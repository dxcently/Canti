import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show PlatformException;

import 'backend.dart';
import 'calibration.dart';
import 'calibration_screen.dart' show calibPopsHint;
import 'channel_backend.dart' show CalibCommandError;
import 'shape_plot.dart';
import 'theme/canti_theme.dart';
import 'theme/dither_background.dart';
import 'theme/dock.dart';
import 'theme/glyphs.dart';
import 'theme/kit.dart';
import 'theme/pixel.dart';
import 'train.dart';

// The round 7 §9b redesign of the calibration and gesture-training screens: one *hub* (every calibration step and
// every gesture, plus the takes to check) and a shared *step* layout for a calibration step and a training take: the
// header's working ◀ i/n ▶, the instruction sentence in font A, the ShapePlot kept up the whole time (live while the
// sound is made, heard after), the heard-vs-wanted miss view, and ONE ActionDock at the bottom with the same three
// slots on every step. No buttons in the content. Leaving never resets progress: calibration saves each step as it
// finishes (a cancel loses only the in-flight one), training stores each take; coming back re-reads the status.

/// Opens the tests hub (calibration + gesture training) for [source] (the current sound source).
Future<void> openHub(BuildContext context, VoxBackend backend, {TrainBackend? train, String? source}) =>
    Navigator.of(context).push<void>(MaterialPageRoute(
        builder: (_) => HubScreen(backend: backend, source: source ?? 'phone', train: train)));

/// How long a finished step / take shows before the next one starts (Kotlin's AUTO_ADVANCE_MS).
const autoAdvanceDelay = Duration(milliseconds: 1200);

/// The calibration side's state: the latest `calib_status` of [source], and the commands.
class CalibController extends ChangeNotifier {
  CalibController({required this.backend, required this.source});

  final VoxBackend backend;
  final String source;
  CalibStatus? status;

  /// The last command's refusal (the service's `error`), until the next command.
  String? error;
  bool busy = false;
  StreamSubscription<CalibStatus>? _sub;
  bool _disposed = false;

  void attach() {
    _sub ??= backend.calibStatus().listen(_on);
    refresh();
  }

  void _on(CalibStatus s) {
    if (_disposed) return;
    if (s.source != null && s.source != source) return;
    status = s;
    notifyListeners();
  }

  Future<void> refresh() => _run(() async => _on(await backend.calibStatusMap()), clearError: false);

  Future<void> start({bool resume = true}) => _run(() => backend.calibStart(source, resume: resume));
  Future<void> step(String step) => _run(() => backend.calibStep(step));
  Future<void> redo(String step) => _run(() => backend.calibRedo(step));
  Future<void> retry() => _run(backend.calibRetry);
  Future<void> skip() => _run(backend.calibSkip);
  Future<void> save() => _run(backend.calibSave);
  Future<void> cancel() => _run(backend.calibCancel);

