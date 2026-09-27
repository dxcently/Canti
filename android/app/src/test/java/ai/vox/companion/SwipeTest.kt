package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Swipes.kt: the direction convention both ways, counts, and where next/previous goes on each screen. */
class SwipeTest {
    private fun action(s: String) = (SwipeGrammar.parse(PhraseGrammar.normalize(s)) as SpeechCommand.Swipe).action

    @Test fun conventionFingerWordsVersusContentWords() {
        // swipe/flick: the finger's direction
        assertEquals("swipe_right", action("swipe right")); assertEquals("swipe_left", action("swipe left"))
        assertEquals("swipe_right", action("flick right")); assertEquals("swipe_left", action("swipe to the left"))
        // scroll/go/move/what's on: the content wanted, so the finger goes the opposite way
        assertEquals("swipe_left", action("scroll right")); assertEquals("swipe_right", action("scroll left"))
        assertEquals("swipe_left", action("go right")); assertEquals("swipe_right", action("move left"))
        assertEquals("swipe_left", action("what's on the right")); assertEquals("swipe_right", action("show me what's on the left"))
    }

    @Test fun counts() {
        assertEquals(1, SwipeGrammar.count(null)); assertEquals(2, SwipeGrammar.count("twice")); assertEquals(3, SwipeGrammar.count("three times"))
        assertEquals(SwipeGrammar.MAX_COUNT, SwipeGrammar.count("twenty times")); assertEquals(1, SwipeGrammar.count("again"))
        assertNull(SwipeGrammar.count("ahead")); assertNull(SwipeGrammar.count("on her"))
    }

    private fun plan(next: Boolean, noun: String = "", kind: String? = null, button: Boolean = false, rtl: Boolean = false) =
        SwipePlan.semantic(next, noun, kind, button, rtl)

    @Test fun nextFollowsTheScreenType() {
        assertEquals("swipe_left", plan(true, kind = "photo viewer").action)       // next photo: content from the right
        assertEquals("swipe_right", plan(false, kind = "photo viewer").action)
        assertEquals("swipe_up", plan(true, kind = "video feed").action)           // a vertical feed
        assertEquals("swipe_down", plan(false, kind = "video feed").action)
        assertEquals("swipe_left", plan(true, noun = "photo", kind = "photo viewer").action)
        assertTrue(plan(true, kind = "photo viewer").via.startsWith("screen"))
    }

    @Test fun elseTheNounThenAButtonThenTheRules() {
        assertEquals("swipe_left", plan(true, noun = "slide", kind = "other").action)
        assertEquals("noun: slide", plan(true, noun = "slide", kind = "other").via)
        val b = plan(true, kind = "other", button = true)
        assertTrue(b.tapButton); assertNull(b.action)
        assertEquals("next_item", plan(true, kind = "video player").action)        // media: the rules' next track
        assertEquals("previous_item", plan(false).action)
        assertFalse(plan(false).tapButton)
    }

    @Test fun rightToLeftMirrorsOnlyHorizontalNextPrevious() {
        assertEquals("swipe_right", plan(true, kind = "photo viewer", rtl = true).action)
        assertEquals("swipe_left", plan(false, noun = "photo", kind = "other", rtl = true).action)
        assertEquals("swipe_up", plan(true, kind = "video feed", rtl = true).action)   // vertical: unchanged
        assertEquals("swipe_left", SwipePlan.mirror("swipe_right")); assertEquals("swipe_up", SwipePlan.mirror("swipe_up"))
    }

    /** Reels, Shorts, TikTok: next/previous is the vertical fling, never a media key (next_item) or a node scroll. */
    @Test fun videoFeedNextPreviousIsAVerticalFlingNeverAMediaKey() {
        for (noun in listOf("", "video", "reel", "short", "tiktok", "one")) {
            assertEquals(noun, "swipe_up", plan(true, noun = noun, kind = "video feed").action)
            assertEquals(noun, "swipe_down", plan(false, noun = noun, kind = "video feed").action)
        }
        // a reel / a short / a tiktok is vertical whatever the screen reads as (TikTok once read as "scrolling list")
        for (kind in listOf(null, "scrolling list", "video player", "other", "photo viewer")) for (noun in SwipeGrammar.VERTICAL) {
            assertEquals("$noun on $kind", "swipe_up", plan(true, noun = noun, kind = kind).action)
            assertEquals("$noun on $kind", "swipe_down", plan(false, noun = noun, kind = kind, rtl = true).action)
            assertFalse(plan(true, noun = noun, kind = kind, button = true).tapButton)
        }
        // the rules' Nav "next" on a video feed: the same fling
        val feed = ScreenContext("video feed", "none", "not scrollable", "hidden")
        assertEquals("swipe_up", RuleDecider.screenTieBreak("next", "next_item", feed))
        assertEquals("swipe_down", RuleDecider.screenTieBreak("the one before", "previous_item", feed))
    }

    @Test fun feedPhrasingsKeepTheirNounAndCount() {
        fun sw(s: String) = SwipeGrammar.parse(PhraseGrammar.normalize(s))
        assertEquals(SpeechCommand.Swipe(null, "next", 1, "reel"), sw("next reel"))
        assertEquals(SpeechCommand.Swipe(null, "next", 1, "short"), sw("next short"))
        assertEquals(SpeechCommand.Swipe(null, "previous", 1, "short"), sw("previous short"))
        assertEquals(SpeechCommand.Swipe(null, "next", 1, "reel"), sw("skip this reel"))
        assertEquals(SpeechCommand.Swipe(null, "next", 3, "reel"), sw("skip three reels"))
        assertEquals(SpeechCommand.Swipe(null, "previous", 2, "video"), sw("go back two videos"))
        assertEquals(SpeechCommand.Nav("the one before"), sw("go back one video"))   // one video: the rules' screen tie-break
        assertEquals(SpeechCommand.Nav("next"), sw("next video"))
    }
}
