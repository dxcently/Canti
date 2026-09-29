package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The transcript strip model (TranscriptStrip.kt) with a fake scheduler and measure: no Android needed. */
class TranscriptStripTest {
    private class Clock : Scheduler {
        var t = 0L
        private val tasks = mutableListOf<Pair<Long, () -> Unit>>()
        override fun now() = t
        override fun schedule(delayMs: Long, task: () -> Unit): () -> Unit {
            val e = (t + delayMs) to task; tasks += e; return { tasks.remove(e) }
        }
        fun advance(ms: Long) {
            val end = t + ms
            while (true) {
                val next = tasks.filter { it.first <= end }.minByOrNull { it.first } ?: break
                tasks.remove(next); t = maxOf(t, next.first); next.second()
            }
            t = end
        }
        val pending get() = tasks.size
    }

    /** A fake measure: each character is one unit wide (words are joined with a single space). */
    private fun measure(s: String) = s.length.toFloat()

    @Test fun liveWordsDimOnlyTheLastPartialWord() {
        assertEquals(listOf(Word("open", Tone.INK), Word("youtube", Tone.DIM)), StripWords.live("", "open youtube"))
        assertEquals(emptyList<Word>(), StripWords.live("", ""))
        // dictation: settled words ink, then the partial with its last word dim
        assertEquals(
            listOf(Word("Hello,", Tone.INK), Word("how", Tone.INK), Word("are", Tone.DIM)),
            StripWords.live("Hello,", "how are"),
        )
        assertEquals(listOf(Word("Hello,", Tone.INK)), StripWords.live("Hello,", ""))
    }

    @Test fun finalIsAllInk() {
        assertEquals(
            listOf(Word("open", Tone.INK), Word("youtube", Tone.INK)),
            StripWords.final("open youtube"),
        )
    }

    @Test fun markSetsBadTonesWithoutMutating() {
        val w = listOf(Word("a", Tone.INK), Word("b", Tone.INK), Word("c", Tone.INK))
        assertEquals(listOf(Word("a", Tone.BAD), Word("b", Tone.INK), Word("c", Tone.BAD)), StripWords.mark(w, setOf(0, 2)))
        assertEquals(Word("a", Tone.INK), w[0])   // the input is unchanged
    }

    @Test fun fitWrapsAndKeepsTheLastTwoLines() {
        val w = listOf("one", "two", "three", "four", "five").map { Word(it, Tone.INK) }
        // width 9 fits "one two" (7) but not "one two three" (13): lines [one two][three four][five]
        val lines = StripWords.fit(w, 9f, ::measure)
        assertEquals(listOf(listOf("three"), listOf("four", "five")), lines.map { it.map(Word::text) })
    }

    @Test fun fitHandlesOneOverLongWord() {
        val w = listOf(Word("supercalifragilistic", Tone.INK), Word("x", Tone.INK))
        // the long word alone exceeds the width but still occupies one line (clipped by the view), never wrapped forever
        val lines = StripWords.fit(w, 5f, ::measure)
        assertEquals(listOf(listOf("supercalifragilistic"), listOf("x")), lines.map { it.map(Word::text) })
    }

    @Test fun notOnScreenUnderlinesTheQueryRun() {
        val w = StripWords.final("open the walrus app")
        val (row, bad) = StripReasons.notOnScreen(w, "walrus app")
        assertEquals(StripRow.Miss("no \"walrus app\" here", true), row)
        assertEquals(setOf(2, 3), bad)   // "walrus app", not "open" or "the"
    }

    @Test fun noAppUnderlinesTheAppName() {
        val w = StripWords.final("open walrus")
        val (row, bad) = StripReasons.noApp(w, "walrus")
        assertEquals(StripRow.Miss("no app called \"walrus\"", true), row)
        assertEquals(setOf(1), bad)
    }

    @Test fun unknownNamesTheFirstUnknownWord() {
        val known = setOf("the", "list")
        val w = StripWords.final("frobnicate the list")
        val (row, bad) = StripReasons.unknown(w, known)
        assertEquals(StripRow.Miss("don't know \"frobnicate\"", true), row)
        assertEquals(setOf(0), bad)
    }

