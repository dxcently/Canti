"""Sound fingerprint `fp1` (24 floats) for phone-side personalization (wiki personalization.md, FINGERPRINT.md).

Everything comes from what the extractor already has per sound: classify()'s summary features and a few extra
running sums of the SAME 512-point power spectrum the front end computes every hop (segmenter.SegmentStats:
8 mel-band powers, band power, 1-6 kHz power, pitched-frame power and its part above 3.5 x f0). No new FFT, no
per-frame storage: 12 extra floats of state per sound.

The vector is meant for nearest-neighbour matching against the SAME user's enrolled examples after per-feature
standardisation by the enrollment statistics (android Personal.Matcher), not as a speaker-independent classifier,
so it keeps pitch (a user's meow and hum differ mainly in f0) and drops level (mic gain / distance).
Selection: the cross-speaker cue analysis (results/real_cues.md); the fields are listed in FP1_NAMES.
"""

from __future__ import annotations

import math

FP_VERSION = "fp1"
CONTOUR_LABELS = ("rise", "fall", "arch", "dip", "flat")

FP1_NAMES = [
    "f0_oct",              # log2(median f0 / 100 Hz); -3 when unpitched
    "f0_range_st",         # max - min of the smoothed contour (semitones); 0 when unpitched
    "pitch_resid_std_st",  # std of the contour around its straight-line fit
    "pitch_rough_st",      # median |2nd difference| of the contour (vibrato / wobble)
    "voiced_frac",         # share of frames voiced
    "strong_voiced_frac",  # ... among frames near the sound's own level
    "clarity_med",         # median MPM clarity (periodicity)
    "centroid_oct",        # log2(energy-weighted centroid / 1 kHz)
    "centroid_spread_oct", # std of log2 centroid over the loud frames (vowel / consonant changes)
    "flatness",            # energy-weighted spectral flatness
    "zcr",                 # energy-weighted zero-crossing rate (per sample)
    "lf_ratio",            # share of band power below 1 kHz
    "hf_ratio",            # share above 3.5 kHz
    "e1k",                 # share of band power in 1-6 kHz (open-mouth brightness)
    "e35f0",               # pitched frames: share of their power above 3.5 x their own f0; 0 when unpitched
    "dur_oct",             # log2(duration / 100 ms)
    "energy_iqr_db",       # interquartile range of hop energy (dB)
    "flux_mean_db",        # energy-weighted spectral flux
    "onset_flux_db",       # max flux over the first 3 frames
    "decay_db",            # peak minus the mean of the last 3 frames
    "cep1", "cep2", "cep3", "cep4",  # DCT-II (orthonormal) of the 8 log mel-band powers (dB) of the whole sound
]
assert len(FP1_NAMES) == 24


def cepstrum(mel8: list[float], n: int = 4) -> list[float]:
    L = [10.0 * math.log10(v + 1e-12) for v in mel8]
    m = len(L)
    return [math.sqrt(2.0 / m) * sum(L[i] * math.cos(math.pi * k * (i + 0.5) / m) for i in range(m)) for k in range(1, n + 1)]


def fingerprint(seg, raw: dict) -> list[float]:
    """fp1 for one finished sound: seg = segmenter.SegmentStats, raw = classify()'s raw feature dict."""
    f0 = raw.get("f0_med_hz") or 0.0
    pitched = f0 > 0 and raw.get("max_st") is not None
    cent = raw.get("centroid_hz") or 0.0
    e1k = seg.p_1k6_sum / seg.p_band_sum if seg.p_band_sum > 0 else 0.0
    e35 = seg.p_hi35_sum / seg.p_voiced_sum if seg.p_voiced_sum > 0 else 0.0
    v = [
        math.log2(f0 / 100.0) if f0 > 0 else -3.0,
        (raw["max_st"] - raw["min_st"]) if pitched else 0.0,
        raw.get("pitch_resid_std_st", 0.0),
        raw.get("pitch_rough_st", 0.0),
        raw.get("voiced_frac", 0.0),
        raw.get("strong_voiced_frac", 0.0),
        raw.get("clarity_med", 0.0),
        math.log2(max(cent, 50.0) / 1000.0),
        raw.get("centroid_spread_oct", 0.0),
        raw.get("flatness", 0.0),
        raw.get("zcr", 0.0),
        raw.get("lf_ratio", 0.0),
        raw.get("hf_ratio", 0.0),
        e1k,
        e35,
        math.log2(max(raw.get("dur_ms", 10), 10) / 100.0),
        raw.get("energy_iqr_db", 0.0),
        raw.get("flux_mean_db", 0.0),
        raw.get("onset_flux_db", 0.0),
        raw.get("decay_db", 0.0),
    ] + cepstrum(seg.mel8_sum)
    return [round(float(x), 4) for x in v]


def features_entry(raw: dict) -> dict | None:
    """The per-sound `features` object of a v1 message (android Personal.SoundFeatures), or None."""
    if not raw.get("fp"):
        return None
    return {"fp": raw["fp"], "fp_version": raw.get("fp_version", FP_VERSION), "pitch16": raw.get("pitch16") or []}
