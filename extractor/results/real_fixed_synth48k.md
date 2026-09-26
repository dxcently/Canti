# Synthetic evaluation (SYNTHETIC AUDIO ONLY: not evidence about real voices or mics)

clips: 528; per cell: 6; SNRs: [30, 20, 10, 5]; backgrounds: ['white', 'pink', 'brown', 'cafe']; sample rate: 48000; seed: 20260926

## Label accuracy (gesture clips)

| | 30 dB | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| contour (hum + whistle) | 100.0 | 100.0 |  95.0 |  88.3 |
| contour, hum only | 100.0 | 100.0 |  93.3 |  86.7 |
| contour, whistle only | 100.0 | 100.0 |  96.7 |  90.0 |
| discrete (pop/click/hiss) | 100.0 | 100.0 |  77.8 |  61.1 |

### Per class

| | 30 dB | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| arch | 100.0 | 100.0 |  83.3 |  83.3 |
| click | 100.0 | 100.0 |  50.0 |  16.7 |
| dip | 100.0 | 100.0 | 100.0 |  83.3 |
| fall | 100.0 | 100.0 | 100.0 | 100.0 |
| flat | 100.0 | 100.0 | 100.0 |  83.3 |
| hiss | 100.0 | 100.0 | 100.0 | 100.0 |
| pop | 100.0 | 100.0 |  83.3 |  66.7 |
| rise | 100.0 | 100.0 |  83.3 |  83.3 |
| whistle_arch | 100.0 | 100.0 | 100.0 | 100.0 |
| whistle_dip | 100.0 | 100.0 | 100.0 |  83.3 |
| whistle_fall | 100.0 | 100.0 | 100.0 |  83.3 |
| whistle_flat | 100.0 | 100.0 |  83.3 |  83.3 |
| whistle_rise | 100.0 | 100.0 | 100.0 | 100.0 |

## End-to-end default action (grouped like the phone, not-deliberate gate applied)

A clip is right only if it yields exactly its default action and no other action (a lone click correctly yields none: it is unbound).

| | 30 dB | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| arch | 100.0 | 100.0 |  66.7 |  66.7 |
| click | 100.0 | 100.0 | 100.0 | 100.0 |
| click_pop | 100.0 |  83.3 |  83.3 |  16.7 |
| dip | 100.0 | 100.0 | 100.0 |  83.3 |
| fall | 100.0 | 100.0 | 100.0 | 100.0 |
| flat | 100.0 |  83.3 | 100.0 |  83.3 |
| hiss | 100.0 | 100.0 | 100.0 |  83.3 |
| pop | 100.0 | 100.0 |  83.3 |  66.7 |
| rise | 100.0 | 100.0 |  83.3 |  83.3 |
| whistle_arch |  83.3 | 100.0 | 100.0 | 100.0 |
| whistle_dip | 100.0 | 100.0 | 100.0 |  83.3 |
| whistle_fall | 100.0 | 100.0 | 100.0 |  83.3 |
| whistle_flat | 100.0 | 100.0 |  83.3 |  83.3 |
| whistle_rise | 100.0 | 100.0 | 100.0 |  83.3 |

## False accepts on negatives (any action other than none)

| | 30 dB | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| air |   0.0 |   0.0 |   0.0 |   0.0 |
| cough |   0.0 |   0.0 |   0.0 |   0.0 |
| fan_motor |   0.0 |  16.7 |   0.0 |   0.0 |
| laugh |   0.0 |   0.0 |   0.0 |   0.0 |
| music |   0.0 |   0.0 |   0.0 |   0.0 |
| silence |   0.0 |   0.0 |   0.0 |   0.0 |
| talk |   0.0 |   0.0 |   0.0 |  16.7 |
| talk_short |  16.7 |   0.0 |  16.7 |   0.0 |

Overall false-accept rate:   2.1 %

Actions triggered by negatives: {"fan_motor": {"swipe_up": 1}, "talk": {"swipe_down": 1}, "talk_short": {"swipe_down": 2}}

'Sounds like' emitted for negatives: 

- air: {"background noise": 19, "hum": 2}
- cough: {"coughing": 15, "hum": 3, "talking": 3, "background noise": 19, "mouth sound": 2}
- fan_motor: {"background noise": 14, "background music": 9, "hum": 1}
- laugh: {"laughing": 21, "talking": 15, "hum": 1}
- music: {"background music": 11, "background noise": 20, "hum": 1}
- silence: {"hum": 4, "talking": 1, "background noise": 1}
- talk: {"talking": 45, "laughing": 1, "hum": 14}
- talk_short: {"hum": 13, "talking": 11}

## Confusion matrix, all SNRs (rows = truth, columns = predicted label)

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 46 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 |
| fall | 0 | 47 | 0 | 1 | 0 | 0 | 0 | 0 | 0 |
| arch | 0 | 2 | 46 | 0 | 0 | 0 | 0 | 0 | 0 |
| dip | 0 | 1 | 0 | 46 | 0 | 0 | 0 | 0 | 1 |
| flat | 0 | 0 | 0 | 3 | 45 | 0 | 0 | 0 | 0 |
| pop | 0 | 0 | 0 | 0 | 1 | 21 | 0 | 0 | 2 |
| click | 0 | 0 | 0 | 0 | 0 | 0 | 16 | 0 | 8 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 24 | 0 |

