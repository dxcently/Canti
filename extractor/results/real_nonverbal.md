# REAL audio: nonverbal

```
Deeply Nonverbal Vocalization Dataset (OpenSLR 99): real tongue clicks / lip pops vs other mouth noises.

Positives: tongue-clicking -> click, lip-popping -> pop. Borderline (reported separately): lip-smacking.
Negatives (user list): coughing, sighing, laughing, throat-clearing, sneezing, yawning, teeth-chattering,
teeth-grinding. Other classes (panting, crying, moaning, screaming, nose-blowing) are scored as "other
negatives" and kept out of the headline negative numbers.

Each file is ONE speaker performing the sound usually SEVERAL times (e.g. a train of 5-15 clicks), with
no per-event timestamps. So scoring is per clip and per event, never "exactly one event":
  * detect:  the clip yields at least one event with the target label;
  * major:   the clip's most frequent emitted label (ties -> the target if tied; "none" if no events);
  * purity:  of all events emitted in positive clips, the share with the target label;
  * fire:    of all events, the share that would trigger their own default action ALONE (pop -> tap;
             a lone click is unbound, so for clicks "fire" means "correct label and passes the gate").
Negatives: false accepts per minute = groups (phone-style, gap <= 600 ms) mapping to an action other than
none, per minute of original audio; and fireable events per minute (each event judged alone, pessimistic).

Filename: {speaker}_{class}_{trial}_{sex}_{age}_{location}_{quality}_{noise}.wav, 16 kHz mono PCM16.
```

### FROZEN config, TEST split  <- headline

| class | SNR | clips | detect % | majority = target % | events/clip | event purity % | event fires own action % |
|---|---|---|---|---|---|---|---|
| tongue-clicking | clean | 31 | 71.0 | 64.5 | 5.1 | 68.6 | 68.6 |
| tongue-clicking | 20 | 31 | 87.1 | 71.0 | 6.6 | 70.2 | 70.2 |
| tongue-clicking | 10 | 31 | 90.3 | 80.6 | 5.9 | 66.5 | 66.5 |
| tongue-clicking | 5 | 31 | 77.4 | 58.1 | 5.4 | 56.3 | 56.3 |
| lip-popping | clean | 35 | 28.6 | 22.9 | 2.5 | 27.0 | 27.0 |
| lip-popping | 20 | 35 | 65.7 | 54.3 | 2.4 | 37.6 | 37.6 |
| lip-popping | 10 | 35 | 57.1 | 45.7 | 2.7 | 31.2 | 31.2 |
| lip-popping | 5 | 35 | 40.0 | 28.6 | 2.3 | 29.6 | 29.6 |
| lip-smacking (borderline) | clean | 35 | 25.7 | 14.3 | 3.9 | 13.3 | 13.3 |
| lip-smacking (borderline) | 20 | 35 | 28.6 | 11.4 | 5.0 | 9.7 | 9.7 |
| lip-smacking (borderline) | 10 | 35 | 37.1 | 11.4 | 5.1 | 8.4 | 8.4 |
| lip-smacking (borderline) | 5 | 35 | 31.4 | 5.7 | 4.8 | 7.7 | 7.7 |

Clip-majority confusion (rows = class, columns = most frequent emitted label):


clean:

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| tongue-clicking | 0 | 1 | 0 | 0 | 0 | 2 | 20 | 8 | 0 | 31 |
| lip-popping | 0 | 0 | 1 | 0 | 3 | 8 | 1 | 22 | 0 | 35 |
| lip-smacking | 1 | 0 | 1 | 0 | 5 | 5 | 7 | 16 | 0 | 35 |

20:

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| tongue-clicking | 0 | 0 | 0 | 1 | 2 | 1 | 22 | 5 | 0 | 31 |
| lip-popping | 1 | 1 | 1 | 1 | 2 | 19 | 0 | 9 | 1 | 35 |
| lip-smacking | 0 | 0 | 1 | 1 | 1 | 4 | 17 | 11 | 0 | 35 |

10:

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| tongue-clicking | 0 | 2 | 0 | 0 | 1 | 1 | 25 | 2 | 0 | 31 |
| lip-popping | 2 | 0 | 0 | 0 | 3 | 16 | 1 | 12 | 1 | 35 |
| lip-smacking | 1 | 0 | 1 | 0 | 4 | 4 | 17 | 7 | 1 | 35 |

