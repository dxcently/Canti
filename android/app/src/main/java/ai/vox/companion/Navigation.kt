package ai.vox.companion

/**
 * Pure helpers for the navigation actions Android has no single call for (JVM-testable; Executor applies them).
 *
 *  - [Forward]: "forward" (app-only binding click hiss) = click a visible Forward control, else open the app's overflow
 *    menu and click Forward there; if there is none (or it is disabled), do nothing and say "no-forward".
 *  - [SwipeGeometry]: fling swipes (vertical 72% -> 12%, horizontal 85% -> 15%, in 100 ms) kept out of the system gesture zones.
 *  - [GestureQueue]: one injected gesture at a time (a new dispatchGesture cancels the one in progress).
 */
object Forward {
    /** What a node looks like to the finder (from AccessibilityNodeInfo in the app, from fakes in tests). */
    data class Info(
        val text: String?, val desc: String?,
        val clickable: Boolean, val enabled: Boolean, val visible: Boolean,
        val left: Int = 0, val top: Int = 0, val right: Int = 0, val bottom: Int = 0,
    )

    /** Exact labels (normalized) only: "Fast forward" (media) or "Forward to…" never match. */
    val FORWARD_LABELS = setOf("forward", "go forward", "navigate forward", "forward button")
    val MENU_LABELS = setOf(
        "more options", "more", "menu", "main menu", "open menu", "overflow menu", "options", "more actions",
        "app menu", "browser menu", "customize and control google chrome", "settings and more",
    )

    fun norm(s: String?): String = s.orEmpty().trim().lowercase().replace(Regex("\\s+"), " ").trimEnd('.', '…', ':')

    fun isForward(i: Info) = norm(i.text) in FORWARD_LABELS || norm(i.desc) in FORWARD_LABELS
    fun isMenu(i: Info) = norm(i.desc) in MENU_LABELS || norm(i.text) in MENU_LABELS

    /** A match: the node carrying the label, the node to click (itself or its nearest clickable ancestor), and whether it is enabled. */
    data class Hit<N>(val labelled: N, val click: N, val enabled: Boolean)

    /**
     * Depth-first search (at most [limit] nodes) for a visible node matching [want] that is clickable or has a
     * clickable ancestor. Returns every hit in tree order.
     */
    fun <N> findAll(root: N, kids: (N) -> List<N>, info: (N) -> Info, want: (Info) -> Boolean, limit: Int = 1500): List<Hit<N>> {
        val hits = mutableListOf<Hit<N>>()
        var seen = 0
        fun walk(n: N, clickableAncestor: N?, ancestorEnabled: Boolean) {
            if (seen++ >= limit) return
            val i = info(n)
            val clicker = if (i.clickable) n else clickableAncestor
            val enabled = if (i.clickable) i.enabled else ancestorEnabled
            if (i.visible && want(i) && clicker != null) hits += Hit(n, clicker, enabled && i.enabled)
            for (c in kids(n)) walk(c, clicker, enabled)
        }
        walk(root, null, true)
        return hits
    }

    /** The Forward control to click: the first enabled hit, else the first (disabled) one, else null. */
    fun <N> forward(roots: List<N>, kids: (N) -> List<N>, info: (N) -> Info): Hit<N>? {
        val hits = roots.flatMap { findAll(it, kids, info, ::isForward) }
        return hits.firstOrNull { it.enabled } ?: hits.firstOrNull()
    }

    /**
     * The overflow-menu button: an enabled visible "More options"/"Menu" control, preferring the toolbar bands (top or
     * bottom [band] of the screen; browsers put the toolbar at either end), then the smallest one.
     */
    fun <N> menu(roots: List<N>, kids: (N) -> List<N>, info: (N) -> Info, screenH: Int, band: Double = 0.18): Hit<N>? {
        val hits = roots.flatMap { findAll(it, kids, info, ::isMenu) }.filter { it.enabled }
        fun inBand(h: Hit<N>): Boolean {
            val i = info(h.labelled)
            val cy = (i.top + i.bottom) / 2
            return cy <= screenH * band || cy >= screenH * (1 - band)
        }
        fun area(h: Hit<N>) = info(h.labelled).let { (it.right - it.left).toLong() * (it.bottom - it.top) }
        return hits.sortedWith(compareBy<Hit<N>>({ if (inBand(it)) 0 else 1 }, { area(it) })).firstOrNull()
    }
}

