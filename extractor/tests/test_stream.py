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
