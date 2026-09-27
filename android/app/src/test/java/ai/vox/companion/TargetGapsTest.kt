package ai.vox.companion

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Target-list gaps the emulator harvest found (2026-09-26), rebuilt as synthetic screens in target_gaps.json (shared
 * with `suite/tree_targets.py --selftest`, which must build the same bytes): a floating button half under the
 * navigation bar, a repeated button per row, a row named by its trend icon, a menu drawn over tabs in the same window.
 */
class TargetGapsTest {
    private val fixture = JSONObject(TargetGapsTest::class.java.classLoader!!.getResource("target_gaps.json")!!.readText())
    private val cases = fixture.getJSONArray("cases").let { a -> (0 until a.length()).map { a.getJSONObject(it) } }

    private fun snap(o: JSONObject): NodeSnap {
        val b = o.getJSONArray("b")
        val kids = o.optJSONArray("kids")?.let { a -> (0 until a.length()).map { snap(a.getJSONObject(it)) } } ?: emptyList()
        return NodeSnap(o.getString("cls"), o.optString("id").ifEmpty { null }, o.optString("text").ifEmpty { null },
            o.optString("desc").ifEmpty { null }, b.getInt(0), b.getInt(1), b.getInt(2), b.getInt(3),
            scrollable = o.optBoolean("scroll"), clickable = o.optBoolean("click"), focusable = o.optBoolean("focus"),
            selected = o.optBoolean("selected"), rows = o.optInt("rows", -1), drawingOrder = o.optInt("draw", 0), children = kids)
    }

    private fun strings(a: JSONArray) = (0 until a.length()).map { a.getString(it) }
    private fun covers(c: JSONObject) = c.getJSONArray("covers").let { a ->
        (0 until a.length()).map { a.getJSONArray(it).let { b -> Box(b.getInt(0), b.getInt(1), b.getInt(2), b.getInt(3)) } } }
    private fun build(c: JSONObject, format: String, root: JSONObject = c.getJSONObject("root")) =
        Targets.build(snap(root), c.getInt("w"), c.getInt("h"), covers(c), format)
    private fun case(prefix: String) = cases.single { it.getString("name").startsWith(prefix) }

    @Test fun sharedFixture() {
        for (c in cases) {
            val v1 = build(c, OptionFormat.V1)
            assertEquals(c.getString("name"), strings(c.getJSONArray("options_v1")).joinToString("\n"), Targets.options(v1).joinToString("\n"))
            assertEquals(c.getString("name"), strings(c.getJSONArray("options_v2")).joinToString("\n"),
                Targets.options(build(c, OptionFormat.V2)).joinToString("\n"))
            val bounds = c.getJSONArray("bounds").let { a -> (0 until a.length()).map { i -> a.getJSONArray(i).let { b -> listOf(b.getInt(0), b.getInt(1), b.getInt(2), b.getInt(3)) } } }
            assertEquals(c.getString("name"), bounds, v1.map { listOf(it.left, it.top, it.right, it.bottom) })
        }
    }

    @Test fun aFloatingButtonHalfUnderTheNavigationBarIsTappedOnItsVisiblePart() {
        val ts = build(case("fab half under"), OptionFormat.V1)
        val fab = ts.single { it.label == "Add device" }
        assertTrue("the tap lands above the navigation bar", fab.cy < 2274)
        assertEquals(Box(891, 2211, 1038, 2274), Box(fab.left, fab.top, fab.right, fab.bottom))
        assertTrue("a 24 px sliver is still hidden", ts.none { it.label == "Sliver" })
    }

    @Test fun everyRequestButtonIsListed() {
        assertEquals(3, build(case("a Request button"), OptionFormat.V1).count { it.label == "Request" })
    }

    @Test fun rowsAreNamedByTheirTitleAndVoteButtonsByTheirIcon() {
        val labels = build(case("rows named"), OptionFormat.V1).map { it.label }
        assertTrue(labels.containsAll(listOf("Harbour Jazz FM", "Northern Lights Radio", "Station logo", "Upvote")))
        assertTrue("Popularity increasing" !in labels && "29" !in labels)
    }

    @Test fun anExpandedSheetDrawnOverThePageHidesIt() {
        val c = case("an expanded player sheet")
        val labels = build(c, OptionFormat.V1).map { it.label }
        assertTrue(labels.containsAll(listOf("Share", "Rewind", "Home", "Queue")))
        assertTrue("nothing of the page behind", labels.none { it in setOf("Visit website", "Open podcast", "Pause", "Download", "More options") })
        // Without the drawing order (a Compose tree, an old capture) nothing is known about which is on top: the page leaks.
        val noOrder = JSONObject(c.getJSONObject("root").toString().replace(Regex("\"draw\":\\d+,?"), "").replace(",}", "}"))
        assertTrue("Visit website" in build(c, OptionFormat.V1, noOrder).map { it.label })
        // A clear layer drawn above that holds only a floating button hides nothing.
        assertEquals(9, build(case("a clear layer"), OptionFormat.V1).size)
    }

    @Test fun viewIdsBecomeNamesNeverRawIds() {
        val labels = build(case("an expanded player sheet"), OptionFormat.V1).map { it.label }
        assertTrue(labels.containsAll(listOf("cover image", "position seek bar", "play button")))
        assertTrue(labels.none { it.contains("imgvCover") || it.contains("sbPosition") || it.contains("butPlay") })
        fun name(cls: String, id: String?) = Targets.label(NodeSnap(cls, id, null, null, 0, 0, 10, 10, clickable = true))
        assertEquals("like button", name("android.widget.ImageButton", "com.x:id/like_btn"))
        assertEquals("url bar button", name("androidx.appcompat.widget.AppCompatImageButton", "x:id/URLBarButton"))
        assertEquals("button", name("android.widget.ImageButton", "x:id/fab"))
        assertEquals("the id already names the control", "volume slider", name("android.widget.SeekBar", "x:id/volume_slider"))
        assertEquals("app icon", name("android.widget.ImageView", "x:id/app_icon"))
        assertEquals("unlabeled", name("android.widget.FrameLayout", "x:id/view_3"))
        assertEquals("no id: unlabeled, as before", "unlabeled", name("android.widget.ImageView", null))
    }

    @Test fun aMenuDrawnInTheWindowHidesTheTabUnderIt() {
        val c = case("an overflow menu")
        val open = build(c, OptionFormat.V1).map { it.label }
        assertTrue(open.containsAll(listOf("Settings", "Account", "Ask")))   // Ask: its centre and half of it are clear
        assertTrue("Show" !in open)
        // Menu closed (the node that reaches out of the top bar removed): Show is back.
        val root = JSONObject(c.getJSONObject("root").toString())
        val bar = root.getJSONArray("kids").getJSONObject(0).getJSONArray("kids").getJSONObject(0).getJSONArray("kids")
        bar.remove(bar.length() - 1)
        assertTrue("Show" in build(c, OptionFormat.V1, root).map { it.label })
    }
}
