package ai.vox.companion.audio

import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothClass
import android.media.AudioDeviceInfo
import android.media.AudioManager

/**
 * The phone-mic "speaker" test: is media playing through a speaker the phone mic hears, rather than headphones /
 * earbuds / a hearing aid (where the mic hears nothing)? Shared by [PhoneGate]'s `mic_media_gate` and media-hiss
 * rules and the media lock ([ai.vox.companion.MediaGate]) so both agree on what "media on the phone's own speaker"
 * means.
 *
 * The route is the `USAGE_MEDIA` output devices ([AudioManager.getAudioDevicesForAttributes]). Speaker types are
 * audible to the phone mic; headphone / headset / hearing-aid types are not:
 * - [TYPE_BUILTIN_SPEAKER]: the phone's own speaker.
 * - [TYPE_BLE_SPEAKER]: a Bluetooth (LE Audio) speaker — it plays into the room, unlike earbuds.
 * - [TYPE_BLUETOOTH_A2DP]: classic Bluetooth, where the type alone does not say whether the endpoint is a speaker or
 *   a headset. Its device class (`BluetoothClass.deviceClass`, read from `BluetoothAdapter.getRemoteDevice(address)`)
 *   decides: a loudspeaker / hifi / portable / car / set-top-box / display-and-loudspeaker class is a speaker (lock);
 *   a headphones / wearable-headset / handsfree class is in or on the ear (no lock). An unknown, uncategorised or
 *   missing class (no permission, no adapter, an error) is assumed audible — fail safe, the mic may hear it.
 * - Any other output (HDMI, line out, a USB DAC, casting...) is not a speaker either: only a known speaker type locks.
 *   An empty route (unknown) is the one fail-safe case and counts as audible.
 */
object SpeakerRoute {
    /** Speaker outputs: media here the phone mic can hear. */
    val SPEAKER_TYPES = setOf(AudioDeviceInfo.TYPE_BUILTIN_SPEAKER, AudioDeviceInfo.TYPE_BLE_SPEAKER)
    /** In/on-ear outputs (and a hearing aid): media here the phone mic cannot hear. */
    val HEADPHONE_TYPES = setOf(
        AudioDeviceInfo.TYPE_WIRED_HEADSET, AudioDeviceInfo.TYPE_WIRED_HEADPHONES,
        AudioDeviceInfo.TYPE_BLUETOOTH_A2DP, AudioDeviceInfo.TYPE_BLE_HEADSET,
        AudioDeviceInfo.TYPE_USB_HEADSET, AudioDeviceInfo.TYPE_HEARING_AID)

    /** A2DP device classes that are room speakers: media the mic hears (lock). */
    val BT_SPEAKER_CLASSES = setOf(
        BluetoothClass.Device.AUDIO_VIDEO_LOUDSPEAKER, BluetoothClass.Device.AUDIO_VIDEO_HIFI_AUDIO,
        BluetoothClass.Device.AUDIO_VIDEO_PORTABLE_AUDIO, BluetoothClass.Device.AUDIO_VIDEO_CAR_AUDIO,
        BluetoothClass.Device.AUDIO_VIDEO_VIDEO_DISPLAY_AND_LOUDSPEAKER, BluetoothClass.Device.AUDIO_VIDEO_SET_TOP_BOX)
    /** A2DP device classes in/on the ear: media the mic cannot hear (no lock). Earbuds report headphones or a
     *  wearable headset (there is no separate "headset" class). */
    val BT_HEADPHONE_CLASSES = setOf(
        BluetoothClass.Device.AUDIO_VIDEO_HEADPHONES, BluetoothClass.Device.AUDIO_VIDEO_WEARABLE_HEADSET,
        BluetoothClass.Device.AUDIO_VIDEO_HANDSFREE)

    /** A `TYPE_BLUETOOTH_A2DP` device with `BluetoothClass.deviceClass` [deviceClass] is a speaker the mic hears.
     *  null (unknown / no permission / no adapter) and any class outside the headphone set answer yes — fail safe. */
    fun a2dpSpeaker(deviceClass: Int?): Boolean = deviceClass == null || deviceClass !in BT_HEADPHONE_CLASSES

    /** Media on the `USAGE_MEDIA` output route is audible to the phone mic. [types] are the route's device types;
     *  [a2dpClasses] the `BluetoothClass.deviceClass` of each A2DP device (null = unknown). An empty route (unknown,
     *  or a pre-Android-13 phone) is assumed audible — fail safe, the mic may hear it. */
    fun speakerMedia(types: Set<Int>, a2dpClasses: Set<Int?> = emptySet()): Boolean {
        if (types.isEmpty()) return true
        if (types.any { it in SPEAKER_TYPES }) return true
        if (a2dpClasses.any { a2dpSpeaker(it) }) return true
        return false
    }

    /** Media on [route] is audible to the phone mic (see [speakerMedia]). */
    fun speakerMedia(route: Route): Boolean = speakerMedia(route.types, route.a2dpClasses)

    /** A short name for the current output route, for status: `speaker`, `bt-speaker`, `bt-headphones`, `headphones`,
     *  `other` or `unknown`. An A2DP device with an unknown class is `bt-speaker` (fail safe). */
    fun routeName(types: Set<Int>, a2dpClasses: Set<Int?> = emptySet()): String = when {
        types.isEmpty() -> "unknown"
        types.any { it in SPEAKER_TYPES } -> "speaker"
        types.contains(AudioDeviceInfo.TYPE_BLUETOOTH_A2DP) ->
            if (a2dpClasses.any { it != null && it in BT_HEADPHONE_CLASSES }) "bt-headphones" else "bt-speaker"
        types.any { it in HEADPHONE_TYPES } -> "headphones"
        else -> "other"
    }

    /** A short name for [route] (see [routeName]). */
    fun routeName(route: Route): String = routeName(route.types, route.a2dpClasses)

    /** The `BluetoothClass.deviceClass` of [device] (null: not A2DP, no address, no adapter, no permission, an
     *  error — all fail safe to "speaker" via [a2dpSpeaker]). */
    fun a2dpDeviceClass(device: AudioDeviceInfo): Int? {
        if (device.type != AudioDeviceInfo.TYPE_BLUETOOTH_A2DP) return null
        val address = device.address ?: return null
        return try {
            BluetoothAdapter.getDefaultAdapter()?.getRemoteDevice(address)?.bluetoothClass?.deviceClass
        } catch (_: Exception) { null }
    }

    /** The current `USAGE_MEDIA` output route: its device types and each A2DP device's class. Empty = unknown
     *  (pre-Android-13, or an error). */
    fun mediaRoute(audio: AudioManager): Route {
        if (android.os.Build.VERSION.SDK_INT < 33) return Route(emptySet(), emptySet())
        val infos = try {
            val attrs = android.media.AudioAttributes.Builder().setUsage(android.media.AudioAttributes.USAGE_MEDIA).build()
            audio.getAudioDevicesForAttributes(attrs).toList()
        } catch (_: Exception) { emptyList() }
        return Route(
            infos.map { it.type }.toSet(),
            infos.filter { it.type == AudioDeviceInfo.TYPE_BLUETOOTH_A2DP }.map { a2dpDeviceClass(it) }.toSet())
    }

    /** Media is playing on a speaker the phone mic hears (the `speaker` test, with the playback check). */
    fun playingOnSpeaker(audio: AudioManager): Boolean = audio.isMusicActive && speakerMedia(mediaRoute(audio))

    /** A resolved `USAGE_MEDIA` output route: device types, and the A2DP devices' classes (null = unknown). */
    data class Route(val types: Set<Int>, val a2dpClasses: Set<Int?>)
}
