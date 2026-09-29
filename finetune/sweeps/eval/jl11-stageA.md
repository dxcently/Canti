# jl11 — stage A (CPU data/code work, no training)

Candidate context: J7b (mix.jl10-v2i-dg, `--dropgold-n 720 --swap-syn-none`) removed synthetic none rows in
shuffled list order and dropped most `tree_none` rows (678 -> 326), losing 0.13 on tree_none probes. jl11 keeps
tree_none rows in the swap and adds a `--dropgold-hard-n` "shared-evidence" pool.

## Files changed
- `vox/real_targets_v2.py`:
  - `drop_gold(...)`: added `kind` kwarg (default `"none_dropgold"`; hard rows pass `"none_dropgold_hard"`). Default path unchanged (byte-identity proved, see below).
  - `drop_gold_hard_ok(r) -> str | None` (new, next to `drop_gold_ok`): a row `drop_gold_ok` rejects *only* for "shared evidence" may still become a hard none row when the phrase has >= 2 content tokens (after `_DG_STOP`) that occur in the gold label, every remaining option misses at least one of those gold tokens, and no remaining option's label contains the whole gold label (or vice versa). Also requires >= 2 non-gold options (so `drop_gold` succeeds).
  - `cmd_mix`: `--dropgold-hard-n N` branch (own rng `seed + 3001`, prints reason counts) and `--keep-tree-none` swap (remove flat `kind=="none"` rows first, never `tree_none`; if more hard rows than flat rows, keep all tree_none anyway and the none share rises).
- `students/jevlike/train.py`: `--patience N` (default 0 = off). Stops after N consecutive epochs without a better selection metric; logs `{"early_stop": <epoch>}` (1-based epoch); saved checkpoint stays the best epoch.
- `students/jevlike/suite_jl.py`: `Predictor.logits` passes `cache_options=(os.environ.get("JL_CACHE")=="1")` to `JLModel.logits`.
- `students/jevlike/opgate.py`: `--pooled` (opt-in) reports per-recipe wrong/tap point estimate + CP95 over dev_test+test_old pooled at the same frozen point; when `--bound point`, the per-set table prints the true CP95 next to the point estimate (the monkeypatched `cp_upper` otherwise collapses it to the rate). Default output unchanged when `--pooled` absent / `--bound cp95`.

## 1c. Byte-identity (measured)
Rebuilt `mix.jl10-v2i-dg.jsonl` into `.scratch_jl11/` with the sidecar's exact flags (no new flags), then `cmp`:
```
.venv/bin/python -m vox.real_targets_v2 mix --real data/real-targets-v2/b4a-v2i/zflip/train_real_all.jsonl \
  --real-rep 3 --syn 12000 --syn-none 0.12 --seed 0 --syn-file data/targets-v2t/train.jsonl \
  --syn-format v2 --swap-syn-none --dropgold-n 720 --out .scratch_jl11/mix.jl10-v2i-dg.jsonl
cmp .scratch_jl11/mix.jl10-v2i-dg.jsonl data/real-targets-v2/b4a-v2i/zflip/mix.jl10-v2i-dg.jsonl
```
-> **IDENTICAL** (exit 0). Scratch copy deleted afterwards.

## 1d. mix.jl11-K0/K1/K2 (built under data/real-targets-v2/b4a-v2i/zflip/)

Base flags for all three: `--real data/real-targets-v2/b4a-v2i/zflip/train_real_all.jsonl --real-rep 3 --syn 12000
--syn-none 0.12 --seed 0 --syn-file data/targets-v2t/train.jsonl --syn-format v2 --swap-syn-none --keep-tree-none`.

| mix | extra flags | rows | none share | none_dropgold | none_dropgold_hard | tree_none | flat synthetic none | teacher.jl8.oof id coverage |
|---|---|---|---|---|---|---|---|---|
| K0 | `--dropgold-n 720` | 24801 | 0.1246 | 720 | 0 | 678 | 42 | 12756 |
| K1 | `--dropgold-n 1440` | 25479 | 0.1479 | 1440 | 0 | 678 | 0 | 12756 |
| K2 | `--dropgold-n 720 --dropgold-hard-n 720` | 24819 | 0.1252 | 720 | 60 | 678 | 0 | 12756 |

