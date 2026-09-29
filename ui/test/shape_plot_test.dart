import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vox_ui/src/theme/pixel.dart' show PixelGlyph;
import 'package:vox_ui/vox_ui.dart';

Future<void> pumpPlot(WidgetTester tester, Widget child) async {
  tester.view.physicalSize = const Size(360, 780);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    VoxUiApp(
      backend: FakeBackend(),
      home: Scaffold(body: SingleChildScrollView(padding: const EdgeInsets.all(8), child: child)),
    ),
  );
}

void main() {
  group('ExpectedShape.example', () {
    const shape = ExpectedShape(sequence: ['rise'], spanSt: 4, tolSt: 1.5);
    test('rise goes 0 -> +span', () {
      final e = const ExpectedShape(sequence: ['rise']).example();
      expect(e.length, 17);
      expect(e.first, 0);
      expect(e.last, 4);
      expect(e[8], closeTo(2, 1e-9));
    });
    test('fall goes 0 -> -span', () {
      final e = const ExpectedShape(sequence: ['fall']).example();
      expect(e.first, 0);
      expect(e.last, -4);
    });
    test('arch peaks at +span halfway', () {
      final e = const ExpectedShape(sequence: ['arch']).example();
      expect(e.first, 0);
      expect(e.last, closeTo(0, 1e-9));
      expect(e[8], closeTo(4, 1e-9));
    });
    test('dip peaks at -span halfway', () {
      final e = const ExpectedShape(sequence: ['dip']).example();
      expect(e[8], closeTo(-4, 1e-9));
    });
    test('flat is all zero', () {
      expect(const ExpectedShape(sequence: ['flat']).example(), everyElement(0));
    });
    test('bandAt is example ± tol', () {
      final (lo, hi) = shape.bandAt(1);
      expect(lo, closeTo(4 - 1.5, 1e-9));
      expect(hi, closeTo(4 + 1.5, 1e-9));
      final (lo0, hi0) = shape.bandAt(0);
      expect(lo0, closeTo(-1.5, 1e-9));
      expect(hi0, closeTo(1.5, 1e-9));
    });
  });

  group('pure helpers', () {
    test('pitch16ToHz and hzToSt round trip', () {
      final hz = pitch16ToHz([0, 12, -12], 100);
      expect(hz[0], closeTo(100, 1e-6));
      expect(hz[1], closeTo(200, 1e-6));
      expect(hz[2], closeTo(50, 1e-6));
      expect(hzToSt(200, 100), closeTo(12, 1e-9));
      expect(hzToSt(50, 100), closeTo(-12, 1e-9));
    });
  });

  group('ExpectedShape.forTake', () {
    const defaults = {
      'speed_s': {'slow': 1.2, 'normal': 0.6, 'quick': 0.3},
      'gap_s': {'quick': 0.15, 'normal': 0.35, 'slow': 0.8},
    };
    test('maps bottom/home/top to low/home/high', () {
      expect(ExpectedShape.forTake(expect: ['rise'], cond: {'pitch': 'bottom'}, defaults: defaults).start, 'low');
      expect(ExpectedShape.forTake(expect: ['rise'], cond: {'pitch': 'home'}, defaults: defaults).start, 'home');
      expect(ExpectedShape.forTake(expect: ['rise'], cond: {'pitch': 'top'}, defaults: defaults).start, 'high');
      expect(ExpectedShape.forTake(expect: ['rise'], cond: {'pitch': 'na'}, defaults: defaults).start, 'none');
    });
    test('speed_s and gap_s from defaults', () {
      final slow = ExpectedShape.forTake(expect: ['rise'], cond: {'pitch': 'home', 'speed': 'slow'}, defaults: defaults);
      expect(slow.durS, 1.2);
      final combo =
          ExpectedShape.forTake(expect: ['click', 'click'], cond: {'gap': 'slow'}, defaults: defaults);
      expect(combo.gapS, 0.8);
      final normal = ExpectedShape.forTake(expect: ['rise'], cond: {'pitch': 'home', 'speed': 'na'}, defaults: defaults);
      expect(normal.durS, 0.6); // the default when not named
    });
  });

  group('ExpectedShape.fromMap', () {
    test('parses E9 expect map', () {
      final e = ExpectedShape.fromMap({
        'sequence': ['arch'],
        'start': 'high',
        'span_st': 5,
        'tol_st': 2,
        'dur_s': 0.8,
        'gap_s': 0.4,
      });
      expect(e.sequence, ['arch']);
      expect(e.start, 'high');
      expect(e.spanSt, 5);
      expect(e.tolSt, 2);
      expect(e.durS, 0.8);
      expect(e.gapS, 0.4);
      expect(e.contour, isTrue);
    });
  });

  group('ShapePlot renders without overflow', () {
    testWidgets('contour, absolute scale', (tester) async {
      const scale = PitchScale(lowHz: 96, homeHz: 142, highHz: 318);
      expect(scale.absolute, isTrue);
      await pumpPlot(
        tester,
        const ShapePlot(
          expected: ExpectedShape(sequence: ['rise'], start: 'home'),
          scale: scale,
          heard: [HeardSound(label: 'rise', relMs: 100, durMs: 600, pitch16: [0, 1, 2, 3, 4], f0Hz: 142)],
        ),
      );
      expect(tester.takeException(), isNull);
      expect(find.byKey(const Key('shape_plot_contour')), findsOneWidget);
    });

    testWidgets('contour, relative fallback', (tester) async {
      await pumpPlot(
        tester,
        const ShapePlot(
          expected: ExpectedShape(sequence: ['arch']),
          heard: [HeardSound(label: 'arch', relMs: 100, durMs: 600, pitch16: [0, 2, 4, 2, 0], f0Hz: 142)],
        ),
      );
      expect(tester.takeException(), isNull);
      expect(find.byKey(const Key('shape_plot_contour')), findsOneWidget);
    });

    testWidgets('beat strip', (tester) async {
      await pumpPlot(
        tester,
        const ShapePlot(
          expected: ExpectedShape(sequence: ['click', 'click'], gapS: 0.35),
          heard: [HeardSound(label: 'click', relMs: 50, durMs: 150)],
        ),
      );
      expect(tester.takeException(), isNull);
      expect(find.byKey(const Key('shape_plot_beat')), findsOneWidget);
    });

    testWidgets('check chips text', (tester) async {
      await pumpPlot(
        tester,
        const ShapePlot(
          expected: ExpectedShape(sequence: ['rise']),
          checks: [
            ShapeCheck('pitch', 'pitch', CheckState.ok),
            ShapeCheck('shape', 'shape', CheckState.near),
            ShapeCheck('length', 'length', CheckState.miss),
            ShapeCheck('tone', 'tone', CheckState.pending),
          ],
        ),
      );
      // the marks are bitmaps and plain ~ / · (neither pixel face has ✓ or ✗)
      expect(find.byKey(const Key('check_pitch_ok')), findsOneWidget);
      expect(find.byKey(const Key('check_shape_near')), findsOneWidget);
      expect(find.byKey(const Key('check_length_miss')), findsOneWidget);
      expect(find.byKey(const Key('check_tone_pending')), findsOneWidget);
      expect(find.text('PITCH'), findsOneWidget);
      expect(find.textContaining('✓'), findsNothing);
      expect(find.textContaining('✗'), findsNothing);
      expect(find.descendant(of: find.byKey(const Key('check_pitch_ok')), matching: find.byType(PixelGlyph)), findsOneWidget);
    });
  });

  group('ShapePlot timing', () {
    testWidgets('rel_ms is milliseconds: a sound 300 ms in lands inside the strip', (tester) async {
      await pumpPlot(
        tester,
        const ShapePlot(
          expected: ExpectedShape(sequence: ['click']),
          heard: [HeardSound(label: 'click', relMs: 300, durMs: 120)],
        ),
      );
      final strip = tester.getRect(find.byKey(const Key('shape_plot_beat')));
      final you = tester.getRect(find.byKey(const Key('beat_you_0')));
      expect(you.left, greaterThan(strip.left));
      expect(you.left, lessThan(strip.center.dx)); // 0.3 s of a ~1 s strip
    });

    testWidgets('alignToHeard starts the first sound where the example starts; the gap is kept', (tester) async {
      Future<(double, double)> lefts(bool align) async {
        await pumpPlot(
          tester,
          ShapePlot(
            key: ValueKey(align),
            expected: const ExpectedShape(sequence: ['pop', 'pop'], gapS: 0.35),
            heard: const [HeardSound(label: 'pop', relMs: 450, durMs: 90), HeardSound(label: 'pop', relMs: 830, durMs: 90)],
            alignToHeard: align,
          ),
        );
        return (
          tester.getRect(find.byKey(const Key('beat_you_0'))).left,
          tester.getRect(find.byKey(const Key('beat_you_1'))).left,
        );
      }

      final (a0, a1) = await lefts(true);
      final (r0, r1) = await lefts(false);
      expect(a0, lessThan(r0));
      final strip = tester.getRect(find.byKey(const Key('shape_plot_beat')));
      expect(a0 - strip.left, 80); // t = 0: past the 40-art-px lane labels (2 dp per art px at 1x)
      expect(a1 - a0, closeTo(r1 - r0, 1.5));
    });

    testWidgets('a single sound: one example box, no overflow in a ~180 dp mini plot', (tester) async {
      await pumpPlot(
        tester,
        const SizedBox(
          width: 180,
          child: ShapePlot(
            expected: ExpectedShape(sequence: ['hiss']),
            heard: [HeardSound(label: 'hiss', relMs: 0, durMs: 200)],
            height: 40,
            checks: [ShapeCheck('shape', 'shape', CheckState.ok), ShapeCheck('length', 'length', CheckState.miss)],
          ),
        ),
      );
      expect(tester.takeException(), isNull);
      await pumpPlot(
        tester,
        const SizedBox(
          width: 180,
          child: ShapePlot(
            expected: ExpectedShape(sequence: ['rise'], durS: 1.2),
            heard: [HeardSound(label: 'rise', relMs: 0, durMs: 1200, pitch16: [0, 1, 2, 3, 4], f0Hz: 142)],
            height: 40,
          ),
        ),
      );
      expect(tester.takeException(), isNull);
    });

    test('forTake: target_s overrides the speed length', () {
      final e = ExpectedShape.forTake(
        expect: ['arch'],
        cond: {'pitch': 'home', 'speed': 'quick'},
        defaults: {'speed_s': {'quick': 0.3}},
        targetS: 0.45,
      );
      expect(e.durS, 0.45);
    });

    test('HeardSound.at moves only the time', () {
      const h = HeardSound(label: 'rise', relMs: 450, durMs: 600, pitch16: [0, 1], f0Hz: 142, didText: 'x');
      final m = h.at(0);
      expect(m.relMs, 0);
      expect((m.label, m.durMs, m.pitch16, m.f0Hz, m.didText), (h.label, h.durMs, h.pitch16, h.f0Hz, h.didText));
    });
  });
}
