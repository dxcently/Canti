"""Regressions from the user's live recordings (recordings/live-20260926-*, 48 kHz USB mic).

105053 @989 ms: the top of a rising whistle came out as a 60 ms "pop" (voiced_frac 1.0, clarity 0.99,
f0 1795 Hz). Two causes, two fixes:
  (a) classify: a short sound that is strongly voiced AND clear is a tone fragment, never pop / click;
  (b) segmenter: a loud sound during warm-up had raised the start-up noise floor ~20 dB, so the
      whistle only crossed the gate at its top. During start-up the floor now uses a low quantile of
      50 ms sub-blocks when the block mean is more than floor_startup_trigger_db above it, and the
      floor rises at most floor_rise_open_db_s while a sound is open.

The user-confirmed label cases (whistle arches, soft clicks, ...) are data-driven: tests/test_live_cases.py
with tests/live_regressions.json.
"""

import numpy as np
import pytest

from vox_extract import Config
from vox_extract.extractor import Extractor

SR_LIST = [16000, 48000]


def db(x):
    return 10 ** (x / 20)


def run(x, sr, cfg=None):
    ex = Extractor(cfg or Config(), input_rate=sr)
    out = []
    blk = sr // 20
    for i in range(0, x.size, blk):
        out += ex.push(x[i:i + blk])
    return [e.to_dict() for e in out + ex.flush()]


def whistle(sr, t0, t1, f_lo, f_hi, a_lo_db, a_hi_db, n):
    """Rising sine glide over [t0, t1) s, amplitude ramping (in dB) from a_lo_db to a_hi_db."""
    y = np.zeros(n)
    i0, i1 = int(t0 * sr), min(n, int(t1 * sr))
    m = i1 - i0
    u = np.linspace(0, 1, m, endpoint=False)
    f = f_lo * (f_hi / f_lo) ** u
    ph = 2 * np.pi * np.cumsum(f) / sr
    amp = db(a_lo_db + (a_hi_db - a_lo_db) * u)
    fade = np.minimum(1, np.minimum(np.arange(m), m - np.arange(m)) / (0.01 * sr))
    y[i0:i1] = amp * fade * np.sin(ph)
    return y


def room(sr, n, rng, level_db=-62.0):
    return rng.standard_normal(n) * db(level_db)


@pytest.mark.parametrize("sr", SR_LIST)
def test_rising_whistle_from_t0_is_never_pop(sr):
    """The whistle is already sounding when streaming starts (the floor start-up sees it)."""
    rng = np.random.default_rng(1)
    n = int(3.0 * sr)
    x = room(sr, n, rng) + whistle(sr, 0.0, 1.2, 900, 1800, -40, -12, n)
    evs = run(x.astype(np.float32), sr)
    assert not [e for e in evs if e["label"] in ("pop", "click")], evs


@pytest.mark.parametrize("sr", SR_LIST)
def test_loud_warmup_transient_then_quiet_whistle(sr):
    """105053: a loud noise burst during warm-up, then a quieter whistle that swells and fades. The
    frozen code let the burst become the floor and found nothing here (in the real recording only
    the whistle's top crossed, as a "pop"). Now the whistle is found, whole, and nothing is pop / click."""
    rng = np.random.default_rng(2)
    n = int(3.0 * sr)
    x = room(sr, n, rng, -50.0)
    i0, i1 = int(0.15 * sr), int(0.55 * sr)
    x[i0:i1] += rng.standard_normal(i1 - i0) * db(-6) * np.hanning(i1 - i0)
    j0, j1 = int(0.8 * sr), int(1.4 * sr)
    m = j1 - j0
    t = np.arange(m) / sr
    ph = 2 * np.pi * np.cumsum(1000 * 1.8 ** (t / t[-1])) / sr
    env_db = -33 + 24 * np.exp(-0.5 * ((t - 0.39) / 0.08) ** 2)
    x[j0:j1] += db(env_db) * np.sin(ph) * np.minimum(1, np.minimum(np.arange(m), m - np.arange(m)) / (0.01 * sr))
    evs = run(x.astype(np.float32), sr)
    assert not [e for e in evs if e["label"] in ("pop", "click")], evs
    w = [e for e in evs if e["t_start_ms"] <= 1200 <= e["t_end_ms"]]
    assert w and w[0]["label"] in ("rise", "flat", "arch", "dip", "fall"), evs
    assert w[0]["t_end_ms"] - w[0]["t_start_ms"] >= 300, w  # the whole whistle, not just its top


