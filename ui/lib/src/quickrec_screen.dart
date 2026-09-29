import 'package:flutter/material.dart';

import 'backend.dart';
import 'recorder.dart';
import 'recorder_screen.dart';
import 'shape_plot.dart';
import 'theme/canti_theme.dart';
import 'theme/dock.dart';
import 'theme/glyphs.dart';
import 'theme/kit.dart';
import 'theme/pixel.dart';

/// Opens the quick record screen: on the pending snapshot (the badge's QUICK REC already took one), or with [snap] a
/// fresh one of the last ~12 s (the status screen's button).
Future<void> openQuickRec(BuildContext context, VoxBackend backend, {RecorderBackend? recorder, bool snap = false}) =>
    Navigator.of(context).push<void>(MaterialPageRoute(
        builder: (_) => QuickRecScreen(backend: backend, recorder: recorder ?? recorderBackendFor(backend), snap: snap)));

/// The label picker: what the sound actually was. "misfire / other" sends `misfire`.
const quickLabels = ['rise', 'fall', 'dip', 'arch', 'pop', 'pop pop', 'click', 'click click', 'click click click', 'hiss', 'hum', 'misfire'];

/// The quick record screen (SHARED CONTRACT §5): the last ~12 s of mic audio, already in RAM, with the sounds Canti
/// heard in it and what it did; pick a sound, say what it really was, and save. Nothing touches storage until SAVE;
/// DISCARD, back and AGAIN drop the snapshot.
class QuickRecScreen extends StatefulWidget {
  const QuickRecScreen({super.key, required this.backend, this.recorder, this.snap = false});

  final VoxBackend backend;
  final RecorderBackend? recorder;

  /// Take a fresh snapshot instead of using the pending one.
  final bool snap;

  @override
  State<QuickRecScreen> createState() => _QuickRecScreenState();
}

class _QuickRecScreenState extends State<QuickRecScreen> {
  late final RecorderBackend _rec = widget.recorder ?? recorderBackendFor(widget.backend);
  QuickSnapshot? _snap;
  int? _sound;
  String? _label;
  final _note = TextEditingController();
  bool _busy = false;
  String? _error;
  bool _leaving = false;

