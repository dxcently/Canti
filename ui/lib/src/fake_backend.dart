import 'dart:async';

import 'backend.dart';

/// An in-memory [VoxBackend] for widget tests and the Linux desktop runner. It simulates a connected VOX device that
/// confirms every command (or, with [confirmDevice] false, never answers, so commands fail after [deviceTimeout]).
/// With [demo], it also plays a short loop of made-up events (a sound, its decision and the action) every [demoEvery],
/// so the screen has something to show.
class FakeBackend implements VoxBackend {
  FakeBackend({
    VoxStatus initial = const VoxStatus(
      service: true,
      armed: true,
      paused: false,
      mode: 'gesture',
      app: 'org.schabi.newpipe',
      decider: 'hybrid',
      bleState: 'ready',
      bleDevice: 'D8:3A:DD:00:00:01',
      deviceState: 'listening',
      deviceReady: true,
      deviceArmed: true,
      deviceMode: 'gesture',
      vocab: 'fake',
    ),
    this.demo = false,
    this.demoEvery = const Duration(milliseconds: 1500),
    this.confirmDevice = true,
    this.deviceTimeout = const Duration(milliseconds: 1500),
  }) : current = initial;

  final bool demo;
  final Duration demoEvery;
  final bool confirmDevice;
  final Duration deviceTimeout;

  /// The state [status] answers with; tests may replace it (the screen sees it on its next fetch).
  VoxStatus current;
  final _events = StreamController<VoxEvent>.broadcast();
  Timer? _timer;
  final _clock = Stopwatch()..start();
  int _n = 0;
  int legacyOpened = 0;
  int connects = 0;

  /// Every device command received, as its CONFIG JSON fields.
  final commands = <Map<String, Object?>>[];

  /// Sends one event to the listeners (tests).
  void emit(String name, [Map<String, Object?> fields = const {}]) {
    _events.add(VoxEvent(name, _clock.elapsedMilliseconds, Map.of(fields)));
  }

  @override
  Future<VoxStatus> status() async => current;

  @override
  Stream<VoxEvent> events() {
    if (demo && _timer == null) _timer = Timer.periodic(demoEvery, (_) => _demoStep());
    return _events.stream;
  }

  @override
  Future<VoxStatus> setPaused(bool paused) async {
    if (paused != current.paused) {
      current = current.copyWith(paused: paused);
      emit('pause', {'state': paused ? 'paused' : 'resumed', 'by': 'app'});
    }
    return current;
  }

  @override
  Future<DeviceResult> deviceCommand({bool? armed, String? mode, bool sleep = false}) async {
    final label = sleep ? 'sleep' : [if (armed != null) armed ? 'arm' : 'pause', if (mode != null) 'mode $mode'].join(' + ');
    if (!current.deviceReady) {
      emit('device_cmd', {'cmd': label, 'result': 'failed', 'error': 'no device connected'});
      return DeviceResult(ok: false, result: 'failed', cmd: label, error: 'no device connected');
    }
    commands.add({'v': 1, 'armed': ?armed, 'mode': ?mode, if (sleep) 'sleep': true});
    emit('device_cmd', {'cmd': label, 'result': 'sent'});
    if (!confirmDevice) {
      await Future<void>.delayed(deviceTimeout);
      final why = 'no confirmation from the device within ${deviceTimeout.inMilliseconds} ms';
      current = current.copyWith(deviceError: () => '${label[0].toUpperCase()}${label.substring(1)} failed: $why.');
      emit('device_cmd', {'cmd': label, 'result': 'failed', 'error': why});
      return DeviceResult(ok: false, result: 'failed', cmd: label, error: why);
    }
    if (sleep) {
      current = current.copyWith(
          armed: false, deviceArmed: false, deviceReady: false, deviceState: () => 'asleep', deviceError: () => null);
      emit('msg', {'source': 'ble', 'armed': false, 'sleeping': true});
      emit('arm', {'state': 'disarmed', 'by': 'device (going to sleep)'});
      emit('ble', {'what': 'asleep'});
    } else {
      final a = armed ?? current.deviceArmed ?? false;
      final m = mode ?? current.deviceMode ?? current.mode;
      current = current.copyWith(
          armed: a,
          mode: m,
          deviceArmed: a,
          deviceMode: m,
          deviceState: () => a ? 'listening' : 'awake – paused',
          deviceError: () => null);
      emit('msg', {'source': 'ble', 'mode': m, 'armed': a});
      if (armed != null) emit('arm', {'state': a ? 'armed' : 'disarmed', 'by': 'device'});
      if (mode != null) emit('mode', {'mode': m});
    }
    emit('device_cmd', {'cmd': label, 'result': 'confirmed', 'applied': true});
    return DeviceResult(ok: true, result: 'confirmed', cmd: label);
  }

  @override
  Future<VoxStatus> connectDevice() async {
    connects++;
    current = current.copyWith(bleHint: () => null, deviceState: () => 'connecting', bleState: 'connecting');
    emit('ble', {'what': 'state', 'state': 'connecting'});
    return current;
  }

  @override
  bool get hasLegacySettings => false;

  @override
  Future<void> openLegacySettings() async => legacyOpened++;

  static const _loop = [
    ['rise', 'swipe up'],
    ['fall', 'swipe down'],
    ['pop', 'tap'],
    ['hiss', 'back'],
  ];

  void _demoStep() {
    if (current.hasDevice && !current.deviceReady) return; // an asleep or absent device sends nothing
    final s = _loop[_n % _loop.length];
    _n++;
    emit('msg', {'id': _n, 'source': 'ble', 'mode': current.mode, 'armed': current.armed, 'sequence': s[0]});
    if (!current.active) {
      emit('ignored', {'reason': current.paused ? 'paused (app)' : 'disarmed'});
      return;
    }
    emit('decision', {'n': _n, 'action': s[1], 'source': 'rules', 'confidence': 1.0});
    emit('confirm', {'watch': _n, 'result': 'confirmed (events)'});
  }

  void dispose() {
    _timer?.cancel();
    _events.close();
  }
}
