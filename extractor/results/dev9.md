# Synthetic evaluation (SYNTHETIC AUDIO ONLY: not evidence about real voices or mics)

clips: 880; per cell: 10; SNRs: [30, 20, 10, 5]; backgrounds: ['white', 'pink', 'brown', 'cafe']; sample rate: 16000; seed: 1

## Label accuracy (gesture clips)

| | 30 dB | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| contour (hum + whistle) | 100.0 | 100.0 |  96.0 |  59.0 |
| contour, hum only | 100.0 | 100.0 |  94.0 |  60.0 |
| contour, whistle only | 100.0 | 100.0 |  98.0 |  58.0 |
| discrete (pop/click/hiss) | 100.0 |  96.7 |  73.3 |  36.7 |

### Per class

| | 30 dB | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| arch | 100.0 | 100.0 |  80.0 |  50.0 |
| click | 100.0 |  90.0 |  20.0 |  20.0 |
| dip | 100.0 | 100.0 | 100.0 |  40.0 |
| fall | 100.0 | 100.0 | 100.0 |  60.0 |
| flat | 100.0 | 100.0 | 100.0 |  60.0 |
| hiss | 100.0 | 100.0 | 100.0 |  70.0 |
| pop | 100.0 | 100.0 | 100.0 |  20.0 |
| rise | 100.0 | 100.0 |  90.0 |  90.0 |
| whistle_arch | 100.0 | 100.0 | 100.0 |  60.0 |
| whistle_dip | 100.0 | 100.0 | 100.0 |  60.0 |
| whistle_fall | 100.0 | 100.0 | 100.0 |  60.0 |
| whistle_flat | 100.0 | 100.0 |  90.0 |  50.0 |
| whistle_rise | 100.0 | 100.0 | 100.0 |  60.0 |

## End-to-end default action (grouped like the phone, not-deliberate gate applied)

A clip is right only if it yields exactly its default action and no other action (a lone click correctly yields none: it is unbound).

| | 30 dB | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| arch | 100.0 | 100.0 |  80.0 |  50.0 |
| click | 100.0 | 100.0 | 100.0 | 100.0 |
| click_pop | 100.0 |  90.0 |  40.0 |  20.0 |
| dip | 100.0 | 100.0 | 100.0 |  40.0 |
| fall | 100.0 | 100.0 | 100.0 |  60.0 |
| flat | 100.0 | 100.0 | 100.0 |  50.0 |
| hiss | 100.0 | 100.0 | 100.0 |  60.0 |
| pop | 100.0 | 100.0 | 100.0 |  20.0 |
| rise | 100.0 | 100.0 |  90.0 |  80.0 |
| whistle_arch | 100.0 | 100.0 | 100.0 |  60.0 |
| whistle_dip | 100.0 | 100.0 | 100.0 |  60.0 |
| whistle_fall | 100.0 | 100.0 | 100.0 |  60.0 |
| whistle_flat | 100.0 | 100.0 |  90.0 |  50.0 |
| whistle_rise | 100.0 | 100.0 | 100.0 |  60.0 |

## False accepts on negatives (any action other than none)

| | 30 dB | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| air |   0.0 |   0.0 |   0.0 |   0.0 |
| cough |  10.0 |   0.0 |   0.0 |   0.0 |
| fan_motor |   0.0 |   0.0 |   0.0 |  30.0 |
| laugh |   0.0 |   0.0 |  10.0 |   0.0 |
| music |   0.0 |   0.0 |   0.0 |   0.0 |
| silence |   0.0 |   0.0 |  10.0 |  10.0 |
| talk |   0.0 |   0.0 |   0.0 |   0.0 |
| talk_short |   0.0 |   0.0 |   0.0 |  10.0 |

Overall false-accept rate:   2.5 %

Actions triggered by negatives: {"cough": {"tap": 1}, "fan_motor": {"long_press": 4}, "laugh": {"tap": 1}, "silence": {"tap": 2}, "talk_short": {"swipe_down": 1}}

'Sounds like' emitted for negatives: 

- air: {"background noise": 32, "mouth sound": 1, "hum": 3}
- cough: {"mouth sound": 4, "coughing": 21, "hum": 7, "background noise": 23, "talking": 4}
- fan_motor: {"background noise": 22, "background music": 11, "hum": 4}
- laugh: {"laughing": 26, "coughing": 5, "talking": 20, "mouth sound": 6, "hum": 2}
- music: {"background music": 12, "background noise": 37, "hum": 7, "talking": 1}
- silence: {"hum": 1, "mouth sound": 2, "laughing": 1, "talking": 1}
- talk: {"talking": 72, "laughing": 4, "hum": 32}
- talk_short: {"talking": 21, "hum": 16}

## Confusion matrix, all SNRs (rows = truth, columns = predicted label)

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 74 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 4 |
| fall | 0 | 72 | 0 | 1 | 1 | 0 | 0 | 0 | 6 |
| arch | 3 | 2 | 69 | 0 | 2 | 0 | 0 | 0 | 4 |
| dip | 2 | 2 | 0 | 70 | 0 | 0 | 0 | 0 | 6 |
| flat | 0 | 0 | 0 | 3 | 70 | 0 | 0 | 0 | 7 |
| pop | 0 | 0 | 0 | 0 | 0 | 32 | 0 | 0 | 8 |
| click | 0 | 0 | 0 | 0 | 1 | 0 | 23 | 0 | 16 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 37 | 3 |

