"""Verdict (bi run dir) soft labels for jevlike distillation: {id, probs} per row, probs = softmax(logits / T) with the
run's fitted temperature (student.json) unless --temperature is given. Rows are read and ids written as-is; write the
output next to the input when the input holds Z Flip rows (…/zflip/, local only).

    python students/jevlike/verdict_teacher.py --run students/verdict/runs/verdict-bi-real-v1d \
        --rows data/real-targets-v2/b4a/zflip/mix.jl7.jsonl --out data/real-targets-v2/b4a/zflip/teacher.jl7.v1d.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "verdict"))
import vlib  # noqa: E402
import torch  # noqa: E402
from common import softmax  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--rows", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--temperature", type=float)
    a = ap.parse_args()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    m = vlib.Student(a.run, "bi", device=dev).eval()
    T = a.temperature or m.temperature
    rows = [json.loads(x) for x in Path(a.rows).read_text().splitlines() if x.strip()]
    ac = torch.autocast("cuda", dtype=torch.bfloat16, enabled=dev == "cuda")
    hit = 0
    with open(a.out, "w") as f, torch.no_grad(), ac:
        for i in range(0, len(rows), 128):
            ch = rows[i:i + 128]
            for r, z in zip(ch, m.logits(ch, cache_options=True)):
                p = softmax(z.float().cpu().tolist(), T)
                hit += max(range(len(p)), key=p.__getitem__) == r["label"]
                f.write(json.dumps({"id": r["id"], "probs": [round(x, 6) for x in p]}) + "\n")
    print(json.dumps({"rows": len(rows), "T": T, "teacher_train_acc": round(hit / len(rows), 4), "out": a.out}))


if __name__ == "__main__":
    main()
