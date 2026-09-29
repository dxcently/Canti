#!/usr/bin/env bash
# jl10 post (one GPU job at a time; run after sweeps/queue_jl10.sh): seed-pooled paired tests of each jl10 recipe vs
# J5c (= runs/jl9-J5b-e3-s{7,8,9}.pt) and the val-fitted operating point (opgate, CP95 and point bounds).
#   bash sweeps/post_jl10.sh J6a J6b J6c          (from finetune/; recipes must have all SEEDS trained + suited)
set -u
cd /home/khoa/VOX/finetune
run_py() { nix shell nixpkgs#python313 nixpkgs#uv -c bash -c "source ./env.sh; source .venv/bin/activate; $(printf '%q ' "$@")"; }
SEEDS=${SEEDS:-7 8 9}
BUILD=${BUILD:-data/real-targets-v2/b4a}
J5C=(); for s in $SEEDS; do J5C+=(runs/jl9-J5b-e3-s$s.pt); done
rs=("--r" "J5c=$(IFS=,; echo "${J5C[*]}")")
for J in "$@"; do
  ck=(); for s in $SEEDS; do ck+=(runs/jl10-$J-s$s.pt); done
  for c in "${ck[@]}"; do [ -e "$c" ] || { echo "missing $c"; exit 1; }; done
  echo "== seedpool $J vs J5c $(date +%T)"
  run_py python students/jevlike/seedpool.py --a "${ck[@]}" --b "${J5C[@]}" --name "jl10-$J-vs-J5c" --build "$BUILD" \
    --sets dev_test test_old val_all 2>&1 | grep -v Warn | tail -3
  rs+=("--r" "$J=$(IFS=,; echo "${ck[*]}")")
done
for b in cp95 point; do
  echo "== opgate $b $(date +%T)"
  run_py python students/jevlike/opgate.py "${rs[@]}" --name "jl10-$b" --baseline J5c --bound $b --build "$BUILD" 2>&1 | grep -v Warn | tail -3
done
echo "post done $(date +%T)"
