package ai.vox.companion

/**
 * The chain panel's geometry and its own-window visibility (pure Kotlin; PanelTest). The panel = the strip window plus
 * the queue window. [PanelPlace] places the strip like [StripPlace] but honours the user's saved top and the chain's
 * jump-to-top rule; [OwnCover] lets targets under Canti's own touchable windows stay visible (C4).
 */

object PanelPlace {
    const val GUT = StripPlace.GUT

    /**
     * The strip's top for the chain panel. The default is [StripPlace.top]; [userTop] (a saved preference, px) clamps
     * between `statusTop + GUT` and the default; [jump] moves the whole panel just below the status bar for one step.
     */
    fun top(screenH: Int, navBottom: Int, statusTop: Int, stripH: Int, imeTop: Int?, field: IntArray?, userTop: Int?, jump: Boolean): Int {
        val default = StripPlace.top(screenH, navBottom, statusTop, stripH, imeTop, field)
        if (jump) return statusTop + GUT
        if (userTop == null) return default
        return userTop.coerceIn(statusTop + GUT, default)
    }

    /** True when [target] (expanded by [pad]) intersects any of the panel's windows: the panel should jump to the top. */
    fun needsJump(target: Box, panel: List<Box>, pad: Int = 16): Boolean {
        val t = Box(target.left - pad, target.top - pad, target.right + pad, target.bottom + pad)
        return panel.any { !t.intersect(it).empty }
    }
}

/** Whether a target under Canti's own touchable windows is still visible to the user (the framework may say no). */
object OwnCover {
    /** [reported] (the node's isVisibleToUser), or a non-empty [r] fully covered by Canti's own rects (they don't hide). */
    fun visible(reported: Boolean, r: Box, own: List<Box>): Boolean =
        reported || (!r.empty && Occlusion.uncovered(r, own).isEmpty())
}

/** Remembers every Canti touchable rect seen recently, so the fingerprint stays consistent as Canti moves itself. */
class OwnRects(private val keepMs: Long = 5_000L) {
    private val seen = ArrayList<Pair<Long, List<Box>>>()

    fun note(rects: List<Box>, now: Long) { seen += now to rects }

    /** Every rect noted in the last [keepMs]. */
    fun recent(now: Long): List<Box> {
        val cutoff = now - keepMs
        return seen.filter { it.first >= cutoff }.flatMap { it.second }
    }
}
