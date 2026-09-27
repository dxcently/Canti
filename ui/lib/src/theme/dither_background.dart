import 'dart:async';
import 'dart:io' show Platform;
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import 'assets.dart';
import 'canti_theme.dart';
import 'clearing.dart';
import 'pixel.dart';

/// The dot-field mood behind the screens: an ordered-dither fragment shader (shaders/dither_field.frag).
///
/// Cost: one full-screen quad in its own layer ([RepaintBoundary]); nothing above it repaints it, and it never
/// rebuilds widgets. When animated, a timer advances the shader's `uTime` [fps] times a second (default 6) through a
/// [ValueNotifier] the painter listens to, so only this layer repaints. It stops while the app is not visible,
/// when the platform asks for reduced motion, and under `flutter test`. If the shader can't be loaded, nothing is
/// drawn.
class DitherBackground extends StatefulWidget {
  const DitherBackground({
    super.key,
    this.animate,
    this.fps = 6,
    this.cell = cellArtPx,
    this.reach = 0.34,
    this.insets = EdgeInsets.zero,
    this.fade = 3,
  });

  /// null: animate unless in a test or reduced motion is on.
  final bool? animate;
  final int fps;

  /// Dot pitch in art pixels ([Px]), so the dots share the grid of the windows on top.
  final int cell;

  /// How far down the top dot field reaches (fraction of the height).
  final double reach;

  /// The system bars over the field (status bar, navigation): only [EdgeInsets.top] and [EdgeInsets.bottom] count.
  /// Under them the field is clear, and it fades in from their edges over [fade] cells (a Bayer ramp, like the
  /// clearings around text in clearing.dart); the pillars stand on the bottom bar. On the desktop both are 0, so the
  /// field fades in from the window's edges.
  final EdgeInsets insets;
  final int fade;

  @override
  State<DitherBackground> createState() => _DitherBackgroundState();
}

class _DitherBackgroundState extends State<DitherBackground> {
  static Future<ui.FragmentProgram?>? _program;
  static final _inTest = !kIsWeb && Platform.environment.containsKey('FLUTTER_TEST');

  ui.FragmentShader? _shader;
  final _time = ValueNotifier<double>(0);
  final _clock = Stopwatch();
  Timer? _timer;
  late final AppLifecycleListener _life;
  bool _visible = true;

  static Future<ui.FragmentProgram?> _load() async {
    for (final key in CantiAssets.candidates('shaders/dither_field.frag')) {
      try {
        return await ui.FragmentProgram.fromAsset(key);
      } catch (_) {
        // try the next key (package vs root asset)
      }
    }
    return null;
  }

  @override
  void initState() {
    super.initState();
    _life = AppLifecycleListener(onStateChange: (s) {
      _visible = s == AppLifecycleState.resumed || s == AppLifecycleState.inactive;
      _sync();
    });
    (_program ??= _load()).then((p) {
      if (!mounted || p == null) return;
      setState(() => _shader = p.fragmentShader());
      _sync();
    });
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _sync();
  }

  bool get _animating {
    final wanted = widget.animate ?? !_inTest;
    final reduce = MediaQuery.maybeDisableAnimationsOf(context) ?? false;
    return wanted && !reduce && _visible && _shader != null;
  }

  void _sync() {
    if (!mounted) return;
    if (_animating) {
      if (_timer != null) return;
      _clock.start();
      _timer = Timer.periodic(Duration(milliseconds: 1000 ~/ widget.fps), (_) {
        _time.value = _clock.elapsedMilliseconds / 1000.0;
      });
    } else {
      _clock.stop();
      _timer?.cancel();
      _timer = null;
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    _life.dispose();
    _time.dispose();
    _shader?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final shader = _shader;
    final p = Px.of(context);
    final dpr = p.dpr;
    final t = CantiTheme.of(context);
    // On the art-pixel grid: a dot every [cell] art px, with a gap of about 0.4 art px (whole device px).
    final cellPx = (widget.cell * p.k).toDouble();
    final gapPx = cellPx >= 4 ? (0.4 * p.k).roundToDouble().clamp(1.0, 4.0) : 0.0;
    return RepaintBoundary(
      child: shader == null
          ? const SizedBox.expand()
          : CustomPaint(
              size: Size.infinite,
              isComplex: true,
              willChange: _timer != null,
              painter: _DitherPainter(
                shader: shader,
                time: _time,
                color: t.dot,
                cell: cellPx / dpr,
                gap: gapPx / dpr,
                reach: widget.reach,
                insets: widget.insets,
                fade: widget.fade.toDouble(),
              ),
            ),
    );
  }
}

class _DitherPainter extends CustomPainter {
  _DitherPainter({
    required this.shader,
    required this.time,
    required this.color,
    required this.cell,
    required this.gap,
    required this.reach,
    required this.insets,
    required this.fade,
  }) : super(repaint: time);

  final ui.FragmentShader shader;
  final ValueListenable<double> time;
  final Color color;
  final double cell;
  final double gap;
  final double reach;
  final EdgeInsets insets;
  final double fade;

  @override
  void paint(Canvas canvas, Size size) {
    shader
      ..setFloat(0, size.width)
      ..setFloat(1, size.height)
      ..setFloat(2, cell)
      ..setFloat(3, time.value)
      ..setFloat(4, color.r)
      ..setFloat(5, color.g)
      ..setFloat(6, color.b)
      ..setFloat(7, color.a)
      ..setFloat(8, reach)
      ..setFloat(9, gap)
      ..setFloat(10, insets.top)
      ..setFloat(11, insets.bottom)
      ..setFloat(12, fade);
    canvas.drawRect(Offset.zero & size, Paint()..shader = shader);
  }

  @override
  bool shouldRepaint(_DitherPainter old) =>
      old.color != color || old.cell != cell || old.gap != gap || old.reach != reach ||
      old.insets != insets ||
      old.fade != fade ||
      old.shader != shader;
}
