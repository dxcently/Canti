# Sound fingerprint `fp1` and pitch track `pitch16`

These two optional per-sound fields in the v1 feature message feed phone-side personalization (`wiki/personalization.md`). The app matches them against the user's own enrolled examples (`Personal.kt`, `Matcher`) and rewrites the sound line before any decider sees it. This file is the exact field spec; `android/PROTOCOL.md` is not changed by it. The reference code is `vox_extract/fingerprint.py`, with the per-frame sums in `frontend.py` and `segmenter.py`.

## Message field

The message gets one extra optional key, `features`. It is a list of the same length as `sequence`, with one entry per sound, in order:

```json
"features": [
  {"fp": [24 floats], "fp_version": "fp1", "pitch16": [16 floats]},   // a contour sound (rise/fall/arch/dip/flat)
  {"fp": [24 floats], "fp_version": "fp1", "pitch16": []},            // pop, click, hiss
  null                                                                 // no fingerprint for this sound
]
```

- **`fp`:** 24 numbers, in the order of the table below, each rounded to 4 decimals. The phone treats the vector as opaque; the only checks are that the version and length match the enrolled examples.
- **`fp_version`:** the string `"fp1"`. Changing anything in the table (a feature, the order, a unit, a band edge, or the frame weighting) requires a new version (`fp2`), because examples enrolled under `fp1` cannot be compared with it. The app skips matching when the versions differ.
- **`pitch16`:** 16 numbers in semitones relative to the start of the sound, rounded to 2 decimals. It is the classifier's smoothed contour, the same track that decides rise, fall, arch or dip, resampled linearly to 16 points. It is sent only when the label is a contour (`rise`, `fall`, `arch`, `dip`, `flat`); otherwise it is `[]`, even if the sound had some pitch.
- **When the field is sent:** omitting `features`, or sending `null` for a sound, is always valid. The reference sends `features` only when asked (`protocol.message(..., features=True)`; record.py always asks). The 16 kHz and 48 kHz paths give the same `fp` to within the decimator's effect.

## The 24 values

The words "loud frames" and "weights" below mean the gate's energy weighting: each frame is weighted by its power above the noise floor, `w = max(0, 10^(e/10) - 10^(floor/10))`. This is the same weighting the extractor already uses for centroid, flatness and the other spectral means.

| # | name | definition | unit / range | source |
|---|---|---|---|---|
| 0 | `f0_oct` | log2(median f0 / 100 Hz) over the cleaned, strong, voiced frames; **-3** when unpitched | octaves | classify `f0_med_hz` |
| 1 | `f0_range_st` | max − min of the smoothed contour; 0 when unpitched | semitones | `max_st - min_st` |
| 2 | `pitch_resid_std_st` | std of the contour around its least-squares line | semitones | classify |
| 3 | `pitch_rough_st` | median of the absolute 2nd difference of the contour (wobble, vibrato) | semitones | classify |
| 4 | `voiced_frac` | share of the sound's frames that are voiced (clarity ≥ 0.6, f0 > 0, ≥ 6 dB over the floor) | 0–1 | classify |
| 5 | `strong_voiced_frac` | the same, among frames within `contour_db` of the sound's 90th-percentile level | 0–1 | classify |
| 6 | `clarity_med` | median MPM clarity over all frames of the sound | 0–1 | classify |
| 7 | `centroid_oct` | log2(max(weighted centroid, 50 Hz) / 1000 Hz) | octaves | `centroid_hz` |
| 8 | `centroid_spread_oct` | std of log2(centroid) over frames above the close threshold | octaves | classify |
| 9 | `flatness` | weighted spectral flatness (90–7600 Hz) | 0–1 | classify |
| 10 | `zcr` | weighted zero-crossing rate | crossings / sample | classify |
| 11 | `lf_ratio` | weighted share of band power below 1 kHz | 0–1 | classify |
| 12 | `hf_ratio` | weighted share above 3.5 kHz | 0–1 | classify |
| 13 | `e1k` | Σ power in 1–6 kHz ÷ Σ power in 90–7600 Hz, summed over all frames of the sound (unweighted) | 0–1 | **new sum** |
| 14 | `e35f0` | pitched frames only (f0 > 0 and clarity ≥ 0.6): Σ power above 3.5 × that frame's f0 ÷ Σ their band power; 0 if no pitched frame | 0–1 | **new sum** |
| 15 | `dur_oct` | log2(max(duration, 10 ms) / 100 ms) | octaves | `dur_ms` |
| 16 | `energy_iqr_db` | interquartile range of hop energy | dB | classify |
| 17 | `flux_mean_db` | weighted mean positive log-spectral flux | dB | classify |
| 18 | `onset_flux_db` | max flux over the first 3 frames | dB | classify |
| 19 | `decay_db` | energy of the peak frame minus the mean of the last 3 frames | dB | classify |
| 20–23 | `cep1..cep4` | orthonormal DCT-II coefficients 1–4 of the 8 log mel-band powers of the whole sound. `L_i = 10 log10(Σ_frames mel_i + 1e-12)`, `cep_k = sqrt(2/8) Σ_i L_i cos(π k (i + 0.5) / 8)`. Coefficient 0, the overall level, is left out, so these do not depend on loudness | dB | **new sum** |

