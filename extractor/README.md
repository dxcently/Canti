# VOX reference feature extractor

This is a Python reference for the on-device sound extractor. It takes microphone samples and emits one event per sound: `{t_start_ms, t_end_ms, label, text line, raw measurements}`.

- The text line uses exactly the strings in `finetune/vox/generate.py`.
- The label is the `sequence` label in the PROTOCOL.md message.

It is written to be ported to C on the Pico 2 W (Cortex-M33, 150 MHz, 520 KB SRAM). It works frame by frame and streams, with fixed buffers and no ML model. It keeps a few KB of state.

> **Two kinds of numbers are in this file.** "Synthetic results" come from SYNTHETIC audio (`synth.py`): they show that the pipeline works on the signals it was designed around, and they are optimistic. "Real-audio results" come from six public datasets and the user's own live recordings (`eval_real/`, `results/real_*`); they are the ones to quote about real voices, mics and rooms, and they are much worse.

## Layout

| path | what |
|---|---|
| `vox_extract/config.py` | `Config`: every threshold in one dataclass. It is saved and loaded as JSON and should be mirrored field for field in C. |
| `vox_extract/resample.py` | `Decimator3` (reference 48 kHz → 16 kHz: a 63-tap FIR, evaluated only at every 3rd sample). Also `to_16k` for other file rates (not part of the port). |
| `vox_extract/frontend.py` | `FrameProcessor`: runs the high-pass filter, then per 10 ms hop computes energy, ZCR, spectral centroid / flatness / flux / band ratios, and MPM pitch with clarity. |
| `vox_extract/segmenter.py` | `NoiseFloor` (minimum statistics), the gate (hysteresis, pre-roll, hangover, 4 s cap) and `SegmentStats` (what is kept per sound). |
| `vox_extract/classify.py` | One sound → `Event`: pop/click/hiss/contour, excursion and duration buckets, tone, loudness, and "sounds like". |
| `vox_extract/lines.py` | Builds lines exactly like generate.py, plus a strict parser. |
| `vox_extract/vocab.py` | A pinned copy of the schema vocabulary and a digest. A test fails if it drifts from `finetune/vox/schema.py`. |
| `vox_extract/extractor.py` | `Extractor(cfg, input_rate=16000 or 48000)`, with `push(samples)` → events and `flush()`. |
| `vox_extract/protocol.py` | Builds PROTOCOL.md v1 messages; `DebugSocket` talks to the app's `vox-debug` socket. |
| `vox_extract/policy.py` | Mirrors the app's not-deliberate gate, the default bindings and the 600 ms grouping. Used only for scoring. |
| `vox_extract/fingerprint.py` | `fp1` (24 floats per sound) and `pitch16`, the optional `features` of the message. Spec: `FINGERPRINT.md`. |
| `vox_extract/personal.py` | Python mirror of the app's enrollment `Matcher` (Personal.kt), for `record.py --enroll` and `eval_real/enroll_sim.py`. |
| `record.py` | Mic or WAV → live event lines, WAV + JSONL, a guided labelled session (`--prompt`), and enrollment takes (`--enroll`). |
| `eval_real/` | The REAL-audio evaluation (six public datasets + the live recordings). See its README. |
| `FINGERPRINT.md` | The `fp1` / `pitch16` field spec, cost on the RP2350, per-feature scales. |
| `synth.py` | Generates labelled SYNTHETIC clips (gestures, click-pop, negatives, 4 backgrounds). |
| `tests/` | pytest suite, plus `synthetic_eval.py` (the SNR sweep). |
| `export_vectors.py` → `vectors/` | Test vectors for the C port. |
| `results/` | Evaluation outputs; `results/README.md` says which are current (`real_*`) and which are superseded (`dev*`). |

## Setup

Nothing is installed system-wide. NixOS provides the C++ runtime and PortAudio through `env.sh`, and `run` wraps it:

