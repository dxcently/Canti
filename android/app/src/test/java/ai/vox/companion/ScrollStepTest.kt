package ai.vox.companion

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.pow

/** No-momentum steps vs flings ([ScrollStep]), the step size, and the hold-scroll pitch throttle ([PitchThrottle]). */
class ScrollStepTest {
    // Z Flip: 1080 x 2640
    private val W = 1080; private val H = 2640
    private val safe = SwipeGeometry.Safe(84, 126, 84, 126)

    private fun node(cls: String, l: Int, t: Int, r: Int, b: Int, id: String? = null, rows: Int = -1, cols: Int = -1,
                     fwd: Boolean = true, back: Boolean = true, kids: List<NodeSnap> = emptyList(), scrollable: Boolean = true) =
        NodeSnap(cls, id, null, null, l, t, r, b, scrollable = scrollable, canScrollForward = fwd, canScrollBackward = back,
            rows = rows, cols = cols, children = kids)

    private fun item(t: Int, b: Int, l: Int = 0, r: Int = 1080) = node("android.view.ViewGroup", l, t, r, b, scrollable = false)
    private fun rows(t: Int, b: Int, h: Int) = (t until b step h).map { item(it, minOf(it + h, b)) }

    private fun decide(action: String, vararg s: ScrollerSnap, pkg: String = "com.example") = ScrollStep.decide(action, pkg, s.toList(), H)

    // --- which gesture ----------------------------------------------------------------------------------------------

    @Test fun ordinaryListsStep() {
        val list = node("androidx.recyclerview.widget.RecyclerView", 0, 250, 1080, 2400, "com.x:id/list", rows = 40, cols = 1, kids = rows(250, 2400, 300))
        val d = decide("swipe_up", ScrollerSnap(list))
        assertTrue(d.why, d.step); assertEquals("list RecyclerView#list", d.why)
        assertTrue(decide("swipe_down", ScrollerSnap(list)).step)
        // a ScrollView's one child is the whole content, never a page
        val scroll = node("android.widget.ScrollView", 0, 250, 1080, 2400, kids = listOf(item(250, 6000)))
        assertTrue(decide("swipe_up", ScrollerSnap(scroll)).step)
        // a web page
        assertTrue(decide("swipe_up", ScrollerSnap(node("android.webkit.WebView", 0, 300, 1080, 2400, kids = listOf(item(300, 2400))))).step)
    }

    @Test fun tabPagerAroundAListStillSteps() {
        // NewPipe: a horizontal tab ViewPager with the vertical list inside, same size (ScrollPick takes the list)
        val pager = node("androidx.viewpager.widget.ViewPager", 0, 300, 1080, 2400, "org.schabi.newpipe:id/pager")
        val list = node("androidx.recyclerview.widget.RecyclerView", 0, 300, 1080, 2400, "org.schabi.newpipe:id/items_list", rows = 16, cols = 1, kids = rows(300, 2400, 250))
        val d = decide("swipe_up", ScrollerSnap(pager), ScrollerSnap(list, "android.widget.FrameLayout"))
        assertTrue(d.why, d.step)
    }

    @Test fun pagedFeedsKeepTheFling() {
        // a vertical ViewPager2 feed (the fixture's FeedView): one page fills the viewport
        val feed = node("ai.vox.fixture.FeedView", 0, 0, 1080, 2640, "ai.vox.fixture:id/feed", rows = 20, cols = 1, kids = listOf(item(0, 2640)))
        assertEquals("pager: one page fills the viewport (1 page visible)", decide("swipe_up", ScrollerSnap(feed)).why)
        // mid-snap: two pages, one covers 85 %
        val mid = feed.copy(children = listOf(item(-400, 390), item(390, 2640)))
        assertFalse(decide("swipe_up", ScrollerSnap(mid)).step)
        // ViewPager2's inner RecyclerView (the page list), whatever its pages look like
        val inner = node("androidx.recyclerview.widget.RecyclerView", 0, 0, 1080, 2640, rows = 9, cols = 1, kids = rows(0, 2640, 400))
        assertEquals("pager: ViewPager2 page list", decide("swipe_up", ScrollerSnap(inner, "androidx.viewpager2.widget.ViewPager2")).why)
        // Shorts / Reels by view id
        val shorts = node("androidx.recyclerview.widget.RecyclerView", 0, 0, 1080, 2640, "com.google.android.youtube:id/reel_recycler", kids = rows(0, 2640, 500))
        assertEquals("pager: id reel_recycler", decide("swipe_down", ScrollerSnap(shorts)).why)
        val clips = shorts.copy(id = "com.instagram.android:id/clips_viewer_view_pager")
        assertFalse(decide("swipe_up", ScrollerSnap(clips)).step)
        // a pager class
        assertEquals("pager: class VerticalViewPager",
            decide("swipe_up", ScrollerSnap(node("com.ss.android.ugc.aweme.VerticalViewPager", 0, 0, 1080, 2640, rows = 5, cols = 1, kids = rows(0, 2640, 600)))).why)
        // the package fallback
        val tiktok = node("android.widget.FrameLayout", 0, 0, 1080, 2640, kids = rows(0, 2640, 400))
        assertEquals("pager app (fallback list): com.zhiliaoapp.musically", decide("swipe_up", ScrollerSnap(tiktok), pkg = "com.zhiliaoapp.musically").why)
        assertTrue(decide("swipe_up", ScrollerSnap(tiktok), pkg = "com.example").step)
    }

