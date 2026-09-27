#!/usr/bin/env python3
"""End-to-end check of the VOX node's BLE link from this PC (BlueZ + bleak), driven over USB serial.

It checks the firmware against android/PROTOCOL.md "BLE GATT link (v1)" and the Python extractor:
  - scan by the service UUID; name VOX-XXXX = last 2 bytes of the address; GATT layout and properties
  - INFO: JSON with v, fw, mic, fp_version (+ insecure:true on a debug build)
  - secure build: an unencrypted link cannot use CONFIG/EVENT; LE Secure Connections Just Works pairing works
  - subscribe to EVENT, reassemble the fragments ([header][chunk]: bit 7 last, bit 6 first, 6-bit counter), and for EVERY
    message check: valid JSON, PROTOCOL fields and types, ids +1, device timing rules
  - every canned sound (serial `send`): line and label identical to the extractor's (tests/test_sounds.json,
    regenerated from the extractor), byte-identical to vox_extract.protocol.message(), passes the extractor's strict
    line parser; timing t_end - t_start = the extracted duration, t_end = the device's send time
  - sequences: one message per sound, device-clock gaps exact, arrival spacing follows the device clock
  - arm / pause / stop / mode messages; nothing is sent while paused or stopped
  - CONFIG writes (known key applied, unknown keys ignored; long write at MTU 23); every write gets exactly one
    no-sound reply with a fresh id; a refused write (bad value, not an object, malformed) gets "rejected" and changes
    nothing
  - pairing gate (secure build): a new pairing is rejected outside the pairing window, accepted inside it (opened
    with `btn hold 5500`), and the window closes on the new bond; bonded reconnects work outside the window
  - app commands: armed / mode / both / no change, each confirmed by its state reply; sleep -> "sleeping":true, then
    the device drops the link
  - the button through the serial console (`btn ...`, the same state machine as the real button): 1 click = mode
    (after the series gap), 2-4 presses nothing, 5 presses arm / turn off / wake, hold 1 s = disarm at once then
    sleep on release, hold 5 s = pairing window (drops the link; a bonded phone may reconnect while it is open)
  - after a 5-press wake the reconnect's state-on-connect says armed:true; after an unexpected disconnect armed:false
  - full run only: no phone within 60 s of a 5-press wake -> sleep; the pairing window closing with no phone ->
    sleep, with a phone connected -> awake and disarmed
  - fragmentation: padded messages past the MTU up to the 4096-byte maximum, and a whole second pass at MTU 23; the counter wraps 63 -> 0
  - reconnect: the device disarms on disconnect; counter restarts at 0; the state message arrives again
  - latency serial `send` -> notification complete on the PC; USB mic stream + BLE at the same time
Captured messages -> tests/captured_messages.jsonl, numbers -> tests/ble_check_report.json.

Run (from firmware/):
  nix shell --impure --expr 'with import <nixpkgs> {}; python313.withPackages (p: [p.bleak p.pyserial])' \\
      -c python tools/ble_check.py [--quick] [-v]

The secure build needs pairing: this script registers its own BlueZ agent (NoInputNoOutput, for this process
only) and removes the bond again at the end (--keep-bond to keep it).
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import math
import re
import statistics
import subprocess
import sys
import time
import types
from dataclasses import dataclass, field
from pathlib import Path

from bleak import BleakClient, BleakScanner
from dbus_fast import BusType, Message, MessageType
from dbus_fast.aio import MessageBus

HERE = Path(__file__).resolve().parent
FIRMWARE = HERE.parent
VOX = FIRMWARE.parent
sys.path.insert(0, str(HERE))
from vox_serial import VoxSerial  # noqa: E402
from bluez_agent import NoIoAgent  # noqa: E402

SVC = "ac740001-3c66-cc47-6290-e0e7094c17b9"
EVENT = "ac740002-3c66-cc47-6290-e0e7094c17b9"
CONFIG = "ac740003-3c66-cc47-6290-e0e7094c17b9"
INFO = "ac740004-3c66-cc47-6290-e0e7094c17b9"
LABELS = {"rise", "fall", "arch", "dip", "flat", "pop", "click", "hiss", "unknown"}
STATE_KEYS = ["v", "id", "mode", "armed", "sounds", "sequence"]
SOUND_KEYS = ["v", "id", "mode", "armed", "sounds", "sequence", "timing", "phrase", "cursor"]


def load_extractor():
    """Import extractor/vox_extract/{lines,protocol,vocab}.py without its package __init__ (which needs numpy)."""
    pkg = types.ModuleType("vox_extract_lite")
    pkg.__path__ = [str(VOX / "extractor" / "vox_extract")]
    sys.modules["vox_extract_lite"] = pkg
    return (importlib.import_module("vox_extract_lite.lines"), importlib.import_module("vox_extract_lite.protocol"),
            importlib.import_module("vox_extract_lite.vocab"))


LINES, PROTOCOL, VOCAB = load_extractor()


# ------------------------------------------------------------------------------------------------ bookkeeping
class Checks:
    def __init__(self) -> None:
        self.results: list[tuple[str, bool, str]] = []

    def ok(self, name: str, cond: bool, detail: str = "") -> bool:
        self.results.append((name, bool(cond), detail))
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(': ' + detail) if detail else ''}", flush=True)
        return bool(cond)

    @property
    def failed(self) -> list:
        return [r for r in self.results if not r[1]]


@dataclass
class Msg:
    raw: bytes
    t_first: float
    t_last: float
    frags: int
    conn: int
    chunks: list = field(default_factory=list)

    @property
    def text(self) -> str:
        return self.raw.decode("utf-8")


class Reassembler:
    """The app's rule (PROTOCOL.md): a message starts at a fragment with bit 6 (first) and ends at one with bit 7
    (last); bits 0-5 count notifications mod 64 from 0 on each connection. A counter skip drops the partial message
    and waits for the next first-fragment. Header anomalies are counted so the checker can fail on them."""

    def __init__(self) -> None:
        self.q: asyncio.Queue = asyncio.Queue()
        self.conn = 0
        self.expect = None
        self.parts: list[bytes] | None = None
        self.t_first = 0.0
        self.first_ctr: dict[int, int] = {}
        self.gaps = 0
        self.bad_first = 0      # bit 6 set while a message was in progress, or missing at a message start
        self.frags = 0
        self.wraps = 0
        self.prev_ctr = None

    def new_connection(self) -> None:
        self.conn += 1
        self.expect = None
        self.prev_ctr = None
        self.parts = None

    def feed(self, data: bytes) -> None:
        t = time.perf_counter()
        hdr = data[0]
        ctr, first, last = hdr & 0x3F, bool(hdr & 0x40), bool(hdr & 0x80)
        self.frags += 1
        self.first_ctr.setdefault(self.conn, ctr)
        if self.expect is not None and ctr != self.expect:
            self.gaps += 1
            self.parts = None
        if self.prev_ctr == 63 and ctr == 0:
            self.wraps += 1
        self.prev_ctr = ctr
        self.expect = (ctr + 1) & 0x3F
        if first:
            if self.parts is not None:
                self.bad_first += 1
            self.parts = []
            self.t_first = t
        elif self.parts is None:
            self.bad_first += 1
            return
        self.parts.append(bytes(data[1:]))
        if last:
            self.q.put_nowait(Msg(b"".join(self.parts), self.t_first, t, len(self.parts), self.conn, list(self.parts)))
            self.parts = None


# ------------------------------------------------------------------------------------------------ the checker
class BleCheck:
    def __init__(self, a: argparse.Namespace) -> None:
        self.a = a
        self.c = Checks()
        self.ser = VoxSerial(a.port, echo=a.verbose)
        self.ra = Reassembler()
        self.sounds = json.loads((FIRMWARE / "tests" / "test_sounds.json").read_text())
        self.by_name = {s["name"]: s for s in self.sounds["sounds"]}
        self.captured: list[Msg] = []
        self.last_id = None
        self.last_t_end = None
        self.secure = True
        self.client: BleakClient | None = None
        self.device = None
        self.bus: MessageBus | None = None
        self.agent: NoIoAgent | None = None
        self.report: dict = {"phases": {}}
        self.phase = ""
        self.lat: dict[str, list[float]] = {}
        self.offsets: list[float] = []   # PC arrival (ms) - device t_end, per sound message
        self.dropped = asyncio.Event()   # set when the device drops the current link

    # ---------------- serial helpers
    def cmd(self, s: str) -> float:
        return self.ser.cmd(s)

    async def swait(self, pred, timeout: float = 3.0):
        return await asyncio.to_thread(self.ser.wait_for, pred, timeout)

    def device_log(self, pat: str) -> list[str]:
        r = re.compile(pat)
        return [s for _, s in self.ser.log if r.search(s)]

    def tx_time(self, msg_id: int) -> int | None:
        for _, s in reversed(self.ser.log):
            m = re.search(r"tx id=(\d+) .* at (\d+) ms", s)
            if m and int(m.group(1)) == msg_id:
                return int(m.group(2))
        return None

    # ---------------- BLE helpers
    async def next_msg(self, timeout: float = 3.0) -> Msg | None:
        try:
            m = await asyncio.wait_for(self.ra.q.get(), timeout)
        except asyncio.TimeoutError:
            return None
        self.captured.append(m)
        return m

    async def expect_none(self, secs: float = 1.0) -> bool:
        m = await self.next_msg(secs)
        return m is None

    async def scan(self):
        t0 = time.perf_counter()
        dev = await BleakScanner.find_device_by_filter(
            lambda d, ad: SVC in [u.lower() for u in ad.service_uuids], timeout=20)
        return dev, time.perf_counter() - t0

    async def connect(self):
        self.ra.new_connection()
        for attempt in range(3):
            if self.device is None:
                self.device, _ = await self.scan()
                if self.device is None:
                    continue
            try:
                self.dropped = asyncio.Event()
                self.client = BleakClient(self.device, timeout=20,
                                          disconnected_callback=lambda _c, ev=self.dropped: ev.set())
                await self.client.connect()
                return True
            except Exception as e:  # noqa: BLE001
                print(f"  connect attempt {attempt + 1} failed: {e!r}")
                self.device = None
                await asyncio.sleep(1)
        return False

    async def disconnect(self):
        """Like the app: unsubscribe, then disconnect. (Without the unsubscribe, BlueZ re-enables a bonded
        device's notifications by itself on the next connection, before bleak has a callback.)"""
        if self.client and self.client.is_connected:
            try:
                await asyncio.wait_for(self.client.stop_notify(EVENT), 5)
            except Exception:  # noqa: BLE001  (not subscribed)
                pass
            await self.client.disconnect()
        await asyncio.sleep(0.5)

    def dev_path(self) -> str:
        return "/org/bluez/hci0/dev_" + self.device.address.replace(":", "_")

    async def bluez_call(self, path, iface, member, sig="", body=None, timeout=30.0):
        msg = Message(destination="org.bluez", path=path, interface=iface, member=member, signature=sig,
                      body=body or [])
        reply = await asyncio.wait_for(self.bus.call(msg), timeout)
        return reply

    async def remove_bond(self):
        if self.device is None or self.bus is None:
            return
        r = await self.bluez_call("/org/bluez/hci0", "org.bluez.Adapter1", "RemoveDevice", "o", [self.dev_path()])
        print(f"  removed BlueZ device entry (bond) for {self.device.address}: "
              f"{'ok' if r.message_type != MessageType.ERROR else r.error_name}")

    # ---------------- per-message validation (every message)
    def validate(self, m: Msg, where: str) -> dict | None:
        try:
            d = json.loads(m.text)
        except Exception as e:  # noqa: BLE001
            self.c.ok(f"{where}: valid JSON", False, repr(e))
            return None
        errs = []
        if not isinstance(d, dict):
            errs.append("not an object")
            d = {}
        if d.get("v") != 1 or type(d.get("v")) is not int:
            errs.append(f"v={d.get('v')!r}")
        if type(d.get("id")) is not int:
            errs.append(f"id={d.get('id')!r}")
        if d.get("mode") not in ("gesture", "cursor", "listening"):
            errs.append(f"mode={d.get('mode')!r}")
        if type(d.get("armed")) is not bool:
            errs.append(f"armed={d.get('armed')!r}")
        snd, seq = d.get("sounds"), d.get("sequence")
        if not (isinstance(snd, list) and len(snd) <= 3 and all(isinstance(x, str) for x in snd)):
            errs.append("sounds")
            snd = []
        if not (isinstance(seq, list) and len(seq) == len(snd) and all(x in LABELS for x in seq)):
            errs.append("sequence")
        if "timing" in d:
            tm = d["timing"]
            if not (isinstance(tm, list) and len(tm) == len(snd)):
                errs.append("timing length")
            else:
                prev = None
                for e in tm:
                    if e is None:
                        continue
                    if not (isinstance(e, dict) and type(e.get("t_start_ms")) is int and type(e.get("t_end_ms")) is int):
                        errs.append("timing entry")
                        continue
                    if e["t_end_ms"] < e["t_start_ms"]:
                        errs.append("end before start")
                    if prev is not None and e["t_start_ms"] < prev:
                        errs.append("starts decrease")
                    prev = e["t_start_ms"]
        for k in ("phrase", "cursor"):
            if k in d and d[k] is not None and not isinstance(d[k], str):
                errs.append(k)
        if "sleeping" in d and (d["sleeping"] is not True or d.get("armed") is not False or snd):
            errs.append("sleeping must be true, only with armed:false and no sounds")
        if "rejected" in d and (not isinstance(d["rejected"], str) or not d["rejected"] or snd):
            errs.append("rejected must be a non-empty reason on a no-sound message")
        if "by" in d and (d["by"] != "button" or snd):
            errs.append('by must be "button", only on a no-sound state message')
        if "features" in d:
            errs.append("features present (fp1 is not final; the firmware must leave it out)")
        if snd:
            for line, lab in zip(snd, seq or []):
                try:
                    if not LINES.label_consistent(lab, LINES.parse_line(line)):
                        errs.append(f"label {lab} vs line")
                except Exception as e:  # noqa: BLE001
                    errs.append(f"strict parser: {e}")
        if self.last_id is not None and d.get("id") != self.last_id + 1:
            errs.append(f"id {d.get('id')} after {self.last_id} (expected +1)")
        if type(d.get("id")) is int:
            self.last_id = d["id"]
        if errs:
            self.c.ok(f"{where}: PROTOCOL fields", False, "; ".join(errs) + f" | {m.text[:160]}")
            return None
        return d

    # ---------------- expectations
    async def expect_state(self, command: str | None, mode: str, armed: bool, where: str,
                           extra: list | None = None, timeout: float = 3.0) -> Msg | None:
        """The next message must be exactly the no-sound state message, in PROTOCOL.md key order; `extra` =
        [(key, value)] placed after armed (sleeping, rejected). Returns the message if it matched."""
        if command:
            self.cmd(command)
        m = await self.next_msg(timeout)
        if not self.c.ok(f"{where}: state message arrives", m is not None):
            return None
        d = self.validate(m, where)
        if d is None:
            return None
        want = {"v": 1, "id": d["id"], "mode": mode, "armed": armed}
        for k, v in extra or []:
            want[k] = v
        want.update({"sounds": [], "sequence": []})
        want_s = json.dumps(want, separators=(",", ":"))
        desc = ", ".join(f"{k} {v}" for k, v in [("mode", mode), ("armed", armed)] + list(extra or []))
        return m if self.c.ok(f"{where}: exact no-sound message ({desc})", m.text == want_s, m.text) else None

    async def expect_sleeping(self, where: str, mode: str, timeout: float = 3.0) -> bool:
        """The "sleeping":true message, then the device drops the link, then it reports itself asleep."""
        m = await self.expect_state(None, mode, False, f"{where}: sleeping message", [("sleeping", True)], timeout)
        try:
            await asyncio.wait_for(self.dropped.wait(), 5)
            dropped = True
        except asyncio.TimeoutError:
            dropped = False
        self.c.ok(f"{where}: then the device drops the link",
                  dropped, f"{(time.perf_counter() - m.t_last) * 1000:.0f} ms after the message" if (dropped and m) else "")
        return await self.expect_power(f"{where}: device", "asleep") and m is not None and dropped

    async def expect_power(self, where: str, want: str, extra: str = "") -> bool:
        """`status` power line starts with "power: <want>" (and contains `extra`)."""
        await asyncio.sleep(0.3)
        self.ser.drain()
        self.cmd("status")
        st = await self.swait(lambda s: s.startswith("power:"), 3.0)
        line = st[1] if st else ""
        return self.c.ok(f"{where} is {want}{(' (' + extra + ')') if extra else ''}",
                         line.startswith(f"power: {want}") and extra in line, line)

    async def config(self, data: bytes) -> float:
        """One CONFIG write with response; returns its time in ms."""
        t0 = time.perf_counter()
        await asyncio.wait_for(self.client.write_gatt_char(CONFIG, data, response=True), 10)
        return (time.perf_counter() - t0) * 1000

    async def config_reply(self, data: bytes, mode: str, armed: bool, where: str, extra: list | None = None):
        """A CONFIG write and its one state reply (exact); returns ms from the write to the complete reply."""
        t0 = time.perf_counter()
        try:
            await self.config(data)
        except Exception as e:  # noqa: BLE001
            self.c.ok(f"{where}: CONFIG write {data!r}", False, repr(e))
            return None
        m = await self.expect_state(None, mode, armed, f"{where} {data.decode(errors='replace')}", extra)
        if m is None:
            return None
        ms = (m.t_last - t0) * 1000
        self.lat.setdefault("config_write_to_reply", []).append(ms)
        return ms

    def check_sound(self, m: Msg, entry: dict, mode: str, where: str, t_cmd: float | None) -> dict | None:
        d = self.validate(m, where)
        if d is None:
            return None
        tm = d.get("timing") or [None]
        ts, te = (tm[0] or {}).get("t_start_ms"), (tm[0] or {}).get("t_end_ms")
        want = PROTOCOL.message([{"text": entry["line"], "label": entry["label"], "t_start_ms": ts, "t_end_ms": te}],
                                d["id"], mode=mode, armed=True)
        exact = m.text == json.dumps(want, separators=(",", ":"))
        errs = []
        if d["sounds"] != [entry["line"]]:
            errs.append("line differs from the extractor's")
        if d["sequence"] != [entry["label"]]:
            errs.append("label differs")
        if not exact:
            errs.append("not byte-identical to vox_extract.protocol.message()")
        if ts is None or te - ts != entry["dur_ms"] and ts != 0:
            errs.append(f"duration {None if ts is None else te - ts} != extracted {entry['dur_ms']}")
        if self.last_t_end is not None and te is not None and te < self.last_t_end:
            errs.append(f"t_end {te} before the previous sound's {self.last_t_end}")
        if te is not None:
            self.last_t_end = te
            self.offsets.append(m.t_last * 1000.0 - te)
        tx = self.tx_time(d["id"])
        if tx is not None and te is not None and abs(tx - te) > 3 and where.endswith("single"):
            errs.append(f"t_end {te} vs device send time {tx}")
        if t_cmd is not None:
            self.lat.setdefault(f"{self.phase}:{entry['label']}", []).append((m.t_last - t_cmd) * 1000.0)
        self.c.ok(f"{where}: {entry['name']} ({m.frags} frag{'s' if m.frags > 1 else ''})", not errs, "; ".join(errs))
        return d

    # ---------------- test blocks
    async def suite(self, mtu: int) -> None:
        P = self.phase
        await self.expect_state("mode gesture", "gesture", False, f"{P} mode gesture")
        await self.expect_state("pause", "gesture", False, f"{P} pause")
        self.ser.drain()
        self.cmd("send rise")
        silent = await self.expect_none(1.0)
        said = await self.swait(lambda s: "not sent" in s, 1.0)
        self.c.ok(f"{P} paused: a sound is not sent", silent and said is not None, said[1] if said else "")
        await self.expect_state("arm", "gesture", True, f"{P} arm")

        for name in ["rise", "fall", "arch", "dip", "flat", "pop", "click", "hiss"]:
            t0 = self.cmd(f"send {name}")
            m = await self.next_msg(3.0)
            if self.c.ok(f"{P} send {name}: message arrives", m is not None):
                self.check_sound(m, self.by_name[name], "gesture", f"{P} single", t0)
            await asyncio.sleep(0.15)

        for q in self.sounds["sequences"] + [{"name": "rise fall 300", "sounds": [self.sounds["sounds"].index(
                self.by_name["rise"]), self.sounds["sounds"].index(self.by_name["fall"])], "gaps_ms": [300]}]:
            self.cmd(f"seq {q['name']}")
            got = []
            for k, idx in enumerate(q["sounds"]):
                m = await self.next_msg(4.0)
                if not self.c.ok(f"{P} seq {q['name']}: sound {k + 1} arrives", m is not None):
                    break
                d = self.check_sound(m, self.sounds["sounds"][idx], "gesture", f"{P} seq {q['name']}", None)
                got.append((m, d))
            if len(got) == len(q["sounds"]) and all(d for _, d in got):
                gaps = [got[k + 1][1]["timing"][0]["t_start_ms"] - got[k][1]["timing"][0]["t_end_ms"]
                        for k in range(len(got) - 1)]
                self.c.ok(f"{P} seq {q['name']}: device-clock gaps", gaps == q["gaps_ms"], f"{gaps} vs {q['gaps_ms']}")
                dev = [got[k + 1][1]["timing"][0]["t_end_ms"] - got[k][1]["timing"][0]["t_end_ms"]
                       for k in range(len(got) - 1)]
                arr = [(got[k + 1][0].t_last - got[k][0].t_last) * 1000 for k in range(len(got) - 1)]
                self.c.ok(f"{P} seq {q['name']}: separate messages, arrival spacing follows the device clock",
                          all(abs(x - y) < 80 for x, y in zip(dev, arr)),
                          f"device {dev} ms, arrival {[round(x) for x in arr]} ms")
            await asyncio.sleep(0.2)

        await self.expect_state("mode cursor", "cursor", True, f"{P} mode cursor")
        t0 = self.cmd("send pop")
        m = await self.next_msg(3.0)
        if self.c.ok(f"{P} cursor mode: sound arrives", m is not None):
            self.check_sound(m, self.by_name["pop"], "cursor", f"{P} cursor single", t0)
        await self.expect_state("mode gesture", "gesture", True, f"{P} back to gesture")
        await self.expect_state("stop", "gesture", False, f"{P} stop")
        self.cmd("send pop")
        self.c.ok(f"{P} stopped: a sound is not sent", await self.expect_none(1.0))
        await self.expect_state("arm", "gesture", True, f"{P} re-arm after stop")

        # fragmentation past the MTU with protocol-valid (whitespace-padded) messages, up to the 4096-byte maximum
        for size in (600, 4096):
            self.cmd(f"pad {size}")
            m = await self.next_msg(8.0)
            if self.c.ok(f"{P} padded {size}-byte message arrives", m is not None):
                d = self.validate(m, f"{P} padded")
                want_frags = math.ceil(size / (mtu - 4))
                self.c.ok(f"{P} padded: {len(m.raw)} bytes in {m.frags} fragments (expected {want_frags} at MTU {mtu})",
                          d is not None and len(m.raw) == size and m.frags == want_frags
                          and sorted(d) == sorted(STATE_KEYS),
                          f"chunk sizes {sorted({len(x) for x in m.chunks})}")
        self.cmd("pad 5000")
        m = await self.next_msg(8.0)
        self.c.ok(f"{P} `pad 5000` is capped at the 4096-byte maximum", m is not None and len(m.raw) == 4096
                  and self.validate(m, f"{P} padded cap") is not None, f"{len(m.raw) if m else None} bytes")

        # CONFIG: every write that reaches the firmware gets exactly one state reply
        payload = b'{"v":1,"test_sounds":true,"future_key":{"a":[1,2,"x}"]},"n":3}'
        self.ser.drain()
        ms = await self.config_reply(payload, "gesture", True, f"{P} CONFIG test_sounds + unknown keys "
                                     f"({len(payload)} B{', long write' if len(payload) > mtu - 3 else ''})")
        ok = await self.swait(lambda s: "trigger ON (CONFIG)" in s, 2.0)
        ign = self.device_log(r"ignoring unknown key 'n'")
        self.c.ok(f"{P} CONFIG: test_sounds applied, unknown keys ignored (write -> reply "
                  f"{ms if ms is None else round(ms)} ms)", ok is not None and bool(ign))
        await self.config_reply(b'{"test_sounds":false}', "gesture", True, f"{P} CONFIG")
        off = self.device_log(r"trigger off \(CONFIG\)")
        await self.config_reply(b"hello", "gesture", True, f"{P} CONFIG", [("rejected", "not a JSON object")])
        self.c.ok(f"{P} CONFIG: false applied; a non-JSON write is rejected (state unchanged)", bool(off))
        self.c.ok(f"{P} CONFIG: exactly one reply per write", await self.expect_none(0.4))

    async def latency(self, n: int, names=("pop", "flat")) -> None:
        for name in names:
            for _ in range(n):
                t0 = self.cmd(f"send {name}")
                m = await self.next_msg(3.0)
                if m is None:
                    self.c.ok(f"{self.phase} latency send {name}", False, "no message")
                    break
                self.check_sound(m, self.by_name[name], "gesture", f"{self.phase} latency", t0)
                await asyncio.sleep(0.12)

    async def stress(self, secs: float = 6.0) -> None:
        """USB mic stream (binary frames, ~33 kB/s) and BLE notifications at the same time."""
        P = self.phase
        f0, g0, c0 = self.ser.audio_frames, self.ser.audio_seq_gaps, self.ser.parser.crc_errors
        self.cmd("mic stream")
        await asyncio.sleep(0.5)
        t_start = time.perf_counter()
        n = 0
        while time.perf_counter() - t_start < secs:
            t0 = self.cmd("send pop")
            m = await self.next_msg(3.0)
            if m is None:
                self.c.ok(f"{P} stress: sound during mic stream", False, "no message")
                break
            self.phase = P + "+stream"
            self.check_sound(m, self.by_name["pop"], "gesture", f"{P} stress", t0)
            self.phase = P
            n += 1
            await asyncio.sleep(0.1)
        dt = time.perf_counter() - t_start
        self.cmd("mic off")
        await asyncio.sleep(0.5)
        frames = self.ser.audio_frames - f0
        rate = frames / (dt + 0.5)
        self.c.ok(f"{P} stress: {n} BLE messages while streaming audio over USB; {frames} audio frames "
                  f"(~{rate:.0f}/s, expect 100/s), seq gaps {self.ser.audio_seq_gaps - g0}, "
                  f"CRC errors {self.ser.parser.crc_errors - c0}",
                  n > 10 and 85 < rate < 115 and self.ser.audio_seq_gaps == g0 and self.ser.parser.crc_errors == c0)
        self.report["phases"].setdefault(P, {})["stress"] = {
            "ble_messages": n, "audio_frames": frames, "audio_frames_per_s": round(rate, 1),
            "seq_gaps": self.ser.audio_seq_gaps - g0, "crc_errors": self.ser.parser.crc_errors - c0}

    async def subscribe(self, expect_armed: bool, expect_mode: str) -> None:
        """Enable EVENT notifications; the device must answer with its current state, counter 0, first+last set."""
        P = self.phase
        t0 = time.perf_counter()
        await self.client.start_notify(EVENT, lambda _c, data: self.ra.feed(bytes(data)))
        m = await self.next_msg(3.0)
        if self.c.ok(f"{P}: state message as soon as EVENT notifications are enabled", m is not None,
                     f"{(m.t_last - t0) * 1000:.0f} ms after start_notify" if m else ""):
            d = self.validate(m, f"{P} subscribe")
            self.c.ok(f"{P}: it is a no-sound message with the current state (armed {expect_armed}, {expect_mode})",
                      d is not None and d["sounds"] == [] and d["armed"] is expect_armed and d["mode"] == expect_mode,
                      m.text)
        self.c.ok(f"{P}: fragment counter starts at 0 on a new connection", self.ra.first_ctr.get(self.ra.conn) == 0,
                  str(self.ra.first_ctr.get(self.ra.conn)))

    async def reconnect_check(self) -> None:
        """Disconnect while armed in cursor mode: the device disarms; on reconnect the counter restarts at 0 and the
        state message arrives again (armed false, mode kept)."""
        P = self.phase = "reconnect"
        print(f"\n== {P}", flush=True)
        await self.expect_state("mode cursor", "cursor", True, f"{P} setup: cursor")
        await self.disconnect()
        paused = await self.swait(lambda s: "pause" in s.lower() or "disarm" in s.lower(), 3.0)
        self.c.ok(f"{P}: a disconnect disarms the device", paused is not None, paused[1] if paused else "")
        if not self.c.ok(f"{P}: connect again (bonded: re-encryption, no new pairing)", await self.connect()):
            return
        n_pair = len(self.device_log(r"pairing started"))
        await self.subscribe(expect_armed=False, expect_mode="cursor")
        self.c.ok(f"{P}: no new pairing was needed", len(self.device_log(r"pairing started")) == n_pair)
        await self.expect_state("mode gesture", "gesture", False, f"{P} mode gesture")
        await self.expect_state("arm", "gesture", True, f"{P} arm")
        t0 = self.cmd("send rise")
        m = await self.next_msg(3.0)
        if self.c.ok(f"{P}: a sound after reconnect", m is not None):
            self.check_sound(m, self.by_name["rise"], "gesture", f"{P} single", t0)
        await self.expect_state("pause", "gesture", False, f"{P} pause")

    async def reconnect_after_wake(self, where: str, expect_armed: bool, mode: str = "gesture") -> bool:
        """Scan, connect (a bonded phone: re-encryption, no new pairing), subscribe; the state-on-connect message must
        say `expect_armed`."""
        self.device, _ = await self.scan()
        if not self.c.ok(f"{where}: the device advertises again and the bonded PC connects",
                         self.device is not None and await self.connect()):
            return False
        n_pair = len(self.device_log(r"pairing started"))
        await self.subscribe(expect_armed=expect_armed, expect_mode=mode)
        if self.secure:
            self.c.ok(f"{where}: bonded reconnect, no new pairing", len(self.device_log(r"pairing started")) == n_pair)
        return True

    async def power_checks(self) -> None:
        """App commands (CONFIG) and their replies, the button through `btn ...`, sleep and wake, the pairing window.
        Starts connected and subscribed, disarmed, gesture mode; ends the same way."""
        P = self.phase = "power"
        print(f"\n== {P}: app commands (CONFIG) and replies", flush=True)
        for data, mode, armed, extra in [
            (b'{"v":1,"armed":true}', "gesture", True, None),
            (b'{"v":1,"mode":"cursor"}', "cursor", True, None),
            (b'{"v":1,"armed":false,"mode":"gesture"}', "gesture", False, None),
            (b'{"v":1,"armed":false}', "gesture", False, None),                       # nothing changes: still a reply
            (b'{"v":1,"future":{"x":[1]}}', "gesture", False, None),                  # unknown key only: a reply
            (b'{"v":1,"mode":"sideways"}', "gesture", False, [("rejected", "bad value for mode")]),
            (b'{"v":1,"mode":"cursor","armed":"yes"}', "gesture", False, [("rejected", "bad value for armed")]),
            (b'{"v":1,"sleep":false}', "gesture", False, [("rejected", "bad value for sleep")]),
            (b'[1,2]', "gesture", False, [("rejected", "not a JSON object")]),
            (b'{"v":1,"armed":tru', "gesture", False, [("rejected", "malformed JSON")]),
        ]:
            await self.config_reply(data, mode, armed, f"{P} CONFIG", extra)
        self.c.ok(f"{P} CONFIG: exactly one reply per write, each with a fresh id (ids +1 are checked on every "
                  f"message)", await self.expect_none(0.4))

        print(f"\n== {P}: the button (serial `btn`, same state machine as the real button)", flush=True)
        t0 = self.cmd("btn click")
        m = await self.expect_state(None, "cursor", False, f"{P} btn click: mode toggles")
        if m:
            dt = (m.t_last - t0) * 1000
            self.c.ok(f"{P} btn click: acts only after the series gap ({dt:.0f} ms after the command; press 80 ms + "
                      f"debounce + 400 ms gap)", dt >= 480, f"{dt:.0f} ms")
        await self.expect_state("btn click", "gesture", False, f"{P} btn click again")
        self.cmd("btn clicks 3")
        self.c.ok(f"{P} btn clicks 3: nothing happens", await self.expect_none(1.6))
        self.cmd("btn clicks 2")
        self.c.ok(f"{P} btn clicks 2 (test-sound trigger off): nothing happens", await self.expect_none(1.5))
        await self.expect_state("btn clicks 5", "gesture", True, f"{P} btn clicks 5 while disarmed: arms")
        self.cmd("test on")
        self.cmd("btn clicks 2")
        m = await self.next_msg(3.0)
        try:
            line = json.loads(m.text)["sounds"][0] if m else None
        except Exception:  # noqa: BLE001  (check_sound reports it)
            line = None
        entry = next((e for e in self.sounds["sounds"] if e["line"] == line), None)
        self.c.ok(f"{P} test-sound trigger on: 2 presses send a canned sound", entry is not None,
                  m.text[:90] if m else "no message")
        if m is not None:
            self.check_sound(m, entry or self.by_name["rise"], "gesture", f"{P} test trigger", None)
        self.cmd("test off")
        await asyncio.sleep(0.3)

        # hold 1 s while armed: disarm at once (while still held), sleep on release
        t0 = self.cmd("btn hold 1200")
        m = await self.expect_state(None, "gesture", False, f"{P} btn hold 1200: fast stop")
        if m:
            dt = (m.t_last - t0) * 1000
            self.c.ok(f"{P} btn hold 1200: the stop comes at ~1 s, while still held ({dt:.0f} ms after the command)",
                      950 <= dt < 1400, f"{dt:.0f}")
        await self.expect_sleeping(f"{P} btn hold 1200 released", "gesture")

        # asleep: 1-4 presses and a 1 s hold do nothing
        self.ser.drain()
        self.cmd("btn clicks 3")
        ign = await self.swait(lambda s: "asleep: 3 presses ignored" in s, 3.0)
        self.cmd("btn hold 1200")
        ign2 = await self.swait(lambda s: "asleep: hold 1 s does nothing" in s, 3.0)
        await asyncio.sleep(0.5)
        self.c.ok(f"{P} asleep: 3 presses and a 1 s hold do nothing", ign is not None and ign2 is not None)
        await self.expect_power(f"{P} after those, the device", "asleep")

        # 5 presses wake it; a bonded reconnect (outside the pairing window) finds it ARMED
        print(f"\n== {P}: wake with 5 presses, sleep from the app, unexpected disconnect", flush=True)
        self.cmd("btn clicks 5")
        wk = await self.swait(lambda s: s.startswith("awake after"), 5.0)
        self.c.ok(f"{P} btn clicks 5 while asleep: wakes (radio + mic back on)", wk is not None, wk[1] if wk else "")
        await self.expect_power(f"{P} woken, the device", "awake", "waiting for a bonded phone")
        self.cmd("status")
        st = await self.swait(lambda s: s.startswith("ble:") and "pairing window" in s, 2.0)
        self.c.ok(f"{P} woken: the pairing window stays closed", st is not None and "pairing window closed" in st[1],
                  st[1] if st else "")
        if await self.reconnect_after_wake(f"{P} after the 5-press wake", expect_armed=True):
            # 5 presses while armed: turn off
            self.cmd("btn clicks 5")
            await self.expect_sleeping(f"{P} btn clicks 5 while armed", "gesture")
        self.cmd("btn clicks 5")
        await self.swait(lambda s: s.startswith("awake after"), 5.0)
        if await self.reconnect_after_wake(f"{P} second wake", expect_armed=True):
            try:
                await self.config(b'{"v":1,"sleep":true}')
                await self.expect_sleeping(f"{P} CONFIG sleep", "gesture")
            except Exception as e:  # noqa: BLE001
                self.c.ok(f"{P} CONFIG sleep write", False, repr(e))
        # an unexpected disconnect (the PC drops the link) after a 5-press wake: the reconnect finds it disarmed
        self.cmd("btn clicks 5")
        await self.swait(lambda s: s.startswith("awake after"), 5.0)
        if await self.reconnect_after_wake(f"{P} third wake", expect_armed=True):
            await self.disconnect()
            await self.reconnect_after_wake(f"{P} after an unexpected disconnect", expect_armed=False)

        # hold 5 s while connected: disarm at 1 s, pairing window at 5 s drops the link; a bonded phone may reconnect
        print(f"\n== {P}: hold 5 s while connected (pairing window)", flush=True)
        await self.config_reply(b'{"v":1,"armed":true}', "gesture", True, f"{P} setup")
        t0 = self.cmd("btn hold 5500")
        await self.expect_state(None, "gesture", False, f"{P} btn hold 5500: fast stop at 1 s")
        try:
            await asyncio.wait_for(self.dropped.wait(), 8)
            dt = (time.perf_counter() - t0) * 1000
            self.c.ok(f"{P} btn hold 5500: the pairing window opens at 5 s and drops the connected phone "
                      f"({dt:.0f} ms)", 4900 <= dt < 7000, f"{dt:.0f}")
        except asyncio.TimeoutError:
            self.c.ok(f"{P} btn hold 5500: the pairing window drops the connected phone", False, "no disconnect")
        self.c.ok(f"{P} btn hold 5500: no sleeping message (the window opens instead of sleep)",
                  await self.expect_none(0.3))
        await self.expect_power(f"{P} window open, the device", "awake", "pairing window OPEN")
        await self.reconnect_after_wake(f"{P} bonded reconnect while the window is open", expect_armed=False)
        if not self.a.quick:
            print(f"   waiting for the 60 s window to close with the phone connected ...", flush=True)
            cl = await self.swait(lambda s: "a phone is connected: staying awake" in s, 70.0)
            self.c.ok(f"{P} the window closes without a new bond while a phone is connected: stays awake, disarmed",
                      cl is not None and self.client.is_connected and await self.expect_none(0.5),
                      cl[1] if cl else "no close within 70 s")
            await self.expect_power(f"{P} after the window closed, the device", "awake")

            print(f"\n== {P}: timeouts (60 s each)", flush=True)
            # 5-press wake, no phone within 60 s: sleep again
            await self.disconnect()
            self.cmd("sleep")
            await self.swait(lambda s: s.startswith("asleep:"), 5.0)
            self.cmd("btn clicks 5")
            await self.swait(lambda s: s.startswith("awake after"), 5.0)
            sl = await self.swait(lambda s: "going to sleep (no bonded phone subscribed within 60 s" in s, 70.0)
            self.c.ok(f"{P} 5-press wake with no phone: back to sleep after 60 s", sl is not None, sl[1] if sl else "")
            await self.expect_power(f"{P} then the device", "asleep")
            # hold 5 s while asleep: wake + pairing window; closes after 60 s with no phone: sleep
            self.cmd("btn hold 5500")
            op = await self.swait(lambda s: "pairing window OPEN" in s, 9.0)
            self.c.ok(f"{P} btn hold 5500 while asleep: wakes and opens the pairing window", op is not None,
                      op[1] if op else "")
            sl = await self.swait(lambda s: "going to sleep (pairing window closed without a new bond)" in s, 70.0)
            self.c.ok(f"{P} the window closes after 60 s without a bond and no phone: sleep", sl is not None,
                      sl[1] if sl else "")
            await self.expect_power(f"{P} then the device", "asleep")
            self.cmd("wake")
            await self.swait(lambda s: s.startswith("awake after"), 5.0)
            await self.reconnect_after_wake(f"{P} after `wake`", expect_armed=False)
        # quick run: the window is still open; run() ends with `sleep` + `wake`, which closes it

    async def session(self, mtu: int, first: bool) -> None:
        P = self.phase
        print(f"\n== {P}: connect (device accepts MTU <= {mtu})", flush=True)
        n_log = len(self.ser.log)
        if not self.c.ok(f"{P}: connect", await self.connect()):
            return
        if first:
            svc = self.client.services.get_service(SVC)
            props = {ch.uuid: sorted(ch.properties) for ch in svc.characteristics} if svc else {}
            self.c.ok("GATT: service with EVENT notify, CONFIG write, INFO read",
                      props.get(EVENT) == ["notify"] and props.get(CONFIG) == ["write"] and props.get(INFO) == ["read"],
                      str(props))
            info_raw = bytes(await self.client.read_gatt_char(INFO))
            info = json.loads(info_raw)
            self.report["info"] = info
            self.secure = not info.get("insecure", False)
            keys_ok = (info.get("v") == 1 and isinstance(info.get("fw"), str) and info.get("mic") in ("inmp441", "none")
                       and "fp_version" in info and (info["fp_version"] is None or isinstance(info["fp_version"], str))
                       and set(info) <= {"v", "fw", "mic", "fp_version", "insecure"})
            self.c.ok(f"INFO read (no pairing needed): {info_raw.decode()}", keys_ok)
            print(f"  build: {'SECURE (encryption required)' if self.secure else 'INSECURE debug build'}")
            if self.secure:
                # without encryption the phone must not be able to use CONFIG / subscribe to EVENT
                # BlueZ answers the device's "insufficient authentication" by trying to pair; with no agent yet
                # that fails (SMP 0x0c) and BlueZ never completes this WriteValue, nor any later write on the same
                # D-Bus device object (measured). So: time out, then drop BlueZ's device object before going on.
                n_cfg = len(self.device_log(r"^CONFIG"))
                outcome = "accepted"
                try:
                    await asyncio.wait_for(self.client.write_gatt_char(CONFIG, b"{}", response=True), 8)
                except Exception as e:  # noqa: BLE001
                    outcome = repr(e)
                fails = self.device_log(r"pairing FAILED")
                self.report["unencrypted_config_write"] = {"bleak": outcome, "device": fails[-1:] }
                self.c.ok("secure: CONFIG write on an unencrypted link never reaches the application",
                          outcome != "accepted" and len(self.device_log(r"^CONFIG")) == n_cfg,
                          f"bleak: {outcome}; device: {fails[-1] if fails else 'no pairing attempt'}")
                await self.disconnect()
                await self.remove_bond()
                self.device, _ = await self.scan()
                if not self.c.ok(f"{P}: reconnect for pairing", await self.connect()):
                    return
                # the agent only now, so that the refusal above is not hidden by BlueZ raising security by itself
                self.agent = NoIoAgent()
                await self.agent.register(self.bus)

                # pairing gate: outside the pairing window a new pairing is rejected by the device
                await self.expect_power("pairing gate: device", "awake")
                n_rej = len(self.device_log(r"REJECTED: pairing window closed"))
                r = await self.bluez_call(self.dev_path(), "org.bluez.Device1", "Pair", timeout=40)
                await asyncio.sleep(0.5)
                rej = self.device_log(r"REJECTED: pairing window closed")
                self.c.ok("pairing gate: a new pairing OUTSIDE the pairing window is rejected",
                          r.message_type == MessageType.ERROR and len(rej) > n_rej and not self.device_log(
                              r"pairing complete: success"),
                          f"BlueZ: {r.error_name if r.message_type == MessageType.ERROR else 'paired!'}; "
                          f"device: {rej[-1] if rej else 'no rejection logged'}")
                await self.disconnect()
                await self.remove_bond()   # BlueZ misbehaves on a device object after a failed pairing
                # open the window with the button (5 s hold), then pair
                self.cmd("btn hold 5500")
                op = await self.swait(lambda s: "pairing window OPEN" in s, 8.0)
                self.c.ok("pairing gate: `btn hold 5500` opens the pairing window", op is not None, op[1] if op else "")
                await self.expect_power("pairing gate: device", "awake", "pairing window OPEN")
                self.device, _ = await self.scan()
                if not self.c.ok(f"{P}: reconnect for pairing (window open)", await self.connect()):
                    return
                t0 = time.perf_counter()
                r = await self.bluez_call(self.dev_path(), "org.bluez.Device1", "Pair", timeout=40)
                paired = r.message_type != MessageType.ERROR
                self.report["pairing_ms"] = round((time.perf_counter() - t0) * 1000)
                self.c.ok(f"secure: LE Secure Connections Just Works pairing via BlueZ "
                          f"({self.report['pairing_ms']} ms)", paired,
                          "" if paired else f"{r.error_name}: {r.body}")
                await asyncio.sleep(0.5)
                enc = self.device_log(r"encryption ON")
                done = self.device_log(r"pairing complete: success")
                self.c.ok("secure: link encrypted with LE Secure Connections (device side)",
                          any("secure connections yes" in s for s in enc) and bool(done),
                          (enc[-1] if enc else "no 'encryption ON' in the device log") + f" | {len(done)} pairing ok")
                self.cmd("status")
                st = await self.swait(lambda s: s.startswith("ble:") and "encrypted" in s, 2.0)
                self.c.ok("secure: device status shows encrypted, LESC, bonded",
                          st is not None and "encrypted yes" in st[1] and "LESC yes" in st[1] and "bonded yes" in st[1],
                          st[1] if st else "")
                cl = self.device_log(r"pairing window closed: new bond made")
                self.c.ok("pairing gate: the window closes at once when the bond is made",
                          bool(cl) and st is not None and "pairing window closed" in st[1], cl[-1] if cl else "")
                self.report["agent_calls"] = self.agent.calls if self.agent else []
        await self.subscribe(expect_armed=False, expect_mode="gesture")
        await asyncio.sleep(0.3)
        new = [s for _, s in self.ser.log[n_log:]]
        mtus = [int(x) for s in new for x in re.findall(r"\] MTU (\d+)", s)]
        ivs = [s for s in new if "interval" in s]
        eff_mtu = mtus[-1] if mtus else 23
        self.c.ok(f"{P}: negotiated MTU {eff_mtu}", eff_mtu == mtu, str(mtus))
        self.report["phases"][P] = {"mtu": eff_mtu, "interval_log": ivs}
        await self.suite(eff_mtu)
        await self.latency(self.a.n)
        if not self.a.quick:
            await self.stress()

    async def run(self) -> int:
        a = self.a
        print("== setup")
        self.ser.drain()
        self.cmd("status")
        st = await self.swait(lambda s: s.startswith("vox_node "), 3.0)
        if not self.c.ok("serial console answers `status`", st is not None):
            return 1
        self.report["firmware"] = st[1]
        self.cmd("list")
        lst = await self.swait(lambda s: "digest" in s, 3.0)
        self.c.ok("firmware's canned sounds = tests/test_sounds.json (same digest)",
                  lst is not None and self.sounds["digest"] in lst[1], lst[1] if lst else "")
        self.c.ok("tests/test_sounds.json uses the extractor's current vocabulary",
                  self.sounds["vocab_digest"] == VOCAB.digest(), f"{self.sounds['vocab_digest']} vs {VOCAB.digest()}")
        runner = VOX / "extractor" / "run"
        if runner.exists() and not a.no_extractor:
            r = subprocess.run([str(runner), "python", str(HERE / "gen_test_sounds.py"), "--check"],
                               capture_output=True, text=True, timeout=300)
            self.c.ok("canned lines = what the extractor produces NOW (gen_test_sounds.py --check)",
                      r.returncode == 0, (r.stdout + r.stderr).strip().splitlines()[-1] if (r.stdout + r.stderr).strip() else "")
        self.cmd("wake")   # in case an earlier run left it asleep
        await asyncio.sleep(1.0)
        for c in ("ble mtu 517", "test off", "mic off", "pause", "mode gesture"):
            self.cmd(c)
            await asyncio.sleep(0.1)
        await asyncio.sleep(0.5)

        self.bus = await MessageBus(bus_type=BusType.SYSTEM).connect()

        print("== scan")
        self.device, dt = await self.scan()
        if not self.c.ok(f"advertising found by service UUID ({dt:.1f} s)", self.device is not None):
            return 1
        suffix = self.device.address.replace(":", "")[-4:].upper()
        self.c.ok(f"advertised name {self.device.name} = VOX-<last 2 address bytes>", self.device.name == f"VOX-{suffix}")
        self.report["address"] = self.device.address
        self.report["name"] = self.device.name
        # start from a clean slate on both sides
        await self.remove_bond()
        self.cmd("ble forget")
        await asyncio.sleep(0.5)
        self.device, _ = await self.scan()

        try:
            self.phase = "mtu517"
            await self.session(517, first=True)
            await self.reconnect_check()
            await self.power_checks()
            if not a.quick:
                self.cmd("ble mtu 23")
                await asyncio.sleep(0.2)
                await self.disconnect()
                self.phase = "mtu23"
                await self.session(23, first=False)
        finally:
            self.cmd("ble mtu 517")
            await self.disconnect()
            # leave the device awake with the pairing window closed: `sleep` closes it, `wake` wakes
            self.cmd("sleep")
            await self.swait(lambda s: s.startswith("asleep:") or "already asleep" in s, 5.0)
            self.cmd("wake")
            await self.swait(lambda s: s.startswith("awake after"), 5.0)
            if not a.keep_bond:
                await self.remove_bond()
                self.cmd("ble forget")
            if self.agent:
                await self.agent.unregister(self.bus)

        # ---------------- global checks and report
        self.c.ok(f"fragment headers: no counter gaps and first/last bits consistent over {self.ra.frags} fragments "
                  f"({self.ra.wraps} wrap(s) 63 -> 0)", self.ra.gaps == 0 and self.ra.bad_first == 0 and (self.ra.wraps >= 1 or a.quick),
                  f"gaps {self.ra.gaps}, bad first-bit {self.ra.bad_first}")
        self.c.ok(f"all {len(self.captured)} messages captured and valid", len(self.captured) > 0)
        lat_summary = {}
        for k, v in sorted(self.lat.items()):
            if len(v) >= 3:
                s = sorted(v)
                lat_summary[k] = {"n": len(v), "median_ms": round(statistics.median(v), 1),
                                  "p90_ms": round(s[int(0.9 * (len(s) - 1))], 1), "min_ms": round(s[0], 1),
                                  "max_ms": round(s[-1], 1)}
        self.report["latency_serial_send_to_notification"] = lat_summary
        if self.offsets:
            base = min(self.offsets)
            spread = sorted(o - base for o in self.offsets)
            self.report["arrival_minus_device_t_end_ms"] = {
                "n": len(spread), "median_above_min": round(statistics.median(spread), 1),
                "p90_above_min": round(spread[int(0.9 * (len(spread) - 1))], 1), "max_above_min": round(spread[-1], 1)}
        self.report["fragments"] = {"total": self.ra.frags, "gaps": self.ra.gaps, "wraps": self.ra.wraps,
                                    "bad_first_bit": self.ra.bad_first,
                                    "first_counter_per_connection": self.ra.first_ctr}
        self.report["checks"] = {"passed": sum(1 for r in self.c.results if r[1]), "failed": len(self.c.failed),
                                 "failures": [f"{n}: {d}" for n, _, d in self.c.failed]}
        out = FIRMWARE / "tests" / "captured_messages.jsonl"
        out.write_text("".join(m.text + "\n" for m in self.captured))
        (FIRMWARE / "tests" / "ble_check_report.json").write_text(json.dumps(self.report, indent=1) + "\n")
        print(f"\nlatency serial `send` -> notification complete (ms): "
              f"{json.dumps(lat_summary, indent=1)}")
        print(f"wrote {out.relative_to(VOX)} ({len(self.captured)} messages) and tests/ble_check_report.json")
        print(f"\n{len(self.c.results) - len(self.c.failed)} passed, {len(self.c.failed)} failed")
        for n, _, d in self.c.failed:
            print(f"  FAIL {n}: {d}")
        return 1 if self.c.failed else 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="/dev/ttyACM0")
    ap.add_argument("-n", type=int, default=20, help="latency samples per sound type and phase")
    ap.add_argument("--quick", action="store_true", help="MTU 517 pass only, no USB stress")
    ap.add_argument("--keep-bond", action="store_true", help="keep the BlueZ bond at the end")
    ap.add_argument("--no-extractor", action="store_true", help="skip running gen_test_sounds.py --check")
    ap.add_argument("-v", "--verbose", action="store_true", help="echo the device console")
    a = ap.parse_args()
    chk = BleCheck(a)
    try:
        rc = asyncio.run(chk.run())
    finally:
        chk.ser.close()
    sys.exit(rc)


if __name__ == "__main__":
    main()
