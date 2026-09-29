import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'backend.dart';
import 'fake_backend.dart';
import 'recorder_fake.dart';
import 'shape_plot.dart';

// The dev-only in-app test recorder + quick record (SHARED CONTRACT §0-§8): what the service sends (`rec_status`,
// `qr_snapshot`), the backend over the `ai.vox/recorder` channel, and [RecorderFlow], the screen's state. The Kotlin
// side (android/.../rec/RecEngine.kt) is the reference; this module codes against the contract through [RecorderBackend]
// and its in-memory fake (recorder_fake.dart), so the screens and tests never touch android/.

double? _d(Object? v) => v is num ? v.toDouble() : null;
int? _i(Object? v) => v is num ? v.round() : null;
String? _s(Object? v) => v is String ? v : null;
Map<Object?, Object?> _m(Object? v) => v is Map ? v.cast<Object?, Object?>() : const {};
List<Object?> _l(Object? v) => v is List ? v : const [];
List<double> _ds(Object? v) => [for (final x in _l(v)) if (x is num) x.toDouble()];

/// The recorder's take states, in order; anything else parses to `idle`.
const _states = {'idle', 'ready', 'countdown', 'recording', 'saved', 'no_sound', 'rate', 'done', 'error'};

/// One background cell of a take (null for `kind: takes`).
@immutable
class RecBg {
  const RecBg({this.name, this.kind, this.level});

  final String? name;
  final String? kind;
  final int? level;

  static RecBg? fromMap(Object? o) {
    if (o is! Map) return null;
    final m = _m(o);
    return RecBg(name: _s(m['name']), kind: _s(m['kind']), level: _i(m['level']));
  }
}

/// The current take (rec_status.take).
@immutable
class RecTake {
  const RecTake({
    this.takeId,
    this.block,
    this.blockTitle,
    this.i = 0,
    this.n = 0,
    this.blockI = 0,
    this.blockN = 0,
    this.cue,
    this.expect = const [],
    this.cond = const {},
    this.bg,
    this.kind = 'takes',
    this.quiet = false,
    this.manual = false,
    this.targetS,
    this.maxS,
    this.seconds,
    this.redo = 0,
  });

  final String? takeId;
  final String? block;
  final String? blockTitle;

  /// 1-based in the profile plan.
  final int i;
  final int n;
  final int blockI;
  final int blockN;
  final String? cue;
  final List<String> expect;
  final Map<String, String> cond;
  final RecBg? bg;
  final String kind;
  final bool quiet;
  final bool manual;
  final double? targetS;
  final double? maxS;
  final double? seconds;
  final int redo;

  static RecTake? fromMap(Object? o) {
    if (o is! Map) return null;
    final m = _m(o);
    return RecTake(
      takeId: _s(m['take_id']),
      block: _s(m['block']),
      blockTitle: _s(m['block_title']),
      i: _i(m['i']) ?? 0,
      n: _i(m['n']) ?? 0,
      blockI: _i(m['block_i']) ?? 0,
      blockN: _i(m['block_n']) ?? 0,
      cue: _s(m['cue']),
      expect: [for (final x in _l(m['expect'])) if (x is String) x],
      cond: {for (final e in _m(m['cond']).entries) '${e.key}': _s(e.value) ?? ''},
      bg: RecBg.fromMap(m['bg']),
      kind: _s(m['kind']) ?? 'takes',
      quiet: m['quiet'] == true,
      manual: m['manual'] == true,
      targetS: _d(m['target_s']),
      maxS: _d(m['max_s']),
      seconds: _d(m['seconds']),
      redo: _i(m['redo']) ?? 0,
    );
  }
}

/// The live level (rec_status.level).
@immutable
class RecLevel {
  const RecLevel({this.barsDb = const [], this.minDb, this.peakDbfs, this.note});

  /// Last 40 ticks of 50 ms RMS dBFS, oldest first.
  final List<double> barsDb;
  final double? minDb;
  final double? peakDbfs;

  /// `quiet` | `good` | `loud`.
  final String? note;

  static RecLevel fromMap(Object? o) {
    final m = _m(o);
    return RecLevel(
      barsDb: _ds(m['bars_db']),
      minDb: _d(m['min_db']),
      peakDbfs: _d(m['peak_dbfs']),
      note: _s(m['note']),
    );
  }
}

