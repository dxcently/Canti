package ai.vox.companion

import kotlin.math.ceil

/**
 * The live transcript strip (pure Kotlin; TranscriptStripTest drives it with a fake scheduler and measure).
 *
 * While Canti listens, a bottom overlay shows the live words, then one result row (what it did, or why it could not).
 * After a miss the mic stays open once for a retry. Everything here is the state and layout the view draws; the view
 * ([TranscriptStripView]) and the controller ([VoxService]) hold the Android side. The transcript text lives only in
 * the view and in memory: it never reaches the event log, a file, or a toast. The only new log event is `strip`, and
 * it carries no text.
 *
 * [StripModel] is one state machine per strip "ticket" (a fresh instance each time the strip is opened, so [open]
 * need not clear the previous transcript: a retry re-opens the same instance and keeps its miss row visible). It
 * notifies one [onChange] listener with the immutable [StripFrame] to draw, or null when the strip hides.
 */

/** What the strip is listening for: the title tab and its lamp colour (orange while listening, red while dictating). */
enum class StripKind(val title: String, val orangeLamp: Boolean) {
    LISTEN("LISTENING", true),
    NAME("NAME IT", true),
    PICK("PICK ONE", true),
    DICTATE("DICTATING", false),
    CHAIN("CHAIN", true),
}

/** A word's drawing tone: settled ink, a still-partial word dim, a word it could not use bad (red). */
enum class Tone { INK, DIM, BAD }

/** One transcript word with its [Tone]. */
data class Word(val text: String, val tone: Tone)

/** The transcript words: live (settled + partial), the final result, marking the bad spans, and line fitting. */
object StripWords {
    /** Settled words (dictation's earlier utterances) INK; the partial's words INK except its last (DIM). */
    fun live(settled: String, partial: String): List<Word> {
        val out = ArrayList<Word>()
        settled.split(' ').filter { it.isNotEmpty() }.forEach { out += Word(it, Tone.INK) }
        val p = partial.split(' ').filter { it.isNotEmpty() }
        p.forEachIndexed { i, w -> out += Word(w, if (i == p.size - 1) Tone.DIM else Tone.INK) }
        return out
    }

    /** The final result: every word INK. */
    fun final(text: String): List<Word> = text.split(' ').filter { it.isNotEmpty() }.map { Word(it, Tone.INK) }

    /** The words at [bad] indexes become BAD (a new list; the input is unchanged). */
    fun mark(words: List<Word>, bad: Set<Int>): List<Word> =
        words.mapIndexed { i, w -> if (i in bad) Word(w.text, Tone.BAD) else w }

    /**
     * Greedy wrap into lines, then keep only the LAST 2 lines (the oldest words scroll off the top). A single word
     * wider than a line is clipped by the view, not wrapped forever.
     */
    fun fit(words: List<Word>, maxWidth: Float, measure: (String) -> Float): List<List<Word>> =
        fitAll(words, maxWidth, measure).takeLast(2)

    /** Greedy wrap into ALL lines (the chain's scrollable transcript keeps every line). */
    fun fitAll(words: List<Word>, maxWidth: Float, measure: (String) -> Float): List<List<Word>> {
        val lines = ArrayList<MutableList<Word>>()
        var cur = ArrayList<Word>()
        for (w in words) {
            if (cur.isNotEmpty() && measure((cur + w).joinToString(" ") { it.text }) > maxWidth) {
                lines += cur; cur = ArrayList()
            }
            cur += w
        }
        if (cur.isNotEmpty()) lines += cur
        return lines
    }
}

/** The result row's value colour: green done, red miss, orange ask, ink otherwise. */
enum class Signal { DONE, MISS, ASK, PLAIN }

