#!/usr/bin/env python3
"""Canti demo console: a small local server between the browser page (web/) and the hardware.

    python demo/server.py                      # then open http://127.0.0.1:8790
    python demo/server.py --pico COM3 --emulator 127.0.0.1:5581 --phone R5CX62H7PNJ

Two targets, one page:
  emulator   the app on the suite's emulator. Sounds go straight into the app's debug feature source
             (adb forward -> localabstract:vox-debug), with the precomputed `features` (fp1 + pitch16) and device
             timing, exactly as the Pico's firmware would send them over BLE. Hold-to-scroll works (hold messages).
  phone      the real phone. Sounds go to the Pico over USB serial (`send <name>`, `seq ...`, `mode ...`), and the
             Pico sends them to the phone over BLE. Canned sends carry no `features` on the wire.
             `--phone-direct` instead injects into the phone's debug source (no Pico, for rehearsing).

The page gets one Server-Sent Events stream (/api/events): the app's event log (adb logcat, tag VOX) of each target,
the Pico's console lines, and this server's own notes. Commands are POST /api/cmd with a JSON body (see Cmd below).

Stdlib only, plus pyserial for the Pico. adb comes from PATH or --adb (scrcpy's bundled adb works).
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
WEB = HERE / "web"
UI_ASSETS = (HERE.parent / "ui" / "assets").resolve()


class _Sounds(dict):
    """The sounds the page shows: data/sounds.recorded.json (your takes, tools/record_demo_sounds.py) when present,
    else data/sounds.json; reloaded when either file changes, so a new recording needs no restart."""

    def __init__(self) -> None:
        super().__init__()
        self._key = None

    def _fresh(self) -> None:
        files = [WEB / "data" / "sounds.recorded.json", WEB / "data" / "sounds.json"]
        path = next(f for f in files if f.exists())
        key = (path, path.stat().st_mtime_ns)
        if key != self._key:
            self.clear()
            self.update(json.loads(path.read_text())["sounds"])
            self._key = key

    def __getitem__(self, k):
        self._fresh()
        return super().__getitem__(k)


SOUNDS = _Sounds()
PICO_VID = 0x2E8A
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
WIKI_URL = "https://en.m.wikipedia.org/wiki/Canti_(FLCL)"
BROWSERS = {"emulator": "org.mozilla.fennec_fdroid", "phone": "com.android.chrome"}


def device_ms() -> int:
    """The stand-in device clock for debug-source messages (only differences matter to the app)."""
    return int(time.monotonic() * 1000)


# ---------------------------------------------------------------- event hub

class Hub:
    """Fan-out of events to every open SSE stream, plus a short backlog for a page that just (re)connected."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.subs: list[queue.Queue] = []
        self.backlog: list[str] = []

    def emit(self, src: str, **data) -> None:
        line = json.dumps({"src": src, "at": round(time.time() * 1000), **data})
        with self.lock:
            self.backlog = (self.backlog + [line])[-200:]
            for q in self.subs:
                q.put(line)

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self.lock:
            for line in self.backlog[-60:]:
                q.put(line)
            self.subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self.lock:
            if q in self.subs:
                self.subs.remove(q)


HUB = Hub()


def note(text: str, **kw) -> None:
    HUB.emit("server", text=text, **kw)


# ---------------------------------------------------------------- adb

class Adb:
    def __init__(self, exe: str) -> None:
        self.exe = exe

    def run(self, serial: str | None, *args: str, timeout: float = 30) -> subprocess.CompletedProcess:
        cmd = [self.exe] + (["-s", serial] if serial else []) + list(args)
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)

    def devices(self) -> dict[str, str]:
        out = self.run(None, "devices").stdout.splitlines()[1:]
        return {p[0]: p[1] for p in (l.split() for l in out) if len(p) >= 2}


def find_adb(given: str | None) -> str:
    if given:
        return given
    exe = shutil.which("adb")
    if exe:
        return exe
    pkgs = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    for p in sorted(pkgs.glob("Genymobile.scrcpy*/*/adb.exe")):
        return str(p)
    raise SystemExit("adb not found: put it on PATH or pass --adb")


# ---------------------------------------------------------------- one Android target

