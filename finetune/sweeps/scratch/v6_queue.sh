#!/usr/bin/env bash
# v6 queue (popclick bindings). One train + four predict/eval legs:
#   a) train v6-e5-small-e3 on data/v6
#   b) v6 ckpt on v6 tests (inside train_one, --data-version data/v6)
#   c) OLD v5 ckpt on v6 tests   -> v5-e5-small-e3-on-v6
#   d) NEW v6 ckpt on v5 tests   -> v6-e5-small-e3-on-v5
# Unlike sweeps/sweep.sh there is NO pgrep wait: run one training job at a time yourself.
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
      --predict-wall-s "$((t2 - t1))" --train-log "$tlog" --command "${cmd[*]}"
  else
    record --name "$name" --checkpoint "$ckpt" --status "$status" --train-wall-s "$((t1 - t0))" \
      --train-log "$tlog" --command "${cmd[*]}" --note "train failed twice (or predict failed); see sweeps/logs/$name.*.log"
  fi
}

# predict + evaluate an existing checkpoint on $DATA's tests, then record a ledger row (no training).
predict_record() {  # name ckpt note
  local name="$1" ckpt="$2" note="$3"
  local t0 t1 cmd="python students/jevlike/train.py <$DATA/{test_iid,test_unseen_phrasing,test_unseen_apps}.jsonl> --predict $ckpt"
  t0=$(date +%s)
  if predict_all "$name" "$ckpt"; then
    t1=$(date +%s)
    record --name "$name" --checkpoint "$ckpt" --status ok --predict-wall-s "$((t1 - t0))" \
      --command "$cmd" --note "$note"
  else
    record --name "$name" --checkpoint "$ckpt" --status failed --command "$cmd" --note "$note"
  fi
}

log "v6 queue start"

# a+b) train v6 and predict/evaluate it on v6's three tests
DATA=data/v6
train_one v6-e5-small-e3

# c) OLD v5 ckpt scored on v6 tests
DATA=data/v6
predict_record v5-e5-small-e3-on-v6 runs/sweep-v5-e5-small-e3.pt "old bindings ckpt scored on v6"

# d) NEW v6 ckpt scored on v5 (old-bindings) tests
DATA=data/v5
predict_record v6-e5-small-e3-on-v5 runs/sweep-v6-e5-small-e3.pt "new bindings ckpt scored on v5 (old bindings; expected default-kind drop)"

log "v6 queue done"
