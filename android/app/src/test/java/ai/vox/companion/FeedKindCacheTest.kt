package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/**
 * The swipe-plan cache ([FeedKindCache], [FlingPlan], [StepCheck], [FeedKindWatcher]): a rise / fall dispatches from
 * the cached answer without reading the tree (round 4 waited 250-300 ms per TikTok fling and a median 248 ms per
 * Instagram home step for that read); a cached step only uses a list that is still on screen; a "neither" answer
 * expires fast.
 */
class FeedKindCacheTest {
    private var now = 10_000L
    private fun cache() = FeedKindCache({ now })
    private val W = 1080; private val H = 2640

    private val TT = "com.zhiliaoapp.musically"
    private val IG = "com.instagram.android"
    private val YT = "com.google.android.youtube"
    private val NOT_FEED_APP = "org.fossify.gallery"
    private val RV = "androidx.recyclerview.widget.RecyclerView"

    private fun listNode(t: Int = 94, b: Int = 2388, fwd: Boolean = true, back: Boolean = true, vis: Boolean = true, cls: String = RV) =
        NodeSnap(cls, "$IG:id/list", null, null, 0, t, W, b, scrollable = true, canScrollForward = fwd, canScrollBackward = back, visible = vis)

    private fun feedA(pkg: String = TT, win: Int = 7, why: String = "pager: class ViewPager") =
        FeedKindCache.Answer(pkg, win, FeedKindCache.Kind.FEED, why, screenW = W, screenH = H)
    private fun otherA(pkg: String = TT, win: Int = 7, why: String = "no scrollable list") =
        FeedKindCache.Answer(pkg, win, FeedKindCache.Kind.OTHER, why, screenW = W, screenH = H)
    private fun listA(pkg: String = IG, win: Int = 7, node: NodeSnap = listNode(), handle: Any? = "node") =
        FeedKindCache.Answer(pkg, win, FeedKindCache.Kind.LIST, "list RecyclerView", node, handle, W, H)

    // --- hit / miss / invalidation -------------------------------------------------------------------------------------

    @Test fun emptyIsAMissAndPlansThePlainFling() {
        val c = cache()
        assertEquals(FeedKindCache.Lookup.Miss, c.lookup(TT))
        assertEquals(FlingPlan.PLAIN, FlingPlan.of(c.lookup(TT)))
        assertEquals(FeedKindCache.Lookup.Miss, c.lookup(null))
    }

    @Test fun eachFreshKindHasItsPlan() {
        val c = cache()
        c.put(feedA()); now += 300
        val l = c.lookup(TT)
        assertEquals(300L, (l as FeedKindCache.Lookup.Hit).ageMs)
        assertEquals(FlingPlan.FEED, FlingPlan.of(l))
        c.put(listA()); assertEquals(FlingPlan.LIST, FlingPlan.of(c.lookup(IG)))
        c.put(otherA()); assertEquals(FlingPlan.OTHER, FlingPlan.of(c.lookup(TT)))
        assertEquals(FeedKindCache.Lookup.Miss, c.lookup(IG))   // one entry: the window in front
    }

    @Test fun windowStateChangeOfTheSameWindowKeepsTheEntry() {
        val c = cache()
        c.put(listA())
        c.windowEvent(IG, 7)
        c.windowEvent(IG, -1)   // no window id: not a new window
        assertTrue(c.lookup(IG) is FeedKindCache.Lookup.Hit)
    }

    @Test fun anotherWindowOrPackageInvalidates() {
        val c = cache()
        c.put(listA())
        c.windowEvent(IG, 9)   // a dialog / another activity of the same app
        assertEquals(FeedKindCache.Lookup.Miss, c.lookup(IG))
        c.put(feedA())
        c.windowEvent(IG, 7)
        assertEquals(FeedKindCache.Lookup.Miss, c.lookup(TT))
        assertNull(c.current())
    }

    @Test fun aRefreshThatStartedBeforeAnInvalidationIsDropped() {
        val c = cache()
        val token = c.begin(force = true)!!
        c.windowEvent(IG, 3)   // the user left TikTok while its tree was being read
        assertFalse(c.finish(token, feedA()))
        assertEquals(FeedKindCache.Lookup.Miss, c.lookup(TT))
    }