/// What the last saved/aborted take heard (rec_status.last).
@immutable
class RecLast {
  const RecLast({this.takeId, this.saved = false, this.durMs, this.reason, this.f0Hz, this.belowF0Min = false});

  final String? takeId;
  final bool saved;
  final int? durMs;

  /// `silence` | `max length` | `fixed` | `no sound` | `aborted`.
  final String? reason;
  final double? f0Hz;
  final bool belowF0Min;

  static RecLast? fromMap(Object? o) {
    if (o is! Map) return null;
    final m = _m(o);
    return RecLast(
      takeId: _s(m['take_id']),
      saved: m['saved'] == true,
      durMs: _i(m['dur_ms']),
      reason: _s(m['reason']),
      f0Hz: _d(m['f0_hz']),
      belowF0Min: m['below_f0_min'] == true,
    );
  }
}

/// One block's progress (rec_status.blocks[]).
@immutable
class RecBlock {
  const RecBlock({
    required this.id,
    required this.title,
    this.intro,
    this.done = 0,
    this.total = 0,
    this.rating,
    this.skipped = 0,
  });

  final String id;
  final String title;
  final String? intro;
  final int done;
  final int total;

  /// 1..5, or null when not rated yet.
  final int? rating;

  /// Takes skipped this sitting.
  final int skipped;

  static RecBlock fromMap(Object? o) {
    final m = _m(o);
    return RecBlock(
      id: _s(m['id']) ?? '?',
      title: _s(m['title']) ?? _s(m['id']) ?? '?',
      intro: _s(m['intro']),
      done: _i(m['done']) ?? 0,
      total: _i(m['total']) ?? 0,
      rating: _i(m['rating']),
      skipped: _i(m['skipped']) ?? 0,
    );
  }
}

/// The next take (rec_status.next).
@immutable
class RecNext {
  const RecNext({this.takeId, this.cue});

  final String? takeId;
  final String? cue;

  static RecNext? fromMap(Object? o) {
    if (o is! Map) return null;
    final m = _m(o);
    return RecNext(takeId: _s(m['take_id']), cue: _s(m['cue']));
  }
}

/// One `rec_status` map.
@immutable
class RecStatus {
  const RecStatus({
    this.enabled = false,
    this.active = false,
    this.name,
    this.speaker,
    this.profile,
    this.mic,
    this.rate,
    this.state = 'idle',
    this.error,
    this.reason,
    this.take,
    this.countdownS,
    this.recS,
    this.level = const RecLevel(),
    this.heard = const [],
    this.last,
    this.blocks = const [],
    this.done = 0,
    this.total = 0,
    this.skipped = 0,
    this.bytes = 0,
    this.next,
    this.plan = const [],
    this.planBlocks = const [],
    this.defaults = const {},
    this.scale,
  });

  final bool enabled;
  final bool active;
  final String? name;
  final String? speaker;
  final String? profile;
  final String? mic;
  final int? rate;

  /// `idle` | `ready` | `countdown` | `recording` | `saved` | `no_sound` | `rate` | `done` | `error` (unknown → idle).
  final String state;
  final String? error;
  final String? reason;
  final RecTake? take;
  final int? countdownS;
  final double? recS;
  final RecLevel level;
  final List<HeardSound> heard;
  final RecLast? last;
  final List<RecBlock> blocks;
  final int done;
  final int total;
  final int skipped;
  final int bytes;
  final RecNext? next;

  /// The take ids of the profile plan in order, and each one's block (null when unknown). An E8 extension to §5
  /// (`plan: [{take_id, block}]`, or plain take ids): the header arrows and the hub rows need it to call
  /// rec_next{take_id}. Absent, it parses to [] and the arrows fall back to rec_redo_last / rec_next.
  final List<String> plan;
  final List<String?> planBlocks;

  /// The first take of [block] in the plan, or null.
  String? firstTakeOf(String block) {
    final i = planBlocks.indexOf(block);
    return i < 0 ? null : plan[i];
  }

  /// `{distances_cm, speed_s, gap_s}` from the spec.
  final Map<String, Object?> defaults;
  final PitchScale? scale;

