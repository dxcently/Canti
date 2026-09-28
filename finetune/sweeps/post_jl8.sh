#!/usr/bin/env bash
# jl8 post: seed-pooled paired comparisons, per-seed paired suites J4 vs C, batch-1 latency, v5 phrase test.
#   bash sweeps/post_jl8.sh [J4 variant tag, e.g. J4-a08]
cd /home/khoa/VOX/finetune
run_py() { nix shell nixpkgs#python313 nixpkgs#uv -c bash -c "source ./env.sh; source .venv/bin/activate; $(printf '%q ' "$@")"; }
V=students/verdict/runs/verdict-bi-real-v1d
J=${1:-J4}
r() { echo runs/jl8-$1-s7.pt runs/jl8-$1-s8.pt runs/jl8-$1-s9.pt; }
SETS="dev_test test_old diag_x val_all"
run_py python students/jevlike/seedpool.py --a $(r $J) --b $(r C) --name jl8-$J-vs-C --sets $SETS 2>&1 | grep -E '^\||wrote|Error|Trace'
run_py python students/jevlike/seedpool.py --a $(r $J) --b $V --name jl8-$J-vs-v1d --sets dev_test test_old diag_x 2>&1 | grep -E '^\||wrote|Error|Trace'
if [ "$J" = J4 ]; then
  run_py python students/jevlike/seedpool.py --a $(r C) --b $V --name jl8-C-vs-v1d --sets dev_test test_old diag_x 2>&1 | grep -E '^\||wrote|Error|Trace'
  run_py python students/jevlike/seedpool.py --a $(r C) --b runs/jl7-J1p.pt runs/jl7-J1p-s8.pt --name jl8-C-vs-jl7J1p --sets $SETS 2>&1 | grep -E '^\||wrote|Error|Trace'
fi
for s in 7 8 9; do
  run_py python students/jevlike/suite_jl.py --run runs/jl8-$J-s$s.pt --champion runs/jl8-C-s$s.pt --name jl8-$J-s$s-vs-C-s$s \
    --build data/real-targets-v2/b4a --no-gate --sets dev_test test_old diag_x val_all > sweeps/logs/jl8-$J-s$s-vs-C-s$s.suite.log 2>&1
  echo "== $J-s$s vs C-s$s"; grep -E "^(dev_test|test_old|val_all|diag_x):" sweeps/logs/jl8-$J-s$s-vs-C-s$s.suite.log
done
if [ "$J" = J4 ]; then
  run_py python students/jevlike/suite_jl.py --latency runs/jl8-C-s7.pt runs/jl8-J4-s7.pt $V --n 200 --name jl8 2>&1 | grep '^{'
  run_py python students/jevlike/suite_jl.py --latency runs/jl8-C-s7.pt runs/jl8-J4-s7.pt $V --n 50 --cpu --name jl8 2>&1 | grep '^{'
fi
run_py python students/jevlike/suite_jl.py --v5 $(r C) $(r $J) $V --name jl8-$J 2>&1 | grep -E '^\{|wrote'
echo post done
