# jl10 step 3 — new option text (stage 1 + stage 3 mixes) — FINAL

## Files changed
- `vox/option_format.py`: `INDENT_CONTEXT`; `indent_context` (fixes a-c + i); `_strip_identical_rank` / `_identical_pass` /
  `_apply_indent` (fix d); `reserialize_exact` / `v2i_from_targets`; `reserialize` applies `_apply_indent`; `selftest`.
- `vox/fixtures/indent_parity.json`: indented list + generic 'more' parent (c) + a 2-column grid under a 'Section'
  header (i) + FAB 'Add' role item (a) + flat list + button bar.
- `vox/real_targets_v2.py`: `--option-format v2i`; `formatted()` exact paths; `cmd_mix` `--syn-format` + none-by-label +
  v2/v2i family check; `rel(syn_f.resolve())` fix (a relative `--syn-file` crashed the `.mix.json` sidecar).
- `sweeps/jl10_verify_b4a.py`, `sweeps/jl10_analyze.py` (evidence scripts).

## Rules implemented
(a) target+parent both "list item"; (b) same immediate parent + list-container test (>= 3 kept items fallback);
(c) skip generic/unlabeled/equal-label parent; (d) indent context applied before the identical-option "k of n" pass
(strip + re-run, byte-identity proven by selftest `flat_unchanged`); (i) a container is a GRID when >= 2 kept list items
are in the same row (vertical overlap, `tt._v_overlap`) at different lefts, and gets no indent context.

## Selftest / build / verify (measured)
- `.venv/bin/python -m vox.option_format --selftest` -> all pass (tree_targets parity ok, approx_equal 19/19,
  indent_parity ok 20 options, flat_unchanged true).
- `.venv/bin/python -m vox.real_targets_v2 build --out data/real-targets-v2/b4a-v2i --overwrite --val-mode optset
  --folds 5 --folds-from data/real-targets-v2/b2/folds.json --option-format v2i` -> 10 split files, vox code c8c0998c5c8c.
- `jl10_verify_b4a.py` (b4a-v2i vs b4a row-for-row): **0 mismatches** across all 10 files.

## Step 4 counts (gained>=1 indent " · " / any context / distinct screens w/ indent)
train_real 14/1000/2 · val_real 0/175/0 · test_real 0/136/0 · test_real_old 0/160/0 · test_exact 0/271/0 ·
zflip/train_real_all 14/1018/2 · zflip/val_real_all 0/175/0 · zflip/train_real_zflip 0/18/0 ·
zflip/val_real_zflip 0/0/0 · zflip/diag_x_opus 0/40/0.
test_exact vs app options_v2: 0 screens differ, 0 options differ.

Top-10 indent contexts (distinct screens): 'Storage manager' 2 (only one label remains).

Remaining indent examples (all distinct): 
- emu-settings-24 (source v1): `Free up space · Storage manager (list item, center, 2nd of 8 down)`
- emu2-settings2-24 (source v2): `Free up space · Storage manager (list item, center, 2nd of 8 down)`

The grid exclusion (i) removed every false positive (launcher GridView, the emu3-settings-01 two-column app list, and
the "Today"/"Live"/date headers, which were multi-column). Only the genuine indented settings list remains.

## Stage 3 — mixes (data/real-targets-v2/b4a-v2i/zflip/)
- mix.jl7 byte-identity: `--real .../b4a/zflip/train_real_all.jsonl --real-rep 3 --syn 12000 --syn-none 0.12 --seed 0`
  into /tmp and `cmp` vs b4a/zflip/mix.jl7.jsonl -> exit 0 (IDENTICAL), then deleted.
- mix.jl10-v2i.jsonl (`--syn-file data/targets-v2t/train.jsonl --syn-format v2`): 24801 rows, none share 0.125,
  tree kinds tree_pc 2185 / tree_c 721 / tree_p 1064 / tree_none 678.
- mix.jl10-v2i-dg.jsonl (same + `--dropgold-n 720 --swap-syn-none`): 24801 rows, none share 0.125,
  tree kinds tree_pc 2185 / tree_c 721 / tree_p 1064 / tree_none 326.
- drop-gold: 720 produced from **1478 eligible** of 4267 real rows (>= 720 needed); the `drop_gold_ok` label parse
  (`rsplit(" (",1)[0].split(" · ")[0]`) behaves on v2i (rank stays in the parens).
- teacher.jl8.oof.jsonl coverage: **12756** matched real-row ids in each of mix.jl7 / mix.jl10-v2i / mix.jl10-v2i-dg
  (identical set).
- real rows carrying an indent context: **14** (of 4267 real rows).

## Commands
All `python` = `.venv/bin/python` (the finetune venv; the nix-shell wrapper is only for torch/ROCm, unused here).
