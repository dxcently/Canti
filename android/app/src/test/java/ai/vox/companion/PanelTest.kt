package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** PanelPlace / OwnCover / OwnRects (Panel.kt): pure geometry and own-window visibility. */
class PanelTest {
    private fun box(l: Int, t: Int, r: Int, b: Int) = Box(l, t, r, b)

    @Test fun panelTopDefaultsAndJumps() {
        // default matches StripPlace.top
        assertEquals(StripPlace.top(1000, 800, 40, 160, null, null), PanelPlace.top(1000, 800, 40, 160, null, null, null, false))
        // jump -> just below the status bar
        assertEquals(40 + 16, PanelPlace.top(1000, 800, 40, 160, null, null, 500, true))
        // userTop clamps into [statusTop+GUT, default]
        assertEquals(StripPlace.top(1000, 800, 40, 160, null, null), PanelPlace.top(1000, 800, 40, 160, null, null, 100000, false))
        assertEquals(56, PanelPlace.top(1000, 800, 40, 160, null, null, 10, false))
        assertEquals(300, PanelPlace.top(1000, 800, 40, 160, null, null, 300, false))
    }

    @Test fun needsJumpWhenTheTargetIntersectsThePanel() {
        val target = box(100, 500, 300, 560)
        assertTrue(PanelPlace.needsJump(target, listOf(box(0, 520, 1080, 760))))
        assertFalse(PanelPlace.needsJump(target, listOf(box(0, 0, 1080, 100))))
        // the 16 px pad counts
        assertTrue(PanelPlace.needsJump(box(100, 700, 300, 760), listOf(box(0, 770, 1080, 900))))
    }

    @Test fun ownCoverKeepsTargetsUnderCantisOwnWindows() {
        val r = box(0, 400, 1080, 760)
        val own = listOf(box(0, 400, 1080, 760))   // fully covered by Canti's own window
        assertTrue(OwnCover.visible(false, r, own))    // the framework says hidden, but it is our own window
        assertFalse(OwnCover.visible(false, r, listOf(box(0, 0, 1080, 300))))   // not covered by our window
        assertTrue(OwnCover.visible(true, r, emptyList()))                       // framework says visible
        assertFalse(OwnCover.visible(false, box(0, 0, 0, 0), own))               // empty rect
    }

    @Test fun ownRectsKeepsRecentRectsOnly() {
        val o = OwnRects(keepMs = 5000)
        o.note(listOf(box(0, 0, 10, 10)), 1000)
        o.note(listOf(box(0, 20, 10, 30)), 6000)
        assertEquals(listOf(box(0, 0, 10, 10), box(0, 20, 10, 30)), o.recent(6000))   // 5000ms old is still within the window
        assertEquals(listOf(box(0, 20, 10, 30)), o.recent(6001))                       // now the first has aged out
        assertEquals(emptyList<Box>(), o.recent(12000))
    }
}
