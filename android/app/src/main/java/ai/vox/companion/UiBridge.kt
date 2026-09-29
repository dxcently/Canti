package ai.vox.companion

import android.app.Activity
import android.bluetooth.BluetoothAdapter
import android.content.Intent
import android.net.Uri
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
 *   `openLegacySettings` opens [LegacySettingsActivity]. Pairing ([Pairing], Dart `PairScreen`): `requestBluetooth`
 *   asks for the missing Bluetooth permissions and answers with the status map once the dialog is answered;
 *   `enableBluetooth` shows the system's turn-on dialog; `openAppSettings` opens Canti's page in the system settings;
 *   `launchRoute` answers the screen the activity was opened for, once (or null). `scrollStep` answers
 *   `{size, sizes}` (the rise/fall step: small | medium | large, [StepSize]); `setScrollStep {size}` stores it and
 *   answers the same. `cursorSettings` answers `{cursor_speed, cursor_pitch_sens}` (the voice joystick's sliders,
 *   0.5..2.0, default 0.9); `setCursorSettings {cursor_speed?, cursor_pitch_sens?}` stores (clamped) and answers the same.
 *   `levelGateSettings` answers `{level_gate, level_gate_offset_db}` (calibration v2's level gate: on / off, and the
 *   offset -10..10 dB, + = stricter); `setLevelGateSettings {level_gate?, level_gate_offset_db?}` stores and answers the same.
 *   The joystick calibration (VoiceJoystick): `calib_start {source, steps?, resume?}`, `calib_step {step}`, `calib_redo {step}`,
 *   `calib_retry`, `calib_skip`, `calib_save`, `calib_cancel`, `calib_status` answer the calib_status map; `calib_get
 *   {source}` the saved profile or null. To a running UI, Kotlin calls `openRoute {route}` (`pair`, `calibrate`) and
 *   `calib_status {map}` (about every 100 ms while a calibration runs, and after every command) on the same channel.
 * - `ai.vox/events` (event channel): every event-log line, as the JSON string the log writes.
 */
class UiBridge(private val activity: Activity, messenger: BinaryMessenger) {
    private val main = Handler(Looper.getMainLooper())
    private val methods = MethodChannel(messenger, METHODS)
    private val events = EventChannel(messenger, EVENTS)
    @Volatile private var listener: ((JSONObject) -> Unit)? = null
    /** The joystick calibration's `calib_status` pushes to Dart (VoiceJoystick.uiSink; main thread). */
    private val calibSink: (Map<String, Any?>) -> Unit = { m -> methods.invokeMethod("calib_status", m) }

