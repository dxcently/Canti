# REAL audio: esc50

```
ESC-50 (Piczak 2015, CC BY-NC 3.0): 2000 five-second environmental clips, 50 classes, 44.1 kHz mono, as
NEGATIVES. The class of interest is "cat" (40 clips, mostly meows): a real cat near the phone is the realistic
version of the user-meow false accepts. Every other class is reported too (dog, crying baby, door knock,
mouse click, keyboard typing, clock tick, snoring, breathing ...), because impulsive household sounds are the
obvious threat to pop / click.

One extra meow: MUSAN noise/sound-bible/noise-sound-bible-0013 ("Cat Meow 2") is scored in the cat row as well.
Split: by src_file (the freesound recording a clip was cut from), 30 % tune / 70 % test.
Rate handling: 44.1 kHz -> 16 kHz with scipy resample_poly (resample.to_16k). ESC-50 pads short sounds with
digital silence; leading / trailing silence is trimmed like everywhere else, but silence INSIDE a clip stays and
drops the noise floor to its -85 dB clamp, which makes the gate very sensitive there (a mic never gives exact zeros).
```

### FROZEN config, TEST split  <- headline

| class | clips | min | clips with FA % | FA groups/min | fireable events/min | actions |
|---|---|---|---|---|---|---|
| cat | 24 | 1.5 | 37.5 | 7.14 | 22.08 | swipe_up 4, long_press 4, tap 1, swipe_right 1, swipe_down 1 |
| ALL | 1455 | 109.6 | 17.0 | 2.63 | 10.10 | tap 111, back 53, long_press 41, swipe_down 34, swipe_up 25, swipe_right 18, swipe_left 5, listen_for_phrase 1 |
| rooster | 26 | 1.4 | 50.0 | 9.92 | 12.76 | swipe_down 4, long_press 3, swipe_right 3, swipe_up 2, tap 1, swipe_left 1 |
| glass_breaking | 29 | 1.1 | 31.0 | 8.37 | 17.66 | back 6, swipe_up 2, tap 1 |
| cow | 25 | 2.0 | 52.0 | 8.17 | 9.19 | swipe_down 5, swipe_right 3, long_press 3, swipe_up 2, tap 2, swipe_left 1 |
| can_opening | 25 | 1.4 | 36.0 | 7.72 | 28.08 | back 9, tap 2 |
| mouse_click | 26 | 1.8 | 30.8 | 6.76 | 25.90 | back 7, tap 5 |
| clock_tick | 26 | 2.1 | 19.2 | 4.69 | 15.47 | back 5, tap 4, listen_for_phrase 1 |
| hen | 32 | 2.5 | 34.4 | 4.41 | 28.48 | tap 4, swipe_down 3, swipe_right 2, long_press 1, swipe_left 1 |
| water_drops | 25 | 1.6 | 20.0 | 4.25 | 19.44 | tap 7 |
| chirping_birds | 31 | 2.6 | 19.4 | 3.89 | 11.66 | swipe_down 5, tap 2, swipe_right 1, back 1, swipe_up 1 |
| church_bells | 31 | 2.6 | 22.6 | 3.87 | 11.23 | swipe_up 3, long_press 2, swipe_down 2, swipe_right 2, swipe_left 1 |
| clock_alarm | 27 | 2.1 | 22.2 | 3.80 | 22.32 | long_press 6, swipe_right 2 |
| footsteps | 30 | 2.3 | 23.3 | 3.43 | 23.98 | tap 8 |
| frog | 29 | 2.4 | 20.7 | 3.33 | 10.81 | swipe_down 3, long_press 2, tap 1, swipe_up 1, back 1 |
| hand_saw | 25 | 2.0 | 20.0 | 2.99 | 8.97 | tap 5, back 1 |
| rain | 33 | 2.7 | 24.2 | 2.91 | 6.91 | tap 5, back 3 |
| snoring | 21 | 1.8 | 19.0 | 2.86 | 5.14 | tap 3, swipe_right 2 |
| laughing | 30 | 2.2 | 20.0 | 2.76 | 13.78 | tap 3, swipe_down 2, swipe_up 1 |
| door_wood_creaks | 30 | 2.2 | 20.0 | 2.69 | 12.08 | swipe_down 3, back 2, long_press 1 |
| crickets | 27 | 2.2 | 18.5 | 2.67 | 6.22 | back 3, tap 1, long_press 1, swipe_right 1 |
| crackling_fire | 28 | 2.3 | 17.9 | 2.66 | 12.83 | tap 4, back 2 |
| keyboard_typing | 33 | 2.7 | 21.2 | 2.60 | 22.62 | tap 4, back 3 |
| car_horn | 32 | 2.0 | 15.6 | 2.56 | 3.58 | long_press 3, swipe_up 1, swipe_right 1 |
| insects | 26 | 2.0 | 15.4 | 2.47 | 2.97 | long_press 3, tap 2 |
| dog | 30 | 2.1 | 16.7 | 2.41 | 8.66 | long_press 2, tap 1, swipe_up 1, swipe_down 1 |
| brushing_teeth | 27 | 2.2 | 18.5 | 2.30 | 13.32 | back 3, tap 1, long_press 1 |
| washing_machine | 32 | 2.6 | 18.8 | 2.27 | 4.92 | tap 3, long_press 2, swipe_up 1 |
| drinking_sipping | 28 | 1.8 | 14.3 | 2.22 | 11.08 | tap 2, long_press 1, back 1 |
| chainsaw | 28 | 2.3 | 17.9 | 2.14 | 5.14 | tap 2, swipe_up 1, long_press 1, swipe_down 1 |
| pig | 38 | 2.9 | 15.8 | 2.10 | 8.39 | tap 2, back 2, long_press 1, swipe_down 1 |
| crow | 29 | 2.2 | 13.8 | 1.86 | 7.43 | swipe_up 1, long_press 1, tap 1, swipe_left 1 |
| breathing | 25 | 1.8 | 8.0 | 1.67 | 2.78 | back 2, tap 1 |
| crying_baby | 30 | 2.5 | 10.0 | 1.63 | 8.98 | tap 3, swipe_down 1 |
| train | 30 | 2.5 | 10.0 | 1.60 | 4.40 | tap 4 |
| siren | 32 | 2.6 | 12.5 | 1.56 | 7.02 | swipe_up 2, swipe_down 1, tap 1 |
| wind | 31 | 2.6 | 12.9 | 1.55 | 2.71 | tap 2, back 1, swipe_down 1 |
| sneezing | 31 | 1.4 | 3.2 | 1.42 | 6.39 | tap 2 |
| pouring_water | 29 | 2.2 | 10.3 | 1.36 | 7.72 | tap 3 |
| fireworks | 36 | 3.0 | 11.1 | 1.35 | 9.75 | tap 3, swipe_up 1 |
| engine | 28 | 2.3 | 10.7 | 1.33 | 22.20 | tap 3 |
| sheep | 31 | 2.6 | 9.7 | 1.18 | 3.53 | tap 2, swipe_up 1 |
| toilet_flush | 31 | 2.6 | 9.7 | 1.16 | 5.81 | tap 3 |
| helicopter | 24 | 1.9 | 4.2 | 1.03 | 2.05 | tap 1, long_press 1 |
| thunderstorm | 30 | 2.5 | 6.7 | 0.80 | 3.20 | tap 2 |
| coughing | 26 | 1.4 | 3.8 | 0.72 | 5.75 | tap 1 |
| airplane | 34 | 2.8 | 5.9 | 0.71 | 1.76 | long_press 2 |
| sea_waves | 36 | 3.0 | 5.6 | 0.67 | 1.68 | tap 2 |
| clapping | 31 | 2.5 | 3.2 | 0.40 | 9.63 | tap 1 |
| vacuum_cleaner | 31 | 2.6 | 3.2 | 0.39 | 1.16 | back 1 |
| door_wood_knock | 26 | 1.4 | 0.0 | 0.00 | 5.01 |  |