    @Test fun aSmallPageIsNotAPager() {
        // a short scroller (under half the screen) with one big item: a card list, not a feed
        val small = node("androidx.recyclerview.widget.RecyclerView", 0, 1500, 1080, 2400, kids = listOf(item(1500, 2400)))
        assertTrue(decide("swipe_up", ScrollerSnap(small)).step)
    }

    @Test fun otherCasesKeepTheFling() {
        val list = node("androidx.recyclerview.widget.RecyclerView", 0, 250, 1080, 2400, rows = 40, cols = 1, kids = rows(250, 2400, 300))
        assertEquals("sideways: pagers and carousels need the fling", decide("swipe_left", ScrollerSnap(list)).why)
        assertFalse(decide("swipe_right", ScrollerSnap(list)).step)
        assertEquals("no scrollable list", decide("swipe_up").why)
        assertEquals("no scrollable list", decide("swipe_up", ScrollerSnap(list.copy(visible = false))).why)
        // at its end that way: pull-to-refresh / overscroll keep the fling
        assertEquals("RecyclerView is at its end that way", decide("swipe_down", ScrollerSnap(list.copy(canScrollBackward = false))).why)
        assertFalse(decide("swipe_up", ScrollerSnap(list.copy(canScrollForward = false))).step)
        // only a horizontal photo pager on screen
        val photos = node("n", 0, 0, 1080, 2640, "org.fossify.gallery:id/view_pager", rows = 1, cols = 5, kids = listOf(item(0, 2640)))
        assertEquals("main scroller n is horizontal", decide("swipe_up", ScrollerSnap(photos)).why)
        assertEquals("not a swipe", decide("tap", ScrollerSnap(list)).why)
    }

    // --- the stroke -------------------------------------------------------------------------------------------------

    private val fullList = node("androidx.recyclerview.widget.RecyclerView", 0, 250, 1080, 2400)

    @Test fun stepLengthFollowsTheSize() {
        val listH = fullList.height   // 2150
        val slop = 21
        for (size in StepSize.entries) {
            val l = ScrollStep.line("swipe_up", fullList, W, H, safe, size, slop)!!
            val len = l[1] - l[3]
            val band = H * ScrollStep.UP_BOTTOM - maxOf(fullList.top + listH * ScrollStep.EDGE, H * ScrollStep.UP_TOP)
            assertEquals(size.key, minOf(listH * size.frac + slop, band), len, 0.5f)
            assertEquals("centred on the list", 540f, l[0]); assertEquals(l[0], l[2])
            assertTrue("starts above the bottom cards", l[1] <= H * ScrollStep.UP_BOTTOM + 0.5f)
            assertTrue("ends inside the list", l[3] >= fullList.top)
        }
        val s = ScrollStep.line("swipe_up", fullList, W, H, safe, StepSize.SMALL, slop)!!
        val m = ScrollStep.line("swipe_up", fullList, W, H, safe, StepSize.MEDIUM, slop)!!
        val lg = ScrollStep.line("swipe_up", fullList, W, H, safe, StepSize.LARGE, slop)!!
        assertTrue(s[1] - s[3] < m[1] - m[3] && m[1] - m[3] < lg[1] - lg[3])
    }

    @Test fun swipeDownMirrorsIntoItsBand() {
        val l = ScrollStep.line("swipe_down", fullList, W, H, safe, StepSize.MEDIUM, 0)!!
        assertTrue("moves down", l[3] > l[1])
        assertEquals(fullList.height * 0.5f, l[3] - l[1], 0.5f)
        assertTrue(l[1] >= H * ScrollStep.DOWN_TOP - 0.5f && l[3] <= H * ScrollStep.DOWN_BOTTOM + 0.5f)
    }

