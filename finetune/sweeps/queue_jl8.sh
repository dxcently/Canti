#!/usr/bin/env bash
# jl8: jevlike iteration 2 on real-targets-v2/b4a (mix.jl7: real x3 + 12k targets-v2 synthetic).
#   C   = J1p recipe (e5-small-v2, e5 prefixes, frozen embeddings), 2 epochs            (same-epochs control)
#   J4  = C + KL to the honest out-of-app Verdict teacher (teacher.jl8.oof.jsonl, alpha ${ALPHA:-0.5})
#   All: --fast-options (dedup + length-chunked option encoding), --select nll_t (val NLL after a val-fitted T),
#   --fit-temperature (T stored in the checkpoint config; suite_jl applies it). val is clean for this family.
# One training job at a time. runs/jl8-<cfg>-s<seed>.pt, sweeps/logs/jl8-*.{train,suite}.log, sweeps/eval/suite.jl8-*.
#   SEEDS="7 8 9" bash sweeps/queue_jl8.sh C J4        (from finetune/; TAG=-a08 ALPHA=0.8 for the alpha variant)
set -u
cd /home/khoa/VOX/finetune
Z=data/real-targets-v2/b4a/zflip
MIX=$Z/mix.jl7.jsonl
VAL=$Z/val_real_all.jsonl
V=students/verdict/runs/verdict-bi-real-v1d
TEACH=$Z/teacher.jl8.oof.jsonl
run_py() { nix shell nixpkgs#python313 nixpkgs#uv -c bash -c "source ./env.sh; source .venv/bin/activate; $(printf '%q ' "$@")"; }
log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
common=(--validation "$VAL" --val-limit 100000 --option-tokens 32 --epochs "${EPOCHS:-2}" --log-every 200
        --q-prefix "query: " --p-prefix "passage: " --freeze-embeddings --fast-options --select nll_t --fit-temperature)
for SEED in ${SEEDS:-7 8 9}; do
for J in "$@"; do
  name=jl8-$J${TAG:-}-s$SEED
  ckpt=runs/$name.pt
  [ -e "$ckpt" ] && { log "skip $name: $ckpt exists"; continue; }
  avail=$(df --output=avail -BG / | tail -1 | tr -dc 0-9); [ "$avail" -ge 30 ] || { log "less than 30G free"; exit 1; }
  case $J in
    C) extra=() ;;
    J4) extra=(--teacher-probs "$TEACH" --alpha "${ALPHA:-0.5}") ;;
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
  grep -E "^(dev_test|test_old|val|val_all|diag_x|syn_[a-z]+):" sweeps/logs/$name.suite.log
  run_py python - "$name" "$ckpt" "${cmd[*]}" "$tw" "$sw" <<'PY'
import json, sys, torch
name, ckpt, cmd, tw, sw = sys.argv[1:]
s = json.load(open(f"sweeps/eval/suite.{name}.json"))
m = {k: {kk: round(v["run"][kk], 4) for kk in ("acc", "none_recall", "novel_acc", "nll") if isinstance(v["run"].get(kk), float)} for k, v in s["sets"].items()}
cfg = torch.load(ckpt, map_location="cpu", weights_only=False)["config"]
fin = [json.loads(l) for l in open(f"sweeps/logs/{name}.train.log") if l.startswith('{"checkpoint"')][-1]
row = {"name": name, "status": "ok", "data_version": "data/real-targets-v2/b4a", "command": cmd, "checkpoint": ckpt,
       "train_wall_s": int(tw), "predict_wall_s": int(sw), "train_rows_per_s": fin.get("train_rows_per_s"),
       "selected": cfg.get("selected"), "temperature": cfg.get("temperature"), "train_log": f"sweeps/logs/{name}.train.log",
       "eval": f"sweeps/eval/suite.{name}.json", "metrics": m,
       "note": "jl8: J1p recipe 2 ep (+ KL to out-of-app Verdict teacher for J4), select val NLL@T, T stored; suite vs verdict-bi-real-v1d"}
open("sweeps/runs.jsonl", "a").write(json.dumps(row) + "\n")
print("recorded", name)
PY
done
done
log "queue done"
