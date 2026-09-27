package ai.vox.companion

import android.os.Handler
import android.os.Looper
import android.view.accessibility.AccessibilityEvent
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The Confirmer's event rules, driven through its primitive onEvent(type, pkg, windowId) with a fake clock. */
class ConfirmerTest {
    private val own = "ai.vox.companion"
    private val app = "com.example.app"
    private val ownWindowId = 77

    private class Rig {
        var now = 1_000L
        var fp = 1
        var walks = 0
        val timers = mutableListOf<() -> Unit>()
    }

    private fun confirmer(r: Rig) = Confirmer(
        Handler(Looper.getMainLooper()), own,
        fingerprint = { r.walks++; r.fp },
        timeoutMs = { 1500L },
        grab = { it(null) },
        gate = GrabGate(),
        ownWindow = { it == ownWindowId },
        clock = { r.now },
        schedule = { _, f -> r.timers += f },
    )

    @Test fun swipesScrollsAndNavigationSkipTheBeforeTreeWalk() {
        val r = Rig(); val c = confirmer(r)
        for (a in listOf("swipe_up", "swipe_down", "swipe_left", "swipe_right", "scroll_up", "scroll_down", "back", "home", "recents")) {
            c.begin(a, injected = a.startsWith("swipe"))
        }
        assertEquals("no tree walk before dispatch", 0, r.walks)
        assertFalse(Confirmer.treeBaseline("back"))
    }

    @Test fun tapsKeepTheBeforeFingerprint() {
        val r = Rig(); val c = confirmer(r)
        c.begin("tap", injected = true)
        assertEquals(1, r.walks)
        assertTrue(Confirmer.treeBaseline("tap"))
        assertTrue(Confirmer.treeBaseline("next_item"))
        // a content change with a different tree confirms the tap
        r.now += 600; r.fp = 2
        c.onEvent(AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED, app, 5)
        assertEquals("confirmed (events)", c.lastResult)
    }

    @Test fun aTapWithAnUnchangedTreeIsNotConfirmedByContentEvents() {
        val r = Rig(); val c = confirmer(r)
        c.begin("tap", injected = true)
        r.now += 600
        c.onEvent(AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED, app, 5)
        assertNull(c.lastResult)
        r.timers.removeAt(0)()   // timeout: tree unchanged, no screenshot
        assertEquals("no visible change", c.lastResult)
    }

    @Test fun withoutABaselineContentEventsNeitherConfirmNorWalkTheTree() {
        val r = Rig(); val c = confirmer(r)
        c.begin("swipe_up", injected = true)
        r.now += 600; r.fp = 2
        c.onEvent(AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED, app, 5)
        assertNull(c.lastResult)
        assertEquals(0, r.walks)
        r.timers.removeAt(0)()   // timeout: no tree compare, no screenshot available
        assertEquals("no visible change", c.lastResult)
        assertEquals(0, r.walks)
    }

    @Test fun aScrollEventConfirmsASwipe() {
        val r = Rig(); val c = confirmer(r)
        c.begin("swipe_up", injected = true)
        c.onEvent(AccessibilityEvent.TYPE_VIEW_SCROLLED, app, 5)
        assertEquals("confirmed (events)", c.lastResult)
    }

    @Test fun cantisOwnOverlayWindowsDoNotConfirm() {
        val r = Rig(); val c = confirmer(r)
        c.begin("tap", injected = true)
        // the head going pass-through / hopping: a windows change with no package, from Canti's window
        c.onEvent(AccessibilityEvent.TYPE_WINDOWS_CHANGED, "", ownWindowId)
        // and anything Canti's own package reports
        c.onEvent(AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED, own, 3)
        assertNull(c.lastResult)
        // a windows change from another window still confirms
        c.onEvent(AccessibilityEvent.TYPE_WINDOWS_CHANGED, "", 12)
        assertEquals("confirmed (events)", c.lastResult)
    }

    @Test fun aWindowsChangeWithAnUnknownWindowIdStillCounts() {
        val r = Rig(); val c = confirmer(r)
        c.begin("back")
        c.onEvent(AccessibilityEvent.TYPE_WINDOWS_CHANGED, "", -1)
        assertEquals("confirmed (events)", c.lastResult)
    }
}
