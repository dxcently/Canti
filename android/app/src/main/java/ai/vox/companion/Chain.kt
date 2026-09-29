package ai.vox.companion

/**
 * Spoken command chains (pure Kotlin, no Android; ChainQueueTest, ChainControlTest on the JVM). A [PhraseGrammar]
 * chain ("open settings then tap wifi") becomes a [ChainQueue]: steps run strictly in order, each starting only after
 * the previous one's Confirmer answered. The queue's words and on-screen text never reach the log: [ChainEffect.Log]
 * carries fixed keys, numbers and command kinds only.
 */

/** A step's life: waiting to run, running, asking (picker or confirm), done, stuck, undone, or dropped. */
enum class StepStatus { WAITING, RUNNING, ASK, DONE, STUCK, UNDONE, DROPPED }

/** One queued step. [said]/[text] are memory/display only; [last] is the Followup slot its exec recorded (for undo). */
class QueueStep(val n: Int, val said: String, val command: SpeechCommand) {
    var status: StepStatus = StepStatus.WAITING
    var note: String? = null
    var text: String = StepText.of(command)
    var last: Last? = null
    val watches: MutableSet<Long> = mutableSetOf()
    var anyConfirmed: Boolean = false
}

/** The strip's short step text (memory only; at most 28 chars). */
object StepText {
    const val MAX = 28

    fun of(c: SpeechCommand): String = clip(when (c) {
        is SpeechCommand.Tap -> "${c.verb ?: "tap"} ${c.query}"
        is SpeechCommand.Nav -> if (c.count > 1) "${c.phrase} x${c.count}" else c.phrase
        is SpeechCommand.OpenApp -> "open ${c.label}"
        is SpeechCommand.AppMissing -> "open ${c.name}"
        is SpeechCommand.Volume -> "volume ${c.op.describe()}"
        is SpeechCommand.Timer -> when {
            c.seconds == null -> "timer"
            c.seconds >= 60 && c.seconds % 60 == 0 -> "timer ${c.seconds / 60} min"
            else -> "timer ${c.seconds}s"
        }
        is SpeechCommand.Swipe -> {
            val base = if (c.action != null) c.action.replace('_', ' ') else "${c.semantic ?: ""} ${c.how}".trim()
            if (c.count > 1) "$base x${c.count}" else base
        }
        is SpeechCommand.Phrase -> c.text
        is SpeechCommand.Followup -> c.said
        is SpeechCommand.Chain -> "chain ${c.steps.size}"
        else -> c.describe()
    })

    private fun clip(s: String): String = if (s.length <= MAX) s else s.take(MAX - 1) + "…"
}

/** The exact S6 control phrases, matched before the grammar while a chain is active. */
object ChainControl {
    sealed class Cmd {
        object Retry : Cmd()
        object Skip : Cmd()
        object Continue : Cmd()
        object Cancel : Cmd()
        object Undo : Cmd()
        data class Rewind(val name: String) : Cmd()
        object RejectNext : Cmd()
        object Done : Cmd()
    }

    private val LEAD = setOf("please", "pls", "ok", "okay", "hey", "hi", "hello", "so", "well", "right", "yeah", "yes",
        "sure", "oh", "no", "just", "now", "and", "then", "also", "canti")
    private val TRAIL = listOf("please", "for me", "thanks", "thank you", "now", "ok", "okay", "i guess", "i think", "canti", "real quick")
    private val NAME_LEAD = setOf("the", "my", "a", "an", "that", "this")

    /** The last self-correction part ("no wait, cancel" -> "cancel"), mirroring PhraseGrammar.corrections. */
    private fun lastCorrectionPart(w: List<String>): List<String> {
        val parts = ArrayList<List<String>>()
        var cur = ArrayList<String>()
        var i = 0
        while (i < w.size) {
            val m = PhraseGrammar.CORRECTIONS.firstOrNull { c ->
                val cw = c.split(' ')
                i + cw.size <= w.size && w.subList(i, i + cw.size) == cw && (cw.size > 1 || w.getOrNull(i - 1) !in PhraseGrammar.TAKES_ARG)
            }
            if (m != null) { parts += cur; cur = ArrayList(); i += m.split(' ').size } else { cur += w[i]; i++ }
        }
        parts += cur
        return parts.last()
    }

