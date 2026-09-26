# VOX device → phone protocol (v1)

Every feature source (the BLE GATT client, which is still a stub, and the two debug sources) delivers the same JSON
message to the app. The app does the rest: sequencing, the decision, the gesture and the confirmation.

## Feature message

```json
{
  "v": 1,
  "id": 1042,
  "mode": "gesture",
  "armed": true,
  "sounds": [
    "hum that rises from low to high; pitch change large (over 4 semitones); duration short (150-400 ms); tone clear tone; loudness normal; sounds like hum"
  ],
  "sequence": ["rise"],
  "timing": [{"t_start_ms": 81234, "t_end_ms": 81512}],
  "phrase": null,
  "cursor": null
}
```

| field | type | meaning |
|---|---|---|
| `v` | int, default 1 | Protocol version. Anything else is rejected. |
| `id` | int, optional | Message id. A repeat of the previous id is ignored, which absorbs BLE retransmits. |
| `mode` | `gesture` \| `cursor` \| `listening` | The device's mode. **The device owns the mode**: it toggles on a single button click, or when the app asks through CONFIG (*App commands*), and the app follows this flag. No model action enters or leaves it (the schema has no `enter_cursor_mode` or `exit_cursor_mode`). `listening` is sent with a spoken phrase; it does not change the app's gesture/cursor mode. |
| `armed` | bool, default true | `false` = disarm (a button hold, going to sleep, or an app command). The app drops pending sounds, stops the cursor, closes the listening window and discards decisions in flight. The next armed message re-arms. |
| `sleeping` | bool, optional, default false | `true` only on the last message before the device goes to sleep (always with `armed: false`). See *Sleep and wake*. |
| `rejected` | str, optional | Present only on the reply to a CONFIG command the device refused: the reason. See *App commands*. |
| `sounds` | list of str (0–3) | One categorical description per sound, exactly the text after `sound i: ` in the model state (format below). |
| `sequence` | list of str, same length | The sound labels: `rise fall arch dip flat pop click hiss unknown`. |
| `timing` | list, optional, same length | Per sound, `{"t_start_ms", "t_end_ms"}` on the **device's** monotonic clock (ms since the Pico booted). An entry may be `null`. Only differences matter: the phone never compares these values with its own clock. The ends must not be before the starts, and the starts must not decrease within a message. Strongly recommended: see *Sound grouping* below. |
| `phrase` | str or null | A transcribed phrase. It is accepted only while a listening window is open (opened by `listen_for_phrase`, default `click pop`, and lasting `listen_window_ms`, default 6000). Otherwise it is logged as `ignored`. |
| `features` | list, optional, same length | Per sound, `null` or `{"fp": [float, ...], "fp_version": "fp1", "pitch16": [16 floats] or []}`: the sound fingerprint (an opaque vector of the declared version, 1–256 values) and the pitch track (16 points in semitones relative to the start; empty for unpitched sounds). Used for personalization (below). A malformed entry rejects the message; a version or length that differs from the enrolled examples is only skipped for matching (logged). |
| `cursor` | str or null | Reserved. The app describes the cursor itself ("moving up fast", "stopped", ...). |

The message is validated by `FeatureMessage.parse`. A bad message gets `{"ok": false, "error": ...}` and an `ignored`
event.

### Sound lines

These are the strings generate.py produces (`deliberate_sound` / `air_hiss` / the discrete sounds), joined with `"; "`:

- hum: `hum that <contour>; pitch change <small (under 2 semitones)|medium (2-4 semitones)|large (over 4 semitones)>; duration <...>; tone <clear tone|breathy|noisy>; loudness <quiet|normal|loud>; sounds like <hum|talking|laughing|coughing|background music|...>`
- hiss: `a hiss; duration <...>; loudness <...>; sounds like <mouth sound|background noise>`
- pop / click: `a short lip pop|a tongue click; instant sound; loudness <...>; sounds like mouth sound`

The device firmware must emit exactly these phrasings. They come from `finetune/vox/schema.py`, and the app
checks them against the same vocabulary, generated into `Vocab.kt` by `tools/gen_vocab.py` with a source digest.

### When does the app act?

The app acts at once, **unless the active profile binds a longer sequence that starts with the sounds heard so far**.
Only then does it wait for the next sound.
- With the defaults, only `click` waits (for `click pop`). `pop` acts immediately because `pop pop` is unbound.
- If a profile binds `pop pop` for an app, a single `pop` in that app waits.
- In cursor mode, only cursor-scope rules count. By default nothing waits there: `click click` is unbound unless a user
  rule binds it, for example to `drag_toggle`.

