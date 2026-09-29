#!/usr/bin/env bash
# jl11 post (run after sweeps/queue_jl11.sh; one GPU job at a time): seedpool K0/K1/K2 vs J7b on the v2i sets, opgate with
# the point-estimate gate (CP95 shown next to it) plus the pooled dev_test+test_old bound, tree_probe predictions and accuracy.
# The opgate operating point is still fitted on val_all (like jl10) so J7b and K* are compared at the same kind of point;
# the near-miss slice only entered epoch selection and the stored T.
set -u; cd /home/khoa/VOX/finetune
run_py() { nix shell nixpkgs#python313 nixpkgs#uv -c bash -c "source ./env.sh; source .venv/bin/activate; export JL_FORMAT=v2i JL_CACHE=1; $(printf '%q ' "$@")"; }
log() { printf '[%s] %s\n' "$(date +%T)" "$*"; }
V2=data/real-targets-v2/b4a-v2i
J7B=(runs/jl10-J7b-s7.pt runs/jl10-J7b-s8.pt runs/jl10-J7b-s9.pt)
KS=${KS:-K0 K1 K2}
R=(--r "J7b=$(IFS=,; echo "${J7B[*]}")")
for J in $KS; do
  ck=(runs/jl11-$J-s7.pt runs/jl11-$J-s8.pt runs/jl11-$J-s9.pt)
  for c in "${ck[@]}"; do [ -e "$c" ] || { log "missing $c"; continue 2; }; done
  log "seedpool $J vs J7b (v2i)"
  run_py python students/jevlike/seedpool.py --a "${ck[@]}" --b "${J7B[@]}" --name "jl11-$J-vs-J7b" --build "$V2" --sets dev_test test_old val_all 2>&1 | grep -v Warn | tail -2
  R+=(--r "$J=$(IFS=,; echo "${ck[*]}")")
done
log "opgate point + pooled"
run_py python students/jevlike/opgate.py "${R[@]}" --name jl11-point --baseline J7b --bound point --pooled --build "$V2" 2>&1 | grep -v Warn | tail -2
log "opgate cp95 (reference)"
run_py python students/jevlike/opgate.py "${R[@]}" --name jl11-cp95 --baseline J7b --bound cp95 --build "$V2" 2>&1 | grep -v Warn | tail -2
log "tree_probe predictions"
mkdir -p preds/jl11
for J in $KS; do for s in 7 8 9; do
  c=runs/jl11-$J-s$s.pt; [ -e "$c" ] || continue
  run_py python students/jevlike/train.py data/targets-v2t/tree_probe.jsonl --predict $c --out preds/jl11/tree_probe.jl11-$J-s$s.jsonl 2>&1 | grep '^{'
done; done
run_py python - <<'PY'
import json, glob, os, collections
rows = [json.loads(l) for l in open("data/targets-v2t/tree_probe.jsonl")]
for p in sorted(glob.glob("preds/jl10/tree_probe.jl10-J7b*.jsonl") + glob.glob("preds/jl11/tree_probe.*.jsonl")):
    pr = [json.loads(l) for l in open(p)]
    if len(pr) != len(rows): print(p, "rows", len(pr), "!=", len(rows)); continue
    ok = collections.Counter(); n = collections.Counter()
    for r, q in zip(rows, pr):
        pred = q.get("pred", q.get("label_pred", q.get("argmax")))
        if pred is None and "probs" in q: pred = max(range(len(q["probs"])), key=q["probs"].__getitem__)
        if pred is None and "logits" in q: pred = max(range(len(q["logits"])), key=q["logits"].__getitem__)
        n[r["kind"]] += 1; ok[r["kind"]] += int(pred == r["label"])
    print(os.path.basename(p), "acc", round(sum(ok.values()) / len(rows), 3), {k: round(ok[k] / n[k], 3) for k in n})
PY
log "post done"
