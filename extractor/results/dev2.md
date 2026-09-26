# Synthetic evaluation (SYNTHETIC AUDIO ONLY: not evidence about real voices or mics)

clips: 352; per cell: 4; SNRs: [30, 20, 10, 5]; backgrounds: ['white', 'pink', 'brown', 'cafe']; sample rate: 16000; seed: 20260926

## Label accuracy (gesture clips)

| | 30 dB | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| contour (hum + whistle) | 100.0 |  47.5 |  47.5 |  30.0 |
| contour, hum only | 100.0 |  55.0 |  55.0 |  30.0 |
| contour, whistle only | 100.0 |  40.0 |  40.0 |  30.0 |
| discrete (pop/click/hiss) | 100.0 |  25.0 |  41.7 |  33.3 |

### Per class

| | 30 dB | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| arch | 100.0 |  25.0 |  25.0 |  25.0 |
| click | 100.0 |  25.0 |  25.0 |   0.0 |
| dip | 100.0 |  25.0 |  25.0 |   0.0 |
| fall | 100.0 |  50.0 |  75.0 |  25.0 |
| flat | 100.0 |  75.0 |  75.0 |  75.0 |
| hiss | 100.0 |  25.0 |  75.0 |  75.0 |
| pop | 100.0 |  25.0 |  25.0 |  25.0 |
| rise | 100.0 | 100.0 |  75.0 |  25.0 |
| whistle_arch | 100.0 |  25.0 |  25.0 |   0.0 |
| whistle_dip | 100.0 |  25.0 |  25.0 |  25.0 |
| whistle_fall | 100.0 |  25.0 |  50.0 |  50.0 |
| whistle_flat | 100.0 |  75.0 |  75.0 |  75.0 |
| whistle_rise | 100.0 |  50.0 |  25.0 |   0.0 |

## End-to-end default action (grouped like the phone, not-deliberate gate applied)

A clip is right only if it yields exactly its default action and no other action (a lone click correctly yields none: it is unbound).

| | 30 dB | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| arch | 100.0 |  25.0 |  25.0 |  25.0 |
| click | 100.0 | 100.0 | 100.0 | 100.0 |
| click_pop | 100.0 |  25.0 |   0.0 |   0.0 |
| dip | 100.0 |  25.0 |  25.0 |   0.0 |
| fall | 100.0 |  50.0 |  75.0 |   0.0 |
| flat | 100.0 |  50.0 |  75.0 |  50.0 |
| hiss | 100.0 |  25.0 |  75.0 |  75.0 |
| pop | 100.0 |  25.0 |  25.0 |  25.0 |
| rise | 100.0 |  75.0 |  75.0 |  25.0 |
| whistle_arch | 100.0 |  25.0 |  25.0 |   0.0 |
| whistle_dip | 100.0 |  25.0 |  25.0 |  25.0 |
| whistle_fall | 100.0 |  25.0 |  25.0 |  50.0 |
| whistle_flat | 100.0 |  75.0 |  50.0 |  50.0 |
| whistle_rise | 100.0 |  50.0 |  25.0 |   0.0 |

## False accepts on negatives (any action other than none)

| | 30 dB | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| air |  25.0 |   0.0 |   0.0 |   0.0 |
| cough |   0.0 |   0.0 |   0.0 |   0.0 |
| fan_motor |   0.0 |   0.0 |   0.0 |   0.0 |
| laugh |   0.0 |  25.0 |   0.0 |  25.0 |
| music |   0.0 |   0.0 |   0.0 |   0.0 |
| silence |   0.0 |   0.0 |   0.0 |   0.0 |
| talk |  25.0 |   0.0 |  25.0 |   0.0 |
| talk_short |  25.0 |   0.0 |   0.0 |   0.0 |

Overall false-accept rate:   4.7 %

Actions triggered by negatives: {"air": {"tap": 1}, "laugh": {"swipe_down": 1, "tap": 1}, "talk": {"swipe_down": 2}, "talk_short": {"long_press": 1}}

'Sounds like' emitted for negatives: 

- air: {"background noise": 15, "mouth sound": 1, "hum": 4}
- cough: {"hum": 1, "whistle": 7, "coughing": 7, "background noise": 4}
- fan_motor: {"background noise": 14, "background music": 1}
- laugh: {"laughing": 6, "hum": 18, "mouth sound": 2, "talking": 1}
- music: {"background music": 4, "hum": 4, "background noise": 17}
- silence: {"mouth sound": 1, "hum": 1}
- talk: {"hum": 40, "talking": 2, "laughing": 2, "mouth sound": 1}
- talk_short: {"hum": 10}

