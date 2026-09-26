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
 *     ECHO events (click, long-click, selection, focus) that arrive while our own injected gesture is running, or
 *     within [echoMs] after it completes, are ignored: they are the app reporting our touch, not an effect of it.
 *     Echo events after that window count as strong.
 *  2. Pixels. If no event confirmed by the timeout (a GL map or a video surface emits none), compare screenshots
 *     taken before dispatch and at the timeout (AccessibilityService.takeScreenshot, API 30+), with the status and
 *     navigation bars and VOX's own overlays masked out. A changed-cell fraction above [pixelThreshold] confirms.
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
) {
    private class Watch(val id: Long, val action: String, val before: Int, val t0: Long, val injected: Boolean) {
        var done = false
        var lastFp = 0L
        var echoUntil = if (injected) Long.MAX_VALUE else 0L   // open until the gesture completes
        var echoesIgnored = 0
        var beforePixels: PixelGrid? = null
        var beforePixelsState = "pending"
    }

    private var watch: Watch? = null
    private var nextId = 1L

    /**
     * Call just before dispatching [action]; [injected] = true when the action is a touch gesture we inject (its
     * echo events must be ignored). Returns the watch id (logged with the exec event).
     */
    fun begin(action: String, injected: Boolean = false): Long {
        watch?.let { if (!it.done) finish(it, "superseded", null) }
        val w = Watch(nextId++, action, fingerprint(), SystemClock.elapsedRealtime(), injected)
        watch = w
        grab { g -> w.beforePixels = g; w.beforePixelsState = if (g == null) "unavailable" else "ok" }
        handler.postDelayed({ timeout(w) }, timeoutMs())
        return w.id
    }

    /** The injected gesture for watch [id] finished (completed or cancelled): the echo window closes echoMs later. */
    fun gestureDone(id: Long) {
        val w = watch ?: return
        if (w.id == id) w.echoUntil = SystemClock.elapsedRealtime() + echoMs
    }

    fun onEvent(e: AccessibilityEvent) {
        val w = watch ?: return
        if (w.done) return
        val pkg = e.packageName?.toString() ?: ""
        if (pkg == ownPackage) return
        val now = SystemClock.elapsedRealtime()
        val type = AccessibilityEvent.eventTypeToString(e.eventType)
        when (kind(e.eventType, now < w.echoUntil)) {
            Kind.ECHO -> w.echoesIgnored++
            Kind.STRONG -> finish(w, "confirmed (events)", "$type:$pkg")
            Kind.CONTENT -> {
                if (now - w.lastFp < 100) return   // throttle tree walks
                w.lastFp = now
                if (fingerprint() != w.before) finish(w, "confirmed (events)", "$type+tree-changed:$pkg")
            }
            Kind.OTHER -> {}
        }
    }

    private fun timeout(w: Watch) {
        if (w.done) return
        if (fingerprint() != w.before) { finish(w, "confirmed (events)", "tree-changed-at-timeout"); return }
        val before = w.beforePixels
        if (before == null) { finish(w, "no visible change", "screenshot ${w.beforePixelsState}"); return }
        grab { after ->
            if (w.done) return@grab
            if (after == null) { finish(w, "no visible change", "screenshot unavailable"); return@grab }
            val d = before.diff(after)
            val by = "pixels ${"%.1f".format(d * 100)}% (${before.hash()}->${after.hash()})"
            finish(w, if (d > pixelThreshold) "confirmed (pixels)" else "no visible change", by)
        }
    }

    private fun finish(w: Watch, result: String, by: String?) {
        w.done = true
        EventLog.ev("confirm", "watch" to w.id, "action" to w.action, "result" to result, "by" to by,
            "ms" to SystemClock.elapsedRealtime() - w.t0, "echoes_ignored" to w.echoesIgnored)
    }

    enum class Kind { STRONG, CONTENT, ECHO, OTHER }

    companion object {
        private const val STRONG_TYPES = AccessibilityEvent.TYPE_VIEW_SCROLLED or AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED or
            AccessibilityEvent.TYPE_WINDOWS_CHANGED or AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED
        private const val ECHO_TYPES = AccessibilityEvent.TYPE_VIEW_CLICKED or AccessibilityEvent.TYPE_VIEW_LONG_CLICKED or
            AccessibilityEvent.TYPE_VIEW_SELECTED or AccessibilityEvent.TYPE_VIEW_FOCUSED

        /** How an event counts; [inEchoWindow] = our injected gesture is running or just finished. */
        fun kind(type: Int, inEchoWindow: Boolean): Kind = when {
            type and ECHO_TYPES != 0 -> if (inEchoWindow) Kind.ECHO else Kind.STRONG
            type and STRONG_TYPES != 0 -> Kind.STRONG
            type == AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED -> Kind.CONTENT
            else -> Kind.OTHER
        }
    }
}
