import 'dart:async';
import 'dart:io' show Platform;
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import 'assets.dart';
import 'canti_theme.dart';
import 'clearing.dart';
import 'pixel.dart';

/// The EQ band's height in cells of the field ([cellArtPx] art px each): the bars and their peak dots stay under it
/// (shaders/dither_field.frag `BAND`). No screen reserves room for it: the bars show only where content leaves space.
const eqBandCells = 14;

/// The EQ bars' motif; its index is the shader's `uMode`.
enum BackdropMotif {
  /// Idle: a calm row of short ticks.
  ticks,

  /// Hearing: dithered level bars.
  bars,

  /// Off, paused (Canti ignores sounds): no bars, and the top field thinned to a quarter.
  flat,
}

/// What the background shows: Canti's held state ([held], the badge's: `idle`, `hearing`, `paused`, `off`, ...; the
/// status screen sets it) and, while a screen records a take (calibration, gesture training), that it is listening,
/// with the live mic level when the source gives one. Shared through [BackdropScope]; only the background listens.
class BackdropMood extends ChangeNotifier {
  String _held = 'idle';
  bool _listening = false;
  double? _levelDb;

  /// The motif for a held state of the badge (Badge.kt `BadgeStates.held`): the phrase window, a sound waiting or a
  /// hold-scroll are hearing; off, paused and tap-to-wake (the Pico paused itself) are off; the rest (idle, cursor,
  /// error, a new state) idle.
  static BackdropMotif motifFor(String held) => switch (held) {
        'hearing' || 'pending' || 'hold-scroll' || 'hold_scroll' => BackdropMotif.bars,
        'off' || 'paused' || 'tap-to-wake' || 'tap_to_wake' => BackdropMotif.flat,
        _ => BackdropMotif.ticks,
      };

  /// A level in dBFS as the bars' height, 0..1 (-60 dBFS and under: 0; -15 and over: 1).
  static double levelOf(double db) => ((db + 60) / 45).clamp(0.0, 1.0);

  String get held => _held;
  set held(String s) {
    if (s == _held) return;
    _held = s;
    notifyListeners();
  }

  /// A screen records (true) or stopped recording (false); [levelDb] is the live mic level, null when the source sends
  /// none (the bars then move by themselves).
  void listen(bool on, {double? levelDb}) {
    final db = on ? levelDb : null;
    if (on == _listening && db == _levelDb) return;
    _listening = on;
    _levelDb = db;
    notifyListeners();
  }

  /// Listening overrides the held state (a calibration pauses Canti's actions while it records).
  BackdropMotif get motif => _listening ? BackdropMotif.bars : motifFor(_held);

  /// The bars' height 0..1 from the live level, or null for none.
  double? get level => _levelDb == null ? null : levelOf(_levelDb!);

  /// The mood of the app around [context], or null outside one (a screen tested alone).
  static BackdropMood? maybeOf(BuildContext context) =>
      context.getInheritedWidgetOfExactType<BackdropScope>()?.mood;
}

/// Hands a [BackdropMood] to the screens (they write it; they never rebuild on it).
class BackdropScope extends InheritedWidget {
  const BackdropScope({super.key, required this.mood, required super.child});

  final BackdropMood mood;

  @override
  bool updateShouldNotify(BackdropScope old) => old.mood != mood;
}

/// The dot-field mood behind the screens: an ordered-dither fragment shader (shaders/dither_field.frag), a dot field
/// along the top and a row of EQ bars along the bottom that follow [mood]: ticks when idle, level bars while Canti
/// hears, nothing (and a thinner top field) when it is off or paused.
///
/// Cost: one full-screen quad in its own layer ([RepaintBoundary]); nothing above it repaints it, and it never
/// rebuilds widgets. When animated, a timer advances the shader's `uTime` [fps] times a second (default 6) through a
/// [ValueNotifier] the painter listens to, so only this layer repaints; the painter also listens to [mood] (a
/// change of state, or a new level, about 10 a second while a screen records). The timer stops while the app is not
/// visible, when the platform asks for reduced motion, while the motif is [BackdropMotif.flat], and under
/// `flutter test`. If the shader can't be loaded, nothing is drawn.
class DitherBackground extends StatefulWidget {
  const DitherBackground({
    super.key,
    this.animate,
    this.fps = 6,
    this.cell = cellArtPx,
    this.reach = 0.34,
    this.insets = EdgeInsets.zero,
    this.fade = 3,
    this.mood,
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
  /// clearings around text in clearing.dart); the EQ bars stand on the bottom bar. On the desktop both are 0, so the
  /// field fades in from the window's edges.
  final EdgeInsets insets;
  final int fade;

  /// What the EQ bars show; null: idle ticks.
  final BackdropMood? mood;

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
    widget.mood?.addListener(_sync);
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
  void didUpdateWidget(DitherBackground old) {
    super.didUpdateWidget(old);
    if (old.mood != widget.mood) {
      old.mood?.removeListener(_sync);
      widget.mood?.addListener(_sync);
      _sync();
    }
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _sync();
  }

  bool get _animating {
    final wanted = widget.animate ?? !_inTest;
    final reduce = MediaQuery.maybeDisableAnimationsOf(context) ?? false;
    final still = widget.mood?.motif == BackdropMotif.flat;
    return wanted && !reduce && !still && _visible && _shader != null;
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
    widget.mood?.removeListener(_sync);
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
                mood: widget.mood,
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
    this.mood,
    required this.color,
    required this.cell,
    required this.gap,
    required this.reach,
    required this.insets,
    required this.fade,
  }) : super(repaint: mood == null ? time : Listenable.merge([time, mood]));

  final ui.FragmentShader shader;
  final ValueListenable<double> time;
  final BackdropMood? mood;
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
      ..setFloat(12, fade)
      ..setFloat(13, (mood?.motif ?? BackdropMotif.ticks).index.toDouble())
      ..setFloat(14, mood?.level ?? -1);
    canvas.drawRect(Offset.zero & size, Paint()..shader = shader);
  }

  @override
  bool shouldRepaint(_DitherPainter old) =>
      old.color != color || old.cell != cell || old.gap != gap || old.reach != reach ||
      old.insets != insets ||
      old.fade != fade ||
      old.mood != mood ||
      old.shader != shader;
}
