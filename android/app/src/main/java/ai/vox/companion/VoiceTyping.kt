package ai.vox.companion

/**
 * Typing by voice (pure Kotlin; VoiceTypingTest drives it with a fake recognizer, clock and text box).
 *
 * In a pop-pop listen window:
 *  - "type <text>" / "write <text>" types <text> into the focused text box, at the cursor (replacing a selection, like
 *    a keyboard), or at the end when it has no cursor;
 *  - "dictate" / "start dictation" starts [Dictation]: each utterance is typed until ~4 s of silence, any sound from
 *    the device, "stop dictation", or 2 minutes.
 * The recognizer's words are kept as said (trimmed); only "comma", "period", "question mark" and "new line" become
 * symbols ([Punctuation]). Nothing typed is ever parsed as a command (the stop phrase aside), and nothing ever presses
 * send, enter or an IME action: [TextInsert] only sets the box's text and its cursor.
 * Refused: no focused editable box ("no text box selected"), a password box, a system dialog in front (Executor).
 * The typed words are never logged unless `log_typed_text` is on (a debug setting, off by default).
 */
object TypeGrammar {
    sealed class Cmd {
        /** Type [text] (the recognizer's words, trimmed; empty = the verb alone, nothing to type). */
        data class Type(val text: String) : Cmd()
        object StartDictation : Cmd()
        object StopDictation : Cmd()
    }

    /** Lead words before the verb ("please type ...", "hey canti, write ..."); kept few on purpose. */
    private const val LEAD = "(?:please|ok|okay|hey|hi|so|now|um+|uh+|canti|kanti|canty|candy)"
    private val TYPE = Regex("^(?:$LEAD[\\s,.!]+)*(type|write)(?![\\p{L}\\p{N}'’-])[\\s,:;.!-]*(.*)$",
        setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL))
    val START = setOf("dictate", "start dictation", "start dictating", "begin dictation", "dictation", "dictation mode",
        "start dictation mode", "turn on dictation")
    val STOP = setOf("stop dictation", "stop dictating", "end dictation", "stop dictate")
    /** The stop phrase closing an utterance ("... see you soon, stop dictation"). */
    private val STOP_AT_END = Regex("[\\s,.!?]*\\b(?:stop dictat(?:ion|ing|e)|end dictation)[\\s,.!?]*$", RegexOption.IGNORE_CASE)

    /** A typing command in [raw] (one hypothesis, as the recognizer wrote it), or null: not about typing. */
    fun parse(raw: String): Cmd? {
        val t = raw.trim()
        TYPE.find(t)?.let { return Cmd.Type(it.groupValues[2].trim()) }
        val n = PhraseGrammar.normalize(t)
        if (n in START) return Cmd.StartDictation
        if (n in STOP) return Cmd.StopDictation
        return null
    }

    /** Dictation: the words before a closing stop phrase ("" = the phrase alone), or null when [raw] has none. */
    fun beforeStop(raw: String): String? = STOP_AT_END.find(raw.trim())?.let { raw.trim().substring(0, it.range.first).trim() }
}

/** The spoken punctuation words -> symbols; everything else as the recognizer wrote it. */
object Punctuation {
    private val RULES = listOf(
        Regex("[ \\t]*\\bnew ?line\\b[ \\t]*", RegexOption.IGNORE_CASE) to "\n",
        Regex("\\s*\\bquestion mark\\b", RegexOption.IGNORE_CASE) to "?",
        Regex("\\s*\\bcomma\\b", RegexOption.IGNORE_CASE) to ",",
        Regex("\\s*\\bperiod\\b", RegexOption.IGNORE_CASE) to ".",
    )

    fun apply(raw: String): String = RULES.fold(raw.trim()) { t, (re, sym) -> t.replace(re, Regex.escapeReplacement(sym)) }
}

