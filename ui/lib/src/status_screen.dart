import 'dart:async';
import 'dart:collection';

import 'package:flutter/material.dart';

import 'backend.dart';
import 'calibration.dart';
import 'calibration_screen.dart';
import 'canti_head.dart';
import 'pair_screen.dart';
import 'quickrec_screen.dart'; // [rec]
import 'recorder_screen.dart'; // [rec]
import 'theme/assets.dart';
import 'theme/canti_theme.dart';
import 'theme/clearing.dart';
import 'theme/glyphs.dart';
import 'theme/kit.dart';
import 'theme/motion.dart';
import 'theme/pixel.dart';
import 'train_screen.dart'; // [train]
import 'voice_cursor.dart';

/// The status screen: the service and device state, pause/resume, the live event log, and a way to the native
/// settings screen. Every control has a text label, so Android accessibility (and VOX's own Targets.kt) can name it.
///
/// With a VOX device connected, the device is the source of truth for `armed`: the main button pauses or arms the
/// **device**, and a mode toggle and "Sleep device" appear. Without one (phone-only or debug sources), the main
/// button is the app-side pause.
///
/// Rebuilds: events go into [_EventLog], a [ChangeNotifier] only the log list listens to, so a stream of events
/// repaints the list and nothing else. The screen's own `setState` runs only when the status, the busy flag or the
/// error line changes; status refetches triggered by bursts of events are coalesced into one in flight plus one
/// queued.
class StatusScreen extends StatefulWidget {
  const StatusScreen({super.key, required this.backend, this.maxEvents = 50});

  final VoxBackend backend;
  final int maxEvents;

  @override
  State<StatusScreen> createState() => _StatusScreenState();
}

class _StatusScreenState extends State<StatusScreen> {
  /// Events after which the status is fetched again.
  static const _statusEvents = {'arm', 'pause', 'mode', 'service', 'ble', 'reset', 'app', 'source', 'device_cmd', 'calib', 'train'};

  VoxStatus? _status;
  String? _error;
  bool _busy = false;
  late final _log = _EventLog(widget.maxEvents);
  StreamSubscription<VoxEvent>? _sub;
  StreamSubscription<String>? _routeSub;
  Future<void>? _inFlight;
  bool _again = false;
  bool _pairOpen = false;
  bool _calibOpen = false;
  bool _recOpen = false; // [rec]
  bool _quickOpen = false; // [rec]
  bool _calibPromptDismissed = false;

  /// Bumped after a calibration is saved, so the voice cursor section reloads.
  final _calibVersion = ValueNotifier<int>(0);

  @override
  void initState() {
    super.initState();
    _refresh();
    _sub = widget.backend.events().listen(_onEvent, onError: (Object e) => _setError('events: $e'));
    // The badge menu and the sound-source chooser open the app for the pairing screen.
    _routeSub = widget.backend.routeRequests().listen(_openRoute);
    widget.backend.launchRoute().then(_openRoute, onError: (Object e) => _setError('route: $e'));
  }

  @override
  void dispose() {
    _sub?.cancel();
    _routeSub?.cancel();
    _log.dispose();
    _calibVersion.dispose();
    super.dispose();
  }

  void _setError(String e) {
    if (mounted) setState(() => _error = e);
  }

  /// Fetches the status. While a fetch is in flight, further calls queue exactly one more fetch after it.
  Future<void> _refresh() {
    if (_inFlight != null) {
      _again = true;
      return _inFlight!;
    }
    return _inFlight = _fetch().whenComplete(() {
      _inFlight = null;
      if (_again) {
        _again = false;
        _refresh();
      }
    });
  }

  Future<void> _fetch() async {
    try {
      final s = await widget.backend.status();
      if (mounted) {
        setState(() {
          _status = s;
          _error = null;
        });
      }
    } catch (e) {
      _setError('status: $e');
    }
  }

