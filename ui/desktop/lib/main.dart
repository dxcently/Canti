import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';
import 'package:vox_ui/vox_ui.dart';

import 'preview.dart';

/// The VOX screens on the Linux desktop, with the in-memory backend playing demo events (no phone needed).
///
/// Environment (all optional):
///   VOX_THEME=light|dark   force a theme (default: the desktop's setting)
///   VOX_FRAME_STATS=N      collect frame timings for N seconds, print a summary to stdout and exit (use a
///                          `--profile` build: debug-mode timings mean nothing)
///   VOX_PREVIEW=calibrate|cursor|settings|pair|train   the voice cursor and gesture training screens on made-up data (see preview.dart)
void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final env = Platform.environment;
  final mode = switch (env['VOX_THEME']) { 'light' => ThemeMode.light, 'dark' => ThemeMode.dark, _ => ThemeMode.system };
  final secs = int.tryParse(env['VOX_FRAME_STATS'] ?? '');
  if (secs != null) _frameStats(secs);
  final preview = Preview.fromEnv(env);
  if (preview == null) {
    runApp(VoxUiApp(backend: FakeBackend(demo: true), themeMode: mode));
    return;
  }
  runApp(VoxUiApp(backend: preview.backend, themeMode: mode, home: preview.home));
  WidgetsBinding.instance.addPostFrameCallback((_) => preview.start());
}

void _frameStats(int seconds) {
  final build = <int>[], raster = <int>[], total = <int>[];
  SchedulerBinding.instance.addTimingsCallback((List<FrameTiming> ts) {
    for (final t in ts) {
      build.add(t.buildDuration.inMicroseconds);
      raster.add(t.rasterDuration.inMicroseconds);
      total.add(t.totalSpan.inMicroseconds);
    }
  });
  String row(String name, List<int> v) {
    if (v.isEmpty) return '$name: no frames';
    final s = [...v]..sort();
    String ms(double q) => (s[((s.length - 1) * q).round()] / 1000).toStringAsFixed(2);
    return '$name ms: p50 ${ms(0.5)}  p90 ${ms(0.9)}  p99 ${ms(0.99)}  max ${ms(1)}';
  }

  Timer(Duration(seconds: seconds), () {
    stdout.writeln('frames: ${total.length} in ${seconds}s');
    stdout.writeln(row('build', build));
    stdout.writeln(row('raster', raster));
    stdout.writeln(row('total', total));
    exit(0);
  });
}
