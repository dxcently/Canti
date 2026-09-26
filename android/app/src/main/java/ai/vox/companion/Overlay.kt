package ai.vox.companion

import android.accessibilityservice.AccessibilityService
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.os.SystemClock
import android.view.Choreographer
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.TextView

/**
 * TYPE_ACCESSIBILITY_OVERLAY windows: a small status badge (mode + last action) and, in cursor mode, a cursor dot.
 * Both are not touchable and not focusable, so dispatched gestures pass straight through to the app.
 *
 * The cursor moves at a constant velocity after a move_* decision and stops on "stop", on leaving cursor mode, on
 * disarm, at the screen edge, or after [autoStopMs] (the device sends discrete events here; with the STREAM
 * characteristic the device would stop it the moment the hum ends).
 */
class Overlay(private val svc: AccessibilityService, private val screenW: () -> Int, private val screenH: () -> Int) {
    private val wm = svc.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private var badge: TextView? = null
    private var cursorView: View? = null
    private val cursorParams = params(SIZE_PX, SIZE_PX).apply { gravity = Gravity.TOP or Gravity.START }

    var x = 0f; private set
    var y = 0f; private set
    private var vx = 0f
    private var vy = 0f
    private var moveStarted = 0L
    var autoStopMs = 2500L
    var dragging = false
    var description = "stopped"; private set
    private var lastFrame = 0L

    private fun params(w: Int, h: Int) = WindowManager.LayoutParams(
        w, h, WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
        WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
            WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
        PixelFormat.TRANSLUCENT,
    )

    fun showBadge() {
        if (badge != null) return
        val tv = TextView(svc).apply {
            setTextColor(Color.WHITE); setBackgroundColor(0xAA000000.toInt()); textSize = 11f
            setPadding(16, 6, 16, 6); text = "VOX"
        }
        wm.addView(tv, params(WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.WRAP_CONTENT).apply {
            gravity = Gravity.TOP or Gravity.END; y = 8
        })
        badge = tv
    }

    fun setBadge(text: String) { badge?.text = text }

    /** Screen rects of VOX's own overlay windows (padded), so the pixel confirmer never sees its own drawing. */
    fun maskRects(): List<IntArray> = listOfNotNull(badge, cursorView).filter { it.isAttachedToWindow }.map { v ->
        val l = IntArray(2); v.getLocationOnScreen(l)
        intArrayOf(l[0] - 32, l[1] - 32, l[0] + v.width + 32, l[1] + v.height + 32)
    }

    fun cursorVisible() = cursorView != null

    // --- intent cursor mode: numbered highlights on the candidate targets ----------------------------------------

    private var highlight: View? = null
    private var hlTargets: List<Target> = emptyList()
    private var hlSelected = 0

