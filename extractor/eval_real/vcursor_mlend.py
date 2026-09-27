"""Voice cursor, hums and whistles: how much pitch span do people use, and do hums/whistles carry formants?
(wiki/voice-cursor.md, "Many voices")

Dataset: MLEnd Hums and Whistles (datasets/mlend_hums_whistles): per interpreter and kind, 5 random song files
(seed 1, first 12 s each). Per person: p5-p95 of voiced f0 (Hz and semitones; a song's span is a lower bound on
the comfortable range), and the fraction of voiced frames with an F2 reading. f0 search 1100 Hz for hums,
4000 Hz for whistles (above the spec's voice limit on purpose).
Analysis settings otherwise come from the voice-cursor spec (prompts/voice_cursor_v2.json by default; --spec voice_cursor_v1
for the v1 tracker).

Reproduce (from extractor/; a few minutes):
    ./run python eval_real/vcursor_mlend.py                          # add --spec voice_cursor_v1 for the v1 tracker
"""

from __future__ import annotations

import csv
import random
import sys
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common as C  # noqa: E402
import voice_cursor_test as V  # noqa: E402

R = C.DATA / "mlend_hums_whistles"


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--spec", default="voice_cursor_v2", help="voice-cursor spec version for the analysis settings")
    args = ap.parse_args()
    V.use_spec(V.load_spec(V.spec_path(args.spec)))
    warnings.simplefilter("ignore")
    by = defaultdict(list)
    with (R / "MLEndHWD_audio_attributes_benchmark.csv").open() as fh:
        for r in csv.DictReader(fh):
            by[(r["Interpreter"], r["Interpretation"])].append(r["filename"])
    random.seed(1)
    out = defaultdict(dict)
    for (p, kind), fs in sorted(by.items()):
        V.A["f0_max_hz"] = 1100 if kind == "Hum" else 4000
        f0s, f2ok, n = [], 0, 0
        for f in random.sample(fs, min(5, len(fs))):
            try:
                x, rate = sf.read(str(R / "MLEndHWD_audiofiles" / f), dtype="float32")
            except Exception:
                continue
            if x.ndim > 1:
                x = x.mean(1)
            fr = V.frames(x[: rate * 12], rate)
            v = fr["voiced"]
            f0s += list(fr["f0"][v])
            f2ok += int(np.isfinite(fr["f2"][v]).sum())
            n += int(v.sum())
        if len(f0s) > 100:
            a = V.st(np.array(f0s))
            out[p][kind] = dict(lo=float(np.percentile(f0s, 5)), hi=float(np.percentile(f0s, 95)),
                                span=float(np.percentile(a, 95) - np.percentile(a, 5)), f2frac=f2ok / max(n, 1))
    print(f"MLEnd, {args.spec}, per person: pitch span used in songs (p5-p95), and formant readings")
    for kind in ("Hum", "Whistle"):
        P = [d[kind] for d in out.values() if kind in d]
        sp, lo, hi = (np.array([q[k] for q in P]) for k in ("span", "lo", "hi"))
        print(f"{kind:7s} persons {len(P):3d}  span st p10/med/p90 {np.percentile(sp, 10):.1f}/{np.median(sp):.1f}/{np.percentile(sp, 90):.1f}"
              f"  <12 st {np.mean(sp < 12):.0%}  low end med {np.median(lo):.0f} Hz ({lo.min():.0f}-{lo.max():.0f})"
              f"  high end med {np.median(hi):.0f} Hz  frames with F2 {np.median([q['f2frac'] for q in P]):.0%}"
              f"  high end >1100 Hz {np.mean(hi > 1100):.0%}")


if __name__ == "__main__":
    main()
