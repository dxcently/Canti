import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'theme/canti_theme.dart';
import 'theme/glyphs.dart';
import 'theme/kit.dart';
import 'theme/pixel.dart';

// The heard-vs-expected shape widget (SHARED CONTRACT §9): an aim band with the expected contour (dithered band,
// dashed example line) and what the user actually did (the live pitch trace and/or each heard sound's pitch16 as a
// solid line), or, for discrete/combos, a beat strip. One row of check chips and a legend under it. E8 draws it for
// the recorder's saved/no-sound take; E9 reuses it for calibration/training, consuming it unchanged.

/// How a single check turned out.
enum CheckState { ok, near, miss, pending }

/// One check chip: `PITCH ✓`, `SHAPE ~`, `LENGTH ✗` (miss is inverted), `TONE ·` (pending).
@immutable
class ShapeCheck {
  const ShapeCheck(this.id, this.label, this.state, {this.value, this.want});

  /// `pitch` | `shape` | `length` | `tone` | `count` | `gap` | `loud`.
  final String id;
  final String label;
  final CheckState state;

  /// What the user did / what was wanted (shown in the accessibility label, not the chip's text).
  final String? value;
  final String? want;

  static ShapeCheck fromMap(Object? o) {
    final m = o is Map ? o.cast<Object?, Object?>() : const <Object?, Object?>{};
    return ShapeCheck(
      (m['id'] as String?) ?? '?',
      (m['label'] as String?) ?? (m['id'] as String?) ?? '?',
      switch (m['state'] as String?) {
        'ok' => CheckState.ok,
        'near' => CheckState.near,
        'miss' => CheckState.miss,
        _ => CheckState.pending,
      },
      value: _text(m['value']),
      want: _text(m['want']),
    );
  }

  /// The service sends numbers for some values (PITCH: st from HOME, SHAPE: st, LENGTH: ms, SOUND: Hz): kept as text
  /// (a cast would throw on them).
  static String? _text(Object? v) => switch (v) {
        String s => s,
        int n => '$n',
        double d => d == d.roundToDouble() ? '${d.round()}' : d.toStringAsFixed(2),
        _ => null,
      };
}

/// The source's saved pitch scale (rec_status.scale): low/home/high in Hz, from the calibration profile.
@immutable
class PitchScale {
  const PitchScale({this.lowHz, this.homeHz, this.highHz});

  final double? lowHz;
  final double? homeHz;
  final double? highHz;

  /// All three set, low < home < high: the plot's y axis is absolute Hz.
  bool get absolute =>
      lowHz != null && homeHz != null && highHz != null && lowHz! < homeHz! && homeHz! < highHz!;

  static PitchScale? fromMap(Object? o) {
    if (o is! Map) return null;
    final m = o.cast<Object?, Object?>();
    final low = _d(m['low_hz']), home = _d(m['home_hz']), high = _d(m['high_hz']);
    return (low == null && home == null && high == null) ? null : PitchScale(lowHz: low, homeHz: home, highHz: high);
  }
}

/// One sound the extractor heard (rec_status.heard[] / snapshot.sounds[]).
@immutable
class HeardSound {
  const HeardSound({
    this.label,
    this.relMs,
    this.durMs,
    this.pitch16 = const [],
    this.f0Hz,
    this.dropped,
    this.gated,
    this.relabel,
    this.didText,
    this.agoS,
  });

  final String? label;

  /// Start relative to GO (or to the clip start in a snapshot), in ms.
  final double? relMs;
  final int? durMs;

  /// 16 points in semitones from the start ([] when unpitched).
  final List<double> pitch16;
  final int? f0Hz;

  /// Why the sound was dropped (or null), whether it failed the media gate, and the relabel.
  final String? dropped;
  final bool? gated;
  final String? relabel;

  /// What Canti did with it ("HISS → back", "ignored: below level gate", "no action").
  final String? didText;

  /// Snapshot only: how long ago, in seconds.
  final double? agoS;

  /// The start pitch in Hz: f0Hz / 2^(median(pitch16)/12) (TrainJudge.startHz) — null when unpitched.
  double? get startHz {
    final f0 = f0Hz;
    if (f0 == null || pitch16.isEmpty) return null;
    final sorted = [...pitch16]..sort();
    final med = sorted.length.isOdd
        ? sorted[sorted.length ~/ 2]
        : (sorted[sorted.length ~/ 2 - 1] + sorted[sorted.length ~/ 2]) / 2;
    return f0 / math.pow(2, med / 12);
  }

