# REAL audio: cue analysis (fixed code)

```
Offline analyses on the per-event feature export (features.py). Nothing here changes the extractor.

  ./run python eval_real/cues.py --tag frozen        # -> results/real_cues.md

1. Which cues separate hums from the voiced negatives ACROSS SPEAKERS (for fp1 and the v6 categories).
   AUC of each cue for hum vs X on two levels: events, and per-speaker medians (one point per speaker,
   so a cue that only works because one prolific speaker differs does not score). 0.5 = useless,
   1.0 / 0.0 = perfect (below 0.5 = the cue is LOWER for X). "sep" = max(AUC, 1 - AUC).
2. The brightness rule (hypothesis from the user's yells): a voiced sound with f0 < 900 Hz and
   (E1k > 0.30 or E3.5 > 0.85) would be tagged "talking" (so never an action). False rejects on hums
   that currently fire; catches (FA groups / min before -> after) on the negatives.
3. A per-user pitch-range gate (EVALUATED ONLY; the user ruled it out as the fix): calibrate on the
   first 5 hums of a speaker, reject voiced sounds whose median f0 is outside [min, max] +- margin.
4. Low-f0 hums tagged "talking": share by f0 bin and which speech cues fired.
```

## 1. Which cues separate hums from voiced negatives across speakers

AUC of each cue, MLEnd hum (voiced events, >= 150 ms, as recorded) vs each voiced negative. Cell = per-speaker-median AUC (event-level AUC in brackets); live columns are one speaker, events only. Sorted by mean separation over the negatives (whistle excluded). > 0.5 = the negative has HIGHER values.

