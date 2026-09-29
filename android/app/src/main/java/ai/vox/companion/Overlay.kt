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
import ai.vox.companion.audio.Measure
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
    /** The measurement prompt (Overlay.showPrompt): one large TextView near the top, auto-hidden. */
    private var promptView: View? = null
    private var promptHide: Runnable? = null
    private val prefs = svc.getSharedPreferences("canti_badge", Context.MODE_PRIVATE)
    private val density = svc.resources.displayMetrics.density
    private val pixelFont: Typeface = try { Typeface.createFromAsset(svc.assets, "flutter_assets/assets/fonts/PressStart2P-Regular.ttf") }
        catch (_: Exception) { Typeface.MONOSPACE }
    private val tinyFont: Typeface = try { Typeface.createFromAsset(svc.assets, "flutter_assets/assets/fonts/Tiny5-Regular.ttf") }
        catch (_: Exception) { Typeface.MONOSPACE }
    private var cursorView: View? = null
    private val cursorParams = params(SIZE_PX, SIZE_PX).apply { gravity = Gravity.TOP or Gravity.START }
    // [strip] the live transcript strip (TranscriptStrip.kt / TranscriptStripView.kt).
    private var stripView: TranscriptStripView? = null
    private var stripParams: WindowManager.LayoutParams? = null
    private var stripPalette: StripPalette = StripPalette.dark()
    private val stripHandler = android.os.Handler(android.os.Looper.getMainLooper())
    // [chain] Canti's own touchable rects (C4): remembered so a target under them stays visible to Targets/TreeReader.
    private val ownRects = OwnRects()
    private var queueView: View? = null

    private fun noteOwn() { ownRects.note(touchableRects(), SystemClock.elapsedRealtime()) }
    fun recentOwnRects(now: Long): List<Box> = ownRects.recent(now)

    // [chain] C5: while a Confirmer watch runs, Canti-initiated geometry changes (panel jump, queue resize, preview)
    // are queued and applied at unfreeze (newest wins); content redraws are allowed.
    private var frozenWatch: Long? = null
    private var freezeTask: Runnable? = null
    private var pendingJump: Boolean? = null

    fun freeze(watch: Long) {
        frozenWatch = watch
        freezeTask?.let { stripHandler.removeCallbacks(it) }
        val r = Runnable { unfreeze(watch) }   // 3 s safety
        freezeTask = r
        stripHandler.postDelayed(r, 3000)
    }

    fun unfreeze(watch: Long) {
        if (frozenWatch != watch) return
        frozenWatch = null
        freezeTask?.let { stripHandler.removeCallbacks(it) }; freezeTask = null
        pendingJump?.let { applyJump(it); pendingJump = null }
    }

    fun panelJump(on: Boolean) {
        if (frozenWatch != null) { pendingJump = on; return }
        applyJump(on)
    }

    private fun applyJump(on: Boolean) { jumped = on; placeStrip(); placeQueue() }   // [chain] C1 moves both windows
    private var jumped = false
    val isJumped: Boolean get() = jumped

    /** The queue window's y and height, or null while hidden (for the `chain_state` op). */
    fun queueGeometry(): IntArray? {
        val p = queueParams ?: return null
        if (queueView?.isAttachedToWindow != true) return null
        return intArrayOf(p.y, p.height)
    }

    /** Screen rects of Canti's touchable windows (badge, menu, strip, queue): the panel must never hide a target. */
    fun touchableRects(): List<Box> = listOfNotNull(badge?.view, menu, stripView, queueView).filter { it.isAttachedToWindow }.map { v ->
        val l = IntArray(2); v.getLocationOnScreen(l)
        Box(l[0], l[1], l[0] + v.width, l[1] + v.height)
    }

    /** The strip + queue rects (the panel) for the jump-to-top check (Y1). */
    fun panelRects(): List<Box> = listOfNotNull(stripView, queueView).filter { it.isAttachedToWindow }.map { v ->
        val l = IntArray(2); v.getLocationOnScreen(l)
        Box(l[0], l[1], l[0] + v.width, l[1] + v.height)
    }

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

    /** A touchable overlay window (the strip / queue): NOT_FOCUSABLE stays, NOT_TOUCHABLE drops. */
    private fun touchParams(w: Int, h: Int) = params(w, h).apply {
        flags = flags and WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE.inv()
    }

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
    /**
     * An injected gesture whose strokes start at [points] would land on a touchable Canti window (the head, the strip or
     * the queue). Each such window becomes NOT_TOUCHABLE for [ms] (the gesture's length + 400 ms), then restores; returns
     * true so the caller can wait a frame for the input windows to update before dispatching. One restore per window.
     */
    fun passThroughIfUnder(points: List<FloatArray>, ms: Long): Boolean {
        var any = false
        for ((view, p, panel) in touchableWindows()) {
            if (!view.isAttachedToWindow || !view.isShown) continue
            val l = IntArray(2); view.getLocationOnScreen(l)
            val hit = points.any { (x, y) -> x >= l[0] && x < l[0] + view.width && y >= l[1] && y < l[1] + view.height }
            if (!hit) continue
            if (!panel) hideMenu()   // a gesture passing through the head also closes its menu
            p.flags = p.flags or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
            wm.updateViewLayout(view, p)
            val restore = Runnable {
                if (view.isAttachedToWindow) {
                    p.flags = p.flags and WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE.inv()
                    wm.updateViewLayout(view, p)
                }
            }
            if (!panel) { view.removeCallbacks(restoreTouch); restoreTouch = restore }
            view.postDelayed(restore, ms)
            EventLog.ev(if (panel) "panel" else "badge", "event" to "pass-through", "ms" to ms)
            any = true
        }
        return any
    }

    private var restoreTouch: Runnable? = null

    /** The touchable Canti windows (badge, queue, title tab) with their params, and whether they are part of the panel. */
    private fun touchableWindows(): List<Triple<View, WindowManager.LayoutParams, Boolean>> {
        val out = ArrayList<Triple<View, WindowManager.LayoutParams, Boolean>>()
        badge?.view?.let { v -> badgeParams?.let { p -> if (!tucked) out += Triple(v, p, false) } }
        queueView?.let { v -> queueParams?.let { p -> out += Triple(v, p, true) } }
        tabView?.let { v -> tabParams?.let { p -> out += Triple(v, p, true) } }
        return out
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
        stripHandler.removeCallbacks(captureRestore)
        captureHidden = hide
        if (hide) {
            hideMenu()
            badge?.view?.let { it.visibility = View.INVISIBLE }
            stripView?.let { it.visibility = View.INVISIBLE }
            stripHandler.postDelayed(captureRestore, ms)
        } else {
            badge?.view?.let { it.visibility = if (tucked) View.INVISIBLE else View.VISIBLE }
            stripView?.let { it.visibility = View.VISIBLE }
        }
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
        if (ai.vox.companion.rec.DevRec.enabled) row("QUICK REC", false) { a.quickRec() }   // [rec]
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
    fun maskRects(): List<IntArray> = listOfNotNull(badge?.view, menu, cursorView, bracketView, stripView, queueView).filter { it.isAttachedToWindow && it.isShown }.map { v ->
        val l = IntArray(2); v.getLocationOnScreen(l)
        intArrayOf(l[0] - 32, l[1] - 32, l[0] + v.width + 32, l[1] + v.height + 32)
    }

    fun cursorVisible() = cursorView != null

    // --- intent cursor mode: numbered highlights on the candidate targets ----------------------------------------

    private var highlight: View? = null
    private var hlTargets: List<Target> = emptyList()
    private var hlSelected = 0

    /**
     * Full-screen, not touchable: each candidate drawn like the cursor mode's snap-to-element selection — the corner
     * brackets come from [JoyIndicators.brackets] and are drawn with [drawGrid], i.e. non-anti-aliased pixel cells with
     * the one-cell paper outline, not lines. The selected one uses the snap's ink brackets with the paper outline;
     * the others are paper-only brackets. Each has a number badge 1..N in the same pixel style (non-AA, the pixel font,
     * the ink/paper palette). The palette and cell size come from the joystick art when present, else the default
     * navy/mint at the default art's geometry ([JoyIndicators.Palette]), so the geometry matches the snap either way.
     */
    fun showTargets(targets: List<Target>, selected: Int) {
        hideTargets()
        hlTargets = targets; hlSelected = selected
        val pal = JoyIndicators.Palette.of(joyArt, density)
        val v = object : View(svc) {
            val p = Paint().apply { isAntiAlias = false }
            val fill = Paint().apply { isAntiAlias = false }
            val txt = Paint().apply { isAntiAlias = false; typeface = pixelFont; textAlign = Paint.Align.CENTER }
            val loc = IntArray(2)
            override fun onDraw(c: Canvas) {
                getLocationOnScreen(loc)
                hlTargets.forEachIndexed { i, t ->
                    val sel = i == hlSelected
                    val l = t.left - loc[0]; val tp = t.top - loc[1]
                    val r = t.right - loc[0]; val b = t.bottom - loc[1]
                    val g = JoyIndicators.brackets(l, tp, r, b, pal.cellPx)
                    // Selected = the snap's ink brackets with their paper outline; else paper-only brackets.
                    drawGrid(c, g, pal.cellPx, if (sel) pal.ink else pal.paper, pal.paper, p)
                    drawBadge(c, i + 1, l, tp, pal, sel)
                }
            }
            /** A filled pixel square (cell-aligned) at the target's top-left, with the 1-based number in the pixel font. */
            private fun drawBadge(c: Canvas, n: Int, l: Int, tp: Int, pal: JoyIndicators.Palette, sel: Boolean) {
                val side = 12 * pal.cellPx
                fill.color = if (sel) pal.ink else pal.paper
                c.drawRect(l.toFloat(), tp.toFloat(), (l + side).toFloat(), (tp + side).toFloat(), fill)
                txt.color = if (sel) pal.paper else pal.ink
                txt.textSize = 7 * pal.cellPx.toFloat()
                c.drawText("$n", l + side / 2f, tp + side / 2f + txt.textSize / 3f, txt)
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
            override fun onDraw(c: Canvas) = drawGrid(c, g, cell, art.ink, art.paper, p)
        }
        wm.addView(v, params(g.w * cell, g.h * cell).apply { gravity = Gravity.TOP or Gravity.START; x = g.x; y = g.y })
        OwnWindows.note(v)
        bracketView = v
    }

    private fun drawGrid(c: Canvas, g: JoyIndicators.Grid, cell: Int, ink: Int, paper: Int, p: Paint) {
        for (yy in 0 until g.h) for (xx in 0 until g.w) {
            val v = g[xx, yy]
            if (v == 0) continue
            p.color = if (v == 1) ink else paper
            c.drawRect((xx * cell).toFloat(), (yy * cell).toFloat(), ((xx + 1) * cell).toFloat(), ((yy + 1) * cell).toFloat(), p)
        }
    }

    private inner class JoyCursorView(val art: JoyIndicators.CursorArt) : View(svc) {
        val p = Paint().apply { isAntiAlias = false }
        override fun onDraw(c: Canvas) {
            val g = art.grids[joyKey] ?: art.grids.getValue("plain")
            drawGrid(c, g, art.cellPx(density), art.ink, art.paper, p)
        }
    }

    fun remove() {
        hideTargets()
        hideCursor()
        hideMenu()
        hidePrompt()
        hideStrip()
        badge?.let { b -> hop?.let { b.view.removeCallbacks(it) }; try { wm.removeView(b.view) } catch (_: Exception) {} }
        badge = null; badgeParams = null; hop = null; tucked = false
    }

    /**
     * The near-field measurement's prompt: large text (the gesture name + a counter) near the top, never covering the
     * centre, no sound or vibration. Not touchable, so dispatched gestures pass through; auto-hides after [ms].
     */
    fun showPrompt(text: String, ms: Long = Measure.PROMPT_VISIBLE_MS) {
        hidePrompt()
        val v = TextView(svc).apply {
            this.text = text
            typeface = Typeface.DEFAULT_BOLD
            textSize = 22f
            setTextColor(Color.WHITE)
            setBackgroundColor(0xCC000000.toInt())
            gravity = Gravity.CENTER
            setPadding((10 * density).toInt(), (4 * density).toInt(), (10 * density).toInt(), (4 * density).toInt())
        }
        val p = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT,
        ).apply { gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL; y = (screenH() * 0.08).toInt() }   // below the status bar / camera cutout
        wm.addView(v, p); OwnWindows.note(v)
        promptView = v
        val hide = Runnable { hidePrompt() }
        promptHide = hide
        v.postDelayed(hide, ms)
    }

    fun hidePrompt() {
        promptHide?.let { promptView?.removeCallbacks(it) }
        promptView?.let { try { wm.removeView(it) } catch (_: Exception) {} }
        promptView = null; promptHide = null
    }

    // --- the transcript strip (TranscriptStrip.kt / TranscriptStripView.kt) -----------------------------------------

    /** The night-mode palette; call again on configuration changes ([VoxService.onConfigurationChanged]). */
    private var stripNight = false
    fun stripThemeChanged() {
        val night = (svc.resources.configuration.uiMode and android.content.res.Configuration.UI_MODE_NIGHT_MASK) ==
            android.content.res.Configuration.UI_MODE_NIGHT_YES
        stripNight = night
        stripPalette = if (night) StripPalette.dark() else StripPalette.light()
        stripView?.let { it.palette = stripPalette; it.invalidate() }
    }

    /** The §9 scale: device pixels at a 1080-wide screen. */
    private fun stripScale() = (screenW() / 1080f).coerceAtLeast(0f)

    private fun stripBodyHeight(@Suppress("UNUSED_PARAMETER") row: Boolean): Int {   // fixed: the row slot is always reserved (no resize when it appears)
        val s = stripScale()
        val body = 32f + 60f * 2 + 72f + 24f
        return Math.round((body + 44f) * s)
    }

    fun showStrip(frame: StripFrame) {
        val v = stripView ?: TranscriptStripView(svc, tinyFont, pixelFont).also { stripView = it }
        v.palette = stripPalette
        v.frame = frame
        val p = stripParams ?: params(0, 0).apply { gravity = Gravity.TOP or Gravity.START }.also { stripParams = it }
        p.width = 0; p.height = 0   // recomputed by placeStrip below
        if (v.isAttachedToWindow) wm.updateViewLayout(v, placeStrip(p, frame))
        else {
            placeStrip(p, frame)
            try { wm.addView(v, p); OwnWindows.note(v) }
            catch (e: IllegalStateException) { wm.updateViewLayout(v, placeStrip(p, frame)) }   // already added (re-attach race)
        }
        noteOwn()   // [chain]
        showTitleTab()   // [chain] C6
    }

    fun updateStrip(frame: StripFrame) {
        val v = stripView ?: return
        v.frame = frame
        stripParams?.let { if (v.isAttachedToWindow) wm.updateViewLayout(v, placeStrip(it, frame)) }
    }

    fun hideStrip() {
        stripView?.let { try { wm.removeView(it) } catch (_: Exception) {} }
        stripView = null; stripParams = null
        hideQueue()   // [chain]
        hideTitleTab()   // [chain] C6
        hideBodyTouch()   // [chain] Y2: never leave the invisible scroll window behind
    }

    // [chain] C1: the queue window (ChainQueueView), right-aligned, stacked above the strip.
    private var queueParams: WindowManager.LayoutParams? = null

    fun showQueue(frame: QueueFrame) {
        val v = queueView as? ChainQueueView ?: ChainQueueView(svc, tinyFont, pixelFont).also { queueView = it }
        v.frame = frame
        v.paletteLight = !stripNight
        v.onTap = { onQueueTap?.invoke() }   // [chain] C6
        v.onScroll = { onQueueScroll?.invoke(it) }   // [chain] C6
        v.invalidate()   // [chain] a Frame redraw (updateViewLayout alone does not re-draw when the size is unchanged)
        val p = queueParams ?: touchParams(0, 0).apply { gravity = Gravity.TOP or Gravity.START }.also { queueParams = it }
        placeQueue()
        if (v.isAttachedToWindow) wm.updateViewLayout(v, p)
        else { try { wm.addView(v, p); OwnWindows.note(v) } catch (_: Exception) {} }
        noteOwn()
    }

    /** [chain] C6: the queue's tap (expand) and drag (scroll) callbacks, set by VoxService. */
    var onQueueTap: (() -> Unit)? = null
    var onQueueScroll: ((Float) -> Unit)? = null
    /** [chain] C6: the panel was dragged by the title tab; VoxService saves panel_top_<orientation>. */
    var onPanelMoved: (() -> Unit)? = null

    // [chain] C6: a small touchable window over the strip's title tab (the drag handle); the body stays NOT_TOUCHABLE.
    private var tabView: View? = null
    private var tabParams: WindowManager.LayoutParams? = null

    fun showTitleTab() {
        val sp = stripParams ?: return
        val s = stripScale()
        val v = tabView ?: View(svc).also { tabView = it }
        val p = tabParams ?: touchParams(0, 0).apply { gravity = Gravity.TOP or Gravity.START }.also { tabParams = it }
        p.width = Math.round(320f * s); p.height = Math.round(52f * s)
        p.x = sp.x + Math.round(24f * s); p.y = sp.y
        v.setOnTouchListener { _, e ->
            when (e.actionMasked) {
                android.view.MotionEvent.ACTION_DOWN -> { downTabY = e.rawY; downPanelY = sp.y; true }
                android.view.MotionEvent.ACTION_MOVE -> { movePanel(downPanelY + Math.round(e.rawY - downTabY)); true }
                android.view.MotionEvent.ACTION_UP -> { onPanelMoved?.invoke(); true }
                else -> false
            }
        }
        if (v.isAttachedToWindow) wm.updateViewLayout(v, p)
        else { try { wm.addView(v, p); OwnWindows.note(v) } catch (_: Exception) {} }
    }

    private var downTabY = 0f
    private var downPanelY = 0

    private fun movePanel(top: Int) {
        val clamped = top.coerceIn(statusBarTop(), screenH() - 80)
        stripParams?.let { it.y = clamped; if (stripView?.isAttachedToWindow == true) wm.updateViewLayout(stripView!!, it) }
        tabParams?.let { it.y = clamped; if (tabView?.isAttachedToWindow == true) wm.updateViewLayout(tabView!!, it) }
        placeQueue()
        if (bodyView != null) showBodyTouch(true)   // [chain] the scroll window follows the drag
    }

    fun hideTitleTab() {
        tabView?.let { try { wm.removeView(it) } catch (_: Exception) {} }
        tabView = null; tabParams = null
    }

    /** [chain] C6/Y2: a touchable window over the strip body, shown only while the transcript overflows (scrollable). */
    var onBodyScroll: ((Float) -> Unit)? = null
    private var bodyView: View? = null
    private var bodyParams: WindowManager.LayoutParams? = null

    fun showBodyTouch(scrollable: Boolean) {
        if (!scrollable) { hideBodyTouch(); return }
        val sp = stripParams ?: return
        val s = stripScale()
        val v = bodyView ?: View(svc).also { bodyView = it }
        val p = bodyParams ?: touchParams(0, 0).apply { gravity = Gravity.TOP or Gravity.START }.also { bodyParams = it }
        p.width = sp.width
        p.height = Math.round((stripBodyHeight(true) - 52f) * s).coerceAtLeast(1)
        p.x = sp.x; p.y = sp.y + Math.round(52f * s)
        var downY = 0f
        v.setOnTouchListener { _, e ->
            when (e.actionMasked) {
                android.view.MotionEvent.ACTION_DOWN -> { downY = e.rawY; true }
                android.view.MotionEvent.ACTION_MOVE -> { onBodyScroll?.invoke(e.rawY - downY); downY = e.rawY; true }
                android.view.MotionEvent.ACTION_UP -> true
                else -> false
            }
        }
        if (v.isAttachedToWindow) wm.updateViewLayout(v, p)
        else { try { wm.addView(v, p); OwnWindows.note(v) } catch (_: Exception) {} }
    }

    fun hideBodyTouch() {
        bodyView?.let { try { wm.removeView(it) } catch (_: Exception) {} }
        bodyView = null; bodyParams = null
    }

    /** Recompute the queue window's height and y (stacked above the strip's tabs), for a jump / return. */
    private fun placeQueue() {
        val v = queueView as? ChainQueueView ?: return
        val p = queueParams ?: return
        val frame = v.frame ?: return
        val s = stripScale()
        val rows = frame.rows.size
        val chips = (if (frame.doneAbove > 0) 1 else 0) + (if (frame.moreBelow > 0) 1 else 0)
        val h = Math.round((rows * ChainViewLayout.rowHeight(s) + chips * (ChainViewLayout.chipHeight(s) + 12f * s) + 10f * s))
        p.height = h.coerceAtLeast(1)
        // [chain] Y3: size the window to the drawn blocks+chips (right-aligned); the left dead area is at most the pad.
        val cw = v.contentWidth(s)
        p.width = Math.round(cw + 40f * s).coerceAtLeast(1)
        p.x = (screenW() - p.width).coerceAtLeast(0)
        val stripTop = stripParams?.y ?: stripTop(stripBodyHeight(false))
        p.y = (stripTop - h).coerceAtLeast(0)
    }

    fun hideQueue() {
        queueView?.let { try { wm.removeView(it) } catch (_: Exception) {} }
        queueView = null; queueParams = null
    }

    /** The queue view's last drawn frame (for the `chain_state` "drawn" diagnostic), or null. */
    fun queueFrame(): QueueFrame? = (queueView as? ChainQueueView)?.frame

    // [chain] C2: the NOW/NEXT preview — orange double outline + a flag above each rect, in NOT_TOUCHABLE windows.
    private var previewView: View? = null
    private var previewNow: Target? = null
    private var previewNext: Target? = null

    fun showPreview(now: Target?, next: Target?) {
        hidePreview()
        if (now == null && next == null) return
        previewNow = now; previewNext = next
        val v = object : View(svc) {
            val p = Paint().apply { isAntiAlias = false; color = 0xFFF2A33A.toInt() }
            val flag = Paint().apply { isAntiAlias = false; typeface = pixelFont; color = 0xFF1D2757.toInt(); textAlign = Paint.Align.CENTER }
            val loc = IntArray(2)
            override fun onDraw(c: Canvas) {
                getLocationOnScreen(loc)
                val entries = ArrayList<Pair<Target, String>>()
                now?.let { entries += it to "NOW" }
                next?.let { entries += it to "NEXT" }
                for ((t, label) in entries) {
                    val l = t.left - loc[0]; val tp = t.top - loc[1]; val r = t.right - loc[0]; val b = t.bottom - loc[1]
                    p.style = Paint.Style.STROKE
                    p.strokeWidth = 4f; c.drawRect(l.toFloat(), tp.toFloat(), r.toFloat(), b.toFloat(), p)
                    c.drawRect((l - 8).toFloat(), (tp - 8).toFloat(), (r + 8).toFloat(), (b + 8).toFloat(), p)
                    flag.textSize = 28f
                    val fw = (r - l).coerceAtLeast(60)
                    p.style = Paint.Style.FILL
                    c.drawRect(l.toFloat(), tp - 44f, (l + fw).toFloat(), tp.toFloat(), p)
                    c.drawText(label, (l + fw / 2).toFloat(), tp - 14f, flag)
                }
            }
        }
        wm.addView(v, params(WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.MATCH_PARENT))
        previewView = v
    }

    fun hidePreview() {
        previewView?.let { try { wm.removeView(it) } catch (_: Exception) {} }
        previewView = null; previewNow = null; previewNext = null
    }

    /** [strip] The strip window's current y and height, or null while hidden (for the `strip_state` op). */
    fun stripGeometry(): IntArray? {
        val p = stripParams ?: return null
        if (stripView?.isAttachedToWindow != true) return null
        return intArrayOf(p.y, p.height)
    }

    /** Re-place the strip (a window / focus change, or a rotation); no-op while it is hidden. */
    fun placeStrip() {
        val v = stripView ?: return
        val f = v.frame ?: return
        stripParams?.let { if (v.isAttachedToWindow) wm.updateViewLayout(v, placeStrip(it, f)) }
        // [chain] the touch windows follow the strip (a jump would otherwise leave them eating touches at the old spot)
        if (tabView != null) showTitleTab()
        if (bodyView != null) showBodyTouch(true)
    }

    private fun placeStrip(p: WindowManager.LayoutParams, frame: StripFrame): WindowManager.LayoutParams {
        val s = stripScale()
        val gut = Math.round(16f * s)
        p.x = gut
        p.width = (screenW() - 2 * gut).coerceAtLeast(1)
        p.height = stripBodyHeight(frame.row != null)
        p.y = stripTop(p.height)
        return p
    }

    /** The strip window's top y from the screen geometry and the focused editable field (see VoxService.placeStrip). */
    private fun stripTop(stripH: Int): Int {
        val navBottom = screenH() - navBarBottom()
        val statusTop = statusBarTop()
        val imeTop = imeTop()
        val field = focusedFieldRect()
        return PanelPlace.top(screenH(), navBottom, statusTop, stripH, imeTop, field, panelTop, jumped)   // [chain] C1
    }

    /** [chain] C1: the saved panel top (px, -1 = default) per orientation, set by VoxService. */
    var panelTop: Int? = null

    private fun navBarBottom(): Int = try {
        wm.currentWindowMetrics.windowInsets.getInsets(android.view.WindowInsets.Type.navigationBars()).bottom
    } catch (_: Exception) { 0 }

    private fun statusBarTop(): Int = try {
        wm.currentWindowMetrics.windowInsets.getInsets(android.view.WindowInsets.Type.statusBars()).top
    } catch (_: Exception) { 0 }

    private fun imeTop(): Int? = try {
        val r = android.graphics.Rect()
        val w = svc.windows.firstOrNull { it.type == android.view.accessibility.AccessibilityWindowInfo.TYPE_INPUT_METHOD }
        if (w == null) null else { w.getBoundsInScreen(r); r.top }
    } catch (_: Exception) { null }

    private fun focusedFieldRect(): IntArray? {
        return try {
            val n = svc.findFocus(android.view.accessibility.AccessibilityNodeInfo.FOCUS_INPUT) ?: return null
            if (!n.isEditable) return null
            val r = android.graphics.Rect(); n.getBoundsInScreen(r)
            intArrayOf(r.left, r.top, r.right, r.bottom)
        } catch (_: Exception) { null }
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