object SwipeGeometry {
    /**
     * Vertical flings start at 72% of the height and end at 12% (swipe_down mirrors: 28% -> 88%). The start used to be
     * 85%, where feeds put bottom cards, banners and tab bars (Telegram's in-list login alert sat right under it);
     * 72% is above them on a 20:9 phone. Horizontal flings keep 85% -> 15% of the width, through the middle.
     * 100 ms keeps the old fling speed (70% in 120 ms) for the shorter stroke.
     */
    const val FROM_V = 0.72f
    const val TO_V = 0.12f
    const val FROM = 0.85f
    const val TO = 0.15f
    const val DURATION_MS = 100L

    /** System gesture insets (px) plus a margin: no swipe point may lie inside them. */
    data class Safe(val left: Int, val top: Int, val right: Int, val bottom: Int)

    /** Fallback when the insets are unknown: 48 dp at the bottom and top, 32 dp at the sides. */
    fun fallback(density: Float) = Safe((32 * density).toInt(), (48 * density).toInt(), (32 * density).toInt(), (48 * density).toInt())

    /** [x1, y1, x2, y2] for a swipe action, or null for any other action. */
    fun line(action: String, w: Int, h: Int, safe: Safe): FloatArray? {
        val cx = w / 2f; val cy = h / 2f
        fun y(f: Float) = (h * f).coerceIn(safe.top.toFloat(), (h - safe.bottom).toFloat())
        fun x(f: Float) = (w * f).coerceIn(safe.left.toFloat(), (w - safe.right).toFloat())
        return when (action) {
            "swipe_up" -> floatArrayOf(cx, y(FROM_V), cx, y(TO_V))
            "swipe_down" -> floatArrayOf(cx, y(1 - FROM_V), cx, y(1 - TO_V))
            "swipe_left" -> floatArrayOf(x(FROM), cy, x(TO), cy)
            "swipe_right" -> floatArrayOf(x(TO), cy, x(FROM), cy)
            else -> null
        }
    }
}

/**
 * Injected gestures one at a time. Android cancels a gesture still in progress when the next dispatchGesture comes,
 * so two flings dispatched 10-25 ms apart (a slow exec meets the next message) scrolled once: the round-2 test lost
 * the first of each such pair. The next step starts only when the running gesture has completed or been cancelled
 * (or was refused). A global action that arrives while gestures wait goes behind them, so "swipe, swipe, back" stays
 * in that order. Not merged: two flings in a row scroll twice, as asked.
 *
 * A running gesture whose callback never comes (a service hiccup) blocks for at most [stuckMs]. At most [max] steps
 * wait; beyond that the oldest waiting one is dropped. Pure; the caller passes the clock. Main thread.
 */
class GestureQueue<T : Any>(private val max: Int = 4, private val stuckMs: Long = 3_000) {
    private var running: T? = null
    private var since = 0L
    private val waiting = ArrayDeque<T>()
    /** Steps dropped from a full queue (for the log); cleared by the caller. */
    val dropped = mutableListOf<T>()

    val idle: Boolean get() = running == null && waiting.isEmpty()
    val hasWaiting: Boolean get() = waiting.isNotEmpty()

    /** Offer [x]: returns the step to start now (it is then running; normally [x] itself), or null if [x] waits. */
    fun offer(x: T, now: Long): T? {
        if (running != null && now - since >= stuckMs) running = null
        if (running == null && waiting.isEmpty()) { running = x; since = now; return x }
        if (waiting.size >= max) dropped += waiting.removeFirst()
        waiting.addLast(x)
        return if (running == null) next(now) else null
    }

    /** Forget the waiting steps (a hold-scroll takes over the finger); returns them for the log. */
    fun dropWaiting(): List<T> = waiting.toList().also { waiting.clear() }

    /** The running step [x] is over (completed, cancelled, refused): the next step to start now, or null. */
    fun finished(x: T, now: Long): T? {
        if (running !== x) return null   // a late callback of a step already given up on
        running = null
        return next(now)
    }

    private fun next(now: Long): T? {
        val n = waiting.removeFirstOrNull() ?: return null
        running = n; since = now
        return n
    }
}
