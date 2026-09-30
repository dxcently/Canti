package ai.vox.companion

/**
 * Item swipes (pure Kotlin, no Android; ItemSwipeGrammarTest, SwipeHoldTest, ItemSwipeGeometryTest).
 *
 * "swipe that away", "swipe the first one left", "swipe mail 3 away": a swipe on one on-screen item rather than the
 * whole screen. The grammar returns [SpeechCommand.ItemSwipe]; resolution to a target, the destructive hold and undo
 * live in VoxService (r8-swipes).
 *
 * Deictic "swipe it/this/that left|right" is ambiguous with a screen swipe: SwipeGrammar keeps it as [SpeechCommand.Swipe]
 * (an existing PhraseGrammarTest asserts "swipe it right" is a screen swipe), so the grammar here only claims deictic
 * for the destructive "away"/"off" directions; VoxService upgrades a deictic screen swipe to an item swipe when a
 * deictic target exists (J1). Plain screen swipes ("swipe left", "swipe left three times") are untouched.
 */

/** What an item swipe names: the last pick ("it/this/that"), a spoken label, or the Nth visible row. */
sealed class ItemRef {
    /** The last pick target or the chain's NOW preview target (resolved at run time). */
    object Deictic : ItemRef()
    /** A spoken label ("mail 3"); matched STRONG or picked. */
    data class Label(val text: String) : ItemRef()
    /** The Nth visible row (role row/list item), top to bottom; [fromEnd] for "last one". */
    data class Ordinal(val n: Int, val fromEnd: Boolean) : ItemRef()

    fun describe(): String = when (this) {
        is Deictic -> "it"
        is Label -> "label \"$text\""
        is Ordinal -> "ordinal " + (if (fromEnd) "last $n" else "$n")
    }
}

/** Parses item-swipe phrases ([SpeechCommand.ItemSwipe]); a pure sibling of [SwipeGrammar]. */
object ItemSwipeGrammar {
    private val DEICTIC = setOf("it", "this", "that")
    private val DIR = "(left|right|away|off)"

    /** "swipe away <it|this|that|label>" ("swipe away it", "swipe away mail 3"). */
    private val AWAY = Regex("^swipe away (.+)$")
    /** "swipe <ref> <left|right|away|off>". */
    private val SWIPE = Regex("^swipe (.+) $DIR$")

    /** "the first one", "last one": an ordinal row. */
    private val ONE = Regex("^(?:the )?(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|last) one$")
    /** "second row": the ordinal row form. */
    private val ROW = Regex("^(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|last) row$")

    private fun ordinal(w: String): Pair<Int, Boolean>? = when (w) {
        "first" -> 1 to false; "second" -> 2 to false; "third" -> 3 to false; "fourth" -> 4 to false
        "fifth" -> 5 to false; "sixth" -> 6 to false; "seventh" -> 7 to false; "eighth" -> 8 to false
        "ninth" -> 9 to false; "tenth" -> 10 to false; "last" -> 1 to true
        else -> null
    }

    /** The [SpeechCommand.ItemSwipe] in the cleaned phrase [t], or null (including the ambiguous deictic left/right). */
    fun parse(t: String): SpeechCommand.ItemSwipe? {
        AWAY.find(t)?.let { m ->
            val x = m.groupValues[1].trim()
            return SpeechCommand.ItemSwipe(if (x in DEICTIC) ItemRef.Deictic else ItemRef.Label(x), "away")
        }
        SWIPE.find(t)?.let { m ->
            val x = m.groupValues[1].trim()
            val dir = if (m.groupValues[2] == "off") "away" else m.groupValues[2]
            // Deictic left/right stays a screen swipe (SwipeGrammar owns it; VoxService upgrades it — J1).
            if (x in DEICTIC) return if (dir == "away") SpeechCommand.ItemSwipe(ItemRef.Deictic, "away") else null
            return refOf(x)?.let { SpeechCommand.ItemSwipe(it, dir) }
        }
        return null
    }

