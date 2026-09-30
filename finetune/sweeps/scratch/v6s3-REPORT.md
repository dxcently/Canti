# v6s3 report: E1-E3 code + scripts (coordinator runs the GPU training)

Acted on the v6 seed advice (`v6s2-ADVICE.md`). No training was run and no background jobs were
launched; E1-E3 are code + 0-GPU scripts, and E4 is a queue script for the coordinator to run.

## 1. What changed

### E1 — `students/jevlike/train.py` (0 GPU, code only)
- New `--save-every-epoch`: after each epoch writes `<output stem>.e<N>.pt`
  (e.g. `runs/sweep-v6-e5-small-e3-s11b.e1.pt`) with the same `{"config", "state_dict"}` format as the
  final checkpoint, so `--predict` loads them unchanged. The `config` carries a `selected` record
  (`by: every_epoch`, epoch + val acc/nll) so each file is self-describing.
- New `--tie {earliest,later}` (default `earliest`): on an exact selection-metric tie, keep the earliest
  epoch (unchanged default, so old runs reproduce) or the later one.
- Factored the tie rule into `students/jevlike/selection.py` (`selection_improves`, torch-free so it is
  unit-testable), imported by `train.py`. The old `--select acc|nll|nll_t` semantics are byte-for-byte
  equivalent when `--tie earliest` and `--save-every-epoch` are absent.
- No default behaviour changed: the save/select code path with both new flags off is identical to before.

### E2 — `sweeps/cluster_eval.py` (new, 0 GPU)
From a data split + one or more preds files, reports per-cluster accuracy, how many clusters pass
(>= 95%), and seed mean + range when several preds are given:
- `test_unseen_phrasing`: clusters = held-out action wording (rows whose gold action's held-out wording
  appears in the context) + held-out phrase text (rows where the phrase is spoken).
- `test_unseen_apps`: clusters = (app package, screen kind) from the context.
- `test_iid`: no held-out wording exists, so overall accuracy only.
Output written to `sweeps/scratch/v6_clusters.txt` (see section 3).

### E3 — prob-average ensemble (0 GPU), `sweeps/scratch/v6_ens.py`
Elementwise mean of the seed 7 + seed 11 probability vectors (same ids/option order) for each split,
written to `preds/sweep-v6-e5-small-e3-ens.<split>.jsonl`, then scored with `vox.evaluate`.
**I did the probability average, not weight soup** (soup needs the checkpoints on GPU; the brief's
offline option was the prob-average). Results in section 4.

### E4 — `sweeps/scratch/v6s3_queue.sh` (prep only, NOT run)
Retrains seed 11 as `v6-e5-small-e3-s11b` with `--seed 11 --save-every-epoch --tie later`, then
predicts + evaluates the final checkpoint (`v6-e5-small-e3-s11b`) and each per-epoch checkpoint
(`-s11b-e1`/`-e2`/`-e3`) on the 3 v6 splits, recording a ledger row per name.

## 2. E1 unit test results

`python -m unittest tests.test_selection -v` (pinned env): **7/7 pass.**

## 3. E2 cluster numbers (v6 s7 + s11, from `sweeps/scratch/v6_clusters.txt`)

| split | seed 7 | seed 11 | seed mean (range) |
|---|---|---|---|
| test_iid | 0.9985 | 0.9990 | 0.9988 (0.9985-0.9990) |
| test_unseen_phrasing | 0.9960 | 0.9860 | 0.9910 (0.9860-0.9960) |
| test_unseen_apps | 0.9940 | 0.9895 | 0.9918 (0.9895-0.9940) |

`test_unseen_phrasing` — 29 clusters (24 held-out action wordings + 5 held-out phrases), pass = acc >= 0.95:
- seed 7: **28/29** pass; seed 11: **26/29** pass.
- The one wording the advisor flagged is the whole gap: `swipe_up "push the screen upward"` is **33/33
  (seed 7) vs 12/33 (seed 11)**. The other 23 action wordings pass on both seeds
  (seed 7's only miss is `swipe_right "slide the screen to the right"` at 40/41).
- Phrases: `"previous"` fails both (29/34 vs 28/34); `"turn it down"` passes seed 7 (18/18) and fails
  seed 11 (17/18); the other three pass both.

`test_unseen_apps` — 12 (app, screen kind) clusters:
- seed 7: **12/12**; seed 11: **11/12** (only `com.google.android.apps.docs / document` at 203/214).
- The never-seen `other`/`dialog` kinds (Duolingo) stay >= 0.98 on seed 11 and 1.00 on seed 7, matching
  the advisor's "screen-kind coverage gap, not the seed".

## 4. E3 ensemble numbers (prob-average, from `sweeps/scratch/v6_ens.txt`)

| split | seed 7 | seed 11 | ensemble |
|---|---|---|---|
| test_iid | 0.9985 | 0.9990 | **1.0000** |
| test_unseen_phrasing | 0.9960 | 0.9860 | **0.9975** |
| test_unseen_apps | 0.9940 | 0.9895 | **0.9945** |

The prob-average is >= max(seed) on all three splits. Ensemble NLL/ECE: iid 0.0014/0.0012,
unseen_phrasing 0.0129/0.0073, unseen_apps 0.0192/0.0041. (Prob-averaging softens the distribution, so
unseen_phrasing NLL is slightly above the advisor's 0.011 soup target even though accuracy improves;
weight soup, which I did not run, is the option that could also lower NLL.)

## 5. Files written/changed (absolute paths)

- `/home/khoa/VOX/finetune/students/jevlike/train.py` (edited)
- `/home/khoa/VOX/finetune/students/jevlike/selection.py` (new)
- `/home/khoa/VOX/finetune/tests/test_selection.py` (new)
- `/home/khoa/VOX/finetune/sweeps/cluster_eval.py` (new)
- `/home/khoa/VOX/finetune/sweeps/scratch/v6_clusters.txt` (new)
- `/home/khoa/VOX/finetune/sweeps/scratch/v6_ens.py` (new)
- `/home/khoa/VOX/finetune/sweeps/scratch/v6_ens.txt` (new)
- `/home/khoa/VOX/finetune/preds/sweep-v6-e5-small-e3-ens.test_iid.jsonl` (new)
- `/home/khoa/VOX/finetune/preds/sweep-v6-e5-small-e3-ens.test_unseen_phrasing.jsonl` (new)
- `/home/khoa/VOX/finetune/preds/sweep-v6-e5-small-e3-ens.test_unseen_apps.jsonl` (new)
- `/home/khoa/VOX/finetune/sweeps/scratch/v6s3_queue.sh` (new)
- `/home/khoa/VOX/finetune/sweeps/scratch/v6s3-REPORT.md` (this file)

## 6. Not done / remaining

- E4 was **written, not run** (coordinator runs the GPU training). `v6s3_queue.sh` was not syntax-checked
  via a shell (no training is being launched here).
- `train.py` was validated by `--help` (full import, prints the two new flags) and the selection unit
  tests; the `--save-every-epoch` checkpoint-writing path was not exercised end-to-end (that needs a
  real training run, which is out of scope for this worker).
