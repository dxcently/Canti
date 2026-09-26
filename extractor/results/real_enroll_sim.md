# Enrollment feasibility (fp1 + android Matcher), REAL audio, config `fixed`

```
Feasibility of phone-side personalization: simulated enrollment + the android Matcher, on real audio.

  ./run python eval_real/enroll_sim.py --tag tuned        # -> results/real_enroll_sim.md

Input: results/real_features_<tag>_clips.jsonl (features.py export + live; rows need fp / pitch16, i.e. a run made
with the fp1 code). Only emitted sounds (the ones a phone would receive) take part, and only the clean
condition (no added noise).

The matcher is vox_extract.personal (a mirror of android Personal.kt), re-implemented here with numpy for speed and
checked against it on a sample at start-up. For every store: standardise by the mean / population std of all its
examples (std raised to a per-feature floor where one is given, as the app does), nearest example picks the class,
reject if the distance > (leave-one-out within-class distance, at every class size) x mult. Five examples are run
four ways: no floor, the extractor's `within` scale as the floor, its published floor (0.25 x population) and the
app's shipped floor table.

Scenarios (every draw enrolls ENROLL examples per class, picked at random from that source; R draws each):
  A. per speaker, datasets (speaker-held-out: enrollment and test sounds come from the same speaker, disjoint):
     - MLEnd: a custom class from the speaker's hums, another from their whistles (both in one store).
       Accept = held-out sounds of the same class matched to it; cross = matched to the speaker's other class.
     - Deeply Nonverbal: the speaker's tongue clicks (gesture click) and lip pops (gesture pop), plus, as a
       custom class, their lip smacks. Own negatives = that speaker's coughs, laughs, sighs ... (other classes).
     - ESC-50 cat: an ignore class from one recording (src_file) with enough meows.
  B. the user's live recordings: custom "meow" (105946), ignore "yell" (110107), gesture click (the click
     sessions), custom "whistle"; the user's hums are NOT enrolled and must stay unmatched (a hum captured by a
     custom class would lose its gesture).
  False accepts of every store on the NEGATIVE sets (other people): MUSAN speech / music / noise, Nonspeech7k,
  ESC-50 (all classes), Deeply Nonverbal negatives: matched sounds per minute of audio (clean, emitted only).
  Also reported: other people's hums / whistles / sung notes (MLEnd, QBSH) captured by a custom class.
```

Emitted clean sounds with an fp: 148434. Negative pools (test split, other people): esc50 4722 sounds / 110 min, others' hum 29470 sounds, others' whistle 14227 sounds, musan 38328 sounds / 1027 min, nonspeech7k 17348 sounds / 304 min, nonverbal 1087 sounds / 20 min, others' sung 938 sounds.

## 5 enrollment examples per class, no std floor  (baseline)

Stores: MLEnd 60 speakers, Deeply Nonverbal 15 speakers, ESC-50 cat 7 recordings, live 30 draws; 3 draws per speaker. Live classes: live:meow (7 sounds), live:yell (7 sounds), click (68 sounds), live:whistle (40 sounds); live hums (not enrolled) 46.

| enrolled class | x mult | accept (held-out, same class) | captured by another enrolled class | own non-enrolled sounds captured |
|---|---|---|---|---|
| esc50:cat | 1.3 | 71.3 % (62/87) | 0.0 % | - |
| esc50:cat | 1.4 | 73.6 % (64/87) | 0.0 % | - |
| esc50:cat | 1.5 | 74.7 % (65/87) | 0.0 % | - |
| live:click | 1.3 | 89.4 % (1690/1890) | 0.4 % | 1.3 % (18/1380) |
| live:click | 1.4 | 91.1 % (1722/1890) | 0.4 % | 1.4 % (19/1380) |
| live:click | 1.5 | 92.4 % (1746/1890) | 0.4 % | 1.7 % (23/1380) |
| live:meow | 1.3 | 93.3 % (56/60) | 0.0 % | 3.8 % (52/1380) |
| live:meow | 1.4 | 93.3 % (56/60) | 0.0 % | 7.2 % (100/1380) |
| live:meow | 1.5 | 98.3 % (59/60) | 0.0 % | 11.3 % (156/1380) |
| live:whistle | 1.3 | 81.6 % (857/1050) | 5.0 % | 0.1 % (1/1380) |
| live:whistle | 1.4 | 82.7 % (868/1050) | 5.4 % | 0.1 % (1/1380) |
| live:whistle | 1.5 | 83.2 % (874/1050) | 6.3 % | 0.1 % (1/1380) |
| live:yell | 1.3 | 61.7 % (37/60) | 10.0 % | 7.6 % (105/1380) |
| live:yell | 1.4 | 63.3 % (38/60) | 10.0 % | 7.8 % (107/1380) |
| live:yell | 1.5 | 70.0 % (42/60) | 11.7 % | 8.0 % (110/1380) |
| mlend:hum | 1.3 | 80.8 % (19724/24423) | 2.3 % | - |
| mlend:hum | 1.4 | 82.1 % (20048/24423) | 2.4 % | - |
| mlend:hum | 1.5 | 83.1 % (20306/24423) | 2.5 % | - |
| mlend:whistle | 1.3 | 83.3 % (24474/29382) | 3.1 % | - |
| mlend:whistle | 1.4 | 84.7 % (24890/29382) | 3.2 % | - |
| mlend:whistle | 1.5 | 85.8 % (25212/29382) | 3.4 % | - |
| nv:click | 1.3 | 82.9 % (87/105) | 0.0 % | 0.0 % (0/30) |
| nv:click | 1.4 | 86.7 % (91/105) | 0.0 % | 0.0 % (0/30) |
| nv:click | 1.5 | 88.6 % (93/105) | 0.0 % | 0.0 % (0/30) |
| nv:pop | 1.3 | 91.7 % (11/12) | 0.0 % | 0.0 % (0/15) |
| nv:pop | 1.4 | 91.7 % (11/12) | 0.0 % | 0.0 % (0/15) |
| nv:pop | 1.5 | 100.0 % (12/12) | 0.0 % | 0.0 % (0/15) |
| nv:smack | 1.3 | 76.9 % (30/39) | 0.0 % | 11.1 % (2/18) |
| nv:smack | 1.4 | 79.5 % (31/39) | 0.0 % | 11.1 % (2/18) |
| nv:smack | 1.5 | 79.5 % (31/39) | 0.0 % | 11.1 % (2/18) |

