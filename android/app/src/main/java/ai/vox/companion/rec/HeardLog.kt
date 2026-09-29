package ai.vox.companion.rec

import org.json.JSONObject

/**
 * What Canti heard and did (contract §4). A pure core (JVM-tested on synthetic event lists) plus an EventLog listener
 * adapter installed only while the gate is on. The listener runs inside EventLog's lock: it parses and appends only,
 * never calling EventLog back.
 *
 * The core keeps the last [MAX] of: mic_sound {t (elapsedRealtime), sound, label, t_start_ms, t_end_ms (stream ms),
 * pitch16, f0_hz, dropped, gated, relabel}, resolve {t, n, sequence}, decision {t, n, action, source}, exec {t, n, ok},
 * media_gate {t, kind, dropped}. It is cleared when a newer capture generation starts.
 *
 * Thread safety: EventLog calls the listener on whichever thread logged (main, the executor, binder threads), inside
 * its lock; the recorder and quick record read on main. Every access goes through [lock]; readers work on a copy.
 */
class HeardLog {
    sealed class Entry(val t: Long)

    class Sound(
        t: Long,
        val label: String,
        val sound: Long,
        val tStartMs: Long,
        val tEndMs: Long,
        val pitch16: List<Double>,
        val f0Hz: Double?,
        val dropped: String?,
        val gated: String?,
        val relabel: String?,
    ) : Entry(t)

    class Resolve(t: Long, val n: Int, val sequence: String) : Entry(t)
    class Decision(t: Long, val n: Int, val action: String) : Entry(t)
    class Exec(t: Long, val n: Int, val ok: Boolean) : Entry(t)
    class MediaGate(t: Long, val kind: String, val dropped: Boolean) : Entry(t)

    /** The "what Canti did" for one sound: the resolve that took it and what the app then did. */
    class Did(val n: Int, val sequence: String, val action: String?, val ok: Boolean?)

    private val lock = Any()
    private val entries = ArrayList<Entry>()
    private var gen = -1

    val generation: Int get() = synchronized(lock) { gen }

    /** Clears every entry when a newer capture generation starts (the stream clock restarted; old sounds are foreign).
     *  Generations only grow: an old capture's late state never rolls it back. */
    fun setGen(g: Int) = synchronized(lock) { if (g > gen) { gen = g; entries.clear() } }

    fun append(e: Entry) = synchronized(lock) {
        entries.add(e)
        while (entries.size > MAX) entries.removeAt(0)
    }

    private fun snapshot(): List<Entry> = synchronized(lock) { entries.toList() }

    fun sounds(): List<Sound> = snapshot().filterIsInstance<Sound>()

    /** The sounds of capture [g] whose stream t_end_ms falls in `[fromMs, toMs]`, in time order. */
    fun window(g: Int, fromMs: Long, toMs: Long): List<Sound> = synchronized(lock) {
        if (g != gen) emptyList() else entries.filterIsInstance<Sound>().filter { it.tEndMs in fromMs..toMs }
    }

    /**
     * "What Canti did" for [sound], from the whole log (pure): dropped -> null (ignored); a media_gate{dropped:true} of
     * the same kind within 1 s after -> null (media lock); else the delivered (not dropped) sounds are assigned in time
     * order to the resolves that follow them, each resolve taking the last k delivered sounds since the previous
     * resolve (k = its sequence length); then decision{n}.action and exec{n}.ok. A sound no resolve took within 3 s
     * gets null ("no action"). Gated sounds are delivered (their label shows as "unknown (media)").
     */
    fun did(sound: Sound): Did? = did(sound, snapshot())

    /** The one-line text for [sound]: "HISS → back", "ignored: below level gate", "no action", ... */
    fun didText(sound: Sound, did: Did?): String = didText(sound, did, snapshot())

