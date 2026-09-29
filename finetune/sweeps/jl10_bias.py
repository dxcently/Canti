"""jl10: post-hoc none-logit bias on J5c (seed-mean of per-seed argmax), recall / false-none / acc per set. Diagnostic only
(test sets are not used to pick anything)."""
import json, glob, math, sys
FT = "/home/khoa/VOX/finetune"; B = f"{FT}/data/real-targets-v2/b4a"
runs = sys.argv[1].split(",") if len(sys.argv) > 1 else [f"runs/jl9-J5b-e3-s{s}.pt" for s in (7, 8, 9)]
import torch
T = {r: float(torch.load(f"{FT}/{r}", map_location="cpu", weights_only=False)["config"].get("temperature", 1)) for r in runs}
def jl(p): return [json.loads(l) for l in open(p)]
sets = {"val_all": ("zflip/val_real_all", "data/real-targets-v2/zflip/preds/suite"), "dev_test": ("test_real", "preds/real-targets-v2/suite"),
        "test_old": ("test_real_old", "preds/real-targets-v2/suite")}
for s, (f, pd) in sets.items():
    rows = jl(f"{B}/{f}.jsonl"); L = {}
    for r in runs:
        pps = sorted(glob.glob(f"{FT}/{pd}/{s}.{r.split('/')[-1]}.none.*.jsonl"), key=lambda p: -__import__('os').path.getmtime(p))
        L[r] = {x["id"]: x["logits"] for x in jl(pps[0])}
    out = []
    for b in (0, 0.25, 0.5, 0.75, 1.0, 1.5):
        rec = fn = acc = 0; ng = sum(r["label"] == len(r["options"]) - 1 for r in rows)
        for r in rows:
            ni = len(r["options"]) - 1
            for run in runs:
                z = [x / T[run] for x in L[run][r["id"]]]; z[ni] += b
                t = max(range(len(z)), key=z.__getitem__)
                acc += t == r["label"]
                if r["label"] == ni: rec += t == ni
                else: fn += t == ni
        k = len(runs)
        out.append(f"b={b:+.2f}: recall {rec/ng/k:.3f} false-none {fn/(len(rows)-ng)/k:.3f} acc {acc/len(rows)/k:.3f}")
    print(s, " | ".join(out))