    @Test fun shortListsAndInsets() {
        // a list in the lower half: the stroke stays inside it
        val low = node("x.List", 100, 1400, 900, 2500)
        val l = ScrollStep.line("swipe_up", low, W, H, safe, StepSize.LARGE, 0)!!
        assertTrue(l[1] <= minOf(low.bottom.toFloat(), H * ScrollStep.UP_BOTTOM) && l[3] >= low.top + low.height * ScrollStep.EDGE - 0.5f)
        assertEquals(500f, l[0])
        // too little room: fling instead
        assertNull(ScrollStep.line("swipe_up", node("x.List", 0, 1700, 1080, 2000), W, H, safe, StepSize.MEDIUM, 0))
        // big insets: never inside them
        val fat = SwipeGeometry.Safe(84, 900, 84, 126)
        val f = ScrollStep.line("swipe_up", fullList, W, H, fat, StepSize.LARGE, 0)!!
        assertTrue(f[3] >= 900)
    }

    @Test fun stepSizeKeys() {
        assertEquals(listOf("small", "medium", "large"), StepSize.KEYS)
        assertEquals(StepSize.MEDIUM, StepSize.of(null)); assertEquals(StepSize.MEDIUM, StepSize.of("huge"))
        assertEquals(StepSize.LARGE, StepSize.of("large"))
    }

    // --- pitch throttle ---------------------------------------------------------------------------------------------

    private fun hz(base: Double, st: Double) = base * 2.0.pow(st / 12)

    @Test fun mappingDeadZoneFloorAndCeiling() {
        val p = PitchThrottle()
        for (st in listOf(-1.0, -0.5, 0.0, 0.7, 1.0)) assertEquals("$st", 1.0, p.map(st), 0.0)
        assertEquals(2.0, p.map(4.0), 1e-9)          // 3 st past the dead zone doubles
        assertEquals(0.5, p.map(-4.0), 1e-9)
        assertEquals(3.0, p.map(8.0), 1e-9)          // ceiling
        assertEquals(0.3, p.map(-8.0), 1e-9)         // floor
        assertEquals("continuous at the edge", 1.0, p.map(1.0001), 1e-3)
        var last = 0.0
        for (i in -80..80) { val f = p.map(i / 10.0); assertTrue("monotonic", f >= last); last = f }
    }

    @Test fun wobbleInsideTheDeadZoneNeverChangesTheSpeed() {
        val p = PitchThrottle(); p.reset(150.0)
        val wobble = listOf(0.4, -0.6, 0.8, -0.3, 0.9, -0.9, 0.5, 0.0, -0.7, 0.6)
        wobble.forEachIndexed { i, st -> assertEquals(1.0, p.update(hz(150.0, st), 200L * i), 0.0) }
    }

    @Test fun smoothingRisesGraduallyAndSettles() {
        val p = PitchThrottle(); p.reset(150.0)
        p.update(150.0, 0); p.update(150.0, 200)
        val fs = (2..12).map { p.update(hz(150.0, 5.0), 200L * it) }
        for (i in 1 until fs.size) assertTrue("rises monotonically: $fs", fs[i] >= fs[i - 1])
        assertTrue("not instant: $fs", fs[0] < 1.5)
        assertEquals(2.0.pow(4.0 / 3), fs.last(), 0.02)   // +5 st -> 2.52x
        assertEquals(5.0, p.semitones!!, 0.05)
    }

    @Test fun glitchesAreDropped() {
        val p = PitchThrottle(); p.reset(150.0)
        p.update(150.0, 0); p.update(150.0, 200)
        assertEquals("an octave error folds back", 1.0, p.update(300.4, 400), 0.0)
        assertEquals(1.0, p.update(149.0, 600), 0.0)
        assertEquals("a single +5 st glitch is outvoted by the median", 1.0, p.update(hz(150.0, 5.0), 800), 0.0)
        assertEquals(1.0, p.update(150.0, 1000), 0.0)
        assertEquals("bad values are ignored", 1.0, p.update(Double.NaN, 1200), 0.0)
        assertEquals(1.0, p.update(0.0, 1400), 0.0)
    }

