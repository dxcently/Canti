# sweeps changelog

## v5 sweep — script changes (this session)

**sweeps/sweep.sh**
- Added `DATA=<dir>` as the single data-directory parameter. It is now used for `train.jsonl`,
  `validation.jsonl`, the `--predict` input AND the `vox.evaluate` gold file, so no split can be
  scored against another version's tests. Previously hardcoded `data/v2` in all four places.
- Added `sweep() { DATA=$1; shift; train_one "$@"; }` so each row declares its own data version.
- `record` now forwards `--data-version "$DATA"`.
- Removed `eval_only` and the `v1-full` / `v2-*` calls: those rows already exist in `runs.jsonl`
  and the brief says not to redo them. The v1-full checkpoint had already finished and been
  evaluated (log ends `{"checkpoint": "runs/jevlike-e5-v1-full.pt", ..., "minutes": 48.5}`).
- `wait_for_train` pattern is now `students/jevlike/[t]rain\.py`. The old pattern could match the
  `grep` in its own pipeline (whose cmdline contains the literal pattern) and block forever.
- New run list: v3, v4, v5 e5-small-e3; v5 e5-base-e3; v5 ModernBERT-e3; v5 e5-small frozen;
  v5 e5-small e6. Predict keeps train.py's built-in batch size 1 so `latency_ms` is recorded.

**sweeps/record.py**
- New `--data-version` argument, written to every new row as `"data_version"`.

## Notes carried from the brief, verified
- `data/v3` and `data/v4` test files are byte-identical (sha256 match); v5 differs. So v3 vs v4 numbers
  are directly comparable, v5 is not.
- `data/v1` and `data/v2` tests are byte-identical to each other but *not* to v3+: the v1-full and
  v2-e5-small-e3 rows are therefore in their own tables and not comparable to v3/v4/v5.
- e5-base-v2 and ModernBERT-base weights are already in the HF cache, so item 5 should not need
  new packages or a download.

## v5 data was regenerated mid-sweep (found 12:50, evidence, no fix needed in scripts)

`data/README.md` (mtime 11:15) states: "v5 ... **Regenerated 2026-09-26 09:02**; runs trained
before that are stale" and "Never regenerate a version while something trains or evaluates on it."

`data/v5/` was rewritten at 09:02:46 while this sweep was running. Hashes measured at 06:50 vs now:

| file | 06:50 | now |
|---|---|---|
| v5/test_iid.jsonl | 85be93322a59… | 13ac72fce437… |
| v5/test_unseen_phrasing.jsonl | d1036f821997… | 6a5548304822… |
| v5/test_unseen_apps.jsonl | 89d1702d5d09… | 2f9f17ee4645… |

Kind counts and option counts changed too (option lists now run to 25 entries). The old v5 test files
are gone, so any prediction made against them is no longer scorable — re-scoring the first
v5-e5-small-e3 preds now crashes in `vox/evaluate.py` with `IndexError` on `probs[g["label"]]`.

Rows and which v5 they touched (`data/v5` files, all mtimes 09:02):

| row | trained | predicted/evaluated | verdict |
|---|---|---|---|
| v5-e5-small-e3 (1st) | 07:54–08:23 (old) | 08:23–08:24 (old tests) | **stale** |
| v5-e5-base-e3 (1st) | 08:24–09:29 (old train) | 09:31–09:33 (new tests) | **stale, mixed** |
| v5-modernbert-e3 | 09:34–11:22 | 11:23–11:25 | valid |
| v5-e5-small-frozen | 11:25–11:42 | 11:41–11:42 | valid |
| v5-e5-small-e6 | 11:42–12:48 | 12:48–12:49 | valid |

v3 and v4 are untouched (dirs still 05:52 / 05:53, hashes unchanged), so those two rows stand.

`sweeps/sweep.sh` was re-run for the two stale rows only:
`nohup bash sweeps/sweep.sh v5-e5-small-e3 v5-e5-base-e3` (started 12:50:44), which overwrites their
checkpoints, preds and eval JSONs. runs.jsonl is append-only, so it now carries a second line for each
of those names; the new line's note says which line it supersedes.

v5 fingerprints as of 12:50 (before the re-run):
train.jsonl `f102914fe343f0f01b4be62175ba04ff7e9c98ab883ce0d8fbe236bc1c72e0d5`,
validation.jsonl `26ab72b328211b8c768deb498881c845a6719ecef10265bb4f55c3a9d082e794`,
test_unseen_phrasing.jsonl `6a554830482288955892fc8ab6c7136d0cf5076ff32c88357fab8d93b8ba6202`.
