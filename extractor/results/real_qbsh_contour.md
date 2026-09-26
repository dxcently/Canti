# REAL audio: qbsh_contour

```
MIR-QBSH (Roger Jang, NTHU): 4431 sung / hummed queries with MANUALLY labelled pitch.

Audio: 8 kHz, 8-bit unsigned PCM, mono -> upsampled to 16 kHz with scipy resample_poly (resample.to_16k;
not the 48 kHz decimator path). The band above 4 kHz is empty and 8-bit quantisation gives a
~-50 dBFS noise floor, so this is a harder, telephone-like channel than a phone mic.
Manual pitch (.pv): one value per 256 samples (32 ms, no overlap), in semitones (MIDI numbers), 0 =
unvoiced / rest. Frame i covers [32 i, 32 i + 32) ms. The corpus notes the labels were made by the
students who recorded them and are not guaranteed correct.

Speaker = the person's name in personDirInfo.txt (the same person can appear in several years).

(a) PITCH: the extractor's raw per-frame MPM pitch (FrameProcessor, the same frames the classifier
    sees; "voiced" = clarity >= voiced_clarity and energy >= floor + voiced_min_db_over_floor) is compared
    with the manual pitch at the centre of every manual frame (nearest 10 ms extractor frame). On frames the
    manual track calls voiced: voicing recall; and, where both are voiced, gross pitch error (GPE: off by
    more than 20 %), octave errors, and the absolute error in cents (all frames, and without gross errors).

(b) CONTOUR CLIPS cut from the recordings. Cutting rules (on the manual pitch only):
    1. phrase = voiced manual frames, joining runs separated by <= 2 unvoiced frames (<= 64 ms);
    2. at least 5 unvoiced manual frames (>= 160 ms) on both sides inside the recording;
    3. 150 ms <= phrase length <= 1500 ms (5..46 frames);
    4. no jump > 7 semitones between consecutive voiced frames (likely label errors / octave slips);
    5. the voiced pitch track gets a 3-frame median; start / end = median of the first / last 2 frames;
       net = end - start, hump = max - max(start, end), valley = min(start, end) - min;
    6. CLEAR-MARGIN truth (ambiguous phrases are dropped, and counted):
         flat : max(|net|, hump, valley) <= 0.5 st           (extractor boundary is 1.5 st)
         rise : net >= +2 st, hump and valley <= min(1, net/4)
         fall : net <= -2 st, hump and valley <= min(1, |net|/4)
         arch : hump >= 2 st, |net| <= hump/2, valley <= 0.5
         dip  : valley >= 2 st, |net| <= valley/2, hump <= 0.5
    7. truth excursion = the schema bucket (EXCURSION: <2, 2-4, >4 st) of |net| (rise/fall), hump (arch),
       valley (dip), max range (flat); scored only when >= 0.5 st from a bucket edge.
       truth duration = the phrase's voiced span, scored only when >= 20 % away from 150 / 400 / 1000 ms.
    8. the clip = the phrase plus 150 ms of the surrounding recording on each side (unvoiced by rule 2,
       but it can hold breaths / consonants), 10 ms fades at the cut edges, preceded by 1.0 s and followed
       by 0.6 s of the recording's own quietest 200 ms looped (so the noise floor is warm).
    9. at most MAX_PER_CLASS_SPK (8) clips per (speaker, class), 4 for flat, chosen deterministically.
    Sung-melody fragments are NOT deliberate gestures: a "rise" here is usually two or three sung notes
    stepping up, not a glide, and many are sung with lyrics (so "sounds like talking" is not always wrong).
```

Cutting outcome (test split): {"no 160 ms rest on both sides": 18769, "ambiguous shape": 1342, "length outside 150-1500 ms": 1286, "kept": 1239, "jump > 7 st or < 4 voiced frames": 35, "capped (per speaker x class)": 430}

Cutting outcome (tune split): {"no 160 ms rest on both sides": 7714, "kept": 500, "ambiguous shape": 470, "length outside 150-1500 ms": 597, "jump > 7 st or < 4 voiced frames": 24, "capped (per speaker x class)": 176}

### FROZEN config, TEST split  <- headline

