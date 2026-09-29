package ai.vox.companion.rec

import ai.vox.companion.Scheduler
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.file.Files

/** The recorder state machine (contract §5) on an injectable clock/scheduler, synthetic audio only. */
class RecEngineTest {
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

    class FakeEnv : RecEngine.Env {
        override val rate = 16000
        override var source = "phone"
        override var capturing = true
        override var listening = true
        override var mode = "gesture"
        override var calibrating = false
        override var training = false
        override var measuring = false
        override var freeBytes = 1L shl 30
        override var scale: JSONObject? = null
        override val micName = "phone built-in mic"
        override val appForeground = "com.test"
        override val filesDir = Files.createTempDirectory("rec").toFile()
    }

    private val spec = File("../../extractor/prompts/range_v2.json").readBytes()

    private fun ringWrite(r: RingBuffer, samples: ShortArray, firstFrame: Long, gen: Int) {
        val b = ByteBuffer.allocateDirect(samples.size * 2).order(ByteOrder.nativeOrder())
        for (s in samples) b.putShort(s)
        r.write(b, samples.size, firstFrame, 16000, gen)
    }

    private fun engine(sched: FakeScheduler, env: FakeEnv, ring: RingBuffer, heard: HeardLog,
                       pushes: MutableList<Map<String, Any?>>? = null): RecEngine =
        RecEngine(sched, { 0L }, ring, heard, spec, env) { pushes?.add(it) }

    private fun sine(n: Int) = ShortArray(n) { (0.5 * 32767.0 * kotlin.math.sin(2 * kotlin.math.PI * 200.0 * it / 16000)).toInt().toShort() }

    /** A session on the short plan with 1 s of pre-roll in the ring, readied on [takeId] and past GO. */
    private fun recordingOn(takeId: String, s: FakeScheduler, e: FakeEnv, ring: RingBuffer): RecEngine {
        ringWrite(ring, ShortArray(16000), 0, 0)
        val r = engine(s, e, ring, HeardLog())
        r.command("rec_start", mapOf("who" to "me", "profile" to "short"))
        r.command("rec_next", mapOf("take_id" to takeId))
        s.advance(RecEngine.READY_MS)
        assertEquals("recording", r.state)
        return r
    }

    private val bottom = "range-bottom_hz-r1"   // dist hand: no countdown

    @Test fun refusesWhenNotListening() {
        val s = FakeScheduler(); val e = FakeEnv()
        e.listening = false
        val r = engine(s, e, RingBuffer(), HeardLog())
        assertTrue((r.command("rec_start", mapOf("who" to "me"))["error"] as String).contains("not listening"))
    }

    @Test fun refusesWhenNotGestureMode() {
        val s = FakeScheduler(); val e = FakeEnv()
        e.mode = "cursor"
        val r = engine(s, e, RingBuffer(), HeardLog())
        assertTrue((r.command("rec_start", mapOf("who" to "me"))["error"] as String).contains("gesture"))
    }

    @Test fun refusesWhenCalibrationTrainingOrMeasurementOpen() {
        for ((k, v) in listOf("calibrating" to "a calibration is open", "training" to "a training round is open", "measuring" to "a measurement is open")) {
            val s = FakeScheduler(); val e = FakeEnv()
            when (k) { "calibrating" -> e.calibrating = true; "training" -> e.training = true; "measuring" -> e.measuring = true }
            val r = engine(s, e, RingBuffer(), HeardLog())
            assertEquals(v, r.command("rec_start", mapOf("who" to "me"))["error"])
        }
    }

    @Test fun refusesBadSpeakerAndLowSpace() {
        val s = FakeScheduler(); val e = FakeEnv()
        val r = engine(s, e, RingBuffer(), HeardLog())
        assertTrue((r.command("rec_start", mapOf("who" to "other", "speaker" to "self"))["error"] as String).contains("nickname"))
        val s2 = FakeScheduler(); val e2 = FakeEnv(); e2.freeBytes = 10L shl 20
        val r2 = engine(s2, e2, RingBuffer(), HeardLog())
        assertTrue((r2.command("rec_start", mapOf("who" to "me"))["error"] as String).contains("free space"))
    }

