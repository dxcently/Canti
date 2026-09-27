package ai.vox.companion

import android.accessibilityservice.AccessibilityService
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.SystemClock
import android.view.Choreographer
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.TextView
import ai.vox.companion.joystick.JoyIndicators
import kotlin.math.hypot

/**
 * TYPE_ACCESSIBILITY_OVERLAY windows: the floating Canti head ([BadgeFace]) and, in cursor mode, a cursor dot.
 *
 * The head is the only touchable one: its window is just its own size and FLAG_NOT_TOUCH_MODAL, so touches outside it
 * go to the app. Drag moves it; on release it snaps to the nearer side edge, and its position is remembered per
 * orientation. It stays at a side edge, outside the paths of the injected swipes (vertical ones run down the middle,
 * horizontal ones between 15% and 85% of the width) and of the hold-to-scroll drag. A tap opens a small pixel menu
 * ([BadgeActions]): Gesture / Cursor / Pause-Resume and the sound source; so does a long-press. In
 * [BadgeState.TAP_TO_WAKE] (the Pico paused itself after a link drop) a tap wakes the Pico instead. While one of Canti's own screens is in front
 * the head hops into the top-left corner, where the app's header shows it, and hides ([tuckBadge]). The cursor dot and
 * target highlights are not
 * touchable and not focusable, so dispatched gestures pass straight through them.
 *
 * The cursor moves at a constant velocity after a move_* decision and stops on "stop", on leaving cursor mode, on
 * disarm, at the screen edge, or after [autoStopMs] (the device sends discrete events here; with the STREAM
 * characteristic the device would stop it the moment the hum ends).
 */
class Overlay(private val svc: AccessibilityService, private val screenW: () -> Int, private val screenH: () -> Int) {
    private val wm = svc.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private var badge: BadgeFace? = null
    private var badgeParams: WindowManager.LayoutParams? = null
    private var actions: BadgeActions? = null
    private var menu: View? = null
    private var menuClosedAt = 0L
    private val prefs = svc.getSharedPreferences("canti_badge", Context.MODE_PRIVATE)
    private val density = svc.resources.displayMetrics.density
    private val pixelFont: Typeface = try { Typeface.createFromAsset(svc.assets, "flutter_assets/assets/fonts/PressStart2P-Regular.ttf") }
        catch (_: Exception) { Typeface.MONOSPACE }
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

