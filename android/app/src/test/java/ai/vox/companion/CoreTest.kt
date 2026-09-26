package ai.vox.companion

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.ServerSocket
import kotlin.concurrent.thread

private fun resource(name: String) = CoreTest::class.java.classLoader!!.getResource(name)!!.readText()
private fun JSONArray?.strings() = if (this == null) emptyList() else List(length()) { getString(it) }

/** Parse a generate.py context back into a Scene (inverse of Scene.text for the fields the rule decider reads). */
fun parseContext(ctx: String): Scene {
    val lines = ctx.split("\n")
    var mode = "gesture"; var app = ""; var name = ""; var screen: ScreenContext? = null; var cursor: String? = null
    var phrase: String? = null; val heard = mutableListOf<String>(); var seq = emptyList<String>()
    for (l in lines) when {
        l.startsWith("mode: ") -> mode = l.removePrefix("mode: ")
        l.startsWith("app: ") -> { name = l.removePrefix("app: ").substringBeforeLast(" ("); app = l.substringAfterLast("(").removeSuffix(")") }
        l.startsWith("screen: ") -> {
            val m = Regex("screen: (.*); media (.*); scroll (.*); keyboard (.*)").matchEntire(l)!!.groupValues
            screen = ScreenContext(m[1], m[2], m[3], m[4])
        }
        l.startsWith("cursor: ") -> cursor = l.removePrefix("cursor: ")
        l.startsWith("spoken phrase: ") -> phrase = l.removePrefix("spoken phrase: ").removeSurrounding("\"")
        l.startsWith("sound ") -> heard += l.substringAfter(": ")
        l.startsWith("sequence: ") -> seq = l.removePrefix("sequence: ").split(" then ")
    }
    return Scene(mode, app, name, heard, seq, emptyList(), phrase, emptyList(), cursor, screen)
}

class CoreTest {
    private val parity = JSONObject(resource("state_parity.json"))

    @Test fun stateTextMatchesGeneratePy() {
        val scenes = parity.getJSONArray("scenes")
        for (i in 0 until scenes.length()) {
            val c = scenes.getJSONObject(i)
            val scr = c.optJSONArray("screen")?.strings()
            val scene = Scene(
                mode = c.getString("mode"), app = c.getString("app"), appName = c.getString("app_name"),
                heard = c.getJSONArray("heard").strings(), sequence = c.getJSONArray("sequence").strings(),
                rules = c.getJSONArray("rules").strings(), phrase = if (c.isNull("phrase")) null else c.getString("phrase"),
                recent = c.getJSONArray("recent").strings(), cursor = if (c.isNull("cursor")) null else c.getString("cursor"),
                screen = scr?.let { ScreenContext(it[0], it[1], it[2], it[3]) },
            )
            assertEquals("scene $i", c.getString("text"), scene.text())
        }
        assertTrue(scenes.length() >= 100)
    }

    @Test fun ruleDeciderReproducesGeneratorLabels() {
        val rows = parity.getJSONArray("rows")
        val d = RuleDecider()
        val wrong = mutableListOf<String>()
        for (i in 0 until rows.length()) {
            val r = rows.getJSONObject(i)
            val got = d.decide(DecisionInput(parseContext(r.getString("context")), Profile.empty())).action
            if (got != r.getString("answer")) wrong += "${r.getString("kind")}: want ${r.getString("answer")} got $got\n${r.getString("context")}"
        }
        // Unknown phrases (outside schema.PHRASES) are the one legitimate gap: generate.py's plain "phrase" rows only
        // use schema.PHRASES and mumbles, so there should be none.
        assertEquals(wrong.joinToString("\n\n"), 0, wrong.size)
    }

    @Test fun defaultBindingsAreTheAgreedOnes() {
        assertEquals("back", Vocab.DEFAULT_BINDINGS[listOf("hiss")])
        assertEquals("tap", Vocab.DEFAULT_BINDINGS[listOf("pop")])
        assertEquals("long_press", Vocab.DEFAULT_BINDINGS[listOf("flat")])
        assertEquals("listen_for_phrase", Vocab.DEFAULT_BINDINGS[listOf("click", "pop")])
        assertFalse(listOf("pop", "pop") in Vocab.DEFAULT_BINDINGS)
        assertFalse(listOf("click", "click") in Vocab.DEFAULT_BINDINGS)
    }

    private fun sound(label: String, loud: String = "normal") = when (label) {
        "pop", "click" -> "${Vocab.DISCRETE[label]}; instant sound; loudness $loud; sounds like mouth sound"
        "hiss" -> "a hiss; duration short (150-400 ms); loudness $loud; sounds like mouth sound"
        "flat" -> "hum that stays level; pitch change small (under 2 semitones); duration medium (400-1000 ms); tone clear tone; loudness $loud; sounds like hum"
        else -> "hum that ${Vocab.CONTOURS[label]}; pitch change large (over 4 semitones); duration short (150-400 ms); tone clear tone; loudness $loud; sounds like hum"
    }

    private fun decide(seq: List<String>, pkg: String = "ai.vox.fixture", mode: String = "gesture", profile: Profile = Profile.empty(),
                       screen: ScreenContext? = null, phrase: String? = null): Decision {
        val scene = StateBuilder.build(mode, pkg, "Fixture", seq.map { sound(it) }, seq, phrase, profile, emptyList(), null, screen)
        return RuleDecider().decide(DecisionInput(scene, profile))
    }

