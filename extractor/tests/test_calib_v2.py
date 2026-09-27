"""Calibration v2 (joystick_core.py level gate / click-pop rule / whistle band; joystick.py setup steps 5-8): the
rules the app port keeps (android JoyCalibration / LevelGate, checked against android/tools/gen_joystick_golden.py)."""

import json

import numpy as np
import pytest

import joystick_core as J
from test_joystick import FS, SPEC, feed, setup_session, tone


def ex(snr, level, dur=40.0, lf=0.03):
    return {"dur_ms": dur, "snr_db": snr, "level_db": level, "lf_ratio": lf, "peak_centroid_hz": 3000.0}


POPS = [ex(40.0, -13.0, 120, 0.3), ex(36.5, -16.0, 110, 0.25), ex(38.0, -15.0, 140, 0.4)]
CLICKS = [ex(20.0, -31.0, 40, 0.02), ex(17.5, -33.5, 50, 0.03), ex(16.0, -34.0, 60, 0.05)]


# ---- the level gate

def test_the_gate_is_the_default_until_the_clicks_step_has_examples():
    d = SPEC["level_gate"]["default"]
    for e in ({}, {"pops": POPS}, {"pops": POPS, "hiss": [ex(25, -25)]}):
        g = J.derive_gate(e, None, SPEC)
        assert g["from"] == "default" and (g["min_snr_db"], g["min_level_dbfs"]) == (d["min_snr_db"], d["min_level_dbfs"])


def test_the_gate_is_the_weakest_example_minus_the_margin():
    g = J.derive_gate({"pops": POPS, "clicks": CLICKS}, None, SPEC)
    m = SPEC["level_gate"]
    assert g["from"] == "calibration" and g["n"] == 6
    assert g["min_snr_db"] == 16.0 - m["margin_snr_db"] and g["min_level_dbfs"] == -34.0 - m["margin_level_db"]
    for e in POPS + CLICKS:                           # every calibrated example passes its own gate
        assert J.gate_reason(g, "click", e["snr_db"], e["level_db"]) is None


def test_a_loud_room_raises_the_gate_but_never_over_the_weakest_example():
    m = SPEC["level_gate"]
    g = J.derive_gate({"clicks": CLICKS}, {"transient_snr_db": 11.0, "transient_level_dbfs": -60.0}, SPEC)
    assert g["min_snr_db"] == 11.0 + m["room_margin_db"] and g["min_level_dbfs"] == -34.0 - m["margin_level_db"]
    g = J.derive_gate({"clicks": CLICKS}, {"transient_snr_db": 30.0, "transient_level_dbfs": -20.0}, SPEC)
    assert g["min_snr_db"] == 16.0 - m["cap_below_weakest_db"] and g["min_level_dbfs"] == -34.0 - m["cap_below_weakest_db"]


def test_the_gate_needs_both_numbers_and_skips_everything_but_pop_click_hiss():
    g = J.derive_gate({"clicks": CLICKS}, None, SPEC)          # 8 dB, -42 dBFS
    r = J.gate_reason(g, "click", 7.0, -30.0)
    assert r["reason"] == "below level gate" and r["min_snr_db"] == 8.0 and r["from"] == "calibration"
    assert J.gate_reason(g, "hiss", 20.0, -43.0)["reason"] == "below level gate"
    assert J.gate_reason(g, "pop", 9.0, -41.0) is None
    assert J.gate_reason(g, "rise", 1.0, -80.0) is None and J.gate_reason(g, "pop", None, -20.0) is None
    assert J.gate_reason(None, "pop", 1.0, -80.0) is None
    # the app gates `unknown` too on the phone / USB mic (before its trained-gesture relabel); the default labels do not
    assert J.gate_reason(g, "unknown", 1.0, -80.0) is None
    assert J.gate_reason(g, "unknown", 1.0, -80.0, labels=J.PHONE_GATE_LABELS)["reason"] == "below level gate"


