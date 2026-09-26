"""Check the batched scorer against each project's own runtime on real VOX rows.

Upstream references (batch 1, eager, no CUDA graphs):
  decider4b  decider.infer.Decider(path, use_graphs=False).system_one(state, {"q": question})   (runs with an attention mask)
  jevk5      jevk5.JevK5(path, graphs=False).decide(state, question)
Ours: teachers.scorer, right-padded batches of 6 mixed-length rows, no mask.

    python -m teachers.parity --rows 24
"""

from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path

import torch

from teachers.scorer import REPOS, REVISIONS, load, question

ROOT = Path(__file__).resolve().parents[1]


def rows(n: int) -> list[dict]:
    out = []
    for split in ("test_iid", "test_unseen_phrasing"):
        out += [json.loads(l) for l in (ROOT / f"data/v0/{split}.jsonl").read_text().splitlines()[: n // 2]]
    return out


def upstream(name: str, data: list[dict], policy: str) -> list[list[float]]:
    from huggingface_hub import snapshot_download

    path = snapshot_download(REPOS[name], revision=REVISIONS[name])
    out = []
    if name == "decider4b":
        from decider.infer import Decider

        d = Decider(path, device="cuda", use_graphs=False)
        for r in data:
            a = d.system_one(r["context"], {"q": question(policy, r["options"])})["answers"]["q"]
            out.append([a["probabilities"][o] for o in r["options"]])
        del d
    else:
        from jevk5 import JevK5

        m = JevK5(path, device="cuda", graphs=False)
        for r in data:
            a = m.decide(r["context"], question(policy, r["options"]))
            out.append([a["probabilities"][o] for o in r["options"]])
        del m
    gc.collect()
    torch.cuda.empty_cache()
    return out


def ours(name: str, data: list[dict], policy: str) -> list[list[float]]:
    t = load(name)
    encs = [t.encode(r["context"], question(policy, r["options"])) for r in data]
    p = [x for i in range(0, len(encs), 6) for x in t.probs(encs[i:i + 6])]  # padded batches of 6 mixed-length rows
    del t
    gc.collect()
    torch.cuda.empty_cache()
    return p


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=24)
    ap.add_argument("--teachers", default="decider4b,jevk5")
    a = ap.parse_args()
    from teachers.rocm_compat import apply

    apply()  # the upstream runtimes need the same ROCm kernel patches (kernels only)
    policy = (ROOT / "data/v0/policy.txt").read_text().strip()
    data = rows(a.rows)
    report = {}
    for name in a.teachers.split(","):
        ref, mine = upstream(name, data, policy), ours(name, data, policy)
        diff = max(abs(x - y) for r, m in zip(ref, mine) for x, y in zip(r, m))
        argmax = sum(max(range(len(r)), key=r.__getitem__) == max(range(len(m)), key=m.__getitem__) for r, m in zip(ref, mine))
        flips = []
        for r, x, m in zip(data, ref, mine):
            ax, am = max(range(len(x)), key=x.__getitem__), max(range(len(m)), key=m.__getitem__)
            if ax != am:
                flips.append({"id": r["id"], "upstream": {r["option_keys"][ax]: round(x[ax], 4), r["option_keys"][am]: round(x[am], 4)},
                              "ours": {r["option_keys"][ax]: round(m[ax], 4), r["option_keys"][am]: round(m[am], 4)}})
        report[name] = {"rows": len(data), "max_abs_prob_diff": round(diff, 5), "same_argmax": argmax, "argmax_flips": flips,
                        "options_range": [min(len(r["options"]) for r in data), max(len(r["options"]) for r in data)]}
        print(name, json.dumps(report[name]), flush=True)
    (ROOT / "teachers/parity.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
