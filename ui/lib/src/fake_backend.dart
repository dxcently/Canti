import 'dart:async';
import 'dart:math' as math;

import 'backend.dart';
import 'calibration.dart';

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
    bool? calibAuto,
    this.calibTick = const Duration(milliseconds: 100),
    this.calibPops = 3,
  })  : current = initial,
        calibAuto = calibAuto ?? demo;

  final bool demo;
  final Duration demoEvery;
  final bool confirmDevice;
  final Duration deviceTimeout;

  /// Calibration: with [calibAuto] (default: [demo]) each step plays a made-up recording, a `calib_status` push every
  /// [calibTick] (a wait for a steady note, live pitch, progress, `step_done`), and the fake hears [calibPops] of the
  /// 3 pops. Without it, tests push statuses with [emitCalib].
  final bool calibAuto;
  final Duration calibTick;
  int calibPops;

  /// The state [status] answers with; tests may replace it (the screen sees it on its next fetch).
  VoxStatus current;
  final _events = StreamController<VoxEvent>.broadcast();
  Timer? _timer;
  final _clock = Stopwatch()..start();
  int _n = 0;
  int legacyOpened = 0;
  int connects = 0;
  int bluetoothRequests = 0;
  int bluetoothEnables = 0;
  int appSettingsOpened = 0;

  /// What [launchRoute] answers (once); [openRoute] sends a route to a running UI (tests).
  String? pendingRoute;
  final _routes = StreamController<String>.broadcast();
  void openRoute(String route) => _routes.add(route);

  /// What [requestBluetooth] grants: true grants every missing permission, false leaves them missing.
  bool grantBluetooth = true;

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
    final mic = current.soundSource == 'phone' || current.soundSource == 'usb';
    if (!current.deviceReady && !mic) {
      emit('device_cmd', {'cmd': label, 'result': 'failed', 'error': 'no device connected'});
      return DeviceResult(ok: false, result: 'failed', cmd: label, error: 'no device connected');
    }
    commands.add({'v': 1, 'armed': ?armed, 'mode': ?mode, if (sleep) 'sleep': true});
    if (mic) {
      // A phone or USB mic source owns the mode and arm state: applied here (VoxService.deviceCommand). No device to sleep.
      if (sleep) {
        emit('device_cmd', {'cmd': label, 'result': 'failed', 'error': 'no device with a mic source'});
        return DeviceResult(ok: false, result: 'failed', cmd: label, error: 'no device with a mic source');
      }
      final a = armed ?? current.armed;
      final m = mode ?? current.mode;
      current = current.copyWith(armed: a, mode: m, deviceArmed: a, deviceMode: m, deviceError: () => null);
      if (mode != null) emit('mode', {'mode': m});
      if (armed != null) emit('arm', {'state': a ? 'armed' : 'disarmed', 'by': 'app'});
      emit('device_cmd', {'cmd': label, 'result': 'applied', 'local': true});
      return DeviceResult(ok: true, result: 'applied', cmd: label);
    }
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
    if (current.bleDevice == null) {
      // Nothing remembered: a search (the test moves it on by replacing [current] and emitting `ble`).
      current = current.copyWith(bleState: 'scanning', bleScan: () => 'scanning', bleHint: () => null);
      emit('ble', {'what': 'scan', 'result': 'started', 'then_connect': true});
      return current;
    }
    current = current.copyWith(bleHint: () => null, deviceState: () => 'connecting', bleState: 'connecting');
    emit('ble', {'what': 'state', 'state': 'connecting'});
    return current;
  }

  @override
  Future<VoxStatus> requestBluetooth() async {
    bluetoothRequests++;
    if (grantBluetooth) {
      current = current.copyWith(bleMissing: const [], bleBlocked: false);
    } else {
      current = current.copyWith(bleBlocked: true);
    }
    emit('ble', {'what': 'permissions', 'granted': grantBluetooth});
    return current;
  }

  @override
  Future<void> enableBluetooth() async => bluetoothEnables++;

  @override
  Future<void> openAppSettings() async => appSettingsOpened++;

  @override
  Future<String?> launchRoute() async {
    final r = pendingRoute;
    pendingRoute = null;
    return r;
  }

  @override
  Stream<String> routeRequests() => _routes.stream;

  @override
  bool get hasLegacySettings => false;

  @override
  Future<void> openLegacySettings() async => legacyOpened++;


  // --- the voice cursor ----------------------------------------------------------------------------------------------

  /// The voice cursor settings as stored.
  CursorSettings cursor = const CursorSettings();

  /// Every calibration command, as (method name, arguments), e.g. `('calib_step', {'step': 'glide'})`.
  final calibCalls = <(String, Map<String, Object?>)>[];

  /// The saved profiles per source (what `calib_get` answers).
  final calibSaved = <String, CalibResult>{};

  /// With [calibAuto]: the steps that fail on their first recording, and the engine's reason.
  final calibFailOnce = <String, String>{};

  final _calibOut = StreamController<CalibStatus>.broadcast();

  /// Sends one `calib_status` push (tests), as Kotlin's `calib_status` call does.
  void emitCalib(Map<String, Object?> status) => _calibOut.add(CalibStatus.fromMap(status));

  @override
  Stream<CalibStatus> calibStatus() => _calibOut.stream;

  @override
  Future<CursorSettings> cursorSettings() async => cursor;

  @override
  Future<CursorSettings> setCursorSettings({double? speed, double? pitchSens}) async {
    cursor = CursorSettings(
      speed: speed == null ? cursor.speed : CursorSettings.snap(speed),
      pitchSens: pitchSens == null ? cursor.pitchSens : CursorSettings.snap(pitchSens),
    );
    emit('setting', {'cursor_speed': ?speed, 'cursor_pitch_sens': ?pitchSens, 'by': 'app'});
    return cursor;
  }

  /// The level gate's settings as stored.
  LevelGateSettings levelGate = const LevelGateSettings();

  @override
  Future<LevelGateSettings> levelGateSettings() async => levelGate;

  @override
  Future<LevelGateSettings> setLevelGateSettings({bool? enabled, int? offsetDb}) async {
    levelGate = levelGate.copyWith(
        enabled: enabled, offsetDb: offsetDb == null ? null : LevelGateSettings.clampOffset(offsetDb));
    emit('setting', {'level_gate': ?enabled, 'level_gate_offset_db': ?offsetDb, 'by': 'app'});
    return levelGate;
  }

  /// With [calibAuto]: the tongue clicks and hisses the fake hears (of 3 and 2).
  int calibClicks = 3;
  int calibHiss = 2;

  @override
  Future<void> calibStart(String source, {List<String>? steps}) async {
    calibCalls.add(('calib_start', {'source': source, 'steps': ?steps}));
    if (source != (current.soundSource ?? 'phone') || source == 'pico') {
      throw StateError(source == 'pico' ? 'the Pico mic cannot be calibrated yet' : '$source is not the sound source');
    }
    if (steps != null && (steps.isEmpty || steps.toSet().length != steps.length || !steps.every(calibSteps.contains))) {
      throw ArgumentError('steps must be an ordered subset of $calibSteps, no repeats');
    }
    _cSource = source;
    _cRun = [...steps ?? calibSteps];
    _cFinished.clear();
    // the draft starts from the saved profile, with the run's steps taken out of `skipped` (they are recorded again)
    _cDraft = {...?calibSaved[source]?.toMap()};
    _cDraft['skipped'] = [for (final s in _steps(_cDraft['skipped'])) if (!_cRun.contains(s)) s];
    if (calibAuto) _cPlay(_cRun.first);
  }

  @override
  Future<void> calibStep(String step) async {
    calibCalls.add(('calib_step', {'step': step}));
    if (!calibAuto) return;
    // a no-op while that step is already waiting or recording
    if (step == _cStep && (_cState == 'waiting' || _cState == 'recording')) return;
    _cPlay(step);
  }

  @override
  Future<void> calibRedo(String step) async {
    calibCalls.add(('calib_redo', {'step': step}));
    if (calibAuto) _cPlay(step);
  }

  @override
  Future<void> calibRetry() async {
    calibCalls.add(('calib_retry', {}));
    if (calibAuto && _cStep != null && _cState == 'failed') _cPlay(_cStep!);
  }

  @override
  Future<void> calibSkip() async {
    calibCalls.add(('calib_skip', {}));
    final step = _cStep;
    if (!calibAuto || step == null) return;
    _cTimer?.cancel();
    _cFill(step, skipped: true);
    _cFinished.add(step);
    _cFailed = null;
    // the run's next unfinished step after it starts by itself; never a wrap round
    final next = _cRun.skip(_cRun.indexOf(step) + 1).where((s) => !_cFinished.contains(s)).firstOrNull;
    if (next != null) {
      _cPlay(next);
    } else {
      _cState = _cRemaining.isEmpty ? 'done' : 'step_done'; // an earlier step still open: the UI picks it
      _calibOut.add(CalibStatus.fromMap(_cStatus()));
    }
  }

  @override
  Future<void> calibSave() async {
    calibCalls.add(('calib_save', {}));
    final r = CalibResult.fromMap(_cResultMap());
    if (_cSource != null && r != null) {
      calibSaved[_cSource!] = CalibResult.fromMap({...r.toMap(), 'source': _cSource, 'saved_at_ms': 1790000000000})!;
    }
    _cStop();
  }

  @override
  Future<void> calibCancel() async {
    calibCalls.add(('calib_cancel', {}));
    _cStop();
  }

  @override
  Future<CalibResult?> calibGet(String source) async {
    calibCalls.add(('calib_get', {'source': source}));
    return calibSaved[source];
  }

  // The made-up recording (calibAuto): ticks of [calibTick]; a wait for a steady note, then the step's length.
  String? _cSource;
  String? _cStep;
  String? _cFailed;
  int _cI = 0;
  Timer? _cTimer;
  /// The run's steps (in order), those finished in it (measured or skipped; a redo keeps its step finished, as the
  /// service does), and the state: waiting | recording | failed | step_done | done.
  List<String> _cRun = const [];
  final _cFinished = <String>{};
  String _cState = 'recording';

  List<String> get _cRemaining => [for (final s in _cRun) if (!_cFinished.contains(s)) s];
  Map<String, Object?> _cDraft = {};

  static const _cWait = {'hum': 8, 'glide': 6, 'whistle': 6};
  static const _cLen = {'hum': 30, 'glide': 50, 'vowels': 66, 'pops': 40, 'clicks': 40, 'whistle': 50, 'hiss': 30, 'room': 30};
  static const _cPrompt = {
    'hum': "Hum 'mm' relaxed for 3 s: the note that comes out without thinking",
    'glide': 'Glide from your lowest comfortable note to your highest and back (5 s)',
    'vowels': "Hold 'ee', then 'ah', then 'oo', 2 s each at a middle pitch",
    'pops': 'Pop your lips 3 times, about a second apart',
    'clicks': 'Click your tongue 3 times, about a second apart',
    'whistle': 'Whistle from your lowest note to your highest and back (5 s)',
    'hiss': "Two short 'tss' hisses, about a second apart",
    'room': 'Stay quiet for 3 s: Canti listens to the room',
  };

  /// When the counted steps' sounds are heard (ticks into the step).
  static const _cAt = {'pops': [8, 20, 32], 'clicks': [6, 18, 30], 'hiss': [6, 18]};

  int _cCount(String step) => switch (step) { 'pops' => calibPops, 'clicks' => calibClicks, 'hiss' => calibHiss, _ => 0 };

  void _cPlay(String step) {
    _cTimer?.cancel();
    _cStep = step;
    _cFailed = null;
    _cI = 0;
    if (!_cRun.contains(step)) _cRun = [..._cRun, step]; // a step outside the run joins it
    _cState = (_cWait[step] ?? 0) > 0 ? 'waiting' : 'recording';
    _calibOut.add(CalibStatus.fromMap(_cStatus()));
    _cTimer = Timer.periodic(calibTick, (_) {
      _cI++;
      final wait = _cWait[step] ?? 0, len = _cLen[step]!;
      final fail = calibFailOnce[step];
      if (fail != null && _cI >= wait + len ~/ 2) {
        _cTimer?.cancel();
        calibFailOnce.remove(step);
        _cFailed = fail;
        _cState = 'failed';
      } else if (_cI >= wait + len) {
        _cTimer?.cancel();
        _cFill(step, skipped: false);
        _cFinished.add(step);
        _cState = _cRemaining.isEmpty ? 'done' : 'step_done';
      } else if (_cI >= wait) {
        _cState = 'recording';
      }
      _calibOut.add(CalibStatus.fromMap(_cStatus()));
    });
  }

  /// Stops the made-up recording where it is (the desktop preview holds a screen still for a screenshot).
  void calibFreeze() => _cTimer?.cancel();

  void _cStop() {
    _cTimer?.cancel();
    _cStep = null;
    final p = calibSaved[_cSource];
    _calibOut.add(CalibStatus.fromMap({
      'active': false,
      'source': _cSource,
      'state': null,
      'calibrated': p != null,
      'skipped': p?.skipped ?? const <String>[],
      'needs_recalibration': p?.needsRecalibration ?? false,
      'missing_steps': p?.missingSteps ?? const <String>[],
    }));
  }

  /// A step's made-up measurement into the draft (or nulls, skipped).
  void _cFill(String step, {required bool skipped}) {
    Object? v(Object? x) => skipped ? null : x;
    final d = _cDraft;
    switch (step) {
      case 'hum':
        d['home_hz'] = v(142.0);
        d['voicing_threshold'] = v(0.42);
      case 'glide':
        d['range_lo_hz'] = v(96.0);
        d['range_hi_hz'] = v(318.0);
      case 'vowels':
        d['vowels'] = {for (final (k, a) in const [('ee', 0.93), ('ah', 0.81), ('oo', 0.88)]) k: {'acc': v(a)}};
      case 'pops':
        d['pops_heard'] = v(calibPops);
      case 'clicks':
        d['clicks_heard'] = v(calibClicks);
      case 'whistle':
        d['whistle_lo_hz'] = v(880.0);
        d['whistle_hi_hz'] = v(2350.0);
        d['whistle_home_hz'] = v(1400.0);
      case 'hiss':
        d['hiss_heard'] = v(calibHiss);
      case 'room':
        d['room_floor_dbfs'] = v(-63.0);
    }
    final k = {..._steps(d['skipped'])};
    skipped ? k.add(step) : k.remove(step);
    d['skipped'] = [for (final s in calibSteps) if (k.contains(s)) s];
    // the gate comes from the calibration once the clicks were measured, else the default
    final n = [d['pops_heard'], d['clicks_heard'], d['hiss_heard']].whereType<int>().fold(0, (a, b) => a + b);
    d['level_gate'] = d['clicks_heard'] != null
        ? {'min_snr_db': 11.0, 'min_level_dbfs': -52.0, 'from': 'calibration', 'n': n, 'weakest_snr_db': 17.0,
            'weakest_level_dbfs': -46.0}
        : {'min_snr_db': 6.0, 'min_level_dbfs': -60.0, 'from': 'default', 'n': 0};
    d['relabel_rule'] = d['pops_heard'] != null && d['clicks_heard'] != null;
  }

  static List<String> _steps(Object? v) => v is List ? [for (final x in v) if (x is String) x] : const [];

  /// The draft as the service answers it (`result`): version 2, with the steps neither measured nor skipped.
  Map<String, Object?> _cResultMap() {
    final d = _cDraft;
    final skipped = _steps(d['skipped']).toSet();
    bool has(String s) => switch (s) {
          'hum' => d['home_hz'] != null,
          'glide' => d['range_lo_hz'] != null,
          'vowels' => (d['vowels'] as Map?)?.values.any((x) => (x as Map?)?['acc'] != null) ?? false,
          'pops' => d['pops_heard'] != null,
          'clicks' => d['clicks_heard'] != null,
          'whistle' => d['whistle_lo_hz'] != null,
          'hiss' => d['hiss_heard'] != null,
          _ => d['room_floor_dbfs'] != null,
        };
    final missing = [for (final s in calibSteps) if (!skipped.contains(s) && !has(s)) s];
    return {
      ...d,
      'version': 2,
      'level_gate': d['level_gate'] ?? {'min_snr_db': 6.0, 'min_level_dbfs': -60.0, 'from': 'default', 'n': 0},
      'missing_steps': missing,
      'needs_recalibration': missing.isNotEmpty,
      'extractor': const <String, Object?>{},
    };
  }

  Map<String, Object?> _cStatus() {
    final step = _cStep!;
    final wait = _cWait[step] ?? 0, len = _cLen[step]!;
    final done = _cState == 'step_done' || _cState == 'done';
    final failed = _cState == 'failed';
    final waiting = _cState == 'waiting';
    final j = (_cI - wait).clamp(0, len);
    final f = j / len;
    Map<String, Object?> live = {'voiced': false, 'pitch_hz': null, 'level_db': -54.0, 'vowel': null, 'vowel_conf': null};
    final heard = <String, int>{};
    String? sub;
    if (!waiting && !done && !failed) {
      switch (step) {
        case 'hum':
          live = {'voiced': true, 'pitch_hz': 142 + 3 * math.sin(_cI / 2), 'level_db': -22.0};
        case 'glide':
          final up = f < 0.5 ? f * 2 : 2 - f * 2;
          live = {'voiced': true, 'pitch_hz': 96 * math.pow(318 / 96, up), 'level_db': -20.0};
        case 'whistle':
          final up = f < 0.5 ? f * 2 : 2 - f * 2;
          live = {'voiced': true, 'pitch_hz': 880 * math.pow(2350 / 880, up), 'level_db': -26.0};
        case 'vowels':
          final v = const ['ee', 'ah', 'oo'][(j * 3 ~/ len).clamp(0, 2)];
          sub = "now '$v'";
          live = {'voiced': true, 'pitch_hz': 180.0, 'level_db': -21.0, 'vowel': v, 'vowel_conf': 0.78 + 0.1 * math.sin(_cI / 3)};
        case 'room':
          sub = 'stay quiet';
          live = {'voiced': false, 'pitch_hz': null, 'level_db': -63 + 2 * math.sin(_cI / 2)};
        case 'pops' || 'clicks' || 'hiss':
          final at = _cAt[step]!.take(_cCount(step));
          heard[step] = at.where((t) => j >= t).length;
          live = {'voiced': false, 'pitch_hz': null, 'level_db': at.any((t) => j - t >= 0 && j - t < 2) ? -9.0 : -52.0};
      }
    }
    if (done && calibCountedSteps.contains(step)) heard[step] = _cCount(step);
    if (waiting) sub = step == 'whistle' ? 'waiting for a steady whistle' : 'waiting for a steady note';
    if (failed) sub = 'failed: retry or skip';
    return {
      'active': true,
      'source': _cSource,
      'step': step,
      'state': _cState,
      'prompt': _cPrompt[step],
      'sub': sub,
      'progress': done ? 1.0 : f,
      'waiting_for_steady': waiting,
      'live': live,
      'heard': {
        'pops_n': heard['pops'] ?? 0,
        'pops_need': 3,
        'clicks_n': heard['clicks'] ?? 0,
        'clicks_need': 3,
        'hiss_n': heard['hiss'] ?? 0,
        'hiss_need': 2,
      },
      'step_done': done,
      'reason': _cFailed,
      'skipped': [for (final s in _steps(_cDraft['skipped'])) if (_cRun.contains(s)) s], // this run's
      'steps': _cRun,
      'remaining': _cRemaining,
      'result': _cFinished.isEmpty ? null : _cResultMap(),
      'calibrated': calibSaved.containsKey(_cSource),
    };
  }

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
    emit('exec', {'n': _n, 'action': s[1].replaceAll(' ', '_'), 'ok': true, 'how': 'fake'});
    emit('confirm', {'watch': _n, 'result': 'confirmed (events)'});
  }

  void dispose() {
    _timer?.cancel();
    _cTimer?.cancel();
    _events.close();
    _routes.close();
    _calibOut.close();
  }
}