"own non-enrolled sounds": Deeply Nonverbal = the same speaker's coughs, laughs, sighs, ...; live = the user's hums (gestures), which must stay unmatched.

### False accepts on other people's sounds, per store (mean over stores)

Matched sounds per minute of negative audio; in brackets the share of stores with at least one false accept on that set. `others'` columns: sounds per 100 of other people's hums / whistles / sung notes captured (MLEnd and QBSH test split; not for the MLEnd stores, whose own speaker is in that pool).

| enrolled class | x mult | esc50 /min | musan /min | nonspeech7k /min | nonverbal /min | others' hum /100 | others' whistle /100 | others' sung /100 |
|---|---|---|---|---|---|---|---|---|
| esc50:cat | 1.3 | - | 9.072 (100.0 %) | 12.983 (100.0 %) | 10.009 (100.0 %) | 24.05 | 30.64 | 17.54 |
| esc50:cat | 1.4 | - | 10.330 (100.0 %) | 14.851 (100.0 %) | 11.662 (100.0 %) | 28.59 | 33.86 | 20.99 |
| esc50:cat | 1.5 | - | 11.612 (100.0 %) | 16.691 (100.0 %) | 13.203 (100.0 %) | 33.75 | 37.09 | 24.52 |
| live:click | 1.3 | 6.776 (100.0 %) | 1.620 (100.0 %) | 4.113 (100.0 %) | 5.440 (100.0 %) | 2.07 | 1.34 | 0.64 |
| live:click | 1.4 | 7.569 (100.0 %) | 1.803 (100.0 %) | 4.574 (100.0 %) | 6.301 (100.0 %) | 2.27 | 1.58 | 0.80 |
| live:click | 1.5 | 8.336 (100.0 %) | 1.967 (100.0 %) | 5.020 (100.0 %) | 7.112 (100.0 %) | 2.47 | 1.81 | 0.94 |
| live:meow | 1.3 | 0.081 (93.3 %) | 0.280 (96.7 %) | 0.338 (96.7 %) | 0.080 (46.7 %) | 4.36 | 0.01 | 0.59 |
| live:meow | 1.4 | 0.139 (93.3 %) | 0.455 (96.7 %) | 0.493 (96.7 %) | 0.168 (70.0 %) | 6.53 | 0.02 | 1.32 |
| live:meow | 1.5 | 0.220 (93.3 %) | 0.686 (100.0 %) | 0.683 (100.0 %) | 0.277 (80.0 %) | 9.22 | 0.04 | 2.60 |
| live:whistle | 1.3 | 3.125 (100.0 %) | 1.425 (100.0 %) | 3.518 (100.0 %) | 3.520 (100.0 %) | 1.55 | 71.63 | 0.84 |
| live:whistle | 1.4 | 3.356 (100.0 %) | 1.488 (100.0 %) | 3.827 (100.0 %) | 3.839 (100.0 %) | 1.65 | 74.52 | 0.92 |
| live:whistle | 1.5 | 3.573 (100.0 %) | 1.540 (100.0 %) | 4.101 (100.0 %) | 4.056 (100.0 %) | 1.74 | 76.88 | 0.96 |
| live:yell | 1.3 | 6.560 (100.0 %) | 3.986 (100.0 %) | 11.509 (100.0 %) | 5.555 (100.0 %) | 5.98 | 2.48 | 7.05 |
| live:yell | 1.4 | 7.044 (100.0 %) | 4.405 (100.0 %) | 12.370 (100.0 %) | 6.326 (100.0 %) | 6.32 | 2.94 | 7.67 |
| live:yell | 1.5 | 7.416 (100.0 %) | 4.752 (100.0 %) | 13.072 (100.0 %) | 6.910 (100.0 %) | 6.58 | 3.32 | 8.18 |
| mlend:hum | 1.3 | 6.833 (98.9 %) | 8.633 (100.0 %) | 11.242 (100.0 %) | 9.807 (100.0 %) | - | - | - |
| mlend:hum | 1.4 | 7.242 (98.9 %) | 9.155 (100.0 %) | 11.955 (100.0 %) | 10.430 (100.0 %) | - | - | - |
| mlend:hum | 1.5 | 7.631 (98.9 %) | 9.642 (100.0 %) | 12.620 (100.0 %) | 11.020 (100.0 %) | - | - | - |
| mlend:whistle | 1.3 | 3.089 (86.1 %) | 1.767 (99.4 %) | 3.248 (96.1 %) | 3.268 (86.7 %) | - | - | - |
| mlend:whistle | 1.4 | 3.322 (88.9 %) | 1.896 (99.4 %) | 3.512 (96.1 %) | 3.541 (88.9 %) | - | - | - |
| mlend:whistle | 1.5 | 3.533 (91.7 %) | 2.014 (99.4 %) | 3.754 (98.3 %) | 3.798 (91.1 %) | - | - | - |
| nv:click | 1.3 | 0.313 (70.4 %) | 0.080 (88.9 %) | 0.131 (59.3 %) | - | 0.07 | 0.03 | 0.00 |
| nv:click | 1.4 | 0.417 (81.5 %) | 0.106 (96.3 %) | 0.181 (63.0 %) | - | 0.11 | 0.05 | 0.00 |
| nv:click | 1.5 | 0.543 (88.9 %) | 0.135 (100.0 %) | 0.243 (74.1 %) | - | 0.14 | 0.06 | 0.00 |
| nv:pop | 1.3 | 6.880 (100.0 %) | 5.077 (100.0 %) | 4.574 (100.0 %) | - | 3.17 | 1.81 | 4.16 |
| nv:pop | 1.4 | 7.485 (100.0 %) | 5.257 (100.0 %) | 5.007 (100.0 %) | - | 3.39 | 1.90 | 4.34 |
| nv:pop | 1.5 | 8.084 (100.0 %) | 5.411 (100.0 %) | 5.416 (100.0 %) | - | 3.58 | 2.00 | 4.76 |
| nv:smack | 1.3 | 12.427 (93.3 %) | 8.249 (100.0 %) | 11.216 (93.3 %) | - | 5.80 | 2.25 | 3.97 |
| nv:smack | 1.4 | 13.510 (93.3 %) | 9.041 (100.0 %) | 12.571 (93.3 %) | - | 8.06 | 2.52 | 5.25 |
| nv:smack | 1.5 | 14.509 (93.3 %) | 9.771 (100.0 %) | 13.910 (93.3 %) | - | 11.15 | 2.78 | 8.02 |