'Sounds like' of all events, cat clips:

| hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound |
|---|---|---|---|---|---|---|---|
| 18 | 15 | 14 | 1 | 0 | 1 | 17 | 9 |

Lines: 4798; strict-parse/label errors: 0; outside generate.py's line space: 1270

### FROZEN config, TUNE split

| class | clips | min | clips with FA % | FA groups/min | fireable events/min | actions |
|---|---|---|---|---|---|---|
| cat | 17 | 1.4 | 52.9 | 8.86 | 19.94 | long_press 7, swipe_up 2, swipe_right 2, swipe_down 1 |
| ALL | 546 | 40.7 | 18.7 | 3.00 | 11.57 | tap 37, back 26, long_press 19, swipe_up 18, swipe_down 10, swipe_left 6, swipe_right 4, listen_for_phrase 2 |
| mouse_click | 14 | 1.0 | 35.7 | 8.94 | 18.87 | back 7, tap 2 |
| glass_breaking | 11 | 0.5 | 36.4 | 8.84 | 15.46 | back 4 |
| hen | 8 | 0.6 | 50.0 | 8.06 | 25.78 | tap 3, long_press 1, swipe_down 1 |
| rooster | 14 | 0.7 | 35.7 | 7.15 | 20.01 | swipe_left 2, swipe_up 1, tap 1, swipe_down 1 |
| sheep | 9 | 0.7 | 44.4 | 6.75 | 12.16 | back 2, long_press 1, swipe_up 1, swipe_right 1 |
| coughing | 14 | 0.6 | 14.3 | 6.31 | 17.35 | tap 4 |
| frog | 11 | 0.9 | 45.5 | 5.45 | 21.82 | swipe_left 2, swipe_up 2, tap 1 |
| clock_tick | 14 | 1.2 | 14.3 | 5.15 | 30.02 | back 5, tap 1 |
| crackling_fire | 12 | 1.0 | 41.7 | 5.05 | 13.13 | tap 4, listen_for_phrase 1 |
| can_opening | 15 | 0.8 | 26.7 | 5.00 | 32.47 | back 2, tap 1, listen_for_phrase 1 |
| cow | 15 | 1.0 | 26.7 | 4.91 | 9.82 | swipe_up 2, swipe_down 1, tap 1, long_press 1 |
| water_drops | 15 | 1.1 | 26.7 | 4.59 | 12.86 | swipe_up 3, tap 1, back 1 |
| wind | 9 | 0.8 | 11.1 | 4.00 | 6.67 | long_press 1, tap 1, swipe_up 1 |
| car_horn | 8 | 0.6 | 25.0 | 3.42 | 22.23 | swipe_right 1, swipe_down 1 |
| chainsaw | 12 | 1.0 | 25.0 | 3.04 | 5.07 | swipe_up 2, long_press 1 |
| fireworks | 4 | 0.3 | 25.0 | 3.00 | 3.00 | tap 1 |
| door_wood_creaks | 10 | 0.7 | 20.0 | 2.84 | 5.68 | swipe_down 1, tap 1 |
| crickets | 13 | 1.1 | 15.4 | 2.77 | 7.38 | tap 2, back 1 |
| chirping_birds | 9 | 0.8 | 22.2 | 2.67 | 10.67 | swipe_down 1, tap 1 |
| insects | 14 | 1.2 | 21.4 | 2.57 | 2.57 | long_press 2, swipe_left 1 |
| crying_baby | 10 | 0.8 | 20.0 | 2.50 | 5.00 | swipe_down 1, swipe_up 1 |
| helicopter | 16 | 1.3 | 18.8 | 2.34 | 2.34 | long_press 2, tap 1 |
| breathing | 15 | 0.9 | 13.3 | 2.13 | 6.40 | tap 1, back 1 |
| sneezing | 9 | 0.5 | 11.1 | 2.08 | 12.47 | tap 1 |
| clock_alarm | 13 | 1.0 | 15.4 | 1.97 | 22.69 | long_press 2 |
| brushing_teeth | 13 | 1.0 | 15.4 | 1.94 | 6.79 | back 2 |
| keyboard_typing | 7 | 0.6 | 14.3 | 1.78 | 16.00 | tap 1 |
| hand_saw | 15 | 1.2 | 13.3 | 1.62 | 13.73 | back 1, tap 1 |
| siren | 8 | 0.7 | 12.5 | 1.50 | 9.00 | swipe_up 1 |
| washing_machine | 8 | 0.7 | 12.5 | 1.50 | 1.50 | long_press 1 |
| clapping | 9 | 0.7 | 11.1 | 1.50 | 23.93 | tap 1 |
| toilet_flush | 9 | 0.7 | 11.1 | 1.39 | 5.56 | tap 1 |
| dog | 10 | 0.7 | 10.0 | 1.39 | 9.70 | swipe_up 1 |
| door_wood_knock | 14 | 0.7 | 7.1 | 1.36 | 9.51 | tap 1 |
| laughing | 10 | 0.7 | 10.0 | 1.34 | 26.85 | swipe_down 1 |
| vacuum_cleaner | 9 | 0.7 | 11.1 | 1.33 | 2.67 | tap 1 |
| church_bells | 9 | 0.8 | 11.1 | 1.33 | 8.00 | swipe_up 1 |
| snoring | 19 | 1.5 | 10.5 | 1.30 | 5.83 | tap 1, swipe_down 1 |
| train | 10 | 0.8 | 10.0 | 1.20 | 7.20 | tap 1 |
| crow | 11 | 0.9 | 9.1 | 1.12 | 6.71 | swipe_left 1 |
| drinking_sipping | 12 | 0.9 | 8.3 | 1.09 | 16.38 | tap 1 |
| airplane | 6 | 0.5 | 0.0 | 0.00 | 6.00 |  |
| engine | 12 | 0.9 | 0.0 | 0.00 | 1.07 |  |
| footsteps | 10 | 0.8 | 0.0 | 0.00 | 12.29 |  |
| pig | 2 | 0.1 | 0.0 | 0.00 | 0.00 |  |
| pouring_water | 11 | 0.8 | 0.0 | 0.00 | 9.93 |  |
| rain | 7 | 0.6 | 0.0 | 0.00 | 0.00 |  |
| sea_waves | 4 | 0.3 | 0.0 | 0.00 | 0.00 |  |
| thunderstorm | 10 | 0.8 | 0.0 | 0.00 | 1.20 |  |

