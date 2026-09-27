package ai.vox.companion

import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo

/** How far a no-momentum step moves an ordinary list: a fraction of the list's own height (its viewport). */
enum class StepSize(val key: String, val frac: Float) {
    SMALL("small", 0.25f), MEDIUM("medium", 0.5f), LARGE("large", 0.75f);

    companion object {
        val DEFAULT = MEDIUM
        val KEYS = entries.map { it.key }
        fun of(key: String?): StepSize = entries.firstOrNull { it.key == key } ?: DEFAULT
    }
}

/** A scrollable node for the planner: the node with its direct children only, and its parent's class. */
data class ScrollerSnap(val node: NodeSnap, val parentCls: String? = null)

/**
 * Rise / fall (swipe_up / swipe_down): a **step** or a **fling**.
 *
 * The old fling (72% -> 12% of the height in 100 ms, [SwipeGeometry]) leaves the finger at high speed, so an ordinary
 * list keeps gliding for several screens. A step is a controlled drag instead: a [STROKE_MS] stroke over
 * [StepSize.frac] of the list's height (plus the touch slop the list swallows), then the finger holds still for
 * [HOLD_MS] before lifting. The velocity at the lift is ~0, so the list stops where the finger stopped.
 *
 * A paged feed (Reels, TikTok, Shorts, any ViewPager / ViewPager2 / vertical pager whose page fills the viewport)
 * keeps the fling: a slow drag under half a page with no velocity snaps back to the same item, and the fling is what
 * snaps to the next one. Anything the planner cannot place keeps the fling too (it is the old behaviour).
 *
 * Vertical rules, first match wins ([decide]):
 *  1. no visible scroller -> fling (unknown surface: games, maps, custom views);
 *  2. the main scroller ([ScrollPick], as the screen line and node-scroll use) is horizontal -> fling;
 *  3. it is a pager ([pagerWhy]): its class is a pager (…ViewPager…, …Pager), it is ViewPager2's inner list, its view
 *     id names a paged feed (reel, clips, shorts, pager), or one child page fills the viewport ([pageFill]: 1-2
 *     visible children of at least a tenth of it, small overlays ignored, one covering 80% of its height and width,
 *     the scroller at least half the screen tall; ScrollView-like scrollers, whose single child is always the whole
 *     content, are excluded) -> a **feed** fling ([Decision.feed], [feedLine]). Checked before the end: a feed's
 *     scroll actions do not tell (TikTok's pager reports "at the bottom" and still pages);
 *  4. package fallback ([PAGER_PKGS]) with a main scroller at least 60% of the screen tall -> feed fling. Only apps
 *     whose feed is known to be paged and whose tree may not show it; kept small on purpose;
 *  5. it cannot scroll in the swipe's direction -> fling (at its end: the swipe is pull-to-refresh, an overscroll or a
 *     launcher's app drawer, where the fling is what those gestures expect);
 *  6. otherwise -> step.
 *
 * Horizontal swipes (arch / dip) always fling: sideways scrollers are nearly all pagers or snapping carousels (tabs,
 * photo viewers, stories, the launcher's pages), where a no-momentum drag under half a page just snaps back.
 */
object ScrollStep {
    const val STROKE_MS = 300L
    const val HOLD_MS = 150L

    /** The band a vertical step may use (fractions of the screen height), the same as the fling's start and end. */
    const val UP_TOP = SwipeGeometry.TO_V            // 0.12
    const val UP_BOTTOM = SwipeGeometry.FROM_V       // 0.72: above bottom cards, banners and tab bars
    const val DOWN_TOP = 1 - SwipeGeometry.FROM_V    // 0.28
    const val DOWN_BOTTOM = 1 - SwipeGeometry.TO_V   // 0.88
    /** Kept clear inside the list's edges (fraction of its height). */
    const val EDGE = 0.03f
    /** A band shorter than this (fraction of the screen height) cannot hold a useful step: fling instead. */
    const val MIN_BAND = 0.15f

