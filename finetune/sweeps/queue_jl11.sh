#!/usr/bin/env bash
# jl11: jevlike iteration 5 on the v2i text. Base = J7b (J5c recipe on mix.jl10-v2i-dg). Variants (sweeps/eval/jl11-stageA.md):
#   K0 = J7b + tree_none synthetic rows kept when swapping in the 720 drop-gold rows
#   K1 = K0 with 1440 drop-gold rows
#   K2 = K0 + 720 "hard" drop-gold rows (evidence word kept in a sibling)
# Selection and T on val_real_all_nm (val_all + near-miss none slice from val screens); --patience 1 with 4 epochs max;
# suite on dev_test/test_old/val_all only, JL_FORMAT=v2i, JL_CACHE=1. One GPU job at a time.
#   SEEDS="7 8 9" bash sweeps/queue_jl11.sh K0 K1 K2
set -u
cd /home/khoa/VOX/finetune
Z=data/real-targets-v2/b4a-v2i/zflip
BUILD=data/real-targets-v2/b4a-v2i
VAL=${VAL:-$Z/val_real_all_nm.jsonl}
V=students/verdict/runs/verdict-bi-real-v1d
TEACH=data/real-targets-v2/b4a/zflip/teacher.jl8.oof.jsonl
run_py() { nix shell nixpkgs#python313 nixpkgs#uv -c bash -c "source ./env.sh; source .venv/bin/activate; export JL_FORMAT=v2i JL_CACHE=${JL_CACHE:-1}; $(printf '%q ' "$@")"; }
log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
common=(--validation "$VAL" --val-limit 100000 --option-tokens 32 --epochs "${EPOCHS:-4}" --patience "${PATIENCE:-1}" --log-every 200
        --q-prefix "query: " --p-prefix "passage: " --freeze-embeddings --fast-options --select nll_t --fit-temperature
        --teacher-probs "$TEACH" --alpha 0.5 --teacher-skip-none)
for SEED in ${SEEDS:-7 8 9}; do
for J in "$@"; do
  name=jl11-$J-s$SEED; ckpt=runs/$name.pt
  [ -e "$ckpt" ] && { log "skip $name: exists"; continue; }
  avail=$(df --output=avail -BG / | tail -1 | tr -dc 0-9); [ "$avail" -ge 30 ] || { log "less than 30G free"; exit 1; }
  MIX=$Z/mix.jl11-$J.jsonl; [ -e "$MIX" ] || { log "missing $MIX"; continue; }
  cmd=(python students/jevlike/train.py "$MIX" "${common[@]}" --seed "$SEED" --output "$ckpt")
  log "train $name: ${cmd[*]}"
  t0=$(date +%s)
  run_py "${cmd[@]}" > sweeps/logs/$name.train.log 2>&1 || { log "TRAIN FAILED $name"; continue; }
  tw=$(( $(date +%s) - t0 ))
  log "trained $name in ${tw}s: $(grep -h '"epoch"\|early_stop\|checkpoint' sweeps/logs/$name.train.log | tr '\n' ' ' | cut -c1-500)"
  t1=$(date +%s)
  run_py python students/jevlike/suite_jl.py --run "$ckpt" --name "$name" --champion "$V" --champion-build data/real-targets-v2/b4a --build "$BUILD" --no-gate \
    --sets dev_test test_old val_all > sweeps/logs/$name.suite.log 2>&1 || log "SUITE FAILED $name"
  sw=$(( $(date +%s) - t1 ))
  grep -E "^(dev_test|test_old|val_all):" sweeps/logs/$name.suite.log
  run_py python - "$name" "$ckpt" "${cmd[*]}" "$tw" "$sw" "jl11 $J: J7b recipe on v2i, sel/T on val_real_all_nm, patience 1 (4 ep max), no icon-none; suite v2i (JL_CACHE=1) vs verdict-bi-real-v1d" "$BUILD" <<'PY'
import json, sys, torch
name, ckpt, cmd, tw, sw, note, build = sys.argv[1:]
s = json.load(open(f"sweeps/eval/suite.{name}.json"))
m = {k: {kk: round(v["run"][kk], 4) for kk in ("acc", "none_recall", "novel_acc", "nll") if isinstance(v["run"].get(kk), float)} for k, v in s["sets"].items()}
cfg = torch.load(ckpt, map_location="cpu", weights_only=False)["config"]
fin = [json.loads(l) for l in open(f"sweeps/logs/{name}.train.log") if l.startswith('{"checkpoint"')][-1]
row = {"name": name, "status": "ok", "data_version": build, "command": cmd, "checkpoint": ckpt, "train_wall_s": int(tw), "predict_wall_s": int(sw),
       "train_rows_per_s": fin.get("train_rows_per_s"), "selected": cfg.get("selected"), "temperature": cfg.get("temperature"),
       "train_log": f"sweeps/logs/{name}.train.log", "eval": f"sweeps/eval/suite.{name}.json", "metrics": m, "note": note}
open("sweeps/runs.jsonl", "a").write(json.dumps(row) + "\n"); print("recorded", name)
PY
done; done
log "queue done"
