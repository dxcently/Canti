package ai.vox.companion

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.file.Files
import kotlin.math.ln

/** Gesture training (GestureTraining.kt): the plan, the per-take judge, the session, and the per-source store. */
class GestureTrainingTest {

    // --- fixtures ------------------------------------------------------------------------------------------------------

    private fun fp(f0Hz: Double?, dim: Int = 24) = DoubleArray(dim) { i -> if (i == 0) (if (f0Hz == null) -3.0 else ln(f0Hz / 100) / ln(2.0)) else 0.1 * i }
    private val rising = DoubleArray(16) { it * 0.4 }                          // 0..6 st (rise)
    private val falling = DoubleArray(16) { (15 - it) * 0.4 }                  // 6..0 st (fall)
    private val arching = DoubleArray(16) { i -> if (i < 8) i * 0.5 else (15 - i) * 0.5 }   // up then down
    private val dipping = DoubleArray(16) { i -> if (i < 8) -i * 0.5 else -(15 - i) * 0.5 }  // down then up
    private val flatTrack = DoubleArray(16) { 0.0 }
    private fun pitchFor(label: String): DoubleArray = when (label) {
        "rise" -> rising; "fall" -> falling; "arch" -> arching; "dip" -> dipping; "flat" -> flatTrack
        else -> DoubleArray(0)
    }
    private fun feats(f0Hz: Double?, pitch: DoubleArray = rising) = SoundFeatures(fp(f0Hz), "fp1", pitch)
    private fun line(label: String, like: String = "hum") = when (label) {
        in TrainPlan.CONTOURS -> "hum that ${Vocab.CONTOURS[label]}; pitch change large (over 4 semitones); duration medium (400-1000 ms); tone clear tone; loudness normal; sounds like $like"
        else -> "${Vocab.DISCRETE[label] ?: "unknown"}; instant sound; loudness normal; sounds like mouth sound"
    }

    private fun heard(label: String, f0: Double? = 200.0, dur: Long? = 500, pitch: DoubleArray? = null, n: Int = 1) =
        TrainHeard(List(n) { label }, List(n) { line(label) }, dur, feats(f0, if (label in TrainPlan.CONTOURS) pitch ?: pitchFor(label) else DoubleArray(0)))

    private fun msg(label: String, f0: Double? = 200.0, dur: Long = 500, features: SoundFeatures? = feats(f0, if (label in TrainPlan.CONTOURS) pitchFor(label) else DoubleArray(0))) =
        FeatureMessage(id = 1, mode = "gesture", armed = true, sounds = listOf(line(label)), sequence = listOf(label), phrase = null,
            timing = listOf(Stamp(1000, 1000 + dur)), features = listOf(features))

    private class FakeHost : TrainHost {
        var t = 0L
        val tasks = mutableListOf<Pair<Long, () -> Unit>>()
        var src = "phone"
        var block: String? = null
        var drop: String? = null
        var ticksOn = false
        val stores = mutableMapOf<String, EnrollmentStore>()
        val trashes = mutableMapOf<String, JSONArray>()
        val logs = mutableListOf<Map<String, Any?>>()
        val pushes = mutableListOf<Map<String, Any?>>()
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
        override fun source() = src
        override fun blocker() = block
        override fun dropSummary(sinceMs: Long) = drop
        override fun liveTrace() = src != "pico"
        override fun ticks(on: Boolean) { ticksOn = on }
        override fun profile() = "default"
        val scales = mutableMapOf<String, ShapeGrade.Scale?>()
        override fun scale(tone: String) = scales[tone]
        var wall = 1_790_000_000_000L
        override fun wallMs() = ++wall
        override fun store(source: String) = stores.getOrPut(source) { EnrollmentStore("default", source) }
        override fun change(source: String, what: String, change: (EnrollmentStore) -> Unit) = change(store(source))
        override fun trash(source: String) = trashes[source]
        override fun saveTrash(source: String, entries: JSONArray?) { if (entries == null) trashes.remove(source) else trashes[source] = entries }
        override fun log(vararg fields: Pair<String, Any?>) { logs += fields.toMap() }
        override fun push(status: Map<String, Any?>) { pushes += status }
    }

    @Suppress("UNCHECKED_CAST")
    private fun session(st: Map<String, Any?>) = st["session"] as Map<String, Any?>

    // --- plan ----------------------------------------------------------------------------------------------------------

    @Test fun planHasEightCellsPerContourFourPerDiscrete() {
        for (g in TrainPlan.CONTOURS) assertEquals(g, 8, TrainPlan.cells(g).size)
        for (g in TrainPlan.DISCRETE) assertEquals(g, 4, TrainPlan.cells(g).size)
        assertEquals(48, TrainPlan.TOTAL)
        assertFalse("pop is folded into click", "pop" in TrainPlan.GESTURES)
        assertEquals(listOf("soft-1", "soft-2", "loud-1", "loud-2"), TrainPlan.cells("click").map { it.id })
        for (g in TrainPlan.GESTURES) assertTrue("under the class cap", TrainPlan.cells(g).size <= EnrollmentStore.MAX_EXAMPLES)
        assertEquals("Whistle a QUICK rise, starting LOW", TrainPlan.cell("rise", "whistle-low-quick").prompt)
        assertEquals("Hum a SLOW arch, starting HIGH", TrainPlan.cell("arch", "hum-high-slow").prompt)
        assertEquals(mapOf("tone" to "hum", "pitch" to "low", "length" to "long"), TrainPlan.cell("flat", "hum-low-long").tags)
        assertEquals("Hum a LONG flat note, LOW", TrainPlan.cell("flat", "hum-low-long").prompt)
        assertEquals(mapOf("loudness" to "loud", "take" to "2"), TrainPlan.cell("click", "loud-2").tags)
        assertEquals("Click your tongue LOUDLY (2 of 2)", TrainPlan.cell("click", "loud-2").prompt)
        // every cell is distinct
        for (g in TrainPlan.GESTURES) assertEquals(TrainPlan.cells(g).size, TrainPlan.cells(g).map { it.id }.toSet().size)
    }

