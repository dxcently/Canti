package ai.vox.companion.audio

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.PixelFormat
import android.os.SystemClock
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import ai.vox.companion.EventLog

/**
 * Sees every touch-down on the screen, whatever app is in front, for [TouchGuard]: a 1x1 invisible accessibility
 * overlay with FLAG_WATCH_OUTSIDE_TOUCH gets an ACTION_OUTSIDE for each touch that starts outside it. Other apps'
 * touches arrive with their coordinates zeroed (Android 10+), which is all we want: the time, not the place.
 *
 * Why not TYPE_TOUCH_INTERACTION_START/END: those come only in touch-exploration mode (TalkBack-style), which would
 * change how the whole phone is touched.
 *
 * [ctx] must be the accessibility service (TYPE_ACCESSIBILITY_OVERLAY needs its window token). Main thread only.
 */
class TouchWatch(private val ctx: Context, private val guard: TouchGuard) {
    private var view: View? = null
    var error: String? = null; private set

    @SuppressLint("ClickableViewAccessibility")
    fun start() {
        if (view != null) return
        val wm = ctx.getSystemService(WindowManager::class.java)
        val v = View(ctx)
        v.setOnTouchListener { _, e ->
            if (e.actionMasked == MotionEvent.ACTION_OUTSIDE || e.actionMasked == MotionEvent.ACTION_DOWN) {
                val at = e.eventTime + (SystemClock.elapsedRealtime() - SystemClock.uptimeMillis())
                // Canti's own touch: the Executor's stamp (uptime clock, like eventTime) or no input device
                val injected = TouchGuard.isInjected(e.deviceId, e.eventTime,
                    ai.vox.companion.Executor.lastInjectedGestureMs, ai.vox.companion.Executor.lastInjectedGestureEndMs)
                guard.onTouchDown(at, injected)
                if (guard.userTouches + guard.injectedTouches <= 3)   // the first few, to check a phone's flags and devices
                    EventLog.ev("mic_touch", "injected" to injected, "device" to e.deviceId, "source" to e.source,
                        "flags" to e.flags, "action" to e.actionMasked)
            }
            false
        }
        val lp = WindowManager.LayoutParams(1, 1, WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
                WindowManager.LayoutParams.FLAG_WATCH_OUTSIDE_TOUCH, PixelFormat.TRANSLUCENT)
            .apply { gravity = Gravity.TOP or Gravity.START; x = 0; y = 0; title = "Canti touch watch" }
        error = try { wm.addView(v, lp); view = v; null } catch (e: Exception) { e.toString() }
        EventLog.ev("mic_touch_watch", "state" to if (error == null) "on" else "failed", "error" to error)
    }

    fun stop() {
        val v = view ?: return
        view = null
        try { ctx.getSystemService(WindowManager::class.java).removeView(v) } catch (_: Exception) {}
        EventLog.ev("mic_touch_watch", "state" to "off", "user_touches" to guard.userTouches,
            "injected_touches" to guard.injectedTouches, "sounds_dropped" to guard.dropped)
    }

    val running get() = view != null
}
