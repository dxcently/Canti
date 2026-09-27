import 'dart:async';
import 'dart:convert';
import 'dart:io' show Platform;
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';

import 'assets.dart';
import 'clearing.dart';
import 'pixel.dart';

/// The Canti character sheet: the same files and format as the Android floating badge (CantiBadgeView.kt,
/// `BadgeSprite`), which reads this package's assets/badge from the APK's flutter_assets/. A manifest (`canti_badge.json`) names the sheet, its frame grid and, per
/// state, the frame indices, ms per frame, whether it loops, and a still frame for reduced motion.
class BadgeSprite {
  BadgeSprite({
    required this.sheet,
    required this.frameW,
    required this.frameH,
    required this.columns,
    required this.frameCount,
    required this.anims,
    this.artPxDp = 0,
  });

  /// The sheet's asset path.
  final String sheet;
  final int frameW;
  final int frameH;
  final int columns;
  final int frameCount;
  final Map<String, BadgeAnim> anims;

  /// dp per art pixel on the Android badge (`n = round(density x artPxDp)` device px there); 0 if the manifest has
  /// none.
  /// The header ignores it: there a sheet pixel is one kit art pixel.
  final double artPxDp;

  int frameX(int i) => (i % columns) * frameW;
  int frameY(int i) => (i ~/ columns) * frameH;

  /// Parses and checks a manifest (the checks are Kotlin's); the sheet path is relative to [dir].
  factory BadgeSprite.parse(String json, {String dir = 'assets/badge/'}) {
    final o = jsonDecode(json) as Map<String, Object?>;
    final n = o['frameCount']! as int;
    final anims = <String, BadgeAnim>{};
    for (final MapEntry(key: name, value: v) in (o['states']! as Map<String, Object?>).entries) {
      final a = v! as Map<String, Object?>;
      final frames = [for (final f in a['frames']! as List) f as int];
      final ms = [for (final m in a['ms']! as List) m as int];
      if (frames.isEmpty || frames.length != ms.length) throw FormatException('badge state $name: frames/ms mismatch');
      if (frames.any((f) => f < 0 || f >= n)) throw FormatException('badge state $name: frame out of range');
      if (ms.any((m) => m <= 0)) throw FormatException('badge state $name: ms must be > 0');
      final still = (a['still'] as int?) ?? 0;
      if (still < 0 || still >= frames.length) throw FormatException('badge state $name: still out of range');
      anims[name] = BadgeAnim(name, a['loop']! as bool, frames, ms, still);
    }
    if (!anims.containsKey('idle')) throw const FormatException('badge manifest has no idle state');
    final artPxDp = ((o['artPxDp'] as num?) ?? 0).toDouble();
    if (artPxDp < 0) throw const FormatException('badge manifest: artPxDp must be >= 0');
    return BadgeSprite(
      sheet: dir + (o['sheet']! as String),
      frameW: o['frameWidth']! as int,
      frameH: o['frameHeight']! as int,
      columns: o['columns']! as int,
      frameCount: n,
      anims: anims,
      artPxDp: artPxDp,
    );
  }
}

class BadgeAnim {
  BadgeAnim(this.name, this.loop, this.frames, this.ms, this.still) : totalMs = ms.fold(0, (a, b) => a + b);

  final String name;
  final bool loop;
  final List<int> frames;
  final List<int> ms;
  final int still;
  final int totalMs;
}

/// Which frame to show when: a held state (looping, or resting on its still frame) and at most one one-shot over it,
/// which hands back to the held state when done. A port of Kotlin's `BadgePlayer`; pure, times in any monotonic ms.
///
/// States are the badge's labels (`idle`, `hearing`, `pending`, `hold-scroll`, `cursor`, `paused`, `off`, `error`;
/// one-shots `scroll-up`, `scroll-down`, `back`, `forward`, `home`, `hearing`, `ignored`, `error`); `-` and `_` are
/// the same. A one-shot plays `<name>_once` when the manifest has it; a name the manifest lacks plays idle.
class BadgePlayer {
  BadgePlayer(this.sprite) : _heldAnim = sprite.anims['idle']!;

  final BadgeSprite sprite;

  /// Show still frames: the held state's still frame, and a one-shot's still frame for the one-shot's length.
  bool reduceMotion = false;

  String _held = 'idle';
  BadgeAnim _heldAnim;
  int _heldStart = 0;
  bool _started = false;
  String? _shot;
  BadgeAnim? _shotAnim;
  int _shotStart = 0;
  bool _lastScrollUp = true;

  String get held => _held;

  /// What is on screen: the one-shot while it plays, else the held state.
  String get showing => _shot ?? _held;

  static String _key(String s) => s.replaceAll('-', '_');

  /// Holds [state]; false if it already was (its loop is not restarted).
  bool setHeld(String state, int now) {
    final s = _key(state);
    if (s == _held && _started) return false;
    _started = true;
    _held = s;
    _heldAnim = _anim(s, once: false);
    _heldStart = now;
    return true;
  }

