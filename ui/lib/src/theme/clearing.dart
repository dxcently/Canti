import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';

import 'assets.dart';
import 'canti_theme.dart';
import 'pixel.dart';

/// Clearings in the dot field ([DitherBackground]): around text and art that sits straight on the field, the dots
/// thin out to clear paper, in the field's own terms. Whole cells of the field's grid, ordered by the same 4x4 Bayer
/// matrix, so the edge is a dither ramp, not a plate:
///
///   * within [clear] art px of the ink (its pixels, dilated), no dots;
///   * over the next [ramp] art px the allowed density rises from 0 to the field's densest tone (50%); a cell with
///     Bayer threshold t keeps its dot only while t < the allowed density (and the field's own density);
///   * beyond that, the field is untouched.
///
/// A [DitherClearing] paints the cleared cells in the paper colour before its child, so it lies over the field (a
/// separate layer) and under the ink. Its inks are the [ClearingInk]s below it: each is a pixel shape ([ClearingShape],
/// for example the wordmark's letters) or, without one, its box. Positions come from the screen at paint time, so the
/// clearing scrolls with the ink and stays on the field's grid (which starts at the screen's top-left corner).
class DitherClearing extends StatefulWidget {
  const DitherClearing({super.key, required this.child, this.clear = 3, this.ramp = 6});

  final Widget child;

  /// Art px around the ink with no dots.
  final double clear;

  /// Art px over which the dots come back.
  final double ramp;

  @override
  State<DitherClearing> createState() => _DitherClearingState();
}

class _DitherClearingState extends State<DitherClearing> {
  final _registry = ClearingRegistry();

  @override
  void dispose() {
    _registry.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => _ClearingScope(
        registry: _registry,
        child: _ClearingPaint(
          registry: _registry,
          px: Px.of(context),
          paper: CantiTheme.of(context).paper,
          clear: widget.clear,
          ramp: widget.ramp,
          child: widget.child,
        ),
      );
}

/// The field's grid: a dot every [cellArtPx] art px (DitherBackground's `cell`).
const cellArtPx = 2;

/// The densest tone of the top field (its 50% checker); a clearing's ramp ends there.
const _fieldMax = 0.5;

/// The shader's 4x4 Bayer threshold for cell (x, y), in [0, 1) (shaders/dither_field.frag `bayer4`).
double bayer4(int x, int y) {
  double b2(int ax, int ay) {
    final v = 0.5 * ax + 0.75 * ay * ay;
    return v - v.floorToDouble();
  }

  return b2(x >> 1, y >> 1) * 0.25 + b2(x, y);
}

/// Whether the dot of cell (x, y) is cleared at [d] art px from the ink.
bool clearedAt(int x, int y, double d, double clear, double ramp) {
  if (d < clear) return true;
  if (d >= clear + ramp) return false;
  return bayer4(x, y) + 0.5 / 16 >= _fieldMax * (d - clear) / ramp;
}

/// A pixel shape to clear around: the distance from any point to its nearest ink pixel, in its own pixels.
class ClearingShape {
  ClearingShape._(this.width, this.height, this._pad, this._dist);

  /// Size in pixels.
  final int width;
  final int height;
  final int _pad;

  /// Distance to the ink per pixel of the padded grid, in pixels ([_pad] around the shape).
  final Float32List _dist;

  /// Far enough: beyond any clearing.
  static const far = 1e9;

  /// [ink] is width x height, nonzero where there is ink. The distance field covers [pad] pixels around it.
  factory ClearingShape.fromInk(int width, int height, Uint8List ink, {int pad = 16}) {
    final w = width + 2 * pad, h = height + 2 * pad;
    const big = 1 << 28;
    // 5-7-11 chamfer distance (within 2% of Euclidean), two passes; units of 1/5 px.
    final d = Int32List(w * h)..fillRange(0, w * h, big);
    for (var y = 0; y < height; y++) {
      for (var x = 0; x < width; x++) {
        if (ink[y * width + x] != 0) d[(y + pad) * w + x + pad] = 0;
      }
    }
    const fwd = [(-1, 0, 5), (0, -1, 5), (-1, -1, 7), (1, -1, 7), (-2, -1, 11), (2, -1, 11), (-1, -2, 11), (1, -2, 11)];
    for (var y = 0; y < h; y++) {
      for (var x = 0; x < w; x++) {
        var v = d[y * w + x];
        for (final (dx, dy, c) in fwd) {
          final nx = x + dx, ny = y + dy;
          if (nx >= 0 && nx < w && ny >= 0) v = math.min(v, d[ny * w + nx] + c);
        }
        d[y * w + x] = v;
      }
    }
    for (var y = h - 1; y >= 0; y--) {
      for (var x = w - 1; x >= 0; x--) {
        var v = d[y * w + x];
        for (final (dx, dy, c) in fwd) {
          final nx = x - dx, ny = y - dy;
          if (nx >= 0 && nx < w && ny < h) v = math.min(v, d[ny * w + nx] + c);
        }
        d[y * w + x] = v;
      }
    }
    final out = Float32List(w * h);
    for (var i = 0; i < w * h; i++) {
      out[i] = d[i] >= big ? far : d[i] / 5;
    }
    return ClearingShape._(width, height, pad, out);
  }

