#!/usr/bin/env bash
# jl9 post (one GPU job at a time, run after the training queue): OptionCache verification, batch-1 latency
# (uncached / cached jevlike vs Verdict v1d, GPU + CPU), Verdict --fast-embed numerics + rows/s A/B, and one teacher
# cross-fit fold (seed 0, fold 0) re-timed with --fast-embed (new recipe name; the jl8 teacher is untouched).
cd /home/khoa/VOX/finetune
run_py() { nix shell nixpkgs#python313 nixpkgs#uv nixpkgs#gcc -c bash -c "source ./env.sh; source .venv/bin/activate; export CC=gcc; $(printf '%q ' "$@")"; }
V=students/verdict/runs/verdict-bi-real-v1d
J=${JL:-runs/jl9-J5b-s7.pt}
echo "== cache verify $(date +%T)"; run_py python sweeps/jl9_cacheverify.py $J 2>&1 | grep '^{'
echo "== latency GPU $(date +%T)"
run_py python students/jevlike/suite_jl.py --latency $J $V --n 200 --name jl9-nocache 2>&1 | grep '^{'
run_py python students/jevlike/suite_jl.py --latency $J $V --n 200 --name jl9-cache --jl-cache 2>&1 | grep '^{'
echo "== latency CPU $(date +%T)"
run_py python students/jevlike/suite_jl.py --latency $J $V --n 50 --cpu --name jl9-nocache 2>&1 | grep '^{'
run_py python students/jevlike/suite_jl.py --latency $J $V --n 50 --cpu --name jl9-cache --jl-cache 2>&1 | grep '^{'
echo "== verdict fast-embed verify $(date +%T)"; run_py python sweeps/jl9_vverify.py 2>&1 | grep '^{'
echo "== verdict fast-embed bench $(date +%T)"; bash sweeps/jl9_vbench.sh
echo "== teacher fold re-time $(date +%T)"
Z=data/real-targets-v2/b4a/zflip
run_py python students/verdict/crossfit.py --build data/real-targets-v2/b4a --recipe jl9speed_fastembed_train --seeds 0 --folds 0 \
  --pool $Z/aug/pool_nohidden_train.jsonl \
  --train-args "--lr 5e-5 --epochs 3 --loss acceptable --lowconf-weight 0.5 --fast-embed" 2>&1 | grep -v Warn
grep -h "rows/s" $Z/crossfit/jl9speed_fastembed_train/s0/f0.train.log | tail -1
grep -h '"wall_seconds"' $Z/crossfit/jl9speed_fastembed_train/s0/f0.train.log $Z/crossfit/jl8teach_lossacc_drop15_train/s0/f0.train.log
echo "post done $(date +%T)"
