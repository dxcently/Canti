package ai.vox.companion.joystick

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** The calibration engine against the prototype's setup (golden "setup": all eight steps pass, the pops segment skipped;
 *  "setup_fail": the glide fails and is retried, the vowels, clicks and whistle fail and are skipped, the hiss fails and
 *  is retried, the room fails and is skipped), plus the command rules and the profile round trip (a version 1 profile
 *  still loads). */
class JoyCalibrationTest {
    private val golden = JSONObject(javaClass.classLoader!!.getResource("joystick_golden.json")!!.readText())
    private val spec = JoySpec.parse(File("src/main/assets/joystick_v1.json").readText())
    private val py2kt = mapOf("home" to "hum", "range" to "glide", "vowels" to "vowels", "clicks" to "clicks",
        "whistle" to "whistle", "hiss" to "hiss", "room" to "room")   // "pops" is gone (2026-09-28); a legacy "pops" maps to null

    private fun num(o: Any?): Double? = if (o == null || o == JSONObject.NULL) null else (o as Number).toDouble()

    private fun ticks(c: JSONObject): List<Tick> {
        val rows = c.getJSONArray("ticks")
        return (0 until rows.length()).map { i ->
            val r = rows.getJSONArray(i)
            Tick(r.getDouble(0), r.getDouble(1), r.getDouble(2), r.getDouble(3), r.getInt(4) == 1,
                num(r.opt(5)) ?: Double.NaN, num(r.opt(6)) ?: Double.NaN, r.getString(7), r.getDouble(8), r.getDouble(9))
        }
    }

    private fun case(name: String): JSONObject {
        val a = golden.getJSONArray("setup")
        return (0 until a.length()).map { a.getJSONObject(it) }.first { it.getString("name") == name }
    }

    /** The prototype's pops step, which the engine no longer has (2026-09-28). Its segment is skipped: ticks and
     *  extractor events from when the step before pops finishes until pops ends are not fed, and the step after it
     *  (clicks) starts once the segment has passed. */
    private class PopsSegment(val predecessor: String, val startMs: Double, val endMs: Double, val actionMs: Double?)

    private fun popsSegment(c: JSONObject): PopsSegment? {
        val done = c.getJSONArray("steps_done").let { a -> (0 until a.length()).map { a.getJSONObject(it) } }
        val popsIdx = done.indexOfFirst { it.getString("step") == "pops" }
        if (popsIdx < 0) return null
        val prev = done.take(popsIdx).lastOrNull { it.getString("step") != "cmd" } ?: return null
        val predecessor = py2kt[prev.getString("step")] ?: return null
        val cmds = done.drop(popsIdx + 1).takeWhile { it.getString("step") == "cmd" }
        val actionMs = cmds.lastOrNull()?.getDouble("t_ms")          // the pops skip / retry (a fail), else null (a pass)
        val endMs = actionMs ?: done[popsIdx].getDouble("t_ms")
        return PopsSegment(predecessor, prev.getDouble("t_ms"), endMs, actionMs)
    }

    /** Runs a golden setup the way the UI drives it: calib_step for the next step after each step_done, the golden's
     *  retry / skip at their times. Returns the engine and the failures seen (step, t, reason). */
    private fun run(c: JSONObject): Pair<JoyCalibration, List<Triple<String, Double, String>>> {
        val cal = JoyCalibration(spec, "phone")
        val acts = c.getJSONArray("actions").let { a -> (0 until a.length()).map { a.getJSONArray(it).let { x -> x.getDouble(0) to x.getString(1) } } }.toMutableList()
        val seg = popsSegment(c)
        if (seg != null && seg.actionMs != null) acts.removeAll { it.first == seg.actionMs }   // the pops skip has no step
        val fails = ArrayList<Triple<String, Double, String>>()
        // the extractor's events: [delivered at, t_start, label, raw], handed over before the tick at or after delivery
        val exq = c.getJSONArray("ex_events").let { a -> (0 until a.length()).map { a.getJSONArray(it) } }.toMutableList()
        var waitingForPops = false
        for (tk in ticks(c)) {
            if (seg != null && tk.tMs > seg.startMs && tk.tMs < seg.endMs) continue   // the pops segment is not fed
            while (acts.isNotEmpty() && acts[0].first <= tk.tMs) {
                when (acts.removeAt(0).second) { "retry" -> cal.retry(tk.tMs); "skip" -> cal.skip(tk.tMs) }
            }
            while (exq.isNotEmpty() && exq[0].getDouble(0) <= tk.tMs) {
                val e = exq.removeAt(0)
                cal.extractorEvent(e.getDouble(1), e.getString(2), SoundExample.raw(e.getJSONObject(3)))
            }
            val was = cal.state
            cal.push(tk)
            if (cal.state == "failed" && was != "failed") fails += Triple(cal.step, tk.tMs, cal.reason!!)
            if (cal.state == "step_done") {
                when {
                    waitingForPops -> { waitingForPops = false; cal.startStep(JoyCalibration.STEPS.first { it !in cal.finished }, tk.tMs) }
                    seg != null && cal.step == seg.predecessor -> waitingForPops = true   // wait out the pops segment
                    else -> cal.startStep(JoyCalibration.STEPS.first { it !in cal.finished }, tk.tMs)
                }
            }
        }
        return cal to fails
    }

