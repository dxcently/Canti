package ai.vox.companion.joystick

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import kotlin.math.abs

/** The Kotlin joystick against golden traces from the Python core (android/tools/gen_joystick_golden.py; synthetic
 *  audio only). Same ticks in, same cursor / pops / clicks / setup results out. */
class JoystickParityTest {
    private val golden = JSONObject(javaClass.classLoader!!.getResource("joystick_golden.json")!!.readText())
    private val spec = JoySpec.parse(File("src/main/assets/joystick_v1.json").readText())

    private fun num(o: Any?): Double? = if (o == null || o == JSONObject.NULL) null else (o as Number).toDouble()

    private fun ticks(rows: JSONArray): List<Tick> = (0 until rows.length()).map { i ->
        val r = rows.getJSONArray(i)
        Tick(r.getDouble(0), r.getDouble(1), r.getDouble(2), r.getDouble(3), r.getInt(4) == 1,
            num(r.opt(5)) ?: Double.NaN, num(r.opt(6)) ?: Double.NaN, r.getString(7), r.getDouble(8), r.getDouble(9))
    }

    private fun near(msg: String, want: Double?, got: Double?, tol: Double = 1e-4) {
        if (want == null) { assertNull(msg, got); return }
        assertTrue("$msg: want $want got $got", got != null && abs(want - got) <= tol + 1e-6 * abs(want))
    }

    private val elements = golden.getJSONArray("elements").let { a ->
        (0 until a.length()).map { i -> a.getJSONArray(i).let { Element(it.getDouble(0), it.getDouble(1), it.getDouble(2), it.getDouble(3), it.getString(4)) } }
    }
    private val vowels = golden.getJSONObject("vowels").let { v ->
        v.keys().asSequence().associateWith { k -> v.getJSONArray(k).let { doubleArrayOf(it.getDouble(0), it.getDouble(1)) } }
    }

    @Test fun assetIsTheSpec() {
        val a = File("src/main/assets/joystick_v1.json").readText()
        val b = File("../../extractor/prompts/joystick_v1.json").readText()
        assertEquals("assets/joystick_v1.json must equal extractor/prompts/joystick_v1.json", b, a)
        assertEquals(golden.getString("spec_version"), spec.json.getString("version"))
    }