  Future<void> _run(Future<void> Function() f, {bool clearError = true}) async {
    if (_disposed) return;
    busy = true;
    if (clearError) error = null;
    notifyListeners();
    try {
      await f();
    } catch (e) {
      if (!_disposed) error = commandMessage(e);
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

/// A refusal in plain words: the service's message (CalibCommandError, a PlatformException's message), else the error.
String commandMessage(Object e) => switch (e) {
      CalibCommandError(:final message) => message,
      PlatformException(:final message, :final code) => message ?? code,
      _ => '$e',
    };

String _cap(String s) => s.isEmpty ? s : '${s[0].toUpperCase()}${s.substring(1)}';

/// Leaves a tests screen: pops its route (never [Navigator.maybePop]: the screens hold system back in a PopScope that
/// calls this, so maybePop would loop). At the root (the desktop preview) there is nothing to go back to.
void closeRoute(BuildContext context) {
  final nav = Navigator.of(context);
  if (nav.canPop()) nav.pop();
}

/// The flat 52-cell plan (gesture, cell id) in TrainPlan order, from the status's cards.
List<(String, String)> planCells(TrainStatus? s) => [
      for (final g in s?.gestures ?? const <TrainGesture>[])
        for (final c in g.cells) (g.name, c.id),
    ];

/// The first undone cell over the whole plan, after [from] (then before it, never [from] itself); or null.
(String, String)? nextUndoneCell(TrainStatus? s, {(String, String)? from}) {
  final plan = planCells(s);
  final done = {
    for (final g in s?.gestures ?? const <TrainGesture>[])
      for (final c in g.cells)
        if (c.done) (g.name, c.id),
  };
  final i = from == null ? -1 : plan.indexOf(from);
  final order = [...plan.skip(i + 1), ...plan.take(math.max(0, i))];
  for (final x in order) {
    if (!done.contains(x)) return x;
  }
  return null;
}

/// The first undone calibration step after [from] (then before it, never [from] itself), by the hub rows; or null.
String? nextUndoneStep(List<CalibStepInfo> rows, {String? from}) {
  final done = {for (final r in rows) if (r.done) r.id};
  final i = from == null ? -1 : calibSteps.indexOf(from);
  for (final s in [...calibSteps.skip(i + 1), ...calibSteps.take(math.max(0, i))]) {
    if (!done.contains(s)) return s;
  }
  return null;
}

/// The one fix for an off banner: resume Canti, or switch to gesture mode. Errors are swallowed (the status shows).
Future<void> fixBlocker(VoxBackend backend, String action) async {
  try {
    if (action == 'gesture_mode') {
      await backend.deviceCommand(mode: 'gesture');
    } else {
      await backend.setPaused(false);
      await backend.deviceCommand(armed: true);
    }
  } catch (_) {}
}

// --- the hub -----------------------------------------------------------------------------------------------------------

/// The hub: `CALIBRATE n/8` (a row per step with its result), `TRAIN GESTURES n/52` (a row per gesture, done/total)
/// and, when `train_status.unconfirmed` is non-empty, the takes to check. Tapping a row opens that step / gesture; the
/// dock's main button runs the first undone one. The off banner (Canti can't hear) sits on top when training is
/// blocked.
class HubScreen extends StatefulWidget {
  const HubScreen({super.key, required this.backend, required this.source, this.train, this.calib, this.flow});

  final VoxBackend backend;
  final String source;
  final TrainBackend? train;

  /// Controllers to drive (tests, the preview); by default the screen makes its own.
  final CalibController? calib;
  final TrainFlow? flow;

  @override
  State<HubScreen> createState() => _HubScreenState();
}

class _HubScreenState extends State<HubScreen> {
  late final TrainBackend _trainBackend = widget.train ?? trainBackendFor(widget.backend);
  late final CalibController _calib = widget.calib ?? CalibController(backend: widget.backend, source: widget.source);
  late final TrainFlow _train = widget.flow ?? TrainFlow(backend: _trainBackend);

  /// The saved profile, for the rows' values (147 Hz, 14 st, ...).
  CalibResult? _profile;

  @override
  void initState() {
    super.initState();
    _calib.attach();
    _train.attach();
    _loadProfile();
  }

  Future<void> _loadProfile() async {
    try {
      final r = await widget.backend.calibGet(widget.source);
      if (mounted) setState(() => _profile = r);
    } catch (_) {}
  }

  @override
  void dispose() {
    if (widget.calib == null) _calib.dispose();
    if (widget.flow == null) _train.dispose();
    super.dispose();
  }

  /// Back from a step / take / review: everything is read again (nothing was reset).
  Future<void> _reload() async {
    if (!mounted) return;
    await Future.wait([_calib.refresh(), _train.refresh(), _loadProfile()]);
  }

  Future<void> _openCalibStep(String step) async {
    await Navigator.of(context).push<void>(MaterialPageRoute(
        builder: (_) => CalibStepScreen(backend: widget.backend, source: widget.source, step: step)));
    await _reload();
  }

  Future<void> _openTrainCell(String gesture, String? cell) async {
    await Navigator.of(context).push<void>(MaterialPageRoute(
        builder: (_) => TrainTakeScreen(backend: widget.backend, train: _trainBackend, gesture: gesture, cell: cell)));
    await _reload();
  }

  Future<void> _openReview(TrainUnconfirmed u) async {
    await Navigator.of(context).push<void>(MaterialPageRoute(
        builder: (_) => ReviewScreen(backend: widget.backend, train: _trainBackend, take: u)));
    await _reload();
  }

  /// RUN THE REST: the first undone calibration step (resumed from the saved progress), else the first undone take.
  Future<void> _runRest() async {
    final step = nextUndoneStep(_calib.status?.hubRows ?? const []);
    if (step != null) {
      // calib_start {resume: true}: a cancelled run picks up where it stopped (the step screen's calib_step joins it)
      if (_calib.status?.active != true && _calib.status?.resume != null) await _calib.start(resume: true);
      if (mounted) await _openCalibStep(step);
      return;
    }
    final cell = nextUndoneCell(_train.status);
    if (cell != null) await _openTrainCell(cell.$1, cell.$2);
  }

  /// The row's value: what the saved profile measured, or `skipped` / `not done`.
  String _calibValue(CalibStepInfo h) {
    if (h.resultWord == 'skipped') return 'skipped';
    if (!h.done) return 'not done';
    final r = _profile;
    String hz(double? v) => v == null ? 'ok' : '${v.round()} Hz';
    return switch (h.id) {
      'hum' => hz(r?.homeHz),
      'glide' => r?.rangeLoHz != null && r?.rangeHiHz != null
          ? '${hzToSt(r!.rangeHiHz!, r.rangeLoHz!).round()} st'
          : 'ok',
      'vowels' => 'ok',
      'pops' => r?.popsHeard == null ? 'ok' : '${r!.popsHeard} of 3',
      'clicks' => r?.clicksHeard == null ? 'ok' : '${r!.clicksHeard} of 3',
      'whistle' => r?.whistleLoHz != null && r?.whistleHiHz != null
          ? '${hzToSt(r!.whistleHiHz!, r.whistleLoHz!).round()} st'
          : 'ok',
      'hiss' => r?.hissHeard == null ? 'ok' : '${r!.hissHeard} of 2',
      'room' => r?.roomFloorDbfs == null ? 'ok' : 'quiet',
      _ => h.resultWord,
    };
  }

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    return ListenableBuilder(
      listenable: Listenable.merge([_calib, _train]),
      builder: (context, _) {
        final cs = _calib.status;
        final ts = _train.status;
        final rows = cs?.hubRows ?? const <CalibStepInfo>[];
        final calibDone = rows.where((h) => h.done).length;
        final resume = cs?.active == true ? null : cs?.resume;
        final unconfirmed = ts?.unconfirmed ?? const <TrainUnconfirmed>[];
        final blocked = ts?.blocked;
        final nextStep = nextUndoneStep(rows);
        final nextCell = nextUndoneCell(ts);
        final undoneSteps = [for (final h in rows) if (!h.done) _cap(h.id)];
        final takesLeft = ts == null ? 0 : ts.total - ts.done;
        final caption = [
          if (undoneSteps.isNotEmpty) undoneSteps.take(2).join(', ') + (undoneSteps.length > 2 ? ', ...' : ''),
          if (takesLeft > 0) '$takesLeft gesture ${takesLeft == 1 ? 'take' : 'takes'}',
        ];
        return StepFrame(
          title: 'Tests',
          backKey: const Key('hub_back'),
          onBack: () => closeRoute(context),
          bodyKey: const Key('hub_body'),
          banner: blocked == null
              ? null
              : OffBanner(
                  blocker: blocked,
                  action: ts?.blockedAction,
                  onFix: () async {
                    await fixBlocker(widget.backend, ts!.blockedAction!);
                    await _reload();
                  },
                ),
          dock: ActionDock(
            caption: caption.isEmpty ? 'Everything is done. Tap a row to redo it.' : 'Next: ${caption.join(', then ')}.',
            right: DockAction('CLOSE', () => closeRoute(context)),
            main: DockAction('RUN THE REST', _runRest,
                enabled: (nextStep != null || nextCell != null) && !(blocked != null && nextStep == null)),
          ),
          children: [
            if (resume != null && resume.step != null) ...[
              SignalNote(
                  signal: Signal.waiting,
                  text: 'Picking up at ${_cap(resume.step!)}: the steps before it are saved.',
                  textKey: const Key('hub_resume')),
              SizedBox(height: p(4)),
            ],
            PixelWindow(
              key: const Key('hub_calib'),
              title: 'Calibrate $calibDone/8',
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  PixelSnap(
                    child: Text('${_cap(sourceLabel(widget.source))}. Tap any step to run it on its own.',
                        style: p.body(t.ink, line: 11)),
                  ),
                  for (final h in rows)
                    HubRow(
                      key: Key('hub_calib_${h.id}'),
                      label: h.id,
                      value: _calibValue(h),
                      done: h.done,
                      onTap: () => _openCalibStep(h.id),
                    ),
                ],
              ),
            ),
            SizedBox(height: p(4)),
            PixelWindow(
              key: const Key('hub_train'),
              title: 'Train gestures ${ts?.done ?? 0}/${ts?.total ?? 52}',
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  for (final g in ts?.gestures ?? const <TrainGesture>[])
                    HubRow(
                      key: Key('hub_train_${g.name}'),
                      label: g.name,
                      value: g.done == 0 ? 'not done' : '${g.done} of ${g.total}',
                      done: g.complete,
                      // a gesture's next undone take; a finished one opens its first take (a redo)
                      onTap: () => _openTrainCell(
                          g.name,
                          g.cells.where((c) => !c.done).firstOrNull?.id ?? g.cells.firstOrNull?.id),
                    ),
                ],
              ),
            ),
            if (unconfirmed.isNotEmpty) ...[
              SizedBox(height: p(4)),
              PixelWindow(
                key: const Key('hub_review'),
                title: '${unconfirmed.length} ${unconfirmed.length == 1 ? 'take' : 'takes'} to check',
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    for (final u in unconfirmed)
                      HubRow(
                        key: Key('hub_review_${u.id}'),
                        label: u.gesture,
                        value: 'heard ${u.heard ?? '?'}',
                        done: false,
                        onTap: () => _openReview(u),
                      ),
                  ],
                ),
              ),
            ],
          ],
        );
      },
    );
  }
}

