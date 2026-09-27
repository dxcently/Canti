#!/usr/bin/env python3
"""Voice-cursor calibration test (wiki/voice-cursor.md): about 5 minutes on the desk mic.

Can your voice place a cursor? Pitch would set the height and the vowel (ee / ah / oo) the sideways position. The session
records what the per-person profile needs, and `--score` computes it: how many pitch rows you hit reliably, and for each
pitch band whether your vowels separate (3 columns) or sideways falls back to snapping to on-screen elements.

Everything comes from ONE spec file, prompts/voice_cursor_v2.json (v1 is kept: a session is scored with the spec it was
recorded with): the steps, the analysis settings and the rules. This script holds no step or threshold of its own, so
the app's calibration can later follow the same file, and a Kotlin scorer can be checked against score.json on the same
recordings. Heights are relative to YOUR low end, home note and high end, so the steps work for any voice.

v2 shows a live pitch meter (your range, the 5 level marks, the target, your pitch now). It is hidden in the BLIND
level block and shown in the FEEDBACK level block and the vowel block. After the range and home note you see your
measured range on the meter and accept it or redo it.

Keys (single key press):  Enter = record   r = redo the last take   s = skip   q = quit (resume later)

Output: recordings/<session>/ (gitignored, PRIVATE: your voice; never commit it, never upload it anywhere)
  labels.jsonl, takes/<block>/*.wav, run-NN/ (session.wav, events.jsonl, ...), session.json, and score.json after --score

Commands
  ./run python voice_cursor_test.py --session vcursor-2                   # record (resumable: same command again)
  ./run python voice_cursor_test.py --score recordings/vcursor-2          # the per-person profile and the verdict
  ./run python voice_cursor_test.py --score recordings/vcursor-1 --spec voice_cursor_v2   # rescore under another spec
  ./run python voice_cursor_test.py --source fake --session selftest --auto   # SYNTHETIC self-test, no mic
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

import guided_session as G
import record as R

HERE = Path(__file__).resolve().parent
SPEC_DIR = HERE / "prompts"
SPEC_PATH = SPEC_DIR / "voice_cursor_v2.json"          # the current spec; recording always uses it


def load_spec(path: Path = SPEC_PATH) -> dict:
    return json.loads(Path(path).read_text())


def spec_path(version: str) -> Path:
    """A spec version name (e.g. voice_cursor_v2) -> prompts/<name>.json; a path ending in .json is used as is."""
    return Path(version) if version.endswith(".json") else SPEC_DIR / f"{version}.json"


def use_spec(spec: dict) -> None:
    """Point the analysis at a spec (the functions below read the module-level A)."""
    global SPEC, A
    SPEC, A = spec, spec["analysis"]


SPEC = load_spec()
A = SPEC["analysis"]


# ------------------------------------------------------------------------------------ the plan (from the spec)

def build_plan(spec: dict, seed: int) -> list[dict]:
    rng = np.random.default_rng(seed)
    take = spec["take"]
    plan: list[dict] = []

    def item(pid, st_, text, sub, **kw):
        return {"pid": pid, "block": st_["block"], "kind": st_["kind"], "text": text, "sub": sub, "max_s": st_.get("max_s"),
                "silence_s": take["silence_s"], "no_sound_s": take["no_sound_s"], "cond": "quiet", "say": None,
                "step": st_["id"], "meter": st_.get("meter", "none"), "feedback": bool(st_.get("feedback")), **kw}

    for s in spec["steps"]:
        if s["kind"] == "confirm":
            plan.append(item(s["id"], s, s["text"], s["sub"], fake=[]))
        elif s["kind"] in ("glide", "anchor"):
            for r in range(1, s["repeats"] + 1):
                plan.append(item(f"{s['id']}_{r}", s, s["text"], s["sub"], anchor=s.get("anchor"),
                                 fake=[({"glide": True} if s["kind"] == "glide" else {"anchor": s["anchor"]}, 0.3)]))
        elif s["kind"] == "level":
            levels = [lv for lv in s["levels"] for _ in range(s["repeats"])]
            if s.get("shuffle"):
                rng.shuffle(levels)
            seen: dict[int, int] = {}
            n = len(s["levels"])
            for lv in levels:
                k = lv["level"]
                seen[k] = seen.get(k, 0) + 1
                stairs = " ".join("▇" if j == k else "▁" for j in range(1, n + 1))
                plan.append(item(f"{s['id']}{k}_{seen[k]}", s, s["text"].format(level=k),
                                 s["sub"].format(stairs=stairs), level=k, pos=lv["pos"],
                                 fake=[({"pos": lv["pos"], "feedback": bool(s.get("feedback"))}, 0.3)]))
        elif s["kind"] == "vowel":
            pairs = [(v, b) for v in s["vowels"] for b in s["bands"] for _ in range(s["repeats"])]
            if s.get("shuffle"):
                rng.shuffle(pairs)
            seen2: dict[tuple, int] = {}
            for v, b in pairs:
                key = (v["vowel"], b["band"])
                seen2[key] = seen2.get(key, 0) + 1
                plan.append(item(f"{s['id']}_{v['vowel']}_{b['band']}_{seen2[key]}", s,
                                 s["text"].format(VOWEL=v["vowel"].upper(), LABEL=b["label"]),
                                 s["sub"].format(hint=v["hint"]), vowel=v["vowel"], band=b["band"], pos=b["pos"],
                                 fake=[({"pos": b["pos"], "vowel": v["vowel"]}, 0.3)]))
    return plan


# ------------------------------------------------------------------------------------ SYNTHETIC voice (self-test only)

# a pretend speaker; its held "highest" note is a falsetto 7 st above the glides, so the self-test exercises the flag
FAKE_VOICE = {"lo_hz": 105.0, "home_hz": 150.0, "hi_hz": 250.0, "pos_sd_st": 0.4, "falsetto_st": 7.0,
              "fb_tau_s": 0.15, "fb_sd_st": 0.1, "fb_start_sd_st": 2.0}
FORMANTS = {"ah": (730, 1090, 2440), "ee": (270, 2290, 3010), "oo": (300, 870, 2240)}


def pos_hz(pos: float, lo: float, home: float, hi: float) -> float:
    """The person's own scale, piecewise log: 0 = low, 0.5 = home, 1 = high."""
    a, b, p = (lo, home, pos / 0.5) if pos <= 0.5 else (home, hi, (pos - 0.5) / 0.5)
    return float(2 ** (np.log2(a) + p * (np.log2(b) - np.log2(a))))


def synth_voice(spec: dict, rate: int, rng: np.random.Generator) -> np.ndarray:
    """A crude source-filter voice: a glottal pulse train through three formant resonators."""
    from scipy.signal import lfilter
    fv = FAKE_VOICE
    dur = 3.0 if spec.get("glide") else 1.8
    n = int(dur * rate)
    if spec.get("glide"):
        f0 = 2 ** np.linspace(np.log2(fv["lo_hz"]) - 0.05, np.log2(fv["hi_hz"]) + 0.05, n)
    else:
        pos = {"low": 0.0, "home": 0.5, "high": 1.0}.get(spec.get("anchor"), spec.get("pos", 0.5))
        target = pos_hz(pos, fv["lo_hz"], fv["home_hz"], fv["hi_hz"])
        if spec.get("anchor") == "high":
            target *= 2 ** (fv["falsetto_st"] / 12)
        start = target * 2 ** (rng.normal(0, fv["fb_start_sd_st" if spec.get("feedback") else "pos_sd_st"]) / 12)
        if spec.get("feedback"):          # with the meter: start off, then home in on the target
            end = target * 2 ** (rng.normal(0, fv["fb_sd_st"]) / 12)
            w = np.exp(-np.arange(n) / rate / fv["fb_tau_s"])
            f0 = 2 ** (w * np.log2(start) + (1 - w) * np.log2(end))
        else:
            f0 = np.full(n, start)
    f0 *= 1 + 0.004 * np.sin(2 * np.pi * 5.5 * np.arange(n) / rate)
    phase = np.cumsum(f0 / rate)
    y = lfilter([1.0], [1.0, -0.95], np.diff(np.floor(phase), prepend=0.0) - np.mean(f0) / rate)
    for f, bw in zip(FORMANTS[spec.get("vowel", "ah")], (80, 100, 120)):
        r = np.exp(-np.pi * bw / rate)
        y = lfilter([1 - r], [1, -2 * r * np.cos(2 * np.pi * f / rate), r * r], y)
    y *= np.minimum(1, np.minimum(np.arange(n), n - np.arange(n)) / (0.05 * rate))
    return (0.1 * y / (np.max(np.abs(y)) + 1e-9)).astype(np.float32)