## 5 enrollment examples per class, std floor = the extractor's `within` scale (results/fp1_scales.json `within`)

Stores: MLEnd 60 speakers, Deeply Nonverbal 15 speakers, ESC-50 cat 7 recordings, live 30 draws; 3 draws per speaker. Live classes: live:meow (7 sounds), live:yell (7 sounds), click (68 sounds), live:whistle (40 sounds); live hums (not enrolled) 46.

| enrolled class | x mult | accept (held-out, same class) | captured by another enrolled class | own non-enrolled sounds captured |
|---|---|---|---|---|
| esc50:cat | 1.3 | 81.6 % (71/87) | 0.0 % | - |
| esc50:cat | 1.4 | 85.1 % (74/87) | 0.0 % | - |
| esc50:cat | 1.5 | 86.2 % (75/87) | 0.0 % | - |
| live:click | 1.3 | 90.5 % (1711/1890) | 0.7 % | 1.5 % (21/1380) |
| live:click | 1.4 | 92.3 % (1744/1890) | 0.7 % | 1.8 % (25/1380) |
| live:click | 1.5 | 93.1 % (1759/1890) | 0.7 % | 1.8 % (25/1380) |
| live:meow | 1.3 | 96.7 % (58/60) | 0.0 % | 3.7 % (51/1380) |
| live:meow | 1.4 | 96.7 % (58/60) | 0.0 % | 5.9 % (82/1380) |
| live:meow | 1.5 | 100.0 % (60/60) | 0.0 % | 9.6 % (132/1380) |
| live:whistle | 1.3 | 86.9 % (912/1050) | 3.0 % | 0.3 % (4/1380) |
| live:whistle | 1.4 | 87.6 % (920/1050) | 3.3 % | 0.4 % (5/1380) |
| live:whistle | 1.5 | 88.0 % (924/1050) | 4.0 % | 0.4 % (6/1380) |
| live:yell | 1.3 | 66.7 % (40/60) | 1.7 % | 6.2 % (85/1380) |
| live:yell | 1.4 | 68.3 % (41/60) | 1.7 % | 6.6 % (91/1380) |
| live:yell | 1.5 | 73.3 % (44/60) | 1.7 % | 6.7 % (92/1380) |
| mlend:hum | 1.3 | 84.7 % (21373/25242) | 3.1 % | - |
| mlend:hum | 1.4 | 86.1 % (21734/25242) | 3.3 % | - |
| mlend:hum | 1.5 | 87.1 % (21975/25242) | 3.4 % | - |
| mlend:whistle | 1.3 | 88.5 % (26375/29814) | 2.3 % | - |
| mlend:whistle | 1.4 | 89.6 % (26702/29814) | 2.4 % | - |
| mlend:whistle | 1.5 | 90.3 % (26936/29814) | 2.5 % | - |
| nv:click | 1.3 | 82.9 % (87/105) | 0.0 % | 0.0 % (0/30) |
| nv:click | 1.4 | 84.8 % (89/105) | 0.0 % | 0.0 % (0/30) |
| nv:click | 1.5 | 86.7 % (91/105) | 0.0 % | 0.0 % (0/30) |
| nv:pop | 1.3 | 100.0 % (12/12) | 0.0 % | 0.0 % (0/15) |
| nv:pop | 1.4 | 100.0 % (12/12) | 0.0 % | 20.0 % (3/15) |
| nv:pop | 1.5 | 100.0 % (12/12) | 0.0 % | 26.7 % (4/15) |
| nv:smack | 1.3 | 92.3 % (36/39) | 0.0 % | 22.2 % (4/18) |
| nv:smack | 1.4 | 92.3 % (36/39) | 0.0 % | 22.2 % (4/18) |
| nv:smack | 1.5 | 92.3 % (36/39) | 0.0 % | 22.2 % (4/18) |

"own non-enrolled sounds": Deeply Nonverbal = the same speaker's coughs, laughs, sighs, ...; live = the user's hums (gestures), which must stay unmatched.

### False accepts on other people's sounds, per store (mean over stores)

Matched sounds per minute of negative audio; in brackets the share of stores with at least one false accept on that set. `others'` columns: sounds per 100 of other people's hums / whistles / sung notes captured (MLEnd and QBSH test split; not for the MLEnd stores, whose own speaker is in that pool).

