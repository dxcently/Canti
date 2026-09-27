package ai.vox.companion

/**
 * Intent cursor mode: the user names an on-screen element ("the like button") and the model picks it from a list of
 * options built from the accessibility tree. Spec: the docstring of finetune/vox/targets.py; the option format must
 * match the training data exactly, NONE_OPTION last:
 *
 *   {label}[ · {context}] ({role}, {position}[, {rank}])
 *
 * [context] (row text for switches, generic and repeated labels) and [rank] (where it sits among its like) are set by
 * [Targets.build] ("OPTION FORMAT" there); without them the option is the original "{label} ({role}, {position})".
 */
data class Target(val label: String, val role: String, val position: String,
                  val left: Int, val top: Int, val right: Int, val bottom: Int,
                  val context: String? = null, val rank: String? = null) {
    val option: String get() = label + (context?.let { " · $it" } ?: "") + " ($role, $position" + (rank?.let { ", $it" } ?: "") + ")"
    val cx: Int get() = (left + right) / 2
    val cy: Int get() = (top + bottom) / 2
}

/** A screen rectangle: a window above the app, or a surface drawn over part of the tree. */
data class Box(val left: Int, val top: Int, val right: Int, val bottom: Int) {
    val empty get() = right <= left || bottom <= top
    val area get() = if (empty) 0L else (right - left).toLong() * (bottom - top)
    fun contains(x: Int, y: Int) = x in left until right && y in top until bottom
    fun intersect(o: Box) = Box(maxOf(left, o.left), maxOf(top, o.top), minOf(right, o.right), minOf(bottom, o.bottom))
}

/**
 * What the user can actually see and tap. isVisibleToUser only knows the node's own window: it ignores other windows
 * above it (keyboard, status and navigation bars, popups, dialogs) and views drawn over it in the same window (an open
 * drawer, a bottom sheet, a scrim). A target is hidden if less than [MIN_VISIBLE_SHARE] of its on-screen area is
 * uncovered (a sliver under the status bar), or its centre is covered and no visible piece is big enough to tap
 * ([visiblePart]; a kept one is then tapped on that piece).
 */
object Occlusion {
    const val MIN_VISIBLE_SHARE = 0.25
    /** A scrim covers at least this share of the screen. */
    private const val SCRIM_SHARE = 0.5
    private val SCRIM_LABELS = setOf("close navigation menu", "close drawer", "close sheet", "dismiss", "close menu", "scrim")

    /** The parts of [r] not under any of [covers]. */
    fun uncovered(r: Box, covers: List<Box>): List<Box> {
        var parts = if (r.empty) emptyList() else listOf(r)
        for (c in covers) {
            parts = parts.flatMap { p ->
                val i = p.intersect(c)
                if (i.empty) listOf(p) else listOf(
                    Box(p.left, p.top, p.right, i.top), Box(p.left, i.bottom, p.right, p.bottom),
                    Box(p.left, i.top, i.left, i.bottom), Box(i.right, i.top, p.right, i.bottom),
                ).filter { !it.empty }
            }
            if (parts.isEmpty()) break
        }
        return parts
    }

    fun hidden(r: Box, covers: List<Box>, screen: Box): Boolean = visiblePart(r, covers, screen) == null

    /** A partly covered target whose centre is covered is kept only if a visible piece is at least this wide and tall. */
    const val MIN_TAP_SIDE = 40

    /**
     * Where [r] can be tapped: null if hidden (off screen, or less than [MIN_VISIBLE_SHARE] of its on-screen area
     * uncovered); [r] itself if its centre is uncovered; else (the centre is under a cover: a floating button half
     * under the navigation bar) the largest uncovered piece, if it is at least [MIN_TAP_SIDE] both ways, so the tap
     * lands on what can be seen, not on the cover.
     */
    fun visiblePart(r: Box, covers: List<Box>, screen: Box): Box? {
        val on = r.intersect(screen)
        if (on.empty) return null
        if (covers.isEmpty()) return r
        val parts = uncovered(on, covers)
        if (parts.sumOf { it.area }.toDouble() / on.area < MIN_VISIBLE_SHARE) return null
        val cx = (r.left + r.right) / 2; val cy = (r.top + r.bottom) / 2
        if (covers.none { it.contains(cx, cy) }) return r
        return parts.maxByOrNull { it.area }?.takeIf { it.right - it.left >= MIN_TAP_SIDE && it.bottom - it.top >= MIN_TAP_SIDE }
    }

