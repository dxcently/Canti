package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Paged video feeds (TikTok, Instagram Reels, YouTube Shorts, Facebook reels): the screen line says "video feed"
 * ([ScreenSummarizer]) and [ScrollStep.decide] says `feed`, so rise / fall, voice scroll and next / previous all fling
 * (in `feed_fling_ms`), never ACTION_SCROLL or a media key. Ordinary lists keep the step.
 *
 * The TikTok tree is the shape of a real Z Flip dump (For You, 2026-09-26, structure only: classes, ids, bounds,
 * visibility; no text). The Reels / Shorts / Facebook shapes are assumed from their known view ids and layouts (no
 * dump yet); replace them with dumped shapes when those exist.
 */
class FeedDetectTest {
    private val W = 1080; private val H = 2640

    private fun n(cls: String, l: Int, t: Int, r: Int, b: Int, vararg kids: NodeSnap) = NodeSnap(cls, null, null, null, l, t, r, b, children = kids.toList())

    /** Options after the children (Kotlin cannot put named arguments before a vararg's positional ones). */
    private fun NodeSnap.o(id: String? = this.id, scroll: Boolean = scrollable, fwd: Boolean = canScrollForward, back: Boolean = canScrollBackward,
                           rows: Int = this.rows, cols: Int = this.cols, vis: Boolean = visible) =
        copy(id = id, scrollable = scroll, canScrollForward = fwd, canScrollBackward = back, rows = rows, cols = cols, visible = vis)

    private fun facts(pkg: String, music: Boolean = true) = ScreenFacts(pkg, W, H, false, emptySet(), music)

    /** What [ScrollerReader] makes of the tree: visible scrollers, their direct children, the parent's class. */
    private fun scrollers(root: NodeSnap): List<ScrollerSnap> {
        val out = mutableListOf<ScrollerSnap>()
        fun walk(x: NodeSnap, parent: String?) {
            if (x.scrollable && x.visible) out += ScrollerSnap(x.copy(children = x.children.map { it.copy(children = emptyList()) }), parent)
            x.children.forEach { walk(it, x.cls) }
        }
        walk(root, null)
        return out
    }

    private fun decide(root: NodeSnap, pkg: String, action: String = "swipe_up") = ScrollStep.decide(action, pkg, scrollers(root), H)

    // --- TikTok (For You), the Z Flip dump's shape --------------------------------------------------------------------

    private val tt = "com.zhiliaoapp.musically:id/"
    private val FL = "android.widget.FrameLayout"

    /** One video page: full-bleed player, the side rail and caption as small overlays; off-screen pages are invisible. */
    private fun ttPage(vis: Boolean, t: Int, b: Int) = if (!vis) n(FL, 0, t, 1080, b).o(id = "${tt}view_rootview", vis = false)
    else n(FL, 0, t, 1080, b,
        n("X.060g", 0, 0, 1080, 2385,
            n("android.widget.ImageView", 942, 1431, 1059, 1548).o(id = "${tt}user_avatar"),
            n("android.widget.ImageView", 942, 1591, 1060, 1708),
            n("android.widget.LinearLayout", 0, 1392, 1080, 2385).o(id = "${tt}llj")).o(id = "${tt}widget_container"),
        n("android.view.View", 0, 0, 1080, 2385).o(id = "${tt}long_press_layout"),
        n("android.widget.LinearLayout", 0, 0, 1080, 2385,
            n(FL, 0, 0, 1080, 2385, n("android.view.View", 0, 232, 1080, 2152)).o(id = "${tt}player_view")).o(id = "${tt}video_container_area"),
        n("android.widget.HorizontalScrollView", 32, 2129, 870, 2187).o(scroll = true, fwd = true),   // a hashtag strip
        n("android.widget.SeekBar", 0, 2360, 1080, 2385),
    ).o(id = "${tt}view_rootview")

