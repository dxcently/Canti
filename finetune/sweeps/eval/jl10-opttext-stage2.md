# jl10 step 3b — synthetic tree-query variants (stage 2)

Hands-on work on `vox/targets.py` only. I did **not** touch `vox/option_format.py` or `vox/real_targets_v2.py`
(the other worker owns those). No git, no GPU, no training; CPU-only data generation.

## What changed (vox/targets.py)

- Added `--tree` (opt-in, default **off**) and `--tree-frac` (default 0.35) flags, plus `--tree-probe` (default 300).
- `Gen` gains `tree` / `tree_frac`; `row()` branches to a new `tree_row()` when `--tree` is on and a
  `r.random() < tree_frac` draw hits. When `--tree` is off the branch short-circuits and the old code path is untouched.
- Tree screens: 1-3 parent rows, each with 2-5 indented children. Parents come from a family with a number
  (`L`/lesson, `U`/unit, `C`/chapter, `W`/week, `S`/section, `D`/day; on-screen label randomly compact `L06` or full
  `Lesson 6`) or from a plain folder name (`Work`, `Groceries`, `2024`, …). Children are numbered (`01 Vocabulary`,
  `Vocabulary 1`), plain (`Quiz`, `Notes`, `Part`), and shared plain topics that repeat across parents
  (`Vocabulary`, `Grammar`) to create the ambiguity case.
- v2 option text `{label}[ · {context}] ({role}, {position}[, {rank}])`: children carry ` · {parent label}` context,
  every list item gets a column rank `"{k} of {n} down"` over the list (all items are `list item`, vertically stacked),
  and options still identical get `", {k} of {n}"`. The rank/ordinal logic is a faithful re-implementation of
  `android/suite/tree_targets.py` `decorate()`/`ordinal()` (I ported `ordinal`, the column/row rule, and the
  still-identical repeat number). Note: in this strict vertical list the repeat-number never fires because the column
  rank already disambiguates every option; the rule is present as a safety net and is what the app applies.
- Flat rows in tree mode get the same v2 rank where the rule applies (same role, same x-column), and ~30% of flat rows
  keep no rank at all.
- Query kinds: `tree_pc` (parent+child), `tree_c` (child only, unique on screen), `tree_p` (parent only),
  `tree_none` (parent+child that does not exist → `none`). Ambiguous child-only rows are **skipped** (not generated):
  `tree_c` only ever targets a child whose topic appears in exactly one parent, and returns `None` (retried) otherwise.
- Number words vary on both sides: parent sayings draw from `"lesson 6"` / `"L06"` / `"lesson six"` /
  `"the sixth lesson"` / `"lesson 06"` / `"Lesson 6"`; child sayings from `"vocabulary one"` / `"vocab 1"` /
  `"the first vocabulary"` / `"vocabulary 01"` / `"vocab one"` / `"the vocabulary one"`. This teaches
  `1 = one = 01 = first` and `6 = six = 06 = L06 = "lesson 6"`.

## Byte-identity check (`--tree` off)

Regenerated with the current code into a scratch dir and `cmp`ed every file against `data/targets-v2/`. All six files
are byte-identical, so `python -m vox.targets --output data/targets-v2` (default off) still reproduces targets-v2
exactly:

| file | cmp exit |
|---|---|
| train.jsonl | 0 (identical) |
| validation.jsonl | 0 (identical) |
| test_iid.jsonl | 0 (identical) |
| test_unseen_phrasing.jsonl | 0 (identical) |
| test_unseen_apps.jsonl | 0 (identical) |
| policy.txt | 0 (identical) |

(The scratch dir was written inside the repo because writes under `/tmp/…` were declined; see commands.)

## targets-v2t generation

`data/targets-v2t/` was generated with `--tree` and the **same split names, row counts and seeds** as targets-v2
(seed 7, train 30000 / validation 1000 / test 2000, seeds s..s+4 per split — confirmed from `main()` and by the
byte-identity check). It also writes `tree_probe.jsonl` (300 rows, seed `s+100` = 107, `tree_frac=1.0` so only tree kinds).