| SNR | clips | contour acc % | balanced % | rise | fall | arch | dip | flat | excursion ok % (given contour ok) | duration ok % | end-to-end action ok % | extra events/clip |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| clean | 809 | 84.8 | 86.4 | 87.9 | 86.6 | 90.9 | 85.0 | 81.6 | 96.7 (n=544) | 72.1 (n=448) | 28.4 | 0.16 |
| 20 | 809 | 84.2 | 84.4 | 89.4 | 86.6 | 81.8 | 85.0 | 79.5 | 96.1 (n=538) | 71.4 (n=461) | 22.6 | 0.56 |
| 10 | 809 | 67.2 | 65.2 | 73.5 | 65.8 | 72.7 | 50.0 | 64.1 | 94.7 (n=419) | 65.4 (n=433) | 16.9 | 0.64 |
| 5 | 809 | 48.8 | 44.6 | 45.8 | 47.7 | 27.3 | 50.0 | 52.1 | 90.4 (n=314) | 60.4 (n=361) | 7.8 | 0.68 |

'Sounds like' on the matched event:

| SNR | hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound | None |
|---|---|---|---|---|---|---|---|---|---|
| clean | 398 | 1 | 359 | 11 | 2 | 0 | 6 | 0 | 32 |
| 20 | 406 | 1 | 365 | 12 | 2 | 0 | 6 | 0 | 17 |
| 10 | 397 | 8 | 316 | 13 | 3 | 10 | 11 | 0 | 51 |
| 5 | 300 | 14 | 295 | 15 | 6 | 18 | 27 | 2 | 132 |

Confusion at clean (rows = manual-pitch truth, columns = matched event label):

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| rise | 232 | 3 | 6 | 4 | 10 | 0 | 0 | 1 | 8 | 264 |
| fall | 2 | 129 | 8 | 1 | 4 | 0 | 0 | 1 | 4 | 149 |
| arch | 0 | 0 | 10 | 0 | 0 | 0 | 0 | 0 | 1 | 11 |
| dip | 2 | 0 | 0 | 17 | 0 | 0 | 0 | 0 | 1 | 20 |
| flat | 8 | 14 | 14 | 9 | 298 | 0 | 0 | 4 | 18 | 365 |

Confusion at 20 (rows = manual-pitch truth, columns = matched event label):

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| rise | 236 | 6 | 5 | 6 | 10 | 0 | 0 | 0 | 1 | 264 |
| fall | 3 | 129 | 6 | 4 | 4 | 0 | 0 | 1 | 2 | 149 |
| arch | 0 | 2 | 9 | 0 | 0 | 0 | 0 | 0 | 0 | 11 |
| dip | 1 | 0 | 2 | 17 | 0 | 0 | 0 | 0 | 0 | 20 |
| flat | 13 | 27 | 12 | 5 | 290 | 0 | 0 | 4 | 14 | 365 |

Confusion at 10 (rows = manual-pitch truth, columns = matched event label):

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| rise | 194 | 12 | 12 | 6 | 29 | 0 | 0 | 3 | 8 | 264 |
| fall | 16 | 98 | 8 | 6 | 12 | 0 | 0 | 1 | 8 | 149 |
| arch | 1 | 1 | 8 | 1 | 0 | 0 | 0 | 0 | 0 | 11 |
| dip | 6 | 3 | 1 | 10 | 0 | 0 | 0 | 0 | 0 | 20 |
| flat | 25 | 27 | 19 | 18 | 234 | 0 | 0 | 7 | 35 | 365 |

Confusion at 5 (rows = manual-pitch truth, columns = matched event label):

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| rise | 121 | 24 | 16 | 17 | 48 | 1 | 0 | 6 | 31 | 264 |
| fall | 6 | 71 | 6 | 17 | 24 | 0 | 0 | 5 | 20 | 149 |
| arch | 3 | 2 | 3 | 0 | 1 | 0 | 0 | 1 | 1 | 11 |
| dip | 1 | 7 | 0 | 10 | 0 | 0 | 0 | 1 | 1 | 20 |
| flat | 21 | 23 | 17 | 20 | 190 | 0 | 0 | 15 | 79 | 365 |

