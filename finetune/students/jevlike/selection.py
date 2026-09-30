"""Checkpoint-selection comparison for students/jevlike/train.py.

Kept free of torch/transformers imports so the tie rule is unit-testable without a GPU.
"""

from __future__ import annotations


def selection_improves(m: dict, best: dict, metric: str, tie_later: bool = False) -> bool:
    """True if epoch metric `m` should replace the current `best`.

    metric is one of train.py's --select choices: "acc" (higher is better) or
    "nll"/"nll_t" (lower is better). On an exact tie the earliest epoch is kept
    unless tie_later is set, in which case the later epoch wins.
    """
    if metric == "acc":
        better = m["acc"] > best["acc"]
        tied = m["acc"] == best["acc"]
    else:
        key = "nll_t" if metric == "nll_t" else "nll"
        better = m[key] < best[key]
        tied = m[key] == best[key]
    return better or (tie_later and tied)
