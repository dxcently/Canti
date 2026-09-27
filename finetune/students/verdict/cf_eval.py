"""Score leave-apps-out cross-fit predictions (crossfit.py) and fit the phone's operating point on them.

Recipe selection (SPLIT.md amendment 2026-09-27) uses threshold-free out-of-app metrics on the pooled out-of-fold
predictions: NLL (after one temperature per recipe-seed), none AUROC, target accuracy (gold is a target), novel-phrase
accuracy (phrase not seen in that fold's training apps), plus plain acc / none recall for reference. CIs resample APPS
(the held-out unit); the noise floor is the SD of each metric across seeds of one recipe.

    python students/verdict/cf_eval.py --recipes ref [cand ...] [--baseline ref] [--fit ref] [--B 1000]

--fit RECIPE fits, on that recipe's pooled out-of-app predictions:
  T          temperature (NLL);
  b          a bias added to the none logit (after /T);
  t_tap      tap the top target only if it is not "none" and p >= t_tap;
  t_none     answer "none" only if p_none >= t_none; everything else defers (ask again / cloud).
  Constraint: Clopper-Pearson 95% upper bound of the wrong-tap rate (wrong taps / taps, a gold "none" tapped counts as
  wrong) <= --max-wrong-tap (0.05), with n = taps per seed / design effect of the app clusters (ICC by one-way ANOVA),
  so a few apps cannot buy a tight bound. Among feasible (b, t_tap, t_none) it maximises correct taps + correct nones
  - wrong nones (a wrong "none" costs the user a retry; a wrong tap acts on the wrong thing and is bounded instead).
Output: sweeps/eval/cf.<build>.<recipes>[.fit-<recipe>].{json,md}. Aggregates only (the pool contains Z Flip rows; never printed).
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vstats  # noqa: E402

FT = Path(__file__).resolve().parents[2]
MKEYS = ("nll", "none_auroc", "target_acc", "novel_acc", "acc", "none_recall", "false_none")
LOWER_BETTER = {"nll", "false_none"}


def jl(p):
    return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]


def softmax(z, T=1.0, b=0.0):
    z = [v / T for v in z]
    z[-1] += b
    m = max(z)
    e = [math.exp(v - m) for v in z]
    s = sum(e)
    return [v / s for v in e]


def fit_T(rows, Z):
    """1-D golden-section search of the NLL over T in [0.3, 6]."""
    def nll(T):
        return sum(-math.log(max(softmax(Z[r["id"]], T)[r["label"]], 1e-12)) for r in rows) / len(rows)
    lo, hi = 0.3, 6.0
    g = (math.sqrt(5) - 1) / 2
    for _ in range(40):
        a, b = hi - g * (hi - lo), lo + g * (hi - lo)
        if nll(a) < nll(b):
            hi = b
        else:
            lo = a
    return (lo + hi) / 2


def load(build: Path, recipe: str, labels: Path | None = None):
    """Rows are keyed by phrase id (meta.pid), not by build row id, so recipes cross-fitted on different builds of the
    same rows pair up. labels: a later build whose labels (label pass) replace the recipe pool's; rows it dropped go."""
    d = build / "zflip" / "crossfit" / recipe
    rec = json.loads((d / "recipe.json").read_text())
    folds = json.loads((build / "folds.json").read_text())
    fold_of = folds["fold"]
    gold = [r for f in rec["pool"] for r in jl(FT / f)]
    id2pid = {r["id"]: r["meta"]["pid"] for r in gold}
    assert len(set(id2pid.values())) == len(gold), "duplicate pids in the pool"
    if labels is not None:
        lab = {r["meta"]["pid"]: r for f in ("zflip/train_real_all.jsonl", "zflip/val_real_all.jsonl") for r in jl(labels / f)}
        new = []
        for r in gold:
            x = lab.get(r["meta"]["pid"])
            if x is None:
                continue
            assert x["options"] == r["options"], f"option list changed for {r['meta']['pid']}"
            new.append({**r, **{k: x[k] for k in ("label", "acceptable", "kind", "confidence", "ambiguous", "gold")}})
        gold = new
    for r in gold:
        r["id"] = r["meta"]["pid"]
    seeds = {}
    for sd in sorted(d.glob("s*")):
        fs = sorted(sd.glob("f*.jsonl"))
        if len(fs) != folds["k"]:
            print(f"{recipe}/{sd.name}: {len(fs)}/{folds['k']} folds, skipped", file=sys.stderr)
            continue
        seeds[int(sd.name[1:])] = {id2pid[x["id"]]: x["logits"] for f in fs for x in jl(f)}
    # novel = phrase not among the training rows of the row's fold (the other folds' apps)
    by_fold = defaultdict(set)
    for r in gold:
        if r.get("phrase"):
            by_fold[fold_of[r["app"]]].add(vstats.phrase_key(r["phrase"]))
    train_ph = {k: set().union(*(v for j, v in by_fold.items() if j != k)) for k in range(folds["k"])}
    novel = {r["id"]: (vstats.phrase_key(r["phrase"]) not in train_ph[fold_of[r["app"]]]) if r.get("phrase") else None for r in gold}
    return rec, gold, seeds, novel


