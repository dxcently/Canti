package ai.vox.companion.rec

import ai.vox.companion.Scheduler
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.file.Files

/** RecPlayer (contract L playback): the "playback" drop window (play + 500 ms tail) and the rec_play refusal, on an
 *  injectable scheduler and a fake backend. */
class RecPlayerTest {
    private class Task(val at: Long, val run: () -> Unit) { var cancelled = false }

    class FakeScheduler : Scheduler {
        var now = 0L
        private val tasks = mutableListOf<Task>()
        override fun now() = now
        override fun schedule(delayMs: Long, task: () -> Unit): () -> Unit {
            val t = Task(now + delayMs, task); tasks.add(t); return { t.cancelled = true }
        }
        fun advance(ms: Long) {
            now += ms
            val due = tasks.filter { !it.cancelled && it.at <= now }
            tasks.removeAll(due)
            due.forEach { it.run() }
        }
    }

    class FakeBackend : RecPlayer.Backend {
        var played: File? = null
        var stops = 0
        var pos = 0L
        override fun play(file: File) { played = file }
        override fun stop() { stops++ }
        override fun positionMs() = pos
    }

    @Test fun playbackDropHoldsDuringPlayAndTail() {
        val s = FakeScheduler(); val b = FakeBackend()
        val pushes = mutableListOf<Map<String, Any?>>()
        val p = RecPlayer(b, s) { pushes.add(it) }
        val f = Files.createTempFile("rec", ".wav").toFile()
        p.start("range-self-0001", "phone", "takes/range/x.wav", f, 1000L)
        assertTrue(p.dropping); assertEquals("playing", p.state)
        assertEquals("playback", RecDrops.reason(false, p.dropping))
        assertEquals("recording", RecDrops.reason(true, p.dropping))   // recording wins over playback
        assertEquals(f, b.played)

        s.advance(1000)   // the 100 ms pump observes elapsed >= dur: natural completion
        assertEquals("done", p.state)
        assertTrue(p.dropping)                       // the 500 ms tail still drops
        assertEquals("playback", RecDrops.reason(false, p.dropping))

        s.advance(RecPlayer.TAIL_MS + 1)             // after the tail the drop clears
        assertFalse(p.dropping)
        assertNull(RecDrops.reason(false, p.dropping))

        val states = pushes.map { it["state"] }
        assertTrue(states.contains("playing") && states.contains("done"))   // a push on each change
        assertTrue(pushes.any { it["pos_ms"] != null && it["dur_ms"] == 1000L })
    }

    @Test fun playStopKeepsTheTailThenClears() {
        val s = FakeScheduler(); val b = FakeBackend()
        val p = RecPlayer(b, s) {}
        p.start("n", "phone", "x.wav", Files.createTempFile("rec", ".wav").toFile(), 1000L)
        p.stop()
        assertEquals("stopped", p.state)
        assertTrue(p.dropping)                       // the 500 ms tail still holds after a manual stop
        s.advance(RecPlayer.TAIL_MS + 1)
        assertFalse(p.dropping)
        assertEquals(2, b.stops)                     // start() stops the old, stop() stops the current
    }

    @Test fun playRefusedWhileCountdownOrRecording() {
        assertNotNull(RecPlayer.refusal("recording"))
        assertNotNull(RecPlayer.refusal("countdown"))
        assertNull(RecPlayer.refusal("idle"))
        assertNull(RecPlayer.refusal("ready"))
        assertNull(RecPlayer.refusal("done"))
    }
}
