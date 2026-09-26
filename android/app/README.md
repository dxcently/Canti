# app: the VOX companion app (`ai.vox.companion`)

An Android AccessibilityService that turns device feature messages into phone actions. It receives one message per
sound (format in [../PROTOCOL.md](../PROTOCOL.md)) and runs these steps in order:
1. rewrites sounds that match the user's enrolled examples;
2. groups the sounds into sequences;
3. builds the exact state text the model is trained on;
4. decides an action (local rule table or `POST /v1/systemone`);
5. performs the action with gestures or global actions;
6. checks that the screen visibly changed.

The service is written in Kotlin with no dependencies beyond the Kotlin stdlib and the platform APIs. The launcher
screen is the Flutter module in `../../ui`, built in from source (the `:flutter` Gradle project; see ../README.md
"Flutter UI"). The Flutter embedding needs AndroidX, so `android.useAndroidX=true` is set. minSdk is 30 and target is
35. Every step is written to the event log.

## Source files

All files are in `src/main/java/ai/vox/companion/`.

| File | What it does |
|---|---|
| `VoxService.kt` | The AccessibilityService and the pipeline. It sets things up and handles:<br>• feature sources and personalization;<br>• the sequencer;<br>• state building and the decider call (on a worker thread);<br>• execution and confirmation;<br>• intent cursor mode (target question, highlights, choice by sound);<br>• the debug control ops (`ping`, `config`, `profile`, `screen`, `dump`, `harvest`, `targets`, `pause`, `reset`, `enroll_*`, `fp_floors`, `ble_*`, `device`);<br>• the phone-side pause and `uiStatus()` for the Flutter screen. |
| `Message.kt` | `FeatureMessage`: parses and validates a device message (sounds, labels, mode, armed, `sleeping`, phrase, `timing`, `features`). `SoundLine` reads the fields of a sound line. |
| `Personal.kt` | Personalization:<br>• `SoundFeatures` is the per-sound `fp`, `fp_version` and `pitch16`;<br>• `EnrollmentStore` holds the enrolled custom, ignore and gesture classes per profile, persisted as JSON;<br>• `FpFloors` is the per-feature std floor table, keyed by `fp_version`;<br>• `Matcher` does standardised nearest-neighbour matching (std raised to the floor), banded DTW for contour classes, and per-class leave-one-out reject thresholds;<br>• the line rewrite;<br>• `Personal.localReason` keeps custom and ignore sounds away from the model. |
| `Sequencer.kt` | Groups sounds into sequences. It waits only when a bound longer sequence starts with the sounds heard so far. It uses device timestamps when present and arrival times otherwise. |
| `StateBuilder.kt` | `Scene.text()`, the model state, byte-identical to finetune `generate.py`. Also `ScreenContext`, the `screen:` line. |
| `ScreenSummarizer.kt` | `NodeSnap`, a plain copy of an accessibility node, and the classifier that picks the screen kind, media, scroll and keyboard values. |
| `TreeReader.kt` | Reads the active app window into `NodeSnap`s. Also finds the app root (VOX's own app windows count, so its Flutter screen is readable; its overlays never do) and computes the tree fingerprint the confirmer uses. |
| `Decider.kt` | `Decision`, the `Decider` interface, and `RuleDecider`: the local policy (defaults, profile bindings, phrases, the screen tie-break, cursor mode, not-deliberate sounds). |
| `HttpDecider.kt` | `SystemOneClient` (the `/v1/systemone` choice question), `HttpDecider` (the action question) and `ChainDecider` (`rules`, `model` or `hybrid`, falling back to rules on error). |
| `Profile.kt` | User bindings: global, per app, cursor and spoken phrases, plus fixed rules on custom sounds (`my:<name>`). It also produces the rule sentences the model sees and the bound sequences the sequencer waits for. |
| `Executor.kt` | Performs an action: swipes, taps, pinches, scrolls, global actions (back, home, ...), volume, `open_camera`, cursor moves, target taps. |
| `Confirmer.kt` | Decides whether an action visibly changed the screen. It uses accessibility events first, then a masked screenshot grid (`PixelGrid`), and ignores the echo of our own touch. |
| `Overlay.kt` | Accessibility overlays: the status badge, the cursor, and the numbered target highlights. |
| `Targets.kt` | Intent cursor mode. Builds `label (role, position)` options from the accessibility tree, the `target` state text, and the answer policy (tap, choose from the top 3, or not on screen). |
| `FeatureSource.kt` | The `FeatureSource`/`Sink` interfaces, the debug socket (`vox-debug`, adb only), the debug broadcast, and the `PhraseRecognizer` stub (speech recognition is not implemented). |
| `BleLink.kt` | The BLE link without Android (PROTOCOL.md "BLE GATT link (v1)"):<br>• `BleProtocol` holds the UUIDs and the device-side `fragment`, used by tests;<br>• `Reassembler` rebuilds messages from EVENT notifications (first/last bits, counter from 0 per connection, gaps, the 4096-byte limit);<br>• `BleMessages.decode` accepts strict UTF-8 holding one JSON feature message, never a control message;<br>• `BleInfo` parses INFO;<br>• `AuthFailures` counts pairing/encryption failures and words the hint for each kind (stale bond: forget VOX-XXXX; pairing window closed: hold the button 5 s; unknown: both);<br>• `Backoff` computes the reconnect delays. |
| `BleFeatureSource.kt` | The BLE GATT client. It scans by service UUID, connects, requests MTU 517, requests high connection priority, reads INFO, bonds (Just Works), and enables EVENT notifications. It reassembles messages into the same `Sink` (the first message of each link marked `ble-connect`, a reset point for message ids), disarms on disconnect, and reconnects with backoff. After two pairing/encryption failures it stops in `needs_pairing` with a hint for the user. It writes CONFIG for `DeviceLink`, and after a `sleeping` message reconnects quietly (every 2 s, auto-connect, no pairing escalation). Its controls are the `ble_*` ops, and it remembers the device in `ble_device`. |
| `Settings.kt` | SharedPreferences keys and defaults. The API key is never logged. |
| `EventLog.kt` | The JSON event log, written to logcat tag `VOX` and to `files/events.jsonl`; also `files/harvest.jsonl`. Listeners (the UI event channel) get each event as it is written. |
| `MainActivity.kt` | The launcher: a `FlutterActivity` showing the `../../ui` status screen. It logs `ui{first_frame}` once per process. |
| `DeviceLink.kt` | The app's view of the device and its commands, without Android: arm/pause/mode/sleep CONFIG writes on a ready link, one at a time, confirmed by the device's next no-sound state message, failed at once when that reply carries `rejected`, or failed after 1.5 s with no reply (`device_cmd` events); asleep/awake tracking from `sleeping`; the device's `presence()` for the status screen; the pairing-failure count and hint. |
| `UiBridge.kt` | The platform channels between the Flutter screen and the service (`ai.vox/backend`, `ai.vox/events`; PROTOCOL.md "UI channel"), including `deviceCommand` (answered when the device confirms or the command fails) and `connectDevice`. |
| `LegacySettingsActivity.kt` | The old native settings screen, opened from the status screen's **Legacy settings** button: decider mode, model endpoint, API key, a link to accessibility settings, and the **Allow Bluetooth (VOX device)** permission button. |
| `Vocab.kt`, `TargetVocab.kt` | **Generated** by `../tools/gen_vocab.py` from `finetune/vox`. Do not edit by hand. |

Other files:

| Path | What it is |
|---|---|
| `src/main/assets/profile_default.json` | The bundled profile: rise→zoom_in and fall→zoom_out in Organic Maps. |
| `src/main/assets/fp_floors.json` | **Generated** by `../tools/fp_floors.py`: the per-feature std floors by `fp_version` (`fp1`, provisional). Replace an entry with the extractor's scales and set `"provisional": false`; no code change. |
| `src/main/res/xml/vox_accessibility.xml` | The accessibility service configuration. |
| `src/test/java/ai/vox/companion/CoreTest.kt` | JVM tests: state text parity with `generate.py`, the rule decider against 380 generator labels, the sequencer and timestamps, the message parser, profiles, the screen summariser, the confirmer, the HTTP decider. |
| `src/test/java/ai/vox/companion/PersonalTest.kt` | JVM tests for personalization: standardisation, DTW, leave-one-out thresholds, the std floor and its table, matching, the store, `features` parsing, the line rewrite, and deciding locally. |
| `src/test/java/ai/vox/companion/DeviceLinkTest.kt` | JVM tests for device control with a fake link and clock: each command's CONFIG write and confirmation, only a no-sound message confirming, a `rejected` reply failing at once with the device's reason, the 1.5 s timeout shown to the user, ready-link and one-at-a-time refusals, a failed write, `sleeping` leading to asleep and a quiet reconnect, waking with `armed: true`, an unexpected disconnect coming back disarmed with nothing written, and the pairing hints. |
| `src/test/java/ai/vox/companion/BleTest.kt` | JVM tests for the BLE link: fragmentation and reassembly (MTU 23–517, first/last bits, counter from 0 and wraparound at 64, gaps, protocol violations, the 4096-byte limit, garbage), message decoding and parsing, INFO, backoff, pairing-failure handling, the firmware's canned test lines, and the 240 real messages in `firmware/tests/captured_messages.jsonl` (parsed, and fragmented and reassembled at MTU 23, 185 and 517). |
| `src/test/resources/state_parity.json` | Fixture written by `../tools/state_parity.py`: 300 scenes, 380 labelled rows and 120 target rows. |

The `TargetTest` class (intent cursor options) is in `CoreTest.kt`.

## Commands

Run these from `android/`.

```sh
./dev bash -c 'cd ../ui && flutter pub get'       # once, and after ui/pubspec.yaml changes: generates ui/.android/include_flutter.groovy
./dev gradle assembleDebug                         # app/build/outputs/apk/debug/app-debug.apk
./dev gradle :app:testDebugUnitTest                # 75 JVM tests (CoreTest 25, TargetTest 7, PersonalTest 13, BleTest 21, DeviceLinkTest 9)
./dev gradle :app:testDebugUnitTest --tests 'ai.vox.companion.PersonalTest'
./dev python3 tools/gen_vocab.py --check           # fail if Vocab.kt / TargetVocab.kt are stale
suite/run.sh test                                  # the emulator tests (see ../suite/README.md)
```
