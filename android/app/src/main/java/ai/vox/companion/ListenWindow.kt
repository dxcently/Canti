package ai.vox.companion

/**
 * The phrase window (pure Kotlin; ListenWindowTest drives it with a fake recognizer and scheduler).
 *
 * open -> the phone mic yields (Canti's capture stops; its foreground service stays) -> after [handoffMs] (only when
 * the capture was running, so the recorder is released first) the recognizer starts -> it ends on its own final
 * result or error, or at the window's end: [PhraseRecognizer.stop], then [graceMs] for the final result, else the last
 * partial -> close exactly once: the recognizer is cancelled (freed), the mic resumes exactly once, [Done] is reported.
 * Anything the recognizer says after the close is ignored.
 */
class ListenWindow(
    private val scheduler: Scheduler,
    private val mic: MicYield?,
    private val handoffMs: Long = HANDOFF_MS,
    private val graceMs: Long = GRACE_MS,
) {
    /** The phone's own capture, paused while a recognizer records (audio/PhoneMicSource). */
    interface MicYield {
        /** Stop capturing for [why]; true if a capture was running (the recorder needs a moment to be released). */
        fun yieldMic(why: String): Boolean
        fun resumeMic(why: String)
    }

    /**
     * How a window ended. [heard] null = nothing to act on. [why]: final | no speech | timeout | error: ... | unavailable
     * | cancelled: ... . [status]: a problem for the user (offline pack missing, permission), else null.
     */
    data class Done(val heard: Heard?, val why: String, val status: String?, val partials: Int, val peakDb: Float?,
                    val readyMs: Long?, val ms: Long, val engine: String, val micYielded: Boolean)

    private inner class Session(val rec: PhraseRecognizer, val onActivity: ((String) -> Unit)?, val onWords: ((String) -> Unit)?, val onDone: (Done) -> Unit) {
        val t0 = scheduler.now()
        val timers = mutableListOf<() -> Unit>()
        var micHeld = false
        var yielded = false   // a mic hold was actually taken (for the log)
        var started = false
        var readyAt: Long? = null
        var lastPartial: String? = null
        var partials = 0
        var peakDb: Float? = null
    }

    private var session: Session? = null
    val isOpen get() = session != null
    val engine get() = session?.rec?.name

    /** [onActivity]: "ready" (the recognizer listens) and "partial" (words so far), while this window is the open one (dictation's silence clock). [onWords]: the partial text and the final best text, only while this window is the open one. */
    fun open(rec: PhraseRecognizer, windowMs: Long, onActivity: ((String) -> Unit)? = null, onWords: ((String) -> Unit)? = null, onDone: (Done) -> Unit) {
        session?.let { finish(it, null, "cancelled: superseded", null) }
        val s = Session(rec, onActivity, onWords, onDone)
        session = s
        rec.status()?.let { st -> finish(s, null, "unavailable", st); return }
        var capturing = false
        if (rec.usesMic && mic != null) { s.micHeld = true; s.yielded = true; capturing = mic.yieldMic("speech window") }
        s.timers += scheduler.schedule(if (capturing) handoffMs else 0) { begin(s) }
        s.timers += scheduler.schedule(windowMs) { timeout(s) }
    }

    /** Close now without acting ([why] e.g. "disarm", "phrase from the device"). */
    fun cancel(why: String) { session?.let { finish(it, null, "cancelled: $why", null) } }

    private fun begin(s: Session) {
        if (session !== s) return
        s.started = true
        try { s.rec.start(listener(s)) }
        catch (e: Exception) { finish(s, null, "error: start failed: ${e.javaClass.simpleName}", "speech recognizer failed to start") }
    }

    private fun timeout(s: Session) {
        if (session !== s) return
        if (!s.started) { finish(s, null, "timeout", null); return }
        try { s.rec.stop() } catch (_: Exception) {}
        s.timers += scheduler.schedule(graceMs) { if (session === s) finish(s, s.partialHeard(), "timeout", null) }
    }

    private fun Session.partialHeard() = lastPartial?.takeIf { it.isNotBlank() }?.let { Heard(listOf(it), partial = true) }

    private fun listener(s: Session) = object : PhraseRecognizer.Listener {
        override fun onReady() { if (session === s) { s.readyAt = scheduler.now(); s.onActivity?.invoke("ready") } }
        override fun onPartial(text: String) { if (session === s) { s.lastPartial = text; s.partials++; if (text.isNotBlank()) { s.onActivity?.invoke("partial"); s.onWords?.invoke(text) } } }
        override fun onLevel(db: Float) { if (session === s && (s.peakDb == null || db > s.peakDb!!)) s.peakDb = db }
        override fun onFinal(heard: Heard) {
            if (session !== s) return
            val h = heard.takeIf { it.hypotheses.any { t -> t.isNotBlank() } } ?: s.partialHeard()
            h?.best?.takeIf { it.isNotBlank() }?.let { s.onWords?.invoke(it) }
            finish(s, h, if (h == null) "no speech" else "final", null)
        }
        override fun onError(code: Int, what: String, status: String?) {
            if (session !== s) return
            // An ordinary miss keeps a partial heard before it; a problem the user must fix acts on nothing.
            finish(s, if (status == null) s.partialHeard() else null, "error: $what", status)
        }
    }

    private fun finish(s: Session, heard: Heard?, why: String, status: String?) {
        if (session !== s) return
        session = null
        s.timers.forEach { it() }; s.timers.clear()
        try { s.rec.cancel() } catch (_: Exception) {}
        if (s.micHeld) { s.micHeld = false; mic?.resumeMic("speech window closed") }
        val now = scheduler.now()
        s.onDone(Done(heard, why, status, s.partials, s.peakDb, s.readyAt?.let { it - s.t0 }, now - s.t0, s.rec.name,
            s.yielded))
    }

    companion object {
        const val HANDOFF_MS = 150L
        const val GRACE_MS = 1500L
    }
}

