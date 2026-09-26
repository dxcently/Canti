# The Android app: full plan

**Status: agreed with the user 2026-09-26. Phase A (spikes) approved; the demo needs phases A–B.**

**Summary.** The pipeline behind the app is mostly built: sound grouping, the model's input text, rules/model deciders, the executor with its screen-change check, intent cursor mode, enrollment and matching, and the event log. It runs inside the accessibility service. The app has almost no UI yet: one settings form. This plan adds four things. **Phone-mic listening** makes the app work before the Pico exists. **On-phone model inference** means it works without a PC. A **HUD with haptics** shows what VOX heard and did. A **touch UI** covers setup, sounds, bindings, the log and settings, and every screen is labelled so that VOX can later operate its own screens by voice.

## Agreed inputs

| Question | Answer |
|---|---|
| Who uses it | All three kinds of user: people who can't use their hands, people whose hands are busy, and a class demo. **The first target is the demo.** The design must not rule out hands-free use later. |
| Sound source before the Pico | **The phone mic.** The extractor is ported to Kotlin and runs in the app. |
| Where the model runs | Available both **on the phone and on a PC server**. **Working on the phone comes first.** |
| Feedback | **HUD and haptics first.** Spoken output (TTS) and earcons are available as toggles, off by default, and low priority. |
| Distribution | Sideloaded APK. No Play Store, so no Play review of the accessibility service. |
| PC | **Both:** the model can run on a PC server (exists), and VOX will later also *control* a PC (phase F, to be planned separately). |
| UI technology | **Flutter** (agreed 2026-09-26), embedded in the Kotlin app with add-to-app: the module lives in `~/VOX/ui/`, and screens talk to the service through a Dart `VoxBackend` interface (a platform channel on Android). The same screens are reused later for the PC app and an iPhone setup companion. The accessibility service, BLE, mic and HUD stay native Kotlin. Cost accepted: AndroidX enters with the Flutter embedding, and the APK grows by about 8–10 MB. The user is new to Dart. |
| Demo | On **the user's own Android phone** (model and version still to confirm). **Phases A–B must be done for the demo.** |

## Architecture

```
 sound sources                      personalization         decision                       action + feedback
┌──────────────────────┐   line    ┌──────────────┐  state  ┌───────────────────────┐ act ┌──────────────────────┐
│ PhoneMicSource (new) │──────────►│ Matcher      │────────►│ rules (explicit       │────►│ Executor (exists)     │
│  AudioRecord 16 kHz  │  + fp1    │ (exists)     │  text   │  bindings, local)     │     │ Confirmer (exists)    │
│  + Kotlin extractor  │  pitch16  │ line rewrite │         │ OnDeviceModel (new):  │     │ HUD overlay (extend)  │
│ BleSource (stub→Pico)│           └──────────────┘         │  ONNX jevlike         │     │ Haptics (new)         │
│ Debug socket / PC    │                  ▲                 │ HttpModel (exists):   │     │ TTS, earcons (new,    │
│  relay (exists)      │                  │ enroll          │  PC server / Jev      │     │  optional)            │
└──────────────────────┘          Sounds screen             └───────────────────────┘     └──────────────────────┘
        ▲ gate while VOX's own sound is playing                        ▲ profiles and rules from the Bindings screen
```

## 1. Listening on the phone mic (new)

- **Kotlin port of `extractor/vox_extract`**: the frontend, segmenter, classify, lines and fp1, streaming frame by frame. The Pico firmware will port the same code, so the Kotlin port doubles as a second implementation.
- **Parity test.** The Kotlin port must reproduce `extractor/vectors/` (PCM in, events out) exactly like the Python reference. This runs as a JVM unit test.
- **Capture.** `AudioRecord` at 16 kHz mono, inside the accessibility service. It runs as a foreground service of type `microphone`, with a persistent notification that has Pause and Stop buttons.
  - **Spike first:** background mic use on Android 14/15 (while-in-use restrictions). Check it on the emulator and a real phone before building on it.
- **Echo and media.** Video audio (TikTok, YouTube) reaches the phone mic. That doesn't happen with a close-talk Pico mic.
  1. Use the `VOICE_COMMUNICATION` source with `AcousticEchoCanceler` where available.
  2. Mute the extractor while VOX's own haptics, TTS or earcons play.
  3. Measure false triggers with media playing, using MUSAN music played through the speaker.
  - If it's still bad, fall back to recommending a wired or Bluetooth headset mic for the demo.