    @Test fun ruleDeciderDefaultsAndProfiles() {
        assertEquals("swipe_up", decide(listOf("rise")).action)
        assertEquals("swipe_down", decide(listOf("fall")).action)
        assertEquals("swipe_right", decide(listOf("arch")).action)
        assertEquals("swipe_left", decide(listOf("dip")).action)
        assertEquals("tap", decide(listOf("pop")).action)
        assertEquals("back", decide(listOf("hiss")).action)
        assertEquals("long_press", decide(listOf("flat")).action)
        assertEquals("listen_for_phrase", decide(listOf("click", "pop")).action)
        assertEquals("none", decide(listOf("pop", "pop")).action)
        assertEquals("none", decide(listOf("click", "click")).action)
        val maps = Profile.parse(JSONObject(resourceProfile))
        assertEquals("zoom_in", decide(listOf("rise"), "app.organicmaps", profile = maps).action)
        assertEquals("swipe_up", decide(listOf("rise"), "org.schabi.newpipe", profile = maps).action)
        // The screen never vetoes an explicit gesture: a swipe on a non-scrollable screen is still a swipe.
        val flat = ScreenContext("other", "none", "not scrollable", "hidden")
        assertEquals("swipe_up", decide(listOf("rise"), screen = flat).action)
        assertEquals("tap", decide(listOf("pop"), screen = ScreenContext("dialog", "none", "not scrollable", "open")).action)
    }

    @Test fun phraseTieBreak() {
        val feed = ScreenContext("video feed", "playing", "can scroll both ways", "hidden")
        assertEquals("swipe_up", decide(emptyList(), mode = "listening", phrase = "next", screen = feed).action)
        assertEquals("next_item", decide(emptyList(), mode = "listening", phrase = "next", screen = null).action)
        assertEquals("none", decide(emptyList(), mode = "listening", phrase = "play", screen = feed).action)
        assertEquals("play_pause", decide(emptyList(), mode = "listening", phrase = "pause", screen = feed).action)
        val p = Profile.parse(JSONObject("""{"phrases":[{"say":"next","kind":"fixed","action":"notifications"}]}"""))
        assertEquals("explicit phrase rule beats the screen", "notifications",
            decide(emptyList(), mode = "listening", phrase = "next", screen = feed, profile = p).action)
    }

    @Test fun cursorDefaults() {
        val loud = StateBuilder.build("cursor", "x", "X", listOf(sound("rise", "loud")), listOf("rise"), null, Profile.empty(), emptyList(), "stopped", null)
        assertEquals("move_up_fast", RuleDecider().decide(DecisionInput(loud, Profile.empty())).action)
        assertEquals("move_left_slow", decide(listOf("dip"), mode = "cursor").action)
        assertEquals("click", decide(listOf("pop"), mode = "cursor").action)
        assertEquals("stop", decide(listOf("flat"), mode = "cursor").action)
        assertEquals("back", decide(listOf("hiss"), mode = "cursor").action)
        assertEquals("none", decide(listOf("click", "click"), mode = "cursor").action)
    }

    private val resourceProfile = """{"app:app.organicmaps":[{"phrase":["rise"],"kind":"fixed","action":"zoom_in"},
        {"phrase":["fall"],"kind":"fixed","action":"zoom_out"}]}"""

    // --- sequencer timing rule --------------------------------------------------------------------------------------

    private class FakeScheduler : Scheduler {
        var t = 0L
        val tasks = mutableListOf<Pair<Long, () -> Unit>>()
        override fun now() = t
        override fun schedule(delayMs: Long, task: () -> Unit): () -> Unit {
            val e = (t + delayMs) to task; tasks += e; return { tasks.remove(e) }
        }
        fun advance(ms: Long) {
            t += ms
            tasks.filter { it.first <= t }.forEach { tasks.remove(it); it.second() }
        }
    }

    private fun seqHarness(bound: Set<List<String>>): Triple<FakeScheduler, Sequencer, MutableList<Pair<List<String>, Long>>> {
        val s = FakeScheduler()
        val out = mutableListOf<Pair<List<String>, Long>>()
        val q = Sequencer(s, { 600L }, onResolve = { out += it.sequence.toList() to s.t })
        return Triple(s, q, out)
    }

    @Test fun popActsAtOnceWithDefaults() {
        val bound = Profile.empty().boundSequences("x", "gesture")
        val (_, q, out) = seqHarness(bound)
        q.add("gesture", "x", listOf("l"), listOf("pop"), bound)
        assertEquals(listOf(listOf("pop") to 0L), out)
    }

    @Test fun clickWaitsForBoundClickPop() {
        val bound = Profile.empty().boundSequences("x", "gesture")
        val (s, q, out) = seqHarness(bound)
        q.add("gesture", "x", listOf("l"), listOf("click"), bound)
        assertTrue(out.isEmpty())
        s.advance(200)
        q.add("gesture", "x", listOf("l"), listOf("pop"), bound)
        assertEquals(listOf(listOf("click", "pop") to 200L), out)
    }

    @Test fun lonelyClickResolvesAfterGap() {
        val bound = Profile.empty().boundSequences("x", "gesture")
        val (s, q, out) = seqHarness(bound)
        q.add("gesture", "x", listOf("l"), listOf("click"), bound)
        s.advance(599); assertTrue(out.isEmpty())
        s.advance(1); assertEquals(listOf(listOf("click") to 600L), out)
    }

    @Test fun popWaitsOnlyWhenProfileBindsPopPop() {
        val p = Profile.parse(JSONObject("""{"app:ai.vox.fixture":[{"phrase":["pop","pop"],"kind":"fixed","action":"like"}]}"""))
        val bound = p.boundSequences("ai.vox.fixture", "gesture")
        val (s, q, out) = seqHarness(bound)
        q.add("gesture", "ai.vox.fixture", listOf("l"), listOf("pop"), bound)
        assertTrue("pop must wait when pop pop is bound", out.isEmpty())
        s.advance(600)
        assertEquals(listOf(listOf("pop") to 600L), out)
        // Other apps are unaffected.
        assertFalse(listOf("pop", "pop") in p.boundSequences("other.app", "gesture"))
    }

