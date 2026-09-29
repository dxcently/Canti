import 'dart:convert';
import 'dart:io';

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
    expect(find.text('Pause Canti'), findsOneWidget);
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
    await tester.tap(find.text('Pause Canti'));
    await tester.pumpAndSettle();
    expect(b.current.paused, isTrue);
    expect(find.text('Paused'), findsOneWidget);
    expect(find.text('Resume Canti'), findsOneWidget);
    expect(find.text('pause'), findsOneWidget); // the backend's pause event is in the live list
    await tester.tap(find.text('Resume Canti'));
    await tester.pumpAndSettle();
    expect(b.current.paused, isFalse);
    expect(find.text('Listening for sounds'), findsOneWidget);
    expect(b.commands, isEmpty);
  });

  testWidgets('with a device, the main button pauses and arms the device', (tester) async {
    final b = await pumpApp(tester);
    await tester.tap(find.text('Pause Canti'));
    await tester.pumpAndSettle();
    expect(b.commands, [
      {'v': 1, 'armed': false},
    ]);
    expect(b.current.paused, isFalse); // the device, not the app-side pause
    expect(find.text('Device paused'), findsOneWidget);
    expect(find.text('awake – paused'), findsOneWidget);
    await tester.tap(find.text('Resume Canti'));
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
    await tester.tap(find.text('Resume Canti'));
    await tester.pumpAndSettle();
    expect(b.current.paused, isFalse);
    expect(b.commands, [
      {'v': 1, 'armed': true},
    ]);
    expect(find.text('Listening for sounds'), findsOneWidget);
  });

  testWidgets('the mode toggle and Sleep device command the device; asleep is not an error', (tester) async {
    final b = await pumpApp(tester);
    // the wide layout's left column scrolls; with the 56-art-px badge in the header the controls start near the fold
    await tester.ensureVisible(find.text('Cursor'));
    await tester.tap(find.text('Cursor'));
    await tester.pumpAndSettle();
    expect(b.commands.last, {'v': 1, 'mode': 'cursor'});
    expect(find.text('cursor'), findsOneWidget); // the mode row
    await tester.ensureVisible(find.text('Sleep device'));
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

  testWidgets('spoken phrases: a missing offline speech pack is shown', (tester) async {
    await pumpApp(tester, backend: FakeBackend(initial: device({'asr_engine': 'android', 'asr_status': 'offline speech pack missing'})));
    expect(find.text('Spoken phrases: offline speech pack missing'), findsOneWidget);
    expect(find.byKey(const Key('asr_status')), findsOneWidget);
  });

  testWidgets('spoken phrases: ready or off is no note', (tester) async {
    await pumpApp(tester, backend: FakeBackend(initial: device({'asr_engine': 'android', 'asr_status': 'ready'})));
    expect(find.byKey(const Key('asr_status')), findsNothing);
    expect(find.text('ready'), findsOneWidget);   // the Speech row
    expect(const VoxStatus(service: true, armed: true, paused: false, mode: 'gesture', asrStatus: 'off').asrProblem, isFalse);
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
    await tester.tap(find.text('Pause Canti'));
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
    await tester.ensureVisible(find.text('Connect'));
    await tester.pumpAndSettle();
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
          matchesSemantics(label: 'Pause Canti', isButton: true, hasTapAction: true, isEnabled: true,
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
    await tester.ensureVisible(find.byKey(const Key('legacy')));
    await tester.pumpAndSettle();
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
    await tester.ensureVisible(find.text('Legacy settings'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Legacy settings'));
    await tester.pump();
    expect(b.legacyOpened, 1);
  });

  testWidgets('a phone mic source shows the mode toggle and commands the mode locally', (tester) async {
    final b = await pumpApp(tester,
        backend: FakeBackend(initial: VoxStatus.fromMap({
          'service': true, 'armed': true, 'paused': false, 'mode': 'gesture', 'app': 'x.y', 'decider': 'rules',
          'sound_source': 'phone',
        })));
    expect(find.byKey(const Key('mode')), findsOneWidget);
    expect(find.text('Sleep device'), findsNothing); // no device to sleep
    await tester.ensureVisible(find.text('Cursor'));
    await tester.tap(find.text('Cursor'));
    await tester.pumpAndSettle();
    expect(b.commands.last, {'v': 1, 'mode': 'cursor'}); // the mic source owns the mode; applied here
    expect(b.current.mode, 'cursor');
  });

  testWidgets('the bindings window shows the backend bindings (a user rule)', (tester) async {
    const bindings = VoxBindings(
      gesture: VoxModeBindings(sounds: {'rise': VoxBinding('zoom in', 'app')}, combos: []),
      cursor: VoxModeBindings(sounds: {}, combos: []),
    );
    await pumpApp(tester,
        backend: FakeBackend(
            initial: const VoxStatus(service: true, armed: true, paused: false, mode: 'gesture', bindings: bindings)));
    // The name bar shows the selected sound (rise), tagged with the source of the user rule.
    expect(find.text('zoom in · app rule'), findsOneWidget);
  });

  testWidgets('the bindings window lists click hiss = forward in the combos', (tester) async {
    await pumpApp(tester); // no bindings: the Vocab defaults are shown
    final next = find.byTooltip('Next page');
    for (var i = 0; i < 2; i++) {
      await tester.ensureVisible(next);
      await tester.pumpAndSettle();
      await tester.tap(next);
      await tester.pumpAndSettle();
    }
    expect(find.text('forward'), findsOneWidget);
    expect(find.text('CLICK HISS'), findsOneWidget);
    expect(find.text('HISS CLICK'), findsOneWidget);
  });

  testWidgets('the bindings window shows click click click -> listen', (tester) async {
    await pumpApp(tester); // the Vocab defaults
    final next = find.byTooltip('Next page');
    for (var i = 0; i < 2; i++) {
      await tester.ensureVisible(next);
      await tester.pumpAndSettle();
      await tester.tap(next);
      await tester.pumpAndSettle();
    }
    expect(find.text('listen'), findsOneWidget); // click click click
    expect(find.text('CLICK ×3'), findsOneWidget);
    expect(find.text('home'), findsOneWidget); // click click
  });

  test('VoxBindings parses the status map shape, and the defaults carry click hiss = forward', () {
    final b = VoxBindings.fromMap({
      'gesture': {
        'sounds': {'rise': {'label': 'swipe up', 'source': 'default'}, 'click': null},
        'combos': [
          {'seq': ['click', 'hiss'], 'label': 'forward', 'source': 'app-only'},
        ],
        'note': null,
      },
      'cursor': {
        'sounds': {'hiss': {'label': 'back', 'source': 'default', 'long': 'listen for a name'}},
        'combos': [],
        'note': 'voice joystick: hums move the cursor, clicks tap, hiss goes back',
      },
    });
    expect(b.gesture.sounds['rise']!.label, 'swipe up');
    expect(b.gesture.sounds['click'], isNull);
    expect(b.gesture.combos.single.sequence, ['click', 'hiss']);
    expect(b.gesture.combos.single.label, 'forward');
    expect(b.cursor.note, 'voice joystick: hums move the cursor, clicks tap, hiss goes back');
    expect(b.cursor.sounds['hiss']!.long, 'listen for a name'); // the `long` key is parsed
    expect(VoxBindings.defaults.gesture.combos.map((c) => c.sequence.join(' ')),
        ['click click click', 'click click', 'hiss click', 'click hiss']);
    expect(VoxBindings.defaults.gesture.combos.last.label, 'forward');
    expect(VoxBindings.defaults.cursor.note, isNull);
    expect(VoxBindings.defaults.cursor.combos, isEmpty); // cursor mode has no combos: a long hiss names a target
    expect(VoxBindings.defaults.cursor.sounds['hiss']!.long, 'listen for a name');
    expect(VoxBindings.defaults.cursor.sounds['hiss']!.label, 'back');
    expect(VoxBindings.fromMapOrNull(null), isNull);
    expect(VoxBindings.fromMapOrNull('x'), isNull);
  });

  test('VoxBindings.defaults equals what the service sends with no rules (fixture from android BindingsTest)', () {
    // android/app BindingsTest.defaultsFixtureForFlutter writes and checks this file from Bindings.view.
    final m = jsonDecode(File('test/fixtures/bindings_defaults.json').readAsStringSync()) as Map<String, Object?>;
    final want = VoxBindings.fromMap(m);
    const have = VoxBindings.defaults;
    for (final (mode, w, h) in [('gesture', want.gesture, have.gesture), ('cursor', want.cursor, have.cursor)]) {
      for (final s in VoxBindings.sounds) {
        expect([h.sounds[s]?.label, h.sounds[s]?.source], [w.sounds[s]?.label, w.sounds[s]?.source], reason: '$mode $s');
      }
      expect([for (final c in h.combos) [c.sequence.join(' '), c.label, c.source]],
          [for (final c in w.combos) [c.sequence.join(' '), c.label, c.source]], reason: '$mode combos');
      expect(h.note, w.note, reason: '$mode note');
    }
  });

  testWidgets('a disarmed phone mic is shown as its own state and resume re-arms it', (tester) async {
    final b = await pumpApp(tester,
        backend: FakeBackend(initial: VoxStatus.fromMap({
          'service': true, 'armed': false, 'paused': false, 'mode': 'gesture', 'app': 'x.y', 'decider': 'rules',
          'sound_source': 'phone',
        })));
    expect(find.text('Disarmed'), findsOneWidget);
    expect(find.text('Resume Canti'), findsOneWidget);
    await tester.tap(find.text('Resume Canti'));
    await tester.pumpAndSettle();
    expect(b.current.armed, isTrue);
    expect(find.text('Listening for sounds'), findsOneWidget);
  });

  testWidgets('an open calibration shows "Calibrating" with a Stop button', (tester) async {
    final b = await pumpApp(tester,
        backend: FakeBackend(initial: VoxStatus.fromMap({
          'service': true, 'armed': true, 'paused': false, 'mode': 'cursor', 'app': 'x.y', 'decider': 'rules',
          'sound_source': 'phone', 'calibrating': true,
        })));
    expect(find.text('Calibrating — sounds are paused.'), findsOneWidget);
    expect(find.text('Stop calibrating'), findsOneWidget);
    await tester.tap(find.text('Stop calibrating'));
    await tester.pumpAndSettle();
    expect(b.calibCalls.last.$1, 'calib_cancel');
  });

  testWidgets('tapping the header head opens the badge actions (pause, mode, calibrate)', (tester) async {
    final b = await pumpApp(tester);
    await tester.tap(find.byKey(const Key('head_menu')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('head_pause')), findsOneWidget);
    expect(find.byKey(const Key('head_mode')), findsOneWidget);
    expect(find.byKey(const Key('head_calibrate')), findsNothing); // the Pico: no voice-cursor setup (as the badge menu)
    // Pause works through the same path as the status button.
    await tester.tap(find.byKey(const Key('head_pause')));
    await tester.pumpAndSettle();
    expect(b.current.deviceArmed, isFalse);
  });

  testWidgets('with a phone mic the head menu switches mode and opens calibration', (tester) async {
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 2.625;
    addTearDown(tester.view.reset);
    final b = await pumpApp(tester,
        backend: FakeBackend(initial: VoxStatus.fromMap({
          'service': true, 'armed': true, 'paused': false, 'mode': 'gesture', 'app': 'x.y', 'decider': 'rules',
          'sound_source': 'phone', 'mic_state': 'listening',
        })));
    await tester.tap(find.byKey(const Key('head_menu')));
    await tester.pumpAndSettle();
    await tester.tap(find.descendant(of: find.byKey(const Key('head_mode')), matching: find.text('Cursor')));
    await tester.pumpAndSettle();
    expect(b.current.mode, 'cursor');
    await tester.tap(find.byKey(const Key('head_menu')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('head_calibrate')));
    await tester.pumpAndSettle();
    expect(find.byType(HubScreen), findsOneWidget);
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