    /** An exact S6 phrase (after clean), else null ("undo the last two" and "skip this video" are not controls). */
    fun parse(raw: String): Cmd? {
        val words = PhraseGrammar.tidy(PhraseGrammar.basic(raw))
        if (words.isEmpty()) return null
        // the phrase itself first ("cancel that", "forget it" are controls, not self-corrections here)
        match(clean(words))?.let { return it }
        // then the last self-correction part ("no wait, cancel" -> "cancel")
        return match(clean(lastCorrectionPart(words)))
    }

    private fun clean(w: List<String>): List<String> {
        var out = w
        while (out.isNotEmpty() && out.first() in LEAD) out = out.drop(1)
        var changed = true
        while (changed && out.isNotEmpty()) {
            changed = false
            for (p in TRAIL) {
                val pw = p.split(' ')
                if (out.size > pw.size && out.takeLast(pw.size) == pw) { out = out.dropLast(pw.size); changed = true; break }
            }
        }
        return out
    }

    private fun match(w: List<String>): Cmd? {
        if (w.isEmpty()) return null
        if (w.first() == "not") {
            var rest = w.drop(1)
            if (rest.firstOrNull() == "the") rest = rest.drop(1)
            val raw2 = rest.joinToString(" ")
            return when {
                raw2.isEmpty() -> Cmd.Undo
                raw2 == "that" -> Cmd.Undo
                raw2 == "that one" -> Cmd.RejectNext
                else -> {
                    val name = rest.filter { it !in NAME_LEAD }.joinToString(" ")
                    if (name.isEmpty()) Cmd.Undo else Cmd.Rewind(name)
                }
            }
        }
        return when (w.joinToString(" ")) {
            "try again", "again", "once more", "retry" -> Cmd.Retry
            "skip", "skip it", "skip that", "skip this step" -> Cmd.Skip
            "continue", "go on", "keep going", "carry on" -> Cmd.Continue
            "cancel", "stop", "cancel that", "stop the chain", "forget it", "never mind" -> Cmd.Cancel
            "undo", "undo that", "not that", "i didnt mean that", "thats wrong" -> Cmd.Undo
            "done", "thats it", "thats all", "im done", "finished" -> Cmd.Done
            else -> null
        }
    }
}

/** Finds the DONE step a rewind name refers to (token overlap, ties to the latest). */
object StepMatch {
    private val VERBS = setOf("tap", "open", "go", "press", "click")

    private fun tokens(s: String): Set<String> = s.split(' ').map { TargetQuery.key(it) }
        .filter { it.isNotEmpty() && it !in TargetMatcher.FILLER && it !in VERBS }.toSet()

    fun named(name: String, steps: List<QueueStep>): QueueStep? {
        val nameTokens = tokens(name)
        if (nameTokens.isEmpty()) return null
        var best: QueueStep? = null
        var bestOverlap = 0
        for (s in steps.filter { it.status == StepStatus.DONE }) {
            val overlap = (tokens(s.text) + tokens(s.said)).intersect(nameTokens).size
            if (overlap > 0 && overlap >= bestOverlap) { bestOverlap = overlap; best = s }
        }
        return best
    }
}

/** The step's exec outcome (no text: [Miss.note] is a fixed key, mapped to a fixed strip note). */
sealed class Outcome {
    object DoneNoWatch : Outcome()
    data class Miss(val note: String) : Outcome()
    sealed class Ask : Outcome() {
        object Picker : Ask()
        object Confirm : Ask()
    }
    data class AskEnded(val ok: Boolean) : Outcome()
}