    @Test fun disablingClickPopStopsClickWaiting() {
        val p = Profile.parse(JSONObject("""{"global":[{"phrase":["click","pop"],"kind":"fixed","action":"none"}]}"""))
        assertFalse(listOf("click", "pop") in p.boundSequences("x", "gesture"))
    }

    // --- device timestamps: grouping by device gaps, not arrival --------------------------------------------------

    /** Harness that keeps the resolved Pending objects (clock, endedBy, gaps) and their local resolve times. */
    private fun stampHarness(): Triple<FakeScheduler, Sequencer, MutableList<Pair<Sequencer.Pending, Long>>> {
        val s = FakeScheduler()
        val out = mutableListOf<Pair<Sequencer.Pending, Long>>()
        val q = Sequencer(s, { 600L }, { 150L }, onResolve = { out += it to s.t })
        return Triple(s, q, out)
    }
    private val defaults = Profile.empty().boundSequences("x", "gesture")
    private fun Sequencer.sound(label: String, st: Stamp?) = add("gesture", "x", listOf("l"), listOf(label), defaults, st?.let { listOf(it) })
    private fun seqs(out: List<Pair<Sequencer.Pending, Long>>) = out.map { it.first.sequence.joinToString(" ") }

    @Test fun lateFollowUpStillMergesByDeviceGap() {
        // Link latency is normally 60 ms. click ends at device 40 and arrives at local 100. pop starts 360 ms after
        // the click ended (a real "click pop"), but a latency spike delivers it at local 800: 700 ms after the click
        // arrived, more than gap_ms. By arrival that is two sounds; by device time it is one sequence.
        val (s, q, out) = stampHarness()
        s.advance(100); q.sound("click", Stamp(0, 40))
        s.advance(700)
        q.sound("pop", Stamp(400, 430))
        assertEquals(listOf("click pop"), seqs(out))
        val p = out[0].first
        assertEquals("device", p.clock); assertEquals(listOf(360L), p.gapsMs); assertEquals("no-continuation", p.endedBy)

        // The same arrivals without stamps split (arrival fallback).
        val (s2, q2, out2) = stampHarness()
        s2.advance(100); q2.sound("click", null)
        s2.advance(700); q2.sound("pop", null)
        assertEquals(listOf("click", "pop"), seqs(out2))
        assertEquals("arrival", out2[0].first.clock); assertEquals("timeout", out2[0].first.endedBy)
    }

    @Test fun burstAfterStallIsSplitByDeviceGap() {
        // Warm-up establishes the normal offset (60 ms). Then a stall delivers a click 300 ms late and the next pop
        // 50 ms later. By arrival that is "click pop" (listen); the device says the pop came 660 ms after the click.
        val (s, q, out) = stampHarness()
        s.advance(90); q.sound("pop", Stamp(0, 30))
        s.advance(1310); q.sound("click", Stamp(1000, 1040))          // arrives at 1400: lag 300
        s.advance(50); q.sound("pop", Stamp(1700, 1730))              // arrives at 1450, device gap 660
        assertEquals(listOf("pop", "click", "pop"), seqs(out))
        assertEquals("device-gap", out[1].first.endedBy)
        assertTrue(out[2].first.note!!.startsWith("split: device gap 660 ms"))

        // Arrival fallback with the same arrival times merges them.
        val (s2, q2, out2) = stampHarness()
        s2.advance(1400); q2.sound("click", null)
        s2.advance(50); q2.sound("pop", null)
        assertEquals(listOf("click pop"), seqs(out2))
    }

    @Test fun waitIsShortenedByTheWaitingSoundsOwnLateness() {
        val (s, q, out) = stampHarness()
        s.advance(90); q.sound("pop", Stamp(0, 30))                   // offset 60
        s.advance(1310); q.sound("click", Stamp(1000, 1040))          // lag 300 -> wait max(0, 600-300) + 150 = 450
        assertEquals(450L, q.waitDelay(s.t, Stamp(1000, 1040)))
        s.advance(449); assertEquals(1, out.size)
        s.advance(1); assertEquals(listOf("pop", "click"), seqs(out))
        assertEquals("timeout", out[1].first.endedBy)
        // Without stamps the wait is the plain gap.
        assertEquals(600L, q.waitDelay(s.t, null))
    }

    @Test fun oneMessageWithTwoStampedSoundsSplitsOnDeviceGap() {
        val (_, q, out) = stampHarness()
        q.add("gesture", "x", listOf("l", "l"), listOf("click", "pop"), defaults, listOf(Stamp(0, 40), Stamp(940, 980)))
        assertEquals(listOf("click", "pop"), seqs(out))
        val (_, q2, out2) = stampHarness()
        q2.add("gesture", "x", listOf("l", "l"), listOf("click", "pop"), defaults, listOf(Stamp(0, 40), Stamp(240, 280)))
        assertEquals(listOf("click pop"), seqs(out2))
    }

    @Test fun deviceClockResetSplits() {
        val (s, q, out) = stampHarness()
        s.advance(100); q.sound("click", Stamp(50_000, 50_040))
        s.advance(100); q.sound("pop", Stamp(10, 40))                 // device rebooted: clock went back
        assertEquals(listOf("click", "pop"), seqs(out))
        assertEquals("device-clock-reset", out[0].first.endedBy)
    }

