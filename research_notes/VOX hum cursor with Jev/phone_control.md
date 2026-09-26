# Phone control for VOX: Pico 2 W → BLE GATT → companion app → taps/swipes (Android first; iOS limits) — as of late Sept 2026

Scope: the phone side of the chosen design (Pico 2 W extracts features/labels → custom BLE GATT notify → phone app → decision model (Jev over HTTPS, local model, or rules) → gesture injection), plus no-app alternatives (BLE HID) and what iPhone allows. BLE HID mouse basics (hog_mouse_demo, AssistiveTouch pointer, 7.5–15 ms intervals) are already in `hardware_and_output.md` §2 and are not repeated except where needed. Tags: [forum] = forum/community only; [3rd-party] = press or blog, not a primary source; [AOSP] = read directly from Android source code.

## 1. Android gesture injection via AccessibilityService

### Takeaway
An AccessibilityService with `canPerformGestures="true"` can tap, swipe, long-press and drag anywhere with `dispatchGesture` (API 24+). Continued strokes (API 26+) let one finger stay down across successive gestures, which gives continuous drags. `performGlobalAction` covers Back, Home, Recents, Notifications, Quick Settings, D-pad (API 33+) and Menu/Media (API 36). A `TYPE_ACCESSIBILITY_OVERLAY` window can draw a pointer. Google's open-source Project Gameface (Android) is almost exactly the VOX architecture with a different input source, so it is the best code to copy. For a class project, install with Android Studio/ADB. That avoids the Play policy review and, per press reports, the restricted-settings block. Set `isAccessibilityTool="true"` anyway, because Android 17's Advanced Protection Mode revokes accessibility access from apps that don't declare it.