    @Test fun anOlderRefreshDoesNotOverwriteANewerAnswer() {
        val c = cache()
        val token = c.begin(force = true)!!
        now += 100
        c.put(feedA(why = "read on the spot"))
        now += 200
        c.finish(token, otherA(why = "started before it"))
        assertEquals("read on the spot", c.current()!!.why)
    }

    // --- expiry ------------------------------------------------------------------------------------------------------

    @Test fun aFeedAnswerExpiresToThePlainFlingOutsideFeedApps() {
        val c = cache()
        c.put(feedA(pkg = NOT_FEED_APP))
        now += FeedKindCache.FEED_TTL_MS
        assertEquals(FlingPlan.FEED, FlingPlan.of(c.lookup(NOT_FEED_APP)))
        now += 1
        val l = c.lookup(NOT_FEED_APP)
        assertTrue(l is FeedKindCache.Lookup.Expired)
        assertEquals(FlingPlan.PLAIN, FlingPlan.of(l, NOT_FEED_APP, c.lastKind(NOT_FEED_APP)))
    }

    @Test fun aNeitherAnswerExpiresFast() {
        val c = cache()
        c.put(otherA(why = "one page fills the viewport, not scrollable"))
        assertTrue(c.lookup(TT) is FeedKindCache.Lookup.Hit)
        now += FeedKindCache.OTHER_TTL_MS + 1
        assertTrue(c.lookup(TT) is FeedKindCache.Lookup.Expired)
        assertTrue(FeedKindCache.OTHER_TTL_MS < FeedKindCache.FEED_TTL_MS)
    }

    @Test fun aListPlanLivesLongerAndThenExpires() {
        val c = cache()
        c.put(listA())
        now += FeedKindCache.LIST_TTL_MS
        assertEquals(FlingPlan.LIST, FlingPlan.of(c.lookup(IG), IG, c.lastKind(IG)))
        now += 1
        assertEquals(FlingPlan.PLAIN, FlingPlan.of(c.lookup(IG), IG, c.lastKind(IG)))   // last answer LIST: not LAST_FEED
        assertTrue(FeedKindCache.LIST_TTL_MS > FeedKindCache.FEED_TTL_MS)
    }

    @Test fun answerOfFollowsClassify() {
        val feed = ScrollStep.Kind.Fling(ScrollStep.Decision(false, "pager: class ViewPager", feed = true))
        val none = ScrollStep.Kind.Fling(ScrollStep.Decision(false, "no scrollable list"))
        val list = ScrollStep.Kind.List(ScrollerSnap(listNode()))
        assertEquals(FeedKindCache.Kind.FEED, FeedKindCache.answerOf(TT, 1, feed, null, W, H).kind)
        assertEquals(FeedKindCache.Kind.OTHER, FeedKindCache.answerOf(TT, 1, none, null, W, H).kind)
        val a = FeedKindCache.answerOf(IG, 1, list, "h", W, H)
        assertEquals(FeedKindCache.Kind.LIST, a.kind); assertEquals(listNode(), a.list); assertEquals("h", a.handle)
        assertEquals(W, a.screenW); assertEquals(H, a.screenH)
    }

    @Test fun classifyThenListStepIsDecide() {
        val scrollers = listOf(ScrollerSnap(listNode(fwd = true, back = false)))
        for (action in listOf("swipe_up", "swipe_down")) {
            val c = ScrollStep.classify(IG, scrollers, H) as ScrollStep.Kind.List
            assertEquals(ScrollStep.decide(action, IG, scrollers, H), ScrollStep.listStep(action, c.main.node))
        }
        assertEquals(ScrollStep.Decision(false, "no scrollable list"), ScrollStep.decide("swipe_up", IG, emptyList(), H))
    }

    // --- the live check before a cached step ---------------------------------------------------------------------------