Lines: 4696; strict-parse/label errors: 0; outside generate.py's line space: 1156

### FROZEN config, TUNE split

| SNR | clips | contour acc % | balanced % | rise | fall | arch | dip | flat | excursion ok % (given contour ok) | duration ok % | end-to-end action ok % | extra events/clip |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| clean | 324 | 84.0 | 86.3 | 88.0 | 93.5 | 80.0 | 94.4 | 75.4 | 93.8 (n=195) | 68.8 (n=199) | 28.1 | 0.22 |
| 20 | 324 | 85.8 | 82.4 | 90.0 | 91.9 | 60.0 | 88.9 | 81.3 | 93.6 (n=202) | 71.6 (n=201) | 23.8 | 0.59 |
| 10 | 324 | 74.7 | 70.5 | 80.0 | 71.0 | 50.0 | 77.8 | 73.9 | 95.0 (n=181) | 68.9 (n=193) | 13.3 | 0.89 |
| 5 | 324 | 45.7 | 39.2 | 49.0 | 56.5 | 20.0 | 27.8 | 42.5 | 85.6 (n=104) | 54.7 (n=148) | 5.2 | 0.79 |

'Sounds like' on the matched event:

| SNR | hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound | None |
|---|---|---|---|---|---|---|---|---|---|
| clean | 139 | 1 | 169 | 4 | 1 | 0 | 5 | 0 | 5 |
| 20 | 149 | 1 | 164 | 3 | 1 | 0 | 2 | 0 | 4 |
| 10 | 138 | 2 | 152 | 5 | 2 | 6 | 7 | 0 | 12 |
| 5 | 96 | 8 | 125 | 8 | 3 | 6 | 12 | 0 | 66 |

Confusion at clean (rows = manual-pitch truth, columns = matched event label):

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| rise | 88 | 2 | 6 | 1 | 2 | 0 | 0 | 1 | 0 | 100 |
| fall | 0 | 58 | 2 | 0 | 2 | 0 | 0 | 0 | 0 | 62 |
| arch | 0 | 1 | 8 | 0 | 1 | 0 | 0 | 0 | 0 | 10 |
| dip | 1 | 0 | 0 | 17 | 0 | 0 | 0 | 0 | 0 | 18 |
| flat | 8 | 9 | 4 | 3 | 101 | 0 | 0 | 4 | 5 | 134 |

Confusion at 20 (rows = manual-pitch truth, columns = matched event label):

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| rise | 90 | 2 | 2 | 2 | 3 | 0 | 0 | 0 | 1 | 100 |
| fall | 1 | 57 | 1 | 1 | 2 | 0 | 0 | 0 | 0 | 62 |
| arch | 2 | 1 | 6 | 0 | 1 | 0 | 0 | 0 | 0 | 10 |
| dip | 1 | 0 | 1 | 16 | 0 | 0 | 0 | 0 | 0 | 18 |
| flat | 9 | 7 | 2 | 2 | 109 | 0 | 0 | 2 | 3 | 134 |

Confusion at 10 (rows = manual-pitch truth, columns = matched event label):

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| rise | 80 | 5 | 6 | 0 | 7 | 0 | 0 | 0 | 2 | 100 |
| fall | 2 | 44 | 5 | 4 | 6 | 0 | 0 | 0 | 1 | 62 |
| arch | 1 | 1 | 5 | 0 | 2 | 0 | 0 | 0 | 1 | 10 |
| dip | 1 | 1 | 0 | 14 | 1 | 0 | 0 | 0 | 1 | 18 |
| flat | 10 | 6 | 1 | 4 | 99 | 0 | 0 | 7 | 7 | 134 |

Confusion at 5 (rows = manual-pitch truth, columns = matched event label):

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| rise | 49 | 8 | 8 | 12 | 9 | 0 | 0 | 2 | 12 | 100 |
| fall | 4 | 35 | 1 | 4 | 9 | 0 | 0 | 2 | 7 | 62 |
| arch | 1 | 1 | 2 | 1 | 1 | 0 | 0 | 0 | 4 | 10 |
| dip | 4 | 4 | 3 | 5 | 0 | 0 | 0 | 0 | 2 | 18 |
| flat | 10 | 8 | 4 | 6 | 57 | 0 | 0 | 8 | 41 | 134 |

