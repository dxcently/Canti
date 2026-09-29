package ai.vox.companion

import java.util.Locale

/**
 * Spoken phrases -> commands, deterministic first (pure Kotlin, no Android; PhraseGrammarTest).
 *
 * Input is a recognizer's transcript plus its n-best ([Heard]), whatever the engine (`asr_engine`: the Android
 * recognizer now, a bundled one later), or the `phrase` of a protocol message.
 *
 * Speech is messy, so each hypothesis is first cleaned ([tidy], [strip]): hesitations ("um", "uh") and softeners
 * ("maybe", "please", "kind of") at the edges or next to a command word, politeness and wake words at the start ("hey canti", "could
 * you"), tails at the end ("for me", "thanks"), doubled words ("the the") and repeats ("scroll down scroll down").
 * A self-correction ("go back, no wait, home") keeps the last part. Then, on what is left:
 *  0. only filler, chatter ("what was I doing"), a retraction ("... never mind"), or two different commands
 *     ("scroll down and go home")                             -> [SpeechCommand.Ignore], nothing happens
 *  1. an exact user phrase rule (profile scope "phrases")      -> [SpeechCommand.Phrase], the decider path
 *  2. "... timer ..."                                          -> [SpeechCommand.Timer] (words or digits, [Durations])
 *  3. navigation ("go back", "scroll down", "next", ...)       -> [SpeechCommand.Nav], decided by the rules
 *  4. "open|launch|start|go to <app>"                           -> [SpeechCommand.OpenApp] ([AppMatcher])
 *  5. "tap|click|press|open <thing>"                            -> [SpeechCommand.Tap] ([TargetMatcher] on the screen)
 *  6. cursor mode: anything else names an element               -> [SpeechCommand.Tap]
 *  7. a command inside a request ("i want you to go back")     -> that command
 *  8. anything else                                             -> [SpeechCommand.Phrase] "unparsed", the decider path
 * A tap always needs a tap verb (or cursor mode) and then a match on the screen: chatter never taps.
 * [choose] picks among the n-best: the most concrete parse wins, ties go to the recognizer's order.
 */
data class Heard(val hypotheses: List<String>, val confidences: List<Float> = emptyList(), val partial: Boolean = false) {
    val best: String? get() = hypotheses.firstOrNull()
}

sealed class SpeechCommand {
    /** Launch an installed app (its launcher entry). */
    data class OpenApp(val pkg: String, val label: String, val score: Double, val others: List<String> = emptyList()) : SpeechCommand()
    /** An app's name that is not installed ("open snapchat"): say "no app called [name]", never tap screen text. */
    data class AppMissing(val name: String) : SpeechCommand()
    /** Tap the on-screen element named [query]; [fallback]: what a bare word means when nothing on screen matches. */
    data class Tap(val query: String, val verb: String?, val fallback: SpeechCommand? = null) : SpeechCommand()
    /** A navigation phrase in [Vocab.PHRASES] form, decided by the rules (screen tie-break for next/previous, play/pause). */
    data class Nav(val phrase: String, val count: Int = 1) : SpeechCommand()
    /** Set a countdown; [seconds] null = no usable length heard (1 s .. 24 h). */
    data class Timer(val seconds: Int?) : SpeechCommand()
    /** For the phrase decider: a user phrase rule, or text the grammar does not know ([why] "unparsed"). */
    data class Phrase(val text: String, val why: String) : SpeechCommand()
    /** No action: filler, chatter, a retraction, two different commands at once ([why] says which). */
    data class Ignore(val why: String) : SpeechCommand()
    /** Change a volume ([VolumeGrammar]): which stream, and a step, a level, mute or unmute. Acts at once, shows the volume bar. */
    data class Volume(val stream: VolStream, val op: VolOp) : SpeechCommand()
    /**
     * A horizontal/vertical swipe ([SwipeGrammar]): [action] a finger direction (`swipe_left`...), or [semantic] "next" /
     * "previous" resolved on the screen ([SwipePlan]); [count] times (1..5); [how]: "finger", "content" or the noun said.
     */
    data class Swipe(val action: String?, val semantic: String?, val count: Int = 1, val how: String = "") : SpeechCommand()

    fun describe(): String = when (this) {
        is OpenApp -> "open_app $label ($pkg, ${"%.2f".format(Locale.ROOT, score)})" + (if (others.isNotEmpty()) " or ${others.joinToString()}" else "")
        is AppMissing -> "no app called $name"
        is Tap -> "tap \"$query\"" + (fallback?.let { " (else ${it.describe()})" } ?: "")
        is Nav -> "nav \"$phrase\"" + (if (count > 1) " x$count" else "")
        is Timer -> if (seconds == null) "timer (no length)" else "timer ${seconds}s"
        is Phrase -> "phrase \"$text\" ($why)"
        is Ignore -> "ignore ($why)"
        is Volume -> "volume ${stream.key} ${op.describe()}"
        is Swipe -> "swipe ${action ?: semantic}" + (if (count > 1) " x$count" else "") + (if (how.isNotEmpty()) " ($how)" else "")
    }
}

object PhraseGrammar {
    data class Context(
        val apps: List<AppEntry> = emptyList(),
        val userPhrases: Set<String> = emptySet(),
        val cursor: Boolean = false,
        /**
         * The phrase answers a listen window the user opened on purpose (a pop pop, then speech): only there a lone
         * "up" / "down" scrolls. Anywhere else (a future always-listening mic) it needs a verb ("scroll down", "go down").
         */
        val window: Boolean = false,
    )

    data class Pick(val index: Int, val text: String, val command: SpeechCommand, val parsed: List<SpeechCommand>)

    // --- cleaning up speech ---------------------------------------------------------------------------------------

    // The filler lists below are shared with [TargetQuery] (the target pickers' query normaliser): edit them in one place.

