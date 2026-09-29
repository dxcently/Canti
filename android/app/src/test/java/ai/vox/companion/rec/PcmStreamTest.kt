package ai.vox.companion.rec

import ai.vox.companion.Scheduler
import org.json.JSONObject
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.file.Files
import java.util.Base64

/** The PC stream (contract §5 pcm_*): refusals, read windows, restart, idle close, and the recorder/drop hooks. */
class PcmStreamTest {
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
        fun pending() = tasks.count { !it.cancelled }
    }

    class FakeEnv : PcmStream.Env {
        override var source = "phone"
        override val micName = "phone built-in mic"
        override var capturing = true
        override var listening = true
        override var mode = "gesture"
        override var calibrating = false
        override var training = false
        override var measuring = false
        override var recording = false
    }

    private val RATE = 16000

    private fun ringWrite(r: RingBuffer, samples: ShortArray, firstFrame: Long, gen: Int, rate: Int = RATE) {
        val b = ByteBuffer.allocateDirect(samples.size * 2).order(ByteOrder.nativeOrder())
        for (s in samples) b.putShort(s)
        r.write(b, samples.size, firstFrame, rate, gen)
    }

    private fun b64(samples: ShortArray): String {
        val bytes = ByteArray(samples.size * 2)
        for (i in samples.indices) {
            val v = samples[i].toInt()
            bytes[i * 2] = (v and 0xff).toByte(); bytes[i * 2 + 1] = (v shr 8).toByte()
        }
        return Base64.getEncoder().encodeToString(bytes)
    }

    private fun open(sched: FakeScheduler, env: FakeEnv, ring: RingBuffer, args: Map<String, Any?> = emptyMap()) =
        PcmStream(sched, ring, env).command("pcm_open", args)

    // --- open refusals ----------------------------------------------------------------------------------------------

    @Test fun refusesUnlessPhoneOrUsbSource() {
        val e = FakeEnv(); e.source = "pico"
        val r = PcmStream(FakeScheduler(), RingBuffer(), e).command("pcm_open", emptyMap())
        assertEquals(false, r["ok"]); assertTrue((r["error"] as String).contains("phone/usb"))
    }

    @Test fun refusesWhenNotListening() {
        val e = FakeEnv(); e.listening = false
        val r = PcmStream(FakeScheduler(), RingBuffer(), e).command("pcm_open", emptyMap())
        assertEquals(false, r["ok"]); assertTrue((r["error"] as String).contains("not listening"))
    }

    @Test fun refusesWhenNotGestureMode() {
        val e = FakeEnv(); e.mode = "cursor"
        val r = PcmStream(FakeScheduler(), RingBuffer(), e).command("pcm_open", emptyMap())
        assertEquals(false, r["ok"]); assertTrue((r["error"] as String).contains("gesture"))
    }

    @Test fun refusesWhenRecorderCalibrationTrainingOrMeasurementOpen() {
        for ((k, v) in listOf("recording" to "a recorder session is open", "calibrating" to "a calibration is open",
                "training" to "a training round is open", "measuring" to "a measurement is open")) {
            val e = FakeEnv()
            when (k) { "recording" -> e.recording = true; "calibrating" -> e.calibrating = true; "training" -> e.training = true; "measuring" -> e.measuring = true }
            val r = PcmStream(FakeScheduler(), RingBuffer(), e).command("pcm_open", emptyMap())
            assertEquals(false, r["ok"]); assertEquals(v, r["error"])
        }
    }

    @Test fun refusesWhenAlreadyOpen() {
        val s = FakeScheduler(); val e = FakeEnv(); val ring = RingBuffer()
        ringWrite(ring, shortArrayOf(1, 2), 0, 0)
        val p = PcmStream(s, ring, e)
        assertEquals(true, p.command("pcm_open", emptyMap())["ok"])
        val r = p.command("pcm_open", emptyMap())
        assertEquals(false, r["ok"]); assertTrue((r["error"] as String).contains("already open"))
    }

    @Test fun openReportsRateGenFrameMicSource() {
        val s = FakeScheduler(); val e = FakeEnv(); val ring = RingBuffer()
        ringWrite(ring, shortArrayOf(1, 2, 3), 0, 7)
        val r = PcmStream(s, ring, e).command("pcm_open", emptyMap())
        assertEquals(true, r["ok"])
        assertEquals(RATE, r["rate"]); assertEquals(7, r["gen"]); assertEquals(3L, r["frame"])
        assertEquals("phone built-in mic", r["mic"]); assertEquals("phone", r["source"])
        assertTrue(r["sid"] is Long)
    }

    // --- read windows ------------------------------------------------------------------------------------------------

    @Test fun readReturnsRingRange() {
        val s = FakeScheduler(); val e = FakeEnv(); val ring = RingBuffer()
        val samples = shortArrayOf(1, 2, 3, 4, 5)
        ringWrite(ring, samples, 0, 0)
        val p = PcmStream(s, ring, e)
        val o = p.command("pcm_open", emptyMap())
        val sid = o["sid"] as Long
        val r = p.command("pcm_read", mapOf("sid" to sid, "from" to 0L))
        assertEquals(true, r["ok"])
        assertEquals(0L, r["from"]); assertEquals(5L, r["to"]); assertEquals(0L, r["start"]); assertEquals(5L, r["end"])
        assertEquals(0L, r["lost_frames"])
        assertEquals(b64(samples), r["b64"])
    }

    @Test fun readCapsAtTwoSeconds() {
        val s = FakeScheduler(); val e = FakeEnv(); val ring = RingBuffer()
        ringWrite(ring, ShortArray(3 * RATE), 0, 0)   // 3 s
        val p = PcmStream(s, ring, e)
        val sid = p.command("pcm_open", emptyMap())["sid"] as Long
        val r = p.command("pcm_read", mapOf("sid" to sid, "from" to 0L))
        assertEquals(true, r["ok"])
        assertEquals(0L, r["start"]); assertEquals(2L * RATE, r["to"])   // capped at 2 s
        assertEquals((2L * RATE * 2).toInt(), (r["b64"] as String).let { Base64.getDecoder().decode(it).size })
        assertEquals(0L, r["lost_frames"])
    }

    @Test fun readReportsLostFrames() {
        val s = FakeScheduler(); val e = FakeEnv(); val ring = RingBuffer()
        val n = 13 * RATE
        ringWrite(ring, ShortArray(n), 0, 0)   // 13 s: only 12 s held, ring.start = 1 s
        val p = PcmStream(s, ring, e)
        val sid = p.command("pcm_open", emptyMap())["sid"] as Long
        val r = p.command("pcm_read", mapOf("sid" to sid, "from" to 0L))
        assertEquals(true, r["ok"])
        assertEquals(RATE.toLong(), r["start"])
        assertEquals(RATE.toLong(), r["lost_frames"])
        assertEquals(RATE.toLong() + 2L * RATE, r["to"])
    }

    @Test fun unknownSidIsNoStream() {
        val s = FakeScheduler(); val e = FakeEnv(); val ring = RingBuffer()
        ringWrite(ring, shortArrayOf(1), 0, 0)
        val p = PcmStream(s, ring, e)
        assertEquals(false, p.command("pcm_read", mapOf("sid" to 99L, "from" to 0L))["ok"])
        assertEquals("no stream", p.command("pcm_read", mapOf("sid" to 99L, "from" to 0L))["error"])
        assertEquals(false, p.command("pcm_close", mapOf("sid" to 99L))["ok"])
    }

    @Test fun closeReportsFramesSent() {
        val s = FakeScheduler(); val e = FakeEnv(); val ring = RingBuffer()
        ringWrite(ring, shortArrayOf(1, 2, 3, 4), 0, 0)
        val p = PcmStream(s, ring, e)
        val sid = p.command("pcm_open", emptyMap())["sid"] as Long
        p.command("pcm_read", mapOf("sid" to sid, "from" to 0L))   // sends 4 frames
        val r = p.command("pcm_close", mapOf("sid" to sid))
        assertEquals(true, r["ok"]); assertEquals(4L, r["frames_sent"])
        assertFalse(p.isOpen)
    }

    // --- restart / idle close ---------------------------------------------------------------------------------------

    @Test fun generationChangeClosesTheStream() {
        val s = FakeScheduler(); val e = FakeEnv(); val ring = RingBuffer()
        ringWrite(ring, shortArrayOf(1, 2), 0, 0)
        val p = PcmStream(s, ring, e)
        val sid = p.command("pcm_open", emptyMap())["sid"] as Long
        ringWrite(ring, shortArrayOf(9), 100, 1)   // new generation
        val r = p.command("pcm_read", mapOf("sid" to sid, "from" to 0L))
        assertEquals(false, r["ok"]); assertEquals("capture restarted", r["error"]); assertEquals(1, r["gen"])
        assertFalse(p.isOpen)
    }

    @Test fun idleCloseFiresAfterIdleMs() {
        val s = FakeScheduler(); val e = FakeEnv(); val ring = RingBuffer()
        ringWrite(ring, shortArrayOf(1), 0, 0)
        val p = PcmStream(s, ring, e)
        p.command("pcm_open", mapOf("idle_ms" to 5000))
        assertTrue(p.isOpen)
        s.advance(4999); assertTrue(p.isOpen)
        s.advance(1); assertFalse(p.isOpen)   // idle_close fired at 5000 ms
    }

    @Test fun everyReadRenewsTheIdleTimer() {
        val s = FakeScheduler(); val e = FakeEnv(); val ring = RingBuffer()
        ringWrite(ring, shortArrayOf(1), 0, 0)
        val p = PcmStream(s, ring, e)
        val sid = p.command("pcm_open", mapOf("idle_ms" to 5000))["sid"] as Long
        s.advance(4000)
        p.command("pcm_read", mapOf("sid" to sid, "from" to 0L))   // renews
        s.advance(4000); assertTrue(p.isOpen)                       // only 4000 since the renew
        s.advance(1000); assertFalse(p.isOpen)
    }

    // --- the drop reason + the recorder refusal ---------------------------------------------------------------------

    @Test fun dropReasonWhileAStreamIsOpen() {
        assertNull(RecDrops.reason(recording = false, pcStream = false))
        assertEquals("recording", RecDrops.reason(recording = true))
        assertEquals("pc stream", RecDrops.reason(recording = false, pcStream = true))
        assertEquals("recording", RecDrops.reason(recording = true, pcStream = true))
    }

    @Test fun recorderRefusesWhileAStreamIsOpen() {
        val spec = File("../../extractor/prompts/range_v2.json").readBytes()
        class RecEnv : RecEngine.Env {
            override val rate = RATE
            override val source = "phone"
            override val micName = "phone built-in mic"
            override val capturing = true
            override val listening = true
            override val mode = "gesture"
            override val calibrating = false
            override val training = false
            override val measuring = false
            override val pcStream = true
            override val freeBytes = 1L shl 30
            override val scale: JSONObject? = null
            override val appForeground = "com.test"
            override val filesDir = Files.createTempDirectory("rec").toFile()
        }
        val r = RecEngine(FakeScheduler(), { 0L }, RingBuffer(), HeardLog(), spec, RecEnv()) {}
        assertEquals("PC stream is open", r.command("rec_start", mapOf("who" to "me"))["error"])
    }
}
