"""Real-screen capture for the intent-cursor test set (finetune/data/real-targets-v1).

    python3 suite/harvest_real.py --apps settings,clock,... [--out-dir DIR] [--append]
    python3 suite/harvest_real.py --peek [--png FILE]     # print the current screen's options (walk design)
    python3 suite/harvest_real.py --capture TAG --app APP --step "how"   # capture the current screen once (manual driving)

Like harvest.py (which it reuses for the launcher, the fixture and the five stand-ins) but every step also saves:
  - a PNG screenshot (`adb exec-out screencap -p`) at <out-dir>/png/<screen_id>.png;
  - the option list from the app's own `targets` debug op (Targets.build on the service's tree snapshot), with each
    option's screen bounds from that same Target list, plus `app_name` and `state_template` (the exact "target"
    question state Targets.stateText builds, with {UTTERANCE} for the phrase);
  - the `harvest` op's screen summary and the `dump` op's visible nodes (provenance / debugging).
The `targets` op runs before and after the screenshot; `stable` is false when the two lists differ (the screen was
still changing, so the PNG may not match the options exactly).

Records go to <out-dir>/screens.jsonl, one per screen. A step whose option list and screen line equal the previous
capture's is kept but marked `duplicate_of`.

Never uses uiautomator (it disconnects the accessibility service; see ../README.md). Runs inside ./dev (adb on PATH).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from harvest import PKGS as HARVEST_PKGS, key, swipe, tap_id, tap_text, walks as harvest_walks
from servers import WebServer
from voxlib import SERIAL, Vox, adb, dismiss_first_run, force_stop, launch, sh, start_activity

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "finetune" / "data" / "real-targets-v1" / "emulator" / "raw"
W, H = 1080, 2400


# --- small step helpers (each returns an action description) -----------------------------------------------------------

def nodes(vox: Vox) -> list[dict]:
    return vox.control("dump").get("nodes", [])


def _tap_bounds(b: str) -> None:
    x1, y1, x2, y2 = map(int, b.split(","))
    sh(f"input tap {(x1 + x2) // 2} {(y1 + y2) // 2}")


def tap_contains(vox: Vox, *subs: str, nth: int = 0) -> str:
    """Tap the nth visible node whose text or description contains one of subs (case-insensitive), clickable first."""
    subs_l = [s.lower() for s in subs]
    hits = [n for n in nodes(vox) if any(s in (n["text"] + " " + n["desc"]).lower() for s in subs_l)]
    hits.sort(key=lambda n: not n.get("click"))
    if len(hits) <= nth:
        return f"tap ~{subs[0]!r} (not found)"
    _tap_bounds(hits[nth]["bounds"])
    return f"tap ~'{hits[nth]['text'] or hits[nth]['desc']}'"


def tap_xy(fx: float, fy: float) -> str:
    sh(f"input tap {int(W * fx)} {int(H * fy)}")
    return f"tap ({fx:.2f},{fy:.2f})"


def long_xy(fx: float, fy: float) -> str:
    x, y = int(W * fx), int(H * fy)
    sh(f"input swipe {x} {y} {x} {y} 900")
    return f"long press ({fx:.2f},{fy:.2f})"


def type_text(t: str) -> str:
    sh("input text " + t.replace(" ", "%s"))
    return f"type {t!r}"


def start(component: str, extra: str = "") -> str:
    start_activity(component, extra)
    return f"start {component}"


def launch_pkg(pkg: str) -> str:
    launch(pkg)
    return f"launch {pkg}"


def am(args: str) -> str:
    sh(f"am start -W {args}", check=False)
    return f"am start {args}"


def seq(*fns) -> str:
    out = []
    for f in fns:
        out.append(f())
        time.sleep(1.2)
    return "; ".join(out)


# --- walks over the stock AOSP apps and VOX itself --------------------------------------------------------------------

STOCK_PKGS = {
    "settings": "com.android.settings", "contacts": "com.android.contacts", "clock": "com.android.deskclock",
    "files": "com.android.documentsui", "camera": "com.android.camera2", "messages": "com.android.messaging",
    "calendar": "com.android.calendar", "dialer": "com.android.dialer", "gallery3d": "com.android.gallery3d",
    "browser": "org.chromium.webview_shell", "vox": "ai.vox.companion",
}


def stock_walks(vox: Vox, web: WebServer) -> dict[str, list]:
    K = lambda k: lambda: key(k)  # noqa: E731
    S = lambda d: lambda: swipe(d)  # noqa: E731
    T = lambda *s, nth=0: lambda: tap_contains(vox, *s, nth=nth)  # noqa: E731
    X = lambda fx, fy: lambda: tap_xy(fx, fy)  # noqa: E731
    return {
        "settings": [
            ("main", lambda: start("com.android.settings/.Settings")),
            ("main scrolled", S("up")),
            ("main bottom", S("up")),
            ("network", lambda: seq(lambda: start("com.android.settings/.Settings"), T("Network & internet"))),
            ("internet", T("Internet")),
            ("connected devices", lambda: am("-a android.settings.BLUETOOTH_SETTINGS")),
            ("display", lambda: am("-a android.settings.DISPLAY_SETTINGS")),
            ("display scrolled", S("up")),
            ("screen timeout dialog", T("Screen timeout")),
            ("sound", lambda: seq(K("KEYCODE_BACK"), lambda: am("-a android.settings.SOUND_SETTINGS"))),
            ("apps", lambda: am("-a android.settings.APPLICATION_SETTINGS")),
            ("app info", lambda: am("-a android.settings.APPLICATION_DETAILS_SETTINGS -d package:org.videolan.vlc")),
            ("accessibility", lambda: am("-a android.settings.ACCESSIBILITY_SETTINGS")),
            ("battery", lambda: am("-a android.intent.action.POWER_USAGE_SUMMARY")),
            ("date time", lambda: am("-a android.settings.DATE_SETTINGS")),
            ("search", lambda: seq(lambda: start("com.android.settings/.Settings"), T("Search settings"))),
            ("search typed", lambda: type_text("wifi")),
            ("about", lambda: seq(K("KEYCODE_BACK"), K("KEYCODE_BACK"), lambda: am("-a android.settings.DEVICE_INFO_SETTINGS"))),
        ],
        "clock": [
            ("alarms", lambda: seq(lambda: launch_pkg("com.android.deskclock"), T("Alarm"))),
            ("alarm expanded", T("Mon", "Tue", "Wed", "Thu", "Fri")),
            ("add alarm", T("Add alarm")),
            ("add alarm keyboard", T("Switch to text input mode for the time input")),
            ("clock tab", lambda: seq(K("KEYCODE_BACK"), K("KEYCODE_BACK"), T("Clock"))),
            ("timer", T("Timer")),
            ("timer typed", lambda: seq(T("5"), T("0"))),
            ("stopwatch", T("Stopwatch")),
            ("stopwatch running", T("Start")),
            ("bedtime", T("Bedtime")),
            ("overflow menu", T("More options")),
        ],
        "contacts": [
            ("list", lambda: launch_pkg("com.android.contacts")),
            ("new contact", T("Create contact", "Create new contact")),
            ("new contact scrolled", S("up")),
            ("drawer", lambda: seq(K("KEYCODE_BACK"), K("KEYCODE_BACK"), T("Open navigation drawer", "Show navigation drawer"))),
            ("search", lambda: seq(K("KEYCODE_BACK"), T("Search contacts", "Search"))),
            ("search typed", lambda: type_text("ann")),
        ],
        "dialer": [
            ("main", lambda: launch_pkg("com.android.dialer")),
            ("keypad", T("key pad", "dial pad", "Dialpad")),
            ("typed number", lambda: type_text("5551234")),
            ("contacts tab", lambda: seq(K("KEYCODE_BACK"), T("Contacts"))),
            ("menu", T("More options")),
        ],
        "messages": [
            ("list", lambda: launch_pkg("com.android.messaging")),
            ("new conversation", T("Start new conversation", "Start chat")),
            ("recipient typed", lambda: type_text("5551234")),
            ("menu", lambda: seq(K("KEYCODE_BACK"), K("KEYCODE_BACK"), T("More options"))),
            ("settings", T("Settings")),
        ],
        "calendar": [
            ("month", lambda: launch_pkg("com.android.calendar")),
            ("view menu", T("Month", "Week", "Day", "Agenda", nth=0)),
            ("day view", T("Day")),
            ("agenda", lambda: seq(T("Day", "Week", "Month", nth=0), T("Agenda"))),
            ("new event", T("New event", "Create event")),
            ("new event keyboard", T("Event name")),
            ("more options", lambda: seq(K("KEYCODE_BACK"), K("KEYCODE_BACK"), K("KEYCODE_BACK"), T("More options"))),
        ],
        "files": [
            ("recent", lambda: launch_pkg("com.android.documentsui")),
            ("drawer", T("Show roots")),
            ("downloads", T("Downloads")),
            ("images", lambda: seq(T("Show roots"), T("Images"))),
            ("images folder", T("Pictures", "VOX")),
            ("sort menu", T("Sort by", "More options")),
            ("search", lambda: seq(K("KEYCODE_BACK"), T("Search"))),
        ],
        "gallery3d": [
            ("albums", lambda: launch_pkg("com.android.gallery3d")),
            ("album", X(0.25, 0.25)),
            ("photo", X(0.2, 0.2)),
            ("photo controls", X(0.5, 0.5)),
        ],
        "browser": [
            ("page", lambda: am(f"-a android.intent.action.VIEW -d {web.url} -n org.chromium.webview_shell/.WebViewBrowserActivity")),
            ("page scrolled", S("up")),
            ("url field", T("Enter URL", "url")),
            ("menu", lambda: seq(K("KEYCODE_BACK"), T("More options"))),
        ],
        "camera": [
            ("start", lambda: launch_pkg("com.android.camera2")),
        ],
        "vox": [
            ("status", lambda: (sh("am start -W -n ai.vox.companion/.MainActivity", check=False), "start VOX (no -S)")[1]),
            ("scrolled", S("up")),
        ],
    }


# --- capture -----------------------------------------------------------------------------------------------------------

def capture(vox: Vox, tag: str, app: str, action: str, out_dir: Path, screen_id: str) -> dict:
    t1 = vox.control("targets")
    png = adb("exec-out", "screencap", "-p", binary=True, timeout=30)
    t2 = vox.control("targets")
    rec = vox.control("harvest", tag=tag)["record"]
    dump = vox.control("dump")
    (out_dir / "png").mkdir(parents=True, exist_ok=True)
    (out_dir / "png" / f"{screen_id}.png").write_bytes(png)
    b1 = [t["bounds"] for t in t1.get("targets", [])]
    b2 = [t["bounds"] for t in t2.get("targets", [])]
    opts = t1["options"]
    bounds = [list(map(int, b.split(","))) for b in b1] + [None]   # NONE_OPTION has no box
    assert len(bounds) == len(opts), (len(bounds), len(opts))
    return {
        "screen_id": screen_id, "tag": tag, "app": app, "package": t1["package"], "app_name": t1.get("app_name"),
        "state_template": t1.get("state_template"), "screen_text": t1["screen_text"], "options": opts,
        "bounds": bounds, "stable": opts == t2["options"] and b1 == b2, "screenshot": f"png/{screen_id}.png",
        "step": action, "summary": rec.get("summary"), "window": dump.get("window"), "nodes": dump.get("nodes"),
        "serial": SERIAL, "screen_size": [W, H], "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--apps", default="")
    p.add_argument("--out-dir", default=str(DEFAULT_OUT))
    p.add_argument("--append", action="store_true", help="append to screens.jsonl instead of refusing to overwrite")
    p.add_argument("--peek", action="store_true")
    p.add_argument("--png", default="")
    p.add_argument("--capture", default="", help="capture the current screen once under this tag (app 'manual')")
    p.add_argument("--settle", type=float, default=2.5)
    p.add_argument("--app", default="manual", help="with --capture: the app key for the screen id")
    p.add_argument("--step", default="manual", help="with --capture: how the screen was reached (provenance)")
    a = p.parse_args()
    vox = Vox()
    out_dir = Path(a.out_dir)
    if a.peek:
        t = vox.control("targets")
        print(t.get("app_name"), t["package"], "|", t["screen_text"])
        for i, (o, tt) in enumerate(zip(t["options"], t.get("targets", []) + [{"bounds": "-"}])):
            print(f"  {i:2d} {o:55s} {tt['bounds']}")
        for n in nodes(vox):
            if n["text"] or n["desc"]:
                print(f"     . {n['cls']:22s} {(n['text'] or n['desc'])[:50]!r:54s} click={n['click']} {n['bounds']}")
        if a.png:
            Path(a.png).write_bytes(adb("exec-out", "screencap", "-p", binary=True, timeout=30))
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    screens = out_dir / "screens.jsonl"
    existing = [json.loads(l) for l in screens.read_text().splitlines() if l.strip()] if screens.exists() else []
    if existing and not a.append:
        raise SystemExit(f"{screens} exists; pass --append")
    used = {r["screen_id"] for r in existing}
    last = existing[-1] if existing else None

    def next_id(app: str) -> str:
        i = 1
        while f"emu-{app}-{i:02d}" in used:
            i += 1
        used.add(f"emu-{app}-{i:02d}")
        return f"emu-{app}-{i:02d}"

    def write(r: dict) -> None:
        nonlocal last
        if last and last["options"] == r["options"] and last["screen_text"] == r["screen_text"] and last["package"] == r["package"]:
            r["duplicate_of"] = last["screen_id"]
        with screens.open("a") as f:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"  {r['screen_id']:22s} {r['tag']:32s} {len(r['options']) - 1:2d} opts stable={r['stable']}"
              f"{' DUP ' + r['duplicate_of'] if r.get('duplicate_of') else ''}  {r['screen_text']}")
        last = r

    if a.capture:
        write(capture(vox, f"{a.app}/{a.capture}", a.app, a.step, out_dir, next_id(a.app)))
        return
    web = WebServer(8766)
    try:
        plan = {**harvest_walks(vox, web), **stock_walks(vox, web)}
        pkgs = {**HARVEST_PKGS, **STOCK_PKGS}
        for app in a.apps.split(","):
            if app in pkgs and app != "vox":
                force_stop(pkgs[app])
            for i, (name, fn) in enumerate(plan[app]):
                try:
                    action = fn()
                except Exception as e:  # a missing element should not end the whole walk
                    action = f"error: {e}"
                time.sleep(a.settle)
                if i == 0:
                    dismiss_first_run(vox=vox, log=lambda m: print(f"    {m}"))
                write(capture(vox, f"{app}/{name}", app, action, out_dir, next_id(app)))
    finally:
        web.close()
        sh("input keyevent KEYCODE_HOME", check=False)


if __name__ == "__main__":
    main()