def test_the_offset_moves_both_thresholds():
    g = J.derive_gate({"clicks": CLICKS}, None, SPEC)
    assert J.gate_reason(g, "click", 9.0, -41.0) is None
    assert J.gate_reason(g, "click", 9.0, -41.0, 2.0)["min_snr_db"] == 10.0          # + = stricter
    assert J.gate_reason(g, "click", 7.0, -43.0, -2.0) is None


# ---- the per-person click / pop rule

def test_the_rule_relabels_only_when_every_separating_feature_agrees():
    rule = J.derive_click_pop(POPS, CLICKS, SPEC)
    assert set(rule["features"]) == {"dur_ms", "snr_db", "level_db", "lf_ratio"}
    r = J.relabel(rule, "pop", ex(18.0, -32.0, 45, 0.02))                           # a click the extractor called pop
    assert r["from"] == "pop" and r["to"] == "click" and set(r["votes"].values()) == {"click"}
    assert J.relabel(rule, "click", ex(37.0, -15.0, 120, 0.3))["to"] == "pop"
    assert J.relabel(rule, "pop", ex(39.0, -14.0, 120, 0.3)) is None                 # already right
    assert J.relabel(rule, "pop", ex(18.0, -15.0, 45, 0.3)) is None                  # features disagree
    assert J.relabel(rule, "hiss", ex(18.0, -32.0)) is None                          # pop <-> click only
    assert J.relabel(rule, "pop", {"dur_ms": 45, "snr_db": 18.0}) == {               # missing numbers do not vote
        "from": "pop", "to": "click", "votes": {"dur_ms": "click", "snr_db": "click"}}


def test_no_rule_without_enough_examples_or_separating_features():
    assert J.derive_click_pop(POPS[:1], CLICKS, SPEC) is None
    same = [ex(30, -20, 100, 0.2), ex(31, -21, 110, 0.2)]
    near = [ex(29, -20.5, 40, 0.19), ex(32, -19, 50, 0.21)]                          # only the duration separates
    assert J.derive_click_pop(same, near, SPEC) is None
    assert J.relabel(None, "pop", ex(18.0, -32.0)) is None


# ---- the whistle band

WHISTLE = {"lo_st": 50.0, "hi_st": 62.0, "home_st": 56.0, "split_st": 36.0}


def mover():
    import joystick as JS
    vow = {k: [float(J.V.bark(f[0])), float(J.V.bark(f[1]))] for k, f in JS.FAKE_FORMANTS.items()}
    mv = J.Mover(SPEC, 411, 914, vow, (9.0, 21.9))
    mv.set_mode("home")
    mv.home_setup = 14.0
    return mv


def test_over_the_split_the_whistle_home_and_range_steer():
    mv = mover()
    assert not mv.in_whistle(60.0) and mv.home_ref(60.0) == mv.mid          # no whistle range: the voice's
    mv.set_whistle(WHISTLE)
    assert mv.in_whistle(40.0) and not mv.in_whistle(20.0)
    assert mv.home_ref(40.0) == 56.0 and mv.home_ref(20.0) == mv.mid
    f = SPEC["vertical"]["home"]["full_frac"]
    assert mv.full_st(False, True) == pytest.approx(f * (62.0 - 56.0)) and mv.full_st(True, True) == pytest.approx(f * 6.0)
    assert mv.full_st(False) == pytest.approx(f * (21.9 - 14.0))                     # the voice side unchanged
    mv.set_whistle(None)
    assert not mv.in_whistle(40.0)


