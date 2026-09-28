import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'backend.dart';
import 'calibration.dart';
import 'calibration_screen.dart' show CalibPanel;
import 'theme/canti_theme.dart';
import 'theme/dither_background.dart';
import 'theme/glyphs.dart';
import 'theme/kit.dart';
import 'theme/pixel.dart';
import 'train.dart';

/// Opens the gesture training screen.
Future<void> openTraining(BuildContext context, VoxBackend backend, {TrainBackend? train}) =>
    Navigator.of(context).push<void>(
        MaterialPageRoute(builder: (_) => TrainScreen(train: train ?? trainBackendFor(backend), backend: backend)));

String _cap(String s) => s.isEmpty ? s : '${s[0].toUpperCase()}${s.substring(1)}';

String _secs(int ms) => '${(ms / 1000).toStringAsFixed(1)} s';

/// "Train gestures" (android/PROTOCOL.md "Gesture training"): a card per gesture with its progress; a card's round
/// records its missing takes one prompt at a time, with the live pitch trace, and shows what Canti heard after
/// each take. A failed take stops with the reason and waits for Retry or Skip (Keep anyway when only the shape was
/// wrong). Resumable: every accepted take is stored at once.
class TrainScreen extends StatefulWidget {
  const TrainScreen({super.key, required this.train, this.flow, this.backend});

  final TrainBackend train;

  /// A flow to drive (tests, the desktop preview); by default the screen makes its own.
  final TrainFlow? flow;

  /// The main backend, for the "Not ready" note's fix button (Resume / switch to gesture mode); null without it.
  final VoxBackend? backend;

  static const intro =
      'Record your own version of each gesture, with its variations: hummed and whistled, starting '
      'low and high, slow and quick. Canti\'s matcher learns your version from them. Every take is stored as you go, '
      'so you can stop at any time and carry on later.';

  @override
  State<TrainScreen> createState() => _TrainScreenState();
}

class _TrainScreenState extends State<TrainScreen> {
  late final TrainFlow _flow = widget.flow ?? TrainFlow(backend: widget.train);
  BackdropMood? _mood;

  @override
  void initState() {
    super.initState();
    _flow.addListener(_toMood);
    _flow.attach();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _mood = BackdropMood.maybeOf(context);
  }

  /// The background's EQ bars follow the mic while a take records (the level only from a live source: phone or USB
  /// mic; from the Canti device they move by themselves).
  void _toMood() {
    final take = _flow.session;
    final on = take?.state == 'recording';
    _mood?.listen(on, levelDb: _flow.status?.liveTrace == true ? take?.live.levelDb : null);
  }

  @override
  void dispose() {
    _flow.removeListener(_toMood);
    _mood?.listen(false);
    _flow.close(); // an open round ends; its stored takes stay
    if (widget.flow == null) _flow.dispose();
    super.dispose();
  }

  Future<void> _back() async {
    await _flow.close();
    if (mounted) Navigator.of(context).maybePop();
  }

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final gap = SizedBox(height: p(5));
    return Scaffold(
      body: SafeArea(
        child: ListenableBuilder(
          listenable: _flow,
          builder: (context, _) {
            final f = _flow;
            final s = f.status;
            final session = f.session;
            return SingleChildScrollView(
              padding: EdgeInsets.all(p(5)),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  ScreenHeader(backKey: const Key('train_back'), title: 'Train gestures', onBack: _back),
                  gap,
                  if (f.error != null) ...[
                    PixelWindow(
                      title: 'Error',
                      onClose: f.dismissError,
                      closeLabel: 'Dismiss error',
                      child: SignalNote(signal: Signal.stop, text: f.error!, textKey: const Key('train_error')),
                    ),
                    gap,
                  ],
                  if (s == null)
                    const SignalNote(signal: Signal.waiting, text: 'Loading...', textKey: Key('train_loading'))
                  else if (!s.service)
                    const SignalNote(signal: Signal.stop, text: 'The Canti service is off: start it to train gestures.')
                  else if (session != null)
                    _SessionWindow(flow: f, status: s, session: session)
                  else ...[
                    _GridWindow(flow: f, status: s, backend: widget.backend),
                    if (f.selected != null && s.gesture(f.selected!) != null) ...[
                      gap,
                      _CardWindow(flow: f, status: s, gesture: s.gesture(f.selected!)!),
                    ],
                  ],
                ],
              ),
            );
          },
        ),
      ),
    );
  }
}

