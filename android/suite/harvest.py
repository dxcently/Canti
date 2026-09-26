"""Walk the stand-in apps, the fixture and the launcher, and record what the screen summariser sees at each step.

    python3 suite/harvest.py [--apps newpipe,vlc,...] [--out suite/out/harvest-<time>.jsonl]

At every step the app's `harvest` control op appends one JSON line to files/harvest.jsonl on the device:
    {"tag", "package", "screen_text" (the exact `screen:` line the model sees), "summary" (raw tree summary)}
The file is then pulled with `adb exec-out run-as ai.vox.companion cat files/harvest.jsonl` and each record is
enriched here with {"step", "action"} describing how the screen was reached.

The walk uses plain adb input (not the VOX pipeline) so the harvest is independent of the decider.

At the same steps the `targets` op returns the option list intent cursor mode would send for that screen; those go to
suite/out/targets-harvest-<time>.jsonl as {"tag", "package", "screen_text", "options"} (options in the order sent,
NONE_OPTION last), for hand-labelling a real-screen test set.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from servers import WebServer
from voxlib import (APP, Vox, adb, dismiss_first_run, force_stop, launch, prime_organic_maps, sh, start_activity)

OUT = Path(__file__).resolve().parent / "out"
W, H = 1080, 2400


def swipe(direction: str) -> str:
    x, y = W // 2, H // 2
    d = {"up": (x, int(H * .72), x, int(H * .28)), "down": (x, int(H * .28), x, int(H * .72)),
         "left": (int(W * .82), y, int(W * .18), y), "right": (int(W * .18), y, int(W * .82), y)}[direction]
    sh(f"input swipe {d[0]} {d[1]} {d[2]} {d[3]} 250")
    return f"swipe {direction}"


def key(k: str) -> str:
    sh(f"input keyevent {k}")
    return f"key {k}"


def tap_text(vox: Vox, *labels: str) -> str:
    for n in vox.control("dump").get("nodes", []):
        if (n["text"] or n["desc"]).strip().lower() in labels:
            x1, y1, x2, y2 = map(int, n["bounds"].split(","))
            sh(f"input tap {(x1 + x2) // 2} {(y1 + y2) // 2}")
            return f"tap '{n['text'] or n['desc']}'"
    return f"tap {labels[0]!r} (not found)"


def tap_id(vox: Vox, suffix: str) -> str:
    for n in vox.control("dump").get("nodes", []):
        if n["id"].endswith("/" + suffix):
            x1, y1, x2, y2 = map(int, n["bounds"].split(","))
            sh(f"input tap {(x1 + x2) // 2} {(y1 + y2) // 2}")
            return f"tap #{suffix}"
    return f"tap #{suffix} (not found)"


def gallery_photo() -> str:
    out = sh("content query --uri content://media/external/images/media --projection _id:_display_name", check=False)
    ids = [line.split("_id=")[1].split(",")[0] for line in out.splitlines() if "vox_test_0" in line]
    if not ids:
        return "open photo (no seeded photo)"
    sh(f"am start -W -a android.intent.action.VIEW -d content://media/external/images/media/{ids[0]} -t image/png "
       f"-p org.fossify.gallery")
    return "open photo via VIEW intent"


def walks(vox: Vox, web: WebServer) -> dict[str, list]:
    """App -> list of (step name, callable returning an action description or None)."""
    fx = lambda a: lambda: (start_activity(f"ai.vox.fixture/.{a}"), f"start {a}")[1]  # noqa: E731
    return {
        "launcher": [("home", lambda: key("KEYCODE_HOME")), ("app drawer", lambda: swipe("up")),
                     ("home again", lambda: key("KEYCODE_HOME")), ("notifications", lambda: (sh("cmd statusbar expand-notifications"), "expand notifications")[1]),
                     ("notifications closed", lambda: (sh("cmd statusbar collapse"), "collapse")[1])],
        "fixture": [("menu", fx("MenuActivity")), ("feed", fx("FeedActivity")), ("feed paused", lambda: (sh(f"input tap {W//2} {H//2}"), "tap centre")[1]),
                    ("feed next", lambda: swipe("up")), ("list", fx("ListActivity")), ("list scrolled", lambda: swipe("up")),
                    ("controls", fx("ControlsActivity")), ("text entry", lambda: tap_id(vox, "text_field")),
                    ("static", fx("StaticActivity"))],
        "newpipe": [("start", lambda: (launch("org.schabi.newpipe"), "launch")[1]), ("tab 2", lambda: swipe("left")),
                    ("scrolled", lambda: swipe("up")), ("search", lambda: tap_text(vox, "search")), ("back", lambda: key("KEYCODE_BACK")),
                    ("open drawer", lambda: tap_text(vox, "open drawer")), ("drawer closed", lambda: key("KEYCODE_BACK"))],
        "vlc": [("start", lambda: (launch("org.videolan.vlc"), "launch")[1]), ("playlists tab", lambda: swipe("left")),
                ("audio", lambda: tap_text(vox, "audio")), ("browse", lambda: tap_text(vox, "browse")), ("more", lambda: tap_text(vox, "more"))],
        "organicmaps": [("start", lambda: (prime_organic_maps(vox), launch("app.organicmaps"), "launch")[2]),
                        ("zoomed", lambda: tap_text(vox, "zoom in")), ("search", lambda: tap_text(vox, "search")),
                        ("back", lambda: key("KEYCODE_BACK")), ("menu", lambda: tap_text(vox, "menu")), ("menu closed", lambda: key("KEYCODE_BACK"))],
        "gallery": [("folders", lambda: (launch("org.fossify.gallery"), "launch")[1]), ("photo", gallery_photo),
                    ("next photo", lambda: swipe("left")), ("back to folder", lambda: key("KEYCODE_BACK"))],
        "fennec": [("page", lambda: (sh(f"am start -W -a android.intent.action.VIEW -d {web.url} -p org.mozilla.fennec_fdroid"), "open long.html")[1]),
                   ("page scrolled", lambda: swipe("up")), ("page end", lambda: key("KEYCODE_MOVE_END")),
                   ("back", lambda: key("KEYCODE_BACK"))],
    }


PKGS = {"newpipe": "org.schabi.newpipe", "vlc": "org.videolan.vlc", "organicmaps": "app.organicmaps",
        "gallery": "org.fossify.gallery", "fennec": "org.mozilla.fennec_fdroid", "fixture": "ai.vox.fixture"}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--apps", default="launcher,fixture,newpipe,vlc,organicmaps,gallery,fennec")
    p.add_argument("--out", default="")
    a = p.parse_args()
    vox = Vox()
    vox.control("reset", clear_harvest=True)
    web = WebServer(8766)
    steps: list[dict] = []
    target_rows: list[dict] = []
    try:
        plan = walks(vox, web)
        for app in a.apps.split(","):
            if app in PKGS:
                force_stop(PKGS[app])
            for i, (name, fn) in enumerate(plan[app]):
                action = fn()
                time.sleep(2.5)
                if i == 0:   # only right after launch: later steps may legitimately show "close"/"cancel" buttons
                    dismiss_first_run(vox=vox, log=lambda m: print(f"    {m}"))
                tag = f"{app}/{name}"
                rec = vox.control("harvest", tag=tag)["record"]
                steps.append({"tag": tag, "action": action})
                print(f"  {tag:28s} {rec['package']:28s} {rec['screen_text']}")
                tr = vox.control("targets")
                target_rows.append({"tag": tag, "package": tr["package"], "screen_text": tr["screen_text"], "options": tr["options"]})
                print(f"  {'':28s} {len(tr['options']) - 1} targets")
    finally:
        web.close()
        sh("input keyevent KEYCODE_HOME", check=False)
    raw = adb("exec-out", "run-as", APP, "cat", "files/harvest.jsonl")
    by_tag = {s["tag"]: s for s in steps}
    OUT.mkdir(exist_ok=True)
    out = Path(a.out) if a.out else OUT / f"harvest-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    n = 0
    with out.open("w") as f:
        for line in raw.splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            rec["step"] = by_tag.get(rec.get("tag"), {}).get("action")
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    print(f"{n} records -> {out}")
    tout = out.with_name(out.name.replace("harvest-", "targets-harvest-", 1)) if out.name.startswith("harvest-") \
        else out.with_name("targets-" + out.name)
    tout.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in target_rows))
    print(f"{len(target_rows)} target lists ({sum(len(r['options']) - 1 for r in target_rows)} targets) -> {tout}")


if __name__ == "__main__":
    main()
