import 'dart:async';
import 'dart:collection';
import 'dart:math' as math;

import 'recorder.dart';
import 'shape_plot.dart';

// An in-memory [RecorderBackend] for tests and the desktop runner. It runs the whole §5 state machine in Dart on a
// controllable clock (tests call [advance]; with [auto] a timer drives it for the desktop preview), over a short plan
// of 8 takes in 4 blocks: contours (rise/fall/arch — fall is `table`, arch is `across`, so they count down), discrete
// (click, hiss, a pop pop combo), the quiet room take and a manual background. The phone's RecEngine.kt is the reference.

const _readMs = 1500; // READY_MS: a non-manual take calls rec_go this long after rec_next
const _countdownMs = 3000;
const _savedHoldMs = 1500; // SAVED_HOLD_MS

class _Cell {
  _Cell({
    required this.takeId,
    required this.block,
    required this.blockTitle,
    required this.i,
    required this.n,
    required this.blockI,
    this.blockN = 0,
    required this.cue,
    required this.expect,
    required this.cond,
    this.kind = 'takes',
    this.quiet = false,
    this.manual = false,
    this.targetS,
    this.maxS,
    this.seconds,
    this.bg,
  });

  final String takeId;
  final String block;
  final String blockTitle;
  final int i;
  final int n;
  final int blockI;
  int blockN;
  final String cue;
  final List<String> expect;
  final Map<String, String> cond;
  final String kind;
  final bool quiet;
  final bool manual;
  final double? targetS;
  final double? maxS;
  final double? seconds;
  final Map<String, Object?>? bg;
  int redo = 0;
}

class _Block {
  _Block(this.id, this.title, this.intro);
  final String id;
  final String title;
  final String intro;
  final cells = <_Cell>[];
}

Map<String, String> _cond(String tone, String pitch, String speed, String loud, String dist, String gap) =>
    {'tone': tone, 'pitch': pitch, 'speed': speed, 'loud': loud, 'dist': dist, 'gap': gap};

/// The short plan the fake runs (a subset of the real short profile, with the spec's own cue wording).
List<_Block> _plan() {
  final contours = _Block('contours', 'Contours', 'Centre = hum at your home note.');
  final discrete = _Block('discrete', 'Discrete', 'One mouth sound per GO; two for the combos.');
  final room = _Block('room', 'Room', 'Canti measures the room: stay quiet.');
  final backgrounds = _Block('backgrounds', 'Backgrounds', 'Remain silent for each recording.');

  const n = 8;
  var i = 1;
  void take(_Block b, String id, List<String> expect, Map<String, String> cond, String cue,
      {bool manual = false, double targetS = 0.6, double maxS = 2.5, Map<String, Object?>? bg, bool quiet = false, double? seconds}) {
    b.cells.add(_Cell(
      takeId: id,
      block: b.id,
      blockTitle: b.title,
      i: i,
      n: n,
      blockI: b.cells.length + 1,
      blockN: 0, // set below
      cue: cue,
      expect: expect,
      cond: cond,
      kind: bg == null ? 'takes' : 'backgrounds',
      quiet: quiet,
      manual: manual,
      targetS: targetS,
      maxS: maxS,
      seconds: seconds,
      bg: bg,
    ));
    i++;
  }

  take(contours, 'rise', ['rise'], _cond('hum', 'home', 'normal', 'normal', 'hand', 'na'),
      'RISE · centre · about 0.6 s');
  take(contours, 'fall', ['fall'], _cond('hum', 'home', 'normal', 'normal', 'table', 'na'),
      'FALL · dist table · about 0.6 s');
  take(contours, 'arch', ['arch'], _cond('whistle', 'home', 'quick', 'normal', 'across', 'na'),
      'ARCH · tone whistle · speed quick · dist across · about 0.3 s', targetS: 0.3);
  take(discrete, 'click', ['click'], _cond('na', 'na', 'na', 'normal', 'hand', 'na'),
      'CLICK · centre · about 0.3 s', targetS: 0.3, maxS: 2.3);
  take(discrete, 'hiss', ['hiss'], _cond('na', 'na', 'na', 'normal', 'hand', 'na'),
      'HISS · centre · about 0.3 s', targetS: 0.3, maxS: 2.3);
  take(discrete, 'pop-pop', ['pop', 'pop'], _cond('na', 'na', 'na', 'normal', 'hand', 'normal'),
      'POP POP · centre · gap normal', targetS: 0.6, maxS: 3);
  take(room, 'room', [], _cond('na', 'na', 'na', 'na', 'na', 'na'), 'Stay quiet for 3 seconds',
      targetS: 3, maxS: 3.5, quiet: true);
  // the spec's longest cue; the fake records it for 5 s instead of 60 so tests stay fast
  take(backgrounds, 'media-90', [], _cond('na', 'na', 'na', 'na', 'na', 'na'),
      'Play a Reel/Short on phone or laptop speakers at 90%; stay silent for 60 s',
      manual: true, targetS: 5, maxS: 5, seconds: 5, bg: {'name': 'media-90', 'kind': 'media', 'level': 90});

  for (final b in [contours, discrete, room, backgrounds]) {
    for (final c in b.cells) {
      c.blockN = b.cells.length;
    }
  }
  return [contours, discrete, room, backgrounds];
}

