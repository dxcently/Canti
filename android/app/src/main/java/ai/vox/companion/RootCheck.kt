package ai.vox.companion

/**
 * Is the app root Canti is about to read the live foreground screen? (pure; RootCheckTest)
 *
 * On the Z Flip one `dump raw=true` taken with Instagram in front returned a byte-identical copy of the TikTok tree
 * from six minutes before; a retry was right. The service reads the tree through Android's per-service accessibility
 * cache (rootInActiveWindow, window roots, children), so a root can be a cached node of a window that is gone, or the
 * active-window tracking can lag behind the app on top. Acting on it would decide, classify or tap on the wrong app's
 * screen. [TreeReader.appRoot] checks each root with [why]: null = use it; else it clears the cache (API 34+), reads
 * once more, and if that fails too returns no root (logged `stale_root`): no screen facts, no targets, nothing tapped.
 */
object RootCheck {
    /** One accessibility window: id, TYPE_APPLICATION or not, active (focused or last touched), layer (higher = front). */
    data class Win(val id: Int, val app: Boolean, val active: Boolean, val layer: Int)

    /**
     * `refresh()` (a synchronous call into the app's UI thread) at most this often per window: a root cached for
     * minutes is still caught within a second, and a busy app is not called on every read. The window list check runs
     * on every read.
     */
    const val REFRESH_MS = 1000L

    /** Is a `refresh()` due for a window last re-read at [lastAt] (null: never)? */
    fun refreshDue(lastAt: Long?, now: Long): Boolean = lastAt == null || now - lastAt >= REFRESH_MS || now < lastAt

    /**
     * Why [rootWindowId]'s root is not the live screen, or null. [alive]: `refresh()` re-read it from the app, bypassing
     * the cache (false: the node or its window is gone). [windows]: the current window list (empty: cannot check).
     */
    fun why(rootWindowId: Int, alive: Boolean, windows: List<Win>): String? {
        if (!alive) return "dead node (its window is gone)"
        if (windows.isEmpty()) return null
        val w = windows.firstOrNull { it.id == rootWindowId } ?: return "window $rootWindowId is not on screen"
        if (!w.app) return null   // the system-window fallback (no app window at all)
        // the foreground app: the active app window, else the top one; a root from another app window is stale
        val top = windows.filter { it.app }.maxByOrNull { it.layer }
        if (!w.active && top != null && top.id != w.id) return "window $rootWindowId is neither active nor the top app window (${top.id})"
        return null
    }
}