    /**
     * Hesitations, dropped wherever they are: um, umm, uh, uhh, uhm, er, erm, ah, ahh, hmm, hm, mm, mmm, eh and their
     * drawn-out spellings ("uhhh", "ummm", "hmmm").
     */
    internal val HESITATION = Regex("^(?:u+h+m*|u+m+|e+r+m*|a+h+|h+m+|m{2,}|e+h+)$")
    fun isHesitation(w: String) = HESITATION.matches(w)
    /** Softeners: dropped at the start or end or next to a command word; kept as an argument ("tap maybe later"). */
    private val SOFT_WORDS = setOf("please", "pls", "maybe", "perhaps", "basically", "literally", "kindly", "quickly", "possibly")
    /** Button labels that start with a softener: kept whole ("maybe later" is the Maybe later button, not "later"). */
    private val SOFT_LABELS = listOf("maybe later", "maybe next time", "maybe not")
    private fun softLabelAt(w: List<String>, i: Int): Boolean =
        SOFT_LABELS.any { l -> val lw = l.split(' '); i + lw.size <= w.size && w.subList(i, i + lw.size) == lw }
    internal val SOFT_PHRASES = listOf("you know what", "you know", "kind of", "sort of", "real quick", "if you can", "if you could",
        "whats it called", "what is it called", "whats that called", "what do you call it", "whatchamacallit", "whatever its called")
    /** Words a command starts with: "like" straight before one is a filler ("can you like scroll down"). */
    private val COMMAND_START = setOf("scroll", "go", "open", "tap", "tab", "click", "press", "launch", "start", "set", "turn", "pause",
        "play", "skip", "show", "select", "hit", "take", "navigate", "swipe", "resume", "next", "previous", "back", "home") +
        setOf("mute", "unmute", "louder", "quieter", "softer", "crank", "raise", "lower", "increase", "decrease", "make", "volume",
            "silence", "max", "flick", "move", "page")
    /** "like" before these is a filler too ("turn it up like a lot", "like way louder"). */
    private val LIKE_BEFORE = setOf("a", "way", "really", "super", "much", "totally", "so", "just")
    /** "open like youtube": a filler "like" after these, unless the like button is named ("open like button"). */
    private val LIKE_OPEN = setOf("open", "launch", "start")
    private val LIKE_NOUNS = setOf("button", "count", "icon", "list", "page", "tab")
    /** Doubled on purpose, never collapsed: "louder louder" is two steps. */
    private val REPEATABLE = setOf("louder", "quieter", "softer")
    /** "would you mind scrolling down" -> "scroll down" (present participles only: past tense is narration). */
    private val ING = mapOf("scrolling" to "scroll", "opening" to "open", "tapping" to "tap", "clicking" to "click", "pressing" to "press",
        "launching" to "launch", "skipping" to "skip", "pausing" to "pause", "selecting" to "select", "starting" to "start",
        "turning" to "turn", "muting" to "mute", "unmuting" to "unmute", "lowering" to "lower", "raising" to "raise",
        "cranking" to "crank", "swiping" to "swipe", "flicking" to "flick", "moving" to "move")
    private val LEAD_WORDS = setOf("please", "ok", "okay", "hey", "hi", "hello", "yo", "canti", "so", "now", "and", "then", "just", "oh",
        "well", "alright", "right", "yeah", "yes", "sure", "also")
    /** The wake word as recognizers spell it, after "hey"/"ok" ("hey candy, open youtube"). */
    private val WAKE = setOf("canti", "kanti", "canty", "cantie", "cante", "candy", "shanti", "auntie", "aunty", "google")
    internal val LEAD_PHRASES = listOf("lets see", "let me see", "let me think", "lets think", "would you mind", "do you mind", "can you", "could you", "would you", "will you", "i want you to",
        "i need you to", "i want to", "i wanna", "i need to", "id like to", "i would like to", "lets", "let us", "go ahead and", "try to",
        "help me", "you can", "i said", "all right")
    private val TRAIL_PHRASES = listOf("please", "for me", "now", "thanks", "thank you", "right now", "again", "then", "ok", "okay",
        "yeah", "i guess", "i think", "if you can", "canti", "for a sec", "thx", "real quick", "instead", "like this", "like that", "like so")
    /** An utterance made only of these is filler. */
    private val ACK = setOf("yeah", "yes", "yep", "yup", "ok", "okay", "right", "alright", "sure", "well", "oh", "cool", "nice", "huh",
        "wow", "wait", "no", "nope", "nah", "so", "and", "fine", "good", "great", "thanks", "thank", "you", "lol", "haha", "hey", "hi",
        "hello", "canti", "like", "anyway", "hmm", "okay", "sorry", "then", "now", "just", "um", "uh", "i", "mean", "see", "got", "it")
    /** First words of a question or a remark, not a command ("what was i doing", "is it on"). */
    private val CHATTER = setOf("what", "whats", "why", "who", "whos", "where", "wheres", "when", "how", "hows", "is", "isnt", "are",
        "arent", "was", "were", "did", "didnt", "does", "doesnt", "am", "im", "i", "ive", "id", "its", "it", "thats", "that", "this",
        "theres", "there", "he", "hes", "she", "shes", "they", "theyre", "we", "my", "your", "youre", "you", "oh", "wow", "huh", "lol",
        "haha", "nah", "hmm", "maybe", "wonder", "look", "wait")
    /** Self-correction: the part after one of these replaces what came before ("go back no wait home"). */
    internal val CORRECTIONS = listOf("no wait", "wait no", "no no", "no sorry", "sorry no", "i mean", "i meant", "scratch that", "or rather",
        "never mind", "forget it", "cancel that", "nevermind", "no", "wait", "sorry", "actually")
    /** Words that make the next word an argument, not a correction ("tap no", "press wait"). */
    internal val TAKES_ARG = setOf("tap", "tab", "click", "press", "hit", "select", "touch", "push", "choose", "pick", "open", "the", "say", "on")
    /** Two commands joined by these are refused (one command per phrase). */
    private val JOINERS = listOf("and then", "after that", "and", "then", "also")

    private val CUT_OFF = Regex("(?<![a-z0-9'’-])[a-z]+-(?=[\\s,.;:!?]|$)")

    /** Lowercase words: "+" -> plus, "5min" -> "5 min", punctuation and apostrophes out. Names (apps, labels) use this. */
    fun basic(raw: String): String {
        // a word cut off mid-way ("scroll d-, scroll down", "open tele-, telegram") goes; "wi-fi" and "check-in" stay
        var t = raw.lowercase(Locale.ROOT).replace(CUT_OFF, " ").replace("%", " percent ").replace("+", " plus ").replace("&", " and ").replace("'", "").replace("’", "")
        t = t.replace(Regex("(\\d)([a-z])"), "$1 $2").replace(Regex("([a-z])(\\d)"), "$1 $2")
        t = t.replace(Regex("(?<!\\d)\\.|\\.(?!\\d)"), " ").replace(Regex("[^a-z0-9. ]"), " ")
        return t.replace(Regex("\\s+"), " ").trim()
    }

    internal fun isNumberWord(w: String) = w.toDoubleOrNull() != null || w in NumberWords.UNITS || w in NumberWords.TENS

    /** Hesitations, softeners and a filler "like" out, "-ing" to the verb, a doubled word once ("the the" -> "the"). */
    fun tidy(basic: String): List<String> {
        var t = " $basic "
        for (p in SOFT_PHRASES) t = t.replace(" $p ", " ")
        t = t.replace(" going back ", " go back ").replace(" going home ", " go home ")
        val h = t.trim().split(' ').filter { it.isNotEmpty() && !isHesitation(it) }.map { ING[it] ?: it }
        // A softener goes at the start or the end, or next to a command word ("scroll quickly down", "can you maybe open
        // youtube"); never where it is the argument: "tap maybe later" is the Maybe later button.
        val lead = h.indexOfFirst { it !in SOFT_WORDS }.let { if (it < 0) h.size else it }
        val trail = h.indexOfLast { it !in SOFT_WORDS }
        val w = h.filterIndexed { i, x ->
            x !in SOFT_WORDS || (i > 0 && h[i - 1] in TAKES_ARG) || softLabelAt(h, i) ||
                !(i < lead || i > trail || h.getOrNull(i - 1) in COMMAND_START || h.getOrNull(i + 1) in COMMAND_START)
        }
        val out = ArrayList<String>()
        for ((i, x) in w.withIndex()) {
            // a filler "like": before a command word, or mid-phrase before an amount or at the end, or between "open"
            // and a name ("open like youtube"); never "like button", "like this", "tap like"
            if (x == "like" && (w.getOrNull(i + 1) in COMMAND_START ||
                    (i > 0 && w[i - 1] in LIKE_OPEN && i + 1 < w.size && w[i + 1] !in LIKE_NOUNS) ||
                    (i > 0 && w[i - 1] !in TAKES_ARG && (i == w.size - 1 || w[i + 1] in LIKE_BEFORE)))) continue
            if (out.isNotEmpty() && out.last() == x && !isNumberWord(x) && x !in REPEATABLE) continue
            out += x
        }
        return out
    }