    @Test fun cases() {
        val cases = golden.getJSONArray("cases")
        for (ci in 0 until cases.length()) {
            val c = cases.getJSONObject(ci)
            val name = c.getString("name")
            val rng = c.getJSONArray("range_st")
            val w = golden.getDouble("w_dp"); val h = golden.getDouble("h_dp")
            val mv = Mover(spec, w, h, vowels, rng.getDouble(0) to rng.getDouble(1))
            mv.setMode(c.getString("mode"))
            num(c.opt("home_st"))?.let { mv.setHome(it) }
            if (c.has("whistle") && !c.isNull("whistle")) mv.setWhistle(WhistleRange.fromJson(c.getJSONObject("whistle")))
            mv.setScreen(w, h, elements)
            val pd = PopDetector(spec.pop)
            val ck = Clicker(spec.popSeqGapMs)
            val tks = ticks(c.getJSONArray("ticks"))
            val expect = c.getJSONArray("expect")
            val events = c.getJSONArray("events")
            var ei = 0
            for ((i, tk) in tks.withIndex()) {
                mv.push(tk)
                val e = expect.getJSONObject(i)
                val at = "$name tick $i (${tk.tMs} ms)"
                val pt = pd.push(tk)
                val popR = pt?.let { ck.pop(it) }
                val click = ck.poll(tk.tMs)
                for (ev in mv.events) {
                    val g = events.getJSONObject(ei++)
                    assertEquals("$at event", g.getString("ev"), ev.kind)
                    near("$at ${ev.kind} t", g.getDouble("t_ms"), ev.tMs)
                    near("$at ${ev.kind} x", g.getDouble("x"), ev.x)
                    near("$at ${ev.kind} y", g.getDouble("y"), ev.y)
                    assertEquals("$at ${ev.kind} snapped", if (g.isNull("snapped")) null else g.getInt("snapped"), ev.snapped)
                    if (ev.kind == "hum_end") {
                        near("$at dur", g.getDouble("dur_ms"), ev.durMs)
                        val s = g.getJSONArray("stop")
                        near("$at stop x", s.getDouble(0), ev.stopX); near("$at stop y", s.getDouble(1), ev.stopY)
                    }
                }
                mv.events.clear()
                near("$at x", e.getDouble("x"), mv.x)
                near("$at y", e.getDouble("y"), mv.y)
                assertEquals("$at phase", e.getString("phase"), mv.state.phase)
                assertEquals("$at snapped", if (e.isNull("snapped")) null else e.getInt("snapped"), mv.snapped)
                near("$at speed", num(e.opt("speed")) ?: 0.0, mv.state.speed)
                near("$at sm", num(e.opt("sm")), mv.state.sm)
                near("$at offset", num(e.opt("offset")), mv.state.offset)
                near("$at momentum", num(e.opt("momentum")) ?: 0.0, mv.state.momentum)
                near("$at x_vowel", num(e.opt("x_vowel")) ?: 0.0, mv.state.xVowel)
                near("$at mid", num(e.opt("mid")), mv.mid)
                assertEquals("$at band", if (e.isNull("band")) null else e.getString("band"), mv.state.band)
                near("$at pop", num(e.opt("pop")), pt)
                assertEquals("$at pop_r", if (e.isNull("pop_r")) null else e.getString("pop_r"), popR)
                assertEquals("$at click", if (e.isNull("click")) null else e.getString("click"), click)
            }
            assertEquals("$name: all events seen", events.length(), ei)
            val bursts = c.getJSONArray("bursts")
            assertEquals("$name bursts", bursts.length(), pd.bursts.size)
            for (i in 0 until bursts.length()) {
                val g = bursts.getJSONObject(i); val b = pd.bursts[i]
                near("$name burst $i t", g.getDouble("t"), b.t)
                assertEquals("$name burst $i ticks", g.getInt("ticks"), b.ticks)
                near("$name burst $i peak", g.getDouble("peak_db"), b.peakDb)
                near("$name burst $i rise", g.getDouble("rise_db"), b.riseDb)
                assertEquals("$name burst $i core", g.getInt("core"), b.core)
                assertEquals("$name burst $i pop", g.getBoolean("pop"), b.pop)
            }
        }
    }

    private fun exs(o: JSONObject, k: String): List<SoundExample>? = if (!o.has(k)) null else SoundExample.listFrom(o.getJSONArray(k))
    private fun rawOf(o: JSONObject): Map<String, Double?> = SoundExample.raw(o)