    /** The vertical feed pager (a ViewPager: no CollectionInfo, no scroll actions) inside two tab pagers (X.05rZ). */
    private fun tiktok(): NodeSnap {
        val feed = n("androidx.viewpager.widget.ViewPager", 0, 0, 1080, 2385,
            ttPage(false, 0, 0), ttPage(true, 0, 2385), ttPage(false, 2385, 2385)).o(id = "${tt}viewpager", scroll = true)
        val inner = n("X.05rZ", 0, 0, 1080, 2514,
            n(FL, 0, 0, 1080, 2514,
                n("android.widget.LinearLayout", 0, 0, 1080, 2514,
                    n(FL, 0, 0, 1080, 2385, feed).o(id = "${tt}view_pager_layout_wrapper")).o(id = "${tt}viewpager_container"),
                n(FL, 0, 94, 1080, 246)).o(id = "${tt}ibs")   // (the Following / For You tab row)
        ).o(id = "${tt}viewpager", scroll = true, back = true)
        val outer = n("X.05rZ", 0, 0, 1080, 2514,
            n(FL, 0, 0, 0, 2514).o(id = "${tt}wm4", vis = false),
            n("android.widget.TabHost", 0, 0, 1080, 2514, inner).o(id = "${tt}oqa"),
            n(FL, 1080, 0, 1080, 2514).o(id = "${tt}f2x", vis = false)).o(id = "${tt}viewpager", scroll = true, back = true)
        return n(FL, 0, 0, 1080, 2640,
            n(FL, 0, 0, 1080, 2514, outer).o(id = "android:id/content"),
            n("android.widget.LinearLayout", 0, 2385, 1080, 2514))   // the bottom nav bar
    }

    @Test fun tiktokForYouIsAVideoFeed() {
        val root = tiktok()
        // round 3 read this as "scrolling list … at the bottom" (the outer tab pager); now the feed pager is found
        assertEquals("video feed", ScreenSummarizer.classify(root, facts("com.zhiliaoapp.musically")).kind)
        // structurally, without the package fallback, and paused (no audio)
        assertEquals("video feed", ScreenSummarizer.classify(root, facts("com.example", music = false)).kind)
        for (a in listOf("swipe_up", "swipe_down")) {
            val d = decide(root, "com.example", a)
            assertTrue(d.why, d.feed); assertFalse(d.step)
        }
        assertTrue(decide(root, "com.zhiliaoapp.musically").feed)
    }

    @Test fun tiktokPackageFallback() {
        // a sparse tree (no page children seen): the package keeps it a feed, if the scroller covers most of the screen
        val bare = n(FL, 0, 0, 1080, 2640,
            n("X.05rZ", 0, 0, 1080, 2514, *Array(8) { n(FL, 0, it * 300, 1080, it * 300 + 290) }).o(scroll = true, back = true))
        assertEquals("video feed", ScreenSummarizer.classify(bare, facts("com.zhiliaoapp.musically")).kind)
        assertEquals("scrolling list", ScreenSummarizer.classify(bare, facts("com.example")).kind)
        assertTrue(decide(bare, "com.zhiliaoapp.musically").feed)
        assertEquals("05rZ is at its end that way", decide(bare, "com.example").why)
        assertTrue(decide(bare, "com.example", "swipe_down").step)
        // TikTok's comment sheet (a short list): not a feed, it steps
        val comments = n(FL, 0, 0, 1080, 2640,
            n("androidx.recyclerview.widget.RecyclerView", 0, 1200, 1080, 2400, *Array(6) { n(FL, 0, 1200 + it * 200, 1080, 1390 + it * 200) })
                .o(scroll = true, fwd = true, back = true, rows = 50, cols = 1))
        assertTrue(decide(comments, "com.zhiliaoapp.musically").step)
    }

    // --- Reels, Shorts, Facebook reels (assumed shapes) ---------------------------------------------------------------

    private fun fullPage(t: Int = 0, b: Int = 2640) = n(FL, 0, t, 1080, b,
        n(FL, 0, t, 1080, b), n("android.widget.ImageView", 950, 1500, 1050, 1600), n("android.widget.TextView", 40, 2200, 900, 2260))

