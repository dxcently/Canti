package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import org.json.JSONObject

/** New default bindings (home, back, app-only forward), the forward finder, fling geometry and hold-to-scroll. */
class NavigationTest {

    private class Clock : Scheduler {
        var t = 0L
        val tasks = mutableListOf<Pair<Long, () -> Unit>>()
        override fun now() = t
        override fun schedule(delayMs: Long, task: () -> Unit): () -> Unit {
            val e = (t + delayMs) to task; tasks += e; return { tasks.remove(e) }
        }
        fun advance(ms: Long) {
            val end = t + ms
            while (true) {
                val next = tasks.filter { it.first <= end }.minByOrNull { it.first } ?: break
                tasks.remove(next); t = next.first; next.second()
            }
            t = end
        }
    }

    private fun line(label: String) = when (label) {
        "pop", "click" -> "${Vocab.DISCRETE[label]}; instant sound; loudness normal; sounds like mouth sound"
        "hiss" -> "a hiss; duration short (150-400 ms); loudness normal; sounds like mouth sound"
        else -> "hum that ${Vocab.CONTOURS[label]}; pitch change large (over 4 semitones); duration short (150-400 ms); tone clear tone; loudness normal; sounds like hum"
    }

    private fun flat(duration: String) =
        "hum that stays level; pitch change small (under 2 semitones); duration $duration; tone clear tone; loudness normal; sounds like hum"

    private fun input(seq: List<String>, profile: Profile = Profile.empty()): DecisionInput =
        DecisionInput(StateBuilder.build("gesture", "org.mozilla.fennec_fdroid", "Fennec", seq.map(::line), seq, null, profile,
            emptyList(), null, null), profile)

    // --- bindings ---------------------------------------------------------------------------------------------------

    @Test fun newDefaultBindings() {
        val r = RuleDecider()
        assertEquals("home", r.decide(input(listOf("click", "click"))).action)
        assertEquals("back", r.decide(input(listOf("hiss", "click"))).action)
        assertEquals("back", r.decide(input(listOf("hiss"))).action)
        val f = r.decide(input(listOf("click", "hiss")))
        assertEquals("forward", f.action); assertEquals(RuleDecider.APP_ONLY, f.source); assertTrue(f.explicit)
        assertTrue(Vocab.DEFAULTS_TEXT.contains("click click=go home"))
        assertTrue(Vocab.DEFAULTS_TEXT.contains("hiss click=go back"))
        assertFalse("the model never hears about forward", Vocab.DEFAULTS_TEXT.contains("forward"))
    }

    @Test fun userRulesOverrideAppOnlyForward() {
        val p = Profile.parse(org.json.JSONObject("""{"global":[{"phrase":["click","hiss"],"kind":"fixed","action":"recents"}]}"""))
        assertEquals("recents", RuleDecider().decide(input(listOf("click", "hiss"), p)).action)
    }

    /** A model that must not be asked: forward is not one of its options. */
    private class NoModel : Decider {
        var asked = 0
        override val name = "fake-model"
        override fun decide(input: DecisionInput): Decision { asked++; return Decision("none", "model") }
    }

    @Test fun forwardStaysLocalInEveryDeciderMode() {
        for (mode in listOf("model", "hybrid")) {
            val m = NoModel()
            val d = ChainDecider(mode, m).decide(input(listOf("click", "hiss")))
            assertEquals(mode, "forward", d.action); assertEquals(mode, 0, m.asked)
        }
        val m = NoModel()
        val d = EscalatingDecider(cloud = null, local = m, log = { _, _ -> }).decide(input(listOf("click", "hiss")))
        assertEquals("forward", d.action); assertEquals(0, m.asked)
        // Unbound sequences still go to the model in model mode.
        val m2 = NoModel()
        ChainDecider("model", m2).decide(input(listOf("click", "pop")))
        assertEquals(1, m2.asked)
    }

    private fun harness(absorbed: MutableList<String> = mutableListOf()): Triple<Clock, Sequencer, MutableList<Pair<String, Long>>> {
        val c = Clock()
        val out = mutableListOf<Pair<String, Long>>()
        return Triple(c, Sequencer(c, { 600L }, onResolve = { out += it.sequence.joinToString(" ") to c.t },
            onAbsorb = { p, s, gap -> absorbed += "$s after ${p.sequence.joinToString(" ")} gap=$gap" }), out)
    }

