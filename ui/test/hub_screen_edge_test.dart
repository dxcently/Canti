import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vox_ui/vox_ui.dart';

/// The step / take / review screens on a small phone (360x740 dp) and rotated (the Z Flip's 1015x415 dp landscape):
/// the plot grows to fill (no scrolling) at 360x740, and nothing overflows on rotation. Runs with the real pixel fonts
/// so the sentence wraps as it will on a device.
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

  const scale = {'low_hz': 110.0, 'home_hz': 147.0, 'high_hz': 262.0};

  VoxStatus status([Map<String, Object?> m = const {}]) => VoxStatus.fromMap({
        'service': true, 'armed': true, 'paused': false, 'mode': 'gesture', 'app': 'x.y', 'decider': 'rules',
        'sound_source': 'phone', ...m,
      });

  FakeTrainBackend train() => FakeTrainBackend(source: 'phone')..scale = scale;

  // name -> the screen (built on the backend/train the test pumps, so the controllers are live)
  final screens = <String, Widget Function(FakeBackend b, FakeTrainBackend t)>{
    'calib step (glide)': (b, t) => CalibStepScreen(backend: b, source: 'phone', step: 'glide'),
    'take (arch)': (b, t) => TrainTakeScreen(backend: b, train: t, gesture: 'arch', cell: 'hum-low-slow'),
    'review': (b, t) => ReviewScreen(
        backend: b,
        train: t,
        take: const TrainUnconfirmed(
            id: 7, gesture: 'rise', heard: 'arch', pos: 1, pitch16: [0.0, 1.0, 2.0, 3.0], f0Hz: 180, durMs: 1400)),
  };

  Future<FakeBackend> pump(WidgetTester tester, Size logical, double dpr, String name) async {
    tester.view.devicePixelRatio = dpr;
    tester.view.physicalSize = logical * dpr;
    addTearDown(tester.view.reset);
    final b = FakeBackend(initial: status(), calibAuto: false);
    final t = train();
    useTrainBackend(b, t);
    await tester.pumpWidget(VoxUiApp(backend: b, home: screens[name]!(b, t)));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull, reason: 'nothing overflows');
    return b;
  }

  for (final MapEntry(key: name) in screens.entries) {
    testWidgets('$name fits at 360x740 dp with no scrolling', (tester) async {
      await pump(tester, const Size(360, 740), 2.0, name);
      expect(find.byType(SingleChildScrollView), findsNothing,
          reason: 'the graph fills the space at 360x740 dp, so there is no scroll view');
      // the plot actually grew: each is taller than its old fixed 84 art px (=168 dp at 2x)
      for (final plot in find.byType(ShapePlot).evaluate()) {
        expect(tester.getRect(find.byWidget(plot.widget)).height, greaterThan(168),
            reason: 'the plot fills the space above the dock');
      }
    });

    testWidgets('$name fits rotated to the Z Flip landscape (1015x415 dp)', (tester) async {
      await pump(tester, const Size(1015, 415), 2.6, name);
    });
  }
}
