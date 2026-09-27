# VOX Android companion app

This is the phone half of VOX. The device (a Pico 2 W, later) sends one feature message per vocal gesture
(format in [PROTOCOL.md](PROTOCOL.md)). The app then:

1. matches each sound's fingerprint against the user's enrolled sounds and rewrites its line if one matches
   (personalization);
2. turns the message into the same state text the model is trained on (finetune `Scene.text()` plus the `screen:` line);
3. decides an action, with the local rule table or the `/v1/systemone` model;
4. performs it through an AccessibilityService;
5. logs whether the screen visibly changed.

```
feature source ─► sequencer (timing rule) ─► state builder ─► decider (rules | model | hybrid) ─► executor ─► confirmer
  (BLE GATT,          wait only if a bound       Scene.text +      explicit binding → local;       dispatchGesture,   a11y events within
   debug socket,      longer sequence starts     screen line       else POST /v1/systemone         global actions,    confirm_timeout_ms →
   debug broadcast)   with what was heard;                                                         overlay cursor     "confirmed (events|pixels)" |
                      device timestamps first                                                                         "no visible change"
```

## Layout

Each folder has its own README with a file table and commands.

| path | what the code in it does |
|---|---|
| [`app/`](app/README.md) | The companion app, `ai.vox.companion` (Kotlin, minSdk 30, target 35; its launcher screen is the Flutter module in [`../ui`](../ui/README.md)). An AccessibilityService that receives feature messages, rewrites personalized sounds, groups sounds into sequences, builds the model state text, decides an action (rule table or `/v1/systemone`), performs it with gestures or global actions, and checks that the screen changed. Also intent cursor mode (name an on-screen element). JVM unit tests in `app/src/test`. |
| [`fixture/`](fixture/README.md) | `ai.vox.fixture`, a small test app with known screens: a vertical video-like feed, a 100-row list, a toggle button with a text field, and a static screen. The emulator tests assert on it. |
| [`suite/`](suite/README.md) | Host-side Python that drives the emulator: boot and stop (`emu.sh`), install the apps and pinned F-Droid stand-ins (`setup_device.py`, `apks.py`), the emulator tests (`test_suite.py`), the screen harvest (`harvest.py`), fake servers, enrollment push (`enroll.py`), and the one entry point `run.sh`. |
| [`tools/`](tools/README.md) | Code generators that keep the app in sync with `finetune/` and `extractor/`: `gen_vocab.py` writes `Vocab.kt` and `TargetVocab.kt`; `state_parity.py` writes the unit-test fixture that proves the app's state text is byte-identical to the training data; `fp_floors.py` writes the provisional fingerprint std floors. |
| [`nix/`](nix/README.md) | The pinned toolchain as a nix flake: Android SDK (platforms 35 and 36, build-tools 35.0.0, emulator, `android-35;default;x86_64` image), JDK 17, Gradle, Python 3, Flutter 3.47.4 (with its Linux desktop toolchain). |
| `dev` | Enters the nix dev shell, or runs one command in it (`./dev gradle ...`). It uses a `path:` flake reference, so nix does not depend on git tracking of `nix/`. |
| `PROTOCOL.md` | The device → phone message format, the BLE GATT link, the control ops, the event log, the model HTTP calls, intent cursor mode and personalization. |
| `build.gradle.kts`, `settings.gradle.kts`, `gradle.properties` | The Gradle build: `:app` and `:fixture`, plus `:flutter` and its plugins from `../ui` (applied through `ui/.android/include_flutter.groovy`). AndroidX is enabled because the Flutter embedding needs it. The Kotlin compiler runs in-process. |
| `.state/` | All mutable state: Gradle home, AVD, emulator and adb user dirs, logs, the F-Droid index cache. Gitignored; delete it to reset. |

## Build, boot, test, harvest

```sh
cd android
suite/run.sh build        # flutter pub get in ../ui, then gradle assembleDebug + 441 JVM unit tests (first run fetches deps into .state)
suite/run.sh boot         # create AVD "vox35" if needed; boot headless (-no-window -no-audio, KVM); VOX_WIPE=1 = factory-fresh
suite/run.sh setup        # install VOX + fixture + 5 hash-pinned F-Droid APKs, seed 5 photos, enable the a11y service
suite/run.sh test         # 34 emulator tests; -k NAME to filter; results in suite/out/results-*.json
suite/run.sh harvest      # walk launcher/fixture/stand-ins → suite/out/harvest-*.jsonl + targets-harvest-*.jsonl
suite/run.sh jev start    # the real local /v1/systemone (finetune/servers/systemone.py, vox-jevlike, CPU) on :8765
suite/run.sh jev stop     # (and `jev status`); log in suite/out/systemone.log
suite/run.sh stop         # kill the emulator and the adb server
suite/run.sh all          # all of the above, and always stops the emulator at the end
```

Only one emulator runs at a time: `emu.sh start` refuses to start if one is already attached. The first
`nix develop` builds the SDK from nixpkgs, which takes about 90 s here.

Manual use inside the shell:

```sh
./dev                                   # shell with adb, emulator, gradle, python3 on PATH
adb forward tcp:7788 localabstract:vox-debug
printf '%s\n' '{"type":"control","op":"ping"}' | nc -q1 127.0.0.1 7788
adb logcat -v raw -s VOX:I              # the event log (full copy: adb exec-out run-as ai.vox.companion cat files/events.jsonl)
```

### Licences

Android SDK licences are accepted only through androidenv's own mechanism: nixpkgs
`config.android_sdk.accept_license = true` (plus `allowUnfree`) in `nix/flake.nix`. No `sdkmanager --licenses`,
nothing interactive and nothing system-wide. Running `./dev` means you accept them.

### Keeping the home directory clean

Everything writes under `android/.state`. Three tools needed help:
- **adb** ignores `ANDROID_USER_HOME` and writes `$HOME/.android`. `.state/bin/adb` is a wrapper that sets `HOME`.
- **AGP** writes `<user.home>/.android/analytics.settings`. Java reads `user.home` from passwd, and Gradle drops
  `-Duser.home` from `org.gradle.jvmargs`. `.state/bin/gradle` is a wrapper that sets `JAVA_TOOL_OPTIONS=-Duser.home=...`.
  That makes Java print "Picked up JAVA_TOOL_OPTIONS"; this is expected.
