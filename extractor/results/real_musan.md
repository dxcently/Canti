# REAL audio: musan

```
MUSAN (OpenSLR 17) as NEGATIVES: speech/, music/ and noise/ must yield no gesture.

  * speech: librivox read speech (several languages) and US-government hearings (English). One file is one
    recording session; no speaker IDs are given, so the split is by file.
  * music: fma, fma-western-art, hd-classical, jamendo, rfm; split BY ARTIST (ANNOTATIONS column 4);
    vocals Y/N from ANNOTATIONS column 3.
  * noise: free-sound and sound-bible technical / ambient noises (DTMF, dial tones, rain, traffic, clapping,
    animals ...); split by file. The same split's noise files are what the other scripts mix into positives.
Each file contributes one excerpt of at most EXCERPT_S seconds (from OFFSET_S in, or the whole file if it is
short). All MUSAN audio is 16 kHz mono.

A negative "false accept" = a phone-style group (gap <= 600 ms) whose default-profile action is not none.
We also report fireable events per minute (each event judged alone) and the "sounds like" distribution: speech
should say "talking", music "background music", but the requirement is only "no gesture".
```

### FROZEN config, TEST split  <- headline

| subset | files | min | events/min | FA groups/min | fireable events/min | files with FA % | actions |
|---|---|---|---|---|---|---|---|
| speech (all) | 297 | 295 | 43.8 | 0.92 | 5.50 | 54.9 | swipe_down 113, swipe_up 46, tap 43, swipe_right 29, swipe_left 20, long_press 17, listen_for_phrase 3, back 2 |
| speech/librivox | 121 | 121 | 34.3 | 0.38 | 2.15 | 30.6 | swipe_down 19, swipe_left 8, tap 7, swipe_up 3, long_press 3, listen_for_phrase 3, back 2, swipe_right 1 |
| speech/us-gov | 176 | 175 | 50.4 | 1.30 | 7.81 | 71.6 | swipe_down 94, swipe_up 43, tap 36, swipe_right 28, long_press 14, swipe_left 12 |
| music (all) | 522 | 518 | 38.5 | 2.29 | 8.69 | 67.4 | tap 719, swipe_down 145, long_press 115, swipe_up 95, swipe_left 62, swipe_right 46, back 2, listen_for_phrase 1 |
| music with vocals | 165 | 165 | 36.0 | 1.94 | 8.36 | 66.1 | tap 235, long_press 24, swipe_down 23, swipe_up 17, swipe_left 10, swipe_right 9, back 1, listen_for_phrase 1 |
| music without vocals | 348 | 344 | 39.9 | 2.46 | 8.84 | 68.1 | tap 470, swipe_down 122, long_press 90, swipe_up 77, swipe_left 51, swipe_right 37, back 1 |
| noise (all) | 673 | 214 | 30.9 | 2.39 | 9.35 | 36.0 | tap 252, long_press 76, back 65, swipe_down 45, swipe_up 27, swipe_right 22, swipe_left 17, listen_for_phrase 7 |

'Sounds like' of all events (counts):

| subset | hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound |
|---|---|---|---|---|---|---|---|---|
| speech (all) | 2716 | 11 | 7620 | 1119 | 110 | 460 | 436 | 477 |
| speech/librivox | 363 | 5 | 2621 | 525 | 81 | 257 | 132 | 161 |
| speech/us-gov | 2353 | 6 | 4999 | 594 | 29 | 203 | 304 | 316 |
| music (all) | 4005 | 236 | 3540 | 70 | 82 | 1020 | 7958 | 3054 |
| music with vocals | 833 | 49 | 1141 | 20 | 16 | 222 | 2541 | 1113 |
| music without vocals | 3104 | 186 | 2331 | 46 | 52 | 777 | 5338 | 1889 |
| noise (all) | 578 | 510 | 404 | 121 | 246 | 140 | 2296 | 2317 |

Labels of events that would fire alone:

| subset | labels |
|---|---|
| speech (all) | fall 625, pop 371, rise 222, arch 154, flat 145, dip 82, hiss 25 |
| speech/librivox | pop 81, fall 75, rise 31, dip 23, hiss 22, arch 16, flat 12 |
| speech/us-gov | fall 550, pop 290, rise 191, arch 138, flat 133, dip 59, hiss 3 |
| music (all) | pop 2851, fall 489, flat 439, rise 360, dip 190, arch 161, hiss 10 |
| music with vocals | pop 1045, flat 104, fall 91, rise 75, dip 34, arch 29, hiss 1 |
| music without vocals | pop 1754, fall 397, flat 325, rise 272, dip 153, arch 132, hiss 9 |
| noise (all) | pop 1175, hiss 325, flat 211, fall 113, rise 75, arch 59, dip 40 |

