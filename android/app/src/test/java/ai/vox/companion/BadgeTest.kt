package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The Canti head's state mapping (Badge.kt): service state -> held state, executed actions -> one-shots. */
class BadgeTest {
    private val base = BadgeStates.Inputs(armed = true, paused = false, mode = "gesture", holdScrolling = false,
        pending = false, listening = false, sourceError = false)

    @Test fun heldStatesAndTheirPriority() {
        assertEquals(BadgeState.IDLE, BadgeStates.held(base))
        assertEquals(BadgeState.CURSOR, BadgeStates.held(base.copy(mode = "cursor")))
        assertEquals(BadgeState.PENDING, BadgeStates.held(base.copy(pending = true)))
        assertEquals("pending beats the cursor face", BadgeState.PENDING, BadgeStates.held(base.copy(mode = "cursor", pending = true)))
        assertEquals(BadgeState.HEARING, BadgeStates.held(base.copy(listening = true, pending = true)))
        assertEquals(BadgeState.HOLD_SCROLL, BadgeStates.held(base.copy(holdScrolling = true, pending = true)))
        assertEquals(BadgeState.ERROR, BadgeStates.held(base.copy(sourceError = true, holdScrolling = true)))
        assertEquals(BadgeState.PAUSED, BadgeStates.held(base.copy(paused = true, sourceError = true)))
        assertEquals("disarmed (also: BLE disconnect, device asleep) is off, whatever else", BadgeState.OFF,
            BadgeStates.held(base.copy(armed = false, paused = true, holdScrolling = true)))
        for (s in listOf(BadgeState.IDLE, BadgeState.CURSOR, BadgeState.PENDING, BadgeState.HOLD_SCROLL, BadgeState.PAUSED, BadgeState.OFF))
            assertFalse("$s is held", s.oneShot)
    }

    @Test fun actionsPlayOneShots() {
        assertEquals(BadgeState.SCROLL_UP, BadgeStates.forAction("swipe_up", true))
        assertEquals(BadgeState.SCROLL_DOWN, BadgeStates.forAction("swipe_down", true))
        assertEquals(BadgeState.BACK, BadgeStates.forAction("back", true))
        assertEquals(BadgeState.FORWARD, BadgeStates.forAction("forward", true))
        assertEquals(BadgeState.HOME, BadgeStates.forAction("home", true))
        assertEquals(BadgeState.ERROR, BadgeStates.forAction("back", false))
        assertNull("no face for other actions yet", BadgeStates.forAction("tap", true))
        assertNull(BadgeStates.forAction("none", true))
        for (s in listOf(BadgeState.SCROLL_UP, BadgeState.SCROLL_DOWN, BadgeState.BACK, BadgeState.FORWARD, BadgeState.HOME, BadgeState.HEARING))
            assertTrue("$s is a one-shot", s.oneShot)
        assertEquals("hold-scroll", BadgeStates.label(BadgeState.HOLD_SCROLL))
        assertEquals(15, BadgeState.values().size)
    }

    /** A `none` decision (heard, nothing done) shrugs; everything else is the action's one-shot; HEARING stays the
     *  held state for an open phrase window. */
    @Test fun noneDecisionShrugsInsteadOfHearing() {
        assertEquals(BadgeState.IGNORED, BadgeStates.forDecision("none", true))
        assertEquals(BadgeState.IGNORED, BadgeStates.forDecision("none", false))
        assertEquals(BadgeState.SCROLL_UP, BadgeStates.forDecision("swipe_up", true))
        assertEquals(BadgeState.ERROR, BadgeStates.forDecision("back", false))
        assertNull(BadgeStates.forDecision("tap", true))
        for (a in listOf("none", "swipe_up", "swipe_down", "back", "forward", "home", "tap"))
            for (ok in listOf(true, false)) assertTrue(BadgeStates.forDecision(a, ok) != BadgeState.HEARING)
        assertTrue(BadgeState.IGNORED.oneShot)
        assertEquals(BadgeState.HEARING, BadgeStates.held(base.copy(listening = true)))
        assertEquals("ignored", BadgeStates.label(BadgeState.IGNORED))
    }

