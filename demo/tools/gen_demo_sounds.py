#!/usr/bin/env python3
"""Precompute what the demo console shows for each canned sound: the real extractor output for the same SYNTHETIC
clips the Pico's canned lines come from (firmware/tools/gen_test_sounds.py), so the console replays true numbers.

    python demo/tools/gen_demo_sounds.py            # writes demo/web/data/sounds.json
    python demo/tools/gen_demo_sounds.py --check    # exit 1 if the lines no longer match firmware/tests/test_sounds.json

Per sound:
  line, label, dur_ms          what the extractor emitted (checked equal to the firmware table's line)
  features {fp, fp_version, pitch16}
                               the fp1 fingerprint and pitch16, exactly as the app's `features` field
  raw {f0_med_hz, level_db, snr_db, ...}
                               the classifier's summary numbers (a few, for the readout)
  frames [[t_ms, e_db, f0, clarity, centroid], ...]
                               the 10 ms front-end frames from 150 ms before the sound to 150 ms after it, t relative
                               to the sound's start: the "mic" the console replays
  wave [peak, ...]             peak |x| per 5 ms over the same span, for the waveform strip

Needs numpy and scipy (the extractor's front end); only this script does, the console reads the JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEMO = HERE.parent
VOX = DEMO.parent
EXTRACTOR = VOX / "extractor"
FW_JSON = VOX / "firmware" / "tests" / "test_sounds.json"
OUT = DEMO / "web" / "data" / "sounds.json"

sys.path.insert(0, str(EXTRACTOR))
sys.path.insert(0, str(VOX / "firmware" / "tools"))

import numpy as np  # noqa: E402

from gen_test_sounds import CHUNK, CLIP_SEQUENCES, RATE, SINGLES  # noqa: E402
from vox_extract import Config  # noqa: E402
from vox_extract.extractor import Extractor  # noqa: E402
from vox_extract.frontend import FrameProcessor  # noqa: E402

PAD_MS = 150
RAW_KEYS = ("f0_med_hz", "level_db", "floor_db", "snr_db", "voiced_frac", "clarity_med", "centroid_hz", "flatness",
            "zcr", "onset_flux_db", "decay_db")
FP1_NAMES = ["f0_oct", "f0_range_st", "pitch_resid_std_st", "pitch_rough_st", "voiced_frac", "strong_voiced_frac",
             "clarity_med", "centroid_oct", "centroid_spread_oct", "flatness", "zcr", "lf_ratio", "hf_ratio", "e1k",
             "e35f0", "dur_oct", "energy_iqr_db", "flux_mean_db", "onset_flux_db", "decay_db", "cep1", "cep2", "cep3",
             "cep4"]


def load(case: str) -> np.ndarray:
    pcm = np.fromfile(EXTRACTOR / "vectors" / f"{case}.pcm", dtype="<i2")
    return pcm.astype(np.float32) / 32768.0


def events(x: np.ndarray) -> list[dict]:
    ex = Extractor(Config(), input_rate=RATE)
    out = []
    for i in range(0, x.size, CHUNK):
        out += ex.push(x[i:i + CHUNK])
    out += ex.flush()
    return [e.to_dict() for e in out if e.emit]


def frames(x: np.ndarray) -> list:
    fp = FrameProcessor(Config())
    return fp.push(x.astype(np.float64))


def entry(name: str, e: dict, fr: list, x: np.ndarray) -> dict:
    t0, t1 = e["t_start_ms"], e["t_end_ms"]
    lo, hi = t0 - PAD_MS, t1 + PAD_MS
    raw = e["raw"]
    rows = [[round(f.t_ms - t0, 1), round(f.e_db, 1), round(f.f0, 1), round(f.clarity, 3), round(f.centroid)]
            for f in fr if lo <= f.t_ms <= hi]
    a, b = max(0, int(lo * RATE / 1000)), min(x.size, int(hi * RATE / 1000))
    step = RATE * 5 // 1000
    seg = np.abs(x[a:b])
    wave = [round(float(seg[i:i + step].max()), 3) for i in range(0, seg.size - step + 1, step)]
    return {
        "name": name, "label": e["label"], "line": e["text"], "dur_ms": int(t1 - t0),
        "features": {"fp": raw["fp"], "fp_version": raw["fp_version"], "pitch16": raw.get("pitch16") or []},
        "raw": {k: raw[k] for k in RAW_KEYS if k in raw},
        "pad_ms": PAD_MS, "frames": rows, "wave": wave,
    }


def entries(name: str, evs: list[dict], x: np.ndarray) -> list[dict]:
    """One entry per event of a 16 kHz clip: `name`, or `name.1`, `name.2`, ... when it holds several.
    Shared with record_demo_sounds.py (recorded takes get the same schema)."""
    fr = frames(x)
    return [entry(name if len(evs) == 1 else f"{name}.{k + 1}", e, fr, x) for k, e in enumerate(evs)]


def build() -> dict:
    sounds = []
    for name, case, labels in SINGLES + CLIP_SEQUENCES:
        x = load(case)
        evs = events(x)
        if [e["label"] for e in evs] != labels:
            raise SystemExit(f"{case}: extractor emitted {[e['label'] for e in evs]}, expected {labels}")
        sounds += entries(name, evs, x)
    return {"generated_by": "demo/tools/gen_demo_sounds.py", "synthetic": True,
            "note": "Real extractor output on the SYNTHETIC clips behind the Pico's canned sounds.",
            "fp1_names": FP1_NAMES,
            "sounds": {s["name"]: s for s in sounds}}


def check(d: dict) -> list[str]:
    fw = {s["name"]: s for s in json.loads(FW_JSON.read_text())["sounds"]}
    bad = []
    for name, s in d["sounds"].items():
        f = fw.get(name)
        if f is None or f["line"] != s["line"] or f["label"] != s["label"]:
            bad.append(name)
    return bad


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="do not write; exit 1 if lines differ from the firmware's")
    a = ap.parse_args()
    d = build()
    bad = check(d)
    if bad:
        print(f"lines differ from {FW_JSON.relative_to(VOX)} for {bad}: reflash / regenerate the firmware table",
              file=sys.stderr)
    if a.check:
        sys.exit(1 if bad else 0)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(d, separators=(",", ":")) + "\n")
    print(f"wrote {OUT.relative_to(VOX)}: {len(d['sounds'])} sounds, {OUT.stat().st_size // 1024} KB"
          + (f" (MISMATCH: {bad})" if bad else ", lines match the firmware table"))


if __name__ == "__main__":
    main()
