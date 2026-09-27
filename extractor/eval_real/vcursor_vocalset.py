"""Voice cursor, singing: where does the ee/ah/oo reading break with pitch, and does the smoother tame vibrato?
(wiki/voice-cursor.md, "Many voices")

Dataset: VocalSet (datasets/vocalset/FULL): 20 trained singers (female1-9, male1-11), a/i/u = ah/ee/oo files,
minus lip trill, vocal fry, inhaled and trill.
Per singer and per F0 band: 250 ms vowel windows (the calibration's own, after the 200 ms smoother), classified
leave-one-file-out by nearest vowel centre learned in the same band (voice_cursor_test.loo_vowel_accuracy, the
scorer's function). Also ee-vs-oo only, and the error pattern. Vibrato: pitch/F2 SD per window, raw vs smoothed,
on long_tones/forte + *vibrato* files vs long_tones/straight.
Analysis settings come from the voice-cursor spec (prompts/voice_cursor_v2.json by default; --spec voice_cursor_v1 for the
v1 tracker), f0 search raised to 1400 Hz.

Reproduce (from extractor/; ~20 s on 20 cores):
    ./run python eval_real/vcursor_vocalset.py --only long_tones   # the wiki table
    ./run python eval_real/vcursor_vocalset.py                     # all a/i/u material (arpeggios, scales too)
    (add --spec voice_cursor_v1 for the v1 tracker)
"""

from __future__ import annotations

import argparse
import re
import sys
import warnings
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common as C  # noqa: E402
import voice_cursor_test as V  # noqa: E402

F = C.DATA / "vocalset" / "FULL"
VOW = {"i": "ee", "a": "ah", "u": "oo"}
SKIP = ("lip_trill", "vocal_fry", "inhaled", "trill", "fry")
BANDS = [(0, 200), (200, 300), (300, 400), (400, 550), (550, 2000)]
ONLY = None
NW = NS = 0


def setup(version: str) -> None:
    """Analysis settings from the spec, with the f0 search raised for sopranos. Runs before the pool forks."""
    global NW, NS
    V.use_spec(V.load_spec(V.spec_path(version)))
    V.A["f0_max_hz"] = 1400
    hop_ms = 1000 * V.A["hop"] / V.A["fs"]
    NW, NS = round(V.A["vowel_window_ms"] / hop_ms), round(V.A["smooth_ms"] / hop_ms)


def nearest(cent: dict, x1: float, x2: float) -> str:
    return min(cent, key=lambda c: (cent[c][0] - x1) ** 2 + (cent[c][1] - x2) ** 2)


