import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/foundation.dart';

import 'backend.dart';

// The voice cursor's calibration: what the service sends (`calib_status`, `calib_get`), the cursor settings, and
// [CalibFlow], the setup screen's state (which page, which steps are done, redo, save, cancel). The service side is
// VoiceJoystick's calibration (android, PROTOCOL.md "Voice joystick" > Calibration); the desktop prototype is
// extractor/joystick.py's setup.

/// The recorded steps, in order (calibration v2: eight).
const calibSteps = ['hum', 'glide', 'vowels', 'pops', 'clicks', 'whistle', 'hiss', 'room'];

/// The steps that count sounds (`heard`): pops, clicks, hiss.
const calibCountedSteps = ['pops', 'clicks', 'hiss'];

/// The steps that follow a pitch (the live readout's Pitch row).
const calibPitchSteps = ['hum', 'glide', 'vowels', 'whistle'];

/// The mic sources a calibration belongs to (one profile each).
const calibSources = ['phone', 'usb', 'pico'];

List<String> _steps(Object? v) => v is List ? [for (final x in v) if (x is String) x] : const [];

/// The setup screen's pages: the intro, one per step, the result.
enum CalibPage {
  intro,
  hum,
  glide,
  vowels,
  pops,
  clicks,
  whistle,
  hiss,
  room,
  result;

  /// The step this page records, or null (intro, result).
  String? get step => calibSteps.contains(name) ? name : null;

  static CalibPage ofStep(String step) => CalibPage.values.byName(step);
}

double? _d(Object? v) => v is num ? v.toDouble() : null;
int? _i(Object? v) => v is num ? v.round() : null;
String? _s(Object? v) => v is String ? v : null;
Map<Object?, Object?>? _m(Object? v) => v is Map ? v.cast<Object?, Object?>() : null;

/// The level gate a calibration derived (`level_gate`): sounds under [minSnrDb] over the room, or quieter than
/// [minLevelDbfs], are ignored. [from] is `calibration` (from the pops, clicks and hiss heard) or `default`.
@immutable
class LevelGate {
  const LevelGate({
    required this.minSnrDb,
    required this.minLevelDbfs,
    this.from = 'default',
    this.n = 0,
    this.weakestSnrDb,
    this.weakestLevelDbfs,
  });

  final double minSnrDb;
  final double minLevelDbfs;
  final String from;

  /// How many calibrated sounds it came from.
  final int n;
  final double? weakestSnrDb;
  final double? weakestLevelDbfs;

  bool get calibrated => from == 'calibration';

  static LevelGate? fromMap(Object? o) {
    final m = _m(o);
    final snr = _d(m?['min_snr_db']), level = _d(m?['min_level_dbfs']);
    if (m == null || snr == null || level == null) return null;
    return LevelGate(
      minSnrDb: snr,
      minLevelDbfs: level,
      from: _s(m['from']) ?? 'default',
      n: _i(m['n']) ?? 0,
      weakestSnrDb: _d(m['weakest_snr_db']),
      weakestLevelDbfs: _d(m['weakest_level_dbfs']),
    );
  }

  Map<String, Object?> toMap() => {
        'min_snr_db': minSnrDb,
        'min_level_dbfs': minLevelDbfs,
        'from': from,
        'n': n,
        'weakest_snr_db': ?weakestSnrDb,
        'weakest_level_dbfs': ?weakestLevelDbfs,
      };

  /// "Ignores sounds under 12 dB over the room (from your calibration)."
  String get sentence => 'Ignores sounds under ${minSnrDb.round()} dB over the room '
      '(${calibrated ? 'from your calibration' : 'the default: calibrate the clicks to tune it'}).';
}

/// A saved (or just measured) calibration (profile version 2): the home note, the range, how well each vowel was told
/// apart, the pops, clicks and hisses heard, the whistle range, the room's floor and the level gate. A skipped or
/// never measured step's fields are null; [missingSteps] are the steps neither measured nor skipped (a version 1
/// profile: clicks, whistle, hiss, room).
@immutable
class CalibResult {
  const CalibResult({
    this.homeHz,
    this.rangeLoHz,
    this.rangeHiHz,
    this.vowelAcc = const {},
    this.popsHeard,
    this.voicingThreshold,
    this.source,
    this.savedAtMs,
    this.skipped = const [],
    this.version = 2,
    this.clicksHeard,
    this.hissHeard,
    this.whistleLoHz,
    this.whistleHiHz,
    this.whistleHomeHz,
    this.roomFloorDbfs,
    this.levelGate,
    this.relabelRule,
    this.missingSteps = const [],
    this.needsRecalibration = false,
  });