/** The queue's effects, emitted synchronously to one listener (the service acts, tests assert). */
sealed class ChainEffect {
    data class RunStep(val step: QueueStep) : ChainEffect()
    data class RunUndo(val step: QueueStep, val plan: Plan) : ChainEffect()
    data class Listen(val ms: Long) : ChainEffect()
    object StopListening : ChainEffect()
    data class Preview(val now: QueueStep?, val next: QueueStep?) : ChainEffect()
    data class Frame(val frame: QueueFrame) : ChainEffect()
    data class Row(val row: StripRow?) : ChainEffect()
    data class Log(val fields: List<Pair<String, Any?>>) : ChainEffect()
    data class Ended(val why: String) : ChainEffect()
}

/** Fixed notes (never spoken or on-screen text). */
private const val NOTE_CHECKING = "checking"
private const val NOTE_HELD = "held"
private const val NOTE_NEXT = "next"
private const val NOTE_WHICH = "which one?"
private const val NOTE_CONFIRM = "click to confirm"
private const val NOTE_NOTHING = "nothing changed"
private const val NOTE_NO_ANSWER = "no answer"
private const val NOTE_UNDONE = "undone"
private const val NOTE_DROPPED = "dropped"
private const val NOTE_SKIPPED = "skipped"
private const val NOTE_CANT_UNDO = "can't undo"

/** The strip row text while a chain runs (fixed; never spoken or on-screen text). */
private fun pausedRow() = StripRow.Paused()

private enum class ChainState { RUNNING, PAUSED, TAIL, ENDED }

/**
 * The chain state machine. One instance per active chain. Steps run strictly in order; the next starts only after the
 * previous Confirmer answered (or timed out). All effects go through [onEffect], emitted synchronously.
 */
