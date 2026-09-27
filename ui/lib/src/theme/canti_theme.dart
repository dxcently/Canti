import 'package:flutter/material.dart';

import 'kit.dart';
import 'pixel.dart';

/// The Canti brand colours (../brand/README.md "Colours"). The UI uses two of them per theme (ink on paper) plus the
/// signal colours where they mean something; the icon and the wordmark keep their own.
abstract final class CantiColors {
  static const mintCream = Color(0xFFDDEBD3);
  static const visorNavy = Color(0xFF1D2757);
  static const signalOrange = Color(0xFFF2A33A);
  static const signalYellow = Color(0xFFF6C945);
  static const signalRed = Color(0xFFD6453D);
}

/// The two tones. Light: visor-navy ink on mint-cream paper. Dark: the same pair swapped. Read it with
/// `CantiTheme.of(context)`.
@immutable
class CantiTheme extends ThemeExtension<CantiTheme> {
  const CantiTheme({required this.ink, required this.paper, required this.dark});

  /// Lines, text and filled (inverted) panels.
  final Color ink;

  /// Window fills and the page.
  final Color paper;
  final bool dark;

  /// The dot field's colour: the ink, solid (the density is the dither, not a tint).
  Color get dot => ink;

  static const light = CantiTheme(ink: CantiColors.visorNavy, paper: CantiColors.mintCream, dark: false);
  static const darkTheme = CantiTheme(ink: CantiColors.mintCream, paper: CantiColors.visorNavy, dark: true);

  static CantiTheme of(BuildContext context) => Theme.of(context).extension<CantiTheme>()!;

  @override
  CantiTheme copyWith({Color? ink, Color? paper}) =>
      CantiTheme(ink: ink ?? this.ink, paper: paper ?? this.paper, dark: dark);

  @override
  CantiTheme lerp(ThemeExtension<CantiTheme>? other, double t) => t < 0.5 ? this : other as CantiTheme;
}

final _cache = <(Brightness, Px), ThemeData>{};

/// The Material theme for the pixel kit at pixel scale [p]: square framed buttons that invert when pressed or
/// selected, corner brackets for hover and focus, the pixel faces at whole multiples, no shadows, no ripples.
ThemeData cantiTheme(Brightness brightness, Px p) => _cache[(brightness, p)] ??= _build(brightness, p);

ThemeData _build(Brightness brightness, Px p) {
  final dark = brightness == Brightness.dark;
  final t = dark ? CantiTheme.darkTheme : CantiTheme.light;
  final ink = t.ink, paper = t.paper;
  final scheme = ColorScheme(
    brightness: brightness,
    primary: ink,
    onPrimary: paper,
    secondary: ink,
    onSecondary: paper,
    error: ink,
    onError: paper,
    surface: paper,
    onSurface: ink,
    onSurfaceVariant: ink,
    outline: ink,
    shadow: Colors.transparent,
  );
  final body = p.body(ink);
  final big = p.big(ink);
  final text = TextTheme(
    displayLarge: big,
    displayMedium: big,
    displaySmall: big,
    headlineLarge: big,
    headlineMedium: big,
    headlineSmall: big,
    titleLarge: big,
    titleMedium: p.title(ink),
    titleSmall: p.title(ink),
    bodyLarge: body,
    bodyMedium: body,
    bodySmall: body,
    labelLarge: p.title(ink),
    labelMedium: p.title(ink),
    labelSmall: p.title(ink),
  );

  ButtonStyle button({required bool double}) => ButtonStyle(
        backgroundColor: const WidgetStatePropertyAll(Colors.transparent),
        foregroundColor: WidgetStateProperty.resolveWith((s) => pixelButtonInverted(s) ? paper : ink),
        iconColor: WidgetStateProperty.resolveWith((s) => pixelButtonInverted(s) ? paper : ink),
        overlayColor: const WidgetStatePropertyAll(Colors.transparent),
        elevation: const WidgetStatePropertyAll(0),
        shadowColor: const WidgetStatePropertyAll(Colors.transparent),
        surfaceTintColor: const WidgetStatePropertyAll(Colors.transparent),
        shape: const WidgetStatePropertyAll(RoundedRectangleBorder()),
        side: const WidgetStatePropertyAll(BorderSide.none),
        minimumSize: const WidgetStatePropertyAll(Size(48, 48)),
        padding: WidgetStatePropertyAll(EdgeInsets.symmetric(horizontal: p(5))),
        iconSize: WidgetStatePropertyAll(p(7)),
        textStyle: WidgetStatePropertyAll(p.title(ink)),
        splashFactory: NoSplash.splashFactory,
        animationDuration: Duration.zero,
        visualDensity: VisualDensity.standard,
        tapTargetSize: MaterialTapTargetSize.padded,
        backgroundBuilder: (context, states, child) =>
            PixelPaint(art: ButtonArt(ink: ink, paper: paper, states: states, double: double), child: child),
      );

  return ThemeData(
    useMaterial3: true,
    brightness: brightness,
    colorScheme: scheme,
    textTheme: text,
    primaryTextTheme: text,
    fontFamily: Fonts.body,
    fontFamilyFallback: Fonts.bodyFallback,
    scaffoldBackgroundColor: Colors.transparent,
    canvasColor: paper,
    extensions: [t],
    splashFactory: NoSplash.splashFactory,
    highlightColor: Colors.transparent,
    hoverColor: Colors.transparent,
    focusColor: Colors.transparent,
    splashColor: Colors.transparent,
    iconTheme: IconThemeData(color: ink, size: p(7)),
    filledButtonTheme: FilledButtonThemeData(style: button(double: true)),
    outlinedButtonTheme: OutlinedButtonThemeData(style: button(double: false)),
    textButtonTheme: TextButtonThemeData(style: button(double: false)),
    iconButtonTheme: IconButtonThemeData(style: button(double: false).copyWith(padding: WidgetStatePropertyAll(EdgeInsets.all(p(4))))),
    listTileTheme: ListTileThemeData(
      dense: true,
      textColor: ink,
      minVerticalPadding: p(2),
      minTileHeight: 0,
      horizontalTitleGap: p(4),
      titleTextStyle: p.title(ink),
      subtitleTextStyle: p.body(ink, line: 11),
      leadingAndTrailingTextStyle: p.body(ink),
    ),
    tooltipTheme: TooltipThemeData(
      decoration: BoxDecoration(color: ink),
      textStyle: p.body(paper),
      padding: EdgeInsets.symmetric(horizontal: p(3), vertical: p(2)),
      waitDuration: const Duration(milliseconds: 400),
    ),
    textSelectionTheme: TextSelectionThemeData(cursorColor: ink, selectionColor: ink.withValues(alpha: 0.3)),
  );
}
