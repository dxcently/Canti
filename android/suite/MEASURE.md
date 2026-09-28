# Near-field measurement (PC side)

`measure.py` drives the shared round-7 control contract. `nearfield.py` stays in
this directory because its session clocks, labels and gates are Android-specific.
The extractor's Hann spectrum calculation was reviewed; these requested bands and
envelope measurements are separate, NumPy-only calculations at the WAV rate.

The coordinator runs the device commands later. Set `VOX_SERIAL`,
`ANDROID_ADB_SERVER_PORT`, and `VOX_SOCKET_PORT` explicitly for the intended device;
voxlib uses those values (its default serial is an emulator). The driver never
changes volume, media playback, sound source, or other phone settings. Start
phone/USB capture and enroll gestures beforehand if template distances are wanted.

Two environments. `measure.py` needs only the stdlib, voxlib and `adb`, so it runs
in the Android dev shell (which has adb but no NumPy), from `android/`:

```sh
./dev env python3 suite/measure.py run --plan default
./dev env python3 suite/measure.py run --plan default --stereo --noisy
./dev env python3 suite/measure.py pull --out ~/VOX/zflip/measure-<date>
```

`nearfield.py` and the tests need NumPy (and pytest), which live in the extractor
env. `extractor/run` changes into `extractor/`, so give absolute paths:

```sh
~/VOX/extractor/run python ~/VOX/android/suite/nearfield.py ~/VOX/zflip/measure-<date>
~/VOX/extractor/run bash -c "cd ~/VOX && python -m pytest android/suite/tests/test_measure.py -q -p no:cacheprovider"
```

Choose a private export directory outside a worktree or an explicitly gitignored
one. `pull` requires an empty destination, reads private files through `adb
exec-out run-as`, verifies remote/local byte counts, PCM framing, sample counts,
rate and channel count, and exports each session's event lines (from
`events.1.jsonl` and `events.jsonl`, since the log rotates at 2 MB). The app's
sids are small integers that restart with each service start, so only a sid's
last complete session (through its `measure_stop`) is exported; pull right after
a run. `--sid SID` is repeatable; the default pulls every recording directory
still on the phone. `--clear` deletes **all** app measurement files, so it
requires every stored recording to be in this pull, and runs only after all of
them were verified. Missing start/stop events, truncated audio and partial
exports prevent clearing. If a transfer
fails, use a fresh destination on retry. Exports stay local.

The default protocol has three silent-media recordings (60 s at 30/60/90%), five
clean recordings (one gesture per session, ten prompts each), and three mixed
recordings (90 s at 30/60/90%, prompts every 5 s). Clean sessions stop 1.5 s after
the tenth prompt is observed, before an eleventh prompt. The optional noisy pair
repeats silent and prompted media at 60%; it is reported separately. Enter `q`
then Enter during recording, or Ctrl-C, to stop. Session ids are printed for
selective export. No local audio is written by `run`.

Analysis writes `features.csv` in the export directory and Markdown to stdout.
Redirect stdout if a saved table is wanted. Options:

- `--window-start-ms -100 --window-end-ms 1500`: inclusive prompt-relative bounds;
  these override the older ±300 ms text in the plan, per the shared contract.
- `--sweep-steps 21`: quantile thresholds per feature, with endpoints just beyond
  observed values, in both directions. AND searches all pairs of distinct
  features in that sweep, independently for each volume.

Feature definitions and interpretation:

- All slices use stream ms minus `wav_t0_ms`, with 50 ms padding and boundary
  clipping. Channel 0 is analyzed; ILD is channel-0 minus channel-1 RMS dB.
- Low-band ratio uses 40 ms Hann windows with 50% overlap: power at 50–<300 Hz
  divided by power at 50–8000 Hz (limited by Nyquist). Silence yields a missing value.
- Floor is the 10th percentile of nonoverlapping 20 ms frame RMS in the preceding
  two seconds, converted to dB. Level above floor = the event's own RMS dB over
  `[t_start_ms, t_end_ms]` from the same WAV channel minus that floor (not
  `gate.level_db`, which is on the extractor's 16 kHz high-passed scale; it stays
  in `gate_level_db`). `history_ms` exposes incomplete history. Missing event RMS
  or history yields a missing value.
- Onset/decay use a 5 ms RMS envelope, 10%→90% rise and peak→10% amplitude decay.
  Unobserved crossings are null, including decay beyond the padded slice.
- Template ratio requires a positive threshold. Missing templates/stereo stay null.
  All gate fields are preserved as `gate_*` columns and `gate_json`.
- Would-act = what would act with the media lock off. The lock never marks
  `mic_sound` (it logs `media_gate` later), so it is ignored by construction.
  A sound would act when `dropped` is null (or `dry_run`, a test switch applied
  after every guard) and `gated` is null: level-gated, touch, joystick,
  calibrating and merged-duplicate drops do not act, nor do sounds the media gate
  or media-hiss rule turned into `unknown`. Raw `dropped`/`gated` are in the CSV.
- Retention counts unique prompts with at least one surviving user-labelled event,
  divided by all prompts whose reaction window ends inside the recording,
  including those with no detection. This is a prompt
  detection proxy, not proof of gesture identity or complete combo recognition.
  Clean events without a matching prompt are labelled user but do not inflate
  prompt retention. Clean positives are reported separately from mixed positives.
- False actions/minute use WAV duration, excluding the union of prompt windows
  in mixed sessions. Timing labels can include coincident media sounds.
- Missing features reject events. GO requires ≤1 false action/minute and ≥90%
  prompt retention with both negative exposure and positive prompts available.
  Clean-only or negative-only groups cannot produce GO. Best AND prioritizes GO,
  then retention at ≤1/minute, otherwise the lowest false-action rate.

These are exploratory, per-volume fitted rules, not held-out validation or a
single deployable rule proven across all volumes. No plots, uploads or model
calls are made. Tests use generated WAVs and a tiny synthetic JSONL fixture only.

## Shared recorded range suite

`range_phone.py` imports this measurement driver's start/stop, checked control
and verified pull helpers. It uses `measure_cue` for operator-paced prompts;
that op must be supplied by the app. The single grid and analysis contract is
`extractor/prompts/range_v1.json`. See [the range suite guide](../../extractor/RANGE.md)
for default emulator ports, native WAV timing, resumable imports, the stdlib-only
recording path, and `range_phone.py finalize` under `extractor/run` for Hz.
`pull` accepts an optional `validate_output` callable so this driver can use its
private-path guard without a git subprocess; all audio/event verification is
unchanged.