def recs_of(gold, Z, novel, T, b=0.0):
    P = {g["id"]: softmax(Z[g["id"]], T, b) for g in gold if g["id"] in Z}
    rs = vstats.records(gold, P)
    for g, r in zip((g for g in gold if g["id"] in Z), rs):
        r["cl"] = g["app"]           # out-of-app: the app is the resampling unit
        r["novel"] = bool(novel.get(g["id"]))
    return rs


def mets(rs):
    m = vstats.metrics(rs)
    m["none_auroc"] = vstats.auroc([r["p_none"] for r in rs if r["gn"]], [r["p_none"] for r in rs if not r["gn"]])
    return {k: m[k] for k in MKEYS}


def app_resamples(apps, B, seed):
    rng = random.Random(seed)
    for _ in range(B):
        yield [rng.choice(apps) for _ in apps]


def idx_by_app(rs):
    d = defaultdict(list)
    for i, r in enumerate(rs):
        d[r["cl"]].append(i)
    return d


def boot_mean(per_seed: list[list[dict]], B, seed=12345):
    """Seed-mean metric with app-cluster CI. per_seed: aligned record lists (same rows, same order)."""
    by = idx_by_app(per_seed[0])
    apps = sorted(by)
    pt = {k: sum(mets(rs)[k] for rs in per_seed) / len(per_seed) for k in MKEYS}
    bs = defaultdict(list)
    for smp in app_resamples(apps, B, seed):
        idx = [i for a in smp for i in by[a]]
        ms = [mets([rs[i] for i in idx]) for rs in per_seed]
        for k in MKEYS:
            v = sum(m[k] for m in ms) / len(ms)
            if not math.isnan(v):
                bs[k].append(v)
    return {k: (pt[k], vstats.pct(bs[k], .025), vstats.pct(bs[k], .975)) for k in MKEYS}


def boot_paired(A: list[list[dict]], Bm: list[list[dict]], B, seed=12345):
    """Difference of seed-mean metrics A - B, app-cluster resampled together (same rows)."""
    by = idx_by_app(A[0])
    apps = sorted(by)
    mean = lambda L, idx: {k: sum(mets([rs[i] for i in idx])[k] for rs in L) / len(L) for k in MKEYS}  # noqa: E731
    full = list(range(len(A[0])))
    pa, pb = mean(A, full), mean(Bm, full)
    ds = defaultdict(list)
    for smp in app_resamples(apps, B, seed):
        idx = [i for a in smp for i in by[a]]
        ma, mb = mean(A, idx), mean(Bm, idx)
        for k in MKEYS:
            d = ma[k] - mb[k]
            if not math.isnan(d):
                ds[k].append(d)
    out = {}
    for k in MKEYS:
        d = ds[k]
        p = min(1.0, 2 * min(sum(v <= 0 for v in d), sum(v >= 0 for v in d)) / len(d)) if d else float("nan")
        out[k] = (pa[k] - pb[k], vstats.pct(d, .025), vstats.pct(d, .975), p)
    return out


# ---- operating point ---------------------------------------------------------------------------------------------