```
cd /home/khoa/VOX/extractor
./run python -m pytest tests -q -p no:cacheprovider      # 77 tests (69 pass, 8 known-open live cases xfail), ~11 s
./run python tests/synthetic_eval.py --per-cell 12 --workers 8   # full synthetic sweep (≤ 8 workers: the box is shared)
./run python export_vectors.py                            # regenerate vectors/
```

The venv at `.venv` was built with `nix shell nixpkgs#python313 nixpkgs#uv` (numpy, scipy, soundfile, sounddevice, pytest).

## Design

**Front end (16 kHz, hop 160 = 10 ms, window 512 = 32 ms).**

- 48 kHz input is decimated by a symmetric 63-tap Kaiser FIR (cutoff 7.2 kHz, β = 8). The attenuation is ≥ 60 dB above 9.6 kHz, and the passband is flat to 0.1 dB up to 5 kHz.
- Next comes a 2nd-order Butterworth high-pass at 60 Hz (one biquad).
- Every hop produces one frame from the latest 512 samples. All of a frame's features describe the window centre, so frame *j* has `t_ms = 10·j − 11`.
  - Energy comes from the central 160 samples, and ZCR from the central 320.
  - A periodic Hann window and a 512-point real FFT give:
    - centroid;
    - spectral flatness;
    - band ratios below 1 kHz and above 3.5 kHz;
    - positive log-spectral flux. This is floored at the tracked noise floor so that silent bins produce no flux.
  - Pitch uses MPM (McLeod & Wyvill). The NSDF comes from a 1024-point FFT autocorrelation of the unwindowed window, over f0 of 75–2600 Hz. It picks the first key maximum ≥ 0.88 × the highest, then applies parabolic interpolation. Clarity is the NSDF peak height.

**Noise floor and gate.**

- **Floor.** This is minimum statistics over 0.4 s blocks: the floor is the lowest block-mean energy of the last 8 blocks (3.2 s). A 0.4 s quiet gap every 3 s is enough to track it. During the first 2 blocks, a block whose mean is more than 10 dB above its quietest quarter of 50 ms sub-blocks uses that quiet part instead, so a sound during start-up does not become the floor. While a sound is open, the floor rises at most 3 dB/s.
- **Spread.** This is the lower median of the block standard deviations. It measures how much the background itself fluctuates.
- **Open/close thresholds.** The gate opens at floor + max(9 dB, 2.5·spread) and a frame counts as active above floor + max(5 dB, 1.5·spread). Babble therefore needs a bigger jump than a steady fan.
- **Timing.**
  - Pre-roll: 3 frames.
  - Hangover: 100 ms.
  - A sound is force-closed at 4 s and flagged truncated. This bounds RAM.
  - Warm-up: 250 ms.
  - `t_end` is the end of the last active frame, so the hangover adds latency but not duration. An event is reported about 116 ms after its sound ends.

**Per sound (`SegmentStats`).** These are three int16-able arrays (energy, f0, clarity; ≤ 400 frames) plus running energy-weighted sums of the spectral features.

**Classification (`classify.py`), in order:**

1. **Pop / click.** The sound must be short: gate time ≤ 200 ms and ≤ 60 ms within 15 dB of its peak. It must also be impulsive: onset flux ≥ 6 dB or the peak within the first 3 frames. A briefly "voiced" resonant lip pop is allowed if its peak is early. A short sound that is mostly voiced (≥ 50 %) and clear (≥ 0.8) is a tone fragment, such as a whistle's top, and is never pop / click. Pop and click are split by the peak-frame centroid at 1.8 kHz. A short blip that is neither impulsive nor voiced is dropped.
2. **Unvoiced sounds** (voiced fraction < 0.25):
   - A **hiss** needs centroid ≥ 2.2 kHz and ZCR ≥ 0.18. It is labelled "background noise" when its low band carries > 20 % of the energy, or when it is > 1.5 s and steady. Otherwise it is a "mouth sound".
   - Cough- and laugh-shaped sounds get a hum line with "coughing" or "laughing".
   - Any other noise becomes a hiss line with "background noise".