  void _onEvent(VoxEvent e) {
    if (!mounted) return;
    _log.add(e);
    if (_statusEvents.contains(e.name)) _refresh();
  }

  /// Whether sounds act, as far as the main button is concerned.
  static bool _on(VoxStatus s) =>
      s.deviceReady ? s.deviceArmed == true && !s.paused : (!_mic(s) || s.armed) && !s.paused;

  /// A phone or USB mic source: the phone owns the arm state and mode (no device), so the app can disarm and re-arm it.
  static bool _mic(VoxStatus s) => s.soundSource == 'phone' || s.soundSource == 'usb';

  Future<void> _busyWhile(String what, Future<void> Function() f) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await f();
    } catch (e) {
      _setError('$what: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Pause or resume. With a device connected this commands the device (and a resume also lifts an app-side pause);
  /// otherwise it is the app-side pause (a disarmed mic source is re-armed first, since resuming is a no-op then).
  Future<void> _togglePause() async {
    final s = _status;
    if (s == null) return;
    await _busyWhile('pause', () async {
      if (!s.deviceReady) {
        if (_on(s)) {
          await widget.backend.setPaused(true);
        } else {
          if (_mic(s) && !s.armed) await widget.backend.deviceCommand(armed: true);
          if (s.paused) await widget.backend.setPaused(false);
        }
        await _refresh();
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

  void _openRoute(String? route) {
    if (route == 'pair') _openPair();
    if (route == 'calibrate') _openCalib();
    if (route == 'quickrec') _quickRoute(); // [rec]
  }

  /// The badge's QUICK REC (a snapshot is pending): dev builds only, so the status is fetched first if it is not in yet. // [rec]
  Future<void> _quickRoute() async {
    if (_status == null) await _refresh();
    if (mounted && _status?.devRecorder == true) _openQuickRec();
  }

  /// The first-run pairing screen (once, however many times it is asked for); the status is fetched again after.
  Future<void> _openPair() async {
    if (_pairOpen || !mounted) return;
    _pairOpen = true;
    await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => PairScreen(backend: widget.backend)));
    _pairOpen = false;
    if (mounted) _refresh();
  }

  /// The mic the voice cursor is calibrated for: the current sound source.
  String get _calibSource => _status?.soundSource ?? 'phone';

  /// The voice cursor's setup (once, however many times it is asked for); the status is fetched again after. Every
  /// Calibrate entry goes through this one guard ([steps]: a profile's missing steps), so screens never stack.
  Future<void> _openCalib({List<String>? steps}) async {
    if (_calibOpen || !mounted) return;
    _calibOpen = true;
    final saved = await openCalibration(context, widget.backend, _calibSource, steps: steps);
    _calibOpen = false;
    if (saved) _calibVersion.value++;
    if (mounted) _refresh();
  }

  /// The in-app test recorder (once, however many times it is asked for). // [rec]
  Future<void> _openRecorder() async {
    if (_recOpen || !mounted) return;
    _recOpen = true;
    await openRecorder(context, widget.backend);
    _recOpen = false;
    if (mounted) _refresh();
  }

  /// The quick record screen (once, however many times it is asked for). // [rec]
  Future<void> _openQuickRec({bool snap = false}) async {
    if (_quickOpen || !mounted) return;
    _quickOpen = true;
    await openQuickRec(context, widget.backend, snap: snap);
    _quickOpen = false;
    if (mounted) _refresh();
  }

  /// Ends an open calibration (the status screen's "Calibrating" Stop button).
  Future<void> _stopCalib() => _busyWhile('calibrate', () async {
        await widget.backend.calibCancel();
        await _refresh();
      });

  /// Tapping the in-app header head: the same actions as the badge menu (pause/resume, mode, calibrate), so they stay
  /// reachable while the floating head is tucked away. Reuses the status screen's own buttons and toggle.
  Future<void> _openHeadMenu() async {
    final s = _status;
    if (s == null || !s.service || !mounted) return;
    final paused = !_on(s);
    final micSource = _mic(s);
    final p = Px.of(context);
    await showModalBottomSheet<void>(
      context: context,
      builder: (sheet) => Padding(
        padding: EdgeInsets.all(p(5)),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            FilledButton.icon(
              key: const Key('head_pause'),
              icon: PixelGlyph(paused ? Icons7.play : Icons7.pause),
              label: Text(paused ? 'Resume Canti' : 'Pause Canti'),
              onPressed: () {
                Navigator.of(sheet).pop();
                _togglePause();
              },
            ),
            if (s.deviceReady || micSource) ...[
              SizedBox(height: p(3)),
              PixelToggle<String>(
                key: const Key('head_mode'),
                options: const [('gesture', 'Gesture', Icons7.hand), ('cursor', 'Cursor', Icons7.cursor)],
                selected: s.deviceMode ?? s.mode,
                onChanged: (v) {
                  Navigator.of(sheet).pop();
                  _busyWhile('mode', () => _device(mode: v));
                },
              ),
            ],
            // the voice cursor's setup: phone / USB mics only (as the badge menu; the Pico's mic can't be calibrated)
            if (micSource) ...[
              SizedBox(height: p(3)),
              OutlinedButton.icon(
                key: const Key('head_calibrate'),
                icon: const PixelGlyph(Icons7.target),
                label: const Text('Calibrate'),
                onPressed: () {
                  Navigator.of(sheet).pop();
                  _openCalib();
                },
              ),
            ],
          ],
        ),
      ),
    );
  }

  /// Cursor mode on a mic with no calibration (the service's `calibrated: false`): offer the setup.
  bool _needsCalib(VoxStatus s) {
    final mode = s.deviceReady ? (s.deviceMode ?? s.mode) : s.mode;
    return s.service &&
        mode == 'cursor' &&
        (s.soundSource == 'phone' || s.soundSource == 'usb') &&
        s.calibrated == false &&
        !_calibPromptDismissed;
  }

  Future<void> _connect() =>_busyWhile('connect', () async {
        final n = await widget.backend.connectDevice();
        if (mounted) setState(() => _status = n);
      });

  @override
  Widget build(BuildContext context) {
    final s = _status;
    final p = Px.of(context);
    final canPause = s != null && s.service && !_busy;
    final paused = s != null && !_on(s);
    // A phone or USB mic source owns the mode (the service applies it here), like a connected device does.
    final micSource = s != null && (s.soundSource == 'phone' || s.soundSource == 'usb');
    final gap = SizedBox(height: p(5), width: p(5));

    final error = _error == null
        ? null
        : PixelWindow(
            title: 'Error',
            onClose: () => setState(() => _error = null),
            closeLabel: 'Dismiss error',
            child: _Note(signal: Signal.stop, text: _error!),
          );
    // First run: the Pico with no device remembered (the pairing screen covers hints and retries then).
    final setup = s != null && s.needsPairing
        ? PixelWindow(
            title: 'Set up',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const _Note(signal: Signal.waiting, text: 'No Canti device is paired with this phone yet.'),
                SizedBox(height: p(3)),
                FilledButton.icon(
                  key: const Key('setup_find_device'),
                  icon: const PixelGlyph(Icons7.target),
                  label: const Text('Find my Canti device'),
                  onPressed: _openPair,
                ),
                SizedBox(height: p(3)),
                const _Note(signal: Signal.idle, text: PairScreen.holdHint),
              ],
            ),
          )
        : null;
    final pairing = s != null && s.service && !s.needsPairing && (s.bleHint != null || s.deviceState == 'pairing needed')
        ? PixelWindow(
            title: 'Pairing',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (s.bleHint != null) _Note(signal: Signal.waiting, text: s.bleHint!, textKey: const Key('ble_hint')),
                if (s.deviceState == 'pairing needed') ...[
                  SizedBox(height: p(3)),
                  OutlinedButton.icon(
                    key: const Key('connect'),
                    icon: const PixelGlyph(Icons7.link),
                    label: const Text('Connect'),
                    onPressed: _busy ? null : _connect,
                  ),
                ],
              ],
            ),
          )
        : null;
    final control = PixelWindow(
      title: 'Control',
      child: Wrap(
        spacing: p(2),
        runSpacing: p(2),
        children: [
          FilledButton.icon(
            key: const Key('pause'),
            icon: PixelGlyph(paused ? Icons7.play : Icons7.pause),
            label: Text(paused ? 'Resume Canti' : 'Pause Canti'),
            onPressed: canPause ? _togglePause : null,
          ),
          if (s != null && s.service && s.deviceReady)
            OutlinedButton.icon(
              key: const Key('sleep'),
              icon: const PixelGlyph(Icons7.moon),
              label: const Text('Sleep device'),
              onPressed: _busy ? null : () => _busyWhile('sleep', () => _device(sleep: true)),
            ),
          if (s != null && s.service && (s.deviceReady || micSource))
            PixelToggle<String>(
              key: const Key('mode'),
              options: const [('gesture', 'Gesture', Icons7.hand), ('cursor', 'Cursor', Icons7.cursor)],
              selected: s.deviceMode ?? s.mode,
              onChanged: _busy ? null : (v) => _busyWhile('mode', () => _device(mode: v)),
            ),
          if (widget.backend.hasLegacySettings)
            OutlinedButton.icon(
              key: const Key('legacy'),
              icon: const PixelGlyph(Icons7.gear),
              label: const Text('Legacy settings'),
              onPressed: widget.backend.openLegacySettings,
            ),
        ],
      ),
    );
    // First time in cursor mode on a mic with no calibration: offer the setup (dismissable for this run).
    final calibPrompt = s != null && _needsCalib(s)
        ? PixelWindow(
            title: 'Calibrate',
            onClose: () => setState(() => _calibPromptDismissed = true),
            closeLabel: 'Not now',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _Note(
                  signal: Signal.waiting,
                  text: 'The voice cursor is not calibrated for the ${sourceLabel(s.soundSource)}. A 25 s setup teaches '
                      'it your voice: your hum, your range, three vowels and your pops.',
                ),
                SizedBox(height: p(3)),
                FilledButton.icon(
                  key: const Key('calib_prompt_start'),
                  icon: const PixelGlyph(Icons7.target),
                  label: const Text('Calibrate now'),
                  onPressed: _openCalib,
                ),
              ],
            ),
          )
        : null;
    // A calibration is running: sounds are dropped as "calibrating", so say so plainly and offer to stop it.
    final calibrating = s != null && s.service && s.calibrating
        ? PixelWindow(
            title: 'Calibrating',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _Note(signal: Signal.waiting, text: 'Calibrating — sounds are paused.', textKey: const Key('calibrating_note')),
                SizedBox(height: p(3)),
                FilledButton.icon(
                  key: const Key('calibrating_stop'),
                  icon: const PixelGlyph(Icons7.pause),
                  label: const Text('Stop calibrating'),
                  onPressed: _busy ? null : _stopCalib,
                ),
              ],
            ),
          )
        : null;
    final left = <Widget>[
      _Header(status: s, events: widget.backend.events(), onRefresh: _refresh, onHeadTap: _openHeadMenu),
      ?error,
      s == null ? const _Loading() : _StatusWindow(status: s),
      ?setup,
      ?pairing,
      ?calibPrompt,
      ?calibrating,
      control,
      if (s != null && s.service) TrainGesturesWindow(backend: widget.backend, source: _calibSource), // [train]
      if (s != null && s.service && s.devRecorder)
        RecorderEntryWindow(backend: widget.backend, onOpen: _openRecorder, onQuick: () => _openQuickRec(snap: true)), // [rec]
      VoiceCursorWindow(
        backend: widget.backend,
        source: _calibSource,
        version: _calibVersion,
        openCalibrate: _openCalib,
        onCalibrated: _refresh,
      ),
    ];
    final right = <Widget>[
      _HeardWindow(log: _log),
      _BindingsWindow(bindings: s?.bindings ?? VoxBindings.defaults),
    ];
    final log = _LogWindow(log: _log);

    return Scaffold(
      body: SafeArea(
        child: LayoutBuilder(
          builder: (context, box) {
            final pad = EdgeInsets.all(p(5));
            if (box.maxWidth >= 700) {
              return Padding(
                padding: pad,
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Expanded(
                      flex: 3,
                      child: SingleChildScrollView(
                        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: _spaced(left, gap)),
                      ),
                    ),
                    gap,
                    Expanded(
                      flex: 2,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Flexible(
                            child: SingleChildScrollView(
                              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: _spaced(right, gap)),
                            ),
                          ),
                          gap,
                          Expanded(child: log),
                        ],
                      ),
                    ),
                  ],
                ),
              );
            }
            return SingleChildScrollView(
              padding: pad,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: _spaced([
                  ...left,
                  ...right,
                  SizedBox(height: (box.maxHeight * 0.55).clamp(p(120), 420.0), child: log),
                ], gap),
              ),
            );
          },
        ),
      ),
    );
  }

  static List<Widget> _spaced(List<Widget> ws, Widget gap) => [
        for (final (i, w) in ws.indexed) ...[if (i > 0) gap, w],
      ];
}

