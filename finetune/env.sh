# Source inside: nix shell nixpkgs#python313 -c bash
# Puts the C/C++ runtime libs that the pip ROCm wheels expect onto LD_LIBRARY_PATH (NixOS has no /usr/lib).
_paths=$(nix build --no-link --print-out-paths \
  nixpkgs#stdenv.cc.cc.lib nixpkgs#zlib.out nixpkgs#zstd.out nixpkgs#libdrm.out \
  nixpkgs#numactl.out nixpkgs#elfutils.out nixpkgs#xz.out nixpkgs#bzip2.out nixpkgs#libffi.out 2>/dev/null)
for p in $_paths; do LD_LIBRARY_PATH="$p/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"; done
export LD_LIBRARY_PATH
