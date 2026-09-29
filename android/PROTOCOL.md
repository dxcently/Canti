# VOX device → phone protocol (v1)

Every feature source (the BLE GATT client `BleFeatureSource`, and the two debug sources) delivers the same JSON
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
| `by` | str, optional | `"button"` only: on a no-sound state message whose mode change the user made with the device's button. The app keeps that mode as the user's own (see *Disconnect*). Absent for console, app commands and everything else. |
| `sleeping` | bool, optional, default false | `true` only on the last message before the device goes to sleep (always with `armed: false`). See *Sleep and wake*. |
| `rejected` | str, optional | Present only on the reply to a CONFIG command the device refused: the reason. See *App commands*. |
| `sounds` | list of str (0–3) | One categorical description per sound, exactly the text after `sound i: ` in the model state (format below). |
| `sequence` | list of str, same length | The sound labels: `rise fall arch dip flat pop click hiss unknown`. |
| `timing` | list, optional, same length | Per sound, `{"t_start_ms", "t_end_ms"}` on the **device's** monotonic clock (ms since the Pico booted). An entry may be `null`. Only differences matter: the phone never compares these values with its own clock. The ends must not be before the starts, and the starts must not decrease within a message. Strongly recommended: see *Sound grouping* below. An entry may also carry `sound` (int) and `held` (bool): see *Hold messages*. |
| `phrase` | str or null | A transcribed phrase. It is accepted only while a listening window is open (opened by `listen_for_phrase`, default `click click click`, and lasting `listen_window_ms`, default 6000). Otherwise it is logged as `ignored`. A phrase in a message answers the window like the phone's recognizer would (*Spoken phrases*, below). |
| `features` | list, optional, same length | Per sound, `null` or `{"fp": [float, ...], "fp_version": "fp1", "pitch16": [16 floats] or []}`: the sound fingerprint (an opaque vector of the declared version, 1–256 values) and the pitch track (16 points in semitones relative to the start; empty for unpitched sounds). Used for personalization (below). A malformed entry rejects the message; a version or length that differs from the enrolled examples is only skipped for matching (logged). |
| `gated` | list, optional, same length | Per sound, `null` or why a guard turned the sound into `unknown` on purpose: `"media"` (`mic_media_gate`) or `"media_hiss"` (the media-hiss rule); only the phone/USB mic sets it (*Phone microphone*, Guards). A gated sound is never rewritten by personalization (below). |
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

### Pop is a click (2026-09-28)

A pop counts as a click on every source (the Pico, the phone mic, the USB mic, the tick detector, the debug socket).
The Pico keeps sending `pop`; the app maps it once, at intake. The single mapping point is `VoxService.features`, whose
first act is `SoundFold.fold`: the `sequence` label `pop` becomes `click`, and a sound line starting with `a short lip
pop` gets `a tongue click` in its place (both strings are ones the models already know). Everything downstream — the
sequencer, the decider, the media gate, personalization, the event log — sees `click`. `FeatureMessage.parse` and
`Message.LABELS` are unchanged: `pop` is still a valid input label. The `msg` event logs the raw sequence as `raw`
(when the fold changed anything). Upstream of the fold, raw labels are seen on purpose: the phone-mic level gate (it
treats pop and click the same), `VoiceJoystick.filter` and the calibration's `extractorEvent`.

One mouth click is never heard twice: click detections whose spans overlap, or lie within 30 ms of each other, merge into
one click (`ClickMerge`, per source string; the extractor's click and the tick detector's 40 ms `pop` are the logged
case). A dropped copy is logged `merged{source, label: "click", t_start_ms, t_end_ms, why: "the same click heard twice"}`.
The deliberate double (140-220 ms apart) is never merged. The merge runs before training, the media gate and the
sequencer. In cursor mode a further guard applies (see *When does the app act?*).

Old profile rules on `pop` are folded: `Personal.rewrite` folds an enrolled `gesture:pop` class (it matches a click as
`click`, trusted, never relabelled to `pop`), `Profile.parse` folds each `phrase` label (a rule on `["pop"]` becomes
`["click"]`, `["pop","pop"]` becomes `["click","click"]`), and `RuleDecider.decide` folds `s.sequence` first. Rule TEXT
the user typed is left as written.

The new `Vocab.DEFAULT_BINDINGS` (2026-09-28, hand-edited; `tools/gen_vocab.py` would revert it): `rise` swipe_up,
`fall` swipe_down, `arch` swipe_right, `dip` swipe_left, `click` tap, `hiss` back, `flat` long_press,
`click click click` listen_for_phrase, `click click` home, `hiss click` back. `pop` and `pop pop` are gone.

### When does the app act?

The app acts at once, **unless the active profile binds a longer sequence that starts with the sounds heard so far**.
Only then does it wait for the next sound.
- With the defaults (2026-09-28), `click` waits (for `click click` = home, `click hiss` = forward, `click click click` =
  listen), so a lone `click` taps only after `gap_ms + jitter_ms` (~0.75 s); `click click` waits one more gap (for
  `click click click`) and then goes home; `click click click` reaches the 3-sound maximum and resolves at once (listen).
- A longer sequence bound to the **same fixed action** as a shorter bound prefix is not waited for, because waiting
  would change nothing but the delay. So `hiss` (back) acts at once although `hiss click` is also bound to back. The
  rest of such a sequence is then **absorbed**: a click that follows the hiss within the gap (device gap when both
  sounds are stamped, else arrival time) is logged as `absorbed{sound, tail_of, gap_ms, clock}` and does nothing, so
  `hiss click` is one back and `hiss click click` is back followed by a lone `click` (which waits, then taps), not
  back + home. A click after the gap starts a new group as usual.
- In cursor mode nothing waits: a click taps at once, a short hiss is back, a long hiss (>= 700 ms, `CursorListen`) opens
  the listen window; multi-sound cursor rules still parse but never fire. A cursor-mode click that starts within
  `CursorClickGuard.CURSOR_CLICK_REFRACTORY_MS` (400 ms) of the previous tap's end is dropped — the user's quick doubles
  were retries after missed pops, not a second tap — logged `ignored{reason: "click refractory"}`. A hiss in between
  does not reset it.

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

## Hold messages (hold-to-scroll)

A sound is normally reported once, when it ends. For "swipe, then hold a hum to keep scrolling" the phone must know
that a tone is being held **now**, and when it stops. The device therefore sends two small messages on EVENT for a
held sound, besides the sound's normal feature message. The reference is `extractor/vox_extract/hold.py`
(`Extractor.push_stream`); the thresholds are the `hold_*` fields of the extractor `Config`.

```json
{"v": 1, "id": 1043, "hold": "start", "sound": 57, "t_start_ms": 81790, "t_ms": 82090, "f0_hz": 145.2, "flat": true}
{"v": 1, "id": 1044, "hold": "end",   "sound": 57, "t_start_ms": 81790, "t_ms": 83790}
```

| field | type | meaning |
|---|---|---|
| `v`, `id` | int | As in the feature message: every hold message carries a fresh `id`, and a repeated `id` is ignored. |
| `hold` | `start` \| `end` | Its presence makes this a hold message, not a feature message. It has no `sounds`, `sequence`, `armed` or `mode`. |
| `sound` | int | The sound's id: 1, 2, ... per device boot (it restarts at 1 after a reboot, as the device clock does). The hold messages of one sound and its feature message share it. |
| `t_start_ms` | int | The sound's start on the device clock: the same value as its feature message's `timing[0].t_start_ms`. |
| `t_ms` | int | `start`: how far the sound had got when it qualified (at least `t_start_ms + 300`). `end`: the sound's end, the same value as its `timing[0].t_end_ms`. |
| `f0_hz` | float, `start` only | Median pitch of the qualifying window. |
| `flat` | bool, `start` only | The window's pitch is within 1.5 semitones of the sound's start pitch. `false` = the sound moved and then settled (for example a rise that levels out without a break). When the hold qualifies at the earliest point, the window is the whole sound so far, and `flat` is always `true`. |
| `from`, `dir` | str, `start` only, optional | `"from": "glide"` with `"dir": "up"` \| `"down"`: a **glide-and-hold** (below). Absent on a steady-hum start. |

**The feature message of a numbered sound** carries the id and the hold flag in its `timing` entry:
`"timing": [{"t_start_ms": 81790, "t_end_ms": 83790, "sound": 57, "held": true}]`. `sound` is optional (older
firmware omits it); `held` is present (`true`) only when a `hold start` was sent for that sound.

**When the device sends them.**
- `hold start`: at most once per sound, while it is still going, at the first 10 ms frame where the sound has lasted
  `hold_start_ms` (300 ms) and its last 300 ms look like one steady voiced tone: at least 80 % voiced frames, median
  clarity at least 0.85, pitch drift under 1 semitone between the window's halves, a pitch wobble (median absolute
  deviation) under 0.5 semitone, and not machine-steady. Pops, clicks and hisses never qualify. A held hum therefore
  gets its `hold start` about 300 ms after it starts. A sound that settles later gets it later.
- **Glide-and-hold** (checked first, every frame): once the sound's last `hold_glide_ms` (250 ms) pass the same
  steadiness test, their median pitch is at least `hold_glide_min_st` (2 semitones) above or below the sound's
  start pitch, and it is within `hold_glide_peak_st` (1.5 semitones) of the highest (up) / lowest (down) pitch the
  sound has reached (so the held note is where the glide went, not the way back of an arch or dip), and that test
  has then kept passing on every frame for `hold_glide_delay_ms` (300 ms) more (the late start), `hold start` goes
  out, with `"from": "glide"`, `"dir": "up"` / `"down"` and `flat: false`. Only a sound that came after at least
  `hold_glide_quiet_ms` (700 ms) of quiet since the previous sound ended is tested (a stream's first sound counts
  as quiet): talk and music run sounds together, and a deliberate glide starts from silence. So a
  rise or fall whose end note is held for about half a second becomes a hold in the glide's direction, typically
  400–650 ms after the glide levels off. A glide released sooner gets no hold at all (`held: false`) and stays a plain `rise` /
  `fall`, which the phone swipes as a full step. There is no rule on how fast the glide itself is.
  `hold_glide_ms: 0` turns it off; `hold_glide_quiet_ms: 0` / `hold_glide_delay_ms: 0` drop the two guards.
- `hold end`: when that sound ends (100 ms of hangover after the voice stops), **immediately before** its feature
  message, which then carries `held: true`. A sound without a `hold start` gets no `hold end`.
- Order on the link: `hold start` (the sound is open), then `hold end`, then the feature message, all with increasing `id`.
  Other sounds cannot interleave: the device has one sound open at a time.

**What the phone does** (auto-scroll, see *Navigation actions*):
- **Gate.** A `hold start` acts only if the previous group was a single `rise` or `fall` that was executed as
  `swipe_up` / `swipe_down` (not `arch` / `dip`: sideways scrolling has no use in feeds), in the same app and mode,
  with nothing decided since, and the held sound follows it within 1 s on the device clock:
  `hold.t_start_ms − swipe.t_end_ms ≤ 1000` (`HoldScrollTrigger.WINDOW_MS`: the default `gap_ms` of 600 plus 400 ms
  of slack for the pause between the two). Without device stamps it is measured by arrival, allowing 2 s. Otherwise the hold messages are only logged, and the
  sound is handled normally when its feature message arrives. `flat: false` does not act.
  If the `hold start` arrives while the swipe's group is still waiting or being decided, the phone keeps it and
  applies the gate once the swipe executes (unless its `hold end` has arrived by then).
- **Glide-and-hold** (`from: glide`) needs no swipe before it: it scrolls the way a single `rise` (dir up) or `fall`
  (dir down) would go in this app and mode (the user's app rule, then global rule, then the default:
  `GlideHold.action`), if that is `swipe_up` / `swipe_down`. Otherwise (cursor mode, a rise bound to zoom, a rule only
  the model can apply) it does not act and its sound is decided as usual. It is also ignored while a sequence is
  waiting for its next sound (this sound may be that next sound), buffered while a decision is in flight, and
  ignored when disarmed, paused or in the phrase window. `HoldGate.route` is the one gate for both kinds of start.
  The older "swipe, then a separate held hum" method below is unchanged; both work with hums and whistles.
- **Scroll** in the swipe's direction from `hold start` until the `hold end` with the same `sound`.
- **The held sound's feature message** (`held: true`, same `sound`) after an acted-on hold is consumed: it is logged
  (its `resolve` carries `auto_scroll`) and not decided. A held sound whose hold did not act is decided as usual.
- **Stops**, besides the `hold end`: `armed: false` (including `sleeping: true`), a disconnect, a mode change, the
  existing safety stops (foreground app change, screen off, pause, `reset`, the service stopping), and a
  **watchdog**: stop if no `hold end` has arrived 5 s after the `hold start` (the device ends every sound within
  4 s, so a missing `hold end` means it was lost).