// --- the cards --------------------------------------------------------------------------------------------------

class _GridWindow extends StatelessWidget {
  const _GridWindow({required this.flow, required this.status, this.backend});

  final TrainFlow flow;
  final TrainStatus status;
  final VoxBackend? backend;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    final gap = SizedBox(height: p(4));
    final s = status;
    return PixelWindow(
      title: 'Your gestures',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          PixelSnap(
            child: Text(
              '${sourceLabel(s.source)} · ${s.done}/${s.total} takes',
              key: const Key('train_where'),
              style: p.body(t.ink),
            ),
          ),
          SizedBox(height: p(3)),
          const SignalNote(signal: Signal.idle, text: TrainScreen.intro),
          if (!s.trainable) ...[
            gap,
            SignalNote(
              signal: Signal.waiting,
              text:
                  'These are the ${sourceLabel(s.source)} takes. Sounds come from the ${sourceLabel(s.currentSource)} '
                  'now: switch the sound source to train these.',
              textKey: const Key('train_other_source'),
            ),
          ] else if (s.blocked != null) ...[
            gap,
            SignalNote(
              signal: Signal.waiting,
              text: 'Not ready to record: ${s.blocked}',
              textKey: const Key('train_blocked'),
            ),
            if (s.blockedAction != null && backend != null) ...[
              SizedBox(height: p(3)),
              Align(alignment: Alignment.centerLeft, child: _fixButton(context, s.blockedAction!)),
            ],
          ],
          gap,
          _CardGrid(flow: flow, status: s),
          gap,
          CalibPanel(
            rows: [
              for (final src in trainSources)
                (
                  src == s.currentSource ? Icons7.sound : Icons7.pipOff,
                  src == 'pico'
                      ? 'Canti'
                      : src == 'usb'
                      ? 'USB'
                      : 'Phone',
                  '${s.sources[src]?.$1 ?? 0}/${s.sources[src]?.$2 ?? s.total}',
                  Key('train_src_$src'),
                ),
            ],
          ),
        ],
      ),
    );
  }

  /// The one button that fixes [action] (the "Not ready" note's cause): resume, or switch to gesture mode.
  Widget _fixButton(BuildContext context, String action) {
    final b = backend!;
    if (action == 'gesture_mode') {
      return OutlinedButton.icon(
        key: const Key('train_fix_mode'),
        icon: const PixelGlyph(Icons7.hand),
        label: const Text('Switch to gesture mode'),
        onPressed: () async {
          await b.deviceCommand(mode: 'gesture');
          await flow.refresh();
        },
      );
    }
    return FilledButton.icon(
      key: const Key('train_fix_resume'),
      icon: const PixelGlyph(Icons7.play),
      label: const Text('Resume Canti'),
      onPressed: () async {
        await b.setPaused(false);
        await b.deviceCommand(armed: true);
        await flow.refresh();
      },
    );
  }
}

class _CardGrid extends StatelessWidget {
  const _CardGrid({required this.flow, required this.status});