    @Test fun baseIsTheFirstReportWithoutAStartPitch() {
        val p = PitchThrottle(); p.reset(null)
        assertEquals(1.0, p.update(200.0, 0), 0.0)
        repeat(10) { p.update(hz(200.0, -6.0), 200L * (it + 1)) }
        assertEquals(2.0.pow(-5.0 / 3), p.factor, 0.02)
        p.reset(200.0); assertEquals(1.0, p.factor, 0.0); assertNull(p.semitones)
    }

    // --- fake stream: messages as the device sends them, through HoldScroller -------------------------------------

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

    /** Plays [lines] (one JSON message per 200 ms of device time) as VoxService does; returns the speed after each. */
    private fun play(lines: List<String>, withStart: Boolean = true): Pair<HoldScroller, List<Double>> {
        val c = Clock()
        val drag = object : ScrollDrag { override fun begin(action: String, onFail: (String) -> Unit) {}; override fun end() {} }
        val s = HoldScroller(c, { "app" }, { true }, drag)
        val speeds = mutableListOf<Double>()
        for (line in lines) {
            val h = HoldMessage.parse(JSONObject(line))
            when (h.kind) {
                "start" -> if (withStart) s.start("swipe_up", "app", h.sound.toString(), h.f0Hz)
                "pitch" -> s.pitch(h.sound.toString(), h.f0Hz!!, h.tMs)
                "end" -> s.holdEnded(h.sound.toString())
            }
            speeds += s.speed
            c.advance(200)
        }
        return s to speeds
    }

    private fun stream(sound: Int, base: Double, sts: List<Double>, t0: Long = 1000): List<String> {
        var id = 100
        val out = mutableListOf("""{"v":1,"id":${id++},"hold":"start","sound":$sound,"t_start_ms":$t0,"t_ms":${t0 + 300},"f0_hz":$base,"flat":true}""")
        sts.forEachIndexed { i, st -> out += """{"v":1,"id":${id++},"hold":"pitch","sound":$sound,"t_ms":${t0 + 500 + 200 * i},"f0_hz":${String.format(java.util.Locale.ROOT, "%.2f", hz(base, st))}}""" }
        out += """{"v":1,"id":${id++},"hold":"end","sound":$sound,"t_start_ms":$t0,"t_ms":${t0 + 700 + 200 * sts.size}}"""
        return out
    }

    @Test fun fakeStreamSpeedsUpSlowsDownAndStops() {
        val sts = listOf(0.3, -0.4, 0.2) + List(6) { 5.0 } + List(3) { 0.5 } + List(8) { -6.0 }
        val (s, sp) = play(stream(57, 140.0, sts))
        val pitchSp = sp.subList(1, 1 + sts.size)
        assertEquals("start: normal speed", 1.0, sp[0], 0.0)
        assertTrue("wobble: normal speed", pitchSp.take(3).all { it == 1.0 })
        assertTrue("humming higher speeds it up: $pitchSp", pitchSp[8] > 2.0)
        assertTrue("never above the ceiling", pitchSp.all { it <= 3.0 })
        assertTrue("humming lower slows it down: $pitchSp", pitchSp.last() < 0.5 && pitchSp.last() >= 0.3)
        assertFalse(s.active); assertEquals("after the end: 1", 1.0, sp.last(), 0.0)
    }

    @Test fun withoutPitchReportsNothingChanges() {
        val lines = stream(3, 150.0, emptyList())
        val (_, sp) = play(lines)
        assertTrue(sp.all { it == 1.0 })
    }

    @Test fun anotherHoldsReportsAndIdleReportsAreIgnored() {
        val c = Clock()
        val s = HoldScroller(c, { "app" }, { true }, object : ScrollDrag { override fun begin(action: String, onFail: (String) -> Unit) {}; override fun end() {} })
        assertFalse("idle", s.pitch("9", 300.0, 0))
        s.start("swipe_down", "app", "9", 150.0)
        repeat(5) { assertFalse("another sound", s.pitch("8", 400.0, 200L * it)) }
        assertEquals(1.0, s.speed, 0.0)
        repeat(8) { assertTrue(s.pitch("9", hz(150.0, 4.0), 200L * it)) }
        assertEquals(2.0, s.speed, 0.05)
        s.start("swipe_up", "app", "10", 150.0)
        assertEquals("a new hold starts at 1", 1.0, s.speed, 0.0)
    }