| cue | speech (14661/426) | yell (1005/230) | cat (86/28) | crying (5304/1052) | laughing (2690/310) | moaning (64/33) | music (9217/93) | whistle (18415/128) | live meow (7/1) | live yell (7/1) | mean sep |
|---|---|---|---|---|---|---|---|---|---|---|---|
| logmel0 | 0.76 (0.69) | 1.00 (0.99) | 1.00 (0.99) | 0.95 (0.94) | 0.99 (0.96) | 0.91 (0.85) | 0.86 (0.72) | 1.00 (0.99) | (0.98) | (0.99) | 0.94 |
| zcr | 0.10 (0.18) | 0.00 (0.02) | 0.00 (0.01) | 0.06 (0.08) | 0.02 (0.06) | 0.22 (0.28) | 0.13 (0.28) | 0.00 (0.02) | (0.03) | (0.01) | 0.94 |
| centroid_hz | 0.10 (0.17) | 0.00 (0.02) | 0.00 (0.01) | 0.06 (0.08) | 0.02 (0.06) | 0.22 (0.28) | 0.20 (0.34) | 0.00 (0.01) | (0.00) | (0.00) | 0.93 |
| lf_ratio | 0.91 (0.83) | 0.99 (0.98) | 1.00 (0.99) | 0.93 (0.88) | 0.97 (0.92) | 0.81 (0.74) | 0.85 (0.72) | 0.99 (0.98) | (0.96) | (0.90) | 0.92 |
| voiced_frac | 0.99 (0.82) | 0.93 (0.89) | 0.91 (0.73) | 0.97 (0.86) | 1.00 (0.92) | 0.99 (0.91) | 1.00 (0.91) | 0.27 (0.42) | (0.33) | (0.84) | 0.92 |
| e1k | 0.10 (0.17) | 0.01 (0.03) | 0.00 (0.01) | 0.08 (0.12) | 0.03 (0.08) | 0.20 (0.27) | 0.17 (0.30) | 0.01 (0.02) | (0.05) | (0.10) | 0.92 |
| clarity_med | 1.00 (0.94) | 0.92 (0.92) | 0.95 (0.86) | 0.96 (0.92) | 1.00 (0.96) | 0.98 (0.93) | 1.00 (0.95) | 0.29 (0.38) | (0.17) | (0.51) | 0.91 |
| peak_centroid_hz | 0.13 (0.21) | 0.01 (0.04) | 0.00 (0.02) | 0.09 (0.10) | 0.04 (0.09) | 0.31 (0.34) | 0.36 (0.43) | 0.01 (0.03) | (0.00) | (0.00) | 0.90 |
| hf_ratio | 0.24 (0.32) | 0.05 (0.10) | 0.06 (0.15) | 0.09 (0.12) | 0.05 (0.09) | 0.15 (0.22) | 0.16 (0.33) | 0.73 (0.69) | (0.09) | (0.21) | 0.88 |
| mfcc1 | 0.50 (0.40) | 0.99 (0.97) | 0.98 (0.96) | 0.95 (0.93) | 0.97 (0.95) | 0.90 (0.82) | 0.73 (0.59) | 0.96 (0.91) | (1.00) | (0.88) | 0.88 |
| strong_voiced_frac | 0.98 (0.83) | 0.92 (0.88) | 0.74 (0.63) | 0.95 (0.82) | 0.96 (0.88) | 0.89 (0.83) | 1.00 (0.96) | 0.44 (0.41) | (0.26) | (0.73) | 0.88 |
| mfcc3 | 0.38 (0.35) | 0.94 (0.88) | 0.89 (0.81) | 0.89 (0.86) | 0.88 (0.83) | 0.87 (0.80) | 0.73 (0.66) | 0.87 (0.80) | (0.94) | (0.98) | 0.86 |
| flux_mean_db | 0.28 (0.35) | 0.21 (0.33) | 0.20 (0.25) | 0.06 (0.13) | 0.09 (0.13) | 0.07 (0.15) | 0.88 (0.79) | 0.34 (0.39) | (0.78) | (0.05) | 0.85 |
| flatness | 0.41 (0.49) | 0.07 (0.08) | 0.07 (0.16) | 0.07 (0.12) | 0.03 (0.06) | 0.11 (0.18) | 0.10 (0.27) | 0.66 (0.64) | (0.35) | (0.28) | 0.83 |
| f0_med_hz | 0.76 (0.73) | 0.06 (0.07) | 0.02 (0.03) | 0.09 (0.10) | 0.11 (0.12) | 0.38 (0.36) | 0.64 (0.64) | 0.00 (0.01) | (0.00) | (0.30) | 0.83 |
| mfcc2 | 0.76 (0.79) | 0.97 (0.95) | 0.90 (0.91) | 0.89 (0.86) | 0.91 (0.85) | 0.57 (0.57) | 0.60 (0.60) | 0.97 (0.94) | (0.95) | (0.90) | 0.83 |
| voiced_runs | 0.10 (0.29) | 0.16 (0.24) | 0.33 (0.47) | 0.14 (0.32) | 0.05 (0.22) | 0.19 (0.36) | 0.11 (0.31) | 0.61 (0.54) | (0.60) | (0.28) | 0.80 |
| e35f0 | 0.03 (0.10) | 0.39 (0.39) | 0.14 (0.23) | 0.25 (0.29) | 0.16 (0.26) | 0.24 (0.33) | 0.11 (0.25) | 0.99 (0.97) | (0.71) | (0.17) | 0.80 |
| logmel4 | 0.14 (0.20) | 0.08 (0.12) | 0.16 (0.14) | 0.15 (0.21) | 0.12 (0.21) | 0.42 (0.42) | 0.33 (0.40) | 0.18 (0.25) | (0.69) | (0.14) | 0.80 |
| energy_iqr_db | 0.15 (0.33) | 0.41 (0.47) | 0.20 (0.29) | 0.06 (0.27) | 0.06 (0.22) | 0.01 (0.15) | 0.92 (0.70) | 0.07 (0.29) | (0.52) | (0.58) | 0.79 |
| logmel1 | 0.43 (0.40) | 0.93 (0.89) | 0.87 (0.85) | 0.78 (0.76) | 0.87 (0.81) | 0.80 (0.75) | 0.69 (0.57) | 0.98 (0.95) | (0.23) | (0.84) | 0.79 |
| logmel7 | 0.61 (0.67) | 0.12 (0.23) | 0.09 (0.19) | 0.17 (0.17) | 0.14 (0.17) | 0.13 (0.18) | 0.29 (0.44) | 0.45 (0.45) | (0.09) | (0.46) | 0.79 |
| mfcc0 | 0.21 (0.24) | 0.14 (0.17) | 0.20 (0.23) | 0.42 (0.33) | 0.22 (0.29) | 0.52 (0.54) | 0.04 (0.11) | 0.66 (0.61) | (0.22) | (0.00) | 0.79 |
| pitch_rough_st | 0.00 (0.12) | 0.35 (0.27) | 0.39 (0.43) | 0.14 (0.23) | 0.02 (0.12) | 0.07 (0.18) | 0.40 (0.51) | 0.86 (0.70) | (0.82) | (0.62) | 0.78 |
| logmel3 | 0.31 (0.31) | 0.07 (0.12) | 0.09 (0.09) | 0.23 (0.34) | 0.22 (0.28) | 0.40 (0.38) | 0.42 (0.41) | 0.07 (0.09) | (0.19) | (0.08) | 0.78 |
| logmel5 | 0.13 (0.20) | 0.09 (0.15) | 0.16 (0.19) | 0.20 (0.24) | 0.18 (0.21) | 0.54 (0.56) | 0.38 (0.46) | 0.50 (0.48) | (0.45) | (0.16) | 0.76 |
| decay_db | 0.59 (0.57) | 0.39 (0.53) | 0.26 (0.34) | 0.18 (0.37) | 0.45 (0.43) | 0.07 (0.21) | 0.98 (0.84) | 0.35 (0.43) | (0.70) | (0.17) | 0.75 |
| centroid_spread_oct | 0.09 (0.25) | 0.53 (0.54) | 0.21 (0.36) | 0.20 (0.35) | 0.29 (0.34) | 0.08 (0.17) | 0.37 (0.49) | 0.90 (0.76) | (0.18) | (0.41) | 0.74 |
| hnr_db | 0.96 (0.84) | 0.62 (0.65) | 0.48 (0.50) | 0.65 (0.64) | 0.82 (0.71) | 0.62 (0.58) | 0.89 (0.73) | 0.02 (0.07) | (0.01) | (0.40) | 0.74 |
| syllable_rate_hz | 0.24 (0.38) | 0.70 (0.61) | 0.66 (0.55) | 0.17 (0.34) | 0.12 (0.28) | 0.42 (0.43) | 0.97 (0.78) | 0.02 (0.24) | (0.24) | (0.48) | 0.74 |
| logmel6 | 0.31 (0.37) | 0.12 (0.19) | 0.26 (0.36) | 0.23 (0.26) | 0.15 (0.20) | 0.29 (0.32) | 0.36 (0.48) | 0.63 (0.59) | (0.22) | (0.39) | 0.74 |
| pitch_jumps_hz | 0.30 (0.35) | 0.17 (0.22) | 0.27 (0.34) | 0.26 (0.32) | 0.15 (0.24) | 0.22 (0.32) | 0.20 (0.28) | 0.49 (0.53) | (0.65) | (0.53) | 0.74 |
| mfcc4 | 0.73 (0.70) | 0.66 (0.69) | 0.56 (0.49) | 0.78 (0.74) | 0.76 (0.70) | 0.48 (0.49) | 0.59 (0.58) | 0.21 (0.26) | (0.96) | (0.91) | 0.72 |
| pitch_resid_std_st | 0.29 (0.38) | 0.23 (0.25) | 0.31 (0.38) | 0.44 (0.41) | 0.18 (0.30) | 0.31 (0.35) | 0.29 (0.42) | 0.91 (0.71) | (0.86) | (0.63) | 0.72 |
| f0_range_st | 0.29 (0.38) | 0.21 (0.26) | 0.36 (0.39) | 0.47 (0.43) | 0.20 (0.32) | 0.28 (0.34) | 0.38 (0.46) | 0.92 (0.71) | (0.91) | (0.63) | 0.71 |
| onset_flux_db | 0.33 (0.42) | 0.44 (0.53) | 0.40 (0.42) | 0.20 (0.31) | 0.27 (0.33) | 0.43 (0.44) | 0.84 (0.73) | 0.68 (0.59) | (0.53) | (0.03) | 0.70 |
| mfcc7 | 0.61 (0.65) | 0.34 (0.35) | 0.21 (0.27) | 0.41 (0.37) | 0.38 (0.40) | 0.30 (0.33) | 0.21 (0.30) | 0.63 (0.57) | (0.78) | (0.32) | 0.69 |
| logmel2 | 0.40 (0.40) | 0.21 (0.21) | 0.27 (0.29) | 0.43 (0.37) | 0.35 (0.38) | 0.36 (0.39) | 0.34 (0.33) | 0.25 (0.35) | (0.58) | (0.03) | 0.69 |
| mfcc11 | 0.22 (0.25) | 0.35 (0.33) | 0.22 (0.25) | 0.36 (0.36) | 0.39 (0.39) | 0.47 (0.52) | 0.30 (0.34) | 0.26 (0.35) | (0.13) | (0.63) | 0.69 |
| mfcc5 | 0.84 (0.77) | 0.43 (0.49) | 0.66 (0.63) | 0.82 (0.75) | 0.65 (0.63) | 0.52 (0.48) | 0.54 (0.52) | 0.16 (0.23) | (0.83) | (0.71) | 0.68 |
| dur_ms | 0.70 (0.60) | 0.33 (0.49) | 0.55 (0.54) | 0.67 (0.61) | 0.55 (0.58) | 0.43 (0.54) | 0.80 (0.64) | 0.83 (0.63) | (0.78) | (0.39) | 0.66 |
| syllable_peaks | 0.43 (0.49) | 0.58 (0.59) | 0.59 (0.57) | 0.32 (0.48) | 0.23 (0.41) | 0.38 (0.48) | 0.96 (0.76) | 0.39 (0.44) | (0.49) | (0.42) | 0.65 |
| mfcc12 | 0.60 (0.61) | 0.37 (0.42) | 0.44 (0.41) | 0.41 (0.36) | 0.29 (0.37) | 0.36 (0.43) | 0.27 (0.39) | 0.41 (0.46) | (0.19) | (0.40) | 0.65 |
| mfcc10 | 0.43 (0.44) | 0.36 (0.37) | 0.27 (0.27) | 0.46 (0.45) | 0.39 (0.40) | 0.41 (0.42) | 0.31 (0.35) | 0.20 (0.30) | (0.24) | (0.29) | 0.65 |
| mfcc6 | 0.39 (0.37) | 0.41 (0.41) | 0.43 (0.43) | 0.75 (0.60) | 0.60 (0.54) | 0.52 (0.55) | 0.42 (0.42) | 0.48 (0.46) | (0.99) | (0.44) | 0.64 |
| mfcc9 | 0.49 (0.48) | 0.42 (0.44) | 0.25 (0.26) | 0.51 (0.51) | 0.42 (0.41) | 0.56 (0.58) | 0.41 (0.41) | 0.32 (0.39) | (0.10) | (0.30) | 0.63 |
| mfcc8 | 0.40 (0.40) | 0.54 (0.53) | 0.46 (0.45) | 0.69 (0.65) | 0.45 (0.49) | 0.48 (0.48) | 0.43 (0.46) | 0.64 (0.59) | (0.23) | (0.16) | 0.63 |