The device may send one sound per message, or a whole sequence (up to 3) in one message. Both go through the same
sequencer.

### Sound grouping: device clock first, arrival fallback

Grouping happens on the phone, but it uses the device's timestamps:

- **Device clock** (every sound has `timing`):
  - Two sounds belong to one sequence if and only if `next.t_start_ms - previous.t_end_ms <= gap_ms` (default 600).
    BLE retries and stalls therefore cannot merge two separate sounds (a burst after a stall) or split one sequence
    (a late follow-up). The only exception is a follow-up that arrives after the wait has already closed.
  - The phone learns the offset between its arrival times and the device clock: the minimum of `arrival - t_end_ms`
    over the last 16 stamped sounds. From that it knows how late a sound arrived.
  - The wait is `max(0, gap_ms - lag) + jitter_ms`, where `jitter_ms` (default 150) allows for the follow-up itself
    arriving late. A click that arrives 300 ms late therefore waits only 450 ms, not 750 ms.
  - A device clock that goes backwards (a reboot, or a 32-bit wrap) splits the sequence and resets the estimate.
- **Arrival fallback** (no `timing`): sounds that arrive while the previous one is waiting belong together, and the
  wait is `gap_ms` from arrival.

The `resolve` event records `clock` (`device` | `arrival`), `gaps_ms` (the device gaps), `ended_by`
(`no-continuation`, `max-length`, `timeout`, `device-gap`, `device-clock-reset`, `flush`, `context-change`) and a
`note`, for example when a split was made by device gap, or when a sound arrived after its group had already
resolved. The `wait` event records `wait_ms` and `clock`.

Cost: with stamps, a waiting sound that arrived on time waits `gap_ms + jitter_ms` (750 ms) instead of `gap_ms`. This
only affects sounds that start a bound multi-sound sequence (by default only `click`).

## Control messages (debug sources only)

`{"type": "control", "op": ...}` returns a JSON reply on the socket.

