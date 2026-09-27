"""Capture the current screen of a USB-connected phone for the real-screen test set (see harvest_device.sh).

    VOX_SERIAL=<serial> python3 suite/harvest_device.py --tag youtube/home [--app youtube] [--out-dir DIR]
    VOX_SERIAL=<serial> python3 suite/harvest_device.py --status          # what source would be used

Per capture it writes <out-dir>/png/<id>.png, <out-dir>/xml/<id>.xml and one line in <out-dir>/screens.jsonl.
The caller (a person, or harvest_device.sh) drives the phone to each screen; this script never taps anything.

Option source, best first:
  1. "app": Canti/VOX is installed and its accessibility service is running -> the app's own `targets` op over the
     debug socket (the same code path as on the emulator; adb forward tcp:$VOX_SOCKET_PORT -> localabstract:vox-debug).
     It is queried BEFORE uiautomator runs, because a uiautomator dump disconnects accessibility services for ~2 s.
  2. "port": otherwise the options come from suite/tree_targets.py, a Python port of Targets.kt / ScreenSummarizer.kt
     over the `uiautomator dump` XML (known gaps are listed in that file).
Either way the uiautomator XML is saved, and with source "app" the port's options are recorded too
(`port_options`) so the port's fidelity can be measured on real screens.

--no-uiautomator: source "app" only, no XML. A `uiautomator dump` does not just pause the VOX accessibility service:
on the Z Flip it STOPS and restarts it, and the Pico BLE link (owned by the service) goes down with it. Use this mode
while the Pico drives the app. The row has "xml": null, no port_options, and "capture_mode": "no-uiautomator".

Personal data: the PNG, the XML and the texts inside screens.jsonl are private. The default out dir is
finetune/data/real-targets-v1/zflip/raw, which is gitignored; keep it there.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path

import tree_targets as tt
from voxlib import SERIAL, Vox, adb, screenshot_png, sh

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "finetune" / "data" / "real-targets-v1" / "zflip" / "raw"
VOCAB_KT = ROOT / "android" / "app" / "src" / "main" / "java" / "ai" / "vox" / "companion" / "Vocab.kt"
# Launcher labels for apps missing from Vocab.APPS (the app uses PackageManager.getApplicationLabel).
LABELS = {"md.obsidian": "Obsidian", "org.mozilla.fennec_fdroid": "Fennec", "app.rvx.android.youtube": "YouTube",
          "app.rvx.android.apps.youtube.music": "YouTube Music", "com.discord": "Discord", "com.facebook.katana": "Facebook",
          "com.twitter.android": "X", "com.sec.android.app.launcher": "One UI Home", "com.android.chrome": "Chrome",
          "com.sec.android.app.sbrowser": "Samsung Internet"}


def vocab_apps() -> dict[str, str]:
    """Vocab.APPS (StateBuilder.appName prefers it over the launcher label)."""
    s = VOCAB_KT.read_text()
    i = s.find("val APPS")
    block = s[i: s.find(")", s.find("linkedMapOf(", i) + 12)]
    return dict(re.findall(r'"([\w.]+)" to "([^"]*)"', block))


def screen_size() -> tuple[int, int]:
    out = sh("wm size", check=False)
    m = re.findall(r"(\d+)x(\d+)", out)
    w, h = map(int, m[-1]) if m else (1080, 2400)   # "Override size" (last) wins over "Physical size"
    return w, h


def keyboard_open() -> bool:
    return "mInputShown=true" in sh("dumpsys input_method", check=False)


def music_active() -> bool:
    return "state:started" in sh("dumpsys audio", check=False)


def launcher_pkgs() -> set[str]:
    out = sh("cmd package resolve-activity --brief --user 0 -a android.intent.action.MAIN -c android.intent.category.HOME",
             check=False).strip().splitlines()
    return {out[-1].split("/")[0]} if out and "/" in out[-1] else set()


def foreground_pkg() -> str:
    out = sh("dumpsys activity activities | grep -m1 topResumedActivity", check=False)
    m = re.search(r"\s([\w.]+)/", out)
    return m.group(1) if m else ""


def app_service_up() -> bool:
    svc = sh("settings get secure enabled_accessibility_services", check=False)
    return "ai.vox.companion" in svc


def ui_dump() -> str:
    out = adb("exec-out", "uiautomator", "dump", "/dev/tty", check=False, timeout=40)
    return out[: out.rfind("</hierarchy>") + len("</hierarchy>")] if "</hierarchy>" in out else ""


def screen_awake() -> bool:
    """False when the phone is dozing/asleep (e.g. a Flip folded shut): the capture would be black with no tree."""
    return "mWakefulness=Awake" in sh("dumpsys power | grep mWakefulness=", check=False)


def capture_app_only(tag: str, app: str, out_dir: Path) -> dict:
    """PNG + the app's `targets` op reply; never runs uiautomator (keeps the service and its BLE link up)."""
    if not screen_awake():
        raise SystemExit("phone screen is off or folded shut (mWakefulness != Awake): nothing captured")
    if not app_service_up():
        raise SystemExit("--no-uiautomator needs the VOX accessibility service: nothing captured")
    w, h = screen_size()
    app_t = Vox().control("targets")
    png = screenshot_png()
    kb, music, fg = keyboard_open(), music_active(), foreground_pkg()
    sid = _next_id(out_dir, app)
    (out_dir / "png").mkdir(parents=True, exist_ok=True)
    (out_dir / "png" / f"{sid}.png").write_bytes(png)
    opts = app_t["options"]
    bounds = [list(map(int, t["bounds"].split(","))) for t in app_t.get("targets", [])] + [None]
    rec = {"screen_id": sid, "tag": tag, "app": app, "package": app_t["package"], "app_name": app_t.get("app_name"),
           "screen_text": app_t["screen_text"], "state_template": app_t.get("state_template"), "options": opts,
           "bounds": bounds, "options_source": "tree", "tree_source": "app", "capture_mode": "no-uiautomator",
           "screenshot": f"png/{sid}.png", "xml": None, "keyboard_open": kb, "music_active": music, "foreground": fg,
           "serial": SERIAL, "screen_size": [w, h], "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "step": "manual (phone)"}
    with (out_dir / "screens.jsonl").open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"  {sid:22s} {tag:30s} {len(opts) - 1:2d} opts source=app (no uiautomator) {rec['screen_text']}")
    return rec