'Sounds like' of all events, cat clips:

| hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound |
|---|---|---|---|---|---|---|---|
| 16 | 17 | 4 | 0 | 0 | 2 | 8 | 3 |

Lines: 1788; strict-parse/label errors: 0; outside generate.py's line space: 452

### FIXED config, TEST split

| class | clips | min | clips with FA % | FA groups/min | fireable events/min | actions |
|---|---|---|---|---|---|---|
| cat | 24 | 1.5 | 33.3 | 6.49 | 22.08 | swipe_up 4, long_press 4, tap 1, swipe_down 1 |
| ALL | 1455 | 109.6 | 15.5 | 2.39 | 9.52 | tap 96, back 48, long_press 40, swipe_down 32, swipe_up 23, swipe_right 17, swipe_left 5, listen_for_phrase 1 |
| rooster | 26 | 1.4 | 50.0 | 9.21 | 10.63 | swipe_down 5, swipe_right 3, long_press 2, swipe_up 2, swipe_left 1 |
| cow | 25 | 2.0 | 52.0 | 8.17 | 8.68 | swipe_down 5, swipe_right 3, long_press 3, swipe_up 2, tap 2, swipe_left 1 |
| glass_breaking | 29 | 1.1 | 27.6 | 7.44 | 16.73 | back 5, swipe_up 2, tap 1 |
| can_opening | 25 | 1.4 | 32.0 | 7.02 | 26.67 | back 8, tap 2 |
| mouse_click | 26 | 1.8 | 30.8 | 6.76 | 25.90 | back 7, tap 5 |
| clock_alarm | 27 | 2.1 | 25.9 | 4.75 | 22.32 | long_press 8, swipe_right 2 |
| clock_tick | 26 | 2.1 | 19.2 | 4.69 | 15.00 | back 5, tap 4, listen_for_phrase 1 |
| church_bells | 31 | 2.6 | 22.6 | 3.87 | 10.84 | swipe_up 3, long_press 2, swipe_down 2, swipe_right 2, swipe_left 1 |
| hen | 32 | 2.5 | 28.1 | 3.61 | 26.07 | tap 4, swipe_right 2, swipe_down 2, swipe_left 1 |
| chirping_birds | 31 | 2.6 | 16.1 | 3.50 | 11.27 | swipe_down 5, tap 2, swipe_right 1, back 1 |
| footsteps | 30 | 2.3 | 23.3 | 3.43 | 23.55 | tap 8 |
| laughing | 30 | 2.2 | 23.3 | 3.22 | 11.94 | tap 4, swipe_down 2, swipe_up 1 |
| crickets | 27 | 2.2 | 22.2 | 3.11 | 6.67 | back 3, tap 1, swipe_left 1, long_press 1, swipe_right 1 |
| water_drops | 25 | 1.6 | 20.0 | 3.04 | 13.97 | tap 5 |
| snoring | 21 | 1.8 | 19.0 | 2.86 | 5.14 | tap 3, swipe_right 2 |
| door_wood_creaks | 30 | 2.2 | 20.0 | 2.69 | 12.08 | swipe_down 3, back 2, long_press 1 |
| crackling_fire | 28 | 2.3 | 17.9 | 2.66 | 12.83 | tap 4, back 2 |
| car_horn | 32 | 2.0 | 15.6 | 2.56 | 3.58 | long_press 3, swipe_up 1, swipe_right 1 |
| rain | 33 | 2.7 | 21.2 | 2.55 | 6.91 | tap 4, back 3 |
| frog | 29 | 2.4 | 17.2 | 2.50 | 9.57 | long_press 2, tap 1, swipe_up 1, swipe_down 1, back 1 |
| brushing_teeth | 27 | 2.2 | 18.5 | 2.30 | 11.94 | back 3, tap 1, long_press 1 |
| drinking_sipping | 28 | 1.8 | 14.3 | 2.22 | 9.97 | tap 2, long_press 1, back 1 |
| chainsaw | 28 | 2.3 | 17.9 | 2.14 | 6.43 | tap 2, swipe_up 1, long_press 1, swipe_down 1 |
| hand_saw | 25 | 2.0 | 12.0 | 1.99 | 7.48 | tap 3, back 1 |
| siren | 32 | 2.6 | 15.6 | 1.95 | 6.63 | swipe_up 2, swipe_down 2, tap 1 |
| dog | 30 | 2.1 | 13.3 | 1.92 | 8.18 | long_press 2, tap 1, swipe_down 1 |
| washing_machine | 32 | 2.6 | 15.6 | 1.89 | 4.92 | tap 2, long_press 2, swipe_up 1 |
| keyboard_typing | 33 | 2.7 | 15.2 | 1.85 | 21.88 | tap 4, back 1 |
| pig | 38 | 2.9 | 13.2 | 1.75 | 7.69 | tap 2, back 1, long_press 1, swipe_down 1 |
| fireworks | 36 | 3.0 | 13.9 | 1.68 | 9.42 | tap 4, swipe_up 1 |
| breathing | 25 | 1.8 | 8.0 | 1.67 | 2.78 | back 2, tap 1 |
| train | 30 | 2.5 | 10.0 | 1.60 | 4.40 | tap 4 |
| wind | 31 | 2.6 | 12.9 | 1.55 | 1.55 | tap 2, back 1, swipe_down 1 |
| insects | 26 | 2.0 | 11.5 | 1.48 | 1.98 | long_press 2, tap 1 |
| sneezing | 31 | 1.4 | 3.2 | 1.42 | 9.23 | tap 2 |
| crow | 29 | 2.2 | 10.3 | 1.39 | 6.97 | swipe_up 1, long_press 1, tap 1 |
| sheep | 31 | 2.6 | 9.7 | 1.18 | 2.74 | tap 2, swipe_up 1 |
| helicopter | 24 | 1.9 | 4.2 | 1.03 | 2.05 | tap 1, long_press 1 |
| engine | 28 | 2.3 | 7.1 | 0.89 | 22.20 | tap 2 |
| toilet_flush | 31 | 2.6 | 6.5 | 0.78 | 6.20 | tap 2 |
| coughing | 26 | 1.4 | 3.8 | 0.72 | 5.75 | tap 1 |
| airplane | 34 | 2.8 | 5.9 | 0.71 | 1.76 | long_press 2 |
| crying_baby | 30 | 2.5 | 3.3 | 0.41 | 6.94 | tap 1 |
| clapping | 31 | 2.5 | 3.2 | 0.40 | 9.23 | tap 1 |
| thunderstorm | 30 | 2.5 | 3.3 | 0.40 | 2.40 | tap 1 |
| vacuum_cleaner | 31 | 2.6 | 3.2 | 0.39 | 1.16 | back 1 |
| sea_waves | 36 | 3.0 | 2.8 | 0.34 | 1.68 | tap 1 |
| door_wood_knock | 26 | 1.4 | 0.0 | 0.00 | 5.01 |  |
| pouring_water | 29 | 2.2 | 0.0 | 0.00 | 3.63 |  |

