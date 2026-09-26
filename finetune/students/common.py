"""Shared helpers for the VOX student models (Kev, Verdict): data, teacher soft labels, loss, metrics, output.

Output format (same as the teachers): one JSON object per line, {"id": ..., "probs": [p_0, ..., p_{K-1}]} with the
probabilities aligned with that row's `options`. Students add optional extra keys (latency) that evaluators ignore.
"""
from __future__ import annotations

import json
import math
import os
import time
from collections import defaultdict
from pathlib import Path

FINETUNE = Path(__file__).resolve().parents[1]
# VOX_DATA=data/v5 picks the data version; split names AND the policy text come from it, so they can't mismatch.
DATA = FINETUNE / os.environ.get("VOX_DATA", "data/v0")
POLICY_PATH = DATA / "policy.txt"


def data_path(split_or_path: str) -> Path:
    """'train' -> $VOX_DATA/train.jsonl; anything with a slash or .jsonl is taken as a path."""
    p = Path(split_or_path)
    if p.suffix == ".jsonl" or "/" in split_or_path:
        return p
    return DATA / f"{split_or_path}.jsonl"


def split_name(split_or_path: str) -> str:
    return Path(split_or_path).name.removesuffix(".jsonl")


def load_rows(split_or_path: str, limit: int | None = None) -> list[dict]:
    """The first `limit` rows (deterministic; the generator already shuffles rows)."""
    rows = []
    with data_path(split_or_path).open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
                if limit and len(rows) >= limit:
                    break
    for r in rows:
        if not 0 <= r["label"] < len(r["options"]):
            raise ValueError(f"{r['id']}: label {r['label']} outside {len(r['options'])} options")
    return rows


def policy_text() -> str:
    return POLICY_PATH.read_text(encoding="utf-8").strip()


def load_teacher(path: str | None, rows: list[dict]) -> dict[str, list[float]]:
    """{id: probs} from a teachers/<split>.<teacher>.jsonl file, checked against the rows it will be used with.
    Rows with no teacher entry train on the hard label only. A length mismatch is an error (misaligned options)."""
    if not path:
        return {}
    by_id = {r["id"]: r for r in rows}
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            t = json.loads(line)
            r = by_id.get(t["id"])
            if r is None:
                continue
            p = [max(0.0, float(x)) for x in t["probs"]]
            if len(p) != len(r["options"]):
                raise ValueError(f"teacher {path}: {t['id']} has {len(p)} probs for {len(r['options'])} options")
            s = sum(p)
            if s <= 0 or not math.isfinite(s):
                continue
            out[t["id"]] = [x / s for x in p]
    print(f"teacher probs: {len(out)}/{len(rows)} training rows covered from {path}", flush=True)
    return out


def mixed_loss(logits, label: int, teacher: list[float] | None, alpha: float, tau: float = 1.0):
    """(1 - alpha) * CE(label) + alpha * tau^2 * KL(teacher || softmax(logits / tau)). No teacher row -> CE only.
    `logits` is a 1-D torch tensor over this row's options."""
    import torch
    import torch.nn.functional as F

    z = logits.float()
    ce = F.cross_entropy(z[None], torch.tensor([label], device=z.device))
    if teacher is None or alpha <= 0:
        return ce
    t = torch.tensor(teacher, device=z.device, dtype=torch.float32).clamp_min(1e-8)
    t = t / t.sum()
    kl = F.kl_div(F.log_softmax(z / tau, -1), t, reduction="sum") * tau * tau
    return (1 - alpha) * ce + alpha * kl


# ---------------------------------------------------------------------------------------------------------- metrics

def ece(conf: list[float], correct: list[bool], bins: int = 15) -> float:
    """Expected calibration error on the top-1 probability, equal-width bins (the Jev/Decision-Index convention)."""
    n = len(conf)
    if not n:
        return float("nan")
    tot = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, c in enumerate(conf) if (lo < c <= hi) or (b == 0 and c == 0)]
        if idx:
            acc = sum(correct[i] for i in idx) / len(idx)
            avg = sum(conf[i] for i in idx) / len(idx)
            tot += len(idx) / n * abs(acc - avg)
    return tot


def score(rows: list[dict], probs: dict[str, list[float]]) -> dict:
    """Accuracy overall and by kind, ECE, NLL, Brier over the rows that have predictions."""
    conf, correct, nll, brier = [], [], [], []
    by_kind = defaultdict(lambda: [0, 0])
    for r in rows:
        p = probs.get(r["id"])
        if p is None:
            continue
        k = max(range(len(p)), key=p.__getitem__)
        ok = k == r["label"]
        conf.append(p[k]); correct.append(ok)
        nll.append(-math.log(max(p[r["label"]], 1e-12)))
        brier.append(sum((pi - (i == r["label"])) ** 2 for i, pi in enumerate(p)))
        by_kind[r["kind"]][0] += ok; by_kind[r["kind"]][1] += 1
    n = len(conf)
    return {
        "n": n,
        "accuracy": round(sum(correct) / n, 4) if n else None,
        "ece": round(ece(conf, correct), 4),
        "nll": round(sum(nll) / n, 4) if n else None,
        "brier": round(sum(brier) / n, 4) if n else None,
        "by_kind": {k: {"acc": round(a / t, 3), "n": t} for k, (a, t) in sorted(by_kind.items())},
    }


def fit_temperature(logits_list, labels: list[int]) -> float:
    """One temperature minimising NLL on held-out rows (grid + golden refinement; no torch needed)."""
    def nll(T):
        s = 0.0
        for z, y in zip(logits_list, labels):
            m = max(z)
            lse =math.log(sum(math.exp((v - m) / T) for v in z)) + m / T
            s -= z[y] / T - lse
        return s / max(1, len(labels))
    grid = [0.25 * 1.15 ** i for i in range(40)]
    best = min(grid, key=nll)
    lo, hi = best / 1.15, best * 1.15
    for _ in range(40):
        a, b = lo + (hi - lo) / 3, hi - (hi - lo) / 3
        if nll(a) < nll(b):
            hi = b
        else:
            lo = a
    return round((lo + hi) / 2, 4)


def softmax(z: list[float], T: float = 1.0) -> list[float]:
    m = max(z)
    e = [math.exp((v - m) / T) for v in z]
    s = sum(e)
    return [v / s for v in e]


# ------------------------------------------------------------------------------------------------------------ output

def write_preds(path: Path, rows: list[dict], probs: dict[str, list[float]], extra: dict[str, dict] | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            if r["id"] in probs:
                rec = {"id": r["id"], "probs": [round(float(x), 6) for x in probs[r["id"]]]}
                if extra and r["id"] in extra:
                    rec.update(extra[r["id"]])
                f.write(json.dumps(rec) + "\n")


def percentiles(xs: list[float]) -> dict:
    if not xs:
        return {}
    s = sorted(xs)
    q = lambda p: s[min(len(s) - 1, int(round(p * (len(s) - 1))))]
    return {"n": len(s), "mean_ms": round(sum(s) / len(s), 2), "p50_ms": round(q(0.5), 2), "p90_ms": round(q(0.9), 2), "p99_ms": round(q(0.99), 2)}


class Timer:
    def __init__(self, sync=None):
        self.sync = sync

    def __enter__(self):
        if self.sync:
            self.sync()
        self.t = time.perf_counter()
        return self

    def __exit__(self, *exc):
        if self.sync:
            self.sync()
        self.ms = (time.perf_counter() - self.t) * 1000
