package ai.vox.companion

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Context
import android.content.Intent
import android.graphics.Path
import android.media.AudioManager
import android.provider.MediaStore
import android.view.KeyEvent
import android.view.accessibility.AccessibilityNodeInfo

/**
 * Performs an action key from ACTIONS / CURSOR_ACTIONS. Gestures via dispatchGesture, navigation via
 * performGlobalAction, media/volume via AudioManager. Every screen-changing action is registered with the
 * [Confirmer] before dispatch.
 *
 * Geometry (fractions of the screen) keeps strokes away from the edges, where gesture navigation would take them.
 */
class Executor(
    private val svc: AccessibilityService,
    private val overlay: Overlay,
    private val confirmer: Confirmer,
    private val screenW: () -> Int,
    private val screenH: () -> Int,
    private val onListen: () -> Unit,
) {
    data class Result(val ok: Boolean, val how: String, val watch: Long? = null)

    private val audio = svc.getSystemService(Context.AUDIO_SERVICE) as AudioManager
    private var dragStart: Pair<Float, Float>? = null

    fun perform(action: String, mode: String): Result {
        val w = screenW().toFloat(); val h = screenH().toFloat()
        val cx = w / 2; val cy = h / 2
        if (mode == "cursor") cursorAction(action)?.let { return it }
        return when (action) {
            "none" -> Result(true, "nothing")
            "swipe_up" -> gesture(action, swipe(cx, h * 0.72f, cx, h * 0.28f, 220), "swipe")
            "swipe_down" -> gesture(action, swipe(cx, h * 0.28f, cx, h * 0.72f, 220), "swipe")
            "swipe_left" -> gesture(action, swipe(w * 0.82f, cy, w * 0.18f, cy, 220), "swipe")
            "swipe_right" -> gesture(action, swipe(w * 0.18f, cy, w * 0.82f, cy, 220), "swipe")
            "tap" -> gesture(action, tap(cx, cy), "tap(center)")
            "double_tap", "like" -> gesture(action, doubleTap(cx, cy), "double-tap(center)")
            "long_press" -> gesture(action, press(cx, cy, 1000), "long-press(center,1000ms)")
            "back" -> global(action, AccessibilityService.GLOBAL_ACTION_BACK)
            "home" -> global(action, AccessibilityService.GLOBAL_ACTION_HOME)
            "recents" -> global(action, AccessibilityService.GLOBAL_ACTION_RECENTS)
            "notifications" -> global(action, AccessibilityService.GLOBAL_ACTION_NOTIFICATIONS)
            "scroll_down" -> scroll(action, forward = true) ?: gesture(action, swipe(cx, h * 0.62f, cx, h * 0.42f, 300), "short-swipe")
            "scroll_up" -> scroll(action, forward = false) ?: gesture(action, swipe(cx, h * 0.42f, cx, h * 0.62f, 300), "short-swipe")
            "zoom_in" -> gesture(action, pinch(cx, cy, w * 0.08f, w * 0.30f), "pinch-out")
            "zoom_out" -> gesture(action, pinch(cx, cy, w * 0.30f, w * 0.08f), "pinch-in")
            "next_item" -> mediaKey(action, KeyEvent.KEYCODE_MEDIA_NEXT)
            "previous_item" -> mediaKey(action, KeyEvent.KEYCODE_MEDIA_PREVIOUS)
            "play_pause" -> mediaKey(action, KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE)
            "volume_up" -> volume(action, AudioManager.ADJUST_RAISE)
            "volume_down" -> volume(action, AudioManager.ADJUST_LOWER)
            "open_camera" -> {
                val id = confirmer.begin(action)
                try {
                    svc.startActivity(Intent(MediaStore.INTENT_ACTION_STILL_IMAGE_CAMERA).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                    Result(true, "intent:STILL_IMAGE_CAMERA", id)
                } catch (e: Exception) { Result(false, "no camera app: ${e.javaClass.simpleName}", id) }
            }
            // An accessibility service cannot inject KEYCODE_CAMERA; per-app shutter taps belong in a profile rule.
            "take_photo" -> Result(false, "unsupported: no generic shutter action (bind a tap in the camera app's profile)")
            "listen_for_phrase" -> { onListen(); Result(true, "listening window opened") }
            else -> Result(false, "unknown action")
        }
    }

    /** Cursor-mode actions; null = not a cursor-only action (e.g. "back" falls through to the normal table). */
    private fun cursorAction(action: String): Result? {
        if (action.startsWith("move_")) {
            val parts = action.removePrefix("move_").split("_")
            val fast = parts.last() == "fast"
            overlay.move(parts.dropLast(1).joinToString("_"), fast)
            return Result(true, "cursor ${overlay.description}")
        }
        return when (action) {
            "stop" -> { overlay.stop(); Result(true, "cursor stopped") }
            "click" -> { overlay.stop(); gesture(action, tap(overlay.x, overlay.y), "tap(cursor ${overlay.x.toInt()},${overlay.y.toInt()})") }
            "drag_toggle" -> {
                overlay.stop()
                val start = dragStart
                if (start == null) {
                    dragStart = overlay.x to overlay.y; overlay.dragging = true; overlay.refresh()
                    Result(true, "drag started at ${overlay.x.toInt()},${overlay.y.toInt()}")
                } else {
                    dragStart = null; overlay.dragging = false; overlay.refresh()
                    gesture(action, swipe(start.first, start.second, overlay.x, overlay.y, 600), "drag")
                }
            }
            "grid_pick_1" -> { overlay.moveTo(screenW() / 6f, screenH() / 6f); Result(true, "cursor to top-left cell") }
            "grid_pick_5" -> { overlay.moveTo(screenW() / 2f, screenH() / 2f); Result(true, "cursor to centre cell") }
            "grid_pick_9" -> { overlay.moveTo(screenW() * 5 / 6f, screenH() * 5 / 6f); Result(true, "cursor to bottom-right cell") }
            else -> null
        }
    }

    /** Intent cursor mode: tap the centre of a chosen element (and park the cursor there, if it is shown). */
    fun tapTarget(t: Target): Result {
        val r = gesture("tap_target", tap(t.cx.toFloat(), t.cy.toFloat()), "tap(${t.cx},${t.cy}) ${t.option}")
        if (overlay.cursorVisible()) overlay.moveTo(t.cx.toFloat(), t.cy.toFloat())
        return r
    }

    fun cancelDrag() { dragStart = null; overlay.dragging = false }

    // --- primitives -----------------------------------------------------------------------------------------------

    private fun gesture(action: String, g: GestureDescription, how: String): Result {
        val id = confirmer.begin(action, injected = true)
        val ok = svc.dispatchGesture(g, object : AccessibilityService.GestureResultCallback() {
            override fun onCompleted(d: GestureDescription?) {
                confirmer.gestureDone(id)
                EventLog.ev("gesture", "watch" to id, "action" to action, "result" to "completed")
            }
            override fun onCancelled(d: GestureDescription?) {
                confirmer.gestureDone(id)
                EventLog.ev("gesture", "watch" to id, "action" to action, "result" to "cancelled")
            }
        }, null)
        return Result(ok, how, id)
    }

    private fun global(action: String, code: Int): Result {
        val id = confirmer.begin(action)
        return Result(svc.performGlobalAction(code), "global:$action", id)
    }

    private fun scroll(action: String, forward: Boolean): Result? {
        val root = TreeReader.appRoot(svc) ?: return null
        val target = largestScrollable(root) ?: return null
        val id = confirmer.begin(action)
        val ok = target.performAction(if (forward) AccessibilityNodeInfo.ACTION_SCROLL_FORWARD else AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD)
        return Result(ok, "node-scroll:${target.className}", id)
    }

    private fun largestScrollable(root: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        var best: AccessibilityNodeInfo? = null
        var bestArea = 0L
        val r = android.graphics.Rect()
        val stack = ArrayDeque<AccessibilityNodeInfo>().apply { add(root) }
        var n = 0
        while (stack.isNotEmpty() && n++ < 1500) {
            val x = stack.removeLast()
            if (x.isScrollable && x.isVisibleToUser) {
                x.getBoundsInScreen(r)
                val a = r.width().toLong() * r.height()
                if (a > bestArea) { best = x; bestArea = a }
            }
            for (i in 0 until x.childCount) x.getChild(i)?.let { stack.add(it) }
        }
        return best
    }

    private fun mediaKey(action: String, code: Int): Result {
        val id = confirmer.begin(action)
        audio.dispatchMediaKeyEvent(KeyEvent(KeyEvent.ACTION_DOWN, code))
        audio.dispatchMediaKeyEvent(KeyEvent(KeyEvent.ACTION_UP, code))
        return Result(true, "media-key:${KeyEvent.keyCodeToString(code)}", id)
    }

    private fun volume(action: String, dir: Int): Result {
        val id = confirmer.begin(action)
        audio.adjustStreamVolume(AudioManager.STREAM_MUSIC, dir, AudioManager.FLAG_SHOW_UI)
        return Result(true, "volume:${if (dir > 0) "raise" else "lower"}", id)
    }

    companion object {
        fun swipe(x1: Float, y1: Float, x2: Float, y2: Float, ms: Long): GestureDescription {
            val p = Path().apply { moveTo(x1, y1); lineTo(x2, y2) }
            return GestureDescription.Builder().addStroke(GestureDescription.StrokeDescription(p, 0, ms)).build()
        }

        fun tap(x: Float, y: Float) = press(x, y, 60)

        fun press(x: Float, y: Float, ms: Long): GestureDescription {
            val p = Path().apply { moveTo(x, y) }
            return GestureDescription.Builder().addStroke(GestureDescription.StrokeDescription(p, 0, ms)).build()
        }

        fun doubleTap(x: Float, y: Float): GestureDescription {
            val p = Path().apply { moveTo(x, y) }
            return GestureDescription.Builder()
                .addStroke(GestureDescription.StrokeDescription(p, 0, 50))
                .addStroke(GestureDescription.StrokeDescription(p, 150, 50))
                .build()
        }

        /** Two fingers moving apart (from < to) or together (from > to) along the horizontal axis. */
        fun pinch(cx: Float, cy: Float, from: Float, to: Float): GestureDescription {
            val a = Path().apply { moveTo(cx - from, cy); lineTo(cx - to, cy) }
            val b = Path().apply { moveTo(cx + from, cy); lineTo(cx + to, cy) }
            return GestureDescription.Builder()
                .addStroke(GestureDescription.StrokeDescription(a, 0, 400))
                .addStroke(GestureDescription.StrokeDescription(b, 0, 400))
                .build()
        }
    }
}