'Sounds like' of all events, cat clips:

| hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound |
|---|---|---|---|---|---|---|---|
| 18 | 18 | 15 | 1 | 0 | 2 | 17 | 9 |

Lines: 4722; strict-parse/label errors: 0; outside generate.py's line space: 1308

### FIXED config, TUNE split

| class | clips | min | clips with FA % | FA groups/min | fireable events/min | actions |
|---|---|---|---|---|---|---|
| cat | 17 | 1.4 | 52.9 | 8.86 | 19.94 | long_press 7, swipe_up 2, swipe_right 2, swipe_down 1 |
| ALL | 546 | 40.7 | 16.3 | 2.60 | 10.94 | tap 30, back 26, long_press 16, swipe_up 16, swipe_down 7, swipe_left 5, swipe_right 4, listen_for_phrase 2 |
| mouse_click | 14 | 1.0 | 35.7 | 8.94 | 18.87 | back 7, tap 2 |
| glass_breaking | 11 | 0.5 | 36.4 | 8.84 | 15.46 | back 4 |
| sheep | 9 | 0.7 | 44.4 | 6.75 | 12.16 | back 2, long_press 1, swipe_up 1, swipe_right 1 |
| hen | 8 | 0.6 | 50.0 | 6.44 | 22.56 | tap 3, long_press 1 |
| coughing | 14 | 0.6 | 14.3 | 6.31 | 17.35 | tap 4 |
| clock_tick | 14 | 1.2 | 14.3 | 5.15 | 30.02 | back 5, tap 1 |
| can_opening | 15 | 0.8 | 26.7 | 5.00 | 27.48 | back 2, tap 1, listen_for_phrase 1 |
| frog | 11 | 0.9 | 36.4 | 4.36 | 21.82 | swipe_left 2, tap 1, swipe_up 1 |
| rooster | 14 | 0.7 | 21.4 | 4.29 | 18.58 | swipe_left 2, swipe_down 1 |
| crackling_fire | 12 | 1.0 | 33.3 | 4.04 | 13.13 | tap 3, listen_for_phrase 1 |
| cow | 15 | 1.0 | 26.7 | 3.93 | 8.84 | swipe_up 3, long_press 1 |
| water_drops | 15 | 1.1 | 20.0 | 3.67 | 10.11 | swipe_up 3, back 1 |
| car_horn | 8 | 0.6 | 25.0 | 3.42 | 22.23 | swipe_right 1, swipe_down 1 |
| fireworks | 4 | 0.3 | 25.0 | 3.00 | 3.00 | tap 1 |
| crickets | 13 | 1.1 | 15.4 | 2.77 | 7.38 | tap 2, back 1 |
| chirping_birds | 9 | 0.8 | 22.2 | 2.67 | 10.67 | swipe_down 1, tap 1 |
| wind | 9 | 0.8 | 11.1 | 2.67 | 5.33 | long_press 1, swipe_up 1 |
| crying_baby | 10 | 0.8 | 20.0 | 2.50 | 5.00 | swipe_down 1, swipe_up 1 |
| breathing | 15 | 0.9 | 13.3 | 2.13 | 6.40 | tap 1, back 1 |
| sneezing | 9 | 0.5 | 11.1 | 2.08 | 12.47 | tap 1 |
| clock_alarm | 13 | 1.0 | 15.4 | 1.97 | 24.66 | long_press 2 |
| brushing_teeth | 13 | 1.0 | 15.4 | 1.94 | 5.82 | back 2 |
| insects | 14 | 1.2 | 14.3 | 1.71 | 1.71 | swipe_left 1, long_press 1 |
| hand_saw | 15 | 1.2 | 13.3 | 1.62 | 13.73 | back 1, tap 1 |
| helicopter | 16 | 1.3 | 12.5 | 1.56 | 1.56 | long_press 1, tap 1 |
| siren | 8 | 0.7 | 12.5 | 1.50 | 9.00 | swipe_up 1 |
| washing_machine | 8 | 0.7 | 12.5 | 1.50 | 1.50 | long_press 1 |
| clapping | 9 | 0.7 | 11.1 | 1.50 | 19.45 | tap 1 |
| door_wood_creaks | 10 | 0.7 | 10.0 | 1.42 | 5.68 | swipe_down 1 |
| toilet_flush | 9 | 0.7 | 11.1 | 1.39 | 4.17 | tap 1 |
| dog | 10 | 0.7 | 10.0 | 1.39 | 12.47 | swipe_up 1 |
| door_wood_knock | 14 | 0.7 | 7.1 | 1.36 | 9.51 | tap 1 |
| vacuum_cleaner | 9 | 0.7 | 11.1 | 1.33 | 2.67 | tap 1 |
| church_bells | 9 | 0.8 | 11.1 | 1.33 | 6.67 | swipe_up 1 |
| snoring | 19 | 1.5 | 10.5 | 1.30 | 5.83 | tap 1, swipe_down 1 |
| train | 10 | 0.8 | 10.0 | 1.20 | 7.20 | tap 1 |
| drinking_sipping | 12 | 0.9 | 8.3 | 1.09 | 16.38 | tap 1 |
| chainsaw | 12 | 1.0 | 8.3 | 1.01 | 3.04 | swipe_up 1 |
| airplane | 6 | 0.5 | 0.0 | 0.00 | 4.00 |  |
| crow | 11 | 0.9 | 0.0 | 0.00 | 5.59 |  |
| engine | 12 | 0.9 | 0.0 | 0.00 | 1.07 |  |
| footsteps | 10 | 0.8 | 0.0 | 0.00 | 12.29 |  |
| keyboard_typing | 7 | 0.6 | 0.0 | 0.00 | 10.67 |  |
| laughing | 10 | 0.7 | 0.0 | 0.00 | 22.82 |  |
| pig | 2 | 0.1 | 0.0 | 0.00 | 0.00 |  |
| pouring_water | 11 | 0.8 | 0.0 | 0.00 | 9.93 |  |
| rain | 7 | 0.6 | 0.0 | 0.00 | 0.00 |  |
| sea_waves | 4 | 0.3 | 0.0 | 0.00 | 0.00 |  |
| thunderstorm | 10 | 0.8 | 0.0 | 0.00 | 1.20 |  |

