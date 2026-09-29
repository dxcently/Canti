#!/usr/bin/env bash
# jl10: the seedpool/opgate part of sweeps/jl10_post_v2i.sh, rerun after seedpool.py/opgate.py learned JL_FORMAT.
set -u; cd /home/khoa/VOX/finetune
run_py() { nix shell nixpkgs#python313 nixpkgs#uv -c bash -c "source ./env.sh; source .venv/bin/activate; export JL_FORMAT=v2i; $(printf '%q ' "$@")"; }
log() { printf '[%s] %s\n' "$(date +%T)" "$*"; }
V2=data/real-targets-v2/b4a-v2i
J5C=(runs/jl9-J5b-e3-s7.pt runs/jl9-J5b-e3-s8.pt runs/jl9-J5b-e3-s9.pt)
for J in J7a J7b; do
  ck=(runs/jl10-$J-s7.pt runs/jl10-$J-s8.pt runs/jl10-$J-s9.pt)
  log "seedpool $J vs J5c (v2i)"
  run_py python students/jevlike/seedpool.py --a "${ck[@]}" --b "${J5C[@]}" --name "jl10-$J-vs-J5c-v2i" --build "$V2" --sets dev_test test_old val_all 2>&1 | grep -v Warn | tail -2
done
log "seedpool J7b vs J7a"
run_py python students/jevlike/seedpool.py --a runs/jl10-J7b-s7.pt runs/jl10-J7b-s8.pt runs/jl10-J7b-s9.pt --b runs/jl10-J7a-s7.pt runs/jl10-J7a-s8.pt runs/jl10-J7a-s9.pt --name jl10-J7b-vs-J7a-v2i --build "$V2" --sets dev_test test_old val_all 2>&1 | grep -v Warn | tail -2
log "opgate v2i"
run_py python students/jevlike/opgate.py --r "J5c=$(IFS=,; echo "${J5C[*]}")" --r J7a=runs/jl10-J7a-s7.pt,runs/jl10-J7a-s8.pt,runs/jl10-J7a-s9.pt --r J7b=runs/jl10-J7b-s7.pt,runs/jl10-J7b-s8.pt,runs/jl10-J7b-s9.pt --name jl10-v2i-cp95 --baseline J5c --bound cp95 --build "$V2" 2>&1 | grep -v Warn | tail -2
log "post v2i b done"
