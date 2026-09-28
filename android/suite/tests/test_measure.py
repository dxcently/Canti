import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import wave

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import measure
import nearfield as nf


@pytest.fixture(autouse=True)
def isolated_processes_and_git(monkeypatch, tmp_path):
    # Tests must never invoke adb/git, even when the host's temp directory is a worktree.
    monkeypatch.setattr(measure.subprocess, "run", lambda *a, **k: pytest.fail("unmocked subprocess"))
    exists = Path.exists
    monkeypatch.setattr(Path, "exists", lambda p: False if p.name == ".git" and
                        not p.is_relative_to(tmp_path) else exists(p))


def wav_bytes(audio, rate=16000):
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setparams((audio.shape[1], 2, rate, 0, "NONE", "not compressed"))
        wav.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
    return out.getvalue()


@pytest.fixture
def recording(tmp_path):
    events = Path(__file__).with_name("fixtures") / "measure-events.jsonl"
    (tmp_path / "events.jsonl").write_bytes(events.read_bytes())
    t = np.arange(160000) / 16000
    x = 0.2 * np.sin(2 * np.pi * 150 * t)
    (tmp_path / "synthetic").mkdir()
    (tmp_path / "synthetic" / "audio.wav").write_bytes(wav_bytes(np.column_stack((x, x * 10**(-6 / 20)))))
    return tmp_path


def test_low_band_highpass():
    rate = 16000
    t = np.arange(rate) / rate
    near = np.sin(2 * np.pi * 150 * t) + 0.2 * np.sin(2 * np.pi * 1000 * t)
    spectrum = np.fft.rfft(near)
    spectrum[np.fft.rfftfreq(len(near), 1 / rate) < 300] = 0
    speaker = np.fft.irfft(spectrum)
    assert nf.low_band_ratio(near, rate) > 0.9
    assert nf.low_band_ratio(speaker, rate) < 0.01


def test_stereo_template_and_gate(recording):
    rows, _ = nf.load(recording)
    assert rows[0]["ild_db"] == pytest.approx(6, abs=0.02)
    assert rows[0]["tmpl_ratio"] == 0.5
    assert rows[0]["tmpl_distance"] == 2
    assert rows[1]["tmpl_ratio"] is None
    assert rows[0]["gate_lf_ratio"] == 0.8
    assert rows[0]["history_ms"] == 2000


def test_mono_and_no_history():
    x = np.ones((1600, 1)) * 0.1
    event = dict(t_start_ms=1000, t_end_ms=1050, gate={"level_db":-20}, tmpl={"distance":1, "threshold":0})
    result = nf.features(x, 16000, dict(wav_t0_ms=1000), event)
    assert result["ild_db"] is None
    assert result["level_above_floor_db"] is None
    assert result["tmpl_ratio"] is None
    assert result["clip_truncated"]


def test_level_floor():
    x = np.ones((48000, 1)) * 0.01
    x[2200 * 16:2500 * 16] = 0.1   # the event itself, 20 dB over the floor; gate.level_db is not used
    result = nf.features(x, 16000, {"wav_t0_ms":0},
                         dict(t_start_ms=2200, t_end_ms=2500, gate={"level_db":-20}))
    assert result["floor_10_db"] == pytest.approx(-40)
    assert result["level_above_floor_db"] == pytest.approx(20)


def test_envelope():
    rate = 16000
    t = np.arange(rate) / rate
    env = np.interp(t, [0, .1, .3, .7, .8, 1], [0, 0, 1, 0.1, 0, 0])
    x = env * np.sin(2 * np.pi * 1000 * t)
    onset, decay = nf.envelope_times(x, rate)
    assert onset == pytest.approx(160, abs=10)
    assert decay == pytest.approx(400, abs=10)
    assert nf.envelope_times(np.zeros(100), rate) == (None, None)
    assert nf.envelope_times(np.ones(1000), rate) == (None, None)