    /** Politeness and wake words off the start, tails off the end ("hey canti could you open youtube for me"). */
    fun strip(text: String): String {
        var t = text.trim()
        var changed = true
        while (changed && t.isNotEmpty()) {
            changed = false
            val first = t.substringBefore(' ')
            if (first in setOf("hey", "ok", "okay", "hi", "yo", "hello") && t.split(' ').getOrNull(1) in WAKE && t.split(' ').size > 2) {
                t = t.split(' ').drop(2).joinToString(" "); changed = true; continue
            }
            if ((first in LEAD_WORDS || (first in SOFT_WORDS && !softLabelAt(t.split(' '), 0))) && t.contains(' ')) { t = t.substringAfter(' '); changed = true; continue }
            // a softener left at the end once a tail is off ("scroll down quickly for me"); "tap maybe" keeps it
            val lastWord = t.substringAfterLast(' ')
            if (lastWord in SOFT_WORDS && t.contains(' ') && t.removeSuffix(" $lastWord").substringAfterLast(' ') !in TAKES_ARG) {
                t = t.removeSuffix(" $lastWord"); changed = true; continue
            }
            for (p in LEAD_PHRASES) if (t.startsWith("$p ")) { t = t.removePrefix("$p "); changed = true; break }
            if (changed) continue
            for (p in TRAIL_PHRASES) {
                if (!t.endsWith(" $p")) continue
                val rest = t.removeSuffix(" $p")
                if (rest.substringAfterLast(' ') in TAKES_ARG) continue   // "tap okay": the word is the argument
                if (p == "right now" && rest.substringAfterLast(' ') in setOf("swipe", "flick", "go", "move", "scroll")) continue   // "swipe right now"
                t = rest; changed = true; break
            }
        }
        return t
    }

    /** The cleaned phrase: [basic], [tidy], [strip] ("Um, could you open YouTube, please?" -> "open youtube"). */
    fun normalize(raw: String): String = strip(tidy(basic(raw)).joinToString(" "))

    /** A unit said twice or more ("scroll down scroll down") -> once. */
    private fun once(w: List<String>): List<String> {
        for (u in 1..w.size / 2) {
            if (w.size % u != 0) continue
            val unit = w.subList(0, u)
            if ((0 until w.size / u).all { k -> w.subList(k * u, k * u + u) == unit }) return unit
        }
        return w
    }

    /** Split at self-corrections; each part, in order. A marker at the very end leaves an empty last part (retracted). */
    private fun corrections(w: List<String>): List<List<String>> {
        val parts = ArrayList<List<String>>(); var cur = ArrayList<String>(); var i = 0
        while (i < w.size) {
            val m = CORRECTIONS.firstOrNull { c ->
                val cw = c.split(' ')
                i + cw.size <= w.size && w.subList(i, i + cw.size) == cw && (cw.size > 1 || w.getOrNull(i - 1) !in TAKES_ARG)
            }
            if (m != null) { parts += cur; cur = ArrayList(); i += m.split(' ').size } else { cur += w[i]; i++ }
        }
        parts += cur
        return parts
    }

    // --- navigation ----------------------------------------------------------------------------------------------

    private const val ITEM = "(?: one| video| song| track| item| page| photo| picture| post| episode| clip| reel| short| tiktok| story)?"
    /** Spoken variants -> the [Vocab.PHRASES] phrase RuleDecider knows. First match wins (order matters). */
    private val NAV: List<Pair<Regex, String>> = listOf(
        "(?:go )?back one|the one before|(?:go to )?(?:the )?(?:previous|last)$ITEM" to "the one before",
        "(?:go |navigate )?back(?:wards)?(?: a page| one page)?|(?:go )?back to (?:the )?(?:previous|last) (?:screen|page)|(?:the )?(?:previous|last) screen|go backwards|back button" to "go back",
        "(?:go |take me |go to (?:the )?|go back |back )?home(?: screen| page)?" to "go home",
        "scroll(?: the page)?(?: down)?(?: a bit| a little| a bit more| a little more| more| some)?|page down|down a bit|(?:scroll|scrawl|school) down|(?:go|move) down(?: a bit| a little)?" to "scroll down",
        "scroll(?: the page)? up(?: a bit| a little| a bit more| a little more| more| some)?|page up|up a bit|scrawl up|(?:go|move) up(?: a bit| a little)?" to "scroll up",
        "(?:go to )?(?:the )?next$ITEM|skip(?: it| this one|(?: this| that| the)?$ITEM)" to "next",
        "pause(?: it| the video| the music| the song)?|stop the video|stop the music|hold on(?: a second| a sec| one second| one sec| a moment| a minute)?" to "pause",
        "play(?: it| the video| the music| the song)?|resume|keep playing|continue playing" to "play",
        "(?:show )?(?:the )?notifications|open notifications|pull down (?:the )?notifications" to "show notifications",
        "recent apps|recents|show open apps|app switcher" to "recent apps",
    ).map { (re, to) -> Regex("^(?:$re)$") to to }

    /** The like action's phrase ([Vocab.PHRASES]); reached only through [LIKE_FORM] or a like-button tap's fallback. */
    const val LIKE = "like this"
    private const val LIKEABLE = "(?:post|video|photo|picture|pic|reel|short|tweet|comment|song|track|story|clip|image|vid)"
    /** Explicit likes: "like this post", "like the video", "like it", "heart it", "heart this photo", "double tap to like". */
    private val LIKE_FORM = Regex("^(?:(?:like|heart|favou?rite) (?:this|that|the|this here) $LIKEABLE|like it|heart (?:it|this|that)|double tap to like)$")
    /** Tap names that mean the like button ("hit like", "press the like button", "tap the heart"). */
    private val LIKE_TARGETS = setOf("like", "like button", "like icon", "heart", "heart button", "heart icon")

    private val DIRECTIONS = setOf("up", "down")
    private val BACK_TO = Regex("^(?:go )?back to (?:the )?(?:previous|last) (?:screen|page)$")
    private val REPEAT = Regex("^(.+?) (twice|thrice|\\S+ times?)$")
    /** Nav phrases a count repeats; anything else ("go back three times", a like) is said once. */
    private val REPEATS = setOf("scroll down", "scroll up", "next", "the one before")

    private fun nav(t: String): String? {
        NAV.firstOrNull { it.first.matches(t) }?.let { return it.second }
        if (t == LIKE) return null   // bare "like this" is speech, not a like (see LIKE_FORM)
        if (Vocab.PHRASES.values.any { t in it } || t in Vocab.PAUSE_WORDS || t in Vocab.PLAY_WORDS) return t
        return null
    }

    // --- the grammar ---------------------------------------------------------------------------------------------

    private val OPEN = Regex("^(open|launch|lunch|start|run|go to|go back to|back to|switch to|switch over to|switch back to|return to|jump to|bring up|show me|show)(?: up)? (.+)$")
    /** Verbs that only ever name an app: an unknown name after them is "no app called ...", never a tap. */
    private val APP_ONLY_VERBS = setOf("launch", "lunch", "start", "run", "go back to", "back to", "switch to", "switch over to", "switch back to", "return to", "jump to")
    private val TAP = Regex("^(tap|tab|click|clique|klick|press|hit|select|touch|push|choose|pick)(?: on| at)? (.+)$")
    /** "tap" heard as "top": only with "on"/"the" after it ("top the search"), "top" alone is a place. */
    private val TOP = Regex("^top (?:on (?:the )?|the )(.+)$")
    private val NAME_LEAD = Regex("^(?:the|my|a|an|that|this)(?: |$)")
    private val APP_TAIL = Regex(" (?:app|application)$")