Lines: 2034; strict-parse/label errors: 0; outside generate.py's line space: 565

### FIXED config, TEST split

| SNR | clips | contour acc % | balanced % | rise | fall | arch | dip | flat | excursion ok % (given contour ok) | duration ok % | end-to-end action ok % | extra events/clip |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| clean | 809 | 86.0 | 90.0 | 89.8 | 88.6 | 100.0 | 90.0 | 81.6 | 96.9 (n=550) | 70.2 (n=456) | 28.2 | 0.17 |
| 20 | 809 | 84.4 | 84.7 | 89.8 | 87.2 | 81.8 | 85.0 | 79.5 | 95.7 (n=540) | 70.1 (n=462) | 22.6 | 0.56 |
| 10 | 809 | 67.1 | 66.1 | 72.7 | 65.8 | 72.7 | 55.0 | 64.1 | 95.2 (n=416) | 64.5 (n=440) | 16.2 | 0.68 |
| 5 | 809 | 48.7 | 44.5 | 46.6 | 47.7 | 27.3 | 50.0 | 51.2 | 90.1 (n=312) | 58.5 (n=371) | 7.3 | 0.68 |

'Sounds like' on the matched event:

| SNR | hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound | None |
|---|---|---|---|---|---|---|---|---|---|
| clean | 394 | 1 | 378 | 14 | 1 | 0 | 8 | 0 | 13 |
| 20 | 403 | 1 | 370 | 13 | 2 | 0 | 6 | 0 | 14 |
| 10 | 389 | 8 | 336 | 12 | 3 | 10 | 16 | 0 | 35 |
| 5 | 292 | 15 | 321 | 14 | 6 | 18 | 28 | 0 | 115 |

Confusion at clean (rows = manual-pitch truth, columns = matched event label):

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| rise | 237 | 3 | 6 | 4 | 12 | 0 | 0 | 2 | 0 | 264 |
| fall | 2 | 132 | 8 | 1 | 4 | 0 | 0 | 1 | 1 | 149 |
| arch | 0 | 0 | 11 | 0 | 0 | 0 | 0 | 0 | 0 | 11 |
| dip | 2 | 0 | 0 | 18 | 0 | 0 | 0 | 0 | 0 | 20 |
| flat | 9 | 17 | 14 | 10 | 298 | 0 | 0 | 5 | 12 | 365 |

Confusion at 20 (rows = manual-pitch truth, columns = matched event label):

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| rise | 237 | 6 | 5 | 6 | 9 | 0 | 0 | 0 | 1 | 264 |
| fall | 3 | 130 | 6 | 4 | 4 | 0 | 0 | 1 | 1 | 149 |
| arch | 0 | 2 | 9 | 0 | 0 | 0 | 0 | 0 | 0 | 11 |
| dip | 1 | 0 | 2 | 17 | 0 | 0 | 0 | 0 | 0 | 20 |
| flat | 14 | 28 | 12 | 5 | 290 | 0 | 0 | 4 | 12 | 365 |

Confusion at 10 (rows = manual-pitch truth, columns = matched event label):

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| rise | 192 | 11 | 13 | 10 | 28 | 0 | 0 | 5 | 5 | 264 |
| fall | 16 | 98 | 10 | 6 | 11 | 0 | 0 | 1 | 7 | 149 |
| arch | 1 | 1 | 8 | 1 | 0 | 0 | 0 | 0 | 0 | 11 |
| dip | 5 | 3 | 1 | 11 | 0 | 0 | 0 | 0 | 0 | 20 |
| flat | 26 | 30 | 20 | 22 | 234 | 0 | 0 | 10 | 23 | 365 |

