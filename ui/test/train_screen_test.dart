import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vox_ui/vox_ui.dart';

VoxStatus phone([Map<String, Object?> m = const {}]) => VoxStatus.fromMap({
      'service': true, 'armed': true, 'paused': false, 'mode': 'gesture', 'app': 'x.y', 'decider': 'rules',
      'sound_source': 'phone', 'mic_state': 'listening', ...m,
    });

String textOf(WidgetTester tester, String key) => tester.widget<Text>(find.byKey(Key(key))).data!;

Future<void> tapKey(WidgetTester tester, String key) async {
  await tester.ensureVisible(find.byKey(Key(key)));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(Key(key)));
  await tester.pumpAndSettle();
}

Future<FakeTrainBackend> pumpTrain(WidgetTester tester, FakeTrainBackend t) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.625;
  addTearDown(tester.view.reset);
  final b = FakeBackend(initial: phone());
  useTrainBackend(b, t);
  await tester.pumpWidget(VoxUiApp(backend: b, home: TrainScreen(train: t)));
  await tester.pumpAndSettle();
  return t;
}

/// Opens [gesture]'s card and records its missing takes: the first take is recording.
Future<void> startRound(WidgetTester tester, String gesture) async {
  await tapKey(tester, 'train_card_$gesture');
  await tapKey(tester, 'train_record_missing');
}