3. **Voiced → contour.**
   - Voiced frames within 12 dB of the sound's level are converted to semitones.
   - Clean-up: a median filter of 5, octave and jump correction (> 7 st), and a smoothing of 5.
   - Start and end pitch are the medians of the first and last 5 voiced frames. Then:
     - net = end − start;
     - hump = max − max(start, end);
     - valley = min(start, end) − min.
   - **flat** if max(|net|, hump, valley) < 1.5 st. **arch** if hump ≥ max(1 st, |net|, valley). **dip** likewise with valley. Otherwise **rise** or **fall** by the sign of net.
   - Excursion buckets: < 2, 2–4 and > 4 st. Duration buckets: 150, 400 and 1000 ms.
   - Tone: median clarity ≥ 0.8 is "clear tone", and ≥ 0.6 is "breathy".
4. **Loudness.**
   - Without calibration: level (the p90 hop energy) − floor is quiet below 18 dB and loud at 40 dB or more.
   - With calibration (`record.py --calibrate`): normal is the calibrated level ± 8 dB.
5. **"Sounds like" for voiced sounds.** The checks run in this order:
   1. Longer than 3 s → background music or noise.
   2. f0 ≥ 600 Hz and clear → whistle.
   3. Pitch residual < 0.04 st over ≥ 0.9 s → background noise (a machine).
   4. Cough shape → coughing.
   5. Regular bursts → laughing.
   6. Talking needs at least 2 of these 3 cues:
      - broken voicing within the strong part;
      - a spread of log2(centroid) ≥ 0.45 octave, from vowel/consonant alternation (≥ 0.7 is enough alone);
      - ≥ 2 syllable-like loudness peaks.
      A short voiced sound starting ≤ 300 ms after a talking sound is also talking.
   7. Long, tonal, with stepping pitch → background music.
   8. Otherwise → hum.

The device does not decide anything. It describes each sound, and the phone groups sounds (gap ≤ 600 ms) and decides. Junk is still emitted, with an honest "sounds like", because the phone's gate and model are trained to ignore it.

## Configuration

Every number lives in `vox_extract/config.py` and is commented there. `Config.load(path)` rejects unknown keys. `record.py` stores the exact config with every recording (`config.json`, `session.json`), and `--config` reloads one. The values were tuned on synthetic audio. The real-audio evaluation added fields for its fixes (start-up floor: `floor_startup_*`; floor-rise cap while a sound is open: `floor_rise_open_db_s`; tonal fragments are never pop / click: `discrete_tonal_voiced_frac`, `discrete_tonal_clarity`) but changed no existing threshold. A set of three thresholds tuned on the real-audio tune split is in `results/real_tuned_config.json`; it is **not** the default (see "Real-audio results").

The development protocol was:

- Tuning used seed 1 (`results/dev*`).
- The quoted numbers come from one run on the default seed 20260926, after tuning was frozen. `synth.py` and the classifier were not changed after that run.

## Real-audio results

`eval_real/` runs the extractor on six public datasets (sources and licences in `datasets/SOURCES.md`) and on the user's twelve live sessions. Speakers are split 30 % tune / 70 % test, and the numbers below are the **test** split. Every dataset file goes through `resample.to_16k`; only the live recordings (48 kHz USB mic) use the `Decimator3` path. Full reports: `results/real_*.md`; one table: `results/real_summary_table.md`.

Three configurations:
- **frozen**: the code as it was before any real audio was seen. This is the headline.
- **fixed**: the current code with the default Config. The fixes were (1) a short, clearly voiced sound is a tone fragment, never pop / click; (2) a sound during start-up no longer becomes the noise floor; (3) the floor rises at most 3 dB/s while a sound is open. No threshold was changed.
- **tuned**: fixed + three thresholds chosen on the tune split only (`discrete_max_ms` 200 → 600, `pop_attack_frames` 3 → −1, `pop_onset_flux_db` 6 → 3).

