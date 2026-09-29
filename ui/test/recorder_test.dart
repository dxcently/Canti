import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vox_ui/vox_ui.dart';

VoxStatus _status({bool dev = true, String source = 'phone'}) => VoxStatus.fromMap({
      'service': true,
      'armed': true,
      'paused': false,
      'mode': 'gesture',
      'app': 'x.y',
      'decider': 'rules',
      'sound_source': source,
      'dev_recorder': dev,
    });

void _phone(WidgetTester tester) {
  tester.view.physicalSize = const Size(1080, 2640); // Z Flip 6 inner screen
  tester.view.devicePixelRatio = 2.6;
  addTearDown(tester.view.reset);
}

/// The recorder as the home page (no route to pop).
Future<FakeBackend> _pumpRec(WidgetTester tester, FakeRecorderBackend r, {VoxStatus? status}) async {
  _phone(tester);
  final b = FakeBackend(initial: status ?? _status());
  useRecorderBackend(b, r);
  await tester.pumpWidget(VoxUiApp(backend: b, home: RecorderScreen(backend: b, recorder: r)));
  await tester.pumpAndSettle();
  return b;
}

/// The recorder pushed over a page with an "open" button, so back and DONE can pop it.
Future<void> _pushRec(WidgetTester tester, FakeRecorderBackend r) async {
  _phone(tester);
  final b = FakeBackend(initial: _status());
  useRecorderBackend(b, r);
  await tester.pumpWidget(VoxUiApp(
    backend: b,
    home: Builder(
      builder: (context) => Scaffold(
        body: Center(
          child: TextButton(
            key: const Key('open'),
            onPressed: () => openRecorder(context, b, recorder: r),
            child: const Text('open'),
          ),
        ),
      ),
    ),
  ));
  await tester.tap(find.byKey(const Key('open')));
  await tester.pumpAndSettle();
}

/// Advances the fake's clock (and pumps) until its state reaches [state].
Future<void> _until(WidgetTester tester, FakeRecorderBackend r, String state) async {
  for (var i = 0; i < 800 && r.state != state; i++) {
    r.advance(const Duration(milliseconds: 100));
    await tester.pump();
  }
  expect(r.state, state);
  await tester.pump();
}

Future<void> _advanceUntil(FakeRecorderBackend r, String state) async {
  for (var i = 0; i < 800 && r.state != state; i++) {
    r.advance(const Duration(milliseconds: 100));
  }
  expect(r.state, state);
}

/// Records every take of a block (from [first]) and rates it.
Future<void> _doBlock(FakeRecorderBackend r, String first, String block, int rating) async {
  await r.recNext(takeId: first);
  for (var i = 0; i < 400 && r.state != 'rate' && r.state != 'done'; i++) {
    if (r.state == 'ready' && r.calls.last != 'rec_go') {
      try {
        await r.recGo(); // the manual background (a non-manual take goes by itself)
      } on RecCommandError catch (_) {}
    }
    if (r.state == 'saved') {
      r.advance(const Duration(milliseconds: 1600)); // SAVED_HOLD
      if (r.state == 'saved') await r.recNext(); // the next take is in another block or manual
    }
    r.advance(const Duration(milliseconds: 100));
  }
  expect(r.state, 'rate');
  await r.recRate(block: block, rating: rating);
}

Future<void> _tapDock(WidgetTester tester, String which) async {
  await tester.tap(find.byKey(Key('dock_$which')));
  await tester.pump();
  await tester.pump();
}

String _mainLabel(WidgetTester tester) =>
    tester.widget<Text>(find.descendant(of: find.byKey(const Key('dock_main')), matching: find.byType(Text))).data!;