class ChainQueue(
    private val scheduler: Scheduler,
    private val maxSteps: Int = 8,
    private val tailMs: Long = 3_000,
    private val pausedMs: Long = 10_000,
    private val stepTimeoutMs: () -> Long,
) {
    var onEffect: ((ChainEffect) -> Unit)? = null

    private val steps = ArrayList<QueueStep>()
    private var running: QueueStep? = null
    private var undoing = false
    private var remembered = false   // the chain was re-opened from ChainMemory only to undo/rewind, then ends again
    private var state = ChainState.RUNNING
    private var stepTimeout: (() -> Unit)? = null
    private val watchStep = HashMap<Long, QueueStep>()
    private var rewindQueue: List<QueueStep>? = null
    private var expanded = false
    private var scroll = 0

    /** The step whose exec is in flight (RUNNING/ASK/being undone), else null. */
    val runningStep: QueueStep? get() = running

    private fun emit(e: ChainEffect) = onEffect?.invoke(e)
    private fun emitFrame() = emit(ChainEffect.Frame(QueueLayout.frame(steps, expanded, scroll)))
    private fun log(vararg fields: Pair<String, Any?>) = emit(ChainEffect.Log(fields.toList()))
    private fun row(r: StripRow?) = emit(ChainEffect.Row(r))
    private fun listen(ms: Long) = emit(ChainEffect.Listen(ms))

    // --- building ----------------------------------------------------------------------

    fun start(chainSteps: List<ChainStep>, dropped: Int) {
        clearTimers()
        steps.clear(); watchStep.clear(); running = null; undoing = false; rewindQueue = null; remembered = false
        state = ChainState.RUNNING; expanded = false; scroll = 0
        chainSteps.take(maxSteps).forEachIndexed { i, s -> steps += QueueStep(i + 1, s.said, s.command) }
        steps.forEach { it.status = StepStatus.WAITING }
        log("event" to "start", "steps" to steps.size, "reason" to if (dropped > 0) "max_steps" else null)
        runNext()
    }

    fun append(chainSteps: List<ChainStep>) {
        if (state == ChainState.ENDED) return
        val startN = steps.size
        chainSteps.forEachIndexed { i, s -> steps += QueueStep(startN + i + 1, s.said, s.command) }
        log("event" to "append", "steps" to chainSteps.size)
        emitFrame()
        if (running == null && state != ChainState.PAUSED) runNext()
    }

    // --- running ----------------------------------------------------------------------

    private fun runNext() {
        val next = steps.firstOrNull { it.status == StepStatus.WAITING }
        if (next == null) { tail(); return }
        expanded = false   // [chain] C6: the next step collapses the queue
        running = next
        undoing = false
        state = ChainState.RUNNING
        next.status = StepStatus.RUNNING
        next.note = NOTE_CHECKING
        steps.firstOrNull { it.status == StepStatus.WAITING }?.note = NOTE_NEXT   // the new next step
        armStepTimeout(next)
        emit(ChainEffect.RunStep(next))
        emitPreview()
        emitFrame()
    }

    private fun armStepTimeout(step: QueueStep) {
        stepTimeout?.invoke()
        stepTimeout = scheduler.schedule(stepTimeoutMs()) {
            stepTimeout = null
            if (step.status == StepStatus.RUNNING && step.watches.isNotEmpty()) {
                stuck(step, NOTE_NO_ANSWER, "no_answer")
            }
        }
    }

    /** The running step (or an undo) executed; [last.watch] may be null (a timer / queued gesture has no watch). */
    fun onExec(last: Last) {
        if (state == ChainState.ENDED) return
        val step = running ?: return
        if (step.last == null) step.last = last
        val w = last.watch
        if (w == null) {
            if (undoing) undoConfirmed(step) else finishStep(step, "confirmed (events)")
        } else {
            step.watches += w
            watchStep[w] = step
            step.note = NOTE_CHECKING
            emitFrame()
        }
    }

    /** The Confirmer's result for [watch] (also "superseded": ignored, another watch took over). [by] fills the step's Last for undo. */
    fun onConfirm(watch: Long, result: String, by: String? = null) {
        if (state == ChainState.ENDED || result == "superseded") return
        val step = watchStep[watch] ?: return
        if (watch !in step.watches) return
        step.watches -= watch
        watchStep.remove(watch)
        step.last = step.last?.withResult("", result, by)
        if (undoing) { undoConfirmed(step); return }
        if (result == "confirmed (events)" || result == "confirmed (pixels)") step.anyConfirmed = true
        if (step.watches.isNotEmpty()) return
        if (step.anyConfirmed) finishStep(step, result) else stuck(step, NOTE_NOTHING, "no_change")
    }

    private fun finishStep(step: QueueStep, result: String) {
        stepTimeout?.invoke(); stepTimeout = null
        step.status = StepStatus.DONE
        step.note = null
        step.watches.clear()
        log("event" to "confirm", "index" to step.n, "status" to "done", "result" to result)
        running = null
        undoing = false
        emitFrame()
        runNext()
    }

    private fun stuck(step: QueueStep, note: String, reason: String) {
        stepTimeout?.invoke(); stepTimeout = null
        step.status = StepStatus.STUCK
        step.note = note
        steps.forEach { if (it.status == StepStatus.WAITING) it.note = NOTE_HELD }
        log("event" to "pause", "index" to step.n, "reason" to reason)
        running = null
        undoing = false
        state = ChainState.PAUSED
        row(pausedRow())
        listen(pausedMs)
        emitFrame()
    }

    // --- outcomes (misses and asks from the service) ------------------------------------

    fun onOutcome(o: Outcome) {
        if (state == ChainState.ENDED) return
        val step = running ?: return
        when (o) {
            is Outcome.DoneNoWatch -> finishStep(step, "done")
            is Outcome.Miss -> stuck(step, o.note, if (o.note == NOTE_NOTHING) "no_change" else "nothing")
            is Outcome.Ask.Picker -> {
                step.status = StepStatus.ASK
                step.note = NOTE_WHICH
                emitFrame()
            }
            is Outcome.Ask.Confirm -> {
                step.status = StepStatus.ASK
                step.note = NOTE_CONFIRM
                emit(ChainEffect.StopListening)
                emitFrame()
            }
            is Outcome.AskEnded -> {
                if (o.ok) {
                    step.status = StepStatus.RUNNING
                    step.note = NOTE_CHECKING
                    emitFrame()
                } else stuck(step, NOTE_NOTHING, "picker_cancelled")
            }
        }
    }

    // --- controls ----------------------------------------------------------------------

    fun control(cmd: ChainControl.Cmd) {
        if (state == ChainState.ENDED) return
        when (cmd) {
            is ChainControl.Cmd.Retry -> retry()
            is ChainControl.Cmd.Skip -> skip()
            is ChainControl.Cmd.Continue -> resume()
            is ChainControl.Cmd.Cancel -> end("cancel")
            is ChainControl.Cmd.Undo -> undo()
            is ChainControl.Cmd.Rewind -> rewind(cmd.name)
            is ChainControl.Cmd.RejectNext -> rejectNext()
            is ChainControl.Cmd.Done -> end("done")
        }
    }

    private fun stuckStep(): QueueStep? = steps.firstOrNull { it.status == StepStatus.STUCK }

    private fun retry() {
        val target = stuckStep() ?: steps.lastOrNull { it.status == StepStatus.DONE } ?: return
        target.status = StepStatus.WAITING
        target.note = null
        target.watches.clear(); target.anyConfirmed = false; target.last = null
        steps.forEach { if (it.status == StepStatus.WAITING) it.note = null }
        row(null)
        running = null
        undoing = false
        runNext()
    }

    private fun skip() {
        val stuck = stuckStep() ?: return
        stuck.status = StepStatus.DROPPED
        stuck.note = NOTE_SKIPPED
        log("event" to "drop", "index" to stuck.n, "status" to "dropped", "reason" to "skip")
        row(null)
        steps.forEach { if (it.status == StepStatus.WAITING) it.note = null }
        running = null
        undoing = false
        runNext()
    }

    private fun resume() {
        if (state == ChainState.ENDED) return
        row(null)
        steps.forEach { if (it.status == StepStatus.WAITING) it.note = null }
        running = null
        undoing = false
        runNext()
    }

    private fun end(reason: String) {
        if (state == ChainState.ENDED) return
        steps.forEach { if (it.status == StepStatus.WAITING || it.status == StepStatus.RUNNING || it.status == StepStatus.ASK) { it.status = StepStatus.DROPPED; it.note = NOTE_DROPPED } }
        log("event" to "end", "reason" to reason)
        state = ChainState.ENDED
        clearTimers()
        running = null
        undoing = false
        remembered = false
        rewindQueue = null
        watchStep.clear()
        row(null)
        emit(ChainEffect.StopListening)
        emitFrame()
        emit(ChainEffect.Ended(reason))
    }

    private fun rejectNext() {
        val next = steps.firstOrNull { it.status == StepStatus.WAITING } ?: return
        next.status = StepStatus.DROPPED
        next.note = NOTE_DROPPED
        log("event" to "drop", "index" to next.n, "status" to "dropped", "reason" to "reject_next")
        emitFrame()
    }

    // --- undo --------------------------------------------------------------------------

    /** A RUNNING/ASK step is put back to WAITING (its late confirm is ignored) before an undo/rewind. */
    private fun holdRunning() {
        val s = running ?: return
        if (s.status != StepStatus.RUNNING && s.status != StepStatus.ASK) return
        for (w in s.watches) watchStep.remove(w)
        s.watches.clear()
        stepTimeout?.invoke(); stepTimeout = null
        s.status = StepStatus.WAITING
        s.note = NOTE_HELD
        s.last = null
        running = null
        undoing = false
    }

    private fun undo() {
        holdRunning()
        val last = steps.lastOrNull { it.status == StepStatus.DONE }
        if (last == null) { if (remembered) { remembered = false; end("undo") }; return }
        val plan = undoPlan(last.last, emptyList())
        if (plan is Plan.CantUndo || plan is Plan.Nothing) {
            row(StripRow.BackMiss("can't undo ${last.text}"))   // key "BACK", red (X2)
            if (remembered) { remembered = false; end("undo") } else { state = ChainState.PAUSED; listen(pausedMs); emitFrame() }
            return
        }
        beginUndo(last, plan)
    }

    private fun rewind(name: String) {
        holdRunning()
        val target = StepMatch.named(name, steps)
        if (target == null) { if (remembered) { remembered = false; end("rewind") }; return }
        val done = steps.filter { it.status == StepStatus.DONE }
        val idx = done.indexOf(target)
        if (idx < 0) { if (remembered) { remembered = false; end("rewind") }; return }
        rewindQueue = done.subList(idx, done.size).asReversed()
        nextRewind()
    }

    private fun beginUndo(step: QueueStep, plan: Plan) {
        step.status = StepStatus.UNDONE
        step.note = NOTE_UNDONE
        step.watches.clear()
        running = step
        undoing = true
        state = ChainState.RUNNING
        log("event" to "undo", "index" to step.n, "result" to "ok")
        emit(ChainEffect.RunUndo(step, plan))
        emitFrame()
    }

    private fun nextRewind() {
        val q = rewindQueue ?: return
        if (q.isEmpty()) { finishRewind(); return }
        val step = q.first()
        rewindQueue = q.drop(1)
        val plan = undoPlan(step.last, emptyList())
        if (plan is Plan.CantUndo || plan is Plan.Nothing) {
            step.note = NOTE_CANT_UNDO
            steps.filter { it.status == StepStatus.WAITING }.forEach { it.status = StepStatus.DROPPED; it.note = NOTE_DROPPED }
            row(StripRow.Miss("can't undo ${step.text} · stopped", retry = false))
            log("event" to "rewind", "result" to "cant_undo", "index" to step.n)
            emitFrame()
            end("rewind")
            return
        }
        log("event" to "rewind", "index" to step.n, "result" to "ok")
        beginUndo(step, plan)
    }

    private fun finishRewind() {
        steps.filter { it.status == StepStatus.WAITING }.forEach { it.status = StepStatus.DROPPED; it.note = NOTE_DROPPED }
        row(null)
        emitFrame()
        end("rewind")
    }

    private fun undoConfirmed(step: QueueStep) {
        step.watches.clear()
        step.status = StepStatus.UNDONE
        step.note = NOTE_UNDONE
        running = null
        undoing = false
        if (rewindQueue != null) { nextRewind(); return }
        if (remembered) { remembered = false; end("undo"); return }
        steps.forEach { if (it.status == StepStatus.WAITING) it.note = NOTE_HELD }
        state = ChainState.PAUSED
        row(pausedRow())
        listen(pausedMs)
        emitFrame()
    }

    // --- pause / tail / silence ---------------------------------------------------------

    private fun tail() {
        running = null
        undoing = false
        state = ChainState.TAIL
        listen(tailMs)
        emitFrame()
    }

    fun onSilence() {
        if (state != ChainState.TAIL && state != ChainState.PAUSED) return   // RUNNING/ENDED: ignore
        if (state == ChainState.PAUSED) {
            steps.forEach { if (it.status == StepStatus.WAITING) { it.status = StepStatus.DROPPED; it.note = NOTE_DROPPED } }
            end("paused_timeout")
        } else {
            end("silence")
        }
    }

    /** Re-open an ENDED chain (from ChainMemory) to undo / rewind its done steps; it ends again after the undo. */
    fun reopenForUndo(): Boolean {
        if (state != ChainState.ENDED) return false
        state = ChainState.RUNNING
        remembered = true
        return true
    }

    /** A phrase was heard but did not restart the window: if the queue is idle (TAIL/PAUSED), re-arm the listen. */
    fun heard() {
        if (state == ChainState.ENDED || state == ChainState.RUNNING) return
        if (state == ChainState.TAIL) { listen(tailMs); emitFrame() } else { listen(pausedMs); emitFrame() }
    }

    fun clear(why: String) {
        if (state == ChainState.ENDED) return
        log("event" to "end", "reason" to why)
        state = ChainState.ENDED
        clearTimers()
        running = null
        undoing = false
        remembered = false
        rewindQueue = null
        watchStep.clear()
        row(null)
        emit(ChainEffect.StopListening)
        emitFrame()
        emit(ChainEffect.Ended(why))
    }

    private fun clearTimers() {
        stepTimeout?.invoke(); stepTimeout = null
    }

    private fun emitPreview() {
        val now = running?.takeIf { it.status == StepStatus.RUNNING }
        val next = steps.firstOrNull { it.status == StepStatus.WAITING }
        emit(ChainEffect.Preview(now, next))
    }

    // --- view --------------------------------------------------------------------------

    fun frame(): QueueFrame = QueueLayout.frame(steps, expanded, scroll)

    fun setExpanded(on: Boolean) { if (expanded != on) { expanded = on; emitFrame() } }
    fun setScroll(v: Int) { if (scroll != v) { scroll = v; emitFrame() } }

    val stepList: List<QueueStep> get() = steps
}

