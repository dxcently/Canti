package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The pop->click fold and the intake click merge (SoundFold.kt, user decisions 2026-09-28). */
class SoundFoldTest {
    private val popLine = "a short lip pop; instant sound; loudness normal; sounds like mouth sound"
    private val clickLine = "a tongue click; instant sound; loudness normal; sounds like mouth sound"

    private fun msg(sequence: List<String>, sounds: List<String>? = null): FeatureMessage = FeatureMessage(
        id = 1, mode = "gesture", armed = true,
        sounds = sounds ?: sequence.map { if (it == "pop") popLine else if (it == "click") clickLine else "a hiss; duration short (150-400 ms); loudness normal; sounds like mouth sound" },
        sequence = sequence, phrase = null,
        timing = listOf(Stamp(0, 40), null), features = null, gated = listOf(null, null),
    )

    @Test fun foldMapsPopToClickAndKeepsTheRest() {
        val m = msg(listOf("pop"), listOf(popLine))
        val f = SoundFold.fold(m)
        assertEquals(listOf("click"), f.msg.sequence)
        assertEquals(listOf(clickLine), f.msg.sounds)
        assertEquals(listOf("pop"), f.raw)
        assertEquals(m.timing, f.msg.timing)
        assertEquals(m.features, f.msg.features)
        assertEquals(m.gated, f.msg.gated)
        assertEquals(m.id, f.msg.id)
        assertEquals(m.mode, f.msg.mode)
    }

    @Test fun foldLeavesNonPopSequencesUntouched() {
        val m = msg(listOf("rise", "click"))
        val f = SoundFold.fold(m)
        assertEquals(listOf("rise", "click"), f.msg.sequence)
        assertNull(f.raw)
    }

    @Test fun mergeOfOverlappingDetectionsIsOneClick() {
        // The logged case: the extractor's click and the tick detector's 40 ms pop are one mouth click.
        val m = ClickMerge()
        assertTrue(m.accept("phone-mic", 3733859, 3733929))
        assertFalse(m.accept("phone-mic", 3733880, 3733920))
        // In the reverse arrival order exactly one is also true.
        val r = ClickMerge()
        assertTrue(r.accept("phone-mic", 3733880, 3733920))
        assertFalse(r.accept("phone-mic", 3733859, 3733929))
    }

    @Test fun slackMergesCloseClicksButNotDeliberateDoubles() {
        // c. (0,40) then (65,100) merged (gap 25); (0,40) then (75,110) accepted (gap 35); (0,40) then (180,220) accepted.
        assertFalse(ClickMerge().run { accept("phone-mic", 0, 40); accept("phone-mic", 65, 100) })    // gap 25 merges
        assertTrue(ClickMerge().run { accept("phone-mic", 0, 40); accept("phone-mic", 75, 110) })     // gap 35 is a new click
        assertTrue(ClickMerge().run { accept("phone-mic", 0, 40); accept("phone-mic", 180, 220) })    // a deliberate double
    }

    @Test fun unionMeansAThirdCopyMerges() {
        val m = ClickMerge()
        assertTrue(m.accept("phone-mic", 0, 40))
        assertFalse(m.accept("phone-mic", 30, 90))
        assertFalse("within 30 of the union's end 90", m.accept("phone-mic", 110, 130))
    }

    @Test fun noStampPassesAndSourcesNeverMerge() {
        val m = ClickMerge()
        assertTrue(m.accept("a", 0, 40))
        assertTrue("another source never merges", m.accept("b", 0, 40))
    }

    @Test fun aClockGoingBackMoreThanFiveSecondsResets() {
        val m = ClickMerge()
        assertTrue(m.accept("phone-mic", 100_000, 100_040))
        assertTrue("a start > 5 s before the kept span is a new clock", m.accept("phone-mic", 94_000, 94_020))
    }

    @Test fun composedMergeAndMediaGateCountOncePerClick() {
        val gate = MediaGate({ true }, { 5000L }, { 600L })
        val merge = ClickMerge()
        fun click(start: Long, end: Long): MediaGate.Verdict? {
            if (!merge.accept("phone-mic", start, end)) return null   // the copy is dropped at intake
            return gate.onSound("click", start, end, end, true)
        }
        // One click heard twice (overlapping) + one more click: only 2 of 3, so no unlock.
        assertEquals(MediaGate.Verdict.PART(1), click(0, 40))
        assertNull(click(20, 60))
        assertEquals(MediaGate.Verdict.PART(2), click(200, 240))
        assertFalse(gate.isOpen(240))
        // A third distinct click unlocks.
        assertEquals(MediaGate.Verdict.UNLOCK, click(400, 440))
        assertTrue(gate.isOpen(440))
    }

    @Test fun cursorClickGuardDropsRetriesAfterAMissedPop() {
        // 2026-09-28: a cursor-mode click taps at once; a click within 400 ms of the tap is a retry, dropped.
        val g = CursorClickGuard()
        assertTrue("first click taps", g.click(0, 40))
        assertFalse("+200 is a retry, dropped", g.click(200, 240))
        assertTrue("+600 is a fresh tap", g.click(600, 640))
        // a hiss in between does not reset the window (it is against the last tapping click's end)
        val h = CursorClickGuard()
        assertTrue(h.click(0, 40))
        assertFalse("a hiss in between does not reset it", h.click(200, 240))
        g.reset()
        assertTrue("after reset the next click taps", g.click(10_000, 10_040))
    }
}
