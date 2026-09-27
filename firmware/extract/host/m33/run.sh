#!/usr/bin/env bash
# Build m33_bench for a Cortex-M33 (the Pico 2 W's core, same FPU flags, -Os like arduino-pico) and run it under
# QEMU's mps2-an505 with -icount: prints instructions per hop and per sound end for some vectors. See m33_bench.cpp.
#   extract/host/m33/run.sh [-O2]        PROFILE=1 adds a per-section split of the front end (marks cost a little)
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
src="$here/../../src"
vec="$(cd "$here/../../../../extractor/vectors" && pwd)"
out="$here/../../../build/host/m33_bench.elf"
opt="${1:--Os}"
prof="${PROFILE:+-DVX_PROFILE}"
mkdir -p "$(dirname "$out")"
nix shell nixpkgs#gcc-arm-embedded -c arm-none-eabi-g++ -mcpu=cortex-m33 -mthumb -mfloat-abi=hard -mfpu=fpv5-sp-d16 \
  "$opt" $prof -std=gnu++17 -fno-exceptions -fno-rtti -ffunction-sections -fdata-sections -I"$src" -DVECTORS="\"$vec\"" \
  --specs=rdimon.specs -T "$here/link.ld" -nostartfiles -Wl,--gc-sections -Wl,--no-warn-rwx-segments \
  "$here/m33_bench.cpp" "$src"/*.cpp -lrdimon -lm -o "$out" 2>&1 | grep -v "is not implemented" || true
nix shell nixpkgs#qemu -c qemu-system-arm -M mps2-an505 -cpu cortex-m33 -icount shift=0 \
  -semihosting-config enable=on,target=native -nographic -monitor none -serial none -kernel "$out"
