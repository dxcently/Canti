"""Emulator harvest for real-targets-v2 batch 3: a locked test set of unseen apps and extra training coverage
(social / chat / feed apps and cross-app surfaces). Emulator only (VOX_SERIAL must be emulator-*).

    python3 suite/harvest_v3.py fetch PKG...                  # newest x86_64 build from F-Droid -> .state/apks-extra (sha256)
    python3 suite/harvest_v3.py install [--no-grant] PKG...   # adb install onto the emulator
    python3 suite/harvest_v3.py peek                          # current screen's options + visible nodes (driving)
    python3 suite/harvest_v3.py cap --out DIR --app KEY --tag NAME --step "how"   # capture the current screen once
    python3 suite/harvest_v3.py explore --out DIR --apps pkg=key,... [--per-app N]  # harvest_explore.Walker, raw capture
    python3 suite/harvest_v3.py manifest --out DIR            # (re)write DIR/manifest.json

Every record is harvest_real.capture's record (PNG, `targets` options + bounds, state template, `dump` nodes) plus
  raw_tree: the `dump raw=true` reply (pre-order app-window tree: depth, class, id, text, desc, visible, important,
            clickable, child count, bounds) so option lists can be re-serialized offline when the option text format
            changes;
  focus:    the window manager's focused window / app;
  build:    the Canti build id (see build.json in the out dir).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import harvest_explore
from apks import REPO, _get, sha256

from voxlib import SERIAL, SERVICE, Vox, adb, sh

assert SERIAL.startswith("emulator-"), f"harvest_v3 is emulator-only (VOX_SERIAL={SERIAL})"
SUITE = Path(__file__).resolve().parent
ANDROID = SUITE.parent
ROOT = ANDROID.parent
INDEX = ANDROID / ".state" / "fdroid" / "index-v2.json"
APK_DIR = ANDROID / ".state" / "apks-extra"
LOCK = APK_DIR / "lock-v3.json"
CANTI_APK = ANDROID / ".state" / "canti-harvest" / "canti-debug-20260926-2237.apk"
V2_EMU = ROOT / "finetune" / "data" / "real-targets-v2" / "emulator"


# Canti builds seen on emulator-5580 during this harvest (tag -> provenance).
BUILDS = {
    "canti-debug-20260926-2237": "app/build debug APK built 22:37 EDT (all sources to 22:31); installed by the harvest at 22:58 EDT; "
                                 "sha256 c07dc5e13367327f2708a8ca38959de043468aca821a7d922c558ab8d25cf40b; single option format",
    "scroll-2337": "the scroll agent's debug build, install -r at 23:37:55 EDT (device lastUpdateTime 2026-09-27 03:26:40); "
                   "base.apk sha256 61b2cbb43895ee55e2410903f17360046ed7c86ee7cc719d84b94ba3a9526613; v1 options carry ', k of n'",
    "shared-2353": "the app agent's dual-format debug build (targets op returns options_v1/targets_v1 and options_v2/targets_v2; "
                 "rawDump adds focusable/editable/scrollable/focused/selected/collection_item/rows/cols); app-debug.apk "
                 "built 23:53:07 EDT, installed 23:53:15 EDT (device lastUpdateTime 2026-09-27 03:42:00); sha256 "
                 "671b7424f13aa617661caa50835d2baf0ed3fec19a0fa22d35f626df4620e08a; copy at "
                 "android/.state/canti-harvest/canti-debug-20260926-2353-dual.apk",
}


# --- build provenance --------------------------------------------------------------------------------------------------

def build_info() -> dict:
    head = (ROOT / ".git" / "refs" / "heads" / "main")
    src = ANDROID / "app" / "src" / "main"
    newest = max(src.rglob("*.kt"), key=lambda p: p.stat().st_mtime)
    upd = re.search(r"lastUpdateTime=(\S+ \S+)", sh("dumpsys package ai.vox.companion", check=False))
    return {
        "build_id": "canti-debug-20260926-2237",
        "apk": str(CANTI_APK.relative_to(ROOT)), "apk_sha256": sha256(CANTI_APK),
        "apk_built_local": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(CANTI_APK.stat().st_mtime)),
        "git_head_main": head.read_text().strip() if head.exists() else None,
        "git_note": "working tree has uncommitted app changes newer than HEAD; the APK sha256 is the exact build id",
        "newest_kt_source": f"{newest.relative_to(ANDROID)} "
                            f"{time.strftime('%Y-%m-%dT%H:%M', time.localtime(newest.stat().st_mtime))}",
        "installed_on": SERIAL, "installed_at_device_clock_utc": upd.group(1) if upd else None,
        "device_clock_note": "the emulator clock runs about 11 min behind the host; captured_at is host local time (EDT)",
    }


# --- capture -----------------------------------------------------------------------------------------------------------

def canti_last_update() -> str:
    m = re.search(r"lastUpdateTime=(\S+ \S+)", sh("dumpsys package ai.vox.companion | grep lastUpdateTime", check=False))
    return m.group(1) if m else ""


def canti_sha() -> str:
    path = sh("pm path ai.vox.companion", check=False).splitlines()[0].split(":", 1)[1].strip()
    return sh(f"sha256sum {path}", check=False, timeout=120).split()[0]


def check_sha() -> str:
    """Start of every app session: the installed Canti APK must be the expected one (HARVEST_EXPECT_SHA)."""
    got, want = canti_sha(), os.environ.get("HARVEST_EXPECT_SHA")
    if want and got != want:
        raise SystemExit(f"STOP: installed Canti APK sha256 {got} != expected {want} (someone reinstalled)")
    print(f"    canti apk sha256 {got[:16]}... ok", flush=True)
    return got


def anr_up() -> bool:
    """A system "isn't responding" dialog is on screen (its window title is "Application Not Responding: <pkg>")."""
    return "Application Not Responding" in sh("dumpsys window windows", check=False, timeout=30)


def _fmt_keys(t: dict) -> dict:
    return {k: v for k, v in t.items() if k.startswith(("options_", "targets_"))}


def capture(vox: Vox, tag: str, app: str, action: str, out_dir: Path, screen_id: str) -> dict:
    """harvest_real.capture's record + every option format the build returns (options_v1/targets_v1, options_v2/...,
    with per-target bounds), the raw tree, the focused window and the build tag. Refuses to capture if the Canti install
    changed (HARVEST_EXPECT_UPDATE = its lastUpdateTime)."""
    if anr_up():
        raise RuntimeError("ANR dialog on screen: capture refused")
    upd = canti_last_update()
    want = os.environ.get("HARVEST_EXPECT_UPDATE")
    if want and upd != want:
        raise SystemExit(f"Canti build changed under the harvest: lastUpdateTime {upd} != {want}")
    # hide Canti's head so it covers no target in the png (it comes back by itself after 10 s if this dies); an older
    # build without badge_hide answers ok: false and the capture goes on with the head showing
    hidden = vox.control("badge_hide", hide=True, ms=10000).get("ok", False)
    if hidden:
        time.sleep(0.25)   # a frame or two for the overlay window to redraw
    try:
        t1 = vox.control("targets")
        png = adb("exec-out", "screencap", "-p", binary=True, timeout=30)
        t2 = vox.control("targets")
    finally:
        if hidden:
            vox.control("badge_hide", hide=False)
    rec = vox.control("harvest", tag=tag)["record"]
    dump = vox.control("dump")
    raw = vox.control("dump", raw=True)
    (out_dir / "png").mkdir(parents=True, exist_ok=True)
    (out_dir / "png" / f"{screen_id}.png").write_bytes(png)
    b1 = [t["bounds"] for t in t1.get("targets", [])]
    b2 = [t["bounds"] for t in t2.get("targets", [])]
    opts = t1["options"]
    bounds = [list(map(int, b.split(","))) for b in b1] + [None]
    assert len(bounds) == len(opts), (len(bounds), len(opts))
    foc = sh("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp' | head -2", check=False)
    return {
        "screen_id": screen_id, "tag": tag, "app": app, "package": t1["package"], "app_name": t1.get("app_name"),
        "state_template": t1.get("state_template"), "screen_text": t1["screen_text"], "options": opts,
        "option_format": t1.get("option_format"), "bounds": bounds,
        "stable": opts == t2["options"] and b1 == b2 and _fmt_keys(t1) == _fmt_keys(t2),
        "screenshot": f"png/{screen_id}.png", "step": action, "summary": rec.get("summary"),
        "window": dump.get("window"), "nodes": dump.get("nodes"),
        **_fmt_keys(t1), "targets": t1.get("targets"),
        "raw_tree": raw.get("raw"), "raw_window": raw.get("window"),
        "focus": " | ".join(l.strip() for l in foc.splitlines() if l.strip()),
        "build": os.environ.get("HARVEST_BUILD", "canti-debug-20260926-2237"), "canti_last_update": upd,
        "apk_sha256": os.environ.get("HARVEST_EXPECT_SHA") or "c07dc5e13367327f2708a8ca38959de043468aca821a7d922c558ab8d25cf40b",
        "serial": SERIAL, "screen_size": [1080, 2400], "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def _out(out: str) -> Path:
    p = Path(out)
    if not p.is_absolute():
        p = V2_EMU / out
    p.mkdir(parents=True, exist_ok=True)
    return p


def _load(out_dir: Path) -> list[dict]:
    f = out_dir / "screens.jsonl"
    return [json.loads(l) for l in f.read_text().splitlines() if l.strip()] if f.exists() else []


def _ids(out_dir: Path):
    used = {r["screen_id"] for r in _load(out_dir)}

    def next_id(app: str) -> str:
        i = 1
        while f"emu3-{app}-{i:02d}" in used:
            i += 1
        used.add(f"emu3-{app}-{i:02d}")
        return f"emu3-{app}-{i:02d}"
    return next_id


def _writer(out_dir: Path):
    def write(r: dict) -> None:
        with (out_dir / "screens.jsonl").open("a") as f:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"  {r['screen_id']:26s} {len(r['options']) - 1:2d} opts stable={r['stable']} {r['package']:28s} "
              f"{r['step'][:36]:36s} {r['screen_text']}", flush=True)
    return write


def manifest(out_dir: Path, note: str = "") -> dict:
    rs = _load(out_dir)
    old = json.loads((out_dir / "manifest.json").read_text()) if (out_dir / "manifest.json").exists() else {}
    apps = {}
    for r in rs:
        a = apps.setdefault(r["app"], {"packages": Counter(), "screen_ids": [], "first": r["captured_at"],
                                       "last": r["captured_at"], "unstable": 0, "few_options": 0, "builds": Counter()})
        a["builds"][r.get("build", "?")] += 1
        a["packages"][r["package"]] += 1
        a["screen_ids"].append(r["screen_id"])
        a["last"] = max(a["last"], r["captured_at"]); a["first"] = min(a["first"], r["captured_at"])
        a["unstable"] += not r["stable"]
        a["few_options"] += len(r["options"]) < 3
    m = {
        "batch": out_dir.name, "note": note or old.get("note", ""), "build_2237": old.get("build_2237") or old.get("build") or build_info(),
        "builds": dict(Counter(r.get("build", "?") for r in rs)), "builds_known": BUILDS,
        "serial": SERIAL, "screens": len(rs), "apps": len(apps),
        "captured_from": min((r["captured_at"] for r in rs), default=None),
        "captured_to": max((r["captured_at"] for r in rs), default=None),
        "per_app": {k: {**v, "packages": dict(v["packages"]), "builds": dict(v["builds"]), "n": len(v["screen_ids"])} for k, v in sorted(apps.items())},
        "record_fields": "harvest_real.capture fields + options_<fmt>/targets_<fmt> (every option format the build returns, "
                         "per-target bounds; builds from the dual-format APK on), targets, option_format, raw_tree (dump raw=true), "
                         "raw_window, focus, build, canti_last_update (device clock, ~11 min behind host)",
        "lock": {p: e for p, e in (json.loads(LOCK.read_text()) if LOCK.exists() else {}).items()
                 if any(p in v["packages"] for v in apps.values())},
    }
    (out_dir / "manifest.json").write_text(json.dumps(m, indent=1, ensure_ascii=False))
    return m


# --- APKs ----------------------------------------------------------------------------------------------------------------

def pick(index: dict, pkg: str):
    best = None
    for v in index["packages"][pkg]["versions"].values():
        m = v["manifest"]
        nat = m.get("nativecode")
        if (nat and "x86_64" not in nat) or m.get("usesSdk", {}).get("minSdkVersion", 1) > 35:
            continue
        if best is None or m["versionCode"] > best["manifest"]["versionCode"]:
            best = v
    return best


def fetch(pkgs: list[str]) -> None:
    index = json.loads(INDEX.read_text())
    APK_DIR.mkdir(parents=True, exist_ok=True)
    lock = json.loads(LOCK.read_text()) if LOCK.exists() else {}
    for pkg in pkgs:
        v = pick(index, pkg)
        if v is None:
            print(f"no x86_64 build: {pkg}"); continue
        name = v["file"]["name"].lstrip("/")
        dest = APK_DIR / name
        if not (dest.exists() and sha256(dest) == v["file"]["sha256"]):
            print(f"fetch {name} ({v['file']['size'] // 1_000_000} MB)", flush=True)
            _get(f"{REPO}/{name}", dest)
            if sha256(dest) != v["file"]["sha256"]:
                dest.unlink(); print(f"SHA256 MISMATCH {pkg}; skipped"); continue
        lock[pkg] = {"file": name, "sha256": v["file"]["sha256"], "versionCode": v["manifest"]["versionCode"],
                     "versionName": v["manifest"].get("versionName"),
                     "name": index["packages"][pkg]["metadata"]["name"].get("en-US", pkg)}
        print(f"ok {pkg} {lock[pkg]['versionName']}", flush=True)
        LOCK.write_text(json.dumps(lock, indent=1, ensure_ascii=False))


def install(pkgs: list[str], grant: bool) -> None:
    lock = json.loads(LOCK.read_text())
    for pkg in pkgs:
        assert pkg != "ai.vox.companion"
        r = adb("install", "-r", *(["-g"] if grant else []), str(APK_DIR / lock[pkg]["file"]), check=False, timeout=600)
        print(f"install {pkg}: {r.strip().splitlines()[-1] if r.strip() else '?'}", flush=True)


# --- driving -------------------------------------------------------------------------------------------------------------

def peek(vox: Vox) -> None:
    t = vox.control("targets")
    print(t.get("app_name"), t["package"], "|", t["screen_text"])
    for i, (o, tt) in enumerate(zip(t["options"], t.get("targets", []) + [{"bounds": "-"}])):
        print(f"  {i:2d} {o:60s} {tt['bounds']}")


def explore(vox: Vox, out_dir: Path, apps: str, per_app: int, max_actions: int, deep: float, settle: float, seed: int,
            no_type: bool) -> None:
    harvest_explore.capture = capture          # the Walker captures through this module's capture (raw tree added)
    next_id, write = _ids(out_dir), _writer(out_dir)
    for i, spec in enumerate([s for s in apps.split(",") if s]):
        pkg, app = spec.split("=")
        assert pkg not in harvest_explore.NEVER_PKGS
        print(f"== {app} ({pkg})", flush=True)
        if anr_up():
            m = re.search(r"Application Not Responding: ([\w.]+)", sh("dumpsys window windows", check=False, timeout=30))
            hung = m.group(1) if m else "?"
            if hung in ("?", "android", "com.android.permissioncontroller", "com.android.systemui", "ai.vox.companion"):
                raise SystemExit(f"STOP: {hung} is not responding before the next app; clear it and find the cause first")
            print(f"    ANR dialog for {hung} (the previous app): force-stopping it", flush=True)
            sh(f"am force-stop {hung}", check=False); time.sleep(3)
            if anr_up():
                raise SystemExit(f"STOP: the ANR dialog for {hung} did not clear")
        check_sha()
        w = harvest_explore.Walker(vox, pkg, app, out_dir, next_id, write, random.Random(seed * 1000 + i), settle)
        if no_type:
            w.typed = 99
        try:
            w.run(per_app, max_actions, deep)
        except Exception as e:  # noqa: BLE001
            print(f"    {app} failed: {e}", flush=True)
        print(f"   {app}: {w.captured} screens", flush=True)
    sh("input keyevent KEYCODE_HOME", check=False)


SETTINGS12 = ["ALL_APPS_NOTIFICATION_SETTINGS", "NIGHT_DISPLAY_SETTINGS", "BATTERY_SAVER_SETTINGS", "DATE_SETTINGS",
              "LOCATION_SOURCE_SETTINGS", "ZEN_MODE_PRIORITY_SETTINGS", "USAGE_ACCESS_SETTINGS", "MANAGE_DEFAULT_APPS_SETTINGS",
              "INPUT_METHOD_SETTINGS", "DISPLAY_SETTINGS", "SOUND_SETTINGS", "WIFI_SETTINGS", "APPLICATION_SETTINGS",
              "CAPTIONING_SETTINGS"]


def settings_pages(vox: Vox, out_dir: Path, app: str, n: int, settle: float) -> None:
    """Capture-only Settings pages by intent (never taps in Settings); a swipe-up capture when the page scrolls."""
    check_sha()
    next_id, write = _ids(out_dir), _writer(out_dir)
    seen, got = set(), 0
    for name in SETTINGS12:
        if got >= n:
            break
        sh(f"am start -W -a android.settings.{name}", check=False)
        time.sleep(settle)
        for how in (f"am start android.settings.{name}", "swipe up"):
            if got >= n:
                break
            if how == "swipe up":
                t = vox.control("targets")
                if "scroll can" not in t["screen_text"] and "scroll at the top" not in t["screen_text"]:
                    break
                sh("input swipe 540 1700 540 700 300"); time.sleep(settle)
            t = vox.control("targets")
            if not t["package"].startswith("com.android.settings") or len(t["options"]) < 3:
                break
            sig = (t["screen_text"], tuple(t["options"]))
            if sig in seen:
                break
            seen.add(sig)
            write(capture(vox, f"{app}/{name.lower()}", app, how, out_dir, next_id(app)))
            got += 1
        sh("input keyevent KEYCODE_HOME"); time.sleep(0.5)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("cmd")
    p.add_argument("pkgs", nargs="*")
    p.add_argument("--no-grant", action="store_true")
    p.add_argument("--out", default="")
    p.add_argument("--app", default="")
    p.add_argument("--tag", default="")
    p.add_argument("--step", default="manual")
    p.add_argument("--apps", default="")
    p.add_argument("--per-app", type=int, default=8)
    p.add_argument("--max-actions", type=int, default=45)
    p.add_argument("--deep", type=float, default=0.6)
    p.add_argument("--settle", type=float, default=2.2)
    p.add_argument("--seed", type=int, default=3)
    p.add_argument("--no-type", action="store_true")
    p.add_argument("--note", default="")
    a = p.parse_args()
    if a.cmd == "fetch":
        return fetch(a.pkgs)
    if a.cmd == "install":
        return install(a.pkgs, not a.no_grant)
    vox = Vox()
    if a.cmd == "peek":
        return peek(vox)
    if a.cmd == "shacheck":
        return print(check_sha())
    out_dir = _out(a.out)
    if a.cmd == "cap":
        _writer(out_dir)(capture(vox, f"{a.app}/{a.tag}", a.app, a.step, out_dir, _ids(out_dir)(a.app)))
    elif a.cmd == "explore":
        explore(vox, out_dir, a.apps, a.per_app, a.max_actions, a.deep, a.settle, a.seed, a.no_type)
    elif a.cmd == "settings":
        settings_pages(vox, out_dir, a.app or "settings", a.per_app, a.settle)
    elif a.cmd != "manifest":
        sys.exit(__doc__)
    m = manifest(out_dir, a.note)
    if a.cmd != "cap":
        print(f"{out_dir.name}: {m['screens']} screens over {m['apps']} apps")
    svc = sh("settings get secure enabled_accessibility_services", check=False)
    if SERVICE not in svc:
        print("WARNING: Canti accessibility service is not enabled")


if __name__ == "__main__":
    main()