    private val bound = Profile.empty().boundSequences("x", "gesture")
    private val absorb = Profile.empty().absorbedSequences("x", "gesture")
    private fun Sequencer.sound(label: String, st: Stamp? = null) =
        add("gesture", "x", listOf("l"), listOf(label), bound, st?.let { listOf(it) }, absorb)

    @Test fun hissActsAtOnceAndClickWaits() {
        assertFalse("hiss click = back = hiss: nothing to wait for", listOf("hiss", "click") in bound)
        assertEquals(setOf(listOf("hiss", "click")), absorb)
        assertTrue(listOf("click", "click") in bound); assertTrue(listOf("click", "hiss") in bound)
        assertTrue(Profile.empty().absorbedSequences("x", "cursor").isEmpty())
        val (c, q, out) = harness()
        q.sound("hiss")
        assertEquals(listOf("hiss" to 0L), out)                     // a single hiss is back at once
        assertFalse(q.isWaiting); assertTrue(c.tasks.isEmpty())     // and nothing is scheduled for it
        assertEquals("tap", RuleDecider().decide(input(listOf("click"))).action)   // 2026-09-28: a lone click taps (pop folded)
        // click click waits (for click click click) and then goes home; a hiss after a click is forward.
        val (c2, q2, out2) = harness()
        q2.sound("click"); c2.advance(250); q2.sound("click")   // click click, now waits for click click click
        c2.advance(600)                                         // the gap elapses with no third click -> home
        assertEquals(listOf("click click" to 850L), out2)
        val (c3, q3, out3) = harness()
        q3.sound("click"); c3.advance(250); q3.sound("hiss")    // click hiss -> forward
        assertEquals(listOf("click hiss" to 250L), out3)
    }

    @Test fun hissClickIsOneBackAndTheClickIsAbsorbed() {
        val absorbed = mutableListOf<String>()
        val (c, q, out) = harness(absorbed)
        q.sound("hiss", Stamp(0, 270))
        assertEquals(listOf("hiss" to 0L), out)
        c.advance(260); q.sound("click", Stamp(520, 530))          // device gap 250 ms (the Pico canned test)
        c.advance(2000)
        assertEquals("the click never forms a group", listOf("hiss" to 0L), out)
        assertEquals(listOf("click after hiss gap=250"), absorbed)
        assertFalse(q.isWaiting)
    }

    @Test fun hissClickClickIsBackThenALoneClickNotHome() {
        val absorbed = mutableListOf<String>()
        val (c, q, out) = harness(absorbed)
        q.sound("hiss", Stamp(0, 270))
        c.advance(260); q.sound("click", Stamp(520, 530))
        c.advance(260); q.sound("click", Stamp(780, 790))
        assertTrue("the second click waits (click click / click hiss)", q.isWaiting)
        c.advance(2000)
        assertEquals(listOf("hiss", "click"), out.map { it.first })
        assertEquals(1, absorbed.size)
        assertEquals("tap", RuleDecider().decide(input(listOf("click"))).action)   // 2026-09-28: a lone click taps
    }

    @Test fun aClickAfterTheGapIsNotAbsorbed() {
        val absorbed = mutableListOf<String>()
        val (c, q, out) = harness(absorbed)
        q.sound("hiss", Stamp(0, 270))
        c.advance(900); q.sound("click", Stamp(1170, 1180))        // device gap 900 ms > 600
        assertTrue(absorbed.isEmpty()); assertTrue(q.isWaiting)
        c.advance(2000)
        assertEquals(listOf("hiss", "click"), out.map { it.first })
        // A burst that arrives late but was close on the device is still absorbed (device clock, not arrival).
        val (c2, q2, out2) = harness(absorbed)
        q2.sound("hiss", Stamp(0, 270))
        c2.advance(1500); q2.sound("click", Stamp(520, 530))
        c2.advance(2000)
        assertEquals(listOf("hiss"), out2.map { it.first }); assertEquals(1, absorbed.size)
    }