    private fun check(c: JSONObject, cal: JoyCalibration) {
        val p = cal.draft
        val n = c.getString("name")
        assertEquals("$n home", num(c.opt("home_st")), p.homeSt)
        assertEquals("$n clarity", num(c.opt("clarity_on")), p.clarityOn)
        assertEquals("$n lo", num(c.opt("lo_st")), p.loSt)
        assertEquals("$n hi", num(c.opt("hi_st")), p.hiSt)
        val gc = c.getJSONObject("centroids_bark")
        val kc = p.centroids ?: spec.centroidsBark
        for (v in JoyCalibration.VOWELS) {
            assertEquals("$n cent $v f1", gc.getJSONArray(v).getDouble(0), kc[v]!![0], 1e-9)
            assertEquals("$n cent $v f2", gc.getJSONArray(v).getDouble(1), kc[v]!![1], 1e-9)
        }
        assertEquals("$n dead zone", c.getDouble("vowel_dead_zone"), p.vowelDeadZone ?: spec.vowelDeadZone, 1e-9)
        assertEquals("$n full", c.getDouble("vowel_full"), p.vowelFull ?: spec.vowelFull, 1e-9)
        if (c.isNull("vowel_report")) assertNull(p.vowelReport)
        else {
            val r = c.getJSONObject("vowel_report")
            for (v in JoyCalibration.VOWELS) for (k in listOf("n", "right", "none", "left"))
                assertEquals("$n report $v $k", num(r.getJSONObject(v).opt(k)), p.vowelReport!![v]!![k])
        }
        // a pop counts as a click (2026-09-28): a fresh run never measures the pops step, so these stay null / default
        assertNull("$n pop", p.pop)
        assertNull("$n pops examples", p.popsExamples)
        assertNull("$n click / pop rule", p.clickPop)
        val sk = c.getJSONArray("skipped")
        assertEquals("$n skipped", (0 until sk.length()).map { py2kt[sk.getString(it)] }.filterNotNull().sortedBy { JoyCalibration.STEPS.indexOf(it) }, p.skipped)
        // calibration v2
        fun exs(k: String) = if (c.isNull(k)) null else SoundExample.listFrom(c.getJSONArray(k))
        assertEquals("$n clicks examples", exs("clicks_examples"), p.clicksExamples)
        assertEquals("$n hiss examples", exs("hiss_examples"), p.hissExamples)
        assertEquals("$n whistle", if (c.isNull("whistle")) null else WhistleRange.fromJson(c.getJSONObject("whistle")), p.whistle)
        assertEquals("$n room", if (c.isNull("room")) null else RoomNoise.fromJson(c.getJSONObject("room")), p.room)
        // the level gate is derived from the clicks + hiss examples and the room (a fresh run has no pops examples):
        // compute it here, not from the golden number (the golden gate included the pops' examples).
        val expGate = CalibV2.deriveGate(null, exs("clicks_examples"), exs("hiss_examples"),
            if (c.isNull("room")) null else RoomNoise.fromJson(c.getJSONObject("room")), spec)
        assertEquals("$n gate", expGate, cal.gate)
        assertEquals("$n tick ceiling", num(c.opt("f0_max_at_end")) ?: spec.voiceTickF0MaxHz, cal.tickF0MaxHz, 0.0)
    }

    @Test fun allStepsPass() {
        val c = case("setup")
        val (cal, fails) = run(c)
        assertTrue("no failures: $fails", fails.isEmpty())
        assertEquals("done", cal.state)
        check(c, cal)
        val done = c.getJSONArray("steps_done")
        val py = (0 until done.length()).map { done.getJSONObject(it) }.filter { it.getString("step") != "cmd" && it.getString("step") != "pops" }
        assertEquals(7, py.size)
        val s = cal.status(false)
        assertEquals(true, s["step_done"]); assertEquals(1.0, s["progress"])
        val r = s["result"] as JSONObject
        assertTrue(r.isNull("pops_heard"))
        assertEquals(1.0, r.getJSONObject("vowels").getJSONObject("ee").getDouble("acc"), 0.0)
        assertTrue(r.getJSONObject("extractor").length() == 0)
        assertEquals(2, r.getInt("version"))
        assertEquals(3, r.getInt("clicks_heard")); assertEquals(2, r.getInt("hiss_heard"))
        assertFalse(r.isNull("whistle_lo_hz")); assertFalse(r.isNull("room_floor_dbfs"))
        assertEquals("calibration", r.getJSONObject("level_gate").getString("from"))
        assertEquals(0, r.getJSONArray("missing_steps").length()); assertFalse(r.getBoolean("needs_recalibration"))
        val heard = s["heard"] as Map<*, *>
        assertEquals(3, heard["clicks_need"]); assertEquals(2, heard["hiss_need"])
        assertEquals(spec.whistleTickF0MaxHz, cal.tickF0MaxHz, 0.0)
    }

    @Test fun failRetrySkip() {
        val c = case("setup_fail")
        val (cal, fails) = run(c)
        val g = c.getJSONArray("fails").let { a -> (0 until a.length()).map { a.getJSONObject(it) } }.filter { it.getString("step") != "pops" }
        assertEquals(g.size, fails.size)
        for ((gf, kf) in g.zip(fails)) {
            assertEquals(py2kt[gf.getString("step")], kf.first)
            assertEquals(gf.getDouble("t_ms"), kf.second, 0.0)
            assertEquals(gf.getString("why"), kf.third)
        }
        assertEquals("done", cal.state)
        check(c, cal)
        assertEquals(listOf("vowels", "clicks", "whistle", "room"), cal.draft.skipped)
        assertEquals("default", cal.gate.from)
        assertEquals(emptyList<String>(), cal.draft.missingSteps)
        val r = cal.draft.toJson()
        assertTrue(r.isNull("pops_heard"))
        assertTrue(r.getJSONObject("vowels").getJSONObject("ee").isNull("acc"))
        assertFalse(r.isNull("home_hz"))
    }