def test_recording_105053_no_tonal_pop():
    """The real recording (skipped when recordings/ is not present)."""
    import glob
    import json
    from pathlib import Path
    d = glob.glob(str(Path(__file__).resolve().parents[1] / "recordings" / "live-20260926-105053"))
    if not d:
        pytest.skip("live recording not present")
    from vox_extract.extractor import load_wav
    x, sr = load_wav(Path(d[0]) / "session.wav")
    cfg = Config.from_dict(json.loads((Path(d[0]) / "session.json").read_text())["config"])
    evs = run(x, sr, cfg)
    bad = [e for e in evs if e["label"] in ("pop", "click") and e["raw"]["voiced_frac"] > 0.5]
    assert not bad, bad
    assert not [e for e in evs if e["label"] in ("pop", "click") and 900 <= e["t_start_ms"] <= 1100], evs


@pytest.mark.parametrize("sr", SR_LIST)
def test_short_tone_fragment_is_not_click(sr):
    """(a) alone: a 60 ms clear 1.8 kHz tone with a hard onset after a quiet second (classic
    pop / click timing) is a tone fragment."""
    rng = np.random.default_rng(3)
    n = int(2.0 * sr)
    x = room(sr, n, rng)
    i0, m = int(1.0 * sr), int(0.06 * sr)
    t = np.arange(m) / sr
    x[i0:i0 + m] += db(-15) * np.sin(2 * np.pi * 1800 * t) * np.exp(-t / 0.04)
    evs = run(x.astype(np.float32), sr)
    assert not [e for e in evs if e["label"] in ("pop", "click")], evs


def test_floor_startup_ignores_warmup_sound():
    """(b) directly: with a loud sound over most of the first block, the start-up floor stays near
    the room level instead of the sound's level."""
    from vox_extract.frontend import FrameProcessor
    from vox_extract.segmenter import Segmenter
    cfg = Config()
    rng = np.random.default_rng(4)
    n = int(1.0 * 16000)
    x = room(16000, n, rng, -60.0)
    # a burst over half of the first block (the start-up quantile tolerates sound in up to ~3/4 of it)
    x[int(0.15 * 16000):int(0.35 * 16000)] += rng.standard_normal(int(0.20 * 16000)) * db(-15)
    fp, sg = FrameProcessor(cfg), Segmenter(cfg)
    floors = []
    for f in fp.push_iter(x):
        sg.push(f)
        fp.floor_db = sg.floor_db
        floors.append(sg.floor_db)
    # room hop energy is about -60 dB; the burst is ~45 dB louder
    assert max(floors[45:]) < -50, max(floors[45:])


def test_floor_rise_is_capped_while_open():
    from vox_extract.frontend import FrameProcessor
    from vox_extract.segmenter import Segmenter
    cfg = Config()
    rng = np.random.default_rng(5)
    n = int(2.0 * 16000)
    x = room(16000, n, rng, -60.0)
    x[int(0.6 * 16000):] += rng.standard_normal(n - int(0.6 * 16000)) * db(-20)  # a sound that stays on
    fp, sg = FrameProcessor(cfg), Segmenter(cfg)
    rows = []
    for f in fp.push_iter(x):
        was_open = sg.seg is not None
        before = sg.floor_db
        sg.push(f)
        fp.floor_db = sg.floor_db
        if was_open and sg.seg is not None:
            rows.append(sg.floor_db - before)
    assert rows and max(rows) <= cfg.floor_rise_open_db_s * cfg.frame_ms / 1000 + 1e-9

