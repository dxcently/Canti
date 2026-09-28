#!/usr/bin/env bash
# jl8 honest teacher: leave-apps-out cross-fit of the Verdict lossacc_drop15 recipe on the TRAIN rows only
# (pool_nohidden minus val_real_all, so no val row ever reaches the student through the teacher), then out-of-app soft
# labels for the jevlike mix (students/jevlike/oof_teacher.py). crossfit.py skips finished folds (resumable).
set -u
cd /home/khoa/VOX/finetune
run_py() { nix shell nixpkgs#python313 nixpkgs#uv nixpkgs#gcc -c bash -c "source ./env.sh; source .venv/bin/activate; export CC=gcc; $(printf '%q ' "$@")"; }
Z=data/real-targets-v2/b4a/zflip
R=jl8teach_lossacc_drop15_train
echo "== teacher cross-fit $R $(date +%T)"
run_py python students/verdict/crossfit.py --build data/real-targets-v2/b4a --recipe $R --seeds ${TSEEDS:-0 1} \
  --pool $Z/aug/pool_nohidden_train.jsonl \
  --train-args "--lr 5e-5 --epochs 3 --loss acceptable --lowconf-weight 0.5" 2>&1 | grep -v Warn
echo "== oof teacher $(date +%T)"
run_py python students/jevlike/oof_teacher.py --crossfit $Z/crossfit/$R --mix $Z/mix.jl7.jsonl --out $Z/teacher.jl8.oof.jsonl
echo "== teacher done $(date +%T)"