  void playOnce(String state, int now) {
    final s = _key(state);
    if (s == 'scroll_up') _lastScrollUp = true;
    if (s == 'scroll_down') _lastScrollUp = false;
    if (_held == 'hold_scroll') _heldAnim = _anim(_held, once: false);
    _shot = s;
    _shotAnim = _anim(s, once: true);
    _shotStart = now;
  }

  /// The sheet frame to draw at [now] (ends a finished one-shot).
  int frameAt(int now) {
    _expire(now);
    final sa = _shotAnim;
    return sa != null ? _index(sa, now - _shotStart, false) : _index(_heldAnim, now - _heldStart, _heldAnim.loop);
  }

  /// ms from [now] until the frame changes, or -1 if it never will without a new state.
  int nextChangeIn(int now) {
    _expire(now);
    final sa = _shotAnim;
    if (sa != null) {
      final t = now - _shotStart;
      if (reduceMotion) return sa.totalMs - t;
      final u = _untilNext(sa, t, false);
      return u < 0 || u > sa.totalMs - t ? sa.totalMs - t : u;
    }
    if (reduceMotion || _heldAnim.frames.length == 1) return -1;
    return _untilNext(_heldAnim, now - _heldStart, _heldAnim.loop);
  }

  void _expire(int now) {
    final sa = _shotAnim;
    if (sa == null) return;
    if (now - _shotStart >= sa.totalMs) {
      _heldStart = _shotStart + sa.totalMs; // the held loop starts over where the one-shot ended
      _shot = null;
      _shotAnim = null;
    }
  }

  int _index(BadgeAnim a, int elapsed, bool loop) {
    if (reduceMotion) return a.frames[a.still];
    var t = loop ? elapsed % a.totalMs : elapsed;
    for (var i = 0; i < a.ms.length; i++) {
      if (t < a.ms[i]) return a.frames[i];
      t -= a.ms[i];
    }
    return a.frames[a.still]; // a one-shot used as a held state rests on its still frame
  }

  int _untilNext(BadgeAnim a, int elapsed, bool loop) {
    if (!loop && elapsed >= a.totalMs) return -1;
    var t = loop ? elapsed % a.totalMs : elapsed;
    for (var i = 0; i < a.ms.length; i++) {
      if (t < a.ms[i]) return a.ms[i] - t;
      t -= a.ms[i];
    }
    return -1;
  }

  BadgeAnim _anim(String s, {required bool once}) {
    final base = s == 'hold_scroll' ? (_lastScrollUp ? 'hold_scroll_up' : 'hold_scroll_down') : s;
    final a = sprite.anims;
    return (once ? a['${base}_once'] : null) ?? a[base] ?? a['idle']!;
  }
}

/// A loaded sheet: the manifest, the image, and the character's footprint (every frame's pixels, for a clearing).
class LoadedSprite {
  LoadedSprite(this.sprite, this.image, this.footprint);

  final BadgeSprite sprite;
  final ui.Image image;
  final ClearingShape footprint;

  static const manifest = 'assets/badge/canti_badge.json';
  static Future<LoadedSprite?>? _loading;

  /// The sheet, loaded once per run (null if it can't be).
  static Future<LoadedSprite?> load() => _loading ??= _load();

  static Future<LoadedSprite?> _load() async {
    try {
      final sprite = BadgeSprite.parse(await rootBundle.loadString(await CantiAssets.key(manifest)));
      final bytes = await rootBundle.load(await CantiAssets.key(sprite.sheet));
      final codec = await ui.instantiateImageCodec(bytes.buffer.asUint8List(bytes.offsetInBytes, bytes.lengthInBytes));
      final image = (await codec.getNextFrame()).image;
      codec.dispose();
      final rgba = (await image.toByteData(format: ui.ImageByteFormat.rawRgba))!;
      return LoadedSprite(sprite, image, _footprint(sprite, rgba, image.width));
    } catch (e) {
      debugPrint('canti sprite: $e');
      return null;
    }
  }

  static ClearingShape _footprint(BadgeSprite s, ByteData rgba, int stride) {
    final ink = Uint8List(s.frameW * s.frameH);
    for (var i = 0; i < s.frameCount; i++) {
      final x0 = s.frameX(i), y0 = s.frameY(i);
      for (var y = 0; y < s.frameH; y++) {
        for (var x = 0; x < s.frameW; x++) {
          if (rgba.getUint8(((y0 + y) * stride + x0 + x) * 4 + 3) >= 128) ink[y * s.frameW + x] = 1;
        }
      }
    }
    return ClearingShape.fromInk(s.frameW, s.frameH, ink);
  }
}

/// Tells a [CantiSprite] what to play: a held state, and one-shots over it.
class SpriteController extends ChangeNotifier {
  SpriteController([this._held = 'idle']);

  String _held;
  String get held => _held;
  (String, int)? _shot;
  int _shots = 0;

  /// The last one-shot asked for and its sequence number.
  (String, int)? get shot => _shot;

  set held(String s) {
    if (s == _held) return;
    _held = s;
    notifyListeners();
  }

  void playOnce(String s) {
    _shot = (s, ++_shots);
    notifyListeners();
  }
}