Confusion at 5 (rows = manual-pitch truth, columns = matched event label):

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| rise | 123 | 27 | 15 | 20 | 48 | 0 | 0 | 5 | 26 | 264 |
| fall | 6 | 71 | 6 | 18 | 24 | 0 | 0 | 6 | 18 | 149 |
| arch | 3 | 2 | 3 | 0 | 1 | 0 | 0 | 1 | 1 | 11 |
| dip | 1 | 7 | 0 | 10 | 0 | 0 | 0 | 1 | 1 | 20 |
| flat | 22 | 29 | 18 | 25 | 187 | 0 | 0 | 15 | 69 | 365 |

Lines: 4782; strict-parse/label errors: 0; outside generate.py's line space: 1260

### FIXED config, TUNE split

| SNR | clips | contour acc % | balanced % | rise | fall | arch | dip | flat | excursion ok % (given contour ok) | duration ok % | end-to-end action ok % | extra events/clip |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| clean | 324 | 84.3 | 86.4 | 88.0 | 93.5 | 80.0 | 94.4 | 76.1 | 93.9 (n=196) | 68.5 (n=200) | 26.9 | 0.23 |
| 20 | 324 | 85.8 | 82.3 | 90.0 | 90.3 | 60.0 | 88.9 | 82.1 | 94.1 (n=203) | 70.8 (n=202) | 23.1 | 0.60 |
| 10 | 324 | 74.4 | 71.1 | 79.0 | 69.4 | 50.0 | 83.3 | 73.9 | 95.0 (n=181) | 67.9 (n=196) | 13.3 | 0.93 |
| 5 | 324 | 46.9 | 41.0 | 51.0 | 58.1 | 20.0 | 33.3 | 42.5 | 84.9 (n=106) | 53.1 (n=160) | 4.9 | 0.91 |

'Sounds like' on the matched event:

| SNR | hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound | None |
|---|---|---|---|---|---|---|---|---|---|
| clean | 135 | 1 | 175 | 4 | 1 | 0 | 6 | 0 | 2 |
| 20 | 146 | 1 | 167 | 3 | 1 | 0 | 2 | 0 | 4 |
| 10 | 135 | 2 | 160 | 5 | 2 | 6 | 7 | 0 | 7 |
| 5 | 97 | 12 | 136 | 8 | 1 | 7 | 13 | 0 | 50 |

Confusion at clean (rows = manual-pitch truth, columns = matched event label):

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| rise | 88 | 2 | 6 | 1 | 2 | 0 | 0 | 1 | 0 | 100 |
| fall | 0 | 58 | 2 | 0 | 2 | 0 | 0 | 0 | 0 | 62 |
| arch | 0 | 1 | 8 | 0 | 1 | 0 | 0 | 0 | 0 | 10 |
| dip | 1 | 0 | 0 | 17 | 0 | 0 | 0 | 0 | 0 | 18 |
| flat | 9 | 9 | 4 | 3 | 102 | 0 | 0 | 5 | 2 | 134 |

Confusion at 20 (rows = manual-pitch truth, columns = matched event label):

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| rise | 90 | 2 | 2 | 2 | 3 | 0 | 0 | 0 | 1 | 100 |
| fall | 1 | 56 | 1 | 1 | 2 | 0 | 0 | 0 | 1 | 62 |
| arch | 2 | 1 | 6 | 0 | 1 | 0 | 0 | 0 | 0 | 10 |
| dip | 1 | 0 | 1 | 16 | 0 | 0 | 0 | 0 | 0 | 18 |
| flat | 9 | 7 | 2 | 2 | 110 | 0 | 0 | 2 | 2 | 134 |

Confusion at 10 (rows = manual-pitch truth, columns = matched event label):

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| rise | 79 | 6 | 7 | 1 | 6 | 0 | 0 | 0 | 1 | 100 |
| fall | 2 | 43 | 5 | 6 | 5 | 0 | 0 | 0 | 1 | 62 |
| arch | 1 | 1 | 5 | 0 | 2 | 0 | 0 | 0 | 1 | 10 |
| dip | 1 | 1 | 0 | 15 | 1 | 0 | 0 | 0 | 0 | 18 |
| flat | 11 | 7 | 2 | 4 | 99 | 0 | 0 | 7 | 4 | 134 |