@pytest.mark.parametrize("t,expected", [(899,"media"), (900,"user"), (2500,"user"), (2501,"media")])
def test_label_edges(t, expected):
    prompts = [{"t_ms":1000, "n":1}]
    assert nf.label("3-media-30", t, prompts)[0] == expected
    assert nf.label("1-media-30", t, prompts)[0] == "media"
    assert nf.label("2-user-rise", t, prompts)[0] == "user"


def test_custom_window_and_unknown_phase():
    assert nf.label("3-media-30", 1400, [{"t_ms":1000}], -300, 300)[0] == "media"
    with pytest.raises(ValueError):
        nf.label("unknown", 0, [])


def test_offset_cut():
    x = np.arange(100).reshape(-1, 1)
    np.testing.assert_array_equal(nf.cut(x, 1000, 5000, 5020, 5040), x[20:40])
    assert len(nf.cut(x, 1000, 5000, 4800, 4900)) == 0
    assert len(nf.cut(x, 1000, 5000, 4900, 5020)) == 20
    assert len(nf.cut(x, 1000, 5000, 5200, 5300)) == 0


@pytest.mark.parametrize("event,expected", [({},True), ({"dropped":None, "gated":None},True),
    ({"dropped":"below level gate"},False), ({"dropped":"touch"},False), ({"dropped":"calibrating"},False),
    ({"dropped":"dry_run"},True), ({"gated":"pop under 14 dB over the floor"},False),
    ({"dropped":"joystick (a hum moves the cursor)"},False), ({"gated":"hiss centroid 7000 Hz"},False)])
def test_would_act(event, expected):
    assert nf.would_act(event) is expected


def test_prompt_recall_and_exposure(recording):
    # A prompt whose reaction window runs past the WAV's end (20000 ms) is not counted as a miss.
    path = recording / "events.jsonl"
    path.write_text(path.read_text().replace('{"ev":"measure_stop"',
        '{"ev":"measure_prompt","sid":"synthetic","n":3,"gesture":"rise","t_ms":19000}\n{"ev":"measure_stop"'))
    rows, groups = nf.load(recording)
    assert len(groups["30"]["prompts"]) == 2
    assert groups["30"]["media_minutes"] == pytest.approx((10000 - 1600 - (20000 - 17900)) / 60000)
    assert nf.score(rows, groups["30"], [r["would_act"] for r in rows]) == (0, 50)
    assert nf.verdict(0, 50) == "NO-GO"
    assert nf.verdict(1, 90) == "GO"
    assert nf.verdict(None, 100) == "NO-GO"
    assert nf.window_ms([{"t_ms":1000}, {"t_ms":1200}], 0, 2000, -100, 1500) == 1100


def test_analysis_csv_and_sweep(recording, capsys):
    nf.analyze(recording, steps=3)
    output = capsys.readouterr().out
    assert "best AND:" in output and "NO-GO" in output
    assert "low_band_ratio >=" in output and "low_band_ratio <=" in output
    assert "gate_lf_ratio" in (recording / "features.csv").read_text()


def test_missing_features_reject():
    assert not nf.rule_mask([dict(would_act=True, ild_db=None)], ("ild_db", ">=", 0))[0]


def test_bad_wav(recording):
    p = recording / "synthetic" / "audio.wav"
    p.write_bytes(p.read_bytes()[:-2])
    with pytest.raises(ValueError, match="truncated"):
        nf.load(recording)


@pytest.mark.parametrize("ignored", [True, False])
def test_output_git_check(tmp_path, monkeypatch, ignored):
    (tmp_path / ".git").write_text("gitdir: irrelevant")
    calls = []
    def run(args, **kw):
        calls.append((args, kw))
        return SimpleNamespace(returncode=0 if ignored else 1)
    monkeypatch.setattr(measure.subprocess, "run", run)
    dest = tmp_path / "data"
    if ignored:
        assert measure.output_dir(dest) == dest
    else:
        with pytest.raises(ValueError, match="not gitignored"):
            measure.output_dir(dest)
    assert calls[0][0] == ["git", "check-ignore", "-q", "--", str(dest) + "/"]