| test split | frozen | fixed | tuned |
|---|---|---|---|
| tongue click detected, clean / 10 dB (31 clips) | 71 / 90 % | 71 / 84 % | 71 / 84 % |
| lip pop detected, clean / 10 dB (35 clips) | 29 / 57 % | 26 / 49 % | 20 / 31 % |
| QBSH sung contour, label right (clean) | 84.8 % | 86.0 % | 86.0 % |
| QBSH pitch tracker, gross pitch error | 0.6 % | 0.6 % | (same front end) |
| MLEnd hum called "hum" / "talking" | 50 / 34 % | 49 / 34 % | 49 / 34 % |
| MLEnd whistle called "whistle" | 91 % | 90 % | 90 % |
| false-accept groups / min: MUSAN speech / music / noise | 0.92 / 2.29 / 2.39 | 0.79 / 2.13 / 2.16 | 0.74 / 0.89 / 1.44 |
| false-accept groups / min: Nonspeech7k / ESC-50 / ESC-50 cat | 2.37 / 2.63 / 7.14 | 2.14 / 2.39 / 6.49 | 1.84 / 1.93 / 7.14 |
| Deeply Nonverbal negatives (coughs, sighs, ...) FA / min | 0.87 | 0.55 | 0.40 |
| lines outside generate.py's line space | 38.5 % | 40.2 % | 42.8 % |

The pop and click rows rest on 31 and 35 clips, so one clip is about 3 points.

**What this says:**
- **Real audio is much harder than synthetic.** Synthetic discrete accuracy at 30 dB is 97 %; a clean real lip pop is found 26–29 % of the time. About 34 % of real hums are called "talking", and about 2 false-accept groups per minute come from music, noise and environmental sounds.
- **The fixes cut false accepts by 7–37 %.** They cost 3–9 points of lip-pop detection and 6 points of tongue clicks at 10 dB, which is a few clips each. On the live recordings they remove both tonal pops (105053 @989 and the meow session); the by-ear checks go from 5 to 6 of 8. The synthetic sweep is unchanged, apart from duration buckets (96.6 → 95.8 %). The start-up floor needed three tries. A 50 ms sub-block quantile cannot tell babble from a sound, so it now triggers only when a block is more than 10 dB above its own quiet quarter.
- **The tuned thresholds are not the default.** On the tune split they looked better: clean pops went from 47 to 53 %, with fewer false accepts. On test they cut pops (26 → 20 % clean, 49 → 31 % at 10 dB) and lip smacks, and on synthetic they drop discrete accuracy from 97 to 89 % (30 dB). They do cut music false accepts by more than half. Use them with `--config results/real_tuned_config.json` where music is the main problem.

**User-confirmed live cases** are in `tests/live_regressions.json`, and 8 of them are open. The whistle arches of 124112 / 124244 come out as "fall". The soft tongue clicks of 124259 come out as "pop". Neither has a general fix that the data supports (see "Known weaknesses").

**Personalization** (`FINGERPRINT.md`, `results/real_enroll_sim.md`). With 5 enrolled examples, the phone's matcher accepts 82–93 % of a user's own sounds and keeps most of their hums unmatched. A custom class fires on other people's similar sounds at 0.1–14 per minute. 3 examples are too few.

## Synthetic results (SYNTHETIC ONLY)

`results/final_16k.md` has 1056 clips: 22 classes × 4 SNRs × 12 clips (3 per background: white, pink, brown, cafe babble), 16 kHz. Here SNR means the active-span RMS of the sound vs. the background RMS.

Label accuracy on gesture clips (%):

| | 30 dB | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| contour (hum + whistle) | 100.0 | 100.0 | 93.3 | 61.7 |
| discrete (pop / click / hiss) | 97.2 | 91.7 | 75.0 | 44.4 |
| click only | 100.0 | 91.7 | 33.3 | 25.0 |

