# v6 seed comparison: advice (seed 7 vs seed 11)

Advisor read: `v6s2-REPORT.md`, `v6s2_compare.txt`, `v6-brief.md`, `data/README.md`, `sweeps/runs.jsonl`,
`sweeps/logs/v6-e5-small-e3*.train.log`, `students/jevlike/train.py`, `vox/generate.py`, `vox/wordings.py`,
`vox/schema.py`, `wordings_llm/bank.json`, `preds/sweep-v6-e5-small-e3*.jsonl`, `data/v6/*.jsonl`,
`students/jevlike/seedpool.py`. No training run; all numbers below were recomputed from those files.

## TL;DR

The "1.0 pt seed swing" on test_unseen_phrasing is **one held-out wording**: `swipe_up` = "push the screen
upward". Seed 7 gets 33/33 of those rows, seed 11 gets 12/33 (answers `volume_up` at 0.87-1.00). 21 of seed 11's
28 errors are that wording; all 23 other held-out action wordings are 100% on both seeds. The remaining 7 errors
are the ambiguous held-out phrase "previous" (-> `back`), which both seeds fail at the same rate (29/34 vs 28/34).
The McNemar p = 0.0005 treats 2000 rows as independent; the true units are ~50 held-out wordings/templates/phrases,
and at that level the result is "seed 11 failed 1 of 24 action wordings, seed 7 failed 0". That is seed noise on a
near-tie wording, not a worse model. Report v6 as the seed mean and switch decisions to 3 seeds + cluster-level
counts. The two concrete defects found are (a) checkpoint selection on a saturated in-distribution validation set
(seed 11's checkpoint is epoch 2, seed 7's is epoch 3, purely from the `>` tie rule), and (b) test_unseen_apps is
silently also a test of never-seen screen kinds (`other`, `dialog` exist only for held-out Duolingo).

## 1. Diagnosis

### 1a. unseen_phrasing: one wording, near-tie in the training bank

