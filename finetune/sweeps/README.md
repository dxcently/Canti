# sweeps: training runs and results

| File | What it does |
|---|---|
| `sweep.sh` | Driver. For each run it trains, predicts the 3 test splits of the *same* data version, evaluates and records. `DATA=data/vN` is threaded through every step |
| `record.py` | Appends one run to `runs.jsonl`: name, data version, exact command, wall time, checkpoint, metrics per test |
| `runs.jsonl` | **The results ledger.** One row per run. Rows with `note: "stale…"` were trained or tested on a data version that was later regenerated; don't compare them |
| `eval/` | `vox.evaluate` JSON per run and test |
| `make_results.sh` | Builds markdown tables per data version from the eval JSON |
| `headline.py` | One-line summary of an eval JSON |
| `probe_encoders.py` | Checks which Hugging Face encoders load and fit before a sweep |
| `CHANGELOG.md` | What changed between sweep batches and why |
