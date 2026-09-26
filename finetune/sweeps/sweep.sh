#!/usr/bin/env bash
# vox-sweeps driver (v5 brief). One row = train + predict the 3 tests of the SAME data version + evaluate + record.
# DATA=data/vN is threaded through train, validation, predict AND evaluate, and stored as data_version in runs.jsonl.
# Writes only to sweeps/, runs/sweep-*.pt and preds/sweep-*.
set -u
cd /home/khoa/VOX/finetune
mkdir -p sweeps/logs sweeps/eval

SPLITS=(test_iid test_unseen_phrasing test_unseen_apps)

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }

# every python command runs inside the pinned env (see brief: env.sh + .venv)
run_py() { nix shell nixpkgs#python313 nixpkgs#uv -c bash -c "source ./env.sh; source .venv/bin/activate; $(printf '%q ' "$@")"; }

# one training job at a time: wait out any other trainer (predict jobs do not count).
# "[t]" keeps pgrep from matching the pattern in this pipeline's own cmdline.
wait_for_train() {
  while pgrep -af 'students/jevlike/[t]rain\.py' | grep -v -- '--predict' | grep -q .; do
    log "waiting for another trainer to finish"
    sleep 60
  done
}

record() { .venv/bin/python sweeps/record.py --data-version "$DATA" "$@"; }

# predict runs at train.py's built-in batch size 1, so latency_ms is recorded per row
predict_all() {  # name ckpt -> preds + eval json for each test set
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
  wait_for_train
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
      --predict-wall-s "$((t2 - t1))" --train-log "$tlog" --command "${cmd[*]}"
  else
    record --name "$name" --checkpoint "$ckpt" --status "$status" --train-wall-s "$((t1 - t0))" \
      --train-log "$tlog" --command "${cmd[*]}" --note "train failed twice (or predict failed); see sweeps/logs/$name.*.log"
  fi
}

sweep() {  # data-dir name [extra train args...]
  DATA="$1"; shift
  log "### $DATA: $*"
  train_one "$@"
}

# data version | row name | extra train args  (the brief's list, in order)
ROWS=(
  "data/v3|v3-e5-small-e3|"
  "data/v4|v4-e5-small-e3|"
  "data/v5|v5-e5-small-e3|"
  "data/v5|v5-e5-base-e3|--hf-model intfloat/e5-base-v2 --batch-size 16 --encoder-lr 3e-5"
  "data/v5|v5-modernbert-e3|--hf-model answerdotai/ModernBERT-base --batch-size 16 --encoder-lr 3e-5"
  "data/v5|v5-e5-small-frozen|--train-layers 0"
  "data/v5|v5-e5-small-e6|--epochs 6"
)

# no args = the whole list; names as args = only those rows (re-runs)
log "sweep start${*:+ (only: $*)}"
for row in "${ROWS[@]}"; do
  IFS='|' read -r data name extra <<< "$row"
  if [ $# -gt 0 ]; then
    case " $* " in *" $name "*) ;; *) continue ;; esac
  fi
  sweep "$data" "$name" $extra
done
log "sweep done"