    // --- judge ---------------------------------------------------------------------------------------------------------

    @Test fun judgeAcceptsTheRightShapeToneAndSpeed() {
        val v = TrainJudge.judge(TrainPlan.cell("rise", "hum-low-quick"), heard("rise", 180.0, 500))
        assertTrue(v.reason, v.ok)
        assertEquals("hum", v.heard["tone"]); assertEquals(180, v.heard["f0_hz"])
        assertEquals(TrainJudge.startHz(feats(180.0))!!.toInt(), v.heard["start_hz"])
        assertTrue(TrainJudge.judge(TrainPlan.cell("rise", "whistle-high-slow"), heard("rise", 1200.0, 1500)).ok)
        assertTrue(TrainJudge.judge(TrainPlan.cell("click", "soft-1"), heard("click", null, 40)).ok)
    }

    @Test fun judgeExplainsAWrongShapeAndOffersKeepAnyway() {
        val v = TrainJudge.judge(TrainPlan.cell("arch", "hum-low-slow"), heard("dip", 200.0, 1400))
        assertFalse(v.ok)
        assertEquals("Heard a dip (down then up): an arch goes up then down.", v.reason)
        assertTrue("a wrong label alone can be kept", v.canKeep)
        val d = TrainJudge.judge(TrainPlan.cell("click", "loud-1"), heard("hiss", null, 30))
        assertEquals("Heard a hiss: a click is a tongue click.", d.reason); assertTrue(d.canKeep)
        // a contour class needs the pitch track: a click cannot be kept as a rise
        val p = TrainJudge.judge(TrainPlan.cell("rise", "hum-low-quick"), heard("click", null, 30))
        assertFalse(p.canKeep)
        val u = TrainJudge.judge(TrainPlan.cell("rise", "hum-low-quick"), heard("unknown", 200.0, 500))
        assertTrue(u.reason, u.reason.startsWith("Canti did not count that as a gesture"))
    }

    @Test fun judgeChecksToneByF0BandAndSpeed() {
        val w = TrainJudge.judge(TrainPlan.cell("rise", "whistle-low-quick"), heard("rise", 220.0, 500))
        assertEquals(listOf("tone"), w.reasons.map { it.first })
        assertTrue(w.reason, w.reason.contains("Heard a hum (about 220 Hz)") && w.reason.contains("600 Hz"))
        assertFalse("only a wrong label can be kept", w.canKeep)
        val h = TrainJudge.judge(TrainPlan.cell("fall", "hum-high-slow"), heard("fall", 900.0, 1500))
        assertTrue(h.reason, h.reason.startsWith("Heard a whistle (about 900 Hz)"))
        val q = TrainJudge.judge(TrainPlan.cell("dip", "hum-low-quick"), heard("dip", 200.0, 1500))
        assertEquals("It took 1.5 s: a QUICK dip takes about half a second (at most 1.0 s).", q.reason)
        val s = TrainJudge.judge(TrainPlan.cell("flat", "hum-low-long"), heard("flat", 200.0, 500))
        assertEquals("It took 0.5 s: a LONG flat note takes about 1.5 s (at least 0.8 s).", s.reason)
        // no f0 in the fingerprint: the line's `sounds like` decides
        assertEquals("whistle", TrainJudge.tone(SoundFeatures(DoubleArray(3), "fp9", rising), line("rise", "whistle")))
    }

    @Test fun judgeRefusesTwoSoundsAndMissingFingerprints() {
        val two = TrainJudge.judge(TrainPlan.cell("arch", "hum-low-slow"),
            TrainHeard(listOf("rise", "fall"), listOf(line("rise"), line("fall")), 600, feats(200.0)))
        assertEquals("Heard 2 sounds (rise then fall): make it one unbroken sound.", two.reason); assertFalse(two.canKeep)
        val none = TrainJudge.judge(TrainPlan.cell("click", "soft-1"), TrainHeard(listOf("click"), listOf(line("click")), 30, null))
        assertEquals(listOf("features"), none.reasons.map { it.first }); assertFalse(none.canKeep)
    }

    // --- session -------------------------------------------------------------------------------------------------------