5:

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| tongue-clicking | 0 | 0 | 0 | 1 | 3 | 3 | 18 | 5 | 1 | 31 |
| lip-popping | 3 | 0 | 1 | 0 | 6 | 10 | 1 | 9 | 5 | 35 |
| lip-smacking | 2 | 1 | 1 | 0 | 4 | 2 | 19 | 6 | 0 | 35 |

False accepts, negatives (user list), as recorded:

| class | clips | min | clips with FA % | FA groups / min | fireable events / min | actions |
|---|---|---|---|---|---|---|
| coughing | 28 | 1.2 | 3.6 | 0.84 | 9.28 | tap 1 |
| sighing | 40 | 1.7 | 2.5 | 0.60 | 6.05 | tap 1 |
| laughing | 20 | 1.7 | 15.0 | 1.74 | 16.28 | tap 3 |
| throat-clearing | 36 | 1.4 | 2.8 | 0.70 | 4.88 | tap 1 |
| sneezing | 43 | 1.8 | 2.3 | 0.57 | 5.69 | tap 1 |
| yawning | 35 | 1.5 | 2.9 | 0.67 | 6.67 | tap 1 |
| teeth-chattering | 36 | 1.7 | 8.3 | 1.76 | 51.64 | tap 2, listen_for_phrase 1 |
| teeth-grinding | 34 | 1.7 | 0.0 | 0.00 | 9.59 |  |
| ALL | 272 | 12.6 | 4.0 | 0.87 | 14.26 | tap 10, listen_for_phrase 1 |

False accepts, other nonverbal classes, as recorded:

| class | clips | min | clips with FA % | FA groups / min | fireable events / min | actions |
|---|---|---|---|---|---|---|
| panting | 30 | 1.5 | 10.0 | 2.04 | 7.47 | back 2, tap 1 |
| crying | 20 | 1.8 | 10.0 | 1.12 | 16.26 | swipe_down 2 |
| moaning | 33 | 1.6 | 9.1 | 2.55 | 10.83 | swipe_down 2, tap 1, long_press 1 |
| screaming | 32 | 1.4 | 43.8 | 10.27 | 21.27 | swipe_right 6, swipe_down 4, tap 2, swipe_up 2 |
| nose-blowing | 35 | 1.6 | 5.7 | 1.24 | 9.30 | tap 1, back 1 |
| ALL | 150 | 7.8 | 16.0 | 3.20 | 12.94 | swipe_down 8, swipe_right 6, tap 5, back 3, swipe_up 2, long_press 1 |

Lines: 2821; strict-parse/label errors: 0; outside generate.py's line space: 537

### FROZEN config, TUNE split

| class | SNR | clips | detect % | majority = target % | events/clip | event purity % | event fires own action % |
|---|---|---|---|---|---|---|---|
| tongue-clicking | clean | 16 | 56.2 | 56.2 | 4.6 | 58.1 | 58.1 |
| tongue-clicking | 20 | 16 | 81.2 | 68.8 | 6.2 | 67.0 | 67.0 |
| tongue-clicking | 10 | 16 | 62.5 | 56.2 | 4.8 | 61.8 | 61.8 |
| tongue-clicking | 5 | 16 | 56.2 | 50.0 | 3.2 | 53.8 | 53.8 |
| lip-popping | clean | 19 | 47.4 | 36.8 | 2.5 | 31.9 | 31.9 |
| lip-popping | 20 | 19 | 63.2 | 57.9 | 2.9 | 52.7 | 52.7 |
| lip-popping | 10 | 19 | 73.7 | 42.1 | 3.9 | 40.0 | 40.0 |
| lip-popping | 5 | 19 | 57.9 | 47.4 | 1.8 | 45.7 | 45.7 |
| lip-smacking (borderline) | clean | 10 | 40.0 | 0.0 | 5.3 | 13.2 | 13.2 |
| lip-smacking (borderline) | 20 | 10 | 40.0 | 0.0 | 5.5 | 7.3 | 7.3 |
| lip-smacking (borderline) | 10 | 10 | 20.0 | 0.0 | 5.2 | 9.6 | 9.6 |
| lip-smacking (borderline) | 5 | 10 | 80.0 | 40.0 | 8.0 | 27.5 | 27.5 |