End to end means the clip yields exactly its default action and nothing else. This includes the phone-style grouping and the not-deliberate gate.

| | 30 dB | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| rise / fall / arch / dip / flat | 100 / 100 / 100 / 100 / 100 | 100 / 100 / 100 / 100 / 100 | 83 / 92 / 92 / 100 / 100 | 75 / 67 / 33 / 58 / 67 |
| pop / hiss | 91.7 / 91.7 | 75.0 / 100 | 91.7 / 100 | 33.3 / 50.0 |
| click → pop (listen for a phrase) | 100 | 91.7 | 41.7 | 25.0 |

**False accepts.** On negatives (talk, short talk, laugh, cough, music, air, fan with motor tone, silence), a false accept means any action other than none. The rate is **2.1 %** over all SNRs (8 of 384 clips):

- 6 taps: cough ×2, and one each for fan, laugh, music and silence;
- 1 swipe_left from silence;
- 1 long_press from talk.

**Buckets and timing.**

- Excursion bucket correct: 94.9 %, when the contour is correct.
- Duration bucket correct: 96.6 %.
- "hum" called hum: 94.6 %. Whistle called whistle: 91.7 %.
- `t_end` error vs. the synthetic truth, where the truth is the sample where the envelope reaches zero:
  - median −7.5 ms, mean |err| 25.5 ms, p90 49 ms;
  - it grows at 5 dB (rise: p90 218 ms).
  - Negative means reported early. The gate closes 5 dB above the floor, before the tail dies out.

**Lines.** 1181 were emitted with 0 strict-parser or label errors. Of these, 193 are valid vocabulary but outside what generate.py produces; see "Schema / line-format issues".

**48 kHz input** (`results/final_48k.md`, 528 clips, 6 per class and SNR, through the decimator):

- Contour accuracy: 100 / 100 / 95.0 / 88.3 %.
- Discrete: 100 / 100 / 77.8 / 61.1 %.
- False accepts: 2.1 %.

The better low-SNR numbers are **not** a real advantage. The synthetic backgrounds are broadband to 24 kHz, and the decimator removes the noise above 8 kHz, so "5 dB" at 48 kHz is about 9–10 dB in band. Compare rates only at the same in-band SNR.

**Speed.** Python runs at a real-time factor of 0.012 on this workstation, which says nothing about the MCU.

## Compute estimate for the Cortex-M33 (ESTIMATE, not measured)

These are per 10 ms hop. One MAC-equivalent is 2 flops; FFT costs assume radix-2 split real FFTs.

| stage | per hop |
|---|---|
| decimator 48→16 kHz (only with a 48 kHz mic) | 160 × 63 = 10 080 MAC (≈ 5 040 using the symmetric taps) |
| high-pass biquad | 160 × 5 = 800 MAC |
| energy + ZCR | 160 MAC + 320 compares |
| Hann window + real FFT 512 + power | 512 + ≈ 6 400 + 514 MAC-eq |
| centroid, band ratios, flatness, flux | ≈ 1 000 MAC + ≈ 480 logs (2 per band bin) |
| MPM: real FFT 1024 forward, power, inverse | ≈ 14 000 + 1 026 + 14 000 MAC-eq |
| MPM: m′(τ) recursion, NSDF, peaks (τ ≤ 214) | ≈ 430 MAC + 215 divides + ≈ 300 compares |
| floor, gate, segment sums | < 200 |
| **total** | **≈ 38 k MAC-eq (16 kHz mic), ≈ 48 k (48 kHz mic)**, plus ≈ 480 logs and ≈ 215 divides |

At an assumed 2–3 cycles per MAC-eq (CMSIS-DSP-class code), ~20 cycles per fast log and 14 cycles per divide, this comes to roughly 90–160 k cycles per hop. The hop budget at 150 MHz is 1.5 M cycles, so the load is **≈ 6–11 % of one core**.