    @Test fun aLiveListStepsWithItsCurrentState() {
        val live = listNode(t = 200, fwd = false, back = true)   // moved a little, now at its end going up
        val up = StepCheck.check("swipe_up", listA(), live, W, H)
        assertNull(up.refused)
        assertEquals(ScrollStep.Decision(false, "RecyclerView is at its end that way"), up.decision)
        val down = StepCheck.check("swipe_down", listA(), live, W, H)
        assertTrue(down.decision!!.step)
        assertEquals(200, down.decision!!.list!!.top)   // the live bounds, not the cached ones
    }

    @Test fun aVanishedOrMovedListIsRefused() {
        val a = listA()
        assertEquals("list node gone", StepCheck.check("swipe_up", a, null, W, H).refused)
        assertEquals("list not visible", StepCheck.check("swipe_up", a, listNode(vis = false), W, H).refused)
        assertTrue(StepCheck.check("swipe_up", a, listNode(cls = "android.widget.ScrollView"), W, H).refused!!.startsWith("list node is now"))
        assertTrue(StepCheck.check("swipe_up", a, listNode(t = -400, b = 1800), W, H).refused!!.startsWith("list off screen"))
        assertTrue(StepCheck.check("swipe_up", a, listNode(t = 100, b = 3000), W, H).refused!!.startsWith("list off screen"))
        assertTrue(StepCheck.check("swipe_up", a, listNode(t = 500, b = 500), W, H).refused!!.startsWith("list off screen"))
        assertTrue(StepCheck.check("swipe_up", a, listNode(), H, W).refused!!.startsWith("screen size changed"))   // rotated / folded
        assertEquals("no cached list", StepCheck.check("swipe_up", feedA(), listNode(), W, H).refused)
        StepCheck.check("swipe_up", a, listNode(), W, H).let { assertNull(it.refused); assertTrue(it.decision!!.step) }
    }

    // --- no usable answer in a known feed app: the last answer this session decides ----------------------------------

    @Test fun feedAppsAreAFixedListIncludingTikTokInstagramAndYouTube() {
        assertTrue(ScrollStep.PAGER_PKGS.all { it in ScrollStep.FEED_APPS })
        for (p in listOf(TT, IG, YT, "app.rvx.android.youtube", "app.revanced.android.youtube")) assertTrue(p, p in ScrollStep.FEED_APPS)
        assertTrue(IG !in ScrollStep.PAGER_PKGS)   // rule 4 of ScrollStep.decide is unchanged
    }

    @Test fun aMissInAFeedAppWhoseLastAnswerWasFeedIsTheFeedFling() {
        val c = cache()
        c.put(feedA(pkg = IG, why = "id clips_viewer_view_pager"))
        c.windowEvent(IG, 9)   // a new window: the entry is gone, the session memory is not
        assertEquals(FeedKindCache.Lookup.Miss, c.lookup(IG))
        assertEquals(FeedKindCache.Kind.FEED, c.lastKind(IG))
        assertEquals(FlingPlan.LAST_FEED, FlingPlan.of(c.lookup(IG), IG, c.lastKind(IG)))
    }

    @Test fun anExpiredFeedAnswerInAFeedAppIsTheFeedFling() {
        val c = cache()
        c.put(feedA())
        now += FeedKindCache.FEED_TTL_MS + 1
        assertEquals(FlingPlan.LAST_FEED, FlingPlan.of(c.lookup(TT), TT, c.lastKind(TT)))
    }

    @Test fun aMissWithNoFeedStatusIsThePlainFling() {
        val c = cache()
        assertEquals(FlingPlan.PLAIN, FlingPlan.of(c.lookup(IG), IG, c.lastKind(IG)))   // nothing yet this session
        c.put(listA()); c.invalidate()   // Instagram's home list last
        assertEquals(FlingPlan.PLAIN, FlingPlan.of(c.lookup(IG), IG, c.lastKind(IG)))
        c.put(feedA(pkg = NOT_FEED_APP)); c.invalidate()   // a photo pager: not a known feed app
        assertEquals(FlingPlan.PLAIN, FlingPlan.of(c.lookup(NOT_FEED_APP), NOT_FEED_APP, c.lastKind(NOT_FEED_APP)))
        c.put(feedA()); c.invalidate()
        assertEquals(FlingPlan.PLAIN, FlingPlan.of(c.lookup(TT)))   // no package given: no session memory
    }