    @Test fun commands() {
        val cal = JoyCalibration(spec, "phone")
        assertEquals("hum", cal.step); assertEquals("waiting", cal.state)
        // no voice at all: the hum fails after 10 s, and waits (never skips or restarts by itself)
        var t = 0.0
        while (cal.state != "failed") { cal.push(Tick(t, 0.0, 0.1, -70.0, false)); t += 20 }
        assertEquals(10000.0, t - 20, 0.0)
        assertEquals("no steady hum heard in 10 s", cal.reason)
        repeat(1000) { cal.push(Tick(t, 0.0, 0.1, -70.0, false)); t += 20 }
        assertEquals("failed", cal.state)
        assertEquals("failed", cal.status(false)["state"])
        cal.retry(t)
        assertEquals("hum", cal.step); assertEquals("waiting", cal.state); assertNull(cal.reason)
        cal.skip(t)                                           // before it heard anything: allowed
        assertEquals("glide", cal.step); assertEquals("waiting", cal.state)
        assertEquals(listOf("hum"), cal.draft.skipped)
        cal.skip(t); cal.skip(t)
        assertEquals("clicks", cal.step); assertEquals("recording", cal.state)
        cal.skip(t)
        assertEquals("whistle", cal.step); assertEquals("waiting", cal.state)
        assertEquals(spec.whistleTickF0MaxHz, cal.tickF0MaxHz, 0.0)        // the whistle step raises the ceiling
        cal.skip(t)
        assertEquals(spec.voiceTickF0MaxHz, cal.tickF0MaxHz, 0.0)
        assertEquals("hiss", cal.step); cal.skip(t)
        assertEquals("room", cal.step); cal.skip(t)
        assertEquals("done", cal.state)
        assertEquals(JoyCalibration.STEPS, cal.draft.skipped)
        try { cal.retry(t); throw AssertionError("retry without a failure") } catch (_: IllegalStateException) {}
    }

    @Test fun profileRoundTrip() {
        val (cal, _) = run(case("setup"))
        val p = cal.draft.copy(savedAtMs = 1234)
        val j = p.toJson()
        for (k in listOf("source", "version", "saved_at_ms", "home_hz", "range_lo_hz", "range_hi_hz", "voicing_threshold",
                "vowels", "pops_heard", "skipped", "extractor")) assertTrue(k, j.has(k))
        val q = JoyProfile.fromJson(JSONObject(j.toString()))
        assertEquals(p.homeSt, q.homeSt); assertEquals(p.loSt, q.loSt); assertEquals(p.hiSt, q.hiSt)
        assertEquals(p.clarityOn, q.clarityOn); assertEquals(p.pop, q.pop); assertEquals(p.popLabels, q.popLabels)
        assertEquals(p.vowelReport, q.vowelReport); assertEquals(p.skipped, q.skipped); assertEquals(1234L, q.savedAtMs)
        for (v in JoyCalibration.VOWELS) assertTrue(p.centroids!![v]!!.contentEquals(q.centroids!![v]!!))
        // applied to a live cursor
        val mv = Mover(spec, 400.0, 800.0)
        val pd = PopDetector(spec.pop)
        q.applyTo(spec, mv, pd)
        assertEquals(q.homeSt!!, mv.mid, 0.0)
        assertEquals(q.loSt!! to q.hiSt!!, mv.range)
        assertNull(q.pop)
        assertEquals(spec.pop.peakDb, pd.c.peakDb, 0.0)   // no pop block: the spec default stays
        assertEquals(q.whistle, mv.whistle)
        assertEquals(p.popsExamples, q.popsExamples); assertEquals(p.clicksExamples, q.clicksExamples)
        assertEquals(p.hissExamples, q.hissExamples); assertEquals(p.whistle, q.whistle); assertEquals(p.room, q.room)
        assertEquals(p.levelGate, q.levelGate); assertEquals(p.clickPop, q.clickPop)
        assertEquals(p.gate(spec), q.gate(spec)); assertEquals(p.levelGate, q.gate(spec))
        assertEquals(2, q.loadedVersion); assertFalse(q.needsRecalibration)
        JoyProfile("usb").applyTo(spec, mv, pd)             // no profile: the defaults
        assertEquals(spec.pop, pd.c)
        assertEquals(spec.homeRangeSt, mv.range)
        assertNull(mv.whistle)
        assertEquals(CalibV2.defaultGate(spec), JoyProfile("usb").gate(spec))
    }

    /** A profile saved before calibration v2 (format version 1) still loads and applies, and says which steps it lacks. */
    @Test fun version1ProfileNeedsRecalibration() {
        val v1 = JSONObject("""{"source":"phone","version":1,"saved_at_ms":5,"home_hz":99.0,"range_lo_hz":98.0,
            "range_hi_hz":184.0,"voicing_threshold":0.8,"vowels":{"ee":{"acc":1.0},"ah":{"acc":1.0},"oo":{"acc":1.0}},
            "pops_heard":3,"skipped":["vowels"],"extractor":{},"home_st":11.06,"clarity_on":0.8,"lo_st":10.06,"hi_st":20.95,
            "vowel_centroids_bark":null,"vowel_dead_zone":null,"vowel_full":null,"vowel_report":null,
            "pop":{"peak_db":15.2,"rise_db":12.0,"core_ticks":3},"pop_labels":["pop"]}""")
        val p = JoyProfile.fromJson(v1)
        assertEquals(1, p.loadedVersion)
        assertEquals(11.06, p.homeSt!!, 0.0); assertEquals(listOf("vowels"), p.skipped)
        assertEquals(JoyCalibration.V2_STEPS, p.missingSteps); assertTrue(p.needsRecalibration)
        assertEquals(CalibV2.defaultGate(spec), p.gate(spec)); assertNull(p.rule(spec))
        assertEquals(spec.voiceTickF0MaxHz, p.tickF0MaxHz(spec), 0.0)
        val j = p.toJson()
        assertEquals(2, j.getInt("version")); assertTrue(j.getBoolean("needs_recalibration"))
        assertEquals(JoyCalibration.V2_STEPS, (0 until j.getJSONArray("missing_steps").length()).map { j.getJSONArray("missing_steps").getString(it) })
        val mv = Mover(spec, 400.0, 800.0)
        p.applyTo(spec, mv, PopDetector(spec.pop))
        assertEquals(10.06 to 20.95, mv.range); assertNull(mv.whistle)
        // a recalibration starts from it: only the v2 steps left to do is the UI's choice; the engine runs any step
        val cal = JoyCalibration(spec, "phone", p)
        cal.startStep("clicks", 0.0)
        assertEquals("clicks", cal.step)
    }

