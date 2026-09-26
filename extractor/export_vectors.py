#!/usr/bin/env python3
"""Export test vectors for the C port of the extractor. The audio is SYNTHETIC (synth.py).

    ./run python export_vectors.py [--out vectors] [--seed 424242]

Writes
  vectors/manifest.json   config (every threshold), vocabulary + digest, the input high-pass biquad,
                          the 48k->16k decimator taps, frame-time formula, tolerances, and the list of cases
  vectors/<case>.pcm      input: signed 16-bit little-endian mono at the case's rate
  vectors/<case>.frames.csv  per-frame reference features (16 kHz frames) + the noise floor after the frame
  vectors/<case>.events.json expected events: t_start_ms, t_end_ms, label, text (schema-exact), the protocol
                          message, and the raw measurements the classifier used
  vectors/decimator.*     a 48 kHz input and the reference 16 kHz output (float32 LE), for the FIR alone

The reference runs on the int16-quantised input (x = pcm / 32768), i.e. exactly what the device sees.
Chunking does not change 16 kHz results; it is fixed to 1600 samples here anyway.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

import synth
from vox_extract import Config
from vox_extract.extractor import Extractor
from vox_extract.frontend import FRAME_FIELDS, FrameProcessor
from vox_extract.protocol import message
from vox_extract.resample import DECIM_CUTOFF_HZ, DECIM_KAISER_BETA, DECIM_TAPS, Decimator3, decim_taps
from vox_extract import vocab

HERE = Path(__file__).resolve().parent

# (case name, synth class, snr dB, background, capture rate)
CASES = [
    ("rise_20db", "rise", 20, "pink", 16000),
    ("fall_20db", "fall", 20, "white", 16000),
    ("arch_20db", "arch", 20, "brown", 16000),
    ("dip_20db", "dip", 20, "pink", 16000),
    ("flat_20db", "flat", 20, "white", 16000),
    ("whistle_rise_20db", "whistle_rise", 20, "pink", 16000),
    ("pop_20db", "pop", 20, "pink", 16000),
    ("click_30db", "click", 30, "white", 16000),
    ("hiss_20db", "hiss", 20, "brown", 16000),
    ("click_pop_30db", "click_pop", 30, "pink", 16000),
    ("rise_10db_cafe", "rise", 10, "cafe", 16000),
    ("talk_20db", "talk", 20, "pink", 16000),
    ("laugh_20db", "laugh", 20, "white", 16000),
    ("cough_20db", "cough", 20, "pink", 16000),
    ("music_20db", "music", 20, "pink", 16000),
    ("fan_motor_20db", "fan_motor", 20, "brown", 16000),
    ("silence", "silence", 20, "pink", 16000),
    ("arch_20db_48k", "arch", 20, "pink", 48000),
    ("pop_20db_48k", "pop", 20, "white", 48000),
]

TOLERANCES = {
    "note": "float32 C vs float64 Python. Frames: compare where both sides agree the frame is above the floor + 6 dB.",
    "frame": {"e_db": 0.05, "zcr": 0.0, "centroid_rel": 0.002, "flatness_abs": 0.002, "flux_db": 0.05,
              "lf_ratio": 0.002, "hf_ratio": 0.002, "f0_rel_if_clarity_ge_0.8": 0.003, "clarity": 0.01,
              "floor_db": 0.05},
    "events": {"count": "exact", "label": "exact", "text": "exact (every bucket string)",
               "t_start_ms": 10, "t_end_ms": 10,
               "fp1_and_pitch16": {"abs": 0.01, "rel": 0.01, "rule": "per value: |c - ref| <= abs + rel * |ref|"}},
    "decimator_abs": 1e-5,
    "48k_note": "48 kHz cases go through the decimator; allow e_db 0.1 and the same event tolerances.",
}


def run_case(pcm: np.ndarray, rate: int, cfg: Config) -> tuple[list, list, list]:
    x = pcm.astype(np.float32) / 32768.0
    ex = Extractor(cfg, input_rate=rate, keep_frames=True)
    events = []
    step = 1600 * (rate // 16000)
    for i in range(0, x.size, step):
        events += ex.push(x[i:i + step])
    events += ex.flush()
    return ex.frames, ex.floors, events


def main() -> None:
    import soundfile as sf  # noqa: F401  (keeps the dependency list honest; WAVs are optional)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=HERE / "vectors")
    ap.add_argument("--seed", type=int, default=424242)
    ap.add_argument("--wav", action="store_true", help="also write a .wav next to each .pcm (for listening)")
    a = ap.parse_args()
    out: Path = a.out
    out.mkdir(parents=True, exist_ok=True)
    cfg = Config()
    fp = FrameProcessor(cfg)
    cases = []
    for k, (name, cls, snr, bg, rate) in enumerate(CASES):
        rng = np.random.default_rng(a.seed + k)
        clip = synth.make_clip(cls, rng, rate, float(snr), bg)
        pcm = np.clip(np.round(clip.audio * 32768.0), -32768, 32767).astype("<i2")
        pcm.tofile(out / f"{name}.pcm")
        if a.wav:
            import soundfile as sf
            sf.write(out / f"{name}.wav", pcm, rate, subtype="PCM_16")
        frames, floors, events = run_case(pcm, rate, cfg)
        with (out / f"{name}.frames.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(FRAME_FIELDS + ["floor_db_after"])
            for fr, fl in zip(frames, floors):
                row = fr.as_list()
                w.writerow([int(row[0])] + [f"{v:.6g}" for v in row[1:]] + [f"{fl:.6g}"])
        evs = []
        for i, e in enumerate(events, 1):
            d = e.to_dict()
            d["message"] = message([d], i, features=True)
            evs.append(d)
        (out / f"{name}.events.json").write_text(json.dumps(
            {"case": name, "synthetic": True, "truth": clip.labels(), "events": evs}, indent=1, default=float))
        cases.append({"name": name, "class": cls, "kind": clip.kind, "snr_db": snr, "background": bg, "rate": rate,
                      "samples": int(pcm.size), "frames": len(frames),
                      "expected": [(e.label, e.text) for e in events]})
        print(f"{name:<22} {rate:>5} Hz {pcm.size / rate:5.2f} s  {len(frames):4d} frames  "
              f"{[e.label for e in events]}")

    # decimator alone: tone sweep + noise at 48 kHz
    rng = np.random.default_rng(a.seed)
    t = np.arange(24000) / 48000.0
    xin = (0.3 * np.sin(2 * np.pi * (200 * t + 9000 * t * t)) + 0.05 * rng.standard_normal(t.size)).astype(np.float32)
    xin.astype("<f4").tofile(out / "decimator.in48k.f32")
    Decimator3().push(xin).astype("<f4").tofile(out / "decimator.out16k.f32")

    manifest = {
        "synthetic": True,
        "note": "SYNTHETIC audio from synth.py. These vectors check that a port reproduces the Python "
                "reference; they say nothing about accuracy on real voices.",
        "config": json.loads(cfg.to_json()),
        "vocab_digest": vocab.digest(),
        "vocab": {k: getattr(vocab, k) for k in ("CONTOURS", "DISCRETE", "EXCURSION", "DURATION", "CLARITY",
                                                  "LOUDNESS", "SOUNDS_LIKE", "LABELS")},
        "highpass_biquad": {"b": [float(v) for v in fp.hpf_b], "a": [float(v) for v in fp.hpf_a],
                            "form": "transposed direct form II, state starts at zero, float64 in the reference"},
        "decimator": {"taps": [float(v) for v in decim_taps()], "n_taps": DECIM_TAPS, "cutoff_hz": DECIM_CUTOFF_HZ,
                      "kaiser_beta": DECIM_KAISER_BETA,
                      "rule": "output m = sum_k h[k] * x[3m - k] over k = 0..62 with x[<0] = 0 (first output at input 0)"},
        "frame_time": "frame j: t_ms = (( j+1)*hop - win/2 - hop/2) * 1000 / 16000 = 10*j - 11; window = the last "
                      "512 samples after hop j+1 (zeros before the stream starts); periodic Hann for spectra, "
                      "no window for MPM",
        "tolerances": TOLERANCES,
        "files": {"pcm": "<case>.pcm, int16 LE mono at 'rate'", "frames": "<case>.frames.csv",
                  "events": "<case>.events.json", "decimator": ["decimator.in48k.f32", "decimator.out16k.f32"]},
        "cases": cases,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"wrote {len(cases)} SYNTHETIC cases + decimator vector to {out}")


if __name__ == "__main__":
    main()
