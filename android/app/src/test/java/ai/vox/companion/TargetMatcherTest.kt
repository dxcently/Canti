package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Task E11 spoken target picking: number equivalence, letter-prefix abbreviation and tree context in [TargetMatcher]
 * and [Targets], with the synthetic AnkiDroid deck tree (L05/L06/L07, each with "01 Vocabulary" / "02 Grammar").
 */
class TargetMatcherTest {
    private val W = 1080
    private val H = 2400

    private fun t(label: String, role: String = "button", pos: String = "top", context: String? = null) =
        Target(label, role, pos, 0, 0, 10, 10, context = context)

    private fun tap(q: String, targets: List<Target>): Target? =
        (TargetMatcher.match(targets, q) as? Targets.Outcome.Tap)?.target

    // --- A1: number equivalence ----------------------------------------------------------------------------------------

    @Test fun numbersAreEquivalent() {
        assertEquals("5", tap("five", listOf(t("5")))?.label)
        assertEquals("01 Vocabulary", tap("1", listOf(t("01 Vocabulary", role = "list item")))?.label)
        assertEquals("01 Vocabulary", tap("one", listOf(t("01 Vocabulary", role = "list item")))?.label)
        assertEquals("01 Vocabulary", tap("first", listOf(t("01 Vocabulary", role = "list item")))?.label)
        assertEquals("06", tap("six", listOf(t("06")))?.label)
        assertEquals("20", tap("twenty", listOf(t("20")))?.label)
        // leading zeros on the label are ignored against the query's bare digit
        assertEquals("L06", tap("l 6", listOf(t("L06", role = "list item")))?.label)
    }

    // --- A2: letter-prefix abbreviation --------------------------------------------------------------------------------

    @Test fun letterPrefixAbbreviation() {
        assertEquals("L06", tap("lesson 6", listOf(t("L06", role = "list item")))?.label)
        assertEquals("L6", tap("lesson 6", listOf(t("L6", role = "list item")))?.label)
        assertEquals("L-6", tap("lesson 6", listOf(t("L-6", role = "list item")))?.label)
        assertEquals("Ch3", tap("chapter 3", listOf(t("Ch3")))?.label)
        assertEquals("C3", tap("chapter 3", listOf(t("C3")))?.label)
        assertEquals("U2", tap("unit 2", listOf(t("U2")))?.label)
        assertEquals("L06", tap("l06", listOf(t("L06", role = "list item")))?.label)
    }

    // --- A3 + A4: tree context on the synthetic deck tree --------------------------------------------------------------

    private fun row(text: String, left: Int, top: Int, bottom: Int) =
        NodeSnap("android.view.ViewGroup", null, text, null, left, top, W, bottom, clickable = true)

    private fun deckTree(): NodeSnap {
        fun lesson(prefix: String, y: Int) = arrayOf(
            row(prefix, 40, y, y + 90),
            row("01 Vocabulary", 110, y + 100, y + 190),
            row("02 Grammar", 110, y + 200, y + 290),
        )
        val rows = ArrayList<NodeSnap>()
        rows += lesson("L05", 300)
        rows += lesson("L06", 700)
        rows += lesson("L07", 1100)
        val list = NodeSnap("androidx.recyclerview.widget.RecyclerView", null, null, null, 0, 200, W, 2000,
            scrollable = true, children = rows)
        return NodeSnap("android.widget.FrameLayout", null, null, null, 0, 0, W, H, children = listOf(list))
    }

    private val deck = Targets.build(deckTree(), W, H, format = OptionFormat.V2)

    private fun tapInDeck(q: String) = tap(q, deck)

    @Test fun treeContextNamesEachChildByItsParent() {
        val byParent = deck.filter { it.label == "01 Vocabulary" }.map { it.parent }
        assertEquals(listOf("L05", "L06", "L07"), byParent)
        // top-level rows have no parent of their own
        assertTrue(deck.filter { it.label == "L05" || it.label == "L06" || it.label == "L07" }.all { it.parent == null })
    }

    @Test fun allFourUtterancesTapTheL06Child() {
        for (q in listOf("lesson 6 vocabulary 1", "lesson 6 vocabulary one", "l6 vocabulary 1", "l06 01 vocabulary")) {
            val t = tapInDeck(q)
            assertEquals("$q -> ${t?.option}", "01 Vocabulary", t?.label)
            assertEquals("$q -> ${t?.option}", "L06", t?.parent)
        }
    }

    @Test fun openL06TapsL06AndOpenVocabularyChoosesAmongThree() {
        val l = tapInDeck("l06")
        assertEquals("L06", l?.label)
        assertNull(l?.parent)
        val c = TargetMatcher.match(deck, "vocabulary")
        assertTrue(c.toString(), c is Targets.Outcome.Choose)
        val chosen = (c as Targets.Outcome.Choose).targets
        assertEquals(3, chosen.size)
        assertEquals(setOf("L05", "L06", "L07"), chosen.map { it.parent }.toSet())
    }

    // --- flat screens are unchanged ------------------------------------------------------------------------------------

    @Test fun flatListGetsNoTreeContext() {
        val list = NodeSnap("androidx.recyclerview.widget.RecyclerView", null, null, null, 0, 300, W, 900,
            scrollable = true, children = listOf(row("A", 40, 300, 400), row("B", 40, 410, 510), row("C", 40, 520, 620)))
        val ts = Targets.build(NodeSnap("android.widget.FrameLayout", null, null, null, 0, 0, W, H, children = listOf(list)),
            W, H, format = OptionFormat.V2)
        assertTrue(ts.all { it.parent == null })
    }
}
