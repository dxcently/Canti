import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vox_ui/vox_ui.dart';

/// The service answers a refused calib_* command with `error` inside the status map (not a platform exception):
/// the flow must show it, and a refused `calib_save` must not read as saved.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const ch = MethodChannel('test.calib');
  final calls = <String>[];

  setUp(() {
    calls.clear();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(ch, (c) async {
      calls.add(c.method);
      final ok = {'active': true, 'source': 'phone', 'step': 'hum', 'state': 'waiting', 'skipped': <String>[]};
      return switch (c.method) {
        'calib_start' => ok,
        'calib_save' => {'active': false, 'source': 'phone', 'state': null, 'calibrated': false,
            'skipped': <String>[], 'error': 'the phone mic is off'},
        _ => ok,
      };
    });
  });
  tearDown(() =>
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(ch, null));

  test('a refused calib_save shows its error and is not saved', () async {
    final f = CalibFlow(backend: ChannelBackend(methods: ch), source: 'phone')..attach();
    await f.begin();
    expect(f.error, isNull);
    await f.save();
    await pumpEventQueue();
    expect(calls, containsAllInOrder(['calib_start', 'calib_save']));
    expect(f.saved, isFalse);
    expect(f.finished, isFalse);
    expect(f.error, contains('the phone mic is off'));
  });
}