const _todo = Glyph(['.']);

/// A hub row: a box (ticked when done), the name, a dotted leader to the value, and ▶. The whole row is the tap target.
class HubRow extends StatelessWidget {
  const HubRow({super.key, required this.label, required this.value, required this.done, required this.onTap});

  final String label;
  final String value;
  final bool done;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    return InkWell(
      onTap: onTap,
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 48),
        child: Padding(
          padding: EdgeInsets.symmetric(vertical: p(3)),
          child: Row(
            children: [
              Expanded(child: StatRow(icon: done ? tickGlyph : _todo, label: label, value: value)),
              SizedBox(width: p(2)),
              PixelGlyph(Marks.right, color: CantiTheme.of(context).ink),
            ],
          ),
        ),
      ),
    );
  }
}

// --- the shared frame --------------------------------------------------------------------------------------------------

/// The layout every tests screen shares (and the recorder's): the header (back + title, and on a step the working,
/// non-wrapping ◀ i/n ▶), an optional top banner, the scrolling content, and the dock pinned at the bottom. System
/// back does what the header's back does.
class StepFrame extends StatelessWidget {
  const StepFrame({
    super.key,
    required this.title,
    required this.onBack,
    required this.bodyKey,
    required this.children,
    required this.dock,
    this.backKey,
    this.pager,
    this.banner,
    this.scroll = true,
  });

  final String title;
  final VoidCallback onBack;
  final Key? backKey;

  /// The header's pager, or null (the hub).
  final StepPager? pager;
  final Widget? banner;
  final Key bodyKey;
  final List<Widget> children;
  final ActionDock dock;

  /// Whether the body scrolls (the hub's long list). The step / take / review screens pass false so their plot can
  /// fill the space between the text and the dock instead of leaving the lower half empty.
  final bool scroll;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final g = pager;
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) onBack();
      },
      child: Scaffold(
        body: SafeArea(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Padding(
                padding: EdgeInsets.fromLTRB(p(5), p(5), p(5), 0),
                child: Row(
                  children: [
                    Expanded(child: ScreenHeader(backKey: backKey, title: title, onBack: onBack)),
                    if (g != null) ...[
                      SizedBox(width: p(2)),
                      PixelPager(
                        key: const Key('step_pager'),
                        index: g.index,
                        count: g.count,
                        wrap: false,
                        canPrev: g.canPrev,
                        canNext: g.canNext,
                        onChanged: (i) => i > g.index ? g.onNext() : g.onPrev(),
                      ),
                    ],
                  ],
                ),
              ),
              if (banner != null) Padding(padding: EdgeInsets.fromLTRB(p(5), p(4), p(5), 0), child: banner),
              Expanded(
                child: scroll
                    ? SingleChildScrollView(
                        padding: EdgeInsets.all(p(5)),
                        child: Column(key: bodyKey, crossAxisAlignment: CrossAxisAlignment.stretch, children: children),
                      )
                    : Padding(
                        padding: EdgeInsets.all(p(5)),
                        child: Column(key: bodyKey, crossAxisAlignment: CrossAxisAlignment.stretch, children: children),
                      ),
              ),
              dock,
            ],
          ),
        ),
      ),
    );
  }
}

/// The header's ◀ i/n ▶: [index] is 0-based; the arrows move (never wrap) and are off where there is nothing.
class StepPager {
  const StepPager({
    required this.index,
    required this.count,
    required this.canPrev,
    required this.canNext,
    required this.onPrev,
    required this.onNext,
  });

  final int index;
  final int count;
  final bool canPrev;
  final bool canNext;
  final VoidCallback onPrev;
  final VoidCallback onNext;
}

// --- the sentence and the off banner -----------------------------------------------------------------------------------

/// An instruction or next-step sentence in font A (Departure Mono, [Px.sentence]); words in capitals (SLOW, HIGH,
/// RISE) are the key words and show inverted.
class Sentence extends StatelessWidget {
  const Sentence(this.text, {super.key, this.color});

  final String text;

  /// The ink (default: the theme's; paper inside an inverted panel).
  final Color? color;

  static final _key = RegExp(r"^[A-Z][A-Z0-9']+[.,:;!?]*$");

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    final ink = color ?? t.ink;
    final bg = ink == t.ink ? t.paper : t.ink;
    final style = p.sentence(ink);
    final spans = <InlineSpan>[];
    for (final m in RegExp(r'\S+|\s+').allMatches(text)) {
      final w = m[0]!;
      final core = w.replaceAll(RegExp(r'[.,:;!?]+$'), '');
      if (_key.hasMatch(w) && core.length > 1) {
        spans.add(TextSpan(text: core, style: style.copyWith(color: bg, background: Paint()..color = ink)));
        if (core.length < w.length) spans.add(TextSpan(text: w.substring(core.length)));
      } else {
        spans.add(TextSpan(text: w));
      }
    }
    return Text.rich(TextSpan(style: style, children: spans));
  }
}

/// The top banner when Canti can't hear (paused, cursor mode, the mic off...): the blocker in plain words and its one
/// fix. The caller disables the dock's main button with the blocker as caption.
class OffBanner extends StatelessWidget {
  const OffBanner({super.key, required this.blocker, required this.action, required this.onFix});

  final String blocker;