Lines: 39526; strict-parse/label errors: 0; outside generate.py's line space: 12329

### FROZEN config, TUNE split

| subset | files | min | events/min | FA groups/min | fireable events/min | files with FA % | actions |
|---|---|---|---|---|---|---|---|
| speech (all) | 129 | 129 | 41.8 | 0.85 | 4.59 | 53.5 | swipe_down 55, tap 14, swipe_up 14, swipe_right 11, long_press 10, swipe_left 4, back 2 |
| speech/librivox | 52 | 52 | 33.4 | 0.33 | 1.64 | 25.0 | swipe_down 7, swipe_up 3, swipe_right 2, tap 2, back 2, swipe_left 1 |
| speech/us-gov | 77 | 77 | 47.5 | 1.21 | 6.58 | 72.7 | swipe_down 48, tap 12, swipe_up 11, long_press 10, swipe_right 9, swipe_left 3 |
| music (all) | 138 | 138 | 35.9 | 2.42 | 9.86 | 73.9 | tap 142, swipe_down 66, swipe_up 46, long_press 35, swipe_right 25, swipe_left 19 |
| music with vocals | 61 | 61 | 33.4 | 2.61 | 8.31 | 72.1 | tap 89, long_press 22, swipe_up 19, swipe_down 17, swipe_left 7, swipe_right 5 |
| music without vocals | 71 | 71 | 34.6 | 2.27 | 10.57 | 76.1 | swipe_down 48, tap 43, swipe_up 26, swipe_right 18, long_press 13, swipe_left 12 |
| noise (all) | 257 | 75 | 35.2 | 3.07 | 12.44 | 38.9 | tap 102, back 35, long_press 23, swipe_left 21, swipe_right 18, swipe_up 18, swipe_down 9, listen_for_phrase 5 |

'Sounds like' of all events (counts):

| subset | hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound |
|---|---|---|---|---|---|---|---|---|
| speech (all) | 1050 | 4 | 3217 | 546 | 59 | 205 | 152 | 153 |
| speech/librivox | 135 | 3 | 1102 | 244 | 37 | 116 | 44 | 49 |
| speech/us-gov | 915 | 1 | 2115 | 302 | 22 | 89 | 108 | 104 |
| music (all) | 1388 | 94 | 1059 | 10 | 3 | 343 | 1305 | 731 |
| music with vocals | 389 | 5 | 419 | 4 | 1 | 119 | 742 | 355 |
| music without vocals | 892 | 89 | 558 | 6 | 1 | 219 | 375 | 300 |
| noise (all) | 140 | 163 | 89 | 54 | 69 | 43 | 922 | 1167 |

Labels of events that would fire alone:

| subset | labels |
|---|---|
| speech (all) | fall 242, pop 118, rise 87, arch 63, flat 44, dip 26, hiss 12 |
| speech/librivox | fall 27, pop 26, rise 14, hiss 11, arch 4, dip 3 |
| speech/us-gov | fall 215, pop 92, rise 73, arch 59, flat 44, dip 23, hiss 1 |
| music (all) | pop 710, fall 243, rise 147, flat 91, dip 87, arch 76, hiss 2 |
| music with vocals | pop 346, fall 50, flat 44, rise 38, dip 17, arch 12 |
| music without vocals | pop 288, fall 185, rise 102, dip 69, arch 56, flat 44, hiss 2 |
| noise (all) | pop 577, hiss 172, flat 78, rise 36, dip 27, arch 24, fall 21 |

Lines: 12966; strict-parse/label errors: 0; outside generate.py's line space: 4190

### FIXED config, TEST split