    @Test fun theLastAnswerFollowsTheNewestStoredAnswer() {
        val c = cache()
        c.put(feedA(pkg = IG))
        c.finish(c.begin(force = true)!!, listA())
        assertEquals(FeedKindCache.Kind.LIST, c.lastKind(IG))
        val t = c.begin(force = true)!!
        c.windowEvent(TT, 1)   // a dropped result changes nothing
        c.finish(t, feedA(pkg = IG))
        assertEquals(FeedKindCache.Kind.LIST, c.lastKind(IG))
    }

    // --- refresh scheduling ------------------------------------------------------------------------------------------

    @Test fun contentChangesRefreshAtMostEveryGap() {
        val c = cache()
        c.finish(c.begin(force = false)!!, feedA())   // no entry: starts at once
        now += FeedKindCache.REFRESH_GAP_MS - 1
        assertNull(c.begin(force = false))
        assertEquals(1L, c.msUntilRefresh())
        now += 1
        assertNotNull(c.begin(force = false))
    }

    @Test fun oneRefreshAtATimeAndAForcedOneRunsAgain() {
        val c = cache()
        val t = c.begin(force = true)!!
        assertNull(c.begin(force = false))
        assertNull(c.begin(force = true))   // remembered
        assertTrue(c.finish(t, feedA()))
        assertNull(c.begin(force = false))   // within the gap: only a forced one
        assertFalse(c.finish(c.begin(force = true)!!, feedA()))
    }

    @Test fun aBurstOfContentChangesEndsWithATrailingRead() {
        val ran = mutableListOf<Runnable>()
        val timers = mutableListOf<Pair<Long, Runnable>>()
        var answer = listA()
        val w = FeedKindWatcher(cache(), { answer }, { ran += it }, { ms, r -> timers += ms to r })
        w.contentChanged(); ran.removeAt(0).run()   // first change: read at once
        now += 500
        answer = feedA(pkg = IG)   // the user opened Reels in the same window
        w.contentChanged(); w.contentChanged(); w.contentChanged()   // too soon: one trailing read, not three
        assertTrue(ran.isEmpty())
        assertEquals(1, timers.size)
        assertEquals(FeedKindCache.REFRESH_GAP_MS - 500, timers[0].first)
        now += timers[0].first
        timers.removeAt(0).second.run()
        ran.removeAt(0).run()
        assertEquals(FlingPlan.FEED, w.plan(IG).first)
    }

    // --- the watcher: no tree read on the swipe's path -----------------------------------------------------------------

    private class SlowReader(val answer: FeedKindCache.Answer?) {
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        val thread = AtomicReference<Thread>()
        fun read(): FeedKindCache.Answer? {
            thread.set(Thread.currentThread()); entered.countDown()
            release.await(5, TimeUnit.SECONDS)
            return answer
        }
    }

    @Test fun planNeverWaitsForASlowTreeRead() {
        val bg = Executors.newSingleThreadExecutor()
        try {
            val r = SlowReader(listA())
            val w = FeedKindWatcher(cache(), r::read, bg::execute)
            w.windowStateChanged(IG, 7)
            assertTrue(r.entered.await(2, TimeUnit.SECONDS))   // the read is running (and blocked)
            val t0 = System.nanoTime()
            val (plan, look) = w.plan(IG)
            val ms = (System.nanoTime() - t0) / 1e6
            assertEquals(FlingPlan.PLAIN, plan)   // no answer yet: the plain fling, at once
            assertEquals("miss", look.label)
            assertTrue("plan took $ms ms", ms < 50)
            assertNotEquals(Thread.currentThread(), r.thread.get())
            r.release.countDown()
            bg.submit {}.get(2, TimeUnit.SECONDS)
            bg.submit {}.get(2, TimeUnit.SECONDS)   // the forced request made during the read runs once more
            assertEquals(FlingPlan.LIST to "hit", w.plan(IG).let { it.first to it.second.label })
        } finally { bg.shutdownNow() }
    }

