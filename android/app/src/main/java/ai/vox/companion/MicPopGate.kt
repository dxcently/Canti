package ai.vox.companion

/**
 * Phone-mic clicks (plain JVM, MicPopGateTest). Pop is folded into click at intake (user decision 2026-09-28), so a lone
 * click from the phone/USB mic has no default action in gesture mode, in any app, unless the user binds ["click"]; the
 * Pico's lone click taps, and cursor-mode clicks from every source tap. The phone's own mic hears the room: on the Z Flip
 * (round 4, 2026-09-27, suite/out/zflip/events_phone_mic_r4.jsonl) 236 sounds in 4 min, and all 5 clicks that got past
 * the touch guard became taps, one of them a real tap(center) in YouTube (a -34.6 dB mouth sound 110 ms after a
 * background hiss). The Pico's mic sits at the user's mouth; the phone's does not.
 *
 * So while the sound source is a phone or USB mic ([MicSettings.usesMic]), user decision 2026-09-27 (kept):
 *  - a lone click has no default action in gesture mode, in any app ([unbound]; logged `unbound{source: phone}`). It
 *    taps only where the user binds it (a global or per-app rule: the rule is the allow-list).
 *  - a click never taps or double-taps in gesture mode unless the user bound that sequence ([gates]), whatever decided
 *    it (a model included).
 *  - safety net: a sequence with a click never does an outward action ([Outward]) in a social / video / messaging app
 *    ([APPS]), even when the user bound it, and a click never confirms one there ([gatesConfirm]). Logged
 *    `gated{why: phone_mic}`.
 * Cursor mode is the exception: a click taps from every source (the user turns cursor mode on on purpose). Navigation,
 * scrolling, listen-for-phrase and every sound from the Pico (click = tap by default) are unchanged.
 * Whether to lift this for the phone mic is an OPEN QUESTION for the coordinator; this policy is unchanged.
 */
object MicPopGate {
    const val WHY = "phone_mic"
    /** `unbound{source}` for a phone or USB mic's lone click. */
    const val SOURCE = "phone"
    val CLICK = listOf("click")

    /** Feeds, video and messaging, where a stray tap likes, opens, plays or sends. By package (not the screen). */
    val APPS: Set<String> = setOf(
        "com.google.android.youtube", "app.rvx.android.youtube", "app.revanced.android.youtube",
        "com.zhiliaoapp.musically", "com.ss.android.ugc.trill", "com.ss.android.ugc.aweme",
        "com.instagram.android", "com.instagram.barcelona",
        "com.facebook.katana", "com.facebook.lite", "com.facebook.orca",
        "com.twitter.android", "com.reddit.frontpage", "com.snapchat.android", "com.pinterest", "com.linkedin.android",
        "com.tumblr", "xyz.blueskyweb.app", "tv.twitch.android.app",
        "com.discord", "com.whatsapp", "org.telegram.messenger",
    )

    private val DISCRETE = setOf("pop", "click")
    private val TAPS = setOf("tap", "double_tap")

    /** A lone click in gesture mode with no user rule for it: no action ([userBound]: a global or per-app rule binds "click"). */
    fun unbound(usesMic: Boolean, mode: String, sequence: List<String>, userBound: Boolean): Boolean =
        usesMic && mode == "gesture" && sequence == CLICK && !userBound

    /**
     * A decision ([action]) from a sequence with a click that must not run: an outward action in [APPS]
     * (bound or not), or a gesture-mode tap / double-tap the user did not bind ([userBound]: the sequence's own rule).
     */
    fun gates(usesMic: Boolean, app: String, sequence: List<String>, action: String, mode: String = "gesture",
              userBound: Boolean = false): Boolean {
        if (!usesMic || sequence.none { it in DISCRETE }) return false
        if (app in APPS && Outward.isOutward(action)) return true
        return mode == "gesture" && action in TAPS && !userBound
    }

    /** A confirm click for an outward action or an outward button ([what]: the action key or the target label). */
    fun gatesConfirm(usesMic: Boolean, app: String, what: String): Boolean =
        usesMic && app in APPS && (Outward.isOutward(what) || Outward.isOutwardTarget(what))
}