  /// The same sound, starting at [relMs] instead (the plot's alignment).
  HeardSound at(double relMs) => HeardSound(
        label: label,
        relMs: relMs,
        durMs: durMs,
        pitch16: pitch16,
        f0Hz: f0Hz,
        dropped: dropped,
        gated: gated,
        relabel: relabel,
        didText: didText,
        agoS: agoS,
      );

  static HeardSound fromMap(Object? o) {
    final m = o is Map ? o.cast<Object?, Object?>() : const <Object?, Object?>{};
    return HeardSound(
      label: _s(m['label']),
      relMs: _d(m['rel_ms']),
      durMs: _i(m['dur_ms']),
      pitch16: [for (final x in _l(m['pitch16'])) if (x is num) x.toDouble()],
      f0Hz: _i(m['f0_hz']),
      dropped: _s(m['dropped']),
      gated: m['gated'] is bool ? m['gated'] as bool : null,
      relabel: _s(m['relabel']),
      didText: _s(m['did_text']),
      agoS: _d(m['ago_s']),
    );
  }
}

/// The canonical expected shape. For the recorder it comes from the spec cell's `expect` + `cond` + `defaults`; for
/// E9's training/calibration from the cell's `expect` map.
@immutable
class ExpectedShape {
  const ExpectedShape({
    required this.sequence,
    this.start = 'home',
    this.spanSt = 4,
    this.tolSt = 1.5,
    this.durS = 0.6,
    this.gapS,
  });

  /// `['rise']` / `['click', 'click']` / `['flat']`.
  final List<String> sequence;

  /// `low` | `home` | `high` | `bottom` | `top` | `none` — where the contour starts.
  final String start;
  final double spanSt;
  final double tolSt;

  /// The aim's length in seconds (contours).
  final double durS;

  /// The gap between the two sounds (combos), in seconds.
  final double? gapS;

  /// A single rise|fall|arch|dip|flat.
  bool get contour => sequence.length == 1 && const ['rise', 'fall', 'arch', 'dip', 'flat'].contains(sequence.first);

  /// The centre path in semitones relative to the start note at t = 0..1 (17 points): rise 0→+span, fall 0→-span,
  /// arch 0→+span→0 (half-sine), dip 0→-span→0, flat 0.
  List<double> example() => [for (var i = 0; i < 17; i++) _centerAt(i / 16)];

  double _centerAt(double t) => switch (sequence.isEmpty ? 'flat' : sequence.first) {
        'rise' => spanSt * t,
        'fall' => -spanSt * t,
        'arch' => spanSt * math.sin(math.pi * t),
        'dip' => -spanSt * math.sin(math.pi * t),
        _ => 0,
      };

  /// The aim band at t (0..1): (centre - tol, centre + tol), in semitones from the start note.
  (double, double) bandAt(double t) {
    final c = _centerAt(t);
    return (c - tolSt, c + tolSt);
  }

  /// For the recorder: `expect` + `cond` from the spec cell, `defaults` from rec_status.defaults.
  /// pitch bottom|home|top → start low|home|high; durS and gapS from speed_s / gap_s. [targetS] (optional, the cell's
  /// target_s, e.g. the range block's 2 s holds) overrides the speed's length.
  static ExpectedShape forTake({
    required List<String> expect,
    required Map<String, String> cond,
    required Map<String, Object?> defaults,
    double? targetS,
  }) {
    final start = switch (cond['pitch']) {
      'bottom' => 'low',
      'top' => 'high',
      'home' => 'home',
      _ => 'none',
    };
    final speedS = _numMap(defaults['speed_s']);
    final gapS = _numMap(defaults['gap_s']);
    final speed = cond['speed'];
    final gap = cond['gap'];
    final dur = targetS ?? ((speed != null && speedS[speed] != null) ? speedS[speed]! : 0.6);
    final gapV = (gap != null && gapS[gap] != null) ? gapS[gap]! : 0.35;
    return ExpectedShape(sequence: expect, start: start, durS: dur, gapS: gapV);
  }

