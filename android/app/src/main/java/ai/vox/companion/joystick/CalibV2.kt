package ai.vox.companion.joystick

import org.json.JSONArray
import org.json.JSONObject

/*
 * Calibration v2's pure rules (a port of extractor/joystick_core.py: example, derive_gate, gate_reason,
 * derive_click_pop, click_pop_vote, relabel), checked against the prototype (golden "calib_v2").
 *
 * The level gate: an extractor pop / click / hiss from the phone or a USB mic (never the Pico) must reach
 * min_snr_db over the floor AND min_level_dbfs, or it is ignored ("below level gate"). One pair per mic, from the
 * person's weakest calibrated pop / click / hiss minus a margin, raised to the room's loudest transient plus a margin,
 * never above the weakest (a calibrated sound always passes); the spec's default until the clicks step has examples.
 * The click / pop rule: pop <-> click relabelled only when every feature that separates the person's own pops and
 * clicks agrees. Pure JVM.
 */

/** One calibrated sound: the extractor's numbers for it (its gate raw), nothing else. */
data class SoundExample(
    val label: String, val durMs: Double?, val snrDb: Double?, val levelDb: Double?, val lfRatio: Double?,
    val peakCentroidHz: Double?,
) {
    fun feature(f: String): Double? = when (f) {
        "dur_ms" -> durMs; "snr_db" -> snrDb; "level_db" -> levelDb; "lf_ratio" -> lfRatio; "peak_centroid_hz" -> peakCentroidHz
        else -> null
    }

    fun toJson(): JSONObject {
        fun o(v: Double?): Any = v ?: JSONObject.NULL
        return JSONObject().put("label", label).put("dur_ms", o(durMs)).put("snr_db", o(snrDb)).put("level_db", o(levelDb))
            .put("lf_ratio", o(lfRatio)).put("peak_centroid_hz", o(peakCentroidHz))
    }

    companion object {
        /** joystick_core.example: the kept numbers of one extractor event, rounded (lf_ratio to 4, the rest to 2). */
        fun of(label: String, raw: Map<String, Double?>): SoundExample {
            fun r(k: String, n: Int) = raw[k]?.takeUnless { it.isNaN() }?.let { PyFmt.round(it, n) }
            return SoundExample(label, r("dur_ms", 2), r("snr_db", 2), r("level_db", 2), r("lf_ratio", 4), r("peak_centroid_hz", 2))
        }

        /** The gate numbers of a native event's `gate` object (missing / null / NaN = null). */
        fun raw(g: JSONObject?): Map<String, Double?> = FEATURES_ALL.associateWith { k ->
            if (g == null || !g.has(k) || g.isNull(k)) null else g.optDouble(k).takeUnless { it.isNaN() }
        }

        fun fromJson(j: JSONObject): SoundExample {
            fun d(k: String) = if (!j.has(k) || j.isNull(k)) null else j.getDouble(k)
            return SoundExample(j.optString("label", "?"), d("dur_ms"), d("snr_db"), d("level_db"), d("lf_ratio"), d("peak_centroid_hz"))
        }

        fun listJson(l: List<SoundExample>?): Any = l?.let { JSONArray(it.map(SoundExample::toJson)) } ?: JSONObject.NULL
        fun listFrom(a: JSONArray?): List<SoundExample>? = a?.let { (0 until it.length()).map { i -> fromJson(it.getJSONObject(i)) } }

        val FEATURES_ALL = listOf("dur_ms", "snr_db", "level_db", "lf_ratio", "peak_centroid_hz")
    }
}

/** The whistle step's range (st on the 55 Hz scale): its home (the glide's median) and the split from the voice. */
data class WhistleRange(val loSt: Double, val hiSt: Double, val homeSt: Double, val splitSt: Double) {
    fun toJson(): JSONObject = JSONObject().put("lo_st", loSt).put("hi_st", hiSt).put("home_st", homeSt).put("split_st", splitSt)

    companion object {
        fun fromJson(j: JSONObject) = WhistleRange(j.getDouble("lo_st"), j.getDouble("hi_st"), j.getDouble("home_st"), j.getDouble("split_st"))
    }
}

/** The room step: the ticks' median level (the floor, dBFS) and the loudest discrete transient in 3 s of quiet. */
data class RoomNoise(val floorDbfs: Double?, val transientSnrDb: Double?, val transientLevelDbfs: Double?, val transients: Int) {
    fun toJson(): JSONObject {
        fun o(v: Double?): Any = v ?: JSONObject.NULL
        return JSONObject().put("floor_dbfs", o(floorDbfs)).put("transient_snr_db", o(transientSnrDb))
            .put("transient_level_dbfs", o(transientLevelDbfs)).put("transients", transients)
    }

