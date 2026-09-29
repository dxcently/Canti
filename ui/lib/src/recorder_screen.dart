import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'backend.dart';
import 'quickrec_screen.dart';
import 'recorder.dart';
import 'shape_plot.dart';
import 'theme/canti_theme.dart';
import 'theme/dither_background.dart';
import 'theme/dock.dart';
import 'theme/glyphs.dart';
import 'theme/kit.dart';
import 'theme/pixel.dart';

/// Opens the in-app test recorder screen.
Future<void> openRecorder(BuildContext context, VoxBackend backend, {RecorderBackend? recorder}) =>
    Navigator.of(context).push<void>(
        MaterialPageRoute(builder: (_) => RecorderScreen(backend: backend, recorder: recorder ?? recorderBackendFor(backend))));

/// The spec's cond values in words, for the take's chips (`normal` and `na` are left out).
String? condWords(String key, String? v) => switch ((key, v)) {
      ('pitch', 'bottom') => 'lowest note',
      ('pitch', 'home') => 'home note',
      ('pitch', 'top') => 'highest note',
      ('speed', 'slow') => 'slow',
      ('speed', 'quick') => 'quick',
      ('loud', 'soft') => 'soft',
      ('loud', 'loud') => 'loud',
      ('dist', 'hand') => 'phone in hand',
      ('dist', 'table') => 'phone on the table',
      ('dist', 'across') => 'across the room',
      ('tone', 'hum') => 'hum',
      ('tone', 'whistle') => 'whistle',
      ('gap', 'quick') => 'short gap',
      ('gap', 'slow') => 'long gap',
      _ => null,
    };

/// What the recorder shows. The service's state picks it, except that the user can go back to the blocks at any time.
enum _View { loading, off, start, hub, take, saved, rate, done }

/// The dev-only in-app test recorder (SHARED CONTRACT §0-§8): start or resume a session, walk its takes block by
/// block, see what Canti heard vs the expected shape after each save, rate each block, and finish with the pull line.
/// Every control is in the [ActionDock]; the content has only list rows. Back goes to the blocks (dropping an
/// in-flight take), and from the blocks ends the sitting: every saved take stays on disk and the session is listed to
/// resume next time.
class RecorderScreen extends StatefulWidget {
  const RecorderScreen({super.key, required this.backend, this.recorder, this.flow});

  final VoxBackend backend;

  /// By default [recorderBackendFor] the backend.
  final RecorderBackend? recorder;

  /// A flow to drive (tests, the desktop preview); by default the screen makes its own.
  final RecorderFlow? flow;

  @override
  State<RecorderScreen> createState() => _RecorderScreenState();
}

class _RecorderScreenState extends State<RecorderScreen> {
  late final RecorderFlow _flow = widget.flow ?? RecorderFlow(backend: widget.recorder ?? recorderBackendFor(widget.backend));
  BackdropMood? _mood;

  // the start / rate form state (the dock's buttons need it, so it lives here)
  String _who = 'me';
  String _profile = 'short';
  final _speaker = TextEditingController();
  int? _rating;
  final _note = TextEditingController();
  String? _soundSource;
  bool _sourceKnown = false;

  /// The user went back to the blocks (the service's state is unchanged).
  bool _hub = false;

  @override
  void initState() {
    super.initState();
    _flow.addListener(_toMood);
    _flow.attach();
    _loadSource();
  }

  Future<void> _loadSource() async {
    try {
      final s = await widget.backend.status();
      if (mounted) setState(() => _soundSource = s.soundSource);
    } catch (_) {
      // unknown: the service refuses a Pico start itself
    }
    if (mounted) setState(() => _sourceKnown = true);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _mood = BackdropMood.maybeOf(context);
  }

  void _toMood() {
    final s = _flow.status;
    _mood?.listen(s != null && s.state == 'recording', levelDb: s?.level.peakDbfs);
  }

  @override
  void dispose() {
    _flow.removeListener(_toMood);
    _mood?.listen(false);
    _speaker.dispose();
    _note.dispose();
    _flow.close(); // ends an open sitting, so sounds act again (the takes stay stored)
    if (widget.flow == null) _flow.dispose();
    super.dispose();
  }

  _View _view(RecStatus? s) {
    if (s == null) return _View.loading;
    if (!s.enabled) return _View.off;
    if (!s.active) return _View.start;
    if (_hub) return _View.hub;
    return switch (s.state) {
      'rate' => _View.rate,
      'done' => _View.done,
      'saved' || 'no_sound' when s.take != null => _View.saved,
      _ when s.take != null => _View.take,
      _ => _View.hub,
    };
  }

  static bool _inFlight(RecStatus s) => const {'ready', 'countdown', 'recording'}.contains(s.state);