    @Test fun pitchMessagesParse() {
        val p = HoldMessage.parse(JSONObject("""{"v":1,"id":1046,"hold":"pitch","sound":57,"t_ms":82290,"f0_hz":151.3}"""))
        assertEquals(HoldMessage(1046, "pitch", 57, 82290, 82290, 151.3), p)
        assertEquals(81790, HoldMessage.parse(JSONObject("""{"v":1,"hold":"pitch","sound":57,"t_start_ms":81790,"t_ms":82290,"f0_hz":151.3}""")).tStartMs)
        for (bad in listOf("""{"v":1,"hold":"pitch","sound":5,"t_ms":300}""", """{"v":1,"hold":"pitch","t_ms":300,"f0_hz":150}"""))
            assertThrows(bad, IllegalArgumentException::class.java) { HoldMessage.parse(JSONObject(bad)) }
        assertNotNull(HoldMessage.parse(JSONObject("""{"v":1,"hold":"end","sound":5,"t_start_ms":0,"t_ms":300}""")))
    }


    // --- glide-and-hold (GlideHold, HoldGate): a rise / fall whose end note is held ----------------------------------

    private fun glideStart(sound: Int, dir: String, t0: Long = 1000, tailMs: Long = 250) =
        """{"v":1,"id":${200 + sound},"hold":"start","sound":$sound,"t_start_ms":$t0,"t_ms":${t0 + 350 + tailMs},"f0_hz":210.0,"flat":false,"from":"glide","dir":"$dir"}"""

    private fun route(line: String, mode: String = "gesture", app: String = "app", profile: Profile = Profile.empty(),
                      armed: Boolean = true, paused: Boolean = false, listening: Boolean = false, waiting: Boolean = false,
                      deciding: Boolean = false) =
        HoldGate.route(HoldMessage.parse(JSONObject(line)), armed, paused, listening, waiting, deciding, mode, app, profile)

    @Test fun glideStartsParse() {
        val h = HoldMessage.parse(JSONObject(glideStart(9, "up")))
        assertTrue(h.isGlide); assertEquals("up", h.dir); assertFalse(h.flat)
        val flat = HoldMessage.parse(JSONObject("""{"v":1,"hold":"start","sound":5,"t_start_ms":0,"t_ms":300,"f0_hz":150,"flat":true}"""))
        assertFalse("an older start has no from", flat.isGlide); assertNull(flat.dir)
        for (bad in listOf("sideways", "")) {
            val line = glideStart(9, bad)
            assertThrows(line, IllegalArgumentException::class.java) { HoldMessage.parse(JSONObject(line)) }
        }
    }

    @Test fun aGlideScrollsTheWayASingleRiseOrFallGoes() {
        assertEquals(HoldGate.Route.Glide("swipe_up"), route(glideStart(1, "up")))
        assertEquals(HoldGate.Route.Glide("swipe_down"), route(glideStart(1, "down")))
        // the user's rules decide the way, as for a single rise / fall
        val flipped = Profile.parse(JSONObject("""{"app:reader":[{"phrase":["rise"],"kind":"fixed","action":"swipe_down"}]}"""))
        assertEquals(HoldGate.Route.Glide("swipe_down"), route(glideStart(1, "up"), app = "reader", profile = flipped))
        assertEquals("other apps keep the default", HoldGate.Route.Glide("swipe_up"), route(glideStart(1, "up"), profile = flipped))
        val zoom = Profile.parse(JSONObject("""{"app:maps":[{"phrase":["rise"],"kind":"fixed","action":"zoom_in"}]}"""))
        assertTrue("a rise that zooms does not scroll", route(glideStart(1, "up"), app = "maps", profile = zoom) is HoldGate.Route.Ignore)
        val rule = Profile.parse(JSONObject("""{"global":[{"phrase":["fall"],"kind":"rule","rule":"fall scrolls a little"}]}"""))
        assertTrue("a rule only the model applies", route(glideStart(1, "down"), profile = rule) is HoldGate.Route.Ignore)
        assertTrue("cursor mode moves the cursor", route(glideStart(1, "up"), mode = "cursor") is HoldGate.Route.Ignore)
    }

    @Test fun theGateForGlides() {
        val g = glideStart(1, "up")
        assertTrue(route(g, armed = false) is HoldGate.Route.Ignore)
        assertTrue(route(g, paused = true) is HoldGate.Route.Ignore)
        assertTrue(route(g, listening = true) is HoldGate.Route.Ignore)
        assertTrue("a waiting sequence may take this sound", route(g, waiting = true) is HoldGate.Route.Ignore)
        assertEquals(HoldGate.Route.Buffer, route(g, deciding = true))
        // the older starts route as before: flat -> after-a-swipe check, settled (flat:false) -> never
        val flat = """{"v":1,"hold":"start","sound":5,"t_start_ms":0,"t_ms":300,"f0_hz":150,"flat":true}"""
        assertEquals(HoldGate.Route.Flat, route(flat))
        assertEquals(HoldGate.Route.Buffer, route(flat, waiting = true))
        assertTrue(route(flat.replace("\"flat\":true", "\"flat\":false")) is HoldGate.Route.Ignore)
    }

