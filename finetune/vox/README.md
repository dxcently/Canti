# vox: vocabulary, data generation, scoring

The single source of truth for what the model can see and do. The Android app's `Vocab.kt` and `TargetVocab.kt` are generated from these files (`android/tools/gen_vocab.py`), and a digest check keeps the two sides in sync.

| File | What it does |
|---|---|
| `schema.py` | The vocabulary: sound contours, discrete sounds, buckets (excursion, duration, loudness, sounds-like), `ACTIONS`/`CURSOR_ACTIONS` (key → option text), `DEFAULT_BINDINGS`, apps, screen-context vocabulary and `screen_text()`, spoken phrases, and the screen tie-breakers (`SCREEN_NEXT`, `PAUSE_WORDS`, …) |
| `generate.py` | Synthetic data for the **gesture decision**. Builds a scene (mode, app, screen line, sounds or phrase, defaults, the user's rules) and the correct action by rule. Row kinds: default, sequence, app_rule, global_rule, phrase, phrase_rule, screen_phrase, disabled, unbound, not_deliberate, cursor. Holds the **held-out** wordings, templates, phrases and apps used by the unseen-phrasing and unseen-apps tests. Deterministic given `--seed` |
| `targets.py` | Synthetic data for **intent cursor mode**: pick the on-screen element the user named ("the heart icon" → `Like (button, bottom right)`), or none. The docstring is the spec for the option format the app builds from accessibility nodes |
| `wordings.py` | Training-only wording banks (more ways to say each action/gesture/rule), kept disjoint from the held-out lists |
| `bank.py` | Merges the LLM wording bank into training while dropping anything near a held-out wording (exact, substring, Jaccard ≥ 0.6) or marked ambiguous |
| `evaluate.py` | Scores any prediction file (`{"id", "probs"}` per row) against gold: accuracy, per-kind accuracy, ECE, NLL, false-trigger and missed-command rates, and latency. Use it for every model so the numbers compare |
| `target_baselines.py` | No-training baselines for target picking (fuzzy word overlap; zero-shot e5 similarity), to show whether a trained model is needed |

Row format (all tasks): `{"context", "options", "label", "option_keys", "kind", "id", "split", "meta"}`. `context` is exactly the text the phone sends as `state`.
