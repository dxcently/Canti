import 'package:flutter/material.dart';

import 'backend.dart';
import 'calibration.dart';
import 'calibration_screen.dart';
import 'theme/canti_theme.dart';
import 'theme/glyphs.dart';
import 'theme/kit.dart';
import 'theme/pixel.dart';

/// The voice cursor's settings section: cursor speed and pitch sensitivity (0.5..2.0, shown as %, stepped by 10%
/// with the pager's arrows), the level gate (on / off, and its strictness, -10..10 dB), which mics are calibrated (one
/// profile per source), the current mic's saved result, and Recalibrate. A profile with missing steps (saved before
/// calibration v2) shows a nudge that records only those. [version] changing (a calibration saved elsewhere) reloads it.
class VoiceCursorWindow extends StatefulWidget {
  const VoiceCursorWindow({super.key, required this.backend, required this.source, this.version, this.openCalibrate, this.onCalibrated});

  final VoxBackend backend;

  /// The current sound source: the one Recalibrate calibrates.
  final String source;
  final Listenable? version;

  /// Opens calibration through the status screen's guard (no stacking); null = open here directly (tests, the desktop).
  final Future<void> Function({List<String>? steps})? openCalibrate;

  /// After a calibration was saved from here.
  final VoidCallback? onCalibrated;

  @override
  State<VoiceCursorWindow> createState() => _VoiceCursorWindowState();
}

class _VoiceCursorWindowState extends State<VoiceCursorWindow> {
  CursorSettings? _settings;
  LevelGateSettings? _gate;
  final _profiles = <String, CalibResult?>{};
  final _unknown = <String>{};
  String? _error;

  @override
  void initState() {
    super.initState();
    widget.version?.addListener(_load);
    _load();
  }

  @override
  void didUpdateWidget(VoiceCursorWindow old) {
    super.didUpdateWidget(old);
    if (old.version != widget.version) {
      old.version?.removeListener(_load);
      widget.version?.addListener(_load);
    }
    if (old.source != widget.source) _load();
  }

