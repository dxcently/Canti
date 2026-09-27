"""Fit a Verdict run's temperature on a (real) validation split without retraining; prints T. Does not modify the run.

    python students/verdict/fit_temp.py --run students/verdict/runs/verdict-bi-targets-v2 --val data/real-targets-v2/zflip/val_real_all.jsonl
Then score with predict.py --temperature T.
"""
from __future__ import annotations

import argparse
import json

import vlib  # noqa: F401  (sets sys.path, env)
import torch
from common import fit_temperature, load_rows, score, softmax


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--val", required=True)
    ap.add_argument("--device", default="cuda")
    a = ap.parse_args()
    meta = json.load(open(f"{a.run}/student.json"))
    m = vlib.Student(a.run, meta["arch"], max_len=meta.get("max_len", 512), device=a.device)
    m.eval()
    rows = load_rows(a.val)
    raw = {}
    with torch.no_grad():
        for i in range(0, len(rows), 32):
            chunk = rows[i:i + 32]
            for r, z in zip(chunk, m.logits(chunk)):
                raw[r["id"]] = z.float().cpu().tolist()
    T = fit_temperature([raw[r["id"]] for r in rows], [r["label"] for r in rows])
    s1 = score(rows, {k: softmax(v, 1.0) for k, v in raw.items()})
    sT = score(rows, {k: softmax(v, T) for k, v in raw.items()})
    sS = score(rows, {k: softmax(v, meta.get("temperature", 1.0)) for k, v in raw.items()})
    print(json.dumps({"run": a.run, "val": a.val, "rows": len(rows), "stored_T": meta.get("temperature"), "T": T,
                      "acc": sT["accuracy"], "ece_T1": s1["ece"], "ece_stored": sS["ece"], "ece_fit": sT["ece"]}))


if __name__ == "__main__":
    main()
