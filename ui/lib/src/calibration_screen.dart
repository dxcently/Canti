import 'package:flutter/material.dart';

import 'backend.dart';
import 'calibration.dart';
import 'theme/canti_theme.dart';
import 'theme/glyphs.dart';
import 'theme/kit.dart';
import 'theme/pixel.dart';

/// Opens the voice cursor's setup for [source]; completes with true when a calibration was saved. With [steps] (a
/// profile's `missing_steps`), only those steps are recorded.
Future<bool> openCalibration(BuildContext context, VoxBackend backend, String source, {List<String>? steps}) async {
  final saved = await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => CalibrationScreen(backend: backend, source: source, steps: steps)));
  return saved == true;
}

/// The voice cursor's setup, after the desktop prototype (extractor/joystick.py): an intro, then eight recorded
/// steps (hum, glide, vowels, pops, clicks, whistle, hiss, room; or only a profile's missing ones) with the live
/// readout, then the result with Save, Redo a step and Cancel. A failed step shows the engine's reason with Retry and
/// Skip, and waits. One window, paged (◀ n/10 ▶); the state is [CalibFlow].
class CalibrationScreen extends StatefulWidget {
  const CalibrationScreen({super.key, required this.backend, required this.source, this.flow, this.steps});

  final VoxBackend backend;

  /// The mic being calibrated (`phone`, `usb`, `pico`): each has its own profile.
  final String source;

  /// A flow to drive (tests, the desktop preview); by default the screen makes its own.
  final CalibFlow? flow;

  /// Only these steps (a profile's missing ones); by default all. Ignored with [flow].
  final List<String>? steps;

  /// Each page's window title, by [CalibPage] index.
  static const titles = ['Setup', 'Hum', 'Glide', 'Vowels', 'Pops', 'Clicks', 'Whistle', 'Hiss', 'Room', 'Result'];

  /// What each step asks for, until the service's own prompt arrives.
  static const prompts = {
    'hum': 'Hum a relaxed "mm" for 3 s: the note that comes out without thinking.',
    'glide': 'Glide from your lowest comfortable note to your highest and back, over 5 s.',
    'vowels': 'Hold "ee" (as in see), then "ah", then "oo", 2 s each, at a middle pitch.',
    'pops': 'Pop your lips 3 times, about a second apart.',
    'clicks': 'Click your tongue 3 times, about a second apart',
    'whistle': 'Whistle from your lowest note to your highest and back (5 s)',
    'hiss': "Two short 'tss' hisses, about a second apart",
    'room': 'Stay quiet for 3 s: Canti listens to the room',
  };

  /// What each step is, for the intro's list.
  static const names = {
    'hum': 'your relaxed hum',
    'glide': 'your lowest and highest notes',
    'vowels': 'three vowels',
    'pops': 'your lip pops',
    'clicks': 'tongue clicks',
    'whistle': 'a whistle',
    'hiss': 'a hiss',
    'room': "your room's quiet",
  };

  /// About how long each step takes (s), for the intro.
  static const seconds = {'hum': 4, 'glide': 6, 'vowels': 7, 'pops': 4, 'clicks': 4, 'whistle': 6, 'hiss': 3, 'room': 4};

  /// "about 40 s" for [steps] (rounded up to 5 s).
  static String duration(List<String> steps) {
    final s = steps.fold(0, (a, k) => a + (seconds[k] ?? 4));
    return 'about ${(s + 4) ~/ 5 * 5} s';
  }

  static const popsHint = 'Canti heard fewer than 2 of your 3 pops, so it may miss them. Redo the pops a bit louder '
      'and closer to the mic. Until then, click from Canti\'s badge: tap it and use its menu.';

  @override
  State<CalibrationScreen> createState() => _CalibrationScreenState();
}

class _CalibrationScreenState extends State<CalibrationScreen> {
  late final CalibFlow _flow = widget.flow ?? CalibFlow(backend: widget.backend, source: widget.source, steps: widget.steps);

  @override
  void initState() {
    super.initState();
    _flow.attach();
  }

  @override
  void dispose() {
    _flow.cancel(); // nothing is sent if it was saved, cancelled, or never started
    if (widget.flow == null) _flow.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    await _flow.save();
    if (mounted && _flow.saved) Navigator.of(context).pop(true);
  }

