#!/usr/bin/env bash
# Build the results tables: one table per data version and test set, straight from vox.evaluate --markdown.
# Each version's table is scored only against that version's own gold; names missing preds are skipped.
# Usage: bash sweeps/make_results.sh > sweeps/results.md
set -eu
cd /home/khoa/VOX/finetune

SPLITS=(test_iid test_unseen_phrasing test_unseen_apps)
declare -A MODELS=(
  [v1]="v1-full-e5-small"
  [v2]="v2-e5-small-e3"
  [v3]="v3-e5-small-e3"
  [v4]="v4-e5-small-e3"
  [v5]="v5-e5-small-e3 v5-e5-base-e3 v5-modernbert-e3 v5-e5-small-frozen v5-e5-small-e6"
)

run_py() { nix shell nixpkgs#python313 nixpkgs#uv -c bash -c "source ./env.sh; source .venv/bin/activate; $(printf '%q ' "$@")"; }

for v in v1 v2 v3 v4 v5; do
  echo "## data/$v"
  echo
  for split in "${SPLITS[@]}"; do
    files=()
    for n in ${MODELS[$v]}; do
      [ -f "preds/sweep-$n.$split.jsonl" ] && files+=("preds/sweep-$n.$split.jsonl")
    done
    if [ ${#files[@]} -eq 0 ]; then
      echo "### $split.jsonl — no predictions"
      echo
      continue
    fi
    run_py python -m vox.evaluate "data/$v/$split.jsonl" "${files[@]}" --markdown
    echo
  done
done
