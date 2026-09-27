package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The target list shows only what can be seen and tapped (Targets.kt Occlusion): nothing under the keyboard, the
 * system bars, an open drawer, a bottom sheet or a scrim, and a floating action button is never the one cut.
 */
class TargetOcclusionTest {
    private val w = 1080; private val h = 2400

    private fun node(cls: String, l: Int, t: Int, r: Int, b: Int, vararg kids: NodeSnap, text: String? = null, desc: String? = null,
                     id: String? = null, click: Boolean = false, visible: Boolean = true) =
        NodeSnap(if ('.' in cls) cls else "android.widget.$cls", id, text, desc, l, t, r, b, clickable = click, visible = visible,
            children = kids.toList())

    private fun button(label: String, l: Int, t: Int, r: Int, b: Int) = node("Button", l, t, r, b, text = label, click = true)
    private fun labels(ts: List<Target>) = ts.map { it.label }.toSet()

    @Test fun rectangleSubtraction() {
        val r = Box(0, 0, 100, 100)
        assertEquals(10000L, Occlusion.uncovered(r, emptyList()).sumOf { it.area })
        assertEquals(6000L, Occlusion.uncovered(r, listOf(Box(0, 60, 100, 200))).sumOf { it.area })
        assertEquals(9600L, Occlusion.uncovered(r, listOf(Box(40, 40, 60, 60))).sumOf { it.area })
        assertEquals(0L, Occlusion.uncovered(r, listOf(Box(0, 0, 50, 100), Box(50, 0, 100, 100))).sumOf { it.area })
        val screen = Box(0, 0, w, h)
        // The centre covered: the largest visible piece is where the tap goes, if it is not a sliver.
        assertEquals(Box(0, 0, 100, 40), Occlusion.visiblePart(Box(0, 0, 100, 100), listOf(Box(40, 40, 60, 60)), screen))
        assertTrue("centre covered, 30 px left", Occlusion.hidden(Box(0, 0, 100, 100), listOf(Box(0, 30, 100, 100)), screen))
        assertEquals("centre free: its own box", Box(0, 0, 100, 100), Occlusion.visiblePart(Box(0, 0, 100, 100), listOf(Box(0, 0, 100, 30)), screen))
        assertFalse(Occlusion.hidden(Box(0, 0, 100, 100), listOf(Box(0, 0, 100, 30)), screen))
        assertTrue("off screen", Occlusion.hidden(Box(-200, 0, -100, 100), emptyList(), screen))
    }

    @Test fun nothingUnderTheKeyboardOrTheSystemBars() {
        val root = node("FrameLayout", 0, 0, w, h,
            button("Search", 0, 200, 540, 330),
            button("Send", 800, 1900, 1060, 2020),        // under the keyboard
            button("Attach", 0, 1300, 300, 1420),         // above it
            button("Profile", 0, -60, 150, 90),           // a sliver under the status bar (84 px)
            button("Home tab", 0, 2280, 270, 2400),       // under the navigation bar
        )
        val bars = listOf(Box(0, 0, w, 84), Box(0, 2274, w, h))
        val keyboard = Box(0, 1500, w, 2274)
        assertEquals(setOf("Search", "Send", "Attach", "Profile", "Home tab"), labels(Targets.build(root, w, h)))
        assertEquals(setOf("Search", "Attach"), labels(Targets.build(root, w, h, bars + keyboard)))
    }

    @Test fun anOpenDrawerHidesTheContentBehindIt() {
        val content = node("FrameLayout", 0, 0, w, h, button("Compose", 850, 2100, 1040, 2260), button("Menu", 0, 100, 150, 250),
            button("Search", 900, 100, 1060, 250))
        val drawer = node("android.widget.LinearLayout", 0, 0, 800, h, button("Inbox", 0, 300, 800, 420), button("Settings", 0, 450, 800, 570))
        val open = node("androidx.drawerlayout.widget.DrawerLayout", 0, 0, w, h, content, drawer)
        assertEquals("the drawer's scrim covers the rest too", setOf("Inbox", "Settings"), labels(Targets.build(open, w, h)))
        val closed = node("androidx.drawerlayout.widget.DrawerLayout", 0, 0, w, h, content,
            node("android.widget.LinearLayout", -800, 0, 0, h, visible = false))
        assertEquals(setOf("Compose", "Menu", "Search"), labels(Targets.build(closed, w, h)))
    }

