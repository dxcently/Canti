import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vox_ui/src/theme/kit.dart' show PixelIconButton;
import 'package:vox_ui/vox_ui.dart';

/// Cursor mode through the phone mic.
VoxStatus phoneCursor([Map<String, Object?> m = const {}]) => VoxStatus.fromMap({
      'service': true, 'armed': true, 'paused': false, 'mode': 'cursor', 'app': 'x.y', 'decider': 'rules',
      'sound_source': 'phone', 'mic_state': 'listening', ...m,
    });

/// A `calib_status` map as the engine sends it.
Map<String, Object?> st(String? step, String state,
        {double progress = 0.5, String? reason, List<String> skipped = const [], Map<String, Object?>? result,
        Map<String, Object?> live = const {}, String source = 'phone', bool active = true,
        Map<String, Object?>? heard, List<String>? steps, List<String>? remaining}) =>
    {
      'active': active, 'source': source, 'step': step, 'state': state, 'prompt': null, 'sub': null,
      'progress': progress, 'waiting_for_steady': state == 'waiting', 'live': live,
      'heard': heard, 'step_done': state == 'step_done' || state == 'done',
      'reason': reason, 'skipped': skipped, 'result': result, 'error': null, 'calibrated': false,
      'steps': ?steps, 'remaining': ?remaining,
    };

const result3 = {
  'home_hz': 142.0, 'range_lo_hz': 96.0, 'range_hi_hz': 318.0, 'voicing_threshold': 0.42,
  'vowels': {'ee': {'acc': 0.93}, 'ah': {'acc': 0.81}, 'oo': {'acc': 0.88}}, 'skipped': <String>[],
};

List<String> calls(FakeBackend b) => [
      for (final (m, a) in b.calibCalls)
        if (m != 'calib_get') a.isEmpty ? m : '$m ${a.values.map((v) => v is List ? v.join('+') : v).join(',')}',
    ];

/// Lets the stream deliver.
Future<void> settle() => Future<void>.delayed(Duration.zero);

String textOf(WidgetTester tester, String key) => tester.widget<Text>(find.byKey(Key(key))).data!;

Future<void> tapKey(WidgetTester tester, String key) async {
  await tester.ensureVisible(find.byKey(Key(key)));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(Key(key)));
  await tester.pumpAndSettle();
}