## Confusion matrix, all SNRs (rows = truth, columns = predicted label)

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 19 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 10 |
| fall | 0 | 19 | 0 | 0 | 1 | 1 | 0 | 0 | 11 |
| arch | 2 | 7 | 13 | 0 | 2 | 0 | 0 | 0 | 8 |
| dip | 11 | 0 | 0 | 13 | 0 | 2 | 0 | 0 | 6 |
| flat | 0 | 3 | 1 | 0 | 26 | 0 | 0 | 0 | 2 |
| pop | 0 | 0 | 0 | 0 | 0 | 7 | 0 | 0 | 9 |
| click | 0 | 0 | 0 | 0 | 0 | 0 | 6 | 0 | 10 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 11 | 5 |

### Confusion at 5 dB

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 1 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 4 |
| fall | 0 | 3 | 0 | 0 | 1 | 0 | 0 | 0 | 4 |
| arch | 0 | 2 | 1 | 0 | 0 | 0 | 0 | 0 | 5 |
| dip | 4 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 3 |
| flat | 0 | 0 | 1 | 0 | 6 | 0 | 0 | 0 | 1 |
| pop | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 3 |
| click | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 1 |

### Confusion at 10 dB

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 |
| fall | 0 | 5 | 0 | 0 | 0 | 1 | 0 | 0 | 2 |
| arch | 1 | 3 | 2 | 0 | 1 | 0 | 0 | 0 | 1 |
| dip | 4 | 0 | 0 | 2 | 0 | 1 | 0 | 0 | 1 |
| flat | 0 | 2 | 0 | 0 | 6 | 0 | 0 | 0 | 0 |
| pop | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 3 |
| click | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 3 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 1 |

### Confusion at 20 dB

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 |
| fall | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 5 |
| arch | 1 | 2 | 2 | 0 | 1 | 0 | 0 | 0 | 2 |
| dip | 3 | 0 | 0 | 2 | 0 | 1 | 0 | 0 | 2 |
| flat | 0 | 1 | 0 | 0 | 6 | 0 | 0 | 0 | 1 |
| pop | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 3 |
| click | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 3 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 3 |

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

- excursion bucket accuracy (hums/whistles with a correct contour label):  83.3 %
- duration bucket accuracy:  68.7 %
- hum clips called 'hum':  80.0 %; whistle clips called 'whistle':  68.8 %
- t_end error, all matched events: {"median": -11.600000000000023, "mean_abs": 20.12111801242237, "p90_abs": 30.90000000000009} (ms; negative = reported early)
- t_start error, all matched events: {"median": 11.0, "mean_abs": 135.15217391304347, "p90_abs": 390.9} (ms)

| sound@SNR | n | median t_end err | mean abs | p90 abs |
|---|---|---|---|---|
| arch@5 | 3 | -18 | 12 | 18 |
| arch@10 | 7 | -18 | 21 | 31 |
| arch@20 | 6 | -13 | 72 | 203 |
| arch@30 | 8 | -6 | 7 | 10 |
| click@10 | 1 | -6 | 6 | 6 |
| click@20 | 2 | -6 | 6 | 10 |
| click@30 | 8 | -10 | 8 | 12 |
| dip@5 | 5 | -29 | 22 | 33 |
| dip@10 | 7 | -14 | 17 | 32 |
| dip@20 | 6 | -11 | 11 | 17 |
| dip@30 | 8 | -7 | 10 | 18 |
| fall@5 | 4 | -29 | 24 | 31 |
| fall@10 | 6 | -12 | 35 | 82 |
| fall@20 | 3 | -10 | 13 | 22 |
| fall@30 | 8 | -10 | 9 | 15 |
| flat@5 | 7 | -26 | 52 | 101 |
| flat@10 | 8 | -9 | 13 | 26 |
| flat@20 | 7 | -7 | 20 | 43 |
| flat@30 | 8 | -2 | 18 | 41 |
| hiss@5 | 3 | -26 | 29 | 39 |
| hiss@10 | 3 | -32 | 32 | 36 |
| hiss@20 | 1 | -4 | 4 | 4 |
| hiss@30 | 4 | -12 | 11 | 16 |
| pop@5 | 3 | -26 | 25 | 27 |
| pop@10 | 2 | -12 | 13 | 22 |
| pop@20 | 3 | -15 | 14 | 17 |
| pop@30 | 8 | -14 | 14 | 27 |
| rise@5 | 4 | -21 | 26 | 38 |
| rise@10 | 4 | -18 | 19 | 32 |
| rise@20 | 6 | -8 | 10 | 18 |
| rise@30 | 8 | -10 | 27 | 56 |

## Line validity

- lines emitted: 327; strict-parser or label errors: 0
- valid but off the training distribution: {"non-flat hum lasting over 1 s": 11, "very short hiss": 5, "hum line sounds like background noise": 6}
- extra events on single-gesture clips: 3
- Python real-time factor (processing time / audio time, this workstation): 0.032
