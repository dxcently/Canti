import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'backend.dart';
import 'fake_backend.dart';
import 'train_fake.dart';

// Gesture training (android/PROTOCOL.md "Gesture training", GestureTraining.kt): the user records their own version of
// every gesture, with variations, into the enrollment store of the current mic source. What the service sends
// (`train_status`), the backend over the `ai.vox/train` channel, and [TrainFlow], the screen's state.

/// The eight gestures, in card order.
const trainGestures = ['rise', 'fall', 'arch', 'dip', 'flat', 'pop', 'click', 'hiss'];

/// The mic sources, each with its own store.
const trainSources = ['phone', 'usb', 'pico'];

double? _d(Object? v) => v is num ? v.toDouble() : null;
int? _i(Object? v) => v is num ? v.round() : null;
String? _s(Object? v) => v is String ? v : null;
Map<Object?, Object?> _m(Object? v) => v is Map ? v.cast<Object?, Object?>() : const {};
List<Object?> _l(Object? v) => v is List ? v : const [];
List<String> _strs(Object? v) => [
  for (final x in _l(v))
    if (x is String) x,
];

/// One cell of a gesture's plan (one take): `hum-low-slow`, `soft-1`, ...
@immutable
class TrainCell {
  const TrainCell({required this.id, required this.prompt, this.done = false, this.tags = const {}});

  final String id;
  final String prompt;
  final bool done;
  final Map<String, String> tags;

  static TrainCell fromMap(Object? o) {
    final m = _m(o);
    return TrainCell(
      id: _s(m['id']) ?? '?',
      prompt: _s(m['prompt']) ?? '',
      done: m['done'] == true,
      tags: {for (final e in _m(m['tags']).entries) '${e.key}': '${e.value}'},
    );
  }
}

/// A gesture card: its cells and how many are recorded.
@immutable
class TrainGesture {
  const TrainGesture({
    required this.name,
    this.kind = 'contour',
    this.done = 0,
    this.total = 0,
    this.examples = 0,
    this.extra = 0,
    this.active = false,
    this.kept = 0,
    this.cells = const [],
  });

  final String name;

  /// `contour` or `discrete`.
  final String kind;
  final int done;
  final int total;

  /// Examples in the class (the cells plus [extra], enrolled some other way).
  final int examples;
  final int extra;

  /// The class has 3+ examples: the matcher uses it.
  final bool active;

  /// Takes kept anyway (the wrong shape, stored as this gesture).
  final int kept;
  final List<TrainCell> cells;

  bool get complete => total > 0 && done >= total;

  static TrainGesture fromMap(Object? o) {
    final m = _m(o);
    return TrainGesture(
      name: _s(m['name']) ?? '?',
      kind: _s(m['kind']) ?? 'contour',
      done: _i(m['done']) ?? 0,
      total: _i(m['total']) ?? 0,
      examples: _i(m['examples']) ?? 0,
      extra: _i(m['extra']) ?? 0,
      active: m['active'] == true,
      kept: _i(m['kept']) ?? 0,
      cells: [for (final c in _l(m['cells'])) TrainCell.fromMap(c)],
    );
  }
}

/// What the extractor heard in a take.
@immutable
class TrainHeard {
  const TrainHeard({
    this.label,
    this.line,
    this.sounds = 1,
    this.labels = const [],
    this.durMs,
    this.f0Hz,
    this.startHz,
    this.tone,
    this.loudness,
    this.pitch16 = const [],
    this.shape,
  });

  final String? label;
  final String? line;
  final int sounds;
  final List<String> labels;
  final int? durMs;
  final int? f0Hz;
  final int? startHz;

  /// `hum` or `whistle` (by f0 band), or null.
  final String? tone;
  final String? loudness;

  /// The extractor's contour, 16 points in semitones from the start (empty for pop, click, hiss).
  final List<double> pitch16;

  /// What that label is ("goes up then down").
  final String? shape;

