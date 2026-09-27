"""Voice joystick core (joystick_core.py, prompts/joystick_v1.json): the rules the app port must keep."""

import json

import numpy as np

import joystick_core as J

SPEC = J.load_spec()
FS = 16000


def tone(segments, vowel="ah", rate=FS, seed=0):
    """A synthetic sung vowel: segments = [(seconds, semitones above 110 Hz or None for silence), ...]."""
    import joystick as JS
    from scipy.signal import lfilter
    rng = np.random.default_rng(seed)
    out = []
    phase = 0.0
    for dur, s in segments:
        n = int(dur * rate)
        if s is None:
            out.append(rng.normal(0, 1e-3, n))
            continue
        f0 = np.full(n, 110 * 2 ** (s / 12)) * (1 + 0.006 * np.sin(2 * np.pi * 5.5 * np.arange(n) / rate))
        ph = phase + np.cumsum(f0 / rate)
        src = np.diff(np.floor(np.r_[phase, ph])) - f0 / rate
        phase = float(ph[-1] % 1)
        y = lfilter([1.0], [1.0, -0.95], src)
        for f, bw in zip(JS.FAKE_FORMANTS[vowel], (80, 100, 120)):
            r = np.exp(-np.pi * bw / rate)
            c = -2 * r * np.cos(2 * np.pi * f / rate)
            y = lfilter([1 + c + r * r], [1, c, r * r], y)
        out.append(0.03 * y + rng.normal(0, 1e-3, n))
    return np.concatenate(out).astype(np.float32)


def run(x, mv=None, elements=(), mode="start", range_st=(9.0, 21.9)):
    """Feed audio through the analyzer and a mover (a new one in `mode`, the user's vcursor-2 range, unless given)."""
    import joystick as JS
    vow = {k: [float(J.V.bark(f[0])), float(J.V.bark(f[1]))] for k, f in JS.FAKE_FORMANTS.items()}
    an = J.Analyzer(SPEC)
    if mv is None:
        mv = J.Mover(SPEC, 411, 914, vow, range_st)
        mv.set_mode(mode)
    mv.elements = list(elements)
    for i in range(0, x.size, 320):
        for tk in an.push(x[i:i + 320]):
            mv.push(tk)
    return mv


def test_f2_continuity_streaming_matches_batch_on_accepted_frames():
    rng = np.random.default_rng(3)
    f2 = np.where(rng.random(300) < 0.1, np.nan, 900 + rng.normal(0, 60, 300))
    f2[100:103] = 2400                              # a one-off jump: dropped
    f2[200:] = 2300                                  # a real vowel change: accepted after 5 frames
    batch = J.V.f2_continuity(f2)
    fc = J.F2Continuity(J.V.A["f2_jump_hz"], J.V.A["f2_jump_frames"])
    live = np.array([fc.push(v) for v in f2])
    ok = np.isfinite(live)
    assert np.all(np.isfinite(batch[ok])) and np.allclose(live[ok], batch[ok])
    assert np.all(np.isnan(live[100:103])) and np.isfinite(live[210])


# tone() semitones are above 110 Hz = 12 st on the 55 Hz scale; the range (9.0, 21.9) has its middle at 15.45 st
MID = 15.45 - 12


def test_steady_note_stays_inside_the_dead_zone():
    mv = run(tone([(0.5, None), (1.5, 12), (0.5, None)]))
    assert np.hypot(mv.x - 205.5, mv.y - 457) < 3


def test_pitch_above_the_start_note_moves_up_and_stops_when_the_sound_ends():
    mv = run(tone([(0.5, None), (0.4, 12), (1.0, 15), (0.6, None)]))
    assert mv.y < 457 - 40 and abs(mv.x - 205.5) < 5 and mv.sound is None
    y = mv.y
    run(tone([(1.0, None)]), mv)
    assert mv.y == y                                   # silence never moves it


def test_vowels_steer_sideways():
    right = run(tone([(0.5, None), (1.2, 12), (0.5, None)], vowel="ee"))
    left = run(tone([(0.5, None), (1.2, 12), (0.5, None)], vowel="oo"))
    assert right.x > 205.5 + 40 and left.x < 205.5 - 40