    @Test fun absorbingOnTheArrivalClockAndOnlyTheTail() {
        val absorbed = mutableListOf<String>()
        val (c, q, out) = harness(absorbed)
        q.sound("hiss"); c.advance(300); q.sound("click")            // no stamps: arrival within the gap
        c.advance(2000)
        assertEquals(listOf("hiss"), out.map { it.first }); assertEquals(listOf("click after hiss gap=null"), absorbed)
        q.sound("hiss"); c.advance(700); q.sound("click")            // arrival after the gap: its own group
        c.advance(2000)
        assertEquals(listOf("hiss", "hiss", "click"), out.map { it.first })
        q.sound("hiss"); c.advance(200); q.sound("pop")              // not the tail: acts as usual (tap)
        c.advance(1000)                                            // (after the gap: pop waits for pop pop)
        assertEquals(listOf("hiss", "hiss", "click", "hiss", "pop"), out.map { it.first })
        assertEquals(1, absorbed.size)
        q.sound("hiss"); q.cancel(); c.advance(100); q.sound("click") // a disarm forgets the tail
        c.advance(2000)
        assertEquals("click", out.last().first)
    }

    @Test fun hissClickInOneBurstIsStillOneBack() {
        // Both sounds in one message: the hiss resolves (back) at once, the click is absorbed.
        val absorbed = mutableListOf<String>()
        val (c, q, out) = harness(absorbed)
        q.add("gesture", "x", listOf("a", "b"), listOf("hiss", "click"), bound, null, absorb)
        c.advance(600)
        assertEquals(listOf("hiss"), out.map { it.first }); assertEquals(1, absorbed.size)
    }

    @Test fun hissWaitsWhenAUserBindsADifferentContinuation() {
        val p = Profile.parse(org.json.JSONObject("""{"global":[{"phrase":["hiss","pop"],"kind":"fixed","action":"recents"}]}"""))
        val bound = p.boundSequences("x", "gesture")
        assertTrue("pop folds to click: hiss pop -> hiss click", listOf("hiss", "click") in bound)
        val (c, q, out) = harness()
        q.add("gesture", "x", listOf("l"), listOf("hiss"), bound, null, p.absorbedSequences("x", "gesture"))
        assertTrue(out.isEmpty())
        c.advance(600); assertEquals(listOf("hiss" to 600L), out)
    }

    // --- fast path: what a decider settles locally ------------------------------------------------------------------

    private fun phraseInput(said: String) = DecisionInput(StateBuilder.build("listening", "x", "X", emptyList(), emptyList(), said,
        Profile.empty(), emptyList(), null, null), Profile.empty())

    @Test fun localDecisionsMatchDecideAndNeverAskTheModel() {
        val gestures = listOf(listOf("rise"), listOf("fall"), listOf("hiss"), listOf("click", "click"), listOf("click", "hiss"), listOf("pop", "pop"))
        for (seq in gestures) {
            val want = RuleDecider().decide(input(seq))
            assertEquals(seq.toString(), want, RuleDecider().local(input(seq)))
            assertEquals(seq.toString(), want, ChainDecider("rules", null).local(input(seq)))
            val m = NoModel()
            assertEquals(seq.toString(), want, EscalatingDecider(cloud = null, local = m, log = { _, _ -> }).local(input(seq)))
            assertEquals(0, m.asked)
        }
        // hybrid: explicit bindings are local; an unbound sequence goes to the model.
        assertEquals("swipe_up", ChainDecider("hybrid", NoModel()).local(input(listOf("rise")))?.action)
        assertNull(ChainDecider("hybrid", NoModel()).local(input(listOf("rise", "rise"))))   // 2026-09-28: "click pop" folds to home, so use a truly unbound sequence
        // model mode: only app-only bindings stay local.
        assertNull(ChainDecider("model", NoModel()).local(input(listOf("rise"))))
        assertEquals("forward", ChainDecider("model", NoModel()).local(input(listOf("click", "hiss")))?.action)
        // A plain-language rule needs the model.
        val rule = Profile.parse(org.json.JSONObject("""{"global":[{"phrase":["rise"],"kind":"rule","rule":"scroll gently"}]}"""))
        assertNull(EscalatingDecider(cloud = null, local = NoModel(), log = { _, _ -> }).local(input(listOf("rise"), rule)))
        // Phrases may read the screen (tie-breaker): never local.
        assertNull(RuleDecider().local(phraseInput("next")))
        assertNull(ChainDecider("rules", null).local(phraseInput("next")))
        assertNull(EscalatingDecider(cloud = null, local = NoModel(), log = { _, _ -> }).local(phraseInput("next")))
        // The interface default: always the full path.
        assertNull(NoModel().local(input(listOf("rise"))))
    }

    // --- forward finder ---------------------------------------------------------------------------------------------

