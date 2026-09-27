import 'dart:math' as math;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';

import 'canti_theme.dart';
import 'glyphs.dart';
import 'pixel.dart';

// The 1-bit RPG kit, reduced to what VOX needs: windows with a double-line frame, notched corners, a title tab and
// an optional close box; inverted panels with stat rows (icon, LABEL, dotted leader, value); a glyph grid with a
// corner-bracket cursor and a name bar; a pager, a pixel scrollbar, pip meters, a signal lamp, square framed
// buttons that invert when pressed, and the diagonal hatch for empty areas. All sizes below are art pixels (Px).

/// A button's face inverts (paper on ink) while it is pressed or selected.
bool pixelButtonInverted(Set<WidgetState> s) =>
    !s.contains(WidgetState.disabled) && (s.contains(WidgetState.pressed) || s.contains(WidgetState.selected));

/// A square button: [double] frame for the main action, single otherwise, [frameless] for bare arrow buttons.
/// Pressed or selected: inverted fill. Disabled: a dotted frame. Hovered or focused: the bracket cursor around it.
class ButtonArt extends PixelArt {
  const ButtonArt({required this.ink, required this.paper, required this.states, this.double = false, this.frameless = false});

  final Color ink;
  final Color paper;
  final Set<WidgetState> states;
  final bool double;
  final bool frameless;

  static const _margin = 2;

  @override
  void paint(PixelCanvas c) {
    const m = _margin;
    final w = c.w - 2 * m, h = c.h - 2 * m;
    final disabled = states.contains(WidgetState.disabled);
    final inverted = pixelButtonInverted(states);
    if (!frameless || inverted) c.block(m, m, w, h, inverted ? ink : paper);
    if (!frameless) {
      if (disabled) {
        c.frame(m, m, w, h, ink, dotted: true);
      } else {
        c.frame(m, m, w, h, ink, notch: true);
        if (double) c.frame(m + 2, m + 2, w - 4, h - 4, inverted ? paper : ink);
      }
    }
    if (!disabled && (states.contains(WidgetState.focused) || states.contains(WidgetState.hovered))) {
      c.brackets(0, 0, c.w, c.h, ink, arm: 4, t: 1);
    }
  }

  @override
  bool shouldRepaint(ButtonArt old) =>
      old.ink != ink || old.paper != paper || old.double != double || old.frameless != frameless ||
      !setEquals(old.states, states);
}

/// A window: paper fill, a double-line frame with notched corners, a title tab on the top edge and, when [onClose]
/// is set, a close box (a 48 dp target in the top-right corner).
class PixelWindow extends StatelessWidget {
  const PixelWindow({super.key, required this.title, required this.child, this.onClose, this.closeLabel = 'Close'});

  /// Shown in capitals in the tab.
  final String title;
  final Widget child;
  final VoidCallback? onClose;
  final String closeLabel;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    final label = title.toUpperCase();
    final tabH = 8 * p.text + 4;
    return Stack(
      children: [
        Positioned.fill(
          child: PixelPaint(art: _WindowArt(t.ink, t.paper, label.length * 8 * p.text + 6, tabH, onClose != null)),
        ),
        Padding(padding: EdgeInsets.fromLTRB(p(6), p(tabH + 3), p(6), p(6)), child: child),
        Positioned(
          left: p(8),
          top: p(2),
          child: Semantics(header: true, child: PixelSnap(child: Text(label, style: p.title(t.ink)))),
        ),
        if (onClose != null)
          Positioned(
            right: 0,
            top: 0,
            width: 48,
            height: 48,
            child: Tooltip(
              message: closeLabel,
              excludeFromSemantics: true,
              child: Semantics(
                button: true,
                label: closeLabel,
                child: GestureDetector(behavior: HitTestBehavior.opaque, onTap: onClose),
              ),
            ),
          ),
      ],
    );
  }
}

class _WindowArt extends PixelArt {
  const _WindowArt(this.ink, this.paper, this.tab, this.tabH, this.close);

  final Color ink;
  final Color paper;
  final int tab;
  final int tabH;
  final bool close;

