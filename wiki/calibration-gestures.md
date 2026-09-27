# Calibration vs gesture labels: desktop go / no-go (2026-09-27)

[Index](index.md) · [Personalization](personalization.md) · [Voice cursor](voice-cursor.md) · [Signal processing](signal-processing.md)

**Question.** The joystick setup (`extractor/joystick.py`) measures the user's home note, pitch range, voicing
threshold, vowel centres and pop thresholds. The gesture extractor (`vox_extract`, mirrored in C++ in
`firmware/extract`, fields in `vx_config.h`) runs on fixed defaults. Can overrides derived from that one setup raise
gesture-label accuracy without raising false triggers?

**Answer: no, not on the data we have. Every candidate field is NO-GO. The list of GO fields is empty, so the
phone engine has nothing to plumb as per-mic overrides yet.** The one field worth re-testing is `voiced_clarity`: it
cut false triggers on speech by a third, but it did not change gesture accuracy, and it lost two held notes. The data
also has **no hummed gesture contours**, and hums are where the voicing and creak fields would matter most.

Script: `extractor/eval_real/calib_gestures.py` (test: `extractor/tests/test_calib_gestures.py`).
Full tables: `extractor/results/calib_gestures.md` / `.json`. Numbers only; the recordings stay private.

## Data

| Set | What | n |
|---|---|---|
| **Gesture attempts** (`khoa-guided-1`, clicks and whistles blocks) | One attempt = one segment of `segments_auto.jsonl`: a take cut at energy pauses of 0.6 s or more, which does not depend on the extractor config. Cut-off `flub`s are left out. The whole 27 min `session.wav` is streamed at 48 kHz, as it was recorded, so the noise floor is the live one. | 87: pop 12, click 7, click_click 8, pop_click 5, click_pop 5, click_run 4, whistle rise / fall / arch / dip 8 / 7 / 7 / 6 quiet and 2 / 6 / 5 / 5 over a video |
| **Voice-cursor takes** (`vcursor-1`, `vcursor-2`) | Not gesture prompts: sung "ah" range glides from LOW to HIGH (expected: one rise) and held notes (anchors, levels, vowels; expected: one flat). | 6 glides, 91 held notes |
| **Negatives** | The speech takes of `khoa-guided-1` (their windows only); the quiet room (`aec-desktop-1`); media on a simulated desk and phone speaker (`aec-desktop-sim-*`: room, music with vocals, podcast, short video, gesture-like clips); the live clips of the user meowing (105946) and yelling (110107). | 20.1 min: speech 7.6, room 1.6, simulated 10.6, live 0.4 |

**No hummed gesture contours exist.**
- `khoa-guided-1` has whistles, pops, clicks and speech only.
- The `vcursor-*` and joystick sessions have calibration glides and held notes, with no hum rise, fall, arch or dip prompt.
- The live-* clips are unlabelled or hold one hum each.
- The two long live sessions (`live-20260926-171632`, 48 min, and `-184251`, 5.8 h) have no labels or session notes, and no eval uses them, so they are not used here.

Whistles are only a **stand-in** for hums:
- they sit at 1.2–1.9 kHz, so pitch floor and creak rules never touch them;
- the range the calibration measured is the user's hummed range, not their whistle range.

**Scoring.**
- **Label.** An attempt is right when its deliberate gesture labels match the expected sequence exactly. Deliberate means the phone would act on it (`policy.not_deliberate` is None). For a click run, 3 or more clicks with nothing else counts as right.
- **Segmentation.** Missed = nothing. Merged = fewer sounds than expected. Split = more.
- **False triggers.** Deliberate gesture events per minute, which is what the config changes. App actions per minute (`sequencer_sim`, default bindings, PhoneGate on for media) are reported next to them.
- **Uncertainty.** 2000 paired bootstrap resamples, over attempts for accuracy and over windows or 20 s chunks for false triggers.
- **Sample size.** n is small: one attempt moves a kind's accuracy by 8–20 points. Five candidates were tested on one set, so a lone "win" would also be a multiple-comparison risk.

