import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vox_ui/src/theme/assets.dart';
import 'package:vox_ui/src/theme/clearing.dart';
import 'package:vox_ui/src/theme/kit.dart' show PixelWindow;
import 'package:vox_ui/src/theme/sprite.dart' show CantiSprite;
import 'package:vox_ui/vox_ui.dart';

/// The clearings in the dot field, rendered for real (shader and all) on a Z Flip-sized screen (1080 x 2640 px at
/// 2.625x, a 94 px status bar): the header's clearing is made of whole cells of the field's grid, even with the page
/// scrolled by a fraction of a pixel, the subtitle has clear paper under it, and the status bar is clear.
void main() {
  setUpAll(() async {
    for (final (fam, file) in [('PressStart2P', 'PressStart2P-Regular.ttf'), ('Tiny5', 'Tiny5-Regular.ttf')]) {
      final bytes = File('assets/fonts/$file').readAsBytesSync();
      await (FontLoader(fam)..addFont(Future.value(ByteData.sublistView(bytes)))).load();
    }
  });

  test('bayer4 is the 4x4 Bayer matrix (each threshold once per 4x4 block)', () {
    for (final (ox, oy) in [(0, 0), (4, 8), (-4, -4)]) {
      final seen = {
        for (var y = 0; y < 4; y++)
          for (var x = 0; x < 4; x++) (bayer4(ox + x, oy + y) * 16).round(),
      };
      expect(seen, {for (var i = 0; i < 16; i++) i});
    }
    // the ramp: all clear inside, untouched beyond, a checker's worth kept at its end
    expect(clearedAt(0, 0, 2, 3, 6), isTrue);
    expect(clearedAt(0, 0, 9, 3, 6), isFalse);
  });

  // One test for both themes: the sheet, the shape and the shader load once per run (static futures), in the first
  // test's zone.
  testWidgets('header clearing on whole cells, light and dark', (tester) async {
    for (final brightness in Brightness.values) {
      const dpr = 2.625, top = 94.0, cellPx = 10; // k = 5 device px per art px; a cell is 2 art px
      tester.view.devicePixelRatio = dpr;
      tester.view.physicalSize = const Size(1080, 2640);
      tester.view.padding = const FakeViewPadding(top: top);
      tester.view.viewPadding = const FakeViewPadding(top: top);
      tester.platformDispatcher.platformBrightnessTestValue = brightness;
      addTearDown(() {
        tester.view.reset();
        tester.platformDispatcher.clearPlatformBrightnessTestValue();
      });
      await tester.pumpWidget(VoxUiApp(backend: FakeBackend(), key: ValueKey(brightness)));
      for (var i = 0; i < 3; i++) {
        await tester.pumpAndSettle();
        await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 200)));
      }
      await tester.pumpAndSettle();
      // scrolled by a fraction of a device pixel
      final scroll = Scrollable.of(tester.element(find.byType(DitherClearing)));
      scroll.position.jumpTo(3.3);
      await tester.pumpAndSettle();

      final img = await captureImage(tester.binding.rootElement!);
      final bytes = (await tester.runAsync(() => img.toByteData(format: ui.ImageByteFormat.rawRgba)))!;
      int at(int x, int y) => bytes.getUint32((y * img.width + x) * 4);

      Rect dev(Finder f) {
        final r = tester.getRect(f);
        return Rect.fromLTRB(r.left * dpr, r.top * dpr, r.right * dpr, r.bottom * dpr);
      }

      final inks = [
        dev(find.byType(CantiSprite)),
        dev(find.byType(BrandArt)),
        dev(find.byKey(const Key('refresh'))),
        for (final e in find.byType(PixelWindow).evaluate()) dev(find.byWidget(e.widget)), // not the field
      ];
      final wordmark = inks[1];
      final region = dev(find.byType(DitherClearing)).inflate(12.0 * 5);
      final paper = at(1, 1); // under the status bar: clear
      var cleared = 0, dots = 0;
      for (var cy = (region.top / cellPx).floor(); cy < (region.bottom / cellPx).ceil(); cy++) {
        for (var cx = 0; cx < img.width ~/ cellPx; cx++) {
          final cell = Rect.fromLTWH(cx * cellPx.toDouble(), cy * cellPx.toDouble(), 8, 8);
          if (cell.top < top || inks.any((r) => r.inflate(1).overlaps(cell))) continue;
          final c = at(cx * cellPx, cy * cellPx);
          for (var y = 0; y < 8; y++) {
            for (var x = 0; x < 8; x++) {
              expect(at(cx * cellPx + x, cy * cellPx + y), c, reason: 'cell ($cx, $cy) is split: a partial dot');
            }
          }
          if (c == paper) {
            cleared++;
          } else {
            dots++;
          }
        }
      }
      expect(cleared, greaterThan(100));
      expect(dots, greaterThan(100)); // the field is still there around the clearing

      // clear paper just under the subtitle (its middle third: art rows 38-39 of the 41, below its last ink row), and
      // under the status bar
      for (var x = (wordmark.left + wordmark.width / 3).round(); x < wordmark.right - wordmark.width / 3; x++) {
        for (var y = (wordmark.bottom - 3 * 5).ceil(); y < wordmark.bottom - 5; y++) {
          expect(at(x, y), paper, reason: 'a dot at ($x, $y) under the subtitle');
        }
      }
      for (var y = 0; y < top; y += 3) {
        for (var x = 0; x < img.width; x += 3) {
          expect(at(x, y), paper, reason: 'a dot at ($x, $y) under the status bar');
        }
      }
      expect(tester.takeException(), isNull, reason: brightness.name);
      img.dispose();
    }
  });

  test('a shape\'s distance field: 0 on the ink, about Euclidean off it', () {
    final ink = Uint8List(9 * 9)..[4 * 9 + 4] = 1;
    final s = ClearingShape.fromInk(9, 9, ink);
    expect(s.distance(4.5, 4.5), 0);
    expect(s.distance(7.5, 4.5), closeTo(3, 0.01));
    expect(s.distance(7.5, 8.5), closeTo(5, 0.15));
    expect(s.distance(-100, 0), ClearingShape.far);
  });
}