At the end of each sound there is a one-off burst for classification. It runs median filters, percentiles and a line fit over at most 400 frames, estimated at ≤ 0.5 M cycles (a few ms). It happens once per sound.

**Cheap saving.** Run MPM only while the gate is open, plus the 3 pre-roll frames: keep 3 hops of extra raw audio and compute their pitch when the gate opens. That drops the idle cost to about 11 k MAC-eq per hop.

**RAM.** Persistent state is about 6–8 KB:

- the 512-sample window;
- the previous log spectrum (241 floats);
- the decimator history (62);
- the floor ring (8 + 8);
- the segment arrays (3 × 400 int16).

Scratch memory is about 10–12 KB (FFT buffers, contour work arrays). Twiddle tables go in flash.

## Recording sessions (for a human)

First check the mic. `--list-devices` shows whether PipeWire sees a plugged-in mic:

```
cd /home/khoa/VOX/extractor
./run python record.py --list-devices
./run python record.py --seconds 10          # live: hum / pop / hiss and watch the lines; Ctrl-C stops early
```

The guided, labelled session:

- asks for each gesture 5 times: rise, fall, arch, dip, long flat, pop, click, hiss, click-then-pop;
- then asks for 8 s each of talk, laugh, cough, music, silence and fan/air.

For each take you press Enter, wait for **GO**, make the sound once, and stay quiet until **stop**. After each take, Enter keeps it, `r` redoes it and `x` discards it. Before a take, `s` skips it and `q` quits.

```
./run python record.py --prompt --calibrate --session <name> --reps 5
#   optional: --whistle (adds whistled contours), --shuffle, --neg-seconds 10,
#             --gestures rise fall pop, --negatives talk silence, --source sd --device N, --rate 16000
./run python record.py --replay recordings/<name>                 # re-run the current code on it and score it
./run python record.py --replay recordings/<name> --config my.json # ... with other thresholds
```

**Output** goes to `recordings/<name>/`:

| file | contents |
|---|---|
| `session.wav` | everything, 48 kHz PCM16 |
| `takes/NNN_<class>_<rep>.wav` | each take plus 1 s before and 0.5 s after |
| `labels.jsonl` | per take: class, instruction, GO/stop times, expected labels/action, detected lines, verdict, level, kept |
| `events.jsonl` | every event with raw features |
| `messages.jsonl` | the PROTOCOL.md messages |
| `session.json` | source, rate, config, vocab digest, signal check, synthetic flag |
| `config.json` | the config used |

**Other options:**

- To feed the phone app live, run `adb forward tcp:7788 localabstract:vox-debug` and add `--send 127.0.0.1:7788`. `--protocol` prints each JSON message.
- `--wav a.wav b.wav [--out dir]` runs files instead of the mic.
- `--source fake` is a SYNTHETIC microphone for testing the tool itself, e.g. `./run python record.py --source fake --prompt --session selftest --reps 2 --auto`. Its sessions are marked `"synthetic": true`.

**Enrollment takes (`--enroll`)** record labelled examples for the phone's personalization, in the push format of `android/suite/enroll.py`:

```
./run python record.py --enroll custom  --name meow            # a new sound of the user's (a custom action on the phone)
./run python record.py --enroll ignore  --name yell            # a sound the phone must ignore
./run python record.py --enroll gesture --gesture click        # the user's own version of a gesture (rise/fall/arch/dip/flat/pop/click/hiss)
#   --takes 5 (default), --take-seconds 3.0
```

Each take keeps one sound: for a gesture, the first event with that label (a contour needs a 16-point `pitch16`); for custom / ignore, the longest. Output goes to `recordings/enroll/<kind>/<name>/`: `examples.jsonl` (one line per kept example: `kind, name, fp, fp_version, pitch16`, plus file, label and text), `takes/NNN.wav`, `takes.jsonl` and a `run-<time>/` folder like a normal session. After the takes it prints the class's spread, its least typical take, and whether any take would match another enrolled class (the app's Matcher rules, `vox_extract/personal.py`, with the app's floor table). Push to the phone with `python android/suite/enroll.py push recordings/enroll/<kind>/<name>/examples.jsonl`.

