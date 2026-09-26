# Synthetic evaluation (SYNTHETIC AUDIO ONLY: not evidence about real voices or mics)

clips: 352; per cell: 4; SNRs: [30, 20, 10, 5]; backgrounds: ['white', 'pink', 'brown', 'cafe']; sample rate: 16000; seed: 20260926

## Label accuracy (gesture clips)

| | 30 dB | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| contour (hum + whistle) | 100.0 |  97.5 |  92.5 |  52.5 |
| contour, hum only | 100.0 |  95.0 |  90.0 |  50.0 |
| contour, whistle only | 100.0 | 100.0 |  95.0 |  55.0 |
| discrete (pop/click/hiss) | 100.0 | 100.0 |  75.0 |  41.7 |

### Per class

| | 30 dB | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| arch | 100.0 | 100.0 |  75.0 |  50.0 |
| click | 100.0 | 100.0 |  25.0 |  25.0 |
| dip | 100.0 | 100.0 | 100.0 |  25.0 |
| fall | 100.0 | 100.0 | 100.0 |  75.0 |
| flat | 100.0 |  75.0 |  75.0 |  50.0 |
| hiss | 100.0 | 100.0 | 100.0 |  75.0 |
| pop | 100.0 | 100.0 | 100.0 |  25.0 |
| rise | 100.0 | 100.0 | 100.0 |  50.0 |
| whistle_arch | 100.0 | 100.0 | 100.0 |  75.0 |
| whistle_dip | 100.0 | 100.0 | 100.0 |  50.0 |
| whistle_fall | 100.0 | 100.0 | 100.0 |  50.0 |
| whistle_flat | 100.0 | 100.0 |  75.0 |  50.0 |
| whistle_rise | 100.0 | 100.0 | 100.0 |  50.0 |

## End-to-end default action (grouped like the phone, not-deliberate gate applied)

A clip is right only if it yields exactly its default action and no other action (a lone click correctly yields none: it is unbound).

| | 30 dB | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| arch | 100.0 | 100.0 |  75.0 |  25.0 |
| click | 100.0 | 100.0 | 100.0 | 100.0 |
| click_pop |  75.0 |  75.0 |  50.0 |  25.0 |
| dip | 100.0 | 100.0 | 100.0 |  25.0 |
| fall | 100.0 | 100.0 | 100.0 |  75.0 |
| flat | 100.0 |  75.0 |  75.0 |  50.0 |
| hiss | 100.0 | 100.0 | 100.0 |  50.0 |
| pop | 100.0 | 100.0 | 100.0 |  25.0 |
| rise | 100.0 | 100.0 | 100.0 |  50.0 |
| whistle_arch | 100.0 | 100.0 | 100.0 |  75.0 |
| whistle_dip | 100.0 | 100.0 | 100.0 |  50.0 |
| whistle_fall | 100.0 | 100.0 | 100.0 |  50.0 |
| whistle_flat | 100.0 | 100.0 |  75.0 |  50.0 |
| whistle_rise | 100.0 | 100.0 | 100.0 |  50.0 |

## False accepts on negatives (any action other than none)

| | 30 dB | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| air |  25.0 |  25.0 |   0.0 |   0.0 |
| cough |   0.0 |   0.0 |   0.0 |   0.0 |
| fan_motor |   0.0 |   0.0 |   0.0 |   0.0 |
| laugh |   0.0 |   0.0 |  25.0 |  25.0 |
| music |   0.0 |   0.0 |   0.0 |   0.0 |
| silence |   0.0 |   0.0 |  25.0 |   0.0 |
| talk |   0.0 |   0.0 |   0.0 |   0.0 |
| talk_short |   0.0 |   0.0 |   0.0 |   0.0 |

Overall false-accept rate:   3.9 %

Actions triggered by negatives: {"air": {"tap": 2}, "laugh": {"tap": 2, "swipe_down": 1}, "silence": {"tap": 1}}

'Sounds like' emitted for negatives: 

- air: {"background noise": 14, "mouth sound": 3, "hum": 3}
- cough: {"coughing": 7, "whistle": 6, "hum": 1, "background noise": 12, "mouth sound": 1}
- fan_motor: {"background noise": 13, "background music": 2}
- laugh: {"laughing": 9, "hum": 18, "coughing": 1, "mouth sound": 3}
- music: {"background music": 5, "hum": 3, "background noise": 19}
- silence: {"hum": 1, "background noise": 1, "mouth sound": 1}
- talk: {"hum": 27, "talking": 5, "laughing": 4, "mouth sound": 2}
- talk_short: {"hum": 16, "talking": 1}

## Confusion matrix, all SNRs (rows = truth, columns = predicted label)

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 28 | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 2 |
| fall | 0 | 29 | 0 | 1 | 0 | 0 | 0 | 0 | 2 |
| arch | 1 | 2 | 28 | 0 | 0 | 0 | 0 | 0 | 1 |
| dip | 0 | 1 | 0 | 27 | 2 | 0 | 0 | 0 | 2 |
| flat | 0 | 3 | 1 | 1 | 25 | 0 | 0 | 0 | 2 |
| pop | 0 | 0 | 0 | 0 | 0 | 13 | 0 | 0 | 3 |
| click | 0 | 0 | 0 | 0 | 0 | 0 | 10 | 0 | 6 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 15 | 1 |

