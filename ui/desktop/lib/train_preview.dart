import 'dart:math' as math;

import 'package:flutter/widgets.dart';
import 'package:vox_ui/vox_ui.dart';

/// VOX_PREVIEW=train: the gesture training screen on the in-memory [FakeTrainBackend], with a few cards already
/// recorded. VOX_PREVIEW_HOLD picks a still screen:
///
///   grid       the cards, the arch card open (5 of 8 recorded)
///   recording  a take of the arch round, the live pitch trace half drawn
///   failed     an arch take heard as a dip: the reason, Retry, Skip and Keep anyway
///   finished   the rise round's last take stored: the full card and the round's summary
///
/// Without a hold the screen is live: a take records for about 2 s with a made-up trace, and the first arch take
/// is heard as a dip, so both paths can be clicked through.
class TrainPreview {
  TrainPreview._(this.train, this.flow, this.hold);

  final FakeTrainBackend train;
  final TrainFlow flow;
  final String? hold;

  static TrainPreview create(FakeBackend backend, String? hold) {
    final t = FakeTrainBackend(source: 'phone', autoTake: hold == null ? const Duration(milliseconds: 2200) : null)
      ..fill('rise', cells: ['hum-low-slow', 'hum-low-quick', 'hum-high-slow', 'hum-high-quick', 'whistle-low-slow',
          'whistle-low-quick', 'whistle-high-slow'])
      ..fill('arch', cells: ['hum-low-slow', 'hum-low-quick', 'hum-high-slow', 'hum-high-quick', 'whistle-low-slow'])
      ..fill('pop')
      ..fill('click', cells: ['soft-1', 'soft-2'])
      ..fill('rise', src: 'pico')
      ..fill('fall', src: 'pico', cells: ['hum-low-slow', 'hum-low-quick']);
    if (hold == null) t.outcomes.add(const FakeTake(label: 'dip'));
    useTrainBackend(backend, t);
    return TrainPreview._(t, TrainFlow(backend: t), hold);
  }

  Widget get screen => TrainScreen(train: train, flow: flow);

  /// Drives the flow to the held screen (after the first frame).
  Future<void> start() async {
    switch (hold) {
      case 'grid':
        await flow.refresh();
        flow.select('arch');
      case 'recording':
        await flow.startRound('arch');
        // a whistled arch from about 1.1 kHz, half way through
        train.trace([
          for (var i = 0; i < 20; i++) null,
          for (var i = 0; i < 45; i++) 1100 * math.pow(2, 4 * math.sin(math.pi * i / 80) / 12).toDouble(),
        ], levelDb: -27);
      case 'failed':
        await flow.startRound('arch');
        train.finishTake(const FakeTake(label: 'dip'));
      case 'finished':
        await flow.startRound('rise');
        train.finishTake();
        await flow.next();
    }
  }
}
