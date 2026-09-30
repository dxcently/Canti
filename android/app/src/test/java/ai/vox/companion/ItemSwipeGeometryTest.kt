package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** ItemSwipe.kt: the item-swipe finger path (70% travel, RTL "away", clamped inside the screen). */
class ItemSwipeGeometryTest {
    @Test fun seventyPercentFromCentre() {
        val g = ItemSwipeGeometry.gesture(Box(100, 100, 300, 200), 1000, "right", rtl = false)
        assertEquals(200f, g.x0, 0.01f)
        assertEquals(900f, g.x1, 0.01f)   // centre 200 + 0.7 * 1000
        assertEquals(150f, g.y0, 0.01f)
        assertEquals(150f, g.y1, 0.01f)
        assertEquals(250L, g.ms)
    }

    @Test fun rtlAwayIsRight() {
        val ltr = ItemSwipeGeometry.gesture(Box(450, 0, 550, 100), 1000, "away", rtl = false)
        assertTrue("ltr away goes left", ltr.x1 < ltr.x0)
        val rtl = ItemSwipeGeometry.gesture(Box(450, 0, 550, 100), 1000, "away", rtl = true)
        assertTrue("rtl away goes right", rtl.x1 > rtl.x0)
    }

    @Test fun clampsInsideScreen() {
        val g = ItemSwipeGeometry.gesture(Box(0, 0, 100, 100), 1000, "left", rtl = false)
        assertEquals(0f, g.x1, 0.01f)   // centre 50 - 700 = -650 -> clamped to 0
    }
}