**GO rule.** A candidate is GO only if all of these hold:
- net gain of at least 2 attempts, with bootstrap P(Δ > 0) ≥ 0.9;
- the pooled false-trigger count does not rise;
- no negative set gains more than one event;
- the glides and held notes do not lose.

## Candidates: derived only from `recordings/joystick/*.json`

These are never fitted on the scored takes. The formulas are in `calib_gestures.derive()`.

| Candidate | `vx_config` field(s) | Derivation | Value for this user |
|---|---|---|---|
| voicing | `voiced_clarity` | `range.json` `clarity_on` | 0.82 (default 0.60) |
| pitch floor (creak) | `f0_min_hz` | 55 × 2^((lo_st − 3) / 12): 3 st under the range's bottom | 82.1 Hz (default 75) |
| excursion scaled to range | `flat_max_range_st`, `shape_min_st`, `exc_medium_st`, `exc_large_st` | default × clip((hi_st − lo_st) / 12, 0.5, 1.5) | ×0.74 (8.9 st range) |
| pop core length | `discrete_core_ms` | 20 ms × `pops.json` `pop.core_ticks` | 100 ms (default 60) |
| pop onset | `pop_onset_flux_db` | 6 × `pop.rise_db` / 5 (the ratio of the two detectors' defaults) | 11.9 dB (default 6) |

**Not derivable from the files as saved:**
- **pop-vs-click** (`click_centroid_hz`): `pops.json` holds no spectral number, and the setup has no click step.
- **creak gap-bridging**: no config field bridges voiced gaps. The segmenter is energy-gated, and `hangover_frames` is energy. The setup does not measure creak.
- **long-tailed pops** (`discrete_max_ms`): no burst length was saved.
- **vowel centres**: the gesture extractor has no formant field.

Two global what-ifs were scored for information only, and are never GO:
- `hangover_frames` = 20, the joystick's 200 ms end gap;
- `discrete_max_ms` = 300, the tick detector's 15 ticks.

## Results

Default accuracy: **36.8 %** (32 / 87 attempts). Default false triggers: **4.82 / min** pooled, and 6.34 / min on
speech. App actions: 3.33 / min pooled.

| Config | Accuracy | Gained / lost | Δ acc (95 % CI) | Δ false triggers / min pooled (95 % CI) | Δ app actions / min | Glides + held: gained / lost | Verdict |
|---|---|---|---|---|---|---|---|
| voicing (`voiced_clarity` 0.82) | 36.8 % | 0 / 0 | +0.0 | **−0.99 (−1.63, −0.42)** | −0.99 | 3 / 2 (held missed 3 → 5) | **NO-GO**: no accuracy change |
| pitch floor (`f0_min_hz` 82.1) | 36.8 % | 0 / 0 | +0.0 | 0.00 | 0.00 | 0 / 1 | **NO-GO** |
| excursion ×0.74 | 36.8 % | 0 / 0 | +0.0 | −0.05 (−0.38, +0.31); speech +2 | −0.05 | 0 / 4 (held flat 29 → 23) | **NO-GO** |
| pop core (`discrete_core_ms` 100) | 37.9 % | 1 / 0 | +1.1 (0.0, +3.4) | **+1.94 (+1.18, +2.76)**; speech +14, gesture-like media +16 | +0.20 | 0 / 0 | **NO-GO** |
| pop onset (`pop_onset_flux_db` 11.9) | 36.8 % | 0 / 0 | +0.0 | 0.00 | 0.00 | 0 / 0 | **NO-GO**: no effect (see below) |
| all five together | 37.9 % | 1 / 0 | +1.1 (0.0, +3.4) | +1.09 (+0.20, +1.96) | −0.75 | 1 / 5 | **NO-GO** |
| what-if `hangover_frames` 20 | 27.6 % | 2 / 10 | −9.2 (−17.2, −1.1) | −2.14 | −1.24 | 1 / 3 | never GO: click pairs merge (8 → 0 right) |
| what-if `discrete_max_ms` 300 | 37.9 % | 1 / 0 | +1.1 (0.0, +3.4) | 0.00 | 0.00 | 0 / 0 | never GO; one long pop recovered |

Default accuracy per kind:
- **click pairs** 8 / 8;
- **single clicks** 1 / 7 (3 read as mouth hiss, 3 missed);
- **pops** 6 / 12 (6 missed);
- **pop_click** 2 / 5;
- **click_pop** 0 / 5;
- **click runs** 1 / 4;
- **whistle rise** 6 / 8 quiet;
- **whistle fall** 5 / 7 quiet;
- **whistle arch** 0 / 12;
- **whistle dip** 0 / 11.

## What the numbers say

1. **The misses are not threshold misses that one calibration could move.**
   - The 6 missed pops are not one problem; see [the follow-up](#follow-up-arch--dip-long-pops-clicks-in-runs-2026-09-27) for what the extra length is. The 100 ms core length recovers one pop but added 14 speech false triggers.
   - `pop_onset_flux_db` changed nothing on the pops that already pass the length rules. Two of the missed pops are *not* impulsive by the extractor's test, because a low-frequency pre-burst comes first (see the follow-up).
2. **Tongue clicks inside a run read as pops in 2 of 4 runs.** Their peak centroid is 1.35–1.53 kHz, under the 1.8 kHz split, while clicks said alone or in pairs sit at 2.7–4.8 kHz. That is a person-specific pop-vs-click boundary, but the setup never records a click or a centroid, so it cannot be derived. The follow-up covers features other than centroid.
3. **The user's whistled arches and dips come out inverted, consistently. The pipeline was checked and is not the cause** (follow-up, section A).
   - Arch reads as dip in 6 of 7 quiet attempts: the contour holds, falls about 7 st, then comes back.
   - Dip reads as rise in 5 of 6: up about 10 st, then back about 5 st.
   - An independent FFT-peak pitch track gives the same shapes. This is how the whistles were produced in this session. Per-person **enrollment** of re-recorded gestures ([Personalization](personalization.md)) is the tool for it, not `vx_config`.
4. **`voiced_clarity` = the user's clarity_on is the only candidate with a real benefit.**
   - Speech false triggers fell from 48 to 31 events (6.3 → 4.1 / min), and app actions from 39 to 19.
   - It did not change a single gesture label.
   - On the held notes it lost two voiced events (missed 3 → 5). That is the hum risk: a creaky or breathy hum loses voiced frames and turns into "talking" or nothing.
   - Without hummed gestures this cannot be cleared. The rule says NO-GO.
5. **Scaling the pitch thresholds to the user's range hurts.** Held notes stop being flat (29 → 23 read flat), and speech gains 2 triggers. A narrow hummed range does not mean small deliberate glides: the whistles use 7–12 st.
6. **The calibration already helps where it lives now.** The joystick's own tick-level PopDetector reads `pops.json`, and that is where the per-person pop thresholds belong. Pushing the same numbers into the extractor's discrete rules adds false triggers.

## Follow-up: arch / dip, long pops, clicks in runs (2026-09-27)

Scratch scripts only; no default was changed. Numbers only; the recordings stay private.

### A. Whistled arch → dip and dip → rise: the user's production, not a pipeline bug

Suspects checked, one at a time:

| Suspect | Check | Result |
|---|---|---|
| Prompt ↔ segment alignment (off-by-one) | Cross-correlated every whistle take's own wav against `session.wav` at its `clip_offset_ms` (±500 ms search). Checked that take order matches prompt order, and that the prompt text shown was `sounds_v1.json` `instruction` ("UP then DOWN (an arch)", "DOWN then UP (a dip)"). | Lag 0 ms on all 42 whistle takes; 40 are sample-identical. The order is rise, fall, arch, dip in every round. No off-by-one. |
| Pitch tracker (range, octave or subharmonic errors) | MPM f0 compared with an independent FFT-peak tracker (48 kHz audio, 2048-point Hann, 500–4000 Hz, parabolic peak) on every strong voiced frame of the whistle events (2628 frames). | Quiet takes: **no** octave errors. Median \|MPM − FFT\| is 0.02 st, and 96.5 % of frames are within 0.5 st. The whistles sit at 1.1–2.3 kHz, under `f0_max_hz` 2600. In loud frames the 300 Hz–20 kHz argmax equals the 500–4000 Hz one 95.7 % of the time, and the 2nd harmonic is −40 dB, so this is the fundamental. |
| Contour classifier sign or shape logic | Fed synthetic 48 kHz whistle glides through the full extractor (decimator included): arch 1300→2200→1300 Hz, dip 2000→1200→2000, rise, fall. | Each one reads correctly (arch hump 7.9 st, dip valley 7.9 st). This is now a test: `tests/test_synthetic_regression.py::test_whistle_shapes_are_not_inverted_at_48k`. |
| Trimming, hold cut or smoothing dropping one half | Classified the FFT-peak track itself with `contour_shape` (no MPM, no median, no jump limit). | Same labels: quiet arch → dip 6, fall 1. Quiet dip → rise 4, arch 2. |

What the audio actually does (FFT track, semitones re the start, quiet takes):
- **Arch prompts:** hold, fall 5–9 st, return to about the start: a V, i.e. a dip. The first arch attempt of the session was up about 2 st and then down about 7 st, which reads as fall.
- **Dip prompts:** rise 10–13 st, then settle 4–6 st back down and hold. That is an overshooting rise. It is never "down then up", and it was already like this on the first dip attempt.

The live feedback ("heard: dip") was on screen after each arch take, and the arches were not changed. For contrast, the
user-confirmed live whistle arches (sessions 124112 / 124244, `tests/live_regressions.json`) *are* up-then-down.
Only this guided session inverts them. The next step is a question for the user, not code: whistle one arch and one
dip while watching a live pitch trace.

A side finding that *is* a pipeline weakness, but a different one: in the **video** condition the background
voice (100–300 Hz) and the whistle fall in one event. MPM then follows the voice for part of it, and the contour
jumps 30–44 st. That accounts for all 3 % of frames where MPM and FFT disagree by more than 10 st. `clean_pitch` enforces
continuity only within 3-frame gaps, so a voice → whistle jump across a longer gap is kept.

### B. The 6 long pops: what the extra length is

Each missed pop's gate span, cut into pre-burst, burst (steepest rise → first frame under the close threshold), and tail:

| Missed pop | Gate time | What makes it long |
|---|---|---|
| 1 | 490 ms | burst 120 ms, then **360 ms of unvoiced low-level noise** at about 5 dB over the floor (the close threshold is floor + 5 dB). Frames flicker across the threshold with gaps of 10–50 ms, and the 100 ms hangover bridges every gap. |
| 2 | 280 ms | same: burst 100 ms, then a 160 ms tail at about 4 dB over the floor, bridged across an 80 ms gap |
| 3 | 370 ms | **90 ms low-frequency pre-burst** before the pop (about 10 dB over floor, centroid about 400 Hz, 87 % of energy under 1 kHz), then burst 130 ms, then a bridged 150 ms tail |
| 4 | 240 ms | 60 ms LF pre-burst of the same kind, then burst 180 ms |
| 5 | 150 ms | not long: its **core** is 80 ms (limit 60), a weaker, slower pop (peak 30 dB over floor versus 41–46 for the pops read right) |
| 6 | 340 ms | a 310 ms LF-heavy burst (85 % under 1 kHz), core 110 ms: more a puff than a pop |

- **Not room reverb.** Reverb decays smoothly. These tails are a flat plateau at 4–5 dB, unvoiced, centroid about 0.9 kHz, with about 65–70 % of the energy under 1 kHz. They also appear in only 3 of 12 pops, while the room is the same for all of them.
- **Breath or air release after the pop**, sitting right at the close threshold and **held open by the gate's hangover**. The burst itself (about 100–130 ms down to the threshold) is the same in the pops read right and the ones missed. A lip pop rings at about 1 kHz, with clarity 0.5–0.9 in its decay.
- The LF pre-burst is before the release, so it is not reverb or mic wind from the burst. The likeliest cause is lip or air pressure noise, or mic handling; the data cannot tell which.

Default changes tried: the user's gesture attempts and negatives (20.1 min); Deeply Nonverbal lip pops and mouth-noise negatives (other speakers, tune + test); Nonspeech7k (405 min of breath, cough, laugh, …).

| Change | Pops right (of 12) | User negatives: events / actions | DN lip-pop detect, clean (tune / test) | DN negatives FA groups (tune / test) | Nonspeech7k FA groups (tune / test) |
|---|---|---|---|---|---|
| default | 6 | 97 / 67 | 47 % / 26 % | 13 / 8 | 228 / 660 |
| **discrete length = start → first frame under the close threshold after the peak** (code; ignores the bridged tail) | **8** | 98 / 67 | 53 % / 31 % | 15 / 8 | 230 / 662 |
| `discrete_max_ms` 300 | 7 | 97 / 67 | 47 % / 29 % | 14 / 8 | 229 / 663 |
| `discrete_max_ms` 500 | 8 | 98 / 67 | 58 % / 37 % | 15 / 9 | 229 / 671 (cough → pop 204 → 239 events) |
| `gate_close_db` 7 | 7 | **127 / 72** | 63 % / 31 % | 15 / 16 | 252 / **867** |
| `hangover_frames` 6 | 7 | **137 / 76** | 58 % / 31 % | 14 / 17 | 255 / 710 |
| impulsive also on a ≥ 15 dB one-frame rise before the peak (code) | 6 | 97 / 67 | 47 % / 31 % | 13 / 10 | 229 / 662 |

**Recommendation.** Measure the discrete length from the start of the sound to the first frame after the peak that falls
under the close threshold, and leave `discrete_max_ms` at 200. It recovers the 2 tail-bridged pops. False triggers stay
flat: +1 user event, +2 DN groups on tune, +2 Nonspeech7k groups over 405 min.

If only a config change is wanted, `discrete_max_ms` 300 is the safe step, but it recovers only 1. Do **not** use a
shorter hangover or a higher close threshold: each adds 30–40 user false triggers. Neither fix passes this page's GO rule
by the letter (it needs a net gain of 2 with P ≥ 0.9 on 87 attempts).

The other 4 pops (LF pre-burst, weak or slow pops) need the length **and** the impulsiveness **and** the core rules
loosened together, and the core rule alone already costs 14 speech triggers. Enroll those per person.

C++ mirror of the recommended change (not applied), `firmware/extract/src/vx_classify.cpp:502`:

```diff
-    if (dur <= cfg->discrete_max_ms && core_ms <= cfg->discrete_core_ms) {
+    int burst_n = peak_i;   // the gate span up to the first frame after the peak under the close threshold
+    while (burst_n < n && e[burst_n] > floor + seg->close_over_floor_db) burst_n++;
+    const double burst_ms = burst_n * fm;
+    if (burst_ms <= cfg->discrete_max_ms && core_ms <= cfg->discrete_core_ms) {
```

The same change goes in `classify.py` at the `dur <= cfg.discrete_max_ms` test, and `burst_ms` goes into `raw` on both sides.

### C. Clicks read as pops inside runs: is there a feature other than centroid?

The user's single-kind takes, restricted to events on the discrete path: 24 clicks (3 read as pop) and 6 pops.

| Feature | User clicks | User pops | The 3 misread clicks | Deeply Nonverbal (33 / 23 speakers), AUC |
|---|---|---|---|---|
| peak centroid | 1.35–4.75 kHz | 0.97–1.16 kHz | 1.35, 1.45, 1.53 kHz | 0.90 |
| `lf_ratio` (energy share under 1 kHz) | 0.01–0.07 | 0.12–0.47 | 0.07, 0.01, 0.02 | 0.90 (pop higher) |
| gate duration | 20–70 ms | 100–150 ms | 50 ms each | **0.52** (no use across speakers) |
| peak level over floor | 16–30 dB | 41–46 dB | 21–29 dB | not comparable (depends on mic distance) |
| voiced frac / clarity | mostly 0 / 0.36 | 0.42 / 0.54 | 0.4–1.0 / 0.56–0.79 | 0.34 / 0.54 |

- **Yes, for this user.** Duration and peak level each separate their clicks from their pops with a margin: 70 → 100 ms, and 30 → 41 dB. `lf_ratio` separates 2 of the 3 misread clicks, and the third ties the lowest pop (0.07).
- The misread clicks are tonal "clucks": a resonance at 1.3–1.4 kHz, voiced 40–100 %. That is why they fall under the 1.8 kHz centroid split.
- **Not as a default.** On other speakers, duration does not separate clicks from pops (AUC 0.52). Adding "click if 1.2–1.8 kHz and `lf_ratio` < 0.10" to the centroid rule gains 1 of 161 DN clicks and flips 2 more of 40 DN pops to click (clean).
- This is per-person material: enroll clicks, or a click step in the setup that saves duration and `lf_ratio`. n is small (6 pops).

## C++ / Python parity (for when a field does become GO)

All candidate fields are plain config fields, read the same way on both sides:

| Field | Python | C++ |
|---|---|---|
| `voiced_clarity` | `classify.py`, `hold.py` | `vx_classify.cpp:339`, `vx_hold.cpp:14`, `vx_frontend.cpp:75/279` |
| `discrete_core_ms` | core frames × frame_ms | `vx_classify.cpp:496/502` |
| `exc_*` / `shape_min_st` / `flat_max_range_st` | contour code | `vx_classify.cpp:196–202, 526` |
| `pop_onset_flux_db` | classifier | `vx_classify.cpp:493` |
| `f0_min_hz` | tau_max = min(n − 2, ⌈sr / f0_min⌉) | tau_max = ⌈sr / f0_min⌉ (`vx_frontend.cpp:72`) |

The two tau_max rules agree for any `f0_min_hz` ≥ 31.4 Hz at the default 512-sample window. `vx_config_check` does not
bound `f0_min_hz`, so a per-mic override should be clamped on the app side (for example to 40–150 Hz).

## What would settle it (the missing data)

Record **hummed gestures** after a fresh joystick setup:

- **Contours:** 15 attempts each of hummed rise, fall, arch, dip and flat (75 attempts, about 10 minutes).
  - Half start at the home note, half near the bottom of the range, where the creak is.
  - With 15 per kind, one attempt is 7 points. A net gain of 2 attempts on a kind is then the smallest thing the rule can see.
- **Short hums:** 10 short hums (under 400 ms), for `voiced_clarity`.
- **Pops and clicks:** 10 lip pops and 10 single tongue clicks. The pop setup now saves each setup pop's burst length and the extractor's reading of it (`ticks`, `extractor_raw`), so `discrete_max_ms` and a click / pop centroid split become derivable. A click step in the setup would complete the pop-vs-click derivation.
- **Re-run:** `./run python eval_real/calib_gestures.py`. The script picks up any new calibration numbers through `derive()`.

## Setup: retry or skip, never skip by itself (user rule, 2026-09-27)

Every joystick setup step now says why it failed, then **waits**: **R** retries that step, **S** skips it (its
defaults stay). While it waits, nothing moves and nothing clicks.

Failures:
- nothing steady within 10 s of the prompt (home, range, each vowel);
- a hum that is too short or too rough;
- a range under 4 st;
- a vowel with fewer than 30 clear frames in 12 s, or vowels that overlap (a vowel steers its own way less than half the time, in-sample);
- fewer than 2 of 3 pops.

What a skip saves:
- Skipped steps are listed in `range.json` (`"skipped"`).
- A skipped vowel or pop step writes its file with `"skipped"` and no numbers, so `--skip-setup` and `calib_gestures.derive()` both keep the defaults for it.
