#!/usr/bin/env bash
# Run a teachers command inside the right environment:  teachers/run.sh python -m teachers.label test_iid --limit 300
# (nix python + uv + gcc for Triton's launcher, env.sh for the ROCm runtime libraries, the ROCm torch venv)
cd /home/khoa/VOX/finetune
export PYTORCH_CUDA_ALLOC_CONF=${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}
exec nix shell nixpkgs#python313 nixpkgs#uv nixpkgs#gcc -c bash -c 'source ./env.sh; source .venv/bin/activate; exec "$@"' _ "$@"
