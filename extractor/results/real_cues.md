# REAL audio: cue analysis (frozen code)

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

| cue | speech (15125/426) | yell (1002/212) | cat (85/27) | crying (5418/1052) | laughing (2714/298) | moaning (64/33) | music (9420/93) | whistle (18936/128) | live meow (7/1) | live yell (7/1) | mean sep |
|---|---|---|---|---|---|---|---|---|---|---|---|
| logmel0 | 0.76 (0.69) | 1.00 (0.99) | 1.00 (0.99) | 0.96 (0.94) | 0.99 (0.96) | 0.91 (0.85) | 0.87 (0.72) | 1.00 (0.99) | (1.00) | (0.99) | 0.94 |
| zcr | 0.10 (0.18) | 0.00 (0.02) | 0.00 (0.01) | 0.06 (0.08) | 0.02 (0.06) | 0.22 (0.28) | 0.13 (0.28) | 0.00 (0.02) | (0.05) | (0.01) | 0.94 |
| centroid_hz | 0.11 (0.18) | 0.00 (0.02) | 0.00 (0.01) | 0.06 (0.08) | 0.02 (0.06) | 0.22 (0.28) | 0.20 (0.34) | 0.00 (0.01) | (0.00) | (0.00) | 0.93 |
| lf_ratio | 0.90 (0.83) | 0.99 (0.98) | 1.00 (0.99) | 0.93 (0.88) | 0.97 (0.92) | 0.81 (0.74) | 0.85 (0.72) | 0.99 (0.98) | (0.97) | (0.94) | 0.93 |
| e1k | 0.10 (0.17) | 0.01 (0.02) | 0.00 (0.01) | 0.07 (0.12) | 0.04 (0.08) | 0.20 (0.27) | 0.17 (0.30) | 0.01 (0.02) | (0.03) | (0.06) | 0.92 |
| voiced_frac | 0.99 (0.82) | 0.91 (0.87) | 0.92 (0.73) | 0.96 (0.85) | 0.99 (0.91) | 0.99 (0.91) | 1.00 (0.91) | 0.27 (0.42) | (0.40) | (0.86) | 0.92 |
| peak_centroid_hz | 0.13 (0.21) | 0.01 (0.04) | 0.00 (0.02) | 0.08 (0.10) | 0.04 (0.10) | 0.30 (0.34) | 0.36 (0.43) | 0.01 (0.03) | (0.01) | (0.01) | 0.90 |
| clarity_med | 1.00 (0.94) | 0.90 (0.91) | 0.95 (0.85) | 0.95 (0.92) | 1.00 (0.96) | 0.98 (0.93) | 1.00 (0.95) | 0.30 (0.38) | (0.33) | (0.59) | 0.89 |
| mfcc1 | 0.50 (0.41) | 0.99 (0.97) | 0.99 (0.96) | 0.95 (0.93) | 0.97 (0.95) | 0.89 (0.82) | 0.73 (0.59) | 0.96 (0.91) | (1.00) | (0.92) | 0.88 |
| hf_ratio | 0.24 (0.33) | 0.05 (0.10) | 0.06 (0.15) | 0.09 (0.12) | 0.05 (0.09) | 0.15 (0.22) | 0.16 (0.33) | 0.73 (0.69) | (0.12) | (0.19) | 0.88 |
| strong_voiced_frac | 0.97 (0.82) | 0.92 (0.87) | 0.75 (0.63) | 0.94 (0.81) | 0.96 (0.88) | 0.89 (0.83) | 1.00 (0.95) | 0.45 (0.41) | (0.30) | (0.75) | 0.88 |
| flatness | 0.41 (0.49) | 0.07 (0.08) | 0.08 (0.16) | 0.07 (0.12) | 0.03 (0.06) | 0.10 (0.18) | 0.10 (0.27) | 0.66 (0.64) | (0.19) | (0.14) | 0.87 |
| mfcc3 | 0.38 (0.35) | 0.94 (0.88) | 0.89 (0.81) | 0.89 (0.86) | 0.88 (0.83) | 0.87 (0.80) | 0.73 (0.66) | 0.87 (0.80) | (0.92) | (0.98) | 0.86 |
| flux_mean_db | 0.27 (0.34) | 0.22 (0.33) | 0.20 (0.24) | 0.06 (0.13) | 0.09 (0.13) | 0.07 (0.15) | 0.86 (0.78) | 0.33 (0.38) | (0.65) | (0.04) | 0.84 |
| f0_med_hz | 0.76 (0.73) | 0.06 (0.07) | 0.02 (0.03) | 0.09 (0.10) | 0.10 (0.12) | 0.38 (0.36) | 0.64 (0.64) | 0.00 (0.01) | (0.00) | (0.20) | 0.84 |
| mfcc2 | 0.76 (0.78) | 0.97 (0.95) | 0.91 (0.91) | 0.89 (0.86) | 0.90 (0.85) | 0.57 (0.57) | 0.60 (0.60) | 0.97 (0.94) | (1.00) | (0.94) | 0.84 |
| voiced_runs | 0.08 (0.29) | 0.17 (0.26) | 0.30 (0.46) | 0.13 (0.32) | 0.05 (0.22) | 0.17 (0.34) | 0.10 (0.31) | 0.58 (0.53) | (0.52) | (0.22) | 0.81 |
| mfcc0 | 0.21 (0.24) | 0.12 (0.16) | 0.20 (0.23) | 0.39 (0.32) | 0.21 (0.28) | 0.53 (0.54) | 0.04 (0.11) | 0.66 (0.61) | (0.08) | (0.00) | 0.81 |
| e35f0 | 0.03 (0.10) | 0.39 (0.40) | 0.14 (0.23) | 0.24 (0.29) | 0.17 (0.26) | 0.24 (0.33) | 0.11 (0.26) | 0.99 (0.97) | (0.71) | (0.16) | 0.80 |
| logmel7 | 0.61 (0.67) | 0.12 (0.23) | 0.09 (0.19) | 0.17 (0.17) | 0.14 (0.17) | 0.13 (0.18) | 0.29 (0.43) | 0.45 (0.45) | (0.10) | (0.43) | 0.79 |
| logmel3 | 0.31 (0.31) | 0.07 (0.12) | 0.08 (0.09) | 0.23 (0.33) | 0.22 (0.28) | 0.40 (0.38) | 0.43 (0.41) | 0.07 (0.09) | (0.10) | (0.03) | 0.79 |
| logmel4 | 0.14 (0.21) | 0.08 (0.12) | 0.14 (0.13) | 0.15 (0.21) | 0.11 (0.22) | 0.42 (0.42) | 0.33 (0.40) | 0.18 (0.25) | (0.57) | (0.12) | 0.79 |
| logmel1 | 0.43 (0.40) | 0.93 (0.89) | 0.89 (0.86) | 0.78 (0.76) | 0.87 (0.81) | 0.80 (0.75) | 0.69 (0.57) | 0.98 (0.95) | (0.39) | (0.85) | 0.78 |
| energy_iqr_db | 0.14 (0.33) | 0.50 (0.51) | 0.21 (0.30) | 0.07 (0.27) | 0.07 (0.22) | 0.01 (0.15) | 0.90 (0.69) | 0.06 (0.28) | (0.45) | (0.48) | 0.77 |
| pitch_rough_st | 0.00 (0.13) | 0.36 (0.27) | 0.42 (0.44) | 0.14 (0.23) | 0.01 (0.13) | 0.07 (0.18) | 0.41 (0.51) | 0.86 (0.70) | (0.75) | (0.55) | 0.76 |
| centroid_spread_oct | 0.09 (0.24) | 0.53 (0.55) | 0.22 (0.36) | 0.20 (0.35) | 0.28 (0.33) | 0.07 (0.17) | 0.36 (0.48) | 0.91 (0.76) | (0.11) | (0.33) | 0.76 |
| logmel5 | 0.13 (0.20) | 0.09 (0.15) | 0.15 (0.19) | 0.20 (0.24) | 0.18 (0.21) | 0.54 (0.56) | 0.38 (0.46) | 0.50 (0.48) | (0.36) | (0.16) | 0.76 |
| decay_db | 0.57 (0.55) | 0.34 (0.52) | 0.20 (0.31) | 0.16 (0.35) | 0.39 (0.41) | 0.06 (0.18) | 0.98 (0.81) | 0.29 (0.41) | (0.66) | (0.19) | 0.76 |
| syllable_rate_hz | 0.24 (0.39) | 0.74 (0.62) | 0.66 (0.55) | 0.17 (0.35) | 0.15 (0.29) | 0.42 (0.43) | 0.98 (0.77) | 0.02 (0.24) | (0.15) | (0.40) | 0.76 |
| hnr_db | 0.96 (0.84) | 0.63 (0.65) | 0.49 (0.50) | 0.65 (0.65) | 0.82 (0.71) | 0.63 (0.59) | 0.90 (0.73) | 0.02 (0.07) | (0.03) | (0.40) | 0.74 |
| logmel6 | 0.32 (0.38) | 0.11 (0.20) | 0.27 (0.36) | 0.23 (0.26) | 0.16 (0.20) | 0.30 (0.32) | 0.36 (0.47) | 0.63 (0.58) | (0.27) | (0.37) | 0.74 |
| pitch_jumps_hz | 0.30 (0.35) | 0.18 (0.22) | 0.26 (0.34) | 0.27 (0.32) | 0.16 (0.25) | 0.22 (0.32) | 0.20 (0.29) | 0.49 (0.53) | (0.55) | (0.42) | 0.73 |
| onset_flux_db | 0.30 (0.40) | 0.42 (0.52) | 0.37 (0.39) | 0.19 (0.29) | 0.24 (0.31) | 0.39 (0.41) | 0.82 (0.72) | 0.65 (0.57) | (0.56) | (0.04) | 0.71 |
| mfcc4 | 0.73 (0.70) | 0.67 (0.69) | 0.54 (0.48) | 0.78 (0.74) | 0.76 (0.70) | 0.48 (0.49) | 0.59 (0.58) | 0.21 (0.26) | (0.94) | (0.87) | 0.71 |
| logmel2 | 0.39 (0.40) | 0.20 (0.21) | 0.28 (0.29) | 0.43 (0.37) | 0.35 (0.38) | 0.36 (0.40) | 0.34 (0.33) | 0.25 (0.35) | (0.56) | (0.06) | 0.68 |
| pitch_resid_std_st | 0.29 (0.38) | 0.23 (0.26) | 0.31 (0.38) | 0.45 (0.41) | 0.18 (0.31) | 0.30 (0.35) | 0.32 (0.43) | 0.92 (0.71) | (0.72) | (0.50) | 0.68 |
| mfcc7 | 0.61 (0.65) | 0.34 (0.35) | 0.21 (0.27) | 0.41 (0.37) | 0.38 (0.40) | 0.30 (0.33) | 0.21 (0.30) | 0.62 (0.57) | (0.82) | (0.44) | 0.68 |
| mfcc11 | 0.22 (0.26) | 0.36 (0.33) | 0.24 (0.25) | 0.36 (0.36) | 0.39 (0.39) | 0.47 (0.52) | 0.30 (0.34) | 0.26 (0.36) | (0.12) | (0.58) | 0.68 |
| f0_range_st | 0.29 (0.38) | 0.21 (0.27) | 0.37 (0.39) | 0.47 (0.43) | 0.20 (0.32) | 0.27 (0.33) | 0.41 (0.47) | 0.92 (0.71) | (0.82) | (0.51) | 0.68 |
| syllable_peaks | 0.43 (0.49) | 0.64 (0.61) | 0.59 (0.57) | 0.33 (0.48) | 0.27 (0.42) | 0.36 (0.47) | 0.97 (0.76) | 0.36 (0.44) | (0.41) | (0.35) | 0.67 |
| dur_ms | 0.72 (0.61) | 0.37 (0.50) | 0.54 (0.53) | 0.69 (0.61) | 0.59 (0.58) | 0.40 (0.52) | 0.82 (0.65) | 0.83 (0.63) | (0.81) | (0.42) | 0.66 |
| mfcc5 | 0.84 (0.77) | 0.43 (0.49) | 0.66 (0.63) | 0.82 (0.75) | 0.66 (0.63) | 0.52 (0.48) | 0.54 (0.51) | 0.16 (0.23) | (0.74) | (0.62) | 0.66 |
| mfcc12 | 0.60 (0.61) | 0.37 (0.42) | 0.45 (0.41) | 0.41 (0.36) | 0.30 (0.37) | 0.35 (0.42) | 0.28 (0.39) | 0.41 (0.46) | (0.18) | (0.39) | 0.65 |
| mfcc10 | 0.43 (0.44) | 0.36 (0.37) | 0.27 (0.27) | 0.46 (0.46) | 0.40 (0.41) | 0.41 (0.42) | 0.31 (0.35) | 0.20 (0.30) | (0.23) | (0.30) | 0.65 |
| mfcc6 | 0.39 (0.37) | 0.41 (0.41) | 0.43 (0.43) | 0.75 (0.60) | 0.59 (0.54) | 0.53 (0.55) | 0.42 (0.42) | 0.48 (0.46) | (0.97) | (0.45) | 0.64 |
| mfcc9 | 0.49 (0.48) | 0.41 (0.44) | 0.25 (0.26) | 0.51 (0.51) | 0.42 (0.41) | 0.55 (0.58) | 0.40 (0.40) | 0.32 (0.39) | (0.12) | (0.31) | 0.63 |
| mfcc8 | 0.40 (0.40) | 0.56 (0.54) | 0.47 (0.46) | 0.70 (0.65) | 0.45 (0.49) | 0.48 (0.48) | 0.43 (0.46) | 0.64 (0.58) | (0.35) | (0.27) | 0.60 |