/// Canti (the animated character, showing the live state), the wordmark and refresh, in a clearing of the dot field
/// so the wordmark and its subtitle read. The brand art keeps its own colours.
class _Header extends StatelessWidget {
  const _Header({required this.status, required this.events, required this.onRefresh, required this.onHeadTap});

  final VoxStatus? status;
  final Stream<VoxEvent> events;
  final VoidCallback onRefresh;
  final VoidCallback onHeadTap;

  /// Art px across Canti's place in the row (at least the sprite's frame width).
  static const _slotArtPx = 40;

  @override
  Widget build(BuildContext context) {
    final t = CantiTheme.of(context);
    final wordmark = BrandArt.wordmark(light: t.dark);
    return DitherClearing(
      child: Row(
        children: [
          // Canti centred in a 40-art-px slot (the frame was 40 wide before the arms were slimmed to 34; the sprite's
          // centre line is the frame's), so the head and the wordmark keep their places.
          SizedBox(
            width: Px.of(context)(_slotArtPx),
            child: Semantics(
              button: true,
              label: 'Canti menu',
              child: GestureDetector(
                key: const Key('head_menu'),
                behavior: HitTestBehavior.opaque,
                onTap: onHeadTap,
                child: Align(alignment: Alignment.topCenter, heightFactor: 1, child: CantiHead(status: status, events: events)),
              ),
            ),
          ),
          SizedBox(width: Px.of(context)(4)),
          // The wordmark (41 art px) sits 8 art px down, level with the head's dome (47 tall; the row is 49, the head 1 down).
          // 8 art px is a whole Bayer period of the dot field (4 cells of 2 art px), so the dither ramp under the subtitle
          // falls as designed and the paper under it stays clear (clearing_test); 4 px down leaves a dot there.
          Padding(
            padding: EdgeInsets.only(top: Px.of(context)(8)),
            child: Semantics(
              header: true,
              label: 'Canti',
              child: ExcludeSemantics(child: AssetClearingInk(asset: wordmark.shapeAsset, child: wordmark)),
            ),
          ),
          const Spacer(),
          ClearingInk(
            child: PixelIconButton(
                key: const Key('refresh'), glyph: Icons7.refresh, tooltip: 'Refresh status', onPressed: onRefresh),
          ),
        ],
      ),
    );
  }
}