def fake_cue(fake, spec) -> None:
    """Replaces guided_session.fake_cue while this script runs: a take's cue is a voice spec, not a synth.py class."""
    with fake.lock:
        fake.pending.append(synth_voice(spec, fake.rate, fake.rng))


# ------------------------------------------------------------------------------------ analysis (settings from the spec)

def bark(f):
    f = np.asarray(f, float)
    return 26.81 * f / (1960 + f) - 0.53


def st(f):
    return 12 * np.log2(np.asarray(f, float) / 55.0)


def _nsdf_f0(x: np.ndarray, fs: int, f0_max_hz: float | None = None) -> tuple[float, float]:
    """McLeod pitch (NSDF key maximum) of one frame: (f0 Hz or 0, clarity). f0_max_hz: the ceiling (default the
    spec's f0_max_hz)."""
    n = x.size
    spec = np.fft.rfft(x, 2 * n)
    r = np.fft.irfft(spec * np.conj(spec))[:n]
    c = np.cumsum(x * x)
    tau = np.arange(n)
    m = c[n - 1 - tau] + (c[n - 1] - np.concatenate(([0.0], c[:-1])))
    nsdf = 2 * r / (m + 1e-12)
    lo, hi = max(2, int(fs / (f0_max_hz or A["f0_max_hz"]))), min(n - 2, int(fs / A["f0_min_hz"]))
    seg = nsdf[lo - 1:hi + 2]
    pk = np.flatnonzero((seg[1:-1] > seg[:-2]) & (seg[1:-1] >= seg[2:]) & (seg[1:-1] > 0)) + 1
    if pk.size == 0:
        return 0.0, 0.0
    top = seg[pk].max()
    i = pk[np.argmax(seg[pk] >= A["mpm_k"] * top)]
    a, b, cc = seg[i - 1], seg[i], seg[i + 1]
    den = a - 2 * b + cc
    d = 0.5 * (a - cc) / den if den != 0 else 0.0
    return fs / (lo - 1 + i + d), float(b)


def _formant_cands(x: np.ndarray, fs: int) -> list[tuple[float, float, float]] | None:
    """LPC roots of a pre-emphasised Hamming frame as sorted (frequency, bandwidth, envelope dB); None if LPC fails."""
    from scipy.linalg import solve_toeplitz
    order = A["lpc_order"]
    y = np.append(x[0], x[1:] - A["preemph"] * x[:-1]) * np.hamming(x.size)
    r = np.correlate(y, y, "full")[y.size - 1:y.size + order]
    if r[0] <= 0:
        return None
    try:
        a = solve_toeplitz(r[:order], -r[1:order + 1])
    except Exception:
        return None
    poly = np.r_[1.0, a]
    roots = np.roots(poly)
    roots = roots[np.imag(roots) > 0]
    fr = np.angle(roots) * fs / (2 * np.pi)
    bw = -fs / np.pi * np.log(np.abs(roots) + 1e-12)
    keep = (fr > 150) & (fr < A["f2_hz"][1] + 500)
    fr, bw = fr[keep], bw[keep]
    # the LPC envelope's level (dB) at each candidate: how much of a peak it really makes
    z = np.exp(-2j * np.pi * np.outer(fr, np.arange(poly.size)) / fs)
    lv = -20 * np.log10(np.abs(z @ poly) + 1e-12)
    return sorted((float(f), float(w), float(l)) for f, w, l in zip(fr, bw, lv))


def _pick_formants(c: list[tuple[float, float, float]] | None) -> tuple[float, float] | None:
    """F1 = the lowest candidate in the F1 range with bandwidth < max_bw_hz. F2 = the lowest candidate at least
    f2_min_gap_hz above it in the F2 range with bandwidth < max_bw_hz (v1). v2 also accepts a BROAD candidate
    (max_bw_hz <= bandwidth < f2_max_bw_hz, typical of a back vowel's F2 on a room mic) when its envelope level is at
    least that of the next candidate up, so a weak broad pole between two real formants is still skipped."""
    if not c:
        return None
    nb = A["max_bw_hz"]
    f1 = [f for f, w, _ in c if A["f1_hz"][0] <= f <= A["f1_hz"][1] and w < nb]
    if not f1:
        return None
    bw2 = A.get("f2_max_bw_hz", nb)
    f2 = [(f, w, l) for f, w, l in c if f > f1[0] + A["f2_min_gap_hz"] and A["f2_hz"][0] <= f <= A["f2_hz"][1] and w < bw2]
    for j, (f, w, l) in enumerate(f2):
        if w < nb:
            return f1[0], f
        nxt = next((l2 for _, w2, l2 in f2[j + 1:] if w2 < nb), None)
        if nxt is None or l >= nxt:
            return f1[0], f
    return None


def _formants(x: np.ndarray, fs: int) -> tuple[float, float] | None:
    """(F1, F2) of one frame; None if the picks are not clean."""
    return _pick_formants(_formant_cands(x, fs))


def f2_continuity(f2: np.ndarray) -> np.ndarray:
    """Drop one-off F2 jumps (v2: a lost broad F2 would otherwise read as F3). A frame more than f2_jump_hz from the
    last accepted F2 becomes nan, unless f2_jump_frames frames in a row agree with each other (a real vowel change).
    The last accepted value expires after f2_jump_frames frames without a reading."""
    jump, need = A.get("f2_jump_hz"), A.get("f2_jump_frames", 5)
    if not jump:
        return f2
    out = np.full_like(f2, np.nan)
    last, since, run = np.nan, 0, []
    for i, v in enumerate(f2):
        if np.isnan(v):
            since += 1
            if since > need:
                last, run = np.nan, []
            continue
        since = 0
        if np.isnan(last) or abs(v - last) <= jump:
            out[i], last, run = v, v, []
            continue
        run = [j for j in run if abs(f2[j] - v) <= jump] + [i]
        if len(run) >= need:                      # the new value held: accept it and the run behind it
            out[run] = f2[run]
            last, run = v, []
    return out


