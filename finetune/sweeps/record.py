"""Append one sweep run to sweeps/runs.jsonl.

Metrics come from the per-test JSON written by `python -m vox.evaluate <gold> <preds>`
(sweeps/eval/<name>.<split>.json); the exact command, wall time and checkpoint are passed in.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

SPLITS = ("test_iid", "test_unseen_phrasing", "test_unseen_apps")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--data-version", default="")
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--command", required=True)
    ap.add_argument("--status", required=True)
    ap.add_argument("--train-wall-s", type=float)
    ap.add_argument("--predict-wall-s", type=float)
    ap.add_argument("--train-log")
    ap.add_argument("--note", default="")
    a = ap.parse_args()

    preds, metrics = {}, {}
    for split in SPLITS:
        name = f"sweep-{a.name}.{split}.jsonl"
        path = Path(f"sweeps/eval/{a.name}.{split}.json")
        pred_path = Path(f"preds/{name}")
        if path.exists() and pred_path.exists():
            preds[split] = str(pred_path)
            metrics[split] = json.loads(path.read_text())[name]

    train_minutes = None
    if a.train_log and Path(a.train_log).exists():
        for line in Path(a.train_log).read_text().splitlines():
            if line.startswith('{"checkpoint"'):
                train_minutes = json.loads(line).get("minutes")

    total = None if a.train_wall_s is None else a.train_wall_s + (a.predict_wall_s or 0.0)
    row = {
        "name": a.name, "status": a.status, "data_version": a.data_version,
        "command": a.command, "checkpoint": a.checkpoint,
        "train_minutes_logged": train_minutes, "train_wall_s": a.train_wall_s,
        "predict_wall_s": a.predict_wall_s, "total_wall_s": total,
        "preds": preds, "metrics": metrics, "note": a.note,
    }
    out = Path("sweeps/runs.jsonl")
    with out.open("a") as f:
        f.write(json.dumps(row) + "\n")
    print(json.dumps({
        "recorded": a.name,
        "unseen_phrasing_acc": metrics.get("test_unseen_phrasing", {}).get("accuracy"),
        "rows_in_runs_jsonl": len(out.read_text().splitlines()),
    }))


if __name__ == "__main__":
    main()
