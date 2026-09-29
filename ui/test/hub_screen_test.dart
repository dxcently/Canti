import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vox_ui/src/theme/glyphs.dart' show Marks;
import 'package:vox_ui/src/theme/kit.dart' show PixelBox, StatRow;
import 'package:vox_ui/vox_ui.dart';

VoxStatus phone([Map<String, Object?> m = const {}]) => VoxStatus.fromMap({
      'service': true, 'armed': true, 'paused': false, 'mode': 'gesture', 'app': 'x.y', 'decider': 'rules',
      'sound_source': 'phone', 'mic_state': 'listening', ...m,
    });

String textOf(WidgetTester tester, String key) => tester.widget<Text>(find.byKey(Key(key))).data!;

/// The plain text of a [Sentence] (its spans).
String sentenceOf(WidgetTester tester, String key) =>
    tester.widget<RichText>(find.descendant(of: find.byKey(Key(key)), matching: find.byType(RichText))).text.toPlainText();

Future<void> tapKey(WidgetTester tester, String key, {bool settle = true}) async {
  await tester.ensureVisible(find.byKey(Key(key)));
  await tester.pump();
  await tester.tap(find.byKey(Key(key)));
  if (settle) {
    await tester.pumpAndSettle();
  } else {
    await flush(tester);
  }
}

Finder pagerIcon(String tooltip) => find.byWidgetPredicate((w) => w is IconButton && w.tooltip == tooltip);

bool arrowEnabled(WidgetTester tester, String tooltip) =>
    tester.widget<IconButton>(pagerIcon(tooltip)).onPressed != null;

String dockLabel(WidgetTester tester, String slot) =>
    tester.widget<Text>(find.descendant(of: find.byKey(Key('dock_$slot')), matching: find.byType(Text)).first).data!;

bool dockEnabled(WidgetTester tester, String slot) =>
    tester.widget<ButtonStyleButton>(find.byKey(Key('dock_$slot'))).onPressed != null;

/// The step layout's rule: every control is in the dock, none in the content.
void expectNoButtonsInBody(WidgetTester tester, String bodyKey) {
  final body = find.byKey(Key(bodyKey));
  expect(body, findsOneWidget);
  expect(find.descendant(of: body, matching: find.byWidgetPredicate((w) => w is ButtonStyleButton)), findsNothing);
  for (final s in ['left', 'right', 'main']) {
    expect(find.byKey(Key('dock_$s')), findsOneWidget);
  }
}

void phoneSize(WidgetTester tester) {
  tester.view.physicalSize = const Size(1080, 2640);
  tester.view.devicePixelRatio = 2.6;
  addTearDown(tester.view.reset);
}

Future<(FakeBackend, FakeTrainBackend)> pumpTake(WidgetTester tester, FakeTrainBackend t,
    {String gesture = 'arch', String cell = 'hum-low-slow', FakeBackend? backend}) async {
  phoneSize(tester);
  final b = backend ?? FakeBackend(initial: phone());
  useTrainBackend(b, t);
  await tester.pumpWidget(const SizedBox());
  await tester.pumpWidget(
      VoxUiApp(backend: b, home: TrainTakeScreen(backend: b, train: t, gesture: gesture, cell: cell)));
  await tester.pumpAndSettle();
  return (b, t);
}

Future<FakeBackend> pumpCalibStep(WidgetTester tester, FakeBackend b, String step) async {
  phoneSize(tester);
  await tester.pumpWidget(VoxUiApp(backend: b, home: CalibStepScreen(backend: b, source: 'phone', step: step)));
  await flush(tester);
  await flush(tester);
  return b;
}

Future<FakeBackend> pumpHub(WidgetTester tester, FakeBackend b, {FakeTrainBackend? t}) async {
  phoneSize(tester);
  final train = t ?? FakeTrainBackend(source: 'phone');
  useTrainBackend(b, train);
  await tester.pumpWidget(VoxUiApp(backend: b, home: HubScreen(backend: b, source: 'phone', train: train)));
  await tester.pumpAndSettle();
  return b;
}

/// Lets a push arrive (a stream event lands after the frame that follows it) and draws it.
Future<void> flush(WidgetTester tester) async {
  await tester.pump();
  await tester.pump();
}

