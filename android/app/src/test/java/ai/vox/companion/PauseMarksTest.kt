package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Test

/** PauseMarks (PhraseGrammar.kt): which words were preceded by a >= 800 ms silence, from partial growth events. */
class PauseMarksTest {
    @Test fun marksWordsAfterAGap() {
        // "open settings" spoken quickly, then a >= 800 ms pause, then "tap" -> mark at index 2
        assertEquals(setOf(2), PauseMarks.indexes(listOf(1 to 0L, 2 to 100L, 3 to 900L)))
        // each word grows at a steady pace under the gap: no marks
        assertEquals(emptySet<Int>(), PauseMarks.indexes(listOf(1 to 0L, 2 to 200L, 3 to 400L)))
    }

    @Test fun firstWordIsNeverMarked() {
        // a long initial silence before the first word is not a mark (nothing precedes it)
        assertEquals(emptySet<Int>(), PauseMarks.indexes(listOf(1 to 5000L, 2 to 5100L)))
    }

    @Test fun aPartialThatDoesNotGrowAddsNothing() {
        // repeated same-count partials keep the first-seen time (a recognizer re-sending the same partial)
        assertEquals(setOf(2), PauseMarks.indexes(listOf(1 to 0L, 2 to 100L, 2 to 400L, 3 to 900L)))
    }

    @Test fun exactEdgeIsAMark() {
        // gap exactly 800 ms counts
        assertEquals(setOf(2), PauseMarks.indexes(listOf(1 to 0L, 2 to 100L, 3 to 900L), gapMs = 800))
        // gap 799 ms does not
        assertEquals(emptySet<Int>(), PauseMarks.indexes(listOf(1 to 0L, 2 to 100L, 3 to 899L), gapMs = 800))
    }
}