  static RecStatus fromMap(Object? o) {
    final m = _m(o);
    final rawState = _s(m['state']) ?? 'idle';
    return RecStatus(
      enabled: m['enabled'] == true,
      active: m['active'] == true,
      name: _s(m['name']),
      speaker: _s(m['speaker']),
      profile: _s(m['profile']),
      mic: _s(m['mic']),
      rate: _i(m['rate']),
      state: _states.contains(rawState) ? rawState : 'idle',
      error: _s(m['error']),
      reason: _s(m['reason']),
      take: RecTake.fromMap(m['take']),
      countdownS: _i(m['countdown_s']),
      recS: _d(m['rec_s']),
      level: RecLevel.fromMap(m['level']),
      heard: [for (final h in _l(m['heard'])) HeardSound.fromMap(h)],
      last: RecLast.fromMap(m['last']),
      blocks: [for (final b in _l(m['blocks'])) RecBlock.fromMap(b)],
      done: _i(m['done']) ?? 0,
      total: _i(m['total']) ?? 0,
      skipped: _i(m['skipped']) ?? 0,
      bytes: _i(m['bytes']) ?? 0,
      next: RecNext.fromMap(m['next']),
      plan: [for (final x in _l(m['plan'])) if (x is String) x else if (_s(_m(x)['take_id']) != null) _s(_m(x)['take_id'])!],
      planBlocks: [for (final x in _l(m['plan'])) if (x is String) null else if (_s(_m(x)['take_id']) != null) _s(_m(x)['block'])],
      defaults: _m(m['defaults']).cast<String, Object?>(),
      scale: PitchScale.fromMap(m['scale']),
    );
  }
}

/// One saved session in rec_list.sessions.
@immutable
class RecSessionInfo {
  const RecSessionInfo({
    required this.name,
    this.speaker,
    this.profile,
    this.mic,
    this.rate,
    this.done = 0,
    this.total = 0,
    this.backgroundsDone = 0,
    this.backgroundsTotal = 0,
    this.ratedBlocks = 0,
    this.bytes = 0,
    this.open = false,
  });

  final String name;
  final String? speaker;
  final String? profile;
  final String? mic;
  final int? rate;
  final int done;
  final int total;
  final int backgroundsDone;
  final int backgroundsTotal;
  final int ratedBlocks;
  final int bytes;
  final bool open;

  static RecSessionInfo fromMap(Object? o) {
    final m = _m(o);
    return RecSessionInfo(
      name: _s(m['name']) ?? '?',
      speaker: _s(m['speaker']),
      profile: _s(m['profile']),
      mic: _s(m['mic']),
      rate: _i(m['rate']),
      done: _i(m['done']) ?? 0,
      total: _i(m['total']) ?? 0,
      backgroundsDone: _i(m['backgrounds_done']) ?? 0,
      backgroundsTotal: _i(m['backgrounds_total']) ?? 0,
      ratedBlocks: _i(m['rated_blocks']) ?? 0,
      bytes: _i(m['bytes']) ?? 0,
      open: m['open'] == true,
    );
  }
}

/// The most recent Canti action in a quick-rec snapshot.
@immutable
class QuickAction {
  const QuickAction({this.text, this.agoS, this.inClip = false});

  final String? text;
  final double? agoS;
  final bool inClip;

  static QuickAction? fromMap(Object? o) {
    if (o is! Map) return null;
    final m = _m(o);
    return QuickAction(text: _s(m['text']), agoS: _d(m['ago_s']), inClip: m['in_clip'] == true);
  }
}

/// One quick-record snapshot (qr_snap / qr_pending).
@immutable
class QuickSnapshot {
  const QuickSnapshot({
    this.id,
    this.seconds = 0,
    this.rate,
    this.barsDb = const [],
    this.minDb,
    this.sounds = const [],
    this.lastAction,
    this.app,
    this.mode,
  });

  final String? id;
  final int seconds;
  final int? rate;

  /// 100 ms RMS dBFS over the clip, oldest first.
  final List<double> barsDb;
  final double? minDb;
  final List<HeardSound> sounds;
  final QuickAction? lastAction;
  final String? app;
  final String? mode;

  static QuickSnapshot fromMap(Object? o) {
    final m = _m(o);
    return QuickSnapshot(
      id: _s(m['id']),
      seconds: _i(m['seconds']) ?? 0,
      rate: _i(m['rate']),
      barsDb: _ds(m['bars_db']),
      minDb: _d(m['min_db']),
      sounds: [for (final s in _l(m['sounds'])) HeardSound.fromMap(s)],
      lastAction: QuickAction.fromMap(m['last_action']),
      app: _s(m['app']),
      mode: _s(m['mode']),
    );
  }
}

