# tools: keep the app in sync with finetune and the extractor

The app must produce exactly what the model is trained on. These scripts read `finetune/` and `extractor/` (read-only;
they never write bytecode there) and generate Kotlin sources, assets and test fixtures under `android/`.

| File | What it does |
|---|---|
| `gen_vocab.py` | Writes two files in `app/src/main/java/ai/vox/companion/`, each with a source digest:<br>• `Vocab.kt` from `finetune/vox/schema.py` and `generate.py`: sound vocabulary, buckets, actions and option texts, default bindings, apps, phrases, screen vocabulary, POLICY, rule templates;<br>• `TargetVocab.kt` from `finetune/data/targets-v1/policy.txt` and `vox/targets.py`: the target POLICY, `NONE_OPTION`, positions and roles.<br>`--check` exits 1 if either file is stale. |
| `state_parity.py` | Writes `app/src/test/resources/state_parity.json`:<br>• 300 `generate.py` scenes with their exact state text;<br>• 380 labelled rows;<br>• 120 target rows from the targets-v1 test splits.<br>The JVM tests use it to prove that `Scene.text()` and the target option format are byte-identical to the training data. |
| `fp_floors.py` | Writes `app/src/main/assets/fp_floors.json`, the **provisional** per-feature std floors for `fp1` (personalization). Each floor is 0.25 × that feature's winsorised population std over every clip in `extractor/results/real_features_frozen_clips.jsonl` (160,270 real clips). The fp1 vector is rebuilt from the clips' raw fields the way `extractor/vox_extract/fingerprint.py` builds it. It is a stand-in until the extractor publishes per-feature scales: then replace the JSON entry and mark it `"provisional": false`. |
| `build_host_jni.sh` | Builds `app/build/host-jni/libvx_jni.so` for this machine (g++ + the JDK's jni.h) from the same sources as the app's NDK build (`app/src/main/cpp/vx_jni.cpp` + `firmware/extract/src`, `-O2 -ffp-contract=off`). The Gradle task `:app:hostJni` runs it before the JVM tests; `PhoneMicTest` loads it for JNI parity. |
| `mic_parity.py` | Device parity and speed of the phone-mic extractor: sends every `extractor/vectors` case to the app's `mic_feed` op and compares the events as `firmware/tools/check_extract.py` does; `--bench N` reports the device's per-hop time and real-time factor. Run with `../extractor/run python` (numpy). |
| `mic_live.py` | Live phone-mic measurement on a device: switches `sound_source` to `phone`/`usb` for `--seconds`, polls `mic_status` (hop p50/p99, audio-thread CPU, app CPU from `top`, level, floor, latency from the end of a sound to the service), then restores the settings. Needs the mic permission granted by the user. It also collects every `mic_sound`: labels, touch drops, media-gated and hiss-gated sounds, would-act per minute as the app counts it (`extractor/vox_extract/sequencer_sim.py`: the act-at-once Sequencer and the app's bindings; the old `policy.group` count is kept as `would_act_policy_group`), per-label gate numbers (`centroid_hz`, `peak_centroid_hz`, `hf_ratio`, `lf_ratio`, `zcr`, `snr_db`, p10/p50/p90) and the mean 8-band input level (`mic_status.bands`), split by media playing or not. `--dry-run` (nothing acted on), `--preset`/`--effects` (the echo A/B), `--media-gate`, `--hiss-max-centroid` (`hiss_media_max_centroid_hz`, 0 = off), `--no-touch-guard`. Run with `../extractor/run python` for the policy mirror. |
| `phone_media_eval.py` | Offline phone-mic-over-media eval (Python reference extractor): the user's recorded gestures, MIR-QBSH hums and synthetic pops/click-pops/hisses/hums/whistles mixed into MUSAN speech/music at clean/10/5/0/-5 dB, plus 60 s media-alone runs. `run --out R.jsonl [--cfg] [--kinds] [--limit]` then `score R.jsonl [...] [--merge] [--gates none app ...]`: survival (conditional on the clean clip acting), wrong actions, and false acts per minute of media alone. Gate `app` mirrors `PhoneGate.kt`. Records keep event numbers, never audio. From `extractor/`: `./run python ../android/tools/phone_media_eval.py ...`. |

## Commands

Run these from `android/`. The host has no python3 of its own; use the dev shell.

```sh
./dev python3 tools/gen_vocab.py            # regenerate Vocab.kt and TargetVocab.kt after finetune/vox changes
./dev python3 tools/gen_vocab.py --check    # verify they are up to date
./dev python3 tools/state_parity.py         # regenerate the parity fixture
./dev gradle :app:testDebugUnitTest         # then run the tests that use it
./dev python3 tools/fp_floors.py            # regenerate the provisional fp1 floors (about 10 s; --print to only show them)
```
