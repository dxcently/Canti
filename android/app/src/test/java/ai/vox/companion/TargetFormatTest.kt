package ai.vox.companion

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The option format (Targets.kt OPTION FORMAT): row context, ordinal / edge rank, repeated controls kept and told
 * apart. target_format_parity.json is shared with `suite/tree_targets.py --selftest` (the same bytes in Python).
 */
class TargetFormatTest {
    private val fixture = JSONObject(TargetFormatTest::class.java.classLoader!!.getResource("target_format_parity.json")!!.readText())
    private val w = fixture.getInt("w"); private val h = fixture.getInt("h")

    private fun snap(o: JSONObject): NodeSnap {
        val b = o.getJSONArray("b")
        val kids = o.optJSONArray("kids")?.let { a -> (0 until a.length()).map { snap(a.getJSONObject(it)) } } ?: emptyList()
        return NodeSnap(o.getString("cls"), o.optString("id").ifEmpty { null }, o.optString("text").ifEmpty { null },
            o.optString("desc").ifEmpty { null }, b.getInt(0), b.getInt(1), b.getInt(2), b.getInt(3),
            scrollable = o.optBoolean("scroll"), clickable = o.optBoolean("click"), focusable = o.optBoolean("focus"),
            selected = o.optBoolean("selected"), rows = o.optInt("rows", -1), children = kids)
    }

    private val screen by lazy { Targets.build(snap(fixture.getJSONObject("root")), w, h, format = OptionFormat.V2) }
    private val screenV1 by lazy { Targets.build(snap(fixture.getJSONObject("root")), w, h) }
    private fun want(key: String) = fixture.getJSONArray(key).let { a -> (0 until a.length()).map { a.getString(it) } }

    @Test fun parityFixture() {
        assertEquals(want("options").joinToString("\n"), Targets.options(screen).joinToString("\n"))
    }

    /** v1 (the default): the original text; only options that would be identical get "{k} of {n}". */
    @Test fun parityFixtureV1() {
        assertEquals(want("options_v1").joinToString("\n"), Targets.options(screenV1).joinToString("\n"))
        assertEquals(Targets.options(screenV1), Targets.options(Targets.build(snap(fixture.getJSONObject("root")), w, h, format = OptionFormat.V1)))
        assertTrue(screenV1.all { it.context == null && (it.rank == null || Regex("^(\\d+(st|nd|rd|th)|last) of \\d+$").matches(it.rank!!)) })
        val opts = Targets.options(screenV1)
        assertEquals(opts.size, opts.toSet().size)
        // The second "Delete" maps back to the Work row under v1 too.
        val second = screenV1.single { it.option == "Delete (button, right, 2nd of 3)" }
        val tapped = (Targets.resolve(screenV1, ChoiceAnswer(second.option, emptyMap(), 0.9, 1), 0.6) as Targets.Outcome.Tap).target
        assertEquals(1250, tapped.top)
    }

    /** jl10 indent-context parity: indent_parity.json (shared with vox/option_format.py --selftest) — v2i options
     *  byte-for-byte and plain v2 unchanged; the tree parent is always on the target, not only in v2i. */
    @Test fun indentParity() {
        val fx = JSONObject(TargetFormatTest::class.java.classLoader!!.getResource("indent_parity.json")!!.readText())
        val fw = fx.getInt("w"); val fh = fx.getInt("h")
        val root = snap(fx.getJSONObject("root"))
        fun want(key: String) = fx.getJSONArray(key).let { a -> (0 until a.length()).map { a.getString(it) } }
        val v2 = Targets.build(root, fw, fh, format = OptionFormat.V2)
        val v2i = Targets.build(root, fw, fh, format = OptionFormat.V2I)
        val v1 = Targets.build(root, fw, fh)
        assertEquals(want("options_v2").joinToString("\n"), Targets.options(v2).joinToString("\n"))
        assertEquals(want("options").joinToString("\n"), Targets.options(v2i).joinToString("\n"))
        // The tree parent is available on every target (even v1), while only v2i puts it in the model-facing context.
        assertEquals(v2i.map { it.parent }, v1.map { it.parent })
        assertEquals(v2i.map { it.parent }, v2.map { it.parent })
        assertEquals(listOf("L06", "L06", "L06"), v1.filter { it.label in setOf("01 Vocabulary", "02 Grammar", "03 Reading") }.map { it.parent })
        assertEquals(listOf("L07", "L07"), v1.filter { it.label in setOf("04 Listening", "05 Speaking") }.map { it.parent })
        assertTrue("v2 must not carry the tree parent as its context", v2.all { it.context == null || it.parent == null || it.context != it.parent })
    }

