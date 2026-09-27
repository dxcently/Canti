# recordings (private, untracked)

Your own voice sessions from `record.py`. **Never committed** (`.gitignore`), because they're a person's voice.

Each session folder `live-YYYYMMDD-HHMMSS/` (or `--session <name>`) holds:
- `session.wav`: the raw capture;
- `events.jsonl`: one extractor event per detected sound;
- `messages.jsonl`: the same sounds as PROTOCOL.md messages;
- `config.json`: the extractor config used;
- `session.json`: capture source and rates, the full config, vocabulary digest, command-line arguments, the start-up signal check, duration and the `synthetic` flag;
- with `--prompt` only: `takes/NNN_<class>_<rep>.wav` and `labels.jsonl` (the prompted class, GO/stop times, expected and detected lines, verdict per take). A free recording has no labels; its by-ear notes live in `eval_real/live_replay.py` (`NOTES`) and `tests/live_regressions.json`.

`guided_session.py --session <name>` sessions hold `labels.jsonl` (one line per take, append-only; the last line per prompt id wins), `takes/<block>/*.wav`, one `run-NN/` folder per sitting (session.wav, events.jsonl, messages.jsonl, config.json), `session.json`, and `score.json` after `--score`.

Enrollment takes (`record.py --enroll custom|ignore|gesture`) go to `enroll/<kind>/<name>/`: `examples.jsonl` (push format of `android/suite/enroll.py`), `takes/`, `takes.jsonl` and one `run-<time>/` session folder per run.

```bash
./run python record.py --seconds 60                    # free recording, prints a line per sound
./run python record.py --prompt --reps 5 --whistle     # guided, labelled takes per gesture
./run python record.py --calibrate                     # set your normal hum loudness first
```
`eval_real/live_replay.py` re-runs the current extractor over the saved sessions `live-20260926-*` (the glob is fixed to that day), so fixes can be checked against your real recordings; `./run python record.py --replay recordings/<session>` does the same for any one session.
