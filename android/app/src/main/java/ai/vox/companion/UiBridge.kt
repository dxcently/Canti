package ai.vox.companion

import android.app.Activity
import android.content.Intent
import android.os.Handler
import android.os.Looper
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel
import org.json.JSONObject

/**
 * The Kotlin end of the Dart `ChannelBackend` (../ui/lib/src/channel_backend.dart); PROTOCOL.md "UI channel".
 *
 * - `ai.vox/backend` (method channel, main thread): `status`, `setPaused {paused}` and `connectDevice` answer with the
 *   status map ([VoxService.uiStatus], or `{service: false}` when the service is off); `deviceCommand {armed?, mode?,
 *   sleep?}` answers when the device has confirmed or the command failed (`{ok, cmd, result, error?, ms, ...}`);
 *   `openLegacySettings` opens [LegacySettingsActivity].
 * - `ai.vox/events` (event channel): every event-log line, as the JSON string the log writes.
 */
class UiBridge(private val activity: Activity, messenger: BinaryMessenger) {
    private val main = Handler(Looper.getMainLooper())
    private val methods = MethodChannel(messenger, METHODS)
    private val events = EventChannel(messenger, EVENTS)
    @Volatile private var listener: ((JSONObject) -> Unit)? = null

    init {
        methods.setMethodCallHandler { call, result ->
            try {
                when (call.method) {
                    "status" -> result.success(status())
                    "setPaused" -> {
                        val p = call.argument<Boolean>("paused") ?: throw IllegalArgumentException("setPaused needs {paused: bool}")
                        VoxService.instance?.setPaused(p, "app")
                        result.success(status())
                    }
                    "deviceCommand" -> {
                        val c = DeviceLink.Command.from(JSONObject(call.arguments as? Map<*, *> ?: emptyMap<String, Any>()))
                        val svc = VoxService.instance
                        if (svc == null) result.success(mapOf("ok" to false, "result" to "failed", "error" to "the VOX service is off"))
                        else svc.deviceCommand(c) { r -> result.success(r.keys().asSequence().associateWith { k -> r.get(k).takeIf { it != JSONObject.NULL } }) }
                    }
                    "connectDevice" -> {
                        (VoxService.instance ?: throw IllegalArgumentException("the VOX service is off")).connectDevice()
                        result.success(status())
                    }
                    "openLegacySettings" -> {
                        activity.startActivity(Intent(activity, LegacySettingsActivity::class.java))
                        result.success(null)
                    }
                    else -> result.notImplemented()
                }
            } catch (e: Exception) {
                result.error("vox", e.message, null)
            }
        }
        events.setStreamHandler(object : EventChannel.StreamHandler {
            override fun onListen(arguments: Any?, sink: EventChannel.EventSink) {
                removeListener()
                lateinit var l: (JSONObject) -> Unit
                l = { o -> val line = o.toString(); main.post { if (listener === l) sink.success(line) } }
                listener = l
                EventLog.addListener(l)
            }
            override fun onCancel(arguments: Any?) = removeListener()
        })
    }

    private fun removeListener() {
        listener?.let(EventLog::removeListener)
        listener = null
    }

    private fun status(): Map<String, Any?> = VoxService.instance?.uiStatus() ?: mapOf("service" to false)

    fun close() {
        removeListener()
        methods.setMethodCallHandler(null)
        events.setStreamHandler(null)
    }

    companion object {
        const val METHODS = "ai.vox/backend"
        const val EVENTS = "ai.vox/events"
    }
}
