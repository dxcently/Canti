import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';

import 'pixel.dart';

/// Asset keys for this package's assets. On Android `vox_ui` is the root (the module), so its assets have plain
/// keys; in the desktop runner it is a dependency, so they are under `packages/vox_ui/`. The manifest says which.
abstract final class CantiAssets {
  static const package = 'vox_ui';
  static Future<String>? _prefix;

  /// The key prefix once [key] has resolved it (null before): lets widgets build synchronously after the first read.
  static String? get prefix => _known;
  static String? _known;

  static Future<String> _resolve() async {
    try {
      final m = await AssetManifest.loadFromAssetBundle(rootBundle);
      return _known = m.listAssets().any((a) => a.startsWith('packages/$package/')) ? 'packages/$package/' : '';
    } catch (_) {
      return _known = '';
    }
  }

  /// The key of [path] in this build.
  static Future<String> key(String path) async => '${await (_prefix ??= _resolve())}$path';

  /// Both possible keys, the package one first (for loaders that just try).
  static List<String> candidates(String path) => ['packages/$package/$path', path];
}

/// One of the brand PNGs (assets/brand, pixel art from brand/tools/stipple.py `app`), drawn at a whole number of
/// device pixels per dot: the PNG made for that scale, 1:1, without smoothing, its origin snapped to the device grid.
/// So the dots stay square and even at any devicePixelRatio (on a 2.625x phone too). Its logical size follows the
/// scale, so it differs a little between screens. Until the asset key is known (one manifest read per run) it is an
/// empty box of the same size.
class BrandArt extends StatelessWidget {
  /// The app icon, 48 dots across, n = round(devicePixelRatio) device px per dot (48 dp at 1x, 2x, 3x...).
  const BrandArt.icon({super.key, required bool on, this.semanticLabel})
      : name = on ? 'canti-icon-on' : 'canti-icon-off',
        width = 48,
        height = 48,
        maxScale = 4,
        perArtPixel = false;

  /// The stipple wordmark, 89 x 41 cells, one cell per art pixel of the kit ([Px.k] device px; 178 x 82 dp at 1x
  /// and 3x). [light] is the mint-cream one for the dark theme.
  const BrandArt.wordmark({super.key, required bool light, this.semanticLabel})
      : name = light ? 'canti-wordmark-light' : 'canti-wordmark',
        width = 89,
        height = 41,
        maxScale = 8,
        perArtPixel = true;

  final String name;

  /// Size in dots.
  final int width;
  final int height;

  /// The largest scale with its own PNG (`name@1.png` .. `name@maxScale.png`).
  final int maxScale;

  /// Device px per dot: the kit's art pixel ([Px.k]) if true, else round(devicePixelRatio).
  final bool perArtPixel;
  final String? semanticLabel;

  /// The 1x PNG, whose opaque pixels are the shape a [DitherClearing] clears around.
  String get shapeAsset => 'assets/brand/$name@1.png';

  /// The PNG to use for [scale] device px per dot and the whole factor it is magnified by: the biggest file whose
  /// scale divides [scale] (so above [max] it is still an exact, nearest-neighbour magnification).
  @visibleForTesting
  static (int, int) pick(int scale, int max) {
    for (var f = scale < max ? scale : max; f > 1; f--) {
      if (scale % f == 0) return (f, scale ~/ f);
    }
    return (1, scale);
  }

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final scale = perArtPixel ? p.k : (p.dpr.round() < 1 ? 1 : p.dpr.round());
    final (file, _) = pick(scale, maxScale);
    final w = width * scale / p.dpr, h = height * scale / p.dpr;
    final path = 'assets/brand/$name@$file.png';
    Widget image(String key) => PixelSnap(
          child: Image(
            image: ExactAssetImage(key),
            width: w,
            height: h,
            fit: BoxFit.fill,
            filterQuality: FilterQuality.none,
            isAntiAlias: false,
            gaplessPlayback: true,
            semanticLabel: semanticLabel,
            excludeFromSemantics: semanticLabel == null,
          ),
        );
    final prefix = CantiAssets.prefix;
    return SizedBox(
      width: w,
      height: h,
      child: prefix != null
          ? image('$prefix$path')
          : FutureBuilder<String>(
              future: CantiAssets.key(path),
              builder: (context, snap) => snap.data == null ? const SizedBox.shrink() : image(snap.data!),
            ),
    );
  }
}
