import 'dart:async';
import 'dart:math' as math;

import 'train.dart';

// An in-memory [TrainBackend] for tests and the desktop runner. It mirrors the plan and the checks of
// android/.../GestureTraining.kt closely enough to exercise the screen; the phone's trainer is the reference.

/// What a simulated take "heard". Defaults to the prompted gesture, in the prompted tone and speed.
class FakeTake {
  const FakeTake({this.label, this.labels, this.durMs, this.f0Hz, this.unpitched = false});

  /// The extractor's label (default: the prompted gesture).
  final String? label;

  /// Several sounds in one take (overrides [label]).
  final List<String>? labels;
  final int? durMs;
  final int? f0Hz;
  final bool unpitched;
}

const _contours = ['rise', 'fall', 'arch', 'dip', 'flat'];
const _shape = {
  'rise': 'goes up',
  'fall': 'goes down',
  'arch': 'goes up then down',
  'dip': 'goes down then up',
  'flat': 'stays level',
  'pop': 'a short lip pop',
  'click': 'a tongue click',
  'hiss': 'a hiss',
};
const _short = {'rise': 'up', 'fall': 'down', 'arch': 'up then down', 'dip': 'down then up', 'flat': 'level'};

String _cap(String s) => s.isEmpty ? s : '${s[0].toUpperCase()}${s.substring(1)}';
String _a(String w) => 'aeiou'.contains(w[0]) ? 'an $w' : 'a $w';

class _Cell {
  _Cell(this.gesture, this.id, this.tags, this.prompt, this.hint);
  final String gesture;
  final String id;
  final Map<String, String> tags;
  final String prompt;
  final String hint;
}

List<_Cell> _cells(String g) {
  final out = <_Cell>[];
  if (_contours.contains(g)) {
    for (final tone in ['hum', 'whistle']) {
      for (final pitch in ['low', 'high']) {
        for (final speed in g == 'flat' ? ['short', 'long'] : ['slow', 'quick']) {
          final verb = tone == 'hum' ? 'Hum' : 'Whistle';
          final prompt = g == 'flat'
              ? '$verb a ${speed.toUpperCase()} flat note, ${pitch.toUpperCase()}'
              : '$verb a ${speed.toUpperCase()} $g, starting ${pitch.toUpperCase()}';
          final how = speed == 'quick' || speed == 'short' ? 'about half a second' : 'about 1.5 s';
          final where = g == 'flat'
              ? (pitch == 'low' ? 'a low note for you' : 'a high note for you')
              : (pitch == 'low' ? 'start near the bottom of your range' : 'start near the top of your range');
          final toneHint = tone == 'hum' ? 'lips closed, "mm"' : 'a whistle';
          out.add(
            _Cell(
              g,
              '$tone-$pitch-$speed',
              {'tone': tone, 'pitch': pitch, g == 'flat' ? 'length' : 'speed': speed},
              prompt,
              '${_cap(_a(g))} ${_shape[g]}. ${_cap(speed)}: $how. ${_cap(where)}. ${_cap(toneHint)}.',
            ),
          );
        }
      }
    }
  } else {
    for (final loud in ['soft', 'loud']) {
      for (final take in [1, 2]) {
        final adv = loud == 'soft' ? 'SOFTLY' : 'LOUDLY';
        final prompt = switch (g) {
          'pop' => 'Pop your lips $adv ($take of 2)',
          'click' => 'Click your tongue $adv ($take of 2)',
          _ => 'Hiss $adv, about half a second ($take of 2)',
        };
        final hint =
            switch (g) {
              'pop' => 'A short lip pop, like "p" with no voice.',
              'click' => 'A tongue click, like "tsk" or a cluck.',
              _ => 'A short "sss" or "shh", under a second.',
            } +
            (loud == 'soft' ? ' Soft: as quiet as you would use it.' : ' Loud: as loud as you would use it.');
        out.add(_Cell(g, '$loud-$take', {'loudness': loud, 'take': '$take'}, prompt, hint));
      }
    }
  }
  return out;
}

final Map<String, List<_Cell>> _plan = {for (final g in trainGestures) g: _cells(g)};
final int _total = _plan.values.fold(0, (a, c) => a + c.length);

/// The contour a label draws, 16 points in semitones from the start.
List<double> fakePitch16(String label, {double span = 5}) => [
  for (var i = 0; i < 16; i++)
    switch (label) {
      'rise' => span * i / 15,
      'fall' => -span * i / 15,
      'arch' => span * math.sin(math.pi * i / 15),
      'dip' => -span * math.sin(math.pi * i / 15),
      _ => 0.15 * math.sin(i.toDouble()),
    },
];