  @override
  void paint(PixelCanvas c) {
    final w = c.w, h = c.h, y = tabH ~/ 2 - 1;
    c.block(0, y, w, h - y, paper);
    c.frame(0, y, w, h - y, ink, notch: true);
    c.frame(2, y + 2, w - 4, h - y - 4, ink);
    // the kit's corner marks
    c.rect(4, h - 5, 1, 1, ink);
    c.rect(w - 5, h - 5, 1, 1, ink);
    if (!close) c.rect(w - 5, y + 4, 1, 1, ink);
    // title tab
    c.block(5, 0, tab, tabH, paper);
    c.frame(5, 0, tab, tabH, ink, notch: true);
    if (close) {
      c.block(w - 12, 1, 9, 9, ink);
      c.glyph(Marks.cross, w - 10, 3, paper);
    }
  }

  @override
  bool shouldRepaint(_WindowArt old) =>
      old.ink != ink || old.paper != paper || old.tab != tab || old.tabH != tabH || old.close != close;
}

/// An inverted panel (ink fill, a paper line inside): its text and icons are paper.
class InvertedPanel extends StatelessWidget {
  const InvertedPanel({super.key, required this.child, this.padding});

  final Widget child;
  final EdgeInsets? padding;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    return PixelPaint(
      art: _PanelArt(t.ink, t.paper),
      child: Padding(
        padding: padding ?? EdgeInsets.all(p(4)),
        child: DefaultTextStyle.merge(
          style: TextStyle(color: t.paper),
          child: IconTheme.merge(data: IconThemeData(color: t.paper), child: child),
        ),
      ),
    );
  }
}

class _PanelArt extends PixelArt {
  const _PanelArt(this.ink, this.paper);

  final Color ink;
  final Color paper;

  @override
  void paint(PixelCanvas c) {
    c.block(0, 0, c.w, c.h, ink);
    c.frame(1, 1, c.w - 2, c.h - 2, paper, notch: true);
  }

  @override
  bool shouldRepaint(_PanelArt old) => old.ink != ink || old.paper != paper;
}

/// A filled or outlined box behind [child] (a tag, a pager count, a message).
class PixelBox extends StatelessWidget {
  const PixelBox({super.key, required this.child, this.inverted = false, this.padding});

  final Widget child;
  final bool inverted;
  final EdgeInsets? padding;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    final fg = inverted ? t.paper : t.ink;
    return PixelPaint(
      art: _BoxArt(inverted ? t.ink : t.paper, t.ink),
      child: Padding(
        padding: padding ?? EdgeInsets.symmetric(horizontal: p(3), vertical: p(2)),
        child: DefaultTextStyle.merge(style: TextStyle(color: fg), child: child),
      ),
    );
  }
}

class _BoxArt extends PixelArt {
  const _BoxArt(this.fill, this.line);

  final Color fill;
  final Color line;

  @override
  void paint(PixelCanvas c) {
    c.block(0, 0, c.w, c.h, fill);
    c.frame(0, 0, c.w, c.h, line, notch: true);
  }

  @override
  bool shouldRepaint(_BoxArt old) => old.fill != fill || old.line != line;
}

/// Row geometry shared by stat rows and name bars (art px from the row's top).
abstract final class _Row {
  static const height = 11;
  static const labelTop = 2;
  static const leaderY = 8;
}

/// One stat: a framed icon, a LABEL, a dotted leader and the value (right-aligned; long values wrap). Reads its
/// colour from the ambient text style (paper inside an [InvertedPanel]).
class StatRow extends StatelessWidget {
  const StatRow({super.key, required this.icon, required this.label, this.value, this.valueKey, this.trailing});

  final Glyph icon;
  final String label;
  final String? value;
  final Key? valueKey;

  /// Instead of a text value (a meter).
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final c = DefaultTextStyle.of(context).style.color ?? CantiTheme.of(context).ink;
    return MergeSemantics(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(width: p(11), height: p(11), child: PixelPaint(art: _IconBoxArt(icon, c))),
          SizedBox(width: p(4)),
          Padding(
            padding: EdgeInsets.only(top: p(_Row.labelTop)),
            child: PixelSnap(child: Text(label.toUpperCase(), style: p.title(c))),
          ),
          SizedBox(width: p(3)),
          Expanded(
            child: LeaderValue(
              color: c,
              child: trailing ?? Text(value ?? '', key: valueKey, style: p.body(c, line: 11), textAlign: TextAlign.right),
            ),
          ),
        ],
      ),
    );
  }
}

