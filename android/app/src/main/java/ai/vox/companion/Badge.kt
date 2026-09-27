package ai.vox.companion

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Rect
import android.graphics.Typeface
import android.view.View
import kotlin.math.max
import kotlin.math.roundToInt

/**
 * What the floating Canti head shows. Held states last until the service's state changes; one-shots
 * ([BadgeState.oneShot]) play once over the held state (an executed action, a sound heard but not acted on) and then
 * return to it.
 */
enum class BadgeState {
    IDLE, HEARING, PENDING, SCROLL_UP, SCROLL_DOWN, HOLD_SCROLL, BACK, FORWARD, HOME, CURSOR, PAUSED, OFF, ERROR,
    /** The Pico is connected but paused itself after a link drop (DeviceLink.wakeable): a tap on the head wakes it.
     *  Its loop: drowsy eyes, then TAP on the face screen (canti_sprite.py `tap_to_wake`). */
    TAP_TO_WAKE,
    /** A sound heard but not acted on (a `none` decision): a brief shrug, one-shot only, rate-limited ([IgnoredGate]). */
    IGNORED;

    val oneShot get() = this in ONE_SHOTS

    companion object {
        val ONE_SHOTS = setOf(HEARING, SCROLL_UP, SCROLL_DOWN, BACK, FORWARD, HOME, ERROR, IGNORED)
    }
}

/**
 * The head's face: the overlay owns the window, drag and menu; the face only draws. [create] is the one line to change
 * to swap in the animated sprite view (CantiBadgeView). A face animates only while [view] is attached and visible,
 * and does not redraw while idle except for its own blink.
 */
interface BadgeFace {
    val view: View
    /** The held state (idle, hearing, pending, hold-scroll, cursor, paused, off, error). */
    fun setState(s: BadgeState)
    /** A one-shot over the held state (scroll up/down, back, forward, home, hearing, ignored, error). */
    fun playOnce(s: BadgeState)
    /** The voice joystick's Face A: a named still frame of the manifest (joy_*, [ai.vox.companion.joystick.JoyIndicators.faceState])
     *  shown instead of the held state while not null; one-shots still play over it. */
    fun setJoy(state: String?) {}

    companion object {
        /** The sprite head (CantiBadgeView); the static placeholder if its assets can't be loaded. */
        fun create(ctx: Context): BadgeFace = try { CantiBadgeView(ctx) } catch (e: Exception) {
            EventLog.ev("error", "where" to "badge sprite", "error" to e.toString()); PlaceholderFace(ctx)
        }
    }
}

/** Service state -> the face's held state, and executed actions -> one-shots. Pure (JVM-tested in BadgeTest). */
object BadgeStates {
    data class Inputs(
        val armed: Boolean,
        val paused: Boolean,
        val mode: String,            // gesture | cursor | listening
        val holdScrolling: Boolean,
        val pending: Boolean,        // a sound group waiting, a decision in flight, or a confirm/choice open
        val listening: Boolean,      // the phrase window is open
        val sourceError: Boolean,    // the sound source reports an error (mic error, BLE link error)
        val wakeable: Boolean = false,   // the Pico is connected and paused only by a link drop (DeviceLink.wakeable)
        val mediaUnlocked: Boolean = false,  // a media-gate unlock window is open (MediaGate): the pending face, no new art
    )

    fun held(i: Inputs): BadgeState = when {
        // A link-drop pause asks for a tap; an app-side Pause the user chose on top of it keeps the plain OFF.
        !i.armed -> if (i.wakeable && !i.paused) BadgeState.TAP_TO_WAKE else BadgeState.OFF
        i.paused -> BadgeState.PAUSED
        i.sourceError -> BadgeState.ERROR
        i.holdScrolling -> BadgeState.HOLD_SCROLL
        i.listening -> BadgeState.HEARING
        i.pending || i.mediaUnlocked -> BadgeState.PENDING
        i.mode == "cursor" -> BadgeState.CURSOR
        else -> BadgeState.IDLE
    }

    /** The one-shot for an executed action; null = none (the held state stays). A failed action is [BadgeState.ERROR]. */
    fun forAction(action: String, ok: Boolean): BadgeState? = when {
        action == "none" -> null
        !ok -> BadgeState.ERROR
        else -> when (action) {
            "swipe_up" -> BadgeState.SCROLL_UP        // rise: the content moves up (next item)
            "swipe_down" -> BadgeState.SCROLL_DOWN    // fall: the content moves down (previous item)
            "back" -> BadgeState.BACK
            "forward" -> BadgeState.FORWARD
            "home" -> BadgeState.HOME
            else -> null
        }
    }

    /** The one-shot for a decision the service performed: [forAction]'s, or [BadgeState.IGNORED] for `none` (a sound
     *  heard, nothing done). The caller rate-limits IGNORED with an [IgnoredGate]. */
    fun forDecision(action: String, ok: Boolean): BadgeState? =
        if (action == "none") BadgeState.IGNORED else forAction(action, ok)

    /** Short text for the accessibility description and the status map. */
    fun label(s: BadgeState) = s.name.lowercase().replace('_', '-')