def whistle(segs, rate=FS, amp=0.05):
    """A whistle: segments = [(seconds, hz0, hz1) or (seconds, None)]: a sine, log-linear glide, 30 ms ramps."""
    rng = np.random.default_rng(3)
    out, ph = [], 0.0
    for s in segs:
        n = int(s[0] * rate)
        if s[1] is None:
            out.append(rng.normal(0, 1e-3, n))
            continue
        f = np.exp(np.linspace(np.log(s[1]), np.log(s[2]), n))
        p = ph + np.cumsum(2 * np.pi * f / rate)
        ph = float(p[-1])
        env = np.minimum(1, np.minimum(np.arange(n), n - np.arange(n)) / (0.03 * rate))
        out.append(amp * env * np.sin(p) + rng.normal(0, 1e-3, n))
    return np.concatenate(out).astype(np.float32)


def test_whistle_ticks_use_the_whistle_ceiling():
    x = whistle([(0.5, None), (1.5, 1600.0, 1600.0), (0.3, None)])
    for fmax, ok in ((None, False), (SPEC["calib_v2"]["whistle"]["tick_f0_max_hz"], True)):
        an = J.Analyzer(SPEC)
        an.f0_max_hz = fmax
        f0 = [t.f0 for i in range(0, x.size, 320) for t in an.push(x[i:i + 320]) if t.voiced]
        right = np.mean([abs(12 * np.log2(f / 1600.0)) < 0.5 for f in f0]) if f0 else 0.0
        assert (right > 0.9) == ok, (fmax, right)


# ---- the setup steps

def raw(snr, level, dur=40.0, lf=0.03):
    return ex(snr, level, dur, lf)


def at(ses, t_ms, label, r):
    ses.ex_event(t_ms, label, r)


def test_clicks_whistle_hiss_room_pass_and_are_saved(tmp_path):
    import joystick as JS
    ses = setup_session(tmp_path)
    feed(ses, tone([(1.0, None)]))
    ses.command("clicks")
    t = ses.t_ms
    for i, (lab, r) in enumerate((("click", raw(20.3, -31.2)), ("click", raw(18.1, -33.0)), ("hiss", raw(16.4, -34.4, 190)))):
        at(ses, t + 500 + 1000 * i, lab, r)
    at(ses, t + 900, "click", raw(30.0, -20.0, 400))                     # too long for a click: not an example
    feed(ses, tone([(4.0, None)]))
    assert not ses.dsetup and not ses.failed
    assert [e["label"] for e in ses.voice["clicks_examples"]] == ["click", "click", "hiss"]
    assert ses.gate["from"] == "calibration" and ses.gate["min_snr_db"] == pytest.approx(16.4 - 8.0)
    ses.command("whistle")
    feed(ses, whistle([(0.5, None), (2.6, 1000.0, 2000.0), (2.6, 2000.0, 1000.0), (0.8, None)]))
    w = ses.voice["whistle"]
    assert not ses.failed and abs(w["lo_st"] - J.V.st(1000.0)) < 1.0 and abs(w["hi_st"] - J.V.st(2000.0)) < 1.0
    assert ses.mv.whistle == w and ses.an.f0_max_hz == SPEC["calib_v2"]["whistle"]["tick_f0_max_hz"]
    assert w["split_st"] == round((ses.mv.range[1] + w["lo_st"]) / 2, 2)
    ses.command("hiss")
    t = ses.t_ms
    at(ses, t + 500, "hiss", raw(25.0, -25.1, 150)); at(ses, t + 1500, "hiss", raw(23.2, -26.3, 160))
    feed(ses, tone([(3.0, None)]))
    assert len(ses.voice["hiss_examples"]) == 2 and not ses.failed
    ses.command("room")
    at(ses, ses.t_ms + 1000, "click", raw(9.2, -50.3))
    feed(ses, tone([(4.0, None)]))
    room = ses.voice["room"]
    assert not ses.in_setup and room["transients"] == 1 and room["transient_snr_db"] == 9.2
    assert ses.gate["min_snr_db"] == pytest.approx(9.2 + 3.0)                         # the room raised it
    saved = json.loads((tmp_path / "calib2.json").read_text())
    assert saved["version"] == 2 and saved["level_gate"] == ses.gate and saved["whistle"] == w
    v = JS.load_voice(tmp_path / "range.json", tmp_path / "pops.json", tmp_path / "calib2.json")
    assert v["whistle"] == w and v["room"] == room and len(v["clicks_examples"]) == 3
    row = {}                                                             # live: a quiet click is ignored, logged
    assert ses._judge("click", raw(10.0, -40.0), row) is None and row["ignored"]["reason"] == "below level gate"
    assert ses._judge("click", raw(20.0, -30.0), {}) == "click"