/** The focused text box as [TextInsert] needs it (Executor wraps an AccessibilityNodeInfo; tests fake it). */
interface TextField {
    /** Its text; ignored while [showingHint] (an empty box shows its hint as text). */
    val text: String?
    val showingHint: Boolean
    /** The cursor/selection; -1 (or out of range) = none. */
    val selStart: Int
    val selEnd: Int
    val isEditable: Boolean
    val isPassword: Boolean
    /** The box's limit (<= 0: none). */
    val maxLength: Int
    /** ACTION_SET_TEXT: the whole text. */
    fun setText(text: String): Boolean
    /** ACTION_SET_SELECTION: the cursor. */
    fun setSelection(start: Int, end: Int): Boolean
}

object TextInsert {
    const val NO_FIELD = "no text box selected"
    const val PASSWORD = "password box: not typing there"
    const val EMPTY = "nothing to type"
    const val FULL = "the text box is full"

    /** [how] "set_text" when typed, else why not; [chars] the characters typed (a separating space included). */
    data class Outcome(val ok: Boolean, val how: String, val chars: Int = 0)

    /** Why [field] can't be typed into, or null. */
    fun refusal(field: TextField?): String? = when {
        field == null || !field.isEditable -> NO_FIELD
        field.isPassword -> PASSWORD
        else -> null
    }

    /**
     * Put [text] at the cursor (replacing a selection) or, with no cursor, at the end; a space is added where a word
     * would run into the text around it. One ACTION_SET_TEXT with the whole new text, then ACTION_SET_SELECTION to put
     * the cursor after what was typed. Never a click, enter, IME action or paste.
     */
    fun insert(field: TextField?, text: String): Outcome {
        refusal(field)?.let { return Outcome(false, it) }
        field!!
        if (text.isEmpty()) return Outcome(false, EMPTY)
        val cur = if (field.showingHint) "" else field.text.orEmpty()
        var s = field.selStart; var e = field.selEnd
        if (s !in 0..cur.length || e !in 0..cur.length) { s = cur.length; e = cur.length }
        if (s > e) { val x = s; s = e; e = x }
        val before = cur.substring(0, s); val after = cur.substring(e)
        var ins = text
        if (before.isNotEmpty() && !before.last().isWhitespace() && ins.first() !in NO_SPACE_BEFORE) ins = " $ins"
        if (after.isNotEmpty() && after.first().isLetterOrDigit() && !ins.last().isWhitespace()) ins = "$ins "
        val out = before + ins + after
        if (field.maxLength > 0 && out.length > field.maxLength) return Outcome(false, FULL)
        if (!field.setText(out)) return Outcome(false, "set_text refused")
        field.setSelection(s + ins.length, s + ins.length)
        return Outcome(true, "set_text", ins.length)
    }

    private val NO_SPACE_BEFORE = setOf(',', '.', '?', '!', ';', ':', ')', '\n')
}

/**
 * Dictation mode: utterance after utterance typed into the focused box. It holds the phone mic for the whole session
 * (the recognizer gets it; Canti's own capture pauses once, resumes once) and opens a fresh recognizer per utterance
 * on [window] (a ListenWindow without a mic of its own). Stops: [SILENCE_MS] without speech, [MAX_MS], the stop phrase,
 * a device sound after a pause in the words ([sound]), [stop] (disarm, pause, reset), or a problem (the box went away,
 * a password box, a recognizer status). The Pico hears the user speak: while words are coming in (a partial or final
 * within [speechHoldMs], `dictate_speech_hold_ms`) its sounds are speech, ignored (`dictate{event: ignored_sound}`).
 * Logs `dictate{event: start|utterance|ignored_sound|stop, why, chars}`; the words only with [logText].
 */
