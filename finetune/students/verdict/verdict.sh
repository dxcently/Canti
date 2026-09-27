#!/usr/bin/env bash
# One command from labelled data to a scored, gated Verdict run:
#   build (refuses to change existing splits) -> MANIFEST -> mix -> train -> ONE suite process for every eval set
#   (screen-bootstrap CIs, paired tests vs the champion, regression gate, markdown) -> sweeps/runs.jsonl.
#   [BUILD=...] [TRAIN=...] [VAL=...] [INIT=...] [SEED=0] [CHAMPION=students/verdict/runs/verdict-bi-real-v1d] [SUITE_ARGS=...] \
#     bash students/verdict/verdict.sh <run-name> [mix args...] -- [train args...]
# Run from finetune/ inside the training env.
set -euo pipefail
name=$1
BUILD=${BUILD:-data/real-targets-v2}
if [ -z "${NO_BUILD:-}" ]; then python -m vox.real_targets_v2 build --out "$BUILD" --option-format "${OPTION_FORMAT:-v1}" ${BUILD_ARGS:-} | tail -2; fi
bash students/verdict/train_real.sh "$@"
out=students/verdict/runs/$name
python students/verdict/suite.py --run $out --build "$BUILD" --champion "${CHAMPION:-students/verdict/runs/verdict-bi-real-v1d}" ${SUITE_ARGS:-} 2>&1 \
  | grep -v "Warning\|warn(" | tee $out/suite.log | tail -40
python - "$out" "$name" <<'PY'
import json, sys, glob
out, name = sys.argv[1:]
s = json.load(open(f"sweeps/eval/suite.{name}.json"))
head = {k: {m: round(v["run"][m], 4) for m in ("acc", "none_recall", "novel_acc", "nll") if isinstance(v["run"].get(m), float)} for k, v in s["sets"].items()}
with open("sweeps/runs.jsonl", "a") as f:
    f.write(json.dumps({"name": name, "status": "scored", "checkpoint": out, "suite": f"sweeps/eval/suite.{name}.json",
                        "gate_pass": s.get("gate_pass"), "metrics": head, "note": "verdict suite"}) + "\n")
print("gate:", "PASS" if s.get("gate_pass") else "FAIL")
PY
