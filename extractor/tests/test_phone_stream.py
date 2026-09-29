"""Phone-as-a-microphone streaming (contract P) and the twin (two-mic) range recorder.

Everything is SYNTHETIC: a fake debug-socket server on 127.0.0.1 (a free port) serves contract P over
generated audio, with injectable loss and restart. No device, no adb, no model API, never zflip/.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import phone_stream as PS
import range_layout as L
import range_session as D
import range_suite as R

FS = 16000
PRIVATE = L.HERE.parent / "android" / ".state"


@pytest.fixture
def private():
    """A private folder under android/.state (gitignored), removed afterwards."""
    PRIVATE.mkdir(parents=True, exist_ok=True)
    d = Path(tempfile.mkdtemp(prefix="range-twin-", dir=PRIVATE))
    yield d
    shutil.rmtree(d, ignore_errors=True)


def write_wav(path: Path, x: np.ndarray, rate: int = FS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.clip(np.asarray(x, dtype=np.float32), -1, 1)
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((data * 32767).astype("<i2").tobytes())


class FakePcmServer(threading.Thread):
    """A contract-P debug socket server over generated audio.

    `realtime=True` advances the frame counter with wall time (`speed` x), for a live round;
    `realtime=False` advances `step` frames per pcm_read, for deterministic unit tests. `drop_at` /
    `restart_at` inject a ring overflow / a capture restart at a given pcm_read index.
    """

    def __init__(self, rate: int = FS, realtime: bool = True, speed: float = 1.0, step: int = 800,
                 ring_s: float = 12.0) -> None:
        super().__init__(daemon=True)
        self.rate = rate
        self.realtime = realtime
        self.speed = speed
        self.step = step
        self.ring = int(ring_s * rate)
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.sock.listen(1)
        self.gen = 1
        self.sid = 0
        self.head = 0
        self.ring_start = 0
        self.drop_at: dict[int, tuple[int, int]] = {}
        self.restart_at: set[int] = set()
        self.reads = 0
        self.t0 = None

    def run(self) -> None:
        conn, _ = self.sock.accept()
        f = conn.makefile("rw", encoding="utf-8", newline="\n")
        self.t0 = time.monotonic()
        while True:
            line = f.readline()
            if not line:
                break
            rep = self.handle(json.loads(line))
            f.write(json.dumps(rep) + "\n")
            f.flush()

    def _now(self) -> int:
        return int((time.monotonic() - self.t0) * self.rate * self.speed) if self.realtime else self.head

    def handle(self, msg: dict) -> dict:
        op = msg["op"]
        if op == "pcm_open":
            self.sid += 1
            return {"ok": True, "sid": self.sid, "rate": self.rate, "gen": self.gen,
                    "frame": self._now(), "mic": "fake-mic", "source": "fake-server"}
        if op == "pcm_read":
            if self.reads in self.restart_at:
                self.reads += 1
                self.gen += 1
                return {"ok": False, "error": "capture restarted", "gen": self.gen}
            from_ = msg["from"]
            self.reads += 1
            if not self.realtime:
                self.head += self.step
            if self.reads in self.drop_at:
                _, b = self.drop_at[self.reads]
                self.ring_start = max(self.ring_start, b)
            end = self._now()
            start = max(self.ring_start, end - self.ring)
            lost = max(0, start - from_)
            a = max(from_, start)
            to = min(end, from_ + int(2 * self.rate))
            return {"ok": True, "sid": msg["sid"], "gen": self.gen, "rate": self.rate,
                    "from": from_, "to": to, "start": start, "end": end,
                    "lost_frames": lost, "b64": base64.b64encode(self._pcm(a, to)).decode()}
        if op == "pcm_close":
            return {"ok": True, "frames_sent": self.head}

    def _pcm(self, a: int, b: int) -> bytes:
        n = b - a
        if n <= 0:
            return b""
        t = (np.arange(n) + a) / self.rate
        x = (0.5 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
        return (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def drain(src: PS.PhoneStreamSource, blocks: int, timeout: float = 3.0) -> list[np.ndarray]:
    out = []
    deadline = time.monotonic() + timeout
    while len(out) < blocks and time.monotonic() < deadline:
        b = src.read()
        if b is None:
            break
        if b.size:
            out.append(b)
    return out


# ---------------------------------------------------------------------------------- the source


def test_source_zero_fill_and_loss_bookkeeping():
    server = FakePcmServer(realtime=False, step=800)
    server.drop_at[2] = (800, 900)  # on the 2nd pcm_read the ring no longer holds [800, 900)
    server.start()
    src = PS.PhoneStreamSource(port=server.port, poll_s=0.01)
    src.start()
    blocks = drain(src, 6)
    src.stop()
    while not src.q.empty():
        blocks.append(src.q.get_nowait())
    assert len(blocks) >= 6
    total = sum(b.size for b in blocks)
    assert total == src._n                    # the sample clock never jumps
    # the drop on read 1: the source zero-filled [800, 900) and recorded it
    assert (800, 900) in src.lost
    # the zero-filled region is exactly zeros in the second block
    assert np.all(blocks[1][:100] == 0)
    assert np.any(blocks[1][100:] != 0)


def test_source_restart_reopens_and_keeps_clock():
    server = FakePcmServer(realtime=False, step=800)
    server.restart_at = {3}   # the 4th pcm_read answers 'capture restarted'
    server.start()
    src = PS.PhoneStreamSource(port=server.port, poll_s=0.01)
    src.start()
    blocks = drain(src, 8)
    src.stop()
    while not src.q.empty():
        blocks.append(src.q.get_nowait())
    assert len(blocks) >= 6
    assert src.restarts                   # a restart happened
    # the stream re-opened with a new sid and kept emitting continuous audio
    assert src.error is None
    assert sum(b.size for b in blocks) == src._n


# ---------------------------------------------------------------------------------- clock + xcorr


def test_fit_offset_lower_envelope():
    rate = 16000
    t0, latency = 1000.0, 0.02
    arrivals = []
    for n in range(0, 10 * rate, rate // 10):
        jitter = (n // rate) % 5 * 0.005          # latency only grows, never shrinks below `latency`
        arrivals.append((t0 + n / rate + latency + jitter, n))
    off = PS.fit_offset(arrivals, rate)
    assert off is not None
    assert abs(off - (t0 + latency)) < 1e-6       # the minimum recent value = t0 + latency
    # n/rate + off recovers the true host time within the jitter floor
    for t, n in arrivals[-5:]:
        assert 0.0 <= (t - (n / rate + off)) < 0.03


def test_xcorr_recovers_a_known_lag():
    rate = 16000
    rng = np.random.default_rng(0)
    n = rate
    desk = np.zeros(n, np.float32)
    desk[rate // 4: rate // 2] = rng.normal(0, 0.2, rate // 4).astype(np.float32)
    lag = 0.030
    phone = np.concatenate([np.zeros(int(lag * rate), np.float32), desk[:-int(lag * rate)]])
    lag_ms, peak = PS.xcorr_lag(desk, rate, phone, rate)
    assert abs(lag_ms - 30.0) < 1.0               # within one 10 ms envelope hop
    assert peak > PS.X_CORR_THRESHOLD


# ---------------------------------------------------------------------------------- the twin round


def test_twin_phone_auto_round(private, monkeypatch):
    server = FakePcmServer(realtime=True, speed=1.0)
    server.start()
    monkeypatch.setenv("VOX_SOCKET_PORT", str(server.port))
    out = private / "range-twin-desk"
    twin_out = private / "range-twin-desk-phone"
    args = SimpleNamespace(spec=L.SPEC_PATH, session="range-twin-desk", profile="short", speaker="self",
                           out=out, block=["range"], source="fake", device=None, rate=None, auto=True,
                           fake_speed=1.0, twin_phone=True, twin_out=twin_out)
    D.run_session(args)
    server.close()
    desk = L.validate_session(out)
    phone = L.validate_session(twin_out)
    assert desk["takes"] == 4 and phone["takes"] == 4
    dm = json.loads((out / "session.json").read_text())
    pm = json.loads((twin_out / "session.json").read_text())
    assert dm["twin"] == twin_out.name and pm["twin"] == out.name
    assert pm["device"] == "phone" and pm["recorder"] == "pc-stream"
    # the phone's take rows carry an align block, and go_offset_ms == pre_roll exactly
    for r in L.take_rows(twin_out / "labels.jsonl").values():
        assert "align" in r and r["align"]["method"] in ("xcorr", "clock")
        assert abs(r["go_offset_ms"] - L.load_spec()["analysis"]["pre_roll_s"] * 1000) < 1e-6


class StubRec:
    def __init__(self, rate, arrivals, buf):
        self.rate, self.arrivals, self.buf = rate, arrivals, np.asarray(buf, dtype=np.float32)

    def audio(self, a, b):
        return self.buf[max(0, a):min(len(self.buf), b)]


def test_dropped_phone_take():
    rate = 16000
    desk_arrivals = [(1000.0 + n / rate + 0.01, n) for n in range(0, 10 * rate, rate // 10)]
    phone_arrivals = [(1000.0 + m / rate + 0.02, m) for m in range(0, 10 * rate, rate // 10)]
    desk = StubRec(rate, desk_arrivals, np.zeros(10 * rate))
    phone = StubRec(rate, phone_arrivals, np.zeros(10 * rate))
    src = PS.PhoneStreamSource(port=1)
    go, end = 80000, 80000 + 32000   # 5 s in, 2 s of gesture
    # no loss: a take is produced
    src.lost, src.restarts = [], []
    win = PS.phone_take_window(desk, phone, src, go, end, 1.0)
    assert win is not None
    clip, a, go_p, align = win
    assert clip.size == end - go + round(1.0 * rate)
    # a loss inside the window -> dropped (None)
    src.lost = [(70000, 70010)]
    assert PS.phone_take_window(desk, phone, src, go, end, 1.0) is None
    # a restart inside the window -> dropped
    src.lost = []
    src.restarts = [go_p]
    assert PS.phone_take_window(desk, phone, src, go, end, 1.0) is None


# ---------------------------------------------------------------------------------- the twin section


def _twin_pair(private):
    spec = L.load_spec()
    desk = private / "twin-desk"
    phone = private / "twin-phone"
    L.open_session(desk, spec, "desktop", "fake (SYNTHETIC)", FS, 1, True, profile="short", speaker="self",
                   twin="twin-phone")
    L.open_session(phone, spec, "phone", "phone: fake-mic (pc stream)", FS, 1, True, profile="short",
                   speaker="self", recorder="pc-stream", twin="twin-desk")
    rng = np.random.default_rng(7)
    import synth
    plan = {t["take_id"]: t for t in L.build_plan(spec, profile="short") if t["kind"] == "takes"}
    picks = [tid for tid, t in plan.items()
             if t["block"] in ("contours", "discrete") and not t.get("quiet")
             and len(t.get("expect") or []) == 1][:3]
    for tid in picks:
        t = plan[tid]
        x = synth.make_clip(t["expect"][0], rng, FS, 20.0, "pink").audio
        row = L.label_row(t, 0, 0, 1000, len(x), FS)
        write_wav(desk / row["file"], x)
        L.append_row(desk / "labels.jsonl", row)
        prow = dict(row, align=dict(offset_ms=20.0, lag_ms=0.0, peak=0.0, method="clock"))
        write_wav(phone / row["file"], x)
        L.append_row(phone / "labels.jsonl", prow)
    for b in ("contours", "discrete"):
        for out in (desk, phone):
            L.append_row(out / "ratings.jsonl", dict(block=b, rating=3, note="", seconds=0, redos=0))
    return desk, phone


def test_twin_section_in_range_suite(private):
    desk, phone = _twin_pair(private)
    argv = [str(desk), str(phone), "--summary-out", str(private / "summary")]
    R.main(argv)
    md = (desk / "report.md").read_text()
    assert "twin mics" in md
    assert "twin-phone" in md
    j = json.loads((desk / "report.json").read_text())
    assert j["twin_section"]["n_takes"] == 3
    assert j["twin_section"]["align"]["methods"] == {"xcorr": 0, "clock": 3}
    # the summary shows desktop then phone on adjacent rows
    smd = (private / "summary" / "summary.md").read_text()
    assert smd.index("desktop") < smd.index("phone")
