package ai.vox.companion

/**
 * The phone-mic media lock (plain JVM, MediaGateTest). User decision 2026-09-27: while media plays on the phone's own
 * speaker (the one route the phone mic hears; earbuds / Bluetooth / USB headphones and a hearing aid do not lock —
 * VoxService passes [ai.vox.companion.audio.SpeakerRoute]'s test as [playing]), the phone mic (and a USB mic) ignores
 * every sound except a deliberate unlock. Pico sounds are never passed here.
 *
 * Why: Z Flip round 4 (suite/out/zflip/echo_cancel_r4*.jsonl, a YouTube Short on the speaker, nobody speaking, 60 s per
 * mic preset / echo-cancel setting) heard 36-100 sounds a minute and 30-47 a minute would have acted, on every setting.
 * The platform echo canceller does not fix it.
 *
 * The unlock is `pop pop`: two sounds labelled `pop` (as delivered, so after [ai.vox.companion.audio.PhoneGate]'s
 * 14 dB rule), the second starting at most `gap_ms` after the first ended, with no other sound between. In round 4
 * the media alone produced 0 of them in 5.4 minutes (hiss hiss 34, click click 39, pop-or-click pairs 40, a flat hum
 * of 1 s or more 7; the extractor labels media transients click, almost never pop: 2 pops in 322 sounds).
 *
 * - Locked (media playing, [enabled]): every sound is dropped ([Verdict.DROP]); a first pop is dropped too
 *   ([Verdict.FIRST_POP]) and the second completes the unlock ([Verdict.UNLOCK], also dropped: the unlock does nothing
 *   else, in particular it does not open the phrase window, whose recognizer would hear the video).
 * - Unlocked: sounds pass ([Verdict.PASS]) to the normal rules (MicPopGate's pop allow-list included) until the
 *   window ends. How it ends is [mode] (`media_unlock_mode`, coordinator 2026-09-27, pending the user's choice):
 *   - `one` (default): exactly the next gesture (the next sequence the sequencer resolves, whatever it decided) passes,
 *     then it re-locks; [unlockMs] is the time allowed to make it. A `pop pop` as that gesture is listen-for-phrase.
 *   - `fixed`: [unlockMs] from the unlock, never extended.
 *   - `popext`: [unlockMs], and only another `pop pop` inside the window extends it (by [unlockMs] from then); that
 *     `pop pop` is taken by the gate ([Resolution.EXTENDED]), it does not also listen.
 *   No mode extends on other gestures: the media alone makes 26-44 would-act sounds a minute (round 4), so a window that
 *   every action restarted rarely closed while the video played (8-19 media actions per unlock in a replay of the logs).
 * - Media stops (or leaves the speaker): the lock lifts at once ([onSound] passes, [mediaChanged] clears the window
 *   and a half unlock).
 *
 * Times: [onSound]'s sound stamps are the sequencer's device clock (elapsedRealtime for the phone mic); [nowMs] is
 * elapsedRealtime.
 */
class MediaGate(
    private val enabled: () -> Boolean,
    private val unlockMs: () -> Long,
    private val gapMs: () -> Long,
    private val mode: () -> String = { ONE },
) {
    enum class Verdict { PASS, DROP, FIRST_POP, UNLOCK }
    /** What a resolved sequence did to an open window: nothing, closed it (`one`), or extended it (`popext`: consume it). */
    enum class Resolution { NONE, CLOSED, EXTENDED }

    private var firstPopEndMs: Long? = null
    /** elapsedRealtime the window closes at; 0 = no window. */
    var openUntilMs = 0L; private set

    /** The lock applies (media on the phone's own speaker and the `media_gate` setting on); the window may still be open. */
    fun active(playing: Boolean) = playing && enabled()

    /** An unlock window is open now (only meaningful while [active]). */
    fun isOpen(nowMs: Long) = openUntilMs > nowMs

    /** One phone / USB mic sound: [label] as delivered, [startMs] / [endMs] its stamps, [playing] media on the phone's
     *  own speaker now. */
    fun onSound(label: String, startMs: Long, endMs: Long, nowMs: Long, playing: Boolean): Verdict {
        if (!active(playing)) { clear(); return Verdict.PASS }
        if (isOpen(nowMs)) return Verdict.PASS
        openUntilMs = 0L
        if (label != UNLOCK_LABEL) { firstPopEndMs = null; return Verdict.DROP }
        val first = firstPopEndMs
        if (first != null && startMs - first <= gapMs()) {
            firstPopEndMs = null
            openUntilMs = nowMs + unlockMs()
            return Verdict.UNLOCK
        }
        firstPopEndMs = endMs
        return Verdict.FIRST_POP
    }

    /**
     * The sequencer resolved [sequence] (a gesture from sounds that passed). `one`: the window closes; `popext`: a
     * `pop pop` extends it and is consumed ([Resolution.EXTENDED]); `fixed`: nothing.
     */
    fun resolved(sequence: List<String>, nowMs: Long, playing: Boolean): Resolution {
        if (!active(playing) || !isOpen(nowMs)) return Resolution.NONE
        return when (mode()) {
            ONE -> { openUntilMs = 0L; Resolution.CLOSED }
            POPEXT -> if (sequence == UNLOCK) { openUntilMs = nowMs + unlockMs(); Resolution.EXTENDED } else Resolution.NONE
            else -> Resolution.NONE
        }
    }

    /** Media (or the setting) changed: when the lock no longer applies, drop the window and a half unlock. True if a window was open. */
    fun mediaChanged(nowMs: Long, playing: Boolean): Boolean {
        if (active(playing)) return false
        val was = isOpen(nowMs)
        clear()
        return was
    }

    /** ms left in the window, 0 if closed. */
    fun leftMs(nowMs: Long) = (openUntilMs - nowMs).coerceAtLeast(0L)

    private fun clear() { firstPopEndMs = null; openUntilMs = 0L }

    companion object {
        /** Both sounds of the unlock. */
        const val UNLOCK_LABEL = "pop"
        val UNLOCK = listOf(UNLOCK_LABEL, UNLOCK_LABEL)
        const val ONE = "one"
        const val FIXED = "fixed"
        const val POPEXT = "popext"
        val MODES = listOf(ONE, FIXED, POPEXT)
        const val DEFAULT_UNLOCK_MS = 5000L
        val UNLOCK_MS_RANGE = 1000L..30_000L

        /** The sources the gate judges: the phone-mic source (the built-in or a USB mic) and its debug feed; never the Pico
         *  (`ble`, `ble-connect`, `ble-disconnect`) or the debug socket. */
        fun appliesTo(source: String) = source.startsWith(ai.vox.companion.audio.PhoneMicSource.NAME)
    }
}
