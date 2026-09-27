"""Bounded automatic exploration of emulator apps for the real-screen training set (data/real-targets-v2).

    python3 suite/harvest_explore.py --apps org.fossify.notes=fnotes,org.tasks=tasks [--per-app 16] [--out-dir DIR]

For each app: force-stop, launch, click through first-run dialogs, then walk. At every step the walker picks an untried
action on the current screen: tap one of the app's own `targets` options (the same list intent cursor mode sends), scroll
the list, open the overflow menu, or type a short query into a focused text field. A screen whose option list (plus
screen line) has not been seen in this app is captured with harvest_real.capture (PNG + targets + bounds + template).
The walker goes deeper with some probability, otherwise presses back. If an action leaves the app it presses back at
once (and relaunches if that does not return), so it never taps anything outside the app under test.

Safety: options whose label matches DENY (delete, uninstall, sign out, call, send, buy, accessibility, ...) are never
tapped. Nothing is ever done in com.android.settings or in ai.vox.companion (Canti), and its accessibility service is
checked at the end.

Never uses uiautomator (it disconnects the accessibility service). Runs inside ./dev (adb on PATH).
"""

from __future__ import annotations

import argparse
import json
import random
import re
import time
from pathlib import Path

from harvest import key, swipe
from harvest_real import DEFAULT_OUT, capture
from voxlib import SERVICE, Vox, dismiss_first_run, force_stop, launch, sh

ROOT = Path(__file__).resolve().parents[2]
V2_OUT = ROOT / "finetune" / "data" / "real-targets-v2" / "emulator" / "raw"
NEVER_PKGS = {"com.android.settings", "ai.vox.companion"}
# Packages a dialog may legitimately belong to while the app is still "the app" (permission prompts, pickers).
DIALOG_PKGS = {"com.android.permissioncontroller", "com.google.android.permissioncontroller", "android",
               "com.android.documentsui", "com.android.intentresolver"}
DENY = re.compile(r"\b(delete|remove|uninstall|clear|reset|erase|wipe|format|factory|disable|deactivate|sign ?out|log ?out|"
                  r"logout|call|dial|send|sms|report|block|buy|purchase|donate|pay|upgrade|subscribe|rate|review|share|"
                  r"accessibility|exit|quit|restart|reboot|power|lock|backup|restore|import|export|kill|force|trash|empty|"
                  r"uninstall|root|debug|developer|install|update|download all|sync now|bluetooth|airplane|wi-?fi|location|"
                  r"record|camera|microphone|emergency|sos|feedback|email us|contact us|website|github|translate|privacy policy|"
                  r"licen[cs]e|donat|sponsor|patreon|liberapay|close app)\b", re.I)


def label(opt: str) -> str:
    i = opt.rfind(" (")
    return opt[:i] if i > 0 else opt


def role(opt: str) -> str:
    m = re.search(r"\(([^,()]+),[^()]*\)$", opt)
    return m.group(1) if m else ""