Clip-majority confusion (rows = class, columns = most frequent emitted label):


clean:

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| tongue-clicking | 0 | 0 | 0 | 0 | 2 | 1 | 9 | 4 | 0 | 16 |
| lip-popping | 0 | 0 | 0 | 0 | 4 | 7 | 0 | 8 | 0 | 19 |
| lip-smacking | 1 | 0 | 0 | 0 | 1 | 0 | 2 | 6 | 0 | 10 |

20:

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| tongue-clicking | 1 | 0 | 0 | 0 | 1 | 0 | 11 | 2 | 1 | 16 |
| lip-popping | 0 | 0 | 0 | 0 | 1 | 11 | 0 | 7 | 0 | 19 |
| lip-smacking | 1 | 0 | 0 | 0 | 0 | 0 | 6 | 3 | 0 | 10 |

10:

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| tongue-clicking | 0 | 0 | 0 | 0 | 1 | 1 | 9 | 4 | 1 | 16 |
| lip-popping | 1 | 0 | 0 | 0 | 0 | 8 | 3 | 6 | 1 | 19 |
| lip-smacking | 0 | 0 | 1 | 0 | 0 | 0 | 7 | 2 | 0 | 10 |

5:

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| tongue-clicking | 0 | 0 | 0 | 0 | 0 | 0 | 8 | 2 | 6 | 16 |
| lip-popping | 2 | 0 | 0 | 0 | 3 | 9 | 0 | 3 | 2 | 19 |
| lip-smacking | 1 | 0 | 0 | 0 | 0 | 4 | 4 | 1 | 0 | 10 |

False accepts, negatives (user list), as recorded:

| class | clips | min | clips with FA % | FA groups / min | fireable events / min | actions |
|---|---|---|---|---|---|---|
| coughing | 22 | 1.0 | 18.2 | 4.15 | 22.85 | tap 4 |
| sighing | 11 | 0.5 | 0.0 | 0.00 | 0.00 |  |
| laughing | 5 | 0.4 | 20.0 | 2.34 | 9.36 | tap 1 |
| throat-clearing | 18 | 0.7 | 5.6 | 1.42 | 5.68 | tap 1 |
| sneezing | 9 | 0.4 | 0.0 | 0.00 | 10.38 |  |
| yawning | 13 | 0.7 | 7.7 | 1.50 | 7.49 | swipe_down 1 |
| teeth-chattering | 10 | 0.4 | 20.0 | 4.52 | 52.02 | tap 2 |
| teeth-grinding | 9 | 0.5 | 11.1 | 2.11 | 27.47 | tap 1 |
| ALL | 97 | 4.5 | 10.3 | 2.20 | 16.52 | tap 9, swipe_down 1 |

False accepts, other nonverbal classes, as recorded:

| class | clips | min | clips with FA % | FA groups / min | fireable events / min | actions |
|---|---|---|---|---|---|---|
| panting | 14 | 0.7 | 7.1 | 1.45 | 4.35 | tap 1 |
| crying | 4 | 0.4 | 0.0 | 0.00 | 5.53 |  |
| moaning | 12 | 0.6 | 8.3 | 1.76 | 8.80 | swipe_down 1 |
| screaming | 19 | 0.8 | 36.8 | 8.73 | 24.95 | swipe_down 4, swipe_right 2, long_press 1 |
| nose-blowing | 13 | 0.5 | 7.7 | 1.85 | 11.09 | tap 1 |
| ALL | 62 | 3.0 | 16.1 | 3.38 | 12.15 | swipe_down 5, tap 2, swipe_right 2, long_press 1 |

Lines: 1175; strict-parse/label errors: 0; outside generate.py's line space: 204

### FIXED config, TEST split