  @override
  void initState() {
    super.initState();
    _load(fresh: widget.snap);
  }

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  /// The pending snapshot, or a new one; the last sound (the one that just misfired) is picked.
  Future<void> _load({required bool fresh}) async {
    setState(() {
      _busy = true;
      _error = null;
      _label = null;
    });
    try {
      QuickSnapshot? snap;
      if (!fresh) {
        final pending = QuickSnapshot.fromMap(await _rec.qrPending());
        if (pending.id != null) snap = pending;
      }
      snap ??= QuickSnapshot.fromMap(await _rec.qrSnap());
      if (!mounted) return;
      setState(() {
        _snap = snap;
        _sound = snap!.sounds.isEmpty ? null : _lastPitchedOr(snap.sounds);
      });
    } catch (e) {
      if (mounted) setState(() => _error = 'snapshot: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// The most recent sound Canti acted on, else the most recent one.
  static int _lastPitchedOr(List<HeardSound> sounds) {
    for (var i = sounds.length - 1; i >= 0; i--) {
      if (sounds[i].dropped == null && sounds[i].didText != null && sounds[i].didText != 'no action') return i;
    }
    return sounds.length - 1;
  }

  Future<void> _discard() async {
    final id = _snap?.id;
    if (id == null) return;
    try {
      await _rec.qrDiscard(id);
    } catch (_) {
      // gone already (saved, replaced or timed out): nothing to drop
    }
  }

  Future<void> _again() async {
    await _discard();
    await _load(fresh: true);
  }

  Future<void> _save() async {
    final snap = _snap;
    final label = _label;
    if (snap == null || snap.id == null || label == null) return;
    setState(() => _busy = true);
    try {
      final note = _note.text.trim();
      final r = await _rec.qrSave(id: snap.id!, label: label, note: note.isEmpty ? null : note, sound: _sound);
      if (!mounted) return;
      _leaving = true;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Saved · ${r['id'] ?? snap.id}')));
      Navigator.of(context).pop();
    } catch (e) {
      if (mounted) setState(() => _error = 'save: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Back and DISCARD: drop the snapshot (it only ever lived in RAM) and leave.
  Future<void> _leave() async {
    if (_leaving) return;
    _leaving = true;
    await _discard();
    if (mounted) Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final gap = SizedBox(height: p(5));
    final snap = _snap;
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _leave();
      },
      child: Scaffold(
        body: SafeArea(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Padding(
                padding: EdgeInsets.fromLTRB(p(5), p(5), p(5), 0),
                child: ScreenHeader(backKey: const Key('qr_back'), title: 'Quick record', onBack: _leave),
              ),
              Expanded(
                child: SingleChildScrollView(
                  padding: EdgeInsets.all(p(5)),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      if (_error != null) ...[
                        PixelWindow(
                          title: 'Refused',
                          onClose: () => setState(() => _error = null),
                          closeLabel: 'Dismiss',
                          child: SignalNote(signal: Signal.stop, text: _error!, textKey: const Key('qr_error')),
                        ),
                        gap,
                      ],
                      if (snap == null)
                        const SignalNote(signal: Signal.waiting, text: 'Loading...', textKey: Key('qr_loading'))
                      else ...[
                        _clip(snap),
                        gap,
                        _labels(snap),
                      ],
                    ],
                  ),
                ),
              ),
              ActionDock(
                caption: snap != null && _label == null ? 'Pick what it really was, then SAVE.' : null,
                left: DockAction('DISCARD', _leave, enabled: !_busy),
                right: DockAction('AGAIN', _again, enabled: !_busy),
                main: DockAction('SAVE', _save, enabled: !_busy && snap?.id != null && _label != null),
              ),
            ],
          ),
        ),
      ),
    );
  }