def frames(clip: np.ndarray, rate: int) -> dict:
    """Per hop: time (s), level (dB), f0 (Hz, 0 = unvoiced), clarity, F1, F2 (Hz, nan = none)."""
    from math import gcd
    from scipy.signal import butter, lfilter, resample_poly
    fs, win, hop = A["fs"], A["win"], A["hop"]
    x = clip.astype(np.float64)
    if x.ndim > 1:
        x = x[:, 0]
    if rate != fs:
        g = gcd(rate, fs)
        x = resample_poly(x, fs // g, rate // g)
    if A.get("hpf_hz"):
        b, a = butter(2, A["hpf_hz"] / (fs / 2), "high")
        x = lfilter(b, a, x)
    nf = max(0, (x.size - win) // hop + 1)
    t, db, f0, cl, f1, f2 = (np.zeros(nf) for _ in range(6))
    f1[:], f2[:] = np.nan, np.nan
    for i in range(nf):
        fr = x[i * hop:i * hop + win]
        t[i] = (i * hop + win / 2) / fs
        db[i] = 20 * np.log10(np.sqrt(np.mean(fr * fr)) + 1e-9)
    floor = float(np.percentile(db, 10)) if nf else -90.0
    for i in range(nf):
        if db[i] < floor + A["level_over_floor_db"]:
            continue
        fr = x[i * hop:i * hop + win]
        f0[i], cl[i] = _nsdf_f0(fr - fr.mean(), fs)
        if cl[i] >= A["clarity_min"]:
            fm = _formants(fr, fs)
            if fm:
                f1[i], f2[i] = fm
    voiced = (cl >= A["clarity_min"]) & (f0 > 0) & (db >= floor + A["level_over_floor_db"])
    f0[~voiced] = 0.0
    f2 = f2_continuity(f2)
    f1[np.isnan(f2)] = np.nan
    return {"t": t, "db": db, "f0": f0, "clarity": cl, "f1": f1, "f2": f2, "voiced": voiced, "floor_db": floor}


def smooth(v: np.ndarray, n: int) -> np.ndarray:
    """Moving mean over n frames, ignoring nan (the vibrato smoother: n covers >= one vibrato cycle)."""
    ok = np.isfinite(v)
    k = np.ones(n)
    num = np.convolve(np.where(ok, v, 0.0), k, "same")
    den = np.convolve(ok.astype(float), k, "same")
    out = num / np.maximum(den, 1e-9)
    out[den < n / 2] = np.nan
    return out


def steady_part(fr: dict, pre_s: float) -> np.ndarray:
    """Indices of the take's steady voiced part: onset + attack_skip to last voiced - release_skip, <= max_steady."""
    v = np.flatnonzero(fr["voiced"] & (fr["t"] >= pre_s - 0.1))
    if v.size < 10:
        return np.zeros(0, int)
    on, off = fr["t"][v[0]], fr["t"][v[-1]]
    a0 = on + A["attack_skip_ms"] / 1000
    return v[(fr["t"][v] >= a0) & (fr["t"][v] <= min(off - A["release_skip_ms"] / 1000, a0 + A["max_steady_ms"] / 1000))]


def lock_ms(fr: dict, pre_s: float, f2_tol_hz: float | None = None) -> float | None:
    """ms from onset until the lock: the first lock_window in which the SMOOTHED pitch stays within lock_pitch_st of
    its median (and F2 within f2_tol_hz); lock = that window's end. None if it never settles."""
    hop_ms = 1000 * A["hop"] / A["fs"]
    n_s, n_w = max(1, round(A["smooth_ms"] / hop_ms)), round(A["lock_window_ms"] / hop_ms)
    v = np.flatnonzero(fr["voiced"] & (fr["t"] >= pre_s - 0.1))
    if v.size < n_w:
        return None
    on = v[0]
    s = smooth(np.where(fr["voiced"], st(np.maximum(fr["f0"], 1)), np.nan), n_s)
    f2s = smooth(fr["f2"], n_s)
    for i in range(on, fr["t"].size - n_w):
        w = s[i:i + n_w]
        if np.isnan(w).mean() > 0.1 or np.nanmax(np.abs(w - np.nanmedian(w))) > A["lock_pitch_st"]:
            continue
        if f2_tol_hz is not None:
            f = f2s[i:i + n_w]
            if np.isnan(f).mean() > 0.5 or np.nanmax(np.abs(f - np.nanmedian(f))) > f2_tol_hz:
                continue
        return round(1000 * (fr["t"][i] - fr["t"][on]) + A["lock_window_ms"], 0)
    return None


def measure_take(fr: dict, pre_s: float) -> dict:
    k = steady_part(fr, pre_s)
    if k.size < 10:
        return {"f0_hz": None, "st": None, "f1_hz": None, "f2_hz": None, "f2_sd_hz": None, "frames": int(k.size)}
    f0 = float(np.median(fr["f0"][k]))
    f1, f2 = fr["f1"][k], fr["f2"][k]
    okf = np.isfinite(f2).sum() >= 5
    return {"f0_hz": f0, "st": float(st(f0)), "f1_hz": float(np.nanmedian(f1)) if okf else None,
            "f2_hz": float(np.nanmedian(f2)) if okf else None, "f2_sd_hz": float(np.nanstd(f2)) if okf else None,
            "frames": int(k.size)}


def vowel_windows(fr: dict, k: np.ndarray) -> list[tuple[float, float]]:
    """(F1, F2) in Bark per vowel window of the steady part (median, after the vibrato smoother)."""
    hop_ms = 1000 * A["hop"] / A["fs"]
    n = round(A["vowel_window_ms"] / hop_ms)
    n_s = max(1, round(A["smooth_ms"] / hop_ms))
    f1s, f2s = smooth(fr["f1"], n_s), smooth(fr["f2"], n_s)
    out = []
    for s0 in range(0, k.size - n + 1, n):
        w = k[s0:s0 + n]
        if np.isfinite(fr["f2"][w]).mean() >= A["vowel_window_min_formant_frac"] and np.isfinite(f2s[w]).any():
            out.append((float(bark(np.nanmedian(f1s[w]))), float(bark(np.nanmedian(f2s[w])))))
    return out


def loo_vowel_accuracy(win: list[tuple[str, str, float, float]]) -> float | None:
    """win = (group id, vowel, F1 Bark, F2 Bark). Each window is classified by the nearest vowel centroid built from
    the OTHER groups (takes or files): leave-one-group-out, so a take never calibrates itself."""
    hits = n = 0
    for g, v, x1, x2 in win:
        cent = {}
        for vv in {w[1] for w in win}:
            pts = [(y1, y2) for gg, v2, y1, y2 in win if v2 == vv and gg != g]
            if pts:
                cent[vv] = np.mean(pts, axis=0)
        if len(cent) < 2 or v not in cent:
            continue
        pred = min(cent, key=lambda c: (cent[c][0] - x1) ** 2 + (cent[c][1] - x2) ** 2)
        hits += int(pred == v)
        n += 1
    return hits / n if n else None


# ------------------------------------------------------------------------------------ scoring (rules from the spec)

def pos_st(pos: float, lo: float, home: float, hi: float) -> float:
    """pos on the person's own scale (0 = low, 0.5 = home, 1 = high, piecewise) -> semitones."""
    return lo + pos / 0.5 * (home - lo) if pos <= 0.5 else home + (pos - 0.5) / 0.5 * (hi - home)


def st_pos(s: float, lo: float, home: float, hi: float) -> float:
    """The inverse of pos_st (not clamped: below the low end < 0, above the high end > 1)."""
    if s <= home:
        return 0.5 * (s - lo) / (home - lo) if home > lo else 0.0
    return 0.5 + 0.5 * (s - home) / (hi - home) if hi > home else 1.0


def glide_steady_st(fr: dict) -> np.ndarray:
    """Semitones of a glide's STEADY frames: voiced, the smoothed pitch moving < glide_max_step_st per hop, and the raw
    frame within 1 st of the smoothed one (so cracks, breaks and one-frame octave errors drop out)."""
    rr = SPEC["rules"]["range"]
    hop_ms = 1000 * A["hop"] / A["fs"]
    raw = np.where(fr["voiced"], st(np.maximum(fr["f0"], 1)), np.nan)
    s = smooth(raw, max(1, round(A["smooth_ms"] / hop_ms)))
    step = np.abs(np.gradient(s))
    ok = np.isfinite(raw) & np.isfinite(s) & (step < rr["glide_max_step_st"]) & (np.abs(raw - s) < 1.0)
    return raw[ok]


def person_range(anchor: dict[str, list[float]], glide_st: np.ndarray, spec: dict) -> dict:
    """The person's comfortable range (st). v1: the held anchors. v2 (rules.range): the glides, capped by the held
    notes, with a flag for a held note far beyond the glide (falsetto / strain)."""
    lo_a = float(np.median(anchor["low"])) if anchor["low"] else None
    hi_a = float(np.median(anchor["high"])) if anchor["high"] else None
    home = float(np.mean(anchor["home"])) if anchor["home"] else None
    rr = spec["rules"].get("range")
    out = {"lo_anchor_st": lo_a, "hi_anchor_st": hi_a, "flags": []}
    if not rr:
        lo, hi = lo_a, hi_a
    else:
        g_lo = float(np.percentile(glide_st, rr["glide_bottom_pct"])) if glide_st.size >= 20 else None
        g_hi = float(np.percentile(glide_st, rr["glide_top_pct"])) if glide_st.size >= 20 else None
        out.update({"lo_glide_st": g_lo, "hi_glide_st": g_hi})
        f = rr["anchor_glide_flag_st"]
        if hi_a is not None and g_hi is not None and hi_a - g_hi > f:
            out["flags"].append(f"held high note is {hi_a - g_hi:.1f} st above the glide top (falsetto or strain?): "
                                "the glide top is used")
        if lo_a is not None and g_lo is not None and g_lo - lo_a > f:
            out["flags"].append(f"held low note is {g_lo - lo_a:.1f} st below the glide bottom (creak or strain?): "
                                "the glide bottom is used")
        his = [x for x in (g_hi, hi_a) if x is not None]
        los = [x for x in (g_lo, lo_a) if x is not None]
        hi, lo = (min(his) if his else None), (max(los) if los else None)
        if lo is not None and hi is not None and hi <= lo:
            out["flags"].append("range is empty: the held notes and the glides disagree; redo the range")
    if home is not None and lo is not None and hi is not None and not lo < home < hi:
        out["flags"].append("home note is outside the range; it is clamped for the level scale")
    rng_st = hi - lo if lo is not None and hi is not None else None
    out.update({"lo_st": lo, "hi_st": hi, "range_st": rng_st, "home_st": home,
                "lo_hz": 55 * 2 ** (lo / 12) if lo is not None else None,
                "hi_hz": 55 * 2 ** (hi / 12) if hi is not None else None})
    return out


def scale_of(rg: dict) -> tuple[float, float, float] | None:
    lo, hi, home = rg.get("lo_st"), rg.get("hi_st"), rg.get("home_st")
    if lo is None or hi is None or hi <= lo:
        return None
    home = home if home is not None else (lo + hi) / 2
    return lo, float(np.clip(home, lo + 0.1 * (hi - lo), hi - 0.1 * (hi - lo))), hi


def feedback_measure(fr: dict, pre_s: float, target: float) -> dict:
    """With the meter: time-to-target, final error, overshoot (see rules.feedback)."""
    fb = SPEC["rules"]["feedback"]
    hop_ms = 1000 * A["hop"] / A["fs"]
    n_s, n_w = max(1, round(A["smooth_ms"] / hop_ms)), round(A["lock_window_ms"] / hop_ms)
    v = np.flatnonzero(fr["voiced"] & (fr["t"] >= pre_s - 0.1))
    if v.size < n_w:
        return {"reached": False, "ttt_ms": None, "final_err_st": None, "overshoot_st": None}
    on = v[0]
    s = smooth(np.where(fr["voiced"], st(np.maximum(fr["f0"], 1)), np.nan), n_s)
    tol = A["lock_pitch_st"]
    lock_i = None
    for i in range(on, fr["t"].size - n_w):
        w = s[i:i + n_w]
        if np.isnan(w).mean() <= 0.1 and np.nanmax(np.abs(w - target)) <= tol:
            lock_i = i
            break
    start = float(np.nanmedian(s[on:on + 5])) if np.isfinite(s[on:on + 5]).any() else target
    d = np.sign(target - start) or 1.0
    before = s[on:(lock_i if lock_i is not None else v[-1]) + 1]
    over = float(max(0.0, np.nanmax(d * (before - target)))) if np.isfinite(before).any() else None
    end = v[-1] - round(A["release_skip_ms"] / hop_ms)
    tail = s[max(on, end - round(fb["final_ms"] / hop_ms)):end + 1]
    final = float(np.nanmedian(tail) - target) if np.isfinite(tail).any() else None
    return {"reached": lock_i is not None,
            "ttt_ms": round(1000 * (fr["t"][lock_i] - fr["t"][on]) + A["lock_window_ms"], 0) if lock_i is not None else None,
            "final_err_st": final, "overshoot_st": over}


def rows_from(rng_st: float | None, sd: float | None, rules: dict) -> int | None:
    if not rng_st or not sd or rng_st <= 0:
        return None
    return int(min(rules["max_rows"], np.floor(rng_st / (rules["rows_sd_factor"] * sd))))


def score_session(d: Path, spec: dict = SPEC) -> dict:
    import soundfile as sf
    use_spec(spec)
    rules = spec["rules"]
    rows = {}
    for r in G.read_rows(d):
        rows[r["pid"]] = r                   # the last line per prompt wins (redos)
    takes = [r for r in rows.values() if r["status"] == "kept" and r.get("heard")]
    fb_steps = {s["id"] for s in spec["steps"] if s.get("feedback")}
    per: list[dict] = []
    fr_by: dict[str, tuple[dict, np.ndarray]] = {}
    for r in sorted(takes, key=lambda r: r["take"]):
        x, rate = sf.read(str(d / r["file"]), dtype="float32")
        fr = frames(x, rate)
        m = measure_take(fr, r.get("pre_s", 1.0))
        m.update({k: r.get(k) for k in ("pid", "step", "kind", "anchor", "level", "pos", "vowel", "band", "file")})
        m["feedback"] = r.get("step") in fb_steps
        m["lock_ms"] = lock_ms(fr, r.get("pre_s", 1.0)) if r["kind"] == "level" and not m["feedback"] else None
        per.append(m)
        fr_by[r["pid"]] = (fr, steady_part(fr, r.get("pre_s", 1.0)))
    by_kind = lambda k, **kw: [m for m in per if m["kind"] == k and m["st"] is not None  # noqa: E731
                               and all(m.get(a) == b for a, b in kw.items())]
    anchor = {a: [m["st"] for m in by_kind("anchor", anchor=a)] for a in ("low", "home", "high")}
    gl_raw = [st(fr_by[m["pid"]][0]["f0"][fr_by[m["pid"]][0]["voiced"]]) for m in per if m["kind"] == "glide"]
    gl_raw = np.concatenate(gl_raw) if gl_raw else np.zeros(0)
    gl = (np.concatenate([glide_steady_st(fr_by[m["pid"]][0]) for m in per if m["kind"] == "glide"] or [np.zeros(0)])
          if rules.get("range") else gl_raw)
    rg = person_range(anchor, gl, spec)
    lo, hi, rng_st, home = rg["lo_st"], rg["hi_st"], rg["range_st"], rg["home_st"]
    scale = scale_of(rg)
    # levels, blind: pooled repeat SD from silence
    by: dict[int, list[float]] = {}
    for m in by_kind("level", feedback=False):
        by.setdefault(m["level"], []).append(m["st"])
    ss = sum(((np.array(x) - np.mean(x)) ** 2).sum() for x in by.values() if len(x) > 1)
    dfree = sum(len(x) - 1 for x in by.values() if len(x) > 1)
    sd = float(np.sqrt(ss / dfree)) if dfree else None
    means = {str(k): float(np.mean(x)) for k, x in sorted(by.items())}
    rows_blind = rows_from(rng_st, sd, rules)
    # levels, with the meter: targets on the person's scale (the range they accepted, else the scored one)
    fbm: list[dict] = []
    meta_p = d / "session.json"
    acc_rg = (json.loads(meta_p.read_text()).get("range") or {}) if meta_p.exists() else {}
    tscale = scale_of(acc_rg) or scale
    for m in per:
        if m["kind"] == "level" and m["feedback"] and tscale:
            tgt = pos_st(m["pos"], *tscale)
            f = feedback_measure(fr_by[m["pid"]][0], 1.0, tgt)
            f.update({"pid": m["pid"], "level": m["level"], "target_st": tgt})
            m.update({k: f[k] for k in ("reached", "ttt_ms", "final_err_st", "overshoot_st", "target_st")})
            fbm.append(f)
    # every feedback prompt counts: a skipped one, or one with no steady pitch, is "never reached"
    n_fb_prompts = sum(1 for r in rows.values() if r.get("step") in fb_steps and r["status"] in ("kept", "skipped"))
    reached = [f for f in fbm if f["reached"]]
    errs = [f["final_err_st"] for f in reached if f["final_err_st"] is not None]
    fb_rms = float(np.sqrt(np.mean(np.square(errs)))) if errs else None
    ttts = [f["ttt_ms"] for f in reached]
    feedback = None
    if fb_steps:
        feedback = {"n": n_fb_prompts, "reached": len(reached),
                    "never_reached": n_fb_prompts - len(reached),
                    "never_reached_frac": (n_fb_prompts - len(reached)) / n_fb_prompts if n_fb_prompts else None,
                    "ttt_ms_median": float(np.median(ttts)) if ttts else None,
                    "ttt_ms_p90": float(np.percentile(ttts, 90)) if ttts else None,
                    "final_err_rms_st": fb_rms,
                    "final_err_median_st": float(np.median(errs)) if errs else None,
                    "overshoot_median_st": float(np.median([f["overshoot_st"] for f in fbm if f["overshoot_st"] is not None]))
                    if fbm else None,
                    "targets_from": "accepted range (session.json)" if scale_of(acc_rg) else "scored range"}
    rows_feedback = rows_from(rng_st, fb_rms, rules) if feedback else None
    # vowels per band: the prompted band (v1) or the MEASURED band (v2)
    vstep = next(s for s in spec["steps"] if s["kind"] == "vowel")
    band_pos = {b["band"]: b["pos"] for b in vstep["bands"]}
    vw = [m for m in per if m["kind"] == "vowel"]
    measured = rules.get("vowel_band_by") == "measured"
    for m in vw:
        m["band_prompted"] = m["band"]
        if measured:
            if m["st"] is not None and scale:
                p = st_pos(m["st"], *scale)
                m["pos_measured"] = p
                m["band"] = min(band_pos, key=lambda b: abs(band_pos[b] - p))
            else:
                m["band"] = None
    band_res = {}
    for b in band_pos:
        win = []
        for m in vw:
            if m["band"] != b:
                continue
            fr, k = fr_by[m["pid"]]
            win += [(m["pid"], m["vowel"], x1, x2) for x1, x2 in vowel_windows(fr, k)]
        acc = loo_vowel_accuracy(win)
        f0s = [m["f0_hz"] for m in vw if m["band"] == b and m["f0_hz"]]
        band_res[b] = {"acc": acc, "windows": len(win), "takes": sum(m["band"] == b for m in vw),
                       "vowels": sorted({m["vowel"] for m in vw if m["band"] == b}),
                       "f0_hz": float(np.median(f0s)) if f0s else None,
                       "columns": "vowel" if acc is not None and acc >= rules["vowel_acc_min"] else "snap"}
    moved = sum(1 for m in vw if m["band"] != m["band_prompted"])
    f2 = {v: float(np.median([m["f2_hz"] for m in vw if m["vowel"] == v and m["f2_hz"]]))
          for v in ("ee", "ah", "oo") if any(m["vowel"] == v and m["f2_hz"] for m in vw)}
    quarter = abs(f2["ee"] - f2["oo"]) * spec["analysis"]["lock_f2_frac_of_ee_oo"] if {"ee", "oo"} <= f2.keys() else None
    vl = [lock_ms(fr_by[m["pid"]][0], 1.0, quarter) for m in vw] if quarter else []
    locks = [m["lock_ms"] for m in per if m["kind"] == "level" and not m["feedback"]] + vl
    lk = [x for x in locks if x is not None]
    wob = [m["f2_sd_hz"] for m in vw if m["f2_sd_hz"] is not None]
    any_vowel = any(v["columns"] == "vowel" for v in band_res.values())
    go = rules.get("go")
    if not go:                                     # v1
        ok_rows = rows_blind is not None and rows_blind >= rules["min_rows"]
        verdict = "GO" if ok_rows and any_vowel else "SNAP-ONLY" if ok_rows else "NO-GO"
        verdict_uses, why = "blind", None
    else:
        verdict_uses = go["uses"]
        if feedback is None or not feedback["n"]:
            verdict, why = "INCOMPLETE", "no feedback (meter) level takes: the go/no-go uses them"
        else:
            fails = []
            if (rows_feedback or 0) < go["rows_feedback_min"]:
                fails.append(f"rows_feedback {rows_feedback} < {go['rows_feedback_min']}")
            if feedback["ttt_ms_p90"] is None or feedback["ttt_ms_p90"] > go["time_to_target_p90_max_ms"]:
                fails.append(f"time-to-target p90 {feedback['ttt_ms_p90']} ms > {go['time_to_target_p90_max_ms']}")
            if feedback["never_reached_frac"] > go["never_reached_max_frac"]:
                fails.append(f"never reached {feedback['never_reached']}/{feedback['n']}")
            verdict = ("GO" if any_vowel else "SNAP-ONLY") if not fails else "NO-GO"
            why = "; ".join(fails) or "all feedback criteria met"
    return {
        "spec": spec["version"], "session": d.name, "synthetic": any(r.get("synthetic") for r in takes),
        "takes": per,
        "person": {
            "range": {**rg, "glide_extremes_st": [float(np.percentile(gl_raw, 2)), float(np.percentile(gl_raw, 98))]
                      if gl_raw.size > 20 else None},
            "home": {"st": home, "sd_st": float(np.std(anchor["home"], ddof=1)) if len(anchor["home"]) > 1 else None},
            "levels": {"means_st": means, "repeat_sd_st": sd,
                       "targets_st": {str(lv["level"]): pos_st(lv["pos"], *scale) for lv in
                                      next(s for s in spec["steps"] if s["kind"] == "level")["levels"]} if scale else None,
                       "in_order": bool(all(np.diff(list(means.values())) > 0)) if len(means) > 1 else None,
                       "level_loo_acc": loo_level(by)},
            "feedback": feedback,
            "vowels": {"bands": band_res, "band_by": "measured" if measured else "prompted",
                       "takes_moved_band": moved if measured else None,
                       "takes_no_pitch": sum(1 for m in vw if m["st"] is None),
                       "f2_median_hz": f2, "f2_within_hold_sd_hz": float(np.median(wob)) if wob else None,
                       "f2_quarter_ee_oo_hz": quarter},
            "lock": {"p90_ms": float(np.percentile(lk, 90)) if lk else None,
                     "never_settled": sum(x is None for x in locks), "n": len(locks)}},
        "profile": {"rows": rows_feedback if go and verdict_uses == "feedback" else rows_blind,
                    "rows_blind": rows_blind, "rows_feedback": rows_feedback,
                    "absolute_no_look": (rows_blind is not None and rows_blind >= go["blind_rows_absolute_min"]) if go else None,
                    "columns_by_band": {b: v["columns"] for b, v in band_res.items()}},
        "verdict": verdict, "verdict_uses": verdict_uses, "verdict_why": why,
    }


# ------------------------------------------------------------------------------------ live pitch and the meter

def live_pitch(x: np.ndarray, rate: int) -> tuple[float, float, float]:
    """(f0 Hz, clarity, level dB) of the newest analysis window of live audio."""
    from math import gcd
    from scipy.signal import resample_poly
    fs, win = A["fs"], A["win"]
    y = x.astype(np.float64)
    if rate != fs:
        g = gcd(rate, fs)
        y = resample_poly(y, fs // g, rate // g)
    y = y[-win:]
    if y.size < win:
        return 0.0, 0.0, -120.0
    lv = 20 * np.log10(np.sqrt(np.mean(y * y)) + 1e-9)
    f0, cl = _nsdf_f0(y - y.mean(), fs)
    return f0, cl, lv


class Meter:
    """A vertical pitch meter of the person's range: level marks, the target line, and the pitch now (plain ANSI)."""

    def __init__(self, scale: tuple[float, float, float], levels: list[dict]):
        lv = SPEC["live"]
        self.lo, self.home, self.hi = scale
        self.top, self.bot = self.hi + lv["meter_margin_st"], self.lo - lv["meter_margin_st"]
        self.n = lv["meter_lines"]
        self.marks = {self.line(pos_st(l["pos"], *scale)): l["level"] for l in levels}
        self.drawn = 0

    def line(self, s: float) -> int:
        return int(round((self.top - s) / (self.top - self.bot) * (self.n - 1)))

    def lines(self, cur: float | None, target: float | None = None, locked: bool = False, note: str = "") -> list[str]:
        tl = self.line(target) if target is not None else None
        cl = None if cur is None else self.line(cur)
        names = {self.line(self.hi): "high", self.line(self.home): "home", self.line(self.lo): "low"}
        out = []
        for i in range(self.n):
            name = names.get(i, "")
            mk = self.marks.get(i)
            bar = "━━━━━━━━━━" if i == tl else ("──────────" if mk else "          ")
            if i == tl:
                bar = G.sty(bar, "1;92" if locked else "1;93")
            elif mk:
                bar = G.sty(bar, "2")
            dot = ""
            if cl is not None:
                if cl == i or (i == 0 and cl < 0) or (i == self.n - 1 and cl >= self.n):
                    dot = G.sty(" ● you" if 0 <= cl < self.n else (" ▲ above" if cl < 0 else " ▼ below"), "1;96")
            out.append(f"   {name:>5s} {str(mk) if mk else ' '} │{bar}│{dot}")
        out.append("   " + (G.sty(note, "2") if note else ""))
        return out

    def draw(self, *a, **kw) -> None:
        ls = self.lines(*a, **kw)
        if G.TTY and self.drawn:
            print(f"\x1b[{self.drawn}F", end="")
        for l in ls:
            print(("\x1b[2K" if G.TTY else "") + l)
        self.drawn = len(ls)


def take_live(rec: R.Recorder, t: dict, fake: R.FakeSource | None, meter: Meter | None,
              target: float | None) -> dict:
    """Record one take, started and stopped by VOICE (not by loudness, so a breath thump neither starts nor ends it),
    drawing the live meter when one is given. Returns the same marks as guided_session.take_one."""
    lv, tick = SPEC["live"], SPEC["live"]["tick_ms"] / 1000
    key = rec.n
    rec.wait_s(G.KEY_GUARD_S)
    go = rec.n
    print(G.sty("   ●  GO", "1;92"), flush=True)
    if fake:
        for cls, off in t["fake"]:
            rec.wait_until(go + int(off * rec.rate))
            fake_cue(fake, cls)
    blk = rec.rate // 20
    pre = rec.audio(max(0, go - rec.rate // 2), go)
    base = np.median(20 * np.log10(np.sqrt(np.mean(pre[: pre.size // blk * blk].reshape(-1, blk).astype(np.float64) ** 2,
                                                   axis=1)) + 1e-9)) if pre.size >= blk else -80.0
    need = int(A["win"] * rec.rate / A["fs"]) + 64
    n_s = max(1, round(A["smooth_ms"] / 1000 / tick))
    heard, run, last_voiced = False, 0, go
    hist: list[float] = []
    in_tol_since, locked = None, False
    reason = "max length"
    if meter:
        meter.draw(None, target)
    while True:
        if not rec.wait_s(tick):
            reason = "capture ended"
            break
        f0, cl, lvl = live_pitch(rec.audio(rec.n - need, rec.n), rec.rate)
        voiced = f0 > 0 and cl >= A["clarity_min"] and lvl >= base + A["level_over_floor_db"]
        el = (rec.n - go) / rec.rate
        cur = None
        if voiced:
            run += 1
            last_voiced = rec.n
            hist = (hist + [float(st(f0))])[-n_s:]
            heard = heard or run >= lv["voiced_ticks_to_start"]
            cur = float(np.mean(hist))
            if target is not None and abs(cur - target) <= A["lock_pitch_st"]:
                in_tol_since = in_tol_since if in_tol_since is not None else rec.n
                locked = locked or (rec.n - in_tol_since) / rec.rate * 1000 >= A["lock_window_ms"]
            else:
                in_tol_since = None
        else:
            run = 0
        if meter and G.TTY:
            meter.draw(cur, target, locked, "locked: you can stop" if locked else "")
        if heard and (rec.n - last_voiced) / rec.rate >= t["silence_s"]:
            reason = "silence"
            break
        if el >= t["max_s"]:
            break
        if not heard and el >= t["no_sound_s"]:
            reason = "no sound"
            break
    if meter and not G.TTY:                      # a log gets the meter once, at the end
        meter.draw(float(np.mean(hist)) if hist else None, target, locked)
    if heard and reason == "max length":
        rec.wait_s(G.POST_S)
    end = min(rec.n, last_voiced + int(G.POST_S * rec.rate)) if heard else rec.n
    return {"key": key, "go": go, "end": max(end, go), "heard": heard, "stop_reason": reason,
            "base_db": round(float(base), 1), "locked_live": locked}


def range_so_far(out: Path, done: set[str]) -> dict:
    """The person's range from the range/home takes recorded so far (the scorer's own rule)."""
    import soundfile as sf
    rows = {}
    for r in G.read_rows(out):
        rows[r["pid"]] = r
    anchor: dict[str, list[float]] = {"low": [], "home": [], "high": []}
    gl = []
    for r in rows.values():
        if r["status"] != "kept" or not r.get("heard") or r.get("kind") not in ("glide", "anchor"):
            continue
        x, rate = sf.read(str(out / r["file"]), dtype="float32")
        fr = frames(x, rate)
        if r["kind"] == "glide":
            gl.append(glide_steady_st(fr))
        else:
            m = measure_take(fr, r.get("pre_s", 1.0))
            if m["st"] is not None:
                anchor[r["anchor"]].append(m["st"])
    return person_range(anchor, np.concatenate(gl) if gl else np.zeros(0), SPEC)


# ------------------------------------------------------------------------------------ recording

def run_session(a: argparse.Namespace) -> None:
    import soundfile as sf
    use_spec(load_spec(SPEC_PATH))
    src = R.make_source(a)
    fake = src if isinstance(src, R.FakeSource) else None
    name = a.session or datetime.now().strftime("vcursor-%Y%m%d-%H%M%S")
    if fake and "synthetic" not in name:
        name += "-synthetic"
    out = HERE / "recordings" / name
    out.mkdir(parents=True, exist_ok=True)
    meta_p = out / "session.json"
    spec_sha = hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest()[:12]
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {
        "created": datetime.now().isoformat(timespec="seconds"), "session": name, "test": "voice_cursor",
        "spec": SPEC["version"], "spec_sha": spec_sha, "synthetic": bool(fake), "seed": a.seed,
        "private": "the user's voice: never commit, never upload", "runs": []}
    if meta.get("spec") != SPEC["version"]:
        raise SystemExit(f"{out} was recorded with {meta.get('spec')}; this script records {SPEC['version']}. "
                         "Use a new --session name (the old one still scores with its own spec).")
    if meta.get("spec_sha") != spec_sha:
        print(G.sty(f"NOTE: the spec changed since this session started ({meta.get('spec_sha')} -> {spec_sha}).", "1;93"))
    plan = build_plan(SPEC, meta["seed"])
    rows = G.read_rows(out)
    if rows and any(r.get("synthetic") for r in rows) != bool(fake):
        raise SystemExit(f"{out} mixes a real and a SYNTHETIC source; use another --session")
    done = {r["pid"] for r in rows if r["status"] in ("kept", "skipped")}
    auto = a.auto or (fake is not None and not a.interactive)
    if not [t for t in plan if t["pid"] not in done]:
        print(f"session {name}: every prompt is done. Score it with:\n"
              f"  ./run python voice_cursor_test.py --score recordings/{name}")
        return
    if not fake and isinstance(src, R.PwSource) and "CMEDIA" not in (src.target or ""):
        print(G.sty(f"NOTE: recording from {src.target}, not the CMEDIA USB mic the guided session used. Pass "
                    "--device alsa_input.usb-CMEDIA_Q9-1-00.mono-fallback (see --list-devices) if that's wrong.", "1;93"))
    G.fake_cue = fake_cue          # (take_live cues SYNTHETIC takes through fake_cue too)
    run = f"run-{len(list(out.glob('run-*'))) + 1:02d}"
    cfg = R.load_cfg(a.config)
    rec = R.Recorder(src, cfg, out / run, print_events=False)
    (out / run / "config.json").write_text(cfg.to_json())
    rec.start()
    sig = R.check_signal(rec, 1.5, a.allow_silent)
    meta["runs"].append({"run": run, "started": datetime.now().isoformat(timespec="seconds"), "source": src.name,
                         "capture_rate": src.rate, "synthetic": bool(fake), "signal_check": sig, "argv": sys.argv[1:]})
    meta_p.write_text(json.dumps(meta, indent=1))
    labels = (out / "labels.jsonl").open("a")
    n_take = len(rows)
    last_t = None
    quit_ = False
    t_start = time.monotonic()
    blocks = [b["id"] for b in SPEC["blocks"]]
    intro = {b["id"]: b["intro"] for b in SPEC["blocks"]}
    level_step = next(s for s in SPEC["steps"] if s["kind"] == "level")
    band_pos = {b["band"]: b["pos"] for s in SPEC["steps"] if s["kind"] == "vowel" for b in s["bands"]}

    def write(row: dict) -> None:
        labels.write(json.dumps(row, default=float) + "\n")
        labels.flush()

    def scale_now() -> tuple[float, float, float] | None:
        return scale_of(meta.get("range") or {})

    def confirm(t: dict) -> str:
        """Show the measured range on the meter: Enter = use it, r = redo the range and home note."""
        rg = range_so_far(out, done)
        sc = scale_of(rg)
        G.clear()
        print(G.sty("\n  YOUR RANGE\n", "1;96"))
        if sc is None:
            print(G.sty("   No usable range was measured (no steady glide or held notes). Redo the range.", "1;93"))
            return "r" if not auto else "\n"
        f = lambda s: f"{55 * 2 ** (s / 12):.0f} Hz"  # noqa: E731
        print(f"   low {f(rg['lo_st'])}   home {f(rg['home_st'])}   high {f(rg['hi_st'])}   "
              f"= {rg['range_st']:.1f} semitones")
        print(G.sty(f"   (glides {f(rg['lo_glide_st']) if rg.get('lo_glide_st') is not None else '–'} to "
                    f"{f(rg['hi_glide_st']) if rg.get('hi_glide_st') is not None else '–'}; held notes "
                    f"{f(rg['lo_anchor_st']) if rg['lo_anchor_st'] is not None else '–'} to "
                    f"{f(rg['hi_anchor_st']) if rg['hi_anchor_st'] is not None else '–'})", "2"))
        for fl in rg["flags"]:
            print(G.sty(f"   ! {fl}", "1;93"))
        print()
        Meter(sc, level_step["levels"]).draw(sc[1], None, False, "● = your home note; the lines are levels 1-5")
        print(G.sty(f"\n   {t['sub']}    q = quit", "1"))
        k = G.getkey(auto)
        if k == "\n":
            meta["range"] = {**{k2: rg[k2] for k2 in ("lo_st", "home_st", "hi_st", "range_st", "lo_glide_st",
                                                      "hi_glide_st", "lo_anchor_st", "hi_anchor_st", "flags")},
                             "accepted": datetime.now().isoformat(timespec="seconds")}
            meta_p.write_text(json.dumps(meta, indent=1, default=float))
        return k

    try:
        bi = 0
        while bi < len(blocks):
            b = blocks[bi]
            block = [t for t in plan if t["block"] == b]
            items = [t for t in block if t["pid"] not in done]
            if not items:
                bi += 1
                continue
            G.clear()
            print(G.sty(f"\n  PART {bi + 1} of {len(blocks)}: {b.upper()}   ({len(items)} prompts)\n", "1;96"))
            for line in intro[b]:
                print("   " + line)
            print(G.sty("\n   Keys:  Enter = record   r = redo last take   s = skip   q = quit (resume later)", "2"))
            print(G.sty("\n   Press Enter to begin (q to stop here).", "1"))
            if G.getkey(auto) == "q":
                quit_ = True
                break
            i, restart = 0, False
            while i < len(items):
                t = items[i]
                if t["kind"] == "confirm":
                    k = confirm(t)
                    if k == "q":
                        quit_ = True
                        break
                    if k == "r":                  # redo the range and the home note
                        done.difference_update(p["pid"] for p in plan if p["block"] in ("range", "home"))
                        meta.pop("range", None)
                        meta_p.write_text(json.dumps(meta, indent=1, default=float))
                        restart = True
                        break
                    n_take += 1
                    write({"take": n_take, "pid": t["pid"], "block": b, "kind": "confirm", "step": t["step"],
                           "status": "kept", "heard": False, "run": run, "range": meta.get("range"),
                           "synthetic": bool(fake), "time": datetime.now().isoformat(timespec="seconds")})
                    done.add(t["pid"])
                    i += 1
                    continue
                G.clear()
                G.header(t, block.index(t), len(block), len(done), len(plan), bi, len(blocks))
                G.big(t["text"])
                print("\n   " + G.sty(t["sub"], "1"))
                if fake:
                    print(G.sty("   [SYNTHETIC fake mic]", "93"))
                print(G.sty("\n   Enter = record    r = redo last    s = skip    q = quit", "2"))
                k = G.getkey(auto)
                if k == "q":
                    quit_ = True
                    break
                redo = False
                if k == "s":
                    n_take += 1
                    write({"take": n_take, "pid": t["pid"], "block": b, "kind": t["kind"], "step": t["step"],
                           "status": "skipped", "run": run, "synthetic": bool(fake)})
                    done.add(t["pid"])
                    i += 1
                    continue
                if k == "r":
                    if not last_t:
                        continue
                    t, redo = last_t, True
                    G.clear()
                    print(G.sty("   REDO of the last take:\n", "1;93"))
                    G.big(t["text"])
                    print("\n   " + G.sty(t["sub"], "1"))
                    print(G.sty("\n   Press Enter to record it again (s = cancel the redo).", "2"))
                    if G.getkey(auto) != "\n":
                        continue
                sc = scale_now()
                meter, target = None, None
                if sc and t["meter"] in ("live", "target"):
                    meter = Meter(sc, level_step["levels"])
                    if t["meter"] == "target" and t.get("pos") is not None:
                        target = pos_st(t["pos"], *sc)
                elif t["meter"] == "hidden":
                    print(G.sty("   (meter hidden for this part)", "2"))
                m = take_live(rec, t, fake, meter, target)
                print(G.sty("   ■  stop", "1;91") + G.sty(f"   ({m['stop_reason']})", "2"), flush=True)
                G.settle(rec)
                ms = lambda s: round(s * 1000 / rec.rate, 1)  # noqa: E731
                clip = rec.audio(m["go"] - int(G.PRE_S * rec.rate), m["end"])
                n_take += 1
                fname = f"takes/{t['block']}/{t['pid']}_t{n_take:03d}.wav"
                (out / "takes" / t["block"]).mkdir(parents=True, exist_ok=True)
                sf.write(str(out / fname), clip, rec.rate, subtype="PCM_16")
                row = {"take": n_take, "pid": t["pid"], "block": t["block"], "kind": t["kind"], "step": t["step"],
                       "status": "kept", "redo": redo, "run": run, "file": fname, "rate": rec.rate, "pre_s": G.PRE_S,
                       **{k2: t[k2] for k2 in ("anchor", "level", "pos", "vowel", "band") if t.get(k2) is not None},
                       "feedback": t["feedback"], "meter": t["meter"], "target_st": target,
                       "go_ms": ms(m["go"]), "end_ms": ms(m["end"]), "heard": m["heard"],
                       "stop_reason": m["stop_reason"], "base_db": m["base_db"], "locked_live": m["locked_live"],
                       "level_db": R.level_report(rec.audio(m["go"], m["end"])), "synthetic": bool(fake),
                       "time": datetime.now().isoformat(timespec="seconds")}
                last_t = t
                if not m["heard"]:
                    print(G.sty("   no steady voice heard: press r to redo it, or go on", "1;93"))
                else:
                    s = measure_take(frames(clip, rec.rate), G.PRE_S)
                    if s["st"] is None:
                        print(G.sty("   no steady pitch in that take: press r to redo it, or go on", "1;93"))
                    elif t["meter"] != "hidden":
                        msg = f"   heard {s['f0_hz']:.0f} Hz" + (f", F2 {s['f2_hz']:.0f} Hz"
                                                                  if t["kind"] == "vowel" and s["f2_hz"] else "")
                        if t["feedback"] and target is not None:
                            fbm = feedback_measure(frames(clip, rec.rate), G.PRE_S, target)
                            msg += (f"; on target after {fbm['ttt_ms']:.0f} ms" if fbm["reached"] else "; never locked")
                        print(G.sty(msg, "2"))
                    if t["kind"] == "vowel" and s["st"] is not None and sc:
                        mb = min(band_pos, key=lambda bb: abs(band_pos[bb] - st_pos(s["st"], *sc)))
                        row["band_measured"] = mb
                        if mb != t["band"]:
                            print(G.sty(f"   that landed in your {mb.upper()} band, not {t['band'].upper()} "
                                        "(it will count there): press r to redo it, or go on", "1;93"))
                write(row)
                if not redo:
                    done.add(t["pid"])
                    i += 1
                if not auto:
                    time.sleep(0.6)
            if quit_:
                break
            if restart:
                bi = 0
                continue
            bi += 1
    except KeyboardInterrupt:
        print("\ninterrupted: everything so far is saved")
    labels.close()
    rec.wait_s(0.3)
    rec.stop()
    meta["runs"][-1].update({"duration_s": round(rec.n / rec.rate, 1), "wall_s": round(time.monotonic() - t_start, 1)})
    meta_p.write_text(json.dumps(meta, indent=1, default=float))
    left = [t for t in plan if t["pid"] not in done]
    print(f"\n{len(done)}/{len(plan)} prompts done in {name}" + (" (SYNTHETIC)" if fake else ""))
    if left:
        print(f"resume with the same command:  ./run python voice_cursor_test.py --session {name}")
    print(f"score with:  ./run python voice_cursor_test.py --score recordings/{name}")
    print("these recordings are private: they stay in extractor/recordings/ (gitignored); never commit or upload them.")


def loo_level(by: dict[int, list[float]]) -> float | None:
    hits = n = 0
    for k, xs in by.items():
        for j, x in enumerate(xs):
            cent = {kk: np.mean([y for jj, y in enumerate(v) if not (kk == k and jj == j)]) for kk, v in by.items()
                    if len(v) > (1 if kk == k else 0)}
            if len(cent) > 1:
                hits += int(min(cent, key=lambda c: abs(cent[c] - x)) == k)
                n += 1
    return hits / n if n else None


def print_report(r: dict, spec: dict = SPEC) -> None:
    f = lambda x, fmt="{:.2f}": "–" if x is None else fmt.format(x)  # noqa: E731
    ru, p = spec["rules"], r["person"]
    rg, lv, vw, fb = p["range"], p["levels"], p["vowels"], p.get("feedback")
    print(G.sty(f"\nVoice-cursor calibration: {r['session']}" + ("  (SYNTHETIC)" if r["synthetic"] else ""), "1;96")
          + f"   spec {r['spec']}, {len(r['takes'])} takes\n")
    print(f"  range          {f(rg['range_st'], '{:.1f}')} st  ({f(rg['lo_hz'], '{:.0f}')}–{f(rg['hi_hz'], '{:.0f}')} Hz), "
          f"home {f(p['home']['st'], '{:.1f}')} st (SD {f(p['home']['sd_st'])})")
    if ru.get("range"):
        print(G.sty(f"                 glides {f(rg.get('lo_glide_st'), '{:.1f}')}–{f(rg.get('hi_glide_st'), '{:.1f}')} st, "
                    f"held notes {f(rg['lo_anchor_st'], '{:.1f}')}–{f(rg['hi_anchor_st'], '{:.1f}')} st", "2"))
    for fl in rg.get("flags", []):
        print(G.sty(f"                 ! {fl}", "93"))
    print(f"  blind          repeat SD {f(lv['repeat_sd_st'])} st from silence; levels in order: {lv['in_order']}; "
          f"each try nearest its own level: {f(lv['level_loo_acc'], '{:.0%}')}")
    print(G.sty(f"  ROWS blind     {f(r['profile']['rows_blind'], '{}')}", "1") +
          f"   (= range / ({ru['rows_sd_factor']:.0f} × SD), max {ru['max_rows']})")
    if fb:
        print(f"  with meter     reached {fb['reached']}/{fb['n']}; time-to-target median {f(fb['ttt_ms_median'], '{:.0f}')} ms, "
              f"p90 {f(fb['ttt_ms_p90'], '{:.0f}')} ms; final error RMS {f(fb['final_err_rms_st'])} st; "
              f"overshoot median {f(fb['overshoot_median_st'])} st")
        print(G.sty(f"  ROWS feedback  {f(r['profile']['rows_feedback'], '{}')}", "1") +
              "   (= range / (4 × final-error RMS))")
    print(f"  sideways, per pitch band ({vw['band_by']} band; vowel if leave-one-take-out accuracy ≥ "
          f"{ru['vowel_acc_min']:.0%}, else snap to elements):")
    for b, v in vw["bands"].items():
        col = G.sty(v["columns"].upper(), "1;92" if v["columns"] == "vowel" else "1;93")
        print(f"     {b:5s} ~{f(v['f0_hz'], '{:.0f}')} Hz   vowel accuracy {f(v['acc'], '{:.0%}')} "
              f"({v['windows']} windows, {v.get('takes', '?')} takes: {'/'.join(v.get('vowels', [])) or '–'})   -> {col}")
    if vw.get("takes_moved_band"):
        print(G.sty(f"     {vw['takes_moved_band']} vowel takes landed in another band than prompted and count there", "2"))
    if vw.get("takes_no_pitch"):
        print(G.sty(f"     {vw['takes_no_pitch']} vowel takes had no steady pitch", "2"))
    ro = ru["report_only"]
    print(f"  also: F2 wobble {f(vw['f2_within_hold_sd_hz'], '{:.0f}')} Hz vs ¼ ee–oo {f(vw['f2_quarter_ee_oo_hz'], '{:.0f}')} Hz;"
          f" blind lock p90 {f(p['lock']['p90_ms'], '{:.0f}')} ms (want ≤ {ro['lock_ms_p90_max']}), "
          f"never settled {p['lock']['never_settled']}/{p['lock']['n']}")
    uses = r.get("verdict_uses", "blind")
    extra = f"   uses the {uses.upper()} measurement" + (f": {r['verdict_why']}" if r.get("verdict_why") else "")
    if r["profile"].get("absolute_no_look") is not None:
        extra += f"; absolute (no look) too: {'yes' if r['profile']['absolute_no_look'] else 'no'}"
    print(G.sty(f"\n  VERDICT: {r['verdict']}", "1;97") + extra)
    print("  (score.json in the session folder has every take)\n")


def session_spec(d: Path, override: str | None = None) -> dict:
    """The spec a session is scored with: --spec, else the one it was recorded with (session.json), else the current."""
    if override:
        return load_spec(spec_path(override))
    meta_p = d / "session.json"
    ver = json.loads(meta_p.read_text()).get("spec") if meta_p.exists() else None
    return load_spec(spec_path(ver)) if ver and spec_path(ver).exists() else load_spec()


def score(a: argparse.Namespace) -> None:
    d = Path(a.score)
    spec = session_spec(d, a.spec)
    res = score_session(d, spec)
    meta_p = d / "session.json"
    recorded = json.loads(meta_p.read_text()).get("spec") if meta_p.exists() else None
    out = d / ("score.json" if not a.spec or a.spec == recorded else f"score_{spec['version']}.json")
    out.write_text(json.dumps(res, indent=1, default=float))
    print_report(res, spec)
    print(f"  written: {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", help="folder name under recordings/ (same name = resume)")
    ap.add_argument("--source", default="auto", choices=["auto", "pw", "sd", "fake"])
    ap.add_argument("--device", help="PipeWire source name (pw) or PortAudio device (sd); default: the default source")
    ap.add_argument("--rate", type=int, default=48000, choices=[16000, 48000])
    ap.add_argument("--config", help="extractor Config JSON (default: as shipped)")
    ap.add_argument("--allow-silent", action="store_true")
    ap.add_argument("--auto", action="store_true", help="no key presses (for --source fake tests)")
    ap.add_argument("--interactive", action="store_true", help="fake source: still read keys")
    ap.add_argument("--fake-speed", type=float, default=20.0)
    ap.add_argument("--seed", type=int, default=7, help="prompt order (kept in session.json, so a resume keeps it)")
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--score", metavar="DIR", help="compute the per-person profile and verdict of a recorded session")
    ap.add_argument("--spec", help="score with this spec version (e.g. voice_cursor_v2) instead of the recorded one; "
                                   "the result goes to score_<version>.json so the original score.json stays")
    a = ap.parse_args()
    if a.list_devices:
        for s in R.pw_sources():
            print(s)
        return
    if a.score:
        score(a)
        return
    run_session(a)


if __name__ == "__main__":
    main()