    /**
     * Fake device streams, as VoxService handles them: hold starts through [HoldGate], the final events through
     * [HoldScroller.consumeFinal] (dropped = its hold scrolled; kept = decided as a normal rise / fall step).
     */
    private class Service {
        val clock = Clock()
        val begun = mutableListOf<String>()
        val scroller = HoldScroller(clock, { "app" }, { true }, object : ScrollDrag {
            override fun begin(action: String, onFail: (String) -> Unit) { begun += action }; override fun end() {}
        })
        val steps = mutableListOf<String>()
        var lastSwipe: HoldScrollTrigger.Swipe? = null
        var n = 0L

        fun hold(line: String) {
            val h = HoldMessage.parse(JSONObject(line))
            when (h.kind) {
                "end" -> scroller.holdEnded(h.sound.toString())
                "pitch" -> scroller.pitch(h.sound.toString(), h.f0Hz!!, h.tMs)
                else -> when (val r = HoldGate.route(h, true, false, false, false, false, "gesture", "app", Profile.empty())) {
                    is HoldGate.Route.Glide -> { lastSwipe = null; scroller.start(r.action, "app", h.sound.toString(), h.f0Hz) }
                    HoldGate.Route.Flat -> HoldScrollTrigger.follows(lastSwipe, n, "gesture", "app", h.tStartMs, clock.now())
                        ?.let { scroller.start(lastSwipe!!.action, "app", h.sound.toString(), h.f0Hz); lastSwipe = null }
                    else -> {}
                }
            }
            clock.advance(10)
        }

        /** A sound's final event ([label], device times): dropped if its hold scrolled, else a normal step. */
        fun final(label: String, sound: Long, t0: Long, t1: Long, held: Boolean) {
            if (scroller.consumeFinal(sound.toString())) return
            val action = Vocab.DEFAULT_BINDINGS[listOf(label)] ?: "none"                // a single sound, default rules
            steps += action; n++
            if (action in HoldScrollTrigger.DIRECTIONS)
                lastSwipe = HoldScrollTrigger.Swipe(n, action, "app", "gesture", Stamp(t0, t1, sound, held), clock.now())
            clock.advance(10)
        }
    }

    @Test fun fakeStreamGlideWithAHeldTailScrollsUntilRelease() {
        val s = Service()
        s.hold(glideStart(21, "down", t0 = 1000, tailMs = 300))                       // 300 ms tail: the Pico sends a glide hold
        assertTrue(s.scroller.active); assertEquals(listOf("swipe_down"), s.begun)
        s.hold("""{"v":1,"hold":"pitch","sound":21,"t_ms":1850,"f0_hz":211.0}""")
        s.clock.advance(1500)
        assertTrue("keeps scrolling while held", s.scroller.active)
        s.hold("""{"v":1,"hold":"end","sound":21,"t_start_ms":1000,"t_ms":3200}""")
        assertFalse("release stops it", s.scroller.active)
        s.final("fall", 21, 1000, 3200, held = true)
        assertEquals("no extra step for the glide's own final event", emptyList<String>(), s.steps)
    }

    @Test fun fakeStreamGlideWithAShortTailIsOneStep() {
        val s = Service()
        s.final("fall", 22, 1000, 1450, held = false)                                   // 100 ms tail: no hold message at all
        assertFalse(s.scroller.active)
        assertEquals(listOf("swipe_down"), s.steps)
    }

    @Test fun fakeStreamGlideThenGapThenHumStillScrolls() {
        val s = Service()
        s.final("rise", 23, 1000, 1400, held = false)                                   // the glide: one step
        s.hold("""{"v":1,"hold":"start","sound":24,"t_start_ms":1700,"t_ms":2000,"f0_hz":180.0,"flat":true}""")
        assertTrue("the separate held hum continues the swipe", s.scroller.active)
        assertEquals(listOf("swipe_up"), s.begun)
        s.hold("""{"v":1,"hold":"end","sound":24,"t_start_ms":1700,"t_ms":3500}""")
        s.final("flat", 24, 1700, 3500, held = true)
        assertEquals("the hum's final event is not a long-press", listOf("swipe_up"), s.steps)
    }
}
