package ai.vox.companion

import org.json.JSONArray
import org.json.JSONObject

/** A plain snapshot of one accessibility node (no Android types, so classification is unit-testable). */
data class NodeSnap(
    val cls: String,
    val id: String?,
    val text: String?,
    val desc: String?,
    val left: Int, val top: Int, val right: Int, val bottom: Int,
    val scrollable: Boolean = false,
    val canScrollForward: Boolean = false,
    val canScrollBackward: Boolean = false,
    val editable: Boolean = false,
    val focused: Boolean = false,
    val clickable: Boolean = false,
    val visible: Boolean = true,
    val focusable: Boolean = false,
    val selected: Boolean = false,
    val collectionItem: Boolean = false,   // has CollectionItemInfo (a row/cell of a list or grid)
    val rows: Int = -1,           // CollectionInfo row count (-1 = none)
    val cols: Int = -1,
    val drawingOrder: Int = 0,    // AccessibilityNodeInfo.getDrawingOrder among its siblings (0 = unknown, e.g. Compose)
    val children: List<NodeSnap> = emptyList(),
) {
    val width get() = (right - left).coerceAtLeast(0)
    val height get() = (bottom - top).coerceAtLeast(0)
    val area get() = width.toLong() * height
    fun walk(): Sequence<NodeSnap> = sequence {
        yield(this@NodeSnap)
        for (c in children) yieldAll(c.walk())
    }
    val shortCls get() = cls.substringAfterLast('.')
}

/**
 * Which scroller is the screen's main list (SCREEN_SCROLL, and the node Executor scrolls for scroll_up/down).
 * Several scrollers often share the biggest area: Instagram's home is a horizontal tab ViewPager > a horizontal nav
 * RecyclerView > the vertical feed, all [0,94][1080,2388]. Taking the first (outermost) of them described the tab
 * pager, which on its first page can only go "forward": "at the top" however far the feed was scrolled (Instagram,
 * WhatsApp), and a node-scroll there would page sideways. So a vertical-looking scroller wins over a horizontal one
 * when it is at least half the size, and among near-equal ones (within 80%) the innermost (last in pre-order) wins.
 */
object ScrollPick {
    /** Horizontal by CollectionInfo (one row, several columns) or by class (ViewPager without vertical rows, HorizontalScrollView). */
    fun horizontal(cls: String?, rows: Int, cols: Int): Boolean {
        val c = cls ?: ""
        return rows == 1 && cols > 1 || c.endsWith("HorizontalScrollView") || c.endsWith("ViewPager") && rows <= 1
    }

    /** [items] in tree pre-order. */
    fun <T> best(items: List<T>, area: (T) -> Long, horizontal: (T) -> Boolean): T? {
        if (items.isEmpty()) return null
        val top = items.maxOf(area)
        val vertical = items.filter { !horizontal(it) }
        val pool = if (vertical.isNotEmpty() && vertical.maxOf(area) * 2 >= top) vertical else items
        val m = pool.maxOf(area)
        return pool.lastOrNull { area(it) * 5 >= m * 4 }
    }
}

/** What the summariser knows beyond the node tree. */
data class ScreenFacts(
    val pkg: String,
    val screenW: Int,
    val screenH: Int,
    val keyboardOpen: Boolean,
    val launcherPkgs: Set<String>,
    val musicActive: Boolean,
    val windowCount: Int = 1,
)

/**
 * Accessibility tree -> the schema's screen line (SCREEN_KIND / SCREEN_MEDIA / SCREEN_SCROLL / SCREEN_KEYBOARD).
 * Heuristic by nature; `harvest` records the line next to the raw summary so the heuristics and the training data's
 * APP_SCREENS can be checked against real screens.
 */
object ScreenSummarizer {
    private val VIDEO_SURFACES = listOf("SurfaceView", "TextureView", "VideoView", "PlayerView", "StyledPlayerView")
    private val WEB = listOf("WebView", "GeckoView")
    private val MAP_HINTS = listOf("map")
    private val CAMERA_PKGS = setOf("com.android.camera2", "com.google.android.GoogleCamera", "org.lineageos.aperture",
        "net.sourceforge.opencamera", "com.simplemobiletools.camera", "org.fossify.camera")
    private val MAP_PKGS = setOf("com.google.android.apps.maps", "app.organicmaps", "net.osmand", "net.osmand.plus")