    companion object {
        fun fromJson(j: JSONObject): RoomNoise {
            fun d(k: String) = if (!j.has(k) || j.isNull(k)) null else j.getDouble(k)
            return RoomNoise(d("floor_dbfs"), d("transient_snr_db"), d("transient_level_dbfs"), j.optInt("transients", 0))
        }
    }
}

/** The per-mic level gate: both thresholds; from "calibration" (n examples, the weakest) or the spec's "default". */
data class LevelGate(val minSnrDb: Double, val minLevelDbfs: Double, val from: String, val n: Int,
                     val weakestSnrDb: Double? = null, val weakestLevelDbfs: Double? = null) {
    fun toJson(): JSONObject = JSONObject().put("min_snr_db", minSnrDb).put("min_level_dbfs", minLevelDbfs).put("from", from).put("n", n)
        .apply { weakestSnrDb?.let { put("weakest_snr_db", it) }; weakestLevelDbfs?.let { put("weakest_level_dbfs", it) } }
}

/** Why a sound was ignored by the level gate (logged: `ignored{reason:"below level gate", ...}`). */
data class GateDrop(val label: String, val snrDb: Double, val levelDbfs: Double, val minSnrDb: Double, val minLevelDbfs: Double,
                    val from: String) {
    val reason get() = REASON
    fun fields(): Array<Pair<String, Any?>> = arrayOf("reason" to REASON, "label" to label, "snr_db" to snrDb, "level_dbfs" to levelDbfs,
        "min_snr_db" to minSnrDb, "min_level_dbfs" to minLevelDbfs, "from" to from)

    companion object { const val REASON = "below level gate" }
}

/** The per-person click / pop rule: per separating feature, its threshold and whether pops sit above it. */
data class ClickPopRule(val features: Map<String, Pair<Double, Boolean>>, val minVotes: Int) {
    fun toJson(): JSONObject = JSONObject()
        .put("features", JSONObject().also { j -> features.forEach { (f, t) -> j.put(f, JSONObject().put("thr", t.first).put("pop_above", t.second)) } })
        .put("min_votes", minVotes)

    companion object {
        fun fromJson(j: JSONObject): ClickPopRule {
            val f = j.getJSONObject("features")
            return ClickPopRule(f.keys().asSequence().associateWith { k -> f.getJSONObject(k).let { it.getDouble("thr") to it.getBoolean("pop_above") } },
                j.getInt("min_votes"))
        }
    }
}

/** A relabel: from -> to, and each separating feature's vote. */
data class Relabel(val from: String, val to: String, val votes: Map<String, String>)

/** The phone / USB mic's calibration-v2 verdict on one extractor sound: dropped by the level gate, or its label after
 *  the click / pop relabel. [deliverable] false = never handed to the service (so never to Personal.rewrite). */
data class PhoneVerdict(val drop: GateDrop?, val relabel: Relabel?, val label: String) {
    val deliverable get() = drop == null
}

object CalibV2 {
    val GATE_LABELS = setOf("pop", "click", "hiss")
    /** What the app gates on the phone / USB mic: the discrete sounds and `unknown`, which the trained-gesture relabel
     *  (Personal.rewrite, after the mic) could otherwise turn into a click or a pop (a quiet keyboard tap). */
    val PHONE_GATE_LABELS = GATE_LABELS + "unknown"
    val CLICK_POP_FEATURES = listOf("dur_ms", "snr_db", "level_db", "lf_ratio")

    fun defaultGate(spec: JoySpec) = LevelGate(spec.gateDefaultSnrDb, spec.gateDefaultLevelDbfs, "default", 0)

    /** joystick_core.derive_gate: examples are the pops, clicks and hiss steps' (in that order). */
    fun deriveGate(pops: List<SoundExample>?, clicks: List<SoundExample>?, hiss: List<SoundExample>?, room: RoomNoise?,
                   spec: JoySpec): LevelGate {
        val ex = listOf(pops, clicks, hiss).flatMap { it ?: emptyList() }.filter { it.snrDb != null && it.levelDb != null }
        if (ex.isEmpty() || clicks.orEmpty().none { it.snrDb != null }) return defaultGate(spec)
        val ws = ex.minOf { it.snrDb!! }; val wl = ex.minOf { it.levelDb!! }
        var s = ws - spec.gateMarginSnrDb
        var lv = wl - spec.gateMarginLevelDb
        room?.transientSnrDb?.let { s = maxOf(s, it + spec.gateRoomMarginDb) }
        room?.transientLevelDbfs?.let { lv = maxOf(lv, it + spec.gateRoomMarginDb) }
        s = minOf(s, ws - spec.gateCapBelowWeakestDb); lv = minOf(lv, wl - spec.gateCapBelowWeakestDb)
        return LevelGate(PyFmt.round(s, 2), PyFmt.round(lv, 2), "calibration", ex.size, PyFmt.round(ws, 2), PyFmt.round(wl, 2))
    }

