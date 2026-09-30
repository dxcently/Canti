package ai.vox.companion

import kotlin.math.abs

/**
 * Spoken follow-ups on the LAST action, decided app-side only (no model): "try again" repeats it, "the other one"
 * picks a different candidate, "the one below" moves to a neighbouring target, "undo" applies a limited inverse.
 * Pure Kotlin (FollowupTest, on the JVM).
 *
 * The memory holds ONE slot ([FollowupMemory]), never a history. Labels and the candidate list live only in this
 * in-memory object: they are never persisted and never appear in any log field (see the `followup` event, which
 * carries only kind / result / ages, never option text).
 *
 * [resolve] turns the memory's slot plus the current screen into a [Plan]. Executing the follow-up records a NEW slot,
 * so "undo" twice re-applies the original direction (undoing an undo restores the original action).
 */
enum class FollowKind { RETRY, OTHER, DIRECTION, UNDO }

enum class Dir { ABOVE, BELOW, LEFT, RIGHT }

/**
 * The last outcome. [at] is [android.os.SystemClock] elapsedRealtime at the moment of the action, [appBefore] the app
 * in front then, [appAfter] the app once the confirmer answered (null until it does), [watch] the confirmer watch id,
 * [confirm] the confirmer's result ("confirmed (events)" / "confirmed (pixels)" / "no visible change") and [by] its
 * evidence (the undo rule reads [by] for a window change).
 */
sealed class Last {
    abstract val at: Long
    abstract val appBefore: String
    abstract val appAfter: String?
    abstract val watch: Long?
    abstract val confirm: String?
    abstract val by: String?
    internal abstract fun withResult(appAfter: String, confirm: String, by: String?): Last

    /** A gesture / nav / swipe action executed through [VoxService.perform]. */
    data class Action(
        val action: String, val mode: String,
        override val at: Long, override val appBefore: String,
        override val appAfter: String? = null, override val watch: Long? = null,
        override val confirm: String? = null, override val by: String? = null,
    ) : Last() {
        override fun withResult(appAfter: String, confirm: String, by: String?) =
            copy(appAfter = appAfter, confirm = confirm, by = by)
    }

    /** A spoken volume change ([VolOp] on a [VolStream]). */
    data class Volume(
        val op: VolOp, val stream: VolStream,
        override val at: Long, override val appBefore: String,
        override val appAfter: String? = null, override val watch: Long? = null,
        override val confirm: String? = null, override val by: String? = null,
    ) : Last() {
        override fun withResult(appAfter: String, confirm: String, by: String?) =
            copy(appAfter = appAfter, confirm = confirm, by = by)
    }

    /** A spoken app launch. */
    data class OpenApp(
        val pkg: String,
        override val at: Long, override val appBefore: String,
        override val appAfter: String? = null, override val watch: Long? = null,
        override val confirm: String? = null, override val by: String? = null,
    ) : Last() {
        override fun withResult(appAfter: String, confirm: String, by: String?) =
            copy(appAfter = appAfter, confirm = confirm, by = by)
    }

    /** A tapped screen target and the ranked other candidates ([alternatives], already excluding [target]). */
    data class Pick(
        val target: Target, val alternatives: List<Target>,
        override val at: Long, override val appBefore: String,
        override val appAfter: String? = null, override val watch: Long? = null,
        override val confirm: String? = null, override val by: String? = null,
    ) : Last() {
        override fun withResult(appAfter: String, confirm: String, by: String?) =
            copy(appAfter = appAfter, confirm = confirm, by = by)
    }

    /** A spoken item swipe (ItemSwipe.kt): [label] the target's label, [dir] left/right/away. */
    data class ItemSwipe(
        val label: String, val dir: String,
        override val at: Long, override val appBefore: String,
        override val appAfter: String? = null, override val watch: Long? = null,
        override val confirm: String? = null, override val by: String? = null,
    ) : Last() {
        override fun withResult(appAfter: String, confirm: String, by: String?) =
            copy(appAfter = appAfter, confirm = confirm, by = by)
    }
}

/**
 * One follow-up slot. [record] overwrites it; [onConfirm] fills [Last.confirm]/[Last.appAfter]/[Last.by] when the
 * watch id matches; [current] returns the slot only while it is younger than [windowMs] AND the app in front is
 * [Last.appAfter] (or [Last.appBefore] before a confirm has arrived); [clear] forgets it.
 */
class FollowupMemory(private val windowMs: Long = 30_000L) {
    private var slot: Last? = null

    fun record(last: Last) { slot = last }

    fun onConfirm(watch: Long, result: String, by: String?, appNow: String) {
        val l = slot ?: return
        if (l.watch == watch) slot = l.withResult(appNow, result, by)
    }

