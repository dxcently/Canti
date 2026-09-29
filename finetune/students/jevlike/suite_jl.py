"""Score jevlike checkpoints on Verdict's real-screen suite (students/verdict/suite.py), so jevlike and Verdict share
one table: same sets, same screen-cluster bootstrap CIs, same paired tests. Verdict's own code is reused unchanged;
this wrapper only teaches it to load a jevlike `.pt` (T = 1, no temperature fit) next to a Verdict run directory.

    python students/jevlike/suite_jl.py --run runs/jl7-J1.pt --champion students/verdict/runs/verdict-bi-real-v1d \
        --build data/real-targets-v2/b4a --name jl7-J1 --no-gate [suite.py args...]
    python students/jevlike/suite_jl.py --latency runs/a.pt students/verdict/runs/verdict-bi-real-v1d [--n 200] [--cpu] [--name tag] [--jl-cache]
    python students/jevlike/suite_jl.py --v5 runs/a.pt ... --name tag      (jevlike's own v5 phrase test)

Cached predictions follow suite.py: public sets under preds/real-targets-v2/suite/, Z Flip sets under
data/real-targets-v2/zflip/preds/suite/ (local only). Aggregates only are printed.
"""
from __future__ import annotations

import os
import hashlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / "verdict"))
sys.path.insert(0, str(HERE))

import suite  # noqa: E402  (students/verdict/suite.py; imports vlib, sets ROCm env)
import vlib  # noqa: E402
import torch  # noqa: E402
from torch.utils.data import DataLoader  # noqa: E402

import train as jl  # noqa: E402  (students/jevlike/train.py)


def is_jl(run: str) -> bool:
    return str(run).endswith(".pt")


class JLModel:
    """jevlike checkpoint with the suite's Predictor interface: logits(rows) at T = 1; `temperature` is the checkpoint's
    fitted T (config "temperature", train.py --fit-temperature) or 1 for checkpoints without one."""

    temperature = 1.0

    def __init__(self, ckpt: str, device: str):
        payload = torch.load(ckpt, map_location="cpu", weights_only=False)
        self.cfg = payload["config"]
        self.temperature = float(self.cfg.get("temperature", 1.0))
        self.device = torch.device(device)
        self.model, self.collate = jl.build(self.cfg, self.device)
        missing = self.model.load_state_dict(payload["state_dict"], strict=False)
        assert not missing.unexpected_keys, missing.unexpected_keys
        self.model.eval()

    @torch.no_grad()
    def logits(self, rows, bs: int = 64, cache_options: bool = False):
        if cache_options:   # jl9: option vectors cached by option text (train.OptionCache); context encoded per call
            if not hasattr(self, "cache"):
                self.cache = jl.OptionCache(self.model, self.collate)
            out = []
            for i in range(0, len(rows), bs):
                with torch.autocast("cuda", dtype=torch.bfloat16, enabled=self.device.type == "cuda"):
                    out += [z.cpu() for z in self.cache.logits(rows[i:i + bs], self.device)]
            return out
        out = []
        for i in range(0, len(rows), bs):
            ch = rows[i:i + bs]
            b = self.collate([jl.validate(r) for r in ch])
            b = {k: v.to(self.device) for k, v in b.items()}
            with torch.autocast("cuda", dtype=torch.bfloat16, enabled=self.device.type == "cuda"):
                z = self.model(b).float()
            out += [z[j, :len(r["options"])].cpu() for j, r in enumerate(ch)]
        return out


class Predictor(suite.Predictor):
    def get(self, run):
        if run not in self.models:
            self.models[run] = JLModel(run, self.device) if is_jl(run) else vlib.Student(run, "bi", device=self.device).eval()
        return self.models[run]

    def logits(self, run, rows):
        if not is_jl(run):
            return super().logits(run, rows)
        cache = os.environ.get("JL_CACHE") == "1"   # jl11 (opt-in): OptionCache (cache_options=True)
        return {r["id"]: z.tolist() for r, z in zip(rows, self.get(run).logits(rows, cache_options=cache))}


_model_id, _run_format = suite.model_id, suite.run_format


def model_id(run: str) -> str:
    if is_jl(run):
        st = Path(run).stat()
        return hashlib.sha1(f"{Path(run).resolve()}:{st.st_size}:{st.st_mtime_ns}".encode()).hexdigest()[:10]
    return _model_id(run)


def run_format(run: str) -> str:
    # jl10: a .pt stores no option format; JL_FORMAT=v2i (opt-in) scores jevlike checkpoints trained on the v2i text on
    # the v2i build's rows (approximated text included: it is the text they were trained on). Default v1 as before.
    return os.environ.get("JL_FORMAT", "v1") if is_jl(run) else _run_format(run)


_get_preds = suite.get_preds


def get_preds(pr, run, *a, **k):
    """On a cache hit suite.py reads <run>/student.json for T; a jevlike .pt has none, so register it (with the
    checkpoint's stored T, default 1) first."""
    if is_jl(run) and run not in pr.models:
        ph = JLModel.__new__(JLModel)   # temperature only; get() is never needed after a cache hit
        ph.temperature = float(torch.load(run, map_location="cpu", weights_only=False)["config"].get("temperature", 1.0))
        pr.models[run] = ph
    return _get_preds(pr, run, *a, **k)


