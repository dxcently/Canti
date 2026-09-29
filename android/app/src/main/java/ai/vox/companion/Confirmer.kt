package ai.vox.companion

import android.os.Handler
import android.os.SystemClock
import android.view.accessibility.AccessibilityEvent

/**
 * A coarse luminance grid of a screenshot, for "did the pixels change?". Cells covered by a mask (status bar,
 * navigation bar, VOX's own overlays) are -1 and never compared. Pure Kotlin: unit-tested on the JVM.
 */
class PixelGrid(val cols: Int, val rows: Int, val cells: IntArray) {
    /** Fraction of cells (unmasked in both grids) whose mean luminance differs by more than [delta] (0-255). */
    fun diff(o: PixelGrid, delta: Int = 12): Double {
        require(cols == o.cols && rows == o.rows)
        var n = 0; var changed = 0
        for (i in cells.indices) {
            val a = cells[i]; val b = o.cells[i]
            if (a < 0 || b < 0) continue
            n++
            if (kotlin.math.abs(a - b) > delta) changed++
        }
        return if (n == 0) 0.0 else changed.toDouble() / n
    }

    /** A short content hash (for the log): equal hashes = identical grids. */
    fun hash(): String = cells.contentHashCode().toUInt().toString(16)

    companion object {
        const val COLS = 36
        const val ROWS = 80

        /**
         * [argb] is a w*h image (already downscaled is fine), [mask] rects are in the same pixel space as the
         * ORIGINAL screen of size [screenW] x [screenH] (left, top, right, bottom).
         */
        fun from(w: Int, h: Int, argb: IntArray, screenW: Int, screenH: Int, mask: List<IntArray>, cols: Int = COLS, rows: Int = ROWS): PixelGrid {
            val cells = IntArray(cols * rows)
            for (r in 0 until rows) for (c in 0 until cols) {
                // cell centre in screen coordinates, for the mask test
                val sx = ((c + 0.5) * screenW / cols).toInt(); val sy = ((r + 0.5) * screenH / rows).toInt()
                if (mask.any { sx >= it[0] && sx < it[2] && sy >= it[1] && sy < it[3] }) { cells[r * cols + c] = -1; continue }
                val x0 = c * w / cols; val x1 = maxOf(x0 + 1, (c + 1) * w / cols)
                val y0 = r * h / rows; val y1 = maxOf(y0 + 1, (r + 1) * h / rows)
                var sum = 0L; var n = 0
                for (y in y0 until minOf(y1, h)) for (x in x0 until minOf(x1, w)) {
                    val p = argb[y * w + x]
                    sum += (299 * ((p shr 16) and 0xFF) + 587 * ((p shr 8) and 0xFF) + 114 * (p and 0xFF)) / 1000
                    n++
                }
                cells[r * cols + c] = if (n == 0) 0 else (sum / n).toInt()
            }
            return PixelGrid(cols, rows, cells)
        }
    }
}

/**
 * Confirms that a dispatched action had a visible effect, within `timeoutMs`:
 *
 *  1. Events. A strong event from another package (scroll, window state/windows change, text change) confirms at once;
 *     a content change confirms if the visible-tree fingerprint differs from the one taken before dispatch.
 *     Events from Canti itself never count: its package, and its overlay windows (a TYPE_WINDOWS_CHANGED event has no
 *     package, only a window id; moving or making the badge pass-through emits one) via [ownWindow].
 *     The before-fingerprint walks the whole tree on the main thread before dispatch (200-470 ms on TikTok), so it is
 *     taken only for actions whose effect may show as nothing but content changes (taps, media keys...). Swipes,
 *     scrolls and global navigation ([treeBaseline] = false) always emit a strong event (VIEW_SCROLLED,
 *     WINDOW_STATE_CHANGED / WINDOWS_CHANGED) when they work; without a baseline their content changes are ignored and
 *     the pixel check at the timeout is the fallback.
 *     ECHO events (click, long-click, selection, focus) that arrive while our own injected gesture is running, or
 *     within [echoMs] after it completes, are ignored: they are the app reporting our touch, not an effect of it.
 *     Echo events after that window count as strong.
 *  2. Pixels. If no event confirmed by the timeout (a GL map or a video surface emits none), compare screenshots
 *     taken before dispatch and at the timeout (AccessibilityService.takeScreenshot, API 30+), with the status and
 *     navigation bars and VOX's own overlays masked out. A changed-cell fraction above [pixelThreshold] confirms.
 *     Android refuses screenshots closer together than its minimum interval (error 3), so grabs go through a
 *     [GrabGate]: a baseline that comes too soon reuses the last timeout screenshot when that one is recent (the screen
 *     as the previous action left it), else the watch runs on events alone ("screenshot rate-limited"); a timeout
 *     screenshot that comes too soon waits out the interval.
 *
 * Result (event "confirm"): "confirmed (events)", "confirmed (pixels)" or "no visible change".
 */
