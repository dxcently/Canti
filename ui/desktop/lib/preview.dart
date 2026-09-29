import 'dart:async';

import 'package:flutter/material.dart';
import 'package:vox_ui/vox_ui.dart';
// ignore: implementation_imports
import 'package:vox_ui/src/theme/pixel.dart' show Px;

import 'train_preview.dart'; // [train]
import 'recorder_preview.dart'; // [rec]

/// The desktop preview of the voice cursor screens, on the in-memory backend's made-up `calib_status` stream
/// (a push every 100 ms, as the service sends them). Picked by VOX_PREVIEW:
///
///   calibrate  the tests hub for the phone mic, or a held calibration step ([CalibPreview])
///   cursor     the status screen in cursor mode on an uncalibrated phone mic: the first-run prompt and the
///              Voice cursor window
///   settings   the Voice cursor window alone
///   pair       the pair screen (its header, for comparing)
///   train      the tests hub live, or a held training take (train_preview.dart; holds: recording, failed,
///              passed, off, review)
///   hub        the tests hub with some progress and a take to check
///
/// More knobs (all optional):
///   VOX_PREVIEW_HOLD=waiting|hum|glide|vowels|pops|clicks|whistle|hiss|room|failed   calibrate: that step, held still
///   VOX_PREVIEW_FAIL=STEP   that step fails once with a made-up reason (hold `failed` shows it)
///   VOX_PREVIEW_POPS=N       the pops the fake hears (under 2 shows the badge hint)
///   VOX_PREVIEW_SAVED=1|v1    cursor/settings: the phone mic has a saved profile (v1: saved before calibration v2)
class Preview {
  Preview._(this.backend, this.home, this._start);

  final FakeBackend backend;
  final Widget? home;
  final void Function() _start;

  /// Starts the autopilot, if any (after the first frame).
  void start() => _start();

  /// The engine's failure reasons (PROTOCOL.md "Voice joystick" > Calibration), per step.
  static const failReasons = {
    'hum': "too short or too rough (12 steady ticks, need 40): a relaxed 'mm', 3 s",
    'glide': 'too small or too short (2.8 st, 31 steady ticks; need 4 st, 50 ticks): glide from your lowest to your '
        'highest and back',
    'vowels': "only 12 clear frames of 'ah' in 4 s (need 30): hold it steady for 2 s",
    'pops': 'heard 1/3 pops, need 2 (pop your lips a bit louder, a second apart)',
    'clicks': 'heard 1/3 clicks, need 2 (click your tongue a bit louder, about a second apart)',
    'whistle': 'the whistle overlaps your voice range (whistle from 610 Hz, voice up to 640 Hz): whistle higher, or skip',
    'hiss': "heard 1/2 hisses, need 2 (a short, sharp 'tss', a bit louder)",
    'room': 'a sound in the room was as loud as your quietest calibrated sound (14 dB over the floor, yours 13 dB): '
        'make the room quieter and retry, or skip',
  };

  /// A saved profile: all eight steps (v2), or one saved before calibration v2 (its four new steps missing).
  static CalibResult savedProfile({required bool v1, int pops = 3}) => CalibResult.fromMap({
        'source': 'phone', 'version': 2, 'saved_at_ms': DateTime(2026, 9, 27, 10, 4).millisecondsSinceEpoch,
        'home_hz': 142.0, 'range_lo_hz': 96.0, 'range_hi_hz': 318.0, 'voicing_threshold': 0.42,
        'vowels': {'ee': {'acc': 0.93}, 'ah': {'acc': 0.81}, 'oo': {'acc': 0.88}}, 'pops_heard': pops,
        'skipped': <String>[],
        if (v1) ...{
          'level_gate': {'min_snr_db': 6.0, 'min_level_dbfs': -60.0, 'from': 'default', 'n': 0},
          'missing_steps': ['clicks', 'whistle', 'hiss', 'room'],
          'needs_recalibration': true,
        } else ...{
          'clicks_heard': 3, 'hiss_heard': 2, 'whistle_lo_hz': 880.0, 'whistle_hi_hz': 2350.0, 'whistle_home_hz': 1400.0,
          'room_floor_dbfs': -63.0, 'relabel_rule': true,
          'level_gate': {'min_snr_db': 11.0, 'min_level_dbfs': -52.0, 'from': 'calibration', 'n': 8},
          'missing_steps': <String>[], 'needs_recalibration': false,
        },
      })!;

