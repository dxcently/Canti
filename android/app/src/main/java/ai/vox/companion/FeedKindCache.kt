package ai.vox.companion

import org.json.JSONArray
import org.json.JSONObject

/**
 * What a rise / fall meets in the app window in front, cached so the swipe dispatches at once (pure: FeedKindCacheTest):
 * a paged feed ([Kind.FEED]), an ordinary list with its step plan ([Kind.LIST]), or neither ([Kind.OTHER]: no
 * scroller, a horizontal one; the plain fling).
 *
 * Why: the check reads the scrollers of the app's tree ([ScrollerReader]), a synchronous call into the app's UI thread
 * for each node. Round 4 on the Z Flip: every TikTok fling waited 250-300 ms for it (round 3's plain swipe: 2-7 ms), and
 * Instagram's home list waited a median 248 ms (worst 512) before each step. Now the read runs on a background thread
 * ([FeedKindWatcher]) when the window changes and (at most every [refreshGapMs], with a trailing read after the last
 * change) when its content changes or scrolls; the swipe reads the answer here ([lookup]).
 *
 * Rules:
 *  - one entry, for the app window in front; [windowEvent] drops it when a window state change comes from another
 *    package or another window id (a dialog, another app);
 *  - each kind is trusted for its own time: [feedTtlMs], [listTtlMs] (longer: the list is re-checked live, one node,
 *    just before each step, [StepCheck]), [otherTtlMs] (short). An expired entry is not used ([Lookup.Expired]);
 *  - results carry the generation they were started in ([begin]); a result that finishes after an invalidation, or
 *    after a newer answer ([put]), is dropped, so a read of the previous window never lands on the new one;
 *  - one refresh at a time; a forced request during one ([begin] force) runs again when it finishes;
 *  - [lastKind]: each package's last stored kind this session, kept across invalidation and expiry ([FlingPlan]).
 */
class FeedKindCache(
    private val clock: () -> Long,
    val feedTtlMs: Long = FEED_TTL_MS,
    val listTtlMs: Long = LIST_TTL_MS,
    val otherTtlMs: Long = OTHER_TTL_MS,
    val refreshGapMs: Long = REFRESH_GAP_MS,
) {
    enum class Kind { FEED, LIST, OTHER }

    /**
     * One read's result. [list]: the main list as read (LIST only), [handle] its node (an AccessibilityNodeInfo on the
     * phone; opaque here) for the live re-check, [screenW] x [screenH] the screen it was read on.
     */
    data class Answer(
        val pkg: String, val windowId: Int, val kind: Kind, val why: String,
        val list: NodeSnap? = null, val handle: Any? = null, val screenW: Int = 0, val screenH: Int = 0,
    )

    data class Entry(val answer: Answer, val at: Long) {
        val pkg get() = answer.pkg
        val windowId get() = answer.windowId
        val kind get() = answer.kind
        val why get() = answer.why
    }

    sealed class Lookup {
        abstract val label: String
        data class Hit(val entry: Entry, val ageMs: Long) : Lookup() { override val label get() = "hit" }
        data class Expired(val entry: Entry, val ageMs: Long) : Lookup() { override val label get() = "expired" }
        object Miss : Lookup() { override val label get() = "miss" }
    }

    private var entry: Entry? = null
    private var gen = 0L
    private var refreshing = false
    private var again = false
    private var lastStart: Long? = null
    /** Package -> its last stored kind ([lastKind]); never cleared by [invalidate]. */
    private val lastKind = HashMap<String, Kind>()

    fun ttl(kind: Kind) = when (kind) { Kind.FEED -> feedTtlMs; Kind.LIST -> listTtlMs; Kind.OTHER -> otherTtlMs }

    /** The cached answer for [pkg] (the app in front); a different package's entry is a miss. */
    @Synchronized fun lookup(pkg: String?): Lookup {
        val e = entry?.takeIf { pkg != null && it.pkg == pkg } ?: return Lookup.Miss
        val age = clock() - e.at
        return if (age in 0..ttl(e.kind)) Lookup.Hit(e, age) else Lookup.Expired(e, age)
    }

    /** A window state change from [pkg] / [windowId]: another package or window drops the entry (a refresh follows). */
    @Synchronized fun windowEvent(pkg: String, windowId: Int) {
        val e = entry
        if (e != null && e.pkg == pkg && (windowId < 0 || e.windowId == windowId)) return
        invalidate()
    }

    /** Forget the entry; a refresh already running will not store its (older) answer. */
    @Synchronized fun invalidate() { entry = null; gen++ }

    /**
     * Start a refresh now? Returns its token for [finish], or null. [force] (a window change, arming, a swipe that found
     * no usable answer): yes unless one is running, which then runs again when it ends. Otherwise (a content change):
     * only when there is no entry or none started in the last [refreshGapMs] ([msUntilRefresh] says when).
     */
    @Synchronized fun begin(force: Boolean): Long? {
        if (refreshing) { if (force) again = true; return null }
        val now = clock()
        if (!force && entry != null && msUntilRefresh() > 0) return null
        refreshing = true; again = false; lastStart = now
        return gen
    }

    /** How long until a content change may start a refresh (0: now). */
    @Synchronized fun msUntilRefresh(): Long {
        val last = lastStart ?: return 0
        return (refreshGapMs - (clock() - last)).coerceAtLeast(0)
    }

    /** The refresh with [token] ends with [a] (null: no answer). True if another refresh should start at once. */
    @Synchronized fun finish(token: Long, a: Answer?): Boolean {
        refreshing = false
        val started = lastStart ?: Long.MIN_VALUE
        if (token == gen && a != null && (entry?.at ?: Long.MIN_VALUE) <= started) store(a)
        return again.also { again = false }
    }

    /** A synchronous read (voice scroll's feed check) found [a]: store it at once (it is the newest answer there is). */
    @Synchronized fun put(a: Answer) = store(a)

    private fun store(a: Answer) { entry = Entry(a, clock()); lastKind[a.pkg] = a.kind }

    /** The last kind stored for [pkg] in this session, kept across invalidations and expiry; null: none yet. */
    @Synchronized fun lastKind(pkg: String?): Kind? = pkg?.let { lastKind[it] }

    @Synchronized fun current(): Entry? = entry

    companion object {
        /** A feed answer is used this long after it was read (TikTok's content changes refresh it every [REFRESH_GAP_MS]). */
        const val FEED_TTL_MS = 6_000L
        /**
         * A list plan is used this long: its node is re-checked live before each step ([StepCheck]), so a list read a
         * while ago (the user reading a post, no content changes) still steps; what can go stale is which scroller is
         * the main one, and a change there emits content changes that refresh the entry.
         */
        const val LIST_TTL_MS = 20_000L
        /** A "neither" answer (no scroller, horizontal) expires fast; its fling is the plain fling anyway. */
        const val OTHER_TTL_MS = 1_500L
        /** Content changes refresh at most this often: each refresh is a tree walk served by the app's UI thread. */
        const val REFRESH_GAP_MS = 2_000L

        /** A read's answer from [ScrollStep.classify]; [handle] is the main list's node. */
        fun answerOf(pkg: String, windowId: Int, c: ScrollStep.Kind, handle: Any?, screenW: Int, screenH: Int): Answer = when (c) {
            is ScrollStep.Kind.Fling -> Answer(pkg, windowId, if (c.d.feed) Kind.FEED else Kind.OTHER, c.d.why, screenW = screenW, screenH = screenH)
            is ScrollStep.Kind.List -> Answer(pkg, windowId, Kind.LIST, "list ${c.main.node.shortCls}", c.main.node, handle, screenW, screenH)
        }
    }
}

