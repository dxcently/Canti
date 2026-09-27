package ai.vox.companion

import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.ln
import kotlin.math.pow
import kotlin.math.sign

/**
 * Hold-to-scroll: a vertical swipe gesture (rise or fall, executed as swipe_up / swipe_down) followed within [WINDOW_MS] by a
 * held flat hum scrolls in the swipe's direction for as long as the hum is held. The device reports the hum live
 * (`hold start` / `hold end`, PROTOCOL.md); the swipe itself is never delayed. That flat's final event is then not
 * acted on (no long-press). A flat hum with no swipe right before it stays long-press.
 */
object HoldScrollTrigger {
    val DIRECTIONS = setOf("swipe_up", "swipe_down")

    /** How soon after the swipe's sound ended the held hum must start. */
    const val WINDOW_MS = 1000L

    /** Arrival fallback (no device stamps): `hold start` may be sent a little after the hum began. */
    const val ARRIVAL_SLACK_MS = 1000L

    /** An executed swipe: decision [n], and the device end / local arrival of its sound. */
    data class Swipe(val n: Long, val action: String, val app: String, val mode: String, val end: Stamp?, val arrivedAt: Long)

    /**
     * Why a hold that started at device time [holdStartMs] (arrived at [arrivedAt]) continues [last] (the decision
     * just before it, [prevN]), or null if it does not. Device clock: hold start - swipe end within [windowMs].
     * Arrival clock: within windowMs + [ARRIVAL_SLACK_MS].
     */
    fun follows(last: Swipe?, prevN: Long, mode: String, app: String, holdStartMs: Long?, arrivedAt: Long,
                windowMs: Long = WINDOW_MS): String? {
        if (last == null || last.n != prevN || last.mode != mode || last.app != app || last.action !in DIRECTIONS) return null
        val end = last.end
        if (holdStartMs != null && end != null) {
            val gap = holdStartMs - end.endMs
            return if (gap in -Sequencer.CLOCK_SLACK_MS..windowMs) "device gap $gap ms" else null
        }
        val dt = arrivedAt - last.arrivedAt
        return if (dt in 0..windowMs + ARRIVAL_SLACK_MS) "arrival gap $dt ms" else null
    }
}

/**
 * Glide-and-hold: a rise or fall whose END note is then held (the device sends `hold start` with `"from":"glide"` and
 * `dir` up / down once that note has been steady for 250 ms; PROTOCOL.md "Glide-and-hold") scrolls continuously the
 * way a single rise / fall would go in this app and mode, until the note is released (`hold end`). No preceding swipe
 * is needed. A glide whose end note is shorter sends no hold and stays a single rise / fall step. The older method (a
 * rise / fall, then a separate held flat hum: [HoldScrollTrigger]) is unchanged.
 */
object GlideHold {
    /**
     * The scroll a glide hold runs: what a single rise (dir up) or fall (down) is bound to in [app] and [mode] (app >
     * global > defaults, as [RuleDecider]), if that is a vertical swipe; else null (it does not scroll: cursor mode, a
     * rule only the model can apply, or a binding to another action such as zoom). Its final event is then decided as
     * usual.
     */
    fun action(dir: String?, mode: String, app: String, profile: Profile): String? {
        if (mode == "cursor") return null
        val seq = listOf(when (dir) { "up" -> "rise"; "down" -> "fall"; else -> return null })
        val a = profile.appBindings(app).lastOrNull { it.phrase == seq }?.let { return@let it.action ?: return null }
            ?: profile.globalBindings().lastOrNull { it.phrase == seq }?.let { return@let it.action ?: return null }
            ?: Vocab.DEFAULT_BINDINGS[seq]
        return a?.takeIf { it in HoldScrollTrigger.DIRECTIONS }
    }
}

/**
 * What the service does with a live `hold start` ([route], pure): the gate in one place for both kinds of hold.
 */
object HoldGate {
    sealed class Route {
        data class Ignore(val why: String) : Route()
        /** A sound is still being decided: wait for it (the start is re-routed when it is done). */
        object Buffer : Route()
        /** A flat hum: scrolls only right after a rise / fall swipe ([HoldScrollTrigger.follows]). */
        object Flat : Route()
        /** Glide-and-hold: scrolls [action] now. */
        data class Glide(val action: String) : Route()
    }

