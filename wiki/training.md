# Training

This page covers how the decision models are trained and measured: the datasets, the splits, the locked test, the
cross-fit protocol, the results so far and the ship gates. The code is in `finetune/`. The model overview is in
[architecture.md](architecture.md#models-and-how-they-are-served), and the research background is in
[decision-models.md](decision-models.md).

## The models

| Model | Job | Status |
|---|---|---|
| Teachers: JevK5, Decider 4B | Label synthetic rows on the PC's AMD GPU (`finetune/teachers`) | Scored 0.69–0.79. Not good enough to replace the code-generated labels, but useful for finding generator bugs ([A02](decisions.md#a02)). |
| jevlike | Gesture/action decider student (e5-small-v2 encoder plus the jevlike `AttentionHead`, `students/jevlike`) | Served on the PC by `servers/systemone.py`; not on the phone. Retrained on real screens on 09-28 (jl7–jl9): the J5c recipe is now level with Verdict v1d on accuracy and latency ([below](#jevlike-jl7jl9)). Its intended job is Live mode ([round7-plan.md §6](round7-plan.md#6-live-mode-a-new-mode)). |
| Kev 0.8B | Generative student (`students/kev`) | Dropped ([D061](decisions.md#d061)). The code is still in the repo. |
| **Verdict** | Target picker: a spoken request plus the on-screen options gives one option or "none". A bi-encoder, multilingual-e5-small (118M) (`students/verdict`). | The chosen phone model ([D041](decisions.md#d041)). **It is not on the phone yet.** |
| Cloud | DeepSeek V4.1 Flash via Ollama | Handles hard cases from the phone. Used as a reference in evals. |

## Datasets and versions

### Synthetic (`finetune/data`, see `data/README.md`)

| Version | What changed |
|---|---|
| v0 | First generator. Rules quote the option text, so scores are inflated. |
| v1 | Paraphrased action wordings |
| v2 | Rich training wordings |
| v3 | 4 label bugs fixed (found by the teachers) |
| v4 | v3 plus the filtered LLM wording bank (`wordings_llm/`, written by DeepSeek executors) |
| v5 | The target task: new defaults (hiss = back, long flat hum = long press), a screen line, the `screen_phrase` kind, cursor actions removed. Regenerated 09-26 09:02, which made two earlier sweep rows stale (`sweeps/CHANGELOG.md`). |
| targets-v1 | Intent-cursor target picking. Superseded. |
| targets-v2 | Tree roles match the emulator harvest |
| targets-v3 | Exists on disk (synthetic geometry, `vox/targets_geo.py`), but is **not documented in `data/README.md`** |

Sweep results are in `sweeps/runs.jsonl`. Rows marked `stale` must not be compared.

### Real screens

| Set | Contents |
|---|---|
| real-targets-v1 | 557 emulator rows (09-26). Phrases by DeepSeek V4 Pro, labels by vision (ae6ba3a). |
| real-targets-v2 (root) | Emulator: 4,648 rows, 613 screens, 57 packages. Phrases by DeepSeek V4 Pro, labels by Opus (42 batches). Z Flip: 160 rows from 4 apps, phrased and labelled by Opus. Files: train 3,589 / val 407 / test_real 344 / test_real_old 308, plus Z Flip 140 train / 20 val and 40 X diagnostic rows. |
| real-targets-v2/b2 | Rebuilt with val by option set and 5 folds (train 3,540 / val 456) |
| real-targets-v2/b2v2, b3 | Later builds by the Verdict lead. b3 adds Z Flip rows from the gesture test, for v1f (details unverified). |
| real-targets-v2/b4 | Built 09-27 (MANIFEST `built_at` 06:04 local, about 10:04Z) with val by option set, the b2 folds and option format v1. Adds a `test_exact.jsonl` of 554 rows (61 screens, 3 apps). Train 3,852 rows / 504 screens / 55 apps. |
| real-targets-v2/b4a | b4 plus the blind-pass adjudication (built 08:35 local, about 12:35Z). Train 3,851, val 473, test_real 344, test_real_old 308, test_exact 554. `b4a/zflip/` holds the Z Flip train and val rows used by jevlike (private, gitignored). Three Z Flip screens are excluded from every b4a file (checked by jl9). |

The **label pass 2** was a blind second labelling of 4,500 rows. It agreed 97% with the first pass, and 135 phrases
were adjudicated.

<a id="b4-and-b4a-builds"></a>**b4 and b4a builds (09-27).** Three Opus batches (042–044, 891 phrases, no drops) were
labelled for b4. A fresh blind pass by 5 labellers covered 889 b4 rows: 867 agreed with pass 1 (97.5 %), 1 was dropped.
One adjudicator settled the 22 disagreements (A 4, B 8, both acceptable 8, neither 0, dropped 2; "none" was the best
answer in 9 of the 20 kept). Z Flip adjudications now reach the build, checked by
`students/verdict/check_zflip_adjudication.py`. Cross-fit result files now carry the build name
(`sweeps/eval/cf.<build>.<recipes>.md`).

<a id="val-contamination"></a>**Val contamination (found 09-28 by jl7).** 434 of the 473 rows of b4a `val` (same
phrase, screen and context) were in the training data of `verdict-bi-real-v1d` and v1d-nd, which were trained on the
older top-level real-targets-v2 build with a different val split. On b4a val, v1d scores 0.960 against 0.817 on its own
val. So b4a val must not be used to select, teach or initialise from v1d. `dev_test`, `test_old` and `diag_x` have no
overlap and are the fair comparison ([A34](decisions.md#a34)).

### Splits (`finetune/data/real-targets-v2/SPLIT.md`)

- Split by **app**, never by screen.
- **Held-out test apps:**
  - X (Z Flip). Its test uses only the user's own phrases; the Opus-written X phrases are a diagnostic only.
  - Wikipedia, AntennaPod and Tasks (emulator).
- **Test extraction.**
  - `test_real` holds screens from the occlusion-aware build.
  - `test_real_old` holds screens captured before it.
  - Both are reported ([A07](decisions.md#a07)).
- **Z Flip social apps.** They were planned as held-in ([D100](decisions.md#d100)), but the harvest was dropped
  ([D106](decisions.md#d106)).
- **Renaming.** Since 09-27 these test sets are called **dev-test**, used for aggregate comparisons only
  ([A10](decisions.md#a10)).

## Locked test

The locked test was sealed by the Verdict lead before any of its data existed ([A10](decisions.md#a10)):
- **Apps.** 14 emulator apps never used before, listed in `vox/real_targets_v2.LOCKED_PKGS`.
- **Seal check.** The module asserts at import that the sha256 of the sorted package list matches the seal.
- **Separation.** Rows from these packages go only to `locked_test.jsonl`, and the build asserts that none leak into
  any other file.

**Amendment (09-27, user edit).** The permission system blocked the agent's edit twice, so the user made it by hand
([D120](decisions.md#d120)):
- Droid-ify was added as the 15th package.
- Open Food Facts stays in the seal but is unused, because it crashes on the emulator.
- The seal moved from `e257ad8e…` (14 packages) to `c95aa250dd3719c53fc9aea895abf8945116db1a44e24499f5d1bf8158ba0a7a`
  (15 packages).
- Training includes F-Droid, which shows the same catalogue as Droid-ify, so locked results are reported both with and
  without Droid-ify.

**Use.** Each run is scored on the locked test once, via `suite.py --final`, and logged to `sweeps/final_evals.jsonl`.
That file doesn't exist yet: **the locked test has not been used**.

## Cross-fit

This protocol replaced picking recipes on a small val set ([A11](decisions.md#a11)).

1. **Val by option set.** Within a package, screens whose option-label sets overlap with Jaccard ≥ 0.8 are linked. A
   linked group goes wholly to val or wholly to train.
2. **Leave-apps-out 5-fold cross-fit.** The unit is the app, and app families share a fold. The folds are in
   `b2/folds.json`. Every held-in row gets a prediction from a model that never saw its app
   (`students/verdict/crossfit.py`).
3. **Recipe selection** uses only those pooled out-of-app predictions (`cf_eval.py`):
   - metrics: NLL after temperature, none AUROC, target accuracy and novel-phrase accuracy;
   - CIs resample apps;
   - the noise floor is the spread across 3 seeds.
4. **The operating point** is fitted on the same predictions: temperature, a none bias, t_tap and t_none. The
   constraint is that the one-sided 95% Clopper-Pearson upper bound on wrong taps per tap is ≤ 5%.

**Results so far** (`finetune/sweeps/eval/cf.*.md`, 95 % app-cluster CIs; acc = overall accuracy):

| Build | Recipe | Seeds | Rows / apps | Acc | NLL | None AUROC | None recall | Operating point (T, none bias, t_tap, t_none) | Tap rate | Wrong / tap (CP95 bound) |
|---|---|---|---|---|---|---|---|---|---|---|
| b2 | ref | 3 | 4,156 / 55 | 0.772 | 0.742 | 0.909 | 0.583 | | | |
| b2 | lossacc | 3 | 4,156 / 55 | 0.776 | 0.735 | 0.912 | 0.582 | T 1.991 (rest in the file) | | |
| b2 | lossacc_drop15 | 1 | 4,141 / 55 | 0.775 | 0.713 | 0.923 | 0.603 | | | |
| b3 | v1f | 1 | 4,436 / 61 | 0.759 | 0.802 | 0.910 | 0.582 | | | |
| b4 | lossacc_drop15 | 3 | 4,751 / 63 | 0.759 | 0.808 | 0.921 | 0.620 | 1.985, +0.75, 0.82, 0.60 | 0.481 | 0.036 (0.050) |
| **b4a** | **lossacc_drop15** | 3 | 4,749 / 63 | **0.759** [0.735, 0.781] | 0.801 | 0.919 | 0.620 | 1.971, +0.50, 0.82, 0.55 | 0.488 | 0.036 (0.050) |
| b4a | jl8teach_lossacc_drop15_train (train rows only, the jevlike teacher) | 2 | 4,252 / 63 | 0.754 | 0.807 | 0.919 | 0.616 | 1.972, +0.50, 0.82, 0.55 | 0.484 | 0.038 (0.050) |

- Recipe names: `lossacc` trains with `--loss acceptable` and `--lowconf-weight 0.5`;
  `drop15` uses a pool without 15 rows whose target was hidden (`pool_nohidden`). Source: each recipe's `recipe.json`
  under `<build>/zflip/crossfit/`.
- On b2, `lossacc_drop15` was the only recipe with a significant NLL gain over `ref`; `swapneg` raised none recall (0.679)
  but lowered accuracy. b4 kept `lossacc_drop15` ([A29](decisions.md#a29)).
- At the b4a operating point, 42 % of requests defer (ask) and 54 % resolve correctly. Target accuracy is 0.780.
- The b4a cross-fit was interrupted by the 09-27 shutdown and finished by jl8 (a9c6c9d) on 09-28, from a copy of the
  queue without `pgrep -f` (`sweeps/jl8_cf_queue8.sh`).
- The b2 and b3 rows have fewer apps, so they are not directly comparable with b4/b4a.

## Recipes and results so far

**Verdict on real screens, v1a–v1e** (`finetune/reports/verdict_real.md`):
- All runs train for 3 epochs. The learning rate is 3e-5 for v1a–c and 5e-5 for v1d and v1e, so v1a → v1d changes both
  the data and the learning rate.
- **Recommended: `verdict-bi-real-v1d`**, with frozen embeddings and no none bias. It was chosen on val before the test
  was seen.

| Set | Accuracy | None recall | Other |
|---|---|---|---|
| Val | 0.817 | 0.803 | |
| Old-extraction test (308 rows) | 0.838 | 0.818 | |
| New-extraction test (344 rows) | 0.738 | 0.529 | false-none 0.041, ECE 0.094 |
| targets-v2 unseen phrasing | 0.675 (was 0.545) | | |

- **Model size.** v1d int8 ONNX is 118 MB (0.745 on 200 test rows; p50 2.1 ms on the PC with cached option embeddings;
  not phone numbers). `v1d-pruned` cuts the vocabulary from 250k to 60k, making the int8 file 45.3 MB. `v1d-nd` is a
  no-dropout variant.
- **Audits** (09-27; a79f29c, a8eedf7, adee2d5):
  - Filler words cut none recall from 0.80 to 0.25; the app's filler normaliser restores it.
  - Most position errors fall inside the right 3×3 cell.
  - The differences between v1a and v1e are within noise (screen-bootstrap CIs).
  - Missed nones are mostly hidden elements that Canti still listed. Canti now excludes them (a74ff1f).
- **Cloud vs v1d on dev-test.** 0.852 vs 0.738, a difference of +0.113 [+0.058, +0.169]. The cloud's none recall is
  lower: 0.431 vs 0.529.

**Earlier comparisons** (`finetune/reports/ollama_vs_students.md`, 09-26):

| Set | Cloud | jevlike | Verdict (targets-v2 run) |
|---|---|---|---|
| targets-v2 unseen phrasing | 0.891 | 0.592 | 0.648 |
| real-targets-v1 emulator (gold) | 0.903 | 0.447 | 0.646 |
| v5 phrases | 0.800 | 0.978 | 0.911 |

Cloud latency from the PC: p50 715 ms, p95 1,085 ms over all 1,551 calls. The cloud's weak spot is "none" (recall about
0.71), so its taps need a confirm.

## jevlike (jl7–jl9)

<a id="jevlike-jl7jl9"></a>Three iterations on 09-28, each by a separate training lead (a6bf6ff, a9c6c9d, ab34f84), on the
b4a build and scored by `students/jevlike/suite_jl.py` against Verdict v1d. The user's standing rule: every result ends
with a list of ways to make iterations and training better ([D180](decisions.md#d180)). Details and flags:
`finetune/students/jevlike/README.md`; rows `jl7-*`, `jl8-*`, `jl9-*` in `sweeps/runs.jsonl`.

| Recipe | What it is | dev_test acc | test_old acc | test_old none recall | test_old NLL |
|---|---|---|---|---|---|
| J0 | the existing jevlike checkpoint, no training | 0.462 | 0.506 | 0.879 | 5.62 |
| J1 | e5-small-v2 + targets-v2 + real Z Flip rows (the mix) | 0.733 | 0.808 | 0.879 | 0.90 |
| J2 | J1 but initialised from Verdict's encoder | 0.677 | 0.789 | 0.727 | 1.81 |
| J3 | J2 plus Verdict as KL teacher (in-sample) | 0.709 | 0.792 | 0.818 | 0.74 |
| C (jl8) | J1 with prefixes and frozen embeddings, 2 epochs, 3 seeds | 0.729 | 0.788 | 0.848 | 0.714 |
| J4 (jl8) | C plus KL (α 0.5) from the honest out-of-app Verdict teacher | 0.744 | 0.819 | 0.747 | 0.644 |
| J5a (jl9) | J4 with the teacher's none bias refit (+0.61 / +0.58) | 0.750 | 0.812 | 0.747 | 0.642 |
| J5b (jl9) | J4 with `--teacher-skip-none` (no KL on gold-none rows) | 0.745 | 0.816 | 0.848 | 0.651 |
| **J5c (jl9)** | J5b at 3 epochs | 0.748 | **0.833** | 0.808 | **0.617** |
| Verdict v1d | reference | 0.750 | 0.838 | 0.818 | 0.578 |

jl8 and jl9 rows are seed means (seeds 7, 8, 9); jl7 rows are one seed. dev_test n = 344, test_old n = 308.

What each iteration found:
- **jl7.** Real screens are the whole gain (+27 points on dev_test). Starting from Verdict's encoder made it worse; Verdict
  as an in-sample teacher mainly fixed calibration (wrong taps at 0.8 confidence 0.102 → 0.055). Found the
  [val contamination](#val-contamination). Training ran at 156 rows/s.
- **jl8.** Speed: 153 → 315 rows/s (the AOTriton flag plus `--fast-options`), 162 s per 2-epoch run. An honest teacher
  (`oof_teacher.py`, from a cross-fit on train rows only). J4 beat C on test_old (0.819 vs 0.788, p = 0.014; dev_test not
  significant) but lost 10 points of none recall (p = 0.013).
- **jl9.** Skipping the teacher on gold-none rows restored none recall (+0.10 on test_old, p < 0.001) with no loss of
  accuracy; J5c is the best jevlike so far. The option cache (option vectors do not depend on the context) cut batch-1
  latency from 756 to 322 ms on CPU and 7.8 to 3.9 ms on GPU, level with v1d (281–311 ms CPU). Verdict's `--fast-embed`
  port gave only 3–8 %. With an operating point fitted on val and frozen (`opgate.py`), J5c improved utility over J4 on
  test_old (+0.029, p = 0.002), but the observed wrong-tap rate on the held-out sets was 3.6–4.4 %, with CP95 bounds of
  8.6–21.7 %, so the 5 % bound is not shown there.
- **Next (jl10), awaiting the user ([D190](decisions.md#d190)).** Adopt J5c; build a partial-sentence set (a prefix that
  does not yet pin down the action is labelled "wait for more words") and baseline on it; export ONNX int8 in two graphs
  (option encoder and context plus head) for the phone.

## Ship gates

These are the conditions for putting a Verdict model on the phone:
- none recall ≥ 0.8;
- wrong-tap upper bound ≤ 5% at the chosen operating point;
- v2 must beat v1 on exact captures;
- the app's new option text ships only with a model trained on it ([D116](decisions.md#d116)).

**Status (09-28).** No model meets the none-recall gate: Verdict b4a cross-fit 0.620, v1d 0.614 on dev_test and 0.818
on test_old, J5c 0.629 and 0.808. The wrong-tap bound is met in the Verdict cross-fit (0.050) but not shown on the
held-out sets for jevlike. The locked test is still unused (`sweeps/final_evals.jsonl` does not exist).

There is also a plan for exact captures (`dev-test-exact`, `raw_train3`, `raw_locked3`) and for approximating the new
option text on about 720 older screens ([D119](decisions.md#d119)).

## Privacy boundary

- **Z Flip data** (screens, dumps, phrases, labels) goes only to Claude Opus agents on this machine
  ([D075](decisions.md#d075)). It is gitignored under `finetune/data/real-targets-v*/zflip/`.
- **DeepSeek** (Ollama cloud or executors) sees emulator screens only. The `phrases` stage asserts this in code.
- **The user's voice recordings** stay local and out of git (`extractor/recordings/`, [D035](decisions.md#d035)).
  Splitting used a local faster-whisper model.
- **The locked test's content** is never read for selection.
- **Eval evidence.** The Ollama eval read and sent nothing from `real-targets-v1/zflip/`.
- **jevlike training (09-28)** uses Z Flip rows (`b4a/zflip/`) but runs only on the local GPU; no row leaves the machine.
  The jl9 lead checked that three excluded Z Flip screens appear in no b4a file.
- **DeepSeek workers in worktrees** (09-28) are forbidden from reading any `zflip/` directory and from touching the phone
  ([process.md](process.md#eidolon-workers-in-worktrees)).
