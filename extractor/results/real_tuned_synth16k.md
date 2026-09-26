# Synthetic evaluation (SYNTHETIC AUDIO ONLY: not evidence about real voices or mics)

clips: 1056; per cell: 12; SNRs: [30, 20, 10, 5]; backgrounds: ['white', 'pink', 'brown', 'cafe']; sample rate: 16000; seed: 20260926

## Label accuracy (gesture clips)

| | 30 dB | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| contour (hum + whistle) | 100.0 | 100.0 |  93.3 |  61.7 |
| contour, hum only | 100.0 | 100.0 |  93.3 |  61.7 |
| contour, whistle only | 100.0 | 100.0 |  93.3 |  61.7 |
| discrete (pop/click/hiss) |  88.9 |  75.0 |  47.2 |  36.1 |

### Per class

| | 30 dB | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| arch | 100.0 | 100.0 |  91.7 |  41.7 |
| click |  91.7 |  58.3 |  16.7 |  16.7 |
| dip | 100.0 | 100.0 | 100.0 |  58.3 |
| fall | 100.0 | 100.0 |  91.7 |  66.7 |
| flat | 100.0 | 100.0 | 100.0 |  66.7 |
| hiss | 100.0 | 100.0 | 100.0 |  75.0 |
| pop |  75.0 |  66.7 |  25.0 |  16.7 |
| rise | 100.0 | 100.0 |  83.3 |  75.0 |
| whistle_arch | 100.0 | 100.0 |  83.3 |  58.3 |
| whistle_dip | 100.0 | 100.0 | 100.0 |  66.7 |
| whistle_fall | 100.0 | 100.0 |  91.7 |  58.3 |
| whistle_flat | 100.0 | 100.0 | 100.0 |  50.0 |
| whistle_rise | 100.0 | 100.0 |  91.7 |  75.0 |

## End-to-end default action (grouped like the phone, not-deliberate gate applied)

A clip is right only if it yields exactly its default action and no other action (a lone click correctly yields none: it is unbound).

| | 30 dB | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| arch | 100.0 | 100.0 |  91.7 |  41.7 |
| click | 100.0 | 100.0 | 100.0 | 100.0 |
| click_pop |  66.7 |  58.3 |  16.7 |  16.7 |
| dip | 100.0 |  91.7 | 100.0 |  58.3 |
| fall | 100.0 | 100.0 |  91.7 |  66.7 |
| flat | 100.0 | 100.0 | 100.0 |  66.7 |
| hiss | 100.0 | 100.0 | 100.0 |  50.0 |
| pop |  75.0 |  66.7 |  25.0 |  16.7 |
| rise | 100.0 | 100.0 |  83.3 |  75.0 |
| whistle_arch |  91.7 | 100.0 |  83.3 |  58.3 |
| whistle_dip | 100.0 | 100.0 | 100.0 |  58.3 |
| whistle_fall | 100.0 | 100.0 |  91.7 |  58.3 |
| whistle_flat | 100.0 | 100.0 | 100.0 |  50.0 |
| whistle_rise | 100.0 | 100.0 |  91.7 |  75.0 |

## False accepts on negatives (any action other than none)

| | 30 dB | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| air |   0.0 |   0.0 |   0.0 |   0.0 |
| cough |   0.0 |   8.3 |   0.0 |   0.0 |
| fan_motor |   0.0 |   0.0 |   0.0 |   0.0 |
| laugh |   0.0 |   0.0 |   0.0 |   0.0 |
| music |   0.0 |   0.0 |   0.0 |   0.0 |
| silence |   0.0 |   8.3 |   0.0 |   0.0 |
| talk |   0.0 |   0.0 |   0.0 |   8.3 |
| talk_short |   0.0 |   0.0 |   0.0 |   0.0 |

Overall false-accept rate:   0.8 %

Actions triggered by negatives: {"cough": {"tap": 1}, "silence": {"swipe_left": 1}, "talk": {"long_press": 1}}

'Sounds like' emitted for negatives: 

- air: {"background noise": 38, "hum": 3}
- cough: {"coughing": 29, "background noise": 32, "hum": 8, "talking": 4, "mouth sound": 1}
- fan_motor: {"background noise": 26, "background music": 18, "hum": 1}
- laugh: {"laughing": 32, "coughing": 4, "talking": 34, "hum": 8}
- music: {"background music": 19, "background noise": 52, "hum": 5, "talking": 2}
- silence: {"hum": 9, "background noise": 2}
- talk: {"talking": 95, "laughing": 4, "hum": 35}
- talk_short: {"talking": 28, "hum": 19, "laughing": 2}

## Confusion matrix, all SNRs (rows = truth, columns = predicted label)

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 87 | 2 | 2 | 0 | 0 | 0 | 0 | 0 | 5 |
| fall | 1 | 85 | 1 | 2 | 0 | 0 | 0 | 0 | 7 |
| arch | 2 | 6 | 81 | 0 | 2 | 0 | 0 | 0 | 5 |
| dip | 2 | 1 | 0 | 87 | 1 | 0 | 0 | 0 | 5 |
| flat | 2 | 0 | 0 | 1 | 86 | 0 | 0 | 0 | 7 |
| pop | 0 | 0 | 0 | 0 | 0 | 22 | 0 | 3 | 23 |
| click | 0 | 1 | 0 | 0 | 1 | 0 | 22 | 1 | 23 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 45 | 3 |