| op | args | reply / effect |
|---|---|---|
| `ping` | | `app`, `mode`, `armed`, `paused`, `waiting`, `settings` (API key redacted), `vocab` digest, `decisions` |
| `config` | any of `decider` (`rules`\|`model`\|`hybrid`), `base_url`, `model`, `api_key`, `min_confidence`, `http_timeout_ms`, `gap_ms`, `jitter_ms`, `confirm_timeout_ms`, `listen_window_ms`, `target_min_confidence`, `target_model`, `target_choose_ms`, `enroll_reject_mult`, `ble_device` (a Bluetooth address, or `null`) | Applies the settings and rebuilds the decider. |
| `profile` | `profile`: profile JSON, or `null` for the bundled default | Replaces the profile (format in `Profile.kt`). Its optional `name` (default `default`) selects the enrollment store. |
| `enroll_add` | `kind` (`custom`\|`ignore`\|`gesture`), `name`, `examples`: list of `{fp, fp_version, pitch16}` | Adds examples to a class of the active profile, creating it if needed. All-or-nothing: rejected if any example has another `fp_version` or length than the store, if the class would exceed 10 examples, or if a `gesture` class is not named after a gesture (contour gestures need a 16-point `pitch16`). Reply: `enrollment` (as `enroll_list`). |
| `enroll_list` | | `enrollment`: `profile`, `fp_version`, `dim`, `reject_mult`, `floors` (see `fp_floors`), and per class `kind`, `name`, `examples`, `active` (3+ examples), `contour`, `threshold`, `dtw_threshold`. |
| `fp_floors` | none; or `table`: `{"<fp_version>": {"floor": [...], "provisional": bool, "source": "..."}}`; or `reset: true` | The per-feature std floors (Personalization, below). `table` stores an on-device override (`files/fp_floors.json`) whose entries replace the bundled ones per version; `reset` removes it. Reply: `table` (in use), `override` (bool), `status`. |
| `enroll_delete` | `name` and optional `index`, or `all: true` | Deletes a class, one of its examples, or every class of the active profile. |
| `screen` | | `line` (the `screen:` line) and `summary` (the raw tree summary) |
| `dump` | | The visible nodes of the app window: `id cls text desc click scroll bounds` |
| `harvest` | `tag` | Appends `{tag, package, screen_text, summary}` to `files/harvest.jsonl`. |
| `pause` | `paused` (bool, default `true`) | Pauses or resumes VOX from the phone, like the status screen's button (logged `pause{by: "op"}`). While paused, messages still update `armed` and `mode`, but their sounds and phrases are ignored (`ignored{reason: "paused (app)"}`). Reply: `paused`. |
| `reset` | `clear_log`, `clear_harvest` (bool) | Drops pending state, re-arms, resumes, forgets the device-clock estimate, cancels a target choice, and optionally clears the files. |
| `targets` | | Intent cursor mode's view of the screen: `package`, `screen_text`, `options` (exactly what the `target` question would send, NONE last) and `targets[{option, bounds}]`. |
| `ble_scan` | `ms` (default 10000, 1000–60000) | Scans for devices advertising the VOX service; each new one is logged (`ble{what: found}`) and listed in `ble_status`. |
| `ble_connect` | `address` (`AA:BB:CC:DD:EE:FF`, or `auto`, the default) | Connects and keeps reconnecting (it also ends a `needs_pairing` stop). `auto` = the remembered device, else the strongest one found, else scan and take the first. The device is remembered (`ble_device`) once the link is ready. |
| `ble_status` | | `ble`: `state` (`off`, `idle`, `scanning`, `connecting`, `discovering`, `bonding`, `subscribing`, `ready`, `waiting`, `needs_pairing`), `why`, `adapter`, `permissions`, `remembered`, `target`, `mtu`, `bonded`, `info` (the device's INFO), `ready_ms`, `reconnect_in_ms`, `failures`, `auth_failures`, `hint` (what the user must do, or null), `messages`, `fragments`, `gaps`, `bad`, `found`, and `device`: `presence` (`listening`, `awake – paused`, `asleep`, `pairing needed`, `connecting`, `not connected`, `bluetooth off`, or null when no device is set up), `ready`, `asleep`, `armed`, `mode` (the device's last word), `waiting_for` (the command awaiting confirmation) and `error` (the last failed command). |
| `ble_disconnect` | | Drops the link and stops reconnecting until the next `ble_connect` (the device stays remembered). |
| `device` | `armed` (bool) and/or `mode` (`gesture`\|`cursor`), or `sleep: true` alone | An app command to the device (*App commands (CONFIG)* above), written only on a ready link. Replies at once: `device_cmd{result: sent}`, or an error (no device connected, the device is asleep, busy with a previous command, invalid). The outcome follows as a `device_cmd` event: `confirmed` when the device's next no-sound state message arrives (for `sleep`, its `sleeping: true` message), `failed` when the device's reply carries `rejected` (at once, with its reason), the write fails, the link drops, or nothing arrives within 1500 ms (a write the stack blocked). The status screen shows the failure. |
| `ble_forget` | | Disconnects and forgets the remembered device. The Android bond is kept (remove it in Bluetooth settings). |
| `ble_config` | `config`: a JSON object | Writes it to the device's CONFIG characteristic (reserved; e.g. `{"v":1,"test_sounds":true}`). Needs a ready link. |

## Transports

1. **Debug socket** (what the suite uses). This is an abstract Unix socket, `vox-debug`, carrying newline-delimited
   JSON with one reply line per message.
   ```
   adb forward tcp:7788 localabstract:vox-debug
   printf '%s\n' '{"v":1,"id":1,"sounds":["a short lip pop; instant sound; loudness normal; sounds like mouth sound"],"sequence":["pop"]}' | nc -q1 127.0.0.1 7788
   ```
   Only peers with uid 0 or 2000 (adb shell) are accepted, and only on debuggable builds.
2. **Debug broadcast**. The receiver is protected by `android.permission.DUMP`, which adb has and ordinary apps
   cannot get. The reply is logged as a `reply` event.
   ```
   adb shell am broadcast -a ai.vox.companion.DEBUG -n ai.vox.companion/.DebugBroadcastReceiver --es b64 $(printf '%s' "$json" | base64 -w0)
   ```
3. **BLE GATT (v1): the Pico 2 W link.** Specified below. The firmware is `firmware/`; the app side is `BleFeatureSource`.

## BLE GATT link (v1)

The Pico is a BLE peripheral; the phone is the central. The messages are the same JSON feature messages as above.

**Advertising.** Name `VOX-XXXX` (the last 2 bytes of the device address, in hex). The service UUID is in the advertisement, so the app scans by that filter.

