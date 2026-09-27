"""Emulator test helpers (stdlib only). Run inside ./dev so adb and the env vars are set."""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

SUITE = Path(__file__).resolve().parent
ANDROID = SUITE.parent
SERIAL = os.environ.get("VOX_SERIAL", f"emulator-{os.environ.get('VOX_EMU_PORT', '5580')}")
APP = "ai.vox.companion"
FIXTURE = "ai.vox.fixture"
SERVICE = f"{APP}/{APP}.VoxService"
SOCKET_PORT = int(os.environ.get("VOX_SOCKET_PORT", "7788"))

# Sound lines in the exact format generate.py's deliberate_sound() produces.
CONTOURS = {"rise": "rises from low to high", "fall": "falls from high to low", "arch": "rises then falls",
            "dip": "falls then rises", "flat": "stays level"}
DISCRETE = {"pop": "a short lip pop", "click": "a tongue click", "hiss": "a hiss"}


def sound(label: str, loud: str = "normal") -> str:
    if label in ("pop", "click"):
        return f"{DISCRETE[label]}; instant sound; loudness {loud}; sounds like mouth sound"
    if label == "hiss":
        return f"a hiss; duration short (150-400 ms); loudness {loud}; sounds like mouth sound"
    if label == "flat":
        return (f"hum that stays level; pitch change small (under 2 semitones); duration medium (400-1000 ms); "
                f"tone clear tone; loudness {loud}; sounds like hum")
    return (f"hum that {CONTOURS[label]}; pitch change large (over 4 semitones); duration short (150-400 ms); "
            f"tone clear tone; loudness {loud}; sounds like hum")


def talking() -> str:
    return ("hum that rises from low to high; pitch change medium (2-4 semitones); duration short (150-400 ms); "
            "tone breathy; loudness normal; sounds like talking")


def device_ms() -> int:
    """The suite's stand-in for the Pico's monotonic clock."""
    return int(time.monotonic() * 1000)


def adb(*args: str, check: bool = True, timeout: float = 60, binary: bool = False):
    r = subprocess.run(["adb", "-s", SERIAL, *args], capture_output=True, timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f"adb {' '.join(args)} failed: {r.stderr.decode(errors='replace')[:400]}")
    return r.stdout if binary else r.stdout.decode(errors="replace")


def sh(cmd: str, **kw) -> str:
    return adb("shell", cmd, **kw)


