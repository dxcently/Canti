package ai.vox.companion

import android.accessibilityservice.AccessibilityService
import android.graphics.Rect
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
     */
    fun appRoot(svc: AccessibilityService): AccessibilityNodeInfo? {
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

    fun keyboardOpen(svc: AccessibilityService): Boolean =
        svc.windows.any { it.type == AccessibilityWindowInfo.TYPE_INPUT_METHOD }

    fun snapshot(root: AccessibilityNodeInfo?): NodeSnap? {
        if (root == null) return null
        var count = 0
        fun read(n: AccessibilityNodeInfo, depth: Int): NodeSnap {
            count++
            val r = Rect().also { n.getBoundsInScreen(it) }
            val actions = n.actionList
            val kids = mutableListOf<NodeSnap>()
            if (depth < MAX_DEPTH) {
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
                children = kids,
            )
        }
        return read(root, 0)
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