    private fun thing(s: String): String {
        var t = s.trim()
        while (NAME_LEAD.containsMatchIn(t)) t = t.replace(NAME_LEAD, "")
        return t.trim()
    }

    fun parse(raw: String, ctx: Context = Context()): SpeechCommand {
        val words = tidy(basic(raw))
        if (words.isEmpty()) return SpeechCommand.Ignore("empty")
        val whole = strip(words.joinToString(" "))
        if (whole in ctx.userPhrases) return SpeechCommand.Phrase(whole, "user phrase rule")
        // Cursor mode names elements, and "ok" or "yes" may be one: only pure hesitation is filler there.
        if (!ctx.cursor && words.all { it in ACK } && !LIKE_FORM.matches(whole)) return SpeechCommand.Ignore("filler")
        val parts = corrections(words)
        val last = strip(parts.last().joinToString(" "))
        if (last.isEmpty()) return if (parts.size > 1) SpeechCommand.Ignore("retracted") else SpeechCommand.Ignore("filler")
        // "swipe left, no, right": after a correction "right" is a direction, not an ack
        if (!ctx.cursor && last.split(" ").all { it in ACK } && !(parts.size > 1 && last == "right") && !LIKE_FORM.matches(last)) return SpeechCommand.Ignore("filler")
        if (last in ctx.userPhrases) return SpeechCommand.Phrase(last, "user phrase rule")
        if (parts.size > 1) {
            // "open youtube, no, spotify", "scroll down, i mean up": the correction borrows the verb it replaces.
            // The part corrected is the last non-empty one ("open facebook, sorry, i mean instagram" splits twice).
            val before = strip(parts.dropLast(1).lastOrNull { it.isNotEmpty() }?.joinToString(" ").orEmpty())
            // a lone "up"/"down" is a scroll by itself, but after a correction it replaces a word ("turn it up, no, down")
            if (before.isNotEmpty() && (single(last, ctx) == null || last in DIRECTIONS)) {
                // the correction replaces the end of what it corrects: "set a timer for ten, no, fifteen minutes",
                // keeping what followed the replaced word: "set a timer for five minutes, sorry, ten"
                val bw = before.split(' ')
                for (k in 1..minOf(3, bw.size - 1)) {
                    // a number replaces a number ("five minutes, sorry, ten": not "five ten")
                    if (isNumberWord(last.substringBefore(' ')) && !isNumberWord(bw[bw.size - k])) continue
                    val head = bw.dropLast(k).joinToString(" ") + " " + last
                    for (cand in listOf(head, (listOf(head) + bw.takeLast(k).drop(1)).joinToString(" ")).distinct()) {
                        val c = single(cand, ctx)
                        if (concrete(c) && c !is SpeechCommand.Tap) return c!!
                    }
                }
                val verb = (OPEN.find(before) ?: TAP.find(before))?.groupValues?.get(1) ?: before.substringBefore(' ')
                single("$verb $last", ctx)?.let { if (concrete(it)) return it }
            }
        }
        return command(last, ctx)
    }

    /** A command someone means, not just a parse: a navigation, an app, a timer with a length, a tap with a verb. */
    private fun concrete(c: SpeechCommand?): Boolean = when (c) {
        is SpeechCommand.Nav, is SpeechCommand.OpenApp, is SpeechCommand.AppMissing, is SpeechCommand.Volume, is SpeechCommand.Swipe -> true
        is SpeechCommand.Timer -> c.seconds != null
        is SpeechCommand.Tap -> c.verb != null
        else -> false
    }

    private fun command(text: String, ctx: Context): SpeechCommand {
        val said = text.split(' ').filter { it.isNotEmpty() }
        val words = once(said)
        val t = words.joinToString(" ")
        twoCommands(words, ctx, JOINERS)?.let { return it }
        val one = single(t, ctx)?.let { times(it, said.size / words.size) }
        if (one != null) {
            // "how long is left on the timer" is a question, not a timer to set
            if (one is SpeechCommand.Timer && one.seconds == null && !ctx.cursor && words.first() in CHATTER) return SpeechCommand.Ignore("chatter")
            return one
        }
        // run together without a joiner: "scroll down go home"
        if (words.size <= 12) twoCommands(words, ctx, null)?.let { return it }
        request(words, ctx)?.let { return it }
        if (ctx.cursor) return SpeechCommand.Tap(thing(t), null)
        if (words.first() in CHATTER) return SpeechCommand.Ignore("chatter")
        return SpeechCommand.Phrase(t, "unparsed")
    }

    /**
     * Two commands in one phrase, split at a joiner (or anywhere, [joiners] null): the same one twice -> it;
     * two different ones -> Ignore (one command per phrase, never a guess). Null: not two commands.
     */
    private fun twoCommands(w: List<String>, ctx: Context, joiners: List<String>?): SpeechCommand? {
        for (i in 1 until w.size) {
            val skip = if (joiners == null) 0 else joiners.firstOrNull { j ->
                val jw = j.split(' '); i + jw.size <= w.size && w.subList(i, i + jw.size) == jw
            }?.split(' ')?.size ?: continue
            if (i + skip >= w.size) continue
            val a = single(strip(w.subList(0, i).joinToString(" ")), ctx)
            if (!concrete(a)) continue
            val right = strip(w.subList(i + skip, w.size).joinToString(" "))
            var b = single(right, ctx)
            // "open youtube and spotify": the second app shares the verb (only apps: "tap terms and conditions" is one name)
            if (!concrete(b) && joiners != null && a is SpeechCommand.OpenApp) {
                val verb = OPEN.find(strip(w.subList(0, i).joinToString(" ")))?.groupValues?.get(1)
                if (verb != null) b = single("$verb $right", ctx)?.takeIf { it is SpeechCommand.OpenApp }
            }
            if (!concrete(b)) continue
            return if (a == b) a else SpeechCommand.Ignore("two commands: ${a!!.describe()} + ${b!!.describe()}")
        }
        return null
    }

    /** Words a request may start with before its command ("i want you to", "would you mind"), and how it may end. */
    private val REQUEST_WORDS = setOf("i", "you", "we", "want", "need", "would", "could", "can", "will", "should", "to", "go", "ahead",
        "and", "lets", "let", "us", "me", "mind", "try", "just", "now", "then", "so", "ok", "okay", "hey", "canti", "yeah", "alright",
        "well", "gonna", "wanna", "im", "going", "if", "do", "please")
    private val REQUEST_END = setOf("to", "you", "and", "mind", "lets", "canti", "ok", "okay", "now", "then", "so", "just", "please", "gonna", "wanna")

    /** "i really need you to go back": a request, then a command (at least two words) that ends the phrase. */
    private fun request(w: List<String>, ctx: Context): SpeechCommand? {
        for (k in 1..w.size - 2) {
            val pre = w.subList(0, k)
            if (!pre.all { it in REQUEST_WORDS } || pre.last() !in REQUEST_END) continue
            val c = single(strip(w.subList(k, w.size).joinToString(" ")), ctx)
            if (concrete(c)) return c
        }
        return null
    }