def _next_id(out_dir: Path, app: str) -> str:
    screens = out_dir / "screens.jsonl"
    used = {json.loads(l)["screen_id"] for l in screens.read_text().splitlines() if l.strip()} if screens.exists() else set()
    i = 1
    while f"zf-{app}-{i:02d}" in used:
        i += 1
    return f"zf-{app}-{i:02d}"


def capture(tag: str, app: str, out_dir: Path, force_port: bool = False) -> dict:
    if not screen_awake():
        raise SystemExit("phone screen is off or folded shut (mWakefulness != Awake): nothing captured")
    w, h = screen_size()
    source = "port"
    app_t = None
    if not force_port and app_service_up():
        try:
            vox = Vox()
            app_t = vox.control("targets")
            source = "app"
        except Exception as e:  # noqa: BLE001
            print(f"  app targets op failed ({e}); using the port")
    png = screenshot_png()   # foldables print a multi-display warning first; stripped there
    kb, music, fg, launchers = keyboard_open(), music_active(), foreground_pkg(), launcher_pkgs()
    xml = ui_dump()
    if not xml:
        raise SystemExit("uiautomator dump returned no tree (screen locked, or the app never went idle): nothing saved")
    if source == "app":
        time.sleep(2.5)   # uiautomator disconnected the service; let it come back before the next capture
    roots = tt.parse_uiautomator(xml) if xml else []
    root = tt.pick_root(roots, w, h)
    pkg = (root.pkg if root else "") or fg
    port_targets = tt.build(root, w, h, tt.covers_for(roots, root))
    port_screen = tt.screen_line(root, pkg, w, h, kb, launchers, music)
    name = vocab_apps().get(pkg) or LABELS.get(pkg) or pkg
    out_dir.mkdir(parents=True, exist_ok=True)
    screens = out_dir / "screens.jsonl"
    sid = _next_id(out_dir, app)
    (out_dir / "png").mkdir(exist_ok=True)
    (out_dir / "xml").mkdir(exist_ok=True)
    (out_dir / "png" / f"{sid}.png").write_bytes(png)
    (out_dir / "xml" / f"{sid}.xml").write_text(xml)
    if source == "app":
        opts = app_t["options"]
        bounds = [list(map(int, t["bounds"].split(","))) for t in app_t.get("targets", [])] + [None]
        rec_app = {"package": app_t["package"], "app_name": app_t.get("app_name"), "screen_text": app_t["screen_text"],
                   "state_template": app_t.get("state_template")}
    else:
        opts = tt.options(port_targets)
        bounds = [t["bounds"] for t in port_targets] + [None]
        rec_app = {"package": pkg, "app_name": name, "screen_text": port_screen,
                   "state_template": tt.state_template(name, pkg, port_screen)}
    rec = {"screen_id": sid, "tag": tag, "app": app, **rec_app, "options": opts, "bounds": bounds,
           "options_source": "tree", "tree_source": source, "screenshot": f"png/{sid}.png", "xml": f"xml/{sid}.xml",
           "port_options": tt.options(port_targets), "port_screen_text": port_screen,
           "keyboard_open": kb, "music_active": music, "foreground": fg, "serial": SERIAL, "screen_size": [w, h],
           "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "step": "manual (phone)"}
    with screens.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"  {sid:22s} {tag:30s} {len(opts) - 1:2d} opts source={source} {rec['screen_text']}")
    return rec


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--tag", default="")
    p.add_argument("--app", default="")
    p.add_argument("--out-dir", default=str(DEFAULT_OUT))
    p.add_argument("--status", action="store_true")
    p.add_argument("--port-only", action="store_true", help="ignore the app even if its service is running")
    p.add_argument("--no-uiautomator", action="store_true",
                   help="PNG + the app's targets op only, no XML (a uiautomator dump restarts the service and drops BLE)")
    a = p.parse_args()
    if a.status:
        print(json.dumps({"serial": SERIAL, "size": screen_size(), "foreground": foreground_pkg(),
                          "vox_service": app_service_up(), "keyboard_open": keyboard_open(),
                          "socket_port": os.environ.get("VOX_SOCKET_PORT", "7788")}))
        return
    if not a.tag:
        raise SystemExit("--tag is required")
    if a.no_uiautomator and a.port_only:
        raise SystemExit("--no-uiautomator and --port-only exclude each other")
    if a.no_uiautomator:
        capture_app_only(a.tag, a.app or a.tag.split("/")[0], Path(a.out_dir))
    else:
        capture(a.tag, a.app or a.tag.split("/")[0], Path(a.out_dir), a.port_only)


if __name__ == "__main__":
    main()