class _Session {
  _Session(this.source, this.gesture, this.queue);
  final String source;
  final String gesture;
  final List<_Cell> queue;
  int index = 0;
  String state = 'ready';
  List<(String, String)> reasons = const [];
  bool canKeep = false;
  Map<String, Object?>? heard;
  final trace = <double?>[];
  double? levelDb;
  int startedMs = 0;
  final passed = <String>[];
  final skipped = <String>[];
  final kept = <String>[];
  _Cell? get cell => index < queue.length ? queue[index] : null;
}

/// In-memory gesture training. A take finishes by [finishTake] (tests), or by itself after [autoTake] with a
/// simulated live trace (the desktop runner); [outcomes] scripts what the next takes hear.
class FakeTrainBackend implements TrainBackend {
  FakeTrainBackend({this.source = 'phone', this.liveTrace = true, this.autoTake, this.blocked});

  /// The current sound source.
  String source;
  bool liveTrace;

  /// Why a take cannot be recorded (null = it can).
  String? blocked;

  /// The one action that fixes [blocked] (`resume` or `gesture_mode`), or null.
  String? blockedAction;

  /// When set, a recording take ends by itself after this long (with a live trace every 20 ms).
  Duration? autoTake;

  /// What the next takes hear, first first (empty = the prompted gesture, done right).
  final outcomes = <FakeTake>[];

  /// Every command, in order (`train_start rise`, ...).
  final calls = <String>[];

  /// source -> gesture -> cell id -> kept anyway.
  final Map<String, Map<String, Map<String, bool>>> stores = {};
  _Session? _s;
  Timer? _timer;
  final _out = StreamController<TrainStatus>.broadcast();

  Map<String, Map<String, bool>> _store(String src) => stores.putIfAbsent(src, () => {});

  /// Marks cells recorded without a session ([cells] null = all of the gesture's).
  void fill(String gesture, {String? src, Iterable<String>? cells}) {
    final g = _store(src ?? source).putIfAbsent(gesture, () => {});
    for (final c in cells ?? _plan[gesture]!.map((c) => c.id)) {
      g[c] = false;
    }
  }

  /// Feeds live ticks to a recording take (tests, the desktop preview).
  void trace(Iterable<double?> hz, {double levelDb = -32}) {
    final c = _s;
    if (c == null || c.state != 'recording') return;
    c.trace.addAll(hz);
    if (c.trace.length > 250) c.trace.removeRange(0, c.trace.length - 250);
    c.levelDb = levelDb;
    _push();
  }

  /// Ends the recording take with [take] (default: the next of [outcomes], else a right one).
  void finishTake([FakeTake? take]) {
    final c = _s;
    if (c == null || c.state != 'recording') return;
    _timer?.cancel();
    _judge(c, take ?? (outcomes.isNotEmpty ? outcomes.removeAt(0) : const FakeTake()));
    _push();
  }

  void _judge(_Session c, FakeTake t) {
    final cell = c.cell!;
    final g = cell.gesture;
    final labels = t.labels ?? [t.label ?? g];
    final label = labels.first;
    final contour = _contours.contains(g);
    final wantTone = cell.tags['tone'];
    final f0 = t.unpitched || !contour ? null : (t.f0Hz ?? (wantTone == 'whistle' ? 1250 : 190));
    final speed = cell.tags['speed'] ?? cell.tags['length'];
    final dur = t.durMs ?? (!contour ? 180 : (speed == 'quick' || speed == 'short' ? 520 : 1450));
    final tone = f0 == null ? null : (f0 >= 600 ? 'whistle' : 'hum');
    c.heard = {
      'label': label,
      'line': '$label ${dur}ms',
      'sounds': labels.length,
      'labels': labels,
      'dur_ms': dur,
      'f0_hz': f0,
      'start_hz': f0 == null ? null : (f0 * 0.85).round(),
      'tone': tone,
      'loudness': contour ? null : cell.tags['loudness'],
      'pitch16': _contours.contains(label) && f0 != null ? fakePitch16(label) : const <double>[],
      'shape': _shape[label],
    };
    final reasons = <(String, String)>[];
    if (labels.length > 1) {
      reasons.add(('count', 'Heard ${labels.length} sounds (${labels.join(' then ')}): make it one unbroken sound.'));
    } else {
      if (label != g) {
        final wanted = contour ? '${_a(g)} ${_shape[g]}' : '${_a(g)} is ${_shape[g]}';
        reasons.add((
          'label',
          label == 'unknown'
              ? 'Canti did not count that as a gesture (too quiet, too short, or media playing): $wanted.'
              : 'Heard ${_short[label] != null ? '${_a(label)} (${_short[label]})' : _a(label)}: $wanted.',
        ));
      }
      if (contour && label == g) {
        if (tone == null) {
          reasons.add((
            'tone',
            'No clear pitch: ${wantTone == 'hum' ? 'hum it with your lips closed' : 'whistle it'}.',
          ));
        } else if (tone != wantTone) {
          reasons.add((
            'tone',
            wantTone == 'whistle'
                ? 'Heard a hum (about $f0 Hz): a whistle is 600 Hz or higher. Whistle it.'
                : 'Heard a whistle (about $f0 Hz): hum it with your lips closed, below 600 Hz.',
          ));
        }
        final what = g == 'flat' ? 'flat note' : g;
        final secs = (dur / 1000).toStringAsFixed(1);
        if ((speed == 'quick' || speed == 'short') && dur > 1000) {
          reasons.add((
            'speed',
            'It took $secs s: a ${speed!.toUpperCase()} $what takes about half a second (at most 1.0 s).',
          ));
        }
        if ((speed == 'slow' || speed == 'long') && dur < 800) {
          reasons.add((
            'speed',
            'It took $secs s: a ${speed!.toUpperCase()} $what takes about 1.5 s (at least 0.8 s).',
          ));
        }
      }
    }
    c.reasons = reasons;
    c.canKeep = reasons.isNotEmpty && reasons.every((r) => r.$1 == 'label') && (!contour || f0 != null);
    if (reasons.isEmpty) {
      _storeTake(c, kept: false);
      c.state = 'passed';
    } else {
      c.state = 'failed';
    }
  }

