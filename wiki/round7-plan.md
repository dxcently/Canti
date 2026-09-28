# Round 7 plan (agreed 2026-09-28)

Worked out with the user on 2026-09-28, with no time pressure. The inputs were the user's idea list and a code survey of the app
(the survey findings are summarised per item below). Nothing on this page is built yet unless its status says so.
Rule: run the emulator suite and a launch check before any Z Flip install.

## Order

1. Fix the round 6 emulator suite failures (§11).
2. Get the phone mic working (§1).
3. Replace pop with clicks (§2) and add the earbuds lift to the media lock (§3a).
4. Fix the dummy UI (§9) and the cross-mode gaps (§7), including gestures in cursor mode (§8).
5. Feedback (§10): the bubble, haptics and badge reactions.
6. Glide scroll (§12).
7. Live mode (§6).
8. The near-field measurement (§3c) → the media gate.
9. Noise (§4).
10. jevlike (§5), which is running now, in parallel.

## 1. Phone mic
- The phone's `sound_source` is still `pico`, and the Pico mic reads all zeros, so nothing is heard.
- Switch the source to `phone`, then record the 4 new calibration steps.
- **Open:** did the phone mic fail at something specific beyond that?

## 2. Pop removed; clicks take over
A pop is too hard to make consistently. Pop carries more than it looks on the phone mic:

| Job | Now | Proposal |
|---|---|---|
| tap, cursor click, choice pick, confirm | pop | lone click |
| listen window, fallback media unlock | pop pop | click click click |
| home | click click | unchanged |

- **Catch:** a lone click is what keyboards and cutlery make, so the level gate and the media gate have to hold.
- A lone click waits one gap to see whether a second click follows.
- Calibration's "pops" step becomes a clicks step; the level gate is derived from it.
- **Open:**
  - Is pop removed on the Pico too, or only on the phone and USB mics?
  - Is the mapping above right?

## 3. The media lock: why gestures fail on videos, Reels and feeds