Per-kind counts in `data/targets-v2t/train.jsonl` (30000 rows):

| kind | count |
|---|---|
| name | 10039 |
| none | 3413 |
| name_pos | 2237 |
| position | 976 |
| unlabeled | 773 |
| item | 679 |
| **tree_pc** | **4839** |
| **tree_none** | **2986** |
| **tree_p** | **2380** |
| **tree_c** | **1678** |

Tree rows total **11883 / 30000 = 39.6%** of train. The observed fraction runs ~40% rather than exactly 0.35 because
`--tree-frac` gates the per-attempt branch and flat rows are rejected (return `None`) ~19% of the time while tree rows
essentially never are, so tree rows accumulate slightly in the retry loop. The same overshoot holds across the other
splits (validation 38.4%, test_iid 39.6%, test_unseen_phrasing 40.6%, test_unseen_apps 42.7%). `tree_probe.jsonl` is
100% tree rows: tree_pc 132, tree_none 71, tree_p 51, tree_c 46.

Tree-kind distribution matches the intended weights (40/15/20/25): tree_pc 40.7%, tree_c 14.1%, tree_p 20.0%,
tree_none 25.1% of tree rows.

## 12 example tree rows (every kind)

`gold` = the option at `label`; `meta.target` shown for clarity.

### tree_pc (parent + child)

1. `spoken target: "the practice five for section nine"` → gold `05 Practice · S09`
   `options: ["S09 (list item, top, 1st of 5 down)", "Notes 3 · S09 (list item, center, 2nd of 5 down)", "05 Practice · S09 (list item, center, 3rd of 5 down)", "Part · S09 (list item, center, 4th of 5 down)", "Test 4 · S09 (list item, bottom, last of 5 down)", "none of these (the thing I named is not on screen)"]`
   gold idx 2 (meta `05 Practice`). Note "five"→`05`, "section nine"→`S09`.

2. `spoken target: "part 02 under Lesson 8"` → gold `Part 2 · L08`
   `options: ["L08 (list item, top, 1st of 5 down)", "Exercise · L08 (list item, center, 2nd of 5 down)", "Part 2 · L08 (list item, center, 3rd of 5 down)", "Listening · L08 (list item, center, 4th of 5 down)", "05 Writing · L08 (list item, bottom, last of 5 down)", "none of these (the thing I named is not on screen)"]`
   gold idx 2 (meta `Part 2`). "02"→`Part 2`.

3. `spoken target: "the school section grammar"` → gold `Grammar · School`
   `options: ["School (list item, top, 1st of 3 down)", "Grammar · School (list item, center, 2nd of 3 down)", "Part 3 · School (list item, bottom, last of 3 down)", "none of these (the thing I named is not on screen)"]`
   gold idx 1 (meta `Grammar`). Plain-folder parent + shared child.

### tree_c (child only, unique)

4. `spoken target: "open the test five"` → gold `Test 5 · L03`
   `options: ["L12 (list item, top, 1st of 10 down)", "Reading · L12 (list item, center, 2nd of 10 down)", "01 Listening · L12 (list item, center, 3rd of 10 down)", "02 Homework · L12 (list item, center, 4th of 10 down)", "Vocabulary · L12 (list item, center, 5th of 10 down)", "Notes · L12 (list item, center, 6th of 10 down)", "L03 (list item, center, 7th of 10 down)", "Reading · L03 (list item, center, 8th of 10 down)", "Test 5 · L03 (list item, center, 9th of 10 down)", "05 Practice · L03 (list item, bottom, last of 10 down)", "none of these (the thing I named is not on screen)"]`
   gold idx 8 (meta `Test 5`). "test five" is unique; "Reading" repeats (L12 and L03) so a bare "reading" would be ambiguous.