Hum reference: 38897 events from 226 MLEnd speakers; live hums: 22 events.

## 2. Brightness rule (hypothesis, not in the extractor)

#### E1k > 0.30 or E3.5 > 0.85, f0 < 900 Hz

Negatives, TEST split, FA groups per minute before -> after:

| dataset | class | min | FA/min before | FA/min after | FAs removed |
|---|---|---|---|---|---|
| nonverbal | ALL | 20.4 | 1.76 | 1.52 | 14 % |
| nonverbal | screaming | 1.4 | 10.27 | 6.60 | 36 % |
| nonverbal | moaning | 1.6 | 2.55 | 2.55 | 0 % |
| nonverbal | laughing | 1.7 | 1.74 | 1.74 | 0 % |
| nonverbal | panting | 1.5 | 2.04 | 2.04 | 0 % |
| nonverbal | teeth-chattering | 1.7 | 1.76 | 1.76 | 0 % |
| nonverbal | crying | 1.8 | 1.12 | 1.12 | 0 % |
| musan | ALL | 813.5 | 1.79 | 1.64 | 9 % |
| musan | music | 518.0 | 2.29 | 2.15 | 6 % |
| musan | speech | 295.5 | 0.92 | 0.74 | 20 % |
| nonspeech7k | ALL | 304.5 | 2.37 | 1.96 | 17 % |
| nonspeech7k | crying | 88.0 | 2.44 | 1.62 | 33 % |
| nonspeech7k | breath | 101.1 | 1.60 | 1.60 | 0 % |
| nonspeech7k | laugh | 50.2 | 2.75 | 2.53 | 8 % |
| nonspeech7k | screaming | 27.2 | 3.74 | 2.42 | 35 % |
| nonspeech7k | cough | 24.8 | 2.09 | 1.97 | 6 % |
| nonspeech7k | yawn | 6.7 | 4.63 | 4.63 | 0 % |
| nonspeech7k | sneeze | 6.3 | 3.31 | 3.15 | 5 % |
| esc50 | ALL | 109.6 | 2.63 | 2.24 | 15 % |
| esc50 | cow | 2.0 | 8.17 | 7.15 | 12 % |
| esc50 | rooster | 1.4 | 9.92 | 4.25 | 57 % |
| esc50 | mouse_click | 1.8 | 6.76 | 6.76 | 0 % |
| esc50 | can_opening | 1.4 | 7.72 | 7.72 | 0 % |
| esc50 | hen | 2.5 | 4.41 | 2.41 | 45 % |
| esc50 | cat | 1.5 | 7.14 | 1.95 | 73 % |
| esc50 | chirping_birds | 2.6 | 3.89 | 3.89 | 0 % |
| esc50 | church_bells | 2.6 | 3.87 | 1.55 | 60 % |
| esc50 | clock_tick | 2.1 | 4.69 | 4.69 | 0 % |
| esc50 | glass_breaking | 1.1 | 8.37 | 8.37 | 0 % |
| esc50 | clock_alarm | 2.1 | 3.80 | 2.85 | 25 % |
| esc50 | footsteps | 2.3 | 3.43 | 3.43 | 0 % |
| esc50 | frog | 2.4 | 3.33 | 3.33 | 0 % |
| esc50 | rain | 2.7 | 2.91 | 2.91 | 0 % |
| esc50 | water_drops | 1.6 | 4.25 | 4.25 | 0 % |
| esc50 | keyboard_typing | 2.7 | 2.60 | 2.60 | 0 % |
| esc50 | crackling_fire | 2.3 | 2.66 | 2.66 | 0 % |
| esc50 | laughing | 2.2 | 2.76 | 2.30 | 17 % |
| esc50 | hand_saw | 2.0 | 2.99 | 2.99 | 0 % |
| esc50 | pig | 2.9 | 2.10 | 1.75 | 17 % |
| esc50 | washing_machine | 2.6 | 2.27 | 2.27 | 0 % |
| esc50 | door_wood_creaks | 2.2 | 2.69 | 1.79 | 33 % |
| esc50 | crickets | 2.2 | 2.67 | 2.67 | 0 % |
| esc50 | dog | 2.1 | 2.41 | 2.41 | 0 % |
| esc50 | chainsaw | 2.3 | 2.14 | 1.29 | 40 % |
| esc50 | brushing_teeth | 2.2 | 2.30 | 2.30 | 0 % |
| esc50 | car_horn | 2.0 | 2.56 | 0.51 | 80 % |
| esc50 | insects | 2.0 | 2.47 | 2.47 | 0 % |
| esc50 | snoring | 1.7 | 2.86 | 2.86 | 0 % |
| esc50 | crow | 2.2 | 1.86 | 1.86 | 0 % |
| esc50 | fireworks | 3.0 | 1.35 | 1.35 | 0 % |
| esc50 | train | 2.5 | 1.60 | 1.60 | 0 % |
| esc50 | wind | 2.6 | 1.55 | 1.55 | 0 % |
| esc50 | crying_baby | 2.5 | 1.63 | 1.63 | 0 % |
| esc50 | siren | 2.6 | 1.56 | 1.56 | 0 % |
| esc50 | drinking_sipping | 1.8 | 2.22 | 2.22 | 0 % |
| esc50 | sheep | 2.6 | 1.18 | 0.78 | 33 % |
| esc50 | breathing | 1.8 | 1.67 | 1.67 | 0 % |
| esc50 | toilet_flush | 2.6 | 1.16 | 1.16 | 0 % |
| esc50 | engine | 2.3 | 1.33 | 1.33 | 0 % |
| esc50 | pouring_water | 2.2 | 1.36 | 1.36 | 0 % |

