# Brief: v6 second seed

You are one worker, inside /home/khoa/VOX/finetune. Goal: check that the v6 result (runs/sweep-v6-e5-small-e3.pt,
train.py default --seed 7) holds up with a different seed. Report exact numbers read from files.

## HARD RULES (same as sweeps/scratch/v6-brief.md, read its HARD RULES section and follow all of it)
- No git, no sudo/installs, no pip/uv install, never touch torch, ~/jevlike or ~/torch-rocm. No adb/phone/emulator.
  Never open any zflip/ directory. Never read ~/.config/vox/ollama_key. Exact PIDs only (no pgrep -f / pkill -f).
- Write only: runs/sweep-v6-e5-small-e3-s2.pt, preds/sweep-v6-e5-small-e3-s2.*, sweeps/logs/v6-e5-small-e3-s2*,
  sweeps/eval/v6-e5-small-e3-s2*, sweeps/scratch/v6s2_*, sweeps/runs.jsonl via sweeps/record.py. Never modify data/ or
  existing runs/*.pt. Keep >= 30 GB free. One training job at a time (check nothing else runs train.py first).
- Python only in the pinned env exactly as v6-brief.md says; train.py must print "device": "cuda", else stop.
- One simple command per bash call.

## Steps
1. Write sweeps/scratch/v6s2_queue.sh from sweeps/scratch/v6_queue.sh: only leg (a)+(b) — train
   name v6-e5-small-e3-s2 on data/v6 with the same args plus `--seed 11`, then predict+eval on the three data/v6 test
   splits and record the ledger row (--note "second seed of v6-e5-small-e3 (seed 11 vs 7)"). nohup it, poll every 60 s.
2. Compare with v6-e5-small-e3 (seed 7) on each split: headline metrics side by side, per-kind accuracy deltas, and
   a paired per-row comparison (rows right in one and wrong in the other; McNemar exact p) from the two preds files.
   Write sweeps/scratch/v6s2_compare.py + its output sweeps/scratch/v6s2_compare.txt.
3. Report (sweeps/scratch/v6s2-REPORT.md): wall time, the table, the paired test, whether the seed-7 result is
   within seed noise, and anything odd (e.g. a kind that swings more than 2 points).
