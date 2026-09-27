package ai.vox.companion

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Rect
import android.graphics.Region
import android.os.Build
import android.os.SystemClock
import android.view.MotionEvent
import android.view.View
import org.json.JSONObject
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * The badge's pixel Canti (brand/tools/canti_sprite.py makes ui/assets/badge/canti_badge.png + .json: one copy, the Flutter
 * module's, which the APK carries under flutter_assets/; the app header plays the same sheet).
 *
 * Pixel-exact: every art pixel is n x n device pixels, n = round(density x the manifest's artPxDp) (3 px at 2.625x
 * for the 38-px-head sheet: the stipple icon's dot; [BadgeSprite.pixelsPerArtPx]); a manifest without artPxDp gets the
 * largest whole n that fits [targetDp] ([BadgeSprite.scaleFor]). Frames are drawn nearest-neighbour (no filtering) at whole-pixel positions. The sheet
 * is loaded from assets, never res/drawable-*dpi, which Android rescales by a fraction on in-between densities.
 *
 * Cheap: frames are sliced once; a single Runnable is posted for the moment the frame next changes (no per-vsync
 * callback, no allocation per frame), only while the view is attached and visible. With the system's animations
 * turned off (animator duration scale 0) it shows each state's still frame and doesn't tick.
 */
class CantiBadgeView(ctx: Context, targetDp: Float = DEFAULT_DP) : View(ctx), BadgeFace {
    private val sprite = BadgeSprite.parse(ctx.assets.open(MANIFEST).bufferedReader().use { it.readText() })
    private val frames: Array<Bitmap> = ctx.assets.open(sprite.sheet).use { input ->
        val sheet = BitmapFactory.decodeStream(input, null, BitmapFactory.Options().apply { inScaled = false })
            ?: error("can't decode ${sprite.sheet}")
        val out = Array(sprite.frameCount) { i ->
            Bitmap.createBitmap(sheet, sprite.frameX(i), sprite.frameY(i), sprite.frameW, sprite.frameH)
        }
        sheet.recycle()
        out
    }
    /** Per frame, which art pixels are drawn: the badge is only its drawn pixels, for taps as well as for eyes. */
    private val masks: Array<BadgeHitMask> = BadgeHitMask.shared(Array(frames.size) { i ->
        val b = frames[i]
        val px = IntArray(b.width * b.height)
        b.getPixels(px, 0, b.width, 0, 0, b.width, b.height)
        BadgeHitMask.of(px, b.width, b.height)
    })
    private val regions = HashMap<BadgeHitMask, Region>()
    private var regionMask: BadgeHitMask? = null
    private var drawn = 0   // the frame on screen: taps are tested against what the user sees
    private val player = BadgePlayer(sprite)
    val scale = ctx.resources.displayMetrics.density.let { d ->
        if (sprite.artPxDp > 0f) BadgeSprite.pixelsPerArtPx(d, sprite.artPxDp)
        else BadgeSprite.scaleFor(targetDp * d, sprite.frameW, sprite.frameH)
    }
    private val dst = Rect(0, 0, sprite.frameW * scale, sprite.frameH * scale)
    private val paint = Paint().apply { isFilterBitmap = false; isAntiAlias = false; isDither = false }
    private var visible = false
    private val tick = Runnable { invalidate(); schedule() }

    override val view: View get() = this

    init {
        player.setHeld(BadgeState.IDLE, SystemClock.uptimeMillis())
        describe()
    }

    override fun setState(s: BadgeState) {
        player.reduceMotion = !ValueAnimator.areAnimatorsEnabled()
        if (player.setHeld(s, SystemClock.uptimeMillis())) changed()
    }

    override fun setJoy(state: String?) {
        if (player.setJoy(state)) changed()
    }

    override fun playOnce(s: BadgeState) {
        player.reduceMotion = !ValueAnimator.areAnimatorsEnabled()
        player.playOnce(s, SystemClock.uptimeMillis())
        changed()
    }

    private fun changed() { describe(); invalidate(); schedule() }

    private fun describe() { contentDescription = "Canti: ${BadgeStates.label(player.showing)}" }

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) = setMeasuredDimension(dst.width(), dst.height())

    override fun onDraw(canvas: Canvas) {
        val now = SystemClock.uptimeMillis()
        val shotBefore = player.showing
        drawn = player.frameAt(now)
        canvas.drawBitmap(frames[drawn], null, dst, paint)
        touchOnlyDrawnPixels(masks[drawn])
        if (player.showing != shotBefore) describe()   // a one-shot just ended
    }

    /** Post [tick] for the next frame change, or nothing (a still frame, or not visible). */
    private fun schedule() {
        removeCallbacks(tick)
        if (!visible || !isAttachedToWindow) return
        val wait = player.nextChangeIn(SystemClock.uptimeMillis())
        if (wait >= 0) postDelayed(tick, max(1L, wait))
    }

    override fun onVisibilityAggregated(isVisible: Boolean) {
        super.onVisibilityAggregated(isVisible)
        visible = isVisible
        if (isVisible) {
            player.reduceMotion = !ValueAnimator.areAnimatorsEnabled()
            invalidate()
        }
        schedule()
    }

    /**
     * Taps on the transparent pixels around Canti (between the arms, beside the antenna, where a pointing arm was)
     * belong to the app underneath. From Android 14 the window's touchable region is set to the frame's drawn pixels,
     * so the system delivers those taps below. Updated only when the silhouette changes (frames that differ only in
     * the face share a mask). On Android 11-13 there is no public way to do that; the window keeps its rectangle, and
     * [dispatchTouchEvent] at least ignores touches that start on a transparent pixel (no drag, no menu).
     */
    private fun touchOnlyDrawnPixels(mask: BadgeHitMask) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.UPSIDE_DOWN_CAKE || mask === regionMask) return
        val sc = rootSurfaceControl ?: return
        regionMask = mask
        sc.setTouchableRegion(regions.getOrPut(mask) {
            Region().apply { for (r in mask.rects) union(Rect(r[0] * scale, r[1] * scale, r[2] * scale, r[3] * scale)) }
        })
    }

    override fun dispatchTouchEvent(e: MotionEvent): Boolean {
        if (e.actionMasked == MotionEvent.ACTION_DOWN &&
            !masks[drawn].hit((e.x / scale).toInt(), (e.y / scale).toInt())) return false
        return super.dispatchTouchEvent(e)
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        regionMask = null   // a new window surface: set its region again on the next draw
    }

    override fun onDetachedFromWindow() {
        removeCallbacks(tick)
        super.onDetachedFromWindow()
    }

    companion object {
        const val MANIFEST = "flutter_assets/assets/badge/canti_badge.json"
        /** Only for a manifest without artPxDp: the box the badge must fit. */
        const val DEFAULT_DP = 76f
    }
}

