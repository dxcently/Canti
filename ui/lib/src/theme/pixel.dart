import 'dart:math' as math;
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';

import 'glyphs.dart';

/// The pixel scale: every frame, glyph and font is drawn on a grid of *art pixels*, each [k] device pixels square.
///
/// k = max(1, round(2 x devicePixelRatio)), so an art pixel is about 2 logical px everywhere (2 on a desktop or a 3x
/// phone, 1.905 on a 2.625x phone) and always a whole number of device pixels. Nothing is resampled: frames are
/// painted as rects on that grid ([PixelPaint] snaps its origin to the device grid), fonts are only used at 8 x the
/// scale (both faces are drawn on an 8-unit em), and glyphs are bitmaps ([Glyph]).
///
/// Text size: the platform's text scale is rounded to a whole multiple ([text], at least 1) so fonts stay on the
/// grid; the app turns Flutter's own scaling off under [PxScope] so it is not applied twice.
@immutable
class Px {
  Px(this.dpr, [TextScaler scaler = TextScaler.noScaling])
      : k = math.max(1, (2 * dpr).round()),
        text = math.max(1, (scaler.scale(8) / 8).round());

  final double dpr;
  final int k;
  final int text;

  /// One art pixel in logical px.
  double get px => k / dpr;

  /// [n] art pixels in logical px.
  double call(num n) => n * px;

  /// Titles, labels, buttons: Press Start 2P, 8 art px, one line per 8 px.
  TextStyle title(Color c) => TextStyle(
        fontFamily: Fonts.label,
        fontFamilyFallback: Fonts.labelFallback,
        fontSize: 8 * px * text,
        height: 1,
        color: c,
        letterSpacing: 0,
      );

  /// Body text with lowercase: Tiny5, 8 art px. [line] is the line height in art px (9 is the font's own; use an
  /// odd number so the extra space splits into whole pixels).
  TextStyle body(Color c, {int line = 9}) => TextStyle(
        fontFamily: Fonts.body,
        fontFamilyFallback: Fonts.bodyFallback,
        fontSize: 8 * px * text,
        height: line / 8,
        leadingDistribution: TextLeadingDistribution.even,
        color: c,
        letterSpacing: 0,
      );

  /// Headlines: Tiny5 at twice the size.
  TextStyle big(Color c) => TextStyle(
        fontFamily: Fonts.body,
        fontFamilyFallback: Fonts.bodyFallback,
        fontSize: 16 * px * text,
        height: 18 / 16,
        leadingDistribution: TextLeadingDistribution.even,
        color: c,
        letterSpacing: 0,
      );

  /// Font A's size in logical px: exactly 16 art px, twice the body (the 2x step).
  double get sentenceSize => 16 * px * text;

  /// Instruction and next-step sentences (font A): Departure Mono at exactly twice the body size, so a sentence on the
  /// calibration and training screens reads at arm's length. [line] is the line height in art px.
  TextStyle sentence(Color c, {int line = 19}) => TextStyle(
        fontFamily: Fonts.sentence,
        fontFamilyFallback: Fonts.sentenceFallback,
        fontSize: sentenceSize,
        height: line * px * text / sentenceSize,
        leadingDistribution: TextLeadingDistribution.even,
        color: c,
        letterSpacing: 0,
      );

  static Px of(BuildContext context) =>
      PxScope.maybeOf(context) ?? Px(MediaQuery.devicePixelRatioOf(context), MediaQuery.textScalerOf(context));

  @override
  bool operator ==(Object other) => other is Px && other.dpr == dpr && other.text == text;

  @override
  int get hashCode => Object.hash(dpr, text);
}

/// The two pixel faces. Use both names: the app's own fonts are 'Tiny5' (Android, where vox_ui is the module), a
/// dependency's are 'packages/vox_ui/Tiny5' (the desktop runner); the fallback covers the other.
abstract final class Fonts {
  static const label = 'PressStart2P';
  static const labelFallback = ['packages/vox_ui/PressStart2P'];
  static const body = 'Tiny5';
  static const bodyFallback = ['packages/vox_ui/Tiny5'];

  /// Font A (Departure Mono): the sentences and numbers on the calibration and training screens.
  static const sentence = 'DepartureMono';
  static const sentenceFallback = ['packages/vox_ui/DepartureMono'];
}

/// Provides one [Px] to the tree (set up once by the app, from the real text scale).
class PxScope extends InheritedWidget {
  const PxScope({super.key, required this.px, required super.child});

  final Px px;

  static Px? maybeOf(BuildContext context) => context.dependOnInheritedWidgetOfExactType<PxScope>()?.px;