    private class N(val i: Forward.Info, val kids: List<N> = emptyList())
    private fun node(text: String? = null, desc: String? = null, clickable: Boolean = false, enabled: Boolean = true,
                     visible: Boolean = true, top: Int = 0, bottom: Int = 100, kids: List<N> = emptyList()) =
        N(Forward.Info(text, desc, clickable, enabled, visible, 0, top, 100, bottom), kids)
    private val kids: (N) -> List<N> = { it.kids }
    private val info: (N) -> Forward.Info = { it.i }

    @Test fun forwardFinderPicksAVisibleForward() {
        val label = node(desc = "Forward")
        val button = node(clickable = true, kids = listOf(label))
        val root = node(kids = listOf(node(text = "Fast forward", clickable = true), node(desc = "Forward", clickable = true, visible = false), button))
        val hit = Forward.forward(listOf(root), kids, info)!!
        assertTrue(hit.labelled === label); assertTrue("clicks the clickable parent", hit.click === button); assertTrue(hit.enabled)
    }

    @Test fun forwardFinderReportsDisabledAndMissing() {
        val off = node(desc = "Forward", clickable = true, enabled = false)
        assertFalse(Forward.forward(listOf(node(kids = listOf(off))), kids, info)!!.enabled)
        assertNull(Forward.forward(listOf(node(kids = listOf(node(text = "Forward to…", clickable = true), node(text = "Reply", clickable = true)))), kids, info))
        assertNull("a label nobody can click is not a control", Forward.forward(listOf(node(kids = listOf(node(text = "Forward")))), kids, info))
    }

    @Test fun overflowMenuPrefersTheToolbarBand() {
        val inPage = node(desc = "More options", clickable = true, top = 1000, bottom = 1100)
        val toolbar = node(desc = "Main menu", clickable = true, top = 2500, bottom = 2600)
        val root = node(kids = listOf(inPage, toolbar))
        assertTrue(Forward.menu(listOf(root), kids, info, 2640)!!.click === toolbar)
        assertNull(Forward.menu(listOf(node(kids = listOf(node(desc = "Share", clickable = true)))), kids, info, 2640))
    }

    // --- fling geometry ----------------------------------------------------------------------------------------------

    @Test fun flingGeometryStaysOutOfTheGestureZones() {
        // Galaxy Z Flip6 main screen 1080x2640 at 420 dpi (2.625): fallback zones 126 px top/bottom, 84 px sides.
        val safe = SwipeGeometry.fallback(2.625f)
        val up = SwipeGeometry.line("swipe_up", 1080, 2640, safe)!!
        assertEquals(1900.8f, up[1], 0.5f); assertEquals(316.8f, up[3], 0.5f)
        assertTrue("72% start is well above bottom cards and tab bars", up[1] < 2640 * 0.75f)
        val down = SwipeGeometry.line("swipe_down", 1080, 2640, safe)!!
        assertEquals(739.2f, down[1], 0.5f); assertEquals(2323.2f, down[3], 0.5f)
        assertTrue("the end stays above the gesture bar", down[3] < 2640 - safe.bottom)
        val left = SwipeGeometry.line("swipe_left", 1080, 2640, safe)!!
        assertEquals(918f, left[0], 0.5f); assertEquals(162f, left[2], 0.5f)
        // Large insets clamp the stroke.
        val clamped = SwipeGeometry.line("swipe_right", 1080, 2640, SwipeGeometry.Safe(200, 0, 200, 0))!!
        assertEquals(200f, clamped[0], 0.5f); assertEquals(880f, clamped[2], 0.5f)
        val tall = SwipeGeometry.line("swipe_up", 1080, 2640, SwipeGeometry.Safe(0, 400, 0, 800))!!
        assertEquals(1840f, tall[1], 0.5f); assertEquals(400f, tall[3], 0.5f)
        assertEquals(100L, SwipeGeometry.DURATION_MS)
        assertNull(SwipeGeometry.line("tap", 1080, 2640, safe))
    }

    // --- gesture queue -------------------------------------------------------------------------------------------------

    @Test fun gestureQueueRunsOneAtATimeInOrder() {
        val q = GestureQueue<String>()
        assertEquals("fling1", q.offer("fling1", 0))
        assertNull("the second fling waits instead of cancelling the first", q.offer("fling2", 15))
        assertNull(q.offer("back", 20))
        assertNull(q.finished("fling2", 30))            // not the running one: ignored
        assertEquals("fling2", q.finished("fling1", 120))
        assertEquals("back", q.finished("fling2", 240))
        assertNull(q.finished("back", 241))
        assertTrue(q.idle)
        assertEquals("tap", q.offer("tap", 1000))       // idle: at once
    }

