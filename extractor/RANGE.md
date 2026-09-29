# Recorded range suite (v1 and v2)

`prompts/range_v2.json` is the current shared desktop/phone/checks contract (round 7 removed the
pop sound: a pop now counts as a click, and a long hiss is a new trigger). Its cells are explicit;
`prompts/make_range_spec.py` deterministically regenerates them. `prompts/range_v1.json` is frozen
(byte-identical) and still loads and scores; a session keeps its own `spec.json` and is validated
and scored with it. `range_layout.SPEC_PATH` (the recorders' default) is `range_v2.json`. Neither
recorder generates a grid. Both save an exact copy as `spec.json` and refuse to resume with a
different spec, source or mic.

The ordered blocks are `range`, `room`, `contours`, `discrete`, `combos`, `backgrounds`,
`real-media-60`, `real-talk`. Counts:

| Block | Calculation | Takes |
| --- | --- | ---: |
| Range | bottom, home, top hum; whistle home | 4 |
| Room | 3 s of quiet (the app's calibration room step) | 1 |
| Contours | 5 gestures × 14 conditions × 2 reps | 140 |
| Discrete | click + short hiss × 6 conditions × 2 reps + long hiss × 3 lengths × 2 conditions × 2 reps | 36 |
| Combos | 4 sequences × 5 conditions × 2 reps | 40 |
| Real checks | 12 centre cells × 2 backgrounds × 2 reps | 48 |
| Backgrounds | 3 media levels + tv/music + fan + talk + typing/kitchen | 7 recordings |

Thus **269 labelled takes and seven 60-second backgrounds**, with eight block
ratings for a complete session. Real checks include combos. The six condition
keys, in canonical ID order, are `tone,pitch,speed,loud,dist,gap`. IDs include
`na` values, so no applicable dimension is lost. An example is
`hum-home-normal-normal-hand-na`. Each take ID is
`<block>-<cell_id>-r<rep>`; it does not depend on dictionary ordering.

Round 7 removed the pop sound: a pop counts as a click everywhere (a heard `pop` folds to `click`,
a v1 `expect` `pop` folds to `click`, `pop pop` to `click click`, before any scoring). There are no
pop cells in v2. Singles are `click` and `hiss`; the combos are `click click` (home),
`click click click` (listen), `hiss click` (back) and `click hiss` (forward, app-only).

A short hiss (Back, about 150–400 ms) keeps v1's cell exactly: cond speed `na`, `target_s` 0.3, so
the `cell_id` is the same as v1's hiss cells. A long hiss (the cursor-mode listen and the media-lock
unlock; the app's `CursorListen.LONG_HISS_MS = 700`, measured as event `t_end_ms - t_start_ms`) gets
three new speed values `long05` / `long07` / `long10`, aimed at 0.5 / 0.7 / 1.0 s (`target_s`).
Example `cell_id`: `hiss-na-na-long07-normal-hand-na`. `defaults.hiss_s` maps the three lengths;
`analysis.long_hiss_ms = 700`.

Combo `target_s = 0.3*n + gap*(n-1)` (a pair is still `0.6 + gap`); `max_s = target_s + 2`, as before.

Cues are plain language with ONE key word in capitals (the thing to notice): at a block's centre the
key word is the gesture ("Hum a RISE at your home note, about 0.6 s"), a one-change cell capitalises
the change ("Hum a rise starting at your LOWEST note"), a corner cell capitalises each change (at most
three). No other capitals anywhere ("tv", not "TV"); every cue is at most 100 characters. The cue ends
with "about N s" only for contours and hisses (where length matters); a click or a combo gets no time
("Make two CLICKS", "Make two clicks with a QUICK gap").

## Profiles and speakers

`spec.profiles` selects cells per block; take IDs and `cond_id`s are identical
across profiles, so a short session compares cell-for-cell with a full one.

| Profile | Blocks | Takes |
| --- | --- | ---: |
| `full` (default) | everything above | 269 + 7 backgrounds |
| `short` (~8 min, a second speaker) | range 4; room 1; contours: centre, pitch bottom, loud soft, dist across × 5 gestures × 1 rep = 20; discrete: click and short hiss at centre + soft + across, long hiss at centre (one rep each) = 9; combos: 4 × centre × 2 reps = 8 | 42, no backgrounds or real checks |

Both recorders take `--profile full|short` and `--speaker <id>` (default
`self`; use a pseudonym, never a real name). `session.json` records both, and a
resume with a different profile or speaker is refused. Without `--session`, a
speaker other than self gets `range-<speaker>-<time>`. Sessions written before
profiles existed read as `full`/`self`.

A session is bound to the spec version it was recorded with. Resuming a `range_v1` session with
the v2 recorder (the default) is refused with a plain message and leaves the session untouched (no
sitting appended, no file written):

> session `<name>` was recorded with range_v1; this recorder runs range_v2. Start a new session, or
> pass --spec prompts/range_v1.json to finish it

To finish a v1 session, pass `--spec prompts/range_v1.json`. The `desk mic` is the PC's USB mic
(`--source pw --device <USB-source-name>`).

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
The `run` driver never clears phone files.

Phone slices are `[cue.t_ms - pre_roll, cue.t_ms + max_s + post_roll)`, translated
to samples by subtracting `measure_start.wav_t0_ms`. Backgrounds are exactly
60 seconds from their cue, without take pre/post-roll. Missing pre/post-roll is
not silently clipped: incomplete attempts remain unlabelled and are prompted
again on resume. Interrupted imports retain `imports/<id>/pending.json` and
verified data; retries preserve partial transfers and use a fresh export
folder. A lost start reply with no session ID requires coordinator recovery;
the driver refuses to guess a session ID. A block reaching the 20-minute cap
stops, exports completed attempts, and can be resumed in another sitting.

### In-app test recorder (dev builds)

A debug build can record the same spec on the phone alone (PROTOCOL.md, *Test
recorder (dev)*): the app shows the cue, cuts each take from its RAM ring and
writes this exact layout under its private `files/range/<name>/` (session names
as `default_session_name`; `recorder: "app"`, Hz pending). Nothing leaves the
phone until the PC pulls it, from `android/`:

```sh
./dev env python3 suite/range_phone.py pull [--session <name>]... [--quickrec] [--clear [--yes]]
```

`pull` refuses while a session is open in the app, copies every finished file
(size-checked, WAV framing checked) into a staging folder, validates each
session with `validate_session`, then swaps it in under `zflip/range/<name>`
(or `--out` below a private root; an existing folder is replaced only if it is
an app session, the old copy is kept aside until the new one is in place).
`--quickrec` also copies quick records to `zflip/quickrec/<id>` (a save still in
progress is skipped). The phone copy is deleted only with `--clear` and a typed
yes (`--yes` skips the question), and only the verified names and ids. The
destinations are gitignored. Then finalize each session under `extractor/run`
as above, and run `range_suite.py` on it.

A take the app heard nothing in (`no_sound`) is kept, not overwritten by the
retry: `takes/<block>/<take_id>.a<N>.wav` with `no_sound: true, attempt: N` in
its row. The plain path is the heard attempt; `take_rows` gives each take's last
heard row (else its last missed one), `no_sound_rows` every missed attempt, and
`range_suite` counts each missed attempt as a gate miss and lists them under
`no_sound` in its report.

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
values. The return dict contains `takes`, `backgrounds`, `ratings`, `sittings`,
`no_sound` (missed attempts, above).
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
takes only: the clicks bucket is centre discrete takes expecting click (a v1 pop
take, now folded to click, is included), the hiss bucket is centre SHORT hiss
takes only (speed `na` — the app's hiss step asks for short "tss"es; a long hiss
never feeds the gate), and the pops bucket stays empty for new data. Then the
room step runs on the room take as the app's does
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

Round 7 folds every heard `pop` into `click` and every v1 `expect` `pop` into `click` (`pop pop`
into `click click`) before any scoring, then merges click events whose spans overlap or lie within
30 ms of each other into one (the app's `ClickMerge`, `SLACK_MS` 30). `GESTURES` drops `pop`; the
report says "pop folded into click (round 7)". Because a v1 pop take now feeds the clicks bucket,
v1 gate numbers can shift slightly against older reports. The app-replay expected action uses a
local round-7 table (rise swipe_up, fall swipe_down, arch swipe_right, dip swipe_left, click tap,
hiss back, flat long_press, click click home, click click click listen_for_phrase, hiss click back,
click hiss forward), not `vox_extract.vocab`.

A new report section "hiss length" (json + md) covers every take expecting `["hiss"]` (discrete and
real): per aimed length (short / long05 / long07 / long10) the count and the median / p10 / p90 of
the heard hiss duration (the longest hiss event's `t_end_ms - t_start_ms`); a cutoff sweep for
c in 400..1000 ms step 50 (the share of short takes with duration < c that stay Back, and the
share of long07+long10 takes with duration >= c that listen, long05 listed apart as the grey zone);
the app's 700 ms row is marked; and a hiss whose `sounds_like` is in
`vox_extract.policy.NOT_GESTURE_SOURCES` is never long (as the app's `CursorListen`). The summary
over several sessions pools this per speaker.

Run the tests with `--basetemp` under `android/.state` (a `.pytest-tmp`
folder is neither gitignored nor a private root, so the privacy guard refuses
it):

```sh
./extractor/run python -m pytest tests/test_range_suite_checks.py -q -p no:cacheprovider --basetemp ../android/.state/pytest-checks
```

Timing: the full grid (269 takes + 7 minutes of backgrounds + ratings) is far
more than 20 minutes per device; plan it over several sittings. `short` is
about 8 minutes.
