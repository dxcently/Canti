import 'dart:async';

import 'package:flutter/material.dart';

import 'backend.dart';

/// The status screen: the service and device state, pause/resume, the live event log, and a way to the native
/// settings screen. Every control has a text label, so Android accessibility (and VOX's own Targets.kt) can name it.
///
/// With a VOX device connected, the device is the source of truth for `armed`: the main button pauses or arms the
/// **device**, and a mode toggle and "Sleep device" appear. Without one (phone-only or debug sources), the main
/// button is the app-side pause.
class StatusScreen extends StatefulWidget {
  const StatusScreen({super.key, required this.backend, this.maxEvents = 50});

  final VoxBackend backend;
  final int maxEvents;

  @override
  State<StatusScreen> createState() => _StatusScreenState();
}

class _StatusScreenState extends State<StatusScreen> {
  /// Events after which the status is fetched again.
  static const _statusEvents = {'arm', 'pause', 'mode', 'service', 'ble', 'reset', 'app', 'source', 'device_cmd'};

  VoxStatus? _status;
  String? _error;
  bool _busy = false;
  final _log = <VoxEvent>[];
  StreamSubscription<VoxEvent>? _sub;

  @override
  void initState() {
    super.initState();
    _refresh();
    _sub = widget.backend.events().listen(_onEvent, onError: (Object e) => _setError('events: $e'));
  }

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }

  void _setError(String e) {
    if (mounted) setState(() => _error = e);
  }

  Future<void> _refresh() async {
    try {
      final s = await widget.backend.status();
      if (mounted) setState(() { _status = s; _error = null; });
    } catch (e) {
      _setError('status: $e');
    }
  }

  void _onEvent(VoxEvent e) {
    if (!mounted) return;
    setState(() {
      _log.insert(0, e);
      if (_log.length > widget.maxEvents) _log.removeLast();
    });
    if (_statusEvents.contains(e.name)) _refresh();
  }

  /// Whether sounds act, as far as the main button is concerned.
  static bool _on(VoxStatus s) => s.deviceReady ? s.deviceArmed == true && !s.paused : !s.paused;

  Future<void> _busyWhile(String what, Future<void> Function() f) async {
    if (_busy) return;
    setState(() { _busy = true; _error = null; });
    try {
      await f();
    } catch (e) {
      _setError('$what: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Pause or resume. With a device connected this commands the device (and a resume also lifts an app-side pause);
  /// otherwise it is the app-side pause.
  Future<void> _togglePause() async {
    final s = _status;
    if (s == null) return;
    await _busyWhile('pause', () async {
      if (!s.deviceReady) {
        final n = await widget.backend.setPaused(!s.paused);
        if (mounted) setState(() => _status = n);
        return;
      }
      if (_on(s)) {
        await _device(armed: false);
      } else {
        if (s.paused) await widget.backend.setPaused(false);
        if (s.deviceArmed != true) await _device(armed: true);
        await _refresh();
      }
    });
  }

  /// One device command; a failure the status does not already show (a refusal) goes to the error line.
  Future<void> _device({bool? armed, String? mode, bool sleep = false}) async {
    final r = await widget.backend.deviceCommand(armed: armed, mode: mode, sleep: sleep);
    await _refresh();
    if (!r.ok && _status?.deviceError == null) _setError('${r.cmd ?? 'command'} failed: ${r.error}');
  }

  @override
  Widget build(BuildContext context) {
    final s = _status;
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(
        title: const Text('VOX'),
        actions: [
          IconButton(
            key: const Key('refresh'),
            tooltip: 'Refresh status',
            icon: const Icon(Icons.refresh),
            onPressed: _refresh,
          ),
        ],
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (_error != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Text(_error!, style: TextStyle(color: theme.colorScheme.error)),
                ),
              s == null ? const _Loading() : _StatusCard(status: s),
              const SizedBox(height: 12),
              Wrap(
                spacing: 12,
                runSpacing: 8,
                children: [
                  FilledButton.icon(
                    key: const Key('pause'),
                    icon: Icon(s != null && !_on(s) ? Icons.play_arrow : Icons.pause),
                    label: Text(s != null && !_on(s) ? 'Resume VOX' : 'Pause VOX'),
                    onPressed: s != null && s.service && !_busy ? _togglePause : null,
                  ),
                  if (s != null && s.service && s.deviceState == 'pairing needed')
                    FilledButton.tonalIcon(
                      key: const Key('connect'),
                      icon: const Icon(Icons.bluetooth_searching),
                      label: const Text('Connect'),
                      onPressed: _busy
                          ? null
                          : () => _busyWhile('connect', () async {
                                final n = await widget.backend.connectDevice();
                                if (mounted) setState(() => _status = n);
                              }),
                    ),
                  if (widget.backend.hasLegacySettings)
                    OutlinedButton.icon(
                      key: const Key('legacy'),
                      icon: const Icon(Icons.settings),
                      label: const Text('Legacy settings'),
                      onPressed: widget.backend.openLegacySettings,
                    ),
                ],
              ),
              if (s != null && s.service && s.deviceReady) ...[
                const SizedBox(height: 8),
                Wrap(
                  spacing: 12,
                  runSpacing: 8,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    SegmentedButton<String>(
                      key: const Key('mode'),
                      segments: const [
                        ButtonSegment(value: 'gesture', label: Text('Gesture'), icon: Icon(Icons.swipe)),
                        ButtonSegment(value: 'cursor', label: Text('Cursor'), icon: Icon(Icons.mouse)),
                      ],
                      selected: {s.deviceMode ?? s.mode},
                      showSelectedIcon: false,
                      onSelectionChanged: _busy ? null : (v) => _busyWhile('mode', () => _device(mode: v.first)),
                    ),
                    OutlinedButton.icon(
                      key: const Key('sleep'),
                      icon: const Icon(Icons.bedtime),
                      label: const Text('Sleep device'),
                      onPressed: _busy ? null : () => _busyWhile('sleep', () => _device(sleep: true)),
                    ),
                  ],
                ),
              ],
              const SizedBox(height: 16),
              Semantics(header: true, child: Text('Live events', style: theme.textTheme.titleMedium)),
              const SizedBox(height: 4),
              Expanded(
                child: _log.isEmpty
                    ? const Text('No events yet.')
                    : ListView.builder(
                        key: const Key('events'),
                        itemCount: _log.length,
                        itemBuilder: (context, i) => _EventTile(event: _log[i]),
                      ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Loading extends StatelessWidget {
  const _Loading();

  @override
  Widget build(BuildContext context) =>
      const Padding(padding: EdgeInsets.all(16), child: Text('Connecting to the VOX service...'));
}

class _StatusCard extends StatelessWidget {
  const _StatusCard({required this.status});

  final VoxStatus status;

  String get _headline {
    final s = status;
    if (!s.service) return 'Service off';
    if (s.hasDevice) {
      switch (s.deviceState) {
        case 'pairing needed':
          return 'Pairing needed';
        case 'asleep':
          return 'Device asleep';
        case 'bluetooth off':
          return 'Bluetooth is off';
        case 'connecting':
          return 'Connecting to the device';
        case 'listening':
        case 'awake – paused':
          break;
        default:
          return 'Device not connected';
      }
    }
    if (s.paused) return 'Paused';
    if (s.deviceReady ? s.deviceArmed != true : !s.armed) return s.deviceReady ? 'Device paused' : 'Disarmed by the device';
    return 'Listening for sounds';
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final s = status;
    final rows = <(String, String)>[
      ('Service', s.service ? 'running' : 'off (turn on VOX in Accessibility settings)'),
      if (s.service) ...[
        ('Device', s.deviceState ?? (s.armed ? 'armed' : 'disarmed')),
        ('Mode', s.deviceReady ? (s.deviceMode ?? s.mode) : s.mode),
        ('App', s.app ?? 'unknown'),
        ('Bluetooth', [s.bleState ?? 'no link', if (s.bleDevice != null) s.bleDevice!].join(', ')),
        ('Decider', s.decider ?? '?'),
      ],
    ];
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Semantics(
              liveRegion: true,
              child: Text(_headline, key: const Key('headline'), style: theme.textTheme.headlineSmall),
            ),
            const SizedBox(height: 8),
            for (final (k, v) in rows)
              MergeSemantics(
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 2),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      SizedBox(width: 96, child: Text(k, style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600))),
                      Expanded(child: Text(v)),
                    ],
                  ),
                ),
              ),
            for (final (key, text) in [('ble_hint', s.bleHint), ('device_error', s.deviceError)])
              if (s.service && text != null) ...[
                const SizedBox(height: 8),
                Semantics(
                  liveRegion: true,
                  child: Text(text, key: Key(key), style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.error)),
                ),
              ],
            if (s.service && s.deviceWaiting != null) ...[
              const SizedBox(height: 8),
              Text('Waiting for the device: ${s.deviceWaiting}', key: const Key('device_waiting')),
            ],
          ],
        ),
      ),
    );
  }
}

class _EventTile extends StatelessWidget {
  const _EventTile({required this.event});

  final VoxEvent event;

  @override
  Widget build(BuildContext context) => ListTile(
        dense: true,
        contentPadding: EdgeInsets.zero,
        title: Text(event.name),
        subtitle: Text(event.summary, maxLines: 2, overflow: TextOverflow.ellipsis),
        trailing: Text('${(event.t / 1000).toStringAsFixed(1)} s'),
      );
}
