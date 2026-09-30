# v6 second seed report (seed 11 vs seed 7)

Run: `v6-e5-small-e3-s2` (train.py `--seed 11`) vs the v6 first seed `v6-e5-small-e3` (train.py default `--seed 7`),
both `e5-small-v2`, 3 epochs, `data/v6`. Full comparison in `sweeps/scratch/v6s2_compare.txt`.

## Wall time (seed 11)
- Train: 998 s (16.5 min logged) — `sweeps/scratch/v6s2_queue.log`, `sweeps/runs.jsonl` `train_wall_s=998.0`
- Predict + eval (3 splits): 79 s (`predict_wall_s=79.0`)
- Total: 1077 s (`total_wall_s=1077.0`)
- Device: `"device": "cuda"` (train log line 3). For reference seed 7 was train 982 s / predict 77 s / total 1059 s.

## Headline + per-kind + paired (McNemar)

### test_iid
| metric | seed 7 | seed 11 | delta |
|---|---|---|---|
| accuracy | 0.9985 | 0.9990 | +0.0005 |
| nll | 0.0026 | 0.0011 | -0.0015 |
| ece | 0.0016 | 0.0009 | -0.0007 |
| false_trigger_rate | 0.0041 | 0.0000 | -0.0041 |
| missed_command_rate | 0.0007 | 0.0000 | -0.0007 |

Paired: b=2 (seed7 right, seed11 wrong), c=3 (seed7 wrong, seed11 right), **McNemar exact p = 1.000000**.
Kind deltas all <= 0.79 pt (cursor +0.0079, app_rule -0.0074, screen_phrase +0.0068).

### test_unseen_phrasing
| metric | seed 7 | seed 11 | delta |
|---|---|---|---|
| accuracy | 0.9960 | 0.9860 | **-0.0100** |
| nll | 0.0108 | 0.0447 | +0.0339 |
| ece | 0.0019 | 0.0119 | +0.0100 |
| false_trigger_rate | 0.0023 | 0.0000 | -0.0023 |
| missed_command_rate | 0.0013 | 0.0000 | -0.0013 |

Paired: b=26, c=6, **McNemar exact p = 0.000535** (significant).
Kind swings > 2 pts: `global_rule` 1.000 -> 0.968 (-0.032), `phrase_rule` 1.000 -> 0.968 (-0.032),
`sequence` 1.000 -> 0.978 (-0.022), `app_rule` 1.000 -> 0.980 (-0.020).

### test_unseen_apps
| metric | seed 7 | seed 11 | delta |
|---|---|---|---|
| accuracy | 0.9940 | 0.9895 | -0.0045 |
| nll | 0.0176 | 0.0434 | +0.0258 |
| ece | 0.0036 | 0.0088 | +0.0052 |
| false_trigger_rate | 0.0021 | 0.0000 | -0.0021 |
| missed_command_rate | 0.0013 | 0.0000 | -0.0013 |

Paired: b=15, c=6, **McNemar exact p = 0.078354** (not significant at 0.05).
Kind swing > 2 pts: `screen_phrase` 0.931 -> 0.893 (**-0.038**, 148/159 vs 142/159).

## Verdict on seed noise
- **test_iid**: within seed noise (delta +0.05 pt, p=1.0).
- **test_unseen_apps**: within seed noise (delta -0.45 pt, p=0.078).
- **test_unseen_phrasing**: NOT within seed noise. Seed 11 is 1.0 accuracy point lower and the paired
  McNemar is significant (p=0.000535), with most of the drop concentrated in `global_rule`,
  `phrase_rule`, `sequence` and `app_rule` (each -2 to -3.2 pts). In relative terms the error rate rises
  from 0.4% (seed 7) to 1.4% (seed 11), ~3.5x.

## Oddities
- Every split shows seed 11 with `false_trigger_rate=0.0000` and `missed_command_rate=0.0000`, vs seed 7's
  small non-zero values. Seed 11 never fires on a "none" row and never abstains on a command here.
- Kinds swinging > 2 points: `global_rule`, `phrase_rule`, `sequence`, `app_rule` on test_unseen_phrasing;
  `screen_phrase` on test_unseen_apps (see tables). None swing > 2 pts on test_iid.

## Disagreeing rows on test_unseen_apps (screen_phrase kind)
18 rows. Seed 11 has a consistent screen_phrase confusion pattern: several `swipe_right` -> `previous_item`,
`next_item` -> `swipe_up`, and `previous_item` -> `swipe_down`/`swipe_left` (a direction/next-prev-media
confusion), while a few rows flip the other way (seed 7 wrong, seed 11 right).

| id | kind | expected | seed 7 | seed 11 |
|---|---|---|---|---|
| test_unseen_apps-1061 | screen_phrase | swipe_right | swipe_right (right) | previous_item (wrong) |
| test_unseen_apps-1252 | screen_phrase | previous_item | previous_item (right) | swipe_down (wrong) |
| test_unseen_apps-138 | screen_phrase | next_item | next_item (right) | swipe_up (wrong) |
| test_unseen_apps-142 | screen_phrase | swipe_right | swipe_right (right) | previous_item (wrong) |
| test_unseen_apps-1552 | screen_phrase | next_item | swipe_up (wrong) | next_item (right) |
| test_unseen_apps-1792 | screen_phrase | swipe_right | swipe_right (right) | previous_item (wrong) |
| test_unseen_apps-1817 | screen_phrase | previous_item | previous_item (right) | swipe_left (wrong) |
| test_unseen_apps-1904 | screen_phrase | play_pause | none (wrong) | play_pause (right) |
| test_unseen_apps-1949 | screen_phrase | none | play_pause (wrong) | none (right) |
| test_unseen_apps-504 | screen_phrase | swipe_left | swipe_left (right) | next_item (wrong) |
| test_unseen_apps-512 | screen_phrase | next_item | swipe_up (wrong) | next_item (right) |
| test_unseen_apps-590 | screen_phrase | next_item | swipe_up (wrong) | next_item (right) |
| test_unseen_apps-666 | screen_phrase | next_item | next_item (right) | swipe_up (wrong) |
| test_unseen_apps-669 | screen_phrase | swipe_right | swipe_right (right) | previous_item (wrong) |
| test_unseen_apps-685 | screen_phrase | next_item | next_item (right) | swipe_up (wrong) |
| test_unseen_apps-690 | screen_phrase | play_pause | none (wrong) | play_pause (right) |
| test_unseen_apps-840 | screen_phrase | next_item | next_item (right) | swipe_up (wrong) |
| test_unseen_apps-861 | screen_phrase | next_item | next_item (right) | swipe_up (wrong) |