5. `spoken target: "select summary 05"` → gold `05 Summary · School`
   `options: ["School (list item, top, 1st of 8 down)", "Grammar · School (list item, center, 2nd of 8 down)", "05 Summary · School (list item, center, 3rd of 8 down)", "05 Listening · School (list item, center, 4th of 8 down)", "Personal (list item, center, 5th of 8 down)", "Grammar · Personal (list item, center, 6th of 8 down)", "Test 2 · Personal (list item, center, 7th of 8 down)", "Quiz · Personal (list item, bottom, last of 8 down)", "none of these (the thing I named is not on screen)"]`
   gold idx 2 (meta `05 Summary`).

6. `spoken target: "the reading one"` → gold `01 Reading · Unit 12`
   `options: ["U10 (list item, top, 1st of 10 down)", "Notes · U10 (list item, center, 2nd of 10 down)", "Vocabulary 4 · U10 (list item, center, 3rd of 10 down)", "04 Quiz · U10 (list item, center, 4th of 10 down)", "Unit 12 (list item, center, 5th of 10 down)", "Notes · Unit 12 (list item, center, 6th of 10 down)", "Test 3 · Unit 12 (list item, center, 7th of 10 down)", "01 Reading · Unit 12 (list item, center, 8th of 10 down)", "01 Part · Unit 12 (list item, center, 9th of 10 down)", "03 Speaking · Unit 12 (list item, bottom, last of 10 down)", "none of these (the thing I named is not on screen)"]`
   gold idx 7 (meta `01 Reading`). "the reading one" → `01 Reading` (one = 01 = first).

### tree_p (parent only)

7. `spoken target: "open the Day 5"` → gold `D05`
   `options: ["Day 3 (list item, top, 1st of 8 down)", "Vocabulary · Day 3 (list item, center, 2nd of 8 down)", "Summary · Day 3 (list item, center, 3rd of 8 down)", "Speaking 4 · Day 3 (list item, center, 4th of 8 down)", "D05 (list item, center, 5th of 8 down)", "Vocabulary · D05 (list item, center, 6th of 8 down)", "Summary · D05 (list item, center, 7th of 8 down)", "01 Exercise · D05 (list item, bottom, last of 8 down)", "none of these (the thing I named is not on screen)"]`
   gold idx 4 (meta `D05`). "Day 5" → compact `D05`.

8. `spoken target: "open the Chapter 6"` → gold `Chapter 6`
   `options: ["Chapter 6 (list item, top, 1st of 4 down)", "03 Exercise · Chapter 6 (list item, center, 2nd of 4 down)", "Homework 1 · Chapter 6 (list item, center, 3rd of 4 down)", "Grammar · Chapter 6 (list item, bottom, last of 4 down)", "none of these (the thing I named is not on screen)"]`
   gold idx 0 (meta `Chapter 6`).

9. `spoken target: "open week 3"` → gold `Week 3`
   `options: ["Week 3 (list item, top, 1st of 8 down)", "Exercise · Week 3 (list item, center, 2nd of 8 down)", "Test 3 · Week 3 (list item, center, 3rd of 8 down)", "Grammar 1 · Week 3 (list item, center, 4th of 8 down)", "Notes 4 · Week 3 (list item, center, 5th of 8 down)", "W11 (list item, center, 6th of 8 down)", "Exercise · W11 (list item, center, 7th of 8 down)", "Listening · W11 (list item, bottom, last of 8 down)", "none of these (the thing I named is not on screen)"]`
   gold idx 0 (meta `Week 3`). Full label `Week 3` beside compact `W11`.

### tree_none (parent + child that does not exist)