    /**
     * A surface drawn over every node that precedes [start] in pre-order and is not its ancestor; with [end] >= 0 (a
     * popup, whose subtree is [start]..[end]) also over every node after its subtree. With [under] set, over exactly
     * the nodes whose pre-order index is in it (a sibling's subtree drawn below it).
     */
    data class Surface(val start: Int, val box: Box, val kind: String, val end: Int = -1, val under: IntRange? = null) {
        /** Whether it is drawn over the node whose subtree is [nodeStart]..[nodeEnd] (boxes aside). */
        fun over(nodeStart: Int, nodeEnd: Int) = under?.let { nodeStart in it } ?: (start > nodeEnd || (end >= 0 && nodeStart > end))
    }

    /** A sibling drawn above another covers it only if its visible leaves fill at least 3/10 of its box ([fills]). */
    private const val ABOVE_FILL_TENTHS = 3

    /**
     * Whether [n] looks opaque: the areas of its visible leaf descendants (clipped to its box) add up to at least
     * [ABOVE_FILL_TENTHS] tenths of its area. A full-player sheet is full of views; a transparent full-screen layer
     * holding only a floating button is not.
     */
    fun fills(n: NodeSnap): Boolean {
        val me = Box(n.left, n.top, n.right, n.bottom)
        if (me.empty) return false
        var sum = 0L
        for (d in n.walk().drop(1)) if (d.visible && d.children.none { it.visible }) sum += Box(d.left, d.top, d.right, d.bottom).intersect(me).area
        return sum * 10 >= me.area * ABOVE_FILL_TENTHS
    }

    /** A popup reaches at least this far outside its parent's box. */
    private const val POPUP_OVERHANG = 24

    /** A sheet with fewer visible parts than this, none of them labelled or tappable, shows nothing (see [showsContent]). */
    private const val SHEET_MIN_PARTS = 2

    /**
     * Whether a sheet container shows anything: a visible descendant with an area that has a label or can be tapped,
     * or at least [SHEET_MIN_PARTS] visible descendants with an area. An empty container covers nothing: Instagram's feed
     * keeps a childless, feed-sized `bottom_sheet_…_container` in its tree, and counting it hid every target.
     */
    fun showsContent(sheet: NodeSnap): Boolean {
        var parts = 0
        for (d in sheet.walk().drop(1)) {
            if (!d.visible || d.area <= 0) continue
            if (d.clickable || d.focusable || d.editable || Targets.clean(d.desc) != null || Targets.clean(d.text) != null) return true
            if (++parts >= SHEET_MIN_PARTS) return true
        }
        return false
    }