class Walker:
    def __init__(self, vox: Vox, pkg: str, app: str, out_dir: Path, next_id, write, rng: random.Random, settle: float):
        self.vox, self.pkg, self.app, self.out_dir = vox, pkg, app, out_dir
        self.next_id, self.write, self.rng, self.settle = next_id, write, rng, settle
        self.seen: set = set()
        self.tried: set = set()
        self.captured = 0
        self.typed = 0

    def targets(self) -> dict:
        return self.vox.control("targets")

    def sig(self, t: dict) -> tuple:
        return (t["package"], t["screen_text"], tuple(sorted(label(o) for o in t["options"][:-1])))

    def in_app(self, t: dict) -> bool:
        return t["package"] == self.pkg or t["package"] in DIALOG_PKGS

    def recover(self) -> dict:
        """Back to the app: back once or twice, then relaunch."""
        for _ in range(2):
            key("KEYCODE_BACK"); time.sleep(self.settle)
            t = self.targets()
            if self.in_app(t):
                return t
        launch(self.pkg); time.sleep(self.settle + 1)
        return self.targets()

    def maybe_capture(self, t: dict, how: str) -> None:
        if t["package"] in NEVER_PKGS or not self.in_app(t) or len(t["options"]) < 2:
            return
        s = self.sig(t)
        if s in self.seen:
            return
        self.seen.add(s)
        rec = capture(self.vox, f"{self.app}/{how[:40]}", self.app, how, self.out_dir, self.next_id(self.app))
        if self.sig({"package": rec["package"], "screen_text": rec["screen_text"], "options": rec["options"]}) != s:
            rec["stable"] = False
        self.write(rec)
        self.captured += 1

    def actions(self, t: dict) -> list[tuple[str, object]]:
        s = self.sig(t)
        acts = []
        for o, tt in zip(t["options"][:-1], t.get("targets", [])):
            lab = label(o)
            if DENY.search(lab) or (s, lab) in self.tried:
                continue
            acts.append((f"tap {lab[:30]!r}", ("tap", lab, tt["bounds"], role(o))))
        if "scroll can" in t["screen_text"] or "scroll at the top" in t["screen_text"]:
            if (s, "swipe") not in self.tried:
                acts.append(("swipe up", ("swipe", "swipe", None, "")))
        if "keyboard open" in t["screen_text"] and (s, "type") not in self.tried and self.typed < 2:
            acts.append(("type query", ("type", "type", None, "")))
        return acts

    def do(self, s, act) -> str:
        kind, lab, bounds, _ = act
        self.tried.add((s, lab))
        if kind == "tap":
            x1, y1, x2, y2 = map(int, bounds.split(","))
            sh(f"input tap {(x1 + x2) // 2} {(y1 + y2) // 2}")
            return f"tap '{lab}'"
        if kind == "swipe":
            return swipe("up")
        if kind == "type":
            q = self.rng.choice(["music", "test", "news", "hello", "notes", "photo", "map"]); self.typed += 1
            sh(f"input text {q}")
            return f"type {q!r}"
        return "?"

    def run(self, per_app: int, max_actions: int, deep_p: float) -> None:
        force_stop(self.pkg)
        launch(self.pkg); time.sleep(self.settle + 2)
        dismiss_first_run(vox=self.vox, log=lambda m: print(f"    {m}"))
        time.sleep(1)
        t = self.targets()
        self.maybe_capture(t, "launch")
        depth = 0
        for _ in range(max_actions):
            if self.captured >= per_app:
                break
            if t["package"] in NEVER_PKGS or not self.in_app(t):
                t = self.recover(); depth = 0
                if not self.in_app(t):
                    print(f"    lost {self.pkg} (now {t['package']}); stopping this app")
                    break
                continue
            acts = self.actions(t)
            if not acts or depth >= 4:
                key("KEYCODE_BACK"); time.sleep(self.settle); depth = max(0, depth - 1)
                t = self.targets()
                if not self.in_app(t):
                    launch(self.pkg); time.sleep(self.settle + 1); t = self.targets(); depth = 0
                continue
            # prefer structural actions (menus, tabs, swipes) a bit over list items
            weights = [3 if a[1][0] != "tap" or a[1][3] in ("tab", "button", "image") else 1 for a in acts]
            how, act = self.rng.choices(acts, weights=weights)[0]
            s = self.sig(t)
            try:
                how = self.do(s, act)
            except Exception as e:  # noqa: BLE001
                print(f"    action failed: {e}")
                continue
            time.sleep(self.settle + (1.5 if act[0] == "swipe" else 0))   # flings keep scrolling after the swipe
            t2 = self.targets()
            if t2["package"] in NEVER_PKGS or not self.in_app(t2):
                t = self.recover(); depth = 0
                continue
            self.maybe_capture(t2, how)
            if self.sig(t2) != s and self.rng.random() > deep_p and act[0] == "tap":
                key("KEYCODE_BACK"); time.sleep(self.settle)
                t = self.targets()
            else:
                t = t2; depth += 1 if self.sig(t2) != s else 0


