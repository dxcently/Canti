# Brief: vox-sweeps (DeepSeek V4.1 executor)

Run training sweeps for the VOX "jevlike" student model and log results. You run experiments; you do not
redesign the data or the evaluation.

## Context
- Project: /home/khoa/VOX/finetune. Student trainer: students/jevlike/train.py (read its --help and docstring).
  Evaluator: vox/evaluate.py. Data: data/v1 (few wordings) and data/v2 (rich training wordings).
- The THREE FIXED TEST SETS are data/v2/test_iid.jsonl, data/v2/test_unseen_phrasing.jsonl,
  data/v2/test_unseen_apps.jsonl (identical copies of data/v1's). Always evaluate on all three, full 2000 rows.
  The headline metric is accuracy on test_unseen_phrasing; also report ECE, false_trigger_rate and by_kind.
- Known result: e5-small-v2, full encoder trainable, 4k rows of v1, 2 epochs -> 95% iid but 75.5% unseen_phrasing
  (app_rule 50%, sequence 38%, global_rule 61%).

## Scope and permissions
- Write ONLY to: /home/khoa/VOX/finetune/sweeps/ (scripts, logs, results), runs/sweep-* checkpoints,
  and preds/sweep-* prediction files. Do not edit students/, vox/, teachers/, data/ or any other file.
- No git operations, no package installs that touch torch (see environment). No network except HF model downloads.

## Environment (critical)
- NixOS, AMD Radeon 8060S (gfx1151), 32 GiB GPU memory SHARED with other jobs. Run one training job at a time.
- Always run python like this:
  cd /home/khoa/VOX/finetune && nix shell nixpkgs#python313 nixpkgs#uv -c bash -c 'source ./env.sh; source .venv/bin/activate; <command>'
- NEVER pip/uv install anything that could replace torch. If an encoder needs a package, stop and report instead.
- Before starting, wait until no other "students/jevlike/train.py" process is running (pgrep -f), then start.
  A full 40k-row run is in progress (runs/jevlike-e5-v1-full.pt, log logs/jevlike-e5-v1-full.log); when it
  finishes, evaluate it too and include it as the first row of the results.

## Sweep (in this order; each row = train, predict all 3 tests, evaluate)
1. v2 data, e5-small-v2, train-layers -1, epochs 3 (full 40k).
2. v2 data, intfloat/e5-base-v2, train-layers -1, epochs 3, batch-size 16, encoder-lr 3e-5.
3. v2 data, answerdotai/ModernBERT-base, train-layers -1, epochs 3, batch-size 16, encoder-lr 3e-5
   (skip with a note if it fails to load or needs new packages).
4. v2 data, e5-small-v2, train-layers 0 (frozen, jevlike's original setting) — the ablation.
5. v2 data, e5-small-v2, train-layers -1, epochs 6 — does longer help or overfit?
Use predict with the default batch size 1 so latency_ms is recorded; note GPU sharing makes it approximate.

## Output
- sweeps/results.md: one table per test set (use `python -m vox.evaluate <gold> <preds...> --markdown`),
  plus a short plain-English summary: best config, what helped, what didn't, and failures.
- sweeps/runs.jsonl: one line per run with its exact command, wall time, checkpoint path and metrics.
Keep going through the list without asking unless something is broken; if a run fails twice, log it and move on.