### Confusion at 5 dB

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 18 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 5 |
| fall | 1 | 15 | 1 | 0 | 0 | 0 | 0 | 0 | 7 |
| arch | 2 | 3 | 12 | 0 | 2 | 0 | 0 | 0 | 5 |
| dip | 2 | 1 | 0 | 15 | 1 | 0 | 0 | 0 | 5 |
| flat | 2 | 0 | 0 | 1 | 14 | 0 | 0 | 0 | 7 |
| pop | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 1 | 9 |
| click | 0 | 0 | 0 | 0 | 1 | 0 | 2 | 0 | 9 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 9 | 3 |

### Confusion at 10 dB

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 21 | 1 | 2 | 0 | 0 | 0 | 0 | 0 | 0 |
| fall | 0 | 22 | 0 | 2 | 0 | 0 | 0 | 0 | 0 |
| arch | 0 | 3 | 21 | 0 | 0 | 0 | 0 | 0 | 0 |
| dip | 0 | 0 | 0 | 24 | 0 | 0 | 0 | 0 | 0 |
| flat | 0 | 0 | 0 | 0 | 24 | 0 | 0 | 0 | 0 |
| pop | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 1 | 8 |
| click | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 9 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 12 | 0 |

### Confusion at 20 dB

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| fall | 0 | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| arch | 0 | 0 | 24 | 0 | 0 | 0 | 0 | 0 | 0 |
| dip | 0 | 0 | 0 | 24 | 0 | 0 | 0 | 0 | 0 |
| flat | 0 | 0 | 0 | 0 | 24 | 0 | 0 | 0 | 0 |
| pop | 0 | 0 | 0 | 0 | 0 | 8 | 0 | 1 | 3 |
| click | 0 | 1 | 0 | 0 | 0 | 0 | 7 | 0 | 4 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 12 | 0 |

### Confusion at 30 dB

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| fall | 0 | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| arch | 0 | 0 | 24 | 0 | 0 | 0 | 0 | 0 | 0 |
| dip | 0 | 0 | 0 | 24 | 0 | 0 | 0 | 0 | 0 |
| flat | 0 | 0 | 0 | 0 | 24 | 0 | 0 | 0 | 0 |
| pop | 0 | 0 | 0 | 0 | 0 | 9 | 0 | 0 | 3 |
| click | 0 | 0 | 0 | 0 | 0 | 0 | 11 | 0 | 1 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 12 | 0 |

## Buckets and timing

- excursion bucket accuracy (hums/whistles with a correct contour label):  94.9 %
- duration bucket accuracy:  95.8 %
- hum clips called 'hum':  94.2 %; whistle clips called 'whistle':  91.2 %
- t_end error, all matched events: {"median": -7.099999999999909, "mean_abs": 29.97966386554622, "p90_abs": 56.12000000000001} (ms; negative = reported early)
- t_start error, all matched events: {"median": 4.899999999999977, "mean_abs": 17.08773109243697, "p90_abs": 24.700000000000045} (ms)

| sound@SNR | n | median t_end err | mean abs | p90 abs |
|---|---|---|---|---|
| arch@5 | 19 | -22 | 47 | 89 |
| arch@10 | 24 | -17 | 44 | 62 |
| arch@20 | 24 | -6 | 11 | 17 |
| arch@30 | 24 | -3 | 31 | 38 |
| click@5 | 5 | -2 | 32 | 82 |
| click@10 | 6 | -1 | 33 | 94 |
| click@20 | 19 | -2 | 35 | 43 |
| click@30 | 23 | -3 | 11 | 13 |
| dip@5 | 19 | -15 | 21 | 31 |
| dip@10 | 24 | -17 | 19 | 34 |
| dip@20 | 24 | -7 | 54 | 18 |
| dip@30 | 24 | -2 | 15 | 55 |
| fall@5 | 17 | -25 | 29 | 56 |
| fall@10 | 24 | -13 | 51 | 80 |
| fall@20 | 24 | -6 | 23 | 66 |
| fall@30 | 24 | -3 | 4 | 9 |
| flat@5 | 17 | -19 | 28 | 48 |
| flat@10 | 24 | -15 | 23 | 51 |
| flat@20 | 24 | -6 | 30 | 60 |
| flat@30 | 24 | -4 | 36 | 12 |
| hiss@5 | 9 | -24 | 29 | 53 |
| hiss@10 | 12 | -27 | 31 | 36 |
| hiss@20 | 12 | -11 | 35 | 20 |
| hiss@30 | 12 | -6 | 12 | 23 |
| pop@5 | 5 | -6 | 21 | 32 |
| pop@10 | 7 | 10 | 29 | 53 |
| pop@20 | 17 | -8 | 49 | 51 |
| pop@30 | 17 | -0 | 22 | 62 |
| rise@5 | 19 | -18 | 84 | 218 |
| rise@10 | 24 | -17 | 33 | 79 |
| rise@20 | 24 | -9 | 21 | 45 |
| rise@30 | 24 | -5 | 23 | 82 |

## Line validity

- lines emitted: 1116; strict-parser or label errors: 0
- valid but off the training distribution: {"hum over 1 s that is not a deliberate flat hum": 87, "very short hum that sounds like talking": 44, "very short hiss": 26, "non-flat hum with small pitch change that sounds like talking": 18, "non-flat hum with small pitch change that sounds like coughing": 1, "non-flat hum with small pitch change that sounds like laughing": 1, "very short hum that sounds like coughing": 1, "loud background / long hiss (generate.py makes those quiet or normal)": 8, "hum line sounds like background noise": 14, "other unseen combination": 3}
- extra events on single-gesture clips: 9
- Python real-time factor (processing time / audio time, this workstation): 0.013