    /** Calibration v2's pure rules on the prototype's hand-made cases: the level gate, its reasons, the click / pop rule. */
    @Test fun calibV2Rules() {
        val g = golden.getJSONObject("calib_v2")
        val gates = g.getJSONArray("gates")
        for (i in 0 until gates.length()) {
            val c = gates.getJSONObject(i)
            val e = c.getJSONObject("examples")
            val room = if (c.isNull("room")) null else RoomNoise.fromJson(c.getJSONObject("room"))
            val want = c.getJSONObject("gate")
            val got = CalibV2.deriveGate(exs(e, "pops"), exs(e, "clicks"), exs(e, "hiss"), room, spec)
            val name = c.getString("name")
            assertEquals("$name snr", want.getDouble("min_snr_db"), got.minSnrDb, 0.0)
            assertEquals("$name level", want.getDouble("min_level_dbfs"), got.minLevelDbfs, 0.0)
            assertEquals("$name from", want.getString("from"), got.from)
            assertEquals("$name n", want.getInt("n"), got.n)
            assertEquals("$name weakest", num(want.opt("weakest_snr_db")), got.weakestSnrDb)
        }
        val reasons = g.getJSONArray("reasons")
        for (i in 0 until reasons.length()) {
            val c = reasons.getJSONObject(i)
            val gj = c.getJSONObject("gate")
            val gate = LevelGate(gj.getDouble("min_snr_db"), gj.getDouble("min_level_dbfs"), gj.getString("from"), gj.getInt("n"))
            val got = CalibV2.gateReason(gate, c.getString("label"), num(c.opt("snr_db")), num(c.opt("level_db")), c.getDouble("offset_db"))
            if (c.isNull("why")) { assertNull("reason $i", got); continue }
            val w = c.getJSONObject("why")
            assertEquals("below level gate", w.getString("reason"))
            assertEquals("reason $i", w.getString("reason"), got!!.reason)
            assertEquals("reason $i label", w.getString("label"), got.label)
            assertEquals("reason $i snr", w.getDouble("snr_db"), got.snrDb, 0.0)
            assertEquals("reason $i level", w.getDouble("level_dbfs"), got.levelDbfs, 0.0)
            assertEquals("reason $i min snr", w.getDouble("min_snr_db"), got.minSnrDb, 0.0)
            assertEquals("reason $i min level", w.getDouble("min_level_dbfs"), got.minLevelDbfs, 0.0)
            assertEquals("reason $i from", w.getString("from"), got.from)
        }
        val rules = g.getJSONArray("rules")
        for (i in 0 until rules.length()) {
            val c = rules.getJSONObject(i)
            val got = CalibV2.deriveClickPop(exs(c, "pops"), exs(c, "clicks"), spec)
            assertEquals(c.getString("name"), if (c.isNull("rule")) null else ClickPopRule.fromJson(c.getJSONObject("rule")), got)
        }
        val relabels = g.getJSONArray("relabels")
        for (i in 0 until relabels.length()) {
            val c = relabels.getJSONObject(i)
            val rule = ClickPopRule.fromJson(c.getJSONObject("rule"))
            val got = CalibV2.relabel(rule, c.getString("label"), rawOf(c.getJSONObject("raw")))
            if (c.isNull("out")) { assertNull("relabel $i", got); continue }
            val o = c.getJSONObject("out")
            assertEquals("relabel $i from", o.getString("from"), got!!.from)
            assertEquals("relabel $i to", o.getString("to"), got.to)
            val v = o.getJSONObject("votes")
            assertEquals("relabel $i votes", v.keys().asSequence().associateWith { v.getString(it) }, got.votes)
        }
    }

    @Test fun sliders() {
        val mv = Mover(spec, 400.0, 800.0, null, 10.0 to 22.0)
        mv.setHome(14.0)
        val f1 = mv.fullSt(false); val s1 = mv.startDpS; val m1 = mv.maxDpS
        mv.speedMul = 2.0; mv.pitchSens = 2.0
        assertEquals(s1 * 2, mv.startDpS, 1e-9)
        assertEquals(m1 * 2, mv.maxDpS, 1e-9)
        assertEquals(maxOf(spec.deadZoneSt + 0.5, f1 / 2), mv.fullSt(false), 1e-9)
        mv.pitchSens = 0.5
        assertEquals(f1 * 2, mv.fullSt(false), 1e-9)
        mv.pitchSens = 100.0
        assertEquals(spec.deadZoneSt + 0.5, mv.fullSt(false), 1e-9)
        assertEquals(spec.deadZoneSt + 0.5, mv.startFullSt, 1e-9)
    }

    @Test fun positionPersists() {
        val mv = Mover(spec, 400.0, 800.0)
        mv.moveTo(390.0, 700.0)
        mv.setScreen(800.0, 400.0, emptyList())          // rotation: clamped, not recentred
        assertEquals(390.0, mv.x, 0.0); assertEquals(400.0, mv.y, 0.0)
        mv.enabled = false; mv.enabled = true
        assertEquals(390.0, mv.x, 0.0)
        mv.recentre()
        assertEquals(400.0, mv.x, 0.0); assertEquals(200.0, mv.y, 0.0)
    }
}