  /// The one fix (`resume` | `gesture_mode`), or null (none the app can do).
  final String? action;
  final VoidCallback onFix;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    return InvertedPanel(
      key: const Key('off_banner'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(children: [
            const SignalLamp(Signal.stop),
            SizedBox(width: p(4)),
            Expanded(child: PixelSnap(child: Text("CANTI CAN'T HEAR", style: p.title(t.paper)))),
          ]),
          SizedBox(height: p(3)),
          Text(blocker, key: const Key('off_banner_text'), style: p.body(t.paper, line: 11)),
          if (action != null) ...[
            SizedBox(height: p(3)),
            Semantics(
              button: true,
              child: InkWell(
                key: const Key('off_banner_fix'),
                onTap: onFix,
                child: ConstrainedBox(
                  constraints: const BoxConstraints(minHeight: 48),
                  child: Container(
                    alignment: Alignment.center,
                    color: t.paper,
                    child: PixelSnap(
                        child: Text(action == 'gesture_mode' ? 'GESTURE MODE' : 'TURN ON', style: p.title(t.ink))),
                  ),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

// --- the heard-vs-wanted miss view -------------------------------------------------------------------------------------

/// The miss view: WANTED | HEARD mini plots, a table of the checks (what was heard, what was wanted, ✓ ~ ✗ ·), ONE
/// next-step sentence, and a "keep it anyway" text link only when the take can be kept. It states what was heard and
/// what was wanted; it never guesses what the user did.
class MissView extends StatelessWidget {
  const MissView({
    super.key,
    required this.expected,
    required this.scale,
    required this.heard,
    required this.checks,
    required this.sentence,
    required this.canKeep,
    required this.onKeep,
  });

  final ExpectedShape expected;
  final PitchScale? scale;
  final HeardSound heard;
  final List<ShapeCheck> checks;
  final String sentence;
  final bool canKeep;
  final VoidCallback onKeep;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    Widget mini(String title, List<HeardSound> h) => Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              PixelSnap(child: Text(title, style: p.title(t.ink))),
              SizedBox(height: p(2)),
              ShapePlot(expected: expected, scale: scale, heard: h, height: 48, showLegend: false),
            ],
          ),
        );
    TextStyle cell(Color c) => p.body(c, line: 11);
    return Column(
      key: const Key('miss_view'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          mini('WANTED', const []),
          SizedBox(width: p(4)),
          mini('HEARD', [heard]),
        ]),
        SizedBox(height: p(4)),
        InvertedPanel(
          key: const Key('miss_table'),
          child: Table(
            columnWidths: const {0: IntrinsicColumnWidth(), 1: IntrinsicColumnWidth(), 2: FlexColumnWidth(), 3: FlexColumnWidth()},
            defaultVerticalAlignment: TableCellVerticalAlignment.middle,
            children: [
              TableRow(children: [
                const SizedBox(),
                const SizedBox(),
                PixelSnap(child: Text('HEARD', style: p.title(t.paper))),
                PixelSnap(child: Text('WANTED', style: p.title(t.paper))),
              ]),
              for (final c in checks)
                TableRow(children: [
                  Padding(
                    key: Key('miss_row_${c.id}'),
                    padding: EdgeInsets.symmetric(vertical: p(2)),
                    child: PixelSnap(child: Text(c.label, style: p.title(t.paper))),
                  ),
                  Padding(padding: EdgeInsets.symmetric(horizontal: p(3)), child: _mark(p, c.state, t.paper)),
                  PixelSnap(child: Text(heardText(c), style: cell(t.paper))),
                  PixelSnap(child: Text(wantText(c, expected), style: cell(t.paper))),
                ]),
            ],
          ),
        ),
        SizedBox(height: p(4)),
        Sentence(sentence, key: const Key('miss_sentence')),
        if (canKeep) ...[
          SizedBox(height: p(3)),
          Align(
            alignment: Alignment.centerLeft,
            child: InkWell(
              key: const Key('miss_keep'),
              onTap: onKeep,
              child: ConstrainedBox(
                constraints: const BoxConstraints(minHeight: 48),
                child: Align(
                  widthFactor: 1,
                  child: Text('That was my ${expected.sequence.join(' ')}: keep it anyway',
                      style: p.body(t.ink, line: 11).copyWith(decoration: TextDecoration.underline)),
                ),
              ),
            ),
          ),
        ],
      ],
    );
  }

  static Widget _mark(Px p, CheckState s, Color c) => switch (s) {
        CheckState.ok => Align(alignment: Alignment.centerLeft, child: PixelGlyph(tickGlyph, color: c)),
        CheckState.miss => Align(alignment: Alignment.centerLeft, child: PixelGlyph(Marks.cross, color: c)),
        CheckState.near => PixelSnap(child: Text('~', style: p.title(c))),
        CheckState.pending => PixelSnap(child: Text('·', style: p.title(c))),
      };
}

double? _num(String? s) => s == null ? null : double.tryParse(s);
String _st(double v) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(1)} st';

/// A check's heard value in words (the service sends PITCH as st from HOME, SHAPE as st, LENGTH as ms, SOUND as Hz).
String heardText(ShapeCheck c) {
  if (c.state == CheckState.pending) return c.id.toUpperCase() == 'PITCH' ? 'no scale' : '-';
  final v = c.value, n = _num(v);
  return switch (c.id.toUpperCase()) {
    'PITCH' => n == null ? (v ?? '-') : '${_st(n)} HOME',
    'SHAPE' => n == null ? (v ?? '-') : _st(n),
    'LENGTH' => n == null ? (v ?? '-') : '${(n / 1000).toStringAsFixed(1)} s',
    'SOUND' => n == null ? (v ?? 'no pitch') : '${n < 600 ? 'hum' : 'whistle'} ${n.round()} Hz',
    'LOUD' => n == null ? (v ?? 'ok') : '${n.round()} dB',
    _ => v ?? '-',
  };
}

/// A check's wanted value in words.
String wantText(ShapeCheck c, ExpectedShape e) {
  final w = c.want;
  return switch (c.id.toUpperCase()) {
    'PITCH' => '${(w ?? e.start).toLowerCase()} start',
    'SHAPE' => switch (w ?? e.sequence.firstOrNull) {
        'rise' => 'rise 0.7+ st',
        'fall' => 'fall 0.7+ st',
        'arch' => 'arch 0.7+ st',
        'dip' => 'dip 0.7+ st',
        'flat' => 'flat, 2 st at most',
        final x => x ?? '-',
      },
    'LENGTH' => switch (w) {
        'quick' || 'short' => 'under 1 s',
        'slow' || 'long' => '0.8 s or more',
        _ => '0.2 to 2.5 s',
      },
    'SOUND' => w ?? '-',
    'LOUD' => _num(w) == null ? 'over the gate' : '${_num(w)!.round()} dB',
    _ => w ?? '-',
  };
}

/// The ONE next-step sentence for a missed take: from the first missed check, else the failure's code. It says what
/// to do next against what was wanted; it never guesses what went wrong.
String nextStepSentence({required List<ShapeCheck> checks, required ExpectedShape expected, List<String> reasons = const []}) {
  final g = expected.sequence.join(' ');
  final miss = checks.where((c) => c.state == CheckState.miss).firstOrNull;
  switch (miss?.id.toUpperCase()) {
    case 'PITCH':
      return switch (miss!.want ?? expected.start) {
        'low' => 'Next: start LOW, near the bottom of your range.',
        'high' => 'Next: start HIGH, near the top of your range.',
        _ => 'Next: start at your HOME note.',
      };
    case 'SHAPE':
      return switch (g) {
        'rise' => 'Next: slide UP from where you start.',
        'fall' => 'Next: slide DOWN from where you start.',
        'arch' => 'Next: go UP, then back DOWN.',
        'dip' => 'Next: go DOWN, then back UP.',
        'flat' => 'Next: hold ONE steady note.',
        _ => 'Next: make one ${g.toUpperCase()}.',
      };
    case 'LENGTH':
      return switch (miss!.want) {
        'quick' || 'short' => 'Next: make it QUICK, under a second.',
        'slow' || 'long' => 'Next: make it SLOW, about 1.5 s.',
        _ => 'Next: make it last about a second.',
      };
    case 'SOUND':
      return switch (miss!.want) {
        'whistle' => 'Next: WHISTLE it.',
        'unpitched' => 'Next: no voice, just the ${g.toUpperCase()}.',
        _ => 'Next: HUM it, lips closed.',
      };
    case 'LOUD':
      return 'Next: a little LOUDER.';
    case 'COUNT':
      return 'Next: make ONE unbroken sound.';
  }
  if (reasons.contains('count')) return 'Next: make ONE unbroken sound.';
  return 'Next: make one ${g.toUpperCase()}.';
}