/** One strip queue row (status glyph + number + text + note). */
data class QueueRow(val n: Int, val text: String, val status: StepStatus, val note: String?)

/** The queue's layout snapshot: the visible rows, chip counts, expanded flag, scroll and a scrollbar. */
data class QueueFrame(
    val rows: List<QueueRow>,
    val doneAbove: Int,
    val moreBelow: Int,
    val expanded: Boolean,
    val scroll: Int,
    val scrollbar: Triple<Int, Int, Int>?,
)

/** Three visible slots (last-done / running-or-stuck / next); expanded shows all, scrolled. */
object QueueLayout {
    const val VISIBLE = 3

    fun frame(steps: List<QueueStep>, expanded: Boolean, scroll: Int): QueueFrame {
        val rows = steps.map { QueueRow(it.n, it.text, it.status, it.note) }
        if (expanded) {
            val total = rows.size
            val clamped = scroll.coerceIn(0, maxOf(0, total - 1))
            return QueueFrame(rows, 0, 0, true, clamped, scrollbar(total, clamped, VISIBLE))
        }
        val cur = steps.indexOfFirst { it.status == StepStatus.RUNNING || it.status == StepStatus.ASK || it.status == StepStatus.STUCK }
        if (cur < 0) {
            val shown = rows.takeLast(minOf(VISIBLE, rows.size))
            return QueueFrame(shown, maxOf(0, steps.size - shown.size), 0, false, 0, null)
        }
        val out = ArrayList<QueueRow>()
        val prev = steps.getOrNull(cur - 1)?.takeIf { it.status == StepStatus.DONE }
        if (prev != null) out += QueueRow(prev.n, prev.text, prev.status, prev.note)
        out += rows[cur]
        val next = steps.getOrNull(cur + 1)?.takeIf { it.status == StepStatus.WAITING }
        if (next != null) out += QueueRow(next.n, next.text, next.status, next.note)
        val doneAbove = steps.count { it.status == StepStatus.DONE && (prev == null || it.n < prev.n) }
        val moreBelow = steps.count { it.status == StepStatus.WAITING && next != null && it.n > next.n }
        return QueueFrame(out, doneAbove, moreBelow, false, 0, null)
    }

    private fun scrollbar(total: Int, scroll: Int, visible: Int): Triple<Int, Int, Int>? {
        if (total <= visible) return null
        val track = 100
        val thumb = (track * visible / total).coerceAtLeast(10)
        val top = (track - thumb) * scroll / (total - visible)
        return Triple(track, thumb, top)
    }
}

/** The ended chain's steps + app + end time, for "undo" / "no, not the X" for a while after it ends (S7). */
class ChainMemory(private val windowMs: Long = 30_000L) {
    private var chain: ChainQueue? = null
    private var app: String? = null
    private var at: Long = 0L

    fun store(queue: ChainQueue, appNow: String, now: Long) { chain = queue; app = appNow; at = now }

    fun current(now: Long, appNow: String): ChainQueue? {
        val c = chain ?: return null
        if (now - at > windowMs) return null
        return if (appNow == app) c else null
    }

    fun clear() { chain = null; app = null }
}