class Confirmer(
    private val handler: Handler,
    private val ownPackage: String,
    private val fingerprint: () -> Int,
    private val timeoutMs: () -> Long,
    /** Asynchronously capture a masked grid of the screen; calls back on the main thread (null = unavailable). */
    private val grab: ((PixelGrid?) -> Unit) -> Unit = { it(null) },
    private val echoMs: Long = 250,
    private val pixelThreshold: Double = 0.005,
    private val gate: GrabGate = GrabGate(),
    /** True if the accessibility window id is one of Canti's own overlay windows. */
    private val ownWindow: (Int) -> Boolean = OwnWindows::contains,
    private val clock: () -> Long = SystemClock::elapsedRealtime,
    private val schedule: (Long, () -> Unit) -> Unit = { ms, r -> handler.postDelayed(r, ms) },
    /** Called from [finish] with each watch's outcome (also "superseded"), after the log line. */
    private val onResult: (watch: Long, action: String, result: String, by: String?) -> Unit = { _, _, _, _ -> },
    /** Called from [begin] with each new watch id and action, right after the watch is created (the overlay freeze). */
    private val onBegin: (watch: Long, action: String) -> Unit = { _, _ -> },
) {
    /** [before] = the tree fingerprint before dispatch, null when not taken ([treeBaseline]). */
    private class Watch(val id: Long, val action: String, val before: Int?, val t0: Long, val injected: Boolean) {
        var done = false
        var lastFp = 0L
        var echoUntil = if (injected) Long.MAX_VALUE else 0L   // open until the gesture completes
        var echoesIgnored = 0
        var beforePixels: PixelGrid? = null
        var beforePixelsState = "pending"
    }

    private var watch: Watch? = null
    private var nextId = 1L

    /** The last watch's result and its evidence (for tests and the debug socket). */
    var lastResult: String? = null; private set
    var lastBy: String? = null; private set

    /**
     * Call just before dispatching [action]; [injected] = true when the action is a touch gesture we inject (its
     * echo events must be ignored). Returns the watch id (logged with the exec event).
     */
    fun begin(action: String, injected: Boolean = false): Long {
        watch?.let { if (!it.done) finish(it, "superseded", null) }
        val w = Watch(nextId++, action, if (treeBaseline(action)) fingerprint() else null, clock(), injected)
        watch = w
        onBegin(w.id, action)
        when (val plan = gate.baseline(w.t0)) {
            GrabGate.Plan.Now -> { gate.took(w.t0); grab { g -> w.beforePixels = g; w.beforePixelsState = if (g == null) "unavailable" else "ok" } }
            is GrabGate.Plan.Reuse -> { w.beforePixels = plan.grid; w.beforePixelsState = "reused" }
            else -> w.beforePixelsState = "rate-limited"
        }
        schedule(timeoutMs()) { timeout(w) }
        return w.id
    }

    /** The injected gesture for watch [id] finished (completed or cancelled): the echo window closes echoMs later. */
    fun gestureDone(id: Long) {
        val w = watch ?: return
        if (w.id == id) w.echoUntil = clock() + echoMs
    }

    fun onEvent(e: AccessibilityEvent) = onEvent(e.eventType, e.packageName?.toString() ?: "", e.windowId)

    fun onEvent(eventType: Int, pkg: String, windowId: Int) {
        val w = watch ?: return
        if (w.done) return
        if (pkg == ownPackage) return
        // No package (TYPE_WINDOWS_CHANGED): Canti's own overlay moving or changing flags is not the app reacting.
        if (pkg.isEmpty() && windowId >= 0 && ownWindow(windowId)) return
        val now = clock()
        val type = AccessibilityEvent.eventTypeToString(eventType)
        when (kind(eventType, now < w.echoUntil)) {
            Kind.ECHO -> w.echoesIgnored++
            Kind.STRONG -> finish(w, "confirmed (events)", "$type:$pkg")
            Kind.CONTENT -> {
                val before = w.before ?: return   // no baseline: the strong event or the pixels decide
                if (now - w.lastFp < 100) return   // throttle tree walks
                w.lastFp = now
                if (fingerprint() != before) finish(w, "confirmed (events)", "$type+tree-changed:$pkg")
            }
            Kind.OTHER -> {}
        }
    }

    private fun timeout(w: Watch) {
        if (w.done) return
        w.before?.let { if (fingerprint() != it) { finish(w, "confirmed (events)", "tree-changed-at-timeout"); return } }
        val before = w.beforePixels
        if (before == null) { finish(w, "no visible change", "screenshot ${w.beforePixelsState}"); return }
        grabAfter(w, before)
    }

    private fun grabAfter(w: Watch, before: PixelGrid) {
        if (w.done) return
        val now = clock()
        val plan = gate.after(now)
        if (plan is GrabGate.Plan.Later) { schedule(plan.ms) { grabAfter(w, before) }; return }
        gate.took(now)
        grab { after ->
            if (after != null) gate.tookAfter(clock(), after)
            if (w.done) return@grab
            if (after == null) { finish(w, "no visible change", "screenshot unavailable"); return@grab }
            val d = before.diff(after)
            val by = "pixels ${"%.1f".format(d * 100)}% (${before.hash()}->${after.hash()})"
            finish(w, if (d > pixelThreshold) "confirmed (pixels)" else "no visible change", by)
        }
    }

    private fun finish(w: Watch, result: String, by: String?) {
        w.done = true
        lastResult = result; lastBy = by
        EventLog.ev("confirm", "watch" to w.id, "action" to w.action, "result" to result, "by" to by,
            "ms" to clock() - w.t0, "echoes_ignored" to w.echoesIgnored, "tree_baseline" to (w.before != null))
        onResult(w.id, w.action, result, by)
    }

    enum class Kind { STRONG, CONTENT, ECHO, OTHER }

    companion object {
        private const val STRONG_TYPES = AccessibilityEvent.TYPE_VIEW_SCROLLED or AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED or
            AccessibilityEvent.TYPE_WINDOWS_CHANGED or AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED
        private const val ECHO_TYPES = AccessibilityEvent.TYPE_VIEW_CLICKED or AccessibilityEvent.TYPE_VIEW_LONG_CLICKED or
            AccessibilityEvent.TYPE_VIEW_SELECTED or AccessibilityEvent.TYPE_VIEW_FOCUSED

        /**
         * Actions that always emit a strong event when they take effect (scroll / window events), so the costly
         * before-dispatch tree walk is skipped for them: swipes and scrolls (VIEW_SCROLLED, or pixels for a GL feed)
         * and global navigation (WINDOW_STATE_CHANGED / WINDOWS_CHANGED).
         */
        private val NO_TREE_BASELINE = setOf(
            "swipe_up", "swipe_down", "swipe_left", "swipe_right", "scroll_up", "scroll_down",
            "back", "home", "recents", "notifications",
        )

        /** True if [begin] takes the before-dispatch tree fingerprint for [action]. */
        fun treeBaseline(action: String): Boolean = action !in NO_TREE_BASELINE

        /** How an event counts; [inEchoWindow] = our injected gesture is running or just finished. */
        fun kind(type: Int, inEchoWindow: Boolean): Kind = when {
            type and ECHO_TYPES != 0 -> if (inEchoWindow) Kind.ECHO else Kind.STRONG
            type and STRONG_TYPES != 0 -> Kind.STRONG
            type == AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED -> Kind.CONTENT
            else -> Kind.OTHER
        }
    }
}

