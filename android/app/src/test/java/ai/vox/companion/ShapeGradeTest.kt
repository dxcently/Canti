package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** [ShapeGrade]: the tolerant grade (E9 contract A). Each check's ok/near/miss boundary, the tone near band at
 *  600 Hz, discrete count/gap, no-scale -> pending, and the live pending rules. */
class ShapeGradeTest {

    // --- fixtures ------------------------------------------------------------------------------------------------------

    /** A monotonic 16-point track from [a] to [b]. */
    private fun track(a: Double, b: Double): DoubleArray = DoubleArray(16) { i -> a + (b - a) * i / 15.0 }
    private val rise = track(0.0, 6.0)
    private val fall = track(6.0, 0.0)
    private val flat = track(0.0, 0.0)

    /** An arch: up then down; [peak] is the height above both ends. */
    private fun arch(peak: Double): DoubleArray = DoubleArray(16) { i -> (if (i < 8) peak * i / 8 else peak * (15 - i) / 7).coerceAtLeast(0.0) }
    /** A dip: down then up; [depth] below both ends. */
    private fun dip(depth: Double): DoubleArray = DoubleArray(16) { i -> (if (i < 8) -depth * i / 8 else -depth * (15 - i) / 7).coerceAtMost(0.0) }

    private fun want(g: String, start: String = "low", speed: String? = null, tone: String = "hum", gapS: Double? = null) =
        ShapeGrade.Want(listOf(g), start, speed, tone, gapS)

    private fun heard(g: String = "heard", f0: Double? = 180.0, startHz: Double? = 120.0, dur: Long? = 500,
                      pitch: DoubleArray = rise, gated: Boolean = false) =
        ShapeGrade.Heard(listOf(g), pitch.toList(), f0, startHz, dur, gated = gated)

    private fun scale(lo: Double = 100.0, home: Double = 180.0, hi: Double = 400.0) =
        ShapeGrade.Scale(lo, home, hi)

    private fun checks(want: ShapeGrade.Want, h: ShapeGrade.Heard, s: ShapeGrade.Scale? = null): Map<String, ShapeGrade.Check> =
        ShapeGrade.grade(want, h, s).associateBy { it.id }

    private fun state(id: String, want: ShapeGrade.Want, h: ShapeGrade.Heard, s: ShapeGrade.Scale? = null) =
        checks(want, h, s)[id]?.state

    // --- pitch --------------------------------------------------------------------------------------------------------

    @Test fun pitchLowHighHomeBoundaries() {
        // home = 180 Hz (~20.5 st). Offsets in st: +1 st ~190.7 Hz, +3 st ~214 Hz, -1 st ~170 Hz, -3 st ~151 Hz.
        // low mark = home-2 st: ok at/below home+1 st, near to home+3 st, miss above
        assertEquals("ok", state("PITCH", want("rise", "low"), heard(startHz = 180.0), scale()))       // 0 st = home -> ok (<= +1)
        assertEquals("ok", state("PITCH", want("rise", "low"), heard(startHz = 100.0), scale()))       // well below -> ok
        assertEquals("near", state("PITCH", want("rise", "low"), heard(startHz = 205.0), scale()))      // ~+2.3 st -> near
        assertEquals("miss", state("PITCH", want("rise", "low"), heard(startHz = 230.0), scale()))      // ~+4.2 st -> miss
        // high mark = home+2 st: ok at/above home-1 st
        assertEquals("ok", state("PITCH", want("rise", "high"), heard(startHz = 180.0), scale()))       // 0 st -> ok (>= -1)
        assertEquals("ok", state("PITCH", want("rise", "high"), heard(startHz = 400.0), scale()))
        assertEquals("near", state("PITCH", want("rise", "high"), heard(startHz = 160.0), scale()))    // ~-2.0 st -> near
        assertEquals("miss", state("PITCH", want("rise", "high"), heard(startHz = 130.0), scale()))    // ~-5.6 st -> miss
        // home mark: within 3 st ok, within 5 st near
        assertEquals("ok", state("PITCH", want("rise", "home"), heard(startHz = 180.0), scale()))
        assertEquals("near", state("PITCH", want("rise", "home"), heard(startHz = 220.0), scale()))    // ~+3.5 st -> near
        assertEquals("miss", state("PITCH", want("rise", "home"), heard(startHz = 250.0), scale()))    // ~+5.7 st -> miss
    }