/// A 16-point contour in semitones for a contour label.
List<double> _pitch16(String label) => [
      for (var i = 0; i < 16; i++)
        switch (label) {
          'rise' => 4 * i / 15,
          'fall' => -4 * i / 15,
          'arch' => 4 * math.sin(math.pi * i / 15),
          'dip' => -4 * math.sin(math.pi * i / 15),
          _ => 0.0,
        },
    ];

class _Session {
  _Session(this.name, this.speaker, this.profile, this.mic, this.rate);

  final String name;
  final String speaker;
  final String profile;
  final String mic;
  final int rate;
  final saved = <String>{};
  final skipped = <String>{};
  final ratings = <String, (int, String?)>{};
}

/// The in-memory recorder. A take finishes by itself after [auto] (desktop) or as tests advance the clock with
/// [advance]; [noSoundTakes] scripts which takes record "no sound"; [scale] is the source's calibration (default: none,
/// so the contour plot uses its relative fallback).
class FakeRecorderBackend implements RecorderBackend {
  FakeRecorderBackend({
    this.source = 'phone',
    this.auto,
    this.scale,
    this.enabled = true,
    this.rate = 16000,
    this.freeBytes = 4 << 30,
  }) {
    final a = auto;
    if (a != null) _timer = Timer.periodic(a, (_) => advance(a));
  }

  /// The current sound source (`phone` | `usb` | `pico`). `pico` refuses a start.
  String source;

  /// When set, a timer drives [advance] for the desktop preview; without it tests advance the clock by hand.
  Duration? auto;

  /// The source's saved calibration scale, or null (the contour plot's relative fallback).
  PitchScale? scale;

  final bool enabled;
  final int rate;

  /// The take ids that record "no sound" (their attempt is kept, the UI offers Try again / Skip).
  final noSoundTakes = <String>{};

  /// Every command, in order (`rec_next rise`, `rec_rate contours 3`, ...).
  final calls = <String>[];

  /// The last rec_next take id, for the pager test.
  String? lastNextTakeId;

  /// The wall clock, in ms. Tests advance it with [advance].
  int now = 0;

  int freeBytes;
  final sessions = <String, _Session>{};

  _Session? _s;
  final _blocks = _plan();
  List<_Cell> get _cells => [for (final b in _blocks) ...b.cells];
  _Cell? _take;
  String _state = 'idle';
  String? _error;
  String? _reason;
  RecLevel _level = const RecLevel();
  final _heard = <HeardSound>[];
  Map<String, Object?>? _last;
  int _countdown = 0;
  double _recS = 0;
  _Cell? _lastSaved; // rec_redo_last: the previously saved take of this sitting

  // quick record
  Map<String, Object?>? _pending;
  final _savedQuick = <String>[];

  Timer? _timer;
  final _out = StreamController<Map<String, Object?>>.broadcast(sync: true);
  final _snap = StreamController<Map<String, Object?>>.broadcast(sync: true);
  final _queue = SplayTreeMap<int, List<void Function()>>();

  /// Advances the controllable clock by [d], firing any scheduled transitions.
  void advance(Duration d) => _tick(d.inMilliseconds);

  void _after(int ms, void Function() f) {
    final t = now + ms;
    _queue.putIfAbsent(t, () => []).add(f);
  }

