### jl10 step 1: why J5c's none recall is 0.63 on dev_test but 0.81 on test_old

Written before any jl10 training. Source: `sweeps/jl10_diag.py` (log `sweeps/logs/jl10-diag.log`), `sweeps/jl10_bias.py`
(log `sweeps/logs/jl10-bias-J5c.log`). J5c = `runs/jl9-J5b-e3-s{7,8,9}.pt`, stored T, seed-mean of per-seed argmax.
dev_test / test_old are emulator apps (public); val_all is reported as aggregates only.

**1. The gap is composition, not the apps.** On *clean* gold-none rows (label confidence high, not ambiguous, phrase
written as a none phrase) the two sets agree: dev_test 0.774 (n 31), test_old 0.795 (n 26). The rest of the gold-none
rows split very differently: dev_test 13 rows at 0.28 recall, test_old 7 rows at 0.86.

| set | gold none | near-miss (phrase written for a target, judged absent) | ambiguous or med/low conf | recall, clean / rest |
|---|---|---|---|---|
| train_real_all | 550 (12.9 %) | 59 (11 %) | 146 (27 %) | |
| val_all | 63 | 4 (6 %) | 16 (25 %) | high 0.82 / near-miss 0.25 (n 4) |
| dev_test | 44 | 8 (18 %) | 13 (30 %) | 0.774 / 0.282 |
| test_old | 33 | 2 (6 %) | 7 (21 %) | 0.795 / 0.857 |

By phrase kind, dev_test *appearance* gold-none rows (8) are recalled 0.08; by label confidence high 0.77, med 0.33,
low 0.00. dev_test is the occlusion-aware build: several of its none rows are icons that are hidden or absent while a
text row with a related meaning is listed.

**2. What J5c picks instead.** 17 dev_test gold-none rows are missed by ≥ 2 of 3 seeds. None is picked with p ≥ 0.8
(median top-target p 0.47, median p_none 0.08), so at a 0.8 tap threshold they become deferrals, not wrong taps.
Two failure types:
- *appearance near-miss* (8): an icon word with no such icon, and J5c picks the text option of the related function:
  "the gear thing" → Configure home screen; "the magnifying glass" → Search saved articles (text field); "the little
  plus sign" → Add subtask; "that little menu button up top" → Task list options.
- *function near-miss* (9): the named thing is absent but a sibling of the same kind is listed: "the english option"
  → Français; "the wikipedia logo" → map; "open the page history" → Search Wikipedia; "set it for the first of
  october" → Due date.

**3. Label-noise suspects (not relabelled).** Among the misses, the label note itself admits a target reading in
rt2-emu-3038 ("the gear thing": "Configure a possible reading"), rt2-emu-2958 (magnifying glass → the search field),
rt2-emu-2856 ("switch the app to german": Add language is a first step); weaker: rt2-emu-3044 ("the toggle that's
on" → Shown), rt2-emu-2896 ("hide everything" → Hide this card). rt2-emu-2932 is a target hidden behind a snackbar
(correct by occlusion, invisible to a text model). At most 3–5 of 44 rows (≤ 0.11 of recall) are in doubt.

**4. A prior shift is not the fix.** A post-hoc none bias on J5c needs +1.5 to reach 0.79 on dev_test, at false-none
0.106 (from 0.042) and −2.3 points of accuracy; on val_all +0.75 already reaches 0.80. The ranking (none AUROC 0.92
dev_test vs 0.98 test_old) is what is weak on dev_test, so a none-class loss weight (≈ a prior shift) is ruled out as
the step-2b variant. C (no teacher) is also low on dev_test (0.659), so the teacher is not the cause either.

**5. Consequences for jl10.**
- Hard ("near-miss") none training data is the fix to try: (a) drop-the-gold covers function near-misses;
  (b) icon-word none rows (an icon phrase on a screen whose only related option is a text row, or none at all) cover
  appearance near-misses, the mirror of Verdict's `icon` hard positives. They are complementary, so (c) = both.
- Both are swapped in for synthetic none rows, so the none share (the prior) stays fixed and any gain is ranking,
  not a bias a val-fitted operating point could get for free.
- val_all has only 4 near-miss none rows, so selection on val cannot see this failure. Selection stays on val (rule);
  dev_test is reported, never tuned on.