    private val v1Json = """{"source":"phone","version":1,"saved_at_ms":5,"home_hz":99.0,"range_lo_hz":98.0,
        "range_hi_hz":184.0,"voicing_threshold":0.8,"vowels":{"ee":{"acc":1.0},"ah":{"acc":1.0},"oo":{"acc":1.0}},
        "pops_heard":3,"skipped":["vowels"],"extractor":{},"home_st":11.06,"clarity_on":0.8,"lo_st":10.06,"hi_st":20.95,
        "vowel_centroids_bark":null,"vowel_dead_zone":null,"vowel_full":null,"vowel_report":null,
        "pop":{"peak_db":15.2,"rise_db":12.0,"core_ticks":3},"pop_labels":["pop"]}"""

    /** Feeds the golden [c] from [fromMs] on, the way the UI drives a run: calib_step for the run's next step after each
     *  step_done (never past the run's own steps). */
    private fun feed(cal: JoyCalibration, c: JSONObject, fromMs: Double, toMs: Double = Double.MAX_VALUE, shift: Double = 0.0) {
        val exq = c.getJSONArray("ex_events").let { a -> (0 until a.length()).map { a.getJSONArray(it) } }
            .filter { it.getDouble(0) > fromMs && it.getDouble(0) <= toMs }.toMutableList()
        for (tk in ticks(c).filter { it.tMs > fromMs && it.tMs <= toMs }) {
            while (exq.isNotEmpty() && exq[0].getDouble(0) <= tk.tMs) {
                val e = exq.removeAt(0)
                cal.extractorEvent(e.getDouble(1) + shift, e.getString(2), SoundExample.raw(e.getJSONObject(3)))
            }
            cal.push(tk.copy(tMs = tk.tMs + shift))
            if (cal.state == "step_done") cal.startStep(cal.remaining.first(), tk.tMs + shift)
        }
    }

    /** calib_start {steps: [clicks, whistle, hiss, room]} from a version 1 profile: starts on clicks (no hum), ends
     *  `done` after the 4, and the saved profile is a full version 2 (the v1 values and skip state kept). */
    @Test fun partialRunFromVersion1() {
        val v1 = JoyProfile.fromJson(JSONObject(v1Json))
        val cal = JoyCalibration(spec, "phone", v1, JoyCalibration.V2_STEPS)
        assertEquals("clicks", cal.step); assertEquals("recording", cal.state)
        assertEquals(JoyCalibration.V2_STEPS, cal.status(true)["steps"]); assertEquals(JoyCalibration.V2_STEPS, cal.remaining)
        assertEquals(emptyList<String>(), cal.status(true)["skipped"])
        // the stream has run 22 s before the start (the golden's pops ended at 22140): the first tick times the step
        feed(cal, case("setup"), 22140.0)
        assertEquals("done", cal.state)
        assertEquals(JoyCalibration.V2_STEPS, cal.finished.toList())
        val p = JoyProfile.fromJson(JSONObject(cal.draft.copy(savedAtMs = 9).toJson().toString()))
        assertEquals(2, p.loadedVersion); assertEquals(emptyList<String>(), p.missingSteps); assertFalse(p.needsRecalibration)
        assertEquals(11.06, p.homeSt!!, 0.0); assertEquals(10.06, p.loSt!!, 0.0); assertEquals(20.95, p.hiSt!!, 0.0)
        assertEquals(15.2, p.pop!!["peak_db"]!!.toDouble(), 0.0)
        assertEquals(listOf("vowels"), p.skipped)                    // outside the run: its saved skip state stays
        assertEquals(3, p.clicksExamples!!.size); assertEquals(2, p.hissExamples!!.size)
        assertTrue(p.whistle != null && p.room != null)
        assertEquals("calibration", p.gate(spec).from)
    }

    /** A requested step skipped earlier is recorded again: the draft starts without its skip; the save merges. */
    @Test fun requestedStepsStartUnskipped() {
        val v1 = JoyProfile.fromJson(JSONObject(v1Json)).copy(skipped = listOf("vowels", "whistle"))
        val cal = JoyCalibration(spec, "phone", v1, listOf("whistle", "room"))
        assertEquals(listOf("vowels"), cal.draft.skipped)
        assertEquals(emptyList<String>(), cal.status(true)["skipped"])
        try { JoyCalibration(spec, "phone", v1, listOf("clicks", "nope")); throw AssertionError("an unknown step") } catch (_: IllegalArgumentException) {}
        try { JoyCalibration(spec, "phone", v1, emptyList()); throw AssertionError("no steps") } catch (_: IllegalArgumentException) {}
        try { JoyCalibration(spec, "phone", v1, listOf("room", "room")); throw AssertionError("a repeat") } catch (_: IllegalArgumentException) {}
    }

    /** Skip on the run's last step: done, never a wrap round to an unfinished step, nor a step outside the run. */
    @Test fun skipOnTheLastStepIsDone() {
        val cal = JoyCalibration(spec, "phone", null, listOf("hiss", "room"))
        assertEquals("hiss", cal.step)
        cal.skip(0.0)
        assertEquals("room", cal.step); assertEquals("recording", cal.state)
        cal.skip(0.0)
        assertEquals("done", cal.state); assertEquals("room", cal.step)
        assertEquals(listOf("hiss", "room"), cal.status(false)["skipped"])
        assertEquals(emptyList<String>(), cal.remaining)
        // the full run: skip the last step while an earlier one is still open (the UI jumped ahead): no wrap
        val full = JoyCalibration(spec, "phone")
        full.startStep("room", 0.0)
        full.skip(0.0)
        assertEquals("room", full.step); assertEquals("step_done", full.state)
        assertEquals(JoyCalibration.STEPS.dropLast(1), full.remaining)
    }

