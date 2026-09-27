package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** VolumePlan: what the Executor sets for a volume command on a stream's current state (Volume.kt). */
class VolumeTest {
    private val music = VolumePlan.Level(index = 7, min = 0, max = 15)
    private val big = VolumePlan.Level(index = 10, min = 0, max = 30)
    private fun up(n: Int, exact: Boolean = false) = VolOp.Step(n, 1, exact)
    private fun down(n: Int, exact: Boolean = false) = VolOp.Step(n, -1, exact)

    @Test fun stepsScaleWithTheStreamsRange() {
        assertEquals(8, VolumePlan.plan(up(1), music, null).setIndex)
        assertEquals(12, VolumePlan.plan(up(1), big, null).setIndex)            // 30 steps: a step is 2 indices
        assertEquals(10, VolumePlan.plan(up(3), music, null).setIndex)
        assertEquals(11, VolumePlan.plan(up(1, exact = true), big, null).setIndex)   // "a bit": one index
        assertEquals(16, VolumePlan.plan(VolOp.Step(0, 1, fraction = 0.2), big, null).setIndex)
        assertEquals(1, VolumePlan.unit(VolumePlan.Level(3, 1, 7)))            // a 7-step stream: at least 1
    }

    @Test fun clampsAndSaysWhyNothingChanged() {
        assertEquals(15, VolumePlan.plan(up(4), music.copy(index = 14), null).setIndex)
        val atMax = VolumePlan.plan(up(1), music.copy(index = 15), null)
        assertNull(atMax.setIndex); assertEquals("already at max", atMax.note)
        assertEquals("already at min", VolumePlan.plan(down(1), music.copy(index = 0), null).note)
        assertEquals(0, VolumePlan.plan(down(20, exact = true), music, null).setIndex)
    }

    @Test fun exactLevelsAndPercentages() {
        assertEquals(8, VolumePlan.plan(VolOp.Set(fraction = 0.5), music, null).setIndex)      // 7.5 rounds up
        assertEquals(15, VolumePlan.plan(VolOp.Set(fraction = 1.0), music, null).setIndex)
        assertEquals(5, VolumePlan.plan(VolOp.Set(index = 5), music, null).setIndex)
        assertEquals(5, VolumePlan.plan(VolOp.Set(index = 30), music, null).setIndex)          // above max: "30" is 30 %
        assertEquals(15, VolumePlan.plan(VolOp.Set(index = 500), music, null).setIndex)
        assertEquals(1, VolumePlan.plan(VolOp.Lowest, music, null).setIndex)                   // lowest audible, not mute
        assertEquals("already there", VolumePlan.plan(VolOp.Set(index = 7), music, null).note)
        assertEquals("47%", VolumePlan.percent(7, music))
    }

    @Test fun muteRemembersAndUnmuteRestores() {
        val m = VolumePlan.plan(VolOp.Mute, music, null)
        assertTrue(m.mute); assertEquals(7, m.remember); assertNull(m.setIndex)
        val muted = music.copy(index = 0, muted = true)
        assertEquals("already muted", VolumePlan.plan(VolOp.Mute, muted, 7).note)
        val u = VolumePlan.plan(VolOp.Unmute, muted, 7)
        assertTrue(u.unmute); assertEquals(7, u.setIndex)
        // silenced by hand (index at min, not muted): back to what was remembered, else 30 %
        assertEquals(7, VolumePlan.plan(VolOp.Unmute, music.copy(index = 0), 7).setIndex)
        assertEquals(5, VolumePlan.plan(VolOp.Unmute, music.copy(index = 0), null).setIndex)
        assertEquals("not muted", VolumePlan.plan(VolOp.Unmute, music, null).note)
    }

    @Test fun stepsFromMute() {
        val muted = music.copy(index = 0, muted = true)
        val up = VolumePlan.plan(up(1), muted, 7)
        assertTrue(up.unmute); assertEquals(8, up.setIndex)                     // like the volume keys: unmute, then up
        assertEquals("muted", VolumePlan.plan(down(1), muted, 7).note)
        assertFalse(VolumePlan.plan(VolOp.Set(fraction = 0.5), muted, 7).mute)
        assertTrue(VolumePlan.plan(VolOp.Set(fraction = 0.5), muted, 7).unmute)
    }

    @Test fun theCallStreamCannotBeMutedSoItGoesToItsMinimum() {
        val call = VolumePlan.Level(index = 4, min = 1, max = 5)
        val p = VolumePlan.plan(VolOp.Mute, call, null, canMute = false)
        assertFalse(p.mute); assertEquals(1, p.setIndex); assertEquals(4, p.remember)
        assertEquals(4, VolumePlan.plan(VolOp.Unmute, call.copy(index = 1), 4).setIndex)
    }

    @Test fun theAutoStreamFollowsACall() {
        assertEquals(VolStream.MUSIC, VolumePlan.stream(VolStream.AUTO, inCall = false))
        assertEquals(VolStream.CALL, VolumePlan.stream(VolStream.AUTO, inCall = true))
        assertEquals(VolStream.RING, VolumePlan.stream(VolStream.RING, inCall = true))   // a named stream wins
    }
}
