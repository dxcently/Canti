#!/usr/bin/env bash
S=/tmp/claude-1000/-home-khoa-VOX/0bcba03f-e9b6-4ba0-860b-c17685de3cb7/scratchpad/v2
while pgrep -f "crossfit.py" >/dev/null; do sleep 60; done
cd /home/khoa/VOX/finetune
echo "== b4a lossacc_drop15 $(date +%T)"; $S/env_run.sh "python students/verdict/crossfit.py --build data/real-targets-v2/b4a --recipe lossacc_drop15 --seeds 0 1 2 --pool data/real-targets-v2/b4a/zflip/aug/pool_nohidden.jsonl --train-args \"--lr 5e-5 --epochs 3 --loss acceptable --lowconf-weight 0.5\" 2>&1 | grep -v Warn"
echo "== queue8 done $(date +%T)"
