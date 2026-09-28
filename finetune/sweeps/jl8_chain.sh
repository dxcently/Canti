#!/usr/bin/env bash
# jl8 chain (one GPU job at a time): honest teacher cross-fit -> C and J4 x seeds 7 8 9.
cd /home/khoa/VOX/finetune
bash sweeps/jl8_teacher.sh
[ -s data/real-targets-v2/b4a/zflip/teacher.jl8.oof.jsonl ] || { echo "no teacher; stop"; exit 1; }
SEEDS="7 8 9" bash sweeps/queue_jl8.sh C J4
echo "chain done $(date +%T)"
