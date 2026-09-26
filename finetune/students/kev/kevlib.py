"""Glue between VOX rows and Kev (third_party/kev): record format, model build/load, batched logits.

A VOX row becomes one Kev Choice question:
    state        = row["context"]                       (the multi-line gesture/app/rules text)
    instructions = data/v0/policy.txt                   (the decision rule, same for every row)
    options      = row["options"]                        (option texts in the row's order, no descriptions)
so the pointer head scores each option's </opt> hidden state against <decide>, and probs come back aligned with
row["options"]. This is exactly the shape kev.serve builds from a /v1/systemone "choice" request whose criteria are
{option_text: null}, so a checkpoint trained here serves unchanged with `python -m kev.serve --run <run dir>`.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEV_REPO = HERE.parents[1] / "third_party" / "kev"
sys.path.insert(0, str(HERE.parent))           # students/common.py
sys.path.insert(0, str(KEV_REPO))              # the kev package


def block_fla():
    """transformers binds Qwen3.5's Gated DeltaNet to flash-linear-attention (Triton, GPU only) at import time when fla is
    importable, and never checks the tensor device. A CPU run must hide fla BEFORE transformers is imported so the torch
    reference kernels are used instead."""
    sys.modules["fla"] = None


if os.environ.get("VOX_NO_FLA") == "1":
    block_fla()

import torch  # noqa: E402

# gfx1151 / ROCm 7.13: MIOpen has no working solver for the depthwise causal conv1d in Qwen3.5's DeltaNet layers
# ("miopenStatusUnknownError", fp32 and bf16). With MIOpen off, torch's native conv kernel runs and is correct.
torch.backends.cudnn.enabled = False


def _patch_triton_bench():
    """gfx1151 / ROCm 7.13: HIP event timing returns 0 ms, so Triton's autotuner (used by the fla DeltaNet kernels)
    divides by zero in do_bench. Replace it with a wall-clock benchmark (synchronize + perf_counter). Needs a C compiler
    on PATH for Triton's HIP launcher (run inside `nix shell ... nixpkgs#gcc` and export CC=gcc)."""
    try:
        import triton.testing as tt
    except Exception:
        return
    import time as _time

    def do_bench(fn, warmup=25, rep=100, grad_to_none=None, quantiles=None, return_mode="mean"):
        fn(); torch.cuda.synchronize()
        ts = []
        for _ in range(5):
            t = _time.perf_counter(); fn(); torch.cuda.synchronize(); ts.append((_time.perf_counter() - t) * 1000)
        ts.sort()
        med = ts[len(ts) // 2]
        if quantiles:
            return [ts[min(len(ts) - 1, int(q * len(ts)))] for q in quantiles]
        return {"min": ts[0], "max": ts[-1], "all": ts}.get(return_mode, med)

    tt.do_bench = do_bench


if os.environ.get("VOX_NO_FLA") != "1":
    _patch_triton_bench()

# the state is VOX's context (<= ~350 tokens); raise Kev's training limits so nothing is ever truncated
MAX_STATE, MAX_BRANCH = 1024, 2048
DEFAULT_BASE = "Qwen/Qwen3.5-0.8B-Base"
DEFAULT_REVISION = "dc7cdfe2ee4154fa7e30f5b51ca41bfa40174e68"   # the revision jaredpalmer/kev-0.8b was trained on
DEFAULT_INIT = "jaredpalmer/kev-0.8b"


def to_record(row: dict, policy: str) -> dict:
    return {"state": row["context"], "questions": [{"instr": policy, "options": list(row["options"]), "label": int(row["label"])}]}


def encode_row(model, tok, row: dict, policy: str) -> dict:
    return model.encode(tok, to_record(row, policy), max_state=MAX_STATE, max_branch=MAX_BRANCH, strict=True)


def logits_batch(model, encs):
    """-> list of 1-D fp32 logits (raw, before the checkpoint temperature), one per encoded row. The row form runs
    state + question as one causal row (a single forward pass per row; hybrid Qwen3.5 backbones always use it)."""
    head_T = model.head.temperature
    model.head.temperature = 1.0
    try:
        out = model.forward_batch(encs)
    finally:
        model.head.temperature = head_T
    return [q[0].float() for q in out]