    fun route(h: HoldMessage, armed: Boolean, paused: Boolean, listening: Boolean, sequenceWaiting: Boolean,
              deciding: Boolean, mode: String, app: String, profile: Profile): Route = when {
        !armed || paused -> Route.Ignore(if (paused) "paused (app)" else "disarmed")
        listening -> Route.Ignore("phrase window open (speech is not gestures)")
        h.isGlide && sequenceWaiting -> Route.Ignore("glide: a sequence is waiting for its next sound; this sound may be it")
        h.isGlide && deciding -> Route.Buffer
        h.isGlide -> GlideHold.action(h.dir, mode, app, profile)?.let { Route.Glide(it) }
            ?: Route.Ignore("glide ${h.dir}: a single ${if (h.dir == "up") "rise" else "fall"} does not scroll here")
        !h.flat -> Route.Ignore("hold start not flat: never acts")
        sequenceWaiting || deciding -> Route.Buffer
        else -> Route.Flat
    }
}

/**
 * Pitch throttle for a hold-scroll (PROTOCOL.md "Hold pitch"): humming higher than the hold started speeds the scroll
 * up, lower slows it down. Input: the device's `hold pitch` reports (median f0 of the last ~200 ms, about 5 per s).
 *
 *  - Relative, in semitones, to [reset]'s base (the `hold start` f0; without one, the first report).
 *  - Cleaned: octave errors of the pitch tracker are folded back (|d| > [foldSt] -> d - 12 round(d / 12)), then clamped
 *    to +-[clampSt]; the median of the last 3 reports drops a single glitch.
 *  - Smoothed: an exponential average with time constant [tauMs] on the device clock (`t_ms`).
 *  - Mapped: within +-[deadSt] of the base the factor is exactly 1 (natural wobble does nothing); beyond it,
 *    2^((|d| - dead) / [stPerDouble]), up or down, clamped to [[floor], [ceiling]]. Continuous at the dead zone's
 *    edge, so crossing it does not jump.
 * Pure (JVM-tested); no reports = factor 1, so a device without `hold pitch` scrolls exactly as before.
 */
class PitchThrottle(
    private val deadSt: Double = 1.0,
    private val stPerDouble: Double = 3.0,
    private val floor: Double = 0.3,
    private val ceiling: Double = 3.0,
    private val tauMs: Double = 200.0,
    private val clampSt: Double = 8.0,
    private val foldSt: Double = 9.0,
) {
    private var base: Double? = null
    private var lastT: Long? = null
    private val recent = ArrayDeque<Double>()
    /** Smoothed semitones relative to the base; null before the first report. */
    var semitones: Double? = null
        private set
    var factor = 1.0
        private set

    fun reset(baseHz: Double?) {
        base = baseHz?.takeIf { it > 0 && it.isFinite() }
        lastT = null; recent.clear(); semitones = null; factor = 1.0
    }

    /** A report of [f0Hz] at device time [tMs]; returns the new factor. A non-positive or NaN f0 is ignored. */
    fun update(f0Hz: Double, tMs: Long): Double {
        if (!(f0Hz > 0) || !f0Hz.isFinite()) return factor
        val b = base ?: f0Hz.also { base = it }
        var d = 12.0 * ln(f0Hz / b) / ln(2.0)
        if (abs(d) > foldSt) d -= 12.0 * Math.round(d / 12.0)
        d = d.coerceIn(-clampSt, clampSt)
        recent.addLast(d); while (recent.size > 3) recent.removeFirst()
        val m = recent.sorted().let { if (it.size == 2) (it[0] + it[1]) / 2 else it[it.size / 2] }
        val prev = semitones
        val dt = lastT?.let { (tMs - it).coerceAtLeast(1L) }
        lastT = tMs
        semitones = if (prev == null || dt == null) m else prev + (m - prev) * (1 - exp(-dt / tauMs))
        factor = map(semitones!!)
        return factor
    }

    fun map(st: Double): Double {
        val over = abs(st) - deadSt
        if (over <= 0) return 1.0
        return 2.0.pow(sign(st) * over / stPerDouble).coerceIn(floor, ceiling)
    }
}

/** The finger that scrolls: [begin] puts it down and keeps it moving; [end] holds it still and lifts it (no fling). */
interface ScrollDrag {
    fun begin(action: String, onFail: (String) -> Unit)
    fun end()
}

