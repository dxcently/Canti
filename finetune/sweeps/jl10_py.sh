#!/usr/bin/env bash
# jl10: run a python command in the finetune env (torch/ROCm needs the nix shell): bash sweeps/jl10_py.sh python x.py ...
cd /home/khoa/VOX/finetune
nix shell nixpkgs#python313 nixpkgs#uv nixpkgs#gcc -c bash -c "source ./env.sh; source .venv/bin/activate; export CC=gcc; $(printf '%q ' "$@")"