  void _tick(int ms) {
    now += ms;
    var n = 0;
    while (_queue.isNotEmpty && _queue.firstKey()! <= now) {
      final fs = _queue.remove(_queue.firstKey()!)!;
      for (final f in fs) {
        f();
      }
      // guard against a transition that schedules at the same instant forever
      if (++n > 1000) break;
    }
    if (_state == 'recording') {
      // animate the level bars once per 50 ms tick (up to 40)
      final ticks = ms ~/ 50;
      for (var k = 0; k < ticks; k++) {
        _recS += 0.05;
        final bars = [..._level.barsDb];
        final wave = math.sin((now + k * 50) / 180).toDouble();
        final v = _take?.quiet == true ? -70 + 3 * wave : -44 + 8 * wave;
        bars.add(v);
        if (bars.length > 40) bars.removeAt(0);
        final peak = bars.isEmpty ? null : bars.reduce(math.max);
        final note = peak != null && peak >= -1 ? 'loud' : (peak != null && peak <= -60 ? 'quiet' : 'good');
        _level = RecLevel(barsDb: bars, minDb: -55, peakDbfs: peak, note: note);
      }
      if (ms ~/ 50 > 0) _push();
    }
  }

  _Session _need() => _s ?? (throw RecCommandError('no session open: start one first'));

  /// The first take that has no label/background row and is not skipped this sitting.
  _Cell? _nextCell() {
    final s = _s;
    if (s == null) return null;
    for (final c in _cells) {
      if (!s.saved.contains(c.takeId) && !s.skipped.contains(c.takeId)) return c;
    }
    return null;
  }

  _Cell? _cellById(String id) {
    for (final c in _cells) {
      if (c.takeId == id) return c;
    }
    return null;
  }

  bool _blockDone(_Block b) {
    final s = _s;
    if (s == null) return false;
    return b.cells.every((c) => s.saved.contains(c.takeId) || s.skipped.contains(c.takeId));
  }

  void _go() {
    final c = _take;
    if (c == null) return;
    final dist = c.cond['dist'];
    if (dist == 'table' || dist == 'across') {
      _state = 'countdown';
      _countdown = _countdownMs ~/ 1000;
      _push();
      for (var k = 1; k <= _countdown; k++) {
        _after(k * 1000, () {
          if (_state != 'countdown' || !identical(_take, c)) return;
          _countdown -= 1;
          if (_countdown <= 0) {
            _beginRecord();
          } else {
            _push();
          }
        });
      }
    } else {
      _beginRecord();
    }
  }

  void _beginRecord() {
    final c = _take;
    if (c == null) return;
    _state = 'recording';
    _recS = 0;
    _level = const RecLevel(minDb: -55); // floor + open_db, known from GO
    _heard.clear();
    _last = null;
    _push();
    // backgrounds: exactly `seconds`; the room: its fixed max_s window; others end on silence after the target
    final dur = c.bg != null ? (c.seconds ?? 5) : (c.quiet ? (c.maxS ?? 3.5) : (c.targetS ?? 0.6) + 1.0);
    _after((dur * 1000).round(), () {
      if (_state != 'recording' || !identical(_take, c)) return;
      _endRecord();
    });
  }

  void _endRecord() {
    final c = _take;
    final s = _s;
    if (c == null || s == null) return;
    if (noSoundTakes.contains(c.takeId)) {
      // saved like the desktop, with no_sound: true on its label row; Try again records a new attempt
      noSoundTakes.remove(c.takeId);
      _state = 'no_sound';
      _last = {'take_id': c.takeId, 'saved': true, 'dur_ms': 4000, 'reason': 'no sound', 'below_f0_min': false};
      _push();
      return;
    }
    // what Canti heard: one sound per expected label (from ~0.45 s after GO), with pitch16 for contours
    _heard.clear();
    for (var k = 0; k < c.expect.length; k++) {
      final label = c.expect[k];
      final contour = const ['rise', 'fall', 'arch', 'dip', 'flat'].contains(label);
      final f0 = !contour ? null : (c.cond['tone'] == 'whistle' ? 1250 : 142);
      _heard.add(HeardSound(
        label: label,
        relMs: 450.0 + k * 380,
        durMs: contour ? ((c.targetS ?? 0.6) * 1000).round() : 120,
        pitch16: contour ? _pitch16(label) : const [],
        f0Hz: f0,
        didText: 'ignored: recording',
        dropped: 'recording',
      ));
    }
    s.saved.add(c.takeId);
    _lastSaved = c;
    _last = {
      'take_id': c.takeId,
      'saved': true,
      'dur_ms': ((c.bg != null ? (c.seconds ?? 5) : (c.targetS ?? 0.6) + 1.5) * 1000).round(),
      'reason': (c.bg != null || c.quiet) ? 'fixed' : 'silence',
      'below_f0_min': false,
    };
    _state = 'saved';
    _push();
    _after(_savedHoldMs, () {
      if (_state == 'saved' && identical(_take, c)) _afterSaved();
    });
  }

