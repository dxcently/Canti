import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vox_ui/src/theme/assets.dart';
import 'package:vox_ui/src/theme/pixel.dart';
import 'package:vox_ui/vox_ui.dart';

/// The brand PNGs are drawn at a whole number of device pixels per dot, from the PNG made for that scale.
void main() {
  test('pick: the biggest PNG whose scale divides the wanted one', () {
    expect(BrandArt.pick(5, 8), (5, 1));
    expect(BrandArt.pick(8, 8), (8, 1));
    expect(BrandArt.pick(10, 8), (5, 2));
    expect(BrandArt.pick(9, 8), (3, 3));
    expect(BrandArt.pick(6, 4), (3, 2));
    expect(BrandArt.pick(11, 8), (1, 11));
    expect(BrandArt.pick(1, 4), (1, 1));
  });

  for (final (dpr, k, n) in [(2.625, 5, 3), (3.0, 6, 3), (1.0, 2, 1), (1.5, 3, 2), (4.0, 8, 4)]) {
    testWidgets('at ${dpr}x: wordmark cells of $k device px, icon dots of $n', (tester) async {
      tester.view.devicePixelRatio = dpr;
      tester.view.physicalSize = const Size(411, 914) * dpr;
      addTearDown(tester.view.reset);
      // the wordmark in the app's header; the icon (not on a screen now) on its own
      await tester.pumpWidget(VoxUiApp(backend: FakeBackend()));
      await tester.pumpAndSettle();
      for (final (name, w, h, s) in [('canti-wordmark', 89, 41, k), ('canti-icon-on', 48, 48, n)]) {
        if (name == 'canti-icon-on') {
          await tester.pumpWidget(MediaQuery(
            data: MediaQueryData(devicePixelRatio: dpr),
            child: PxScope(
              px: Px(dpr),
              child: const Directionality(
                  textDirection: TextDirection.ltr, child: Center(child: BrandArt.icon(on: true))),
            ),
          ));
          await tester.pumpAndSettle();
        }
        final img = find.byWidgetPredicate(
            (x) => x is Image && x.image is ExactAssetImage && (x.image as ExactAssetImage).assetName.endsWith('$name@$s.png'));
        expect(img, findsOneWidget, reason: '$name@$s.png');
        final size = tester.getSize(img);
        // exactly w*s x h*s device pixels, so the PNG is drawn 1:1
        expect(size.width * dpr, moreOrLessEquals(w * s.toDouble(), epsilon: 1e-6));
        expect(size.height * dpr, moreOrLessEquals(h * s.toDouble(), epsilon: 1e-6));
        final x = tester.widget<Image>(img);
        expect(x.filterQuality, FilterQuality.none);
        // painted on the device grid: PixelSnap moves it by under a device pixel at paint time
        RenderObject? a = tester.renderObject(img).parent;
        while (a != null && a is! RenderPixelPaint) {
          a = a.parent;
        }
        final box = a! as RenderPixelPaint;
        expect(box.localToGlobal(Offset.zero), tester.getTopLeft(img));
        final o = (box.localToGlobal(Offset.zero) + pixelSnap(box, dpr)) * dpr;
        expect(o.dx, moreOrLessEquals(o.dx.roundToDouble(), epsilon: 1e-6));
        expect(o.dy, moreOrLessEquals(o.dy.roundToDouble(), epsilon: 1e-6));
      }
    });
  }
}