void main() {
  group('models', () {
    test('calib_status parses the engine contract', () {
      final s = CalibStatus.fromMap(st('vowels', 'recording',
          progress: 1.4, live: {'voiced': true, 'pitch_hz': 181.2, 'level_db': -21.0, 'vowel': 'ah', 'vowel_conf': 0.8}));
      expect([s.active, s.source, s.step, s.state, s.progress, s.waitingForSteady, s.stepDone, s.failed],
          [true, 'phone', 'vowels', 'recording', 1.0, false, false, false]);
      expect([s.live.voiced, s.live.pitchHz, s.live.levelDb, s.live.vowel, s.live.vowelConf], [true, 181.2, -21.0, 'ah', 0.8]);
      expect([s.clicksNeed, s.calibrated], [3, false]);
      final f = CalibStatus.fromMap(st('glide', 'failed', reason: 'range too small', skipped: ['hum']));
      expect([f.failed, f.reason, f.skipped, f.stepDone], [true, 'range too small', ['hum'], false]);
      expect(CalibStatus.fromMap(st('hum', 'waiting')).waitingForSteady, isTrue);
    });

    test('a profile with a skipped step has null fields', () {
      final r = CalibResult.fromMap({
        ...result3, 'source': 'phone', 'version': 1, 'saved_at_ms': 1700000000000, 'range_lo_hz': null,
        'range_hi_hz': null, 'skipped': ['glide'], 'extractor': {},
      })!;
      expect([r.source, r.savedAtMs, r.rangeLoHz, r.skipped, r.vowelAcc['ah']],
          ['phone', 1700000000000, null, ['glide'], 0.81]);
      expect(CalibResult.fromMap(null), isNull);
      final rows = {for (final (_, label, value, _) in calibSummaryRows(r.toMap())) label: value};
      expect(rows['Range'], 'skipped');
      expect(rows['Home'], '142 Hz (C#3)');
      expect(rows['Skipped'], 'glide');
    });

    test('profile v2: clicks, whistle, hiss, room, the level gate; a v1 profile lists its missing steps', () {
      final r = CalibResult.fromMap({
        ...result3, 'source': 'phone', 'version': 2, 'clicks_heard': 3, 'hiss_heard': 2, 'whistle_lo_hz': 880.0,
        'whistle_hi_hz': 2350.0, 'whistle_home_hz': 1400.0, 'room_floor_dbfs': -63.4, 'relabel_rule': true,
        'level_gate': {'min_snr_db': 11.2, 'min_level_dbfs': -52.0, 'from': 'calibration', 'n': 8, 'weakest_snr_db': 17.0},
        'missing_steps': <String>[], 'needs_recalibration': false,
      })!;
      expect([r.version, r.clicksHeard, r.hissHeard, r.whistleHomeHz, r.roomFloorDbfs, r.relabelRule, r.needsRecalibration],
          [2, 3, 2, 1400.0, -63.4, true, false]);
      expect([r.levelGate!.n, r.levelGate!.calibrated, r.levelGate!.weakestSnrDb, r.levelGate!.weakestLevelDbfs],
          [8, isTrue, 17.0, null]);
      var rows = {for (final (_, label, value, _) in calibSummaryRows(r.toMap())) label: value};
      expect([rows['Clicks'], rows['Whistle'], rows['Hiss'], rows['Room'], rows['Gate']],
          ['3/3', '880-2350 Hz', '2/2', '-63 dBFS', '11 dB, calibration']);
      expect(rows.containsKey('Missing'), isFalse);
      expect(r.levelGate!.sentence, 'Ignores sounds under 11 dB over the room (from your calibration).');

      // A version 1 profile loads as version 2 with its missing steps and the default gate.
      final v1 = CalibResult.fromMap({
        ...result3, 'version': 2, 'missing_steps': ['clicks', 'whistle', 'hiss', 'room'], 'needs_recalibration': true,
        'level_gate': {'min_snr_db': 6.0, 'min_level_dbfs': -60.0, 'from': 'default', 'n': 0},
      })!;
      expect(v1.needsRecalibration, isTrue);
      rows = {for (final (_, label, value, _) in calibSummaryRows(v1.toMap())) label: value};
      expect([rows['Clicks'], rows['Whistle'], rows['Room'], rows['Gate'], rows['Missing'], rows['Home']],
          ['not yet', 'not yet', 'not yet', '6 dB, default', 'clicks, whistle, hiss, room', '142 Hz (C#3)']);
      expect(v1.levelGate!.sentence, contains('the default'));
      // needs_recalibration is inferred from missing_steps when absent
      expect(CalibResult.fromMap({'missing_steps': ['room']})!.needsRecalibration, isTrue);

      // The inactive status map carries both too; heard has the clicks and the hiss.
      final idle = CalibStatus.fromMap({
        'active': false, 'source': 'phone', 'state': null, 'calibrated': true, 'skipped': <String>[], 'error': null,
        'needs_recalibration': true, 'missing_steps': ['clicks', 'whistle', 'hiss', 'room'],
      });
      expect([idle.active, idle.needsRecalibration, idle.missingSteps.length], [false, isTrue, 4]);
      final h = CalibStatus.fromMap(st('clicks', 'recording',
          heard: {'clicks_n': 1, 'clicks_need': 3, 'hiss_n': 2, 'hiss_need': 2}));
      expect([h.heard('clicks'), h.heard('hiss'), h.heard('room')], [(1, 3), (2, 2), null]);
    });

    test('level gate settings: on by default, offset -10..10 dB, + is stricter', () {
      expect([LevelGateSettings.fromMap(null).enabled, LevelGateSettings.fromMap(null).offsetDb], [isTrue, 0]);
      final g = LevelGateSettings.fromMap({'level_gate': false, 'level_gate_offset_db': 14});
      expect([g.enabled, g.offsetDb], [isFalse, 10]);
      expect(LevelGateSettings.fromMap({'level_gate_offset_db': -12.4}).offsetDb, -10);
      expect([LevelGateSettings.label(3), LevelGateSettings.label(0), LevelGateSettings.label(-2)], ['+3 dB', '0 dB', '-2 dB']);
    });

    test('cursor settings: 0.5..2.0 on a 10% grid, default 90%', () {
      expect(CursorSettings.fromMap(null).speed, 0.9);
      expect(CursorSettings.fromMap({'cursor_speed': 3.0, 'cursor_pitch_sens': 0.44}).speed, 2.0);
      expect(CursorSettings.fromMap({'cursor_pitch_sens': 0.44}).pitchSens, 0.5);
      expect(CursorSettings.snap(0.9 + 0.1), 1.0);
      expect(CursorSettings.percent(0.9), '90%');
      expect(noteName(440), 'A4');
      expect(hzLabel(null), '-');
    });
  });

  group('status screen', () {
    Future<FakeBackend> pumpStatus(WidgetTester tester, FakeBackend b) async {
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 2.625;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(const SizedBox()); // a fresh status screen per backend
      await tester.pumpWidget(VoxUiApp(backend: b));
      await tester.pumpAndSettle();
      return b;
    }

    testWidgets('cursor mode on the phone mic, not calibrated: the prompt opens the hub', (tester) async {
      await pumpStatus(tester, FakeBackend(initial: phoneCursor({'calibrated': false})));
      await tapKey(tester, 'calib_prompt_start');
      expect(find.byType(HubScreen), findsOneWidget);
      expect(find.text('CALIBRATE 0/7'), findsOneWidget);
    });

    testWidgets('calibration shows 7 steps and no Pops', (tester) async {
      await pumpStatus(tester, FakeBackend(initial: phoneCursor({'calibrated': false})));
      await tapKey(tester, 'calib_prompt_start');
      expect(find.text('CALIBRATE 0/7'), findsOneWidget);
      for (final s in const ['hum', 'glide', 'vowels', 'clicks', 'whistle', 'hiss', 'room']) {
        expect(find.byKey(Key('hub_calib_$s')), findsOneWidget, reason: s);
      }
      expect(find.byKey(const Key('hub_calib_pops')), findsNothing);
    });

    testWidgets('no prompt when calibrated, in gesture mode, or on the Pico; "Not now" hides it', (tester) async {
      await pumpStatus(tester, FakeBackend(initial: phoneCursor({'calibrated': true})));
      expect(find.byKey(const Key('calib_prompt_start')), findsNothing);
      await pumpStatus(tester, FakeBackend(initial: phoneCursor({'calibrated': false, 'mode': 'gesture'})));
      expect(find.byKey(const Key('calib_prompt_start')), findsNothing);
      await pumpStatus(tester, FakeBackend(initial: phoneCursor({'calibrated': false, 'sound_source': 'pico'})));
      expect(find.byKey(const Key('calib_prompt_start')), findsNothing);
      await pumpStatus(tester, FakeBackend(initial: phoneCursor({'calibrated': false})));
      expect(find.byKey(const Key('calib_prompt_start')), findsOneWidget);
      await tester.tap(find.byTooltip('Not now'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('calib_prompt_start')), findsNothing);
    });

    testWidgets('the service can open the setup (route calibrate)', (tester) async {
      await pumpStatus(tester, FakeBackend(initial: phoneCursor())..pendingRoute = 'calibrate');
      expect(find.byType(HubScreen), findsOneWidget);
    });

    testWidgets('voice cursor section: the two settings as %, per-source state, recalibrate', (tester) async {
      final b = await pumpStatus(tester, FakeBackend(initial: phoneCursor()));
      expect(textOf(tester, 'cursor_speed_value'), '90%');
      expect(textOf(tester, 'cursor_pitch_sens_value'), '90%');
      await tapKey(tester, 'cursor_speed_up');
      expect(textOf(tester, 'cursor_speed_value'), '100%');
      expect(b.cursor.speed, 1.0);
      await tapKey(tester, 'cursor_pitch_sens_down');
      expect(b.cursor.pitchSens, 0.8);
      expect(textOf(tester, 'calib_state_phone'), 'not calibrated, in use');
      expect(textOf(tester, 'calib_state_usb'), 'not calibrated');
      expect(find.byKey(const Key('calib_none')), findsOneWidget);
      expect(find.text('Calibrate'), findsOneWidget);
      // A saved profile: the summary and "Recalibrate".
      b.calibSaved['phone'] = CalibResult.fromMap(result3)!;
      b.cursor = const CursorSettings(speed: 2.0);
      await tester.pumpWidget(const SizedBox());
      await pumpStatus(tester, b);
      expect(textOf(tester, 'calib_state_phone'), 'calibrated, in use');
      expect(textOf(tester, 'calib_home'), '142 Hz (C#3)');
      expect(find.text('Recalibrate'), findsOneWidget);
      expect(tester.widget<PixelIconButton>(find.byKey(const Key('cursor_speed_up'))).onPressed, isNull);
      await tapKey(tester, 'recalibrate');
      expect(find.byType(HubScreen), findsOneWidget);
    });

    testWidgets('a v1 profile: the nudge opens the hub with only the 4 new steps left', (tester) async {
      final b = FakeBackend(initial: phoneCursor({'calibrated': true}), calibAuto: true);
      b.calibSaved['phone'] = CalibResult.fromMap({
        ...result3, 'source': 'phone', 'version': 2, 'missing_steps': ['clicks', 'whistle', 'hiss', 'room'],
        'needs_recalibration': true, 'level_gate': {'min_snr_db': 6.0, 'min_level_dbfs': -60.0, 'from': 'default', 'n': 0},
      })!;
      await pumpStatus(tester, b);
      expect(textOf(tester, 'calib_state_phone'), 'partly calibrated, in use');
      expect(textOf(tester, 'calib_nudge'), startsWith('Recalibrate: 4 new steps (clicks, whistle, hiss, room)'));
      expect([textOf(tester, 'calib_clicks'), textOf(tester, 'calib_missing')], ['not yet', 'clicks, whistle, hiss, room']);
      expect(find.text('Recalibrate all'), findsOneWidget);
      await tapKey(tester, 'calib_record_missing');
      expect(find.byType(HubScreen), findsOneWidget);
      // the saved steps show as done, the 4 new ones as not done
      for (final s in calibSteps) {
        final missing = const ['clicks', 'whistle', 'hiss', 'room'].contains(s);
        final notDone = find.descendant(of: find.byKey(Key('hub_calib_$s')), matching: find.text('not done'));
        expect(notDone, missing ? findsOneWidget : findsNothing, reason: s);
      }
    });

    testWidgets('level gate: on / off, and its strictness in 1 dB steps', (tester) async {
      final b = await pumpStatus(tester, FakeBackend(initial: phoneCursor()));
      expect(textOf(tester, 'level_gate_offset_value'), '0 dB');
      await tapKey(tester, 'level_gate_offset_up');
      expect([textOf(tester, 'level_gate_offset_value'), b.levelGate.offsetDb], ['+1 dB', 1]);
      await tapKey(tester, 'level_gate_offset_down');
      await tapKey(tester, 'level_gate_offset_down');
      expect(b.levelGate.offsetDb, -1);
      final off = find.descendant(of: find.byKey(const Key('level_gate')), matching: find.text('Off'));
      await tester.ensureVisible(off);
      await tester.tap(off);
      await tester.pumpAndSettle();
      expect(b.levelGate.enabled, isFalse);
      expect(textOf(tester, 'level_gate_note'), startsWith('Off'));
      expect(tester.widget<PixelIconButton>(find.byKey(const Key('level_gate_offset_up'))).onPressed, isNull);
      b.levelGate = const LevelGateSettings(offsetDb: 10);
      await tester.pumpWidget(const SizedBox());
      await pumpStatus(tester, b);
      expect(textOf(tester, 'level_gate_offset_value'), '+10 dB');
      expect(tester.widget<PixelIconButton>(find.byKey(const Key('level_gate_offset_up'))).onPressed, isNull);
    });
  });

  group('FakeBackend (the service contract)', () {
    test('steps / remaining, a no-op calib_step, skip never wraps, a redo goes back to done', () async {
      final b = FakeBackend(initial: phoneCursor(), calibAuto: true, calibTick: const Duration(milliseconds: 1));
      b.calibSaved['phone'] = CalibResult.fromMap({...result3, 'source': 'phone', 'skipped': ['room']})!;
      final got = <CalibStatus>[];
      final sub = b.calibStatus().listen(got.add);
      Future<void> until(bool Function(CalibStatus s) ok) async {
        for (var i = 0; i < 400 && (got.isEmpty || !ok(got.last)); i++) {
          await Future<void>.delayed(const Duration(milliseconds: 5));
        }
      }

      await b.calibStart('phone', steps: const ['hum', 'room']);
      await settle();
      // it starts on steps[0]; the room is taken out of the saved profile's skipped (it is recorded again)
      expect([got.last.step, got.last.runSteps, got.last.remaining, got.last.skipped],
          ['hum', ['hum', 'room'], ['hum', 'room'], isEmpty]);
      await b.calibStep('room'); // jumps ahead: the hum stays open
      await until((s) => s.step == 'room' && s.state == 'recording');
      final n = b.calibCalls.length;
      b.calibFreeze(); // hold the room still
      final pushes = got.length;
      await b.calibStep('room'); // already recording: a no-op
      await settle();
      expect([b.calibCalls.length, got.length, got.last.step], [n + 1, pushes, 'room']);
      await b.calibSkip(); // nothing after the room, and no wrap round to the hum: step_done, the UI picks it
      await settle();
      expect([got.last.step, got.last.state, got.last.remaining, got.last.skipped], ['room', 'step_done', ['hum'], ['room']]);
      await b.calibStep('hum');
      await until((s) => s.state == 'done');
      expect([got.last.step, got.last.state, got.last.remaining, got.last.result?.homeHz], ['hum', 'done', isEmpty, 142]);
      await b.calibRedo('hum');
      await until((s) => s.state == 'done');
      expect([got.last.step, got.last.state, got.last.remaining], ['hum', 'done', isEmpty]); // nothing else starts
      Object? err;
      try {
        await b.calibStart('phone', steps: const ['hum', 'hum']);
      } catch (e) {
        err = e;
      }
      expect(err, isArgumentError); // a repeat
      await b.calibCancel();
      await sub.cancel();
      b.dispose();
    });
  });

  group('ChannelBackend', () {
    const methods = MethodChannel(ChannelBackend.methodsName);
    TestWidgetsFlutterBinding.ensureInitialized();
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    tearDown(() => messenger.setMockMethodCallHandler(methods, null));

    test('calib_* method names and arguments, answers and Kotlin\'s calib_status calls', () async {
      final got = <MethodCall>[];
      messenger.setMockMethodCallHandler(methods, (call) async {
        got.add(call);
        return switch (call.method) {
          'calib_get' => (call.arguments as Map)['source'] == 'phone' ? {...result3, 'source': 'phone'} : null,
          'cursorSettings' || 'setCursorSettings' => {'cursor_speed': 1.2, 'cursor_pitch_sens': 0.9},
          'levelGateSettings' || 'setLevelGateSettings' => {'level_gate': false, 'level_gate_offset_db': 3},
          _ => st('hum', 'waiting'),
        };
      });
      final b = ChannelBackend();
      final pushes = <CalibStatus>[];
      final sub = b.calibStatus().listen(pushes.add);
      await b.calibStart('phone');
      await b.calibStart('phone', steps: const ['clicks', 'room']);
      await b.calibStep('glide');
      await b.calibRedo('clicks');
      await b.calibRetry();
      await b.calibSkip();
      await b.calibSave();
      await b.calibCancel();
      expect((await b.calibGet('phone'))!.homeHz, 142);
      expect(await b.calibGet('usb'), isNull);
      expect((await b.setCursorSettings(speed: 1.2)).speed, 1.2);
      expect((await b.cursorSettings()).pitchSens, 0.9);
      expect((await b.setLevelGateSettings(enabled: false, offsetDb: 3)).offsetDb, 3);
      expect((await b.levelGateSettings()).enabled, isFalse);
      expect([for (final c in got) '${c.method} ${c.arguments}'], [
        'calib_start {source: phone}', 'calib_start {source: phone, steps: [clicks, room]}', 'calib_step {step: glide}',
        'calib_redo {step: clicks}', 'calib_retry null',
        'calib_skip null', 'calib_save null', 'calib_cancel null', 'calib_get {source: phone}', 'calib_get {source: usb}',
        'setCursorSettings {cursor_speed: 1.2}', 'cursorSettings null',
        'setLevelGateSettings {level_gate: false, level_gate_offset_db: 3}', 'levelGateSettings null',
      ]);
      // Kotlin -> Dart: invokeMethod("calib_status", map)
      await messenger.handlePlatformMessage(ChannelBackend.methodsName,
          const StandardMethodCodec().encodeMethodCall(MethodCall('calib_status', {
            'active': true, 'source': 'phone', 'step': 'glide', 'state': 'failed', 'reason': 'range too small',
            'steps': ['hum', 'glide'], 'remaining': ['glide'],
          })), (_) {});
      await settle();
      expect(pushes.length, 9); // eight command answers and the push
      expect([pushes.last.step, pushes.last.failed, pushes.last.reason], ['glide', isTrue, 'range too small']);
      expect([pushes.last.runSteps, pushes.last.remaining], [['hum', 'glide'], ['glide']]);
      expect(pushes.first.remaining, isNull); // a status without them
      await sub.cancel();
    });
  });
}

/// Taps Next after each step until the result shows.
Future<void> nextToResult(WidgetTester tester) async {
  while (find.byKey(const Key('calib_save')).evaluate().isEmpty) {
    await waitFor(tester, find.byKey(const Key('calib_next')));
    await tapKey(tester, 'calib_next');
  }
}

/// Pumps the fake engine's clock in 100 ms steps until [finder] finds something (at most [max]).
Future<void> waitFor(WidgetTester tester, Finder finder, {Duration max = const Duration(seconds: 20)}) async {
  var t = Duration.zero;
  while (finder.evaluate().isEmpty) {
    if (t > max) fail('not found within $max: $finder');
    await tester.pump(const Duration(milliseconds: 100));
    t += const Duration(milliseconds: 100);
  }
}