    @Test fun aBottomSheetHidesWhatIsUnderIt() {
        val root = node("androidx.coordinatorlayout.widget.CoordinatorLayout", 0, 0, w, h,
            button("Top", 0, 200, 540, 330),
            button("Buried", 0, 1800, 540, 1930),
            node("FrameLayout", 0, 1400, w, h, button("Share", 0, 1500, w, 1620), button("Copy link", 0, 1650, w, 1770),
                id = "com.app:id/design_bottom_sheet"),
        )
        assertEquals(setOf("Top", "Share", "Copy link"), labels(Targets.build(root, w, h)))
    }

    /**
     * A social feed (synthetic, modelled on a real capture's structure only) keeps an empty, childless container whose id
     * says bottom_sheet, spanning the whole feed and late in the tree. It shows nothing, so it hides nothing. The same
     * container with one blank placeholder child still hides nothing; with a labelled button in it, it is a real sheet.
     */
    @Test fun anEmptyBottomSheetContainerHidesNothing() {
        fun feed(vararg sheetKids: NodeSnap) = node("FrameLayout", 0, 0, w, h,
            node("androidx.recyclerview.widget.RecyclerView", 0, 94, w, 2200,
                button("Like", 0, 900, 150, 1020), button("Comment", 150, 900, 300, 1020), button("Share", 300, 900, 450, 1020),
                node("ImageView", 0, 200, w, 880, desc = "Photo by someone", click = true)),
            node("LinearLayout", 0, 2200, w, h, button("Home", 0, 2200, 216, h), button("Search", 216, 2200, 432, h),
                button("Profile", 864, 2200, w, h)),
            node("FrameLayout", 0, 94, w, h, *sheetKids, id = "com.example.feed:id/bottom_sheet_container"),
        )
        val all = setOf("Like", "Comment", "Share", "Photo by someone", "Home", "Search", "Profile")
        assertEquals(all, labels(Targets.build(feed(), w, h)))
        assertEquals("one blank placeholder is still nothing to see", all,
            labels(Targets.build(feed(node("FrameLayout", 0, 94, w, h)), w, h)))
        assertEquals("a sheet with content hides what is under it", setOf("Close"),
            labels(Targets.build(feed(node("FrameLayout", 0, 94, w, h, button("Close", 0, 100, 200, 220))), w, h)))
        assertFalse(Occlusion.showsContent(node("FrameLayout", 0, 94, w, 2300)))
        assertFalse("children without an area", Occlusion.showsContent(node("FrameLayout", 0, 94, w, 2300, node("View", 0, 0, 0, 0), node("View", 5, 5, 5, 5))))
        assertTrue("two plain parts (a custom-drawn sheet)", Occlusion.showsContent(node("FrameLayout", 0, 94, w, 2300,
            node("View", 0, 94, w, 400), node("View", 0, 400, w, 900))))
    }