    @Test fun aPassingTakeIsStoredWithItsCellTags() {
        val h = FakeHost(); val t = GestureTrainer(h)
        var st = t.command("train_start", mapOf("gesture" to "rise"))
        assertNull(st["error"]); assertEquals("ready", session(st)["state"]); assertEquals("hum-low-slow", session(st)["cell"])
        assertEquals("Hum a SLOW rise, starting LOW", session(st)["prompt"]); assertTrue(h.ticksOn)
        st = t.command("train_record", emptyMap()); assertEquals("recording", session(st)["state"])
        t.onTick(180.0, -30.0); t.onTick(null, -50.0)
        @Suppress("UNCHECKED_CAST")
        assertEquals(listOf(180.0, null), (session(t.status(null))["live"] as Map<String, Any?>)["trace_hz"])
        assertTrue(t.onSounds(msg("rise", 180.0, 1400)))
        assertEquals("recording", session(t.status(null))["state"])   // settling: a second sound may follow
        h.advance(GestureTrainer.SETTLE_MS)
        st = t.status(null)
        assertEquals("passed", session(st)["state"])
        val c = h.store("phone").find("rise")!!
        assertEquals(EnrollmentStore.GESTURE, c.kind); assertEquals(1, c.examples.size)
        val meta = c.examples[0].meta!!
        assertEquals("hum-low-slow", meta.getString("cell")); assertEquals("hum", meta.getString("tone"))
        assertEquals("low", meta.getString("pitch")); assertEquals("slow", meta.getString("speed"))
        assertEquals("rise", meta.getJSONObject("heard").getString("label")); assertEquals(1400, meta.getJSONObject("heard").getInt("dur_ms"))
        @Suppress("UNCHECKED_CAST")
        val rise = (st["gestures"] as List<Map<String, Any?>>).first { it["name"] == "rise" }
        assertEquals(1, rise["done"]); assertEquals(8, rise["total"])
        assertEquals(1, st["done"]); assertEquals(48, st["total"])
        // NEXT records the next missing cell at once
        st = t.command("train_next", emptyMap())
        assertEquals("recording", session(st)["state"]); assertEquals("hum-low-quick", session(st)["cell"])
    }

    @Test fun aFailedTakeStopsAndWaitsForRetrySkipOrKeep() {
        val h = FakeHost(); val t = GestureTrainer(h)
        t.command("train_start", mapOf("gesture" to "arch")); t.command("train_record", emptyMap())
        t.onSounds(msg("dip", 200.0, 1400)); h.advance(GestureTrainer.SETTLE_MS)
        var s = session(t.status(null))
        assertEquals("failed", s["state"]); assertEquals(true, s["can_keep"])
        assertEquals("Heard a dip (down then up): an arch goes up then down.", s["reason"])
        // it waits: time passes, nothing is recorded again or skipped
        h.advance(60_000); assertEquals("failed", session(t.status(null))["state"]); assertNull(h.store("phone").find("arch"))
        // RETRY records the same cell again
        s = session(t.command("train_retry", emptyMap())); assertEquals("recording", s["state"]); assertEquals("hum-low-slow", s["cell"])
        t.onSounds(msg("dip", 200.0, 1400)); h.advance(GestureTrainer.SETTLE_MS)
        // KEEP ANYWAY stores it into the prompted class, marked and logged
        s = session(t.command("train_keep", emptyMap())); assertEquals("passed", s["state"])
        val ex = h.store("phone").find("arch")!!.examples.single()
        assertTrue(ex.meta!!.getBoolean("kept")); assertEquals("dip", ex.meta!!.getJSONObject("heard").getString("label"))
        assertTrue(h.logs.any { it["event"] == "keep" && it["heard"] == "dip" && it["cell"] == "hum-low-slow" })
        // a take that fails on tone cannot be kept, only retried or skipped
        t.command("train_next", emptyMap())
        t.onSounds(msg("arch", 900.0, 500)); h.advance(GestureTrainer.SETTLE_MS)
        s = session(t.status(null)); assertEquals("failed", s["state"]); assertEquals(false, s["can_keep"])
        val refused = t.command("train_keep", emptyMap()); assertNotNull(refused["error"])
        s = session(t.command("train_skip", emptyMap()))
        assertEquals("ready", s["state"]); assertEquals(listOf("hum-low-quick"), s["skipped"]); assertEquals("hum-high-slow", s["cell"])
    }

    @Test fun silenceTimesOutWithAReasonAndABlockerFailsAtOnce() {
        val h = FakeHost(); val t = GestureTrainer(h)
        t.command("train_start", mapOf("gesture" to "click")); t.command("train_record", emptyMap())
        h.advance(GestureTrainer.TAKE_TIMEOUT_MS)
        val s = session(t.status(null)); assertEquals("failed", s["state"]); assertEquals("Heard nothing in 8 s.", s["reason"])
        h.block = "Canti is in cursor mode: switch to gesture mode to train gestures."
        val r = session(t.command("train_retry", emptyMap()))
        assertEquals("failed", r["state"]); assertEquals(h.block, r["reason"])
    }

    @Test fun heardButDroppedSoundsReportTheDropReasonInsteadOfSilence() {
        val h = FakeHost(); val t = GestureTrainer(h)
        t.command("train_start", mapOf("gesture" to "click")); t.command("train_record", emptyMap())
        // The mic heard sounds but dropped them (level gate, touch, a calibration): the timeout says so.
        h.drop = "Heard 3 sounds, all below the level gate"
        h.advance(GestureTrainer.TAKE_TIMEOUT_MS)
        val s = session(t.status(null))
        assertEquals("failed", s["state"]); assertEquals("Heard 3 sounds, all below the level gate", s["reason"])
    }

    @Test fun twoSoundsInOneTakeFail() {
        val h = FakeHost(); val t = GestureTrainer(h)
        t.command("train_start", mapOf("gesture" to "arch")); t.command("train_record", emptyMap())
        t.onSounds(msg("rise")); h.advance(300); t.onSounds(msg("fall")); h.advance(GestureTrainer.SETTLE_MS)
        assertEquals("Heard 2 sounds (rise then fall): make it one unbroken sound.", session(t.status(null))["reason"])
    }

