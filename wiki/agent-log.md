# Agent log

Every agent and fork the coordinator started for VOX / Canti between 2026-09-26 07:40 and 2026-09-28 15:30 (UTC). That
is 140 Claude agents plus 3 DeepSeek workers:
- 78 top-level Claude agents (general-purpose, Explore, forks, Opus reviewers and librarian runs);
- 62 second-level agents, started by two of the Verdict agents;
- 3 DeepSeek workers run through `eidolon` in git worktrees (E1–E3, 2026-09-28), listed in their own section.

How the work was organised is in [process.md](process.md), and the decisions are in [decisions.md](decisions.md).
Prompts are quoted from their first sentence and trimmed. Device serials, screen content and third-party names are
removed. "Result" is taken from the agent's final report.

Times are UTC, as start → end. An agent marked *died* stopped when the desktop session crashed at about 04:41 on
09-27, and the fork listed next to it took over. The PC was shut down to be moved at about 14:20 on 09-27; the Verdict
fork a19c44b stopped then, and its unfinished cross-fit was completed by jl8 (a9c6c9d) on 09-28.

## Research (09-26)

| Agent | Time | Role | Prompt (trimmed) | Result | Decisions |
|---|---|---|---|---|---|
| a25189a | 07:40 → 07:46 | Jev research | "Research Jev, TypeSafe AI's non-generative 'System One' decision model … for use as the output/decision stage" | `research_notes/…/jev.md`. Jev is weak at numbers ("does not count reliably"), so the Pico should send named buckets, not raw numbers. | [D001](decisions.md#d001) |
| ac0bf63 | 07:40 → 07:49 | Hardware + BLE HID | "Research low-cost hardware for a hum/tone-driven cursor controller" | `hardware_and_output.md`: Pico 2 W specs, BLE HID, mics, BOM. | |
| ac4d842 | 07:40 → 07:49 | MCU signal processing | "Research real-time audio feature extraction and tiny on-device classification … on a Cortex-M33" | `signal_processing_and_ml.md`. No published M33 cycle counts, so hardware measurement came first. | |
| a977685 | 07:40 → 07:49 | Prior art | "Research prior art on controlling a computer or phone cursor with non-speech vocal sounds" | `prior_art.md`. Keep Jev out of the cursor loop; lag hurts from 75 ms. | |
| a0c24e1 | 07:48 → 07:59 | Alternatives to Jev | "Research models other than Jev that could make the decision in VOX" | `alternative_models.md`. Recommends a small local classifier first and the cloud as a fallback. | [D006](decisions.md#d006) |
| ac37607 | 07:52 → 08:01 | Phone output | "Research how a Raspberry Pi Pico 2 W can drive a phone over Bluetooth LE through a companion app" | `phone_control.md`. Android can be fully driven through a companion app; iPhone cannot (it needs a HID mouse). | [D010](decisions.md#d010) |
| a89f15f | 08:02 → 08:23 | Report + wiki | "Read the notes in research_notes/… and write the final report and wiki" | `reports/VOX hum cursor with Jev.md` ("Keep Hums Local, Let Jev Referee") and the first 10 wiki pages. | |

## Models and Verdict training

| Agent | Time | Role | Prompt (trimmed) | Result | Decisions |
|---|---|---|---|---|---|
| a6b89ec | 09-26 08:15 → 09:49 | Teacher models | "Set up two open 'Jev-like' teacher models locally on this machine's AMD GPU, and write the labelling script" | JevK5 and Decider 4B run on the GPU. They score 0.69–0.79, not good enough to replace the code labels, but they found generator bugs. | [A02](decisions.md#a02) |
| a50d77f | 09-26 08:15 → 09-27 01:32 | Kev + Verdict students | "Set up fine-tuning for two student models, Kev 0.8B and Verdict-118M" | Kev best on test_iid (0.980). Verdict bi-encoder recommended: 0.95 on both splits, about 8 ms ONNX int8. | [A01](decisions.md#a01), [D041](decisions.md#d041) |
| ae6ba3a | 09-26 20:14 → 21:32 | Real-screen dataset | "Build a real-screen test set for VOX's voice screen targeting, labelled by you using vision, then score our trained models" | real-targets-v1, 557 emulator rows. Verdict 0.646, jevlike 0.447, fuzzy baseline 0.557. Phone work paused after a denied tap. | [D062](decisions.md#d062), [A06](decisions.md#a06) |
| a5756884 | 09-26 21:16 → 09-27 04:33 | Verdict on real screens | "train the **Verdict** student further on **real phone screens**" | real-targets-v2 and runs v1a–v1e. **v1d recommended**: new test 0.738, old test 0.838 (`finetune/reports/verdict_real.md`). Started 47 sub-agents. | [D074](decisions.md#d074), [A07](decisions.md#a07), [A08](decisions.md#a08) |
| a79f29c | 09-27 02:35 → 02:47 | Audit: data and labels | "Audit the DATA and LABELS side of the Verdict training loop" | Fillers cut none recall from 0.80 to 0.25; position errors stay inside the same 3×3 bucket. | [D110](decisions.md#d110) |
| a8eedf7 | 09-27 02:35 → 02:48 | Audit: model and objective | "Audit the MODEL, OBJECTIVE and CALIBRATION side" | CPU diagnostics on val; calibration and objective findings. | [D110](decisions.md#d110) |
| adee2d5 | 09-27 02:35 → 02:42 | Audit: eval and loop | "Audit the EVALUATION methodology and the end-to-end LOOP" | Screen-bootstrap CIs show that v1a–e differences are not real; found test-reuse risks. | [D110](decisions.md#d110) |
| a81e006 | 09-27 02:54 → 04:33 *died* | Verdict lead | "You are the Verdict lead for VOX/Canti … Verdict = the on-device target picker" | Locked test sealed, val by option set, cross-fit tooling (`crossfit.py`, `cf_eval.py`), b2/b3 builds, label pass 2. Its seal edit was blocked by the permission system twice. Started 15 sub-agents. | [D112](decisions.md#d112), [A10](decisions.md#a10), [A11](decisions.md#a11) |
| a19c44b | 09-27 04:42 → 14:18 | **Fork**, replaces a81e006 | "You are the replacement VERDICT LEAD … Monitor the orphaned crossfit and train jobs, then report the step-2 status". Later briefs: build b4, prepare the blind pass, compare `lossacc` and `drop15`, cross-fit b4; then route Z Flip adjudications into the build; then build b4a and refit. | b4 built; `drop15` chosen (T 1.99, none bias +0.75, t_tap 0.82, t_none 0.60: tap rate 0.481, wrong/tap 0.036, bound 0.050; none recall 0.62). Added `check_zflip_adjudication.py` and build names in cross-fit filenames. Sent a low-disk warning at 10:53. The b4a cross-fit was cut off by the shutdown. | [D165](decisions.md#d165), [A29](decisions.md#a29) |
| ad77509 | 09-27 03:18 → 04:07 | Phrase recordings | "The user just recorded a guided session … split and review" | Split 176 segments with faster-whisper medium.en; built a phone-recognizer op that has never run on a device. | [D116](decisions.md#d116), [A17](decisions.md#a17) |
| a6bf6ff | 09-28 10:50 → 12:39 | jevlike iteration 1 (jl7) | "You are the jevlike training lead for the VOX project … Report back a concise result (tables, numbers, what you ran, anything surprising, and concrete optimization ideas for the next iteration)" | Runs J0–J3 plus controls J1p and J2c on the b4a build. dev_test: J0 0.462, J1 0.733, J2 0.677, J3 0.709, J1p 0.750, Verdict v1d 0.750. Found b4a `val` contaminated for v1d (434/473 rows). Trained at 156 rows/s. Reported its own read-only `git check-ignore` (a rule breach, no change made). | [D180](decisions.md#d180), [A34](decisions.md#a34) |
| a9c6c9d | 09-28 12:40 → 14:30 | jevlike iteration 2 (jl8) | "You are the jevlike training lead for VOX (~/VOX/finetune), iteration 2 ("jl8")" — speed fixes, an honest teacher, finish the b4a cross-fit, train J4 | 315 rows/s (`--fast-options` plus the AOTriton flag); `oof_teacher.py`; the b4a Verdict cross-fit finished (acc 0.759). J4: dev_test 0.744, test_old 0.819 (p = 0.014 against control C), but none recall −0.10 on test_old. | [A35](decisions.md#a35) |
| ab34f84 | 09-28 14:31 → 15:29 | jevlike iteration 3 (jl9) | "You are the jevlike training lead for VOX (~/VOX/finetune), iteration 3 ("jl9")" — none-recall fix, option cache, Verdict speed port | J5b (`--teacher-skip-none`) restored none recall (+0.10 on test_old, p < 0.001). J5c (3 epochs): test_old 0.833, none recall 0.808, NLL 0.617. Option cache: CPU 756 → 322 ms, GPU 7.8 → 3.9 ms. `opgate.py`. Verdict `--fast-embed` only +3–8 %. Proposed jl10. | [A36](decisions.md#a36), [D190](decisions.md#d190) |

### Second-level agents (Verdict)

Started by **a5756884** (47 agents, 09-26 21:32 → 09-27 01:32):

| Agents | Count | Job | Result |
|---|---|---|---|
| "Label batch 000" … "Label batch 041" | 42 | Label DeepSeek-written emulator phrases against marked screenshots (`real-targets-v2/emulator/labels/batch_NNN.jsonl`) | 16–120 phrases per batch, each pid once. 59 rows were dropped in total. |
| "Write Z Flip X phrases", "Write Z Flip phrases batch 1–4" | 5 | Opus writes phrases and labels for Z Flip screens (`zflip/written/zbatch_00N.jsonl`) | 40 lines each. The content is private: see `finetune/data/real-targets-v2/zflip/` (gitignored). |

Started by **a81e006** (15 agents, 09-27 03:43 → 04:08):

| Agents | Count | Job | Result |
|---|---|---|---|
| "Verify swap negatives batches 0-2 / 3-5 / 6-8" | 3 | Check synthetic "swap" negatives (match / none / unsure) | Counts per batch in `b2`. |
| "Verify swap r2 …" | 3 | Round 2 of the same check | Mostly "none" in round 2. |
| "Blind label pass 00-04 … 25-29" | 6 | A blind second labelling pass | Label pass 2: 4,500 rows, 97% agreement. |
| "Write Z Flip phrases 005-007 / 008-010" | 2 | More Opus phrases for Z Flip screens | 8 per screen, private. |
| Adjudicate (a3edd9f) | 1 | Settle disagreements between the passes | 135 phrases adjudicated. |

Started by the **coordinator** on 09-27 for the b4 / b4a builds:

| Agents | Count | Time | Job | Result |
|---|---|---|---|---|
| a842c55, a723893, a233872 ("Label batch 042 / 043 / 044") | 3 | 09:53 → 10:00 | Opus labels for three new emulator phrase batches | 042: 364 phrases, 0 drops (96 "none", above the 10–15 % the brief expected); 043: 361, 0 drops; 044: 166 phrases over 18 screens of one app. |
| ad9f153, a1ce876, abd3d5a, adf087c, a81d6ae ("Blind label pass: blind_00 … 04") | 5 | 12:27 → 12:32 | A fresh blind second pass on the b4 rows | 182 / 181 / 181 / 182 / 163 rows; 1 drop in total. 867 of 889 agree with pass 1 (97.5 %). |
| abb3903 ("Adjudicate b4 label disagreements") | 1 | 12:33 → 12:35 | A/B blind adjudication of the 22 disagreements | A 4, B 8, both 8, neither 0, drop 2; best = none in 9 of the 20 kept. |

## App, grammar and phone mic

| Agent | Time | Role | Prompt (trimmed) | Result | Decisions |
|---|---|---|---|---|---|
| a76da37 | 09-26 10:27 → 17:55 | App skeleton + emulator suite | "Build the VOX Android companion-app skeleton and an emulator test suite. Work ONLY under ~/VOX/android" | `android/` app, `suite/` (emulator AVD vox35, F-Droid stand-ins, 34 emulator tests). Last change: a refused device command fails right away with the device's reason. 75/75 JVM tests. | [D022](decisions.md#d022), [D025](decisions.md#d025) |
| a6f1962 | 09-26 21:08 → 09-27 04:31 *died* | Ollama cloud decider, then grammar | "Add an Ollama-cloud 'deeper decision' backend to the Canti Android app, and first evaluate the cloud model" | `OllamaDecider`, report `ollama_vs_students.md` (cloud 0.891 vs jevlike 0.592 on unseen phrasing). Later: grammar (volume, swipes, repeats), ForegroundApp per window, 348 tests. | [D072](decisions.md#d072), [D113](decisions.md#d113), [A12](decisions.md#a12), [A13](decisions.md#a13) |
| a10ebe3 | 09-27 04:42 → 05:18 | **Fork**, replaces a6f1962 | "You are the replacement GRAMMAR agent" | Phone-mic pop gate, youtube → RVX, pop pop = listen, voice typing and dictation. **386 JVM tests pass.** Not on a phone yet. | [D130](decisions.md#d130), [D135](decisions.md#d135), [D137](decisions.md#d137), [A20](decisions.md#a20) |
| a40b392 | 09-26 22:16 → 09-27 02:09 | Phone mic (NDK) | "listen with the phone's own microphone, including a USB mic plugged into the phone" | `audio/*`: JNI `libvx_jni.so` built from `firmware/extract/src`, MicCapture, MicListenService. Also the guided recording session (`extractor/guided_session.py`, 60 phrases, 85 sounds). | [D085](decisions.md#d085), [D107](decisions.md#d107), [A16](decisions.md#a16) |
| ac238e2 | 09-27 02:00 → 02:36 | BLE stale link + target bugs | "Fix three product bugs in Canti found by a live test on the user's Z Flip. Off-device work only" | `LinkRecovery`, bottom-sheet rule, tree_targets parity. 207 JVM tests. | [D108](decisions.md#d108), [A14](decisions.md#a14) |
| a74ff1f | 09-27 02:54 → 04:27 | App side of the Verdict plan | "App-side changes … fillers, ordinals, dup options. Off-device: JVM tests only" | Filler normaliser, ordinals, sheet occlusion, no raw view ids. 348 tests. | [D116](decisions.md#d116), [A15](decisions.md#a15) |
| a419b79 | 09-27 03:24 → 04:33 *died* | Scroll | "Scroll step, throttle, sensitivity" | `ScrollStep.kt` (no-momentum step), pitch throttle, sensitivity setting; started glide-and-hold. | [D117](decisions.md#d117), [D128](decisions.md#d128) |
| afe9ca9 | 09-27 07:09 → 07:37 | Feed-fling delay | "Fix a latency regression in the Canti Android app … Source changes only: no install, no device or emulator use, no git" | `FeedKindCache.kt`: the feed/not-feed answer is cached per window (trusted 6 s for a feed, 20 s for a list, 1.5 s otherwise), plus a `fling_wait` event. 418 JVM tests. | [D148](decisions.md#d148) |
| a5443ae | 09-27 07:34 → 07:52 | Media gate | "Add a 'media playing' gate to the Canti Android app's phone-mic path" | `MediaGate.kt`, setting `media_lock` (default on), unlock by pop pop, modes `one` / `fixed` / `popext`. 438 tests. | [D149](decisions.md#d149), [A23](decisions.md#a23) |
| a4371e9 | 09-27 07:38 → 08:17 | Desktop echo cancel | "Desktop go/no-go: can a reference-based echo canceller … remove media sounds well enough that the VOX extractor stops hearing false gestures?" | No speaker was connected, so it ran a simulation: WebRTC AEC3, AECM, SpeexDSP and NLMS. Best gesture survival 46 % against a 90 % target: **NO-GO**. Recordings stayed local (gitignored). | [D150](decisions.md#d150), [A26](decisions.md#a26) |
| a3f4443 | 09-27 08:17 → 08:26 | Why the phone mic fires 45/min | "Investigate the gap between two measurements (offline first, no device yet)" | The two numbers counted different things (sounds vs groups); with a Python replica of the app's Sequencer the real gap is about 15×. The phone hears a 6.6–7.3 kHz hiss while media plays. Proposed the centroid rule. Added a section to [phone-mic-echo.md](phone-mic-echo.md). Aggregates only. | [D150](decisions.md#d150) |
| a52f3c7 | 09-27 08:26 → 08:39 | PhoneGate hiss rule | "Implement three follow-ups from the phone-mic false-trigger investigation" | `hiss_media_max_centroid_hz` (6500) in `PhoneGate.kt`, centroid passed from the extractor, gate features logged. 441 JVM, 118 pytest. | [A24](decisions.md#a24) |
| a64985c | 09-27 08:38 → 09:31 | Joystick on Android | "Port the voice joystick cursor from the desktop prototype to the Canti Android app … Use the PHONE MIC as the source first" | `VoiceJoystick.kt` and `joystick/` (`JoystickCore`, `JoyCalibration`, `JoyIndicators`); two sensitivity settings. 461 tests. | [D147](decisions.md#d147), [D153](decisions.md#d153) |
| a06f276 | 09-27 08:45 → 09:05 | Calibration → gestures | "Calibration→gesture go/no-go + desktop retry/skip" | Every candidate field NO-GO, so calibration sets no gesture threshold. Retry/skip added to the desktop calibration. pytest 129. | [D154](decisions.md#d154), [A27](decisions.md#a27) |
| aba64c2 | 09-27 09:06 → 09:43 | Arch/dip inversion | "Diagnose arch/dip inversion and long pops" | No pipeline bug: the takes themselves were whistled inverted. | |
| a99fd9a | 09-27 09:56 → 11:22 | Calibration v2 and level gate | "Calibration v2: clicks, whistle, room, level gate" | `CalibV2.kt`: 8 steps (hum, glide, vowels, pops, clicks, whistle, hiss, room), the level gate (`level_gate`, `level_gate_offset_db`), and the `calib_*` contract. 489 JVM / 144 pytest, then contract fixes: 497 JVM / 145 pytest. | [D156](decisions.md#d156) |
| ac87763 | 09-27 10:04 → 10:58 | Gesture training | "Gesture training: resumable per-mic enrollment" | `GestureTraining.kt`, the `ai.vox/train` channel, 52 takes per source, `enroll_gesture_relabel`. 484 tests. | [D158](decisions.md#d158), [A28](decisions.md#a28) |
| a21cd3f | 09-28 08:46 → 08:53 | Survey (Explore) | "Read-only survey of ~/VOX … report conclusions with file:line citations" | The dummy-button table (static bindings window, mode toggle hidden for the phone mic, orphan `scrollStep`), both-mode gaps and pop usage. Became [round7-plan.md](round7-plan.md). | [D171](decisions.md#d171) |

## Firmware and extractor

| Agent | Time | Role | Prompt (trimmed) | Result | Decisions |
|---|---|---|---|---|---|
| ac344c8 | 09-26 13:20 → 14:07 | Reference extractor | "Build the VOX reference feature extractor and recording tool in Python. Work ONLY under ~/VOX/extractor" | `extractor/vox_extract`, recorder, synthetic generator, C test vectors. 57 tests (synthetic audio only). | |
| add4c65 | 09-26 14:42 → 17:37 | Real-audio eval | "Build a REAL-AUDIO evaluation of the VOX sound extractor from public datasets" | Public-dataset eval plus live regression cases (77 tests, 8 xfail). No label rule changed, because every general rule regressed. | [D032](decisions.md#d032), [D043](decisions.md#d043) |
| af4600b | 09-26 15:54 → 18:15 | First firmware | "Build the first real firmware for the VOX Pico 2 W, and test everything that can be tested before any wiring exists" | Code and docs done. The Pico hung in a sleep test; fix: wait for `HCI_STATE_OFF`, plus a watchdog. | [A03](decisions.md#a03), [D048](decisions.md#d048) |
| aacb3c7 | 09-26 20:29 → 22:18 | Port extractor to C++ | "Port the VOX Python feature extractor to C/C++ for the Pico 2 W firmware. Match the Python output exactly" | Did the Python side of hold-to-scroll and its PROTOCOL.md format. The C port was deferred (firmware frozen). Found the vocab drift (see below). | [D066](decisions.md#d066), [A09](decisions.md#a09) |
| a381aa0 | 09-26 22:14 → 09-27 00:55 | Pico bring-up | "You own Pico firmware bring-up … The user just plugged in the Raspberry Pi Pico 2 W" | 0.2.1 flashed and paired (LESC bond). Watchdog fix in the `ext feed` loop. | [D087](decisions.md#d087), [A04](decisions.md#a04) |
| a7b15d7 | 09-27 04:42 → 05:29 | **Fork**, replaces a419b79 | "You are the replacement SCROLL/FIRMWARE agent" | Glide-and-hold with both guards, and the `by:"button"` tag. Firmware 0.2.2; the user flashed it at about 05:34 and re-paired it with `btn hold 5500`. | [D131](decisions.md#d131), [D136](decisions.md#d136), [A19](decisions.md#a19) |

The C++ extractor in `firmware/extract/src` exists and matches Python (19/19 vectors pass on the Pico). The agent
that wrote it is not clear from the reports: aacb3c7 deferred it and a381aa0 flashed it (unverified which agent ported
it).

## Brand, badge and UI

| Agent | Time | Role | Prompt (trimmed) | Result | Decisions |
|---|---|---|---|---|---|
| ab69ad3 | 09-26 18:13 → 18:20 | App icon v1 | "Redraw the Canti app icon as a hand-written SVG in ~/VOX/brand/" | A robot head peeking in from the lower-left. Later replaced by B1. | |
| a75e328 | 18:28 → 18:31 | Icon mockup A1 | "Draw ONE app-icon mockup … variant A1" (head fills the tile) | Mockup in scratchpad. | [D054](decisions.md#d054) |
| aa92faf | 18:28 → 18:32 | Icon mockup A2 | Same, variant A2 | Three-quarter-view teal head. | [D054](decisions.md#d054) |
| a1df027 | 18:28 → 19:52 | Icon mockup B1 (winner) | Same, variant B1 (mostly screen) | Iterated with the user through B1c … B1x and B1z2, then on/off state icons. | [D058](decisions.md#d058), [D059](decisions.md#d059) |
| a5e7baa | 18:28 → 18:32 | Icon mockup B2 | Same, variant B2 | CRT screen set deep in the head. | [D054](decisions.md#d054) |
| a8b23f1 | 18:35 → 19:53 | Wordmark | "Redraw the Canti wordmark as pure SVG" | Colour and B/W wordmarks, all paths. | [D055](decisions.md#d055) |
| a42082a | 09-26 20:38 → 09-27 00:10 | App restyle + stipple brand | "Restyle the Canti phone app with the brand, and make stippled/dithered versions of the logo and icon" | 1-bit pixel kit, dither shader, clearing, stipple icon and wordmark v5. flutter test 42/42. | [D068](decisions.md#d068), [D078](decisions.md#d078), [D079](decisions.md#d079), [D086](decisions.md#d086) |
| ad924c4 | 09-26 22:40 → 09-27 00:57 | Badge animation | "You are building the animated pixel-character sprite for the Canti app's floating badge" | Sprite sheet v3A in the APK (`ui/assets/badge`). | [D090](decisions.md#d090), [D093](decisions.md#d093), [D101](decisions.md#d101) |
| a8d4d0a | 09-27 02:18 → 02:55 | Badge shoulders | "Make STATIC design mockups (no animation build …) for a small change to Canti's floating badge sprite" | Variants A/B/C. C became the default sprite. | [D111](decisions.md#d111), [A22](decisions.md#a22) |
| ad271ef | 09-27 03:34 → 04:25 | Tap-to-wake | "Badge tap-to-wake mockup + logic" | Mockups A/B/C, `UserMode`, wake restores the user's mode. 348 tests. | [D122](decisions.md#d122), [D125](decisions.md#d125) |
| a4236175 | 09-27 05:32 → 05:48 | **Fork**, build book | "You are the BUILD BOOK agent. The user approved the style of the sample … and wants ALL the steps drawn." | Build book v3: 28 steps from a bare Pico (breadboard 1–10, necklace 11–28), republished as an artifact, not in the repo. Nobody has checked the rendered layout since. (The previous log gave its start as about 04:50; the transcript shows the fork was launched at 05:32. Who drew the earlier sample is unverified.) | [D133](decisions.md#d133), [D142](decisions.md#d142), [D143](decisions.md#d143) |
| a60c8f5 | 09-27 05:04 → 08:31 | **Fork**, voice cursor design, then the desktop joystick | "You are the VOICE CURSOR DESIGN agent … a design write-up (nothing built)"; later resumed to build the desktop joystick prototype and add the indicators | Wrote [voice-cursor.md](voice-cursor.md); ran the recording test with a live pitch display; built the desktop joystick (relative, never resets, magnet on stop) with per-voice calibration, then the chevron cursor and bar face. Findings: creak chops hums, the reference note biases steering, pops were missed. | [D135](decisions.md#d135), [D139](decisions.md#d139), [D146](decisions.md#d146), [D147](decisions.md#d147) |
| a46729b | 09-27 08:02 → 08:12 | Joystick indicator mockups | "Make STATIC design mockups, for the user's sign-off, of two pitch/steering indicators in the Canti Android app's joystick cursor mode. Mockups only" | Cursor A (arrow) and B (chevrons); badge face A (bar) and B (stick dot). Recommended A + A; flagged a caption error (the crop is 30×46 art px). The user took chevrons + bar. | [D152](decisions.md#d152), [A30](decisions.md#a30) |
| a751aaf | 09-27 08:38 → 11:55 | Flutter calibration and sliders | "Build the voice-cursor calibration setup screen and two sensitivity sliders in the Canti Flutter UI (~/VOX/ui). No install, no device, no git." Resumed three times for the title plate, calibration v2 and the `steps` contract. | `calibration.dart`, `calibration_screen.dart`, `voice_cursor.dart` and settings. Tests 72 + 4, then v2 92 + 10, then 94 + 10. It found `JoyCalibration.startStep` did not no-op while recording; the coordinator fixed that. | [D153](decisions.md#d153), [D154](decisions.md#d154) |
| a9363e6 | 09-27 09:57 → 10:53 | Icon v5 and v5b mockups | "This task is a MOCKUP ONLY, for the user's sign-off." (trim and hood to the border) | v5: the trim runs to the border, the hood full bleed. v5b: whole-dot dome steps and a Bayer crown. v5b applied at 11:18. | [D157](decisions.md#d157), [D162](decisions.md#d162), [D164](decisions.md#d164) |

## Hardware and case

| Agent | Time | Role | Prompt (trimmed) | Result | Decisions |
|---|---|---|---|---|---|
| ab0084b | 09-26 20:53 → 21:17 | Case redesign | "Redesign the VOX pendant case so the microphone module mounts on TOP of the protoboard" | Mid-task switch to a lid-mounted mic with a Dupont header. New `mic_clip.stl`; the lid needs a reprint. | [D069](decisions.md#d069), [D070](decisions.md#d070), [A21](decisions.md#a21) |

The coordinator built the first case itself: a throat-facing mic, about 17:00 on 09-26. The main transcript shows it
editing `vox_case.scad`, for example "Updating the case to one button". Who made the lid-corner fix (commit acce546) is
unverified.

## Harvest

| Agent | Time | Role | Prompt (trimmed) | Result | Decisions |
|---|---|---|---|---|---|
| ae81972 | 09-27 02:54 → 04:33 *died* | Harvest | "Harvest new EMULATOR screens for Verdict: (1) a locked test set from 10–12 apps never used before, and (2) extra training coverage" | Chose the locked apps and started `harvest_v3.py`. | [D112](decisions.md#d112) |
| a81a619 | 09-27 04:48 → 06:47 | **Fork**, replaces ae81972 | "restart emulator-5580 (shared-2353), the view-only mirror, and resume the harvest" | Finished the locked and training captures. ANR handling added to `harvest_v3.py`; 18 rows quarantined; one dialer app skipped. | |

## Z Flip tests

| Agent | Time | Role | Prompt (trimmed) | Result | Decisions |
|---|---|---|---|---|---|
| aa60915 | 09-27 01:48 → 04:33 *died* | Social-app gesture test | "You are testing Canti on the user's real Samsung Z Flip (adb serial redacted) inside their social apps, using ONLY scrolls, back and home" | Rounds 1–4. Found the stale-BLE-link bug. Visual latency test (see [architecture.md](architecture.md#latency)). Write-up (private): `android/suite/out/zflip/social_gesture_test.md`. | [D104](decisions.md#d104), [D121](decisions.md#d121), [A18](decisions.md#a18) |
| a7c5b25 | 09-27 04:48 → 07:29 | **Fork**, replaces aa60915 | "You are the replacement Z FLIP TEST agent" | Finished round 4 once the source was back on the Pico. A feed app's stuck state was the app's own; apps throttle after about 30–100 automated flings; Reels advanced one item per fling at 15 %/50 ms. The platform echo canceller cut sounds by about 60 % but still let 30–35 would-act a minute through. Write-up private: see `android/suite/out/zflip/`. | [D140](decisions.md#d140), [D149](decisions.md#d149) |

## Documentation

| Agent | Time | Role | Prompt (trimmed) | Result |
|---|---|---|---|---|
| a7094c0 | 09-27 05:28 → 05:50 | Librarian, first run | "Read ~/VOX/.claude/agents/librarian.md first … This is the first run, a full BACKFILL" | Wrote architecture, process, decisions, agent-log, design-process and training. |
| (coordinator) | 09-27 ~14:10 | Handoff | The librarian did not run again on 09-27; the coordinator wrote [session-2026-09-27.md](session-2026-09-27.md) and a handoff memory before the shutdown. | Folded into these pages by a083bbb. |
| a083bbb | 09-28 15:30 → | Librarian, incremental (this run) | "Run your incremental update for the VOX wiki. Two sessions are unprocessed" | Added D142–D190 and A23–A37, the 09-27 and 09-28 agents, the eidolon workflow, jl7–jl9 and the b4a results. |

## DeepSeek workers and Opus reviewers (09-28)

Started after [D183](decisions.md#d183). Each worker ran headless with `eidolon run -m ollama:deepseek-v4-pro --cwd <worktree>`
in its own git worktree (branched from `main` at 94a34e6), under a shared hard-rules file (no git, worktree only, emulator
adb server 5038 only, never the phone, never read the Ollama key, keep 30 GB free, no `pgrep -f`, write `REPORT.md`).
They are not Claude agents, so they have no agent id. Each was checked by an Opus reviewer that could fix what it found.
None of the three branches is committed or merged yet ([D188](decisions.md#d188)).

| Worker | Time | Worktree / branch | Brief (trimmed) | Result | Review |
|---|---|---|---|---|---|
| E1 | 11:03 → ~11:51 | `~/worktrees/vox-r7-suite` / `r7-suite` | "Round 6 emulator suite failures … update stale tests … root-cause the 'no visible change by pixels' swipes, and the service socket closing" | Resumed twice (no edits on its first turn; a dropped stream). 33/34 pass, 1 skip. Claimed "no app bug": the fixture pager used a strict `>` 15 % threshold; changed it to `>=`, updated stale tests, set `asr_engine=off` in reset. | **a3aa91b** (11:51 → 12:02): accept with changes. Replaced the threshold with velocity-based paging (like a real ViewPager: > 25 dp and > 400 dp/s, or half a page); restored the model-request checks E1 had dropped; the socket crash stays "not reproduced, cause unknown". The fling lifts at 7238 px/s (about 7.9k on the phone), well above real pagers' thresholds: don't make it faster. Suggested a Reels diagnostic ([D189](decisions.md#d189)). |
| E2 | 11:03 → ~11:19 | `~/worktrees/vox-r7-medialock` / `r7-medialock` | "Media lock should not lock when media plays into earbuds/headphones" | Resumed once (parked on a build). `SpeakerRoute.kt` shared by the lock and PhoneGate; wired, USB and Bluetooth outputs count as headphones; `media_speaker` and `route` in ping. 500 tests. | **a4b0918** (11:19 → 11:23): merge after fixes. Fixed the lift reason, KDoc and 2 tests (502 tests). Main issue: a Bluetooth A2DP speaker now gets neither the lock nor PhoneGate under defaults; option a = check the Bluetooth class ([D185](decisions.md#d185)). HDMI, USB DAC and casting also don't lock. |
| E3 | 11:03 → ~11:28 | `~/worktrees/vox-r7-bindings` / `r7-bindings` | "Make the status screen's bindings window live, and show the mode toggle for phone/USB mic users" | Resumed once (hit the 128-step limit). `Bindings.kt` feeds the window from `Vocab.kt` plus the user's rules; mode toggle for mic sources. Flutter 98 + 10, JVM 507. | **af0ff04** (11:28 → 11:39): merge after fixes. Fixed a false cursor-mode note, the hums label ("steers the joystick") and the combo rows; added `RuleDecider` and Flutter-fixture parity tests (JVM 510, Flutter 99 + 10). Open: per-app rules show Canti's own ([D187](decisions.md#d187)); long labels wrap ([D186](decisions.md#d186)). |

## Forks and what was decided in them

| Fork | Replaced | Decided or built in the fork |
|---|---|---|
| a10ebe3 | a6f1962 | pop pop = listen ([D130](decisions.md#d130)); phone-mic pops do nothing ([D135](decisions.md#d135)); dictation stop rule ([D137](decisions.md#d137), [A20](decisions.md#a20)); youtube → RVX ([D129](decisions.md#d129)) |
| a7b15d7 | a419b79 | glide-and-hold guards ([D136](decisions.md#d136), [A19](decisions.md#a19)); button tag ([D131](decisions.md#d131)) |
| a19c44b | a81e006 | b4 build, `drop15` recipe ([A29](decisions.md#a29)); b4a cross-fit started, finished by a9c6c9d |
| a81a619 | ae81972 | harvest of `raw_locked3` / `raw_train3`; done 06:47 |
| a7c5b25 | aa60915 | waited until the source was back on the Pico, then finished round 4 (07:29) |
| a60c8f5 | — (new) | voice-cursor design ([D135](decisions.md#d135), [D139](decisions.md#d139)); desktop joystick ([D147](decisions.md#d147)) |
| a4236175 | — (new) | LEGO build book v3 ([D133](decisions.md#d133), [D142](decisions.md#d142), [D143](decisions.md#d143)) |