    @Test fun gestureQueueDoesNotWaitForeverOnALostCallback() {
        val q = GestureQueue<String>(stuckMs = 3_000)
        q.offer("a", 0)
        assertNull(q.offer("b", 100))
        assertEquals("b", q.offer("c", 3_100))          // a is given up on: the oldest waiting one runs
        assertNull(q.finished("a", 3_200))              // a's late callback changes nothing
        assertEquals("c", q.finished("b", 3_300))
    }

    @Test fun gestureQueueDropsTheOldestWhenFull() {
        val q = GestureQueue<Int>(max = 2)
        q.offer(0, 0); q.offer(1, 1); q.offer(2, 2); q.offer(3, 3)
        assertEquals(listOf(1), q.dropped)
        assertEquals(2, q.finished(0, 10))
        assertEquals(listOf(3), q.dropWaiting())
        assertNull(q.finished(2, 20))
        assertTrue(q.idle)
    }

    // --- hold-to-scroll ------------------------------------------------------------------------------------------------

    @Test fun holdMustStartSoonAfterTheSwipe() {
        val swipe = HoldScrollTrigger.Swipe(7, "swipe_up", "x", "gesture", Stamp(0, 300), arrivedAt = 360)
        assertEquals("device gap 400 ms", HoldScrollTrigger.follows(swipe, 7, "gesture", "x", 700, 1100))
        assertEquals("device gap 1000 ms", HoldScrollTrigger.follows(swipe, 7, "gesture", "x", 1300, 1400))
        assertNull("too late", HoldScrollTrigger.follows(swipe, 7, "gesture", "x", 1301, 1400))
        assertNull("something else was decided in between", HoldScrollTrigger.follows(swipe, 8, "gesture", "x", 700, 1100))
        assertNull("other app", HoldScrollTrigger.follows(swipe, 7, "gesture", "y", 700, 1100))
        assertNull("a flat with no swipe before it stays long-press", HoldScrollTrigger.follows(null, 7, "gesture", "x", 700, 1100))
        assertNull(HoldScrollTrigger.follows(swipe.copy(action = "zoom_in"), 7, "gesture", "x", 700, 1100))
        assertEquals("device gap 400 ms", HoldScrollTrigger.follows(swipe.copy(action = "swipe_down"), 7, "gesture", "x", 700, 1100))
        for (a in listOf("swipe_left", "swipe_right"))
            assertNull("arch/dip never open the gate: $a", HoldScrollTrigger.follows(swipe.copy(action = a), 7, "gesture", "x", 700, 1100))
        // Arrival clock (no stamps).
        val noStamp = swipe.copy(end = null)
        assertEquals("arrival gap 1640 ms", HoldScrollTrigger.follows(noStamp, 7, "gesture", "x", null, 2000))
        assertNull(HoldScrollTrigger.follows(noStamp, 7, "gesture", "x", null, 360 + 2001))
    }

    @Test fun holdMessagesParse() {
        val start = HoldMessage.parse(JSONObject("""{"v":1,"id":1043,"hold":"start","sound":57,"t_start_ms":81790,"t_ms":82090,"f0_hz":145.2,"flat":true}"""))
        assertEquals(HoldMessage(1043, "start", 57, 81790, 82090, 145.2, true), start)
        val end = JSONObject("""{"v":1,"id":1044,"hold":"end","sound":57,"t_start_ms":81790,"t_ms":83790}""")
        assertTrue(HoldMessage.isHold(end)); assertEquals("end", HoldMessage.parse(end).kind)
        assertFalse(HoldMessage.parse(JSONObject("""{"v":1,"hold":"start","sound":5,"t_start_ms":0,"t_ms":300,"flat":false}""")).flat)
        for (bad in listOf("""{"v":1,"hold":"middle","sound":5,"t_start_ms":0,"t_ms":300}""",
                           """{"v":1,"hold":"end","t_start_ms":0,"t_ms":300}""",
                           """{"v":1,"hold":"end","sound":5,"t_start_ms":400,"t_ms":300}""",
                           """{"v":2,"hold":"end","sound":5,"t_start_ms":0,"t_ms":300}"""))
            assertThrows(bad, IllegalArgumentException::class.java) { HoldMessage.parse(JSONObject(bad)) }
        val feat = FeatureMessage.parse(JSONObject("""{"v":1,"id":1045,"mode":"gesture","armed":true,"sounds":["hum that stays level"],
            "sequence":["flat"],"timing":[{"t_start_ms":81790,"t_end_ms":83790,"sound":57,"held":true}]}"""))
        assertEquals(Stamp(81790, 83790, 57, true), feat.timing!![0])
        assertEquals(Stamp(81790, 83790, 57, true), FeatureMessage.parse(feat.toJson()).timing!![0])
    }

