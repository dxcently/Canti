package ai.vox.companion

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The phone mic hears the room (user decision 2026-09-27): its lone pop has no default action (the user's rule is the
 * allow-list), cursor mode keeps pop = click, the Pico keeps pop = tap, and outward actions stay gated in social apps.
 */
class MicPopGateTest {
    private val yt = "com.google.android.youtube"
    private val ig = "com.instagram.android"
    private val docs = "org.wikipedia"

    /** The service's order (VoxService.resolveInput then act): unbound -> the rules -> the gate. */
    private fun outcome(usesMic: Boolean, seq: List<String>, pkg: String = yt, mode: String = "gesture", profile: Profile = Profile.empty()): String {
        val bound = profile.appBindings(pkg).any { it.phrase == seq } || profile.globalBindings().any { it.phrase == seq }
        if (MicPopGate.unbound(usesMic, mode, seq, bound)) return "unbound"
        val scene = StateBuilder.build(mode, pkg, "App", seq, seq, null, profile, emptyList(), null, null)
        val action = RuleDecider().decide(DecisionInput(scene, profile)).action
        return if (MicPopGate.gates(usesMic, pkg, seq, action, mode, bound)) "gated" else action
    }

    @Test fun phoneMicPopDoesNothingByDefault() {
        assertEquals("unbound", outcome(usesMic = true, seq = listOf("pop")))
        assertEquals("unbound", outcome(true, listOf("pop"), pkg = docs))   // in any app, not only social ones
    }

    @Test fun aUserRuleIsTheAllowList() {
        val global = Profile.parse(JSONObject("""{"global":[{"phrase":["pop"],"kind":"fixed","action":"tap"}]}"""))
        assertEquals("tap", outcome(true, listOf("pop"), profile = global))
        val perApp = Profile.parse(JSONObject("""{"app:$docs":[{"phrase":["pop"],"kind":"fixed","action":"tap"}]}"""))
        assertEquals("tap", outcome(true, listOf("pop"), pkg = docs, profile = perApp))
        assertEquals("unbound", outcome(true, listOf("pop"), pkg = yt, profile = perApp))   // that app only
    }

    @Test fun cursorModeClicksFromEverySource() {
        assertEquals("click", outcome(true, listOf("pop"), mode = "cursor"))
        assertEquals("click", outcome(false, listOf("pop"), mode = "cursor"))
    }

    @Test fun thePicoIsUnchanged() {
        assertEquals("tap", outcome(false, listOf("pop")))
        assertEquals("tap", outcome(false, listOf("pop"), pkg = ig))
    }

    @Test fun popPopStillListensFromThePhoneMic() {
        assertFalse(MicPopGate.unbound(true, "gesture", listOf("pop", "pop"), false))
        assertFalse(MicPopGate.gates(true, ig, listOf("pop", "pop"), "listen_for_phrase"))
    }

    @Test fun unboundTapsAndOutwardActionsAreGated() {
        // the round-4 incident (00:22:29): a mouth-sound pop decided as tap(center) in YouTube, e.g. by a model
        assertTrue(MicPopGate.gates(usesMic = true, app = yt, sequence = listOf("pop"), action = "tap"))
        assertTrue(MicPopGate.gates(true, docs, listOf("hiss", "pop"), "tap"))
        for (a in listOf("double_tap", "like")) assertTrue(a, MicPopGate.gates(true, ig, listOf("pop"), a))
        assertTrue(MicPopGate.gates(true, ig, listOf("hiss", "pop"), "follow_user"))
        // a user binding never gets an outward action past the gate in a social app
        assertTrue(MicPopGate.gates(true, ig, listOf("click", "click"), "like", userBound = true))
        val like = Profile.parse(JSONObject("""{"app:$ig":[{"phrase":["pop"],"kind":"fixed","action":"like"}]}"""))
        assertEquals("gated", outcome(true, listOf("pop"), pkg = ig, profile = like))
        assertFalse("a bound tap is the user's", MicPopGate.gates(true, yt, listOf("pop"), "tap", userBound = true))
        assertFalse("cursor click", MicPopGate.gates(true, yt, listOf("pop"), "click", mode = "cursor"))
    }

    @Test fun navigationScrollAndHumsAreNotGated() {
        assertFalse(MicPopGate.gates(true, ig, listOf("click", "click"), "home"))
        assertFalse(MicPopGate.gates(true, ig, listOf("hiss", "click"), "back"))
        assertFalse("a hum is not a pop", MicPopGate.gates(true, ig, listOf("flat"), "tap"))
        assertFalse(MicPopGate.gates(true, ig, listOf("rise"), "swipe_up"))
        assertFalse("the Pico", MicPopGate.gates(false, yt, listOf("pop"), "tap"))
        assertFalse("the Pico", MicPopGate.unbound(false, "gesture", listOf("pop"), false))
    }

    @Test fun confirmPopForOutwardOnly() {
        assertTrue(MicPopGate.gatesConfirm(true, ig, "like"))
        assertTrue(MicPopGate.gatesConfirm(true, ig, "tap Follow"))
        assertFalse("a risky but private action still confirms", MicPopGate.gatesConfirm(true, ig, "open_camera"))
        assertFalse(MicPopGate.gatesConfirm(false, ig, "like"))
        assertFalse(MicPopGate.gatesConfirm(true, docs, "like"))
    }
}
