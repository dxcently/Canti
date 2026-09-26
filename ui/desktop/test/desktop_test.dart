import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vox_ui/vox_ui.dart';

void main() {
  testWidgets('the desktop runner shows the status screen with demo events', (tester) async {
    // The runner's default window (linux/runner/my_application.cc).
    tester.view.physicalSize = const Size(420, 820);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final b = FakeBackend(demo: true, demoEvery: const Duration(milliseconds: 100));
    await tester.pumpWidget(VoxUiApp(backend: b));
    await tester.pump();
    expect(find.text('Listening for sounds'), findsOneWidget);
    await tester.pump(const Duration(milliseconds: 150));
    await tester.pump();
    expect(find.text('msg'), findsOneWidget);
    expect(find.text('decision'), findsOneWidget);
    b.dispose();
  });
}
