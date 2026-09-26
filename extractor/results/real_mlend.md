# REAL audio: mlend

```
MLEnd Hums and Whistles (Queen Mary University of London): ~15-20 s hummed / whistled song excerpts
recorded by 226 interpreters on their own devices (mostly phones / laptops), 44.1 kHz, mono or stereo.

These are MELODIES, not gestures: a hummed song breaks into many notes and phrases, and anything longer than
3 s is "background music" by design (max_gesture_ms). So nothing here is scored as a gesture. Two questions:
  1. Does the extractor recognise the source? Of the voiced (contour) events, how many say "hum" for hum
     recordings and "whistle" for whistle recordings, time-weighted and by count; which other "sounds like"
     values appear (talking, background music ...). Also by the event's median f0 (low-f0 hums vs talking cue).
  2. Is pitch tracked? No manual pitch exists, so the reference is Praat's autocorrelation tracker
     (parselmouth, to_pitch_ac, 10 ms step; floor/ceiling 60/900 Hz for hums, 300/3000 Hz for whistles):
     voicing agreement and, on frames both call voiced, gross error (> 20 %), octave errors and cents error.
     This measures agreement with another tracker, NOT accuracy against the truth.
Rate handling: stereo -> mean, 44.1 kHz -> 16 kHz with scipy resample_poly (resample.to_16k), not the 48 kHz
decimator. Speaker = Interpreter.
```

### FROZEN config, TEST split  <- headline

| recordings | files | min | events/min | voiced events | called right % (n) | called right % (time) | hum or whistle % | talking % | files with >= 1 right | voicing recall vs Praat % | GPE vs Praat % | octave err % | median |cents| (no gross) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| hum | 3351 | 896 | 34.0 | 28007 | 50.3 | 33.4 | 51.0 | 34.3 | 93.1 | 90.8 | 2.5 | 2.2 | 4 |
| whistle | 1181 | 321 | 45.8 | 13862 | 91.1 | 75.2 | 92.0 | 2.4 | 98.7 | 95.2 | 2.7 | 0.8 | 5 |

'Sounds like' of voiced events in hum recordings, by event median f0:

| f0 | hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound | n |
|---|---|---|---|---|---|---|---|---|---|
| 0-110 Hz | 494 | 0 | 340 | 21 | 41 | 13 | 90 | 0 | 999 |
| 110-160 Hz | 3495 | 0 | 2870 | 57 | 5 | 62 | 668 | 0 | 7157 |
| 160-250 Hz | 5241 | 0 | 3642 | 26 | 8 | 34 | 1750 | 0 | 10701 |
| 250-400 Hz | 4078 | 0 | 2407 | 6 | 1 | 19 | 1144 | 0 | 7655 |
| 400-600 Hz | 634 | 0 | 258 | 0 | 1 | 1 | 165 | 0 | 1059 |
| 600-1000 Hz | 9 | 91 | 11 | 0 | 0 | 0 | 8 | 0 | 119 |
| 1000-5000 Hz | 131 | 101 | 66 | 0 | 17 | 0 | 2 | 0 | 317 |

'Sounds like' of voiced events in whistle recordings, by event median f0:

| f0 | hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound | n |
|---|---|---|---|---|---|---|---|---|---|
| 0-110 Hz | 5 | 0 | 7 | 4 | 12 | 2 | 0 | 0 | 30 |
| 110-160 Hz | 4 | 0 | 6 | 2 | 0 | 0 | 0 | 0 | 12 |
| 160-250 Hz | 8 | 0 | 2 | 1 | 0 | 0 | 0 | 0 | 11 |
| 250-400 Hz | 3 | 0 | 4 | 0 | 0 | 1 | 0 | 0 | 8 |
| 400-600 Hz | 9 | 0 | 9 | 0 | 1 | 0 | 0 | 0 | 19 |
| 600-1000 Hz | 9 | 554 | 14 | 2 | 1 | 5 | 24 | 0 | 609 |
| 1000-5000 Hz | 95 | 12070 | 285 | 41 | 6 | 106 | 570 | 0 | 13173 |

Lines: 45200; strict-parse/label errors: 0; outside generate.py's line space: 23063

### FROZEN config, TUNE split