  /// E9's `expect` map: {sequence, start, span_st, tol_st, dur_s, gap_s}.
  static ExpectedShape fromMap(Object? o) {
    final m = o is Map ? o.cast<Object?, Object?>() : const <Object?, Object?>{};
    return ExpectedShape(
      sequence: [for (final x in _l(m['sequence'])) if (x is String) x],
      start: _s(m['start']) ?? 'home',
      spanSt: _d(m['span_st']) ?? 4,
      tolSt: _d(m['tol_st']) ?? 1.5,
      durS: _d(m['dur_s']) ?? 0.6,
      gapS: _d(m['gap_s']),
    );
  }
}

// --- pure helpers ----------------------------------------------------------------------------------------------------

/// pitch16 (semitones from a start note) as Hz, anchored at [startHz].
List<double> pitch16ToHz(List<double> pitch16, double startHz) =>
    [for (final st in pitch16) startHz * math.pow(2, st / 12)];

/// Semitones from [refHz] to [hz].
double hzToSt(double hz, double refHz) => 12 * math.log(hz / refHz) / math.ln2;

// --- the widget ------------------------------------------------------------------------------------------------------

/// The heard-vs-expected plot. Contour mode (a single rise/fall/arch/dip/flat) draws the aim band and example against
/// an absolute Hz scale (with [scale]) or a relative semitone scale; discrete/combos draw a beat strip. Drawn 1-bit
/// with [PixelArt]; renders at 360 dp wide (and in half-width mini plots) without overflow.
class ShapePlot extends StatelessWidget {
  const ShapePlot({
    super.key,
    required this.expected,
    this.scale,
    this.liveHz = const [],
    this.liveTickS = 0.02,
    this.heard = const [],
    this.checks = const [],
    this.height = 64,
    this.showLegend = true,
    this.caption,
    this.alignToHeard = false,
    this.grow = false,
  });

  final ExpectedShape expected;
  final PitchScale? scale;

  /// The live pitch in Hz, one point per [liveTickS], null = unvoiced (E9's training).
  final List<double?> liveHz;
  final double liveTickS;

  /// The heard sounds (post-sound pitch16 only for the recorder). [HeardSound.relMs] is in ms from the plot's t = 0.
  final List<HeardSound> heard;

  final List<ShapeCheck> checks;

  /// The plot's height in art px (its fixed height when not [grow]; the preferred height when [grow], which fills
  /// whatever the parent gives and so shrinks rather than overflows on a short screen).
  final int height;
  final bool showLegend;
  final String? caption;

  /// (Added to §9, optional.) Shift [heard] so the first sound starts at t = 0, where the aim starts: the recorder's
  /// sounds are timed from GO (the user starts a beat later), a snapshot's from the clip start.
  final bool alignToHeard;

  /// Fill the available height (the parent gives a bounded height, e.g. an `Expanded`) instead of a fixed [height]
  /// plot: the calibration / training / review screens grow the graph into the otherwise-empty lower half.
  final bool grow;

  /// [heard] as drawn: shifted to start at 0 when [alignToHeard].
  List<HeardSound> get _heard {
    if (!alignToHeard || heard.isEmpty) return heard;
    final first = heard.map((h) => h.relMs ?? 0).reduce(math.min);
    return [for (final h in heard) h.at((h.relMs ?? 0) - first)];
  }

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    final ink = t.ink;
    final heard = _heard;
    final plot = expected.contour
        ? _ContourPlot(
            key: const Key('shape_plot_contour'),
            expected: expected,
            scale: scale,
            liveHz: liveHz,
            liveTickS: liveTickS,
            heard: heard,
            height: height,
            fill: grow,
          )
        : _BeatStrip(
            key: const Key('shape_plot_beat'),
            expected: expected,
            heard: heard,
            height: height,
            fill: grow,
          );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: grow ? MainAxisSize.max : MainAxisSize.min,
      children: [
        if (grow)
          // Fill the space the parent gives (a tight Expanded); no hard minimum, so a short screen (rotation, a
          // resized window) shrinks the plot instead of overflowing.
          Expanded(child: plot)
        else
          plot,
        if (caption != null) ...[
          SizedBox(height: p(2)),
          PixelSnap(child: Text(caption!, style: p.body(ink, line: 11))),
        ],
        if (checks.isNotEmpty) ...[
          SizedBox(height: p(2)),
          Wrap(
            spacing: p(2),
            runSpacing: p(2),
            children: [
              for (final c in checks) _Chip(check: c),
            ],
          ),
        ],
        if (showLegend) ...[
          SizedBox(height: p(2)),
          PixelSnap(
            child: Text(expected.contour ? 'aim · example — you' : 'example □ · you ■', style: p.body(ink, line: 11)),
          ),
        ],
      ],
    );
  }
}