    /** Instagram's Reels tab (structure of the Z Flip dump, 2026-09-27; home feed rows at width 0 left out). */
    private fun reelsTab(pkg: String, innerScrolls: Boolean): NodeSnap {
        val page = n(FL, 0, 94, 1080, 2388,
            n("android.view.ViewGroup", 0, 94, 1080, 2388,
                n("android.view.ViewGroup", 0, 94, 1080, 2388,
                    n(FL, 0, 94, 1080, 2388, n(FL, 0, 281, 1080, 2201, n("android.view.View", 0, 281, 1080, 2201)).o(id = "$pkg:id/clips_video_container"))
                        .o(id = "$pkg:id/clips_viewer_video_layout")).o(id = "$pkg:id/clips_media_component"),
                n("android.view.ViewGroup", 0, 94, 1080, 2388,
                    n("android.widget.ImageView", 943, 1392, 1059, 1508).o(id = "$pkg:id/comment_button"),
                    n("android.widget.ImageView", 52, 2146, 147, 2241).o(id = "$pkg:id/clips_author_profile_pic"),
                    n("android.widget.SeekBar", 0, 2362, 1080, 2388).o(id = "$pkg:id/scrubber"))))
        val list = n("androidx.recyclerview.widget.RecyclerView", 0, 94, 1080, 2388, page)
            .let { if (innerScrolls) it.o(scroll = true, fwd = true, back = true, rows = 20, cols = 1) else it }
        val clips = n("androidx.viewpager.widget.ViewPager", 0, 94, 1080, 2388, list).o(id = "$pkg:id/clips_viewer_view_pager", scroll = true, fwd = true, back = true)
        val reelsTab = n(FL, 0, 94, 1080, 2388,
            n(FL, 0, 94, 1080, 2388, n(FL, 0, 94, 1080, 2388, n(FL, 0, 94, 1080, 2388, clips).o(id = "$pkg:id/clips_viewer_container"))
                .o(id = "$pkg:id/gesture_manager")).o(id = "$pkg:id/root_clips_layout"),
            n("android.widget.RelativeLayout", 0, 94, 1080, 241).o(id = "$pkg:id/clips_viewer_action_bar"))
        val nav = n("androidx.recyclerview.widget.RecyclerView", 0, 94, 1080, 2388,
            n(FL, 0, 94, 0, 2388).o(vis = false), reelsTab).o(id = "$pkg:id/swipeable_nav_view_pager_inner_recycler_view",
                scroll = innerScrolls, fwd = innerScrolls, back = innerScrolls, rows = 1, cols = 5)
        val tabs = n("androidx.viewpager.widget.ViewPager", 0, 94, 1080, 2388, nav).o(id = "$pkg:id/swipeable_tab_view_pager", scroll = true, fwd = true, back = true)
        return n(FL, 0, 0, 1080, 2640, n(FL, 0, 94, 1080, 2514, tabs, n(FL, 0, 2388, 1080, 2514).o(id = "$pkg:id/tab_bar")))
    }

    @Test fun instagramReels() {
        val pkg = "com.instagram.android"
        // the Reels tab, the Z Flip dump's shape: a horizontal tab ViewPager > its nav RecyclerView > the Reels tab >
        // clips_viewer_view_pager (a ViewPager) > an inner RecyclerView > one full page; all 0,94..2388. Which of them
        // report scrollable is not in the dump: both ways are checked.
        for (inner in listOf(true, false)) {
            val tab = reelsTab(pkg, inner)
            assertEquals("inner=$inner", "video feed", ScreenSummarizer.classify(tab, facts(pkg)).kind)
            val d = decide(tab, pkg)
            assertTrue("inner=$inner: ${d.why}", d.feed)
            assertTrue(decide(tab, pkg, "swipe_down").feed)
        }
        // a reel opened from the feed: full screen, no tab bar, the first reel (cannot go back), paused
        val opened = n(FL, 0, 0, 1080, 2640,
            n("androidx.viewpager.widget.ViewPager", 0, 0, 1080, 2640, fullPage()).o(id = "$pkg:id/clips_viewer_view_pager", scroll = true, fwd = true))
        assertEquals("video feed", ScreenSummarizer.classify(opened, facts(pkg, music = false)).kind)
        val d = decide(opened, pkg, "swipe_down")
        assertTrue(d.why, d.feed)
        // the home feed stays a list: several posts, under the top bar
        val home = n(FL, 0, 0, 1080, 2640,
            n("androidx.recyclerview.widget.RecyclerView", 0, 250, 1080, 2460,
                n("android.widget.LinearLayout", 0, 250, 1080, 1700), n("android.widget.LinearLayout", 0, 1700, 1080, 2460))
                .o(id = "android:id/list", scroll = true, fwd = true, rows = 30, cols = 1))
        assertEquals("scrolling list", ScreenSummarizer.classify(home, facts(pkg)).kind)
        assertTrue(decide(home, pkg).step)
    }

    @Test fun youtubeShortsInBothYoutubeApps() {
        for (pkg in listOf("com.google.android.youtube", "app.revanced.android.youtube", "app.rvx.android.youtube")) {
            val shorts = n(FL, 0, 0, 1080, 2640,
                n("androidx.recyclerview.widget.RecyclerView", 0, 0, 1080, 2470,
                    n(FL, 0, 0, 1080, 2470, n("android.view.ViewGroup", 0, 0, 1080, 2470), n("android.widget.ImageView", 960, 1300, 1060, 1400))
                        .o(id = "$pkg:id/reel_player_page_container"))
                    .o(id = "$pkg:id/reel_recycler", scroll = true, fwd = true, back = true),
                n(FL, 0, 2470, 1080, 2640).o(id = "$pkg:id/pivot_bar"))
            assertEquals(pkg, "video feed", ScreenSummarizer.classify(shorts, facts(pkg)).kind)
            assertTrue(pkg, decide(shorts, pkg).feed)
            assertTrue(pkg, decide(shorts, pkg, "swipe_down").feed)
        }
    }