    /** joystick_core.gate_reason: null = the sound passes; [offsetDb] raises both thresholds (+ = stricter). */
    fun gateReason(gate: LevelGate?, label: String, snrDb: Double?, levelDb: Double?, offsetDb: Double = 0.0,
                   labels: Set<String> = GATE_LABELS): GateDrop? {
        if (gate == null || label !in labels || snrDb == null || levelDb == null || snrDb.isNaN() || levelDb.isNaN()) return null
        val ms = gate.minSnrDb + offsetDb; val ml = gate.minLevelDbfs + offsetDb
        if (snrDb >= ms && levelDb >= ml) return null
        return GateDrop(label, PyFmt.round(snrDb, 2), PyFmt.round(levelDb, 2), PyFmt.round(ms, 2), PyFmt.round(ml, 2), gate.from)
    }

    /** joystick_core.derive_click_pop: null when fewer than min_votes features separate the person's pops and clicks. */
    fun deriveClickPop(pops: List<SoundExample>?, clicks: List<SoundExample>?, spec: JoySpec): ClickPopRule? {
        val feats = LinkedHashMap<String, Pair<Double, Boolean>>()
        for ((f, gap) in spec.clickPopMinGap) {
            val p = pops.orEmpty().mapNotNull { it.feature(f) }
            val k = clicks.orEmpty().mapNotNull { it.feature(f) }
            if (p.size < spec.clickPopMinEach || k.size < spec.clickPopMinEach) continue
            if (p.min() - k.max() >= gap) feats[f] = PyFmt.round((p.min() + k.max()) / 2, 4) to true
            else if (k.min() - p.max() >= gap) feats[f] = PyFmt.round((k.min() + p.max()) / 2, 4) to false
        }
        return if (feats.size >= spec.clickPopMinVotes) ClickPopRule(feats, spec.clickPopMinVotes) else null
    }

    /** joystick_core.click_pop_vote: the rule's label when enough separating features have a value and all agree. */
    fun vote(rule: ClickPopRule?, raw: Map<String, Double?>): Pair<String, Map<String, String>>? {
        if (rule == null) return null
        val votes = LinkedHashMap<String, String>()
        for ((f, t) in rule.features) {
            val v = raw[f]?.takeUnless { it.isNaN() } ?: continue
            votes[f] = if ((v > t.first) == t.second) "pop" else "click"
        }
        if (votes.size < rule.minVotes || votes.values.toSet().size != 1) return null
        return votes.values.first() to votes
    }

    /**
     * PhoneMicSource.judge's calibration-v2 step, before the joystick filter and before the service (whose
     * personalization, Personal.rewrite, may turn any delivered sound, `unknown` included, into a trained gesture):
     * the level gate over [PHONE_GATE_LABELS] (off for ticks, touch-dropped sounds, or [on] false), then the click / pop
     * relabel of what passed. [g] is the native event's `gate` object.
     */
    fun phoneVerdict(label: String, g: JSONObject?, gate: LevelGate?, rule: ClickPopRule?, on: Boolean = true,
                     offsetDb: Double = 0.0, tick: Boolean = false, touched: Boolean = false): PhoneVerdict {
        if (tick || touched) return PhoneVerdict(null, null, label)
        val raw = SoundExample.raw(g)
        val drop = if (on) gateReason(gate, label, raw["snr_db"], raw["level_db"], offsetDb, PHONE_GATE_LABELS) else null
        if (drop != null) return PhoneVerdict(drop, null, label)
        val rl = relabel(rule, label, raw)
        return PhoneVerdict(null, rl, rl?.to ?: label)
    }

    /** joystick_core.relabel: pop <-> click only, only when the rule is confident and says the other one. */
    fun relabel(rule: ClickPopRule?, label: String, raw: Map<String, Double?>): Relabel? {
        if (label != "pop" && label != "click") return null
        val (to, votes) = vote(rule, raw) ?: return null
        return if (to == label) null else Relabel(label, to, votes)
    }
}