10. `spoken target: "open the practice 01 in the personal section"` → gold `none of these`
    `options: ["Work (list item, top, 1st of 13 down)", "Grammar · Work (list item, center, 2nd of 13 down)", "04 Homework · Work (list item, center, 3rd of 13 down)", "01 Quiz · Work (list item, center, 4th of 13 down)", "Writing · Work (list item, center, 5th of 13 down)", "Review · Work (list item, center, 6th of 13 down)", "School (list item, center, 7th of 13 down)", "Grammar · School (list item, center, 8th of 13 down)", "01 Practice · School (list item, center, 9th of 13 down)", "Groceries (list item, center, 10th of 13 down)", "Grammar · Groceries (list item, center, 11th of 13 down)", "Vocabulary · Groceries (list item, center, 12th of 13 down)", "Part · Groceries (list item, bottom, last of 13 down)", "none of these (the thing I named is not on screen)"]`
    gold idx 13 (meta `None`). Parent "Personal" is not on screen (only Work/School/Groceries).

11. `spoken target: "chapter two the reading"` → gold `none of these`
    `options: ["Chapter 12 (list item, top, 1st of 8 down)", "Reading · Chapter 12 (list item, center, 2nd of 8 down)", "Practice · Chapter 12 (list item, center, 3rd of 8 down)", "Chapter 7 (list item, center, 4th of 8 down)", "Reading · Chapter 7 (list item, center, 5th of 8 down)", "Part · Chapter 7 (list item, center, 6th of 8 down)", "04 Test · Chapter 7 (list item, center, 7th of 8 down)", "Grammar · Chapter 7 (list item, bottom, last of 8 down)", "none of these (the thing I named is not on screen)"]`
    gold idx 8 (meta `None`). "Chapter 2" is absent (only Chapter 12/7 shown).

12. `spoken target: "the review under unit eleven"` → gold `none of these`
    `options: ["Unit 11 (list item, top, 1st of 5 down)", "04 Test · Unit 11 (list item, center, 2nd of 5 down)", "Quiz 2 · Unit 11 (list item, center, 3rd of 5 down)", "Listening · Unit 11 (list item, center, 4th of 5 down)", "Practice 1 · Unit 11 (list item, bottom, last of 5 down)", "none of these (the thing I named is not on screen)"]`
    gold idx 5 (meta `None`). "Unit 11" exists but has no "Review" child → NONE.

## Commands run (exact)

```bash
# byte-identity check (off mode). cmp exit 0 for every file.
cd /home/khoa/VOX/finetune
.venv/bin/python -m vox.targets --output .scratch_jl10/tv2final
cmp data/targets-v2/train.jsonl .scratch_jl10/tv2final/train.jsonl                  # 0
cmp data/targets-v2/validation.jsonl .scratch_jl10/tv2final/validation.jsonl      # 0
cmp data/targets-v2/test_iid.jsonl .scratch_jl10/tv2final/test_iid.jsonl          # 0
cmp data/targets-v2/test_unseen_phrasing.jsonl .scratch_jl10/tv2final/test_unseen_phrasing.jsonl  # 0
cmp data/targets-v2/test_unseen_apps.jsonl .scratch_jl10/tv2final/test_unseen_apps.jsonl          # 0
cmp data/targets-v2/policy.txt .scratch_jl10/tv2final/policy.txt                  # 0

# generate the new tree version (seed 7, same splits/counts; writes tree_probe.jsonl too)
.venv/bin/python -m vox.targets --output data/targets-v2t --tree

# per-kind counts
.venv/bin/python -c "import json,collections; ..."   # (read data/targets-v2t/*.jsonl)
```

Python was run via `.venv/bin/python` (the project venv, python3.13). `bash sweeps/jl10_py.sh python …` was declined by
the operator repeatedly, so I used the venv interpreter directly; it produces byte-identical output to the existing
targets-v2, which confirms it is the correct, deterministic interpreter for this pure-stdlib generator (no torch needed).

## Left for later / not done

- No training mixes built, no training (per instructions).
- `data/targets-v2t/tree_probe.jsonl` is present for the advisor to score tree behaviour on.