- **Without hold messages** (older firmware) there is no auto-scroll: the earlier timed rule ("a `flat` over 1 s
  after the swipe scrolls until the next sound") was dropped. A `flat` is then always `long_press`. The debug
  socket accepts hold messages like any other message.
- **Speed:** a continuous drag at `auto_scroll_pct` % of the screen height per second (default 10). The finger moves
  in 100 ms continued-stroke segments from 75% towards 25% of the screen, is lifted and put down again after half a
  screen, and at the end holds still for 150 ms before lifting, so there is no fling. Touching the screen cancels it
  (`why: drag cancelled (screen touched?)`).
- **Log:** `hold{kind, sound, ...}` for each message, `hold{event: buffered | scroll | no scroll, why}`,
  `auto_scroll{event: start | stop, action, app, hold, why, pct_per_s, ms}`, and the held sound's
  `resolve{auto_scroll: hold}`.

**The 4 s split.** The device force-closes a sound after 4 s (`max_segment_frames`, which bounds RAM; the feature
message says `truncated`). A hum held longer than that gets its `hold end` at `t_start_ms + 4000`, and scrolling
stops there. The rest of the hum usually does not become a new sound (the noise floor has risen towards it), and if it
does, it is a new sound without a preceding swipe, so the gate ignores it. **One hold scrolls for at most about 4 s;**
the user swipes and holds again to continue. Longer holds need a firmware change (keep the gate open past 4 s while a
hold is active, and flag the split). That is not part of v1.

**Sleep, disarm and disconnect in the middle of a hold.** When the device disarms or goes to sleep while a hold is
open, it SHOULD send `hold end` for it before the `armed: false` / `sleeping: true` message. The phone MUST NOT rely on
that: `armed: false`, `sleeping: true` and a disconnect each end any hold at once, and a `hold end` arriving later
for that sound is ignored. After a reconnect or wake, a `hold end` without a matching `hold start` is ignored. The
same holds for a device reboot (`sound` restarts at 1, and the device clock goes backwards).

**Older apps** reject a hold message as a malformed feature message (`ignored`). Nothing else changes for them: the
feature message only gains optional `timing` fields.

## Control messages (debug sources only)

`{"type": "control", "op": ...}` returns a JSON reply on the socket.

| op | args | reply / effect |
|---|---|---|
| `ping` | | `app`, `mode`, `armed`, `paused`, `waiting`, `settings` (API key redacted), `vocab` digest, `decisions`, `media_lock{on, mode, media_playing, media_speaker, route, locked, unlock_left_ms}` (the phone-mic media lock; `media_speaker`: media plays on the speaker the mic hears, `route`: `speaker`\|`bt-speaker`\|`bt-headphones`\|`headphones`\|`other`\|`unknown`) |
| `config` | any of `decider` (`rules`\|`model`\|`hybrid`\|`escalate`), `base_url`, `model`, `api_key`, `min_confidence`, `http_timeout_ms`, `gap_ms`, `jitter_ms`, `confirm_timeout_ms`, `outward_confirm_ms` (the outward-action confirm-pop window, 500-30000, default 3000), `listen_window_ms`, `asr_engine` (`android`\|`off`), `asr_allow_online` (bool, default false), `asr_language` (default `en-US`), `auto_scroll_pct` (2-60, default 10), `feed_fling_pct` (8-60, default 15) and `feed_fling_ms` (30-150, default 50: the fling on a paged feed, `ScrollStep.kt`), `target_min_confidence`, `target_model`, `target_choose_ms`, `timer_app` (a clock app package for spoken timers; empty = automatic), `app_prefer` (`from=to,...` packages: a spoken name that resolves to `from` opens `to` when it is installed; default `com.google.android.youtube=app.rvx.android.youtube`), `enroll_reject_mult`, `enroll_gesture_relabel` (bool, default true: a trained gesture relabels a sound, *Personalization*), `ble_device` (a Bluetooth address, or `null`), `ollama_endpoint`, `ollama_model`, `ollama_timeout_ms`, `ollama_target_timeout_ms`, `log_typed_text` (bool, default false: the words typed by voice appear in `exec`/`dictate` events), `dictate_speech_hold_ms` (200-3000, default 1000: during dictation a device sound this soon after the last words is speech), `media_lock` (bool, default true: while media plays, phone/USB mic sounds are dropped except a `pop pop` unlock), `media_unlock_mode` (`one`\|`fixed`\|`popext`, default `one`: how an unlock ends), `media_unlock_ms` (1000-30000, default 5000: the unlock's time limit), `cursor_speed` and `cursor_pitch_sens` (the voice joystick's sliders, 0.5-2.0, default 0.9, rounded to 0.01), `sound_source` (`pico`\|`phone`\|`usb`), `mic_rate`, `mic_preset`, `mic_read_ms`, `mic_while_disarmed`, `mic_effects`, `mic_touch_guard`, `mic_media_gate`, `hiss_media_max_centroid_hz` (0-8000, default 6500, 0 = off: the media-hiss rule under "Phone microphone" Guards), `level_gate` (bool, default true) and `level_gate_offset_db` (-10..10, default 0: the calibration-v2 level gate under "Phone microphone" Guards), `mic_dry_run` | Applies the settings and rebuilds the decider. `ollama_key` is refused: the cloud key is entered in the settings screen only, and `ping` shows it only as `"set"` or `""`. |
| `profile` | `profile`: profile JSON, or `null` for the bundled default | Replaces the profile (format in `Profile.kt`). Its optional `name` (default `default`) selects the enrollment store. |
| `enroll_add` | `kind` (`custom`\|`ignore`\|`gesture`), `name`, `examples`: list of `{fp, fp_version, pitch16}` (each may carry a `meta` object, at most 2048 characters of JSON, stored with it), optional `source` | Adds examples to a class of the active profile, creating it if needed. `source` (`pico`\|`phone`\|`usb`, default the current sound source) picks the store (*Gesture training*: one store per mic source). All-or-nothing: rejected if any example has another `fp_version` or length than the store, if the class would exceed 10 examples, or if a `gesture` class is not named after a gesture (contour gestures need a 16-point `pitch16`). Reply: `enrollment` (as `enroll_list`). |
| `enroll_list` | optional `source` | `enrollment`: `profile`, `source`, `file` (the store file name), `fp_version`, `dim`, `reject_mult`, `floors` (see `fp_floors`), and per class `kind`, `name`, `examples`, `active` (3+ examples), `contour`, `threshold`, `dtw_threshold`. |
| `fp_floors` | none; or `table`: `{"<fp_version>": {"floor": [...], "provisional": bool, "source": "..."}}`; or `reset: true` | The per-feature std floors (Personalization, below). `table` stores an on-device override (`files/fp_floors.json`) whose entries replace the bundled ones per version; `reset` removes it. Reply: `table` (in use), `override` (bool), `status`. |
| `enroll_delete` | `name` and optional `index`, or `all: true`; optional `source` | Deletes a class, one of its examples, or every class of the active profile. |
| `screen` | | `line` (the `screen:` line) and `summary` (the raw tree summary) |
| `asr` | `check` (bool, optional) | The phrase recognizer: `engine`, `status` (`ready`, `off`, or what the user must fix), `window_open`, and for `android` `asr{recognizer (on_device\|default_offline\|default_online\|none), status, language, pack, allow_online, on_device_available, any_available}`. `check: true` asks the recognizer again whether the offline pack is installed (API 33+; the answer is an `asr{event: check}` event). |
| `listen` | | Opens the phrase window, as `listen_for_phrase` does. |
| `phrase` | `text`: string and/or `nbest`: list of strings; `window` (bool, default true: as if a pop pop opened the listen window; false: as a phrase from outside a window, where a lone `up`/`down` does nothing) | A transcript as if the recognizer heard it, without a microphone: closes an open window and runs the full path (grammar → decider → executor). Reply `result{heard, hypothesis, command, parses, apps_ms, parse_ms, decision{n, action, source, path}, exec{action, ok, how, prep_ms}, target{query, targets, result}, result: ignored, pending, total_ms, armed, mode}` (keys present when that step ran; `pending`: the decision runs on the worker, the model decider, and its `decision`/`exec` events follow in the log). Debug builds only, like every op. |
| `asr_audio` / `asr_audio_result` | `wav_b64` (16 kHz mono PCM16 WAV, <= 30 s); options `segmented` (EXTRA_SEGMENTED_SESSION), `feed_at` (`ready`\|`start`), `realtime` (bool), `lead_ms` / `tail_ms` (0-5000 of silence), `chunk_ms` (10-200); then `id` | A recorded clip through the on-device recognizer with EXTRA_AUDIO_SOURCE (a pipe of raw PCM, never the mic, never online; `AudioFileAsr.kt`). The result: `why`, `error_code`, `hypotheses`, `confidences`, `pick`, `audio_ms` (sent), `clip_ms`, `fed_ms`, `ready_ms`, `fed_all_ms`, `mic_watch`, `mic_opened`, `heard{rms_db_min, rms_db_max, rms_n, begin_ms, end_ms, buffers, events, segments, segmented_end}` (what the recognizer did with the audio), `sent{peak_dbfs, rms_dbfs, lead_silence_ms, clipped, samples, options}`, `service{on_device_default, user_default, installed}`. The log gets counts only. |
| `heard` | `hypotheses`: list of strings (n-best) | The older form of `phrase` (same path). |
| `dump` | `raw` (bool, optional) | The visible nodes of the app window: `id cls text desc click scroll bounds`. With `raw: true`, every node as the framework reports it, in pre-order with no filter or pruning (`raw: [{d, cls, id, text, desc, vis, imp, click, kids, bounds}]`, at most 800), for diagnosing odd trees |
| `main_load` | `reset` (bool, optional) | Where the main thread spends its time (`MainLoad.kt`): `sections{what: {count, total_ms, mean_ms, max_ms, over_16, over_50, over_100}}`, busiest first. Sections: `a11y_event` (each accessibility event), `msg:features` (a feature message end to end, its tree reads included), `tree:current_app` (normally no tree read: the active window's package is learned once per window, `ForegroundApp.kt`), `tree:summarize`, `tree:fingerprint` (the Confirmer's tree walks), `tree:refresh` (the stale-root re-read, at most once a second per window), and `main:lag` (how late a 50 ms tick ran while armed: time the main thread was busy). A section timed off the main thread (the background feed-kind read's `tree:refresh`) is listed as `what@bg` and never logs `main_slow`. Any one main-thread section over 100 ms also logs `main_slow{what, ms, app}` at once. `reset: true` starts over after replying. |
| `harvest` | `tag` | Appends `{tag, package, screen_text, summary}` to `files/harvest.jsonl`. |
| `pause` | `paused` (bool, default `true`) | Pauses or resumes VOX from the phone, like the status screen's button (logged `pause{by: "op"}`). While paused, messages still update `armed` and `mode`, but their sounds and phrases are ignored (`ignored{reason: "paused (app)"}`). Reply: `paused`. |
| `reset` | `clear_log`, `clear_harvest` (bool) | Drops pending state, re-arms, resumes, forgets the device-clock estimate, cancels a target choice, and optionally clears the files. |
| `targets` | | Intent cursor mode's view of the screen: `package`, `screen_text`, `options` (exactly what the `target` question would send, NONE last) and `targets[{option, bounds}]`. |
| `ble_scan` | `ms` (default 10000, 1000–60000) | Scans for devices advertising the VOX service; each new one is logged (`ble{what: found}`) and listed in `ble_status`. |
| `ble_connect` | `address` (`AA:BB:CC:DD:EE:FF`, or `auto`, the default) | Connects and keeps reconnecting (it also ends a `needs_pairing` stop). `auto` = the remembered device, else the strongest one found, else scan and take the first. The device is remembered (`ble_device`) once the link is ready. |
| `ble_status` | | `ble`: `state` (`off`, `idle`, `scanning`, `connecting`, `discovering`, `bonding`, `subscribing`, `ready`, `waiting`, `needs_pairing`), `why`, `adapter`, `permissions`, `remembered`, `target`, `mtu`, `bonded`, `info` (the device's INFO), `ready_ms`, `reconnect_in_ms`, `failures`, `auth_failures`, `hint` (what the user must do, or null), `messages`, `fragments`, `gaps`, `bad`, `found`, and `device`: `presence` (`listening`, `awake – paused`, `asleep`, `pairing needed`, `connecting`, `not connected`, `bluetooth off`, or null when no device is set up), `ready`, `asleep`, `armed`, `mode` (the device's last word), `waiting_for` (the command awaiting confirmation), `error` (the last failed command), `pause_cause` (`link-drop`, `user`, or null: why the device is disarmed, see *Disconnect*) and `wakeable` (connected and paused only by a link drop: the badge shows `tap-to-wake`). |
| `ble_disconnect` | | Drops the link and stops reconnecting until the next `ble_connect` (the device stays remembered). |
| `device` | `armed` (bool) and/or `mode` (`gesture`\|`cursor`), or `sleep: true` alone | An app command to the device (*App commands (CONFIG)* above), written only on a ready link. Replies at once: `device_cmd{result: sent}`, or an error (no device connected, the device is asleep, busy with a previous command, invalid). The outcome follows as a `device_cmd` event: `confirmed` when the device's next no-sound state message arrives (for `sleep`, its `sleeping: true` message), `failed` when the device's reply carries `rejected` (at once, with its reason), the write fails, the link drops, or nothing arrives within 1500 ms (a write the stack blocked). The status screen shows the failure. |
| `ble_forget` | | Disconnects and forgets the remembered device. The Android bond is kept (remove it in Bluetooth settings). |
| `ble_config` | `config`: a JSON object | Writes it to the device's CONFIG characteristic (reserved; e.g. `{"v":1,"test_sounds":true}`). Needs a ready link. |
| `mic_status` | | `mic`: the phone-mic source (PROTOCOL "Phone microphone"): `source`, `state`, `plan{service, capture, route}`, `service_running`, `service_refused`, `capturing`, `routed` (the input in use), `capture` (route, preset, effects, buffers), `permission`, `native` (the extractor version, or why it did not load), `unprocessed_supported`, `inputs`, `sounds`, `latency_ms{n, p50, max}` (end of sound → delivered), `stats` (once a second: the native `hop_us{p50,p90,p99,mean,max,over_4ms}`, `push_us`, `floor_db`, `gate_open`, `level{rms_dbfs, peak_dbfs, ms, band_hz, bands_dbfs}`, `thread_cpu_pct`, `silent_input`, `env`), `bands{band_hz, dbfs, ms}` while capturing (see below), `touch_guard{on, error, user_touches, injected_touches, sounds_dropped}`, `media_gate{mode, media_playing, media_speaker, gated, hiss_gated, hiss_media_max_centroid_hz}`, `level_gate{on, offset_db, gate, dropped, relabel_rule, relabelled}` (`gate`: the live `{min_snr_db, min_level_dbfs, from, n, weakest_snr_db?, weakest_level_dbfs?}` or null), and the `mic_*` settings and `hiss_media_max_centroid_hz`. **Band levels** (diagnostic, 2026-09-27): `bands.dbfs` is 8 numbers, the input level in dBFS (mean square, the same scale as `rms_dbfs`) in 8 equal bands from 0 to 8 kHz (`band_hz` 1000: 0-1, 1-2, ... 7-8 kHz), over the last once-a-second snapshot (`ms`). They are summed from the extractor's own per-hop spectrum (512-point Hann FFT at 16 kHz, after its 60 Hz high-pass; no extra FFT, no audio kept). At `mic_rate` 48000 they are after the 48→16 kHz decimator, whose filter takes about 4 dB off 7 kHz and 10 dB off 7.5 kHz. -200 = digital silence; absent when the mic is not capturing. For telling an acoustic 6-8 kHz media band (scales with volume, gone when muted) from a device artefact. |
| `badge_hide` | `hide` (bool, default true), `ms` (500-60000, default 10000) | Hides Canti's head and its menu for a screen capture (`harvest_v3.py` wraps its `screencap` in it); `hide: false` shows it again, and it comes back by itself after `ms`. Reply `hidden`. A tucked head stays hidden. |
| `joy_state` | | `joystick`: the voice joystick (*Voice joystick* below): `on`, `source`, `calibrated`, `mode`, `x_dp`, `y_dp`, `snapped`, `phase`, `mid_st`, `range_st`, `speed_mul`, `pitch_sens`, `elements` (magnet candidates), `ticks`, `pops` (tick-detector pops delivered), `merged`, `calibrating`; null if it did not start. |
| `joy_recentre` | | Moves the joystick cursor to the screen centre (logged `joystick{event: recentre, by: ctl}`). Reply as `joy_state`. |
| `calib_start` / `calib_step` / `calib_redo` / `calib_retry` / `calib_skip` / `calib_save` / `calib_cancel` / `calib_status` / `calib_get` | as the UI methods (`source`, `step`, `steps`, `resume`) | The joystick calibration, exactly as the UI channel's methods (*Voice joystick*, Calibration). Reply `calib`: the calib_status map (`calib_get`: the saved profile, or null); a command error also sets `ok: false, error`. |
| `train_status` / `train_start` / `train_record` / `train_retry` / `train_skip` / `train_keep` / `train_next` / `train_goto` / `train_confirm` / `train_cancel` / `train_delete` | as the UI methods (`gesture`, `cell`, `source`, `record`, `id`, `keep`) | Gesture training, exactly as the `ai.vox/train` channel (*Gesture training*). Reply `train`: the train_status map; a refused command also sets `ok: false, error`. |
| `mic_level` | | `mic`: `state`, `routed`, `level{rms_dbfs, peak_dbfs, ms, band_hz, bands_dbfs}` of the last second, `floor_db`, `gate_open`, `silent_input`. For checking a mic (e.g. a USB mic) without making sounds count. |
| `mic_feed` | `pcm_b64` (PCM16 LE mono), `rate` (16000\|48000), `chunk_ms` (20), `repeat` (1-1000), `raw` (bool), `deliver` (bool) | Runs the PCM through a fresh JNI extractor, the live path's code (direct buffer, `chunk_ms` pushes), independent of the mic. `mic`: `events` (with `raw`: the full event JSON as in `extractor/vectors`), `stats` (as above, over all repeats), `wall_ms`, `audio_ms`, `native`. `deliver` also hands the sounds to the service as source `phone-mic-feed`. `tools/mic_parity.py` uses it for device parity and speed. |
| `measure_start` | `phase` (string, e.g. `1-media-30`), `every_ms` (2000-30000, default 5000), `gestures` (list of strings, default `["rise","fall","click","click click","hiss"]`), `prompt` (bool, default true), `record` (bool, default true), `stereo` (bool, default false), `max_s` (30-1200, default 300) | Starts the near-field measurement (below). Refused (`ok:false, error`) unless the sound source is `phone`/`usb` and the capture is listening, or if one session already runs. Reply: `sid` (the wall-clock ms at the start, unique across service restarts; an existing `measure/<sid>/` is never reused), `file` (`measure/<sid>/audio.wav`), `rate`, `channels` (1 or 2; the requested count, the `measure_start` event has the actual one). |
| `measure_stop` | | Ends the running session (as if `max_s` or a capture stop). Reply: `sid`, `samples` (frames), `seconds`. |
| `measure_status` | | `running`, `sid`, `phase`, `seconds`, `prompts`, `file` (or `running:false`). |
| `measure_clear` | | Deletes `files/measure/` entirely (nothing else). Refused while a session runs. Reply: `deleted` (the file count). |
| `measure_cue` | `text` (string, 1-120 chars), `id` (string) | The range suite's PC-driven prompt (round7-plan §3d): shows `text` now on the measurement prompt overlay and logs `measure_prompt` with `gesture` = `id` and `text`, exactly like a scheduled prompt (also with `prompt:false`). Refused (`ok:false, error`) when no session runs, before the session's first sample (retry), or on a blank/too long `text` or blank `id`. Reply: `n` (the session's prompt sequence number, shared with the scheduled prompts), `t_ms` (stream ms when shown, on the recording capture's clock, as the event). |

## Near-field measurement (round7-plan §3c)

A debug harness that records the phone/USB mic while the gestures keep working, so the media gate's near-field rule can
be measured. One session at a time; it stops by itself at `max_s`, on capture stop/restart (or a failed WAV write), and on service stop. A stereo session restarts the capture into stereo and back; that restart does not end it (capture generations tell the old capture's late states apart).

- **Clock** ("stream ms"): ms since the first sample of the current capture stream, i.e. `pushed * 1000 / rate`. All the
  times below are in stream ms. A measurement that restarts the capture (for stereo) restarts the clock, so `wav_t0_ms`
  is taken after the restart.
- **File**: `files/measure/<sid>/audio.wav`, PCM16 LE, mono or interleaved stereo, at the capture rate, written only while
  the session runs, never uploaded, deleted by `measure_clear`. `record:false` opens no file.
- **Stereo**: `stereo:true` opens `CHANNEL_IN_STEREO` for the session; the extractor still gets channel 0 (de-interleaved)
  so gestures work, and the WAV keeps both channels. A device that refuses stereo falls back to mono (`stereo_ok:false`).
- **Prompt**: with `prompt:true`, a large on-screen gesture name + counter near the top, visible ~1.5 s, no sound or
  vibration, every `every_ms`, round-robin over `gestures`, starting at the session's first sample (so every `t_ms` is on
  the recording capture's clock, also after a stereo restart).

**Events** (EventLog):
- `measure_start{sid, phase, rate, channels, file, wav_t0_ms, every_ms, gestures, stereo_ok}` — `wav_t0_ms` = stream ms of
  the WAV's first sample (null when not recording); `stereo_ok:false` = stereo was asked for but the device refused.
- `measure_prompt{sid, n, gesture, text, t_ms}` — `t_ms` = stream ms when the prompt became visible; `text` = what it showed.
  `n` counts every prompt of the session, scheduled or `measure_cue` (whose `gesture` is the cue's `id`).
- `measure_stop{sid, reason, samples}` — `reason` is `op` \| `max_s` \| `capture` \| `service`; `error` names a failed WAV write (reason `capture`), else null. `measure_start` is logged at the session's first sample (or at its stop if none came), so it always precedes the prompts and the stop.
- `mic_sound` gains `sid` and `tmpl` while a session runs: `tmpl` is `{nearest, distance, threshold, kind}` from the
  gesture-training/enrollment matcher (`kind` "none" for a non-match, which keeps its nearest class and distance), or
  `null` when nothing is enrolled or the fingerprint is incompatible. Computed for
  every `mic_sound` of the recording capture, including level-gated, media-gated and dropped ones (not `mic_feed`).

## Phone microphone (sound source `phone` / `usb`)

The app can hear sounds without the Pico: the phone's built-in mic, or a USB mic plugged into the phone, runs
through **the Pico's own extractor** (`firmware/extract/src`, compiled into `libvx_jni.so` with the NDK; not a port)
on the phone. The setting `sound_source` picks one: `pico` (Bluetooth, the default), `phone` or `usb`. Only one
source runs: `pico` = BLE only; `phone`/`usb` = no BLE.

- **Same messages.** Each extracted sound becomes the feature message the Pico would send for it (`send_sound` in
  `vox_state.cpp`): `{"v":1,"id","mode","armed":true,"sounds":[line],"sequence":[label],"timing":[{t_start_ms,
  t_end_ms,sound}],"phrase":null,"cursor":null,"features":[{fp,fp_version:"fp1",pitch16}]}`, delivered as source
  `phone-mic`. Times are on the phone's `elapsedRealtime` clock (the sequencer's arrival clock), so device-clock
  grouping applies as with the Pico. `mode` is the service's current mode; ids start at `elapsedRealtime` at source
  start. Hold messages (above) are mapped the same way once the extractor emits them.
- **Capture.** `AudioRecord`, 16-bit mono at `mic_rate` (16000 direct, or 48000 through the extractor's
  `Decimator3`), preset `mic_preset` (`auto` = `UNPROCESSED` when the phone supports it, else `VOICE_RECOGNITION`),
  AGC/NS/AEC switched off where attached (`mic_effects` changes that), `mic_read_ms` blocking reads (default 20 ms) into one direct buffer on a
  dedicated `THREAD_PRIORITY_AUDIO` thread: no allocation per read, and the native side reads the buffer in place.
  `usb` routes to the first USB input (`TYPE_USB_DEVICE`/`TYPE_USB_HEADSET`) and waits when none is plugged; it never
  falls back to the phone mic. `phone` prefers the built-in mic explicitly (a plugged USB headset does not take over).
- **When it listens.** Only while the source is `phone`/`usb`, the service is not paused, and it is armed (or
  `mic_while_disarmed`). Pausing (app, notification, `pause` op) closes the mic; resuming re-arms and reopens it.
  With a mic source the phone owns mode and arm state: `device {mode, armed}` and the UI's mode button apply them
  locally.
- **Android.** `RECORD_AUDIO` (asked with its reason when a mic source is picked) and a foreground service of type
  `microphone` (`MicListenService`) kept up while a mic source is selected. Android 14 lets it start only while a
  Canti screen is visible; otherwise the mic state says `open Canti to start the mic` and it starts on the next
  resume.
- **Notification.** Canti's status notification (all sources): e.g. `Canti · Pico listening` or
  `Canti is listening · Phone mic`, body `Gesture mode · <input>`, buttons **Cursor mode/Gesture mode**,
  **Pause/Resume**, **Source** (a small chooser). It is the mic service's notification when that runs, else a plain
  ongoing one; only a phone/USB source holds the microphone.
- **Guards.** A sound that overlaps a user's touch on the screen is dropped (`mic_touch_guard`: a tap on the glass
  is a pop to the phone's mic). While media plays on the phone's speaker, a pop/click under 14 dB over the floor, or
  a hum under 14 dB or with clarity under 0.8, is passed on with `sequence: ["unknown"]` (not deliberate; it still
  breaks up its group) (`mic_media_gate`, `PhoneGate.kt`). The message says so: `gated: ["media"]` (the media hiss: `["media_hiss"]`), and
  personalization leaves a gated sound as it is. Each sound is judged 150 ms after its end, so a touch-down
  that follows it can still count.
- **Level gate** (calibration v2, `level_gate` default on, `level_gate_offset_db` -10..10 default 0, + = stricter;
  `CalibV2.phoneVerdict`). A `phone`/`usb` `pop`, `click`, `hiss` or `unknown` must reach **both**
  `gate.snr_db >= min_snr_db` and `gate.level_db >= min_level_dbfs` (each plus the offset), else it is dropped:
  `ignored{reason: "below level gate", label, snr_db, level_dbfs, min_snr_db, min_level_dbfs, from, offset_db, source,
  sound, t_start_ms}` and `mic_sound{dropped: "below level gate"}`. One pair per mic source, from its calibration
  profile: the weakest calibrated pop / click / hiss minus 8 dB (SNR) and 8 dB (level), raised to the room step's
  loudest transient + 3 dB, never above the weakest - 1 dB (`from: "calibration"`). Uncalibrated, or the clicks step
  never measured: 12 dB and -45 dBFS (`from: "default"`). Hums are never level-gated. It runs in `PhoneMicSource`
  before the joystick's filter and before the service, so a gated sound never reaches personalization
  (`Personal.rewrite`'s trained-gesture relabel). No gate while a calibration runs, nor for Pico sounds, tick-detector
  pops or touch-dropped sounds. A sound without gate numbers passes. Then the **click / pop relabel**: with a
  per-person rule (the pops and clicks steps' examples separate on at least 2 of `dur_ms`, `snr_db`, `level_db`,
  `lf_ratio`), a `pop` / `click` whose separating features all say the other label is relabelled:
  `relabel{by: "click_pop_rule", from, to, votes, source, sound, t_start_ms}`, `mic_sound{relabel: "pop->click"}`.
- **Media hiss** (`hiss_media_max_centroid_hz`, default 6500, 0 = off; `PhoneGate.hissReason`, 2026-09-27). While
  media plays on the phone's own speaker (the `speaker` test above; earbuds/Bluetooth: no rule), a `phone`/`usb` hiss
  whose spectral centroid (`gate.centroid_hz`, energy-weighted over the sound) is over the threshold is passed on as
  `unknown`, `mic_sound.gated: "hiss centroid <n> Hz over <max> Hz while media plays on the speaker"`, message `gated: ["media_hiss"]`. It does not
  depend on `mic_media_gate`. Pico sounds never. Why: on the Z Flip a YouTube Short made lone 6.6-7.3 kHz "mouth sound"
  hisses, each a `back` (38-42 a minute in `auto`); the rule cuts that to 0-7 and kept 100 % of the user's Q9 mouth
  hisses and 98 % of the phone's quiet-room ones (wiki/phone-mic-echo.md).
- **Media lock** (`media_lock`, `MediaGate.kt`, user decision 2026-09-27; Z Flip round 4 heard 36-100 sounds a minute
  from a YouTube Short alone, 30-47 of them would have acted, on every mic preset and echo-cancel setting). While media
  plays on a speaker the phone mic hears (`AudioManager.isMusicActive` and the media output route is a speaker;
  `SpeakerRoute.kt`, the same "speaker" test as `mic_media_gate`'s `speaker` mode) a `phone`/`usb` sound is dropped
  before the sequencer,
  in gesture and cursor mode alike: `media_gate{kind, source, dropped: true, unlock?}` (`kind`: the label, or `hold` for
  a `hold start`; a `hold end` always passes). Media on earbuds / headphones / a hearing aid — wired, Bluetooth LE or
  USB (`TYPE_WIRED_HEADSET`, `TYPE_WIRED_HEADPHONES`, `TYPE_BLE_HEADSET`, `TYPE_USB_HEADSET`, `TYPE_HEARING_AID`) — does
  **not** lock: the phone mic cannot hear it, so sounds pass. A speaker is: the phone's `TYPE_BUILTIN_SPEAKER`, a
  Bluetooth LE `TYPE_BLE_SPEAKER`, or a classic-Bluetooth `TYPE_BLUETOOTH_A2DP` endpoint whose **device class** says it
  is a speaker — read via `BluetoothAdapter.getRemoteDevice(address).bluetoothClass` (BLUETOOTH_CONNECT): a
  loudspeaker / hifi / portable / car / set-top-box / display-and-loudspeaker class is a speaker (lock); a headphones /
  wearable-headset / handsfree class is in or on the ear (no lock). An unknown, uncategorised or missing class (no
  permission, no adapter, an error), and an unknown route (pre-Android-13 or an error), are assumed audible — fail
  safe, the mic may hear it. The exception is the unlock, `click click click` (three `click`s, each starting within
  `gap_ms` of the previous one's end, nothing between; the media alone made 0 triples in round 4 after the level gate
  and `PhoneGate`): all three clicks are dropped too (`unlock: "1/3"`, `"2/3"`, `"3/3"`) and do nothing else (no phrase
  window: its recognizer would hear the video). Then sounds pass
  to the usual rules (the click allow-list below included) until the unlock ends, by `media_unlock_mode` (pending the
  user's choice; no mode extends on other gestures, since media sounds would keep the window open):
  - `one` (default): exactly the next gesture (the next resolved sequence, whatever it decides) passes, then it
    re-locks: `media_unlock{event: used, sequence}`. `media_unlock_ms` is the time allowed to make it. A
    `click click click` as that gesture is listen-for-phrase.
  - `fixed`: a `media_unlock_ms` window that never extends.
  - `popext`: a `media_unlock_ms` window that only another `click click click` extends (`media_unlock{event: extend}`);
    that triple is taken by the lock and does not listen, so listen-for-phrase is not reachable by gesture while media
    plays.
  The badge shows the pending face while an unlock is open. Media stopping, or leaving the speaker (earbuds plugged
  in), lifts the lock at once; a route back to the speaker (earbuds removed) re-locks. Events
  `media_unlock{event: open|used|extend|expired|lifted, window_ms?, unlock_mode?, sequence?, mode?, app?}`. Pico sounds
  are never gated. (The event name `media_gate` and `mic_status.media_gate` belong to different gates: the event is this
  lock, the `mic_status` block is `mic_media_gate`.)
- **No taps from room clicks** (`MicPopGate.kt`, user decisions 2026-09-27/28, after a mouth-sound click became a real
  tap in YouTube). With a `phone`/`usb` source:
  - a lone `click` has **no default action** in gesture mode, in any app: `unbound{n, sequence, app, source: phone}` and
    `decision{action: none, source: "app:unbound (phone mic click)"}`. It taps only where the user binds it (a global or
    per-app profile rule for `click`: the rule is the allow-list).
  - a sequence with a click that the user did not bind is never a `tap` or `double_tap` in gesture mode, whatever
    decided it (a model included): `gated{n, action, sequence, app, why: phone_mic}`, nothing happens.
  - in a social, video or messaging app (`MicPopGate.APPS`: YouTube and its mods, TikTok, Instagram, Threads, Facebook,
    Messenger, X, Reddit, Snapchat, Pinterest, LinkedIn, Tumblr, Bluesky, Twitch, Discord, WhatsApp, Telegram), a
    sequence with a click never does an outward action, even a user-bound one, and a click never confirms an outward
    action: `gated{n, action, sequence, app, why: phone_mic, confirm?}`.
  - cursor mode keeps click = click from every source (the user turns it on with the button).
  Home, back, scrolling, `click click click` = listen and everything from the Pico (click = tap) are unchanged; a listen
  window opened from the mic is logged `mic_listen{n, app, sequence, source}`.
- **Privacy.** Samples go from `AudioRecord` into the extractor and nowhere else: nothing is stored, logged or sent.
  Only the extractor's output (the sound lines and fp1 numbers the Pico would send) leaves the audio thread.

Events: `mic{state, why, source}` (`off`, `paused`, `listening`, `starting`, `waiting for a USB mic`,
`needs microphone permission`, `open Canti to start the mic`, `mic error: ...`, `unavailable: ...`, `paused for speech` (the phrase window: the capture stops, the
foreground service stays)),
`mic_capture{state, info}` (the route, preset, effects, buffer sizes; once a second a stats snapshot is kept for
`mic_status`), `mic_service{state: foreground|refused}`, `mic_sound{label, text, t_start_ms, t_end_ms, detect_ms, latency_ms,
gate{like, why, cues, dur_ms, floor_db, level_db, snr_db, voiced_frac, strong_voiced_frac, clarity_med, f0_med_hz,
onset_flux_db, energy_iqr_db, centroid_hz, peak_centroid_hz, centroid_spread_oct, zcr, lf_ratio, hf_ratio, pitch_jumps_hz,
voiced_runs, syllable_peaks, ...}, pitch16 (16 floats or `[]`), f0_hz (Hz or null) (both: *Test recorder (dev)*),
dropped (touch|below level gate|joystick ...|calibrating|recording|dry_run|null), touch_ms, relabel (e.g. `pop->click`, or null), media, media_speaker, gated}` per phone-mic sound (the extractor's own gate
numbers, never audio; the spectral ones are over 90-7600 Hz of the 16 kHz stream: `centroid_hz` energy-weighted over
the sound's frames (the media-hiss rule reads it), `peak_centroid_hz` at its loudest frame, `zcr` zero crossings per
sample, `lf_ratio` / `hf_ratio` the energy share below 1 kHz / above 3.5 kHz; all exactly the raw event's values), `mic_touch{injected, device, source, flags}` (the first 3 touches), `mic_touch_watch{state}`,
`sound_source{source, by}`.

## Voice joystick (cursor mode, phone / USB mic)

User decisions 2026-09-27; design in `wiki/voice-cursor.md` "Joystick cursor"; code `VoiceJoystick.kt` and
`joystick/` (a port of `extractor/joystick_core.py`, checked tick for tick by `JoystickParityTest`). In cursor mode
with `sound_source` `phone` or `usb`, the cursor is a relative 360° joystick. With the Pico the discrete cursor stays.

- **Ticks.** The native extractor also runs the joystick's per-20 ms analysis on the same samples (`vx_tick.cpp`,
  `VxNative.enableTicks` / `takeTicks`), only while the joystick is on or a calibration runs. Each row has
  `TICK_COLS` = 10 doubles: `t_ms` (the stream clock, the same as the sounds' `t_start_ms`), `f0`, `f0_raw`,
  `clarity`, `db`, `floor`, `f1`, `f2` (NaN = none), `voiced`, `why` (0 none, 1 quiet, 2 unclear, 3 no pitch). With
  ticks off, the extractor path is byte-identical to before. The cost is about 27 µs per tick on the host.
- **Moving.**
  - Pitch against the home note moves it up or down, and the vowel moves it sideways (ee right, oo left, ah none).
  - It moves only while a hum lasts and stops where the hum ends.
  - The position (dp) is kept in prefs `canti_joystick` and never resets. Only `joy_recentre` or the badge menu's
    RECENTRE moves it, or a rotation's clamp into the new screen.
  - The magnet snaps a stopped cursor to a clickable element (`Targets`) within 48 dp. It jumps to the centre only for
    small elements; corner brackets mark the snapped element.
  - The sliders `cursor_speed` and `cursor_pitch_sens` scale the speed and the pitch sensitivity.
- **Sounds while it drives.**
  - Only `pop`, `click` and `hiss` go on to the sequencer (the RAW extractor labels at this point; `SoundFold` folds pop
    to click downstream). Other extractor sounds (the hums the joystick is using) are dropped:
    `mic_sound{dropped: "joystick (a hum moves the cursor)"}`.
  - The ticks have a second pop detector. Its pops arrive as sound `pop` with `text: "pop (tick detector)"` and
    `tick: true`.
  - When both detectors hear one click (within `merge_ms` + 100 ms), it counts once: `VoiceJoystick.filter` merges on
    both `pop` and `click` labels (2026-09-28). The later copy is dropped as `joystick (the tick detector heard this
    click)`, or not delivered at all if it is the tick detector's.
  - A click taps at the cursor. The Outward / social / MediaGate / PhoneGate rules are unchanged.
  - A click on an outward button under the cursor ("Like", "Follow", "Send") waits for a confirm pop, like a named
    target: `confirm_ask{source: joystick, why: "outward button"}`.
- **Log.**
  - `joystick{state: on|off, source, calibrated}`
  - `joystick{profile, calibrated, skipped}`
  - `joystick{event: stop, x_dp, y_dp, stop_dp, ms, why, snapped, reanchors}`
  - `joystick{event: pop, detector: tick, t_ms}`
  - `joystick{event: recentre|screen, ...}`
- **Indicators.** Cursor B is a pixel ring with 1–3 chevrons in its heading (`assets/joystick_cursor.json`).
  Face A is the badge's `joy_*` still frames: a pitch bar with 4 steps, and a pointer for the vowel.

### Calibration

The setup screen (`ui/lib/src/calibration.dart`, route `calibrate`) records seven steps, in this order (calibration
v2, 2026-09-27; design in `wiki/voice-cursor.md` "Calibration v2"; a pop counts as a click, 2026-09-28, so the pops
step is gone):

| Step | The user | Measures | Fails with (`reason`) |
| --- | --- | --- | --- |
| `hum` | hums 'mm' relaxed, 3 s | the home note, the voicing threshold | `no steady hum heard in <n> s`; `too short or too rough (<n> steady ticks, need 40): a relaxed 'mm', 3 s` |
| `glide` | glides lowest -> highest -> back, 5 s | the voice range | `no steady voice heard in <n> s`; `too small or too short (<x> st, <n> steady ticks; need 4 st, 50 ticks): ...` |
| `vowels` | holds ee, ah, oo, 2 s each | the vowel centroids | `no clear '<v>' heard in <n> s`; `only <n> clear frames of '<v>' in <n> s (need 30): hold it steady for 2 s` |
| `clicks` | 3 tongue clicks, a second apart (8 s) | the clicks' gate numbers (any extractor pop / click / hiss up to 250 ms; the 3 strongest) — this step sets the level gate | `heard <n>/3 clicks, need 2 (click your tongue a bit louder, about a second apart)` |
| `whistle` | a whistle glide lowest -> highest -> back, 5 s | the whistle range, its home, the split from the voice range | `no steady whistle heard in <n> s`; `too small or too short (<x> st, <n> steady ticks; need 3 st, 50 ticks): whistle from your lowest to your highest and back`; `the whistle overlaps your voice range (whistle from <f> Hz, voice up to <f> Hz): whistle higher, or skip` |
| `hiss` | 2 short 'tss' (8 s) | the hisses' gate numbers | `heard <n>/2 hisses, need 2 (a short, sharp 'tss', a bit louder)` |
| `room` | stays quiet, 3 s | the floor (dBFS) and the loudest extractor transient | `not quiet: a steady tone was heard for <n> ms (a voice, music or a hum): make the room quiet and retry`; `a sound in the room was as loud as your quietest calibrated sound (<n> dB over the floor, yours <n> dB): make the room quieter and retry, or skip` |

The room fails on a transient only when it is within the gate's reach in both SNR and level (transient + 3 dB over
the weakest calibrated sound - 1 dB). During the whistle step, and afterwards for a profile with a whistle range, the
ticks track pitch up to 2600 Hz (the voice's ceiling is 1100 Hz). The profile then steers by the whistle over the
split: its own home and range, `band: "whistle"` in the joystick's state. It keeps one profile per mic
source, stored only on the phone (prefs `canti_joystick`, key `calib_<source>`). The Pico can't be calibrated yet.
While a calibration runs, every mic sound is dropped (`mic_sound{dropped: "calibrating"}`): nothing acts.

The **tick detector is not calibrated** by any step: a profile's `pop` block (`peak_db`, `rise_db`, `core_ticks`) is
kept from an old profile, or stays null (the spec defaults). Its thresholds were tuned on lip pops; whether tongue
clicks trip it is an open question — if they don't, cursor clicks come from the extractor alone (~110–160 ms after the
sound ends). Old profiles' `pops_examples` still count toward the level gate (they are the user's mouth sounds); a new
run has none.

**Commands.** Each is a UI-channel method or a debug op of the same name. Each answers the calib_status map.

| Command | What it does |
| --- | --- |
| `calib_start {source, steps?, resume?}` | Starts a run. `steps` (optional) is an ordered subset of the 7 steps, no repeats (e.g. `["clicks", "whistle", "hiss", "room"]` to bring a version 1 profile up to date); without it, all 7 in order. `resume` (default true when `calib_progress_<source>` exists and is < 24 h old; never with `steps`) runs the steps not in the saved `done_steps`, starting at the first; with none left it is a full run. The run starts directly on its first step and covers only those steps. `source` must be the current sound source, and the mic must be capturing (Canti resumed). The draft is the saved profile with the run's steps taken out of `skipped`: a step outside the run keeps its saved values and skip state (the save merges), and a step in the run that was skipped before is recorded again. The first tick after the start times the first step (the stream may have run for minutes). |
| `calib_step {step}` | Records `step`. It works in any state (a step already waiting or recording is left alone unless it is a different step, in which case the in-flight step is dropped; saved steps stay). With no run open (the hub's rows, after a cancel) it first opens one on the current source as `calib_start` without args would (resumed). After `step_done`, the UI sends it for the next step of the run (`remaining[0]`). A step outside the run joins it. |
| `calib_redo {step}` | Records a finished step again, for example from the result (it is saved again when it finishes). With no run open it opens one, as `calib_step`. When it finishes (or is skipped) the state goes back to `done` if every step of the run is finished; no other step starts. A step outside the run joins it. |
| `calib_retry` | Only from `failed`: records the failed step again. |
| `calib_skip` | Allowed from `failed`, from `waiting`, on `clicks` / `hiss` before anything countable was heard, or during `room`. The step keeps its defaults and goes into `skipped`. **The run's next unfinished step after it then starts by itself** (the UI sends no `calib_step` after a skip). It never wraps round and never starts a step outside the run: with none after it, the state is `done` when every step of the run is finished, else `step_done` (an earlier step is still open: the UI picks it). |
| `calib_save` | Stores the draft (`saved_at_ms`, `complete: true`), removes `calib_progress_<source>` (the run is complete: the next `calib_start` begins at the top), applies it to the joystick, and ends the run. It answers the inactive map. |
| `calib_cancel` | Ends the run. **Finished steps are already saved** (per-step save): only the in-flight step is lost. It answers the inactive map (with `resume`). The service also ends an open run by itself (log `calib{event: cancel, by}`): `idle` (no command for 5 min), `app background` (every Canti screen stopped for 10 s: Home, another app, the screen off), `ui closed` (the Flutter screen that owned it went away); for the first two a `calib_status` push carries the inactive map with an `error` saying so. A refused `calib_start` logs `calib{event: refused, reason, source}`. |
| `calib_status` | Changes nothing. |
| `calib_get {source}` | Answers the saved profile, or null. |
| `calib_delete {source?, step}` | Deletes **one step's saved result** (no run may be open, else `error: "Finish or cancel the calibration first"`). It clears that step's measured fields (the same per-step reset as `calib_skip`, not a copy), removes it from `skipped` if it was there (it is **not** added), re-derives the level gate from the examples left, and removes the step from `calib_progress_<source>`'s `done_steps` — or, when the profile was complete and had no progress, writes one with every *other* finished step. The step then reads as not done (`missing_steps`, the hub, `needs_recalibration: true`). The other steps' values are unchanged. The old profile + progress are stashed first in `calib_trash_<source>`. Answers the inactive map. |
| `calib_undelete {source?}` | Restores the profile and progress a `calib_delete` stashed, only if the saved profile is still the one the delete wrote (its `saved_at_ms` is compared): otherwise `error: "calibrated again since"`. A new `calib_start` clears the stash, so an undo after starting a new run has nothing to restore. Answers the inactive map. |

A failed step never skips or starts again on its own: it stays `failed`, with a `reason`, until `calib_retry` or
`calib_skip`. A command that can't run (no run, a wrong source, the mic off, an unknown step) answers the status map
with `error`. The debug op also sets `ok: false`.

**The calib_status map:**

- Identity and state: `active` (true during a run), `source`, `step` (`hum`|`glide`|`vowels`|`clicks`|`whistle`|`hiss`|`room`), `state`
  (`waiting`|`recording`|`failed`|`step_done`|`done`; `done` = every step of the run is finished, measured or skipped).
- The run: `steps` (the run's steps, in order) and `remaining` (those not finished yet, in order).
- Prompts: `prompt`, `sub`, and `waiting_for_steady` (the step waits for a steady note).
- Progress:
  - `progress` (0..1 of the step);
  - `step_done` (bool: the step just succeeded);
  - `reason` (the failure, or null);
  - `skipped` (the steps skipped in this run; `result.skipped` is the merged profile's).
- Live readout: `live{voiced, pitch_hz, level_db, vowel, vowel_conf, trace_hz (the joystick ticks, 20 ms, the last 5 s,
  null = unvoiced), checks (the provisional grade)}` and `heard{clicks_n, clicks_need: 3, hiss_n, hiss_need: 2}`
  (`*_n`: the countable sounds heard so far in that step; `*_need` is what is asked, the step passes on 2). No `pops_n`
  / `pops_need` (the pops step is gone).
- `expect`: the wanted shape for a pitched step, as the training `expect` plus `tone`: `hum` = flat at home over 3 s;
  `glide` = an ARCH from low over 5 s (the prompt says lowest to highest AND BACK, which a rise check would fail);
  `whistle` = an arch from low, whistled, over the spec's glide time. Null for the others.
- `scale`: `{low_hz, home_hz, high_hz}` from the draft so far (during `whistle`: the whistle range, else null), or null.
- `live.trace_hz` and `live.checks` are the current step's: the trace starts empty at each step.
- `pos`: `{i, n}` (1..7 over `JoyCalibration.STEPS`).
- `hub`: `[{id, done, result_word}]` over all 7 steps (`result_word`: `ok` | `skipped` | `·`), for the hub rows. (The E9
  contract calls this `steps`; that name was already the run's step list, so it is `hub`. `done` = the draft has the
  step's values, from this run or the saved profile.)
- `result`: the draft profile, once any step has finished.
- `calibrated`: whether a profile is saved for that source.
- `error`: the last command's error, if any.

The inactive map, with no run, is `{active: false, source, state: null, calibrated, skipped, resume, error}`, where
`resume` is `{step, done_steps}` (where `calib_start {resume: true}` begins, and the steps done so far) when a progress
is saved with a step left, else null.

**Per-step save and resume.** When a step finishes (measured or skipped, a redo too) its values are merged into the
profile `calib_<source>` at once (the same JSON as `calib_save` with `complete: false`; unfinished steps keep their
saved values), and `calib_progress_<source>` = `{done_steps, current, updated_ms}` is written in the same
SharedPreferences commit (synchronous, so an app kill right after keeps it). `done_steps` = the steps this run finished
plus the ones done before it (a resumed run's earlier steps; a `steps` subset run's other steps the profile has), in
step order. A cancel (BackgroundGuard, UiBridge.close, idle, `calib_cancel`), a service restart or an app kill therefore
loses only the in-flight step. `calib_start {resume: true}` (the default while the progress is < 24 h old) runs the
steps not in `done_steps`. Existing profiles load as before (no `complete` = false; no progress = no resume).

**The profile:**

- The contract fields:
  - `source`, `version: 2`, `saved_at_ms`, `complete` (true only after `calib_save`);
  - `home_hz`, `range_lo_hz`, `range_hi_hz`, `voicing_threshold`;
  - `vowels{ee, ah, oo: {acc}}`;
  - `pops_heard`, `skipped`;
  - `extractor: {}`;
  - calibration v2: `clicks_heard`, `hiss_heard`, `whistle_lo_hz`, `whistle_hi_hz`, `whistle_home_hz`,
    `room_floor_dbfs`, `level_gate{min_snr_db, min_level_dbfs, from, n, weakest_snr_db?, weakest_level_dbfs?}`,
    `relabel_rule` (bool, always false for a new run: the pop <-> click relabel is retired), `missing_steps` (the steps
    neither measured nor skipped), `needs_recalibration` (`missing_steps` is not empty).
- Extras:
  - `home_st`, `clarity_on`, `lo_st`, `hi_st`;
  - `vowel_centroids_bark`, `vowel_dead_zone`, `vowel_full`, `vowel_report`;
  - **Legacy (a pop counts as a click, 2026-09-28):** `pop{peak_db, rise_db, core_ticks}`, `pop_labels`,
    `pops_examples`, `click_pop`, `pops_heard`. These are read, kept and round-tripped so old profiles load and nothing
    crashes; a new run leaves them null. The `pop` block (the tick detector's thresholds) is not recalibrated, and the
    old `pops_examples` still feed the level gate. `relabel_rule` is always false for a new run.
  - `whistle{lo_st, hi_st, home_st, split_st}`, `room{floor_dbfs, transient_snr_db, transient_level_dbfs, transients}`,
    `pops_examples` / `clicks_examples` / `hiss_examples` (each `[{label, dur_ms, snr_db, level_db, lf_ratio,
    peak_centroid_hz}]`: the extractor's gate numbers, never audio), `click_pop{features{<f>: {thr, pop_above}}, min_votes}`.
- **Version 1** profiles (four steps) still load and drive the cursor as before; they answer `version: 2` with
  `missing_steps: ["clicks", "whistle", "hiss", "room"]` and `needs_recalibration: true`, and keep the default level
  gate. The inactive calib_status map and the joystick's describe also carry `needs_recalibration` and
  `missing_steps`. The gate and the relabel rule are derived again from the stored examples on every load, so a
  spec change applies without recalibrating.
- A skipped or unknown value is null, and the spec default applies.
- `extractor` is reserved for the gesture extractor's overrides (`VxNative.open`). It is **empty**: the desktop
  go/no-go found no `vx_config` field worth moving. If overrides are used, `f0_min_hz` is clamped to at least 32 Hz.

**Migration (2026-09-28).** `calib_step` / `calib_redo` / `calib_start {steps}` accept `"pops"` as `"clicks"` (an old
UI sends it until E10UI), so `["pops","clicks"]` collapses to `["clicks"]`. Old saved progress (`calib_progress_<source>`
with `"pops"` in `done_steps`) loads, but the finished `"pops"` is **not** a finished `"clicks"`: it is dropped and the
resume starts at `clicks`. Old profiles' legacy fields (above) round-trip and a legacy `skipped: ["pops"]` is ignored
(dropped on the next save).

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
| 1 click | toggle `mode` gesture ↔ cursor (its state message carries `"by": "button"`) | nothing |
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

**Disconnect** means the device is disarmed: the app behaves as on `armed: false`. After an unexpected disconnect, such as the phone going out of range, the device stays **disarmed** when the phone reconnects. The user re-arms with 5 presses or from the app. Only waking with 5 presses arms on connect. The app tells this **link-drop pause** from a pause the user chose (the device's state message carries no reason): a link whose first message says `armed: false` is a link-drop pause, unless the device was last disarmed by the user (`armed` going true -> false on a live link, from the app's Pause or the button, or a confirmed `armed: false` command; kept across service restarts). Only a link-drop pause is `wakeable`: the floating badge shows `tap-to-wake`, and a tap on it (or the notification's **Wake**) sends `{"v":1,"armed":true}`, the status screen's Resume command, plus `"mode"` in the same write when the device is not in the **user's mode**: the mode the user last chose themselves, saved (`canti_device/user_mode`, default `gesture`) only when a mode change from the badge menu, the notification or the status screen is confirmed, or when a state message says the device's button made it (`"by": "button"`). The `device` op, test tools and the Pico's console never change it. The confirming state message arms the app and sets its mode in one badge update (no `idle` on the way to `cursor`). Long-press opens the badge's menu in every state. Logged `device_pause{cause: link-drop | user | none, why}`, `wake{by: badge | notification, result: sent | confirmed | failed | skipped, why, error, ms, mode, device_mode, user_mode}`, `mode_request{by: wake}` when the mode is restored, `user_mode{mode, by, result: saved | unchanged | ignored}`, `badge{event: tap-to-wake | long-press}`.

## Event log

Each event is one JSON line: `{"ev": name, "t": elapsedRealtime ms, ...}`. It is written to logcat, tag `VOX`
(`adb logcat -v raw -s VOX:I`), and to `files/events.jsonl` (`adb exec-out run-as ai.vox.companion cat files/events.jsonl`).
Logcat cuts lines at about 3.8 KB, so the file is the complete record. The API key is never logged.

The event chain for one decision (`n` links the events of one decision; `watch` links the gesture to its confirmation):

```
msg → [wait] → resolve{n, sequence, phrase, waited, held_ms, app} → state{n, text}
    → decision{n, action, source, confidence, ms, path, since_msg_ms} → exec{n, ok, how, watch, prep_ms}
    → gesture{watch, result} → confirm{watch, result, by, ms, echoes_ignored}
```

The confirmer's `result` is one of:
- `confirmed (events)`: an accessibility event showed an effect (a scroll, a window change, a text change, or a
  content change that altered the visible-tree fingerprint).
- `confirmed (pixels)`: no event came, but a `takeScreenshot` taken before dispatch and one taken at the timeout differ
  in more than 0.5% of a 36x80 luminance grid. System bars and VOX's own overlays are masked out. This covers GL
  surfaces such as maps. Screenshots are kept at least 1 s apart (Android refuses closer ones with error 3): a baseline
  that would come too soon reuses the previous watch's timeout screenshot if it is under 1 s old (`screenshot
  reused`), else the watch runs on events alone (`by: screenshot rate-limited`); a timeout screenshot that would come
  too soon waits out the interval.
- `no visible change`.

Clicks, long clicks, selections and focus changes that arrive while our own injected gesture is running, or within
250 ms after it, are echoes of our touch. They are counted in `echoes_ignored` and never confirm anything.

Latency: `decision.path` is `local` when the decider settled it without the screen or a model (`Decider.local`: bound
gestures, cursor sounds, app-only bindings, not-deliberate and unbound sequences; in `model` mode only app-only and
personal ones), decided at once on the main thread with no screen walk (its `state` has no screen line and
`screen: "skipped (decided locally)"`); `worker` is the full path (screen summary, then the decider thread). It is
taken only when nothing older is still being decided, so decisions stay in order. `since_msg_ms` is the time since the
last features message arrived (it includes a sequencer wait). `exec.prep_ms` is the main-thread time up to the gesture
dispatch (the confirmer's before-fingerprint included). Event-file writes run on their own thread.

A rise / fall (and a voice scroll or next / previous that becomes a feed fling) also logs
`fling_wait{action, plan, cache, cache_hit, age_ms, tree_ms, check_ms, refused, wait_ms, how, ok}` just before `exec`.
A rise / fall never reads the tree: it plans from a cache (FeedKindCache) refreshed off the main thread. `plan`:
`feed` (a fresh "paged feed" answer: the feed fling), `list` (a fresh list plan: its one list node is refreshed,
`check_ms`, and must still be visible, the same class and inside the screen, on a screen of the same size; then it
steps with the node's live bounds and scroll actions), `other` (a fresh "neither" answer, no scroller or a horizontal
one: the plain fling), `last-feed` (no usable answer, in a known feed app, ScrollStep.FEED_APPS, whose last answer this
session was a feed: the feed fling), `plain` (no usable answer otherwise, or the list check `refused`: the plain
fling; a background refresh starts), `read` (voice scroll only: the tree read on the spot, `tree_ms`), `sideways`.
`cache`: `hit`, `expired`, `miss` (`none` for sideways). `wait_ms`: from the executor taking the swipe to the dispatch
call returning. `age_ms`: the cached answer's age. The cache is refreshed on window changes and, at most every 2 s with
a trailing read after the last change, on content changes and scrolls, while armed; feed answers live 6 s, list plans
20 s (re-checked live before each step), "neither" answers 1.5 s.

`feed_undetected{app, window, why, tree}`: once per window, a known feed app whose screen shows no usable scroller
(YouTube Shorts in RVX, round 4). `tree`: structure only, no text: node count, the scrollable nodes (visible or not),
the big nodes and the video surfaces, each with class, view id, bounds, visibility, child count and scroll actions.

`decision` also carries `server_ms` (the server's `latency_ms`, when a model answered) and `top` (the model's best
options with probabilities).

Intent cursor mode (see below) adds its own chain, linked by `n`:

```
listening{mode: cursor} → [asr] → msg{phrase} → target_state{n, app, text, options}
    → target_decision{n, choice, confidence, top, ms, server_ms, min_confidence, unscored}   (or {n, error})
    → target{n, result: "tap" | "choose" | "not on screen" | "no model (decider=rules)", ...}
    → [choice{n, event: select | picked | spoken_pick | spoken | narrowed | no_match | ignored | cancelled, selected, option, text, why}]
    → exec/gesture/confirm as above
```

Other events: `absorbed{sound, tail_of, gap_ms, clock}` (above), `mode`, `arm`, `listening`, `ignored{reason}`, `app`, `service`, `source`, `profile`, `screen`,
`harvest`, `reset`, `error`, `cursor`, `toast{text}`, `asr` / `phrase_parse` / `target_match` (*Spoken phrases*, below),
`escalate{kind, outcome, model, choice, ms, tokens_in, tokens_out, error, fallback}` and `confirm_ask{n, action, event, why}`
(decider `escalate`, below),
`match`, `enroll` and `fp_floors{fp_version, status, source, note}` (personalization, below),
`train{event: start | take | skip | keep | delete | done | end, ...}` (*Gesture training*, below),
`forward{result: clicked | click-failed | no-forward, where, why, waited_ms, menu_closed}` and
`badge{event: moved | menu | long-press | tap-to-wake | pass-through | tucked | untucked | state, ...}` (the Canti head; `state` carries the held state on each change, for the app's header; `tucked` while a Canti screen is in front), `hold{kind, sound, ...}` / `hold{event, why}` and `auto_scroll{event: start | stop, action, app, hold, why, pct_per_s, ms}` (*Hold messages*),
and the BLE link's events:
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
    `armed`, `paused`, `mode`, `app`, `decider` (the display line: the mode, or `escalate (ollama: <model>)`),
    `decider_mode` (the bare mode), `ble_state`, `ble_device`, `ble_hint` (the `needs_pairing` hint,
    or null), `device_state` (`ble_status` `device.presence`), `device_ready`, `device_armed`, `device_mode`,
    `device_waiting`, `device_error`, `vocab`, `auto_scroll` (null, or e.g. `hold-scroll down`), `badge` (the head's held state: `idle`, `pending`, `hold-scroll`, `cursor`, `paused`, `off`, `tap-to-wake`, ...), `sound_source`
    (`pico`|`phone`|`usb`), `mic_state` (the phone-mic state, e.g. `listening`) and `mic_device` (the input in use).
    `asr_engine` and `asr_status` (the phrase window's speech: `ready`, `off`, or e.g. `offline speech pack missing`).
    For the first-run pairing screen: `ble_missing` (the Bluetooth runtime permissions not granted, Android names),
    `ble_blocked` (refused with "don't ask again"), and with the Pico as the source `ble_adapter` (`on`|`off`|`none`),
    `ble_target` (the address being connected), `ble_target_name` (its advertised name, e.g. `VOX-2807`) and
    `ble_scan` (`scanning`, `none found` when the last search ended empty, or null). `calibrated` (bool): a voice-joystick
    calibration is saved for the current sound source (always false for the Pico); `calibrating` (bool): a calibration
    run is open now (its sounds are dropped as "calibrating", so Canti is deaf until it ends); `training` (bool): a
    gesture-training round is open now. `bindings`: the bindings window's
    picture (`ui/lib/src/status_screen.dart` "Bindings") — `{gesture: {sounds, combos, note}, cursor: {sounds, combos,
    note}}`, one `{label, source}` per single sound (null = unbound, `source` one of `default`, `app-only`, `global`,
    `app`, `cursor`) and one `{seq, label, source}` per multi-sound combo, resolved like the rule decider
    (`app > global > defaults > app-only` in gesture mode; cursor rules > the built-in single-sound cursor and the app's
    `pop pop` target listening) and noting
    the mic-source exceptions (a phone/USB lone pop taps only where bound; in cursor mode the voice joystick takes
    the hums). `Bindings.kt`
    builds it.
  - `setPaused {paused: bool}` does what the `pause` op does, logs `pause{by: app}`, and returns the status map;
  - `deviceCommand {armed?, mode?, sleep?}` does what the `device` op does, but answers only when the device has
    confirmed or the command failed: `{ok, cmd, result, error, ms, applied, armed, mode, sleeping}`;
  - `connectDevice` connects to the remembered device again (`ble_connect auto`; it also ends `needs_pairing`), or,
    with none remembered, searches and connects to the first Canti device found; returns the status map;
  - `requestBluetooth` asks for the missing Bluetooth permissions and answers with the status map once the dialog
    is answered (logs `ble{what: permissions}`); `enableBluetooth` shows the system's turn-on dialog;
    `openAppSettings` opens Canti's page in the system settings;
  - `launchRoute` answers the screen the activity was opened for (`pair`, or `calibrate`: the joystick calibration,
    from the badge menu's CALIBRATE, logs `ui{what: open_calibrate, by}`), once, or null. The badge menu and the
    sound-source chooser open the pairing screen this way when the Pico is picked with no device remembered
    (`Pairing.kt`, logs `ui{what: open_pairing, by}`); a running UI gets `openRoute {route}`, a call from Kotlin on
    this same channel;
  - `cursorSettings` answers `{cursor_speed, cursor_pitch_sens}` (the joystick sliders, 0.5-2.0, default 0.9; works
    with the service off); `setCursorSettings {cursor_speed?, cursor_pitch_sens?}` stores them clamped (logs
    `setting{cursor_speed, cursor_pitch_sens, by: app}`), applies them to a running joystick, answers the same map;
  - `levelGateSettings` answers `{level_gate, level_gate_offset_db}` (the calibration-v2 level gate: bool, default
    true; -10..10 dB, default 0, + = stricter); `setLevelGateSettings {level_gate?, level_gate_offset_db?}` stores
    them (the offset clamped, logs `setting{level_gate, level_gate_offset_db, by: app}`) and answers the same map;
  - `calib_start {source, steps?, resume?}`, `calib_step {step}`, `calib_redo {step}`, `calib_retry`, `calib_skip`, `calib_save`,
    `calib_cancel`, `calib_status` answer the calib_status map, and `calib_get {source}` the saved profile or null
    (*Voice joystick*, Calibration). Kotlin also calls `calib_status {map}` on this channel about every 100 ms while a
    calibration runs and after every command (also one from the debug socket);
  - `openLegacySettings` opens `LegacySettingsActivity`, the native screen (decider, endpoint, API key,
    permissions) that stays until Flutter screens replace it.
- `ai.vox/events` is an event channel: every event-log line as its JSON string, from the moment the screen listens.
- `ai.vox/train` is a method channel for gesture training (*Gesture training*, below; the Dart side is
  `ui/lib/src/train.dart`, `ChannelTrainBackend`): `train_status {source?}`, `train_start {gesture, cell?, source?}`,
  `train_record`, `train_retry`, `train_skip`, `train_keep`, `train_next {record?}`, `train_cancel`,
  `train_delete {gesture, cell?, source?}` answer the train_status map (with `error` when refused; `{service: false}`
  with the service off). Kotlin calls `train_status {map}` on it after every change and about every 100 ms while a take
  records. Closing the UI ends an open round.

With the Pico as the source and no device remembered, the status screen shows **Find my Canti device**. It opens the
pairing screen (`ui/lib/src/pair_screen.dart`), which searches at once and shows each stage (search, found
`VOX-xxxx`, connect, pair, connected), names any missing permission with a button to grant it, offers to turn
Bluetooth on, and explains the device's pairing window (hold its button 5 s).

The status screen's main button follows the device when one is connected (`device_ready`): **Pause Canti** sends
`{"armed": false}`, **Resume Canti** lifts an app-side pause and sends `{"armed": true}`. Without a connected device
it is the app-side pause (`setPaused`). The **Gesture / Cursor** mode toggle appears whenever the service runs and a
mode can be set: with a connected device it commands the device (like `deviceCommand {mode}`), and with a phone or USB
mic source it applies here (`setDeviceMode`; the phone owns the mode). **Sleep device** appears only while the device
is connected.

The Dart side is `ui/lib/src/channel_backend.dart` (`ChannelBackend`). `FakeBackend` is the in-memory stand-in
used by the widget tests and the Linux desktop runner.

## Test recorder (dev)

DEV-ONLY (round 7 §3d in-app): the in-app range recorder + quick record, gated by `BuildConfig.DEV_RECORDER` (true in
debug, false in release; read as `ai.vox.companion.rec.DevRec.enabled`). All code is in package `ai.vox.companion.rec`;
every hook in existing files is a `// [rec]` one-liner that no-ops when the gate is off. The Pico source is not
supported (it sends features, never audio): the recorder records the running phone/usb capture only. Audio stays in
app-private `files/` (run-as only; `allowBackup=false`), is never uploaded or logged; the ring is RAM-only. Removing
for release = set `DEV_RECORDER` false (or delete package `rec` + the `[rec]` lines).

`uiStatus` gains `dev_recorder` (the gate) and `recording` (a recorder session is open); the UI shows every
recorder/quick-record entry only when `dev_recorder == true`.

- The recorder runs `extractor/prompts/range_v2.json` (`short` 42 takes; `full` 269 takes + 7 backgrounds), bundled as
  the asset `range/range_v2.json` by a Gradle copy task (DEBUG source set only, so a release APK ships no spec), and
  writes the exact `range_layout.validate_session` layout under `files/range/<name>/` (spec.json verbatim; session.json
  with `recorder:"app"`/`range_pending`/`app_range`/`skipped_by_sitting` and `range` Hz null; labels.jsonl /
  backgrounds.jsonl / ratings.jsonl; `takes/` / `backgrounds/` WAVs — tmp + rename before the label row, last row per
  take_id wins). A session is bound to its spec version: `rec_open` refuses a different version ("This session was
  recorded with range_v1; the app records range_v2. Start a new session.") and a byte-for-byte differ for the same
  version; `rec_list` marks each session `resumable` (its spec version matches the bundled one).
- Quick record snapshots the last ~12 s RAM ring plus the HeardLog window into one pending snapshot; nothing touches
  storage until `qr_save` writes `files/quickrec/<id>/{clip.wav, meta.json}`.

Ops (method channel `ai.vox/recorder`, main thread; the same names are debug ops on the control socket, flat replies
like `measure_*`; with the gate off the channel answers `{enabled:false}` and the debug ops `{ok:false,
"recorder disabled"}`): `rec_list {}`, `rec_start {who:"me"|"other", speaker?, profile:"short"|"full"}`, `rec_open
{name}`, `rec_status {}`, `rec_next {take_id?}`, `rec_go {}`, `rec_abort {}`, `rec_skip {}`, `rec_redo_last {}`,
`rec_rate {block, rating:1..5, note}`, `rec_close {}`, `rec_clear {sessions?, quickrec?}`, `rec_delete {name?,
take_id, scope:"take"|"attempt", attempt?: int|null}`, `rec_restore {name?, del_id}`, `rec_trash_clear {name?,
del_ids?}`, `qr_snap {}`, `qr_pending
{}`, `qr_save {id, label, note?, sound?}`, `qr_discard {id}`. Kotlin pushes `rec_status {map}` on every change and every
100 ms while ready/countdown/recording, and `qr_snapshot {map}` from the badge's QUICK REC menu row (which then opens
the `quickrec` route).

`rec_status` map: `{enabled, active, name, speaker, profile, mic, rate, state:
idle|ready|countdown|recording|saved|no_sound|rate|done|error, error, reason, take: {take_id, block, block_title, i,
n, block_i, block_n, cue, expect, cond, bg, kind, quiet, manual, target_s, max_s, seconds, redo}, countdown_s, rec_s,
level: {bars_db, min_db, peak_dbfs, note}, heard: [HeardSound...], last: {take_id, saved, dur_ms, reason, f0_hz,
below_f0_min}|null, live: {trace_hz: [Hz|null...], tick_ms: 20}|null, blocks: [{id, title, intro, done, total, rating, skipped}], done, total, skipped, bytes,
backgrounds_done, backgrounds_total, rated_blocks, next: {take_id, cue}|null, defaults: {distances_cm, speed_s, gap_s},
scale: {low_hz, home_hz, high_hz, from:"calibration"}|null, plan: [{take_id, block}]}`. HeardSound: `{label, t_start_ms, t_end_ms, rel_ms,
dur_ms, pitch16, f0_hz, dropped, gated, relabel, did: {n, sequence, action, ok}|null, did_text, ago_s?, raw_label?}`.

`plan` is the open profile's whole take list in plan order (the order `range_layout.build_plan` gives; `short` 42,
`full` 276 with the backgrounds). It is fixed for the session, so it is in every command reply and every state-change
push but left out of the 10 Hz ready/countdown/recording pushes (about 16 KB for `full`): a UI keeps the last one it got
and sends `rec_next {take_id}` from it (header arrows, block rows). `next` is the first take neither recorded nor
skipped this sitting.

Sessions are named like the desktop recorder (`range_layout.default_session_name`): `range-<yyyyMMdd-HHmmss>` for
`who:"me"` (speaker `self`), `range-<speaker>-<yyyyMMdd-HHmmss>` for another speaker (a pseudonymous id, letters, digits,
`-`, `_`); a clash within the same second gets `-2`, `-3`, ...

A **missed take** (`no_sound`: the detector heard nothing to keep) is saved and kept, never overwritten by "Try again":
its WAV is `takes/<block>/<take_id>.a<N>.wav` and its label row carries `no_sound: true, attempt: N` (N = the
attempt's redo number). A heard attempt keeps the plain `takes/<block>/<take_id>.wav`. The take is its last heard row
(`range_layout.take_rows`); a take with only missed attempts is its last missed row. `range_layout.validate_session`
checks every missed attempt's file and fields; `range_suite` counts each one as a gate miss (kept 0) and reports them
under `no_sound`.

A take (or background) can be soft-deleted and undone (contract T, same for v1 and v2 sessions): `rec_delete` moves the
WAV(s) to `trash/<del_id>/<its original relative path>` then appends the `op:"delete"` row (a background's row has
`name` in place of `take_id`), `rec_restore` moves them back then appends `op:"restore"`, `rec_trash_clear` removes
`trash/<del_id>/` and appends `op:"purge"` rows. The journals stay append-only; a delete excludes the earlier rows its
scope names (a deleted take is not done and is prompted again), and ratings are never touched. The live pitch trace
(`live.trace_hz`, a 20 ms tick's f0 Hz or null) is filled during a hum/whistle take and kept for the last take in
`saved`/`no_sound`; a heard `pop` folds to `click` in `heard[].label` with the raw kept as `raw_label`.

"What Canti did" (`did` / `did_text`), from the in-memory event log only (no audio): a dropped sound is `ignored:
<why>`; a sound followed within 1 s by `media_gate{dropped:true}` of its kind is `ignored: media lock`; otherwise the
delivered sounds are taken in time order by the resolves that follow them (each resolve takes the last k delivered
sounds of the last 3 s, k = its sequence length), then `decision{n}.action` and `exec{n}.ok`; one no resolve took is `no
action`. A gated sound shows as `UNKNOWN (MEDIA) → <action>`. The log follows the capture generation: a new capture
clears it, a late event of an older one is ignored.

Quick record: `qr_snap` (or the badge row) holds the ring's current contents atomically (`rate`, capture generation) and
the heard window; an empty ring (the mic not listening) replies `{id:null, error:"nothing heard yet: the mic is not
listening"}`. `qr_save {id, label, note?, sound?}` refuses an unknown label or a `sound` index outside the snapshot's
sounds and writes `clip.wav` (PCM16 mono) + `meta.json {version, id, saved_at_ms, label (rise|fall|dip|arch|pop|pop pop|click|click click|click click click|hiss|hum|
misfire), note, sound, rate, seconds, source (phone|usb), mic, app, mode, sounds: [HeardSound with did/did_text]}`
(tmp + rename). The snapshot map (`qr_snapshot` / `qr_pending`) also carries `last_action`. `rec_clear {sessions?: [names], quickrec?: [ids] | "all"}` deletes exactly those
(names and ids are checked, never a path; refused while a session is open) and replies `{ok, deleted: {sessions,
quickrec}}`.

Events: `rec{event: open|take|skip|rate|close|clear|abort|delete|restore|purge, name, fields}` (take ids, reasons, counts only; never audio).

`mic_sound` (all builds) gains `pitch16` (16 floats, semitones from the sound's start, rounded to 0.1; `[]` when
unpitched) and `f0_hz` (median f0 from `fp[0]` as `TrainJudge.f0Hz`, rounded to 1 Hz; null when unpitched). While a
recorder session is open every phone/usb sound is dropped with `mic_sound{dropped:"recording"}` (precedence
`touch ?: level gate ?: joystick ?: recording ?: dry_run`), so labels/gates/pitch still log and nothing acts.

`rec_start` refuses unless the source is phone|usb, the capture is listening, the mode is gesture ("Switch Canti to
gesture mode first"), no calibration/training/measurement is open, and ≥ 200 MB is free; the other way round,
`calib_start` and a training start refuse with "Test recorder is open" while a session is open; `rec_open` refuses a differing
spec version (see above) or, for the same version, a byte-for-byte differ, a differing rate or mic. A capture stop/restart aborts only the in-flight take (state `error`, session open);
the session closes on `rec_close`, UiBridge close, or 10 min idle — never on BackgroundGuard (a background may play on
the phone). The PC pulls with `android/suite/range_phone.py pull` (see extractor/RANGE.md): every file is
size-checked and each session validated before anything local is replaced, and the phone copy is deleted only with
`--clear` and a typed yes (or `--yes`).

## Decider HTTP call

`POST {base_url}/v1/systemone`. `Authorization: Bearer <key>` is sent only when a key is set. Both model clients (this one and
the `escalate` Ollama client) send `User-Agent: Canti/<version> (Android)` (`CantiHttp`): ollama.com answers the
default `Dalvik/...` agent with a 403 HTML page whatever the key. An HTTP error with an HTML body reads
`HTTP <code> blocked by server (not an API reply)`; a 401/403 API answer reads `HTTP <code> (auth): <body>`.

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
otherwise. `escalate` is below.

## Navigation actions: swipes, home, back, forward, auto-scroll

Default gesture bindings (`finetune/vox/schema.py`, generated into `Vocab.kt`):

| Sound(s) | Action | Notes |
|---|---|---|
| `rise` / `fall` | `swipe_up` / `swipe_down` | A fling: 72% → 12% of the screen height in 100 ms (`swipe_down` mirrors it, 28% → 88%; `SwipeGeometry` in `Navigation.kt`), clamped out of the system gesture and bar insets (at least 48 dp top and bottom, 32 dp at the sides). Paged feeds (Reels, Shorts, TikTok) get a shorter fling instead: 15% of the height in 50 ms (`feed_fling_pct` / `feed_fling_ms`), so they snap to exactly one item. |
| `arch` / `dip` | `swipe_right` / `swipe_left` | A fling across the width, 85% → 15% in 100 ms, through the middle, inside the side back-gesture zones. |
| `hiss` | `back` | The quick path, and the cancel sound (target choice, confirm). Acts at once. |
| `hiss click` | `back` | The two-sound form. The hiss has already gone back; a click within the gap is absorbed (`absorbed` event). |
| `click click` | `home` | `GLOBAL_ACTION_HOME`. |
| `click hiss` | `forward` | **App-only** (`schema.APP_ONLY_BINDINGS`): resolved by the rule table in every decider mode (source `rules:app-only`), and never a model option. `forward` is not in `ACTIONS`, so the students' option lists and the datasets are unchanged. A user rule for `click hiss` still overrides it. |
| `rise`/`fall` + held hum | auto-scroll | Scrolls in the swipe's direction while the hum is held (*Hold messages*: `hold start` within 1 s of the swipe, until `hold end`). A `flat` on its own stays `long_press`. |

**Forward.** Android has no global forward.
1. The app clicks a visible, enabled control whose text or content description is exactly `Forward`, `Go forward`,
   `Navigate forward` or `Forward button`, in any of the foreground app's windows. It clicks the node itself or its
   nearest clickable ancestor. `Fast forward` and `Forward to…` never match.
2. If that control is disabled, nothing happens: `exec` shows `no-forward (Forward is disabled)`.
3. If there is no such control, the app clicks the overflow-menu button: `More options`, `Main menu`, `Menu`, and
   similar labels, preferring one in the top or bottom 18% of the screen. It then polls the menu for Forward for up
   to 1.5 s.
   - If Forward is there and enabled, it is clicked (`forward{result: clicked}`).
   - If Forward is missing or disabled, the menu is closed with back, but only if the screen changed, and the event
     is `forward{result: no-forward}`.
4. With neither a Forward control nor a menu, nothing happens (`no-forward`).

Note: in mail and chat apps "Forward" means forwarding a message. `click hiss` there opens the app's forward screen;
it never sends anything.

**Auto-scroll (hold-to-scroll).** A `rise` or `fall` executes its swipe at once, with no delay. If a held flat hum
starts within 1 s of the swipe's end, the page keeps scrolling that way until the hum stops. The held sound's own
final event is then not acted on, so it is not a long-press. The rules (gate, speed, stops, the 4 s limit per hold,
the log events) are under *Hold messages*. It shows in the status map's `auto_scroll` field
(e.g. `hold-scroll down`) and on the overlay badge while it runs.

## Decider `escalate`: the cloud model for hard cases

`EscalatingDecider` (`OllamaDecider.kt`). The phone calls an Ollama chat API directly, with no PC in the path:
`ollama_endpoint` (default `https://ollama.com`, or a LAN Ollama), `ollama_model` (default `deepseek-v4.1-flash`),
and the key from the settings screen. The key is stored AES-GCM encrypted under an Android Keystore key and sent only
as `Authorization: Bearer <key>` (no header when it is empty).

```json
POST {ollama_endpoint}/api/chat
{"model": "<ollama_model>", "stream": false, "think": false, "options": {"temperature": 0},
 "format": {"type": "object", "properties": {"choice": {"type": "string", "enum": ["<key>", "..."]}}, "required": ["choice"]},
 "messages": [{"role": "system", "content": "<POLICY or TargetVocab.POLICY>"},
              {"role": "user", "content": "<state>\n\noptions (answer with the key before the colon):\n<key>: <option text>\n..."}]}
```

Keys are the action keys for gestures and phrases, and `t0`, `t1`, ... plus `none` for targets. The answer is
`message.content`, parsed strictly: `{"choice": k}`, `"k"`, the bare key, or `k: <start of option k's text>`.
Ollama cloud does not apply `format` for this model and usually sends the bare key. Anything else is an error.

Routing:
- **Local, instant, never the network:** personalization, every explicit binding (defaults, profile and cursor
  bindings, phrase rules, phrases in the phrase table), and what the policy settles (not-deliberate sounds, unbound
  sequences).
- **Hard cases:** a rule table answer of `*-rule-needs-model` or `rules:unknown-phrase`. The local model
  (`base_url`, optional: blank = none) answers first. The cloud is asked when the local model is absent, fails or
  answers below `min_confidence`, with a deadline of `ollama_timeout_ms` (1500). If the cloud fails, the local
  model's answer is used, else the rule table's.
- **Intent cursor targets:** the cloud first (`ollama_target_timeout_ms`, 2500), then the local model's `target`
  question.
- **Never blocking:** every new event cancels a cloud call in flight, and a decision that starts while a newer event
  is queued skips the network. The event then gets the rule table's answer (`escalate-skipped` /
  `escalate-fallback`).
- **Confirmation:** cloud answers have no calibrated confidence (`unscored`).
  - A risky action waits for a confirm click (`confirm_ask`). Risky means an injected touch on content: `tap`,
    `double_tap`, `like`, `long_press`, `click`, `drag_toggle`.
  - A `click` performs the action; `hiss` cancels it; any other sound cancels it and is then handled as usual.
    `target_choose_ms` also cancels it.
  - A cloud target pick is highlighted alone (the `choose` flow), so a `click` taps it.

**Outward actions always ask** (user decision; `Outward.kt`, one table). Publicly visible actions — `like`,
`double_tap` (the same double-tap at the centre, which likes a post in feeds), and any future action or button whose
name has an outward word (like, follow, share, repost, comment, reply, send, post, subscribe, ...) — wait for a confirm
pop **whatever decided them** (rules, grammar, cloud, local model) and at any confidence. The badge asks ("Like? click to
confirm", "Tap Follow? click to confirm"); `click` performs it, `hiss` or any other sound cancels, and no click within
`outward_confirm_ms` (default 3000; not `confirm_timeout_ms`, which stays the Confirmer's screen-change timeout) means nothing happens (`confirm_ask{n, action, source, why: "outward action" | "outward
button" | "unscored risky action", window_ms}`, then `event: confirmed | cancelled`). A tap on a screen target whose label
is outward ("Like", "Follow", "Send message") asks the same way, also after a highlighted pick. The Executor refuses an
unconfirmed outward action itself (`exec{ok: false, how: "refused: ... needs a confirm pop"}`). Scroll, back, home,
volume, swipes and the rest stay instant. OutwardTest fails until every vocabulary action is classified.

**System dialogs: back or home only** (`SystemDialog.kt`, SystemDialogTest). While a system dialog is in front of the
app — a permission request (the permission controller), the package installer, or a window owned by the system
itself (`android`, `com.android.intentresolver`: the app chooser, a role request such as Chrome's "default browser?",
"isn't responding") at or above the top app window — the Executor drops every queued gesture (`gesture{action, result:
"dropped (system dialog: <pkg>)"}`; a queued back or home stays), refuses every touch (swipes, flings, node scrolls,
taps, double-taps, long-presses, target taps, cursor clicks, hold strokes: `exec{ok: false, how: "refused: system
dialog (<pkg>): <action> (back or home only)"}`, `system_dialog{action, dialog, result: refused}`), never taps a
dialog's buttons, and the badge says "system dialog: back or home only". Back, home, volume, media keys, cursor moves,
open app and timers still run. The signal is the accessibility window list by owner package (cached 100 ms), not the
window type: chat heads, the edge panel and other overlays are system windows too but never block; SystemUI and Canti's
own windows never count.

**Stale trees are refused** (`RootCheck.kt`, RootCheckTest; `TreeReader.appRoot`, which every screen read uses: the
summary, targets, scroll/step decisions, the Confirmer's fingerprint, `dump`). The service reads trees through
Android's per-service accessibility cache; on the Z Flip a `dump` with Instagram in front once returned TikTok's tree
from six minutes before. Every root must be on a current window that is the active or the top app window, and is
re-read past the cache (`refresh()`: false = its window is gone; a synchronous call into the app, so at most once a
second per window). Otherwise the cache is cleared (API 34+) and the root read
once more; if that fails too there is no root: `stale_root{package, why, retry, result: re-read | refused}`, no screen
facts, no targets, nothing tapped.

Every cloud call logs `escalate{kind, outcome: ok | timeout | invalid choice | error | cancelled (newer event) |
skipped (newer event) | no cloud ..., ms, tokens_in, tokens_out}`, never the key. Measured quality and latency are in
`finetune/reports/ollama_vs_students.md`.

Test servers: the suite's fake `/v1/systemone` listens on host port **8767**; the real local server
(`finetune/servers/systemone.py`, started by `suite/run.sh jev start`) listens on **8765**. Both reach the emulator
through `adb reverse`.

## Spoken phrases (the phrase window)

`listen_for_phrase` (default `pop pop`) opens a window of `listen_window_ms` (6000). What is said in it goes through a
deterministic grammar first; only what the grammar does not know reaches the phrase decider.

**Recognizer** (`asr_engine`; `ListenWindow.kt`, `AndroidPhraseRecognizer.kt`). An engine only turns speech into a
transcript plus its n-best (`Heard`); the grammar never depends on the engine.
- `android` (default): the phone's `SpeechRecognizer`, main thread, one per window. The on-device recognizer
  (`createOnDeviceSpeechRecognizer`, API 31+) when available; else the default recognizer with
  `EXTRA_PREFER_OFFLINE` ("only use an offline engine"). **Never a silent cloud fallback**: with `asr_allow_online`
  off (the default), a missing offline pack is reported (`offline speech pack missing`: toast, `asr_status` in the
  app's status screen, the event log) and nothing is sent. `asr_allow_online: true` lets the default recognizer use
  the network. API 33+: at start and on `asr {check: true}` the recognizer is asked whether `asr_language` (`en-US`)
  is installed. Partial results, up to 5 hypotheses with confidences.
- `off`: no phone-side recognition; the window waits for a message `phrase`.
- A message `phrase` (the device, the debug socket) or the `phrase`/`heard` op answers the window the same way.

**Window.** Open → the phone mic yields (`sound_source` phone/usb: Canti's capture stops, `mic{state: "paused for
speech"}`, the foreground service stays; the Pico has nothing to yield) → the recognizer starts 150 ms later when a
capture was running (the recorder is released first) → it ends on its final result or error, or at the window's end:
stop, then 1.5 s for the final result, else the last partial (`partial: true`) → close exactly once: the recognizer is
destroyed, the mic resumes exactly once, late results are ignored. The badge shows `hearing` while it is open. Sounds
and holds that arrive while it is open are `ignored{reason: "phrase window open (speech is not gestures)"}`. A
disarm, pause, reset or a new window cancels it. Canti plays no sounds of its own, so the recognizer cannot hear it.

**Cleaning** (per hypothesis, before the grammar). Hesitations (`um`, `uh`, `er`, `hmm`) and `kind of`, `you know`
are dropped wherever they are; softeners (`maybe`, `please`, `quickly`, ...) at the start or end or next to a command
word ("scroll quickly down"), never as an argument ("tap maybe later" = the Maybe later button); `like` straight before
a command word ("can you like scroll down"), before an amount ("like a lot"), at the end, or between `open` and a name;
a phrase starting with `like` is filler unless it is an explicit like (see the grammar); politeness and the wake word at the start (`could you`, `would you mind`, `i want you to`, `hey
canti` and its mishearings `hey candy`, `ok google`); tails at the end (`for me`, `thanks`, `again`, but not the argument
of a tap verb: "tap okay"); a doubled word (`the the`, not numbers) and a repeated command ("scroll down scroll down")
count once; `scrolling` → `scroll` (present participles only: "i opened it" is narration). **Self-correction**: after
`no`, `wait`, `no wait`, `sorry`, `i mean`, `i meant`, `actually` the last part wins ("go back, no wait, home" → home), borrowing
the verb it replaces ("open youtube, no, spotify", "scroll down, i mean up") or the end of what it corrects ("set a
timer for ten, no, fifteen minutes" → 15 min; "open facebook, sorry, i mean instagram"); `no`/`wait` right after a tap verb are
the argument ("tap no"). A command after a request is found ("i'm gonna go home"). A word cut off with a dash
("scroll d-, scroll down", "open tele-, telegram") is dropped; `let's see`, `what's it called` are filler.

**Nothing happens** (`ignore (why)` in `phrase_parse`; no decision, no toast) for: only filler ("um okay yeah"), a
retraction ("open settings, never mind"), chatter (starts with a question or remark word: "what was i doing", "is it
paused", "how long is left on the timer"), and **two different commands** in one phrase ("scroll down and go home",
"open youtube and spotify": toast "one command at a time"; never a guess; the same one twice is fine). "and" inside
one command stays ("tap terms and conditions", "an hour and a half"). A tap always needs a tap verb (or cursor mode)
and a match on the screen: chatter never taps.

**Grammar** (`PhraseGrammar.kt`, on the cleaned phrase):

| Said | Command | Done by |
|---|---|---|
| an exact user phrase rule (profile scope `phrases`) | the phrase | the phrase decider (as before) |
| `set a timer for 5 minutes`, `set timer for five minutes`, `ten minute timer`, `timer for an hour and a half`, `one minute thirty` (= 90 s), `three thirty` (= 3 min 30 s: two bare numbers, the second 10..59, no unit; a timer is a length, never a clock time; `timer for thirty` alone has no length) | timer, 1 s .. 24 h | `AlarmClock.ACTION_SET_TIMER` (skip UI, message "Canti") sent to **one resolved clock app** (`TimerTarget`): the `timer_app` setting, else the only handler, else the system default, else the one preinstalled clock; several and none of these → not ok, toast "no timer set: choose a clock app for timers ...", nothing started (never the app chooser reported as success) |
| `louder`, `turn it up a bit`, `a lot quieter`, `crank it up`, `louder louder`, `volume up by 3`, `volume to 30 percent`, `half volume`, `volume 5`, `max volume`, `mute`, `shh`, `unmute`, `sound back on`, `it's too loud`, `i can't hear it`, `turn the ringer up`, `alarm volume to max` | volume (`Volume.kt`) | `Executor.setVolume`: the stream (during a call the call volume, else media; `ring`/`alarm`/`notification`/`media` words pick one), the plan (`VolumePlan`: a step is ~1/15 of the stream's range, "a bit" = 1 index, "a lot" = 3 steps, crank = 4; exact levels by fraction or index, a number above the max is a percent; mute remembers the level and unmute restores it, the call volume goes to its minimum instead). Always instant, always the system volume bar (`FLAG_SHOW_UI`). `exec{action: volume, stream, op, ok, how: "volume:music 7->9 of 15 (set 9)"}` |
| `swipe right`, `flick left twice`, `swipe it right` | swipe, the finger's direction | the gesture, repeated (at most 5) |
| `scroll right`, `go right`, `move left`, `what's on the right` | swipe, the **content** direction: the finger goes the other way (`scroll right` = `swipe_left`) | the gesture, repeated |
| `next photo`, `previous slide`, `go back one picture`, `go three photos forward`, `skip two`, `the next three pictures`, `next reel`, `previous short`, `skip this reel` | next / previous N (`next video`, `next one`, `skip this`, `go back one video`: the navigation phrase as before) | `SwipePlan`: a reel / short / tiktok is always the vertical fling (`swipe_up` / `swipe_down`, never a media key), then the rules' screen tie-break (video feed vertical, photo viewer / document horizontal), else a horizontal noun (photo, slide, story, card, tab, page) swipes, else a clear Next / Previous button is tapped, else the rules (`next_item`); horizontal next/previous mirrored in right-to-left layouts. `swipe_plan{n, semantic, noun, screen, rtl, via, action, button, count}` |
| `like this post`, `like the video`, `like it`, `heart it`; `hit like`, `tap the like button` | like (the like button on screen, else the like action) | **always a confirm pop** (outward). `like this`, `like that`, any other phrase starting with `like` → filler, nothing happens |
| `go back`, `back`, `go home`, `scroll up/down`, `go down`, `move up a bit`, a lone `down` / `up` (= scroll **only in a listen window a pop pop opened**, user decision; outside one, e.g. a future always-listening mic, it is `ignore` and needs a verb), `go back to the previous screen`, `hold on a second` (= pause), `next`, `previous`, `pause`, `open camera`, ... (variants → the `Vocab.PHRASES` phrase); `scroll down three times`, `next twice` | navigation (a count repeats only scrolls and next/previous, at most 5) | `RuleDecider` on the phrase (user phrase rules first, the screen tie-break for next/previous and play/pause: a video feed, Reels / Shorts / TikTok, flings vertically); never a model |
| `open\|launch\|start\|go to\|go back to\|switch to\|return to <app>` | open app | launcher labels + aliases, fuzzy (`you tube`, `tick tock`, `net flicks`); `getLaunchIntentForPackage` in user 0. Two installed apps with the name (YouTube and a mod): the `app_prefer` one (default: RVX for YouTube; also applied when only the official app matched the name but RVX is installed), else the most recently used if usage access is already granted (Canti never asks for it), else the official package, else toast "which YouTube? ..." and nothing opens. A known app's name that is not installed (`open snapchat`): toast "no app called snapchat", `exec{action: open_app, name, ok: false, how: "not installed"}`, **never a tap**; `launch`/`switch to`/`go back to` + an unknown name never taps either |
| `tap\|click\|press\|select <thing>`, or `open <thing>` that is no app | tap | `TargetMatcher` on the screen's targets: one clear match (≥ 0.85, 0.1 ahead) is tapped; weak or several are highlighted (numbered, rise/fall move, click taps, hiss cancels, speech narrows); none → the model's `target` question if the decider is not `rules`, else a toast |
| `type <text>`, `write <text>` (only in a listen window) | type into the focused text box | *Typing by voice*, below; checked before the rest of the grammar on the best hypothesis, as the recognizer wrote it |
| `dictate`, `start dictation` (only in a listen window) | dictation mode | *Typing by voice*, below |
| anything else, in cursor mode | tap (a bare word such as `home` falls back to the command) | as above |
| anything else | the phrase | the phrase decider (`resolve` with the phrase, as before) |

Volume and swipe forms are the grammar's own commands (like opening an app): the model vocabulary, its option lists and
`Vocab.SOURCE_DIGEST` are unchanged, and the decider path (rules, models) keeps `volume_up` / `volume_down` (one system
step on the same call-aware stream) and `swipe_*` / `next_item`.
Numbers are words or digits (`twenty five`, `1.5`, `a hundred`); `for`/`to` count as 4/2 only straight before a unit
("timer for minutes" = 4 min). The n-best: every hypothesis is parsed and the most concrete command wins (a known
command, then a tap on something on screen, then a timer without a length, then unparsed); ties keep the recognizer's
order.

**Privacy.** Transcripts are personal: they go to the local event log only. They leave the phone only as the phrase
decider's input when the user chose a model decider (`model`, `hybrid`, `escalate`) and the grammar did not handle
them.

**Events.** `listening{state: open, window_ms, mode, engine, recognizer}` →
`asr{event: closed, why (final | no speech | timeout | error: ... | unavailable | cancelled: ...), engine, recognizer,
status, n_best, confidence, partial, partials, peak_db, ready_ms, ms, mic_yielded}` →
`phrase_parse{source, heard, hypothesis, command, parses, mode, window, parse_ms}` → `exec{n, action: open_app | set_timer | volume, ...}`, or `swipe_plan` + `decision` per swipe, or
`state` + `decision` (navigation, `path: local`), or `target_match{n, query, targets, result, top}` + `target` /
`choice`, or the usual `resolve` chain. Also `asr{engine}` and `asr{event: check, pack, status, info}`.

### Typing by voice

In a listen window (`pop pop`), with the phone's on-device recognizer (never online: `asr_allow_online` is not
changed) and the phone mic (`VoiceTyping.kt`):

- **`type <text>` / `write <text>`** types `<text>` into the box with input focus: at its cursor (a selection is
  replaced, as a keyboard would), or at the end when it has none; a space is added where a word would run into the
  text around it. The words are the recognizer's own, trimmed; only `comma`, `period`, `question mark` and `new line`
  become `,` `.` `?` and a line break. **How:** `ACTION_SET_TEXT` with the box's whole new text, then
  `ACTION_SET_SELECTION` to put the cursor after it; not a paste, which would overwrite the user's clipboard. Nothing
  presses send, enter or an IME action, so nothing is ever submitted or sent.
- **`dictate` / `start dictation`** starts dictation: each utterance is typed as above (a space between utterances),
  and nothing said is parsed as a command except the stop phrase. It stops on about 4 s without speech, a sound from the
  device after a pause of at least `dictate_speech_hold_ms` (default 1000, 200-3000) since the last recognized words
  (that sound is not acted on; one sooner is the user speaking, which the Pico hears too: ignored,
  `dictate{event: ignored_sound, sequence, since_words_ms}`), saying `stop dictation` (the words before it in that utterance are typed), or
  after 2 minutes; also on disarm, pause, `reset`, the box going away, or a recognizer problem. The mic is yielded once
  for the session; each utterance has its own recognizer. The badge shows the listening face while dictating.
- **Refused**, with the toast and nothing typed: no focused editable box (`no text box selected`), a password box, a
  box that would overflow its limit, and a system dialog in front (`SystemDialog`: `refused: system dialog`).
  `type` alone: toast `say what to type`.

**Events.** `phrase_parse{source, command: "type (N chars)" | dictate | "stop dictation", mode, window}` →
`exec{n, action: type_text, ok, how (set_text | why not), chars, text?}`; dictation:
`dictate{event: start | utterance | ignored_sound | stop | refused, why, chars, utterances?, status?, text?}` (`why` of a stop:
`silence`, `sound`, `stop phrase`, `time limit`, `disarm`, `pause`, `reset`, `no text box selected`, `recognizer: ...`).
The typed words (`text`, and `n_best` in the window's `asr{event: closed}`) are logged **only** with `log_typed_text`
on; otherwise `n_best` reads `(typing: not logged)`.

## Intent cursor mode: the `target` question

In cursor mode the user can name an on-screen element ("the subscriptions tab") instead of steering the cursor there.

1. **Trigger.** A long hiss (>= 700 ms, `CursorListen.LONG_HISS_MS`) in cursor mode opens the listening window
   (`Decision("listen_for_phrase", "app:cursor-listen")`). `schema.CURSOR_ACTIONS` has no listen option and the
   generator never produces it, so the **app** handles this and it is never sent to the action model. The long hiss runs
   before the not-deliberate gate (which rejects a long hiss). A short hiss is back; a cursor rule on `["hiss"]` applies
   only to short hisses. Cursor mode never waits: a click taps at once.
2. **Phrase.** From the phone's recognizer or a message's `phrase` (*Spoken phrases*). In cursor mode a phrase that is
   not a command names an element: it is matched by name first (`TargetMatcher`, no model); only when nothing on
   screen matches, and the decider is not `rules`, it becomes a `target` question as below. Matching treats "1" = "one"
   = "01" = "first" (up to 20), abbreviates a letter + number ("lesson 6" ~ "L06"/"L6", "chapter 3" ~ "Ch3"/"C3",
   "unit 2" ~ "U2", "l 6" ~ "L06"), and scores a query that names a row's label **and** its context (the nearest
   indented parent, e.g. "01 Vocabulary · L06") above the label alone.
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
   - otherwise: numbered highlights on the (up to) 3 most probable elements, #1 selected, drawn like the cursor mode's
     snap-to-element selection (corner brackets in the snap ink/paper, a number badge 1..N on each). `rise` = next,
     `fall` = previous (both wrap), a **click** (a pop counts as a click) = tap the selected one, `hiss` = cancel. The mic also listens on
     its own (the same listening window as `click click click`): a spoken **number** ("2", "two", "open 2", "the second one") taps that
     candidate, "cancel"/"never mind" cancels, anything else narrows — re-ranking only the current candidates by the
     phrase (label + context words, the same matcher rules). One clear winner is tapped, several remain shown
     renumbered while it keeps listening, none matches → "no match, say a number" (the choice stays). A phrase that
     names no candidate but parses to a concrete command ("go home") cancels the choice and runs normally; with a model
     decider a narrowing phrase that leaves several goes to the model's `target` question with the phrase and the
     remaining options. No input for 8000 ms cancels; any input restarts that timer. A mode change, disarm, reset or new
     phrase also cancels. Other sounds are ignored while choosing; sounds failing the not-deliberate gate (talking
     etc.) are ignored. Choice events log `spoken_pick`, `spoken`, `narrowed` and `no_match` with the spoken `text`.
   - With `decider = rules` there is no model to ask: toast, and `target{result: "no model (decider=rules)"}`.
   - With `decider = escalate` the cloud answers first. Its answer has no probabilities (`unscored`), so it always
     takes the highlight path with the one element: a click or `pop` taps it, `hiss` cancels.

## Personalization: enrolled sounds rewrite the line

Design: `wiki/personalization.md`. The device sends a fingerprint with each sound (`features`, above). The app compares it
with the user's enrolled examples and rewrites the sound line **before** sequencing and before any decider sees it.

**Enrollment.** Per profile, any number of classes, each `custom` (a sound the user invented and named), `ignore`
(a sound that must never act: a sneeze, a laugh, a kettle) or `gesture` (the user's own rise, pop, ...), with 3–10
examples. Classes with fewer than 3 examples are stored but not matched. Examples are recorded on the PC for now and
pushed with `suite/enroll.py` (the `enroll_*` ops), or recorded on the phone (*Gesture training*, below). There is one
store per profile and mic source, `files/enroll/<profile>@<source>.json` in app-private storage (`source` = `pico`,
`phone`, `usb`); matching uses the current sound source's store. A store from before (`files/enroll/<profile>.json`) is
renamed, once, to the store of the sound source that is current when it is first loaded (logged
`enroll{change: migrate, from, to}`).

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
   `match{id, i, profile, result, class, nearest, distance, threshold, dtw, dtw_threshold, reason, label, new_label, line, floors, relabel, trusted, dist, skipped, gated}`
   (`relabel{from, to}` and `dist`: a gesture class relabelled the sound; `trusted: true`: it agreed with the extractor).

**Rewrite:**

| match | sound line | sequence label |
|---|---|---|
| custom `meow` | `my sound "meow"; duration <bucket>; loudness <bucket>` (the extractor's buckets; a pop/click line, which has no duration, gets `very short (under 150 ms)`) | `my:meow` |
| ignore | the extractor's line with `sounds like one of my ignore sounds` | unchanged |
| gesture `arch`, the extractor said `dip` (or `unknown`, ...) | the arch's normal line, keeping the measured fields: `hum that rises then falls; pitch change <kept, or from pitch16>; duration <kept>; tone <kept>; loudness <kept>; sounds like <kept>` (pop/click: `<shape>; instant sound; loudness; sounds like`, hiss: `a hiss; duration; loudness; sounds like`; flat: pitch change always small) | `arch` |
| gesture `arch`, the extractor also said `arch` | unchanged (logged `trusted: true`) | unchanged |
| none, skipped | unchanged | unchanged |

**Gesture relabel** ([train], 2026-09-27; `wiki/personalization.md`: a re-recorded gesture becomes "the normal gesture
line, now trusted"). Only an **active** `gesture` class (3+ examples) of the **current sound source's** store can
relabel, and only within its reject threshold (plus the DTW test for a contour). Custom and ignore keep their
precedence: the nearest class decides, whatever its kind. A relabelled line is an ordinary gesture line, so every
decider and binding treats it as that gesture. `config {enroll_gesture_relabel: false}` turns it off (the match is
still logged). The gesture trainer sees the extractor's own labels (its takes are taken before this step).
A **gated** sound (the message's `gated[i]`, set by the phone mic's media gate and media-hiss rule) is never rewritten, by
any class kind: a trained pop or click must not turn a deliberately `unknown` media sound back into an action. The match
is still logged, with `skipped: "gated"` and `gated: "<reason>"`.

**Deciding.** The model has no training data for these lines until data v6, so:
- a sound that `sounds like one of my ignore sounds` is always `none`, decided locally (source `personal:ignore-sound`);
- a custom sound is decided locally by the rule table (source `personal:custom-sound -> ...`): a fixed rule
  `{"sound": "my:meow", "action": "open_camera"}` (in `global`, `app:<pkg>` or `cursor`) runs its action, and an
  unbound custom sound is `none`. `"sound": "my:meow"` is shorthand for `"phrase": ["my:meow"]`; custom labels may also
  appear inside longer `phrase` sequences;
- only a plain-language rule (`kind: "rule"`) bound to exactly that sequence sends it to the model.

Fixed rules on custom sounds are not shown to the model under "my rules:".

## Gesture training

<!-- [train] GestureTraining.kt, ui/lib/src/train_screen.dart; user decision 2026-09-27 -->
Design: `wiki/personalization.md`. The user records their own version of every gesture, with its variations, into
the enrollment store of the **current sound source** (class kind `gesture`, named after the gesture, e.g. `arch`).
It is separate from the voice cursor's setup and resumable: one card per gesture, each done, stopped and redone on
its own; every accepted take is stored at once.

**Plan** (`TrainPlan`, 48 takes per source; a pop counts as a click, 2026-09-28, so the discrete gestures are click and
hiss). Each take is a *cell*:

| gesture | cells | takes |
|---|---|---|
| rise, fall, arch, dip | `hum`\|`whistle` × start `low`\|`high` × `slow` (~1.5 s)\|`quick` (~0.5 s): ids `hum-low-slow`, ... | 8 |
| flat | `hum`\|`whistle` × note `low`\|`high` × `short`\|`long`: ids `whistle-high-long`, ... | 8 |
| click, hiss | `soft`\|`loud` × 2: ids `soft-1`, `soft-2`, `loud-1`, `loud-2` | 4 |

Each cell has a prompt ("Whistle a QUICK rise, starting LOW", "Click your tongue LOUDLY (2 of 2)") and a hint.

**A take** (`GestureTrainer`). While a round is open, every sound of the current source goes to it and none acts
(outside a recording they are dropped: `ignored{reason: "gesture training (not recording)"}`; hold messages too). A
take records from `train_record` until 0.9 s after its first sound (so a split arch arrives whole), or fails after
8 s with nothing. It is judged against its cell (`TrainJudge`), in this order; the first reasons found are shown:

| check | reason code | e.g. |
|---|---|---|
| a sound was heard | `nothing` | "Heard nothing in 8 s." (sounds heard but dropped by the mic: "Heard 3 sounds, all below the level gate.") |
| exactly one sound | `count` | "Heard 2 sounds (rise then fall): make it one unbroken sound." |
| it carries an fp1 fingerprint | `features` | |
| the extractor counted it as a gesture (not `unknown`) | `label` | "Canti did not count that as a gesture (too quiet, too short, or media playing): ..." |
| then the tolerant grade (below); the FIRST miss gives the one reason: PITCH | `pitch` | "It started too high: start LOW, near the bottom of your range." |
| SHAPE | `shape` | "Heard a dip (down then up): an arch goes up then down." |
| LENGTH | `speed` | "It took 1.6 s: a QUICK dip takes about half a second (at most 1.0 s)." |
| SOUND | `tone` | "Heard a hum (about 220 Hz): a whistle is 600 Hz or higher. Whistle it." (a low hum with no pitch: "..., a little above your very lowest note.") |
| LOUD | `loud` | "Too quiet for Canti: a little louder." |

Also `blocked` (the take could not start: paused, not armed, cursor mode, mic not listening, Canti device not
connected) and `store` (the store refused it). Nothing is skipped or recorded again without a command.

**Tolerant grade** (E9 §9b, `ShapeGrade`). The judge now grades the take against the wanted shape with thresholds
*looser* than the extractor's own classifier (`flat_max_range_st` 1.5, `shape_min_st` 1.0 in `extractor/config.py`),
and a *near* miss is a pass (shown `~`); only a clear `miss` fails. Each check is `{id, label, state: ok|near|miss|pending,
value, want}`, in this order, only the ids that apply:

| id | ok | near | miss |
| --- | --- | --- | --- |
| `PITCH` | start note within 3 st of the mark (low: HOME−2 st, so ok at/below HOME+1 st; high: HOME+2 st, so ok at/above HOME−1 st; home: ±3 st), on the voice range for a hum and the WHISTLE range for a whistle | within 5 st | further (no scale → `pending`, which passes) |
| `SHAPE` | the extractor labelled it the wanted gesture; or rise/fall net move ≥ ±0.7 st; arch/dip peak/trough ≥ 0.7 st above/below both ends; flat range ≤ 2.0 st (a single point ≥ 5 st off both neighbours, an octave error, is ignored) | ≥ 0.4 st (flat ≤ 3.0 st) | less; discrete = the right label (click/hiss), else miss |
| `LENGTH` | quick/short ≤ 1.0 s; slow/long ≥ 0.8 s; untagged 0.2–2.5 s (none for click/hiss) | ≤ 1.4 s / ≥ 0.6 s / ≤ 4 s | further |
| `SOUND` | hum/whistle as tagged (whistle ≥ 600 Hz: ok ≥ 660, hum ok < 540); unpitched stays unpitched (or the extractor gave it the wanted discrete label) | within 10 % of 600 Hz | the other band / pitched when unpitched |
| `LOUD` | level gate passed and not clipped (training takes carry no level yet: always ok) | within 3 dB of the gate | gated / clipped / too quiet |
| `COUNT` | (combos) the right number of sounds | — | wrong number |
| `GAP` | (combos) the gap within `gap_s` ± 0.6 s | — | outside |

A pass = no `miss`. The store keeps a passing take **even when the extractor label differs** (the meta gets
`label_mismatch: true` + the heard label + `confirmed: false`); Personal matching and relabel skip it until the user
confirms it via `train_confirm {id, keep}` (`keep: true` → `confirmed: true`; `keep: false` → deleted). The flag is
in the store file, so it holds across restarts. `train_status` carries `unconfirmed: [{id, gesture, heard, pos}]` for the
review screen. `train_keep` ("keep it anyway") stays for a take whose only miss is the shape (a contour take needs a
pitch track); a kept take the extractor labelled otherwise is held the same way. After a pass the next UNDONE cell of
the round (after this one, then one the arrows jumped over; not a skipped one) starts recording 1.2 s later and the
status is pushed, unless any command other than `train_status` came first.

**Live grade.** `live.checks` is the same grade on the take's live trace so far: `pending` until there is enough data
(PITCH after 150 ms voiced, the start being the median of the first 8 voiced ticks; SHAPE after 60 % of the wanted
length voiced; LENGTH always pending live).

**Commands** (the `ai.vox/train` channel, and the debug socket's ops of the same names). All answer the status map;
a refused one adds `error`.

| method | args | effect |
|---|---|---|
| `train_status` | `source?` | the status (of `source`'s store; default the current one) |
| `train_start` | `gesture`, `cell?`, `source?` | opens a round: the gesture's missing cells, or only `cell` (a redo, replacing its example). `gesture` is folded (`SoundFold.label`): an old UI's `"pop"` opens the click card. `source` must be the current sound source. Refused when every cell is recorded, or the class would exceed 10 examples |
| `train_record` | | records the current cell (state `ready`, `failed` or `passed`) |
| `train_retry` | | records the failed cell again (state `failed` only) |
| `train_skip` | | leaves the cell unrecorded; the next one waits in `ready` (it does not record by itself) |
| `train_keep` | | stores a take that failed only on its shape |
| `train_goto` | `gesture`, `cell`, `source?` | switches the current take to that cell at any time (an in-flight take is dropped, a stored take stays; a recorded cell is recorded again, replacing its example); `gesture` is folded (`SoundFold.label`). The header arrows ◀ ▶ use it to move over the whole plan, crossing gestures. With no round open (the hub's rows) it opens one. Refused while blocked (`error` = the blocker) |
| `train_confirm` | `id`, `keep`, `source?` | confirms a `label_mismatch` take (`keep: true` → `confirmed: true`) or deletes it (`keep: false`). Only a take stored with `label_mismatch` has an addressable `id` (`meta.id`, unique in the store) |
| `train_next` | `record?` (default true) | after a stored take: the next cell (recording at once), or `done` after the last |
| `train_cancel` | | ends the round (stored takes stay). Also on a sound-source change, UI close, or 5 min without a command |
| `train_delete` | `gesture`, `cell?`, `source?` | soft-deletes the gesture's class (Delete / redo) or one cell's example, in any source's store: the removed example(s) move to that source's trash (`train_trash_<source>`, a JSON file per profile and source), newest first, at most 20 entries (the oldest drop off), as `{id, gesture, cell, examples (JSON), t}`. The reply gains `undo_id` (the entry's `id`). `gesture` is NOT folded: `{gesture: "pop"}` with no cell soft-deletes a legacy `gesture:pop` class if one exists (never the click class), otherwise it is the usual error. A legacy whole-class delete (E10B) is trashed the same way |
| `train_undelete` | `id`, `source?` | puts a trashed delete back, only if that cell has no example now (else `error: "recorded again since"`); a whole-class delete comes back whole. The entry is removed from the trash |
| `train_trash_clear` | `source?` | empties a source's trash |

**States:** `ready` (the prompt; RECORD) → `recording` → `passed` (stored; NEXT) or `failed` (the reason; RETRY /
SKIP / KEEP ANYWAY) → ... → `done`.

**Status map** (`train_status`): `active`, `source` (whose cards), `current_source`, `profile`, `live_trace` (the
source gives live pitch ticks: phone / USB mic, not the Pico), `blocked` (why a take cannot start now, or null), `blocked_action` (the one fix for it: `resume` | `gesture_mode`, or null),
`done`, `total` (48), `sources{pico|phone|usb: {done, total}}`, `gestures[{name, kind (contour|discrete), done, total,
examples, extra (examples not from training), active (3+), kept, cells[{id, prompt, done, tags}]}]`, and `session`
(null when no round is open): `source`, `gesture`, `state`, `cell`, `prompt`, `hint`, `tags`, `index`, `count`,
`next_prompt`, `reason`, `reasons` (codes), `can_keep`, `heard{label, line, sounds, labels, dur_ms, f0_hz, start_hz,
tone, loudness, pitch16, shape}`, `heard_n`, `left_ms`, `live{trace_hz (one per 20 ms tick, null = unvoiced, at most
250), level_db, pitch_hz, checks (the provisional grade)}`, `result{checks (the final grade)}`, `expect{sequence,
start, span_st: 4, tol_st: 1.5, dur_s (quick 0.6 / slow 1.5 / untagged 0.8), gap_s: null}`, `pos{i, n, gesture_i,
gesture_n}` (1-based: i of n = 52 over the whole plan in TrainPlan order, gesture_i of gesture_n within the gesture),
`can_prev`, `can_next`, `passed`, `skipped`, `kept`. Top level also carries `scale{low_hz, home_hz, high_hz}|null` (the
current source's saved calibration: the voice range, or the whistle range while the current cell is a whistle; null
when not calibrated) and `unconfirmed[{id, gesture, heard, pos}]` (`pos`: the example's index in its class), plus
`legacy: [{gesture: "pop", n}]` when a legacy `gesture:pop` class is in the store (so a UI can offer deleting it).

**Stored example.** `enroll_add` semantics into class `gesture:<name>` of the round's source, with
`meta{train: 1, cell, id, <tags: tone, pitch, speed|length | loudness, take>, heard{label, dur_ms, f0_hz, start_hz, tone,
loudness}, kept?, label_mismatch?, confirmed?, at_ms}`. A cell counts as recorded when an example of the class carries its
`meta.cell`; a take whose `label_mismatch` is set but `confirmed` is not is held out of matching and relabel.

**What it changes.** From 3 takes a gesture class takes part in matching (*Personalization*): a sound it matches
that the extractor labelled otherwise becomes that gesture (`match{result: gesture, relabel{from, to}}`), unless
`enroll_gesture_relabel` is off.

**Events:** `train{event: start{source, gesture, cells, cell}, take{gesture, cell, result: passed | failed, reason,
reasons, label, can_keep, dur_ms, f0_hz, source}, skip{gesture, cell, reason}, keep{gesture, cell, heard, line,
reason, source}, delete{source, gesture, cell}, done{gesture, source, passed, kept, skipped}, end{by, gesture, source,
passed, kept, skipped, state}}`, and `enroll{change, source, ...}` for each store change.

**Live trace.** For the phone / USB mic the trainer turns the native 20 ms ticks on while a round is open
(`PhoneMicSource.setTrainTicks`, independent of the joystick's); the Pico sends no ticks, so the screen shows the
take's `pitch16` after it instead.
