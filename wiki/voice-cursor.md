# Voice cursor: pitch places the cursor up and down, the vowel places it sideways

> **Decision (user, 2026-09-27): the absolute voice cursor is dropped.** Test 2 (vcursor-2) came out NO-GO. What replaces it is a **relative 360° joystick cursor with snap-to-elements**, built as a desktop prototype first: see [Joystick cursor](#joystick-cursor-decision-2026-09-27). The rest of this page is the absolute design and its tests, kept as the record. The analysis they produced is reused: the pitch tracker, the F2 tracker with the v2 fixes, and the vibrato and release handling.

**Status: design draft (2026-09-27). Nothing is built.** The user asked for an *absolute* voice cursor: the same sound always lands on the same screen spot, whatever the screen size, calibrated to your own voice. This page covers:
- the mapping;
- its honest limits;
- where the maths runs and what the protocol needs;
- how it fits the existing modes;
- the calibration recording;
- a cheap test to run before building anything.

**Summary.**
- **Y comes from pitch.** Semitones are scaled to your calibrated comfortable range.
- **X comes from the vowel,** via the second formant F2: "ee" right, "ah" centre, "oo" left.
- **Accuracy is coarse.** Realistically the voice alone lands on about **6–9 rows × 3 columns**. That is too coarse to hit a button on its own.
- **Precision comes from snapping.** The design gets its accuracy by snapping to the tappable elements Canti already lists (the intent cursor's targets), with a zoom step as the fallback.
- **Hums carry almost no vowel.** Your existing hums show no usable X signal (measured below), so X needs an open-mouth vowel.
- **Everything is relative to the person.** Rows come from *your* range and *your* repeatability. Vowel centres are learned per person and per pitch band. Each band decides for itself whether sideways is **vowel** or **snap to elements**, where height picks a screen band and short hums step through the elements in it.
- **Many voices, measured** (Hillenbrand speech, VocalSet singers, MLEnd hums; see [Many voices](#many-voices)):
  - vowels read well in speech up to about 250 Hz;
  - trained singing degrades above about 400 Hz and is near chance above 550 Hz;
  - so the snap fallback is a main path, not a corner case.
- **Test 1 (2026-09-27) came out NO-GO, mostly because of the test itself** (see [Test 1](#test-1-vcursor-1-what-the-test-got-wrong)):
  - a falsetto "highest note" stretched the range;
  - vowel takes were filed under the band they were prompted for, not the one they were sung in;
  - the tracker read some "oo" F2s as F3;
  - breath thumps cut some low takes short.
- **Next step:** test v2 (spec `extractor/prompts/voice_cursor_v2.json`). It adds a live pitch meter and measures the levels twice: blind, and with the meter.

## Joystick cursor (decision 2026-09-27)

> Does this setup also improve the gesture extractor? Tested on the desktop: not yet. Every per-person `vx_config` override is NO-GO on the data we have, and there are no labelled hums. See [Calibration vs gesture labels](calibration-gestures.md).

**Status: desktop prototype built (`extractor/joystick.py`). The first live try failed on up/down (see [Live test 1](#live-test-1-2026-09-27-down-was-nearly-impossible)); the prototype now has three vertical modes to compare live, "home" (formerly "mid") by default. After [Live test 2](#live-test-2-2026-09-27-fun-but-not-calibrated-for-my-voice) the setup is personal: home note, voicing threshold, range without creak, vowels and pops. No app, firmware or protocol code has been written. The port plan is at the end of this section.**

### How it moves

| | Rule | Default (spec `extractor/prompts/joystick_v1.json`) |
|---|---|---|
| **Up / down** | Three modes, keys **1 / 2 / 3** (spec `vertical`). **1 home** (default; was "mid"): the pitch offset from the user's **home note**, their relaxed hum from the setup, which then follows the median start note of their last 9 hums (at most ±2 st from the setup's); without a setup hum, the middle of the range. Above = up, below = down, further off = steeper. **2 glide**: the direction the pitch **moves**: a glide up adds up, a glide down adds down, a held note keeps its direction (momentum); glide back to stop. **3 start**: the offset from the note **this sound started on** (the first prototype). | home: dead zone ±**1.0 st**, full speed at 0.7 × the room between home and that end of the range, per side. glide: counts only changes ≥ 0.8 st per 150 ms; 2.5 st = full; momentum dead band 0.5. start: dead zone 1.0 st, full at 4 st |
| **Sideways** | The vowel: **ee = right, oo = left, ah = none**. Soft weights over the three vowel centres in (F1, F2) Bark, x = w_ee − w_oo. | Dead zone 0.35, full at 0.8; σ 1 Bark |
| **Diagonal** | Both at once (e.g. "ee" sung 2 st above the start note goes up and right). Any direction works; the direction's length is capped at 1. | |
| **Speed** | **Ramps up while the sound lasts:** 80 dp/s at first, rising to 600 dp/s over 1.2 s, times the direction's length. The ramp resets after 150 ms of no direction. | A nudge ≈ 10–25 dp, a 1 s sound ≈ 300 dp, the 914 dp screen height ≈ 2 s |
| **Stop** | The cursor moves **only while the sound lasts**. A sound **starts** on clear voice (clarity ≥ the person's threshold, 0.78–0.82, default 0.80) and **continues** through ticks that are loud, near its pitch (±3 st) and at clarity ≥ 0.6 (hysteresis). It ends after 200 ms with neither; the cursor then stops where it was **80 ms before the last voiced tick**, which undoes the release's pitch fall. | `end_gap_ms` 200 (was 100), `clarity_continue` 0.6, `rewind_ms` 80 |
| **Magnet** | On stop, the element whose bounds are nearest the cursor, if within **48 dp** (0 when inside; the smaller element wins a tie), is highlighted and the cursor snaps to its **centre**. Nothing within reach: it stays exactly where it stopped. | `snap_dp` 48, `centre_max_dp` 96 |
| **Click** | A pop clicks at the cursor (the highlighted element's centre when snapped), once the 600 ms pop-pop gap has passed. Two detectors run side by side and a pop heard by both counts once: the extractor's (label "pop") and a tick-level one (`PopDetector`, spec `pop`) whose thresholds the setup's 3 pops can tighten. SPACE also pops. `pop pop` stays "listen" with the intent cursor's numbered targets, unchanged. | `pop_seq_gap_ms` 600 |
| **Position** | Never reset by a sound, a pop, or leaving and re-entering cursor mode. Only an explicit **recentre** moves it. A **rotation** keeps the same coordinates, clamped into the new screen. | |

**Onset.**
- A sound starts after 3 voiced 20 ms ticks, so a pop or a thump never starts one. In mid and glide modes it moves 60 ms after onset.
- Start mode only: the start note is the median of the first 120 ms window, at least 60 ms after onset, that stays within ±0.5 st. Nothing moves before that (about 180 ms). Within 600 ms of onset, a new settled note **6 st or more** away replaces the start note and undoes the motion since.
- Mid and glide modes: within 600 ms of onset, a note that settles **6 st or more above** the sound's first frames undoes the motion so far (an onset creak or scoop from below). Only from below, and only that large, so a deliberate early step either way is never undone.
- A frame more than 5 st off the running pitch is ignored unless it lasts 100 ms (octave errors).

**Why these defaults.** They are proposals, and every number is in the spec, not the code.
- **Dead zone 1.0 st** ≈ 3 × test 2's 0.32 st RMS error with the meter.
  - On the user's held notes in vcursor-2, the steady parts stay well inside even ±0.5 st, so wobble is not the limit.
  - What moves a held note is real pitch jumps: the onset creak and scoops below. The re-anchor rule is for those.
  - 1.0 st leaves margin for intent. A deliberate step of a tone or more moves, and vibrato (about ±0.5 st raw) does not.
- **Ramp, not constant or loudness:**
  - Constant speed forces one trade-off on every move. Sporka's fixed-speed melodic mode made every user overshoot (see [Y: pitch, as a position](#y-pitch-as-a-position)).
  - Loudness is a poor second control: louder notes go sharp, and loudness changes with mic distance and the Pico's gain.
  - A ramp while held is the MouseKeys pattern. Short sounds are precise, long ones travel, and nothing else has to be controlled.
  - The cost: at full speed a 250 ms reaction overshoots by about 150 dp. So far moves take a stop and then a short correction; the task mode counts both.
- **48 dp magnet:**
  - It is Android's minimum touch target (about 7.6 mm) and about an adult fingertip pad (8–10 mm = 50–63 dp).
- **Centre only for small elements (my change to the literal rule; confirm or overrule).**
  - An element with a side over 96 dp (a list row, a panel) is highlighted, but the cursor does not jump to its centre. If it stopped on the element it stays there; if it stopped just outside, it moves 8 dp inside the nearest edge.
  - Why: in the prototype, stopping inside a 411 × 394 dp list 15 dp below a 48 dp toolbar button threw the cursor about 190 dp to the list's centre, and every correction started from there again. The target was never reached.
  - `centre_max_dp: null` restores "always the centre".

**Findings from the user's own vcursor-2 takes** (the joystick engine run over them locally; aggregate numbers only):
- **Vowel centres have to be the person's, per mic.**
  - With the default centres (Hillenbrand adults), 47% of the user's "ah" frames read as "oo", so the cursor would drift left.
  - With the user's own centres, "ah" gives 0% sideways, "ee" 99% right, and "oo" 71% left (25% right).
  - So the prototype has a **10-second vowel setup** (key `v`: hold ee, ah, oo about 2 s each) that saves the three centres. It can also take them from a voice-cursor score (`--vowels recordings/vcursor-2`).
  - This contradicts "no calibration" for the vowel axis only. The pitch axis needs none.
- **A closed-mouth hum steers sideways.** Hums read as "oo"-like: with the user's centres, the median sideways drift over a held hum is about 200 dp. To go straight up or down, sing "ah". A hum-means-no-sideways rule would need a hum detector; it is not built.
- **Onset creak.** 4 of 12 blind level takes start with 0.2–0.5 s of creak 7–18 st below the note. Raising the re-anchor window from 400 to 600 ms cut the p90 vertical travel of those held notes from 985 to 360 dp.

### Live test 1 (2026-09-27): down was nearly impossible

The user's words: "i cant really move the cursor below half way.. and it doesnt move from the top edge/corners, its really weighted for higher pitches. going left/right is kinda hard".

The saved task (desk mic, start-note mode, the user's vcursor-2 vowel centres; numbers only): **0 of 11 targets hit**, all 30 s timeouts, a median of 12 sounds per target, and no click attempted.

What caused it, checked against the user's vcursor-2 session (aggregate numbers only):

| Suspected cause | Verdict | Evidence |
|---|---|---|
| **The start note sits at the bottom of the range** | **Confirmed: the main cause** | The user's range is 9.0–21.9 st (92–195 Hz), and the home note is **10.2 st, 1.2 st above the bottom** and 11.7 st below the top. A hum starts near home, so "below the start" has 1.2 st of room. Minus the 1.0 st dead zone, that leaves 0.2 st: **7% of the speed at best**, and only while straining at the bottom. Up has 12 st. At the top edge nothing brings it back down. |
| The re-anchor rule cancels deliberate early drops | Mostly not | A drop can't reach 6 st from a start 1.2 st above the bottom. It could cancel an early leap of 6 st or more up. |
| Octave errors or creak at the low end read as high | Partly | Low takes (median within 3 st of the bottom): **6.4% of frames** read more than 5 st above the note (1.2% on high takes). Most bursts are 20 ms (p50), which the 100 ms jump guard drops, but 9 bursts in 24 takes lasted 100 ms or more and passed. |
| The vowel centres come from another session and mic distance | Plausible, not measurable | The live task used vcursor-2's centres. There, "oo" was 71% left even in-sample. |

The creak itself **is not low-clarity**. Onset frames far below the note have clarity p50 0.92, and the steady note 0.94; both pass the 0.8 voicing gate. So a "replace the onset only if it was low clarity" rule would never fire on this voice. The onset rule uses the direction (from below) and the size (6 st) instead; `vertical.onset_undo.clarity_max` can add a clarity condition.

**The fix: three vertical modes, to compare live (keys 1 / 2 / 3).**
- **1 mid (default).** The reference is the middle of the user's range (15.4 st for the user), so there is the same room both ways (±6.4 st). The range comes from the setup's 5 s glide, or from a voice-cursor score. A strip at the phone's right edge shows the range, the middle with its dead zone, and the live pitch, like the meter in the v2 test.
  - The cost: the user's natural hum (home, 10.2 st) is 5 st below the middle, so it moves down at nearly full speed. To go only sideways, sing at the middle.
- **2 glide.** No range, no calibration. On the user's held notes (level takes), 10 of 12 stay still, but the vowel takes' onset scoops of a few st read as glides: the p90 vertical travel of a held vowel take is 812 dp (3 start: 668 dp).
- **3 start**, kept to compare.

Synthetic check (`--source fake --headless`, 3 seeds × 30 targets; a "low" fake voice with the user's range, every hum starting 1.2 st above its bottom, no note outside the range):

| Fake voice, mode | Hit | Time median (p90) | Targets **below**: hit, median time | Targets above: hit, median time |
|---|---|---|---|---|
| free voice (the old fake), 3 start | 89/90 | 4.0–4.3 s (4.8–8.1) | 40/40, 4.1–4.2 s | 39/40, 4.0–5.0 s |
| **low voice, 3 start (the bug)** | 85/90 | 4.5–8.1 s (18.6–24.0) | **36/41, 11.4–17.1 s** | 38/38, 4.1–4.4 s |
| low voice, **1 mid** | 86/90 | 3.8 s (4.4–8.1) | 37/38, 4.0–4.2 s | 36/39, 3.9–4.0 s |
| low voice, **2 glide** | 87/90 | 3.7–4.0 s (4.4–6.2) | 39/40, 3.8–4.0 s | 38/40, 3.7–4.2 s |

- It reproduces the bug: with the old rule, targets below take about 3× as long and some are never reached. Mid and glide remove the difference.
- The fake singer's pitch is exact, so glide looks as good as mid here. On the user's real held notes it drifts more (above).
- The misses in mid and glide are the fake policy getting stuck on 24 dp targets nested inside a bigger element, not the mode.

**Left / right.** The prototype now starts with a setup on the mic (skip with `--skip-setup`): a 5 s range glide, then ee, ah, oo about 2 s each. It then prints each vowel's per-frame right / none / left share with the new centres. If "ah" steers sideways in more than 10% of its frames, the vowel dead zone is widened, up to 0.7.
- A bug found on the way: the vowel setup moved on after 80 frames while the vowel was still sounding, so the tail of "ee" was collected as "ah" (and "ah" as "oo"). On a synthetic voice, "oo" read 63% left in-sample; with the fix, it reads over 80%. The setup now waits for a 200 ms silence between vowels.
- The user's live test did not use the setup (no vowels file was saved); it used vcursor-2's centres.

### Live test 2 (2026-09-27): "fun, but not calibrated for my voice"

The user's words: "the controls are pretty fun. I just wish it was more calibrated for my voice", and about clicking: "mainly just steer i tried popping but didnt seem to work".

The saved task (home mode, then called "mid", desk mic, the setup's range and vowels; numbers only): **0 of 12 hit**, 8 passes over a target, 2 clicks (both off target), a median 7.5 sounds per target. The trace (435 s, per tick) was replayed offline; aggregate numbers only.

| Suspected cause | Verdict | Evidence |
|---|---|---|
| **Hums get chopped** | **Confirmed**, and it is mostly creak | 131 "hums" in 435 s, median 420 ms. The voice drops out for short gaps: 280 of 289 short-gap ticks are loud (+10 dB) but "unclear" (clarity p50 0.74, under the 0.8 gate). Gaps of 60 ms or less never ended a sound; the chop was the 80–200 ms gaps with end_gap 100 ms. They cluster where the pitch goes down into **creak** (the pitch before a gap: median 4 st, ~70 Hz). |
| **The mid reference is off for this voice** | **Confirmed** | Mid of the setup range = 13.4 st, but the user's hums start at a median of 8.4 st and the setup vowels were sung at 11.3 st: 55% of voiced moving ticks read "down", 36% "up". The p5 of 2.2 st is **creak, not octave errors** (1 of 39 low runs is octave-related; creak jitters 0.4 st per tick against 0.06 on a held hum; F1 near 1 kHz): 18% of voiced moving ticks, and the last ~50 s of the test is a stream of short creak "hums". |
| **Pops were tried and not heard** | **Confirmed** | 2 clicks came through (bursts of 34 and 9 dB over the floor). Pop-shaped bursts that did not click: 32 dB (while snapped on an element), 12 and 16 dB, 10 dB, and maybe two near creak. The trace has no audio and did not log extractor events, so which extractor rule rejected each can't be proven. On the user's guided-1 pop takes the extractor says "pop" for 5 of 11 (mostly "hiss": the user's pops are loud, 38–42 dB, with long tails). |
| **oo (left) rarely shows** | **Not confirmed** | While moving: left 29%, none 44%, right 26% of voiced ticks; the cursor moved 3493 dp left and 3577 dp right. F1 does drop with pitch (Bark 4.85 at 6–10 st, 4.0 at 17–25 st), but "oo" still reads left. No multi-pitch vowel setup. |

**Changes** (spec `extractor/prompts/joystick_v1.json`, code `joystick_core.py` / `joystick.py`):
- **Hysteresis:** a sound starts at clarity ≥ the person's threshold and continues at ≥ 0.6 (the extractor's own voiced threshold, under creak's 0.66–0.74) when loud and within 3 st of its pitch; a loud tick far from any voice reaches 0.76 (p95), so it may only continue, never start. **end_gap 100 → 200 ms:** with the continue rule, the user's gaps split into ≤ 200 ms (195) and > 300 ms (104), with only 7 in between. The speed ramp carries through a gap; the cost is a snap and pop 100 ms later.
- **Home reference:** the setup's relaxed hum, then the median start note of the last 9 hums, at most ±2 st from it. Full speed per side = 0.7 × the room to that end of the range.
- **Tick pop detector** beside the extractor's, dedupe within 400 ms; every extractor event and pop-detector burst now goes into the trace.
- **The setup** (about 20–25 s; keys h / g / v / o, s = all), each step's clock starting on the first **steady** voiced run (8 ticks moving ≤ 0.35 st/tick; in live test 2 creak blips started the 5 s glide's clock before the glide):
  1. **Relaxed hum**, 3 s, "the note that comes out without thinking" → home = the median of its steady ticks; the voicing threshold = the 10th percentile of its loud pitched ticks' clarity − 0.05, within 0.78–0.82 (≈ 0.81 for this user, so little change for them: the hysteresis does the work).
  2. **Range glide**, 5 s → the 5th / 95th percentile of the steady ticks. The steady filter keeps 0 of 724 creak ticks (< 6 st) of the trace and 86% of the rest. Home is kept ≥ 1 st inside the range.
  3. **ee, ah, oo**, 2 s each, as before.
  4. **Three lip pops** → the 3 strongest pop-like bursts set the tick detector's peak and rise thresholds to half the weakest's, never below the defaults; the extractor labels ("pop" or "click") at least 2 of them got are accepted too. It prints "heard n/3". Under 2 of 3: the defaults stay.
  - Saved as numbers in `range.json` (range, home, threshold), `vowels.json`, `pops.json`; `--skip-setup` reuses them all.
- **"no pop? press SPACE (= pop)"** shows in the panel until the pop setup has heard at least 2 of 3.

**Replay of the live trace, before → after** (the same ticks; balance with the corrected up/down labels):

| | Before | After |
|---|---|---|
| Hums | 131 | **91** |
| Median hum length | 420 ms | **660 ms** (p90 2540) |
| Hums under 200 ms | 41 | 8 |
| Up / still / down of voiced moving ticks | 36% / 9% / 55% (mid 13.4 st) | 42% / 12% / 46% (home 11.3 st, adaptive); 46% / 7% / 47% with a fixed home |
| Vowel share left / none / right | 29% / 44% / 26% | unchanged (the gating does not change the vowel read) |
| Pop-shaped bursts caught | 2 clicks | **7** by the tick detector (all the bursts above), 0 in the setup parts of both traces |

- Setup range with the steady start, on the same setup: 8.3–18.9 st (saved then: 7.8–19.0).
- **The pop trade-off, measured** on the user's guided-1 and vcursor-2 takes. Default thresholds (8 dB peak, 5 dB rise): 10/11 guided pop takes, but also tongue clicks (click-click 10/10), 5/11 "clean" phrases (plosives), 4/42 whistle onsets and 2/70 hum takes. Calibrated from loud pops like guided-1's: peak 19 / rise 8 → 9/11 pops, false: 0/11 phrases, 1/10 tongue clicks, 1/42 whistles, 0/70 hums, but only the two live attempts over 30 dB. So pop in the setup the way you will pop in use. Looser than the defaults (6 / 3) added 6 detections inside the creak stream, so the defaults are the floor.
- Tongue clicks count as pops at the defaults; in the app, click click = home. It only matters once the joystick moves to the app.

**Indicators (approved 2026-09-27 as mockups, now drawn in the prototype at the approved size, 4 device px per art px):**
- **Cursor B, the chevron trail:** a pixel ring; 1–3 chevrons run ahead in its heading (8 directions) by thirds of the speed ramp (80–253, 253–427, 427–600 dp/s); voiced but still = four crosshair ticks; stopped = the ring; snapped = corner brackets around the element.
- **Face A, the bar**, on the Canti badge (top right of the phone): the bar steps with the **real** vertical offset (home or start: 4 equal steps from the dead zone to full speed; glide: the momentum), `[----]` in the dead zone, an arrowhead when the pitch is outside the range, a side pointer for ee / oo, a dashed line when not voiced.
- They replace the edge pitch strip; key **d** brings back the debug view (strip, old dot, reach ring). Code: `extractor/joystick_ind.py` (the mockup's drawing code, numpy only); the badge bodies are pre-rendered by it into `extractor/assets/joystick_badge.npz` (brand `canti_sprite`, needs pillow).

### The desktop prototype

```bash
cd ~/VOX/extractor
./run python joystick.py --task 12 --trace                           # setup (hum, range, vowels, pops), then the task
./run python joystick.py --task 12 --trace --skip-setup              # reuse the last setup
./run python joystick.py --vowels recordings/vcursor-2 --skip-setup  # no setup: range and vowels from the v2 session
./run python joystick.py --source fake --task 12                     # watch a SYNTHETIC singer do the task
./run python joystick.py --source fake --task 30 --headless --mode start   # self-test, no window (~5 s)
```

- **What you see:** a phone (411 × 914 dp) showing a harvested **emulator** screen (screenshot plus clickable bounds, from `finetune/data/real-targets-v2/emulator`; 585 screens, not Z Flip data).
  - Cursor B and the badge's Face A (see [Live test 2](#live-test-2-2026-09-27-fun-but-not-calibrated-for-my-voice)), the path of the current sound, the highlighted element (green) and the task target (yellow).
  - Key **d**: the debug view instead: the old dot with its 48 dp reach ring and a **pitch strip** at the phone's right edge (the range, home and its dead zone or the start note, the live pitch).
  - A side panel shows the vertical mode and a **debug HUD**: pitch in Hz and st, the reference (home, the start note, or the glide momentum), the vertical velocity, the vowel read with its weight, the phase, an EDGE flag, and **why the last sound stopped** (quiet, unclear, no pitch, mode off). It also shows the offset bar, the ee/ah/oo weights, the speed and a log.
  - Add `--device alsa_input.usb-CMEDIA_Q9-1-00.mono-fallback` if the default source isn't the Q9.
- **Keys:** 1 / 2 / 3 = vertical mode home / glide / start, space = pop by key, c = recentre, m = cursor mode on/off (the position is kept), r = rotate (clamped), n/p = screen, t = task, d = debug strip, h = home hum, g = range glide, v = vowels, o = pops, s = the whole setup, q = quit. When a setup step fails, it shows why and waits: **R** retries the step, **S** skips it and keeps its defaults (the skip is saved as `"skipped"`); see [Calibration vs gesture labels](calibration-gestures.md#setup-retry-or-skip-never-skip-by-itself-user-rule-2026-09-27).
- **Files** (numbers only, gitignored under `extractor/recordings/joystick/`):
  - `range.json` (the range, home and the voicing threshold);
  - `pops.json` (the pop thresholds, the extractor labels accepted, how many of 3 were heard, each pop's burst length `ticks` and the extractor's reading of it, `extractor_raw`);
  - `vowels.json` (centres, dead zone and per-vowel accuracy);
  - `task-<time>.json`, also written when you quit mid-task (the target on screen is kept as `quit: true`). Each trial records the modes used and the target's direction from the start, and the summary splits times into targets below, above and level.
  - `--trace` writes `trace-<time>.jsonl`, one line per 20 ms tick: f0, st, clarity, level, floor, why unvoiced, F1/F2, vowel weights, the mode, the reference, the offset, the momentum, the direction, the speed, the position, the phase, the snap, home, the voicing threshold and any events (hum start/end, clicks, every pop-detector burst with its features, every extractor event with its label).
- **The task** (`--task N`):
  - N random clickable elements, one at a time: 24 dp or more on a side, no containers, at least 150 dp from the cursor. Each is on a random screen, and the cursor keeps its place.
  - Per target it measures: **time** to the click on it (including the 600 ms pop gap), **misses** (a click on nothing), **false clicks** (a click on another element), **overshoot** (per sound that came within 48 dp of the target, how much further it stopped than its closest point), sounds used, and **not reached** (30 s timeout).
  - Numbers only (no audio) are saved to `extractor/recordings/joystick/task-<time>.json`, which is gitignored.
- **The code split:** `joystick_core.py` (Analyzer, Mover, magnet, Clicker, PopDetector) is the part meant for the app. It reuses `voice_cursor_test.py`'s per-frame pitch and formant maths under voice_cursor_v2's settings, plus a streaming form of the F2 continuity filter. `joystick.py` is the window, sources, task and fake singer.
  - Pops come from the real extractor (`vox_extract`, the same detector the Pico runs) and from the tick-level `PopDetector`.
  - tkinter is borrowed from nixpkgs at start-up, because the venv's Python has no `_tkinter`.
- **Tests:**
  - `tests/test_joystick.py` has 23 tests, and they pass (the 5 newest cover retry and skip):
    - the streaming and batch F2 continuity agree;
    - a steady note stays still;
    - pitch up moves up and stops at the sound's end;
    - ee/oo steer;
    - home mode moves the same both ways;
    - **a voice starting 1.2 st above its bottom reaches down in home mode and not in start mode** (the live bug);
    - glide keeps its direction while held and stops on a glide back;
    - an onset from far below is undone, and an early 4 st step is not;
    - the stop reason is reported;
    - the setup measures home, the voicing threshold, the range, the vowels and the pops, saves them and `--skip-setup` loads them; a quit task keeps its partial trial;
    - the steady filter drops creak from the setup;
    - after the pop setup, a pop heard by both detectors clicks once;
    - a creak-like dropout continues a sound, and unclear noise never starts one (live test 2);
    - the tick pop detector hears a pop but not a hum onset, a plosive or a sustained noise;
    - the position survives a mode toggle and is clamped on rotation;
    - the magnet rules;
    - the pop gap;
    - the end-to-end fake task.
  - The whole extractor suite passes: 104 passed, 8 xfailed.
- **Self-test** (`--source fake --headless`, 5 seeds × 30 targets, first version, start mode): **150 of 150 hit**, time median 3.9–4.1 s (p90 4.5–7.9 s), 0 misses, 0 false clicks. That fake voice could sing any pitch, so it hid the live bug. The mode comparison with the "low" fake voice is in [Live test 1](#live-test-1-2026-09-27-down-was-nearly-impossible). After live test 2 (seed 1, 30 targets, low voice): home 30/30 (median 3.8 s), glide 30/30 (4.1 s), start 29/30 (6.5 s); each fake pop is heard by both detectors and clicks once.
  - The fake singer is a closed-loop pipeline test, not a human model. It sees the cursor 250 ms late and leads it by its speed.
  - Its first versions exposed the magnet trap above, a noise floor that a long note raised over itself (fixed: the floor now learns only from non-periodic ticks), and early deliberate steps being taken for onset blips (fixed: 6 st).
  - Human numbers come from the user's run.
- **Not tested here:** the live desk-mic path, since I did not capture the user's room. It uses `record.PwSource`, the same reader the recording tools use.

### Calibration v2 (2026-09-27)

**Status: built on the desktop (`extractor/joystick.py`, `joystick_core.py`) and ported to the app (`joystick/CalibV2.kt`, `JoyCalibration.kt`, `PhoneMicSource`), with parity goldens. Not yet tried on the phone.** The protocol is in `android/PROTOCOL.md` ("Voice joystick", Calibration; "Phone microphone", Guards). The numbers below come from `extractor/eval_real/level_gate.py`, whose output is `extractor/results/level_gate.md`. They are aggregates only.

**Steps.** The setup runs hum, glide, vowels, pops, **clicks** (3 tongue clicks, 2 needed), **whistle** (a 5 s whistle glide), **hiss** (2 "tss") and **room** (3 s of quiet). Every step keeps the fail → retry / skip rule, with a reason that says what to change. A profile is now format version 2. A version 1 profile still loads and drives the cursor, but it shows `needs_recalibration` and lists the 4 missing steps.

**The level gate** (phone and USB mics only, never the Pico):
- **What it drops.** An extractor pop, click, hiss or (in the app) `unknown` that misses **either** the SNR threshold or the level threshold is dropped. It is logged `ignored{reason: "below level gate"}`.
- **Where it runs.** The gate is in the app, after the extractor; the extractor config is unchanged. It runs before the joystick filter and before personalization. So a quiet keyboard tap can't be relabelled into a trained click by the gesture matcher.
- **Thresholds.** There is one pair per mic:
  - start from the weakest calibrated pop, click or hiss, minus 8 dB for SNR and 8 dB for level;
  - raise to the room step's loudest transient + 3 dB;
  - cap at the weakest − 1 dB, so a calibrated sound always passes.
- **Uncalibrated default.** A mic whose clicks step was never measured uses 12 dB SNR and −45 dBFS.
- **Settings.** `level_gate` (on by default) and `level_gate_offset_db` (−10..+10; + is stricter).
- **Why 8 / 8.** On the guided desktop takes, a held-out real sound sits below the weakest calibrated one by up to 5.5 dB at p99 and 8.6 dB at worst. 8 dB leaves 2.5 dB over that p99, and the pool has only 13 attempts. Over 400 simulated leave-out setups the gate loses **0.26 %** of real sounds and drops 2.4 % of the desktop noise. An SNR margin of 6 loses the same amount and drops more noise (10.8 %), but it sits only 0.5 dB over the p99.
- **Default gate on real data.** On the guided desktop takes it loses 1 of 49 real discrete sounds (an 8.6 dB click). On one phone event log (426 discrete sounds):

| | quiet events (< 15 dB) | 15–40 dB events | real pops (≥ 40 dB) |
|---|---|---|---|
| whole log | 243 of 245 dropped | 81 of 157 dropped | 0 of 15 lost |
| after the log's calibration | 203 of 203 dropped | 24 of 78 dropped | 0 of 15 lost |

  The phone's calibration pops were about 48 dB over the floor. A gate derived from pops alone would have been far too strict (about 40 dB). That is why the gate waits for the clicks step, whose deliberately soft sounds set the bottom.

**The click / pop relabel** (per person, only when confident):
- **The rule.** A feature (`dur_ms`, `snr_db`, `level_db`, `lf_ratio`) separates a person's pops from their clicks when every pop example sits on one side and every click example on the other, with a minimum gap. The rule needs at least 2 such features and 2 examples a side.
- **When it relabels.** A pop or click is relabelled only when every separating feature it has votes for the other label. Each relabel is logged `relabel{by: "click_pop_rule"}`.
- **How it tested.** Over 400 leave-out setups it made 967 relabels, all right and none wrong. All of them were pop → click on quick click runs.

**Whistle range:**
- **What the step gives.** It gives a second range with its own home. Above the split (halfway between the voice's top and the whistle's bottom), the cursor steers by the whistle's home and range.
- **The pitch ceiling.** At the voice ceiling of 1100 Hz, only 251 of 1243 guided whistle ticks were within 0.5 st; the rest were octave or twelfth errors. At 2600 Hz, 98 % were right, and only 26 of 8112 voice ticks changed. So ticks use 2600 Hz during the whistle step and for a profile that has a whistle range.
- **Sample rate.** The phone captures at 16 kHz (Nyquist 8 kHz), which is not the limit. Whistles over about 2.6 kHz are lost to the f0 ceiling in both the extractor and the ticks.
- **Rise and fall.** Scaling the rise/fall thresholds to the whistle range changes nothing on the guided whistles. Misses there are segmentation, not thresholds. Arch and dip were produced inverted, so they are not a threshold question either. This is a report only; nothing was changed.

### Port plan (not implemented)

**1. Pico streaming** (PROTOCOL.md change, firmware `vx_hold`):
- **Extend the hold messages.** In cursor mode with `cursor_style: joystick` (a new CONFIG field the app sets), the device:
  - sends `hold: "start"` at **voice onset** (3 voiced ticks, `"from": "onset"`) rather than after 300 ms steady;
  - then sends a new `hold: "tick"` message every 40 ms while the sound lasts;
  - then sends `hold: "end"` and the normal feature message as today.
  - The pop and every other gesture keep their feature messages. Gesture mode is unchanged: nothing is streamed.
- **The tick message** carries 2 ticks, 20 ms apart, per notification:
  ```json
  {"v":1,"id":2051,"hold":"tick","sound":57,"t_ms":82110,"k":[[131.2,0.93,-31.5,702,1180],[131.6,0.94,-31.2,698,1176]]}
  ```
  - Each tick is `[f0_hz or 0, clarity, db, f1_hz or null, f2_hz or null]`: the per-frame values after the Pico's voicing gate and F2 pick rule.
  - The streaming F2 continuity filter, the start note, the dead zone, the ramp, the rewind and the magnet all run on the phone (the Mover). So tuning never needs a flash.
- **BLE budget:**
  - About 110 bytes × 25 messages/s ≈ **2.8 kB/s**, one notification per message at the requested MTU 517.
  - BlueZ settles on an 18.75 ms connection interval (firmware README), about 53 events/s, so 25 notifications/s fits with margin.
  - At the default MTU 23, a message is about 6 fragments (150 notifications/s). There the device should drop to 10 Hz with 5 ticks per message, which costs about 100 ms of extra lag.
  - Latency: 20 ms tick + up to 40 ms batching + one connection interval ≈ 60–80 ms, plus the 100 ms smoothing.
- **Firmware work:**
  - The formant step: LPC order 18 with envelope peak-picking and the v2 broad-F2 rule. About 10–15 k instructions per hop, only in joystick cursor mode (see [Formant cost on the Pico](#where-it-runs)).
  - The tick emitter in `vx_hold`.
  - Parity vectors: whole takes through `check_extract.py`, since the continuity filter is stateful.
- **Hold end** stays the backstop: the phone ends a sound itself after 100 ms of unvoiced ticks. If ticks stop arriving (a link stall), it ends the sound after 300 ms and does not rewind.

**2. App side** (`Overlay.kt`, a new `JoystickMover.kt`):
- **Position:**
  - `showCursor()` (Overlay.kt:399) sets `x = screenW()/2f; y = screenH()/2f` every time the view is re-added, and `hideCursor()` removes the view when cursor mode ends. So today, **every re-entry recentres**.
  - Change: keep `x`/`y` across hide and show, initialised once. Add `recentre()` (a badge menu item and an app command). On a configuration change, clamp into the new `screenW()`/`screenH()`.
- **Moving:**
  - Today `move(direction, fast)` sets a constant velocity, and the Choreographer frame callback runs it until "stop", the screen edge or **`autoStopMs` (2500 ms)**. That is timer-driven, because the device only sends discrete events.
  - In joystick style, `JoystickMover` (a port of `joystick_core.Mover`, reading `joystick_v1.json` as an asset) consumes `hold` ticks. The frame callback only renders the Mover's position, interpolated between ticks.
  - The sound's end is the stop. `autoStopMs` stays only as the link-stall safety.
- **Magnet:** the clickable list the intent cursor already builds (`Targets.kt`, px → dp by `density`), highlighted with the existing `showTargets`/`selectTarget` overlay.
- **Click:** the existing cursor pop-click path, at the snapped centre.
- **Vertical mode:** port all three (a setting), with mid as the default until the live A/B says otherwise. The range is per person and per mic, like the vowel centres.
- **Style setting:** `cursor_style: steer | joystick`. Steer keeps today's `move_*` decisions. Both share cursor mode, the pop click, `pop pop`, hiss back and click click home.
- **Vowel setup:** a 10 s screen (ee, ah, oo) per mic, stored with the other per-person data ([personalization](personalization.md)).
- **Parity:** a Kotlin `JoystickMover` test fed the same tick streams as `tests/test_joystick.py`, which must give the same positions.

**3. Phone mic as the interim** (no BLE, no flash):
- The phone-mic path already runs the **same C++ extractor** through JNI (`audio/VxNative.kt` → `PhoneMessages.toProtocol`).
- Add the tick emitter and the formant step there first. The app then gets the identical `hold` tick messages from the phone mic, so the whole app side can be built and tried before any firmware change.
- **Caveats:**
  - The phone mic hears phone audio and room voices, and formants shift with distance, so the vowel setup is per mic.
  - Pops: phone-mic pops do nothing outside cursor mode ([D135](decisions.md#d135)), but in cursor mode a pop clicks from every source, so the click works.

## Mapping

### Y: pitch, as a position

- **Input:** f0 from the existing MPM pitch tracker, in semitones: `st = 12·log2(f0 / 55 Hz)`.
- **Scaling:** `y = 1 − clamp((st − lo) / (hi − lo), 0, 1)`.
  - `lo` and `hi` are the edges of your *comfortable* range from calibration, not your extremes.
  - Low notes are the bottom of the screen and high notes the top. The screen height only scales the 0–1 value, so any screen size works.
- **Daily re-anchor.** Your range shifts from day to day. Mahmud et al. found humming users had to re-pick their threshold pitch every day ([INTERACT 2007](https://opendl.ifip-tc6.org/db/conf/interact/interact2007-2/MahmudSKS07.pdf)).
  - So a **3-second "home note"** at the start of a session re-centres the range. The range keeps its calibrated width and only shifts.
- **Why this isn't the melodic scheme that lost** ([gesture vocabulary](gesture-vocabulary.md), "About 'move down on a low tone'"):
  - Sporka's *melodic mode* mapped absolute pitch to a *direction* at a fixed speed. That is rate control, so every user overshot ([Sporka et al. 2006](https://dcgi.fel.cvut.cz/wp-content/wpallimport-dist/publications/pdf/publications-2006-sporka-uais-acmp-paper.pdf)).
  - Here pitch sets a *position*, like a slider. The cursor sits where your note is and stops when you stop. The Vocal Joystick group used exactly this kind of 1-D vocal slider in VoicePen ([CHI'09](https://faculty.washington.edu/wobbrock/pubs/chi-09.03.pdf)).
  - The drift finding still applies, hence the re-anchor.

### X: the vowel, from F2

| Vowel (as in) | Mouth | F2 (typical adult male, Hz) | X |
|---|---|---|---|
| "ee" (see) | spread, tongue front | ~2200–2400 | right edge |
| "ah" (father) | open | ~1100–1300 | centre |
| "oo" (food) | rounded, tongue back | ~800–1000 | left edge |

- **Why F2:**
  - F2 is the front/back axis of the vowel chart, and it moves monotonically from "oo" through "ah" to "ee".
  - F1 is mostly open/closed. It adds little to a left-right axis, and it is the hardest formant to measure at high pitch.
  - So X uses F2 on a Bark scale, placed between your three calibrated vowel centres. Below the "oo" centre maps to 0, above the "ee" centre to 1, and linear between.
- **Why only three vowels:**
  - The Vocal Joystick used vowel quality as its steering signal. An 8-way vowel compass was learnable (recall was perfect by session 5).
  - But many users could not reliably produce some vowels, depending on dialect. The authors used a 4-way set for novices ([ASSETS'06](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf); [CHI'09](https://faculty.washington.edu/wobbrock/pubs/chi-09.03.pdf)).
  - Three corner vowels on one axis is the most robust subset.
  - We have no published per-frame vowel accuracy for the VJ engine: the HLT/EMNLP 2005 engine paper was not retrieved (see the research notes). The 5-minute test below measures it for you instead.
- **In-between vowels** ("eh", "uh") land between the columns. Whether you can hold them repeatably is the open question. The design assumes 3 columns, and 5 only if the test says so.
- **Per person, per pitch band.** The Hz values in the table are only a guide:
  - women's and children's formants sit 15–25% higher than men's (children's "ee" F2 is often above 3000 Hz, so the tracker's F2 ceiling is 3600 Hz);
  - a vowel sung high is not the same vowel sung low.
  - So calibration learns the three centres separately in your low, home and high band, and a note's X is read against the band its pitch falls in.

### Fallback: snap to elements (when vowels don't separate)

A band whose vowels don't separate for this person uses **snap** instead of vowel columns:
- **Height picks a screen band** (the rows as usual).
- **Short hums step** through the tappable elements in that band, left to right, then wrapping. A short hum is under 300 ms at any pitch, and the step is haptic.
- **Pop clicks** as usual.

This needs no vowel at all, so it also serves whistlers, closed-mouth hummers and high voices. It is the Dragon-style "pick a region, then cycle" pattern, on the target list Canti already builds.

**Who gets which** is decided by the calibration, per band, and never by voice type:
- `columns = vowel` if leave-one-take-out vowel accuracy in that band ≥ `vowel_acc_min` (0.9);
- otherwise `snap`.
- The rule and the threshold live in the spec file (`rules`), not in code.

### Onset, settling and release

A sung note has an unstable attack and a falling release, and both would throw the cursor.

| Phase | What happens |
|---|---|
| **Attack** (first ~100–150 ms) | Ignored. A pale *preview dot* appears only once pitch clarity ≥ 0.85 and formant quality are good for 3 consecutive 10 ms frames. |
| **Tracking** | The dot follows a smoothed value. Smoothing is a One-Euro filter on semitones and Bark: heavy when the voice is steady, light when it moves. Its time constant is about 60–100 ms. **Vibrato:** before any steadiness test, pitch and formants are averaged over ≥ one vibrato cycle (5–7 Hz, so `smooth_ms` = 200). On VocalSet vibrato long tones, this takes the pitch SD from 0.52 st to 0.06 st and the F2 SD from 54 Hz to 12 Hz. |
| **Settle** | When pitch stays within ±0.5 st and F2 within about ¼ of the ee–oo distance for **300 ms**, the dot *locks* (haptic tick, solid dot). |
| **Release** | On the sound's end, the position is taken from the window 250 ms to 80 ms **before** the energy drop. The ring buffer keeps it. This ignores the downward pitch slide at release. The cursor stays there after you stop. |

Latency from voice to dot: 10 ms hop + about 20–40 ms BLE + 60–100 ms smoothing ≈ **100–150 ms**. That is close to the Vocal Joystick's per-frame updates, and well under the "jerky, four times a second" Dragon cursor ([ASSETS'06](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf)).

### Resolution: how many spots are really there

- **Rows (pitch).**
  - Your holds are steady *within* a sound. Median pitch wobble on flat holds of 400 ms or more is **0.25 st** for hums (IQR 0.14–0.45, n = 166) and 0.20 st for whistles (n = 30), from your recordings.
  - The number that matters is *between* attempts: hitting the same note again from silence. It isn't measured yet, and it is typically larger (assume 0.5–1 st).
  - Rows are **per person**: `rows = floor(range_st / (4 × repeat_SD))`, capped at 9, with at least 2 usable. There is no fixed minimum range.
    - A 6 st singer with a 0.3 st repeat SD gets 5 rows; a 20 st singer with a 1 st SD gets 5 too.
    - MLEnd hummers use 9–17.5 st (p10–p90) in a single song. Their comfortable range is wider, so most people have room.
  - With your ~15 st, this gives **4–8 rows**, and 9 with good repeatability.
- **Columns.** Vowel bands get 3 columns, and 5 only if the in-between vowels test well. Snap bands have no columns: hums step through the band's targets instead.
- **Total:** about 12–27 zones. On a Z Flip screen (about 1080 × 2640 px) a zone is roughly 360 × 300–600 px. A 48 dp button is about 125 px. **So the voice alone cannot hit a button.** Two fixes, used in this order:
  1. **Snap to targets.** When the dot locks, it snaps to the nearest tappable element inside its zone. Canti already builds that list for the intent cursor (`Targets.kt`, the `targets` op). The snapped element's label shows next to the dot. Most screens have fewer than 30 targets, so a zone rarely holds more than 1–3.
  2. **Zoom (coarse grid, then refine).** With no single target in the zone, a second sung note within 1.5 s zooms in: the locked zone becomes the full pitch × vowel range. Two levels give about 150–700 spots.
     - This is the recursive-grid idea, and Dragon's recursive 3×3 Mouse Grid was *not significantly slower* than the Vocal Joystick for novices ([ASSETS'06](http://aiweb.cs.washington.edu/research/projects/aiweb/media/papers/vocaljoystick.pdf)).

## Limits, honestly

| Limit | Effect | Mitigation |
|---|---|---|
| **Hums and whistles carry (almost) no vowel** | Closed-mouth hums ("mmm") are nasal: F1 sits near 250–350 Hz and F2 wanders with no mouth shape behind it. A whistle is a single sine with no formants: the tracker finds formants in only 12% of MLEnd whistle frames. | X needs an open-mouth vowel. A hum or whistle moves **Y only**, and sideways is **snap**. |
| **Whistles are above the voice pitch limit** | 99% of MLEnd whistlers go above 1100 Hz (median range 1074–1841 Hz). | A whistle profile needs `f0_max_hz` ≈ 4000 (the M33 pitch search too). It is always snap. |
| **High pitch breaks formant tracking** | Once f0 approaches F1, the harmonics are too sparse for LPC, and the estimate snaps to a harmonic. Measured on VocalSet: 3-vowel accuracy has a median of 0.85–0.92 below 400 Hz, 0.73–0.82 at 400–550 Hz, and 0.42–0.53 above 550 Hz (chance is 0.33). | Per-band calibration: bands that fail use snap. Sopranos' upper range is almost always snap. |
| **Vibrato** | Raw pitch SD on a vibrato note is 0.5–0.6 st, over twice the row tolerance. | The 200 ms smoother (≥ one cycle) brings it to 0.06–0.12 st, as steady as a straight tone. |
| **Pitch drift and fatigue** | Voices drift over a day and tire over minutes. Several VJ users ran out of breath on long moves ([Mahmud et al. 2007](https://opendl.ifip-tc6.org/db/conf/interact/interact2007-2/MahmudSKS07.pdf)). | The daily home-note re-anchor. Positions are short notes (sing, lock, stop), not continuous steering. Snapping keeps the notes few. |
| **Noisy room** | Prior systems were "very sensitive" to background noise (same source). Other voices and TV speech carry vowels too. | Only in cursor mode (you entered it with the button). The preview needs high clarity. The Pico mic is closer to your mouth than the phone. |
| **Phone mic vs Pico** | The phone mic hears phone audio and room voices, and formants shift with mic distance and response. | Calibrate **per mic**. Position mode is Pico-first. The phone mic gets it only after the echo-cancel measurement (round 4). |
| **Dialect and accent** | Vowel positions differ per person, and some can't produce some vowels (VJ). | Your own calibrated centres, never fixed Hz values. Only 3 corner vowels. |
| **Singing ability** | Not everyone can hit a note again from silence (the reason the user kept humming for glides). | The go/no-go test measures exactly this. The fallback is the existing steering cursor. |

## Where it runs

**The measuring runs where the audio is. The mapping and the calibration run on the phone.** This follows the [personalization](personalization.md) rule: examples and thresholds live in the app, and re-calibrating needs no re-flash.

| | Pico (M33, 150 MHz) | Phone |
|---|---|---|
| Pitch | Already computed every 10 ms hop | Already in the Kotlin extractor port (phone mic) |
| Formants (F1, F2) | **New**, about 10–15 k instructions per hop (below) | Trivial |
| Mapping, smoothing, snapping, zoom, calibration | No | Yes |

**Formant cost on the Pico:**
- **Reuse the pitch path's autocorrelation.** The extractor already computes the frame's ACF by a 1024-point FFT for pitch. Lags 0–18 of it are all LPC needs.
  - Pre-emphasis is applied in the lag domain: `r'[k] = (1+a²)·r[k] − a·(r[k−1] + r[k+1])`, with a = 0.97.
- **Levinson-Durbin, order 16–18:** about 300–400 multiply-adds.
- **Formants by peak-picking the LPC envelope** at 128 frequencies up to 4 kHz: about 128 × 18 complex multiply-adds ≈ 5 k operations. That avoids polynomial root-finding.
  - F1 is the first peak in 200–1100 Hz with a bandwidth under 500 Hz. F2 is the next peak at least 150 Hz above it, in 600–3600 Hz.
  - **v2 changes to the picking rule,** after test 1:
    - **Broad F2 allowed.** An F2 with a 500–1000 Hz bandwidth is accepted if its envelope level is at least that of the next narrow candidate up. That is typical of a back vowel's F2 on a room mic.
    - **One-frame jumps refused.** A frame whose F2 is more than 500 Hz from the last accepted F2 is dropped, unless 5 frames in a row agree (a real vowel change).
    - **High-pass and level gate.** A 70 Hz high-pass comes first, and the level gate is 6 dB over the take's noise floor (was 10).
    - Why the first two: in v1, a broad F2 (the user's "oo" at 850–1100 Hz with a 500–1000 Hz bandwidth) failed the 500 Hz bandwidth test, so the next pole, F3 (~2200 Hz), was read as F2.
    - The envelope level is one extra polynomial evaluation per candidate on the M33.
  - The ceiling was 3000 Hz until children's "ee" was measured. Raising it lifted boys from 42% to 79% of talkers passing, and girls from 16% to 47%. Men were unchanged.
- **Total:** roughly **10–15 k instructions per hop**, about 1% of the 1.5 M-cycle budget. The whole extractor today runs about 205 k per hop (firmware README, M33 table).
  - Running it only in cursor mode keeps the gesture path unchanged.
  - The 512-sample (32 ms) pitch window is the right length for formants.

**Protocol additions** (PROTOCOL.md; only in cursor mode with `cursor_style: position`):

```json
{"v":1,"track":"voice","sound":57,"t_ms":82110,"f0_hz":131.2,"clarity":0.93,"f1_hz":702,"f2_hz":1180,"fq":0.8,"db":-31.5}
```

- **When:** sent every 20 ms (50 Hz) while a sound is open, then the normal end-of-sound message. This is the "STREAM" channel sketched in [phone control](phone-control.md) (10–30 Hz, pitch offset and voicing), extended with formants.
- **`fq`:** formant quality, 0–1, from peak sharpness and bandwidth. The app ignores X when it is low, e.g. on a hum.
- **Bandwidth:** about 110 bytes × 50/s ≈ 5.5 kB/s, fine for BLE with the existing fragmented notifications. 20–25 Hz would also do, given 60–100 ms smoothing.
- **Mode:** the device already owns the mode, so the Pico knows when to stream. `cursor_style` is a new config field the app sets through CONFIG.

## Interaction

| | How |
|---|---|
| **Enter / leave** | The device button, as today: a single click toggles cursor mode. A sound never switches modes ([gesture vocabulary](gesture-vocabulary.md)). A setting chooses the cursor style: **steer** (today's rise/fall/arch/dip moves) or **position** (this page). Position is unavailable until you calibrate. |
| **Place** | Sing a vowel. The preview follows, locks after 300 ms, and snaps to the nearest target (its label is shown). Stop singing: the cursor stays. |
| **Click** | **Pop = click** at the cursor (user decision 2026-09-27: pop keeps clicking in cursor mode, even with phone-mic pop→tap removed elsewhere). |
| **Name it instead** | `pop pop`, then say the element's name: the intent cursor, unchanged. |
| **Back / home** | Hiss = back, click click = home, as everywhere. |
| **Zoom** | A second note within 1.5 s of a lock zooms into the zone. |
| **Scroll** | Default: leave cursor mode (button) and use the scroll gestures. Option (off by default): a held note **above your top edge** or **below your bottom edge** (≥ 1 st past the range) for 0.5 s scrolls up or down until you stop, like eye-tracker edge zones. |
| **Whistle** | Moves Y only (no vowel). Sideways is snap. |
| **Snap band** (where your vowels don't separate) | Height picks the band. **Short hums step** through its tappable elements (the label shows, with a haptic tick). Pop clicks. |

**Coexistence.** Gesture mode is untouched: no stream is sent and no formants are computed. Steer and position share cursor mode, the pop click, the intent cursor's `pop pop` and the target list. Position just adds the stream and a different mover.

## Calibration

**What you record** (v2: about 9–10 minutes, 55 takes, once per mic). The steps, texts, analysis settings and rules are all in **one spec file**, `extractor/prompts/voice_cursor_v2.json` (`version` field). The desktop test reads it now, and the app's calibration will read it later.
- `voice_cursor_v1.json` is kept unchanged. A session is scored with the spec it was recorded with, so test 1 still scores exactly as before.
- **The live meter** is a vertical bar of your range showing the 5 level marks, the target line (yellow, green once you've held it 0.3 s) and a dot for your pitch now. It updates every 50 ms and uses the same smoothing as the scorer.

| Part | Meter | You do | It sets |
|---|---|---|---|
| Range | live | Glide "ah" from your lowest comfortable note to your highest, twice. Then hold each end for 2 s, in your normal voice | `lo`, `hi`, by the range rule below |
| Home note | live | Hum your easiest note 3 × 2 s | The middle of the screen, and the anchor for the daily 3 s re-anchor |
| **Check** | shows the result | Your measured low / home / high on the meter, plus any flag ("held high note is 14.6 st above the glide top: falsetto?"). **Enter** accepts it, **r** redoes the range and home note | The accepted range, kept in `session.json` |
| Levels, **blind** | hidden | 5 heights × 3, shuffled, from silence: 1 = your low end, 3 = home, 5 = your high end | The repeat SD → `rows_blind`: "same pitch = same spot" without looking |
| Levels, **with the meter** | target line | The same 15 prompts. Get the dot onto the line and hold it until it turns green | Time-to-target, final error, overshoot, never-reached → `rows_feedback` |
| Vowels | target line | Hold "ee", "ah", "oo" for 2 s at your LOW, HIGH and HOME note, × 2, shuffled. A take that lands in another band is flagged live, and you can redo it | The 3 vowel centres (F1, F2 in Bark) per pitch band, and per band: vowel or snap |

**The range rule (v2):**
- `top = min(glide top, held high note)` and `bottom = max(glide bottom, held low note)`.
- The glide edges are the 95th and 5th percentiles of *steady* glide frames. A steady frame is voiced, with the smoothed pitch moving < 0.3 st per 10 ms and the raw frame within 1 st of the smoothed one, so cracks and octave jumps drop out.
- A held note more than 5 st beyond the glide edge is flagged and not used.

**Takes are started and stopped by voice** (v2):
- A take starts after 3 voiced 50 ms ticks, and stops after 0.6 s without voice.
- In v1, any loud sound started a take. A breath thump on the mic could open a take, and the 0.6 s of quiet after it closed the take before the voice came.

Heights are never absolute notes. `pos` runs 0 (your low) → 0.5 (home) → 1 (your high), piecewise, so an off-centre home note is fine.

**Stored:**
- **On the phone:** a JSON calibration profile per mic source, next to the personalization enrollment: `{version, mic, date, lo_st, hi_st, home_st, vowels:{ee,ah,oo:{f1,f2,cov}} per pitch band, rows, cols}`. It carries only numbers, no audio.
- **On the desktop test:** the audio stays in `extractor/recordings/<session>/` (gitignored, never committed, never sent to any external model).

**Reuse for the gesture models** (the user's "record my voice to retrain"):
- **The range makes gesture sizes personal.** Your `lo`–`hi` span can scale the extractor's rise and fall size buckets ("small/medium/large" in semitones) and its f0 search limits to your voice. It also normalises the fp1 fingerprint's f0 statistics before [personalization](personalization.md) matching. Pitch ranges are still never a *gate* (voices differ too much).
- **The vowel holds are labelled open-mouth voiced sound.** That is exactly the "sounds like talking" material the model must learn to ignore in gesture mode, so the holds become personal negatives for the ignore set.
- **The calibration audio can be replayed.** It goes through `eval_real/` like the live sessions, so extractor changes are checked against your own voice.
- **Retraining the gesture model itself** on your data still only helps once the lines differ ([personalization](personalization.md): "Why not by retraining Jev"). The calibration improves the lines first.

## Cheap feasibility test first

### What your existing recordings already say

Run locally with a throwaway script (`scratchpad/vcursor/feas.py`), with nothing sent anywhere. It used LPC order 18 at 16 kHz on voiced frames only.

| | Result |
|---|---|
| Hum pitch used (median per sound, p10–p90) | 102–239 Hz = **14.7 st**, median 129 Hz (n = 2380 hum sounds). Median in-sound excursion 3.9 st |
| Whistle pitch used | 985–1762 Hz = 10.1 st, median 1389 Hz (n = 512) |
| Pitch steadiness on flat holds (within a sound) | Median wobble 0.25 st for hums, 0.20 st for whistles |
| Formants on hums (201 hum sounds) | F1 median **359 Hz** (the nasal murmur). F2 **wanders with a median SD of 378 Hz inside one sound**, though you weren't changing anything |
| Formants on speech (60 phrase takes) | F2 spans 1099–2615 Hz (p10–p90) as the vowels change |

**Reading:**
- The pitch side looks workable: a 15 st range and 0.25 st steadiness.
- A hum's F2 noise (≈380 Hz) is about the size of a whole vowel step, so **hums cannot drive X**, as expected.
- Open vowels do move F2 over a wide span.
- The recordings **can't** answer the two questions that matter:
  - whether you can hit the same note again from silence;
  - whether *deliberately held* ee/ah/oo separate cleanly across your pitch range.

### Test 1 (vcursor-1): what the test got wrong

This was your first run (2026-09-27, v1: 40 prompts, 50 recorded takes including redos). Only aggregate numbers are given here; the audio stays in `extractor/recordings/`.
- **The v1 score:**
  - range 28.4 st (88–453 Hz), home SD 0.69 st;
  - blind level repeat SD **4.0 st → 1 row**;
  - vowels: low –, home 100%, high 66%;
  - lock p90 1548 ms, 3 of 31 never settled;
  - **NO-GO**.

| Problem | Evidence | Fix (v2) |
|---|---|---|
| **Range top was a falsetto note** | The held "highest" came out 453 Hz, while the glides topped out near 195 Hz and level 5 averaged about 240 Hz. Levels 2, 4 and 5 were placed far too high: level 4's mean landed next to level 3's | The range rule above, and you check the range on the meter before the levels |
| **Vowel bands followed the prompt, not the pitch** | 7 of 17 scored vowel takes were sung in another band than prompted, e.g. two "high" takes at 111 and 128 Hz | Scored by the **measured** band; flagged live with a redo offer |
| **"oo" read as F3** | Two "oo" takes had F2 medians of 2552 and 2308 Hz. The real F2 (850–1100 Hz) had a 500–1000 Hz bandwidth and failed the 500 Hz test | The broad-F2 and continuity rules (above). The same takes now read 942 and 886 Hz |
| **3 low vowel takes had no pitch** | Their loud frames were breath/handling thumps (energy below 70 Hz, no harmonics). The take opened on the thump and closed on the quiet after it, before or just as the voice began. One more had a quiet 87 Hz voice just under the 10 dB level gate | Voice-triggered takes, the 70 Hz high-pass and the 6 dB gate. Two of the three stay empty (no voice inside the recording), and one comes back (87 Hz) |

**Test 1 rescored under v2** (`./run python voice_cursor_test.py --score recordings/vcursor-1 --spec voice_cursor_v2`; it writes `score_voice_cursor_v2.json` and leaves `score.json` alone):

| | v1 | v2 |
|---|---|---|
| Range | 28.4 st (88–453 Hz) | **13.5 st (89–195 Hz)**, falsetto flag: the held high note is 14.6 st above the glide top |
| Blind repeat SD → rows_blind | 4.02 st → 1 | 4.01 st → 0 (the narrower range makes it worse) |
| Vowel bands | low – (no reading), home 100%, high 66% | low 78% (7 takes), home 100% (3 takes, ee/ah only), **high 93%** (5 takes) |
| F2 wobble within a hold | 306 Hz (¼ ee–oo = 347) | **119 Hz** (¼ ee–oo = 371) |
| Lock p90 / never settled | 1548 ms / 3 of 31 | 1184 ms / 3 of 31 |
| Verdict | NO-GO (blind) | INCOMPLETE: v2 decides on the meter block, which test 1 didn't have |

**Reading:**
- The blind 4 st spread is real, not a scoring artefact: each level's takes were spread that far. It is also inflated by the test, because the level targets were abstract numbers built on a wrong range, and there was no meter.
- Your blind level 5 (~240 Hz) sat *above* the glide top (195 Hz). The glides were short (1.3–1.8 s for the second one), so the v2 range is probably too low at the top. The range check screen is where you'd see this and redo it with slower, fuller glides.
- The vowels came out better once bands follow the pitch and "oo" is read right: 2 of 3 bands pass 0.9.

### Test 2 (vcursor-2): NO-GO, and a test flaw

This was the v2 test with the live meter (2026-09-27; aggregate numbers only).

| Measure | Result |
|---|---|
| With the meter (the GO measurement) | Final pitch error **0.32 st RMS**, so rows_feedback **9**. But **4 of 15 targets were never reached**, and time-to-target p90 was **2410 ms**. |
| Blind | Repeat SD 1.86 st, so rows_blind 1 |
| Vowels (measured band) | low 100%, home 100%, high 91%: all three bands "vowel" |
| Verdict | **NO-GO** (never-reached 27% > 10%, p90 2410 > 1500 ms). The user chose not to re-run and moved to the [joystick cursor](#joystick-cursor-decision-2026-09-27). |

**Test flaw, for any re-run.**
- Only **1 home take was kept**, and home sat **1.2 st above the low end**. Because the level targets are placed piecewise around home, levels 1–3 were squeezed into **1.3 st** and levels 3–5 spread over 11.6 st.
- So the low targets were closer together than the pitch error.
- The fix, either:
  - require `hm`'s 3 repeats before the range check can be accepted; or
  - space the levels **evenly over the range** (lo..hi), with home used only as the re-anchor.

### Many voices

All of this was run locally on public datasets, using the scorer's own functions (`frames`, `vowel_windows`, `loo_vowel_accuracy` from `voice_cursor_test.py`) and the analysis settings from the spec. Only aggregates are printed. Datasets, licences and hashes are in `datasets/SOURCES.md`. Each table below names its command. Run them from `extractor/`; they read only `~/VOX/datasets`.

| Script | Reproduces | Time |
|---|---|---|
| `./run python eval_real/vcursor_hillenbrand.py` | the speech table and the speech fallback row (`--f2-max 3000` gives the before numbers for the F2 ceiling) | ~1 min |
| `./run python eval_real/vcursor_vocalset.py --only long_tones` | the singing table, the vibrato table and the long-tone fallback row | ~20 s |
| `./run python eval_real/vcursor_vocalset.py` | the "all a/i/u material" medians and fallback row | ~20 s |
| `./run python eval_real/vcursor_mlend.py` | the hums and whistles table | a few min |

**Tracker v1 vs v2 on the public sets.** The tables below were measured with the v1 tracker. Every script takes `--spec voice_cursor_v1|voice_cursor_v2`:

| | v1 | v2 |
|---|---|---|
| Hillenbrand talkers ≥ 0.9, men / women / boys / girls | 100 / 87 / 79 / 47% | 100 / 81 / 75 / 53% |
| Hillenbrand talkers ≥ 0.8, men / women / boys / girls | 100 / 96 / 83 / 63% | 100 / 91 / 88 / 84% |
| Hillenbrand, all talkers ≥ 0.9 (≥ 0.8) | 84% (90%) | 82% (93%) |
| Hillenbrand frame F2 gross error (> 25% off hand), /u/ men / women / kids | 2 / 5 / 9% | 3 / 6 / 6% |
| VocalSet long tones, singer-bands ≥ 0.9, by band < 200 … > 550 Hz | 50 / 47 / 36 / 20 / 0% | 60 / 45 / 27 / 10 / 0% |
| VocalSet long tones, singers with ≥ 1 vowel band at 0.9 (0.8) | 70% (95%) | 70% (100%) |
| VocalSet all material, singer-bands ≥ 0.9, by band | 55 / 55 / 40 / 33 / 0% | 64 / 65 / 55 / 25 / 0% |
| VocalSet vibrato F2 SD raw → smoothed | 54 → 12 Hz | 42 → 9 Hz |
| MLEnd hum / whistle spans and formant frames | as in the table below | the same within 0.3 st; hum F2 frames 89 → 83% |
| **Your test-1 takes:** "oo" F2 medians; within-hold F2 wobble; low-band accuracy | 2552 / 2308 Hz; 306 Hz; – | 942 / 886 Hz; 119 Hz; 78% |

- **Hillenbrand /u/ was never the problem.** It is lab-mic speech, with only 2–9% gross F2 error under v1. The failure only showed on your room-mic takes.
- **On the public sets v2 is a wash.** It is a little better at 0.8 and on all of VocalSet's material, and a little worse at 0.9 for Hillenbrand women (−3 talkers) and for the 300–550 Hz VocalSet long-tone bands (1–2 singers each). Every one of those cells rests on 10–47 people, so one person moves it 2–10%.
- **An ablation shows the cost is the continuity rule.** It drops frames, and in Hillenbrand's 50 ms windows a dropped frame counts as a miss:
  - without continuity, Hillenbrand is 85% (94%);
  - on your takes, without continuity the low band falls from 78% to 39% and the wobble rises from 119 to 295 Hz.
  - v2 keeps continuity, because your mic is the target.

**Speech: Hillenbrand et al. 1995** (135 of the 139 talkers have all three vowels measured; /hVd/ words, vowels ee/ah/oo). Command: `eval_real/vcursor_hillenbrand.py`.
- Frames are classified against *that talker's own* hand-measured vowel centres.
- The windows are 50 ms, because the vowels last only about 250 ms. That is harsher than the 250 ms windows the calibration uses.

| Group | Talkers | Median F0 | Median accuracy | Talkers ≥ 0.9 (vowel) | Talkers ≥ 0.8 | Median F2 error vs hand |
|---|---|---|---|---|---|---|
| Men | 45 | 133 Hz | 1.00 | **100%** | 100% | 29 Hz |
| Women | 47 | 225 Hz | 1.00 | **87%** | 96% | 43 Hz |
| Boys | 24 | 243 Hz | 1.00 | **79%** | 83% | 38 Hz |
| Girls | 19 | 238 Hz | 0.83 | **47%** | 63% | 57 Hz |

**Singing: VocalSet** (20 trained singers, 9 women and 11 men; files carry no voice types). Command: `eval_real/vcursor_vocalset.py --only long_tones`.
- Long tones on a/i/u, with 250 ms windows as in the calibration.
- Accuracy is leave-one-file-out, per singer and per F0 band, with centres learned in the same band.

| F0 band | Singers with notes there | Median 3-vowel accuracy (p10) | Singer-bands ≥ 0.9 (vowel) | ee-vs-oo only ≥ 0.9 |
|---|---|---|---|---|
| < 200 Hz (bass/baritone low) | 10 | 0.89 (0.84) | 50% | 50% |
| 200–300 Hz (tenor, alto low) | 19 | 0.88 (0.75) | 47% | 47% |
| 300–400 Hz (tenor high, mezzo) | 11 | 0.85 (0.69) | 36% | 45% |
| 400–550 Hz (soprano middle) | 10 | 0.73 (0.60) | 20% | 80% |
| > 550 Hz (soprano high) | 9 | 0.42 (0.26) | **0%** | 11% |

- Over all of VocalSet's a/i/u material (arpeggios and scales too), the medians are 0.91 / 0.92 / 0.88 / 0.82 / 0.53, in the same shape.
- **Where the reading breaks:** it degrades from about **400 Hz** and is near chance (0.33) above **550 Hz**. The "~350 Hz" rule of thumb is roughly right as the start of the slide.
- **Why singers score worse than speech even when low:** trained singers deliberately modify vowels, "oo" drifts toward "ah" and back, and the most common error is "oo" read as "ee" when F2 merges into F1. Casual users holding a spoken-style vowel should look more like Hillenbrand than VocalSet. That is a guess, and your own test measures it.
- **Vibrato** (VocalSet vibrato vs straight long tones; same command):

  | | Raw | After the 200 ms smoother |
  |---|---|---|
  | Pitch SD, vibrato | 0.52 st | **0.06 st** |
  | Pitch SD, straight | 0.08 st | 0.03 st |
  | F2 SD, vibrato | 54 Hz | 12 Hz |

  - So vibrato is a solved problem once smoothing spans a cycle. The cost is about 100 ms more lag before the lock.

**Hums and whistles: MLEnd** (226 hummers and 127 whistlers, 5 random songs each, first 12 s). Command: `eval_real/vcursor_mlend.py`.

| | Pitch span used in songs (p10 / median / p90) | Low end (median) | High end (median) | Frames with a formant reading |
|---|---|---|---|---|
| Hum | 9.0 / 12.5 / 17.5 st | 130 Hz (73–290) | 276 Hz | 89%, but hum F2 is noise (see above) |
| Whistle | 4.0 / 8.6 / 14.8 st | 1074 Hz | 1841 Hz | 12% |

- 42% of hummers use less than 12 st in a song, so a fixed 12 st gate would have wrongly failed many people. Rows are per person now.

**Fallback rate** (how often sideways would be snap), at `vowel_acc_min` 0.9, with 0.8 in brackets. Each script prints its row as `fallback at vowel_acc_min …`:

| Population | People with ≥ 1 vowel band | Bands that snap |
|---|---|---|
| Speech (Hillenbrand, one band per talker) | 84% (90%) | 16% (10%) |
| Trained singers, long tones | 70% (95%) | **66%** (46%) |
| Trained singers, all a/i/u material | 75% (95%) | 60% (32%) |
| Whistlers, closed-mouth hummers | 0% | 100% |

- **Reading:** for most people, part of the screen will snap.
  - Snap is a first-class mode, not an error path.
  - The 0.9 threshold is strict for a cursor you can see and correct. At 0.8, 95% of singers get at least one vowel band.
  - The threshold is a spec knob to settle after your own test and a real-use trial, not a code change.

### Your test (v2)

The guided terminal script builds the steps from the spec, reusing `guided_session.py`'s screens and `record.py`'s recorder:

```bash
cd ~/VOX/extractor
./run python voice_cursor_test.py --session vcursor-2
#   (add --device alsa_input.usb-CMEDIA_Q9-1-00.mono-fallback if the default source isn't the Q9 USB mic)
./run python voice_cursor_test.py --score recordings/vcursor-2
```

- **What you do:** 55 takes plus the range check, about 9–10 minutes (test 1's 40 took 7). That is range 4, home 3, check, blind levels 15, meter levels 15, vowels 18. Each take starts from silence. `r` redoes, `s` skips, `q` quits, and the same `--session` resumes.
- **Use a big terminal.** The meter needs about 25 lines.
- **Where it goes:** takes go to `extractor/recordings/vcursor-2/` (gitignored, never committed or uploaded), with `labels.jsonl` and `session.json` (the spec version and hash, the seed and the accepted range).
- **What the score prints:**
  - range (with the glide and held-note edges, and any flag) and home note;
  - blind: repeat SD and **rows_blind**;
  - with the meter: reached n/15, time-to-target median and p90, final error RMS, overshoot, and **rows_feedback**;
  - per band (measured): vowel accuracy and **VOWEL or SNAP**;
  - the verdict, naming the measurement it used.
  - `score.json` holds all of it as plain JSON.
- **Self-test:** `--source fake --auto` runs the whole flow on a synthetic voice (56/56). The fake singer's held top note is a falsetto 7 st up, so the flag and the glide-top rule are exercised. It gives 14.4 st, rows_blind 9, rows_feedback 9, time-to-target p90 ≈ 650 ms, 100% vowels, GO.
  - The range redo path and resume were also run with scripted keys.

### Go / no-go (per person, from the spec's `rules.go`)

**Measures:**
- **rows_blind** = floor(range / (4 × blind repeat SD)).
- **rows_feedback** = floor(range / (4 × RMS final error)), over the meter takes that reached their target.
- **Time-to-target** = from voice onset to the end of the first 300 ms in which the smoothed pitch stays within ±0.5 st of the target.

**Proposed rule** (the go/no-go uses the **with-meter** measurement, because the position cursor always shows its dot):

| Verdict | When | Then |
|---|---|---|
| **GO** | rows_feedback ≥ **3**, time-to-target p90 ≤ **1500 ms**, never reached ≤ **10%** (at most 1 of 15), and at least one band is "vowel" | Position cursor: vowel columns where they work, snap elsewhere |
| **SNAP-ONLY** | the same, but every band snaps | Position cursor without vowels: height picks the band, hums step |
| **NO-GO** | any of the three fails | Keep the steering cursor and the intent cursor |

- **Reported with it:** "absolute (no look) too: yes" if rows_blind ≥ 3. Then jumping to a spot without watching the dot also works.
- **Why these numbers:**
  - 3 rows is the least that beats a plain up/down steer.
  - 1500 ms allows about 300 ms reaction, a glide, and the 300 ms hold, and is still well under a Dragon-grid step.
  - A cursor that misses 1 in 10 is already annoying.
- The numbers are open until the user confirms them. They live in the spec, not in code.
- Reported, not gating: blind lock time p90 (want ≤ 400 ms) and F2 wobble within a hold (want ≤ ¼ of the ee–oo distance).

**If it's a go:** prototype on the **desktop** first. The extractor reads the USB mic, and a phone-sized window shows the dot, the lock and a fake target list. That needs no app or firmware change. Then the app mover on the phone mic, and the Pico stream last (it needs a flash).

## Moving to the app

- **Per mic source.** Calibration is stored per mic (Pico or phone), because formants shift with the mic and its distance. The desktop run is only the go/no-go. **It is never the stored profile.**
- **One spec, three readers.** The app's calibration screen walks the same `steps` from `voice_cursor_v2.json` (range check, the live meter, blind and meter levels), and applies the same `analysis`, `live` and `rules`.
  - A change of steps or thresholds bumps `version`. Profiles record the version they were made with.
  - The Kotlin scorer is checked against the Python `score.json` on the same takes.
- **Parity for the vowel measurement.** Formant extraction (LPC, the F1/F2 picking rule, the smoother) needs matching implementations in Python (reference), C++ (Pico M33) and Kotlin (phone mic), with shared test vectors in the style of `check_extract`: the same wav gives the same F1/F2 per frame within a tolerance.
  - The M33 version uses the envelope peak-picking described above, not polynomial roots, so the vectors must pin down the *picked* formants, not the roots.
  - v2 adds three things the vectors must cover: the 70 Hz high-pass (a biquad), the broad-F2 envelope-level test, and the F2 continuity state machine (500 Hz / 5 frames). The continuity is stateful across frames, so the vectors need whole takes, not single frames.
- **The Pico needs a flash** for the formant stream, the `track: voice` message and the `cursor_style` config. Nothing is flashed without your OK.
- **Whistle profiles** need the pitch search raised to about 4000 Hz on both extractors.

See also: the decisions behind this design, [D134](decisions.md#d134), [D135](decisions.md#d135) and [D137](decisions.md#d137)–[D139](decisions.md#d139), and the fork that wrote it in [agent-log.md](agent-log.md#brand-badge-and-ui).