/// The live trace as drawn: from the first voiced tick, so the "you" line starts where the aim starts.
List<double?> liveFromVoice(List<double?> hz) {
  final i = hz.indexWhere((x) => x != null);
  return i < 0 ? const [] : hz.sublist(i);
}

// --- a calibration step ------------------------------------------------------------------------------------------------

/// A calibration step: the sentence, the ShapePlot (hum, glide, whistle: live trace + live checks) or the live readout
/// (the steps without a shape), and the dock. It follows the service's current step (the arrows, a skip, the next step
/// after a pass all move it). A finished step moves on to the next undone one after [autoAdvanceDelay].
class CalibStepScreen extends StatefulWidget {
  const CalibStepScreen({super.key, required this.backend, required this.source, required this.step, this.controller});

  final VoxBackend backend;
  final String source;

  /// The step to open (an undone one records at once, as calib_step does; a done one opens idle, unrecorded).
  final String step;
  final CalibController? controller;

  @override
  State<CalibStepScreen> createState() => _CalibStepScreenState();
}

class _CalibStepScreenState extends State<CalibStepScreen> {
  late final CalibController _calib =
      widget.controller ?? CalibController(backend: widget.backend, source: widget.source);
  late String _step = widget.step;
  Timer? _advance;
  bool _left = false;
  BackdropMood? _mood;

  @override
  void initState() {
    super.initState();
    _calib.addListener(_onStatus);
    _calib.attach();
    _open();
  }

  /// Opens the step: one that is already done opens idle (its saved result, REDO/START to record again); an undone one
  /// records it at once, as calib_step does. Opening a done step never records, so its save is untouched.
  Future<void> _open() async {
    await _calib.refresh();
    if (!mounted) return;
    final done = _calib.status?.hubRows.any((r) => r.id == widget.step && r.done) ?? false;
    if (!done) await _calib.step(widget.step);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _mood = BackdropMood.maybeOf(context);
  }

  @override
  void dispose() {
    _advance?.cancel();
    _calib.removeListener(_onStatus);
    _mood?.listen(false);
    // system back or a route pop without the dock: end the run (finished steps are already saved)
    if (!_left && _calib.status?.active == true) widget.backend.calibCancel().catchError((_) {});
    if (widget.controller == null) _calib.dispose();
    super.dispose();
  }

  List<CalibStepInfo> get _rows => _calib.status?.hubRows ?? const [];

  void _onStatus() {
    final s = _calib.status;
    if (s == null) return;
    if (s.active && s.step != null && s.step != _step) setState(() => _step = s.step!);
    _mood?.listen(s.active && (s.state == 'recording' || s.state == 'waiting'), levelDb: s.live.levelDb);
    // a step that just finished moves on to the next undone one, unless a button came first
    if (s.active && s.step == _step && s.stepDone && _advance == null && !_left) {
      final next = nextUndoneStep(_rows, from: _step);
      if (next != null) {
        _advance = Timer(autoAdvanceDelay, () {
          _advance = null;
          if (mounted && !_left) _calib.step(next);
        });
      }
    }
  }

  /// Every button goes through here: a pending auto-advance is dropped first.
  void _act(Future<void> Function() f) {
    _advance?.cancel();
    _advance = null;
    f();
  }

  /// Back / STEPS: to the hub. The run ends; every finished step is already saved (a complete one is saved as such).
  Future<void> _leave() async {
    if (_left) return;
    _left = true;
    _advance?.cancel();
    final s = _calib.status;
    if (s?.active == true) {
      if (_rows.isNotEmpty && _rows.every((r) => r.done) && !(s!.state == 'waiting' || s.state == 'recording')) {
        await _calib.save();
      } else {
        await _calib.cancel();
      }
    }
    if (mounted) closeRoute(context);
  }

