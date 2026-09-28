import 'dart:async';
import 'dart:convert';

import 'calibration.dart';

/// The service state the UI shows. On Android it comes from the Kotlin accessibility service
/// (`VoxService.uiStatus`, sent over the `ai.vox/backend` method channel); see android/PROTOCOL.md "UI channel".
class VoxStatus {
  const VoxStatus({
    required this.service,
    required this.armed,
    required this.paused,
    required this.mode,
    this.app,
    this.decider,
    this.bleState,
    this.bleDevice,
    this.bleHint,
    this.deviceState,
    this.deviceReady = false,
    this.deviceArmed,
    this.deviceMode,
    this.deviceWaiting,
    this.deviceError,
    this.vocab,
    this.badge,
    this.soundSource,
    this.bleAdapter,
    this.bleMissing = const [],
    this.bleBlocked = false,
    this.bleTarget,
    this.bleTargetName,
    this.bleScan,
    this.asrEngine,
    this.asrStatus,
    this.calibrated,
    this.calibrating = false,
    this.training = false,
    this.bindings,
  });

  /// The accessibility service is running (the other fields are only meaningful then).
  final bool service;

  /// The device's arm state (the last message from the device, or a dropped link).
  final bool armed;

  /// Paused from the phone (this UI): sounds are ignored until resumed, whatever the device says.
  final bool paused;

  /// `gesture` or `cursor`.
  final String mode;

  /// The foreground app's package.
  final String? app;

  /// `rules`, `model` or `hybrid`.
  final String? decider;

  /// The BLE link state (`idle`, `scanning`, `ready`, `waiting`, ...), or null without a BLE source.
  final String? bleState;

  /// The remembered VOX device's address.
  final String? bleDevice;

  /// What the user has to do to get the link back (for example forget a re-flashed device in Bluetooth settings),
  /// or null.
  final String? bleHint;

  /// The VOX device as the status screen names it: `listening`, `awake – paused`, `asleep`, `pairing needed`,
  /// `connecting`, `not connected` or `bluetooth off`; null when no device is set up (phone-only / debug sources).
  final String? deviceState;

  /// The device link is up (encrypted, subscribed): the device can be commanded.
  final bool deviceReady;

  /// The device's own arm state and mode (it owns both), as it last said.
  final bool? deviceArmed;
  final String? deviceMode;

  /// The command waiting for the device's confirmation, if any (`pause`, `arm`, `mode cursor`, `sleep`, ...).
  final String? deviceWaiting;

  /// The last failed device command, e.g. "Pause failed: no confirmation from the device within 1500 ms.".
  final String? deviceError;

  /// A VOX device is set up (connected or not).
  bool get hasDevice => deviceState != null;

  /// The gesture vocabulary digest.
  final String? vocab;

  /// The Canti head's held state as the service shows it on the floating badge (`idle`, `hearing`, `pending`,
  /// `hold-scroll`, `cursor`, `paused`, `off`, `error`; Badge.kt `BadgeStates.label`), or null from an older service.
  final String? badge;

  /// Where Canti hears sounds: `pico` (the Canti device over Bluetooth), `phone` or `usb` (a microphone).
  final String? soundSource;

  /// The phone's Bluetooth: `on`, `off` or `none`.
  final String? bleAdapter;

  /// The Bluetooth runtime permissions not granted yet (Android names, e.g. `android.permission.BLUETOOTH_SCAN`).
  final List<String> bleMissing;

  /// The user refused them with "don't ask again": only the app's settings page can grant them now.
  final bool bleBlocked;

  /// The device being connected (its address) and its advertised name (`VOX-2807`), once one was found.
  final String? bleTarget;
  final String? bleTargetName;

  /// The first-run search: `scanning`, `none found` (the last search ended without a device), or null.
  final String? bleScan;

  /// The service says the Pico is the source and no device is remembered: pairing is the next step.
  bool get needsPairing => service && soundSource == 'pico' && bleDevice == null && !deviceReady;

  static const offline = VoxStatus(service: false, armed: false, paused: false, mode: 'gesture');

  /// The phrase window's speech engine (`android` or `off`, setting `asr_engine`).
  final String? asrEngine;

  /// Whether it can listen: `ready`, `off`, or what the user must fix (`offline speech pack missing`, ...).
  final String? asrStatus;

  /// The voice cursor has a saved calibration for the current sound source (null from a service without one).
  final bool? calibrated;

  /// A calibration run is open now (its sounds are dropped as "calibrating": Canti is deaf until it ends).
  final bool calibrating;

  /// A gesture-training round is open now (its sounds go to the trainer, not to actions).
  final bool training;