Hum reference: 37726 events from 226 MLEnd speakers; live hums: 43 events.

## 2. Brightness rule (hypothesis, not in the extractor)

#### E1k > 0.30 or E3.5 > 0.85, f0 < 900 Hz

Negatives, TEST split, FA groups per minute before -> after:

| dataset | class | min | FA/min before | FA/min after | FAs removed |
|---|---|---|---|---|---|
| nonverbal | ALL | 20.4 | 1.13 | 0.98 | 13 % |
| nonverbal | screaming | 1.4 | 5.13 | 2.93 | 43 % |
| nonverbal | moaning | 1.6 | 1.91 | 1.91 | 0 % |
| nonverbal | teeth-chattering | 1.7 | 1.76 | 1.76 | 0 % |
| nonverbal | crying | 1.8 | 1.12 | 1.12 | 0 % |
| nonverbal | laughing | 1.7 | 0.00 | 0.00 | - |
| musan | ALL | 813.5 | 1.64 | 1.50 | 9 % |
| musan | music | 518.0 | 2.13 | 2.01 | 6 % |
| musan | speech | 295.5 | 0.79 | 0.62 | 22 % |
| nonspeech7k | ALL | 304.5 | 2.14 | 1.77 | 18 % |
| nonspeech7k | crying | 88.0 | 2.14 | 1.41 | 34 % |
| nonspeech7k | breath | 101.1 | 1.53 | 1.53 | 0 % |
| nonspeech7k | laugh | 50.2 | 2.33 | 2.07 | 11 % |
| nonspeech7k | screaming | 27.2 | 3.56 | 2.35 | 34 % |
| nonspeech7k | cough | 24.8 | 1.81 | 1.69 | 7 % |
| nonspeech7k | yawn | 6.7 | 4.48 | 4.48 | 0 % |
| nonspeech7k | sneeze | 6.3 | 3.31 | 3.00 | 10 % |
| esc50 | ALL | 109.6 | 2.39 | 2.03 | 15 % |
| esc50 | cow | 2.0 | 8.17 | 7.15 | 12 % |
| esc50 | rooster | 1.4 | 9.21 | 2.83 | 69 % |
| esc50 | mouse_click | 1.8 | 6.76 | 6.76 | 0 % |
| esc50 | can_opening | 1.4 | 7.02 | 7.02 | 0 % |
| esc50 | church_bells | 2.6 | 3.87 | 1.55 | 60 % |
| esc50 | clock_alarm | 2.1 | 4.75 | 3.80 | 20 % |
| esc50 | clock_tick | 2.1 | 4.69 | 4.69 | 0 % |
| esc50 | cat | 1.5 | 6.49 | 1.95 | 70 % |
| esc50 | chirping_birds | 2.6 | 3.50 | 3.50 | 0 % |
| esc50 | hen | 2.5 | 3.61 | 2.41 | 33 % |
| esc50 | footsteps | 2.3 | 3.43 | 3.43 | 0 % |
| esc50 | glass_breaking | 1.1 | 7.44 | 7.44 | 0 % |
| esc50 | rain | 2.7 | 2.55 | 2.55 | 0 % |
| esc50 | laughing | 2.2 | 3.22 | 2.76 | 14 % |
| esc50 | crickets | 2.2 | 3.11 | 3.11 | 0 % |
| esc50 | frog | 2.4 | 2.50 | 2.50 | 0 % |
| esc50 | crackling_fire | 2.3 | 2.66 | 2.66 | 0 % |
| esc50 | door_wood_creaks | 2.2 | 2.69 | 1.79 | 33 % |
| esc50 | fireworks | 3.0 | 1.68 | 1.68 | 0 % |
| esc50 | chainsaw | 2.3 | 2.14 | 1.29 | 40 % |
| esc50 | water_drops | 1.6 | 3.04 | 3.04 | 0 % |
| esc50 | brushing_teeth | 2.2 | 2.30 | 2.30 | 0 % |
| esc50 | car_horn | 2.0 | 2.56 | 0.51 | 80 % |
| esc50 | snoring | 1.7 | 2.86 | 2.86 | 0 % |
| esc50 | pig | 2.9 | 1.75 | 1.40 | 20 % |
| esc50 | washing_machine | 2.6 | 1.89 | 1.89 | 0 % |
| esc50 | siren | 2.6 | 1.95 | 1.95 | 0 % |
| esc50 | keyboard_typing | 2.7 | 1.85 | 1.85 | 0 % |
| esc50 | dog | 2.1 | 1.92 | 1.92 | 0 % |
| esc50 | train | 2.5 | 1.60 | 1.60 | 0 % |
| esc50 | wind | 2.6 | 1.55 | 1.55 | 0 % |
| esc50 | hand_saw | 2.0 | 1.99 | 1.99 | 0 % |
| esc50 | drinking_sipping | 1.8 | 2.22 | 2.22 | 0 % |
| esc50 | crow | 2.2 | 1.39 | 1.39 | 0 % |
| esc50 | sheep | 2.6 | 1.18 | 0.78 | 33 % |
| esc50 | breathing | 1.8 | 1.67 | 1.67 | 0 % |
| esc50 | insects | 2.0 | 1.48 | 1.48 | 0 % |