    /** A command said [n] times: a plain volume step n steps ("louder louder"); anything else once ("scroll down scroll down"). */
    private fun times(c: SpeechCommand, n: Int): SpeechCommand {
        if (n <= 1) return c
        if (c is SpeechCommand.Swipe && c.count == 1) return c.copy(count = n.coerceAtMost(SwipeGrammar.MAX_COUNT))   // "swipe right swipe right"
        if (c !is SpeechCommand.Volume) return c
        val s = c.op as? VolOp.Step ?: return c
        return if (!s.exact && s.fraction == null && s.steps == 1) c.copy(op = s.copy(steps = n.coerceAtMost(5))) else c
    }

    /** One command, or null: not one the grammar knows. */
    private fun single(t: String, ctx: Context): SpeechCommand? {
        if (t.isEmpty()) return null
        val words = t.split(' ')
        if ("timer" in words || "countdown" in words) return SpeechCommand.Timer(Durations.seconds(t)?.takeIf { it in 1..86_400 })
        VolumeGrammar.parse(t)?.let { v ->
            // cursor mode: a bare word ("mute") names an element first (a Mute button); the volume is the fallback
            return if (ctx.cursor && !t.contains(' ')) SpeechCommand.Tap(t, null, v) else v
        }
        // "go back to the previous screen" is back, not a pager swipe to the previous "screen"
        if (BACK_TO.matches(t)) return SpeechCommand.Nav("go back")
        SwipeGrammar.parse(t)?.let { return it }
        // Liking is outward (it always waits for a confirm pop) and "like" is the commonest filler: only an explicit
        // form likes ("like this post", "like it", "heart it"); any other phrase starting with "like" is filler.
        if (LIKE_FORM.matches(t)) return SpeechCommand.Nav(LIKE)
        if (words[0] == "like" && words.size > 1) {
            if (t == "like button" || t == "like icon") return SpeechCommand.Tap(t, null, SpeechCommand.Nav(LIKE))
            return SpeechCommand.Ignore("filler like")
        }
        // "scroll down three times", "next twice": a scroll or next/previous repeated (at most SwipeGrammar.MAX_COUNT)
        REPEAT.find(t)?.let { m ->
            val p = nav(m.groupValues[1]); val n = SwipeGrammar.count(m.groupValues[2])
            if (p != null && n != null) return SpeechCommand.Nav(p, if (p in REPEATS) n else 1)
        }
        // A lone "down" / "up" (user decision): a scroll only in a listen window opened on purpose; elsewhere nothing
        // (it is too common in speech), say "scroll down". In cursor mode it names an element first, as other bare words.
        if (t in DIRECTIONS) {
            val scroll = SpeechCommand.Nav("scroll $t")
            return when {
                ctx.cursor -> SpeechCommand.Tap(t, null, scroll.takeIf { ctx.window })
                ctx.window -> scroll
                else -> SpeechCommand.Ignore("lone direction outside a listen window: say \"scroll $t\"")
            }
        }
        nav(t)?.let { p ->
            // In cursor mode a bare word ("home", "next", "back") names an element first; the command is the fallback.
            return if (ctx.cursor && !t.contains(' ')) SpeechCommand.Tap(t, null, SpeechCommand.Nav(p)) else SpeechCommand.Nav(p)
        }
        OPEN.find(t)?.let { m ->
            val verb = m.groupValues[1]
            val name = thing(m.groupValues[2]).replace(APP_TAIL, "").trim()
            if (name.isNotEmpty()) {
                nav("open $name")?.let { return SpeechCommand.Nav(it) }   // "open the camera" = "open camera"
                val best = AppMatcher.best(name, ctx.apps)
                if (best != null) {
                    // two installed apps answer to the name (YouTube and a YouTube mod): the service picks or asks
                    val others = AppMatcher.ties(name, ctx.apps).map { it.app.pkg }.filter { it != best.app.pkg }
                    return SpeechCommand.OpenApp(best.app.pkg, best.app.label, best.score, others)
                }
                // an app's name that is not installed ("open snapchat"): say so, never tap screen text of that name
                AppMatcher.known(name)?.let { return SpeechCommand.AppMissing(it) }
                if (verb in APP_ONLY_VERBS) return if (nav(name) == "go home") SpeechCommand.Nav("go home") else null   // "go back to the home screen"
                if (verb == "open" || verb == "go to" || verb == "select") return SpeechCommand.Tap(name, verb)
            }
        }
        (TAP.find(t) ?: TOP.find(t))?.let { m ->
            val name = thing(m.groupValues.last())
            // "hit like", "tap the like button": the Like button on the screen, else the like action (both confirmed)
            val fb = if (name in LIKE_TARGETS) SpeechCommand.Nav(LIKE) else null
            if (name.isNotEmpty()) return SpeechCommand.Tap(name, if (m.groupValues.size > 2) m.groupValues[1] else "tap", fb)
        }
        return null
    }

    /** How concrete a parse is: a known command > a tap on something > a timer without a length > unparsed. */
    private fun rank(c: SpeechCommand, tapScore: ((String) -> Double)?): Int = when (c) {
        is SpeechCommand.OpenApp, is SpeechCommand.Nav, is SpeechCommand.Volume, is SpeechCommand.Swipe -> 4
        is SpeechCommand.AppMissing -> 1
        is SpeechCommand.Timer -> if (c.seconds != null) 4 else 1
        is SpeechCommand.Phrase -> when (c.why) { "user phrase rule" -> 4; else -> 0 }
        is SpeechCommand.Ignore -> 0
        is SpeechCommand.Tap -> when {
            tapScore == null -> 3
            tapScore(c.query) >= TargetMatcher.STRONG -> 3
            tapScore(c.query) >= TargetMatcher.WEAK -> 2
            c.fallback != null -> 2
            else -> 1
        }
    }

    /** The command for a recognizer result: each hypothesis parsed, the most concrete one wins (ties: recognizer order). */
    fun choose(h: Heard, ctx: Context = Context(), tapScore: ((String) -> Double)? = null): Pick {
        val hyps = h.hypotheses.take(5)
        if (hyps.isEmpty()) return Pick(-1, "", SpeechCommand.Ignore("empty"), emptyList())
        val parsed = hyps.map { parse(it, ctx) }
        var bestI = 0; var bestR = -1
        parsed.forEachIndexed { i, c -> val r = rank(c, tapScore); if (r > bestR) { bestR = r; bestI = i } }
        return Pick(bestI, hyps[bestI], parsed[bestI], parsed)
    }
}

// --- numbers and durations ---------------------------------------------------------------------------------------

/** Spoken or written numbers: "5", "1.5", "twenty five", "a hundred and twenty". */
object NumberWords {
    val UNITS = mapOf("zero" to 0, "one" to 1, "two" to 2, "three" to 3, "four" to 4, "five" to 5, "six" to 6, "seven" to 7,
        "eight" to 8, "nine" to 9, "ten" to 10, "eleven" to 11, "twelve" to 12, "thirteen" to 13, "fourteen" to 14,
        "fifteen" to 15, "sixteen" to 16, "seventeen" to 17, "eighteen" to 18, "nineteen" to 19)
    val TENS = mapOf("twenty" to 20, "thirty" to 30, "forty" to 40, "fourty" to 40, "fifty" to 50, "sixty" to 60,
        "seventy" to 70, "eighty" to 80, "ninety" to 90)