class _IconBoxArt extends PixelArt {
  const _IconBoxArt(this.g, this.c);

  final Glyph g;
  final Color c;

  @override
  void paint(PixelCanvas c0) {
    c0.frame(0, 0, 11, 11, c, notch: true);
    c0.glyph(g, 2, 2, c);
  }

  @override
  bool shouldRepaint(_IconBoxArt old) => old.g != g || old.c != c;
}

/// A dotted leader from the left edge up to [child], which sits right-aligned on the art grid.
class LeaderValue extends SingleChildRenderObjectWidget {
  const LeaderValue({super.key, required this.color, super.child});

  final Color color;

  @override
  RenderLeader createRenderObject(BuildContext context) => RenderLeader(Px.of(context), color);

  @override
  void updateRenderObject(BuildContext context, RenderLeader renderObject) => renderObject
    ..px = Px.of(context)
    ..color = color;
}

class RenderLeader extends RenderShiftedBox {
  RenderLeader(this._px, this._color) : super(null);

  Px _px;
  set px(Px v) {
    if (v == _px) return;
    _px = v;
    markNeedsLayout();
  }

  Color _color;
  set color(Color v) {
    if (v == _color) return;
    _color = v;
    markNeedsPaint();
  }

  int _dotsTo = 0;

  @override
  void performLayout() {
    final u = _px.px;
    final minH = _Row.height * u;
    final c = child;
    if (c == null) {
      size = constraints.constrain(Size(constraints.maxWidth, minH));
      return;
    }
    c.layout(BoxConstraints(maxWidth: math.max(0.0, constraints.maxWidth - 4 * u)), parentUsesSize: true);
    size = constraints.constrain(Size(constraints.maxWidth, math.max(minH, c.size.height)));
    final x = ((size.width - c.size.width) / u + 1e-6).floor();
    (c.parentData! as BoxParentData).offset = Offset(x * u, 0);
    _dotsTo = x - 2;
  }

  @override
  void paint(PaintingContext context, Offset offset) {
    final u = _px.px;
    final o = offset + pixelSnap(this, _px.dpr);
    final pts = <int>[];
    for (var x = 1; x < _dotsTo; x += 2) {
      pts..add(x)..add(_Row.leaderY);
    }
    PixelCanvas(context.canvas, o, u, 0, 0).points(pts, _color);
    final c = child;
    if (c != null) context.paintChild(c, o + (c.parentData! as BoxParentData).offset);
  }
}

