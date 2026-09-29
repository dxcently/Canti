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

    @Test fun paletteMatchesArtAndFallsBackToTheSameGeometry() {
        val art = JoyIndicators.CursorArt(File("src/main/assets/joystick_cursor.json").readText())
        val p = JoyIndicators.Palette.of(art, 2.625f)
        assertEquals(art.ink, p.ink); assertEquals(art.paper, p.paper); assertEquals(art.cellPx(2.625f), p.cellPx)
        // No art: the same navy/mint and the same cell size the default art would use, so the bracket geometry matches.
        for (d in listOf(1f, 1.5f, 2f, 2.625f, 3f)) {
            val fallback = JoyIndicators.Palette.of(null, d)
            assertEquals("ink @$d", JoyIndicators.Palette.DEFAULT_INK, fallback.ink)
            assertEquals("paper @$d", JoyIndicators.Palette.DEFAULT_PAPER, fallback.paper)
            assertEquals("cell @$d", art.cellPx(d), fallback.cellPx)
        }
        assertEquals(1.5238095238095237, JoyIndicators.Palette.DEFAULT_ART_PX_DP, 1e-9)
        // A non-null art never uses the defaults, even if its own art_px_dp were to differ.
        val custom = JoyIndicators.Palette.of(art, 1f)
        assertEquals(art.cellPx(1f), custom.cellPx)
    }

    @Test fun targetBracketsInkWithPaperOutlineSelectedAndPaperOnlyOtherwise() {
        // showTargets draws JoyIndicators.brackets for every candidate: value 1 (ink) and 2 (the one-cell paper
        // outline) for the selected look, and paper-only (draw 1 as paper) for the rest. The grid geometry is shared.
        val g = JoyIndicators.brackets(40, 300, 1040, 390, 4)
        assertTrue(g.rows().toString(), g.rows().any { it.contains("1") })
        assertTrue(g.rows().toString(), g.rows().any { it.contains("2") })
        // The paper outline hugs the ink: every paper cell borders an ink cell (JoyIndicators.outline's invariant).
        for (y in 0 until g.h) for (x in 0 until g.w) if (g[x, y] == 2) {
            var near = false
            for (dy in -1..1) for (dx in -1..1) {
                val xx = x + dx; val yy = y + dy
                if (xx in 0 until g.w && yy in 0 until g.h && g[xx, yy] == 1) near = true
            }
            assertTrue("($x,$y) paper cell not adjacent to ink", near)
        }
    }
}