Positives, TEST split: voiced events that fire their own action alone today, and the share the rule would silence (false rejects). Per speaker (>= 5 firing events): median / 90th percentile / worst.

| set | firing events | false rejects | per speaker: median / p90 / worst |
|---|---|---|---|
| MLEnd hum recordings | 9962 | 1.2 % | 0 % / 4 % / 27 % |
| MLEnd whistle recordings | 6596 | 0.4 % | 0 % / 1 % / 6 % |
| QBSH contour clips (as recorded) | 389 | 3.3 % | 0 % / 20 % / 38 % |

| user's recordings, voiced events | events | rule hits | firing today | firing and hit |
|---|---|---|---|---|
| hum | 46 | 0 | 37 | 0 |
| whistle | 40 | 0 | 32 | 0 |
| talk | 3 | 0 | 0 | 0 |
| meow | 7 | 0 | 4 | 0 |
| yell | 7 | 7 | 5 | 5 |

Variant without the thin E3.5 arm (E1k > 0.30 only):

#### E1k > 0.30 only

Negatives, TEST split, FA groups per minute before -> after:

| dataset | class | min | FA/min before | FA/min after | FAs removed |
|---|---|---|---|---|---|
| nonverbal | ALL | 20.4 | 1.13 | 0.98 | 13 % |
| nonverbal | screaming | 1.4 | 5.13 | 2.93 | 43 % |
| nonverbal | moaning | 1.6 | 1.91 | 1.91 | 0 % |
| nonverbal | teeth-chattering | 1.7 | 1.76 | 1.76 | 0 % |
| nonverbal | crying | 1.8 | 1.12 | 1.12 | 0 % |
| nonverbal | laughing | 1.7 | 0.00 | 0.00 | - |
| musan | ALL | 813.5 | 1.64 | 1.55 | 6 % |
| musan | music | 518.0 | 2.13 | 2.04 | 4 % |
| musan | speech | 295.5 | 0.79 | 0.68 | 13 % |
| nonspeech7k | ALL | 304.5 | 2.14 | 1.77 | 17 % |
| nonspeech7k | crying | 88.0 | 2.14 | 1.43 | 33 % |
| nonspeech7k | breath | 101.1 | 1.53 | 1.53 | 0 % |
| nonspeech7k | laugh | 50.2 | 2.33 | 2.07 | 11 % |
| nonspeech7k | screaming | 27.2 | 3.56 | 2.35 | 34 % |
| nonspeech7k | cough | 24.8 | 1.81 | 1.69 | 7 % |
| nonspeech7k | yawn | 6.7 | 4.48 | 4.48 | 0 % |
| nonspeech7k | sneeze | 6.3 | 3.31 | 3.00 | 10 % |
| esc50 | ALL | 109.6 | 2.39 | 2.04 | 15 % |
| esc50 | cow | 2.0 | 8.17 | 7.15 | 12 % |
| esc50 | rooster | 1.4 | 9.21 | 2.83 | 69 % |
| esc50 | mouse_click | 1.8 | 6.76 | 6.76 | 0 % |
| esc50 | can_opening | 1.4 | 7.02 | 7.02 | 0 % |
| esc50 | church_bells | 2.6 | 3.87 | 2.32 | 40 % |
| esc50 | clock_alarm | 2.1 | 4.75 | 3.80 | 20 % |
| esc50 | clock_tick | 2.1 | 4.69 | 4.69 | 0 % |
| esc50 | cat | 1.5 | 6.49 | 1.95 | 70 % |
| esc50 | chirping_birds | 2.6 | 3.50 | 3.50 | 0 % |
| esc50 | hen | 2.5 | 3.61 | 2.41 | 33 % |
| esc50 | footsteps | 2.3 | 3.43 | 3.43 | 0 % |
| esc50 | glass_breaking | 1.1 | 7.44 | 7.44 | 0 % |
| esc50 | rain | 2.7 | 2.55 | 2.55 | 0 % |
| esc50 | laughing | 2.2 | 3.22 | 2.76 | 14 % |
| esc50 | crickets | 2.2 | 3.11 | 3.11 | 0 % |
| esc50 | frog | 2.4 | 2.50 | 2.50 | 0 % |
| esc50 | crackling_fire | 2.3 | 2.66 | 2.66 | 0 % |
| esc50 | door_wood_creaks | 2.2 | 2.69 | 1.79 | 33 % |
| esc50 | fireworks | 3.0 | 1.68 | 1.68 | 0 % |
| esc50 | chainsaw | 2.3 | 2.14 | 1.29 | 40 % |
| esc50 | water_drops | 1.6 | 3.04 | 3.04 | 0 % |
| esc50 | brushing_teeth | 2.2 | 2.30 | 2.30 | 0 % |
| esc50 | car_horn | 2.0 | 2.56 | 0.51 | 80 % |
| esc50 | snoring | 1.7 | 2.86 | 2.86 | 0 % |
| esc50 | pig | 2.9 | 1.75 | 1.40 | 20 % |
| esc50 | washing_machine | 2.6 | 1.89 | 1.89 | 0 % |
| esc50 | siren | 2.6 | 1.95 | 1.95 | 0 % |
| esc50 | keyboard_typing | 2.7 | 1.85 | 1.85 | 0 % |
| esc50 | dog | 2.1 | 1.92 | 1.92 | 0 % |
| esc50 | train | 2.5 | 1.60 | 1.60 | 0 % |
| esc50 | wind | 2.6 | 1.55 | 1.55 | 0 % |
| esc50 | hand_saw | 2.0 | 1.99 | 1.99 | 0 % |
| esc50 | drinking_sipping | 1.8 | 2.22 | 2.22 | 0 % |
| esc50 | crow | 2.2 | 1.39 | 1.39 | 0 % |
| esc50 | sheep | 2.6 | 1.18 | 0.78 | 33 % |
| esc50 | breathing | 1.8 | 1.67 | 1.67 | 0 % |
| esc50 | insects | 2.0 | 1.48 | 1.48 | 0 % |