Per held-out action wording (rows whose gold action's held-out wording appears in the context):

| action | held-out wording | n | seed 7 | seed 11 |
|---|---|---|---|---|
| swipe_up | "push the screen upward" | 33 | 1.000 | **0.364** |
| swipe_right | "slide the screen to the right" | 41 | 0.976 | 1.000 |
| all 22 others | | 25-54 each | 1.000 | 1.000 |

Held-out phrases: "previous" 29/34 vs 28/34, "turn it down" 18/18 vs 17/18, the other three 100%/100%.

Seed 11 error table (28): 21 x `swipe_up -> volume_up` on "push the screen upward" (spread over app_rule 6,
phrase_rule 5, sequence 5, global_rule 5: exactly the four kinds the report flagged, because those are the kinds
that carry a rule with an action wording), 6 x "previous" -> `back`, 1 x "turn it down" -> `scroll_down`.
Seed 7 error table (8): 3 x "previous" -> `back`, 3 x "resume" confusions with `none`, 1 slide-right, 1 previous.

Why `volume_up`: the training bank for `volume_up` contains "push the sound up", "push the volume higher",
"push ... up"; `swipe_up` training has "push the page up with a swipe", "pull the screen upward" (train counts:
"push the screen" 0, "screen upward" 107, "push the page up" 55). "push the screen upward" therefore sits between
two training clusters and which side wins is initialisation luck. Nothing in the data disambiguates it; the
held-out wording is a genuinely hard, single item.

Consequence for the statistics: `test_unseen_phrasing` has 2000 rows but only ~24 action wordings + 14 gesture
wordings + 5 held-out templates + 5 phrases as independent units. One flipped wording = 30-50 rows = 1.5-2.5 pt.
The noise floor of this split for a single seed is therefore ~1-2 pt, and row-level McNemar will call any single
flipped wording "significant". Use the wording as the unit (see section 2).

### 1b. NLL / ECE / false_trigger differences are the same rows

Seed 11's NLL 0.045 and ECE 0.012 on unseen_phrasing come from the ~21 confident wrong `volume_up` answers; nothing
else moved. Seed 11's `false_trigger = missed = 0` vs seed 7's 0.002-0.004 is 2-4 rows per split ("resume" while
paused -> `none`, "resume" while playing -> `play_pause`); that is within noise, not a property of the seed.

### 1c. Checkpoint selection is arbitrary (confound, not proven cause)

Train logs: seed 7 val_acc 0.977 / 0.995 / 0.997 -> epoch 3 saved. Seed 11 val_acc 0.973 / 1.0 / 1.0 -> **epoch 2**
saved, because `better["acc"]` is `>` and ties keep the earliest epoch. Validation is `validation.jsonl[:1000]`,
generated with `rich=True` on TRAIN_APPS, i.e. the training distribution; it saturates at epoch 2 in most runs
(v3: 1.0/1.0, v5-regen: 1.0/1.0, v6-s11: 1.0/1.0). So selection systematically prefers the earliest saturated
epoch, which under OneCycle (3 epochs, pct_start 0.06) is a checkpoint with the LR still at roughly half of max
rather than the annealed one. Val NLL cannot break the tie either (0.0001 vs 0.0003 is float noise).
Caveat: the regenerated v5 run also selected epoch 2 and scored 0.996 on unseen_phrasing, so epoch 2 alone does
not cause the failure; it is a confound that a 16-minute retrain would settle (or nothing, once per-epoch
checkpoints are kept; see E1). Only the best checkpoint is saved today, so seed 11's epoch-3 state is gone.

### 1d. unseen_apps screen_phrase (0.93 / 0.89): a screen-kind coverage gap, not the seed

Training screen kinds (all 40k rows): scrolling list, video feed, none, video player, camera viewfinder, text
entry, photo viewer, web page, map, document. **No row has `screen: other` or `screen: dialog`**: in `APP_SCREENS`
those two kinds exist only for `com.duolingo`, a held-out app. `document` appears in 117 screen_phrase training
rows (Kindle only), yet held-out Google Docs is 50% `document`.

test_unseen_apps screen_phrase by (screen kind, base) -> n / seed 7 right / seed 11 right:
`document,next_item` 6/1/0; `document,previous_item` 4/4/0; `other,next_item` 5/5/2; `dialog,next_item` 5/5/3;
`other,previous_item` 8/8/7; `dialog,previous_item` 6/6/5; `text entry,next_item` 10/7/10; everything else equal.
So both seeds are weak on `document` (next -> swipe_left seen 117 times), and seed 11 additionally wobbles on the
two never-seen kinds where the correct rule ("unknown screen: keep next_item") has zero training support. The
direction confusions in the report (next_item -> swipe_up, swipe_right -> previous_item) are exactly the
SCREEN_NEXT/SCREEN_PREV tie-breaker firing or not firing on screens the model has no evidence about.

## 2. What to report, and a seed protocol

**Reported v6 number**: the seed mean with the per-seed range, and the cluster-level pass count next to it.

| split | seed 7 | seed 11 | report as |
|---|---|---|---|
| test_iid | 0.9985 | 0.9990 | 0.999 (2 seeds, 0.9985-0.9990) |
| test_unseen_phrasing | 0.9960 | 0.9860 | 0.991 (2 seeds, 0.986-0.996); 23/24 held-out action wordings pass on both seeds, 1 fails on one seed |
| test_unseen_apps | 0.9940 | 0.9895 | 0.992 (2 seeds, 0.990-0.994); screen_phrase 0.91, weak on document/other/dialog screens |

Do not report seed 7 alone as "the v6 number"; it is the better of two draws.

**Protocol going forward** (this is what jl8-jl11 already did on the real-target track with seeds 7/8/9 and
`seedpool.py`; the synthetic track never adopted it):
1. Every recipe = 3 seeds (7, 11, 13). 3 x 16.5 min = 50 min per recipe today; ~30-35 min with `--fast-options`.
2. Headline = mean over seeds; also show min. A recipe change is accepted only if the mean improves AND at least 2
   of 3 seeds improve on the paired per-seed comparison.
3. Significance at the cluster level: for unseen_phrasing pair rows by held-out wording/template/phrase (the
   `ACTION_WORDS[*][1]`, `GESTURE_WORDS[*][1]`, `*_TEMPLATES[1]`, `HELDOUT_PHRASES` strings found in the context);
   for unseen_apps pair by (app, screen kind). Count clusters that flipped, not rows. One flipped cluster is noise.
   A cluster bootstrap like `seedpool.py`'s screen-cluster bootstrap is the ready-made pattern.
4. Decision threshold on unseen_phrasing with the current test: differences under ~1 pt from a single seed mean
   nothing; with 3 seeds, treat < 0.5 pt mean difference as a tie.
5. Record `--seed` in every ledger command (seed 7 runs omit it today) and store `selected_epoch` for `acc` too.

## 3. Next experiments, ranked by expected value per GPU-hour

**E1. Keep every epoch's checkpoint and fix the tie rule (0 GPU-min, code only).** train.py saves only the best
checkpoint, so the seed-11 epoch-3 model is unrecoverable and any epoch question costs a 16.5-min retrain.
Change: write `runs/<name>.epN.pt` each epoch (134 MB each, 273 GB free) plus the selected one as today; on
`--select acc` break ties toward the LATER epoch (or add `--select last`). Success: any epoch comparison costs one
80 s predict pass; selection never prefers a mid-schedule checkpoint by accident.

**E2. Cluster-level evaluation report (0 GPU-min, ~4 min CPU).** Add `--by-cluster` to `vox/evaluate.py` (or a
`sweeps/cluster_report.py`) that prints the per-held-out-wording / per-phrase / per-(app, screen kind) pass table
for every prediction file, and a cluster-paired comparison for two files. Success: the v6s2 verdict is restated as
"1/24 wordings on one seed"; future seed comparisons are judged on clusters. This is the highest-leverage change
because it stops row-level McNemar from driving decisions.

**E3. Seed-averaged model soup of s7 + s11 (about 2 GPU-min).** Both checkpoints start from the same pretrained
e5-small-v2 and the same head init seed-independent structure, so averaging the two `state_dict`s is a valid
weight soup; also average the two prediction files' probabilities offline (0 GPU). Hypothesis: the near-tie
wording resolves to `swipe_up` (seed 7 is at 1.00 on it), giving >= 0.996 on unseen_phrasing and >= 0.994 on
unseen_apps at no inference cost (soup) or 2x cost (prob ensemble). Success: soup >= max(seed) on all three splits
and NLL <= 0.011. If the soup works it is the cheapest serving improvement available; if it does not, the two
models disagree on a feature, which is itself informative.

**E4. Retrain seed 11 with E1 in place, compare epoch 2 vs 3 (1 train, 16.5 min).** Hypothesis: the annealed epoch-3
checkpoint recovers "push the screen upward" (>= 30/33). If epoch 3 == epoch 2 on that wording, the failure is
initialisation luck on a near-tie and only data/selection changes (E5, E6) can fix it. Either outcome removes the
confound from section 1c. Do this before any other v6 retrain.

**E5. Held-out-wording validation for selection (generator change + 3 trains, ~50 min).** Today's val is the train
distribution and saturates at epoch 2, so `--select acc|nll|nll_t` all pick arbitrarily. Change: in
`vox/generate.py`, reserve a slice of the LLM bank per action (e.g. 4 of the ~32 bank wordings per action, 1 bank
template per family, 2 gesture wordings) as `validation_unseen.jsonl` wordings, excluded from train and disjoint
from the test held-out lists (`check_disjoint` already exists; extend it). Train with `--validation
data/v7/validation_unseen.jsonl --select nll` (NLL is the right criterion on an unsaturated set; acc ties at 1.0
are the whole problem). Success: selected epoch differs between epochs by > 0.1 pt on the new val, and the
selected epoch's test_unseen_phrasing is >= the mean of the other epochs across 3 seeds. Cost is mostly one-time
generator work; it also produces the first validation signal that resembles the tests.

**E6. v7 data: cover the screen kinds the phone will actually send (generator change + 3 trains, ~50 min).**
`other` and `dialog` are real screen kinds the app emits for anything it cannot classify, and they are currently
test-only. Change `APP_SCREENS` so at least three training apps carry `other` and two carry `dialog` (e.g. Chrome
+ WhatsApp + Maps: `other`; WhatsApp + Spotify: `dialog`), and add `document` to one more training app so the
document tie-breaker has > 117 rows. Keep Duolingo/Docs held out. Hypothesis: unseen_apps screen_phrase goes from
0.89-0.93 to >= 0.97 on all 3 seeds with no change on the other splits. This is a coverage fix, not a leak: the
held-out apps stay held out; only the screen vocabulary stops being confounded with them. Do E5 and E6 in the same
data version (v7) to pay the 3-seed cost once.

**Not recommended now**: more epochs (v5-e5-small-e6 scored 0.9865 on unseen_phrasing vs 0.996 for e3 at 2x the
cost), a bigger encoder (v5-e5-base-e3: 0.987-0.9995, 4x cost, unstable), and label smoothing (the accuracy
problem is a near-tie between two actions, which smoothing does not move; it would only lower the NLL of the wrong
answers). Revisit smoothing only if calibration becomes the target.

## 4. Bugs, leaks and oddities

1. **Selection tie rule** (`train.py`, `better["acc"] = m > b`): on a saturated val the earliest saturated epoch
   wins, so the selected checkpoint is systematically the least-annealed one. Seed 11 = epoch 2, seed 7 = epoch 3;
   the two "identical-settings" runs are not identical checkpoints. Fix in E1.
2. **Only the best checkpoint is saved**; per-epoch states are discarded, so epoch questions need retrains. E1.
3. **Validation measures nothing the tests measure**: `validation.jsonl` is generated with `rich=True` on
   TRAIN_APPS (training wordings, training apps), and `--val-limit 1000` uses its first 1000 rows. It cannot
   see wording or app generalisation and hits 1.0 by epoch 2. E5.
4. **Screen-kind leak in reverse in test_unseen_apps**: `other` and `dialog` occur in 0 training rows and only in
   the held-out app Duolingo, so that split is partly a test of unseen screen kinds. Any future "unseen_apps
   improvement" must be checked per screen kind. E6.
5. **Ambiguous held-out phrase**: `HELDOUT_PHRASES["previous"] = previous_item`, but `PHRASES["back"]` contains
   "previous screen". Both seeds fail ~15% of "previous" rows toward `back`. Either drop "previous" from the
   held-out phrases or accept a permanent ~0.3 pt floor on that split; do not read those rows as model regressions.
6. **Row-level McNemar on clustered rows** (`v6s2_compare.py`): overstates significance by ~30x on this split.
   Use the cluster tests in section 2.
7. Ledger: seed 7 runs do not carry `--seed` in `command` (default), so the seed must be inferred; `selected` is
   null for `--select acc` runs, so the selected epoch is only in the train log. Two ledger rows are named
   `v5-e5-small-e3` (stale vs regenerated). Cosmetic, but seed-pooled tooling will trip on it.
8. Not a bug (checked): `torch.manual_seed` covers DataLoader shuffling and dropout; `random` is not used in
   training; `generate.py` sorts option sets before shuffling so PYTHONHASHSEED cannot leak; `check_disjoint`
   confirms "push the screen upward" and "raise the sound level" are absent from train (0 occurrences).

## 5. Faster iterations

- **`--fast-options`** is validated (jl9 cache/bf16 checks) and used by every jl8-jl11 run but not by the v6 runs.
  ~30% of rows carry all 25 options and the rest 8-14, so a batch of 32 encodes ~450 option strings where at most
  ~26 are distinct. Expect a 1.3-2x wall-time cut on the option side; measure once (one run, compare
  `rows_per_s_epoch` to 122). Same function up to float noise, so results stay comparable.
- With per-epoch checkpoints (E1) every epoch question becomes an 80 s predict instead of a 16.5 min train.
- Seed sweeps: run the three seeds back to back in one queue script and pool with the cluster report (E2); do not
  run two trainings concurrently on this box (GPU-bound, no throughput gain).
- 2-epoch OneCycle (2500 steps, ~11 min) is plausible since iid saturates at epoch 2, but only test it after E5
  exists, otherwise there is no way to select between the two epochs anyway. 3 seeds, success = mean
  unseen_phrasing within 0.3 pt of the 3-epoch mean.
- Predict at batch size 1 (79 s for 6000 rows) is fine for the ledger's latency column; for seed-sweep scoring use
  `--cache-options` to cut it further if it ever matters.