/** canti_badge.json: the sheet's frame grid and, per state, frame indices, ms per frame, loop, and a still frame. */
class BadgeSprite(
    val sheet: String,
    val frameW: Int,
    val frameH: Int,
    val columns: Int,
    val frameCount: Int,
    val anims: Map<String, Anim>,
    /** dp per art pixel (0 = not given: fit a box instead). */
    val artPxDp: Float = 0f,
) {
    class Anim(val name: String, val loop: Boolean, val frames: IntArray, val ms: IntArray, val still: Int) {
        val totalMs: Long = ms.fold(0L) { a, b -> a + b }
    }

    fun frameX(i: Int) = (i % columns) * frameW
    fun frameY(i: Int) = (i / columns) * frameH

    companion object {
        fun parse(json: String): BadgeSprite {
            val o = JSONObject(json)
            val dir = MANIFEST_DIR
            val fw = o.getInt("frameWidth"); val fh = o.getInt("frameHeight")
            val n = o.getInt("frameCount")
            val st = o.getJSONObject("states")
            val anims = HashMap<String, Anim>()
            for (name in st.keys()) {
                val a = st.getJSONObject(name)
                val fr = a.getJSONArray("frames"); val ms = a.getJSONArray("ms")
                require(fr.length() > 0 && fr.length() == ms.length()) { "badge state $name: frames/ms mismatch" }
                val frames = IntArray(fr.length()) { fr.getInt(it) }
                val durs = IntArray(ms.length()) { ms.getInt(it) }
                require(frames.all { it in 0 until n }) { "badge state $name: frame out of range" }
                require(durs.all { it > 0 }) { "badge state $name: ms must be > 0" }
                val still = a.optInt("still", 0)
                require(still in frames.indices) { "badge state $name: still out of range" }
                anims[name] = Anim(name, a.getBoolean("loop"), frames, durs, still)
            }
            require("idle" in anims) { "badge manifest has no idle state" }
            val artPxDp = o.optDouble("artPxDp", 0.0).toFloat()
            require(artPxDp >= 0f) { "badge manifest: artPxDp must be >= 0" }
            return BadgeSprite(dir + o.getString("sheet"), fw, fh, o.getInt("columns"), n, anims, artPxDp)
        }

        private const val MANIFEST_DIR = "flutter_assets/assets/badge/"

        /** The largest whole art-pixel size (>= 1) at which a fw x fh frame fits a targetPx square. */
        fun scaleFor(targetPx: Float, fw: Int, fh: Int): Int = max(1, floor(min(targetPx / fw, targetPx / fh)).toInt())

        /** Device px per art px: the whole number nearest density x artPxDp, at least 1 (so the badge keeps about the same
         *  size in dp on every screen: 2.625x -> 3, 3x -> 3, 2x -> 2, 3.5x -> 4, 4x -> 5 for artPxDp = 8/7). */
        fun pixelsPerArtPx(density: Float, artPxDp: Float): Int = max(1, (density * artPxDp).roundToInt())
    }
}