Confusion at 5 (rows = manual-pitch truth, columns = matched event label):

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| rise | 51 | 9 | 7 | 14 | 9 | 0 | 0 | 2 | 8 | 100 |
| fall | 4 | 36 | 1 | 6 | 8 | 0 | 0 | 2 | 5 | 62 |
| arch | 0 | 1 | 2 | 2 | 1 | 0 | 0 | 0 | 4 | 10 |
| dip | 3 | 4 | 4 | 6 | 0 | 0 | 0 | 0 | 1 | 18 |
| flat | 12 | 10 | 4 | 10 | 57 | 0 | 0 | 9 | 32 | 134 |

Lines: 2112; strict-parse/label errors: 0; outside generate.py's line space: 627

### TUNED config, TEST split

| SNR | clips | contour acc % | balanced % | rise | fall | arch | dip | flat | excursion ok % (given contour ok) | duration ok % | end-to-end action ok % | extra events/clip |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| clean | 809 | 86.0 | 90.0 | 89.8 | 88.6 | 100.0 | 90.0 | 81.6 | 96.9 (n=550) | 70.2 (n=456) | 30.5 | 0.10 |
| 20 | 809 | 84.4 | 84.7 | 89.8 | 87.2 | 81.8 | 85.0 | 79.5 | 95.7 (n=540) | 70.1 (n=462) | 24.8 | 0.38 |
| 10 | 809 | 67.1 | 66.1 | 72.7 | 65.8 | 72.7 | 55.0 | 64.1 | 95.2 (n=416) | 64.5 (n=440) | 18.5 | 0.51 |
| 5 | 809 | 48.7 | 44.5 | 46.6 | 47.7 | 27.3 | 50.0 | 51.2 | 90.1 (n=312) | 58.5 (n=371) | 8.8 | 0.57 |

'Sounds like' on the matched event:

| SNR | hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound | None |
|---|---|---|---|---|---|---|---|---|---|
| clean | 393 | 1 | 379 | 14 | 1 | 0 | 8 | 0 | 13 |
| 20 | 403 | 1 | 370 | 13 | 2 | 0 | 6 | 0 | 14 |
| 10 | 389 | 8 | 336 | 12 | 3 | 10 | 16 | 0 | 35 |
| 5 | 292 | 15 | 321 | 14 | 6 | 18 | 28 | 0 | 115 |

Confusion at clean (rows = manual-pitch truth, columns = matched event label):

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| rise | 237 | 3 | 6 | 4 | 12 | 0 | 0 | 2 | 0 | 264 |
| fall | 2 | 132 | 8 | 1 | 4 | 0 | 0 | 1 | 1 | 149 |
| arch | 0 | 0 | 11 | 0 | 0 | 0 | 0 | 0 | 0 | 11 |
| dip | 2 | 0 | 0 | 18 | 0 | 0 | 0 | 0 | 0 | 20 |
| flat | 9 | 17 | 14 | 10 | 298 | 0 | 0 | 5 | 12 | 365 |

Confusion at 20 (rows = manual-pitch truth, columns = matched event label):

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| rise | 237 | 6 | 5 | 6 | 9 | 0 | 0 | 0 | 1 | 264 |
| fall | 3 | 130 | 6 | 4 | 4 | 0 | 0 | 1 | 1 | 149 |
| arch | 0 | 2 | 9 | 0 | 0 | 0 | 0 | 0 | 0 | 11 |
| dip | 1 | 0 | 2 | 17 | 0 | 0 | 0 | 0 | 0 | 20 |
| flat | 14 | 28 | 12 | 5 | 290 | 0 | 0 | 4 | 12 | 365 |

Confusion at 10 (rows = manual-pitch truth, columns = matched event label):

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| rise | 192 | 11 | 13 | 10 | 28 | 0 | 0 | 5 | 5 | 264 |
| fall | 16 | 98 | 10 | 6 | 11 | 0 | 0 | 1 | 7 | 149 |
| arch | 1 | 1 | 8 | 1 | 0 | 0 | 0 | 0 | 0 | 11 |
| dip | 5 | 3 | 1 | 11 | 0 | 0 | 0 | 0 | 0 | 20 |
| flat | 26 | 30 | 20 | 22 | 234 | 0 | 0 | 10 | 23 | 365 |

