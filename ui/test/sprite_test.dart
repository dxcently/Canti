import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vox_ui/src/canti_head.dart';
import 'package:vox_ui/src/theme/assets.dart' show BrandArt;
import 'package:vox_ui/src/theme/pixel.dart' show Px;
import 'package:vox_ui/src/theme/sprite.dart';
import 'package:vox_ui/vox_ui.dart';

/// The header's Canti: the badge manifest (same format and checks as CantiBadgeView.kt), the player (a port of
/// Kotlin's BadgePlayer), and the mapping from the service's state and events.
void main() {
  final json = File('assets/badge/canti_badge.json').readAsStringSync();
  final sprite = BadgeSprite.parse(json);

  // The one copy of the sheet: the Android badge (CantiBadgeView.kt) reads it from the APK's flutter_assets/, so it
  // has to be a declared Flutter asset, and there must be no second copy to drift.
  test('the badge sheet is a declared Flutter asset, and the only copy', () {
    final pubspec = File('pubspec.yaml').readAsLinesSync().map((l) => l.trim());
    expect(pubspec, contains('- assets/badge/'), reason: 'pubspec.yaml must declare assets/badge/');
    for (final f in ['canti_badge.json', 'canti_badge.png']) {
      expect(File('assets/badge/$f').existsSync(), isTrue, reason: f);
    }
    expect(Directory('../android/app/src/main/assets/badge').existsSync(), isFalse,
        reason: 'a second copy under android/: the badge reads flutter_assets/assets/badge');
  });

  test('manifest: every state the header uses is there, frames inside the sheet', () {
    expect(sprite.sheet, 'assets/badge/canti_badge.png');
    for (final s in ['idle', 'hearing', 'pending', 'hold_scroll_up', 'hold_scroll_down', 'cursor', 'paused', 'off',
      'error', 'scroll_up', 'scroll_down', 'back', 'forward', 'home', 'tap_to_wake']) {
      expect(sprite.anims, contains(s));
    }
    expect(() => BadgeSprite.parse(json.replaceFirst('"idle"', '"idle2"')), throwsFormatException);
  });

  test('manifest v2: the pre-load box is the sheet\'s frame, artPxDp is read', () {
    expect((CantiSprite.defaultFrameW, CantiSprite.defaultFrameH), (sprite.frameW, sprite.frameH));
    expect(sprite.artPxDp, greaterThan(0));
    expect(BadgeSprite.parse(json.replaceFirst(RegExp(r'"artPxDp":\s*[0-9.]+,'), '')).artPxDp, 0);
  });

  // The header draws one sheet pixel per kit art pixel (k = round(2 x dpr) device px, whole pixels), never a fraction:
  // the character has to fit beside the wordmark as it is, on narrow and wide phones.
  testWidgets('the header fits the character beside the wordmark on phones', (tester) async {
    for (final (fam, file) in [('PressStart2P', 'PressStart2P-Regular.ttf'), ('Tiny5', 'Tiny5-Regular.ttf')]) {
      final bytes = File('assets/fonts/$file').readAsBytesSync();
      await (FontLoader(fam)..addFont(Future.value(ByteData.sublistView(bytes)))).load();
    }
    for (final (w, dpr) in [(360.0, 3.0), (411.0, 2.625), (360.0, 2.0), (412.0, 3.5)]) {
      tester.view.devicePixelRatio = dpr;
      tester.view.physicalSize = Size(w * dpr, 800 * dpr);
      addTearDown(tester.view.reset);
      await tester.pumpWidget(VoxUiApp(backend: FakeBackend(), key: ValueKey((w, dpr))));
      for (var i = 0; i < 3; i++) {
        await tester.pumpAndSettle();
        await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 100)));
      }
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull, reason: '$w dp at ${dpr}x');
      final k = Px(dpr, TextScaler.noScaling).k;
      final head = tester.getRect(find.byType(CantiSprite));
      expect(head.width * dpr, closeTo(sprite.frameW * k, 0.01), reason: 'whole art px at ${dpr}x');
      expect(head.height * dpr, closeTo(sprite.frameH * k, 0.01));
      final mark = tester.getRect(find.byType(BrandArt));
      final refresh = tester.getRect(find.byKey(const Key('refresh')));
      expect(head.right, lessThanOrEqualTo(mark.left), reason: '$w dp at ${dpr}x');
      expect(mark.right, lessThanOrEqualTo(refresh.left), reason: '$w dp at ${dpr}x: the wordmark runs into refresh');
      expect(refresh.right, lessThanOrEqualTo(w), reason: '$w dp at ${dpr}x');
    }
  });

  test('player: loops, one-shots hand back to the held loop, still frames with reduced motion', () {
    final p = BadgePlayer(sprite);
    final idle = sprite.anims['idle']!;
    expect(p.setHeld('idle', 0), isTrue);
    expect(p.setHeld('idle', 50), isFalse);
    expect(p.frameAt(0), idle.frames[0]);
    expect(p.frameAt(idle.ms[0]), idle.frames[1]);
    expect(p.frameAt(idle.totalMs), idle.frames[0]); // looped
    expect(p.nextChangeIn(10), idle.ms[0] - 10);

    final back = sprite.anims['back']!;
    p.playOnce('back', 1000);
    expect(p.showing, 'back');
    expect(p.frameAt(1000), back.frames[0]);
    expect(p.frameAt(1000 + back.totalMs), idle.frames[0]); // back to idle, its loop restarted
    expect(p.showing, 'idle');

    // hold-scroll plays the direction of the last scroll one-shot
    p.playOnce('scroll-down', 5000);
    p.frameAt(9000);
    p.setHeld('hold-scroll', 9000);
    expect(p.frameAt(9000), sprite.anims['hold_scroll_down']!.frames[0]);

    p.reduceMotion = true;
    p.setHeld('paused', 10000);
    final paused = sprite.anims['paused']!;
    expect(p.frameAt(10000 + paused.ms[0] + 1), paused.frames[paused.still]);
    expect(p.nextChangeIn(10001), -1);

    // unknown states play idle
    p.setHeld('dancing', 11000);
    expect(p.frameAt(11000), idle.frames[idle.still]);

    // tap-to-wake (the service's label) has its own loop; reduced motion shows its still frame, TAP
    final wake = sprite.anims['tap_to_wake']!;
    p.setHeld('tap-to-wake', 12000);
    expect(p.frameAt(12000), wake.frames[wake.still]);
    expect(wake.frames.any(paused.frames.contains), isFalse);
  });

  test('held state: the service\'s badge state, else from the status', () {
    const base = VoxStatus(service: true, armed: true, paused: false, mode: 'gesture');
    expect(CantiHead.heldFor(null), 'off');
    expect(CantiHead.heldFor(VoxStatus.offline), 'off');
    expect(CantiHead.heldFor(VoxStatus.fromMap({'service': true, 'armed': true, 'badge': 'pending'})), 'pending');
    expect(CantiHead.heldFor(base), 'idle');
    expect(CantiHead.heldFor(base.copyWith(paused: true)), 'paused');
    expect(CantiHead.heldFor(base.copyWith(armed: false)), 'paused');
    expect(CantiHead.heldFor(base.copyWith(mode: 'cursor')), 'cursor');
    expect(CantiHead.heldFor(base.copyWith(deviceState: () => 'asleep')), 'off');
    expect(CantiHead.heldFor(base.copyWith(deviceError: () => 'Pause failed')), 'error');
  });

  test('one-shots: executed actions, like BadgeStates.forAction', () {
    expect(CantiHead.oneShotFor('swipe_up', true), 'scroll_up');
    expect(CantiHead.oneShotFor('swipe down', true), 'scroll_down');
    expect(CantiHead.oneShotFor('back', true), 'back');
    expect(CantiHead.oneShotFor('home', true), 'home');
    expect(CantiHead.oneShotFor('tap', true), isNull);
    expect(CantiHead.oneShotFor('back', false), 'error');
    expect(CantiHead.oneShotFor('none', true), 'ignored');
    expect(CantiHead.oneShotFor('none', false), 'ignored');
  });

  test('a sound that did nothing shrugs (ignored_once), at most once per 2.5 s, dropped not queued', () {
    final a = sprite.anims['ignored_once']!;
    expect(a.loop, isFalse);
    expect(a.totalMs, inInclusiveRange(400, 500));
    expect(a.frames.length, inInclusiveRange(4, 5));
    expect(a.frames.where(sprite.anims['hearing']!.frames.contains), isEmpty, reason: 'nothing like hearing');
    final p = BadgePlayer(sprite)..setHeld('idle', 0);
    p.playOnce('ignored', 1000);
    expect(p.showing, 'ignored');
    expect(p.frameAt(1000 + a.ms[0]), a.frames[1]);
    p.frameAt(1000 + a.totalMs);
    expect(p.showing, 'idle');

    expect(OneShots.ignoredGapMs, 2500);
    final s = OneShots();
    expect(s.next('none', true, 10000), 'ignored');
    expect(s.next('none', true, 10001), isNull);
    expect(s.next('swipe_up', true, 10002), 'scroll_up', reason: 'actions are never limited');
    expect(s.next('none', true, 12499), isNull);
    expect(s.next('none', true, 12500), 'ignored');
    // a sound every 500 ms for 10 s (a video playing): 4 shrugs, 2.5 s apart
    final v = OneShots();
    expect([for (var t = 0; t < 10000; t += 500) if (v.next('none', true, t) != null) t], [0, 2500, 5000, 7500]);
  });
}