    @Test fun allKnownWordsUnderlineEverything() {
        val known = setOf("open", "youtube")
        val w = StripWords.final("open youtube")
        val (row, bad) = StripReasons.unknown(w, known)
        assertEquals(StripRow.Miss("don't know \"open\"", true), row)
        assertEquals(setOf(0, 1), bad)
    }

    @Test fun numbersAreNeverUnknown() {
        val known = setOf("the", "list")
        val w = StripWords.final("frobnicate five the list")
        val (row, bad) = StripReasons.unknown(w, known)
        assertEquals(StripRow.Miss("don't know \"frobnicate\"", true), row)
        assertEquals(setOf(0), bad)   // "five" is a number, never underlined as unknown
    }

    @Test fun noWordsWhyAndAsk() {
        assertEquals(StripRow.Miss("couldn't make out words", true) to emptySet<Int>(), StripReasons.noWords())
        assertEquals(StripRow.Miss("one command at a time", true) to emptySet<Int>(), StripReasons.why("one command at a time"))
        assertEquals(StripRow.Ask("which app?") to emptySet<Int>(), StripReasons.ask("which app?"))
    }

    @Test fun clipValueEllipsizesTheQuotedPart() {
        assertEquals("no \"walrus app\" here", StripReasons.clipValue("no \"walrus app\" here", 100f, ::measure))
        // keep at most what fits after the frame (before + "…" + after), ellipsizing inside the quotes
        assertEquals("no \"wal…\" here", StripReasons.clipValue("no \"walrus app\" here", 14f, ::measure))
    }

    @Test fun leftRowWording() {
        assertEquals("2 LEFT" to "say 1 or 2", StripRow.Left(2).key to StripRow.Left(2).value)
        assertEquals("3 LEFT" to "say 1, 2 or 3", StripRow.Left(3).key to StripRow.Left(3).value)
        assertEquals("5 LEFT" to "say 1 to 5", StripRow.Left(5).key to StripRow.Left(5).value)
    }

    @Test fun retryRule() {
        fun ok(vararg over: Pair<Int, Boolean>) = RetryRule.allowed(
            userOpened = over.firstOrNull { it.first == 0 }?.second ?: true,
            alreadyRetried = over.firstOrNull { it.first == 1 }?.second ?: false,
            dictating = over.firstOrNull { it.first == 2 }?.second ?: false,
            sameGeneration = over.firstOrNull { it.first == 3 }?.second ?: true,
            armed = over.firstOrNull { it.first == 4 }?.second ?: true,
            paused = over.firstOrNull { it.first == 5 }?.second ?: false,
            choiceOpen = over.firstOrNull { it.first == 6 }?.second ?: false,
            confirmPending = over.firstOrNull { it.first == 7 }?.second ?: false,
            windowOpen = over.firstOrNull { it.first == 8 }?.second ?: false,
            stripEnabled = over.firstOrNull { it.first == 9 }?.second ?: true,
        )
        assertTrue(ok())   // a user-opened first miss
        assertFalse(ok(1 to true))                       // second miss
        assertFalse(ok(0 to false))                      // never PICK / DICTATE
        assertFalse(ok(2 to true))                       // dictating
        assertFalse(ok(3 to false))                      // generation changed
        assertFalse(ok(4 to false))                      // disarmed
        assertFalse(ok(5 to true))                       // paused
        assertFalse(ok(6 to true))                       // choice open
        assertFalse(ok(7 to true))                       // confirm pending
        assertFalse(ok(8 to true))                       // window already open
        assertFalse(ok(9 to false))                      // setting off
    }

    @Test fun stripPlace() {
        // no IME: above the nav bar
        assertEquals(800 - 16 - 160, StripPlace.top(1000, 800, 40, 160, null, null))
        // IME without a field: above the IME
        assertEquals(500 - 16 - 160, StripPlace.top(1000, 800, 40, 160, 500, null))
        // IME with a field overlapping the band: above the field
        assertEquals(300 - 16 - 160, StripPlace.top(1000, 800, 40, 160, 500, intArrayOf(0, 300, 1000, 400)))
        // IME with a field above the band: stays above the IME
        assertEquals(500 - 16 - 160, StripPlace.top(1000, 800, 40, 160, 500, intArrayOf(0, 100, 1000, 200)))
        // too tall for the space left: just below the status bar
        assertEquals(40 + 16, StripPlace.top(1000, 800, 40, 760, null, null))
    }