    @Test fun soundsOutsideARecordingAreSwallowedAndTheCardResumes() {
        val h = FakeHost(); val t = GestureTrainer(h)
        assertFalse("no session: sounds act as usual", t.onSounds(msg("click")))
        t.command("train_start", mapOf("gesture" to "click"))
        assertTrue("session open, not recording: dropped", t.onSounds(msg("click")))
        assertNull(h.store("phone").find("click"))
        // record two cells, stop, and start again: only the missing ones are asked for
        for (i in 0 until 2) { t.command(if (i == 0) "train_record" else "train_next", emptyMap()); t.onSounds(msg("click", null, 40)); h.advance(GestureTrainer.SETTLE_MS) }
        t.command("train_cancel", emptyMap()); assertFalse(t.active); assertFalse(h.ticksOn)
        val s = session(t.command("train_start", mapOf("gesture" to "click")))
        assertEquals("loud-1", s["cell"]); assertEquals(2, s["count"])
        // a finished card refuses a new round until Delete / redo
        for (i in 0 until 2) { t.command(if (i == 0) "train_record" else "train_next", emptyMap()); t.onSounds(msg("click", null, 40)); h.advance(GestureTrainer.SETTLE_MS) }
        assertEquals("passed", session(t.status(null))["state"])
        assertEquals("done", session(t.command("train_next", emptyMap()))["state"])
        t.command("train_cancel", emptyMap())
        assertTrue((t.command("train_start", mapOf("gesture" to "click"))["error"] as String).contains("Delete / redo"))
        // redo one cell: it replaces its example
        t.command("train_start", mapOf("gesture" to "click", "cell" to "soft-2")); t.command("train_record", emptyMap())
        t.onSounds(msg("click", null, 40)); h.advance(GestureTrainer.SETTLE_MS)
        assertEquals(4, h.store("phone").find("click")!!.examples.size)
        t.command("train_cancel", emptyMap())
        // Delete / redo: one cell, then the card
        t.command("train_delete", mapOf("gesture" to "click", "cell" to "loud-1"))
        assertEquals(3, h.store("phone").find("click")!!.examples.size)
        t.command("train_delete", mapOf("gesture" to "click"))
        assertNull(h.store("phone").find("click"))
    }

    @Test fun trainingIsPerSource() {
        val h = FakeHost(); val t = GestureTrainer(h)
        val e = t.command("train_start", mapOf("gesture" to "rise", "source" to "usb"))["error"] as String
        assertTrue(e, e.contains("switch to the USB mic"))
        t.command("train_start", mapOf("gesture" to "hiss")); t.command("train_record", emptyMap())
        t.onSounds(msg("hiss", null, 400)); h.advance(GestureTrainer.SETTLE_MS)
        t.command("train_cancel", emptyMap())
        @Suppress("UNCHECKED_CAST")
        val src = t.status(null)["sources"] as Map<String, Map<String, Int>>
        assertEquals(1, src.getValue("phone")["done"]); assertEquals(0, src.getValue("usb")["done"]); assertEquals(0, src.getValue("pico")["done"])
        assertEquals(0, t.status("usb")["done"])
    }

    @Test fun roomInTheClassIsCheckedBeforeARound() {
        val h = FakeHost(); val t = GestureTrainer(h)
        h.store("phone").add("gesture", "rise", List(5) { feats(200.0) })   // enrolled from the PC, no cells
        val e = t.command("train_start", mapOf("gesture" to "rise"))["error"] as String
        assertTrue(e, e.contains("already holds 5 examples (5 not from training)"))
        @Suppress("UNCHECKED_CAST")
        val rise = (t.status(null)["gestures"] as List<Map<String, Any?>>).first { it["name"] == "rise" }
        assertEquals(5, rise["extra"]); assertEquals(0, rise["done"])
    }

    @Test fun anIdleSessionCloses() {
        val h = FakeHost(); val t = GestureTrainer(h)
        t.command("train_start", mapOf("gesture" to "click"))
        h.advance(GestureTrainer.IDLE_MS)
        assertFalse(t.active)
        assertTrue(h.logs.any { it["event"] == "end" && it["by"] == "idle" })
        // the screen (if still there) hears that the session ended
        assertEquals(false, h.pushes.last()["active"])
    }

    @Test fun aCancelFromOutsideTheScreenIsPushedToIt() {
        val h = FakeHost(); val t = GestureTrainer(h)
        t.command("train_start", mapOf("gesture" to "click"))
        val n = h.pushes.size
        t.cancel("app background")
        assertFalse(t.active)
        assertEquals(n + 1, h.pushes.size); assertEquals(false, h.pushes.last()["active"])
        assertTrue(h.logs.any { it["event"] == "end" && it["by"] == "app background" })
        t.cancel("app background")   // nothing open: nothing logged or pushed
        assertEquals(n + 1, h.pushes.size)
    }

    // --- the "Not ready" blocker and its one button (TrainBlock) ------------------------------------------------------------

    private fun block(calibrating: Boolean = false, paused: Boolean = false, armed: Boolean = true, usesMic: Boolean = true,
                      cursor: Boolean = false, mic: String? = "listening", ready: Boolean = false) =
        TrainBlock.of(TrainBlock.Inputs(calibrating, paused, armed, usesMic, cursor, mic, ready))

