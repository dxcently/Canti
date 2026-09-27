import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vox_ui/src/theme/kit.dart' show PipMeter, PixelIconButton;
import 'package:vox_ui/vox_ui.dart';

/// Cursor mode through the phone mic.
VoxStatus phoneCursor([Map<String, Object?> m = const {}]) => VoxStatus.fromMap({
      'service': true, 'armed': true, 'paused': false, 'mode': 'cursor', 'app': 'x.y', 'decider': 'rules',
      'sound_source': 'phone', 'mic_state': 'listening', ...m,
    });

/// A `calib_status` map as the engine sends it.
Map<String, Object?> st(String? step, String state,
        {double progress = 0.5, String? reason, List<String> skipped = const [], Map<String, Object?>? result,
        Map<String, Object?> live = const {}, int popsN = 0, String source = 'phone', bool active = true,
        Map<String, Object?>? heard, List<String>? steps, List<String>? remaining}) =>
    {
      'active': active, 'source': source, 'step': step, 'state': state, 'prompt': null, 'sub': null,
      'progress': progress, 'waiting_for_steady': state == 'waiting', 'live': live,
      'heard': heard ?? {'pops_n': popsN, 'pops_need': 3}, 'step_done': state == 'step_done' || state == 'done',
      'reason': reason, 'skipped': skipped, 'result': result, 'error': null, 'calibrated': false,
      'steps': ?steps, 'remaining': ?remaining,
    };

const result3 = {
  'home_hz': 142.0, 'range_lo_hz': 96.0, 'range_hi_hz': 318.0, 'voicing_threshold': 0.42,
  'vowels': {'ee': {'acc': 0.93}, 'ah': {'acc': 0.81}, 'oo': {'acc': 0.88}}, 'pops_heard': 3, 'skipped': <String>[],
};

List<String> calls(FakeBackend b) => [
      for (final (m, a) in b.calibCalls)
        if (m != 'calib_get') a.isEmpty ? m : '$m ${a.values.map((v) => v is List ? v.join('+') : v).join(',')}',
    ];

/// Lets the stream deliver.
Future<void> settle() => Future<void>.delayed(Duration.zero);

String textOf(WidgetTester tester, String key) => tester.widget<Text>(find.byKey(Key(key))).data!;