  /// Back: from a take to the blocks (an in-flight take is dropped, not saved); from the blocks out of the recorder.
  Future<void> _back() async {
    final s = _flow.status;
    final view = _view(s);
    if (s != null && s.active && view != _View.hub) {
      if (_inFlight(s)) await _flow.abort();
      if (mounted) setState(() => _hub = true);
      return;
    }
    await _flow.close();
    if (mounted) Navigator.of(context).pop();
  }

  /// Calls [f] and leaves the blocks view (the service's state shows again).
  Future<void> _act(Future<void> Function() f) async {
    setState(() => _hub = false);
    await f();
  }

  bool get _other => _who == 'other';
  String? get _speakerError {
    final s = _speaker.text.trim();
    if (!_other) return null;
    if (s.isEmpty) return 'a nickname is needed';
    if (!RegExp(r'^[A-Za-z0-9_-]{1,24}$').hasMatch(s)) return 'letters, digits, - and _, up to 24';
    if (s == 'self') return 'not "self"';
    return null;
  }

  bool get _pico => _soundSource == 'pico';
  static const _picoText = 'The Pico sends no audio. Switch the sound source to the phone or USB mic.';

  /// The block being rated (state `rate`): the first unrated block whose takes are all saved or skipped.
  RecBlock? _rateBlock(RecStatus s) {
    for (final b in s.blocks) {
      if (b.rating == null && b.total > 0 && b.done + b.skipped >= b.total) return b;
    }
    return null;
  }

