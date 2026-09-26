# Synthetic evaluation (SYNTHETIC AUDIO ONLY: not evidence about real voices or mics)

clips: 352; per cell: 4; SNRs: [30, 20, 10, 5]; backgrounds: ['white', 'pink', 'brown', 'cafe']; sample rate: 16000; seed: 20260926

## Label accuracy (gesture clips)

| | 30 dB | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| contour (hum + whistle) |  97.5 |  92.5 |  80.0 |  82.5 |
| contour, hum only | 100.0 |  90.0 |  80.0 |  85.0 |
| contour, whistle only |  95.0 |  95.0 |  80.0 |  80.0 |
| discrete (pop/click/hiss) |  91.7 |  83.3 |  83.3 |  66.7 |

### Per class

| | 30 dB | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| arch | 100.0 | 100.0 |  75.0 | 100.0 |
| click |  75.0 |  75.0 |  50.0 |  25.0 |
| dip | 100.0 | 100.0 | 100.0 | 100.0 |
| fall | 100.0 |  75.0 |  75.0 |  75.0 |
| flat | 100.0 |  75.0 |  75.0 |  75.0 |
| hiss | 100.0 | 100.0 | 100.0 | 100.0 |
| pop | 100.0 |  75.0 | 100.0 |  75.0 |
| rise | 100.0 | 100.0 |  75.0 |  75.0 |
| whistle_arch | 100.0 | 100.0 | 100.0 | 100.0 |
| whistle_dip |  75.0 | 100.0 |  75.0 |  75.0 |
| whistle_fall | 100.0 | 100.0 |  75.0 |  75.0 |
| whistle_flat | 100.0 | 100.0 |  75.0 |  75.0 |
| whistle_rise | 100.0 |  75.0 |  75.0 |  75.0 |

## End-to-end default action (grouped like the phone, not-deliberate gate applied)

A clip is right only if it yields exactly its default action and no other action (a lone click correctly yields none: it is unbound).

| | 30 dB | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| arch | 100.0 |  75.0 |  75.0 |  75.0 |
| click |  75.0 | 100.0 | 100.0 | 100.0 |
| click_pop |  75.0 | 100.0 |  50.0 |  25.0 |
| dip |  75.0 |  75.0 |  75.0 |  75.0 |
| fall |  75.0 |  75.0 |  75.0 |  75.0 |
| flat |  75.0 |  75.0 |  75.0 |  75.0 |
| hiss | 100.0 |  75.0 |  75.0 |  75.0 |
| pop |  75.0 |  50.0 |  75.0 |  50.0 |
| rise |  75.0 | 100.0 |  75.0 |  50.0 |
| whistle_arch |  75.0 |  75.0 |  75.0 | 100.0 |
| whistle_dip |  75.0 |  75.0 |  75.0 |  75.0 |
| whistle_fall | 100.0 | 100.0 |  75.0 |  75.0 |
| whistle_flat | 100.0 |  75.0 |  75.0 |  75.0 |
| whistle_rise | 100.0 |  75.0 |  75.0 |  75.0 |

## False accepts on negatives (any action other than none)

| | 30 dB | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| air |  25.0 |  25.0 |   0.0 |  25.0 |
| cough |   0.0 |   0.0 |   0.0 |   0.0 |
| fan_motor |  25.0 |   0.0 |  25.0 |   0.0 |
| laugh |   0.0 |   0.0 |  25.0 |   0.0 |
| music |   0.0 |   0.0 |   0.0 |   0.0 |
| silence |  25.0 |   0.0 |   0.0 |  25.0 |
| talk |   0.0 |   0.0 |   0.0 |   0.0 |
| talk_short |   0.0 |   0.0 |   0.0 |  25.0 |

Overall false-accept rate:   7.0 %

Actions triggered by negatives: {"air": {"tap": 2, "swipe_up": 1, "swipe_down": 1}, "fan_motor": {"long_press": 2}, "laugh": {"tap": 1}, "silence": {"swipe_right": 1, "tap": 2}, "talk_short": {"tap": 1}}

'Sounds like' emitted for negatives: 

- air: {"background noise": 14, "mouth sound": 3, "hum": 3, "background music": 2}
- cough: {"coughing": 8, "whistle": 5, "hum": 4, "background noise": 8, "mouth sound": 4}
- fan_motor: {"background noise": 10, "hum": 4, "mouth sound": 2, "background music": 1}
- laugh: {"laughing": 13, "hum": 12, "mouth sound": 8, "background music": 1}
- music: {"hum": 9, "background noise": 17, "mouth sound": 3}
- silence: {"hum": 2, "mouth sound": 2}
- talk: {"hum": 35, "talking": 7, "laughing": 3, "mouth sound": 4, "background noise": 2, "background music": 1}
- talk_short: {"hum": 17, "talking": 2, "background noise": 2, "mouth sound": 3}

## Confusion matrix, all SNRs (rows = truth, columns = predicted label)

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 27 | 2 | 2 | 1 | 0 | 0 | 0 | 0 | 0 |
| fall | 1 | 27 | 1 | 3 | 0 | 0 | 0 | 0 | 0 |
| arch | 0 | 1 | 31 | 0 | 0 | 0 | 0 | 0 | 0 |
| dip | 0 | 2 | 1 | 29 | 0 | 0 | 0 | 0 | 0 |
| flat | 1 | 2 | 1 | 1 | 27 | 0 | 0 | 0 | 0 |
| pop | 0 | 0 | 0 | 0 | 1 | 14 | 0 | 0 | 1 |
| click | 0 | 2 | 0 | 0 | 1 | 0 | 9 | 0 | 4 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 16 | 0 |

