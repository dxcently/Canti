#!/usr/bin/env bash
# jl9: jevlike iteration 3, none-recall fix, on real-targets-v2/b4a (mix.jl7: real x3 + 12k targets-v2 synthetic).
# Base = jl8 J4 (e5-small-v2, e5 prefixes, frozen embeddings, --fast-options, KL alpha 0.5 to the honest out-of-app
# Verdict teacher, --select nll_t, --fit-temperature), 2 epochs unless EPOCHS is set.
#   J5a = J4 with the teacher's none logit shifted by its own OOF-NLL-fitted bias (+0.60/+0.58 per cross-fit seed, after /T)
#         before the softmax: teacher.jl9.nbfit.oof.jsonl (oof_teacher.py --none-bias fit).
#   J5b = J4 with --teacher-skip-none: gold-none rows get no KL (hard-label CE share only, as the teacher-less rows).
#   J5ab = both.   J5c = the chosen variant at 3 epochs: TAG=-e3 EPOCHS=3 bash sweeps/queue_jl9.sh <J5a|J5b|J5ab>
# One training job at a time. runs/jl9-<cfg><tag>-s<seed>.pt, sweeps/logs/jl9-*.{train,suite}.log, sweeps/eval/suite.jl9-*.
#   SEEDS="7 8 9" bash sweeps/queue_jl9.sh J5a J5b      (from finetune/)
set -u
cd /home/khoa/VOX/finetune
Z=data/real-targets-v2/b4a/zflip
MIX=$Z/mix.jl7.jsonl
VAL=$Z/val_real_all.jsonl
V=students/verdict/runs/verdict-bi-real-v1d
TEACH=$Z/teacher.jl8.oof.jsonl
TEACH_NB=$Z/teacher.jl9.nbfit.oof.jsonl
run_py() { nix shell nixpkgs#python313 nixpkgs#uv -c bash -c "source ./env.sh; source .venv/bin/activate; $(printf '%q ' "$@")"; }
log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
common=(--validation "$VAL" --val-limit 100000 --option-tokens 32 --epochs "${EPOCHS:-2}" --log-every 200
        --q-prefix "query: " --p-prefix "passage: " --freeze-embeddings --fast-options --select nll_t --fit-temperature)
for SEED in ${SEEDS:-7 8 9}; do
for J in "$@"; do
  name=jl9-$J${TAG:-}-s$SEED
  ckpt=runs/$name.pt
  [ -e "$ckpt" ] && { log "skip $name: $ckpt exists"; continue; }
  avail=$(df --output=avail -BG / | tail -1 | tr -dc 0-9); [ "$avail" -ge 30 ] || { log "less than 30G free"; exit 1; }
  case $J in
    J5a) extra=(--teacher-probs "$TEACH_NB" --alpha "${ALPHA:-0.5}"); note="teacher none logit + OOF-fitted bias" ;;
    J5b) extra=(--teacher-probs "$TEACH" --alpha "${ALPHA:-0.5}" --teacher-skip-none); note="no KL on gold-none rows" ;;
    J5ab) extra=(--teacher-probs "$TEACH_NB" --alpha "${ALPHA:-0.5}" --teacher-skip-none); note="teacher none bias + no KL on gold-none rows" ;;
    *) log "unknown config $J"; continue ;;
  esac
  cmd=(python students/jevlike/train.py "$MIX" "${common[@]}" --seed "$SEED" "${extra[@]}" --output "$ckpt")
  log "train $name: ${cmd[*]}"
  t0=$(date +%s)
  run_py "${cmd[@]}" > sweeps/logs/$name.train.log 2>&1 || { log "TRAIN FAILED $name"; continue; }
  tw=$(( $(date +%s) - t0 ))
  log "trained $name in ${tw}s: $(grep -h '"epoch"\|checkpoint' sweeps/logs/$name.train.log | tr '\n' ' ')"
  t1=$(date +%s)
  run_py python students/jevlike/suite_jl.py --run "$ckpt" --name "$name" --champion "$V" --build data/real-targets-v2/b4a --no-gate \
    > sweeps/logs/$name.suite.log 2>&1 || log "SUITE FAILED $name"
  sw=$(( $(date +%s) - t1 ))
  grep -E "^(dev_test|test_old|val|val_all|diag_x):" sweeps/logs/$name.suite.log
  run_py python - "$name" "$ckpt" "${cmd[*]}" "$tw" "$sw" "jl9 $J${TAG:-} (${EPOCHS:-2} ep): J4 recipe + $note; select val NLL@T, T stored; suite vs verdict-bi-real-v1d" <<'PY'
import json, sys, torch
name, ckpt, cmd, tw, sw, note = sys.argv[1:]
s = json.load(open(f"sweeps/eval/suite.{name}.json"))
m = {k: {kk: round(v["run"][kk], 4) for kk in ("acc", "none_recall", "novel_acc", "nll") if isinstance(v["run"].get(kk), float)} for k, v in s["sets"].items()}
cfg = torch.load(ckpt, map_location="cpu", weights_only=False)["config"]
fin = [json.loads(l) for l in open(f"sweeps/logs/{name}.train.log") if l.startswith('{"checkpoint"')][-1]
row = {"name": name, "status": "ok", "data_version": "data/real-targets-v2/b4a", "command": cmd, "checkpoint": ckpt,
       "train_wall_s": int(tw), "predict_wall_s": int(sw), "train_rows_per_s": fin.get("train_rows_per_s"),
       "selected": cfg.get("selected"), "temperature": cfg.get("temperature"), "train_log": f"sweeps/logs/{name}.train.log",
       "eval": f"sweeps/eval/suite.{name}.json", "metrics": m, "note": note}
open("sweeps/runs.jsonl", "a").write(json.dumps(row) + "\n")
print("recorded", name)
PY
done
done
log "queue done"