  @override
  bool updateShouldNotify(PxScope old) => old.px != px;
}

/// Draws on the art-pixel grid: whole-pixel rects only, no anti-aliasing. Coordinates are art pixels from the
/// snapped origin; [w] x [h] is the art area that fits.
class PixelCanvas {
  PixelCanvas(this.canvas, this.origin, this.unit, this.w, this.h);

  final Canvas canvas;
  final Offset origin;
  final double unit;
  final int w;
  final int h;
  final _paint = Paint()..isAntiAlias = false;

  void rect(int x, int y, int rw, int rh, Color c) {
    if (rw <= 0 || rh <= 0) return;
    canvas.drawRect(Rect.fromLTWH(origin.dx + x * unit, origin.dy + y * unit, rw * unit, rh * unit), _paint..color = c);
  }

  void hline(int x, int y, int len, Color c) => rect(x, y, len, 1, c);
  void vline(int x, int y, int len, Color c) => rect(x, y, 1, len, c);

  /// A 1-pixel outline; [notch] leaves the four corner pixels out, the kit's clipped corners.
  void frame(int x, int y, int fw, int fh, Color c, {bool notch = false, bool dotted = false}) {
    if (fw <= 0 || fh <= 0) return;
    if (dotted) {
      final pts = <int>[];
      for (var i = x; i < x + fw; i += 2) {
        pts..add(i)..add(y)..add(i)..add(y + fh - 1);
      }
      for (var j = y + 2; j < y + fh - 1; j += 2) {
        pts..add(x)..add(j)..add(x + fw - 1)..add(j);
      }
      points(pts, c);
      return;
    }
    final n = notch ? 1 : 0;
    hline(x + n, y, fw - 2 * n, c);
    hline(x + n, y + fh - 1, fw - 2 * n, c);
    vline(x, y + 1, fh - 2, c);
    vline(x + fw - 1, y + 1, fh - 2, c);
  }

  /// A filled rect with notched corners.
  void block(int x, int y, int bw, int bh, Color c) {
    rect(x + 1, y, bw - 2, bh, c);
    rect(x, y + 1, 1, bh - 2, c);
    rect(x + bw - 1, y + 1, 1, bh - 2, c);
  }

  /// Single pixels, as (x, y) pairs: one draw call.
  void points(List<int> xy, Color c) {
    if (xy.isEmpty) return;
    final f = Float32List(xy.length);
    for (var i = 0; i < xy.length; i += 2) {
      f[i] = origin.dx + (xy[i] + 0.5) * unit;
      f[i + 1] = origin.dy + (xy[i + 1] + 0.5) * unit;
    }
    canvas.drawRawPoints(
      ui.PointMode.points,
      f,
      Paint()
        ..isAntiAlias = false
        ..color = c
        ..strokeWidth = unit
        ..strokeCap = StrokeCap.square,
    );
  }

  /// A bitmap glyph, [scale] art pixels per glyph pixel; each run of lit pixels is one rect.
  void glyph(Glyph g, int x, int y, Color c, {int scale = 1}) {
    for (var r = 0; r < g.rows.length; r++) {
      final row = g.rows[r];
      var i = 0;
      while (i < row.length) {
        if (row.codeUnitAt(i) != 0x23) {
          i++;
          continue;
        }
        final s = i;
        while (i < row.length && row.codeUnitAt(i) == 0x23) {
          i++;
        }
        rect(x + s * scale, y + r * scale, (i - s) * scale, scale, c);
      }
    }
  }

  /// The kit's diagonal hatch: one pixel in every [step] along each diagonal.
  void hatch(int x, int y, int hw, int hh, Color c, {int step = 4}) {
    final pts = <int>[];
    for (var j = y; j < y + hh; j++) {
      for (var i = x + ((step - (j % step)) % step); i < x + hw; i += step) {
        pts..add(i)..add(j);
      }
    }
    points(pts, c);
  }

  /// The selection cursor: four corner brackets, [arm] long and [t] thick, just inside the box.
  void brackets(int x, int y, int bw, int bh, Color c, {int arm = 4, int t = 2}) {
    for (final (cx, cy, sx, sy) in [(x, y, 1, 1), (x + bw, y, -1, 1), (x, y + bh, 1, -1), (x + bw, y + bh, -1, -1)]) {
      final x0 = sx > 0 ? cx : cx - arm;
      final y0 = sy > 0 ? cy : cy - t;
      rect(x0, y0, arm, t, c);
      rect(sx > 0 ? cx : cx - t, sy > 0 ? cy : cy - arm, t, arm, c);
    }
  }
}