| subset | files | min | events/min | FA groups/min | fireable events/min | files with FA % | actions |
|---|---|---|---|---|---|---|---|
| speech (all) | 297 | 295 | 42.1 | 0.79 | 4.97 | 47.5 | swipe_down 104, swipe_up 40, tap 27, swipe_right 27, swipe_left 15, long_press 15, listen_for_phrase 3, back 1 |
| speech/librivox | 121 | 121 | 32.6 | 0.26 | 1.80 | 21.5 | swipe_down 14, tap 5, swipe_left 5, swipe_up 3, listen_for_phrase 3, back 1, long_press 1 |
| speech/us-gov | 176 | 175 | 48.7 | 1.15 | 7.17 | 65.3 | swipe_down 90, swipe_up 37, swipe_right 27, tap 22, long_press 14, swipe_left 10 |
| music (all) | 522 | 518 | 37.5 | 2.13 | 8.17 | 64.9 | tap 670, swipe_down 142, long_press 104, swipe_up 84, swipe_left 57, swipe_right 44, back 1, listen_for_phrase 1 |
| music with vocals | 165 | 165 | 34.9 | 1.77 | 7.73 | 61.2 | tap 217, swipe_down 22, long_press 20, swipe_up 16, swipe_left 8, swipe_right 7, back 1, listen_for_phrase 1 |
| music without vocals | 348 | 344 | 38.8 | 2.31 | 8.36 | 66.7 | tap 440, swipe_down 120, long_press 83, swipe_up 67, swipe_left 48, swipe_right 37 |
| noise (all) | 673 | 214 | 30.3 | 2.16 | 8.76 | 34.0 | tap 221, long_press 69, back 63, swipe_down 43, swipe_up 27, swipe_right 20, swipe_left 14, listen_for_phrase 4 |

'Sounds like' of all events (counts):

| subset | hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound |
|---|---|---|---|---|---|---|---|---|
| speech (all) | 2529 | 10 | 7326 | 1084 | 119 | 555 | 431 | 378 |
| speech/librivox | 310 | 5 | 2452 | 509 | 92 | 305 | 133 | 130 |
| speech/us-gov | 2219 | 5 | 4874 | 575 | 27 | 250 | 298 | 248 |
| music (all) | 3854 | 226 | 3422 | 62 | 79 | 1135 | 7795 | 2851 |
| music with vocals | 803 | 46 | 1105 | 18 | 16 | 249 | 2484 | 1039 |
| music without vocals | 2985 | 178 | 2250 | 42 | 50 | 862 | 5237 | 1761 |
| noise (all) | 559 | 563 | 407 | 123 | 246 | 148 | 2261 | 2165 |

Labels of events that would fire alone:

| subset | labels |
|---|---|
| speech (all) | fall 587, pop 284, rise 216, arch 144, flat 134, dip 81, hiss 23 |
| speech/librivox | pop 61, fall 61, rise 29, dip 21, hiss 20, arch 14, flat 11 |
| speech/us-gov | fall 526, pop 223, rise 187, arch 130, flat 123, dip 60, hiss 3 |
| music (all) | pop 2653, fall 482, flat 420, rise 331, dip 178, arch 157, hiss 10 |
| music with vocals | pop 971, flat 101, fall 79, rise 63, dip 32, arch 29, hiss 1 |
| music without vocals | pop 1631, fall 401, flat 310, rise 254, dip 143, arch 128, hiss 9 |
| noise (all) | pop 1081, hiss 315, flat 197, fall 109, rise 75, arch 58, dip 37 |

Lines: 38328; strict-parse/label errors: 0; outside generate.py's line space: 12513

### FIXED config, TUNE split

| subset | files | min | events/min | FA groups/min | fireable events/min | files with FA % | actions |
|---|---|---|---|---|---|---|---|
| speech (all) | 129 | 129 | 39.9 | 0.75 | 4.18 | 46.5 | swipe_down 53, swipe_up 14, tap 9, long_press 9, swipe_right 7, swipe_left 3, back 1 |
| speech/librivox | 52 | 52 | 31.8 | 0.25 | 1.33 | 19.2 | swipe_down 5, swipe_up 4, swipe_left 1, back 1, swipe_right 1, tap 1 |
| speech/us-gov | 77 | 77 | 45.4 | 1.08 | 6.09 | 64.9 | swipe_down 48, swipe_up 10, long_press 9, tap 8, swipe_right 6, swipe_left 2 |
| music (all) | 138 | 138 | 34.6 | 2.24 | 8.99 | 69.6 | tap 131, swipe_down 62, swipe_up 43, long_press 31, swipe_right 26, swipe_left 15 |
| music with vocals | 61 | 61 | 32.1 | 2.46 | 7.46 | 68.9 | tap 85, long_press 19, swipe_down 18, swipe_up 17, swipe_left 6, swipe_right 5 |
| music without vocals | 71 | 71 | 33.2 | 2.04 | 9.69 | 70.4 | swipe_down 43, tap 36, swipe_up 25, swipe_right 19, long_press 12, swipe_left 9 |
| noise (all) | 257 | 75 | 34.8 | 3.01 | 12.08 | 38.9 | tap 96, back 34, swipe_left 24, long_press 23, swipe_up 18, swipe_right 16, swipe_down 10, listen_for_phrase 5 |