/** One result row: a key, a value with dotted leaders, and a [Signal] colour for the value. */
sealed class StripRow(val key: String, val value: String, val signal: Signal) {
    /** The action it took ("DO ... tap Recently updated"). */
    class Done(value: String) : StripRow("DO", value, Signal.DONE)
    /** A picker narrowing: `2 LEFT ... say 1 or 2` (`3` -> `say 1, 2 or 3`, `4+` -> `say 1 to N`). */
    class Left(n: Int) : StripRow("$n LEFT", pickText(n), Signal.PLAIN)
    /** Dictation: `END ... say "stop dictation"`, shown the whole time while dictating. */
    class End : StripRow("END", "say \"stop dictation\"", Signal.PLAIN)
    /** A miss (`? ... <reason>`, red). [retry] = the mic stays open once; a Fail is a Miss that never retries. */
    class Miss(reason: String, val retry: Boolean) : StripRow("?", reason, Signal.MISS)
    /** A question, not a miss (`? ... <question>`, orange): no red words, no retry. */
    class Ask(question: String) : StripRow("?", question, Signal.ASK)
    /** A paused chain (`PAUSED ... try again · skip · cancel`, red). */
    class Paused : StripRow("PAUSED", "try again · skip · cancel", Signal.MISS)
    /** An undone navigation step (`BACK ... <what the last inverse did>`, done colour). */
    class Back(value: String) : StripRow("BACK", value, Signal.DONE)
    /** A refused undo (`BACK ... can't undo <text>`, red): the key is BACK, the colour a miss. */
    class BackMiss(value: String) : StripRow("BACK", value, Signal.MISS)
    /** A picker inside a chain (`<n> · WHICH ... say 1 or 2`, same value as [Left]). */
    class Which(n: Int) : StripRow("$n · WHICH", pickText(n), Signal.PLAIN)

    /** Two rows are equal when they read the same (a [Miss] also by its retry flag); the view never compares them. */
    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is StripRow) return false
        if (key != other.key || value != other.value || signal != other.signal) return false
        val a = this as? Miss; val b = other as? Miss
        return if (a != null && b != null) a.retry == b.retry else a == null && b == null
    }

    override fun hashCode(): Int {
        var h = key.hashCode()
        h = 31 * h + value.hashCode()
        h = 31 * h + signal.hashCode()
        h = 31 * h + ((this as? Miss)?.retry?.hashCode() ?: 0)
        return h
    }

    companion object {
        private fun pickText(n: Int): String = when {
            n <= 2 -> "say 1 or 2"
            n == 3 -> "say 1, 2 or 3"
            else -> "say 1 to $n"
        }
    }
}

/**
 * The result row and the bad-word spans from the transcript words. Pure; the words are tokenized per word by
 * lowercasing and stripping punctuation ([TargetQuery.key]); a query or app name is tokenized the same way. The query
 * shown is always as said (never the picker-cleaned form).
 */
object StripReasons {
    /** `no "<query>" here`: underline the longest contiguous run of words in the query's token set, else every word in it. */
    fun notOnScreen(words: List<Word>, query: String): Pair<StripRow, Set<Int>> =
        StripRow.Miss("no \"$query\" here", true) to span(words, tokens(query))

    /** `no app called "<name>"`: the same span rule on the app name. */
    fun noApp(words: List<Word>, name: String): Pair<StripRow, Set<Int>> =
        StripRow.Miss("no app called \"$name\"", true) to span(words, tokens(name))

    /**
     * The first unknown word (not in [known], not a number) gives `don't know "<word>"`; every unknown word is
     * underlined. If every word is known (the grammar just could not fit them together), underline all and name the
     * first word.
     */
    fun unknown(words: List<Word>, known: Set<String>): Pair<StripRow, Set<Int>> {
        val unknown = words.indices.filter { i ->
            val k = TargetQuery.key(words[i].text)
            k !in known && !PhraseGrammar.isNumberWord(k)
        }
        return if (unknown.isNotEmpty()) {
            StripRow.Miss("don't know \"${words[unknown.first()].text}\"", true) to unknown.toSet()
        } else {
            val first = words.firstOrNull()?.text ?: ""
            StripRow.Miss("don't know \"$first\"", true) to words.indices.toSet()
        }
    }

    /** Nothing was heard: `couldn't make out words`, no spans (the transcript shows a dim `...`). */
    fun noWords(): Pair<StripRow, Set<Int>> = StripRow.Miss("couldn't make out words", true) to emptySet()

    /** The text as given, no spans ("one command at a time", a follow-up's why, the hint). */
    fun why(text: String): Pair<StripRow, Set<Int>> = StripRow.Miss(text, true) to emptySet()

    /** An orange question, no spans. */
    fun ask(text: String): Pair<StripRow, Set<Int>> = StripRow.Ask(text) to emptySet()

