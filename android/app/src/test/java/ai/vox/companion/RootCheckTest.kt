package ai.vox.companion

import ai.vox.companion.RootCheck.Win
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** A root from the accessibility cache must be the live foreground screen (RootCheck.kt; TreeReader.appRoot). */
class RootCheckTest {
    private val instagram = Win(7, app = true, active = true, layer = 3)
    private val bars = Win(2, app = false, active = false, layer = 9)

    @Test fun theActiveTopAppWindowIsLive() {
        assertNull(RootCheck.why(7, alive = true, windows = listOf(instagram, bars)))
    }

    @Test fun aCachedRootOfAWindowThatIsGoneIsStale() {
        // Z Flip: Instagram in front, the cache still served TikTok's tree (window 4) from minutes before
        assertNotNull(RootCheck.why(4, alive = true, windows = listOf(instagram, bars)))
        assertNotNull(RootCheck.why(4, alive = false, windows = listOf(instagram, bars)))
        assertNotNull(RootCheck.why(7, alive = false, windows = emptyList()))   // refresh() failed: dead node
    }

    @Test fun aRootFromABackgroundAppWindowIsStale() {
        val tiktokBehind = Win(4, app = true, active = false, layer = 1)
        assertNotNull(RootCheck.why(4, alive = true, windows = listOf(instagram, tiktokBehind, bars)))
    }

    @Test fun theActiveWindowWinsOverAnInactiveOneOnTop() {
        // picture-in-picture (or a split screen's other half) above the app the user is using: the active one is right
        val tiktok = Win(4, app = true, active = true, layer = 1)
        val pip = Win(9, app = true, active = false, layer = 5)
        assertNull(RootCheck.why(4, alive = true, windows = listOf(pip, tiktok, bars)))
        // no window marked active: the top app window is the foreground
        assertNull(RootCheck.why(9, alive = true, windows = listOf(pip.copy(active = false), tiktok.copy(active = false))))
        assertNotNull(RootCheck.why(4, alive = true, windows = listOf(pip.copy(active = false), tiktok.copy(active = false))))
    }

    @Test fun systemWindowFallbackAndAnUnreadableListPassWhenAlive() {
        assertNull(RootCheck.why(2, alive = true, windows = listOf(bars)))
        assertNull(RootCheck.why(7, alive = true, windows = emptyList()))
    }

    @Test fun theSlowRefreshIsThrottledPerWindow() {
        assertTrue(RootCheck.refreshDue(null, 5_000))                              // never re-read: now
        assertFalse(RootCheck.refreshDue(5_000, 5_400))                            // re-read 400 ms ago: the cheap check only
        assertTrue(RootCheck.refreshDue(5_000, 5_000 + RootCheck.REFRESH_MS))      // a second later: again
        assertTrue(RootCheck.refreshDue(5_000, 100))                               // clock went back: re-read
    }
}