  /// Distance in pixels from the point (x, y) (in pixels from the shape's top-left) to the nearest ink pixel.
  double distance(double x, double y) {
    final w = width + 2 * _pad;
    final ix = x.floor() + _pad, iy = y.floor() + _pad;
    if (ix < 0 || iy < 0 || ix >= w || iy >= height + 2 * _pad) return far;
    return _dist[iy * w + ix];
  }

  static final _assets = <String, Future<ClearingShape?>>{};

  /// The shape of a PNG's opaque pixels (alpha >= 50%), loaded once per run; null if it can't be.
  static Future<ClearingShape?> ofAsset(String path) => _assets[path] ??= _ofAsset(path);

  static Future<ClearingShape?> _ofAsset(String path) async {
    try {
      final bytes = await rootBundle.load(await CantiAssets.key(path));
      final codec = await ui.instantiateImageCodec(bytes.buffer.asUint8List(bytes.offsetInBytes, bytes.lengthInBytes));
      final image = (await codec.getNextFrame()).image;
      codec.dispose();
      final rgba = (await image.toByteData(format: ui.ImageByteFormat.rawRgba))!;
      final ink = Uint8List(image.width * image.height);
      for (var i = 0; i < ink.length; i++) {
        ink[i] = rgba.getUint8(i * 4 + 3) >= 128 ? 1 : 0;
      }
      final s = ClearingShape.fromInk(image.width, image.height, ink);
      image.dispose();
      return s;
    } catch (e) {
      debugPrint('clearing shape $path: $e');
      return null;
    }
  }
}

/// Marks [child] as ink for the [DitherClearing] above it: [shape] stretched over the child's box, or the box itself.
class ClearingInk extends SingleChildRenderObjectWidget {
  const ClearingInk({super.key, this.shape, super.child});

  final ClearingShape? shape;

  @override
  RenderClearingInk createRenderObject(BuildContext context) => RenderClearingInk(_ClearingScope.of(context), shape);

  @override
  void updateRenderObject(BuildContext context, RenderClearingInk renderObject) {
    renderObject
      ..registry = _ClearingScope.of(context)
      ..shape = shape;
  }
}

/// A [ClearingInk] whose shape is a PNG's opaque pixels (see [ClearingShape.ofAsset]); its box until that has loaded.
class AssetClearingInk extends StatefulWidget {
  const AssetClearingInk({super.key, required this.asset, required this.child});

  final String asset;
  final Widget child;

  @override
  State<AssetClearingInk> createState() => _AssetClearingInkState();
}

class _AssetClearingInkState extends State<AssetClearingInk> {
  ClearingShape? _shape;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(AssetClearingInk old) {
    super.didUpdateWidget(old);
    if (old.asset != widget.asset) _load();
  }

  void _load() {
    final asset = widget.asset;
    ClearingShape.ofAsset(asset).then((s) {
      if (mounted && asset == widget.asset) setState(() => _shape = s);
    });
  }

  @override
  Widget build(BuildContext context) => ClearingInk(shape: _shape, child: widget.child);
}

/// The inks under one [DitherClearing].
class ClearingRegistry extends ChangeNotifier {
  final inks = <RenderClearingInk>{};

  void changed() => notifyListeners();
}

class _ClearingScope extends InheritedWidget {
  const _ClearingScope({required this.registry, required super.child});

  final ClearingRegistry registry;

  static ClearingRegistry? of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<_ClearingScope>()?.registry;

  @override
  bool updateShouldNotify(_ClearingScope old) => old.registry != registry;
}

class RenderClearingInk extends RenderProxyBox {
  RenderClearingInk(this._registry, this._shape);

  ClearingRegistry? _registry;
  set registry(ClearingRegistry? v) {
    if (v == _registry) return;
    if (attached) {
      _registry?.inks.remove(this);
      _registry?.changed();
      v?.inks.add(this);
      v?.changed();
    }
    _registry = v;
  }

  ClearingShape? _shape;
  ClearingShape? get shape => _shape;
  set shape(ClearingShape? v) {
    if (v == _shape) return;
    _shape = v;
    _registry?.changed();
  }

  @override
  void attach(PipelineOwner owner) {
    super.attach(owner);
    _registry?.inks.add(this);
    _registry?.changed();
  }

  @override
  void detach() {
    _registry?.inks.remove(this);
    _registry?.changed();
    super.detach();
  }

  @override
  void performLayout() {
    final old = hasSize ? size : null;
    super.performLayout();
    if (size != old) _registry?.changed();
  }
}

class _ClearingPaint extends SingleChildRenderObjectWidget {
  const _ClearingPaint({
    required this.registry,
    required this.px,
    required this.paper,
    required this.clear,
    required this.ramp,
    super.child,
  });