    @Test fun trainBlockStatesTheCauseAndTheButtonThatFixesIt() {
        assertNull(block())
        assertNull(block(usesMic = false, mic = null, ready = true))
        assertEquals("Canti is calibrating." to null, block(calibrating = true, paused = true))   // calibrating wins, no button
        assertEquals("Canti is paused." to "resume", block(paused = true))
        // a disarmed phone / USB mic is Canti paused (resume re-arms); a disarmed Pico: resume only while it is connected
        assertEquals("Canti is paused." to "resume", block(armed = false))
        assertEquals("Canti is not listening (the device is paused or asleep)." to "resume", block(armed = false, usesMic = false, ready = true))
        assertEquals(null, block(armed = false, usesMic = false, ready = false)!!.second)
        assertEquals("gesture_mode", block(cursor = true)!!.second)
        // armed, not paused, mic off (permission, no USB mic, a refused service): resuming changes nothing, so no button
        assertEquals("The mic is off (needs microphone permission)." to null, block(mic = "needs microphone permission"))
        assertEquals("The mic is off (off)." to null, block(mic = null))
        assertEquals("The Canti device is not connected." to null, block(usesMic = false, mic = null, ready = false))
    }

    @Test fun micDropsSayWhatHappenedToTheSounds() {
        assertNull(ai.vox.companion.audio.MicDrops.line(emptyList()))
        assertEquals("Heard 3 sounds, all below the level gate.", ai.vox.companion.audio.MicDrops.line(List(3) { "below level gate" }))
        assertEquals("Heard 1 sound, dropped while a calibration ran.", ai.vox.companion.audio.MicDrops.line(listOf("calibrating")))
        assertEquals("Heard 2 sounds, all while you touched the screen.", ai.vox.companion.audio.MicDrops.line(listOf("touch", "touch")))
        // mixed reasons are each counted, not collapsed into "all <the most frequent>"
        assertEquals("Heard 3 sounds, none used: 2 below the level gate, 1 while you touched the screen.",
            ai.vox.companion.audio.MicDrops.line(listOf("below level gate", "touch", "below level gate")))
        assertEquals("Heard 1 sound, dropped by the dry run.", ai.vox.companion.audio.MicDrops.line(listOf("dry_run")))
    }

    // --- per-source store ------------------------------------------------------------------------------------------------

    @Test fun storeIsPerSourceAndTheOldFileIsMigratedOnce() {
        val dir = Files.createTempDirectory("enroll").toFile()
        try {
            val old = EnrollmentStore("default").apply { add("custom", "meow", List(3) { feats(300.0, DoubleArray(0)) }) }
            EnrollmentStore.save(dir, old)
            assertTrue(File(dir, "enroll/default.json").exists())
            val moved = mutableListOf<String>()
            val phone = EnrollmentStore.load(dir, "default", "phone") { a, b -> moved += "${a.name}->${b.name}" }
            assertEquals(listOf("default.json->default@phone.json"), moved)
            assertEquals("phone", phone.source); assertEquals(3, phone.find("meow")!!.examples.size)
            assertFalse(File(dir, "enroll/default.json").exists()); assertTrue(File(dir, "enroll/default@phone.json").exists())
            // other sources start empty, and nothing is migrated twice
            val usb = EnrollmentStore.load(dir, "default", "usb") { _, _ -> moved += "again" }
            assertTrue(usb.classes.isEmpty()); assertEquals(1, moved.size)
            // saved with its source and example meta
            phone.add("gesture", "pop", listOf(feats(null, DoubleArray(0)).withMeta(JSONObject().put("cell", "soft-1").put("loudness", "soft"))))
            EnrollmentStore.save(dir, phone)
            val back = EnrollmentStore.load(dir, "default", "phone")
            assertEquals("phone", back.toJson().getString("source"))
            assertEquals("soft-1", back.find("pop")!!.examples[0].cell)
            assertEquals(phone.toJson().toString(), back.toJson().toString())
        } finally { dir.deleteRecursively() }
    }

    @Test fun exampleMetaIsValidated() {
        val o = JSONObject().put("fp", org.json.JSONArray(listOf(1.0, 2.0))).put("fp_version", "fp1").put("meta", "x")
        try { SoundFeatures.parse(o, "e"); throw AssertionError("expected a rejection") } catch (e: IllegalArgumentException) {
            assertTrue(e.message!!.contains("meta"))
        }
        o.put("meta", JSONObject().put("cell", "a".repeat(SoundFeatures.MAX_META_CHARS)))
        try { SoundFeatures.parse(o, "e"); throw AssertionError("expected a rejection") } catch (e: IllegalArgumentException) {
            assertTrue(e.message!!.contains("over"))
        }
    }

    // --- the tolerant grade and the new ops ----------------------------------------------------------------------------

    @Test fun aLabelMismatchWithAGoodShapeIsStoredAndHeldUntilConfirmed() {
        val h = FakeHost(); val t = GestureTrainer(h)
        t.command("train_start", mapOf("gesture" to "rise")); t.command("train_record", emptyMap())
        // a good rise (pitch16 rising), but the extractor heard "arch": stored with label_mismatch, not confirmed
        t.onSounds(msg("arch", 180.0, 1400, features = feats(180.0, rising))); h.advance(GestureTrainer.SETTLE_MS)
        assertEquals("passed", session(t.status(null))["state"])
        val ex = h.store("phone").find("rise")!!.examples.single()
        assertTrue(ex.meta!!.getBoolean("label_mismatch")); assertFalse(ex.meta!!.getBoolean("confirmed"))
        assertEquals("arch", ex.meta!!.getJSONObject("heard").getString("label"))
        val id = ex.meta!!.getLong("id")
        @Suppress("UNCHECKED_CAST")
        val un = t.status(null)["unconfirmed"] as List<Map<String, Any?>>
        assertEquals(1, un.size)
        assertEquals(id.toLong(), (un[0]["id"] as Number).toLong()); assertEquals("rise", un[0]["gesture"]); assertEquals("arch", un[0]["heard"])
        // the review plots the take itself: its pitch16 and f0 ride along
        assertEquals(rising.toList(), un[0]["pitch16"])
        assertEquals(180, (un[0]["f0_hz"] as Number).toInt())
        assertEquals(1400, (un[0]["dur_ms"] as Number).toInt())
        // confirm: it now takes part in matching (meta.confirmed true), and leaves the review list
        t.command("train_confirm", mapOf("id" to id, "keep" to true))
        assertTrue(h.store("phone").find("rise")!!.examples.single().meta!!.getBoolean("confirmed"))
        assertEquals(0, (t.status(null)["unconfirmed"] as List<*>).size)
    }