    fun clear() { slot = null }

    fun current(now: Long, app: String): Last? {
        val l = slot ?: return null
        if (now - l.at > windowMs) return null
        val expected = l.appAfter ?: l.appBefore
        return if (app == expected) l else null
    }

    /** The stored slot's watch id (null when empty), for the no-change shrug. */
    fun watch(): Long? = slot?.watch
}

/** What a follow-up resolves to; the service executes it ([VoxService.followup]). */
sealed class Plan {
    /** Re-execute [action] (a gesture / nav / swipe) in [mode]. */
    data class Run(val action: String, val mode: String) : Plan()
    /** Re-apply a spoken volume change. */
    data class RunVolume(val op: VolOp, val stream: VolStream) : Plan()
    /** Re-launch an app. */
    data class RunApp(val pkg: String) : Plan()
    /** Tap [target]; [alternatives] become the new slot's other candidates. */
    data class Tap(val target: Target, val alternatives: List<Target> = emptyList()) : Plan()
    /** Highlight [targets] for the user to pick one (the existing choice picker). */
    data class Choose(val targets: List<Target>) : Plan()
    /** Nothing to undo, and why. */
    data class CantUndo(val why: String) : Plan()
    /** Nothing to do, and why. */
    data class Nothing(val why: String) : Plan()
    /** Fall back to the phrase's normal parse (there was nothing to act on). */
    object Fallback : Plan()
}

/** Pure direction pairs (Vocab.ACTIONS keys) that undo each other; everything else is "can't undo that". */
private val INVERSE = mapOf(
    "swipe_up" to "swipe_down", "swipe_down" to "swipe_up",
    "swipe_left" to "swipe_right", "swipe_right" to "swipe_left",
    "scroll_up" to "scroll_down", "scroll_down" to "scroll_up",
    "zoom_in" to "zoom_out", "zoom_out" to "zoom_in",
    "next_item" to "previous_item", "previous_item" to "next_item",
    "volume_up" to "volume_down", "volume_down" to "volume_up",
)

private fun dirWord(dir: Dir) = dir.name.lowercase()

private fun sameTarget(a: Target, b: Target) = a.label == b.label && abs(a.cx - b.cx) <= 24 && abs(a.cy - b.cy) <= 24

/** The screen target that is [t] re-found by the same label and a centre within 24 px, else null. */
private fun refind(t: Target, screen: List<Target>): Target? =
    screen.firstOrNull { s -> s.label == t.label && abs(s.cx - t.cx) <= 24 && abs(s.cy - t.cy) <= 24 }

private fun inDirection(t: Target, pick: Target, dir: Dir): Boolean = when (dir) {
    Dir.BELOW -> t.cy > pick.cy
    Dir.ABOVE -> t.cy < pick.cy
    Dir.RIGHT -> t.cx > pick.cx
    Dir.LEFT -> t.cx < pick.cx
}

private fun overlaps(t: Target, pick: Target, dir: Dir): Boolean = when (dir) {
    Dir.BELOW, Dir.ABOVE -> t.left < pick.right && t.right > pick.left
    Dir.LEFT, Dir.RIGHT -> t.top < pick.bottom && t.bottom > pick.top
}

/** Centre distance squared (the "nearest" metric). */
private fun distSq(a: Target, b: Target): Long {
    val dx = (a.cx - b.cx).toLong(); val dy = (a.cy - b.cy).toLong()
    return dx * dx + dy * dy
}

/**
 * The on-screen targets next to [pick] in [dir], nearest first, excluding [pick]: those whose centre lies in that
 * direction with an overlap along the perpendicular axis first, else those whose centre is more along [dir] than
 * across it (`|dx| < |dy|` for BELOW/ABOVE, the symmetric condition for LEFT/RIGHT).
 */
private fun directionalCandidates(pick: Target, dir: Dir, screen: List<Target>): List<Target> {
    val others = screen.filter { !sameTarget(it, pick) }.filter { inDirection(it, pick, dir) }
    if (others.isEmpty()) return emptyList()
    val overlap = others.filter { overlaps(it, pick, dir) }
    val pool = if (overlap.isNotEmpty()) overlap else others.filter {
        val dx = abs(it.cx - pick.cx); val dy = abs(it.cy - pick.cy)
        if (dir == Dir.BELOW || dir == Dir.ABOVE) dx < dy else dy < dx
    }
    return pool.sortedBy { distSq(it, pick) }
}

