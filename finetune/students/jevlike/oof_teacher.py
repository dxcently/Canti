"""Honest (out-of-app) Verdict soft labels for jevlike distillation, from a leave-apps-out cross-fit (crossfit.py).

Each real training row of the jevlike mix is a copy of a held-in row (`<id>-r<k>` -> `<id>`, same context and options)
and gets the logits that the cross-fit fold model which did NOT train on that row's app produced for that row
(aligned to the row's own option list; verified). Several cross-fit seeds are averaged in probability space.
T is fitted on the same out-of-fold logits (common.fit_temperature), so the teacher is calibrated out-of-app too.
Synthetic mix rows (targets-v2) get no teacher (the fold models were initialised/trained on targets-v2: in-sample);
the student keeps plain CE on them. Rows whose original id is not in the cross-fit pool get no teacher either.

    python students/jevlike/oof_teacher.py --crossfit data/real-targets-v2/b4a/zflip/crossfit/<recipe> \
        --mix data/real-targets-v2/b4a/zflip/mix.jl7.jsonl --out data/real-targets-v2/b4a/zflip/teacher.jl8.oof.jsonl
Output rows {id, probs}; a summary (aggregates only) goes to stdout and <out>.json. Z Flip ids: keep under zflip/.

--none-bias B (jl9, opt-in; default 0 = jl8 behaviour): add B to the none logit (the last option) after /T, before the
softmax, per cross-fit seed (cf_eval.py's convention). --none-bias fit: per seed, fit b by NLL on the out-of-fold logits
(T refitted once given b), so the bias is the teacher's own out-of-app calibration correction, not a hand value.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import fit_temperature, softmax  # noqa: E402


def jl(p):
    return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]


def softmax_b(z, T, b=0.0):
    """softmax(z / T) with b added to the none (last) logit after /T (cf_eval.py's convention)."""
    import math
    v = [x / T for x in z]
    v[-1] += b
    m = max(v)
    e = [math.exp(x - m) for x in v]
    s = sum(e)
    return [x / s for x in e]


def _nll(Z, labels, T, b):
    import math
    return -sum(math.log(max(softmax_b(z, T, b)[y], 1e-300)) for z, y in zip(Z, labels)) / len(labels)


def _golden(f, lo, hi, it=40):
    g = (5 ** 0.5 - 1) / 2
    for _ in range(it):
        x1, x2 = hi - g * (hi - lo), lo + g * (hi - lo)
        if f(x1) < f(x2):
            hi = x2
        else:
            lo = x1
    return (lo + hi) / 2


def fit_none_bias(Z, labels, T):
    return round(_golden(lambda b: _nll(Z, labels, T, b), -3.0, 3.0), 4)


def fit_t_given_b(Z, labels, b):
    return round(_golden(lambda T: _nll(Z, labels, T, b), 0.3, 6.0), 4)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--crossfit", required=True, help="crossfit.py output dir (recipe.json, s<seed>/f<k>.jsonl)")
    ap.add_argument("--mix", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seeds", type=int, nargs="*", default=None, help="default: every complete seed")
    ap.add_argument("--none-bias", default="0", help="float added to the none logit after /T, or 'fit' (per seed, by OOF NLL)")
    a = ap.parse_args()
    cf = Path(a.crossfit)
    rec = json.loads((cf / "recipe.json").read_text())
    pool = {r["id"]: r for f in rec["pool"] for r in jl(Path(__file__).resolve().parents[2] / f)}
    seeds = a.seeds if a.seeds is not None else rec.get("seeds_done", [])
    assert seeds, "no complete cross-fit seed"
    per_seed = []
    for s in seeds:
        z = {}
        for f in sorted((cf / f"s{s}").glob("f*.jsonl")):
            for r in jl(f):
                z[r["id"]] = r["logits"]
        assert set(z) == set(pool), f"seed {s}: {len(z)} predictions for {len(pool)} pool rows (incomplete)"
        per_seed.append(z)
    ids = sorted(pool)
    labels = [pool[i]["label"] for i in ids]
    Ts = [fit_temperature([z[i] for i in ids], labels) for z in per_seed]
    if a.none_bias == "fit":
        bs = []
        for k, z in enumerate(per_seed):
            b = fit_none_bias([z[i] for i in ids], labels, Ts[k])
            # refit T given b (one coordinate round), then b given the new T
            Ts[k] = fit_t_given_b([z[i] for i in ids], labels, b)
            bs.append(fit_none_bias([z[i] for i in ids], labels, Ts[k]))
    else:
        bs = [float(a.none_bias)] * len(per_seed)
    probs = {}
    for i in ids:
        ps = [softmax_b(z[i], T, b) for z, T, b in zip(per_seed, Ts, bs)]
        probs[i] = [sum(col) / len(ps) for col in zip(*ps)]
    oof_acc = sum(max(range(len(probs[i])), key=probs[i].__getitem__) == pool[i]["label"] for i in ids) / len(ids)
    import math
    oof_nll = -sum(math.log(max(probs[i][pool[i]["label"]], 1e-12)) for i in ids) / len(ids)
    gn = [i for i in ids if pool[i]["label"] == len(probs[i]) - 1]
    none_recall = sum(max(range(len(probs[i])), key=probs[i].__getitem__) == len(probs[i]) - 1 for i in gn) / max(1, len(gn))
    pn = [i for i in ids if max(range(len(probs[i])), key=probs[i].__getitem__) == len(probs[i]) - 1]
    false_none = sum(pool[i]["label"] != len(probs[i]) - 1 for i in pn) / max(1, len(ids) - len(gn))
    n_real = n_hit = n_syn = n_miss = n_mismatch = 0
    with open(a.out, "w") as f:
        for r in jl(a.mix):
            if "app" not in r:
                n_syn += 1
                continue
            n_real += 1
            orig = re.sub(r"-r\d+$", "", r["id"])
            p = pool.get(orig)
            if p is None:
                n_miss += 1
                continue
            if p["options"] != r["options"] or p["context"] != r["context"] or p["label"] != r["label"]:
                n_mismatch += 1
                continue
            n_hit += 1
            f.write(json.dumps({"id": r["id"], "probs": [round(x, 6) for x in probs[orig]]}) + "\n")
    summ = {"crossfit": str(cf), "recipe": rec["recipe"], "seeds": seeds, "T_per_seed": Ts, "none_bias_per_seed": [round(b, 4) for b in bs], "pool_rows": len(ids),
            "oof_acc_ensemble": round(oof_acc, 4), "oof_nll_ensemble": round(oof_nll, 4),
            "oof_none_recall": round(none_recall, 4), "oof_false_none_per_nonnone_row": round(false_none, 4), "oof_gold_none_rows": len(gn), "mix": a.mix, "mix_real_rows": n_real,
            "teacher_rows": n_hit, "no_teacher_missing_from_pool": n_miss, "no_teacher_mismatch": n_mismatch, "synthetic_rows_no_teacher": n_syn,
            "out": a.out}
    Path(a.out + ".json").write_text(json.dumps(summ, indent=1))
    print(json.dumps(summ))


if __name__ == "__main__":
    main()
