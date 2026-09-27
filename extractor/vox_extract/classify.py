"""Turn one finished sound (SegmentStats) into an event with a schema-exact text line.

Runs once per sound, not per frame. Everything is O(frames) with fixed-size buffers.

Decision order
  1. short (gate time <= discrete_max_ms, time near the peak <= discrete_core_ms) and impulsive (onset flux spike, or the energy peak within the
     first pop_attack_frames) and not tonal (voiced AND clear: a whistle fragment) -> pop / click (peak-frame centroid splits them); a short voiced
     sound that is not impulsive -> very short hum; anything else short is dropped (not emitted).
  2. mostly unvoiced:  hiss (high centroid + high zero-crossing rate) -> hiss line;
     cough / laugh shapes -> hum line with that "sounds like"; any other noise -> hiss line
     "sounds like background noise" (the only trained way to say "noise").
  3. voiced: semitone contour relative to the start -> rise / fall / arch / dip / flat, with
     excursion, duration, tone and loudness buckets, and a "sounds like" guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import lines
from .config import Config
from .segmenter import SegmentStats
from .vocab import CLARITY, DURATION, EXCURSION, LOUDNESS


@dataclass
class Event:
    t_start_ms: int
    t_end_ms: int
    label: str                 # protocol sequence label: rise fall arch dip flat pop click hiss
    sounds_like: str
    text: str                  # the schema-exact sound line
    emit: bool = True          # False = segment was dropped (weak blip); kept for debugging
    truncated: bool = False
    raw: dict = field(default_factory=dict)
    sound: int = 0             # the sound's id in its stream (Extractor; 0 = not numbered); hold messages share it
    held: bool = False         # a `hold start` was sent for this sound (hold.py)

    def to_dict(self) -> dict:
        d = {"t_start_ms": self.t_start_ms, "t_end_ms": self.t_end_ms, "label": self.label,
             "sounds_like": self.sounds_like, "text": self.text, "emit": self.emit, "truncated": self.truncated}
        if self.sound:
            d["sound"] = self.sound
        if self.held:
            d["held"] = True
        d["raw"] = self.raw
        return d


# ---------------------------------------------------------------- small portable helpers

def running_median(x: np.ndarray, w: int) -> np.ndarray:
    """Centred median, window shrinking at the ends (so no padding values are invented)."""
    n = x.size
    h = w // 2
    return np.array([np.median(x[max(0, i - h): min(n, i + h + 1)]) for i in range(n)]) if n else x


def moving_average(x: np.ndarray, w: int) -> np.ndarray:
    n = x.size
    h = w // 2
    return np.array([np.mean(x[max(0, i - h): min(n, i + h + 1)]) for i in range(n)]) if n else x


def hysteresis_peaks(e: np.ndarray, prominence: float, min_gap: int) -> list[int]:
    """Streaming-style peak picker: a peak counts once the track has fallen `prominence` dB below
    it after rising `prominence` dB above the previous valley. O(1) state per step."""
    peaks: list[int] = []
    if e.size == 0:
        return peaks
    lo = e[0]
    hi, hi_i = -np.inf, -1
    rising = True  # looking for a peak
    for i, v in enumerate(e):
        if rising:
            if v > hi:
                hi, hi_i = v, i
            if hi - lo >= prominence and hi - v >= prominence:
                if peaks and hi_i - peaks[-1] < min_gap:
                    if e[hi_i] > e[peaks[-1]]:
                        peaks[-1] = hi_i
                else:
                    peaks.append(hi_i)
                rising = False
                lo = v
        else:
            if v < lo:
                lo = v
            if v - lo >= prominence:
                rising = True
                hi, hi_i = v, i
    # a final peak that never fell back (the sound ended on it) still counts if it rose enough
    if rising and hi_i >= 0 and hi - lo >= prominence and (not peaks or hi_i - peaks[-1] >= min_gap):
        peaks.append(hi_i)
    return peaks


def bucket(v: float, edges: list[float], names: list[str]) -> str:
    for edge, name in zip(edges, names):
        if v < edge:
            return name
    return names[len(edges)]


# ---------------------------------------------------------------- pitch post-processing

def clean_pitch(f0: np.ndarray, voiced: np.ndarray, cfg: Config) -> tuple[np.ndarray, np.ndarray]:
    """Returns (frame indices, semitones re 100 Hz) of the voiced frames that survive median
    filtering, octave correction and the jump limit."""
    idx = np.flatnonzero(voiced)
    if idx.size == 0:
        return idx, np.zeros(0)
    st = 12.0 * np.log2(f0[idx] / 100.0)
    st = running_median(st, cfg.median_frames)
    keep_i: list[int] = []
    keep_s: list[float] = []
    for i, s in zip(idx, st):
        if keep_i and i - keep_i[-1] <= 3:  # within a voiced run: enforce continuity
            prev = keep_s[-1]
            if abs(s - prev) > cfg.jump_limit_st:
                for cand in (s - 12.0, s + 12.0):
                    if abs(cand - prev) <= cfg.jump_limit_st:
                        s = cand
                        break
                else:
                    continue
        keep_i.append(int(i))
        keep_s.append(float(s))
    return np.array(keep_i, dtype=int), np.array(keep_s)


def contour_shape(st: np.ndarray, cfg: Config) -> dict:
    """Shape of a semitone track (absolute semitones). Contour is relative to its start."""
    e = min(cfg.edge_frames, max(1, st.size // 3))
    start = float(np.median(st[:e]))
    end = float(np.median(st[-e:]))
    sm = moving_average(st - start, cfg.smooth_frames)
    net = end - start
    hi, lo = float(np.max(sm)), float(np.min(sm))
    hump = hi - max(0.0, net)
    valley = min(0.0, net) - lo
    biggest = max(abs(net), hump, valley)
    if biggest < cfg.flat_max_range_st:
        shape, exc = "flat", biggest
    elif hump >= cfg.shape_min_st and hump >= cfg.arch_ratio * abs(net) and hump >= valley:
        shape, exc = "arch", hump
    elif valley >= cfg.shape_min_st and valley >= cfg.arch_ratio * abs(net) and valley > hump:
        shape, exc = "dip", valley
    else:
        shape, exc = ("rise" if net > 0 else "fall"), abs(net)
    return {"shape": shape, "excursion_st": exc, "net_st": net, "hump_st": hump, "valley_st": valley,
            "max_st": hi, "min_st": lo, "contour_rel": sm}


def resample_contour(c: np.ndarray, n: int = 64) -> list[float]:
    if c.size == 0:
        return []
    if c.size == 1:
        return [round(float(c[0]), 2)] * n
    xs = np.linspace(0, c.size - 1, n)
    return [round(float(v), 2) for v in np.interp(xs, np.arange(c.size), c)]


# ---------------------------------------------------------------- the classifier

def classify(seg: SegmentStats, cfg: Config, ctx: dict | None = None) -> Event:
    """ctx (optional, from the extractor): {"gap_ms": time since the previous sound ended,
    "prev_talky": whether that sound was talking / laughing or a short voiced burst}."""
    ctx = ctx or {}
    fm = cfg.frame_ms
    n = seg.n
    t0 = int(round(max(0.0, seg.t_start_ms)))
    t1 = int(round(max(0.0, seg.t_start_ms + n * fm)))
    dur = t1 - t0
    e = np.array(seg.e_db)
    f0 = np.array(seg.f0)
    clar = np.array(seg.clarity)
    floor = seg.floor_db

    voiced = (clar >= cfg.voiced_clarity) & (f0 > 0) & (e >= floor + cfg.voiced_min_db_over_floor)
    n_voiced = int(np.count_nonzero(voiced))
    voiced_frac = n_voiced / n
    clar_med = float(np.median(clar))
    level = float(np.percentile(e, 90))
    peak_i = int(np.argmax(e))
    onset_flux = float(max(seg.flux)) if seg.flux else 0.0
    tail = float(np.mean(e[-3:]))
    decay = float(e[peak_i] - tail)
    peak_pos = peak_i / max(1, n - 1)
    iqr = float(np.percentile(e, 75) - np.percentile(e, 25))

    # syllable-like energy modulation (talking / laughing)
    env = moving_average(e, 3)
    peaks = hysteresis_peaks(env, cfg.syllable_prominence_db, cfg.syllable_min_gap_frames)
    dur_s = max(dur, 1) / 1000.0
    rate = len(peaks) / dur_s
    ints = np.diff(peaks) * fm if len(peaks) >= 3 else np.zeros(0)
    interval_cv = float(np.std(ints) / np.mean(ints)) if ints.size >= 2 else 1.0
    run_starts = int(np.count_nonzero(voiced[1:] & ~voiced[:-1])) + int(bool(voiced[0])) if n else 0
    breaks_hz = run_starts / dur_s
    # voiced runs of at least 2 frames (single-frame flickers at a noisy edge do not count)
    runs = 0
    k = 0
    while k < n:
        if voiced[k]:
            j = k
            while j < n and voiced[j]:
                j += 1
            runs += int(j - k >= 2)
            k = j
        else:
            k += 1

    # pitch: only frames near the sound's own level (weak tails are dominated by the background)
    strong = e >= level - cfg.contour_db
    strong_voiced_frac = float(np.count_nonzero(voiced & strong)) / max(1, int(np.count_nonzero(strong)))
    vi, st = clean_pitch(f0, voiced & strong, cfg)
    shape = contour_shape(st, cfg) if st.size >= 3 else None
    if st.size >= 3:
        d2 = np.abs(np.diff(st, 2))
        rough = float(np.median(d2))
        t = np.arange(st.size)
        resid = st - np.polyval(np.polyfit(t, st, 1), t) if st.size >= 4 else st - st.mean()
        resid_std = float(np.std(resid))
        jumps = int(np.count_nonzero(np.abs(np.diff(moving_average(st, 3))) > 1.5))
        f0_med = float(100.0 * 2 ** (np.median(st) / 12.0))
    else:
        rough, resid_std, jumps, f0_med = 0.0, 0.0, 0, 0.0
    jumps_hz = jumps / dur_s

    raw = {
        "dur_ms": dur, "frames": n, "floor_db": round(floor, 2), "level_db": round(level, 2),
        "snr_db": round(level - floor, 2), "voiced_frac": round(voiced_frac, 3), "clarity_med": round(clar_med, 3),
        "f0_med_hz": round(f0_med, 1), "onset_flux_db": round(onset_flux, 2), "decay_db": round(decay, 2),
        "peak_pos": round(peak_pos, 3), "energy_iqr_db": round(iqr, 2), "truncated": seg.truncated,
        "gate_close_over_floor_db": round(seg.close_over_floor_db, 2),
        "peak_centroid_hz": round(seg.peak_centroid, 1), "centroid_hz": round(seg.wmean(seg.centroid_sum), 1),
        "flatness": round(seg.wmean(seg.flatness_sum), 4), "zcr": round(seg.wmean(seg.zcr_sum), 4),
        "lf_ratio": round(seg.wmean(seg.lf_sum), 4), "hf_ratio": round(seg.wmean(seg.hf_sum), 4),
        "flux_mean_db": round(seg.wmean(seg.flux_sum), 3),
        "centroid_spread_oct": round(max(0.0, seg.cent_sq / seg.cent_n - (seg.cent_sum / seg.cent_n) ** 2) ** 0.5, 3) if seg.cent_n else 0.0,
        "syllable_peaks": len(peaks), "syllable_rate_hz": round(rate, 2), "interval_cv": round(interval_cv, 3),
        "voiced_runs": runs, "strong_voiced_frac": round(strong_voiced_frac, 3),
        "voicing_breaks_hz": round(breaks_hz, 2), "pitch_rough_st": round(rough, 3),
        "pitch_resid_std_st": round(resid_std, 3), "pitch_jumps_hz": round(jumps_hz, 2),
    }
    if shape:
        raw.update({k: round(v, 2) for k, v in shape.items() if k not in ("shape", "contour_rel")})
        raw["contour64"] = resample_contour(shape["contour_rel"])
        raw["pitch16"] = resample_contour(shape["contour_rel"], 16)

    loud = loudness(level, floor, cfg)
    dur_b = bucket(dur, [cfg.dur_short_ms, cfg.dur_medium_ms, cfg.dur_long_ms], DURATION)
    centroid = seg.wmean(seg.centroid_sum)
    zcr = seg.wmean(seg.zcr_sum)
    lf = seg.wmean(seg.lf_sum)

    def ev(label: str, like: str, text: str, emit: bool = True, why: str = "") -> Event:
        raw["why"] = why
        return Event(t0, t1, label, like, text, emit, seg.truncated, raw)

    # 1. short -> pop / click: an onset spike with the energy peak early (a resonant lip pop can
    #    be briefly "voiced", so voicing alone does not rule it out). A short, voiced sound without
    #    that shape is a very short hum; a short sound with neither is dropped.
    impulsive = onset_flux >= cfg.pop_onset_flux_db or peak_i <= cfg.pop_attack_frames
    core_ms = int(np.count_nonzero(e >= e[peak_i] - cfg.discrete_core_db)) * fm
    # a short, strongly voiced and clear sound is a fragment of a tone (a whistle's top that alone
    # crossed the gate), not a mouth transient: real pops / clicks are at most ~40 % voiced, clarity < 0.65
    tonal = voiced_frac > cfg.discrete_tonal_voiced_frac and clar_med > cfg.discrete_tonal_clarity
    raw["impulsive"] = bool(impulsive)
    raw["core_ms"] = core_ms
    raw["tonal"] = bool(tonal)
    if dur <= cfg.discrete_max_ms and core_ms <= cfg.discrete_core_ms:
        if impulsive and not tonal and (n_voiced < cfg.discrete_max_voiced or peak_pos <= cfg.discrete_peak_pos):
            kind = "click" if seg.peak_centroid >= cfg.click_centroid_hz else "pop"
            return ev(kind, "mouth sound", lines.discrete_line(kind, loud), why=f"short+flux -> {kind}")
        if n_voiced < cfg.discrete_max_voiced:
            return ev("unknown", "background noise", "", emit=False, why="short blip without onset")

    unvoiced = voiced_frac < cfg.hiss_max_voiced_frac or shape is None
    coughy = (onset_flux >= cfg.cough_onset_flux_db and peak_pos <= cfg.cough_peak_pos
              and decay >= cfg.cough_decay_db and dur <= cfg.cough_max_ms
              and voiced_frac <= cfg.cough_max_voiced_frac)
    laughy = (len(peaks) >= cfg.laugh_min_peaks and cfg.laugh_rate_lo_hz <= rate <= cfg.laugh_rate_hi_hz
              and interval_cv <= cfg.laugh_max_interval_cv and clar_med <= cfg.laugh_max_clarity)

    def hum_from(like: str, why: str) -> Event:
        if shape is None:
            contour, exc_b = "flat", EXCURSION[0]
        else:
            contour = shape["shape"]
            exc_b = bucket(shape["excursion_st"], [cfg.exc_medium_st, cfg.exc_large_st], EXCURSION)
        return ev(contour, like, lines.hum_line(contour, exc_b, dur_b, tone(clar_med, voiced_frac, cfg), loud, like), why=why)

    # 2. mostly unvoiced
    if unvoiced:
        if centroid >= cfg.hiss_centroid_hz and zcr >= cfg.hiss_zcr and dur >= cfg.hiss_min_ms and not laughy:
            steady = dur >= cfg.hiss_bg_steady_ms and iqr < cfg.hiss_steady_db
            like = "background noise" if (lf > cfg.hiss_bg_lf_ratio or steady) else "mouth sound"
            return ev("hiss", like, lines.hiss_line(dur_b, loud, like), why=f"hiss ({'lf' if lf > cfg.hiss_bg_lf_ratio else 'steady' if steady else 'mouth'})")
        if coughy:
            return hum_from("coughing", "unvoiced cough shape")
        if laughy:
            return hum_from("laughing", "unvoiced regular bursts")
        return ev("hiss", "background noise", lines.hiss_line(dur_b, loud, "background noise"), why="unvoiced noise")

    # 3. voiced
    raw["gap_ms"] = ctx.get("gap_ms")
    raw["prev_talky"] = bool(ctx.get("prev_talky", False))
    like, why = sounds_like_voiced(raw, coughy, laughy, dur, cfg)
    return hum_from(like, why)


def speech_cues(raw: dict, cfg: Config) -> list[str]:
    """Three independent kinds of evidence that a voiced sound is speech rather than a hum.
    Each is weak alone (a hum can swell in loudness; a pitch glide moves the centroid a little)."""
    cues = []
    # voicing gaps count only in the sound's strong part: every sound's weak attack and tail are unvoiced
    if raw["strong_voiced_frac"] < cfg.talk_max_voiced_frac or raw["voiced_runs"] >= cfg.talk_min_runs:
        cues.append("broken voicing")
    if raw["centroid_spread_oct"] >= cfg.talk_centroid_spread_oct:
        cues.append("consonant / formant changes")
    # needs at least two loudness peaks: a single swell (attack, sustain, decay) is what a hum does
    if raw["syllable_peaks"] >= cfg.talk_min_peaks and (
            cfg.talk_min_rate_hz <= raw["syllable_rate_hz"] <= cfg.talk_max_rate_hz or raw["energy_iqr_db"] >= cfg.talk_min_iqr_db):
        cues.append("syllable-like loudness")
    return cues


def sounds_like_voiced(raw: dict, coughy: bool, laughy: bool, dur: int, cfg: Config) -> tuple[str, str]:
    if dur > cfg.max_gesture_ms or raw.get("truncated"):
        tonal = raw["clarity_med"] < cfg.music_max_clarity and raw["flatness"] < cfg.music_max_flatness
        return ("background music", "too long, tonal") if tonal else ("background noise", "too long")
    clear = raw["clarity_med"] >= cfg.tone_clear and raw["voiced_frac"] >= cfg.tone_min_voiced_frac
    if raw["f0_med_hz"] >= cfg.whistle_min_hz and clear:
        return "whistle", "clear tone with f0 >= whistle_min_hz"
    if dur >= cfg.machine_min_ms and raw["pitch_resid_std_st"] < cfg.machine_max_pitch_std_st:
        return "background noise", "machine-steady pitch"
    if coughy:
        return "coughing", "onset + early peak + decay"
    if laughy:
        return "laughing", "regular bursts"
    cues = speech_cues(raw, cfg)
    raw["speech_cues"] = cues
    if len(cues) >= cfg.talk_min_cues or raw["centroid_spread_oct"] >= cfg.talk_strong_centroid_spread_oct:
        return "talking", "speech cues: " + ", ".join(cues)
    gap = raw.get("gap_ms")
    if gap is not None and gap <= cfg.train_gap_ms and raw.get("prev_talky") and (cues or dur <= cfg.train_max_ms):
        return "talking", "follows talking closely"
    if (dur >= cfg.music_min_ms and raw["clarity_med"] < cfg.music_max_clarity and raw["flatness"] < cfg.music_max_flatness
            and raw["pitch_jumps_hz"] >= cfg.music_min_jumps_hz):
        return "background music", "long, tonal, stepping pitch, no single clear period"
    return "hum", "default voiced"


def tone(clar_med: float, voiced_frac: float, cfg: Config) -> str:
    if clar_med >= cfg.tone_clear and voiced_frac >= cfg.tone_min_voiced_frac:
        return CLARITY[2]
    if clar_med >= cfg.tone_breathy:
        return CLARITY[1]
    return CLARITY[0]


def loudness(level_db: float, floor_db: float, cfg: Config) -> str:
    if cfg.loud_calib_db is not None:
        if level_db < cfg.loud_calib_db - cfg.loud_calib_span_db:
            return LOUDNESS[0]
        if level_db >= cfg.loud_calib_db + cfg.loud_calib_span_db:
            return LOUDNESS[2]
        return LOUDNESS[1]
    rel = level_db - max(floor_db, cfg.loud_ref_min_db)
    return bucket(rel, [cfg.loud_quiet_over_floor_db, cfg.loud_loud_over_floor_db], LOUDNESS)