| recordings | files | min | events/min | voiced events | called right % (n) | called right % (time) | hum or whistle % | talking % | files with >= 1 right | voicing recall vs Praat % | GPE vs Praat % | octave err % | median |cents| (no gross) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| hum | 1453 | 393 | 34.9 | 12604 | 50.6 | 34.2 | 51.1 | 35.3 | 93.9 | 90.2 | 2.4 | 1.9 | 4 |
| whistle | 616 | 163 | 47.4 | 7216 | 89.5 | 75.6 | 91.4 | 2.9 | 97.6 | 93.9 | 1.3 | 0.5 | 5 |

'Sounds like' of voiced events in hum recordings, by event median f0:

| f0 | hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound | n |
|---|---|---|---|---|---|---|---|---|---|
| 0-110 Hz | 206 | 0 | 162 | 2 | 14 | 7 | 31 | 0 | 422 |
| 110-160 Hz | 1606 | 0 | 1146 | 15 | 3 | 21 | 298 | 0 | 3089 |
| 160-250 Hz | 2264 | 0 | 1635 | 6 | 0 | 29 | 785 | 0 | 4719 |
| 250-400 Hz | 1886 | 0 | 1323 | 5 | 0 | 11 | 399 | 0 | 3624 |
| 400-600 Hz | 349 | 0 | 155 | 0 | 0 | 0 | 73 | 0 | 577 |
| 600-1000 Hz | 3 | 24 | 5 | 0 | 1 | 0 | 3 | 0 | 36 |
| 1000-5000 Hz | 66 | 38 | 28 | 0 | 5 | 0 | 0 | 0 | 137 |

'Sounds like' of voiced events in whistle recordings, by event median f0:

| f0 | hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound | n |
|---|---|---|---|---|---|---|---|---|---|
| 0-110 Hz | 0 | 0 | 5 | 4 | 7 | 0 | 0 | 0 | 16 |
| 110-160 Hz | 5 | 0 | 8 | 2 | 0 | 0 | 0 | 0 | 15 |
| 160-250 Hz | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 2 |
| 250-400 Hz | 2 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 4 |
| 400-600 Hz | 11 | 0 | 10 | 0 | 0 | 0 | 0 | 0 | 21 |
| 600-1000 Hz | 4 | 442 | 8 | 1 | 0 | 2 | 11 | 0 | 468 |
| 1000-5000 Hz | 110 | 6017 | 177 | 36 | 12 | 28 | 310 | 0 | 6690 |

Lines: 21459; strict-parse/label errors: 0; outside generate.py's line space: 11000

### FIXED config, TEST split

| recordings | files | min | events/min | voiced events | called right % (n) | called right % (time) | hum or whistle % | talking % | files with >= 1 right | voicing recall vs Praat % | GPE vs Praat % | octave err % | median |cents| (no gross) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| hum | 3351 | 896 | 32.9 | 27131 | 48.6 | 30.3 | 49.3 | 34.2 | 91.9 | 93.4 | 2.6 | 2.2 | 4 |
| whistle | 1181 | 321 | 44.4 | 13527 | 90.3 | 71.7 | 91.2 | 2.3 | 98.7 | 96.0 | 2.7 | 0.8 | 5 |

'Sounds like' of voiced events in hum recordings, by event median f0:

| f0 | hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound | n |
|---|---|---|---|---|---|---|---|---|---|
| 0-110 Hz | 473 | 0 | 322 | 22 | 41 | 15 | 96 | 0 | 969 |
| 110-160 Hz | 3252 | 0 | 2784 | 54 | 5 | 66 | 720 | 0 | 6881 |
| 160-250 Hz | 4908 | 0 | 3521 | 24 | 12 | 39 | 1879 | 0 | 10383 |
| 250-400 Hz | 3813 | 0 | 2333 | 6 | 2 | 22 | 1258 | 0 | 7434 |
| 400-600 Hz | 598 | 0 | 252 | 0 | 1 | 1 | 188 | 0 | 1040 |
| 600-1000 Hz | 9 | 84 | 11 | 0 | 0 | 0 | 12 | 0 | 116 |
| 1000-5000 Hz | 124 | 102 | 63 | 0 | 17 | 0 | 2 | 0 | 308 |

'Sounds like' of voiced events in whistle recordings, by event median f0:

| f0 | hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound | n |
|---|---|---|---|---|---|---|---|---|---|
| 0-110 Hz | 4 | 0 | 6 | 4 | 14 | 2 | 0 | 0 | 30 |
| 110-160 Hz | 4 | 0 | 6 | 2 | 0 | 0 | 0 | 0 | 12 |
| 160-250 Hz | 8 | 0 | 2 | 1 | 0 | 0 | 0 | 0 | 11 |
| 250-400 Hz | 3 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 6 |
| 400-600 Hz | 6 | 0 | 9 | 0 | 1 | 1 | 0 | 0 | 17 |
| 600-1000 Hz | 8 | 522 | 14 | 2 | 1 | 6 | 26 | 0 | 579 |
| 1000-5000 Hz | 90 | 11687 | 275 | 41 | 6 | 123 | 650 | 0 | 12872 |

Lines: 43697; strict-parse/label errors: 0; outside generate.py's line space: 23101

### FIXED config, TUNE split

| recordings | files | min | events/min | voiced events | called right % (n) | called right % (time) | hum or whistle % | talking % | files with >= 1 right | voicing recall vs Praat % | GPE vs Praat % | octave err % | median |cents| (no gross) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| hum | 1453 | 393 | 33.6 | 12195 | 48.8 | 31.4 | 49.3 | 35.6 | 92.9 | 92.8 | 2.5 | 2.0 | 4 |
| whistle | 616 | 163 | 45.8 | 7001 | 88.7 | 71.5 | 90.5 | 2.8 | 97.2 | 94.7 | 1.3 | 0.5 | 5 |

'Sounds like' of voiced events in hum recordings, by event median f0:

| f0 | hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound | n |
|---|---|---|---|---|---|---|---|---|---|
| 0-110 Hz | 195 | 0 | 154 | 2 | 13 | 9 | 29 | 0 | 402 |
| 110-160 Hz | 1512 | 0 | 1120 | 15 | 3 | 22 | 325 | 0 | 2997 |
| 160-250 Hz | 2106 | 0 | 1583 | 6 | 1 | 33 | 841 | 0 | 4570 |
| 250-400 Hz | 1747 | 0 | 1295 | 5 | 0 | 10 | 446 | 0 | 3503 |
| 400-600 Hz | 323 | 0 | 153 | 0 | 0 | 0 | 75 | 0 | 551 |
| 600-1000 Hz | 3 | 22 | 5 | 0 | 1 | 0 | 3 | 0 | 34 |
| 1000-5000 Hz | 65 | 40 | 28 | 0 | 5 | 0 | 0 | 0 | 138 |

'Sounds like' of voiced events in whistle recordings, by event median f0:

| f0 | hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound | n |
|---|---|---|---|---|---|---|---|---|---|
| 0-110 Hz | 0 | 0 | 5 | 4 | 6 | 0 | 0 | 0 | 15 |
| 110-160 Hz | 5 | 0 | 7 | 2 | 0 | 0 | 0 | 0 | 14 |
| 160-250 Hz | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 2 |
| 250-400 Hz | 2 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 5 |
| 400-600 Hz | 11 | 0 | 10 | 0 | 0 | 0 | 1 | 0 | 22 |
| 600-1000 Hz | 3 | 422 | 8 | 1 | 0 | 2 | 11 | 0 | 447 |
| 1000-5000 Hz | 106 | 5786 | 165 | 41 | 11 | 33 | 354 | 0 | 6496 |

Lines: 20686; strict-parse/label errors: 0; outside generate.py's line space: 11001

### TUNED config, TEST split

| recordings | files | min | events/min | voiced events | called right % (n) | called right % (time) | hum or whistle % | talking % | files with >= 1 right | voicing recall vs Praat % | GPE vs Praat % | octave err % | median |cents| (no gross) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| hum | 3351 | 896 | 32.0 | 27144 | 48.6 | 30.3 | 49.3 | 34.3 | 91.9 | 93.4 | 2.6 | 2.2 | 4 |
| whistle | 1181 | 321 | 43.7 | 13531 | 90.2 | 71.7 | 91.2 | 2.3 | 98.7 | 96.0 | 2.7 | 0.8 | 5 |

'Sounds like' of voiced events in hum recordings, by event median f0:

| f0 | hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound | n |
|---|---|---|---|---|---|---|---|---|---|
| 0-110 Hz | 473 | 0 | 325 | 22 | 34 | 15 | 96 | 0 | 965 |
| 110-160 Hz | 3255 | 0 | 2789 | 54 | 5 | 66 | 720 | 0 | 6889 |
| 160-250 Hz | 4906 | 0 | 3527 | 24 | 12 | 39 | 1879 | 0 | 10387 |
| 250-400 Hz | 3812 | 0 | 2335 | 6 | 2 | 22 | 1258 | 0 | 7435 |
| 400-600 Hz | 598 | 0 | 252 | 0 | 1 | 1 | 188 | 0 | 1040 |
| 600-1000 Hz | 9 | 84 | 11 | 0 | 0 | 0 | 12 | 0 | 116 |
| 1000-5000 Hz | 130 | 102 | 64 | 0 | 14 | 0 | 2 | 0 | 312 |

'Sounds like' of voiced events in whistle recordings, by event median f0:

| f0 | hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound | n |
|---|---|---|---|---|---|---|---|---|---|
| 0-110 Hz | 4 | 0 | 6 | 3 | 11 | 2 | 0 | 0 | 26 |
| 110-160 Hz | 5 | 0 | 5 | 2 | 0 | 0 | 0 | 0 | 12 |
| 160-250 Hz | 8 | 0 | 2 | 1 | 0 | 0 | 0 | 0 | 11 |
| 250-400 Hz | 6 | 0 | 5 | 0 | 0 | 0 | 0 | 0 | 11 |
| 400-600 Hz | 6 | 0 | 9 | 0 | 1 | 1 | 0 | 0 | 17 |
| 600-1000 Hz | 9 | 522 | 15 | 2 | 1 | 6 | 26 | 0 | 581 |
| 1000-5000 Hz | 91 | 11687 | 275 | 41 | 6 | 123 | 650 | 0 | 12873 |

Lines: 42680; strict-parse/label errors: 0; outside generate.py's line space: 23114

### TUNED config, TUNE split

| recordings | files | min | events/min | voiced events | called right % (n) | called right % (time) | hum or whistle % | talking % | files with >= 1 right | voicing recall vs Praat % | GPE vs Praat % | octave err % | median |cents| (no gross) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| hum | 1453 | 393 | 32.7 | 12201 | 48.9 | 31.4 | 49.4 | 35.5 | 93.0 | 92.8 | 2.5 | 2.0 | 4 |
| whistle | 616 | 163 | 45.0 | 7003 | 88.6 | 71.5 | 90.6 | 2.8 | 97.2 | 94.7 | 1.3 | 0.5 | 5 |

'Sounds like' of voiced events in hum recordings, by event median f0:

| f0 | hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound | n |
|---|---|---|---|---|---|---|---|---|---|
| 0-110 Hz | 198 | 0 | 154 | 2 | 11 | 9 | 29 | 0 | 403 |
| 110-160 Hz | 1514 | 0 | 1120 | 15 | 2 | 22 | 325 | 0 | 2998 |
| 160-250 Hz | 2108 | 0 | 1584 | 6 | 1 | 33 | 841 | 0 | 4573 |
| 250-400 Hz | 1750 | 0 | 1294 | 5 | 0 | 10 | 446 | 0 | 3505 |
| 400-600 Hz | 323 | 0 | 153 | 0 | 0 | 0 | 75 | 0 | 551 |
| 600-1000 Hz | 3 | 22 | 5 | 0 | 0 | 0 | 3 | 0 | 33 |
| 1000-5000 Hz | 66 | 40 | 27 | 0 | 5 | 0 | 0 | 0 | 138 |

'Sounds like' of voiced events in whistle recordings, by event median f0:

| f0 | hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound | n |
|---|---|---|---|---|---|---|---|---|---|
| 0-110 Hz | 1 | 0 | 5 | 4 | 4 | 0 | 0 | 0 | 14 |
| 110-160 Hz | 5 | 0 | 7 | 2 | 0 | 0 | 0 | 0 | 14 |
| 160-250 Hz | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 2 |
| 250-400 Hz | 3 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 6 |
| 400-600 Hz | 11 | 0 | 10 | 0 | 0 | 0 | 1 | 0 | 22 |
| 600-1000 Hz | 4 | 422 | 8 | 1 | 0 | 2 | 11 | 0 | 448 |
| 1000-5000 Hz | 110 | 5786 | 162 | 41 | 11 | 33 | 354 | 0 | 6497 |

Lines: 20210; strict-parse/label errors: 0; outside generate.py's line space: 11003

