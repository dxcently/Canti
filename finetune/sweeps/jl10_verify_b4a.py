import json
from pathlib import Path

FILES = ["train_real.jsonl", "val_real.jsonl", "test_real.jsonl", "test_real_old.jsonl", "test_exact.jsonl",
         "zflip/train_real_all.jsonl", "zflip/val_real_all.jsonl", "zflip/train_real_zflip.jsonl",
         "zflip/val_real_zflip.jsonl", "zflip/diag_x_opus.jsonl"]

A = Path("data/real-targets-v2/b4a")
B = Path("data/real-targets-v2/b4a-v2i")

def load(p):
    return [json.loads(l) for l in open(p)]

report = {}
for f in FILES:
    ra, rb = load(A / f), load(B / f)
    issues = []
    if len(ra) != len(rb):
        issues.append(f"row count {len(ra)} vs {len(rb)}")
    n = min(len(ra), len(rb))
    id_ok = sum(a["id"] == b["id"] for a, b in zip(ra, rb))
    label_ok = sum(a["label"] == b["label"] for a, b in zip(ra, rb))
    acc_ok = sum(a["acceptable"] == b["acceptable"] for a, b in zip(ra, rb))
    phrase_ok = sum(a["phrase"] == b["phrase"] for a, b in zip(ra, rb))
    nopt_ok = sum(len(a["options"]) == len(b["options"]) for a, b in zip(ra, rb))
    # same number of options AND same option_keys
    keys_ok = sum(a.get("option_keys") == b.get("option_keys") for a, b in zip(ra, rb))
    # only option text differs: check that non-option fields are equal (excluding options itself)
    same_except_options = 0
    for a, b in zip(ra, rb):
        a2 = {k: v for k, v in a.items() if k not in ("options", "option_format", "v2_approx")}
        b2 = {k: v for k, v in b.items() if k not in ("options", "option_format", "v2_approx")}
        if a2 == b2:
            same_except_options += 1
    mismatches = []
    for i, (a, b) in enumerate(zip(ra, rb)):
        for key in ("id", "label", "acceptable", "phrase"):
            if a[key] != b[key]:
                mismatches.append((i, key, a[key], b[key]))
                break
        else:
            if len(a["options"]) != len(b["options"]):
                mismatches.append((i, "n_options", len(a["options"]), len(b["options"])))
    report[f] = {"rows": len(ra), "id_ok": id_ok, "label_ok": label_ok, "acceptable_ok": acc_ok,
                 "phrase_ok": phrase_ok, "n_options_ok": nopt_ok, "option_keys_ok": keys_ok,
                 "same_except_options": same_except_options, "n_mismatch": len(mismatches),
                 "mismatch_samples": mismatches[:5]}

for f, r in report.items():
    print(f)
    for k, v in r.items():
        if k != "mismatch_samples":
            print(f"   {k}: {v}")
    if r["mismatch_samples"]:
        print(f"   samples: {r['mismatch_samples']}")
    print()
