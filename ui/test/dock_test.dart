import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vox_ui/vox_ui.dart';

Future<void> _pump(WidgetTester tester, Widget dock) async {
  tester.view.physicalSize = const Size(360, 780);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    VoxUiApp(
      backend: FakeBackend(),
      home: Scaffold(body: Column(children: [const Expanded(child: SizedBox()), dock])),
    ),
  );
}

void main() {
  testWidgets('layout is identical with null left/right', (tester) async {
    var taps = 0;
    await _pump(tester, ActionDock(main: DockAction('GO', () => taps++)));
    expect(find.byKey(const Key('dock_left')), findsOneWidget);
    expect(find.byKey(const Key('dock_right')), findsOneWidget);
    expect(find.byKey(const Key('dock_main')), findsOneWidget);
    await tester.tap(find.byKey(const Key('dock_main')));
    await tester.pump();
    expect(taps, 1);
  });

  testWidgets('a disabled main does nothing', (tester) async {
    var taps = 0;
    await _pump(tester, ActionDock(main: DockAction('GO', () => taps++, enabled: false)));
    await tester.tap(find.byKey(const Key('dock_main')));
    await tester.pump();
    expect(taps, 0);
  });

  testWidgets('caption and both small buttons render', (tester) async {
    var left = 0, right = 0, main = 0;
    await _pump(
      tester,
      ActionDock(
        caption: 'refused',
        left: DockAction('A', () => left++),
        right: DockAction('B', () => right++),
        main: DockAction('GO', () => main++),
      ),
    );
    expect(find.text('refused'), findsOneWidget);
    expect(find.text('A'), findsOneWidget);
    expect(find.text('B'), findsOneWidget);
    expect(find.text('GO'), findsOneWidget);
    await tester.tap(find.byKey(const Key('dock_left')));
    await tester.tap(find.byKey(const Key('dock_right')));
    await tester.pump();
    expect(left, 1);
    expect(right, 1);
    expect(main, 0);
  });

  testWidgets('the buttons sit in the same place with or without left/right and a caption', (tester) async {
    Future<List<Rect>> rects(ActionDock d) async {
      await _pump(tester, d);
      await tester.pumpAndSettle();
      return [for (final k in const ['dock_left', 'dock_right', 'dock_main']) tester.getRect(find.byKey(Key(k)))];
    }

    final bare = await rects(ActionDock(main: DockAction('GO', () {})));
    final full = await rects(ActionDock(
      caption: 'a caption that is long enough to wrap onto a second line at this width, maybe',
      left: DockAction('REDO LAST', () {}),
      right: DockAction('SKIP', () {}),
      main: DockAction('A VERY LONG MAIN BUTTON LABEL THAT DOES NOT FIT', () {}),
    ));
    expect(full, bare);
    expect(tester.takeException(), isNull);
    for (final r in full) {
      expect(r.height, greaterThanOrEqualTo(48)); // touch targets
    }
    expect(find.byKey(const Key('dock_caption')), findsOneWidget);
  });
}