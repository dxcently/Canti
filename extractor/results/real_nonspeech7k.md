# REAL audio: nonspeech7k

```
Nonspeech7k (Rashid et al., IET Signal Processing 2023; Zenodo 10.5281/zenodo.6967442) as NEGATIVES.

Seven classes of human non-speech sound: breath, cough, crying, laugh, screaming, sneeze, yawn. Clips are
0.5-4 s, 32 kHz mono, cut from freesound / YouTube / Aigei recordings. Only "Original" rows are used (the
metadata also lists augmented copies). There are no speaker IDs; File_ID (the source recording) stands in for
the speaker, so segments of one source recording never land in both splits. Train and test folders of the
corpus are pooled and re-split by File_ID (30 % tune / 70 % test).
Rate handling: 32 kHz -> 16 kHz with scipy resample_poly (resample.to_16k), not the 48 kHz decimator.
```

### FROZEN config, TEST split  <- headline

| class | clips | min | clips with FA % | FA groups/min | fireable events/min | actions |
|---|---|---|---|---|---|---|
| breath | 1585 | 101.1 | 9.9 | 1.60 | 6.12 | long_press 88, tap 45, back 25, swipe_down 4 |
| cough | 510 | 24.8 | 9.4 | 2.09 | 12.08 | tap 36, back 6, swipe_down 5, swipe_right 2, swipe_up 2, swipe_left 1 |
| crying | 1407 | 88.0 | 14.3 | 2.44 | 15.68 | swipe_down 61, tap 48, swipe_up 37, swipe_right 27, swipe_left 16, back 15, long_press 11 |
| laugh | 886 | 50.2 | 14.7 | 2.75 | 18.02 | tap 71, swipe_down 20, back 18, swipe_up 14, swipe_left 6, swipe_right 4, long_press 3, listen_for_phrase 2 |
| screaming | 494 | 27.2 | 18.8 | 3.74 | 11.30 | swipe_up 25, tap 25, swipe_down 24, swipe_right 14, swipe_left 7, long_press 6, back 1 |
| sneeze | 186 | 6.3 | 10.8 | 3.31 | 21.12 | back 15, tap 4, long_press 1, swipe_down 1 |
| yawn | 167 | 6.7 | 18.6 | 4.63 | 12.69 | swipe_down 18, tap 7, swipe_up 2, back 2, swipe_left 1, swipe_right 1 |
| ALL | 5235 | 304.5 | 13.0 | 2.37 | 12.25 | tap 236, swipe_down 133, long_press 109, back 82, swipe_up 80, swipe_right 48, swipe_left 31, listen_for_phrase 2 |

'Sounds like' of all events (counts):

| class | hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound |
|---|---|---|---|---|---|---|---|---|
| breath | 1015 | 0 | 410 | 40 | 40 | 17 | 3285 | 472 |
| cough | 102 | 18 | 414 | 132 | 379 | 19 | 287 | 325 |
| crying | 999 | 394 | 1835 | 489 | 231 | 119 | 688 | 663 |
| laugh | 374 | 166 | 1107 | 387 | 110 | 87 | 342 | 770 |
| screaming | 298 | 143 | 217 | 17 | 13 | 159 | 204 | 113 |
| sneeze | 40 | 6 | 98 | 37 | 57 | 1 | 112 | 148 |
| yawn | 63 | 3 | 117 | 2 | 9 | 4 | 77 | 52 |
| ALL | 2891 | 730 | 4198 | 1104 | 839 | 406 | 4995 | 2543 |

Lines: 17706; strict-parse/label errors: 0; outside generate.py's line space: 4998

### FROZEN config, TUNE split