| enrolled class | x mult | esc50 /min | musan /min | nonspeech7k /min | nonverbal /min | others' hum /100 | others' whistle /100 | others' sung /100 |
|---|---|---|---|---|---|---|---|---|
| esc50:cat | 1.3 | - | 16.924 (100.0 %) | 28.571 (100.0 %) | 21.883 (100.0 %) | 51.69 | 50.80 | 37.08 |
| esc50:cat | 1.4 | - | 18.834 (100.0 %) | 31.517 (100.0 %) | 24.592 (100.0 %) | 59.00 | 57.00 | 44.43 |
| esc50:cat | 1.5 | - | 20.556 (100.0 %) | 34.295 (100.0 %) | 27.047 (100.0 %) | 65.73 | 62.38 | 51.65 |
| live:click | 1.3 | 7.538 (100.0 %) | 1.790 (100.0 %) | 4.702 (100.0 %) | 5.927 (100.0 %) | 2.38 | 1.38 | 0.89 |
| live:click | 1.4 | 8.452 (100.0 %) | 2.005 (100.0 %) | 5.246 (100.0 %) | 6.916 (100.0 %) | 2.60 | 1.61 | 1.06 |
| live:click | 1.5 | 9.272 (100.0 %) | 2.192 (100.0 %) | 5.708 (100.0 %) | 7.775 (100.0 %) | 2.80 | 1.83 | 1.23 |
| live:meow | 1.3 | 0.059 (96.7 %) | 0.195 (96.7 %) | 0.278 (96.7 %) | 0.029 (26.7 %) | 3.35 | 0.01 | 0.21 |
| live:meow | 1.4 | 0.103 (96.7 %) | 0.321 (100.0 %) | 0.412 (100.0 %) | 0.088 (63.3 %) | 5.02 | 0.01 | 0.48 |
| live:meow | 1.5 | 0.166 (96.7 %) | 0.499 (100.0 %) | 0.579 (100.0 %) | 0.204 (83.3 %) | 7.14 | 0.02 | 1.06 |
| live:whistle | 1.3 | 2.471 (100.0 %) | 0.812 (100.0 %) | 2.631 (100.0 %) | 2.796 (100.0 %) | 1.09 | 72.15 | 0.39 |
| live:whistle | 1.4 | 2.676 (100.0 %) | 0.876 (100.0 %) | 2.912 (100.0 %) | 3.114 (100.0 %) | 1.17 | 74.86 | 0.44 |
| live:whistle | 1.5 | 2.868 (100.0 %) | 0.932 (100.0 %) | 3.154 (100.0 %) | 3.404 (100.0 %) | 1.24 | 77.09 | 0.48 |
| live:yell | 1.3 | 8.162 (100.0 %) | 4.366 (100.0 %) | 14.448 (100.0 %) | 7.476 (100.0 %) | 5.60 | 3.83 | 7.94 |
| live:yell | 1.4 | 8.721 (100.0 %) | 4.871 (100.0 %) | 15.483 (100.0 %) | 8.416 (100.0 %) | 5.97 | 4.43 | 8.61 |
| live:yell | 1.5 | 9.157 (100.0 %) | 5.313 (100.0 %) | 16.306 (100.0 %) | 9.172 (100.0 %) | 6.26 | 4.91 | 9.33 |
| mlend:hum | 1.3 | 6.873 (100.0 %) | 10.417 (100.0 %) | 13.065 (100.0 %) | 10.364 (100.0 %) | - | - | - |
| mlend:hum | 1.4 | 7.440 (100.0 %) | 11.324 (100.0 %) | 14.229 (100.0 %) | 11.230 (100.0 %) | - | - | - |
| mlend:hum | 1.5 | 7.999 (100.0 %) | 12.195 (100.0 %) | 15.345 (100.0 %) | 12.010 (100.0 %) | - | - | - |
| mlend:whistle | 1.3 | 5.590 (100.0 %) | 3.308 (100.0 %) | 6.956 (100.0 %) | 5.948 (90.0 %) | - | - | - |
| mlend:whistle | 1.4 | 6.101 (100.0 %) | 3.512 (100.0 %) | 7.589 (100.0 %) | 6.506 (93.3 %) | - | - | - |
| mlend:whistle | 1.5 | 6.586 (100.0 %) | 3.714 (100.0 %) | 8.164 (100.0 %) | 7.012 (95.0 %) | - | - | - |
| nv:click | 1.3 | 0.896 (88.9 %) | 0.207 (96.3 %) | 0.454 (77.8 %) | - | 0.23 | 0.10 | 0.00 |
| nv:click | 1.4 | 1.252 (96.3 %) | 0.280 (100.0 %) | 0.662 (92.6 %) | - | 0.34 | 0.15 | 0.00 |
| nv:click | 1.5 | 1.666 (100.0 %) | 0.364 (100.0 %) | 0.923 (92.6 %) | - | 0.47 | 0.21 | 0.00 |
| nv:pop | 1.3 | 17.944 (100.0 %) | 13.934 (100.0 %) | 21.642 (100.0 %) | - | 6.38 | 3.82 | 6.68 |
| nv:pop | 1.4 | 19.863 (100.0 %) | 14.926 (100.0 %) | 24.708 (100.0 %) | - | 7.32 | 4.23 | 8.64 |
| nv:pop | 1.5 | 21.779 (100.0 %) | 15.941 (100.0 %) | 27.295 (100.0 %) | - | 8.57 | 4.64 | 10.77 |
| nv:smack | 1.3 | 20.035 (100.0 %) | 12.546 (100.0 %) | 19.703 (100.0 %) | - | 12.66 | 10.18 | 10.77 |
| nv:smack | 1.4 | 21.240 (100.0 %) | 13.468 (100.0 %) | 21.566 (100.0 %) | - | 14.60 | 12.51 | 13.89 |
| nv:smack | 1.5 | 22.366 (100.0 %) | 14.396 (100.0 %) | 23.218 (100.0 %) | - | 16.61 | 15.15 | 17.47 |

## 5 enrollment examples per class, std floor = the extractor's published floor, 0.25 x population (results/fp1_scales.json `floor`)

Stores: MLEnd 60 speakers, Deeply Nonverbal 15 speakers, ESC-50 cat 7 recordings, live 30 draws; 3 draws per speaker. Live classes: live:meow (7 sounds), live:yell (7 sounds), click (68 sounds), live:whistle (40 sounds); live hums (not enrolled) 46.

| enrolled class | x mult | accept (held-out, same class) | captured by another enrolled class | own non-enrolled sounds captured |
|---|---|---|---|---|
| esc50:cat | 1.3 | 77.0 % (67/87) | 0.0 % | - |
| esc50:cat | 1.4 | 77.0 % (67/87) | 0.0 % | - |
| esc50:cat | 1.5 | 79.3 % (69/87) | 0.0 % | - |
| live:click | 1.3 | 92.3 % (1745/1890) | 0.7 % | 0.8 % (11/1380) |
| live:click | 1.4 | 93.9 % (1775/1890) | 0.7 % | 1.2 % (16/1380) |
| live:click | 1.5 | 94.9 % (1793/1890) | 0.7 % | 1.4 % (19/1380) |
| live:meow | 1.3 | 100.0 % (60/60) | 0.0 % | 5.6 % (77/1380) |
| live:meow | 1.4 | 100.0 % (60/60) | 0.0 % | 8.8 % (121/1380) |
| live:meow | 1.5 | 100.0 % (60/60) | 0.0 % | 13.4 % (185/1380) |
| live:whistle | 1.3 | 84.0 % (882/1050) | 3.3 % | 0.0 % (0/1380) |
| live:whistle | 1.4 | 84.8 % (890/1050) | 4.4 % | 0.1 % (1/1380) |
| live:whistle | 1.5 | 85.0 % (892/1050) | 5.3 % | 0.1 % (1/1380) |
| live:yell | 1.3 | 70.0 % (42/60) | 6.7 % | 7.3 % (101/1380) |
| live:yell | 1.4 | 71.7 % (43/60) | 8.3 % | 7.4 % (102/1380) |
| live:yell | 1.5 | 80.0 % (48/60) | 8.3 % | 7.8 % (107/1380) |
| mlend:hum | 1.3 | 83.7 % (20778/24810) | 2.6 % | - |
| mlend:hum | 1.4 | 85.2 % (21145/24810) | 2.7 % | - |
| mlend:hum | 1.5 | 86.4 % (21444/24810) | 2.8 % | - |
| mlend:whistle | 1.3 | 84.4 % (26025/30828) | 3.4 % | - |
| mlend:whistle | 1.4 | 85.8 % (26465/30828) | 3.6 % | - |
| mlend:whistle | 1.5 | 87.0 % (26822/30828) | 3.7 % | - |
| nv:click | 1.3 | 81.0 % (85/105) | 0.0 % | 0.0 % (0/30) |
| nv:click | 1.4 | 83.8 % (88/105) | 0.0 % | 0.0 % (0/30) |
| nv:click | 1.5 | 89.5 % (94/105) | 0.0 % | 0.0 % (0/30) |
| nv:pop | 1.3 | 83.3 % (10/12) | 0.0 % | 0.0 % (0/15) |
| nv:pop | 1.4 | 83.3 % (10/12) | 0.0 % | 0.0 % (0/15) |
| nv:pop | 1.5 | 83.3 % (10/12) | 0.0 % | 0.0 % (0/15) |
| nv:smack | 1.3 | 79.5 % (31/39) | 0.0 % | 5.6 % (1/18) |
| nv:smack | 1.4 | 79.5 % (31/39) | 0.0 % | 11.1 % (2/18) |
| nv:smack | 1.5 | 84.6 % (33/39) | 0.0 % | 11.1 % (2/18) |