- **Calibration.** A 5-second "hum at your normal level" step sets `loud_calib_db`, per mic.
- **Enrollment follows the mic.** An example recorded on the phone mic only matches on the phone mic. Each enrollment class records which source it came from.

## 2. Decision model on the phone (new)

- **OnDeviceModel.** ONNX Runtime for Android, running the jevlike student (e5-small encoder + attention head) exported to int8 ONNX. This needs a WordPiece tokenizer in Kotlin, checked against the Python tokenizer on the test sets. It is a native dependency added next to the Flutter embedding.
- **Size and speed targets:** model about 35 MB int8; under 50 ms per decision on a mid-range phone. To be measured.
- **Two tasks, two heads.** Gesture decisions (data v5, and v6 when ready) and targets (targets-v2, where training is queued). The target model must be trained before intent cursor mode can work on the phone.
- **Choosing a backend.** Settings offers **On phone** (the default), **PC server** (the existing `/v1/systemone`, as the local student or `decider-4b` over the LAN or `adb reverse`) and **Jev** (TypeSafe, needs a key). The hybrid rule stays: explicit bindings are decided locally, and only anything else goes to the model.
- **Calibration gap.** The student's confidence is about 1.000 on everything, so `min_confidence` and `target_min_confidence` do nothing yet. Temperature scaling has to be fitted on real (not synthetic) logged data before those gates mean anything.

## 3. Staying safe and in control

The accessibility service can tap anything, so stopping it must never depend on the model or the mic.

