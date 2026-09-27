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
    val by: String? = null,         // "button": the user changed the mode on the device's button (a state message)
    // [train] per-sound gate reason ("media", "media_hiss"; null = not gated): a phone-mic gate turned the sound into
    // `unknown` on purpose to keep it from acting; personalization never relabels it (PROTOCOL.md "gated"). null = not sent
    val gated: List<String?>? = null,
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
                        val st = Stamp(o.getLong("t_start_ms"), o.getLong("t_end_ms"),
                            if (o.has("sound") && !o.isNull("sound")) o.getLong("sound") else null, o.optBoolean("held", false))
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
            // [train] gated
            val gated = if (json.has("gated") && !json.isNull("gated")) {
                val a = json.optJSONArray("gated") ?: throw IllegalArgumentException("gated must be an array")
                require(a.length() == sequence.size) { "gated (${a.length()}) and sequence (${sequence.size}) differ in length" }
                List(a.length()) { i -> if (a.isNull(i)) null else a.getString(i) }
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
                by = if (json.has("by") && !json.isNull("by")) json.getString("by") else null,
                gated = gated,   // [train]
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
        by?.let { put("by", it) }
        if (sleeping) put("sleeping", true)
        put("sounds", JSONArray(sounds))
        put("sequence", JSONArray(sequence))
        phrase?.let { put("phrase", it) }
        cursor?.let { put("cursor", it) }
        features?.let { f -> put("features", JSONArray(f.map { it?.toJson() ?: JSONObject.NULL })) }
        timing?.let { t -> put("timing", JSONArray(t.map { st -> st?.let {
            JSONObject().put("t_start_ms", it.startMs).put("t_end_ms", it.endMs).apply {
                it.sound?.let { id -> put("sound", id) }
                if (it.held) put("held", true)
            } } ?: JSONObject.NULL })) }
        gated?.let { g -> put("gated", JSONArray(g.map { it ?: JSONObject.NULL })) }   // [train]
    }
}

/**
 * A live hold message (PROTOCOL.md "Hold messages"): `start` while a steady tone is being held, `end` when it stops.
 * [sound] ties it to the sound's feature message (`timing[i].sound`). A glide-and-hold start ([isGlide]) carries
 * `"from":"glide"` and [dir] up / down: a rise or fall whose end note is being held.
 */
data class HoldMessage(
    val id: Long?,
    val kind: String,          // start | pitch | end
    val sound: Long,
    val tStartMs: Long,
    val tMs: Long,
    val f0Hz: Double? = null,
    val flat: Boolean = true,  // start only; false = the sound moved, then settled: never acts (unless a glide)
    val from: String? = null,  // start only: "glide" = glide-and-hold; absent = a steady hum
    val dir: String? = null,   // start only, glide: "up" | "down"
) {
    val isGlide get() = kind == "start" && from == "glide"

    companion object {
        fun isHold(json: JSONObject) = json.has("hold")

        fun parse(json: JSONObject): HoldMessage {
            val v = json.optInt("v", 1)
            require(v == 1) { "unsupported protocol version $v" }
            val kind = json.getString("hold")
            require(kind == "start" || kind == "end" || kind == "pitch") { "hold must be start, pitch or end, got '$kind'" }
            if (kind == "pitch") {
                // periodic pitch report while held (PROTOCOL.md "Hold pitch"); t_start_ms is optional
                require(json.has("sound") && json.has("t_ms") && json.has("f0_hz")) { "hold pitch needs sound, t_ms and f0_hz" }
            } else require(json.has("sound") && json.has("t_start_ms") && json.has("t_ms")) { "hold needs sound, t_start_ms and t_ms" }
            val m = HoldMessage(
                id = if (json.has("id")) json.getLong("id") else null,
                kind = kind, sound = json.getLong("sound"), tMs = json.getLong("t_ms"),
                tStartMs = if (kind == "pitch" && !json.has("t_start_ms")) json.getLong("t_ms") else json.getLong("t_start_ms"),
                f0Hz = if (json.has("f0_hz") && !json.isNull("f0_hz")) json.getDouble("f0_hz") else null,
                flat = json.optBoolean("flat", true),
                from = if (kind == "start" && json.has("from") && !json.isNull("from")) json.getString("from") else null,
                dir = if (kind == "start" && json.has("dir") && !json.isNull("dir")) json.getString("dir") else null,
            )
            require(m.tMs >= m.tStartMs) { "hold: t_ms before t_start_ms" }
            if (m.from == "glide") require(m.dir == "up" || m.dir == "down") { "glide hold needs dir up or down, got '${m.dir}'" }
            return m
        }
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
