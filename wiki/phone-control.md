# Phone control: Android does the work, iPhone gets HID

[Index](index.md) · [Hardware](hardware.md) · [Signal processing](signal-processing.md) · [Gestures and phrases](gesture-vocabulary.md) · [Decision models](decision-models.md) · [Phone control](phone-control.md) · [Prior art](prior-art.md) · [Latency and risks](latency-and-risks.md) · [Roadmap](roadmap.md) · [Sources](sources.md)

**Summary.**

- **Link.** The Pico talks to the phone over an encrypted custom BLE GATT service.
- **Android.** A Kotlin AccessibilityService tracks the foreground app, resolves profiles, calls the decision model and injects gestures, with an overlay built on Project Gameface.
- **Spoken phrases** are an opt-in, push-to-talk module, and lightly researched.
- **Phase 1** (no app) is BLE HID.
- **iPhone** stays on HID for good. VOX adds less there than one might hope, because of Apple's Sound Actions.

## The BLE link

The link follows the pico-examples `ble_temp_sensor` pattern: a compiled `.gatt` file, a CCCD write, then `att_server_request_can_send_now_event` and `att_server_notify` ([pico-examples](https://github.com/raspberrypi/pico-examples/tree/master/bluetooth/ble_temp_sensor)). The custom service follows `gatt_streamer_server`, with a 128-bit UUID and `ENCRYPTION_KEY_SIZE_16` ([BTstack](https://github.com/bluekitchen/btstack/blob/master/example/gatt_streamer_server.gatt)).

| Characteristic | Direction | Payload | Rate |
|---|---|---|---|
| EVENT | Pico → phone (notify) | seq, gesture/phrase labels, match distance, categorical buckets (~8–20 B) | per event |
| CONTOUR | Pico → phone | 64-point int8 contour (64 B); Android 14+ negotiates a 517-byte MTU ([requestMtu](https://developer.android.com/reference/android/bluetooth/BluetoothGatt#requestMtu(int))) | per event |
| STREAM | Pico → phone | pitch offset (st), voicing, loudness bucket | 10–30 Hz, cursor mode or glides only |
| CONFIG | phone → Pico (write) | templates, thresholds, arm state | on change |
| AUDIO (optional) | Pico → phone | ADPCM audio for spoken phrases, armed window only | ~64 kbps [EST] |

HIGH connection priority maps to 11.25–15 ms intervals in AOSP ([AOSP Bluetooth](https://android.googlesource.com/platform/packages/apps/Bluetooth/+/31c02c5a770c0c12becb0856b2c7132470a49939%5E2..31c02c5a770c0c12becb0856b2c7132470a49939/)), so the BLE hop is about **15–50 ms** [EST].

**Security.** Any peer that writes to this service drives an accessibility service. A Pico with no display pairs only with "Just Works", which is encrypted but unauthenticated. So VOX should require bonding and **accept pairing only while the physical button is held** [design].

## The Android app

A single Kotlin AccessibilityService with `canPerformGestures="true"` owns:

- the GATT client
- **foreground-app tracking**: `TYPE_WINDOW_STATE_CHANGED` plus `getPackageName()` ([AccessibilityEvent](https://developer.android.com/reference/android/view/accessibility/AccessibilityEvent))
- the phrase parser and profile resolver ([Gestures](gesture-vocabulary.md#profiles-global-plus-per-app-fixed-or-rule))
- the model client (Jev, the VOX student or a workstation Jev-like behind one `/v1/systemone` URL) ([Decision models](decision-models.md))
- the executor
- the overlay

| API | Fact | Source |
|---|---|---|
| `dispatchGesture` (API 24) | Cancels "any gestures currently in progress, whether from the user, this service, or another service" | [AccessibilityService](https://developer.android.com/reference/android/accessibilityservice/AccessibilityService) |
| Gesture limits | 20 strokes, 60 s | [GestureDescription.java](https://github.com/aosp-mirror/platform_frameworks_base/blob/main/core/java/android/accessibilityservice/GestureDescription.java) |
| `continueStroke` (API 26) | Keeps a finger down across dispatches, so drag is possible | [StrokeDescription](https://developer.android.com/reference/android/accessibilityservice/GestureDescription.StrokeDescription) |
| `performGlobalAction` | Back, Home, Recents, Notifications | [AccessibilityService](https://developer.android.com/reference/android/accessibilityservice/AccessibilityService) |
| Overlay | `TYPE_ACCESSIBILITY_OVERLAY` cursor windows; 100 ms swipes, 250 ms taps | [project-gameface](https://github.com/google/project-gameface) |

**Template: Google's Project Gameface for Android** (Apache-2.0). It has the same structure with a face tracker in place of the mic ([project-gameface](https://github.com/google/project-gameface); [Google Developers Blog](https://developers.googleblog.com/project-gameface-launches-on-android/)). The overlay shows the armed state, the last gesture, and the **mode badge** (GESTURE / CURSOR / GRID) for [Jev cursor mode](decision-models.md#jev-cursor-mode-is-design-b-applied-to-pointing).

**Installing and policy:**

- **Install with Android Studio or ADB.** The press reports that ADB installs are exempt from Android 13–15's restricted-settings block ([Android Authority](https://www.androidauthority.com/android-15-restricted-settings-sideloading-3481098/)).
- Declare `isAccessibilityTool="true"`. Android 17's opt-in Advanced Protection Mode revokes accessibility access from apps that don't ([Android Authority](https://www.androidauthority.com/android-advanced-protection-mode-accessibility-apk-teardown-3640742/)).
- Play lists "switch-based input systems" as eligible, but prohibits accessibility use that lets an app "autonomously initiate, plan, and execute actions" ([Play policy](https://support.google.com/googleplay/android-developer/answer/10964491)). Model-interpreted rules and cursor mode are defensible only because **every action traces back to a user's sound or phrase**.

## Screen context, action checks and the emulator suite

**Decided 2026-09-26.** The app reads the accessibility tree for three jobs:

1. **Screen context for the model, as a tie-breaker only.** The tree is summarised into one categorical line, identical to the training data: `screen: <kind>; media <playing|paused|none>; scroll <...>; keyboard <open|hidden>`. The vocabulary is `SCREEN_*` in `finetune/vox/schema.py`.
   - It settles phrases whose meaning depends on the screen. "Next" in a video feed means swipe up; in a photo viewer or document it means swipe left. "Pause" while already paused means do nothing, because play/pause is a toggle.
   - It **never** changes an explicit gesture or rule. The training data includes gestures paired with screens that would tempt a veto, such as swipe down "at the top" of a list.
2. **Action confirmation.** After each dispatch, the app waits for a matching event (window state change, content change, scroll, click) and logs "confirmed" or "no visible change". This shows missed swipes and gives the user feedback.
3. **Harvesting real screens** to check the generator's screen distribution against real apps.

Accessibility trees are weak in games, canvases and some video surfaces, so the line can be "other" or missing. iPhone (the HID path) has no tree at all, so the line is omitted and the model falls back to defaults.

**Emulator test suite (in progress, `~/VOX/android/`).**
- A headless AVD via nixpkgs `androidenv`, running on KVM.
- It installs the companion app, a fixture app of our own (feed, list, toggle button, text field) and open-source stand-ins from F-Droid: NewPipe, VLC, Organic Maps, Fossify Gallery and a browser. No real TikTok or Instagram: those need logins and would make runs flaky.
- Tests replay feature messages through a debug input using a deterministic rule decider, then assert the screen changed.

## Spoken phrases (opt-in module)

**Lightly researched. Everything here is a starting point to verify.** Spoken phrases ("next", "open camera") are off by default. The recommendation is **push-to-talk**: a sound gesture arms the recogniser for a few seconds, rather than always listening, to limit false triggers, battery use and privacy exposure. Recognised text goes into the decision model's state next to the gesture labels and per-app rules ([Decision models](decision-models.md)). That open-ended text against plain-language rules is the input a text-in decision model is actually good at.

**Audio source:**

| Source | Pros | Cons |
|---|---|---|
| Phone mic | Simple; no extra BLE bandwidth | Needs a `microphone`-type foreground service (`FOREGROUND_SERVICE_MICROPHONE` + `RECORD_AUDIO`). The app "cannot create a microphone foreground service while your app is in the background", with a few exceptions ([FGS types](https://developer.android.com/develop/background-work/services/fgs/service-types)). The privacy indicator shows. **Whether an accessibility service is exempt is unverified** |
| Pico mic over BLE | Same mic as gestures; no phone mic permission | 16 kHz 16-bit = 256 kbps raw, ~64 kbps with 4-bit ADPCM. BLE 2M PHY plausibly carries it [EST]. CYW43439/BTstack 2M PHY unverified. Only the few-second armed window needs streaming |

**Recognisers:**

| Recogniser | Notes |
|---|---|
| Android `SpeechRecognizer`, on-device mode | System recogniser; the docs could not be fetched. API level and continuous-use limits **to verify** |
| Vosk small models | "Portable per-language models are only 50Mb", offline on Android/iOS/Pi, "quick reconfiguration of vocabulary", which suits a restricted phrase grammar ([Vosk](https://alphacephei.com/vosk/)) |
| Picovoice Porcupine / Rhino | Free plan: 1 monthly active user ([pricing](https://picovoice.ai/pricing/)). Free-tier AccessKeys reportedly stopped after 30 June 2026 ([Home Assistant community](https://community.home-assistant.io/t/fyi-picovoice-confirmed-free-tier-accesskeys-will-stop-working-after-june-30-2026/1012744)) |
| whisper.cpp tiny/base | MIT. Tiny 75 MiB disk (~273 MB RAM), base 142 MiB (~388 MB) ([whisper.cpp](https://github.com/ggml-org/whisper.cpp)). Too heavy for always-on; fine for push-to-talk |
| iOS `SFSpeechRecognizer` | `requiresOnDeviceRecognition` keeps audio on the device ([Apple docs](https://developer.apple.com/documentation/speech/sfspeechrecognitionrequest/requiresondevicerecognition)). An iOS app still cannot act on other apps. **Vocal Shortcuts** already exists ([9to5Mac](https://9to5mac.com/2024/08/09/ios-18-can-perform-actions-based-on-any-voice-command-you-set/)) |

## Phase 1: BLE HID without an app

The Pico is a composite HOG device: relative mouse with wheel, keyboard and consumer control ([BTstack hog_mouse_demo.c](https://github.com/bluekitchen/btstack/blob/master/example/hog_mouse_demo.c)).

- **Swipes on Android:** button-down, dx/dy over about 150–300 ms, then button-up.
- **Keys:** Back, Home and All Apps are consumer usages **0x224, 0x223, 0x2A2** ([hid-input.c](https://github.com/torvalds/linux/blob/master/drivers/hid/hid-input.c); [Generic.kl](https://github.com/aosp-mirror/platform_frameworks_base/blob/main/data/keyboards/Generic.kl)).
- **No touchscreen descriptor:** "with android, some are ok, some are not working" ([BLE_HID_TouchScreen](https://github.com/AiueoABC/BLE_HID_TouchScreen)).
- **No per-app profiles, no model and no cursor mode in Phase 1.**

## iPhone: HID, and an honest pitch

iOS won't let VOX inject touches. Valid `UITouch` events "can only be created by the system" ([Apple Developer Forums](https://developer.apple.com/forums/thread/129316)), and touch simulators need a jailbreak ([IOS13-SimulateTouch](https://github.com/xuan32546/IOS13-SimulateTouch)). There are two HID routes:

- **BLE mouse through AssistiveTouch** ([Apple Support 111775](https://support.apple.com/en-us/111775); [AssistiveTouch guide](https://support.apple.com/guide/iphone/use-assistivetouch-iph96b21954/ios)).
- **BLE keys as Switch Control switches**, mapped to actions or page-turning Recipes ([Switch Control guide](https://support.apple.com/guide/iphone/set-up-and-turn-on-switch-control-iph400b2f114/ios); [Adafruit](https://learn.adafruit.com/ios-switch-control-using-ble/configuring-ios-switch-control)).

| Feature | iOS built-in | What VOX adds on iPhone |
|---|---|---|
| Mouth pop / S-sound → gesture | **Sound Actions** in AssistiveTouch ([AssistiveTouch guide](https://support.apple.com/guide/iphone/use-assistivetouch-iph96b21954/ios); [AbilityNet](https://mcmw.abilitynet.org.uk/how-to-perform-actions-on-your-iphone-or-ipad-using-sounds-as-part-of-assistivetouch-in-ios-18)) | Nothing |
| Custom spoken trigger | **Vocal Shortcuts** ([9to5Mac](https://9to5mac.com/2024/08/09/ios-18-can-perform-actions-based-on-any-voice-command-you-set/)) | Nothing |
| Pitch-contour gestures | Not in any Apple source found (full list not located) | **Yes**, as switch keys |
| Fixed sound phrases | No | **Yes**, compiled on the Pico into keys |
| Re-recordable templates | Limited | **Yes** |
| Per-app profiles, model rules, cursor mode | n/a | **Impossible**: no foreground-app signal, no app-side injection |
| External mic | n/a | Possible benefit, untested |

## Open questions / to verify on hardware

- Can an **AccessibilityService start a microphone FGS from the background** for push-to-talk, or must capture begin in the foreground?
- Android `SpeechRecognizer` **on-device mode**: API level and limits. The docs could not be fetched.
- Does **BLE 2M PHY** work on CYW43439 + BTstack for audio streaming?
- Measure real **BLE notify latency** on the target phone at HIGH priority.
- Does `dispatchGesture` swipe **reliably scroll TikTok, Maps and the reader** at 100–300 ms durations?
- Does a **Switch Control Recipe hold a custom swipe on iOS 26**? This is inferred, not verified.
- Does **Just Works bonding with button-gated pairing** hold up on both OSes?
- Does the overlay behave on the **lock screen and in full-screen video apps**?
