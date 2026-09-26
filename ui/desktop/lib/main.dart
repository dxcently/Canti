import 'package:flutter/widgets.dart';
import 'package:vox_ui/vox_ui.dart';

/// The VOX screens on the Linux desktop, with the in-memory backend playing demo events (no phone needed).
void main() => runApp(VoxUiApp(backend: FakeBackend(demo: true)));
