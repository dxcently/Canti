package ai.vox.companion

/**
 * Smart swipes (pure Kotlin, no Android; PhraseGrammarTest, SwipeTest).
 *
 * DIRECTION CONVENTION (one place, tested both ways in SwipeTest):
 *  - A *swipe* word names the finger: "swipe right" / "flick right" = the finger moves left -> right = `swipe_right`
 *    (as the arch/dip gestures and the model vocabulary have it: in a photo viewer that shows the previous photo).
 *  - A *content* word names what you want to see: "scroll right", "go right", "move right", "what's on the right" =
 *    bring the content on the right into view = the finger moves right -> left = `swipe_left`. Mirror for left.
 *  - *Next / previous* ("next photo", "go back two pictures") follow the screen ([SwipePlan.semantic]): the rules'
 *    screen tie-break (video feed vertical, photo viewer and document horizontal), else a horizontal noun (photo,
 *    slide, story, card, tab, page) swipes horizontally, else a visible "Next"/"Previous" button is tapped, else the
 *    rules decide (media next/previous). Horizontal next/previous are mirrored in right-to-left layouts; explicit and
 *    content directions are physical and never mirrored.
 * Counts ("swipe right twice", "go three photos forward", "skip two") repeat the swipe, at most [MAX_COUNT] times.
 */
object SwipeGrammar {
    const val MAX_COUNT = 5

    /** Nouns that mean a horizontal pager when the screen type does not say. */
    val HORIZONTAL = setOf("photo", "picture", "pic", "image", "slide", "story", "card", "tab", "page", "screen", "shot")
    /** Items the rules' tie-break already handles (video feed, player): one of them next/previous stays a plain nav phrase. */
    private val ITEMS = setOf("video", "song", "track", "item", "episode", "clip", "reel", "short", "tiktok", "post", "one", "thing")
    /** Items that only live in a vertical feed (Reels, Shorts, TikTok): next/previous is a vertical fling on any screen. */
    val VERTICAL = setOf("reel", "short", "tiktok")
    // "skip this reel", "skip that video", "skip the short"
    private val SKIP_THIS = Regex("^skip (?:this|that|the) (\\S+)$")

    private val PLURAL = mapOf("photos" to "photo", "pictures" to "picture", "pics" to "pic", "images" to "image", "slides" to "slide",
        "stories" to "story", "cards" to "card", "tabs" to "tab", "pages" to "page", "screens" to "screen", "shots" to "shot",
        "videos" to "video", "songs" to "song", "tracks" to "track", "items" to "item", "episodes" to "episode", "clips" to "clip",
        "reels" to "reel", "shorts" to "short", "tiktoks" to "tiktok", "posts" to "post", "ones" to "one", "things" to "thing")

    private const val DIR = "(left|right|up|down)"
    private const val TAIL = "(?: on (?:it|this|that|him|her|them|this one|that one))?"
    private val EXPLICIT = Regex("^(?:swipe|flick|fling|slide)(?: it| this| that| the screen| the page| the photo| the picture)?(?: over)?(?: to the| towards the| to| towards)? $DIR$TAIL(?: (.+))?$")
    /** "swipe it/this/that <dir>": a deictic subject, which VoxService upgrades to an item swipe when a target exists (J1). */
    private val DEICTIC_SUBJECT = Regex("^(?:swipe|flick|fling|slide) (it|this|that) ")
    private val CONTENT = Regex("^(?:scroll|go|move|pan|look|shift)(?: it| the page| the screen| over)?(?: to the| over to the| towards the| to| towards| over)? (left|right)(?: (.+))?$")
    private val WHATS_ON = Regex("^(?:(?:let me |lets )?see |show me |show )?(?:whats|what is) (?:on|to|over on|off to) the (left|right)$")