  final double? homeHz;
  final double? rangeLoHz;
  final double? rangeHiHz;

  /// `ee`, `ah`, `oo` -> accuracy 0..1 (null when the vowel had no frames).
  final Map<String, double?> vowelAcc;
  final int? popsHeard;
  final double? voicingThreshold;

  /// The profile's source and when it was saved (a saved profile only).
  final String? source;
  final int? savedAtMs;

  /// The steps skipped (their defaults kept; their fields are null).
  final List<String> skipped;

  final int version;
  final int? clicksHeard;
  final int? hissHeard;
  final double? whistleLoHz;
  final double? whistleHiHz;
  final double? whistleHomeHz;
  final double? roomFloorDbfs;
  final LevelGate? levelGate;

  /// A per-person click / pop rule was derived.
  final bool? relabelRule;

  /// The steps neither measured nor skipped.
  final List<String> missingSteps;
  /// Some steps are missing (the service says so; [fromMap] also infers it from [missingSteps]).
  final bool needsRecalibration;

  /// Fewer than 2 of 3 pops heard: the pops may be missed in use.
  bool get popsWeak => (popsHeard ?? 0) < 2;

  static CalibResult? fromMap(Object? o) {
    final m = _m(o);
    if (m == null) return null;
    final v = _m(m['vowels']) ?? const {};
    return CalibResult(
      homeHz: _d(m['home_hz']),
      rangeLoHz: _d(m['range_lo_hz']),
      rangeHiHz: _d(m['range_hi_hz']),
      vowelAcc: {for (final k in const ['ee', 'ah', 'oo']) k: _d(_m(v[k])?['acc'])},
      popsHeard: _i(m['pops_heard']),
      voicingThreshold: _d(m['voicing_threshold']),
      source: _s(m['source']),
      savedAtMs: _i(m['saved_at_ms']),
      skipped: _steps(m['skipped']),
      version: _i(m['version']) ?? 1,
      clicksHeard: _i(m['clicks_heard']),
      hissHeard: _i(m['hiss_heard']),
      whistleLoHz: _d(m['whistle_lo_hz']),
      whistleHiHz: _d(m['whistle_hi_hz']),
      whistleHomeHz: _d(m['whistle_home_hz']),
      roomFloorDbfs: _d(m['room_floor_dbfs']),
      levelGate: LevelGate.fromMap(m['level_gate']),
      relabelRule: m['relabel_rule'] as bool?,
      missingSteps: _steps(m['missing_steps']),
      needsRecalibration: m['needs_recalibration'] as bool? ?? _steps(m['missing_steps']).isNotEmpty,
    );
  }

  Map<String, Object?> toMap() => {
        'source': ?source,
        'version': version,
        'saved_at_ms': ?savedAtMs,
        'home_hz': homeHz,
        'range_lo_hz': rangeLoHz,
        'range_hi_hz': rangeHiHz,
        'vowels': {for (final e in vowelAcc.entries) e.key: {'acc': e.value}},
        'pops_heard': popsHeard,
        'voicing_threshold': voicingThreshold,
        'skipped': skipped,
        'clicks_heard': clicksHeard,
        'hiss_heard': hissHeard,
        'whistle_lo_hz': whistleLoHz,
        'whistle_hi_hz': whistleHiHz,
        'whistle_home_hz': whistleHomeHz,
        'room_floor_dbfs': roomFloorDbfs,
        'level_gate': levelGate?.toMap(),
        'relabel_rule': relabelRule,
        'missing_steps': missingSteps,
        'needs_recalibration': needsRecalibration,
      };
}

/// What the mic hears right now (`calib_status.live`).
@immutable
class CalibLive {
  const CalibLive({this.voiced = false, this.pitchHz, this.levelDb, this.vowel, this.vowelConf});

  final bool voiced;
  final double? pitchHz;
  final double? levelDb;
  final String? vowel;
  final double? vowelConf;

  static CalibLive fromMap(Object? o) {
    final m = _m(o) ?? const {};
    return CalibLive(
      voiced: m['voiced'] == true,
      pitchHz: _d(m['pitch_hz']),
      levelDb: _d(m['level_db']),
      vowel: _s(m['vowel']),
      vowelConf: _d(m['vowel_conf']),
    );
  }
}