- **The emulator** writes `~/.emulator_console_auth_token`, so `emu.sh` runs it with `HOME` inside `.state`.
- **Flutter and Dart** keep config, analytics consent and caches in `$HOME`, the XDG dirs and `~/.pub-cache`.
  `.state/bin/flutter` and `.state/bin/dart` are wrappers that point `HOME`, `XDG_*` and `PUB_CACHE` into `.state`
  (pub cache: `.state/pub-cache`). The Gradle wrapper sets the same variables, because the Flutter Gradle plugin runs
  the Flutter tool during the app build. Analytics are turned off once per `.state`
  (`flutter --disable-analytics`, `flutter config --no-analytics`, `dart --disable-analytics`).

The only write outside `android/` is nix's own evaluation cache in `~/.cache/nix`.

## Configuration (app)

The settings screen (the launcher icon "VOX") and the debug `config` op share the same keys:

| key | default | |
|---|---|---|
| `decider` | `rules` | `rules` (deterministic), `model` (falls back to rules on error), `hybrid` (explicit bindings local, else the model), or `escalate` (hybrid plus a cloud model for target picking and the cases the local path can't settle; PROTOCOL.md "Decider `escalate`") |
| `base_url` | `https://api.typesafe.ai` | `POST {base_url}/v1/systemone` |
| `model` | `jev-1.13.0` | |
| `api_key` | empty | Entered in settings and never hard-coded. It is redacted in `ping` and never logged. Stored in app-private SharedPreferences (Keystore encryption is a TODO). |
| `min_confidence` | 0.5 | A model answer below this becomes `none`. |
| `ollama_endpoint` | `https://ollama.com` | Decider `escalate`: `POST {ollama_endpoint}/api/chat` (Ollama cloud, or a LAN Ollama). |
| `ollama_model` | `deepseek-v4.1-flash` | |
| cloud key | empty | Entered in the settings screen only (not accepted by `config`; `ping` shows `"set"` or `""`). Stored AES-GCM encrypted under an Android Keystore key; never logged. |
| `ollama_timeout_ms` / `ollama_target_timeout_ms` | 1500 / 2500 | Hard deadlines for a cloud gesture/phrase decision and a cloud target pick; past them the local path answers. |
| `auto_scroll_pct` | 10 | Hold-to-scroll speed (rise/fall, then hold a flat hum: it scrolls while the hum is held), in percent of the screen height per second (2-60). It also stops on an app change, screen off, or 5 s without a `hold end`. |
| `gap_ms` | 600 | Max device gap between sounds of one sequence; also the wait for a follow-up (only when a bound sequence continues). |
| `jitter_ms` | 150 | With device timestamps: extra wait allowing for a follow-up that arrives late. |
| `confirm_timeout_ms` | 1500 | The confirmer's window. |
| `listen_window_ms` | 6000 | How long a phrase is accepted after `listen_for_phrase`. |
| `target_min_confidence` | 0.6 | Intent cursor mode: a `target` answer at or above this is tapped; below it, the top 3 are highlighted. |
| `target_model` | empty | Model for the `target` question; empty = same as `model`. |
| `target_choose_ms` | 6000 | How long the highlighted candidates wait for rise/fall/pop/hiss before cancelling. |
| `enroll_reject_mult` | 1.4 | Personalization: a sound matches an enrolled class only within the class's within-class distance × this. |
| `ble_device` | none | The remembered VOX device (Bluetooth address). Set on the first good connection; the service connects to it at start. `null` forgets it. |
| `sound_source` | `pico` | Where sounds come from: `pico` (the VOX device over Bluetooth), `phone` (the phone's mic) or `usb` (a USB mic plugged into the phone). The mic sources run the Pico's extractor on the phone (PROTOCOL.md "Phone microphone"). Also the **Sound source** block of the settings screen and the notification's **Source** button. |
| `mic_rate` | 16000 | Capture rate for the mic sources: 16000, or 48000 (decimated by 3 in the extractor). |
| `mic_preset` | `auto` | `auto` (UNPROCESSED when supported, else VOICE_RECOGNITION), `unprocessed`, `voice_recognition`, `voice_communication` (the call path, with the platform's echo canceller: for the echo A/B), `mic`. |
| `mic_effects` | `off` | Platform pre-processing on the capture: `off` (AGC/NS/AEC off where attached), `platform` (as the preset attaches them), `aec` (echo canceller only), `aec_ns` (+ noise suppressor). |
| `mic_touch_guard` | true | Drop a phone-mic sound when a touch-down on the screen lies within 400 ms before its start to 150 ms after its end: a finger on the glass reads as a pop (`TouchGuard.kt`, fed by `TouchWatch.kt`, a 1×1 accessibility overlay watching outside touches). Canti's own injected gestures do not count. |
| `mic_media_gate` | `speaker` | While media plays, a pop/click must be ≥ 14 dB over the noise floor and a hum ≥ 14 dB with clarity ≥ 0.8, else it reaches the service as `unknown` (not deliberate; `PhoneGate.kt`). `speaker`: only while media plays on the phone's own speaker (earbuds/Bluetooth: no echo, no gate); `media`: any media; `always`; `off`. |
| `hiss_media_max_centroid_hz` | 6500 | While media plays on the phone's own speaker, a phone/USB mic hiss with a spectral centroid over this many Hz reaches the service as `unknown` (`PhoneGate.hissReason`; logged in `mic_sound.gated`). 0 = off, 0-8000. Independent of `mic_media_gate`; never for the Pico. From the Z Flip's 7 kHz media hisses (wiki/phone-mic-echo.md). |
| `mic_dry_run` | false | Measurement: phone-mic sounds are logged (`mic_sound`) but never handed to the service. |
| `mic_read_ms` | 20 | AudioRecord read size in ms (10-40). |
| `mic_while_disarmed` | false | Keep the mic open while disarmed (normally a disarm or pause closes it). |

Profiles are JSON with scopes `global`, `app:<package>`, `cursor` and `phrases`, plus an optional `name` that selects
the enrollment store; see `Profile.kt`. The bundled
default (`assets/profile_default.json`) binds rise→zoom_in and fall→zoom_out in Organic Maps.

## Intent cursor mode

In cursor mode, `pop pop` opens the listening window and the next phrase names an element ("the subscriptions
tab"). The app builds an option list from the accessibility tree (`Targets.kt`, spec: `finetune/vox/targets.py`),
asks the `target` question on `/v1/systemone`, and then:
- taps the element if confidence >= `target_min_confidence`;
- otherwise shows numbered highlights on the 3 most probable elements: rise/fall cycles, pop taps, hiss or
  `target_choose_ms` cancels;
- shows the toast "not on screen" if the model picks `none of these ...`.

Wire format, option rules and events: [PROTOCOL.md](PROTOCOL.md#intent-cursor-mode-the-target-question). The debug
`targets` op returns the options for the current screen.

Deviations from, and additions to, the targets.py spec:
- **Label fallback**: before the viewId tail, the first text of a non-clickable, non-focusable descendant is used.
  Many rows and bottom-nav items carry their title on a child view; without this they came out as viewId words
  or `unlabeled`.
- **Container exclusions**: scrollable non-clickable containers, focusable-only nodes covering more than half the
  screen, and label-less focusable-only containers holding other targets are not options. Without the last rule,
  NewPipe's tab strip produced a spurious "Live (item, top)".
- **Reading order** = 3x3 cell (row, then column), then top edge, then left edge. The cap is 40 options
  **including** `none`.
- **`pop pop` in cursor mode** is handled by the app (source `app:cursor-listen`), because `schema.CURSOR_ACTIONS`
  has no listen option. So a cursor-mode `pop` (click) waits `gap_ms + jitter_ms` for a possible second `pop`.
  Since 2026-09-27 `pop pop` (not `click pop`) is also the gesture-mode listen gesture, owned by the app (`app:listen`)
  in every decider mode, because the models were trained on `click pop` (`Vocab.DEFAULTS_TEXT` still says so).

## Personalization

When a sound carries a fingerprint (`features` in the message), the app matches it against the active profile's
enrolled examples before anything else (`Personal.kt`, design: `wiki/personalization.md`):
- a **custom** match (a sound the user invented, e.g. "meow") becomes the line `my sound "meow"; duration <bucket>;
  loudness <bucket>` with label `my:meow`. It does nothing unless a fixed rule binds it:
  `{"sound": "my:meow", "kind": "fixed", "action": "open_camera"}`.
- an **ignore** match (a sneeze, a laugh) keeps its line but says `sounds like one of my ignore sounds`, and is always
  `none`.
- a **gesture** match (the user's own rise, pop, ...) is only logged for now.

Custom and ignore sounds are decided locally, never by the model, because the model has no training data for these lines
before data v6. The exception is a plain-language rule (`kind: "rule"`) bound to the custom sound. Enrollment is recorded
on the PC and pushed over the debug socket:

```sh
./dev python3 suite/enroll.py push examples.jsonl   # one {"kind","name","fp","fp_version","pitch16"} per line
./dev python3 suite/enroll.py list                  # classes, example counts, thresholds
```

Matching rules, thresholds and events: [PROTOCOL.md](PROTOCOL.md#personalization-enrolled-sounds-rewrite-the-line).
In short: features are standardised with a per-feature std floor (`assets/fp_floors.json`, keyed by `fp_version`;
`fp1`'s floors are provisional until the extractor publishes real scales), and a class's reject threshold is its
leave-one-out within-class distance × `enroll_reject_mult`, for every class size.

## Flutter UI (`../ui`)

`MainActivity` (launched through the icon aliases below) is a `FlutterActivity` that shows the status screen from
[`../ui`](../ui/README.md).
The screen shows:
- whether the service runs, the device's arm state, mode, foreground app, Bluetooth link and decider;
- **Pause VOX** / **Resume VOX**, a phone-side switch independent of the device's `armed`;
- **Legacy settings**, which opens the old native screen (`LegacySettingsActivity`);
- the live event log.

It talks to the service over two platform channels (PROTOCOL.md "UI channel").

The Flutter module is built into the app **from source**. `settings.gradle.kts` applies
`../ui/.android/include_flutter.groovy`, which `flutter pub get` in `../ui` generates (`suite/run.sh build` runs
it first). The alternative, a prebuilt AAR, needs a separate `flutter build aar` step and a local Maven repository.
With source integration, one Gradle build compiles both halves. The Flutter engine artifacts come from
`storage.googleapis.com/download.flutter.io`, which `settings.gradle.kts` adds as a repository. The NDK
(28.2.13676358) and the Gradle arguments nixpkgs' Flutter needs are in `nix/` (nix/README.md).

**APK size**, `ai.vox.companion`, three ABIs (arm64-v8a, armeabi-v7a, x86_64), bytes:

| build | before Flutter | with Flutter |
|---|---|---|
| debug (JIT, kernel blob, Vulkan validation layer) | 3,089,532 | 170,046,656 |
| release, unsigned (AOT, not minified) | 2,461,400 | 52,174,986 |

In the release APK:
- `libflutter.so` is 13.1 MB (x86_64), 11.8 MB (arm64) and 8.6 MB (armv7);
- `libapp.so` (the compiled Dart) is about 3.7–4.0 MB per ABI;
- `classes.dex` is 6.3 MB;
- MaterialIcons was 1.6 MB. Since the Canti restyle `gradle.properties` sets `tree-shake-icons=true`, which cuts it to
  2 KB; the restyle's before/after sizes are in `../ui/README.md` "Performance".

An arm64-only release would be about 22.7 MB. A Play App Bundle's per-ABI split would give about the same per
device.

**Launcher icon.** The Canti stipple icon (`../brand`), as adaptive icons with a themed (monochrome) layer:
`res/mipmap-anydpi-v26/ic_launcher_on|off.xml`, their pixel-exact PNG layers per density and
`res/drawable/ic_launcher_mono_on|off.xml`, all generated by `../brand/tools/stipple.py launcher`. The icon shows
the link: "on" (lit eyes and lamp) while a device is paired and connected (BLE state `ready`), "off" otherwise. The
LAUNCHER intent filter is on two `<activity-alias>`es of `MainActivity`, `.LauncherOn` (enabled in the manifest, the
default) and `.LauncherOff`; `LauncherIcon.kt` enables one and disables the other with `DONT_KILL_APP`. It switches
only when the state has been stable for 10 s, and at most once a minute (`IconSwitch`, tested by
`LauncherIconTest`), because every switch is a component change for the launcher:
- most launchers redraw the icon in place within a few seconds, but some drop a home-screen shortcut or move the app
  back to the drawer, and some close its recents entry;
- the icon only follows the link while the accessibility service runs; otherwise it keeps its last state;
- `am start -n ai.vox.companion/.MainActivity` still works (MainActivity stays exported), and
  `monkey -c android.intent.category.LAUNCHER` resolves to whichever alias is enabled.

**Start time** on the emulator (vox35, API 35 x86_64, KVM): `am start -W` TotalTime in ms, median (min–max) of 5
after one warm-up. Two cases:
- **cold**: the process was killed with `am force-stop`;
- **warm**: the process is alive (as it is whenever the accessibility service runs), and the activity is
  recreated with NEW_TASK|CLEAR_TASK.

The release APKs were zipaligned and signed with the `.state` debug key. `FlutterActivity` holds Android's first draw
until Flutter's first frame, so TotalTime includes it.

| build | cold | warm |
|---|---|---|
| pre-Flutter debug | 1037 (664–1123) | 79 (77–109) |
| pre-Flutter release | 482 (467–805) | 79 (59–109) |
| Flutter debug | 2966 (2596–3191) | 1926 (1781–2108) |
| Flutter release | 1504 (1365–1509) | 858 (806–968) |

In the Flutter release, the first frame came 1025–1141 ms after process start (`ui{first_frame}`). In short,
Flutter adds about 1.0 s to a cold start and about 0.8 s to each opening. These are emulator numbers; a phone will
differ.

## BLE link (Pico → phone)

`BleFeatureSource.kt` implements the app side of PROTOCOL.md "BLE GATT link (v1)": scan by the VOX service UUID,
connect, request MTU 517 (it works at whatever the phone grants, down to 23), read INFO (logged), bond (LE Secure
Connections, Just Works; skipped if INFO says `insecure`), enable EVENT notifications, reassemble the fragments
(`BleLink.kt`) and hand each message to the same pipeline as the debug sources. A dropped link disarms the app, and
the source reconnects with backoff (1 s doubling to 30 s; after 5 failures Android's background auto-connect takes over).
The device may not send control messages (they are rejected). There is no Bluetooth setup screen yet. The
**Allow Bluetooth (VOX device)** button (VOX > **Legacy settings**) asks for the permissions, and the `ble_*` debug
ops (PROTOCOL.md) do the rest. The status screen shows the link state.

Reassembly follows the fragment header exactly: a message starts at a fragment with the *first* bit and ends at one
with the *last* bit; the counter starts at 0 on each connection. After a counter gap the partial message is dropped
(`ble_gap`) and fragments are skipped until the next *first* bit. Messages over the protocol's 4096 bytes are dropped
(`ble_bad`). On (re)connect the device sends a no-sound state message, which sets `armed` and `mode` like any other.

Facts about the finished Pico firmware, and how the app handles them:
- **Message ids restart at 1 on every Pico boot.** The first message of each link, normally that state message, is
  delivered as `msg{source: "ble-connect"}`. It clears the app's last-seen id, so sounds after a device reboot are
  not dropped as duplicates.
- **Connection interval.** Right after connecting, the source calls `requestConnectionPriority(HIGH)` (logged
  `ble{what: priority}`). The device asks for 7.5–30 ms; Android's default adds latency.
- **Every flash erases the device's bonds**, so a phone still bonded to VOX-XXXX fails encryption on reconnect.
  After two pairing/encryption failures in a row, the source stops retrying and enters `needs_pairing` (logged
  `ble{what: auth_failed}`). The status screen then shows "Forget VOX-XXXX in the phone's Bluetooth settings, then
  reconnect." Removing the bond restarts the connection by itself, and `ble_connect` does too. The failure statuses
  (5, 6, 15, 61, 137) come from the Android/HCI definitions and have not yet been seen from a real re-flashed Pico.

Controlling the device from the app (`DeviceLink.kt`; PROTOCOL.md *App commands (CONFIG)*, *Sleep and wake*,
*Pairing*, *Disconnect*):
- **Commands.** Arm, pause, mode and sleep are CONFIG writes (`{"v":1,"armed":…}`, `{"v":1,"mode":…}`,
  `{"v":1,"sleep":true}`), sent only on a ready link and one at a time. The write succeeding is not the confirmation:
  the device's next no-sound state message is (for sleep, its `sleeping: true` message). A reply carrying `rejected`
  fails at once with the device's reason; no reply within 1.5 s (a write the stack blocked) is a failure too.
  Failures are logged `device_cmd{result: failed}` and shown on the status screen. The debug op is `device`
  (`ctl.py device armed=false`), the UI call `deviceCommand`.
- **The device owns `armed`.** With a ready device, the status screen's Pause/Resume pauses or arms the device;
  without one, it is the app-side pause as before. The mode toggle and **Sleep device** appear while the device is
  connected. The device row reads `listening`, `awake – paused`, `asleep` or `pairing needed`.
- **Sleep.** `sleeping: true` (sent before the device sleeps, whether asked by the app or by 5 presses) means asleep,
  not an error: the drop that follows is expected, the app reconnects quietly every 2 s with background auto-connect,
  and never escalates to `needs_pairing`. Waking with 5 presses reconnects, and the state-on-connect message says
  `armed: true`; the app follows it.
- **Unexpected disconnect.** The device comes back disarmed (`armed: false` on connect) and the app never arms it by
  itself. The user resumes it.
- **Pairing** works only in the device's 60 s pairing window. The hint says "Hold the VOX button 5 s until the light
  blinks fast, then connect." When the failure looks like a stale bond (the phone is still bonded), it also says to
  forget the device; when the app cannot tell, it shows both. The **Connect** button on the status screen retries.

### BLE end-to-end test (needs the physical phone and a Pico with the BLE firmware)

The emulator has no Bluetooth, so this is manual. It installs only `ai.vox.companion` (and the fixture app for
step 8), changes nothing else on the phone, and removes what it installed at the end.

1. Build: `suite/run.sh build`. Flash the Pico with the BLE firmware (see `../firmware/README.md`) and keep it
   powered off for now.
2. Plug in the phone (USB debugging on) and check `./dev adb devices` lists it. Then:
   ```sh
   export VOX_SERIAL=<serial from adb devices>
   ./dev adb -s $VOX_SERIAL install -r app/build/outputs/apk/debug/app-debug.apk
   ./dev adb -s $VOX_SERIAL install -r fixture/build/outputs/apk/debug/fixture-debug.apk
   ```
3. Turn on the service: Settings > Accessibility > VOX > on. Or, from the PC, *append* it to the enabled list without
   removing the others:
   ```sh
   cur=$(./dev adb -s $VOX_SERIAL shell settings get secure enabled_accessibility_services | tr -d '\r')
   new=ai.vox.companion/.VoxService; [ -n "$cur" ] && [ "$cur" != null ] && new="$cur:$new"
   ./dev adb -s $VOX_SERIAL shell settings put secure enabled_accessibility_services "$new"
   ./dev adb -s $VOX_SERIAL shell settings put secure accessibility_enabled 1
   ```
4. Open the VOX app, tap **Legacy settings**, press **Allow Bluetooth (VOX device)** and allow. The status line should say
   "Bluetooth: allowed". Go back to the VOX status screen.
5. In a second terminal, watch the log:
   `./dev adb -s $VOX_SERIAL logcat -v raw -s VOX:I | grep -E '"ev":"(ble|ble_gap|ble_bad|msg|arm|pause|decision|device_cmd|config_write)"'`
6. Power the Pico. Run `./dev python3 suite/ctl.py ble_scan`, wait 10 s, then `./dev python3 suite/ctl.py ble_status`.
   **Pass:** `found` lists a `VOX-XXXX` device.
7. Hold the VOX button 5 s until the light blinks fast (the 60 s pairing window), then
   `./dev python3 suite/ctl.py ble_connect`. If Android shows "Pair with VOX-XXXX?", accept. Then `ble_status` again.
   **Pass:**
   - `state` is `ready`, `bonded` is `bonded` (or INFO says `insecure`), `mtu` > 23 (517 on most phones);
   - `info` has the firmware's `fw`, `mic` and `fp_version`, and a `ble{what: info}` event was logged;
   - `ble{what: priority, high: true}` was logged;
   - the first message is `msg{source: "ble-connect"}` (the device's state message);
   - `remembered` is the Pico's address, and the VOX status screen shows `Bluetooth ready, <address>`.
8. Make sounds (or, if the firmware implements test sounds:
   `./dev python3 suite/ctl.py ble_config 'config={"v":1,"test_sounds":true}'`). With the fixture's video feed in
   front (`./dev adb -s $VOX_SERIAL shell am start -n ai.vox.fixture/.FeedActivity`), a rise should swipe to the next
   video. **Pass:**
   - `msg{source: "ble"}` events arrive with the device's `timing`;
   - `ble_status` shows `messages` rising and `gaps` and `bad` at 0;
   - `fragments` is greater than `messages` once fingerprints are sent, so fragmentation works;
   - the actions happen.
9. Arm/pause from the Pico's button. **Pass:** `msg{armed: false}`, then `arm{state: disarmed, by: device}`; arming
   again re-arms.
10. Commands from the app. Run each and watch for `device_cmd{result: sent}`, then `config_write{status: 0}`, then
    `device_cmd{result: confirmed, applied: true}` within 1.5 s (`ms` shows how long it took):
    - `./dev python3 suite/ctl.py device armed=false`. **Pass:** the device's light shows paused, a `msg{armed: false}`
      arrives, and sounds are ignored. The status screen headline is "Device paused" and the device row
      `awake – paused`.
    - Tap **Resume VOX** on the status screen. **Pass:** the same three events with `cmd: arm`, the device row
      `listening`, and the next sound acts.
    - Tap **Pause VOX**. **Pass:** `cmd: pause` confirmed; nothing on the phone reacts to sounds.
      Tap **Resume VOX** again.
    - Tap **Cursor**, then **Gesture** in the mode toggle. **Pass:** `cmd: "mode cursor"` / `"mode gesture"`
      confirmed, and `msg{mode: …}` matches.
    - Timeout: power the Pico off and at once (before the drop is noticed) run
      `./dev python3 suite/ctl.py device armed=false`. **Pass:** `device_cmd{result: failed}` with
      "no confirmation from the device within 1500 ms" or "the link dropped", and the status screen shows it in red.
      Power it on and let it reconnect.
11. Sleep and wake:
    - Tap **Sleep device**. **Pass:** `msg{sleeping: true}`, `arm{by: "device (going to sleep)"}`, `ble{what: asleep}`,
      `device_cmd{cmd: sleep, result: confirmed}`; the link drops with no `auth_failed` and no error on the screen;
      the device row says `asleep` and `ble_status` shows `device.asleep: true` and `waiting` "device asleep".
    - Press the VOX button 5 times quickly. **Pass:** `ble{what: awake}`, the link is `ready` without a pairing
      prompt, the state-on-connect message has `armed: true`, and the device row says `listening`.
    - Press the button 5 times again while armed. **Pass:** the same as tapping **Sleep device**, without a
      `device_cmd` event.
12. Power the Pico off (or walk out of range). **Pass:**
    - `ble{what: disarm}` and `arm{state: disarmed, by: "ble disconnect"}` appear;
    - `state` goes to `waiting` with a growing `reconnect_in_ms`.

    Power it on again (or come back). **Pass:** `ready` again without a pairing prompt; the state-on-connect message
    says `armed: false`, the device row says `awake – paused`, and no `device_cmd` is sent (the app does not arm it).
    Tap **Resume VOX**; the next sound acts. After a power cycle the device's ids restarted at 1, and it is still not
    dropped as a duplicate.
13. Toggle the phone's Bluetooth off and on. **Pass:** `state` goes to `off`, then back to `ready`. Turn the VOX
    service off and on. **Pass:** it reconnects to the remembered device by itself.
14. Re-flash the Pico (this erases its bonds) and power it. **Pass:**
    - after at most two failed attempts, `ble{what: auth_failed}` is logged (with `problem: stale_bond` or `unknown`)
      and `ble_status` shows `needs_pairing` with the hint;
    - the status screen shows "Pairing needed", the forget hint ("Forget VOX-XXXX in the phone's Bluetooth settings
      …" or "If VOX-XXXX was re-flashed, forget it …") followed by "Hold the VOX button 5 s until the light blinks
      fast, then connect.", and a **Connect** button; the source stops retrying.

    Forget VOX-XXXX under Settings > Bluetooth, hold the VOX button 5 s until the light blinks fast, and tap
    **Connect** (removing the bond also restarts the source by itself). **Pass:** the pairing prompt appears (accept
    it), and the link reaches `ready`.
15. Pairing window closed: forget VOX-XXXX on the phone *without* holding the button, and tap **Connect**. **Pass:**
    pairing fails, and after at most two attempts the hint is "Hold the VOX button 5 s until the light blinks fast,
    then connect." (`problem: window_closed`; `unknown` shows both lines). Hold the button 5 s and tap **Connect**:
    it pairs.
16. Clean up:
    - `./dev python3 suite/ctl.py ble_forget`;
    - remove the VOX-XXXX bond under Settings > Bluetooth;
    - turn the VOX service off;
    - run `./dev adb -s $VOX_SERIAL uninstall ai.vox.companion`, `./dev adb -s $VOX_SERIAL uninstall ai.vox.fixture` and `./dev adb -s $VOX_SERIAL forward --remove tcp:7788`.

Not covered by this test: forcing MTU 23 (the phone chooses; the JVM tests cover 23 to 517), and a counter gap on
real radio (the JVM tests cover gaps; `ble_gap` events would show one).

## What was verified by running it (2026-09-26, this machine)

- **Device control from the app (latest round).**
  - JVM tests: **76/76 passed, 0 skipped** (BleTest 21, CoreTest 25, DeviceLinkTest 10, PersonalTest 13, TargetTest 7).
    The new `DeviceLinkTest` drives `DeviceLink` with a fake link and a manual clock:
    - each command's CONFIG JSON and its confirmation by the next no-sound state message, and that only such a
      message confirms;
    - a reply carrying `rejected` fails the command at once with the device's reason (no wait for the timeout);
    - no confirmation in 1.5 s is a `device_cmd` failure kept for the status screen, and a failed write fails at once;
    - no ready link, or a command still waiting, is refused;
    - `sleeping: true` means asleep: the drop is expected, auth failures do not escalate, and nothing is written;
    - waking reconnects with `armed: true` and the app follows; an unexpected disconnect comes back `armed: false`
      and the app writes nothing.
  - Flutter: `flutter analyze` is clean in `ui/` and `ui/desktop`. `flutter test` passes **15/15** in `ui/` and **1/1**
    in `ui/desktop`.
  - Emulator suite: **33/34 passed, 1 skipped** (Jev, server not started), in
    `suite/out/results-20260926-135238.json`. `ble_ops_without_a_device` now also checks the `device` op's refusals
    and validation, and `ble_status.device`.
  - **Not verified:** anything on a Pico or a phone. The emulator has no Bluetooth and no phone was attached, so the
    manual steps 7–15 above have not been run.

- **Flutter status screen and firmware facts.**
  - JVM tests: **66/66 passed, 0 skipped** (BleTest 21, CoreTest 25, PersonalTest 13, TargetTest 7).
    - `capturedPicoMessagesParse` now runs: all 240 lines of `firmware/tests/captured_messages.jsonl` parse.
    - New, `capturedPicoMessagesThroughTheReassembler`: the same 240 lines (4 of them exactly 4096 bytes) are
      fragmented with one running counter at MTU 23, 185 and 517. They come out byte for byte, and they parse.
    - New, `authFailuresStopRetryingAndNameTheDevice`.
  - Flutter: `flutter analyze` is clean. `flutter test` passes **10/10** in `ui/` and **1/1** in `ui/desktop`.
  - Emulator suite: **33/34 passed, 1 skipped** (Jev, server not started), in
    `suite/out/results-20260926-130943.json`. The TreeReader/`currentApp` change broke nothing. The new
    `ui_flutter_status_screen_is_readable_and_pausable`:
    - reads VOX's own Flutter screen through the `targets` op, which lists `Pause VOX (button, left)`,
      `Refresh status (button, top right)` and `Legacy settings (button, center)`, and the status rows as items;
    - taps them with `adb input` at the listed bounds: pause logs `pause{by: app}`, a sound is then
      `ignored{reason: "paused (app)"}`, and nothing runs. Resume works, **Legacy settings** opens
      `LegacySettingsActivity`, and back returns.
  - **Not verified:**
    - on a Pico: the connection priority, the `ble-connect` reset point and the `needs_pairing` handling. There
      was no phone attached, and the emulator has no Bluetooth;
    - the reset point is not covered by any automated test.

- **BLE contract amendment (first-fragment bit, counter mod 64 from 0, 4096-byte limit).** JVM tests: **63 passed,
  1 skipped** out of 64 (BleTest now 19; the same skip). The reassembly tests were rewritten for the new header:
  first/last bits at MTU 23–517, counter from 0 per connection and wraparound 63→0, a gap mid-message, on a first
  fragment, on a last fragment and swallowing a whole message, a continuation chunk starting with `{` after a gap (the
  old guess would have taken it as a new message; now skipped), a continuation with no first fragment, a first
  fragment before the previous last, exactly 4096 bytes accepted and 4097 dropped, and 20000 random notifications.
- **Matching fixes and the BLE receiver.**
  - JVM tests: **60 passed, 1 skipped** out of 61 (CoreTest 25, TargetTest 7, PersonalTest 13, BleTest 16). The
    skipped one is `capturedPicoMessagesParse`: `firmware/tests/captured_messages.jsonl` does not exist yet.
  - What the new tests cover:
    - leave-one-out at 2, 3, 4 and 10 examples;
    - the floor: the midpoint case, which passes without a floor and is **rejected** with it, while the classes'
      own sounds still match;
    - the floor table: missing version, length mismatch, provisional/final, JSON validation and override, and the
      shipped `fp1` table;
    - BLE: single and multi fragment at MTU 23–517, a UTF-8 character split across fragments, counter wraparound
      127→0, reset per connection, a gap mid-message, a gap that swallows a whole message, a gap on the last fragment;
    - that no message tail decodes;
    - garbage: empty, header-only, bad UTF-8, not JSON, a JSON array, trailing data, a control message, oversize,
      and 2000 random notifications;
    - message parsing (a sound with timing and fingerprint; arm, pause and mode messages; invalid ones), INFO,
      backoff and the UUIDs;
    - every canned line in `firmware/tests/test_sounds.json`, fragmented at MTU 23.
  - Emulator suite: **32/33 passed, 1 skipped** (Jev, server not started), in `suite/out/results-20260926-121501.json`.
    The personalization test now also checks that the floors are provisional, and the `fp_floors` override and reset.
    The new `ble_ops_without_a_device` test checks that the BLE source runs on the emulator (adapter on, state idle)
    and that its ops answer and validate. With LOO and the floor, the synthetic thresholds are meow 0.625 (5
    examples) and sneeze 0.474 (3). The near-meow is at 0.209 and the far sound at 51.6.

Earlier rounds:

- **Nix shell**: builds. The emulator boots headless under KVM in 22–25 s on an idle box and 49 s under host load
  70 (Pixel 6 profile, 1080x2400, API 35).
- **Build and JVM unit tests**: `gradle assembleDebug :app:testDebugUnitTest` gives **43/43 passed** (CoreTest 25,
  TargetTest 7, PersonalTest 11). These include:
  - personalization: standardisation, banded DTW (band ±3, including a shift the band cannot absorb), the reject
    thresholds (pairwise max vs leave-one-out at 3 examples), nearest neighbour with reject, contour classes needing
    both the fp and the DTW match, the store's version/length/size rules and JSON round trip, `features` message
    validation, the exact rewritten lines, and that custom/ignore sounds never reach the model (a counting fake);
  - `Scene.text()` byte-identical to finetune `generate.py` on 300 random scenes;
  - the local rule decider reproducing **380/380** generator labels (defaults, unbound sequences, not-deliberate
    sounds, phrases, the screen tie-break, cursor, including the new "click click unbound in cursor mode");
  - option order equal to `schema.ACTIONS` / `schema.CURSOR_ACTIONS` dict order (25 and 24 options);
  - the timing rule on a fake clock. Device-stamp grouping covers a late follow-up that still merges, a burst after
    a stall that still splits, the lateness-compensated wait, a split inside one message, and a device clock reset.
    Each has an arrival-fallback contrast;
  - intent cursor options: 3x3 bucket edges, label fallback order, role mapping, reading order with dedupe, the cap
    and `none` last, the option and state text format against 120 targets-v1 test rows, the answer policy
    (tap / choose top 3 / not on screen / unknown choice), and the `target` question over HTTP;
  - the message parser (including `timing` validation), the profile rule sentences, the screen summariser,
    confirmer echo classification, the pixel-grid diff with masks, and the HTTP decider against a local drop-in
    server.
- **Emulator suite** `suite/run.sh test`: **31/31 passed**, twice in a row with the real local server up
  (`suite/out/results-20260926-103146.json`, 207 s; `results-20260926-103524.json`, 212 s). Earlier round:
  27/27 twice (`results-20260926-091545.json`, `results-20260926-091916.json`). Each test sends real messages through
  the debug socket, runs the rule decider, and asserts on the app's own tree dump, screenshots and the event log.
  The previous version also passed 25/25 via `suite/run.sh all` on a factory-fresh AVD.

  **Note (2026-09-27): the results below predate pop pop = listen and have not been re-run.** The suite now sends
  `pop pop` for the listen and intent-cursor checks, a lone `pop` is expected to tap after one gap (waiting for `pop
  pop`), and `click pop` is unbound (it still merges on the arrival clock, now to `none`). With `decider=model` the
  app answers `pop pop` itself (`app:listen`), so the real-Jev run no longer asks the model about the listen gesture.

  Fixture: every default gesture.
  - `rise`/`fall`: next/previous video ("Video 1 of 20" → 2 → 1).
  - `dip`/`arch`: horizontal page ±1.
  - `pop`: tap, playing→paused, decided after 0–1 ms (no wait).
  - `flat`: long press (counter 1).
  - `hiss`: back to the menu.
  - `click pop`: opens the listening window; the phrase "next" is then resolved to swipe_up by the screen line
    ("video feed").
  - A phrase outside the listening window is ignored.
  - List scroll; toggle button tap.

  Timing rule.
  - A lone `click` waits one gap (held 601–602 ms) and resolves to `none`.
  - A profile binding `pop pop`→like makes `pop pop` like (likes 1), and a single `pop` in that app then waits
    (held 602 ms), while `pop` on the launcher still acts at once.
  - `click` + `rise` forms the unbound sequence `click rise` → none.

  Device timestamps.
  - A `pop` delivered 650 ms after the `click` (arrival would split), but stamped 300 ms after it, resolves as
    `click pop` (clock device, gaps [300], waited 750 ms). Without stamps the same timing splits.
  - A `click` and `pop` delivered 50 ms apart after a stall (arrival would merge into `click pop`), but stamped
    660 ms apart, resolve as `click` (ended by device-gap) and then `pop`, which taps the feed. Without stamps they
    merge.

  Confirmer.
  - `pop` on the static screen: **"no visible change"**, even after the pixel fallback (status bar and VOX overlays
    masked).
  - `rise` on the static screen is still performed (the screen never vetoes an explicit gesture) and reported as
    "no visible change".
  - The fixture and four stand-ins give "confirmed (events)".
  - Organic Maps gives **"confirmed (pixels)"** (20% of grid cells changed). The pinch's own click echo is now
    ignored, where before it "confirmed" the pinch.

  Other fixture tests.
  - A rise that sounds like talking gives none.
  - Disarm drops a pending click.
  - Cursor mode on the device flag: pop clicks at the cursor, which toggles the button; loud rise → move_up_fast;
    flat → stop, with the state showing "cursor: moving up fast".
  - Cursor mode: `click click` is none by default. With a cursor rule it is `drag_toggle`, and the first click then
    waits for the second.
  - The model decider against a local fake `/v1/systemone` (via `adb reverse`): the request `state` equals the logged
    Scene text exactly. The criteria are 25 options, in schema order on the wire, with no cursor-mode option. The
    Bearer key is sent and is absent from the event log. On HTTP 500 it falls back to `rules:default`.

  Real local Jev stand-in (`jev_local_systemone_vox_jevlike`; `suite/run.sh jev start`, `adb reverse tcp:8765`,
  model `vox-jevlike`, `decider=model`). There are 11 requests over the real HTTP path, and the test asserts the
  parsed choice, the confidence and the executed action:
  - rise, fall, dip, arch, pop and flat each run their default action;
  - talking → none; `click rise` → none; hiss → back; `click pop` → listen; then the phrase "next" → swipe_up.
  - Result: **11/11 correct**, but every confidence is 1.000 (the model's confidence saturates).
  - Latency, median/max: 2.2 s standalone, 3.0 s and 3.6 s within the two full runs, max 7.3 s (8 CPU threads,
    sharing the box with the emulator).
  - If `/health` is unreachable, the test reports SKIP rather than a failure (checked: `results-20260926-103744.json`).

  Intent cursor mode. Each test uses a fake `target` model and the real options built from NewPipe's screen
  (15 options):
  - Confident: "What's New (tab, top)" is tapped and the tab becomes selected, confirmed (events).
  - Low confidence, 3-way split: numbered highlights appear (screenshot diff 1.4%, checked visually); rise, rise, pop
    taps the 3rd, "Bookmarked Playlists", confirmed (events).
  - On the fixture: `none` gives the toast "not on screen"; hiss cancels; a 1.5 s `target_choose_ms` timeout cancels;
    `decider=rules` reports "no model".

  Stand-ins (one gesture each, asserted by screenshot diff, an app-specific before→after check, and the confirmer):

  | app | message | result |
  |---|---|---|
  | NewPipe 0.29.1 | dip → swipe_left | tab Live → What's New, confirmed (events) |
  | VLC 3.7.1 | dip → swipe_left | tab Videos → Playlists, confirmed (events) |
  | Organic Maps 2026.08.27 | rise → zoom_in (per-app rule) | pinch-out, map zoomed, confirmed (pixels) |
  | Fossify Gallery 1.13.1 | dip → swipe_left | vox_test_0.png → vox_test_1.png, confirmed (events) |
  | Fennec 156.0.0 | rise → swipe_up | long page scrolled from Section 1–2 to Section 3, confirmed (events) |

- **Personalization on the emulator** (`personal_custom_meow_bound_ignore_sneeze_and_far_sound`, synthetic 24-value
  `fp1` vectors): a custom "meow" (5 examples) and an ignore "sneeze" (3 examples) enrolled over the socket; a
  mismatched `fp_version` and a wrong length are rejected; the store is on disk. Each probe sound is sent with the
  extractor's label `rise`:
  - near-meow: matched (distance 0.57, threshold 3.58), the line became `my sound "meow"; duration short (150-400 ms);
    loudness normal`, and the fixed rule ran `open_camera` (Camera2 opened, then crashed: the AVD has no camera);
  - a far vector: `none` (distance 134 > 1.77), the normal line was kept, and the feed swiped up;
  - near-sneeze: `sounds like one of my ignore sounds`, decision `none`, the feed did not move;
  - an `fp2` fingerprint: `skipped`, the normal rise ran;
  - with the model decider: 0 requests for an unbound custom sound and for an ignore sound, and 1 request for the far
    sound;
  - a second profile (`name: alice`) has its own empty store.
- **Full emulator suite** after the personalization change: **31/32 passed, 1 skipped** (the Jev test, whose local server
  was not started) in `suite/out/results-20260926-113417.json`.
- **Harvest**: 40 JSONL records (`tag, package, screen_text, summary, step`) over the launcher, the fixture and all
  five stand-ins (`suite/out/harvest-20260926-103727.jsonl`). Target lists go to
  `suite/out/targets-harvest-20260926-103727.jsonl` (`{tag, package, screen_text, options}`): 40 lists, 301 targets,
  at most 21 options per screen. Roles: item 72, list item 70, tab 56, button 50, image 38, text field 12, switch 3.
  Two are `unlabeled`.

## What is stubbed or missing

- **Flutter UI**:
  - only the status screen exists; everything else is still in **Legacy settings**;
  - the App row shows the app that was in front before VOX. The screen does not refresh when its own window takes
    focus;
  - every opening builds a new Flutter engine (about 0.9 s warm in release on the emulator). A pre-warmed, cached
    engine would cut that at the cost of memory held by the service process. This is not done;
  - Material icons are not tree-shaken in the Gradle-built release (1.6 MB).

- **Personalization**:
  - the `fp1` contents are not final (the extractor is still choosing them), so the matcher has only seen
    synthetic vectors;
  - the per-feature std floors for `fp1` are **provisional** (0.25 × the population std over real clips,
    `tools/fp_floors.py`), not the extractor's per-feature scales. Replacing them is a JSON change
    (`assets/fp_floors.json`, or the `fp_floors` op on a device);
  - `extractor/vox_extract/personal.py`, the Python mirror of the matcher, still has the old rules (pairwise maximum
    for 4+ examples, no floor);
  - gesture matches are only logged; there is no on-phone enrollment recording yet (the PC pushes examples).

- **Speech recognition**: `PhraseRecognizer` is an interface; `StubPhraseRecognizer` produces nothing. Phrases
  come in as the feature message's `phrase` field.
- **No trained target model.** `vox-jevlike` answers only the gesture question, so the intent tests use the suite's
  fake. Set `target_model` once a real one is served.
- Domain gaps in the target options, seen in the harvest:
  - clickable ImageViews (Gallery actions, the VLC/Gallery "More options") are `image`, where the training data
    would say `button`;
  - Organic Maps' controls are `item`;
  - Fennec exposes only its toolbar, not the page content;
  - the fixture feed has no targets at all.

- **BLE GATT source**: implemented, but not run against a device. Reassembly, decoding, INFO and backoff are
  unit-tested, and the ops run on the emulator, but connect/bond/notify need the phone and the Pico (manual test
  above). Real device timestamps are unverified; the suite uses host monotonic ms as the "device" clock. The CONFIG
  characteristic is only a debug op (`ble_config`); nothing in the app writes it yet. `ble_forget` cannot remove
  the Android bond (no public API).
- `take_photo`: reported as unsupported (no reliable cross-app shutter; `open_camera` works through an intent).
- The API key is stored in plain app-private SharedPreferences; Keystore encryption is a TODO.
- The settings UI is minimal: no profile editor (profiles are pushed as JSON through the `profile` op). `jitter_ms`
  is settable only through `config`.
- The pixel confirmer cannot tell our effect from ambient motion. A playing video or an animation that changes
  more than 0.5% of the grid during the timeout reads as "confirmed (pixels)". It only runs when no event confirmed.
  `takeScreenshot` is rate-limited by the OS (one per second), so an action that starts less than 1 s after the
  previous one's baseline gets no pixel check (`by: screenshot rate-limited`) unless the previous watch's timeout
  screenshot is recent enough to reuse (PROTOCOL.md "confirm").
- Not tested on a physical phone. `usesCleartextTraffic=true` is set so the suite can reach its local fake servers;
  turn it off for release.

## Things learned the hard way

- `suite/voxlib.start_activity` uses `am start -S`, which force-stops the package. Pointed at VOX itself, that kills
  the accessibility service and removes it from `enabled_accessibility_services`. VOX's own screen is therefore
  started without `-S`.
- nixpkgs' Flutter makes Gradle exit 1 **with no output** unless the plugin's relocated cache dirs are passed
  (nix/README.md).
- `flutter run -d linux` opens on the user's Wayland session even under `xvfb-run`. For headless runs use
  `env -u WAYLAND_DISPLAY GDK_BACKEND=x11 xvfb-run ...`.

- **`uiautomator dump` suppresses every accessibility service** and makes it reconnect. For about 2 s afterwards,
  the service sees a stale window list and dispatched gestures are cancelled. The suite therefore never uses
  uiautomator: it reads the screen through the app's own `dump` op, including for clicking through first-run
  dialogs.
- Stand-ins restore their last screen: VLC reopens its last tab, and Fennec restores the scroll position. The tests
  navigate to a known start state first. Without that, VLC's swipe correctly came back as "no visible change".
- Organic Maps downloads a 69 MB world map on first launch; `setup` does it.
- `pgrep -f "[u]vicorn servers"` matched the shell running it, because that pattern appeared in the shell's own
  command line. `run.sh jev` therefore matches `[b]in/uvicorn servers` instead.
- Stand-ins also restore state that breaks tests over many runs. Organic Maps restores its zoom, and repeated zoom-in
  runs reached the maximum (5 m scale), where a pinch-out changes nothing; the test now zooms out first. VLC's
  collapsing app bar can move its tab strip up, so the tab finder accepts y from 150 to 450.
- `/home/khoa/VOX` became a git repository. A nix flake inside a git repository sees only tracked files, so `./dev`
  now uses `path:` to reach `nix/`.
- The emulator has network access, and NewPipe shows live YouTube content. The NewPipe assertion therefore checks the
  selected tab, not the content.
