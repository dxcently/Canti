package ai.vox.companion

import android.accessibilityservice.AccessibilityService
import android.graphics.Rect
import android.os.Build
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityNodeInfo.AccessibilityAction
import android.view.accessibility.AccessibilityWindowInfo

/** Reads the accessibility tree into [NodeSnap]s (bounded, so a huge tree cannot stall the service). */
object TreeReader {
    private const val MAX_NODES = 1500
    private const val MAX_DEPTH = 40

    /**
     * Root of the active application window. VOX's own app windows (the Flutter screens) count like any app's; VOX's
     * accessibility overlays (badge, cursor, highlights), its other non-app windows, and the IME never do.
     * Checked live ([RootCheck]): a cached root of a window that is gone, or of an app that is not in front, is
     * re-read once (the cache cleared, API 34+), else null (`stale_root`): never the wrong app's screen.
     */
    fun appRoot(svc: AccessibilityService): AccessibilityNodeInfo? {
        val first = pick(svc) ?: return null
        val why = stale(svc, first) ?: return first.also(::learn)
        if (Build.VERSION.SDK_INT >= 34) try { svc.clearCache() } catch (_: Exception) {}
        val second = pick(svc)
        val why2 = if (second == null) "no root on re-read" else stale(svc, second)
        EventLog.ev("stale_root", "package" to first.packageName?.toString(), "why" to why, "retry" to (why2 ?: "ok"),
            "result" to if (why2 == null) "re-read" else "refused")
        return if (why2 == null) second?.also(::learn) else null
    }

    /** Each window's package, learned from every checked root ([ForegroundApp]: the app in front without a tree read). */
    val windowPackages = WindowPackages()
    private fun learn(root: AccessibilityNodeInfo) = windowPackages.learn(root.windowId, root.packageName?.toString())

    /**
     * The package [appRoot] would return, from the window list and [windowPackages] ([ForegroundApp.resolve]); a window
     * not learned yet is read once. Null: no app window.
     */
    fun appPackage(svc: AccessibilityService): String? {
        val ws = try { svc.windows } catch (_: Exception) { emptyList<AccessibilityWindowInfo>() }
        windowPackages.retain(ws.map { it.id })
        val wins = ws.map {
            ForegroundApp.Win(it.id, when (it.type) {
                AccessibilityWindowInfo.TYPE_APPLICATION -> ForegroundApp.Type.APPLICATION
                AccessibilityWindowInfo.TYPE_SYSTEM -> ForegroundApp.Type.SYSTEM
                else -> ForegroundApp.Type.OTHER
            }, it.isActive)
        }
        return when (val r = ForegroundApp.resolve(wins, windowPackages::get, svc.packageName)) {
            is ForegroundApp.Result.Known -> r.pkg
            ForegroundApp.Result.None -> null
            ForegroundApp.Result.Read -> appRoot(svc)?.packageName?.toString()
        }
    }

    private fun pick(svc: AccessibilityService): AccessibilityNodeInfo? {
        val own = svc.packageName
        val windows = try { svc.windows } catch (_: Exception) { emptyList<AccessibilityWindowInfo>() }
        val active = svc.rootInActiveWindow
        if (active != null) {
            if (active.packageName?.toString() != own) return active
            if (windows.any { it.isActive && it.type == AccessibilityWindowInfo.TYPE_APPLICATION }) return active
        }
        return windows.firstNotNullOfOrNull { w ->
            when (w.type) {
                AccessibilityWindowInfo.TYPE_APPLICATION -> w.root
                AccessibilityWindowInfo.TYPE_SYSTEM -> w.root?.takeIf { it.packageName?.toString() != own }
                else -> null
            }
        }
    }

    /** When each window's root was last re-read past the cache (window id -> uptime ms). */
    private val verified = HashMap<Int, Long>()