/// A rec_* command the service refused (its answer's `error`).
class RecCommandError implements Exception {
  RecCommandError(this.message);
  final String message;
  @override
  String toString() => message;
}

/// The recorder service over the `ai.vox/recorder` channel. Every command answers a map (with `error` when refused);
/// Kotlin pushes `rec_status` and `qr_snapshot` maps on the same channel.
abstract class RecorderBackend {
  Future<Map<String, Object?>> recList();
  Future<Map<String, Object?>> recStart({String? who, String? speaker, String? profile});
  Future<Map<String, Object?>> recOpen(String name);
  Future<Map<String, Object?>> recStatus();
  Future<Map<String, Object?>> recNext({String? takeId});
  Future<Map<String, Object?>> recGo();
  Future<Map<String, Object?>> recAbort();
  Future<Map<String, Object?>> recSkip();
  Future<Map<String, Object?>> recRedoLast();
  Future<Map<String, Object?>> recRate({required String block, required int rating, String? note});
  Future<Map<String, Object?>> recClose();
  Future<Map<String, Object?>> recClear({List<String>? sessions, Object? quickrec});
  Future<Map<String, Object?>> qrSnap();
  Future<Map<String, Object?>> qrPending();
  Future<Map<String, Object?>> qrSave({required String id, required String label, String? note, int? sound});
  Future<Map<String, Object?>> qrDiscard(String id);

  /// The service's `rec_status` pushes (on every change, every 100 ms while ready/countdown/recording) and each
  /// command's answer.
  Stream<Map<String, Object?>> statusStream();

  /// The service's `qr_snapshot` pushes (when a snapshot is taken from the badge).
  Stream<Map<String, Object?>> snapshotStream();
}

final _fakes = Expando<FakeRecorderBackend>('recorder');
ChannelRecorderBackend? _channel;

/// The recorder backend that goes with [backend]: the `ai.vox/recorder` channel on the phone, an in-memory fake for a
/// [FakeBackend] (tests, the desktop runner).
RecorderBackend recorderBackendFor(VoxBackend backend) {
  if (backend is FakeBackend) {
    return _fakes[backend] ??= FakeRecorderBackend(source: backend.current.soundSource ?? 'phone');
  }
  return _channel ??= ChannelRecorderBackend();
}

/// Makes [recorderBackendFor] answer [fake] for [backend] (the desktop preview, tests).
void useRecorderBackend(FakeBackend backend, FakeRecorderBackend fake) => _fakes[backend] = fake;

/// [RecorderBackend] over the `ai.vox/recorder` method channel (android UiBridge.kt).
class ChannelRecorderBackend implements RecorderBackend {
  ChannelRecorderBackend({MethodChannel? methods}) : _methods = methods ?? const MethodChannel(channelName) {
    _methods.setMethodCallHandler((call) async {
      if (call.method == 'rec_status' && call.arguments is Map) {
        _status.add(_map(call.arguments));
      } else if (call.method == 'qr_snapshot' && call.arguments is Map) {
        _snap.add(_map(call.arguments));
      }
      return null;
    });
  }

  static const channelName = 'ai.vox/recorder';
  final MethodChannel _methods;
  final _status = StreamController<Map<String, Object?>>.broadcast();
  final _snap = StreamController<Map<String, Object?>>.broadcast();

  static Map<String, Object?> _map(Object? o) => o is Map ? o.cast<String, Object?>() : const {};

  Future<Map<String, Object?>> _call(String method, [Map<String, Object?>? args]) async {
    final r = _map(await _methods.invokeMapMethod<Object?, Object?>(method, args));
    if (method.startsWith('rec_') && _isStatus(r)) _status.add(r);
    if (r['error'] != null) throw RecCommandError('${r['error']}');
    return r;
  }

  bool _isStatus(Map<String, Object?> m) => m.containsKey('active') || m.containsKey('state');

