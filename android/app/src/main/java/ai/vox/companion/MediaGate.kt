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
 * The unlock is `click click click` (user decision 2026-09-28: a pop counts as a click at intake): three sounds labelled
 * `click` (as delivered, so after [ai.vox.companion.audio.PhoneGate]'s 14 dB rule and after [SoundFold]), each starting
 * at most `gap_ms` after the previous one ended, with no other sound between. In round 4 the media alone produced 0 of
 * them in 5.4 minutes (hiss hiss 34, click click 39, pop-or-click pairs 40, a flat hum of 1 s or more 7; the extractor
 * labels media transients click, almost never pop: 2 pops in 322 sounds). Measured by the coordinator on
 * suite/out/zflip/echo_cancel_r4_events.jsonl (324 media sounds): raw click-or-pop chains with gaps <= 600 ms gave
 * 35 pairs and 14 triples; with the default level gate (12 dB SNR, -45 dBFS) that became 1 pair and 0 triples, and with
 * the 14 dB media rule 0 and 0. So the triple is safe only while the level gate and [ai.vox.companion.audio.PhoneGate]
 * hold.
 *
 * - Locked (media playing, [enabled]): every sound is dropped ([Verdict.DROP]); a click that advances the chain is
 *   dropped too ([Verdict.PART], `chain` = 1 or 2) and the third completes the unlock ([Verdict.UNLOCK], also dropped:
 *   the unlock does nothing else, in particular it does not open the phrase window, whose recognizer would hear the
 *   video). A non-click, or a click more than `gap_ms` after the previous one, restarts the chain.
 * - Unlocked: sounds pass ([Verdict.PASS]) to the normal rules (MicPopGate's click allow-list included) until the
 *   window ends. How it ends is [mode] (`media_unlock_mode`, coordinator 2026-09-27, pending the user's choice):
 *   - `one` (default): exactly the next gesture (the next sequence the sequencer resolves, whatever it decided) passes,
 *     then it re-locks; [unlockMs] is the time allowed to make it. A `click click click` as that gesture is
 *     listen-for-phrase.
 *   - `fixed`: [unlockMs] from the unlock, never extended.
 *   - `popext`: [unlockMs], and only another `click click click` inside the window extends it (by [unlockMs] from then);
 *     that triple is taken by the gate ([Resolution.EXTENDED]), it does not also listen.
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
    sealed class Verdict {
        /** Pass through to the normal rules. */
        object PASS : Verdict()
        /** Dropped, no chain progress (a non-click, or a click that restarted). */
        object DROP : Verdict()
        /** A click that advanced the unlock chain (not yet complete): [chain] = the count so far (1 or 2). */
        data class PART(val chain: Int) : Verdict()
        /** The third click: the unlock (also dropped). */
        object UNLOCK : Verdict()
    }
    /** What a resolved sequence did to an open window: nothing, closed it (`one`), or extended it (`popext`: consume it). */
    enum class Resolution { NONE, CLOSED, EXTENDED }

    private var chain = 0
    private var lastClickEndMs: Long? = null
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
        if (label != UNLOCK_LABEL) { chain = 0; lastClickEndMs = null; return Verdict.DROP }
        val last = lastClickEndMs
        if (last != null && startMs - last <= gapMs()) {
            chain++
            lastClickEndMs = endMs
            if (chain >= UNLOCK_COUNT) {
                chain = 0; lastClickEndMs = null
                openUntilMs = nowMs + unlockMs()
                return Verdict.UNLOCK
            }
            return Verdict.PART(chain)
        }
        chain = 1
        lastClickEndMs = endMs
        return Verdict.PART(1)
    }

    /**
     * The sequencer resolved [sequence] (a gesture from sounds that passed). `one`: the window closes; `popext`: a
     * `click click click` extends it and is consumed ([Resolution.EXTENDED]); `fixed`: nothing.
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

    private fun clear() { chain = 0; lastClickEndMs = null; openUntilMs = 0L }

    companion object {
        /** The label of each click of the unlock. */
        const val UNLOCK_LABEL = "click"
        val UNLOCK = listOf(UNLOCK_LABEL, UNLOCK_LABEL, UNLOCK_LABEL)
        const val UNLOCK_COUNT = 3
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