    /** The `targets` op's options_v1 / options_v2 (harvest): both fixtures from the same windows, with the parts. */
    @Test fun allFormatsForTheTargetsOp() {
        val all = Targets.allFormats(listOf(snap(fixture.getJSONObject("root")) to emptyList()), w, h)
        assertEquals(setOf("options_v1", "targets_v1", "options_v2", "targets_v2"), all.keys().asSequence().toSet())
        for ((f, key) in listOf(OptionFormat.V1 to "options_v1", OptionFormat.V2 to "options")) {
            val opts = all.getJSONArray("options_$f").let { a -> (0 until a.length()).map { a.getString(it) } }
            assertEquals(want(key), opts)
            val ts = all.getJSONArray("targets_$f")
            assertEquals(opts.size - 1, ts.length())   // NONE_OPTION has no target
            for (i in 0 until ts.length()) assertEquals(opts[i], ts.getJSONObject(i).getString("option"))
        }
        val t = all.getJSONArray("targets_v2").let { a -> (0 until a.length()).map { a.getJSONObject(it) } }
            .first { it.getString("option").startsWith("Delete · Groceries") }
        assertEquals("Delete", t.getString("label")); assertEquals("button", t.getString("role")); assertEquals("right", t.getString("position"))
        assertEquals("Groceries for the week and...", t.getString("context")); assertEquals("2nd of 5 down", t.getString("rank"))
        assertTrue(Regex("^\\d+,\\d+,\\d+,\\d+$").matches(t.getString("bounds")))
        val plain = all.getJSONArray("targets_v1").getJSONObject(0)   // "Navigate up (button, top left)"
        assertEquals("Navigate up", plain.getString("label"))
        assertTrue(!plain.has("context") && !plain.has("rank"))
    }

    @Test fun everyOptionNamesOneTargetAndMapsBackToIt() {
        val opts = Targets.options(screen)
        assertEquals(opts.size, opts.toSet().size)
        // The three "Delete" buttons all survive, and the chosen one is the row that was named.
        val deletes = screen.filter { it.label == "Delete" }
        assertEquals(3, deletes.size)
        val work = deletes.single { it.context == "Work" }
        val a = ChoiceAnswer(work.option, emptyMap(), 0.9, 1)
        val tapped = (Targets.resolve(screen, a, 0.6) as Targets.Outcome.Tap).target
        assertEquals(1250, tapped.top); assertEquals(970, tapped.cx)
        // Identical twins with nothing to tell them apart: reading order.
        val shares = screen.filter { it.label == "Share" }
        assertEquals(listOf("1st of 2", "last of 2"), shares.map { it.rank })
        assertTrue(shares[0].cy < shares[1].cy)
    }

    @Test fun ordinalWords() {
        assertEquals(listOf("1st", "2nd", "3rd", "4th", "10th", "11th", "12th", "13th", "21st", "22nd", "23rd", "101st", "111th", "last"),
            listOf(1, 2, 3, 4, 10, 11, 12, 13, 21, 22, 23, 101, 111).map { Targets.ordinal(it, 200) } + Targets.ordinal(5, 5))
    }

    private fun button(label: String, l: Int, t: Int, r: Int, b: Int) =
        NodeSnap("android.widget.Button", null, label, null, l, t, r, b, clickable = true)
    private fun root(vararg kids: NodeSnap) = NodeSnap("android.widget.FrameLayout", null, null, null, 0, 0, w, h, children = kids.toList())

    @Test fun aLoneTargetHasNoRankAndTheOriginalFormat() {
        val ts = Targets.build(root(button("Search", 400, 100, 600, 200), NodeSnap("android.widget.EditText", null, "Message", null,
            100, 2250, 900, 2350, clickable = true, editable = true)), w, h, format = OptionFormat.V2)
        assertEquals(listOf("Search (button, top)", "Message (text field, bottom)"), ts.map { it.option })
        assertNull(ts[0].rank); assertNull(ts[0].context)
    }

    @Test fun theSameElementTwiceIsOneOption() {
        // Nested wrapper of the same role and label, and the same button seen in two layers: kept once (the first).
        val outer = NodeSnap("android.widget.Button", null, "Send", null, 900, 2200, 1060, 2360, clickable = true,
            children = listOf(button("Send", 910, 2210, 1050, 2350)))
        assertEquals(listOf("Send (button, bottom right)"), Targets.build(root(outer), w, h, format = OptionFormat.V2).map { it.option })
        val layer = root(button("Send", 900, 2200, 1060, 2360))
        assertEquals(1, Targets.build(listOf(layer to emptyList(), layer to emptyList()), w, h).size)
    }

    @Test fun rowContextOnlyForSwitchesGenericAndRepeatedLabels() {
        fun row(y: Int, title: String, vararg ctl: NodeSnap) = NodeSnap("android.view.ViewGroup", null, null, null, 0, y, w, y + 200,
            children = listOf(NodeSnap("android.widget.TextView", null, title, null, 40, y + 50, 600, y + 150)) + ctl)
        val ts = Targets.build(root(
            row(300, "Wi-Fi", NodeSnap("android.widget.Switch", null, null, "Wi-Fi", 880, 350, 1040, 450, clickable = true)),
            row(600, "Downloads", button("Open", 880, 650, 1040, 750)),
            row(900, "Song title", NodeSnap("android.widget.ImageButton", null, null, "play or pause", 880, 950, 1040, 1050, clickable = true)),
            // a text below the control (no vertical overlap) is not its row
            NodeSnap("android.view.ViewGroup", null, null, null, 0, 1500, w, 1900, children = listOf(
                NodeSnap("android.widget.TextView", null, "Caption", null, 40, 1750, 600, 1850),
                NodeSnap("android.widget.ImageButton", null, null, "More", 880, 1520, 1040, 1620, clickable = true))),
        ), w, h, format = OptionFormat.V2)
        val byLabel = ts.associateBy { it.label }
        assertNull("the switch's own label is not its context", byLabel.getValue("Wi-Fi").context)
        assertNull("a plain, unique button gets none", byLabel.getValue("Open").context)
        assertEquals("Song title", byLabel.getValue("play or pause").context)
        assertNull(byLabel.getValue("More").context)
    }
}
