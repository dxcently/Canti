#!/usr/bin/env bash
# Smoke predictions for both students (run inside the nix shell with gcc; see the READMEs). Sequential so latencies do
# not overlap each other (the GPU may still be shared with other jobs).
set -e
cd /home/khoa/VOX/finetune
source ./env.sh; source .venv/bin/activate; export CC=gcc
for sp in test_iid test_unseen_phrasing; do
  python students/verdict/predict.py --run students/verdict/runs/verdict-bi-smoke --split $sp --limit 300 --name verdict-bi-smoke --latency-cpu 50
  python students/verdict/predict.py --run students/verdict/runs/verdict-cross-smoke --split $sp --limit 300 --name verdict-cross-smoke --latency-cpu 20
  python students/kev/predict.py --run students/kev/runs/smoke --split $sp --limit 300 --name kev-smoke --latency-cpu 10
done
python students/kev/predict.py --run jaredpalmer/kev-0.8b --split test_iid --limit 300 --name kev-zeroshot --latency-gpu 0
python students/verdict/predict.py --run Manav2op/verdict-small --arch bi --split test_iid --limit 300 --name verdict-zeroshot --latency-gpu 0 --latency-cpu 0