  /// The block after [current] that still has takes to record, or null.
  String? _nextBlockTitle(RecStatus s, String? current) {
    final i = s.blocks.indexWhere((b) => b.id == current);
    for (final b in [...s.blocks.skip(i + 1), ...s.blocks.take(math.max(0, i))]) {
      if (b.done + b.skipped < b.total) return b.title;
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _back();
      },
      child: Scaffold(
        body: SafeArea(
          child: ListenableBuilder(
            listenable: _flow,
            builder: (context, _) {
              final f = _flow;
              final s = f.status;
              final view = _view(s);
              final Widget body = switch (view) {
                _View.loading => const SignalNote(signal: Signal.waiting, text: 'Loading...', textKey: Key('rec_loading')),
                _View.off => const SignalNote(signal: Signal.idle, text: 'The recorder is not in this build.'),
                _View.start => _start(f, s!),
                _View.hub => _blocks(s!),
                _View.take => _take(s!, s.take!),
                _View.saved => _saved(s!, s.take!),
                _View.rate => _rate(s!),
                _View.done => _done(s!),
              };
              return Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Padding(padding: EdgeInsets.fromLTRB(p(5), p(5), p(5), 0), child: _header(f, s, view)),
                  if (f.error != null)
                    Padding(
                      padding: EdgeInsets.fromLTRB(p(5), p(4), p(5), 0),
                      child: PixelWindow(
                        title: 'Refused',
                        onClose: f.dismissError,
                        closeLabel: 'Dismiss',
                        child: SignalNote(signal: Signal.stop, text: f.error!, textKey: const Key('rec_error')),
                      ),
                    ),
                  Expanded(
                    child: view == _View.take
                        ? Padding(padding: EdgeInsets.all(p(5)), child: body)
                        : SingleChildScrollView(padding: EdgeInsets.all(p(5)), child: body),
                  ),
                  if (s != null && s.enabled) _dock(f, s, view),
                ],
              );
            },
          ),
        ),
      ),
    );
  }

  // --- the header: back, the title, and on a take the working ◀ i/n ▶ ---------------------------------------------

  Widget _header(RecorderFlow f, RecStatus? s, _View view) {
    final p = Px.of(context);
    final take = s?.take;
    final onTake = (view == _View.take || view == _View.saved) && take != null && take.n > 0;
    final title = switch (view) {
      _View.take || _View.saved => 'Recorder', // the block goes in the window's tab: a long block name would wrap here
      _View.rate => 'Block done',
      _View.done => 'Session done',
      _ => 'Test recorder',
    };
    return Row(
      children: [
        Expanded(child: ScreenHeader(backKey: const Key('rec_back'), title: title, onBack: _back)),
        if (onTake) ...[
          SizedBox(width: p(2)),
          PixelPager(
            key: const Key('rec_pager'),
            index: take.i - 1,
            count: take.n,
            onChanged: f.busy ? (_) {} : (index) => _page(f, s!, take, index),
          ),
        ],
      ],
    );
  }

  /// The pager's arrows: the previous / next take of the plan (no wrap-around at the ends). Needs rec_status.plan;
  /// without it, back redoes the last saved take and forward goes to the next unrecorded one.
  void _page(RecorderFlow f, RecStatus s, RecTake take, int index) {
    final cur = take.i - 1, n = take.n;
    final int target;
    if (index == cur + 1) {
      target = cur + 1;
    } else if (index == cur - 1) {
      target = cur - 1;
    } else {
      return; // the pager wrapped around an end
    }
    if (target < 0 || target >= n) return;
    if (s.plan.length == n) {
      _act(() => f.next(takeId: s.plan[target]));
    } else if (target < cur) {
      _act(f.redoLast);
    } else if (s.next?.takeId != null && s.next!.takeId != take.takeId) {
      _act(() => f.next(takeId: s.next!.takeId));
    }
  }

  // --- the start screen -----------------------------------------------------------------------------------------------

  Widget _start(RecorderFlow f, RecStatus s) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    final speaker = _other ? (_speaker.text.trim().isEmpty ? '<nickname>' : _speaker.text.trim()) : 'self';
    final mic = switch (_soundSource) {
      'pico' => _picoText,
      'usb' => 'USB mic (the routed input)',
      null => '...',
      _ => 'Phone built-in mic',
    };
    final others = [for (final x in f.sessions) if (!x.open) x];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        PixelWindow(
          key: const Key('rec_start'),
          title: 'New session',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _label('Who', const Key('rec_who')),
              SizedBox(height: p(2)),
              PixelToggle<String>(
                options: const [('me', 'Me', Icons7.hand), ('other', 'Other', Icons7.app)],
                selected: _who,
                onChanged: (v) => setState(() => _who = v),
              ),
              if (_other) ...[
                SizedBox(height: p(4)),
                _label('Speaker nickname', const Key('rec_speaker_label')),
                SizedBox(height: p(2)),
                TextField(
                  key: const Key('rec_speaker'),
                  controller: _speaker,
                  style: p.body(t.ink),
                  onChanged: (_) => setState(() {}),
                  decoration: const InputDecoration(hintText: 'a nickname, never a real name'),
                ),
              ],
              SizedBox(height: p(4)),
              _label('Length', const Key('rec_length')),
              SizedBox(height: p(2)),
              PixelToggle<String>(
                options: const [('short', 'Short', Icons7.hourglass), ('full', 'Full', Icons7.hourglass)],
                selected: _profile,
                onChanged: (v) => setState(() => _profile = v),
              ),
              SizedBox(height: p(2)),
              PixelSnap(
                child: Text(
                  _profile == 'short' ? '42 takes · about 15 min' : '269 takes + 7 backgrounds · about 2 h, over several sittings',
                  key: const Key('rec_length_note'),
                  style: p.body(t.ink, line: 11),
                ),
              ),
              SizedBox(height: p(4)),
              _label('Mic', const Key('rec_mic')),
              SizedBox(height: p(2)),
              SignalNote(signal: _pico ? Signal.stop : Signal.idle, textKey: const Key('rec_mic_value'), text: mic),
              SizedBox(height: p(4)),
              PixelSnap(
                child: Text('Saves as range-$speaker-MMDD', key: const Key('rec_saves'), style: p.body(t.ink, line: 11)),
              ),
            ],
          ),
        ),
        if (others.isNotEmpty) ...[
          SizedBox(height: p(5)),
          PixelWindow(
            key: const Key('rec_other_sessions'),
            title: 'Other sessions',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                for (final x in others)
                  _row(
                    key: Key('rec_session_${x.name}'),
                    icon: Icons7.sound,
                    label: x.speaker == null || x.speaker == 'self' ? 'Me · ${x.profile ?? ''}' : '${x.speaker} · ${x.profile ?? ''}',
                    value: '${x.done}/${x.total}',
                    onTap: f.busy ? null : () => _act(() => f.open(x.name)),
                  ),
              ],
            ),
          ),
        ],
      ],
    );
  }

  Widget _label(String text, Key key) {
    final p = Px.of(context);
    return PixelSnap(child: Text(text.toUpperCase(), key: key, style: p.title(CantiTheme.of(context).ink)));
  }

  /// A tappable list row: a framed icon, a LABEL, a dotted leader and the value (a 48 dp target).
  Widget _row({required Key key, required Glyph icon, required String label, required String value, VoidCallback? onTap}) {
    final p = Px.of(context);
    return InkWell(
      key: key,
      onTap: onTap,
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 48),
        child: Padding(
          padding: EdgeInsets.symmetric(vertical: p(3)),
          child: Row(
            children: [
              Expanded(child: StatRow(icon: icon, label: label, value: value)),
              SizedBox(width: p(2)),
              PixelGlyph(Marks.right, color: CantiTheme.of(context).ink),
            ],
          ),
        ),
      ),
    );
  }

  // --- the blocks hub -------------------------------------------------------------------------------------------------

  Widget _blocks(RecStatus s) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    return PixelWindow(
      key: const Key('rec_hub'),
      title: '${s.speaker == null || s.speaker == 'self' ? 'Me' : s.speaker} · ${s.profile ?? ''} ${s.done}/${s.total}',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          PixelSnap(
            child: Text(
              s.name ?? '',
              key: const Key('rec_hub_progress'),
              style: p.body(t.ink, line: 11),
            ),
          ),
          SizedBox(height: p(2)),
          PixelSnap(child: Text('Tap a block to record or redo its takes.', style: p.body(t.ink, line: 11))),
          SizedBox(height: p(2)),
          for (final b in s.blocks)
            _row(
              key: Key('rec_block_${b.id}'),
              icon: b.total > 0 && b.done + b.skipped >= b.total ? tickGlyph : Icons7.decider,
              label: b.title,
              value: blockStatus(b),
              onTap: _flow.busy ? null : () => _openBlock(s, b),
            ),
        ],
      ),
    );
  }

  /// A block row (rec_next {take_id}): an unfinished block goes on at the next unrecorded take when that is in it, else
  /// starts at its first take (a finished block: redo from the top). Without rec_status.plan, the next unrecorded take.
  void _openBlock(RecStatus s, RecBlock b) {
    final nextId = s.next?.takeId;
    final i = nextId == null ? -1 : s.plan.indexOf(nextId);
    final nextHere = i >= 0 && i < s.planBlocks.length && s.planBlocks[i] == b.id;
    final finished = b.total > 0 && b.done + b.skipped >= b.total;
    _act(() => _flow.next(takeId: !finished && nextHere ? nextId : s.firstTakeOf(b.id)));
  }

  // --- the take -------------------------------------------------------------------------------------------------------

  Widget _take(RecStatus s, RecTake take) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    final countdown = s.state == 'countdown';
    final recording = s.state == 'recording';
    final ready = s.state == 'ready';
    final recS = s.recS ?? 0;
    final chips = [
      for (final k in const ['pitch', 'speed', 'loud', 'dist', 'tone', 'gap']) ?condWords(k, take.cond[k]),
    ];

    // what goes above the cue: the countdown, the seconds left of a fixed take, or a one-line prompt
    final Widget? lead;
    if (countdown) {
      lead = _BigLine(number: '${s.countdownS ?? 3}', text: 'far take: get in place', numberKey: const Key('rec_countdown'));
    } else if (recording && (take.quiet || take.bg != null)) {
      final total = take.bg != null ? (take.seconds ?? take.maxS ?? 60) : (take.maxS ?? take.targetS ?? 3.5);
      lead = _BigLine(
        number: '${math.max(0, (total - recS).ceil())}',
        text: 's left',
        numberKey: const Key('rec_room'),
      );
    } else if (ready && take.manual) {
      lead = _line('Start the media, then tap START.', const Key('rec_manual'));
    } else if (ready) {
      lead = _line('Get ready…', const Key('rec_ready'));
    } else if (s.state == 'error') {
      lead = SignalNote(signal: Signal.stop, textKey: const Key('rec_take_error'), text: s.reason ?? s.error ?? 'The take stopped.');
    } else if (!recording) {
      lead = _line('Stopped. START records it again.', const Key('rec_stopped'));
    } else {
      lead = null;
    }
    final cue = take.quiet && recording ? 'Stay quiet' : (take.cue ?? '');

    return PixelWindow(
      key: const Key('rec_take'),
      title: '${take.blockTitle ?? take.block ?? 'Take'} · ${take.blockI}/${take.blockN}',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Wrap(
            spacing: p(2),
            runSpacing: p(2),
            children: [
              if (take.expect.isNotEmpty)
                PixelBox(
                  key: const Key('rec_expect'),
                  inverted: true,
                  padding: EdgeInsets.fromLTRB(p(4), p(2), p(3), p(2)),
                  child: PixelSnap(child: Text(take.expect.join(' ').toUpperCase(), style: p.big(t.paper))),
                ),
              for (final c in chips)
                PixelBox(
                  padding: EdgeInsets.fromLTRB(p(3), p(3), p(3), p(3)),
                  child: PixelSnap(child: Text(c.toUpperCase(), style: p.title(t.ink))),
                ),
            ],
          ),
          SizedBox(height: p(4)),
          ?lead,
          if (lead != null) SizedBox(height: p(3)),
          Expanded(child: _FitText(cue, key: const Key('rec_cue'))),
          SizedBox(height: p(3)),
          Row(
            children: [
              SignalLamp(recording ? Signal.listening : (countdown || ready ? Signal.waiting : Signal.idle)),
              SizedBox(width: p(4)),
              Expanded(
                child: PixelSnap(
                  child: Text(
                    recording ? 'REC ${recS.toStringAsFixed(1)} s' : (countdown ? 'Counting down' : (ready ? 'Ready' : 'Not recording')),
                    key: const Key('rec_seconds'),
                    style: p.big(t.ink),
                  ),
                ),
              ),
              PixelBox(
                inverted: true,
                child: PixelSnap(child: Text(_levelChip(s.level.note), key: const Key('rec_level_chip'), style: p.title(t.paper))),
              ),
            ],
          ),
          SizedBox(height: p(3)),
          LevelBars(key: const Key('rec_level'), barsDb: s.level.barsDb, minDb: s.level.minDb, height: 30),
        ],
      ),
    );
  }

  String _levelChip(String? note) => switch (note) {
        'quiet' => 'TOO QUIET',
        'good' => 'LEVEL GOOD',
        'loud' => 'TOO LOUD',
        _ => 'LEVEL',
      };

  Widget _line(String text, Key key) {
    final p = Px.of(context);
    return PixelSnap(child: Text(text, key: key, textAlign: TextAlign.center, style: p.big(CantiTheme.of(context).ink)));
  }

  // --- saved / no sound -----------------------------------------------------------------------------------------------

  Widget _saved(RecStatus s, RecTake take) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    final noSound = s.state == 'no_sound';
    final shaped = take.expect.isNotEmpty && !take.quiet && take.bg == null;
    final heard = s.heard;
    return PixelWindow(
      key: Key(noSound ? 'rec_no_sound' : 'rec_saved'),
      title: noSound ? 'No sound · take ${take.i}' : 'Saved · take ${take.i}',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (take.expect.isNotEmpty)
            PixelSnap(child: Text(take.expect.join(' ').toUpperCase(), style: p.big(t.ink))),
          if (shaped) ...[
            SizedBox(height: p(3)),
            ShapePlot(
              expected: ExpectedShape.forTake(expect: take.expect, cond: take.cond, defaults: s.defaults, targetS: take.targetS),
              scale: s.scale,
              heard: heard,
              height: 84,
              alignToHeard: true,
            ),
          ],
          SizedBox(height: p(5)),
          if (noSound) ...[
            PixelSnap(child: Text('Canti heard no sound.', key: const Key('rec_heard'), style: p.big(t.ink))),
            SizedBox(height: p(3)),
            SignalNote(
              signal: Signal.waiting,
              textKey: const Key('rec_no_sound_note'),
              text: 'The take is saved and flagged "no sound": the range suite counts it as a miss. '
                  'Try again to record another attempt, or skip.',
            ),
          ] else
            PixelSnap(child: Text(heardLine(heard, take), key: const Key('rec_heard'), style: p.big(t.ink))),
        ],
      ),
    );
  }

  // --- block end (rate) -----------------------------------------------------------------------------------------------

  Widget _rate(RecStatus s) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    final block = _rateBlock(s);
    final title = block?.title ?? 'this block';
    return PixelWindow(
      key: const Key('rec_rate'),
      title: title,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (block != null)
            PixelSnap(
              child: Text('${block.done} saved · ${block.skipped} skipped', style: p.body(t.ink, line: 11)),
            ),
          SizedBox(height: p(3)),
          PixelSnap(child: Text('How easy was $title?', key: const Key('rec_rate_title'), style: p.big(t.ink))),
          SizedBox(height: p(4)),
          Row(
            children: [
              for (var i = 1; i <= 5; i++) ...[
                if (i > 1) SizedBox(width: p(2)),
                Expanded(
                  child: Semantics(
                    button: true,
                    selected: _rating == i,
                    label: 'ease $i',
                    excludeSemantics: true,
                    child: InkWell(
                      key: Key('rec_rate_$i'),
                      onTap: () => setState(() => _rating = i),
                      child: SizedBox(
                        height: 48,
                        child: PixelBox(
                          inverted: _rating == i,
                          child: Center(child: PixelSnap(child: Text('$i', style: p.big(_rating == i ? t.paper : t.ink)))),
                        ),
                      ),
                    ),
                  ),
                ),
              ],
            ],
          ),
          SizedBox(height: p(2)),
          Row(
            children: [
              PixelSnap(child: Text('1 hard', style: p.body(t.ink))),
              const Spacer(),
              PixelSnap(child: Text('5 easy', style: p.body(t.ink))),
            ],
          ),
          SizedBox(height: p(4)),
          _label('Note (optional)', const Key('rec_rate_note_label')),
          SizedBox(height: p(2)),
          TextField(key: const Key('rec_rate_note'), controller: _note, style: p.body(t.ink), maxLines: 1),
        ],
      ),
    );
  }

  Future<void> _rateSubmit(RecorderFlow f, RecStatus s) async {
    final block = _rateBlock(s);
    final rating = _rating;
    if (block == null || rating == null) return;
    setState(() => _hub = false);
    await f.rate(block: block.id, rating: rating, note: _note.text.trim());
    if (f.error != null) return;
    setState(() => _rating = null);
    _note.clear();
    // rec_rate answers idle (or done): on to the next take
    if (f.status?.state == 'idle') await f.next();
  }

  // --- done -----------------------------------------------------------------------------------------------------------

  Widget _done(RecStatus s) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    final rated = s.blocks.where((b) => b.rating != null).length;
    final mb = (s.bytes / (1024 * 1024)).toStringAsFixed(1);
    return PixelWindow(
      key: const Key('rec_done'),
      title: 'Session done',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          PixelSnap(child: Text('${s.done} takes saved.', key: const Key('rec_summary'), style: p.big(t.ink))),
          SizedBox(height: p(3)),
          InvertedPanel(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                StatRow(icon: Icons7.hand, label: 'Speaker', value: s.speaker ?? 'self'),
                StatRow(icon: Icons7.hourglass, label: 'Length', value: s.profile ?? '?'),
                StatRow(icon: Icons7.refresh, label: 'Skipped', value: '${s.skipped}'),
                StatRow(icon: Icons7.decider, label: 'Rated', value: '$rated/${s.blocks.length} blocks'),
                StatRow(icon: Icons7.device, label: 'Size', value: '$mb MB'),
              ],
            ),
          ),
          SizedBox(height: p(4)),
          _label('To the PC', const Key('rec_to_pc')),
          SizedBox(height: p(2)),
          PixelSnap(child: Text('Plug the phone in, then run from android/:', style: p.body(t.ink, line: 11))),
          SizedBox(height: p(2)),
          SelectableText(
            './dev env python3 suite/range_phone.py pull',
            key: const Key('rec_pull'),
            style: p.body(t.ink, line: 11),
          ),
          SizedBox(height: p(2)),
          PixelSnap(child: Text('then finalize on the PC.', style: p.body(t.ink, line: 11))),
        ],
      ),
    );
  }

  // --- the dock: the same three slots on every screen -----------------------------------------------------------------

  Widget _dock(RecorderFlow f, RecStatus s, _View view) {
    final idle = !f.busy;
    final take = s.take;
    switch (view) {
      case _View.loading || _View.off:
        return ActionDock(main: DockAction('START', () {}, enabled: false));
      case _View.start:
        final refuse = _pico ? _picoText : (_speakerError != null ? 'Nickname: $_speakerError.' : null);
        return ActionDock(
          caption: refuse ?? 'Somewhere quiet, phone in hand.',
          main: DockAction(
            'START',
            () => _act(() => f.start(who: _who, speaker: _other ? _speaker.text.trim() : 'self', profile: _profile)),
            enabled: idle && refuse == null && _sourceKnown,
          ),
        );
      case _View.hub:
        final next = s.state == 'rate'
            ? 'Next: rate ${_rateBlock(s)?.title ?? 'the block'}.'
            : (s.state == 'done' ? 'Every take is done.' : (s.next?.cue != null ? 'Next: ${s.next!.cue}' : null));
        return ActionDock(
          caption: next,
          left: DockAction('CLOSE', () async {
            await f.close();
            if (mounted) setState(() => _hub = false);
          }, enabled: idle),
          main: DockAction(
            'CONTINUE',
            () => (s.state == 'rate' || s.state == 'done' || (s.take != null && s.state != 'idle'))
                ? setState(() => _hub = false)
                : _act(f.next),
            enabled: idle,
          ),
        );
      case _View.take:
        final running = s.state == 'recording' || s.state == 'countdown';
        return ActionDock(
          left: DockAction('REDO LAST', () => _act(f.redoLast), enabled: idle),
          right: DockAction('SKIP', () => _act(f.skip), enabled: idle),
          main: running
              ? DockAction('STOP', () => _act(f.abort), enabled: idle)
              : DockAction(
                  'START',
                  s.state == 'ready' ? () => _act(f.go) : () => _act(() => f.next(takeId: take?.takeId)),
                  enabled: idle,
                ),
        );
      case _View.saved:
        if (s.state == 'no_sound') {
          return ActionDock(
            left: DockAction('REDO LAST', () => _act(f.redoLast), enabled: idle),
            right: DockAction('SKIP', () => _act(f.skip), enabled: idle),
            main: DockAction('TRY AGAIN', () => _act(() => f.next(takeId: take?.takeId)), enabled: idle),
          );
        }
        return ActionDock(
          left: DockAction('REDO', () => _act(f.redoLast), enabled: idle),
          right: DockAction('BLOCKS', () => setState(() => _hub = true), enabled: idle),
          main: DockAction('NEXT', () => _act(f.next), enabled: idle),
        );
      case _View.rate:
        final nextTitle = _nextBlockTitle(s, _rateBlock(s)?.id);
        return ActionDock(
          caption: _rating == null ? 'Pick 1 to 5 to go on.' : null,
          left: DockAction('REDO TAKE', () => _act(f.redoLast), enabled: idle),
          right: DockAction('BLOCKS', () => setState(() => _hub = true), enabled: idle),
          main: DockAction(
            nextTitle == null ? 'NEXT' : 'NEXT: ${nextTitle.toUpperCase()}',
            () => _rateSubmit(f, s),
            enabled: idle && _rating != null,
          ),
        );
      case _View.done:
        return ActionDock(
          left: DockAction('BLOCKS', () => setState(() => _hub = true), enabled: idle),
          right: DockAction('NEW', () async {
            await f.close();
            if (mounted) setState(() => _hub = false);
          }, enabled: idle),
          main: DockAction('DONE', () async {
            await f.close();
            if (mounted) Navigator.of(context).pop();
          }, enabled: idle),
        );
    }
  }
}

