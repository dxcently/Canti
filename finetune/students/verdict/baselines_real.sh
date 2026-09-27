#!/usr/bin/env bash
# Baselines on real-targets-v2: current Verdict (stored T and T refit on real val) and jevlike targets-v2-e5-small-e3.
# Run from finetune/ inside the training env.
set -euo pipefail
R=data/real-targets-v2; Z=$R/zflip; P=preds/real-targets-v2; base=students/verdict/runs/verdict-bi-targets-v2
mkdir -p $P sweeps/eval
[ "${SKIP_BASE:-0}" = 1 ] || bash students/verdict/eval_real.sh $base verdict-bi-targets-v2 --no-syn
T=$(python students/verdict/fit_temp.py --run $base --val $Z/val_real_all.jsonl | tail -1 | python -c "import json,sys; print(json.load(sys.stdin)['T'])")
echo "refit T on real val: $T"
for s in test_real test_real_old val_real; do
  python students/verdict/predict.py --run $base --split $R/$s.jsonl --name verdict-bi-targets-v2-realT --out-dir $P --temperature $T \
    --latency-gpu 0 --latency-cpu 0 --latency-onnx 0 > /dev/null 2>&1
  python -m vox.real_targets_v2 score $R/$s.jsonl $P/$s.verdict-bi-targets-v2-realT.jsonl --out sweeps/eval/real-v2.verdict-bi-targets-v2-realT.$s.json
  python students/jevlike/train.py $R/$s.jsonl --predict runs/sweep-targets-v2-e5-small-e3.pt --out $P/$s.jevlike-targets-v2-e5-small-e3.jsonl > /dev/null 2>&1
  python -m vox.real_targets_v2 score $R/$s.jsonl $P/$s.jevlike-targets-v2-e5-small-e3.jsonl --out sweeps/eval/real-v2.jevlike-targets-v2-e5-small-e3.$s.json
done