/// A name bar under a grid: "RISE ........ swipe up" in paper on ink.
class NameBar extends StatelessWidget {
  const NameBar({super.key, required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    return PixelPaint(
      art: _FillArt(t.ink),
      child: Padding(
        padding: EdgeInsets.symmetric(horizontal: p(3), vertical: p(1)),
        child: MergeSemantics(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(
                padding: EdgeInsets.only(top: p(_Row.labelTop)),
                child: PixelSnap(child: Text(label.toUpperCase(), style: p.title(t.paper))),
              ),
              SizedBox(width: p(3)),
              Expanded(
                child: LeaderValue(
                  color: t.paper,
                  child: Text(value, style: p.body(t.paper, line: 11), textAlign: TextAlign.right),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _FillArt extends PixelArt {
  const _FillArt(this.c);

  final Color c;

  @override
  void paint(PixelCanvas c0) => c0.block(0, 0, c0.w, c0.h, c);

  @override
  bool shouldRepaint(_FillArt old) => old.c != c;
}

/// Pips, like the kit's HEALTH and MANA rows: [value] filled out of [max].
class PipMeter extends StatelessWidget {
  const PipMeter({super.key, required this.value, required this.max, required this.label, this.color});

  final int value;
  final int max;

  /// What it measures, for accessibility ("link": "link 3 of 4").
  final String label;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final c = color ?? DefaultTextStyle.of(context).style.color ?? CantiTheme.of(context).ink;
    return Semantics(
      label: '$label $value of $max',
      child: SizedBox(
        width: p(max * 9 - 2),
        height: p(11),
        child: PixelPaint(art: _PipArt(value, max, c)),
      ),
    );
  }
}

class _PipArt extends PixelArt {
  const _PipArt(this.value, this.max, this.c);

  final int value;
  final int max;
  final Color c;

  @override
  void paint(PixelCanvas c0) {
    for (var i = 0; i < max; i++) {
      c0.glyph(i < value ? Icons7.pipOn : Icons7.pipOff, i * 9, 2, c);
    }
  }

  @override
  bool shouldRepaint(_PipArt old) => old.value != value || old.max != max || old.c != c;
}

/// What the status lamp shows. Orange only while sounds act, yellow while something is pending, red when stopped
/// by a fault; otherwise it is dark (an empty frame).
enum Signal { listening, waiting, stop, idle }

class SignalLamp extends StatelessWidget {
  const SignalLamp(this.signal, {super.key});

  final Signal signal;

  static Color? colorOf(Signal s) => switch (s) {
        Signal.listening => CantiColors.signalOrange,
        Signal.waiting => CantiColors.signalYellow,
        Signal.stop => CantiColors.signalRed,
        Signal.idle => null,
      };

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    return SizedBox(width: p(11), height: p(11), child: PixelPaint(art: _LampArt(t.ink, t.paper, colorOf(signal))));
  }
}

class _LampArt extends PixelArt {
  const _LampArt(this.ink, this.paper, this.lit);

  final Color ink;
  final Color paper;
  final Color? lit;

  @override
  void paint(PixelCanvas c) {
    c.block(0, 0, 11, 11, ink);
    c.block(1, 1, 9, 9, lit ?? paper);
    if (lit != null) {
      c.rect(3, 3, 2, 1, paper); // a glint
      c.rect(3, 4, 1, 1, paper);
    } else {
      c.rect(4, 4, 3, 3, ink);
    }
  }

  @override
  bool shouldRepaint(_LampArt old) => old.ink != ink || old.paper != paper || old.lit != lit;
}

/// The diagonal hatch over the whole area, with [child] (if any) centred in a solid box on top, so text never sits
/// on the hatch.
class HatchBox extends StatelessWidget {
  const HatchBox({super.key, this.child});

  final Widget? child;

  @override
  Widget build(BuildContext context) {
    final t = CantiTheme.of(context);
    return PixelPaint(
      art: _HatchArt(t.ink),
      child: child == null ? const SizedBox.expand() : Center(child: PixelBox(child: child!)),
    );
  }
}

class _HatchArt extends PixelArt {
  const _HatchArt(this.c);

  final Color c;

  @override
  void paint(PixelCanvas c0) => c0.hatch(0, 0, c0.w, c0.h, c);

  @override
  bool shouldRepaint(_HatchArt old) => old.c != c;
}

/// A bare or framed icon button with a glyph (tooltip = its label).
class PixelIconButton extends StatelessWidget {
  const PixelIconButton({super.key, required this.glyph, required this.tooltip, required this.onPressed, this.framed = true});

  final Glyph glyph;
  final String tooltip;
  final VoidCallback? onPressed;
  final bool framed;

  @override
  Widget build(BuildContext context) {
    final t = CantiTheme.of(context);
    return IconButton(
      tooltip: tooltip,
      onPressed: onPressed,
      icon: PixelGlyph(glyph),
      style: framed
          ? null
          : ButtonStyle(
              backgroundBuilder: (context, states, child) => PixelPaint(
                  art: ButtonArt(ink: t.ink, paper: t.paper, states: states, frameless: true), child: child),
            ),
    );
  }
}

/// Two or more square buttons, one selected (inverted), for a choice like Gesture / Cursor.
class PixelToggle<T> extends StatelessWidget {
  const PixelToggle({super.key, required this.options, required this.selected, required this.onChanged});

  final List<(T, String, Glyph)> options;
  final T selected;
  final ValueChanged<T>? onChanged;

  @override
  Widget build(BuildContext context) {
    final t = CantiTheme.of(context);
    final p = Px.of(context);
    final selectedStyle = ButtonStyle(
      foregroundColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.disabled) ? t.ink : t.paper),
      iconColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.disabled) ? t.ink : t.paper),
      backgroundBuilder: (context, states, child) =>
          PixelPaint(art: ButtonArt(ink: t.ink, paper: t.paper, states: {...states, WidgetState.selected}), child: child),
    );
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        for (final (i, (value, label, glyph)) in options.indexed) ...[
          if (i > 0) SizedBox(width: p(1)),
          Semantics(
            selected: value == selected,
            inMutuallyExclusiveGroup: true,
            child: OutlinedButton.icon(
              style: value == selected ? selectedStyle : null,
              onPressed: onChanged == null ? null : () => onChanged!(value),
              icon: PixelGlyph(glyph),
              label: Text(label),
            ),
          ),
        ],
      ],
    );
  }
}