    fun classify(root: NodeSnap?, f: ScreenFacts): ScreenContext {
        val keyboard = if (f.keyboardOpen) "open" else "hidden"
        if (root == null) return ScreenContext("other", if (f.musicActive) "playing" else "none", "not scrollable", keyboard)
        val nodes = root.walk().filter { it.visible }.toList()
        val screenArea = f.screenW.toLong() * f.screenH
        fun frac(n: NodeSnap) = if (screenArea == 0L) 0.0 else n.area.toDouble() / screenArea
        fun label(n: NodeSnap) = ((n.desc ?: "") + " " + (n.text ?: "")).trim().lowercase()

        val primaryScroll = ScrollPick.best(nodes.filter { it.scrollable }, { it.area }, { ScrollPick.horizontal(it.cls, it.rows, it.cols) })
        val scroll = when {
            primaryScroll == null -> "not scrollable"
            primaryScroll.canScrollForward && primaryScroll.canScrollBackward -> "can scroll both ways"
            primaryScroll.canScrollForward -> "at the top"
            primaryScroll.canScrollBackward -> "at the bottom"
            else -> "not scrollable"
        }

        val bigSurface = nodes.any { n -> VIDEO_SURFACES.any { n.cls.endsWith(it) } && n.width >= f.screenW * 0.9 && n.height >= f.screenH * 0.2 }
        val seekBar = nodes.any { it.cls.endsWith("SeekBar") || it.cls.endsWith("Slider") || (it.id ?: "").contains("seek", true) || (it.id ?: "").contains("progress", true) && it.width > f.screenW / 2 }
        val pauseCtl = nodes.any { label(it).let { l -> l == "pause" || l.startsWith("pause ") || l.startsWith("pause video") } }
        val playCtl = nodes.any { label(it).let { l -> l == "play" || l.startsWith("play ") && !l.startsWith("play all") || l.startsWith("play video") } }

        // A pager: a big scroller showing one dominant page ([ScrollStep.pageFill]; small overlays such as a feed's side
        // buttons and caption are ignored), or one whose view id names a video feed ([ScrollStep.feedId]: Reels,
        // Shorts). It is a feed only if that page is not itself a list (NewPipe's and VLC's tab pagers wrap
        // RecyclerViews that fill the page) and not just a still image (a photo pager).
        val pagers = nodes.filter { n ->
            n.scrollable && frac(n) >= 0.6 && n.rows != 0 && (ScrollStep.pageFill(n) != null || ScrollStep.feedId(n) != null)
        }
        fun pageOf(p: NodeSnap) = p.children.filter { it.visible }.maxByOrNull { it.area }
        fun imageOn(page: NodeSnap?) = page != null && page.walk().any { it.cls.endsWith("ImageView") && it.area >= page.area * 0.5 }
        // Feed = a vertical pager (CollectionInfo rows > 1, one column, as vertical ViewPager2/RecyclerView report it),
        // a pager whose page shows video, a pager named as a feed, or a full-bleed pager ([ScrollStep.immersive]:
        // TikTok's feed pager reports no CollectionInfo and no video view) whose page is not a still image.
        // A horizontal tab pager with an empty page is not a feed. Pagers nest (TikTok: two tab pagers around the
        // feed pager), so the first pager that is a feed counts; an outer one whose page holds the feed is a list.
        fun isFeed(p: NodeSnap): Boolean {
            val page = pageOf(p) ?: return false
            if (ScrollStep.feedId(p) != null) return true   // named as a video feed (its page may be its own inner list)
            if (page.walk().any { it.scrollable && it.area * 2 >= page.area }) return false   // a list (or a pager) fills the page
            val video = page.walk().any { d -> VIDEO_SURFACES.any { d.cls.endsWith(it) } } || pauseCtl || playCtl
            val vertical = p.rows > 1 && p.cols <= 1
            return video || (vertical || ScrollStep.immersive(p, f.screenW, f.screenH)) && !imageOn(page)
        }
        val pager = pagers.firstOrNull()
        val pageImage = pager != null && imageOn(pageOf(pager))
        // Package fallback ([ScrollStep.PAGER_PKGS], TikTok): its main vertical scroller when that covers most of the
        // screen, as ScrollStep.decide has it.
        val feed = pagers.firstOrNull(::isFeed)
            ?: primaryScroll?.takeIf { f.pkg in ScrollStep.PAGER_PKGS && it.height * 5 >= f.screenH * 3 && !ScrollStep.horizontal(it) }

        val kind = when {
            f.keyboardOpen && nodes.any { it.editable && it.focused } -> "text entry"
            f.pkg in f.launcherPkgs -> "home screen"
            root.area in 1 until (screenArea * 0.6).toLong() && root.width < f.screenW -> "dialog"
            f.pkg in CAMERA_PKGS -> "camera viewfinder"
            f.pkg in MAP_PKGS || nodes.any { n -> frac(n) >= 0.4 && MAP_HINTS.any { h -> (n.id ?: "").substringAfter('/').contains(h, true) || n.shortCls.contains("MapView") } } -> "map"
            nodes.any { n -> WEB.any { n.cls.endsWith(it) } && frac(n) >= 0.4 } -> "web page"
            feed != null -> "video feed"
            bigSurface || (seekBar && (pauseCtl || playCtl)) -> "video player"
            pageImage || nodes.any { it.cls.endsWith("ImageView") && frac(it) >= 0.5 } || nodes.any { (it.id ?: "").contains("photo", true) && frac(it) >= 0.5 } -> "photo viewer"
            nodes.any { !it.editable && (it.text?.length ?: 0) >= 600 && frac(it) >= 0.3 } -> "document"
            primaryScroll != null && frac(primaryScroll) >= 0.3 -> "scrolling list"
            else -> "other"
        }
        val mediaUi = kind == "video player" || kind == "video feed"
        val media = when {
            f.musicActive || (pauseCtl && (mediaUi || bigSurface)) -> "playing"
            playCtl && (mediaUi || bigSurface) -> "paused"
            else -> "none"
        }
        return ScreenContext(kind, media, scroll, keyboard)
    }