| class | clips | min | clips with FA % | FA groups/min | fireable events/min | actions |
|---|---|---|---|---|---|---|
| breath | 265 | 15.8 | 12.8 | 2.47 | 7.98 | tap 17, back 7, swipe_down 7, long_press 5, swipe_left 2, swipe_right 1 |
| cough | 192 | 8.9 | 12.5 | 2.70 | 9.80 | tap 15, swipe_right 3, swipe_down 3, back 3 |
| crying | 589 | 36.7 | 13.4 | 2.26 | 14.21 | tap 21, swipe_down 16, swipe_up 13, back 11, long_press 9, swipe_right 8, swipe_left 5 |
| laugh | 387 | 23.2 | 13.4 | 2.32 | 17.91 | tap 29, swipe_up 8, long_press 5, swipe_left 5, swipe_down 5, back 2 |
| screaming | 169 | 9.0 | 15.4 | 3.33 | 13.54 | swipe_right 6, long_press 6, swipe_down 5, tap 5, swipe_up 4, swipe_left 4 |
| sneeze | 80 | 2.8 | 15.0 | 4.57 | 22.49 | back 8, tap 3, swipe_up 1, swipe_down 1 |
| yawn | 97 | 4.1 | 22.7 | 5.67 | 17.50 | swipe_down 17, tap 6 |
| ALL | 1779 | 100.5 | 14.0 | 2.65 | 14.00 | tap 96, swipe_down 54, back 31, swipe_up 26, long_press 25, swipe_right 18, swipe_left 16 |

'Sounds like' of all events (counts):

| class | hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound |
|---|---|---|---|---|---|---|---|---|
| breath | 78 | 0 | 86 | 10 | 20 | 10 | 447 | 127 |
| cough | 31 | 1 | 117 | 36 | 173 | 4 | 138 | 98 |
| crying | 381 | 134 | 830 | 190 | 135 | 47 | 253 | 298 |
| laugh | 189 | 152 | 511 | 165 | 50 | 35 | 154 | 305 |
| screaming | 67 | 74 | 38 | 4 | 1 | 35 | 69 | 29 |
| sneeze | 19 | 6 | 47 | 11 | 32 | 0 | 37 | 62 |
| yawn | 51 | 0 | 72 | 6 | 17 | 5 | 37 | 48 |
| ALL | 816 | 367 | 1701 | 422 | 428 | 136 | 1135 | 967 |

Lines: 5972; strict-parse/label errors: 0; outside generate.py's line space: 1944

### FIXED config, TEST split

| class | clips | min | clips with FA % | FA groups/min | fireable events/min | actions |
|---|---|---|---|---|---|---|
| breath | 1585 | 101.1 | 9.5 | 1.53 | 5.75 | long_press 87, tap 45, back 20, swipe_down 3 |
| cough | 510 | 24.8 | 8.0 | 1.81 | 11.20 | tap 31, back 6, swipe_down 5, swipe_up 1, swipe_right 1, swipe_left 1 |
| crying | 1407 | 88.0 | 12.5 | 2.14 | 13.39 | swipe_down 52, tap 39, swipe_up 33, swipe_right 26, swipe_left 13, long_press 13, back 12 |
| laugh | 886 | 50.2 | 12.4 | 2.33 | 15.27 | tap 52, swipe_down 18, back 18, swipe_up 13, swipe_right 5, swipe_left 5, long_press 4, listen_for_phrase 2 |
| screaming | 494 | 27.2 | 17.8 | 3.56 | 9.87 | swipe_down 23, swipe_up 22, tap 22, swipe_right 16, swipe_left 8, long_press 6 |
| sneeze | 186 | 6.3 | 10.2 | 3.31 | 21.12 | back 13, tap 6, long_press 2 |
| yawn | 167 | 6.7 | 18.0 | 4.48 | 12.69 | swipe_down 18, tap 6, swipe_up 2, back 2, swipe_left 1, swipe_right 1 |
| ALL | 5235 | 304.5 | 11.7 | 2.14 | 10.81 | tap 201, swipe_down 119, long_press 112, back 71, swipe_up 71, swipe_right 49, swipe_left 28, listen_for_phrase 2 |

'Sounds like' of all events (counts):

