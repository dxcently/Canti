import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vox_ui/vox_ui.dart';
import 'package:vox_ui_desktop/preview.dart';

void main() {
  testWidgets('the desktop runner shows the status screen with demo events', (tester) async {
    // The runner's default window (linux/runner/my_application.cc).
    tester.view.physicalSize = const Size(420, 820);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final b = FakeBackend(demo: true, demoEvery: const Duration(milliseconds: 100));
    await tester.pumpWidget(VoxUiApp(backend: b));
    await tester.pump();
    expect(find.text('Listening for sounds'), findsOneWidget);
    await tester.pump(const Duration(milliseconds: 150));
    await tester.pump();
    expect(find.text('msg'), findsOneWidget);
    expect(find.text('decision'), findsOneWidget);
    b.dispose();
  });

  Future<Preview> preview(WidgetTester tester, Map<String, String> env) async {
    tester.view.physicalSize = const Size(420, 820);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final p = Preview.fromEnv(env)!;
    await tester.pumpWidget(VoxUiApp(backend: p.backend, home: p.home));
    p.start();
    return p;
  }

  Future<void> waitFor(WidgetTester tester, Finder f, {int ticks = 400}) async {
    for (var i = 0; i < ticks && f.evaluate().isEmpty; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    expect(f, findsWidgets);
  }

  testWidgets('the calibrate preview is the hub; RUN THE REST walks the steps, moving on by itself', (tester) async {
    final p = await preview(tester, {'VOX_PREVIEW': 'calibrate'});
    await tester.pump();
    expect(find.byType(HubScreen), findsOneWidget);
    await tester.tap(find.byKey(const Key('dock_main')));
    await waitFor(tester, find.byKey(const Key('calib_step_glide')), ticks: 200);
    expect([for (final (m, a) in p.backend.calibCalls) if (m == 'calib_step') a['step']], ['hum', 'glide']);
    await tester.tap(find.byKey(const Key('dock_right'))); // STEPS
    await tester.pump(const Duration(seconds: 1));
    p.backend.dispose();
  });

  testWidgets('the calibrate preview with a v1 profile shows only its missing steps as not done', (tester) async {
    final p = await preview(tester, {'VOX_PREVIEW': 'calibrate', 'VOX_PREVIEW_SAVED': 'v1'});
    await tester.pump();
    await tester.pump();
    expect(find.text('CALIBRATE 3/7'), findsOneWidget);
    p.backend.dispose();
  });

  testWidgets('the calibrate preview holds a step still', (tester) async {
    final p = await preview(tester, {'VOX_PREVIEW': 'calibrate', 'VOX_PREVIEW_HOLD': 'vowels'});
    await waitFor(tester, find.textContaining(RegExp(r'^(ee|ah|oo)$')), ticks: 1200);
    final n = p.backend.calibCalls.length;
    await tester.pump(const Duration(seconds: 5));
    expect(find.byKey(const Key('calib_readout')), findsOneWidget);
    expect(p.backend.calibCalls.length, n);
    await tester.pumpWidget(const SizedBox());
    p.backend.dispose();
  });

  testWidgets('the calibrate preview holds a failed step with its reason', (tester) async {
    final p = await preview(tester, {'VOX_PREVIEW': 'calibrate', 'VOX_PREVIEW_HOLD': 'failed', 'VOX_PREVIEW_FAIL': 'clicks'});
    await waitFor(tester, find.byKey(const Key('calib_reason')), ticks: 1200);
    expect(find.text('TRY AGAIN'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    p.backend.dispose();
  });

  testWidgets('the cursor preview shows the first-run prompt', (tester) async {
    final p = await preview(tester, {'VOX_PREVIEW': 'cursor'});
    await tester.pump();
    expect(find.byKey(const Key('calib_prompt_start')), findsOneWidget);
    p.backend.dispose();
  });

  // [train]
  for (final (hold, key) in const [
    ('recording', 'take_state'),
    ('failed', 'miss_view'),
    ('passed', 'take_state'),
    ('off', 'off_banner'),
    ('review', 'review_sentence'),
  ]) {
    testWidgets('the train preview holds $hold', (tester) async {
      final p = await preview(tester, {'VOX_PREVIEW': 'train', 'VOX_PREVIEW_HOLD': hold});
      await waitFor(tester, find.byKey(Key(key)));
      await tester.pump(const Duration(milliseconds: 500));
      expect(tester.takeException(), isNull);
      if (hold == 'passed') expect(find.textContaining('Stored.'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
      p.backend.dispose();
    });
  }

  testWidgets('the live train preview records a take by itself and fails the first (heard a dip)', (tester) async {
    final p = await preview(tester, {'VOX_PREVIEW': 'train'});
    await tester.pump(const Duration(milliseconds: 500));
    await tester.pump(const Duration(milliseconds: 500));
    await tester.ensureVisible(find.byKey(const Key('hub_train_arch')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('hub_train_arch')));
    for (var i = 0; i < 10; i++) {
      await tester.pump(const Duration(milliseconds: 100)); // the route comes in over a few frames
    }
    expect(find.byType(TrainTakeScreen), findsOneWidget);
    expect(find.text('START'), findsOneWidget);
    await tester.tap(find.byKey(const Key('dock_main'))); // START
    await tester.pump();
    expect(find.text('STOP'), findsOneWidget);
    await waitFor(tester, find.byKey(const Key('miss_view')), ticks: 60);
    await tester.tap(find.byKey(const Key('dock_main'))); // TRY AGAIN
    await waitFor(tester, find.textContaining('Stored.'), ticks: 60);
    await tester.tap(find.byKey(const Key('dock_right'))); // STEPS
    await tester.pump(const Duration(seconds: 2));
    expect(find.byType(HubScreen), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    p.backend.dispose();
  });

  // [rec]
  for (final (hold, key) in const [
    ('start', 'rec_start'),
    ('hub', 'rec_hub'),
    ('ready', 'rec_ready'),
    ('countdown', 'rec_countdown'),
    ('recording', 'rec_seconds'),
    ('longest', 'rec_cue'),
    ('room', 'rec_room'),
    ('saved', 'rec_saved'),
    ('no_sound', 'rec_no_sound'),
    ('rate', 'rec_rate'),
    ('done', 'rec_pull'),
  ]) {
    testWidgets('the recorder preview holds $hold', (tester) async {
      final p = await preview(tester, {'VOX_PREVIEW': 'recorder', 'VOX_PREVIEW_HOLD': hold});
      await waitFor(tester, find.byKey(Key(key)));
      expect(tester.takeException(), isNull);
      p.backend.dispose();
    });
  }

  testWidgets('the quickrec preview shows a snapshot', (tester) async {
    final p = await preview(tester, {'VOX_PREVIEW': 'quickrec'});
    await waitFor(tester, find.byKey(const Key('qr_clip')));
    expect(tester.takeException(), isNull);
    p.backend.dispose();
  });

  testWidgets('the shape preview renders all variants', (tester) async {
    final p = await preview(tester, {'VOX_PREVIEW': 'shape'});
    await tester.pump();
    expect(tester.takeException(), isNull);
    expect(find.byKey(const Key('shape_plot_contour')), findsWidgets);
    expect(find.byKey(const Key('shape_plot_beat')), findsOneWidget);
    p.backend.dispose();
  });
}
