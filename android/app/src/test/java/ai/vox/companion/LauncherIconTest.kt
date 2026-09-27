package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** [IconSwitch]: the launcher icon's decision and debounce (switch after 10 s stable, at most once a minute). */
class LauncherIconTest {
    @Test fun sameStateDoesNothing() {
        val s = IconSwitch(shown = true)
        s.observe(true, 1_000)
        assertNull(s.poll(1_000))
        assertNull(s.poll(100_000))
    }

    @Test fun switchesOnlyAfterStable() {
        val s = IconSwitch(shown = true)
        s.observe(false, 5_000)
        assertEquals(10_000L, s.poll(5_000))
        assertEquals(1L, s.poll(14_999))
        assertEquals(0L, s.poll(15_000))
        assertFalse(s.shown)
        assertNull(s.poll(15_001))
    }

    @Test fun flapBackCancels() {
        val s = IconSwitch(shown = false)
        s.observe(true, 0)
        s.observe(false, 4_000)          // back to what is shown before 10 s: nothing to do
        assertNull(s.poll(20_000))
        assertFalse(s.shown)
    }

    @Test fun flappingRestartsTheStableWindow() {
        val s = IconSwitch(shown = false)
        s.observe(true, 0)
        s.observe(false, 3_000)
        s.observe(true, 6_000)           // stable from 6 s
        assertEquals(10_000L, s.poll(6_000))
        assertEquals(0L, s.poll(16_000))
        assertTrue(s.shown)
    }

    @Test fun atMostOncePerMinute() {
        val s = IconSwitch(shown = true)
        s.observe(false, 0)
        assertEquals(0L, s.poll(10_000))  // off at 10 s
        s.observe(true, 11_000)
        assertEquals(49_000L, s.poll(21_000)) // stable since 11 s, but the last switch was at 10 s: wait until 70 s
        assertEquals(0L, s.poll(70_000))
        assertTrue(s.shown)
    }

    @Test fun firstSwitchIsNotHeldByTheMinute() {
        val s = IconSwitch(shown = true)
        s.observe(false, 0)
        assertEquals(0L, s.poll(10_000))
    }

    /** A service restart drops the link (off) and the recovery brings it back within seconds: the icon never changes. */
    @Test fun quickRestartAndRecoveryKeepTheIcon() {
        val s = IconSwitch(shown = true)
        s.observe(true, 0)
        s.observe(false, 60_000)          // service stopped: link state idle
        assertEquals(10_000L, s.poll(60_000))
        s.observe(false, 61_000)          // stale link waited out, setup failed once, retrying
        s.observe(true, 66_000)           // fresh link ready
        assertNull(s.poll(70_000))
        assertTrue(s.shown)
        // but a recovery that never gets ready shows "off" 10 s after the link went
        s.observe(false, 80_000)
        assertEquals(0L, s.poll(90_000))
        assertFalse(s.shown)
    }
}
