package ai.vox.companion

/** Minimal timer abstraction so the sequencer is unit-testable without Android. */
interface Scheduler {
    fun now(): Long
    fun schedule(delayMs: Long, task: () -> Unit): () -> Unit   // returns a cancel function
}

/**
 * When a sound happened, on the DEVICE's monotonic clock (ms). Differences are meaningful, absolute values are not.
 * [sound] = the device's per-boot sound id and [held] = a `hold start` was sent for it (PROTOCOL.md "Hold messages").
 */
data class Stamp(val startMs: Long, val endMs: Long, val sound: Long? = null, val held: Boolean = false)

/**
 * Groups sounds into sequences (sound phrases) and decides WHEN to resolve them.
 *
 * Timing rule: act at once, unless a multi-sound sequence bound in the active profile (for this app and mode) starts
 * with the sounds heard so far. Only then wait for the next sound. With the default bindings "click" waits (for
 * "click click" / "click hiss") and "pop" waits (for "pop pop", listen for a phrase: a lone pop taps after the gap).
 *
 * Grouping clock:
 *  - "device" (every sound carries a [Stamp]): two sounds belong together iff the device gap
 *    (next.start - previous.end) is at most gapMs. Arrival jitter (BLE retries, a stall that delivers two sounds in a
 *    burst) cannot merge or split a sequence while the follow-up is still pending. The wait deadline is compensated
 *    for how late the waiting sound arrived: lag = its arrival offset minus the smallest recent offset (arrival time
 *    minus device end time; the clock offset plus the fastest link latency), so the wait is max(0, gap - lag) + jitterMs.
 *    jitterMs is the allowance for the follow-up itself arriving later than the fastest link.
 *  - "arrival" (fallback when stamps are missing): sounds that arrive while the previous one is still waiting belong
 *    together; the wait is gapMs from arrival.
 * The resolved [Pending] says which clock was used, the device gaps, and why it ended.
 *
 * Absorbed tails: a sequence left out of the bound set because a shorter prefix already does the same thing (default
 * "hiss click" = back = "hiss", [Profile.absorbedSequences]) acts on its prefix at once; the rest of it, if it follows
 * within the gap (same clock rules), is absorbed ([onAbsorb]) instead of starting a new group. So "hiss click" is one
 * back, and "hiss click click" is back and then a lone click, not back + home.
 */