  Future<void> _cancel() async {
    await _flow.cancel();
    if (mounted) Navigator.of(context).pop(false);
  }

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    final gap = SizedBox(height: p(5));
    return PopScope(
      onPopInvokedWithResult: (didPop, _) {
        if (didPop) _flow.cancel();
      },
      child: Scaffold(
        body: SafeArea(
          child: ListenableBuilder(
            listenable: _flow,
            builder: (context, _) {
              final f = _flow;
              return SingleChildScrollView(
                padding: EdgeInsets.all(p(5)),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    ScreenHeader(backKey: const Key('calib_back'), title: 'Voice cursor setup', onBack: _cancel),
                    gap,
                    if (f.error != null) ...[
                      PixelWindow(
                        title: 'Error',
                        onClose: f.dismissError,
                        closeLabel: 'Dismiss error',
                        child: SignalNote(signal: Signal.stop, text: f.error!, textKey: const Key('calib_error')),
                      ),
                      gap,
                    ],
                    PixelWindow(
                      title: CalibrationScreen.titles[f.page.index],
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          PixelSnap(
                            child: Text(
                              '${sourceLabel(widget.source)} · ${_where(f)}',
                              key: const Key('calib_where'),
                              style: p.body(t.ink),
                            ),
                          ),
                          SizedBox(height: p(3)),
                          ..._page(context, f),
                          Center(
                            child: PixelPager(index: f.pageIndex, count: f.pages.length, onChanged: f.goTo),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              );
            },
          ),
        ),
      ),
    );
  }

  static String _where(CalibFlow f) => switch (f.page) {
        CalibPage.intro => CalibrationScreen.duration(f.steps),
        CalibPage.result => 'result',
        final page => 'step ${f.steps.indexOf(page.step!) + 1} of ${f.steps.length}',
      };

  /// "a, b and c".
  static String _and(List<String> xs) =>
      xs.length < 2 ? xs.join() : '${xs.take(xs.length - 1).join(', ')} and ${xs.last}';

  List<Widget> _page(BuildContext context, CalibFlow f) {
    final p = Px.of(context);
    final gap = SizedBox(height: p(4));
    final time = CalibrationScreen.duration(f.steps);
    final names = [for (final s in f.steps) CalibrationScreen.names[s]!];
    switch (f.page) {
      case CalibPage.intro:
        return [
          SignalNote(
            signal: Signal.idle,
            textKey: const Key('calib_intro'),
            text: f.partial
                ? 'Canti\'s cursor has ${f.steps.length} new ${f.steps.length == 1 ? 'step' : 'steps'}: '
                    '${_and(names)}. Your other steps stay as they are. It takes $time.'
                : 'Canti learns your voice for the cursor: ${_and(names)}. It takes $time.',
          ),
          gap,
          _Panel(rows: [
            (Icons7.sound, 'Mic', sourceLabel(widget.source), const Key('calib_source')),
            (Icons7.hourglass, 'Time', time, null),
            (Icons7.cursor, 'Steps', f.steps.join(', '), const Key('calib_steps')),
          ]),
          gap,
          const SignalNote(signal: Signal.idle, text: 'Somewhere quiet, holding the phone the way you use it.'),
          gap,
          _Buttons(children: [
            FilledButton.icon(
              key: const Key('calib_begin'),
              icon: const PixelGlyph(Icons7.play),
              label: const Text('Begin'),
              onPressed: f.busy || f.started ? null : f.begin,
            ),
          ]),
        ];
      case CalibPage.result:
        return _result(context, f);
      default:
        return _step(context, f, f.page.step!);
    }
  }

  List<Widget> _step(BuildContext context, CalibFlow f, String step) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    final gap = SizedBox(height: p(4));
    final s = f.pageStatus;
    final failure = f.pageFailure;
    final done = f.pageDone;
    final skipped = f.skipped.contains(step);
    final live = s?.live ?? const CalibLive();
    final hearing = s != null && !done && failure == null;
    final pitch = hearing && live.voiced ? hzLabel(live.pitchHz) : '-';
    final level = hearing && live.levelDb != null ? '${live.levelDb!.round()} dB' : '-';
    final progress = done ? 1.0 : (s?.progress ?? 0);

    final (Signal, String, Key) state = failure != null
        ? (Signal.stop, failure, const Key('calib_reason'))
        : done
            ? (Signal.idle, skipped ? 'Skipped: the defaults are kept for this step.' : 'Done.', const Key('calib_state'))
            : s == null
                ? (Signal.waiting, 'Starting...', const Key('calib_state'))
                : s.waitingForSteady && step != 'vowels'
                    ? (
                        Signal.waiting,
                        step == 'whistle' ? 'Waiting for a steady whistle...' : 'Waiting for a steady note...',
                        const Key('calib_waiting'),
                      )
                    : (Signal.listening, step == 'room' ? 'Listening to the room...' : 'Listening...', const Key('calib_state'));

    final heard = (s ?? const CalibStatus(active: false)).heard(step);
    final rows = <(Glyph, String, String?, Key?)>[
      if (step == 'vowels')
        (
          Icons7.decider,
          'Vowel',
          hearing && live.vowel != null
              ? '${live.vowel}${live.vowelConf != null ? ' ${(live.vowelConf! * 100).round()}%' : ''}'
              : '-',
          const Key('calib_vowel'),
        ),
      if (heard != null)
        (Icons7.target, 'Heard', '${done && s == null ? '-' : heard.$1}/${heard.$2}', const Key('calib_heard')),
      if (calibPitchSteps.contains(step)) (Icons7.sound, 'Pitch', pitch, const Key('calib_pitch')),
      (Icons7.power, 'Level', level, const Key('calib_level')),
    ];

    final Widget buttons;
    if (failure != null) {
      buttons = _Buttons(children: [
        FilledButton.icon(
          key: const Key('calib_retry'),
          icon: const PixelGlyph(Icons7.refresh),
          label: const Text('Retry'),
          onPressed: f.busy ? null : f.retry,
        ),
        OutlinedButton.icon(
          key: const Key('calib_skip'),
          icon: const PixelGlyph(Marks.right),
          label: const Text('Skip'),
          onPressed: f.busy ? null : f.skip,
        ),
      ]);
    } else if (done) {
      final last = f.nextIsResult;
      buttons = _Buttons(children: [
        FilledButton.icon(
          key: const Key('calib_next'),
          icon: const PixelGlyph(Icons7.play),
          label: Text(last ? 'See result' : 'Next'),
          onPressed: f.busy ? null : f.next,
        ),
        OutlinedButton.icon(
          key: const Key('calib_redo'),
          icon: const PixelGlyph(Icons7.refresh),
          label: const Text('Redo'),
          onPressed: f.busy || f.finished ? null : () => f.redo(step),
        ),
      ]);
    } else {
      buttons = _Buttons(children: [
        OutlinedButton.icon(
          key: const Key('calib_restart'),
          icon: const PixelGlyph(Icons7.refresh),
          label: const Text('Start over'),
          onPressed: f.busy || s == null ? null : () => f.redo(step),
        ),
        // before a failure too, where the service allows it (waiting, nothing heard yet, the room)
        if (f.canSkip)
          OutlinedButton.icon(
            key: const Key('calib_skip'),
            icon: const PixelGlyph(Marks.right),
            label: const Text('Skip'),
            onPressed: f.busy ? null : f.skip,
          ),
      ]);
    }

    return [
      Text(s?.prompt ?? CalibrationScreen.prompts[step]!, key: const Key('calib_prompt'), style: p.body(t.ink, line: 11)),
      if (s?.sub != null) Text(s!.sub!, key: const Key('calib_sub'), style: p.body(t.ink, line: 11)),
      gap,
      SignalNote(signal: state.$1, text: state.$2, textKey: state.$3),
      gap,
      InvertedPanel(
        child: Column(
          children: [
            for (final (icon, label, value, key) in rows) ...[
              StatRow(icon: icon, label: label, value: value, valueKey: key),
              SizedBox(height: p(1)),
            ],
            StatRow(
              icon: Icons7.hourglass,
              label: 'Done',
              trailing: PipMeter(value: (progress * 10).round(), max: 10, label: 'progress'),
            ),
          ],
        ),
      ),
      gap,
      buttons,
    ];
  }