    /**
     * Why [root] is not the live foreground screen ([RootCheck]), or null. The window list check is cheap and runs every
     * time; `refresh()` re-reads the root past the cache, a synchronous call into the app's UI thread (slow while a
     * busy app such as Instagram's feed is drawing), so it runs at most once per [RootCheck.REFRESH_MS] per window.
     */
    private fun stale(svc: AccessibilityService, root: AccessibilityNodeInfo): String? {
        val now = android.os.SystemClock.uptimeMillis()
        val wid = root.windowId
        val due = synchronized(verified) { RootCheck.refreshDue(verified[wid], now) }
        val alive = if (!due) true else MainLoad.time("tree:refresh") { try { root.refresh() } catch (_: Exception) { false } }
            .also { ok -> synchronized(verified) { if (ok) { if (verified.size > 32) verified.clear(); verified[wid] = now } else verified.remove(wid) } }
        val ws = try { svc.windows } catch (_: Exception) { emptyList<AccessibilityWindowInfo>() }
        return RootCheck.why(root.windowId, alive, ws.map {
            RootCheck.Win(it.id, it.type == AccessibilityWindowInfo.TYPE_APPLICATION, it.isActive, it.layer)
        })
    }

    /**
     * For the target list: the app window's tree plus the same app's other windows above it (popup menus, a floating
     * button layer), each with the screen bounds of every window above it (keyboard, status and navigation bars,
     * dialogs, other apps' popups). Canti's own accessibility overlays are not covers: the head lets taps through.
     */
    fun targetLayers(svc: AccessibilityService): List<Pair<NodeSnap, List<Box>>> {
        val root = appRoot(svc) ?: return emptyList()
        val windows = try { svc.windows } catch (_: Exception) { emptyList<AccessibilityWindowInfo>() }
        val appWin = root.window ?: return listOfNotNull(snapshot(root)?.let { it to emptyList() })
        val r = Rect()
        fun coversAbove(layer: Int) = windows.filter { it.layer > layer && it.type != AccessibilityWindowInfo.TYPE_ACCESSIBILITY_OVERLAY }
            .map { w -> w.getBoundsInScreen(r); Box(r.left, r.top, r.right, r.bottom) }
        val pkg = root.packageName?.toString()
        val extra = windows.filter { it.type == AccessibilityWindowInfo.TYPE_APPLICATION && it.layer > appWin.layer && it.id != appWin.id }
            .mapNotNull { w -> w.root?.takeIf { it.packageName?.toString() == pkg }?.let { wr -> snapshot(wr)?.let { it to coversAbove(w.layer) } } }
        return listOfNotNull(snapshot(root)?.let { it to coversAbove(appWin.layer) }) + extra
    }

    fun keyboardOpen(svc: AccessibilityService): Boolean =
        svc.windows.any { it.type == AccessibilityWindowInfo.TYPE_INPUT_METHOD }

    /**
     * Whether [snapshot] reads a node's children. Only a node that is invisible AND has empty bounds is pruned: an
     * off-screen page or a closed drawer (their bounds are clipped to the parent, so empty). An invisible node with
     * real bounds is read: Compose reports its `AndroidView` interop holder (ViewFactoryHolder) as not visible to the
     * user while every view inside it is visible, so pruning on visibility alone lost whole screens (Tasks.org: the
     * dump was 9 empty containers). Pure (TargetTest).
     */
    fun descends(visible: Boolean, left: Int, top: Int, right: Int, bottom: Int): Boolean =
        visible || (right > left && bottom > top)