    @Test fun countdownForAcrossDistance() {
        val s = FakeScheduler(); val e = FakeEnv()
        val ring = RingBuffer()
        ringWrite(ring, ShortArray(16000), 0, 0)   // pre-roll so GO holds a full second
        val r = engine(s, e, ring, HeardLog())
        r.command("rec_start", mapOf("who" to "me", "profile" to "short"))
        r.command("rec_next", mapOf("take_id" to "contours-rise-hum-home-normal-normal-across-na-r1"))
        assertEquals("ready", r.state)
        s.advance(RecEngine.READY_MS)   // auto-go -> countdown (dist across)
        assertEquals("countdown", r.state)
        s.advance(RecEngine.COUNTDOWN_MS)
        assertEquals("recording", r.state)
    }

    @Test fun manualBackgroundWaitsForRecGo() {
        val s = FakeScheduler(); val e = FakeEnv()
        val ring = RingBuffer()
        ringWrite(ring, ShortArray(16000), 0, 0)
        val r = engine(s, e, ring, HeardLog())
        r.command("rec_start", mapOf("who" to "me", "profile" to "full"))
        r.command("rec_next", mapOf("take_id" to "backgrounds-media-30-r1"))
        assertEquals("ready", r.state)
        s.advance(RecEngine.READY_MS)   // manual: does NOT auto-go
        assertEquals("ready", r.state)
        r.command("rec_go", emptyMap())
        assertEquals("recording", r.state)
    }

    @Test fun abortReturnsToIdle() {
        val s = FakeScheduler(); val e = FakeEnv()
        val ring = RingBuffer()
        ringWrite(ring, ShortArray(16000), 0, 0)
        val r = engine(s, e, ring, HeardLog())
        r.command("rec_start", mapOf("who" to "me", "profile" to "short"))
        r.command("rec_next", emptyMap())
        assertEquals("ready", r.state)
        r.command("rec_abort", emptyMap())
        assertEquals("idle", r.state)
    }

    @Test fun captureStopAbortsOnlyTheTake() {
        val s = FakeScheduler(); val e = FakeEnv()
        val ring = RingBuffer()
        ringWrite(ring, ShortArray(16000), 0, 0)
        val r = engine(s, e, ring, HeardLog())
        r.command("rec_start", mapOf("who" to "me", "profile" to "short"))
        r.command("rec_next", emptyMap())
        s.advance(RecEngine.READY_MS)
        assertEquals("recording", r.state)
        r.onCaptureState("stopped", 0)
        assertEquals("error", r.state)
        assertTrue(r.recording)   // session stays open
    }

    @Test fun idleTenMinutesCloses() {
        val s = FakeScheduler(); val e = FakeEnv()
        val r = engine(s, e, RingBuffer(), HeardLog())
        r.command("rec_start", mapOf("who" to "me", "profile" to "short"))
        assertTrue(r.recording)
        s.advance(RecEngine.IDLE_CLOSE_MS)
        assertFalse(r.recording)
    }

    @Test fun takeSavesThenAutoNext() {
        val s = FakeScheduler(); val e = FakeEnv()
        val ring = RingBuffer()
        ringWrite(ring, ShortArray(16000), 0, 0)   // 1 s pre-roll
        val r = engine(s, e, ring, HeardLog())
        r.command("rec_start", mapOf("who" to "me", "profile" to "short"))
        r.command("rec_next", emptyMap())   // range-bottom_hz-r1, dist hand (no countdown)
        s.advance(RecEngine.READY_MS)   // auto-go -> recording
        assertEquals("recording", r.state)
        // a loud 0.5 s burst then 2 s of silence so the detector ends on silence
        val burst = ShortArray(8000) { (0.5 * 32767.0 * kotlin.math.sin(2 * kotlin.math.PI * 200.0 * it / 16000)).toInt().toShort() }
        ringWrite(ring, burst, 16000, 0)
        ringWrite(ring, ShortArray(16000 * 2), 24000, 0)
        s.advance(RecEngine.TICK_MS)   // one tick reads the whole ring and finalises
        assertEquals("saved", r.state)
        s.advance(RecEngine.SAVED_HOLD_MS)
        assertEquals("ready", r.state)   // auto-next advanced to the next take
    }

