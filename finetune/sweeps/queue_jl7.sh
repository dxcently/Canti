#!/usr/bin/env bash
# jl7: jevlike retrain on real-targets-v2/b4a (+ targets-v2 synthetic), and whether Verdict helps it.
#   J1 e5-small-v2 init; J2 Verdict v1d encoder init; J3 = J2 + KL to Verdict v1d soft labels.
# One training job at a time; each run -> runs/jl7-<run>.pt, sweeps/logs/jl7-<run>.{train,suite}.log, suite JSON/md in sweeps/eval.
#   bash sweeps/queue_jl7.sh J1 J2 J3        (from finetune/; SEED=7 default)
set -u
cd /home/khoa/VOX/finetune
SEED=${SEED:-7}
Z=data/real-targets-v2/b4a/zflip
MIX=$Z/mix.jl7.jsonl
VAL=$Z/val_real_all.jsonl
V=students/verdict/runs/verdict-bi-real-v1d
TEACH=$Z/teacher.jl7.v1d.jsonl
run_py() { nix shell nixpkgs#python313 nixpkgs#uv -c bash -c "source ./env.sh; source .venv/bin/activate; $(printf '%q ' "$@")"; }
log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
common=(--validation "$VAL" --val-limit 100000 --option-tokens 32 --epochs "${EPOCHS:-3}" --seed "$SEED" --log-every 200)
vargs=(--hf-model "$V" --q-prefix "query: " --p-prefix "passage: " --freeze-embeddings)
for J in "$@"; do
  tag=${TAG:-}
  name=jl7-$J$tag; [ "$SEED" != 7 ] && name=$name-s$SEED
  ckpt=runs/$name.pt
  [ -e "$ckpt" ] && { log "skip $name: $ckpt exists"; continue; }
  avail=$(df --output=avail -BG / | tail -1 | tr -dc 0-9); [ "$avail" -ge 30 ] || { log "less than 30G free"; exit 1; }
  case $J in
    J1) extra=() ;;
    J2) extra=("${vargs[@]}") ;;
    J3) extra=("${vargs[@]}" --teacher-probs "$TEACH" --alpha "${ALPHA:-0.5}") ;;
    *) extra=(${EXTRA:-}) ;;
  esac
  extra+=(${MORE:-})
  cmd=(python students/jevlike/train.py "$MIX" "${common[@]}" "${extra[@]}" --output "$ckpt")
  log "train $name: ${cmd[*]}"
  t0=$(date +%s)
  run_py "${cmd[@]}" > sweeps/logs/$name.train.log 2>&1 || { log "TRAIN FAILED $name"; continue; }
  tw=$(( $(date +%s) - t0 ))
  log "trained $name in ${tw}s: $(grep -h '"epoch"\|checkpoint' sweeps/logs/$name.train.log | tr '\n' ' ')"
  t1=$(date +%s)
  run_py python students/jevlike/suite_jl.py --run "$ckpt" --name "$name" --champion "$V" --build data/real-targets-v2/b4a --no-gate \
    > sweeps/logs/$name.suite.log 2>&1 || log "SUITE FAILED $name"
  sw=$(( $(date +%s) - t1 ))
  grep -E "^(dev_test|test_old|val|val_all|diag_x|syn_[a-z]+):" sweeps/logs/$name.suite.log
  run_py python - "$name" "$ckpt" "${cmd[*]}" "$tw" "$sw" <<'PY'
import json, sys
name, ckpt, cmd, tw, sw = sys.argv[1:]
s = json.load(open(f"sweeps/eval/suite.{name}.json"))
m = {k: {kk: round(v["run"][kk], 4) for kk in ("acc", "none_recall", "novel_acc", "nll") if isinstance(v["run"].get(kk), float)} for k, v in s["sets"].items()}
row = {"name": name, "status": "ok", "data_version": "data/real-targets-v2/b4a", "command": cmd, "checkpoint": ckpt,
       "train_wall_s": int(tw), "predict_wall_s": int(sw), "train_log": f"sweeps/logs/{name}.train.log",
       "eval": f"sweeps/eval/suite.{name}.json", "metrics": m, "note": "jl7: jevlike on b4a mix (real x3 + 12k targets-v2), suite vs verdict-bi-real-v1d"}
open("sweeps/runs.jsonl", "a").write(json.dumps(row) + "\n")
print("recorded", name)
PY
done
log "queue done"