    /** calib_step for the step already recording keeps what it heard; a redo (force) starts it over. */
    @Test fun stepWhileRecordingIsNoOp() {
        val v1 = JoyProfile.fromJson(JSONObject(v1Json))
        val cal = JoyCalibration(spec, "phone", v1, JoyCalibration.V2_STEPS)
        val c = case("setup")
        val shift = 41400.0 - 22140.0
        cal.startStep("clicks", 22140.0 + shift, force = true)
        fun clicksN() = (cal.status(false)["heard"] as Map<*, *>)["clicks_n"] as Int
        // feed the golden clicks one tick at a time until the first is heard
        val ts = ticks(c).map { it.tMs }.filter { it > 22140.0 && it <= 26620.0 }
        var at = 22140.0
        for (t in ts) { feed(cal, c, at, t, shift); at = t; if (clicksN() > 0) break }
        assertEquals("clicks", cal.step); assertEquals("recording", cal.state)
        val heard = clicksN()
        assertTrue(heard > 0)
        cal.startStep("clicks", at + shift)
        assertEquals(heard, clicksN())
        cal.startStep("clicks", at + shift, force = true)
        assertEquals(0, clicksN())
    }

    /** A redo from the result returns to done after the redone step (measured or skipped), starting nothing else. */
    @Test fun redoReturnsToDone() {
        val v1 = JoyProfile.fromJson(JSONObject(v1Json))
        val cal = JoyCalibration(spec, "phone", v1, JoyCalibration.V2_STEPS)
        val c = case("setup")
        feed(cal, c, 22140.0)
        assertEquals("done", cal.state)
        // redo the clicks with the golden's clicks again (the stream clock goes on: the same ticks, shifted past its end)
        val shift = 41400.0 - 22140.0
        cal.startStep("clicks", 22140.0 + shift)
        assertEquals("clicks", cal.step); assertEquals("recording", cal.state)
        feed(cal, c, 22140.0, 26620.0 + 200.0, shift)
        assertEquals("done", cal.state); assertEquals("clicks", cal.step)
        assertEquals(3, cal.draft.clicksExamples!!.size)
        // a redo that is skipped: done too, nothing else starts
        cal.startStep("whistle", 60000.0)
        cal.skip(60000.0)
        assertEquals("done", cal.state); assertEquals("whistle", cal.step)
        assertEquals(listOf("whistle"), cal.status(false)["skipped"])
        // a redo of a step outside the run joins it
        cal.startStep("hum", 60000.0)
        assertEquals(JoyCalibration.V2_STEPS + "hum", cal.steps)
        cal.skip(60000.0)
        assertEquals("done", cal.state)
    }

    @Test fun steadyMatchesPrototype() {
        val xs = listOf(10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 12.0, Double.NaN, 11.0, 11.1)
        assertEquals(xs.take(8), JoyCalibration.steady(xs))
        assertEquals(emptyList<Double>(), JoyCalibration.steady(xs.take(7)))
    }

    /** The service's SharedPreferences for [CalibSaves]: a map; [puts] counts the commits. */
    private class MapPrefs : CalibPrefs {
        val m = mutableMapOf<String, String>()
        var puts = 0
        override fun get(key: String) = m[key]
        override fun put(entries: Map<String, String?>) { puts++; entries.forEach { (k, v) -> if (v == null) m.remove(k) else m[k] = v } }
    }

    private fun savedProfile(p: MapPrefs, src: String = "phone") = JoyProfile.fromJson(JSONObject(p.m["calib_$src"]!!))
    private fun savedDone(p: MapPrefs, src: String = "phone") = CalibProgress.doneStepsOf(JSONObject(p.m["calib_progress_$src"]!!))

    /** E9 contract C: each step is saved on its own as it finishes; a cancel (the service just drops the run: the
     *  BackgroundGuard, UiBridge.close, idle, calib_cancel) keeps them, and a new service (restart / app kill) resumes
     *  at the first undone step. */
    @Test fun perStepSaveKeepsFinishedStepsAcrossACancelAndResume() {
        val c = case("setup")
        val prefs = MapPrefs()
        val saves = CalibSaves(prefs)
        val cal = saves.start(spec, "phone", null, null, 1_000)
        assertFalse(saves.resumed); assertEquals(JoyCalibration.STEPS, cal.steps)
        assertFalse(saves.check(cal, 1_000))                          // nothing finished: no write
        // hum finishes (the golden's home ends at 4800 ms): saved at once, before glide even starts
        feed(cal, c, 0.0, 4800.0)
        assertTrue(saves.check(cal, 2_000))
        assertEquals(listOf("hum"), savedDone(prefs))
        assertEquals(cal.draft.homeSt, savedProfile(prefs).homeSt); assertNull(savedProfile(prefs).loSt)
        assertFalse(savedProfile(prefs).complete)
        // glide (ends at 10600 ms)
        feed(cal, c, 4800.0, 10600.0)
        assertTrue(saves.check(cal, 3_000))
        assertEquals(listOf("hum", "glide"), savedDone(prefs))
        val home = cal.draft.homeSt; val lo = cal.draft.loSt
        assertTrue(home != null && lo != null && savedProfile(prefs).loSt == lo)
        // vowels starts, then the run is cancelled mid-step (nothing more is written) and the service restarts
        feed(cal, c, 10600.0, 11000.0)
        assertEquals("vowels", cal.step); assertFalse(saves.check(cal, 3_500))
        val saves2 = CalibSaves(prefs)
        assertEquals(mapOf("step" to "vowels", "done_steps" to listOf("hum", "glide")), saves2.resume("phone"))
        // calib_start (resume by default: the progress is < 24 h old) picks up at vowels with hum + glide kept
        val again = saves2.start(spec, "phone", null, null, 4_000)
        assertTrue(saves2.resumed)
        assertEquals("vowels", again.step); assertEquals(listOf("vowels", "clicks", "whistle", "hiss", "room"), again.steps)
        assertEquals(home, again.draft.homeSt); assertEquals(lo, again.draft.loSt)
        // an old progress (> 24 h) does not resume by itself, but {resume: true} still does
        assertFalse(CalibSaves(prefs).let { it.start(spec, "phone", null, null, 3_000 + CalibProgress.FRESH_MS + 1); it.resumed })
        assertTrue(CalibSaves(prefs).let { it.start(spec, "phone", null, true, 3_000 + CalibProgress.FRESH_MS + 1); it.resumed })
        assertFalse(CalibSaves(prefs).let { it.start(spec, "phone", null, false, 4_000); it.resumed })
    }

