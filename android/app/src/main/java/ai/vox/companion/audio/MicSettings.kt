package ai.vox.companion.audio

import android.content.Context
import android.content.SharedPreferences
import org.json.JSONObject

/**
 * The sound-source settings (SharedPreferences "vox", the same file as [ai.vox.companion.Settings], which routes
 * these keys here from the debug `config` op). README "Phone microphone".
 *
 * | key | default | |
 * |---|---|---|
 * | `sound_source` | `pico` | `pico` (the VOX device over Bluetooth), `phone` (the phone's own mic), `usb` (a USB mic plugged into the phone) |
 * | `mic_rate` | 16000 | capture rate: 16000, or 48000 through the extractor's Decimator3 |
 * | `mic_preset` | `auto` | AudioRecord source: `auto` (UNPROCESSED when the phone supports it, else VOICE_RECOGNITION), `unprocessed`, `voice_recognition`, `voice_communication` (the call path: platform echo cancelling), `mic` |
 * | `mic_effects` | `off` | platform pre-processing: `off` (AGC / NS / AEC off), `platform` (as the source attaches them), `aec` (echo canceller only), `aec_ns` (+ noise suppressor) |
 * | `mic_read_ms` | 20 | samples per read (10..40 ms): fewer wake-ups vs a few ms of latency |
 * | `mic_while_disarmed` | false | keep the mic open while disarmed (normally it is released) |
 * | `mic_touch_guard` | true | drop phone-mic sounds that overlap a touch on the screen (a finger on the glass reads as a pop) |
 * | `mic_media_gate` | `speaker` | while media plays, a phone-mic pop / hum must be clearly over the floor ([PhoneGate]): `speaker` (media on the phone's own speaker), `media` (any media playing), `always`, `off` |
 * | `hiss_media_max_centroid_hz` | 6500 | while media plays on the phone's own speaker, a phone / USB mic hiss with a spectral centroid over this (Hz) is `unknown` ([PhoneGate.hissReason]); 0 = off; 0..8000 |
 * | `level_gate` | true | calibration v2's level gate: a phone / USB mic pop, click, hiss or unknown quieter than the mic's calibrated threshold (SNR and level; the spec's default 12 dB / -45 dBFS when uncalibrated) is ignored (`ignored{reason:"below level gate"}`); never the Pico |
 * | `level_gate_offset_db` | 0 | moves both level-gate thresholds, -10..10 dB (+ = stricter: fewer quiet sounds, fewer false ones) |
 * | `mic_dry_run` | false | measurement: phone-mic sounds are logged (`mic_sound`, with text and gate numbers) but never handed to the service, so nothing is acted on |
 */
class MicSettings(private val p: SharedPreferences) {
    constructor(ctx: Context) : this(ctx.getSharedPreferences("vox", Context.MODE_PRIVATE))

    var source: String get() = p.getString("sound_source", PICO)!!.takeIf { it in SOURCES } ?: PICO
        set(v) { require(v in SOURCES) { "sound_source must be one of $SOURCES" }; p.edit().putString("sound_source", v).apply() }
    var rate: Int get() = p.getInt("mic_rate", 16000)
        set(v) { require(v == 16000 || v == 48000) { "mic_rate must be 16000 or 48000" }; p.edit().putInt("mic_rate", v).apply() }
    var preset: String get() = p.getString("mic_preset", "auto")!!
        set(v) { require(v in PRESETS) { "mic_preset must be one of $PRESETS" }; p.edit().putString("mic_preset", v).apply() }
    var readMs: Int get() = p.getInt("mic_read_ms", 20)
        set(v) { require(v in 10..40) { "mic_read_ms must be 10..40" }; p.edit().putInt("mic_read_ms", v).apply() }
    var whileDisarmed: Boolean get() = p.getBoolean("mic_while_disarmed", false)
        set(v) { p.edit().putBoolean("mic_while_disarmed", v).apply() }