  /// SAVED_HOLD_MS after a save: the rating when the block is finished, done at the end, the next take by itself when
  /// it is in the same block and not manual; otherwise the take stays "saved" until the user moves on.
  void _afterSaved() {
    final c = _take;
    final s = _s;
    if (c == null || s == null) return;
    final block = _blocks.firstWhere((b) => b.id == c.block);
    if (_blockDone(block) && !s.ratings.containsKey(block.id)) {
      _state = 'rate';
      _take = null;
      _push();
      return;
    }
    final next = _nextCell();
    if (next == null) {
      _state = 'done';
      _take = null;
      _push();
      return;
    }
    if (next.block != c.block || next.manual) return;
    _ready(next);
  }

  void _ready(_Cell c, {bool redo = false}) {
    final s = _s;
    if (s == null) return;
    if (redo) c.redo += 1;
    _take = c;
    _state = 'ready';
    _countdown = 0;
    _level = const RecLevel();
    _heard.clear();
    _last = null;
    _push();
    if (!c.manual) {
      _after(_readMs, () {
        if (_state == 'ready' && identical(_take, c)) _go();
      });
    }
  }

  /// The current state, for tests.
  String get state => _state;

  void _push() => _out.add(statusMap(null));

  Future<Map<String, Object?>> _cmd(String name, void Function() f) async {
    calls.add(name);
    _error = null;
    _reason = null;
    try {
      f();
    } on RecCommandError catch (e) {
      _error = e.message;
    }
    final st = statusMap(null);
    _out.add(st);
    if (_error != null) throw RecCommandError(_error!);
    return st;
  }

  @override
  Future<Map<String, Object?>> recList() async {
    calls.add('rec_list');
    return {
      'enabled': enabled,
      'sessions': [
        for (final s in sessions.values)
          {
            'name': s.name,
            'speaker': s.speaker,
            'profile': s.profile,
            'mic': s.mic,
            'rate': s.rate,
            'done': s.saved.length,
            'total': _cells.length,
            'backgrounds_done': 0,
            'backgrounds_total': 1,
            'rated_blocks': s.ratings.length,
            'bytes': 0,
            'open': identical(s, _s),
          },
      ],
      'free_bytes': freeBytes,
      'quickrec': {'count': _savedQuick.length, 'bytes': 0},
    };
  }

  @override
  Future<Map<String, Object?>> recStart({String? who, String? speaker, String? profile}) =>
      _cmd('rec_start ${who ?? ''} ${speaker ?? ''}', () {
        if (source == 'pico') throw RecCommandError('the Pico sends no audio: switch the sound source to phone or USB');
        final w = who ?? 'me';
        final sp = w == 'me' ? 'self' : (speaker ?? '');
        if (w == 'other' && !RegExp(r'^[A-Za-z0-9_-]{1,24}$').hasMatch(sp)) {
          throw RecCommandError('speaker must match [A-Za-z0-9_-]{1,24}');
        }
        if (w == 'other' && sp == 'self') throw RecCommandError('speaker must not be "self"');
        final base = 'range-$sp-${DateTime(2026, 9, 1).add(Duration(days: now ~/ 86400000 % 28)).month.toString().padLeft(2, '0')}${DateTime(2026, 9, 1).day.toString().padLeft(2, '0')}';
        var name = base;
        var n = 1;
        while (sessions.containsKey(name)) {
          n++;
          name = '$base-$n';
        }
        final mic = source == 'usb' ? 'usb: fake device' : 'phone built-in mic';
        _s = _Session(name, sp, profile ?? 'short', mic, rate);
        sessions[name] = _s!;
        _state = 'idle';
        _take = null;
      });

  @override
  Future<Map<String, Object?>> recOpen(String name) => _cmd('rec_open $name', () {
        final s = sessions[name] ?? (throw RecCommandError('no session named $name'));
        _s = s;
        _lastSaved = null;
        _state = 'idle';
        _take = null;
      });

  @override
  Future<Map<String, Object?>> recStatus() async => statusMap(null);