    @Test fun messageTimingParsing() {
        val m = FeatureMessage.parse(JSONObject("""{"sounds":["a","b"],"sequence":["click","pop"],
            "timing":[{"t_start_ms":100,"t_end_ms":140},{"t_start_ms":400,"t_end_ms":430}]}"""))
        assertEquals(listOf(Stamp(100, 140), Stamp(400, 430)), m.timing)
        assertEquals(null, FeatureMessage.parse(JSONObject("""{"sounds":["a"],"sequence":["pop"]}""")).timing)
        for (b in listOf(
            """{"sounds":["a"],"sequence":["pop"],"timing":[]}""",
            """{"sounds":["a"],"sequence":["pop"],"timing":[{"t_start_ms":10,"t_end_ms":5}]}""",
            """{"sounds":["a","b"],"sequence":["pop","pop"],"timing":[{"t_start_ms":10,"t_end_ms":20},{"t_start_ms":5,"t_end_ms":8}]}""",
        )) {
            try { FeatureMessage.parse(JSONObject(b)); throw AssertionError("accepted $b") } catch (_: IllegalArgumentException) {}
        }
    }

    // --- cursor mode: button only; click click unbound unless a rule binds it -------------------------------------

    @Test fun cursorModeIsButtonOnly() {
        assertFalse("enter_cursor_mode" in Vocab.ACTIONS)
        assertFalse("exit_cursor_mode" in Vocab.CURSOR_ACTIONS)
        assertEquals(25, Vocab.ACTIONS.size)
        assertEquals(24, Vocab.CURSOR_ACTIONS.size)
        // Only "click pop" (name a target, handled by the app) is bound in cursor mode by default.
        assertEquals(setOf(Profile.CURSOR_LISTEN), Profile.empty().boundSequences("x", "cursor"))
        val p = Profile.parse(JSONObject("""{"cursor":[{"phrase":["click","click"],"kind":"fixed","action":"drag_toggle"}]}"""))
        assertEquals(setOf(listOf("click", "click"), Profile.CURSOR_LISTEN), p.boundSequences("x", "cursor"))
        val off = Profile.parse(JSONObject("""{"cursor":[{"phrase":["click","pop"],"kind":"fixed","action":"none"}]}"""))
        assertTrue("a cursor rule can switch click pop off", off.boundSequences("x", "cursor").isEmpty())
        assertEquals("drag_toggle", decide(listOf("click", "click"), mode = "cursor", profile = p).action)
    }

    /** The options go out in schema dict order (Vocab maps are generated in that order; the request iterates them). */
    @Test fun optionOrderMatchesSchema() {
        val order = parity.getJSONObject("option_order")
        assertEquals(order.getJSONArray("actions").strings(), Vocab.ACTIONS.keys.toList())
        assertEquals(order.getJSONArray("cursor_actions").strings(), Vocab.CURSOR_ACTIONS.keys.toList())
        val scene = StateBuilder.build("gesture", "x", "X", listOf(sound("rise")), listOf("rise"), null, Profile.empty(), emptyList(), null, null)
        assertEquals(Vocab.ACTIONS.values.toList(), DecisionInput(scene, Profile.empty()).options.values.toList())
    }

    // --- confirmer: echo events and pixel grid ----------------------------------------------------------------------

    @Test fun confirmerIgnoresEchoesOnlyInsideTheWindow() {
        val clicked = android.view.accessibility.AccessibilityEvent.TYPE_VIEW_CLICKED
        val scrolled = android.view.accessibility.AccessibilityEvent.TYPE_VIEW_SCROLLED
        assertEquals(Confirmer.Kind.ECHO, Confirmer.kind(clicked, inEchoWindow = true))
        assertEquals(Confirmer.Kind.STRONG, Confirmer.kind(clicked, inEchoWindow = false))
        assertEquals(Confirmer.Kind.STRONG, Confirmer.kind(scrolled, inEchoWindow = true))
    }

    @Test fun pixelGridDiffIgnoresMaskedAreas() {
        val w = 36; val h = 80
        fun img(f: (Int, Int) -> Int) = IntArray(w * h) { i -> f(i % w, i / w) }
        val grey = img { _, _ -> 0xFF808080.toInt() }
        val mask = listOf(intArrayOf(0, 0, 1080, 120))                  // a status bar strip
        val a = PixelGrid.from(w, h, grey, 1080, 2400, mask)
        // Only the masked strip changes (clock tick): no difference.
        val clock = PixelGrid.from(w, h, img { _, y -> if (y < 4) 0xFFFFFFFF.toInt() else 0xFF808080.toInt() }, 1080, 2400, mask)
        assertEquals(0.0, a.diff(clock), 0.0)
        // A map redraw in the middle: a real change.
        val map = PixelGrid.from(w, h, img { _, y -> if (y in 30..50) 0xFF203040.toInt() else 0xFF808080.toInt() }, 1080, 2400, mask)
        assertTrue(a.diff(map) > 0.2)
        assertEquals(a.hash(), PixelGrid.from(w, h, grey, 1080, 2400, mask).hash())
    }

    // --- messages and profile ---------------------------------------------------------------------------------------

    @Test fun messageParsing() {
        val m = FeatureMessage.parse(JSONObject("""{"v":1,"id":3,"mode":"gesture","sounds":["a"],"sequence":["rise"]}"""))
        assertEquals(listOf("rise"), m.sequence); assertTrue(m.armed)
        val bad = listOf(
            """{"mode":"gesture","sounds":["a","b"],"sequence":["rise"]}""",
            """{"mode":"flying","sounds":[],"sequence":[]}""",
            """{"sounds":["a"],"sequence":["wobble"]}""",
            """{"v":2,"sounds":["a"],"sequence":["rise"]}""",
        )
        for (b in bad) {
            try { FeatureMessage.parse(JSONObject(b)); throw AssertionError("accepted $b") } catch (_: IllegalArgumentException) {}
        }
        val disarm = FeatureMessage.parse(JSONObject("""{"armed":false}"""))
        assertFalse(disarm.armed)
    }