/// ✓ as a bitmap (neither pixel face has ✓ or ✗; ✗ is [Marks.cross]).
const tickGlyph = Glyph([
  '......#',
  '.....##',
  '#...##.',
  '##.##..',
  '.###...',
  '..#....',
]);

/// One check chip: `PITCH ✓` (✓ ok, ~ near, ✗ miss inverted, · pending).
class _Chip extends StatelessWidget {
  const _Chip({required this.check});

  final ShapeCheck check;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    final miss = check.state == CheckState.miss;
    final fg = miss ? t.paper : t.ink;
    final mark = switch (check.state) {
      CheckState.ok => PixelGlyph(tickGlyph, color: fg),
      CheckState.miss => PixelGlyph(Marks.cross, color: fg),
      CheckState.near => PixelSnap(child: Text('~', style: p.title(fg))),
      CheckState.pending => PixelSnap(child: Text('·', style: p.title(fg))),
    };
    final said = [
      check.label,
      check.state.name,
      if (check.value != null) 'got ${check.value}',
      if (check.want != null) 'want ${check.want}',
    ].join(', ');
    return Semantics(
      label: said,
      excludeSemantics: true,
      child: PixelBox(
        key: Key('check_${check.id}_${check.state.name}'),
        inverted: miss,
        padding: EdgeInsets.symmetric(horizontal: p(3), vertical: p(2)),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            PixelSnap(child: Text(check.label.toUpperCase(), style: p.title(fg))),
            SizedBox(width: p(3)),
            mark,
          ],
        ),
      ),
    );
  }
}

// --- contour plot ----------------------------------------------------------------------------------------------------

class _ContourPlot extends StatelessWidget {
  const _ContourPlot({
    super.key,
    required this.expected,
    required this.scale,
    required this.liveHz,
    required this.liveTickS,
    required this.heard,
    required this.height,
    required this.fill,
  });

  final ExpectedShape expected;
  final PitchScale? scale;
  final List<double?> liveHz;
  final double liveTickS;
  final List<HeardSound> heard;
  final int height;
  final bool fill;

  /// The y axis spans [stMin, stMax] semitones (relative to LOW in absolute mode, to the start note otherwise); x
  /// spans 0..xMax seconds.
  static ({double stMin, double stMax, double xMax}) geom(
      ExpectedShape expected, PitchScale? scale, List<double?> liveHz, double liveTickS, List<HeardSound> heard) {
    final xMax = math.max(
      expected.durS * 1.6,
      math.max(
        liveHz.length * liveTickS,
        heard.fold(0.0, (a, h) => math.max(a, ((h.relMs ?? 0) + (h.durMs ?? 0)) / 1000)),
      ),
    );
    if (scale != null && scale.absolute) {
      return (stMin: -3.0, stMax: hzToSt(scale.highHz!, scale.lowHz!) + 3.0, xMax: xMax);
    }
    var lo = math.min(0.0, -(expected.spanSt + expected.tolSt));
    var hi = math.max(0.0, expected.spanSt + expected.tolSt);
    for (final h in heard) {
      for (final st in h.pitch16) {
        lo = math.min(lo, st);
        hi = math.max(hi, st);
      }
    }
    final voiced = liveHz.whereType<double>().toList();
    if (voiced.isNotEmpty) {
      final ref = voiced.first;
      for (final hz in voiced) {
        final st = hzToSt(hz, ref);
        lo = math.min(lo, st);
        hi = math.max(hi, st);
      }
    }
    final mid = (lo + hi) / 2;
    if (hi - lo < 12) {
      lo = mid - 6;
      hi = mid + 6;
    }
    return (stMin: lo, stMax: hi, xMax: xMax);
  }

