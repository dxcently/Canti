package ai.vox.companion

/**
 * Whether Canti's own screens (this process's activities) have all been stopped for [graceMs]: the app is in the
 * background (Home, another app, the screen off). [onBackground] runs once per such stretch, with the time it has
 * been away.
 *
 * Only a stop of the last started screen counts; a started screen within [graceMs] calls it off. So moving between
 * Canti screens (the next starts before the old stops), a dialog or the system permission prompt (the screen is only
 * paused), a rotation (the engine handles it; a recreate starts the new one at once) and a quick look away and back
 * mid-step are not "the background". Main thread (VoxService's activity callbacks); pure for the tests.
 */
class BackgroundGuard(private val scheduler: Scheduler, private val graceMs: Long, private val onBackground: (awayMs: Long) -> Unit) {
    private val started = java.util.Collections.newSetFromMap(java.util.IdentityHashMap<Any, Boolean>())
    private var pending: (() -> Unit)? = null
    private var stoppedAt = 0L

    /** At least one Canti screen is started now. */
    val foreground: Boolean get() = started.isNotEmpty()

    fun started(screen: Any) {
        started += screen
        pending?.invoke(); pending = null
    }

    fun stopped(screen: Any) {
        if (!started.remove(screen) || started.isNotEmpty()) return
        pending?.invoke()
        stoppedAt = scheduler.now()
        pending = scheduler.schedule(graceMs) {
            pending = null
            if (started.isEmpty()) onBackground(scheduler.now() - stoppedAt)
        }
    }

    fun clear() {
        started.clear()
        pending?.invoke(); pending = null
    }
}