/**
 * Keeps screenshots at least [minIntervalMs] apart (Android's AccessibilityService.takeScreenshot limit; closer requests
 * fail with ERROR_TAKE_SCREENSHOT_INTERVAL_TIME_SHORT). Pure: the caller passes the clock. JVM-tested (CoreTest).
 */
class GrabGate(private val minIntervalMs: Long = MIN_INTERVAL_MS) {
    sealed interface Plan {
        /** Take it now (then call [took]). */
        data object Now : Plan
        /** Use this recent timeout screenshot as the baseline. */
        data class Reuse(val grid: PixelGrid) : Plan
        /** Too soon: try again in [ms]. */
        data class Later(val ms: Long) : Plan
        /** Too soon and nothing to reuse: go without. */
        data object Skip : Plan
    }

    private var lastAt: Long? = null
    private var after: PixelGrid? = null
    private var afterAt = 0L

    private fun wait(now: Long): Long = lastAt?.let { minIntervalMs - (now - it) } ?: 0L

    /** The baseline before a dispatch cannot wait: it is now, the last timeout screenshot if recent, or nothing. */
    fun baseline(now: Long): Plan {
        if (wait(now) <= 0) return Plan.Now
        val a = after
        return if (a != null && now - afterAt < minIntervalMs) Plan.Reuse(a) else Plan.Skip
    }

    /** The screenshot at the timeout can wait out the interval (a later look only gives the change more time). */
    fun after(now: Long): Plan = wait(now).let { if (it <= 0) Plan.Now else Plan.Later(it) }

    fun took(now: Long) { lastAt = now }

    fun tookAfter(now: Long, grid: PixelGrid) { after = grid; afterAt = now }

    companion object {
        /** Android 11-14 allow one screenshot per second per service (333 ms on some builds): take the safe one. */
        const val MIN_INTERVAL_MS = 1000L
    }
}
