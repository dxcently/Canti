import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vox_ui/vox_ui.dart';

/// Every recorder screen and both quick record screens on the Z Flip 6 inner screen (1080 x 2640 px at 2.6x, a 94 px
/// status bar) with the real pixel fonts, light and dark: nothing overflows, the cue (the spec's longest included) is
/// whole above the dock, and the dock is on screen. With VOX_SHOTS_DIR set, each screen is also written there as a PNG.
void main() {
  setUpAll(() async {
    for (final (fam, file) in [('PressStart2P', 'PressStart2P-Regular.ttf'), ('Tiny5', 'Tiny5-Regular.ttf')]) {
      final bytes = File('assets/fonts/$file').readAsBytesSync();
      await (FontLoader(fam)..addFont(Future.value(ByteData.sublistView(bytes)))).load();
    }
  });

  final shots = Platform.environment['VOX_SHOTS_DIR'];

  Future<void> run(FakeRecorderBackend r, String state) async {
    for (var i = 0; i < 800 && r.state != state; i++) {
      r.advance(const Duration(milliseconds: 100));
    }
    expect(r.state, state);
  }

  Future<FakeRecorderBackend> started() async {
    final r = FakeRecorderBackend();
    await r.recStart(who: 'me', speaker: 'self', profile: 'short');
    return r;
  }

  Future<void> finish(FakeRecorderBackend r, String first, String block) async {
    await r.recNext(takeId: first);
    for (var i = 0; i < 400 && r.state != 'rate'; i++) {
      if (r.state == 'ready' && r.calls.last != 'rec_go') {
        try {
          await r.recGo();
        } on RecCommandError catch (_) {}
      }
      if (r.state == 'saved') {
        r.advance(const Duration(milliseconds: 1600));
        if (r.state == 'saved') await r.recNext();
      }
      r.advance(const Duration(milliseconds: 100));
    }
    await r.recRate(block: block, rating: 3);
  }

  // name -> (the fake in the state to show, quick record?, what to do on screen first)
  final screens = <String, (Future<FakeRecorderBackend> Function(), bool, Future<void> Function(WidgetTester)?)>{
    '1-start': (() async => FakeRecorderBackend(), false, null),
    '2-blocks': (() async {
      final r = await started();
      await finish(r, 'rise', 'contours');
      return r;
    }, false, null),
    '3-ready': (() async {
      final r = await started();
      await r.recNext(takeId: 'rise');
      return r;
    }, false, null),
    '4-countdown': (() async {
      final r = await started();
      await r.recNext(takeId: 'arch');
      await run(r, 'countdown');
      return r;
    }, false, null),
    '5-recording': (() async {
      final r = await started();
      await r.recNext(takeId: 'rise');
      await run(r, 'recording');
      r.advance(const Duration(milliseconds: 1200));
      return r;
    }, false, null),
    '5b-recording-longest-cue': (() async {
      final r = await started();
      await r.recNext(takeId: 'media-90');
      await r.recGo();
      r.advance(const Duration(milliseconds: 2000));
      return r;
    }, false, null),
    '5c-room': (() async {
      final r = await started();
      await r.recNext(takeId: 'room');
      await run(r, 'recording');
      r.advance(const Duration(milliseconds: 1500));
      return r;
    }, false, null),
    '6-saved-contour': (() async {
      final r = await started();
      await r.recNext(takeId: 'arch');
      await run(r, 'saved');
      return r;
    }, false, null),
    '6b-saved-beat': (() async {
      final r = await started();
      await r.recNext(takeId: 'pop-pop');
      await run(r, 'saved');
      return r;
    }, false, null),
    '6c-no-sound': (() async {
      final r = (await started())..noSoundTakes.add('hiss');
      await r.recNext(takeId: 'hiss');
      await run(r, 'no_sound');
      return r;
    }, false, null),
    '7-rate': (() async {
      final r = await started();
      await r.recNext(takeId: 'room');
      await run(r, 'rate');
      return r;
    }, false, (tester) async {
      await tester.tap(find.byKey(const Key('rec_rate_4')));
    }),
    '8-done': (() async {
      final r = await started();
      await finish(r, 'rise', 'contours');
      await finish(r, 'click', 'discrete');
      await finish(r, 'room', 'room');
      await finish(r, 'media-90', 'backgrounds');
      return r;
    }, false, null),
    'q1-clip': (() async {
      final r = FakeRecorderBackend();
      await r.qrSnap();
      return r;
    }, true, null),
    'q2-labelled': (() async {
      final r = FakeRecorderBackend();
      await r.qrSnap();
      return r;
    }, true, (tester) async {
      final f = find.byKey(const Key('qr_label_arch'));
      await tester.ensureVisible(f);
      await tester.pumpAndSettle();
      await tester.tap(f);
    }),
  };

  for (final brightness in Brightness.values) {
    for (final MapEntry(key: name, value: (make, quick, act)) in screens.entries) {
      testWidgets('Z Flip ${brightness.name}: $name', (tester) async {
        const dpr = 2.6, top = 94.0;
        tester.view.devicePixelRatio = dpr;
        tester.view.physicalSize = const Size(1080, 2640);
        tester.view.padding = const FakeViewPadding(top: top);
        tester.view.viewPadding = const FakeViewPadding(top: top);
        addTearDown(tester.view.reset);
        final r = await make();
        final b = FakeBackend(initial: VoxStatus.fromMap({
          'service': true, 'armed': true, 'paused': false, 'mode': 'gesture', 'app': 'x.y', 'decider': 'rules',
          'sound_source': 'phone', 'dev_recorder': true,
        }));
        useRecorderBackend(b, r);
        await tester.pumpWidget(VoxUiApp(
          backend: b,
          themeMode: brightness == Brightness.dark ? ThemeMode.dark : ThemeMode.light,
          home: quick ? QuickRecScreen(backend: b, recorder: r) : RecorderScreen(backend: b, recorder: r),
        ));
        for (var i = 0; i < 3; i++) {
          await tester.pumpAndSettle();
          await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 100)));
        }
        if (act != null) {
          await act(tester);
          await tester.pumpAndSettle();
          if (quick) Scrollable.of(tester.element(find.byKey(const Key('qr_label')))).position.jumpTo(0);
          await tester.pumpAndSettle();
        }
        expect(tester.takeException(), isNull);

        final screen = Rect.fromLTWH(0, 0, 1080 / dpr, 2640 / dpr);
        final dock = tester.getRect(find.byKey(const Key('dock_main')));
        expect(screen.contains(dock.bottomRight - const Offset(1, 1)), isTrue);
        final cue = find.byKey(const Key('rec_cue'));
        if (cue.evaluate().isNotEmpty) {
          final c = tester.getRect(cue);
          expect(c.top, greaterThanOrEqualTo(top / dpr));
          expect(c.bottom, lessThanOrEqualTo(dock.top), reason: 'the cue is whole above the dock');
          expect(c.right, lessThanOrEqualTo(screen.right));
        }

        if (shots != null) {
          final img = await captureImage(tester.binding.rootElement!);
          final png = (await tester.runAsync(() => img.toByteData(format: ui.ImageByteFormat.png)))!;
          File('$shots/$name-${brightness.name}.png').writeAsBytesSync(png.buffer.asUint8List());
        }
      });
    }
  }
}
