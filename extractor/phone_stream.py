"""Live PCM streaming from the phone's mic over the app's debug socket (contract P, RANGE.md).

`PhoneStreamSource` is a `record.Source`: `start()` opens a `pcm_open` stream on a reader thread,
`read()` returns float32 mono blocks, `stop()` closes it with `pcm_close`. Lost frames (the ring
overflowed) and capture restarts are zero-filled so the sample clock stays continuous, and the
source records every lost range `[a, b)` in its own (continuous) frame numbers so a recorder can
refuse a take that lost audio.

The clock is mapped with the arrival stamps the reader keeps: `(time.monotonic() at reply, frames
received so far)`. `fit_offset` is the least-latency lower envelope of `t_arrival - n/rate` over the
last `window_s`; `xcorr_lag` refines a desk->phone mapping with a 10 ms energy-envelope
cross-correlation.

Connection settings are voxlib's (`range_phone.py`) env vars: VOX_SERIAL / ANDROID_ADB_SERVER_PORT /
VOX_SOCKET_PORT, defaulting to emulator-5580 / 5038 / 7789. The source connects to the *forwarded*
debug socket on 127.0.0.1:VOX_SOCKET_PORT (the operator, or `voxlib.Vox`, does the adb forward).
Importing this module connects to nothing.
"""
from __future__ import annotations

import base64
import json
import os
import queue
import socket
import threading
import time

import numpy as np

import record

# voxlib's connection defaults (range_phone.py). Merely setting these never touches a device.
os.environ.setdefault("VOX_SERIAL", "emulator-5580")
os.environ.setdefault("ANDROID_ADB_SERVER_PORT", "5038")
os.environ.setdefault("VOX_SOCKET_PORT", "7789")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_IDLE_MS = 5000.0
POLL_S = 0.05          # pcm_read is polled every 50 ms on the reader thread
X_CORR_THRESHOLD = 0.6  # normalized envelope correlation below which the clock mapping is kept


def socket_settings() -> tuple[str, int]:
    """(host, port) of the debug socket, from voxlib's env vars."""
    return DEFAULT_HOST, int(os.environ.get("VOX_SOCKET_PORT", "7789"))


class _Socket:
    """Newline-delimited JSON control channel to the app's debug socket."""

    def __init__(self, host: str, port: int) -> None:
        self.host, self.port = host, port
        self.sock: socket.socket | None = None
        self.file = None
        self.lock = threading.Lock()

    def connect(self) -> None:
        self.sock = socket.create_connection((self.host, self.port), timeout=5.0)
        self.file = self.sock.makefile("rw", encoding="utf-8", newline="\n")

    def control(self, op: str, **kw) -> dict:
        with self.lock:
            assert self.file is not None
            self.file.write(json.dumps({"type": "control", "op": op, **kw}) + "\n")
            self.file.flush()
            line = self.file.readline()
            if not line:
                raise ConnectionError("debug socket closed")
            return json.loads(line)

    def close(self) -> None:
        with self.lock:
            try:
                if self.sock is not None:
                    self.sock.close()
            finally:
                self.sock = None
                self.file = None