"own non-enrolled sounds": Deeply Nonverbal = the same speaker's coughs, laughs, sighs, ...; live = the user's hums (gestures), which must stay unmatched.

### False accepts on other people's sounds, per store (mean over stores)

Matched sounds per minute of negative audio; in brackets the share of stores with at least one false accept on that set. `others'` columns: sounds per 100 of other people's hums / whistles / sung notes captured (MLEnd and QBSH test split; not for the MLEnd stores, whose own speaker is in that pool).

| enrolled class | x mult | esc50 /min | musan /min | nonspeech7k /min | nonverbal /min | others' hum /100 | others' whistle /100 | others' sung /100 |
|---|---|---|---|---|---|---|---|---|
| esc50:cat | 1.3 | - | 13.555 (100.0 %) | 19.817 (100.0 %) | 14.793 (100.0 %) | 40.40 | 52.32 | 29.57 |
| esc50:cat | 1.4 | - | 15.374 (100.0 %) | 22.545 (100.0 %) | 17.073 (100.0 %) | 47.66 | 59.20 | 36.94 |
| esc50:cat | 1.5 | - | 17.069 (100.0 %) | 25.143 (100.0 %) | 19.407 (100.0 %) | 54.43 | 64.86 | 44.30 |
| live:click | 1.3 | 6.678 (100.0 %) | 1.589 (100.0 %) | 4.039 (100.0 %) | 4.894 (100.0 %) | 2.25 | 1.17 | 0.61 |
| live:click | 1.4 | 7.698 (100.0 %) | 1.826 (100.0 %) | 4.633 (100.0 %) | 5.880 (100.0 %) | 2.51 | 1.40 | 0.83 |
| live:click | 1.5 | 8.654 (100.0 %) | 2.048 (100.0 %) | 5.215 (100.0 %) | 6.677 (100.0 %) | 2.74 | 1.64 | 1.11 |
| live:meow | 1.3 | 0.095 (100.0 %) | 0.312 (100.0 %) | 0.376 (100.0 %) | 0.085 (60.0 %) | 5.15 | 0.01 | 0.47 |
| live:meow | 1.4 | 0.157 (100.0 %) | 0.505 (100.0 %) | 0.545 (100.0 %) | 0.178 (76.7 %) | 7.61 | 0.02 | 1.14 |
| live:meow | 1.5 | 0.248 (100.0 %) | 0.760 (100.0 %) | 0.756 (100.0 %) | 0.300 (93.3 %) | 10.64 | 0.04 | 2.52 |
| live:whistle | 1.3 | 3.073 (100.0 %) | 1.253 (100.0 %) | 3.326 (100.0 %) | 3.251 (100.0 %) | 1.57 | 74.88 | 0.81 |
| live:whistle | 1.4 | 3.312 (100.0 %) | 1.309 (100.0 %) | 3.642 (100.0 %) | 3.577 (100.0 %) | 1.66 | 77.22 | 0.86 |
| live:whistle | 1.5 | 3.506 (100.0 %) | 1.355 (100.0 %) | 3.916 (100.0 %) | 3.887 (100.0 %) | 1.75 | 79.03 | 0.91 |
| live:yell | 1.3 | 7.005 (100.0 %) | 4.041 (100.0 %) | 12.817 (100.0 %) | 6.304 (100.0 %) | 4.72 | 2.50 | 6.63 |
| live:yell | 1.4 | 7.543 (100.0 %) | 4.510 (100.0 %) | 13.802 (100.0 %) | 7.173 (100.0 %) | 5.06 | 3.03 | 7.31 |
| live:yell | 1.5 | 7.956 (100.0 %) | 4.906 (100.0 %) | 14.603 (100.0 %) | 7.909 (100.0 %) | 5.33 | 3.46 | 7.82 |
| mlend:hum | 1.3 | 7.233 (100.0 %) | 9.813 (100.0 %) | 12.656 (100.0 %) | 10.286 (100.0 %) | - | - | - |
| mlend:hum | 1.4 | 7.858 (100.0 %) | 10.710 (100.0 %) | 13.829 (100.0 %) | 11.240 (100.0 %) | - | - | - |
| mlend:hum | 1.5 | 8.445 (100.0 %) | 11.541 (100.0 %) | 14.953 (100.0 %) | 12.151 (100.0 %) | - | - | - |
| mlend:whistle | 1.3 | 4.223 (98.3 %) | 2.404 (99.4 %) | 4.285 (98.9 %) | 4.266 (86.7 %) | - | - | - |
| mlend:whistle | 1.4 | 4.554 (98.9 %) | 2.566 (99.4 %) | 4.694 (98.9 %) | 4.652 (90.6 %) | - | - | - |
| mlend:whistle | 1.5 | 4.857 (99.4 %) | 2.715 (99.4 %) | 5.082 (98.9 %) | 5.014 (91.7 %) | - | - | - |
| nv:click | 1.3 | 0.479 (77.8 %) | 0.126 (88.9 %) | 0.221 (70.4 %) | - | 0.13 | 0.06 | 0.00 |
| nv:click | 1.4 | 0.647 (81.5 %) | 0.162 (96.3 %) | 0.314 (74.1 %) | - | 0.18 | 0.09 | 0.00 |
| nv:click | 1.5 | 0.884 (88.9 %) | 0.208 (100.0 %) | 0.445 (77.8 %) | - | 0.24 | 0.13 | 0.00 |
| nv:pop | 1.3 | 8.674 (100.0 %) | 9.068 (100.0 %) | 10.417 (100.0 %) | - | 3.56 | 2.28 | 3.13 |
| nv:pop | 1.4 | 9.772 (100.0 %) | 10.001 (100.0 %) | 12.408 (100.0 %) | - | 4.20 | 2.55 | 4.23 |
| nv:pop | 1.5 | 10.992 (100.0 %) | 10.950 (100.0 %) | 14.207 (100.0 %) | - | 5.08 | 2.91 | 4.94 |
| nv:smack | 1.3 | 16.064 (93.3 %) | 10.149 (100.0 %) | 14.427 (100.0 %) | - | 9.40 | 7.62 | 7.51 |
| nv:smack | 1.4 | 17.456 (93.3 %) | 10.997 (100.0 %) | 15.984 (100.0 %) | - | 11.51 | 9.20 | 10.43 |
| nv:smack | 1.5 | 18.653 (93.3 %) | 11.786 (100.0 %) | 17.449 (100.0 %) | - | 14.52 | 10.98 | 13.26 |