    @Test fun profileRuleSentencesUseTrainingTemplates() {
        val p = Profile.parse(JSONObject(resourceProfile))
        assertEquals(listOf("In Organic Maps, a rising hum means zoom in.", "In Organic Maps, a falling hum means zoom out."),
            p.ruleTexts("app.organicmaps", "Organic Maps", "gesture"))
        assertEquals(emptyList<String>(), p.ruleTexts("org.videolan.vlc", "VLC", "gesture"))
    }

    // --- screen summariser ------------------------------------------------------------------------------------------

    private fun n(cls: String, l: Int, t: Int, r: Int, b: Int, vararg kids: NodeSnap, scroll: Boolean = false, fwd: Boolean = false,
                  back: Boolean = false, text: String? = null, desc: String? = null, rows: Int = -1, id: String? = null) =
        NodeSnap(cls, id, text, desc, l, t, r, b, scrollable = scroll, canScrollForward = fwd, canScrollBackward = back,
            rows = rows, children = kids.toList())

    private val facts = ScreenFacts("ai.vox.fixture", 1080, 2400, false, setOf("com.android.launcher3"), false)

    @Test fun summariserFeedListStaticHome() {
        val feed = n("android.widget.FrameLayout", 0, 0, 1080, 2400,
            n("ai.vox.fixture.FeedView", 0, 0, 1080, 2400,
                n("android.widget.LinearLayout", 0, 0, 1080, 2400, n("android.widget.TextView", 0, 900, 1080, 1000, text = "Pause", desc = "Pause")),
                scroll = true, fwd = true, rows = 20))
        assertEquals("screen: video feed; media playing; scroll at the top; keyboard hidden", ScreenSummarizer.classify(feed, facts).text())

        val rowsKids = Array(12) { n("android.widget.TextView", 0, it * 200, 1080, it * 200 + 190, text = "Item $it") }
        val list = n("android.widget.ListView", 0, 0, 1080, 2400, *rowsKids, scroll = true, fwd = true, back = true, rows = 100)
        assertEquals("screen: scrolling list; media none; scroll can scroll both ways; keyboard hidden", ScreenSummarizer.classify(list, facts).text())

        val static = n("android.widget.FrameLayout", 0, 0, 1080, 2400, n("android.widget.TextView", 300, 160, 780, 220, text = "Static"))
        assertEquals("screen: other; media none; scroll not scrollable; keyboard hidden", ScreenSummarizer.classify(static, facts).text())

        assertEquals("home screen", ScreenSummarizer.classify(static, facts.copy(pkg = "com.android.launcher3")).kind)
        val web = n("android.widget.FrameLayout", 0, 0, 1080, 2400, n("android.webkit.WebView", 0, 200, 1080, 2400))
        assertEquals("web page", ScreenSummarizer.classify(web, facts).kind)
        val edit = n("android.widget.FrameLayout", 0, 0, 1080, 2400,
            NodeSnap("android.widget.EditText", null, "", null, 0, 100, 1080, 200, editable = true, focused = true))
        assertEquals("screen: text entry; media none; scroll not scrollable; keyboard open",
            ScreenSummarizer.classify(edit, facts.copy(keyboardOpen = true)).text())
        val dialog = n("android.widget.FrameLayout", 100, 800, 980, 1500, n("android.widget.Button", 200, 1300, 500, 1400, text = "OK"))
        assertEquals("dialog", ScreenSummarizer.classify(dialog, facts).kind)

        // A tab pager whose page is a list (NewPipe) is a list, not a feed; a pager showing one still image is a photo viewer.
        val tabs = n("android.widget.FrameLayout", 0, 0, 1080, 2400,
            n("androidx.viewpager.widget.ViewPager", 0, 400, 1080, 2270,
                n("androidx.recyclerview.widget.RecyclerView", 0, 400, 1080, 2270, *rowsKids, scroll = true, fwd = true),
                scroll = true, fwd = true))
        assertEquals("scrolling list", ScreenSummarizer.classify(tabs, facts).kind)
        val photos = n("android.widget.FrameLayout", 0, 0, 1080, 2400,
            n("androidx.viewpager.widget.ViewPager", 0, 0, 1080, 2400,
                n("android.widget.FrameLayout", 0, 0, 1080, 2400, n("android.widget.ImageView", 0, 300, 1080, 2100)),
                scroll = true, fwd = true, back = true))
        assertEquals("photo viewer", ScreenSummarizer.classify(photos, facts).kind)
        val emptyTab = n("android.widget.FrameLayout", 0, 0, 1080, 2400,
            n("androidx.viewpager.widget.ViewPager", 0, 400, 1080, 2270,
                n("android.view.ViewGroup", 0, 400, 1080, 2270, n("android.widget.TextView", 0, 1200, 1080, 1300, text = "Nothing here")),
                scroll = true, fwd = true))
        assertEquals("scrolling list", ScreenSummarizer.classify(emptyTab, facts).kind)
    }

    // --- HTTP decider against a local drop-in /v1/systemone --------------------------------------------------------