/**
 * Which frame to show when: a held state (looping, or holding its last frame) and at most one one-shot over it,
 * which returns to the held state when done. Pure; times are any monotonic ms clock.
 */
class BadgePlayer(private val sprite: BadgeSprite) {
    /** Show still frames: a held state's still frame, and a one-shot's still frame for the one-shot's length. */
    var reduceMotion = false

    var held = BadgeState.IDLE; private set
    private var heldAnim = sprite.anims.getValue("idle")
    private var heldStart = 0L
    private var started = false
    private var shot: BadgeState? = null
    private var shotAnim: BadgeSprite.Anim? = null
    private var shotStart = 0L
    /** The direction of the last scroll one-shot; HOLD_SCROLL plays hold_scroll_up / _down after it. */
    private var lastScrollUp = true

    private var joyAnim: BadgeSprite.Anim? = null

    /** Face A (voice joystick): a named manifest state's still frame, shown instead of the held state (one-shots play
     *  over it); null or an unknown name = off. Returns true if it changed. */
    fun setJoy(name: String?): Boolean {
        val a = name?.let { sprite.anims[it] }
        if (a === joyAnim) return false
        joyAnim = a
        return true
    }

    /** What is on screen: the one-shot while it plays, else the held state. */
    val showing: BadgeState get() = shot ?: held

    /** Hold [s]; returns false if it already was held (its loop is not restarted). */
    fun setHeld(s: BadgeState, now: Long): Boolean {
        if (s == held && started) return false
        started = true
        held = s
        heldAnim = anim(s, once = false)
        heldStart = now
        return true
    }

    fun playOnce(s: BadgeState, now: Long) {
        if (s == BadgeState.SCROLL_UP) lastScrollUp = true
        if (s == BadgeState.SCROLL_DOWN) lastScrollUp = false
        if (held == BadgeState.HOLD_SCROLL) heldAnim = anim(held, once = false)
        shot = s
        shotAnim = anim(s, once = true)
        shotStart = now
    }

    /** The sheet frame index to draw at [now] (ends a finished one-shot). */
    fun frameAt(now: Long): Int {
        expire(now)
        val sa = shotAnim
        if (sa != null) return index(sa, now - shotStart, loop = false)
        joyAnim?.let { return it.frames[it.still] }
        return index(heldAnim, now - heldStart, heldAnim.loop)
    }

    /** ms from [now] until the frame changes, or -1 if it never will without a new state. */
    fun nextChangeIn(now: Long): Long {
        expire(now)
        val sa = shotAnim
        if (sa != null) {
            val t = now - shotStart
            return if (reduceMotion) sa.totalMs - t else untilNext(sa, t, loop = false).coerceAtMost(sa.totalMs - t)
        }
        if (joyAnim != null || reduceMotion || heldAnim.frames.size == 1) return -1
        return untilNext(heldAnim, now - heldStart, heldAnim.loop)
    }