| Characteristic | UUID | Properties | Content |
|---|---|---|---|
| Service | `ac740001-3c66-cc47-6290-e0e7094c17b9` | | |
| EVENT | `ac740002-3c66-cc47-6290-e0e7094c17b9` | notify | Feature messages, fragmented (below) |
| CONFIG | `ac740003-3c66-cc47-6290-e0e7094c17b9` | write | A JSON object written by the phone: the *App commands* below, or `{"v":1,"test_sounds":true}`. The device ignores unknown keys |
| INFO | `ac740004-3c66-cc47-6290-e0e7094c17b9` | read | `{"v":1,"fw":"0.1.0","mic":"inmp441"\|"none","fp_version":"fp1"\|null}` |

**Fragmentation.** A message with a fingerprint is larger than one notification (at most MTU − 3 bytes; 514 at the requested MTU of 517; the device must also work at the default 23). Each EVENT notification is `[header byte][UTF-8 chunk]`:
- bit 7 is set on the **last** fragment of a message;
- bit 6 is set on the **first** fragment of a message (a single-fragment message has both bits set);
- bits 0–5 are a counter: 0 for the first notification after each connection, then +1 per notification, mod 64, across messages.

The app starts a message at a fragment with bit 6 set and appends chunks until one with bit 7 set, then parses the whole message. If the counter skips a value, the partial message is dropped (logged as `ble_gap`) and the app waits for the next fragment with bit 6 set. A message may be at most 4096 bytes of UTF-8. Anything larger is a device bug; the app drops it.

**State on connect.** As soon as the phone enables EVENT notifications, the device sends one no-sound message with its current `armed` and `mode`, so the app never has to guess them after a (re)connect.

**One sound per message.** The device sends each sound as soon as it ends, in its own message with its device timestamps. The phone groups sounds into sequences using those timestamps (*Sound grouping*), so the device never waits for a follow-up.

**Arm, pause, mode changes and sleep reach the phone as messages with no sounds**, e.g. `{"v":1,"id":7,"mode":"gesture","armed":false,"sounds":[],"sequence":[]}`. This is true whether a button or the app caused them.

**The button.** The device has one button:

| Press | Awake | Asleep |
|---|---|---|
| 5 quick presses | toggle: if armed, turn off (disarm, then sleep); if not armed, arm | wake, then arm once the phone has subscribed |
| 1 click | toggle `mode` gesture ↔ cursor | nothing |
| hold 1 s | disarm at once (the fast stop); sleep on release | nothing |
| hold 5 s | disarm, then open the pairing window instead of sleeping | wake and open the pairing window |

Two to four presses do nothing. Presses belong to the same series while each follows the previous one within a short gap (firmware `config.h`), so a single click acts only after that gap.

**App commands (CONFIG).** Accepted only on an encrypted link (or on an `insecure` debug build, which needs no encryption for anything), while the device is awake and connected:
- `{"v":1,"armed":true}` or `{"v":1,"armed":false}`: arm or pause. The device stays awake and connected.
- `{"v":1,"mode":"gesture"}` or `{"v":1,"mode":"cursor"}`: set the mode. `armed` and `mode` may be sent in one write.
- `{"v":1,"sleep":true}`: the same as turning it off with the button. Its confirmation is the `sleeping: true` message, which the device sends before sleeping, however sleep was triggered. A stay-awake build (see *Power banks* below) does not sleep: it answers with a plain `armed: false` state message and keeps the link, and the app counts that as applied.

**Replies.** Every command write that reaches the firmware gets exactly one no-sound state message in reply, even if nothing changed. The app treats that message as the confirmation, not the write's success.
- A command the device refuses gets the same reply, carrying `"rejected": "<reason>"` (e.g. `"bad value for mode"`). The state fields show that nothing changed.
- A write the Bluetooth stack blocks before it reaches the firmware (an unencrypted link) gets no reply. The app times out.
- Every state message, confirmations included, carries a fresh `id`.

The button and the app are equal: the most recent action wins.

**Sleep and wake.**
- **Going to sleep.** The device first sends a no-sound message with `"armed": false, "sleeping": true`. It then drops the link and turns off Bluetooth and the mic.
- **The app while the device sleeps.** It shows the device as asleep, not as a connection error, and keeps reconnecting quietly in the background.
- **Waking.** 5 presses wake the device, which then advertises to bonded phones. It arms itself once a phone subscribes: its state-on-connect message says `armed: true`, because the presses were the user asking to listen. If no bonded phone connects within 60 s, it goes back to sleep.
- **Power banks.** A build option (`VOX_SLEEP_STAYS_AWAKE=1`) turns sleep into "disarm and stay awake": no `sleeping` message, no link drop, just `armed: false`. Some power banks switch off when the draw becomes very small.