Confusion at 5 (rows = manual-pitch truth, columns = matched event label):

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| rise | 123 | 27 | 15 | 20 | 48 | 0 | 0 | 5 | 26 | 264 |
| fall | 6 | 71 | 6 | 18 | 24 | 0 | 0 | 6 | 18 | 149 |
| arch | 3 | 2 | 3 | 0 | 1 | 0 | 0 | 1 | 1 | 11 |
| dip | 1 | 7 | 0 | 10 | 0 | 0 | 0 | 1 | 1 | 20 |
| flat | 22 | 29 | 18 | 25 | 187 | 0 | 0 | 15 | 69 | 365 |

Lines: 4343; strict-parse/label errors: 0; outside generate.py's line space: 1267

### TUNED config, TUNE split

| SNR | clips | contour acc % | balanced % | rise | fall | arch | dip | flat | excursion ok % (given contour ok) | duration ok % | end-to-end action ok % | extra events/clip |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| clean | 324 | 84.3 | 86.4 | 88.0 | 93.5 | 80.0 | 94.4 | 76.1 | 93.9 (n=196) | 68.5 (n=200) | 29.6 | 0.09 |
| 20 | 324 | 85.5 | 82.1 | 90.0 | 90.3 | 60.0 | 88.9 | 81.3 | 94.1 (n=202) | 71.1 (n=201) | 25.0 | 0.42 |
| 10 | 324 | 74.4 | 71.1 | 79.0 | 69.4 | 50.0 | 83.3 | 73.9 | 95.0 (n=181) | 67.9 (n=196) | 15.4 | 0.71 |
| 5 | 324 | 46.9 | 41.0 | 51.0 | 58.1 | 20.0 | 33.3 | 42.5 | 84.9 (n=106) | 53.1 (n=160) | 5.6 | 0.77 |

'Sounds like' on the matched event:

| SNR | hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound | None |
|---|---|---|---|---|---|---|---|---|---|
| clean | 135 | 1 | 175 | 4 | 1 | 0 | 6 | 0 | 2 |
| 20 | 146 | 1 | 167 | 3 | 0 | 0 | 2 | 1 | 4 |
| 10 | 135 | 2 | 160 | 5 | 2 | 6 | 7 | 0 | 7 |
| 5 | 96 | 12 | 137 | 8 | 1 | 7 | 12 | 1 | 50 |

Confusion at clean (rows = manual-pitch truth, columns = matched event label):

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| rise | 88 | 2 | 6 | 1 | 2 | 0 | 0 | 1 | 0 | 100 |
| fall | 0 | 58 | 2 | 0 | 2 | 0 | 0 | 0 | 0 | 62 |
| arch | 0 | 1 | 8 | 0 | 1 | 0 | 0 | 0 | 0 | 10 |
| dip | 1 | 0 | 0 | 17 | 0 | 0 | 0 | 0 | 0 | 18 |
| flat | 9 | 9 | 4 | 3 | 102 | 0 | 0 | 5 | 2 | 134 |

Confusion at 20 (rows = manual-pitch truth, columns = matched event label):

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| rise | 90 | 2 | 2 | 2 | 3 | 0 | 0 | 0 | 1 | 100 |
| fall | 1 | 56 | 1 | 1 | 2 | 0 | 0 | 0 | 1 | 62 |
| arch | 2 | 1 | 6 | 0 | 1 | 0 | 0 | 0 | 0 | 10 |
| dip | 1 | 0 | 1 | 16 | 0 | 0 | 0 | 0 | 0 | 18 |
| flat | 9 | 7 | 2 | 2 | 109 | 1 | 0 | 2 | 2 | 134 |

Confusion at 10 (rows = manual-pitch truth, columns = matched event label):

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| rise | 79 | 6 | 7 | 1 | 6 | 0 | 0 | 0 | 1 | 100 |
| fall | 2 | 43 | 5 | 6 | 5 | 0 | 0 | 0 | 1 | 62 |
| arch | 1 | 1 | 5 | 0 | 2 | 0 | 0 | 0 | 1 | 10 |
| dip | 1 | 1 | 0 | 15 | 1 | 0 | 0 | 0 | 0 | 18 |
| flat | 11 | 7 | 2 | 4 | 99 | 0 | 0 | 7 | 4 | 134 |