'Sounds like' of all events, cat clips:

| hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound |
|---|---|---|---|---|---|---|---|
| 16 | 17 | 4 | 0 | 0 | 2 | 8 | 3 |

Lines: 1755; strict-parse/label errors: 0; outside generate.py's line space: 468

### TUNED config, TEST split

| class | clips | min | clips with FA % | FA groups/min | fireable events/min | actions |
|---|---|---|---|---|---|---|
| cat | 24 | 1.5 | 37.5 | 7.14 | 18.18 | swipe_up 6, long_press 4, swipe_down 1 |
| ALL | 1455 | 109.6 | 12.2 | 1.93 | 6.62 | back 47, tap 43, long_press 40, swipe_down 32, swipe_up 26, swipe_right 17, swipe_left 6, listen_for_phrase 1 |
| rooster | 26 | 1.4 | 50.0 | 9.21 | 10.63 | swipe_down 5, swipe_right 3, long_press 2, swipe_up 2, swipe_left 1 |
| cow | 25 | 2.0 | 44.0 | 7.15 | 7.66 | swipe_down 5, swipe_right 3, long_press 3, swipe_up 2, swipe_left 1 |
| glass_breaking | 29 | 1.1 | 24.1 | 6.51 | 14.87 | back 5, swipe_up 2 |
| mouse_click | 26 | 1.8 | 26.9 | 6.19 | 17.45 | tap 7, back 4 |
| can_opening | 25 | 1.4 | 24.0 | 5.62 | 16.85 | back 8 |
| water_drops | 25 | 1.6 | 20.0 | 4.86 | 10.32 | tap 8 |
| clock_alarm | 27 | 2.1 | 25.9 | 4.75 | 22.32 | long_press 8, swipe_right 2 |
| clock_tick | 26 | 2.1 | 19.2 | 4.69 | 11.25 | back 5, tap 5 |
| hen | 32 | 2.5 | 31.2 | 4.01 | 16.44 | swipe_down 3, tap 3, swipe_right 2, swipe_left 1, long_press 1 |
| church_bells | 31 | 2.6 | 22.6 | 3.87 | 10.45 | swipe_up 3, long_press 2, swipe_down 2, swipe_right 2, swipe_left 1 |
| chirping_birds | 31 | 2.6 | 16.1 | 3.50 | 10.49 | swipe_down 5, back 2, swipe_up 1, swipe_right 1 |
| footsteps | 30 | 2.3 | 26.7 | 3.43 | 24.41 | tap 8 |
| door_wood_creaks | 30 | 2.2 | 20.0 | 3.13 | 8.50 | swipe_down 2, back 2, swipe_left 1, swipe_up 1, long_press 1 |
| crickets | 27 | 2.2 | 18.5 | 2.67 | 6.22 | back 3, swipe_left 1, long_press 1, swipe_right 1 |
| car_horn | 32 | 2.0 | 15.6 | 2.56 | 3.58 | long_press 3, swipe_up 1, swipe_right 1 |
| brushing_teeth | 27 | 2.2 | 18.5 | 2.30 | 10.11 | back 4, long_press 1 |
| drinking_sipping | 28 | 1.8 | 14.3 | 2.22 | 6.09 | tap 2, long_press 1, back 1 |
| frog | 29 | 2.4 | 13.8 | 2.08 | 9.15 | long_press 2, swipe_up 1, swipe_down 1, back 1 |
| fireworks | 36 | 3.0 | 11.1 | 1.68 | 7.06 | tap 5 |
| siren | 32 | 2.6 | 12.5 | 1.56 | 6.24 | swipe_up 2, swipe_down 2 |
| rain | 33 | 2.7 | 9.1 | 1.45 | 2.55 | back 4 |
| dog | 30 | 2.1 | 10.0 | 1.44 | 5.29 | long_press 2, swipe_down 1 |
| laughing | 30 | 2.2 | 10.0 | 1.38 | 8.27 | swipe_down 2, swipe_up 1 |
| snoring | 21 | 1.8 | 4.8 | 1.14 | 2.29 | swipe_right 2 |
| washing_machine | 32 | 2.6 | 9.4 | 1.13 | 3.03 | long_press 2, swipe_up 1 |
| keyboard_typing | 33 | 2.7 | 9.1 | 1.11 | 17.06 | listen_for_phrase 1, tap 1, back 1 |
| pig | 38 | 2.9 | 7.9 | 1.05 | 3.49 | back 1, long_press 1, swipe_down 1 |
| insects | 26 | 2.0 | 7.7 | 0.99 | 1.48 | long_press 2 |
| crow | 29 | 2.2 | 6.9 | 0.93 | 6.04 | swipe_up 1, long_press 1 |
| crackling_fire | 28 | 2.3 | 7.1 | 0.89 | 3.54 | back 2 |
| chainsaw | 28 | 2.3 | 7.1 | 0.86 | 3.00 | swipe_up 1, swipe_down 1 |
| clapping | 31 | 2.5 | 6.5 | 0.80 | 3.61 | tap 2 |
| wind | 31 | 2.6 | 6.5 | 0.77 | 0.77 | back 1, swipe_down 1 |
| coughing | 26 | 1.4 | 3.8 | 0.72 | 4.31 | tap 1 |
| airplane | 34 | 2.8 | 5.9 | 0.71 | 1.06 | long_press 2 |
| breathing | 25 | 1.8 | 4.0 | 0.56 | 1.11 | back 1 |
| helicopter | 24 | 1.9 | 4.2 | 0.51 | 0.51 | long_press 1 |
| hand_saw | 25 | 2.0 | 4.0 | 0.50 | 2.99 | back 1 |
| sheep | 31 | 2.6 | 3.2 | 0.39 | 1.57 | swipe_up 1 |
| toilet_flush | 31 | 2.6 | 3.2 | 0.39 | 3.10 | tap 1 |
| vacuum_cleaner | 31 | 2.6 | 3.2 | 0.39 | 0.77 | back 1 |
| crying_baby | 30 | 2.5 | 0.0 | 0.00 | 6.12 |  |
| door_wood_knock | 26 | 1.4 | 0.0 | 0.00 | 2.86 |  |
| engine | 28 | 2.3 | 0.0 | 0.00 | 7.55 |  |
| pouring_water | 29 | 2.2 | 0.0 | 0.00 | 2.27 |  |
| sea_waves | 36 | 3.0 | 0.0 | 0.00 | 0.00 |  |
| sneezing | 31 | 1.4 | 0.0 | 0.00 | 3.55 |  |
| thunderstorm | 30 | 2.5 | 0.0 | 0.00 | 0.00 |  |
| train | 30 | 2.5 | 0.0 | 0.00 | 0.00 |  |