    private fun refOf(x: String): ItemRef? {
        ONE.find(x)?.let { m -> return ordinal(m.groupValues[1])?.let { (n, end) -> ItemRef.Ordinal(n, end) } }
        ROW.find(x)?.let { m -> return ordinal(m.groupValues[1])?.let { (n, end) -> ItemRef.Ordinal(n, end) } }
        val label = x.removePrefix("the ").trim()
        return if (label.isNotEmpty()) ItemRef.Label(label) else null
    }
}

/**
 * The finger path of an item swipe: from the target's centre, horizontal, 70% of the screen width in [dir]
 * ("away" = the reading-direction end: left in LTR, right in RTL), 250 ms, clamped inside the screen.
 */
object ItemSwipeGeometry {
    const val TRAVEL = 0.7f
    const val MS = 250L

    data class Swipe(val x0: Float, val y0: Float, val x1: Float, val y1: Float, val ms: Long)

    fun gesture(target: Box, screenW: Int, dir: String, rtl: Boolean): Swipe {
        val cx = (target.left + target.right) / 2f
        val cy = (target.top + target.bottom) / 2f
        val travel = TRAVEL * screenW
        val sign = when (dir) {
            "right" -> 1f
            "away" -> if (rtl) 1f else -1f
            else -> -1f   // "left" and anything else
        }
        val x1 = (cx + sign * travel).coerceIn(0f, screenW.toFloat())
        return Swipe(cx, cy, x1, cy, MS)
    }
}

/**
 * A countdown before a destructive swipe (pure, fake-clock tested). [onTick] reports the remaining ms (and the frozen
 * seconds), [onFire] runs when the hold elapses, [onCancel] when it is stopped. Speech during the hold freezes the
 * countdown ([freeze]); when the utterance ends a cancel resumes nothing (the caller cancels) and anything else
 * resumes where it froze ([resume]). A zero hold fires at once and never reports running.
 */
class SwipeHold(
    private val clock: Scheduler,
    private val holdMs: Long,
    private val onTick: (leftMs: Long) -> Unit,
    private val onFire: () -> Unit,
    private val onCancel: () -> Unit,
) {
    companion object { const val TICK_MS = 100L }

    var running = false
        private set
    private var fireAt = 0L
    private var frozenAt = 0L
    private var frozen = false
    private var cancelFire: (() -> Unit)? = null
    private var cancelTick: (() -> Unit)? = null

    fun start() {
        if (running) return
        if (holdMs <= 0) { onFire(); return }
        running = true
        fireAt = clock.now() + holdMs
        onTick(holdMs)
        cancelFire = clock.schedule(holdMs, ::fire)
        tick()
    }

    private fun tick() {
        cancelTick?.invoke()
        cancelTick = clock.schedule(TICK_MS) {
            if (running && !frozen) {
                val left = (fireAt - clock.now()).coerceAtLeast(0)
                onTick(left)
                if (left > 0) tick()
            }
        }
    }

    /** Speech during the hold: stop the countdown (and the fire), report the frozen seconds. */
    fun freeze() {
        if (!running || frozen) return
        frozen = true
        cancelFire?.invoke(); cancelFire = null
        cancelTick?.invoke(); cancelTick = null
        frozenAt = clock.now()
        onTick((fireAt - frozenAt).coerceAtLeast(0))
    }

    /** The utterance ended without a cancel word: resume where it froze. */
    fun resume() {
        if (!running || !frozen) return
        frozen = false
        val left = (fireAt - frozenAt).coerceAtLeast(0)
        fireAt = clock.now() + left
        cancelFire = clock.schedule(left, ::fire)
        tick()
    }

    fun cancel(why: String) {
        if (!running) return
        cancelFire?.invoke(); cancelFire = null
        cancelTick?.invoke(); cancelTick = null
        running = false
        onCancel()
    }

    private fun fire() {
        if (!running || frozen) return
        cancelTick?.invoke(); cancelTick = null
        cancelFire = null
        running = false
        onFire()
    }
}
