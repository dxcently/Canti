#!/usr/bin/env bash
# One entry point for the emulator suite. Run from anywhere; it enters the pinned dev shell itself.
#   suite/run.sh build     flutter pub get (ui/), gradle assembleDebug + JVM unit tests
#   suite/run.sh boot      create the AVD if needed and boot it headless (VOX_WIPE=1 for a factory-fresh device)
#   suite/run.sh setup     install VOX, fixture and the hash-pinned F-Droid stand-ins; seed photos; enable the service
#   suite/run.sh test [-k NAME]   run the emulator tests (results in suite/out/results-*.json)
#   suite/run.sh harvest   walk the apps and write suite/out/harvest-*.jsonl
#   suite/run.sh stop      shut the emulator down
#   suite/run.sh jev start|stop|status   the local /v1/systemone stand-in (finetune/servers/systemone.py, CPU,
#                          vox-jevlike) on 127.0.0.1:8765; log in suite/out/systemone.log
#   suite/run.sh all       build, boot, setup, test, harvest, stop (stops the emulator even on failure)
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dev() { "$here/dev" "$@"; }
py() { dev env PYTHONPATH="$here/suite" python3 "$@"; }
cmd="${1:-}"; shift || true
case "$cmd" in
  # pub get first: it (re)generates ui/.android/include_flutter.groovy, which settings.gradle.kts applies.
  build)   dev bash -c 'cd ../ui && flutter pub get' && dev gradle --console=plain assembleDebug :app:testDebugUnitTest ;;
  boot)    dev suite/emu.sh start ;;
  setup)   py suite/setup_device.py "$@" ;;
  test)    py suite/test_suite.py "$@" ;;
  harvest) py suite/harvest.py "$@" ;;
  stop)    dev suite/emu.sh stop; dev adb kill-server || true ;;
  jev)
    # "[b]in/uvicorn servers" matches only the venv uvicorn process (the bracket keeps pgrep from matching itself, and
    # "bin/" keeps it from matching a shell whose command text merely mentions the server).
    case "${1:-status}" in
      start)
        if pgrep -f "[b]in/uvicorn servers" >/dev/null; then echo "systemone already running"; exit 0; fi
        mkdir -p "$here/suite/out"
        # Redirect the whole group, so no process keeps the caller's stdout open.
        ( cd "$here/../finetune" && exec env PYTHONDONTWRITEBYTECODE=1 setsid nix shell nixpkgs#python313 nixpkgs#uv nixpkgs#gcc -c bash -c \
            'source ./env.sh; source .venv/bin/activate; VOX_DEVICE=cpu VOX_THREADS=8 VOX_JEVLIKE_CKPT=runs/sweep-v5-e5-small-e3.pt VOX_JEVLIKE_TARGET_CKPT=runs/jl11-K1-s9.pt VOX_JEVLIKE_TARGET_FORMAT=v2i exec uvicorn servers.systemone:app --port 8765' \
        ) >"$here/suite/out/systemone.log" 2>&1 </dev/null &
        for _ in $(seq 1 180); do
          if curl -fsS http://127.0.0.1:8765/health >/dev/null 2>&1; then echo "systemone up: $(curl -fsS http://127.0.0.1:8765/health)"; exit 0; fi
          sleep 2
        done
        echo "systemone did not come up; see suite/out/systemone.log"; exit 1 ;;
      stop)
        pids=$(pgrep -f "[b]in/uvicorn servers" || true)
        if [ -z "$pids" ]; then echo "systemone not running"; exit 0; fi
        kill $pids; sleep 2; pgrep -f "[b]in/uvicorn servers" && { echo "still running: $(pgrep -f '[b]in/uvicorn servers')"; exit 1; }
        echo "systemone stopped ($pids)" ;;
      status) pgrep -fa "[b]in/uvicorn servers" || echo "not running"; curl -fsS http://127.0.0.1:8765/health 2>/dev/null || true; echo ;;
      *) echo "usage: suite/run.sh jev start|stop|status"; exit 2 ;;
    esac ;;
  all)
    trap '"$0" stop' EXIT
    "$0" build; "$0" boot; "$0" setup
    rc=0; "$0" test || rc=$?
    "$0" harvest || rc=$?
    exit $rc ;;
  *) sed -n '2,11p' "$0"; exit 2 ;;
esac