  final TrainFlow flow;
  final TrainStatus status;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final gs = status.gestures;
    return Column(
      children: [
        for (var r = 0; r < gs.length; r += 2) ...[
          if (r > 0) SizedBox(height: p(2)),
          IntrinsicHeight(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Expanded(
                  child: _Card(g: gs[r], selected: flow.selected == gs[r].name, onTap: () => flow.select(gs[r].name)),
                ),
                SizedBox(width: p(2)),
                Expanded(
                  child: r + 1 < gs.length
                      ? _Card(
                          g: gs[r + 1],
                          selected: flow.selected == gs[r + 1].name,
                          onTap: () => flow.select(gs[r + 1].name),
                        )
                      : const SizedBox(),
                ),
              ],
            ),
          ),
        ],
      ],
    );
  }
}

/// A gesture card: glyph, name, done/total and a bar; inverted when every take is recorded, bracketed when selected.
class _Card extends StatelessWidget {
  const _Card({required this.g, required this.selected, this.onTap});

  final TrainGesture g;
  final bool selected;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    final inv = g.complete;
    final fg = inv ? t.paper : t.ink;
    return Semantics(
      button: onTap != null,
      selected: selected,
      label: '${g.name}, ${g.done} of ${g.total} takes',
      child: GestureDetector(
        key: Key('train_card_${g.name}'),
        behavior: HitTestBehavior.opaque,
        onTap: onTap,
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 48),
          child: PixelPaint(
            art: _CardArt(inv ? t.ink : t.paper, t.ink, fg, selected),
            child: Padding(
              padding: EdgeInsets.all(p(4)),
              child: ExcludeSemantics(
                child: Row(
                  children: [
                    PixelGlyph(GestureGlyphs.bySound[g.name] ?? Icons7.sound, color: fg),
                    SizedBox(width: p(3)),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          PixelSnap(child: Text(g.name.toUpperCase(), style: p.title(fg))),
                          SizedBox(height: p(2)),
                          Row(
                            children: [
                              Expanded(
                                child: SizedBox(
                                  height: p(5),
                                  child: PixelPaint(art: _BarArt(g.done, g.total, fg)),
                                ),
                              ),
                              SizedBox(width: p(2)),
                              Text('${g.done}/${g.total}', key: Key('train_count_${g.name}'), style: p.body(fg)),
                            ],
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _CardArt extends PixelArt {
  const _CardArt(this.fill, this.line, this.mark, this.selected);

  final Color fill;
  final Color line;
  final Color mark;
  final bool selected;

  @override
  void paint(PixelCanvas c) {
    c.block(0, 0, c.w, c.h, fill);
    c.frame(0, 0, c.w, c.h, line, notch: true);
    if (selected) {
      c.frame(2, 2, c.w - 4, c.h - 4, mark, dotted: true);
    }
  }

  @override
  bool shouldRepaint(_CardArt old) =>
      old.fill != fill || old.line != line || old.mark != mark || old.selected != selected;
}

class _BarArt extends PixelArt {
  const _BarArt(this.value, this.max, this.c);

  final int value;
  final int max;
  final Color c;

  @override
  void paint(PixelCanvas c0) {
    c0.frame(0, 0, c0.w, c0.h, c);
    if (max <= 0) return;
    final inner = c0.w - 4;
    c0.block(2, 2, (inner * value / max).round().clamp(0, inner), c0.h - 4, c);
  }

  @override
  bool shouldRepaint(_BarArt old) => old.value != value || old.max != max || old.c != c;
}

/// The selected card: its cells (done or not; a done one can be recorded again), Record missing, Delete / redo.
class _CardWindow extends StatelessWidget {
  const _CardWindow({required this.flow, required this.status, required this.gesture});

  final TrainFlow flow;
  final TrainStatus status;
  final TrainGesture gesture;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final g = gesture;
    final f = flow;
    final missing = g.total - g.done;
    final canRecord = status.trainable && !f.busy;
    final confirm = f.confirmDelete == g.name;
    final gap = SizedBox(height: p(4));
    return PixelWindow(
      key: const Key('train_card_window'),
      title: '${_cap(g.name)} ${g.done}/${g.total}',
      onClose: () => f.select(g.name),
      closeLabel: 'Close card',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SignalNote(
            signal: g.complete ? Signal.idle : Signal.waiting,
            text: [
              g.complete ? 'Every take is recorded.' : '$missing of ${g.total} takes to record.',
              if (g.active) 'The matcher uses it (${g.examples} examples).' else 'The matcher uses it from 3 takes on.',
              if (g.kept > 0) '${g.kept} kept anyway.',
              if (g.extra > 0) '${g.extra} more enrolled outside training.',
            ].join(' '),
            textKey: Key('train_card_note_${g.name}'),
          ),
          gap,
          for (final c in g.cells) ...[_CellRow(cell: c), SizedBox(height: p(1))],
          gap,
          if (confirm) ...[
            SignalNote(
              signal: Signal.stop,
              text:
                  'Delete all ${g.examples} ${g.name} takes for the ${sourceLabel(status.source)}? Press Delete again.',
              textKey: const Key('train_delete_confirm'),
            ),
            gap,
          ],
          Wrap(
            spacing: p(2),
            runSpacing: p(2),
            children: [
              if (missing > 0)
                FilledButton.icon(
                  key: const Key('train_record_missing'),
                  icon: const PixelGlyph(Icons7.play),
                  label: Text(g.done == 0 ? 'Record' : 'Record missing ($missing)'),
                  onPressed: canRecord ? () => f.startRound(g.name) : null,
                ),
              OutlinedButton.icon(
                key: const Key('train_delete'),
                icon: const PixelGlyph(Marks.cross),
                label: Text(confirm ? 'Delete' : 'Delete / redo'),
                onPressed: f.busy || g.examples == 0 ? null : () => f.delete(g.name),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _CellRow extends StatelessWidget {
  const _CellRow({required this.cell});

  final TrainCell cell;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    return Semantics(
      label: '${cell.prompt}, ${cell.done ? 'recorded' : 'not recorded'}',
      child: KeyedSubtree(
        key: Key('train_cell_${cell.id}'),
        child: ExcludeSemantics(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(
                padding: EdgeInsets.only(top: p(1)),
                child: PixelGlyph(cell.done ? Icons7.pipOn : Icons7.pipOff),
              ),
              SizedBox(width: p(3)),
              Expanded(child: Text(cell.prompt, style: p.body(t.ink, line: 11))),
            ],
          ),
        ),
      ),
    );
  }
}

// --- a round ----------------------------------------------------------------------------------------------------

class _SessionWindow extends StatelessWidget {
  const _SessionWindow({required this.flow, required this.status, required this.session});

  final TrainFlow flow;
  final TrainStatus status;
  final TrainSession session;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    final f = flow;
    final s = session;
    final gap = SizedBox(height: p(4));
    final h = s.heard;
    final done = s.state == 'done';
    final take = done ? 'round done' : 'take ${s.index + 1} of ${s.count}';
    final g = status.gesture(s.gesture);

    final (Signal, String, Key) note = switch (s.state) {
      'recording' => (
        Signal.listening,
        s.heardN > 0
            ? 'Heard it, checking...'
            : 'Listening: make the sound now.${s.leftMs != null ? ' ${(s.leftMs! / 1000).ceil()} s left.' : ''}',
        const Key('train_state'),
      ),
      'passed' => (
        Signal.idle,
        s.kept.contains(s.cell) ? 'Kept anyway and stored.' : 'Good: stored.',
        const Key('train_state'),
      ),
      'failed' => (Signal.stop, s.reason ?? 'That take did not work.', const Key('train_reason')),
      'done' => (
        Signal.idle,
        'Round done: ${s.passed.length} stored'
            '${s.kept.isNotEmpty ? ' (${s.kept.length} kept anyway)' : ''}'
            '${s.skipped.isNotEmpty ? ', ${s.skipped.length} skipped' : ''}.'
            '${g == null ? '' : ' ${_cap(g.name)}: ${g.done} of ${g.total} takes${g.complete ? '' : ' (the rest wait on the card)'}.'}'
            '${g != null && g.active ? ' The matcher uses them.' : ''}',
        const Key('train_state'),
      ),
      _ => (Signal.waiting, 'Press Record, then make the sound.', const Key('train_state')),
    };

    final busy = f.busy;
    final buttons = <Widget>[
      if (s.state == 'ready')
        FilledButton.icon(
          key: const Key('train_record'),
          icon: const PixelGlyph(Icons7.play),
          label: const Text('Record'),
          onPressed: busy ? null : f.record,
        ),
      if (s.state == 'failed') ...[
        FilledButton.icon(
          key: const Key('train_retry'),
          icon: const PixelGlyph(Icons7.refresh),
          label: const Text('Retry'),
          onPressed: busy ? null : f.retry,
        ),
        OutlinedButton.icon(
          key: const Key('train_skip'),
          icon: const PixelGlyph(Marks.right),
          label: const Text('Skip'),
          onPressed: busy ? null : f.skip,
        ),
        if (s.canKeep)
          OutlinedButton.icon(
            key: const Key('train_keep'),
            icon: const PixelGlyph(Icons7.target),
            label: const Text('Keep anyway'),
            onPressed: busy ? null : f.keep,
          ),
      ],
      if (s.state == 'ready')
        OutlinedButton.icon(
          key: const Key('train_skip'),
          icon: const PixelGlyph(Marks.right),
          label: const Text('Skip'),
          onPressed: busy ? null : f.skip,
        ),
      if (s.state == 'passed')
        FilledButton.icon(
          key: const Key('train_next'),
          icon: const PixelGlyph(Icons7.play),
          label: Text(s.nextPrompt != null ? 'Record next' : 'Finish'),
          onPressed: busy ? null : f.next,
        ),
      if (done)
        FilledButton.icon(
          key: const Key('train_done'),
          icon: const PixelGlyph(Marks.left),
          label: const Text('Back to cards'),
          onPressed: busy ? null : f.stop,
        )
      else
        OutlinedButton.icon(
          key: const Key('train_stop'),
          icon: const PixelGlyph(Icons7.pause),
          label: const Text('Stop'),
          onPressed: busy ? null : f.stop,
        ),
    ];

    return PixelWindow(
      key: const Key('train_session'),
      title: _cap(s.gesture),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          PixelSnap(
            child: Text(
              '${sourceLabel(s.source ?? status.source)} · $take',
              key: const Key('train_take'),
              style: p.body(t.ink),
            ),
          ),
          SizedBox(height: p(3)),
          if (done && g != null)
            _Card(g: g, selected: false)
          else ...[
            Text(s.prompt ?? '', key: const Key('train_prompt'), style: p.big(t.ink)),
            if (s.hint != null) ...[
              SizedBox(height: p(2)),
              Text(s.hint!, key: const Key('train_hint'), style: p.body(t.ink, line: 11)),
            ],
            gap,
            _Trace(session: s, live: status.liveTrace),
          ],
          gap,
          SignalNote(signal: note.$1, text: note.$2, textKey: note.$3),
          if (h != null && !done) ...[gap, _HeardPanel(heard: h, contour: g?.kind != 'discrete')],
          gap,
          Wrap(spacing: p(2), runSpacing: p(2), children: buttons),
          if (s.nextPrompt != null && !done) ...[
            gap,
            Text('Next: ${s.nextPrompt}', key: const Key('train_next_prompt'), style: p.body(t.ink, line: 11)),
          ],
        ],
      ),
    );
  }
}

/// What the extractor heard in the last take.
class _HeardPanel extends StatelessWidget {
  const _HeardPanel({required this.heard, required this.contour});

  final TrainHeard heard;
  final bool contour;

  @override
  Widget build(BuildContext context) {
    final h = heard;
    final label = h.sounds > 1
        ? h.labels.join(' then ')
        : '${h.label ?? '-'}${h.shape != null && h.label != 'unknown' ? ' (${h.shape})' : ''}';
    final tone = h.tone == null ? '-' : '${h.tone}${h.f0Hz != null ? ', ${h.f0Hz} Hz' : ''}';
    return CalibPanel(
      rows: [
        (Icons7.decider, 'Heard', label, const Key('train_heard')),
        if (contour) (Icons7.sound, 'Tone', tone, const Key('train_heard_tone')),
        if (contour && h.startHz != null)
          (Icons7.cursor, 'Start', hzLabel(h.startHz!.toDouble()), const Key('train_heard_start')),
        (Icons7.hourglass, 'Length', h.durMs == null ? '-' : _secs(h.durMs!), const Key('train_heard_len')),
        if (!contour && h.loudness != null) (Icons7.power, 'Loudness', h.loudness!, const Key('train_heard_loud')),
      ],
    );
  }
}

/// The pitch trace: the live mic ticks while recording (phone / USB mic), else the heard take's contour.
class _Trace extends StatelessWidget {
  const _Trace({required this.session, required this.live});

  final TrainSession session;
  final bool live;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    final s = session;
    final recording = s.state == 'recording';
    final heard = s.heard?.pitch16 ?? const <double>[];
    final List<double?> semis;
    final String caption;
    if (recording && live) {
      final hz = s.live.traceHz;
      final ref = hz.whereType<double>().firstOrNull;
      semis = [for (final x in hz) x == null || ref == null ? null : 12 * math.log(x / ref) / math.ln2];
      final pitch = s.live.pitchHz;
      caption =
          'Live pitch${pitch != null ? ' · ${hzLabel(pitch)}' : ''}'
          '${s.live.levelDb != null ? ' · ${s.live.levelDb!.round()} dB' : ''}';
    } else if (heard.isNotEmpty) {
      semis = heard;
      caption = 'What Canti heard (pitch, from the start)';
    } else {
      semis = const [];
      caption = recording
          ? 'No live trace from the Canti device: the shape shows after the take.'
          : s.heard != null
          ? 'No pitch track (an unpitched sound).'
          : 'The pitch trace shows here while you record.';
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SizedBox(
          key: const Key('train_trace'),
          height: p(44),
          child: PixelPaint(art: _TraceArt(semis, t.ink, recording)),
        ),
        SizedBox(height: p(1)),
        Text(caption, key: const Key('train_trace_caption'), style: p.body(t.ink)),
      ],
    );
  }
}

class _TraceArt extends PixelArt {
  const _TraceArt(this.semis, this.ink, this.recording);

  /// Semitones from the first voiced point (null = unvoiced).
  final List<double?> semis;
  final Color ink;
  final bool recording;

  @override
  void paint(PixelCanvas c) {
    c.frame(0, 0, c.w, c.h, ink, notch: true);
    final w = c.w - 6;
    final h = c.h - 6;
    if (w <= 0 || h <= 0) return;
    // dotted mid line
    for (var x = 3; x < 3 + w; x += 3) {
      c.rect(x, 3 + h ~/ 2, 1, 1, ink);
    }
    final vals = semis.whereType<double>();
    if (vals.isEmpty) return;
    var lo = vals.reduce(math.min);
    var hi = vals.reduce(math.max);
    // at least an octave of height so a flat note stays flat
    final mid = (lo + hi) / 2;
    if (hi - lo < 12) {
      lo = mid - 6;
      hi = mid + 6;
    }
    // live: 250 ticks (5 s) across; heard: the 16 points across
    final n = recording ? math.max(semis.length, 150) : semis.length;
    int? px, py;
    for (var i = 0; i < semis.length; i++) {
      final v = semis[i];
      if (v == null) {
        px = null;
        continue;
      }
      final x = 3 + (n <= 1 ? 0 : (i * (w - 2) / (n - 1)).round());
      final y = 3 + ((hi - v) / (hi - lo) * (h - 2)).round();
      if (px != null && py != null) {
        // join to the previous point with a vertical run
        final y0 = math.min(py, y), y1 = math.max(py, y);
        for (var xx = px; xx <= x; xx++) {
          final yy = px == x ? y : (py + (y - py) * (xx - px) / (x - px)).round();
          c.rect(xx, yy, 2, 2, ink);
        }
        if (x - px <= 1) c.rect(x, y0, 2, y1 - y0 + 1, ink);
      } else {
        c.rect(x, y, 2, 2, ink);
      }
      px = x;
      py = y;
    }
  }

  @override
  bool shouldRepaint(_TraceArt old) => old.semis != semis || old.ink != ink || old.recording != recording;
}

// --- the status screen's entry -----------------------------------------------------------------------------------

/// The status screen's "Train gestures" window: progress per mic source and the button that opens [TrainScreen].
class TrainGesturesWindow extends StatefulWidget {
  const TrainGesturesWindow({super.key, required this.backend, required this.source, this.train});

  final VoxBackend backend;

  /// The current sound source.
  final String source;

  /// By default [trainBackendFor] the backend.
  final TrainBackend? train;

  @override
  State<TrainGesturesWindow> createState() => _TrainGesturesWindowState();
}

class _TrainGesturesWindowState extends State<TrainGesturesWindow> {
  late final TrainBackend _train = widget.train ?? trainBackendFor(widget.backend);
  TrainStatus? _status;
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(TrainGesturesWindow old) {
    super.didUpdateWidget(old);
    if (old.source != widget.source) _load();
  }

  Future<void> _load() async {
    try {
      final s = await _train.status();
      if (!mounted) return;
      setState(() {
        _status = s;
        _failed = false;
      });
    } catch (_) {
      if (mounted) setState(() => _failed = true);
    }
  }

  Future<void> _open() async {
    await openTraining(context, widget.backend, train: _train);
    if (mounted) await _load();
  }

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final s = _status;
    final src = s?.currentSource ?? widget.source;
    final done = s?.sources[src]?.$1 ?? s?.done;
    final total = s?.sources[src]?.$2 ?? s?.total;
    final text = s == null
        ? (_failed ? 'Training is not available right now.' : 'Loading...')
        : done == 0
        ? 'Teach Canti your own version of each gesture on the ${sourceLabel(src)}: hummed and whistled, low '
              'and high, slow and quick. One card at a time, about 10 s a take.'
        : '${sourceLabel(src)}: $done of $total takes recorded.';
    return PixelWindow(
      key: const Key('train_entry'),
      title: 'Train gestures',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SignalNote(
            signal: s != null && done != null && total != null && done >= total ? Signal.idle : Signal.waiting,
            text: text,
            textKey: const Key('train_entry_note'),
          ),
          if (s != null) ...[
            SizedBox(height: p(3)),
            CalibPanel(
              rows: [
                for (final x in trainSources)
                  (
                    x == src ? Icons7.sound : Icons7.pipOff,
                    x == 'pico'
                        ? 'Canti'
                        : x == 'usb'
                        ? 'USB'
                        : 'Phone',
                    '${s.sources[x]?.$1 ?? 0}/${s.sources[x]?.$2 ?? s.total}',
                    Key('train_entry_$x'),
                  ),
              ],
            ),
          ],
          SizedBox(height: p(3)),
          Align(
            alignment: Alignment.centerLeft,
            child: FilledButton.icon(
              key: const Key('train_open'),
              icon: const PixelGlyph(Icons7.hand),
              label: Text(done != null && done > 0 ? 'Train gestures' : 'Start training'),
              onPressed: _failed ? null : _open,
            ),
          ),
        ],
      ),
    );
  }
}
