import 'dart:async';
import 'dart:convert';

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

  static const offline = VoxStatus(service: false, armed: false, paused: false, mode: 'gesture');

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
  }) =>
      VoxStatus(
        service: service,
        armed: armed ?? this.armed,
        paused: paused ?? this.paused,
        mode: mode ?? this.mode,
        app: app ?? this.app,
        decider: decider,
        bleState: bleState ?? this.bleState,
        bleDevice: bleDevice,
        bleHint: bleHint != null ? bleHint() : this.bleHint,
        deviceState: deviceState != null ? deviceState() : this.deviceState,
        deviceReady: deviceReady ?? this.deviceReady,
        deviceArmed: deviceArmed ?? this.deviceArmed,
        deviceMode: deviceMode ?? this.deviceMode,
        deviceWaiting: deviceWaiting,
        deviceError: deviceError != null ? deviceError() : this.deviceError,
        vocab: vocab,
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

  /// Connects to the remembered device again (after the user acted on a pairing hint). Returns the new state.
  Future<VoxStatus> connectDevice();

  /// Whether [openLegacySettings] does anything here (the native settings screen exists only on Android).
  bool get hasLegacySettings;

  /// Opens the native settings screen (decider, endpoint, API key, permissions) until Flutter screens replace it.
  Future<void> openLegacySettings();
}