### Confusion at 5 dB

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 4 | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 2 |
| fall | 0 | 5 | 0 | 1 | 0 | 0 | 0 | 0 | 2 |
| arch | 1 | 1 | 5 | 0 | 0 | 0 | 0 | 0 | 1 |
| dip | 0 | 1 | 0 | 3 | 2 | 0 | 0 | 0 | 2 |
| flat | 0 | 0 | 1 | 1 | 4 | 0 | 0 | 0 | 2 |
| pop | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 3 |
| click | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 3 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 1 |

### Confusion at 10 dB

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| fall | 0 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| arch | 0 | 1 | 7 | 0 | 0 | 0 | 0 | 0 | 0 |
| dip | 0 | 0 | 0 | 8 | 0 | 0 | 0 | 0 | 0 |
| flat | 0 | 2 | 0 | 0 | 6 | 0 | 0 | 0 | 0 |
| pop | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 |
| click | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 3 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 |

### Confusion at 20 dB

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| fall | 0 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| arch | 0 | 0 | 8 | 0 | 0 | 0 | 0 | 0 | 0 |
| dip | 0 | 0 | 0 | 8 | 0 | 0 | 0 | 0 | 0 |
| flat | 0 | 1 | 0 | 0 | 7 | 0 | 0 | 0 | 0 |
| pop | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 |
| click | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 |

### Confusion at 30 dB

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| fall | 0 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| arch | 0 | 0 | 8 | 0 | 0 | 0 | 0 | 0 | 0 |
| dip | 0 | 0 | 0 | 8 | 0 | 0 | 0 | 0 | 0 |
| flat | 0 | 0 | 0 | 0 | 8 | 0 | 0 | 0 | 0 |
| pop | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 |
| click | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 |

## Buckets and timing

- excursion bucket accuracy (hums/whistles with a correct contour label):  93.4 %
- duration bucket accuracy:  95.2 %
- hum clips called 'hum':  96.2 %; whistle clips called 'whistle':  92.5 %
- t_end error, all matched events: {"median": -9.150000000000034, "mean_abs": 20.160849056603777, "p90_abs": 45.07000000000009} (ms; negative = reported early)
- t_start error, all matched events: {"median": 4.850000000000023, "mean_abs": 17.80141509433962, "p90_abs": 22.35999999999998} (ms)

| sound@SNR | n | median t_end err | mean abs | p90 abs |
|---|---|---|---|---|
| arch@5 | 7 | -26 | 36 | 79 |
| arch@10 | 8 | -16 | 17 | 26 |
| arch@20 | 8 | -10 | 10 | 19 |
| arch@30 | 8 | 1 | 11 | 22 |
| click@5 | 2 | -7 | 7 | 8 |
| click@10 | 3 | -6 | 6 | 10 |
| click@20 | 8 | -4 | 13 | 28 |
| click@30 | 7 | -2 | 5 | 10 |
| dip@5 | 6 | -18 | 20 | 35 |
| dip@10 | 8 | -12 | 14 | 29 |
| dip@20 | 8 | -10 | 10 | 17 |
| dip@30 | 8 | -1 | 6 | 9 |
| fall@5 | 6 | -29 | 35 | 59 |
| fall@10 | 8 | -16 | 30 | 60 |
| fall@20 | 8 | -4 | 42 | 98 |
| fall@30 | 8 | -2 | 5 | 10 |
| flat@5 | 6 | -26 | 26 | 44 |
| flat@10 | 8 | -12 | 15 | 22 |
| flat@20 | 8 | -8 | 19 | 38 |
| flat@30 | 8 | -2 | 11 | 22 |
| hiss@5 | 3 | -40 | 34 | 49 |
| hiss@10 | 4 | -22 | 32 | 46 |
| hiss@20 | 4 | -12 | 12 | 17 |
| hiss@30 | 4 | -1 | 30 | 75 |
| pop@5 | 2 | -9 | 17 | 24 |
| pop@10 | 8 | -27 | 23 | 34 |
| pop@20 | 8 | -16 | 23 | 37 |
| pop@30 | 8 | -6 | 14 | 28 |
| rise@5 | 6 | -18 | 71 | 176 |
| rise@10 | 8 | -17 | 18 | 31 |
| rise@20 | 8 | -4 | 13 | 30 |
| rise@30 | 8 | -5 | 34 | 109 |

## Line validity

- lines emitted: 392; strict-parser or label errors: 0
- valid but off the training distribution: {"non-flat hum lasting over 1 s": 19, "very short hiss": 10, "hum line sounds like background noise": 5}
- extra events on single-gesture clips: 2
- Python real-time factor (processing time / audio time, this workstation): 0.027
