"""Shared helpers for the REAL-audio evaluation (eval_real/).

Everything here reads audio from /home/khoa/VOX/datasets (never copied into the repo) and runs the
extractor exactly as shipped (vox_extract.extractor.extract_array, 1600-sample streaming chunks).

Conventions used by every dataset script
  * split_of(dataset, speaker): a deterministic 30 % "tune" / 70 % "test" split BY SPEAKER
    (sha1 of "<dataset>:<speaker>"), so no speaker is in both halves.
  * SNR (noise mixing): active-span RMS of the (as-recorded) sound vs the RMS of the added MUSAN
    noise excerpt, the same definition synth.py uses. The active span = 10 ms frames within 20 dB
    of the clip's loudest frame. The recordings already carry their own room / phone noise, so
    "clean" here means "as recorded", not noiseless.
  * lead-in: the extractor needs ~0.3-0.5 s to learn a noise floor (warm-up 250 ms, 0.4 s floor
    blocks). A deployed extractor runs continuously, so each clip gets LEAD_S of lead-in and TAIL_S
    of tail made of the clip's own quietest 200 ms, looped with 10 ms crossfades. Added noise then
    covers the whole padded clip.
  * line checks reuse tests/synthetic_eval.off_distribution (exact membership in generate.py's
    sampled line support via tests/finetune_ref.py, reasons named by the same hand rules), i.e. the
    same check that produced the "193 of 1181 lines" figure in the README.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = Path("/home/khoa/VOX/datasets")
RESULTS = ROOT / "results"
CACHE = DATA / "_eval_cache"          # derived lists / pitch caches: kept with the data, out of the repo
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
# VOX_CODE=frozen runs the byte-identical snapshot of vox_extract taken before any fix (md5s in
# _eval_cache/frozen_code.md5), so frozen numbers can be regenerated after the code has changed.
CODE = os.environ.get("VOX_CODE", "current")
if CODE == "frozen":
    sys.path.insert(0, str(CACHE / "frozen_src"))

from vox_extract import Config  # noqa: E402
from vox_extract.extractor import Extractor, extract_array, load_wav  # noqa: E402
from vox_extract.lines import LineError, label_consistent, parse_line  # noqa: E402
from vox_extract.policy import action_for, group, not_deliberate  # noqa: E402
from vox_extract.resample import to_16k  # noqa: E402

WORKERS = int(os.environ.get("VOX_EVAL_WORKERS", "8"))   # the box is shared: keep it modest
SNRS = ["clean", 20, 10, 5]
LEAD_S = 1.0
TAIL_S = 0.6
TUNE_PCT = 30
DEAD_DB = -90.0         # 10 ms frames below this are digital silence (app start-up zeros, 8-bit mid-code)
LABELS = ["rise", "fall", "arch", "dip", "flat", "pop", "click", "hiss"]


# ------------------------------------------------------------------------------ splits

def split_of(dataset: str, speaker: str) -> str:
    h = int(hashlib.sha1(f"{dataset}:{speaker}".encode()).hexdigest()[:8], 16)
    return "tune" if h % 100 < TUNE_PCT else "test"


# ------------------------------------------------------------------------------ audio

def load_16k(path: str | Path) -> np.ndarray:
    x, sr = load_wav(path)
    x = np.asarray(x, dtype=np.float32)
    if sr != 16000:
        x = to_16k(x, sr)
    return x


def frame_db(x: np.ndarray, hop: int = 160) -> np.ndarray:
    n = len(x) // hop
    if n == 0:
        return np.array([-120.0])
    f = x[: n * hop].astype(np.float64).reshape(n, hop)
    return 10 * np.log10(np.mean(f * f, axis=1) + 1e-12)


def active_rms(x: np.ndarray, within_db: float = 20.0) -> float:
    e = frame_db(x)
    act = e >= e.max() - within_db
    n = len(e) * 160
    f = x[:n].astype(np.float64).reshape(-1, 160)[act]
    return float(np.sqrt(np.mean(f * f) + 1e-20))


def own_background(x: np.ndarray, n_out: int, win_ms: int = 200) -> np.ndarray:
    """n_out samples of the clip's own quietest win_ms, looped with 10 ms crossfades.
    Windows touching digital silence (< -90 dBFS, e.g. a phone app's start-up zeros) are skipped."""
    w = int(16 * win_ms)
    if len(x) <= w or n_out <= 0:
        return np.zeros(max(0, n_out), dtype=np.float32)
    e = frame_db(x)
    k = w // 160
    s = np.convolve(10 ** (e / 10), np.ones(k), "valid")
    dead = np.convolve((e < DEAD_DB).astype(float), np.ones(k), "valid") > 0
    if not dead.all():
        s = np.where(dead, np.inf, s)
    i0 = int(np.argmin(s)) * 160
    seg = x[i0:i0 + w].astype(np.float64)
    xf = 160
    ramp = np.linspace(0, 1, xf)
    out = np.zeros(n_out + w)
    pos = 0
    while pos < n_out:
        piece = seg.copy()
        if pos > 0:
            piece[:xf] *= ramp
            out[pos:pos + xf] *= 1 - ramp  # crossfade into the previous copy's tail
            out[pos:pos + w] += piece
        else:
            out[:w] = piece
        pos += w - xf
    return out[:n_out].astype(np.float32)


def trim_dead(x: np.ndarray) -> tuple[np.ndarray, int]:
    """Drop leading / trailing digital silence (10 ms frames below DEAD_DB). Returns (x, samples cut at the start)."""
    e = frame_db(x)
    live = np.flatnonzero(e >= DEAD_DB)
    if live.size == 0:
        return x, 0
    a, b = int(live[0]) * 160, min(len(x), (int(live[-1]) + 1) * 160)
    return x[a:b], a


def pad_clip(x: np.ndarray, lead_s: float = LEAD_S, tail_s: float = TAIL_S) -> tuple[np.ndarray, int, int]:
    """Returns (padded, offset_samples, trimmed_samples). Leading / trailing digital silence is cut
    first (a live stream has none); lead-in / tail are the clip's own quietest 200 ms, looped.
    An event at t_ms in the padded signal is at t_ms - 1000*offset/16000 + 1000*trimmed/16000 in the file."""
    x, cut = trim_dead(x)
    nl, nt = int(lead_s * 16000), int(tail_s * 16000)
    bg = own_background(x, nl + nt)
    y = np.concatenate([bg[:nl], x, bg[nl:]]).astype(np.float32)
    return y, nl, cut


@lru_cache(maxsize=4)
def musan_noise_files(split: str) -> list[str]:
    """MUSAN noise/ files of one split (split by file: the noise set has no speakers)."""
    root = DATA / "musan" / "musan" / "noise"
    fs = sorted(str(p) for p in root.rglob("*.wav"))
    return [f for f in fs if split_of("musan-noise", Path(f).stem) == split]


def noise_excerpt(rng: np.random.Generator, n: int, split: str) -> tuple[np.ndarray, str, int]:
    """n samples from a random MUSAN noise file of `split` (looped if short). Skips near-silent ones."""
    files = musan_noise_files(split)
    for _ in range(20):
        f = files[int(rng.integers(len(files)))]
        z = load_16k(f)
        if len(z) < 1600:
            continue
        off = int(rng.integers(max(1, len(z) - n))) if len(z) > n else 0
        seg = z[off:off + n]
        if len(seg) < n:
            seg = np.resize(seg, n)
        if np.sqrt(np.mean(seg.astype(np.float64) ** 2)) > 1e-4:
            return seg.astype(np.float32), f, off
    raise RuntimeError("no usable noise excerpt")


def mix_at(x: np.ndarray, snr_db, rng: np.random.Generator, split: str, ref_rms: float | None = None) -> tuple[np.ndarray, dict]:
    if snr_db == "clean":
        return x, {}
    z, f, off = noise_excerpt(rng, len(x), split)
    ref = ref_rms if ref_rms is not None else active_rms(x)
    zr = float(np.sqrt(np.mean(z.astype(np.float64) ** 2)))
    g = ref / (zr * 10 ** (snr_db / 20))
    y = x + g * z
    peak = float(np.max(np.abs(y)))
    if peak > 0.99:          # keep it in range like a real ADC would (scale, don't clip)
        y = y * (0.99 / peak)
    return y.astype(np.float32), {"noise": str(Path(f).relative_to(DATA)), "noise_off": off}


# ------------------------------------------------------------------------------ running + line checks

@lru_cache(maxsize=1)
def _synth_eval():
    import synthetic_eval  # tests/synthetic_eval.py: SEEN + off_distribution (the README's check)
    return synthetic_eval


def run_extractor(x: np.ndarray, cfg: Config, sr: int = 16000) -> list[dict]:
    return [e.to_dict() for e in extract_array(x, sr, cfg)]


def check_lines(events: list[dict]) -> tuple[list[str], list[list[str]]]:
    """(strict parse / label errors, [[reason, text], ...] for lines outside generate.py's support)."""
    se = _synth_eval()
    errs, ood = [], []
    for e in events:
        try:
            p = parse_line(e["text"])
            if not label_consistent(e["label"], p):
                errs.append(f"label {e['label']} vs line {e['text']}")
            o = se.off_distribution(p, e["label"], e["text"])
            if o:
                ood.append([o, e["text"]])
        except LineError as err:
            errs.append(str(err))
    return errs, ood


def fireable(e: dict) -> str:
    """The action this one event would trigger ALONE under the default profile ('none' if gated)."""
    return action_for([(e["label"], e["text"])])


def slim(e: dict) -> dict:
    r = e["raw"]
    return {"t0": e["t_start_ms"], "t1": e["t_end_ms"], "label": e["label"], "like": e["sounds_like"],
            "text": e["text"], "why": r.get("why", ""),
            "gate": not_deliberate(e["label"], e["text"]) if e["text"] else "unmatched",
            "raw": {k: r.get(k) for k in ("dur_ms", "snr_db", "voiced_frac", "clarity_med", "f0_med_hz", "onset_flux_db",
                                          "peak_centroid_hz", "centroid_hz", "zcr", "lf_ratio", "core_ms", "impulsive",
                                          "excursion_st", "net_st", "hump_st", "valley_st", "centroid_spread_oct",
                                          "syllable_peaks", "strong_voiced_frac", "voiced_runs", "pitch_resid_std_st",
                                          "flatness", "decay_db", "peak_pos", "speech_cues", "max_st", "min_st",
                                          "pitch_rough_st", "pitch_jumps_hz", "energy_iqr_db", "level_db", "floor_db",
                                          "hf_ratio", "flux_mean_db", "syllable_rate_hz", "interval_cv", "contour64", "tonal",
                                          "fp", "pitch16", "fp_version")}}


@lru_cache(maxsize=2)
def _mel_fb(n_mels: int, nfft: int = 512, sr: int = 16000, lo: float = 60.0, hi: float = 7600.0) -> np.ndarray:
    mel = lambda f: 2595 * np.log10(1 + f / 700.0)  # noqa: E731
    imel = lambda m: 700 * (10 ** (m / 2595.0) - 1)  # noqa: E731
    pts = imel(np.linspace(mel(lo), mel(hi), n_mels + 2))
    f = np.fft.rfftfreq(nfft, 1 / sr)
    fb = np.zeros((n_mels, f.size))
    for i in range(n_mels):
        l, c, r = pts[i], pts[i + 1], pts[i + 2]
        fb[i] = np.clip(np.minimum((f - l) / (c - l), (r - f) / (r - c)), 0, None)
    return fb


def brightness(y: np.ndarray, t0_ms: float, t1_ms: float, f0: float) -> dict:
    """Offline per-event features (NOT computed by the extractor; for what-if rules and the v6 feature
    export). Frames: 512-sample Hann, hop 160, over the event span (centre 512 samples if shorter).
      e1k      energy share 1-6 kHz of the 60 Hz-8 kHz band (energy-weighted over frames)
      e35f0    energy share above 3.5 x f0 (f0 = the event's median pitch), same band
      logmel8  mean log-mel energy (dB) in 8 mel bands 60-7600 Hz, minus the event's mean over bands
      mfcc13   mean MFCC 0-12 (26 mel bands, DCT-II ortho, log power)
      hnr_db   rough harmonic-to-noise ratio from the mean spectrum at f0 harmonics vs between them"""
    a, b = max(0, int(t0_ms * 16)), min(len(y), int(t1_ms * 16))
    if b - a < 512:
        c = (a + b) // 2
        a, b = max(0, c - 256), min(len(y), c + 256)
    seg = y[a:b].astype(np.float64)
    if seg.size < 512:
        return {}
    w = np.hanning(512)
    fr = np.lib.stride_tricks.sliding_window_view(seg, 512)[::160] * w
    P = np.abs(np.fft.rfft(fr, axis=1)) ** 2 + 1e-12
    spec = P.sum(axis=0)
    f = np.fft.rfftfreq(512, 1 / 16000)
    band = (f >= 60) & (f <= 8000)
    tot = spec[band].sum() + 1e-20
    out = {"e1k": round(float(spec[(f >= 1000) & (f <= 6000)].sum() / tot), 4)}
    if f0 and f0 > 0:
        out["e35f0"] = round(float(spec[band & (f > 3.5 * f0)].sum() / tot), 4)
        k = np.arange(1, int(min(16, 7600 // f0)) + 1)
        if k.size >= 1:
            harm = np.interp(k * f0, f, spec)
            mid = np.interp((k + 0.5) * f0, f, spec)
            out["hnr_db"] = round(float(10 * np.log10(harm.sum() / (mid.sum() + 1e-20))), 2)
    lm = 10 * np.log10(P @ _mel_fb(8).T + 1e-12).mean(axis=0)
    out["logmel8"] = [round(float(v), 2) for v in (lm - lm.mean())]
    L26 = np.log(P @ _mel_fb(26).T + 1e-12)
    n = 26
    dct = np.sqrt(2 / n) * np.cos(np.pi / n * (np.arange(n)[None, :] + 0.5) * np.arange(13)[:, None])
    dct[0] /= np.sqrt(2)
    out["mfcc13"] = [round(float(v), 3) for v in (L26 @ dct.T).mean(axis=0)]
    return out


def analyse(events: list[dict], y: np.ndarray | None = None, shift_ms: float = 0.0) -> dict:
    """Everything the scorers need from one run: slim events, group actions, fireable events, line checks.
    With y (the exact 16 kHz signal the extractor saw) the offline brightness features are added per event;
    shift_ms = how much the caller already subtracted from the event times."""
    errs, ood = check_lines(events)
    groups = group(events)
    acts = [action_for([(e["label"], e["text"]) for e in g]) for g in groups]
    sl = [slim(e) for e in events]
    if y is not None:
        for e, s_ in zip(events, sl):
            s_["raw"].update(brightness(y, e["t_start_ms"] + shift_ms, e["t_end_ms"] + shift_ms, e["raw"].get("f0_med_hz") or 0.0))
    return {"events": sl, "actions": acts, "fire": [fireable(e) for e in events],
            "line_errors": errs, "ood": ood}


def pmap(fn, jobs: list, workers: int = WORKERS, chunksize: int = 4) -> list:
    if workers <= 1:
        return [fn(j) for j in jobs]
    with ProcessPoolExecutor(workers) as ex:
        return list(ex.map(fn, jobs, chunksize=chunksize))


def cfg_from(name_or_path: str | None) -> Config:
    if not name_or_path or name_or_path == "frozen":
        return Config()
    return Config.load(name_or_path)


def seed_of(*parts) -> int:
    return int(hashlib.sha1(":".join(map(str, parts)).encode()).hexdigest()[:8], 16)


# ------------------------------------------------------------------------------ reporting helpers

def pct(v) -> str:
    return "-" if v is None else f"{100 * v:.1f}"


def rate(num: int, den: int):
    return (num / den) if den else None


def md_table(header: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(map(str, header)) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(map(str, r)) + " |" for r in rows]
    return "\n".join(out)


def confusion_md(conf: dict[str, Counter], cols: list[str]) -> str:
    rows = [[t] + [conf[t].get(c, 0) for c in cols] + [sum(conf[t].values())] for t in conf]
    return md_table(["truth \\ predicted"] + cols + ["n"], rows)


def write_jsonl(path: Path, recs: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in recs:
            f.write(json.dumps(r, default=str) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def num(v, fmt: str = ".2f") -> str:
    return "-" if v is None else format(v, fmt)