Positives, TEST split: voiced events that fire their own action alone today, and the share the rule would silence (false rejects). Per speaker (>= 5 firing events): median / 90th percentile / worst.

| set | firing events | false rejects | per speaker: median / p90 / worst |
|---|---|---|---|
| MLEnd hum recordings | 10704 | 1.2 % | 0 % / 3 % / 26 % |
| MLEnd whistle recordings | 6891 | 0.4 % | 0 % / 1 % / 6 % |
| QBSH contour clips (as recorded) | 394 | 3.3 % | 0 % / 20 % / 38 % |

| user's recordings, voiced events | events | rule hits | firing today | firing and hit |
|---|---|---|---|---|
| hum | 23 | 0 | 19 | 0 |
| whistle | 29 | 0 | 24 | 0 |
| talk | 3 | 0 | 0 | 0 |
| meow | 7 | 0 | 4 | 0 |
| yell | 7 | 7 | 5 | 5 |

Variant without the thin E3.5 arm (E1k > 0.30 only):

#### E1k > 0.30 only

Negatives, TEST split, FA groups per minute before -> after:

| dataset | class | min | FA/min before | FA/min after | FAs removed |
|---|---|---|---|---|---|
| nonverbal | ALL | 20.4 | 1.76 | 1.52 | 14 % |
| nonverbal | screaming | 1.4 | 10.27 | 6.60 | 36 % |
| nonverbal | moaning | 1.6 | 2.55 | 2.55 | 0 % |
| nonverbal | laughing | 1.7 | 1.74 | 1.74 | 0 % |
| nonverbal | panting | 1.5 | 2.04 | 2.04 | 0 % |
| nonverbal | teeth-chattering | 1.7 | 1.76 | 1.76 | 0 % |
| nonverbal | crying | 1.8 | 1.12 | 1.12 | 0 % |
| musan | ALL | 813.5 | 1.79 | 1.69 | 6 % |
| musan | music | 518.0 | 2.29 | 2.19 | 4 % |
| musan | speech | 295.5 | 0.92 | 0.82 | 12 % |
| nonspeech7k | ALL | 304.5 | 2.37 | 1.97 | 17 % |
| nonspeech7k | crying | 88.0 | 2.44 | 1.65 | 33 % |
| nonspeech7k | breath | 101.1 | 1.60 | 1.60 | 0 % |
| nonspeech7k | laugh | 50.2 | 2.75 | 2.53 | 8 % |
| nonspeech7k | screaming | 27.2 | 3.74 | 2.42 | 35 % |
| nonspeech7k | cough | 24.8 | 2.09 | 1.97 | 6 % |
| nonspeech7k | yawn | 6.7 | 4.63 | 4.63 | 0 % |
| nonspeech7k | sneeze | 6.3 | 3.31 | 3.15 | 5 % |
| esc50 | ALL | 109.6 | 2.63 | 2.26 | 14 % |
| esc50 | cow | 2.0 | 8.17 | 7.15 | 12 % |
| esc50 | rooster | 1.4 | 9.92 | 4.25 | 57 % |
| esc50 | mouse_click | 1.8 | 6.76 | 6.76 | 0 % |
| esc50 | can_opening | 1.4 | 7.72 | 7.72 | 0 % |
| esc50 | hen | 2.5 | 4.41 | 2.41 | 45 % |
| esc50 | cat | 1.5 | 7.14 | 1.95 | 73 % |
| esc50 | chirping_birds | 2.6 | 3.89 | 3.89 | 0 % |
| esc50 | church_bells | 2.6 | 3.87 | 2.32 | 40 % |
| esc50 | clock_tick | 2.1 | 4.69 | 4.69 | 0 % |
| esc50 | glass_breaking | 1.1 | 8.37 | 8.37 | 0 % |
| esc50 | clock_alarm | 2.1 | 3.80 | 2.85 | 25 % |
| esc50 | footsteps | 2.3 | 3.43 | 3.43 | 0 % |
| esc50 | frog | 2.4 | 3.33 | 3.33 | 0 % |
| esc50 | rain | 2.7 | 2.91 | 2.91 | 0 % |
| esc50 | water_drops | 1.6 | 4.25 | 4.25 | 0 % |
| esc50 | keyboard_typing | 2.7 | 2.60 | 2.60 | 0 % |
| esc50 | crackling_fire | 2.3 | 2.66 | 2.66 | 0 % |
| esc50 | laughing | 2.2 | 2.76 | 2.30 | 17 % |
| esc50 | hand_saw | 2.0 | 2.99 | 2.99 | 0 % |
| esc50 | pig | 2.9 | 2.10 | 1.75 | 17 % |
| esc50 | washing_machine | 2.6 | 2.27 | 2.27 | 0 % |
| esc50 | door_wood_creaks | 2.2 | 2.69 | 1.79 | 33 % |
| esc50 | crickets | 2.2 | 2.67 | 2.67 | 0 % |
| esc50 | dog | 2.1 | 2.41 | 2.41 | 0 % |
| esc50 | chainsaw | 2.3 | 2.14 | 1.29 | 40 % |
| esc50 | brushing_teeth | 2.2 | 2.30 | 2.30 | 0 % |
| esc50 | car_horn | 2.0 | 2.56 | 0.51 | 80 % |
| esc50 | insects | 2.0 | 2.47 | 2.47 | 0 % |
| esc50 | snoring | 1.7 | 2.86 | 2.86 | 0 % |
| esc50 | crow | 2.2 | 1.86 | 1.86 | 0 % |
| esc50 | fireworks | 3.0 | 1.35 | 1.35 | 0 % |
| esc50 | train | 2.5 | 1.60 | 1.60 | 0 % |
| esc50 | wind | 2.6 | 1.55 | 1.55 | 0 % |
| esc50 | crying_baby | 2.5 | 1.63 | 1.63 | 0 % |
| esc50 | siren | 2.6 | 1.56 | 1.56 | 0 % |
| esc50 | drinking_sipping | 1.8 | 2.22 | 2.22 | 0 % |
| esc50 | sheep | 2.6 | 1.18 | 0.78 | 33 % |
| esc50 | breathing | 1.8 | 1.67 | 1.67 | 0 % |
| esc50 | toilet_flush | 2.6 | 1.16 | 1.16 | 0 % |
| esc50 | engine | 2.3 | 1.33 | 1.33 | 0 % |
| esc50 | pouring_water | 2.2 | 1.36 | 1.36 | 0 % |

