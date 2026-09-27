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

  testWidgets('the calibrate preview walks through every step to the result', (tester) async {
    final p = await preview(tester, {'VOX_PREVIEW': 'calibrate', 'VOX_PREVIEW_FAIL': 'glide', 'VOX_PREVIEW_POPS': '1'});
    await waitFor(tester, find.byKey(const Key('calib_save')), ticks: 1200);
    expect(find.byKey(const Key('calib_pops_hint')), findsOneWidget);
    expect(p.backend.calibCalls.map((c) => c.$1),
        ['calib_start', 'calib_step', 'calib_skip', 'calib_step', 'calib_step', 'calib_step', 'calib_step', 'calib_step'],
        reason: 'after a skip the service moves on by itself: vowels is not asked for');
    p.backend.dispose();
  });

  testWidgets('the calibrate preview can record only a v1 profile\'s missing steps', (tester) async {
    final p = await preview(tester, {'VOX_PREVIEW': 'calibrate', 'VOX_PREVIEW_SAVED': 'v1', 'VOX_PREVIEW_STEPS': 'missing'});
    await waitFor(tester, find.byKey(const Key('calib_save')), ticks: 1200);
    expect([for (final (m, a) in p.backend.calibCalls) if (m != 'calib_get') '$m ${a.values.join(' ')}'.trim()],
        ['calib_start phone [clicks, whistle, hiss, room]', 'calib_step whistle', 'calib_step hiss', 'calib_step room']);
    p.backend.dispose();
  });

  testWidgets('the calibrate preview holds a step still', (tester) async {
    final p = await preview(tester, {'VOX_PREVIEW': 'calibrate', 'VOX_PREVIEW_HOLD': 'vowels'});
    await waitFor(tester, find.byKey(const Key('calib_vowel')), ticks: 1200);
    final n = p.backend.calibCalls.length;
    await tester.pump(const Duration(seconds: 5));
    expect(find.byKey(const Key('calib_vowel')), findsOneWidget);
    expect(p.backend.calibCalls.length, n);
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
    ('grid', 'train_card_window'),
    ('recording', 'train_trace'),
    ('failed', 'train_keep'),
    ('finished', 'train_done'),
  ]) {
    testWidgets('the train preview holds $hold', (tester) async {
      final p = await preview(tester, {'VOX_PREVIEW': 'train', 'VOX_PREVIEW_HOLD': hold});
      await waitFor(tester, find.byKey(Key(key)));
      expect(tester.takeException(), isNull);
      p.backend.dispose();
    });
  }

  testWidgets('the live train preview records a take by itself and fails the first (heard a dip)', (tester) async {
    final p = await preview(tester, {'VOX_PREVIEW': 'train'});
    await tester.pump();
    await tester.tap(find.byKey(const Key('train_card_arch')));
    await tester.pump();
    await tester.ensureVisible(find.byKey(const Key('train_record_missing')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('train_record_missing')));
    await waitFor(tester, find.byKey(const Key('train_reason')), ticks: 60);
    expect(find.textContaining('Heard a dip'), findsOneWidget);
    await tester.ensureVisible(find.byKey(const Key('train_retry')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('train_retry')));
    await waitFor(tester, find.text('Good: stored.'), ticks: 60);
    await tester.ensureVisible(find.byKey(const Key('train_stop')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('train_stop')));
    await tester.pump();
    p.backend.dispose();
  });
}
