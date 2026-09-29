#!/usr/bin/env bash
# jl10: jevlike iteration 4. Base = jl9 J5c (J4 recipe + --teacher-skip-none, 3 epochs): e5-small-v2, e5 prefixes, frozen
# embeddings, --fast-options, KL alpha 0.5 to the honest out-of-app Verdict teacher, --select nll_t, --fit-temperature.
# Hard-none variants (step 2; sweeps/eval/diag.jl10-none.md), each a mix with the same rows and none share as mix.jl7:
#   J6a = strict drop-gold: 720 drop-gold none rows (vox.real_targets_v2.drop_gold_ok) swapped for 720 synthetic none rows
#   J6b = icon-word none rows: 720 of aug/icon_none.jsonl (vox.verdict_aug iconnone) swapped for 720 synthetic none rows
#   J6c = both (1,440 hard none rows replace all 1,440 synthetic none rows)
#   J7* = step 3, the new option text (MIX / VAL / TEACH overridable, see sweeps/jl10_v3.sh)
# One training job at a time. runs/jl10-<cfg>-s<seed>.pt, sweeps/logs/jl10-*.{train,suite}.log, sweeps/eval/suite.jl10-*.
#   SEEDS="7 8 9" bash sweeps/queue_jl10.sh J6a J6b      (from finetune/)
set -u
cd /home/khoa/VOX/finetune
Z=data/real-targets-v2/b4a/zflip
VAL=${VAL:-$Z/val_real_all.jsonl}
BUILD=${BUILD:-data/real-targets-v2/b4a}
V=students/verdict/runs/verdict-bi-real-v1d
TEACH=${TEACH:-$Z/teacher.jl8.oof.jsonl}
run_py() { nix shell nixpkgs#python313 nixpkgs#uv -c bash -c "source ./env.sh; source .venv/bin/activate; $(printf '%q ' "$@")"; }
log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
common=(--validation "$VAL" --val-limit 100000 --option-tokens 32 --epochs "${EPOCHS:-3}" --log-every 200
        --q-prefix "query: " --p-prefix "passage: " --freeze-embeddings --fast-options --select nll_t --fit-temperature
        --teacher-probs "$TEACH" --alpha 0.5 --teacher-skip-none)
for SEED in ${SEEDS:-7 8 9}; do
for J in "$@"; do
  name=jl10-$J-s$SEED
  ckpt=runs/$name.pt
  [ -e "$ckpt" ] && { log "skip $name: $ckpt exists"; continue; }
  avail=$(df --output=avail -BG / | tail -1 | tr -dc 0-9); [ "$avail" -ge 30 ] || { log "less than 30G free"; exit 1; }
  case $J in
    J5c) MIX=$Z/mix.jl7.jsonl; note="J5c control (mix.jl7)" ;;
    J6a) MIX=$Z/mix.jl10-dg.jsonl; note="strict drop-gold 720 swapped for synthetic none" ;;
    J6b) MIX=$Z/mix.jl10-ic.jsonl; note="icon-word none 720 swapped for synthetic none" ;;
    J6c) MIX=$Z/mix.jl10-dgic.jsonl; note="drop-gold 720 + icon-word none 720 swapped for all synthetic none" ;;
    J7*) MIX=${MIX:?set MIX for $J}; note=${NOTE:-new option text} ;;
    *) log "unknown config $J"; continue ;;
  esac
  cmd=(python students/jevlike/train.py "$MIX" "${common[@]}" --seed "$SEED" --output "$ckpt")
  log "train $name: ${cmd[*]}"
  t0=$(date +%s)
  run_py "${cmd[@]}" > sweeps/logs/$name.train.log 2>&1 || { log "TRAIN FAILED $name"; continue; }
  tw=$(( $(date +%s) - t0 ))
  log "trained $name in ${tw}s: $(grep -h '"epoch"\|checkpoint' sweeps/logs/$name.train.log | tr '\n' ' ' | cut -c1-400)"
  t1=$(date +%s)
  run_py python students/jevlike/suite_jl.py --run "$ckpt" --name "$name" --champion "$V" --build "$BUILD" --no-gate ${SUITE_ARGS:-} \
    > sweeps/logs/$name.suite.log 2>&1 || log "SUITE FAILED $name"
  sw=$(( $(date +%s) - t1 ))
  grep -E "^(dev_test|test_old|val|val_all|diag_x):" sweeps/logs/$name.suite.log
  run_py python - "$name" "$ckpt" "${cmd[*]}" "$tw" "$sw" "jl10 $J (${EPOCHS:-3} ep): J5c recipe + $note; select val NLL@T, T stored; suite vs verdict-bi-real-v1d" "$BUILD" <<'PY'
import json, sys, torch
name, ckpt, cmd, tw, sw, note, build = sys.argv[1:]
s = json.load(open(f"sweeps/eval/suite.{name}.json"))
m = {k: {kk: round(v["run"][kk], 4) for kk in ("acc", "none_recall", "novel_acc", "nll") if isinstance(v["run"].get(kk), float)} for k, v in s["sets"].items()}
cfg = torch.load(ckpt, map_location="cpu", weights_only=False)["config"]
fin = [json.loads(l) for l in open(f"sweeps/logs/{name}.train.log") if l.startswith('{"checkpoint"')][-1]
row = {"name": name, "status": "ok", "data_version": build, "command": cmd, "checkpoint": ckpt,
       "train_wall_s": int(tw), "predict_wall_s": int(sw), "train_rows_per_s": fin.get("train_rows_per_s"),
       "selected": cfg.get("selected"), "temperature": cfg.get("temperature"), "train_log": f"sweeps/logs/{name}.train.log",
       "eval": f"sweeps/eval/suite.{name}.json", "metrics": m, "note": note}
open("sweeps/runs.jsonl", "a").write(json.dumps(row) + "\n")
print("recorded", name)
PY
done
done
log "queue done"
