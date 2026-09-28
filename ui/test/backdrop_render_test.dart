import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vox_ui/src/theme/canti_theme.dart';
import 'package:vox_ui/src/theme/dither_background.dart';
import 'package:vox_ui/src/theme/pixel.dart';

/// A render smoke test of the background shader (shaders/dither_field.frag) and its uniforms. In a file of its own:
/// the shader program is loaded once per isolate, in the zone of the first test that asks, and later tests' fake
/// async zones never run its callbacks.
void main() {
  testWidgets('the shader draws each motif: bars over ticks, none when off', (tester) async {
    tester.view.devicePixelRatio = 2.625;
    tester.view.physicalSize = const Size(1080, 2400);
    addTearDown(tester.view.reset);
    final mood = BackdropMood();
    final key = GlobalKey();
    await tester.pumpWidget(MaterialApp(
      theme: cantiTheme(Brightness.light, Px(2.625)),
      home: RepaintBoundary(key: key, child: DitherBackground(mood: mood, animate: false)),
    ));
    // the shader loads asynchronously
    for (var i = 0; i < 20 && find.byType(CustomPaint).evaluate().where(_isDither).isEmpty; i++) {
      await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
      await tester.pump();
    }
    expect(find.byType(CustomPaint).evaluate().where(_isDither), isNotEmpty, reason: 'the shader did not load');

    Future<(int, int)> ink() async {
      await tester.pump();
      return (await tester.runAsync(() async {
        final box = key.currentContext!.findRenderObject()! as RenderRepaintBoundary;
        final img = await box.toImage();
        final data = (await img.toByteData(format: ui.ImageByteFormat.rawRgba))!;
        // alpha > 0 in the bottom quarter (the bars) and the top quarter (the field)
        var bottom = 0, top = 0;
        for (var y = 0; y < img.height; y++) {
          for (var x = 0; x < img.width; x++) {
            if (data.getUint8((y * img.width + x) * 4 + 3) == 0) continue;
            if (y > img.height * 3 ~/ 4) bottom++;
            if (y < img.height ~/ 4) top++;
          }
        }
        return (bottom, top);
      }))!;
    }

    final (ticks, fieldOn) = await ink();
    mood.held = 'hearing';
    final (bars, _) = await ink();
    mood.held = 'off';
    final (flat, fieldOff) = await ink();
    expect(ticks, greaterThan(0));
    expect(bars, greaterThan(ticks * 1.5));
    expect(flat, 0); // off: no bars
    expect(fieldOff, lessThan(fieldOn * 0.6)); // off thins the top field out
  });
}

bool _isDither(Element e) => (e.widget as CustomPaint).painter?.runtimeType.toString() == '_DitherPainter';
