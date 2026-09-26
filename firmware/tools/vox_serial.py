"""USB serial link to the VOX node: text console lines plus the binary frames of `mic stream`.

Frame (firmware out.h): b"VX" | type (1) | seq u16 LE | len u16 LE | payload | crc16 u16 LE
crc16 = CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) over type..payload.
Types: b"A" = PCM16 LE mono 16 kHz audio, b"T" = one console text line.
Outside `mic stream` the console is plain text lines ending in CRLF.

Used by ble_check.py and pico_stream.py. Needs pyserial.
"""

from __future__ import annotations

import queue
import threading
import time

import serial

MAGIC = b"VX"


def crc16(data: bytes, crc: int = 0xFFFF) -> int:
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


class Parser:
    """Feed bytes; yields ("line", str) and ("frame", type, seq, payload) items. Tolerates garbage."""

    def __init__(self) -> None:
        self.buf = bytearray()
        self.crc_errors = 0

    def feed(self, data: bytes):
        self.buf += data
        out = []
        while self.buf:
            if self.buf[:2] == MAGIC:
                if len(self.buf) < 7:
                    break
                typ, seq, n = self.buf[2], self.buf[3] | self.buf[4] << 8, self.buf[5] | self.buf[6] << 8
                if typ in (ord("A"), ord("T")) and n <= 4096:
                    if len(self.buf) < 7 + n + 2:
                        break
                    body = bytes(self.buf[2:7 + n])
                    crc = self.buf[7 + n] | self.buf[8 + n] << 8
                    if crc16(body) == crc:
                        out.append(("frame", chr(typ), seq, bytes(self.buf[7:7 + n])))
                        del self.buf[:9 + n]
                        continue
                    self.crc_errors += 1
            # plain text up to the next newline (or up to a possible frame start)
            nl = self.buf.find(b"\n")
            vx = self.buf.find(MAGIC, 1)
            if nl < 0 and vx < 0:
                if len(self.buf) > 8192:
                    self.buf.clear()
                break
            if vx >= 0 and (nl < 0 or vx < nl):
                text = bytes(self.buf[:vx])
                del self.buf[:vx]
                if text.strip():
                    out.append(("line", text.decode("utf-8", "replace").strip()))
                continue
            line = bytes(self.buf[:nl])
            del self.buf[:nl + 1]
            out.append(("line", line.decode("utf-8", "replace").rstrip("\r")))
        return out


class VoxSerial:
    """Background reader. `lines` gets (t, text) for console lines (plain or 'T' frames); audio frames go to
    `on_audio(seq, payload)` if set, and are counted."""

    def __init__(self, port: str = "/dev/ttyACM0", echo: bool = False) -> None:
        self.ser = serial.Serial(port, 115200, timeout=0.05)
        self.lines: queue.Queue = queue.Queue()
        self.log: list[tuple[float, str]] = []
        self.echo = echo
        self.parser = Parser()
        self.on_audio = None
        self.audio_frames = 0
        self.audio_seq_gaps = 0
        self._last_seq = None
        self._stop = False
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def _run(self) -> None:
        while not self._stop:
            try:
                data = self.ser.read(4096)
            except serial.SerialException:
                if self._stop:
                    return
                time.sleep(0.2)
                continue
            if not data:
                continue
            t = time.perf_counter()
            for item in self.parser.feed(data):
                if item[0] == "line":
                    self._line(t, item[1])
                    continue
                # one sequence counter for all frame types ('A' audio and 'T' text), so a gap = a lost frame
                seq = item[2]
                if self._last_seq is not None and seq != (self._last_seq + 1) & 0xFFFF:
                    self.audio_seq_gaps += 1
                self._last_seq = seq
                if item[1] == "T":
                    self._line(t, item[3].decode("utf-8", "replace"))
                else:
                    self.audio_frames += 1
                    if self.on_audio:
                        self.on_audio(seq, item[3])

    def _line(self, t: float, s: str) -> None:
        self.log.append((t, s))
        self.lines.put((t, s))
        if self.echo:
            print(f"  | {s}", flush=True)

    def cmd(self, s: str) -> float:
        """Send one console command; returns the perf_counter time just after the write was flushed."""
        self.ser.write((s + "\n").encode())
        self.ser.flush()
        return time.perf_counter()

    def drain(self) -> None:
        while not self.lines.empty():
            self.lines.get_nowait()

    def wait_for(self, pred, timeout: float = 3.0):
        """Wait for a console line with pred(line) true; returns (t, line) or None."""
        end = time.perf_counter() + timeout
        while True:
            left = end - time.perf_counter()
            if left <= 0:
                return None
            try:
                t, s = self.lines.get(timeout=left)
            except queue.Empty:
                return None
            if pred(s):
                return t, s

    def close(self) -> None:
        self._stop = True
        self._t.join(timeout=1)
        self.ser.close()