def test_position_survives_mode_toggle_and_only_recentre_resets():
    mv = run(tone([(0.5, None), (0.4, 12), (1.0, 15), (0.6, None)]))
    x, y = mv.x, mv.y
    mv.enabled = False
    run(tone([(1.0, 12), (0.5, None)]), mv)
    mv.enabled = True
    assert (mv.x, mv.y) == (x, y)
    mv.set_screen(914, 411, [])                        # rotation: same coordinates, clamped
    assert mv.x == x and mv.y == min(y, 411)
    mv.recentre()
    assert (mv.x, mv.y) == (457, 205.5)


def test_home_mode_moves_down_below_the_middle_and_up_above_it():
    still = run(tone([(0.5, None), (1.5, MID), (0.5, None)]), mode="mid")
    down = run(tone([(0.5, None), (1.2, MID - 4), (0.5, None)]), mode="mid")
    up = run(tone([(0.5, None), (1.2, MID + 4), (0.5, None)]), mode="mid")
    assert abs(still.y - 457) < 3
    assert down.y > 457 + 100 and up.y < 457 - 100 and abs((down.y - 457) - (457 - up.y)) < 30   # same both ways


def test_low_home_voice_reaches_down_in_home_mode_but_not_in_start_mode():
    """The live bug: a hum starts 1.2 st above the bottom of the range, so 'below the start' has no room."""
    lo = 9.0 - 12
    seg = [(0.5, None), (0.3, lo + 1.2), (1.2, lo), (0.5, None)]      # start at home, then down as far as it goes
    start = run(tone(seg), mode="start")
    mid = run(tone(seg), mode="mid")
    assert start.y - 457 < 15 and mid.y - 457 > 200


def test_glide_mode_keeps_its_direction_while_held_and_a_glide_back_stops_it():
    def glide(a, b, dur=0.3, n=15):
        return [(dur / n, a + (b - a) * (i + 1) / n) for i in range(n)]
    held = run(tone([(0.5, None), (0.3, MID)] + glide(MID, MID + 2.5) + [(1.0, MID + 2.5), (0.5, None)]), mode="glide")
    assert held.y < 457 - 150                                          # up, and kept going while the note was held
    back = run(tone([(0.5, None), (0.3, MID)] + glide(MID, MID + 2.5) + [(0.2, MID + 2.5)]
                    + glide(MID + 2.5, MID) + [(1.0, MID), (0.5, None)]), mode="glide")
    ys = [y for _, _, y in back.events[-1]["path"]]
    assert np.ptp(ys[-40:]) < 5                                        # the last 0.8 s of the held note: no vertical motion
    flat = run(tone([(0.5, None), (1.5, MID + 6), (0.5, None)]), mode="glide")
    assert abs(flat.y - 457) < 3                                       # a held note from the start: nothing vertical


def test_onset_from_far_below_is_undone_but_a_deliberate_early_step_is_not():
    creak = run(tone([(0.5, None), (0.3, MID - 10), (1.0, MID), (0.5, None)]), mode="mid")
    assert abs(creak.y - 457) < 5 and creak.events[-1]["reanchors"] == 1
    step = run(tone([(0.5, None), (0.35, MID - 4), (1.0, MID), (0.5, None)]), mode="mid")
    assert step.y > 457 + 10 and step.events[-1]["reanchors"] == 0     # the early 4 st step down counted


def test_the_stop_reason_is_reported():
    mv = run(tone([(0.5, None), (0.8, MID), (0.5, None)]), mode="mid")
    assert mv.last_stop == "quiet (level < floor+6dB)" and mv.events[-1]["why"] == mv.last_stop


def test_magnet_picks_the_nearest_within_reach_and_the_smaller_on_a_tie():
    row = J.Element(0, 100, 411, 172, "row")
    btn = J.Element(350, 112, 398, 160, "button")
    far = J.Element(0, 400, 48, 448, "far")
    els = [row, btn, far]
    big = 0.5 * 411 * 914
    assert J.magnet(els, 360, 130, 48, big) == 1        # inside both: the smaller
    assert J.magnet(els, 200, 60, 48, big) == 0         # 40 dp above the row
    assert J.magnet(els, 200, 300, 48, big) is None     # nothing within 48 dp: stays put
    assert J.snap_point(btn, 360, 130, 96) == btn.centre
    assert J.snap_point(row, 200, 130, 96) == (200, 130)          # on a big element: stays where it stopped
    assert J.snap_point(row, 200, 60, 96) == (200, 108)           # just outside: onto it, 8 dp in


