package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** ChainViewLayout (ChainView.kt): the pure S9 block geometry, from a fake measure. */
class ChainViewLayoutTest {
    @Test fun scaleIsWidthOver1080() {
        assertEquals(1.0f, ChainViewLayout.scale(1080), 0.001f)
        assertEquals(0.5f, ChainViewLayout.scale(540), 0.001f)
    }

    @Test fun blockWidthGrowsWithTextAndNote() {
        val s = 1.0f
        val bare = ChainViewLayout.blockWidth(s, 0f, 0f)
        val withText = ChainViewLayout.blockWidth(s, 100f, 0f)
        val withNote = ChainViewLayout.blockWidth(s, 100f, 60f)
        assertTrue(withText > bare)
        assertTrue(withNote > withText)
        // the fixed shell (pad + glyph + gap + pad) is 12 + 28 + 16 + 12 = 68 px at scale 1
        assertEquals(68f, bare, 0.01f)
    }

    @Test fun geometryScalesWithTheBase() {
        assertEquals(ChainViewLayout.blockWidth(1.0f, 50f, 20f) / 2, ChainViewLayout.blockWidth(0.5f, 25f, 10f), 0.5f)
    }

    @Test fun rowAndChipHeights() {
        assertEquals(48f, ChainViewLayout.rowHeight(1.0f), 0.01f)
        assertEquals(34f, ChainViewLayout.chipHeight(1.0f), 0.01f)
    }
}
