# tools: keep the app in sync with finetune and the extractor

The app must produce exactly what the model is trained on. These scripts read `finetune/` and `extractor/` (read-only;
they never write bytecode there) and generate Kotlin sources, assets and test fixtures under `android/`.

| File | What it does |
|---|---|
| `gen_vocab.py` | Writes two files in `app/src/main/java/ai/vox/companion/`, each with a source digest:<br>• `Vocab.kt` from `finetune/vox/schema.py` and `generate.py`: sound vocabulary, buckets, actions and option texts, default bindings, apps, phrases, screen vocabulary, POLICY, rule templates;<br>• `TargetVocab.kt` from `finetune/data/targets-v1/policy.txt` and `vox/targets.py`: the target POLICY, `NONE_OPTION`, positions and roles.<br>`--check` exits 1 if either file is stale. |
| `state_parity.py` | Writes `app/src/test/resources/state_parity.json`:<br>• 300 `generate.py` scenes with their exact state text;<br>• 380 labelled rows;<br>• 120 target rows from the targets-v1 test splits.<br>The JVM tests use it to prove that `Scene.text()` and the target option format are byte-identical to the training data. |
| `fp_floors.py` | Writes `app/src/main/assets/fp_floors.json`, the **provisional** per-feature std floors for `fp1` (personalization). Each floor is 0.25 × that feature's winsorised population std over every clip in `extractor/results/real_features_frozen_clips.jsonl` (160,270 real clips). The fp1 vector is rebuilt from the clips' raw fields the way `extractor/vox_extract/fingerprint.py` builds it. It is a stand-in until the extractor publishes per-feature scales: then replace the JSON entry and mark it `"provisional": false`. |

## Commands

Run these from `android/`. The host has no python3 of its own; use the dev shell.

```sh
./dev python3 tools/gen_vocab.py            # regenerate Vocab.kt and TargetVocab.kt after finetune/vox changes
./dev python3 tools/gen_vocab.py --check    # verify they are up to date
./dev python3 tools/state_parity.py         # regenerate the parity fixture
./dev gradle :app:testDebugUnitTest         # then run the tests that use it
./dev python3 tools/fp_floors.py            # regenerate the provisional fp1 floors (about 10 s; --print to only show them)
```
