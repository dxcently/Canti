"""Score any model's predictions against code labels, the same way for everyone.

Prediction files are JSONL: {"id": ..., "probs": [... aligned with the row's options ...]}.
Optional per-row "latency_ms" is summarised too.

Usage:
  python -m vox.evaluate data/v0/test_iid.jsonl preds/test_iid.jevk5.jsonl [more.jsonl ...]
  python -m vox.evaluate --markdown ... > report.md
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path


def load(path: str | Path) -> dict[str, dict]:
    return {r["id"]: r for r in map(json.loads, Path(path).read_text().splitlines()) if r}


def ece(confs: list[float], hits: list[bool], bins: int = 10) -> float:
    total, err = len(confs), 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, c in enumerate(confs) if lo < c <= hi or (b == 0 and c == 0)]
        if idx:
            acc = sum(hits[i] for i in idx) / len(idx)
            conf = sum(confs[i] for i in idx) / len(idx)
            err += len(idx) / total * abs(acc - conf)
    return err


def score(gold: dict[str, dict], preds: dict[str, dict], threshold: float | None = None) -> dict:
    """threshold: act only if confidence >= threshold, otherwise fall back to 'none' (abstain)."""
    rows = [(g, preds[i]) for i, g in gold.items() if i in preds]
    by_kind: dict[str, list[bool]] = defaultdict(list)
    confs, hits, nll, lat = [], [], 0.0, []
    false_trigger = actionable_none = missed = actionable = 0
    for g, p in rows:
        probs = p["probs"]
        top = max(range(len(probs)), key=probs.__getitem__)
        conf = probs[top]
        keys = g["option_keys"]
        if threshold is not None and conf < threshold and "none" in keys:
            top = keys.index("none")
        hit = top == g["label"]
        by_kind[g["kind"]].append(hit)
        confs.append(conf)
        hits.append(hit)
        nll -= math.log(max(probs[g["label"]], 1e-9))
        gold_none = keys[g["label"]] == "none"
        pred_none = keys[top] == "none"
        if gold_none:
            actionable_none += 1
            false_trigger += not pred_none
        else:
            actionable += 1
            missed += pred_none
        if "latency_ms" in p:
            lat.append(p["latency_ms"])
    n = len(rows)
    out = {
        "n": n, "coverage": n / max(len(gold), 1),
        "accuracy": sum(hits) / max(n, 1),
        "nll": nll / max(n, 1),
        "ece": ece(confs, hits),
        "false_trigger_rate": false_trigger / max(actionable_none, 1),
        "missed_command_rate": missed / max(actionable, 1),
        "by_kind": {k: round(sum(v) / len(v), 3) for k, v in sorted(by_kind.items())},
    }
    if lat:
        lat.sort()
        out["latency_ms_p50"] = lat[len(lat) // 2]
        out["latency_ms_p95"] = lat[min(len(lat) - 1, int(len(lat) * 0.95))]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("gold")
    ap.add_argument("preds", nargs="+")
    ap.add_argument("--threshold", type=float)
    ap.add_argument("--markdown", action="store_true")
    a = ap.parse_args()
    gold = load(a.gold)
    results = {Path(p).name: score(gold, load(p), a.threshold) for p in a.preds}
    if not a.markdown:
        print(json.dumps(results, indent=2))
        return
    kinds = sorted({k for r in results.values() for k in r["by_kind"]})
    print(f"### {Path(a.gold).name}" + (f" (abstain below {a.threshold})" if a.threshold else ""))
    print("| model | n | acc | ECE | NLL | false trigger | missed cmd | p50 ms | " + " | ".join(kinds) + " |")
    print("|---" * (8 + len(kinds)) + "|")
    for name, r in results.items():
        print(f"| {name} | {r['n']} | {r['accuracy']:.3f} | {r['ece']:.3f} | {r['nll']:.3f} | "
              f"{r['false_trigger_rate']:.3f} | {r['missed_command_rate']:.3f} | {r.get('latency_ms_p50', '')} | "
              + " | ".join(str(r["by_kind"].get(k, "")) for k in kinds) + " |")


if __name__ == "__main__":
    main()
