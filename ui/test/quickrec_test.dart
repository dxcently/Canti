import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vox_ui/vox_ui.dart';

VoxStatus _status() => VoxStatus.fromMap({
      'service': true, 'armed': true, 'paused': false, 'mode': 'gesture', 'app': 'x.y', 'decider': 'rules',
      'sound_source': 'phone', 'dev_recorder': true,
    });

/// Quick record pushed over a page with an "open" button (so back and SAVE can pop it).
Future<FakeRecorderBackend> _pump(WidgetTester tester, FakeRecorderBackend r, {bool snap = false}) async {
  tester.view.physicalSize = const Size(1080, 2640);
  tester.view.devicePixelRatio = 2.6;
  addTearDown(tester.view.reset);
  final b = FakeBackend(initial: _status());
  useRecorderBackend(b, r);
  await tester.pumpWidget(VoxUiApp(
    backend: b,
    home: Builder(
      builder: (context) => Scaffold(
        body: Center(
          child: TextButton(
            key: const Key('open'),
            onPressed: () => openQuickRec(context, b, recorder: r, snap: snap),
            child: const Text('open'),
          ),
        ),
      ),
    ),
  ));
  await tester.tap(find.byKey(const Key('open')));
  await tester.pumpAndSettle();
  return r;
}

FilledButton _save(WidgetTester tester) => tester.widget<FilledButton>(find.byKey(const Key('dock_main')));

int _count(FakeRecorderBackend r, String c) => r.calls.where((x) => x == c).length;

Future<void> _tapIn(WidgetTester tester, Finder f) async {
  await tester.ensureVisible(f);
  await tester.pumpAndSettle();
  await tester.tap(f);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('from the badge: the pending snapshot is shown, not a new one', (tester) async {
    final r = FakeRecorderBackend();
    await r.qrSnap(); // the badge already snapped
    await _pump(tester, r);
    expect(find.byKey(const Key('qr_clip')), findsOneWidget);
    expect(find.byKey(const Key('qr_bars')), findsOneWidget);
    expect(find.text('last 12 s'), findsOneWidget);
    expect(_count(r, 'qr_pending'), 1);
    expect(_count(r, 'qr_snap'), 1);
  });

  testWidgets('from the status screen: a fresh snapshot (a stale pending one is not reused)', (tester) async {
    final r = FakeRecorderBackend();
    await r.qrSnap(); // an old one
    await _pump(tester, r, snap: true);
    expect(_count(r, 'qr_pending'), 0);
    expect(_count(r, 'qr_snap'), 2);
  });

  testWidgets('what Canti heard and did: every sound with its action, the misfire picked, its shape', (tester) async {
    final r = FakeRecorderBackend();
    await _pump(tester, r, snap: true);
    expect(find.textContaining('HISS → back'), findsOneWidget);
    expect(find.textContaining('ignored: below level gate'), findsOneWidget);
    // the last sound Canti acted on is picked (the dip that swiped left), not the ignored click
    expect(tester.widget<Text>(find.byKey(const Key('qr_heard'))).data, 'Canti heard DIP → swipe left, 5.5 s ago.');
    expect(find.byKey(const Key('qr_shape')), findsOneWidget);
    expect(find.descendant(of: find.byKey(const Key('qr_shape')), matching: find.byKey(const Key('shape_plot_contour'))),
        findsOneWidget);
    // tap another sound
    await _tapIn(tester, find.byKey(const Key('qr_sound_0')));
    expect(tester.widget<Text>(find.byKey(const Key('qr_heard'))).data, contains('HISS'));
    expect(find.descendant(of: find.byKey(const Key('qr_shape')), matching: find.byKey(const Key('shape_plot_beat'))),
        findsOneWidget);
    // the label picked sets the wanted shape: "arch" draws an arch contour for the heard dip
    await _tapIn(tester, find.byKey(const Key('qr_sound_1')));
    await _tapIn(tester, find.byKey(const Key('qr_label_arch')));
    expect(find.descendant(of: find.byKey(const Key('qr_shape')), matching: find.byKey(const Key('shape_plot_contour'))),
        findsOneWidget);
  });

  testWidgets('SAVE is disabled until a label is picked; it saves the picked sound and leaves', (tester) async {
    final r = FakeRecorderBackend();
    await _pump(tester, r, snap: true);
    expect(_save(tester).onPressed, isNull);
    expect(find.text('Pick what it really was, then SAVE.'), findsOneWidget);
    await _tapIn(tester, find.byKey(const Key('qr_label_pop_pop')));
    expect(_save(tester).onPressed, isNotNull);
    await tester.tap(find.byKey(const Key('dock_main')));
    await tester.pumpAndSettle();
    expect(_count(r, 'qr_save pop pop'), 1);
    expect(_count(r, 'qr_discard'), 0);
    expect(find.byKey(const Key('open')), findsOneWidget);
  });

  testWidgets('"misfire / other" sends "misfire"', (tester) async {
    final r = FakeRecorderBackend();
    await _pump(tester, r, snap: true);
    await _tapIn(tester, find.byKey(const Key('qr_label_misfire')));
    await tester.tap(find.byKey(const Key('dock_main')));
    await tester.pumpAndSettle();
    expect(_count(r, 'qr_save misfire'), 1);
  });

  testWidgets('AGAIN discards and snaps anew', (tester) async {
    final r = FakeRecorderBackend();
    await _pump(tester, r, snap: true);
    await tester.tap(find.byKey(const Key('dock_right'))); // AGAIN
    await tester.pumpAndSettle();
    expect(_count(r, 'qr_discard'), 1);
    expect(_count(r, 'qr_snap'), 2);
    expect(find.byKey(const Key('qr_clip')), findsOneWidget);
  });

  testWidgets('DISCARD and system back drop the snapshot once and leave', (tester) async {
    final r = FakeRecorderBackend();
    await _pump(tester, r, snap: true);
    await tester.tap(find.byKey(const Key('dock_left'))); // DISCARD
    await tester.pumpAndSettle();
    expect(_count(r, 'qr_discard'), 1);
    expect(find.byKey(const Key('open')), findsOneWidget);

    await tester.tap(find.byKey(const Key('open')));
    await tester.pumpAndSettle();
    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(_count(r, 'qr_discard'), 2);
    expect(find.byKey(const Key('open')), findsOneWidget);
  });
}