class PhoneStreamSource(record.Source):
    """The phone mic as a live mono float32 stream, zero-filled across loss/restarts.

    Frame numbers here are the app's continuous PCM frame counter (one mono sample each): `self.n`
    is both the next frame to request and the number of samples the source has emitted, so the
    clock never jumps — lost audio becomes zeros and the lost `[a, b)` ranges are recorded.
    """

    synthetic = False
    name = "phone"

    def __init__(self, host: str = DEFAULT_HOST, port: int | None = None, idle_ms: float = DEFAULT_IDLE_MS,
                 poll_s: float = POLL_S) -> None:
        self.host = host
        self.port = socket_settings()[1] if port is None else port
        self.idle_ms = idle_ms
        self.poll_s = poll_s
        self.rate = 0
        self.mic = ""
        self.source = ""
        self.q: queue.Queue = queue.Queue()          # float32 mono blocks, zero-filled for loss
        self.lost: list[tuple[int, int]] = []        # [a, b) zero-filled ranges, continuous frame numbers
        self.restarts: list[int] = []                # frame numbers where a capture restart happened
        self.arrivals: list[tuple[float, int]] = []  # (time.monotonic() at reply, frames received so far)
        self._lock = threading.Lock()
        self._sock = _Socket(host, self.port)
        self._sid: int | None = None
        self._gen = 0
        self._n = 0                                  # next frame to request / frames emitted
        self._done = threading.Event()
        self._thread: threading.Thread | None = None
        self.error: str | None = None

    # -- lifecycle -------------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return   # a Recorder re-starts its source; the stream is already open
        self._sock.connect()
        reply = self._sock.control("pcm_open", idle_ms=self.idle_ms)
        self._adopt(reply)
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def read(self) -> np.ndarray | None:
        try:
            return self.q.get(timeout=1.0)
        except queue.Empty:
            return np.zeros(0, np.float32)

    def stop(self) -> None:
        self._done.set()
        if self._sid is not None:
            try:
                self._sock.control("pcm_close", sid=self._sid)
            except (OSError, ConnectionError):
                pass
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._sock.close()

    # -- internals -------------------------------------------------------------
    def _adopt(self, reply: dict) -> None:
        """Record the stream's identity and first frame from a pcm_open reply."""
        if not reply.get("ok"):
            raise RuntimeError(f"pcm_open: {reply.get('error', reply)}")
        self._sid = reply["sid"]
        self._gen = reply["gen"]
        self.rate = reply["rate"]
        self.mic = reply.get("mic", "")
        self.source = reply.get("source", "")
        self._n = reply["frame"]

    def _record_lost(self, a: int, b: int) -> None:
        if b > a:
            with self._lock:
                self.lost.append((a, b))

    def _reader(self) -> None:
        try:
            while not self._done.is_set():
                try:
                    reply = self._sock.control("pcm_read", **{"sid": self._sid, "from": self._n})
                except (OSError, ConnectionError) as e:
                    self._fail(f"{type(e).__name__}: {e}")
                    return
                if not reply.get("ok"):
                    if reply.get("error") == "capture restarted":
                        self._reopen(reply.get("gen"))
                        continue
                    self._fail(reply.get("error", reply))
                    return
                if reply.get("gen") != self._gen:
                    self._reopen(reply.get("gen"))
                    continue
                self._take_reply(reply)
        except Exception as e:  # surface any reader error to read()/stop()
            self._fail(f"{type(e).__name__}: {e}")

    def _take_reply(self, reply: dict) -> None:
        from_ = self._n
        to = reply["to"]
        start = reply.get("start", from_)
        data = np.frombuffer(base64.b64decode(reply["b64"]), dtype="<i2").astype(np.float32) / 32768.0
        n_zero = min(max(0, start - from_), to - from_)   # zero-fill the lost part of [from_, to)
        if n_zero > 0:
            self._record_lost(from_, from_ + n_zero)
        block = np.concatenate((np.zeros(n_zero, np.float32), data)) if n_zero > 0 else data
        with self._lock:
            self.arrivals.append((time.monotonic(), to))
            self._n = to
        self.q.put(block)

    def _reopen(self, gen) -> None:
        """A capture restart: zero-fill the gap to the new frame, then re-open (a new sid)."""
        old = self._n
        reply = self._sock.control("pcm_open", idle_ms=self.idle_ms)
        self._adopt(reply)
        with self._lock:
            self.restarts.append(old)
        self._record_lost(old, self._n)
        gap = self._n - old
        if gap > 0:
            with self._lock:
                self.arrivals.append((time.monotonic(), self._n))
            self.q.put(np.zeros(gap, np.float32))

    def _fail(self, message: str) -> None:
        with self._lock:
            self.error = message
        self._done.set()
        self.q.put(None)  # wake read() with end-of-stream

    def lost_overlaps(self, a: int, b: int) -> bool:
        """Whether any zero-filled/restart range intersects [a, b)."""
        with self._lock:
            return any(lo < b and hi > a for lo, hi in self.lost) or any(a <= f < b for f in self.restarts)


# ---------------------------------------------------------------------------------- clock mapping


def fit_offset(arrivals: list[tuple[float, int]], rate: int, window_s: float = 30.0) -> float | None:
    """The least-latency lower envelope: min(t_arrival - n/rate) over the last `window_s`.

    Each block's host arrival is `n/rate + latency`, and latency only grows (queueing/decimation), so
    the minimum recent value tracks the true offset and absorbs clock drift. None without arrivals.
    """
    if not arrivals:
        return None
    cut = arrivals[-1][0] - window_s
    recent = [(t, n) for t, n in arrivals if t >= cut] or [arrivals[-1]]
    return min(t - n / rate for t, n in recent)