  /// The ◀ ▶ arrows move over the steps: an undone step records it (continuing the run, as START does); a done step
  /// just shows its saved result idle — navigating never re-records a save (only REDO / START do).
  void _goto(int i) {
    final target = calibSteps[i];
    if (_rows.any((r) => r.id == target && r.done)) {
      _act(() async {
        if (_calib.status?.active == true) await _calib.cancel();
        if (mounted) setState(() => _step = target);
      });
    } else {
      _act(() => _calib.step(target));
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    return ListenableBuilder(
      listenable: _calib,
      builder: (context, _) {
        final s = _calib.status;
        final step = _step;
        final i = calibSteps.indexOf(step);
        final here = s != null && s.active && s.step == step;
        final state = here ? s.state : null;
        final inFlight = state == 'waiting' || state == 'recording';
        final failed = state == 'failed';
        final finished = here && (s.stepDone || state == 'done');
        final rowDone = _rows.any((r) => r.id == step && r.done);
        final next = nextUndoneStep(_rows, from: step);
        final busy = _calib.busy;
        final err = _calib.error;
        // the mic off / Canti paused refusal is the off banner; any other refusal a plain note
        final off = err != null && (err.contains('mic is off') || err.contains('resume Canti'));
        final expect = (here ? s.expect : null) ?? _calibExpect[step];
        final prompt = (here ? s.prompt : null) ?? _calibPrompts[step] ?? '';

        final DockAction main;
        if (off) {
          main = DockAction('START', () {}, enabled: false);
        } else if (failed) {
          main = DockAction('TRY AGAIN', () => _act(_calib.retry), enabled: !busy);
        } else if (inFlight) {
          main = DockAction('STOP', () => _act(_calib.cancel), enabled: !busy);
        } else if (finished) {
          main = next == null
              ? DockAction('DONE', _leave, enabled: !busy)
              : DockAction('NEXT STEP', () => _act(() => _calib.step(next)), enabled: !busy);
        } else if (rowDone) {
          // a done step opened idle: view the saved result; REDO re-records it, NEXT STEP continues the run
          main = next == null
              ? DockAction('DONE', _leave, enabled: !busy)
              : DockAction('NEXT STEP', () => _act(() => _calib.step(next)), enabled: !busy);
        } else {
          main = DockAction('START', () => _act(() => _calib.step(step)), enabled: !busy);
        }
        final DockAction left;
        if (inFlight) {
          left = DockAction('RESTART', () => _act(() => _calib.redo(step)), enabled: !busy);
        } else if (rowDone && !failed) {
          left = DockAction('REDO', () => _act(() => _calib.redo(step)), enabled: !busy && !off);
        } else {
          left = DockAction('SKIP', () => _act(_calib.skip), enabled: !busy && here && (failed || state == 'waiting'));
        }

        final window = PixelWindow(
          key: Key('calib_step_$step'),
          title: 'Step ${i + 1} of 8 · ${_cap(step)}',
          expand: expect != null,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Sentence(prompt, key: const Key('step_sentence')),
              SizedBox(height: p(4)),
              if (expect != null)
                Expanded(
                  child: ShapePlot(
                    expected: expect,
                    scale: here ? s.scale : null,
                    liveHz: here ? liveFromVoice(s.live.traceHz) : const [],
                    checks: here && (inFlight || finished || failed) ? s.live.checks : const [],
                    height: 84,
                    grow: true,
                  ),
                )
              else
                _CalibReadout(status: here ? s : null, step: step),
              SizedBox(height: p(4)),
              if (err != null && !off)
                SignalNote(signal: Signal.stop, text: err, textKey: const Key('calib_error'))
              else if (failed)
                SignalNote(
                    signal: Signal.stop, text: s!.reason ?? 'This step did not work.', textKey: const Key('calib_reason'))
              else if (finished)
                SignalNote(
                    signal: Signal.idle,
                    text: next == null ? 'Saved. Every step is done.' : 'Saved. Next: ${_cap(next)}.',
                    textKey: const Key('calib_state'))
              else if (inFlight)
                SignalNote(
                    signal: Signal.listening,
                    text: state == 'waiting' ? (s!.sub ?? 'Waiting for a steady sound.') : 'Listening. Keep going.',
                    textKey: const Key('calib_state'))
              else if (s?.error != null && !off)
                SignalNote(
                    signal: Signal.waiting,
                    text: '${s!.error} The steps before it are saved: START picks up here.',
                    textKey: const Key('calib_state'))
              else
                SignalNote(
                    signal: Signal.idle,
                    text: rowDone ? 'Saved. REDO records it again.' : 'Tap START, then make the sound.',
                    textKey: const Key('calib_state')),
              if (finished && step == 'pops' && s.popsN < 2) ...[
                SizedBox(height: p(3)),
                const SignalNote(signal: Signal.waiting, text: calibPopsHint, textKey: Key('calib_pops_hint')),
              ],
            ],
          ),
        );
        return StepFrame(
          title: 'Calibrate',
          backKey: const Key('step_back'),
          onBack: _leave,
          bodyKey: const Key('calib_step_body'),
          scroll: expect == null,
          pager: StepPager(
            index: i,
            count: calibSteps.length,
            canPrev: i > 0 && !busy,
            canNext: i < calibSteps.length - 1 && !busy,
            onPrev: () => _goto(i - 1),
            onNext: () => _goto(i + 1),
          ),
          banner: off
              ? OffBanner(
                  blocker: err,
                  action: 'resume',
                  onFix: () async {
                    await fixBlocker(widget.backend, 'resume');
                    if (mounted) _act(() => _calib.step(step));
                  })
              : null,
          dock: ActionDock(
            caption: off ? "Canti can't hear: turn it on first." : null,
            left: left,
            right: DockAction('STEPS', _leave),
            main: main,
          ),
          children: [expect != null ? Expanded(child: window) : window],
        );
      },
    );
  }
}

/// Each step's prompt and shape until the service's own arrive (and while no run is open).
const _calibPrompts = {
  'hum': "Hum 'mm' relaxed for 3 s: the note that comes out without thinking",
  'glide': 'Glide from your lowest comfortable note to your highest and back (5 s)',
  'vowels': "Hold 'ee', then 'ah', then 'oo', 2 s each at a middle pitch",
  'pops': 'Pop your lips 3 times, about a second apart',
  'clicks': 'Click your tongue 3 times, about a second apart',
  'whistle': 'Whistle from your lowest note to your highest and back (5 s)',
  'hiss': "Two short 'tss' hisses, about a second apart",
  'room': 'Stay quiet for 3 s: Canti listens to the room',
};

/// As JoyCalibration.expectFor: hum flat at home, glide and whistle an ARCH from low (lowest, highest and back).
const _calibExpect = {
  'hum': ExpectedShape(sequence: ['flat'], start: 'home', durS: 3),
  'glide': ExpectedShape(sequence: ['arch'], start: 'low', durS: 5),
  'whistle': ExpectedShape(sequence: ['arch'], start: 'low', durS: 5),
};

/// The live readout for a step without a shape (vowels, pops, clicks, hiss, room), in the plot's slot.
class _CalibReadout extends StatelessWidget {
  const _CalibReadout({required this.status, required this.step});

  final CalibStatus? status;
  final String step;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    final live = status?.live ?? const CalibLive();
    final heard = status?.heard(step);
    final rows = <(String, String)>[
      if (step == 'vowels') ('Vowel', live.vowel ?? '-'),
      if (heard != null) ('Heard', '${heard.$1} of ${heard.$2}'),
      if (calibPitchSteps.contains(step)) ('Pitch', hzLabel(live.pitchHz)),
      ('Level', live.levelDb == null ? '-' : '${live.levelDb!.round()} dB'),
    ];
    return InvertedPanel(
      key: const Key('calib_readout'),
      child: Column(
        children: [
          for (final (i, (label, value)) in rows.indexed) ...[
            if (i > 0) SizedBox(height: p(2)),
            Row(children: [
              SizedBox(width: p(52), child: PixelSnap(child: Text(label.toUpperCase(), style: p.title(t.paper)))),
              Expanded(child: Text(value, style: p.sentence(t.paper))),
            ]),
          ],
        ],
      ),
    );
  }
}

// --- a training take ---------------------------------------------------------------------------------------------------

/// A training take: the sentence, the ShapePlot (live while recording, heard + result.checks after), the heard-vs-
/// wanted miss view, and the dock. A pass is stored and the service starts the next undone take 1.2 s later (this
/// screen follows it); at the end of a gesture the screen moves on to the next gesture's first undone take.
class TrainTakeScreen extends StatefulWidget {
  const TrainTakeScreen(
      {super.key, required this.backend, required this.train, required this.gesture, this.cell, this.flow});

  final VoxBackend backend;
  final TrainBackend train;
  final String gesture;

  /// The take to open (null: the gesture's first undone one).
  final String? cell;
  final TrainFlow? flow;

  @override
  State<TrainTakeScreen> createState() => _TrainTakeScreenState();
}

class _TrainTakeScreenState extends State<TrainTakeScreen> {
  late final TrainFlow _flow = widget.flow ?? TrainFlow(backend: widget.train);
  late String _g = widget.gesture;
  String? _c;
  Timer? _advance;
  bool _left = false;
  BackdropMood? _mood;

  @override
  void initState() {
    super.initState();
    _c = widget.cell;
    _flow.addListener(_onStatus);
    _flow.attach();
    _open();
  }

