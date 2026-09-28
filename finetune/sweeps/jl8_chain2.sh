#!/usr/bin/env bash
# jl8 chain 2: post-analysis of J4, then the alpha variant J4-a08 (alpha 0.8) x 3 seeds, then its post-analysis.
cd /home/khoa/VOX/finetune
bash sweeps/post_jl8.sh J4
TAG=-a08 ALPHA=0.8 SEEDS="7 8 9" bash sweeps/queue_jl8.sh J4
bash sweeps/post_jl8.sh J4-a08
echo "chain2 done $(date +%T)"
