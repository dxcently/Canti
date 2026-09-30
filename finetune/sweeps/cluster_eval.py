"""Cluster-level accuracy report for one data split and one or more prediction files.

Clusters:
  - test_unseen_phrasing: held-out action wordings (rows whose gold action's held-out wording
    appears in the context) and held-out phrase text (rows where the phrase is spoken). A row can
    belong to several clusters (a phrase_rule sentence carries a held-out action wording, and a
    spoken phrase plus a rule can co-occur).
  - test_unseen_apps: (app package, screen kind) read from the context.
  - test_iid (in-distribution): no held-out wording exists, so only overall accuracy is reported.

For each cluster it prints n and per-pred accuracy, marks pass (accuracy >= threshold), and when
more than one preds file is given also the seed mean + range (min/max) of the overall accuracy.

Usage (from finetune/):
  .venv/bin/python sweeps/cluster_eval.py data/v6/test_unseen_phrasing.jsonl \
      preds/sweep-v6-e5-small-e3.test_unseen_phrasing.jsonl \
      preds/sweep-v6-e5-small-e3-s2.test_unseen_phrasing.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # project root, for vox.*

from vox import generate as G  # noqa: E402

APP_RE = re.compile(r"^app: .* \(([^)]*)\)$", re.MULTILINE)
SCREEN_RE = re.compile(r"^screen: ([^;]*);", re.MULTILINE)


def load(path: str) -> dict[str, dict]:
    return {r["id"]: r for r in map(json.loads, Path(path).read_text().splitlines()) if r}


def app_screen(ctx: str) -> tuple[str | None, str | None]:
    m = APP_RE.search(ctx)
    app = m.group(1) if m else None
    m = SCREEN_RE.search(ctx)
    kind = m.group(1) if m else None
    return app, kind


def detect_split(gold_path: str, gold: dict[str, dict]) -> str:
    first = next(iter(gold.values()), {})
    if first.get("split"):
        return first["split"]
    name = Path(gold_path).name
    for split in ("test_iid", "test_unseen_phrasing", "test_unseen_apps"):
        if split in name:
            return split
    return name


def correct_rows(gold: dict[str, dict], preds: dict[str, dict]) -> dict[str, bool]:
    out = {}
    for i, g in gold.items():
        if i not in preds:
            continue
        probs = preds[i]["probs"]
        top = max(range(len(probs)), key=probs.__getitem__)
        out[i] = top == g["label"]
    return out


def short_label(pred_path: str, split: str) -> str:
    name = Path(pred_path).name
    if name.startswith("sweep-"):
        name = name[len("sweep-"):]
    suffix = f".{split}.jsonl"
    if name.endswith(suffix):
        name = name[: -len(suffix)]
    if name.endswith(".jsonl"):
        name = name[: -len(".jsonl")]
    return name


def unseen_phrasing_clusters(gold: dict[str, dict]) -> dict[tuple[str, str], list[str]]:
    """Map (category, label) -> row ids for held-out action wordings and held-out phrases."""
    buckets: dict[tuple[str, str], list[str]] = {}
    for i, g in gold.items():
        ctx = g["context"]
        gold_action = g["option_keys"][g["label"]]
        # held-out action wording: the gold action's wording appearing in the context
        if gold_action in G.ACTION_WORDS:
            wording = G.ACTION_WORDS[gold_action][1][0]
            if wording in ctx:
                buckets.setdefault(("action", f'{gold_action} "{wording}"'), []).append(i)
        # held-out phrase text
        for phrase in G.HELDOUT_PHRASES:
            if f'spoken phrase: "{phrase}"' in ctx:
                buckets.setdefault(("phrase", f'"{phrase}"'), []).append(i)
    return buckets


def unseen_apps_clusters(gold: dict[str, dict]) -> dict[tuple[str, str], list[str]]:
    buckets: dict[tuple[str, str], list[str]] = {}
    for i, g in gold.items():
        app, kind = app_screen(g["context"])
        label = f"{app or '(no app)'} / {kind or '(no screen)'}"
        buckets.setdefault(("app_screen", label), []).append(i)
    return buckets


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("gold")
    ap.add_argument("preds", nargs="+")
    ap.add_argument("--threshold", type=float, default=0.95, help="cluster pass threshold (default 0.95)")
    a = ap.parse_args()

    gold = load(a.gold)
    preds = [load(p) for p in a.preds]
    split = detect_split(a.gold, gold)
    labels = [short_label(p, split) for p in a.preds]
    thr = a.threshold

    corrects = [correct_rows(gold, p) for p in preds]

    print(f"=== {split} ===  (gold {Path(a.gold).name}: {len(gold)} rows)")
    print(f"preds: {', '.join(labels)}  pass threshold: {thr:.2f}")
    print()

    # overall accuracy + seed mean/range
    accs = []
    for label, corr in zip(labels, corrects):
        n = len(corr)
        acc = sum(corr.values()) / n if n else 0.0
        accs.append(acc)
        print(f"overall accuracy {label:<24} {acc:.4f}  ({sum(corr.values())}/{n})")
    if len(preds) > 1:
        print(f"seed mean {sum(accs) / len(accs):.4f}   range {min(accs):.4f}-{max(accs):.4f}")
    print()

    if split == "test_unseen_apps":
        buckets = unseen_apps_clusters(gold)
    elif split == "test_unseen_phrasing":
        buckets = unseen_phrasing_clusters(gold)
    else:
        print(f"(no held-out wording clusters for {split}; nothing more to report)")
        return

    ordered = sorted(buckets, key=lambda k: (k[0], k[1]))
    header = f"{'cluster':<52}{'n':>6}" + "".join(f"{l:>10}" for l in labels) + f"{'pass':>24}"
    print(header)
    print("-" * len(header))

    pass_counts = {l: [0, 0] for l in labels}  # label -> [passing clusters, total clusters]
    for cat, lbl in ordered:
        ids = buckets[(cat, lbl)]
        cells = []
        marks = []
        for label, corr in zip(labels, corrects):
            hits = sum(corr[i] for i in ids if i in corr)
            total = len([i for i in ids if i in corr])
            cells.append(f"{hits}/{total}" if total else "-")
            if total:
                pass_counts[label][1] += 1
                passed = hits / total >= thr
                pass_counts[label][0] += int(passed)
                marks.append(f"{label}:{'Y' if passed else 'N'}")
            else:
                marks.append(f"{label}:-")
        n = len([i for i in ids if any(i in c for c in corrects)])
        print(f"{lbl:<52}{n:>6}" + "".join(f"{c:>10}" for c in cells) + f"{' '.join(marks):>24}")

    print()
    for label in labels:
        p, t = pass_counts[label]
        print(f"clusters passing (>= {thr:.2f}): {label} {p}/{t}")
    print(f"cluster categories: {sorted({k[0] for k in buckets})}")


if __name__ == "__main__":
    main()
