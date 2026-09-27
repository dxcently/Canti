# vox_extract: the reference sound extractor

This is the Python reference for what the Pico will run. Samples go in; out comes one event per sound, holding a schema-exact text line, a `sequence` label, timing, raw measurements and the `fp1` fingerprint.

- It streams frame by frame, with fixed-size state and no ML model.
- The C port mirrors it module for module. `../vectors/` checks the port against it.
- Everything is imported through `Extractor`, so the rest of the repo never calls the stages directly.

| File | What it does |
|---|---|
| `config.py` | `Config`: every tunable number in one dataclass, saved and loaded as JSON (`Config.load`, `to_json`). The C struct should mirror it field for field. A session's `config.json` is one of these. |
| `resample.py` | `Decimator3`, the reference 48 → 16 kHz path: a 63-tap Kaiser FIR evaluated at every 3rd sample. `to_16k()` handles other file rates offline with scipy `resample_poly`; it is not part of the port, and every dataset in the real-audio evaluation goes through it. |
| `frontend.py` | `FrameProcessor`: 60 Hz high-pass, then every 10 ms hop one `Frame` from a 512-point window. Each frame has energy, ZCR, centroid, flatness, flux, band ratios, MPM pitch and clarity. It also carries the fp1 per-frame sums, which are not part of the C vectors: 8 mel-band powers, band power, 1–6 kHz power, and pitched-frame power above 3.5 × f0. |
| `segmenter.py` | `NoiseFloor`: minimum statistics over 0.4 s block means, with a robust start-up estimate from 50 ms sub-blocks and a capped rise while a sound is open. Also the gate (hysteresis, pre-roll, hangover, 4 s cap) and `SegmentStats`, the per-sound state that `classify` sees: 3 per-frame arrays plus running sums. |
| `classify.py` | One finished sound → `Event`. The order is: pop/click (short, impulsive, not tonal) → hiss / cough / laugh shapes → pitch contour (rise, fall, arch, dip, flat), then the excursion, duration, tone and loudness buckets and "sounds like". It fills `raw` with every measurement it used, plus `contour64` and `pitch16`. |
| `fingerprint.py` | `fp1`: 24 floats per sound for phone-side personalization, built from `raw` and the `SegmentStats` sums. `features_entry()` is the per-sound object of a message's `features` list. The spec is `../FINGERPRINT.md`. |
| `extractor.py` | `Extractor(cfg, input_rate=16000 or 48000)`: `push(samples)` → finished events, and `flush()`. It attaches `fp`, `fp_version` and `pitch16` to every event. `extract_array()` and `load_wav()` are conveniences. |
| `lines.py` | Builds the three line templates exactly as `finetune/vox/generate.py` does, and a strict parser (`LineError` on anything else). |
| `vocab.py` | A pinned copy of the schema vocabulary, plus `DEFAULT_BINDINGS` and `digest()`. `tests/test_lines.py` fails if it drifts from `finetune/vox/schema.py`. |
| `policy.py` | A scoring-only mirror of the app: the not-deliberate gate, the default bindings, and grouping of sounds 600 ms apart. `action_for()` answers "what would the phone do?" for one group. |
| `sequencer_sim.py` | Scoring-only replica of the app's Sequencer (act at once unless a longer bound sequence continues; absorbed tails; device-gap and arrival-timeout splits), its current bindings (pop pop, click hiss, hiss click; not `vocab.DEFAULT_BINDINGS`, the training contract), MicPopGate's lone pop and PhoneGate (incl. the media-hiss centroid rule). `would_act()` is the per-minute count `mic_live.py` and `eval_real/aec_desktop.py` report; `tests/test_sequencer_sim.py` replays the Kotlin tests' cases. |
| `protocol.py` | `message()` builds an android/PROTOCOL.md v1 message: one sound per message; `features=True` adds the optional `features` list. `DebugSocket` sends it to the app. |
| `personal.py` | A Python mirror of the app's enrollment `Matcher` (`android/.../Personal.kt`): standardise, nearest neighbour, reject threshold, banded DTW on `pitch16`. It is used by `record.py --enroll` and `eval_real/enroll_sim.py`, and never by the extractor itself. |

## How to use it

```python
from vox_extract import Config
from vox_extract.extractor import Extractor

ex = Extractor(Config(), input_rate=48000)     # or Config.load("recordings/<session>/config.json")
for chunk in audio_chunks:                     # any chunk size; results do not depend on chunking
    for ev in ex.push(chunk):
        print(ev.label, ev.text, ev.raw["fp"])
tail = ex.flush()
```

Run the tests from the extractor folder: `./run python -m pytest tests -q`.

**Changing a threshold:**
1. Edit `config.py`.
2. Re-export `../vectors/` with `./run python export_vectors.py`.
3. Rerun the synthetic eval and the real-audio eval (see `../eval_real/README.md`).