    /**
     * Surfaces inside one window's tree ([order]: pre-order index of each node):
     *  - an open drawer: a DrawerLayout child after the first that is visible on screen; it hides the whole DrawerLayout
     *    area (the rest is behind its scrim, and a tap there only closes the drawer);
     *  - a bottom sheet (class or id "BottomSheet" / "bottom_sheet") that [showsContent];
     *  - a scrim: a clickable node over at least half the screen, labelled like "Close navigation menu", or with an id
     *    ending in touch_outside / scrim;
     *  - a contextual bar drawn over the toolbar ([OVERLAY_BAR]: the action mode bar of a search or selection mode, an
     *    "overlay toolbar") that [showsContent]: Wikipedia's search mode, a file manager's selection toolbar;
     *  - a snackbar: the parent of a `snackbar_text` / `snackbar_action` node (a button under it is hidden);
     *  - a popup drawn in the app's own window (a Compose overflow menu without a Popup window, Glider): a node that
     *    [showsContent], smaller than half the screen, reaching at least [POPUP_OVERHANG] px outside its visible
     *    parent's box. Views are clipped to their parent, so only something drawn on top gets out; it hides what is
     *    under it before and after it in the tree, its own subtree and ancestors aside;
     *  - a sibling drawn above another ([NodeSnap.drawingOrder], both known): if it [showsContent] and [fills] its box,
     *    it hides the lower sibling's subtree where they overlap. AntennaPod's full player is a bottom sheet in the
     *    app's window, before the page it covers in the tree (larger first) but drawn after it.
     *
     * Not every later node: the accessibility order sorts siblings by position (larger first), not by drawing order, so
     * "later in the tree" does not mean "drawn on top" in general (LibreTube's expanded player comes before the toolbar
     * it covers). Only these widgets, which are always drawn above what they overlap, count.
     */
    fun surfaces(root: NodeSnap, order: java.util.IdentityHashMap<NodeSnap, IntArray>, screenW: Int, screenH: Int): List<Surface> {
        val out = mutableListOf<Surface>()
        val screenArea = screenW.toLong() * screenH
        fun box(n: NodeSnap) = Box(n.left, n.top, n.right, n.bottom)
        fun visit(n: NodeSnap, parent: NodeSnap?) {
            for (c in n.children) visit(c, n)
            if (!n.visible) return
            val idx = order[n]?.get(0) ?: return
            if (n.shortCls == "DrawerLayout") {
                n.children.drop(1).firstOrNull { it.visible && it.width > 0 && it.height > 0 }?.let { d ->
                    out += Surface(order[d]!![0], box(n), "drawer")
                }
            }
            val idTail = n.id?.substringAfterLast('/')?.lowercase().orEmpty()
            if ((n.shortCls.contains("BottomSheet") || idTail.contains("bottom_sheet")) && n.area > 0 && showsContent(n)) out += Surface(idx, box(n), "sheet")
            if (OVERLAY_BAR.containsMatchIn(idTail) && n.area > 0 && showsContent(n)) out += Surface(idx, box(n), "bar")
            if ((idTail == "snackbar_text" || idTail == "snackbar_action") && parent != null && parent.visible && parent.area > 0)
                order[parent]?.let { out += Surface(it[0], box(parent), "snackbar") }
            val label = Targets.clean(n.desc ?: n.text)?.lowercase()
            if (n.clickable && n.area >= SCRIM_SHARE * screenArea &&
                (label in SCRIM_LABELS || idTail.endsWith("touch_outside") || idTail.endsWith("scrim"))) out += Surface(idx, box(n), "scrim")
            if (parent != null && parent.visible && parent.area > 0 && n.area > 0 && n.area < SCRIM_SHARE * screenArea &&
                maxOf(parent.left - n.left, n.right - parent.right, parent.top - n.top, n.bottom - parent.bottom) >= POPUP_OVERHANG &&
                showsContent(n)) out += Surface(idx, box(n), "popup", order[n]!![1])
            val drawn = n.children.filter { it.visible && it.drawingOrder > 0 && it.area > 0 }
            if (drawn.size >= 2) for (s in drawn) {
                val lower = drawn.filter { it.drawingOrder < s.drawingOrder && !box(it).intersect(box(s)).empty }
                if (lower.isEmpty() || !showsContent(s) || !fills(s)) continue
                for (b in lower) order[b]?.let { r -> out += Surface(order[s]!![0], box(s), "above", under = r[0]..r[1]) }
            }
        }
        visit(root, null)
        return out.distinct()
    }

    /** Resource-id tails of bars drawn over the toolbar while a search or selection mode is on. */
    private val OVERLAY_BAR = Regex("action_?mode_?bar|overlay_?tool_?bar|tool_?bar_?overlay|selection_?tool_?bar|contextual_?(action_?)?bar")
}

object Targets {
    /** At most this many options on the wire, NONE_OPTION included (39 elements + none). */
    const val MAX_OPTIONS = 40
    const val MAX_LABEL_CHARS = 60
    /** A focusable-but-not-clickable node covering more than this share of the screen is a container, not a target. */
    private const val CONTAINER_SHARE = 0.5
    private val LIST_CLASSES = setOf("RecyclerView", "ListView", "GridView")

    // --- the three parts of an option --------------------------------------------------------------------------------

    /** 3x3 bucket of a point: row * 3 + col. A point exactly on a third-line belongs to the cell below/right of it. */
    fun bucket(cx: Int, cy: Int, screenW: Int, screenH: Int): Int {
        val col = if (screenW <= 0) 1 else (cx.toLong() * 3 / screenW).toInt().coerceIn(0, 2)
        val row = if (screenH <= 0) 1 else (cy.toLong() * 3 / screenH).toInt().coerceIn(0, 2)
        return row * 3 + col
    }

    fun position(cx: Int, cy: Int, screenW: Int, screenH: Int): String = TargetVocab.POSITIONS[bucket(cx, cy, screenW, screenH)]

    /** Whitespace collapsed to single spaces (an option is one line), null if empty, capped at MAX_LABEL_CHARS. */
    fun clean(s: String?): String? {
        val t = s?.replace(Regex("\\s+"), " ")?.trim()?.takeIf { it.isNotEmpty() } ?: return null
        return if (t.length <= MAX_LABEL_CHARS) t else t.take(MAX_LABEL_CHARS - 3).trimEnd() + "..."
    }

