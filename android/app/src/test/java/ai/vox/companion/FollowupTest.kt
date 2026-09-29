package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Spoken follow-ups on the last action (Followup.kt): resolve rules, the 30 s window, and the confirm fill. */
class FollowupTest {
    private fun t(label: String, left: Int = 0, top: Int = 0, right: Int = 100, bottom: Int = 50) =
        Target(label, "button", "center", left, top, right, bottom)

    private fun action(a: String, confirm: String? = null, by: String? = null, watch: Long? = null) =
        Last.Action(a, "listening", at = 1000L, appBefore = "app", watch = watch, confirm = confirm, by = by)

    // --- RETRY ---------------------------------------------------------------------------------------------------------

    @Test fun retryRepeatsEachKindOfLastAction() {
        assertEquals(Plan.Run("swipe_up", "listening"), resolve(FollowKind.RETRY, null, "try again", action("swipe_up"), emptyList()))
        assertEquals(Plan.RunVolume(VolOp.Step(1, 1), VolStream.MUSIC),
            resolve(FollowKind.RETRY, null, "try again", Last.Volume(VolOp.Step(1, 1), VolStream.MUSIC, 1000L, "app"), emptyList()))
        assertEquals(Plan.RunApp("com.example"), resolve(FollowKind.RETRY, null, "try again", Last.OpenApp("com.example", 1000L, "app"), emptyList()))
        assertEquals(Plan.Nothing("nothing to repeat"), resolve(FollowKind.RETRY, null, "try again", null, emptyList()))
    }

    @Test fun retryReFindsTheSameTargetOrSaysNotOnScreen() {
        val pick = Last.Pick(t("A", 10, 10, 110, 60), emptyList(), 1000L, "app")
        // the same label with a centre within 24 px is found (even at slightly different bounds)
        assertEquals(Plan.Tap(t("A", 12, 12, 112, 62)), resolve(FollowKind.RETRY, null, "try again", pick, listOf(t("A", 12, 12, 112, 62))))
        // moved beyond 24 px (or absent): nothing
        assertEquals(Plan.Nothing("not on screen"), resolve(FollowKind.RETRY, null, "try again", pick, listOf(t("A", 100, 100, 200, 150))))
        assertEquals(Plan.Nothing("not on screen"), resolve(FollowKind.RETRY, null, "try again", pick, emptyList()))
    }

    // --- OTHER ---------------------------------------------------------------------------------------------------------

    @Test fun otherPicksFromTheRemainingAlternatives() {
        val picked = t("A", 0, 0, 100, 50)
        val b = t("B", 0, 60, 100, 110)
        val c = t("C", 0, 120, 100, 170)
        val pick = Last.Pick(picked, listOf(b, c), 1000L, "app")
        // several remaining -> choose them (in order, re-found on the screen)
        val choose = resolve(FollowKind.OTHER, null, "the other one", pick, listOf(picked, b, c))
        assertEquals(Plan.Choose(listOf(b, c)), choose)
        // exactly one remaining -> tap it
        val one = resolve(FollowKind.OTHER, null, "the other one", Last.Pick(picked, listOf(b), 1000L, "app"), listOf(picked, b))
        assertEquals(Plan.Tap(b), one)
        // none re-found -> nothing
        assertEquals(Plan.Nothing("no other match"), resolve(FollowKind.OTHER, null, "the other one", pick, listOf(picked)))
    }

    @Test fun otherWithoutAPickFallsBackOnlyForTheNextOne() {
        assertEquals(Plan.Fallback, resolve(FollowKind.OTHER, null, "the next one", action("tap"), emptyList()))
        assertEquals(Plan.Fallback, resolve(FollowKind.OTHER, null, "next one", action("tap"), emptyList()))
        assertEquals(Plan.Nothing("nothing to pick instead"), resolve(FollowKind.OTHER, null, "the other one", action("tap"), emptyList()))
        assertEquals(Plan.Nothing("nothing to pick instead"), resolve(FollowKind.OTHER, null, "not that one", null, emptyList()))
    }

    // --- DIRECTION -----------------------------------------------------------------------------------------------------