def test_output_outside_and_symlink(tmp_path, monkeypatch):
    monkeypatch.setattr(measure.subprocess, "run", lambda *a, **k: pytest.fail("unexpected git"))
    assert measure.output_dir(tmp_path / "new") == tmp_path / "new"
    (tmp_path / "alias").symlink_to(tmp_path / "new")
    assert measure.output_dir(tmp_path / "alias") == tmp_path / "new"


class FakeVox:
    def __init__(self, running=False):
        self.calls = []
        self.running = running

    def control(self, op, **kw):
        self.calls.append((op, kw))
        if op == "measure_status":
            return dict(running=self.running)
        return dict(ok=True, sid="synthetic")


def mock_pull(monkeypatch, recording, bad_size=False, rotated=b"", stored=b"synthetic\n"):
    events = (recording / "events.jsonl").read_bytes()
    data = (recording / "synthetic" / "audio.wav").read_bytes()
    def adb(*args, **kwargs):
        if len(args) == 2:
            assert args[0] == "exec-out" and args[1].startswith(f"run-as {measure.APP} sh -c '")
            return {"cat files/events.1.jsonl": rotated, "cat files/events.jsonl": events,
                    "ls files/measure": stored}[args[1].split("'")[1].removesuffix(" 2>/dev/null; true")]
        assert args[:3] == ("exec-out", "run-as", measure.APP)
        if args[3] == "stat":
            return str(len(data) + int(bad_size))
        return data
    monkeypatch.setattr(measure, "adb", adb)
    monkeypatch.setattr(measure.shutil, "disk_usage", lambda _: SimpleNamespace(free=100 * 1024**3))


def test_pull_verified_then_clear(recording, tmp_path, monkeypatch):
    mock_pull(monkeypatch, recording)
    vox = FakeVox()
    out = tmp_path / "export"
    assert measure.pull(vox, out, clear=True) == ["synthetic"]
    assert (out / "synthetic" / "audio.wav").read_bytes() == (recording / "synthetic" / "audio.wav").read_bytes()
    assert vox.calls[-1][0] == "measure_clear"


def test_pull_bad_size_never_clear(recording, tmp_path, monkeypatch):
    mock_pull(monkeypatch, recording, bad_size=True)
    vox = FakeVox()
    with pytest.raises(ValueError, match="size mismatch"):
        measure.pull(vox, tmp_path / "export", clear=True)
    assert all(op != "measure_clear" for op, _ in vox.calls)


def test_pull_running_refused(tmp_path):
    with pytest.raises(RuntimeError, match="stop recording"):
        measure.pull(FakeVox(True), tmp_path)


def test_pull_low_disk(recording, tmp_path, monkeypatch):
    mock_pull(monkeypatch, recording)
    monkeypatch.setattr(measure.shutil, "disk_usage", lambda _: SimpleNamespace(free=30 * 1024**3))
    with pytest.raises(RuntimeError, match="30 GiB"):
        measure.pull(FakeVox(), tmp_path / "export")


def test_plan():
    phases = measure.plan()
    assert len(phases) == 11
    assert [p["max_s"] for p in phases[:3]] == [60] * 3
    assert [p["takes"] for p in phases[3:8]] == [10] * 5
    assert [p["gestures"][0] for p in phases[3:8]] == measure.GESTURES
    assert [p["max_s"] for p in phases[8:]] == [90] * 3
    assert len(measure.plan(True)) == 13


@pytest.mark.parametrize("interrupt", [False, True])
def test_run_stop_on_abort(monkeypatch, interrupt):
    monkeypatch.setattr("builtins.input", lambda _: "")
    def wait(*args):
        if interrupt:
            raise KeyboardInterrupt
        return False
    monkeypatch.setattr(measure, "wait_phase", wait)
    vox = FakeVox()
    assert measure.run(vox, measure.plan()) == ["synthetic"]
    assert [op for op, _ in vox.calls] == ["measure_status", "measure_start", "measure_stop"]
    start = vox.calls[1][1]
    assert start["record"] and start["every_ms"] == 5000


