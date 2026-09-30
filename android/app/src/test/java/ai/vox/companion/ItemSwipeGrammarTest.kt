package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** ItemSwipe.kt: the item-swipe grammar (deictic away, label, ordinal row) and what it leaves to a screen swipe. */
class ItemSwipeGrammarTest {
    private fun item(s: String) = ItemSwipeGrammar.parse(PhraseGrammar.normalize(s))

    @Test fun swipeThatAwayIsDeicticAway() {
        assertEquals(SpeechCommand.ItemSwipe(ItemRef.Deictic, "away"), item("swipe that away"))
    }

    @Test fun swipeTheFirstOneLeftIsOrdinal() {
        assertEquals(SpeechCommand.ItemSwipe(ItemRef.Ordinal(1, false), "left"), item("swipe the first one left"))
    }

    @Test fun swipeSecondRowRight() {
        assertEquals(SpeechCommand.ItemSwipe(ItemRef.Ordinal(2, false), "right"), item("swipe second row right"))
    }

    @Test fun swipeLastOneAwayFromEnd() {
        assertEquals(SpeechCommand.ItemSwipe(ItemRef.Ordinal(1, true), "away"), item("swipe last one away"))
    }

    @Test fun swipeLabelAwayIsLabel() {
        assertEquals(SpeechCommand.ItemSwipe(ItemRef.Label("mail 3"), "away"), item("swipe mail 3 away"))
    }

    @Test fun plainSwipeLeftIsNotItemSwipe() {
        assertNull(item("swipe left"))
    }

    @Test fun swipeLeftThreeTimesIsNotItemSwipe() {
        assertNull(item("swipe left three times"))
    }
}
