package ai.vox.companion

/**
 * About-Canti detection (pure Kotlin, no Android; CantiTalkTest).
 *
 * Phrases that talk about Canti itself ("move the badge", "the box is covering the button", "canti keeps mishearing
 * me") never act on the app. When a UI fix exists Canti does it; otherwise the utterance is saved as a local feedback
 * note. Detection runs before the grammar (and before any Decider), but it CONSULTS the grammar: a phrase that parses
 * into a concrete command is a command, not about Canti, unless it explicitly targets Canti (a possessive marker, a
 * "canti"/"kanti" subject, or — while the relevant chrome is up — a Canti noun with a fix verb or complaint). A null
 * result means the phrase goes on to the chain / grammar as today.
 *
 * The utterance words themselves are never logged (HideWhy.CANTI); they reach only the local note file (W8/W10).
 */
object CantiTalk {
    enum class Fix { MOVE_BADGE, HIDE_QUEUE, PANEL_OTHER_END, HIDE_STRIP }

    /** [fix] the UI fix to apply, or null for a note; [note] whether a local note should be written (fix == null). */
    data class Result(val fix: Fix?, val note: Boolean)

    /** Which Canti chrome is visible right now (drives the "while the X is up" gates). */
    data class CantiUi(
        val badge: Boolean = false,
        val strip: Boolean = false,
        val queue: Boolean = false,
        val preview: Boolean = false,
        val picker: Boolean = false,   // the number overlay (picker/targets)
    ) {
        val up get() = badge || strip || queue || preview || picker
    }

    private data class Noun(val fix: Fix, val up: (CantiUi) -> Boolean)

    /** Named pieces of Canti's chrome: the fix they map to, gated on that piece being visible. */
    private val FIX_NOUNS = mapOf(
        "badge" to Noun(Fix.MOVE_BADGE, { it.badge }),
        "queue" to Noun(Fix.HIDE_QUEUE, { it.queue }),
        "strip" to Noun(Fix.HIDE_STRIP, { it.strip }),
        "transcript" to Noun(Fix.HIDE_STRIP, { it.strip }),
        "subtitle" to Noun(Fix.HIDE_STRIP, { it.strip }),
        "subtitles" to Noun(Fix.HIDE_STRIP, { it.strip }),
    )
    /** Self-reference words ("canti"/"kanti" as subject). "candy" is NOT here: "open candy crush" must open the app. */
    private val SELF = setOf("canti", "kanti")
    /** Shared nouns: about Canti only with a complaint while Canti UI is up (they name the panel, mostly). */
    private val SHARED = setOf("box", "menu", "button", "bar", "panel", "thing", "bubble")
    /** A verb that asks to fix the chrome ("move the badge", "hide your subtitles", "get rid of the queue"). */
    private val FIX_VERBS = setOf("move", "hide", "remove", "dismiss")
    private val COMPLAINT = listOf(
        "in the way", "covering", "blocking", "hiding", "on top of", "over the", "annoying", "too big", "too small",
    )
    /** "orange box/outline/frame/square": the NOW/NEXT outline (no fix in Stage 1, J5) -> note. */
    private val ORANGE = setOf("box", "outline", "frame", "square")

    /** About Canti if any hypothesis reads that way (recognizer order), else null (a normal command). */
    fun detect(hyps: List<String>, ui: CantiUi): Result? {
        for (h in hyps) detectOne(h, ui)?.let { return it }
        return null
    }

    private fun detectOne(h: String, ui: CantiUi): Result? {
        val words = PhraseGrammar.basic(h).split(' ').filter { it.isNotEmpty() }
        if (words.isEmpty()) return null
        val phrase = words.joinToString(" ")
        val concrete = PhraseGrammar.concrete(PhraseGrammar.parse(h))
        val possessive = possessiveTarget(words)                      // "your X" / "canti's X" / "the canti X"
        val selfSubject = !concrete && words.any { it in SELF }       // "canti" as subject, not the wake
        val fix = fixIntent(words, phrase, ui, possessive)

        // A concrete command with no explicit Canti targeting is a command (K1, K3, K5).
        if (concrete && possessive == null && !selfSubject && fix == null) return null

        if (fix != null) return Result(fix, false)
        if (words.contains("orange") && words.any { it in ORANGE }) return Result(null, true)
        if (phrase.contains("the numbers") && ui.picker) return Result(null, true)
        // a possessive marker names Canti's chrome directly -> that piece's fix ("your badge")
        possessive?.let { p -> FIX_NOUNS[p]?.let { return Result(it.fix, false) } }
        if (selfSubject) return Result(null, true)
        if (possessive != null) return Result(null, true)
        return null
    }

    /** A fix verb ("move"/"hide"/"get rid of") or a complaint predicate ("in the way", "covering", ...). */
    private fun fixVerbOrComplaint(words: List<String>, phrase: String): Boolean =
        words.any { it in FIX_VERBS } || words.windowed(3).any { it.joinToString(" ") == "get rid of" } ||
            COMPLAINT.any { phrase.contains(it) }

    /** The fix for a Canti noun said with a fix verb/complaint, gated on that piece being up (or an explicit marker). */
    private fun fixIntent(words: List<String>, phrase: String, ui: CantiUi, possessive: String?): Fix? {
        for ((noun, spec) in FIX_NOUNS) {
            if (!words.contains(noun)) continue
            val explicit = possessive == noun
            if (fixVerbOrComplaint(words, phrase) && (spec.up(ui) || explicit)) return spec.fix
        }
        if (ui.up && words.any { it in SHARED } && COMPLAINT.any { phrase.contains(it) }) return Fix.PANEL_OTHER_END
        return null
    }

    /** The noun a possessive marker names ("your X", "canti's X" -> "cantis X", "the canti X"), or null. */
    private fun possessiveTarget(words: List<String>): String? {
        for (i in 0 until words.size - 1) {
            val w = words[i]
            if (w == "your" || w == "cantis" || w == "kantis") return words[i + 1]
            if (w == "canti" && i >= 1 && words[i - 1] == "the") return words[i + 1]
        }
        return null
    }
}
