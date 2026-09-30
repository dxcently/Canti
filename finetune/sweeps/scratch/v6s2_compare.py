"""Compare v6-e5-small-e3 (seed 7) vs v6-e5-small-e3-s2 (seed 11) on data/v6's three test splits.

For each split: headline metrics side by side, per-kind accuracy deltas, and a paired
per-row comparison (rows right in one seed and wrong in the other) with McNemar's exact
two-sided p (binomial test on the discordant cells).

Usage: .venv/bin/python sweeps/scratch/v6s2_compare.py > sweeps/scratch/v6s2_compare.txt
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

SPLITS = ("test_iid", "test_unseen_phrasing", "test_unseen_apps")
SEED7 = "v6-e5-small-e3"
SEED11 = "v6-e5-small-e3-s2"


def load_jsonl(path: str) -> dict[str, dict]:
    return {r["id"]: r for r in map(json.loads, Path(path).read_text().splitlines()) if r}


def load_eval(name: str, split: str) -> dict:
    key = f"sweep-{name}.{split}.jsonl"
    return json.loads(Path(f"sweeps/eval/{name}.{split}.json").read_text())[key]


def mcnemar_exact_p(b: int, c: int) -> float:
    """Two-sided exact binomial p on the discordant pair counts (n = b + c, p = 0.5)."""
    n = b + c
    if n == 0:
        return 1.0
    lo = min(b, c)
    p = 0.0
    for k in range(lo + 1):
        p += math.comb(n, k)
    p *= 0.5 ** n
    return min(1.0, 2.0 * p)


def per_row(gold: dict, preds: dict) -> dict[str, dict]:
    """Per-row result: correct (bool), predicted key, expected key, kind."""
    out = {}
    for i, g in gold.items():
        if i not in preds:
            continue
        probs = preds[i]["probs"]
        top = max(range(len(probs)), key=probs.__getitem__)
        out[i] = {
            "correct": top == g["label"],
            "pred": g["option_keys"][top],
            "expected": g["option_keys"][g["label"]],
            "kind": g["kind"],
        }
    return out


def kind_accs(rows: dict[str, dict]) -> dict[str, tuple[int, int]]:
    acc = defaultdict(lambda: [0, 0])
    for r in rows.values():
        acc[r["kind"]][0] += r["correct"]
        acc[r["kind"]][1] += 1
    return {k: (v[0], v[1]) for k, v in acc.items()}


def fmt_acc(n_hit: int, n: int) -> str:
    return f"{n_hit}/{n}={n_hit / n:.4f}" if n else "-"


def main() -> None:
    for split in SPLITS:
        gold = load_jsonl(f"data/v6/{split}.jsonl")
        p7 = load_jsonl(f"preds/sweep-{SEED7}.{split}.jsonl")
        p11 = load_jsonl(f"preds/sweep-{SEED11}.{split}.jsonl")
        e7 = load_eval(SEED7, split)
        e11 = load_eval(SEED11, split)
        r7 = per_row(gold, p7)
        r11 = per_row(gold, p11)

        ids = sorted(set(r7) & set(r11))
        b = c = agree_r = agree_w = 0
        disagreements = []  # rows where the two seeds differ
        for i in ids:
            c7, c11 = r7[i]["correct"], r11[i]["correct"]
            if c7 and not c11:
                b += 1
                disagreements.append(i)
            elif not c7 and c11:
                c += 1
                disagreements.append(i)
            elif c7:
                agree_r += 1
            else:
                agree_w += 1
        n = len(ids)
        p = mcnemar_exact_p(b, c)

        print(f"\n=== {split} ===")
        print(f"n rows compared: {n}  (agree right {agree_r}, agree wrong {agree_w}, "
              f"discordant {b}+{c}={b + c})")
        print()
        # headline table
        rows_metrics = [
            ("accuracy", "accuracy", "higher better"),
            ("nll", "nll", "lower better"),
            ("ece", "ece", "lower better"),
            ("false_trigger_rate", "false_trigger_rate", "lower better"),
            ("missed_command_rate", "missed_command_rate", "lower better"),
        ]
        print(f"{'metric':<22}{SEED7:>12}{SEED11:>12}{'delta(11-7)':>14}")
        for label, key, _ in rows_metrics:
            a, bb = e7[key], e11[key]
            print(f"{label:<22}{a:>12.4f}{bb:>12.4f}{bb - a:>+14.4f}")
        print()
        # per-kind table
        k7 = kind_accs(r7)
        k11 = kind_accs(r11)
        kinds = sorted(set(k7) | set(k11))
        print(f"{'kind':<16}{SEED7:>14}{SEED11:>14}{'delta':>10}")
        for k in kinds:
            h7, n7 = k7.get(k, (0, 0))
            h11, n11 = k11.get(k, (0, 0))
            a7 = h7 / n7 if n7 else 0.0
            a11 = h11 / n11 if n11 else 0.0
            print(f"{k:<16}{fmt_acc(h7, n7):>14}{fmt_acc(h11, n11):>14}{a11 - a7:>+10.4f}")
        print()
        print(f"paired (McNemar): seed7-right/seed11-wrong b={b}, seed7-wrong/seed11-right c={c}, "
              f"exact two-sided p={p:.6f}")

    # concrete disagreement rows on test_unseen_apps screen_phrase
    gold = load_jsonl("data/v6/test_unseen_apps.jsonl")
    p7 = load_jsonl(f"preds/sweep-{SEED7}.test_unseen_apps.jsonl")
    p11 = load_jsonl(f"preds/sweep-{SEED11}.test_unseen_apps.jsonl")
    r7 = per_row(gold, p7)
    r11 = per_row(gold, p11)
    print("\n=== disagreements on test_unseen_apps (screen_phrase kind) ===")
    shown = 0
    for i in sorted(set(r7) & set(r11)):
        if r7[i]["kind"] != "screen_phrase":
            continue
        if r7[i]["correct"] == r11[i]["correct"]:
            continue
        shown += 1
        print(f"{i}  kind=screen_phrase  expected={r7[i]['expected']}  "
              f"seed7={r7[i]['pred']}{'  (right)' if r7[i]['correct'] else '  (wrong)'}  "
              f"seed11={r11[i]['pred']}{'  (right)' if r11[i]['correct'] else '  (wrong)'}")
    if shown == 0:
        print("(none)")


if __name__ == "__main__":
    main()
