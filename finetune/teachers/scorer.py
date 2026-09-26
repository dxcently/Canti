"""In-process, batched teacher scorers for VOX: Decider 4B and JevK5 (both Qwen3.5-4B, one forward pass per question).

Each teacher answers one TypeSafe-style `choice` question per row:
    state = row["context"], instructions = policy text, criteria = the row's option texts (no descriptions).
That is the request a `/v1/systemone` client would send; the prompt and readout below are the ones each project's own runtime
builds for that request, reproduced so that many rows can share one padded GPU batch:

  decider-4b  decider.systemone.render_question + decider.prompt.build (plain, state-first layout, options in given order),
              letter logits at the final "Answer: (" token, softmax(logits / T_choice), T_choice = 1.11 from decider_config.json.
  JevK5       jevk5.prompt.decision_options + messages + the Qwen3.5 chat template with thinking off, logits of the letters
              A..P at the last token, softmax(logits / 1.22) from jevk5_config.json. At most 16 options -> one pass.

Batches are right-padded with no attention mask, exactly as both upstream CUDA-graph engines run them: every layer is causal
(full attention and gated delta-net), so padding after the last real token cannot change it. `parity.py` checks this against
the upstream `Decider.system_one` / `JevK5.decide` on real rows.

The linear-attention layers use flash-linear-attention's Triton kernels (gated delta rule and, via teachers.rocm_compat, the
causal conv, whose MIOpen fallback fails on gfx1151).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import torch

TEACHERS = ("decider4b", "jevk5")
REPOS = {"decider4b": "Mapika/decider-4b", "jevk5": "alibiserikbay/JevK5"}
# Pinned model revisions (Hub commit shas at setup time, 2026-09-26) so labels are reproducible.
REVISIONS = {"decider4b": "eb5fbdfc9448473ec25e399882912863afbdb70e", "jevk5": "c4f7fdb3aeab5582336406e78d3bef11bf98833d"}


def question(policy: str, options: list[str], keys: list[str] | None = None) -> dict:
    """The /v1/systemone choice question for one row. keys=None: criteria are the option texts themselves (the default);
    keys given: {key: option text}, the "keyed" variant."""
    if keys is None:
        return {"type": "choice", "instructions": policy, "criteria": {o: None for o in options}}
    return {"type": "choice", "instructions": policy, "criteria": dict(zip(keys, options))}


def jev_confidence(p: list[float]) -> float:
    """TypeSafe's Choice confidence (N * p_max - 1) / (N - 1), clipped to [0, 1]."""
    n = len(p)
    return 1.0 if n <= 1 else min(1.0, max(0.0, (n * max(p) - 1) / (n - 1)))


@dataclass
class Encoded:
    ids: list[int]
    n: int  # number of options, i.e. how many label logits to read


class Teacher:
    name: str
    temperature: float

    def __init__(self, source: str, device: str = "cuda", dtype=torch.bfloat16) -> None:
        import transformers

        cfg = transformers.AutoConfig.from_pretrained(source)
        cfg = cfg.get_text_config() if hasattr(cfg, "get_text_config") else cfg
        self.tok = transformers.AutoTokenizer.from_pretrained(source)
        # Loaded in CPU RAM first. The 248k x 2560 embedding (tied to lm_head, 1.27 GB bf16) stays there: token lookups
        # happen on the CPU and only the embedded rows go to the GPU, and the readout needs just the K label rows of
        # lm_head (self.W). Same numbers, about 1.3 GB less VRAM (the GPU is shared with student training).
        model = transformers.Qwen3_5ForCausalLM.from_pretrained(source, config=cfg, dtype=dtype, device_map={"": "cpu"}).eval()
        self.device = device
        self.pad = self.tok.pad_token_id if self.tok.pad_token_id is not None else 0
        self.W = model.lm_head.weight[self.label_ids()].detach().clone().contiguous().to(device)  # [K, H]
        self.embed = model.model.embed_tokens
        model.lm_head = torch.nn.Identity()
        model.model.embed_tokens = torch.nn.Identity()  # never called: forward gets inputs_embeds
        self.model = model.to(device)

    # -- per teacher --------------------------------------------------------------------------------------------------------
    def label_ids(self) -> list[int]:
        raise NotImplementedError

    def encode(self, state: str, q: dict) -> Encoded:
        raise NotImplementedError

    # -- shared ---------------------------------------------------------------------------------------------------------------
    @torch.inference_mode()
    def logits(self, batch: list[Encoded]) -> list[torch.Tensor]:
        T = max(len(e.ids) for e in batch)
        ids = torch.full((len(batch), T), self.pad, dtype=torch.long)
        for i, e in enumerate(batch):
            ids[i, : len(e.ids)] = torch.tensor(e.ids)
        emb = self.embed(ids).to(self.device, non_blocking=True)
        last = torch.tensor([len(e.ids) - 1 for e in batch], device=self.device)
        h = self.model.model(inputs_embeds=emb, use_cache=False).last_hidden_state
        lg = (h[torch.arange(len(batch), device=self.device), last] @ self.W.T).float().cpu()
        return [lg[i, : e.n] for i, e in enumerate(batch)]

    def probs(self, batch: list[Encoded]) -> list[list[float]]:
        return [torch.softmax(lg / self.temperature, -1).tolist() for lg in self.logits(batch)]


