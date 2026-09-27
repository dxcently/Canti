import 'dart:async';

import 'package:flutter/widgets.dart';

import 'backend.dart';
import 'theme/sprite.dart';

/// The animated Canti in the status screen's header: the floating badge's character, docked here while the app is
/// in front (the service hides the floating one then; the two never show at once).
///
/// Held state: the service's own badge state (`VoxStatus.badge`, and `badge{event: state}` events as it changes),
/// else worked out from the status (older service, desktop): off without the service or with the device away,
/// paused, error, cursor, idle. One-shots: each executed action (`exec{action, ok}` events), mapped like the
/// service's `BadgeStates.forDecision` (Badge.kt): swipe up/down, back, forward, home; a failure plays error, and a
/// sound that did nothing (`none`) plays the `ignored` shrug, at most once per 2.5 s ([OneShots]).
class CantiHead extends StatefulWidget {
  const CantiHead({super.key, required this.status, required this.events, this.animate});

  final VoxStatus? status;
  final Stream<VoxEvent> events;
  final bool? animate;

  /// The held state for [s].
  static String heldFor(VoxStatus? s) {
    if (s == null || !s.service) return 'off';
    final b = s.badge;
    if (b != null && b.isNotEmpty) return b;
    if (s.hasDevice && !s.deviceReady) return 'off';
    if (s.paused || (s.deviceReady ? s.deviceArmed != true : !s.armed)) return 'paused';
    if (s.deviceError != null) return 'error';
    if ((s.deviceReady ? s.deviceMode ?? s.mode : s.mode) == 'cursor') return 'cursor';
    return 'idle';
  }

  /// The one-shot for an executed action, or null (Badge.kt `BadgeStates.forDecision`: `none` is the ignored shrug).
  /// Not rate-limited; [OneShots] is.
  static String? oneShotFor(String action, bool ok) {
    final a = action.replaceAll(' ', '_');
    if (a == 'none') return 'ignored';
    if (!ok) return 'error';
    return switch (a) {
      'swipe_up' => 'scroll_up',
      'swipe_down' => 'scroll_down',
      'back' || 'forward' || 'home' => a,
      _ => null,
    };
  }

  @override
  State<CantiHead> createState() => _CantiHeadState();
}

/// Executed actions -> the header's one-shots, like the service (VoxService.perform): a `none` shrugs (`ignored`) at
/// most once per [gapMs]; one less than [gapMs] after the last shrug that played is dropped, not queued.
class OneShots {
  OneShots({this.gapMs = ignoredGapMs});

  /// Badge.kt `IgnoredGate.GAP_MS`.
  static const ignoredGapMs = 2500;

  final int gapMs;
  int? _lastIgnored;

  /// The one-shot to play for `exec{action, ok}` at [now] (any monotonic ms clock), or null.
  String? next(String action, bool ok, int now) {
    final s = CantiHead.oneShotFor(action, ok);
    if (s != 'ignored') return s;
    final last = _lastIgnored;
    if (last != null && now - last < gapMs) return null;
    _lastIgnored = now;
    return s;
  }
}

class _CantiHeadState extends State<CantiHead> {
  late final _sprite = SpriteController(CantiHead.heldFor(widget.status));
  final _shots = OneShots();
  final _clock = Stopwatch()..start();
  StreamSubscription<VoxEvent>? _sub;

  @override
  void initState() {
    super.initState();
    _sprite.addListener(_relabel);
    _listen();
  }

  @override
  void didUpdateWidget(CantiHead old) {
    super.didUpdateWidget(old);
    if (old.events != widget.events) {
      _sub?.cancel();
      _listen();
    }
    if (!identical(old.status, widget.status)) _sprite.held = CantiHead.heldFor(widget.status);
  }

  void _listen() => _sub = widget.events.listen(_onEvent, onError: (Object _) {});

  void _onEvent(VoxEvent e) {
    switch (e.name) {
      case 'exec':
        final action = '${e.fields['action'] ?? 'none'}';
        final shot = _shots.next(action, e.fields['ok'] != false, _clock.elapsedMilliseconds);
        if (shot != null) _sprite.playOnce(shot);
      case 'badge' when e.fields['event'] == 'state' && e.fields['state'] is String:
        if (widget.status?.service ?? false) _sprite.held = e.fields['state']! as String;
    }
  }

  void _relabel() => setState(() {});

  @override
  void dispose() {
    _sub?.cancel();
    _sprite.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => CantiSprite(
        controller: _sprite,
        animate: widget.animate,
        semanticLabel: 'Canti: ${_sprite.held.replaceAll('_', '-')}',
      );
}