class _Loading extends StatelessWidget {
  const _Loading();

  @override
  Widget build(BuildContext context) => PixelWindow(
        title: 'Status',
        child: Text('Connecting to the Canti service...', style: Px.of(context).body(CantiTheme.of(context).ink)),
      );
}

/// A message with its signal lamp: an error (red), a hint or a wait (yellow). Text stays ink on paper.
class _Note extends StatelessWidget {
  const _Note({required this.signal, required this.text, this.textKey});

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

/// The status: the lamp and headline, the link meter, then the fields as stat rows on an inverted panel.
class _StatusWindow extends StatelessWidget {
  const _StatusWindow({required this.status});

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
    if (s.deviceReady ? s.deviceArmed != true : !s.armed) {
      return s.deviceReady ? 'Device paused' : (s.soundSource == 'phone' || s.soundSource == 'usb' ? 'Disarmed' : 'Disarmed by the device');
    }
    return 'Listening for sounds';
  }

  /// Orange only while sounds act, yellow while something is pending, red when stopped by a fault.
  Signal get _signal {
    final s = status;
    if (!s.service || s.deviceError != null) return Signal.stop;
    if (s.deviceWaiting != null || s.deviceState == 'connecting' || s.deviceState == 'pairing needed') return Signal.waiting;
    final acting = s.hasDevice ? s.deviceState == 'listening' && s.deviceReady && s.deviceArmed == true && !s.paused : s.active;
    return acting ? Signal.listening : Signal.idle;
  }