def test_the_new_steps_fail_with_a_reason_then_retry_or_skip(tmp_path):
    ses = setup_session(tmp_path)
    feed(ses, tone([(1.0, None)]))
    ses.command("clicks")
    at(ses, ses.t_ms + 500, "click", raw(19.0, -32.0))
    feed(ses, tone([(9.0, None)]))
    assert ses.failed["step"] == "clicks" and ses.failed["why"].startswith("heard 1/3 clicks, need 2")
    ses.command("skip")
    assert "clicks" in json.loads((tmp_path / "range.json").read_text())["skipped"] and ses.gate["from"] == "default"
    ses.command("whistle")
    feed(ses, tone([(11.0, None)]))
    assert ses.failed["step"] == "whistle" and ses.failed["why"] == "no steady whistle heard in 10 s"
    ses.command("retry")
    feed(ses, tone([(0.5, None), (2.5, 1.0), (2.5, 7.0), (1.0, None)]))    # sung, inside the voice range
    assert ses.failed["step"] == "whistle" and "overlaps your voice range" in ses.failed["why"]
    ses.command("skip")
    assert "whistle" not in ses.voice and ses.an.f0_max_hz is None
    ses.command("hiss")
    feed(ses, tone([(9.0, None)]))
    assert ses.failed["why"].startswith("heard 0/2 hisses, need 2")
    ses.command("skip")
    ses.command("room")
    feed(ses, tone([(0.5, None), (1.5, 3.0), (2.0, None)]))
    assert ses.failed["step"] == "room" and ses.failed["why"].startswith("not quiet: a steady tone")
    ses.command("retry")
    at(ses, ses.t_ms + 800, "pop", raw(30.5, -20.0, 100))
    ses.voice["pops_examples"] = [raw(25.0, -25.0, 120)]                   # a calibrated sound to compare with
    feed(ses, tone([(4.0, None)]))
    assert ses.failed["step"] == "room" and ses.failed["why"].startswith("a sound in the room was as loud")
    ses.command("skip")
    assert not ses.in_setup


# ---- a partial setup (the app's calib_start {steps})

def test_a_partial_setup_runs_only_its_steps_and_ends_after_the_last(tmp_path):
    import joystick as JS
    assert JS.Session.parse_steps("hum,glide,clicks") == ["home", "range", "clicks"]
    assert JS.Session.parse_steps(None) is None
    for bad in ("clicks,nope", "room,room", ","):
        with pytest.raises(ValueError):
            JS.Session.parse_steps(bad)
    ses = setup_session(tmp_path, setup_steps="clicks,hiss")
    ses.command("setup")
    assert ses.dsetup and ses.dsetup["kind"] == "clicks" and not ses.hsetup      # no hum first
    feed(ses, tone([(9.0, None)]))
    assert ses.failed and ses.failed["step"] == "clicks"
    ses.command("skip")
    assert ses.dsetup["kind"] == "hiss"
    feed(ses, tone([(9.0, None)]))
    assert ses.failed and ses.failed["step"] == "hiss"
    ses.command("skip")                              # the last step skipped: the setup is over, nothing wraps round
    assert not ses.in_setup and not ses.failed and ses.setup_queue == []
    assert set(ses.voice["skipped"]) == {"clicks", "hiss"}
    feed(ses, tone([(12.0, None)]))
    assert not ses.in_setup and not ses.failed