  static TrainHeard? fromMap(Object? o) {
    if (o is! Map) return null;
    final m = _m(o);
    return TrainHeard(
      label: _s(m['label']),
      line: _s(m['line']),
      sounds: _i(m['sounds']) ?? 1,
      labels: _strs(m['labels']),
      durMs: _i(m['dur_ms']),
      f0Hz: _i(m['f0_hz']),
      startHz: _i(m['start_hz']),
      tone: _s(m['tone']),
      loudness: _s(m['loudness']),
      pitch16: [
        for (final x in _l(m['pitch16']))
          if (x is num) x.toDouble(),
      ],
      shape: _s(m['shape']),
    );
  }
}

/// The mic right now, while a take records (phone / USB mic only).
@immutable
class TrainLive {
  const TrainLive({this.traceHz = const [], this.levelDb, this.pitchHz});

  /// One pitch per 20 ms tick, oldest first; null = unvoiced.
  final List<double?> traceHz;
  final double? levelDb;
  final double? pitchHz;

  static TrainLive fromMap(Object? o) {
    final m = _m(o);
    return TrainLive(
      traceHz: [for (final x in _l(m['trace_hz'])) _d(x)],
      levelDb: _d(m['level_db']),
      pitchHz: _d(m['pitch_hz']),
    );
  }
}

/// The open training round: one gesture's cells, one prompt at a time.
@immutable
class TrainSession {
  const TrainSession({
    required this.gesture,
    required this.state,
    this.source,
    this.cell,
    this.prompt,
    this.hint,
    this.index = 0,
    this.count = 0,
    this.nextPrompt,
    this.reason,
    this.canKeep = false,
    this.heard,
    this.heardN = 0,
    this.leftMs,
    this.live = const TrainLive(),
    this.passed = const [],
    this.skipped = const [],
    this.kept = const [],
  });

  final String gesture;

  /// `ready`, `recording`, `passed`, `failed` or `done`.
  final String state;
  final String? source;
  final String? cell;
  final String? prompt;
  final String? hint;
  final int index;
  final int count;
  final String? nextPrompt;
  final String? reason;
  final bool canKeep;
  final TrainHeard? heard;
  final int heardN;
  final int? leftMs;
  final TrainLive live;
  final List<String> passed;
  final List<String> skipped;
  final List<String> kept;

  static TrainSession? fromMap(Object? o) {
    if (o is! Map) return null;
    final m = _m(o);
    return TrainSession(
      gesture: _s(m['gesture']) ?? '?',
      state: _s(m['state']) ?? 'ready',
      source: _s(m['source']),
      cell: _s(m['cell']),
      prompt: _s(m['prompt']),
      hint: _s(m['hint']),
      index: _i(m['index']) ?? 0,
      count: _i(m['count']) ?? 0,
      nextPrompt: _s(m['next_prompt']),
      reason: _s(m['reason']),
      canKeep: m['can_keep'] == true,
      heard: TrainHeard.fromMap(m['heard']),
      heardN: _i(m['heard_n']) ?? 0,
      leftMs: _i(m['left_ms']),
      live: TrainLive.fromMap(m['live']),
      passed: _strs(m['passed']),
      skipped: _strs(m['skipped']),
      kept: _strs(m['kept']),
    );
  }
}

/// One `train_status` map.
@immutable
class TrainStatus {
  const TrainStatus({
    this.service = true,
    this.active = false,
    this.source = 'phone',
    this.currentSource = 'phone',
    this.profile,
    this.liveTrace = false,
    this.blocked,
    this.done = 0,
    this.total = 0,
    this.gestures = const [],
    this.session,
    this.sources = const {},
    this.error,
  });

  /// False when the service is off (nothing else is meaningful then).
  final bool service;
  final bool active;

  /// Whose cards these are, and the source sounds come from now (only it can be trained).
  final String source;
  final String currentSource;
  final String? profile;

  /// The current source gives a live pitch trace (phone / USB mic).
  final bool liveTrace;

