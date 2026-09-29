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

void main() {
  group('models', () {
    test('train_status parses the service contract', () {
      final s = TrainStatus.fromMap({
        'active': true, 'source': 'phone', 'current_source': 'phone', 'profile': 'default', 'live_trace': true,
        'blocked': null, 'done': 9, 'total': 48,
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
        'sources': {'phone': {'done': 9, 'total': 48}, 'pico': {'done': 0, 'total': 48}},
        'unconfirmed': [
          {'id': 42, 'gesture': 'rise', 'heard': 'arch', 'pos': 3},
        ],
      });
      expect(s.trainable, isTrue);
      expect(s.gesture('arch')!.complete, isTrue);
      expect(s.gesture('arch')!.cells.single.tags['speed'], 'slow');
      expect(s.sources['phone'], (9, 48));
      final x = s.session!;
      expect((x.state, x.index, x.count, x.canKeep), ('failed', 2, 8, true));
      expect(x.heard!.label, 'dip');
      expect(x.heard!.pitch16, [0, -1.5, -3]);
      expect(x.live.traceHz, [null, 210.5, 220.0]);
      expect(x.kept, ['b']);
      expect(x.reasons, ['label']);
      // the takes to check: Kotlin's numeric id and the heard label as a plain string
      expect([for (final u in s.unconfirmed) (u.id, u.gesture, u.heard, u.pos)], [(42, 'rise', 'arch', 3)]);
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
        return {'active': call.method != 'train_cancel', 'source': 'phone', 'done': 1, 'total': 48};
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
      await t.delete('click', cell: 'soft-1', source: 'usb');
      await t.goto('arch', 'hum-high-quick');
      await t.confirm(17, keep: false);
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
        'train_delete {gesture: click, cell: soft-1, source: usb}',
        'train_goto {gesture: arch, cell: hum-high-quick}',
        'train_confirm {id: 17, keep: false}',
        'train_cancel',
      ]);
      // Kotlin's train_status call on the same channel
      await TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.handlePlatformMessage(
        ch.name,
        ch.codec.encodeMethodCall(const MethodCall('train_status', {'active': true, 'done': 7, 'total': 48})),
        (_) {},
      );
      await Future<void>.delayed(Duration.zero);
      expect(pushed.last.done, 7);
      expect(pushed.length, 13); // every answer, then the push
      await sub.cancel();
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
        ..fill('click', src: 'usb');
      useTrainBackend(b, t);
      await tester.pumpWidget(VoxUiApp(backend: b));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('train_entry')), findsOneWidget);
      expect(textOf(tester, 'train_entry_note'), 'phone mic: 8 of 48 takes recorded.');
      await tapKey(tester, 'train_open');
      expect(find.byType(HubScreen), findsOneWidget);
      expect(find.text('TRAIN GESTURES 8/48'), findsOneWidget);
      expect(find.byKey(const Key('hub_train_pop')), findsNothing);
      await tapKey(tester, 'hub_back');
      expect(find.byType(HubScreen), findsNothing);
    });
  });
}
