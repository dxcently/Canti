import 'package:flutter/material.dart';

import 'backend.dart';
import 'calibration.dart';
import 'calibration_screen.dart' show CalibPanel;
import 'hub_screen.dart';
import 'theme/glyphs.dart';
import 'theme/kit.dart';
import 'theme/pixel.dart';
import 'train.dart';

/// Opens gesture training (android/PROTOCOL.md "Gesture training"): the tests hub for [source], where each gesture
/// row opens its takes.
Future<void> openTraining(BuildContext context, VoxBackend backend, {TrainBackend? train, String? source}) =>
    openHub(context, backend, train: train, source: source);

// --- the status screen's entry -----------------------------------------------------------------------------------

/// The status screen's "Train gestures" window: progress per mic source and the button that opens the tests hub.
class TrainGesturesWindow extends StatefulWidget {
  const TrainGesturesWindow({super.key, required this.backend, required this.source, this.train});

  final VoxBackend backend;

  /// The current sound source.
  final String source;

  /// By default [trainBackendFor] the backend.
  final TrainBackend? train;

  @override
  State<TrainGesturesWindow> createState() => _TrainGesturesWindowState();
}

class _TrainGesturesWindowState extends State<TrainGesturesWindow> {
  late final TrainBackend _train = widget.train ?? trainBackendFor(widget.backend);
  TrainStatus? _status;
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(TrainGesturesWindow old) {
    super.didUpdateWidget(old);
    if (old.source != widget.source) _load();
  }

  Future<void> _load() async {
    try {
      final s = await _train.status();
      if (!mounted) return;
      setState(() {
        _status = s;
        _failed = false;
      });
    } catch (_) {
      if (mounted) setState(() => _failed = true);
    }
  }

  Future<void> _open() async {
    await openTraining(context, widget.backend, train: _train, source: _status?.currentSource ?? widget.source);
    if (mounted) await _load();
  }

  @override
  Widget build(BuildContext context) {
    final p = Px.of(context);
    final s = _status;
    final src = s?.currentSource ?? widget.source;
    final done = s?.sources[src]?.$1 ?? s?.done;
    final total = s?.sources[src]?.$2 ?? s?.total;
    final text = s == null
        ? (_failed ? 'Training is not available right now.' : 'Loading...')
        : done == 0
        ? 'Teach Canti your own version of each gesture on the ${sourceLabel(src)}: hummed and whistled, low '
              'and high, slow and quick. One gesture at a time, about 10 s a take.'
        : '${sourceLabel(src)}: $done of $total takes recorded.';
    return PixelWindow(
      key: const Key('train_entry'),
      title: 'Train gestures',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SignalNote(
            signal: s != null && done != null && total != null && done >= total ? Signal.idle : Signal.waiting,
            text: text,
            textKey: const Key('train_entry_note'),
          ),
          if (s != null) ...[
            SizedBox(height: p(3)),
            CalibPanel(
              rows: [
                for (final x in trainSources)
                  (
                    x == src ? Icons7.sound : Icons7.pipOff,
                    x == 'pico'
                        ? 'Canti'
                        : x == 'usb'
                        ? 'USB'
                        : 'Phone',
                    '${s.sources[x]?.$1 ?? 0}/${s.sources[x]?.$2 ?? s.total}',
                    Key('train_entry_$x'),
                  ),
              ],
            ),
          ],
          SizedBox(height: p(3)),
          Align(
            alignment: Alignment.centerLeft,
            child: FilledButton.icon(
              key: const Key('train_open'),
              icon: const PixelGlyph(Icons7.hand),
              label: Text(done != null && done > 0 ? 'Train gestures' : 'Start training'),
              onPressed: _failed ? null : _open,
            ),
          ),
        ],
      ),
    );
  }
}