    @Test fun cachedPlansAnswerAtOnceWhileARefreshIsSlow() {
        val bg = Executors.newSingleThreadExecutor()
        try {
            val c = cache()
            c.put(listA())
            val r = SlowReader(listA())
            val w = FeedKindWatcher(c, r::read, bg::execute)
            now += FeedKindCache.REFRESH_GAP_MS
            w.contentChanged()
            assertTrue(r.entered.await(2, TimeUnit.SECONDS))
            val t0 = System.nanoTime()
            assertEquals(FlingPlan.LIST, w.plan(IG).first)
            assertTrue((System.nanoTime() - t0) / 1e6 < 50)
            r.release.countDown()
        } finally { bg.shutdownNow() }
    }

    @Test fun theReadNeverRunsOnTheCallersThread() {
        val ran = mutableListOf<Runnable>()
        var reads = 0
        val w = FeedKindWatcher(cache(), { reads++; feedA() }, { ran += it })
        w.windowStateChanged(TT, 7)
        assertEquals(FlingPlan.PLAIN, w.plan(TT).first)
        assertEquals(0, reads)   // queued on the background runner only
        ran.removeAt(0).run()
        assertEquals(1, reads)
        assertEquals(FlingPlan.FEED, w.plan(TT).first)
    }

    @Test fun aFailingReadStoresNothingAndDoesNotWedgeTheRefresh() {
        val ran = mutableListOf<Runnable>()
        var fail = true
        val w = FeedKindWatcher(cache(), { if (fail) throw IllegalStateException("tree gone") else feedA() }, { ran += it })
        w.refresh(force = true)
        ran.removeAt(0).run()
        assertNull(w.cache.current())
        fail = false
        w.refresh(force = true)
        ran.removeAt(0).run()
        assertEquals(FeedKindCache.Kind.FEED, w.cache.current()!!.kind)
    }

    @Test fun aNeitherReadIsReplacedByTheNextFeedRead() {
        // TikTok's pager briefly without a visible scroller (a video loading): "no scrollable list" is cached (the
        // plain fling, never a stop), and the next refresh finds the feed again
        val ran = mutableListOf<Runnable>()
        var answer = otherA()
        val w = FeedKindWatcher(cache(), { answer }, { ran += it })
        w.windowStateChanged(TT, 7); ran.removeAt(0).run()
        assertEquals(FlingPlan.OTHER, w.plan(TT).first)
        answer = feedA()
        now += FeedKindCache.REFRESH_GAP_MS
        w.contentChanged(); ran.removeAt(0).run()
        assertEquals(FlingPlan.FEED, w.plan(TT).first)
    }

    @Test fun theWatcherPlansTheLastFeedAndStillRefreshes() {
        val ran = mutableListOf<Runnable>()
        var reads = 0
        val w = FeedKindWatcher(cache(), { reads++; feedA(pkg = IG, win = 9) }, { ran += it })
        w.cache.put(feedA(pkg = IG))
        w.cache.windowEvent(IG, 9)
        val (plan, look) = w.plan(IG)
        assertEquals(FlingPlan.LAST_FEED, plan)
        assertEquals("miss", look.label)
        assertEquals(1, ran.size)   // a background refresh was started, not run on the caller's thread
        assertEquals(0, reads)
        ran.removeAt(0).run()
        assertEquals(FlingPlan.FEED, w.plan(IG).first)
    }

    // --- the probe for undetected feeds ------------------------------------------------------------------------------

    @Test fun theProbeLogsStructureNeverText() {
        val page = NodeSnap("android.view.SurfaceView", "$YT:id/player", "secret caption", "secret desc", 0, 0, W, H)
        val hidden = NodeSnap(RV, "$YT:id/reel_recycler", "t", null, 0, 0, W, H, scrollable = true, visible = false, children = listOf(page))
        val root = NodeSnap("android.widget.FrameLayout", null, "root text", null, 0, 0, W, H, children = listOf(hidden))
        val s = FeedProbe.summary(root, W, H)
        assertEquals(3, s.getInt("nodes"))
        val sc = s.getJSONArray("scrollables").getJSONObject(0)
        assertEquals("reel_recycler", sc.getString("id")); assertFalse(sc.getBoolean("visible"))
        assertEquals(1, s.getJSONArray("video").length())
        assertFalse(s.toString().contains("secret")); assertFalse(s.toString().contains("root text"))
    }
}
