#!/usr/bin/env bash
# jl10 chain (one GPU job at a time): J6 post-scoring, then the new-option-text recipes J7a/J7b (mix on b4a-v2i real rows
# + targets-v2t synthetic rows; val and suite sets from the b4a-v2i build), then their seedpool vs J5c on the v2i sets
# (J5c scored on the v2i text: what shipping the new text with the old model would cost) and the tree_probe predictions.
set -u
cd /home/khoa/VOX/finetune
run_py() { nix shell nixpkgs#python313 nixpkgs#uv -c bash -c "source ./env.sh; source .venv/bin/activate; $(printf '%q ' "$@")"; }
log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
V2=data/real-targets-v2/b4a-v2i
log "post J6"; bash sweeps/post_jl10.sh J6a J6b J6c
log "train J7a"; MIX=$V2/zflip/mix.jl10-v2i.jsonl NOTE="new option text v2i + targets-v2t synthetic (tree queries)" VAL=$V2/zflip/val_real_all.jsonl BUILD=$V2 \
  bash sweeps/queue_jl10.sh J7a >> sweeps/logs/jl10-queue-step3.log 2>&1
log "train J7b"; MIX=$V2/zflip/mix.jl10-v2i-dg.jsonl NOTE="v2i + tree synthetic + strict drop-gold 720 swapped" VAL=$V2/zflip/val_real_all.jsonl BUILD=$V2 \
  bash sweeps/queue_jl10.sh J7b >> sweeps/logs/jl10-queue-step3.log 2>&1
grep -E "trained |FAILED|recorded|^(dev_test|test_old|val_all):" sweeps/logs/jl10-queue-step3.log
J5C=(runs/jl9-J5b-e3-s7.pt runs/jl9-J5b-e3-s8.pt runs/jl9-J5b-e3-s9.pt)
for J in J7a J7b; do
  ck=(runs/jl10-$J-s7.pt runs/jl10-$J-s8.pt runs/jl10-$J-s9.pt)
  log "seedpool $J vs J5c on v2i sets"
  run_py python students/jevlike/seedpool.py --a "${ck[@]}" --b "${J5C[@]}" --name "jl10-$J-vs-J5c-v2i" --build "$V2" --sets dev_test test_old val_all 2>&1 | grep -v Warn | tail -2
done
log "seedpool J7b vs J7a (v2i)"
run_py python students/jevlike/seedpool.py --a runs/jl10-J7b-s7.pt runs/jl10-J7b-s8.pt runs/jl10-J7b-s9.pt --b runs/jl10-J7a-s7.pt runs/jl10-J7a-s8.pt runs/jl10-J7a-s9.pt \
  --name jl10-J7b-vs-J7a-v2i --build "$V2" --sets dev_test test_old val_all 2>&1 | grep -v Warn | tail -2
log "opgate J7 (v2i build)"
run_py python students/jevlike/opgate.py --r "J5c=$(IFS=,; echo "${J5C[*]}")" --r J7a=runs/jl10-J7a-s7.pt,runs/jl10-J7a-s8.pt,runs/jl10-J7a-s9.pt \
  --r J7b=runs/jl10-J7b-s7.pt,runs/jl10-J7b-s8.pt,runs/jl10-J7b-s9.pt --name jl10-v2i-cp95 --baseline J5c --bound cp95 --build "$V2" 2>&1 | grep -v Warn | tail -2
log "tree_probe predictions"
mkdir -p preds/jl10
for c in runs/jl10-J7a-s7.pt runs/jl10-J7a-s8.pt runs/jl10-J7a-s9.pt runs/jl10-J7b-s7.pt runs/jl10-J7b-s8.pt runs/jl10-J7b-s9.pt runs/jl10-J6a-s7.pt "${J5C[@]}"; do
  n=$(basename $c .pt)
  run_py python students/jevlike/train.py data/targets-v2t/tree_probe.jsonl --predict $c --out preds/jl10/tree_probe.$n.jsonl 2>&1 | grep '^{'
done
log "chain done"
