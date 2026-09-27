import 'dart:async';

import 'package:flutter/material.dart';

import 'backend.dart';
import 'theme/canti_theme.dart';
import 'theme/glyphs.dart';
import 'theme/kit.dart';
import 'theme/pixel.dart';

/// Where the first-run pairing stands, from the status alone ([pairStep]).
enum PairStep {
  /// The accessibility service is off: nothing can connect.
  serviceOff,

  /// A microphone is the sound source: there is no device to pair.
  notPico,

  /// Bluetooth permissions are missing ([VoxStatus.bleMissing]).
  permissions,

  /// Bluetooth is off (or the phone has none).
  bluetoothOff,

  /// Ready to search.
  ready,
  scanning,

  /// The last search ended without finding a device.
  notFound,

  /// A device was found and is being connected (link up, services).
  connecting,

  /// Bonding: the device's pairing window must be open.
  pairing,

  /// The link dropped and is being retried.
  retrying,

  /// Pairing failed (the window was closed, or a stale bond): [VoxStatus.bleHint] says what to do.
  failed,
  connected,
}

/// The step for [s]; pure (tested in pair_screen_test.dart).
PairStep pairStep(VoxStatus s) {
  if (!s.service) return PairStep.serviceOff;
  if ((s.soundSource ?? 'pico') != 'pico') return PairStep.notPico;
  if (s.bleMissing.isNotEmpty) return PairStep.permissions;
  if (s.bleAdapter == 'off' || s.bleAdapter == 'none' || s.deviceState == 'bluetooth off') return PairStep.bluetoothOff;
  if (s.deviceReady) return PairStep.connected;
  switch (s.bleState) {
    case 'needs_pairing':
      return PairStep.failed;
    case 'bonding':
      return PairStep.pairing;
    case 'connecting' || 'discovering' || 'subscribing':
      return PairStep.connecting;
    case 'waiting':
      return PairStep.retrying;
    case 'scanning':
      return PairStep.scanning;
  }
  if (s.bleScan == 'scanning') return PairStep.scanning;
  if (s.bleScan == 'none found') return PairStep.notFound;
  if (s.deviceState == 'pairing needed') return PairStep.failed;
  return PairStep.ready;
}

/// A user-facing name for an Android Bluetooth permission.
String permissionLabel(String p) => switch (p.split('.').last) {
      'BLUETOOTH_SCAN' => 'Nearby devices (find)',
      'BLUETOOTH_CONNECT' => 'Nearby devices (connect)',
      'ACCESS_FINE_LOCATION' => 'Location (Bluetooth search)',
      final other => other,
    };

/// The device's name for the screen: its advertised name, else its address, else "your Canti device".
String deviceLabel(VoxStatus s) => s.bleTargetName ?? s.bleTarget ?? s.bleDevice ?? 'your Canti device';

/// The first-run pairing screen: find the Canti device, connect and pair, with each stage shown as it happens, what is
/// missing (permissions, Bluetooth) with a button to fix it, and the device's 5 s button hold explained. Opened from
/// the status screen's "Find my Canti device" button, and by the badge menu and the sound-source chooser when the Pico
/// is picked with no device remembered ([VoxBackend.routeRequests]).
///
/// With [autoStart], a search starts at once when nothing stands in the way (the user already asked for it).
class PairScreen extends StatefulWidget {
  const PairScreen({super.key, required this.backend, this.autoStart = true, this.poll = const Duration(seconds: 1)});

  final VoxBackend backend;
  final bool autoStart;

  /// Status refetch interval while a search or connection is in progress (events also refetch).
  final Duration poll;

  static const holdHint = 'Pairing window: hold the button on your Canti device for 5 s, until its light blinks fast. '
      'It stays open for 60 s.';

  @override
  State<PairScreen> createState() => _PairScreenState();
}

class _PairScreenState extends State<PairScreen> {
  static const _statusEvents = {'ble', 'service', 'source', 'sound_source', 'arm'};