    @Test fun cellsLeftEdgesAndRounding() {
        assertEquals(8, cellsLeft(0, 8000, 8000))
        assertEquals(0, cellsLeft(8000, 8000, 8000))
        assertEquals(4, cellsLeft(4000, 8000, 8000))     // exactly half
        assertEquals(5, cellsLeft(3950, 8000, 8000))     // 4.05 rounds up (ceil)
        assertEquals(5, cellsLeft(3900, 8000, 8000))     // 4.1 -> ceil 5
        assertEquals(8, cellsLeft(-100, 8000, 8000))     // clamped up
        assertEquals(0, cellsLeft(9000, 8000, 8000))     // clamped down
    }

    @Test fun resultHidesAfterTwoSeconds() {
        val c = Clock(); val m = StripModel(c)
        val frames = mutableListOf<StripFrame?>()
        m.onChange = { frames += it }
        m.open(StripKind.LISTEN, 6000)
        m.final("open youtube")
        m.result(StripRow.Done("open youtube"), emptySet())
        assertEquals(1, c.pending)   // the hide is scheduled
        assertTrue(frames.last()!!.visible)
        c.advance(StripModel.RESULT_MS)
        assertNull(frames.last())   // null is delivered when hidden
        assertEquals(0, c.pending)
    }

    @Test fun dictateKeepsEndAndDoesNotAutoHide() {
        val c = Clock(); val m = StripModel(c)
        val frames = mutableListOf<StripFrame?>()
        m.onChange = { frames += it }
        m.open(StripKind.DICTATE, 4000)
        m.result(StripRow.End(), emptySet())
        assertEquals(0, c.pending)   // no hide scheduled while dictating
        assertTrue(frames.last()!!.visible)
        c.advance(10_000)
        assertTrue(frames.last()!!.visible)
    }

    @Test fun pickRowStaysWhileChoosing() {
        val c = Clock(); val m = StripModel(c)
        m.onChange = { }
        m.open(StripKind.PICK, 8000)
        m.result(StripRow.Left(3), emptySet())
        assertEquals(0, c.pending)   // a picker's "n LEFT" row does not auto-hide (the choice window ends it)
    }

    @Test fun openCancelsAPendingHide() {
        val c = Clock(); val m = StripModel(c)
        m.onChange = { }
        m.open(StripKind.LISTEN, 6000)
        m.final("open youtube")
        m.result(StripRow.Done("open youtube"), emptySet())
        assertEquals(1, c.pending)
        m.open(StripKind.LISTEN, 4000)   // a re-open (retry) cancels the hide
        assertEquals(0, c.pending)
    }

    @Test fun retryKeepsTheMissRowUntilTheFirstNewPartial() {
        val c = Clock(); val m = StripModel(c)
        val frames = mutableListOf<StripFrame?>()
        m.onChange = { frames += it }
        m.open(StripKind.LISTEN, 6000)
        m.final("open the walrus app")
        val (row, bad) = StripReasons.notOnScreen(StripWords.final("open the walrus app"), "walrus app")
        m.result(row, bad)
        assertEquals(row, frames.last()!!.row)
        m.open(StripKind.LISTEN, 4000)   // the retry window re-opens the same ticket
        assertEquals(row, frames.last()!!.row)   // the miss row stays visible
        m.partial("open the walrus")            // the first new partial clears it
        assertNull(frames.last()!!.row)
    }

    @Test fun dictationSettlesThenShowsAPartial() {
        val c = Clock(); val m = StripModel(c)
        val frames = mutableListOf<StripFrame?>()
        m.onChange = { frames += it }
        m.open(StripKind.DICTATE, 4000)
        m.typed("Hello,")
        assertEquals(listOf(Word("Hello,", Tone.INK)), frames.last()!!.lines.flatten())
        m.partial("how are")
        assertEquals(
            listOf(Word("Hello,", Tone.INK), Word("how", Tone.INK), Word("are", Tone.DIM)),
            frames.last()!!.lines.flatten(),
        )
        m.quiet(c.t + 4000)
        assertEquals(c.t + 4000, frames.last()!!.deadline)
    }
}