  List<Widget> _result(BuildContext context, CalibFlow f) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    final gap = SizedBox(height: p(4));
    final r = f.result;
    if (r == null) {
      return [
        const SignalNote(signal: Signal.waiting, text: 'Working out your result...', textKey: Key('calib_state')),
        gap,
      ];
    }
    final skipped = f.skipped;
    return [
      _Panel(rows: calibSummaryRows({...r.toMap(), 'skipped': [for (final k in calibSteps) if (skipped.contains(k)) k]})),
      if (r.levelGate != null) ...[
        gap,
        SignalNote(signal: Signal.idle, text: r.levelGate!.sentence, textKey: const Key('calib_gate_note')),
      ],
      if (r.popsWeak && f.steps.contains('pops')) ...[
        gap,
        const SignalNote(signal: Signal.waiting, text: CalibrationScreen.popsHint, textKey: Key('calib_pops_hint')),
      ],
      gap,
      _Buttons(children: [
        FilledButton.icon(
          key: const Key('calib_save'),
          icon: const PixelGlyph(Icons7.play),
          label: const Text('Save'),
          onPressed: f.busy || f.finished ? null : _save,
        ),
        OutlinedButton.icon(
          key: const Key('calib_cancel'),
          icon: const PixelGlyph(Marks.cross),
          label: const Text('Cancel'),
          onPressed: f.busy ? null : _cancel,
        ),
      ]),
      gap,
      PixelSnap(child: Text('REDO A STEP', style: p.title(t.ink))),
      SizedBox(height: p(2)),
      _Buttons(children: [
        for (final step in f.steps)
          OutlinedButton.icon(
            key: Key('calib_redo_$step'),
            icon: const PixelGlyph(Icons7.refresh),
            label: Text(step[0].toUpperCase() + step.substring(1)),
            onPressed: f.busy || f.finished ? null : () => f.redo(step),
          ),
      ]),
      gap,
    ];
  }
}