    @Test fun directionPicksTheNeighbouringTarget() {
        val picked = t("A", 100, 100, 200, 150)   // centre (150, 125)
        val below = t("B", 100, 160, 200, 210)     // centre (150, 185), horizontal overlap
        val above = t("C", 100, 40, 200, 90)       // centre (150, 65)
        val right = t("D", 210, 100, 310, 150)     // centre (260, 125)
        val left = t("E", 0, 100, 90, 150)         // centre (45, 125)
        val screen = listOf(picked, below, above, right, left)
        assertEquals(Plan.Tap(below), resolve(FollowKind.DIRECTION, Dir.BELOW, "the one below", Last.Pick(picked, emptyList(), 1000L, "app"), screen))
        assertEquals(Plan.Tap(above), resolve(FollowKind.DIRECTION, Dir.ABOVE, "the one above", Last.Pick(picked, emptyList(), 1000L, "app"), screen))
        assertEquals(Plan.Tap(right), resolve(FollowKind.DIRECTION, Dir.RIGHT, "the one on the right", Last.Pick(picked, emptyList(), 1000L, "app"), screen))
        assertEquals(Plan.Tap(left), resolve(FollowKind.DIRECTION, Dir.LEFT, "the one on the left", Last.Pick(picked, emptyList(), 1000L, "app"), screen))
        // nothing in that direction / no pick
        val lone = listOf(picked)
        assertEquals(Plan.Nothing("nothing below"), resolve(FollowKind.DIRECTION, Dir.BELOW, "the one below", Last.Pick(picked, emptyList(), 1000L, "app"), lone))
        assertEquals(Plan.Nothing("nothing to pick"), resolve(FollowKind.DIRECTION, Dir.BELOW, "the one below", action("tap"), emptyList()))
    }

    @Test fun directionFallsBackToCentreDistanceWithoutOverlap() {
        val picked = t("A", 100, 100, 200, 150)   // centre (150, 125)
        // neither overlaps horizontally; only the one more below than across qualifies
        val offAxis = t("B", 210, 200, 300, 250)   // centre (255, 225): dx=105, dy=100 -> |dx|>|dy|, excluded
        val down = t("C", 210, 300, 300, 350)      // centre (255, 325): dx=105, dy=200 -> |dx|<|dy|
        val screen = listOf(picked, offAxis, down)
        assertEquals(Plan.Tap(down), resolve(FollowKind.DIRECTION, Dir.BELOW, "the one below", Last.Pick(picked, emptyList(), 1000L, "app"), screen))
    }

    // --- UNDO ----------------------------------------------------------------------------------------------------------

    @Test fun undoInvertsPureDirectionPairs() {
        for ((a, b) in listOf("swipe_up" to "swipe_down", "swipe_left" to "swipe_right", "scroll_up" to "scroll_down",
                "zoom_in" to "zoom_out", "next_item" to "previous_item", "volume_up" to "volume_down")) {
            assertEquals(Plan.Run(b, "listening"), resolve(FollowKind.UNDO, null, "undo", action(a), emptyList()))
            assertEquals(Plan.Run(a, "listening"), resolve(FollowKind.UNDO, null, "undo", action(b), emptyList()))
        }
    }

    @Test fun undoInvertsAVolumeStepOnly() {
        val step = VolOp.Step(3, 1, exact = true, fraction = null)
        assertEquals(Plan.RunVolume(VolOp.Step(3, -1, exact = true, fraction = null), VolStream.MUSIC),
            resolve(FollowKind.UNDO, null, "undo", Last.Volume(step, VolStream.MUSIC, 1000L, "app"), emptyList()))
        // Set / Mute / Unmute / Lowest have no stored level
        for (op in listOf<VolOp>(VolOp.Set(fraction = 0.5), VolOp.Mute, VolOp.Unmute, VolOp.Lowest)) {
            assertEquals(Plan.CantUndo("can't undo that"),
                resolve(FollowKind.UNDO, null, "undo", Last.Volume(op, VolStream.MUSIC, 1000L, "app"), emptyList()))
        }
    }

