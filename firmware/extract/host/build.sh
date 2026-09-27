#!/usr/bin/env bash
# Build the host CLI of the extractor port (same sources as the firmware) into firmware/build/host/:
#   vx_cli         float32 per-frame DSP, as on the Pico
#   vx_cli_double  the same code with -DVX_REAL_DOUBLE (porting check: must match Python to ~1e-9)
#   vx_cli_f32acc  float32 accumulators too (-DVX_ACC_FLOAT), to show what that costs in exactness
# Uses the host g++ if there is one, else `nix shell nixpkgs#gcc`.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
src="$here/../src"
out="$here/../../build/host"
mkdir -p "$out"
CXX="${CXX:-}"
if [ -z "$CXX" ]; then
  if command -v g++ >/dev/null; then CXX=g++; else CXX="nix shell nixpkgs#gcc -c g++"; fi
fi
# -ffp-contract=off: no fused multiply-add on the host, so float32 results do not depend on the host CPU
flags=(-O2 -std=c++17 -Wall -Wextra -Wno-unused-parameter -ffp-contract=off -I"$src")
srcs=("$src"/*.cpp "$here/vx_cli.cpp")
$CXX "${flags[@]}" -o "$out/vx_cli" "${srcs[@]}" -lm
$CXX "${flags[@]}" -DVX_REAL_DOUBLE -o "$out/vx_cli_double" "${srcs[@]}" -lm
$CXX "${flags[@]}" -DVX_ACC_FLOAT -o "$out/vx_cli_f32acc" "${srcs[@]}" -lm
echo "built $out/vx_cli{,_double,_f32acc}"
# The sketch's core-0/core-1 glue (arduino/vox_node/ext.cpp) with two host threads (Arduino.h stubbed)
sketch="$here/../../arduino/vox_node"
$CXX "${flags[@]}" -I"$here/stub" -I"$sketch" -o "$out/ext_sim" "$src"/*.cpp "$sketch/ext.cpp" "$here/ext_sim.cpp" -lm -lpthread
echo "built $out/ext_sim"