class Target:
    """One device running the app: its debug socket (for control ops and injected sounds) and its event log."""

    def __init__(self, name: str, adb: Adb, serial: str | None, local_port: int) -> None:
        self.name, self.adb, self.serial, self.port = name, adb, serial, local_port
        self.sock: socket.socket | None = None
        self.rfile = None
        self.lock = threading.Lock()
        self.next_id = int(time.time()) % 100000 * 10   # fresh ids after a server restart (repeats are ignored)
        self.sound_no = 0
        self.logcat: subprocess.Popen | None = None
        self.mode = "gesture"

    def online(self) -> bool:
        return bool(self.serial) and self.adb.devices().get(self.serial) == "device"

    def _connect(self) -> None:
        r = self.adb.run(self.serial, "forward", f"tcp:{self.port}", "localabstract:vox-debug")
        if r.returncode:
            raise RuntimeError(f"adb forward failed: {r.stderr.strip()[:200]}")
        self.sock = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        self.rfile = self.sock.makefile("r", encoding="utf-8")

    def send(self, msg: dict) -> dict:
        """One JSON line to the app's debug source, one reply line back (reconnects once)."""
        with self.lock:
            for attempt in (0, 1):
                try:
                    if self.sock is None:
                        self._connect()
                    self.sock.sendall((json.dumps(msg) + "\n").encode())
                    line = self.rfile.readline()
                    if not line:
                        raise ConnectionError("debug socket closed")
                    return json.loads(line)
                except (OSError, ConnectionError, ValueError, RuntimeError) as e:
                    self.close()
                    if attempt:
                        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        return {"ok": False, "error": "unreachable"}

    def close(self) -> None:
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            pass
        self.sock = self.rfile = None

    def new_id(self) -> int:
        self.next_id += 1
        return self.next_id

    def control(self, op: str, **kw) -> dict:
        return self.send({"type": "control", "op": op, **kw})

    def sound(self, name: str, t_end: int | None = None, held_sound: int | None = None) -> dict:
        """The feature message the Pico would send for this canned sound: its line, fp1 features and timing."""
        s = SOUNDS[name]
        t_end = t_end or device_ms()
        timing = {"t_start_ms": t_end - s["dur_ms"], "t_end_ms": t_end}
        if held_sound:
            timing.update(sound=held_sound, held=True)
        msg = {"v": 1, "id": self.new_id(), "mode": self.mode, "armed": True, "sounds": [s["line"]],
               "sequence": [s["label"]], "timing": [timing], "features": [s["features"]], "phrase": None,
               "cursor": None}
        r = self.send(msg)
        HUB.emit("inject", target=self.name, name=name, msg=msg, reply=r)
        return r

    def set_mode(self, mode: str) -> dict:
        self.mode = mode
        r = self.send({"v": 1, "id": self.new_id(), "mode": mode, "armed": True, "sounds": [], "sequence": []})
        HUB.emit("inject", target=self.name, name=f"mode {mode}", reply=r)
        return r

    def hold(self, name: str, hold_ms: int) -> dict:
        """A held hum after a swipe: hold start (300 ms in), hold end, then the held sound's own feature message."""
        s = SOUNDS[name]
        self.sound_no += 1
        n, t0 = self.sound_no, device_ms()
        f0 = s["raw"].get("f0_med_hz") or 200.0
        self.send({"v": 1, "id": self.new_id(), "hold": "start", "sound": n, "t_start_ms": t0 - 300, "t_ms": t0,
                   "f0_hz": f0, "flat": True})
        HUB.emit("inject", target=self.name, name=f"hold start ({name})", hold="start", sound=n)
        time.sleep(hold_ms / 1000)
        t1 = device_ms()
        self.send({"v": 1, "id": self.new_id(), "hold": "end", "sound": n, "t_start_ms": t0 - 300, "t_ms": t1})
        HUB.emit("inject", target=self.name, name=f"hold end ({name})", hold="end", sound=n)
        msg = {"v": 1, "id": self.new_id(), "mode": self.mode, "armed": True, "sounds": [s["line"]],
               "sequence": [s["label"]], "timing": [{"t_start_ms": t0 - 300, "t_end_ms": t1, "sound": n, "held": True}],
               "features": [s["features"]], "phrase": None, "cursor": None}
        return self.send(msg)

    def start_logcat(self) -> None:
        if not self.serial or (self.logcat and self.logcat.poll() is None):
            return
        # -T 1: from now on (the phone's log is not cleared)
        self.logcat = subprocess.Popen([self.adb.exe, "-s", self.serial, "logcat", "-v", "raw", "-T", "1", "-s", "VOX:I"],
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                                       errors="replace", creationflags=NO_WINDOW)
        threading.Thread(target=self._read_logcat, args=(self.logcat,), daemon=True).start()

    def _read_logcat(self, proc: subprocess.Popen) -> None:
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("{"):
                try:
                    HUB.emit("app", target=self.name, ev=json.loads(line))
                except ValueError:
                    pass
        note(f"{self.name}: event log stream ended")


# ---------------------------------------------------------------- the Pico