    /** A number starting at [i]: (value, tokens used), or null. "a"/"an" count only before hundred/thousand. */
    fun at(t: List<String>, i: Int): Pair<Double, Int>? {
        if (i >= t.size) return null
        t[i].toDoubleOrNull()?.let { return it to 1 }
        var total = 0L; var current = 0L; var j = i; var any = false
        while (j < t.size) {
            val w = t[j]
            when {
                w in UNITS -> {
                    val u = UNITS.getValue(w).toLong()
                    // "twenty five" continues; "five five" or "fifteen five" does not.
                    if (any && current % 100 != 0L && !(current % 10 == 0L && u < 10)) break
                    current += u; any = true
                }
                w in TENS -> { if (any && current % 100 != 0L) break; current += TENS.getValue(w); any = true }
                w == "hundred" -> { current = maxOf(current, 1) * 100; any = true }
                w == "thousand" -> { total += maxOf(current, 1) * 1000; current = 0; any = true }
                (w == "a" || w == "an") && !any && t.getOrNull(j + 1) in setOf("hundred", "thousand") -> {}
                w == "and" && any && (t.getOrNull(j + 1)?.let { it in UNITS || it in TENS } == true) -> {}
                else -> break
            }
            j++
        }
        return if (any) (total + current).toDouble() to (j - i) else null
    }

    fun parse(text: String): Double? {
        val t = PhraseGrammar.normalize(text).split(' ').filter { it.isNotEmpty() }
        val r = at(t, 0) ?: return null
        return if (r.second == t.size) r.first else null
    }
}

/** Timer lengths: "five minutes", "1 hour 30 minutes", "an hour and a half", "half a minute", "for minutes" (= 4). */
object Durations {
    private val UNIT = mapOf("second" to 1, "seconds" to 1, "sec" to 1, "secs" to 1,
        "minute" to 60, "minutes" to 60, "min" to 60, "mins" to 60, "minuets" to 60,
        "hour" to 3600, "hours" to 3600, "hr" to 3600, "hrs" to 3600)
    /** Heard in place of a number, accepted only directly before a unit with no number of its own. */
    private val SOUNDALIKE = mapOf("for" to 4.0, "fore" to 4.0, "to" to 2.0, "too" to 2.0, "won" to 1.0, "ate" to 8.0, "tree" to 3.0, "free" to 3.0)

    fun seconds(text: String): Int? {
        val t = PhraseGrammar.normalize(text).split(' ').filter { it.isNotEmpty() }
        var total = 0.0; var found = false; var i = 0
        fun unitAt(j: Int) = t.getOrNull(j)?.let { UNIT[it] }
        fun andAHalf(j: Int) = t.getOrNull(j) == "and" && t.getOrNull(j + 1) in setOf("a", "an") && t.getOrNull(j + 2) == "half"
        // "one minute thirty", "an hour and fifteen": a bare number after a unit is the next unit down
        fun downUnit(j: Int, u: Int): Int {
            if (u < 60) return j
            val k = if (t.getOrNull(j) == "and") j + 1 else j
            val rest = NumberWords.at(t, k) ?: return j
            if (unitAt(k + rest.second) != null || rest.first <= 0 || rest.first >= 60) return j
            total += rest.first * (u / 60); return k + rest.second
        }
        while (i < t.size) {
            val w = t[i]
            // "half an hour", "half a minute"
            if (w == "half" && t.getOrNull(i + 1) in setOf("a", "an") && unitAt(i + 2) != null) {
                total += 0.5 * unitAt(i + 2)!!; found = true; i += 3; continue
            }
            // "a minute", "an hour" (+ "and a half")
            if ((w == "a" || w == "an") && unitAt(i + 1) != null) {
                val u = unitAt(i + 1)!!; total += u; found = true; i += 2
                if (andAHalf(i)) { total += 0.5 * u; i += 3 } else i = downUnit(i, u)
                continue
            }
            val num = NumberWords.at(t, i)
            if (num != null) {
                var n = num.first; var j = i + num.second
                if (andAHalf(j) && unitAt(j + 3) != null) { n += 0.5; j += 3 }   // "two and a half minutes"
                val u = unitAt(j)
                if (u != null) {
                    total += n * u; found = true; j++
                    if (andAHalf(j)) { total += 0.5 * u; j += 3 }                // "an hour and a half"
                    else j = downUnit(j, u)
                    i = j; continue
                }
                // "three thirty", "one forty five", "3 30": minutes and seconds said like a clock (a timer is a length,
                // never a time of day); only two bare numbers, the second 10..59, and no unit anywhere
                val m = NumberWords.at(t, j)
                if (m != null && !found && t.none { it in UNIT } && n >= 1 && n < 100 && n == Math.floor(n) &&
                        m.first >= 10 && m.first < 60 && NumberWords.at(t, j + m.second) == null) {
                    total += n * 60 + m.first; found = true; i = j + m.second; continue
                }
                i = j; continue
            }
            val alike = SOUNDALIKE[w]
            if (alike != null && unitAt(i + 1) != null) { total += alike * unitAt(i + 1)!!; found = true; i += 2; continue }
            i++
        }
        return if (found && total > 0) Math.round(total).toInt() else null
    }
}

// --- apps --------------------------------------------------------------------------------------------------------

/** A launchable app: its launcher label and extra names people say. */
data class AppEntry(val pkg: String, val label: String, val aliases: List<String> = emptyList())

object AppMatcher {
    data class Match(val app: AppEntry, val score: Double, val via: String)
    const val STRONG = 0.8

    /** Names people say for common apps, used only when that package is installed (plus [Vocab.APPS]). */
    val ALIASES: Map<String, List<String>> = mapOf(
        "com.google.android.youtube" to listOf("you tube", "yt", "you too", "you tub"),
        "com.zhiliaoapp.musically" to listOf("tick tock", "tik tok", "tic toc"),
        "com.ss.android.ugc.trill" to listOf("tick tock", "tik tok"),
        "com.instagram.android" to listOf("insta", "ig"),
        "com.whatsapp" to listOf("whats app"),
        "com.google.android.apps.maps" to listOf("maps", "google maps"),
        "com.google.android.apps.photos" to listOf("photos", "google photos"),
        "com.android.chrome" to listOf("chrome", "google chrome", "browser"),
        "com.android.vending" to listOf("play store", "google play"),
        "com.google.android.gm" to listOf("gmail", "g mail"),
        "com.android.settings" to listOf("settings"),
        "com.sec.android.app.camera" to listOf("camera"),
        "com.samsung.android.messaging" to listOf("messages", "texts", "text messages"),
        "com.google.android.apps.messaging" to listOf("messages", "texts", "text messages"),
        "com.sec.android.app.clockpackage" to listOf("clock", "alarm", "alarms"),
        "com.google.android.deskclock" to listOf("clock", "alarm", "alarms"),
        "com.samsung.android.dialer" to listOf("phone", "dialer"),
        "com.google.android.dialer" to listOf("phone", "dialer"),
        "com.spotify.music" to listOf("spotify"),
        "com.reddit.frontpage" to listOf("reddit"),
        "com.netflix.mediaclient" to listOf("netflix"),
    )

    /** Launcher entries (package, label) -> entries with the aliases and [Vocab.APPS] names of installed packages. */
    fun entries(launcher: List<Pair<String, String>>): List<AppEntry> = launcher.distinctBy { it.first + "\u0000" + it.second }.map { (pkg, label) ->
        AppEntry(pkg, label, (ALIASES[pkg].orEmpty() + listOfNotNull(Vocab.APPS[pkg])).distinct())
    }

