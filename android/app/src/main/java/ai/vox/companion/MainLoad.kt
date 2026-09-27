package ai.vox.companion

/**
 * Where Canti's main thread spends its time (pure [LoadStats]; LoadStatsTest). On the Flip, BLE message -> decision
 * took 8-503 ms in Instagram's feed (median 170) and ~9 ms in TikTok/Shorts, with nothing queued: the main thread was
 * busy. Every tree read is a synchronous call into the app's UI thread (the accessibility cache is emptied by the
 * app's event flood), so a busy app stalls Canti. These sections are timed on the main thread; the `main_load` op
 * returns them, and one section over [SLOW_MS] logs `main_slow{what, ms}` at once.
 */
class LoadStats {
    class Section { var count = 0L; var totalMs = 0.0; var maxMs = 0.0; var over16 = 0L; var over50 = 0L; var over100 = 0L }
    private val sections = LinkedHashMap<String, Section>()

    @Synchronized fun record(what: String, ms: Double) {
        val s = sections.getOrPut(what) { Section() }
        s.count++; s.totalMs += ms; if (ms > s.maxMs) s.maxMs = ms
        if (ms > 16) s.over16++; if (ms > 50) s.over50++; if (ms > 100) s.over100++
    }

    /** what -> {count, total_ms, mean_ms, max_ms, over_16, over_50, over_100}, the busiest (total) first. */
    @Synchronized fun snapshot(): Map<String, Map<String, Number>> = sections.entries.sortedByDescending { it.value.totalMs }
        .associate { (k, s) ->
            k to linkedMapOf<String, Number>("count" to s.count, "total_ms" to round1(s.totalMs),
                "mean_ms" to round1(if (s.count == 0L) 0.0 else s.totalMs / s.count), "max_ms" to round1(s.maxMs),
                "over_16" to s.over16, "over_50" to s.over50, "over_100" to s.over100)
        }

    @Synchronized fun reset() = sections.clear()

    private fun round1(v: Double) = Math.round(v * 10) / 10.0
}

object MainLoad {
    const val SLOW_MS = 100.0
    val stats = LoadStats()
    /** Called with a section over [SLOW_MS] (VoxService logs it). */
    @Volatile var onSlow: (String, Double) -> Unit = { _, _ -> }

    inline fun <T> time(what: String, block: () -> T): T {
        val t0 = System.nanoTime()
        try { return block() } finally { done(what, (System.nanoTime() - t0) / 1e6) }
    }

    /**
     * The main thread, set by the service. A section timed on any other thread (a background tree read, e.g.
     * appRoot's `tree:refresh` from the feed-kind refresh) is recorded as `what@bg` and never reported as `main_slow`.
     * Null (JVM tests): every thread counts as main.
     */
    @Volatile var mainThread: Thread? = null

    fun done(what: String, ms: Double) {
        val main = mainThread.let { it == null || it === Thread.currentThread() }
        stats.record(if (main) what else "$what@bg", ms)
        if (main && ms > SLOW_MS) onSlow(what, ms)
    }
}