class Pico:
    def __init__(self, port: str | None) -> None:
        self.want = port
        self.port: str | None = None
        self.ser = None
        self.lock = threading.Lock()
        self.last_send: str | None = None
        self.retried = False

    def find(self) -> str | None:
        if self.want and self.want != "auto":
            return self.want
        try:
            from serial.tools import list_ports
        except ImportError:
            return None
        for p in list_ports.comports():
            if p.vid == PICO_VID:
                return p.device
        return None

    def ensure(self) -> bool:
        if self.ser is not None:
            return True
        try:
            import serial
        except ImportError:
            note("pyserial is missing: pip install pyserial")
            return False
        port = self.find()
        if not port:
            return False
        try:
            self.ser = serial.Serial(port, 115200, timeout=0.2)
        except (OSError, serial.SerialException) as e:
            note(f"pico: cannot open {port}: {e}")
            return False
        self.port = port
        note(f"pico: connected on {port}")
        threading.Thread(target=self._read, daemon=True).start()
        return True

    def _read(self) -> None:
        buf = b""
        while self.ser is not None:
            try:
                chunk = self.ser.read(512)
            except Exception as e:  # noqa: BLE001 (unplugged: any serial error)
                note(f"pico: link lost ({e})")
                self.ser = None
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode(errors="replace").rstrip("\r")
                if text:
                    HUB.emit("pico", line=text)
                    # a send refused while disarmed (after a reboot or a pause): arm, then send it again once
                    if ": not sent (device is" in text and self.last_send and not self.retried:
                        self.retried = True
                        threading.Thread(target=self._rearm, daemon=True).start()

    def _rearm(self) -> None:
        self.cmd("arm")
        time.sleep(0.3)
        self.cmd(self.last_send, keep=True)

    def cmd(self, line: str, keep: bool = False) -> dict:
        if line.startswith(("send ", "seq ")) and not keep:
            self.last_send, self.retried = line, False
        if not self.ensure():
            return {"ok": False, "error": "no Pico serial port"}
        with self.lock:
            try:
                self.ser.write((line + "\n").encode())
            except Exception as e:  # noqa: BLE001
                self.ser = None
                return {"ok": False, "error": str(e)}
        return {"ok": True, "sent": line}


# ---------------------------------------------------------------- commands

class Console:
    def __init__(self, a: argparse.Namespace) -> None:
        self.adb = Adb(find_adb(a.adb))
        self.targets = {"emulator": Target("emulator", self.adb, a.emulator, 7788),
                        "phone": Target("phone", self.adb, a.phone, 7789)}
        self.pico = Pico(a.pico)
        self.phone_direct = a.phone_direct
        self.scrcpy = a.scrcpy or shutil.which("scrcpy") or str(Path(self.adb.exe).with_name("scrcpy.exe"))

    def resolve(self) -> None:
        devs = self.adb.devices()
        emu = self.targets["emulator"]
        if emu.serial and ":" in emu.serial and emu.serial not in devs:
            self.adb.run(None, "connect", emu.serial, timeout=10)
            devs = self.adb.devices()
        ph = self.targets["phone"]
        if not ph.serial:
            real = [s for s, st in devs.items() if st == "device" and not s.startswith("emulator-") and ":" not in s]
            ph.serial = real[0] if real else None
        for t in self.targets.values():
            if t.serial and devs.get(t.serial) == "device":
                t.start_logcat()

    def status(self) -> dict:
        self.resolve()
        devs = self.adb.devices()
        out = {"targets": {}, "pico": {"port": self.pico.port or self.pico.find(), "open": self.pico.ser is not None},
               "phone_direct": self.phone_direct}
        for name, t in self.targets.items():
            st = devs.get(t.serial or "", "absent")
            out["targets"][name] = {"serial": t.serial, "adb": st}
        return out

    def run(self, c: dict) -> dict:
        op = c.get("op")
        tname = c.get("target", "emulator")
        t = self.targets.get(tname)
        via_pico = tname == "phone" and not self.phone_direct
        if op == "status":
            return self.status()
        if op == "ping":
            return t.control("ping")
        if op == "control":
            return t.control(c["name"], **c.get("args", {}))
        if op == "sound":
            name = c["name"]
            if via_pico:
                return self.pico.cmd(f"send {name}")
            return t.sound(name)
        if op == "seq":
            names, gap = c["names"], int(c.get("gap_ms", 250))
            if via_pico:
                return self.pico.cmd(f"seq {' '.join(names)} {gap}")
            # separate messages, each sent when its sound ends on the device clock (as the Pico does)
            r = {}
            t_end = device_ms()
            for i, n in enumerate(names):
                if i:
                    t_end += gap + SOUNDS[n]["dur_ms"]
                    time.sleep(max(0, t_end - device_ms()) / 1000)
                r = t.sound(n, t_end=t_end)
            return r
        if op == "hold":
            if via_pico:
                return {"ok": False, "error": "canned sends have no hold messages (emulator or --phone-direct only)"}
            return t.hold(c.get("name", "flat"), int(c.get("ms", 1500)))
        if op == "mode":
            if via_pico:
                return self.pico.cmd(f"mode {c['mode']}")
            return t.set_mode(c["mode"])
        if op == "pico":
            return self.pico.cmd(c["line"])
        if op == "reset":
            # the suite's reset recipe: rules decider, default gap, gesture mode
            if via_pico:
                self.pico.cmd("arm")
            r1 = t.control("reset")
            r2 = t.control("config", decider=c.get("decider", "rules"))
            if not via_pico:
                t.set_mode("gesture")
            return {"ok": bool(r1.get("ok") and r2.get("ok")), "reset": r1, "config": r2}
        if op == "shell":
            return self.shell(t, c["preset"], c.get("url"))
        if op == "scrcpy":
            return self.mirror(t)
        return {"ok": False, "error": f"unknown op {op!r}"}

    def shell(self, t: Target, preset: str, url: str | None) -> dict:
        s = t.serial
        if preset == "wiki":
            # quoted: adb joins the args into one device shell line, and wiki URLs can hold ( )
            args = ["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", f"'{url or WIKI_URL}'",
                    "-p", BROWSERS[t.name]]
        elif preset == "home":
            args = ["shell", "input", "keyevent", "KEYCODE_HOME"]
        elif preset == "vox":
            args = ["shell", "am", "start", "-W", "-n", "ai.vox.companion/.MainActivity"]
        else:
            return {"ok": False, "error": f"unknown preset {preset!r}"}
        r = self.adb.run(s, *args)
        note(f"{t.name}: {preset}", rc=r.returncode)
        return {"ok": r.returncode == 0, "out": (r.stdout + r.stderr).strip()[-300:]}

    def mirror(self, t: Target) -> dict:
        if not t.serial:
            return {"ok": False, "error": "no device"}
        title = "Canti - emulator" if t.name == "emulator" else "Canti - phone"
        subprocess.Popen([self.scrcpy, "-s", t.serial, "--window-title", title, "--no-audio", "--stay-awake"],
                         env={**os.environ, "ADB": self.adb.exe}, creationflags=NO_WINDOW)
        return {"ok": True}


