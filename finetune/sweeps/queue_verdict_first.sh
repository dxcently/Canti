#!/usr/bin/env bash
# Verdict-first queue (2026-09-26). The user asked for Verdict right after the running v5 re-run sweep, ahead of the
# jevlike v5r/targets runs. Replaces sweeps/queue_jevlike_then_verdict.sh (stopped while still waiting). Order:
#   1. Verdict-bi on data/v5 (+ int8 ONNX export)   -> the phone-model baseline
#   2. jevlike v5r + targets-v2 (sweeps/queue_v5r_targets.sh)
#   3. Verdict-bi on data/targets-v2
#   4. Kev on data/v5
# The verdict() and Kev steps are copied unchanged from queue_jevlike_then_verdict.sh.
set -u
cd "$(dirname "$0")/.."
WAIT_PID="${1:-}"
LOG=logs/queue_verdict_first.log
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
py() { nix shell nixpkgs#python313 nixpkgs#uv nixpkgs#gcc -c bash -c "source ./env.sh; source .venv/bin/activate; export CC=gcc VOX_DATA=$VOX_DATA PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True; $*" >> "$LOG" 2>&1; }
SPLITS=(test_iid test_unseen_phrasing test_unseen_apps)

if [ -n "$WAIT_PID" ]; then
  log "waiting for pid $WAIT_PID (v5 re-run sweep, incl. its predicts) to exit"
  while kill -0 "$WAIT_PID" 2>/dev/null; do sleep 60; done
fi
while pgrep -af 'students/jevlike/[t]rain\.py' | grep -q .; do log "a jevlike train/predict is still running"; sleep 60; done

verdict() {  # data-dir run-name
  export VOX_DATA="$1"; local name="$2" out="students/verdict/runs/$2" pdir="preds/${1#data/}"
  log "TRAIN $name on $VOX_DATA"
  if py python students/verdict/train.py --arch bi --train train --epochs 3 --batch 16 --lr 5e-5 --val-limit 1000 --out "$out"; then
    py python students/verdict/export_onnx.py "$out" || log "onnx export failed $name (continuing)"
    for s in "${SPLITS[@]}"; do
      py python students/verdict/predict.py --run "$out" --split "$s" --name "$name" --out-dir "$pdir" || log "PREDICT FAILED $name $s"
      py python -m vox.evaluate "$VOX_DATA/$s.jsonl" "$pdir/$s.$name.jsonl" --markdown || log "EVAL FAILED $name $s"
    done
    log "DONE $name"
  else
    log "TRAIN FAILED $name"
  fi
}

verdict data/v5 verdict-bi-v5
log "jevlike v5r + targets-v2 (sweeps/queue_v5r_targets.sh, log sweeps/logs/queue_v5r_targets.log)"
bash sweeps/queue_v5r_targets.sh > sweeps/logs/queue_v5r_targets.log 2>&1
verdict data/targets-v2 verdict-bi-targets-v2

export VOX_DATA=data/v5
log "TRAIN kev-v5"
if py python students/kev/train.py --train train --epochs 1 --batch 4 --accum 4 --lr 5e-5 --weights-dtype bf16 --val-limit 1000 --out students/kev/runs/kev-v5; then
  for s in "${SPLITS[@]}"; do
    py python students/kev/predict.py --run students/kev/runs/kev-v5 --split "$s" --name kev-v5 --out-dir preds/v5 --latency-gpu 200 --latency-cpu 20 || log "PREDICT FAILED kev $s"
  done
else
  log "TRAIN FAILED kev-v5"
fi
log "QUEUE DONE"
