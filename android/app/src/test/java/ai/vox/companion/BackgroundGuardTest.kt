package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** [BackgroundGuard]: an open calibration / training round ends when Canti is in the background, and only then. */
class BackgroundGuardTest {
    private class Clock : Scheduler {
        var t = 0L
        val tasks = mutableListOf<Pair<Long, () -> Unit>>()
        override fun now() = t
        override fun schedule(delayMs: Long, task: () -> Unit): () -> Unit {
            val e = (t + delayMs) to task; tasks += e; return { tasks.remove(e) }
        }
        fun advance(ms: Long) {
            val end = t + ms
            while (true) {
                val next = tasks.filter { it.first <= end }.minByOrNull { it.first } ?: break
                tasks.remove(next); t = next.first; next.second()
            }
            t = end
        }
    }

    private val grace = VoxService.BACKGROUND_GRACE_MS
    private val clock = Clock()
    private val fired = mutableListOf<Long>()
    private val g = BackgroundGuard(clock, grace) { fired += it }
    private val main = Any()
    private val settings = Any()

    @Test fun homeOrTheScreenOffEndsItAfterTheGrace() {
        g.started(main)
        g.stopped(main)
        clock.advance(grace - 1)
        assertTrue(fired.isEmpty())
        clock.advance(1)
        assertEquals(listOf(grace), fired)
        assertFalse(g.foreground)
        clock.advance(10 * grace)   // once per stretch in the background
        assertEquals(1, fired.size)
    }

    @Test fun aQuickLookAwayMidStepDoesNot() {
        g.started(main)
        g.stopped(main)
        clock.advance(grace / 2)
        g.started(main)   // back within the grace
        clock.advance(10 * grace)
        assertTrue(fired.isEmpty())
        assertTrue(g.foreground)
    }

    @Test fun movingBetweenCantiScreensDoesNot() {
        // the next screen starts before the old one stops (Android's order), either way round
        g.started(main)
        g.started(settings); g.stopped(main)
        clock.advance(10 * grace)
        g.started(main); g.stopped(settings)
        clock.advance(10 * grace)
        assertTrue(fired.isEmpty())
    }

    @Test fun aRecreateThatStopsFirstIsWithinTheGrace() {
        val old = Any(); val new = Any()
        g.started(old)
        g.stopped(old); clock.advance(300); g.started(new)
        clock.advance(10 * grace)
        assertTrue(fired.isEmpty())
    }

    @Test fun aStopOfAScreenNeverSeenStartedIsIgnored() {
        g.stopped(main)
        clock.advance(10 * grace)
        assertTrue(fired.isEmpty())
    }

    @Test fun clearDropsAPendingCheck() {
        g.started(main); g.stopped(main)
        g.clear()
        clock.advance(10 * grace)
        assertTrue(fired.isEmpty())
    }
}