    @Test fun aRejectedUnconfirmedTakeIsDeleted() {
        val h = FakeHost(); val t = GestureTrainer(h)
        t.command("train_start", mapOf("gesture" to "rise")); t.command("train_record", emptyMap())
        t.onSounds(msg("arch", 180.0, 1400, features = feats(180.0, rising))); h.advance(GestureTrainer.SETTLE_MS)
        val id = h.store("phone").find("rise")!!.examples.single().meta!!.getLong("id")
        t.command("train_confirm", mapOf("id" to id, "keep" to false))
        assertNull(h.store("phone").find("rise"))   // the class goes when its last example is deleted
    }

    @Test fun trainGotoDropsOnlyTheInFlightTake() {
        val h = FakeHost(); val t = GestureTrainer(h)
        t.command("train_start", mapOf("gesture" to "rise")); t.command("train_record", emptyMap())
        t.onSounds(msg("rise", 180.0, 1400)); h.advance(GestureTrainer.SETTLE_MS)
        assertEquals("passed", session(t.status(null))["state"])
        t.command("train_next", emptyMap())                       // records the next cell
        assertEquals("recording", session(t.status(null))["state"])
        t.onTick(180.0, -30.0)                                    // in-flight data, not yet a sound
        val st = t.command("train_goto", mapOf("gesture" to "rise", "cell" to "hum-high-slow"))
        assertNull(st["error"])
        assertEquals("hum-high-slow", session(st)["cell"]); assertEquals("ready", session(st)["state"])
        // the stored take stays, the in-flight one is dropped (not stored)
        assertEquals(1, h.store("phone").find("rise")!!.examples.size)
        assertEquals("hum-low-slow", h.store("phone").find("rise")!!.examples[0].cell)
        // crossing a gesture boundary
        val st2 = t.command("train_goto", mapOf("gesture" to "fall", "cell" to "hum-low-slow"))
        assertEquals("fall", session(st2)["gesture"]); assertEquals("hum-low-slow", session(st2)["cell"])
    }

    @Test fun autoAdvanceStartsTheNextUndoneCellAfterAPass() {
        val h = FakeHost(); val t = GestureTrainer(h)
        t.command("train_start", mapOf("gesture" to "rise")); t.command("train_record", emptyMap())
        t.onSounds(msg("rise", 180.0, 1400)); h.advance(GestureTrainer.SETTLE_MS)
        assertEquals("passed", session(t.status(null))["state"])
        h.advance(GestureTrainer.AUTO_ADVANCE_MS)
        assertEquals("recording", session(t.status(null))["state"])
        assertEquals("hum-low-quick", session(t.status(null))["cell"])
    }

    @Test fun autoAdvanceIsCancelledByACommand() {
        val h = FakeHost(); val t = GestureTrainer(h)
        t.command("train_start", mapOf("gesture" to "rise")); t.command("train_record", emptyMap())
        t.onSounds(msg("rise", 180.0, 1400)); h.advance(GestureTrainer.SETTLE_MS)
        assertEquals("passed", session(t.status(null))["state"])
        // a dock command (goto) cancels the pending auto-advance
        t.command("train_goto", mapOf("gesture" to "rise", "cell" to "whistle-low-slow"))
        assertEquals("whistle-low-slow", session(t.status(null))["cell"])
        h.advance(5_000)
        assertEquals("ready", session(t.status(null))["state"])
        assertEquals("whistle-low-slow", session(t.status(null))["cell"])
    }

    @Test fun statusHasExpectPosAndPrevNext() {
        val h = FakeHost(); val t = GestureTrainer(h)
        t.command("train_start", mapOf("gesture" to "rise"))
        val s = session(t.status(null))
        @Suppress("UNCHECKED_CAST")
        val expect = s["expect"] as Map<String, Any?>
        assertEquals(listOf("rise"), expect["sequence"]); assertEquals("low", expect["start"])
        assertEquals(4, expect["span_st"]); assertEquals(1.5, expect["tol_st"])
        @Suppress("UNCHECKED_CAST")
        val pos = s["pos"] as Map<String, Any?>
        assertEquals(1, pos["i"]); assertEquals(TrainPlan.TOTAL, pos["n"]); assertEquals(1, pos["gesture_i"]); assertEquals(8, pos["gesture_n"])
        assertEquals(false, s["can_prev"]); assertEquals(true, s["can_next"])
    }