Positives, TEST split: voiced events that fire their own action alone today, and the share the rule would silence (false rejects). Per speaker (>= 5 firing events): median / 90th percentile / worst.

| set | firing events | false rejects | per speaker: median / p90 / worst |
|---|---|---|---|
| MLEnd hum recordings | 9962 | 1.1 % | 0 % / 3 % / 24 % |
| MLEnd whistle recordings | 6596 | 0.4 % | 0 % / 1 % / 6 % |
| QBSH contour clips (as recorded) | 389 | 2.3 % | 0 % / 14 % / 20 % |

| user's recordings, voiced events | events | rule hits | firing today | firing and hit |
|---|---|---|---|---|
| hum | 46 | 0 | 37 | 0 |
| whistle | 40 | 0 | 32 | 0 |
| talk | 3 | 0 | 0 | 0 |
| meow | 7 | 0 | 4 | 0 |
| yell | 7 | 6 | 5 | 5 |

## 3. Per-user pitch-range gate (evaluated only; not the fix)

Calibration = the median f0 of a speaker's first 5 voiced events of the same kind (files in name order); a later voiced sound is rejected if its median f0 is outside [min, max] of those 5, widened by the margin.

| held-out positives | margin | events | false rejects |
|---|---|---|---|
| MLEnd hum | +-2 st | 36549 | 23.8 % |
| MLEnd hum | +-4 st | 36549 | 11.8 % |
| MLEnd hum | +-6 st | 36549 | 6.3 % |
| MLEnd whistle | +-2 st | 17758 | 14.6 % |
| MLEnd whistle | +-4 st | 17758 | 5.5 % |
| MLEnd whistle | +-6 st | 17758 | 2.6 % |
| QBSH sung | +-2 st | 404 | 21.8 % |
| QBSH sung | +-4 st | 404 | 9.7 % |
| QBSH sung | +-6 st | 404 | 4.0 % |