  /// The start mark's semitone (relative to LOW in absolute mode; 0 otherwise).
  double _startSt() {
    final s = scale;
    if (s == null || !s.absolute) return 0;
    return switch (expected.start) {
      'low' || 'bottom' => 0,
      'high' || 'top' => hzToSt(s.highHz!, s.lowHz!),
      _ => hzToSt(s.homeHz!, s.lowHz!),
    };
  }

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    final g = geom(expected, scale, liveHz, liveTickS, heard);
    final abs = scale != null && scale!.absolute;
    final gutter = abs ? 22 : 0;
    final plotH = p(height);
    final art = _ContourArt(
      expected: expected,
      scale: scale,
      liveHz: liveHz,
      liveTickS: liveTickS,
      heard: heard,
      stMin: g.stMin,
      stMax: g.stMax,
      xMax: g.xMax,
      startSt: _startSt(),
      gutter: gutter,
      ink: t.ink,
    );
    Widget stackAt(double h) => Stack(
          children: [
            Positioned.fill(child: PixelPaint(art: art)),
            if (abs)
              for (final (tag, hz) in [('HIGH', scale!.highHz!), ('HOME', scale!.homeHz!), ('LOW', scale!.lowHz!)])
                Positioned(
                  left: p(3),
                  width: p(gutter - 2),
                  top: _tagTop(p, h, g, hzToSt(hz, scale!.lowHz!)),
                  child: PixelSnap(
                    child: Text(tag, style: p.body(t.ink, line: 9), maxLines: 1, overflow: TextOverflow.clip),
                  ),
                ),
          ],
        );
    if (!fill) return SizedBox(height: plotH, width: double.infinity, child: stackAt(plotH));
    return LayoutBuilder(builder: (context, bc) => SizedBox.expand(child: stackAt(bc.maxHeight)));
  }

  /// The tag's top so its middle sits on the dotted line (mirrors [_ContourArt._y]).
  double _tagTop(Px p, double plotH, ({double stMin, double stMax, double xMax}) g, double st) {
    final innerH = (plotH / p.px).floor() - 6;
    final y = 3 + ((g.stMax - st) / (g.stMax - g.stMin) * innerH).round();
    return p(y - 4);
  }
}

class _ContourArt extends PixelArt {
  const _ContourArt({
    required this.expected,
    required this.scale,
    required this.liveHz,
    required this.liveTickS,
    required this.heard,
    required this.stMin,
    required this.stMax,
    required this.xMax,
    required this.startSt,
    required this.gutter,
    required this.ink,
  });

  final ExpectedShape expected;
  final PitchScale? scale;
  final List<double?> liveHz;
  final double liveTickS;
  final List<HeardSound> heard;
  final double stMin, stMax, xMax, startSt;
  final int gutter;
  final Color ink;

  bool get _abs => scale != null && scale!.absolute;

  int _x(double secs, int w) => 3 + gutter + (secs / xMax * (w - 6 - gutter)).round();
  int _y(double st, int h) => 3 + ((stMax - st) / (stMax - stMin) * (h - 6)).round();

  @override
  void paint(PixelCanvas c) {
    c.frame(0, 0, c.w, c.h, ink, notch: true);
    final w = c.w, h = c.h;
    if (w - 6 - gutter <= 0 || h - 6 <= 0) return;

    // x ticks every 0.5 s
    for (var s = 0.0; s <= xMax + 1e-9; s += 0.5) {
      c.rect(_x(s, w), h - 4, 1, 2, ink);
    }

    // dotted guide lines (LOW/HOME/HIGH, or the start note)
    final guides = _abs
        ? [for (final hz in [scale!.highHz!, scale!.homeHz!, scale!.lowHz!]) hzToSt(hz, scale!.lowHz!)]
        : [0.0];
    for (final st in guides) {
      final y = _y(st, h);
      for (var x = 3 + gutter; x < w - 2; x += 3) {
        c.rect(x, y, 1, 1, ink);
      }
    }

    // the aim band: dithered, over [0, durS], centre = startSt + example(t), ± tolSt
    final dur = expected.durS;
    const n = 16;
    for (var i = 0; i < n; i++) {
      final (lo0, hi0) = expected.bandAt(i / n);
      final (lo1, hi1) = expected.bandAt((i + 1) / n);
      final x0 = _x(dur * i / n, w), x1 = _x(dur * (i + 1) / n, w);
      final yTop = math.min(_y(startSt + hi0, h), _y(startSt + hi1, h));
      final yBot = math.max(_y(startSt + lo0, h), _y(startSt + lo1, h));
      if (yBot - yTop < 1 || x1 <= x0) continue;
      c.hatch(x0, yTop, x1 - x0, yBot - yTop, ink, step: 3);
    }

    // the example: a dashed line along the centre (two pixels on, two off)
    final ex = expected.example();
    for (var i = 0; i < ex.length - 1; i++) {
      final x0 = _x(dur * i / (ex.length - 1), w), x1 = _x(dur * (i + 1) / (ex.length - 1), w);
      for (var x = x0; x < x1; x++) {
        if (x % 4 >= 2) continue;
        final f = x1 == x0 ? 0.0 : (x - x0) / (x1 - x0);
        c.rect(x, _y(startSt + ex[i] + (ex[i + 1] - ex[i]) * f, h), 1, 1, ink);
      }
    }

    _drawLive(c, w, h);
    _drawHeard(c, w, h);
  }

