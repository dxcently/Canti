import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vox_ui/vox_ui.dart';

Future<FakeBackend> pumpApp(WidgetTester tester, {FakeBackend? backend}) async {
  final b = backend ?? FakeBackend();
  await tester.pumpWidget(VoxUiApp(backend: b));
  await tester.pumpAndSettle();
  return b;
}

/// No VOX device set up: phone-only or debug sources. The main button is the app-side pause.
const phoneOnly = VoxStatus(service: true, armed: true, paused: false, mode: 'gesture', app: 'org.schabi.newpipe', decider: 'rules');

VoxStatus device(Map<String, Object?> m) => VoxStatus.fromMap({
      'service': true, 'armed': true, 'paused': false, 'mode': 'gesture', 'app': 'x.y', 'decider': 'rules',
      'ble_state': 'ready', 'ble_device': 'D8:3A:DD:00:00:01', ...m,
    });

void main() {
  testWidgets('shows the status from the backend', (tester) async {
    await pumpApp(tester);
    expect(find.text('Listening for sounds'), findsOneWidget);
    expect(find.text('running'), findsOneWidget);
    expect(find.text('listening'), findsOneWidget); // the device row
    expect(find.text('gesture'), findsOneWidget);
    expect(find.text('org.schabi.newpipe'), findsOneWidget);
    expect(find.text('ready, D8:3A:DD:00:00:01'), findsOneWidget);
    expect(find.text('Pause VOX'), findsOneWidget);
    expect(find.text('Gesture'), findsOneWidget);
    expect(find.text('Cursor'), findsOneWidget);
    expect(find.text('Sleep device'), findsOneWidget);
    // The fake has no native settings screen.
    expect(find.text('Legacy settings'), findsNothing);
  });

  testWidgets('without a device, pause and resume are the app-side pause', (tester) async {
    final b = await pumpApp(tester, backend: FakeBackend(initial: phoneOnly));
    expect(find.text('armed'), findsOneWidget);
    expect(find.text('Sleep device'), findsNothing);
    expect(find.byKey(const Key('mode')), findsNothing);
    await tester.tap(find.text('Pause VOX'));
    await tester.pumpAndSettle();
    expect(b.current.paused, isTrue);
    expect(find.text('Paused'), findsOneWidget);
    expect(find.text('Resume VOX'), findsOneWidget);
    expect(find.text('pause'), findsOneWidget); // the backend's pause event is in the live list
    await tester.tap(find.text('Resume VOX'));
    await tester.pumpAndSettle();
    expect(b.current.paused, isFalse);
    expect(find.text('Listening for sounds'), findsOneWidget);
    expect(b.commands, isEmpty);
  });

  testWidgets('with a device, the main button pauses and arms the device', (tester) async {
    final b = await pumpApp(tester);
    await tester.tap(find.text('Pause VOX'));
    await tester.pumpAndSettle();
    expect(b.commands, [
      {'v': 1, 'armed': false},
    ]);
    expect(b.current.paused, isFalse); // the device, not the app-side pause
    expect(find.text('Device paused'), findsOneWidget);
    expect(find.text('awake – paused'), findsOneWidget);
    await tester.tap(find.text('Resume VOX'));
    await tester.pumpAndSettle();
    expect(b.commands.last, {'v': 1, 'armed': true});
    expect(find.text('Listening for sounds'), findsOneWidget);
    expect(find.text('listening'), findsOneWidget);
  });

  testWidgets('resume lifts an app-side pause and arms the device', (tester) async {
    final b = await pumpApp(tester,
        backend: FakeBackend(
            initial: device({'armed': false, 'paused': true, 'device_state': 'awake – paused', 'device_ready': true,
                'device_armed': false, 'device_mode': 'gesture'})));
    expect(find.text('Paused'), findsOneWidget);
    await tester.tap(find.text('Resume VOX'));
    await tester.pumpAndSettle();
    expect(b.current.paused, isFalse);
    expect(b.commands, [
      {'v': 1, 'armed': true},
    ]);
    expect(find.text('Listening for sounds'), findsOneWidget);
  });

  testWidgets('the mode toggle and Sleep device command the device; asleep is not an error', (tester) async {
    final b = await pumpApp(tester);
    await tester.tap(find.text('Cursor'));
    await tester.pumpAndSettle();
    expect(b.commands.last, {'v': 1, 'mode': 'cursor'});
    expect(find.text('cursor'), findsOneWidget); // the mode row
    await tester.tap(find.text('Sleep device'));
    await tester.pumpAndSettle();
    expect(b.commands.last, {'v': 1, 'sleep': true});
    expect(find.text('Device asleep'), findsOneWidget);
    expect(find.text('asleep'), findsOneWidget);
    // no device controls while it sleeps, and nothing shown as an error
    expect(find.text('Sleep device'), findsNothing);
    expect(find.byKey(const Key('mode')), findsNothing);
    expect(find.byKey(const Key('ble_hint')), findsNothing);
    expect(find.byKey(const Key('device_error')), findsNothing);
  });

  testWidgets('a device that is asleep (from the service) shows as asleep, not as an error', (tester) async {
    await pumpApp(tester,
        backend: FakeBackend(initial: device({'armed': false, 'ble_state': 'waiting', 'device_state': 'asleep', 'device_ready': false})));
    expect(find.text('Device asleep'), findsOneWidget);
    expect(find.byKey(const Key('ble_hint')), findsNothing);
    expect(find.byKey(const Key('device_error')), findsNothing);
    expect(find.byKey(const Key('connect')), findsNothing);
  });

  testWidgets('a command the device never confirms fails visibly', (tester) async {
    final b = await pumpApp(tester, backend: FakeBackend(confirmDevice: false));
    await tester.tap(find.text('Pause VOX'));
    await tester.pump();
    expect(tester.widget<ButtonStyleButton>(find.byKey(const Key('pause'))).onPressed, isNull); // busy meanwhile
    await tester.pump(const Duration(milliseconds: 1500));
    await tester.pumpAndSettle();
    expect(b.commands, hasLength(1));
    expect(find.text('Pause failed: no confirmation from the device within 1500 ms.'), findsOneWidget);
    expect(find.text('Listening for sounds'), findsOneWidget); // nothing changed
    expect(tester.widget<ButtonStyleButton>(find.byKey(const Key('pause'))).onPressed, isNotNull);
  });

  testWidgets('live events arrive newest first, capped, and refresh the status', (tester) async {
    final b = await pumpApp(tester, backend: FakeBackend(initial: phoneOnly));
    expect(find.text('No events yet.'), findsOneWidget);
    b.emit('msg', {'id': 1, 'source': 'ble', 'sequence': 'rise', 'phrase': null});
    b.emit('decision', {'n': 1, 'action': 'swipe up'});
    await tester.pumpAndSettle();
    final titles = tester.widgetList<ListTile>(find.byType(ListTile)).map((t) => (t.title as Text).data).toList();
    expect(titles, ['decision', 'msg']);
    expect(find.text('id=1  source=ble  sequence=rise'), findsOneWidget); // nulls are left out
    // A disarm from the device: the arm event makes the screen fetch the status again.
    b.current = b.current.copyWith(armed: false);
    b.emit('arm', {'state': 'disarmed', 'by': 'device'});
    await tester.pumpAndSettle();
    expect(find.text('Disarmed by the device'), findsOneWidget);
    for (var i = 0; i < 80; i++) {
      b.emit('msg', {'id': i});
    }
    await tester.pumpAndSettle();
    final list = tester.widget<ListView>(find.byKey(const Key('events')));
    expect((list.childrenDelegate as SliverChildBuilderDelegate).childCount, 50);
  });

  testWidgets('service off: says so and cannot pause', (tester) async {
    await pumpApp(tester, backend: FakeBackend(initial: VoxStatus.offline));
    expect(find.text('Service off'), findsOneWidget);
    expect(tester.widget<ButtonStyleButton>(find.byKey(const Key('pause'))).onPressed, isNull);
  });

  testWidgets('pairing needed: the hint says what to do, and Connect tries again', (tester) async {
    const hint = "If VOX-2807 was re-flashed, forget it in the phone's Bluetooth settings first.\n"
        'Hold the VOX button 5 s until the light blinks fast, then connect.';
    final b = await pumpApp(tester,
        backend: FakeBackend(
            initial: device({'armed': false, 'ble_state': 'needs_pairing', 'ble_hint': hint, 'device_state': 'pairing needed'})));
    expect(find.text('Pairing needed'), findsOneWidget);
    expect(find.text(hint), findsOneWidget);
    expect(find.text('pairing needed'), findsOneWidget);
    expect(find.text('Sleep device'), findsNothing);
    await expectLater(tester, meetsGuideline(textContrastGuideline));
    await tester.tap(find.text('Connect'));
    await tester.pumpAndSettle();
    expect(b.connects, 1);
    expect(find.text(hint), findsNothing);
    expect(find.text('Connecting to the device'), findsOneWidget);
  });

  testWidgets('accessibility: labelled tap targets of Android size, readable contrast', (tester) async {
    final handle = tester.ensureSemantics();
    for (final b in [FakeBackend(), _WithLegacy()]) {
      await pumpApp(tester, backend: b);
      await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
      await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
      await expectLater(tester, meetsGuideline(textContrastGuideline));
      // The labels Android will see on the controls (Targets.kt reads them as button labels).
      expect(tester.getSemantics(find.byKey(const Key('pause'))),
          matchesSemantics(label: 'Pause VOX', isButton: true, hasTapAction: true, isEnabled: true,
              hasEnabledState: true, isFocusable: true, hasFocusAction: true));
      expect(tester.getSemantics(find.byKey(const Key('refresh'))),
          matchesSemantics(tooltip: 'Refresh status', isButton: true, hasTapAction: true, isEnabled: true,
              hasEnabledState: true, isFocusable: true, hasFocusAction: true));
      expect(tester.getSemantics(find.byKey(const Key('sleep'))),
          matchesSemantics(label: 'Sleep device', isButton: true, hasTapAction: true, isEnabled: true,
              hasEnabledState: true, isFocusable: true, hasFocusAction: true));
      for (final seg in ['Gesture', 'Cursor']) {
        expect(tester.getSemantics(find.text(seg)), isSemantics(label: seg, isButton: true, hasTapAction: true));
      }
    }
    expect(tester.getSemantics(find.byKey(const Key('legacy'))),
        matchesSemantics(label: 'Legacy settings', isButton: true, hasTapAction: true, isEnabled: true,
            hasEnabledState: true, isFocusable: true, hasFocusAction: true));
    handle.dispose();
  });

  testWidgets('dark theme contrast', (tester) async {
    final handle = tester.ensureSemantics();
    tester.platformDispatcher.platformBrightnessTestValue = Brightness.dark;
    addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);
    await pumpApp(tester);
    await expectLater(tester, meetsGuideline(textContrastGuideline));
    handle.dispose();
  });

  testWidgets('legacy settings button calls the backend', (tester) async {
    final b = _WithLegacy();
    await pumpApp(tester, backend: b);
    await tester.tap(find.text('Legacy settings'));
    await tester.pump();
    expect(b.legacyOpened, 1);
  });

  group('ChannelBackend', () {
    const methods = MethodChannel(ChannelBackend.methodsName);
    const events = EventChannel(ChannelBackend.eventsName);
    TestWidgetsFlutterBinding.ensureInitialized();
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    tearDown(() {
      messenger.setMockMethodCallHandler(methods, null);
      messenger.setMockStreamHandler(events, null);
    });

    test('status, setPaused, openLegacySettings and the event stream', () async {
      final calls = <MethodCall>[];
      var paused = false;
      messenger.setMockMethodCallHandler(methods, (call) async {
        calls.add(call);
        if (call.method == 'setPaused') paused = (call.arguments as Map)['paused'] as bool;
        if (call.method == 'openLegacySettings') return null;
        if (call.method == 'deviceCommand') {
          return {'ok': false, 'cmd': 'pause', 'result': 'failed', 'error': 'no confirmation from the device within 1500 ms', 'ms': 1500};
        }
        return {
          'service': true, 'armed': true, 'paused': paused, 'mode': 'cursor', 'app': 'x.y', 'decider': 'rules',
          'ble_state': 'waiting', 'ble_device': null, 'ble_hint': 'forget it', 'vocab': 'abc',
          'device_state': 'awake – paused', 'device_ready': true, 'device_armed': false, 'device_mode': 'cursor',
          'device_waiting': null, 'device_error': 'Pause failed.',
        };
      });
      messenger.setMockStreamHandler(events, MockStreamHandler.inline(onListen: (args, sink) {
        sink.success('{"ev":"arm","t":1234,"state":"disarmed","by":"device"}');
        sink.success('{"ev":"msg","t":1300,"id":7,"phrase":null}');
      }));
      final b = ChannelBackend();
      final s = await b.status();
      expect([s.service, s.armed, s.paused, s.mode, s.app, s.bleState, s.bleDevice, s.bleHint],
          [true, true, false, 'cursor', 'x.y', 'waiting', null, 'forget it']);
      expect([s.deviceState, s.deviceReady, s.deviceArmed, s.deviceMode, s.deviceWaiting, s.deviceError],
          ['awake – paused', true, false, 'cursor', null, 'Pause failed.']);
      expect((await b.setPaused(true)).paused, isTrue);
      expect(calls.last.arguments, {'paused': true});
      final r = await b.deviceCommand(armed: false);
      expect(calls.last.arguments, {'armed': false});
      expect([r.ok, r.result, r.cmd, r.error], [false, 'failed', 'pause', 'no confirmation from the device within 1500 ms']);
      await b.deviceCommand(mode: 'gesture');
      expect(calls.last.arguments, {'mode': 'gesture'});
      await b.deviceCommand(sleep: true);
      expect(calls.last.arguments, {'sleep': true});
      expect((await b.connectDevice()).deviceState, 'awake – paused');
      await b.openLegacySettings();
      expect(calls.map((c) => c.method),
          ['status', 'setPaused', 'deviceCommand', 'deviceCommand', 'deviceCommand', 'connectDevice', 'openLegacySettings']);
      final got = await b.events().take(2).toList();
      expect(got.map((e) => e.name), ['arm', 'msg']);
      expect(got[0].t, 1234);
      expect(got[0].fields, {'state': 'disarmed', 'by': 'device'});
      expect(got[1].summary, 'id=7');
    });

    test('a stopped service answers as offline', () async {
      messenger.setMockMethodCallHandler(methods, (call) async => {'service': false});
      final s = await ChannelBackend().status();
      expect(s.service, isFalse);
      expect(s.active, isFalse);
    });
  });
}

class _WithLegacy extends FakeBackend {
  @override
  bool get hasLegacySettings => true;
}
