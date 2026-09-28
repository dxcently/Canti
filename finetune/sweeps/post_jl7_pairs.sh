#!/usr/bin/env bash
# jl7 post: paired J-vs-J suites (cached preds), batch-1 latency, v5 phrase test.
cd /home/khoa/VOX/finetune
run_py() { nix shell nixpkgs#python313 nixpkgs#uv -c bash -c "source ./env.sh; source .venv/bin/activate; $(printf '%q ' "$@")"; }
for p in "J2 J1" "J3 J1" "J3 J2" "J1p J1" "J2c J1p" "J2 J2c"; do set -- $p
  for s in "" "-s8"; do
    run_py python students/jevlike/suite_jl.py --run runs/jl7-$1$s.pt --champion runs/jl7-$2$s.pt --name jl7-$1$s-vs-$2$s \
      --build data/real-targets-v2/b4a --no-gate --sets dev_test test_old val diag_x syn_phrasing > sweeps/logs/jl7-$1$s-vs-$2$s.suite.log 2>&1
    echo "== $1$s vs $2$s"; grep -E "^(dev_test|test_old|val|diag_x|syn_phrasing):" sweeps/logs/jl7-$1$s-vs-$2$s.suite.log
  done
done
run_py python students/jevlike/suite_jl.py --latency runs/sweep-targets-v2-e5-small-e3.pt runs/jl7-J1.pt runs/jl7-J2.pt students/verdict/runs/verdict-bi-real-v1d --n 200 2>&1 | grep '^{'
run_py python students/jevlike/suite_jl.py --latency runs/jl7-J1.pt runs/jl7-J2.pt students/verdict/runs/verdict-bi-real-v1d --n 50 --cpu 2>&1 | grep '^{'
echo pairs done