/// The Canti character from the badge sheet, pixel-exact: each art pixel of the sheet is one art pixel of the kit
/// ([Px.k] device px), drawn nearest-neighbour at a whole-pixel position ([PixelSnap]). Frame timing is the
/// manifest's; one timer for the next frame change, none while the frame can't change. Still frames (each state's
/// `still`) when animations are off (the platform's reduce-motion setting, [TickerMode], the app in the background,
/// and under `flutter test` unless [animate] is true). Until the sheet has loaded it is an empty box of its size.
class CantiSprite extends StatefulWidget {
  const CantiSprite({super.key, required this.controller, this.animate, this.semanticLabel});

  final SpriteController controller;
  final bool? animate;
  final String? semanticLabel;

  /// The frame size in art px of the current sheet (the box before it loads, so the header doesn't jump).
  static const defaultFrameW = 34, defaultFrameH = 47;

  @override
  State<CantiSprite> createState() => _CantiSpriteState();
}

class _CantiSpriteState extends State<CantiSprite> {
  static final _inTest = !kIsWeb && Platform.environment.containsKey('FLUTTER_TEST');
  static final _clock = Stopwatch()..start();

  LoadedSprite? _sheet;
  BadgePlayer? _player;
  int _seenShot = 0;
  Timer? _timer;
  late final AppLifecycleListener _life;
  bool _visible = true;
  bool _still = true;

  int get _now => _clock.elapsedMilliseconds;

  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_apply);
    _life = AppLifecycleListener(onStateChange: (s) {
      _visible = s == AppLifecycleState.resumed || s == AppLifecycleState.inactive;
      _sync();
    });
    LoadedSprite.load().then((s) {
      if (!mounted || s == null) return;
      setState(() {
        _sheet = s;
        _player = BadgePlayer(s.sprite);
      });
      _seenShot = widget.controller.shot?.$2 ?? 0; // one-shots from before the sheet loaded are stale
      _apply();
    });
  }

  @override
  void didUpdateWidget(CantiSprite old) {
    super.didUpdateWidget(old);
    if (old.controller != widget.controller) {
      old.controller.removeListener(_apply);
      widget.controller.addListener(_apply);
      _apply();
    }
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _sync(rebuild: false); // build follows
  }

  @override
  void dispose() {
    widget.controller.removeListener(_apply);
    _timer?.cancel();
    _life.dispose();
    super.dispose();
  }

  void _apply() {
    final p = _player;
    if (p == null || !mounted) return;
    final c = widget.controller;
    p.setHeld(c.held, _now);
    final shot = c.shot;
    if (shot != null && shot.$2 != _seenShot) {
      _seenShot = shot.$2;
      p.playOnce(shot.$1, _now);
    }
    setState(() {});
    _schedule();
  }

  void _sync({bool rebuild = true}) {
    if (!mounted) return;
    final animate = widget.animate ?? !_inTest;
    final still = !animate ||
        !_visible ||
        !TickerMode.valuesOf(context).enabled ||
        (MediaQuery.maybeDisableAnimationsOf(context) ?? false);
    if (still != _still) {
      _still = still;
      _player?.reduceMotion = still;
      if (rebuild) setState(() {});
    }
    _schedule();
  }

  void _schedule() {
    _timer?.cancel();
    _timer = null;
    final p = _player;
    if (p == null) return;
    p.reduceMotion = _still;
    final wait = p.nextChangeIn(_now);
    if (wait < 0) return;
    _timer = Timer(Duration(milliseconds: wait < 1 ? 1 : wait), () {
      if (!mounted) return;
      setState(() {});
      _schedule();
    });
  }

  @override
  Widget build(BuildContext context) {
    final px = Px.of(context);
    final s = _sheet;
    final fw = s?.sprite.frameW ?? CantiSprite.defaultFrameW, fh = s?.sprite.frameH ?? CantiSprite.defaultFrameH;
    final size = Size(px(fw), px(fh));
    final p = _player;
    Widget art = s == null || p == null
        ? const SizedBox.shrink()
        : PixelSnap(child: CustomPaint(size: size, painter: _FramePainter(s, p.frameAt(_now))));
    if (widget.semanticLabel != null) art = Semantics(image: true, label: widget.semanticLabel, child: art);
    // ink for a DitherClearing above: every pixel any frame uses (the box until the sheet has loaded)
    return ClearingInk(shape: s?.footprint, child: SizedBox.fromSize(size: size, child: art));
  }
}

class _FramePainter extends CustomPainter {
  _FramePainter(this.sheet, this.frame);

  final LoadedSprite sheet;
  final int frame;

  static final _paint = Paint()
    ..filterQuality = FilterQuality.none
    ..isAntiAlias = false;

  @override
  void paint(Canvas canvas, Size size) {
    final s = sheet.sprite;
    final src = Rect.fromLTWH(s.frameX(frame).toDouble(), s.frameY(frame).toDouble(), s.frameW.toDouble(),
        s.frameH.toDouble());
    canvas.drawImageRect(sheet.image, src, Offset.zero & size, _paint);
  }

  @override
  bool shouldRepaint(_FramePainter old) => old.frame != frame || old.sheet != sheet;
}