/**
 * Which Android recognizer to use, and what to tell the user when there is none (pure; ListenWindowTest).
 * The on-device recognizer first (API 31+). Else the default recognizer with EXTRA_PREFER_OFFLINE ("only use an
 * offline engine") - unless `asr_allow_online`, the only way speech may leave the phone. Never a silent cloud fallback.
 */
object AsrPlan {
    enum class Kind { ON_DEVICE, DEFAULT_OFFLINE, DEFAULT_ONLINE, NONE }
    data class Plan(val kind: Kind, val status: String?)

    const val PACK_MISSING = "offline speech pack missing"
    const val NO_PERMISSION = "microphone permission missing"

    fun choose(api: Int, permission: Boolean, onDevice: Boolean, anyRecognizer: Boolean, allowOnline: Boolean,
               packKnownMissing: Boolean = false): Plan = when {
        !permission -> Plan(Kind.NONE, NO_PERMISSION)
        api >= 31 && onDevice && !packKnownMissing -> Plan(Kind.ON_DEVICE, null)
        !anyRecognizer -> Plan(Kind.NONE, if (api >= 31 && onDevice) PACK_MISSING else "no speech recognizer on this phone")
        allowOnline -> Plan(Kind.DEFAULT_ONLINE, null)
        packKnownMissing -> Plan(Kind.NONE, PACK_MISSING)
        else -> Plan(Kind.DEFAULT_OFFLINE, null)
    }

    /**
     * SpeechRecognizer error codes -> (name, status for the user or null for an ordinary miss). Offline-only, a
     * network or server error means the engine wanted the network: the offline pack is missing.
     */
    fun error(code: Int, offlineOnly: Boolean): Pair<String, String?> = when (code) {
        1 -> "network timeout" to if (offlineOnly) PACK_MISSING else "speech needs the network (timed out)"
        2 -> "network" to if (offlineOnly) PACK_MISSING else "speech needs the network"
        3 -> "audio" to "the recognizer could not record (mic busy or blocked in the background)"
        4 -> "server" to if (offlineOnly) PACK_MISSING else "speech server error"
        5 -> "client" to null
        6 -> "no speech" to null
        7 -> "no match" to null
        8 -> "recognizer busy" to "speech recognizer busy"
        9 -> "insufficient permissions" to NO_PERMISSION
        10 -> "too many requests" to "speech recognizer: too many requests"
        11 -> "server disconnected" to if (offlineOnly) PACK_MISSING else "speech server disconnected"
        12 -> "language not supported" to PACK_MISSING
        13 -> "language unavailable" to PACK_MISSING
        14 -> "cannot check support" to null
        else -> "error $code" to null
    }
}