  final ClearingRegistry registry;
  final Px px;
  final Color paper;
  final double clear;
  final double ramp;

  @override
  _RenderClearing createRenderObject(BuildContext context) => _RenderClearing(registry, px, paper, clear, ramp);

  @override
  void updateRenderObject(BuildContext context, _RenderClearing r) {
    r
      ..registry = registry
      ..px = px
      ..paper = paper
      ..clear = clear
      ..ramp = ramp;
  }
}

class _RenderClearing extends RenderProxyBox {
  _RenderClearing(this._registry, this._px, this._paper, this._clear, this._ramp);

  ClearingRegistry _registry;
  set registry(ClearingRegistry v) {
    if (v == _registry) return;
    if (attached) {
      _registry.removeListener(markNeedsPaint);
      v.addListener(markNeedsPaint);
    }
    _registry = v;
    markNeedsPaint();
  }

  Px _px;
  set px(Px v) {
    if (v == _px) return;
    _px = v;
    markNeedsPaint();
  }

  Color _paper;
  set paper(Color v) {
    if (v == _paper) return;
    _paper = v;
    markNeedsPaint();
  }

  double _clear;
  set clear(double v) {
    if (v == _clear) return;
    _clear = v;
    markNeedsPaint();
  }

  double _ramp;
  set ramp(double v) {
    if (v == _ramp) return;
    _ramp = v;
    markNeedsPaint();
  }

  // The last path, reused while nothing moved (for example while only a sprite inside changes frame).
  Object? _key;
  Path? _path;

  @override
  void attach(PipelineOwner owner) {
    super.attach(owner);
    _registry.addListener(markNeedsPaint);
  }

  @override
  void detach() {
    _registry.removeListener(markNeedsPaint);
    super.detach();
  }

  /// The cleared cells, in this box's coordinates: whole cells of the field's grid (from the screen's origin).
  Path _cells() {
    final g = localToGlobal(Offset.zero);
    final unit = _px.px; // one art px, logical
    final cell = cellArtPx * _px.k / _px.dpr; // one field cell, logical (a whole number of device px)
    final inks = <(Offset, double, double, ClearingShape?, Size)>[];
    Rect? bounds;
    for (final ink in _registry.inks) {
      if (!ink.hasSize || !ink.attached) continue;
      final o = MatrixUtils.transformPoint(ink.getTransformTo(this), Offset.zero);
      final s = ink.shape;
      // shape pixels per art px on each axis
      final sx = s == null ? 1.0 : s.width * unit / ink.size.width;
      final sy = s == null ? 1.0 : s.height * unit / ink.size.height;
      inks.add((o, sx, sy, s, ink.size));
      final r = (o & ink.size).inflate((_clear + _ramp) * unit);
      bounds = bounds == null ? r : bounds.expandToInclude(r);
    }
    final key = (g, _px, _clear, _ramp, [for (final i in inks) (i.$1, i.$4, i.$5)].toString());
    if (_path != null && _key == key) return _path!;
    final path = Path();
    if (bounds != null) {
      final x0 = ((g.dx + bounds.left) / cell).floor(), x1 = ((g.dx + bounds.right) / cell).ceil();
      final y0 = ((g.dy + bounds.top) / cell).floor(), y1 = ((g.dy + bounds.bottom) / cell).ceil();
      for (var cy = y0; cy < y1; cy++) {
        int? run;
        for (var cx = x0; cx <= x1; cx++) {
          var hit = false;
          if (cx < x1) {
            final c = Offset((cx + 0.5) * cell - g.dx, (cy + 0.5) * cell - g.dy);
            var d = ClearingShape.far;
            for (final (o, sx, sy, s, size) in inks) {
              final q = c - o; // logical, from the ink's top-left
              final dd = s == null
                  ? _boxDistance(q, size) / unit
                  : s.distance(q.dx / unit * sx, q.dy / unit * sy) / math.max(sx, sy);
              if (dd < d) d = dd;
            }
            hit = clearedAt(cx, cy, d, _clear, _ramp);
          }
          if (hit) {
            run ??= cx;
          } else if (run != null) {
            path.addRect(Rect.fromLTRB(run * cell - g.dx, cy * cell - g.dy, cx * cell - g.dx, (cy + 1) * cell - g.dy));
            run = null;
          }
        }
      }
    }
    _key = key;
    return _path = path;
  }

  static double _boxDistance(Offset q, Size s) {
    final dx = math.max(0.0, math.max(-q.dx, q.dx - s.width));
    final dy = math.max(0.0, math.max(-q.dy, q.dy - s.height));
    return math.sqrt(dx * dx + dy * dy);
  }

  @override
  void paint(PaintingContext context, Offset offset) {
    final path = _cells();
    context.canvas.drawPath(
      path.shift(offset),
      Paint()
        ..color = _paper
        ..isAntiAlias = false,
    );
    super.paint(context, offset);
  }
}