    @Test fun httpDeciderRequestAndAnswer() {
        var seen: JSONObject? = null
        var auth: String? = null
        // Minimal HTTP/1.1 server (com.sun.net.httpserver is not on the Android unit-test classpath).
        val server = ServerSocket(0, 5, java.net.InetAddress.getLoopbackAddress())
        thread(isDaemon = true) {
            while (!server.isClosed) {
                val c = try { server.accept() } catch (e: Exception) { break }
                c.use { sock ->
                    val inp = sock.getInputStream().bufferedReader()
                    val headers = generateSequence { inp.readLine() }.takeWhile { it.isNotEmpty() }.toList()
                    val len = headers.first { it.startsWith("Content-Length", true) }.substringAfter(":").trim().toInt()
                    auth = headers.firstOrNull { it.startsWith("Authorization", true) }?.substringAfter(":")?.trim()
                    val buf = CharArray(len); var got = 0
                    while (got < len) got += inp.read(buf, got, len - got)
                    seen = JSONObject(String(buf))
                    val body = """{"model":"test","answers":{"action":{"type":"choice","choice":"swipe up","probabilities":{"swipe up":0.9},"confidence":0.88}}}"""
                    sock.getOutputStream().write(("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: ${body.length}\r\nConnection: close\r\n\r\n$body").toByteArray())
                }
            }
        }
        try {
            val base = "http://127.0.0.1:${server.localPort}"
            val scene = StateBuilder.build("gesture", "ai.vox.fixture", "Fixture", listOf(sound("rise")), listOf("rise"), null,
                Profile.empty(), emptyList(), null, ScreenContext("video feed", "playing", "at the top", "hidden"))
            val d = HttpDecider(base, "jev-1.13.0", { "sk-test" }).decide(DecisionInput(scene, Profile.empty()))
            assertEquals("swipe_up", d.action); assertEquals("model", d.source)
            assertEquals("Bearer sk-test", auth)
            val s = seen!!
            assertEquals("jev-1.13.0", s.getString("model"))
            assertEquals(scene.text(), s.getString("state"))
            val q = s.getJSONObject("questions").getJSONObject("action")
            assertEquals("choice", q.getString("type"))
            assertEquals(Vocab.POLICY, q.getString("instructions"))
            assertEquals(Vocab.ACTIONS.size, q.getJSONObject("criteria").length())
            // Below threshold -> none; no key -> no Authorization header.
            val low = HttpDecider(base, "m", { "" }, minConfidence = 0.95).decide(DecisionInput(scene, Profile.empty()))
            assertEquals("none", low.action); assertEquals(null, auth)
            // Server down -> ChainDecider falls back to the rule table.
            val chain = ChainDecider("model", HttpDecider("http://127.0.0.1:1", "m", { null }, timeoutMs = 300))
            val fb = chain.decide(DecisionInput(scene, Profile.empty()))
            assertEquals("swipe_up", fb.action); assertTrue(fb.source, fb.source.startsWith("model-fallback"))
        } finally { server.close() }
    }
}

/** Intent cursor mode: option building (targets.py format), the answer policy, and the "target" HTTP question. */
class TargetTest {
    private val parity = JSONObject(resource("state_parity.json"))
    private val W = 1080
    private val H = 2400

    private fun node(cls: String, l: Int, t: Int, r: Int, b: Int, vararg kids: NodeSnap, text: String? = null, desc: String? = null,
                     id: String? = null, click: Boolean = true, focus: Boolean = false, visible: Boolean = true, selected: Boolean = false,
                     scroll: Boolean = false, editable: Boolean = false, rows: Int = -1, item: Boolean = false) =
        NodeSnap("android.widget.$cls", id, text, desc, l, t, r, b, scrollable = scroll, editable = editable, clickable = click,
            visible = visible, focusable = focus, selected = selected, collectionItem = item, rows = rows, children = kids.toList())

    private fun root(vararg kids: NodeSnap) = node("FrameLayout", 0, 0, W, H, *kids, click = false)

    @Test fun positionBucketEdges() {
        fun pos(x: Int, y: Int) = Targets.position(x, y, W, H)
        assertEquals("top left", pos(0, 0))
        assertEquals("top left", pos(359, 799))       // just inside the first third on both axes
        assertEquals("top", pos(360, 0))              // exactly on the 1/3 line: the cell to the right
        assertEquals("center", pos(360, 800))
        assertEquals("center", pos(719, 1599))
        assertEquals("right", pos(720, 800))          // on the 2/3 line
        assertEquals("bottom", pos(540, 1600))
        assertEquals("bottom right", pos(1079, 2399))
        assertEquals("bottom right", pos(5000, 9000)) // clamped
        assertEquals("top left", pos(-5, -5))
        assertEquals(TargetVocab.POSITIONS, (0 until 9).map { TargetVocab.POSITIONS[it] })
        assertEquals("center", TargetVocab.POSITIONS[4])
    }

    @Test fun labelFallbackOrder() {
        assertEquals("Like", Targets.label(node("ImageButton", 0, 0, 10, 10, desc = "Like", text = "12", id = "a:id/like_btn")))
        assertEquals("12", Targets.label(node("Button", 0, 0, 10, 10, text = "12", id = "a:id/like_btn")))
        assertEquals("like btn", Targets.label(node("ImageButton", 0, 0, 10, 10, id = "com.x:id/like_btn")))
        assertEquals("unlabeled", Targets.label(node("ImageButton", 0, 0, 10, 10)))
        assertEquals("unlabeled", Targets.label(node("ImageButton", 0, 0, 10, 10, desc = "  \n ")))
        // A row whose title is on a (non-clickable) child: the first such text, before the view id.
        val row = node("LinearLayout", 0, 0, 1080, 200,
            node("ImageView", 0, 0, 100, 100, click = false),
            node("TextView", 100, 0, 1080, 100, text = "Blinding Lights", click = false),
            node("TextView", 100, 100, 1080, 200, text = "The Weeknd", click = false), id = "a:id/row")
        assertEquals("Blinding Lights", Targets.label(row))
        // ...but never the text of a nested clickable element (that one is its own option).
        val card = node("LinearLayout", 0, 0, 1080, 200, node("Button", 0, 0, 200, 100, text = "Follow"), id = "a:id/card_view")
        assertEquals("card view", Targets.label(card))
        // One line, capped.
        assertEquals("Two lines", Targets.label(node("Button", 0, 0, 10, 10, text = "Two\n  lines")))
        val long = Targets.label(node("Button", 0, 0, 10, 10, text = "x".repeat(200)))
        assertEquals(Targets.MAX_LABEL_CHARS, long.length); assertTrue(long.endsWith("..."))
    }