  /// null: VOX_PREVIEW is not set (the normal demo).
  static Preview? fromEnv(Map<String, String> env) {
    final kind = env['VOX_PREVIEW'];
    if (kind == null || kind.isEmpty) return null;
    final hold = env['VOX_PREVIEW_HOLD'];
    final fail = env['VOX_PREVIEW_FAIL'] ?? (hold == 'failed' ? 'glide' : null);
    final savedKind = env['VOX_PREVIEW_SAVED'];
    final saved = savedKind == '1' || savedKind == 'v1';
    final b = FakeBackend(
      initial: VoxStatus(
        service: true,
        armed: true,
        paused: false,
        mode: 'cursor',
        app: 'org.schabi.newpipe',
        decider: 'hybrid',
        bleState: 'off',
        soundSource: 'phone',
        vocab: 'fake',
        calibrated: saved,
      ),
      calibAuto: true,
      calibPops: int.tryParse(env['VOX_PREVIEW_POPS'] ?? '') ?? 3,
    );
    if (fail != null) b.calibFailOnce[fail] = failReasons[fail] ?? 'Too short: hold the sound a bit longer.';
    if (saved) b.calibSaved['phone'] = savedProfile(v1: savedKind == 'v1', pops: b.calibPops);
    switch (kind) {
      case 'calibrate':
        final c = CalibPreview(b, hold, fail);
        return Preview._(b, c.screen, c.start);
      case 'cursor':
        return Preview._(b, null, () {});
      case 'pair':
        return Preview._(b, PairScreen(backend: b), () {});
      case 'settings':
        return Preview._(b, _SettingsPage(backend: b), () {});
      case 'train': // [train]
        final t = TrainPreview.create(b, hold);
        return Preview._(b, t.screen, t.start);
      case 'hub': // [train] the round-7 tests hub (calibration + training + review)
        final t = FakeTrainBackend(source: 'phone')
          ..fill('rise', cells: ['hum-low-slow', 'hum-low-quick'])
          ..fill('pop');
        t.unconfirmed.add({
          'id': 1, 'gesture': 'arch', 'heard': 'dip', 'pos': 1,
        });
        useTrainBackend(b, t);
        return Preview._(b, HubScreen(backend: b, source: 'phone', train: t), () {});
      case 'recorder': // [rec]
        final t = RecorderPreview.create(b, hold);
        return Preview._(b, t.screen, t.start);
      case 'quickrec': // [rec]
        return Preview._(b, QuickRecScreen(backend: b), () {});
      case 'shape': // [rec]
        return Preview._(b, ShapePreview.screen(), () {});
    }
    throw ArgumentError('VOX_PREVIEW=$kind: expected calibrate, cursor, settings, pair, train, hub, recorder, quickrec or shape');
  }
}

/// VOX_PREVIEW=calibrate: the calibration step screen on the fake engine's made-up recordings. Without a hold, the
/// tests hub (RUN THE REST walks the steps; a v1 profile shows only its missing steps as not done). With a hold:
/// that step's screen, frozen part way through (`waiting`: the hum waiting for a steady note; `failed`: the failing
/// step's reason, see VOX_PREVIEW_FAIL).
class CalibPreview {
  CalibPreview(this.backend, this.hold, this.fail);

  final FakeBackend backend;
  final String? hold;
  final String? fail;
  StreamSubscription<CalibStatus>? _sub;
  int _waits = 0;

  Widget get screen {
    final step = switch (hold) {
      null => null,
      'waiting' => 'hum',
      'failed' => fail ?? 'glide',
      final s when calibSteps.contains(s) => s,
      _ => 'hum',
    };
    return step == null
        ? HubScreen(backend: backend, source: 'phone')
        : CalibStepScreen(backend: backend, source: 'phone', step: step);
  }

  void start() {
    if (hold == null || hold == 'failed') return;
    _sub = backend.calibStatus().listen((s) {
      if (hold == 'waiting' ? (s.waitingForSteady && ++_waits >= 4) : (s.step == hold && s.state == 'recording' && _heldEnough(s))) {
        backend.calibFreeze();
        _sub?.cancel();
      }
    });
  }

  // Far enough into a step that its live readout has something to show.
  static bool _heldEnough(CalibStatus s) => switch (s.step) {
        'pops' => s.popsN >= 2,
        'clicks' => s.clicksN >= 2,
        'hiss' => s.hissN >= 1,
        'vowels' => s.progress >= 0.4 && s.live.vowel != null,
        _ => s.progress >= 0.55,
      };
}

class _SettingsPage extends StatelessWidget {
  const _SettingsPage({required this.backend});

  final VoxBackend backend;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    return Scaffold(
      body: SafeArea(
        child: SingleChildScrollView(
          padding: EdgeInsets.all(p(5)),
          child: VoiceCursorWindow(backend: backend, source: 'phone'),
        ),
      ),
    );
  }
}
