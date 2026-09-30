#!/usr/bin/env bash
# v6s3 queue: retrain seed 11 with --save-every-epoch --tie later (v6-e5-small-e3-s11b), then
# predict + evaluate the FINAL checkpoint and each per-epoch checkpoint on v6's three tests.
# Based on sweeps/scratch/v6s2_queue.sh. No pgrep wait: run one training job at a time yourself.
# DO NOT RUN this yourself; the coordinator launches the GPU training.
set -u
cd /home/khoa/VOX/finetune
mkdir -p sweeps/logs sweeps/eval

SPLITS=(test_iid test_unseen_phrasing test_unseen_apps)

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }

run_py() { nix shell nixpkgs#python313 nixpkgs#uv -c bash -c "source ./env.sh; source .venv/bin/activate; $(printf '%q ' "$@")"; }

record() { .venv/bin/python sweeps/record.py --data-version "$DATA" "$@"; }

predict_all() {  # name ckpt -> preds + eval json for each of $SPLITS under $DATA
  local name="$1" ckpt="$2" split
  for split in "${SPLITS[@]}"; do
    if ! run_py python students/jevlike/train.py "$DATA/$split.jsonl" --predict "$ckpt" \
         --out "preds/sweep-$name.$split.jsonl" > "sweeps/logs/$name.predict.$split.log" 2>&1; then
      log "PREDICT FAILED $name $split"; return 1
    fi
    if ! run_py python -m vox.evaluate "$DATA/$split.jsonl" "preds/sweep-$name.$split.jsonl" \
         > "sweeps/eval/$name.$split.json" 2>&1; then
      log "EVAL FAILED $name $split"; return 1
    fi
    log "evaluated $name $split: $(.venv/bin/python sweeps/headline.py "sweeps/eval/$name.$split.json" "sweep-$name.$split.jsonl")"
  done
}

train_one() {  # name [extra train args...]  (train/predict/eval on $DATA)
  local name="$1"; shift
  local ckpt="runs/sweep-$name.pt" tlog="sweeps/logs/$name.train.log"
  local cmd=(python students/jevlike/train.py "$DATA/train.jsonl" --validation "$DATA/validation.jsonl" --output "$ckpt" "$@")
  local t0 t1 t2 status=failed attempt
  for attempt in 1 2; do
    log "TRAIN $name (attempt $attempt): ${cmd[*]}"
    t0=$(date +%s)
    if run_py "${cmd[@]}" > "$tlog" 2>&1; then status=ok; break; fi
    log "TRAIN FAILED $name attempt $attempt; tail of $tlog:"; tail -3 "$tlog" | sed 's/^/    /'
    sleep 20
  done
  t1=$(date +%s)
  if [ "$status" = ok ]; then
    log "TRAIN DONE $name in $((t1 - t0))s; $(tail -1 "$tlog")"
  fi
  if [ "$status" = ok ] && predict_all "$name" "$ckpt"; then
    t2=$(date +%s)
    record --name "$name" --checkpoint "$ckpt" --status ok --train-wall-s "$((t1 - t0))" \
      --predict-wall-s "$((t2 - t1))" --train-log "$tlog" --command "${cmd[*]}" \
      --note "seed 11 retrain of v6-e5-small-e3 with --save-every-epoch --tie later (selected/final checkpoint)"
  else
    record --name "$name" --checkpoint "$ckpt" --status "$status" --train-wall-s "$((t1 - t0))" \
      --train-log "$tlog" --command "${cmd[*]}" \
      --note "seed 11 retrain of v6-e5-small-e3 with --save-every-epoch --tie later; failed"
  fi
}

predict_only() {  # name ckpt note -> predict + eval + record (no training)
  local name="$1" ckpt="$2" note="$3"
  local t0 t1
  t0=$(date +%s)
  if predict_all "$name" "$ckpt"; then
    t1=$(date +%s)
    record --name "$name" --checkpoint "$ckpt" --status ok --predict-wall-s "$((t1 - t0))" \
      --command "python students/jevlike/train.py <split>.jsonl --predict $ckpt --out preds/sweep-$name.<split>.jsonl" \
      --note "$note"
  else
    record --name "$name" --checkpoint "$ckpt" --status failed \
      --command "python students/jevlike/train.py <split>.jsonl --predict $ckpt" --note "$note; failed"
  fi
}

log "v6s3 queue start"

DATA=data/v6
# a) retrain seed 11 as v6-e5-small-e3-s11b with per-epoch checkpoints and tie-later selection
train_one v6-e5-small-e3-s11b --seed 11 --save-every-epoch --tie later

# b) predict + evaluate the FINAL checkpoint (done inside train_one) and each per-epoch checkpoint
#    on the 3 v6 splits, recording a ledger row per name
for epoch in 1 2 3; do
  predict_only "v6-e5-small-e3-s11b-e${epoch}" "runs/sweep-v6-e5-small-e3-s11b.e${epoch}.pt" \
    "per-epoch checkpoint e${epoch} of v6-e5-small-e3-s11b (seed 11, --tie later)"
done

log "v6s3 queue done"