  /// The bindings window's picture (null from a service without one, or when the service is off): the effective
  /// sound -> action per mode, resolved on the Kotlin side (`Bindings.kt`), for the current app.
  final VoxBindings? bindings;

  /// Speech needs the user (not `ready`, not `off`).
  bool get asrProblem => asrStatus != null && asrStatus != 'ready' && asrStatus != 'off';

  /// Whether sounds act right now.
  bool get active => service && armed && !paused;

  factory VoxStatus.fromMap(Map<Object?, Object?> m) => VoxStatus(
        service: m['service'] == true,
        armed: m['armed'] == true,
        paused: m['paused'] == true,
        mode: (m['mode'] as String?) ?? 'gesture',
        app: m['app'] as String?,
        decider: m['decider'] as String?,
        bleState: m['ble_state'] as String?,
        bleDevice: m['ble_device'] as String?,
        bleHint: m['ble_hint'] as String?,
        deviceState: m['device_state'] as String?,
        deviceReady: m['device_ready'] == true,
        deviceArmed: m['device_armed'] as bool?,
        deviceMode: m['device_mode'] as String?,
        deviceWaiting: m['device_waiting'] as String?,
        deviceError: m['device_error'] as String?,
        vocab: m['vocab'] as String?,
        badge: m['badge'] as String?,
        soundSource: m['sound_source'] as String?,
        bleAdapter: m['ble_adapter'] as String?,
        bleMissing: [for (final x in (m['ble_missing'] as List<Object?>?) ?? const []) '$x'],
        bleBlocked: m['ble_blocked'] == true,
        bleTarget: m['ble_target'] as String?,
        bleTargetName: m['ble_target_name'] as String?,
        bleScan: m['ble_scan'] as String?,
        asrEngine: m['asr_engine'] as String?,
        asrStatus: m['asr_status'] as String?,
        calibrated: m['calibrated'] as bool?,
        calibrating: m['calibrating'] == true,
        training: m['training'] == true,
        bindings: VoxBindings.fromMapOrNull(m['bindings']),
      );

  VoxStatus copyWith({
    bool? armed,
    bool? paused,
    String? mode,
    String? app,
    String? bleState,
    String? Function()? bleHint,
    String? Function()? deviceState,
    bool? deviceReady,
    bool? deviceArmed,
    String? deviceMode,
    String? Function()? deviceError,
    String? Function()? bleDevice,
    String? soundSource,
    String? bleAdapter,
    List<String>? bleMissing,
    bool? bleBlocked,
    String? Function()? bleTarget,
    String? Function()? bleTargetName,
    String? Function()? bleScan,
  }) =>
      VoxStatus(
        service: service,
        armed: armed ?? this.armed,
        paused: paused ?? this.paused,
        mode: mode ?? this.mode,
        app: app ?? this.app,
        decider: decider,
        bleState: bleState ?? this.bleState,
        bleDevice: bleDevice != null ? bleDevice() : this.bleDevice,
        bleHint: bleHint != null ? bleHint() : this.bleHint,
        deviceState: deviceState != null ? deviceState() : this.deviceState,
        deviceReady: deviceReady ?? this.deviceReady,
        deviceArmed: deviceArmed ?? this.deviceArmed,
        deviceMode: deviceMode ?? this.deviceMode,
        deviceWaiting: deviceWaiting,
        deviceError: deviceError != null ? deviceError() : this.deviceError,
        vocab: vocab,
        badge: badge,
        soundSource: soundSource ?? this.soundSource,
        bleAdapter: bleAdapter ?? this.bleAdapter,
        bleMissing: bleMissing ?? this.bleMissing,
        bleBlocked: bleBlocked ?? this.bleBlocked,
        bleTarget: bleTarget != null ? bleTarget() : this.bleTarget,
        bleTargetName: bleTargetName != null ? bleTargetName() : this.bleTargetName,
        bleScan: bleScan != null ? bleScan() : this.bleScan,
        asrEngine: asrEngine,
        asrStatus: asrStatus,
        calibrated: calibrated,
        calibrating: calibrating,
        training: training,
        bindings: bindings,
      );

  @override
  String toString() => 'VoxStatus(service: $service, armed: $armed, paused: $paused, mode: $mode, app: $app, '
      'decider: $decider, ble: $bleState $bleDevice, device: $deviceState)';
}

/// The outcome of a device command: confirmed by the device's state message, or failed (refused, write failed, or no
/// confirmation within the timeout).
class DeviceResult {
  const DeviceResult({required this.ok, required this.result, this.cmd, this.error});

  final bool ok;

  /// `confirmed` or `failed`.
  final String result;

  /// `pause`, `arm`, `mode cursor`, `sleep`, ...
  final String? cmd;
  final String? error;