/// The stat rows of a calibration (a result or a saved profile): home note, range, each vowel, pops, clicks, the
/// whistle range, hiss, the room's floor, the level gate, voicing, the skipped steps and the missing ones. A skipped
/// step's values are null: "skipped"; a missing one's: "not yet".
List<(Glyph, String, String, Key?)> calibSummaryRows(Map<String, Object?> m) {
  final r = CalibResult.fromMap(m)!;
  final skipped = r.skipped.toSet();
  final missing = r.missingSteps.toSet();
  String pct(double? v) => v == null ? '-' : '${(v * 100).round()}%';
  String or(String step, String v) => skipped.contains(step) ? 'skipped' : missing.contains(step) ? 'not yet' : v;
  String hz(double? lo, double? hi) => lo == null || hi == null ? '-' : '${lo.round()}-${hi.round()} Hz';
  String n(int? v, int of) => v == null ? '-' : '$v/$of';
  final gate = r.levelGate;
  List<String> inOrder(Set<String> s) => [for (final k in calibSteps) if (s.contains(k)) k];
  return [
    (Icons7.sound, 'Home', or('hum', hzLabel(r.homeHz)), const Key('calib_home')),
    (Icons7.cursor, 'Range', or('glide', hz(r.rangeLoHz, r.rangeHiHz)), const Key('calib_range')),
    for (final v in const ['ee', 'ah', 'oo']) (Icons7.decider, v, or('vowels', pct(r.vowelAcc[v])), Key('calib_acc_$v')),
    (Icons7.target, 'Pops', or('pops', n(r.popsHeard, 3)), const Key('calib_pops')),
    (Icons7.target, 'Clicks', or('clicks', n(r.clicksHeard, 3)), const Key('calib_clicks')),
    (Icons7.cursor, 'Whistle', or('whistle', hz(r.whistleLoHz, r.whistleHiHz)), const Key('calib_whistle')),
    (Icons7.target, 'Hiss', or('hiss', n(r.hissHeard, 2)), const Key('calib_hiss')),
    (Icons7.power, 'Room', or('room', r.roomFloorDbfs == null ? '-' : '${r.roomFloorDbfs!.round()} dBFS'),
        const Key('calib_room')),
    (Icons7.power, 'Gate', gate == null ? '-' : '${gate.minSnrDb.round()} dB, ${gate.from}', const Key('calib_gate')),
    (Icons7.power, 'Voicing', or('hum', r.voicingThreshold?.toStringAsFixed(2) ?? '-'), const Key('calib_voicing')),
    (Icons7.bang, 'Skipped', skipped.isEmpty ? 'none' : inOrder(skipped).join(', '), const Key('calib_skipped')),
    if (missing.isNotEmpty) (Icons7.bang, 'Missing', inOrder(missing).join(', '), const Key('calib_missing')),
  ];
}

/// Stat rows on an inverted panel.
class _Panel extends StatelessWidget {
  const _Panel({required this.rows});

  final List<(Glyph, String, String, Key?)> rows;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    return InvertedPanel(
      child: Column(
        children: [
          for (final (i, (icon, label, value, key)) in rows.indexed) ...[
            if (i > 0) SizedBox(height: p(1)),
            StatRow(icon: icon, label: label, value: value, valueKey: key),
          ],
        ],
      ),
    );
  }
}

class _Buttons extends StatelessWidget {
  const _Buttons({required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    return Wrap(spacing: p(2), runSpacing: p(2), children: children);
  }
}

/// Stat rows on an inverted panel (for other screens: the settings' saved profile).
class CalibPanel extends StatelessWidget {
  const CalibPanel({super.key, required this.rows});

  final List<(Glyph, String, String, Key?)> rows;

  @override
  Widget build(BuildContext context) => _Panel(rows: rows);
}