Positives, TEST split: voiced events that fire their own action alone today, and the share the rule would silence (false rejects). Per speaker (>= 5 firing events): median / 90th percentile / worst.

| set | firing events | false rejects | per speaker: median / p90 / worst |
|---|---|---|---|
| MLEnd hum recordings | 10704 | 1.1 % | 0 % / 3 % / 23 % |
| MLEnd whistle recordings | 6891 | 0.4 % | 0 % / 1 % / 6 % |
| QBSH contour clips (as recorded) | 394 | 2.3 % | 0 % / 14 % / 20 % |

| user's recordings, voiced events | events | rule hits | firing today | firing and hit |
|---|---|---|---|---|
| hum | 23 | 0 | 19 | 0 |
| whistle | 29 | 0 | 24 | 0 |
| talk | 3 | 0 | 0 | 0 |
| meow | 7 | 0 | 4 | 0 |
| yell | 7 | 6 | 5 | 5 |

## 3. Per-user pitch-range gate (evaluated only; not the fix)

Calibration = the median f0 of a speaker's first 5 voiced events of the same kind (files in name order); a later voiced sound is rejected if its median f0 is outside [min, max] of those 5, widened by the margin.

| held-out positives | margin | events | false rejects |
|---|---|---|---|
| MLEnd hum | +-2 st | 37721 | 25.4 % |
| MLEnd hum | +-4 st | 37721 | 12.9 % |
| MLEnd hum | +-6 st | 37721 | 7.0 % |
| MLEnd whistle | +-2 st | 18279 | 15.1 % |
| MLEnd whistle | +-4 st | 18279 | 5.8 % |
| MLEnd whistle | +-6 st | 18279 | 2.8 % |
| QBSH sung | +-2 st | 390 | 21.3 % |
| QBSH sung | +-4 st | 390 | 9.2 % |
| QBSH sung | +-6 st | 390 | 3.8 % |

