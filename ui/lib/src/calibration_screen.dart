import 'package:flutter/material.dart';

import 'backend.dart';
import 'calibration.dart';
import 'hub_screen.dart';
import 'theme/glyphs.dart';
import 'theme/kit.dart';
import 'theme/pixel.dart';

/// Opens the voice cursor's setup for [source]: the tests hub (calibration + gesture training; a profile's missing
/// steps show there as not done). Completes with true when the hub closes, so the caller re-reads the profile (each
/// step is saved as it finishes; there is no single save to wait for). [steps] is kept for the callers: the hub lists
/// every step and RUN THE REST runs the undone ones.
Future<bool> openCalibration(BuildContext context, VoxBackend backend, String source, {List<String>? steps}) async {
  await openHub(context, backend, source: source);
  return true;
}

/// The stat rows of a calibration (a result or a saved profile): home note, range, each vowel, clicks, the
/// whistle range, hiss, the room's floor, the level gate, voicing, the skipped steps and the missing ones. A skipped
/// step's values are null: "skipped"; a missing one's: "not yet".
List<(Glyph, String, String, Key?)> calibSummaryRows(Map<String, Object?> m) {
  final r = CalibResult.fromMap(m)!;
  final skipped = r.skipped.toSet();
  final missing = r.missingSteps.toSet();
  String pct(double? v) => v == null ? '-' : '${(v * 100).round()}%';
  String or(String step, String v) => skipped.contains(step) ? 'skipped' : missing.contains(step) ? 'not yet' : v;
  String hz(double? lo, double? hi) => lo == null || hi == null ? '-' : '${lo.round()}-${hi.round()} Hz';
  String n(int? v, int of) => v == null ? '-' : '$v/$of';
  final gate = r.levelGate;
  List<String> inOrder(Set<String> s) => [for (final k in calibSteps) if (s.contains(k)) k];
  return [
    (Icons7.sound, 'Home', or('hum', hzLabel(r.homeHz)), const Key('calib_home')),
    (Icons7.cursor, 'Range', or('glide', hz(r.rangeLoHz, r.rangeHiHz)), const Key('calib_range')),
    for (final v in const ['ee', 'ah', 'oo']) (Icons7.decider, v, or('vowels', pct(r.vowelAcc[v])), Key('calib_acc_$v')),
    (Icons7.target, 'Clicks', or('clicks', n(r.clicksHeard, 3)), const Key('calib_clicks')),
    (Icons7.cursor, 'Whistle', or('whistle', hz(r.whistleLoHz, r.whistleHiHz)), const Key('calib_whistle')),
    (Icons7.target, 'Hiss', or('hiss', n(r.hissHeard, 2)), const Key('calib_hiss')),
    (Icons7.power, 'Room', or('room', r.roomFloorDbfs == null ? '-' : '${r.roomFloorDbfs!.round()} dBFS'),
        const Key('calib_room')),
    (Icons7.power, 'Gate', gate == null ? '-' : '${gate.minSnrDb.round()} dB, ${gate.from}', const Key('calib_gate')),
    (Icons7.power, 'Voicing', or('hum', r.voicingThreshold?.toStringAsFixed(2) ?? '-'), const Key('calib_voicing')),
    (Icons7.bang, 'Skipped', skipped.isEmpty ? 'none' : inOrder(skipped).join(', '), const Key('calib_skipped')),
    if (missing.isNotEmpty) (Icons7.bang, 'Missing', inOrder(missing).join(', '), const Key('calib_missing')),
  ];
}

/// Stat rows on an inverted panel (the settings' saved profile).
class CalibPanel extends StatelessWidget {
  const CalibPanel({super.key, required this.rows});

  final List<(Glyph, String, String, Key?)> rows;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    return InvertedPanel(
      child: Column(
        children: [
          for (final (i, (icon, label, value, key)) in rows.indexed) ...[
            if (i > 0) SizedBox(height: p(1)),
            StatRow(icon: icon, label: label, value: value, valueKey: key),
          ],
        ],
      ),
    );
  }
}