  void _storeTake(_Session c, {required bool kept}) {
    _store(c.source).putIfAbsent(c.gesture, () => {})[c.cell!.id] = kept;
    c.passed.add(c.cell!.id);
  }

  void _record() {
    final c = _s;
    if (c == null) throw TrainCommandError('no training session: start one from a gesture card');
    if (!const ['ready', 'failed', 'passed'].contains(c.state)) {
      throw TrainCommandError('not possible now (the take is ${c.state})');
    }
    if (c.cell == null) throw TrainCommandError('no take left in this round');
    _timer?.cancel();
    c
      ..trace.clear()
      ..levelDb = null
      ..heard = null
      ..reasons = const []
      ..canKeep = false;
    if (blocked != null) {
      c
        ..state = 'failed'
        ..reasons = [('blocked', blocked!)];
      return;
    }
    c
      ..state = 'recording'
      ..startedMs = DateTime.now().millisecondsSinceEpoch;
    final auto = autoTake;
    if (auto != null) {
      final cell = c.cell!;
      final ticks = auto.inMilliseconds ~/ 20;
      var n = 0;
      final base = cell.tags['tone'] == 'whistle' ? 1100.0 : 180.0;
      final p16 = _contours.contains(cell.gesture) ? fakePitch16(cell.gesture) : const <double>[];
      _timer = Timer.periodic(const Duration(milliseconds: 20), (t) {
        if (!identical(_s, c) || c.state != 'recording') return t.cancel();
        n++;
        final on = n > ticks * 0.15 && n < ticks * 0.85;
        final x = ((n - ticks * 0.15) / (ticks * 0.7)).clamp(0.0, 1.0);
        final st = p16.isEmpty ? 0.0 : p16[(x * 15).round()];
        c.trace.add(on && p16.isNotEmpty ? base * math.pow(2, st / 12) : null);
        c.levelDb = on ? -28 : -55;
        if (n >= ticks) {
          t.cancel();
          finishTake();
        } else if (n % 5 == 0) {
          _push();
        }
      });
    }
  }

  void _advance(_Session c, {required bool record}) {
    _timer?.cancel();
    c
      ..index += 1
      ..heard = null
      ..reasons = const []
      ..canKeep = false
      ..trace.clear();
    if (c.cell == null) {
      c.state = 'done';
    } else {
      c.state = 'ready';
      if (record) _record();
    }
  }

  _Session _need() => _s ?? (throw TrainCommandError('no training session: start one from a gesture card'));

  Future<TrainStatus> _cmd(String name, void Function() f, {String? src}) async {
    calls.add(name);
    String? err;
    try {
      f();
    } on TrainCommandError catch (e) {
      err = e.message;
    }
    final st = TrainStatus.fromMap({...statusMap(src), 'error': ?err});
    _out.add(st);
    if (err != null) throw TrainCommandError(err);
    return st;
  }

  void _push() => _out.add(TrainStatus.fromMap(statusMap(null)));

  @override
  Future<TrainStatus> status({String? source}) => _cmd('train_status', () {}, src: source);

  @override
  Future<TrainStatus> start(String gesture, {String? cell}) =>
      _cmd('train_start $gesture${cell == null ? '' : ' $cell'}', () {
        final cells = _plan[gesture] ?? (throw TrainCommandError('gesture must be one of $trainGestures'));
        final done = _store(source)[gesture] ?? const {};
        final queue = cell != null
            ? cells.where((c) => c.id == cell).toList()
            : cells.where((c) => !done.containsKey(c.id)).toList();
        if (queue.isEmpty) {
          throw TrainCommandError('every $gesture take is recorded: use Delete / redo to record them again');
        }
        _timer?.cancel();
        _s = _Session(source, gesture, queue);
      });