**Mel bands for `cep1..cep4`:**
- 8 triangular filters, HTK mel scale (`2595 log10(1 + f/700)`), from 60 to 7600 Hz, each with a peak of 1.
- They are applied to the 512-point power spectrum of every frame.

**Loudness is left out on purpose.** Level depends on mic gain and distance, and the line already carries a loudness bucket. `cep0` and `level_db` are not in the vector.

**Pitch is kept.** Across speakers it is a weak cue: voices differ, which is why a pitch gate is not used. Within one user, a meow and a hum differ mainly in f0, and matching is always against that same user's examples.

## Cost on the RP2350 (per sound; no new FFT, no new per-frame storage)

- **Per frame.** Everything reuses the power spectrum `p[0..256]` that the front end already computes for centroid and flatness.
  - Mel filters: 8 triangular filters over bins 2–243, about 480 multiply-adds.
  - Two band sums: the 1–6 kHz sum and the voiced sum above 3.5 × f0. Both are simple bin ranges, about 250 adds.
  - That is under 5 % of the frame's existing FFT and MPM work.
- **State per open sound:** 12 floats (8 mel sums, the band sum, the 1–6 kHz sum, the voiced sum and the voiced-above-3.5 f0 sum). Everything else in the table comes from values `classify` already computes. The 8 × 257 filter weights are constant; they can live in flash, or be stored sparsely as (start bin, length, weights), which is about 500 floats.
- **Once per sound:** 8 `log10`, a 4 × 8 DCT with constant cosines, and 3 `log2`.
- **Message size:** 24 + 16 numbers add about 250 bytes of JSON per sound. Over BLE, a binary encoding (int16, scaled) would make it 80 bytes.

## How the values were chosen

The choice rests on the cross-speaker cue analysis of the real-audio evaluation (`results/real_cues.md`).

- **What was tested:** which per-sound features separate hums from voiced negatives (speech, yells, cats, crying, laughing, moaning, music) consistently across speakers. The test uses per-speaker-median AUC, so one prolific speaker cannot carry a cue.
- **Strongest cues** (mean separation 0.88–0.94):
  - log-mel level and shape;
  - zcr;
  - centroid;
  - lf_ratio;
  - e1k;
  - voiced_frac, clarity and strong_voiced_frac;
  - mfcc1;
  - hf_ratio;
  - flatness.
- **Also kept:** f0 (0.84), which matters within a user; the contour statistics, which separate a wobbly meow from a steady hum; and duration, onset, decay, flux and IQR, which separate clicks, smacks and yelps from each other.
- **Dropped:**
  - HNR, because it is a third periodicity measure next to clarity and voiced_frac and would need extra work per frame;
  - MFCC 5–12, because they add little beyond cep1–4 at 8 bands and would need more mel bands;
  - syllable rate, because it is unstable on the sub-second sounds people enroll.

## Per-feature scales and the std floor

`results/fp1_scales.json` (written by `eval_real/fp_scales.py`, tune split of the real-audio evaluation, current code) has the shape of the app's `android/app/src/main/assets/fp_floors.json`, so it can replace the provisional entry as is:

```json
{"fp1": {"provisional": false, "source": "...", "names": [24 names], "floor": [24 numbers],
         "within": [24 numbers], "population": [24 numbers], "use": "..."}}
```

- **`population`:** the typical spread of the feature across many speakers and sounds: a robust std (IQR / 1.349) over clean emitted sounds, with the same number of sounds (396) from each of Deeply Nonverbal, QBSH, MUSAN, MLEnd, Nonspeech7k and ESC-50.
- **`within`:** the typical spread when the same person repeats the same sound: the median, over (dataset, speaker, class) groups with ≥ 5 sounds in Deeply Nonverbal, Nonspeech7k and ESC-50, of the std inside the group.
- **`floor` = 0.25 × `population`**, the app's rule. It is close to the app's provisional table, which used a winsorised std over all splits of the frozen export.

The app uses it as `std_j = max(population std of the enrolled examples_j, floor_j)`, then 1 if that is below 1e-9.

