package ai.vox.companion

import android.content.ComponentName
import android.content.Context
import android.content.pm.PackageManager
import android.os.Handler
import android.os.Looper
import android.os.SystemClock

/**
 * When to switch the launcher icon (plain JVM, tested by LauncherIconTest). [shown] is the icon on the launcher now.
 * [observe] the wanted icon each time the link state changes; [poll] says what to do: switch only once the wanted icon
 * has been the same for [stableMs] and at least [minGapMs] after the previous switch, so a flapping link never makes the
 * launcher redraw more than once a minute.
 */
class IconSwitch(var shown: Boolean, private val stableMs: Long = 10_000, private val minGapMs: Long = 60_000) {
    private var wanted = shown
    private var since = 0L
    private var lastSwitch: Long? = null

    fun observe(on: Boolean, now: Long) {
        if (on != wanted) { wanted = on; since = now }
    }

    /** null: nothing to do. 0: switch to [shown] now (already recorded). Otherwise: poll again in that many ms. */
    fun poll(now: Long): Long? {
        if (wanted == shown) return null
        val due = maxOf(since + stableMs, lastSwitch?.let { it + minGapMs } ?: Long.MIN_VALUE)
        if (now < due) return due - now
        shown = wanted; lastSwitch = now
        return 0
    }
}

/**
 * The launcher icon follows the link: "on" (lit eyes and lamp) while paired and connected, "off" otherwise. The two
 * icons are two `<activity-alias>`es of MainActivity (manifest; `.LauncherOn` is enabled by default) and switching
 * enables one and disables the other with DONT_KILL_APP. Called by BleFeatureSource on every link state change (main
 * thread); the icon changes only as [IconSwitch] allows.
 *
 * Launcher caveat: changing which component carries the LAUNCHER category is an app update as far as the launcher is
 * concerned. Most launchers redraw the icon in place within a few seconds; some drop a home-screen shortcut, move it
 * back to the app drawer, or close their recents entry. The debounce keeps that rare. The icon stays as it was while
 * the service is not running (nothing observes the link then), and the one-a-minute limit is per process.
 */
object LauncherIcon {
    private const val ON = "ai.vox.companion.LauncherOn"
    private const val OFF = "ai.vox.companion.LauncherOff"
    private val main = Handler(Looper.getMainLooper())
    private var switch: IconSwitch? = null
    private var pending: Runnable? = null

    fun update(ctx: Context, connected: Boolean) {
        val app = ctx.applicationContext
        val s = switch ?: IconSwitch(shown = showingOn(app)).also { switch = it }
        s.observe(connected, SystemClock.elapsedRealtime())
        schedule(app, s)
    }

    // Canti's screens are started under the alias the user tapped, and disabling that alias finishes them (the system
    // logs "disabled-package"), so while any Canti screen is started the switch waits for the last one to stop.
    private var started = 0
    private var deferred: (() -> Unit)? = null
    private var watching = false

    /** Start counting Canti's started screens; VoxService calls it in onCreate, before any screen can be open. */
    fun watch(ctx: Context) {
        if (watching) return
        val app = ctx.applicationContext as? android.app.Application ?: return
        watching = true
        app.registerActivityLifecycleCallbacks(object : android.app.Application.ActivityLifecycleCallbacks {
            override fun onActivityStarted(a: android.app.Activity) { started++ }
            override fun onActivityStopped(a: android.app.Activity) {
                started = maxOf(0, started - 1)
                if (started == 0) deferred?.let { deferred = null; it() }
            }
            override fun onActivityCreated(a: android.app.Activity, b: android.os.Bundle?) {}
            override fun onActivityResumed(a: android.app.Activity) {}
            override fun onActivityPaused(a: android.app.Activity) {}
            override fun onActivitySaveInstanceState(a: android.app.Activity, b: android.os.Bundle) {}
            override fun onActivityDestroyed(a: android.app.Activity) {}
        })
    }

    private fun schedule(ctx: Context, s: IconSwitch) {
        pending?.let(main::removeCallbacks); pending = null
        watch(ctx)
        when (val r = s.poll(SystemClock.elapsedRealtime())) {
            null -> {}
            0L -> if (started > 0) deferred = { apply(ctx, s.shown) } else apply(ctx, s.shown)
            else -> pending = Runnable { pending = null; schedule(ctx, s) }.also { main.postDelayed(it, r) }
        }
    }

    private fun showingOn(ctx: Context): Boolean =
        ctx.packageManager.getComponentEnabledSetting(ComponentName(ctx, OFF)) != PackageManager.COMPONENT_ENABLED_STATE_ENABLED

    private fun apply(ctx: Context, on: Boolean) {
        val pm = ctx.packageManager
        // Enable the new one first, so there is always a launcher entry.
        try {
            pm.setComponentEnabledSetting(ComponentName(ctx, if (on) ON else OFF), PackageManager.COMPONENT_ENABLED_STATE_ENABLED, PackageManager.DONT_KILL_APP)
            pm.setComponentEnabledSetting(ComponentName(ctx, if (on) OFF else ON), PackageManager.COMPONENT_ENABLED_STATE_DISABLED, PackageManager.DONT_KILL_APP)
            EventLog.ev("launcher_icon", "icon" to if (on) "on" else "off")
        } catch (e: Exception) {
            EventLog.ev("error", "where" to "launcher icon", "error" to e.toString())
        }
    }
}