    private val NEXT_WORDS = setOf("next", "forward", "forwards", "ahead", "following")
    private val PREV_WORDS = setOf("previous", "last", "prior", "back", "backward", "backwards", "before", "earlier")
    // "next photo", "the next three photos", "swipe to the next picture", "show me the previous slide"
    private val ADJ = Regex("^(?:(?:swipe|go|move|flick|skip|jump|scroll|show me|show|take me|bring me|bring up|give me|open) )?(?:to |back to )?(?:the )?(next|previous|last|prior|following) (?:(\\S+(?: \\S+)?) )?(\\S+)$")
    // "go three photos forward", "go forward two pictures", "skip two photos", "back three pictures", "skip 2"
    private val MOVE = Regex("^(?:(go|move|skip|jump|swipe|flick|scroll|page) )?(?:(forward|forwards|ahead|back|backward|backwards) )?(?:(\\S+(?: \\S+)?) )?(?!(?:forward|forwards|ahead|back|backward|backwards)$)(\\S+)(?: (forward|forwards|ahead|back|backward|backwards))?$")

    /** Counts: "twice", "three times", "2 times", "x3". */
    fun count(s: String?): Int? {
        if (s.isNullOrBlank()) return 1
        val w = s.trim().split(' ')
        when (s.trim()) { "once", "again", "a bit", "a little", "a little bit", "some", "more", "a bit more" -> return 1; "twice" -> return 2; "thrice" -> return 3 }
        val n = NumberWords.at(w, 0) ?: return null
        val rest = w.drop(n.second)
        if (rest.isNotEmpty() && rest != listOf("times") && rest != listOf("time")) return null
        return n.first.toInt().coerceIn(1, MAX_COUNT)
    }

    private fun num(s: String?): Int? {
        if (s.isNullOrBlank()) return 1
        val w = s.split(' ')
        val n = NumberWords.at(w, 0)?.takeIf { it.second == w.size } ?: return when (s) { "a" -> 1; "a couple" -> 2; "a couple of" -> 2; "a few" -> 3; else -> null }
        return n.first.toInt().coerceIn(1, MAX_COUNT)
    }

    private fun noun(w: String): String? { val s = PLURAL[w] ?: w; return if (s in HORIZONTAL || s in ITEMS) s else null }

    // W4 system pulls, matched before EXPLICIT (its trailing "( .+)?" would swallow "swipe up for recents").
    private val RECENTS = Regex("^swipe up (?:for recents|from the bottom and hold)$")
    private val QUICK_SETTINGS = Regex("^(?:pull down(?: the)?|open) quick settings$")
    private val CLOSE_SHADE = Regex("^close(?: the)?(?: notifications| quick settings| shade)$")
    private val PULL_REFRESH = Regex("^(?:pull to refresh|refresh(?: this| the page))$")

