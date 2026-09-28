import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'backend.dart';
import 'status_screen.dart';
import 'theme/assets.dart';
import 'theme/canti_theme.dart';
import 'theme/dither_background.dart';
import 'theme/pixel.dart';

/// The Flutter part of the VOX app. Android embeds it (android/app, `MainActivity`); ../desktop runs it on Linux with
/// a [FakeBackend].
///
/// Look: a 1-bit pixel kit (theme/kit.dart) in the Canti brand's two tones, [cantiTheme] at the device's pixel scale
/// ([Px]), windows over the [DitherBackground] dot field.
class VoxUiApp extends StatelessWidget {
  const VoxUiApp({super.key, required this.backend, this.animateBackground, this.themeMode = ThemeMode.system, this.home});

  final VoxBackend backend;

  /// Light or dark; by default the platform's setting.
  final ThemeMode themeMode;

  /// null: animate the background unless in a test or reduced motion is on.
  final bool? animateBackground;

  /// The first screen; by default the status screen (the desktop preview opens others directly).
  final Widget? home;

  // Only pick the brightness; the builder puts the theme for this screen's pixel scale on top.
  static final _light = cantiTheme(Brightness.light, Px(1));
  static final _dark = cantiTheme(Brightness.dark, Px(1));
  static bool _licensed = false;

  static void _addLicenses() {
    if (_licensed) return;
    _licensed = true;
    LicenseRegistry.addLicense(() async* {
      for (final (name, file) in [('Press Start 2P', 'PressStart2P-OFL.txt'), ('Tiny5', 'Tiny5-OFL.txt')]) {
        final key = await CantiAssets.key('assets/fonts/$file');
        yield LicenseEntryWithLineBreaks([name], await rootBundle.loadString(key));
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    _addLicenses();
    return MaterialApp(
      title: 'Canti',
      debugShowCheckedModeBanner: false,
      theme: _light,
      darkTheme: _dark,
      themeMode: themeMode,
      builder: (context, child) {
        final mq = MediaQuery.of(context);
        final px = Px(mq.devicePixelRatio, mq.textScaler);
        return PxScope(
          px: px,
          // Text scale is applied by Px in whole steps (pixel fonts stay on the grid), so not again by Flutter.
          child: MediaQuery(
            data: mq.copyWith(textScaler: TextScaler.noScaling),
            child: Theme(
              data: cantiTheme(Theme.of(context).brightness, px),
              child: ScrollConfiguration(
                behavior: ScrollConfiguration.of(context).copyWith(scrollbars: false),
                child: _Backdrop(animate: animateBackground, child: child!),
              ),
            ),
          ),
        );
      },
      home: home ?? StatusScreen(backend: backend),
    );
  }
}

/// The page colour and the dot field, under the navigator. Built once per theme change, never by screen state: the
/// screens tell the field what Canti is doing through the [BackdropMood] it hands down ([BackdropScope]).
class _Backdrop extends StatefulWidget {
  const _Backdrop({required this.child, this.animate});

  final Widget child;
  final bool? animate;

  @override
  State<_Backdrop> createState() => _BackdropState();
}

class _BackdropState extends State<_Backdrop> {
  final _mood = BackdropMood();

  @override
  void dispose() {
    _mood.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => ColoredBox(
        color: Theme.of(context).colorScheme.surface,
        child: BackdropScope(
          mood: _mood,
          child: Stack(
            fit: StackFit.expand,
            children: [
              // clear under the status and navigation bars (edge-to-edge on Android), fading in below them
              DitherBackground(animate: widget.animate, insets: MediaQuery.viewPaddingOf(context), mood: _mood),
              widget.child,
            ],
          ),
        ),
      );
}