    /** At most one shrug per 2.5 s, dropped (not queued) in between; a dropped one doesn't restart the wait. */
    @Test fun ignoredIsRateLimited() {
        assertEquals(2500L, IgnoredGate.GAP_MS)
        val g = IgnoredGate()
        assertTrue(g.admit(10_000))
        assertFalse(g.admit(10_001))
        assertFalse(g.admit(11_000))
        assertFalse(g.admit(12_499))
        assertTrue("2.5 s after the last one that played", g.admit(12_500))
        assertFalse(g.admit(14_999))
        assertTrue(g.admit(15_000))
        // a sound every 500 ms for 10 s (a video playing): 4 shrugs, 2.5 s apart
        val v = IgnoredGate()
        val played = (0 until 20).map { it * 500L }.filter { v.admit(it) }
        assertEquals(listOf(0L, 2500L, 5000L, 7500L), played)
        assertTrue("any monotonic clock, from 0", IgnoredGate().admit(0))
    }

    /** The Pico paused itself after a link drop: its own held state, only while disarmed and not app-paused. */
    @Test fun aLinkDropPauseAsksForATap() {
        val dropped = base.copy(armed = false, wakeable = true)
        assertEquals(BadgeState.TAP_TO_WAKE, BadgeStates.held(dropped))
        assertEquals("beats everything but an app-side Pause", BadgeState.TAP_TO_WAKE,
            BadgeStates.held(dropped.copy(holdScrolling = true, pending = true, listening = true, sourceError = true, mode = "cursor")))
        assertEquals("the menu's Pause on top of it: plain off", BadgeState.OFF, BadgeStates.held(dropped.copy(paused = true)))
        assertEquals("a user's device pause (not wakeable) stays off", BadgeState.OFF, BadgeStates.held(base.copy(armed = false)))
        assertEquals("armed again: wakeable no longer matters", BadgeState.IDLE, BadgeStates.held(base.copy(wakeable = true)))
        assertEquals("the deliberate Pause is still PAUSED", BadgeState.PAUSED, BadgeStates.held(base.copy(paused = true)))
        assertFalse(BadgeState.TAP_TO_WAKE.oneShot)
        assertEquals("tap-to-wake", BadgeStates.label(BadgeState.TAP_TO_WAKE))
    }

    /** A tap wakes only in that state; a long-press always opens the menu. */
    @Test fun tapWakesLongPressOpensTheMenu() {
        assertEquals(BadgeStates.Touch.WAKE, BadgeStates.onTap(wakeable = true))
        assertEquals(BadgeStates.Touch.MENU, BadgeStates.onTap(wakeable = false))
        assertEquals(BadgeStates.Touch.MENU, BadgeStates.onLongPress())
        // BadgeActions defaults: an implementation that knows nothing of waking never wakes.
        val a = object : BadgeActions {
            override val mode = "gesture"; override val paused = false; override val source = "pico"
            override fun setMode(mode: String) {}; override fun setPaused(p: Boolean) {}; override fun setSource(src: String) {}
        }
        assertFalse(a.wakeable)
    }

    /** The notification: Wake replaces Pause while the Pico waits for a tap; the title says so. */
    @Test fun theNotificationOffersWake() {
        val s = ai.vox.companion.audio.CantiNotification.State("pico", paused = false, armed = false, mode = "gesture",
            device = "awake – paused", micState = null, micDevice = null, wakeable = true)
        assertEquals("Canti · Pico paused (link lost): tap Wake", ai.vox.companion.audio.CantiNotification.title(s))
        assertEquals("Canti · off", ai.vox.companion.audio.CantiNotification.title(s.copy(wakeable = false)))
        assertEquals("Canti · paused", ai.vox.companion.audio.CantiNotification.title(s.copy(paused = true)))
    }
}