| # | feature | floor (0.25 x population) | population | within | within / population |
|---|---|---|---|---|---|
| 0 | `f0_oct` | 0.9077 | 3.631 | 0.6888 | 0.19 |
| 1 | `f0_range_st` | 0.9711 | 3.884 | 1.231 | 0.32 |
| 2 | `pitch_resid_std_st` | 0.2157 | 0.8627 | 0.394 | 0.46 |
| 3 | `pitch_rough_st` | 0.0102 | 0.04077 | 0.04008 | 0.98 |
| 4 | `voiced_frac` | 0.1563 | 0.6251 | 0.129 | 0.21 |
| 5 | `strong_voiced_frac` | 0.1781 | 0.7126 | 0.1327 | 0.19 |
| 6 | `clarity_med` | 0.1095 | 0.4381 | 0.07797 | 0.18 |
| 7 | `centroid_oct` | 0.3596 | 1.438 | 0.5965 | 0.41 |
| 8 | `centroid_spread_oct` | 0.092 | 0.3679 | 0.2129 | 0.58 |
| 9 | `flatness` | 0.0082 | 0.03277 | 0.01566 | 0.48 |
| 10 | `zcr` | 0.026 | 0.1042 | 0.05273 | 0.51 |
| 11 | `lf_ratio` | 0.1345 | 0.538 | 0.1412 | 0.26 |
| 12 | `hf_ratio` | 0.0092 | 0.03679 | 0.03113 | 0.85 |
| 13 | `e1k` | 0.118 | 0.4721 | 0.1487 | 0.31 |
| 14 | `e35f0` | 0.0296 | 0.1185 | 0.06878 | 0.58 |
| 15 | `dur_oct` | 0.5185 | 2.074 | 0.992 | 0.48 |
| 16 | `energy_iqr_db` | 1.617 | 6.466 | 4.421 | 0.68 |
| 17 | `flux_mean_db` | 0.3472 | 1.389 | 0.6263 | 0.45 |
| 18 | `onset_flux_db` | 0.6167 | 2.467 | 1.813 | 0.73 |
| 19 | `decay_db` | 3.338 | 13.35 | 7.709 | 0.58 |
| 20 | `cep1` | 4.652 | 18.61 | 5.296 | 0.28 |
| 21 | `cep2` | 2.811 | 11.24 | 3.467 | 0.31 |
| 22 | `cep3` | 2.33 | 9.321 | 3.193 | 0.34 |
| 23 | `cep4` | 1.637 | 6.548 | 2.38 | 0.36 |

**Which floor, and whether it matters** (`results/real_enroll_sim.md`, 5 examples per class, ×1.4, test split):
- A floor helps acceptance a little and costs false accepts; no variant is better on both. Against no floor, the published floor moved acceptance by −8 to +8 points per class (MLEnd hum 82 → 85 %, live meow 93 → 100 %, live click 91 → 94 %, Deeply Nonverbal pop 92 → 83 %) and changed false accepts on other people's audio by −12 to +90 % (cat as an ignore class: 10.3 → 15.4 per minute of MUSAN).
- **`within` is too large as a floor.** On most features it is 2× the published floor, and it raised other people's false accepts 1.5–5× for some classes (lip pop: 5.3 → 14.9 per minute of MUSAN; cat 10.3 → 18.8). So the claim that flooring at the repeat spread "would change nothing" does not hold here: within-person repeat spreads are 0.2–1.0 × the population spread, not small.
- The small classes (lip pop 12 held-out sounds, meow 60) move by several points between runs, because each variant draws its own enrollment sets.

## Feasibility (enrollment simulation on real audio)

The matcher is `vox_extract/personal.py`, a mirror of the app's `Personal.kt` as of 2026-09-26: a leave-one-out within-class threshold at every class size, and the std floor above. With 5 examples per class, ×1.4 and no floor (full tables, including 3 and 10 examples, in `results/real_enroll_sim.md`):

- **Own sounds are accepted** at 82–93 %: MLEnd hum 82 %, whistle 85 %, Deeply Nonverbal click 87 %, the user's live clicks 91 %, meows 93 %. The user's live yells reach only 63 %.
- **3 examples are too few:** Deeply Nonverbal click falls to 46 %, pop to 53 %. **10 examples** reach 90–100 %.
- **A custom class captures other people's sounds** at 0.1–14 per minute, depending on the class. The meow class is the cleanest (≤ 0.5 per minute), and a hum class is the worst (7–12 per minute). A custom class built from a common sound type will fire on other people's versions of it. The app should show this before a user binds an action to it.
- **The user's hums stay unmatched** for most classes (0.1–1.4 % captured). The exceptions are meow (7 %) and yell (8 %), and, at 10 examples, a whistle class (19 %). A hum captured this way loses its gesture.

