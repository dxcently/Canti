"""F-Droid stand-in apps: pin (lock) and fetch with sha256 verification.

    python3 suite/apks.py lock    # resolve the newest x86_64-compatible build of each app from F-Droid's index-v2
                                  # and write suite/apks.lock.json (url + sha256 + size). Commit the lockfile.
    python3 suite/apks.py fetch   # download every locked APK into suite/apks/ and verify its sha256 (idempotent)

Stand-ins are open-source, need no login, and exercise the screen kinds VOX cares about.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

REPO = "https://f-droid.org/repo"
SUITE = Path(__file__).resolve().parent
LOCK = SUITE / "apks.lock.json"
APKS = SUITE / "apks"
ABI = "x86_64"
MAX_SDK = 35  # the emulator image's API level

APPS = [
    {"role": "video feed / player (YouTube-like)", "package": "org.schabi.newpipe"},
    {"role": "video player", "package": "org.videolan.vlc"},
    {"role": "map", "package": "app.organicmaps"},
    {"role": "photo viewer / gallery", "package": "org.fossify.gallery"},
    {"role": "web browser", "package": "org.mozilla.fennec_fdroid"},
]


def _get(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "vox-android-suite/0.1"})
    with urllib.request.urlopen(req, timeout=120) as r, tmp.open("wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.rename(dest)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def lock() -> None:
    cache = SUITE.parent / ".state" / "fdroid" / "index-v2.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    if not cache.exists() or time.time() - cache.stat().st_mtime > 86400:
        print(f"downloading {REPO}/index-v2.json")
        _get(f"{REPO}/index-v2.json", cache)
    index = json.loads(cache.read_text())
    out = []
    for app in APPS:
        pkg = index["packages"][app["package"]]
        cands = []
        for v in pkg["versions"].values():
            m = v["manifest"]
            native = m.get("nativecode")
            if native and ABI not in native:
                continue
            if m.get("usesSdk", {}).get("minSdkVersion", 1) > MAX_SDK:
                continue
            name = v["file"]["name"].lstrip("/")
            plain = name == f"{app['package']}_{m['versionCode']}.apk"
            cands.append((m["versionCode"], plain, v, name))
        vc, _, v, name = max(cands, key=lambda c: (c[0], c[1]))
        out.append({
            "role": app["role"], "package": app["package"],
            "name": pkg["metadata"]["name"].get("en-US", app["package"]),
            "versionCode": vc, "versionName": v["manifest"].get("versionName"),
            "url": f"{REPO}/{name}", "sha256": v["file"]["sha256"], "size": v["file"]["size"],
            "nativecode": v["manifest"].get("nativecode"),
        })
    LOCK.write_text(json.dumps({"source": REPO, "abi": ABI, "max_sdk": MAX_SDK, "apps": out}, indent=2) + "\n")
    for a in out:
        print(f"locked {a['package']} {a['versionName']} ({a['versionCode']}) {a['size'] // 1_000_000} MB")


def fetch() -> None:
    APKS.mkdir(exist_ok=True)
    for a in json.loads(LOCK.read_text())["apps"]:
        dest = APKS / f"{a['package']}_{a['versionCode']}.apk"
        if dest.exists() and sha256(dest) == a["sha256"]:
            print(f"ok      {dest.name}")
            continue
        print(f"fetch   {a['url']} ({a['size'] // 1_000_000} MB)")
        _get(a["url"], dest)
        got = sha256(dest)
        if got != a["sha256"]:
            dest.unlink()
            sys.exit(f"SHA256 MISMATCH for {a['url']}: expected {a['sha256']} got {got}")
        print(f"verified {dest.name}")


def path_for(package: str) -> Path:
    for a in json.loads(LOCK.read_text())["apps"]:
        if a["package"] == package:
            return APKS / f"{a['package']}_{a['versionCode']}.apk"
    raise KeyError(package)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "lock":
        lock()
    elif cmd == "fetch":
        fetch()
    else:
        sys.exit(__doc__)
