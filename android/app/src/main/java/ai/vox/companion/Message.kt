package ai.vox.companion

import org.json.JSONArray
import org.json.JSONObject

/**
 * One message from the VOX device (or the debug source). Format: PROTOCOL.md.
 *
 * `sounds[i]` is the categorical description of the i-th sound (exactly the text after "sound i: " in the model state),
 * `sequence[i]` its gesture label (rise|fall|arch|dip|flat|pop|click|hiss|unknown). Both lists have the same length.
 */
data class FeatureMessage(
    val id: Long?,
    val mode: String,               // gesture | cursor | listening
    val armed: Boolean,
    val sounds: List<String>,
    val sequence: List<String>,
    val phrase: String?,
    val cursor: String? = null,     // optional device-side cursor description; the app normally fills this itself
    val timing: List<Stamp?>? = null, // per-sound device times (PROTOCOL.md "timing"); null = not sent
    val features: List<SoundFeatures?>? = null, // per-sound fingerprint + pitch track (PROTOCOL.md "features"); null = not sent
    val sleeping: Boolean = false,  // the device's last message before it sleeps (always disarms)
) {
    companion object {
        val MODES = setOf("gesture", "cursor", "listening")
        val LABELS = Vocab.CONTOURS.keys + Vocab.DISCRETE.keys + "unknown"

        /** Parses and validates; throws IllegalArgumentException with a readable reason. */
        fun parse(json: JSONObject): FeatureMessage {
            val v = json.optInt("v", 1)
            require(v == 1) { "unsupported protocol version $v" }
            val mode = json.optString("mode", "gesture")
            require(mode in MODES) { "mode must be one of $MODES, got '$mode'" }
            val sounds = strings(json.optJSONArray("sounds"))
            val sequence = strings(json.optJSONArray("sequence")).map { it.lowercase() }
            require(sounds.size == sequence.size) { "sounds (${sounds.size}) and sequence (${sequence.size}) differ in length" }
            require(sequence.size <= 3) { "at most 3 sounds per message" }
            for (s in sequence) require(s in LABELS) { "unknown sound label '$s'" }
            val phrase = if (json.has("phrase") && !json.isNull("phrase")) json.getString("phrase") else null
            val timing = json.optJSONArray("timing")?.let { t ->
                require(t.length() == sequence.size) { "timing (${t.length()}) and sequence (${sequence.size}) differ in length" }
                List(t.length()) { i ->
                    if (t.isNull(i)) null else t.getJSONObject(i).let { o ->
                        val st = Stamp(o.getLong("t_start_ms"), o.getLong("t_end_ms"))
                        require(st.endMs >= st.startMs) { "timing[$i]: t_end_ms before t_start_ms" }
                        st
                    }
                }
            }
            if (timing != null) for (i in 1 until timing.size) {
                val a = timing[i - 1]; val b = timing[i]
                if (a != null && b != null) require(b.startMs >= a.startMs) { "timing[$i] starts before timing[${i - 1}]" }
            }
            val features = if (json.has("features") && !json.isNull("features")) {
                val f = json.optJSONArray("features") ?: throw IllegalArgumentException("features must be an array")
                require(f.length() == sequence.size) { "features (${f.length()}) and sequence (${sequence.size}) differ in length" }
                List(f.length()) { i ->
                    if (f.isNull(i)) null
                    else SoundFeatures.parse(f.optJSONObject(i) ?: throw IllegalArgumentException("features[$i] is not an object"), "features[$i]")
                }
            } else null
            val sleeping = json.optBoolean("sleeping", false)
            // "sleeping" comes with armed:false (PROTOCOL.md); a device going to sleep is never armed, whatever it says.
            val armed = !sleeping && json.optBoolean("armed", true)
            require(!armed || sounds.isNotEmpty() || phrase != null || json.has("mode")) { "empty message" }
            return FeatureMessage(
                id = if (json.has("id")) json.getLong("id") else null,
                mode = mode,
                armed = armed,
                sounds = sounds,
                sequence = sequence,
                phrase = phrase,
                cursor = if (json.has("cursor") && !json.isNull("cursor")) json.getString("cursor") else null,
                timing = timing,
                features = features,
                sleeping = sleeping,
            )
        }

        private fun strings(a: JSONArray?): List<String> =
            if (a == null) emptyList() else List(a.length()) { a.getString(it) }
    }

    fun toJson(): JSONObject = JSONObject().apply {
        put("v", 1)
        id?.let { put("id", it) }
        put("mode", mode)
        put("armed", armed)
        if (sleeping) put("sleeping", true)
        put("sounds", JSONArray(sounds))
        put("sequence", JSONArray(sequence))
        phrase?.let { put("phrase", it) }
        cursor?.let { put("cursor", it) }
        features?.let { f -> put("features", JSONArray(f.map { it?.toJson() ?: JSONObject.NULL })) }
        timing?.let { t -> put("timing", JSONArray(t.map { st -> st?.let { JSONObject().put("t_start_ms", it.startMs).put("t_end_ms", it.endMs) } ?: JSONObject.NULL })) }
    }
}

/** Parsed "key value; key value" fields of a sound line, e.g. loudness -> loud. */
class SoundLine(val text: String) {
    val isHum = text.startsWith("hum that ")
    val isHiss = text.startsWith(Vocab.DISCRETE.getValue("hiss"))
    private val fields: Map<String, String> = text.split("; ").associate { part ->
        val known = listOf("pitch change", "duration", "tone", "loudness", "sounds like")
        val key = known.firstOrNull { part.startsWith("$it ") }
        if (key != null) key to part.removePrefix("$key ") else part to ""
    }
    fun field(name: String): String? = fields[name]
    val loudness get() = field("loudness")
    val duration get() = field("duration")
    val soundsLike get() = field("sounds like")
    val tone get() = field("tone")
    val pitchChange get() = field("pitch change")
}
