"""Provisional per-feature std floors for fingerprint matching (app/src/main/assets/fp_floors.json).

The matcher standardises each fingerprint feature by the std of the user's enrolled examples. A feature on which every
enrolled class agrees then gets a std equal to its noise, and that noise weighs as much as a separating feature. The
floor stops this: std_used = max(std_enrolled, floor). The floor has to be on the scale of how much the feature varies
across *different* sounds (flooring at the repeat noise would change nothing).

Until the extractor publishes real per-feature scales (extractor/FINGERPRINT.md), this derives provisional floors
from the extractor's real-audio clips: floor = FRACTION x the winsorised (1st-99th percentile) population std of each
fp1 feature over every clip in extractor/results/real_features_frozen_clips.jsonl (speech, non-speech, environmental
sounds, music and hums from several datasets). The vector is built the way extractor/vox_extract/fingerprint.py
builds it, from the same raw fields. Read-only use of extractor/ (no bytecode is written there).

    python3 tools/fp_floors.py            # write app/src/main/assets/fp_floors.json (entry "fp1", provisional)
    python3 tools/fp_floors.py --print    # print the table only

To install real scales later: replace the "fp1" entry (or add "fp2") in the JSON with "provisional": false; no code
change is needed. On a device, the `fp_floors` control op replaces the table without rebuilding.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ANDROID = HERE.parent
EXTRACTOR = Path(os.environ.get("VOX_EXTRACTOR", ANDROID.parent / "extractor"))
CLIPS = EXTRACTOR / "results/real_features_frozen_clips.jsonl"
OUT = ANDROID / "app/src/main/assets/fp_floors.json"
FRACTION = 0.25

sys.dont_write_bytecode = True
# fingerprint.py only needs `math`; load it by path so the package __init__ (numpy) is not imported.
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("vox_fp", EXTRACTOR / "vox_extract/fingerprint.py")
_fp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fp)
FP1_NAMES, cepstrum = _fp.FP1_NAMES, _fp.cepstrum


def fp1_from_clip(r: dict) -> list[float] | None:
    """fp1 from a clip record's raw fields (fingerprint.fingerprint, with logmel8 standing in for the mel sums: the
    cepstrum leaves out coefficient 0, so the dB offset between the two does not matter)."""
    if not r.get("logmel8") or r.get("dur_ms") is None:
        return None
    f0 = r.get("f0_med_hz") or 0.0
    pitched = f0 > 0 and r.get("max_st") is not None
    cent = r.get("centroid_hz") or 0.0
    mel = [10 ** (x / 10.0) for x in r["logmel8"]]
    return [
        math.log2(f0 / 100.0) if f0 > 0 else -3.0,
        (r["max_st"] - r["min_st"]) if pitched else 0.0,
        r.get("pitch_resid_std_st") or 0.0,
        r.get("pitch_rough_st") or 0.0,
        r.get("voiced_frac") or 0.0,
        r.get("strong_voiced_frac") or 0.0,
        r.get("clarity_med") or 0.0,
        math.log2(max(cent, 50.0) / 1000.0),
        r.get("centroid_spread_oct") or 0.0,
        r.get("flatness") or 0.0,
        r.get("zcr") or 0.0,
        r.get("lf_ratio") or 0.0,
        r.get("hf_ratio") or 0.0,
        r.get("e1k") or 0.0,
        r.get("e35f0") or 0.0,
        math.log2(max(r["dur_ms"], 10) / 100.0),
        r.get("energy_iqr_db") or 0.0,
        r.get("flux_mean_db") or 0.0,
        r.get("onset_flux_db") or 0.0,
        r.get("decay_db") or 0.0,
    ] + cepstrum(mel)


def winsorised_std(xs: list[float], lo: float = 0.01, hi: float = 0.99) -> float:
    s = sorted(xs)
    a, b = s[int(lo * (len(s) - 1))], s[int(hi * (len(s) - 1))]
    c = [min(max(x, a), b) for x in xs]
    m = sum(c) / len(c)
    return math.sqrt(sum((x - m) ** 2 for x in c) / len(c))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", action="store_true")
    a = ap.parse_args()
    cols: list[list[float]] = [[] for _ in FP1_NAMES]
    datasets: dict[str, int] = {}
    with CLIPS.open() as f:
        for line in f:
            r = json.loads(line)
            v = fp1_from_clip(r)
            if v is None:
                continue
            datasets[r.get("dataset", "?")] = datasets.get(r.get("dataset", "?"), 0) + 1
            for j, x in enumerate(v):
                cols[j].append(x)
    n = len(cols[0])
    stds = [winsorised_std(c) for c in cols]
    floors = [round(FRACTION * s, 4) for s in stds]
    entry = {
        "provisional": True,
        "source": (f"tools/fp_floors.py: {FRACTION} x winsorised population std over {n} real clips "
                   f"({', '.join(f'{k} {v}' for k, v in sorted(datasets.items()))}) from "
                   "extractor/results/real_features_frozen_clips.jsonl; replace with the extractor's per-feature scales"),
        "names": FP1_NAMES,
        "floor": floors,
    }
    for name, s, fl in zip(FP1_NAMES, stds, floors):
        print(f"{name:22s} pop_std {s:9.4f}  floor {fl:8.4f}")
    print(f"{n} clips: {datasets}")
    if not a.print:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps({"fp1": entry}, indent=1) + "\n")
        print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
