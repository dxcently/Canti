"""Scoring for Verdict on real screens: point metrics, screen-cluster bootstrap CIs, paired tests between two models on
the same rows, novel-phrase accuracy. Pure python (no torch). Aggregates only; never prints row content.

A "cluster" is a screen (rows on one screen share options and a labeller); synthetic rows have no screen_id and are
their own cluster. Paired tests resample the SAME clusters for both models.
"""
from __future__ import annotations

import math
import random
import re
from collections import defaultdict

_NORM = re.compile(r"[^a-z0-9 ]")


def phrase_key(p: str) -> str:
    return _NORM.sub("", (p or "").lower()).strip()


def top(p):
    return max(range(len(p)), key=p.__getitem__)


def records(gold: list[dict], probs: dict[str, list[float]], train_phrases: set[str] | None = None) -> list[dict]:
    """Per-row outcome records for rows that have predictions."""
    out = []
    for g in gold:
        p = probs.get(g["id"])
        if p is None:
            continue
        t, ni = top(p), len(g["options"]) - 1
        acc_set = g.get("acceptable") or [g["label"]]
        rec = {"cl": g.get("screen_id") or g["id"], "hit": t == g["label"], "hit_a": t in acc_set, "gn": g["label"] == ni,
               "pn": t == ni, "conf": p[t], "nll": -math.log(max(p[g["label"]], 1e-12)), "kind": g.get("kind", ""),
               "app": g.get("app", ""), "p_none": p[ni]}
        if train_phrases is not None and "phrase" in g:
            rec["novel"] = phrase_key(g["phrase"]) not in train_phrases
        out.append(rec)
    return out


def ece(conf, ok, bins=15):
    n = len(conf)
    tot = 0.0
    for b in range(bins):
        idx = [i for i, c in enumerate(conf) if b / bins < c <= (b + 1) / bins or (b == 0 and c == 0)]
        if idx:
            tot += len(idx) / n * abs(sum(ok[i] for i in idx) / len(idx) - sum(conf[i] for i in idx) / len(idx))
    return tot


def auroc(pos: list[float], neg: list[float]) -> float:
    """P(score of a positive > score of a negative), ties half. pos = p_none on gold-none rows, neg = on target rows."""
    if not pos or not neg:
        return float("nan")
    allv = sorted([(v, 1) for v in pos] + [(v, 0) for v in neg])
    rank, i, rs = 1, 0, 0.0
    while i < len(allv):
        j = i
        while j < len(allv) and allv[j][0] == allv[i][0]:
            j += 1
        r = (rank + rank + (j - i) - 1) / 2
        rs += r * sum(1 for k in range(i, j) if allv[k][1])
        rank += j - i
        i = j
    return (rs - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def metrics(recs: list[dict]) -> dict:
    n = len(recs)
    if not n:
        return {"n": 0}
    gn = [r for r in recs if r["gn"]]
    act = [r for r in recs if not r["gn"]]
    nov = [r for r in recs if r.get("novel")]
    m = {"n": n, "acc": sum(r["hit"] for r in recs) / n, "acc_acceptable": sum(r["hit_a"] for r in recs) / n,
         "none_recall": sum(r["pn"] for r in gn) / len(gn) if gn else float("nan"),
         "false_none": sum(r["pn"] for r in act) / len(act) if act else float("nan"),
         "target_acc": sum(r["hit"] for r in act) / len(act) if act else float("nan"),
         "nll": sum(r["nll"] for r in recs) / n, "n_none": len(gn),
         "novel_acc": sum(r["hit"] for r in nov) / len(nov) if nov else float("nan"), "n_novel": len(nov)}
    return m


def full_metrics(recs: list[dict]) -> dict:
    m = metrics(recs)
    if not recs:
        return m
    m["ece"] = ece([r["conf"] for r in recs], [r["hit"] for r in recs])
    m["none_auroc"] = auroc([r["p_none"] for r in recs if r["gn"]], [r["p_none"] for r in recs if not r["gn"]])
    by = defaultdict(list)
    for r in recs:
        by["kind:" + r["kind"]].append(r)
        by["app:" + r["app"]].append(r)
    m["groups"] = {k: {"n": len(v), "acc": round(sum(x["hit"] for x in v) / len(v), 3)} for k, v in sorted(by.items())}
    for t in (0.7, 0.8, 0.9):
        cov = [r for r in recs if r["conf"] >= t]
        taps = [r for r in cov if not r["pn"]]
        m[f"@{t}"] = {"coverage": len(cov) / len(recs), "acc_covered": sum(r["hit_a"] for r in cov) / len(cov) if cov else float("nan"),
                      "wrong_tap_rate": sum(not r["hit_a"] for r in taps) / len(recs),
                      "gold_none_tapped": sum(r["gn"] for r in taps) / max(1, sum(r["gn"] for r in recs))}
    return m


def pct(xs, q):
    xs = sorted(x for x in xs if not (isinstance(x, float) and math.isnan(x)))
    if not xs:
        return float("nan")
    k = (len(xs) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


KEYS = ("acc", "acc_acceptable", "none_recall", "false_none", "target_acc", "novel_acc", "nll")


def _resamples(recs: list[dict], B: int, seed: int):
    by = defaultdict(list)
    for i, r in enumerate(recs):
        by[r["cl"]].append(i)
    cls = list(by)
    rng = random.Random(seed)
    for _ in range(B):
        yield [i for c in (rng.choice(cls) for _ in cls) for i in by[c]]


def bootstrap(recs: list[dict], B: int = 2000, seed: int = 12345) -> dict:
    """{metric: (point, lo95, hi95)} with screen-cluster resampling."""
    pt = metrics(recs)
    bs = [metrics([recs[i] for i in idx]) for idx in _resamples(recs, B, seed)]
    return {k: (pt[k], pct([b[k] for b in bs], .025), pct([b[k] for b in bs], .975)) for k in KEYS}


def paired(a: list[dict], b: list[dict], B: int = 2000, seed: int = 12345) -> dict:
    """a, b: records of two models over the SAME rows in the same order. {metric: (diff a-b, lo, hi, p two-sided)}."""
    assert len(a) == len(b) and all(x["cl"] == y["cl"] for x, y in zip(a, b)), "paired test needs aligned rows"
    pa, pb = metrics(a), metrics(b)
    ds = defaultdict(list)
    for idx in _resamples(a, B, seed):
        ma, mb = metrics([a[i] for i in idx]), metrics([b[i] for i in idx])
        for k in KEYS:
            d = ma[k] - mb[k]
            if not math.isnan(d):
                ds[k].append(d)
    out = {}
    for k in KEYS:
        d = ds[k]
        if not d:
            continue
        p_le, p_ge = sum(v <= 0 for v in d) / len(d), sum(v >= 0 for v in d) / len(d)
        out[k] = (pa[k] - pb[k], pct(d, .025), pct(d, .975), min(1.0, 2 * min(p_le, p_ge)))
    out["discordant"] = (sum(x["hit"] and not y["hit"] for x, y in zip(a, b)), sum(y["hit"] and not x["hit"] for x, y in zip(a, b)))
    return out