    /**
     * contentDescription, else text, else (addition to the spec, see README) the first text of a descendant that is
     * not itself clickable/focusable, as TalkBack reads a row whose title sits on a child view ([DESCENDANT_PASSES]:
     * a title before an icon's contentDescription, RadioDroid's station row is its name, not its "Popularity
     * increasing" trend icon; a bare number last), else a name made from the view id and the widget ([idName]; never
     * the raw id), else "unlabeled".
     */
    fun label(n: NodeSnap): String {
        clean(n.desc)?.let { return it }
        clean(n.text)?.let { return it }
        DESCENDANT_PASSES.firstNotNullOfOrNull { descendantText(n, 0, it) }?.let { return it }
        return clean(idName(n)) ?: "unlabeled"
    }

    /** Widget-prefix and filler words of view ids, dropped by [idName]: imgvCover, sbPosition, like_btn, card_view. */
    val ID_FILLER = setOf("img", "imgv", "iv", "image", "imageview", "txt", "txtv", "tv", "text", "textview", "btn", "but",
        "button", "ib", "imgbtn", "sb", "seekbar", "pb", "fab", "cb", "chk", "checkbox", "sw", "switch", "et", "edittext",
        "rv", "lv", "ll", "fl", "rl", "cl", "vg", "layout", "view", "container", "holder", "wrapper", "item", "id")

    /** The widget noun [idName] appends, by class name without an AppCompat / Material prefix. */
    val WIDGET_NOUNS = mapOf("ImageView" to "image", "ImageButton" to "button", "Button" to "button",
        "FloatingActionButton" to "button", "SeekBar" to "seek bar", "Slider" to "slider", "ProgressBar" to "progress bar",
        "RatingBar" to "rating bar", "Switch" to "switch", "SwitchCompat" to "switch", "CheckBox" to "checkbox",
        "RadioButton" to "radio button", "ToggleButton" to "toggle", "EditText" to "text field",
        "TextInputEditText" to "text field", "Spinner" to "dropdown", "Chip" to "chip")

    /** A last id word that already says what the control is: no widget noun after it (volume_slider, app_icon). */
    val ID_NAMED = setOf("icon", "image", "picture", "photo", "avatar", "thumbnail", "logo", "button", "slider", "switch",
        "toggle", "box", "field", "chip", "card", "dropdown")

