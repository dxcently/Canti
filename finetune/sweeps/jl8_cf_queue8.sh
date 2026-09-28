#!/usr/bin/env bash
# jl8: finish the interrupted cf_queue8 (b4a lossacc_drop15 cross-fit, seeds 0 1 2; crossfit.py skips finished folds),
# then refresh the cross-fit report + operating-point fit (sweeps/eval/cf.b4a.lossacc_drop15.fit-lossacc_drop15.{json,md}).
# Same args as cf_queue8.sh; no pgrep wait (run it only when no other GPU job is running).
set -u
cd /home/khoa/VOX/finetune
run_py() { nix shell nixpkgs#python313 nixpkgs#uv nixpkgs#gcc -c bash -c "source ./env.sh; source .venv/bin/activate; export CC=gcc; $(printf '%q ' "$@")"; }
echo "== b4a lossacc_drop15 $(date +%T)"
run_py python students/verdict/crossfit.py --build data/real-targets-v2/b4a --recipe lossacc_drop15 --seeds 0 1 2 \
  --pool data/real-targets-v2/b4a/zflip/aug/pool_nohidden.jsonl \
  --train-args "--lr 5e-5 --epochs 3 --loss acceptable --lowconf-weight 0.5" 2>&1 | grep -v Warn
echo "== cf_eval $(date +%T)"
run_py python students/verdict/cf_eval.py --build data/real-targets-v2/b4a --recipes lossacc_drop15 --fit lossacc_drop15 2>&1 | tail -30
echo "== done $(date +%T)"