    @Test fun pitchNoScaleIsPending() {
        assertEquals("pending", state("PITCH", want("rise", "low"), heard(startHz = 180.0), null))
        // a discrete gesture has no pitch check at all
        assertNull(state("PITCH", want("pop", "none", tone = "any"), heard("pop", f0 = null, pitch = DoubleArray(0))))
    }

    // --- shape --------------------------------------------------------------------------------------------------------

    @Test fun shapeRiseFallBoundaries() {
        assertEquals("ok", state("SHAPE", want("rise"), heard(pitch = track(0.0, 0.7))))      // net +0.7 -> ok
        assertEquals("near", state("SHAPE", want("rise"), heard(pitch = track(0.0, 0.5))))    // net +0.5 -> near
        assertEquals("miss", state("SHAPE", want("rise"), heard(pitch = track(0.0, 0.3))))    // net +0.3 -> miss
        assertEquals("miss", state("SHAPE", want("rise"), heard(pitch = fall)))               // down -> miss
        assertEquals("ok", state("SHAPE", want("fall"), heard(pitch = track(0.0, -0.7))))     // net -0.7 -> ok
        assertEquals("near", state("SHAPE", want("fall"), heard(pitch = track(0.0, -0.5))))
        assertEquals("miss", state("SHAPE", want("fall"), heard(pitch = track(0.0, -0.3))))
        assertEquals("miss", state("SHAPE", want("fall"), heard(pitch = rise)))
    }

    @Test fun shapeArchDipFlatBoundaries() {
        assertEquals("ok", state("SHAPE", want("arch"), heard(pitch = arch(0.7))))
        assertEquals("near", state("SHAPE", want("arch"), heard(pitch = arch(0.5))))
        assertEquals("miss", state("SHAPE", want("arch"), heard(pitch = arch(0.3))))
        assertEquals("ok", state("SHAPE", want("dip"), heard(pitch = dip(0.7))))
        assertEquals("near", state("SHAPE", want("dip"), heard(pitch = dip(0.5))))
        assertEquals("miss", state("SHAPE", want("dip"), heard(pitch = dip(0.3))))
        // flat: range <= 2.0 ok, <= 3.0 near, else miss
        assertEquals("ok", state("SHAPE", want("flat"), heard(pitch = track(0.0, 2.0))))
        assertEquals("near", state("SHAPE", want("flat"), heard(pitch = track(0.0, 2.5))))
        assertEquals("miss", state("SHAPE", want("flat"), heard(pitch = track(0.0, 3.5))))
    }

    @Test fun shapeDiscreteIsTheLabelFamily() {
        assertEquals("ok", state("SHAPE", want("pop", "none", tone = "any"), heard("pop", f0 = null, pitch = DoubleArray(0))))
        assertEquals("miss", state("SHAPE", want("pop", "none", tone = "any"), heard("click", f0 = null, pitch = DoubleArray(0))))
    }

    // --- length -------------------------------------------------------------------------------------------------------

