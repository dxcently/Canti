#!/usr/bin/env bash
# Score a Verdict bi run on real-targets-v2 (held-out real apps, real validation incl. Z Flip, X Opus diagnostic) and the targets-v2 synthetic tests.
#   [NB=<none bias>] bash students/verdict/eval_real.sh <run dir> <name> [--no-syn]   (NB: also score test with the val-fitted none bias)
# Run from finetune/ inside the training env (source ./env.sh; source .venv/bin/activate).
# Z Flip predictions stay under data/real-targets-v2/zflip/ (personal, gitignored).
set -euo pipefail
run=$1; name=$2; syn=${3:-}
R=data/real-targets-v2; Z=$R/zflip; P=preds/real-targets-v2
mkdir -p $P $Z/preds sweeps/eval
pred() { python students/verdict/predict.py --run "$run" --split "$1" --name "$name" --out-dir "$2" \
           --latency-gpu 0 --latency-cpu 0 --latency-onnx 0 > /dev/null 2>&1; }
pred $R/test_real.jsonl $P
pred $R/test_real_old.jsonl $P
pred $R/val_real.jsonl $P
if [ -s $Z/diag_x_opus.jsonl ]; then pred $Z/diag_x_opus.jsonl $Z/preds; fi
if [ -s $Z/val_real_all.jsonl ]; then pred $Z/val_real_all.jsonl $Z/preds; fi
if [ "$syn" != "--no-syn" ]; then
  for s in test_iid test_unseen_apps test_unseen_phrasing; do
    VOX_DATA=data/targets-v2 python students/verdict/predict.py --run "$run" --split $s --name "$name" --out-dir preds/targets-v2 \
      --latency-gpu 0 --latency-cpu 0 --latency-onnx 0 > /dev/null 2>&1
    python - <<EOF
import json; s=json.load(open("preds/targets-v2/$s.$name.jsonl.summary.json"))
print("synthetic $s", s["metrics"]["accuracy"], "ece", s["metrics"]["ece"])
EOF
  done
fi
for s in test_real test_real_old; do
  python -m vox.real_targets_v2 score $R/$s.jsonl $P/$s.$name.jsonl --out sweeps/eval/real-v2.$name.$s.json
  if [ -n "${NB:-}" ]; then python -m vox.real_targets_v2 score $R/$s.jsonl $P/$s.$name.jsonl --none-bias $NB --out sweeps/eval/real-v2.$name-nb.$s.json; fi
done
python -m vox.real_targets_v2 score $R/val_real.jsonl $P/val_real.$name.jsonl --out sweeps/eval/real-v2.$name.val_real.json
if [ -s $Z/diag_x_opus.jsonl ]; then
  python -m vox.real_targets_v2 score $Z/diag_x_opus.jsonl $Z/preds/diag_x_opus.$name.jsonl --out $Z/eval.$name.diag_x_opus.json
fi
if [ -s $Z/val_real_all.jsonl ]; then
  python -m vox.real_targets_v2 score $Z/val_real_all.jsonl $Z/preds/val_real_all.$name.jsonl --out $Z/eval.$name.val_real_all.json
fi