    private fun expire(now: Long) {
        val sa = shotAnim ?: return
        if (now - shotStart >= sa.totalMs) {
            heldStart = shotStart + sa.totalMs     // the held loop starts over where the one-shot ended
            shot = null; shotAnim = null
        }
    }

    private fun index(a: BadgeSprite.Anim, elapsed: Long, loop: Boolean): Int {
        if (reduceMotion) return a.frames[a.still]
        var t = if (loop) elapsed % a.totalMs else elapsed
        for (i in a.ms.indices) {
            if (t < a.ms[i]) return a.frames[i]
            t -= a.ms[i]
        }
        return a.frames[a.still]                     // a one-shot used as a held state rests on its still frame
    }

    private fun untilNext(a: BadgeSprite.Anim, elapsed: Long, loop: Boolean): Long {
        if (!loop && elapsed >= a.totalMs) return -1
        var t = if (loop) elapsed % a.totalMs else elapsed
        for (i in a.ms.indices) {
            if (t < a.ms[i]) return a.ms[i] - t
            t -= a.ms[i]
        }
        return -1
    }

    /** Manifest entry for a state: "<name>_once" for one-shots when present; HOLD_SCROLL by the last scroll. */
    private fun anim(s: BadgeState, once: Boolean): BadgeSprite.Anim {
        val base = when (s) {
            BadgeState.HOLD_SCROLL -> if (lastScrollUp) "hold_scroll_up" else "hold_scroll_down"
            else -> s.name.lowercase()
        }
        val a = sprite.anims
        return (if (once) a[base + "_once"] else null) ?: a[base] ?: a.getValue("idle")
    }

    companion object {
        /** The manifest names every BadgeState resolves to (for tests / checks). */
        fun namesFor(s: BadgeState): List<String> = when (s) {
            BadgeState.HOLD_SCROLL -> listOf("hold_scroll_up", "hold_scroll_down")
            BadgeState.IGNORED -> listOf("ignored_once")   // one-shot only: no held loop
            else -> listOf(s.name.lowercase())
        }
    }
}

/**
 * Which art pixels of one frame are drawn (alpha > 0): [hit] for a single pixel, [rects] = the same pixels as a few
 * rectangles [left, top, right, bottom) in art px (each row's opaque runs, merged down while the next row repeats them).
 * Equal masks compare equal, so frames that differ only in colour share one.
 */
class BadgeHitMask private constructor(val w: Int, val h: Int, private val opaque: BooleanArray) {
    fun hit(x: Int, y: Int): Boolean = x in 0 until w && y in 0 until h && opaque[y * w + x]

    val rects: List<IntArray> by lazy {
        val out = ArrayList<IntArray>()
        var open = ArrayList<IntArray>()          // rects still growing down: their runs match the previous row
        for (y in 0 until h) {
            val runs = ArrayList<IntArray>()
            var x = 0
            while (x < w) {
                if (!opaque[y * w + x]) { x++; continue }
                val x0 = x
                while (x < w && opaque[y * w + x]) x++
                runs.add(intArrayOf(x0, x))
            }
            val next = ArrayList<IntArray>()
            for (r in runs) {
                val same = open.firstOrNull { it[0] == r[0] && it[2] == r[1] }
                if (same != null) { same[3] = y + 1; next.add(same) }
                else { val n = intArrayOf(r[0], y, r[1], y + 1); out.add(n); next.add(n) }
            }
            open = next
        }
        out
    }

    override fun equals(other: Any?) = other is BadgeHitMask && w == other.w && h == other.h && opaque.contentEquals(other.opaque)
    override fun hashCode() = 31 * (31 * w + h) + opaque.contentHashCode()

    companion object {
        /** From ARGB pixels (row-major, [w] x [h]). */
        fun of(argb: IntArray, w: Int, h: Int): BadgeHitMask {
            require(argb.size == w * h) { "badge mask: ${argb.size} pixels for $w x $h" }
            return BadgeHitMask(w, h, BooleanArray(argb.size) { (argb[it] ushr 24) != 0 })
        }

        /** The same masks, with equal ones replaced by one shared instance. */
        fun shared(masks: Array<BadgeHitMask>): Array<BadgeHitMask> {
            val seen = HashMap<BadgeHitMask, BadgeHitMask>()
            return Array(masks.size) { seen.getOrPut(masks[it]) { masks[it] } }
        }
    }
}