SETTINGS_INTENTS = """WIRELESS_SETTINGS WIFI_SETTINGS BLUETOOTH_SETTINGS DATA_ROAMING_SETTINGS DISPLAY_SETTINGS SOUND_SETTINGS
APPLICATION_SETTINGS MANAGE_APPLICATIONS_SETTINGS MANAGE_DEFAULT_APPS_SETTINGS ACCESSIBILITY_SETTINGS DATE_SETTINGS LOCALE_SETTINGS
INPUT_METHOD_SETTINGS PRIVACY_SETTINGS SECURITY_SETTINGS LOCATION_SOURCE_SETTINGS INTERNAL_STORAGE_SETTINGS DEVICE_INFO_SETTINGS
ZEN_MODE_PRIORITY_SETTINGS NIGHT_DISPLAY_SETTINGS CAST_SETTINGS USER_SETTINGS SYNC_SETTINGS USAGE_ACCESS_SETTINGS VPN_SETTINGS
DREAM_SETTINGS CAPTIONING_SETTINGS MANAGE_UNKNOWN_APP_SOURCES AIRPLANE_MODE_SETTINGS NFC_SETTINGS HARD_KEYBOARD_SETTINGS
USER_DICTIONARY_SETTINGS MANAGE_ALL_FILES_ACCESS_PERMISSION APP_SEARCH_SETTINGS ALL_APPS_NOTIFICATION_SETTINGS
CONDITION_PROVIDER_SETTINGS WEBVIEW_SETTINGS BATTERY_SAVER_SETTINGS""".split()


def settings_walk(vox: Vox, out_dir: Path, next_id, write, settle: float) -> None:
    """Capture-only: open each Settings page by intent, capture it and one scroll. Never taps anything in Settings."""
    seen = set()
    for name in SETTINGS_INTENTS:
        sh(f"am start -W -a android.settings.{name}", check=False)
        time.sleep(settle)
        for how in (f"am start {name}", "swipe up"):
            if how == "swipe up":
                swipe("up"); time.sleep(settle)
            t = vox.control("targets")
            if not t["package"].startswith("com.android.") or len(t["options"]) < 2:
                break
            s = (t["package"], t["screen_text"], tuple(sorted(label(o) for o in t["options"][:-1])))
            if s in seen:
                break
            seen.add(s)
            write(capture(vox, f"settings2/{name.lower()}", "settings2", how, out_dir, next_id("settings2")))
        key("KEYCODE_HOME"); time.sleep(0.5)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--settings", action="store_true", help="capture-only Settings pages by intent (no taps)")
    p.add_argument("--apps", default="", help="pkg=key,pkg=key,...")
    p.add_argument("--out-dir", default=str(V2_OUT))
    p.add_argument("--per-app", type=int, default=16)
    p.add_argument("--max-actions", type=int, default=70)
    p.add_argument("--deep", type=float, default=0.55, help="probability of staying on a new screen (vs back)")
    p.add_argument("--settle", type=float, default=2.0)
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args()
    assert Path(a.out_dir) != DEFAULT_OUT, "write v2 data outside real-targets-v1"
    vox = Vox()
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    screens = out_dir / "screens.jsonl"
    existing = [json.loads(l) for l in screens.read_text().splitlines() if l.strip()] if screens.exists() else []
    used = {r["screen_id"] for r in existing}

    def next_id(app: str) -> str:
        i = 1
        while f"emu-{app}-{i:02d}" in used:
            i += 1
        used.add(f"emu-{app}-{i:02d}")
        return f"emu-{app}-{i:02d}"

    def write(r: dict) -> None:
        with screens.open("a") as f:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"  {r['screen_id']:24s} {len(r['options']) - 1:2d} opts stable={r['stable']} {r['step'][:40]:40s} {r['screen_text']}",
              flush=True)

    try:
        if a.settings:
            settings_walk(vox, out_dir, next_id, write, a.settle)
        for i, spec in enumerate([s for s in a.apps.split(",") if s]):
            pkg, app = spec.split("=")
            assert pkg not in NEVER_PKGS
            print(f"== {app} ({pkg})", flush=True)
            w = Walker(vox, pkg, app, out_dir, next_id, write, random.Random(a.seed * 1000 + i), a.settle)
            try:
                w.run(a.per_app, a.max_actions, a.deep)
            except Exception as e:  # noqa: BLE001  one broken app must not end the harvest
                print(f"    {app} failed: {e}", flush=True)
            force_stop(pkg)
            print(f"   {app}: {w.captured} screens", flush=True)
    finally:
        sh("input keyevent KEYCODE_HOME", check=False)
        svc = sh("settings get secure enabled_accessibility_services", check=False)
        print("Canti accessibility service still enabled:", SERVICE in svc or "ai.vox.companion" in svc)


if __name__ == "__main__":
    main()
