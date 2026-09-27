#!/usr/bin/env bash
# Build the host CLI of the C++ extractor port and compare it with the Python reference: config, vocabulary,
# decimator, every test vector, and real audio (the live recordings + a fixed sample of the public datasets).
#   tools/check_extract.sh                 # full check (about a minute)
#   tools/check_extract.sh --no-real       # vectors only
#   tools/check_extract.sh --real 100      # 100 clips per dataset
#   tools/check_extract.sh --bench         # also time the host build per hop
#   (then tools/check_ticks.py: the joystick ticks vs extractor/joystick_core.py, report tests/tick_check_report.json)
# Report: tests/extract_check_report.json. Exit status 1 on any mismatch.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fw="$(dirname "$here")"
vox="$(dirname "$fw")"
bench=0; args=()
for a in "$@"; do
  if [ "$a" = "--bench" ]; then bench=1; else args+=("$a"); fi
done
"$fw/extract/host/build.sh"
"$vox/extractor/run" python "$here/check_extract.py" "${args[@]}"
# the joystick ticks (vx_tick.cpp) against joystick_core.Analyzer, on public dataset clips only
"$vox/extractor/run" python "$here/check_ticks.py"
if [ "$bench" = 1 ]; then
  for v in rise_20db talk_20db music_20db silence; do
    printf '%-14s' "$v"; "$fw/build/host/vx_cli" --pcm "$vox/extractor/vectors/$v.pcm" --bench 20 2>&1 >/dev/null
  done
fi
