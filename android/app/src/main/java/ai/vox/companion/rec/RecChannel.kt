package ai.vox.companion.rec

import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodChannel

/**
 * The `ai.vox/recorder` method channel (contract §5), registered by [ai.vox.companion.UiBridge]. It answers every
 * method with the [command] map on the main thread, and pushes `rec_status {map}` and `qr_snapshot {map}` through
 * [statusSink] / [snapshotSink] via `invokeMethod`. With the gate off it answers `{enabled:false}` to every method
 * (the channel is always registered so the Dart side gets an answer, never a MissingPluginException).
 */
class RecChannel(messenger: BinaryMessenger, private val command: (String, Map<String, Any?>) -> Map<String, Any?>) {
    private val methods = MethodChannel(messenger, NAME)
    val statusSink: (Map<String, Any?>) -> Unit = { m -> methods.invokeMethod("rec_status", m) }
    val snapshotSink: (Map<String, Any?>) -> Unit = { m -> methods.invokeMethod("qr_snapshot", m) }

    init {
        methods.setMethodCallHandler { call, result ->
            try {
                if (!DevRec.enabled) result.success(mapOf("enabled" to false))
                else result.success(command(call.method, (call.arguments as? Map<String, Any?>) ?: emptyMap()))
            } catch (e: Exception) {
                result.error("vox", e.message, null)
            }
        }
    }

    fun close() { methods.setMethodCallHandler(null) }

    companion object {
        const val NAME = "ai.vox/recorder"
    }
}
