# Recorded range suite, v1

`prompts/range_v1.json` is the shared desktop/phone/checks contract. Its cells
are explicit; `prompts/make_range_spec.py` deterministically regenerates them.
Neither recorder generates a grid. Both save an exact copy as `spec.json` and
refuse to resume with a different spec, source or mic.

The ordered blocks are `range`, `room`, `contours`, `discrete`, `combos`, `backgrounds`,
`real-media-60`, `real-talk`. Counts:

| Block | Calculation | Takes |
| --- | --- | ---: |
| Range | bottom, home, top hum; whistle home | 4 |
| Room | 3 s of quiet (the app's calibration room step) | 1 |
| Contours | 5 gestures × 14 conditions × 2 reps | 140 |
| Discrete | 3 gestures × 6 conditions × 2 reps | 36 |
| Combos | 4 sequences × 5 conditions × 2 reps | 40 |
| Real checks | all 12 centre sequences × 2 backgrounds × 2 reps | 48 |
| Backgrounds | 3 media levels + TV/music + fan + talk + typing/kitchen | 7 recordings |

Thus **269 labelled takes and seven 60-second backgrounds**, with eight block
ratings for a complete session. Real checks include combos. The six condition
keys, in canonical ID order, are `tone,pitch,speed,loud,dist,gap`. IDs include
`na` values, so no applicable dimension is lost. An example is
`hum-home-normal-normal-hand-na`. Each take ID is
`<block>-<cell_id>-r<rep>`; it does not depend on dictionary ordering.

## Profiles and speakers

`spec.profiles` selects cells per block; take IDs and `cond_id`s are identical
across profiles, so a short session compares cell-for-cell with a full one.

| Profile | Blocks | Takes |
| --- | --- | ---: |
| `full` (default) | everything above | 269 + 7 backgrounds |
| `short` (~8 min, a second speaker) | range 4; room 1; contours: centre, pitch bottom, loud soft, dist across × 5 gestures × 1 rep = 20; discrete: centre, soft, across × 3 × 1 = 9; combos: centre × 4 × 2 reps = 8 | 42, no backgrounds or real checks |

Both recorders take `--profile full|short` and `--speaker <id>` (default
`self`; use a pseudonym, never a real name). `session.json` records both, and a
resume with a different profile or speaker is refused. Without `--session`, a
speaker other than self gets `range-<speaker>-<time>`. Sessions written before
profiles existed read as `full`/`self`.

## Desktop

From the repository root (these are operator commands, not commands run during
implementation):

```sh
./extractor/run python range_session.py --session range-1 --source pw --device <USB-source-name>
./extractor/run python range_session.py --session range-1 --source pw --device <USB-source-name> --block contours
./extractor/run python range_session.py --profile short --speaker sis --source pw --device <USB-source-name>
```

`--block` is repeatable. Without it, blocks run in spec order, starting with
range. Use the same session and source to resume. Enter records, `r` redoes the
last take in the current block, `s` skips until another sitting, and `q` quits.
The final take has its own review prompt, so it can also be redone. Ctrl-C stops
capture and closes the sitting. Each completed block asks for ease 1–5 and an
optional note. A missing rating is requested on resume even if all its takes
were saved. Partial block ratings can describe a sitting with skipped prompts.

The live path reuses `record.Recorder`; fake capture reuses `record.FakeSource`
and the same take loop. Single-key handling is shared with `guided_session`.
The meter and NSDF pitch analysis reuse `voice_cursor_test`. Range calibration
uses a 128 ms window and 35–2600 Hz analysis bounds from this spec; it does not
silently discard a low voice at the extractor's 75 Hz boundary. The median of
clear, audible pitch frames is stored in Hz; unavailable measurements stay null.
A measured bottom below `Config().f0_min_hz` prints a prominent warning and sets
`range.below_f0_min`. Pitch prompts refer to the person's measured bottom/home/top;
whistle prompts use whistle home.

Gesture takes without a background use spec-controlled floor-relative silence detection. Its one-second
hangover spans the slow combo's 0.8-second gap. Every take retains one second
before GO and 0.5 seconds after the detected end. Real acoustic checks use the
spec's maximum window plus post-roll, because continuous background audio can
prevent an energy-based silence detector from closing. No claims of isolated
voice end timing are made for those mixed recordings.
The room take (`quiet: true` in the spec: nothing expected, all conditions
`na`) is also a fixed window: 3.5 s from GO (the app's 3 s room window plus its
0.5 s settle), so a tap in the room cannot end it early.

Synthetic self-test, with no microphone, phone or external service:

```sh
./extractor/run python range_session.py --source fake --auto --session range-synthetic
./extractor/run python -m pytest tests/test_range_suite.py -q -p no:cacheprovider --basetemp ../android/.state/pytest-range
```

`--auto` is refused for real sources. Synthetic recordings carry
`session.synthetic=true`; they must never be used as real-audio evidence.

## Phone

`android/suite/range_phone.py` uses the same spec, PC prompts and single-key
controls. It imports `measure.checked`, `measure.stop`, `measure.pull` and
`voxlib`. It never implements another adb export path. The new optional
`measure.pull(validate_output=...)` argument lets it supply the shared private
path guard without invoking git; ordinary measurement callers retain their
existing default output guard and verification behavior.

Default connection settings are **VOX_SERIAL=emulator-5580**,
**ANDROID_ADB_SERVER_PORT=5038**, **VOX_SOCKET_PORT=7789**. Explicit coordinator
settings override these defaults. Merely importing the driver or running
`finalize` makes no device connection. No phone commands were run for C3.
The app's `measure_cue {text,id}` (PROTOCOL.md) shows the cue on the phone and
logs `measure_prompt`; text is at most 120 characters (every spec cue is ≤ 74).
A cue before the measurement's first sample is refused with a retryable
error; the driver retries it for about 2 s.

For later operator use, run from `android/` inside the Android dev environment:

```sh
./dev env python3 suite/range_phone.py run --session range-1 --block range
```

Its default private folder is `<repo>/zflip/range/<session>` (therefore
`~/VOX/zflip/range/<session>` when installed in the main repo). `--out` can
instead select a private session below `extractor/recordings` or
`android/.state`, useful for synthetic tests. The implementation and tests did
not access a zflip directory. Rates/channels are adopted from the first
measurement's native capture format and must agree for subsequent blocks.
The driver never changes capture source, volume, playback or phone settings;
the operator selects the built-in phone mic and the requested background.

The Android shell needs no NumPy: WAV slicing, cue journals and export
verification are stdlib-only. For the first range block, run the post step
under the extractor environment, then resume the phone run. Substitute the
actual private output directory:

```sh
./extractor/run python ../android/suite/range_phone.py finalize <absolute-session-directory>
```

When NumPy and the extractor dependencies are available, the run command also
finalizes the range immediately after the range block. Otherwise it marks Hz
pending and leaves calibration to `finalize`. Run `finalize` before analysis;
it processes channel 0 and does not resample or rewrite the stored native WAVs.

Each block starts `measure_start` with `phase=range-<block>`, `prompt=false`,
`record=true`, `max_s=1200`. Every GO uses `measure_cue {text,id}`; its returned
`{n,t_ms}` is durably journalled and must match the exported
`measure_prompt {sid,n,gesture,text,t_ms}`. The PC displays the same cue text.
After stopping, `measure.pull` verifies remote/local byte counts, PCM framing,
rate/channels/sample count, and exports the continuous WAV plus event lines.
The driver never clears phone files.

Phone slices are `[cue.t_ms - pre_roll, cue.t_ms + max_s + post_roll)`, translated
to samples by subtracting `measure_start.wav_t0_ms`. Backgrounds are exactly
60 seconds from their cue, without take pre/post-roll. Missing pre/post-roll is
not silently clipped: incomplete attempts remain unlabelled and are prompted
again on resume. Interrupted imports retain `imports/<id>/pending.json` and
verified data; retries preserve partial transfers and use a fresh export
folder. A lost start reply with no session ID requires coordinator recovery;
the driver refuses to guess a session ID. A block reaching the 20-minute cap
stops, exports completed attempts, and can be resumed in another sitting.

## Checks-runner API and timing

`range_layout` has no NumPy or Android dependency:

```python
from range_layout import load_spec, build_plan, latest_rows, validate_session
spec = load_spec()
plan = build_plan(spec)  # expands reps only, preserving order and cell IDs
rows = latest_rows(session / 'labels.jsonl')  # take_id -> final attempt
counts = validate_session(session, spec, complete=False)
```

`validate_layout` is an alias of `validate_session`. Invalid values raise
`ValueError`; missing/invalid input JSON can also raise the usual file/JSON/key
errors. By default an incomplete sitting is valid. `complete=True` additionally
requires every planned take, background, block rating and four measured Hz
values. The return dict contains `takes`, `backgrounds`, `ratings`, `sittings`.
Background rows use last name wins, ratings preserve sitting history.

`t_go_ms` is on the source stream clock, **not** a take-relative clock. Extra
`clip_start_ms` and `go_offset_ms` provide the mapping to the take WAV;
`dur_ms` is its full PCM duration. Desktop source clocks restart per sitting;
phone rows additionally carry `sid`, `cue_n`, `import_id`. `redo` starts at zero
and increments for replacement attempts. The canonical file path is overwritten
atomically before appending the replacement row; consumers read only the last
row per take ID. The layout validator checks metadata, spec conditions, timing,
PCM16 format, full frame data, background duration and rating bounds.

All session contents, including continuous WAVs, labels, events, ratings and
pitch summaries, are private. Never commit, upload or send them to a model.

## Checks runner (`range_suite.py`)

```sh
./extractor/run python range_suite.py recordings/<session> [more sessions] \
    [--gate-from recordings/<other>] [--summary-out <private dir>] [--emulator]
```

It loads sessions only through `range_layout` (spec, `validate_session`,
last-row-wins rows, profile, speaker) and writes `report.md`/`report.json`
(version 2) into each private session folder; it refuses any folder outside
the private roots, including `--summary-out`. The level gate is derived like
the app's CalibV2 (clicks/hiss/pops steps) from the discrete block's centre
takes only, then the room step runs on the room take as the app's does
(JoyCalibration.room): over 3 s from GO, the floor (median tick level), the
longest voiced run (3+ ticks fails as "not quiet"), and the loudest pop, click
or hiss by SNR and by level. A transient as loud as the weakest example (both)
fails as "too loud". When the room step passes, the gate is raised to the
transient + 3 dB (capped at weakest − 1 dB). When it fails, or a session
predates the room step, the gate has no room (as after an app skip), and the
report says so. `--gate-from` also scores
a session with another session's gate (e.g. a second speaker under the user's
gate). The summary groups results by speaker, then device. Mixes are seeded,
hard-clipped (clip count reported), never peak-rescaled, and never cached to
disk. Real-vs-mix mixes the *clean* counterparts (same `cond_id`) at the
estimated real SNR and pools the verdict per background. App replay
(`--emulator`) refuses the phone's serial, any non-emulator serial, adb port
5037 and socket 7788.

Run the tests with `--basetemp` under `android/.state` (a `.pytest-tmp`
folder is neither gitignored nor a private root, so the privacy guard refuses
it):

```sh
./extractor/run python -m pytest tests/test_range_suite_checks.py -q -p no:cacheprovider --basetemp ../android/.state/pytest-checks
```

Timing: the full grid (269 takes + 7 minutes of backgrounds + ratings) is far
more than 20 minutes per device; plan it over several sittings. `short` is
about 8 minutes.