  VoxStatus? _status;
  String? _error;
  bool _busy = false;
  bool _autoTried = false;
  StreamSubscription<VoxEvent>? _sub;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _sub = widget.backend.events().listen((e) {
      if (_statusEvents.contains(e.name)) _refresh();
    });
    _refresh();
  }

  @override
  void dispose() {
    _sub?.cancel();
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _refresh() async {
    try {
      final s = await widget.backend.status();
      if (!mounted) return;
      setState(() => _status = s);
      _schedule(s);
      if (widget.autoStart && !_autoTried && pairStep(s) == PairStep.ready) {
        _autoTried = true;
        await _find();
      }
    } catch (e) {
      if (mounted) setState(() => _error = 'status: $e');
    }
  }

  /// Poll while something is in progress; stop otherwise.
  void _schedule(VoxStatus s) {
    final live = const {PairStep.scanning, PairStep.connecting, PairStep.pairing, PairStep.retrying}.contains(pairStep(s));
    if (live && _timer == null) {
      _timer = Timer.periodic(widget.poll, (_) => _refresh());
    } else if (!live) {
      _timer?.cancel();
      _timer = null;
    }
  }

  Future<void> _run(String what, Future<VoxStatus?> Function() f) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final n = await f();
      if (mounted && n != null) {
        setState(() => _status = n);
        _schedule(n);
      }
    } catch (e) {
      if (mounted) setState(() => _error = '$what: ${_message(e)}');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  static String _message(Object e) {
    final s = '$e';
    final m = RegExp(r'PlatformException\([^,]*, (.*?), ').firstMatch(s);
    return m?.group(1) ?? s;
  }

  Future<void> _find() {
    _autoTried = true;
    return _run('search', widget.backend.connectDevice);
  }

  Future<void> _allow() => _run('permissions', widget.backend.requestBluetooth);

  Future<void> _settings() => _run('settings', () async {
        await widget.backend.openAppSettings();
        return null;
      });

  Future<void> _enable() => _run('bluetooth', () async {
        await widget.backend.enableBluetooth();
        return null;
      });

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    final s = _status;
    final gap = SizedBox(height: p(5));
    return Scaffold(
      body: SafeArea(
        child: SingleChildScrollView(
          padding: EdgeInsets.all(p(5)),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              ScreenHeader(
                backKey: const Key('pair_back'),
                title: 'Find my Canti device',
                onBack: () => Navigator.of(context).maybePop(),
              ),
              gap,
              if (_error != null) ...[
                PixelWindow(
                  title: 'Error',
                  onClose: () => setState(() => _error = null),
                  closeLabel: 'Dismiss error',
                  child: _Line(signal: Signal.stop, text: _error!, textKey: const Key('pair_error')),
                ),
                gap,
              ],
              if (s == null)
                PixelWindow(title: 'Pairing', child: Text('Reading the Bluetooth state...', style: p.body(t.ink)))
              else
                _PairWindow(
                  status: s,
                  busy: _busy,
                  onFind: _find,
                  onAllow: _allow,
                  onSettings: _settings,
                  onEnable: _enable,
                  onDone: () => Navigator.of(context).maybePop(),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _PairWindow extends StatelessWidget {
  const _PairWindow({
    required this.status,
    required this.busy,
    required this.onFind,
    required this.onAllow,
    required this.onSettings,
    required this.onEnable,
    required this.onDone,
  });

  final VoxStatus status;
  final bool busy;
  final VoidCallback onFind, onAllow, onSettings, onEnable, onDone;

  /// The stages as a checklist: done, now (with its word), or not yet.
  static List<(Glyph, String, String)> _stages(VoxStatus s, PairStep step) {
    // 0 search, 1 found, 2 connect, 3 pair, 4 connected; the index of the stage in progress (5 = all done).
    final at = switch (step) {
      PairStep.scanning => 0,
      PairStep.connecting => s.bleState == 'subscribing' ? 3 : 2,
      PairStep.pairing => 3,
      PairStep.retrying => 2,
      PairStep.connected => 5,
      _ => -1,
    };
    String state(int i, String now) => at < 0 ? '-' : i < at ? 'done' : i == at ? now : '-';
    final name = deviceLabel(s);
    return [
      (Icons7.target, 'Search', state(0, 'looking...')),
      (Icons7.device, 'Found', at > 1 ? name : '-'),
      (Icons7.link, 'Connect', state(2, step == PairStep.retrying ? 'retrying...' : 'connecting...')),
      (Icons7.hourglass, 'Pair', state(3, 'pairing...')),
      (Icons7.power, 'Ready', at == 5 ? 'connected' : '-'),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final s = status;
    final step = pairStep(s);
    final name = deviceLabel(s);
    final (Signal signal, String text) = switch (step) {
      PairStep.serviceOff => (Signal.stop, 'The Canti service is off. Turn on Canti in Accessibility settings first.'),
      PairStep.notPico => (
          Signal.idle,
          'Canti is listening through the ${s.soundSource == 'usb' ? 'USB mic' : 'phone mic'}. Choose Pico (Bluetooth) '
              'as the sound source to use your Canti device.'
        ),
      PairStep.permissions => (
          Signal.waiting,
          'Canti needs permission to find and connect to Bluetooth devices. Missing: '
              '${s.bleMissing.map(permissionLabel).toSet().join(', ')}.'
              '${s.bleBlocked ? ' Android will not ask again: allow it on Canti\'s page in the system settings.' : ''}'
        ),
      PairStep.bluetoothOff =>
        (Signal.stop, s.bleAdapter == 'none' ? 'This phone has no Bluetooth.' : 'Bluetooth is off. Turn it on to search.'),
      PairStep.ready => (Signal.idle, 'Wake your Canti device (press its button), then search.'),
      PairStep.scanning => (Signal.waiting, 'Looking for your Canti device...'),
      PairStep.notFound => (
          Signal.stop,
          'No Canti device found. Press its button to wake it, keep it near the phone, and search again.'
        ),
      PairStep.connecting => (Signal.waiting, 'Found $name. Connecting...'),
      PairStep.pairing => (Signal.waiting, 'Pairing with $name. If it does not finish, hold its button for 5 s now.'),
      PairStep.retrying => (Signal.waiting, 'The connection to $name dropped. Trying again...'),
      PairStep.failed => (Signal.stop, s.bleHint ?? 'Pairing with $name failed. Open its pairing window and try again.'),
      PairStep.connected => (Signal.listening, 'Connected to $name. Canti hears it now.'),
    };
    final Widget? action = switch (step) {
      PairStep.permissions => s.bleBlocked
          ? _button(const Key('open_settings'), Icons7.gear, 'Open app settings', onSettings)
          : _button(const Key('allow_bluetooth'), Icons7.link, 'Allow Bluetooth', onAllow),
      PairStep.bluetoothOff =>
        s.bleAdapter == 'none' ? null : _button(const Key('enable_bluetooth'), Icons7.power, 'Turn on Bluetooth', onEnable),
      PairStep.ready => _button(const Key('find_device'), Icons7.target, 'Find my Canti device', onFind, filled: true),
      PairStep.notFound => _button(const Key('find_device'), Icons7.refresh, 'Search again', onFind, filled: true),
      PairStep.failed => _button(const Key('find_device'), Icons7.refresh, 'Try again', onFind, filled: true),
      PairStep.connected => _button(const Key('pair_done'), Icons7.play, 'Done', onDone, filled: true),
      _ => null,
    };
    final showStages = !const {PairStep.serviceOff, PairStep.notPico}.contains(step);
    return PixelWindow(
      title: 'Pairing',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _Line(signal: signal, text: text, textKey: const Key('pair_text')),
          if (showStages) ...[
            SizedBox(height: p(4)),
            InvertedPanel(
              child: Column(
                children: [
                  for (final (i, (icon, label, value)) in _stages(s, step).indexed) ...[
                    if (i > 0) SizedBox(height: p(1)),
                    StatRow(icon: icon, label: label, value: value, valueKey: Key('stage_$i')),
                  ],
                ],
              ),
            ),
          ],
          if (action != null) ...[
            SizedBox(height: p(4)),
            Align(alignment: Alignment.centerLeft, child: action),
          ],
          if (showStages && step != PairStep.connected) ...[
            SizedBox(height: p(4)),
            _Line(signal: Signal.idle, text: PairScreen.holdHint, textKey: const Key('hold_hint')),
          ],
        ],
      ),
    );
  }

  Widget _button(Key key, Glyph glyph, String label, VoidCallback onPressed, {bool filled = false}) => filled
      ? FilledButton.icon(key: key, icon: PixelGlyph(glyph), label: Text(label), onPressed: busy ? null : onPressed)
      : OutlinedButton.icon(key: key, icon: PixelGlyph(glyph), label: Text(label), onPressed: busy ? null : onPressed);
}

/// A line with its signal lamp (the status screen's note, here for the pairing screen).
class _Line extends StatelessWidget {
  const _Line({required this.signal, required this.text, this.textKey});

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
