package ai.vox.companion

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
    private val rising = DoubleArray(16) { it * 0.4 }
    private fun feats(f0Hz: Double?, pitch: DoubleArray = rising) = SoundFeatures(fp(f0Hz), "fp1", pitch)
    private fun line(label: String, like: String = "hum") = when (label) {
        in TrainPlan.CONTOURS -> "hum that ${Vocab.CONTOURS[label]}; pitch change large (over 4 semitones); duration medium (400-1000 ms); tone clear tone; loudness normal; sounds like $like"
        else -> "${Vocab.DISCRETE[label] ?: "unknown"}; instant sound; loudness normal; sounds like mouth sound"
    }

    private fun heard(label: String, f0: Double? = 200.0, dur: Long? = 500, pitch: DoubleArray = rising, n: Int = 1) =
        TrainHeard(List(n) { label }, List(n) { line(label) }, dur, feats(f0, if (label in TrainPlan.CONTOURS) pitch else DoubleArray(0)))

    private fun msg(label: String, f0: Double? = 200.0, dur: Long = 500, features: SoundFeatures? = feats(f0, if (label in TrainPlan.CONTOURS) rising else DoubleArray(0))) =
        FeatureMessage(id = 1, mode = "gesture", armed = true, sounds = listOf(line(label)), sequence = listOf(label), phrase = null,
            timing = listOf(Stamp(1000, 1000 + dur)), features = listOf(features))

    private class FakeHost : TrainHost {
        var t = 0L
        val tasks = mutableListOf<Pair<Long, () -> Unit>>()
        var src = "phone"
        var block: String? = null
        var ticksOn = false
        val stores = mutableMapOf<String, EnrollmentStore>()
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
        override fun liveTrace() = src != "pico"
        override fun ticks(on: Boolean) { ticksOn = on }
        override fun profile() = "default"
        override fun store(source: String) = stores.getOrPut(source) { EnrollmentStore("default", source) }
        override fun change(source: String, what: String, change: (EnrollmentStore) -> Unit) = change(store(source))
        override fun wallMs() = 1_790_000_000_000L
        override fun log(vararg fields: Pair<String, Any?>) { logs += fields.toMap() }
        override fun push(status: Map<String, Any?>) { pushes += status }
    }

    @Suppress("UNCHECKED_CAST")
    private fun session(st: Map<String, Any?>) = st["session"] as Map<String, Any?>

    // --- plan ----------------------------------------------------------------------------------------------------------

    @Test fun planHasEightCellsPerContourFourPerDiscrete() {
        for (g in TrainPlan.CONTOURS) assertEquals(g, 8, TrainPlan.cells(g).size)
        for (g in TrainPlan.DISCRETE) assertEquals(g, 4, TrainPlan.cells(g).size)
        assertEquals(52, TrainPlan.TOTAL)
        for (g in TrainPlan.GESTURES) assertTrue("under the class cap", TrainPlan.cells(g).size <= EnrollmentStore.MAX_EXAMPLES)
        assertEquals("Whistle a QUICK rise, starting LOW", TrainPlan.cell("rise", "whistle-low-quick").prompt)
        assertEquals("Hum a SLOW arch, starting HIGH", TrainPlan.cell("arch", "hum-high-slow").prompt)
        assertEquals(mapOf("tone" to "hum", "pitch" to "low", "length" to "long"), TrainPlan.cell("flat", "hum-low-long").tags)
        assertEquals("Hum a LONG flat note, LOW", TrainPlan.cell("flat", "hum-low-long").prompt)
        assertEquals(mapOf("loudness" to "loud", "take" to "2"), TrainPlan.cell("pop", "loud-2").tags)
        assertEquals("Pop your lips LOUDLY (2 of 2)", TrainPlan.cell("pop", "loud-2").prompt)
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
        assertTrue(TrainJudge.judge(TrainPlan.cell("pop", "soft-1"), heard("pop", null, 40)).ok)
    }

    @Test fun judgeExplainsAWrongShapeAndOffersKeepAnyway() {
        val v = TrainJudge.judge(TrainPlan.cell("arch", "hum-low-slow"), heard("dip", 200.0, 1400))
        assertFalse(v.ok)
        assertEquals("Heard a dip (down then up): an arch goes up then down.", v.reason)
        assertTrue("a wrong label alone can be kept", v.canKeep)
        val d = TrainJudge.judge(TrainPlan.cell("pop", "loud-1"), heard("click", null, 30))
        assertEquals("Heard a click: a pop is a short lip pop.", d.reason); assertTrue(d.canKeep)
        // a contour class needs the pitch track: a pop cannot be kept as a rise
        val p = TrainJudge.judge(TrainPlan.cell("rise", "hum-low-quick"), heard("pop", null, 30))
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
        val q = TrainJudge.judge(TrainPlan.cell("dip", "hum-low-quick"), heard("dip", 200.0, 1400))
        assertEquals("It took 1.4 s: a QUICK dip takes about half a second (at most 1.0 s).", q.reason)
        val s = TrainJudge.judge(TrainPlan.cell("flat", "hum-low-long"), heard("flat", 200.0, 500))
        assertEquals("It took 0.5 s: a LONG flat note takes about 1.5 s (at least 0.8 s).", s.reason)
        // no f0 in the fingerprint: the line's `sounds like` decides
        assertEquals("whistle", TrainJudge.tone(SoundFeatures(DoubleArray(3), "fp9", rising), line("rise", "whistle")))
    }

    @Test fun judgeRefusesTwoSoundsAndMissingFingerprints() {
        val two = TrainJudge.judge(TrainPlan.cell("arch", "hum-low-slow"),
            TrainHeard(listOf("rise", "fall"), listOf(line("rise"), line("fall")), 600, feats(200.0)))
        assertEquals("Heard 2 sounds (rise then fall): make it one unbroken sound.", two.reason); assertFalse(two.canKeep)
        val none = TrainJudge.judge(TrainPlan.cell("pop", "soft-1"), TrainHeard(listOf("pop"), listOf(line("pop")), 30, null))
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
        assertEquals(1, st["done"]); assertEquals(52, st["total"])
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
        t.command("train_start", mapOf("gesture" to "pop")); t.command("train_record", emptyMap())
        h.advance(GestureTrainer.TAKE_TIMEOUT_MS)
        val s = session(t.status(null)); assertEquals("failed", s["state"]); assertEquals("Heard nothing in 8 s.", s["reason"])
        h.block = "Canti is in cursor mode: switch to gesture mode to train gestures."
        val r = session(t.command("train_retry", emptyMap()))
        assertEquals("failed", r["state"]); assertEquals(h.block, r["reason"])
    }

    @Test fun twoSoundsInOneTakeFail() {
        val h = FakeHost(); val t = GestureTrainer(h)
        t.command("train_start", mapOf("gesture" to "arch")); t.command("train_record", emptyMap())
        t.onSounds(msg("rise")); h.advance(300); t.onSounds(msg("fall")); h.advance(GestureTrainer.SETTLE_MS)
        assertEquals("Heard 2 sounds (rise then fall): make it one unbroken sound.", session(t.status(null))["reason"])
    }

    @Test fun soundsOutsideARecordingAreSwallowedAndTheCardResumes() {
        val h = FakeHost(); val t = GestureTrainer(h)
        assertFalse("no session: sounds act as usual", t.onSounds(msg("pop")))
        t.command("train_start", mapOf("gesture" to "pop"))
        assertTrue("session open, not recording: dropped", t.onSounds(msg("pop")))
        assertNull(h.store("phone").find("pop"))
        // record two cells, stop, and start again: only the missing ones are asked for
        for (i in 0 until 2) { t.command(if (i == 0) "train_record" else "train_next", emptyMap()); t.onSounds(msg("pop", null, 40)); h.advance(GestureTrainer.SETTLE_MS) }
        t.command("train_cancel", emptyMap()); assertFalse(t.active); assertFalse(h.ticksOn)
        val s = session(t.command("train_start", mapOf("gesture" to "pop")))
        assertEquals("loud-1", s["cell"]); assertEquals(2, s["count"])
        // a finished card refuses a new round until Delete / redo
        for (i in 0 until 2) { t.command(if (i == 0) "train_record" else "train_next", emptyMap()); t.onSounds(msg("pop", null, 40)); h.advance(GestureTrainer.SETTLE_MS) }
        assertEquals("passed", session(t.status(null))["state"])
        assertEquals("done", session(t.command("train_next", emptyMap()))["state"])
        t.command("train_cancel", emptyMap())
        assertTrue((t.command("train_start", mapOf("gesture" to "pop"))["error"] as String).contains("Delete / redo"))
        // redo one cell: it replaces its example
        t.command("train_start", mapOf("gesture" to "pop", "cell" to "soft-2")); t.command("train_record", emptyMap())
        t.onSounds(msg("pop", null, 40)); h.advance(GestureTrainer.SETTLE_MS)
        assertEquals(4, h.store("phone").find("pop")!!.examples.size)
        t.command("train_cancel", emptyMap())
        // Delete / redo: one cell, then the card
        t.command("train_delete", mapOf("gesture" to "pop", "cell" to "loud-1"))
        assertEquals(3, h.store("phone").find("pop")!!.examples.size)
        t.command("train_delete", mapOf("gesture" to "pop"))
        assertNull(h.store("phone").find("pop"))
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
}