def test_run_q_before_start(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "q")
    vox = FakeVox()
    assert measure.run(vox, measure.plan()) == []
    assert [op for op, _ in vox.calls] == ["measure_status"]


def fake_clock(monkeypatch, step=0.5):
    now = [0.0]
    def tick():
        now[0] += step
        return now[0]
    monkeypatch.setattr(measure.time, "monotonic", tick)


def test_wait_tenth_prompt(monkeypatch):
    fake_clock(monkeypatch)
    monkeypatch.setattr(measure.select, "select", lambda *args: ([], [], []))
    statuses = iter([dict(running=True, sid=7, prompts=n, seconds=n * 5) for n in range(1, 11)] +
                    [dict(running=True, sid=7, prompts=10, seconds=50)] * 3)
    vox = SimpleNamespace(control=lambda _: next(statuses))
    assert measure.wait_phase(vox, "7", 55, 10)


def test_wait_capture_abort(monkeypatch):
    fake_clock(monkeypatch)
    monkeypatch.setattr(measure.select, "select", lambda *args: ([], [], []))
    vox = SimpleNamespace(control=lambda _: dict(running=False))   # a stopped session has no sid
    with pytest.raises(RuntimeError, match="before the planned"):
        measure.wait_phase(vox, "s", 60)


def test_wait_max_s_end(monkeypatch):
    # The app stopped the timed phase at max_s: status is only {running: false}; that is the normal end.
    fake_clock(monkeypatch, step=20)
    monkeypatch.setattr(measure.select, "select", lambda *args: ([], [], []))
    statuses = iter([dict(running=True, sid=3, prompts=0, seconds=20)] * 2 + [dict(running=False)])
    assert measure.wait_phase(SimpleNamespace(control=lambda _: next(statuses)), "3", 60)


@pytest.mark.parametrize("running", [False, True])
def test_stop_after_self_end(running):
    vox = SimpleNamespace(control=lambda op, **kw: dict(ok=False, error="no measurement running")
                          if op == "measure_stop" else dict(running=running))
    if running:
        with pytest.raises(RuntimeError, match="still running"):
            measure.stop(vox)
    else:
        measure.stop(vox)


def test_sessions_last_block_int_sid():
    lines = [b'{"ev":"measure_start","sid":1,"phase":"old"}', b'{"ev":"mic_sound","sid":1,"t_start_ms":5}',
             b'{"ev":"measure_stop","sid":1,"samples":1}', b'{"ev":"unrelated"}',
             b'{"ev":"measure_prompt","sid":1,"n":0}', b'{"ev":"measure_start","sid":1,"phase":"new"}',
             b'{"ev":"measure_stop","sid":1,"samples":2}', b'{"ev":"measure_start","sid":2}', b'{"ev":"mic_so']
    blocks = measure.sessions(lines)
    assert list(blocks) == ["1"]   # sid 2 never stopped
    assert blocks["1"] == lines[4:7]   # the prompt logged before its (first-sample) start is kept


@pytest.mark.parametrize("sid", ["../x", "", "a/b", "$(bad)", True, None, 1.5])
def test_safe_sid(sid):
    with pytest.raises(ValueError):
        measure.safe_sid(sid)
    assert measure.safe_sid(12) == "12"


def test_pull_default_keeps_device_files(recording, tmp_path, monkeypatch):
    mock_pull(monkeypatch, recording)
    vox = FakeVox()
    measure.pull(vox, tmp_path / "export")
    assert all(op != "measure_clear" for op, _ in vox.calls)


def test_pull_clear_orphan_refused(recording, tmp_path, monkeypatch):
    # A stored recording that is not being pulled blocks --clear (it deletes everything).
    mock_pull(monkeypatch, recording, stored=b"synthetic\norphan\n")
    vox = FakeVox()
    with pytest.raises(ValueError, match="ALL recordings"):
        measure.pull(vox, tmp_path / "export", sids=["synthetic"], clear=True)
    assert all(op != "measure_clear" for op, _ in vox.calls)