class Sequencer(
    private val scheduler: Scheduler,
    private val gapMs: () -> Long,
    private val jitterMs: () -> Long = { 150L },
    private val maxLen: Int = 3,
    private val onResolve: (Pending) -> Unit,
    private val onWait: (Pending, List<List<String>>, Long) -> Unit = { _, _, _ -> },
    /** A sound absorbed as the tail of [Pending] (already resolved); the device gap, or null on the arrival clock. */
    private val onAbsorb: (Pending, String, Long?) -> Unit = { _, _, _ -> },
) {
    data class Pending(
        val mode: String,
        val app: String,
        val sounds: MutableList<String> = mutableListOf(),
        val sequence: MutableList<String> = mutableListOf(),
        val stamps: MutableList<Stamp?> = mutableListOf(),
        val gapsMs: MutableList<Long> = mutableListOf(),     // device gaps between consecutive sounds
        var firstAt: Long = 0,
        var waited: Boolean = false,
        var endedBy: String = "",   // no-continuation | max-length | timeout | device-gap | device-clock-reset | flush | context-change
        var note: String? = null,
    ) {
        /** "device" if every sound was stamped, else "arrival". */
        val clock get() = if (stamps.isNotEmpty() && stamps.all { it != null }) "device" else "arrival"
    }

    private var pending: Pending? = null
    private var cancelTimer: (() -> Unit)? = null

    // Arrival offsets (local arrival ms - device end ms) of recent stamped sounds; min = clock offset + fastest link.
    private val offsets = ArrayDeque<Long>()
    private var lastDeviceEnd: Long? = null
    private var lastResolved: Pending? = null
    private var lastResolvedEnd: Stamp? = null   // its last sound, or the last sound absorbed as its tail

    /** After a group resolved: the longer sequences whose rest may still be absorbed. */
    private class Tail(val mode: String, val app: String, val done: Pending, var tails: List<List<String>>, var matched: Int,
                       var lastStamp: Stamp?, var lastAt: Long)
    private var tail: Tail? = null
    private var absorb: Set<List<String>> = emptySet()

    val isWaiting get() = pending != null

    /**
     * Add sounds for [app] in [mode]; [bound] = the bound sequences for that app and mode; [stamps] = device times
     * aligned with [sequence] (null, or null entries, when the device sent none); [absorb] = the sequences whose tail
     * is absorbed after their prefix acted ([Profile.absorbedSequences]).
     * A mode or app change resolves what was pending first.
     */
    fun add(mode: String, app: String, sounds: List<String>, sequence: List<String>, bound: Set<List<String>>,
            stamps: List<Stamp?>? = null, absorb: Set<List<String>> = emptySet()) {
        pending?.let { if (it.mode != mode || it.app != app) resolveNow("context-change") }
        this.absorb = absorb
        val now = scheduler.now()
        for (i in sequence.indices) {
            val st = stamps?.getOrNull(i)
            var note: String? = null
            if (st != null) note = observe(now, st)
            if (pending == null && note == null && absorbed(mode, app, sequence[i], st, now)) continue
            tail = null
            pending?.let { p ->
                val prev = p.stamps.lastOrNull()
                if (st != null && prev != null) {
                    val gap = st.startMs - prev.endMs
                    when {
                        gap < -CLOCK_SLACK_MS -> { resolveNow("device-clock-reset"); note = "device clock went back ${-gap} ms" }
                        gap > gapMs() -> { resolveNow("device-gap"); note = "split: device gap $gap ms > ${gapMs()} ms" }
                        else -> p.gapsMs += gap
                    }
                }
            }
            if (pending == null && st != null) {
                // Arrived after the previous group had already been resolved although the device says it was close.
                val lr = lastResolved
                val lrEnd = lastResolvedEnd
                if (lr != null && lrEnd != null && lr.mode == mode && lr.app == app) {
                    val gap = st.startMs - lrEnd.endMs
                    if (gap in 0..gapMs() && note == null) note = "late: device gap $gap ms, but ${lr.sequence.joinToString(" ")} had already resolved (${lr.endedBy})"
                }
            }
            val p = pending ?: Pending(mode, app, firstAt = now).also { pending = it }
            if (note != null && p.note == null) p.note = note
            p.sounds += sounds[i]
            p.sequence += sequence[i]
            p.stamps += st
            val waitingFor = bound.filter { it.size > p.sequence.size && it.subList(0, p.sequence.size) == p.sequence }
            if (p.sequence.size >= maxLen) {
                resolveNow("max-length")
            } else if (waitingFor.isEmpty()) {
                resolveNow("no-continuation")
            } else {
                cancelTimer?.invoke()
                p.waited = true
                val delay = waitDelay(now, st)
                onWait(p, waitingFor, delay)
                cancelTimer = scheduler.schedule(delay) { resolveNow("timeout") }
            }
        }
    }

    /** True if [label] continues the tail of the group that just resolved, within the gap: it is absorbed. */
    private fun absorbed(mode: String, app: String, label: String, st: Stamp?, now: Long): Boolean {
        val t = tail ?: return false
        if (t.mode != mode || t.app != app) return false
        val prev = t.lastStamp
        val gap = if (st != null && prev != null) st.startMs - prev.endMs else null
        val close = if (gap != null) gap in -CLOCK_SLACK_MS..gapMs() else now - t.lastAt <= gapMs()
        val next = t.tails.filter { it[t.matched] == label }
        if (!close || next.isEmpty()) return false
        t.matched++; t.lastStamp = st; t.lastAt = now
        t.tails = next.filter { it.size > t.matched }
        if (st != null) lastResolvedEnd = st
        if (t.tails.isEmpty()) tail = null
        onAbsorb(t.done, label, gap)
        return true
    }

    /** How long to wait for a follow-up to the sound that arrived at [now] with stamp [st]. */
    fun waitDelay(now: Long, st: Stamp?): Long {
        val gap = gapMs()
        if (st == null || offsets.isEmpty()) return gap
        val lag = ((now - st.endMs) - offsets.min()).coerceAtLeast(0)
        return (gap - lag).coerceAtLeast(0) + jitterMs()
    }

    private fun observe(now: Long, st: Stamp): String? {
        var note: String? = null
        val last = lastDeviceEnd
        if (last != null && st.endMs < last - CLOCK_SLACK_MS) {   // device rebooted or its clock wrapped
            offsets.clear()
            note = "device clock reset"
        }
        lastDeviceEnd = st.endMs
        offsets.addLast(now - st.endMs)
        while (offsets.size > OFFSET_WINDOW) offsets.removeFirst()
        return note
    }

    /** Resolve whatever is pending now (timeout, mode change, or a phrase arriving). */
    fun flush() { if (pending != null) resolveNow("flush") }

    /** Drop pending sounds without acting (disarm / emergency stop). */
    fun cancel() {
        cancelTimer?.invoke(); cancelTimer = null
        pending = null; tail = null
    }

    /** Forget the device-clock estimate (e.g. the device reconnected). */
    fun resetClock() { offsets.clear(); lastDeviceEnd = null; lastResolved = null; lastResolvedEnd = null; tail = null }

    private fun resolveNow(why: String) {
        cancelTimer?.invoke(); cancelTimer = null
        val p = pending ?: return
        pending = null
        p.endedBy = why
        lastResolved = p
        lastResolvedEnd = p.stamps.lastOrNull()
        val n = p.sequence.size
        val tails = absorb.filter { it.size > n && it.subList(0, n) == p.sequence }
        tail = if (why == "no-continuation" && tails.isNotEmpty())
            Tail(p.mode, p.app, p, tails, n, p.stamps.lastOrNull(), scheduler.now()) else null
        onResolve(p)
    }

    companion object {
        const val CLOCK_SLACK_MS = 50L
        const val OFFSET_WINDOW = 16
    }
}
