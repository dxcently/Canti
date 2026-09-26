import 'package:flutter/material.dart';

import 'backend.dart';
import 'status_screen.dart';

/// The Flutter part of the VOX app. Android embeds it (android/app, `MainActivity`); ../desktop runs it on Linux with
/// a [FakeBackend].
class VoxUiApp extends StatelessWidget {
  const VoxUiApp({super.key, required this.backend});

  final VoxBackend backend;

  static const _seed = Color(0xFF3949AB);

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'VOX',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(colorScheme: ColorScheme.fromSeed(seedColor: _seed)),
        darkTheme: ThemeData(colorScheme: ColorScheme.fromSeed(seedColor: _seed, brightness: Brightness.dark)),
        home: StatusScreen(backend: backend),
      );
}