def host_time_of(arrivals: list[tuple[float, int]], rate: int, n: int) -> float | None:
    off = fit_offset(arrivals, rate)
    return None if off is None else n / rate + off


def frame_of(arrivals: list[tuple[float, int]], rate: int, t: float) -> int | None:
    off = fit_offset(arrivals, rate)
    return None if off is None else int(round((t - off) * rate))


def envelope(x: np.ndarray, rate: int, hop_s: float = 0.010) -> np.ndarray:
    """Mean power of consecutive 10 ms frames (the same definition range_suite uses)."""
    x = np.asarray(x, dtype=np.float64)
    hop = max(1, round(rate * hop_s))
    n = len(x) // hop
    return np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1) if n else np.zeros(0)


def xcorr_lag(desk: np.ndarray, desk_rate: int, phone: np.ndarray, phone_rate: int,
              search_ms: float = 150.0) -> tuple[float, float]:
    """The phone's lag behind the desk (ms) from 10 ms energy-envelope cross-correlation.

    Returns `(lag_ms, peak)`; `lag_ms > 0` means the phone lags the desk. `peak` is the normalized
    cross-correlation at the best lag (a caller's threshold decides whether to trust it).
    """
    de = envelope(desk, desk_rate)
    pe = envelope(phone, phone_rate)
    n = min(len(de), len(pe))
    if n < 2:
        return 0.0, 0.0
    de = de[:n] - de[:n].mean()
    pe = pe[:n] - pe[:n].mean()
    denom = float(np.sqrt(np.dot(de, de) * np.dot(pe, pe)))
    if denom <= 0:
        return 0.0, 0.0
    max_lag = max(1, int(round(search_ms / 10.0)))  # 10 ms envelope hop
    best_lag, best_peak = 0, -1.0
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            d, p = de[:n - lag], pe[lag:]
        else:
            d, p = de[-lag:], pe[:n + lag]
        if len(d) < 2:
            continue
        corr = float(np.dot(d, p) / denom)
        if corr > best_peak:
            best_peak, best_lag = corr, lag
    return best_lag * 10.0, best_peak


def phone_take_window(desk_rec, phone_rec, phone, go: int, end: int, pre_roll_s: float,
                      is_background: bool = False):
    """The phone window for a desk take `[go - pre_roll_s, end)` (a background has no pre-roll).

    Maps the desk GO to host time (`fit_offset`) then to a phone frame, refines that GO with
    `xcorr_lag` (takes only; a background keeps the clock mapping), and returns
    `(clip, start_frame, go_frame, align)` — or None if any frame of the window was lost or the
    stream restarted inside it. `align` is `{offset_ms, lag_ms, peak, method: 'xcorr'|'clock'}`
    where `offset_ms` is the clock-only phone-vs-desk offset (their fitted offsets' difference) and
    `lag_ms` the xcorr refinement (0 for `clock`).
    """
    desk_rate, phone_rate = desk_rec.rate, phone_rec.rate
    t_go = host_time_of(desk_rec.arrivals, desk_rate, go)
    if t_go is None:
        return None
    go_p = frame_of(phone_rec.arrivals, phone_rate, t_go)
    if go_p is None:
        return None
    pre = 0 if is_background else round(pre_roll_s * phone_rate)
    post = round((end - go) * phone_rate / desk_rate)
    a0, b0 = go_p - pre, go_p + post
    lag_ms, peak, method = 0.0, 0.0, "clock"
    if not is_background:
        desk_clip = desk_rec.audio(go - round(pre_roll_s * desk_rate), end)
        phone_clip0 = phone_rec.audio(a0, b0)
        lag_ms, peak = xcorr_lag(desk_clip, desk_rate, phone_clip0, phone_rate)
        if peak >= X_CORR_THRESHOLD:
            go_p += round(lag_ms * phone_rate / 1000)
            method = "xcorr"
        else:
            lag_ms = 0.0
    a, b = go_p - pre, go_p + post
    if phone.lost_overlaps(a, b):
        return None
    clip = phone_rec.audio(a, b)
    if clip.size != b - a:
        return None
    offset_d = fit_offset(desk_rec.arrivals, desk_rate)
    offset_p = fit_offset(phone_rec.arrivals, phone_rate)
    offset_ms = None if (offset_d is None or offset_p is None) else round((offset_p - offset_d) * 1000, 3)
    align = dict(offset_ms=offset_ms, lag_ms=round(lag_ms, 3), peak=round(peak, 6), method=method)
    return clip, a, go_p, align