    /** Compact raw summary for harvest: enough to audit the heuristic without a full dump. */
    fun rawSummary(root: NodeSnap?, f: ScreenFacts): JSONObject {
        val o = JSONObject().put("package", f.pkg).put("screen", "${f.screenW}x${f.screenH}")
            .put("keyboard_open", f.keyboardOpen).put("music_active", f.musicActive).put("windows", f.windowCount)
        if (root == null) return o.put("root", JSONObject.NULL)
        val nodes = root.walk().filter { it.visible }.toList()
        val area = f.screenW.toLong() * f.screenH
        o.put("nodes", nodes.size)
        val classes = nodes.groupingBy { it.shortCls }.eachCount().entries.sortedByDescending { it.value }.take(15)
        o.put("classes", JSONObject().apply { classes.forEach { put(it.key, it.value) } })
        o.put("scrollables", JSONArray().apply {
            nodes.filter { it.scrollable }.sortedByDescending { it.area }.take(6).forEach { n ->
                put(JSONObject().put("cls", n.shortCls).put("id", n.id ?: "").put("area_pct", pct(n.area, area))
                    .put("fwd", n.canScrollForward).put("back", n.canScrollBackward).put("rows", n.rows).put("cols", n.cols)
                    .put("children", n.children.size))
            }
        })
        o.put("large", JSONArray().apply {
            nodes.filter { it.area >= area * 0.25 && it.children.isEmpty() || it.area >= area * 0.25 && it.cls.let { c -> VIDEO_SURFACES.any(c::endsWith) || WEB.any(c::endsWith) } }
                .sortedByDescending { it.area }.take(8).forEach { n ->
                    put(JSONObject().put("cls", n.shortCls).put("id", n.id ?: "").put("area_pct", pct(n.area, area)))
                }
        })
        o.put("texts", JSONArray().apply {
            nodes.mapNotNull { n -> (n.text ?: n.desc)?.trim()?.takeIf { it.isNotEmpty() } }.distinct().take(25)
                .forEach { put(it.take(48)) }
        })
        o.put("editable_focused", nodes.any { it.editable && it.focused })
        return o
    }

    private fun pct(a: Long, total: Long) = if (total == 0L) 0 else (a * 100 / total).toInt()
}