    private val VENDOR = setOf("google", "samsung", "galaxy", "microsoft", "the", "my")

    fun score(query: String, name: String): Double {
        val q = PhraseGrammar.basic(query); val n = PhraseGrammar.basic(name)
        val qc = Fuzzy.compact(q); val nc = Fuzzy.compact(n)
        if (qc.isEmpty() || nc.isEmpty()) return 0.0
        if (qc == nc) return 1.0
        val qs = Fuzzy.compact(q.split(' ').filter { it !in VENDOR }.joinToString(" "))
        val ns = Fuzzy.compact(n.split(' ').filter { it !in VENDOR }.joinToString(" "))
        if (qs.isNotEmpty() && qs == ns) return 0.97
        val qp = Fuzzy.phonetic(qs.ifEmpty { qc }); val np = Fuzzy.phonetic(ns.ifEmpty { nc })
        if (qp == np) return 0.92
        var s = 0.0
        if (qp.length >= 4 && np.startsWith(qp)) s = maxOf(s, 0.82)
        if (qp.length >= 4 && np.length >= 4) s = maxOf(s, Fuzzy.ratio(qp, np))
        return s
    }

    fun rank(query: String, apps: List<AppEntry>): List<Match> =
        apps.map { a ->
            (listOf(a.label) + a.aliases).map { name -> Match(a, score(query, name), name) }.maxByOrNull { it.score }!!
        }.filter { it.score > 0 }.sortedByDescending { it.score }

    /** Installed apps that answer to [query] about equally well (near-exact names): more than one = ambiguous. */
    fun ties(query: String, apps: List<AppEntry>): List<Match> {
        val r = rank(query, apps).distinctBy { it.app.pkg }
        val top = r.firstOrNull() ?: return emptyList()
        if (top.score < 0.95) return listOf(top)
        return r.filter { it.score >= 0.95 && it.score >= top.score - 0.03 }
    }

    /** App names people say, installed or not ("open snapchat": "no app called snapchat"). Brand names only: a generic word ("messages", "photos", "settings", "notes") may be an item inside the app, so it stays a tap. */
    val KNOWN: List<String> by lazy { (Vocab.APPS.values.filter { it != "Camera" } + listOf("snapchat", "snap chat", "telegram", "facebook",
        "messenger", "twitter", "linkedin", "linked in", "discord", "tiktok", "tik tok", "youtube", "you tube", "youtube music",
        "instagram", "whatsapp", "pinterest", "reddit", "netflix", "spotify", "prime video", "disney plus", "hulu",
        "twitch", "tumblr", "bereal", "wechat", "viber", "slack", "microsoft teams",
        "outlook", "uber", "lyft", "google play", "play store", "gmail", "chrome", "firefox", "duolingo", "kindle",
        "shazam", "waze", "paypal", "venmo", "cash app", "bluesky", "mastodon", "soundcloud", "audible")).map { PhraseGrammar.basic(it) }.distinct() }

    /** The known app name [query] says (near-exact), or null. */
    fun known(query: String): String? = KNOWN.firstOrNull { score(query, it) >= 0.92 }

    /** The app [query] names, or null: at least [STRONG], and clearly ahead of a different app unless near-exact. */
    fun best(query: String, apps: List<AppEntry>): Match? {
        val r = rank(query, apps).distinctBy { it.app.pkg }
        val top = r.firstOrNull() ?: return null
        if (top.score < STRONG) return null
        val second = r.getOrNull(1)
        if (top.score < 0.95 && second != null && second.score > top.score - 0.05) return null
        return top
    }
}

// --- on-screen targets -------------------------------------------------------------------------------------------

/**
 * "tap the plus button" -> the screen's targets ([Targets.build]): Tap when one clearly matches, Choose (highlight,
 * pop picks, hiss cancels) when the match is weak or several match, NotOnScreen when nothing does.
 */
object TargetMatcher {
    data class Scored(val target: Target, val score: Double)
    const val STRONG = 0.85
    const val WEAK = 0.5
    const val MARGIN = 0.1

    private val GROUPS: List<Set<String>> = listOf(
        setOf("plus", "add", "new", "create", "compose"),
        setOf("x", "close", "dismiss", "cancel", "exit"),
        setOf("search", "find", "magnifier", "magnifying"),
        setOf("menu", "more", "options", "overflow", "dots", "hamburger"),
        setOf("settings", "setting", "gear", "preferences", "cog"),
        setOf("back", "navigate", "return"),
        setOf("send", "submit"),
        setOf("ok", "okay", "done", "confirm", "yes", "accept"),
        setOf("like", "heart", "favorite", "favourite"),
        setOf("delete", "remove", "trash", "bin"),
        setOf("edit", "pencil"),
        setOf("mic", "microphone", "voice"),
        setOf("profile", "account", "avatar"),
        setOf("photo", "picture", "image"),
    )
    private val SYN: Map<String, Set<String>> = GROUPS.flatMap { g -> g.map { it to g } }.toMap()
    private val ROLE_WORDS = mapOf("button" to "button", "icon" to "button", "tab" to "tab", "field" to "text field",
        "box" to "text field", "bar" to "text field", "switch" to "switch", "toggle" to "switch", "checkbox" to "switch",
        "item" to "list item", "row" to "list item", "entry" to "list item", "image" to "image", "link" to "item", "option" to "item")
    private val POSITION_SAY = mapOf("upper left" to "top left", "upper right" to "top right", "lower left" to "bottom left",
        "lower right" to "bottom right", "middle" to "center", "centre" to "center")
    // "one" is a number word ("vocabulary one" = "01 vocabulary"), not filler; "the one"/"this one" still resolve to 1.
    private val FILLER = setOf("the", "a", "an", "that", "this", "on", "at", "in", "of", "corner", "screen")

    /** [full]: the whole name run together ("in box" = "Inbox", "add item" = "Add item"), checked before the parts. */
    private data class Query(val words: List<String>, val role: String?, val position: String?, val full: String)

    private val SAY_AS = mapOf("three dots" to "more options", "3 dots" to "more options", "kebab menu" to "more options",
        "hamburger menu" to "menu", "x button" to "close", "magnifying glass" to "search", "cog wheel" to "settings")

    private fun query(raw: String): Query {
        var t = " " + PhraseGrammar.basic(raw) + " "
        val full = Fuzzy.compact(t.trim().split(' ').dropWhile { it in setOf("the", "a", "an", "that", "this") }.joinToString(" "))
        for ((k, v) in SAY_AS) t = t.replace(" $k ", " $v ")
        for ((k, v) in POSITION_SAY) t = t.replace(" $k ", " $v ")
        var position: String? = null
        for (p in TargetVocab.POSITIONS.sortedByDescending { it.length }) {
            if (t.contains(" $p ")) { position = p; t = t.replaceFirst(" $p ", " "); break }
        }
        var words = t.trim().split(' ').filter { it.isNotEmpty() }
        var role: String? = null
        if (words.takeLast(2) == listOf("text", "field")) { role = "text field"; words = words.dropLast(2) }
        val kept = words.filter { it !in FILLER }.toMutableList()
        // A role word ("the plus button", "search bar", "the button at the top right") when there is more to go on.
        val ri = kept.indexOfLast { it in ROLE_WORDS }
        if (role == null && ri >= 0 && (kept.size > 1 || position != null)) { role = ROLE_WORDS[kept[ri]]; kept.removeAt(ri) }
        // "tap one": a bare filler word is the name itself when nothing else was said
        words = (if (kept.isEmpty() && position == null && role == null) words.filter { it !in setOf("the", "a", "an", "on", "at") } else kept).map(Fuzzy::digit)
        return Query(words, role, position, full)
    }