    fun showBadge(actions: BadgeActions) {
        if (badge != null) return
        this.actions = actions
        val face = BadgeFace.create(svc)
        val p = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT,
        ).apply { gravity = Gravity.TOP or Gravity.START }
        badge = face; badgeParams = p
        face.view.setOnTouchListener(BadgeTouch())
        face.view.measure(View.MeasureSpec.UNSPECIFIED, View.MeasureSpec.UNSPECIFIED)
        placeBadge()
        wm.addView(face.view, p); OwnWindows.note(face.view)
    }

    fun setBadgeState(s: BadgeState) { badge?.setState(s) }

    /** The joystick's Face A still (a joy_* manifest state) on the badge, or null for the normal faces. */
    fun setBadgeJoy(state: String?) { badge?.setJoy(state) }

    /**
     * An injected gesture whose strokes start at [points] would land on the head (it is touchable). If one does, the
     * head (and its menu) let touches through for [ms]; returns true so the caller can wait a frame for the input
     * windows to update before dispatching. Swipes, pinches and the hold drag never start there (the head sits at a
     * side edge); cursor and target taps can.
     */
    fun passThroughIfUnder(points: List<FloatArray>, ms: Long): Boolean {
        val v = badge?.view ?: return false
        val p = badgeParams ?: return false
        if (!v.isAttachedToWindow || tucked || !v.isShown) return false
        val l = IntArray(2); v.getLocationOnScreen(l)
        val hit = points.any { (x, y) -> x >= l[0] && x < l[0] + v.width && y >= l[1] && y < l[1] + v.height }
        if (!hit) return false
        hideMenu()
        p.flags = p.flags or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
        wm.updateViewLayout(v, p)
        v.removeCallbacks(restoreTouch); v.postDelayed(restoreTouch, ms)
        EventLog.ev("badge", "event" to "pass-through", "ms" to ms)
        return true
    }

    private val restoreTouch = Runnable {
        val v = badge?.view; val p = badgeParams
        if (v != null && p != null && v.isAttachedToWindow && !tucked) {
            p.flags = p.flags and WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE.inv()
            wm.updateViewLayout(v, p)
        }
    }
    fun badgePlayOnce(s: BadgeState) { badge?.playOnce(s) }

    private fun portrait() = screenW() <= screenH()
    private fun posKey() = if (portrait()) "pos_portrait" else "pos_landscape"

    /** Put the head at its remembered edge and height for this orientation (default: right edge, 30% down). */
    fun placeBadge() {
        val v = badge?.view ?: return
        val p = badgeParams ?: return
        hop?.let { v.removeCallbacks(it) }; hop = null
        val (x, y) = if (tucked) corner() else home(v)
        p.x = x; p.y = y
        // A hop cut short (rotation) still ends in its state: hidden and untouchable, or shown and touchable.
        if (tucked) v.visibility = View.INVISIBLE
        else { v.visibility = View.VISIBLE; p.flags = p.flags and WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE.inv() }
        if (v.isAttachedToWindow) wm.updateViewLayout(v, p)
    }

    /** The remembered spot for this orientation. */
    private fun home(v: View): Pair<Int, Int> {
        val saved = prefs.getString(posKey(), null)?.split(",")
        val right = saved?.getOrNull(0) != "L"
        val frac = saved?.getOrNull(1)?.toFloatOrNull() ?: 0.30f
        val w = (if (v.width > 0) v.width else v.measuredWidth).coerceAtLeast(1)
        val h = (if (v.height > 0) v.height else v.measuredHeight).coerceAtLeast(1)
        return (if (right) screenW() - w else 0) to clampY((frac * screenH()).toInt(), h)
    }

    /** Where the app's header shows the head: the top-left corner, under the status bar. */
    private fun corner(): Pair<Int, Int> = (8 * density).toInt() to (48 * density).toInt()

    // --- tucked away while a Canti screen is in front ---------------------------------------------------------------

    private var tucked = false
    private var hop: Runnable? = null

    // --- hidden for a screen capture (the badge_hide debug op) -------------------------------------------------------

    private var captureHidden = false
    private val captureRestore = Runnable { hideForCapture(false) }

    /**
     * [hide] = a harvest is about to capture the screen: hide the head and its menu so they cover no target. It comes
     * back by itself after [ms], so a harvest that dies mid-capture cannot leave it hidden. Tucking still decides
     * whether it shows once it is back.
     */
    fun hideForCapture(hide: Boolean, ms: Long = 10_000) {
        val v = badge?.view ?: return
        v.removeCallbacks(captureRestore)
        captureHidden = hide
        if (hide) { hideMenu(); v.visibility = View.INVISIBLE; v.postDelayed(captureRestore, ms) }
        else v.visibility = if (tucked) View.INVISIBLE else View.VISIBLE
    }

    /**
     * [tuck] = one of Canti's own screens is in front (its header shows the head): hop into the top-left corner and
     * hide, untouchable. Otherwise reappear there and hop back to the remembered spot. So there is never a second head
     * on screen. The hop is [HOP_STEPS] pixel-snapped window moves on an arc (about 240 ms, no animator); instant when
     * the system's animations are off.
     */
    fun tuckBadge(tuck: Boolean) {
        if (tuck == tucked) return
        val v = badge?.view ?: return
        val p = badgeParams ?: return
        tucked = tuck
        hideMenu()
        v.removeCallbacks(restoreTouch)
        EventLog.ev("badge", "event" to if (tuck) "tucked" else "untucked")
        if (tuck) {
            p.flags = p.flags or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
            hopTo(v, p, corner()) { v.visibility = View.INVISIBLE }
        } else {
            val (cx, cy) = corner()
            p.x = cx; p.y = cy
            v.visibility = if (captureHidden) View.INVISIBLE else View.VISIBLE
            if (v.isAttachedToWindow) wm.updateViewLayout(v, p)
            hopTo(v, p, home(v)) {
                p.flags = p.flags and WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE.inv()
                if (v.isAttachedToWindow) wm.updateViewLayout(v, p)
            }
        }
    }

    private fun hopTo(v: View, p: WindowManager.LayoutParams, to: Pair<Int, Int>, done: () -> Unit) {
        hop?.let { v.removeCallbacks(it) }
        val fromX = p.x; val fromY = p.y
        val steps = if (animationsOff()) 1 else HOP_STEPS
        val unit = (2 * density).toInt().coerceAtLeast(1)
        val lift = 24 * density
        var i = 0
        val r = object : Runnable {
            override fun run() {
                if (hop !== this) return
                i++
                if (i >= steps) {
                    p.x = to.first; p.y = to.second
                    hop = null
                    if (v.isAttachedToWindow) wm.updateViewLayout(v, p)
                    done()
                    return
                }
                val t = i.toFloat() / steps
                val x = fromX + (to.first - fromX) * t
                val y = fromY + (to.second - fromY) * t - lift * 4 * t * (1 - t)
                p.x = Math.round(x / unit) * unit; p.y = Math.round(y / unit) * unit
                if (v.isAttachedToWindow) wm.updateViewLayout(v, p)
                v.postDelayed(this, HOP_FRAME_MS)
            }
        }
        hop = r
        v.post(r)
    }

    private fun animationsOff() = try {
        android.provider.Settings.Global.getFloat(svc.contentResolver, android.provider.Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f
    } catch (_: Exception) { false }

    /** Keep the head out of the status bar and the navigation bar (48 dp each). */
    private fun clampY(y: Int, h: Int): Int {
        val m = (48 * density).toInt()
        return y.coerceIn(m, (screenH() - m - h).coerceAtLeast(m))
    }

    private fun snapBadge() {
        val v = badge?.view ?: return
        val p = badgeParams ?: return
        val right = p.x + v.width / 2 >= screenW() / 2
        p.x = if (right) screenW() - v.width else 0
        p.y = clampY(p.y, v.height)
        wm.updateViewLayout(v, p)
        val frac = p.y.toFloat() / screenH()
        prefs.edit().putString(posKey(), "${if (right) "R" else "L"},$frac").apply()
        EventLog.ev("badge", "event" to "moved", "edge" to if (right) "right" else "left", "y_frac" to Math.round(frac * 1000) / 1000.0,
            "orientation" to if (portrait()) "portrait" else "landscape")
    }

    /**
     * Drag moves the head (snapping to an edge on release). A tap without movement toggles the menu, or, while the Pico
     * sits paused after a link drop ([BadgeActions.wakeable]), wakes it; a long-press always opens the menu
     * ([BadgeStates.onTap], [BadgeStates.onLongPress]).
     */
    private inner class BadgeTouch : View.OnTouchListener {
        private val slop = ViewConfiguration.get(svc).scaledTouchSlop
        private var downX = 0f; private var downY = 0f; private var startX = 0; private var startY = 0; private var moved = false
        private var longPressed = false
        private val longPress = Runnable {
            if (moved || tucked) return@Runnable
            longPressed = true
            EventLog.ev("badge", "event" to "long-press", "wakeable" to (actions?.wakeable == true))
            if (BadgeStates.onLongPress() == BadgeStates.Touch.MENU && menu == null) showMenu()
        }

        override fun onTouch(v: View, e: MotionEvent): Boolean {
            val p = badgeParams ?: return false
            when (e.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    downX = e.rawX; downY = e.rawY; startX = p.x; startY = p.y; moved = false; longPressed = false
                    v.removeCallbacks(longPress); v.postDelayed(longPress, ViewConfiguration.getLongPressTimeout().toLong())
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = e.rawX - downX; val dy = e.rawY - downY
                    if (!moved && hypot(dx, dy) > slop) { moved = true; v.removeCallbacks(longPress); hideMenu() }
                    if (moved) {
                        p.x = (startX + dx).toInt().coerceIn(0, screenW() - v.width)
                        p.y = (startY + dy).toInt().coerceIn(0, screenH() - v.height)
                        wm.updateViewLayout(v, p)
                    }
                }
                MotionEvent.ACTION_UP -> {
                    v.removeCallbacks(longPress)
                    if (moved) snapBadge() else if (!longPressed) tap()
                }
                MotionEvent.ACTION_CANCEL -> { v.removeCallbacks(longPress); if (moved) snapBadge() }
            }
            return true
        }

        private fun tap() {
            val a = actions
            if (tucked || a == null || BadgeStates.onTap(a.wakeable) == BadgeStates.Touch.MENU) { toggleMenu(); return }
            hideMenu()
            EventLog.ev("badge", "event" to "tap-to-wake")
            a.wake()
        }
    }

    // --- the badge's tap menu ------------------------------------------------------------------------------------

    private fun toggleMenu() {
        if (menu != null) { hideMenu(); return }
        if (tucked) return
        // The tap that closed the menu (an outside touch on the head) must not reopen it at once.
        if (SystemClock.elapsedRealtime() - menuClosedAt < 300) return
        showMenu()
    }

    fun hideMenu() {
        val m = menu ?: return
        menu = null; menuClosedAt = SystemClock.elapsedRealtime()
        try { wm.removeView(m) } catch (_: Exception) {}
    }

    private fun showMenu() {
        val a = actions ?: return
        val head = badge?.view ?: return
        val hp = badgeParams ?: return
        val unit = (2 * density).toInt().coerceAtLeast(2)
        val box = LinearLayout(svc).apply {
            orientation = LinearLayout.VERTICAL
            background = GradientDrawable().apply { setColor(Color.BLACK); setStroke(unit, Color.WHITE) }
            setPadding(unit * 3, unit * 3, unit * 3, unit * 3)
        }
        fun row(text: String, selected: Boolean, header: Boolean = false, onTap: (() -> Unit)? = null) {
            box.addView(TextView(svc).apply {
                this.text = (if (selected) "> " else "  ") + text
                typeface = pixelFont; textSize = if (header) 7f else 9f
                setTextColor(if (header) 0xFF9E9E9E.toInt() else Color.WHITE)
                setPadding(unit * 2, unit * (if (header) 4 else 3), unit * 4, unit * 3)
                if (onTap != null) setOnClickListener { hideMenu(); onTap() }
                contentDescription = text
            })
        }
        val mode = a.mode
        row("GESTURE", mode == "gesture") { a.setMode("gesture") }
        row("CURSOR", mode == "cursor") { a.setMode("cursor") }
        if (a.joystick) {
            row("RECENTRE", false) { a.recentre() }
            row("CALIBRATE", false) { a.calibrate() }
        }
        row(if (a.paused) "RESUME" else "PAUSE", false) { a.setPaused(!a.paused) }
        row("SOUND SOURCE", false, header = true)
        val src = a.source
        for ((key, label) in BadgeActions.SOURCES) row(label, key == src) { a.setSource(key) }
        box.setOnTouchListener { _, e -> if (e.actionMasked == MotionEvent.ACTION_OUTSIDE) hideMenu(); false }
        box.measure(View.MeasureSpec.UNSPECIFIED, View.MeasureSpec.UNSPECIFIED)
        val right = hp.x + head.width / 2 >= screenW() / 2
        val p = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
                WindowManager.LayoutParams.FLAG_WATCH_OUTSIDE_TOUCH or WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = if (right) (hp.x - box.measuredWidth - unit * 2).coerceAtLeast(0) else (hp.x + head.width + unit * 2)
            y = hp.y.coerceAtMost((screenH() - box.measuredHeight - (48 * density).toInt()).coerceAtLeast(0))
        }
        wm.addView(box, p); OwnWindows.note(box)
        menu = box
        EventLog.ev("badge", "event" to "menu", "mode" to mode, "paused" to a.paused, "source" to src)
    }

    /** Screen rects of Canti's own overlay windows (padded), so the pixel confirmer never sees its own drawing. */
    fun maskRects(): List<IntArray> = listOfNotNull(badge?.view, menu, cursorView, bracketView).filter { it.isAttachedToWindow && it.isShown }.map { v ->
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
        OwnWindows.note(v)
        highlight = v
    }

    fun selectTarget(i: Int) { hlSelected = i; highlight?.invalidate() }

    fun hideTargets() {
        highlight?.let { try { wm.removeView(it) } catch (_: Exception) {} }
        highlight = null; hlTargets = emptyList()
    }

    /**
     * Show the cursor where it last was: the position never resets (user decision 2026-09-27). Only the first show
     * ever starts in the centre; [recentre] and a rotation's clamp ([clampCursor]) are the only other jumps.
     */
    fun showCursor() {
        if (cursorView != null) return
        if (!placed) { x = screenW() / 2f; y = screenH() / 2f; placed = true }
        x = x.coerceIn(0f, (screenW() - 1f).coerceAtLeast(0f)); y = y.coerceIn(0f, (screenH() - 1f).coerceAtLeast(0f))
        val art = joyArt
        val v = if (art != null) JoyCursorView(art) else object : View(svc) {
            val p = Paint(Paint.ANTI_ALIAS_FLAG)
            override fun onDraw(c: Canvas) {
                p.color = if (dragging) 0xCCFF8800.toInt() else 0xCC2196F3.toInt()
                c.drawCircle(width / 2f, height / 2f, width / 2f - 4, p)
                p.color = Color.WHITE
                c.drawCircle(width / 2f, height / 2f, 6f, p)
            }
        }
        cursorParams.width = cursorSize(); cursorParams.height = cursorSize()
        drawX = x; drawY = y
        wm.addView(v, cursorParams.also { place(it) }); OwnWindows.note(v)
        cursorView = v
    }

    fun hideCursor() {
        stop()
        Choreographer.getInstance().removeFrameCallback(joyFrame)
        joyBrackets(null)
        cursorView?.let { wm.removeView(it) }
        cursorView = null
    }

    /** The cursor has a position (shown once, or moved / restored). */
    var placed = false; private set

    /** Back to the centre (the joystick's recentre: a menu item, the debug op). */
    fun recentre() = moveTo(screenW() / 2f, screenH() / 2f)

    /** A rotation or a new screen size: the cursor keeps its coordinates, clamped into the new bounds. */
    fun clampCursor() {
        if (!placed) return
        x = x.coerceIn(0f, (screenW() - 1f).coerceAtLeast(0f)); y = y.coerceIn(0f, (screenH() - 1f).coerceAtLeast(0f))
        drawX = x; drawY = y
        cursorView?.let { wm.updateViewLayout(it, cursorParams.also { p -> place(p) }) }
    }

    // --- the voice joystick's cursor (Cursor B, JoyIndicators) ------------------------------------------------------

    private var joyArt: JoyIndicators.CursorArt? = null
    private var joyKey = "plain"
    private var drawX = 0f
    private var drawY = 0f
    private var joyLastFrame = 0L
    private var bracketView: View? = null
    private var bracketGrid: JoyIndicators.Grid? = null
    private val cellPx get() = joyArt?.cellPx(density) ?: 1

    private fun cursorSize() = joyArt?.let { (2 * it.r + 1) * it.cellPx(density) } ?: SIZE_PX

    /** Joystick cursor on (Cursor B, drawn from [art]) or off (the discrete cursor's dot). Keeps the position. */
    fun setJoystick(art: JoyIndicators.CursorArt?) {
        if ((art == null) == (joyArt == null)) return
        val shown = cursorView != null
        if (shown) hideCursor()
        joyArt = art; joyKey = "plain"
        if (shown) showCursor()
    }

    val joystick get() = joyArt != null

    /**
     * The joystick moved the cursor to ([nx], [ny]) px (clamped) and it looks like [key] ("plain", "neutral",
     * "E-2", ...). [x] / [y] (what a click taps) take the new point at once; the drawing follows it each frame
     * (about 25 ms behind: the ticks come in blocks), or jumps there when [jump] (the magnet, a recentre).
     */
    fun joyUpdate(nx: Float, ny: Float, key: String, jump: Boolean = false) {
        showCursor()
        x = nx.coerceIn(0f, (screenW() - 1f).coerceAtLeast(0f)); y = ny.coerceIn(0f, (screenH() - 1f).coerceAtLeast(0f))
        placed = true
        val redraw = key != joyKey
        joyKey = key
        description = when (key) { "plain" -> "stopped"; "neutral" -> "held"; else -> "moving ${key.substringBefore('-')}" }
        if (jump) { drawX = x; drawY = y; cursorView?.let { wm.updateViewLayout(it, cursorParams.also { p -> place(p) }) } }
        if (redraw) cursorView?.invalidate()
        if (drawX != x || drawY != y) {
            joyLastFrame = System.nanoTime()
            Choreographer.getInstance().removeFrameCallback(joyFrame)
            Choreographer.getInstance().postFrameCallback(joyFrame)
        }
    }

    private val joyFrame = object : Choreographer.FrameCallback {
        override fun doFrame(now: Long) {
            val dt = ((now - joyLastFrame) / 1e9f).coerceIn(0f, 0.1f)
            joyLastFrame = now
            val k = 1f - kotlin.math.exp(-dt / 0.025f)
            drawX += (x - drawX) * k; drawY += (y - drawY) * k
            if (kotlin.math.abs(x - drawX) < 0.5f && kotlin.math.abs(y - drawY) < 0.5f) { drawX = x; drawY = y }
            cursorView?.let { wm.updateViewLayout(it, cursorParams.also { p -> place(p) }) }
            if (drawX != x || drawY != y) Choreographer.getInstance().postFrameCallback(this)
        }
    }

    /** Snapped: corner brackets around [bounds] (device px: l, t, r, b), or none. */
    fun joyBrackets(bounds: IntArray?) {
        bracketView?.let { try { wm.removeView(it) } catch (_: Exception) {} }
        bracketView = null; bracketGrid = null
        val art = joyArt ?: return
        if (bounds == null) return
        val g = JoyIndicators.brackets(bounds[0], bounds[1], bounds[2], bounds[3], cellPx)
        bracketGrid = g
        val cell = cellPx
        val v = object : View(svc) {
            val p = Paint().apply { isAntiAlias = false }
            override fun onDraw(c: Canvas) = drawGrid(c, g, cell, art, p)
        }
        wm.addView(v, params(g.w * cell, g.h * cell).apply { gravity = Gravity.TOP or Gravity.START; x = g.x; y = g.y })
        OwnWindows.note(v)
        bracketView = v
    }

    private fun drawGrid(c: Canvas, g: JoyIndicators.Grid, cell: Int, art: JoyIndicators.CursorArt, p: Paint) {
        for (yy in 0 until g.h) for (xx in 0 until g.w) {
            val v = g[xx, yy]
            if (v == 0) continue
            p.color = if (v == 1) art.ink else art.paper
            c.drawRect((xx * cell).toFloat(), (yy * cell).toFloat(), ((xx + 1) * cell).toFloat(), ((yy + 1) * cell).toFloat(), p)
        }
    }

    private inner class JoyCursorView(val art: JoyIndicators.CursorArt) : View(svc) {
        val p = Paint().apply { isAntiAlias = false }
        override fun onDraw(c: Canvas) {
            val g = art.grids[joyKey] ?: art.grids.getValue("plain")
            drawGrid(c, g, art.cellPx(density), art, p)
        }
    }

    fun remove() {
        hideTargets()
        hideCursor()
        hideMenu()
        badge?.let { b -> hop?.let { b.view.removeCallbacks(it) }; try { wm.removeView(b.view) } catch (_: Exception) {} }
        badge = null; badgeParams = null; hop = null; tucked = false
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
        placed = true; drawX = x; drawY = y
        cursorView?.let { wm.updateViewLayout(it, cursorParams.also { p -> place(p) }) }
    }

    fun refresh() { cursorView?.invalidate(); description = if (vx == 0f && vy == 0f) (if (dragging) "dragging, stopped" else "stopped") else description }

    private fun place(p: WindowManager.LayoutParams) {
        val s = cursorSize()
        if (joyArt != null) { p.x = (drawX - s / 2).toInt(); p.y = (drawY - s / 2).toInt() }
        else { p.x = (x - s / 2).toInt(); p.y = (y - s / 2).toInt() }
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

    companion object {
        const val SIZE_PX = 64
        const val HOP_STEPS = 6
        const val HOP_FRAME_MS = 40L
    }
}

