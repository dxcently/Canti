import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vox_ui/vox_ui.dart';

/// The service answers a refused calib_* command with `error` inside the status map (not a platform exception):
/// the hub's controller must show it as the plain message.
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

  test('a refused calib_save shows its error in plain words', () async {
    final c = CalibController(backend: ChannelBackend(methods: ch), source: 'phone')..attach();
    await c.start();
    expect(c.error, isNull);
    await c.save();
    await pumpEventQueue();
    expect(calls, containsAllInOrder(['calib_start', 'calib_save']));
    expect(c.error, 'the phone mic is off');
    c.dispose();
  });
}
