import 'dart:math' as math;

import 'package:flutter/foundation.dart';

import 'shape_plot.dart';

// The voice cursor's calibration: what the service sends (`calib_status`, `calib_get`), the cursor settings, and
// the hub rows. The screens are hub_screen.dart (CalibController holds the live status). The service side is
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

/// The items of a list as objects, for nested status lists (checks, hub rows).
List<Object?> _list(Object? v) => v is List ? v.cast<Object?>() : const [];

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
  const CalibLive({
    this.voiced = false,
    this.pitchHz,
    this.levelDb,
    this.vowel,
    this.vowelConf,
    this.traceHz = const [],
    this.checks = const [],
  });

  final bool voiced;
  final double? pitchHz;
  final double? levelDb;
  final String? vowel;
  final double? vowelConf;

  /// The joystick ticks (20 ms, the last 5 s), null = unvoiced.
  final List<double?> traceHz;

  /// The provisional grade of the step so far.
  final List<ShapeCheck> checks;

  static CalibLive fromMap(Object? o) {
    final m = _m(o) ?? const {};
    return CalibLive(
      voiced: m['voiced'] == true,
      pitchHz: _d(m['pitch_hz']),
      levelDb: _d(m['level_db']),
      vowel: _s(m['vowel']),
      vowelConf: _d(m['vowel_conf']),
      // nulls are the unvoiced ticks (gaps in the trace), so they stay
      traceHz: [for (final x in _list(m['trace_hz'])) _d(x)],
      checks: [
        for (final c in _list(m['checks'])) ShapeCheck.fromMap(c),
      ],
    );
  }
}

/// One row of the hub: a step and its one-word result.
@immutable
class CalibStepInfo {
  const CalibStepInfo({required this.id, this.done = false, this.resultWord = '·'});

  final String id;
  final bool done;

  /// `ok` | `skipped` | `·` (the E9 contract also allows `low` | `noisy`).
  final String resultWord;

  static CalibStepInfo fromMap(Object? o) {
    final m = _m(o) ?? const {};
    return CalibStepInfo(
      id: _s(m['id']) ?? '?',
      done: m['done'] == true,
      resultWord: _s(m['result_word']) ?? '·',
    );
  }
}

/// Where a step sits in the run (1-based).
@immutable
class CalibPos {
  const CalibPos({this.i = 1, this.n = 8});

  final int i;
  final int n;

  static CalibPos fromMap(Object? o) {
    final m = _m(o) ?? const {};
    return CalibPos(i: _i(m['i']) ?? 1, n: _i(m['n']) ?? 8);
  }
}

/// Where a cancelled run left off: the step `calib_start {resume: true}` begins at, and the steps done so far.
@immutable
class CalibResume {
  const CalibResume({this.step, this.doneSteps = const []});

  final String? step;
  final List<String> doneSteps;

  static CalibResume? fromMap(Object? o) {
    if (o is! Map) return null;
    final m = o.cast<Object?, Object?>();
    return CalibResume(
      step: _s(m['step']),
      doneSteps: _steps(m['done_steps']),
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
    this.expect,
    this.scale,
    this.pos = const CalibPos(),
    this.hub = const [],
    this.resume,
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

  /// The wanted shape for a pitched step (hum/glide/whistle; null for the others).
  final ExpectedShape? expect;

  /// The draft's saved pitch scale (the voice range; the whistle range during `whistle`), or null.
  final PitchScale? scale;

  /// Where the current step sits in the run (1..8).
  final CalibPos pos;

  /// The hub rows: every step with its one-word result.
  final List<CalibStepInfo> hub;

  /// Where a cancelled run left off (the inactive map), or null.
  final CalibResume? resume;

  /// (heard, asked) for a counted step (pops, clicks, hiss), else null.
  (int, int)? heard(String step) => switch (step) {
        'pops' => (popsN, popsNeed),
        'clicks' => (clicksN, clicksNeed),
        'hiss' => (hissN, hissNeed),
        _ => null,
      };

  /// The hub's eight rows. The active map carries them (`hub`); the inactive one (no run: the hub's usual case, and
  /// after a cancel) has none, so they are derived as Kotlin does: a step is done when the saved profile has it (not in
  /// `missing_steps`) or the saved progress lists it (`resume.done_steps`); a skipped one reads `skipped`.
  List<CalibStepInfo> get hubRows {
    if (hub.isNotEmpty) return hub;
    final done = <String>{
      ...?resume?.doneSteps,
      if (calibrated == true || missingSteps.isNotEmpty)
        for (final s in calibSteps)
          if (!missingSteps.contains(s)) s,
    };
    return [
      for (final s in calibSteps)
        CalibStepInfo(
            id: s,
            done: done.contains(s),
            resultWord: skipped.contains(s) ? 'skipped' : (done.contains(s) ? 'ok' : '·')),
    ];
  }

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
      expect: m['expect'] is Map ? ExpectedShape.fromMap(m['expect']) : null,
      scale: PitchScale.fromMap(m['scale']),
      pos: CalibPos.fromMap(m['pos']),
      hub: [for (final s in _list(m['hub'])) CalibStepInfo.fromMap(s)],
      resume: CalibResume.fromMap(m['resume']),
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