    @Test fun statusCarriesTheOrderedPlanExceptInLevelPushes() {
        val s = FakeScheduler(); val e = FakeEnv()
        val pushes = ArrayList<Map<String, Any?>>()
        val r = engine(s, e, RingBuffer(), HeardLog(), pushes)
        org.junit.Assert.assertNull(r.command("rec_status", emptyMap())["plan"])   // no session: no plan
        r.command("rec_start", mapOf("who" to "me", "profile" to "short"))
        @Suppress("UNCHECKED_CAST")
        val plan = r.command("rec_status", emptyMap())["plan"] as List<Map<String, Any?>>
        val expected = RangePlan.parse(spec, "short").takes   // tied to range_layout by the plan-fixture test
        assertEquals(expected.map { it.takeId }, plan.map { it["take_id"] })
        assertEquals(expected.map { it.block }, plan.map { it["block"] })
        assertEquals(42, plan.size)
        assertEquals(bottom, plan.first()["take_id"])
        assertTrue(pushes.last().containsKey("plan"))   // the start push carries it
        // a rec_next by take_id from the plan (what the header arrows send) lands on that take
        val third = plan[2]["take_id"] as String
        @Suppress("UNCHECKED_CAST")
        assertEquals(third, (r.command("rec_next", mapOf("take_id" to third))["take"] as Map<String, Any?>)["take_id"])
        pushes.clear(); r.pushIfActive()
        assertFalse(pushes.single().containsKey("plan"))   // the 10 Hz level push stays small
    }

    @Test fun idleCloseIsMovedByEveryCommand() {
        val s = FakeScheduler(); val e = FakeEnv()
        val r = engine(s, e, RingBuffer(), HeardLog())
        r.command("rec_start", mapOf("who" to "me", "profile" to "short"))
        s.advance(RecEngine.IDLE_CLOSE_MS / 2)
        r.command("rec_status", emptyMap())
        s.advance(RecEngine.IDLE_CLOSE_MS / 2)
        assertTrue(r.recording)   // only 5 min since the last command
        s.advance(RecEngine.IDLE_CLOSE_MS / 2)
        assertFalse(r.recording)
    }

    @Test fun goWaitsForAFullSecondOfPreRoll() {
        val s = FakeScheduler(); val e = FakeEnv()
        val ring = RingBuffer()
        ringWrite(ring, ShortArray(8000), 0, 0)   // only 0.5 s since the capture started
        val r = engine(s, e, ring, HeardLog())
        r.command("rec_start", mapOf("who" to "me", "profile" to "short"))
        r.command("rec_next", mapOf("take_id" to bottom))
        s.advance(RecEngine.READY_MS)
        assertEquals("ready", r.state)            // GO waits, nothing is buffered
        ringWrite(ring, ShortArray(8000), 8000, 0)
        s.advance(RecEngine.TICK_MS)
        assertEquals("recording", r.state)
    }

    @Test fun aRestartOrAGapDuringATakeAbortsItInsteadOfSplicing() {
        for (restart in listOf(true, false)) {
            val s = FakeScheduler(); val e = FakeEnv(); val ring = RingBuffer()
            val r = recordingOn(bottom, s, e, ring)
            if (restart) ringWrite(ring, sine(8000), 0, 1)          // a new capture generation
            else ringWrite(ring, sine(8000), 16000 + 4000, 0)       // same generation, 4000 frames missing
            s.advance(RecEngine.TICK_MS)
            assertEquals("error", r.state)
            assertTrue(r.recording)
            assertEquals(0, File(e.filesDir, "range").walkTopDown().count { it.name.endsWith(".wav") })
        }
    }

    @Test fun anOldCapturesLateStoppedDoesNotAbortTheTake() {
        val s = FakeScheduler(); val e = FakeEnv(); val ring = RingBuffer()
        val r = recordingOn(bottom, s, e, ring)
        r.onCaptureState("stopped", -1)   // the previous generation's late state
        assertEquals("recording", r.state)
        r.onCaptureState("stopped", 0)
        assertEquals("error", r.state)
    }

