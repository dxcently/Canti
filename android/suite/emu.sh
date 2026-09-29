#!/usr/bin/env bash
# Headless emulator lifecycle. Run inside the dev shell (../dev suite/emu.sh <cmd>).
#   create   create the AVD (idempotent)
#   start    boot headless (-no-window -no-audio) and wait for sys.boot_completed (VOX_WIPE=1: factory-fresh -wipe-data)
#   stop     kill the emulator (only the one this script started)
#   status   print whether it is running
# One emulator per port: start refuses if this serial is already attached to adb. A second AVD runs beside the suite's:
#   VOX_AVD=vox35-play VOX_EMU_PORT=5582 VOX_AVD_IMAGE="$VOX_ANDROID_PLAY_IMAGE" VOX_WINDOW=1 ../dev suite/emu.sh start
# (Google Play image, hand-driven: sign in once on its window; the suite never runs on it.)
set -euo pipefail
: "${VOX_STATE:?run inside ./dev}"
AVD="${VOX_AVD:-vox35}"
PORT="${VOX_EMU_PORT:-5580}"
SERIAL="emulator-$PORT"
PIDFILE="$VOX_STATE/emulator.pid"; [ "$AVD" = vox35 ] || PIDFILE="$VOX_STATE/emulator-$AVD.pid"
LOG="$VOX_STATE/logs/emulator.log"; [ "$AVD" = vox35 ] || LOG="$VOX_STATE/logs/emulator-$AVD.log"
mkdir -p "$VOX_STATE/logs"

create() {
  if [ -d "$ANDROID_AVD_HOME/$AVD.avd" ]; then echo "avd $AVD exists"; return; fi
  echo no | JAVA_TOOL_OPTIONS="-Duser.home=$VOX_STATE/home" avdmanager create avd -n "$AVD" -k "${VOX_AVD_IMAGE:-$VOX_ANDROID_IMAGE}" -d pixel_6 --force
  cfg="$ANDROID_AVD_HOME/$AVD.avd/config.ini"
  # Deterministic, light headless device: 1080x2400 @ 420 dpi, no camera, no snapshot.
  {
    echo "hw.ramSize=4096"
    echo "hw.cpu.ncore=4"
    echo "hw.keyboard=yes"
    echo "hw.camera.back=none"
    echo "hw.camera.front=none"
    echo "hw.audioInput=no"
    echo "hw.gpu.enabled=yes"
    echo "hw.gpu.mode=swiftshader_indirect"
    echo "disk.dataPartition.size=8G"
    echo "fastboot.forceColdBoot=yes"
  } >> "$cfg"
  echo "created $AVD"
}

running() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

start() {
  create
  if running; then echo "already running (pid $(cat "$PIDFILE"))"; return; fi
  if adb devices | grep -q "^$SERIAL\b"; then
    echo "$SERIAL is already attached to adb; refusing to start another on that port" >&2; exit 1
  fi
  echo "booting $AVD on port $PORT (log: $LOG)"
  local wipe=(); [ "${VOX_WIPE:-0}" = 1 ] && wipe=(-wipe-data)
  local win=(-no-window); [ "${VOX_WINDOW:-0}" = 1 ] && win=()
  # The SDK's Qt has no wayland plugin: a window goes through XWayland.
  [ "${VOX_WINDOW:-0}" = 1 ] && export QT_QPA_PLATFORM=xcb
  # HOME inside .state: the emulator writes ~/.emulator_console_auth_token otherwise.
  HOME="$VOX_STATE/home" nohup emulator -avd "$AVD" -port "$PORT" "${win[@]}" -no-audio -no-boot-anim -no-snapshot \
    -gpu swiftshader_indirect -accel on -camera-back none -camera-front none "${wipe[@]}" \
    >"$LOG" 2>&1 &
  echo $! > "$PIDFILE"
  local t0=$SECONDS
  adb -s "$SERIAL" wait-for-device
  until [ "$(adb -s "$SERIAL" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1 ]; do
    if ! running; then echo "emulator exited during boot; tail of log:" >&2; tail -30 "$LOG" >&2; exit 1; fi
    if (( SECONDS - t0 > ${VOX_BOOT_TIMEOUT:-600} )); then echo "boot timeout" >&2; exit 1; fi
    sleep 3
  done
  # Test hygiene: no animations (deterministic dumps), stay awake, unlocked.
  adb -s "$SERIAL" shell settings put global window_animation_scale 0
  adb -s "$SERIAL" shell settings put global transition_animation_scale 0
  adb -s "$SERIAL" shell settings put global animator_duration_scale 0
  adb -s "$SERIAL" shell svc power stayon true
  adb -s "$SERIAL" shell input keyevent KEYCODE_WAKEUP
  adb -s "$SERIAL" shell wm dismiss-keyguard || true
  echo "booted in $((SECONDS - t0)) s: $SERIAL"
}

stop() {
  if adb -s "$SERIAL" get-state >/dev/null 2>&1; then adb -s "$SERIAL" emu kill >/dev/null 2>&1 || true; fi
  if running; then
    local pid; pid="$(cat "$PIDFILE")"
    for _ in $(seq 20); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
    kill "$pid" 2>/dev/null || true
  fi
  rm -f "$PIDFILE"
  echo stopped
}

status() { if running; then echo "running pid $(cat "$PIDFILE") serial $SERIAL"; else echo "not running"; fi; }

case "${1:-}" in
  create) create ;;
  start) start ;;
  stop) stop ;;
  status) status ;;
  serial) echo "$SERIAL" ;;
  *) echo "usage: $0 create|start|stop|status|serial" >&2; exit 2 ;;
esac
