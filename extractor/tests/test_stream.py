"""Streaming: the result must not depend on how the audio is chunked. Plus resampler and config."""

import json

import numpy as np
import pytest

import synth
from vox_extract import Config
from vox_extract.extractor import Extractor
from vox_extract.resample import Decimator3, decim_taps


def run(x, rate, chunks, cfg=None):
    ex = Extractor(cfg or Config(), input_rate=rate, keep_frames=True)
    evs, i, k = [], 0, 0
    while i < x.size:
        n = chunks[k % len(chunks)]
        evs += ex.push(x[i:i + n])
        i += n
        k += 1
    evs += ex.flush()
    return ex, [e.to_dict() for e in evs]


@pytest.mark.parametrize("cls", ["arch", "click_pop", "hiss", "talk"])
def test_chunking_16k_is_exact(cls):
    clip = synth.make_clip(cls, np.random.default_rng(11), 16000, 20.0, "pink")
    x = clip.audio
    ref_ex, ref = run(x, 16000, [x.size])
    for chunks in ([1600], [160], [37, 1, 503], [4097]):
        ex, got = run(x, 16000, chunks)
        assert got == ref, chunks
        assert [f.as_list() for f in ex.frames] == [f.as_list() for f in ref_ex.frames]


@pytest.mark.parametrize("cls", ["rise", "pop"])
def test_chunking_48k(cls):
    clip = synth.make_clip(cls, np.random.default_rng(12), 48000, 20.0, "white")
    x = clip.audio
    _, ref = run(x, 48000, [x.size])
    for chunks in ([4800], [480], [7, 1000, 333]):
        _, got = run(x, 48000, chunks)
        assert [(e["label"], e["text"], e["t_start_ms"], e["t_end_ms"]) for e in got] == \
               [(e["label"], e["text"], e["t_start_ms"], e["t_end_ms"]) for e in ref], chunks