User's recordings: calibrated on the first 5 hums (f0 87-183 Hz):

| margin | group | voiced events | rejected |
|---|---|---|---|
| +-2 st | hum | 38 | 10 |
| +-2 st | meow | 7 | 7 |
| +-2 st | yell | 7 | 3 |
| +-4 st | hum | 38 | 5 |
| +-4 st | meow | 7 | 7 |
| +-4 st | yell | 7 | 3 |
| +-6 st | hum | 38 | 2 |
| +-6 st | meow | 7 | 7 |
| +-6 st | yell | 7 | 3 |

## 4. Low-f0 hums tagged "talking"

| median f0 | hum / sung events | tagged talking | cues present in those (share) |
|---|---|---|---|
| 0-100 Hz | 719 | 35.5 % | broken voicing 72 %, consonant / formant changes 52 %, syllable-like loudness 51 % |
| 100-130 Hz | 3115 | 37.7 % | consonant / formant changes 59 %, syllable-like loudness 52 %, broken voicing 52 % |
| 130-160 Hz | 7429 | 40.8 % | consonant / formant changes 63 %, syllable-like loudness 59 %, broken voicing 49 % |
| 160-200 Hz | 8732 | 35.7 % | syllable-like loudness 60 %, consonant / formant changes 59 %, broken voicing 48 % |
| 200-250 Hz | 6159 | 33.2 % | syllable-like loudness 62 %, consonant / formant changes 57 %, broken voicing 47 % |
| 250-400 Hz | 10786 | 33.5 % | syllable-like loudness 64 %, consonant / formant changes 55 %, broken voicing 43 % |
| 400-600 Hz | 1539 | 25.4 % | syllable-like loudness 55 %, consonant / formant changes 41 %, broken voicing 32 % |
| 600-5000 Hz | 442 | 17.9 % | broken voicing 91 %, consonant / formant changes 57 %, syllable-like loudness 16 % |