  @override
  Future<Map<String, Object?>> recNext({String? takeId}) => _cmd('rec_next ${takeId ?? ''}', () {
        final s = _need();
        final c = takeId == null ? _nextCell() : _cellById(takeId);
        if (c == null) {
          _state = s.saved.length + s.skipped.length >= _cells.length ? 'done' : 'idle';
          _take = null;
          return;
        }
        lastNextTakeId = c.takeId;
        _ready(c, redo: takeId != null && s.saved.contains(c.takeId));
      });

  @override
  Future<Map<String, Object?>> recGo() => _cmd('rec_go', () {
        _need();
        if (_state != 'ready') {
          throw RecCommandError('not possible now (the take is $_state)');
        }
        _go();
      });

  @override
  Future<Map<String, Object?>> recAbort() => _cmd('rec_abort', () {
        _need();
        _state = 'idle';
        _take = null;
      });

  @override
  Future<Map<String, Object?>> recSkip() => _cmd('rec_skip', () {
        final s = _need();
        final c = _take;
        if (c == null) throw RecCommandError('no take in flight');
        s.skipped.add(c.takeId);
        final next = _nextCell();
        if (next == null) {
          _state = 'done';
          _take = null;
        } else {
          _ready(next);
        }
      });

  @override
  Future<Map<String, Object?>> recRedoLast() => _cmd('rec_redo_last', () {
        _need();
        final c = _lastSaved;
        if (c == null) throw RecCommandError('no saved take to redo in this sitting');
        _ready(c, redo: true);
      });

  @override
  Future<Map<String, Object?>> recRate({required String block, required int rating, String? note}) =>
      _cmd('rec_rate $block $rating', () {
        final s = _need();
        if (rating < 1 || rating > 5) throw RecCommandError('rating must be 1..5');
        s.ratings[block] = (rating, note);
        final allRated = _blocks.every((b) => s.ratings.containsKey(b.id));
        final allDone = _cells.every((c) => s.saved.contains(c.takeId) || s.skipped.contains(c.takeId));
        _state = (allRated && allDone) ? 'done' : 'idle';
        _take = null;
      });

  @override
  Future<Map<String, Object?>> recClose() => _cmd('rec_close', () {
        _s = null;
        _lastSaved = null;
        _state = 'idle';
        _take = null;
      });

  @override
  Future<Map<String, Object?>> recClear({List<String>? sessions, Object? quickrec}) async {
    calls.add('rec_clear');
    for (final n in sessions ?? const <String>[]) {
      if (identical(this.sessions[n], _s)) throw RecCommandError('the open session cannot be cleared');
      this.sessions.remove(n);
    }
    return {'deleted': sessions?.length ?? 0};
  }

  // --- quick record ---------------------------------------------------------------------------------------------------

  @override
  Future<Map<String, Object?>> qrSnap() async {
    calls.add('qr_snap');
    _pending = _snapshot();
    _snap.add(_pending!);
    return _pending!;
  }

  Map<String, Object?> _snapshot() {
    final id = '$now';
    return {
      'id': id,
      'seconds': 12,
      'rate': rate,
      'bars_db': [for (var i = 0; i < 120; i++) _clipDb(i)],
      'min_db': -55,
      // a hiss that pressed Back, then an arch heard as a dip (the misfire), then a click that did nothing
      'sounds': [
        {
          'label': 'hiss',
          'rel_ms': 3000.0,
          'dur_ms': 220,
          'pitch16': const <double>[],
          'f0_hz': null,
          'did_text': 'HISS → back',
          'ago_s': 9.0,
        },
        {
          'label': 'dip',
          'rel_ms': 6500.0,
          'dur_ms': 640,
          'pitch16': [for (var i = 0; i < 16; i++) (30 * math.sin(math.pi * i / 15)).round() / 10],
          'f0_hz': 150,
          'did_text': 'DIP → swipe left',
          'ago_s': 5.5,
        },
        {
          'label': 'click',
          'rel_ms': 10800.0,
          'dur_ms': 120,
          'pitch16': const <double>[],
          'f0_hz': null,
          'dropped': 'below level gate',
          'did_text': 'ignored: below level gate',
          'ago_s': 1.2,
        },
      ],
      'last_action': {'text': 'DIP → swipe left', 'ago_s': 5.5, 'in_clip': true},
      'app': 'org.schabi.newpipe',
      'mode': 'gesture',
    };
  }