/**
 * Accessibility window ids of Canti's own overlay windows (head, menu, cursor, target highlights). A
 * TYPE_WINDOWS_CHANGED event carries no package, only a window id, so the [Confirmer] asks here to ignore the windows
 * Canti adds, moves or makes pass-through itself. An id is recorded when its view attaches (the accessibility window
 * id is set by then) and kept after it detaches, so the "removed" event of a window is recognised too; window ids are
 * not reused while the system runs.
 */
object OwnWindows {
    private val ids = java.util.Collections.synchronizedSet(HashSet<Int>())
    private val views = java.util.Collections.synchronizedList(ArrayList<java.lang.ref.WeakReference<View>>())

    /** Call right after WindowManager.addView(v). */
    fun note(v: View) {
        views.add(java.lang.ref.WeakReference(v))
        record(v)
        v.addOnAttachStateChangeListener(object : View.OnAttachStateChangeListener {
            override fun onViewAttachedToWindow(x: View) = record(x)
            override fun onViewDetachedFromWindow(x: View) {}
        })
    }

    fun contains(windowId: Int): Boolean {
        if (windowId < 0) return false
        if (windowId in ids) return true
        // not seen yet: read the live views again (cheap: a handful of windows)
        synchronized(views) {
            views.removeAll { it.get() == null }
            views.forEach { r -> r.get()?.let(::record) }
        }
        return windowId in ids
    }

    private fun record(v: View) {
        try {
            if (!v.isAttachedToWindow) return
            val n = v.createAccessibilityNodeInfo()
            n.windowId.takeIf { it >= 0 }?.let { ids.add(it) }
        } catch (_: Exception) {}
    }
}