User's recordings: calibrated on the first 5 hums (f0 87-183 Hz):

| margin | group | voiced events | rejected |
|---|---|---|---|
| +-2 st | hum | 17 | 2 |
| +-2 st | meow | 7 | 7 |
| +-2 st | yell | 7 | 3 |
| +-4 st | hum | 17 | 2 |
| +-4 st | meow | 7 | 7 |
| +-4 st | yell | 7 | 3 |
| +-6 st | hum | 17 | 2 |
| +-6 st | meow | 7 | 7 |
| +-6 st | yell | 7 | 3 |

## 4. Low-f0 hums tagged "talking"

| median f0 | hum / sung events | tagged talking | cues present in those (share) |
|---|---|---|---|
| 0-100 Hz | 737 | 36.4 % | broken voicing 70 %, syllable-like loudness 52 %, consonant / formant changes 51 % |
| 100-130 Hz | 3225 | 37.5 % | consonant / formant changes 58 %, broken voicing 52 %, syllable-like loudness 52 % |
| 130-160 Hz | 7655 | 40.5 % | consonant / formant changes 63 %, syllable-like loudness 60 %, broken voicing 48 % |
| 160-200 Hz | 8941 | 35.7 % | syllable-like loudness 59 %, consonant / formant changes 58 %, broken voicing 46 % |
| 200-250 Hz | 6362 | 33.3 % | syllable-like loudness 61 %, consonant / formant changes 56 %, broken voicing 46 % |
| 250-400 Hz | 11086 | 33.3 % | syllable-like loudness 63 %, consonant / formant changes 55 %, broken voicing 41 % |
| 400-600 Hz | 1585 | 25.3 % | syllable-like loudness 55 %, consonant / formant changes 40 %, broken voicing 31 % |
| 600-5000 Hz | 455 | 17.8 % | broken voicing 91 %, consonant / formant changes 57 %, syllable-like loudness 16 % |