    /** Full-screen, not touchable: a numbered box on each candidate (1 = most probable); [selected] drawn thicker. */
    fun showTargets(targets: List<Target>, selected: Int) {
        hideTargets()
        hlTargets = targets; hlSelected = selected
        val v = object : View(svc) {
            val box = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE }
            val fill = Paint(Paint.ANTI_ALIAS_FLAG)
            val txt = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.WHITE; textSize = 46f; typeface = Typeface.DEFAULT_BOLD; textAlign = Paint.Align.CENTER }
            val loc = IntArray(2)
            override fun onDraw(c: Canvas) {
                getLocationOnScreen(loc)
                hlTargets.forEachIndexed { i, t ->
                    val sel = i == hlSelected
                    val col = if (sel) 0xFFFF9800.toInt() else 0xFF2196F3.toInt()
                    box.color = col; box.strokeWidth = if (sel) 14f else 6f
                    val l = (t.left - loc[0]).toFloat(); val tp = (t.top - loc[1]).toFloat()
                    c.drawRect(l, tp, (t.right - loc[0]).toFloat(), (t.bottom - loc[1]).toFloat(), box)
                    fill.color = col
                    c.drawCircle(l + 34f, tp + 34f, 34f, fill)
                    c.drawText("${i + 1}", l + 34f, tp + 50f, txt)
                }
            }
        }
        wm.addView(v, params(WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.MATCH_PARENT).apply {
            gravity = Gravity.TOP or Gravity.START
        })
        highlight = v
    }

    fun selectTarget(i: Int) { hlSelected = i; highlight?.invalidate() }

    fun hideTargets() {
        highlight?.let { try { wm.removeView(it) } catch (_: Exception) {} }
        highlight = null; hlTargets = emptyList()
    }

    fun showCursor() {
        if (cursorView != null) return
        x = screenW() / 2f; y = screenH() / 2f
        val v = object : View(svc) {
            val p = Paint(Paint.ANTI_ALIAS_FLAG)
            override fun onDraw(c: Canvas) {
                p.color = if (dragging) 0xCCFF8800.toInt() else 0xCC2196F3.toInt()
                c.drawCircle(width / 2f, height / 2f, width / 2f - 4, p)
                p.color = Color.WHITE
                c.drawCircle(width / 2f, height / 2f, 6f, p)
            }
        }
        wm.addView(v, cursorParams.also { place(it) })
        cursorView = v
    }

    fun hideCursor() {
        stop()
        cursorView?.let { wm.removeView(it) }
        cursorView = null
    }

    fun remove() {
        hideTargets()
        hideCursor()
        badge?.let { wm.removeView(it) }
        badge = null
    }

    /** Start moving: direction like "up", "down_left"; fast=true for loud hums. */
    fun move(direction: String, fast: Boolean) {
        showCursor()
        val speed = (if (fast) 0.45f else 0.15f) * screenH()   // screen heights per second
        val dx = when { "left" in direction -> -1f; "right" in direction -> 1f; else -> 0f }
        val dy = when { direction.startsWith("up") -> -1f; direction.startsWith("down") -> 1f; else -> 0f }
        val norm = if (dx != 0f && dy != 0f) 0.7071f else 1f
        vx = dx * speed * norm; vy = dy * speed * norm
        moveStarted = SystemClock.elapsedRealtime()
        lastFrame = System.nanoTime()
        description = (if (dragging) "dragging, " else "") + "moving ${direction.replace('_', '-')} ${if (fast) "fast" else "slow"}"
        Choreographer.getInstance().removeFrameCallback(frame)
        Choreographer.getInstance().postFrameCallback(frame)
    }

    fun stop() {
        vx = 0f; vy = 0f
        Choreographer.getInstance().removeFrameCallback(frame)
        description = if (dragging) "dragging, stopped" else "stopped"
    }

    fun moveTo(nx: Float, ny: Float) {
        showCursor(); stop()
        x = nx.coerceIn(0f, screenW() - 1f); y = ny.coerceIn(0f, screenH() - 1f)
        cursorView?.let { wm.updateViewLayout(it, cursorParams.also { p -> place(p) }) }
    }

    fun refresh() { cursorView?.invalidate(); description = if (vx == 0f && vy == 0f) (if (dragging) "dragging, stopped" else "stopped") else description }

    private fun place(p: WindowManager.LayoutParams) {
        p.x = (x - SIZE_PX / 2).toInt(); p.y = (y - SIZE_PX / 2).toInt()
    }

    private val frame = object : Choreographer.FrameCallback {
        override fun doFrame(now: Long) {
            val dt = (now - lastFrame) / 1e9f
            lastFrame = now
            x += vx * dt; y += vy * dt
            val hitEdge = x <= 0f || y <= 0f || x >= screenW() - 1f || y >= screenH() - 1f
            x = x.coerceIn(0f, screenW() - 1f); y = y.coerceIn(0f, screenH() - 1f)
            cursorView?.let { wm.updateViewLayout(it, cursorParams.also { p -> place(p) }) }
            if (hitEdge || SystemClock.elapsedRealtime() - moveStarted > autoStopMs) {
                stop()
                EventLog.ev("cursor", "state" to description, "x" to x.toInt(), "y" to y.toInt(), "why" to if (hitEdge) "edge" else "auto-stop")
            } else {
                Choreographer.getInstance().postFrameCallback(this)
            }
        }
    }

    companion object { const val SIZE_PX = 64 }
}
