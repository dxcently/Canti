#!/usr/bin/env bash
# jl10 post for the new-option-text recipes (run after sweeps/jl10_chain.sh; one GPU job at a time). suite_jl scores a
# .pt as v1 unless JL_FORMAT=v2i (jl10), so the chain's J7 suites skipped the real sets; this rescoring runs them on the
# b4a-v2i build: J7a/J7b and J5c (J5c on the v2i text = the cost of shipping the new text with the old model), then the
# paired seedpools and the opgate, and records jl10-J7*-s* rows with real-set metrics in sweeps/runs.jsonl.
set -u
cd /home/khoa/VOX/finetune
export JL_FORMAT=v2i
run_py() { nix shell nixpkgs#python313 nixpkgs#uv -c bash -c "source ./env.sh; source .venv/bin/activate; export JL_FORMAT=v2i; $(printf '%q ' "$@")"; }
log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
V2=data/real-targets-v2/b4a-v2i
V=students/verdict/runs/verdict-bi-real-v1d
J5C=(runs/jl9-J5b-e3-s7.pt runs/jl9-J5b-e3-s8.pt runs/jl9-J5b-e3-s9.pt)
for J in J7a J7b; do for s in 7 8 9; do
  name=jl10-$J-s$s; ckpt=runs/$name.pt; [ -e "$ckpt" ] || { log "missing $ckpt"; continue; }
  log "suite $name (v2i)"
  run_py python students/jevlike/suite_jl.py --run "$ckpt" --name "$name" --champion "$V" --champion-build data/real-targets-v2/b4a --build "$V2" --no-gate \
    > sweeps/logs/$name.suite-v2i.log 2>&1 || log "SUITE FAILED $name"
  grep -E "^(dev_test|test_old|val_all):" sweeps/logs/$name.suite-v2i.log | cut -c1-160
  run_py python - "$name" "$ckpt" "$J" <<'PY'
import json, sys, torch
name, ckpt, J = sys.argv[1:]
s = json.load(open(f"sweeps/eval/suite.{name}.json"))
m = {k: {kk: round(v["run"][kk], 4) for kk in ("acc", "none_recall", "novel_acc", "nll") if isinstance(v["run"].get(kk), float)} for k, v in s["sets"].items()}
cfg = torch.load(ckpt, map_location="cpu", weights_only=False)["config"]
row = {"name": name, "status": "ok", "data_version": "data/real-targets-v2/b4a-v2i", "checkpoint": ckpt, "selected": cfg.get("selected"),
       "temperature": cfg.get("temperature"), "train_log": f"sweeps/logs/{name}.train.log", "eval": f"sweeps/eval/suite.{name}.json", "metrics": m,
       "note": f"jl10 {J} rescored with JL_FORMAT=v2i on b4a-v2i (the chain's first suite row for this name scored synthetic sets only); "
               + ("v2i text + targets-v2t tree synthetic" if J == "J7a" else "v2i text + tree synthetic + strict drop-gold 720 swapped")}
open("sweeps/runs.jsonl", "a").write(json.dumps(row) + "\n"); print("recorded", name)
PY
done; done
for J in J7a J7b; do
  ck=(runs/jl10-$J-s7.pt runs/jl10-$J-s8.pt runs/jl10-$J-s9.pt)
  log "seedpool $J vs J5c (both on v2i text)"
  run_py python students/jevlike/seedpool.py --a "${ck[@]}" --b "${J5C[@]}" --name "jl10-$J-vs-J5c-v2i" --build "$V2" --sets dev_test test_old val_all 2>&1 | grep -v Warn | tail -2
done
log "seedpool J7b vs J7a"
run_py python students/jevlike/seedpool.py --a runs/jl10-J7b-s7.pt runs/jl10-J7b-s8.pt runs/jl10-J7b-s9.pt --b runs/jl10-J7a-s7.pt runs/jl10-J7a-s8.pt runs/jl10-J7a-s9.pt \
  --name jl10-J7b-vs-J7a-v2i --build "$V2" --sets dev_test test_old val_all 2>&1 | grep -v Warn | tail -2
log "opgate v2i"
run_py python students/jevlike/opgate.py --r "J5c=$(IFS=,; echo "${J5C[*]}")" --r J7a=runs/jl10-J7a-s7.pt,runs/jl10-J7a-s8.pt,runs/jl10-J7a-s9.pt \
  --r J7b=runs/jl10-J7b-s7.pt,runs/jl10-J7b-s8.pt,runs/jl10-J7b-s9.pt --name jl10-v2i-cp95 --baseline J5c --bound cp95 --build "$V2" 2>&1 | grep -v Warn | tail -2
log "tree_probe accuracy"
run_py python - <<'PY'
import json, glob, os
gold = {r["id"] if "id" in r else i: r for i, r in enumerate(json.loads(l) for l in open("data/targets-v2t/tree_probe.jsonl"))}
rows = [json.loads(l) for l in open("data/targets-v2t/tree_probe.jsonl")]
for p in sorted(glob.glob("preds/jl10/tree_probe.*.jsonl")):
    pr = [json.loads(l) for l in open(p)]
    if len(pr) != len(rows): print(p, "rows", len(pr), "!=", len(rows)); continue
    hit = kinds = None
    import collections
    ok = collections.Counter(); n = collections.Counter()
    for r, q in zip(rows, pr):
        pred = q.get("pred", q.get("label_pred", q.get("argmax")))
        if pred is None and "probs" in q: pred = max(range(len(q["probs"])), key=q["probs"].__getitem__)
        if pred is None and "logits" in q: pred = max(range(len(q["logits"])), key=q["logits"].__getitem__)
        n[r["kind"]] += 1; ok[r["kind"]] += int(pred == r["label"])
    print(os.path.basename(p), "acc", round(sum(ok.values()) / len(rows), 3), {k: round(ok[k] / n[k], 3) for k in n})
PY
log "post v2i done"
