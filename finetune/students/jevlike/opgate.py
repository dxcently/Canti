"""Ship-gate style operating point for jevlike recipes (jl9), the cf_eval.py procedure on what jevlike has.

Verdict fits its phone operating point on pooled leave-apps-out cross-fit predictions (cf_eval.py --fit). jevlike has no
cross-fit, but its val (zflip/val_real_all) is clean for this family (the jl8 teacher saw TRAIN rows only; val only picks
the epoch and T). So, per recipe (several seed checkpoints, each at its own stored T):
  1. fit on val_all, seeds pooled, with cf_eval.fit_operating_point unchanged: a pooled T (about 1 after the stored T),
     the none-logit bias b, t_tap and t_none, subject to the Clopper-Pearson 95% upper bound of wrong taps / taps <= 0.05
     with the app design effect; maximising correct taps + correct nones - wrong nones;
  2. freeze that point and score dev_test and test_old with cf_eval.op_eval (seeds pooled);
  3. paired screen-cluster bootstrap of the per-row utility and wrong taps between recipes (each at its own frozen point).
The selection is optimistic on val (checkpoint epoch and T were also picked there), equally for every recipe.

    python students/jevlike/opgate.py --r J4=runs/jl8-J4-s7.pt,runs/jl8-J4-s8.pt,runs/jl8-J4-s9.pt --r C=... \
        --name jl9 [--baseline J4] [--fit-set val_all] [--sets dev_test test_old] [--B 2000]
Writes sweeps/eval/opgate.<name>.{json,md}. Aggregates only.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import suite_jl  # noqa: E402,F401  (patches students/verdict/suite.py for .pt runs)
from suite_jl import suite  # noqa: E402
import cf_eval  # noqa: E402  (students/verdict/cf_eval.py, on sys.path via suite_jl)
import vstats  # noqa: E402
from seedpool import T_of  # noqa: E402

FT = HERE.parents[1]


def outcome(g, p, pt):
    """(utility contribution, wrong tap, tap, resolved correct) of one row at a frozen point."""
    d, k = cf_eval.decide(p, pt["t_tap"], pt["t_none"])
    ni = len(g["options"]) - 1
    acc = set(g.get("acceptable") or [g["label"]])
    if d == "tap":
        ok = k in acc
        return (1.0 if ok else 0.0), (0.0 if ok else 1.0), 1.0, float(ok)
    if d == "none":
        ok = g["label"] == ni
        return (1.0 if ok else -1.0), 0.0, 0.0, float(ok)
    return 0.0, 0.0, 0.0, 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--r", action="append", required=True, help="NAME=ckpt1,ckpt2,... (a Verdict run dir also works)")
    ap.add_argument("--name", required=True)
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--build", default="data/real-targets-v2/b4a")
    ap.add_argument("--fit-set", default="val_all")
    ap.add_argument("--sets", nargs="+", default=["dev_test", "test_old"])
    ap.add_argument("--max-wrong-tap", type=float, default=0.05)
    ap.add_argument("--B", type=int, default=2000)
    ap.add_argument("--bound", choices=("cp95", "point"), default="cp95",
                    help="cp95 = cf_eval's gate (CP95 upper bound with the app design effect); point = the plain wrong/tap rate "
                         "(a matched-risk comparison when val is too small for the bound)")
    ap.add_argument("--device", default="cuda")
    a = ap.parse_args()
    if a.bound == "point":   # the gate's bound becomes the observed rate (op_eval passes k = rate * n_eff)
        cf_eval.cp_upper = lambda k, n, alpha=0.05: (k / n) if n > 0 else 1.0
    recipes = dict(x.split("=", 1) for x in a.r)
    recipes = {k: v.split(",") for k, v in recipes.items()}
    base = a.baseline or next(iter(recipes))
    specs = suite.sets_for(a.build, "v1")
    pr = suite.Predictor(a.device)
    gold, Zs = {}, defaultdict(dict)
    for s in [a.fit_set] + a.sets:
        spec = specs[s]
        rows = suite.rows_for_format(suite.jl(FT / spec["path"]), "v1")
        gold[s] = rows
        fsha = suite.sha(FT / spec["path"])
        for rn, cks in recipes.items():
            Zs[rn][s] = []
            for ck in cks:
                T = T_of(ck)
                z = suite.get_preds(pr, ck, s, spec, rows, "none", fsha)
                Zs[rn][s].append({k: [v / T for v in zz] for k, zz in z.items()})
    res = {"name": a.name, "recipes": recipes, "fit_set": a.fit_set, "bound": a.bound, "max_wrong_tap": a.max_wrong_tap, "points": {}, "sets": {}}
    for rn in recipes:
        op = cf_eval.fit_operating_point(gold[a.fit_set], Zs[rn][a.fit_set], {}, a.max_wrong_tap)
        res["points"][rn] = {"T_pooled": op["T"], "best": op["best"], "n_feasible": op["n_feasible"],
                             "argmax_reference": op["argmax_reference"]}
    bl = "CP95 UB (app design effect)" if a.bound == "cp95" else "observed rate"
    md = [f"### Operating point fitted on `{a.fit_set}` (seeds pooled, cf_eval.fit_operating_point, {bl} of wrong/tap <= {a.max_wrong_tap}), "
          f"frozen and applied to {', '.join(a.sets)}", "",
          "| recipe | set | none bias | t_tap | t_none | tap rate | wrong/tap (bound used) | none rate (prec) | defer | resolved correct | utility |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for rn in recipes:
        pt = res["points"][rn]["best"]
        if pt is None:
            md.append(f"| {rn} | {a.fit_set} | infeasible | | | | | | | | |")
            continue
        md.append(f"| {rn} | {a.fit_set} (fit) | {pt['b']:+.2f} | {pt['t_tap']:.2f} | {pt['t_none']:.2f} | {pt['tap_rate']:.3f} | "
                  f"{pt['wrong_tap_per_tap']:.3f} ({pt['wrong_tap_ub95']:.3f}) | {pt['none_rate']:.3f} ({pt['none_precision']:.3f}) | "
                  f"{pt['defer_rate']:.3f} | {pt['resolved_correct']:.3f} | {pt['utility']:.3f} |")
    per_row = defaultdict(dict)   # [set][recipe] -> list of per-row (seed-mean) outcomes
    for s in a.sets:
        by_id = {g["id"]: g for g in gold[s]}
        res["sets"][s] = {}
        for rn in recipes:
            pt = res["points"][rn]["best"]
            if pt is None:
                continue
            T = res["points"][rn]["T_pooled"]
            Ps = [{i: cf_eval.softmax(z, T, pt["b"]) for i, z in Z.items()} for Z in Zs[rn][s]]
            e = cf_eval.op_eval(by_id, Ps, pt["t_tap"], pt["t_none"])
            res["sets"][s][rn] = e
            md.append(f"| {rn} | {s} | | | | {e['tap_rate']:.3f} | {e['wrong_tap_per_tap']:.3f} ({e['wrong_tap_ub95']:.3f}) | "
                      f"{e['none_rate']:.3f} ({e['none_precision']:.3f}) | {e['defer_rate']:.3f} | {e['resolved_correct']:.3f} | {e['utility']:.3f} |")
            per_row[s][rn] = [[sum(x) / len(Ps) for x in zip(*[outcome(g, P[g["id"]], pt) for P in Ps])] for g in gold[s]]
    md += ["", f"Paired against {base} at each recipe's own frozen point (screen-cluster bootstrap B={a.B}): "
           "Δutility/row, Δwrong taps/row, Δtap rate, Δresolved correct [95% CI] p", "",
           "| recipe | set | Δutility | Δwrong taps / row | Δtap rate | Δresolved correct |", "|---|---|---|---|---|---|"]
    res["paired"] = {}
    for s in a.sets:
        if base not in per_row[s]:
            continue
        cl = [g.get("screen_id") or g["id"] for g in gold[s]]
        by = defaultdict(list)
        for i, c in enumerate(cl):
            by[c].append(i)
        cls = sorted(by)
        for rn in recipes:
            if rn == base or rn not in per_row[s]:
                continue
            A, Bm = per_row[s][rn], per_row[s][base]
            D = [[x - y for x, y in zip(ra, rb)] for ra, rb in zip(A, Bm)]
            pt = [sum(d[j] for d in D) / len(D) for j in range(4)]
            rng = random.Random(12345)
            bs = [[] for _ in range(4)]
            for _ in range(a.B):
                idx = [i for c in (rng.choice(cls) for _ in cls) for i in by[c]]
                for j in range(4):
                    bs[j].append(sum(D[i][j] for i in idx) / len(idx))
            out = []
            for j in range(4):
                d = bs[j]
                p = min(1.0, 2 * min(sum(v <= 0 for v in d), sum(v >= 0 for v in d)) / len(d))
                out.append((pt[j], vstats.pct(d, .025), vstats.pct(d, .975), p))
            res["paired"].setdefault(s, {})[rn] = dict(zip(("utility", "wrong_tap_per_row", "tap_rate", "resolved_correct"), out))
            f = lambda t: f"{t[0]:+.3f} [{t[1]:+.3f}, {t[2]:+.3f}] p={t[3]:.3f}"  # noqa: E731
            md.append(f"| {rn} | {s} | {f(out[0])} | {f(out[1])} | {f(out[2])} | {f(out[3])} |")
    text = "\n".join(md) + "\n"
    print(text)
    out = FT / "sweeps" / "eval" / f"opgate.{a.name}"
    Path(f"{out}.json").write_text(json.dumps(res, indent=1, default=float))
    Path(f"{out}.md").write_text(text)
    print(f"wrote {out}.json/.md")


if __name__ == "__main__":
    main()
