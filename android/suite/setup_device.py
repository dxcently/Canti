"""Install the VOX app, the fixture app and the locked F-Droid stand-ins, seed test media, enable the service.

    python3 suite/setup_device.py [--no-standins]

Assumes a booted emulator (suite/emu.sh start) and built APKs (gradle assembleDebug).
"""

from __future__ import annotations

import argparse
import struct
import sys
import time
import zlib
from pathlib import Path

import apks
from voxlib import ANDROID, APP, FIXTURE, SERVICE, Vox, adb, prime_organic_maps, sh

APP_APK = ANDROID / "app/build/outputs/apk/debug/app-debug.apk"
FIXTURE_APK = ANDROID / "fixture/build/outputs/apk/debug/fixture-debug.apk"


def png(w: int, h: int, rgb: tuple[int, int, int], stripe: int) -> bytes:
    """A small PNG (solid colour with a white stripe) so the gallery has distinguishable photos."""
    rows = b""
    for y in range(h):
        line = bytearray()
        for x in range(w):
            line += bytes((255, 255, 255)) if (x // 40) == stripe else bytes(rgb)
        rows += b"\x00" + bytes(line)

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def install(apk: Path) -> None:
    print(f"  install {apk.name}")
    adb("install", "-r", "-t", "-g", str(apk), timeout=600)


def seed_media() -> None:
    out = ANDROID / ".state" / "media"
    out.mkdir(parents=True, exist_ok=True)
    colors = [(200, 40, 40), (40, 160, 60), (40, 70, 200), (220, 170, 30), (120, 40, 160)]
    sh("mkdir -p /sdcard/Pictures/VOX")
    for i, c in enumerate(colors):
        f = out / f"vox_test_{i}.png"
        f.write_bytes(png(360, 640, c, i + 1))
        adb("push", str(f), f"/sdcard/Pictures/VOX/{f.name}")
    # Make MediaStore index them now.
    for i in range(len(colors)):
        sh(f"am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file:///sdcard/Pictures/VOX/vox_test_{i}.png",
           check=False)
    sh("cmd media_provider scan /sdcard/Pictures/VOX", check=False)
    print(f"  seeded {len(colors)} photos in /sdcard/Pictures/VOX")


def enable_service() -> None:
    sh(f"settings put secure enabled_accessibility_services {SERVICE}")
    sh("settings put secure accessibility_enabled 1")
    vox = Vox()
    for _ in range(40):
        try:
            r = vox.control("ping")
            if r.get("ok"):
                print(f"  service up: vocab {r['vocab']} decider {r['settings']['decider']}")
                vox.close()
                return
        except Exception:
            pass
        time.sleep(0.5)
    sys.exit("VOX accessibility service did not come up (no ping over the debug socket)")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--no-standins", action="store_true")
    a = p.parse_args()
    for f in (APP_APK, FIXTURE_APK):
        if not f.exists():
            sys.exit(f"missing {f}: run `gradle assembleDebug` first")
    print("installing VOX + fixture")
    install(APP_APK)
    install(FIXTURE_APK)
    if not a.no_standins:
        print("installing F-Droid stand-ins (hash-verified)")
        apks.fetch()
        for pkg in [x["package"] for x in __import__("json").loads(apks.LOCK.read_text())["apps"]]:
            installed = sh(f"pm list packages {pkg}", check=False)
            if f"package:{pkg}\n" in installed + "\n" and "--reinstall" not in sys.argv:
                print(f"  {pkg} already installed")
                continue
            install(apks.path_for(pkg))
        # Runtime permissions the stand-ins ask for on first run (-g grants those declared at install time).
        for pkg, perms in {"org.fossify.gallery": ["android.permission.READ_MEDIA_IMAGES", "android.permission.READ_MEDIA_VIDEO"],
                           "app.organicmaps": ["android.permission.ACCESS_FINE_LOCATION"],
                           "org.videolan.vlc": ["android.permission.READ_MEDIA_VIDEO", "android.permission.READ_MEDIA_AUDIO"]}.items():
            for perm in perms:
                sh(f"pm grant {pkg} {perm}", check=False)
        sh("appops set org.fossify.gallery MANAGE_EXTERNAL_STORAGE allow", check=False)
        sh("appops set org.videolan.vlc MANAGE_EXTERNAL_STORAGE allow", check=False)
        seed_media()
    print("enabling the accessibility service")
    enable_service()
    if not a.no_standins:
        prime_organic_maps(Vox(), log=lambda m: print(f"  {m}"))


if __name__ == "__main__":
    main()