  /// Opens the take (train_goto: with no round open it opens one; refused while blocked: the banner shows why).
  Future<void> _open() async {
    await _flow.refresh();
    if (!mounted) return;
    final c = _c ?? _flow.status?.gesture(_g)?.cells.where((x) => !x.done).firstOrNull?.id;
    if (c == null) return;
    setState(() => _c = c);
    await _flow.goto(_g, c);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _mood = BackdropMood.maybeOf(context);
  }

  @override
  void dispose() {
    _advance?.cancel();
    _flow.removeListener(_onStatus);
    _mood?.listen(false);
    if (!_left) _flow.close(); // system back: end the round (stored takes stay)
    if (widget.flow == null) _flow.dispose();
    super.dispose();
  }

  void _onStatus() {
    final s = _flow.session;
    if (s != null && s.cell != null && (s.gesture != _g || s.cell != _c)) {
      setState(() {
        _g = s.gesture;
        _c = s.cell;
      });
    }
    _mood?.listen(s?.state == 'recording', levelDb: s?.live.levelDb);
    // the gesture's round is done: go on to the next undone take of the plan (the service moves within a gesture)
    if (s != null && s.state == 'done' && _advance == null && !_left) {
      final next = nextUndoneCell(_flow.status, from: (_g, _c ?? ''));
      if (next != null) {
        _advance = Timer(autoAdvanceDelay, () {
          _advance = null;
          if (mounted && !_left) _go(next.$1, next.$2, record: true);
        });
      }
    }
  }

  /// Every button goes through here: a pending move is dropped first.
  void _act(Future<void> Function() f) {
    _advance?.cancel();
    _advance = null;
    f();
  }

  Future<void> _go(String g, String c, {bool record = false}) async {
    setState(() {
      _g = g;
      _c = c;
    });
    await _flow.goto(g, c);
    if (record && _flow.error == null && _flow.session?.state == 'ready') await _flow.record();
  }

  Future<void> _leave() async {
    if (_left) return;
    _left = true;
    _advance?.cancel();
    await _flow.close();
    if (mounted) closeRoute(context);
  }

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    return ListenableBuilder(
      listenable: _flow,
      builder: (context, _) {
        final st = _flow.status;
        final s = _flow.session;
        final blocked = st?.blocked;
        final g = _g, c = _c;
        final gesture = st?.gesture(g);
        final cellInfo = gesture?.cells.where((x) => x.id == c).firstOrNull;
        final plan = planCells(st);
        final at = c == null ? -1 : plan.indexOf((g, c));
        final state = s?.state;
        final recording = state == 'recording';
        final passed = state == 'passed';
        final failed = state == 'failed' && !(s?.reasons.contains('blocked') ?? false);
        final roundDone = state == 'done';
        final cellDone = cellInfo?.done ?? false;
        final heard = _heardSound(s?.heard);
        final expect = s?.expect ?? _expectOf(g, cellInfo);
        final busy = _flow.busy;
        final nextCell = nextUndoneCell(st, from: (g, c ?? ''));
        final gi = gesture == null || cellInfo == null ? 0 : gesture.cells.indexOf(cellInfo) + 1;
        final gn = gesture?.cells.length ?? 0;

        final DockAction main;
        if (blocked != null) {
          main = DockAction('START', () {}, enabled: false);
        } else if (failed) {
          main = DockAction('TRY AGAIN', () => _act(_flow.retry), enabled: !busy);
        } else if (recording) {
          // STOP drops the in-flight take (train_goto to the same take): it waits, ready
          main = DockAction('STOP', () => _act(() => _go(g, c!)), enabled: !busy && c != null);
        } else if (passed) {
          main = DockAction('NEXT TAKE', () => _act(_flow.next), enabled: !busy);
        } else if (roundDone) {
          main = nextCell == null
              ? DockAction('DONE', _leave)
              : DockAction('NEXT TAKE', () => _act(() => _go(nextCell.$1, nextCell.$2, record: true)), enabled: !busy);
        } else if (s == null) {
          main = DockAction('START', () => _act(() => _go(g, c!, record: true)), enabled: !busy && c != null);
        } else {
          main = DockAction('START', () => _act(_flow.record), enabled: !busy);
        }
        final DockAction left;
        if (recording) {
          left = DockAction('RESTART', () => _act(() => _go(g, c!, record: true)), enabled: !busy);
        } else if (passed || (cellDone && !failed)) {
          left = DockAction('REDO', () => _act(() => _go(g, c!, record: true)), enabled: !busy && blocked == null && c != null);
        } else {
          left = DockAction('SKIP', () => _act(_flow.skip),
              enabled: !busy && s != null && (state == 'ready' || state == 'failed'));
        }

        final miss = failed && heard != null && expect != null;
        final Widget result;
        if (miss) {
          result = MissView(
            expected: expect,
            scale: st?.scale,
            heard: heard,
            checks: s!.resultChecks,
            sentence: nextStepSentence(checks: s.resultChecks, expected: expect, reasons: s.reasons),
            canKeep: s.canKeep,
            onKeep: () => _act(_flow.keep),
          );
        } else {
          result = Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (expect != null)
                Expanded(
                  child: ShapePlot(
                    expected: expect,
                    scale: st?.scale,
                    liveHz: recording ? liveFromVoice(s!.live.traceHz) : const [],
                    heard: passed && heard != null ? [heard] : const [],
                    checks: recording ? s!.live.checks : (passed ? s!.resultChecks : const []),
                    height: 84,
                    alignToHeard: true,
                    grow: true,
                  ),
                ),
              SizedBox(height: p(4)),
              if (_flow.error != null && blocked == null)
                SignalNote(signal: Signal.stop, text: _flow.error!, textKey: const Key('take_error'))
              else if (failed)
                // no sound to compare (nothing heard, the store refused it): the service's plain statement
                SignalNote(
                    signal: Signal.stop,
                    text: s!.reason ?? 'Nothing to compare.',
                    textKey: const Key('take_reason'))
              else if (passed)
                SignalNote(
                    signal: Signal.idle,
                    text: 'Stored. ${gesture?.done ?? 0} of $gn ${_cap(g)} takes done.',
                    textKey: const Key('take_state'))
              else if (recording)
                SignalNote(
                    signal: Signal.listening,
                    text: s!.heardN > 0 ? 'Heard it. Checking...' : 'Listening. Make the sound now.',
                    textKey: const Key('take_state'))
              else if (roundDone)
                SignalNote(
                    signal: Signal.idle,
                    text: nextCell == null
                        ? 'Every take is recorded.'
                        : 'Every ${_cap(g)} take is done. Next: ${_cap(nextCell.$1)}.',
                    textKey: const Key('take_state'))
              else
                SignalNote(
                    signal: Signal.idle,
                    text: cellDone ? 'Recorded before. START records it again.' : 'Tap START, then make the sound.',
                    textKey: const Key('take_state')),
            ],
          );
        }