  /// The link as pips: up and commandable 4, linked 3, connecting 2, waiting for the device 1, else 0.
  int get _link {
    final s = status;
    if (s.deviceReady) return 4;
    return switch (s.bleState) { 'ready' => 3, 'connecting' || 'scanning' => 2, 'waiting' => 1, _ => 0 };
  }

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    final s = status;
    final mode = s.deviceReady ? (s.deviceMode ?? s.mode) : s.mode;
    final rows = <(Glyph, String, String)>[
      (Icons7.power, 'Service', s.service ? 'running' : 'off (turn on Canti controls in Accessibility settings)'),
      if (s.service) ...[
        (Icons7.device, 'Device', s.deviceState ?? (s.armed ? 'armed' : 'disarmed')),
        (mode == 'cursor' ? Icons7.cursor : Icons7.hand, 'Mode', mode),
        (Icons7.app, 'App', s.app ?? 'unknown'),
        (Icons7.link, 'Link', [s.bleState ?? 'no link', if (s.bleDevice != null) s.bleDevice!].join(', ')),
        (Icons7.decider, 'Decider', s.decider ?? '?'),
        if (s.asrStatus != null) (Icons7.sound, 'Speech', s.asrStatus!),
      ],
    ];
    final headline = _headline;
    return PixelWindow(
      title: 'Status',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(padding: EdgeInsets.only(top: p(3)), child: SignalLamp(_signal)),
              SizedBox(width: p(4)),
              Expanded(
                // a headline change flickers on like a screen
                child: Flicker(
                  key: ValueKey(headline),
                  child: Semantics(
                    liveRegion: true,
                    child: PixelSnap(child: Text(headline, key: const Key('headline'), style: p.big(t.ink))),
                  ),
                ),
              ),
              if (s.service && s.hasDevice)
                Padding(
                  padding: EdgeInsets.only(top: p(3), left: p(3)),
                  child: PipMeter(value: _link, max: 4, label: 'link', color: t.ink),
                ),
            ],
          ),
          SizedBox(height: p(3)),
          InvertedPanel(
            child: Column(
              children: [
                for (final (i, (icon, label, value)) in rows.indexed) ...[
                  if (i > 0) SizedBox(height: p(1)),
                  StatRow(icon: icon, label: label, value: value),
                ],
              ],
            ),
          ),
          if (s.service && s.deviceError != null) ...[
            SizedBox(height: p(4)),
            _Note(signal: Signal.stop, text: s.deviceError!, textKey: const Key('device_error')),
          ],
          if (s.service && s.asrProblem) ...[
            SizedBox(height: p(4)),
            _Note(signal: Signal.waiting, text: 'Spoken phrases: ${s.asrStatus}', textKey: const Key('asr_status')),
          ],
          if (s.service && s.deviceWaiting != null) ...[
            SizedBox(height: p(4)),
            _Note(signal: Signal.waiting, text: 'Waiting for the device: ${s.deviceWaiting}', textKey: const Key('device_waiting')),
          ],
        ],
      ),
    );
  }
}

