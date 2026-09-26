# Source from bash:  source /home/khoa/VOX/extractor/env.sh
# NixOS has no /usr/lib: put the C++ runtime (numpy/scipy wheels) and PortAudio (optional sounddevice path)
# on LD_LIBRARY_PATH for this shell only, and activate the extractor venv. Nothing is installed system-wide.
_vox_paths=$(nix build --no-link --print-out-paths nixpkgs#stdenv.cc.cc.lib nixpkgs#zlib.out nixpkgs#portaudio 2>/dev/null)
for p in $_vox_paths; do [ -d "$p/lib" ] && LD_LIBRARY_PATH="$p/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"; done
export LD_LIBRARY_PATH
unset _vox_paths p
export VOX_EXTRACTOR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$VOX_EXTRACTOR/.venv/bin/activate"