    /** Auto-advance goes to the next UNDONE cell, wrapping to one the arrows jumped over, and pushes it (a Pico source
     *  sends no ticks, so nothing else would tell the screen). */
    @Test fun autoAdvanceFindsTheNextUndoneCellAndPushesIt() {
        val h = FakeHost(); val t = GestureTrainer(h)
        t.command("train_start", mapOf("gesture" to "rise"))
        t.command("train_goto", mapOf("gesture" to "rise", "cell" to "whistle-high-quick"))   // the last cell
        t.command("train_record", emptyMap())
        t.onSounds(msg("rise", 1200.0, 500)); h.advance(GestureTrainer.SETTLE_MS)
        assertEquals("passed", session(t.status(null))["state"])
        h.pushes.clear()
        h.advance(GestureTrainer.AUTO_ADVANCE_MS)
        assertEquals("hum-low-slow", session(t.status(null))["cell"])           // wrapped to the first undone cell
        assertEquals("recording", session(h.pushes.last())["state"])
    }

    /** An auto-advance of a round that ended (train_cancel, the background) does nothing. */
    @Test fun autoAdvanceNeverOutlivesItsRound() {
        val h = FakeHost(); val t = GestureTrainer(h)
        t.command("train_start", mapOf("gesture" to "rise")); t.command("train_record", emptyMap())
        t.onSounds(msg("rise", 180.0, 1400)); h.advance(GestureTrainer.SETTLE_MS)
        t.cancel("app background")
        h.advance(GestureTrainer.AUTO_ADVANCE_MS)
        assertFalse(t.active); assertTrue(h.tasks.isEmpty())
    }

    /** train_goto with no round open (the hub's rows) opens one on that cell; refused while blocked. */
    @Test fun trainGotoOpensARoundFromTheHub() {
        val h = FakeHost(); val t = GestureTrainer(h)
        h.block = "Canti is paused."
        assertEquals("Canti is paused.", t.command("train_goto", mapOf("gesture" to "fall", "cell" to "whistle-low-slow"))["error"])
        assertFalse(t.active)
        h.block = null
        val st = t.command("train_goto", mapOf("gesture" to "fall", "cell" to "whistle-low-slow"))
        assertNull(st["error"])
        assertEquals("fall", session(st)["gesture"]); assertEquals("whistle-low-slow", session(st)["cell"]); assertEquals("ready", session(st)["state"])
        assertEquals(13, (session(st)["pos"] as Map<*, *>)["i"])                // rise 8 + fall's 5th cell
    }

    /** train_confirm addresses only a take stored with label_mismatch: never a legacy example (no id) or a plain one. */
    @Test fun trainConfirmRefusesOtherExamples() {
        val h = FakeHost(); val t = GestureTrainer(h)
        h.store("phone").add(EnrollmentStore.GESTURE, "rise", listOf(feats(180.0).withMeta(JSONObject().put("cell", "hum-low-slow"))))
        assertNotNull(t.command("train_confirm", mapOf("id" to -1, "keep" to false))["error"])
        t.command("train_start", mapOf("gesture" to "rise")); t.command("train_record", emptyMap())
        t.onSounds(msg("rise", 180.0, 500)); h.advance(GestureTrainer.SETTLE_MS)   // hum-low-quick, label agrees
        val id = h.store("phone").find("rise")!!.examples.last().meta!!.getLong("id")
        assertNotNull(t.command("train_confirm", mapOf("id" to id, "keep" to false))["error"])
        assertEquals(2, h.store("phone").find("rise")!!.examples.size)
    }

    /** A whistle cell is judged on the whistle range: a low whistle start is far above the voice's home. */
    @Test fun aWhistleCellUsesTheWhistleScale() {
        val h = FakeHost(); val t = GestureTrainer(h)
        h.scales["hum"] = ShapeGrade.Scale(80.0, 110.0, 160.0)
        h.scales["whistle"] = ShapeGrade.Scale(800.0, 1100.0, 1600.0)
        t.command("train_goto", mapOf("gesture" to "rise", "cell" to "whistle-low-slow"))
        t.command("train_record", emptyMap())
        t.onSounds(msg("rise", 1000.0, 1400)); h.advance(GestureTrainer.SETTLE_MS)   // starts ~840 Hz
        val s = session(t.status(null))
        assertEquals("passed", s["state"])
        @Suppress("UNCHECKED_CAST")
        val pitch = ((s["result"] as Map<String, Any?>)["checks"] as List<Map<String, Any?>>).first { it["id"] == "PITCH" }
        assertEquals("ok", pitch["state"])
        assertEquals(1100.0, (t.status(null)["scale"] as Map<*, *>)["home_hz"])
    }

    /** A pop counts as a click (2026-09-28): an old UI's "pop" opens the click card, and train_goto folds it too. */
    @Test fun legacyPopGestureFoldsToClickInStartAndGoto() {
        val h = FakeHost(); val t = GestureTrainer(h)
        t.command("train_start", mapOf("gesture" to "pop"))
        assertEquals("click", session(t.status(null))["gesture"]); assertEquals("soft-1", session(t.status(null))["cell"])
        t.command("train_cancel", emptyMap())
        t.command("train_goto", mapOf("gesture" to "pop", "cell" to "loud-1"))
        assertEquals("click", session(t.status(null))["gesture"]); assertEquals("loud-1", session(t.status(null))["cell"])
    }

