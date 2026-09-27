# Training

This page covers how the decision models are trained and measured: the datasets, the splits, the locked test, the
cross-fit protocol, the results so far and the ship gates. The code is in `finetune/`. The model overview is in
[architecture.md](architecture.md#models-and-how-they-are-served), and the research background is in
[decision-models.md](decision-models.md).

## The models

| Model | Job | Status |
|---|---|---|
| Teachers: JevK5, Decider 4B | Label synthetic rows on the PC's AMD GPU (`finetune/teachers`) | Scored 0.69–0.79. Not good enough to replace the code-generated labels, but useful for finding generator bugs ([A02](decisions.md#a02)). |
| jevlike | Gesture/action decider student (e5 encoder, `students/jevlike`) | Served on the PC by `servers/systemone.py`. Strong on synthetic data, weak on real screens. |
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

The **label pass 2** was a blind second labelling of 4,500 rows. It agreed 97% with the first pass, and 135 phrases
were adjudicated.

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

**Status (05:30 on 09-27).** Step 2 of the Verdict plan (v1f cross-fit) is running under fork a19c44b. **No results
yet.**

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

## Ship gates

These are the conditions for putting a Verdict model on the phone:
- none recall ≥ 0.8;
- wrong-tap upper bound ≤ 5% at the chosen operating point;
- v2 must beat v1 on exact captures;
- the app's new option text ships only with a model trained on it ([D116](decisions.md#d116)).

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