    @Test fun aMissedTakeIsKeptAndTryAgainNeverOverwritesIt() {
        val s = FakeScheduler(); val e = FakeEnv(); val ring = RingBuffer()
        val r = recordingOn(bottom, s, e, ring)
        ringWrite(ring, ShortArray(16000 * 5), 16000, 0)   // 5 s of silence: "no sound" at 4 s
        s.advance(RecEngine.TICK_MS)
        assertEquals("no_sound", r.state)
        s.advance(RecEngine.SAVED_HOLD_MS)
        assertEquals("no_sound", r.state)                  // waits for Try again / Skip
        val dir = File(e.filesDir, "range").listFiles()!!.single()
        val missed = File(dir, "takes/range/$bottom.a0.wav")
        assertTrue(missed.exists())
        val before = missed.readBytes()
        // Try again: heard this time
        r.command("rec_next", mapOf("take_id" to bottom))
        s.advance(RecEngine.READY_MS)
        val go = 16000L * 6
        ringWrite(ring, sine(8000), go, 0)
        ringWrite(ring, ShortArray(16000 * 2), go + 8000, 0)
        s.advance(RecEngine.TICK_MS)
        assertEquals("saved", r.state)
        assertTrue(missed.readBytes().contentEquals(before))
        assertTrue(File(dir, "takes/range/$bottom.wav").exists())
        val rows = File(dir, "labels.jsonl").readLines().map { JSONObject(it) }
        assertEquals(listOf(true, false), rows.map { it.optBoolean("no_sound") })
        assertEquals(0, rows[0].getInt("attempt"))
        assertEquals(listOf(0, 1), rows.map { it.getInt("redo") })
    }

    @Test fun aSettledUnratedBlockAsksForARating() {
        val s = FakeScheduler(); val e = FakeEnv(); val ring = RingBuffer()
        ringWrite(ring, ShortArray(16000), 0, 0)
        val r = engine(s, e, ring, HeardLog())
        r.command("rec_start", mapOf("who" to "me", "profile" to "short"))
        r.command("rec_next", mapOf("take_id" to "room-room-r1"))
        r.command("rec_skip", emptyMap())
        assertEquals("rate", r.state)   // the room block has one take
        assertTrue(r.command("rec_rate", mapOf("block" to "nope", "rating" to 3))["error"] != null)
        r.command("rec_rate", mapOf("block" to "room", "rating" to 3, "note" to ""))
        assertEquals("idle", r.state)
        val row = JSONObject(File(File(e.filesDir, "range").listFiles()!!.single(), "ratings.jsonl").readLines().single())
        assertEquals(0, row.getInt("redos"))
        assertTrue(row.getDouble("seconds") >= 0.0)
    }

    @Test fun aSkippedBackgroundIsNotOfferedAgain() {
        val s = FakeScheduler(); val e = FakeEnv(); val ring = RingBuffer()
        ringWrite(ring, ShortArray(16000), 0, 0)
        val r = engine(s, e, ring, HeardLog())
        r.command("rec_start", mapOf("who" to "me", "profile" to "full"))
        val first = "backgrounds-media-30-r1"
        r.command("rec_next", mapOf("take_id" to first))
        val st = r.command("rec_skip", emptyMap())
        assertTrue(((st["take"] as Map<*, *>?)?.get("take_id")) != first)
    }

    @Test fun startPushesAndNamesTheSessionLikeRangeLayout() {
        val s = FakeScheduler(); val e = FakeEnv(); val pushes = mutableListOf<Map<String, Any?>>()
        val r = engine(s, e, RingBuffer(), HeardLog(), pushes)
        val st = r.command("rec_start", mapOf("who" to "other", "speaker" to "sis", "profile" to "short"))
        assertTrue((st["name"] as String).matches(Regex("range-sis-[0-9]{8}-[0-9]{6}")))
        assertEquals(true, pushes.last()["active"])   // the UI (and the sound drop) see the open session at once
        assertTrue(r.sessionBase("self", 0L).matches(Regex("range-[0-9]{8}-[0-9]{6}")))
    }