### Confusion at 5 dB

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 6 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| fall | 1 | 6 | 0 | 1 | 0 | 0 | 0 | 0 | 0 |
| arch | 0 | 0 | 8 | 0 | 0 | 0 | 0 | 0 | 0 |
| dip | 0 | 1 | 0 | 7 | 0 | 0 | 0 | 0 | 0 |
| flat | 0 | 1 | 0 | 1 | 6 | 0 | 0 | 0 | 0 |
| pop | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 1 |
| click | 0 | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 2 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 |

### Confusion at 10 dB

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 6 | 0 | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| fall | 0 | 6 | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| arch | 0 | 1 | 7 | 0 | 0 | 0 | 0 | 0 | 0 |
| dip | 0 | 1 | 0 | 7 | 0 | 0 | 0 | 0 | 0 |
| flat | 0 | 1 | 1 | 0 | 6 | 0 | 0 | 0 | 0 |
| pop | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 |
| click | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 2 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 |

### Confusion at 20 dB

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 7 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| fall | 0 | 7 | 0 | 1 | 0 | 0 | 0 | 0 | 0 |
| arch | 0 | 0 | 8 | 0 | 0 | 0 | 0 | 0 | 0 |
| dip | 0 | 0 | 0 | 8 | 0 | 0 | 0 | 0 | 0 |
| flat | 1 | 0 | 0 | 0 | 7 | 0 | 0 | 0 | 0 |
| pop | 0 | 0 | 0 | 0 | 1 | 3 | 0 | 0 | 0 |
| click | 0 | 0 | 0 | 0 | 1 | 0 | 3 | 0 | 0 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 |

### Confusion at 30 dB

| truth | rise | fall | arch | dip | flat | pop | click | hiss | none |
|---|---|---|---|---|---|---|---|---|---|
| rise | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| fall | 0 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| arch | 0 | 0 | 8 | 0 | 0 | 0 | 0 | 0 | 0 |
| dip | 0 | 0 | 1 | 7 | 0 | 0 | 0 | 0 | 0 |
| flat | 0 | 0 | 0 | 0 | 8 | 0 | 0 | 0 | 0 |
| pop | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 |
| click | 0 | 1 | 0 | 0 | 0 | 0 | 3 | 0 | 0 |
| hiss | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 |

## Buckets and timing

- excursion bucket accuracy (hums/whistles with a correct contour label):  92.5 %
- duration bucket accuracy:  88.6 %
- hum clips called 'hum':  95.0 %; whistle clips called 'whistle':  98.8 %
- t_end error, all matched events: {"median": -4.7999999999999545, "mean_abs": 55.62510822510822, "p90_abs": 141.4000000000001} (ms; negative = reported early)
- t_start error, all matched events: {"median": 1.7999999999999545, "mean_abs": 27.351515151515148, "p90_abs": 39.200000000000045} (ms)

| sound@SNR | n | median t_end err | mean abs | p90 abs |
|---|---|---|---|---|
| arch@5 | 8 | -12 | 14 | 29 |
| arch@10 | 8 | -15 | 14 | 20 |
| arch@20 | 8 | -5 | 7 | 15 |
| arch@30 | 8 | 4 | 46 | 136 |
| click@5 | 4 | -6 | 177 | 482 |
| click@10 | 5 | -6 | 50 | 122 |
| click@20 | 8 | 0 | 71 | 178 |
| click@30 | 8 | 0 | 90 | 224 |
| dip@5 | 8 | -10 | 59 | 133 |
| dip@10 | 8 | -5 | 100 | 270 |
| dip@20 | 8 | -4 | 9 | 21 |
| dip@30 | 8 | 5 | 69 | 215 |
| fall@5 | 8 | -14 | 88 | 231 |
| fall@10 | 8 | -5 | 86 | 226 |
| fall@20 | 8 | 41 | 147 | 398 |
| fall@30 | 8 | 0 | 2 | 5 |
| flat@5 | 8 | -24 | 48 | 87 |
| flat@10 | 8 | -9 | 15 | 27 |
| flat@20 | 8 | -5 | 30 | 95 |
| flat@30 | 8 | -2 | 16 | 34 |
| hiss@5 | 4 | -23 | 27 | 31 |
| hiss@10 | 4 | -12 | 27 | 50 |
| hiss@20 | 4 | -10 | 22 | 43 |
| hiss@30 | 4 | 2 | 53 | 144 |
| pop@5 | 6 | -22 | 54 | 122 |
| pop@10 | 8 | -16 | 72 | 155 |
| pop@20 | 8 | -10 | 26 | 48 |
| pop@30 | 8 | 1 | 28 | 77 |
| rise@5 | 8 | -19 | 108 | 265 |
| rise@10 | 8 | -5 | 96 | 269 |
| rise@20 | 8 | -3 | 70 | 193 |
| rise@30 | 8 | -2 | 71 | 181 |

## Line validity

- lines emitted: 513; strict-parser or label errors: 0
- valid but off the training distribution: {"non-flat hum lasting over 1 s": 36, "very short hiss": 4, "hum line sounds like background noise": 2}
- extra events on single-gesture clips: 65
- Python real-time factor (processing time / audio time, this workstation): 0.037