/// The live event log: newest first, at most [max] entries. Only the log's listeners rebuild on an event.
class _EventLog extends ChangeNotifier {
  _EventLog(this.max);

  final int max;
  final _items = ListQueue<VoxEvent>();

  int get length => _items.length;
  VoxEvent operator [](int i) => _items.elementAt(i);
  bool get isEmpty => _items.isEmpty;
  Iterable<VoxEvent> get newestFirst => _items;

  void add(VoxEvent e) {
    _items.addFirst(e);
    while (_items.length > max) {
      _items.removeLast();
    }
    notifyListeners();
  }
}

/// The last sound heard and what was decided for it, from the event log.
class _HeardWindow extends StatelessWidget {
  const _HeardWindow({required this.log});

  final _EventLog log;

  static String? _str(Object? v) => v == null ? null : '$v';

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    return PixelWindow(
      title: 'Heard',
      child: InvertedPanel(
        child: ListenableBuilder(
          listenable: log,
          builder: (context, _) {
            String? sound, action, conf, by;
            for (final e in log.newestFirst) {
              if (sound == null && e.name == 'msg') sound = _str(e.fields['sequence']) ?? _str(e.fields['phrase']);
              if (action == null && e.name == 'decision') {
                action = _str(e.fields['action']) ?? '?';
                final c = e.fields['confidence'];
                conf = c is num ? c.toStringAsFixed(2) : '-';
                by = _str(e.fields['source']) ?? '-';
              }
              if (sound != null && action != null) break;
            }
            final rows = [
              (Icons7.sound, 'Sound', sound ?? '-'),
              (Icons7.hand, 'Action', action ?? '-'),
              (Icons7.target, 'Conf', conf ?? '-'),
              (Icons7.decider, 'By', by ?? '-'),
            ];
            return Column(
              children: [
                for (final (i, (icon, label, value)) in rows.indexed) ...[
                  if (i > 0) SizedBox(height: p(1)),
                  StatRow(icon: icon, label: label, value: value),
                ],
              ],
            );
          },
        ),
      ),
    );
  }
}

