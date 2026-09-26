import 'package:flutter/services.dart';

import 'backend.dart';

/// [VoxBackend] over platform channels to the Kotlin app (android/app/.../UiBridge.kt).
///
/// - `ai.vox/backend` (method channel): `status`, `setPaused {paused}` and `connectDevice` return the status map
///   ([VoxStatus.fromMap]); `deviceCommand {armed?, mode?, sleep?}` returns once the device confirmed or the command
///   failed ([DeviceResult.fromMap]); `openLegacySettings` opens the native settings screen.
/// - `ai.vox/events` (event channel): one event-log JSON line per event.
class ChannelBackend implements VoxBackend {
  ChannelBackend({MethodChannel? methods, EventChannel? events})
      : _methods = methods ?? const MethodChannel(methodsName),
        _events = events ?? const EventChannel(eventsName);

  static const methodsName = 'ai.vox/backend';
  static const eventsName = 'ai.vox/events';

  final MethodChannel _methods;
  final EventChannel _events;
  Stream<VoxEvent>? _stream;

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
  bool get hasLegacySettings => true;

  @override
  Future<void> openLegacySettings() => _methods.invokeMethod<void>('openLegacySettings');
}