### Confusion at 5 dB

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 11 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| fall | 0 | 11 | 0 | 1 | 0 | 0 | 0 | 0 | 0 |
| arch | 0 | 1 | 11 | 0 | 0 | 0 | 0 | 0 | 0 |
| dip | 0 | 1 | 0 | 10 | 0 | 0 | 0 | 0 | 1 |
| flat | 0 | 0 | 0 | 2 | 10 | 0 | 0 | 0 | 0 |
| pop | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 2 |
| click | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 5 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6 | 0 |

### Confusion at 10 dB

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 11 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| fall | 0 | 12 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| arch | 0 | 1 | 11 | 0 | 0 | 0 | 0 | 0 | 0 |
| dip | 0 | 0 | 0 | 12 | 0 | 0 | 0 | 0 | 0 |
| flat | 0 | 0 | 0 | 1 | 11 | 0 | 0 | 0 | 0 |
| pop | 0 | 0 | 0 | 0 | 1 | 5 | 0 | 0 | 0 |
| click | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 3 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6 | 0 |

### Confusion at 20 dB

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 12 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| fall | 0 | 12 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| arch | 0 | 0 | 12 | 0 | 0 | 0 | 0 | 0 | 0 |
| dip | 0 | 0 | 0 | 12 | 0 | 0 | 0 | 0 | 0 |
| flat | 0 | 0 | 0 | 0 | 12 | 0 | 0 | 0 | 0 |
| pop | 0 | 0 | 0 | 0 | 0 | 6 | 0 | 0 | 0 |
| click | 0 | 0 | 0 | 0 | 0 | 0 | 6 | 0 | 0 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6 | 0 |

### Confusion at 30 dB

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 12 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| fall | 0 | 12 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| arch | 0 | 0 | 12 | 0 | 0 | 0 | 0 | 0 | 0 |
| dip | 0 | 0 | 0 | 12 | 0 | 0 | 0 | 0 | 0 |
| flat | 0 | 0 | 0 | 0 | 12 | 0 | 0 | 0 | 0 |
| pop | 0 | 0 | 0 | 0 | 0 | 6 | 0 | 0 | 0 |
| click | 0 | 0 | 0 | 0 | 0 | 0 | 6 | 0 | 0 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6 | 0 |

## Buckets and timing

- excursion bucket accuracy (hums/whistles with a correct contour label):  95.0 %
- duration bucket accuracy:  99.2 %
- hum clips called 'hum':  96.7 %; whistle clips called 'whistle':  99.2 %
- t_end error, all matched events: {"median": -8.599999999999909, "mean_abs": 18.210850439882694, "p90_abs": 31.799999999999955} (ms; negative = reported early)
- t_start error, all matched events: {"median": 5.2000000000000455, "mean_abs": 11.568914956011728, "p90_abs": 22.600000000000023} (ms)

| sound@SNR | n | median t_end err | mean abs | p90 abs |
|---|---|---|---|---|
| arch@5 | 12 | -26 | 25 | 36 |
| arch@10 | 12 | -21 | 20 | 26 |
| arch@20 | 12 | -6 | 6 | 9 |
| arch@30 | 12 | -2 | 12 | 8 |
| click@5 | 2 | -0 | 5 | 6 |
| click@10 | 8 | -6 | 6 | 9 |
| click@20 | 12 | -4 | 15 | 12 |
| click@30 | 12 | -3 | 13 | 7 |
| dip@5 | 11 | -22 | 20 | 27 |
| dip@10 | 12 | -13 | 15 | 23 |
| dip@20 | 12 | -9 | 17 | 14 |
| dip@30 | 12 | -1 | 5 | 10 |
| fall@5 | 12 | -23 | 20 | 38 |
| fall@10 | 12 | -15 | 17 | 23 |
| fall@20 | 12 | -8 | 16 | 15 |
| fall@30 | 12 | 2 | 12 | 9 |
| flat@5 | 12 | -18 | 17 | 29 |
| flat@10 | 12 | -14 | 36 | 82 |
| flat@20 | 12 | -6 | 66 | 33 |
| flat@30 | 12 | -1 | 8 | 8 |
| hiss@5 | 6 | -27 | 26 | 37 |
| hiss@10 | 6 | -19 | 20 | 32 |
| hiss@20 | 6 | -14 | 14 | 19 |
| hiss@30 | 6 | -8 | 8 | 12 |
| pop@5 | 8 | -20 | 33 | 56 |
| pop@10 | 12 | -23 | 26 | 33 |
| pop@20 | 12 | -4 | 10 | 21 |
| pop@30 | 12 | 1 | 11 | 24 |
| rise@5 | 12 | -15 | 34 | 75 |
| rise@10 | 12 | -14 | 22 | 32 |
| rise@20 | 12 | -7 | 9 | 16 |
| rise@30 | 12 | -2 | 9 | 19 |

## Line validity

- lines emitted: 590; strict-parser or label errors: 0
- valid but off the training distribution: {"hum over 1 s that is not a deliberate flat hum": 44, "very short hum that sounds like whistle": 1, "very short hiss": 13, "very short hum that sounds like talking": 12, "non-flat hum with small pitch change that sounds like talking": 6, "non-flat hum with small pitch change that sounds like laughing": 1, "loud background / long hiss (generate.py makes those quiet or normal)": 2, "hum line sounds like background noise": 9}
- extra events on single-gesture clips: 3
- Python real-time factor (processing time / audio time, this workstation): 0.016
