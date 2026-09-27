#!/usr/bin/env bash
# Capture real-phone screens for finetune/data/real-targets-v1 (the Z Flip test set). Run from anywhere.
#
#   suite/harvest_device.sh status                     serial, screen size, foreground app, Canti service on/off
#   suite/harvest_device.sh cap <app>/<state>          capture the screen that is showing now
#   suite/harvest_device.sh open <package>             launch an app (monkey, user 0); nothing else is tapped
#
# The phone must be the only non-emulator device, or set VOX_PHONE=<serial>. Always addressed with -s <serial>; the adb
# server is never restarted (another tool may hold the emulator). The person drives the phone to each screen; this
# script only launches apps and captures.
#
# Per capture: a PNG (screencap -p), the `uiautomator dump` XML, and an option list. If Canti/VOX is installed with its
# accessibility service on, the options come from the app's own `targets` op (forwarded to tcp:$VOX_SOCKET_PORT,
# default 7789 so it cannot collide with the emulator's 7788); otherwise from suite/tree_targets.py, the Python port of
# Targets.kt over the uiautomator XML. Output: finetune/data/real-targets-v1/zflip/raw (gitignored: personal data).
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cmd="${1:-status}"; shift || true
run() { "$here/dev" "$@"; }
serial="${VOX_PHONE:-$(run adb devices 2>/dev/null | awk 'NR>1 && $2=="device" && $1 !~ /^emulator-/ {print $1; exit}')}"
[ -n "$serial" ] || { echo "no physical device in 'adb devices' (plug in the phone, enable USB debugging, accept the prompt)"; exit 1; }
export VOX_SERIAL="$serial" VOX_SOCKET_PORT="${VOX_SOCKET_PORT:-7789}"
py() { run env VOX_SERIAL="$VOX_SERIAL" VOX_SOCKET_PORT="$VOX_SOCKET_PORT" PYTHONPATH="$here/suite" python3 "$@"; }
case "$cmd" in
  status) py "$here/suite/harvest_device.py" --status ;;
  cap)    [ -n "${1:-}" ] || { echo "usage: $0 cap <app>/<state>"; exit 2; }
          py "$here/suite/harvest_device.py" --tag "$1" "${@:2}" ;;
  open)   run adb -s "$serial" shell monkey --pct-syskeys 0 -p "$1" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 \
            || run adb -s "$serial" shell am start --user 0 -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -p "$1" ;;
  *) sed -n '2,16p' "$0"; exit 2 ;;
esac