| class | hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound |
|---|---|---|---|---|---|---|---|---|
| breath | 947 | 0 | 425 | 39 | 43 | 27 | 3213 | 446 |
| cough | 100 | 20 | 430 | 138 | 378 | 22 | 307 | 305 |
| crying | 938 | 391 | 1814 | 488 | 227 | 160 | 701 | 524 |
| laugh | 341 | 172 | 1138 | 404 | 111 | 98 | 349 | 640 |
| screaming | 275 | 137 | 233 | 17 | 12 | 169 | 228 | 96 |
| sneeze | 38 | 5 | 100 | 42 | 54 | 1 | 123 | 154 |
| yawn | 64 | 3 | 117 | 3 | 8 | 5 | 78 | 50 |
| ALL | 2703 | 728 | 4257 | 1131 | 833 | 482 | 4999 | 2215 |

Lines: 17348; strict-parse/label errors: 0; outside generate.py's line space: 5318

### FIXED config, TUNE split

| class | clips | min | clips with FA % | FA groups/min | fireable events/min | actions |
|---|---|---|---|---|---|---|
| breath | 265 | 15.8 | 11.7 | 2.28 | 7.60 | tap 16, swipe_down 7, back 6, long_press 5, swipe_left 2 |
| cough | 192 | 8.9 | 10.4 | 2.25 | 9.46 | tap 13, back 3, swipe_right 2, swipe_down 2 |
| crying | 589 | 36.7 | 11.7 | 1.96 | 12.55 | tap 15, swipe_down 14, swipe_up 13, back 11, long_press 9, swipe_right 7, swipe_left 3 |
| laugh | 387 | 23.2 | 10.6 | 1.85 | 14.25 | tap 22, swipe_left 6, swipe_up 6, long_press 4, swipe_down 3, back 2 |
| screaming | 169 | 9.0 | 13.0 | 2.78 | 10.77 | swipe_right 6, long_press 6, swipe_left 5, swipe_down 4, swipe_up 4 |
| sneeze | 80 | 2.8 | 13.8 | 4.22 | 22.14 | back 7, tap 3, swipe_up 1, swipe_down 1 |
| yawn | 97 | 4.1 | 18.6 | 4.68 | 15.04 | swipe_down 16, tap 3 |
| ALL | 1779 | 100.5 | 11.9 | 2.26 | 12.10 | tap 72, swipe_down 47, back 29, long_press 24, swipe_up 24, swipe_left 16, swipe_right 15 |

'Sounds like' of all events (counts):

| class | hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound |
|---|---|---|---|---|---|---|---|---|
| breath | 75 | 0 | 85 | 9 | 20 | 11 | 444 | 125 |
| cough | 28 | 3 | 133 | 38 | 173 | 4 | 138 | 98 |
| crying | 369 | 126 | 831 | 189 | 131 | 56 | 254 | 249 |
| laugh | 176 | 145 | 514 | 169 | 47 | 45 | 148 | 223 |
| screaming | 53 | 73 | 44 | 3 | 3 | 41 | 73 | 18 |
| sneeze | 18 | 7 | 47 | 11 | 30 | 1 | 45 | 61 |
| yawn | 45 | 0 | 79 | 6 | 17 | 6 | 35 | 36 |
| ALL | 764 | 354 | 1733 | 425 | 421 | 164 | 1137 | 810 |

Lines: 5808; strict-parse/label errors: 0; outside generate.py's line space: 2033

### TUNED config, TEST split

| class | clips | min | clips with FA % | FA groups/min | fireable events/min | actions |
|---|---|---|---|---|---|---|
| breath | 1585 | 101.1 | 7.4 | 1.21 | 3.75 | long_press 88, back 21, tap 10, swipe_down 3 |
| cough | 510 | 24.8 | 8.2 | 1.77 | 9.34 | tap 29, back 6, swipe_down 5, swipe_up 1, long_press 1, swipe_right 1, swipe_left 1 |
| crying | 1407 | 88.0 | 11.6 | 1.98 | 11.55 | swipe_down 58, swipe_up 34, swipe_right 26, tap 18, swipe_left 13, long_press 13, back 12 |
| laugh | 886 | 50.2 | 9.8 | 1.83 | 11.51 | tap 26, back 21, swipe_down 17, swipe_up 14, swipe_right 5, swipe_left 5, long_press 4 |
| screaming | 494 | 27.2 | 15.6 | 3.01 | 7.60 | swipe_down 24, swipe_up 21, swipe_right 18, swipe_left 9, long_press 7, tap 3 |
| sneeze | 186 | 6.3 | 9.1 | 3.00 | 16.87 | back 15, tap 2, long_press 2 |
| yawn | 167 | 6.7 | 16.8 | 4.18 | 8.81 | swipe_down 20, swipe_left 2, swipe_up 2, back 2, long_press 1, swipe_right 1 |
| ALL | 5235 | 304.5 | 10.2 | 1.84 | 8.47 | swipe_down 127, long_press 116, tap 88, back 77, swipe_up 72, swipe_right 51, swipe_left 30 |