    /**
     * Fallback only (rule 4): packages whose main feed is a full-screen pager and whose accessibility tree may not show
     * it. TikTok (global, Asia and China builds). Unverified on this machine (not installed on the emulator); the tree
     * rules come first and catch Reels / Shorts / Facebook reels by class, id or page size.
     */
    val PAGER_PKGS = setOf("com.zhiliaoapp.musically", "com.ss.android.ugc.trill", "com.ss.android.ugc.aweme")
    /**
     * Apps with a paged video feed ([PAGER_PKGS] plus Instagram Reels and YouTube Shorts, stock and ReVanced / RVX builds).
     * Not a tree rule: only [FeedKindCache] uses it, to keep the feed fling while its answer is missing or expired, and
     * only when the last answer for that app was a feed. (Not added to [PAGER_PKGS]: rule 4 would then feed-fling
     * Instagram's home list.)
     */
    val FEED_APPS = PAGER_PKGS + setOf("com.instagram.android", "com.google.android.youtube", "app.revanced.android.youtube",
        "app.rvx.android.youtube", "com.vanced.android.youtube")
    val PAGER_ID_HINTS = listOf("reel", "clips", "shorts", "pager")
    /** View ids that name a paged *video* feed (not "pager": tab pagers are called that too). */
    val FEED_ID_HINTS = listOf("reel", "clips", "shorts")
    private val WHOLE_CONTENT = listOf("ScrollView", "WebView", "GeckoView")

    /**
     * The fling on a paged video feed: [feedLine] over `feed_fling_ms`, both settable for the phone A/B.
     * Goal: exactly one item per fling. The old feed fling (60% of the height in 100 ms, ~15.8k px/s on the Z Flip)
     * skipped reels: Instagram's first fast flings travelled ~3 reels. The feed snaps by fling velocity, and an
     * injected stroke lifts at its average speed (length / duration), so the default is a short stroke: 15% of the
     * height (396 px on the Flip) in 50 ms, ~7.9k px/s, about half the old speed and a short, snappy flick.
     * `feed_fling_pct` 60 with `feed_fling_ms` 100 is the old fling again.
     */
    const val FEED_FLING_MS = 50
    val FEED_FLING_RANGE = 30..150
    const val FEED_FLING_PCT = 15
    val FEED_FLING_PCT_RANGE = 8..60

    /**
     * [x1, y1, x2, y2] of the feed fling: from the fling's usual start ([SwipeGeometry.FROM_V], 72%; 28% for
     * swipe_down) [pct] % of the screen height towards the other end, clamped out of the insets. Null if not vertical.
     */
    fun feedLine(action: String, w: Int, h: Int, safe: SwipeGeometry.Safe, pct: Int): FloatArray? {
        val cx = w / 2f
        val d = pct.coerceIn(FEED_FLING_PCT_RANGE) / 100f
        fun y(f: Float) = (h * f).coerceIn(safe.top.toFloat(), (h - safe.bottom).toFloat())
        return when (action) {
            "swipe_up" -> floatArrayOf(cx, y(SwipeGeometry.FROM_V), cx, y(SwipeGeometry.FROM_V - d))
            "swipe_down" -> floatArrayOf(cx, y(1 - SwipeGeometry.FROM_V), cx, y(1 - SwipeGeometry.FROM_V + d))
            else -> null
        }
    }

    /**
     * [step]: a no-momentum step in [list]; else a fling, and [feed] says the main scroller is a paged feed (TikTok,
     * Reels, Shorts, any vertical pager): voice scroll and next/previous must fling there too, never ACTION_SCROLL
     * (TikTok's pager accepts it and does not move), and the fling is [feedLine] (`feed_fling_pct`) in `feed_fling_ms`.
     */
    data class Decision(val step: Boolean, val why: String, val list: NodeSnap? = null, val feed: Boolean = false)

    fun decide(action: String, pkg: String?, scrollers: List<ScrollerSnap>, screenH: Int): Decision {
        if (action == "swipe_left" || action == "swipe_right") return Decision(false, "sideways: pagers and carousels need the fling")
        if (action != "swipe_up" && action != "swipe_down") return Decision(false, "not a swipe")
        return when (val c = classify(pkg, scrollers, screenH)) {
            is Kind.Fling -> c.d
            is Kind.List -> listStep(action, c.main.node)
        }
    }