class EventStream:
    """Collects the app's VOX log events from logcat in a background thread."""

    def __init__(self) -> None:
        adb("logcat", "-c")
        self.events: list[dict] = []
        self.lock = threading.Lock()
        self.proc = subprocess.Popen(["adb", "-s", SERIAL, "logcat", "-v", "raw", "-s", "VOX:I"],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        assert self.proc.stdout
        for line in self.proc.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            with self.lock:
                self.events.append(ev)

    def mark(self) -> int:
        with self.lock:
            return len(self.events)

    def since(self, mark: int) -> list[dict]:
        with self.lock:
            return list(self.events[mark:])

    def wait(self, mark: int, pred, timeout: float = 5.0) -> dict | None:
        end = time.time() + timeout
        while time.time() < end:
            for ev in self.since(mark):
                if pred(ev):
                    return ev
            time.sleep(0.05)
        return None

    def close(self) -> None:
        self.proc.terminate()


class Vox:
    """Talks to the app's debug feature source (adb forward tcp -> localabstract:vox-debug)."""

    def __init__(self) -> None:
        adb("forward", f"tcp:{SOCKET_PORT}", "localabstract:vox-debug")
        self.sock: socket.socket | None = None
        self.file = None
        self.next_id = int(time.time()) % 100000 * 10

    def _connect(self) -> None:
        self.sock = socket.create_connection(("127.0.0.1", SOCKET_PORT), timeout=10)
        self.file = self.sock.makefile("rw")

    def send(self, msg: dict) -> dict:
        for attempt in range(2):
            try:
                if self.sock is None:
                    self._connect()
                self.file.write(json.dumps(msg) + "\n")
                self.file.flush()
                line = self.file.readline()
                if not line:
                    raise ConnectionError("socket closed")
                return json.loads(line)
            except (OSError, ConnectionError, json.JSONDecodeError):
                self.close()
                if attempt:
                    raise
                time.sleep(0.5)
        raise AssertionError("unreachable")

    def close(self) -> None:
        try:
            if self.sock:
                self.sock.close()
        finally:
            self.sock = None
            self.file = None

    def control(self, op: str, **kw) -> dict:
        return self.send({"type": "control", "op": op, **kw})

    def sounds(self, *labels: str, mode: str = "gesture", loud: str = "normal", lines: list[str] | None = None,
               timing: list[tuple[int, int]] | None = None, features: list[dict | None] | None = None) -> dict:
        """timing: per-sound (t_start_ms, t_end_ms) on the "device" clock (the suite uses host monotonic ms).
        features: per-sound {fp, fp_version, pitch16} (personalization) or None."""
        self.next_id += 1
        msg = {"v": 1, "id": self.next_id, "mode": mode, "armed": True,
               "sounds": lines or [sound(l, loud) for l in labels], "sequence": list(labels)}
        if features is not None:
            msg["features"] = features
        if timing is not None:
            msg["timing"] = [{"t_start_ms": a, "t_end_ms": b} for a, b in timing]
        return self.send(msg)

    def phrase(self, text: str) -> dict:
        self.next_id += 1
        return self.send({"v": 1, "id": self.next_id, "mode": "listening", "armed": True, "sounds": [], "sequence": [],
                          "phrase": text})

    def disarm(self) -> dict:
        self.next_id += 1
        return self.send({"v": 1, "id": self.next_id, "armed": False})

    def mode(self, mode: str) -> dict:
        self.next_id += 1
        return self.send({"v": 1, "id": self.next_id, "mode": mode, "armed": True, "sounds": [], "sequence": []})

    def texts(self) -> dict[str, str]:
        """resource-id (short) -> text of the visible app window, via the service's own tree reader."""
        r = self.control("dump")
        out = {}
        for n in r.get("nodes", []):
            if n["id"]:
                out[n["id"].split("/")[-1]] = n["text"] or n["desc"]
        return out

    def all_text(self) -> str:
        r = self.control("dump")
        return "\n".join(f"{n['cls']}|{n['id']}|{n['text']}|{n['desc']}" for n in r.get("nodes", []))


def ui_dump() -> str:
    """uiautomator dump of the current window (independent of the VOX service)."""
    out = adb("exec-out", "uiautomator", "dump", "/dev/tty", check=False, timeout=30)
    return out[: out.rfind("</hierarchy>") + len("</hierarchy>")] if "</hierarchy>" in out else ""


def ui_texts(xml: str) -> dict[str, str]:
    out = {}
    if not xml:
        return out
    for n in ET.fromstring(xml).iter("node"):
        rid = n.get("resource-id", "")
        if rid:
            out[rid.split("/")[-1]] = n.get("text") or n.get("content-desc") or ""
    return out


def _raw_header_at(raw: bytes) -> int:
    """Offset of the raw screencap header. Foldables (several displays, no -d) print a text warning first; the header
    (w, h, format[, colorspace]: 12 or 16 bytes) starts right after one of its newlines."""
    for off in [0] + [i + 1 for i in range(min(len(raw), 4096)) if raw[i] == 0x0A]:
        if len(raw) < off + 12:
            break
        w, h = int.from_bytes(raw[off:off + 4], "little"), int.from_bytes(raw[off + 4:off + 8], "little")
        if 0 < w <= 10000 and 0 < h <= 10000 and len(raw) - off - w * h * 4 in (12, 16):
            return off
    raise RuntimeError("screencap: no raw header found")


def screenshot() -> tuple[int, int, bytes]:
    raw = adb("exec-out", "screencap", binary=True, timeout=30)
    off = _raw_header_at(raw)
    w, h = int.from_bytes(raw[off:off + 4], "little"), int.from_bytes(raw[off + 4:off + 8], "little")
    return w, h, raw[len(raw) - w * h * 4:]


def screenshot_png() -> bytes:
    """PNG of the current screen, with the foldable multi-display warning (text before the PNG) stripped."""
    png = adb("exec-out", "screencap", "-p", binary=True, timeout=30)
    return png[png.find(b"\x89PNG"):] if b"\x89PNG" in png else png


def screen_diff(a: tuple[int, int, bytes], b: tuple[int, int, bytes], skip_top: int = 150) -> float:
    """Fraction of sampled pixels that differ (status bar skipped: its clock changes)."""
    w, h, pa = a
    _, _, pb = b
    if len(pa) != len(pb):
        return 1.0
    diff = total = 0
    for y in range(skip_top, h, 8):
        row = y * w * 4
        for x in range(0, w, 8):
            i = row + x * 4
            total += 1
            if abs(pa[i] - pb[i]) + abs(pa[i + 1] - pb[i + 1]) + abs(pa[i + 2] - pb[i + 2]) > 30:
                diff += 1
    return diff / max(total, 1)


def start_activity(component: str, extra: str = "") -> None:
    sh(f"am start -W -S -n {component} {extra}", timeout=60)


def launch(package: str) -> None:
    sh(f"monkey -p {package} -c android.intent.category.LAUNCHER 1", check=False, timeout=60)


def force_stop(package: str) -> None:
    sh(f"am force-stop {package}", check=False)


def foreground_package() -> str:
    out = sh("dumpsys activity activities | grep -E 'topResumedActivity|mResumedActivity' | head -1", check=False)
    m = re.search(r"\s([\w.]+)/", out)
    return m.group(1) if m else ""


FIRST_RUN_BUTTONS = [
    "accept", "agree", "i agree", "continue", "next", "skip", "ok", "got it", "allow", "while using the app",
    "only this time", "not now", "no thanks", "later", "close", "done", "start", "get started", "dismiss",
    "maybe later", "don't allow", "deny", "cancel", "understood", "i understand", "confirm", "proceed",
]


def dismiss_first_run(max_steps: int = 12, vox: Vox | None = None, log=print) -> list[str]:
    """Click through onboarding / permission dialogs by button text. Returns the labels clicked.

    Reads the screen through the VOX service's own `dump` op, not uiautomator: a uiautomator dump suppresses and
    reconnects every accessibility service, which leaves the service with a stale window list for a moment and
    cancels gestures dispatched meanwhile.
    """
    vox = vox or Vox()
    clicked = []
    for _ in range(max_steps):
        try:
            nodes = vox.control("dump").get("nodes", [])
        except Exception:
            time.sleep(1)
            continue
        # Prefer a clickable node; else a labelled child of one (Compose puts the text on a non-clickable child).
        hits = [n for n in nodes if (n["text"] or n["desc"]).strip().lower() in FIRST_RUN_BUTTONS]
        hits.sort(key=lambda n: not (n.get("click") or n["cls"].endswith("Button")))
        target = ((hits[0]["text"] or hits[0]["desc"]).strip().lower(), hits[0]["bounds"]) if hits else None
        if not target or clicked[-2:] == [target, target]:   # nothing to click, or the same button isn't moving on
            break
        x1, y1, x2, y2 = map(int, target[1].split(","))
        sh(f"input tap {(x1 + x2) // 2} {(y1 + y2) // 2}")
        clicked.append(target)
        log(f"first-run: tapped '{target[0]}'")
        time.sleep(1.5)
    return [t[0] for t in clicked]


def node_by_id(vox: Vox, suffix: str) -> dict | None:
    return next((n for n in vox.control("dump").get("nodes", []) if n["id"].endswith(suffix)), None)


def tap_node(n: dict) -> None:
    x1, y1, x2, y2 = map(int, n["bounds"].split(","))
    sh(f"input tap {(x1 + x2) // 2} {(y1 + y2) // 2}")


def prime_organic_maps(vox: Vox, log=print, timeout: float = 300) -> None:
    """Organic Maps needs its world overview map (about 69 MB, from the network) before it shows a map."""
    launch("app.organicmaps")
    time.sleep(4)
    b = node_by_id(vox, "btn_download_resources")
    if not b:
        return
    log("Organic Maps: downloading the world overview map")
    tap_node(b)
    end = time.time() + timeout
    while time.time() < end:
        time.sleep(3)
        if not node_by_id(vox, "btn_download_resources") and not node_by_id(vox, "head_message"):
            return
    raise RuntimeError("Organic Maps world map download did not finish")