'Sounds like' of all events (counts):

| class | hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound |
|---|---|---|---|---|---|---|---|---|
| breath | 948 | 0 | 425 | 39 | 39 | 27 | 3209 | 209 |
| cough | 101 | 20 | 427 | 137 | 348 | 22 | 303 | 247 |
| crying | 947 | 391 | 1812 | 486 | 219 | 160 | 697 | 328 |
| laugh | 346 | 172 | 1144 | 404 | 104 | 98 | 345 | 416 |
| screaming | 277 | 137 | 234 | 17 | 11 | 169 | 228 | 16 |
| sneeze | 38 | 5 | 100 | 42 | 54 | 1 | 122 | 123 |
| yawn | 64 | 3 | 117 | 3 | 7 | 5 | 78 | 20 |
| ALL | 2721 | 728 | 4259 | 1128 | 782 | 482 | 4982 | 1359 |

Lines: 16441; strict-parse/label errors: 0; outside generate.py's line space: 5329

### TUNED config, TUNE split

| class | clips | min | clips with FA % | FA groups/min | fireable events/min | actions |
|---|---|---|---|---|---|---|
| breath | 265 | 15.8 | 8.3 | 1.65 | 4.05 | back 8, swipe_down 7, long_press 5, tap 3, swipe_left 2, swipe_right 1 |
| cough | 192 | 8.9 | 7.8 | 1.69 | 7.88 | tap 8, back 3, swipe_right 2, swipe_down 2 |
| crying | 589 | 36.7 | 10.7 | 1.77 | 10.54 | swipe_down 15, swipe_up 12, back 12, long_press 9, tap 7, swipe_right 7, swipe_left 3 |
| laugh | 387 | 23.2 | 8.5 | 1.46 | 11.15 | tap 12, swipe_left 7, swipe_up 6, long_press 4, swipe_down 3, back 2 |
| screaming | 169 | 9.0 | 13.0 | 2.78 | 9.66 | swipe_right 6, long_press 6, swipe_left 5, swipe_down 4, swipe_up 4 |
| sneeze | 80 | 2.8 | 12.5 | 3.87 | 17.57 | back 7, tap 2, swipe_up 1, swipe_down 1 |
| yawn | 97 | 4.1 | 17.5 | 4.44 | 10.60 | swipe_down 18 |
| ALL | 1779 | 100.5 | 10.2 | 1.93 | 9.55 | swipe_down 50, tap 32, back 32, long_press 24, swipe_up 23, swipe_left 17, swipe_right 16 |

'Sounds like' of all events (counts):

| class | hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound |
|---|---|---|---|---|---|---|---|---|
| breath | 75 | 0 | 86 | 9 | 20 | 11 | 443 | 62 |
| cough | 27 | 3 | 132 | 38 | 162 | 4 | 137 | 85 |
| crying | 374 | 126 | 834 | 189 | 125 | 56 | 251 | 161 |
| laugh | 174 | 145 | 515 | 169 | 38 | 45 | 146 | 152 |
| screaming | 53 | 73 | 44 | 3 | 3 | 41 | 73 | 8 |
| sneeze | 18 | 7 | 47 | 11 | 30 | 1 | 45 | 43 |
| yawn | 45 | 0 | 79 | 6 | 17 | 6 | 35 | 13 |
| ALL | 766 | 354 | 1737 | 425 | 395 | 164 | 1130 | 524 |

Lines: 5495; strict-parse/label errors: 0; outside generate.py's line space: 2036