        final window = PixelWindow(
          key: Key('take_${g}_${c ?? ''}'),
          title: gi == 0 ? _cap(g) : 'Take $gi of $gn · ${_cap(g)}',
          expand: !miss,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Sentence(s?.prompt ?? cellInfo?.prompt ?? '', key: const Key('take_sentence')),
              if (s?.hint != null) ...[
                SizedBox(height: p(3)),
                Text(s!.hint!, key: const Key('take_hint'), style: p.body(t.ink, line: 11)),
              ],
              SizedBox(height: p(4)),
              if (miss) result else Expanded(child: result),
            ],
          ),
        );
        return StepFrame(
          title: 'Train',
          backKey: const Key('step_back'),
          onBack: _leave,
          bodyKey: const Key('take_body'),
          scroll: miss,
          pager: StepPager(
            // the take's place in the whole plan (52), as the arrows move over it
            index: at >= 0 ? at : math.max(0, (s?.pos.i ?? 1) - 1),
            count: plan.isEmpty ? (s?.pos.n ?? 52) : plan.length,
            canPrev: !busy && blocked == null && at > 0,
            canNext: !busy && blocked == null && at >= 0 && at < plan.length - 1,
            onPrev: () => _act(() => _go(plan[at - 1].$1, plan[at - 1].$2)),
            onNext: () => _act(() => _go(plan[at + 1].$1, plan[at + 1].$2)),
          ),
          banner: blocked == null
              ? null
              : OffBanner(
                  blocker: blocked,
                  action: st?.blockedAction,
                  onFix: () async {
                    await fixBlocker(widget.backend, st!.blockedAction!);
                    await _flow.refresh();
                    if (mounted && _flow.status?.blocked == null && _flow.session == null && c != null) {
                      _act(() => _go(g, c));
                    }
                  },
                ),
          dock: ActionDock(
            caption: blocked != null ? "Canti can't hear: $blocked" : null,
            left: left,
            right: DockAction('STEPS', _leave),
            main: main,
          ),
          children: [miss ? window : Expanded(child: window)],
        );
      },
    );
  }
}

/// A cell's wanted shape before the service sends its own (no round open: blocked, loading), as expectMap does.
ExpectedShape? _expectOf(String gesture, TrainCell? cell) {
  if (cell == null) return null;
  const contours = ['rise', 'fall', 'arch', 'dip', 'flat'];
  if (!contours.contains(gesture)) return ExpectedShape(sequence: [gesture], start: 'none');
  final speed = cell.tags['speed'] ?? cell.tags['length'];
  return ExpectedShape(
    sequence: [gesture],
    start: cell.tags['pitch'] == 'high' ? 'high' : 'low',
    durS: speed == 'quick' || speed == 'short' ? 0.6 : (speed == null ? 0.8 : 1.5),
  );
}

HeardSound? _heardSound(TrainHeard? h) => h == null
    ? null
    : HeardSound(label: h.label, relMs: 0, durMs: h.durMs, pitch16: h.pitch16, f0Hz: h.f0Hz);

// --- the review of an unconfirmed take ---------------------------------------------------------------------------------

/// The review of the takes stored with a label mismatch, one screen per take: "Canti heard ARCH. Keep as RISE?" with the
/// two shapes, and the dock: DELETE (train_confirm keep: false) / KEEP (keep: true). After a decision it shows the next
/// take to check, and goes back to the hub after the last.
class ReviewScreen extends StatefulWidget {
  const ReviewScreen({super.key, required this.backend, required this.train, required this.take, this.flow});

  final VoxBackend backend;
  final TrainBackend train;
  final TrainUnconfirmed take;
  final TrainFlow? flow;

  @override
  State<ReviewScreen> createState() => _ReviewScreenState();
}

class _ReviewScreenState extends State<ReviewScreen> {
  late final TrainFlow _flow = widget.flow ?? TrainFlow(backend: widget.train);
  late TrainUnconfirmed _take = widget.take;

  @override
  void initState() {
    super.initState();
    _flow.attach();
  }

  @override
  void dispose() {
    if (widget.flow == null) _flow.dispose();
    super.dispose();
  }

  Future<void> _decide(bool keep) async {
    await _flow.confirm(_take.id, keep: keep);
    if (!mounted || _flow.error != null) return;
    final next = _flow.status?.unconfirmed.where((u) => u.id != _take.id).firstOrNull;
    if (next == null) {
      closeRoute(context);
    } else {
      setState(() => _take = next);
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    return ListenableBuilder(
      listenable: _flow,
      builder: (context, _) {
        final left = _flow.status?.unconfirmed.length ?? 1;
        final want = _take.gesture, heard = _take.heard ?? '?';
        // the take as heard: its own pitch16 (and f0), so the review plots the actual take, not the canonical outline
        final heardSound = HeardSound(
            label: heard, relMs: 0, durMs: _take.durMs, pitch16: _take.pitch16, f0Hz: _take.f0Hz);
        Widget shape(String title, List<HeardSound> h) => Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  PixelSnap(child: Text(title, style: p.title(t.ink))),
                  SizedBox(height: p(2)),
                  Expanded(
                    child: ShapePlot(
                        expected: ExpectedShape(sequence: [want]), heard: h, height: 48, showLegend: false, grow: true),
                  ),
                ],
              ),
            );
        return StepFrame(
          title: 'Check',
          backKey: const Key('review_back'),
          onBack: () => closeRoute(context),
          bodyKey: const Key('review_body'),
          scroll: false,
          dock: ActionDock(
            caption: left > 1 ? '$left takes to check' : null,
            left: DockAction('DELETE', () => _decide(false), enabled: !_flow.busy),
            right: DockAction('STEPS', () => closeRoute(context)),
            main: DockAction('KEEP', () => _decide(true), enabled: !_flow.busy),
          ),
          children: [
            Expanded(
              child: PixelWindow(
                key: Key('review_${_take.id}'),
                title: 'Take to check · ${_cap(want)}',
                expand: true,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Sentence('Canti heard ${heard.toUpperCase()}. Keep as ${want.toUpperCase()}?',
                        key: const Key('review_sentence')),
                    SizedBox(height: p(4)),
                    Expanded(
                      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        shape('HEARD', [heardSound]),
                        SizedBox(width: p(4)),
                        shape('WANTED', const []),
                      ]),
                    ),
                    SizedBox(height: p(4)),
                    Text('The take passed the checks for ${want.toUpperCase()}, but Canti labelled it '
                        '${heard.toUpperCase()}. KEEP teaches Canti your $want; DELETE drops the take.',
                        style: p.body(t.ink, line: 11)),
                    if (_flow.error != null) ...[
                      SizedBox(height: p(3)),
                      SignalNote(signal: Signal.stop, text: _flow.error!, textKey: const Key('review_error')),
                    ],
                  ],
                ),
              ),
            ),
          ],
        );
      },
    );
  }
}