**Silence protection.** At start, `record.py` measures 1.5–2 s. If the input is exact digital zeros (muted, unplugged or jack not detected), or below −90 dBFS, it stops unless `--allow-silent` is given. It also warns after any 3 s of exact zeros, and on clipping.

## Microphone status on this machine

A USB mic works: `pipewire:alsa_input.usb-CMEDIA_Q9-1-00.mono-fallback`, captured at 48 kHz through `--source pw` (the default). The user's twelve sessions `recordings/live-20260926-*` were made with it and are replayed by `eval_real/live_replay.py`.

The on-board input `alsa_input.pci-0000_c5_00.6.analog-stereo` still delivers exact zeros (both its Front and Rear Microphone ports report *not available*). PortAudio's `default` / `pipewire` devices fail to open in this Nix environment, so use `--source pw` or `--source sd --device N`.

## Known weaknesses (honest list)

**The thresholds were tuned on synthetic audio**, and the real-audio evaluation shows where they break (numbers in "Real-audio results"):

- **Lip pops are mostly missed** (26 % of clean real pops found). Many real pops have a slow onset (onset flux < 2 dB) and a low, voiced resonance.
- **About a third of real hums are called "talking"** (MLEnd 34 %; 33–41 % at every f0 band). The speech cues fire on real hums.
- **About 2 false-accept groups per minute** on music, noise, crying, screaming and environmental sounds. A cat's meow is the worst (6.5 / min).
- **Asymmetric contours depend on the user.** The user's whistled arches (124112, 124244) rise only 1–2 semitones early and then fall 4–6, so by the rule (hump ≥ |net|; the wiki says peak ≥ 4 st above both ends) they are falls. The user's other whistled and hummed "falls" (e.g. 105021 @1069, 105053 @8389, 124112 @11169) have the same shape. No threshold separates the two. `arch_ratio` 0.5 fixes 1 of the 4 arches and flips 3 other live contours; including quiet onset frames (`contour_db` 30) costs 10 points of QBSH accuracy. Per-user enrollment of a gesture arch (pitch16 + DTW) is the tool for this.
- **Soft tongue clicks can look like lip pops.** In 124259 the user's soft clicks have a peak centroid of 0.8–1.3 kHz, lf_ratio 0.67–0.92 and flatness ≤ 0.06, which is the same range as the user's own lip pops (105910: 0.6–0.9 kHz, 0.52–0.91, ≤ 0.04). Only onset flux (1.6–2.6 vs 4.3–7.1 dB) and rise time separate them for this user. In Deeply Nonverbal, 12 of the 18 low-centroid test lip pops have flux ≤ 1.9 dB, so a flux rule would lose about two thirds of them. A split at 1 kHz fixes 2 of the 4 clicks and costs 14 points of pops at 10 dB. Per-user enrollment of a gesture click is the tool.
- **Long wide glides are called "talking"** (124028 @1179: 2 s, 43 st range). The centroid follows the harmonics, so a large pitch change looks like vowel/consonant change (centroid spread 0.73 octave ≥ 0.7). A pitch-normalised spread might fix it; this has not been tried, because there is no ground truth yet.
- The machine-steady rule (0.04 st): a very steady real whistle or trained hum held ≥ 0.9 s could be called background noise.

**Detection gaps:**

- **Clicks at low SNR** are missed on synthetic audio: 33 % at 10 dB and 25 % at 5 dB. A tongue click is a few ms long, so its 10 ms hop energy barely clears the gate. On real audio (Deeply Nonverbal, test), 71 % of clean tongue-click clips and 84 % at 10 dB yield a pop or click event; only 65 % of clean clips are mostly labelled click.
- **5 dB SNR is poor for everything:** about 62 % for contours and 44 % for discrete sounds. Arches lose their hump.