| class | SNR | clips | detect % | majority = target % | events/clip | event purity % | event fires own action % |
|---|---|---|---|---|---|---|---|
| tongue-clicking | clean | 31 | 71.0 | 64.5 | 5.0 | 66.7 | 66.7 |
| tongue-clicking | 20 | 31 | 83.9 | 67.7 | 6.5 | 65.5 | 65.5 |
| tongue-clicking | 10 | 31 | 83.9 | 71.0 | 5.6 | 63.2 | 63.2 |
| tongue-clicking | 5 | 31 | 77.4 | 54.8 | 5.5 | 55.3 | 55.3 |
| lip-popping | clean | 35 | 25.7 | 17.1 | 2.4 | 21.2 | 21.2 |
| lip-popping | 20 | 35 | 62.9 | 51.4 | 2.6 | 35.6 | 35.6 |
| lip-popping | 10 | 35 | 48.6 | 40.0 | 2.9 | 26.2 | 26.2 |
| lip-popping | 5 | 35 | 37.1 | 25.7 | 2.9 | 20.4 | 20.4 |
| lip-smacking (borderline) | clean | 35 | 22.9 | 11.4 | 3.8 | 12.7 | 12.7 |
| lip-smacking (borderline) | 20 | 35 | 22.9 | 5.7 | 4.8 | 7.1 | 7.1 |
| lip-smacking (borderline) | 10 | 35 | 34.3 | 11.4 | 5.3 | 7.5 | 7.5 |
| lip-smacking (borderline) | 5 | 35 | 28.6 | 5.7 | 4.9 | 6.9 | 6.9 |

Clip-majority confusion (rows = class, columns = most frequent emitted label):


clean:

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| tongue-clicking | 0 | 0 | 0 | 0 | 0 | 2 | 20 | 9 | 0 | 31 |
| lip-popping | 0 | 0 | 1 | 0 | 3 | 6 | 1 | 24 | 0 | 35 |
| lip-smacking | 1 | 0 | 1 | 0 | 5 | 4 | 7 | 17 | 0 | 35 |

20:

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| tongue-clicking | 0 | 0 | 0 | 1 | 3 | 1 | 21 | 5 | 0 | 31 |
| lip-popping | 1 | 1 | 2 | 0 | 5 | 18 | 0 | 8 | 0 | 35 |
| lip-smacking | 0 | 0 | 2 | 1 | 2 | 2 | 14 | 14 | 0 | 35 |

10:

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| tongue-clicking | 0 | 1 | 0 | 0 | 2 | 1 | 22 | 5 | 0 | 31 |
| lip-popping | 3 | 0 | 1 | 0 | 3 | 14 | 1 | 13 | 0 | 35 |
| lip-smacking | 2 | 0 | 1 | 0 | 3 | 4 | 16 | 9 | 0 | 35 |

5:

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| tongue-clicking | 0 | 0 | 0 | 1 | 3 | 4 | 17 | 6 | 0 | 31 |
| lip-popping | 3 | 0 | 1 | 0 | 10 | 9 | 1 | 9 | 2 | 35 |
| lip-smacking | 2 | 0 | 2 | 0 | 4 | 2 | 18 | 7 | 0 | 35 |

False accepts, negatives (user list), as recorded:

| class | clips | min | clips with FA % | FA groups / min | fireable events / min | actions |
|---|---|---|---|---|---|---|
| coughing | 28 | 1.2 | 0.0 | 0.00 | 8.44 |  |
| sighing | 40 | 1.7 | 2.5 | 0.60 | 5.44 | tap 1 |
| laughing | 20 | 1.7 | 0.0 | 0.00 | 10.47 |  |
| throat-clearing | 36 | 1.4 | 2.8 | 0.70 | 4.18 | tap 1 |
| sneezing | 43 | 1.8 | 2.3 | 0.57 | 5.69 | tap 1 |
| yawning | 35 | 1.5 | 2.9 | 0.67 | 6.67 | tap 1 |
| teeth-chattering | 36 | 1.7 | 8.3 | 1.76 | 50.46 | tap 2, listen_for_phrase 1 |
| teeth-grinding | 34 | 1.7 | 0.0 | 0.00 | 8.99 |  |
| ALL | 272 | 12.6 | 2.6 | 0.55 | 12.99 | tap 6, listen_for_phrase 1 |

False accepts, other nonverbal classes, as recorded:

| class | clips | min | clips with FA % | FA groups / min | fireable events / min | actions |
|---|---|---|---|---|---|---|
| panting | 30 | 1.5 | 6.7 | 1.36 | 6.11 | tap 1, back 1 |
| crying | 20 | 1.8 | 10.0 | 1.12 | 12.33 | swipe_down 2 |
| moaning | 33 | 1.6 | 6.1 | 1.91 | 10.20 | swipe_down 2, long_press 1 |
| screaming | 32 | 1.4 | 21.9 | 5.13 | 19.80 | swipe_down 3, swipe_right 3, tap 1 |
| nose-blowing | 35 | 1.6 | 5.7 | 1.24 | 9.30 | tap 1, back 1 |
| ALL | 150 | 7.8 | 10.0 | 2.05 | 11.41 | swipe_down 7, tap 3, swipe_right 3, back 2, long_press 1 |

Lines: 2834; strict-parse/label errors: 0; outside generate.py's line space: 584

### FIXED config, TUNE split

| class | SNR | clips | detect % | majority = target % | events/clip | event purity % | event fires own action % |
|---|---|---|---|---|---|---|---|
| tongue-clicking | clean | 16 | 56.2 | 56.2 | 4.6 | 58.9 | 58.9 |
| tongue-clicking | 20 | 16 | 81.2 | 68.8 | 6.2 | 64.6 | 64.6 |
| tongue-clicking | 10 | 16 | 68.8 | 56.2 | 5.3 | 56.5 | 56.5 |
| tongue-clicking | 5 | 16 | 68.8 | 50.0 | 4.9 | 41.0 | 41.0 |
| lip-popping | clean | 19 | 47.4 | 36.8 | 2.5 | 31.9 | 31.9 |
| lip-popping | 20 | 19 | 52.6 | 47.4 | 3.2 | 42.6 | 42.6 |
| lip-popping | 10 | 19 | 73.7 | 36.8 | 4.6 | 36.4 | 36.4 |
| lip-popping | 5 | 19 | 52.6 | 42.1 | 2.6 | 30.0 | 30.0 |
| lip-smacking (borderline) | clean | 10 | 40.0 | 0.0 | 5.3 | 13.2 | 13.2 |
| lip-smacking (borderline) | 20 | 10 | 40.0 | 0.0 | 5.4 | 7.4 | 7.4 |
| lip-smacking (borderline) | 10 | 10 | 20.0 | 0.0 | 5.3 | 9.4 | 9.4 |
| lip-smacking (borderline) | 5 | 10 | 70.0 | 40.0 | 8.1 | 25.9 | 25.9 |

Clip-majority confusion (rows = class, columns = most frequent emitted label):


clean:

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| tongue-clicking | 0 | 0 | 1 | 0 | 2 | 0 | 9 | 4 | 0 | 16 |
| lip-popping | 0 | 0 | 0 | 0 | 4 | 7 | 0 | 8 | 0 | 19 |
| lip-smacking | 1 | 0 | 0 | 0 | 1 | 0 | 2 | 6 | 0 | 10 |

20:

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| tongue-clicking | 1 | 0 | 0 | 1 | 1 | 0 | 11 | 2 | 0 | 16 |
| lip-popping | 0 | 1 | 0 | 0 | 2 | 9 | 0 | 7 | 0 | 19 |
| lip-smacking | 1 | 0 | 0 | 0 | 1 | 0 | 4 | 4 | 0 | 10 |

10:

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| tongue-clicking | 0 | 0 | 0 | 0 | 2 | 1 | 9 | 4 | 0 | 16 |
| lip-popping | 1 | 0 | 0 | 0 | 2 | 7 | 2 | 7 | 0 | 19 |
| lip-smacking | 0 | 0 | 1 | 0 | 0 | 0 | 7 | 2 | 0 | 10 |

5:

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| tongue-clicking | 0 | 0 | 0 | 0 | 6 | 0 | 8 | 2 | 0 | 16 |
| lip-popping | 2 | 0 | 1 | 1 | 2 | 8 | 0 | 5 | 0 | 19 |
| lip-smacking | 1 | 0 | 0 | 0 | 0 | 4 | 4 | 1 | 0 | 10 |

False accepts, negatives (user list), as recorded:

| class | clips | min | clips with FA % | FA groups / min | fireable events / min | actions |
|---|---|---|---|---|---|---|
| coughing | 22 | 1.0 | 18.2 | 4.15 | 22.85 | tap 4 |
| sighing | 11 | 0.5 | 0.0 | 0.00 | 0.00 |  |
| laughing | 5 | 0.4 | 0.0 | 0.00 | 7.02 |  |
| throat-clearing | 18 | 0.7 | 5.6 | 1.42 | 5.68 | tap 1 |
| sneezing | 9 | 0.4 | 0.0 | 0.00 | 10.38 |  |
| yawning | 13 | 0.7 | 7.7 | 1.50 | 6.00 | swipe_down 1 |
| teeth-chattering | 10 | 0.4 | 20.0 | 4.52 | 45.23 | tap 2 |
| teeth-grinding | 9 | 0.5 | 11.1 | 2.11 | 25.36 | tap 1 |
| ALL | 97 | 4.5 | 9.3 | 1.98 | 15.20 | tap 8, swipe_down 1 |

False accepts, other nonverbal classes, as recorded:

| class | clips | min | clips with FA % | FA groups / min | fireable events / min | actions |
|---|---|---|---|---|---|---|
| panting | 14 | 0.7 | 7.1 | 1.45 | 4.35 | tap 1 |
| crying | 4 | 0.4 | 0.0 | 0.00 | 5.53 |  |
| moaning | 12 | 0.6 | 8.3 | 1.76 | 8.80 | swipe_down 1 |
| screaming | 19 | 0.8 | 36.8 | 8.73 | 24.95 | swipe_down 4, swipe_right 2, long_press 1 |
| nose-blowing | 13 | 0.5 | 7.7 | 1.85 | 11.09 | tap 1 |
| ALL | 62 | 3.0 | 16.1 | 3.38 | 12.15 | swipe_down 5, tap 2, swipe_right 2, long_press 1 |

Lines: 1239; strict-parse/label errors: 0; outside generate.py's line space: 236

### TUNED config, TEST split

| class | SNR | clips | detect % | majority = target % | events/clip | event purity % | event fires own action % |
|---|---|---|---|---|---|---|---|
| tongue-clicking | clean | 31 | 71.0 | 67.7 | 4.5 | 75.2 | 75.2 |
| tongue-clicking | 20 | 31 | 87.1 | 71.0 | 6.2 | 70.8 | 70.8 |
| tongue-clicking | 10 | 31 | 83.9 | 71.0 | 5.4 | 63.5 | 63.5 |
| tongue-clicking | 5 | 31 | 74.2 | 58.1 | 4.8 | 55.0 | 55.0 |
| lip-popping | clean | 35 | 20.0 | 20.0 | 1.9 | 16.2 | 16.2 |
| lip-popping | 20 | 35 | 40.0 | 31.4 | 2.1 | 26.4 | 26.4 |
| lip-popping | 10 | 35 | 31.4 | 20.0 | 2.4 | 15.7 | 15.7 |
| lip-popping | 5 | 35 | 14.3 | 8.6 | 2.5 | 9.0 | 9.0 |
| lip-smacking (borderline) | clean | 35 | 2.9 | 0.0 | 3.2 | 0.9 | 0.9 |
| lip-smacking (borderline) | 20 | 35 | 2.9 | 0.0 | 4.6 | 0.6 | 0.6 |
| lip-smacking (borderline) | 10 | 35 | 5.7 | 2.9 | 4.9 | 1.2 | 1.2 |
| lip-smacking (borderline) | 5 | 35 | 11.4 | 2.9 | 4.4 | 4.5 | 4.5 |

Clip-majority confusion (rows = class, columns = most frequent emitted label):


clean:

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| tongue-clicking | 0 | 0 | 0 | 0 | 1 | 0 | 21 | 9 | 0 | 31 |
| lip-popping | 0 | 0 | 1 | 0 | 2 | 7 | 0 | 25 | 0 | 35 |
| lip-smacking | 1 | 0 | 1 | 0 | 6 | 0 | 15 | 12 | 0 | 35 |

20:

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| tongue-clicking | 0 | 0 | 0 | 1 | 3 | 1 | 22 | 4 | 0 | 31 |
| lip-popping | 1 | 2 | 2 | 0 | 8 | 11 | 0 | 7 | 4 | 35 |
| lip-smacking | 1 | 0 | 2 | 0 | 2 | 0 | 18 | 12 | 0 | 35 |

