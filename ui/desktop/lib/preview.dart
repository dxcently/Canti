import 'dart:async';

import 'package:flutter/material.dart';
import 'package:vox_ui/vox_ui.dart';
// ignore: implementation_imports
import 'package:vox_ui/src/theme/pixel.dart' show Px;

import 'train_preview.dart'; // [train]

/// The desktop preview of the voice cursor screens, on the in-memory backend's made-up `calib_status` stream
/// (a push every 100 ms, as the service sends them). Picked by VOX_PREVIEW:
///
///   calibrate  the setup screen for the phone mic, walked through by [CalibAutopilot] (Begin, then Next once each
///              step is done, to the result)
///   cursor     the status screen in cursor mode on an uncalibrated phone mic: the first-run prompt and the
///              Voice cursor window
///   settings   the Voice cursor window alone
///   pair       the pair screen (its header, for comparing)
///   train      the gesture training screen (train_preview.dart; holds: grid, recording, failed, finished)
///
/// More knobs (all optional):
///   VOX_PREVIEW_HOLD=intro|waiting|hum|glide|vowels|pops|clicks|whistle|hiss|room|failed|result   stop there, hold still
///   VOX_PREVIEW_FAIL=STEP   that step fails once with a made-up reason; the autopilot skips it (or holds: `failed`)
///   VOX_PREVIEW_POPS=N       the pops the fake hears (under 2 shows the badge hint)
///   VOX_PREVIEW_SAVED=1|v1    cursor/settings: the phone mic has a saved profile (v1: saved before calibration v2)
///   VOX_PREVIEW_STEPS=missing calibrate: only the saved profile's missing steps (with VOX_PREVIEW_SAVED=v1)
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
    // VOX_PREVIEW_STEPS=missing: only the saved profile's missing steps (with VOX_PREVIEW_SAVED=v1)
    final steps = env['VOX_PREVIEW_STEPS'] == 'missing' ? b.calibSaved['phone']?.missingSteps : null;
    switch (kind) {
      case 'calibrate':
        final flow = CalibFlow(backend: b, source: 'phone', steps: steps);
        final pilot = CalibAutopilot(flow, b, hold: hold);
        return Preview._(b, CalibrationScreen(backend: b, source: 'phone', flow: flow), pilot.start);
      case 'cursor':
        return Preview._(b, null, () {});
      case 'pair':
        return Preview._(b, PairScreen(backend: b), () {});
      case 'settings':
        return Preview._(b, _SettingsPage(backend: b), () {});
      case 'train': // [train]
        final t = TrainPreview.create(b, hold);
        return Preview._(b, t.screen, t.start);
    }
    throw ArgumentError('VOX_PREVIEW=$kind: expected calibrate, cursor, settings, pair or train');
  }
}

/// Presses the setup screen's buttons as a person would: Begin after a moment, Next once a step is done, Skip on a
/// failure; stops at the result, or at [hold] (then freezes the fake's recording so the screen holds still).
class CalibAutopilot {
  CalibAutopilot(this.flow, this.backend, {this.hold, this.pause = const Duration(milliseconds: 900)});

  final CalibFlow flow;
  final FakeBackend backend;
  final String? hold;
  final Duration pause;
  bool _stopped = false;
  bool _acting = false;
  int _waits = 0;

  void start() {
    if (hold == 'intro') return;
    flow.addListener(_check);
    Timer(pause, flow.begin);
  }

  void _stop({bool freeze = false}) {
    _stopped = true;
    if (freeze) backend.calibFreeze();
    flow.removeListener(_check);
  }

  void _act(Future<void> Function() f) {
    if (_acting) return;
    _acting = true;
    Timer(pause, () async {
      try {
        if (!_stopped) await f();
      } finally {
        _acting = false;
      }
    });
  }

  void _check() {
    if (_stopped) return;
    final page = flow.page;
    final s = flow.pageStatus;
    if (page == CalibPage.result) return _stop();
    if (hold == 'waiting' && page == CalibPage.hum && s != null && s.waitingForSteady && ++_waits >= 4) {
      return _stop(freeze: true);
    }
    if (hold == page.name && s != null && s.state == 'recording' && _heldEnough(page, s)) {
      return _stop(freeze: true);
    }
    if (flow.pageFailure != null) {
      if (hold == 'failed') return _stop();
      return _act(flow.skip);
    }
    if (flow.pageDone && !flow.busy) _act(flow.next);
  }

  // Far enough into a step that its live readout has something to show.
  static bool _heldEnough(CalibPage page, CalibStatus s) => switch (page) {
        CalibPage.pops => s.popsN >= 2,
        CalibPage.clicks => s.clicksN >= 2,
        CalibPage.hiss => s.hissN >= 1,
        CalibPage.vowels => s.progress >= 0.4 && s.live.vowel != null,
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