    @Test fun lengthQuickSlowUntagged() {
        assertEquals("ok", state("LENGTH", want("rise", speed = "quick"), heard(dur = 1000)))
        assertEquals("near", state("LENGTH", want("rise", speed = "quick"), heard(dur = 1200)))
        assertEquals("miss", state("LENGTH", want("rise", speed = "quick"), heard(dur = 1500)))
        assertEquals("ok", state("LENGTH", want("rise", speed = "slow"), heard(dur = 800)))
        assertEquals("near", state("LENGTH", want("rise", speed = "slow"), heard(dur = 700)))
        assertEquals("miss", state("LENGTH", want("rise", speed = "slow"), heard(dur = 500)))
        assertEquals("ok", state("LENGTH", want("rise", speed = null), heard(dur = 500)))
        assertEquals("ok", state("LENGTH", want("rise", speed = null), heard(dur = 2500)))
        assertEquals("near", state("LENGTH", want("rise", speed = null), heard(dur = 100)))   // too short -> near
        assertEquals("near", state("LENGTH", want("rise", speed = null), heard(dur = 3000)))
        assertEquals("miss", state("LENGTH", want("rise", speed = null), heard(dur = 4500)))
    }

    // --- sound --------------------------------------------------------------------------------------------------------

    @Test fun soundHumWhistleNearBandAt600() {
        assertEquals("ok", state("SOUND", want("rise", tone = "hum"), heard(f0 = 100.0)))
        assertEquals("near", state("SOUND", want("rise", tone = "hum"), heard(f0 = 560.0)))    // within 10% of 600
        assertEquals("miss", state("SOUND", want("rise", tone = "hum"), heard(f0 = 700.0)))
        assertEquals("ok", state("SOUND", want("rise", tone = "whistle"), heard(f0 = 1200.0)))
        assertEquals("near", state("SOUND", want("rise", tone = "whistle"), heard(f0 = 640.0)))
        assertEquals("miss", state("SOUND", want("rise", tone = "whistle"), heard(f0 = 500.0)))
        // no clear pitch on a pitched gesture: miss
        assertEquals("miss", state("SOUND", want("rise", tone = "hum"), heard(f0 = null)))
        // an unpitched gesture must be unpitched
        assertEquals("ok", state("SOUND", want("pop", "none", tone = "any"), heard("pop", f0 = null, pitch = DoubleArray(0))))
        assertEquals("miss", state("SOUND", want("pop", "none", tone = "any"), heard("click", f0 = 200.0, pitch = DoubleArray(0))))
        // ... unless the extractor itself called it that gesture (a hiss can carry a stray f0)
        assertEquals("ok", state("SOUND", want("hiss", "none", tone = "any"), heard("hiss", f0 = 200.0, pitch = DoubleArray(0))))
    }

    // --- loud ---------------------------------------------------------------------------------------------------------

    @Test fun loudGateAndClip() {
        assertEquals("ok", state("LOUD", want("rise"), heard()))
        assertEquals("miss", state("LOUD", want("rise"), heard(gated = true)))
    }

    // --- count / gap (combos) -----------------------------------------------------------------------------------------

    @Test fun comboCountAndGap() {
        val w = want("pop", "none", tone = "any").copy(sequence = listOf("pop", "pop"), gapS = 0.5)
        val h = heard("pop", f0 = null, pitch = DoubleArray(0)).copy(labels = listOf("pop", "pop"), gapsMs = listOf(500L))
        val c = checks(w, h)
        assertEquals("ok", c["COUNT"]?.state)
        assertEquals("ok", c["GAP"]?.state)
        // wrong count and a too-wide gap
        val h2 = h.copy(labels = listOf("pop"), gapsMs = listOf(2000L))
        val c2 = checks(w, h2)
        assertEquals("miss", c2["COUNT"]?.state)
        assertEquals("miss", c2["GAP"]?.state)
    }

    // --- pass rule ----------------------------------------------------------------------------------------------------

    @Test fun passIsNoMiss() {
        // a near on shape still passes (no miss)
        val w = want("rise", "low", "quick", "hum")
        val h = heard(pitch = track(0.0, 0.5), dur = 1200)   // shape near, length near
        assertTrue(ShapeGrade.grade(w, h).none { it.state == "miss" })
        assertTrue(ShapeGrade.grade(w, h).any { it.state == "near" })
    }

    // --- live ---------------------------------------------------------------------------------------------------------

