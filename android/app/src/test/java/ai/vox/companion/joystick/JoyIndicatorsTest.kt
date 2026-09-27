package ai.vox.companion.joystick

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** The indicator rules against extractor/joystick_ind.py (golden from android/tools/gen_joystick_cursor.py), and Face
 *  A's state names against the badge manifest. */
class JoyIndicatorsTest {
    private val g = JSONObject(javaClass.classLoader!!.getResource("joystick_ind_golden.json")!!.readText())
    private val spec = JoySpec.parse(File("src/main/assets/joystick_v1.json").readText())

    @Test fun heading() {
        val a = g.getJSONArray("headings")
        for (i in 0 until a.length()) a.getJSONArray(i).let {
            assertEquals("$it", it.getString(2), JoyIndicators.heading(it.getDouble(0), it.getDouble(1)))
        }
    }

    @Test fun chevrons() {
        val a = g.getJSONArray("chevrons")
        for (i in 0 until a.length()) a.getJSONArray(i).let {
            assertEquals("$it", it.getInt(1), JoyIndicators.chevrons(it.getDouble(0), spec.startDpS, spec.maxDpS))
        }
    }

    @Test fun barStep() {
        val a = g.getJSONArray("bars")
        for (i in 0 until a.length()) a.getJSONArray(i).let {
            val py = it.get(4)
            val want = when (py) { "off" -> "upoff"; "-off" -> "downoff"; else -> (py as Number).toInt().let { n -> if (n == 0) "0" else if (n > 0) "up$n" else "down${-n}" } }
            assertEquals("$it", want, JoyIndicators.barStep(it.getDouble(0), it.getDouble(1), it.getDouble(2), it.getInt(3)))
        }
    }

    @Test fun brackets() {
        val a = g.getJSONArray("brackets")
        for (i in 0 until a.length()) {
            val c = a.getJSONObject(i)
            val b = c.getJSONArray("ltrb")
            val k = JoyIndicators.brackets(b.getInt(0), b.getInt(1), b.getInt(2), b.getInt(3), 4)
            assertEquals(c.getInt("x"), k.x); assertEquals(c.getInt("y"), k.y)
            val rows = c.getJSONArray("rows")
            assertEquals((0 until rows.length()).map { rows.getString(it) }, k.rows())
        }
    }

    @Test fun cursorArt() {
        val art = JoyIndicators.CursorArt(File("src/main/assets/joystick_cursor.json").readText())
        assertEquals(26, art.grids.size)
        assertEquals(4, art.cellPx(2.625f))
        for (d in JoyIndicators.ORDER) for (n in 1..3) assertTrue("$d-$n", "$d-$n" in art.grids)
        val plain = art.grids.getValue("plain")
        assertEquals(2 * art.r + 1, plain.w)
        assertEquals(1, plain[art.r, art.r])                     // the centre dot
    }

    @Test fun faceStatesInManifest() {
        val m = JSONObject(File("../../ui/assets/badge/canti_badge.json").readText()).getJSONObject("states")
        assertEquals(34, JoyIndicators.FACE_STATES.size)
        for (s in JoyIndicators.FACE_STATES) assertTrue(s, m.has(s))
    }

    @Test fun faceFromMover() {
        val mv = Mover(spec, 400.0, 800.0, null, 10.0 to 22.0)
        assertEquals("joy_idle", JoyIndicators.faceState(mv))
        assertEquals("plain", JoyIndicators.cursorKey(mv))
        mv.setHome(16.0)
        var t = 0.0
        repeat(40) { mv.push(Tick(t, JMath.hz(19.0), 0.95, -30.0, true, f0Raw = JMath.hz(19.0), overDb = 30.0)); t += 20 }
        assertTrue(JoyIndicators.faceState(mv), JoyIndicators.faceState(mv).startsWith("joy_up"))
        assertTrue(JoyIndicators.cursorKey(mv), JoyIndicators.cursorKey(mv).startsWith("N-"))
    }
}