/// One `calib_status` push (about 10 Hz while a calibration is active).
@immutable
class CalibStatus {
  const CalibStatus({
    required this.active,
    this.source,
    this.step,
    this.prompt,
    this.sub,
    this.progress = 0,
    this.state,
    this.waitingForSteady = false,
    this.live = const CalibLive(),
    this.popsN = 0,
    this.popsNeed = 3,
    this.clicksN = 0,
    this.clicksNeed = 3,
    this.hissN = 0,
    this.hissNeed = 2,
    this.stepDone = false,
    this.calibrated,
    this.result,
    this.error,
    this.failed = false,
    this.reason,
    this.skipped = const [],
    this.runSteps,
    this.remaining,
    this.missingSteps = const [],
    this.needsRecalibration = false,
  });

  final bool active;
  final String? source;

  /// One of [calibSteps] while one is recorded (anything else: none).
  final String? step;
  final String? prompt;
  final String? sub;

  /// 0..1 through the step.
  final double progress;
  /// `waiting` (for a steady note), `recording`, `failed`, `step_done` or `done`.
  final String? state;
  final bool waitingForSteady;
  final CalibLive live;
  final int popsN;
  final int popsNeed;
  final int clicksN;
  final int clicksNeed;
  final int hissN;
  final int hissNeed;
  final bool stepDone;

  /// This source has a saved profile.
  final bool? calibrated;
  final CalibResult? result;
  final String? error;

  /// The step failed (too short, too rough, range too small, ...): [reason] says why. The service waits for
  /// `calib_retry` or `calib_skip`; the screen never skips or restarts it by itself.
  final bool failed;
  final String? reason;

  /// The steps skipped in this run (`result.skipped` is the merged profile's).
  final List<String> skipped;

  /// The run's steps, in order (`steps`), and those not finished yet (`remaining`); null from a status without them.
  final List<String>? runSteps;
  final List<String>? remaining;

  /// The inactive map: the saved profile's steps neither measured nor skipped (a version 1 profile).
  final List<String> missingSteps;
  final bool needsRecalibration;

  /// (heard, asked) for a counted step (pops, clicks, hiss), else null.
  (int, int)? heard(String step) => switch (step) {
        'pops' => (popsN, popsNeed),
        'clicks' => (clicksN, clicksNeed),
        'hiss' => (hissN, hissNeed),
        _ => null,
      };

  static CalibStatus fromMap(Map<Object?, Object?> m) {
    final heard = _m(m['heard']) ?? const {};
    return CalibStatus(
      active: m['active'] == true,
      source: _s(m['source']),
      step: _s(m['step']),
      prompt: _s(m['prompt']),
      sub: _s(m['sub']),
      progress: (_d(m['progress']) ?? 0).clamp(0.0, 1.0),
      state: _s(m['state']),
      waitingForSteady: m['waiting_for_steady'] == true || m['state'] == 'waiting',
      live: CalibLive.fromMap(m['live']),
      popsN: _i(heard['pops_n']) ?? 0,
      popsNeed: _i(heard['pops_need']) ?? 3,
      clicksN: _i(heard['clicks_n']) ?? 0,
      clicksNeed: _i(heard['clicks_need']) ?? 3,
      hissN: _i(heard['hiss_n']) ?? 0,
      hissNeed: _i(heard['hiss_need']) ?? 2,
      stepDone: m['step_done'] == true || m['state'] == 'step_done',
      calibrated: m['calibrated'] as bool?,
      result: CalibResult.fromMap(m['result']),
      error: _s(m['error']),
      // `state: failed`, with `reason` (the engine's words)
      failed: m['state'] == 'failed',
      reason: _s(m['reason']),
      skipped: _steps(m['skipped']),
      runSteps: m['steps'] is List ? _steps(m['steps']) : null,
      remaining: m['remaining'] is List ? _steps(m['remaining']) : null,
      missingSteps: _steps(m['missing_steps']),
      needsRecalibration: m['needs_recalibration'] == true,
    );
  }
}

/// The voice cursor's two settings, 0.5..2.0 each (1.0 = 100%).
@immutable
class CursorSettings {
  const CursorSettings({this.speed = defaultValue, this.pitchSens = defaultValue});

  static const min = 0.5;
  static const max = 2.0;
  static const step = 0.1;
  static const defaultValue = 0.9;

  /// `cursor_speed`.
  final double speed;

  /// `cursor_pitch_sens`.
  final double pitchSens;

  /// Clamped to [min]..[max] and put on the [step] grid.
  static double snap(double v) => double.parse(((v.clamp(min, max) / step).round() * step).toStringAsFixed(2));