    companion object {
        const val MAX = 64
        const val MEDIA_LOCK_MS = 1000L
        const val NO_ACTION_MS = 3000L

        /** The pure text for [sound] (see [did]). */
        fun didText(sound: Sound, did: Did?, entries: List<Entry>): String {
            sound.dropped?.let { return "ignored: $it" }
            if (mediaLocked(sound, entries)) return "ignored: media lock"
            val d = did ?: return "no action"
            val label = if (sound.gated != null) "UNKNOWN (MEDIA)" else sound.label.uppercase()
            return "$label → ${d.action ?: "?"}"
        }

        private fun mediaLocked(sound: Sound, entries: List<Entry>): Boolean {
            for (e in entries) if (e is MediaGate && e.dropped && e.kind == sound.label &&
                e.t >= sound.t && e.t - sound.t <= MEDIA_LOCK_MS) return true
            return false
        }

        /** The pure assignment, JVM-tested on synthetic event lists. */
        fun did(sound: Sound, entries: List<Entry>): Did? {
            if (sound.dropped != null) return null
            if (mediaLocked(sound, entries)) return null
            val decision = HashMap<Int, String>()
            val exec = HashMap<Int, Boolean>()
            for (e in entries) {
                if (e is Decision) decision[e.n] = e.action
                if (e is Exec) exec[e.n] = e.ok
            }
            val pending = ArrayList<Sound>()   // delivered sounds not yet taken by a resolve
            var found: Did? = null
            for (e in entries) {
                // delivered = not dropped and not held back by the media lock (those never reach a resolve)
                if (e is Sound && e.dropped == null && !mediaLocked(e, entries)) { pending.add(e); continue }
                if (e is Resolve) {
                    // a resolve only takes sounds from the last NO_ACTION_MS: an older one got no action
                    pending.removeAll { e.t - it.t > NO_ACTION_MS }
                    val k = e.sequence.split(' ').count { it.isNotEmpty() }
                    val take = if (k <= 0) 0 else minOf(k, pending.size)
                    val from = pending.size - take
                    val taken = if (take > 0) pending.subList(from, pending.size).toList() else emptyList()
                    pending.subList(from, pending.size).clear()
                    for (s in taken) {
                        if (s === sound) {
                            found = Did(e.n, e.sequence, decision[e.n], exec[e.n])
                        }
                    }
                }
            }
            // A delivered sound no resolve took within NO_ACTION_MS is "no action" (did stays null).
            return found
        }
    }
}

/**
 * The EventLog listener: parses each event and appends the kept ones to [log]. Installed only while the gate is on.
 * Runs inside EventLog's lock, so it parses and appends only — it never calls EventLog.
 */
class HeardLogListener(private val log: HeardLog) {
    val onEvent: (JSONObject) -> Unit = onEvent@ { o ->
        val e = parse(o) ?: return@onEvent
        log.append(e)
    }

    private fun parse(o: JSONObject): HeardLog.Entry? {
        val t = o.optLong("t")
        return when (o.optString("ev")) {
            "mic_sound" -> HeardLog.Sound(t,
                o.optString("label"), o.optLong("sound"), o.optLong("t_start_ms"), o.optLong("t_end_ms"),
                doubleList(o.optJSONArray("pitch16")), o.opt("f0_hz")?.takeIf { it !== JSONObject.NULL }?.let { (it as Number).toDouble() },
                o.opt("dropped")?.takeIf { it !== JSONObject.NULL }?.toString(),
                o.opt("gated")?.takeIf { it !== JSONObject.NULL }?.toString(),
                o.opt("relabel")?.takeIf { it !== JSONObject.NULL }?.toString())
            "resolve" -> HeardLog.Resolve(t, o.optInt("n"), o.optString("sequence"))
            "decision" -> HeardLog.Decision(t, o.optInt("n"), o.optString("action"))
            "exec" -> HeardLog.Exec(t, o.optInt("n"), o.optBoolean("ok"))
            "media_gate" -> HeardLog.MediaGate(t, o.optString("kind"), o.optBoolean("dropped"))
            else -> null
        }
    }

    private fun doubleList(a: org.json.JSONArray?): List<Double> {
        if (a == null) return emptyList()
        return (0 until a.length()).map { a.getDouble(it) }
    }
}