Future<FakeBackend> pumpCalib(WidgetTester tester, FakeBackend b, {String source = 'phone'}) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.625;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(VoxUiApp(backend: b));
  await tester.pumpAndSettle();
  final nav = tester.state<NavigatorState>(find.byType(Navigator));
  nav.push(MaterialPageRoute<bool>(builder: (_) => CalibrationScreen(backend: b, source: source)));
  await tester.pumpAndSettle();
  return b;
}

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
      expect([s.popsNeed, s.calibrated], [3, false]);
      final f = CalibStatus.fromMap(st('glide', 'failed', reason: 'range too small', skipped: ['hum']));
      expect([f.failed, f.reason, f.skipped, f.stepDone], [true, 'range too small', ['hum'], false]);
      expect(CalibStatus.fromMap(st('hum', 'waiting')).waitingForSteady, isTrue);
    });

    test('a profile with a skipped step has null fields', () {
      final r = CalibResult.fromMap({
        ...result3, 'source': 'phone', 'version': 1, 'saved_at_ms': 1700000000000, 'range_lo_hz': null,
        'range_hi_hz': null, 'skipped': ['glide'], 'extractor': {}, 'pops_heard': 1,
      })!;
      expect([r.source, r.savedAtMs, r.rangeLoHz, r.skipped, r.vowelAcc['ah'], r.popsWeak],
          ['phone', 1700000000000, null, ['glide'], 0.81, isTrue]);
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
          heard: {'pops_n': 0, 'pops_need': 3, 'clicks_n': 1, 'clicks_need': 3, 'hiss_n': 2, 'hiss_need': 2}));
      expect([h.heard('clicks'), h.heard('hiss'), h.heard('pops'), h.heard('room')], [(1, 3), (2, 2), (0, 3), null]);
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

  group('CalibFlow', () {
    late FakeBackend b;
    late CalibFlow f;
    setUp(() {
      b = FakeBackend(initial: phoneCursor());
      f = CalibFlow(backend: b, source: 'phone')..attach();
    });
    tearDown(() {
      f.dispose();
      b.dispose();
    });

    Future<void> push(Map<String, Object?> m) async {
      b.emitCalib(m);
      await settle();
    }

    test('steps progress: start (the service starts the hum), step_done, next ... result', () async {
      await f.begin();
      expect(calls(b), ['calib_start phone']); // no calib_step for the hum: calib_start starts it
      expect(f.page, CalibPage.hum);
      await push(st('hum', 'waiting', progress: 0));
      expect(f.pageStatus!.waitingForSteady, isTrue);
      expect(f.pageDone, isFalse);
      await f.next(); // not done yet: nothing
      expect(calls(b), ['calib_start phone']);
      await push(st('hum', 'step_done', progress: 1));
      expect(f.pageDone, isTrue);
      await f.next();
      expect(f.page, CalibPage.glide);
      // A stale step_done for the step just commanded is ignored until the service shows it running.
      await push(st('glide', 'step_done'));
      expect(f.pageDone, isFalse);
      await push(st('glide', 'recording'));
      await push(st('glide', 'step_done'));
      await f.next();
      await push(st('vowels', 'recording'));
      await push(st('vowels', 'step_done'));
      await f.next();
      await push(st('pops', 'recording', popsN: 2));
      expect(f.pageStatus!.popsN, 2);
      await push(st('pops', 'step_done', popsN: 3));
      for (final s in ['clicks', 'whistle', 'hiss', 'room']) {
        await f.next();
        expect(f.page, CalibPage.ofStep(s));
        await push(st(s, 'recording'));
        await push(st(s, s == 'room' ? 'done' : 'step_done', result: s == 'room' ? result3 : null));
      }
      await f.next();
      expect(f.page, CalibPage.result);
      expect(f.result!.homeHz, 142);
      expect(calls(b), [
        'calib_start phone', 'calib_step glide', 'calib_step vowels', 'calib_step pops', 'calib_step clicks',
        'calib_step whistle', 'calib_step hiss', 'calib_step room',
      ]);
      expect(f.furthest, CalibPage.result);
      expect([f.pageIndex, f.pages.length], [9, 10]);
      f.goTo(1);
      expect(f.page, CalibPage.hum); // the pager shows it; nothing is recorded
      expect(calls(b).length, 8);
    });

    test('redo from the result goes back to the result', () async {
      await f.begin();
      for (final s in calibSteps) {
        if (s != 'hum') await f.next();
        await push(st(s, 'recording'));
        await push(st(s, s == 'room' ? 'done' : 'step_done', result: s == 'room' ? result3 : null));
      }
      await f.next();
      expect(f.page, CalibPage.result);
      await f.redo('glide');
      expect(calls(b).last, 'calib_redo glide');
      expect([f.page, f.redoing, f.pageDone], [CalibPage.glide, isTrue, isFalse]);
      await push(st('glide', 'recording'));
      await push(st('glide', 'done', result: result3));
      await f.next();
      expect(f.page, CalibPage.result);
      expect(f.redoing, isFalse);
    });

    test('a failed step waits with the reason: Retry reruns it, Skip keeps its defaults', () async {
      await f.begin();
      await push(st('hum', 'recording'));
      await push(st('hum', 'failed', reason: 'too short or too rough: hum again, 3 s'));
      expect(f.pageFailure, 'too short or too rough: hum again, 3 s');
      expect(f.pageDone, isFalse);
      // Nothing is sent by itself, however long it waits, and next does nothing.
      await f.next();
      expect(calls(b), ['calib_start phone']);
      await f.retry();
      expect(calls(b).last, 'calib_retry');
      expect(f.pageFailure, isNull);
      await push(st('hum', 'recording'));
      await push(st('hum', 'failed', reason: 'still rough'));
      expect(f.pageFailure, 'still rough');
      await f.skip();
      expect(calls(b).last, 'calib_skip');
      expect(f.skipped, {'hum'});
      expect(f.page, CalibPage.glide); // the service moved on: shown, not commanded
      expect(calls(b).where((c) => c.startsWith('calib_step')), isEmpty);
      await push(st('glide', 'waiting', skipped: ['hum']));
      expect(f.pageStatus!.step, 'glide');
    });

    test('skip before a failure: waiting, a counted step before anything is heard, the room', () async {
      Map<String, Object?> clicks(int n) => {'pops_n': 0, 'pops_need': 3, 'clicks_n': n, 'clicks_need': 3, 'hiss_n': 0, 'hiss_need': 2};
      await f.begin();
      await push(st('hum', 'waiting', progress: 0));
      expect(f.canSkip, isTrue);
      await push(st('hum', 'recording'));
      expect(f.canSkip, isFalse); // a hum under way: only a failure can skip it
      await push(st('hum', 'step_done'));
      expect(f.canSkip, isFalse);
      await push(st('clicks', 'recording', heard: clicks(1))); // followed: the hum page is done
      expect(f.page, CalibPage.clicks);
      expect(f.canSkip, isFalse); // a click was heard
      await push(st('clicks', 'recording', heard: clicks(0)));
      expect(f.canSkip, isTrue);
      await f.skip();
      expect(calls(b), ['calib_start phone', 'calib_skip']);
      // The service starts the next unfinished step after the clicks (the whistle) by itself: nothing more is sent.
      expect(f.page, CalibPage.whistle);
      await push(st('room', 'recording'));
      expect(f.page, CalibPage.whistle); // not followed: the whistle page is not done
      f.goTo(f.pages.indexOf(CalibPage.whistle));
      expect(f.canSkip, isFalse); // the room's status is not this page's
    });

    test('only the missing steps: calib_start with them; after step_done calib_step remaining[0]; done: the result',
        () async {
      final g = CalibFlow(backend: b, source: 'phone', steps: const ['room', 'clicks', 'whistle', 'hiss'])..attach();
      expect(g.steps, ['clicks', 'whistle', 'hiss', 'room']); // in the service's order
      expect(g.pages, [CalibPage.intro, CalibPage.clicks, CalibPage.whistle, CalibPage.hiss, CalibPage.room, CalibPage.result]);
      expect(g.partial, isTrue);
      const run = ['clicks', 'whistle', 'hiss', 'room'];
      await g.begin();
      expect(calls(b), ['calib_start phone,clicks+whistle+hiss+room']); // the service starts on the clicks
      expect(g.page, CalibPage.clicks);
      await push(st('clicks', 'recording', steps: run, remaining: run));
      await push(st('clicks', 'step_done', steps: run, remaining: const ['whistle', 'hiss', 'room']));
      expect(g.nextIsResult, isFalse);
      await g.next();
      expect(calls(b).last, 'calib_step whistle');
      await push(st('whistle', 'recording', steps: run, remaining: const ['whistle', 'hiss', 'room']));
      await push(st('whistle', 'failed', reason: 'the whistle overlaps your voice range', steps: run,
          remaining: const ['whistle', 'hiss', 'room']));
      expect(g.pageFailure, contains('overlaps'));
      await g.skip();
      expect(calls(b).last, 'calib_skip'); // the service goes on to the hiss by itself
      expect(g.page, CalibPage.hiss);
      await push(st('hiss', 'recording', steps: run, remaining: const ['hiss', 'room'], skipped: const ['whistle']));
      await push(st('hiss', 'step_done', steps: run, remaining: const ['room'], skipped: const ['whistle']));
      await g.next();
      expect(calls(b).last, 'calib_step room');
      await push(st('room', 'recording', steps: run, remaining: const ['room'], skipped: const ['whistle']));
      expect(g.canSkip, isTrue); // the room can be skipped at any time
      await g.skip(); // nothing after it and nothing open: the run is done
      expect(g.page, CalibPage.result);
      expect(calls(b), [
        'calib_start phone,clicks+whistle+hiss+room', 'calib_step whistle', 'calib_skip', 'calib_step room', 'calib_skip',
      ]);
      g.dispose();
    });

    test('the whole run starts with calib_start alone (no steps), on the hum', () async {
      await f.begin();
      expect(calls(b), ['calib_start phone']);
      expect(f.page, CalibPage.hum);
    });

    test('skip never wraps: with an earlier step still open (step_done), the screen asks for it', () async {
      const run = ['hum', 'room'];
      final g = CalibFlow(backend: b, source: 'phone', steps: run)..attach();
      await g.begin();
      await push(st('hum', 'step_done', steps: run, remaining: const ['room']));
      await push(st('room', 'recording', steps: run, remaining: const ['room'])); // followed: the hum page is done
      expect(g.page, CalibPage.room);
      // The service reports the hum open again (say it was re-recorded elsewhere): skipping the room can't wrap.
      await push(st('room', 'recording', steps: run, remaining: run));
      expect(g.nextIsResult, isFalse);
      await g.skip();
      expect(calls(b), ['calib_start phone,hum+room', 'calib_skip', 'calib_step hum']);
      expect(g.page, CalibPage.hum);
      g.dispose();
    });

    test('status skipped is this run\'s: a skipped step recorded again stays open until it finishes', () async {
      await f.begin();
      await push(st('hum', 'waiting', progress: 0));
      await f.skip();
      expect([f.page, f.skipped], [CalibPage.glide, {'hum'}]);
      await push(st('glide', 'step_done', skipped: const ['hum']));
      await f.redo('hum'); // from the glide page: not a redo from the result
      expect([calls(b).last, f.page, f.redoing, f.pageDone], ['calib_redo hum', CalibPage.hum, isFalse, isFalse]);
      await push(st('hum', 'waiting', skipped: const ['hum'])); // still in skipped until it is measured
      expect(f.pageDone, isFalse);
      await push(st('hum', 'step_done'));
      expect([f.pageDone, f.skipped.contains('hum')], [isTrue, isFalse]);
    });

    test('the service moving on by itself is followed', () async {
      await f.begin();
      await push(st('hum', 'step_done'));
      await push(st('glide', 'waiting'));
      expect(f.page, CalibPage.glide);
      await push(st('glide', 'step_done'));
      await f.next(); // vowels: not started by the service yet, so commanded
      expect(calls(b).last, 'calib_step vowels');
    });

    test('save and cancel', () async {
      await f.cancel(); // never started: nothing sent
      expect(calls(b), isEmpty);
      final g = CalibFlow(backend: b, source: 'phone')..attach();
      await g.begin();
      await g.save();
      expect([g.saved, g.finished], [isTrue, isTrue]);
      expect(calls(b).last, 'calib_save');
      await g.cancel(); // already over
      expect(calls(b).last, 'calib_save');
      final h = CalibFlow(backend: b, source: 'phone')..attach();
      await h.begin();
      await h.cancel();
      expect(calls(b).last, 'calib_cancel');
      g.dispose();
      h.dispose();
    });

    test('a refused start (not the current source, or the Pico) shows the error and stays on the intro', () async {
      final p = CalibFlow(backend: b, source: 'pico')..attach();
      await p.begin();
      expect(p.error, contains('Pico'));
      expect([p.page, p.started], [CalibPage.intro, isFalse]);
      p.dispose();
    });

    test('pushes for another source are ignored; a service stop is an error', () async {
      await f.begin();
      await push(st('glide', 'recording', source: 'usb'));
      expect(f.status, isNull);
      await push(st(null, 'done', active: false));
      expect(f.error, contains('stopped'));
    });

    test('calib_get: null is not calibrated', () async {
      expect(await b.calibGet('phone'), isNull);
    });
  });

  group('screen', () {
    testWidgets('the whole setup on the fake engine: waiting, live pitch, vowels, pops, result, save', (tester) async {
      final b = await pumpCalib(tester, FakeBackend(initial: phoneCursor(), calibAuto: true));
      expect(textOf(tester, 'calib_source'), 'phone mic');
      expect(find.text('phone mic · about 40 s'), findsOneWidget);
      await tapKey(tester, 'calib_begin');
      expect(textOf(tester, 'calib_where'), 'phone mic · step 1 of 8');
      expect(find.text('Waiting for a steady note...'), findsOneWidget);
      await waitFor(tester, find.text('Listening...'));
      expect(textOf(tester, 'calib_pitch'), contains('Hz'));
      await waitFor(tester, find.byKey(const Key('calib_next')));
      await tapKey(tester, 'calib_next');
      expect(textOf(tester, 'calib_where'), 'phone mic · step 2 of 8');
      await waitFor(tester, find.byKey(const Key('calib_next')));
      await tapKey(tester, 'calib_next');
      await waitFor(tester, find.byKey(const Key('calib_vowel')));
      await waitFor(tester, find.text('Listening...'));
      expect(textOf(tester, 'calib_vowel'), startsWith('ee'));
      expect(find.byKey(const Key('calib_sub')), findsOneWidget);
      await waitFor(tester, find.byKey(const Key('calib_next')));
      await tapKey(tester, 'calib_next');
      await waitFor(tester, find.byKey(const Key('calib_next')));
      expect(textOf(tester, 'calib_heard'), '3/3');
      await tapKey(tester, 'calib_next');
      // clicks: counted like the pops, out of 3
      expect(textOf(tester, 'calib_prompt'), 'Click your tongue 3 times, about a second apart');
      await waitFor(tester, find.byKey(const Key('calib_next')));
      expect(textOf(tester, 'calib_heard'), '3/3');
      await tapKey(tester, 'calib_next');
      // whistle: waits for a steady whistle, then a pitch far above the voice
      await waitFor(tester, find.text('Waiting for a steady whistle...'));
      await waitFor(tester, find.text('Listening...'));
      expect(textOf(tester, 'calib_pitch'), contains('Hz'));
      await waitFor(tester, find.byKey(const Key('calib_next')));
      await tapKey(tester, 'calib_next');
      // hiss: out of 2
      await waitFor(tester, find.byKey(const Key('calib_next')));
      expect(textOf(tester, 'calib_heard'), '2/2');
      await tapKey(tester, 'calib_next');
      // room: the level only
      expect(textOf(tester, 'calib_where'), 'phone mic · step 8 of 8');
      await waitFor(tester, find.text('Listening to the room...'));
      expect(find.byKey(const Key('calib_pitch')), findsNothing);
      await waitFor(tester, find.text('See result'));
      await tapKey(tester, 'calib_next');
      expect(textOf(tester, 'calib_home'), '142 Hz (C#3)');
      expect(textOf(tester, 'calib_range'), '96-318 Hz');
      expect(textOf(tester, 'calib_acc_ah'), '81%');
      expect(textOf(tester, 'calib_pops'), '3/3');
      expect(textOf(tester, 'calib_clicks'), '3/3');
      expect(textOf(tester, 'calib_whistle'), '880-2350 Hz');
      expect(textOf(tester, 'calib_hiss'), '2/2');
      expect(textOf(tester, 'calib_room'), '-63 dBFS');
      expect(textOf(tester, 'calib_gate'), '11 dB, calibration');
      expect(textOf(tester, 'calib_gate_note'), 'Ignores sounds under 11 dB over the room (from your calibration).');
      expect(textOf(tester, 'calib_skipped'), 'none');
      expect(find.byKey(const Key('calib_missing')), findsNothing);
      expect(find.byKey(const Key('calib_pops_hint')), findsNothing);
      await tapKey(tester, 'calib_save');
      expect(find.byType(CalibrationScreen), findsNothing);
      expect(b.calibSaved['phone']!.homeHz, 142);
      expect(b.calibSaved['phone']!.needsRecalibration, isFalse);
      expect(calls(b), [
        'calib_start phone', 'calib_step glide', 'calib_step vowels', 'calib_step pops', 'calib_step clicks',
        'calib_step whistle', 'calib_step hiss', 'calib_step room', 'calib_save',
      ]);
    });

    testWidgets('live readout: waiting for a steady note, then pitch and progress', (tester) async {
      final b = await pumpCalib(tester, FakeBackend(initial: phoneCursor()));
      await tapKey(tester, 'calib_begin');
      b.emitCalib(st('hum', 'waiting', progress: 0));
      await tester.pumpAndSettle();
      expect(find.text('Waiting for a steady note...'), findsOneWidget);
      expect(textOf(tester, 'calib_pitch'), '-');
      b.emitCalib(st('hum', 'recording', progress: 0.6, live: {'voiced': true, 'pitch_hz': 142.4, 'level_db': -22.4}));
      await tester.pumpAndSettle();
      expect(find.text('Listening...'), findsOneWidget);
      expect(textOf(tester, 'calib_pitch'), '142 Hz (C#3)');
      expect(textOf(tester, 'calib_level'), '-22 dB');
      expect(tester.widget<PipMeter>(find.byType(PipMeter)).value, 6);
      b.emitCalib(st('vowels', 'recording', live: {'voiced': true, 'pitch_hz': 180.0, 'vowel': 'ee', 'vowel_conf': 0.82}));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('calib_vowel')), findsNothing); // still on the hum page
    });

    testWidgets('a failed step: the reason, Retry and Skip; the summary lists the skipped step', (tester) async {
      final b = FakeBackend(initial: phoneCursor(), calibAuto: true)
        ..calibFailOnce['glide'] = 'Range too small (3.1 st): glide wider.';
      await pumpCalib(tester, b);
      await tapKey(tester, 'calib_begin');
      await waitFor(tester, find.byKey(const Key('calib_next')));
      await tapKey(tester, 'calib_next');
      await waitFor(tester, find.byKey(const Key('calib_reason')));
      expect(textOf(tester, 'calib_reason'), 'Range too small (3.1 st): glide wider.');
      expect(find.byKey(const Key('calib_retry')), findsOneWidget);
      expect(find.byKey(const Key('calib_skip')), findsOneWidget);
      expect(find.byKey(const Key('calib_next')), findsNothing);
      // It waits: nothing is skipped or restarted by itself.
      final before = calls(b).length;
      await tester.pump(const Duration(seconds: 10));
      expect(find.byKey(const Key('calib_reason')), findsOneWidget);
      expect(calls(b).length, before);
      await tapKey(tester, 'calib_skip');
      expect(textOf(tester, 'calib_where'), 'phone mic · step 3 of 8');
      await nextToResult(tester);
      expect(textOf(tester, 'calib_range'), 'skipped');
      expect(textOf(tester, 'calib_skipped'), 'glide');
      expect(calls(b), [
        'calib_start phone', 'calib_step glide', 'calib_skip', 'calib_step pops', 'calib_step clicks',
        'calib_step whistle', 'calib_step hiss', 'calib_step room',
      ]);
    });

    testWidgets('Retry records the failed step again', (tester) async {
      final b = FakeBackend(initial: phoneCursor(), calibAuto: true)..calibFailOnce['hum'] = 'Too short or too rough.';
      await pumpCalib(tester, b);
      await tapKey(tester, 'calib_begin');
      await waitFor(tester, find.byKey(const Key('calib_retry')));
      await tapKey(tester, 'calib_retry');
      expect(calls(b).last, 'calib_retry');
      expect(find.byKey(const Key('calib_reason')), findsNothing);
      await waitFor(tester, find.byKey(const Key('calib_next')));
      expect(find.text('Done.'), findsOneWidget);
    });

    testWidgets('fewer than 2 pops: the hint names the badge, never a keyboard; Redo pops', (tester) async {
      final b = FakeBackend(initial: phoneCursor(), calibAuto: true, calibPops: 1);
      await pumpCalib(tester, b);
      await tapKey(tester, 'calib_begin');
      await nextToResult(tester);
      expect(textOf(tester, 'calib_pops'), '1/3');
      final hint = textOf(tester, 'calib_pops_hint');
      expect(hint, contains('badge'));
      expect(hint.toLowerCase(), isNot(contains('key')));
      await tapKey(tester, 'calib_redo_pops');
      expect(calls(b).last, 'calib_redo pops');
      await waitFor(tester, find.text('See result'));
      await tapKey(tester, 'calib_next');
      expect(find.byKey(const Key('calib_save')), findsOneWidget);
    });

    testWidgets('clicks: Skip until a click is heard; the room: a long reason wraps, Skip keeps the defaults',
        (tester) async {
      const long = 'a sound in the room was as loud as your quietest calibrated sound (14 dB over the floor, yours '
          '13 dB): make the room quieter and retry, or skip';
      final b = FakeBackend(initial: phoneCursor(), calibAuto: true)..calibFailOnce['room'] = long;
      await pumpCalib(tester, b);
      await tapKey(tester, 'calib_begin');
      while (!textOf(tester, 'calib_where').endsWith('step 5 of 8')) {
        await waitFor(tester, find.byKey(const Key('calib_next')));
        await tapKey(tester, 'calib_next');
      }
      await waitFor(tester, find.text('Listening...'));
      expect(textOf(tester, 'calib_heard'), '0/3');
      expect(find.byKey(const Key('calib_skip')), findsOneWidget); // nothing heard yet: skippable
      await waitFor(tester, find.text('1/3'));
      expect(find.byKey(const Key('calib_skip')), findsNothing);
      while (!textOf(tester, 'calib_where').endsWith('step 8 of 8')) {
        await waitFor(tester, find.byKey(const Key('calib_next')));
        await tapKey(tester, 'calib_next');
      }
      expect(find.byKey(const Key('calib_skip')), findsOneWidget); // the room: any time
      await waitFor(tester, find.byKey(const Key('calib_reason')));
      expect(textOf(tester, 'calib_reason'), long);
      expect(tester.takeException(), isNull); // wrapped, no overflow
      await tapKey(tester, 'calib_skip');
      expect(find.byKey(const Key('calib_save')), findsOneWidget);
      expect(textOf(tester, 'calib_room'), 'skipped');
      expect(textOf(tester, 'calib_skipped'), 'room');
      expect(calls(b).last, 'calib_skip');
    });

    testWidgets('Back cancels; accessibility guidelines hold', (tester) async {
      final handle = tester.ensureSemantics();
      final b = await pumpCalib(tester, FakeBackend(initial: phoneCursor(), calibAuto: true));
      await tapKey(tester, 'calib_begin');
      await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
      await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
      await expectLater(tester, meetsGuideline(textContrastGuideline));
      await tapKey(tester, 'calib_back');
      expect(find.byType(CalibrationScreen), findsNothing);
      expect(calls(b).last, 'calib_cancel');
      handle.dispose();
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

    testWidgets('cursor mode on the phone mic, not calibrated: the prompt opens the setup', (tester) async {
      await pumpStatus(tester, FakeBackend(initial: phoneCursor({'calibrated': false})));
      await tapKey(tester, 'calib_prompt_start');
      expect(find.byType(CalibrationScreen), findsOneWidget);
      expect(textOf(tester, 'calib_source'), 'phone mic');
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
      expect(find.byType(CalibrationScreen), findsOneWidget);
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
      expect(find.byType(CalibrationScreen), findsOneWidget);
    });

    testWidgets('a v1 profile: the nudge records only the 4 new steps and keeps the rest', (tester) async {
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
      expect(textOf(tester, 'calib_steps'), 'clicks, whistle, hiss, room');
      expect(textOf(tester, 'calib_intro'), contains('4 new steps'));
      expect(textOf(tester, 'calib_where'), 'phone mic · about 20 s');
      await tapKey(tester, 'calib_begin');
      expect(textOf(tester, 'calib_where'), 'phone mic · step 1 of 4');
      await nextToResult(tester);
      expect(textOf(tester, 'calib_home'), '142 Hz (C#3)'); // kept from the saved profile
      expect(textOf(tester, 'calib_clicks'), '3/3');
      expect(find.byKey(const Key('calib_missing')), findsNothing);
      expect(find.byKey(const Key('calib_redo_hum')), findsNothing);
      expect(find.byKey(const Key('calib_redo_room')), findsOneWidget);
      await tapKey(tester, 'calib_save');
      expect(calls(b), [
        'calib_start phone,clicks+whistle+hiss+room', 'calib_step whistle', 'calib_step hiss', 'calib_step room',
        'calib_save',
      ]);
      expect(b.calibSaved['phone']!.needsRecalibration, isFalse);
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('calib_nudge')), findsNothing);
      expect(textOf(tester, 'calib_state_phone'), 'calibrated, in use');
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
      await b.calibRedo('pops');
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
        'calib_redo {step: pops}', 'calib_retry null',
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