## 5 enrollment examples per class, std floor = the app's table (android assets/fp_floors.json, provisional=True)

Stores: MLEnd 60 speakers, Deeply Nonverbal 15 speakers, ESC-50 cat 7 recordings, live 30 draws; 3 draws per speaker. Live classes: live:meow (7 sounds), live:yell (7 sounds), click (68 sounds), live:whistle (40 sounds); live hums (not enrolled) 46.

| enrolled class | x mult | accept (held-out, same class) | captured by another enrolled class | own non-enrolled sounds captured |
|---|---|---|---|---|
| esc50:cat | 1.3 | 75.9 % (66/87) | 0.0 % | - |
| esc50:cat | 1.4 | 75.9 % (66/87) | 0.0 % | - |
| esc50:cat | 1.5 | 81.6 % (71/87) | 0.0 % | - |
| live:click | 1.3 | 91.6 % (1732/1890) | 0.6 % | 1.2 % (16/1380) |
| live:click | 1.4 | 93.4 % (1765/1890) | 0.6 % | 1.4 % (19/1380) |
| live:click | 1.5 | 94.1 % (1778/1890) | 0.6 % | 1.5 % (21/1380) |
| live:meow | 1.3 | 93.3 % (56/60) | 0.0 % | 2.5 % (35/1380) |
| live:meow | 1.4 | 96.7 % (58/60) | 0.0 % | 4.9 % (67/1380) |
| live:meow | 1.5 | 98.3 % (59/60) | 0.0 % | 8.3 % (115/1380) |
| live:whistle | 1.3 | 82.7 % (868/1050) | 2.2 % | 0.0 % (0/1380) |
| live:whistle | 1.4 | 83.5 % (877/1050) | 2.5 % | 0.0 % (0/1380) |
| live:whistle | 1.5 | 84.7 % (889/1050) | 3.0 % | 0.0 % (0/1380) |
| live:yell | 1.3 | 56.7 % (34/60) | 3.3 % | 7.5 % (103/1380) |
| live:yell | 1.4 | 61.7 % (37/60) | 3.3 % | 7.8 % (108/1380) |
| live:yell | 1.5 | 68.3 % (41/60) | 3.3 % | 8.0 % (111/1380) |
| mlend:hum | 1.3 | 86.4 % (21051/24360) | 2.2 % | - |
| mlend:hum | 1.4 | 87.7 % (21371/24360) | 2.2 % | - |
| mlend:hum | 1.5 | 88.8 % (21633/24360) | 2.3 % | - |
| mlend:whistle | 1.3 | 86.5 % (25635/29625) | 3.6 % | - |
| mlend:whistle | 1.4 | 87.7 % (25987/29625) | 3.8 % | - |
| mlend:whistle | 1.5 | 88.7 % (26268/29625) | 3.9 % | - |
| nv:click | 1.3 | 84.8 % (89/105) | 0.0 % | 0.0 % (0/30) |
| nv:click | 1.4 | 89.5 % (94/105) | 0.0 % | 0.0 % (0/30) |
| nv:click | 1.5 | 91.4 % (96/105) | 0.0 % | 0.0 % (0/30) |
| nv:pop | 1.3 | 66.7 % (8/12) | 0.0 % | 0.0 % (0/15) |
| nv:pop | 1.4 | 66.7 % (8/12) | 0.0 % | 0.0 % (0/15) |
| nv:pop | 1.5 | 66.7 % (8/12) | 0.0 % | 0.0 % (0/15) |
| nv:smack | 1.3 | 71.8 % (28/39) | 0.0 % | 11.1 % (2/18) |
| nv:smack | 1.4 | 74.4 % (29/39) | 0.0 % | 11.1 % (2/18) |
| nv:smack | 1.5 | 79.5 % (31/39) | 0.0 % | 22.2 % (4/18) |

"own non-enrolled sounds": Deeply Nonverbal = the same speaker's coughs, laughs, sighs, ...; live = the user's hums (gestures), which must stay unmatched.

### False accepts on other people's sounds, per store (mean over stores)

Matched sounds per minute of negative audio; in brackets the share of stores with at least one false accept on that set. `others'` columns: sounds per 100 of other people's hums / whistles / sung notes captured (MLEnd and QBSH test split; not for the MLEnd stores, whose own speaker is in that pool).

