#!/usr/bin/env bash
# v6 second seed queue: train v6-e5-small-e3-s2 (seed 11) and predict/eval on v6's three tests.
# Only legs (a)+(b) of sweeps/scratch/v6_queue.sh. No pgrep wait: run one training job at a time yourself.
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
      --note "second seed of v6-e5-small-e3 (seed 11 vs 7)"
  else
    record --name "$name" --checkpoint "$ckpt" --status "$status" --train-wall-s "$((t1 - t0))" \
      --train-log "$tlog" --command "${cmd[*]}" --note "second seed of v6-e5-small-e3 (seed 11 vs 7); failed"
  fi
}

log "v6s2 queue start"

# a+b) train v6-e5-small-e3-s2 (seed 11) and predict/evaluate it on v6's three tests
DATA=data/v6
train_one v6-e5-small-e3-s2 --seed 11

log "v6s2 queue done"
