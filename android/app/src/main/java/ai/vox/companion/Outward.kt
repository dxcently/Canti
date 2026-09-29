package ai.vox.companion

/**
 * Outward (publicly visible) actions: like, follow, share, repost, comment, send, post... ALWAYS wait for a confirm
 * pop, whatever decided them (rules, grammar, cloud, local model) and at any confidence (user decision). Canti shows
 * what it is about to do ("Like? pop to confirm") and waits `confirm_timeout_ms`; no pop, nothing happens.
 * Scroll, back, home, volume, swipes and the rest stay instant.
 *
 * One table ([ACTIONS]) classifies every action key. A key missing from it (a new action) is classified by its words:
 * outward if any word is in [WORDS] ("share_post", "follow_user"), else instant; OutwardTest fails until every
 * vocabulary key is listed here explicitly. Screen targets (a tap on a named button) are outward when their label
 * has one of [WORDS] ("Like", "Follow", "Share", "Send"). [mayDispatch] is the Executor's own last check: an outward
 * action without a confirm is refused even if a caller forgot to ask.
 */
object Outward {
    enum class Kind { OUTWARD, INSTANT }

    val ACTIONS: Map<String, Kind> = linkedMapOf(
        // outward: acts on someone else's content where others see it
        "like" to Kind.OUTWARD,
        "double_tap" to Kind.OUTWARD,   // a double-tap at the centre is how feeds like a post (Executor: the same gesture as like)
        // instant (reversible or private)
        "swipe_up" to Kind.INSTANT, "swipe_down" to Kind.INSTANT, "swipe_left" to Kind.INSTANT, "swipe_right" to Kind.INSTANT,
        "tap" to Kind.INSTANT, "long_press" to Kind.INSTANT, "back" to Kind.INSTANT, "home" to Kind.INSTANT,
        "recents" to Kind.INSTANT, "notifications" to Kind.INSTANT, "scroll_up" to Kind.INSTANT, "scroll_down" to Kind.INSTANT,
        "zoom_in" to Kind.INSTANT, "zoom_out" to Kind.INSTANT, "next_item" to Kind.INSTANT, "previous_item" to Kind.INSTANT,
        "play_pause" to Kind.INSTANT, "volume_up" to Kind.INSTANT, "volume_down" to Kind.INSTANT, "open_camera" to Kind.INSTANT,
        "take_photo" to Kind.INSTANT, "listen_for_phrase" to Kind.INSTANT, "none" to Kind.INSTANT, "forward" to Kind.INSTANT,
        // cursor mode
        "stop" to Kind.INSTANT, "click" to Kind.INSTANT, "drag_toggle" to Kind.INSTANT,
        "grid_pick_1" to Kind.INSTANT, "grid_pick_5" to Kind.INSTANT, "grid_pick_9" to Kind.INSTANT,
        // grammar commands executed directly
        "volume" to Kind.INSTANT, "open_app" to Kind.INSTANT, "set_timer" to Kind.INSTANT, "tap_target" to Kind.INSTANT,
        // typing by voice (VoiceTyping.kt): only sets a text box's text, never presses send or enter
        "type_text" to Kind.INSTANT,
    )

    /** Words of an outward action or button label. */
    val WORDS = setOf("like", "unlike", "heart", "love", "favorite", "favourite", "follow", "unfollow", "subscribe", "unsubscribe",
        "share", "repost", "reshare", "retweet", "reblog", "quote", "comment", "reply", "send", "post", "publish", "tweet", "upload",
        "upvote", "downvote", "react", "invite", "friend", "join", "duet", "stitch", "remix", "gift", "donate", "tip", "vote")

    private fun words(s: String): List<String> = s.lowercase().split(Regex("[^a-z]+")).filter { it.isNotEmpty() }

    /** Cursor moves ("move_up_fast") are instant by family. */
    fun kind(action: String): Kind = ACTIONS[action]
        ?: if (action.startsWith("move_")) Kind.INSTANT
        else if (words(action).any { it in WORDS }) Kind.OUTWARD else Kind.INSTANT

    fun isOutward(action: String): Boolean = kind(action) == Kind.OUTWARD

    /** A screen target is outward when its label (or description) has an outward word: "Like", "Follow", "Send message". */
    fun isOutwardTarget(label: String): Boolean = words(label).any { it in WORDS }

    /** The Executor's last check: an outward action is dispatched only after a confirm pop. */
    fun mayDispatch(action: String, confirmed: Boolean): Boolean = confirmed || !isOutward(action)
    fun mayTap(label: String, confirmed: Boolean): Boolean = confirmed || !isOutwardTarget(label)

    /** `outward_confirm_ms`: its own window, not the Confirmer's screen-change timeout (`confirm_timeout_ms`). */
    const val DEFAULT_CONFIRM_MS = 3000L
    val CONFIRM_MS_RANGE = 500L..30_000L

    /** The confirm-pop window for [why] ([Risk.why]): outward -> [outwardMs]; an unscored risky action -> [riskyMs] (target_choose_ms). */
    fun windowMs(why: String, outwardMs: Long, riskyMs: Long): Long = if (why.startsWith("outward")) outwardMs else riskyMs

    /** The badge question: "Like? click to confirm", "Tap Follow? click to confirm". */
    fun question(what: String): String = "${what.replace('_', ' ').replaceFirstChar { it.uppercase() }}? click to confirm"
}