# ---------------------------------------------------------------- HTTP

def make_handler(con: Console):
    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(WEB), **kw)

        def log_message(self, fmt, *args):  # quiet: the page shows what matters
            pass

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def translate_path(self, path):
            # /ui/... = the Flutter UI's own assets (fonts, stipple brand PNGs), shared rather than copied
            if path.startswith("/ui/"):
                rel = path.split("?", 1)[0][len("/ui/"):]
                p = (UI_ASSETS / rel).resolve()
                return str(p) if UI_ASSETS in p.parents else str(UI_ASSETS / "missing")
            return super().translate_path(path)

        def do_GET(self):
            if self.path == "/api/events":
                return self.events()
            if self.path == "/api/status":
                return self.reply(con.status())
            return super().do_GET()

        def do_POST(self):
            if self.path != "/api/cmd":
                return self.send_error(HTTPStatus.NOT_FOUND)
            n = int(self.headers.get("Content-Length", 0))
            try:
                c = json.loads(self.rfile.read(n) or b"{}")
                r = con.run(c)
            except Exception as e:  # noqa: BLE001 (report to the page, keep serving)
                r = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            self.reply(r)

        def reply(self, obj: dict) -> None:
            body = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def events(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            q = HUB.subscribe()
            try:
                while True:
                    try:
                        line = q.get(timeout=15)
                        self.wfile.write(f"data: {line}\n\n".encode())
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
            except OSError:
                pass
            finally:
                HUB.unsubscribe(q)

    return H


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--adb")
    ap.add_argument("--scrcpy")
    ap.add_argument("--emulator", default="127.0.0.1:5581", help="adb serial of the emulator (WSL: 127.0.0.1:5581)")
    ap.add_argument("--phone", help="adb serial of the phone (default: the first USB device)")
    ap.add_argument("--pico", default="auto", help="the Pico's serial port (default: first Raspberry Pi USB port)")
    ap.add_argument("--phone-direct", action="store_true", help="phone target: inject over adb instead of the Pico")
    a = ap.parse_args()
    con = Console(a)
    con.resolve()
    con.pico.ensure()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(con))
    srv.daemon_threads = True
    print(f"Canti demo console: http://127.0.0.1:{a.port}  (adb: {con.adb.exe})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
