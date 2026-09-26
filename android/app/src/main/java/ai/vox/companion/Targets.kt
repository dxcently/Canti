package ai.vox.companion

/**
 * Intent cursor mode: the user names an on-screen element ("the like button") and the model picks it from a list of
 * options built from the accessibility tree. Spec: the docstring of finetune/vox/targets.py; the option format must
 * match the training data exactly: "{label} ({role}, {position})", NONE_OPTION last.
 */
data class Target(val label: String, val role: String, val position: String,
                  val left: Int, val top: Int, val right: Int, val bottom: Int) {
    val option: String get() = "$label ($role, $position)"
    val cx: Int get() = (left + right) / 2
    val cy: Int get() = (top + bottom) / 2
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
     * not itself clickable/focusable, as TalkBack reads a row whose title sits on a child view, else the viewIdResourceName tail with
     * "_" as spaces, else "unlabeled".
     */
    fun label(n: NodeSnap): String {
        clean(n.desc)?.let { return it }
        clean(n.text)?.let { return it }
        descendantText(n)?.let { return it }
        clean(n.id?.substringAfterLast('/')?.replace('_', ' '))?.let { return it }
        return "unlabeled"
    }

    private fun descendantText(n: NodeSnap, depth: Int = 0): String? {
        if (depth > 8) return null
        for (c in n.children) {
            if (!c.visible || c.clickable || c.focusable) continue   // a nested tappable element is its own option
            clean(c.desc)?.let { return it }
            clean(c.text)?.let { return it }
            descendantText(c, depth + 1)?.let { return it }
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

    private fun hasTargetInside(n: NodeSnap, depth: Int = 0): Boolean =
        depth < 12 && n.visible && ((n.clickable || n.focusable) || n.children.any { hasTargetInside(it, depth + 1) })

    /**
     * Targets in reading order: by 3x3 bucket (top row first, then left to right, the order the training data uses),
     * then by top and left edge inside a bucket. Duplicate option strings keep the first; at most MAX_OPTIONS - 1.
     */
    fun build(root: NodeSnap?, screenW: Int, screenH: Int): List<Target> {
        if (root == null) return emptyList()
        val found = mutableListOf<Target>()
        fun visit(n: NodeSnap, parent: NodeSnap?) {
            if (isTarget(n, screenW, screenH)) {
                val cx = (n.left + n.right) / 2; val cy = (n.top + n.bottom) / 2
                found += Target(label(n), role(n, parent), position(cx, cy, screenW, screenH), n.left, n.top, n.right, n.bottom)
            }
            for (c in n.children) visit(c, n)
        }
        visit(root, null)
        return found
            .sortedWith(compareBy({ bucket(it.cx, it.cy, screenW, screenH) / 3 }, { bucket(it.cx, it.cy, screenW, screenH) % 3 },
                { it.top }, { it.left }))
            .distinctBy { it.option }
            .take(MAX_OPTIONS - 1)
    }

    /** The criteria sent to the model, in order: every target's option, then NONE_OPTION. */
    fun options(targets: List<Target>): List<String> = targets.map { it.option } + TargetVocab.NONE_OPTION

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