**Pairing.**
- New bonds are accepted only during a **60 s pairing window**, opened by holding the button 5 s. The LED blinks fast while the window is open.
- Outside the window the device rejects pairing requests, and only phones that are already bonded can reach EVENT and CONFIG.
- Opening the window drops any connected phone. The device can hold only one link, and the phone being paired needs it. The dropped phone sees an ordinary disconnect: it comes back disarmed.
- A bonded phone may reconnect while the window is open.
- When the window closes without a new bond, the device goes to sleep, unless a phone is connected. In that case it stays awake and disarmed.
- Every firmware flash erases the bonds, so after a flash you hold the button to pair again.

**Security.** LE Secure Connections bonding ("Just Works"; the device has no display or keypad). Android may still show a "Pair with VOX-XXXX?" confirmation once. EVENT and CONFIG require an encrypted link. A debug firmware build may turn encryption off for PC testing, and says so in INFO (`"insecure": true`).

**Disconnect** means the device is disarmed: the app behaves as on `armed: false`. After an unexpected disconnect, such as the phone going out of range, the device stays **disarmed** when the phone reconnects. The user re-arms with 5 presses or from the app. Only waking with 5 presses arms on connect.

## Event log

Each event is one JSON line: `{"ev": name, "t": elapsedRealtime ms, ...}`. It is written to logcat, tag `VOX`
(`adb logcat -v raw -s VOX:I`), and to `files/events.jsonl` (`adb exec-out run-as ai.vox.companion cat files/events.jsonl`).
Logcat cuts lines at about 3.8 KB, so the file is the complete record. The API key is never logged.

The event chain for one decision (`n` links the events of one decision; `watch` links the gesture to its confirmation):

```
msg → [wait] → resolve{n, sequence, phrase, waited, held_ms, app} → state{n, text}
    → decision{n, action, source, confidence, ms} → exec{n, ok, how, watch}
    → gesture{watch, result} → confirm{watch, result, by, ms, echoes_ignored}
```

The confirmer's `result` is one of:
- `confirmed (events)`: an accessibility event showed an effect (a scroll, a window change, a text change, or a
  content change that altered the visible-tree fingerprint).
- `confirmed (pixels)`: no event came, but a `takeScreenshot` taken before dispatch and one taken at the timeout differ
  in more than 0.5% of a 36x80 luminance grid. System bars and VOX's own overlays are masked out. This covers GL
  surfaces such as maps.
- `no visible change`.

Clicks, long clicks, selections and focus changes that arrive while our own injected gesture is running, or within
250 ms after it, are echoes of our touch. They are counted in `echoes_ignored` and never confirm anything.

`decision` also carries `server_ms` (the server's `latency_ms`, when a model answered) and `top` (the model's best
options with probabilities).

Intent cursor mode (see below) adds its own chain, linked by `n`:

```
listening{mode: cursor} → [asr] → msg{phrase} → target_state{n, app, text, options}
    → target_decision{n, choice, confidence, top, ms, server_ms, min_confidence}   (or {n, error})
    → target{n, result: "tap" | "choose" | "not on screen" | "no model (decider=rules)", ...}
    → [choice{n, event: select | picked | ignored | cancelled, selected, option, why}] → exec/gesture/confirm as above
```

