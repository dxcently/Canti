package ai.vox.companion.audio

/**
 * What runs for a given sound source and app state (pure, JVM-tested). One source at a time:
 * - `pico`: the BLE link only; the mic, its foreground service and notification are off.
 * - `phone` / `usb`: no BLE link. The foreground service (type microphone, notification "Canti is listening") runs
 *   as long as the source is selected and allowed, so the mic can restart from the background after a pause or a
 *   USB plug; the mic itself (AudioRecord) is open only while [Inputs.active] (not paused, armed or
 *   `mic_while_disarmed`) and, for `usb`, while a USB input is plugged in.
 */
object SourcePolicy {
    data class Inputs(
        val source: String,
        val active: Boolean,           // !paused && (armed || mic_while_disarmed)
        val permission: Boolean,       // RECORD_AUDIO granted
        val usbPresent: Boolean,       // a USB input device is attached
        val nativeOk: Boolean,         // libvx_jni loaded
    )

    enum class Route { BUILTIN, USB }

    data class Plan(val ble: Boolean, val service: Boolean, val capture: Boolean, val route: Route?, val state: String)

    fun plan(i: Inputs): Plan = when {
        i.source == MicSettings.PICO -> Plan(ble = true, service = false, capture = false, route = null, state = "off")
        !i.nativeOk -> Plan(false, false, false, null, "unavailable: native extractor not loaded")
        !i.permission -> Plan(false, false, false, null, "needs microphone permission")
        i.source == MicSettings.USB && !i.usbPresent -> Plan(false, true, false, null, "waiting for a USB mic")
        !i.active -> Plan(false, true, false, null, "paused")
        else -> Plan(false, true, true, if (i.source == MicSettings.USB) Route.USB else Route.BUILTIN, "listening")
    }
}
