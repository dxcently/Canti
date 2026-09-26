# Synthetic evaluation (SYNTHETIC AUDIO ONLY: not evidence about real voices or mics)

clips: 880; per cell: 10; SNRs: [30, 20, 10, 5]; backgrounds: ['white', 'pink', 'brown', 'cafe']; sample rate: 16000; seed: 1

## Label accuracy (gesture clips)

| | 30 dB | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| contour (hum + whistle) |  98.0 |  99.0 |  95.0 |  60.0 |
| contour, hum only |  98.0 | 100.0 |  92.0 |  62.0 |
| contour, whistle only |  98.0 |  98.0 |  98.0 |  58.0 |
| discrete (pop/click/hiss) | 100.0 |  96.7 |  70.0 |  36.7 |

### Per class

| | 30 dB | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| arch | 100.0 | 100.0 |  70.0 |  50.0 |
| click | 100.0 |  90.0 |  20.0 |  20.0 |
| dip |  90.0 | 100.0 | 100.0 |  40.0 |
| fall | 100.0 | 100.0 | 100.0 |  70.0 |
| flat | 100.0 | 100.0 |  90.0 |  70.0 |
| hiss | 100.0 | 100.0 | 100.0 |  70.0 |
| pop | 100.0 | 100.0 |  90.0 |  20.0 |
| rise | 100.0 | 100.0 | 100.0 |  80.0 |
| whistle_arch | 100.0 | 100.0 | 100.0 |  60.0 |
| whistle_dip | 100.0 | 100.0 | 100.0 |  50.0 |
| whistle_fall | 100.0 | 100.0 | 100.0 |  70.0 |
| whistle_flat |  90.0 |  90.0 |  90.0 |  50.0 |
| whistle_rise | 100.0 | 100.0 | 100.0 |  60.0 |

## End-to-end default action (grouped like the phone, not-deliberate gate applied)

A clip is right only if it yields exactly its default action and no other action (a lone click correctly yields none: it is unbound).

| | 30 dB | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| arch | 100.0 | 100.0 |  70.0 |  50.0 |
| click | 100.0 | 100.0 | 100.0 | 100.0 |
| click_pop |  80.0 | 100.0 |  40.0 |  20.0 |
| dip |  90.0 | 100.0 |  90.0 |  40.0 |
| fall | 100.0 | 100.0 | 100.0 |  60.0 |
| flat | 100.0 | 100.0 |  90.0 |  70.0 |
| hiss | 100.0 | 100.0 | 100.0 |  70.0 |
| pop | 100.0 | 100.0 |  90.0 |  20.0 |
| rise | 100.0 | 100.0 | 100.0 |  70.0 |
| whistle_arch | 100.0 |  80.0 |  90.0 |  60.0 |
| whistle_dip | 100.0 | 100.0 | 100.0 |  50.0 |
| whistle_fall | 100.0 | 100.0 |  90.0 |  70.0 |
| whistle_flat |  80.0 |  90.0 |  90.0 |  50.0 |
| whistle_rise | 100.0 | 100.0 |  90.0 |  60.0 |

## False accepts on negatives (any action other than none)

| | 30 dB | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| air |   0.0 |  10.0 |   0.0 |   0.0 |
| cough |  10.0 |   0.0 |   0.0 |   0.0 |
| fan_motor |   0.0 |   0.0 |   0.0 |  30.0 |
| laugh |   0.0 |   0.0 |   0.0 |  20.0 |
| music |   0.0 |   0.0 |   0.0 |   0.0 |
| silence |   0.0 |   0.0 |   0.0 |   0.0 |
| talk |   0.0 |  10.0 |  10.0 |  10.0 |
| talk_short |  10.0 |   0.0 |   0.0 |  10.0 |

Overall false-accept rate:   3.8 %

Actions triggered by negatives: {"air": {"tap": 1}, "cough": {"tap": 1}, "fan_motor": {"long_press": 3}, "laugh": {"swipe_down": 2, "tap": 1}, "talk": {"long_press": 1, "swipe_down": 1, "tap": 1}, "talk_short": {"long_press": 1, "swipe_up": 1}}

'Sounds like' emitted for negatives: 

- air: {"background noise": 32, "hum": 3, "mouth sound": 1}
- cough: {"mouth sound": 2, "coughing": 14, "whistle": 9, "hum": 10, "background noise": 24}
- fan_motor: {"background noise": 30, "background music": 2, "hum": 4}
- laugh: {"laughing": 28, "hum": 34, "coughing": 3, "mouth sound": 4, "background noise": 1}
- music: {"background music": 13, "background noise": 37, "hum": 5}
- silence: {"hum": 3, "background noise": 2, "mouth sound": 1}
- talk: {"hum": 119, "laughing": 9, "talking": 10, "coughing": 1, "mouth sound": 4}
- talk_short: {"talking": 2, "hum": 36, "coughing": 1, "laughing": 2}

## Confusion matrix, all SNRs (rows = truth, columns = predicted label)

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 74 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 5 |
| fall | 0 | 74 | 0 | 0 | 0 | 0 | 0 | 0 | 6 |
| arch | 3 | 3 | 68 | 0 | 2 | 0 | 0 | 0 | 4 |
| dip | 1 | 3 | 0 | 68 | 1 | 0 | 0 | 0 | 7 |
| flat | 0 | 3 | 0 | 2 | 68 | 0 | 0 | 0 | 7 |
| pop | 0 | 0 | 0 | 0 | 0 | 31 | 0 | 1 | 8 |
| click | 0 | 0 | 0 | 0 | 1 | 0 | 23 | 0 | 16 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 37 | 3 |