    private val ID_SPLIT = Regex("[_\\-.\\s]+|(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

    /**
     * A name for a node with no text of its own or under it: the words of its view id tail (split at "_", "-", "."
     * and camelCase; lowercased; [ID_FILLER] and bare numbers dropped), then the widget noun ([WIDGET_NOUNS]) unless
     * the words already end with it or with a word of [ID_NAMED]: imgvCover (ImageView) -> "cover image", sbPosition (SeekBar) -> "position seek
     * bar", like_btn (ImageButton) -> "like button", card_view (LinearLayout) -> "card"; no words (fab, view_3): the
     * noun alone; no id, or neither: null ("unlabeled"). Never the raw id.
     */
    fun idName(n: NodeSnap): String? {
        if (n.id.isNullOrBlank()) return null
        val words = n.id?.substringAfterLast('/').orEmpty().split(ID_SPLIT).map { it.lowercase(java.util.Locale.ROOT) }
            .filter { it.isNotEmpty() && it !in ID_FILLER && !it.all(Char::isDigit) }.joinToString(" ")
        val noun = WIDGET_NOUNS[n.shortCls.removePrefix("AppCompat").removePrefix("Material")]
        return when {
            noun != null && words.isNotEmpty() && !words.endsWith(noun) && words.substringAfterLast(' ') !in ID_NAMED -> "$words $noun"
            words.isNotEmpty() -> words
            else -> noun
        }
    }

    /**
     * What a row's descendants are read for, in order (for a label and for a context): a text with a letter in it (a
     * title), else a contentDescription (an icon's), else any text (a count: Jerboa's vote button is "Upvote", not "29").
     */
    private val DESCENDANT_PASSES: List<(NodeSnap) -> String?> =
        listOf({ n -> n.text?.takeIf { t -> t.any { it.isLetter() } } }, { n -> n.desc }, { n -> n.text })

    private fun descendantText(n: NodeSnap, depth: Int, field: (NodeSnap) -> String?): String? {
        if (depth > 8) return null
        for (c in n.children) {
            if (!c.visible || c.clickable || c.focusable) continue   // a nested tappable element is its own option
            clean(field(c))?.let { return it }
            descendantText(c, depth + 1, field)?.let { return it }
        }
        return null
    }

    /**
     * Button/ImageButton -> button, EditText -> text field, Switch/CheckBox -> switch, TabWidget child or a tab-strip
     * member -> tab, ImageView -> image, list rows -> list item, else item.
     * Tab strip: siblings of one class laid out in one row, one of them selected (TabLayout, bottom navigation).
     */
    fun role(n: NodeSnap, parent: NodeSnap?): String {
        val c = n.shortCls
        return when {
            c == "EditText" || n.editable -> "text field"
            c == "Switch" || c == "CheckBox" -> "switch"
            isTab(n, parent) -> "tab"
            c == "Button" || c == "ImageButton" -> "button"
            isListItem(n, parent) -> "list item"
            c == "ImageView" -> "image"
            else -> "item"
        }
    }

    private fun isTab(n: NodeSnap, parent: NodeSnap?): Boolean {
        val c = n.shortCls
        if (c.endsWith("\$Tab") || c == "TabView" || parent?.shortCls == "TabWidget") return true
        val sibs = parent?.children?.filter { it.visible } ?: return false
        if (sibs.size < 2 || sibs.none { it.selected }) return false
        return sibs.all { it.shortCls == c && kotlin.math.abs(it.top - n.top) <= 8 && kotlin.math.abs(it.height - n.height) <= 8 }
    }

    private fun isListItem(n: NodeSnap, parent: NodeSnap?): Boolean =
        n.collectionItem || (parent != null && (parent.shortCls in LIST_CLASSES || parent.rows > 0 || parent.cols > 0))

    // --- the option list ---------------------------------------------------------------------------------------------

    fun isTarget(n: NodeSnap, screenW: Int, screenH: Int): Boolean {
        if (!n.visible || !(n.clickable || n.focusable) || n.width <= 0 || n.height <= 0) return false
        if (n.scrollable && !n.clickable) return false   // a scrolling container
        if (!n.clickable && n.area > CONTAINER_SHARE * screenW.toLong() * screenH) return false
        // A focusable-only container without its own label that holds other targets (a tab strip, a card): its
        // children are the options.
        if (!n.clickable && clean(n.desc) == null && clean(n.text) == null && n.children.any { hasTargetInside(it) }) return false
        val cx = (n.left + n.right) / 2; val cy = (n.top + n.bottom) / 2
        return cx in 0 until screenW && cy in 0 until screenH
    }

    // An invisible node can still hold visible targets (Compose's AndroidView holder, TreeReader.descends): look through it.
    private fun hasTargetInside(n: NodeSnap, depth: Int = 0): Boolean =
        depth < 12 && ((n.visible && (n.clickable || n.focusable)) || n.children.any { hasTargetInside(it, depth + 1) })

    /**
     * Targets in reading order: by 3x3 bucket (top row first, then left to right, the order the training data uses),
     * then by top and left edge inside a bucket; at most MAX_OPTIONS - 1 (see the layered [build]).
     */
    fun build(root: NodeSnap?, screenW: Int, screenH: Int, covers: List<Box> = emptyList(), format: String = OptionFormat.V1): List<Target> =
        build(listOfNotNull(root?.let { it to covers }), screenW, screenH, format)

    /** A target and the text of the row it sits in ([rowText]), before [build] decides whether the option shows it. */
    class Found(val target: Target, val rowText: String?)

    /** One window's tree and the windows above it. */
    fun collect(root: NodeSnap, screenW: Int, screenH: Int, covers: List<Box>): List<Found> {
        val order = java.util.IdentityHashMap<NodeSnap, IntArray>()
        var i = 0
        fun index(n: NodeSnap): Int { val me = IntArray(2); order[n] = me; me[0] = i++; for (c in n.children) index(c); me[1] = i - 1; return me[1] }
        index(root)
        val surfaces = Occlusion.surfaces(root, order, screenW, screenH)
        val screen = Box(0, 0, screenW, screenH)
        val found = mutableListOf<Found>()
        val path = ArrayList<NodeSnap>()   // ancestors of the node being visited, root first
        fun visit(n: NodeSnap) {
            if (isTarget(n, screenW, screenH)) {
                val (start, end) = order.getValue(n).let { it[0] to it[1] }
                val me = Box(n.left, n.top, n.right, n.bottom)
                // Only surfaces that overlap it: keeps the rectangle subtraction small on screens with many tappable nodes.
                val over = covers + surfaces.filter { it.over(start, end) && !it.box.intersect(me).empty }.map { it.box }
                // Its box, or the piece of it that can be seen when its centre is covered (the tap lands on the centre).
                Occlusion.visiblePart(me, over, screen)?.let { v ->
                    val cx = (v.left + v.right) / 2; val cy = (v.top + v.bottom) / 2
                    val lab = label(n)
                    found += Found(Target(lab, role(n, path.lastOrNull()), position(cx, cy, screenW, screenH), v.left, v.top, v.right, v.bottom),
                        rowText(n, lab, path, screenW, screenH))
                }
            }
            path += n
            for (c in n.children) visit(c)
            path.removeAt(path.size - 1)
        }
        visit(root)
        return found
    }

    // --- OPTION FORMAT -----------------------------------------------------------------------------------------------
    //
    //   {label}[ · {context}] ({role}, {position}[, {rank}])            (suite/tree_targets.py builds the same bytes)
    //
    // context: the row's text, only for a switch, a generic label ([GENERIC_LABELS], compared lowercased) or a label
    //   that more than one kept target has (lowercased): the first text with a letter (cleaned) met in pre-order
    //   under the nearest of up to [ROW_CLIMB] ancestors (nearest first; stop at one larger than half the screen), else
    //   the first description (an icon's) found the same way, else the first text ([DESCENDANT_PASSES]),
    //   skipping the target's own subtree and every invisible, clickable or focusable subtree (depth <= 8), whose
    //   vertical overlap with the target is > 0 and at least half the shorter height, and that is not the label itself
    //   (lowercased). Capped at [MAX_CONTEXT_CHARS] (27 chars + "..."). None found: no " · ".
    // rank, the first that applies:
    //   - column: targets of the same role whose horizontal overlap with it is > 0 and >= half the narrower width
    //     (itself included), sorted by top, left, reading order; row: same with vertical overlap / shorter height,
    //     sorted by left, top, reading order. Column when it has >= 2 and (more than the row, or as many and the role
    //     is not "tab"): "{k} of {n} down"; else row with >= 2: "{k} of {n} from left".
    //     {k} = "last" if k == n, else 1st 2nd 3rd 4th ... 11th 12th 13th ... 21st 22nd 23rd (English suffixes).
    //   - edge: others share its 3x3 bucket, the bucket is in the left (right) column, and its centre x is strictly
    //     left (right) of all of theirs: "far left" ("far right").
    //   - none.
    // Last, options that are still identical (same label, context, role, position, rank) get "{k} of {n}" in reading
    // order appended to the rank (", " after an existing rank), so every option names exactly one target.
    // Ranks, contexts and repeats are computed over the kept targets (after the MAX_OPTIONS cap).
    //
    // Only format "v2" ([OptionFormat], declared by the local target model) adds context and rank. "v1" is the original
    // "{label} ({role}, {position})" for models trained on it; there only options that would be identical (repeated
    // controls) get the "{k} of {n}" suffix: "Delete (button, right, 1st of 3)".

    const val MAX_CONTEXT_CHARS = 30
    private const val ROW_CLIMB = 3
    val GENERIC_LABELS = setOf("unlabeled", "more", "more options", "more actions", "onoff", "on off", "toggle", "switch", "checkbox",
        "play or pause", "media image", "channel image", "image", "icon", "button", "menu", "options", "overflow menu", "expand", "collapse")

    private fun vOverlap(aTop: Int, aBottom: Int, bTop: Int, bBottom: Int): Boolean {
        val ov = minOf(aBottom, bBottom) - maxOf(aTop, bTop)
        return ov > 0 && 2 * ov >= minOf(aBottom - aTop, bBottom - bTop)
    }

    /** The text of the row [n] sits in (see OPTION FORMAT), or null. [path]: its ancestors, root first. */
    fun rowText(n: NodeSnap, label: String, path: List<NodeSnap>, screenW: Int, screenH: Int): String? {
        val own = label.lowercase(java.util.Locale.ROOT)
        fun find(p: NodeSnap, depth: Int, field: (NodeSnap) -> String?): String? {
            if (depth > 8) return null
            for (c in p.children) {
                if (c === n || !c.visible || c.clickable || c.focusable) continue
                val t = clean(field(c))
                if (t != null && t.lowercase(java.util.Locale.ROOT) != own && vOverlap(c.top, c.bottom, n.top, n.bottom)) return t
                find(c, depth + 1, field)?.let { return it }
            }
            return null
        }
        // [DESCENDANT_PASSES] in order (a row's title before its icons', as in [label]), each nearest ancestor first.
        val near = path.asReversed().take(ROW_CLIMB).takeWhile { it.area <= CONTAINER_SHARE * screenW.toLong() * screenH }
        val t = DESCENDANT_PASSES.firstNotNullOfOrNull { f -> near.firstNotNullOfOrNull { a -> find(a, 0, f) } } ?: return null
        return if (t.length <= MAX_CONTEXT_CHARS) t else t.take(MAX_CONTEXT_CHARS - 3).trimEnd() + "..."
    }

    fun ordinal(k: Int, n: Int): String = if (k == n) "last" else k.toString() + when {
        k % 100 in 11..13 -> "th"
        k % 10 == 1 -> "st"
        k % 10 == 2 -> "nd"
        k % 10 == 3 -> "rd"
        else -> "th"
    }

    /** Context, rank and the last-resort repeat number for the kept targets, in reading order (see OPTION FORMAT). */
    fun decorate(kept: List<Found>, screenW: Int, screenH: Int, format: String = OptionFormat.V1): List<Target> {
        val v2 = format == OptionFormat.V2
        val ts = kept.map { it.target }
        val counts = ts.groupingBy { it.label.lowercase(java.util.Locale.ROOT) }.eachCount()
        fun b(t: Target) = bucket(t.cx, t.cy, screenW, screenH)
        val out = if (!v2) ts else ts.mapIndexed { i, t ->
            val low = t.label.lowercase(java.util.Locale.ROOT)
            val ctx = kept[i].rowText.takeIf { t.role == "switch" || low in GENERIC_LABELS || counts.getValue(low) >= 2 }
            val col = ts.indices.filter { j -> ts[j].role == t.role &&
                    (minOf(t.right, ts[j].right) - maxOf(t.left, ts[j].left)).let { ov -> ov > 0 && 2 * ov >= minOf(t.right - t.left, ts[j].right - ts[j].left) } }
                .sortedWith(compareBy({ ts[it].top }, { ts[it].left }, { it }))
            val row = ts.indices.filter { j -> ts[j].role == t.role && vOverlap(t.top, t.bottom, ts[j].top, ts[j].bottom) }
                .sortedWith(compareBy({ ts[it].left }, { ts[it].top }, { it }))
            val others = ts.indices.filter { it != i && b(ts[it]) == b(t) }
            val rank = when {
                col.size >= 2 && (col.size > row.size || (col.size == row.size && t.role != "tab")) ->
                    "${ordinal(col.indexOf(i) + 1, col.size)} of ${col.size} down"
                row.size >= 2 -> "${ordinal(row.indexOf(i) + 1, row.size)} of ${row.size} from left"
                others.isNotEmpty() && b(t) % 3 == 0 && others.all { ts[it].cx > t.cx } -> "far left"
                others.isNotEmpty() && b(t) % 3 == 2 && others.all { ts[it].cx < t.cx } -> "far right"
                else -> null
            }
            t.copy(context = ctx, rank = rank)
        }
        val same = out.indices.groupBy { out[it].option }
        return out.mapIndexed { i, t ->
            val g = same.getValue(t.option)
            if (g.size < 2) t else t.copy(rank = listOfNotNull(t.rank, "${ordinal(g.indexOf(i) + 1, g.size)} of ${g.size}").joinToString(", "))
        }
    }

    /** The same element found twice (nested nodes, two layers): same label and role, one's centre inside the other. */
    private fun sameElement(a: Target, b: Target) = a.label == b.label && a.role == b.role &&
        (Box(a.left, a.top, a.right, a.bottom).contains(b.cx, b.cy) || Box(b.left, b.top, b.right, b.bottom).contains(a.cx, a.cy))

    /**
     * Targets of the app's windows (each with the rects of the windows above it), in reading order: by 3x3 bucket (top
     * row first, then left to right, the order the training data uses), then by top and left edge inside a bucket.
     * The same element found twice keeps the first ([sameElement]); repeated identical controls (a "Delete" per row)
     * all stay, told apart by their context and rank ([decorate]). Over MAX_OPTIONS - 1, the least useful go first
     * ([keepRank]: unlabeled, then plain items and images, then list rows), so a labelled button at the end of the
     * reading order (a floating action button, bottom right) is not the one cut. Every option string is unique.
     */
    fun build(layers: List<Pair<NodeSnap, List<Box>>>, screenW: Int, screenH: Int, format: String = OptionFormat.V1): List<Target> {
        val readingOrder = compareBy<Found>({ bucket(it.target.cx, it.target.cy, screenW, screenH) / 3 },
            { bucket(it.target.cx, it.target.cy, screenW, screenH) % 3 }, { it.target.top }, { it.target.left })
        val all = ArrayList<Found>()
        for (f in layers.flatMap { (root, covers) -> collect(root, screenW, screenH, covers) }.sortedWith(readingOrder))
            if (all.none { sameElement(it.target, f.target) }) all += f
        val kept = if (all.size <= MAX_OPTIONS - 1) all
            else all.withIndex().sortedWith(compareBy({ keepRank(it.value.target) }, { it.index })).take(MAX_OPTIONS - 1)
                .sortedBy { it.index }.map { it.value }
        return decorate(kept, screenW, screenH, format)
    }

    /** Lower = kept first when there are too many targets. */
    fun keepRank(t: Target): Int = when {
        t.label == "unlabeled" -> 3
        t.role == "item" || t.role == "image" -> 2
        t.role == "list item" -> 1
        else -> 0   // button, tab, text field, switch
    }

    /** The criteria sent to the model, in order: every target's option, then NONE_OPTION. */
    fun options(targets: List<Target>): List<String> = targets.map { it.option } + TargetVocab.NONE_OPTION

    /** One target for the `targets` op: its option, bounds and the parts the option is made of (null parts omitted). */
    fun json(t: Target): org.json.JSONObject = org.json.JSONObject().put("option", t.option)
        .put("bounds", "${t.left},${t.top},${t.right},${t.bottom}").put("label", t.label).put("role", t.role)
        .put("position", t.position).putOpt("context", t.context).putOpt("rank", t.rank)

    /**
     * Every option format of the same windows, for the `targets` op (harvest: training text of each format at capture
     * time, whatever the live model uses): {"options_v1": [..NONE], "targets_v1": [json..], "options_v2": .., ..}.
     */
    fun allFormats(layers: List<Pair<NodeSnap, List<Box>>>, screenW: Int, screenH: Int): org.json.JSONObject {
        val out = org.json.JSONObject()
        for (f in listOf(OptionFormat.V1, OptionFormat.V2)) {
            val ts = build(layers, screenW, screenH, f)
            out.put("options_$f", org.json.JSONArray(options(ts))).put("targets_$f", org.json.JSONArray(ts.map(::json)))
        }
        return out
    }

    /** The "target" question's state (targets.py Gen.row). */
    fun stateText(appName: String, pkg: String, screen: ScreenContext, utterance: String): String =
        "mode: cursor\napp: $appName ($pkg)\n${screen.text()}\nspoken target: \"$utterance\""

    // --- what to do with the answer ------------------------------------------------------------------------------------

    sealed class Outcome {
        data class Tap(val target: Target) : Outcome()
        /** Low confidence: highlight these (best first) and let the user pick with sounds. */
        data class Choose(val targets: List<Target>) : Outcome()
        object NotOnScreen : Outcome()
    }

    /**
     * none chosen -> NotOnScreen; confidence >= minConfidence -> Tap; else Choose among the (up to) 3 most probable
     * elements (NONE_OPTION excluded).
     */
    fun resolve(targets: List<Target>, answer: ChoiceAnswer, minConfidence: Double): Outcome {
        if (answer.choice == TargetVocab.NONE_OPTION) return Outcome.NotOnScreen
        val byOption = targets.associateBy { it.option }
        val chosen = byOption[answer.choice] ?: throw IllegalArgumentException("model chose an unknown option '${answer.choice}'")
        if (answer.confidence >= minConfidence) return Outcome.Tap(chosen)
        val ranked = answer.probabilities.entries
            .filter { it.key != TargetVocab.NONE_OPTION && it.key in byOption }
            .sortedByDescending { it.value }
            .map { byOption.getValue(it.key) }
        val top = (if (ranked.isEmpty()) listOf(chosen) else ranked).take(3)
        return Outcome.Choose(top)
    }
}

/** The highlighted-candidates state: rise/fall cycle, pop taps, hiss or a timeout cancels. */
class TargetChoice(val candidates: List<Target>) {
    init { require(candidates.isNotEmpty()) }
    var index = 0; private set
    val selected: Target get() = candidates[index]
    fun next() { index = (index + 1) % candidates.size }
    fun previous() { index = (index - 1 + candidates.size) % candidates.size }
}