    private fun wordMatch(q: String, l: String): Boolean {
        if (q == l) return true
        if (SYN[q]?.contains(l) == true) return true
        // Number equivalence: "1" = "one" = "01" = "first" (up to 20; "6" = "06" = "six"); leading zeros ignored.
        val qn = number(q); val ln = number(l)
        if (qn != null && qn == ln) return true
        // Letter-prefix abbreviation: a short letter label token that begins the query word ("l" ~ "lesson", "ch" ~ "chapter").
        if (l.length in 1..3 && l.all { it.isLetter() } && q.length >= 4 && q.lowercase(Locale.ROOT).startsWith(l.lowercase(Locale.ROOT))) return true
        if (q.length >= 4 && l.length >= 4 && Fuzzy.ratio(Fuzzy.phonetic(q), Fuzzy.phonetic(l)) >= 0.8) return true
        return q.length >= 4 && l.startsWith(q)
    }

    /** A token as an integer when it is a number in any spoken form: digits (leading zeros ignored), a number word
     *  ("six", "twenty"), or an ordinal ("first", "1st", "20th"). Null otherwise. */
    internal fun number(tok: String): Int? {
        val t = tok.lowercase(Locale.ROOT)
        t.toIntOrNull()?.let { return it }
        NumberWords.UNITS[t]?.let { return it }
        NumberWords.TENS[t]?.let { return it }
        return ORDINALS[t]
    }

    /** "first".."twentieth" as their value (number equivalence up to at least 20). */
    private val ORDINALS: Map<String, Int> = run {
        val m = HashMap<String, Int>()
        val words = listOf("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth",
            "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth", "seventeenth", "eighteenth",
            "nineteenth", "twentieth")
        for ((i, w) in words.withIndex()) m[w] = i + 1
        m
    }

    fun score(t: Target, raw: String): Double = score(t, query(raw))

    private fun score(t: Target, q: Query): Double {
        if (t.label == "unlabeled") return 0.0
        // Label + context + tree parent words together ("01 Vocabulary · L06"), so a query naming both scores highest
        // ("lesson 6 vocabulary 1" covers the label and the parent's name). The tree parent is always available (it
        // lives on Target.parent, not the model-facing context), so the local match works with any model format.
        val extra = listOfNotNull(t.context, t.parent).distinct().joinToString(" ")
        val lw = PhraseGrammar.basic(t.label.removeSuffix("...") + (if (extra.isEmpty()) "" else " $extra"))
            .split(' ').filter { it.isNotEmpty() }.map(Fuzzy::digit)
        var s: Double
        val labelFull = Fuzzy.compact(lw.joinToString(" "))
        if (q.full.length >= 2 && q.full == labelFull) s = 1.0
        else if (q.words.isEmpty()) {
            // Only a place and/or a role ("the button at the top right"): never confident on its own.
            s = if (q.position != null || q.role != null) 0.55 else 0.0
        } else {
            val qc = Fuzzy.compact(q.words.joinToString(" ")); val lc = Fuzzy.compact(lw.joinToString(" "))
            s = when {
                lc.isEmpty() -> 0.0
                qc == lc -> 1.0
                Fuzzy.phonetic(qc) == Fuzzy.phonetic(lc) -> 0.95
                else -> {
                    val covered = q.words.count { w -> lw.any { wordMatch(w, it) } }
                    val used = lw.count { l -> q.words.any { wordMatch(it, l) } }
                    val cover = covered.toDouble() / q.words.size
                    val precision = if (lw.isEmpty()) 0.0 else used.toDouble() / lw.size
                    var v = if (cover == 1.0) 0.75 + 0.2 * precision else 0.3 + 0.5 * cover * (0.5 + 0.5 * precision)
                    if (cover == 0.0) v = 0.0
                    if (qc.length >= 4 && lc.contains(qc)) v = maxOf(v, 0.8)
                    if (lc.length >= 4 && qc.contains(lc)) v = maxOf(v, 0.8)
                    if (qc.length >= 4 && lc.length >= 4) v = maxOf(v, Fuzzy.ratio(Fuzzy.phonetic(qc), Fuzzy.phonetic(lc)).takeIf { it >= 0.75 } ?: 0.0)
                    v
                }
            }
        }
        if (s <= 0.0) return 0.0
        if (q.role != null) s += if (q.role == t.role) 0.05 else -0.05
        if (q.position != null) s += when {
            q.position == t.position -> 0.1
            t.position.split(' ').any { it in q.position.split(' ') } -> -0.1
            else -> -0.25
        }
        return s.coerceIn(0.0, 1.0)
    }

    fun rank(targets: List<Target>, raw: String): List<Scored> {
        val q = query(raw)
        return targets.map { Scored(it, score(it, q)) }.filter { it.score > 0 }.sortedByDescending { it.score }
    }

    fun best(targets: List<Target>, raw: String): Double = rank(targets, raw).firstOrNull()?.score ?: 0.0

    fun match(targets: List<Target>, raw: String): Targets.Outcome {
        val r = rank(targets, raw)
        val top = r.firstOrNull() ?: return Targets.Outcome.NotOnScreen
        if (top.score < WEAK) return Targets.Outcome.NotOnScreen
        val second = r.getOrNull(1)
        if (top.score >= STRONG && (second == null || second.score < top.score - MARGIN)) return Targets.Outcome.Tap(top.target)
        return Targets.Outcome.Choose(r.filter { it.score >= maxOf(WEAK, top.score - 0.15) }.take(3).map { it.target })
    }
}

/** String helpers for the matchers. */
object Fuzzy {
    fun compact(s: String) = s.filter { it.isLetterOrDigit() }

    private val DIGITS = NumberWords.UNITS.entries.associate { it.key to it.value.toString() }
    /** Number words as digits, so "tap 5" finds "five" and the other way round. */
    fun digit(w: String) = DIGITS[w] ?: w

    /** A rough sound-alike key: "netflicks" = "netflix", "tick tock" = "tiktok", "spotifi" = "spotify". */
    fun phonetic(s: String): String {
        var t = compact(s.lowercase(Locale.ROOT))
        t = t.replace("chr", "kr").replace("cks", "x").replace("ks", "x").replace("cs", "x").replace("ck", "k").replace("ph", "f")
            .replace("ch", "\u0001").replace("c", "k").replace("\u0001", "ch").replace("q", "k").replace("z", "s").replace("y", "i")
        val out = StringBuilder()
        for (ch in t) if (out.isEmpty() || out.last() != ch) out.append(ch)
        return out.toString()
    }

    fun ratio(a: String, b: String): Double {
        if (a.isEmpty() && b.isEmpty()) return 1.0
        return 1.0 - levenshtein(a, b).toDouble() / maxOf(a.length, b.length)
    }

    fun levenshtein(a: String, b: String): Int {
        var prev = IntArray(b.length + 1) { it }
        var cur = IntArray(b.length + 1)
        for (i in 1..a.length) {
            cur[0] = i
            for (j in 1..b.length) cur[j] = minOf(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + if (a[i - 1] == b[j - 1]) 0 else 1)
            val t = prev; prev = cur; cur = t
        }
        return prev[b.length]
    }
}
