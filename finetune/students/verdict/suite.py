"""Score a Verdict bi run on every evaluation set in ONE process, with screen-bootstrap CIs, paired tests against the
champion, the regression gate and a markdown table.

    python students/verdict/suite.py --run students/verdict/runs/<name> [--champion students/verdict/runs/verdict-bi-real-v1d]
           [--build data/real-targets-v2] [--phrase-tf norm] [--sets ...] [--final]

Sets (see SETS): dev-test (test_real, new extraction), test_real_old, val (emulator), val_all (+ Z Flip val), diag_x
(X, Opus phrases, diagnostic), and the three synthetic targets-v2 tests. `locked_test` is scored only with --final
(logged to sweeps/final_evals.jsonl; once per release).

Predictions (logits at T=1 and probs at the run's T) are cached per (set file sha, model, phrase transform):
public sets under preds/real-targets-v2/suite/, Z Flip sets under data/real-targets-v2/zflip/preds/suite/.

Gate (all must hold): syn test_iid acc >= 0.995; syn test_unseen_apps acc >= 0.97; syn test_unseen_phrasing acc and
val acc / none recall not worse than the champion beyond the paired 95% CI (fail = CI upper bound < 0).
Headline metric: novel-phrase accuracy (rows whose normalised phrase is not in the build's real training phrases).
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import sys
from pathlib import Path

import vlib  # noqa: F401  (sets sys.path, env)
import torch
from common import softmax

import vstats

FT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FT))
from vox.normalize import SPEC_VERSION, phrase_of, transform, with_phrase  # noqa: E402

CHAMPION = "students/verdict/runs/verdict-bi-real-v1d"
SYN = {"v1": "data/targets-v2", "v2": "data/targets-v3/v2"}   # synthetic tests in each option format
# Locked apps whose content a training app also serves (SPLIT.md 2026-09-27b): locked results also reported without them.
LOCKED_OVERLAP = {"com.looker.droidify"}


def run_format(run: str) -> str:
    return json.loads((Path(run) / "student.json").read_text()).get("option_format", "v1")


def rows_for_format(rows: list[dict], fmt: str) -> list[dict]:
    """A model is scored only on rows in the format it was trained on. v2 is never scored on approximated screens
    (v2_approx True / "no_tree"); synthetic-geometry rows are exact by construction."""
    if fmt == "v2":
        return [r for r in rows if r.get("option_format") == "v2" and r.get("v2_approx") in (None, False)]
    return [r for r in rows if r.get("option_format", "v1") == "v1"]


def sets_for(build: str, fmt: str = "v1") -> dict[str, dict]:
    b = build.rstrip("/")
    SYN_ = SYN[fmt]
    return {
        "dev_test": {"path": f"{b}/test_real.jsonl", "private": False, "cluster": True},
        "test_old": {"path": f"{b}/test_real_old.jsonl", "private": False, "cluster": True},
        "val": {"path": f"{b}/val_real.jsonl", "private": False, "cluster": True},
        "val_all": {"path": f"{b}/zflip/val_real_all.jsonl", "private": True, "cluster": True},
        "diag_x": {"path": f"{b}/zflip/diag_x_opus.jsonl", "private": True, "cluster": True},
        "syn_iid": {"path": f"{SYN_}/test_iid.jsonl", "private": False, "cluster": False},
        "syn_apps": {"path": f"{SYN_}/test_unseen_apps.jsonl", "private": False, "cluster": False},
        "syn_phrasing": {"path": f"{SYN_}/test_unseen_phrasing.jsonl", "private": False, "cluster": False},
        "locked_test": {"path": f"{b}/locked_test.jsonl", "private": False, "cluster": True, "final_only": True},
        # exact captures (the app's own options_v1 / options_v2): the v1-vs-v2 ship gate is paired on these screens
        "dev_test_exact": {"path": f"{b}/test_exact.jsonl", "private": False, "cluster": True, "exact_only": True},
        "locked_test_exact": {"path": f"{b}/locked_test_exact.jsonl", "private": False, "cluster": True, "final_only": True,
                              "exact_only": True},
    }


def row_key(r: dict) -> str:
    """Pairing key across builds / formats: the phrase id (same phrase on the same screen), else the row id."""
    return (r.get("meta") or {}).get("pid") or r["id"]


DEFAULT_SETS = ["dev_test", "dev_test_exact", "test_old", "val", "val_all", "diag_x", "syn_iid", "syn_apps", "syn_phrasing"]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def jl(p) -> list[dict]:
    return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]


def model_id(run: str) -> str:
    st = (Path(run) / "model.safetensors").stat()
    return hashlib.sha1(f"{Path(run).resolve()}:{st.st_size}:{st.st_mtime_ns}".encode()).hexdigest()[:10]


def pred_path(set_name: str, spec: dict, run: str, tf: str, file_sha: str) -> Path:
    base = FT / ("data/real-targets-v2/zflip/preds/suite" if spec["private"] else "preds/real-targets-v2/suite")
    return base / f"{set_name}.{Path(run).name}.{tf}.{file_sha[:10]}.{model_id(run)}.jsonl"


class Predictor:
    def __init__(self, device: str):
        self.device, self.models = device, {}

    def get(self, run):
        if run not in self.models:
            self.models[run] = vlib.Student(run, "bi", device=self.device).eval()
        return self.models[run]

    def logits(self, run, rows):
        m = self.get(run)
        out = {}
        ac = torch.autocast("cuda", dtype=torch.bfloat16, enabled=self.device.startswith("cuda"))
        with torch.no_grad(), ac:
            for i in range(0, len(rows), 64):
                ch = rows[i:i + 64]
                for r, z in zip(ch, m.logits(ch)):
                    out[r["id"]] = z.float().cpu().tolist()
        return out


def apply_tf(rows: list[dict], tf: str, seed: int = 0) -> list[dict]:
    if tf == "none":
        return rows
    import random
    f, rng = transform(tf), random.Random(seed)
    out = []
    for r in rows:
        p = r.get("phrase") or phrase_of(r["context"])
        out.append({**r, "context": with_phrase(r["context"], f(p, rng))})
    return out


def get_preds(pr: Predictor, run: str, set_name: str, spec: dict, rows: list[dict], tf: str, file_sha: str) -> dict[str, list[float]]:
    """{id: logits at T=1}, cached."""
    pp = pred_path(set_name, spec, run, tf, file_sha)
    if pp.exists():
        c = {r["id"]: r["logits"] for r in jl(pp)}
        if all(r["id"] in c for r in rows):
            return c
    z = pr.logits(run, apply_tf(rows, tf))
    pp.parent.mkdir(parents=True, exist_ok=True)
    T = pr.get(run).temperature
    pp.write_text("".join(json.dumps({"id": k, "logits": [round(x, 5) for x in v], "probs": [round(x, 6) for x in softmax(v, T)]}) + "\n"
                          for k, v in z.items()))
    return z


def fmt_ci(t, digits=3):
    p, lo, hi = t
    if isinstance(p, float) and math.isnan(p):
        return "n/a"
    return f"{p:.{digits}f} [{lo:.{digits}f}, {hi:.{digits}f}]"


def fmt_d(t):
    d, lo, hi, p = t
    return f"{d:+.3f} [{lo:+.3f}, {hi:+.3f}] p={p:.3f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--name", default="")
    ap.add_argument("--champion", default=CHAMPION)
    ap.add_argument("--build", default="data/real-targets-v2")
    ap.add_argument("--champion-build", default="", help="the champion's own-format build when its option format differs from "
                    "the run's (rows are paired by id; only ids present in both are compared)")
    ap.add_argument("--sets", nargs="+", default=DEFAULT_SETS)
    ap.add_argument("--phrase-tf", default="none", help="none | norm | filler | filler+norm | heavy | heavy+norm | restart+norm")
    ap.add_argument("--train-phrases", default="", help="default <build>/zflip/train_real_all.jsonl (novel-phrase definition)")
    ap.add_argument("--temperature", type=float, default=None, help="override the run's T (both models) for probs")
    ap.add_argument("--B", type=int, default=2000)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--final", action="store_true", help="also score locked_test (logged; once per release)")
    ap.add_argument("--no-gate", action="store_true")
    ap.add_argument("--out-md", default="")
    a = ap.parse_args()
    name = a.name or Path(a.run).name
    fmt = run_format(a.run)
    cfmt = run_format(a.champion) if a.champion else fmt
    if a.champion and cfmt != fmt and not a.champion_build:
        raise SystemExit(f"run is {fmt}, champion is {cfmt}: pass --champion-build (the champion's {cfmt} build)")
    specs = sets_for(a.build, fmt)
    cspecs = sets_for(a.champion_build or a.build, cfmt)
    sets = list(a.sets)
    if {"locked_test", "locked_test_exact"} & set(sets) and not a.final:
        raise SystemExit("locked_test is scored only with --final <run> (once per release)")
    if a.final:
        if not (FT / specs["locked_test"]["path"]).exists():
            raise SystemExit("no locked_test.jsonl in this build")
        sets.append("locked_test") if "locked_test" not in sets else None
        if (FT / specs["locked_test_exact"]["path"]).exists() and "locked_test_exact" not in sets:
            sets.append("locked_test_exact")
        log = FT / "sweeps" / "final_evals.jsonl"
        prev = [r for r in jl(log)] if log.exists() else []
        if any(r["run"] == str(Path(a.run).resolve()) for r in prev):
            raise SystemExit(f"{a.run} was already scored on the locked test ({log}); refusing a second look")
        with log.open("a") as f:
            f.write(json.dumps({"run": str(Path(a.run).resolve()), "name": name, "at": datetime.datetime.now().isoformat(timespec="seconds"),
                                "argv": sys.argv, "locked_sha256": sha(FT / specs["locked_test"]["path"])}) + "\n")
    tp = Path(a.train_phrases or f"{a.build}/zflip/train_real_all.jsonl")
    train_phr = {vstats.phrase_key(r["phrase"]) for r in jl(FT / tp) if r.get("phrase")}
    pr = Predictor(a.device)
    models = {"run": a.run} | ({"champion": a.champion} if a.champion and Path(a.champion).resolve() != Path(a.run).resolve() else {})
    res = {"name": name, "run": a.run, "champion": a.champion, "build": a.build, "phrase_tf": a.phrase_tf,
           "normaliser": SPEC_VERSION if "norm" in a.phrase_tf else None, "train_phrases": str(tp), "sets": {}}
    manifest = FT / a.build / "MANIFEST.json"
    if manifest.exists():
        res["manifest_sha256"] = sha(manifest)
    for s in sets:
        spec = specs[s]
        gp = FT / spec["path"]
        if not gp.exists():
            print(f"skip {s}: {gp} missing", flush=True)
            continue
        exact = (lambda rs: [r for r in rs if r.get("options_exact") == "app"]) if spec.get("exact_only") else (lambda rs: rs)  # noqa: E731
        rows = exact(rows_for_format(jl(gp), fmt))
        fsha = sha(gp)
        role_rows = {"run": rows}
        if "champion" in models:
            cgp = FT / cspecs[s]["path"]
            if not cgp.exists():
                print(f"skip {s}: champion set {cgp} missing", flush=True)
                continue
            cby = {row_key(r): r for r in exact(rows_for_format(jl(cgp), cfmt))}
            rows = [r for r in rows if row_key(r) in cby]
            role_rows = {"run": rows, "champion": [cby[row_key(r)] for r in rows]}
            csha = sha(cgp)
        if not rows:
            print(f"skip {s}: no rows in the run's format ({fmt}; v2 is never scored on approximated screens)", flush=True)
            continue
        recs = {}
        for role, run in models.items():
            z = get_preds(pr, run, s, spec, role_rows[role], a.phrase_tf, fsha if role == "run" else csha)
            T = a.temperature if a.temperature is not None else pr.get(run).temperature if run in pr.models else json.loads((Path(run) / "student.json").read_text()).get("temperature", 1.0)
            probs = {k: softmax(v, T) for k, v in z.items()}
            rr = role_rows[role]
            rows_c = [{**r, "screen_id": r["id"]} for r in rr] if not spec["cluster"] else rr
            recs[role] = vstats.records(rows_c, probs, train_phr if spec["cluster"] else None)
        out = {"n": len(rows), "file_sha256": fsha, "option_format": {"run": fmt, "champion": cfmt}}
        for role, rc in recs.items():
            fm = vstats.full_metrics(rc)
            out[role] = {"ci": vstats.bootstrap(rc, a.B), **{k: v for k, v in fm.items()}}
        if "champion" in recs:
            out["paired"] = vstats.paired(recs["run"], recs["champion"], a.B)
        res["sets"][s] = out
        if s in ("locked_test", "locked_test_exact"):   # the same predictions without the overlap app(s)
            keep = [i for i, r in enumerate(rows) if r["package"] not in LOCKED_OVERLAP]
            o2 = {"n": len(keep), "file_sha256": fsha, "without": sorted(LOCKED_OVERLAP)}
            for role, rc in recs.items():
                sub = [rc[i] for i in keep]
                o2[role] = {"ci": vstats.bootstrap(sub, a.B), **vstats.full_metrics(sub)}
            if "champion" in recs:
                o2["paired"] = vstats.paired([recs["run"][i] for i in keep], [recs["champion"][i] for i in keep], a.B)
            res["sets"][s + "_without_overlap"] = o2
        m = out["run"]
        print(f"{s}: n={len(rows)} acc {fmt_ci(m['ci']['acc'])} none_rec {fmt_ci(m['ci']['none_recall'])} "
              f"novel {fmt_ci(m['ci']['novel_acc'])}" + (f" | vs champion acc {fmt_d(out['paired']['acc'])}" if "paired" in out else ""), flush=True)

    # --- gate
    gate = {}
    S = res["sets"]
    if not a.no_gate:
        if "syn_iid" in S: gate["syn_iid acc >= 0.995"] = S["syn_iid"]["run"]["acc"] >= 0.995
        if "syn_apps" in S: gate["syn_apps acc >= 0.97"] = S["syn_apps"]["run"]["acc"] >= 0.97
        for s, ks in (("syn_phrasing", ["acc"]), ("val", ["acc", "none_recall"]), ("val_all", ["acc", "none_recall"])):
            if s in S and "paired" in S[s]:
                for k in ks:
                    gate[f"{s} {k} not worse than champion (CI hi >= 0)"] = S[s]["paired"][k][2] >= 0
        res["gate"] = gate
        res["gate_pass"] = all(gate.values()) if gate else None

    # --- markdown
    L = [f"### Suite: `{name}`" + (f" (phrase transform: {a.phrase_tf})" if a.phrase_tf != "none" else ""), "",
         f"Champion: `{Path(a.champion).name}`. Build: `{a.build}`" + (f" (MANIFEST sha {res.get('manifest_sha256', '')[:12]})" if res.get("manifest_sha256") else "")
         + f". 95% CIs: screen-cluster bootstrap, B={a.B} (synthetic: row bootstrap). Novel = phrase not in `{tp}`.", "",
         "| set | model | n | acc | none recall | false none | novel-phrase acc (n) | target acc | NLL | ECE | none AUROC |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for s, o in S.items():
        for role in [r for r in ("run", "champion") if r in o]:
            m = o[role]
            L.append(f"| {s} | {name if role == 'run' else Path(a.champion).name} | {m['n']} | {fmt_ci(m['ci']['acc'])} | "
                     f"{fmt_ci(m['ci']['none_recall'])} | {m['false_none']:.3f} | "
                     f"{fmt_ci(m['ci']['novel_acc'])} ({m['n_novel']}) | {m['target_acc']:.3f} | {m['nll']:.3f} | {m['ece']:.3f} | "
                     f"{m['none_auroc']:.3f} |")
    if any("paired" in o for o in S.values()):
        L += ["", "Paired differences (run - champion), same screen resamples:", "",
              "| set | acc | none recall | false none | novel acc | NLL | discordant (run only / champ only) |", "|---|---|---|---|---|---|---|"]
        for s, o in S.items():
            if "paired" in o:
                p = o["paired"]
                L.append(f"| {s} | {fmt_d(p['acc'])} | {fmt_d(p['none_recall']) if 'none_recall' in p else 'n/a'} | {fmt_d(p['false_none'])} | "
                         f"{fmt_d(p['novel_acc']) if 'novel_acc' in p else 'n/a'} | {fmt_d(p['nll'])} | {p['discordant'][0]} / {p['discordant'][1]} |")
    if gate:
        L += ["", f"**Gate: {'PASS' if res['gate_pass'] else 'FAIL'}**", ""] + [f"- {'ok' if v else 'FAIL'}: {k}" for k, v in gate.items()]
    md = "\n".join(L) + "\n"
    print(md)
    tag = name + ("" if a.phrase_tf == "none" else "." + a.phrase_tf.replace("+", "_"))
    (FT / "sweeps" / "eval").mkdir(exist_ok=True)
    (FT / "sweeps" / "eval" / f"suite.{tag}.json").write_text(json.dumps(res, indent=1, default=float))
    mdp = Path(a.out_md) if a.out_md else (Path(a.run) / f"suite.{tag}.md" if (Path(a.run) / "student.json").exists() else FT / "sweeps" / "eval" / f"suite.{tag}.md")
    mdp.write_text(md)
    print(f"wrote sweeps/eval/suite.{tag}.json and {mdp}")


if __name__ == "__main__":
    main()