    /** What a touch on the head does ([Overlay]'s touch listener; a drag always moves it). */
    enum class Touch { WAKE, MENU }

    /** A tap wakes a Pico that sits paused after a link drop; otherwise it opens (or closes) the menu. */
    fun onTap(wakeable: Boolean) = if (wakeable) Touch.WAKE else Touch.MENU

    /** A long-press always opens the menu, so mode, pause and source stay reachable in every state. */
    fun onLongPress() = Touch.MENU
}

/**
 * At most one [BadgeState.IGNORED] per [gapMs]: with a video playing, every sound would otherwise shrug. No queueing: a
 * `none` less than [gapMs] after the last shrug that played is dropped (the dropped ones don't restart the wait).
 */
class IgnoredGate(private val gapMs: Long = GAP_MS) {
    private var last: Long? = null

    /** True (and counted as played) if a shrug may play at [now] (any monotonic ms clock). */
    fun admit(now: Long): Boolean {
        val l = last
        if (l != null && now - l < gapMs) return false
        last = now
        return true
    }

    companion object { const val GAP_MS = 2500L }
}

/**
 * Placeholder face until the sprite view lands: the static stipple icon (Flutter's brand asset, 48 px) drawn
 * pixel-exact at an integer scale, with the state's name in a strip under it. One-shots show for [ONE_SHOT_MS].
 */
class PlaceholderFace(private val ctx: Context) : BadgeFace {
    private val density = ctx.resources.displayMetrics.density
    private val scale = max(1, (density * 36f / 48f).roundToInt())
    private val on = load("canti-icon-on@1.png")
    private val off = load("canti-icon-off@1.png")
    private var held = BadgeState.IDLE
    private var shot: BadgeState? = null
    private val clearShot = Runnable { shot = null; view.invalidate(); describe() }

    private fun load(name: String): Bitmap? = try {
        ctx.assets.open("flutter_assets/assets/brand/$name").use { BitmapFactory.decodeStream(it) }
    } catch (_: Exception) { null }

    override val view: View = object : View(ctx) {
        val px = Paint().apply { isFilterBitmap = false; isAntiAlias = false; isDither = false }
        val strip = Paint().apply { color = Color.BLACK }
        val txt = Paint().apply { color = Color.WHITE; typeface = Typeface.MONOSPACE; isAntiAlias = false; textAlign = Paint.Align.CENTER
            textSize = (5 * scale).toFloat() }
        val src = Rect(); val dst = Rect()
        val side = 48 * scale
        val stripH = 7 * scale

        override fun onMeasure(w: Int, h: Int) = setMeasuredDimension(side, side + stripH)

        override fun onDraw(c: Canvas) {
            val s = shot ?: held
            val bmp = if (s == BadgeState.OFF || s == BadgeState.PAUSED || s == BadgeState.TAP_TO_WAKE) off ?: on else on
            if (bmp != null) {
                src.set(0, 0, bmp.width, bmp.height); dst.set(0, 0, side, side)
                c.drawBitmap(bmp, src, dst, px)
            } else {
                strip.color = 0xFF222222.toInt(); c.drawRect(0f, 0f, side.toFloat(), side.toFloat(), strip); strip.color = Color.BLACK
            }
            c.drawRect(0f, side.toFloat(), side.toFloat(), (side + stripH).toFloat(), strip)
            c.drawText(BadgeStates.label(s).uppercase().take(11), side / 2f, side + stripH - 1.5f * scale, txt)
        }
    }

    override fun setState(s: BadgeState) {
        if (s == held) return
        held = s
        if (shot == null) { view.invalidate(); describe() }
    }

    override fun playOnce(s: BadgeState) {
        shot = s
        view.removeCallbacks(clearShot); view.postDelayed(clearShot, ONE_SHOT_MS)
        view.invalidate(); describe()
    }

    private fun describe() { view.contentDescription = "Canti: ${BadgeStates.label(shot ?: held)}" }

    companion object { const val ONE_SHOT_MS = 900L }
}

/** What the badge's tap menu can do; the service implements it (mode and pause through its own paths). */
interface BadgeActions {
    val mode: String
    val paused: Boolean
    val source: String
    fun setMode(mode: String)
    fun setPaused(p: Boolean)
    fun setSource(src: String)
    /** The Pico is connected and paused only by a link drop: a tap wakes it ([wake]) instead of opening the menu. */
    val wakeable: Boolean get() = false
    /** Arm the Pico (the badge's tap in [BadgeState.TAP_TO_WAKE]). */
    fun wake() {}
    /** The voice joystick drives the cursor (cursor mode, phone / USB mic): the menu offers RECENTRE and CALIBRATE. */
    val joystick: Boolean get() = false
    /** Put the joystick cursor back in the centre. */
    fun recentre() {}
    /** Open the calibration screen (route `calibrate`). */
    fun calibrate() {}

    companion object {
        /** Menu rows: sound-source keys (audio.SoundSource) and their labels. */
        val SOURCES = listOf("pico" to "PICO", "phone" to "PHONE MIC", "usb" to "USB MIC")
    }
}
