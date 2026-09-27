import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vox_ui/vox_ui.dart';

/// A first run: the Pico is the source, nothing is remembered, Bluetooth on and permitted.
VoxStatus firstRun([Map<String, Object?> m = const {}]) => VoxStatus.fromMap({
      'service': true, 'armed': false, 'paused': false, 'mode': 'gesture', 'decider': 'rules',
      'sound_source': 'pico', 'ble_adapter': 'on', 'ble_state': 'idle', 'ble_missing': <String>[], ...m,
    });

/// The app opened for the pairing screen (as the badge menu and the source chooser open it).
Future<FakeBackend> pumpPair(WidgetTester tester, VoxStatus initial) async {
  final b = FakeBackend(initial: initial)..pendingRoute = 'pair';
  await tester.pumpWidget(VoxUiApp(backend: b));
  await tester.pumpAndSettle();
  return b;
}

/// Moves the fake's state on and tells the screen (as the service's `ble` events do).
Future<void> advance(WidgetTester tester, FakeBackend b, Map<String, Object?> m) async {
  b.current = firstRun(m);
  b.emit('ble', {'what': 'state'});
  await tester.pumpAndSettle();
}

String pairText(WidgetTester tester) => tester.widget<Text>(find.byKey(const Key('pair_text'))).data!;
String stage(WidgetTester tester, int i) => tester.widget<Text>(find.byKey(Key('stage_$i'))).data!;

