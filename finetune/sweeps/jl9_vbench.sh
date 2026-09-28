#!/usr/bin/env bash
# Verdict train.py rows/s, plain vs --fast-embed (alternating, 2 each), teacher-recipe args on 4800 pool rows, 1 epoch.
cd /home/khoa/VOX/finetune
run_py() { nix shell nixpkgs#python313 nixpkgs#uv -c bash -c "source ./env.sh; source .venv/bin/activate; $(printf '%q ' "$@")"; }
CK=runs/tmp-jl9-vbench
for flag in "" "--fast-embed" "" "--fast-embed"; do
  echo "== flag='$flag' $(date +%T)"
  run_py python students/verdict/train.py --arch bi --init students/verdict/runs/verdict-bi-targets-v2 \
    --train data/real-targets-v2/b4a/zflip/aug/pool_nohidden_train.jsonl --limit 4800 --epochs 1 --val-limit 0 --seed 0 --log-every 100 \
    --lr 5e-5 --loss acceptable --lowconf-weight 0.5 --out $CK $flag 2>&1 | grep -E "^step 300|wall_seconds"
done
rm -rf $CK