/// A block's hub status: "ease N" when rated, "not rated" when finished and unrated (never "RATE 1/1"), "done/total"
/// while in progress, "·" when untouched.
String blockStatus(RecBlock b) {
  final n = '${b.done}/${b.total}';
  if (b.rating != null) return '$n · ease ${b.rating}';
  if (b.total > 0 && b.done + b.skipped >= b.total) return '$n · not rated';
  if (b.done > 0 || b.skipped > 0) return n;
  return '·';
}

/// "Canti heard: RISE" (the sounds of the take; in a recorder session Canti drops them, so what it would have done is
/// left out), or "Canti heard nothing" / the room's "Saved: 3.5 s of the room".
String heardLine(List<HeardSound> heard, RecTake take) {
  if (take.quiet) return 'Saved: the room, quiet.';
  if (take.bg != null) return 'Saved: ${take.seconds?.round() ?? '?'} s of ${take.bg!.name ?? 'background'}.';
  if (heard.isEmpty) return 'Canti heard nothing.';
  String one(HeardSound h) {
    final label = (h.relabel ?? h.label ?? '?').toUpperCase();
    final did = h.didText;
    return did == null || h.dropped == 'recording' || did.startsWith('ignored: recording') ? label : '$label → $did';
  }

  return 'Canti heard: ${heard.map(one).join(', ')}';
}

