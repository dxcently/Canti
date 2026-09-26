#!/usr/bin/env bash
# Train + score Verdict-bi and Kev on data/v5 once the GPU is free (after the jevlike sweeps).
# Usage: bash students/queue_v5.sh <pid-to-wait-for>   (log: logs/students-v5.log)
set -u
cd "$(dirname "$0")/.."
WAIT_PID="${1:-}"
LOG=logs/students-v5.log
export VOX_DATA=data/v5
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
py() { nix shell nixpkgs#python313 nixpkgs#uv nixpkgs#gcc -c bash -c "source ./env.sh; source .venv/bin/activate; export CC=gcc VOX_DATA=$VOX_DATA PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True; $*" >> "$LOG" 2>&1; }

if [ -n "$WAIT_PID" ]; then
  log "waiting for pid $WAIT_PID (sweeps executor) to exit"
  while kill -0 "$WAIT_PID" 2>/dev/null; do sleep 60; done
fi
while pgrep -f "students/jevlike/train.py" >/dev/null; do log "a jevlike job is still running"; sleep 60; done

SPLITS=(test_iid test_unseen_phrasing test_unseen_apps)

log "TRAIN verdict-bi-v5"
if py python students/verdict/train.py --arch bi --train train --epochs 3 --batch 16 --lr 5e-5 --val-limit 1000 --out students/verdict/runs/verdict-bi-v5; then
  py python students/verdict/export_onnx.py students/verdict/runs/verdict-bi-v5 || log "onnx export failed (continuing)"
  for s in "${SPLITS[@]}"; do
    py python students/verdict/predict.py --run students/verdict/runs/verdict-bi-v5 --split "$s" --name verdict-bi-v5 --out-dir preds/v5 || log "PREDICT FAILED verdict $s"
  done
else
  log "TRAIN FAILED verdict-bi-v5"
fi

log "TRAIN kev-v5"
if py python students/kev/train.py --train train --epochs 1 --batch 4 --accum 4 --lr 5e-5 --weights-dtype bf16 --val-limit 1000 --out students/kev/runs/kev-v5; then
  for s in "${SPLITS[@]}"; do
    py python students/kev/predict.py --run students/kev/runs/kev-v5 --split "$s" --name kev-v5 --out-dir preds/v5 --latency-gpu 200 --latency-cpu 20 || log "PREDICT FAILED kev $s"
  done
else
  log "TRAIN FAILED kev-v5"
fi

for s in "${SPLITS[@]}"; do
  py python -m vox.evaluate "data/v5/$s.jsonl" $(ls preds/v5/"$s".*.jsonl preds/sweep-*v5-e5-small-e3*."$s".jsonl 2>/dev/null) --markdown || true
done
log "DONE"
