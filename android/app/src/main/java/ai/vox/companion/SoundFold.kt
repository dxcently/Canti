package ai.vox.companion

/**
 * The single point where a "pop" becomes a "click" (user decision 2026-09-28: a pop counts as a click on every source —
 * the Pico, the phone mic, the USB mic, the tick detector, the debug socket). The mapping runs once, at intake, in
 * [VoxService.features] before anything downstream, so the sequencer, the decider, the media gate, personalization and
 * the event log all see "click".
 *
 * Components upstream of this point see the raw labels ON PURPOSE: [ai.vox.companion.audio.PhoneMicSource]'s level gate
 * (it treats pop and click the same), [VoiceJoystick.filter] and the calibration's `extractorEvent` read the extractor's
 * own labels, which still say "pop".
 */
object SoundFold {
    const val FROM = "pop"
    const val TO = "click"

    /** `pop` -> `click`, anything else unchanged. */
    fun label(l: String): String = if (l == FROM) TO else l

    /** The sequence with every label folded. */
    fun seq(l: List<String>): List<String> = l.map(::label)

    /** A sound line that starts with [Vocab.DISCRETE]'s "a short lip pop" gets "a tongue click" in place of that prefix;
     *  the rest of the line (the measured duration, loudness, sounds-like) is kept. Both strings are ones the models
     *  already know. */
    fun line(s: String): String {
        val pop = Vocab.DISCRETE.getValue(FROM)
        return if (s.startsWith(pop)) Vocab.DISCRETE.getValue(TO) + s.removePrefix(pop) else s
    }

    /** A message with the sequence and sounds folded; timing, features, gated, id, mode, phrase and the rest are kept. */
    data class Folded(val msg: FeatureMessage, val raw: List<String>?)

    /** Folds [m]'s sequence and sounds; `raw` is the original sequence when anything changed, else null. */
    fun fold(m: FeatureMessage): Folded {
        val sequence = seq(m.sequence)
        val sounds = m.sounds.map(::line)
        val changed = sequence != m.sequence || sounds != m.sounds
        return Folded(m.copy(sequence = sequence, sounds = sounds), if (changed) m.sequence else null)
    }
}

/**
 * One mouth click is never heard twice (user decision 2026-09-28): the phone mic's extractor and its tick detector both
 * report the same click, and the BLE / debug path may deliver a copy. Click detections whose spans overlap, or lie within
 * [slackMs] of each other, merge into one click — [accept] returns false for the copy.
 *
 * The logged case: the extractor's click 3733859-3733929 and the tick detector's pop 3733880-3733920
 * ([VoiceJoystick] `deliverTickPop`'s fixed 40 ms span) are one mouth click. The user's deliberate doubles are 140-220 ms
 * apart, so they are never merged (a click ends and the next starts well over 30 ms later).
 *
 * The merge is per source string: the phone mic's extractor sounds and its tick-detector pops share
 * [ai.vox.companion.audio.PhoneMicSource.NAME]. Different sources never merge.
 */
class ClickMerge(private val slackMs: Long = SLACK_MS) {
    private class Span(var startMs: Long, var endMs: Long)

    /** The last accepted click span per source; a merged copy is unioned into it. */
    private val last = HashMap<String, Span>()

    /**
     * False (= the same sound again) when [startMs]..[endMs] overlaps the last accepted click span from [source] after
     * widening both by [slackMs] (`start <= last.end + slack && end >= last.start - slack`). A merged span is unioned
     * into the kept one, so a third copy also merges. A start more than [CLOCK_RESET_MS] before the kept span's start is
     * a new clock (the mic restarted): forget it and accept.
     */
    fun accept(source: String, startMs: Long, endMs: Long): Boolean {
        val kept = last[source]
        if (kept == null || startMs < kept.startMs - CLOCK_RESET_MS) {
            last[source] = Span(startMs, endMs)
            return true
        }
        if (startMs <= kept.endMs + slackMs && endMs >= kept.startMs - slackMs) {
            kept.startMs = minOf(kept.startMs, startMs)
            kept.endMs = maxOf(kept.endMs, endMs)
            return false
        }
        kept.startMs = startMs
        kept.endMs = endMs
        return true
    }

    fun reset() { last.clear() }

    companion object {
        const val SLACK_MS = 30L
        /** A start this far before the kept span's start is a clock reset, not a copy. */
        const val CLOCK_RESET_MS = 5000L
    }
}

/**
 * Cursor-mode double-tap guard (user decision 2026-09-28): after a cursor-mode click taps, a click that starts within
 * [refractoryMs] of that click's end is dropped — the user's quick doubles were retries after missed pops, not a second
 * tap. A hiss in between does not reset it (the window is against the last TAPPING click's end). Cursor mode has no
 * sequencer waits, so each click taps at once; this is what stops a double-tap.
 */
class CursorClickGuard(private val refractoryMs: Long = CURSOR_CLICK_REFRACTORY_MS) {
    private var lastClickEndMs: Long? = null

    /** True = this click taps; false = dropped (refractory). Only a tapping click becomes the new reference. */
    fun click(startMs: Long, endMs: Long): Boolean {
        val last = lastClickEndMs
        if (last != null && startMs - last <= refractoryMs) return false
        lastClickEndMs = endMs
        return true
    }

    fun reset() { lastClickEndMs = null }

    companion object {
        const val CURSOR_CLICK_REFRACTORY_MS = 400L
    }
}