  /// The clip: its level with a mark per sound (tap one to pick it), what Canti heard and did, and its shape.
  Widget _clip(QuickSnapshot snap) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    final secs = snap.seconds > 0 ? snap.seconds : 12;
    final marks = [for (final s in snap.sounds) ((s.relMs ?? 0) / 1000 / secs).clamp(0.0, 1.0)];
    final sel = _sound != null && _sound! < snap.sounds.length ? snap.sounds[_sound!] : null;
    return PixelWindow(
      key: const Key('qr_clip'),
      title: 'The last $secs s',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          LayoutBuilder(
            builder: (context, box) => GestureDetector(
              behavior: HitTestBehavior.opaque,
              onTapUp: marks.isEmpty
                  ? null
                  : (d) {
                      final f = d.localPosition.dx / box.maxWidth;
                      var best = 0;
                      for (var i = 1; i < marks.length; i++) {
                        if ((marks[i] - f).abs() < (marks[best] - f).abs()) best = i;
                      }
                      setState(() => _sound = best);
                    },
              child: LevelBars(
                key: const Key('qr_bars'),
                barsDb: snap.barsDb,
                minDb: snap.minDb,
                height: 36,
                marks: marks,
                selected: _sound,
              ),
            ),
          ),
          SizedBox(height: p(1)),
          Row(
            children: [
              PixelSnap(child: Text('−$secs s', style: p.body(t.ink))),
              const Spacer(),
              PixelSnap(child: Text('last $secs s', key: const Key('qr_axis'), style: p.body(t.ink))),
              const Spacer(),
              PixelSnap(child: Text('now', style: p.body(t.ink))),
            ],
          ),
          SizedBox(height: p(3)),
          if (snap.sounds.isEmpty)
            PixelSnap(child: Text('Canti heard no sound in the clip.', key: const Key('qr_heard'), style: p.big(t.ink)))
          else ...[
            for (final (i, s) in snap.sounds.indexed)
              InkWell(
                key: Key('qr_sound_$i'),
                onTap: () => setState(() => _sound = i),
                child: ConstrainedBox(
                  constraints: const BoxConstraints(minHeight: 48),
                  child: Padding(
                    padding: EdgeInsets.symmetric(vertical: p(2)),
                    child: StatRow(
                      icon: i == _sound ? tickGlyph : Icons7.sound,
                      label: s.label ?? '?',
                      value: '${s.didText ?? 'no action'} · ${s.agoS?.toStringAsFixed(1) ?? '?'} s ago',
                    ),
                  ),
                ),
              ),
            if (sel != null) ...[
              SizedBox(height: p(3)),
              PixelSnap(
                child: Text(
                  _heardText(sel),
                  key: const Key('qr_heard'),
                  style: p.big(t.ink),
                ),
              ),
              SizedBox(height: p(3)),
              ShapePlot(
                key: const Key('qr_shape'),
                expected: _expectedFor(_label ?? sel.label ?? 'flat', sel),
                heard: [sel],
                height: 60,
                alignToHeard: true,
              ),
            ],
          ],
          if (snap.lastAction != null && !snap.lastAction!.inClip) ...[
            SizedBox(height: p(3)),
            SignalNote(
              signal: Signal.idle,
              text: 'Canti\'s last action: ${snap.lastAction!.text ?? '?'}, '
                  '${snap.lastAction!.agoS?.toStringAsFixed(0) ?? '?'} s ago (before the clip).',
            ),
          ],
        ],
      ),
    );
  }

  /// `Canti heard DIP → swipe left, 5.5 s ago.` (did_text already names the sound when Canti acted on it).
  static String _heardText(HeardSound s) {
    final label = (s.label ?? '?').toUpperCase();
    final did = s.didText ?? 'no action';
    final what = did.startsWith(label) ? did : '$label → $did';
    return 'Canti heard $what, ${s.agoS?.toStringAsFixed(1) ?? '?'} s ago.';
  }

  /// The shape the picked label wants (relative: a snapshot has no scale), timed like the heard sound.
  static ExpectedShape _expectedFor(String label, HeardSound heard) {
    final seq = switch (label) {
      'pop pop' => const ['pop', 'pop'],
      'click click' => const ['click', 'click'],
      'click click click' => const ['click', 'click', 'click'],
      'hum' => const ['flat'],
      'misfire' => [heard.label ?? 'flat'],
      _ => [label],
    };
    return ExpectedShape(sequence: seq, start: 'none', durS: ((heard.durMs ?? 600) / 1000).clamp(0.2, 3.0));
  }

  Widget _labels(QuickSnapshot snap) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    Widget chip(String l) {
      final on = _label == l;
      return Semantics(
        button: true,
        selected: on,
        excludeSemantics: true,
        label: l == 'misfire' ? 'misfire or other' : l,
        child: InkWell(
          key: Key('qr_label_${l.replaceAll(' ', '_')}'),
          onTap: _busy ? null : () => setState(() => _label = l),
          child: SizedBox(
            height: 48,
            child: PixelBox(
              inverted: on,
              child: Center(
                child: PixelSnap(
                  child: Text((l == 'misfire' ? 'misfire / other' : l).toUpperCase(), style: p.title(on ? t.paper : t.ink)),
                ),
              ),
            ),
          ),
        ),
      );
    }

    final grid = quickLabels.where((l) => l != 'misfire').toList();
    return PixelWindow(
      key: const Key('qr_label'),
      title: 'What was it?',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (var r = 0; r < grid.length; r += 3) ...[
            if (r > 0) SizedBox(height: p(2)),
            Row(
              children: [
                for (var c = r; c < r + 3; c++) ...[
                  if (c > r) SizedBox(width: p(2)),
                  Expanded(child: c < grid.length ? chip(grid[c]) : const SizedBox()),
                ],
              ],
            ),
          ],
          SizedBox(height: p(2)),
          chip('misfire'),
          SizedBox(height: p(4)),
          PixelSnap(child: Text('NOTE (optional)', style: p.title(t.ink))),
          SizedBox(height: p(2)),
          TextField(key: const Key('qr_note'), controller: _note, style: p.body(t.ink), maxLines: 1),
        ],
      ),
    );
  }
}