    private class FakeDrag : ScrollDrag {
        val calls = mutableListOf<String>(); var fail: ((String) -> Unit)? = null
        override fun begin(action: String, onFail: (String) -> Unit) { calls += "begin $action"; fail = onFail }
        override fun end() { calls += "end" }
    }

    private class Hold(val c: Clock = Clock()) {
        var app = "com.twitter.android"; var screen = true
        val drag = FakeDrag(); val events = mutableListOf<String>()
        val s = HoldScroller(c, { app }, { screen }, drag, { ev, _, why -> events += if (why == null) ev else "$ev: $why" })
    }

    @Test fun scrollsWhileHeldAndTheFlatIsNotALongPress() {
        val t = Hold()
        assertFalse("nothing held: a flat's final event is acted on", t.s.consumeFinal("s9"))
        t.s.start("swipe_up", t.app, "s9")
        assertEquals("hold-scroll down", t.s.status)
        assertEquals(listOf("begin swipe_up"), t.drag.calls)
        t.c.advance(3000); assertTrue(t.s.active)
        assertFalse("another hold's end is ignored", t.s.holdEnded("s8")); assertTrue(t.s.active)
        assertTrue(t.s.holdEnded("s9"))
        assertEquals(listOf("begin swipe_up", "end"), t.drag.calls)
        assertFalse(t.s.active); assertNull(t.s.status)
        assertTrue("the held flat's final event is dropped (no long-press)", t.s.consumeFinal("s9"))
        assertFalse("only once", t.s.consumeFinal("s9"))
        assertEquals(listOf("start", "stop: hold end"), t.events)
    }

    @Test fun aLostHoldEndIsStoppedByTheFinalEvent() {
        val t = Hold()
        t.s.start("swipe_down", t.app, "s3")
        assertTrue(t.s.consumeFinal("s3"))
        assertEquals("stop: hold's final event (no hold end seen)", t.events.last())
    }

    @Test fun holdScrollSafetyStops() {
        val dog = Hold(); dog.s.start("swipe_down", dog.app, "a"); dog.c.advance(4500); assertTrue(dog.s.active)
        dog.c.advance(500); assertEquals("stop: watchdog: no hold end after 5 s", dog.events.last())
        assertTrue("its final event is still dropped", dog.s.consumeFinal("a"))
        val cap = Hold(); cap.s.start("swipe_down", cap.app, null); cap.c.advance(200_000)
        assertEquals("stop: cap 120 s", cap.events.last())
        assertThrows(IllegalArgumentException::class.java) { Hold().let { it.s.start("swipe_left", it.app, "a") } }
        val app = Hold(); app.s.start("swipe_up", app.app, "a"); app.c.advance(1000); app.app = "com.other"; app.c.advance(500)
        assertEquals("stop: app changed: com.other", app.events.last())
        val ev = Hold(); ev.s.start("swipe_up", ev.app, "a"); ev.s.appChanged(ev.app); assertTrue(ev.s.active)
        ev.s.appChanged("com.launcher"); assertFalse(ev.s.active)
        val off = Hold(); off.s.start("swipe_up", off.app, "a"); off.screen = false; off.c.advance(500)
        assertEquals("stop: screen off", off.events.last())
        val touched = Hold(); touched.s.start("swipe_up", touched.app, "a"); touched.drag.fail!!("drag cancelled (screen touched?)")
        assertEquals("stop: drag cancelled (screen touched?)", touched.events.last())
        val paused = Hold(); paused.s.start("swipe_up", paused.app, "a"); assertTrue(paused.s.stop("pause"))
        assertFalse(paused.s.stop("again")); assertEquals(listOf("begin swipe_up", "end"), paused.drag.calls)
    }
}
