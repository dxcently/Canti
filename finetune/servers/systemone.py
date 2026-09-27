"""Local stand-in for TypeSafe's Jev: POST /v1/systemone with the same wire format, served by local models.

The Android app's HTTP decider talks to this unchanged, so moving to the real Jev later is a URL + key change.

Models (the request's "model" field):
  decider-4b   Mapika/decider-4b, a general open Jev-like, NOT trained on VOX: the honest proxy for Jev.
               Up to 255 options.
  jevk5        alibiserikbay/JevK5, also general. At most 16 options (its one-pass readout); more is a 422.
  vox-jevlike  our fine-tuned VOX student (jevlike scorer). It learned the VOX policy from labels, so it ignores
               `instructions` and option descriptions: it sees the state and the option texts only.
Only `choice` questions are served; `score` and `noul` return 422 (VOX doesn't use them yet).

Run (from finetune/):
  nix shell nixpkgs#python313 nixpkgs#uv nixpkgs#gcc -c bash -c 'source ./env.sh; source .venv/bin/activate;
      VOX_DEVICE=cpu VOX_JEVLIKE_CKPT=runs/sweep-v5-e5-small-e3.pt uvicorn servers.systemone:app --port 8765'
VOX_DEVICE=cpu hides flash-linear-attention (GPU-only Triton kernels) so Qwen3.5 uses torch's reference kernels.
VOX_THREADS (default 8) caps torch CPU threads. Models load on first use; VOX_PRELOAD=decider-4b,vox-jevlike loads them at start-up.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
import time
from pathlib import Path

DEVICE = os.environ.get("VOX_DEVICE", "cuda")
if DEVICE == "cpu":
    sys.modules["fla"] = None  # must happen before transformers is imported

import torch  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from pydantic import BaseModel  # noqa: E402

# One request at a time: a few threads beat all cores, and leave the rest for training jobs on the same box.
torch.set_num_threads(int(os.environ.get("VOX_THREADS", "8")))

FINETUNE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FINETUNE))
from teachers.scorer import jev_confidence  # noqa: E402

app = FastAPI(title="vox-systemone")
_lock = threading.Lock()  # one model call at a time (CPU threads / GPU memory are shared)
_models: dict[str, object] = {}


class Request(BaseModel):
    state: str | dict | list
    model: str = "decider-4b"
    questions: dict[str, dict]


class TeacherModel:
    def __init__(self, name: str) -> None:
        from teachers import scorer

        if DEVICE == "cpu":
            # scorer.load() applies the ROCm/Triton patches, which import fla; on the CPU build the teacher directly
            from huggingface_hub import snapshot_download

            source = os.environ.get(f"VOX_{name.upper()}_PATH") or snapshot_download(scorer.REPOS[name], revision=scorer.REVISIONS[name])
            cls = {"decider4b": scorer.DeciderTeacher, "jevk5": scorer.JevK5Teacher}[name]
            self.t = cls(source, device="cpu", dtype=torch.bfloat16)
        else:
            self.t = scorer.load(name, device=DEVICE)
        self.name = name

    def choice(self, state: str, q: dict) -> tuple[list[float], int]:
        if self.name == "jevk5" and len(q["criteria"]) > 16:
            raise HTTPException(422, f"jevk5 reads at most 16 options in one pass; got {len(q['criteria'])}")
        enc = self.t.encode(state, q)
        return self.t.probs([enc])[0], len(enc.ids)


class JevlikeModel:
    def __init__(self) -> None:
        ckpt = os.environ.get("VOX_JEVLIKE_CKPT")
        if not ckpt:
            raise HTTPException(503, "vox-jevlike needs VOX_JEVLIKE_CKPT=<checkpoint .pt>")
        spec = importlib.util.spec_from_file_location("jevlike_train", FINETUNE / "students/jevlike/train.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        payload = torch.load(ckpt, map_location="cpu", weights_only=False)
        self.model, self.collate = mod.build(payload["config"], torch.device(DEVICE))
        self.model.load_state_dict(payload["state_dict"], strict=False)
        self.model.eval()
        self.ckpt = ckpt

    @torch.inference_mode()
    def choice(self, state: str, q: dict) -> tuple[list[float], int]:
        from jevlike.data import validate

        options = list(q["criteria"])
        batch = self.collate([validate({"context": state, "options": options, "label": 0})])
        batch = {k: v.to(DEVICE) for k, v in batch.items()}
        with torch.autocast("cuda", dtype=torch.bfloat16, enabled=DEVICE == "cuda"):
            probs = self.model(batch).float().softmax(-1)[0][: len(options)]
        return probs.tolist(), int(batch["context_mask"].sum())


def get_model(name: str):
    if name not in _models:
        if name == "decider-4b":
            _models[name] = TeacherModel("decider4b")
        elif name == "jevk5":
            _models[name] = TeacherModel("jevk5")
        elif name == "vox-jevlike":
            _models[name] = JevlikeModel()
        else:
            raise HTTPException(404, f"unknown model {name!r}; have decider-4b, jevk5, vox-jevlike")
    return _models[name]


@app.post("/v1/systemone")
def systemone(req: Request) -> dict:
    state = req.state if isinstance(req.state, str) else json.dumps(req.state, ensure_ascii=False)
    t0 = time.perf_counter()
    answers, tokens = {}, 0
    with _lock:
        model = get_model(req.model)
        for qid, q in req.questions.items():
            if q.get("type") != "choice":
                raise HTTPException(422, f"question {qid!r}: only 'choice' is served locally, got {q.get('type')!r}")
            crit = q.get("criteria") or {}
            if len(crit) < 2:
                raise HTTPException(422, f"question {qid!r}: a choice needs at least 2 criteria")
            q = {"type": "choice", "instructions": q.get("instructions", ""), "criteria": crit}
            probs, n_tok = model.choice(state, q)
            tokens += n_tok
            opts = list(crit)
            best = max(range(len(opts)), key=probs.__getitem__)
            answers[qid] = {"type": "choice", "choice": opts[best],
                            "probabilities": {o: round(p, 6) for o, p in zip(opts, probs)},
                            "confidence": round(jev_confidence(probs), 6)}
    return {"model": req.model, "answers": answers,
            "usage": {"input_tokens": tokens}, "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}


def _option_format() -> str:
    """Target option text format the served target model was trained on (the app's OptionFormat.kt keys on this).
    VOX_VERDICT_RUN=<verdict run dir> reports that run's student.json "option_format"; otherwise, and for every model
    served here today (all trained on v1 text), "v1". Only a model trained on v2 text may ever report "v2"."""
    run = os.environ.get("VOX_VERDICT_RUN")
    if not run:
        return "v1"
    try:
        return "v2" if json.loads((Path(run) / "student.json").read_text()).get("option_format") == "v2" else "v1"
    except (OSError, ValueError):
        return "v1"


@app.get("/health")
def health() -> dict:
    return {"device": DEVICE, "loaded": sorted(_models), "jevlike_ckpt": os.environ.get("VOX_JEVLIKE_CKPT"),
            "option_format": _option_format()}


for _name in filter(None, os.environ.get("VOX_PRELOAD", "").split(",")):
    get_model(_name.strip())