  static String percent(double v) => '${(v * 100).round()}%';

  static CursorSettings fromMap(Map<Object?, Object?>? m) => CursorSettings(
        speed: snap(_d(m?['cursor_speed']) ?? defaultValue),
        pitchSens: snap(_d(m?['cursor_pitch_sens']) ?? defaultValue),
      );

  CursorSettings copyWith({double? speed, double? pitchSens}) =>
      CursorSettings(speed: speed ?? this.speed, pitchSens: pitchSens ?? this.pitchSens);
}

/// The level gate's settings (`levelGateSettings`): on / off, and an offset of -10..10 dB (+ = stricter: ignores
/// more quiet sounds).
@immutable
class LevelGateSettings {
  const LevelGateSettings({this.enabled = true, this.offsetDb = 0});

  static const minOffset = -10;
  static const maxOffset = 10;

  /// `level_gate`.
  final bool enabled;

  /// `level_gate_offset_db`.
  final int offsetDb;

  static int clampOffset(num v) => v.round().clamp(minOffset, maxOffset);

  /// "+3 dB", "0 dB", "-2 dB".
  static String label(int v) => '${v > 0 ? '+' : ''}$v dB';

  static LevelGateSettings fromMap(Map<Object?, Object?>? m) => LevelGateSettings(
        enabled: m?['level_gate'] as bool? ?? true,
        offsetDb: clampOffset(_d(m?['level_gate_offset_db']) ?? 0),
      );

  LevelGateSettings copyWith({bool? enabled, int? offsetDb}) =>
      LevelGateSettings(enabled: enabled ?? this.enabled, offsetDb: offsetDb ?? this.offsetDb);
}

/// "C#3" for [hz] (A4 = 440 Hz), or null.
String? noteName(double? hz) {
  if (hz == null || hz <= 0) return null;
  const names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
  final midi = (69 + 12 * math.log(hz / 440) / math.ln2).round();
  return '${names[midi % 12]}${midi ~/ 12 - 1}';
}

/// "142 Hz (C#3)", or "-".
String hzLabel(double? hz) => hz == null || hz <= 0 ? '-' : '${hz.round()} Hz (${noteName(hz)})';

/// The user-facing name of a sound source.
String sourceLabel(String? source) => switch (source) {
      'phone' => 'phone mic',
      'usb' => 'USB mic',
      'pico' => 'Canti device (Pico mic)',
      null => 'phone mic',
      final other => other,
    };

/// The calibration screen's state. The service records each step and pushes `calib_status`; this keeps the page,
/// the steps done, failed and skipped, the result, and whether a redo goes back to the result.
///
/// The flow: intro, then [begin] (`calib_start`, which starts the hum). When a step's status says `step_done`, [next]
/// starts the next step (`calib_step`), or shows the result after the last. A step whose status says `failed` shows
/// the engine's reason and waits: [retry] (`calib_retry`) records it again, [skip] (`calib_skip`) keeps its defaults
/// and moves on. [skip] also works where the service allows it before a failure ([canSkip]: waiting for a steady
/// note, a counted step before anything was heard, the room). Nothing is skipped or restarted without the user.
/// [redo] records a done step again (`calib_redo`); a redo from the result goes back to the result. [save]
/// (`calib_save`) and [cancel] (`calib_cancel`) end it. The pager can show any page reached so far ([goTo]) without
/// recording anything. When the service moves on by itself (after a skip), the screen follows it.
///
/// With [steps] (a profile's `missing_steps`), the run records only those, in order: [begin] sends `calib_start`
/// (the service starts the hum) and at once `calib_step` for the first of them. The service's draft starts from the
/// saved profile, so the other steps keep their values.
class CalibFlow extends ChangeNotifier {
  CalibFlow({required this.backend, required this.source, List<String>? steps})
      : steps = [for (final s in calibSteps) if (steps == null || steps.contains(s)) s];

  final VoxBackend backend;
  final String source;

  /// The steps this run records, in [calibSteps] order (all of them, or the missing ones).
  final List<String> steps;

  /// Only some steps (the missing ones).
  bool get partial => steps.length < calibSteps.length;

  /// The pages of this run: the intro, its steps, the result.
  List<CalibPage> get pages => [CalibPage.intro, for (final s in steps) CalibPage.ofStep(s), CalibPage.result];

  CalibPage _page = CalibPage.intro;
  CalibPage _furthest = CalibPage.intro;
  CalibStatus? _status;
  CalibResult? _result;
  String? _error;
  bool _started = false;
  bool _finished = false;
  bool _saved = false;
  bool _busy = false;
  bool _redoing = false;
  final _done = <String>{};
  final _skipped = <String>{};
  final _failed = <String, String>{};

