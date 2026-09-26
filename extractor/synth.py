#!/usr/bin/env python3
"""Synthetic, labelled audio for self-tests of the VOX extractor. THIS IS NOT REAL AUDIO.

Every clip carries its ground truth: class, kind (gesture | sequence | negative), and for
gestures the expected events (label, t_start_ms, t_end_ms, expected excursion / duration buckets).

Classes
  gestures:  rise fall arch dip flat (hummed: harmonics, nasal resonance, vibrato, jitter, shimmer,
             breath noise), whistle_<contour>, pop (lip pop), click (tongue click), hiss ("s" / "sh")
  sequence:  click_pop (two sounds, 150-450 ms apart)
  negatives: talk (babble: formant-filtered harmonic source, 3-12 syllables at 3-6 Hz), talk_short
             (1-2 syllables), laugh, cough, music (chords + bass + optional melody / drums),
             air (long broadband air / fan noise), fan_motor (air + a perfectly steady motor tone),
             silence (background only)
  backgrounds: white, pink, brown, cafe (distant babble), at a chosen SNR
             (SNR = active-span RMS of the sound vs background RMS)

Usage
  python synth.py --out synth_clips --per-class 3 --snr 20        # writes WAVs + labels.jsonl
  python synth.py --demo out.wav                                   # one long clip of every gesture
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.signal import butter, lfilter, sosfilt

CONTOUR_CLASSES = ["rise", "fall", "arch", "dip", "flat"]
GESTURES = CONTOUR_CLASSES + [f"whistle_{c}" for c in CONTOUR_CLASSES] + ["pop", "click", "hiss"]
SEQUENCES = ["click_pop"]
NEGATIVES = ["talk", "talk_short", "laugh", "cough", "music", "air", "fan_motor", "silence"]
ALL_CLASSES = GESTURES + SEQUENCES + NEGATIVES
BACKGROUNDS = ["white", "pink", "brown", "cafe"]

VOWELS = {  # F1, F2, F3 (Hz), adult averages
    "a": (730, 1090, 2440), "i": (270, 2290, 3010), "u": (300, 870, 2240),
    "e": (530, 1840, 2480), "o": (570, 840, 2410), "ae": (660, 1720, 2410),
}


@dataclass
class Clip:
    audio: np.ndarray
    sr: int
    cls: str
    kind: str                                   # gesture | sequence | negative
    events: list[dict] = field(default_factory=list)  # expected events (gestures / sequences)
    span: tuple[int, int] | None = None         # ms span of the target sound (all kinds)
    meta: dict = field(default_factory=dict)

    def labels(self) -> dict:
        return {"cls": self.cls, "kind": self.kind, "events": self.events, "span_ms": self.span,
                "sr": self.sr, "meta": self.meta}


# ------------------------------------------------------------------------------- primitives

def raised_env(n: int, attack: int, release: int) -> np.ndarray:
    e = np.ones(n)
    a = min(attack, n // 2)
    r = min(release, n - a)
    if a > 0:
        e[:a] = 0.5 - 0.5 * np.cos(np.pi * np.arange(a) / a)
    if r > 0:
        e[n - r:] = 0.5 + 0.5 * np.cos(np.pi * np.arange(r) / r)
    return e


def smooth_noise(rng: np.random.Generator, n: int, sr: int, cutoff_hz: float) -> np.ndarray:
    """Zero-mean, unit-std low-pass random signal (for jitter, shimmer, wobble)."""
    w = rng.standard_normal(n + sr // 2)
    b, a = butter(2, cutoff_hz / (sr / 2))
    y = lfilter(b, a, w)[sr // 2:]
    return y / (np.std(y) + 1e-12)


def resonator(x: np.ndarray, f: float, bw: float, sr: int) -> np.ndarray:
    r = np.exp(-np.pi * bw / sr)
    th = 2 * np.pi * f / sr
    a = [1.0, -2 * r * np.cos(th), r * r]
    b = [1.0 - r]
    return lfilter(b, a, x)


def formant_filter(x: np.ndarray, formants, sr: int, bws=(90, 110, 170)) -> np.ndarray:
    y = np.zeros_like(x)
    for (f, g), bw in zip(zip(formants, (1.0, 0.7, 0.35)), bws):
        if f < sr / 2 - 200:
            y += g * resonator(x, f, bw, sr)
    return y


def harmonic_source(f0: np.ndarray, sr: int, rng: np.random.Generator, tilt: float, max_h: int = 60) -> np.ndarray:
    """Sum of harmonics following a per-sample f0 track; amplitude k^-tilt; no aliasing."""
    phase = 2 * np.pi * np.cumsum(f0) / sr
    y = np.zeros_like(f0)
    for k in range(1, max_h + 1):
        ok = k * f0 < 0.45 * sr
        if not ok.any():
            break
        y += ok * (k ** -tilt) * np.sin(k * phase + rng.uniform(0, 2 * np.pi))
    return y


def band_noise(rng: np.random.Generator, n: int, sr: int, lo: float, hi: float, order: int = 4) -> np.ndarray:
    hi = min(hi, 0.47 * sr)
    sos = butter(order, [lo / (sr / 2), hi / (sr / 2)], btype="band", output="sos")
    y = sosfilt(sos, rng.standard_normal(n))
    return y / (np.std(y) + 1e-12)


def colored_noise(rng: np.random.Generator, n: int, color: str) -> np.ndarray:
    w = rng.standard_normal(n)
    if color == "white":
        y = w
    else:
        spec = np.fft.rfft(w)
        f = np.arange(spec.size) + 1.0
        spec /= np.sqrt(f) if color == "pink" else f  # brown: 1/f^2 power
        y = np.fft.irfft(spec, n)
    return y / (np.std(y) + 1e-12)


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x * x) + 1e-20))


# ------------------------------------------------------------------------------- contours

def contour_track(shape: str, u: np.ndarray, exc: float, rng: np.random.Generator) -> tuple[np.ndarray, dict]:
    """Semitone track over normalised time u in [0,1]. Returns (track, truth dict)."""
    h0, h1 = rng.uniform(0, 0.15), rng.uniform(0, 0.15)
    def glide(a, b):  # smooth 0->1 between a and b
        v = np.clip((u - a) / max(b - a, 1e-6), 0, 1)
        return v * v * (3 - 2 * v)
    if shape == "rise":
        return exc * glide(h0, 1 - h1), {"excursion": exc}
    if shape == "fall":
        return -exc * glide(h0, 1 - h1), {"excursion": exc}
    if shape in ("arch", "dip"):
        p = rng.uniform(0.38, 0.62)
        ret = rng.uniform(0.8, 1.1)  # how far it comes back
        tr = exc * glide(h0, p) - exc * ret * glide(p, 1 - h1)
        hump = exc * min(ret, 1.0) if ret < 1 else exc
        sign = 1 if shape == "arch" else -1
        return sign * tr, {"excursion": hump, "return": ret}
    if shape == "flat":
        drift = rng.uniform(-0.4, 0.4)
        return drift * u, {"excursion": abs(drift)}
    raise ValueError(shape)


def exc_bucket(e: float) -> str:
    return "small (under 2 semitones)" if e < 2 else "medium (2-4 semitones)" if e < 4 else "large (over 4 semitones)"


def dur_bucket(ms: float) -> str:
    return ("very short (under 150 ms)" if ms < 150 else "short (150-400 ms)" if ms < 400
            else "medium (400-1000 ms)" if ms < 1000 else "long (over 1 s)")


# ------------------------------------------------------------------------------- sound makers
# Each returns (signal, info). The signal starts at its onset and ends where it reaches silence.

def make_hum(shape: str, rng: np.random.Generator, sr: int, whistle: bool = False,
             exc: float | None = None, dur_ms: float | None = None) -> tuple[np.ndarray, dict]:
    if dur_ms is None:
        if shape == "flat":
            dur_ms = rng.uniform(1100, 1600) if rng.random() < 0.6 else rng.uniform(500, 900)
        else:
            dur_ms = rng.uniform(220, 360) if rng.random() < 0.4 else rng.uniform(450, 900)
    if exc is None:
        exc = rng.uniform(5, 10)
    n = int(sr * dur_ms / 1000)
    u = np.linspace(0, 1, n)
    track, truth = contour_track(shape, u, exc, rng)
    lo, hi = track.min(), track.max()
    if whistle:
        f_start = rng.uniform(700, 1400)
        f_start = float(np.clip(f_start, 650 * 2 ** (-lo / 12), 2300 * 2 ** (-hi / 12)))
    else:
        f_start = rng.uniform(95, 160) if rng.random() < 0.5 else rng.uniform(170, 300)
        f_start = float(np.clip(f_start, 88 * 2 ** (-lo / 12), 600 * 2 ** (-hi / 12)))
    t = np.arange(n) / sr
    vib_depth = rng.uniform(0, 0.35)
    vib_rate = rng.uniform(4, 6.5)
    st = track + vib_depth * np.sin(2 * np.pi * vib_rate * t + rng.uniform(0, 6.28))
    st += rng.uniform(0.04, 0.15) * smooth_noise(rng, n, sr, 12.0)  # jitter-like drift
    f0 = f_start * 2 ** (st / 12)
    if whistle:
        phase = 2 * np.pi * np.cumsum(f0) / sr
        y = np.sin(phase) + 0.05 * np.sin(2 * phase)
        breath = rng.uniform(0.05, 0.15)
    else:
        y = harmonic_source(f0, sr, rng, tilt=rng.uniform(1.0, 1.8))
        y = 0.6 * resonator(y, rng.uniform(220, 320), 80, sr) * 8 + 0.4 * y  # nasal murmur resonance
        breath = rng.uniform(0.01, 0.06)
    y /= rms(y)
    y += breath * band_noise(rng, n, sr, 800, 7000)
    shimmer = 1 + rng.uniform(0.02, 0.08) * smooth_noise(rng, n, sr, 8.0)
    att = int(sr * rng.uniform(0.02, 0.06))
    rel = int(sr * rng.uniform(0.03, 0.08))
    y *= shimmer * raised_env(n, att, rel)
    return y, {"f_start": round(f_start, 1), "excursion_st": round(truth["excursion"], 2),
               "expected_excursion": exc_bucket(truth["excursion"]) if shape != "flat" else exc_bucket(0),
               "expected_duration": dur_bucket(dur_ms), "vibrato_st": round(vib_depth, 2)}


def make_pop(rng: np.random.Generator, sr: int) -> tuple[np.ndarray, dict]:
    n = int(sr * rng.uniform(0.03, 0.05))
    t = np.arange(n) / sr
    f = rng.uniform(250, 400) + rng.uniform(250, 500) * np.clip(t / 0.025, 0, 1)
    tau = rng.uniform(0.005, 0.012)
    y = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t / tau)
    burst = band_noise(rng, n, sr, 80, 2000) * np.exp(-t / 0.002) * 0.6
    y = y + burst
    y *= raised_env(n, int(sr * 0.0008), int(sr * 0.005))
    return y / (np.max(np.abs(y)) + 1e-12), {"expected_duration": "instant"}


def make_click(rng: np.random.Generator, sr: int) -> tuple[np.ndarray, dict]:
    n = int(sr * rng.uniform(0.012, 0.02))
    t = np.arange(n) / sr
    f1 = rng.uniform(2200, 3800)
    y = np.sin(2 * np.pi * f1 * t) * np.exp(-t / rng.uniform(0.0015, 0.003))
    y += 0.4 * np.sin(2 * np.pi * rng.uniform(1000, 1500) * t) * np.exp(-t / 0.002)
    y += 0.5 * band_noise(rng, n, sr, 1500, 7000) * np.exp(-t / 0.001)
    y *= raised_env(n, int(sr * 0.0003), int(sr * 0.003))
    return y / (np.max(np.abs(y)) + 1e-12), {"expected_duration": "instant"}


def make_hiss(rng: np.random.Generator, sr: int, dur_ms: float | None = None) -> tuple[np.ndarray, dict]:
    dur_ms = dur_ms or (rng.uniform(220, 360) if rng.random() < 0.4 else rng.uniform(450, 850))
    n = int(sr * dur_ms / 1000)
    if rng.random() < 0.6:  # "s"
        y = band_noise(rng, n, sr, rng.uniform(3500, 4500), 7800)
        variant = "s"
    else:  # "sh"
        y = band_noise(rng, n, sr, rng.uniform(1700, 2200), rng.uniform(4500, 6000))
        variant = "sh"
    y *= 10 ** (rng.uniform(0.5, 1.5) / 20 * smooth_noise(rng, n, sr, 4.0))
    y *= raised_env(n, int(sr * rng.uniform(0.03, 0.08)), int(sr * rng.uniform(0.05, 0.1)))
    return y, {"variant": variant, "expected_duration": dur_bucket(dur_ms)}


def glottal_voice(f0: np.ndarray, sr: int, rng: np.random.Generator, formants, breath: float) -> np.ndarray:
    src = harmonic_source(f0, sr, rng, tilt=2.0)
    src /= rms(src)
    src += breath * rng.standard_normal(f0.size)
    return formant_filter(src, formants, sr)


def make_talk(rng: np.random.Generator, sr: int, n_syll: int | None = None) -> tuple[np.ndarray, dict]:
    """Connected babble: syllable = consonant + vowel. Consonants are voiced (nasal / liquid, weaker
    voicing with a low first formant), voiceless fricatives, or stop closures (silence + burst).
    Voicing continues through voiced consonants, as in real connected speech; true silences are
    only stop closures (40-80 ms) and phrase pauses (150-350 ms, every 3-6 syllables)."""
    n_syll = n_syll or int(rng.integers(3, 13))
    rate = rng.uniform(3.0, 6.0)
    base = rng.uniform(100, 140) if rng.random() < 0.5 else rng.uniform(180, 240)
    pieces = []
    next_pause = int(rng.integers(3, 7))
    for i in range(n_syll):
        syl = 1.0 / rate * rng.uniform(0.75, 1.25)
        v_len = syl * rng.uniform(0.55, 0.75)
        c_len = syl - v_len
        prog = i / max(n_syll - 1, 1)
        accent = rng.uniform(-1.0, 3.0) if rng.random() < 0.4 else rng.uniform(-1.0, 1.0)
        f_syl = base * 2 ** ((-2.5 * prog + accent) / 12)  # declination + accents
        cons = rng.choice(["voiced", "fric", "stop"], p=[0.45, 0.3, 0.25]) if i > 0 or rng.random() < 0.7 else "none"
        m = int(sr * c_len)
        if cons == "voiced":
            f0 = f_syl * 2 ** (0.3 * smooth_noise(rng, m, sr, 15.0) / 12)
            c = glottal_voice(f0, sr, rng, [rng.uniform(250, 320), rng.uniform(1000, 1500), 2500], 0.05)
            c = 0.3 * c / rms(c) * raised_env(m, m // 4, m // 4)
        elif cons == "fric":
            c = 0.35 * band_noise(rng, m, sr, rng.uniform(2000, 4000), 7500) * raised_env(m, m // 4, m // 4)
        elif cons == "stop":
            k = int(sr * 0.012)
            c = np.zeros(m)
            c[-k:] = 0.6 * band_noise(rng, k, sr, 500, 6000) * np.exp(-np.arange(k) / (0.003 * sr))
        else:
            c = np.zeros(0)
        mv = int(sr * v_len)
        st = rng.uniform(-2, 2) * np.linspace(0, 1, mv) + 0.3 * smooth_noise(rng, mv, sr, 15.0)
        f0 = f_syl * 2 ** (st / 12)
        vowel = VOWELS[rng.choice(list(VOWELS))]
        formants = [f * rng.uniform(0.9, 1.1) for f in vowel]
        v = glottal_voice(f0, sr, rng, formants, breath=0.05)
        v = v / rms(v) * rng.uniform(0.6, 1.0) * raised_env(mv, int(mv * 0.2), int(mv * 0.25))
        pieces += [c, v]
        next_pause -= 1
        if next_pause == 0 and i < n_syll - 1:
            pieces.append(np.zeros(int(sr * rng.uniform(0.15, 0.35))))
            next_pause = int(rng.integers(3, 7))
    y = np.concatenate(pieces)
    nz = np.flatnonzero(np.abs(y) > 1e-6)
    y = y[nz[0]: nz[-1] + 1] if nz.size else y
    return y, {"syllables": n_syll, "rate_hz": round(rate, 2)}


def make_laugh(rng: np.random.Generator, sr: int) -> tuple[np.ndarray, dict]:
    n_b = int(rng.integers(4, 9))
    period = rng.uniform(0.16, 0.24)
    f_base = rng.uniform(220, 380)
    out = []
    for i in range(n_b):
        amp = 1.0 * (0.85 ** i)
        h = int(sr * rng.uniform(0.025, 0.045))
        asp = band_noise(rng, h, sr, 500, 5000) * raised_env(h, h // 3, h // 3) * rng.uniform(0.3, 0.6)
        m = int(sr * period * rng.uniform(0.35, 0.55))
        f0 = f_base * (0.97 ** i) * 2 ** (np.linspace(1, -1.5, m) / 12)
        v = glottal_voice(f0, sr, rng, VOWELS["a"], breath=0.35)
        v = v / rms(v) * raised_env(m, m // 5, m // 3)
        gap = int(sr * period * rng.uniform(0.9, 1.1)) - h - m
        out.append(amp * np.concatenate([asp, v, rng.uniform(0.15, 0.3) * band_noise(rng, max(gap, 1), sr, 400, 4000)]))
    y = np.concatenate(out)
    return y, {"bursts": n_b, "period_s": round(period, 3)}


def make_cough(rng: np.random.Generator, sr: int) -> tuple[np.ndarray, dict]:
    n_c = int(rng.integers(1, 3))
    out = []
    for i in range(n_c):
        m = int(sr * rng.uniform(0.18, 0.32))
        t = np.arange(m) / sr
        tau = rng.uniform(0.05, 0.1)
        noise = band_noise(rng, m, sr, 200, 5000)
        noise = formant_filter(noise, [rng.uniform(400, 700), rng.uniform(1200, 1800), 2600], sr)
        noise /= rms(noise)
        k = int(sr * rng.uniform(0.04, 0.08))
        f0 = np.full(k, rng.uniform(130, 260))
        voice = np.zeros(m)
        voice[:k] = glottal_voice(f0, sr, rng, VOWELS["a"], 0.3)[:k]
        voice[:k] /= rms(voice[:k]) + 1e-12
        y = (noise + 0.5 * voice) * np.exp(-t / tau)
        y *= raised_env(m, int(sr * 0.003), int(sr * 0.03))
        out.append(y)
        if i < n_c - 1:
            out.append(np.zeros(int(sr * rng.uniform(0.15, 0.3))))
    return np.concatenate(out), {"coughs": n_c}


def make_music(rng: np.random.Generator, sr: int, dur_s: float | None = None) -> tuple[np.ndarray, dict]:
    dur_s = dur_s or rng.uniform(3.0, 5.0)
    n = int(sr * dur_s)
    y = np.zeros(n)
    style = rng.choice(["piano", "organ"])
    chord_len = rng.uniform(0.4, 0.9)
    roots = [0, 5, 7, 9, 2, 4]
    key = rng.uniform(-3, 3)
    t0 = 0.0
    while t0 < dur_s:
        root = rng.choice(roots)
        notes = [root, root + (3 if rng.random() < 0.4 else 4), root + 7] + ([root + 10] if rng.random() < 0.3 else [])
        m = min(int(sr * chord_len), n - int(sr * t0))
        if m <= 0:
            break
        t = np.arange(m) / sr
        env = np.exp(-t / rng.uniform(0.3, 0.9)) if style == "piano" else raised_env(m, int(0.02 * sr), int(0.05 * sr))
        seg = np.zeros(m)
        for st in notes + [root - 12]:
            f = 220 * 2 ** ((st + key - 9) / 12)
            seg += harmonic_source(np.full(m, f), sr, rng, tilt=1.3, max_h=12)
        if rng.random() < 0.6:  # melody note on top
            f = 220 * 2 ** ((root + 12 + rng.choice([0, 4, 7, 12]) + key - 9) / 12)
            seg += 0.7 * harmonic_source(np.full(m, f), sr, rng, tilt=1.0, max_h=8)
        i0 = int(sr * t0)
        y[i0:i0 + m] += seg * env * raised_env(m, int(0.005 * sr), int(0.01 * sr))
        t0 += chord_len
    if rng.random() < 0.5:  # soft drums
        beat = chord_len / 2
        for k in range(int(dur_s / beat)):
            i0 = int(sr * k * beat)
            m = min(int(0.12 * sr), n - i0)
            t = np.arange(m) / sr
            if k % 2 == 0:
                y[i0:i0 + m] += 2.0 * np.sin(2 * np.pi * 60 * t) * np.exp(-t / 0.05)
            else:
                y[i0:i0 + m] += 0.6 * band_noise(rng, m, sr, 5000, 7800) * np.exp(-t / 0.02)
    return y, {"style": style, "chord_s": round(chord_len, 2)}


def make_air(rng: np.random.Generator, sr: int, motor: bool = False) -> tuple[np.ndarray, dict]:
    dur_s = rng.uniform(3.5, 6.0)
    n = int(sr * dur_s)
    color = rng.choice(["pink", "brown", "white"], p=[0.5, 0.3, 0.2])
    y = colored_noise(rng, n, color)
    b, a = butter(2, rng.uniform(2500, 6000) / (sr / 2))
    y = lfilter(b, a, y)
    y /= rms(y)
    y *= 1 + 0.05 * smooth_noise(rng, n, sr, 2.0)
    info = {"color": color}
    if motor:
        f = rng.uniform(95, 125)
        t = np.arange(n) / sr
        tone = sum((0.7 ** k) * np.sin(2 * np.pi * k * f * t) for k in range(1, 5))
        y += rng.uniform(0.5, 1.5) * tone / rms(tone)
        info["motor_hz"] = round(f, 1)
    fade = int(sr * rng.uniform(0.2, 1.0))
    y *= raised_env(n, fade, fade)
    return y, info


# ------------------------------------------------------------------------------- backgrounds & assembly

def background(rng: np.random.Generator, kind: str, n: int, sr: int) -> np.ndarray:
    if kind == "cafe":
        y = np.zeros(n)
        for _ in range(4):
            v, _ = make_talk(rng, sr, n_syll=int(rng.integers(20, 40)))
            v = np.tile(v, int(np.ceil(n / v.size)) + 1)
            off = int(rng.integers(0, v.size - n))
            y += v[off:off + n] / rms(v)
        y = lfilter(*butter(2, 3000 / (sr / 2)), y)  # distant = duller
        y += 0.5 * colored_noise(rng, n, "pink")
    else:
        y = colored_noise(rng, n, kind)
    return y / rms(y)


def active_rms(sig: np.ndarray) -> float:
    """RMS over the samples within 20 dB of the envelope peak (the 'active span')."""
    a = np.abs(sig)
    k = max(1, int(0.005 * len(sig)) if len(sig) > 400 else 1)
    env = np.convolve(a, np.ones(k) / k, mode="same")
    m = env > env.max() * 0.1
    return rms(sig[m]) if m.any() else rms(sig)


def place(parts: list[tuple[np.ndarray, str, dict]], sr: int, rng: np.random.Generator, snr_db: float,
          bg: str, gaps_ms: list[float] | None = None, lead_ms: float | None = None,
          tail_ms: float = 700.0, level_dbfs: float | None = None) -> tuple[np.ndarray, list[dict]]:
    """Concatenate sounds with gaps, set the level, add background at snr_db. Returns (audio, events)."""
    lead_ms = lead_ms if lead_ms is not None else rng.uniform(700, 1000)
    level_dbfs = level_dbfs if level_dbfs is not None else rng.uniform(-32, -18)
    target = 10 ** (level_dbfs / 20)
    segs, events = [], []
    t = lead_ms / 1000
    segs.append(np.zeros(int(sr * t)))
    for i, (sig, label, info) in enumerate(parts):
        s = sig / active_rms(sig) * target
        start = sum(len(x) for x in segs)
        segs.append(s)
        events.append({"label": label, "t_start_ms": round(start / sr * 1000, 1),
                       "t_end_ms": round((start + len(s)) / sr * 1000, 1), **info})
        if i < len(parts) - 1:
            segs.append(np.zeros(int(sr * (gaps_ms[i] if gaps_ms else 1500) / 1000)))
    segs.append(np.zeros(int(sr * tail_ms / 1000)))
    y = np.concatenate(segs)
    noise = background(rng, bg, y.size, sr) * target / 10 ** (snr_db / 20)
    return (y + noise).astype(np.float32), events


def make_clip(cls: str, rng: np.random.Generator, sr: int = 16000, snr_db: float = 20.0,
              bg: str = "pink") -> Clip:
    meta = {"snr_db": snr_db, "background": bg}
    if cls in CONTOUR_CLASSES or cls.startswith("whistle_"):
        shape = cls.replace("whistle_", "")
        sig, info = make_hum(shape, rng, sr, whistle=cls.startswith("whistle_"))
        y, ev = place([(sig, shape, info)], sr, rng, snr_db, bg)
        return Clip(y, sr, cls, "gesture", ev, (ev[0]["t_start_ms"], ev[0]["t_end_ms"]), meta)
    if cls in ("pop", "click", "hiss"):
        sig, info = {"pop": make_pop, "click": make_click, "hiss": make_hiss}[cls](rng, sr)
        y, ev = place([(sig, cls, info)], sr, rng, snr_db, bg)
        return Clip(y, sr, cls, "gesture", ev, (ev[0]["t_start_ms"], ev[0]["t_end_ms"]), meta)
    if cls == "click_pop":
        c, ci = make_click(rng, sr)
        p, pi = make_pop(rng, sr)
        gap = rng.uniform(150, 450)
        y, ev = place([(c, "click", ci), (p, "pop", pi)], sr, rng, snr_db, bg, gaps_ms=[gap])
        meta["gap_ms"] = round(gap, 1)
        return Clip(y, sr, cls, "sequence", ev, (ev[0]["t_start_ms"], ev[1]["t_end_ms"]), meta)
    if cls == "silence":
        n = int(sr * rng.uniform(2.5, 4.0))
        level = 10 ** (rng.uniform(-70, -45) / 20)
        y = (background(rng, bg, n, sr) * level).astype(np.float32)
        return Clip(y, sr, cls, "negative", [], None, meta)
    maker = {"talk": make_talk, "talk_short": lambda r, s: make_talk(r, s, n_syll=int(r.integers(1, 3))),
             "laugh": make_laugh, "cough": make_cough, "music": make_music,
             "air": make_air, "fan_motor": lambda r, s: make_air(r, s, motor=True)}[cls]
    sig, info = maker(rng, sr)
    meta.update(info)
    y, ev = place([(sig, cls, info)], sr, rng, snr_db, bg)
    return Clip(y, sr, cls, "negative", [], (ev[0]["t_start_ms"], ev[0]["t_end_ms"]), meta)


def demo(rng: np.random.Generator, sr: int = 16000, snr_db: float = 25.0, bg: str = "pink") -> Clip:
    """One long clip with every default gesture once, 1.5 s apart (for a quick listen / smoke test)."""
    parts = []
    for g in ["rise", "fall", "arch", "dip", "flat"]:
        s, i = make_hum(g, rng, sr)
        parts.append((s, g, i))
    for g, mk in (("pop", make_pop), ("hiss", make_hiss), ("click", make_click), ("pop", make_pop)):
        s, i = mk(rng, sr)
        parts.append((s, g, i))
    gaps = [1500] * (len(parts) - 1)
    gaps[-2] = 300  # click then pop -> one "click pop" sequence
    y, ev = place(parts, sr, rng, snr_db, bg, gaps_ms=gaps, level_dbfs=-24)
    return Clip(y, sr, "demo", "sequence", ev, None, {"snr_db": snr_db, "background": bg})


def main() -> None:
    import soundfile as sf
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, help="directory for WAVs + labels.jsonl")
    ap.add_argument("--classes", nargs="*", default=ALL_CLASSES)
    ap.add_argument("--per-class", type=int, default=3)
    ap.add_argument("--snr", type=float, default=20.0)
    ap.add_argument("--background", default="pink", choices=BACKGROUNDS)
    ap.add_argument("--sr", type=int, default=16000, choices=[16000, 48000])
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--demo", type=Path, help="write one demo WAV with every gesture")
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)
    if a.demo:
        c = demo(rng, a.sr)
        sf.write(a.demo, c.audio, c.sr, subtype="PCM_16")
        a.demo.with_suffix(".labels.json").write_text(json.dumps(c.labels(), indent=1))
        print(f"wrote {a.demo} ({len(c.audio) / c.sr:.1f} s, SYNTHETIC)")
        return
    if not a.out:
        ap.error("--out or --demo is required")
    a.out.mkdir(parents=True, exist_ok=True)
    with (a.out / "labels.jsonl").open("w") as f:
        for cls in a.classes:
            for i in range(a.per_class):
                c = make_clip(cls, rng, a.sr, a.snr, a.background)
                name = f"{cls}_{i:03d}.wav"
                sf.write(a.out / name, c.audio, c.sr, subtype="PCM_16")
                f.write(json.dumps({"file": name, "synthetic": True, **c.labels()}) + "\n")
    print(f"wrote {len(a.classes) * a.per_class} SYNTHETIC clips to {a.out}")


if __name__ == "__main__":
    main()