def singer(d: Path) -> dict:
    warnings.simplefilter("ignore")
    wins, allf0, wob = [], [], {"straight": [], "vib": []}
    for f in sorted(d.rglob("*.wav")):
        m = re.search(r"_([aiu])\.wav$", f.name)
        if not m or any(s in str(f) for s in SKIP) or (ONLY and ONLY not in str(f)):
            continue
        vib = "long_tones/forte" in str(f) or "vibrato" in f.name
        strt = "long_tones/straight" in str(f)
        x, r = sf.read(str(f), dtype="float32")
        if x.ndim > 1:
            x = x.mean(1)
        fr = V.frames(x[: r * 40], r)
        k = np.flatnonzero(fr["voiced"])
        allf0 += list(fr["f0"][k])
        f1s, f2s = V.smooth(fr["f1"], NS), V.smooth(fr["f2"], NS)
        pst = V.smooth(V.st(np.where(fr["voiced"], fr["f0"], np.nan)), NS)
        for s0 in range(0, k.size - NW + 1, NW):
            w = k[s0:s0 + NW]
            if w[-1] - w[0] > NW + 5:          # window must be one stretch of voice
                continue
            f0 = float(np.median(fr["f0"][w]))
            ok = np.isfinite(fr["f2"][w]).mean() >= V.A["vowel_window_min_formant_frac"] and np.isfinite(f2s[w]).any()
            wins.append((f.name, VOW[m.group(1)], f0,
                         float(V.bark(np.nanmedian(f1s[w]))) if ok else None, float(V.bark(np.nanmedian(f2s[w]))) if ok else None))
            if vib or strt:
                wob["vib" if vib else "straight"].append((float(np.std(V.st(fr["f0"][w]))), float(np.nanstd(pst[w])),
                                                          float(np.nanstd(fr["f2"][w])), float(np.nanstd(f2s[w]))))
    res = {"singer": d.name, "bands": {}, "wobble": {k: np.nanmedian(np.array(v), 0).tolist() for k, v in wob.items() if v}}
    for lo, hi in BANDS:
        W = [w for w in wins if lo <= w[2] < hi]
        if len({w[1] for w in W}) < 3 or len(W) < 12:
            continue
        ok = [(g, v, x1, x2) for g, v, _, x1, x2 in W if x1 is not None]
        conf = Counter()
        for g, v, x1, x2 in ok:
            cent = {vv: np.mean([(y1, y2) for gg, v2, y1, y2 in ok if v2 == vv and gg != g] or [(99, 99)], 0) for vv in VOW.values()}
            conf[f"{v}>{nearest(cent, x1, x2)}"] += 1
        res["bands"][f"{lo}-{hi}"] = {"n": len(W), "read": len(ok) / len(W), "acc": V.loo_vowel_accuracy(ok) or 0.0,
                                      "acc2": V.loo_vowel_accuracy([w for w in ok if w[1] != "ah"]) or 0.0, "conf": dict(conf)}
    return res


def main() -> None:
    global ONLY
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", help="path substring filter, e.g. long_tones")
    ap.add_argument("--jobs", type=int, default=20)
    ap.add_argument("--spec", default="voice_cursor_v2", help="voice-cursor spec version for the analysis settings")
    a = ap.parse_args()
    ONLY = a.only
    setup(a.spec)
    with Pool(a.jobs) as p:
        R = p.map(singer, sorted(d for d in F.iterdir() if d.is_dir()))
    print(f"VocalSet a/i/u ({a.only or 'all material'}), {a.spec}, {len(R)} singers, 250 ms windows, leave-one-file-out")
    print("F0 band    singers  windows  3-vowel acc med (p10)  bands>=0.9  ee-vs-oo>=0.9  top errors")
    for lo, hi in BANDS:
        b = f"{lo}-{hi}"
        E = [r["bands"][b] for r in R if b in r["bands"]]
        if not E:
            continue
        acc, acc2 = np.array([e["acc"] for e in E]), np.array([e["acc2"] for e in E])
        conf = Counter()
        for e in E:
            conf.update(e["conf"])
        tot = sum(conf.values())
        errs = ", ".join(f"{k} {v / tot:.0%}" for k, v in conf.most_common() if k[:2] != k[3:])[:48]
        print(f"{b:9s}  {len(E):6d}  {sum(e['n'] for e in E):7d}   {np.median(acc):.2f} ({np.percentile(acc, 10):.2f})"
              f"           {np.mean(acc >= .9):4.0%}        {np.mean(acc2 >= .9):4.0%}      {errs}")
    for thr in (0.9, 0.8):
        anyb = [any(b["acc"] >= thr for b in r["bands"].values()) for r in R]
        fb = [b["acc"] < thr for r in R for b in r["bands"].values()]
        print(f"fallback at vowel_acc_min {thr}: singers with >=1 vowel band {np.mean(anyb):.0%}, bands that snap {np.mean(fb):.0%}")
    for k, name in (("vib", "vibrato"), ("straight", "straight")):
        W = np.array([r["wobble"][k] for r in R if k in r["wobble"]])
        if W.size:
            m = np.nanmedian(W, 0)
            print(f"{name:8s} pitch SD {m[0]:.2f} st -> {m[1]:.2f} st smoothed;  F2 SD {m[2]:.0f} Hz -> {m[3]:.0f} Hz smoothed")


if __name__ == "__main__":
    main()
