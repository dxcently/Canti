package ai.vox.companion.joystick

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** The calibration engine against the prototype's setup (golden "setup": all eight steps pass; "setup_fail": the glide
 *  fails and is retried, the vowels, pops, clicks and whistle fail and are skipped, the hiss fails and is retried, the
 *  room fails and is skipped), plus the command rules and the profile round trip (a version 1 profile still loads). */
class JoyCalibrationTest {
    private val golden = JSONObject(javaClass.classLoader!!.getResource("joystick_golden.json")!!.readText())
    private val spec = JoySpec.parse(File("src/main/assets/joystick_v1.json").readText())
    private val py2kt = mapOf("home" to "hum", "range" to "glide", "vowels" to "vowels", "pops" to "pops", "clicks" to "clicks",
        "whistle" to "whistle", "hiss" to "hiss", "room" to "room")

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

    /** Runs a golden setup the way the UI drives it: calib_step for the next step after each step_done, the golden's
     *  retry / skip at their times. Returns the engine and the failures seen (step, t, reason). */
    private fun run(c: JSONObject): Pair<JoyCalibration, List<Triple<String, Double, String>>> {
        val cal = JoyCalibration(spec, "phone")
        val acts = c.getJSONArray("actions").let { a -> (0 until a.length()).map { a.getJSONArray(it).let { x -> x.getDouble(0) to x.getString(1) } } }.toMutableList()
        val fails = ArrayList<Triple<String, Double, String>>()
        // the extractor's events: [delivered at, t_start, label, raw], handed over before the tick at or after delivery
        val exq = c.getJSONArray("ex_events").let { a -> (0 until a.length()).map { a.getJSONArray(it) } }.toMutableList()
        for (tk in ticks(c)) {
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
                val next = JoyCalibration.STEPS.first { it !in cal.finished }
                cal.startStep(next, tk.tMs)
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
        if (c.isNull("pop")) assertNull(p.pop)
        else {
            val g = c.getJSONObject("pop")
            assertEquals(g.getDouble("peak_db"), p.pop!!["peak_db"]!!.toDouble(), 1e-6)
            assertEquals(g.getDouble("rise_db"), p.pop!!["rise_db"]!!.toDouble(), 1e-6)
            assertEquals(g.getInt("core_ticks"), p.pop!!["core_ticks"]!!.toInt())
            val labels = c.getJSONArray("pop_labels")
            assertEquals((0 until labels.length()).map { labels.getString(it) }, p.popLabels)
        }
        val sk = c.getJSONArray("skipped")
        assertEquals("$n skipped", (0 until sk.length()).map { py2kt[sk.getString(it)] }.sortedBy { JoyCalibration.STEPS.indexOf(it) }, p.skipped)
        // calibration v2
        fun exs(k: String) = if (c.isNull(k)) null else SoundExample.listFrom(c.getJSONArray(k))
        assertEquals("$n pops examples", exs("pops_examples"), p.popsExamples)
        assertEquals("$n clicks examples", exs("clicks_examples"), p.clicksExamples)
        assertEquals("$n hiss examples", exs("hiss_examples"), p.hissExamples)
        assertEquals("$n whistle", if (c.isNull("whistle")) null else WhistleRange.fromJson(c.getJSONObject("whistle")), p.whistle)
        assertEquals("$n room", if (c.isNull("room")) null else RoomNoise.fromJson(c.getJSONObject("room")), p.room)
        val g = c.getJSONObject("level_gate")
        assertEquals("$n gate snr", g.getDouble("min_snr_db"), cal.gate.minSnrDb, 0.0)
        assertEquals("$n gate level", g.getDouble("min_level_dbfs"), cal.gate.minLevelDbfs, 0.0)
        assertEquals("$n gate from", g.getString("from"), cal.gate.from)
        assertEquals("$n gate n", g.getInt("n"), cal.gate.n)
        assertEquals("$n click / pop rule", if (c.isNull("click_pop")) null else ClickPopRule.fromJson(c.getJSONObject("click_pop")), p.clickPop)
        assertEquals("$n tick ceiling", num(c.opt("f0_max_at_end")) ?: spec.voiceTickF0MaxHz, cal.tickF0MaxHz, 0.0)
    }

    @Test fun allStepsPass() {
        val c = case("setup")
        val (cal, fails) = run(c)
        assertTrue("no failures: $fails", fails.isEmpty())
        assertEquals("done", cal.state)
        check(c, cal)
        val done = c.getJSONArray("steps_done")
        val py = (0 until done.length()).map { done.getJSONObject(it) }.filter { it.getString("step") != "cmd" }
        assertEquals(8, py.size)
        val s = cal.status(false)
        assertEquals(true, s["step_done"]); assertEquals(1.0, s["progress"])
        val r = s["result"] as JSONObject
        assertEquals(3, r.getInt("pops_heard"))
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
        val g = c.getJSONArray("fails").let { a -> (0 until a.length()).map { a.getJSONObject(it) } }
        assertEquals(g.size, fails.size)
        for ((gf, kf) in g.zip(fails)) {
            assertEquals(py2kt[gf.getString("step")], kf.first)
            assertEquals(gf.getDouble("t_ms"), kf.second, 0.0)
            assertEquals(gf.getString("why"), kf.third)
        }
        assertEquals("done", cal.state)
        check(c, cal)
        assertEquals(listOf("vowels", "pops", "clicks", "whistle", "room"), cal.draft.skipped)
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
        assertEquals("pops", cal.step)
        cal.skip(t)
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
        assertEquals(q.pop!!["peak_db"]!!.toDouble(), pd.c.peakDb, 0.0)
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
}