/// ◀ n/m ▶ with 48 dp arrow targets; wraps around.
class PixelPager extends StatelessWidget {
  const PixelPager({super.key, required this.index, required this.count, required this.onChanged});

  final int index;
  final int count;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        PixelIconButton(
            glyph: Marks.left, tooltip: 'Previous page', framed: false, onPressed: () => onChanged((index - 1) % count)),
        PixelBox(
          padding: EdgeInsets.fromLTRB(p(4), p(3), p(3), p(3)),
          child: PixelSnap(child: Text('${index + 1}/$count', style: p.title(CantiTheme.of(context).ink))),
        ),
        PixelIconButton(
            glyph: Marks.right, tooltip: 'Next page', framed: false, onPressed: () => onChanged((index + 1) % count)),
      ],
    );
  }
}

/// The kit's scrollbar for [controller]'s list: arrows at both ends, a track and a striped thumb. It only shows
/// where the list is; the list itself scrolls by touch.
class PixelScrollbar extends StatelessWidget {
  const PixelScrollbar({super.key, required this.controller});

  final ScrollController controller;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    return ExcludeSemantics(
      child: SizedBox(
        width: p(9),
        child: RepaintBoundary(child: PixelPaint(repaint: controller, art: _ScrollArt(controller, t.ink, t.paper))),
      ),
    );
  }
}

class _ScrollArt extends PixelArt {
  const _ScrollArt(this.controller, this.ink, this.paper);

  final ScrollController controller;
  final Color ink;
  final Color paper;

  @override
  void paint(PixelCanvas c) {
    final h = c.h;
    if (h < 20) return;
    c.glyph(Marks.up, 1, 0, ink);
    c.glyph(Marks.down, 1, h - 4, ink);
    final top = 6, len = h - 12;
    c.vline(4, top, len, ink);
    var th = len, ty = top;
    if (controller.hasClients && controller.position.hasContentDimensions) {
      final pos = controller.position;
      final total = pos.maxScrollExtent - pos.minScrollExtent + pos.viewportDimension;
      if (pos.maxScrollExtent > pos.minScrollExtent && total > 0) {
        th = math.max(9, (len * pos.viewportDimension / total).round());
        final f = ((pos.pixels - pos.minScrollExtent) / (pos.maxScrollExtent - pos.minScrollExtent)).clamp(0.0, 1.0);
        ty = top + ((len - th) * f).round();
      }
    }
    c.block(1, ty, 7, th, paper);
    c.frame(1, ty, 7, th, ink, notch: true);
    for (var y = ty + 2; y < ty + th - 2; y += 2) {
      c.hline(3, y, 3, ink);
    }
  }

  @override
  bool shouldRepaint(_ScrollArt old) => old.controller != controller || old.ink != ink || old.paper != paper;
}

/// One cell of a [GlyphGrid].
class GridItem {
  const GridItem(this.name, this.glyph, this.value);

  final String name;
  final Glyph glyph;
  final String value;
}

/// The kit's inventory grid: glyphs in cells on an inverted panel, the selected one in corner brackets. Each cell
/// is a tap target of at least 48 dp.
class GlyphGrid extends StatelessWidget {
  const GlyphGrid({super.key, required this.items, required this.selected, required this.onSelect, this.columns = 4});