Notes:
- none share in cmd_mix's final line is rounded to 3 decimals (K0 "0.125", K1 "0.148", K2 "0.125"); the table is the exact 4-decimal share = `none rows / rows`.
- `tree_none` is **678 for all three** (preserved, vs mix.jl10-v2i-dg's 326). `flat synthetic none` = synthetic rows with `kind=="none"`.
- teacher coverage = rows whose id is in `data/real-targets-v2/b4a/zflip/teacher.jl8.oof.jsonl` = 12756 for all three (the jl10 number).
- K1/K2 have fewer synthetic rows than 12000 (11238) and more total rows than 24801 because there are only 762 flat none rows in the 1440-row none window: `--dropgold-n 1440` (K1) and 720+60 (K2) exceed 762, so the rule keeps all 678 tree_none rows as *extra* synthetic none rows (none share rises; K1 0.1479).

### Eligible counts
- strict (`drop_gold_ok is None`): **1478** of 4267 real rows (same as jl10).
- hard (`drop_gold_hard_ok is None`): **60** of 4267. Reason counts over all 4267: `not shared-evidence-rejected` 4135, `fewer than 2 gold tokens` 58, `ok` 60, `label containment` 10, `option matches all gold tokens` 2, `fewer than 2 options left` 2. The "shared evidence" pool is 132 = 60 ok + 58 + 10 + 2 + 2.

**Open finding:** `--dropgold-hard-n 720` yields only **60** rows (not 720). The safety rules (>= 2 gold tokens, no remaining option matches all gold tokens, no label containment) shrink the 132 shared-evidence rows to 60. So K2 carries 720 strict + 60 hard = 780 hard none rows, not the intended 1440.

### 12 random hard drop-gold rows (K2, `kind=="none_dropgold_hard"`, `random.Random(0).sample`)
1. phrase "export all my notes please" — dropped gold "Export all notes (list item, top right, 1st of 3 down)" — remaining ["Delete all done (list item, top right, 2nd of 3 down)", "Change category (list item, top right, last of 3 down)"]
2. phrase "yeah the health manager thing" — dropped gold "Health Manager (item, top left, 2nd of 6 down)" — remaining [Back, Sports & Health, Share, More options, unlabeled, Install, unlabeled, unlabeled, More, Links, Versions, Expand]
3. phrase "the data limit settings" — dropped gold "Data warning & limit (item, bottom, last of 2 down)" — remaining [Navigate up, Use this SIM, SIM name & color, Roaming, App data usage, Preferred network type, IMEI]
4. phrase "switch over to the synced tabs" — dropped gold "Synced Tabs Open: 0. Tap to switch tabs. (list item, top right, 1st of 4 down)" — remaining [Private Tabs Open: 0..., Normal Tabs Open: 24..., 0 tab groups open..., Dismiss, View options, Dismiss tab group onboarding, VOX long page, Close tab VOX long page, ...]
5. phrase "the health manager one" — dropped gold "Health Manager (item, top left, 1st of 7 down)" — remaining [Sports & Health, Install, unlabeled, unlabeled, More, unlabeled, Links, Versions, Expand, Developer contact, Expand, Collapse]
6. phrase "hide the archived ones" — dropped gold "Hide archived (list item, top right, 1st of 3 down)" — remaining ["Hide completed (list item, top right, 2nd of 3 down)", "Sort (list item, top right, last of 3 down)"]
7. phrase "export as kmz" — dropped gold "Export KMZ (list item, bottom, 3rd of 5 down)" — remaining [touch outside, Edit, Hide, Export GPX, Export GeoJSON]
8. phrase "the normal tabs section" — dropped gold "Normal Tabs Open: 23. Tap to switch tabs. (list item, top, 2nd of 4 from left)" — remaining [Private Tabs Open: 0..., 0 tab groups open..., Dismiss, Synced Tabs Open: 0..., View options, UNDO]
9. phrase "the play queue" — dropped gold "Play queue (button, bottom right, 2nd of 4 from left)" — remaining [Open Drawer, Live, What's New, Subscriptions, Search, Bookmarked Playlists, overlay thumbnail, video item detail, Play video..., overlay buttons layout, Pause, Close]
10. phrase "the plus sign to add a network" — dropped gold "Add network (list item, center, 4th of 7 down)" — remaining [Navigate up, T-Mobile, Fix connectivity, Settings, Wi-Fi, AndroidWifi..., Network preferences, Saved networks, Non-carrier data usage]
11. phrase "sync the feeds" — dropped gold "Sync feeds (item, top right, 2nd of 10 down)" — remaining [Mark all as read, Add feed, Edit feed, Delete feed, Import feeds from OPML, Export feeds to OPML, Import saved articles, Export saved articles, Settings, Close menu]
12. phrase "tap the box that says enter your password" — dropped gold "Please enter a password (text field, top, 1st of 2 down)" — remaining ["Please confirm the password (text field, center, last of 2 down)", Show password, btnPrevious, btnNext]

(Rows 2, 4, 8, 9 have long option lists; abbreviated here with "...". Full text is in the mix file.)

## Task 2. near-miss none val slice (built)
- `val_real_all` = 497 rows, none share **0.1268** (63 none rows).
- `drop_gold_ok` passes on **168** of 497; capped to **80** with `random.Random(0).sample` -> `val_nearmiss.jsonl` (80 rows, all `kind=="none_dropgold"`, ids `<id>-dgv`, label = none).
- `val_real_all_nm.jsonl` = val_real_all + val_nearmiss = **577** rows, none share **0.2478** (143 none).
- **0 id collisions** between the 497 val ids and the 80 `-dgv` ids (577 unique ids total).

## Tasks 3/4/5 (code only; no GPU run in this stage)
- train.py `--patience`: logic added after the per-epoch selection update; logs `{"early_stop": epoch+1}` then breaks; checkpoint save path untouched.
- suite_jl.py `JL_CACHE=1`: `Predictor.logits` -> `JLModel.logits(..., cache_options=True)`; default (env unset) unchanged.
- opgate.py `--pooled`: pools dev_test+test_old rows (seeds aligned) and calls `cf_eval.op_eval` once per recipe at the frozen point; reports `wrong_tap_per_tap` (point) and `real_cp_upper(rate*n_eff, n_eff)` (CP95). The CP95 routine is `cf_eval.cp_upper` (one-sided Clopper-Pearson upper bound); it does **not** take a design effect — the app design effect is applied the same way `op_eval` does it (effective n `n_eff = taps / deff`, `deff` from `cf_eval.design_effect`, one-way ANOVA ICC floored at 0). When `--bound point`, the per-set table prints `point (CP95)` using `real_cp_upper` instead of the monkeypatched rate.

## --help default-path checks
- `.venv/bin/python -m vox.real_targets_v2 mix --help` -> OK (no torch).
- `nix shell nixpkgs#python313 nixpkgs#uv -c bash -c "source ./env.sh && source .venv/bin/activate && python students/jevlike/{train,opgate,suite_jl}.py --help"` -> all OK (train.py/opgate.py/suite_jl.py import torch, which needs the project's nix ROCm env for libstdc++; `--patience`, `--pooled`, `--dropgold-hard-n`, `--keep-tree-none` all appear in their `--help`).

## Commands (all `.venv/bin/python` unless noted; from finetune/)
```
# 1c
.venv/bin/python -m vox.real_targets_v2 mix --real data/real-targets-v2/b4a-v2i/zflip/train_real_all.jsonl --real-rep 3 \
  --syn 12000 --syn-none 0.12 --seed 0 --syn-file data/targets-v2t/train.jsonl --syn-format v2 --swap-syn-none \
  --dropgold-n 720 --out .scratch_jl11/mix.jl10-v2i-dg.jsonl
cmp .scratch_jl11/mix.jl10-v2i-dg.jsonl data/real-targets-v2/b4a-v2i/zflip/mix.jl10-v2i-dg.jsonl   # IDENTICAL

# 1d (BASE="--real .../train_real_all.jsonl --real-rep 3 --syn 12000 --syn-none 0.12 --seed 0 \
#        --syn-file data/targets-v2t/train.jsonl --syn-format v2 --swap-syn-none --keep-tree-none")
.venv/bin/python -m vox.real_targets_v2 mix $BASE --dropgold-n 720  --out .../mix.jl11-K0.jsonl
.venv/bin/python -m vox.real_targets_v2 mix $BASE --dropgold-n 1440 --out .../mix.jl11-K1.jsonl
.venv/bin/python -m vox.real_targets_v2 mix $BASE --dropgold-n 720 --dropgold-hard-n 720 --out .../mix.jl11-K2.jsonl

# Task 2 (one-off script)
#   val = jl(val_real_all); elig = [r for r in val if drop_gold_ok(r) is None]  (168)
#   elig = random.Random(0).sample(elig, 80); for r: x = drop_gold(r, Random(0)); x['id'] = r['id']+'-dgv'
#   wjl(val_nearmiss, out); wjl(val_real_all_nm, val + out)
```

## Open questions
1. `--dropgold-hard-n 720` only finds **60** eligible rows (shared-evidence pool 132, safety rules -> 60). K2 therefore has 780 hard none rows, not 1440. Do we (a) accept K2 at 60, (b) relax the `>= 2` gold-token / no-label-containment rules, or (c) drop K2 / the hard pool for jl11?
2. K1 (`--dropgold-n 1440 --keep-tree-none`) and K2 exceed the 762 flat none rows, so their none share rises (K1 0.1479) and total rows grow (25479 / 24819). Confirm that is the intended "keep all tree_none anyway" behavior (vs. instead capping hard rows at the flat count).
3. train.py `--patience` logs `{"early_stop": <1-based epoch>}` to match the file's `"epoch"` convention; confirm the advisor reads it that way (the brief wrote `{"early_stop": epoch}`).