  @override
  Future<Map<String, Object?>> recList() => _call('rec_list');
  @override
  Future<Map<String, Object?>> recStart({String? who, String? speaker, String? profile}) =>
      _call('rec_start', {'who': ?who, 'speaker': ?speaker, 'profile': ?profile});
  @override
  Future<Map<String, Object?>> recOpen(String name) => _call('rec_open', {'name': name});
  @override
  Future<Map<String, Object?>> recStatus() => _call('rec_status');
  @override
  Future<Map<String, Object?>> recNext({String? takeId}) => _call('rec_next', {'take_id': ?takeId});
  @override
  Future<Map<String, Object?>> recGo() => _call('rec_go');
  @override
  Future<Map<String, Object?>> recAbort() => _call('rec_abort');
  @override
  Future<Map<String, Object?>> recSkip() => _call('rec_skip');
  @override
  Future<Map<String, Object?>> recRedoLast() => _call('rec_redo_last');
  @override
  Future<Map<String, Object?>> recRate({required String block, required int rating, String? note}) =>
      _call('rec_rate', {'block': block, 'rating': rating, 'note': ?note});
  @override
  Future<Map<String, Object?>> recClose() => _call('rec_close');
  @override
  Future<Map<String, Object?>> recClear({List<String>? sessions, Object? quickrec}) =>
      _call('rec_clear', {'sessions': ?sessions, 'quickrec': ?quickrec});
  @override
  Future<Map<String, Object?>> qrSnap() async {
    final r = await _call('qr_snap');
    _snap.add(r);
    return r;
  }

  @override
  Future<Map<String, Object?>> qrPending() => _call('qr_pending');

  @override
  Future<Map<String, Object?>> qrSave({required String id, required String label, String? note, int? sound}) =>
      _call('qr_save', {'id': id, 'label': label, 'note': ?note, 'sound': ?sound});

  @override
  Future<Map<String, Object?>> qrDiscard(String id) => _call('qr_discard', {'id': id});

  @override
  Stream<Map<String, Object?>> statusStream() => _status.stream;
  @override
  Stream<Map<String, Object?>> snapshotStream() => _snap.stream;
}

/// The recorder screen's state: the latest status, the session list, a pending error and busy flag.
class RecorderFlow extends ChangeNotifier {
  RecorderFlow({required this.backend});

  final RecorderBackend backend;
  RecStatus? status;
  List<RecSessionInfo> sessions = const [];
  bool busy = false;
  String? error;
  StreamSubscription<Map<String, Object?>>? _sub;
  bool _disposed = false;

  /// Listens to the pushes, then loads the status and the saved sessions (the start screen lists them to resume).
  void attach() {
    _sub ??= backend.statusStream().listen((m) => _onStatus(RecStatus.fromMap(m)));
    refresh();
    loadSessions();
  }

  void _onStatus(RecStatus s) {
    if (_disposed) return;
    status = s;
    notifyListeners();
  }

  Future<void> refresh() => _run('status', backend.recStatus);

  Future<void> loadSessions() async {
    if (_disposed) return;
    try {
      final r = await backend.recList();
      sessions = [for (final s in _l(r['sessions'])) RecSessionInfo.fromMap(s)];
    } catch (e) {
      error = 'list: $e';
    }
    if (!_disposed) notifyListeners();
  }

  Future<void> start({String? who, String? speaker, String? profile}) =>
      _run('start', () => backend.recStart(who: who, speaker: speaker, profile: profile));

  Future<void> open(String name) => _run('open', () => backend.recOpen(name));

  Future<void> next({String? takeId}) => _run('next', () => backend.recNext(takeId: takeId));

  Future<void> go() => _run('go', backend.recGo);
  Future<void> abort() => _run('abort', backend.recAbort);
  Future<void> skip() => _run('skip', backend.recSkip);
  Future<void> redoLast() => _run('redo', backend.recRedoLast);

  Future<void> rate({required String block, required int rating, String? note}) =>
      _run('rate', () => backend.recRate(block: block, rating: rating, note: note));

  /// Ends the sitting (every saved take stays on disk; the session is resumable from the list). A no-op when none is
  /// open.
  Future<void> close() async {
    if (status?.active != true) return;
    await _run('close', backend.recClose);
    await loadSessions();
  }

  void dismissError() {
    error = null;
    notifyListeners();
  }

  Future<void> _run(String what, Future<Map<String, Object?>> Function() f) async {
    if (_disposed) return;
    busy = true;
    error = null;
    notifyListeners();
    try {
      final r = await f();
      if (_disposed) return;
      status = RecStatus.fromMap(r);
    } on RecCommandError catch (e) {
      error = e.message;
    } catch (e) {
      error = '$what: $e';
    } finally {
      busy = false;
      if (!_disposed) notifyListeners();
    }
  }

  @override
  void dispose() {
    _disposed = true;
    _sub?.cancel();
    super.dispose();
  }
}
