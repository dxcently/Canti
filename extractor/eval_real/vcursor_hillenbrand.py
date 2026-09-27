"""Voice cursor, speech: does the tracker read ee/ah/oo for men, women and children? (wiki/voice-cursor.md, "Many voices")

Dataset: Hillenbrand et al. 1995 (datasets/hillenbrand/data): 139 talkers, /hVd/ words, hand-measured F0/F1/F2 in
vowdata.dat. Uses iy/ah/uw = ee/ah/oo.
Per talker, 50 ms windows of the vowel's middle 40 % (the vowels last only ~250 ms, so shorter than the calibration's
250 ms windows) are classified by nearest vowel centre (Bark F1/F2), the centres being that talker's own hand-measured
values. A window with no formant reading counts as a miss. Also: tracker F2 vs hand F2.
Analysis settings come from the voice-cursor spec (prompts/voice_cursor_v2.json by default; --spec voice_cursor_v1 for the
v1 tracker) via voice_cursor_test.py.

Reproduce (from extractor/):
    ./run python eval_real/vcursor_hillenbrand.py                  # spec F2 ceiling (3600 Hz)
    ./run python eval_real/vcursor_hillenbrand.py --f2-max 3000    # the old ceiling, for the before/after
    ./run python eval_real/vcursor_hillenbrand.py --spec voice_cursor_v1   # the v1 tracker
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common as C  # noqa: E402
import voice_cursor_test as V  # noqa: E402

D = C.DATA / "hillenbrand" / "data"
VW = {"iy": "ee", "ah": "ah", "uw": "oo"}
GROUP = {"m": "men", "w": "women", "b": "boys", "g": "girls"}
FOLDER = {"m": "men", "w": "women", "b": "kids", "g": "kids"}


def truth() -> dict:
    out = {}
    for line in (D / "vowdata.dat").read_text().splitlines():
        p = line.split()
        if len(p) == 16 and p[0][:1] in "mwbg" and p[1].isdigit():
            out[p[0]] = dict(f0=float(p[2]), f1=float(p[3]), f2=float(p[4]))
    return out


def talker(s: str, tv: dict) -> dict | None:
    cent = {v: (V.bark(t["f1"]), V.bark(t["f2"])) for v, t in tv.items()}
    hits = n = 0
    err = []
    for v in VW:
        f = D / FOLDER[s[0]] / f"{s}{v}.wav"
        if not f.exists():
            continue
        x, r = sf.read(str(f), dtype="float32")
        fr = V.frames(x, r)
        vi = np.flatnonzero(fr["voiced"])
        if vi.size < 8:
            continue
        mid = vi[int(vi.size * 0.3):int(vi.size * 0.7) + 1]
        if np.isfinite(fr["f2"][mid]).any():
            err.append(abs(np.nanmedian(fr["f2"][mid]) - tv[v]["f2"]))
        for s0 in range(0, mid.size - 4, 5):
            w = mid[s0:s0 + 5]
            n += 1
            if np.isfinite(fr["f2"][w]).mean() < 0.5:
                continue
            x1, x2 = V.bark(np.nanmedian(fr["f1"][w])), V.bark(np.nanmedian(fr["f2"][w]))
            hits += min(cent, key=lambda c: (cent[c][0] - x1) ** 2 + (cent[c][1] - x2) ** 2) == v
    if not n:
        return None
    return dict(type=s[0], f0=float(np.median([t["f0"] for t in tv.values()])), acc=hits / n,
                f2err=float(np.median(err)) if err else None)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--f2-max", type=int, help="override the spec's F2 ceiling (Hz)")
    ap.add_argument("--spec", default="voice_cursor_v2", help="voice-cursor spec version for the analysis settings")
    a = ap.parse_args()
    V.use_spec(V.load_spec(V.spec_path(a.spec)))
    if a.f2_max:
        V.A["f2_hz"] = [V.A["f2_hz"][0], a.f2_max]
    T = truth()
    rows = []
    for s in sorted({k[:3] for k in T}):
        tv = {v: T.get(s + v) for v in VW}
        if all(tv.values()) and all(t["f1"] and t["f2"] for t in tv.values()):
            r = talker(s, tv)
            if r:
                rows.append(r)
    print(f"Hillenbrand ee/ah/oo, {a.spec}, F2 ceiling {V.A['f2_hz'][1]} Hz, {len(rows)} talkers")
    print("group   n  F0 med  acc med  talkers>=0.9  >=0.8  F2 err med Hz")
    for t, name in GROUP.items():
        R = [r for r in rows if r["type"] == t]
        a_ = np.array([r["acc"] for r in R])
        print(f"{name:6s} {len(R):2d}  {np.median([r['f0'] for r in R]):5.0f}   {np.median(a_):.2f}      {np.mean(a_ >= .9):4.0%}"
              f"      {np.mean(a_ >= .8):4.0%}  {np.median([r['f2err'] for r in R if r['f2err'] is not None]):5.0f}")
    a_ = np.array([r["acc"] for r in rows])
    for thr in (0.9, 0.8):
        print(f"fallback at vowel_acc_min {thr}: talkers with vowel {np.mean(a_ >= thr):.0%}, snap {np.mean(a_ < thr):.0%}")


if __name__ == "__main__":
    main()
