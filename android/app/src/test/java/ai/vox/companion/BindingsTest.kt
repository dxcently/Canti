package ai.vox.companion

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class BindingsTest {
    private fun view(profile: Profile = Profile.empty(), pkg: String = "x", micSource: Boolean = false) =
        Bindings.view(profile, pkg, micSource)

    @Suppress("UNCHECKED_CAST")
    private fun sounds(v: Map<String, Any?>, mode: String) = (v[mode] as Map<String, Any?>)["sounds"] as Map<String, Any?>

    @Suppress("UNCHECKED_CAST")
    private fun label(sounds: Map<String, Any?>, sound: String): String? =
        (sounds[sound] as? Map<String, Any?>)?.get("label") as? String?

    private fun source(sounds: Map<String, Any?>, sound: String): String? =
        (sounds[sound] as? Map<String, Any?>)?.get("source") as? String?

    @Suppress("UNCHECKED_CAST")
    private fun combos(v: Map<String, Any?>, mode: String) = (v[mode] as Map<String, Any?>)["combos"] as List<Map<String, Any?>>

    @Test fun gestureDefaults() {
        val s = sounds(view(), "gesture")
        assertEquals("swipe up", label(s, "rise"))
        assertEquals("swipe down", label(s, "fall"))
        assertEquals("swipe right", label(s, "arch"))
        assertEquals("swipe left", label(s, "dip"))
        assertEquals("long-press / hold", label(s, "flat"))
        assertEquals("tap the screen", label(s, "pop"))
        assertNull(label(s, "click"))                 // a lone click is unbound
        assertEquals("go back", label(s, "hiss"))
        assertEquals("default", source(s, "rise"))
    }

    @Test fun gestureCombos() {
        val c = combos(view(), "gesture")
        assertEquals(
            listOf(listOf("pop", "pop"), listOf("click", "click"), listOf("hiss", "click"), listOf("click", "hiss")),
            c.map { it["seq"] })
        assertEquals("listen for a spoken phrase", c[0]["label"])
        assertEquals("go to the home screen", c[1]["label"])
        assertEquals("go back", c[2]["label"])
        assertEquals("go forward", c[3]["label"])     // the app-only binding the old static window omitted
        assertEquals("app-only", c[3]["source"])
    }

    @Test fun cursorDefaults() {
        val s = sounds(view(), "cursor")
        assertEquals("move cursor up", label(s, "rise"))
        assertEquals("move cursor down", label(s, "fall"))
        assertEquals("move cursor right", label(s, "arch"))
        assertEquals("move cursor left", label(s, "dip"))
        assertEquals("stop", label(s, "flat"))
        assertEquals("click", label(s, "pop"))
        assertNull(label(s, "click"))                 // a lone click is unbound in cursor mode
        assertEquals("back", label(s, "hiss"))
        // pop pop names a target in cursor mode (the app owns it: VoxService.resolveInput)
        val c = combos(view(), "cursor")
        assertEquals(listOf(Profile.CURSOR_LISTEN), c.map { it["seq"] })
        assertEquals("listen for a target name", c[0]["label"])
        assertNull((view()["cursor"] as Map<String, Any?>)["note"])
    }

    @Test fun appRuleOverridesDefault() {
        val p = Profile.parse(JSONObject("""{"app:app.organicmaps":[{"phrase":["rise"],"kind":"fixed","action":"zoom_in"}]}"""))
        val s = sounds(view(p, "app.organicmaps"), "gesture")
        assertEquals("zoom in", label(s, "rise"))
        assertEquals("app", source(s, "rise"))
        // another app keeps the default
        assertEquals("swipe up", label(sounds(view(p, "org.schabi.newpipe"), "gesture"), "rise"))
    }

    @Test fun globalRuleOverridesDefault() {
        val p = Profile.parse(JSONObject("""{"global":[{"phrase":["hiss"],"kind":"fixed","action":"notifications"}]}"""))
        assertEquals("open the notification shade", label(sounds(view(p), "gesture"), "hiss"))
    }

    @Test fun cursorRuleOverridesBuiltIn() {
        val p = Profile.parse(JSONObject("""{"cursor":[{"phrase":["hiss"],"kind":"fixed","action":"drag_toggle"},
            {"phrase":["click","click"],"kind":"fixed","action":"drag_toggle"}]}"""))
        val s = sounds(view(p), "cursor")
        assertEquals("start or end a drag at the cursor", label(s, "hiss"))
        assertEquals("cursor", source(s, "hiss"))
        // a user cursor rule binds a combo that otherwise would not act
        val c = combos(view(p), "cursor")
        assertEquals(listOf(listOf("pop", "pop"), listOf("click", "click")), c.map { it["seq"] })
        assertEquals("start or end a drag at the cursor", c[1]["label"])   // a cursor action's text, not its key
        // a cursor rule on pop pop replaces the app's target listening
        val q = Profile.parse(JSONObject("""{"cursor":[{"phrase":["pop","pop"],"kind":"fixed","action":"drag_toggle"}]}"""))
        assertEquals(listOf(mapOf("seq" to listOf("pop", "pop"), "label" to "start or end a drag at the cursor", "source" to "cursor")),
            combos(view(q), "cursor"))
    }

    @Test fun disabledRuleShowsIgnored() {
        val p = Profile.parse(JSONObject("""{"global":[{"phrase":["pop"],"kind":"fixed","action":"none"}]}"""))
        val s = sounds(view(p), "gesture")
        assertEquals("ignored", label(s, "pop"))
        assertEquals("global", source(s, "pop"))
    }

    @Test fun micPopHasNoDefault() {
        // The phone/USB mic's lone pop taps only where bound (MicPopGate.unbound).
        assertEquals("tap only if bound", label(sounds(view(micSource = true), "gesture"), "pop"))
        val p = Profile.parse(JSONObject("""{"global":[{"phrase":["pop"],"kind":"fixed","action":"tap"}]}"""))
        assertEquals("tap the screen", label(sounds(view(p, micSource = true), "gesture"), "pop"))
        // the Pico keeps pop = tap
        assertEquals("tap the screen", label(sounds(view(micSource = false), "gesture"), "pop"))
    }

    @Test fun cursorNoteNamesTheJoystickOnAMic() {
        assertEquals(Bindings.JOYSTICK_NOTE, (view(micSource = true)["cursor"] as Map<String, Any?>)["note"])
    }

    @Test fun micCursorHumsSteerTheJoystick() {
        // VoiceJoystick.filter drops every mic sound but pop / click / hiss in cursor mode: a cursor rule on a hum never fires.
        val p = Profile.parse(JSONObject("""{"cursor":[{"phrase":["rise"],"kind":"fixed","action":"click"}]}"""))
        val s = sounds(view(p, micSource = true), "cursor")
        for (h in listOf("rise", "fall", "arch", "dip", "flat")) assertEquals(Bindings.JOYSTICK, label(s, h))
        assertEquals("click", label(s, "pop"))
        assertEquals("back", label(s, "hiss"))
        assertNull(label(s, "click"))
        assertEquals("click at the cursor", label(sounds(view(p), "cursor"), "rise"))   // the Pico: the rule acts
    }

    // --- parity with the rule decider (what acts), so this display-only mirror cannot drift silently -------------

    private fun heard(label: String) = when (label) {
        "pop", "click" -> "${Vocab.DISCRETE[label]}; instant sound; loudness normal; sounds like mouth sound"
        "hiss" -> "a hiss; duration short (150-400 ms); loudness normal; sounds like mouth sound"
        "flat" -> "hum that stays level; pitch change small (under 2 semitones); duration medium (400-1000 ms); tone clear tone; loudness normal; sounds like hum"
        else -> "hum that ${Vocab.CONTOURS[label]}; pitch change large (over 4 semitones); duration short (150-400 ms); tone clear tone; loudness normal; sounds like hum"
    }

    private fun decide(seq: List<String>, mode: String, profile: Profile, pkg: String): String {
        val scene = StateBuilder.build(mode, pkg, "Fixture", seq.map(::heard), seq, null, profile, emptyList(), null, null)
        return RuleDecider().decide(DecisionInput(scene, profile)).action
    }

    /** The texts [Bindings] may show for a decided action key (the built-in cursor uses short words, no speed). */
    private fun shown(action: String, mode: String): Set<String?> = when {
        action == "none" -> setOf(null)
        mode == "cursor" -> setOf(Vocab.CURSOR_ACTIONS[action], Vocab.CURSOR_ACTIONS[action]?.removeSuffix(" slow"),
            mapOf("stop" to "stop", "click" to "click", "back" to "back")[action])
        else -> setOf(Vocab.ACTIONS[action] ?: Vocab.APP_ONLY_ACTIONS[action])
    }

    private val ruleProfile = Profile.parse(JSONObject("""{"global":[{"phrase":["hiss"],"kind":"fixed","action":"notifications"},
        {"phrase":["click","click"],"kind":"fixed","action":"recents"},{"phrase":["pop"],"kind":"fixed","action":"none"}],
        "app:a.b":[{"phrase":["rise"],"kind":"fixed","action":"zoom_in"},{"phrase":["hiss","click"],"kind":"fixed","action":"none"},
            {"phrase":["rise"],"kind":"fixed","action":"zoom_out"}],
        "cursor":[{"phrase":["hiss"],"kind":"fixed","action":"drag_toggle"},{"phrase":["click","click"],"kind":"fixed","action":"stop"}]}"""))

    @Test fun matchesTheRuleDeciderOnThePico() {
        for (p in listOf(Profile.empty(), ruleProfile)) for (pkg in listOf("a.b", "c.d")) {
            val v = view(p, pkg)
            for (mode in listOf("gesture", "cursor")) {
                val s = sounds(v, mode)
                for (sound in Bindings.SOUNDS) {
                    val got = label(s, sound).takeIf { it != "ignored" }
                    val want = shown(decide(listOf(sound), mode, p, pkg), mode)
                    org.junit.Assert.assertTrue("$mode $sound in $pkg: shown '$got', decider $want", got in want)
                }
                val shownCombos = combos(v, mode).associate {
                    @Suppress("UNCHECKED_CAST") (it["seq"] as List<String>) to it["label"] as String
                }
                for (a in Bindings.SOUNDS) for (b in Bindings.SOUNDS) {
                    val seq = listOf(a, b)
                    // cursor pop pop is the app's (VoxService.resolveInput), not the decider's
                    if (mode == "cursor" && seq == Profile.CURSOR_LISTEN && p.cursorBindings().none { it.phrase == seq }) {
                        assertEquals(Bindings.CURSOR_LISTEN_LABEL, shownCombos[seq]); continue
                    }
                    val act = decide(seq, mode, p, pkg)
                    val want = if (act == "none") null
                        else if (mode == "cursor") Vocab.CURSOR_ACTIONS[act] else Vocab.ACTIONS[act] ?: Vocab.APP_ONLY_ACTIONS[act]
                    assertEquals("$mode $seq in $pkg", want, shownCombos[seq])
                }
            }
        }
    }

    /**
     * The Flutter fallback (`ui/lib/src/backend.dart` VoxBindings.defaults) must equal what the service sends with no
     * rules on the Pico. The Flutter test (status_screen_test.dart) compares the fallback against this fixture; this
     * test fails when the fixture is stale (VOX_WRITE_FIXTURES=1 rewrites it).
     */
    @Test fun defaultsFixtureForFlutter() {
        val f = java.io.File("../../ui/test/fixtures/bindings_defaults.json")
        val want = JSONObject(Bindings.view(Profile.empty(), "", micSource = false))
        if (System.getenv("VOX_WRITE_FIXTURES") == "1" || !f.exists()) { f.parentFile.mkdirs(); f.writeText(want.toString(2) + "\n") }
        org.junit.Assert.assertTrue("ui/test/fixtures/bindings_defaults.json is stale (VOX_WRITE_FIXTURES=1 rewrites it):\n$want",
            JsonMaps.of(want) == JsonMaps.of(JSONObject(f.readText())))
    }
}