    /** A recalibration over a complete profile: done_steps are the steps THIS run finished (not every step the old
     *  profile has), calib_save clears the progress, and the next calib_start is a full run (never refused). */
    @Test fun recalibrationProgressAndSaveClearIt() {
        val c = case("setup")
        val prefs = MapPrefs()
        val first = CalibSaves(prefs)
        val cal = first.start(spec, "phone", null, null, 1_000)
        feed(cal, c, 0.0)                                              // the whole golden run (room fails, skipped)
        if (cal.state == "failed") cal.skip()
        assertEquals("done", cal.state)
        first.check(cal, 2_000)
        first.complete(cal, 2_000)
        assertTrue(savedProfile(prefs).complete); assertNull(prefs.m["calib_progress_phone"]); assertNull(first.resume("phone"))
        // recalibrate: the next start is a full run (not "every step is recorded"), and after hum the resume is glide
        val saves = CalibSaves(prefs)
        val re = saves.start(spec, "phone", null, null, 3_000)
        assertFalse(saves.resumed); assertEquals("hum", re.step)
        feed(re, c, 0.0, 4800.0)
        saves.check(re, 4_000)
        assertEquals(listOf("hum"), savedDone(prefs))
        assertEquals("glide", saves.resume("phone")!!["step"])
        assertFalse(savedProfile(prefs).complete)
        assertTrue(savedProfile(prefs).room != null || "room" in savedProfile(prefs).skipped)   // the old values stay
    }

    /** A redo of a finished step (calib_redo / the arrows back) is saved again when it finishes. */
    @Test fun aRedoneStepIsSavedAgain() {
        val c = case("setup")
        val prefs = MapPrefs()
        val saves = CalibSaves(prefs)
        val cal = saves.start(spec, "phone", listOf("hum"), null, 1_000)
        feed(cal, c, 0.0, 4800.0)
        assertTrue(saves.check(cal, 2_000)); val n = prefs.puts
        cal.startStep("hum", 4800.0, force = true)
        feed(cal, c, 0.0, 4800.0, shift = 4800.0)                      // the same hum again, later on the clock
        assertEquals("done", cal.state)
        assertTrue(saves.check(cal, 3_000)); assertEquals(n + 1, prefs.puts)
    }

    /** The phone's existing prefs: a version 1 profile and no progress still load; nothing resumes; a damaged progress
     *  entry reads as none. */
    @Test fun existingSavedProfileMigrates() {
        val prefs = MapPrefs()
        prefs.m["calib_phone"] = v1Json
        val saves = CalibSaves(prefs)
        assertNotNull(saves.load("phone")); assertFalse(saves.load("phone")!!.complete)
        assertNull(saves.resume("phone"))
        val cal = saves.start(spec, "phone", null, null, 1_000)
        assertFalse(saves.resumed); assertEquals("hum", cal.step)
        prefs.m["calib_progress_phone"] = "{not json"
        assertNull(CalibSaves(prefs).resume("phone"))
        prefs.m["calib_progress_phone"] = """{"done_steps": ["hum", 3, "bogus"], "updated_ms": 1}"""
        assertEquals(listOf("hum"), CalibSaves(prefs).progress("phone").let { CalibProgress.doneStepsOf(it) })
    }

    /** E9 contract C: calib_step mid-take drops only the in-flight step (a saved step stays). */
    @Test fun calibStepMidTakeDropsTheInFlightStep() {
        val c = case("setup")
        val prefs = MapPrefs()
        val saves = CalibSaves(prefs)
        val cal = saves.start(spec, "phone", null, null, 1_000)
        feed(cal, c, 0.0, 4800.0); saves.check(cal, 2_000)             // hum saved
        cal.startStep("clicks", 22140.0)
        assertEquals("recording", cal.state)
        feed(cal, c, 22140.0, 24000.0)                                  // a couple of seconds into the clicks window
        assertEquals("clicks", cal.step)
        cal.startStep("whistle", 24000.0)                               // the arrows: jump mid-take
        assertEquals("whistle", cal.step); assertEquals("waiting", cal.state)
        assertEquals(setOf("hum"), cal.finished)
        assertFalse(saves.check(cal, 3_000)); assertEquals(listOf("hum"), savedDone(prefs))
        // the status: the whistle glide's expected shape (an arch, up and back) and this step's own live trace
        val s = cal.status(false)
        assertEquals("whistle", s["step"]); assertEquals(listOf("arch"), (s["expect"] as Map<*, *>)["sequence"])
        assertEquals(emptyList<Any?>(), (s["live"] as Map<*, *>)["trace_hz"])
        assertEquals(mapOf("i" to 5, "n" to 7), s["pos"])
    }

    // --- the pops step is gone (2026-09-28) ---------------------------------------------------------------------------

    @Test fun sevenStepsAndCanonicalNames() {
        assertEquals(listOf("hum", "glide", "vowels", "clicks", "whistle", "hiss", "room"), JoyCalibration.STEPS)
        assertEquals("clicks", JoyCalibration.canonical("pops"))
        assertEquals("hiss", JoyCalibration.canonical("hiss"))
        val cal = JoyCalibration(spec, "phone")
        val s = cal.status(false)
        assertEquals(mapOf("i" to 1, "n" to 7), s["pos"])
        assertEquals(7, (s["hub"] as List<*>).size)
    }