/// A huge number with a line beside it: the countdown's "3  far take: get in place", the room's "2  s left".
class _BigLine extends StatelessWidget {
  const _BigLine({required this.number, required this.text, this.numberKey});

  final String number;
  final String text;
  final Key? numberKey;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final ink = CantiTheme.of(context).ink;
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        PixelSnap(child: Text(number, key: numberKey, style: _sized(p, ink, 48))),
        SizedBox(width: p(4)),
        Flexible(child: Padding(padding: EdgeInsets.only(bottom: p(4)), child: PixelSnap(child: Text(text, style: p.big(ink))))),
      ],
    );
  }
}

/// The body face at [artPx] (a multiple of 8, so it stays on the pixel grid).
TextStyle _sized(Px p, Color c, int artPx) => p.body(c).copyWith(fontSize: artPx * p.px * p.text, height: 9 / 8);

/// The cue, as big as the space allows: the body face at 3x, else 2x, else 1x (scrolling if even that is too tall),
/// centred in the take's empty middle.
class _FitText extends StatelessWidget {
  const _FitText(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final ink = CantiTheme.of(context).ink;
    return LayoutBuilder(
      builder: (context, box) {
        TextStyle? fit;
        for (final size in const [24, 16]) {
          final style = _sized(p, ink, size);
          final tp = TextPainter(
            text: TextSpan(text: text, style: style),
            textAlign: TextAlign.center,
            textDirection: TextDirection.ltr,
          )..layout(maxWidth: box.maxWidth);
          final ok = tp.height <= box.maxHeight && !tp.didExceedMaxLines;
          tp.dispose();
          if (ok) {
            fit = style;
            break;
          }
        }
        final label = Text(text, textAlign: TextAlign.center, style: fit ?? p.body(ink, line: 11));
        return Center(
          child: fit != null ? PixelSnap(child: label) : SingleChildScrollView(child: PixelSnap(child: label)),
        );
      },
    );
  }
}