class Dictation(
    private val scheduler: Scheduler,
    private val mic: ListenWindow.MicYield?,
    private val window: ListenWindow,
    private val recognizer: () -> PhraseRecognizer,
    private val typer: Typer,
    private val logText: () -> Boolean,
    private val log: (Array<Pair<String, Any?>>) -> Unit,
    private val onStop: (why: String, status: String?) -> Unit = { _, _ -> },
    private val speechHoldMs: () -> Long = { SPEECH_HOLD_MS },
) {
    interface Typer {
        /** Why typing can't happen now ([TextInsert.NO_FIELD], [TextInsert.PASSWORD], a system dialog), or null. */
        fun refusal(): String?
        fun type(text: String): TextInsert.Outcome
    }

    var active = false; private set
    private val timers = mutableListOf<() -> Unit>()
    private var silence: (() -> Unit)? = null
    private var micHeld = false
    private var chars = 0
    private var utterances = 0

    /** Start; null when started, else why not (nothing is held then). */
    fun start(why: String): String? {
        if (active) return "already dictating"
        typer.refusal()?.let { log(arrayOf("event" to "refused", "why" to it)); return it }
        recognizer().status()?.let { log(arrayOf("event" to "refused", "why" to it)); return it }
        active = true; chars = 0; utterances = 0
        lastWordsAt = scheduler.now()   // the start phrase was just said: its tail is speech too
        val capturing = mic?.let { micHeld = true; it.yieldMic("dictation") } ?: false
        log(arrayOf("event" to "start", "why" to why, "chars" to 0))
        timers += scheduler.schedule(MAX_MS) { stop("time limit") }
        quiet()
        timers += scheduler.schedule(if (capturing) ListenWindow.HANDOFF_MS else 0) { listen() }
        return null
    }

    /** Stop now (nothing more is typed). */
    fun stop(why: String, status: String? = null) {
        if (!active) return
        active = false
        timers.forEach { it() }; timers.clear()
        silence?.invoke(); silence = null
        window.cancel("dictation: $why")
        if (micHeld) { micHeld = false; mic?.resumeMic("dictation stopped") }
        log(arrayOf("event" to "stop", "why" to why, "chars" to chars, "utterances" to utterances, "status" to status))
        onStop(why, status)
    }

    private var lastWordsAt = 0L

    /**
     * A sound from the device ([sequence]): while words are coming in (the last partial or final within
     * [speechHoldMs]) it is speech and ignored; after a pause of at least that long it stops dictation. Either way it
     * is not acted on. True = it stopped dictation.
     */
    fun sound(sequence: String): Boolean {
        if (!active) return false
        val sinceWords = scheduler.now() - lastWordsAt
        if (sinceWords < speechHoldMs()) {
            log(arrayOf("event" to "ignored_sound", "why" to "speech", "sequence" to sequence, "since_words_ms" to sinceWords))
            return false
        }
        stop("sound")
        return true
    }

    /** The silence clock restarts on speech (a partial, a typed utterance). */
    private fun quiet() {
        silence?.invoke()
        silence = scheduler.schedule(SILENCE_MS) { stop("silence") }
    }

    private fun listen() {
        if (!active) return
        window.open(recognizer(), UTTERANCE_MS, onActivity = { kind -> if (active && kind == "partial") { lastWordsAt = scheduler.now(); quiet() } }) { d -> heard(d) }
    }

    private fun heard(d: ListenWindow.Done) {
        if (!active) return
        if (d.status != null) { stop("recognizer: ${d.status}", d.status); return }
        val raw = d.heard?.best?.trim().orEmpty()
        if (raw.isNotEmpty()) {
            lastWordsAt = scheduler.now()
            quiet()
            val before = TypeGrammar.beforeStop(raw)
            val text = Punctuation.apply(before ?: raw)
            if (text.isNotEmpty()) {
                val r = typer.type(text)
                utterances++
                if (r.ok) chars += r.chars
                log(arrayOf("event" to "utterance", "why" to if (r.ok) "typed" else r.how, "chars" to r.chars,
                    "text" to if (logText()) text else null))
                if (!r.ok) { stop(r.how); return }
            }
            if (before != null) { stop("stop phrase"); return }
        }
        timers += scheduler.schedule(REOPEN_MS) { listen() }
    }

    companion object {
        const val SILENCE_MS = 4000L
        /** How long after the last words a device sound still counts as speech (`dictate_speech_hold_ms`). */
        const val SPEECH_HOLD_MS = 1000L
        val SPEECH_HOLD_RANGE = 200L..3000L
        const val MAX_MS = 120_000L
        /** One utterance's longest window; the silence clock usually ends a session long before. */
        const val UTTERANCE_MS = 30_000L
        /** A fresh recognizer right after the last one is freed can report "busy": a short breath between them. */
        const val REOPEN_MS = 150L
    }
}