private fun backIfWindowChange(last: Last, mode: String): Plan {
    val by = last.by ?: return Plan.CantUndo("can't undo that")
    if (last.confirm != "confirmed (events)") return Plan.CantUndo("can't undo that")
    if (by.startsWith("TYPE_WINDOW_STATE_CHANGED") || by.startsWith("TYPE_WINDOWS_CHANGED")) return Plan.Run("back", mode)
    return Plan.CantUndo("can't undo that")
}

/**
 * The plan for a follow-up. [said] is the exact matched follow-up phrase ("the next one" falls back to its normal
 * parse when there is no pick, while "the other one" says "nothing to pick instead"). [screen] is the current screen's
 * targets. [last] is the current slot (already vetted for age and app), or null.
 */
fun resolve(kind: FollowKind, dir: Dir?, said: String, last: Last?, screen: List<Target>): Plan {
    return when (kind) {
    FollowKind.RETRY -> when (last) {
        null -> Plan.Nothing("nothing to repeat")
        is Last.Action -> Plan.Run(last.action, last.mode)
        is Last.Volume -> Plan.RunVolume(last.op, last.stream)
        is Last.OpenApp -> Plan.RunApp(last.pkg)
        is Last.Pick -> {
            val t = refind(last.target, screen) ?: return Plan.Nothing("not on screen")
            Plan.Tap(t, last.alternatives.mapNotNull { refind(it, screen) })
        }
        is Last.ItemSwipe -> Plan.Nothing("nothing to repeat")
    }
    FollowKind.OTHER -> {
        if (last !is Last.Pick) {
            return if (said == "the next one" || said == "next one") Plan.Fallback
            else Plan.Nothing("nothing to pick instead")
        }
        val remaining = last.alternatives.filter { it !== last.target }.mapNotNull { refind(it, screen) }
        when {
            remaining.isEmpty() -> Plan.Nothing("no other match")
            remaining.size == 1 -> Plan.Tap(remaining[0])
            else -> Plan.Choose(remaining)
        }
    }
    FollowKind.DIRECTION -> {
        val d = dir ?: return Plan.Nothing("nothing to pick")
        if (last !is Last.Pick) return Plan.Nothing("nothing to pick")
        val candidates = directionalCandidates(last.target, d, screen)
        if (candidates.isEmpty()) return Plan.Nothing("nothing ${dirWord(d)}")
        Plan.Tap(candidates[0], candidates.drop(1))
    }
    FollowKind.UNDO -> undoPlan(last, screen)
    }
}

/**
 * The UNDO branch of [resolve], extracted for the command chain ([Chain.kt]) to undo a done step by the same rules.
 * [screen] is unused here (no undo reads the screen; the service re-finds an on-screen "Undo" button itself).
 */
fun undoPlan(last: Last?, screen: List<Target>): Plan {
    if (last == null) return Plan.CantUndo("can't undo that")
    if (last.confirm == "no visible change") return Plan.CantUndo("nothing changed")
    return when (last) {
        is Last.Action -> {
            if (Outward.isOutward(last.action)) return Plan.CantUndo("can't undo that")
            INVERSE[last.action]?.let { return Plan.Run(it, last.mode) }
            when (last.action) {
                "tap", "click" -> backIfWindowChange(last, last.mode)
                else -> Plan.CantUndo("can't undo that")
            }
        }
        is Last.Volume -> when (val op = last.op) {
            is VolOp.Step -> Plan.RunVolume(VolOp.Step(op.steps, -op.dir, op.exact, op.fraction), last.stream)
            else -> Plan.CantUndo("can't undo that")   // Set / Mute / Unmute / Lowest: no stored level
        }
        is Last.OpenApp -> backIfWindowChange(last, "listening")
        is Last.Pick -> if (Outward.isOutwardTarget(last.target.label)) Plan.CantUndo("can't undo that")
            else backIfWindowChange(last, "listening")
        is Last.ItemSwipe -> Plan.CantUndo("the swipe")
    }
}

/** Exact visible-label precedence for spoken follow-ups (for example, an app's own Undo button). */
fun followupLabel(said: String, targets: List<Target>): Target? {
    val query = TargetQuery.normalize(said)
    // normalize keeps case; the spoken side is lower-case, so "undo" must match an "Undo"/"UNDO" button.
    return targets.firstOrNull { it.label.isNotBlank() && TargetQuery.normalize(it.label).equals(query, ignoreCase = true) }
}

/** True when [p] is a navigation undo (a scroll/swipe/next/previous inverse, or a "back"), i.e. a chain can apply it. */
fun navigationUndo(p: Plan): Boolean = when (p) {
    is Plan.Run -> p.action == "back" ||
        (INVERSE.containsKey(p.action) && p.action != "volume_up" && p.action != "volume_down")
    else -> false
}