def beta_ppf(q, a, b):
    """Inverse regularised incomplete beta by bisection (pure python; a, b > 0 may be fractional)."""
    def ibeta(x):
        if x <= 0:
            return 0.0
        if x >= 1:
            return 1.0
        # continued fraction (Numerical Recipes betacf)
        lbt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
        def cf(x, a, b):
            qab, qap, qam = a + b, a + 1, a - 1
            c, d = 1.0, 1 - qab * x / qap
            d = 1 / (d if abs(d) > 1e-30 else 1e-30)
            h = d
            for m in range(1, 300):
                m2 = 2 * m
                aa = m * (b - m) * x / ((qam + m2) * (a + m2))
                d = 1 + aa * d; d = 1 / (d if abs(d) > 1e-30 else 1e-30)
                c = 1 + aa / c if abs(c) > 1e-30 else 1e30
                h *= d * c
                aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
                d = 1 + aa * d; d = 1 / (d if abs(d) > 1e-30 else 1e-30)
                c = 1 + aa / c if abs(c) > 1e-30 else 1e30
                de = d * c
                h *= de
                if abs(de - 1) < 1e-12:
                    break
            return h
        if x < (a + 1) / (a + b + 2):
            return math.exp(lbt) * cf(x, a, b) / a
        return 1 - math.exp(lbt) * cf(1 - x, b, a) / b
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if ibeta(mid) < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def cp_upper(k, n, alpha=0.05):
    """One-sided Clopper-Pearson upper bound; k, n may be fractional (effective counts)."""
    if n <= 0:
        return 1.0
    if k >= n:
        return 1.0
    return beta_ppf(1 - alpha, k + 1, n - k)


def design_effect(groups: dict[str, list[int]]):
    """1 + (m_bar - 1) * ICC for 0/1 outcomes grouped by app (one-way ANOVA ICC, floored at 0)."""
    gs = [g for g in groups.values() if g]
    N = sum(len(g) for g in gs)
    k = len(gs)
    if k < 2 or N <= k:
        return 1.0
    mean = sum(sum(g) for g in gs) / N
    ssb = sum(len(g) * (sum(g) / len(g) - mean) ** 2 for g in gs)
    ssw = sum(sum((x - sum(g) / len(g)) ** 2 for x in g) for g in gs)
    msb, msw = ssb / (k - 1), ssw / (N - k)
    n0 = (N - sum(len(g) ** 2 for g in gs) / N) / (k - 1)
    icc = max(0.0, (msb - msw) / (msb + (n0 - 1) * msw)) if (msb + (n0 - 1) * msw) > 0 else 0.0
    mbar = N / k
    return 1 + (mbar - 1) * icc, icc


def decide(p, t_tap, t_none):
    t = vstats.top(p)
    ni = len(p) - 1
    if t == ni:
        return ("none", ni) if p[ni] >= t_none else ("defer", None)
    return ("tap", t) if p[t] >= t_tap else ("defer", None)


def op_eval(gold_by_id, P_seeds: list[dict], t_tap, t_none, alpha=0.05):
    ns = len(P_seeds)
    c = defaultdict(float)
    wrong_by_app = defaultdict(list)
    for P in P_seeds:
        for i, p in P.items():
            g = gold_by_id[i]
            ni = len(g["options"]) - 1
            acc = set(g.get("acceptable") or [g["label"]])
            d, k = decide(p, t_tap, t_none)
            c["n"] += 1
            if d == "tap":
                ok = k in acc
                c["tap"] += 1; c["tap_ok"] += ok; c["tap_wrong"] += not ok; c["tap_on_none"] += g["label"] == ni
                wrong_by_app[g["app"]].append(int(not ok))
            elif d == "none":
                c["none"] += 1; c["none_ok"] += g["label"] == ni
            else:
                c["defer"] += 1
    deff, icc = design_effect(wrong_by_app)
    taps = c["tap"] / ns
    n_eff = taps / deff
    rate = c["tap_wrong"] / c["tap"] if c["tap"] else 0.0
    ub = cp_upper(rate * n_eff, n_eff, alpha)
    n = c["n"]
    return {"tap_rate": c["tap"] / n, "wrong_tap_per_tap": rate, "wrong_tap_ub95": ub, "deff": deff, "icc": icc, "n_eff_taps": n_eff,
            "wrong_tap_per_row": c["tap_wrong"] / n, "gold_none_tapped_per_row": c["tap_on_none"] / n,
            "none_rate": c["none"] / n, "none_precision": c["none_ok"] / c["none"] if c["none"] else float("nan"),
            "defer_rate": c["defer"] / n, "resolved_correct": (c["tap_ok"] + c["none_ok"]) / n,
            "utility": (c["tap_ok"] + c["none_ok"] - (c["none"] - c["none_ok"])) / n}


