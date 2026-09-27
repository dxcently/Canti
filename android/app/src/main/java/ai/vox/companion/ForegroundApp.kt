package ai.vox.companion

/**
 * The foreground app's package without reading the app's tree (pure; ForegroundAppTest).
 *
 * `currentApp()` runs for every gesture. Reading it from the tree ([TreeReader.appRoot]: `rootInActiveWindow`) is a
 * synchronous call into the app's UI thread whenever the app's event flood has emptied the accessibility cache
 * (Instagram's feed: BLE message -> decision 8-503 ms on the Flip, TikTok ~9 ms). A window belongs to one app for its
 * whole life, so each window's package is learned once, from a root [TreeReader.appRoot] returned ([WindowPackages]),
 * and [resolve] repeats appRoot's choice on the window list (cached until the windows change, so cheap):
 *  1. the active window's app, unless it is Canti's own; Canti's own too when an active app window exists;
 *  2. else the first application window in list order, or a system window that is not Canti's;
 * with the same answer as reading the tree. A window it has not learned yet: [Result.Read], read the tree once.
 */
object ForegroundApp {
    enum class Type { APPLICATION, SYSTEM, OTHER }
    data class Win(val id: Int, val type: Type, val active: Boolean)

    sealed class Result {
        data class Known(val pkg: String) : Result()
        /** Read the tree (appRoot) and learn its window. */
        object Read : Result()
        /** No app window at all: appRoot would return nothing either. */
        object None : Result()
    }

    fun resolve(windows: List<Win>, pkgOf: (Int) -> String?, own: String): Result {
        if (windows.isEmpty()) return Result.Read
        val active = windows.firstOrNull { it.active }
        if (active != null) {
            val p = pkgOf(active.id) ?: return Result.Read
            if (p != own) return Result.Known(p)
            if (windows.any { it.active && it.type == Type.APPLICATION }) return Result.Known(p)
        }
        for (w in windows) when (w.type) {
            Type.APPLICATION -> return pkgOf(w.id)?.let { Result.Known(it) } ?: Result.Read
            Type.SYSTEM -> { val p = pkgOf(w.id) ?: return Result.Read; if (p != own) return Result.Known(p) }
            Type.OTHER -> {}
        }
        return Result.None
    }
}

/** Window id -> package, learned from roots that passed [RootCheck]; forgets windows no longer listed. Thread-safe. */
class WindowPackages {
    private val map = HashMap<Int, String>()

    @Synchronized fun learn(windowId: Int, pkg: String?) { if (windowId >= 0 && !pkg.isNullOrEmpty()) map[windowId] = pkg }
    @Synchronized fun get(windowId: Int): String? = map[windowId]
    /** Keep only the windows on screen now (called with the current window list). */
    @Synchronized fun retain(ids: Collection<Int>) { if (ids.isNotEmpty()) map.keys.retainAll(ids.toSet()) }
    @Synchronized fun size() = map.size
}