  @override
  Future<Map<String, Object?>> qrPending() async {
    calls.add('qr_pending');
    return _pending ?? {'id': null};
  }

  @override
  Future<Map<String, Object?>> qrSave({required String id, required String label, String? note, int? sound}) async {
    calls.add('qr_save $label');
    final p = _pending;
    if (p == null || p['id'] != id) throw RecCommandError('no such snapshot');
    _savedQuick.add(id);
    _pending = null;
    return {'ok': true, 'id': id, 'file': 'files/quickrec/$id/clip.wav', 'bytes': 384000};
  }

  @override
  Future<Map<String, Object?>> qrDiscard(String id) async {
    calls.add('qr_discard');
    if (_pending != null && _pending!['id'] == id) _pending = null;
    return {'ok': true};
  }

  @override
  Stream<Map<String, Object?>> statusStream() => _out.stream;
  @override
  Stream<Map<String, Object?>> snapshotStream() => _snap.stream;

  /// The status map, as the phone sends it.
  Map<String, Object?> statusMap(String? _) {
    final s = _s;
    final c = _take;
    final next = _nextCell();
    return {
      'enabled': enabled,
      'active': s != null,
      'name': s?.name,
      'speaker': s?.speaker,
      'profile': s?.profile,
      'mic': s?.mic,
      'rate': s?.rate,
      'state': _state,
      'error': _error,
      'reason': _reason,
      'take': c == null
          ? null
          : {
              'take_id': c.takeId,
              'block': c.block,
              'block_title': c.blockTitle,
              'i': c.i,
              'n': c.n,
              'block_i': c.blockI,
              'block_n': c.blockN,
              'cue': c.cue,
              'expect': c.expect,
              'cond': c.cond,
              'bg': c.bg,
              'kind': c.kind,
              'quiet': c.quiet,
              'manual': c.manual,
              'target_s': c.targetS,
              'max_s': c.maxS,
              'seconds': c.seconds,
              'redo': c.redo,
            },
      'countdown_s': _state == 'countdown' ? _countdown : null,
      'rec_s': _state == 'recording' ? _recS : null,
      'level': {
        'bars_db': _level.barsDb,
        'min_db': _level.minDb,
        'peak_dbfs': _level.peakDbfs,
        'note': _level.note,
      },
      'heard': [for (final h in _heard) _heardMap(h)],
      'last': _last,
      'blocks': [
        for (final b in _blocks)
          {
            'id': b.id,
            'title': b.title,
            'intro': b.intro,
            'done': b.cells.where((x) => s != null && s.saved.contains(x.takeId)).length,
            'total': b.cells.length,
            'rating': s?.ratings[b.id]?.$1,
            'skipped': b.cells.where((x) => s != null && s.skipped.contains(x.takeId)).length,
          },
      ],
      'done': s?.saved.length ?? 0,
      'total': _cells.length,
      'skipped': s?.skipped.length ?? 0,
      'bytes': 0,
      'next': next == null
          ? null
          : {'take_id': next.takeId, 'cue': next.cue},
      'plan': [for (final c in _cells) {'take_id': c.takeId, 'block': c.block}],
      'defaults': {
        'distances_cm': {'hand': 25, 'table': 60, 'across': 150},
        'speed_s': {'slow': 1.2, 'normal': 0.6, 'quick': 0.3},
        'gap_s': {'quick': 0.15, 'normal': 0.35, 'slow': 0.8},
      },
      'scale': scale == null
          ? null
          : {'low_hz': scale!.lowHz, 'home_hz': scale!.homeHz, 'high_hz': scale!.highHz, 'from': 'calibration'},
    };
  }

  Map<String, Object?> _heardMap(HeardSound h) => {
        'label': h.label,
        'rel_ms': h.relMs,
        'dur_ms': h.durMs,
        'pitch16': h.pitch16,
        'f0_hz': h.f0Hz,
        'dropped': h.dropped,
        'gated': h.gated,
        'relabel': h.relabel,
        'did_text': h.didText,
      };

  void dispose() {
    _timer?.cancel();
    _out.close();
    _snap.close();
  }
}

/// The fake clip's 100 ms levels: a quiet room with the three sounds of the snapshot standing out.
double _clipDb(int i) {
  if (i == 108) return -57; // the click, under the level gate (min_db -55)
  final loud = (i >= 30 && i < 33) || (i >= 65 && i < 72);
  return (loud ? -30 : -64) + 2 * math.sin(i / 3);
}
