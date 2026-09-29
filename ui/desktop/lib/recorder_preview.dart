import 'package:flutter/material.dart';
import 'package:vox_ui/vox_ui.dart';

/// VOX_PREVIEW=recorder: the in-app test recorder on the [FakeRecorderBackend], with VOX_PREVIEW_HOLD picking a still
/// screen: start, hub, ready, countdown, recording, longest, room, saved, no_sound, rate, done. Without a hold it is live: a session
/// records takes by itself on the fake's auto clock. VOX_PREVIEW=quickrec shows the quick record screen, and
/// VOX_PREVIEW=shape shows the heard-vs-expected [ShapePlot] variants.
class RecorderPreview {
  RecorderPreview._(this.backend, this.rec, this.flow, this.hold);

  final FakeBackend backend;
  final FakeRecorderBackend rec;
  final RecorderFlow flow;
  final String? hold;

  static RecorderPreview create(FakeBackend backend, String? hold) {
    final r = FakeRecorderBackend(
      source: 'phone',
      auto: hold == null ? const Duration(milliseconds: 50) : null,
      scale: const PitchScale(lowHz: 96, homeHz: 142, highHz: 318),
    );
    useRecorderBackend(backend, r);
    return RecorderPreview._(backend, r, RecorderFlow(backend: r), hold);
  }

  Widget get screen => RecorderScreen(backend: backend, recorder: rec, flow: flow);

  Future<void> start() async {
    if (hold == null || hold == 'start') {
      if (hold == null) await flow.start(who: 'me', speaker: 'self', profile: 'short'); // live: the hub, then CONTINUE
      return;
    }
    await flow.start(who: 'me', speaker: 'self', profile: 'short');
    switch (hold) {
      case 'hub':
        break;
      case 'ready':
        await flow.next(takeId: 'rise');
      case 'countdown': // a far take
        await flow.next(takeId: 'arch');
        await _drive('countdown');
      case 'recording':
        await flow.next(takeId: 'rise');
        await _drive('recording');
        rec.advance(const Duration(milliseconds: 1200));
      case 'longest': // the spec's longest cue, recording
        await flow.next(takeId: 'media-90');
        await flow.go();
        rec.advance(const Duration(milliseconds: 2000));
      case 'room':
        await flow.next(takeId: 'room');
        await _drive('recording');
        rec.advance(const Duration(milliseconds: 1500));
      case 'saved':
        await flow.next(takeId: 'arch');
        await _drive('saved');
      case 'no_sound':
        rec.noSoundTakes.add('hiss');
        await flow.next(takeId: 'hiss');
        await _drive('no_sound');
      case 'rate':
        await flow.next(takeId: 'room');
        await _drive('rate');
      case 'done':
        for (final (first, block) in const [
          ('rise', 'contours'),
          ('click', 'discrete'),
          ('room', 'room'),
          ('media-90', 'backgrounds'),
        ]) {
          await flow.next(takeId: first);
          for (var i = 0; i < 400 && rec.state != 'rate'; i++) {
            if (rec.state == 'ready' && rec.calls.last != 'rec_go') {
              try {
                await rec.recGo(); // the manual background
              } on RecCommandError catch (_) {}
            }
            if (rec.state == 'saved') {
              rec.advance(const Duration(milliseconds: 1600));
              if (rec.state == 'saved') await flow.next();
            }
            rec.advance(const Duration(milliseconds: 100));
          }
          await flow.rate(block: block, rating: 3);
        }
    }
  }

  Future<void> _drive(String state) async {
    for (var i = 0; i < 2000 && rec.state != state; i++) {
      rec.advance(const Duration(milliseconds: 100));
    }
  }
}

/// VOX_PREVIEW=shape: the heard-vs-expected plot in its four looks.
class ShapePreview {
  static const scale = PitchScale(lowHz: 96, homeHz: 142, highHz: 318);
  static const heard = [
    HeardSound(label: 'rise', relMs: 100, durMs: 600, pitch16: [0, 1, 2, 3, 4, 4, 3, 2, 1, 0], f0Hz: 142),
  ];

  static Widget screen() {
    return Scaffold(
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(8),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _panel(
                'contour · absolute',
                const ShapePlot(
                  expected: ExpectedShape(sequence: ['rise'], start: 'home'),
                  scale: scale,
                  heard: heard,
                  checks: [ShapeCheck('pitch', 'pitch', CheckState.ok), ShapeCheck('shape', 'shape', CheckState.near)],
                ),
              ),
              const SizedBox(height: 12),
              _panel(
                'contour · relative',
                const ShapePlot(
                  expected: ExpectedShape(sequence: ['arch']),
                  heard: [HeardSound(label: 'arch', relMs: 100, durMs: 600, pitch16: [0, 2, 4, 2, 0], f0Hz: 142)],
                ),
              ),
              const SizedBox(height: 12),
              _panel(
                'beat strip',
                const ShapePlot(
                  expected: ExpectedShape(sequence: ['click', 'click'], gapS: 0.35),
                  heard: [HeardSound(label: 'click', relMs: 50, durMs: 150)],
                  checks: [ShapeCheck('count', 'count', CheckState.miss)],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  static Widget _panel(String title, Widget child) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(padding: const EdgeInsets.only(bottom: 4), child: Text(title, style: const TextStyle(fontWeight: FontWeight.bold))),
          child,
        ],
      );
}
