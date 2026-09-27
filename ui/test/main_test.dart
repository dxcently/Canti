import 'dart:io';

import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vox_ui/vox_ui.dart';

// The installed app crashed on open: main() built ChannelBackend (which sets a method call handler, so needs the
// binding's messenger) before the binding existed. Each test file runs in its own isolate, so the first test here
// still sees no binding, the same as main() on a phone.
void main() {
  test('ChannelBackend before the binding throws (what crashed on open)', () {
    expect(() => ChannelBackend(), throwsA(anything));
  });

  test('main() initialises the binding before it builds ChannelBackend', () {
    final src = File('lib/main.dart').readAsStringSync();
    final init = src.indexOf('WidgetsFlutterBinding.ensureInitialized()');
    final backend = src.indexOf('ChannelBackend(');
    expect(init, isNonNegative, reason: 'main() must call WidgetsFlutterBinding.ensureInitialized()');
    expect(backend, greaterThan(init), reason: 'ChannelBackend() must come after ensureInitialized()');
  });

  test('after ensureInitialized, ChannelBackend builds', () {
    TestWidgetsFlutterBinding.ensureInitialized();
    expect(WidgetsBinding.instance, isNotNull);
    expect(ChannelBackend.new, returnsNormally);
  });
}
