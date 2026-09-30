package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** ItemSwipe.kt: the destructive-hold countdown (fires, cancel, zero, ticks, and the speech freeze/resume). */
class SwipeHoldTest {
    private val scheduler = FakeScheduler()

    private fun hold(ms: Long, fire: () -> Unit = {}, cancel: () -> Unit = {}, tick: (Long) -> Unit = {}) =
        SwipeHold(scheduler, ms, tick, fire, cancel)

    @Test fun firesAfterHold() {
        var fired = 0
        val h = hold(1000, fire = { fired++ })
        h.start()
        assertTrue(h.running)
        scheduler.advance(1000)
        assertEquals(1, fired)
        assertFalse(h.running)
    }

    @Test fun cancelBeforeFireNeverFires() {
        var fired = 0
        var cancelled = 0
        val h = hold(1000, fire = { fired++ }, cancel = { cancelled++ })
        h.start()
        scheduler.advance(500)
        h.cancel("no")
        scheduler.advance(1000)
        assertEquals(0, fired)
        assertEquals(1, cancelled)
        assertFalse(h.running)
    }

    @Test fun zeroHoldFiresNow() {
        var fired = 0
        val h = hold(0, fire = { fired++ })
        h.start()
        assertEquals(1, fired)
        assertFalse(h.running)
    }

    @Test fun ticksCountDown() {
        val ticks = mutableListOf<Long>()
        hold(1000, tick = { ticks.add(it) }).start()
        assertEquals(listOf(1000L), ticks)
        scheduler.advance(100)
        scheduler.advance(100)
        assertEquals(listOf(1000L, 900L, 800L), ticks)
    }

    @Test fun freezePausesTheCountdownAndResumeContinues() {
        val ticks = mutableListOf<Long>()
        var fired = 0
        val h = hold(1000, fire = { fired++ }, tick = { ticks.add(it) })
        h.start()
        scheduler.advance(300)
        h.freeze()
        assertEquals(700L, ticks.last())   // the frozen seconds are shown
        scheduler.advance(500)
        assertEquals(0, fired)
        assertEquals(700L, ticks.last())   // still frozen
        h.resume()
        scheduler.advance(700)
        assertEquals(1, fired)
        assertFalse(h.running)
    }
}

/** A deterministic Scheduler for SwipeHold: [advance] runs due tasks in time order. */
private class FakeScheduler : Scheduler {
    var nowMs = 0L
        private set

    private class Task(val at: Long, val run: () -> Unit) { var done = false }

    private val tasks = ArrayList<Task>()

    override fun now() = nowMs

    override fun schedule(delayMs: Long, task: () -> Unit): () -> Unit {
        val t = Task(nowMs + delayMs, task)
        tasks.add(t)
        return { t.done = true }
    }

    fun advance(ms: Long) {
        val end = nowMs + ms
        while (true) {
            val next = tasks.filter { !it.done && it.at <= end }.minByOrNull { it.at } ?: break
            next.done = true
            nowMs = next.at
            next.run()
        }
        nowMs = end
    }
}
