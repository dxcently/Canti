# eval_real: the extractor on real audio

This folder scores the extractor on six public datasets and on the user's own live recordings. **CPU only.**
- Workers: at most 8 (`--workers`, or `VOX_EVAL_WORKERS`), each single-threaded.
- Audio: read from `/home/khoa/VOX/datasets/`, never copied here. The sources, licences and fetch commands are in `datasets/SOURCES.md`.
- Per-clip run records: `datasets/_eval_cache/runs/<tag>/<dataset>_<split>.jsonl`, outside the repo.
- Reports: `../results/real_*.md`.

**Conventions**, from `common.py`:
- **Split by speaker:** `sha1("<dataset>:<speaker>") % 100 < 30` puts a speaker in *tune*, else in *test*.
- **Thresholds:** fitted on tune only. Headline numbers are test.
- **Clips:** padded with 1.0 s of their own background before the sound and 0.6 s after.
- **Noise:** MUSAN noise from the same split is mixed in at 20, 10 and 5 dB. SNR is measured on the active span, the same way synth.py does.
- **Sample rates:** every dataset is ≤ 44.1 kHz and goes through `resample.to_16k` (scipy `resample_poly`). Only the live recordings use the 48 kHz `Decimator3` path.
- **`VOX_CODE=frozen`:** imports the pre-fix snapshot in `datasets/_eval_cache/frozen_src/` instead of `vox_extract/`.

## Run it

```bash
cd /home/khoa/VOX/extractor
VOX_CODE=frozen ./run python eval_real/run_all.py run --tag frozen                    # the headline: code as shipped before real audio
./run python eval_real/run_all.py run --tag fixed                                     # current code, default Config
./run python eval_real/run_all.py run --tag tuned --cfg results/real_tuned_config.json --datasets nonverbal qbsh_contour musan mlend nonspeech7k esc50
./run python eval_real/run_all.py report --tags frozen fixed tuned                    # results/real_<dataset>.md, real_ood_lines.md
./run python eval_real/compare.py --split test --tags frozen fixed tuned --out results/real_summary_table.md
./run python eval_real/live_replay.py --tag fixed                                     # before / after on the live recordings
./run python eval_real/live_replay.py --tag tuned --config results/real_tuned_config.json --out results/real_live_replay_tuned.json
./run python eval_real/features.py export --tag fixed && ./run python eval_real/features.py live --tag fixed
./run python eval_real/fp_scales.py --tag fixed                                       # results/fp1_scales.json (app floor table shape)
./run python eval_real/enroll_sim.py --tag fixed                                      # fp1 + Matcher feasibility
./run python eval_real/cues.py --tag fixed                                            # cross-speaker cues, brightness rule, pitch gate
```

A full run of all datasets and both splits takes about 15 minutes on 8 workers.

| File | What it does |
|---|---|
| `common.py` | Shared helpers: dataset root, the speaker split, `pmap` (a process pool of ≤ 8 single-threaded workers), padding and noise mixing, and `analyse()`. `analyse()` groups events like the phone, applies the policy gate, and records which groups would fire, the OOD lines, and offline brightness / MFCC features. It also provides `slim()`, the per-event record, and the markdown helpers. |
| `nonverbal.py` | Deeply Nonverbal (OpenSLR 99). Positives: tongue click → click, lip pop → pop, scored clean and at 20 / 10 / 5 dB. Lip smack is borderline. Negatives come from the user's list, and the other classes are reported separately. Outputs: detection per clip, majority label, confusion, and FA/min. |
| `qbsh.py` | MIR-QBSH. (a) The pitch tracker vs the manual `.pv` pitch: GPE, cents error, voicing, and a lag check. (b) Contour clips of 150 ms – 1.5 s, cut from the manual pitch by the rules in its docstring, scored against the EXCURSION buckets. Sung melodies are not gestures, and the report says so. |
| `musan.py` | MUSAN speech, music and noise as negatives, as one ≤ 60 s excerpt per file. Gives FA/min, and the "sounds like" given to speech and music. Also provides the noise pool used by the other scripts. |
| `mlend.py` | MLEnd Hums & Whistles: is the source recognised ("hum" or "whistle" vs "talking" etc.), broken down by f0? Also the pitch agreement with Praat (parselmouth). |
| `nonspeech7k.py` | Nonspeech7k (breath, cough, crying, laugh, screaming, sneeze, yawn) as negatives: FA/min per class. |
| `esc50.py` | ESC-50: all 50 environmental classes as negatives, with cat as the class of interest, plus the MUSAN "Cat Meow 2". |
| `run_all.py` | The runner (`run --tag`, `--cfg`, `--datasets`, `--splits`, `--workers`, `--limit`) and the report writer (`report`). Report tags go in the order frozen, fixed, tuned. |
| `compare.py` | One table of headline metrics across tags, for tuning decisions and the summary. |
| `live_replay.py` | Before and after on `recordings/live-20260926-*`: the events saved at recording time vs the current code and config, with the user's by-ear notes. Writes `results/real_live_replay*.json`. |
| `features.py` | Per-event feature export: one row per event, with f0 stats, E1k, E3.5, HNR, log-mel, MFCC, every raw feature, `fp` and `pitch16`. It covers every run of a tag (`export`) plus the live recordings (`live`), and writes `results/real_features_<tag>_clips.jsonl`. That file is large, regenerable and gitignored. |
| `cues.py` | Offline analyses on the feature export: cross-speaker separability (AUC, per-speaker medians), the brightness "yelling" rule as a hypothesis with before/after numbers, the per-user pitch gate (evaluated, not built), and low-f0 "talking". Writes `results/real_cues*.md`. |
| `enroll_sim.py` | The personalization feasibility check. It simulates enrollment of 3 / 5 / 10 examples per class with the app's Matcher (`vox_extract.personal`, numpy-vectorised and checked against it). It covers dataset speakers and the user's live meows, yells, clicks and whistles, and reports accept rates and false accepts on other people's sounds. Writes `results/real_enroll_sim.md`. |
| `fp_scales.py` | Per-feature scales of `fp1` from the tune split: `within` (typical spread when the same person repeats the same sound) and `population` (robust spread across many speakers and sounds). Writes `results/fp1_scales.json` in the shape of the app's `android/app/src/main/assets/fp_floors.json` (`{"fp1": {"provisional", "source", "names", "floor", ...}}`), with `floor` = 0.25 x population (the app's rule; `within` as a floor raised false accepts, see `real_enroll_sim.md`), so the app can drop it in. |

`enroll_sim.py` runs 5 examples four ways: no floor, the `within` scale, the published floor (0.25 x population) from `results/fp1_scales.json`, and the app's shipped floor table (read only). The matcher rules follow the app as of 2026-09-26: leave-one-out within-class distance at every class size, and `std_j = max(popstd_j, floor_j)`, then 1 if below 1e-9.