    /** A legacy gesture:pop class stays in the store but is not part of the plan; train_delete {gesture:"pop"} removes
     *  only it (never the click class). */
    @Test fun legacyPopClassIsNotCountedAndDeletesOnItsOwn() {
        val h = FakeHost(); val t = GestureTrainer(h)
        h.store("phone").add("gesture", "pop", List(4) { feats(null, DoubleArray(0)).withMeta(JSONObject().put("cell", "soft-1")) })
        assertEquals(0, t.status(null)["done"])   // the legacy pop class is not counted toward 48
        @Suppress("UNCHECKED_CAST")
        val legacy = t.status(null)["legacy"] as List<Map<String, Any?>>
        assertEquals(listOf(mapOf("gesture" to "pop", "n" to 4)), legacy)
        // train_delete {gesture:"pop"} removes only the legacy pop class, never the click class
        h.store("phone").add("gesture", "click", List(3) { feats(null, DoubleArray(0)).withMeta(JSONObject().put("cell", "soft-1")) })
        t.command("train_delete", mapOf("gesture" to "pop"))
        assertNull(h.store("phone").find("pop"))
        assertNotNull(h.store("phone").find("click"))   // the click class is untouched
    }

    /** A click take whose extractor said "pop" stores without a label_mismatch (the fold, 2026-09-28). */
    @Test fun aPopHeardForAClickCellIsNotALabelMismatch() {
        val h = FakeHost(); val t = GestureTrainer(h)
        t.command("train_start", mapOf("gesture" to "click")); t.command("train_record", emptyMap())
        t.onSounds(msg("pop", null, 40)); h.advance(GestureTrainer.SETTLE_MS)
        val s = session(t.status(null))
        assertEquals("passed", s["state"])
        val ex = h.store("phone").find("click")!!.examples.single()
        assertEquals("pop", ex.meta!!.getJSONObject("heard").getString("label"))
        assertFalse(ex.meta!!.optBoolean("label_mismatch"))
    }

    // --- soft delete / undo (range-calibdel-k) --------------------------------------------------------------------------

    @Test fun softDeleteTrashesATakeAndUndoRestoresIt() {
        val h = FakeHost(); val t = GestureTrainer(h)
        h.store("phone").add("gesture", "click", listOf(
            feats(null, DoubleArray(0)).withMeta(JSONObject().put("cell", "soft-1").put("id", 1)),
            feats(null, DoubleArray(0)).withMeta(JSONObject().put("cell", "soft-2").put("id", 2))))
        val r = t.command("train_delete", mapOf("gesture" to "click", "cell" to "soft-1"))
        val undoId = r["undo_id"] as Long
        assertEquals("soft-2", h.store("phone").find("click")!!.examples.single().cell)   // the other cell stays
        assertEquals(1, h.trash("phone")!!.length())
        // undo puts the example back with its cell and id, beside the one that stayed
        t.command("train_undelete", mapOf("id" to undoId))
        assertEquals(setOf("soft-1", "soft-2"), h.store("phone").find("click")!!.examples.map { it.cell }.toSet())
        assertEquals(1L, h.store("phone").find("click")!!.examples.first { it.cell == "soft-1" }.meta!!.getLong("id"))
        assertNull(h.trash("phone"))
    }

    @Test fun aWholeClassDeleteComesBackWhole() {
        val h = FakeHost(); val t = GestureTrainer(h)
        h.store("phone").add("gesture", "hiss", listOf(
            feats(null, DoubleArray(0)).withMeta(JSONObject().put("cell", "soft-1")),
            feats(null, DoubleArray(0)).withMeta(JSONObject().put("cell", "loud-2"))))
        val r = t.command("train_delete", mapOf("gesture" to "hiss"))
        val undoId = r["undo_id"] as Long
        assertNull(h.store("phone").find("hiss"))
        t.command("train_undelete", mapOf("id" to undoId))
        assertEquals(setOf("soft-1", "loud-2"), h.store("phone").find("hiss")!!.examples.mapNotNull { it.cell }.toSet())
        assertNull(h.trash("phone"))
    }

    @Test fun undoRefusedAfterARecordAgain() {
        val h = FakeHost(); val t = GestureTrainer(h)
        h.store("phone").add("gesture", "click", listOf(feats(null, DoubleArray(0)).withMeta(JSONObject().put("cell", "soft-1"))))
        val r = t.command("train_delete", mapOf("gesture" to "click", "cell" to "soft-1"))
        val undoId = r["undo_id"] as Long
        h.store("phone").add("gesture", "click", listOf(feats(null, DoubleArray(0)).withMeta(JSONObject().put("cell", "soft-1"))))
        val e = t.command("train_undelete", mapOf("id" to undoId))["error"] as String
        assertEquals("recorded again since", e)
    }

    @Test fun trashCapsAtTwentyNewestFirst() {
        val h = FakeHost(); val t = GestureTrainer(h)
        val cells = TrainPlan.GESTURES.flatMap { g -> TrainPlan.cells(g).map { g to it.id } }
        for ((g, cell) in cells.take(21)) {
            val ex = (if (g in TrainPlan.CONTOURS) feats(200.0, pitchFor(g)) else feats(null, DoubleArray(0)))
                .withMeta(JSONObject().put("cell", cell))
            h.store("phone").add("gesture", g, listOf(ex))
        }
        val undoIds = mutableListOf<Long>()
        for ((g, cell) in cells.take(21)) undoIds += t.command("train_delete", mapOf("gesture" to g, "cell" to cell))["undo_id"] as Long
        val tr = h.trash("phone")!!
        assertEquals(20, tr.length())                       // the oldest entry dropped off
        val ids = (0 until tr.length()).map { tr.getJSONObject(it).getLong("id") }
        assertTrue(undoIds.first() !in ids)                 // the first delete is gone
        assertEquals(undoIds.drop(1), ids.reversed())       // newest first
    }
}