def _get(self, run, _orig=Predictor.get):
    m = self.models.get(run)
    if m is not None and is_jl(run) and not hasattr(m, "model"):
        del self.models[run]   # placeholder from get_preds: load for real
    return _orig(self, run)


Predictor.get = _get
suite.Predictor, suite.model_id, suite.run_format, suite.get_preds = Predictor, model_id, run_format, get_preds


# ------------------------------------------------------------------------------------------------ latency (batch 1)

def latency(runs: list[str], n: int, device: str, jl_cache: bool = False):
    """End-to-end batch-1 latency (tokenise + encode + score) on the first n dev-test rows, after 10 warm-up rows.
    Verdict: option embeddings cached (its deployment mode). jevlike: context AND options encoded every call, or (jl9,
    jl_cache) option vectors cached by text like Verdict (train.OptionCache). The warm-up rows fill part of the cache;
    later rows hit it only for options already seen (same screen), as on the phone."""
    rows = suite.jl(FT / "data/real-targets-v2/b4a/test_real.jsonl")[:n]
    res = {}
    for run in runs:
        pr = Predictor(device)
        m = pr.get(run)
        sync = torch.cuda.synchronize if device.startswith("cuda") else (lambda: None)
        ts = []
        ac = torch.autocast("cuda", dtype=torch.bfloat16, enabled=device.startswith("cuda"))
        with torch.no_grad(), ac:
            for k, r in enumerate(rows[:10] + rows):
                sync(); t = time.perf_counter()
                m.logits([r], cache_options=jl_cache) if is_jl(run) else m.logits([r], cache_options=True)
                sync()
                if k >= 10:
                    ts.append((time.perf_counter() - t) * 1000)
        ts.sort()
        res[run] = {"device": device, "n": len(ts), "p50_ms": round(ts[len(ts) // 2], 2), "p90_ms": round(ts[int(0.9 * (len(ts) - 1))], 2),
                    "mean_ms": round(sum(ts) / len(ts), 2), **({"jl_option_cache": jl_cache} if is_jl(run) else {})}
        if is_jl(run) and jl_cache:
            res[run]["cache_hits"], res[run]["cache_misses"] = m.cache.hits, m.cache.misses
        print(json.dumps({"run": run, **res[run]}), flush=True)
        del pr, m
        torch.cuda.empty_cache() if device.startswith("cuda") else None
    return res


# ------------------------------------------------------------------------------------------------ v5 phrase test

def v5(runs: list[str], device: str, tag: str):
    """jevlike's own v5 phrase decisions: data/v5 test_unseen_phrasing (kinds phrase + screen_phrase, the 314 rows of
    reports/ollama_vs_students.md) and the whole file; also test_iid phrase kinds."""
    from collections import defaultdict
    out = {}
    for split in ("test_unseen_phrasing", "test_iid"):
        rows = suite.jl(FT / f"data/v5/{split}.jsonl")
        for run in runs:
            pr = Predictor(device)
            z = pr.logits(run, rows) if is_jl(run) else _vlogits(pr, run, rows)
            by = defaultdict(lambda: [0, 0])
            for r in rows:
                v = z[r["id"]]
                ok = max(range(len(v)), key=v.__getitem__) == r["label"]
                by[r["kind"]][0] += ok; by[r["kind"]][1] += 1
                g = "phrase+screen_phrase" if r["kind"] in ("phrase", "screen_phrase") else "other"
                by[g][0] += ok; by[g][1] += 1
                by["all"][0] += ok; by["all"][1] += 1
            out.setdefault(split, {})[run] = {k: {"acc": round(a / t, 4), "n": t} for k, (a, t) in sorted(by.items())}
            print(json.dumps({"split": split, "run": run, "phrase+screen_phrase": out[split][run]["phrase+screen_phrase"],
                              "all": out[split][run]["all"]}), flush=True)
            del pr
    p = FT / "sweeps" / "eval" / f"v5phrase.{tag}.json"
    p.write_text(json.dumps(out, indent=1))
    print(f"wrote {p}")


def _vlogits(pr, run, rows):
    return pr.logits(run, rows)


if __name__ == "__main__":
    argv = sys.argv[1:]
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    if argv and argv[0] == "--latency":
        n = 200
        if "--n" in argv:
            i = argv.index("--n"); n = int(argv[i + 1]); argv = argv[:i] + argv[i + 2:]
        tag = "jl7"
        if "--name" in argv:
            i = argv.index("--name"); tag = argv[i + 1]; argv = argv[:i] + argv[i + 2:]
        if "--cpu" in argv:
            argv.remove("--cpu"); dev = "cpu"; torch.set_num_threads(4)
        jl_cache = "--jl-cache" in argv
        if jl_cache:
            argv.remove("--jl-cache")
        res = latency(argv[1:], n, dev, jl_cache)
        (FT / "sweeps" / "eval" / f"latency.{tag}.{dev}.json").write_text(json.dumps(res, indent=1))
    elif argv and argv[0] == "--v5":
        tag = "jl7"
        if "--name" in argv:
            i = argv.index("--name"); tag = argv[i + 1]; argv = argv[:i] + argv[i + 2:]
        v5(argv[1:], dev, tag)
    else:
        suite.main()
