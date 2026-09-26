import 'package:flutter/widgets.dart';

import 'vox_ui.dart';

/// Entry point when embedded in the Android app: the backend is the Kotlin service, over platform channels.
void main() => runApp(VoxUiApp(backend: ChannelBackend()));