### Confusion at 5 dB

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 14 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 5 |
| fall | 0 | 14 | 0 | 0 | 0 | 0 | 0 | 0 | 6 |
| arch | 2 | 1 | 11 | 0 | 2 | 0 | 0 | 0 | 4 |
| dip | 1 | 2 | 0 | 9 | 1 | 0 | 0 | 0 | 7 |
| flat | 0 | 1 | 0 | 0 | 12 | 0 | 0 | 0 | 7 |
| pop | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 1 | 7 |
| click | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 8 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 7 | 3 |

### Confusion at 10 dB

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 20 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| fall | 0 | 20 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| arch | 1 | 2 | 17 | 0 | 0 | 0 | 0 | 0 | 0 |
| dip | 0 | 0 | 0 | 20 | 0 | 0 | 0 | 0 | 0 |
| flat | 0 | 1 | 0 | 1 | 18 | 0 | 0 | 0 | 0 |
| pop | 0 | 0 | 0 | 0 | 0 | 9 | 0 | 0 | 1 |
| click | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 8 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 10 | 0 |

### Confusion at 20 dB

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 20 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| fall | 0 | 20 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| arch | 0 | 0 | 20 | 0 | 0 | 0 | 0 | 0 | 0 |
| dip | 0 | 0 | 0 | 20 | 0 | 0 | 0 | 0 | 0 |
| flat | 0 | 0 | 0 | 1 | 19 | 0 | 0 | 0 | 0 |
| pop | 0 | 0 | 0 | 0 | 0 | 10 | 0 | 0 | 0 |
| click | 0 | 0 | 0 | 0 | 1 | 0 | 9 | 0 | 0 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 10 | 0 |

### Confusion at 30 dB

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 20 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| fall | 0 | 20 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| arch | 0 | 0 | 20 | 0 | 0 | 0 | 0 | 0 | 0 |
| dip | 0 | 1 | 0 | 19 | 0 | 0 | 0 | 0 | 0 |
| flat | 0 | 1 | 0 | 0 | 19 | 0 | 0 | 0 | 0 |
| pop | 0 | 0 | 0 | 0 | 0 | 10 | 0 | 0 | 0 |
| click | 0 | 0 | 0 | 0 | 0 | 0 | 10 | 0 | 0 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 10 | 0 |

## Buckets and timing

- excursion bucket accuracy (hums/whistles with a correct contour label):  92.7 %
- duration bucket accuracy:  94.9 %
- hum clips called 'hum':  94.5 %; whistle clips called 'whistle':  90.0 %
- t_end error, all matched events: {"median": -9.099999999999909, "mean_abs": 26.117590822179732, "p90_abs": 41.76000000000009} (ms; negative = reported early)
- t_start error, all matched events: {"median": 4.2000000000000455, "mean_abs": 16.970936902485658, "p90_abs": 24.600000000000023} (ms)

| sound@SNR | n | median t_end err | mean abs | p90 abs |
|---|---|---|---|---|
| arch@5 | 16 | -30 | 115 | 439 |
| arch@10 | 20 | -18 | 57 | 77 |
| arch@20 | 20 | -9 | 18 | 32 |
| arch@30 | 20 | -4 | 7 | 9 |
| click@5 | 4 | -8 | 17 | 31 |
| click@10 | 6 | -3 | 5 | 11 |
| click@20 | 20 | -6 | 12 | 14 |
| click@30 | 20 | -4 | 25 | 32 |
| dip@5 | 13 | -18 | 20 | 33 |
| dip@10 | 20 | -12 | 25 | 38 |
| dip@20 | 20 | -9 | 15 | 22 |
| dip@30 | 20 | -4 | 9 | 12 |
| fall@5 | 14 | -17 | 29 | 45 |
| fall@10 | 20 | -17 | 37 | 38 |
| fall@20 | 20 | -12 | 20 | 21 |
| fall@30 | 20 | -4 | 13 | 32 |
| flat@5 | 13 | -18 | 35 | 39 |
| flat@10 | 20 | -16 | 28 | 39 |
| flat@20 | 20 | -11 | 17 | 22 |
| flat@30 | 20 | -3 | 8 | 12 |
| hiss@5 | 7 | -29 | 35 | 58 |
| hiss@10 | 10 | -32 | 36 | 50 |
| hiss@20 | 10 | -10 | 18 | 24 |
| hiss@30 | 10 | -8 | 8 | 12 |
| pop@5 | 6 | -12 | 17 | 29 |
| pop@10 | 19 | -28 | 31 | 40 |
| pop@20 | 20 | -11 | 27 | 71 |
| pop@30 | 20 | -4 | 14 | 24 |
| rise@5 | 15 | -24 | 85 | 242 |
| rise@10 | 20 | -20 | 38 | 101 |
| rise@20 | 20 | -8 | 10 | 16 |
| rise@30 | 20 | -6 | 9 | 16 |

## Line validity

- lines emitted: 984; strict-parser or label errors: 0
- valid but off the training distribution: {"non-flat hum lasting over 1 s": 40, "very short hiss": 22, "hum line sounds like background noise": 17}
- extra events on single-gesture clips: 15
- Python real-time factor (processing time / audio time, this workstation): 0.029
