#!/usr/bin/env bash
# Build (and optionally flash) the VOX node firmware. Regenerates test_sounds.h from the Python extractor first,
# so the canned lines cannot drift from extractor/vox_extract.
#
#   tools/build.sh                 # secure build  -> build/vox_node/
#   tools/build.sh --insecure      # debug build without encryption -> build/vox_node_insecure/
#   tools/build.sh --upload        # ... and flash: `bootsel` over /dev/ttyACM0 (PORT=...), then picotool
#                                  # (if the board is not running VOX firmware: hold BOOTSEL while plugging in)
#   tools/build.sh --no-gen        # skip the extractor step (uses the committed test_sounds.h)
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fw="$(dirname "$here")"
vox="$(dirname "$fw")"
FQBN="rp2040:rp2040:rpipico2w:ipbtstack=ipv4btcble"
PORT="${PORT:-/dev/ttyACM0}"
insecure=0; upload=0; gen=1
for a in "$@"; do
  case "$a" in
    --insecure) insecure=1 ;;
    --upload) upload=1 ;;
    --no-gen) gen=0 ;;
    *) echo "unknown option $a" >&2; exit 2 ;;
  esac
done

if [ "$gen" = 1 ]; then
  "$vox/extractor/run" python "$here/gen_test_sounds.py"
fi

UDEV=$(nix build --no-link --print-out-paths nixpkgs#systemdLibs)   # the core's picotool needs libudev
acli() { LD_LIBRARY_PATH="$UDEV/lib" nix shell nixpkgs#arduino-cli -c arduino-cli --config-file "$fw/arduino-cli.yaml" "$@"; }

out="$fw/build/vox_node"; flags=""
if [ "$insecure" = 1 ]; then out="$fw/build/vox_node_insecure"; flags="-DVOX_INSECURE=1"; fi
cd "$fw"
acli compile --fqbn "$FQBN" --build-property "compiler.cpp.extra_flags=$flags" \
  --build-path "$out.cache" --output-dir "$out" arduino/vox_node
if [ "$upload" = 1 ]; then
  # arduino-cli's default UF2 upload needs udisksctl to mount the BOOTSEL drive; picotool talks USB directly.
  picotool() { nix run nixpkgs#picotool -- "$@"; }
  if ! picotool info >/dev/null 2>&1; then
    if [ -w "$PORT" ]; then
      stty -F "$PORT" 115200 raw -echo -hupcl && printf 'bootsel\n' > "$PORT" || true
    fi
    for _ in $(seq 60); do picotool info >/dev/null 2>&1 && break; sleep 0.5; done
  fi
  picotool load -x "$out/vox_node.ino.uf2"
  # the serial port comes back after ~2 s (udev applies its permissions a moment later)
  for _ in $(seq 40); do [ -r "$PORT" ] && [ -w "$PORT" ] && break; sleep 0.5; done
  sleep 1
fi