    /** What a vertical swipe meets, whatever its direction: rules 1-4 end in [Kind.Fling]; else the main list ([Kind.List]). */
    sealed class Kind {
        data class Fling(val d: Decision) : Kind()
        data class List(val main: ScrollerSnap) : Kind()
    }

    /** Rules 1-4 of [decide] (they do not depend on the direction); [FeedKindCache]'s background read keeps the result. */
    fun classify(pkg: String?, scrollers: List<ScrollerSnap>, screenH: Int): Kind {
        val vis = scrollers.filter { it.node.visible && it.node.area > 0 }
        // a big scroller whose id names a video feed wins (Reels: clips_viewer_view_pager, a ViewPager, sits under a
        // horizontal tab pager of the same size, and ScrollPick would take one of the horizontal ones)
        val main = vis.firstOrNull { feedId(it.node) != null && it.node.height * 2 >= screenH }
            ?: ScrollPick.best(vis, { it.node.area }, { horizontal(it.node) }) ?: return Kind.Fling(Decision(false, "no scrollable list"))
        val n = main.node
        // a ViewPager is horizontal by default, unless its id names a video feed (Reels' clips_viewer_view_pager)
        if (horizontal(n) && feedId(n) == null) return Kind.Fling(Decision(false, "main scroller ${n.shortCls} is horizontal"))
        // before the end check: a feed's scroll actions do not say whether it can page (TikTok says "at the bottom")
        pagerWhy(main, screenH)?.let { return Kind.Fling(Decision(false, "pager: $it", feed = true)) }
        if (pkg in PAGER_PKGS && n.height * 5 >= screenH * 3) return Kind.Fling(Decision(false, "pager app (fallback list): $pkg", feed = true))
        return Kind.List(main)
    }

    /** Rules 5-6 of [decide] on the main list [n] (or its live state, refreshed just before a cached step). */
    fun listStep(action: String, n: NodeSnap): Decision {
        val can = if (action == "swipe_up") n.canScrollForward else n.canScrollBackward
        if (!can) return Decision(false, "${n.shortCls} is at its end that way")
        return Decision(true, "list ${n.shortCls}${n.id?.let { "#" + it.substringAfter('/') } ?: ""}", n)
    }

    fun horizontal(n: NodeSnap) = ScrollPick.horizontal(n.cls, n.rows, n.cols)

    /** Why [s] is a paged feed, or null for an ordinary list. */
    fun pagerWhy(s: ScrollerSnap, screenH: Int): String? {
        val n = s.node
        if (n.cls.contains("ViewPager") || n.shortCls.endsWith("Pager")) return "class ${n.shortCls}"
        if (s.parentCls?.contains("ViewPager2") == true) return "ViewPager2 page list"
        val id = n.id?.substringAfter('/')?.lowercase()
        if (id != null) PAGER_ID_HINTS.firstOrNull { id.contains(it) }?.let { return "id $id" }
        if (WHOLE_CONTENT.any { n.cls.endsWith(it) }) return null
        if (n.height * 2 < screenH) return null
        return pageFill(n)?.let { "one page fills the viewport ($it)" }
    }

    /**
     * One page fills [n]: among its visible children that are at least a tenth of it (small overlays such as a
     * feed's side buttons or caption are ignored), 1 or 2, one covering 80% of its height and width. Null if not.
     */
    fun pageFill(n: NodeSnap): String? {
        val big = n.children.filter { it.visible && it.area > 0 && it.area * 10 >= n.area }
        if (big.size !in 1..2 || big.none { it.height * 5 >= n.height * 4 && it.width * 5 >= n.width * 4 }) return null
        val small = n.children.count { it.visible && it.area > 0 } - big.size
        return "${big.size} page${if (big.size == 1) "" else "s"} visible" + if (small > 0) ", $small overlay${if (small == 1) "" else "s"}" else ""
    }

    /** The view id names a paged video feed (Reels' clips_viewer_view_pager, Shorts' reel_recycler), else null. */
    fun feedId(n: NodeSnap): String? {
        val id = n.id?.substringAfter('/')?.lowercase() ?: return null
        return id.takeIf { FEED_ID_HINTS.any { h -> id.contains(h) } }
    }

    /** Full-bleed: from the very top (under the status bar) over nearly the whole screen, as TikTok / Reels / Shorts. */
    fun immersive(n: NodeSnap, screenW: Int, screenH: Int): Boolean =
        n.top * 100 <= screenH * 6 && n.height * 5 >= screenH * 4 && n.width * 100 >= screenW * 95

    /**
     * The step's stroke [x1, y1, x2, y2] inside [list], or null when the band left is too short (then fling).
     * Length: [StepSize.frac] of the list's height plus [slop] (the list ignores the first slop px of a drag), capped
     * by the band. The stroke is centred in the band: the list's inside (less [EDGE]), the fling's band for that
     * direction, and outside the system gesture insets.
     */
    fun line(action: String, list: NodeSnap, w: Int, h: Int, safe: SwipeGeometry.Safe, size: StepSize, slop: Int = 0): FloatArray? {
        val up = action == "swipe_up"
        val pad = list.height * EDGE
        val top = maxOf(list.top + pad, h * (if (up) UP_TOP else DOWN_TOP), safe.top.toFloat())
        val bottom = minOf(list.bottom - pad, h * (if (up) UP_BOTTOM else DOWN_BOTTOM), (h - safe.bottom).toFloat())
        val band = bottom - top
        if (band < h * MIN_BAND) return null
        val len = minOf(list.height * size.frac + slop, band)
        val c = (top + bottom) / 2
        val x = ((list.left + list.right) / 2f).coerceIn(safe.left.toFloat(), (w - safe.right).toFloat())
        return if (up) floatArrayOf(x, c + len / 2, x, c - len / 2) else floatArrayOf(x, c - len / 2, x, c + len / 2)
    }
}

/** Reads the visible scrollers of the app window for [ScrollStep] (cheap: bounds and children of scrollers only). */
object ScrollerReader {
    private const val MAX_NODES = 1500