def test_pull_default_orphan_unverifiable(recording, tmp_path, monkeypatch):
    # By default every stored recording is pulled; one without logged start/stop cannot be verified.
    mock_pull(monkeypatch, recording, stored=b"synthetic\norphan\n")
    vox = FakeVox()
    with pytest.raises(ValueError, match="missing start/stop"):
        measure.pull(vox, tmp_path / "export", clear=True)
    assert all(op != "measure_clear" for op, _ in vox.calls)


def test_pull_event_filter(recording, tmp_path, monkeypatch):
    path = recording / "events.jsonl"
    path.write_text(path.read_text() + '\n{"ev":"unrelated"}\n{"ev":"mic_sound","sid":"other"}\n')
    mock_pull(monkeypatch, recording)
    out = tmp_path / "export"
    measure.pull(FakeVox(), out)
    assert all(json.loads(line)["sid"] == "synthetic" for line in (out / "events.jsonl").read_text().splitlines())


def test_pull_reads_rotated_log(recording, tmp_path, monkeypatch):
    lines = (recording / "events.jsonl").read_bytes().splitlines(keepends=True)
    (recording / "events.jsonl").write_bytes(b"".join(lines[3:]))
    mock_pull(monkeypatch, recording, rotated=b"".join(lines[:3]))
    out = tmp_path / "export"
    measure.pull(FakeVox(), out)
    assert len((out / "events.jsonl").read_text().splitlines()) == len(lines)


def test_nearfield_int_sid(recording):
    path = recording / "events.jsonl"
    path.write_text(path.read_text().replace('"sid":"synthetic"', '"sid":4'))
    (recording / "synthetic").rename(recording / "4")
    rows, _ = nf.load(recording)
    assert {r["sid"] for r in rows} == {"4"}


def test_pull_sample_mismatch(recording, tmp_path, monkeypatch):
    path = recording / "events.jsonl"
    path.write_text(path.read_text().replace('"samples":160000', '"samples":1'))
    mock_pull(monkeypatch, recording)
    with pytest.raises(ValueError, match="sample count mismatch"):
        measure.pull(FakeVox(), tmp_path / "export")


def test_pull_refuses_existing_files(recording, tmp_path, monkeypatch):
    mock_pull(monkeypatch, recording)
    with pytest.raises(ValueError, match="not empty"):
        measure.pull(FakeVox(), recording)


def test_start_failure_attempts_stop(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "")
    vox = FakeVox()
    original = vox.control
    def control(op, **kw):
        if op == "measure_start":
            raise ConnectionError("lost reply")
        return original(op, **kw)
    vox.control = control
    with pytest.raises(ConnectionError):
        measure.run(vox, measure.plan())
    assert vox.calls[-1][0] == "measure_stop"


def test_wait_q(monkeypatch):
    monkeypatch.setattr(measure.sys, "stdin", io.StringIO("q\n"))
    monkeypatch.setattr(measure.select, "select", lambda *a: ([measure.sys.stdin], [], []))
    vox = FakeVox()
    assert not measure.wait_phase(vox, "s", 60)
    assert vox.calls == []


def test_report_go_and_and(capsys):
    rows = []
    for i in range(10):
        rows.append(dict(sid="s", prompt_n=i, volume="30", label="user", would_act=True,
                         **{f:1 for f in nf.FEATURES}))
    rows.append(dict(sid="s", prompt_n=None, volume="30", label="media", would_act=True,
                     **{f:0 for f in nf.FEATURES}))
    nf.report(rows, {"30":dict(media_minutes=1, prompts={("s", i) for i in range(10)})}, steps=2)
    output = capsys.readouterr().out
    assert "| GO |" in output
    assert "best AND:" in output


def test_missing_stop_refused(recording):
    path = recording / "events.jsonl"
    path.write_text("\n".join(line for line in path.read_text().splitlines() if "measure_stop" not in line))
    with pytest.raises(ValueError, match="missing stop"):
        nf.load(recording)
