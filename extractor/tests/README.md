# tests: pytest suite and the synthetic sweep

Run everything from the extractor folder. It takes about 11 s: 69 pass and 8 are expected failures (open live cases, see below).

```bash
./run python -m pytest tests -q -p no:cacheprovider
./run python tests/synthetic_eval.py --workers 8 --name final_16k           # full SYNTHETIC sweep -> results/final_16k.{md,json}
./run python tests/synthetic_eval.py --workers 8 --sr 48000 --per-cell 6 --name final_48k
```

`conftest.py` puts the extractor root first on `sys.path`, so the tests always import the working copy of `vox_extract`. To check that a test fails on older code, run its functions from a script against that code instead.

| File | What it checks |
|---|---|
| `test_lines.py` | Every emitted line is one of generate.py's three templates, with exact vocabulary. The pinned `vocab.py` matches the live `finetune/vox/schema.py`, which is read-only. |
| `test_stream.py` | Results do not depend on chunk size; the 48 kHz decimator; config JSON round trip. |
| `test_protocol.py` | PROTOCOL.md v1 message keys and types, and the phone-side grouping and policy mirror. |
| `test_synthetic_regression.py` | A small SYNTHETIC smoke test: clean-ish clips of each class give the right label. It guards the pipeline; it is not an accuracy measure. |
| `test_live_regressions.py` | Regressions from the user's live recordings (48 kHz USB mic). A whistle rising from t = 0 is never a pop. A loud warm-up burst must not raise the start-up floor enough to hide a following whistle. A decaying tone is not a click. The floor rise is capped while a sound is open. Recording 105053 has no tonal pop, and that test is skipped if the recording is absent. Each test runs at 16 and 48 kHz where it matters. |
| `test_live_cases.py` + `live_regressions.json` | User-confirmed labels at given spans of the live recordings (`{session, t_start_ms, t_end_ms, expected_label}`), matched to the replayed event that overlaps most. Skipped when the WAV is absent. Cases marked `"status": "open"` are known failures (xfail, not strict, with the reason in `why_open`): the asymmetric whistle arches of 124112 / 124244 and the soft tongue clicks of 124259. A fix shows up as XPASS. |
| `test_vectors.py` | `vectors/` still matches the current code. If this fails after a deliberate change, re-export with `./run python export_vectors.py`. |
| `synthetic_eval.py` | Not a test: the SNR × background sweep over synth.py clips. It gives the confusion matrix, bucket accuracy, timing error, end-to-end action accuracy and off-distribution lines. **SYNTHETIC ONLY.** |
| `finetune_ref.py` | Read-only import of `finetune/vox/generate.py`, with bytecode writing off, used for the off-distribution check. It returns None if finetune/ is missing. |