| enrolled class | x mult | esc50 /min | musan /min | nonspeech7k /min | nonverbal /min | others' hum /100 | others' whistle /100 | others' sung /100 |
|---|---|---|---|---|---|---|---|---|
| esc50:cat | 1.3 | - | 12.400 (100.0 %) | 19.778 (100.0 %) | 14.336 (100.0 %) | 31.10 | 37.09 | 19.01 |
| esc50:cat | 1.4 | - | 14.136 (100.0 %) | 22.614 (100.0 %) | 16.479 (100.0 %) | 38.20 | 41.42 | 24.05 |
| esc50:cat | 1.5 | - | 15.789 (100.0 %) | 25.275 (100.0 %) | 18.516 (100.0 %) | 46.00 | 45.56 | 30.37 |
| live:click | 1.3 | 7.542 (100.0 %) | 1.759 (100.0 %) | 4.702 (100.0 %) | 5.848 (100.0 %) | 2.41 | 1.34 | 0.66 |
| live:click | 1.4 | 8.589 (100.0 %) | 1.991 (100.0 %) | 5.326 (100.0 %) | 6.807 (100.0 %) | 2.66 | 1.62 | 0.85 |
| live:click | 1.5 | 9.537 (100.0 %) | 2.198 (100.0 %) | 5.930 (100.0 %) | 7.737 (100.0 %) | 2.87 | 1.86 | 0.96 |
| live:meow | 1.3 | 0.054 (93.3 %) | 0.194 (96.7 %) | 0.269 (100.0 %) | 0.034 (40.0 %) | 3.38 | 0.01 | 0.21 |
| live:meow | 1.4 | 0.099 (93.3 %) | 0.326 (100.0 %) | 0.402 (100.0 %) | 0.086 (63.3 %) | 5.15 | 0.01 | 0.53 |
| live:meow | 1.5 | 0.166 (93.3 %) | 0.510 (100.0 %) | 0.557 (100.0 %) | 0.193 (83.3 %) | 7.39 | 0.02 | 1.16 |
| live:whistle | 1.3 | 3.501 (100.0 %) | 1.543 (100.0 %) | 3.883 (100.0 %) | 4.247 (93.3 %) | 1.60 | 70.94 | 0.98 |
| live:whistle | 1.4 | 3.713 (100.0 %) | 1.614 (100.0 %) | 4.203 (100.0 %) | 4.659 (96.7 %) | 1.72 | 73.24 | 1.15 |
| live:whistle | 1.5 | 3.916 (100.0 %) | 1.677 (100.0 %) | 4.509 (100.0 %) | 5.066 (96.7 %) | 1.84 | 75.11 | 1.29 |
| live:yell | 1.3 | 6.754 (100.0 %) | 4.052 (100.0 %) | 12.215 (100.0 %) | 6.011 (100.0 %) | 6.06 | 2.98 | 6.89 |
| live:yell | 1.4 | 7.296 (100.0 %) | 4.551 (100.0 %) | 13.177 (100.0 %) | 6.895 (100.0 %) | 6.49 | 3.47 | 7.52 |
| live:yell | 1.5 | 7.717 (100.0 %) | 4.963 (100.0 %) | 13.961 (100.0 %) | 7.494 (100.0 %) | 6.82 | 3.92 | 8.08 |
| mlend:hum | 1.3 | 8.439 (99.4 %) | 11.956 (100.0 %) | 15.659 (100.0 %) | 12.099 (100.0 %) | - | - | - |
| mlend:hum | 1.4 | 9.131 (99.4 %) | 12.938 (100.0 %) | 16.961 (100.0 %) | 13.086 (100.0 %) | - | - | - |
| mlend:hum | 1.5 | 9.795 (99.4 %) | 13.847 (100.0 %) | 18.172 (100.0 %) | 14.001 (100.0 %) | - | - | - |
| mlend:whistle | 1.3 | 4.033 (98.9 %) | 2.156 (99.4 %) | 4.613 (99.4 %) | 3.878 (88.9 %) | - | - | - |
| mlend:whistle | 1.4 | 4.372 (98.9 %) | 2.278 (100.0 %) | 5.072 (99.4 %) | 4.239 (92.8 %) | - | - | - |
| mlend:whistle | 1.5 | 4.689 (99.4 %) | 2.396 (100.0 %) | 5.509 (99.4 %) | 4.603 (96.1 %) | - | - | - |
| nv:click | 1.3 | 0.471 (77.8 %) | 0.120 (92.6 %) | 0.222 (74.1 %) | - | 0.11 | 0.05 | 0.00 |
| nv:click | 1.4 | 0.663 (85.2 %) | 0.160 (96.3 %) | 0.315 (81.5 %) | - | 0.17 | 0.08 | 0.00 |
| nv:click | 1.5 | 0.902 (88.9 %) | 0.207 (100.0 %) | 0.448 (92.6 %) | - | 0.23 | 0.11 | 0.00 |
| nv:pop | 1.3 | 8.857 (100.0 %) | 8.853 (100.0 %) | 10.490 (100.0 %) | - | 3.50 | 2.22 | 4.05 |
| nv:pop | 1.4 | 9.921 (100.0 %) | 9.686 (100.0 %) | 11.977 (100.0 %) | - | 3.96 | 2.48 | 4.69 |
| nv:pop | 1.5 | 11.025 (100.0 %) | 10.513 (100.0 %) | 13.512 (100.0 %) | - | 4.45 | 2.70 | 5.29 |
| nv:smack | 1.3 | 16.193 (100.0 %) | 10.020 (100.0 %) | 14.608 (100.0 %) | - | 6.46 | 3.23 | 4.99 |
| nv:smack | 1.4 | 17.765 (100.0 %) | 11.065 (100.0 %) | 16.619 (100.0 %) | - | 8.45 | 3.69 | 6.05 |
| nv:smack | 1.5 | 19.171 (100.0 %) | 11.992 (100.0 %) | 18.595 (100.0 %) | - | 10.39 | 4.40 | 7.92 |

## 3 enrollment examples per class, no std floor

Stores: MLEnd 60 speakers, Deeply Nonverbal 32 speakers, ESC-50 cat 11 recordings, live 30 draws; 3 draws per speaker. Live classes: live:meow (7 sounds), live:yell (7 sounds), click (68 sounds), live:whistle (40 sounds); live hums (not enrolled) 46.