    init {
        methods.setMethodCallHandler { call, result ->
            try {
                when (call.method) {
                    "status" -> result.success(status())
                    "setPaused" -> {
                        val p = call.argument<Boolean>("paused") ?: throw IllegalArgumentException("setPaused needs {paused: bool}")
                        // [phone-mic] a resume from the screen retries a refused foreground-service start (visible now)
                        if (!p) ai.vox.companion.audio.PhoneMicSource.current?.appVisible()
                        VoxService.instance?.setPaused(p, "app")
                        result.success(status())
                    }
                    "deviceCommand" -> {
                        val c = DeviceLink.Command.from(JSONObject(call.arguments as? Map<*, *> ?: emptyMap<String, Any>()))
                        val svc = VoxService.instance
                        if (c.armed == true) ai.vox.companion.audio.PhoneMicSource.current?.appVisible()   // as setPaused(false)
                        if (svc == null) result.success(mapOf("ok" to false, "result" to "failed", "error" to "the Canti service is off"))
                        // Only the status screen's buttons call this: a confirmed mode change is the user's (UserMode).
                        else svc.deviceCommand(c, "status-screen") { r -> result.success(r.keys().asSequence().associateWith { k -> r.get(k).takeIf { it != JSONObject.NULL } }) }
                    }
                    "connectDevice" -> {
                        (VoxService.instance ?: throw IllegalArgumentException("the Canti service is off")).connectDevice()
                        result.success(status())
                    }
                    "requestBluetooth" -> requestBluetooth(result)
                    "enableBluetooth" -> {
                        activity.startActivity(Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE))
                        result.success(null)
                    }
                    "openAppSettings" -> {
                        activity.startActivity(Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                            Uri.fromParts("package", activity.packageName, null)))
                        result.success(null)
                    }
                    "launchRoute" -> { result.success(pendingRoute); pendingRoute = null }
                    "scrollStep" -> result.success(scrollStep())
                    "setScrollStep" -> {
                        val v = call.argument<String>("size")
                        require(v in StepSize.KEYS) { "setScrollStep needs {size: ${StepSize.KEYS.joinToString(" | ")}}" }
                        Settings(activity).scrollStep = v!!
                        EventLog.ev("setting", "scroll_step" to v, "by" to "app")
                        result.success(scrollStep())
                    }
                    "cursorSettings" -> result.success(cursorSettings())
                    "setCursorSettings" -> {
                        val s = Settings(activity)
                        val speed = (call.argument<Any>("cursor_speed") as? Number)?.toDouble()
                        val sens = (call.argument<Any>("cursor_pitch_sens") as? Number)?.toDouble()
                        if (speed != null) s.cursorSpeed = speed
                        if (sens != null) s.cursorPitchSens = sens
                        EventLog.ev("setting", "cursor_speed" to s.cursorSpeed, "cursor_pitch_sens" to s.cursorPitchSens, "by" to "app")
                        VoxService.instance?.joy?.applySliders()
                        result.success(cursorSettings())
                    }
                    "levelGateSettings" -> result.success(levelGateSettings())
                    "setLevelGateSettings" -> {
                        val m = ai.vox.companion.audio.MicSettings(activity)
                        val on = call.argument<Any>("level_gate") as? Boolean
                        val off = (call.argument<Any>("level_gate_offset_db") as? Number)?.toInt()
                        if (on != null) m.levelGate = on
                        if (off != null) m.levelGateOffsetDb = off.coerceIn(-10, 10)
                        EventLog.ev("setting", "level_gate" to m.levelGate, "level_gate_offset_db" to m.levelGateOffsetDb, "by" to "app")
                        result.success(levelGateSettings())
                    }
                    "calib_start", "calib_step", "calib_redo", "calib_retry", "calib_skip", "calib_save", "calib_cancel",
                    "calib_status", "calib_get" -> {
                        @Suppress("UNCHECKED_CAST")
                        val args = (call.arguments as? Map<String, Any?>) ?: emptyMap()
                        val joy = VoxService.instance?.joy
                        result.success(when {
                            joy != null -> joy.calibCommand(call.method, args)
                            call.method == "calib_get" -> null
                            else -> mapOf("active" to false, "calibrated" to false, "error" to "the Canti service is off")
                        })
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
        VoiceJoystick.uiSink = calibSink
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

    // --- pairing ------------------------------------------------------------------------------------------------------

    private var permissionResult: MethodChannel.Result? = null
    private var pendingRoute: String? = null

    private fun requestBluetooth(result: MethodChannel.Result) {
        val missing = BleFeatureSource.missingPermissions(activity)
        if (missing.isEmpty()) { result.success(status()); return }
        permissionResult?.success(status())   // an earlier request that never came back
        permissionResult = result
        EventLog.ev("ble", "what" to "permissions", "asked" to missing.joinToString())
        activity.requestPermissions(missing.toTypedArray(), REQ_BLE)
    }

    /** MainActivity forwards the permission dialog's answer; true if it was ours. */
    fun onPermissionResult(requestCode: Int): Boolean {
        if (requestCode != REQ_BLE) return false
        val missing = BleFeatureSource.missingPermissions(activity)
        // Still missing and no rationale to show: "don't ask again" (or refused twice); only the settings page helps.
        Pairing.permissionBlocked = missing.any { !activity.shouldShowRequestPermissionRationale(it) }
        VoxService.instance?.blePermissionsChanged()
        EventLog.ev("ble", "what" to "permissions", "missing" to missing.joinToString(), "blocked" to Pairing.permissionBlocked)
        permissionResult?.success(status()); permissionResult = null
        return true
    }

    /**
     * The activity was opened for a screen ([Pairing.EXTRA_ROUTE]): kept for `launchRoute` on a cold start, or sent to
     * the running UI with `openRoute`. The extra is consumed so a recreated activity does not open it again.
     */
    fun route(intent: Intent?, running: Boolean) {
        val r = intent?.getStringExtra(Pairing.EXTRA_ROUTE) ?: return
        intent.removeExtra(Pairing.EXTRA_ROUTE)
        if (running) methods.invokeMethod("openRoute", r) else pendingRoute = r
    }

    private fun removeListener() {
        listener?.let(EventLog::removeListener)
        listener = null
    }

    private fun status(): Map<String, Any?> = VoxService.instance?.uiStatus() ?: mapOf("service" to false)

    /** The rise/fall step size (app-side; works with the service off): `{size, sizes}`. */
    private fun scrollStep(): Map<String, Any?> = mapOf("size" to Settings(activity).scrollStep, "sizes" to StepSize.KEYS)

    /** The voice joystick's sliders (app-side; works with the service off): `{cursor_speed, cursor_pitch_sens}`, 0.5..2.0. */
    private fun cursorSettings(): Map<String, Any?> = Settings(activity).let { mapOf("cursor_speed" to it.cursorSpeed, "cursor_pitch_sens" to it.cursorPitchSens) }

    /** Calibration v2's level gate (app-side; read by the mic at each sound): `{level_gate, level_gate_offset_db}`. */
    private fun levelGateSettings(): Map<String, Any?> = ai.vox.companion.audio.MicSettings(activity).let {
        mapOf("level_gate" to it.levelGate, "level_gate_offset_db" to it.levelGateOffsetDb)
    }

    // --- [train] gesture training (GestureTraining.kt; PROTOCOL.md "Gesture training") ---------------------------------
    // Its own method channel `ai.vox/train`, so the Dart side (train_screen.dart) owns its handler: the methods
    // train_status {source?}, train_start {gesture, cell?, source?}, train_record, train_retry, train_skip, train_keep,
    // train_next {record?}, train_goto {gesture, cell, source?}, train_confirm {id, keep, source?}, train_cancel,
    // train_delete {gesture, cell?, source?} answer the train_status map (with
    // `error` when refused, or {service: false} with the service off); Kotlin calls `train_status {map}` on it on every
    // change and about every 100 ms while a take records.
    // Plain vals, set up in declaration order: the init block that uses them must come after them (a `by lazy` declared
    // below an init block that reads it is still null there; that crashed MainActivity on launch).
    private val trainMethods = MethodChannel(messenger, TRAIN)
    private val trainSink: (Map<String, Any?>) -> Unit = { m -> trainMethods.invokeMethod("train_status", m) }

    init { trainInit() }

    private fun trainInit() {
        trainMethods.setMethodCallHandler { call, result ->
            try {
                if (!call.method.startsWith("train_")) { result.notImplemented(); return@setMethodCallHandler }
                @Suppress("UNCHECKED_CAST")
                val args = (call.arguments as? Map<String, Any?>) ?: emptyMap()
                val t = VoxService.instance?.train
                result.success(t?.command(call.method, args) ?: mapOf("service" to false, "active" to false,
                    "error" to "the Canti service is off"))
            } catch (e: Exception) {
                result.error("vox", e.message, null)
            }
        }
        VoxService.trainSink = trainSink
    }

    fun close() {
        // [train] the screen is gone: end an open training session (its sounds would otherwise never act)
        trainMethods.setMethodCallHandler(null)
        if (VoxService.trainSink === trainSink) { VoxService.trainSink = null; VoxService.instance?.train?.cancel("ui closed") }
        removeListener()
        // A calibration left open makes Canti deaf (every mic sound is dropped as "calibrating"): this screen's one ends
        // with it (another Canti screen that took over the calibration pushes keeps its run).
        if (VoiceJoystick.uiSink === calibSink) { VoiceJoystick.uiSink = null; VoxService.instance?.joy?.cancelCalibration("ui closed") }
        permissionResult?.success(mapOf("service" to (VoxService.instance != null))); permissionResult = null
        methods.setMethodCallHandler(null)
        events.setStreamHandler(null)
    }

    companion object {
        const val METHODS = "ai.vox/backend"
        const val EVENTS = "ai.vox/events"
        const val TRAIN = "ai.vox/train"   // [train]
        const val REQ_BLE = 7310
    }
}