  /// Why a take cannot be recorded now (paused, cursor mode, mic off, ...), or null.
  final String? blocked;
  final int done;
  final int total;
  final List<TrainGesture> gestures;
  final TrainSession? session;

  /// Per source: (done, total).
  final Map<String, (int, int)> sources;

  /// The command was refused: why.
  final String? error;

  bool get trainable => source == currentSource;

  TrainGesture? gesture(String name) {
    for (final g in gestures) {
      if (g.name == name) return g;
    }
    return null;
  }

  static TrainStatus fromMap(Object? o) {
    final m = _m(o);
    return TrainStatus(
      service: m['service'] != false,
      active: m['active'] == true,
      source: _s(m['source']) ?? 'phone',
      currentSource: _s(m['current_source']) ?? _s(m['source']) ?? 'phone',
      profile: _s(m['profile']),
      liveTrace: m['live_trace'] == true,
      blocked: _s(m['blocked']),
      done: _i(m['done']) ?? 0,
      total: _i(m['total']) ?? 0,
      gestures: [for (final g in _l(m['gestures'])) TrainGesture.fromMap(g)],
      session: TrainSession.fromMap(m['session']),
      sources: {
        for (final e in _m(m['sources']).entries)
          '${e.key}': (_i(_m(e.value)['done']) ?? 0, _i(_m(e.value)['total']) ?? 0),
      },
      error: _s(m['error']),
    );
  }
}

/// A train_* command the service refused (its answer's `error`).
class TrainCommandError implements Exception {
  TrainCommandError(this.message);
  final String message;
  @override
  String toString() => message;
}

/// The service's gesture training. Every command answers the status after it (and pushes it to [pushes]).
abstract class TrainBackend {
  Future<TrainStatus> status({String? source});
  Future<TrainStatus> start(String gesture, {String? cell});
  Future<TrainStatus> record();
  Future<TrainStatus> retry();
  Future<TrainStatus> skip();
  Future<TrainStatus> keep();
  Future<TrainStatus> next({bool record = true});
  Future<TrainStatus> cancel();
  Future<TrainStatus> delete(String gesture, {String? cell, String? source});

  /// The service's `train_status` pushes (on every change, about 10 Hz while a take records) and every answer.
  Stream<TrainStatus> pushes();
}

final _fakes = Expando<FakeTrainBackend>('train');
ChannelTrainBackend? _channel;

/// The training backend that goes with [backend]: the `ai.vox/train` channel on the phone, an in-memory fake for a
/// [FakeBackend] (tests, the desktop runner).
TrainBackend trainBackendFor(VoxBackend backend) {
  if (backend is FakeBackend) {
    return _fakes[backend] ??= FakeTrainBackend(source: backend.current.soundSource ?? 'phone');
  }
  return _channel ??= ChannelTrainBackend();
}

/// Makes [trainBackendFor] answer [fake] for [backend] (the desktop preview, tests).
void useTrainBackend(FakeBackend backend, FakeTrainBackend fake) => _fakes[backend] = fake;

/// [TrainBackend] over the `ai.vox/train` method channel (android UiBridge.kt): `train_status {source?}`,
/// `train_start {gesture, cell?}`, `train_record`, `train_retry`, `train_skip`, `train_keep`, `train_next {record?}`,
/// `train_cancel`, `train_delete {gesture, cell?, source?}` answer the status map (with `error` when refused); Kotlin
/// calls `train_status {map}` on the same channel on every change.
class ChannelTrainBackend implements TrainBackend {
  ChannelTrainBackend({MethodChannel? methods}) : _methods = methods ?? const MethodChannel(channelName) {
    _methods.setMethodCallHandler((call) async {
      if (call.method == 'train_status' && call.arguments is Map) _out.add(TrainStatus.fromMap(call.arguments));
      return null;
    });
  }

  static const channelName = 'ai.vox/train';
  final MethodChannel _methods;
  final _out = StreamController<TrainStatus>.broadcast();