  @override
  void dispose() {
    widget.version?.removeListener(_load);
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final s = await widget.backend.cursorSettings();
      if (mounted) setState(() => _settings = s);
    } catch (e) {
      _setError('settings: $e');
    }
    try {
      final g = await widget.backend.levelGateSettings();
      if (mounted) setState(() => _gate = g);
    } catch (e) {
      _setError('level gate: $e');
    }
    for (final src in calibSources) {
      try {
        final r = await widget.backend.calibGet(src);
        if (!mounted) return;
        setState(() {
          _profiles[src] = r;
          _unknown.remove(src);
        });
      } catch (_) {
        if (mounted) setState(() => _unknown.add(src));
      }
    }
  }

  void _setError(String e) {
    if (mounted) setState(() => _error = e);
  }

  Future<void> _set({double? speed, double? pitchSens}) async {
    final before = _settings;
    if (before == null) return;
    setState(() {
      _settings = before.copyWith(speed: speed, pitchSens: pitchSens);
      _error = null;
    });
    try {
      final n = await widget.backend.setCursorSettings(speed: speed, pitchSens: pitchSens);
      if (mounted) setState(() => _settings = n);
    } catch (e) {
      if (mounted) setState(() => _settings = before);
      _setError('settings: $e');
    }
  }

  Future<void> _setGate({bool? enabled, int? offsetDb}) async {
    final before = _gate;
    if (before == null) return;
    setState(() {
      _gate = before.copyWith(enabled: enabled, offsetDb: offsetDb);
      _error = null;
    });
    try {
      final n = await widget.backend.setLevelGateSettings(enabled: enabled, offsetDb: offsetDb);
      if (mounted) setState(() => _gate = n);
    } catch (e) {
      if (mounted) setState(() => _gate = before);
      _setError('level gate: $e');
    }
  }

  Future<void> _calibrate({List<String>? steps}) async {
    final open = widget.openCalibrate;
    if (open != null) {
      await open(steps: steps);   // the status screen's guard; its version bump reloads this window
      return;
    }
    final saved = await openCalibration(context, widget.backend, widget.source, steps: steps);
    if (!mounted) return;
    await _load();
    if (saved) widget.onCalibrated?.call();
  }
  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    final s = _settings;
    final g = _gate;
    final gap = SizedBox(height: p(4));
    final current = _profiles[widget.source];
    final known = _profiles.containsKey(widget.source);
    const eps = 1e-6;
    return PixelWindow(
      title: 'Voice cursor',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (_error != null) ...[
            SignalNote(signal: Signal.stop, text: _error!, textKey: const Key('cursor_error')),
            gap,
          ],
          _Stepper(
            name: 'Cursor speed',
            id: 'cursor_speed',
            text: s == null ? null : CursorSettings.percent(s.speed),
            onDown: s == null || s.speed <= CursorSettings.min + eps
                ? null
                : () => _set(speed: CursorSettings.snap(s.speed - CursorSettings.step)),
            onUp: s == null || s.speed >= CursorSettings.max - eps
                ? null
                : () => _set(speed: CursorSettings.snap(s.speed + CursorSettings.step)),
          ),
          SizedBox(height: p(2)),
          _Stepper(
            name: 'Pitch sensitivity',
            label: 'Pitch sens',
            id: 'cursor_pitch_sens',
            text: s == null ? null : CursorSettings.percent(s.pitchSens),
            onDown: s == null || s.pitchSens <= CursorSettings.min + eps
                ? null
                : () => _set(pitchSens: CursorSettings.snap(s.pitchSens - CursorSettings.step)),
            onUp: s == null || s.pitchSens >= CursorSettings.max - eps
                ? null
                : () => _set(pitchSens: CursorSettings.snap(s.pitchSens + CursorSettings.step)),
          ),
          gap,
          // the level gate (calibration v2): sounds too quiet to be the user's are ignored
          Row(
            children: [
              Expanded(child: PixelSnap(child: Text('IGNORE QUIET', style: p.title(t.ink)))),
              PixelToggle<bool>(
                key: const Key('level_gate'),
                options: const [(true, 'On', Icons7.power), (false, 'Off', Icons7.pause)],
                selected: g?.enabled ?? true,
                onChanged: g == null ? null : (v) => _setGate(enabled: v),
              ),
            ],
          ),
          SizedBox(height: p(2)),
          _Stepper(
            name: 'Level gate strictness',
            label: 'Strictness',
            id: 'level_gate_offset',
            text: g == null ? null : LevelGateSettings.label(g.offsetDb),
            onDown: g == null || !g.enabled || g.offsetDb <= LevelGateSettings.minOffset
                ? null
                : () => _setGate(offsetDb: g.offsetDb - 1),
            onUp: g == null || !g.enabled || g.offsetDb >= LevelGateSettings.maxOffset
                ? null
                : () => _setGate(offsetDb: g.offsetDb + 1),
          ),
          SizedBox(height: p(2)),
          Text(
            g != null && !g.enabled
                ? 'Off: every sound reaches Canti, however quiet.'
                : 'Canti ignores sounds too quiet to be yours. + ignores more, - fewer.',
            key: const Key('level_gate_note'),
            style: p.body(t.ink, line: 11),
          ),
          gap,
          PixelSnap(child: Text('CALIBRATION', style: p.title(t.ink))),
          SizedBox(height: p(2)),
          CalibPanel(rows: [
            for (final src in calibSources)
              (
                src == 'pico' ? Icons7.device : Icons7.sound,
                switch (src) { 'phone' => 'Phone mic', 'usb' => 'USB mic', _ => 'Pico mic' },
                _unknown.contains(src)
                    ? 'unknown'
                    : !_profiles.containsKey(src)
                        ? '...'
                        : [
                            _profiles[src] == null
                                ? 'not calibrated'
                                : _profiles[src]!.needsRecalibration
                                    ? 'partly calibrated'
                                    : 'calibrated',
                            if (src == widget.source) 'in use',
                          ].join(', '),
                Key('calib_state_$src'),
              ),
          ]),
          if (current != null && current.needsRecalibration) ...[
            gap,
            SignalNote(
              signal: Signal.waiting,
              text: 'Recalibrate: ${current.missingSteps.length} new '
                  '${current.missingSteps.length == 1 ? 'step' : 'steps'} (${current.missingSteps.join(', ')}). '
                  'Your other steps stay as they are.',
              textKey: const Key('calib_nudge'),
            ),
            gap,
            Align(
              alignment: Alignment.centerLeft,
              child: FilledButton.icon(
                key: const Key('calib_record_missing'),
                icon: const PixelGlyph(Icons7.target),
                label: Text('Record the ${current.missingSteps.length} new'),
                onPressed: () => _calibrate(steps: current.missingSteps),
              ),
            ),
          ],
          if (current != null) ...[
            gap,
            PixelSnap(child: Text('${sourceLabel(widget.source)} · saved', style: p.body(t.ink))),
            SizedBox(height: p(2)),
            CalibPanel(rows: calibSummaryRows(current.toMap())),
            if (current.popsWeak) ...[
              gap,
              const SignalNote(signal: Signal.waiting, text: CalibrationScreen.popsHint),
            ],
          ] else if (known) ...[
            gap,
            SignalNote(
              signal: Signal.idle,
              text: 'The cursor is not calibrated for the ${sourceLabel(widget.source)} yet: it uses the defaults.',
              textKey: const Key('calib_none'),
            ),
          ],
          gap,
          Align(
            alignment: Alignment.centerLeft,
            child: current == null
                ? FilledButton.icon(
                    key: const Key('recalibrate'),
                    icon: const PixelGlyph(Icons7.target),
                    label: const Text('Calibrate'),
                    onPressed: _calibrate,
                  )
                : OutlinedButton.icon(
                    key: const Key('recalibrate'),
                    icon: const PixelGlyph(Icons7.refresh),
                    label: Text(current.needsRecalibration ? 'Recalibrate all' : 'Recalibrate'),
                    onPressed: _calibrate,
                  ),
          ),
        ],
      ),
    );
  }
}

