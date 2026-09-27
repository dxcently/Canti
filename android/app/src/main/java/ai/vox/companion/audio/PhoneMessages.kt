package ai.vox.companion.audio

import org.json.JSONArray
import org.json.JSONObject

/**
 * Native extractor messages ([VxNative]) -> protocol messages (PROTOCOL.md), exactly what the Pico's firmware sends
 * for the same sound (`vox_state.cpp` `send_sound`): one sound per message, `sounds`/`sequence` of length 1, `timing`
 * on the source's clock, the fp1 `features` entry. The service then parses them with FeatureMessage.parse like any
 * BLE message, so the sequencer, personalization, decider and bindings see no difference.
 *
 * Clock: the extractor counts stream milliseconds from the first sample; [baseMs] maps that to the phone's
 * monotonic clock (System.nanoTime in ms) at stream time 0, so sounds keep increasing across mic restarts and the
 * sequencer's lag estimate (arrival - t_end) is the real pipeline latency.
 *
 * Hold messages (`kind` hold_start / hold_end) map to PROTOCOL.md "Hold messages" once the C++ port emits them; the
 * native fields are assumed to be named like the protocol's (sound, t_start_ms, t_ms, f0_hz, flat).
 */
object PhoneMessages {
    /** The protocol message for one native message, or null for a kind this app does not know (logged by the caller). */
    fun toProtocol(native: JSONObject, id: Long, mode: String, baseMs: Long): JSONObject? = when (native.optString("kind")) {
        "sound" -> JSONObject()
            .put("v", 1).put("id", id).put("mode", mode).put("armed", true)
            .put("sounds", JSONArray().put(native.getString("text")))
            .put("sequence", JSONArray().put(native.getString("label")))
            .put("timing", JSONArray().put(JSONObject()
                .put("t_start_ms", baseMs + native.getLong("t_start_ms"))
                .put("t_end_ms", baseMs + native.getLong("t_end_ms"))
                .apply {
                    if (native.has("sound")) put("sound", native.getLong("sound"))
                    if (native.optBoolean("held", false)) put("held", true)
                }))
            .put("phrase", JSONObject.NULL).put("cursor", JSONObject.NULL)
            .put("features", JSONArray().put(native.optJSONObject("features") ?: JSONObject.NULL))
        "hold_start", "hold_end" -> JSONObject()
            .put("v", 1).put("id", id).put("hold", if (native.getString("kind") == "hold_start") "start" else "end")
            .put("sound", native.getLong("sound"))
            .put("t_start_ms", baseMs + native.getLong("t_start_ms"))
            .put("t_ms", baseMs + native.getLong("t_ms"))
            .apply {
                if (native.has("f0_hz")) put("f0_hz", native.getDouble("f0_hz"))
                if (native.has("flat")) put("flat", native.getBoolean("flat"))
            }
        else -> null
    }
}