  @override
  Future<TrainStatus> record() => _cmd('train_record', _record);

  @override
  Future<TrainStatus> retry() => _cmd('train_retry', () {
    if (_need().state != 'failed') throw TrainCommandError('not possible now (the take is ${_s!.state})');
    _record();
  });

  @override
  Future<TrainStatus> skip() => _cmd('train_skip', () {
    final c = _need();
    if (c.state != 'failed' && c.state != 'ready') throw TrainCommandError('not possible now (the take is ${c.state})');
    c.skipped.add(c.cell!.id);
    _advance(c, record: false);
  });

  @override
  Future<TrainStatus> keep() => _cmd('train_keep', () {
    final c = _need();
    if (c.state != 'failed' || !c.canKeep) {
      throw TrainCommandError('only a take with the wrong shape can be kept anyway');
    }
    _storeTake(c, kept: true);
    c
      ..kept.add(c.cell!.id)
      ..state = 'passed';
  });

  @override
  Future<TrainStatus> next({bool record = true}) => _cmd('train_next', () {
    final c = _need();
    if (c.state != 'passed') throw TrainCommandError('not possible now (the take is ${c.state})');
    _advance(c, record: record);
  });

  @override
  Future<TrainStatus> cancel() => _cmd('train_cancel', () {
    _timer?.cancel();
    _s = null;
  });

  @override
  Future<TrainStatus> delete(String gesture, {String? cell, String? source}) =>
      _cmd('train_delete $gesture${cell == null ? '' : ' $cell'}', () {
        final src = source ?? this.source;
        if (_s != null && _s!.gesture == gesture && _s!.source == src) {
          throw TrainCommandError('the $gesture card is being recorded: stop it first');
        }
        if (cell == null) {
          _store(src).remove(gesture);
        } else {
          _store(src)[gesture]?.remove(cell);
        }
      }, src: source);

  @override
  Stream<TrainStatus> pushes() => _out.stream;

  /// The status map, as the phone sends it.
  Map<String, Object?> statusMap(String? src) {
    final s = src ?? source;
    final st = _store(s);
    final c = _s;
    return {
      'active': c != null,
      'source': s,
      'current_source': source,
      'profile': 'default',
      'live_trace': liveTrace,
      'blocked': blocked,
      'blocked_action': blockedAction,
      'done': st.values.fold<int>(0, (a, g) => a + g.length),
      'total': _total,
      'gestures': [
        for (final g in trainGestures)
          {
            'name': g,
            'kind': _contours.contains(g) ? 'contour' : 'discrete',
            'done': st[g]?.length ?? 0,
            'total': _plan[g]!.length,
            'examples': st[g]?.length ?? 0,
            'extra': 0,
            'active': (st[g]?.length ?? 0) >= 3,
            'kept': st[g]?.values.where((k) => k).length ?? 0,
            'cells': [
              for (final cell in _plan[g]!)
                {'id': cell.id, 'prompt': cell.prompt, 'done': st[g]?.containsKey(cell.id) ?? false, 'tags': cell.tags},
            ],
          },
      ],
      'session': c == null
          ? null
          : {
              'source': c.source,
              'gesture': c.gesture,
              'state': c.state,
              'cell': c.cell?.id,
              'prompt': c.cell?.prompt,
              'hint': c.cell?.hint,
              'tags': c.cell?.tags,
              'index': c.index,
              'count': c.queue.length,
              'next_prompt': c.index + 1 < c.queue.length ? c.queue[c.index + 1].prompt : null,
              'reason': c.reasons.isEmpty ? null : c.reasons.map((r) => r.$2).join(' '),
              'reasons': [for (final r in c.reasons) r.$1],
              'can_keep': c.state == 'failed' && c.canKeep,
              'heard': c.heard,
              'heard_n': c.heard == null ? 0 : (c.heard!['sounds'] as int? ?? 1),
              'left_ms': c.state == 'recording'
                  ? math.max(0, 8000 - (DateTime.now().millisecondsSinceEpoch - c.startedMs))
                  : null,
              'live': {'trace_hz': c.trace, 'level_db': c.levelDb, 'pitch_hz': c.trace.isEmpty ? null : c.trace.last},
              'passed': c.passed,
              'skipped': c.skipped,
              'kept': c.kept,
            },
      'sources': {
        for (final x in trainSources)
          x: {'done': _store(x).values.fold<int>(0, (a, g) => a + g.length), 'total': _total},
      },
    };
  }

  void dispose() {
    _timer?.cancel();
    _out.close();
  }
}