### Cited Findings
**dispatchGesture / GestureDescription**
- `dispatchGesture(GestureDescription, GestureResultCallback, Handler)` was added in API 24. The docs say: "Dispatch a gesture to the touch screen. Any gestures currently in progress, whether from the user, this service, or another service, will be cancelled. The gesture will be dispatched as if it were performed directly on the screen by a user, so the events may be affected by features such as magnification and explore by touch." The service "must declare the capability by setting the `canPerformGestures` property in its meta-data." It returns "true if the gesture is dispatched". The callback reports completion or cancellation, and a null handler means callbacks run on the main thread — [AccessibilityService reference](https://developer.android.com/reference/android/accessibilityservice/AccessibilityService#dispatchGesture(android.accessibilityservice.GestureDescription,%20android.accessibilityservice.AccessibilityService.GestureResultCallback,%20android.os.Handler))
- The official tap example builds `new StrokeDescription(path(point), 0, ViewConfiguration.getTapTimeout())` and dispatches it. The docs frame this as a fallback when `ACTION_CLICK` fails — [AccessibilityService reference](https://developer.android.com/reference/android/accessibilityservice/AccessibilityService)
- Limits: `getMaxStrokeCount()` and `getMaxGestureDuration()` (API 24) are documented without values. The AOSP source sets `MAX_STROKE_COUNT = 20` and `MAX_GESTURE_DURATION_MS = 60 * 1000`, and `Builder.addStroke` throws when either is exceeded [AOSP] — [GestureDescription.java](https://github.com/aosp-mirror/platform_frameworks_base/blob/main/core/java/android/accessibilityservice/GestureDescription.java); [GestureDescription reference](https://developer.android.com/reference/android/accessibilityservice/GestureDescription). `getDisplayId()` was added in API 30 (multi-display) — same reference.
- StrokeDescription:
  - The `(path, startTime, duration, willContinue)` constructor was added in API 26: "`true` if this stroke will be continued by one in the next gesture… Continued strokes keep their pointers down when the gesture completes."
  - `continueStroke(path, startTime, duration, willContinue)` (API 26) creates "a new stroke that will continue this one. This is only possible if this stroke will continue." The "starting point of this path must match the ending point of the stroke it continues".
  - The path "Must have exactly one contour… If the path has zero length (for example, a single moveTo()), the stroke is a touch that doesn't move."
  - Source: [StrokeDescription reference](https://developer.android.com/reference/android/accessibilityservice/GestureDescription.StrokeDescription)
- AOSP enforces the chaining rule. `continueStroke` throws "Only strokes marked willContinue can be continued" [AOSP] — [GestureDescription.java](https://github.com/aosp-mirror/platform_frameworks_base/blob/main/core/java/android/accessibilityservice/GestureDescription.java)

**performGlobalAction constants (API level added)** — [AccessibilityService reference](https://developer.android.com/reference/android/accessibilityservice/AccessibilityService)
- BACK, HOME, RECENTS, NOTIFICATIONS: API 16. QUICK_SETTINGS: 17. POWER_DIALOG: 21. TOGGLE_SPLIT_SCREEN: 24. LOCK_SCREEN and TAKE_SCREENSHOT: 28.
- API 31: ACCESSIBILITY_BUTTON, ACCESSIBILITY_BUTTON_CHOOSER, ACCESSIBILITY_SHORTCUT, ACCESSIBILITY_ALL_APPS ("show Launcher's all apps"), DISMISS_NOTIFICATION_SHADE, KEYCODE_HEADSETHOOK (answers or hangs up calls, plays or stops media).
- DPAD_UP/DOWN/LEFT/RIGHT/CENTER: API 33.
- MENU and MEDIA_PLAY_PAUSE: API 36 (Android 16).

**Other relevant APIs**
- `onMotionEvent(MotionEvent)` (API 34) lets a service observe generic MotionEvents from sources set with `AccessibilityServiceInfo.setMotionEventSources`, and those events "are not sent to the rest of the system". This is for observing and consuming input, not injecting it — [AccessibilityService reference](https://developer.android.com/reference/android/accessibilityservice/AccessibilityService)
- `TYPE_ACCESSIBILITY_OVERLAY` (2032): "Windows that are overlaid only by a connected AccessibilityService for interception of user interactions without changing the windows an accessibility service can introspect." — [WindowManager.LayoutParams reference](https://developer.android.com/reference/android/view/WindowManager.LayoutParams#TYPE_ACCESSIBILITY_OVERLAY)

**Working open-source template: Project Gameface (Android), Apache-2.0**
- It uses "the Android accessibility service to create a new cursor". MediaPipe face blendshapes are mapped to actions: Tap, Home, Notification, Pause cursor, Reset cursor, "Drag and hold" (set start and end points) and All apps — [project-gameface Android README](https://github.com/google/project-gameface/tree/main/Android)
- Code details, all from the [project-gameface repo](https://github.com/google/project-gameface):
  - `ServiceUiManager.java` draws the cursor and drag line in `TYPE_ACCESSIBILITY_OVERLAY` windows with `FLAG_NOT_TOUCHABLE`.
  - `DispatchEventHelper.java` taps with a 250 ms stroke and uses `SWIPE_DURATION_MS = 100` ("fast enough to change page in launcher app") and `DRAG_DURATION_MS = 250`. It calls `performGlobalAction` for HOME, BACK, NOTIFICATIONS and ACCESSIBILITY_ALL_APPS.
  - Its drag is a single swipe from a stored start to end point, not continued strokes.
  - The service config sets `canPerformGestures="true"` and `isAccessibilityTool="true"`.
- EVA Facial Mouse is a GPL-3.0 camera-based mouse for Android built on an accessibility service, developed with Fundación Vodafone España and ASPACE — [cmauri/eva_facial_mouse](https://github.com/cmauri/eva_facial_mouse); [eViacam news](https://sourceforge.net/p/eviacam/news/2016/02/introducing-eva-facial-mouse-a-eviacam-port-for-android-devices/). It is older (2016 era) and predates API 24 gestures in parts of its design [3rd-party].
- Google's TalkBack source is public (`google/talkback`: `talkback`, `braille`, `utils`, …). No Switch Access or Voice Access module was visible in the top-level listing — [google/talkback](https://github.com/google/talkback)

**Google Play policy** — [Play Console Help: Use of the AccessibilityService API](https://support.google.com/googleplay/android-developer/answer/10964491)
- Declaring `isAccessibilityTool` exempts an app from the prominent-disclosure requirement.
- Eligible examples: "Screen readers…" and "Switch-based input systems which support people with motor impairments".
- "A general assistant that is voice-activated… would not qualify". Automation tools, assistants and launchers are listed as non-qualifying.
- "Any use of the Accessibility API that enables an app to autonomously initiate, plan, and execute actions or decisions is strictly prohibited". Verified accessibility tools "are exempt from this prohibition".
- Since November 3, 2021, apps targeting API 31 with an AccessibilityService must complete a Play Console declaration.

**Advanced Protection Mode (Android 16 feature; accessibility restriction in Android 17)**
- With AAPM on, the system "prevent[s] users from granting Accessibility Services permission to non-Accessibility Tools" and "revokes the permission if it was already granted". This was seen in Canary 2602 (Feb 2026) and targeted for Android 17. AAPM is opt-in, not the default — [Android Authority, Feb 13 2026](https://www.androidauthority.com/android-advanced-protection-mode-accessibility-apk-teardown-3640742/) [3rd-party]; [Security Affairs](https://securityaffairs.com/189497/security/advanced-protection-mode-in-android-17-prevents-apps-from-misusing-accessibility-services.html) [3rd-party]
- Qualifying categories: screen readers, switch-based input, voice-based input, braille — [Android Authority](https://www.androidauthority.com/android-advanced-protection-mode-accessibility-apk-teardown-3640742/) [3rd-party]

**Restricted settings (Android 13+) and sideloading**
- To unlock: Settings → Apps → [app] → ⋮ More → "Allow restricted settings". Google warns against doing this unless you trust the developer — [Google Android Help 12623953](https://support.google.com/android/answer/12623953)
- Android 13 restricts apps "installed from an app that didn't use the purpose-built installation API designed for app stores… web browsers, messaging apps, or file managers". Android 15 extends this to `PACKAGE_SOURCE_LOCAL_FILE` installs and to more permissions: accessibility, notification listener, device admin, display overlay, usage access, SMS, dialer. "The session-based installation API… and ADB installations are not subject to these restrictions." — [Android Authority, Sep 12 2024](https://www.androidauthority.com/android-15-restricted-settings-sideloading-3481098/) [3rd-party]. A developer blog reports that `adb shell settings put secure enabled_accessibility_services` can be blocked for sideloaded apps on newer versions — [dev.moe](https://dev.moe/en/3030) [forum]
- Developer verification timeline:
  - August 2026: developer APIs, limited-distribution accounts and the "power user advanced flow" launch.
  - September 30, 2026: enforcement begins in Brazil, Indonesia, Singapore and Thailand for participating stores, on certified devices running Android 7+.
  - 2027+: global rollout.
  - Limited-distribution accounts let "students, teachers, and hobbyists… share apps with up to 20 devices without a government-issued ID or registration fee."
  - Source: [Android developer verification](https://developer.android.com/developer-verification)
- ADB installs remain exempt from developer verification, according to press coverage of Google's FAQ. The official page I fetched did not state this — [Android Authority timeline](https://www.androidauthority.com/android-sideloading-changes-timeline-3679204/) [3rd-party]

### Inferences
- **Discrete actions** (tap, 4-direction swipe, scroll page): build one `GestureDescription` with one stroke. Use about 100–300 ms per swipe (Gameface uses 100 ms swipes and 250 ms drags/taps) and ~50–100 ms for taps. Scroll = a short swipe in the opposite direction to the content motion. Back, Home, Recents and Notifications should use `performGlobalAction`, not gestures, because it is more reliable across launchers and gesture-navigation modes.
- **Continuous drag / "hold and move"**: dispatch a first stroke with `willContinue=true`, then on each new VOX update call `continueStroke()` with a short segment (e.g. 30–60 ms) that starts where the last one ended, and finish with `willContinue=false`. Each dispatch cancels any gesture in progress, including the user's real touches. So never overlap dispatches: wait for `onCompleted`, or queue segments. Apart from the 60 s / 20-stroke limit per `GestureDescription`, chaining is the documented way to exceed a single gesture's length. No official statement caps the total length of a chain; that is unverified.
- **Cursor overlay**: a small `TYPE_ACCESSIBILITY_OVERLAY` view with `FLAG_NOT_TOUCHABLE | FLAG_NOT_FOCUSABLE` that you move with `updateViewLayout` is the Gameface pattern. Taps go to the cursor's coordinates. Because the overlay is not touchable, injected gestures pass through it.
- **Policy fit**: VOX is a switch-like input system for people with motor impairments. That plausibly fits Google's "accessibility tool" definition, and declaring `isAccessibilityTool="true"` also protects it from the Android 17 AAPM revocation. Letting Jev "decide" what to do is borderline under the "autonomously initiate, plan, and execute" clause. VOX should only execute user-intended commands, not have the model take autonomous actions. For a class project none of this matters: install from Android Studio (ADB). That avoids the restricted-settings prompt and, per press reports, developer verification.
- **Where to host the BLE client**: an AccessibilityService is bound and kept alive by the system while enabled. The GATT connection can therefore live inside the service, without a separate foreground service. This is not confirmed by an official doc; a foreground service (see §2) is the safe fallback.

### Gaps
- No primary measurement of `dispatchGesture` latency (from the call to the target app receiving `ACTION_DOWN`) was found. Anecdotally it is tens of ms, but I have no citable figure.
- The official docs do not state whether `continueStroke` chains have a total-duration limit, or how OEM gesture navigation (edge swipes for Back) interacts with injected edge swipes.
- I did not confirm whether Google's Switch Access or Voice Access source is public. The talkback repo listing showed no such module.

## 2. The BLE link: Pico GATT server (BTstack) ↔ Android/iOS central

### Takeaway
Use the pico-examples `ble_temp_sensor` server pattern: a `.gatt` file compiled at build time, `att_server_init`, and notifications through `att_server_request_can_send_now_event` → `att_server_notify`. Replace the Environmental Sensing service with a custom 128-bit UUID service, as BTstack's `gatt_streamer_server` does. Android can request an 11.25–15 ms interval (CONNECTION_PRIORITY_HIGH), and the peripheral can request its own interval with `gap_request_connection_parameter_update`. So the BLE hop is about 1–2 connection intervals (~15–30 ms), which is negligible next to Jev's ~250 ms median. On iOS, the `bluetooth-central` background mode keeps notifications arriving in the background, but iOS apps cannot act on them by injecting touches (§4).

### Cited Findings
**Pico side (pico-sdk + BTstack)**
- pico-examples `bluetooth/ble_temp_sensor` has a `server.c` ("a peripheral or server that transmits its temperature") and a `client.c` — [pico-examples ble_temp_sensor](https://github.com/raspberrypi/pico-examples/tree/master/bluetooth/ble_temp_sensor)
  - `temp_sensor.gatt`: a `PRIMARY_SERVICE, ORG_BLUETOOTH_SERVICE_ENVIRONMENTAL_SENSING` service with `CHARACTERISTIC, ORG_BLUETOOTH_CHARACTERISTIC_TEMPERATURE, READ | NOTIFY | INDICATE | DYNAMIC`.
  - CMake runs `pico_btstack_make_gatt_header(ble_temp_server PRIVATE ".../temp_sensor.gatt")` and links `pico_btstack_ble` + `pico_btstack_cyw43`.
  - `server.c`:
    - Calls `att_server_init(profile_data, att_read_callback, att_write_callback)`.
    - In the write callback, watches the `…_CLIENT_CONFIGURATION_HANDLE` (the CCCD the phone writes to enable notify).
    - Calls `att_server_request_can_send_now_event(con_handle)`, then `att_server_notify(con_handle, …_VALUE_HANDLE, data, len)` on `ATT_EVENT_CAN_SEND_NOW`.
    - Uses a 1000 ms heartbeat timer.
    - Advertises via `gap_advertisements_set_params/set_data/enable`.
- A custom 128-bit service is declared as in BTstack's `gatt_streamer_server.gatt`: `PRIMARY_SERVICE, 0000FF10-0000-1000-8000-00805F9B34FB` and `CHARACTERISTIC, 0000FF11-…, WRITE_WITHOUT_RESPONSE | NOTIFY | ENCRYPTION_KEY_SIZE_16 | DYNAMIC`. `gatt_streamer_server.c` calls `gap_request_connection_parameter_update(con_handle, 12, 12, 4, 0x0048)`, reads MTU from `ATT_EVENT_MTU_EXCHANGE_COMPLETE`, and sends with `att_server_notify` on `ATT_EVENT_CAN_SEND_NOW` — [btstack example/gatt_streamer_server.gatt](https://github.com/bluekitchen/btstack/blob/master/example/gatt_streamer_server.gatt); [gatt_streamer_server.c](https://github.com/bluekitchen/btstack/blob/master/example/gatt_streamer_server.c)
- The BTstack API is `int gap_request_connection_parameter_update(hci_con_handle_t, conn_interval_min, conn_interval_max, conn_latency, supervision_timeout)`, with intervals in 1.25 ms units — [btstack src/gap.h](https://github.com/bluekitchen/btstack/blob/master/src/gap.h)

**Android central (Kotlin, `android.bluetooth`)**
- Notifications: `setCharacteristicNotification(char, true)` enables delivery locally, and then the CCCD must be written. After that, "a `BluetoothGattCallback.onCharacteristicChanged(BluetoothGatt, BluetoothGattCharacteristic, byte[])` callback will be triggered". BLUETOOTH_CONNECT is required on targetSdk ≥ 31 — [BluetoothGatt reference](https://developer.android.com/reference/android/bluetooth/BluetoothGatt#setCharacteristicNotification(android.bluetooth.BluetoothGattCharacteristic,%20boolean))
- `requestConnectionPriority` (API 21) offers four priorities — [BluetoothGatt reference](https://developer.android.com/reference/android/bluetooth/BluetoothGatt#requestConnectionPriority(int))
  - BALANCED: "parameters recommended by the Bluetooth SIG"; the default.
  - HIGH: "a high priority, low latency connection… should only request high priority… to transfer large amounts of data… then request BALANCED… to reduce energy use".
  - LOW_POWER.
  - DCK (API 34): "priority preferred for Digital Car Key for a lower latency connection… more power".
- AOSP defaults: HIGH = interval 9–12 (11.25–15 ms), BALANCED = 24–40 (30–50 ms), LOW_POWER = 80–100 (100–125 ms). Values come from the Bluetooth app `config.xml` — [AOSP Bluetooth diff](https://android.googlesource.com/platform/packages/apps/Bluetooth/+/31c02c5a770c0c12becb0856b2c7132470a49939%5E2..31c02c5a770c0c12becb0856b2c7132470a49939/); [Nordic DevZone](https://devzone.nordicsemi.com/f/nordic-q-a/17099/why-has-android-started-giving-such-long-connection-intervals) [forum]
- MTU: "starting from Android 14, the Android Bluetooth stack requests the BLE ATT MTU to 517 bytes when the first GATT client requests an MTU, and disregards all subsequent MTU requests" — [BluetoothGatt.requestMtu](https://developer.android.com/reference/android/bluetooth/BluetoothGatt#requestMtu(int))
- Keeping the connection alive in the background:
  - Foreground service type `connectedDevice`, with the `FOREGROUND_SERVICE_CONNECTED_DEVICE` permission and `startForeground(…, FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)`.
  - Runtime prerequisite: for example, BLUETOOTH_CONNECT granted.
  - Google suggests CompanionDeviceManager and its presence API "to help your app stay running while the companion device is in range" for continuous transfer.
  - Source: [FGS service types](https://developer.android.com/develop/background-work/services/fgs/service-types)

**iOS central (CoreBluetooth)**
- With the `bluetooth-central` background mode, the app "can still discover and connect to peripherals, and explore and interact with peripheral data". "The system wakes up your app when any of the CBCentralManagerDelegate or CBPeripheralDelegate delegate methods are invoked… when a peripheral sends updated characteristic values".
  - Background scans coalesce duplicates and slow down.
  - State preservation tracks the connected peripherals and subscribed characteristics.
  - The system may still terminate the app "to free up memory", dropping connections.
  - Source: [Apple Core Bluetooth Programming Guide – background](https://developer.apple.com/library/archive/documentation/NetworkingInternetWeb/Conceptual/CoreBluetooth_concepts/CoreBluetoothBackgroundProcessingForIOSApps/PerformingTasksWhileYourAppIsInTheBackground.html)
- Apple's accessory guidelines set a 15 ms minimum connection interval, with down to 11.25 ms accepted when BLE HID is present (see `hardware_and_output.md` §2) — [Silicon Labs summary of Apple ADG](https://docs.silabs.com/bluetooth/9.1.1/mobile-apps-suitable-connection-parameters/)

**Latency/power**
- Android accepts connection intervals down to 7.5 ms. Community measurements show button-to-LED delays of ~70–150 ms at default parameters and ~10 ms after tuning [forum] — [ST Community](https://community.st.com/t5/stm32-mcus-wireless/how-to-reduce-ble-notification-latency/td-p/306291); [Nordic DevZone](https://devzone.nordicsemi.com/f/nordic-q-a/86619/ble-configuration-for-low-latency-applications) [forum]
- Peripheral latency lets the peripheral skip connection events while idle: "With a 100ms connection interval and peripheral latency of 4, the peripheral can sleep through up to 4 consecutive events (400ms)". The constraint is "Supervision timeout > (1 + Peripheral latency) × Connection interval × 2" — [Punch Through connection parameters guide](https://punchthrough.com/ble-connection-parameters-guide/)

### Inferences
- **Payload**: VOX events are tiny, e.g. `{seq, event_id, label, confidence, pitch_bucket, duration_bucket}`, about 8–20 bytes. They fit in the default 23-byte ATT MTU (20-byte payload), so MTU negotiation is optional. Send one notify per detected sound event, plus an optional 10–30 Hz "continuous" stream only while a glide/drag is active.
- **Connection parameters**: have the Pico request 12–24 (15–30 ms) with peripheral latency of about 4 for idle power savings, and the Android app call `requestConnectionPriority(HIGH)` while in continuous mode and BALANCED otherwise. The expected BLE contribution is ~15–50 ms. That is small compared with Jev (median 252.8 ms, p95 436.6 ms per `jev.md`).
- **Radio sharing**: the Pico no longer needs WiFi, which removes the CYW43439 WiFi/BLE time-sharing concern from `hardware_and_output.md` §1.
- **Security**: use LE Secure Connections pairing (as in pico-examples `ble_secure_temp_sensor`) and `ENCRYPTION_KEY_SIZE_16` on the characteristic, so another phone can't subscribe to or spoof VOX commands. An unencrypted notify link that drives an accessibility service is an injection vector.
- **Two roles at once is possible**: the Pico can expose the custom GATT service and a HID-over-GATT service in one GATT database. The phase-1 HID mouse firmware can then grow into phase 2 without re-pairing. This is not tested; BTstack supports multiple services in one `.gatt` file.

### Gaps
- No measured CYW43439/BTstack notify latency or current draw per connection interval was found. Power use for Pico 2 W in a BLE connection is unquantified in the sources fetched.
- No official Android doc confirms which interval a given phone actually grants for HIGH on Android 16/17. The AOSP defaults above come from an older commit, and OEMs may override them.

## 3. No-app Android alternative: BLE HID digitizer/touchscreen, mouse drag, consumer keys

### Takeaway
Android classifies an input device as a touchscreen only if the kernel reports multi-touch/absolute axes with `INPUT_PROP_DIRECT`. In principle, a BLE HID digitizer reaches the kernel through uhid/hid-multitouch. In practice, the only ESP32 BLE touchscreen project found says "with android, some are ok, some are not working". A BLE HID **mouse** is the reliable no-app path: button-held drag acts like a swipe, and the wheel scrolls. **Consumer-control** usages give Home, Back, volume, play/pause, Recents and All-apps through standard kernel → Android keycode mappings.

### Cited Findings
- Android input classification: a device is multi-touch if it reports `ABS_MT_POSITION_X` and `ABS_MT_POSITION_Y`. It is then classified as a touch screen, touch pad or pointer. `INPUT_PROP_DIRECT` → touch screen; `INPUT_PROP_POINTER` → pointer device (indirect, cursor) — [AOSP Touch devices](https://source.android.com/docs/core/interaction/input/touch-devices)
- ESP32 "BLE_HID_TouchScreen" is recognized as a "HID-compliant touch screen" on a laptop. "With android, some are ok, some are not working." It gives no device list and no multi-touch details [3rd-party] — [AiueoABC/BLE_HID_TouchScreen](https://github.com/AiueoABC/BLE_HID_TouchScreen)
- The ESP32 lib `topcoco/ESP32-BLE-HID` advertises keyboard, "Abs Mouse" and touchscreen modes [3rd-party] — [topcoco/ESP32-BLE-HID](https://github.com/topcoco/ESP32-BLE-HID). The T-vK ESP32-BLE-Mouse issue asking for BLE touchscreen/absolute coordinates (Feb 2020) has no answer [forum] — [T-vK issue #5](https://github.com/T-vK/ESP32-BLE-Mouse/issues/5)
- PiKVM: "Bluetooth mouse can work only in relative mode… many Bluetooth host drivers do not correctly implement HID descriptors" — [PiKVM docs](https://docs.pikvm.org/bluetooth_hid/) (already in `hardware_and_output.md`)
- Consumer-control key chain (HID usage page 0x0C → Linux key → Android keycode):
  - Linux `hid-input.c` maps 0x223 → `KEY_HOMEPAGE`, 0x224 → `KEY_BACK`, 0x0E9/0x0EA → `KEY_VOLUMEUP/DOWN`, 0x0CD → `KEY_PLAYPAUSE`, 0x221 → `KEY_SEARCH`, 0x2A2 → `KEY_ALL_APPLICATIONS` — [linux drivers/hid/hid-input.c](https://github.com/torvalds/linux/blob/master/drivers/hid/hid-input.c)
  - Android `Generic.kl` maps key 172 → `HOME`, 158 → `BACK`, 114/115 → `VOLUME_DOWN/UP`, 113 → `VOLUME_MUTE`, 164 → `MEDIA_PLAY_PAUSE`, 139 → `MENU`, 580 → `APP_SWITCH`. It also has usage fallbacks `0x0c029F RECENT_APPS` and `0x0c02A2 ALL_APPS` — [AOSP Generic.kl](https://github.com/aosp-mirror/platform_frameworks_base/blob/main/data/keyboards/Generic.kl) [AOSP]

### Inferences
- **Recommended no-app Android path**: a composite HOG device with a relative mouse (buttons + dx/dy + wheel) plus a consumer-control report.
  - Swipe = button-1 down, a series of dx/dy reports over ~150–300 ms, button up.
  - Scroll = wheel reports.
  - Home/Back/Recents/volume = consumer keys (0x223 / 0x224 / 0x29F / 0xE9 / 0xEA).
  - Android shows its own mouse pointer for a connected mouse, so no overlay is needed. That is standard Android behaviour, but I have no specific citation for it here.
- A mouse gives only relative positioning. To tap a fixed screen location, you must "home" the pointer first, e.g. with a large move into a corner, then move by known steps. Pointer acceleration makes step sizes nonlinear. That is a reason to prefer the companion app (absolute coordinates via `dispatchGesture`) on Android.
- A digitizer descriptor is not worth the risk for a class project: support varies by device, and iOS doesn't accept touch digitizers as touch input (it expects pointers through AssistiveTouch).

### Gaps
- No primary test report of a BLE (not USB) HID multi-touch digitizer on a named Android 14–17 phone was found. Whether the GKI kernel's `hid-multitouch` binds to BLE uhid devices on all OEMs is unverified.
- No citation found for Android's default mapping of mouse right-click to Back. It is commonly reported but not verified here.

## 4. iPhone: what's possible without jailbreak

### Takeaway
Third-party iOS apps cannot inject touches into other apps. Only the system creates `UITouch`/`UIEvent` objects, and the only examples of touch simulation require jailbreak. An iOS companion app can therefore receive the Pico's GATT notifications but cannot act on them system-wide. What gives the Pico swipe-like control is to make it an **input device that iOS accessibility features consume**:
- (a) **BLE HID mouse + AssistiveTouch**: pointer, Dwell, custom recorded gestures, and multi-finger swipe via the menu. This is the best general option.
- (b) **BLE HID keyboard used as Switch Control switches**: each key maps to an action such as Select, Move to Next, Home, scroll or gestures, plus Recipes. This is the most deterministic option for "swipe left/right/up/down".
- (c) **Full Keyboard Access**: keyboard navigation with customizable commands.

Shortcuts automations cannot perform arbitrary taps. Also, iOS already has **native non-speech sound triggers**: AssistiveTouch "Sound Actions" (mouth pop, S-sound) and "Sound" as a Switch Control source. That overlaps directly with VOX's premise.

### Cited Findings
**No touch injection**
- Developer-forum consensus: valid `UITouch`/`UIEvent` objects can only be created by the system. A user building a TeamViewer-like remote control was advised to call control actions within their own app, not to inject touches. There was no Apple staff reply [forum] — [Apple Developer Forums thread 129316](https://developer.apple.com/forums/thread/129316)
- System-wide touch simulation libraries such as IOS13-SimulateTouch require a jailbroken device [3rd-party] — [xuan32546/IOS13-SimulateTouch](https://github.com/xuan32546/IOS13-SimulateTouch)

**AssistiveTouch (pointer + gestures)**
- AssistiveTouch can:
  - "Perform multifinger gestures", "Perform scroll gestures", open Control Center, notifications, Lock Screen and App Switcher, adjust volume and take screenshots.
  - For multifinger swipe or drag: "Tap Device > More > Gestures, then tap the number of digits… swipe or drag in the direction required".
  - Source: [iPhone User Guide – Use AssistiveTouch](https://support.apple.com/guide/iphone/use-assistivetouch-iph96b21954/ios)
- Pointer devices: "You can connect Bluetooth® and USB assistive pointer devices, such as trackpads, game controllers, and mouse devices". Settings: "Devices: Pair or unpair devices and customize buttons", Mouse Keys, Pointer Style, Always Show Menu, Tracking Sensitivity — same guide
- Dwell Control: "iPhone performs a selected action when you hold the cursor still". Options include Movement Tolerance, Fallback Action, and Hot Corners that can "take a screenshot, open Control Center, activate Siri, scroll, or use a shortcut" — same guide
- Custom gestures:
  - Settings → Accessibility → Touch → AssistiveTouch → Create New Gesture. "If you record a sequence of taps or drag gestures, they're all played back at the same time."
  - To use one: "tap Custom, then choose the gesture. When the blue circles representing your gesture appear, drag them to where you want to use the gesture, then release".
  - Source: [iPhone User Guide – Use AssistiveTouch](https://support.apple.com/guide/iphone/use-assistivetouch-iph96b21954/ios); [Apple Support 111794](https://support.apple.com/en-us/111794) ("You can record custom taps and swipes… and save them to the AssistiveTouch menu")
- Custom actions for menu-button Single-Tap/Double-Tap/Long Press — [Apple Support 111794](https://support.apple.com/en-us/111794). Pointer "Drag Lock" lets you drag without holding the button, and Dwell works "without physically pressing buttons" — [Apple Support 111775](https://support.apple.com/en-us/111775)
- **Native sound triggers**: "With AssistiveTouch, you can have iPhone perform a gesture or other action when you make a simple sound, such as a mouth pop or an S-sound… Tap Sound Actions, then tap a sound. Select the gesture or other action" — [iPhone User Guide – Use AssistiveTouch](https://support.apple.com/guide/iphone/use-assistivetouch-iph96b21954/ios)

**Switch Control**
- Switch sources: "Add New Switch, then choose External, Screen, Camera, Back Tap, Sound, or AirPod Gestures". A Bluetooth switch must be paired in Settings → Bluetooth first. Each switch gets an assigned action (e.g. Select Item, Move to Next Item).
  - "Recipes—a set of temporary, specialized actions" can be assigned to switches, "for repetitive, complex actions in apps such as turning pages in the Books app".
  - Switch Sets hold profiles. Scanning styles are Auto, Manual (≥2 switches) and Single Switch Step. There is a "Long Press" alternate action per switch.
  - Source: [iPhone User Guide – Set up and turn on Switch Control](https://support.apple.com/guide/iphone/set-up-and-turn-on-switch-control-iph400b2f114/ios)
- Switch Control can "select, tap, or drag items, type, and even freehand draw". It offers item scanning, point scanning (crosshairs) and manual selection. A menu gives Tap, gestures, and "Scroll", plus hardware functions (Home, Notification Center, Control Center, volume, lock, screenshot, Siri) — [Apple Support 119835](https://support.apple.com/en-us/119835)
- A BLE HID keyboard works as external switches: "Tap on 'Add new switch' and then 'External'. You will now be prompted to press one of your switches." Assignable actions include Select Item, Scanner Menu, Move to Next/Previous Item, Home, scrolling, touchscreen gestures, Control Center, notifications and volume, and each switch gets a second action on Long Press [3rd-party] — [Adafruit: Configuring iOS Switch Control](https://learn.adafruit.com/ios-switch-control-using-ble/configuring-ios-switch-control). "iOS Switch Control will respond to a standard Bluetooth HID Keyboard… every key on the keyboard" can be a switch [3rd-party] — [ATMakers](https://atmakers.org/2016/10/ios-switch-control-on-a-budget-using-bluetooth-kbd/)

**Full Keyboard Access**
- Turn it on in Settings → Accessibility → Keyboards & Typing → Full Keyboard Access. Commands are listed and can be customized under "Commands" — [iPhone User Guide – Control iPhone with an external keyboard](https://support.apple.com/guide/iphone/control-iphone-with-an-external-keyboard-ipha4375873f/ios) (via search snippet; the page body did not render when fetched)

### Inferences
- **Best iOS path for swipes**: the Pico presents a composite **BLE HID keyboard + mouse** (the same HOG firmware as phase 1).
  - Switch Control mode: assign keys (e.g. F13–F18 or letters) to Switch Control actions. Use Recipes whose "custom gesture" steps are swipe left/right/up/down, since Recipes are built for "turning pages". Use the Long Press alternate for a second action per key. This gives discrete, deterministic swipes without a cursor.
  - AssistiveTouch mode: HID mouse movement drives the pointer. Button-1 drag swipes (with Drag Lock if holding is awkward). Map additional mouse buttons (buttons 3–5) to AssistiveTouch actions such as Home, App Switcher, a Custom gesture or scroll. Apple's text only says "customize buttons", so the exact action list per button is unverified.
- **An iOS companion app adds almost nothing for control.** It could show status or configure the Pico, and it could call Jev, but it can't act. Any decision model on iOS must therefore sit on the Pico or be bypassed. Alternatively, the Pico, as a HID device, emits keys that Switch Control maps.
- **Shortcuts app**: automations can run Shortcuts actions (open app, media, system settings). They cannot synthesize taps or swipes into arbitrary apps. No Apple doc was fetched to confirm the complete action list, so treat this as an inference.
- **Critical project-level point, stated once**: iOS AssistiveTouch Sound Actions and Switch Control "Sound" switches already map non-speech sounds (pop, S-sound, and others) to gestures, natively and on-device, with no hardware. VOX's added value on iPhone has to be clearly argued: more sound classes, pitch glides as continuous control, robustness, or a hands-free wearable mic. Otherwise a reviewer will ask why not use the built-in feature.

### Gaps
- Apple's current list of Sound Action sounds (iOS 26) and whether pitch/hum classes exist was not fetched.
- Whether Switch Control Recipes can hold a user-defined swipe as a step on iOS 26 was not verified in an Apple doc; it is inferred from the Recipe and custom-gesture docs.
- The Full Keyboard Access command list (e.g. gesture or scroll commands) could not be read; the Apple page body didn't render.
- No test of Pico 2 W `hog_keyboard_demo` as a Switch Control switch was found (ESP32/Bluefruit reports only).

## 5. Where to put the decision model (Jev vs local vs rules) and latency budgets

### Takeaway
With the phone as the hub, calling Jev from the app costs about 250 ms median / 440 ms p95 (third-party measurement) plus 30–50 ms of mobile-network RTT. That is acceptable for **discrete** commands (swipe, back, home), where total sound-end-to-action is roughly 0.3–0.6 s. It is unacceptable for **continuous** cursor/drag. Continuous control should be a local rules or tiny-model path on the phone (LiteRT / ONNX Runtime Mobile / Core ML) or on the Pico. Jev should be reserved for fuzzy disambiguation or user-defined mappings.

### Cited Findings
- Jev latency: TypeSafe claims 70–500 ms end to end. The HF Decision Index measured jev-1.13.0 at median 252.8 ms and p95 436.6 ms over HTTP. Unauthenticated POSTs (network/TLS floor only) took 137–203 ms from one box — see `jev.md` §3; [TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev); [HF Decision Index data](https://huggingface.co/spaces/multimodalart/jev-decision-index/raw/main/data/index.json)
- Jev handles numeric input poorly, so VOX should send pre-bucketed categorical features, e.g. `{"pitch_band":"low","contour":"falling",…}` — `jev.md` (TypeSafe docs cited there)
- Mobile network: T-Mobile US had the lowest median 5G latency at 44 ms. NSA 5G has a floor of about 30 ms, and standalone 5G is 20–30% lower [3rd-party summary of Opensignal] — [Opensignal 2025 US analysis](https://insights.opensignal.com/2025/11/benchmarking-readiness-for-advanced-5g-consumer-services/dt); [RCR Wireless](https://rcrwireless.com/20250627/test-and-measurement/t-mobile-us-test)
- LiteRT is "Android's official ML inference runtime" with CPU/GPU/NPU backends — [Android Developers: Use LiteRT on Android](https://developer.android.com/ai/custom). ONNX Runtime Mobile is a lean runtime for Android and iOS, with a QNN execution provider for Qualcomm NPUs [3rd-party] — [Fora Soft 2026 guide](https://www.forasoft.com/blog/article/neural-networks-on-android-369)
- Gameface runs MediaPipe face landmarks on-device and maps blendshape thresholds to actions, with no cloud call in the loop — [project-gameface Android README](https://github.com/google/project-gameface/tree/main/Android)

### Inferences
- **Latency budget (discrete swipe via Jev)**:

  | Step | Time |
  |---|---|
  | Sound ends → Pico labels it | ~50–150 ms, depends on the event-end detector |
  | BLE notify | ~15–50 ms |
  | App → Jev, HTTPS keep-alive, phone on LTE/5G | ~250 ms median, ~450 ms p95, plus ~40 ms RTT |
  | `dispatchGesture` swipe stroke | 100–250 ms |
  | **Total** | **~0.45–0.9 s** |

  That is usable for page-flip-style swipes but noticeably sluggish. Without Jev (a rules table on the phone or Pico) the total drops to ~0.2–0.45 s.
- **Continuous control** (pitch glide → cursor or drag): must never wait on the network. The Pico streams a 10–30 Hz "glide" value. The app integrates it into cursor position (overlay) or into `continueStroke` segments locally. Jev at most decides mode switches ("enter drag mode", "was that intentional?").
- **Suggested split**:
  1. Deterministic mapping table (label → action) on the phone as the default.
  2. Optional small local classifier (LiteRT or ONNX) if Pico features are richer than labels.
  3. Jev as an asynchronous "second opinion" or for natural-language user mappings. When Jev is unreachable, fall back to the table so the phone is never locked into an unresponsive state.
- Put a hard **timeout** (e.g. 600 ms) on Jev calls and drop stale decisions. A swipe executed a second late after the user has moved on is worse than none.

### Gaps
- No measured Jev latency from a phone on cellular (all figures are from servers or a wired box).
- No benchmark of a tiny audio or feature classifier on LiteRT vs ONNX Runtime Mobile on a mid-range phone was fetched. Such a model is expected to take microseconds to a few ms, but this is unsourced.

## 6. Recommended architecture and phased build (class project)

### Takeaway
Phase 1 (no app, both OSes): the Pico is a composite BLE HID mouse + keyboard + consumer-control device driven by on-Pico rules. Phase 2 (Android): add a custom GATT service to the same firmware, plus a Kotlin companion app. The app hosts an AccessibilityService that does BLE, the decision (rules → optional Jev), `dispatchGesture` / `performGlobalAction`, and a cursor overlay. It is installed via Android Studio/ADB, declared `isAccessibilityTool`, and modelled on Project Gameface. iOS stays on the phase-1 HID path through Switch Control and AssistiveTouch; an iOS app can't inject gestures.

### Cited Findings
- Phase 1 building blocks: BTstack `hog_mouse_demo` / `hog_keyboard_demo` in pico-examples, and iOS pointer via AssistiveTouch — [pico-examples README](https://github.com/raspberrypi/pico-examples/blob/master/README.md); [Apple Support 111775](https://support.apple.com/en-us/111775) (details in `hardware_and_output.md` §2)
- Phase 2 building blocks:
  - GATT notify server pattern: [pico-examples ble_temp_sensor](https://github.com/raspberrypi/pico-examples/tree/master/bluetooth/ble_temp_sensor) and [btstack gatt_streamer_server](https://github.com/bluekitchen/btstack/blob/master/example/gatt_streamer_server.gatt).
  - Android APIs: [dispatchGesture / global actions](https://developer.android.com/reference/android/accessibilityservice/AccessibilityService) and [continued strokes](https://developer.android.com/reference/android/accessibilityservice/GestureDescription.StrokeDescription).
  - Overlay and gesture code to copy: [project-gameface Android](https://github.com/google/project-gameface/tree/main/Android).
- Distribution: install with ADB or Android Studio; restricted settings exempt ADB per [Android Authority](https://www.androidauthority.com/android-15-restricted-settings-sideloading-3481098/) [3rd-party]; free "limited distribution" accounts for up to 20 devices per [Android developer verification](https://developer.android.com/developer-verification)
- iOS: Switch Control with external (BLE keyboard) switches, Recipes and gestures — [Apple Switch Control setup](https://support.apple.com/guide/iphone/set-up-and-turn-on-switch-control-iph400b2f114/ios); AssistiveTouch pointer, Dwell and custom gestures — [Apple AssistiveTouch guide](https://support.apple.com/guide/iphone/use-assistivetouch-iph96b21954/ios)

### Inferences
**Phase 1 — HID only (1–2 weeks)**
- Firmware: a composite HOG device (relative mouse with wheel + keyboard + consumer control) in a single `.gatt`/report map.
- A local rules table maps sound labels to actions:
  - Swipes: mouse drag.
  - Scroll: wheel.
  - Back/Home/Recents on Android: consumer keys 0x224 / 0x223 / 0x29F.
  - Switch keys on iOS: F-keys mapped in Switch Control.
- Deliverable demo: swipe through a photo gallery / reels on both OSes. Known limits: relative pointer only, no absolute taps on Android without homing, and iOS setup is manual.

**Phase 2 — Android companion app (2–4 weeks)**
- Firmware: add a `VOX_SERVICE` (128-bit UUID) with `EVENT` (notify: seq, label, confidence, buckets) and `STREAM` (notify, 10–30 Hz, only during glides) characteristics, plus a `CONFIG` (write) characteristic. Use LE Secure Connections pairing and keep HID in the same database, or behind a firmware mode switch.
- App (Kotlin), a single AccessibilityService:
  - Config: `canPerformGestures`, `isAccessibilityTool`, `accessibilityFlags` minimal.
  - Owns a `BluetoothGatt` client (autoConnect, CCCD, `requestConnectionPriority(HIGH)` during stream mode) and a `TYPE_ACCESSIBILITY_OVERLAY` cursor.
  - Action executor: taps and swipes via `dispatchGesture`, drags via `continueStroke`, and `performGlobalAction` for BACK/HOME/RECENTS/NOTIFICATIONS.
  - Decision layer: a rules table first, then an optional Jev call with timeout and fallback; the API key is kept on the phone.
  - A settings Activity for mapping and calibration, and a visible "VOX armed" indicator plus an emergency stop (e.g. a long hum = pause).
- Evaluation: log timestamps (Pico event end, BLE receive, decision, gesture completed) to measure the real latency budget. Primary data here fills the gaps above.

**Phase 3 (optional)**
- iOS polish: ship Switch Control recipe and key-mapping instructions, and possibly a small iOS app only for configuring the Pico over GATT. It cannot control the phone.
- Android: add continuous cursor mode (pitch glide → overlay cursor → dwell tap), mirroring Gameface.

**Skeptical checks**
- Is Jev needed in the loop at all? After bucketing, the label → action mapping is a table (see `jev.md`). Keep Jev optional and off the critical path.
- On iPhone, the native Sound Actions feature already does "sound → gesture". Position VOX's iOS story accordingly.
- The accessibility service is powerful, and any BLE peer that can write to it can drive the phone. Require bonding and encryption.

### Gaps
- No end-to-end latency figures exist yet for this exact pipeline; phase-2 logging should produce them.
- Effort estimates above are unsourced judgment.