Confusion at 5 (rows = manual-pitch truth, columns = matched event label):

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| rise | 51 | 9 | 7 | 14 | 9 | 0 | 0 | 2 | 8 | 100 |
| fall | 4 | 36 | 1 | 6 | 8 | 0 | 0 | 2 | 5 | 62 |
| arch | 0 | 1 | 2 | 2 | 1 | 0 | 0 | 0 | 4 | 10 |
| dip | 3 | 4 | 4 | 6 | 0 | 0 | 0 | 0 | 1 | 18 |
| flat | 12 | 10 | 4 | 10 | 57 | 1 | 0 | 8 | 32 | 134 |

Lines: 1884; strict-parse/label errors: 0; outside generate.py's line space: 627

### Pitch tracker vs manual pitch, FROZEN config, TEST split (lag 0)

| metric | value (%, or cents) |
|---|---|
| files | 3035 |
| ref_voiced_frames | 545909 |
| voicing_recall | 89.8 |
| false_voicing_on_ref_unvoiced | 11.6 |
| compared_frames | 490327 |
| gpe_20pct | 0.6 |
| octave_err | 0.4 |
| err_over_1st | 0.7 |
| mean_abs_cents_all | 22.3 |
| mean_abs_cents_fine | 12.5 |
| median_abs_cents_fine | 10.3 |
| median_signed_cents_fine | -1.9 |
| files_gpe_over_20pct | 0.1 |

Alignment check, GPE at lag -16 / 0 / +16 ms: 0.8 / 0.6 / 0.7 %

### Pitch tracker vs manual pitch, FROZEN config, TUNE split (lag 0)

| metric | value (%, or cents) |
|---|---|
| files | 1396 |
| ref_voiced_frames | 260561 |
| voicing_recall | 88.2 |
| false_voicing_on_ref_unvoiced | 10.2 |
| compared_frames | 229802 |
| gpe_20pct | 0.6 |
| octave_err | 0.5 |
| err_over_1st | 0.8 |
| mean_abs_cents_all | 22.6 |
| mean_abs_cents_fine | 13.0 |
| median_abs_cents_fine | 10.7 |
| median_signed_cents_fine | -1.7 |
| files_gpe_over_20pct | 0.1 |

Alignment check, GPE at lag -16 / 0 / +16 ms: 0.7 / 0.6 / 0.7 %

### Pitch tracker vs manual pitch, FIXED config, TEST split (lag 0)

| metric | value (%, or cents) |
|---|---|
| files | 3035 |
| ref_voiced_frames | 545909 |
| voicing_recall | 92.5 |
| false_voicing_on_ref_unvoiced | 12.5 |
| compared_frames | 504793 |
| gpe_20pct | 0.6 |
| octave_err | 0.4 |
| err_over_1st | 0.8 |
| mean_abs_cents_all | 22.4 |
| mean_abs_cents_fine | 12.5 |
| median_abs_cents_fine | 10.3 |
| median_signed_cents_fine | -1.9 |
| files_gpe_over_20pct | 0.1 |

Alignment check, GPE at lag -16 / 0 / +16 ms: 0.8 / 0.6 / 0.7 %

### Pitch tracker vs manual pitch, FIXED config, TUNE split (lag 0)

| metric | value (%, or cents) |
|---|---|
| files | 1396 |
| ref_voiced_frames | 260561 |
| voicing_recall | 91.3 |
| false_voicing_on_ref_unvoiced | 11.3 |
| compared_frames | 238010 |
| gpe_20pct | 0.6 |
| octave_err | 0.4 |
| err_over_1st | 0.8 |
| mean_abs_cents_all | 22.6 |
| mean_abs_cents_fine | 13.0 |
| median_abs_cents_fine | 10.6 |
| median_signed_cents_fine | -1.7 |
| files_gpe_over_20pct | 0.1 |

Alignment check, GPE at lag -16 / 0 / +16 ms: 0.7 / 0.6 / 0.7 %