    @Test fun roleMapping() {
        fun role(n: NodeSnap, parent: NodeSnap? = null) = Targets.role(n, parent)
        assertEquals("button", role(node("Button", 0, 0, 10, 10)))
        assertEquals("button", role(node("ImageButton", 0, 0, 10, 10)))
        assertEquals("text field", role(node("EditText", 0, 0, 10, 10)))
        assertEquals("text field", role(node("View", 0, 0, 10, 10, editable = true)))
        assertEquals("switch", role(node("Switch", 0, 0, 10, 10)))
        assertEquals("switch", role(node("CheckBox", 0, 0, 10, 10)))
        assertEquals("image", role(node("ImageView", 0, 0, 10, 10)))
        assertEquals("item", role(node("TextView", 0, 0, 10, 10)))
        val tw = node("TabWidget", 0, 0, 1080, 100, click = false)
        assertEquals("tab", role(node("TextView", 0, 0, 10, 10), tw))
        assertEquals("tab", NodeSnap("android.app.ActionBar\$Tab", null, "Home", null, 0, 0, 10, 10, clickable = true).let { role(it) })
        // A strip of same-class siblings in one row with one selected: bottom navigation / tab layout.
        val a = node("FrameLayout", 0, 2200, 360, 2400, selected = true)
        val b = node("FrameLayout", 360, 2200, 720, 2400)
        val c = node("FrameLayout", 720, 2200, 1080, 2400)
        val strip = node("FrameLayout", 0, 2200, 1080, 2400, a, b, c, click = false)
        assertEquals("tab", role(b, strip))
        // Same row but nothing selected: not a tab strip.
        val plain = node("FrameLayout", 0, 2200, 1080, 2400, node("FrameLayout", 0, 2200, 360, 2400), b, c, click = false)
        assertEquals("item", role(b, plain))
        // List rows.
        val rv = NodeSnap("androidx.recyclerview.widget.RecyclerView", null, null, null, 0, 0, 1080, 2000, scrollable = true, rows = 50)
        assertEquals("list item", role(node("LinearLayout", 0, 0, 1080, 200), rv))
        assertEquals("list item", role(node("LinearLayout", 0, 0, 1080, 200, item = true)))
        for (r in listOf("button", "text field", "switch", "tab", "image", "list item", "item")) assertTrue(r, r in TargetVocab.ROLES)
    }

    @Test fun optionsInReadingOrderDedupedCappedNoneLast() {
        val tree = root(
            node("ImageButton", 950, 2250, 1050, 2350, desc = "Send"),                          // bottom right
            node("ImageButton", 20, 100, 120, 200, desc = "Navigate up"),                       // top left
            node("ImageButton", 950, 700, 1050, 780, desc = "More options"),                    // top right, lower than...
            node("ImageButton", 400, 100, 500, 200, desc = "Search"),                           // top
            node("ImageButton", 30, 700, 130, 780, desc = "Close"),                             // top left, y=740 (after Navigate up)
            node("ImageButton", 950, 2260, 1040, 2340, desc = "Send"),                          // duplicate option: dropped
            node("ImageButton", 500, 1100, 580, 1180, desc = "Play", visible = false),          // invisible: dropped
            node("TextView", 0, 0, 100, 100, text = "Title", click = false),                   // not clickable/focusable
            node("RecyclerView", 0, 300, 1080, 2000, scroll = true, click = false, focus = true), // scrolling container
            node("View", 0, 0, 1080, 2400, focus = true, click = false),                        // huge focusable container
            node("EditText", 100, 2250, 900, 2350, text = "Message", focus = true, click = false), // bottom (focusable only)
            node("Button", 2000, 100, 2100, 200, text = "Offscreen"),                           // centre off screen
        )
        val ts = Targets.build(tree, W, H)
        assertEquals(listOf(
            "Navigate up (button, top left)", "Close (button, top left)", "Search (button, top)", "More options (button, top right)",
            "Message (text field, bottom)", "Send (button, bottom right)"), ts.map { it.option })
        val opts = Targets.options(ts)
        assertEquals(TargetVocab.NONE_OPTION, opts.last()); assertEquals(ts.size + 1, opts.size)
        assertEquals(1000, ts.first { it.label == "Send" }.cx)   // the first of the duplicates is kept
        // Cap: 60 distinct buttons -> 39 targets + none = 40 options, the first 39 in reading order.
        val many = root(*Array(60) { i -> node("Button", 10 + (i % 6) * 170, 10 + (i / 6) * 230, 150 + (i % 6) * 170, 200 + (i / 6) * 230, text = "B$i") })
        val capped = Targets.options(Targets.build(many, W, H))
        assertEquals(Targets.MAX_OPTIONS, capped.size)
        assertEquals(TargetVocab.NONE_OPTION, capped.last())
        assertEquals("B0 (button, top left)", capped.first())
        assertTrue(Targets.build(null, W, H).isEmpty())
        // A focusable, label-less tab strip holding the (focusable) tabs is not an option itself, and does not borrow
        // the selected tab's text.
        val strip = root(node("HorizontalScrollView", 0, 275, 1080, 400,
            node("LinearLayout", 0, 275, 270, 400, node("TextView", 0, 300, 270, 380, text = "Live", click = false), click = false, focus = true, selected = true),
            node("LinearLayout", 270, 275, 540, 400, node("TextView", 270, 300, 540, 380, text = "New", click = false)),
            click = false, focus = true))
        assertEquals(listOf("Live (tab, top left)", "New (tab, top)"), Targets.build(strip, W, H).map { it.option })
    }

