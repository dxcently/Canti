package ai.vox.companion

import android.os.Bundle
import android.os.Process
import android.os.SystemClock
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine

/**
 * The launcher screen: the Flutter UI from ../ui (add-to-app, built from source). The Dart side talks to the service
 * through [UiBridge]; the old native screen is [LegacySettingsActivity], opened from the Flutter "Legacy settings"
 * button.
 *
 * Logs `ui{what: first_frame, since_process_start_ms, since_create_ms}` when Flutter draws its first frame (the
 * cold-start figure in README).
 */
class MainActivity : FlutterActivity() {
    private var bridge: UiBridge? = null
    private var createdAt = 0L

    override fun onCreate(savedInstanceState: Bundle?) {
        createdAt = SystemClock.elapsedRealtime()
        EventLog.initIfNeeded(this)
        super.onCreate(savedInstanceState)
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        bridge = UiBridge(this, flutterEngine.dartExecutor.binaryMessenger)
    }

    override fun cleanUpFlutterEngine(flutterEngine: FlutterEngine) {
        bridge?.close(); bridge = null
        super.cleanUpFlutterEngine(flutterEngine)
    }

    override fun onFlutterUiDisplayed() {
        super.onFlutterUiDisplayed()
        if (firstFrameLogged) return
        firstFrameLogged = true
        val now = SystemClock.elapsedRealtime()
        EventLog.ev("ui", "what" to "first_frame", "since_process_start_ms" to now - Process.getStartElapsedRealtime(),
            "since_create_ms" to now - createdAt)
    }

    companion object {
        /** Once per process: the first frame after a cold start. */
        @Volatile private var firstFrameLogged = false
    }
}