void main() {
  group('models', () {
    test('rec_status parses defensively (unknown state -> idle), plan as maps or strings', () {
      final s = RecStatus.fromMap({
        'enabled': true,
        'active': true,
        'state': 'frobnicating',
        'take': {
          'take_id': 'rise',
          'block': 'contours',
          'i': 3,
          'n': 6,
          'expect': ['rise'],
          'cond': {'pitch': 'home'},
        },
        'heard': [
          {'label': 'rise', 'rel_ms': 0.0, 'dur_ms': 600, 'pitch16': [0, 1, 2], 'f0_hz': 142, 'did_text': 'no action'},
        ],
        'blocks': [
          {'id': 'contours', 'title': 'Contours', 'done': 2, 'total': 3, 'rating': null, 'skipped': 0},
        ],
        'plan': [
          {'take_id': 'rise', 'block': 'contours'},
          {'take_id': 'click', 'block': 'discrete'},
        ],
      });
      expect(s.state, 'idle');
      expect(s.take!.takeId, 'rise');
      expect(s.heard.single.pitch16, [0, 1, 2]);
      expect(s.blocks.single.rating, isNull);
      expect(s.plan, ['rise', 'click']);
      expect(s.firstTakeOf('discrete'), 'click');
      final strings = RecStatus.fromMap({
        'plan': ['a', 'b'],
      });
      expect(strings.plan, ['a', 'b']);
      expect(strings.firstTakeOf('x'), isNull);
    });

    test('blockStatus: ease, not rated, progress', () {
      expect(blockStatus(RecBlock.fromMap({'id': 'a', 'title': 'A', 'done': 3, 'total': 3, 'rating': 4})),
          contains('ease 4'));
      expect(blockStatus(RecBlock.fromMap({'id': 'a', 'title': 'A', 'done': 2, 'total': 3, 'skipped': 1})),
          contains('not rated'));
      expect(blockStatus(RecBlock.fromMap({'id': 'a', 'title': 'A', 'done': 1, 'total': 3})), contains('1/3'));
    });
  });

  testWidgets('start -> blocks -> take -> saved (heard vs expected) -> the far take counts down 3, 2', (tester) async {
    final r = FakeRecorderBackend();
    await _pumpRec(tester, r);
    expect(find.byKey(const Key('rec_start')), findsOneWidget);
    expect(find.text('Phone built-in mic'), findsOneWidget);
    await _tapDock(tester, 'main'); // START
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('rec_hub')), findsOneWidget);
    expect(r.calls.where((c) => c.startsWith('rec_start')), hasLength(1));
    await _tapDock(tester, 'main'); // CONTINUE
    await tester.pumpAndSettle();
    expect(r.calls.last, 'rec_next ');
    expect(find.byKey(const Key('rec_take')), findsOneWidget);
    expect(find.byKey(const Key('rec_cue')), findsOneWidget);
    expect(find.byKey(const Key('rec_ready')), findsOneWidget);
    // rise is a hand take: straight to recording, with the seconds and the one level meter
    await _until(tester, r, 'recording');
    expect(find.byKey(const Key('rec_seconds')), findsOneWidget);
    expect(find.byKey(const Key('rec_level')), findsOneWidget);
    expect(find.byKey(const Key('rec_countdown')), findsNothing);
    expect(_mainLabel(tester), 'STOP');
    await _until(tester, r, 'saved');
    expect(find.byKey(const Key('rec_saved')), findsOneWidget);
    expect(find.byKey(const Key('shape_plot_contour')), findsOneWidget);
    expect(find.textContaining('ignored: recording'), findsNothing); // every sound is dropped while recording
    // the next take (fall, table distance) counts down
    await _until(tester, r, 'countdown');
    expect(find.text('far take: get in place'), findsOneWidget);
    expect(tester.widget<Text>(find.byKey(const Key('rec_countdown'))).data, '3');
    r.advance(const Duration(seconds: 1));
    await tester.pump();
    expect(tester.widget<Text>(find.byKey(const Key('rec_countdown'))).data, '2');
  });

  testWidgets('no sound: saved and flagged; TRY AGAIN is rec_next on the same take (never rec_go)', (tester) async {
    final r = FakeRecorderBackend()..noSoundTakes.add('click');
    await _pumpRec(tester, r);
    await r.recStart(who: 'me', speaker: 'self', profile: 'short');
    await r.recNext(takeId: 'click');
    await _advanceUntil(r, 'no_sound');
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('rec_no_sound')), findsOneWidget);
    expect(find.text('Canti heard no sound.'), findsOneWidget);
    expect(find.textContaining('saved and flagged'), findsOneWidget);
    expect(find.textContaining('discard'), findsNothing);
    expect(_mainLabel(tester), 'TRY AGAIN');
    await _tapDock(tester, 'main');
    expect(r.calls.last, 'rec_next click');
    expect(r.calls, isNot(contains('rec_go')));
    await _until(tester, r, 'recording');
  });

  testWidgets('the room: "N s left"; block end: the rating; BLOCKS shows the block "not rated"', (tester) async {
    final r = FakeRecorderBackend();
    await _pumpRec(tester, r);
    await r.recStart(who: 'me', speaker: 'self', profile: 'short');
    await r.recNext(takeId: 'room'); // a one-take block
    await _until(tester, r, 'recording');
    expect(tester.widget<Text>(find.byKey(const Key('rec_room'))).data, '4'); // ceil(3.5 s max - 0 s)
    r.advance(const Duration(seconds: 2));
    await tester.pump();
    expect(tester.widget<Text>(find.byKey(const Key('rec_room'))).data, '2');
    await _until(tester, r, 'rate');
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('rec_rate')), findsOneWidget);
    expect(find.text('How easy was Room?'), findsOneWidget);
    expect(find.text('Pick 1 to 5 to go on.'), findsOneWidget);
    await _tapDock(tester, 'right'); // BLOCKS
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('rec_hub')), findsOneWidget);
    expect(find.descendant(of: find.byKey(const Key('rec_block_room')), matching: find.textContaining('not rated')),
        findsOneWidget);
    // CONTINUE goes back to the rating
    await _tapDock(tester, 'main');
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('rec_rate_4')));
    await tester.pumpAndSettle();
    await _tapDock(tester, 'main');
    await tester.pumpAndSettle();
    expect(r.calls, contains('rec_rate room 4'));
  });

  testWidgets('a block row goes to its first take, or on at the next unrecorded take in it', (tester) async {
    final r = FakeRecorderBackend();
    await _pumpRec(tester, r);
    await r.recStart(who: 'me', speaker: 'self', profile: 'short');
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('rec_block_discrete')));
    await tester.pumpAndSettle();
    expect(r.calls.last, 'rec_next click');
    await r.recAbort();
    await _doBlock(r, 'rise', 'contours', 3);
    await r.recNext(takeId: 'click');
    await _advanceUntil(r, 'saved');
    await r.recAbort();
    await tester.pumpAndSettle();
    // one take of discrete done: its row goes on at hiss
    await tester.tap(find.byKey(const Key('rec_block_discrete')));
    await tester.pumpAndSettle();
    expect(r.calls.last, 'rec_next hiss');
    // a finished block starts again from its first take
    await r.recAbort();
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('rec_block_contours')));
    await tester.pumpAndSettle();
    expect(r.calls.last, 'rec_next rise');
  });

  testWidgets('the header arrows move back and forth through the plan and stop at the ends', (tester) async {
    final r = FakeRecorderBackend();
    await _pumpRec(tester, r);
    await r.recStart(who: 'me', speaker: 'self', profile: 'short');
    await r.recNext(takeId: 'rise');
    await tester.pumpAndSettle();
    final pager = find.byKey(const Key('rec_pager'));
    Future<void> arrow(String tip) async {
      await tester.tap(find.descendant(of: pager, matching: find.byTooltip(tip)));
      await tester.pump();
      await tester.pump();
    }

    final n = r.calls.length;
    await arrow('Previous page'); // take 1: nothing before it (no wrap to the last take)
    expect(r.calls.length, n);
    await arrow('Next page');
    expect(r.calls.last, 'rec_next fall');
    await arrow('Next page');
    expect(r.calls.last, 'rec_next arch');
    await arrow('Previous page');
    expect(r.calls.last, 'rec_next fall');
    // the last take: forward does not wrap
    await r.recNext(takeId: 'media-90');
    await tester.pump();
    final m = r.calls.length;
    await arrow('Next page');
    expect(r.calls.length, m);
  });

  testWidgets('back from a take goes to the blocks (take dropped, session kept); back again closes; resume', (tester) async {
    final r = FakeRecorderBackend();
    await _pushRec(tester, r);
    await _tapDock(tester, 'main'); // START
    await tester.pumpAndSettle();
    await _tapDock(tester, 'main'); // CONTINUE
    await _until(tester, r, 'recording');
    await tester.binding.handlePopRoute(); // system back
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('rec_hub')), findsOneWidget);
    expect(r.calls, contains('rec_abort'));
    expect(r.calls, isNot(contains('rec_close')));
    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(r.calls, contains('rec_close'));
    expect(find.byKey(const Key('open')), findsOneWidget);
    // nothing is lost: the session is listed to resume
    await tester.tap(find.byKey(const Key('open')));
    await tester.pumpAndSettle();
    final name = r.sessions.keys.single;
    final row = find.byKey(Key('rec_session_$name'));
    expect(row, findsOneWidget);
    await tester.ensureVisible(row);
    await tester.pumpAndSettle();
    await tester.tap(row);
    await tester.pumpAndSettle();
    expect(r.calls.last, 'rec_open $name');
    expect(find.byKey(const Key('rec_hub')), findsOneWidget);
  });

  testWidgets('done: the pull line; DONE closes and leaves', (tester) async {
    final r = FakeRecorderBackend();
    await r.recStart(who: 'me', speaker: 'self', profile: 'short');
    await _doBlock(r, 'rise', 'contours', 3);
    await _doBlock(r, 'click', 'discrete', 2);
    await _doBlock(r, 'room', 'room', 5);
    await _doBlock(r, 'media-90', 'backgrounds', 4);
    expect(r.state, 'done');
    await _pushRec(tester, r);
    expect(find.byKey(const Key('rec_done')), findsOneWidget);
    expect(find.text('./dev env python3 suite/range_phone.py pull'), findsOneWidget);
    await _tapDock(tester, 'main'); // DONE
    await tester.pumpAndSettle();
    expect(r.calls, contains('rec_close'));
    expect(find.byKey(const Key('open')), findsOneWidget);
  });

  testWidgets('Pico: START is disabled and the dock says why', (tester) async {
    final r = FakeRecorderBackend(source: 'pico');
    await _pumpRec(tester, r, status: _status(source: 'pico'));
    expect(find.byKey(const Key('rec_start')), findsOneWidget);
    expect(tester.widget<Text>(find.byKey(const Key('dock_caption'))).data, contains('The Pico sends no audio'));
    expect(tester.widget<FilledButton>(find.byKey(const Key('dock_main'))).onPressed, isNull);
  });

  group('the dev gate', () {
    for (final dev in [false, true]) {
      testWidgets('dev_recorder $dev: the entry and the quickrec route are ${dev ? 'there' : 'gone'}', (tester) async {
        _phone(tester);
        final b = FakeBackend(initial: _status(dev: dev));
        final r = FakeRecorderBackend();
        useRecorderBackend(b, r);
        await tester.pumpWidget(VoxUiApp(backend: b));
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('rec_entry')), dev ? findsOneWidget : findsNothing);
        expect(find.byKey(const Key('quick_rec')), dev ? findsOneWidget : findsNothing);
        await r.qrSnap(); // the badge's QUICK REC
        b.openRoute('quickrec');
        await tester.pumpAndSettle();
        expect(find.byType(QuickRecScreen), dev ? findsOneWidget : findsNothing);
      });
    }
  });
}
