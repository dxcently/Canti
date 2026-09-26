# results: what is current and what is superseded

All numbers here are regenerable from code in this folder's parent (commands in `../eval_real/README.md` and `../README.md`). Files ending in `_clips.jsonl` are large per-clip dumps and are gitignored.

## Current: real audio (2026-09-26)

Three configurations are compared throughout. **The headline is `frozen`.**

- **`frozen`**: the code and `Config()` as they were before any real audio was seen (snapshot in `datasets/_eval_cache/frozen_src/`).
- **`fixed`**: the current code with the default `Config()`: the tonal-pop fix, the start-up noise floor and the cap on floor rise while a sound is open. No threshold was changed.
- **`tuned`**: the current code with `real_tuned_config.json`, three thresholds picked on the TUNE split only. Not the default; see `real_summary_table.md` and the extractor README for why.

| file | what |
|---|---|
| `real_summary_table.md` | One table of headline metrics on the TEST split: frozen vs fixed vs tuned. |
| `real_nonverbal.md`, `real_qbsh_contour.md`, `real_musan.md`, `real_mlend.md`, `real_nonspeech7k.md`, `real_esc50.md` | Per-dataset reports, both splits, all three tags. `real_qbsh_contour.md` also has the pitch-tracker scores (GPE, cents). |
| `real_ood_lines.md` | Lines the extractor emits that generate.py never produces, per dataset and tag. |
| `real_summaries.json` | The numbers behind the tables above (small). |
| `real_tuned_config.json` | The tuned thresholds (partial Config JSON). |
| `real_live_replay.json`, `real_live_replay_tuned.json` | The user's live recordings: events at recording time vs the current code (fixed / tuned), with by-ear checks. |
| `real_fixed_synth16k.*`, `real_fixed_synth48k.*`, `real_tuned_synth16k.*`, `real_tuned_synth48k.*` | The synthetic sweep rerun with the current code (fixed / tuned), to check the real-audio fixes did not break the synthetic numbers. |
| `real_cues.md` (frozen), `real_cues_fixed.md` (current code) | Cross-speaker cue ranking, the brightness "yelling" rule as a hypothesis, the per-user pitch gate (evaluated, not built), low-f0 "talking". |
| `fp1_scales.json` | Per-feature scales of `fp1` in the app's `fp_floors.json` shape: `floor` (0.25 × population), `population`, `within` (see `../FINGERPRINT.md`). |
| `real_enroll_sim.md` | Personalization feasibility: fp1 + the app's Matcher, simulated enrollment on real audio. |
| `real_features_<tag>_clips.jsonl` | Per-event feature export (large, gitignored). `android/tools/fp_floors.py` reads `real_features_frozen_clips.jsonl`, so regenerate it before deleting. |

## Reference: synthetic, frozen

- `final_16k.*`, `final_48k.*`: the held-out synthetic run quoted in the extractor README (seed 20260926, frozen code). Kept as the synthetic reference; `real_fixed_synth*` is the same sweep on the current code.

## Superseded

- `dev1` … `dev10` (`.md`, `.json`, `_clips.jsonl`): synthetic tuning runs (seed 1) from before the code was frozen. Kept only as history.