    /** A search or selection mode draws its bar over the toolbar: the toolbar's buttons under it are not options. */
    @Test fun aSearchModeBarHidesTheToolbarUnderIt() {
        val toolbar = node("android.view.ViewGroup", 0, 128, w, 296, node("TextView", 42, 169, 216, 254, text = "Saved"),
            button("Filter", 699, 148, 826, 274), button("Collections", 826, 148, 953, 274), button("More options", 953, 148, w, 274))
        val list = node("FrameLayout", 0, 296, w, h, button("First article", 0, 300, w, 500))
        fun screen(vararg bar: NodeSnap) = node("FrameLayout", 0, 0, w, h, node("FrameLayout", 0, 0, w, h, toolbar, list), *bar)
        assertEquals(setOf("Filter", "Collections", "More options", "First article"), labels(Targets.build(screen(), w, h)))
        val search = node("android.view.ViewGroup", 0, 0, w, 296,
            node("ImageView", 0, 149, 147, 275, desc = "Done", click = true),
            NodeSnap("android.widget.AutoCompleteTextView", "com.example:id/search_src_text", "Search saved articles", null,
                189, 163, 1059, 258, clickable = true, editable = true),
            id = "com.example:id/action_mode_bar")
        assertEquals(setOf("Done", "Search saved articles", "First article"), labels(Targets.build(screen(search), w, h)))
        // A selection toolbar laid over the normal one (same bounds, later in the tree).
        val selection = node("android.view.ViewGroup", 0, 128, w, 296, node("ImageButton", 21, 138, 168, 285, desc = "Clear selection", click = true),
            button("Delete", 822, 148, 949, 274), id = "com.example:id/overlayToolbar")
        assertEquals(setOf("Clear selection", "Delete", "First article"), labels(Targets.build(screen(selection), w, h)))
        assertEquals("an empty bar hides nothing", setOf("Filter", "Collections", "More options", "First article"),
            labels(Targets.build(screen(node("android.view.ViewGroup", 0, 0, w, 296, id = "com.example:id/action_mode_bar")), w, h)))
    }

    @Test fun aSnackbarHidesTheButtonUnderIt() {
        val snack = node("FrameLayout", 21, 2049, 1059, 2253, node("LinearLayout", 42, 2049, 1038, 2253,
            node("TextView", 63, 2049, 845, 2253, text = "Nothing nearby", id = "com.example:id/snackbar_text"),
            node("Button", 866, 2088, 1038, 2214, text = "Close", click = true, id = "com.example:id/snackbar_action")))
        val root = node("FrameLayout", 0, 0, w, h, button("Search places", 147, 139, 933, 265),
            node("Button", 891, 2085, 1038, 2232, desc = "My location", click = true), snack)
        assertEquals(setOf("Search places", "Close"), labels(Targets.build(root, w, h)))
    }

    /**
     * The accessibility order sorts siblings by position, not by drawing order, so a later tappable node alone does not
     * hide what it overlaps: an expanded video player listed before the toolbar and page it covers keeps its buttons.
     */
    @Test fun aLaterTappableNodeAloneHidesNothing() {
        val player = node("FrameLayout", 0, 128, w, 735, node("ImageView", 21, 150, 147, 276, desc = "Close player", click = true),
            desc = "Show player controls", click = true)
        val toolbar = node("android.view.ViewGroup", 0, 128, w, 296, button("Search", 848, 148, 975, 274))
        val page = node("FrameLayout", 0, 296, w, 2105, node("android.view.ViewGroup", 0, 422, w, 936, desc = "A video", click = true))
        val got = labels(Targets.build(node("FrameLayout", 0, 0, w, h, player, toolbar, page), w, h))
        assertTrue("Close player" in got && "Show player controls" in got)
    }

    @Test fun aComposeScrimHidesTheContent() {
        val root = node("android.view.View", 0, 0, w, h,
            node("android.view.View", 0, 0, w, h, button("Like", 100, 1000, 300, 1100), button("Reply", 400, 1000, 600, 1100)),
            node("android.view.View", 0, 0, w, h, desc = "Close navigation menu", click = true),
            node("android.view.View", 0, 0, 800, h, button("Profile", 0, 300, 800, 420)),
        )
        val got = labels(Targets.build(root, w, h))
        assertTrue("Profile" in got && "Close navigation menu" in got)
        assertFalse("Like" in got || "Reply" in got)
    }