  factory DeviceResult.fromMap(Map<Object?, Object?> m) => DeviceResult(
        ok: m['ok'] == true,
        result: (m['result'] as String?) ?? '?',
        cmd: m['cmd'] as String?,
        error: m['error'] as String?,
      );
}

/// One event-log line (android/PROTOCOL.md "Event log"): `{"ev": name, "t": ms, ...fields}`.
class VoxEvent {
  VoxEvent(this.name, this.t, this.fields);

  final String name;
  final int t;
  final Map<String, Object?> fields;

  factory VoxEvent.fromJson(String line) {
    final o = jsonDecode(line) as Map<String, Object?>;
    final fields = Map<String, Object?>.of(o)
      ..remove('ev')
      ..remove('t');
    return VoxEvent((o['ev'] as String?) ?? '?', (o['t'] as num?)?.toInt() ?? 0, fields);
  }

  /// `key=value` pairs, nulls left out, for one line of the event list.
  String get summary => fields.entries.where((e) => e.value != null).map((e) => '${e.key}=${e.value}').join('  ');
}

/// One resolved binding for the status screen's bindings window: what a sound (or a two-sound combo) does, and where
/// that came from (`default`, `app-only`, `global`, `app` or `cursor`; a user rule is one of the last three).
class VoxBinding {
  const VoxBinding(this.label, this.source, [this.sequence = const []]);

  /// The action's option text (`swipe up`, `back`, `cursor up`, ...: the short label, D186), or `custom rule` / `ignored`.
  final String label;

  /// Where the binding came from; null when unknown.
  final String? source;

  /// The sound sequence; empty for a single sound (those are keyed by sound in [VoxModeBindings.sounds]).
  final List<String> sequence;

  factory VoxBinding.fromMap(Map<Object?, Object?> m, {List<String> sequence = const []}) => VoxBinding(
        (m['label'] as String?) ?? '?',
        m['source'] as String?,
        sequence,
      );
}

/// One mode's bindings: the single sounds (`sound name -> binding`, null = unbound) and the multi-sound combos.
class VoxModeBindings {
  const VoxModeBindings({required this.sounds, required this.combos, this.note});

  /// Sound name (`rise`, `fall`, ... `hiss`) -> its binding, or null when the sound does nothing in this mode.
  final Map<String, VoxBinding?> sounds;

  /// The two-sound combos bound in this mode, in order.
  final List<VoxBinding> combos;

  /// A one-line truth about this mode (the cursor's voice joystick, or that combos do not act), or null.
  final String? note;

  factory VoxModeBindings.fromMap(Map<Object?, Object?> m) => VoxModeBindings(
        sounds: {
          for (final e in (m['sounds'] as Map<Object?, Object?>? ?? const {}).entries)
            '${e.key}': e.value is Map ? VoxBinding.fromMap((e.value! as Map).cast<Object?, Object?>()) : null,
        },
        combos: [
          for (final c in (m['combos'] as List<Object?>? ?? const []))
            VoxBinding.fromMap(
              (c! as Map).cast<Object?, Object?>(),
              sequence: [
                for (final s in ((c as Map)['seq'] as List<Object?>? ?? const [])) '$s',
              ],
            ),
        ],
        note: m['note'] as String?,
      );
}

/// The bindings window's picture, per mode (android `Bindings.kt`, the status map's `bindings` key).
class VoxBindings {
  const VoxBindings({required this.gesture, required this.cursor});

  final VoxModeBindings gesture;
  final VoxModeBindings cursor;

  /// The single sounds shown as glyphs, in order (contours then discrete).
  static const sounds = ['rise', 'fall', 'arch', 'dip', 'flat', 'pop', 'click', 'hiss'];

  factory VoxBindings.fromMap(Map<Object?, Object?> m) => VoxBindings(
        gesture: VoxModeBindings.fromMap((m['gesture'] as Map<Object?, Object?>? ?? const {}).cast<Object?, Object?>()),
        cursor: VoxModeBindings.fromMap((m['cursor'] as Map<Object?, Object?>? ?? const {}).cast<Object?, Object?>()),
      );

  /// Null when the status map has no `bindings` key (an older service, or the service off).
  static VoxBindings? fromMapOrNull(Object? m) => m is Map ? VoxBindings.fromMap(m.cast<Object?, Object?>()) : null;