    /** One scroller (or child) as the planner sees it: bounds, scroll actions, visibility, CollectionInfo. */
    fun snap(n: AccessibilityNodeInfo, kids: List<NodeSnap> = emptyList(), r: Rect = Rect()): NodeSnap {
        n.getBoundsInScreen(r)
        val ci = n.collectionInfo
        val acts = n.actionList
        return NodeSnap(
            cls = n.className?.toString() ?: "", id = n.viewIdResourceName, text = null, desc = null,
            left = r.left, top = r.top, right = r.right, bottom = r.bottom,
            scrollable = n.isScrollable,
            canScrollForward = acts.contains(AccessibilityNodeInfo.AccessibilityAction.ACTION_SCROLL_FORWARD) ||
                acts.contains(AccessibilityNodeInfo.AccessibilityAction.ACTION_SCROLL_DOWN),
            canScrollBackward = acts.contains(AccessibilityNodeInfo.AccessibilityAction.ACTION_SCROLL_BACKWARD) ||
                acts.contains(AccessibilityNodeInfo.AccessibilityAction.ACTION_SCROLL_UP),
            visible = n.isVisibleToUser, rows = ci?.rowCount ?: -1, cols = ci?.columnCount ?: -1, children = kids,
        )
    }

    fun read(root: AccessibilityNodeInfo): List<ScrollerSnap> = readNodes(root).map { it.first }

    /** [read] with each scroller's node (kept by [FeedKindCache] to re-check a cached list just before a step). */
    fun readNodes(root: AccessibilityNodeInfo): List<Pair<ScrollerSnap, AccessibilityNodeInfo>> {
        val out = ArrayList<Pair<ScrollerSnap, AccessibilityNodeInfo>>()
        val r = Rect()
        val stack = ArrayDeque<Pair<AccessibilityNodeInfo, String?>>().apply { add(root to null) }
        var seen = 0
        while (stack.isNotEmpty() && seen++ < MAX_NODES) {
            val (x, parentCls) = stack.removeLast()   // children pushed in reverse: pre-order, as ScrollPick expects
            val children = (0 until x.childCount).mapNotNull { x.getChild(it) }
            if (x.isScrollable && x.isVisibleToUser) {
                val kids = children.map { snap(it, emptyList(), r) }
                out += ScrollerSnap(snap(x, kids, r), parentCls) to x
            }
            val cls = x.className?.toString()
            for (c in children.asReversed()) stack.add(c to cls)
        }
        return out
    }
}