/// The bindings window: per mode, what each sound does, from the service's resolved bindings ([VoxBindings];
/// android `Bindings.kt`): a glyph grid with the bracket cursor and a name bar per mode, and the two-sound combos,
/// paged. It shows the user's own rules on top of the Vocab defaults, and tags a rule's source.
class _BindingsWindow extends StatefulWidget {
  const _BindingsWindow({required this.bindings});

  /// The resolved bindings (the status's `bindings`, or [VoxBindings.defaults] when the service sent none).
  final VoxBindings bindings;

  @override
  State<_BindingsWindow> createState() => _BindingsWindowState();
}

/// The tag for a binding that came from a user rule (null for the built-in defaults and app-only bindings).
String? _ruleTag(String? source) => switch (source) {
      'global' => 'global rule',
      'app' => 'app rule',
      'cursor' => 'cursor rule',
      _ => null,
    };

/// A binding's name-bar text: its label, with the source of a user rule after it.
String _bindingLabel(VoxBinding b) {
  final tag = _ruleTag(b.source);
  return tag == null ? b.label : '${b.label} · $tag';
}

class _BindingsWindowState extends State<_BindingsWindow> {
  static const _pages = ['gesture mode', 'cursor mode', 'combos'];

  int _page = 0;
  final _sel = [0, 0];

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final t = CantiTheme.of(context);
    final Widget body;
    if (_page < 2) {
      final mode = _page == 0 ? widget.bindings.gesture : widget.bindings.cursor;
      final items = [
        for (final sound in VoxBindings.sounds)
          GridItem(
            sound,
            GestureGlyphs.bySound[sound]!,
            mode.sounds[sound] == null ? '-' : _bindingLabel(mode.sounds[sound]!),
          ),
      ];
      final sel = items[_sel[_page]];
      body = Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Center(
            child: GlyphGrid(items: items, selected: _sel[_page], onSelect: (i) => setState(() => _sel[_page] = i)),
          ),
          SizedBox(height: p(2)),
          NameBar(label: sel.name, value: sel.value),
          if (mode.note != null) ...[
            SizedBox(height: p(3)),
            _Note(signal: Signal.idle, text: mode.note!, textKey: const Key('bindings_note')),
          ],
        ],
      );
    } else {
      // The combos: gesture mode's defaults and rules, then cursor mode's (any cursor rules; each tagged, since the
      // same sounds can mean something else in gesture mode).
      final combos = [
        for (final c in widget.bindings.gesture.combos) c,
        for (final c in widget.bindings.cursor.combos)
          c.source == 'cursor' ? c : VoxBinding('${c.label} · cursor', c.source, c.sequence),
      ];
      body = InvertedPanel(
        child: Column(
          children: [
            for (final (i, c) in combos.indexed) ...[
              if (i > 0) SizedBox(height: p(1)),
              StatRow(icon: Icons7.sound, label: _comboName(c.sequence), value: _bindingLabel(c)),
            ],
          ],
        ),
      );
    }
    return PixelWindow(
      title: 'Bindings',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          PixelSnap(child: Text(_pages[_page], style: p.body(t.ink))),
          SizedBox(height: p(3)),
          body,
          Center(child: PixelPager(index: _page, count: _pages.length, onChanged: (i) => setState(() => _page = i))),
        ],
      ),
    );
  }
}

