"""Probability-average ensemble of v6 seed 7 (v6-e5-small-e3) and seed 11 (v6-e5-small-e3-s2).

No model is loaded: the two prediction files already share the same row ids and option order (both
were produced by train.py --predict on the same gold split), so the ensemble is just the elementwise
mean of the per-row probability vectors. Weight soup is NOT done (would need the checkpoints on GPU);
this is a prob-average, which is the offline / zero-GPU option named in the brief.

Writes preds/sweep-v6-e5-small-e3-ens.<split>.jsonl for each of the three v6 splits.
"""

from __future__ import annotations

import json
from pathlib import Path

SPLITS = ("test_iid", "test_unseen_phrasing", "test_unseen_apps")
SEED7 = "sweep-v6-e5-small-e3"
SEED11 = "sweep-v6-e5-small-e3-s2"
ENS = "sweep-v6-e5-small-e3-ens"


def load(path: str) -> dict[str, dict]:
    return {r["id"]: r for r in map(json.loads, Path(path).read_text().splitlines()) if r}


def ensemble(split: str) -> None:
    a = load(f"preds/{SEED7}.{split}.jsonl")
    b = load(f"preds/{SEED11}.{split}.jsonl")
    out_path = Path(f"preds/{ENS}.{split}.jsonl")
    n = 0
    with out_path.open("w") as f:
        for i in a:
            if i not in b:
                continue
            pa, pb = a[i]["probs"], b[i]["probs"]
            assert len(pa) == len(pb), f"probs length mismatch on {i}"
            probs = [(x + y) / 2 for x, y in zip(pa, pb)]
            f.write(json.dumps({"id": i, "probs": [round(x, 6) for x in probs]}) + "\n")
            n += 1
    print(json.dumps({"split": split, "ensembled_rows": n, "out": str(out_path)}))


if __name__ == "__main__":
    for s in SPLITS:
        ensemble(s)