/**
 * How a vertical swipe is planned from the cache ([FeedKindCache.lookup]), without reading the tree (pure):
 *  - [FEED]: a fresh feed answer: the feed fling at once;
 *  - [LIST]: a fresh list plan: the step at once, after the live one-node check ([StepCheck]); if that fails, [PLAIN];
 *  - [OTHER]: a fresh "neither" answer: the plain fling (what the read would have given);
 *  - [LAST_FEED]: no usable answer (none, or expired) in a known feed app ([ScrollStep.FEED_APPS]) whose last answer
 *    this session was a feed: the feed fling at once (the plain fling skips ~3 Reels);
 *  - [PLAIN]: no usable answer otherwise: the plain fling at once. Never a wait for the tree: in a list the plain
 *    fling glides further than a step, but a step needs the list's geometry, and a step from a guessed one could drag
 *    whatever is under it now (a slider, a map, another page).
 * With no usable answer ([LAST_FEED], [PLAIN]) a background refresh starts.
 */
enum class FlingPlan { FEED, LIST, OTHER, LAST_FEED, PLAIN;
    companion object {
        /** [lastKind]: the cache's last answer for [pkg] this session ([FeedKindCache.lastKind]). */
        fun of(l: FeedKindCache.Lookup, pkg: String? = null, lastKind: FeedKindCache.Kind? = null): FlingPlan = when (l) {
            is FeedKindCache.Lookup.Hit -> when (l.entry.kind) {
                FeedKindCache.Kind.FEED -> FEED
                FeedKindCache.Kind.LIST -> LIST
                FeedKindCache.Kind.OTHER -> OTHER
            }
            is FeedKindCache.Lookup.Expired, FeedKindCache.Lookup.Miss ->
                if (pkg in ScrollStep.FEED_APPS && lastKind == FeedKindCache.Kind.FEED) LAST_FEED else PLAIN
        }
    }
}

/**
 * The live check before a cached step (pure). The step's stroke is in screen coordinates, so it may only use a list
 * that is still there: [live] is the cached list node refreshed just now (one node, not the tree; null = gone or
 * refresh failed). Refused (null decision, with the reason) when the node is gone or hidden, is a different class, is
 * empty or reaches off the screen, or the screen size changed (rotation, the Flip folded). Otherwise the step rules
 * ([ScrollStep.listStep]) run on the live node: its current bounds and scroll actions.
 */