void main() {
  test('pairStep follows the status', () {
    expect(pairStep(VoxStatus.offline), PairStep.serviceOff);
    expect(pairStep(firstRun({'sound_source': 'phone'})), PairStep.notPico);
    expect(pairStep(firstRun({'ble_missing': ['android.permission.BLUETOOTH_SCAN']})), PairStep.permissions);
    expect(pairStep(firstRun({'ble_adapter': 'off'})), PairStep.bluetoothOff);
    expect(pairStep(firstRun()), PairStep.ready);
    expect(pairStep(firstRun({'ble_state': 'scanning', 'ble_scan': 'scanning'})), PairStep.scanning);
    expect(pairStep(firstRun({'ble_scan': 'none found'})), PairStep.notFound);
    expect(pairStep(firstRun({'ble_state': 'connecting', 'ble_target_name': 'VOX-2807'})), PairStep.connecting);
    expect(pairStep(firstRun({'ble_state': 'discovering'})), PairStep.connecting);
    expect(pairStep(firstRun({'ble_state': 'bonding'})), PairStep.pairing);
    expect(pairStep(firstRun({'ble_state': 'waiting'})), PairStep.retrying);
    expect(pairStep(firstRun({'ble_state': 'needs_pairing', 'ble_hint': 'Hold the button 5 s'})), PairStep.failed);
    expect(pairStep(firstRun({'ble_state': 'ready', 'device_ready': true, 'ble_device': 'D8:3A:DD:00:00:01'})),
        PairStep.connected);
    // Permissions come before Bluetooth being off (turning it on needs the connect permission).
    expect(pairStep(firstRun({'ble_adapter': 'off', 'ble_missing': ['android.permission.BLUETOOTH_CONNECT']})),
        PairStep.permissions);
    expect(permissionLabel('android.permission.BLUETOOTH_SCAN'), 'Nearby devices (find)');
    expect(permissionLabel('android.permission.ACCESS_FINE_LOCATION'), 'Location (Bluetooth search)');
  });

  test('needsPairing: the Pico with nothing remembered, and only when the service says so', () {
    expect(firstRun().needsPairing, isTrue);
    expect(firstRun({'ble_device': 'D8:3A:DD:00:00:01'}).needsPairing, isFalse);
    expect(firstRun({'sound_source': 'phone'}).needsPairing, isFalse);
    expect(firstRun({'sound_source': null}).needsPairing, isFalse);
  });

  testWidgets('first run: the status screen offers "Find my Canti device", which opens the search', (tester) async {
    final b = FakeBackend(initial: firstRun());
    await tester.pumpWidget(VoxUiApp(backend: b));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('setup_find_device')), findsOneWidget);
    expect(find.text('Find my Canti device'), findsWidgets);
    await tester.tap(find.byKey(const Key('setup_find_device')));
    await tester.pumpAndSettle();
    expect(b.connects, 1); // the search starts at once
    expect(pairText(tester), 'Looking for your Canti device...');
    expect(stage(tester, 0), 'looking...');
    expect(find.byKey(const Key('hold_hint')), findsOneWidget);
  });

  testWidgets('a device with nothing to set up: no setup window', (tester) async {
    await tester.pumpWidget(VoxUiApp(backend: FakeBackend()));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('setup_find_device')), findsNothing);
  });

  testWidgets('the whole flow: scanning, found VOX-xxxx, connecting, pairing, connected', (tester) async {
    final b = await pumpPair(tester, firstRun());
    expect(b.connects, 1);
    expect(pairText(tester), 'Looking for your Canti device...');

    await advance(tester, b, {'ble_state': 'connecting', 'ble_target': 'D8:3A:DD:00:28:07', 'ble_target_name': 'VOX-2807'});
    expect(pairText(tester), 'Found VOX-2807. Connecting...');
    expect(stage(tester, 0), 'done');
    expect(stage(tester, 2), 'connecting...');

    await advance(tester, b, {'ble_state': 'bonding', 'ble_target': 'D8:3A:DD:00:28:07', 'ble_target_name': 'VOX-2807'});
    expect(pairText(tester), contains('Pairing with VOX-2807'));
    expect(stage(tester, 1), 'VOX-2807');
    expect(stage(tester, 3), 'pairing...');

    await advance(tester, b, {
      'ble_state': 'ready', 'device_ready': true, 'ble_device': 'D8:3A:DD:00:28:07', 'ble_target': 'D8:3A:DD:00:28:07',
      'ble_target_name': 'VOX-2807', 'device_state': 'listening', 'device_armed': true, 'armed': true,
    });
    expect(pairText(tester), 'Connected to VOX-2807. Canti hears it now.');
    expect(stage(tester, 4), 'connected');
    expect(find.byKey(const Key('hold_hint')), findsNothing);
    await tester.tap(find.byKey(const Key('pair_done')));
    await tester.pumpAndSettle();
    expect(find.byType(PairScreen), findsNothing);
    expect(b.connects, 1);
  });

  testWidgets('nothing found: says so, and Search again searches', (tester) async {
    final b = await pumpPair(tester, firstRun());
    await advance(tester, b, {'ble_scan': 'none found'});
    expect(pairText(tester), startsWith('No Canti device found.'));
    await tester.tap(find.byKey(const Key('find_device')));
    await tester.pumpAndSettle();
    expect(b.connects, 2);
    expect(pairText(tester), 'Looking for your Canti device...');
  });

  testWidgets('pairing failed: the hint, and Try again', (tester) async {
    final b = await pumpPair(tester, firstRun({'ble_state': 'needs_pairing', 'ble_target_name': 'VOX-2807',
        'ble_hint': 'Hold the VOX button 5 s until the light blinks fast, then connect.'}));
    expect(b.connects, 0); // no automatic retry of a failed pairing
    expect(pairText(tester), 'Hold the VOX button 5 s until the light blinks fast, then connect.');
    expect(find.text('Try again'), findsOneWidget);
  });

  testWidgets('missing permissions: names them; Allow asks, then the search starts', (tester) async {
    final b = await pumpPair(tester,
        firstRun({'ble_missing': ['android.permission.BLUETOOTH_SCAN', 'android.permission.BLUETOOTH_CONNECT']}));
    expect(b.connects, 0);
    expect(pairText(tester), contains('Missing: Nearby devices (find), Nearby devices (connect).'));
    await tester.tap(find.byKey(const Key('allow_bluetooth')));
    await tester.pumpAndSettle();
    expect(b.bluetoothRequests, 1);
    expect(b.connects, 1);
    expect(pairText(tester), 'Looking for your Canti device...');
  });

  testWidgets('permissions refused for good: the app settings button', (tester) async {
    final b = await pumpPair(tester, firstRun({'ble_missing': ['android.permission.BLUETOOTH_SCAN'], 'ble_blocked': true}));
    expect(pairText(tester), contains('Android will not ask again'));
    expect(find.byKey(const Key('allow_bluetooth')), findsNothing);
    await tester.tap(find.byKey(const Key('open_settings')));
    await tester.pumpAndSettle();
    expect(b.appSettingsOpened, 1);
  });

  testWidgets('Bluetooth off: says so, and the button asks to turn it on', (tester) async {
    final b = await pumpPair(tester, firstRun({'ble_adapter': 'off', 'device_state': null}));
    expect(pairText(tester), 'Bluetooth is off. Turn it on to search.');
    await tester.tap(find.byKey(const Key('enable_bluetooth')));
    await tester.pumpAndSettle();
    expect(b.bluetoothEnables, 1);
    expect(b.connects, 0);
  });

  testWidgets('a mic source: explains, no search', (tester) async {
    final b = await pumpPair(tester, firstRun({'sound_source': 'usb'}));
    expect(pairText(tester), contains('USB mic'));
    expect(find.byKey(const Key('find_device')), findsNothing);
    expect(b.connects, 0);
  });

  testWidgets('a route request while running opens the pairing screen once', (tester) async {
    final b = FakeBackend(initial: firstRun({'ble_state': 'needs_pairing', 'ble_hint': 'x'}));
    await tester.pumpWidget(VoxUiApp(backend: b));
    await tester.pumpAndSettle();
    expect(find.byType(PairScreen), findsNothing);
    b.openRoute('pair');
    await tester.pumpAndSettle();
    expect(find.byType(PairScreen), findsOneWidget);
    b.openRoute('pair');
    await tester.pumpAndSettle();
    expect(find.byType(PairScreen), findsOneWidget);
    await tester.tap(find.byKey(const Key('pair_back')));
    await tester.pumpAndSettle();
    expect(find.byType(PairScreen), findsNothing);
  });

  testWidgets('pairing screen: labelled tap targets of Android size', (tester) async {
    final handle = tester.ensureSemantics();
    await pumpPair(tester, firstRun({'ble_missing': ['android.permission.BLUETOOTH_SCAN']}));
    await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
    await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
    handle.dispose();
  });
}