    @Test fun undoOfATapOrAppLaunchGoesBackOnlyAfterAWindowChange() {
        // a tap confirmed by a window change -> back
        assertEquals(Plan.Run("back", "listening"),
            resolve(FollowKind.UNDO, null, "undo", action("tap", confirm = "confirmed (events)", by = "TYPE_WINDOW_STATE_CHANGED:com.x"), emptyList()))
        assertEquals(Plan.Run("back", "listening"),
            resolve(FollowKind.UNDO, null, "undo", action("click", confirm = "confirmed (events)", by = "TYPE_WINDOWS_CHANGED:"), emptyList()))
        // a tap confirmed by a scroll (no window change) is not undoable
        assertEquals(Plan.CantUndo("can't undo that"),
            resolve(FollowKind.UNDO, null, "undo", action("tap", confirm = "confirmed (events)", by = "TYPE_VIEW_SCROLLED:com.x"), emptyList()))
        // an app launch confirmed by a window change -> back
        assertEquals(Plan.Run("back", "listening"),
            resolve(FollowKind.UNDO, null, "undo", Last.OpenApp("com.x", 1000L, "app", confirm = "confirmed (events)", by = "TYPE_WINDOW_STATE_CHANGED:com.x"), emptyList()))
        // a pick (tap target) confirmed by a window change -> back
        val pick = Last.Pick(t("Go"), emptyList(), 1000L, "app", confirm = "confirmed (events)", by = "TYPE_WINDOW_STATE_CHANGED:com.x")
        assertEquals(Plan.Run("back", "listening"), resolve(FollowKind.UNDO, null, "undo", pick, emptyList()))
    }

    @Test fun outwardIsNeverUndone() {
        assertEquals(Plan.CantUndo("can't undo that"), resolve(FollowKind.UNDO, null, "undo", action("like"), emptyList()))
        val pick = Last.Pick(t("Like"), emptyList(), 1000L, "app", confirm = "confirmed (events)", by = "TYPE_WINDOW_STATE_CHANGED:com.x")
        assertEquals(Plan.CantUndo("can't undo that"), resolve(FollowKind.UNDO, null, "undo", pick, emptyList()))
    }

    @Test fun backHomeRecentsListenAndOtherActionsAreNotUndoable() {
        for (a in listOf("back", "home", "recents", "notifications", "listen_for_phrase", "type_text", "tap")) {
            assertEquals(Plan.CantUndo("can't undo that"), resolve(FollowKind.UNDO, null, "undo", action(a), emptyList()))
        }
        assertEquals(Plan.CantUndo("can't undo that"), resolve(FollowKind.UNDO, null, "undo", null, emptyList()))
    }

    @Test fun aNoVisibleChangeConfirmCannotBeUndone() {
        assertEquals(Plan.CantUndo("nothing changed"),
            resolve(FollowKind.UNDO, null, "undo", action("swipe_up", confirm = "no visible change"), emptyList()))
    }

    // --- memory --------------------------------------------------------------------------------------------------------

    @Test fun theSlotAgesOutAndSwitchesOnApp() {
        val m = FollowupMemory()
        m.record(action("swipe_up"))
        assertEquals("swipe_up", (m.current(1000L + 30_000, "app") as Last.Action).action)   // exactly the window edge
        assertNull(m.current(1000L + 30_001, "app"))                                        // older than 30 s
        // before a confirm arrives the app must equal appBefore
        assertNotNull(m.current(2000, "app")); assertNull(m.current(2000, "other"))
    }

    @Test fun confirmFillsByWatchIdAndAppAfterGoverns() {
        val m = FollowupMemory()
        m.record(Last.Action("swipe_up", "listening", 1000L, "appA", watch = 42L))
        m.onConfirm(99L, "confirmed (events)", "by", "appB")   // wrong watch: ignored
        val un = m.current(2000, "appA"); assertNull((un as Last.Action).confirm)
        m.onConfirm(42L, "confirmed (events)", "TYPE_WINDOW_STATE_CHANGED:appB", "appB")
        val done = m.current(2000, "appB") as Last.Action
        assertEquals("confirmed (events)", done.confirm); assertEquals("appB", done.appAfter)
        assertEquals("TYPE_WINDOW_STATE_CHANGED:appB", done.by)
        assertNull(m.current(2000, "appA"))   // now the app must equal appAfter
        m.clear(); assertNull(m.current(2000, "appB"))
    }
}