10:

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| tongue-clicking | 0 | 1 | 0 | 0 | 2 | 0 | 22 | 6 | 0 | 31 |
| lip-popping | 3 | 0 | 1 | 0 | 4 | 7 | 2 | 13 | 5 | 35 |
| lip-smacking | 2 | 0 | 1 | 0 | 4 | 1 | 15 | 12 | 0 | 35 |

5:

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| tongue-clicking | 0 | 0 | 0 | 1 | 3 | 3 | 18 | 6 | 0 | 31 |
| lip-popping | 3 | 0 | 1 | 0 | 10 | 3 | 2 | 10 | 6 | 35 |
| lip-smacking | 2 | 0 | 2 | 0 | 5 | 1 | 17 | 8 | 0 | 35 |

False accepts, negatives (user list), as recorded:

| class | clips | min | clips with FA % | FA groups / min | fireable events / min | actions |
|---|---|---|---|---|---|---|
| coughing | 28 | 1.2 | 3.6 | 0.84 | 6.75 | tap 1 |
| sighing | 40 | 1.7 | 2.5 | 0.60 | 3.02 | tap 1 |
| laughing | 20 | 1.7 | 0.0 | 0.00 | 9.30 |  |
| throat-clearing | 36 | 1.4 | 0.0 | 0.00 | 1.39 |  |
| sneezing | 43 | 1.8 | 0.0 | 0.00 | 1.14 |  |
| yawning | 35 | 1.5 | 0.0 | 0.00 | 2.00 |  |
| teeth-chattering | 36 | 1.7 | 5.6 | 1.17 | 39.31 | tap 2 |
| teeth-grinding | 34 | 1.7 | 2.9 | 0.60 | 6.00 | tap 1 |
| ALL | 272 | 12.6 | 1.8 | 0.40 | 8.95 | tap 5 |

False accepts, other nonverbal classes, as recorded:

| class | clips | min | clips with FA % | FA groups / min | fireable events / min | actions |
|---|---|---|---|---|---|---|
| panting | 30 | 1.5 | 3.3 | 0.68 | 5.43 | back 1 |
| crying | 20 | 1.8 | 10.0 | 1.12 | 9.53 | swipe_down 2 |
| moaning | 33 | 1.6 | 6.1 | 1.91 | 6.37 | swipe_down 2, long_press 1 |
| screaming | 32 | 1.4 | 25.0 | 5.87 | 12.47 | swipe_down 4, swipe_right 3, swipe_up 1 |
| nose-blowing | 35 | 1.6 | 2.9 | 0.62 | 6.82 | back 1 |
| ALL | 150 | 7.8 | 9.3 | 1.92 | 8.07 | swipe_down 8, swipe_right 3, back 2, long_press 1, swipe_up 1 |

Lines: 2541; strict-parse/label errors: 0; outside generate.py's line space: 583

### TUNED config, TUNE split

| class | SNR | clips | detect % | majority = target % | events/clip | event purity % | event fires own action % |
|---|---|---|---|---|---|---|---|
| tongue-clicking | clean | 16 | 56.2 | 56.2 | 4.3 | 71.0 | 71.0 |
| tongue-clicking | 20 | 16 | 81.2 | 75.0 | 5.8 | 69.6 | 69.6 |
| tongue-clicking | 10 | 16 | 62.5 | 56.2 | 4.6 | 54.8 | 54.8 |
| tongue-clicking | 5 | 16 | 62.5 | 43.8 | 4.4 | 40.8 | 40.8 |
| lip-popping | clean | 19 | 52.6 | 47.4 | 2.0 | 36.8 | 36.8 |
| lip-popping | 20 | 19 | 42.1 | 36.8 | 2.8 | 34.0 | 34.0 |
| lip-popping | 10 | 19 | 57.9 | 21.1 | 4.0 | 31.6 | 31.6 |
| lip-popping | 5 | 19 | 21.1 | 10.5 | 2.2 | 16.7 | 16.7 |
| lip-smacking (borderline) | clean | 10 | 0.0 | 0.0 | 4.6 | 0.0 | 0.0 |
| lip-smacking (borderline) | 20 | 10 | 0.0 | 0.0 | 4.6 | 0.0 | 0.0 |
| lip-smacking (borderline) | 10 | 10 | 20.0 | 0.0 | 5.3 | 7.5 | 7.5 |
| lip-smacking (borderline) | 5 | 10 | 10.0 | 0.0 | 5.7 | 1.8 | 1.8 |

