"""Summarise teacher labels against the code labels: accuracy (overall and per kind), ECE, agreement, and where both
teachers overrule the code label (candidate generator bugs).

    python -m teachers.smoke --splits test_iid,test_unseen_phrasing --limit 300 > teachers/smoke_metrics.md

Also writes teachers/labels/<split>.disagreements.jsonl: every row where at least one teacher's top option differs from the
code label, with both teachers' picks and confidences, for reading by hand.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from vox.evaluate import load, score

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--splits", default="test_iid,test_unseen_phrasing")
    ap.add_argument("--teachers", default="decider4b,jevk5")
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--labels", type=Path, default=ROOT / "teachers/labels")
    ap.add_argument("--suffix", default="", help='e.g. ".keyed" for the keyed-criteria files')
    a = ap.parse_args()
    teachers = a.teachers.split(",")

    for split in a.splits.split(","):
        rows = [json.loads(l) for l in (ROOT / f"data/v0/{split}.jsonl").read_text().splitlines()[: a.limit]]
        gold = {r["id"]: r for r in rows}
        preds = {t: load(a.labels / f"{split}.{t}{a.suffix}.jsonl") for t in teachers}
        metas = {t: json.loads((a.labels / f"{split}.{t}{a.suffix}.meta.json").read_text()) for t in teachers}
        res = {t: score(gold, preds[t]) for t in teachers}
        kinds = sorted(Counter(r["kind"] for r in rows).items())

        print(f"\n### {split} (first {len(rows)} rows)\n")
        print("| teacher | n | rows/s | tokens/s | acc | ECE | NLL | false trigger | missed cmd |")
        print("|---|---|---|---|---|---|---|---|---|")
        for t in teachers:
            r, m = res[t], metas[t]
            print(f"| {t} | {r['n']} | {m['rows_per_s']} | {m['tokens_per_s']} | {r['accuracy']:.3f} | {r['ece']:.3f} | "
                  f"{r['nll']:.3f} | {r['false_trigger_rate']:.3f} | {r['missed_command_rate']:.3f} |")
        print("\n| kind | n | " + " | ".join(teachers) + " | both wrong, same answer |")
        print("|---|---|" + "---|" * len(teachers) + "---|")
        both_same = defaultdict(int)
        for r in rows:
            tops = [preds[t][r["id"]]["top"] for t in teachers]
            if len(set(tops)) == 1 and tops[0] != r["label"]:
                both_same[r["kind"]] += 1
        for k, n in kinds:
            print(f"| {k} | {n} | " + " | ".join(f"{res[t]['by_kind'].get(k, 0):.2f}" for t in teachers) + f" | {both_same[k]} |")

        agree = sum(len({preds[t][r["id"]]["top"] for t in teachers}) == 1 for r in rows)
        print(f"\nTop-choice agreement between {' and '.join(teachers)}: {agree}/{len(rows)} = {agree / len(rows):.3f}")
        print(f"Both teachers wrong with the same answer: {sum(both_same.values())} rows")

        # confusion patterns: gold key -> predicted key, per teacher
        print("\nMost common errors (code label -> teacher pick), per teacher:\n")
        for t in teachers:
            c = Counter()
            for r in rows:
                p = preds[t][r["id"]]["top"]
                if p != r["label"]:
                    c[(r["kind"], r["option_keys"][r["label"]], r["option_keys"][p])] += 1
            print(f"- {t}: " + "; ".join(f"{k}: {g} -> {p} ({n})" for (k, g, p), n in c.most_common(8)))

        out = a.labels / f"{split}.disagreements{a.suffix}.jsonl"
        with out.open("w") as f:
            for r in rows:
                picks = {t: preds[t][r["id"]] for t in teachers}
                if all(p["top"] == r["label"] for p in picks.values()):
                    continue
                f.write(json.dumps({
                    "id": r["id"], "kind": r["kind"], "meta": r.get("meta"), "gold": r["option_keys"][r["label"]],
                    **{t: {"pick": r["option_keys"][p["top"]], "conf": p["confidence"],
                           "p_gold": round(p["probs"][r["label"]], 4)} for t, p in picks.items()},
                    "context": r["context"]}) + "\n")


if __name__ == "__main__":
    main()