  Future<TrainStatus> _call(String method, [Map<String, Object?>? args]) async {
    final s = TrainStatus.fromMap(await _methods.invokeMethod<Object?>(method, args));
    _out.add(s);
    if (s.error != null) throw TrainCommandError(s.error!);
    return s;
  }

  @override
  Future<TrainStatus> status({String? source}) => _call('train_status', {'source': ?source});
  @override
  Future<TrainStatus> start(String gesture, {String? cell}) =>
      _call('train_start', {'gesture': gesture, 'cell': ?cell});
  @override
  Future<TrainStatus> record() => _call('train_record');
  @override
  Future<TrainStatus> retry() => _call('train_retry');
  @override
  Future<TrainStatus> skip() => _call('train_skip');
  @override
  Future<TrainStatus> keep() => _call('train_keep');
  @override
  Future<TrainStatus> next({bool record = true}) => _call('train_next', {'record': record});
  @override
  Future<TrainStatus> cancel() => _call('train_cancel');
  @override
  Future<TrainStatus> delete(String gesture, {String? cell, String? source}) =>
      _call('train_delete', {'gesture': gesture, 'cell': ?cell, 'source': ?source});
  @override
  Stream<TrainStatus> pushes() => _out.stream;
}

/// The training screen's state: the latest status, the selected card, a pending delete, the last error.
class TrainFlow extends ChangeNotifier {
  TrainFlow({required this.backend});

  final TrainBackend backend;
  TrainStatus? status;
  String? error;
  bool busy = false;

  /// The card whose cells are shown (and whose round runs).
  String? selected;

  /// The card whose Delete / redo waits for its confirmation.
  String? confirmDelete;
  StreamSubscription<TrainStatus>? _sub;
  bool _disposed = false;

  TrainSession? get session => status?.session;

  void attach() {
    _sub ??= backend.pushes().listen(_onStatus);
    refresh();
  }

  void _onStatus(TrainStatus s) {
    if (_disposed) return;
    // a push without the cards (none today) never blanks them; the one without a session ends the round
    status = s;
    if (s.session != null) selected = s.session!.gesture;
    notifyListeners();
  }

  Future<void> refresh() => _run('status', () => backend.status());

  void select(String gesture) {
    if (session != null) return;
    selected = selected == gesture ? null : gesture;
    confirmDelete = null;
    notifyListeners();
  }

  Future<void> startRound(String gesture, {String? cell}) async {
    await _run('start', () => backend.start(gesture, cell: cell));
    if (error == null && session?.state == 'ready') await record();
  }

  Future<void> record() => _run('record', backend.record);
  Future<void> retry() => _run('retry', backend.retry);
  Future<void> skip() => _run('skip', backend.skip);
  Future<void> keep() => _run('keep', backend.keep);
  Future<void> next() => _run('next', () => backend.next());
  Future<void> stop() => _run('stop', backend.cancel);

  /// First press arms it, the second deletes the card's takes.
  Future<void> delete(String gesture) async {
    if (confirmDelete != gesture) {
      confirmDelete = gesture;
      notifyListeners();
      return;
    }
    confirmDelete = null;
    await _run('delete', () => backend.delete(gesture));
  }

  void dismissError() {
    error = null;
    notifyListeners();
  }

  Future<void> _run(String what, Future<TrainStatus> Function() f) async {
    if (_disposed) return;
    busy = true;
    error = null;
    notifyListeners();
    try {
      final s = await f();
      if (_disposed) return;
      status = s;
      if (s.session != null) selected = s.session!.gesture;
    } on TrainCommandError catch (e) {
      error = e.message;
    } catch (e) {
      error = '$what: $e';
    } finally {
      busy = false;
      if (!_disposed) notifyListeners();
    }
  }

  /// The screen goes away: end an open round (its accepted takes stay stored).
  Future<void> close() async {
    if (session != null) {
      try {
        await backend.cancel();
      } catch (_) {}
    }
  }

  @override
  void dispose() {
    _disposed = true;
    _sub?.cancel();
    super.dispose();
  }
}