    @Test fun stateTextAndOptionFormatMatchTrainingRows() {
        val rows = parity.getJSONArray("targets")
        assertTrue(rows.length() >= 100)
        for (i in 0 until rows.length()) {
            val r = rows.getJSONObject(i)
            val scr = r.getJSONArray("screen").strings()
            val ctx = Targets.stateText(r.getString("app_name"), r.getString("app"), ScreenContext(scr[0], scr[1], scr[2], scr[3]), r.getString("utterance"))
            assertEquals("row $i", r.getString("context"), ctx)
            val opts = r.getJSONArray("options")
            for (j in 0 until opts.length()) {
                val o = opts.getJSONObject(j)
                assertTrue(o.getString("role"), o.getString("role") in TargetVocab.ROLES)
                assertTrue(o.getString("position"), o.getString("position") in TargetVocab.POSITIONS)
                val t = Target(o.getString("label"), o.getString("role"), o.getString("position"), 0, 0, 1, 1)
                assertEquals(o.getString("option"), t.option)
            }
        }
    }

    private fun t(label: String, pos: String = "center") = Target(label, "button", pos, 0, 0, 10, 10)
    private fun ans(choice: String, conf: Double, vararg p: Pair<String, Double>) = ChoiceAnswer(choice, linkedMapOf(*p), conf, 5)

    @Test fun answerPolicy() {
        val ts = listOf(t("Like"), t("Share"), t("Save"), t("Comment"))
        val none = TargetVocab.NONE_OPTION
        assertEquals(Targets.Outcome.NotOnScreen, Targets.resolve(ts, ans(none, 0.9), 0.6))
        assertEquals(Targets.Outcome.NotOnScreen, Targets.resolve(ts, ans(none, 0.2), 0.6))
        assertEquals(Targets.Outcome.Tap(ts[1]), Targets.resolve(ts, ans(ts[1].option, 0.6), 0.6))    // at the threshold: tap
        val low = Targets.resolve(ts, ans(ts[0].option, 0.3, ts[0].option to 0.3, none to 0.28, ts[3].option to 0.2,
            ts[2].option to 0.12, ts[1].option to 0.1), 0.6)
        assertEquals(Targets.Outcome.Choose(listOf(ts[0], ts[3], ts[2])), low)                      // top 3 by p, none skipped
        assertEquals(Targets.Outcome.Choose(listOf(ts[2])), Targets.resolve(ts, ans(ts[2].option, 0.1), 0.6))  // no probabilities
        try { Targets.resolve(ts, ans("Bogus (button, top)", 0.9), 0.6); throw AssertionError("expected a rejection") }
        catch (e: IllegalArgumentException) { assertTrue(e.message!!.contains("unknown option")) }
        // The chooser: rise, rise -> third; fall wraps around.
        val c = TargetChoice(listOf(ts[0], ts[3], ts[2]))
        c.next(); c.next(); assertEquals(ts[2], c.selected)
        c.next(); assertEquals(ts[0], c.selected)
        c.previous(); assertEquals(ts[2], c.selected)
    }

    @Test fun targetQuestionOverHttp() {
        var seen: JSONObject? = null
        val server = ServerSocket(0, 5, java.net.InetAddress.getLoopbackAddress())
        thread(isDaemon = true) {
            while (!server.isClosed) {
                val c = try { server.accept() } catch (e: Exception) { break }
                c.use { sock ->
                    val inp = sock.getInputStream().bufferedReader()
                    val headers = generateSequence { inp.readLine() }.takeWhile { it.isNotEmpty() }.toList()
                    val len = headers.first { it.startsWith("Content-Length", true) }.substringAfter(":").trim().toInt()
                    val buf = CharArray(len); var got = 0
                    while (got < len) got += inp.read(buf, got, len - got)
                    seen = JSONObject(String(buf))
                    val body = """{"model":"t","answers":{"target":{"type":"choice","choice":"Share (button, bottom right)",
                        "probabilities":{"Like (button, bottom right)":0.2,"Share (button, bottom right)":0.7,"${TargetVocab.NONE_OPTION}":0.1},
                        "confidence":0.55}},"latency_ms":1234.5}"""
                    sock.getOutputStream().write(("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: ${body.toByteArray().size}\r\nConnection: close\r\n\r\n$body").toByteArray())
                }
            }
        }
        try {
            val ts = listOf(t("Like", "bottom right"), t("Share", "bottom right"))
            val opts = Targets.options(ts)
            val state = Targets.stateText("VLC", "org.videolan.vlc", ScreenContext("scrolling list", "none", "at the top", "hidden"), "share this")
            val a = SystemOneClient("http://127.0.0.1:${server.localPort}", "vox-targets", { "" }).choice(state, "target", TargetVocab.POLICY, opts)
            assertEquals("Share (button, bottom right)", a.choice)
            assertEquals(0.55, a.confidence, 1e-9); assertEquals(1234.5, a.serverMs!!, 1e-9)
            assertEquals(listOf("Share (button, bottom right)", "Like (button, bottom right)", TargetVocab.NONE_OPTION), a.top(3).map { it.first })
            val q = seen!!.getJSONObject("questions").getJSONObject("target")
            assertEquals("choice", q.getString("type"))
            assertEquals(TargetVocab.POLICY, q.getString("instructions"))
            // (The JVM's org.json does not keep key order; the emulator suite checks the order on the wire.)
            assertEquals(opts.toSet(), q.getJSONObject("criteria").keys().asSequence().toSet())
            assertEquals(state, seen!!.getString("state"))
            assertEquals("vox-targets", seen!!.getString("model"))
            // Below target_min_confidence (0.6): highlight both (none is never highlighted).
            assertEquals(Targets.Outcome.Choose(listOf(ts[1], ts[0])), Targets.resolve(ts, a, 0.6))
        } finally { server.close() }
    }
}