    @Test fun legacyPopsStepNameFoldsToClicks() {
        val cal = JoyCalibration(spec, "phone")
        cal.startStep("pops")
        assertEquals("clicks", cal.step); assertEquals("recording", cal.state)
        assertEquals(listOf("clicks", "hiss"), JoyCalibration(spec, "phone", null, listOf("pops", "hiss")).steps)
        assertEquals(listOf("clicks"), JoyCalibration(spec, "phone", null, listOf("pops", "clicks")).steps)
    }

    @Test fun deriveRetiresTheClickPopRule() {
        val c = case("setup")
        fun exs(k: String) = SoundExample.listFrom(c.getJSONArray(k))!!
        assertNotNull(CalibV2.deriveClickPop(exs("pops_examples"), exs("clicks_examples"), spec))   // they separate
        val base = JoyProfile("phone", popsExamples = exs("pops_examples"), clicksExamples = exs("clicks_examples"))
        val cal = JoyCalibration(spec, "phone", base, listOf("clicks"))
        cal.skip(0.0)   // derive() runs on a skip of clicks
        assertNull(cal.draft.clickPop)   // the relabel is retired even when the examples separate
    }

    @Test fun oldPopsProgressResumesAtClicks() {
        val prefs = MapPrefs()
        prefs.m["calib_progress_phone"] = """{"done_steps":["hum","glide","vowels","pops"],"current":"pops","updated_ms":999}"""
        val saves = CalibSaves(prefs)
        val cal = saves.start(spec, "phone", null, null, 1_000)
        assertTrue(saves.resumed)
        assertEquals("clicks", cal.step); assertEquals(listOf("clicks", "whistle", "hiss", "room"), cal.steps)
        assertEquals(mapOf("step" to "clicks", "done_steps" to listOf("hum", "glide", "vowels")), saves.resume("phone"))
    }

    @Test fun oldPopsProgressWithClicksDoneResumesAtWhistle() {
        val prefs = MapPrefs()
        prefs.m["calib_progress_phone"] = """{"done_steps":["hum","glide","vowels","pops","clicks"],"current":"clicks","updated_ms":999}"""
        val saves = CalibSaves(prefs)
        val cal = saves.start(spec, "phone", null, null, 1_000)
        assertTrue(saves.resumed)
        assertEquals("whistle", cal.step); assertEquals(listOf("whistle", "hiss", "room"), cal.steps)
    }

    @Test fun oldV2ProfileWithLegacyPopsFieldsStillLoads() {
        val j = JSONObject("""
            {"source":"phone","version":2,"saved_at_ms":5,"complete":true,
             "home_hz":99.0,"range_lo_hz":98.0,"range_hi_hz":184.0,"voicing_threshold":0.8,
             "vowels":{"ee":{"acc":1.0},"ah":{"acc":1.0},"oo":{"acc":1.0}},
             "pops_heard":3,"skipped":["pops"],"extractor":{},
             "home_st":11.06,"clarity_on":0.8,"lo_st":10.06,"hi_st":20.95,
             "vowel_centroids_bark":{"ee":[9.0,2.0],"ah":[8.0,1.5],"oo":[7.0,1.0]},
             "vowel_dead_zone":null,"vowel_full":null,"vowel_report":null,
             "pop":{"peak_db":15.2,"rise_db":12.0,"core_ticks":3},"pop_labels":["pop"],
             "pops_examples":[{"label":"pop","dur_ms":110.0,"snr_db":8.0,"level_db":-40.0,"lf_ratio":0.26,"peak_centroid_hz":850.0},
                              {"label":"pop","dur_ms":120.0,"snr_db":9.0,"level_db":-39.0,"lf_ratio":0.3,"peak_centroid_hz":900.0}],
             "clicks_examples":[{"label":"click","dur_ms":40.0,"snr_db":20.3,"level_db":-31.2,"lf_ratio":0.02,"peak_centroid_hz":3600.0},
                                {"label":"click","dur_ms":40.0,"snr_db":18.1,"level_db":-33.0,"lf_ratio":0.02,"peak_centroid_hz":3600.0}],
             "hiss_examples":[{"label":"hiss","dur_ms":150.0,"snr_db":25.0,"level_db":-25.1,"lf_ratio":0.04,"peak_centroid_hz":4300.0}],
             "whistle":{"lo_st":50.79,"hi_st":61.61,"home_st":56.2,"split_st":35.87},
             "room":{"floor_dbfs":-60.05,"transient_snr_db":9.2,"transient_level_dbfs":-50.3,"transients":1},
             "click_pop":{"features":{"snr_db":{"thr":29.25,"pop_above":true}},"min_votes":2}}
        """.trimIndent())
        val p = JoyProfile.fromJson(j)
        assertFalse("pops" in p.missingSteps)
        assertFalse(p.needsRecalibration)
        assertEquals(15.2, p.pop!!["peak_db"]!!.toDouble(), 0.0)
        assertEquals(3, p.popsHeard)
        assertEquals(2, p.popsExamples!!.size)
        assertNotNull(p.clickPop)
        // the legacy fields round-trip
        val q = JoyProfile.fromJson(JSONObject(p.toJson().toString()))
        assertEquals(p.pop, q.pop); assertEquals(p.popsExamples, q.popsExamples); assertEquals(p.popsHeard, q.popsHeard)
        assertEquals(p.clickPop, q.clickPop)
        // the pops examples still feed the level gate
        assertEquals(CalibV2.deriveGate(p.popsExamples, p.clicksExamples, p.hissExamples, p.room, spec), p.gate(spec))
        assertNotEquals(CalibV2.deriveGate(null, p.clicksExamples, p.hissExamples, p.room, spec), p.gate(spec))
    }

