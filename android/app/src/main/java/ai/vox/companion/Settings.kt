package ai.vox.companion

import android.content.Context
import android.content.SharedPreferences
import org.json.JSONObject

/**
 * App settings (SharedPreferences "vox"). The API key lives here and only here: it is entered in MainActivity (or,
 * on debug builds, pushed over the adb-only debug channel), never hard-coded and never written to the event log.
 * TODO: move the key to Android Keystore-backed storage before any non-debug release.
 */
class Settings(ctx: Context) {
    private val p: SharedPreferences = ctx.getSharedPreferences("vox", Context.MODE_PRIVATE)

    var decider: String get() = p.getString("decider", "rules")!!; set(v) = put("decider", v)
    var baseUrl: String get() = p.getString("base_url", "https://api.typesafe.ai")!!; set(v) = put("base_url", v)
    var model: String get() = p.getString("model", "jev-1.13.0")!!; set(v) = put("model", v)
    var apiKey: String get() = p.getString("api_key", "")!!; set(v) = put("api_key", v)
    var minConfidence: Double get() = p.getFloat("min_confidence", 0.5f).toDouble(); set(v) = p.edit().putFloat("min_confidence", v.toFloat()).apply()
    var httpTimeoutMs: Int get() = p.getInt("http_timeout_ms", 2000); set(v) = p.edit().putInt("http_timeout_ms", v).apply()
    /** Max gap between sounds of one sequence, and how long a bound prefix waits (wiki: ~600 ms). */
    var gapMs: Long get() = p.getLong("gap_ms", 600); set(v) = p.edit().putLong("gap_ms", v).apply()
    /** Device-stamp grouping: allowance for a follow-up sound arriving later than the fastest link (PROTOCOL.md). */
    var jitterMs: Long get() = p.getLong("jitter_ms", 150); set(v) = p.edit().putLong("jitter_ms", v).apply()
    var confirmTimeoutMs: Long get() = p.getLong("confirm_timeout_ms", 1500); set(v) = p.edit().putLong("confirm_timeout_ms", v).apply()
    var listenWindowMs: Long get() = p.getLong("listen_window_ms", 6000); set(v) = p.edit().putLong("listen_window_ms", v).apply()
    /** Intent cursor mode: tap the model's pick at or above this confidence, else highlight the top 3. */
    var targetMinConfidence: Double get() = p.getFloat("target_min_confidence", 0.6f).toDouble(); set(v) = p.edit().putFloat("target_min_confidence", v.toFloat()).apply()
    /** Model for the "target" question; empty = the same as `model`. */
    var targetModel: String get() = p.getString("target_model", "")!!; set(v) = put("target_model", v)
    /** How long the highlighted candidates wait for rise/fall/pop before cancelling (reset by each rise/fall). */
    var targetChooseMs: Long get() = p.getLong("target_choose_ms", 6000); set(v) = p.edit().putLong("target_choose_ms", v).apply()
    /** Personalization: a sound matches a class only within (largest within-class distance) x this. */
    var enrollRejectMult: Double get() = p.getFloat("enroll_reject_mult", 1.4f).toDouble(); set(v) = p.edit().putFloat("enroll_reject_mult", v.toFloat()).apply()
    /** The remembered VOX device (Bluetooth address), set on the first good BLE connection; null = none. */
    var bleDevice: String? get() = p.getString("ble_device", null); set(v) = put("ble_device", v)
    var debugSource: Boolean get() = p.getBoolean("debug_source", true); set(v) = p.edit().putBoolean("debug_source", v).apply()
    var profileJson: String? get() = p.getString("profile", null); set(v) = put("profile", v)

    private fun put(k: String, v: String?) = p.edit().putString(k, v).apply()

    /** Apply a debug "config" control message. Unknown keys are rejected. */
    fun apply(o: JSONObject) {
        for (k in o.keys()) when (k) {
            "op", "type", "v" -> {}
            "decider" -> { val v = o.getString(k); require(v in setOf("rules", "model", "hybrid")); decider = v }
            "base_url" -> baseUrl = o.getString(k)
            "model" -> model = o.getString(k)
            "api_key" -> apiKey = o.getString(k)
            "min_confidence" -> minConfidence = o.getDouble(k)
            "http_timeout_ms" -> httpTimeoutMs = o.getInt(k)
            "gap_ms" -> gapMs = o.getLong(k)
            "jitter_ms" -> jitterMs = o.getLong(k)
            "confirm_timeout_ms" -> confirmTimeoutMs = o.getLong(k)
            "listen_window_ms" -> listenWindowMs = o.getLong(k)
            "target_min_confidence" -> targetMinConfidence = o.getDouble(k)
            "target_model" -> targetModel = o.getString(k)
            "target_choose_ms" -> targetChooseMs = o.getLong(k)
            "enroll_reject_mult" -> { val v = o.getDouble(k); require(v > 0) { "enroll_reject_mult must be > 0" }; enrollRejectMult = v }
            "ble_device" -> bleDevice = if (o.isNull(k)) null else o.getString(k).uppercase().also {
                require(BLE_ADDRESS.matches(it)) { "ble_device must be a Bluetooth address like AA:BB:CC:DD:EE:FF, or null" }
            }
            else -> throw IllegalArgumentException("unknown config key '$k'")
        }
    }

    /** Settings as JSON with the API key redacted. */
    fun describe(): JSONObject = JSONObject()
        .put("decider", decider).put("base_url", baseUrl).put("model", model)
        .put("api_key", if (apiKey.isBlank()) "" else "set(${apiKey.length} chars)")
        .put("min_confidence", minConfidence).put("http_timeout_ms", httpTimeoutMs).put("gap_ms", gapMs).put("jitter_ms", jitterMs)
        .put("confirm_timeout_ms", confirmTimeoutMs).put("listen_window_ms", listenWindowMs)
        .put("target_min_confidence", targetMinConfidence).put("target_model", targetModel).put("target_choose_ms", targetChooseMs)
        .put("enroll_reject_mult", enrollRejectMult).put("ble_device", bleDevice ?: JSONObject.NULL)

    companion object { val BLE_ADDRESS = Regex("[0-9A-F]{2}(:[0-9A-F]{2}){5}") }
}
