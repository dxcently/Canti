package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Spoken input during a target choice (SpokenPick.kt): number picks, cancel, narrowing, full commands. */
class SpokenPickTest {
    private val W = 1080
    private val H = 2400

    private fun row(text: String, left: Int, top: Int, bottom: Int) =
        NodeSnap("android.view.ViewGroup", null, text, null, left, top, W, bottom, clickable = true)

    /** The three "01 Vocabulary" rows under L05/L06/L07 (each with its parent as context), plus their siblings. */
    private val deck: List<Target> by lazy {
        fun lesson(prefix: String, y: Int) = arrayOf(
            row(prefix, 40, y, y + 90), row("01 Vocabulary", 110, y + 100, y + 190), row("02 Grammar", 110, y + 200, y + 290))
        val rows = ArrayList<NodeSnap>()
        rows += lesson("L05", 300); rows += lesson("L06", 700); rows += lesson("L07", 1100)
        val list = NodeSnap("androidx.recyclerview.widget.RecyclerView", null, null, null, 0, 200, W, 2000, scrollable = true, children = rows)
        Targets.build(NodeSnap("android.widget.FrameLayout", null, null, null, 0, 0, W, H, children = listOf(list)), W, H, format = OptionFormat.V2)
    }

    private val vocab: List<Target> by lazy { deck.filter { it.label == "01 Vocabulary" } }

    private fun any3() = listOf(
        Target("A", "button", "top", 0, 0, 1, 1), Target("B", "button", "top", 0, 0, 1, 1), Target("C", "button", "top", 0, 0, 1, 1))

    // --- number picks --------------------------------------------------------------------------------------------------

    @Test fun numberPicks() {
        for (s in listOf("2", "two", "number 2", "open 2", "tap 2", "click 2", "pick 2", "the second one", "second", "option 3")) {
            val want = if (s.endsWith("3")) 3 else 2
            val r = SpokenPick.parse(s, any3())
            assertTrue("$s -> $r", r is SpokenPick.Result.Tap && r.index == want)
        }
        // out of range: hint, choice stays
        assertTrue(SpokenPick.parse("7", any3()) is SpokenPick.Result.Hint)
        assertTrue(SpokenPick.parse("open 0", any3()) is SpokenPick.Result.Hint)
    }

    @Test fun cancel() {
        for (s in listOf("cancel", "never mind", "nevermind", "forget it")) {
            assertTrue("$s", SpokenPick.parse(s, any3()) is SpokenPick.Result.Cancel)
        }
    }

    // --- narrowing -----------------------------------------------------------------------------------------------------

    @Test fun narrowingToOneTapsIt() {
        val r = SpokenPick.parse("lesson 6", vocab)
        assertTrue(r.toString(), r is SpokenPick.Result.Narrow)
        val n = (r as SpokenPick.Result.Narrow).targets
        assertEquals(1, n.size)
        assertEquals("L06", n[0].parent)
    }

    @Test fun theOneUnderL06NarrowsToItsChild() {
        // "under" is not a covered token; "one" is a number word; disambiguation rests on "06" alone, which still
        // leaves the L06 child clearly ahead (a single-target Narrow, not a confident Tap).
        val r = SpokenPick.parse("the one under L06", vocab)
        assertTrue(r.toString(), r is SpokenPick.Result.Narrow)
        val n = (r as SpokenPick.Result.Narrow).targets
        assertEquals(listOf("L06"), n.map { it.parent })
        assertEquals("01 Vocabulary", n[0].label)
    }

    @Test fun narrowingToSeveralRenumbers() {
        val r = SpokenPick.parse("vocabulary", vocab)
        assertTrue(r.toString(), r is SpokenPick.Result.Narrow)
        val n = (r as SpokenPick.Result.Narrow).targets
        assertEquals(3, n.size)
        assertEquals(setOf("L05", "L06", "L07"), n.map { it.parent }.toSet())
    }

    @Test fun noMatchKeepsChoiceAndFullCommandRunsNormally() {
        assertTrue(SpokenPick.parse("banana", vocab).toString(), SpokenPick.parse("banana", vocab) is SpokenPick.Result.Hint)
        assertTrue(SpokenPick.parse("go home", vocab).toString(), SpokenPick.parse("go home", vocab) is SpokenPick.Result.RunNormally)
        assertTrue(SpokenPick.parse("scroll down", vocab).toString(), SpokenPick.parse("scroll down", vocab) is SpokenPick.Result.RunNormally)
    }

    @Test fun appAndExplicitTapCommandsRunNormally() {
        // A real command that names no candidate cancels the choice and runs, not "no match" (false trigger).
        for (s in listOf("open settings", "open snapchat", "tap the settings button", "home")) {
            assertTrue("$s", SpokenPick.parse(s, vocab) is SpokenPick.Result.RunNormally)
        }
        // A bare word that only names an element in cursor mode is not a command: the choice stays.
        assertTrue(SpokenPick.parse("banana", vocab) is SpokenPick.Result.Hint)
    }
}