    var effects: String get() = p.getString("mic_effects", "off")!!.takeIf { it in EFFECTS } ?: "off"
        set(v) { require(v in EFFECTS) { "mic_effects must be one of $EFFECTS" }; p.edit().putString("mic_effects", v).apply() }
    var dryRun: Boolean get() = p.getBoolean("mic_dry_run", false)
        set(v) { p.edit().putBoolean("mic_dry_run", v).apply() }
    var touchGuard: Boolean get() = p.getBoolean("mic_touch_guard", true)
        set(v) { p.edit().putBoolean("mic_touch_guard", v).apply() }
    var mediaGate: String get() = p.getString("mic_media_gate", "speaker")!!.takeIf { it in MEDIA_GATES } ?: "speaker"
        set(v) { require(v in MEDIA_GATES) { "mic_media_gate must be one of $MEDIA_GATES" }; p.edit().putString("mic_media_gate", v).apply() }

    var hissMediaMaxCentroidHz: Int get() = p.getInt("hiss_media_max_centroid_hz", PhoneGate.HISS_MEDIA_MAX_CENTROID_HZ)
        set(v) { require(v in 0..8000) { "hiss_media_max_centroid_hz must be 0 (off) .. 8000" }; p.edit().putInt("hiss_media_max_centroid_hz", v).apply() }

    var levelGate: Boolean get() = p.getBoolean("level_gate", true)
        set(v) { p.edit().putBoolean("level_gate", v).apply() }
    var levelGateOffsetDb: Int get() = p.getInt("level_gate_offset_db", 0).coerceIn(-10, 10)
        set(v) { require(v in -10..10) { "level_gate_offset_db must be -10..10" }; p.edit().putInt("level_gate_offset_db", v).apply() }

    val usesMic get() = source != PICO

    /** One `config` key; false if it is not one of ours. */
    fun apply(k: String, o: JSONObject): Boolean {
        when (k) {
            "sound_source" -> source = o.getString(k)
            "mic_rate" -> rate = o.getInt(k)
            "mic_preset" -> preset = o.getString(k)
            "mic_read_ms" -> readMs = o.getInt(k)
            "mic_while_disarmed" -> whileDisarmed = o.getBoolean(k)
            "mic_touch_guard" -> touchGuard = o.getBoolean(k)
            "mic_dry_run" -> dryRun = o.getBoolean(k)
            "mic_effects" -> effects = o.getString(k)
            "mic_media_gate" -> mediaGate = o.getString(k)
            "hiss_media_max_centroid_hz" -> hissMediaMaxCentroidHz = o.getInt(k)
            "level_gate" -> levelGate = o.getBoolean(k)
            "level_gate_offset_db" -> levelGateOffsetDb = o.getInt(k)
            else -> return false
        }
        return true
    }

    fun describeInto(o: JSONObject): JSONObject = o.put("sound_source", source).put("mic_rate", rate).put("mic_preset", preset)
        .put("mic_read_ms", readMs).put("mic_while_disarmed", whileDisarmed).put("mic_touch_guard", touchGuard)
        .put("mic_effects", effects).put("mic_dry_run", dryRun).put("mic_media_gate", mediaGate)
        .put("hiss_media_max_centroid_hz", hissMediaMaxCentroidHz)
        .put("level_gate", levelGate).put("level_gate_offset_db", levelGateOffsetDb)

    companion object {
        const val PICO = "pico"
        const val PHONE = "phone"
        const val USB = "usb"
        val SOURCES = listOf(PICO, PHONE, USB)
        val PRESETS = listOf("auto", "unprocessed", "voice_recognition", "voice_communication", "mic")
        val EFFECTS = listOf("off", "platform", "aec", "aec_ns")
        val MEDIA_GATES = listOf("speaker", "media", "always", "off")
        val KEYS = setOf("sound_source", "mic_rate", "mic_preset", "mic_read_ms", "mic_while_disarmed", "mic_touch_guard", "mic_effects",
            "mic_dry_run", "mic_media_gate", "hiss_media_max_centroid_hz", "level_gate", "level_gate_offset_db")
        /** The settings screen's names. */
        val LABELS = mapOf(PICO to "Pico (Bluetooth)", PHONE to "Phone mic", USB to "USB mic")
    }
}
