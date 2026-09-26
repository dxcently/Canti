#!/usr/bin/env python3
"""One-table comparison of run tags (headline numbers only), for tuning decisions and the summary report.

  ./run python eval_real/compare.py --split tune --tags frozen fixed tuneA tuneB     # print a markdown table
  ./run python eval_real/compare.py --split test --tags frozen fixed tuned --out results/real_summary_table.md

Reads the per-clip runs in datasets/_eval_cache/runs/<tag>/ through the dataset scripts' summarise functions (the
same numbers as results/real_<dataset>.md). Pop / click detection is per clip ("the clip yields at least one
event of the right label"); FA/min = false-accept GROUPS per minute (a group the default profile would act on).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
import run_all as R  # noqa: E402

ROWS = [
    # (label, dataset, getter)
    ("tongue click detect, clean", "nonverbal", lambda s: s["pos"]["clean"]["tongue-clicking"]["detect"], "pct"),
    ("tongue click detect, 10 dB", "nonverbal", lambda s: s["pos"][10]["tongue-clicking"]["detect"], "pct"),
    ("tongue click: majority label click, clean", "nonverbal", lambda s: s["pos"]["clean"]["tongue-clicking"]["major_acc"], "pct"),
    ("lip pop detect, clean", "nonverbal", lambda s: s["pos"]["clean"]["lip-popping"]["detect"], "pct"),
    ("lip pop detect, 10 dB", "nonverbal", lambda s: s["pos"][10]["lip-popping"]["detect"], "pct"),
    ("lip smack as pop/click, clean (borderline)", "nonverbal", lambda s: s["border"]["clean"]["lip-smacking"]["detect"], "pct"),
    ("Nonverbal negatives (user list) FA/min", "nonverbal", lambda s: s["neg"]["ALL"]["fa_per_min"], "num"),
    ("Nonverbal other negatives FA/min", "nonverbal", lambda s: s["other"]["ALL"]["fa_per_min"], "num"),
    ("QBSH contour label acc, clean", "qbsh_contour", lambda s: s["clean"]["acc"], "pct"),
    ("QBSH end-to-end action OK, clean", "qbsh_contour", lambda s: s["clean"]["action_ok"], "pct"),
    ("QBSH contour label acc, 10 dB", "qbsh_contour", lambda s: s[10]["acc"], "pct"),
    ("MUSAN speech FA/min", "musan", lambda s: s["speech (all)"]["fa_per_min"], "num"),
    ("MUSAN music FA/min", "musan", lambda s: s["music (all)"]["fa_per_min"], "num"),
    ("MUSAN noise FA/min", "musan", lambda s: s["noise (all)"]["fa_per_min"], "num"),
    ("MLEnd hum: voiced events called hum", "mlend", lambda s: s["hum"]["called_right_n"], "pct"),
    ("MLEnd hum: called talking", "mlend", lambda s: s["hum"]["talking_n"], "pct"),
    ("MLEnd whistle: called whistle", "mlend", lambda s: s["whistle"]["called_right_n"], "pct"),
    ("Nonspeech7k FA/min", "nonspeech7k", lambda s: s["ALL"]["fa_per_min"], "num"),
    ("Nonspeech7k screaming FA/min", "nonspeech7k", lambda s: s["screaming"]["fa_per_min"], "num"),
    ("ESC-50 FA/min (all 50 classes)", "esc50", lambda s: s["ALL"]["fa_per_min"], "num"),
    ("ESC-50 cat FA/min", "esc50", lambda s: s["cat"]["fa_per_min"], "num"),
]


def table(tags: list[str], split: str) -> str:
    S = R.summaries(tags)
    body = []
    for label, ds, get, kind in ROWS:
        row = [label]
        for t in tags:
            s = S.get((t, split), {}).get(ds)
            try:
                v = get(s)
                row.append(C.pct(v) + " %" if kind == "pct" else C.num(v))
            except (KeyError, TypeError):
                row.append("-")
        body.append(row)
    return C.md_table(["metric (" + split + " split)"] + tags, body)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tags", nargs="+", required=True)
    ap.add_argument("--split", default="test")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    t = table(a.tags, a.split)
    if a.out:
        Path(a.out).write_text(t + "\n")
    print(t)


if __name__ == "__main__":
    main()