    fun snapshot(root: AccessibilityNodeInfo?): NodeSnap? {
        if (root == null) return null
        var count = 0
        fun read(n: AccessibilityNodeInfo, depth: Int): NodeSnap {
            count++
            val r = Rect().also { n.getBoundsInScreen(it) }
            val actions = n.actionList
            val kids = mutableListOf<NodeSnap>()
            // An off-screen subtree (an off-screen pager page, a closed drawer) is skipped, so the node budget reaches
            // what is drawn last: floating buttons and sheets usually come at the end of the tree. See [descends].
            if (depth < MAX_DEPTH && descends(n.isVisibleToUser, r.left, r.top, r.right, r.bottom)) {
                for (i in 0 until n.childCount) {
                    if (count >= MAX_NODES) break
                    val c = n.getChild(i) ?: continue
                    kids += read(c, depth + 1)
                }
            }
            val ci = n.collectionInfo
            return NodeSnap(
                cls = n.className?.toString() ?: "",
                id = n.viewIdResourceName,
                text = n.text?.toString(),
                desc = n.contentDescription?.toString(),
                left = r.left, top = r.top, right = r.right, bottom = r.bottom,
                scrollable = n.isScrollable,
                canScrollForward = actions.contains(AccessibilityAction.ACTION_SCROLL_FORWARD) ||
                    actions.contains(AccessibilityAction.ACTION_SCROLL_DOWN),
                canScrollBackward = actions.contains(AccessibilityAction.ACTION_SCROLL_BACKWARD) ||
                    actions.contains(AccessibilityAction.ACTION_SCROLL_UP),
                editable = n.isEditable,
                focused = n.isFocused,
                clickable = n.isClickable,
                visible = n.isVisibleToUser,
                focusable = n.isFocusable,
                selected = n.isSelected,
                collectionItem = n.collectionItemInfo != null,
                rows = ci?.rowCount ?: -1,
                cols = ci?.columnCount ?: -1,
                drawingOrder = n.drawingOrder,
                children = kids,
            )
        }
        return read(root, 0)
    }

    /**
     * Every node as the framework reports it (debug op `dump` with `raw: true`): no visibility filter, no pruning,
     * pre-order with depth and the raw child count. For diagnosing trees the snapshot reads oddly (Compose).
     */
    fun rawDump(root: AccessibilityNodeInfo?, max: Int = 800): org.json.JSONArray {
        val out = org.json.JSONArray()
        val r = Rect()
        fun walk(n: AccessibilityNodeInfo, depth: Int) {
            if (out.length() >= max || depth > MAX_DEPTH) return
            n.getBoundsInScreen(r)
            out.put(org.json.JSONObject().put("d", depth).put("cls", n.className?.toString() ?: "")
                .put("id", n.viewIdResourceName ?: "").put("text", n.text?.toString() ?: "").put("desc", n.contentDescription?.toString() ?: "")
                .put("vis", n.isVisibleToUser).put("imp", n.isImportantForAccessibility).put("click", n.isClickable)
                .put("kids", n.childCount).put("bounds", "${r.left},${r.top},${r.right},${r.bottom}")
                // the rest of what snapshot() reads into NodeSnap, so offline tools see the fields Targets.build uses
                .put("focusable", n.isFocusable).put("editable", n.isEditable).put("scrollable", n.isScrollable)
                .put("focused", n.isFocused).put("selected", n.isSelected).put("collection_item", n.collectionItemInfo != null)
                .put("rows", n.collectionInfo?.rowCount ?: -1).put("cols", n.collectionInfo?.columnCount ?: -1)
                .put("draw", n.drawingOrder))
            for (i in 0 until n.childCount) n.getChild(i)?.let { walk(it, depth + 1) }
        }
        if (root != null) walk(root, 0)
        return out
    }

    /**
     * Cheap fingerprint of what is visible: used by the confirmer to tell a real change from a no-op.
     * Includes texts, descriptions, bounds and checked/selected state of visible nodes.
     */
    fun fingerprint(root: AccessibilityNodeInfo?): Int {
        if (root == null) return 0
        var h = 17
        var count = 0
        val r = Rect()
        fun walk(n: AccessibilityNodeInfo, depth: Int) {
            if (count++ > MAX_NODES || depth > MAX_DEPTH) return
            if (n.isVisibleToUser) {
                n.getBoundsInScreen(r)
                h = 31 * h + (n.className?.hashCode() ?: 0)
                h = 31 * h + (n.text?.toString()?.hashCode() ?: 0)
                h = 31 * h + (n.contentDescription?.toString()?.hashCode() ?: 0)
                h = 31 * h + r.hashCode()
                h = 31 * h + (if (n.isChecked) 1 else 0) + (if (n.isSelected) 2 else 0)
            }
            for (i in 0 until n.childCount) n.getChild(i)?.let { walk(it, depth + 1) }
        }
        walk(root, 0)
        return h
    }
}