### Confusion at 5 dB

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 15 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 4 |
| fall | 0 | 12 | 0 | 1 | 1 | 0 | 0 | 0 | 6 |
| arch | 2 | 1 | 11 | 0 | 2 | 0 | 0 | 0 | 4 |
| dip | 2 | 2 | 0 | 10 | 0 | 0 | 0 | 0 | 6 |
| flat | 0 | 0 | 0 | 2 | 11 | 0 | 0 | 0 | 7 |
| pop | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 8 |
| click | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 8 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 7 | 3 |

### Confusion at 10 dB

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 19 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| fall | 0 | 20 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| arch | 1 | 1 | 18 | 0 | 0 | 0 | 0 | 0 | 0 |
| dip | 0 | 0 | 0 | 20 | 0 | 0 | 0 | 0 | 0 |
| flat | 0 | 0 | 0 | 1 | 19 | 0 | 0 | 0 | 0 |
| pop | 0 | 0 | 0 | 0 | 0 | 10 | 0 | 0 | 0 |
| click | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 8 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 10 | 0 |

### Confusion at 20 dB

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 20 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| fall | 0 | 20 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| arch | 0 | 0 | 20 | 0 | 0 | 0 | 0 | 0 | 0 |
| dip | 0 | 0 | 0 | 20 | 0 | 0 | 0 | 0 | 0 |
| flat | 0 | 0 | 0 | 0 | 20 | 0 | 0 | 0 | 0 |
| pop | 0 | 0 | 0 | 0 | 0 | 10 | 0 | 0 | 0 |
| click | 0 | 0 | 0 | 0 | 1 | 0 | 9 | 0 | 0 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 10 | 0 |

### Confusion at 30 dB

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 20 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| fall | 0 | 20 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| arch | 0 | 0 | 20 | 0 | 0 | 0 | 0 | 0 | 0 |
| dip | 0 | 0 | 0 | 20 | 0 | 0 | 0 | 0 | 0 |
| flat | 0 | 0 | 0 | 0 | 20 | 0 | 0 | 0 | 0 |
| pop | 0 | 0 | 0 | 0 | 0 | 10 | 0 | 0 | 0 |
| click | 0 | 0 | 0 | 0 | 0 | 0 | 10 | 0 | 0 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 10 | 0 |

## Buckets and timing

- excursion bucket accuracy (hums/whistles with a correct contour label):  93.3 %
- duration bucket accuracy:  95.9 %
- hum clips called 'hum':  94.5 %; whistle clips called 'whistle':  91.0 %
- t_end error, all matched events: {"median": -9.100000000000023, "mean_abs": 25.66755218216319, "p90_abs": 38.47999999999997} (ms; negative = reported early)
- t_start error, all matched events: {"median": 4.100000000000023, "mean_abs": 14.235863377609109, "p90_abs": 24.600000000000023} (ms)

| sound@SNR | n | median t_end err | mean abs | p90 abs |
|---|---|---|---|---|
| arch@5 | 16 | -31 | 124 | 439 |
| arch@10 | 20 | -18 | 50 | 50 |
| arch@20 | 20 | -11 | 14 | 15 |
| arch@30 | 20 | -4 | 6 | 9 |
| click@5 | 4 | -8 | 17 | 31 |
| click@10 | 6 | -3 | 5 | 11 |
| click@20 | 20 | -6 | 54 | 40 |
| click@30 | 20 | -4 | 6 | 10 |
| dip@5 | 14 | -19 | 23 | 33 |
| dip@10 | 20 | -12 | 15 | 28 |
| dip@20 | 20 | -7 | 10 | 16 |
| dip@30 | 20 | -4 | 5 | 10 |
| fall@5 | 14 | -19 | 27 | 45 |
| fall@10 | 20 | -15 | 22 | 38 |
| fall@20 | 20 | -11 | 18 | 30 |
| fall@30 | 20 | -4 | 9 | 15 |
| flat@5 | 13 | -18 | 20 | 39 |
| flat@10 | 20 | -16 | 22 | 33 |
| flat@20 | 20 | -11 | 22 | 32 |
| flat@30 | 20 | -4 | 10 | 11 |
| hiss@5 | 7 | -29 | 37 | 58 |
| hiss@10 | 10 | -32 | 35 | 50 |
| hiss@20 | 10 | -10 | 19 | 33 |
| hiss@30 | 10 | -8 | 8 | 12 |
| pop@5 | 7 | -11 | 65 | 165 |
| pop@10 | 20 | -28 | 26 | 33 |
| pop@20 | 20 | -14 | 21 | 27 |
| pop@30 | 20 | -4 | 9 | 18 |
| rise@5 | 16 | -27 | 108 | 324 |
| rise@10 | 20 | -21 | 30 | 73 |
| rise@20 | 20 | -8 | 10 | 16 |
| rise@30 | 20 | -6 | 11 | 17 |

## Line validity

- lines emitted: 932; strict-parser or label errors: 0
- valid but off the training distribution: {"other unseen combination": 12, "hum over 1 s that is not a deliberate flat hum": 64, "very short hiss": 17, "non-flat hum with small pitch change that sounds like talking": 6, "very short hum that sounds like talking": 24, "non-flat hum with small pitch change that sounds like coughing": 1, "non-flat hum with small pitch change that sounds like laughing": 2, "hum line sounds like background noise": 9}
- extra events on single-gesture clips: 6
- Python real-time factor (processing time / audio time, this workstation): 0.016
