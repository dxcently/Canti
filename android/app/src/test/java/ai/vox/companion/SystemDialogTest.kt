package ai.vox.companion

import ai.vox.companion.SystemDialog.Kind.APPLICATION
import ai.vox.companion.SystemDialog.Kind.OTHER
import ai.vox.companion.SystemDialog.Kind.SYSTEM
import ai.vox.companion.SystemDialog.Win
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** While a system dialog is in front: back or home only, never a touch (SystemDialog.kt; Executor.dialogInFront). */
class SystemDialogTest {
    private val own = "ai.vox.companion"
    private val tiktok = Win(APPLICATION, "com.zhiliaoapp.musically", 1)
    private val bars = Win(SYSTEM, "com.android.systemui", 5)
    private val canti = Win(SYSTEM, own, 9)

    @Test fun permissionControllerOverAnAppBlocks() {
        val w = listOf(tiktok, Win(APPLICATION, "com.google.android.permissioncontroller", 2), bars, canti)
        assertEquals("com.google.android.permissioncontroller", SystemDialog.detect(w, own))
        assertEquals("com.samsung.android.permissioncontroller",
            SystemDialog.detect(listOf(tiktok, Win(APPLICATION, "com.samsung.android.permissioncontroller", 2)), own))
    }

    @Test fun packageInstallerBlocks() {
        assertEquals("com.android.packageinstaller",
            SystemDialog.detect(listOf(tiktok, Win(APPLICATION, "com.android.packageinstaller", 2)), own))
    }

    @Test fun systemOwnedWindowAboveTheAppBlocksBelowItDoesNot() {
        // Chrome's "default browser?" role prompt / the app chooser / "isn't responding": owned by the system
        val chrome = Win(APPLICATION, "com.android.chrome", 1)
        assertEquals("android", SystemDialog.detect(listOf(chrome, Win(APPLICATION, "android", 2)), own))
        assertEquals("com.android.intentresolver", SystemDialog.detect(listOf(chrome, Win(SYSTEM, "com.android.intentresolver", 3)), own))
        assertNull(SystemDialog.detect(listOf(Win(APPLICATION, "android", 0), chrome), own))
    }

    @Test fun overlaysSystemUiCantiAndTheKeyboardNeverBlock() {
        val chatHead = Win(SYSTEM, "com.facebook.orca", 4)
        val edge = Win(SYSTEM, "com.samsung.android.app.cocktailbarservice", 4)
        assertNull(SystemDialog.detect(listOf(tiktok, chatHead, edge, bars, canti), own))
        assertNull(SystemDialog.detect(listOf(tiktok, Win(OTHER, "com.google.android.permissioncontroller", 3)), own))
        assertNull(SystemDialog.detect(listOf(tiktok, Win(APPLICATION, null, 3)), own))
        assertNull(SystemDialog.detect(emptyList(), own))
    }

    @Test fun backAndHomeAllowedEveryTouchRefused() {
        for (a in listOf("back", "home", "volume_up", "volume", "play_pause", "move_up", "move_left_fast", "none"))
            assertTrue(a, SystemDialog.allows(a))
        for (a in listOf("swipe_up", "swipe_left", "scroll_down", "fling_up", "tap", "click", "double_tap", "long_press",
                "like", "tap_target", "drag", "gesture", "select", "some_new_action"))
            assertFalse(a, SystemDialog.allows(a))
    }

    @Test fun refusalSaysBackOrHomeOnly() {
        val r = SystemDialog.refusal("swipe_up", "com.google.android.permissioncontroller")
        assertTrue(r, r.startsWith(SystemDialog.REFUSED) && r.contains("swipe_up") && r.contains("back or home only"))
        assertEquals("system dialog: back or home only", SystemDialog.BADGE)
    }
}