void main() {
  group('models', () {
    test('train_status parses the service contract', () {
      final s = TrainStatus.fromMap({
        'active': true, 'source': 'phone', 'current_source': 'phone', 'profile': 'default', 'live_trace': true,
        'blocked': null, 'done': 9, 'total': 52,
        'gestures': [
          {
            'name': 'arch', 'kind': 'contour', 'done': 8, 'total': 8, 'examples': 9, 'extra': 1, 'active': true,
            'kept': 1,
            'cells': [
              {'id': 'hum-low-slow', 'prompt': 'Hum a SLOW arch, starting LOW', 'done': true,
                'tags': {'tone': 'hum', 'pitch': 'low', 'speed': 'slow'}},
            ],
          },
        ],
        'session': {
          'source': 'phone', 'gesture': 'arch', 'state': 'failed', 'cell': 'hum-low-slow', 'prompt': 'P', 'hint': 'H',
          'index': 2, 'count': 8, 'next_prompt': 'N', 'reason': 'Heard a dip (down then up): an arch goes up then down.',
          'reasons': ['label'], 'can_keep': true, 'heard_n': 1, 'left_ms': null,
          'heard': {'label': 'dip', 'sounds': 1, 'labels': ['dip'], 'dur_ms': 1400, 'f0_hz': 212, 'start_hz': 230,
            'tone': 'hum', 'loudness': null, 'pitch16': [0, -1.5, -3], 'shape': 'goes down then up'},
          'live': {'trace_hz': [null, 210.5, 220], 'level_db': -31.5, 'pitch_hz': 220},
          'passed': ['a', 'b'], 'skipped': <String>[], 'kept': ['b'],
        },
        'sources': {'phone': {'done': 9, 'total': 52}, 'pico': {'done': 0, 'total': 52}},
      });
      expect(s.trainable, isTrue);
      expect(s.gesture('arch')!.complete, isTrue);
      expect(s.gesture('arch')!.cells.single.tags['speed'], 'slow');
      expect(s.sources['phone'], (9, 52));
      final x = s.session!;
      expect((x.state, x.index, x.count, x.canKeep), ('failed', 2, 8, true));
      expect(x.heard!.label, 'dip');
      expect(x.heard!.pitch16, [0, -1.5, -3]);
      expect(x.live.traceHz, [null, 210.5, 220.0]);
      expect(x.kept, ['b']);
      // the service off
      expect(TrainStatus.fromMap({'service': false, 'active': false, 'error': 'off'}).service, isFalse);
    });

    test('ChannelTrainBackend: method names, arguments, refusals and Kotlin pushes', () async {
      TestWidgetsFlutterBinding.ensureInitialized();
      const ch = MethodChannel('ai.vox/train.test');
      final seen = <String>[];
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(ch, (call) async {
        seen.add('${call.method} ${call.arguments ?? ''}'.trim());
        if (call.method == 'train_keep') return {'active': true, 'error': 'only a take with the wrong shape can be kept anyway'};
        return {'active': call.method != 'train_cancel', 'source': 'phone', 'done': 1, 'total': 52};
      });
      final t = ChannelTrainBackend(methods: ch);
      final pushed = <TrainStatus>[];
      final sub = t.pushes().listen(pushed.add);
      await t.status();
      await t.start('rise');
      await t.start('rise', cell: 'hum-low-slow');
      await t.record();
      await t.retry();
      await t.skip();
      await t.next(record: false);
      await expectLater(t.keep(), throwsA(isA<TrainCommandError>()));
      await t.delete('pop', cell: 'soft-1', source: 'usb');
      await t.cancel();
      expect(seen, [
        'train_status {}',
        'train_start {gesture: rise}',
        'train_start {gesture: rise, cell: hum-low-slow}',
        'train_record',
        'train_retry',
        'train_skip',
        'train_next {record: false}',
        'train_keep',
        'train_delete {gesture: pop, cell: soft-1, source: usb}',
        'train_cancel',
      ]);
      // Kotlin's train_status call on the same channel
      await TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.handlePlatformMessage(
        ch.name,
        ch.codec.encodeMethodCall(const MethodCall('train_status', {'active': true, 'done': 7, 'total': 52})),
        (_) {},
      );
      await Future<void>.delayed(Duration.zero);
      expect(pushed.last.done, 7);
      expect(pushed.length, 11); // every answer, then the push
      await sub.cancel();
    });
  });

  group('screen', () {
    testWidgets('the grid: a card per gesture with its progress; a full card; per-source totals', (tester) async {
      final t = FakeTrainBackend()
        ..fill('rise', cells: ['hum-low-slow', 'hum-low-quick', 'hum-high-slow', 'hum-high-quick', 'whistle-low-slow'])
        ..fill('pop')
        ..fill('click', src: 'pico', cells: ['soft-1']);
      await pumpTrain(tester, t);
      for (final g in trainGestures) {
        expect(find.byKey(Key('train_card_$g')), findsOneWidget);
      }
      expect(textOf(tester, 'train_count_rise'), '5/8');
      expect(textOf(tester, 'train_count_pop'), '4/4');
      expect(textOf(tester, 'train_count_hiss'), '0/4');
      expect(textOf(tester, 'train_where'), contains('9/52'));
      expect(find.text('9/52'), findsOneWidget); // the phone row
      expect(find.text('1/52'), findsOneWidget); // the pico row
      await tapKey(tester, 'train_card_rise');
      expect(find.byKey(const Key('train_card_window')), findsOneWidget);
      expect(find.text('Record missing (3)'), findsOneWidget);
      expect(find.text('Whistle a QUICK rise, starting HIGH'), findsOneWidget);
      // a full card has nothing to record, only Delete / redo
      await tapKey(tester, 'train_card_pop');
      expect(find.byKey(const Key('train_record_missing')), findsNothing);
      expect(find.byKey(const Key('train_delete')), findsOneWidget);
    });

    testWidgets('a round: one prompt at a time, the live trace, what was heard, Record next', (tester) async {
      final t = await pumpTrain(tester, FakeTrainBackend());
      await startRound(tester, 'arch');
      expect(t.calls, containsAllInOrder(['train_start arch', 'train_record']));
      expect(textOf(tester, 'train_prompt'), 'Hum a SLOW arch, starting LOW');
      expect(textOf(tester, 'train_take'), contains('take 1 of 8'));
      expect(textOf(tester, 'train_state'), startsWith('Listening'));
      expect(textOf(tester, 'train_next_prompt'), 'Next: Hum a QUICK arch, starting LOW');
      t.trace([null, 180, 190, 200, 210, 200, 190]);
      await tester.pump();
      expect(textOf(tester, 'train_trace_caption'), contains('Live pitch'));
      t.finishTake();
      await tester.pumpAndSettle();
      expect(textOf(tester, 'train_state'), 'Good: stored.');
      expect(textOf(tester, 'train_heard'), 'arch (goes up then down)');
      expect(textOf(tester, 'train_heard_tone'), 'hum, 190 Hz');
      expect(textOf(tester, 'train_heard_len'), '1.4 s');
      expect(t.stores['phone']!['arch']!.keys, ['hum-low-slow']);
      await tapKey(tester, 'train_next');
      expect(textOf(tester, 'train_prompt'), 'Hum a QUICK arch, starting LOW');
      expect(textOf(tester, 'train_state'), startsWith('Listening'));
    });

    testWidgets('a wrong shape stops with the reason: Retry, Skip or Keep anyway; nothing moves on by itself', (tester) async {
      final t = await pumpTrain(tester, FakeTrainBackend());
      await startRound(tester, 'arch');
      t.finishTake(const FakeTake(label: 'dip'));
      await tester.pumpAndSettle();
      expect(textOf(tester, 'train_reason'), 'Heard a dip (down then up): an arch goes up then down.');
      expect(find.byKey(const Key('train_retry')), findsOneWidget);
      expect(find.byKey(const Key('train_skip')), findsOneWidget);
      expect(find.byKey(const Key('train_keep')), findsOneWidget);
      expect(find.byKey(const Key('train_next')), findsNothing);
      expect(textOf(tester, 'train_heard'), 'dip (goes down then up)');
      // Retry records the same cell again
      await tapKey(tester, 'train_retry');
      expect(textOf(tester, 'train_prompt'), 'Hum a SLOW arch, starting LOW');
      expect(textOf(tester, 'train_state'), startsWith('Listening'));
      // wrong tone: no Keep anyway
      t.finishTake(const FakeTake(f0Hz: 900));
      await tester.pumpAndSettle();
      expect(textOf(tester, 'train_reason'), contains('hum it with your lips closed'));
      expect(find.byKey(const Key('train_keep')), findsNothing);
      await tapKey(tester, 'train_retry');
      t.finishTake(const FakeTake(label: 'rise'));
      await tester.pumpAndSettle();
      await tapKey(tester, 'train_keep');
      expect(textOf(tester, 'train_state'), 'Kept anyway and stored.');
      expect(t.stores['phone']!['arch']!['hum-low-slow'], isTrue);
      // Skip after a failure waits on the next prompt (Record), it does not record by itself
      await tapKey(tester, 'train_next');
      t.finishTake(const FakeTake(labels: ['rise', 'fall']));
      await tester.pumpAndSettle();
      expect(textOf(tester, 'train_reason'), 'Heard 2 sounds (rise then fall): make it one unbroken sound.');
      await tapKey(tester, 'train_skip');
      expect(textOf(tester, 'train_prompt'), 'Hum a SLOW arch, starting HIGH');
      expect(textOf(tester, 'train_state'), 'Press Record, then make the sound.');
      expect(find.byKey(const Key('train_record')), findsOneWidget);
    });

    testWidgets('a take that cannot start (paused) says why and waits', (tester) async {
      final t = await pumpTrain(tester, FakeTrainBackend(blocked: 'Canti is paused.'));
      expect(textOf(tester, 'train_blocked'), contains('Canti is paused.'));
      await startRound(tester, 'pop');
      expect(textOf(tester, 'train_reason'), 'Canti is paused.');
      t.blocked = null;
      await tapKey(tester, 'train_retry');
      expect(textOf(tester, 'train_prompt'), 'Pop your lips SOFTLY (1 of 2)');
      expect(textOf(tester, 'train_state'), startsWith('Listening'));
    });

    testWidgets('the last take finishes the round; Back to cards shows the full card; Delete / redo asks first',
        (tester) async {
      final t = FakeTrainBackend()..fill('hiss', cells: ['soft-1', 'soft-2', 'loud-1']);
      await pumpTrain(tester, t);
      await startRound(tester, 'hiss');
      expect(textOf(tester, 'train_prompt'), 'Hiss LOUDLY, about half a second (2 of 2)');
      t.finishTake();
      await tester.pumpAndSettle();
      expect(find.text('Finish'), findsOneWidget);
      await tapKey(tester, 'train_next');
      expect(textOf(tester, 'train_state'), 'Round done: 1 stored. Hiss: 4 of 4 takes. The matcher uses them.');
      expect(textOf(tester, 'train_count_hiss'), '4/4');
      await tapKey(tester, 'train_done');
      expect(find.byKey(const Key('train_session')), findsNothing);
      expect(textOf(tester, 'train_count_hiss'), '4/4');
      expect(find.byKey(const Key('train_card_window')), findsOneWidget); // the card stays open
      await tapKey(tester, 'train_delete');
      expect(textOf(tester, 'train_delete_confirm'), contains('Delete all 4 hiss takes'));
      expect(t.stores['phone']!['hiss']!.length, 4);
      await tapKey(tester, 'train_delete');
      expect(t.calls.last, 'train_delete hiss');
      expect(textOf(tester, 'train_count_hiss'), '0/4');
      expect(find.text('Record'), findsOneWidget);
    });

    testWidgets('Stop and Back end the round; stored takes stay', (tester) async {
      final t = await pumpTrain(tester, FakeTrainBackend());
      await startRound(tester, 'flat');
      expect(textOf(tester, 'train_prompt'), 'Hum a SHORT flat note, LOW');
      t.finishTake();
      await tester.pumpAndSettle();
      await tapKey(tester, 'train_stop');
      expect(t.calls.last, 'train_cancel');
      expect(textOf(tester, 'train_count_flat'), '1/8');
      await tapKey(tester, 'train_record_missing'); // the card stays open
      expect(textOf(tester, 'train_prompt'), 'Hum a LONG flat note, LOW');
      expect(textOf(tester, 'train_take'), contains('take 1 of 7'));
    });

    testWidgets('accessibility guidelines hold on the grid and in a round', (tester) async {
      final handle = tester.ensureSemantics();
      final t = FakeTrainBackend()..fill('rise');
      await pumpTrain(tester, t);
      await tapKey(tester, 'train_card_arch');
      await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
      await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
      await expectLater(tester, meetsGuideline(textContrastGuideline));
      await tapKey(tester, 'train_record_missing');
      t.finishTake(const FakeTake(label: 'dip'));
      await tester.pumpAndSettle();
      await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
      await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
      await expectLater(tester, meetsGuideline(textContrastGuideline));
      handle.dispose();
    });
  });

  group('status screen', () {
    testWidgets('the Train gestures entry shows per-source progress and opens the screen', (tester) async {
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 2.625;
      addTearDown(tester.view.reset);
      final b = FakeBackend(initial: phone());
      final t = FakeTrainBackend()
        ..fill('rise')
        ..fill('pop', src: 'usb');
      useTrainBackend(b, t);
      await tester.pumpWidget(VoxUiApp(backend: b));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('train_entry')), findsOneWidget);
      expect(textOf(tester, 'train_entry_note'), 'phone mic: 8 of 52 takes recorded.');
      await tapKey(tester, 'train_open');
      expect(find.byType(TrainScreen), findsOneWidget);
      expect(textOf(tester, 'train_count_rise'), '8/8');
      await tapKey(tester, 'train_back');
      expect(find.byType(TrainScreen), findsNothing);
    });
  });
}