class DeciderTeacher(Teacher):
    name = "decider4b"

    def __init__(self, source: str, **kw) -> None:
        from decider.prompt import load_decider_config, resolve_layout

        cfg = load_decider_config(source)
        if resolve_layout(cfg) != "plain" or cfg.get("schema_first") or cfg.get("neutralize_none"):
            raise ValueError(f"unexpected decider_config.json for this scorer: {cfg}")
        self.temperature = float((cfg.get("temperature_by_type") or {}).get("choice", cfg.get("temperature", 1.0)))
        super().__init__(source, **kw)

    def label_ids(self) -> list[int]:
        from decider.prompt import MAX_OPTIONS, label_table

        return label_table(self.tok)[1][:MAX_OPTIONS]

    def encode(self, state: str, q: dict) -> Encoded:
        # Decider._system_one_items, one independent choice row, state-first plain layout, options kept in order.
        from decider.infer import Example, Q, _NoShuffle
        from decider.prompt import MAX_OPTIONS, build
        from decider.systemone import render_question, render_state

        rq = render_question(q)
        item = build(Example(render_state(state), [Q(rq["question"], list(rq["options"]), 0)]), self.tok, _NoShuffle(),
                     max_options=MAX_OPTIONS, max_ctx_tokens=32768, layout="state_first", chat=None)
        assert item["slots"] == [len(item["ids"]) - 1], "the answer slot must be the last token"
        return Encoded(item["ids"], len(rq["options"]))


class JevK5Teacher(Teacher):
    name = "jevk5"

    def __init__(self, source: str, **kw) -> None:
        from jevk5.runtime import _load_config

        cfg = _load_config(source)
        self.temperature = float(cfg.get("temperature", 1.0))
        super().__init__(source, **kw)

    def label_ids(self) -> list[int]:
        from jevk5.prompt import LETTERS

        out = []
        for L in LETTERS:
            t = self.tok.encode(L, add_special_tokens=False)
            assert len(t) == 1, L
            out.append(t[0])
        return out

    def encode(self, state: str, q: dict) -> Encoded:
        # JevK5.probabilities -> read(texts) for <= 16 options (one pass, no knockout).
        from jevk5.prompt import LETTERS, decision_options, messages

        texts = [t for _, t in decision_options(q)]
        if len(texts) > len(LETTERS):
            raise ValueError(f"{len(texts)} options: JevK5 needs its multi-pass knockout readout above {len(LETTERS)}")
        prompt = self.tok.apply_chat_template(messages(state, q["instructions"], texts), tokenize=False,
                                              add_generation_prompt=True, enable_thinking=False)
        return Encoded(self.tok.encode(prompt, add_special_tokens=False), len(texts))


def load(name: str, device: str = "cuda") -> Teacher:
    from huggingface_hub import snapshot_download

    from teachers.rocm_compat import apply

    apply()

    source = os.environ.get(f"VOX_{name.upper()}_PATH") or snapshot_download(REPOS[name], revision=REVISIONS[name])
    cls = {"decider4b": DeciderTeacher, "jevk5": JevK5Teacher}[name]
    return cls(source, device=device)


def check_kernels() -> str:
    """Which gated delta-rule implementation transformers bound: 'fla' (Triton kernels) or 'torch' (slow reference loop)."""
    from transformers.models.qwen3_5 import modeling_qwen3_5 as mq

    impls = [c.cell_contents for c in (mq.torch_chunk_gated_delta_rule.__closure__ or ())
             if callable(c.cell_contents) and hasattr(c.cell_contents, "__module__")]
    return "fla" if any((getattr(f, "__module__", "") or "").startswith("fla") for f in impls) else "torch"


if __name__ == "__main__":  # quick one-row demo: python -m teachers.scorer jevk5
    import sys

    name = sys.argv[1] if len(sys.argv) > 1 else "jevk5"
    policy = (Path(__file__).resolve().parents[1] / "data/v0/policy.txt").read_text().strip()
    row = json.loads(open(Path(__file__).resolve().parents[1] / "data/v0/test_iid.jsonl").readline())
    t = load(name)
    p = t.probs([t.encode(row["context"], question(policy, row["options"]))])[0]
    print(json.dumps({"kernels": check_kernels(), "label": row["label"], "probs": [round(x, 4) for x in p]}))