    @Test fun facebookReelsByPageFill() {
        // no useful ids: a full-bleed scroller showing one page (plus small overlays) is a feed
        val pkg = "com.facebook.katana"
        val reels = n(FL, 0, 0, 1080, 2640,
            n("android.view.ViewGroup", 0, 0, 1080, 2640,
                fullPage(), n("android.widget.Button", 960, 1500, 1060, 1600), n("android.widget.Button", 960, 1650, 1060, 1750))
                .o(scroll = true, fwd = true, back = true))
        assertEquals("video feed", ScreenSummarizer.classify(reels, facts(pkg)).kind)
        assertTrue(decide(reels, pkg).feed)
    }

    @Test fun notFeeds() {
        // a photo pager (still image page): a photo viewer, not a feed
        val photos = n(FL, 0, 0, 1080, 2640,
            n("androidx.viewpager.widget.ViewPager", 0, 0, 1080, 2640, n(FL, 0, 0, 1080, 2640, n("android.widget.ImageView", 0, 300, 1080, 2300)))
                .o(scroll = true, fwd = true, rows = 1, cols = 9))
        assertEquals("photo viewer", ScreenSummarizer.classify(photos, facts("org.fossify.gallery", music = false)).kind)
        assertFalse(decide(photos, "org.fossify.gallery").feed)
        // a tab pager around a list (NewPipe)
        val rowsKids = Array(10) { n("android.widget.LinearLayout", 0, 400 + it * 180, 1080, 570 + it * 180) }
        val tabs = n(FL, 0, 0, 1080, 2640,
            n("androidx.viewpager.widget.ViewPager", 0, 300, 1080, 2400,
                n("androidx.recyclerview.widget.RecyclerView", 0, 300, 1080, 2400, *rowsKids).o(scroll = true, fwd = true, rows = 40, cols = 1))
                .o(id = "org.schabi.newpipe:id/pager", scroll = true, fwd = true))
        assertEquals("scrolling list", ScreenSummarizer.classify(tabs, facts("org.schabi.newpipe", music = false)).kind)
        assertTrue(decide(tabs, "org.schabi.newpipe").step)
    }

    @Test fun feedFlingSetting() {
        assertEquals(50, ScrollStep.FEED_FLING_MS)
        assertEquals(30..150, ScrollStep.FEED_FLING_RANGE)
        assertTrue("snappier than the list fling", ScrollStep.FEED_FLING_MS < SwipeGeometry.DURATION_MS)
        assertEquals(15, ScrollStep.FEED_FLING_PCT)
        assertEquals(8..60, ScrollStep.FEED_FLING_PCT_RANGE)
    }

    @Test fun feedLineIsAShortStrokeFromTheUsualStart() {
        val safe = SwipeGeometry.Safe(84, 126, 84, 126)
        val (w, h) = 1080 to 2640   // Z Flip
        val up = ScrollStep.feedLine("swipe_up", w, h, safe, ScrollStep.FEED_FLING_PCT)!!
        val old = SwipeGeometry.line("swipe_up", w, h, safe)!!
        assertEquals(old[1], up[1], 0.5f)                         // same start (72%)
        assertEquals(396f, up[1] - up[3], 1f)                     // 15% of 2640
        assertEquals(540f, up[0], 0f); assertEquals(540f, up[2], 0f)
        // ~7.9k px/s at the 50 ms default: about half the old feed fling's 15.8k (1584 px in 100 ms)
        val v = (up[1] - up[3]) / ScrollStep.FEED_FLING_MS * 1000
        val vOld = (old[1] - old[3]) / SwipeGeometry.DURATION_MS * 1000
        assertTrue("v=$v vOld=$vOld", v in 7000f..9000f && v * 1.8f < vOld)
        val down = ScrollStep.feedLine("swipe_down", w, h, safe, 15)!!
        assertEquals(h * 0.28f, down[1], 0.5f); assertEquals(h * 0.43f, down[3], 0.5f)
        // pct 60 is the old fling's line; out-of-range values are clamped; sideways is not a feed line
        val full = ScrollStep.feedLine("swipe_up", w, h, safe, 60)!!
        assertEquals(old[3], full[3], 0.5f)
        assertEquals(h * 0.72f - h * 0.08f, ScrollStep.feedLine("swipe_up", w, h, safe, 1)!![3], 0.5f)
        assertEquals(null, ScrollStep.feedLine("swipe_left", w, h, safe, 15))
    }
}
