"""Leave-apps-out cross-fit for recipe selection (SPLIT.md amendment 2026-09-27).

Every held-in row (train + val of the build) gets an out-of-app prediction: fold k trains on the apps of the other
folds (<build>/folds.json; forks share a fold) and predicts the apps of fold k. Recipes are compared on these pooled
out-of-app predictions (students/verdict/cf_eval.py), never on dev-test or the locked test.

    python students/verdict/crossfit.py --recipe ref --build data/real-targets-v2/b2 --seeds 0 1 2 \
        [--mix-args "--real-rep 3 --syn 12000"] [--train-args "--lr 5e-5 --epochs 3"] [--pool FILE] [--extra FILE ...]

--pool      held-in rows to cross-fit (default: <build>/zflip/train_real_all.jsonl + val_real_all.jsonl). A recipe that
            changes option text or phrases passes its own pool with the SAME row ids, so recipes stay paired.
--extra     extra TRAINING-only rows (hard negatives, augmentation) with an "app" field (and "phrase_app" for screen
            swaps); used in a fold only when those apps are training apps of that fold. Never predicted.
Fold checkpoints are deleted after prediction (regenerable). Output (local only; contains Z Flip ids):
<build>/zflip/crossfit/<recipe>/s<seed>/f<k>.jsonl  {id, logits, fold, seed}, plus recipe.json.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import vlib  # noqa: F401
import torch

FT = Path(__file__).resolve().parents[2]


def jl(p):
    return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]


def wjl(p, rows):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipe", required=True)
    ap.add_argument("--build", default="data/real-targets-v2/b2")
    ap.add_argument("--seeds", type=int, nargs="+", default=[0])
    ap.add_argument("--folds", type=int, nargs="*", default=None)
    ap.add_argument("--mix-args", default="")
    ap.add_argument("--train-args", default="--lr 5e-5 --epochs 3")
    ap.add_argument("--init", default="students/verdict/runs/verdict-bi-targets-v2")
    ap.add_argument("--pool", nargs="*", default=None)
    ap.add_argument("--extra", nargs="*", default=[])
    ap.add_argument("--keep-ckpt", action="store_true")
    a = ap.parse_args()
    B = FT / a.build
    folds = json.loads((B / "folds.json").read_text())
    fold_of = folds["fold"]
    pool_files = a.pool or [str(B / "zflip" / "train_real_all.jsonl"), str(B / "zflip" / "val_real_all.jsonl")]
    pool = [r for f in pool_files for r in jl(FT / f)]
    extra = [r for f in a.extra for r in jl(FT / f)]
    ids = [r["id"] for r in pool]
    assert len(ids) == len(set(ids)), "duplicate ids in the pool"
    missing = {r["app"] for r in pool if r["app"] not in fold_of}
    assert not missing, f"apps without a fold: {missing}"
    out = B / "zflip" / "crossfit" / a.recipe
    out.mkdir(parents=True, exist_ok=True)
    rec = {"recipe": a.recipe, "at": datetime.datetime.now().isoformat(timespec="seconds"), "argv": sys.argv, "build": a.build,
           "manifest_sha256": sha(B / "MANIFEST.json"), "folds_sha256": sha(B / "folds.json"), "pool": pool_files,
           "pool_sha256": [sha(FT / f) for f in pool_files], "extra": a.extra, "extra_sha256": [sha(FT / f) for f in a.extra],
           "mix_args": a.mix_args, "train_args": a.train_args, "init": a.init}
    rp = out / "recipe.json"
    if rp.exists():
        old = json.loads(rp.read_text())
        for k in ("pool_sha256", "extra_sha256", "mix_args", "train_args", "init", "folds_sha256"):
            if old.get(k) != rec[k]:
                raise SystemExit(f"{rp} exists with a different {k}: use a new --recipe name")
        rec["seeds_done"] = old.get("seeds_done", [])
    rp.write_text(json.dumps(rec, indent=1))
    ks = a.folds if a.folds is not None else list(range(folds["k"]))
    for seed in a.seeds:
        for k in ks:
            pred_f = out / f"s{seed}" / f"f{k}.jsonl"
            if pred_f.exists():
                print(f"seed {seed} fold {k}: done", flush=True)
                continue
            t0 = time.time()
            work = out / f"s{seed}" / f"work{k}"
            if work.exists():
                shutil.rmtree(work)
            work.mkdir(parents=True)
            # an extra row is used only when its screen's app AND (swaps) its phrase's app are training apps of this fold
            tr = [r for r in pool if fold_of[r["app"]] != k] + [r for r in extra if all(fold_of.get(x, -1) not in (k, -1)
                                                                                         for x in (r["app"], r.get("phrase_app", r["app"])))]
            ho = [r for r in pool if fold_of[r["app"]] == k]
            wjl(work / "real.jsonl", tr)
            py = sys.executable
            subprocess.run([py, "-m", "vox.real_targets_v2", "mix", "--real", str(work / "real.jsonl"), "--out", str(work / "mix.jsonl"),
                            "--seed", str(seed), *shlex.split(a.mix_args)], cwd=FT, check=True, stdout=subprocess.DEVNULL)
            ck = work / "ckpt"
            log = work / "train.log"
            with open(log, "w") as lf:
                subprocess.run([py, "students/verdict/train.py", "--arch", "bi", "--init", a.init, "--train", str(work / "mix.jsonl"),
                                "--val-limit", "0", "--seed", str(seed), "--log-every", "1000", "--out", str(ck), *shlex.split(a.train_args)],
                               cwd=FT, check=True, stdout=lf, stderr=subprocess.STDOUT)
            m = vlib.Student(str(ck), "bi", device="cuda").eval()
            z = {}
            with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
                for i in range(0, len(ho), 64):
                    ch = ho[i:i + 64]
                    for r, v in zip(ch, m.logits(ch)):
                        z[r["id"]] = [round(x, 5) for x in v.float().cpu().tolist()]
            del m
            torch.cuda.empty_cache()
            wjl(pred_f, [{"id": i, "logits": v, "fold": k, "seed": seed} for i, v in z.items()])
            shutil.copy(log, out / f"s{seed}" / f"f{k}.train.log")
            if not a.keep_ckpt:
                shutil.rmtree(work)
            print(f"seed {seed} fold {k}: train {len(tr)} real rows, predicted {len(ho)}; {time.time() - t0:.0f}s", flush=True)
        rec["seeds_done"] = sorted(set(rec.get("seeds_done", [])) | {seed})
        rp.write_text(json.dumps(rec, indent=1))


if __name__ == "__main__":
    main()