/// A setting as NAME .... ◀ 90% ▶: the pager's arrows and box. A null [onDown] / [onUp] disables that arrow.
class _Stepper extends StatelessWidget {
  const _Stepper({required this.name, this.label, required this.id, required this.text, this.onDown, this.onUp});

  /// The full name (tooltips, screen readers).
  final String name;

  /// What the row shows, when shorter than [name] (fits one line at phone width).
  final String? label;
  final String id;

  /// The value as shown; null: not loaded yet.
  final String? text;
  final VoidCallback? onDown;
  final VoidCallback? onUp;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    return Row(
      children: [
        Expanded(child: PixelSnap(child: Text((label ?? name).toUpperCase(), style: p.title(t.ink)))),
        PixelIconButton(
          key: Key('${id}_down'),
          glyph: Marks.left,
          tooltip: 'Lower ${name.toLowerCase()}',
          framed: false,
          onPressed: onDown,
        ),
        PixelBox(
          padding: EdgeInsets.fromLTRB(p(4), p(3), p(3), p(3)),
          child: PixelSnap(
            child: Text(
              text ?? '---',
              key: Key('${id}_value'),
              semanticsLabel: '$name ${text ?? 'unknown'}',
              style: p.title(t.ink),
            ),
          ),
        ),
        PixelIconButton(
          key: Key('${id}_up'),
          glyph: Marks.right,
          tooltip: 'Raise ${name.toLowerCase()}',
          framed: false,
          onPressed: onUp,
        ),
      ],
    );
  }
}