/// Runs the fake calibration's made-up recording until [until] holds (100 ms ticks).
Future<void> runUntil(WidgetTester tester, bool Function() until, {int max = 200}) async {
  for (var i = 0; i < max && !until(); i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
  expect(until(), isTrue);
}

List<String> calibCalls(FakeBackend b) => [
      for (final (m, a) in b.calibCalls)
        if (m != 'calib_get' && m != 'calib_status') a.isEmpty ? m : '$m ${a.values.join(',')}',
    ];

void main() {
  group('font A sentence', () {
    testWidgets('Departure Mono, snapped to its 11 px grid; the capitalised key words are inverted', (tester) async {
      phoneSize(tester);
      await tester.pumpWidget(VoxUiApp(
          backend: FakeBackend(initial: phone()),
          home: const Scaffold(body: Sentence('Start LOW, then go UP.', key: Key('s')))));
      final rich = tester.widget<RichText>(find.descendant(of: find.byKey(const Key('s')), matching: find.byType(RichText)));
      final root = (rich.text as TextSpan).children!.single as TextSpan; // Text.rich wraps it in the default style
      expect(root.style!.fontFamily, 'DepartureMono');
      // 16 art px at 2.6x is exactly 80 device px (twice the 8 art px body)
      expect(root.style!.fontSize! * 2.6, closeTo(80, 1e-9));
      final keyWords = [
        for (final s in root.children!.cast<TextSpan>())
          if (s.style?.background != null) s.text,
      ];
      expect(keyWords, ['LOW', 'UP']);
      expect(root.toPlainText(), 'Start LOW, then go UP.');
    });
  });

  group('training take screen', () {
    testWidgets('the instruction is font A; the ShapePlot is up before the take starts', (tester) async {
      await pumpTake(tester, FakeTrainBackend(source: 'phone'));
      final rich = tester.widget<RichText>(
          find.descendant(of: find.byKey(const Key('take_sentence')), matching: find.byType(RichText)));
      expect(((rich.text as TextSpan).children!.single as TextSpan).style!.fontFamily, 'DepartureMono');
      expect(sentenceOf(tester, 'take_sentence'), isNotEmpty);
      expect(find.byType(ShapePlot), findsOneWidget);
      expect(dockLabel(tester, 'main'), 'START');
      expectNoButtonsInBody(tester, 'take_body');
    });

    testWidgets('a live take: the trace from the first voiced tick, pending checks are not misses', (tester) async {
      final (_, t) = await pumpTake(tester, FakeTrainBackend(source: 'phone'));
      await tapKey(tester, 'dock_main'); // START
      expect(t.calls.last, 'train_record');
      expect(dockLabel(tester, 'main'), 'STOP');
      expect(dockLabel(tester, 'left'), 'RESTART');
      t.trace([null, null, null, 180, 185, 190], levelDb: -30);
      await tester.pumpAndSettle();
      final plot = tester.widget<ShapePlot>(find.byType(ShapePlot));
      expect(plot.liveHz.first, 180); // the leading silence is not drawn
      expect(plot.liveHz.length, 3);
      expect(plot.checks, isNotEmpty);
      final pending = plot.checks.where((c) => c.state == CheckState.pending).toList();
      expect(pending, isNotEmpty);
      for (final c in pending) {
        final chip = tester.widget<PixelBox>(find.byKey(Key('check_${c.id}_pending')));
        expect(chip.inverted, isFalse, reason: '${c.id} pending must not look like a miss');
      }
      expectNoButtonsInBody(tester, 'take_body');
    });

    testWidgets('STOP drops the in-flight take and waits on the same take', (tester) async {
      final (_, t) = await pumpTake(tester, FakeTrainBackend(source: 'phone'));
      await tapKey(tester, 'dock_main'); // START
      await tapKey(tester, 'dock_main'); // STOP
      expect(t.calls.last, 'train_goto arch hum-low-slow');
      expect(find.byType(TrainTakeScreen), findsOneWidget); // it stays
      expect(dockLabel(tester, 'main'), 'START');
    });

    testWidgets('a pass is stored and the next take starts 1.2 s later; ◀ goes back to it', (tester) async {
      final (_, t) = await pumpTake(tester, FakeTrainBackend(source: 'phone'));
      await tapKey(tester, 'dock_main'); // START
      t.finishTake();
      await flush(tester);
      expect(find.byKey(const Key('take_arch_hum-low-slow')), findsOneWidget);
      expect(textOf(tester, 'take_state'), startsWith('Stored.'));
      expect(dockLabel(tester, 'left'), 'REDO');
      await tester.pump(const Duration(milliseconds: 1100));
      expect(find.byKey(const Key('take_arch_hum-low-slow')), findsOneWidget); // not yet
      await tester.pump(const Duration(milliseconds: 200));
      await flush(tester);
      expect(find.byKey(const Key('take_arch_hum-low-quick')), findsOneWidget);
      expect(t.calls.where((c) => c == 'train_next'), isEmpty); // the service moved on; the screen did not race it
      expect(dockLabel(tester, 'main'), 'STOP'); // recording
      await tester.tap(pagerIcon('Previous page'));
      await tester.pumpAndSettle();
      expect(t.calls.last, 'train_goto arch hum-low-slow');
      expect(find.byKey(const Key('take_arch_hum-low-slow')), findsOneWidget);
      expect(dockLabel(tester, 'left'), 'REDO'); // it stayed stored
      expect(textOf(tester, 'take_state'), startsWith('Recorded before'));
    });

    testWidgets('pager arrows call train_goto and are off at the plan ends (no wrap)', (tester) async {
      final t = FakeTrainBackend(source: 'phone');
      final plan = planCells(await t.status());
      final (first, last) = (plan.first, plan.last);
      await pumpTake(tester, t, gesture: first.$1, cell: first.$2);
      expect(arrowEnabled(tester, 'Previous page'), isFalse);
      expect(arrowEnabled(tester, 'Next page'), isTrue);
      await tester.tap(pagerIcon('Next page'));
      await tester.pumpAndSettle();
      expect(t.calls.last, 'train_goto ${plan[1].$1} ${plan[1].$2}');
      await tester.tap(pagerIcon('Previous page'));
      await tester.pumpAndSettle();
      expect(t.calls.last, 'train_goto ${first.$1} ${first.$2}');

      await pumpTake(tester, FakeTrainBackend(source: 'phone'), gesture: last.$1, cell: last.$2);
      expect(arrowEnabled(tester, 'Next page'), isFalse);
      expect(arrowEnabled(tester, 'Previous page'), isTrue);
    });

    testWidgets('a miss: heard vs wanted, ONE next-step sentence, keep only when allowed', (tester) async {
      final (_, t) = await pumpTake(tester, FakeTrainBackend(source: 'phone'));
      await tapKey(tester, 'dock_main');
      t.finishTake(const FakeTake(label: 'dip')); // the wrong shape: keep is allowed
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('miss_view')), findsOneWidget);
      expect(find.descendant(of: find.byKey(const Key('miss_table')), matching: find.text('HEARD')), findsOneWidget);
      expect(find.descendant(of: find.byKey(const Key('miss_table')), matching: find.text('WANTED')), findsOneWidget);
      expect(find.byKey(const Key('miss_row_SHAPE')), findsOneWidget);
      expect(sentenceOf(tester, 'miss_sentence'), 'Next: go UP, then back DOWN.');
      expect(find.byType(Sentence), findsNWidgets(2)); // the instruction + the one next step
      expect(find.byKey(const Key('take_reason')), findsNothing); // the reason is not repeated under it
      expect(find.byKey(const Key('miss_keep')), findsOneWidget);
      expect(dockLabel(tester, 'main'), 'TRY AGAIN');
      expectNoButtonsInBody(tester, 'take_body');
      await tapKey(tester, 'miss_keep');
      expect(t.calls, contains('train_keep'));
    });

    testWidgets('no keep link when the take cannot be kept', (tester) async {
      final (_, t) = await pumpTake(tester, FakeTrainBackend(source: 'phone'));
      await tapKey(tester, 'dock_main');
      t.finishTake(const FakeTake(label: 'dip', unpitched: true));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('miss_view')), findsOneWidget);
      expect(find.byKey(const Key('miss_keep')), findsNothing);
    });

    testWidgets('the off banner: START off, and its one fix resumes Canti', (tester) async {
      final b = FakeBackend(initial: phone({'paused': true}));
      final t = FakeTrainBackend(source: 'phone')
        ..blocked = 'Canti is paused'
        ..blockedAction = 'resume';
      await pumpTake(tester, t, backend: b);
      expect(find.byKey(const Key('off_banner')), findsOneWidget);
      expect(textOf(tester, 'off_banner_text'), 'Canti is paused');
      expect(dockEnabled(tester, 'main'), isFalse);
      expect(arrowEnabled(tester, 'Next page'), isFalse);
      t.blocked = null; // what resuming does on the service
      await tapKey(tester, 'off_banner_fix');
      expect(b.current.paused, isFalse);
      expect(b.commands.last['armed'], isTrue);
      expect(find.byKey(const Key('off_banner')), findsNothing);
      expect(dockEnabled(tester, 'main'), isTrue);
    });

    testWidgets('back ends the round (stored takes stay)', (tester) async {
      final b = FakeBackend(initial: phone());
      final t = FakeTrainBackend(source: 'phone');
      await pumpHub(tester, b, t: t);
      await tapKey(tester, 'hub_train_arch');
      expect(find.byType(TrainTakeScreen), findsOneWidget);
      await tapKey(tester, 'dock_main');
      t.finishTake();
      await flush(tester);
      await tapKey(tester, 'step_back');
      expect(find.byType(TrainTakeScreen), findsNothing);
      expect(t.calls, contains('train_cancel'));
      expect(find.descendant(of: find.byKey(const Key('hub_train_arch')), matching: find.text('1 of 8')), findsOneWidget);
    });

    testWidgets('opening a done take shows it idle (REDO) and does not record', (tester) async {
      final t = FakeTrainBackend(source: 'phone')..fill('arch');
      await pumpTake(tester, t, gesture: 'arch', cell: 'hum-low-slow');
      expect(t.calls.where((c) => c == 'train_record'), isEmpty, reason: 'a done take opens idle');
      expect(textOf(tester, 'take_state'), startsWith('Recorded before'));
      expect(dockLabel(tester, 'left'), 'REDO');
    });
  });

  group('calibration step screen', () {
    testWidgets('font A instruction; the arrows move the service and the screen follows it', (tester) async {
      final b = FakeBackend(initial: phone(), calibAuto: false);
      await pumpCalibStep(tester, b, 'vowels');
      final rich = tester.widget<RichText>(
          find.descendant(of: find.byKey(const Key('step_sentence')), matching: find.byType(RichText)));
      expect(((rich.text as TextSpan).children!.single as TextSpan).style!.fontFamily, 'DepartureMono');
      expect(calibCalls(b), ['calib_step vowels']);
      await tester.tap(pagerIcon('Next page'));
      await flush(tester);
      expect(calibCalls(b).last, 'calib_step clicks');
      // the service's current step is what the screen shows (here: it went to clicks)
      b.emitCalib({'active': true, 'source': 'phone', 'step': 'clicks', 'state': 'waiting'});
      await flush(tester);
      expect(find.byKey(const Key('calib_step_clicks')), findsOneWidget);
      await tester.tap(pagerIcon('Previous page'));
      await flush(tester);
      expect(calibCalls(b).last, 'calib_step vowels');
      expectNoButtonsInBody(tester, 'calib_step_body');
    });

    testWidgets('the arrows are off at the ends and never wrap', (tester) async {
      final b = FakeBackend(initial: phone(), calibAuto: false);
      await pumpCalibStep(tester, b, 'hum');
      expect(arrowEnabled(tester, 'Previous page'), isFalse);
      expect(arrowEnabled(tester, 'Next page'), isTrue);
      b.emitCalib({'active': true, 'source': 'phone', 'step': 'room', 'state': 'waiting'});
      await flush(tester);
      expect(arrowEnabled(tester, 'Next page'), isFalse);
      expect(arrowEnabled(tester, 'Previous page'), isTrue);
    });

    testWidgets('glide and whistle expect an arch from LOW; live checks show while recording', (tester) async {
      final b = FakeBackend(initial: phone(), calibAuto: false);
      await pumpCalibStep(tester, b, 'glide');
      var plot = tester.widget<ShapePlot>(find.byType(ShapePlot));
      expect(plot.expected.sequence, ['arch']);
      expect(plot.expected.start, 'low');
      b.emitCalib({
        'active': true, 'source': 'phone', 'step': 'glide', 'state': 'recording',
        'live': {'trace_hz': [null, 120, 130], 'checks': [
          {'id': 'PITCH', 'label': 'PITCH', 'state': 'ok'},
          {'id': 'SHAPE', 'label': 'SHAPE', 'state': 'pending'},
        ]},
      });
      await flush(tester);
      plot = tester.widget<ShapePlot>(find.byType(ShapePlot));
      expect(plot.liveHz, [120, 130]);
      expect([for (final c in plot.checks) c.state], [CheckState.ok, CheckState.pending]);
      expect(tester.widget<PixelBox>(find.byKey(const Key('check_SHAPE_pending'))).inverted, isFalse);
      expect(dockLabel(tester, 'main'), 'STOP');
    });

    testWidgets('a finished step moves on after 1.2 s; ◀ goes back and it is still saved', (tester) async {
      final b = FakeBackend(initial: phone(), calibAuto: true);
      await pumpCalibStep(tester, b, 'hum');
      await runUntil(tester, () => find.text('NEXT STEP').evaluate().isNotEmpty);
      expect(textOf(tester, 'calib_state'), 'Saved. Next: Glide.');
      final before = calibCalls(b).length;
      await tester.pump(const Duration(milliseconds: 1250));
      await flush(tester);
      expect(calibCalls(b).sublist(before), ['calib_step glide']);
      expect(find.byKey(const Key('calib_step_glide')), findsOneWidget);
      await tester.tap(pagerIcon('Previous page'));
      await flush(tester);
      await flush(tester);
      // ◀ back to a done step shows it idle (never re-records it); the in-flight glide is dropped, hum stays saved
      expect(calibCalls(b).last, 'calib_cancel');
      expect(find.byKey(const Key('calib_step_hum')), findsOneWidget);
      expect(dockLabel(tester, 'left'), 'REDO');
      expect(b.calibProgress['phone']!['done_steps'], contains('hum'));
    });

    testWidgets('the mic off: the off banner, START off; its fix resumes Canti and starts the step', (tester) async {
      final b = FakeBackend(initial: phone({'paused': true}), calibAuto: false)
        ..calibRefusal = 'the mic is off (paused): resume Canti first';
      await pumpCalibStep(tester, b, 'hum');
      expect(find.byKey(const Key('off_banner')), findsOneWidget);
      expect(textOf(tester, 'off_banner_text'), contains('resume Canti first'));
      expect(dockEnabled(tester, 'main'), isFalse);
      b.calibRefusal = null;
      await tapKey(tester, 'off_banner_fix', settle: false);
      await flush(tester);
      expect(b.current.paused, isFalse);
      expect(calibCalls(b).where((c) => c == 'calib_step hum').length, 2);
      expect(find.byKey(const Key('off_banner')), findsNothing);
    });

    testWidgets('the last step done: DONE saves the calibration (calib_save) and goes back', (tester) async {
      final b = FakeBackend(initial: phone(), calibAuto: false);
      phoneSize(tester);
      await tester.pumpWidget(VoxUiApp(backend: b));
      await tester.pumpAndSettle();
      tester.state<NavigatorState>(find.byType(Navigator)).push(MaterialPageRoute<void>(
          builder: (_) => CalibStepScreen(backend: b, source: 'phone', step: 'room')));
      await tester.pump(const Duration(seconds: 1));
      b.emitCalib({
        'active': true, 'source': 'phone', 'step': 'room', 'state': 'step_done', 'step_done': true,
        'hub': [for (final s in calibSteps) {'id': s, 'done': true, 'result_word': 'ok'}],
      });
      await flush(tester);
      expect(dockLabel(tester, 'main'), 'DONE');
      await tester.pump(const Duration(seconds: 2));
      expect(calibCalls(b).where((c) => c.startsWith('calib_step')).length, 1, reason: 'nothing left to move on to');
      await tapKey(tester, 'dock_main', settle: false);
      await tester.pump(const Duration(seconds: 1));
      expect(calibCalls(b).last, 'calib_save');
      expect(find.byType(CalibStepScreen), findsNothing);
    });

    testWidgets('opening a done step shows it idle (REDO/NEXT STEP), records nothing, and keeps the save', (tester) async {
      final b = FakeBackend(initial: phone(), calibAuto: false);
      b.calibProgress['phone'] = {'done_steps': ['hum'], 'current': 'glide', 'updated_ms': 1};
      await pumpCalibStep(tester, b, 'hum');
      expect(calibCalls(b).where((c) => c.startsWith('calib_step') || c.startsWith('calib_start')), isEmpty,
          reason: 'a done step opens idle, unrecorded');
      expect(find.byKey(const Key('calib_step_hum')), findsOneWidget);
      expect(textOf(tester, 'calib_state'), 'Saved. REDO records it again.');
      expect(dockLabel(tester, 'left'), 'REDO');
      expect(dockLabel(tester, 'main'), 'NEXT STEP');
      // opening never touches the save
      expect(b.calibProgress['phone']!['done_steps'], ['hum']);
      expect(b.calibProgress['phone']!['current'], 'glide');
      expect(b.calibSaved['phone'], isNull);
    });

    testWidgets('the ShapePlot grows to fill the space above the dock', (tester) async {
      final b = FakeBackend(initial: phone(), calibAuto: false);
      await pumpCalibStep(tester, b, 'glide');
      final plot = tester.getRect(find.byType(ShapePlot));
      expect(plot.height, greaterThan(200), reason: 'the graph fills the lower half, not a fixed 84 art px');
    });

    testWidgets('the arrows show a done step idle too (navigating never re-records a save)', (tester) async {
      final b = FakeBackend(initial: phone(), calibAuto: false);
      b.calibProgress['phone'] = {'done_steps': ['hum', 'glide'], 'current': 'vowels', 'updated_ms': 1};
      await pumpCalibStep(tester, b, 'hum');
      expect(calibCalls(b).where((c) => c.startsWith('calib_step')), isEmpty);
      expect(dockLabel(tester, 'left'), 'REDO');
      // next → glide is also done: it opens idle, no calib_step / calib_redo
      await tester.tap(pagerIcon('Next page'));
      await flush(tester);
      expect(calibCalls(b).where((c) => c.startsWith('calib_step') || c.startsWith('calib_redo')), isEmpty,
          reason: 'navigating to a done step never records');
      expect(find.byKey(const Key('calib_step_glide')), findsOneWidget);
      expect(dockLabel(tester, 'left'), 'REDO');
      expect(b.calibProgress['phone']!['done_steps'], ['hum', 'glide']);
    });
  });

  group('hub and resume', () {
    test('the hub rows come from the inactive map (it has no hub list), as Kotlin sends it', () async {
      final b = FakeBackend(initial: phone(), calibAuto: false);
      b.calibSaved['phone'] = CalibResult.fromMap({'source': 'phone', 'version': 2, 'home_hz': 142.0})!;
      b.calibProgress['phone'] = {'done_steps': ['hum'], 'current': 'glide', 'updated_ms': 1};
      b.calibBackgroundCancel();
      final s = await b.calibStatusMap();
      expect(s.active, isFalse);
      expect(s.hub, isEmpty);
      expect(s.resume!.doneSteps, ['hum']);
      expect([for (final h in s.hubRows) if (h.done) h.id], ['hum']);
      expect(nextUndoneStep(s.hubRows), 'glide');
    });

    testWidgets('leaving mid-run never resets it: back in, RUN THE REST lands on the saved step', (tester) async {
      final b = FakeBackend(initial: phone(), calibAuto: true);
      await pumpHub(tester, b);
      expect(find.text('CALIBRATE 0/7'), findsOneWidget);
      await tapKey(tester, 'dock_main', settle: false); // RUN THE REST: hum
      await flush(tester);
      expect(find.byType(CalibStepScreen), findsOneWidget);
      // hum finishes, the screen moves on to glide by itself; then the app goes to the background
      await runUntil(tester, () => find.byKey(const Key('calib_step_glide')).evaluate().isNotEmpty, max: 300);
      await tester.pump(const Duration(milliseconds: 300));
      b.calibBackgroundCancel();
      await flush(tester);
      expect(find.byKey(const Key('calib_step_glide')), findsOneWidget);
      await tapKey(tester, 'dock_right', settle: false); // STEPS
      await tester.pump(const Duration(milliseconds: 500));
      expect(find.byType(HubScreen), findsOneWidget);
      expect(find.text('CALIBRATE 1/7'), findsOneWidget);
      expect(textOf(tester, 'hub_resume'), contains('Glide'));
      await tapKey(tester, 'dock_main', settle: false);
      await flush(tester);
      await flush(tester);
      await tester.pump(const Duration(milliseconds: 500));
      expect(calibCalls(b), containsAllInOrder(['calib_start phone,true', 'calib_step glide']));
      expect(find.byKey(const Key('calib_step_glide')), findsOneWidget);
      expect(b.calibProgress['phone']!['done_steps'], ['hum']);
      await tapKey(tester, 'dock_right', settle: false);
      await tester.pump(const Duration(milliseconds: 500));
    });

    testWidgets('undone rows are blank boxes, not crosses; gesture rows show their count', (tester) async {
      final t = FakeTrainBackend(source: 'phone')..fill('rise', cells: ['hum-low-slow', 'hum-low-quick']);
      final b = FakeBackend(initial: phone(), calibAuto: false);
      b.calibSaved['phone'] = CalibResult.fromMap({'source': 'phone', 'version': 2, 'home_hz': 147.0})!;
      b.calibProgress['phone'] = {'done_steps': ['hum'], 'current': 'glide', 'updated_ms': 1};
      await pumpHub(tester, b, t: t);
      expect(find.descendant(of: find.byKey(const Key('hub_calib_hum')), matching: find.text('147 Hz')), findsOneWidget);
      expect(find.descendant(of: find.byKey(const Key('hub_calib_glide')), matching: find.text('not done')), findsOneWidget);
      expect(find.descendant(of: find.byKey(const Key('hub_train_rise')), matching: find.text('2 of 8')), findsOneWidget);
      expect(find.descendant(of: find.byKey(const Key('hub_train_arch')), matching: find.text('not done')), findsOneWidget);
      final undone = tester.widget<StatRow>(
          find.descendant(of: find.byKey(const Key('hub_calib_glide')), matching: find.byType(StatRow)));
      expect(undone.icon, isNot(Marks.cross));
      expect(find.byType(ActionDock), findsOneWidget);
      expectNoButtonsInBody(tester, 'hub_body');
    });

    testWidgets('the hub off banner: its one fix switches to gesture mode', (tester) async {
      final b = FakeBackend(initial: phone({'mode': 'cursor'}));
      final t = FakeTrainBackend(source: 'phone')
        ..blocked = 'Canti is in cursor mode'
        ..blockedAction = 'gesture_mode';
      await pumpHub(tester, b, t: t);
      expect(find.byKey(const Key('off_banner')), findsOneWidget);
      await tapKey(tester, 'off_banner_fix');
      expect(b.commands.last['mode'], 'gesture');
    });

    testWidgets('the hub\'s left dock slot is empty on purpose (disabled, same size as CLOSE)', (tester) async {
      final b = FakeBackend(initial: phone());
      await pumpHub(tester, b);
      final leftBtn = tester.widget<OutlinedButton>(
          find.descendant(of: find.byKey(const Key('dock_left')), matching: find.byType(OutlinedButton)));
      expect(leftBtn.onPressed, isNull, reason: 'the left slot is an empty placeholder, not an action');
      final leftRect = tester.getRect(find.byKey(const Key('dock_left')));
      expect(leftRect.height, greaterThanOrEqualTo(48), reason: 'the empty slot keeps its touch-target height');
      expect(leftRect.width, greaterThan(0), reason: 'the empty slot never collapses to zero size');
    });
  });

  group('takes to check', () {
    testWidgets('"Canti heard ARCH. Keep as RISE?": KEEP / DELETE send the numeric id, then back', (tester) async {
      final t = FakeTrainBackend(source: 'phone');
      t.unconfirmed
        ..add({'id': 7, 'gesture': 'rise', 'heard': 'arch', 'pos': 1})
        ..add({'id': 8, 'gesture': 'fall', 'heard': 'dip', 'pos': 2});
      await pumpHub(tester, FakeBackend(initial: phone()), t: t);
      expect(find.text('2 TAKES TO CHECK'), findsOneWidget);
      await tapKey(tester, 'hub_review_7');
      expect(sentenceOf(tester, 'review_sentence'), 'Canti heard ARCH. Keep as RISE?');
      expect(dockLabel(tester, 'left'), 'DELETE');
      expect(dockLabel(tester, 'main'), 'KEEP');
      expectNoButtonsInBody(tester, 'review_body');
      await tapKey(tester, 'dock_main'); // KEEP
      expect(t.calls, contains('train_confirm 7 true'));
      expect(sentenceOf(tester, 'review_sentence'), 'Canti heard DIP. Keep as FALL?');
      await tapKey(tester, 'dock_left'); // DELETE
      expect(t.calls, contains('train_confirm 8 false'));
      expect(find.byType(ReviewScreen), findsNothing);
      expect(find.byKey(const Key('hub_review')), findsNothing);
    });

    testWidgets('a mismatched pass is stored and waits in the hub to be checked', (tester) async {
      final t = FakeTrainBackend(source: 'phone');
      await pumpHub(tester, FakeBackend(initial: phone()), t: t);
      await tapKey(tester, 'hub_train_rise');
      await tapKey(tester, 'dock_main');
      t.finishTake(const FakeTake(label: 'arch', mismatch: true));
      await flush(tester);
      await tapKey(tester, 'step_back');
      expect(find.byKey(const Key('hub_review')), findsOneWidget);
    });

    testWidgets('the review plots the take\'s own pitch16 as heard, not the outline', (tester) async {
      phoneSize(tester);
      final t = FakeTrainBackend(source: 'phone');
      final b = FakeBackend(initial: phone());
      await tester.pumpWidget(VoxUiApp(
          backend: b,
          home: ReviewScreen(
              backend: b,
              train: t,
              take: const TrainUnconfirmed(
                  id: 7, gesture: 'rise', heard: 'arch', pos: 1, pitch16: [0.0, 1.0, 2.0, 3.0], f0Hz: 180, durMs: 1400))));
      await tester.pumpAndSettle();
      final plots = tester.widgetList<ShapePlot>(find.byType(ShapePlot)).toList();
      expect(plots.length, 2);
      expect(plots[0].heard.single.pitch16, [0.0, 1.0, 2.0, 3.0]); // HEARD: the take itself
      expect(plots[0].heard.single.f0Hz, 180);
      expect(plots[1].heard, isEmpty); // WANTED: the standard outline only
    });

    testWidgets('a take with no pitch still reviews (the heard plot is empty, the outline is shown)', (tester) async {
      phoneSize(tester);
      final b = FakeBackend(initial: phone());
      await tester.pumpWidget(VoxUiApp(
          backend: b,
          home: ReviewScreen(
              backend: b,
              train: FakeTrainBackend(source: 'phone'),
              take: const TrainUnconfirmed(id: 7, gesture: 'click', heard: 'click', pos: 1))));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      final plots = tester.widgetList<ShapePlot>(find.byType(ShapePlot)).toList();
      expect(plots.length, 2);
      expect(plots[0].heard.single.pitch16, isEmpty); // HEARD: no pitch, nothing to trace
      expect(plots[0].heard.single.f0Hz, isNull);
      expect(plots[1].heard, isEmpty); // WANTED: the standard outline only
    });
  });

  group('the next-step sentence', () {
    const arch = ExpectedShape(sequence: ['arch'], start: 'low', durS: 0.8);
    ShapeCheck miss(String id, [String? want]) => ShapeCheck(id, id, CheckState.miss, want: want);

    test('one plain step from the first miss, never a guess at what the user did', () {
      final said = {
        'PITCH': nextStepSentence(checks: [miss('PITCH', 'low')], expected: arch),
        'SHAPE': nextStepSentence(checks: [miss('SHAPE', 'arch')], expected: arch),
        'LENGTH': nextStepSentence(checks: [miss('LENGTH', 'slow')], expected: arch),
        'SOUND': nextStepSentence(checks: [miss('SOUND', 'whistle')], expected: arch),
        'LOUD': nextStepSentence(checks: [miss('LOUD')], expected: arch),
        'none': nextStepSentence(checks: const [], expected: arch),
      };
      expect(said['PITCH'], 'Next: start LOW, near the bottom of your range.');
      expect(said['SHAPE'], 'Next: go UP, then back DOWN.');
      expect(said['LENGTH'], 'Next: make it SLOW, about 1.5 s.');
      expect(said['SOUND'], 'Next: WHISTLE it.');
      for (final s in said.values) {
        expect(s, startsWith('Next: '));
        expect(s.endsWith('.'), isTrue);
        expect(s.toLowerCase(), isNot(matches(RegExp(r'\byou (were|went|did|made|sang|hummed)|too (high|low|short|long|quiet)'))));
      }
      // the first miss wins; near and pending are not misses
      expect(
          nextStepSentence(checks: [
            const ShapeCheck('PITCH', 'PITCH', CheckState.near),
            const ShapeCheck('SHAPE', 'SHAPE', CheckState.pending),
            miss('LENGTH', 'quick'),
          ], expected: arch),
          'Next: make it QUICK, under a second.');
    });

    test('heard values from the numbers Kotlin sends', () {
      ShapeCheck c(String id, Object v) => ShapeCheck.fromMap({'id': id, 'label': id, 'state': 'miss', 'value': v});
      expect(heardText(c('PITCH', 2.5)), '+2.5 st HOME');
      expect(heardText(c('SHAPE', -1.4)), '-1.4 st');
      expect(heardText(c('LENGTH', 640)), '0.6 s');
      expect(heardText(c('SOUND', 212)), 'hum 212 Hz');
      expect(heardText(const ShapeCheck('PITCH', 'PITCH', CheckState.pending)), 'no scale');
    });
  });
}