    // --- calib_delete / calib_undelete (range-calibdel-k) ------------------------------------------------------------

    /** The step's measured fields are equal between two profiles (the arrays by content). */
    private fun assertSameFields(a: JoyProfile, b: JoyProfile, step: String) {
        when (step) {
            "hum" -> { assertEquals(a.homeSt, b.homeSt); assertEquals(a.clarityOn, b.clarityOn) }
            "glide" -> { assertEquals(a.loSt, b.loSt); assertEquals(a.hiSt, b.hiSt) }
            "vowels" -> {
                val ac = a.centroids
                if (ac == null) assertNull(b.centroids) else {
                    assertNotNull(b.centroids); assertEquals(ac.keys, b.centroids!!.keys)
                    ac.forEach { (k, v) -> assertTrue("centroids[$k]", b.centroids!![k]!!.contentEquals(v)) }
                }
                assertEquals(a.vowelDeadZone, b.vowelDeadZone); assertEquals(a.vowelFull, b.vowelFull); assertEquals(a.vowelReport, b.vowelReport)
            }
            "clicks" -> assertEquals(a.clicksExamples, b.clicksExamples)
            "whistle" -> assertEquals(a.whistle, b.whistle)
            "hiss" -> assertEquals(a.hissExamples, b.hissExamples)
            "room" -> assertEquals(a.room, b.room)
        }
    }

    @Test fun calibDeleteClearsEachStepAndKeepsTheOthersByteIdentical() {
        val c = case("setup")
        val prefs = MapPrefs()
        val saves = CalibSaves(prefs)
        val cal = saves.start(spec, "phone", null, null, 1_000)
        feed(cal, c, 0.0); if (cal.state == "failed") cal.skip()
        saves.complete(cal, 2_000)
        val full = savedProfile(prefs)
        val fullJson = full.toJson().toString()
        for (step in JoyCalibration.STEPS) {
            prefs.m["calib_phone"] = fullJson; prefs.m.remove("calib_progress_phone"); prefs.m.remove("calib_trash_phone")
            saves.delete("phone", step, spec, 3_000L)
            val after = savedProfile(prefs)
            assertTrue("$step missing", step in after.missingSteps)         // not done
            assertFalse("$step skipped", step in after.skipped)             // and removed from skipped if it was there
            assertTrue("$step needs recalibration", after.needsRecalibration)
            for (other in JoyCalibration.STEPS) if (other != step) assertSameFields(full, after, other)
        }
    }

    @Test fun calibDeleteRederivesTheGateAndRewritesTheProgress() {
        val c = case("setup")
        val prefs = MapPrefs()
        val saves = CalibSaves(prefs)
        val cal = saves.start(spec, "phone", null, null, 1_000)
        feed(cal, c, 0.0); if (cal.state == "failed") cal.skip()
        saves.complete(cal, 2_000)
        val before = savedProfile(prefs)
        assertNotNull(before.levelGate)
        saves.delete("phone", "clicks", spec, 3_000L)
        val after = savedProfile(prefs)
        // the gate is derived again from the examples left (clicks gone), not the saved value
        assertEquals(CalibV2.deriveGate(after.popsExamples, null, after.hissExamples, after.room, spec), after.levelGate)
        assertNotEquals(before.levelGate, after.levelGate)
        // a complete profile had no progress: the delete writes one with every other finished step
        assertEquals(listOf("hum", "glide", "vowels", "whistle", "hiss", "room"), savedDone(prefs))
        assertEquals(mapOf("step" to "clicks", "done_steps" to listOf("hum", "glide", "vowels", "whistle", "hiss", "room")), saves.resume("phone"))
    }

    @Test fun calibUndoRestoresTheProfileAndProgress() {
        val c = case("setup")
        val prefs = MapPrefs()
        val saves = CalibSaves(prefs)
        val cal = saves.start(spec, "phone", null, null, 1_000)
        feed(cal, c, 0.0); if (cal.state == "failed") cal.skip()
        saves.complete(cal, 2_000)
        val full = savedProfile(prefs)
        saves.delete("phone", "clicks", spec, 3_000L)
        assertNull(savedProfile(prefs).clicksExamples)
        val restored = saves.undelete("phone")
        assertEquals(full.savedAtMs, restored.savedAtMs); assertTrue(restored.complete)
        assertEquals(full.levelGate, restored.levelGate); assertEquals(full.skipped, restored.skipped)
        for (step in JoyCalibration.STEPS) assertSameFields(full, restored, step)
        assertNull(prefs.m["calib_trash_phone"])          // the stash goes
        assertNull(prefs.m["calib_progress_phone"])       // the complete profile's (absent) progress stays absent
    }

    @Test fun calibUndeleteRefusedAfterANewSave() {
        val c = case("setup")
        val prefs = MapPrefs()
        val saves = CalibSaves(prefs)
        val cal = saves.start(spec, "phone", null, null, 1_000)
        feed(cal, c, 0.0); if (cal.state == "failed") cal.skip()
        saves.complete(cal, 2_000)
        saves.delete("phone", "clicks", spec, 3_000L)
        // the saved profile is written again after the delete (a new save) with a later saved_at_ms
        val cur = savedProfile(prefs)
        prefs.m["calib_phone"] = cur.copy(savedAtMs = 4_000L).toJson().toString()
        val e = assertThrows(IllegalArgumentException::class.java) { saves.undelete("phone") }
        assertEquals("calibrated again since", e.message)
        // and a new calib_start clears the stash outright
        prefs.m["calib_phone"] = cur.copy(savedAtMs = 3_000L).toJson().toString()
        saves.start(spec, "phone", null, null, 5_000L)
        assertNull(prefs.m["calib_trash_phone"])
        val e2 = assertThrows(IllegalArgumentException::class.java) { saves.undelete("phone") }
        assertEquals("nothing to undelete for phone", e2.message)
    }
}