'Sounds like' of all events (counts):

| subset | hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound |
|---|---|---|---|---|---|---|---|---|
| speech (all) | 971 | 5 | 3071 | 519 | 61 | 252 | 145 | 121 |
| speech/librivox | 114 | 3 | 1042 | 235 | 38 | 135 | 40 | 40 |
| speech/us-gov | 857 | 2 | 2029 | 284 | 23 | 117 | 105 | 81 |
| music (all) | 1331 | 91 | 1030 | 7 | 6 | 374 | 1270 | 648 |
| music with vocals | 373 | 4 | 403 | 4 | 3 | 141 | 718 | 314 |
| music without vocals | 852 | 87 | 544 | 3 | 2 | 228 | 367 | 263 |
| noise (all) | 146 | 173 | 88 | 52 | 69 | 47 | 916 | 1122 |

Labels of events that would fire alone:

| subset | labels |
|---|---|
| speech (all) | fall 231, pop 89, rise 80, arch 61, flat 45, dip 21, hiss 11 |
| speech/librivox | fall 23, pop 19, hiss 10, rise 10, arch 5, dip 2 |
| speech/us-gov | fall 208, pop 70, rise 70, arch 56, flat 45, dip 19, hiss 1 |
| music (all) | pop 629, fall 235, rise 134, flat 87, dip 79, arch 71, hiss 2 |
| music with vocals | pop 306, fall 49, flat 40, rise 33, dip 16, arch 11 |
| music without vocals | pop 252, fall 178, rise 94, dip 62, arch 52, flat 44, hiss 2 |
| noise (all) | pop 549, hiss 169, flat 80, rise 35, dip 32, arch 23, fall 20 |

Lines: 12515; strict-parse/label errors: 0; outside generate.py's line space: 4232

### TUNED config, TEST split

| subset | files | min | events/min | FA groups/min | fireable events/min | files with FA % | actions |
|---|---|---|---|---|---|---|---|
| speech (all) | 297 | 295 | 41.4 | 0.74 | 4.16 | 45.5 | swipe_down 107, swipe_up 43, swipe_right 29, long_press 16, swipe_left 15, tap 6, back 1, listen_for_phrase 1 |
| speech/librivox | 121 | 121 | 32.2 | 0.24 | 1.47 | 19.8 | swipe_down 16, swipe_left 5, swipe_up 3, tap 2, back 1, long_press 1, listen_for_phrase 1 |
| speech/us-gov | 176 | 175 | 47.8 | 1.08 | 6.01 | 63.1 | swipe_down 91, swipe_up 40, swipe_right 29, long_press 15, swipe_left 10, tap 4 |
| music (all) | 522 | 518 | 32.6 | 0.89 | 3.26 | 39.5 | swipe_down 148, long_press 107, swipe_up 91, swipe_left 57, swipe_right 45, tap 12, back 1 |
| music with vocals | 165 | 165 | 29.2 | 0.49 | 2.03 | 25.5 | swipe_down 22, long_press 20, swipe_up 17, swipe_left 8, swipe_right 8, tap 5, back 1 |
| music without vocals | 348 | 344 | 34.4 | 1.09 | 3.84 | 46.0 | swipe_down 125, long_press 86, swipe_up 71, swipe_left 48, swipe_right 37, tap 7 |
| noise (all) | 673 | 214 | 26.0 | 1.44 | 5.48 | 22.6 | tap 73, long_press 70, back 55, swipe_down 45, swipe_up 29, swipe_right 19, swipe_left 15, listen_for_phrase 2 |

'Sounds like' of all events (counts):

| subset | hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound |
|---|---|---|---|---|---|---|---|---|
| speech (all) | 2534 | 10 | 7369 | 1084 | 119 | 555 | 429 | 127 |
| speech/librivox | 312 | 5 | 2452 | 509 | 92 | 305 | 130 | 82 |
| speech/us-gov | 2222 | 5 | 4917 | 575 | 27 | 250 | 299 | 45 |
| music (all) | 3904 | 226 | 3459 | 62 | 78 | 1135 | 7796 | 247 |
| music with vocals | 820 | 46 | 1117 | 18 | 16 | 249 | 2484 | 70 |
| music without vocals | 3018 | 178 | 2275 | 42 | 50 | 862 | 5238 | 174 |
| noise (all) | 572 | 563 | 410 | 123 | 203 | 148 | 2221 | 1317 |

