import 'package:flutter/material.dart';

import 'canti_theme.dart';
import 'pixel.dart';

/// The one action a dock button carries: its text, what it does, and whether it is enabled.
class DockAction {
  const DockAction(this.label, this.onTap, {this.enabled = true});

  final String label;
  final VoidCallback onTap;
  final bool enabled;
}

/// The shared bottom action dock (SHARED CONTRACT §9): a dotted rule, an optional caption line, two small
/// single-framed buttons (either may be null: an empty slot keeps the layout) and one full-width double-framed main
/// button. It carries its own padding and paper fill, so it looks and sits the same on every screen: make it the last
/// child of the screen's Column (or a Scaffold's bottomNavigationBar), outside any scroll view. The caption grows
/// upwards, so the buttons never move. E9 reuses it unchanged (changes only by adding optional parameters).
class ActionDock extends StatelessWidget {
  const ActionDock({super.key, this.caption, this.left, this.right, required this.main});

  final String? caption;

  /// The small button on the left (or null: an empty slot keeps the layout).
  final DockAction? left;

  /// The small button on the right (or null: an empty slot keeps the layout).
  final DockAction? right;

  /// The full-width main button.
  final DockAction main;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    return ColoredBox(
      color: t.paper,
      child: Padding(
        padding: EdgeInsets.fromLTRB(p(5), 0, p(5), p(5)),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            SizedBox(height: p(3), child: PixelPaint(art: _RuleArt(t.ink))),
            SizedBox(height: p(3)),
            if (caption != null) ...[
              PixelSnap(child: Text(caption!, key: const Key('dock_caption'), style: p.body(t.ink, line: 11))),
              SizedBox(height: p(3)),
            ],
            Row(
              children: [
                Expanded(child: _SmallButton(key: const Key('dock_left'), action: left)),
                SizedBox(width: p(3)),
                Expanded(child: _SmallButton(key: const Key('dock_right'), action: right)),
              ],
            ),
            SizedBox(height: p(3)),
            FilledButton(
              key: const Key('dock_main'),
              onPressed: main.enabled ? main.onTap : null,
              child: Text(main.label, maxLines: 1, overflow: TextOverflow.ellipsis),
            ),
          ],
        ),
      ),
    );
  }
}

/// A small single-framed button; with no action it is an empty (disabled-looking) slot that keeps the layout.
class _SmallButton extends StatelessWidget {
  const _SmallButton({super.key, required this.action});

  final DockAction? action;

  @override
  Widget build(BuildContext context) {
    final a = action;
    return OutlinedButton(
      onPressed: a != null && a.enabled ? a.onTap : null,
      child: Text(a?.label ?? '', maxLines: 1, overflow: TextOverflow.ellipsis),
    );
  }
}

/// The dock's top edge: a dotted rule with a tick every 8 px.
class _RuleArt extends PixelArt {
  const _RuleArt(this.ink);

  final Color ink;

  @override
  void paint(PixelCanvas c) {
    for (var x = 0; x < c.w; x += 2) {
      c.rect(x, 1, 1, 1, ink);
    }
    for (var x = 4; x < c.w; x += 8) {
      c.rect(x, 0, 1, 3, ink);
    }
  }

  @override
  bool shouldRepaint(_RuleArt old) => old.ink != ink;
}