  // live trace (Hz; null = gap): absolute = st vs LOW; relative = st vs the first voiced point
  void _drawLive(PixelCanvas c, int w, int h) {
    if (liveHz.isEmpty) return;
    final voiced = liveHz.whereType<double>().toList();
    if (voiced.isEmpty) return;
    final ref = _abs ? scale!.lowHz! : voiced.first;
    int? px, py;
    for (var i = 0; i < liveHz.length; i++) {
      final hz = liveHz[i];
      if (hz == null || hz <= 0) {
        px = py = null;
        continue;
      }
      final x = _x(i * liveTickS, w);
      final y = _y(hzToSt(hz, ref), h);
      _seg(c, px, py, x, y);
      px = x;
      py = y;
    }
  }

  // each heard sound: pitch16 stretched over its durMs from its relMs, anchored at startHz (absolute) or at the start
  // note (relative, or no f0); an unpitched sound is a bar on the bottom edge over its length
  void _drawHeard(PixelCanvas c, int w, int h) {
    for (final s in heard) {
      final start = (s.relMs ?? 0) / 1000;
      final dur = (s.durMs ?? 0) / 1000;
      if (s.pitch16.isEmpty) {
        final x0 = _x(start, w), x1 = math.max(x0 + 2, _x(start + dur, w));
        c.rect(x0, h - 7, x1 - x0, 2, ink);
        continue;
      }
      final sh = s.startHz;
      final n = s.pitch16.length;
      int? px, py;
      for (var i = 0; i < n; i++) {
        final x = _x(start + (n <= 1 ? 0 : dur * i / (n - 1)), w);
        final st = _abs && sh != null
            ? hzToSt(sh * math.pow(2, s.pitch16[i] / 12), scale!.lowHz!)
            : startSt + s.pitch16[i];
        final y = _y(st, h);
        _seg(c, px, py, x, y);
        px = x;
        py = y;
      }
      // an end box on the last point
      if (px != null && py != null) c.frame(px - 1, py - 2, 4, 5, ink);
    }
  }

  // a 2 px thick segment from (px, py) to (x, y)
  void _seg(PixelCanvas c, int? px, int? py, int x, int y) {
    if (px == null || py == null) {
      c.rect(x, y, 2, 2, ink);
      return;
    }
    final steps = math.max((x - px).abs(), (y - py).abs());
    for (var k = 0; k <= steps; k++) {
      final f = steps == 0 ? 0.0 : k / steps;
      c.rect(px + ((x - px) * f).round(), py + ((y - py) * f).round(), 2, 2, ink);
    }
  }

  @override
  bool shouldRepaint(_ContourArt old) =>
      old.expected != expected ||
      old.scale != scale ||
      old.liveHz != liveHz ||
      old.liveTickS != liveTickS ||
      old.heard != heard ||
      old.stMin != stMin ||
      old.stMax != stMax ||
      old.xMax != xMax ||
      old.startSt != startSt ||
      old.gutter != gutter ||
      old.ink != ink;
}

// --- the beat strip (discrete / combos) ------------------------------------------------------------------------------

/// Two lanes on one time axis: EXAMPLE (an outlined box per expected sound, [ExpectedShape.gapS] apart) and YOU (a
/// filled box per heard sound at its relMs, with its label), with the "too late" hatch after gap + 0.6 s.
class _BeatStrip extends StatelessWidget {
  const _BeatStrip({super.key, required this.expected, required this.heard, required this.height, required this.fill});