  /// The step last commanded, until the service has shown it running (a `step_done` before that is stale).
  String? _pending;
  StreamSubscription<CalibStatus>? _sub;

  CalibPage get page => _page;
  CalibPage get furthest => _furthest;
  CalibStatus? get status => _status;
  CalibResult? get result => _result;
  String? get error => _error;
  bool get started => _started;
  bool get finished => _finished;
  bool get saved => _saved;
  bool get busy => _busy;

  /// A redo started from the result: done means back to the result.
  bool get redoing => _redoing;
  Set<String> get done => Set.unmodifiable(_done);

  /// The steps skipped (their defaults kept), in this run and in the draft.
  Set<String> get skipped => {..._skipped, ...?_result?.skipped};

  /// This page's step has been recorded (or skipped).
  bool get pageDone => _page.step != null && _done.contains(_page.step);

  /// Why this page's step failed (the engine's reason), or null. It stays until [retry] or [skip].
  String? get pageFailure => _failed[_page.step];

  /// The status, if it is about this page's step (the live readout).
  CalibStatus? get pageStatus {
    final s = _status;
    return s != null && s.step != null && s.step == _page.step && _pending != s.step ? s : null;
  }

  /// The service would take `calib_skip` now: the step failed, waits for a steady note, has heard nothing countable
  /// yet (pops, clicks, hiss), or is the room.
  bool get canSkip {
    final step = _page.step;
    if (step == null || _finished || pageDone) return false;
    if (_failed.containsKey(step)) return true;
    final s = pageStatus;
    if (s == null || !s.active) return false;
    if (s.state == 'waiting') return true;
    if (s.state != 'recording') return false;
    return step == 'room' || (s.heard(step)?.$1 ?? 1) == 0;
  }

  /// Where this page is in the run (the pager).
  int get pageIndex => pages.indexOf(_page);

  /// Listens to the service's pushes.
  void attach() => _sub ??= backend.calibStatus().listen(onStatus, onError: (Object e) => _fail('status', e));

  void dismissError() {
    _error = null;
    notifyListeners();
  }

  /// One push from the service (also each command's answer).
  @visibleForTesting
  void onStatus(CalibStatus s) {
    if (_finished) return;
    if (s.source != null && s.source != source) return;
    _status = s;
    if (s.error != null) _error = s.error;
    if (s.result != null) _result = s.result;
    if (_started && s.active) {
      // this run's skips; a skipped step that is being recorded again stays open until it finishes
      for (final k in s.skipped) {
        if (!steps.contains(k) || k == _pending || (k == s.step && !s.stepDone)) continue;
        _skipped.add(k);
        _done.add(k);
        _failed.remove(k);
      }
    }
    final step = s.step;
    if (step != null && calibSteps.contains(step)) {
      if (_pending == step && !s.stepDone && !s.failed) _pending = null;
      if (_pending != step) {
        if (s.failed) {
          _failed[step] = s.reason ?? 'This step did not work.';
          _done.remove(step);
        } else if (s.stepDone || s.state == 'done') {
          _failed.remove(step);
          _done.add(step);
        } else {
          _failed.remove(step);
          _follow(step);
        }
      }
    }
    if (_started && !s.active && s.error == null) _error = 'The calibration stopped (the Canti service ended it).';
    notifyListeners();
  }

  /// The service is recording [step]: show it if the screen is not busy elsewhere (on the intro, or on a step that is
  /// finished), unless a redo from the result is under way or it is not a step of this run.
  void _follow(String step) {
    if (!_started || _redoing || !steps.contains(step) || step == _page.step || _done.contains(step)) return;
    if (_page == CalibPage.intro || pageDone) _show(CalibPage.ofStep(step));
  }

  /// Starts the calibration: `calib_start` with this run's steps (a partial run); the service starts on the first.
  Future<void> begin() async {
    if (_started || _busy) return;
    _started = true;
    _error = null;   // an earlier refusal must not read as this start failing (the run would go on, unseen)
    _show(CalibPage.ofStep(steps.first));
    await _call('start', () => backend.calibStart(source, steps: partial ? steps : null));
    if (_error != null) {
      _started = false;
      _show(CalibPage.intro);
    }
  }

  /// The run's steps not finished yet, in order: the service's `remaining` (this screen's own count only until a
  /// status carries it).
  List<String> get _remaining => _status?.remaining ?? [for (final s in steps) if (!_done.contains(s)) s];