/**
 * Runs one hold-scroll from `hold start` to `hold end`. Safety stops, checked every [checkMs]: the [watchdogMs]
 * watchdog (5 s with no `hold end`: it was lost; the device ends every sound within 4 s), the [capMs] cap (2 min, for
 * a run without a hold id), the foreground app changing, the screen turning off. The service also stops it on pause, disarm, a mode
 * change and any other sound. The ids of recent holds are kept so the held flat's final event can be dropped
 * ([consumeFinal]). Main thread only.
 */
class HoldScroller(
    private val scheduler: Scheduler,
    private val foreground: () -> String,
    private val screenOn: () -> Boolean,
    private val drag: ScrollDrag,
    private val onEvent: (event: String, run: Run, why: String?) -> Unit = { _, _, _ -> },
    private val checkMs: Long = 500L,
    private val capMs: Long = 120_000L,
    private val watchdogMs: Long = 5_000L,
    private val throttle: PitchThrottle = PitchThrottle(),
) {
    data class Run(val action: String, val app: String, val holdId: String?, val startedAt: Long)

    var run: Run? = null
        private set
    private var cancelTimer: (() -> Unit)? = null
    private val held = ArrayDeque<String>()

    val active get() = run != null

    /** Status text for the badge / status field, or null when idle. */
    val status: String? get() = run?.let { "hold-scroll ${DIR[it.action]}" }

    /** Speed multiplier from the pitch throttle ([PitchThrottle]); 1 when idle or without `hold pitch` reports. */
    val speed: Double get() = if (run != null) throttle.factor else 1.0
    /** Smoothed semitones relative to the hold's start pitch, for the log; null before any report. */
    val pitchSt: Double? get() = if (run != null) throttle.semitones else null

    /** [f0Hz]: the `hold start` pitch, the throttle's base (null: the first `hold pitch` report is). */
    fun start(action: String, app: String, holdId: String?, f0Hz: Double? = null) {
        require(action in HoldScrollTrigger.DIRECTIONS) { "hold-scroll direction must be a swipe" }
        stop("restarted")
        throttle.reset(f0Hz)
        val r = Run(action, app, holdId, scheduler.now())
        run = r
        if (holdId != null) remember(holdId)
        onEvent("start", r, null)
        drag.begin(action) { why -> if (run === r) stop(why) }
        schedule()
    }

    /** Stop; true if it was running. */
    fun stop(why: String): Boolean {
        val r = run ?: return false
        cancelTimer?.invoke(); cancelTimer = null
        run = null
        drag.end()
        onEvent("stop", r, why)
        return true
    }

    /** `hold end` for [holdId]: stops the run it started (true). A stale id (another hold) is ignored. */
    fun holdEnded(holdId: String?): Boolean {
        val r = run ?: return false
        if (holdId != null && r.holdId != null && holdId != r.holdId) return false
        return stop("hold end")
    }

    /**
     * A `hold pitch` report for [holdId] at device time [tMs]: feeds the throttle (true). Ignored (false) when no run is
     * going or it belongs to another hold.
     */
    fun pitch(holdId: String?, f0Hz: Double, tMs: Long): Boolean {
        val r = run ?: return false
        if (holdId != null && r.holdId != null && holdId != r.holdId) return false
        throttle.update(f0Hz, tMs)
        return true
    }

    private fun remember(holdId: String) { held.addLast(holdId); while (held.size > 8) held.removeFirst() }

    /** The final event of a sound: true (drop it) if it is the flat whose hold scrolled; that also stops the run. */
    fun consumeFinal(soundId: String?): Boolean {
        if (soundId == null || soundId !in held) return false
        held.remove(soundId)
        run?.let { if (it.holdId == soundId) stop("hold's final event (no hold end seen)") }
        return true
    }

    fun appChanged(pkg: String) { run?.let { if (pkg != it.app) stop("app changed: $pkg") } }

    private fun schedule() { cancelTimer = scheduler.schedule(checkMs) { cancelTimer = null; check() } }

    private fun check() {
        val r = run ?: return
        val why = when {
            scheduler.now() - r.startedAt >= capMs -> "cap ${capMs / 1000} s"
            r.holdId != null && scheduler.now() - r.startedAt >= watchdogMs -> "watchdog: no hold end after ${watchdogMs / 1000} s"
            !screenOn() -> "screen off"
            foreground() != r.app -> "app changed: ${foreground()}"
            else -> null
        }
        if (why != null) stop(why) else schedule()
    }

    companion object {
        val DIR = mapOf("swipe_up" to "down", "swipe_down" to "up", "swipe_left" to "right", "swipe_right" to "left")
    }
}