Other events: `mode`, `arm`, `listening`, `ignored{reason}`, `app`, `service`, `source`, `profile`, `screen`,
`harvest`, `reset`, `error`, `cursor`, `toast{text}`, `asr` (the phrase recognizer; currently a stub),
`match`, `enroll` and `fp_floors{fp_version, status, source, note}` (personalization, below), and the BLE link's events:
- `ble{what, ...}`: `start`, `scan`, `found{address, name, rssi}`, `state{state, why, address}`,
  `priority{high}` (the result of `requestConnectionPriority(HIGH)`, asked right after connecting), `mtu{mtu}`,
  `info{fw, mic, fp_version, insecure, raw}`, `bond{state, previous}`, `remember`, `disarm{reason}`, `forget`,
  `adapter`, `permissions`, `config_write{bytes, started}` / `config_write{status}` (the write's result),
  `asleep` (the device said `sleeping: true`), `awake` (a connection reached it again), and
  `auth_failed{reason, problem, failures, bonded, hint}`: pairing or encryption failed twice in a row (GATT/HCI status
  5, 6, 15, 61 or 137, or bonding fell back to none). The source stops retrying and enters `needs_pairing`. `problem`
  and the `hint` it sets:
  - `window_closed` (the phone was not bonded and bonding was refused): "Hold the VOX button 5 s until the light
    blinks fast, then connect.";
  - `stale_bond` (bonded, but encryption failed: a firmware flash erased the device's bonds): forget `VOX-XXXX` in
    the phone's Bluetooth settings, then the same hold line;
  - `unknown`: both lines ("If VOX-XXXX was re-flashed, forget it ... first", then the hold line).

  Removing the bond, `ble_connect`, or the status screen's **Connect** starts again. Nothing escalates while the
  device sleeps;
- `device_cmd{cmd, result: sent | confirmed | failed, error, ms, applied, armed, mode, sleeping}`: an app command
  (`pause`, `arm`, `mode cursor`, `sleep`, ...). `applied: false` on a confirmation means the device's state message
  shows something else (the button acted in between: the latest action wins). A refusal is `failed` with
  `error: "the device refused it (<reason>)"`;
- `ble_gap{expected, got, dropped_bytes}`: a skipped fragment counter; the partial message was dropped;
- `ble_bad{reason}`: an unusable notification or message (empty, not UTF-8, not one JSON object, a control message,
  longer than 4096 bytes, a continuation fragment with no first fragment, a first fragment before the previous
  message's last).
Messages that arrive over BLE are logged as `msg{source: "ble"}` like any other. The first message of each link
(normally the no-sound state message the device sends when EVENT notifications are enabled) is logged as
`msg{source: "ble-connect"}`. It clears the duplicate-id memory, because the device's message ids restart at 1 on every
boot. A dropped link logs `msg{source: "ble-disconnect", armed: false}` and `arm{state: disarmed, by: "ble disconnect"}`.
The device's `sleeping: true` message logs `msg{sleeping: true}` and `arm{state: disarmed, by: "device (going to
sleep)"}`. The link drop that follows is expected: no second disarm, and the source waits for the device quietly
(the background auto-connect, no backoff, no pairing escalation; `ble_status` `presence: asleep`). When 5 presses wake
it, the device's state-on-connect message says `armed: true`, and the app arms from it like from any message. After
an unexpected disconnect, the device comes back `armed: false`, and the app never arms it by itself.

The phone side adds:
- `pause{state: paused | resumed, by: app | op}`: VOX paused or resumed from the status screen (`app`) or the
  `pause` op. This is independent of the device's `armed`; see "UI channel" below;
- `ui{what: first_frame, since_process_start_ms, since_create_ms}`: the Flutter status screen drew its first frame
  (once per process).

## UI channel (Flutter screens ↔ service)

The launcher activity, `MainActivity` (a `FlutterActivity`), runs the `../ui` Flutter module. `UiBridge.kt`
connects it to the running accessibility service through two platform channels. Nothing leaves the phone.

- `ai.vox/backend` is a method channel (main thread). Its methods:
  - `status` returns a map: `service` (false, and nothing else, when the accessibility service is not running),
    `armed`, `paused`, `mode`, `app`, `decider`, `ble_state`, `ble_device`, `ble_hint` (the `needs_pairing` hint,
    or null), `device_state` (`ble_status` `device.presence`), `device_ready`, `device_armed`, `device_mode`,
    `device_waiting`, `device_error`, and `vocab`;
  - `setPaused {paused: bool}` does what the `pause` op does, logs `pause{by: app}`, and returns the status map;
  - `deviceCommand {armed?, mode?, sleep?}` does what the `device` op does, but answers only when the device has
    confirmed or the command failed: `{ok, cmd, result, error, ms, applied, armed, mode, sleeping}`;
  - `connectDevice` connects to the remembered device again (`ble_connect auto`; it also ends `needs_pairing`) and
    returns the status map;
  - `openLegacySettings` opens `LegacySettingsActivity`, the native screen (decider, endpoint, API key,
    permissions) that stays until Flutter screens replace it.
- `ai.vox/events` is an event channel: every event-log line as its JSON string, from the moment the screen listens.

The status screen's main button follows the device when one is connected (`device_ready`): **Pause VOX** sends
`{"armed": false}`, **Resume VOX** lifts an app-side pause and sends `{"armed": true}`. Without a connected device
it is the app-side pause (`setPaused`). The mode toggle and **Sleep device** appear only while the device is
connected.

The Dart side is `ui/lib/src/channel_backend.dart` (`ChannelBackend`). `FakeBackend` is the in-memory stand-in
used by the widget tests and the Linux desktop runner.

## Decider HTTP call

`POST {base_url}/v1/systemone`. `Authorization: Bearer <key>` is sent only when a key is set.

```json
{"state": "<Scene.text()>", "model": "<model>",
 "questions": {"action": {"type": "choice", "instructions": "<POLICY>", "criteria": {"swipe up": null, "...": null}}}}
```

`criteria` always lists the **full** option table (25 actions, or 24 in cursor mode) in `schema.py` dict order. The
suite checks the key order on the wire against `finetune/vox/schema.py`. JSON object keys are formally unordered, so
the server must not depend on this order.

The answer is `answers.action.choice` (an option text, mapped back to the action key) with `confidence`. If the
confidence is below `min_confidence` (0.5), the decision is `none`. On any error, the `model` decider falls back to
the rule table (source `model-fallback:...`). `hybrid` applies an explicit local binding first and asks the model
otherwise.

Test servers: the suite's fake `/v1/systemone` listens on host port **8767**; the real local server
(`finetune/servers/systemone.py`, started by `suite/run.sh jev start`) listens on **8765**. Both reach the emulator
through `adb reverse`.

## Intent cursor mode: the `target` question

In cursor mode the user can name an on-screen element ("the subscriptions tab") instead of steering the cursor there.

1. **Trigger.** `click pop` in cursor mode opens the listening window (`Decision("listen_for_phrase",
   "app:cursor-listen")`). `schema.CURSOR_ACTIONS` has no listen option and the generator never produces it, so the
   **app** handles this sequence and it is never sent to the action model. A cursor-scope profile rule for `click pop`
   overrides it (binding it to `none` disables it). Because `click pop` is now bound in cursor mode, a `click` there
   waits `gap_ms + jitter_ms` for a possible `pop`.
2. **Phrase.** The phrase arrives as the `phrase` field of a feature message (from the device, or from the on-phone
   `PhraseRecognizer`, which is a **stub**: `StubPhraseRecognizer` logs `asr` and produces nothing). A phrase inside
   the window in cursor mode becomes a `target` question; in gesture mode it is resolved as before.
3. **Options** (spec: the docstring of `finetune/vox/targets.py`; `Targets.kt`):
   - Nodes: visible, clickable or focusable, with the centre on screen. Not options: a scrollable non-clickable
     container, a focusable-only node covering more than half the screen, and a label-less focusable-only container
     that holds other targets (its children are the options).
   - `{label} ({role}, {position})`.
   - label = contentDescription, else text, else the first text of a non-clickable, non-focusable descendant
     (**addition to the spec**: rows whose title is on a child view), else the viewId tail with `_` as spaces, else
     `unlabeled`. Whitespace is collapsed; labels are capped at 60 characters (`...`).
   - role = `text field` (EditText or editable), `switch` (Switch/CheckBox), `tab` (…$Tab, TabView, a TabWidget child,
     or a same-class sibling row with one selected), `button` (Button/ImageButton), `list item` (collection item, or
     child of RecyclerView/ListView/GridView or of a node with rows/cols), `image` (ImageView), else `item`.
   - position = the 3x3 cell of the node's centre: `top left, top, top right, left, center, right, bottom left, bottom,
     bottom right`. A centre exactly on a third-line belongs to the cell right of / below it.
   - Order: by cell (top row first, left to right), then by top edge, then left edge. Duplicate option strings keep
     the first. At most 39 elements, then `none of these (the thing I named is not on screen)` last (40 total).
4. **Request.** The same endpoint and envelope as the action question, with question id `target`:

   ```json
   {"state": "mode: cursor\napp: NewPipe (org.schabi.newpipe)\nscreen: ...\nspoken target: \"the subscriptions tab\"",
    "model": "<target_model, or model if empty>",
    "questions": {"target": {"type": "choice", "instructions": "<TargetVocab.POLICY>",
                             "criteria": {"What's New (tab, top)": null, "...": null,
                                          "none of these (the thing I named is not on screen)": null}}}}
   ```

   `instructions` is `finetune/data/targets-v1/policy.txt`, generated into `TargetVocab.kt` by `tools/gen_vocab.py`
   (digest `80cfb75f0115eb6c`; `--check` detects drift).
5. **Answer.** `answers.target.{choice, probabilities, confidence}`. A choice not in the options is an error (logged,
   nothing tapped).
   - choice = NONE: toast **"not on screen"**.
   - confidence >= `target_min_confidence` (0.6): tap the element's centre (`tap_target`), confirmed as usual.
   - otherwise: numbered highlights on the (up to) 3 most probable elements, #1 selected (orange). `rise` = next,
     `fall` = previous (both wrap), `pop` = tap the selected one, `hiss` = cancel. No input for `target_choose_ms`
     (6000) cancels; each rise/fall restarts that timer. A mode change, disarm, reset or new phrase also cancels.
     Other sounds are ignored while choosing; sounds failing the not-deliberate gate (talking etc.) are ignored.
   - With `decider = rules` there is no model to ask: toast, and `target{result: "no model (decider=rules)"}`.

## Personalization: enrolled sounds rewrite the line

Design: `wiki/personalization.md`. The device sends a fingerprint with each sound (`features`, above). The app compares it
with the user's enrolled examples and rewrites the sound line **before** sequencing and before any decider sees it.

**Enrollment.** Per profile, any number of classes, each `custom` (a sound the user invented and named), `ignore`
(a sound that must never act: a sneeze, a laugh, a kettle) or `gesture` (the user's own rise, pop, ...), with 3–10
examples. Classes with fewer than 3 examples are stored but not matched. Examples are recorded on the PC for now and
pushed with `suite/enroll.py` (the `enroll_*` ops). The store is `files/enroll/<profile>.json` in app-private storage.

**Matching** (`Matcher` in `Personal.kt`):
1. Every fingerprint is standardised by the per-feature mean and std of all examples in the store, the std raised
   to a per-feature **floor** for the store's `fp_version`: std_used = max(std, floor) (still std 1 if that is 0).
   Without the floor, a feature that is nearly constant across every enrolled example is divided by its own noise,
   and that noise then outweighs the features that separate the classes. The floors are a table keyed by
   `fp_version`, bundled as `assets/fp_floors.json` and overridable on the device (`fp_floors` op). `fp1`'s are
   **provisional**: 0.25 × each feature's population std over 160,270 real clips (`tools/fp_floors.py`), until the
   extractor publishes per-feature scales; then only the JSON changes (`"provisional": false`). A version without an
   entry, or whose floor length differs, is matched without floors. The matcher logs which it uses
   (`fp_floors{status: provisional | final | none | mismatch}`, also `floors` in `match` and `enroll_list`).
2. The nearest example (Euclidean) over all active classes picks the class. A contour-gesture class (rise, fall, arch,
   dip, flat) is a candidate only for a sound with a 16-point pitch track, and must also pass a banded DTW test
   (band ±3, cost |a−b|) on the pitch tracks.
3. Reject threshold per class = its within-class distance × `enroll_reject_mult` (default 1.4). The within-class
   distance is the leave-one-out distance for every class size (3–10): the largest distance from one of its examples
   to the nearest of the others. (The pairwise maximum grows with the class's size and spread, so a class with more
   examples would accept ever farther sounds.) The DTW threshold is computed the same way on the pitch tracks.
4. Result: `custom`, `ignore`, `gesture`, `none` (nearest class beyond its threshold), or `skipped` (nothing enrolled,
   or another `fp_version` or length). Every attempt is logged:
   `match{id, i, profile, result, class, nearest, distance, threshold, dtw, dtw_threshold, reason, label, new_label, line, floors}`.

**Rewrite:**

| match | sound line | sequence label |
|---|---|---|
| custom `meow` | `my sound "meow"; duration <bucket>; loudness <bucket>` (the extractor's buckets; a pop/click line, which has no duration, gets `very short (under 150 ms)`) | `my:meow` |
| ignore | the extractor's line with `sounds like one of my ignore sounds` | unchanged |
| gesture, none, skipped | unchanged | unchanged |

**Deciding.** The model has no training data for these lines until data v6, so:
- a sound that `sounds like one of my ignore sounds` is always `none`, decided locally (source `personal:ignore-sound`);
- a custom sound is decided locally by the rule table (source `personal:custom-sound -> ...`): a fixed rule
  `{"sound": "my:meow", "action": "open_camera"}` (in `global`, `app:<pkg>` or `cursor`) runs its action, and an
  unbound custom sound is `none`. `"sound": "my:meow"` is shorthand for `"phrase": ["my:meow"]`; custom labels may also
  appear inside longer `phrase` sequences;
- only a plain-language rule (`kind: "rule"`) bound to exactly that sequence sends it to the model.

Fixed rules on custom sounds are not shown to the model under "my rules:".
