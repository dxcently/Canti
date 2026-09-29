import 'dart:math' as math;

import 'package:flutter/widgets.dart';
import 'package:vox_ui/vox_ui.dart';

/// VOX_PREVIEW=train: gesture training on the in-memory [FakeTrainBackend], with a few gestures already recorded.
/// VOX_PREVIEW_HOLD picks a still screen:
///
///   recording  an arch take, the live pitch trace half drawn, the checks pending
///   failed     an arch take heard as a dip: the heard-vs-wanted miss view
///   passed     an arch take stored (the move to the next take is held off)
///   off        Canti in cursor mode: the "Canti can't hear" banner
///   review     a take to check: "Canti heard ARCH. Keep as RISE?"
///
/// Without a hold it is the tests hub, live: a take records for about 2 s with a made-up trace, and the first arch
/// take is heard as a dip, so both paths can be clicked through.
class TrainPreview {
  TrainPreview._(this.train, this.backend, this.hold);

  final FakeTrainBackend train;
  final FakeBackend backend;
  final String? hold;

  static TrainPreview create(FakeBackend backend, String? hold) {
    final t = FakeTrainBackend(source: 'phone', autoTake: hold == null ? const Duration(milliseconds: 2200) : null)
      ..scale = const {'low_hz': 110.0, 'home_hz': 147.0, 'high_hz': 262.0}
      ..fill('rise', cells: ['hum-low-slow', 'hum-low-quick', 'hum-high-slow', 'hum-high-quick', 'whistle-low-slow',
          'whistle-low-quick', 'whistle-high-slow'])
      ..fill('pop')
      ..fill('click', cells: ['soft-1', 'soft-2'])
      ..fill('rise', src: 'pico');
    if (hold == null) t.outcomes.add(const FakeTake(label: 'dip'));
    if (hold == 'passed') t.autoAdvance = const Duration(days: 1);
    if (hold == 'off') {
      t
        ..blocked = 'Canti is in cursor mode: gestures are off.'
        ..blockedAction = 'gesture_mode';
    }
    if (hold == 'review') {
      t.unconfirmed.add({
        'id': 12, 'gesture': 'rise', 'heard': 'arch', 'pos': 4,
        'pitch16': fakePitch16('arch'), 'f0_hz': 180, 'dur_ms': 1400,
      });
    }
    useTrainBackend(backend, t);
    return TrainPreview._(t, backend, hold);
  }

  Widget get screen => switch (hold) {
        null => HubScreen(backend: backend, source: 'phone', train: train),
        'review' => ReviewScreen(
            backend: backend,
            train: train,
            take: TrainUnconfirmed(
                id: 12, gesture: 'rise', heard: 'arch', pos: 4, pitch16: fakePitch16('arch'), f0Hz: 180, durMs: 1400)),
        _ => TrainTakeScreen(backend: backend, train: train, gesture: 'arch', cell: 'hum-low-slow'),
      };

  /// An arch from about 118 Hz (a LOW start), [n] ticks of it after a short silence.
  static List<double?> arch(int n) => [
        for (var i = 0; i < 6; i++) null,
        for (var i = 0; i < n; i++) 118 * math.pow(2, 5 * math.sin(math.pi * i / 70) / 12).toDouble(),
      ];

  /// Drives the take to the held screen (after the first frame; the screen has opened the take by then).
  Future<void> start() async {
    if (!const ['recording', 'failed', 'passed'].contains(hold)) return;
    await Future<void>.delayed(const Duration(milliseconds: 200));
    await train.record();
    switch (hold) {
      case 'recording':
        train.trace(arch(35), levelDb: -27);
      case 'failed':
        train.finishTake(const FakeTake(label: 'dip'));
      case 'passed':
        train.trace(arch(70), levelDb: -27);
        train.finishTake();
    }
  }
}