  /// The fallback picture when the service sends none: the Vocab defaults with no user rules, on the Pico (the same
  /// thing `Bindings.view(Profile.empty(), "", micSource = false)` computes on the Kotlin side).
  static const defaults = VoxBindings(
    gesture: VoxModeBindings(
      sounds: {
        'rise': VoxBinding('swipe up', 'default'),
        'fall': VoxBinding('swipe down', 'default'),
        'arch': VoxBinding('swipe right', 'default'),
        'dip': VoxBinding('swipe left', 'default'),
        'flat': VoxBinding('hold', 'default'),
        'pop': VoxBinding('tap', 'default'),
        'click': null,
        'hiss': VoxBinding('back', 'default'),
      },
      combos: [
        VoxBinding('listen', 'default', ['pop', 'pop']),
        VoxBinding('home', 'default', ['click', 'click']),
        VoxBinding('back', 'default', ['hiss', 'click']),
        VoxBinding('forward', 'app-only', ['click', 'hiss']),
      ],
    ),
    cursor: VoxModeBindings(
      sounds: {
        'rise': VoxBinding('cursor up', 'default'),
        'fall': VoxBinding('cursor down', 'default'),
        'arch': VoxBinding('cursor right', 'default'),
        'dip': VoxBinding('cursor left', 'default'),
        'flat': VoxBinding('stop', 'default'),
        'pop': VoxBinding('click', 'default'),
        'click': null,
        'hiss': VoxBinding('back', 'default'),
      },
      combos: [
        VoxBinding('listen for a name', 'default', ['pop', 'pop']),
      ],
    ),
  );
}

/// Everything the screens need from the phone side. [ChannelBackend] talks to the Kotlin service over platform
/// channels; [FakeBackend] is in-memory, for widget tests and the Linux desktop runner.
abstract class VoxBackend {
  /// The current state.
  Future<VoxStatus> status();

  /// The live event log (a broadcast stream).
  Stream<VoxEvent> events();

  /// Pause (true) or resume (false) from the phone. Returns the new state.
  Future<VoxStatus> setPaused(bool paused);

  /// Commands the VOX device (arm or pause, set the mode, or sleep; `sleep` goes alone). Completes when the device has
  /// confirmed with its state message, or the command failed.
  Future<DeviceResult> deviceCommand({bool? armed, String? mode, bool sleep = false});

  /// Connects to the remembered device again (after the user acted on a pairing hint), or, with none remembered,
  /// searches for a Canti device and connects to the first one found. Returns the new state.
  Future<VoxStatus> connectDevice();

  /// Asks for the missing Bluetooth permissions (the system dialog). Completes with the state after the answer.
  Future<VoxStatus> requestBluetooth();

  /// Asks the system to turn Bluetooth on (its own dialog).
  Future<void> enableBluetooth();

  /// Opens this app's page in the system settings (permissions refused with "don't ask again").
  Future<void> openAppSettings();

  /// The screen the app was opened for (`pair`), once: the badge menu and the sound-source chooser open the pairing
  /// screen this way. Null for a normal start.
  Future<String?> launchRoute();

  /// Screens asked for while the app is running (same values as [launchRoute]).
  Stream<String> routeRequests();

  /// Whether [openLegacySettings] does anything here (the native settings screen exists only on Android).
  bool get hasLegacySettings;

  /// Opens the native settings screen (decider, endpoint, API key, permissions) until Flutter screens replace it.
  Future<void> openLegacySettings();

  // --- the voice cursor ----------------------------------------------------------------------------------------------

  /// The voice cursor's settings (`cursor_speed`, `cursor_pitch_sens`).
  Future<CursorSettings> cursorSettings();

  /// Stores either or both; answers the settings as stored.
  Future<CursorSettings> setCursorSettings({double? speed, double? pitchSens});

  /// The level gate (calibration v2): on / off and its offset, -10..10 dB (+ = stricter).
  Future<LevelGateSettings> levelGateSettings();

  /// Stores either or both (the offset clamped); answers the settings as stored.
  Future<LevelGateSettings> setLevelGateSettings({bool? enabled, int? offsetDb});

  /// Starts a calibration of the voice cursor for a sound source (`phone`, `usb`, `pico`): all 8 steps, or [steps] (an
  /// ordered subset, e.g. a version 1 profile's missing steps). The run starts on its first step.
  Future<void> calibStart(String source, {List<String>? steps});

  /// Records one step: `hum`, `glide`, `vowels` or `pops`.
  Future<void> calibStep(String step);

  /// Records one step again.
  Future<void> calibRedo(String step);

  /// From a failed step: records it again.
  Future<void> calibRetry();

  /// From a failed step (or one not started): keeps its defaults and moves on; the step is listed in `skipped`.
  Future<void> calibSkip();


  /// Keeps the result (the cursor uses it from then on).
  Future<void> calibSave();

  /// Ends the calibration without keeping anything.
  Future<void> calibCancel();

  /// The saved calibration for a source, or null when there is none.
  Future<CalibResult?> calibGet(String source);

  /// The service's `calib_status` pushes (about 10 Hz while a calibration is active, and on every change), and
  /// each calibration command's answer (the status after it).
  Stream<CalibStatus> calibStatus();
}