    @Test fun clearDeletesOnlyNamedSessionsAndQuickrecIds() {
        val s = FakeScheduler(); val e = FakeEnv()
        val r = engine(s, e, RingBuffer(), HeardLog())
        File(e.filesDir, "range/range-a").mkdirs(); File(e.filesDir, "range/range-b").mkdirs()
        File(e.filesDir, "quickrec/111").mkdirs(); File(e.filesDir, "quickrec/222").mkdirs()
        assertTrue(r.command("rec_clear", mapOf("sessions" to listOf("../range")))["error"] != null)
        assertTrue(File(e.filesDir, "range/range-a").exists())
        val out = r.command("rec_clear", mapOf("sessions" to listOf("range-a"), "quickrec" to "all"))
        assertEquals(mapOf("sessions" to listOf("range-a"), "pc_sessions" to emptyList<String>(), "quickrec" to listOf("111", "222")),
            (out["deleted"] as Map<*, *>).mapValues { (_, v) -> (v as List<*>).sortedBy { it.toString() } })
        assertTrue(File(e.filesDir, "range/range-b").exists())
    }

    @Test fun livePitchTraceInStatus() {
        val s = FakeScheduler(); val e = FakeEnv()
        val ring = RingBuffer()
        ringWrite(ring, ShortArray(16000), 0, 0)
        val r = engine(s, e, ring, HeardLog())
        r.command("rec_start", mapOf("who" to "me", "profile" to "short"))
        r.command("rec_next", mapOf("take_id" to "range-bottom_hz-r1"))   // hum tone
        s.advance(RecEngine.READY_MS)
        assertEquals("recording", r.state)
        r.onTick(200.0, -40.0); r.onTick(null, -45.0); r.onTick(220.0, -38.0)
        @Suppress("UNCHECKED_CAST")
        val live = r.command("rec_status", emptyMap())["live"] as Map<String, Any?>
        assertEquals(20L, live["tick_ms"])
        assertEquals(listOf(200.0, null, 220.0), live["trace_hz"])
    }

    @Test fun openRefusesDifferentSpecVersion() {
        val s = FakeScheduler(); val e = FakeEnv()
        val r = engine(s, e, RingBuffer(), HeardLog())
        r.command("rec_start", mapOf("who" to "me", "profile" to "short"))
        val name = r.openName!!
        r.command("rec_close", emptyMap())
        // rewrite the session to look like a range_v1 session
        val dir = File(e.filesDir, "range/$name")
        File(dir, "spec.json").writeBytes(File("../../extractor/prompts/range_v1.json").readBytes())
        val metaFile = File(dir, "session.json")
        val meta = JSONObject(metaFile.readText()); meta.put("spec", "range_v1")
        metaFile.writeText(meta.toString(2) + "\n")
        val out = r.command("rec_open", mapOf("name" to name))
        assertEquals("This session was recorded with range_v1; the app records range_v2. Start a new session.", out["error"])
    }

    @Test fun pcOriginDeleteRestorePurgeRefused() {
        val s = FakeScheduler(); val e = FakeEnv()
        val r = engine(s, e, RingBuffer(), HeardLog())
        val msg = "PC sessions are read-only here; delete on the PC and push again"
        assertEquals(msg, r.command("rec_delete", mapOf("origin" to "pc", "name" to "x", "take_id" to "t", "scope" to "take"))["error"])
        assertEquals(msg, r.command("rec_restore", mapOf("origin" to "pc", "name" to "x", "del_id" to "d"))["error"])
        assertEquals(msg, r.command("rec_trash_clear", mapOf("origin" to "pc", "name" to "x"))["error"])
    }

    @Test fun recClearDeletesPushedPcSessions() {
        val s = FakeScheduler(); val e = FakeEnv()
        val r = engine(s, e, RingBuffer(), HeardLog())
        File(e.filesDir, "range_pc/range-a").mkdirs()
        File(e.filesDir, "range_pc/range-b").mkdirs()
        val out = r.command("rec_clear", mapOf("pc_sessions" to listOf("range-a")))
        assertEquals(mapOf("sessions" to emptyList<Any>(), "pc_sessions" to listOf("range-a"), "quickrec" to emptyList<Any>()),
            out["deleted"])
        assertTrue(!File(e.filesDir, "range_pc/range-a").exists())
        assertTrue(File(e.filesDir, "range_pc/range-b").exists())
    }
}
