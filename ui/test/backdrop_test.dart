import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vox_ui/src/theme/clearing.dart';
import 'package:vox_ui/src/theme/dither_background.dart';
import 'package:vox_ui/src/theme/pixel.dart';
import 'package:vox_ui/vox_ui.dart';

/// The background's EQ bars: Canti's state -> the motif, and who sets it (backdrop_render_test.dart draws them).
void main() {
  BackdropMood moodOf(WidgetTester tester, Type screen) => BackdropMood.maybeOf(tester.element(find.byType(screen)))!;

  group('BackdropMood', () {
    test('each badge state maps to its motif', () {
      const want = {
        'idle': BackdropMotif.ticks,
        'cursor': BackdropMotif.ticks,
        'error': BackdropMotif.ticks,
        'something-new': BackdropMotif.ticks,
        'hearing': BackdropMotif.bars,
        'pending': BackdropMotif.bars,
        'hold-scroll': BackdropMotif.bars,
        'hold_scroll': BackdropMotif.bars,
        'off': BackdropMotif.flat,
        'paused': BackdropMotif.flat,
        'tap-to-wake': BackdropMotif.flat,
      };
      for (final e in want.entries) {
        expect(BackdropMood.motifFor(e.key), e.value, reason: e.key);
      }
      // the shader's uMode
      expect([for (final m in BackdropMotif.values) m.index], [0, 1, 2]);
      expect(BackdropMotif.values, [BackdropMotif.ticks, BackdropMotif.bars, BackdropMotif.flat]);
    });

    test('a recording screen overrides the held state, with its level; notifies only on change', () {
      final m = BackdropMood();
      var n = 0;
      m.addListener(() => n++);
      expect(m.motif, BackdropMotif.ticks);
      m.held = 'paused';
      expect(m.motif, BackdropMotif.flat);
      m.listen(true, levelDb: -27);
      expect(m.motif, BackdropMotif.bars);
      expect(m.level, closeTo(33 / 45, 1e-9));
      m.listen(true, levelDb: -27);
      expect(n, 2);
      m.listen(true); // a source without a level: the bars move by themselves
      expect(m.level, isNull);
      m.listen(false, levelDb: -20);
      expect(m.motif, BackdropMotif.flat);
      expect(m.level, isNull);
      expect(BackdropMood.levelOf(-80), 0);
      expect(BackdropMood.levelOf(-15), 1);
      expect(BackdropMood.levelOf(0), 1);
    });
  });

  testWidgets('the status screen sets the held state: idle, a badge event, paused', (tester) async {
    final b = FakeBackend();
    await tester.pumpWidget(VoxUiApp(backend: b));
    await tester.pumpAndSettle();
    final mood = moodOf(tester, StatusScreen);
    expect(mood.held, 'idle');
    expect(mood.motif, BackdropMotif.ticks);
    b.emit('badge', {'event': 'state', 'state': 'hearing'});
    await tester.pumpAndSettle();
    expect(mood.motif, BackdropMotif.bars);
    await tester.tap(find.text('Pause Canti'));
    await tester.pumpAndSettle();
    expect(mood.held, 'paused');
    expect(mood.motif, BackdropMotif.flat);
  });

  testWidgets('the status screen keeps no strip for the EQ band: the bars show only in free space', (tester) async {
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 2.625;
    tester.view.viewPadding = const FakeViewPadding(bottom: 63);
    tester.view.padding = const FakeViewPadding(bottom: 63);
    addTearDown(tester.view.reset);
    await tester.pumpWidget(VoxUiApp(backend: FakeBackend()));
    await tester.pumpAndSettle();
    final p = Px.of(tester.element(find.byType(StatusScreen)));
    final scroll = tester.getRect(find.byType(SingleChildScrollView).first);
    final bottom = 2400 / 2.625 - 63 / 2.625;
    expect(bottom - scroll.bottom, lessThan(p(cellArtPx * eqBandCells)));
  });

  testWidgets('the status screen: no service is off', (tester) async {
    await tester.pumpWidget(VoxUiApp(backend: FakeBackend(initial: VoxStatus.offline)));
    await tester.pumpAndSettle();
    expect(moodOf(tester, StatusScreen).motif, BackdropMotif.flat);
  });

  testWidgets('a calibration step drives the bars with the live level, and lets go when it ends', (tester) async {
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 2.625;
    addTearDown(tester.view.reset);
    final b = FakeBackend(initial: VoxStatus.fromMap({'service': true, 'armed': true, 'paused': false, 'mode': 'cursor', 'sound_source': 'phone'}));
    await tester.pumpWidget(VoxUiApp(backend: b));
    await tester.pumpAndSettle();
    tester.state<NavigatorState>(find.byType(Navigator)).push(
        MaterialPageRoute<bool>(builder: (_) => CalibrationScreen(backend: b, source: 'phone')));
    await tester.pumpAndSettle();
    final mood = moodOf(tester, CalibrationScreen);
    Map<String, Object?> st(String state, [double? db]) => {
          'active': true, 'source': 'phone', 'step': 'hum', 'state': state, 'progress': 0.5,
          'live': {'voiced': db != null, 'level_db': db}, 'step_done': state == 'step_done',
        };
    b.emitCalib(st('recording', -22));
    await tester.pumpAndSettle();
    expect(mood.motif, BackdropMotif.bars);
    expect(mood.level, closeTo(38 / 45, 1e-9));
    b.emitCalib(st('step_done'));
    await tester.pumpAndSettle();
    expect(mood.level, isNull);
    expect(mood.motif, isNot(BackdropMotif.bars));
    b.emitCalib(st('waiting', -50));
    await tester.pumpAndSettle();
    expect(mood.motif, BackdropMotif.bars);
    tester.state<NavigatorState>(find.byType(Navigator)).pop();
    await tester.pumpAndSettle();
    expect(mood.motif, isNot(BackdropMotif.bars));
  });

  testWidgets('a training take drives the bars: with the level from the phone mic', (tester) async {
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 2.625;
    addTearDown(tester.view.reset);
    final b = FakeBackend();
    final t = FakeTrainBackend(source: 'phone');
    useTrainBackend(b, t);
    final flow = TrainFlow(backend: t);
    await tester.pumpWidget(VoxUiApp(backend: b, home: TrainScreen(train: t, flow: flow)));
    await tester.pumpAndSettle();
    final mood = moodOf(tester, TrainScreen);
    expect(mood.motif, BackdropMotif.ticks);
    await flow.startRound('arch');
    await tester.pumpAndSettle();
    expect(mood.motif, BackdropMotif.bars);
    t.trace([200, 210], levelDb: -24);
    await tester.pumpAndSettle();
    expect(mood.level, closeTo(36 / 45, 1e-9));
    t.finishTake();
    await tester.pumpAndSettle();
    expect(mood.motif, BackdropMotif.ticks);
  });
}
