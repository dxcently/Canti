import 'dart:async';

import 'package:flutter/services.dart';

import 'backend.dart';
import 'calibration.dart';

/// [VoxBackend] over platform channels to the Kotlin app (android/app/.../UiBridge.kt).
///
/// - `ai.vox/backend` (method channel): `status`, `setPaused {paused}` and `connectDevice` return the status map
///   ([VoxStatus.fromMap]); `deviceCommand {armed?, mode?, sleep?}` returns once the device confirmed or the command
///   failed ([DeviceResult.fromMap]); `openLegacySettings` opens the native settings screen. Pairing:
///   `requestBluetooth` (answers with the status map after the permission dialog), `enableBluetooth`,
///   `openAppSettings`, `launchRoute` (the screen the app was opened for, once, or null). Kotlin calls `openRoute
///   {route}` on this channel when a running UI should show a screen ([routeRequests]).
///   Voice cursor: `cursorSettings` and `setCursorSettings {cursor_speed?, cursor_pitch_sens?}` answer
///   `{cursor_speed, cursor_pitch_sens}` (like `scrollStep` / `setScrollStep`); `levelGateSettings` and
///   `setLevelGateSettings {level_gate?, level_gate_offset_db?}` answer `{level_gate, level_gate_offset_db}`;
///   `calib_start {source, steps?}`, `calib_step {step}`, `calib_redo {step}`, `calib_retry`, `calib_skip`, `calib_save`,
///   `calib_cancel` each answer the `calib_status` map; `calib_get {source}` answers the saved profile or null.
///   Kotlin calls `calib_status {map}` on this channel about every 100 ms while a calibration is active and on every
///   change ([calibStatus]).
/// - `ai.vox/events` (event channel): one event-log JSON line per event.
class ChannelBackend implements VoxBackend {
  ChannelBackend({MethodChannel? methods, EventChannel? events})
      : _methods = methods ?? const MethodChannel(methodsName),
        _events = events ?? const EventChannel(eventsName) {
    _methods.setMethodCallHandler((call) async {
      if (call.method == 'openRoute' && call.arguments is String) _routes.add(call.arguments as String);
      if (call.method == 'calib_status') _calibPush(call.arguments);
      return null;
    });
  }

  static const methodsName = 'ai.vox/backend';
  static const eventsName = 'ai.vox/events';

  final MethodChannel _methods;
  final EventChannel _events;
  Stream<VoxEvent>? _stream;
  final _routes = StreamController<String>.broadcast();

  @override
  Future<VoxStatus> status() async =>
      VoxStatus.fromMap(await _methods.invokeMapMethod<Object?, Object?>('status') ?? const {});

  @override
  Stream<VoxEvent> events() =>
      _stream ??= _events.receiveBroadcastStream().map((e) => VoxEvent.fromJson(e as String)).asBroadcastStream();

  @override
  Future<VoxStatus> setPaused(bool paused) async =>
      VoxStatus.fromMap(await _methods.invokeMapMethod<Object?, Object?>('setPaused', {'paused': paused}) ?? const {});

  @override
  Future<DeviceResult> deviceCommand({bool? armed, String? mode, bool sleep = false}) async =>
      DeviceResult.fromMap(await _methods.invokeMapMethod<Object?, Object?>('deviceCommand', {
            'armed': ?armed,
            'mode': ?mode,
            if (sleep) 'sleep': true,
          }) ??
          const {});

  @override
  Future<VoxStatus> connectDevice() async =>
      VoxStatus.fromMap(await _methods.invokeMapMethod<Object?, Object?>('connectDevice') ?? const {});

  @override
  Future<VoxStatus> requestBluetooth() async =>
      VoxStatus.fromMap(await _methods.invokeMapMethod<Object?, Object?>('requestBluetooth') ?? const {});

  @override
  Future<void> enableBluetooth() => _methods.invokeMethod<void>('enableBluetooth');

  @override
  Future<void> openAppSettings() => _methods.invokeMethod<void>('openAppSettings');

  @override
  Future<String?> launchRoute() => _methods.invokeMethod<String>('launchRoute');

  @override
  Stream<String> routeRequests() => _routes.stream;

  @override
  bool get hasLegacySettings => true;

  @override
  Future<void> openLegacySettings() => _methods.invokeMethod<void>('openLegacySettings');

  // --- the voice cursor ----------------------------------------------------------------------------------------------

  @override
  Future<CursorSettings> cursorSettings() async =>
      CursorSettings.fromMap(await _methods.invokeMapMethod<Object?, Object?>('cursorSettings'));

  @override
  Future<CursorSettings> setCursorSettings({double? speed, double? pitchSens}) async =>
      CursorSettings.fromMap(await _methods.invokeMapMethod<Object?, Object?>('setCursorSettings', {
        'cursor_speed': ?speed,
        'cursor_pitch_sens': ?pitchSens,
      }));

  @override
  Future<LevelGateSettings> levelGateSettings() async =>
      LevelGateSettings.fromMap(await _methods.invokeMapMethod<Object?, Object?>('levelGateSettings'));

  @override
  Future<LevelGateSettings> setLevelGateSettings({bool? enabled, int? offsetDb}) async =>
      LevelGateSettings.fromMap(await _methods.invokeMapMethod<Object?, Object?>('setLevelGateSettings', {
        'level_gate': ?enabled,
        'level_gate_offset_db': ?offsetDb,
      }));

  @override
  Future<void> calibStart(String source, {List<String>? steps}) =>
      _calib('calib_start', {'source': source, 'steps': ?steps});

  @override
  Future<void> calibStep(String step) => _calib('calib_step', {'step': step});

  @override
  Future<void> calibRedo(String step) => _calib('calib_redo', {'step': step});

  @override
  Future<void> calibRetry() => _calib('calib_retry');

  @override
  Future<void> calibSkip() => _calib('calib_skip');

  @override
  Future<void> calibSave() => _calib('calib_save');

  @override
  Future<void> calibCancel() => _calib('calib_cancel');

  @override
  Future<CalibResult?> calibGet(String source) async =>
      CalibResult.fromMap(await _methods.invokeMethod<Object?>('calib_get', {'source': source}));

  final _calibOut = StreamController<CalibStatus>.broadcast();

  /// Kotlin's `calib_status` calls, plus each command's answer (the status after it).
  @override
  Stream<CalibStatus> calibStatus() => _calibOut.stream;

  void _calibPush(Object? m) {
    if (m is Map && m.containsKey('active')) _calibOut.add(CalibStatus.fromMap(m.cast<Object?, Object?>()));
  }

  /// Sends a calib_* command. The service reports a command error inside its answer (`error`), not as a platform
  /// exception, so it is thrown here: the flow sees it at once, even after [CalibFlow] stopped following pushes
  /// (a failed `calib_save` must not read as saved).
  Future<void> _calib(String method, [Map<String, Object?>? args]) async {
    final r = await _methods.invokeMethod<Object?>(method, args);
    _calibPush(r);
    if (r is Map && r['error'] != null) throw CalibCommandError('${r['error']}');
  }
}

/// A calib_* command the service refused (its answer's `error`).
class CalibCommandError implements Exception {
  CalibCommandError(this.message);
  final String message;
  @override
  String toString() => message;
}
