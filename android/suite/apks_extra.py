"""Extra F-Droid apps for the real-screen harvest (data/real-targets-v2). Separate from apks.py / apks.lock.json so the
test suite's pinned stand-ins are untouched.

    python3 suite/apks_extra.py fetch     # newest x86_64-compatible build of each app -> .state/apks-extra/ (sha256-checked)
    python3 suite/apks_extra.py install   # adb install each fetched APK that is not installed yet (never touches Canti)

Uses the F-Droid index cached by apks.py lock (.state/fdroid/index-v2.json).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from apks import REPO, _get, sha256
from voxlib import adb, sh

SUITE = Path(__file__).resolve().parent
INDEX = SUITE.parent / ".state" / "fdroid" / "index-v2.json"
OUT = SUITE.parent / ".state" / "apks-extra"
# Not io.github.muntashirakon.AppManager: its ActivityInterceptor claims system intents (STILL_IMAGE_CAMERA -> a chooser)
# and the shell cannot disable the component, so it breaks the camera test.
APPS = """org.fossify.calendar org.fossify.notes org.fossify.filemanager org.fossify.contacts org.fossify.clock
org.fossify.musicplayer org.fossify.messages org.fossify.phone org.fossify.voicerecorder org.fossify.paint org.fossify.math
de.danoeh.antennapod com.fsck.k9 net.gsantner.markor org.tasks org.isoron.uhabits org.oxycblt.auxio
com.beemdevelopment.aegis com.kunzisoft.keepass.libre com.nononsenseapps.feeder me.zhanghai.android.files
me.hackerchick.catima ws.xsoh.etar org.breezyweather com.keylesspalace.tusky org.wikipedia org.kde.kdeconnect_tp
com.github.ashutoshgngwr.noice org.joinmastodon.android com.github.libretube org.fdroid.fdroid
com.best.deskclock org.secuso.privacyfriendlytodolist org.secuso.privacyfriendlynotes
com.forrestguice.suntimeswidget org.jellyfin.mobile com.gh4a com.darshancomputing.BatteryIndicatorPro""".split()


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


def fetch() -> None:
    index = json.loads(INDEX.read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    lock = {}

    def one(pkg):
        v = pick(index, pkg)
        name = v["file"]["name"].lstrip("/")
        dest = OUT / name
        if not (dest.exists() and sha256(dest) == v["file"]["sha256"]):
            print(f"fetch {name} ({v['file']['size'] // 1_000_000} MB)", flush=True)
            _get(f"{REPO}/{name}", dest)
            if sha256(dest) != v["file"]["sha256"]:
                dest.unlink()
                return pkg, None
        return pkg, {"file": name, "sha256": v["file"]["sha256"], "versionCode": v["manifest"]["versionCode"]}

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(6) as ex:
        for pkg, e in ex.map(one, APPS):
            if e is None:
                print(f"SHA256 MISMATCH {pkg}; skipped", flush=True)
            else:
                lock[pkg] = e
                print(f"ok {pkg}", flush=True)
    (OUT / "lock.json").write_text(json.dumps(lock, indent=1))
    print(f"{len(lock)} apks ok in {OUT}")


def install() -> None:
    lock = json.loads((OUT / "lock.json").read_text())
    have = {l.split(":", 1)[1].strip() for l in sh("pm list packages").splitlines() if ":" in l}
    for pkg, e in lock.items():
        if pkg in have:
            print(f"ok      {pkg}")
            continue
        r = adb("install", "-g", str(OUT / e["file"]), check=False, timeout=300)
        print(f"install {pkg}: {r.strip().splitlines()[-1] if r.strip() else '?'}", flush=True)


if __name__ == "__main__":
    {"fetch": fetch, "install": install}[sys.argv[1]]()