**Speech vs. hum is hard.**

- 1–2 syllable utterances look like short hums. On synthetic data, 19 of 49 short-talk sounds are called "hum". They usually fail the not-deliberate gate anyway (small change or short), but not always: see the talk false accepts.
- On real speech (MUSAN) the default profile acts on 0.8 groups per minute.

**Insertions void gestures.** In cafe babble or with a cough nearby, an extra blip within 600 ms joins the gesture's group. The phone then rejects the whole group.

**Coughs, laughs and music.** These are often "background noise" hiss lines or a "talking"/"laughing" hum, not always the right source label. They still map to no action.

**Loudness without calibration** is relative to the noise floor. The same hum reads "loud" in a quiet room and "normal" in a noisy one. Use `--calibrate` per mic and distance.

**Latency and timing.**

- An event arrives about 116 ms after its sound ends.
- `t_end` runs early by about 8 ms (median), and much more at low SNR.
- A sound longer than 4 s is truncated.
- A steady noise longer than about 3 s becomes the new floor.

**The synthetic generator shares assumptions with the detector** (e.g., nasal resonance, harmonic tilt), so these numbers are optimistic even for "hums like the model".

## Schema / line-format issues (reported, not changed)

1. **No template for unvoiced non-hiss sounds** (cough bursts, taps, rustle). The extractor has to use the hiss line with "background noise", or a hum line with "coughing". generate.py only makes hum lines for coughing.
2. **Lines the extractor emits that generate.py never produces.** The vocabulary is valid but the combinations are unseen in training. The model's behaviour on them is untested. Counts from the final synthetic run:
   - non-deliberate hums longer than 1 s (music, laughs, long talk): 85;
   - very short hums that sound like talking or coughing: 39;
   - very short hisses: 26;
   - non-flat hums with a small pitch change that sound like talking, coughing or laughing: 20;
   - hum lines with "sounds like background noise": 13;
   - loud "background noise" hisses (generate.py makes those quiet or normal): 7;
   - other unseen combinations: 3.

   Suggestion: widen `junk_sound` / `air_hiss` in generate.py to cover these (all EXCURSION and DURATION values for non-gesture sources, "background noise" hums, very short and loud hisses). The Android rules decider already handles them via "sounds like".
3. **Pop/click lines can only say "mouth sound".** A keyboard click or a knock is still a "mouth sound" pop or click, and becomes a tap. `sounds like background noise` for instant sounds would let the phone ignore it, but generate.py never writes it and the parser mirrors that.
4. **The protocol label "unknown"** exists in Message.kt, but no training line corresponds to it. The extractor never emits it. Junk voiced sounds carry their contour label instead.
5. **Cooldown.** The wiki mentions about 300 ms of refractory time after an event. That would swallow the pop of a click-pop (150–450 ms apart), so `cooldown_ms` defaults to 0.
6. **Two different digests.** `vocab.digest()` hashes the vocabulary lists, which is what a C port can embed. The app's `Vocab.SOURCE_DIGEST` hashes the source files of schema.py + generate.py. The two are different numbers by design; do not compare them.

## C-port test vectors (`vectors/`)

`export_vectors.py` writes 19 SYNTHETIC cases, 2 of them at 48 kHz, plus a decimator-only vector. Each case has:

- `<case>.pcm`: int16 LE input;
- `<case>.frames.csv`: every frame's features and the floor after it;
- `<case>.events.json`: the expected events, with exact lines and protocol messages.

`manifest.json` holds:

- the full config and the vocabulary with its digest;
- the high-pass biquad coefficients;
- the decimator taps and indexing rule;
- the frame-time formula;
- the tolerances. Event labels and texts must match exactly and times within one frame (10 ms). Per-feature tolerances for frames are listed in the manifest.

`tests/test_vectors.py` fails if the vectors go stale. After changing the code or config, re-export them.