def fit_operating_point(gold, seeds_Z, novel, max_wrong, alpha=0.05):
    gold_by_id = {g["id"]: g for g in gold}
    rows = [g for g in gold if all(g["id"] in Z for Z in seeds_Z)]
    pooled = [(g, Z) for Z in seeds_Z for g in rows]
    # one T for the pooled seeds (NLL)
    def nll(T):
        return sum(-math.log(max(softmax(Z[g["id"]], T)[g["label"]], 1e-12)) for g, Z in pooled) / len(pooled)
    lo, hi, gr = 0.3, 6.0, (math.sqrt(5) - 1) / 2
    for _ in range(40):
        a, b = hi - gr * (hi - lo), lo + gr * (hi - lo)
        lo, hi = (lo, b) if nll(a) < nll(b) else (a, hi)
    T = (lo + hi) / 2
    grid_b = [x / 4 for x in range(-8, 9)]
    grid_tap = [x / 100 for x in range(30, 100, 2)]
    grid_none = [x / 100 for x in range(50, 100, 5)]
    best, table = None, []
    for b in grid_b:
        Ps = [{g["id"]: softmax(Z[g["id"]], T, b) for g in rows} for Z in seeds_Z]
        for tt in grid_tap:
            # the tap bound depends on t_tap only (t_none only changes none/defer): check it once per (b, tt)
            e0 = op_eval(gold_by_id, Ps, tt, 1.01, alpha)
            if e0["wrong_tap_ub95"] > max_wrong:
                continue
            for tn in grid_none:
                e = op_eval(gold_by_id, Ps, tt, tn, alpha)
                e.update({"b": b, "t_tap": tt, "t_none": tn})
                table.append(e)
                if best is None or e["utility"] > best["utility"] + 1e-12:
                    best = e
    # per-seed spread of the chosen point (stability), and the no-threshold reference
    per_seed = []
    ref = None
    if best:
        for Z in seeds_Z:
            P = {g["id"]: softmax(Z[g["id"]], T, best["b"]) for g in rows}
            per_seed.append(op_eval(gold_by_id, [P], best["t_tap"], best["t_none"], alpha))
        ref = op_eval(gold_by_id, [{g["id"]: softmax(Z[g["id"]], T) for g in rows} for Z in seeds_Z], 0.0, 0.0, alpha)
    return {"T": T, "best": best, "per_seed": per_seed, "argmax_reference": ref, "n_feasible": len(table),
            "frontier": sorted(table, key=lambda e: -e["utility"])[:15]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", default="data/real-targets-v2/b2")
    ap.add_argument("--recipes", nargs="+", required=True)
    ap.add_argument("--baseline", default=None, help="paired comparisons of every other recipe against this one")
    ap.add_argument("--fit", default=None, help="fit T / none bias / thresholds on this recipe's out-of-app preds")
    ap.add_argument("--max-wrong-tap", type=float, default=0.05)
    ap.add_argument("--B", type=int, default=1000)
    ap.add_argument("--out", default="")
    ap.add_argument("--labels", default=None, help="score against this build's labels (matched by phrase id), e.g. after the label pass")
    a = ap.parse_args()
    build = FT / a.build
    res = {"build": a.build, "labels": a.labels, "recipes": {}}
    md = [f"### Leave-apps-out cross-fit ({a.build}; app-cluster 95% CIs, B={a.B})", ""]
    per = {}
    for rname in a.recipes:
        rec, gold, seeds, novel = load(build, rname, FT / a.labels if a.labels else None)
        if not seeds:
            raise SystemExit(f"{rname}: no complete seed")
        rows = [g for g in gold if all(g["id"] in Z for Z in seeds.values())]
        Ts = {s: fit_T(rows, Z) for s, Z in seeds.items()}
        RS = [recs_of(rows, Z, novel, Ts[s]) for s, Z in sorted(seeds.items())]
        per[rname] = (rows, RS)
        seed_m = {s: mets(rs) for s, rs in zip(sorted(seeds), RS)}
        sd = {k: (statistics_sd([m[k] for m in seed_m.values()])) for k in MKEYS}
        bm = boot_mean(RS, a.B)
        res["recipes"][rname] = {"n_rows": len(rows), "n_apps": len({g["app"] for g in rows}), "seeds": sorted(seeds), "T": Ts,
                                 "seed_mean": bm, "per_seed": seed_m, "seed_sd": sd, "n_novel": sum(bool(novel.get(g["id"])) for g in rows),
                                 "mix_args": rec["mix_args"], "train_args": rec["train_args"]}
    f = lambda t: f"{t[0]:.3f} [{t[1]:.3f}, {t[2]:.3f}]"  # noqa: E731
    md += ["| recipe | seeds | rows / apps | NLL | none AUROC | target acc | novel acc | acc | none recall |", "|---|---|---|---|---|---|---|---|---|"]
    for rname, r in res["recipes"].items():
        m = r["seed_mean"]
        md.append(f"| {rname} | {len(r['seeds'])} | {r['n_rows']} / {r['n_apps']} | {f(m['nll'])} | {f(m['none_auroc'])} | {f(m['target_acc'])} | "
                  f"{f(m['novel_acc'])} (n={r['n_novel']}) | {f(m['acc'])} | {f(m['none_recall'])} |")
    md += ["", "Seed SD (noise floor of one run): " + "; ".join(
        f"{rn}: " + ", ".join(f"{k} {v:.4f}" for k, v in r["seed_sd"].items() if not math.isnan(v)) for rn, r in res["recipes"].items()), ""]
    if a.baseline and len(a.recipes) > 1:
        res["paired"] = {}
        rows_b, RS_b = per[a.baseline]
        ids_b = [g["id"] for g in rows_b]
        md += [f"Paired against {a.baseline} (difference of seed means, same rows, app resampling):", "",
               "| recipe | " + " | ".join(MKEYS) + " |", "|---" * (len(MKEYS) + 1) + "|"]
        for rname in a.recipes:
            if rname == a.baseline:
                continue
            rows_c, RS_c = per[rname]
            common = [i for i in ids_b if i in {g["id"] for g in rows_c}]
            pos_b = {g["id"]: j for j, g in enumerate(rows_b)}
            pos_c = {g["id"]: j for j, g in enumerate(rows_c)}
            A = [[rs[pos_c[i]] for i in common] for rs in RS_c]
            Bm = [[rs[pos_b[i]] for i in common] for rs in RS_b]
            p = boot_paired(A, Bm, a.B)
            res["paired"][rname] = {"n_common": len(common), **p}
            md.append(f"| {rname} | " + " | ".join(f"{p[k][0]:+.4f} [{p[k][1]:+.4f}, {p[k][2]:+.4f}]" for k in MKEYS) + " |")
        md.append("")
    if a.fit:
        rec, gold, seeds, novel = load(build, a.fit, FT / a.labels if a.labels else None)
        op = fit_operating_point(gold, [Z for _, Z in sorted(seeds.items())], novel, a.max_wrong_tap)
        res["operating_point"] = {"recipe": a.fit, "max_wrong_tap_ub95": a.max_wrong_tap, **op}
        b = op["best"]
        md += [f"Operating point fitted on {a.fit} out-of-app preds ({len(seeds)} seeds pooled): T={op['T']:.3f}", ""]
        if b is None:
            md.append(f"No (b, t_tap, t_none) keeps the CP upper bound of the wrong-tap rate <= {a.max_wrong_tap}.")
        else:
            r0 = op["argmax_reference"]
            md += ["| | none bias | t_tap | t_none | tap rate | wrong taps / taps (CP95 UB, deff) | none rate (precision) | defer rate | resolved correct |",
                   "|---|---|---|---|---|---|---|---|---|",
                   f"| fitted | {b['b']:+.2f} | {b['t_tap']:.2f} | {b['t_none']:.2f} | {b['tap_rate']:.3f} | {b['wrong_tap_per_tap']:.3f} "
                   f"({b['wrong_tap_ub95']:.3f}, {b['deff']:.2f}) | {b['none_rate']:.3f} ({b['none_precision']:.3f}) | {b['defer_rate']:.3f} | {b['resolved_correct']:.3f} |",
                   f"| argmax, no thresholds | 0 | 0 | 0 | {r0['tap_rate']:.3f} | {r0['wrong_tap_per_tap']:.3f} ({r0['wrong_tap_ub95']:.3f}, {r0['deff']:.2f}) | "
                   f"{r0['none_rate']:.3f} ({r0['none_precision']:.3f}) | {r0['defer_rate']:.3f} | {r0['resolved_correct']:.3f} |"]
            md += ["", "Per seed at the fitted point: " + "; ".join(
                f"tap {e['tap_rate']:.3f}, wrong/tap {e['wrong_tap_per_tap']:.3f}, defer {e['defer_rate']:.3f}" for e in op["per_seed"])]
        md.append("")
    text = "\n".join(md)
    print(text)
    tag = Path(a.build).name + "." + "+".join(a.recipes) + (f".fit-{a.fit}" if a.fit else "") + (f".labels-{Path(a.labels).name}" if a.labels else "")
    out = Path(a.out) if a.out else FT / "sweeps" / "eval" / f"cf.{tag}.json"
    out.write_text(json.dumps(res, indent=1, default=float))
    out.with_suffix(".md").write_text(text)


def statistics_sd(xs):
    xs = [x for x in xs if not (isinstance(x, float) and math.isnan(x))]
    if len(xs) < 2:
        return float("nan")
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


if __name__ == "__main__":
    main()