Labels of events that would fire alone:

| subset | labels |
|---|---|
| speech (all) | fall 582, rise 216, arch 143, flat 133, dip 80, pop 52, hiss 22 |
| speech/librivox | fall 61, rise 29, pop 23, dip 21, hiss 19, arch 14, flat 11 |
| speech/us-gov | fall 521, rise 187, arch 129, flat 122, dip 59, pop 29, hiss 3 |
| music (all) | fall 481, flat 419, rise 330, dip 178, arch 157, pop 112, hiss 10 |
| music with vocals | flat 101, fall 78, rise 63, dip 32, pop 31, arch 29, hiss 1 |
| music without vocals | fall 401, flat 309, rise 253, dip 143, arch 128, pop 78, hiss 9 |
| noise (all) | pop 416, hiss 280, flat 196, fall 109, rise 75, arch 58, dip 37 |

Lines: 34691; strict-parse/label errors: 0; outside generate.py's line space: 12586

### TUNED config, TUNE split

| subset | files | min | events/min | FA groups/min | fireable events/min | files with FA % | actions |
|---|---|---|---|---|---|---|---|
| speech (all) | 129 | 129 | 39.4 | 0.71 | 3.59 | 45.7 | swipe_down 54, swipe_up 14, long_press 9, swipe_right 7, swipe_left 3, tap 3, back 1 |
| speech/librivox | 52 | 52 | 31.5 | 0.23 | 1.02 | 17.3 | swipe_down 5, swipe_up 4, swipe_left 1, back 1, swipe_right 1 |
| speech/us-gov | 77 | 77 | 44.8 | 1.03 | 5.31 | 64.9 | swipe_down 49, swipe_up 10, long_press 9, swipe_right 6, tap 3, swipe_left 2 |
| music (all) | 138 | 138 | 30.4 | 1.36 | 4.66 | 54.3 | swipe_down 64, swipe_up 43, long_press 31, swipe_right 26, swipe_left 16, tap 7 |
| music with vocals | 61 | 61 | 27.5 | 1.13 | 2.74 | 45.9 | long_press 19, swipe_down 19, swipe_up 17, swipe_left 6, swipe_right 5, tap 3 |
| music without vocals | 71 | 71 | 29.9 | 1.62 | 6.33 | 63.4 | swipe_down 44, swipe_up 25, swipe_right 20, long_press 12, swipe_left 10, tap 3 |
| noise (all) | 257 | 75 | 29.5 | 2.31 | 7.59 | 28.4 | tap 48, back 34, swipe_left 24, long_press 23, swipe_up 18, swipe_right 17, swipe_down 10 |

'Sounds like' of all events (counts):

| subset | hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound |
|---|---|---|---|---|---|---|---|---|
| speech (all) | 969 | 5 | 3086 | 519 | 60 | 252 | 144 | 44 |
| speech/librivox | 114 | 3 | 1044 | 235 | 38 | 135 | 40 | 23 |
| speech/us-gov | 855 | 2 | 2042 | 284 | 22 | 117 | 104 | 21 |
| music (all) | 1346 | 91 | 1037 | 7 | 6 | 374 | 1270 | 47 |
| music with vocals | 379 | 4 | 404 | 4 | 3 | 141 | 718 | 22 |
| music without vocals | 854 | 87 | 547 | 3 | 2 | 228 | 367 | 24 |
| noise (all) | 148 | 173 | 88 | 51 | 59 | 47 | 898 | 755 |

Labels of events that would fire alone:

| subset | labels |
|---|---|
| speech (all) | fall 227, rise 80, arch 60, flat 44, dip 21, pop 19, hiss 11 |
| speech/librivox | fall 23, hiss 10, rise 10, arch 4, pop 4, dip 2 |
| speech/us-gov | fall 204, rise 70, arch 56, flat 44, dip 19, pop 15, hiss 1 |
| music (all) | fall 235, rise 134, flat 87, dip 79, arch 70, pop 34, hiss 2 |
| music with vocals | fall 49, flat 40, rise 33, pop 18, dip 16, arch 11 |
| music without vocals | fall 178, rise 94, dip 62, arch 52, flat 44, pop 15, hiss 2 |
| noise (all) | pop 241, hiss 140, flat 80, rise 35, dip 32, arch 23, fall 20 |

Lines: 11476; strict-parse/label errors: 0; outside generate.py's line space: 4244

