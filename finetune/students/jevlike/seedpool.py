"""Seed-pooled comparison of two recipes (each = several seed checkpoints; a Verdict run dir counts as one "seed") on
the suite sets, from suite.py's cached predictions (run suite_jl.py on every checkpoint first; missing preds are computed).

Metric of a recipe = mean over its seeds. Paired difference A - B with a screen-cluster bootstrap that resamples the
screens once and applies them to every seed of both recipes (so seed noise AND screen noise are both in the CI).
Each checkpoint's own T is used for probabilities (NLL, ECE, wrong-tap@t).

    python students/jevlike/seedpool.py --a runs/jl8-J4-s7.pt runs/jl8-J4-s8.pt runs/jl8-J4-s9.pt \
        --b runs/jl8-C-s7.pt runs/jl8-C-s8.pt runs/jl8-C-s9.pt --name jl8-J4-vs-C [--sets dev_test test_old diag_x] [--B 2000]
Writes sweeps/eval/seedpool.<name>.{json,md}. Aggregates only.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import suite_jl  # noqa: E402,F401  (patches students/verdict/suite.py for .pt runs)
from suite_jl import suite, torch  # noqa: E402
import vstats  # noqa: E402  (students/verdict/vstats.py, on sys.path via suite)
from common import softmax  # noqa: E402

FT = HERE.parents[1]
KEYS = ("acc", "none_recall", "false_none", "novel_acc", "nll", "ece", "wrong_tap@0.8", "coverage@0.8", "none_auroc")


def mets(recs):
    m = vstats.metrics(recs)
    if not recs:
        return m
    m["ece"] = vstats.ece([r["conf"] for r in recs], [r["hit"] for r in recs])
    cov = [r for r in recs if r["conf"] >= 0.8]
    taps = [r for r in cov if not r["pn"]]
    m["wrong_tap@0.8"] = sum(not r["hit_a"] for r in taps) / len(recs)
    m["coverage@0.8"] = len(cov) / len(recs)
    m["none_auroc"] = vstats.auroc([r["p_none"] for r in recs if r["gn"]], [r["p_none"] for r in recs if not r["gn"]])
    return m


def T_of(run):
    if run.endswith(".pt"):
        return float(torch.load(run, map_location="cpu", weights_only=False)["config"].get("temperature", 1.0))
    return float(json.loads((Path(run) / "student.json").read_text()).get("temperature", 1.0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", nargs="+", required=True)
    ap.add_argument("--b", nargs="+", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--build", default="data/real-targets-v2/b4a")
    ap.add_argument("--sets", nargs="+", default=["dev_test", "test_old", "diag_x", "val_all"])
    ap.add_argument("--B", type=int, default=2000)
    ap.add_argument("--device", default="cuda")
    a = ap.parse_args()
    specs = suite.sets_for(a.build, "v1")
    train_phr = {vstats.phrase_key(r["phrase"]) for r in suite.jl(FT / a.build / "zflip/train_real_all.jsonl") if r.get("phrase")}
    pr = suite.Predictor(a.device)
    Ts = {r: T_of(r) for r in a.a + a.b}
    res = {"name": a.name, "a": a.a, "b": a.b, "T": Ts, "B": a.B, "sets": {}}
    md = [f"### Seed-pooled: `{a.name}`", "", f"A = {', '.join(Path(r).name for r in a.a)}; B = {', '.join(Path(r).name for r in a.b)}. "
          f"Mean over seeds; paired A - B, screen-cluster bootstrap B={a.B} shared across seeds. T per checkpoint (stored).", "",
          "| set | n | A mean (seed SD) acc | B mean acc | Δacc [95% CI] p | ΔNLL [95% CI] | Δwrong-tap@0.8 [95% CI] | A NLL / B NLL | A wt@0.8 / B wt@0.8 "
          "| A / B none recall | Δnone recall [95% CI] p | Δnone AUROC [95% CI] |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in a.sets:
        spec = specs[s]
        rows = suite.rows_for_format(suite.jl(FT / spec["path"]), "v1")
        if spec.get("exact_only"):
            rows = [r for r in rows if r.get("options_exact") == "app"]
        fsha = suite.sha(FT / spec["path"])
        recs = {}
        for run in a.a + a.b:
            z = suite.get_preds(pr, run, s, spec, rows, "none", fsha)
            probs = {k: softmax(v, Ts[run]) for k, v in z.items()}
            recs[run] = vstats.records(rows, probs, train_phr if spec["cluster"] else None)
        cl = [r["cl"] for r in recs[a.a[0]]]
        assert all([r["cl"] for r in recs[x]] == cl for x in recs), "unaligned rows"

        def pooled(runs, idx):
            ms = [mets([recs[r][i] for i in idx]) for r in runs]
            return {k: statistics.fmean(m[k] for m in ms) if not any(isinstance(m[k], float) and math.isnan(m[k]) for m in ms) else float("nan")
                    for k in KEYS}
        allidx = list(range(len(cl)))
        pa, pb = pooled(a.a, allidx), pooled(a.b, allidx)
        sd = {k: statistics.stdev([mets(recs[r])[k] for r in a.a]) if len(a.a) > 1 else 0.0 for k in ("acc", "nll")}
        ds = {k: [] for k in KEYS}
        for idx in vstats._resamples(recs[a.a[0]], a.B, 12345):
            qa, qb = pooled(a.a, idx), pooled(a.b, idx)
            for k in KEYS:
                d = qa[k] - qb[k]
                if not math.isnan(d):
                    ds[k].append(d)
        diff = {}
        for k in KEYS:
            d = ds[k]
            if d:
                p = min(1.0, 2 * min(sum(v <= 0 for v in d), sum(v >= 0 for v in d)) / len(d))
                diff[k] = (pa[k] - pb[k], vstats.pct(d, .025), vstats.pct(d, .975), p)
        per_seed = {r: {k: mets(recs[r])[k] for k in ("acc", "nll", "wrong_tap@0.8")} for r in a.a + a.b}
        res["sets"][s] = {"n": len(rows), "a": pa, "b": pb, "a_seed_sd": sd, "diff": diff, "per_seed": per_seed}
        f = lambda t: f"{t[0]:+.3f} [{t[1]:+.3f}, {t[2]:+.3f}]"  # noqa: E731
        md.append(f"| {s} | {len(rows)} | {pa['acc']:.3f} ({sd['acc']:.3f}) | {pb['acc']:.3f} | {f(diff['acc'])} p={diff['acc'][3]:.3f} | "
                  f"{f(diff['nll'])} | {f(diff['wrong_tap@0.8'])} | {pa['nll']:.3f} / {pb['nll']:.3f} | {pa['wrong_tap@0.8']:.3f} / {pb['wrong_tap@0.8']:.3f} | "
                  f"{pa['none_recall']:.3f} / {pb['none_recall']:.3f} | {f(diff['none_recall'])} p={diff['none_recall'][3]:.3f} | {f(diff['none_auroc'])} |")
        print(md[-1], flush=True)
    out = FT / "sweeps" / "eval" / f"seedpool.{a.name}"
    Path(f"{out}.json").write_text(json.dumps(res, indent=1, default=float))
    Path(f"{out}.md").write_text("\n".join(md) + "\n")
    print(f"wrote {out}.json/.md")


if __name__ == "__main__":
    main()