  final ExpectedShape expected;
  final List<HeardSound> heard;
  final int height;
  final bool fill;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    final gap = expected.gapS ?? 0.35;
    final count = math.max(1, expected.sequence.length);
    final late = gap * (count - 1) + 0.6;
    final xMax = math.max(late + 0.4, heard.fold(0.0, (a, h) => math.max(a, (h.relMs ?? 0) / 1000 + 0.3)));
    const labelW = 40, box = 9, lane = 13; // labelW: "EXAMPLE" in the body face, and a gap
    return SizedBox(
      height: fill ? null : p(math.max(height, 2 * lane + 10)),
      width: double.infinity,
      child: LayoutBuilder(
        builder: (context, bc) {
          final wArt = (bc.maxWidth / p.px).floor();
          final plotW = math.max(1, wArt - labelW - 4 - box);
          double x(double secs) => p(labelW + (secs / xMax * plotW).round());
          final lateX = x(late);
          Widget laneAt(int top, String name, List<Widget> marks) => Positioned(
                left: 0,
                right: 0,
                top: p(top),
                height: p(lane),
                child: Stack(
                  clipBehavior: Clip.hardEdge,
                  children: [
                    Positioned(
                      left: p(4),
                      top: p(2),
                      child: PixelSnap(child: Text(name, style: p.body(t.ink, line: 9))),
                    ),
                    ...marks,
                  ],
                ),
              );
          return Stack(
            children: [
              Positioned.fill(child: PixelPaint(art: _FrameArt(t.ink))),
              // too late: hatched after the last wanted sound + 0.6 s
              if (lateX < bc.maxWidth - p(3))
                Positioned(
                  left: lateX,
                  top: p(1),
                  bottom: p(1),
                  right: p(1),
                  child: PixelPaint(art: _HatchArt(t.ink)),
                ),
              laneAt(4, 'EXAMPLE', [
                for (var k = 0; k < count; k++)
                  Positioned(
                    left: x(gap * k),
                    top: p(2),
                    width: p(box),
                    height: p(box),
                    child: PixelPaint(art: _BoxArt(t.ink, filled: false)),
                  ),
              ]),
              laneAt(4 + lane + 2, 'YOU', [
                for (final (i, s) in heard.indexed)
                  Positioned(
                    key: Key('beat_you_$i'),
                    left: x((s.relMs ?? 0) / 1000),
                    top: p(2),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        SizedBox(width: p(box), height: p(box), child: PixelPaint(art: _BoxArt(t.ink, filled: true))),
                        SizedBox(width: p(2)),
                        PixelSnap(child: Text(s.label ?? '?', style: p.body(t.ink, line: 9))),
                      ],
                    ),
                  ),
              ]),
            ],
          );
        },
      ),
    );
  }
}

class _FrameArt extends PixelArt {
  const _FrameArt(this.ink);
  final Color ink;
  @override
  void paint(PixelCanvas c) => c.frame(0, 0, c.w, c.h, ink, notch: true);
  @override
  bool shouldRepaint(_FrameArt old) => old.ink != ink;
}

class _HatchArt extends PixelArt {
  const _HatchArt(this.ink);
  final Color ink;
  @override
  void paint(PixelCanvas c) => c.hatch(0, 0, c.w, c.h, ink, step: 4);
  @override
  bool shouldRepaint(_HatchArt old) => old.ink != ink;
}

class _BoxArt extends PixelArt {
  const _BoxArt(this.ink, {required this.filled});
  final Color ink;
  final bool filled;
  @override
  void paint(PixelCanvas c) => filled ? c.block(0, 0, c.w, c.h, ink) : c.frame(0, 0, c.w, c.h, ink, notch: true);
  @override
  bool shouldRepaint(_BoxArt old) => old.ink != ink || old.filled != filled;
}

// --- shared parsing helpers -------------------------------------------------------------------------------------------

double? _d(Object? v) => v is num ? v.toDouble() : null;
int? _i(Object? v) => v is num ? v.round() : null;
String? _s(Object? v) => v is String ? v : null;
List<Object?> _l(Object? v) => v is List ? v : const [];
Map<String, double> _numMap(Object? v) => {
      if (v is Map)
        for (final e in v.cast<Object?, Object?>().entries)
          if (e.value is num) '${e.key}': (e.value as num).toDouble(),
    };