'Sounds like' of all events, cat clips:

| hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound |
|---|---|---|---|---|---|---|---|
| 18 | 18 | 15 | 1 | 0 | 2 | 17 | 0 |

Lines: 4294; strict-parse/label errors: 0; outside generate.py's line space: 1309

### TUNED config, TUNE split

| class | clips | min | clips with FA % | FA groups/min | fireable events/min | actions |
|---|---|---|---|---|---|---|
| cat | 17 | 1.4 | 52.9 | 8.86 | 18.46 | long_press 7, swipe_up 2, swipe_right 2, swipe_down 1 |
| ALL | 546 | 40.7 | 12.6 | 1.99 | 7.79 | back 24, long_press 18, swipe_up 16, swipe_down 7, tap 7, swipe_left 5, swipe_right 4 |
| glass_breaking | 11 | 0.5 | 45.5 | 11.05 | 13.25 | back 5 |
| sheep | 9 | 0.7 | 44.4 | 6.75 | 12.16 | back 2, long_press 1, swipe_up 1, swipe_right 1 |
| water_drops | 15 | 1.1 | 20.0 | 4.59 | 11.02 | swipe_up 3, back 2 |
| rooster | 14 | 0.7 | 21.4 | 4.29 | 5.72 | swipe_left 2, swipe_down 1 |
| clock_tick | 14 | 1.2 | 7.1 | 4.29 | 26.59 | back 5 |
| clock_alarm | 13 | 1.0 | 23.1 | 3.95 | 22.69 | long_press 4 |
| cow | 15 | 1.0 | 26.7 | 3.93 | 8.84 | swipe_up 3, long_press 1 |
| can_opening | 15 | 0.8 | 20.0 | 3.75 | 21.23 | back 2, tap 1 |
| car_horn | 8 | 0.6 | 25.0 | 3.42 | 10.26 | swipe_right 1, swipe_down 1 |
| frog | 11 | 0.9 | 27.3 | 3.27 | 18.55 | swipe_left 2, swipe_up 1 |
| fireworks | 4 | 0.3 | 25.0 | 3.00 | 6.00 | tap 1 |
| wind | 9 | 0.8 | 11.1 | 2.67 | 5.33 | long_press 1, swipe_up 1 |
| crying_baby | 10 | 0.8 | 20.0 | 2.50 | 5.00 | swipe_down 1, swipe_up 1 |
| hand_saw | 15 | 1.2 | 20.0 | 2.42 | 12.92 | back 2, tap 1 |
| crackling_fire | 12 | 1.0 | 16.7 | 2.02 | 7.07 | back 1, tap 1 |
| mouse_click | 14 | 1.0 | 14.3 | 1.99 | 8.94 | tap 1, back 1 |
| brushing_teeth | 13 | 1.0 | 15.4 | 1.94 | 3.88 | back 2 |
| insects | 14 | 1.2 | 14.3 | 1.71 | 2.57 | swipe_left 1, long_press 1 |
| hen | 8 | 0.6 | 12.5 | 1.61 | 9.67 | long_press 1 |
| siren | 8 | 0.7 | 12.5 | 1.50 | 9.00 | swipe_up 1 |
| washing_machine | 8 | 0.7 | 12.5 | 1.50 | 1.50 | long_press 1 |
| door_wood_creaks | 10 | 0.7 | 10.0 | 1.42 | 4.26 | swipe_down 1 |
| dog | 10 | 0.7 | 10.0 | 1.39 | 6.93 | swipe_up 1 |
| door_wood_knock | 14 | 0.7 | 7.1 | 1.36 | 5.44 | tap 1 |
| chirping_birds | 9 | 0.8 | 11.1 | 1.33 | 9.33 | swipe_down 1 |
| church_bells | 9 | 0.8 | 11.1 | 1.33 | 6.67 | swipe_up 1 |
| pouring_water | 11 | 0.8 | 9.1 | 1.24 | 4.97 | tap 1 |
| breathing | 15 | 0.9 | 6.7 | 1.07 | 4.27 | back 1 |
| chainsaw | 12 | 1.0 | 8.3 | 1.01 | 3.04 | swipe_up 1 |
| crickets | 13 | 1.1 | 7.7 | 0.92 | 4.62 | back 1 |
| helicopter | 16 | 1.3 | 6.2 | 0.78 | 0.78 | long_press 1 |
| snoring | 19 | 1.5 | 5.3 | 0.65 | 1.94 | swipe_down 1 |
| airplane | 6 | 0.5 | 0.0 | 0.00 | 4.00 |  |
| clapping | 9 | 0.7 | 0.0 | 0.00 | 13.46 |  |
| coughing | 14 | 0.6 | 0.0 | 0.00 | 0.00 |  |
| crow | 11 | 0.9 | 0.0 | 0.00 | 5.59 |  |
| drinking_sipping | 12 | 0.9 | 0.0 | 0.00 | 8.74 |  |
| engine | 12 | 0.9 | 0.0 | 0.00 | 0.00 |  |
| footsteps | 10 | 0.8 | 0.0 | 0.00 | 7.38 |  |
| keyboard_typing | 7 | 0.6 | 0.0 | 0.00 | 8.89 |  |
| laughing | 10 | 0.7 | 0.0 | 0.00 | 20.13 |  |
| pig | 2 | 0.1 | 0.0 | 0.00 | 0.00 |  |
| rain | 7 | 0.6 | 0.0 | 0.00 | 0.00 |  |
| sea_waves | 4 | 0.3 | 0.0 | 0.00 | 0.00 |  |
| sneezing | 9 | 0.5 | 0.0 | 0.00 | 2.08 |  |
| thunderstorm | 10 | 0.8 | 0.0 | 0.00 | 0.00 |  |
| toilet_flush | 9 | 0.7 | 0.0 | 0.00 | 0.00 |  |
| train | 10 | 0.8 | 0.0 | 0.00 | 0.00 |  |
| vacuum_cleaner | 9 | 0.7 | 0.0 | 0.00 | 1.33 |  |

'Sounds like' of all events, cat clips:

| hum | whistle | talking | laughing | coughing | background music | background noise | mouth sound |
|---|---|---|---|---|---|---|---|
| 17 | 17 | 4 | 0 | 0 | 2 | 8 | 1 |

Lines: 1584; strict-parse/label errors: 0; outside generate.py's line space: 467

