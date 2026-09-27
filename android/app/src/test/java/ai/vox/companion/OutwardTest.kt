package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Outward actions (like, follow, share...) always need a confirm pop, whatever decided them (Outward.kt, Risk). */
class OutwardTest {
    @Test fun everyVocabularyActionIsClassifiedExplicitly() {
        val keys = Vocab.ACTIONS.keys + Vocab.CURSOR_ACTIONS.keys.filterNot { it.startsWith("move_") }
        val missing = keys.filter { it !in Outward.ACTIONS }
        assertTrue("classify these in Outward.ACTIONS: $missing", missing.isEmpty())
    }

    @Test fun outwardActionsAndNewOnesByTheirWords() {
        assertTrue(Outward.isOutward("like")); assertTrue(Outward.isOutward("double_tap"))
        for (a in listOf("follow", "share", "repost", "share_post", "follow_user", "send_message", "post_comment", "retweet"))
            assertTrue(a, Outward.isOutward(a))
        for (a in listOf("swipe_up", "scroll_down", "back", "home", "volume_up", "volume", "next_item", "tap", "open_app", "move_up_fast",
                "zoom_in", "brand_new_thing")) assertFalse(a, Outward.isOutward(a))
    }

    @Test fun outwardButtonsByLabel() {
        for (l in listOf("Like", "Follow", "Share", "Send", "Post", "Repost", "Comment", "Subscribe", "Send message", "Unfollow"))
            assertTrue(l, Outward.isOutwardTarget(l))
        for (l in listOf("Settings", "Search", "Following", "Posts", "Comments", "Likes", "Maybe later", "Home", "Share-able?"))
            assertEquals(l, l == "Share-able?", Outward.isOutwardTarget(l))
    }

    /** Every decision path: an outward action waits for a confirm pop whatever the source or confidence. */
    @Test fun everyPathConfirmsAnOutwardAction() {
        for (a in listOf("like", "double_tap")) {
            val decisions = listOf(
                Decision(a, "rules:phrase", explicit = true), Decision(a, "rules:default", explicit = true),
                Decision(a, "rules:phrase-binding", explicit = true), Decision(a, "grammar:swipe", explicit = true),
                Decision(a, "model", 0.99), Decision(a, "model:local", 1.0), Decision(a, "cloud", 0.0, unscored = true),
                Decision(a, "cloud:gesture:low-confidence", 0.0, unscored = true), Decision(a, "http", 0.97),
            )
            for (d in decisions) {
                assertTrue("$a from ${d.source}", Risk.needsConfirm(d))
                assertEquals("outward action", Risk.why(d))
            }
        }
        // instant actions stay instant from the rules and a scored model; unscored risky ones still ask
        assertFalse(Risk.needsConfirm(Decision("swipe_up", "rules:default", explicit = true)))
        assertFalse(Risk.needsConfirm(Decision("volume_up", "cloud", 0.0, unscored = true)))
        assertEquals("unscored risky action", Risk.why(Decision("tap", "cloud", 0.0, unscored = true)))
    }

    /** The Executor's own last check: a double-tap like cannot be dispatched without a confirm. */
    @Test fun theExecutorRefusesAnUnconfirmedOutwardAction() {
        assertFalse(Outward.mayDispatch("like", confirmed = false)); assertTrue(Outward.mayDispatch("like", confirmed = true))
        assertFalse(Outward.mayDispatch("double_tap", confirmed = false))
        assertTrue(Outward.mayDispatch("swipe_left", confirmed = false))
        assertFalse(Outward.mayTap("Like", confirmed = false)); assertTrue(Outward.mayTap("Like", confirmed = true))
        assertTrue(Outward.mayTap("Settings", confirmed = false))
    }

    /** Outward pops wait `outward_confirm_ms` (default 3000), unscored risky ones `target_choose_ms`; never confirm_timeout_ms. */
    @Test fun outwardConfirmHasItsOwnWindow() {
        assertEquals(3000L, Outward.DEFAULT_CONFIRM_MS)
        assertTrue(Outward.DEFAULT_CONFIRM_MS in Outward.CONFIRM_MS_RANGE)
        val like = Risk.why(Decision("like", "rules:phrase", explicit = true))!!
        assertEquals(3000L, Outward.windowMs(like, outwardMs = 3000, riskyMs = 6000))
        assertEquals(4500L, Outward.windowMs("outward button", outwardMs = 4500, riskyMs = 6000))
        val risky = Risk.why(Decision("tap", "cloud", 0.0, unscored = true))!!
        assertEquals(6000L, Outward.windowMs(risky, outwardMs = 3000, riskyMs = 6000))
    }

    /** A spoken like reaches the like action only through the rules' phrase, which asks. */
    @Test fun aSpokenLikeIsDecidedAsLikeAndAsks() {
        val s = Scene(mode = "listening", app = "x", appName = "x", phrase = PhraseGrammar.LIKE)
        val d = RuleDecider().decide(DecisionInput(s, Profile.empty()))
        assertEquals("like", d.action); assertTrue(Risk.needsConfirm(d))
        assertEquals("Like? pop to confirm", Outward.question("like"))
        assertEquals("Tap Follow? pop to confirm", Outward.question("tap Follow"))
    }
}
