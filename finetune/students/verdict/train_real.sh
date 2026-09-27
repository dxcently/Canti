#!/usr/bin/env bash
# One real-targets-v2 training run, reproducible: mix -> train -> run_info.json (+ MANIFEST.json, mix sidecar) -> sweeps/runs.jsonl.
#   [BUILD=data/real-targets-v2] [TRAIN=<real train file>] [VAL=<val file>] [INIT=<init run>] [SEED=0] \
#     bash students/verdict/train_real.sh <run-name> [mix args...] -- [train args...]
# Run from finetune/ inside the training env. The mix contains Z Flip rows, so it is written under <build>/zflip/ (local only).
# Recipe note (2026-09-27): train.py no longer applies weight decay to LayerNorm weights and biases (--decay-norm-bias 0).
# v1a-v1e used decay on everything; pass --decay-norm-bias 1 to reproduce them.
set -euo pipefail
name=$1; shift
argv_all=("$name" "$@")
mixargs=(); while [ $# -gt 0 ] && [ "$1" != "--" ]; do mixargs+=("$1"); shift; done; [ $# -gt 0 ] && shift
BUILD=${BUILD:-data/real-targets-v2}; Z=$BUILD/zflip
TRAIN=${TRAIN:-$Z/train_real_all.jsonl}; VAL=${VAL:-$Z/val_real_all.jsonl}
INIT=${INIT:-students/verdict/runs/verdict-bi-targets-v2}; SEED=${SEED:-0}
out=students/verdict/runs/$name
[ -e "$out" ] && { echo "refusing to overwrite $out"; exit 1; }
avail=$(df --output=avail -BG / | tail -1 | tr -dc 0-9); [ "$avail" -ge 30 ] || { echo "less than 30G free"; exit 1; }
[ -f "$BUILD/MANIFEST.json" ] || { echo "no $BUILD/MANIFEST.json: run 'python -m vox.real_targets_v2 build --out $BUILD' first"; exit 1; }
fmt=$(python -c "import json,sys; print(json.load(open(sys.argv[1])).get('option_format','v1'))" "$BUILD/MANIFEST.json")
mix=$Z/mix.$name.jsonl
python -m vox.real_targets_v2 mix --real "$TRAIN" --out "$mix" --seed "$SEED" "${mixargs[@]}"
t0=$(date +%s)
python students/verdict/train.py --arch bi --init "$INIT" --train "$mix" --seed "$SEED" \
  --val "$VAL" --val-limit 100000 --watch data/targets-v2/validation.jsonl --watch-limit 1000 \
  --select-best --none-floor 0.8 --log-every 500 --option-format "$fmt" --out $out "$@" 2>&1 | grep -v "^step\|Writing\|Loading" | tee $out.log.tmp
mv $out.log.tmp $out/train.log
cp "$BUILD/MANIFEST.json" $out/MANIFEST.json
cp "$mix.mix.json" $out/mix.json
python - "$out" "$name" "$BUILD" "$TRAIN" "$VAL" "$INIT" "$SEED" "$(( $(date +%s) - t0 ))" "${argv_all[@]}" <<'PY'
import json, sys, hashlib, datetime
out, name, build, train, val, init, seed, wall, *argv = sys.argv[1:]
man = json.load(open(f"{out}/MANIFEST.json")); mix = json.load(open(f"{out}/mix.json")); st = json.load(open(f"{out}/student.json"))
tm = json.load(open(f"{out}/training_metrics.json"))
info = {"name": name, "at": datetime.datetime.now().isoformat(timespec="seconds"), "argv": ["students/verdict/train_real.sh", *argv],
        "build": build, "manifest_sha256": hashlib.sha256(open(f"{out}/MANIFEST.json", "rb").read()).hexdigest(),
        "vox_code": man.get("vox_py_combined"), "train_real": train, "val": val, "init": init, "seed": int(seed),
        "mix_args": mix["args"], "mix_sha256": mix["out_sha256"], "train_args": st.get("args"), "train_wall_s": int(wall),
        "best_epoch": tm.get("best_epoch"), "temperature": tm.get("temperature")}
json.dump(info, open(f"{out}/run_info.json", "w"), indent=1)
with open("sweeps/runs.jsonl", "a") as f:
    f.write(json.dumps({"name": name, "status": "trained", "data_version": build, "command": " ".join(info["argv"]),
                        "checkpoint": out, "train_wall_s": int(wall), "run_info": info, "metrics": {}, "note": "verdict real-v2"}) + "\n")
print("run_info.json written; appended to sweeps/runs.jsonl")
PY