> **Status (2026-09-28).** a is merged into `main` (09-28, `r7-medialock`); A2DP speakers lock by Bluetooth class
> ([D185](decisions.md#d185)). See [architecture.md](architecture.md#round-7-branches-merged-09-28).
- `MediaGate.kt` drops every phone-mic sound while media plays. Only `pop pop` unlocks, and only for **one** gesture.
- The lock came from round 4: a Short playing on the speaker produced 30–47 would-act sounds a minute, and the platform echo
  canceller did not fix it.

**Decided (user):**
- **a, earbuds:** no lock while audio goes to wired, Bluetooth A2DP/LE or USB headphones. Check: one 60 s media-only session
  with earbuds in; expect about 0 would-act sounds a minute.
- **c, near-field gate:** measured first (the protocol is below).
  - Includes **A, "is this sound mine?"**: the distance from the event's fingerprint to the user's own gesture-training
    templates. No new model.
- **B, fallback only if c misses:** a spoken unlock ("Canti, go") = openWakeWord plus an ECAPA-TDNN speaker check, enrolled
  with about 5 utterances. Needs ONNX Runtime on the phone.
- **Not chosen:** b, the playback reference (`AudioPlaybackCapture`).

### Measurement protocol (c)
Features, per event:
- the low-band ratio (under ~300 Hz; phone speakers can't reproduce it);
- the level above the floor;
- the onset sharpness and decay;
- the level difference between the two mics (if the Z Flip allows stereo capture);
- the template distance (A).

| # | Media | User | Gives |
|---|---|---|---|
| 1 | a Short on the speaker, 60 s | silent | negatives |
| 2 | paused | each gesture ×10 (rise, fall, click, click click, hiss) | clean positives |
| 3 | playing | the same gestures on an on-screen prompt every 5 s | the real test: an event within ±300 ms of a prompt is the user's |

- Sessions 1 and 3 run at volume 30/60/90%, plus one noisy room.
- Recordings stay in the gitignored `zflip/`, never go to an external model, and are deleted afterwards.
- Output: per threshold, video would-act sounds a minute against the user's gestures kept during media.
- **Targets:** ≤ 1 video false action a minute and ≥ 90% of gestures kept. Miss → c is NO-GO → B.
- For B: ≥ 9/10 hits, ≤ 1 false wake an hour (an unattended playlist), and other voices rejected.

### Reels diagnosis (2026-09-28, the Z Flip driven over adb)
- The swipe works: 3/3 injected rises on Instagram Reels ran as feed flings (pager detected), and the confirmer saw the
  screen change.
- The lock is the whole failure: it stays locked while a reel plays, and every mic sound is dropped.
- The reel's own audio over 68 s: 29 mic sounds; the level gate stopped 21; 9 reached the lock (about 8 a minute that
  would act without it). Round 4 saw 30–47 a minute before the level gate existed. The near-field gate (c) has to take it
  from about 8 to ≤ 1 a minute.
- Bluetooth (user): headsets and earbuds must work. **Option a decided:** A2DP devices are classified by their Bluetooth
  class. Speakers lock; headphones and headsets don't; unknown locks.

## 3b. Bluetooth headset mic as a sound source (new, user 2026-09-28)
- A new `sound_source` alongside pico / phone / usb: the headset's own mic.
- Catches:
  - Android switches the headset into call mode (HFP/SCO, 16 kHz mSBC at best), so media audio drops to call quality
    while it listens;
  - the headset's own noise suppression may remove hums and clicks.
- Measure both before committing to it.

## 4. Noise
- Now:
  - the level gate;
  - SNR gates (`PhoneGate`);
  - the extractor's noise-floor tracker;
  - Android NS, which is available but off by default (`mic_effects`).
- There is no denoiser.
- Options:
  - **a.** Turn on `mic_effects aec_ns` and measure it.
  - **b.** Spectral subtraction or Wiener filtering in `vx_frontend`, fed by the floor tracker. Every feature sees it, and the
    Pico/Python parity is kept.
  - **c.** RNNoise is doubtful: it is trained to keep speech and may eat hums and clicks.
- Recommended: a → b.
- **Open:** which noise matters (TV, fans, people talking)? Which dataset for augmentation (DEMAND, ESC-50, the user's own)?

## 5. jevlike, retrained using Verdict

> **Status (librarian, 2026-09-28 15:30).** Ran as jl7, jl8 and jl9. The J5c recipe reaches dev_test 0.748 and test_old
> 0.833, level with Verdict v1d (0.750 / 0.838); J1 (real data) was the big step, and Verdict's encoder as a start (J2)
> made it worse. The numbers in the next line are the 09-26 baseline on the older real-targets-v1 set. Details in
> [training.md](training.md#jevlike-jl7jl9); the next step (partial sentences, ONNX) awaits the user
> ([D190](decisions.md#d190)).

- Real-screen accuracy (09-26 baseline, real-targets-v1): jevlike 0.447, Verdict 0.646, cloud about 0.90.
- The encoders differ: jevlike uses e5-small-v2 (BERT vocabulary), Verdict uses multilingual-e5-small (XLM-R). Rows share
  one format.
- Controlled runs, all scored on Verdict's real-screen suite:

| Run | Init | Data |
|---|---|---|
| J0 | the existing jevlike, no training | baseline |
| J1 | e5-small-v2 | targets-v2 + real Z Flip train rows (b4a) |
| J2 | Verdict's encoder | same |
| J3 | Verdict's encoder + Verdict as the KL teacher | same |

- Later: its job in Live mode is picking intents from **partial** speech, so it needs partial-sentence training data.
- User rule: on every training result, look for ways to make the iterations and the training better.

## 6. Live mode (a new mode)
- The reference: Jev's Mac-assistant demo, where actions fire while the user is still talking.
- How it works: streaming speech-to-text, then the decider runs on every partial, then a committable step runs at once. The
  rest of the sentence queues further steps, and the bubble shows the queue.
- Reversible steps (open an app, scroll, navigate) can fire early on a partial. Typing, sending and anything outward fire only
  on the final words, and outward steps still need a confirm.
- Speech-to-text runs offline on the phone.
- The decider:
  - the grammar first (PhraseGrammar on partials);
  - then jevlike;
  - **DeepSeek as the fallback** for multi-step requests (decided).
- **Open:**
  - How do you enter and leave (the badge menu, plus `click click click`?), and does it stay on or last one sentence?
  - Are sound gestures on inside it? Hiss must stay on for cancel.
  - Grammar first, or jevlike only?

## 7. Both modes: gaps
- Combos are dead in cursor mode (Pico).
- Hold-scroll is gesture-mode only.
- Pop taps in cursor mode but not in gesture mode on the phone mic.
- Cursor mode accepts bare target names; gesture mode needs "tap X".
- Phone-mic users have no mode toggle on the status screen.
- Plan: make these work in both modes. Don't auto-detect the mode, since that guesses wrong silently.

## 8. Gestures in cursor mode
- click = click at the cursor, click click = home, click hiss = forward, hiss = back; hums move the cursor.
- **Open:** a single click waits one gap (and home stays), or clicks are instant (and home isn't available in cursor mode)?
- **Open:** relative page scrolling with the cursor (user, 10:55): A edge-push, B grab-drag, or C scroll-under-cursor
  ([D184](decisions.md#d184)).

## 9. Dummy UI

> **Status (2026-09-28).** The live bindings window and the mode toggle for phone and USB mics are built on the
> `r7-bindings` branch, merged 09-28 with short labels ([D186](decisions.md#d186)); per-app rules dropped
> ([D187](decisions.md#d187)).
- The **bindings window is static text**: it ignores the user's rules and omits `click hiss`. It becomes live.
- The mode toggle is hidden for the phone mic.
- `scrollStep` has no control.
- The decider, mic effects, feed fling and ASR settings have no screen.

## 10. Feedback: no talking
- **No TTS and no audio voice** (user). Replies are text only: a silent pixel **speech bubble** from the badge.
- It shows gesture results ("home", "scroll ↓"), voice-command results, and **queued motions** (done, running, queued), with
  **cancel** (tap `×`, or hiss).
- Continuous actions show a live count until cancelled.
- Proposed as well:
  - a haptic pattern per result (there is no vibration in the app today);
  - a "heard but ignored" cue with the reason;
  - badge reactions per gesture;
  - a level meter while humming;
  - a cursor target outline and a click pulse.
- **Open:** which of these? (The recommendation is all but the cursor trail.)
- Static mockups at phone size go to the user first.

## 11. Round 6 suite failures (suspects, from the survey)

> **Status (2026-09-28).** Resolved on the `r7-suite` branch (merged 09-28): the "stale tests" suspects were right; the
> swipe suspect was the fixture pager, not the app. The feed fling pages real pagers with a wide margin, so it is not
> the likely cause of the phone's feed failures. The socket crash was not reproduced.
- Probably stale tests:
  - no `screen:` line on the local fast path;
  - "next" now goes through `swipeNamed` with no state event;
  - "like" is outward and asks for a confirm;
  - intent-cursor phrases are now matched locally.
- A real suspect: swipes that don't move the fixture pager, possibly the shorter feed-fling path (`Executor.kt:292`,
  `feed_fling_ms/pct`). This may also be part of why feeds fail on the phone.

## 12. Glide scroll
- `ScrollStep` drags, holds and lifts with zero velocity, so lists stop dead. That was deliberate in round 5, and it feels stiff.
- Plan: a **glide** setting (off / soft / long) that sets the lift speed, plus an eased stroke curve. Paged feeds keep the fling.
- **Open:** default to soft? Should hold-to-scroll get the same treatment?

## 13. Margins
- Screens already have about 22 dp of side inset.
- **Open:** which surface (the Canti screens, the badge or overlay, the cover screen)? Mock it up first.
