import 'package:flutter/widgets.dart';

/// Plays once when it is created (key it by what changed): off, on, off, on, in whole steps like a pixel screen
/// switching on (no fades: the kit has two tones). A plain [AnimationController] on the ticker, so tests settle and
/// nothing runs once it is done; only this subtree rebuilds while it plays.
class Flicker extends StatefulWidget {
  const Flicker({super.key, required this.child, this.duration = const Duration(milliseconds: 240)});

  final Widget child;
  final Duration duration;

  @override
  State<Flicker> createState() => _FlickerState();
}

class _FlickerState extends State<Flicker> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: widget.duration)..forward();

  static bool _on(double v) => v >= 1 || (v >= 0.15 && v < 0.4) || v >= 0.6;

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: _c,
        builder: (context, child) => Visibility.maintain(visible: _on(_c.value), child: child!),
        child: widget.child,
      );
}