    /**
     * Clip a value to [maxWidth] (its measured width): the last quoted part is ellipsized in place
     * (`no "walrus app wi…" here`); a value with no quoted part just loses its tail. The caller keeps at least three
     * leader dots before the value by passing the width left for it.
     */
    fun clipValue(value: String, maxWidth: Float, measure: (String) -> Float): String {
        if (measure(value) <= maxWidth) return value
        val i = value.indexOf('"'); val j = value.lastIndexOf('"')
        if (i >= 0 && j > i) {
            val before = value.substring(0, i + 1); val after = value.substring(j)
            var inner = value.substring(i + 1, j)
            while (inner.isNotEmpty() && measure("$before$inner…$after") > maxWidth) inner = inner.dropLast(1)
            return "$before$inner…$after"
        }
        var v = value
        while (v.length > 1 && measure("$v…") > maxWidth) v = v.dropLast(1)
        return "$v…"
    }

    private fun tokens(s: String): Set<String> = s.split(' ').map { TargetQuery.key(it) }.filter { it.isNotEmpty() }.toSet()

    private fun span(words: List<Word>, set: Set<String>): Set<Int> {
        val keys = words.map { TargetQuery.key(it.text) }
        var bestStart = -1; var bestLen = 0
        var runStart = -1; var runLen = 0
        for (i in keys.indices) {
            if (keys[i] in set) {
                if (runStart < 0 || keys[i - 1] !in set) { runStart = i; runLen = 1 } else runLen++
                if (runLen > bestLen) { bestStart = runStart; bestLen = runLen }
            }
        }
        if (bestStart >= 0) return (bestStart until bestStart + bestLen).toSet()
        return words.indices.filter { keys[it] in set }.toSet()
    }
}

/** Whether a miss may reopen the mic for one retry (every guard must pass; see VoxService.maybeRetry). */
object RetryRule {
    fun allowed(
        userOpened: Boolean, alreadyRetried: Boolean, dictating: Boolean, sameGeneration: Boolean,
        armed: Boolean, paused: Boolean, choiceOpen: Boolean, confirmPending: Boolean,
        windowOpen: Boolean, stripEnabled: Boolean,
    ): Boolean =
        userOpened && !alreadyRetried && !dictating && sameGeneration && armed && !paused &&
            !choiceOpen && !confirmPending && !windowOpen && stripEnabled
}

/** The strip window's top y from the screen geometry and the focused editable field (see VoxService.placeStrip). */
object StripPlace {
    const val GUT = 16

    fun top(screenH: Int, navBottom: Int, statusTop: Int, stripH: Int, imeTop: Int?, field: IntArray?): Int {
        var bottom = navBottom - GUT
        if (imeTop != null) {
            bottom = imeTop - GUT
            val f = field
            // The field's rect overlaps the band the strip would sit in: sit above the field instead (dictation).
            if (f != null && f[1] < bottom && f[3] > bottom - stripH) bottom = f[1] - GUT
        }
        var top = bottom - stripH
        if (top < statusTop) top = statusTop + GUT   // too tall for the space left: just below the status bar
        return top
    }
}

/** The timer tab's filled cells: `ceil(n * (deadline - now) / total)`, clamped to `0..n` (n = 8). */
fun cellsLeft(now: Long, deadline: Long, totalMs: Long, n: Int = 8): Int {
    if (totalMs <= 0) return 0
    return ceil(n.toDouble() * (deadline - now) / totalMs).toInt().coerceIn(0, n)
}

/** One immutable snapshot the view draws. */
data class StripFrame(
    val kind: StripKind,
    val lines: List<List<Word>>,
    val row: StripRow?,
    val deadline: Long,
    val totalMs: Long,
    val caret: Boolean,
    val visible: Boolean,
)

/**
 * The strip's state machine. One instance per ticket; [open] re-opens the same instance for a retry, so it keeps the
 * miss row (the first new partial clears it). [onChange] receives the frame to draw, or null when hidden.
 */