/// Pixel art for a [PixelPaint].
abstract class PixelArt {
  const PixelArt();

  void paint(PixelCanvas c);

  bool shouldRepaint(covariant PixelArt old);
}

/// The device-pixel offset that puts [box]'s origin on the device grid (at most half a device pixel).
Offset pixelSnap(RenderBox box, double dpr) {
  final g = box.localToGlobal(Offset.zero);
  return Offset(((g.dx * dpr).roundToDouble() - g.dx * dpr) / dpr, ((g.dy * dpr).roundToDouble() - g.dy * dpr) / dpr);
}

/// Paints [art] behind [child] (and [foreground] over it), both snapped to the device grid, the child with them.
/// Without a child it fills the incoming constraints.
class PixelPaint extends SingleChildRenderObjectWidget {
  const PixelPaint({super.key, this.art, this.foreground, this.repaint, super.child});

  final PixelArt? art;
  final PixelArt? foreground;
  final Listenable? repaint;

  @override
  RenderPixelPaint createRenderObject(BuildContext context) =>
      RenderPixelPaint(Px.of(context), art, foreground, repaint);

  @override
  void updateRenderObject(BuildContext context, RenderPixelPaint renderObject) {
    renderObject
      ..px = Px.of(context)
      ..art = art
      ..foreground = foreground
      ..repaint = repaint;
  }
}

class RenderPixelPaint extends RenderProxyBox {
  RenderPixelPaint(this._px, this._art, this._foreground, this._repaint);

  Px _px;
  set px(Px v) {
    if (v == _px) return;
    _px = v;
    markNeedsPaint();
  }

  PixelArt? _art;
  set art(PixelArt? v) {
    final old = _art;
    _art = v;
    if (v == null || old == null || v.runtimeType != old.runtimeType || v.shouldRepaint(old)) markNeedsPaint();
  }

  PixelArt? _foreground;
  set foreground(PixelArt? v) {
    final old = _foreground;
    _foreground = v;
    if (v == null || old == null || v.runtimeType != old.runtimeType || v.shouldRepaint(old)) markNeedsPaint();
  }

  Listenable? _repaint;
  set repaint(Listenable? v) {
    if (v == _repaint) return;
    if (attached) _repaint?.removeListener(markNeedsPaint);
    _repaint = v;
    if (attached) _repaint?.addListener(markNeedsPaint);
    markNeedsPaint();
  }

  @override
  void attach(PipelineOwner owner) {
    super.attach(owner);
    _repaint?.addListener(markNeedsPaint);
  }

  @override
  void detach() {
    _repaint?.removeListener(markNeedsPaint);
    super.detach();
  }

  @override
  Size computeSizeForNoChild(BoxConstraints constraints) =>
      constraints.hasBoundedWidth && constraints.hasBoundedHeight ? constraints.biggest : constraints.smallest;

  @override
  void paint(PaintingContext context, Offset offset) {
    final snap = pixelSnap(this, _px.dpr);
    final o = offset + snap;
    final u = _px.px;
    final w = ((size.width - math.max(0.0, snap.dx)) / u + 1e-6).floor();
    final h = ((size.height - math.max(0.0, snap.dy)) / u + 1e-6).floor();
    _art?.paint(PixelCanvas(context.canvas, o, u, w, h));
    if (child != null) context.paintChild(child!, o);
    _foreground?.paint(PixelCanvas(context.canvas, o, u, w, h));
  }
}

/// A bitmap glyph at [scale] art pixels per pixel, in [color] or the ambient icon colour.
class PixelGlyph extends StatelessWidget {
  const PixelGlyph(this.glyph, {super.key, this.color, this.scale = 1});

  final Glyph glyph;
  final Color? color;
  final int scale;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final c = color ?? IconTheme.of(context).color ?? DefaultTextStyle.of(context).style.color ?? const Color(0xFF000000);
    return SizedBox(
      width: p(glyph.width * scale),
      height: p(glyph.height * scale),
      child: PixelPaint(art: _GlyphArt(glyph, c, scale)),
    );
  }
}

class _GlyphArt extends PixelArt {
  const _GlyphArt(this.g, this.c, this.scale);

  final Glyph g;
  final Color c;
  final int scale;

  @override
  void paint(PixelCanvas c0) => c0.glyph(g, 0, 0, c, scale: scale);

  @override
  bool shouldRepaint(_GlyphArt old) => old.g != g || old.c != c || old.scale != scale;
}

/// Snaps [child]'s origin to the device grid (for text in the pixel faces, so it lands on whole pixels).
class PixelSnap extends StatelessWidget {
  const PixelSnap({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) => PixelPaint(child: child);
}