| enrolled class | x mult | accept (held-out, same class) | captured by another enrolled class | own non-enrolled sounds captured |
|---|---|---|---|---|
| esc50:cat | 1.4 | 54.7 % (87/159) | 0.0 % | - |
| live:click | 1.4 | 92.8 % (1810/1950) | 0.7 % | 2.1 % (29/1380) |
| live:meow | 1.4 | 95.0 % (114/120) | 0.0 % | 15.9 % (220/1380) |
| live:whistle | 1.4 | 79.4 % (881/1110) | 7.2 % | 0.9 % (13/1380) |
| live:yell | 1.4 | 61.7 % (74/120) | 8.3 % | 5.1 % (70/1380) |
| mlend:hum | 1.4 | 71.1 % (17841/25104) | 1.9 % | - |
| mlend:whistle | 1.4 | 77.8 % (24019/30867) | 2.3 % | - |
| nv:click | 1.4 | 59.4 % (130/219) | 0.0 % | 0.0 % (0/66) |
| nv:pop | 1.4 | 60.8 % (31/51) | 9.8 % | 14.6 % (7/48) |
| nv:smack | 1.4 | 62.5 % (75/120) | 1.7 % | 22.2 % (10/45) |

"own non-enrolled sounds": Deeply Nonverbal = the same speaker's coughs, laughs, sighs, ...; live = the user's hums (gestures), which must stay unmatched.

### False accepts on other people's sounds, per store (mean over stores)

Matched sounds per minute of negative audio; in brackets the share of stores with at least one false accept on that set. `others'` columns: sounds per 100 of other people's hums / whistles / sung notes captured (MLEnd and QBSH test split; not for the MLEnd stores, whose own speaker is in that pool).

| enrolled class | x mult | esc50 /min | musan /min | nonspeech7k /min | nonverbal /min | others' hum /100 | others' whistle /100 | others' sung /100 |
|---|---|---|---|---|---|---|---|---|
| esc50:cat | 1.4 | - | 6.623 (97.0 %) | 10.001 (100.0 %) | 7.159 (93.9 %) | 22.18 | 23.45 | 14.98 |
| live:click | 1.4 | 10.143 (100.0 %) | 2.378 (100.0 %) | 6.490 (100.0 %) | 8.467 (100.0 %) | 3.07 | 2.33 | 1.67 |
| live:meow | 1.4 | 0.412 (93.3 %) | 1.169 (100.0 %) | 0.983 (100.0 %) | 0.452 (73.3 %) | 13.32 | 0.13 | 7.24 |
| live:whistle | 1.4 | 3.324 (100.0 %) | 1.423 (100.0 %) | 4.456 (100.0 %) | 4.158 (100.0 %) | 2.12 | 67.91 | 0.90 |
| live:yell | 1.4 | 5.237 (100.0 %) | 3.138 (100.0 %) | 9.306 (100.0 %) | 4.676 (100.0 %) | 6.06 | 4.10 | 6.09 |
| mlend:hum | 1.4 | 3.757 (96.1 %) | 4.527 (100.0 %) | 6.094 (100.0 %) | 5.690 (100.0 %) | - | - | - |
| mlend:whistle | 1.4 | 2.114 (84.4 %) | 1.248 (97.2 %) | 1.997 (92.8 %) | 2.182 (81.7 %) | - | - | - |
| nv:click | 1.4 | 1.668 (64.6 %) | 1.038 (77.1 %) | 1.329 (54.2 %) | - | 0.54 | 0.32 | 0.50 |
| nv:pop | 1.4 | 6.304 (100.0 %) | 5.248 (100.0 %) | 6.756 (100.0 %) | - | 11.15 | 21.42 | 9.61 |
| nv:smack | 1.4 | 7.930 (97.2 %) | 4.853 (100.0 %) | 7.372 (94.4 %) | - | 4.35 | 2.43 | 3.59 |

## 10 enrollment examples per class, no std floor

Stores: MLEnd 60 speakers, Deeply Nonverbal 1 speakers, ESC-50 cat 1 recordings, live 30 draws; 3 draws per speaker. Live classes: click (68 sounds), live:whistle (40 sounds); live hums (not enrolled) 46.

| enrolled class | x mult | accept (held-out, same class) | captured by another enrolled class | own non-enrolled sounds captured |
|---|---|---|---|---|
| esc50:cat | 1.4 | 95.8 % (23/24) | 0.0 % | - |
| live:click | 1.4 | 92.4 % (1608/1740) | 0.5 % | 1.4 % (19/1380) |
| live:whistle | 1.4 | 91.7 % (825/900) | 0.1 % | 15.4 % (212/1380) |
| mlend:hum | 1.4 | 89.2 % (19647/22023) | 2.7 % | - |
| mlend:whistle | 1.4 | 91.2 % (26244/28770) | 3.2 % | - |
| nv:click | 1.4 | 88.9 % (16/18) | 0.0 % | - |

"own non-enrolled sounds": Deeply Nonverbal = the same speaker's coughs, laughs, sighs, ...; live = the user's hums (gestures), which must stay unmatched.

### False accepts on other people's sounds, per store (mean over stores)

Matched sounds per minute of negative audio; in brackets the share of stores with at least one false accept on that set. `others'` columns: sounds per 100 of other people's hums / whistles / sung notes captured (MLEnd and QBSH test split; not for the MLEnd stores, whose own speaker is in that pool).

| enrolled class | x mult | esc50 /min | musan /min | nonspeech7k /min | nonverbal /min | others' hum /100 | others' whistle /100 | others' sung /100 |
|---|---|---|---|---|---|---|---|---|
| esc50:cat | 1.4 | - | 21.727 (100.0 %) | 32.571 (100.0 %) | 24.023 (100.0 %) | 76.11 | 14.75 | 26.15 |
| live:click | 1.4 | 6.041 (100.0 %) | 1.377 (100.0 %) | 3.459 (100.0 %) | 3.933 (100.0 %) | 2.13 | 1.36 | 0.84 |
| live:whistle | 1.4 | 8.031 (100.0 %) | 7.075 (100.0 %) | 10.952 (100.0 %) | 11.170 (100.0 %) | 29.87 | 83.31 | 21.63 |
| mlend:hum | 1.4 | 8.635 (100.0 %) | 11.766 (100.0 %) | 14.895 (100.0 %) | 12.455 (100.0 %) | - | - | - |
| mlend:whistle | 1.4 | 5.018 (97.2 %) | 2.812 (100.0 %) | 5.211 (99.4 %) | 5.485 (98.3 %) | - | - | - |
| nv:click | 1.4 | 2.010 (100.0 %) | 0.448 (100.0 %) | 0.509 (100.0 %) | - | 0.65 | 0.24 | 0.00 |