def test_decimator_streaming_equals_one_shot():
    x = np.random.default_rng(0).standard_normal(10007).astype(np.float32)
    one = Decimator3().push(x)
    d = Decimator3()
    parts, i = [], 0
    for n in [1, 2, 3, 500, 7, 4096] * 10:
        parts.append(d.push(x[i:i + n]))
        i += n
        if i >= x.size:
            break
    parts.append(d.push(x[i:]))
    np.testing.assert_allclose(np.concatenate(parts), one, atol=1e-6)
    assert one.size == -(-x.size // 3)


def test_decimator_response():
    h = decim_taps().astype(np.float64)
    f = np.linspace(0, 24000, 4801)
    H = np.abs(np.exp(-2j * np.pi * np.outer(f / 48000, np.arange(h.size))) @ h)
    db = 20 * np.log10(H + 1e-15)
    assert np.max(np.abs(db[f <= 5000])) < 0.1        # flat over the speech band used
    assert np.max(db[f >= 9600]) < -60                # anything that would alias below 6.4 kHz


def test_48k_and_16k_agree_on_a_band_limited_clip():
    """The same content captured at 48 kHz and at 16 kHz gives the same events."""
    clip = synth.make_clip("arch", np.random.default_rng(3), 48000, 25.0, "pink")
    from scipy.signal import resample_poly
    x16 = resample_poly(clip.audio, 1, 3).astype(np.float32)
    _, a = run(clip.audio, 48000, [4800])
    _, b = run(x16, 16000, [1600])
    assert [e["label"] for e in a] == [e["label"] for e in b]
    for ea, eb in zip(a, b):
        assert abs(ea["t_start_ms"] - eb["t_start_ms"]) <= 10 and abs(ea["t_end_ms"] - eb["t_end_ms"]) <= 10


def test_config_roundtrip_and_unknown_keys(tmp_path):
    c = Config(gate_open_db=11.0, loud_calib_db=-30.0)
    p = tmp_path / "c.json"
    c.save(p)
    assert Config.load(p) == c
    d = json.loads(c.to_json())
    d["no_such_threshold"] = 1
    with pytest.raises(ValueError):
        Config.from_dict(d)


def test_digital_silence_gives_no_events():
    _, evs = run(np.zeros(48000, np.float32), 16000, [1600])
    assert evs == []


def _stream(x, chunks, cfg=None):
    from vox_extract import Hold
    ex = Extractor(cfg or Config())
    out, i, k = [], 0, 0
    while i < x.size:
        n = chunks[k % len(chunks)]
        out += ex.push_stream(x[i:i + n])
        i += n
        k += 1
    out += ex.flush_stream()
    return [("hold", o.to_dict()) if isinstance(o, Hold) else ("event", o.to_dict()) for o in out]


def test_hold_flat_hum():
    """A held flat hum: `hold start` while it goes on, `hold end` just before its event; chunking-exact."""
    rng = np.random.default_rng(21)
    hum, _ = synth.make_hum("flat", rng, 16000, dur_ms=1500)
    x = np.concatenate([np.zeros(12800), hum, np.zeros(12800)]).astype(np.float32)
    x += (synth.background(rng, "pink", x.size, 16000) * 0.003).astype(np.float32)
    got = _stream(x, [1600])
    pitch = [d for k, d in got if k == "hold" and d["hold"] == "pitch"]
    assert pitch, "a 1.5 s hold sends pitch reports"
    got = [(k, d) for k, d in got if not (k == "hold" and d["hold"] == "pitch")]
    assert [k for k, _ in got] == ["hold", "hold", "event"]
    (_, start), (_, end), (_, ev) = got
    assert start["hold"] == "start" and end["hold"] == "end"
    assert start["sound"] == end["sound"] == ev["sound"] == 1 and ev["held"] is True
    assert start["t_start_ms"] == ev["t_start_ms"] and end["t_ms"] == ev["t_end_ms"]
    assert start["t_ms"] - start["t_start_ms"] == Config().hold_start_ms and start["flat"] is True
    assert [(k, d) for k, d in _stream(x, [37, 1, 503]) if d.get("hold") != "pitch"] == got
    assert run(x, 16000, [1600])[1] == [ev]


@pytest.mark.parametrize("cls", ["pop", "click", "hiss", "arch"])
def test_no_hold(cls):
    clip = synth.make_clip(cls, np.random.default_rng(22), 16000, 20.0, "pink")
    got = _stream(clip.audio, [1600])
    assert all(k == "event" for k, _ in got) and not any(d.get("held") for _, d in got)


def test_hold_off_and_push_unchanged():
    clip = synth.make_clip("flat", np.random.default_rng(23), 16000, 20.0, "pink")
    evs = [d for k, d in _stream(clip.audio, [1600]) if k == "event"]
    assert run(clip.audio, 16000, [1600])[1] == evs
    off = _stream(clip.audio, [1600], Config(hold_start_ms=0))
    assert all(k == "event" for k, _ in off) and not any(d.get("held") for _, d in off)


def _tone(f0_track, sr=16000, seed=31):
    """A hummed-like harmonic tone following f0_track (Hz per sample), with a little jitter (a voice, not a motor)."""
    rng = np.random.default_rng(seed)
    f = np.asarray(f0_track, float) * (1 + 0.004 * np.sin(2 * np.pi * 5.5 * np.arange(len(f0_track)) / sr))
    f *= 1 + 0.002 * rng.standard_normal(len(f))
    ph = 2 * np.pi * np.cumsum(f) / sr
    x = sum((0.5 / h) * np.sin(h * ph) for h in range(1, 6))
    ramp = np.minimum(1, np.minimum(np.arange(len(x)), np.arange(len(x))[::-1]) / 160)
    return (0.25 * x * ramp).astype(np.float32)


def test_hold_pitch_reports_follow_the_pitch():
    """Hold at 150 Hz, then slide up to 190 Hz (+4.1 st) and hold: the pitch reports follow, every hold_pitch_ms."""
    sr = 16000
    track = np.concatenate([np.full(int(1.0 * sr), 150.0), np.linspace(150, 190, int(0.2 * sr)), np.full(int(1.0 * sr), 190.0)])
    rng = np.random.default_rng(32)
    x = np.concatenate([np.zeros(12800, np.float32), _tone(track), np.zeros(12800, np.float32)])
    x += (synth.background(rng, "pink", x.size, sr) * 0.003).astype(np.float32)
    got = _stream(x, [1600])
    holds = [d for k, d in got if k == "hold"]
    kinds = [d["hold"] for d in holds]
    assert kinds[0] == "start" and kinds[-1] == "end" and set(kinds[1:-1]) == {"pitch"}
    pitch = [d for d in holds if d["hold"] == "pitch"]
    assert set(pitch[0]) == {"hold", "sound", "t_ms", "f0_hz"}          # compact: no t_start_ms, no flat
    gaps = np.diff([holds[0]["t_ms"]] + [d["t_ms"] for d in pitch])
    assert all(g == Config().hold_pitch_ms for g in gaps), gaps          # one report per 200 ms of sound
    assert abs(holds[0]["f0_hz"] - 150) < 3
    early = [d["f0_hz"] for d in pitch if d["t_ms"] - holds[0]["t_start_ms"] < 900]
    late = [d["f0_hz"] for d in pitch if d["t_ms"] - holds[0]["t_start_ms"] > 1500]
    assert early and late and all(abs(f - 150) < 3 for f in early) and all(abs(f - 190) < 4 for f in late), (early, late)
    assert [d for k, d in _stream(x, [37, 1, 503])] == [d for _, d in got]   # chunking-exact


def test_hold_pitch_off():
    sr = 16000
    x = np.concatenate([np.zeros(12800, np.float32), _tone(np.full(int(1.5 * sr), 150.0)), np.zeros(12800, np.float32)])
    on = [d["hold"] for k, d in _stream(x, [1600]) if k == "hold"]
    off = [d["hold"] for k, d in _stream(x, [1600], Config(hold_pitch_ms=0)) if k == "hold"]
    assert "pitch" in on and off == ["start", "end"]


def _glide_tail(f_from, f_to, glide_s, tail_s, seed=41):
    """A glide from f_from to f_to over glide_s, then its end note held for tail_s, in quiet pink noise."""
    sr = 16000
    track = np.concatenate([np.full(int(0.08 * sr), f_from), np.linspace(f_from, f_to, int(glide_s * sr)),
                            np.full(int(tail_s * sr), f_to)])
    x = np.concatenate([np.zeros(12800, np.float32), _tone(track, seed=seed), np.zeros(12800, np.float32)])
    x += (synth.background(np.random.default_rng(seed), "pink", x.size, sr) * 0.003).astype(np.float32)
    return x


@pytest.mark.parametrize("f_from,f_to,d", [(140, 210, "up"), (220, 140, "down")])
def test_glide_and_hold(f_from, f_to, d):
    """A glide whose end note is held: `hold start` with from = glide and the glide's direction, once the tail has
    been steady for hold_glide_ms and then hold_glide_delay_ms more (late start); then pitch reports, end, and the
    event (held)."""
    x = _glide_tail(f_from, f_to, 0.35, 0.8)
    got = _stream(x, [1600])
    holds = [d_ for k, d_ in got if k == "hold"]
    start = holds[0]
    assert start["hold"] == "start" and start.get("from") == "glide" and start["dir"] == d and start["flat"] is False
    assert abs(start["f0_hz"] - f_to) < 0.03 * f_to
    # hold_glide_delay_ms after the glide has mostly settled (the steadiness test tolerates the last ~100 ms of a
    # slope)
    c = Config()
    lo = 0.08e3 + 350 + 100 + c.hold_glide_delay_ms
    assert lo <= start["t_ms"] - start["t_start_ms"] <= lo + c.hold_glide_ms
    assert holds[-1]["hold"] == "end" and {h["hold"] for h in holds[1:-1]} <= {"pitch"}
    ev = [d_ for k, d_ in got if k == "event"]
    assert len(ev) == 1 and ev[0]["held"] is True
    assert [d_ for _, d_ in _stream(x, [37, 1, 503])] == [d_ for _, d_ in got]   # chunking-exact


def test_glide_short_tail_stays_a_step():
    """A glide whose end note lasts under hold_glide_ms: no hold, one plain event."""
    got = _stream(_glide_tail(220, 140, 0.35, 0.10), [1600])
    assert all(k == "event" for k, _ in got) and len(got) == 1 and not got[0][1].get("held")


def test_glide_then_gap_then_hum_is_a_flat_hold():
    """The older method still works: a glide, a gap, then a separate held flat hum -> a flat hold (no `from`)."""
    sr = 16000
    g = _glide_tail(140, 210, 0.35, 0.05)
    hum = np.concatenate([_tone(np.full(int(1.2 * sr), 180.0), seed=43), np.zeros(12800, np.float32)])
    x = np.concatenate([g, hum])
    got = _stream(x, [1600])
    starts = [d for k, d in got if k == "hold" and d["hold"] == "start"]
    assert len(starts) == 1 and "from" not in starts[0] and starts[0]["flat"] is True
    assert starts[0]["sound"] == 2


def test_glide_released_before_the_late_start_is_a_plain_step():
    """The end note passes the glide test but is released within hold_glide_delay_ms: no hold at all (not even the
    flat test's), one plain event with held = False, so the phone swipes a full step."""
    x = _glide_tail(140, 210, 0.35, 0.40)
    got = _stream(x, [1600])
    assert [k for k, _ in got] == ["event"] and not got[0][1].get("held")
    on = [d for k, d in _stream(x, [1600], Config(hold_glide_delay_ms=0)) if k == "hold" and d["hold"] == "start"]
    assert on and on[0].get("from") == "glide"   # without the late start it would have been a glide hold


def test_glide_right_after_another_sound_is_not_a_glide_hold():
    """A glide under hold_glide_quiet_ms after the previous sound (talk, music) is not tested for glide-and-hold."""
    sr = 16000
    blip = np.concatenate([np.zeros(12800, np.float32), _tone(np.full(int(0.15 * sr), 300.0), seed=44)])
    g = _glide_tail(140, 210, 0.35, 0.8)[12800 - int(0.3 * sr):]   # ~0.3 s of quiet between the two
    x = np.concatenate([blip, g])
    x += (synth.background(np.random.default_rng(45), "pink", x.size, sr) * 0.003).astype(np.float32)
    starts = [d for k, d in _stream(x, [1600]) if k == "hold" and d["hold"] == "start"]
    assert all(d.get("from") != "glide" for d in starts)
    on = [d for k, d in _stream(x, [1600], Config(hold_glide_quiet_ms=0)) if k == "hold" and d["hold"] == "start"]
    assert on and on[0].get("from") == "glide"


def test_glide_off():
    x = _glide_tail(140, 210, 0.35, 0.8)
    starts = [d for k, d in _stream(x, [1600], Config(hold_glide_ms=0)) if k == "hold" and d["hold"] == "start"]
    assert starts and "from" not in starts[0]   # the flat-hold test still catches the settled note (flat = False)


def test_arch_ending_high_is_not_a_glide():
    """An arch that comes back down but ends above its start pitch: the held note is not where the glide went
    (hold_glide_peak_st), so no glide hold; it stays an arch (at most a flat:false start, which never acts)."""
    sr = 16000
    track = np.concatenate([np.full(int(0.08 * sr), 140.0), np.linspace(140, 230, int(0.3 * sr)),
                            np.linspace(230, 180, int(0.3 * sr)), np.full(int(0.8 * sr), 180.0)])
    x = np.concatenate([np.zeros(12800, np.float32), _tone(track, seed=45), np.zeros(12800, np.float32)])
    x += (synth.background(np.random.default_rng(45), "pink", x.size, sr) * 0.003).astype(np.float32)
    starts = [d for k, d in _stream(x, [1600]) if k == "hold" and d["hold"] == "start"]
    assert all("from" not in d for d in starts), starts
    on = [d for k, d in _stream(x, [1600], Config(hold_glide_peak_st=0)) if k == "hold" and d["hold"] == "start"]
    assert on and on[0].get("from") == "glide" and on[0]["dir"] == "up"   # without the peak test it would be one