object StepCheck {
    data class Result(val decision: ScrollStep.Decision?, val refused: String?)

    fun check(action: String, a: FeedKindCache.Answer, live: NodeSnap?, w: Int, h: Int): Result {
        val cached = a.list ?: return Result(null, "no cached list")
        if (a.screenW != w || a.screenH != h) return Result(null, "screen size changed (${a.screenW}x${a.screenH} -> ${w}x$h)")
        if (live == null) return Result(null, "list node gone")
        if (!live.visible) return Result(null, "list not visible")
        if (live.cls != cached.cls) return Result(null, "list node is now ${live.shortCls}")
        if (live.area <= 0 || live.left < 0 || live.top < 0 || live.right > w || live.bottom > h)
            return Result(null, "list off screen [${live.left},${live.top}][${live.right},${live.bottom}]")
        return Result(ScrollStep.listStep(action, live), null)
    }
}

/**
 * What the tree shows when a known feed app's screen has no usable scroller ("no scrollable list": YouTube Shorts in RVX
 * on the Flip), for adding its detection later (pure). Structure only, never text: node count, every scrollable node
 * (visible or not), the big nodes (a quarter of the screen or more), and the video surfaces.
 */
object FeedProbe {
    private val VIDEO = listOf("SurfaceView", "TextureView", "VideoView", "PlayerView")

    fun summary(root: NodeSnap, w: Int, h: Int): JSONObject {
        val all = root.walk().toList()
        val screen = w.toLong() * h
        fun j(n: NodeSnap) = JSONObject().put("cls", n.shortCls).put("id", n.id?.substringAfter('/') ?: "")
            .put("bounds", "[${n.left},${n.top}][${n.right},${n.bottom}]").put("visible", n.visible)
            .put("children", n.children.size).put("scrollable", n.scrollable)
            .put("fwd", n.canScrollForward).put("back", n.canScrollBackward).put("rows", n.rows).put("cols", n.cols)
        return JSONObject().put("nodes", all.size)
            .put("scrollables", JSONArray(all.filter { it.scrollable }.sortedByDescending { it.area }.take(8).map(::j)))
            .put("big", JSONArray(all.filter { screen > 0 && it.area * 4 >= screen }.sortedByDescending { it.area }.take(10).map(::j)))
            .put("video", JSONArray(all.filter { n -> VIDEO.any { n.cls.endsWith(it) } }.take(4).map(::j)))
    }
}

/**
 * Keeps [cache] current off the swipe's path (Android-free: FeedKindCacheTest). [read] is the tree read (appRoot,
 * [ScrollerReader], [ScrollStep.classify]); it runs only through [background], never on the caller's thread, so the
 * swipe ([plan]) never waits for it. Null from [read]: no app window (nothing stored). [later] runs the trailing
 * refresh after a burst of content changes (main thread).
 */
class FeedKindWatcher(
    val cache: FeedKindCache,
    private val read: () -> FeedKindCache.Answer?,
    private val background: (Runnable) -> Unit,
    private val later: (Long, Runnable) -> Unit = { _, _ -> },
) {
    private var trailing = false

    /** A window state change ([pkg], [windowId]): a new window drops the entry; always re-read. */
    fun windowStateChanged(pkg: String, windowId: Int) { cache.windowEvent(pkg, windowId); refresh(force = true) }

    /**
     * A content change or scroll in the app's window: re-read at most every [FeedKindCache.refreshGapMs]; a change that
     * comes too soon schedules one trailing read at the end of the gap, so the last change is always read.
     */
    fun contentChanged() {
        if (refresh(force = false) || trailing) return
        trailing = true
        later(cache.msUntilRefresh().coerceAtLeast(MIN_TRAIL_MS), Runnable { trailing = false; contentChanged() })
    }

    /** True if a refresh was started. */
    fun refresh(force: Boolean): Boolean {
        val token = cache.begin(force) ?: return false
        try { background(Runnable { run(token) }) } catch (e: Exception) { cache.finish(token, null); return false }
        return true
    }

    private fun run(token: Long) {
        val a = try { read() } catch (_: Exception) { null }
        if (cache.finish(token, a)) refresh(force = true)
    }

    /** How to swipe in [pkg] now, from the cache only; with no usable answer a refresh starts (the swipe does not wait). */
    fun plan(pkg: String?): Pair<FlingPlan, FeedKindCache.Lookup> {
        val l = cache.lookup(pkg)
        val p = FlingPlan.of(l, pkg, cache.lastKind(pkg))
        if (p == FlingPlan.PLAIN || p == FlingPlan.LAST_FEED) refresh(force = true)
        return p to l
    }

    companion object {
        const val MIN_TRAIL_MS = 100L
    }
}
