"""Synthetic tests for extractor/range_suite.py (the recorded range suite CHECKS RUNNER + mixer).

Everything is SYNTHETIC: numpy tones / synth.py gestures / noise, written as contract-valid sessions through
range_layout (open_session, label_row, the spec's take IDs) into a private folder under android/.state (the runner
refuses to write reports anywhere else). No microphone, no device, no model API; app replay runs against fakes.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
import pytest

import range_layout as L
import range_suite as R

FS = 16000
PRIVATE = L.HERE.parent / "android" / ".state"
CENTRE = dict(tone="hum", pitch="home", speed="normal", loud="normal", dist="hand", gap="na")
DISCRETE = dict(CENTRE, tone="na", pitch="na", speed="na")


# ---------------------------------------------------------------------------------- synth audio

def write_wav(path: Path, x: np.ndarray, rate: int = FS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.clip(np.asarray(x, dtype=np.float32), -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((data * 32767).astype("<i2").tobytes())


def sine(hz: float, seconds: float, amp: float = 0.1, rate: int = FS) -> np.ndarray:
    t = np.arange(int(rate * seconds)) / rate
    return (amp * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def white_noise(n: int, rms_target: float, seed: int = 0) -> np.ndarray:
    x = np.random.default_rng(seed).standard_normal(n).astype(np.float32)
    return x * (rms_target / R.rms(x))


def make_gesture(cls: str, rng: np.random.Generator) -> np.ndarray:
    """A single synthetic gesture (synth.py's own generator, which the extractor is tuned on)."""
    import synth
    return synth.make_clip(cls, rng, FS, 20.0, "pink").audio


# ---------------------------------------------------------------------------------- session builder

@pytest.fixture
def private():
    """A private folder the runner accepts (android/.state is gitignored), removed afterwards."""
    PRIVATE.mkdir(parents=True, exist_ok=True)
    d = Path(tempfile.mkdtemp(prefix="range-checks-", dir=PRIVATE))
    yield d
    shutil.rmtree(d, ignore_errors=True)


def tid(block: str, gesture: str, cond: dict, rep: int = 1) -> str:
    return f"{block}-{gesture.replace(' ', '-')}-{L.cond_id(cond)}-r{rep}"


def build(root: Path, takes: dict[str, np.ndarray], backgrounds: dict[str, np.ndarray] | None = None,
          name: str = "s", speaker: str = "self", profile: str = "full", ratings: list[dict] | None = None) -> Path:
    """A contract-valid SYNTHETIC session: {take_id: audio (1 s before GO included)}, {background name: 60 s}."""
    spec = L.load_spec()
    out = root / name
    L.open_session(out, spec, "desktop", "synthetic", FS, 1, True, profile=profile, speaker=speaker)
    plan = {t["take_id"]: t for t in L.build_plan(spec, profile=profile)}
    for take_id, x in takes.items():
        t = plan[take_id]
        row = L.label_row(t, 0, 0, 1000, len(x), FS)
        write_wav(out / row["file"], x)
        L.append_row(out / "labels.jsonl", row)
    for bg, x in (backgrounds or {}).items():
        t = plan[f"backgrounds-{bg}-r1"]
        write_wav(out / "backgrounds" / f"{bg}.wav", x)
        L.append_row(out / "backgrounds.jsonl", dict(name=bg, kind=t["bg_kind"], level=t["level"],
                                                      seconds=t["seconds"], file=f"backgrounds/{bg}.wav"))
    for r in ratings or []:
        L.append_row(out / "ratings.jsonl", r)
    return out


def standard(root: Path, **kw) -> Path:
    """Contours rise/fall, discrete click/hiss at the centre: gestures synth.py makes the extractor get right."""
    rng = np.random.default_rng(7)
    return build(root, {tid("contours", "rise", CENTRE): make_gesture("rise", rng),
                        tid("contours", "fall", CENTRE): make_gesture("fall", rng),
                        tid("discrete", "click", DISCRETE): make_gesture("click", rng),
                        tid("discrete", "hiss", DISCRETE): make_gesture("hiss", rng)},
                 ratings=[dict(block="contours", rating=4, note="fine", seconds=20, redos=1)], **kw)


def opts(**kw):
    base = dict(config=None, no_cpp=True, musan=[], esc50=[], snr=None, seed=0, flag=10.0, emulator=False,
                serial="emulator-5580", adb_port=5038, socket_port=7789, replay_settle_s=0.0)
    base.update(kw)
    return type("O", (), base)()


def ev(label: str, snr: float | None = 20.0, level: float | None = -30.0, dur: float = 100.0,
       text: str = "a tongue click; instant sound; loudness normal; sounds like mouth sound") -> dict:
    raw = {"snr_db": snr, "level_db": level, "dur_ms": dur}
    return {"label": label, "text": text, "snr_db": snr, "level_db": level, "dur_ms": dur,
            "example": R.J.example(raw), "nearfield": None}


# ---------------------------------------------------------------------------------- loading

def test_load_session_uses_range_layout_last_row_wins(private):
    out = standard(private)
    rows = L.read_rows(out / "labels.jsonl")
    L.append_row(out / "labels.jsonl", dict(rows[0], redo=1))
    s = R.load_session(out)
    assert len(s["takes"]) == 4 and s["takes"][0]["redo"] == 1
    assert (s["speaker"], s["profile"], s["device"]) == ("self", "full", "desktop")
    # plan order, not journal order
    assert [t["block"] for t in s["takes"]] == ["contours", "contours", "discrete", "discrete"]


def test_load_session_rejects_an_invalid_layout(private):
    out = standard(private)
    row = L.read_rows(out / "labels.jsonl")[0]
    L.append_row(out / "labels.jsonl", dict(row, cond_id="bad"))
    with pytest.raises(ValueError):
        R.load_session(out)


# ---------------------------------------------------------------------------------- DSP

@pytest.mark.parametrize("snr", [20, 10, 5, 0, -5])
def test_snr_mixing_math_exact(snr):
    take = np.concatenate([np.zeros(FS // 2), sine(220, 0.5, amp=0.1), np.zeros(FS // 2)]).astype(np.float32)
    bg = white_noise(len(take), rms_target=0.02, seed=1)
    mixed, info = R.mix_deterministic(take, FS, bg, FS, snr, seed=123)
    assert not info["clipped"]
    added = mixed.astype(np.float64) - take
    assert abs(20 * np.log10(R.active_rms(take, FS) / R.rms(added)) - snr) < 0.1


def test_mixing_seeded_determinism_and_int_float_steps():
    take = np.concatenate([np.zeros(FS // 2), sine(220, 0.5, 0.1), np.zeros(FS // 2)]).astype(np.float32)
    bg = white_noise(len(take) * 2, rms_target=0.02, seed=2)
    a, _ = R.mix_deterministic(take, FS, bg, FS, 5.0, seed=999)
    assert np.array_equal(a, R.mix_deterministic(take, FS, bg, FS, 5.0, seed=999)[0])
    assert not np.array_equal(a, R.mix_deterministic(take, FS, bg, FS, 0.0, seed=999)[0])
    assert R.mix_seed(0, "t", "fan", 5) == R.mix_seed(0, "t", "fan", 5.0)   # --snr parses floats
    assert R.mix_seed(0, "t", "fan", 5) != R.mix_seed(1, "t", "fan", 5)


def test_mixing_clips_like_an_adc_and_never_rescales():
    take = sine(220, 1.0, amp=0.9)
    bg = white_noise(len(take), rms_target=0.1, seed=3)
    mixed, info = R.mix_deterministic(take, FS, bg, FS, -5, seed=1)
    assert info["clipped"] > 0 and np.max(np.abs(mixed)) <= 1.0
    want = take + info["gain"] * bg    # same length: the slice is the whole background
    inside = np.abs(want) < 0.99
    assert np.allclose(mixed[inside], want[inside], atol=1e-6)


def test_mixing_resamples_the_background_to_the_take_rate():
    take = sine(440, 0.5, amp=0.1, rate=48000)
    bg = white_noise(16000 * 2, rms_target=0.02, seed=4)
    mixed, _ = R.mix_deterministic(take, 48000, bg, 16000, 10, seed=1)
    assert len(mixed) == len(take)
    assert abs(20 * np.log10(R.active_rms(take, 48000) / R.rms(mixed - take)) - 10) < 0.2


def test_estimate_snr_subtracts_the_noise_power():
    pre = white_noise(FS, rms_target=0.01, seed=5)
    x = np.concatenate([pre, sine(440, 0.4, amp=0.2) + white_noise(int(FS * .4), 0.01, 6),
                        white_noise(FS // 2, 0.01, 7)]).astype(np.float32)
    assert R.estimate_snr(x, FS, 1000) == pytest.approx(20 * np.log10((0.2 / np.sqrt(2)) / 0.01), abs=0.3)
    assert R.estimate_snr(np.zeros(FS * 2, np.float32), FS, 1000) is None


# ---------------------------------------------------------------------------------- scoring

def test_label_scoring_combos_and_exact_sequence():
    session = {"takes": [
        {"take_id": "a", "block": "combos", "expect": ["click", "click"], "cond": DISCRETE, "cond_id": "x"},
        {"take_id": "b", "block": "combos", "expect": ["click", "hiss"], "cond": DISCRETE, "cond_id": "x"},
        {"take_id": "c", "block": "contours", "expect": ["rise"], "cond": CENTRE, "cond_id": "y"}]}
    events = {"a": [ev("click"), ev("click")], "b": [ev("hiss"), ev("click")], "c": [ev("fall")]}
    lab = R.check_labels(session, events, None)
    assert lab["recall"]["per_gesture"]["click"] == {"correct": 3, "total": 3, "recall": 1.0}   # never above 1
    assert lab["recall"]["per_gesture"]["rise"]["recall"] == 0.0
    assert lab["recall"]["overall"] == pytest.approx(4 / 5, abs=1e-4)
    assert lab["exact"]["per_sequence"]["click click"]["recall"] == 1.0
    assert lab["exact"]["per_sequence"]["click hiss"]["recall"] == 0.0   # heard hiss click: the app acts otherwise
    assert lab["confusion"]["rise"] == {"fall": 1}


def test_level_gate_mirrors_the_apps_calibration_steps():
    joy = json.loads(R.JOY_SPEC.read_text())
    session = {"takes": [
        {"take_id": "click", "block": "discrete", "expect": ["click"], "cond": DISCRETE, "bg": None},
        {"take_id": "soft", "block": "discrete", "expect": ["click"], "cond": dict(DISCRETE, loud="soft"), "bg": None},
        {"take_id": "hiss", "block": "discrete", "expect": ["hiss"], "cond": DISCRETE, "bg": None},
        {"take_id": "pop", "block": "discrete", "expect": ["pop"], "cond": DISCRETE, "bg": None}]}
    events = {
        # the clicks step takes any pop/click/hiss up to max_dur_ms (the strongest), not a longer one
        "click": [ev("hiss", 18, -35, 120), ev("click", 30, -20, joy["calib_v2"]["clicks"]["max_dur_ms"] + 1)],
        "soft": [ev("click", 6, -50)],            # soft/across takes are not a calibration: ignored
        "hiss": [ev("click", 40, -15), ev("hiss", 22, -32, 200)],   # the hiss step takes only hiss
        "pop": [ev("pop", 35, -18), ev("unknown", 50, -10)]}
    gate = R.derive_level_gate(session, events, joy)
    want = R.J.derive_gate({"clicks": [ev("hiss", 18, -35, 120)["example"]], "hiss": [ev("hiss", 22, -32, 200)["example"]],
                            "pops": [ev("pop", 35, -18)["example"]]}, None, joy)
    assert {k: gate[k] for k in want} == want
    assert gate["examples"] == {"pops": 1, "clicks": 1, "hiss": 1}
    assert gate["min_snr_db"] == pytest.approx(18 - joy["level_gate"]["margin_snr_db"])
    # no centre click: the spec default, like the app before its clicks step
    assert R.derive_level_gate({"takes": session["takes"][1:]}, events, joy)["from"] == "default"


ROOM_TID = "room-room-r1"


def room_audio(hum_hz: float | None = None) -> np.ndarray:
    """The room take as the recorders store it: 1 s pre-roll + the 3.5 s fixed window + 0.5 s post-roll of a quiet
    floor; [hum_hz] adds a 1 s steady hum inside the window (a voice / music: the app's "not quiet")."""
    x = white_noise(5 * FS, 0.002, seed=3)
    if hum_hz:
        x[2 * FS:3 * FS] += sine(hum_hz, 1.0, 0.1)
    return x


def room_session(root: Path, hum_hz: float | None = None) -> dict:
    return R.load_session(build(root, {ROOM_TID: room_audio(hum_hz)}))


def test_room_step_mirrors_the_apps_room_step(private):
    joy = json.loads(R.JOY_SPEC.read_text())
    g = joy["level_gate"]
    session = room_session(private)
    assert [t["quiet"] for t in session["takes"]] == [True]
    examples = {"clicks": [ev("click", 18, -35)["example"]], "hiss": [], "pops": []}
    win = joy["calib_v2"]["room"]["window_ms"]

    def at(t_ms, e):
        return dict(e, t_start_ms=t_ms)
    events = {ROOM_TID: [at(500, ev("hiss", 30, -20)),            # before GO (the pre-roll): not the room step's
                         at(2000, ev("click", 12, -40)),          # the loudest SNR in the window
                         at(2500, ev("pop", 9, -38)),             # the loudest level in the window (taken separately)
                         at(2600, ev("unknown", 40, -10)),        # not a gate label
                         at(1000 + win + 1, ev("click", 30, -15))]}  # after the window
    rs = R.room_step(session, events, examples, joy)
    assert rs["status"] == "ok" and rs["room"]["transients"] == 2
    assert (rs["room"]["transient_snr_db"], rs["room"]["transient_level_dbfs"]) == (12, -38)
    assert rs["room"]["floor_dbfs"] == pytest.approx(20 * np.log10(0.002), abs=3)
    gate = R.J.derive_gate(examples, rs["room"], joy)
    # the room raises the gate to its loudest transient + room_margin_db (SNR 12 + 3 over 18 - 8)
    assert gate["min_snr_db"] == 12 + g["room_margin_db"] > 18 - g["margin_snr_db"]
    # ... but never above the weakest example - cap_below_weakest_db (-38 + 3 = -35 is capped to -36)
    assert gate["min_level_dbfs"] == min(-38 + g["room_margin_db"], -35 - g["cap_below_weakest_db"]) == -36
    # as loud as the weakest calibrated example (both SNR and level): the app fails the step -> no room
    loud = {ROOM_TID: [at(2000, ev("click", 16, -34))]}
    assert R.room_step(session, loud, examples, joy)["status"] == "too loud"
    assert "room" not in R.room_step(session, loud, examples, joy)
    # a quiet room without transients: ok, the floor only (the gate is not raised)
    assert R.room_step(session, {ROOM_TID: []}, examples, joy)["room"]["transient_snr_db"] is None
    # no room take (a session from before the room step)
    assert R.room_step({"takes": []}, {}, examples, joy) == {"status": "absent"}


def test_room_step_fails_on_a_steady_tone(private):
    joy = json.loads(R.JOY_SPEC.read_text())
    rs = R.room_step(room_session(private, hum_hz=150.0), {ROOM_TID: []}, {"clicks": []}, joy)
    assert rs["status"] == "not quiet"
    assert rs["max_voiced_run_ticks"] >= joy["calib_v2"]["room"]["max_voiced_run_ticks"]


def test_level_gate_uses_the_room_take(private):
    joy = json.loads(R.JOY_SPEC.read_text())
    session = room_session(private)
    session["takes"].insert(0, {"take_id": "click", "block": "discrete", "expect": ["click"], "cond": DISCRETE,
                                "bg": None})
    events = {"click": [ev("click", 18, -35)], ROOM_TID: [dict(ev("click", 12, -40), t_start_ms=2000)]}
    gate = R.derive_level_gate(session, events, joy)
    assert gate["room"]["status"] == "ok" and gate["min_snr_db"] == 15.0
    events[ROOM_TID] = []
    assert R.derive_level_gate(session, events, joy)["min_snr_db"] == 10.0


def test_report_room_caveat_only_without_a_room_take(private):
    rng = np.random.default_rng(7)
    takes = {tid("discrete", "click", DISCRETE): make_gesture("click", rng)}
    without = R.run_session(build(private, takes, name="old"), opts())
    assert without["gate"]["room"]["status"] == "absent"
    assert any("no room step" in n for n in without["notes"])
    with_room = R.run_session(build(private, dict(takes, **{ROOM_TID: room_audio()}), name="new"), opts())
    assert with_room["gate"]["room"]["status"] == "ok"
    assert not any("room" in n for n in with_room["notes"])
    # the room take is not a gesture take: not in the label or keep-rate scoring
    assert with_room["labels"]["n_takes"] == without["labels"]["n_takes"] == 1
    assert ROOM_TID not in {t["take_id"] for t in with_room["gates"]["own"]["per_take"]}
    assert "room step: ok" in (private / "new" / "report.md").read_text()
    failed = R.run_session(build(private, dict(takes, **{ROOM_TID: room_audio(150.0)}), name="hum"), opts())
    assert failed["gate"]["room"]["status"] == "not quiet"
    assert any("failed the app's room step" in n for n in failed["notes"])


def test_would_act_and_gate_keep():
    gate = {"min_snr_db": 10, "min_level_dbfs": -40, "from": "calibration"}
    assert R.gate_keep(gate, ev("click", 12, -30)) and not R.gate_keep(gate, ev("click", 8, -30))
    assert R.gate_keep(gate, ev("rise", 1, -60))   # contours are never level-gated
    assert not R.would_act(gate, ev("unknown", 30, -10))
    assert R.would_act(gate, ev("click", 12, -30))


# ---------------------------------------------------------------------------------- end to end

def test_recall_known_outcome_and_report(private):
    out = standard(private)
    rep = R.run_session(out, opts())
    lab = rep["labels"]
    assert lab["n_takes"] == 4
    for g in ("rise", "fall", "click", "hiss"):
        assert lab["recall"]["per_gesture"][g]["recall"] == 1.0, g
    assert lab["recall"]["overall"] == 1.0
    for exp, row in lab["confusion"].items():
        assert set(row) == {exp}, f"{exp} confused as {row}"
    saved = json.loads((out / "report.json").read_text())
    for key in ("version", "session", "speaker", "profile", "device", "spec", "generated", "cpp", "range", "gate",
                "gate_from", "labels", "gates", "mixing", "real_vs_mix", "app_replay", "ratings", "notes", "layout"):
        assert key in saved, key
    assert saved["gate"]["from"] == "calibration" and saved["gate"]["examples"]["clicks"] == 1
    assert set(saved["gates"]) == {"own"} and saved["gate_from"] is None
    assert saved["ratings"][0]["block"] == "contours"
    assert (out / "report.md").read_text().startswith("# range suite")
    assert any("SYNTHETIC" in n for n in saved["notes"])
    assert not (out / "mix-cache").exists()   # no derived audio copies


def test_reports_only_in_private_folders(private, monkeypatch):
    out = standard(private)

    def refuse(path):
        raise ValueError("use a private session")
    monkeypatch.setattr(L, "private_dir", refuse)
    with pytest.raises(ValueError, match="private"):
        R.run_session(out, opts())
    assert not (out / "report.json").exists()


def test_backgrounds_mixing_and_real_vs_mix(private):
    import synth
    rng = np.random.default_rng(11)
    bg = synth.background(rng, "pink", FS * 60, FS).astype(np.float32)
    bg *= 0.01 / R.rms(bg)
    click = make_gesture("click", rng)
    shot = make_gesture("click", rng)
    shot = shot * (0.2 / R.active_rms(shot, FS))
    tail = shot[FS // 2: FS // 2 + FS]
    real = np.concatenate([bg[:FS], tail + bg[FS:2 * FS], bg[:FS // 2]]).astype(np.float32)
    out = build(private, {tid("discrete", "click", DISCRETE): click,
                          tid("real-media-60", "click", DISCRETE): real}, {"media-60": bg})
    rep = R.run_session(out, opts(snr=[20, 0]))
    m = rep["mixing"]
    assert m["n_mixes"] == 2 and m["snr_steps"] == [20.0, 0.0]   # only the clean take is mixed
    assert set(m["recall_vs_snr"]["media"]) == {"20", "0"}
    assert set(m["keep_vs_snr"]) == {"own"}
    bgs = rep["gates"]["own"]["backgrounds"]
    assert bgs[0]["name"] == "media-60" and bgs[0]["seconds"] == pytest.approx(60)
    rv = rep["real_vs_mix"]
    row = rv["rows"][0]
    assert row["counterparts"] == 1 and row["nearest_snr_db"] in (20.0, 0.0) and row["est_snr_db"] is not None
    assert rv["per_bg"]["media-60"]["n_real"] == 1 and rv["per_bg"]["media-60"]["n_mix"] == 1
    assert rv["verdict"] in ("representative", "not representative")


def test_gate_from_another_session_and_summary_by_speaker(private):
    mine = standard(private, name="mine")
    sis = standard(private, name="sis", speaker="sis", profile="short")
    strict = {"session": str(mine), "speaker": "self", "device": "desktop",
              "gate": {"min_snr_db": 200.0, "min_level_dbfs": 0.0, "from": "calibration", "n": 1}}
    rep = R.run_session(sis, opts(), gate_from=strict)
    assert rep["speaker"] == "sis" and rep["profile"] == "short"
    assert set(rep["gates"]) == {"own", "from"}
    keep = rep["gates"]["from"]["keep_rate"]["per_gesture"]
    assert keep["click"]["recall"] == 0.0 and keep["rise"]["recall"] == 1.0   # contours are never level-gated
    assert rep["gates"]["own"]["keep_rate"]["per_gesture"]["click"]["recall"] == 1.0
    summary = R.summarize([R.run_session(mine, opts()), rep])
    assert set(summary) == {"self", "sis"}
    assert summary["sis"]["desktop"]["keep"]["from"]["click"]["recall"] == 0.0
    # the same cond_id in both profiles: comparable cell for cell
    assert set(summary["sis"]["desktop"]["per_cond_id"]) == set(summary["self"]["desktop"]["per_cond_id"])


def test_cli_gate_from_and_summary_out(private, capsys):
    mine = standard(private, name="mine")
    sis = standard(private, name="sis", speaker="sis", profile="short")
    assert R.main([str(sis), "--gate-from", str(mine), "--no-cpp", "--summary-out", str(private / "summary")]) == 0
    assert "| sis | desktop |" in capsys.readouterr().out
    summary = json.loads((private / "summary" / "summary.json").read_text())
    assert summary["sis"]["desktop"]["keep"]["from"]
    assert json.loads((sis / "report.json").read_text())["gate_from"]["speaker"] == "self"
    with pytest.raises(ValueError, match="private"):
        R.main([str(sis), "--no-cpp", "--summary-out", str(L.HERE / "tests")])


# ---------------------------------------------------------------------------------- app replay safety

def test_emulator_refusal():
    with pytest.raises(ValueError, match="R5CX62H7PNJ"):
        R.check_device("R5CX62H7PNJ", 5038, 7789)
    with pytest.raises(ValueError, match="5037"):
        R.check_device("emulator-5580", 5037, 7789)
    with pytest.raises(ValueError, match="7788"):
        R.check_device("emulator-5580", 5038, 7788)
    with pytest.raises(ValueError, match="emulator only"):
        R.check_device("SOMEPHONE123", 5038, 7789)
    R.check_device("emulator-5580", 5038, 7789)


def test_cli_refuses_the_phone_before_reading_anything():
    with pytest.raises(ValueError, match="7788"):
        R.main(["/nonexistent", "--emulator", "--socket-port", "7788"])
    with pytest.raises(ValueError, match="5037"):
        R.main(["/nonexistent", "--emulator", "--adb-port", "5037"])


def test_replay_pcm_is_full_scale_pcm16():
    pcm, rate = R.replay_pcm(np.array([[0.5], [-0.5], [1.0], [-1.0]]), 48000)
    assert rate == 48000
    assert np.frombuffer(base64.b64decode(pcm), "<i2").tolist() == [16384, -16384, 32767, -32768]
    _, rate = R.replay_pcm(np.zeros((4410, 1)), 44100)
    assert rate == 16000   # mic_feed takes 16000 | 48000


def test_app_replay_pins_the_emulator_and_reads_decisions(private, monkeypatch):
    out = standard(private)
    sys.path.insert(0, str(R.NF_DIR))
    import voxlib
    seen = {}

    class FakeStream:
        def __init__(self):
            self.events = []

        def mark(self):
            return len(self.events)

        def since(self, mark):
            return self.events[mark:]

        def close(self):
            pass

    stream = FakeStream()

    class FakeVox:
        def __init__(self):
            seen.update(serial=voxlib.SERIAL, port=voxlib.SOCKET_PORT, adb=os.environ["ANDROID_ADB_SERVER_PORT"])

        def control(self, op, **kw):
            assert op == "mic_feed" and kw["deliver"] and kw["rate"] == FS
            assert np.abs(np.frombuffer(base64.b64decode(kw["pcm_b64"]), "<i2")).max() > 100   # not silence
            stream.events += [{"ev": "decision", "action": "swipe_up"}, {"ev": "exec", "action": "swipe_up"}]
            return {"ok": True}

        def close(self):
            pass

    monkeypatch.setattr(voxlib, "Vox", FakeVox)
    monkeypatch.setattr(voxlib, "EventStream", lambda: stream)
    for k in ("ANDROID_ADB_SERVER_PORT", "VOX_SERIAL", "VOX_SOCKET_PORT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(voxlib, "SOCKET_PORT", 7788)   # voxlib's own default is the phone's host port
    res = R.check_app_replay(R.load_session(out), "emulator-5580", 5038, 7789, settle_s=0)
    assert seen == {"serial": "emulator-5580", "port": 7789, "adb": "5038"}
    assert [r["actions"] for r in res["rows"]] == [["swipe_up"]] * 4   # decisions only, not exec
    assert res["rows"][0]["match"] and not res["rows"][1]["match"]    # rise -> swipe_up; fall is not


def test_expected_action_mapping():
    assert R.expected_action(["rise"]) == "swipe_up"
    assert R.expected_action(["click", "click"]) == "home"
    assert R.expected_action(["pop", "pop"]) == "none"