  /// Once this page's step is done, the result comes next (every other step of the run is finished, or a redo from
  /// the result is under way), not another step.
  bool get nextIsResult {
    final step = _page.step;
    return _redoing || !_remaining.any((s) => s != step);
  }

  /// After a step is done: the run's next unfinished step (`remaining[0]`), or the result once the run is done (or
  /// after a redo from the result: the service goes back to done, nothing else starts).
  Future<void> next() async {
    final step = _page.step;
    if (step == null || !_done.contains(step) || _busy) return;
    final rest = [for (final s in _remaining) if (s != step) s];
    if (_redoing || rest.isEmpty) {
      _redoing = false;
      _show(CalibPage.result);
      return;
    }
    final nextStep = rest.first;
    // The service already records it (it moves on by itself after a skip): just show it.
    if (_status?.step == nextStep) {
      _show(CalibPage.ofStep(nextStep));
      return;
    }
    await _startStep(nextStep, redo: false);
  }

  /// Records a done step again (from its page or from the result).
  Future<void> redo(String step) async {
    if (!_started || _finished || _busy) return;
    _redoing = _page == CalibPage.result || _redoing;
    _skipped.remove(step);
    await _startStep(step, redo: true);
  }

  /// Records the failed step again (`calib_retry`).
  Future<void> retry() async {
    final step = _page.step;
    if (step == null || !_failed.containsKey(step) || _busy || _finished) return;
    _failed.remove(step);
    _done.remove(step);
    _pending = step;
    notifyListeners();
    await _call('retry', backend.calibRetry);
  }

  /// Keeps the defaults for this step (`calib_skip`) and moves on. The service never wraps round: the run's next
  /// unfinished step after this one starts by itself (nothing more is sent); with none, the run is done (the result),
  /// or an earlier step is still open (`step_done`) and this screen asks for it (`calib_step remaining[0]`).
  Future<void> skip() async {
    final step = _page.step;
    if (step == null || !canSkip || _busy) return;
    final run = _status?.runSteps ?? steps;
    final rest = [for (final s in _remaining) if (s != step) s];
    final after = run.skip(run.indexOf(step) + 1).where(rest.contains).firstOrNull;
    await _call('skip', backend.calibSkip);
    if (_error != null) return;
    _failed.remove(step);
    _skipped.add(step);
    _done.add(step);
    if (_redoing || rest.isEmpty) {
      _redoing = false;
      _show(CalibPage.result);
    } else if (after != null) {
      _show(CalibPage.ofStep(after));
    } else {
      await _startStep(rest.first, redo: false);
    }
  }

  Future<void> save() async {
    if (!_started || _finished || _busy) return;
    _finished = true;
    _saved = true;
    await _call('save', backend.calibSave);
    if (_error != null) {
      _finished = false;
      _saved = false;
      notifyListeners();
    }
  }

  /// Ends the calibration without saving (nothing is sent if it never started or already ended).
  Future<void> cancel() async {
    if (_finished) return;
    _finished = true;
    if (_started) await _call('cancel', backend.calibCancel);
    notifyListeners();
  }

  /// Shows a page of this run reached before (the pager, by [pages] index); records nothing.
  void goTo(int index) {
    final ps = pages;
    if (index < 0 || index >= ps.length || ps[index].index > _furthest.index) return;
    _show(ps[index]);
  }

  Future<void> _startStep(String step, {required bool redo}) async {
    _done.remove(step);
    _failed.remove(step);
    _pending = step;
    _show(CalibPage.ofStep(step));
    await _call(redo ? 'redo' : 'step', () => redo ? backend.calibRedo(step) : backend.calibStep(step));
  }

  void _show(CalibPage p) {
    _page = p;
    if (p.index > _furthest.index) _furthest = p;
    notifyListeners();
  }

  Future<void> _call(String what, Future<void> Function() f) async {
    _busy = true;
    notifyListeners();
    try {
      await f();
    } catch (e) {
      _fail(what, e);
    } finally {
      _busy = false;
      notifyListeners();
    }
  }

  void _fail(String what, Object e) {
    final m = RegExp(r'PlatformException\([^,]*, (.*?), ').firstMatch('$e');
    _error = '$what: ${m?.group(1) ?? e}';
    notifyListeners();
  }

  bool _disposed = false;

  @override
  void notifyListeners() {
    if (!_disposed) super.notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _sub?.cancel();
    super.dispose();
  }
}