/// The status screen's recorder entry (shown only when the dev gate is on): opens the recorder and quick record.
class RecorderEntryWindow extends StatelessWidget {
  const RecorderEntryWindow({super.key, required this.backend, this.recorder, this.onOpen, this.onQuick});

  final VoxBackend backend;
  final RecorderBackend? recorder;

  /// Overrides for the guarded openers (the status screen guards against stacking); null uses [openRecorder]/[openQuickRec].
  final VoidCallback? onOpen;
  final VoidCallback? onQuick;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    return PixelWindow(
      key: const Key('rec_entry'),
      title: 'Test recorder',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const SignalNote(
            signal: Signal.idle,
            text: 'Record the range suite on the phone, or save the last 12 s after a misfire. Dev builds only.',
          ),
          SizedBox(height: p(3)),
          Row(
            children: [
              Expanded(
                child: FilledButton(
                  key: const Key('rec_open'),
                  onPressed: onOpen ?? () => openRecorder(context, backend, recorder: recorder),
                  child: const Text('RECORDER'),
                ),
              ),
              SizedBox(width: p(3)),
              Expanded(
                child: OutlinedButton(
                  key: const Key('quick_rec'),
                  onPressed: onQuick ?? () => openQuickRec(context, backend, recorder: recorder, snap: true),
                  child: const Text('QUICK REC'),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

// --- the level meter --------------------------------------------------------------------------------------------------

/// The one level meter: a bar history of [barsDb] (dBFS, oldest first, newest on the right; -80..0 dB), with a
/// dotted MIN line and tag at [minDb]. [marks] (0..1 along the history) draw a tick under the bars, [selected] one
/// inverted: quick record's sounds.
class LevelBars extends StatelessWidget {
  const LevelBars({super.key, required this.barsDb, this.minDb, this.height = 30, this.marks = const [], this.selected});

  final List<double> barsDb;
  final double? minDb;

  /// In art px.
  final int height;
  final List<double> marks;
  final int? selected;

  static const floorDb = -80.0;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    final min = minDb;
    return SizedBox(
      height: p(height),
      child: Stack(
        children: [
          Positioned.fill(child: PixelPaint(art: _LevelArt(barsDb, min, marks, selected, t.ink))),
          if (min != null)
            Positioned(
              right: p(3),
              top: p(_LevelArt.yOf(min, height, marks.isNotEmpty) - 10).clamp(0.0, double.infinity),
              child: PixelBox(
                padding: EdgeInsets.symmetric(horizontal: p(2), vertical: p(1)),
                child: PixelSnap(child: Text('MIN', style: p.body(t.ink, line: 7))),
              ),
            ),
        ],
      ),
    );
  }
}

class _LevelArt extends PixelArt {
  const _LevelArt(this.bars, this.minDb, this.marks, this.selected, this.ink);

  final List<double> bars;
  final double? minDb;
  final List<double> marks;
  final int? selected;
  final Color ink;

  /// The y of [db] in a meter [h] art px tall (3 px frame margin; 5 more at the bottom for marks).
  static int yOf(double db, int h, bool withMarks) {
    final inner = h - 6 - (withMarks ? 5 : 0);
    final f = ((db - LevelBars.floorDb) / -LevelBars.floorDb).clamp(0.0, 1.0);
    return 3 + ((1 - f) * (inner - 1)).round();
  }

  @override
  void paint(PixelCanvas c) {
    c.frame(0, 0, c.w, c.h, ink, notch: true);
    final w = c.w - 6, h = c.h;
    if (w <= 0 || h <= 8) return;
    final withMarks = marks.isNotEmpty;
    final base = yOf(LevelBars.floorDb, h, withMarks);

    // the bars, newest on the right: 2 px wide with a 1 px gap when they fit, else one column per slice (its loudest)
    final n = bars.length;
    if (n > 0) {
      if (n * 3 <= w) {
        for (var i = 0; i < n; i++) {
          final x = 3 + w - (n - i) * 3;
          final y = yOf(bars[i], h, withMarks);
          c.rect(x, y, 2, base - y + 1, ink);
        }
      } else {
        for (var x = 0; x < w; x++) {
          final a = x * n ~/ w, b = math.max(a + 1, (x + 1) * n ~/ w);
          var db = LevelBars.floorDb;
          for (var i = a; i < b && i < n; i++) {
            db = math.max(db, bars[i]);
          }
          final y = yOf(db, h, withMarks);
          c.rect(3 + x, y, 1, base - y + 1, ink);
        }
      }
    }

    // the dotted MIN line
    final m = minDb;
    if (m != null) {
      final y = yOf(m, h, withMarks);
      for (var x = 3; x < 3 + w; x += 2) {
        c.rect(x, y, 1, 1, ink);
      }
    }

    // the marks: an up-tick under the bars at each sound, the selected one a filled block
    for (final (i, f) in marks.indexed) {
      final x = 3 + (f.clamp(0.0, 1.0) * (w - 3)).round();
      if (i == selected) {
        c.rect(x - 1, h - 7, 5, 4, ink);
      } else {
        c.rect(x + 1, h - 7, 1, 4, ink);
        c.rect(x, h - 5, 3, 1, ink);
      }
    }
  }

  @override
  bool shouldRepaint(_LevelArt old) =>
      old.bars != bars || old.minDb != minDb || old.marks != marks || old.selected != selected || old.ink != ink;
}