def test_pop_clicks_after_the_gap_and_pop_pop_does_not():
    c = J.Clicker(SPEC)
    assert c.pop(1000) is None and c.poll(1500) is None and c.poll(1700) == "click"
    assert c.pop(3000) is None and c.pop(3300) == "pop_pop" and c.poll(5000) is None


def test_fake_singer_task_end_to_end():
    import argparse
    import joystick as JS
    screens = JS.load_screens(SPEC)
    a = argparse.Namespace(screen=None, task=6, seed=4, source="fake", vowels_out=JS.OUT / "unused.json", mode="start",
                           fake_voice="free")
    vow = {k: [float(J.V.bark(f[0])), float(J.V.bark(f[1]))] for k, f in JS.FAKE_FORMANTS.items()}
    ses = JS.Session(SPEC, screens, a, vow)
    while not ses.task.done and ses.t_ms < 200_000:
        ses.feed(ses.fake.audio(320))
    sm = ses.task.summary()
    assert sm["targets"] == 6 and sm["hit"] >= 5 and sm["false_clicks"] == 0


def pops(k, gap_s=1.0, gain=0.3, seed=0):
    """k lip pops (synth.make_pop), gap_s apart, after 0.5 s of quiet."""
    import synth
    rng = np.random.default_rng(seed)
    out = [np.random.default_rng(seed + 1).normal(0, 1e-3, FS // 2)]
    for _ in range(k):
        y = gain * synth.make_pop(rng, FS)[0]
        out += [y, rng.normal(0, 1e-3, int(gap_s * FS) - y.size)]
    return np.concatenate(out).astype(np.float32)


def feed(ses, x):
    for i in range(0, x.size, 320):
        ses.feed(x[i:i + 320])


def setup_session(tmp_path, **kw):
    import argparse
    import joystick as JS
    a = argparse.Namespace(screen=None, task=3, seed=1, source="pw", vowels_out=tmp_path / "vowels.json",
                           range_out=tmp_path / "range.json", pops_out=tmp_path / "pops.json",
                           calib2_out=tmp_path / "calib2.json", trace=False, **kw)
    return JS.Session(SPEC, JS.load_screens(SPEC), a, None)


def test_setup_measures_home_range_vowels_and_pops_and_a_quit_task_is_kept(tmp_path):
    import joystick as JS
    ses = setup_session(tmp_path)
    ses.command("setup")
    n = 250                                  # a smooth glide: 0.1 st steps (a person glides, not in stairs)
    glide = [(5.4 / n, -2 + 13 * (1 - abs(2 * i / n - 1))) for i in range(n + 1)]     # 9 st .. 22 st .. 9 st
    x = np.concatenate([tone([(1.2, None), (3.3, MID - 1.5), (0.6, None)]),           # the relaxed hum: 13.95 st
                        tone([(0.5, None)] + glide + [(0.5, None)])]
                       + [tone([(2.2, MID), (0.6, None)], vowel=v, seed=i) for i, v in enumerate(("ee", "ah", "oo"))]
                       + [pops(3), tone([(1.0, None)])])
    feed(ses, x)
    assert ses.dsetup and ses.dsetup["kind"] == "clicks"     # calibration v2 goes on: clicks, whistle, hiss, room
    for _ in range(3):                               # (tests/test_calib_v2.py); here each fails and is skipped
        feed(ses, tone([(11.0, None)]))
        assert ses.failed
        ses.command("skip")
    feed(ses, tone([(4.0, None)]))                    # the room: quiet
    assert not ses.in_setup and ses.voice["room"]["transients"] == 0
    assert abs(ses.mv.mid - (MID - 1.5 + 12)) < 0.3 and ses.voice["home_st"] == round(ses.mv.home_setup, 2)
    lo_c, hi_c = SPEC["voicing"]["person_clarity"]
    assert lo_c <= ses.an.clarity_on <= hi_c
    lo, hi = ses.mv.range
    assert abs(lo - 10) < 1.5 and abs(hi - 22) < 1.5
    saved = json.loads((tmp_path / "range.json").read_text())
    assert saved["home_st"] == ses.voice["home_st"] and saved["clarity_on"] and saved["lo_st"] == round(lo, 2)
    rep = ses.vowel_report["per_vowel"]
    assert rep["ee"]["right"] > 0.8 and rep["oo"]["left"] > 0.8 and rep["ah"]["none"] > 0.8
    assert (tmp_path / "vowels.json").exists()
    assert ses.pops_cal and (tmp_path / "pops.json").exists() and ses.pops == 0     # setup pops never click
    v = JS.load_voice(tmp_path / "range.json", tmp_path / "pops.json")             # --skip-setup reuses it all
    assert v["home_st"] == ses.voice["home_st"] and v["pop"]["peak_db"] == ses.pd.c["peak_db"]
    ses.task.abort(ses.t_ms)
    assert len(ses.task.trials) == 1 and ses.task.trials[0]["quit"] and ses.task.summary()["quit"] == 1


def test_setup_creak_is_dropped_from_home_and_range():
    """Creak jumps ~0.4 st tick to tick; a held note or a 5 s glide moves < 0.2: only steady ticks count."""
    import joystick as JS
    rng = np.random.default_rng(0)
    held = list(12 + rng.normal(0, 0.03, 100))
    creak = list(3 + rng.normal(0, 0.5, 40))
    v = JS.Session.steady(held + [np.nan] + creak)
    assert v.size > 90 and np.mean(v < 6) < 0.03


def test_after_the_setup_pops_click_once_even_when_both_detectors_hear_them(tmp_path):
    ses = setup_session(tmp_path)
    feed(ses, tone([(1.0, None)]))                  # the detector's warm-up (the floor settles)
    ses.command("pops")
    feed(ses, np.concatenate([pops(3), tone([(1.0, None)])]))
    assert ses.pops_cal and not ses.in_setup
    feed(ses, np.concatenate([pops(2, gap_s=1.5, seed=7), tone([(1.0, None)])]))
    assert ses.pops == 2, ses.pop_by


def tick(t, f0=0.0, cl=0.3, over=0.0, voiced=False):
    return J.Tick(t, f0 if voiced else 0.0, cl, -60 + over, voiced, np.nan, np.nan, "" if voiced else "unclear", f0, over)


def test_a_fry_like_dropout_continues_the_sound_but_unclear_noise_never_starts_one():
    mv = J.Mover(SPEC, 411, 914, None, (9.0, 21.9))
    f0 = 55 * 2 ** (15 / 12)
    ts = iter(range(0, 100000, 20))
    for _ in range(30):
        mv.push(tick(next(ts), f0, 0.95, 20, True))
    for _ in range(8):                                        # 160 ms: loud, pitched, clarity 0.7 (creak-like)
        mv.push(tick(next(ts), f0 * 0.99, 0.7, 15))
    for _ in range(30):
        mv.push(tick(next(ts), f0, 0.95, 20, True))
    for _ in range(20):
        mv.push(tick(next(ts)))
    ends = [e for e in mv.events if e["ev"] == "hum_end"]
    assert len(ends) == 1 and ends[0]["continued"] == 8
    mv2 = J.Mover(SPEC, 411, 914, None, (9.0, 21.9))
    for t in range(0, 2000, 20):                             # loud noise with a stray pitch, clarity 0.7: no sound
        mv2.push(tick(t, f0, 0.7, 15))
    assert not [e for e in mv2.events if e["ev"] == "hum_start"] and mv2.sound is None


def pop_ticks(det, level):
    """Level tracks (dB over the floor, 20 ms ticks) through the tick pop detector -> the pops' times."""
    out = []
    for i, (ov, voiced) in enumerate(level):
        r = det.push(tick(1000 + 20 * i, 150.0, 0.95 if voiced else 0.3, ov, voiced))
        if r is not None:
            out.append(r)
    return out


def test_tick_pop_detector_hears_a_pop_but_not_a_hum_onset_or_a_plosive():
    q = [(0.0, False)] * 10
    pop = [(30.0, False), (18.0, False), (8.0, False)]
    assert len(pop_ticks(J.PopDetector(SPEC), q + pop + q)) == 1
    hum = [(6.0, False), (14.0, False)] + [(20.0, True)] * 30
    assert pop_ticks(J.PopDetector(SPEC), q + hum + q) == []                     # a hum's onset
    word = pop + [(4.0, False)] + [(20.0, True)] * 10
    assert pop_ticks(J.PopDetector(SPEC), q + word + q) == []                    # 'p' then voice: a plosive
    long = [(25.0, False)] * 12
    assert pop_ticks(J.PopDetector(SPEC), q + long + q) == []                    # a sustained noise, not a pop


# ---- setup failures: say why, then wait for R (retry) or S (skip); a skip is saved

def test_a_failed_pop_setup_waits_for_retry_and_then_succeeds(tmp_path):
    ses = setup_session(tmp_path)
    feed(ses, tone([(1.0, None)]))
    ses.command("pops")
    feed(ses, tone([(9.0, None)]))                  # no pops in 8 s
    assert ses.failed and ses.failed["step"] == "pops" and "0/3" in ses.failed["why"] and ses.in_setup
    feed(ses, np.concatenate([pops(3), tone([(1.0, None)])]))       # pops while it waits: nothing happens
    assert ses.failed and ses.pops == 0 and not ses.pops_cal
    ses.command("glide")                            # any other key only reminds
    assert ses.failed and ses.mv.mode != "glide"
    ses.command("rotate")                           # R
    assert not ses.failed and ses.psetup
    feed(ses, np.concatenate([pops(3), tone([(1.0, None)])]))
    assert ses.pops_cal and not ses.in_setup and "pops" not in ses.voice.get("skipped", [])
    saved = json.loads((tmp_path / "pops.json").read_text())
    assert saved["pop"] and len(saved["ticks"]) == len(saved["peaks_db"])


def test_a_skipped_pop_setup_keeps_the_defaults_and_is_saved(tmp_path):
    import joystick as JS
    ses = setup_session(tmp_path)
    feed(ses, tone([(1.0, None)]))
    ses.command("pops")
    feed(ses, tone([(9.0, None)]))
    ses.command("setup")                            # S
    assert not ses.in_setup and not ses.pops_cal and ses.pd.c == SPEC["pop"]
    assert json.loads((tmp_path / "pops.json").read_text())["skipped"] == ["pops"]
    assert json.loads((tmp_path / "range.json").read_text())["skipped"] == ["pops"]
    v = JS.load_voice(tmp_path / "range.json", tmp_path / "pops.json")   # --skip-setup: the defaults
    assert "pop" not in v and v["skipped"] == ["pops"]


def test_silent_home_fails_and_a_skip_keeps_the_default_voicing(tmp_path):
    ses = setup_session(tmp_path)
    ses.command("hum")
    feed(ses, tone([(11.0, None)]))
    assert ses.failed["step"] == "home" and "no steady hum" in ses.failed["why"]
    feed(ses, tone([(2.0, MID)]))                   # sound while it waits: the cursor does not move
    assert ses.mv.sound is None and (ses.mv.x, ses.mv.y) == (ses.mv.w / 2, ses.mv.h / 2)
    ses.command("skip")
    assert not ses.in_setup and ses.an.clarity_on == SPEC["voicing"]["clarity_min"] and ses.mv.home_setup is None
    saved = json.loads((tmp_path / "range.json").read_text())
    assert saved["skipped"] == ["home"] and "home_st" not in saved


def test_a_narrow_range_fails_and_a_retry_restarts_the_step(tmp_path):
    ses = setup_session(tmp_path)
    ses.command("range")
    feed(ses, tone([(0.5, None), (5.5, MID), (0.6, None)]))   # one held note: 0 st of range
    assert ses.failed["step"] == "range" and "too small" in ses.failed["why"]
    ses.command("retry")
    assert ses.rsetup and ses.rsetup["t0"] is None and not ses.failed
    ses.command("range")                            # (a key other than R / S while not failed: normal)
    feed(ses, tone([(11.0, None)]))
    ses.command("skip")
    saved = json.loads((tmp_path / "range.json").read_text())
    assert "range" in saved["skipped"] and "lo_st" not in saved
    assert ses.mv.range == tuple(SPEC["vertical"]["home"]["range_st"])


def test_silent_vowels_fail_and_a_skip_writes_no_centres(tmp_path):
    import joystick as JS
    ses = setup_session(tmp_path)
    before = {k: v.copy() for k, v in ses.mv.cent.items()}
    ses.command("vowels")
    feed(ses, tone([(13.0, None)]))
    assert ses.failed["step"] == "vowels" and "'ee'" in ses.failed["why"]
    assert all(np.allclose(ses.mv.cent[k], before[k]) for k in before)
    ses.command("setup")
    assert JS.load_vowels(str(tmp_path / "vowels.json")) is None
    assert "vowels" in json.loads((tmp_path / "range.json").read_text())["skipped"]