| Stop / pause path | How |
|---|---|
| Notification | Pause/Resume and Stop buttons on the always-visible foreground notification |
| Android accessibility shortcut | Hold both volume keys for 3 s to turn the service off. This is built into Android and gets enabled during onboarding |
| HUD | Tap the HUD to pause |
| Pico button / switch jack | Later, as agreed |
| Automatic | Pauses during phone calls, while the screen is off, and while the VOX app itself is being edited (so a hum doesn't trigger things mid-enrollment) |

- **States:** Off → Paused → Armed (gesture mode) ⇄ Cursor mode, plus the Listening-for-phrase window. The HUD always shows which state is active.
- **Protected apps:** an app list where VOX pauses automatically, such as banking, the dialer or settings. Set during onboarding and editable later.

## 4. Feedback: HUD and haptics first

**HUD** (extends the existing `Overlay.kt` badge; `TYPE_ACCESSIBILITY_OVERLAY`, so no draw-over-apps permission is needed):
- A small draggable pill with a state dot (armed / paused / cursor / listening).
- It shows the last sound as its short name (`rise`, `pop`, `my: meow`) and its outcome, for example `→ scroll up ✓`, `→ nothing (unbound)`, or `✗ no visible change`.
- It fades to a dot after 2 s.
- It shows a live level meter while a sound is in progress, so the user sees that VOX is hearing them.
- Tap to pause; long-press to open the app.
- A **demo size** option: large text, plus the live pitch trace and the rewritten line, for showing on a projector.

**Haptics** (Vibrator): one pattern per outcome, each distinguishable without looking:

| Outcome | Pattern |
|---|---|
| Action done and confirmed | one short tick |
| Heard, but nothing bound (or an ignore sound) | two soft ticks |
| Did an action but saw no visible change | one long buzz |
| Paused / armed | a falling or rising double pulse |
| Cursor mode on / off | a triple tick |

**TTS / earcons:** off by default. When on, the mic is gated while they play (see §1).

## 5. Screens (touch-first for the demo; every control has an accessibility label)

Building the screens in Flutter with explicit `Semantics` labels on every control has a side effect: **VOX's intent cursor mode can operate VOX's own screens.** "The pause button", "the sounds tab" and so on then work hands-free for free. Only stopping needs to be independent of the model (§3).

1. **Onboarding (a first-run wizard; each step can be done again later from Settings):**
   1. what VOX does, and the privacy note (what leaves the phone depends on the backend);
   2. microphone permission;
   3. enable the accessibility service, via a deep link and an explanation of why it needs this;
   4. enable the volume-key shortcut;
   5. pick the sound source (phone mic, Pico later, or PC relay);
   6. pick the model (on phone by default);
   7. calibration hum;
   8. **"Try it"**: do each gesture in turn with live HUD feedback (rise ✓, fall ✓, pop ✓, …). This is also the first demo moment;
   9. protected apps;
   10. done.
2. **Home:** a big Armed/Paused switch. Source, model and service health each show a green/red status with a fix-it button. Below that: the current mode, the app profile in effect, the last 10 sounds with their outcomes, and a **Practice** button that runs "Try it" again.
3. **Sounds:**
   - the **built-in gestures**, each with its current binding;
   - **my custom sounds**;
   - **my ignore sounds**.
   - **Add sound** opens enrollment: record 3–5 takes, with each take shown as it lands and whether it's consistent with the others. Then name it and choose custom, ignore, or "my version of <gesture>". It checks for clashes with existing classes, and ends with "Bind it now?".
4. **Bindings & rules:**
   - profiles: Everywhere, per app (a picker of installed apps), Cursor mode, Phrases;
   - in each profile, binding rows (sound or sequence → an action from the action list) plus plain-language rules as free text, for example "in Maps, a rising hum zooms in";
   - **Test:** pick or perform a sound and see what the decider would do in this profile, without acting;
   - conflict warnings, for example when the same sound is bound twice in one scope;
   - import/export of profile JSON.
5. **Log:** a live list of the lines received, each showing:
   - the rewritten line;
   - the source (rules or model), the choice and its top-3 probabilities;
   - the action and its confirmation;
   - the latency.

   Filter by app or outcome, and clear the log. **Export is manual only**, because the log contains on-screen text. Exported logs, with consent, become the real-data test set and the calibration data (§2).
6. **Settings:**
   - feedback (HUD size and position, haptics on/off and strength, TTS, earcons);
   - model backend (on phone, PC server, Jev: URL, model, key);
   - thresholds and timing (the existing keys);
   - sound source;
   - protected apps;
   - developer (debug socket, vocabulary digest, the raw config);
   - reset.

## 6. Testing

- **JVM:** extractor parity (vectors), tokenizer parity, ONNX model parity (the same probabilities as PyTorch to 1e-3 on 200 rows), the existing state-text parity and the matcher tests.
- **Emulator suite:**
  - a **WAV file source** feeds recorded or synthetic audio through the full phone pipeline with no real mic;
  - screenshot and assertion tests per screen;
  - the onboarding flow;
  - stop paths (notification, shortcut, protected app);
  - self-operation (intent cursor on VOX's own UI).
- **Real phone:** background mic, echo with media playing, latency, battery drain per hour armed.

## 7. Phases

| Phase | Delivers | Done when |
|---|---|---|
| **A. Spikes** | Background mic on Android 14/15; the on-phone model runtime (ONNX vs ExecuTorch) on a real phone (size, latency); echo with media playing; whether VOX's accessibility reader (`Targets.kt`) can see and tap Flutter widgets | Each spike has a measured answer, and the plan is adjusted to match |
| **B. Demo core** | Kotlin extractor + parity, PhoneMicSource, OnDeviceModel (gesture task), HUD + haptics, stop paths, Home, a light onboarding with "Try it", Log | Scroll a feed, go back and zoom a map by hum on a real phone, with no PC, shown on the HUD |
| **C. Make it yours** | The Sounds screen and enrollment UI; the Bindings & rules editor with Test; protected apps; demo-size HUD | A new custom sound is enrolled and bound on the phone, and ignore sounds do nothing |
| **D. Cursor mode on phone** | The target model trained (targets-v2) and exported; intent cursor on the on-phone backend; VOX operating its own screens | "The subscriptions tab" taps the right element on phone-only inference |
| **E. Hardware and polish** | BleSource for the Pico, TTS/earcons, confidence calibration from logs, full onboarding | The Pico replaces the phone mic without UI changes |
| **F. VOX controls a PC** | Bluetooth HID mouse/keyboard from the Pico, or a desktop agent; needs its own plan | To be planned |

## Open questions

- The demo phone's model and Android version decide the background-mic rules and the latency target. **open**
- The protected-apps defaults, and whether screen text may ever leave the phone (the Jev backend sends it).