    @Test fun aFloatingActionButtonIsNeverTheOneCut() {
        val rows = (0 until 45).map { i -> node("android.view.ViewGroup", 0, 100 + i * 50, w, 145 + i * 50, text = "Post $i", click = true) }
        val list = NodeSnap("androidx.recyclerview.widget.RecyclerView", null, null, null, 0, 100, w, h, scrollable = true, rows = 45,
            children = rows)
        val fab = node("ImageButton", 900, 2200, 1040, 2340, desc = "New post", click = true)
        val got = Targets.build(node("FrameLayout", 0, 0, w, h, list, fab), w, h)
        assertEquals(Targets.MAX_OPTIONS - 1, got.size)
        assertTrue("New post (button, bottom right)" in got.map { it.option })
        assertEquals("still in reading order", got.sortedWith(compareBy({ Targets.bucket(it.cx, it.cy, w, h) / 3 },
            { Targets.bucket(it.cx, it.cy, w, h) % 3 }, { it.top }, { it.left })), got)
        // Plain images go before buttons.
        val photos = (0 until 45).map { i -> node("ImageView", 0, 100 + i * 50, w, 145 + i * 50, desc = "Photo $i", click = true) }
        val got2 = Targets.build(node("FrameLayout", 0, 0, w, h, *photos.toTypedArray(), button("Next", 0, 2300, 300, 2390)), w, h)
        assertEquals(Targets.MAX_OPTIONS - 1, got2.size)
        assertTrue("Next" in labels(got2))
    }

    @Test fun aFloatingButtonInItsOwnWindowIsCollected() {
        val main = node("FrameLayout", 0, 0, w, h, button("Feed item", 0, 2000, w, 2300))
        val fabLayer = node("FrameLayout", 880, 2180, 1060, 2360, node("ImageButton", 900, 2200, 1040, 2340, desc = "Compose", click = true))
        val fabWindow = Box(880, 2180, 1060, 2360)
        val got = labels(Targets.build(listOf(main to listOf(fabWindow), fabLayer to emptyList()), w, h))
        assertEquals(setOf("Feed item", "Compose"), got)
    }

    /**
     * Compose's AndroidView holder (ViewFactoryHolder) is reported not visible to the user while the views inside it
     * are (Tasks.org v15.12, emulator raw dump): the reader must read through it, and the target list must find the
     * buttons under it. Off-screen subtrees (empty, clipped bounds) are still pruned.
     */
    @Test fun composeInteropHolderIsReadThrough() {
        assertTrue("invisible holder with real bounds", TreeReader.descends(false, 0, 0, w, h))
        assertTrue(TreeReader.descends(true, 0, 0, 0, 0))
        assertFalse("off-screen page / closed drawer: clipped to empty", TreeReader.descends(false, 0, 0, 0, 0))
        assertFalse(TreeReader.descends(false, 1080, 500, 1080, 900))
        val bar = node("ViewGroup", 0, 2064, 1080, 2274,
            node("ImageButton", 11, 2064, 158, 2274, click = true, desc = "Open menu"),
            node("androidx.appcompat.widget.LinearLayoutCompat", 158, 2064, 517, 2274,
                node("Button", 158, 2106, 285, 2232, desc = "Search", click = true),
                node("Button", 285, 2106, 412, 2232, desc = "Sort", click = true)))
        val fab = node("ImageButton", 892, 2096, 1039, 2243, desc = "Create new task", click = true)
        val holder = node("androidx.compose.ui.viewinterop.ViewFactoryHolder", 0, 0, w, h,
            node("FrameLayout", 0, 0, w, h, node("ScrollView", 0, 0, w, h, bar, fab)), visible = false)
        val root = node("androidx.compose.ui.platform.ComposeView", 0, 0, w, h, node("android.view.View", 0, 0, w, h, holder))
        assertEquals(setOf("Open menu", "Search", "Sort", "Create new task"), labels(Targets.build(root, w, h)))
        // A focusable, unlabelled wrapper around the holder is a container, not a target of its own.
        val inner = node("androidx.compose.ui.viewinterop.ViewFactoryHolder", 0, 2064, 1080, 2274,
            node("Button", 400, 2100, 700, 2240, text = "Go", click = true), visible = false)
        val wrapper = NodeSnap("android.view.View", null, null, null, 0, 2064, 1080, 2274, focusable = true, children = listOf(inner))
        assertEquals(setOf("Go"), labels(Targets.build(node("FrameLayout", 0, 0, w, h, wrapper), w, h)))
    }
}