class StripModel(
    private val scheduler: Scheduler,
    private var measure: (String) -> Float = { it.length.toFloat() },
    private var maxWidth: Float = Float.MAX_VALUE,
) {
    var onChange: ((StripFrame?) -> Unit)? = null

    private var kind = StripKind.LISTEN
    private var settled = ""          // dictation's earlier utterances (settled words)
    private var words: List<Word> = emptyList()
    private var row: StripRow? = null
    private var deadline = 0L
    private var totalMs = 0L
    private var caret = true
    private var visible = false
    private var hideTask: (() -> Unit)? = null
    private var hold = false      // a CHAIN ticket never auto-hides a DO row while held
    private var scroll = 0        // transcript line scroll (chain strip body drag)

    fun frame(): StripFrame = StripFrame(kind, StripWords.fit(words, maxWidth, measure), row, deadline, totalMs, caret, visible)

    /** All wrapped transcript lines (the chain's scrollable body keeps every line; [fit] still shows the last 2). */
    fun allLines(): List<List<Word>> = StripWords.fitAll(words, maxWidth, measure)

    /** True when the transcript overflows the visible 2 lines (the body becomes scrollable by touch). */
    fun scrollable(): Boolean = allLines().size > 2

    /** The transcript scroll offset (chain strip body drag; clamped by the view). */
    fun scrollOffset(): Int = scroll

    /** The transcript scroll offset (chain strip body drag; clamped by the view). */
    fun setScroll(v: Int) { if (scroll != v) { scroll = v; emit() } }

    /** The view sets its measurement and width (e.g. after a rotation); the current frame is re-notified. */
    fun setGeometry(measure: (String) -> Float, maxWidth: Float) {
        this.measure = measure; this.maxWidth = maxWidth
        emit()
    }

    /** A new ticket: forget the last transcript and row, then [open]. */
    fun start(kind: StripKind, windowMs: Long) {
        settled = ""; words = emptyList(); row = null
        open(kind, windowMs)
    }

    /** Open (or re-open) for [windowMs]. A re-open (the retry) cancels a pending hide and keeps the transcript/row. */
    fun open(kind: StripKind, windowMs: Long) {
        this.kind = kind
        deadline = scheduler.now() + windowMs
        totalMs = windowMs
        caret = true
        visible = true
        hideTask?.invoke(); hideTask = null
        emit()
    }

    /** The recognizer's words so far: the trailing word dim, and (on a retry) the old row clears. */
    fun partial(text: String) {
        words = StripWords.live(settled, text)
        row = null
        caret = true
        emit()
    }

    /** The final result: all words ink, no caret. */
    fun final(text: String) {
        words = StripWords.final(text)
        caret = false
        emit()
    }

    /** Show a result row and mark the bad words; a done/miss hides after [RESULT_MS], a dictation's End stays. */
    fun result(row: StripRow, bad: Set<Int>) {
        this.row = row
        words = StripWords.mark(words, bad)
        caret = false
        hideTask?.invoke(); hideTask = null
        // stays up: dictation, the picker's own rows (n LEFT, a no-match hint) while it is open, a miss the mic
        // re-opens for, and a held chain ticket (a DO row stays while the chain runs); every other result hides
        if (!persistentRow(row)) hideTask = scheduler.schedule(RESULT_MS) { hide() }
        emit()
    }

    private fun persistentRow(r: StripRow?): Boolean =
        kind == StripKind.DICTATE || (kind == StripKind.PICK && (r is StripRow.Left || r is StripRow.Miss)) ||
            (r is StripRow.Miss && r.retry) || hold

    /** While a chain is active ([on] true) its DO rows never auto-hide; turning it off lets the current row hide. */
    fun hold(on: Boolean) {
        if (hold == on) return
        hold = on
        hideTask?.invoke(); hideTask = null
        if (!on && !persistentRow(row)) hideTask = scheduler.schedule(RESULT_MS) { hide() }
        emit()
    }

    /** Dictation settles an utterance: append it to the settled words (all ink, no partial). */
    fun typed(text: String) {
        settled = if (settled.isEmpty()) text else "$settled $text"
        words = StripWords.live(settled, "")
        caret = true
        emit()
    }

    /** The dictation silence clock restarted: it will stop at [deadline] (the timer tab's total stays [SILENCE_MS]). */
    fun quiet(deadline: Long) {
        this.deadline = deadline
        emit()
    }

    fun hide() {
        hideTask?.invoke(); hideTask = null
        visible = false
        emit()
    }

    private fun emit() { onChange?.invoke(if (visible) frame() else null) }

    companion object {
        const val RESULT_MS = 2000L
    }
}