    /** The swipe (or a plain nav phrase for one ordinary "next video") in [t] (a cleaned phrase), or null. */
    fun parse(t: String): SpeechCommand? {
        if (RECENTS.matches(t)) return SpeechCommand.Nav("recent apps")
        if (QUICK_SETTINGS.matches(t)) return SpeechCommand.SystemAction("quick_settings", "swipe grammar")
        if (CLOSE_SHADE.matches(t)) return SpeechCommand.SystemAction("close_shade", "swipe grammar")
        if (PULL_REFRESH.matches(t)) return SpeechCommand.SystemAction("pull_refresh", "swipe grammar")
        EXPLICIT.find(t)?.let { m ->
            val n = count(m.groupValues[2]) ?: return null
            return SpeechCommand.Swipe("swipe_${m.groupValues[1]}", null, n, "finger", deictic = DEICTIC_SUBJECT.containsMatchIn(t))
        }
        CONTENT.find(t)?.let { m ->
            val n = count(m.groupValues[2]) ?: return null
            return SpeechCommand.Swipe(if (m.groupValues[1] == "right") "swipe_left" else "swipe_right", null, n, "content")
        }
        WHATS_ON.find(t)?.let { m -> return SpeechCommand.Swipe(if (m.groupValues[1] == "right") "swipe_left" else "swipe_right", null, 1, "content") }
        ADJ.find(t)?.let { m ->
            val next = m.groupValues[1] in NEXT_WORDS
            val nn = noun(m.groupValues[3]) ?: return@let
            val n = num(m.groupValues[2].ifEmpty { null }) ?: return@let
            return semantic(next, nn, n)
        }
        SKIP_THIS.find(t)?.let { m -> noun(m.groupValues[1])?.let { return semantic(true, it, 1) } }
        MOVE.find(t)?.let { m ->
            val verb = m.groupValues[1]
            val d1 = m.groupValues[2]; val d2 = m.groupValues[5]
            if (d1.isNotEmpty() && d2.isNotEmpty()) return@let
            val dirWord = d1.ifEmpty { d2 }
            val last = m.groupValues[4]
            val nn = noun(last)
            val qty = m.groupValues[3].ifEmpty { null }
            when {
                // "skip two", "skip 2 videos", "skip three photos": skip means forward
                verb == "skip" && dirWord.isEmpty() -> {
                    if (nn == null) { val n = num(listOfNotNull(qty, last).joinToString(" ")) ?: return@let; if (qty != null && num(qty) == null) return@let
                        return if (n == 1) null else semantic(true, null, n) }
                    val n = num(qty) ?: return@let
                    return semantic(true, nn, n)
                }
                dirWord.isEmpty() || nn == null -> return@let
                // "go back one photo", "go three photos forward", "back two pictures", "forward 3 slides"
                verb.isEmpty() && dirWord !in setOf("back", "forward", "ahead") -> return@let
                else -> {
                    val n = num(qty) ?: return@let
                    return semantic(dirWord in NEXT_WORDS, nn, n)
                }
            }
        }
        return null
    }

    private fun semantic(next: Boolean, noun: String?, n: Int): SpeechCommand {
        val phrase = if (next) "next" else "the one before"
        // one ordinary item ("next video", "previous song"): the existing nav phrase and its screen tie-break
        if (n == 1 && (noun == null || (noun in ITEMS && noun !in VERTICAL))) return SpeechCommand.Nav(phrase)
        return SpeechCommand.Swipe(null, if (next) "next" else "previous", n, noun ?: "")
    }
}

/** Where a next/previous goes on this screen (see [SwipeGrammar]'s convention). */
object SwipePlan {
    /** [action]: an action key to perform; [tapButton]: tap the screen's Next/Previous button instead; [via]: why. */
    data class Plan(val action: String?, val tapButton: Boolean, val via: String)

    fun mirror(action: String): String = when (action) { "swipe_left" -> "swipe_right"; "swipe_right" -> "swipe_left"; else -> action }

    /**
     * [next]: next or previous; [noun]: what was named ("photo", "" for none); [screenKind]: the screen summary's kind;
     * [hasButton]: a clear Next/Previous control is on screen; [rtl]: the layout reads right to left.
     */
    fun semantic(next: Boolean, noun: String, screenKind: String?, hasButton: Boolean, rtl: Boolean): Plan {
        val base = if (next) "next_item" else "previous_item"
        val tie = RuleDecider.screenTieBreak(if (next) "next" else "the one before", base, screenKind?.takeIf { it in Vocab.SCREEN_KIND }?.let { ScreenContext(it, "none", "not scrollable", "hidden") })
        // a reel, a short, a tiktok: always the vertical feed's fling, never a media key (whatever the screen reads as)
        if (noun in SwipeGrammar.VERTICAL) return Plan(if (next) "swipe_up" else "swipe_down", false, "noun: $noun")
        if (tie != base) return Plan(if (rtl) mirror(tie) else tie, false, "screen: $screenKind")
        if (noun in SwipeGrammar.HORIZONTAL) {
            val a = if (next) "swipe_left" else "swipe_right"
            return Plan(if (rtl) mirror(a) else a, false, "noun: $noun")
        }
        if (hasButton) return Plan(null, true, "button")
        return Plan(base, false, "rules")
    }
}