Clip-majority confusion (rows = class, columns = most frequent emitted label):


clean:

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| tongue-clicking | 0 | 0 | 1 | 0 | 3 | 0 | 9 | 3 | 0 | 16 |
| lip-popping | 0 | 0 | 0 | 0 | 1 | 9 | 0 | 9 | 0 | 19 |
| lip-smacking | 1 | 0 | 0 | 0 | 1 | 0 | 4 | 4 | 0 | 10 |

20:

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| tongue-clicking | 1 | 0 | 0 | 1 | 1 | 0 | 12 | 1 | 0 | 16 |
| lip-popping | 0 | 1 | 0 | 0 | 3 | 7 | 0 | 7 | 1 | 19 |
| lip-smacking | 1 | 0 | 0 | 0 | 1 | 0 | 5 | 3 | 0 | 10 |

10:

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| tongue-clicking | 0 | 0 | 0 | 0 | 2 | 0 | 9 | 4 | 1 | 16 |
| lip-popping | 2 | 0 | 0 | 0 | 2 | 4 | 3 | 6 | 2 | 19 |
| lip-smacking | 0 | 0 | 1 | 0 | 0 | 0 | 7 | 2 | 0 | 10 |

5:

| truth \ predicted | rise | fall | arch | dip | flat | pop | click | hiss | none | n |
|---|---|---|---|---|---|---|---|---|---|---|
| tongue-clicking | 0 | 0 | 0 | 1 | 5 | 0 | 7 | 3 | 0 | 16 |
| lip-popping | 2 | 0 | 1 | 1 | 2 | 2 | 0 | 7 | 4 | 19 |
| lip-smacking | 1 | 0 | 0 | 0 | 0 | 0 | 5 | 4 | 0 | 10 |

False accepts, negatives (user list), as recorded:

| class | clips | min | clips with FA % | FA groups / min | fireable events / min | actions |
|---|---|---|---|---|---|---|
| coughing | 22 | 1.0 | 0.0 | 0.00 | 11.42 |  |
| sighing | 11 | 0.5 | 9.1 | 2.09 | 2.09 | tap 1 |
| laughing | 5 | 0.4 | 0.0 | 0.00 | 7.02 |  |
| throat-clearing | 18 | 0.7 | 0.0 | 0.00 | 2.84 |  |
| sneezing | 9 | 0.4 | 0.0 | 0.00 | 2.60 |  |
| yawning | 13 | 0.7 | 7.7 | 1.50 | 6.00 | swipe_down 1 |
| teeth-chattering | 10 | 0.4 | 30.0 | 6.78 | 42.97 | tap 3 |
| teeth-grinding | 9 | 0.5 | 11.1 | 2.11 | 21.13 | tap 1 |
| ALL | 97 | 4.5 | 6.2 | 1.32 | 11.23 | tap 5, swipe_down 1 |

False accepts, other nonverbal classes, as recorded:

| class | clips | min | clips with FA % | FA groups / min | fireable events / min | actions |
|---|---|---|---|---|---|---|
| panting | 14 | 0.7 | 0.0 | 0.00 | 1.45 |  |
| crying | 4 | 0.4 | 0.0 | 0.00 | 5.53 |  |
| moaning | 12 | 0.6 | 8.3 | 1.76 | 7.04 | swipe_down 1 |
| screaming | 19 | 0.8 | 42.1 | 9.98 | 21.21 | swipe_down 4, swipe_right 2, long_press 1, swipe_up 1 |
| nose-blowing | 13 | 0.5 | 0.0 | 0.00 | 1.85 |  |
| ALL | 62 | 3.0 | 14.5 | 3.04 | 8.44 | swipe_down 5, swipe_right 2, long_press 1, swipe_up 1 |

Lines: 1092; strict-parse/label errors: 0; outside generate.py's line space: 237