/// The event log window: the list with the kit's scrollbar, or a hatched empty state.
class _LogWindow extends StatefulWidget {
  const _LogWindow({required this.log});

  final _EventLog log;

  @override
  State<_LogWindow> createState() => _LogWindowState();
}

class _LogWindowState extends State<_LogWindow> {
  final _scroll = ScrollController();

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final log = widget.log;
    return PixelWindow(
      title: 'Log',
      child: ListenableBuilder(
        listenable: log,
        builder: (context, _) => log.isEmpty
            ? const HatchBox(child: Text('No events yet.'))
            : Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Expanded(
                    child: ListView.builder(
                      key: const Key('events'),
                      controller: _scroll,
                      itemCount: log.length,
                      itemBuilder: (context, i) {
                        final e = log[i];
                        final tile = _EventTile(event: e);
                        // Only the newest line blinks in, once (its key is the event).
                        return i == 0 ? Flicker(key: ObjectKey(e), child: tile) : tile;
                      },
                    ),
                  ),
                  SizedBox(width: p(2)),
                  PixelScrollbar(controller: _scroll),
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
        contentPadding: EdgeInsets.zero,
        visualDensity: VisualDensity.compact,
        title: Text(event.name),
        subtitle: Text(event.summary, maxLines: 2, overflow: TextOverflow.ellipsis),
        trailing: Text('${(event.t / 1000).toStringAsFixed(1)} s'),
      );
}

/// A combo's sounds as its row label; a run of three or more of the same sound is written `click ×3` so the row fits.
String _comboName(List<String> seq) {
  final out = <String>[];
  for (var i = 0; i < seq.length;) {
    var j = i;
    while (j < seq.length && seq[j] == seq[i]) {
      j++;
    }
    out.add(j - i >= 3 ? '${seq[i]} ×${j - i}' : List.filled(j - i, seq[i]).join(' '));
    i = j;
  }
  return out.join(' ');
}
