import 'package:flutter/widgets.dart';

import 'vox_ui.dart';

/// Entry point when embedded in the Android app: the backend is the Kotlin service, over platform channels.
void main() {
  // ChannelBackend sets a method call handler in its constructor, which needs the binding's messenger.
  WidgetsFlutterBinding.ensureInitialized();
  runApp(VoxUiApp(backend: ChannelBackend()));
}
