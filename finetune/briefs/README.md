# briefs: executor task briefs

Complete, self-contained instructions handed to the executor agents (DeepSeek via eidolon, run through aoide) that do long-running work in `~/VOX` without supervision: training sweeps and wording-bank writing. Each brief names its allowed paths, the data version, the run list, and what to report. Keep them updated when a plan changes, because an executor only knows what its brief says.

- `vox-sweeps.md`: the first sweep brief (v1–v4)
- `vox-sweeps-v5.md`: the current sweep brief (v3/v4/v5 runs, encoder comparisons, the targets task)
- `vox-wordings.md`: the brief for the blind LLM wording bank (`wordings_llm/`)
