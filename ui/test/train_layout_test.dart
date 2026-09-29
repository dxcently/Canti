import 'dart:io';
import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vox_ui/vox_ui.dart';

/// The tests hub, the calibration steps and the training takes on the Z Flip 6 inner screen (1080 x 2640 px at 2.6x,
/// a 94 px status bar) with the real pixel fonts (font A included), light and dark: nothing overflows, the content
/// scrolls above the dock, the dock is whole on screen and there is no strip kept for the EQ bars. With VOX_SHOTS_DIR
/// set, each screen is also written there as a PNG.
void main() {
  setUpAll(() async {
    for (final (fam, file) in [
      ('PressStart2P', 'PressStart2P-Regular.ttf'),
      ('Tiny5', 'Tiny5-Regular.ttf'),
      ('DepartureMono', 'DepartureMono-Regular.otf'),
    ]) {
      final bytes = File('assets/fonts/$file').readAsBytesSync();
      await (FontLoader(fam)..addFont(Future.value(ByteData.sublistView(bytes)))).load();
    }
  });

  final shots = Platform.environment['VOX_SHOTS_DIR'];
  const scale = {'low_hz': 110.0, 'home_hz': 147.0, 'high_hz': 262.0};

  VoxStatus status([Map<String, Object?> m = const {}]) => VoxStatus.fromMap({
        'service': true, 'armed': true, 'paused': false, 'mode': 'gesture', 'app': 'x.y', 'decider': 'rules',
        'sound_source': 'phone', ...m,
      });

  /// An arch sung from LOW: [n] ticks of 20 ms, after a short silence.
  List<double?> archHz(int n, {double from = 118, double span = 5}) => [
        null, null, null,
        for (var i = 0; i < n; i++) from * math.pow(2, span * math.sin(math.pi * i / 70) / 12).toDouble(),
      ];

  FakeTrainBackend trainWithProgress() => FakeTrainBackend(source: 'phone')
    ..scale = scale
    ..fill('rise')
    ..fill('fall', cells: ['hum-low-slow', 'hum-low-quick', 'hum-high-slow'])
    ..fill('click');

  Map<String, Object?> calibLive(String step, String state, {List<double?> trace = const [], Object? checks,
          double? level = -24, String? vowel}) =>
      {
        'active': true, 'source': 'phone', 'step': step, 'state': state, 'progress': 0.55,
        'prompt': null, 'scale': scale,
        'live': {'trace_hz': trace, 'level_db': level, 'pitch_hz': trace.lastOrNull, 'vowel': ?vowel, 'checks': ?checks},
        'heard': <String, int>{},
        'step_done': state == 'step_done',
      };

  // name -> builds the screen (backend, train) and drives it to the state to show
  final screens = <String, Future<Widget> Function(WidgetTester, FakeBackend, FakeTrainBackend)>{
    'hub': (tester, b, t) async {
      b.calibSaved['phone'] = CalibResult.fromMap({
        'source': 'phone', 'version': 2, 'home_hz': 147.0, 'voicing_threshold': 0.42, 'range_lo_hz': 104.0,
        'range_hi_hz': 262.0, 'vowels': {'ee': {'acc': 0.9}, 'ah': {'acc': 0.8}, 'oo': {'acc': 0.85}},
      })!;
      b.calibProgress['phone'] = {'done_steps': ['hum', 'glide', 'vowels'], 'current': 'clicks', 'updated_ms': 1};
      t.unconfirmed.add({'id': 12, 'gesture': 'rise', 'heard': 'arch', 'pos': 4});
      return HubScreen(backend: b, source: 'phone', train: t);
    },
    'hub-off': (tester, b, t) async {
      t
        ..blocked = 'Canti is paused.'
        ..blockedAction = 'resume';
      return HubScreen(backend: b, source: 'phone', train: t);
    },
    'calib-hum-live': (tester, b, t) async {
      final w = CalibStepScreen(backend: b, source: 'phone', step: 'hum');
      Future<void>.delayed(Duration.zero, () => b.emitCalib(calibLive('hum', 'recording',
          trace: [null, null, for (var i = 0; i < 90; i++) 147 + 3 * math.sin(i / 9)],
          checks: [
            {'id': 'PITCH', 'label': 'PITCH', 'state': 'ok', 'value': 0.2},
            {'id': 'SHAPE', 'label': 'SHAPE', 'state': 'near', 'value': 1.1},
            {'id': 'LENGTH', 'label': 'LENGTH', 'state': 'pending'},
          ])));
      return w;
    },
    'calib-glide-live': (tester, b, t) async {
      final w = CalibStepScreen(backend: b, source: 'phone', step: 'glide');
      Future<void>.delayed(Duration.zero, () => b.emitCalib(calibLive('glide', 'recording',
          trace: archHz(60, from: 104, span: 16),
          checks: [
            {'id': 'PITCH', 'label': 'PITCH', 'state': 'ok'},
            {'id': 'SHAPE', 'label': 'SHAPE', 'state': 'pending'},
            {'id': 'LENGTH', 'label': 'LENGTH', 'state': 'pending'},
          ])));
      return w;
    },
    'calib-clicks': (tester, b, t) async {
      final w = CalibStepScreen(backend: b, source: 'phone', step: 'clicks');
      Future<void>.delayed(Duration.zero, () => b.emitCalib(calibLive('clicks', 'recording', level: -18)));
      return w;
    },
    'calib-done': (tester, b, t) async {
      final w = CalibStepScreen(backend: b, source: 'phone', step: 'hum');
      Future<void>.delayed(Duration.zero, () => b.emitCalib({
            ...calibLive('hum', 'step_done', trace: [for (var i = 0; i < 150; i++) 147 + 2 * math.sin(i / 11)], checks: [
              {'id': 'PITCH', 'label': 'PITCH', 'state': 'ok'},
              {'id': 'SHAPE', 'label': 'SHAPE', 'state': 'ok'},
              {'id': 'LENGTH', 'label': 'LENGTH', 'state': 'ok'},
            ]),
            'hub': [for (final s in calibSteps) {'id': s, 'done': s == 'hum', 'result_word': s == 'hum' ? 'ok' : '·'}],
          }));
      return w;
    },
    'calib-off': (tester, b, t) async {
      b.calibRefusal = 'the mic is off (paused): resume Canti first';
      return CalibStepScreen(backend: b, source: 'phone', step: 'hum');
    },
    'take-live': (tester, b, t) async {
      return TrainTakeScreen(backend: b, train: t, gesture: 'arch', cell: 'hum-low-slow');
    },
    'take-pass': (tester, b, t) async {
      return TrainTakeScreen(backend: b, train: t, gesture: 'arch', cell: 'hum-low-slow');
    },
    'take-miss': (tester, b, t) async {
      return TrainTakeScreen(backend: b, train: t, gesture: 'arch', cell: 'hum-low-slow');
    },
    'take-off': (tester, b, t) async {
      t
        ..blocked = 'Canti is in cursor mode: gestures are off.'
        ..blockedAction = 'gesture_mode';
      return TrainTakeScreen(backend: b, train: t, gesture: 'arch', cell: 'hum-low-slow');
    },
    'review': (tester, b, t) async {
      t.unconfirmed
        ..add({'id': 12, 'gesture': 'rise', 'heard': 'arch', 'pos': 4, 'pitch16': fakePitch16('arch'), 'f0_hz': 180, 'dur_ms': 1400})
        ..add({'id': 13, 'gesture': 'fall', 'heard': 'dip', 'pos': 2, 'pitch16': fakePitch16('dip'), 'f0_hz': 180, 'dur_ms': 1400});
      return ReviewScreen(
          backend: b,
          train: t,
          take: TrainUnconfirmed(
              id: 12, gesture: 'rise', heard: 'arch', pos: 4, pitch16: fakePitch16('arch'), f0Hz: 180, durMs: 1400));
    },
  };

  // what to do once the screen is up (the take screens)
  final acts = <String, Future<void> Function(WidgetTester, FakeTrainBackend)>{
    'take-live': (tester, t) async {
      await t.record();
      t.trace(archHz(40), levelDb: -26);
    },
    'take-pass': (tester, t) async {
      await t.record();
      t.trace(archHz(70), levelDb: -26);
      t.finishTake();
    },
    'take-miss': (tester, t) async {
      await t.record();
      t.finishTake(const FakeTake(label: 'dip'));
    },
  };

  for (final brightness in Brightness.values) {
    for (final MapEntry(key: name, value: make) in screens.entries) {
      testWidgets('Z Flip ${brightness.name}: $name', (tester) async {
        const dpr = 2.6, top = 94.0;
        tester.view.devicePixelRatio = dpr;
        tester.view.physicalSize = const Size(1080, 2640);
        tester.view.padding = const FakeViewPadding(top: top);
        tester.view.viewPadding = const FakeViewPadding(top: top);
        addTearDown(tester.view.reset);
        final b = FakeBackend(initial: status(), calibAuto: false);
        final t = trainWithProgress();
        useTrainBackend(b, t);
        final home = await make(tester, b, t);
        await tester.pumpWidget(VoxUiApp(
          backend: b,
          themeMode: brightness == Brightness.dark ? ThemeMode.dark : ThemeMode.light,
          home: home,
        ));
        await tester.pumpAndSettle();
        final act = acts[name];
        if (act != null) {
          await act(tester, t);
          await tester.pump();
        }
        await tester.pump();
        await tester.pump();
        expect(tester.takeException(), isNull);

        final screen = Rect.fromLTWH(0, 0, 1080 / dpr, 2640 / dpr);
        final dock = tester.getRect(find.byType(ActionDock));
        expect(screen.contains(dock.bottomRight - const Offset(1, 1)), isTrue);
        expect(dock.bottom, closeTo(screen.bottom, 1), reason: 'the dock sits at the bottom, no strip under it');
        // the hub scrolls above the dock; the step / take / review screens fill it (their plot grows) — no band for the EQ bars
        final scrollFinder = find.byType(SingleChildScrollView);
        if (scrollFinder.evaluate().isNotEmpty) {
          final scroll = tester.getRect(scrollFinder);
          expect(scroll.bottom, closeTo(dock.top, 0.5));
          expect(scroll.top, greaterThanOrEqualTo(top / dpr));
        }

        final sentences = find.byType(Sentence);
        for (final e in sentences.evaluate()) {
          final r = tester.getRect(find.byWidget(e.widget));
          expect(r.right, lessThanOrEqualTo(screen.right), reason: 'a sentence stays on screen');
        }

        if (shots != null) {
          final img = await captureImage(tester.binding.rootElement!);
          final png = (await tester.runAsync(() => img.toByteData(format: ui.ImageByteFormat.png)))!;
          File('$shots/$name-${brightness.name}.png').writeAsBytesSync(png.buffer.asUint8List());
        }
        // end any fake timers (a pass's auto-advance)
        await tester.pumpWidget(const SizedBox());
        await tester.pump(const Duration(seconds: 2));
      });
    }
  }
}