  final List<GridItem> items;
  final int selected;
  final ValueChanged<int> onSelect;
  final int columns;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    final cell = math.max(20, (48 / p.px).ceil());
    final rows = (items.length / columns).ceil();
    final w = 2 + columns * (cell + 1) + 1;
    final h = 2 + rows * (cell + 1) + 1;
    return SizedBox(
      width: p(w),
      height: p(h),
      child: PixelPaint(
        art: _GridArt(t.ink, t.paper, [for (final i in items) i.glyph], columns, rows, cell, selected),
        child: Stack(
          children: [
            for (final (i, item) in items.indexed)
              Positioned(
                left: p(2 + (i % columns) * (cell + 1)),
                top: p(2 + (i ~/ columns) * (cell + 1)),
                width: p(cell),
                height: p(cell),
                child: Semantics(
                  button: true,
                  selected: i == selected,
                  label: '${item.name}: ${item.value}',
                  child: GestureDetector(behavior: HitTestBehavior.opaque, onTap: () => onSelect(i)),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _GridArt extends PixelArt {
  const _GridArt(this.ink, this.paper, this.glyphs, this.cols, this.rows, this.cell, this.selected);

  final Color ink;
  final Color paper;
  final List<Glyph> glyphs;
  final int cols;
  final int rows;
  final int cell;
  final int selected;

  @override
  void paint(PixelCanvas c) {
    final w = 2 + cols * (cell + 1) + 1;
    final h = 2 + rows * (cell + 1) + 1;
    c.block(0, 0, w, h, ink);
    for (var i = 0; i <= cols; i++) {
      c.vline(1 + i * (cell + 1), 1, h - 2, paper);
    }
    for (var j = 0; j <= rows; j++) {
      c.hline(1, 1 + j * (cell + 1), w - 2, paper);
    }
    for (var i = 0; i < cols * rows; i++) {
      final x = 2 + (i % cols) * (cell + 1), y = 2 + (i ~/ cols) * (cell + 1);
      if (i >= glyphs.length) {
        c.hatch(x, y, cell, cell, paper);
        continue;
      }
      final g = glyphs[i];
      c.glyph(g, x + (cell - g.width) ~/ 2, y + (cell - g.height) ~/ 2, paper);
      if (i == selected) c.brackets(x + 1, y + 1, cell - 2, cell - 2, paper, arm: 4, t: 2);
    }
  }

  @override
  bool shouldRepaint(_GridArt old) =>
      old.ink != ink || old.paper != paper || old.selected != selected || old.cell != cell || old.glyphs != glyphs;
}

/// A message with its signal lamp: an error (red), a wait (yellow), sounds acting (orange), or plain (dark). The text
/// stays ink on paper. (The status screen's note and the pairing screen's line, shared.)
class SignalNote extends StatelessWidget {
  const SignalNote({super.key, required this.signal, required this.text, this.textKey});

  final Signal signal;
  final String text;
  final Key? textKey;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SignalLamp(signal),
        SizedBox(width: p(4)),
        Expanded(
          child: Semantics(
            liveRegion: true,
            child: Text(text, key: textKey, style: p.body(CantiTheme.of(context).ink, line: 11)),
          ),
        ),
      ],
    );
  }
}

/// A screen's header: the back button, then the big title on a plate of the ground colour with the kit's 1-px
/// border (a [PixelBox]), so the title stays readable over the dither.
class ScreenHeader extends StatelessWidget {
  const ScreenHeader({super.key, required this.title, required this.onBack, this.backKey});

  final String title;
  final VoidCallback onBack;
  final Key? backKey;

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    return Row(
      children: [
        PixelIconButton(key: backKey, glyph: Marks.left, tooltip: 'Back', onPressed: onBack),
        SizedBox(width: p(4)),
        Flexible(
          child: PixelBox(
            padding: EdgeInsets.fromLTRB(p(4), p(3), p(3), p(3)),
            child: Semantics(
              header: true,
              child: PixelSnap(child: Text(title, style: p.big(t.ink))),
            ),
          ),
        ),
      ],
    );
  }
}
