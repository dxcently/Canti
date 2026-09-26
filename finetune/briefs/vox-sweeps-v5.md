# Brief: vox-sweeps (DeepSeek V4.1 executor)

Run training sweeps for the VOX "jevlike" student model and log results. You run experiments; you do not
redesign the data or the evaluation.

## Context
- Project: /home/khoa/VOX/finetune. Student trainer: students/jevlike/train.py (read its --help and docstring).
  Evaluator: vox/evaluate.py. Your earlier work is in sweeps/ (sweep.sh, record.py, headline.py, runs.jsonl);
  reuse it, but sweep.sh hardcodes data/v2. Make the data directory a parameter (DATA=data/vN) used for
  train, validation, predict AND evaluate, and add a data_version field to every new runs.jsonl row.
- Data versions (each has its own test_*.jsonl; evaluate on all three tests of the SAME version, full 2000 rows):
  v3 = four label bugs fixed. v4 = v3 + a filtered wording bank; v4's tests are byte-identical to v3's.
  v5 = the target task: new defaults, a 'screen:' context line, a new kind 'screen_phrase'. Its tests differ from v3/v4.
  Never score a model on another version's tests, and only compare numbers that share a test set.
- Headline metric: accuracy on test_unseen_phrasing. Also report ECE, false_trigger_rate and by_kind; for v5
  call out screen_phrase, cursor, unbound and not_deliberate.
- Already done (do not redo): v1-full and v2-e5-small-e3 rows in runs.jsonl. sweep-v2-e5-base-e3 was stopped on
  purpose and is obsolete; do not restart it and do not wait for it.
- The GPU is free: the other tenant was stopped. Still run one training job at a time.

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

## Sweep (in this order; each row = train, predict all 3 tests of the same data version, evaluate)
1. sweep-v3-e5-small-e3: data/v3, e5-small-v2, train-layers -1, epochs 3.
2. sweep-v4-e5-small-e3: data/v4, same settings (the v3 vs v4 difference = the effect of the wording bank).
3. sweep-v5-e5-small-e3: data/v5, same settings (the v5 baseline).
4. sweep-v5-e5-base-e3: data/v5, intfloat/e5-base-v2, batch-size 16, encoder-lr 3e-5.
5. sweep-v5-modernbert-e3: data/v5, answerdotai/ModernBERT-base, batch-size 16, encoder-lr 3e-5
   (skip with a note if it fails to load or needs new packages).
6. sweep-v5-e5-small-frozen: data/v5, e5-small-v2, train-layers 0 (the ablation).
7. sweep-v5-e5-small-e6: data/v5, e5-small-v2, epochs 6.
Use predict with the default batch size 1 so latency_ms is recorded.
Poll for progress with short sleeps (at most 300 s at a time), never one long sleep.

## Output
- sweeps/results.md: one table per data version and test set (use `python -m vox.evaluate <gold> <preds...> --markdown`),
  plus a short plain-English summary: best config, what helped, what didn't, and failures.
- sweeps/runs.jsonl: one line per run with its exact command, wall time, checkpoint path and metrics.
Keep going through the list without asking unless something is broken; if a run fails twice, log it and move on.