    @Test fun livePendsUntilEnoughData() {
        val w = want("rise", "low", "quick", "hum")
        // a few voiced ticks, well under 150 ms voiced: pitch pending, shape pending, length pending
        val short = ShapeGrade.live(w, listOf(150.0, 155.0, null), 20, scale())
        assertEquals("pending", short.first { it.id == "PITCH" }.state)
        assertEquals("pending", short.first { it.id == "SHAPE" }.state)
        assertEquals("pending", short.first { it.id == "LENGTH" }.state)
        // after 150 ms voiced but before 60% of the wanted length, pitch resolves, shape still pending
        val mid = ShapeGrade.live(w, List(10) { 150.0 + it * 5.0 }, 20, scale())   // 10 ticks * 20 ms = 200 ms voiced
        assertEquals("ok", mid.first { it.id == "PITCH" }.state)                   // start 150 Hz, low -> ok
        assertEquals("pending", mid.first { it.id == "SHAPE" }.state)
        // enough data (>= 60% of 0.6 s = 360 ms) resolves the shape
        val long = ShapeGrade.live(w, (0 until 30).map { if (it % 3 == 2) null else 150.0 + it * 4.0 }, 20, scale())
        assertEquals("ok", long.first { it.id == "SHAPE" }.state)                  // a clear rise
        assertEquals("pending", long.first { it.id == "LENGTH" }.state)            // length is always pending live
    }

    // --- review fixes -------------------------------------------------------------------------------------------------

    @Test fun theExtractorsOwnLabelIsAlwaysTheRightShape() {
        // its thresholds are stricter, so its "rise" is a rise even when the 16 points barely move
        assertEquals("ok", state("SHAPE", want("rise"), heard("rise", pitch = track(0.0, 0.2))))
        assertEquals("miss", state("SHAPE", want("rise"), heard("flat", pitch = track(0.0, 0.2))))
    }

    @Test fun oneStrayPointDoesNotDecideTheShape() {
        // a low voice near the 75 Hz f0 floor: one point an octave off
        val spike = DoubleArray(16) { if (it == 9) 12.0 else 0.0 }
        assertEquals("ok", state("SHAPE", want("flat"), heard(pitch = spike)))
        assertEquals("miss", state("SHAPE", want("arch"), heard(pitch = spike)))
        // an end point off by an octave does not turn a rise into a fall
        val rise2 = track(0.0, 3.0).also { it[15] = -9.0 }
        assertEquals("ok", state("SHAPE", want("rise"), heard(pitch = rise2)))
    }

    @Test fun aPopHasNoLength() {
        assertNull(state("LENGTH", want("pop", "none", tone = "any"), heard("pop", f0 = null, dur = 40, pitch = DoubleArray(0))))
        assertNull(ShapeGrade.live(want("click", "none", tone = "any"), listOf(null, null), 20).firstOrNull { it.id == "LENGTH" })
    }

    @Test fun liveStartIgnoresAnOnsetGlitchAndShapeWaitsForVoicedTime() {
        val w = want("rise", "low", "quick", "hum")
        // the first tick is an octave up (360 Hz), the note starts at 180 Hz = home: low -> ok, not a miss
        val tr = listOf(360.0) + List(9) { 180.0 + it }
        assertEquals("ok", ShapeGrade.live(w, tr, 20, scale()).first { it.id == "PITCH" }.state)
        // 2 s of silence then 100 ms of voice: the shape is still pending (not judged on 5 points)
        val late = List(100) { null } + List(5) { 150.0 + it * 10 }
        assertEquals("pending", ShapeGrade.live(w, late, 20, scale()).first { it.id == "SHAPE" }.state)
    }

    @Test fun calibrationLengthsOverrideTheSpeed() {
        assertEquals(3.0, ShapeGrade.wantedDurS(want("flat", "home").copy(durS = 3.0)), 1e-9)
        assertEquals(ShapeGrade.UNTAGGED_DUR_S, ShapeGrade.wantedDurS(want("flat", "home")), 1e-9)
    }
}
