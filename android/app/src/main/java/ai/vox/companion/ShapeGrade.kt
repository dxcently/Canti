package ai.vox.companion

import ai.vox.companion.joystick.JMath
import kotlin.math.abs

/*
 * The tolerant grade (E9 contract A, PROTOCOL.md "Gesture training" / "Calibration"). Pure JVM: no Android types.
 *
 * A take (or a live trace so far) is graded against the *wanted* shape with thresholds LOOSER than the gesture
 * extractor's own classifier (extractor/vox_extract/config.py: flat_max_range_st 1.5, shape_min_st 1.0), so a near
 * miss is still a pass (shown "~"), and only a clear miss fails. The output is a list of [Check] in this order,
 * only the ids that apply to the wanted shape:
 *
 *   PITCH  start note vs the wanted start mark (low|high|home), in semitones on the user's scale
 *   SHAPE  the contour direction from the pitch track, or the label family for a discrete sound
 *   LENGTH quick/short/slow/long/untagged duration
 *   SOUND  voiced vs not (hum/whistle by the 600 Hz whistle band, or unpitched)
 *   LOUD   the level gate passed and not clipped
 *   COUNT  (combos) the number of sounds
 *   GAP    (combos) the gap between sounds within the wanted window
 *
 * [grade] judges a finished take; [live] judges the live trace while a take records (provisional: pending until
 * enough data). A pass = no check is `miss` (`near` passes).
 */
object ShapeGrade {
    // --- thresholds ---------------------------------------------------------------------------------------------------

    // PITCH: the start note within this many semitones of the mark is ok; within PITCH_NEAR_ST is near.
    const val PITCH_OK_ST = 3.0
    const val PITCH_NEAR_ST = 5.0
    // PITCH: a low start is "at or below HOME-2 st", a high start "at or above HOME+2 st" (the mark itself).
    const val START_MARK_ST = 2.0

    // SHAPE: a rise/fall net move and an arch/dip peak/trough of at least this (st) is ok; SHAPE_NEAR_ST is near.
    // Looser than the extractor's shape_min_st (1.0).
    const val SHAPE_OK_ST = 0.7
    const val SHAPE_NEAR_ST = 0.4
    // SHAPE: a point this far (st) from both neighbours is a spike (an octave error is 12 st; a real contour moves well
    // under 2 st between its 16 points).
    const val SPIKE_ST = 5.0
    // SHAPE: a flat contour's range within this (st) is ok; within FLAT_NEAR_ST is near.
    // Looser than the extractor's flat_max_range_st (1.5).
    const val FLAT_OK_ST = 2.0
    const val FLAT_NEAR_ST = 3.0

    // LENGTH: quick/short ok within 1.0 s, near within 1.4 s; slow/long ok from 0.8 s, near from 0.6 s.
    const val QUICK_OK_MS = 1000.0
    const val QUICK_NEAR_MS = 1400.0
    const val SLOW_OK_MS = 800.0
    const val SLOW_NEAR_MS = 600.0
    // LENGTH: untagged ok 0.2-2.5 s, near otherwise within 4 s.
    const val UNTAGGED_OK_LO_MS = 200.0
    const val UNTAGGED_OK_HI_MS = 2500.0
    const val UNTAGGED_NEAR_MS = 4000.0

    // SOUND: whistle = median f0 at least this (the extractor's whistle_min_hz); near within TONE_NEAR_FRAC of it.
    const val WHISTLE_MIN_HZ = 600.0
    const val TONE_NEAR_FRAC = 0.10

    // LOUD: near when the level is within this many dB of the gate (miss when gated / clipped / too quiet).
    const val LOUD_NEAR_DB = 3.0

    // GAP: the gap within the wanted window gap_s +/- this many seconds.
    const val GAP_OK_S = 0.6

    // LIVE: pitch pending until this much voiced data; shape pending until this fraction of the wanted length.
    const val LIVE_PITCH_MS = 150.0
    const val LIVE_SHAPE_FRAC = 0.6
    // LIVE: the start note is the median of the first this-many voiced ticks (an onset tick can be an octave off).
    const val LIVE_START_TICKS = 8

    /** The wanted length (s) of a speed/length tag, for the live shape timing (contract B `dur_s`). */
    const val QUICK_DUR_S = 0.6
    const val SLOW_DUR_S = 1.5
    const val UNTAGGED_DUR_S = 0.8

    // --- types --------------------------------------------------------------------------------------------------------

    /**
     * The wanted shape. [start] low|home|high (a PITCH check) or `none` (unpitched); [speed] quick|short|slow|long|null
     * (untagged); [tone] hum|whistle|any; [durS] overrides the speed's wanted length (a
     * calibration step's 3 s / 5 s).
     */
    data class Want(
        val sequence: List<String>,
        val start: String,
        val speed: String?,
        val tone: String,
        val gapS: Double? = null,
        val durS: Double? = null,
    )

    /** What was heard. [pitch16] is the 16-point relative pitch track (semitones); null when there is none. */
    data class Heard(
        val labels: List<String>,
        val pitch16: List<Double>? = null,
        val f0Hz: Double? = null,
        val startHz: Double? = null,
        val durMs: Long? = null,
        val loudness: String? = null,
        val tone: String? = null,
        val gated: Boolean = false,
        val clipped: Boolean = false,
        val levelDb: Double? = null,
        val gateDb: Double? = null,
        val gapsMs: List<Long>? = null,
    ) {
        val label get() = labels.firstOrNull()
    }

    /** The user's scale (a saved calibration profile's range_lo_hz / home_hz / range_hi_hz), when there is one. */
    data class Scale(val loHz: Double?, val homeHz: Double?, val hiHz: Double?)

    /** One check: [state] ok|near|miss|pending. [value] is what was heard/measured, [want] what was asked. */
    data class Check(val id: String, val label: String, val state: String, val value: Any?, val want: Any?)

    // --- helpers ------------------------------------------------------------------------------------------------------

    private fun st(hz: Double) = JMath.st(hz)
    private fun unpitched(heard: Heard) = heard.f0Hz == null

    /** The wanted duration in seconds for [speed] (contract B `dur_s`). */
    fun wantedDurS(want: Want): Double = want.durS ?: wantedDurS(want.speed)

    fun wantedDurS(speed: String?): Double = when (speed) {
        "quick", "short" -> QUICK_DUR_S
        "slow", "long" -> SLOW_DUR_S
        else -> UNTAGGED_DUR_S
    }

    /** The finite points with single-point spikes removed: one stray point (an octave jump near the extractor's 75 Hz f0
     *  floor, a low voice's creak) must not decide the shape. A genuine contour's neighbours stay as they are. */
    private fun stTrack(pitch16: List<Double>?): List<Double> {
        val t = pitch16?.filter { it.isFinite() }?.toMutableList() ?: return emptyList()
        val n = t.size
        if (n < 3) return t
        val far = { a: Double, b: Double -> abs(a - b) > SPIKE_ST }
        for (i in 1 until n - 1)
            if (far(t[i], t[i - 1]) && far(t[i], t[i + 1]) && (t[i] - t[i - 1]) * (t[i] - t[i + 1]) > 0) t[i] = (t[i - 1] + t[i + 1]) / 2
        if (far(t[0], t[1]) && !far(t[1], t[2])) t[0] = 2 * t[1] - t[2]
        if (far(t[n - 1], t[n - 2]) && !far(t[n - 2], t[n - 3])) t[n - 1] = 2 * t[n - 2] - t[n - 3]
        return t
    }

    /** A live trace (Hz, voiced ticks only) as at most 16 median bins in st, like the extractor's pitch16. */
    private fun bins16(voicedHz: List<Double>): List<Double> {
        val n = voicedHz.size
        if (n <= 16) return voicedHz.map(::st)
        return (0 until 16).map { b -> JMath.median(voicedHz.subList(b * n / 16, (b + 1) * n / 16).map(::st)) }
    }

    /** The measured shape number (st): net move (rise/fall), peak/trough clearance (arch/dip), range (flat). */
    private fun shapeMetric(g: String, track: List<Double>): Double {
        if (track.size < 2) return 0.0
        val first = track.first(); val last = track.last()
        return when (g) {
            "rise", "fall" -> last - first
            "arch" -> (track.max() - first).coerceAtMost(track.max() - last)
            "dip" -> (first - track.min()).coerceAtMost(last - track.min())
            "flat" -> track.max() - track.min()
            else -> 0.0
        }
    }

    // --- the checks, in order -----------------------------------------------------------------------------------------

    private fun pitchCheck(want: Want, heard: Heard, scale: Scale?): Check? {
        if (want.start == "none") return null                       // unpitched: no pitch check
        val mark = want.start
        val startHz = heard.startHz
        val homeHz = scale?.homeHz
        if (startHz == null || homeHz == null)                       // no scale: relative to the session median (pending)
            return Check("PITCH", "PITCH", "pending", startHz, mark)
        val value = st(startHz) - st(homeHz)                        // the start note in st above home
        val state = when (mark) {
            // low: the mark is HOME-2 st; within 3 st of it is ok, and anything at/below it is ok too
            "low" -> when {
                value <= PITCH_OK_ST - START_MARK_ST -> "ok"
                value <= PITCH_NEAR_ST - START_MARK_ST -> "near"
                else -> "miss"
            }
            // high: the mark is HOME+2 st, symmetric
            "high" -> when {
                value >= -(PITCH_OK_ST - START_MARK_ST) -> "ok"
                value >= -(PITCH_NEAR_ST - START_MARK_ST) -> "near"
                else -> "miss"
            }
            else -> when {                                          // "home": the note itself
                abs(value) <= PITCH_OK_ST -> "ok"
                abs(value) <= PITCH_NEAR_ST -> "near"
                else -> "miss"
            }
        }
        return Check("PITCH", "PITCH", state, value, mark)
    }

    private fun shapeCheck(want: Want, heard: Heard): Check? {
        val g = want.sequence.singleOrNull() ?: return null          // a combo has no single shape
        if (g !in TrainPlan.CONTOURS && g !in TrainPlan.DISCRETE) return null
        if (g in TrainPlan.DISCRETE) {
            // discrete: shape = the right label family (click / hiss); a heard "pop" folds to "click" (2026-09-28)
            val label = heard.label
            return Check("SHAPE", "SHAPE", if (SoundFold.label(label ?: "") == g) "ok" else "miss", label, g)
        }
        val track = stTrack(heard.pitch16)
        // the extractor's own label agrees (its thresholds are stricter): ok, whatever the smoothed track says
        if (SoundFold.label(heard.label ?: "") == g) return Check("SHAPE", "SHAPE", "ok", if (track.size < 2) null else shapeMetric(g, track), g)
        if (track.size < 2) return Check("SHAPE", "SHAPE", "miss", null, g)   // no pitch track to judge
        val m = shapeMetric(g, track)
        val state = when (g) {
            "rise" -> if (m >= SHAPE_OK_ST) "ok" else if (m >= SHAPE_NEAR_ST) "near" else "miss"
            "fall" -> if (m <= -SHAPE_OK_ST) "ok" else if (m <= -SHAPE_NEAR_ST) "near" else "miss"
            "arch", "dip" -> if (m >= SHAPE_OK_ST) "ok" else if (m >= SHAPE_NEAR_ST) "near" else "miss"
            else -> if (m <= FLAT_OK_ST) "ok" else if (m <= FLAT_NEAR_ST) "near" else "miss"
        }
        return Check("SHAPE", "SHAPE", state, m, g)
    }

    private fun lengthCheck(want: Want, heard: Heard): Check? {
        val d = heard.durMs ?: return null
        val speed = want.speed
        if (speed == null && want.sequence.all { it in TrainPlan.DISCRETE }) return null   // a pop is as long as it is
        val state = when (speed) {
            "quick", "short" -> if (d <= QUICK_OK_MS) "ok" else if (d <= QUICK_NEAR_MS) "near" else "miss"
            "slow", "long" -> if (d >= SLOW_OK_MS) "ok" else if (d >= SLOW_NEAR_MS) "near" else "miss"
            else -> if (d >= UNTAGGED_OK_LO_MS && d <= UNTAGGED_OK_HI_MS) "ok" else if (d <= UNTAGGED_NEAR_MS) "near" else "miss"
        }
        return Check("LENGTH", "LENGTH", state, d, speed)
    }

    private fun soundCheck(want: Want, heard: Heard): Check? {
        if (want.start == "none") {
            // unpitched gestures must be unpitched (the extractor's own label for it counts: a hiss can carry a stray f0)
            val u = unpitched(heard) || (heard.label != null && SoundFold.label(heard.label!!) in want.sequence)
            return Check("SOUND", "SOUND", if (u) "ok" else "miss", if (u) null else heard.f0Hz, "unpitched")
        }
        if (want.tone == "any") return null
        val f0 = heard.f0Hz
        if (f0 == null) return Check("SOUND", "SOUND", "miss", null, want.tone)   // no clear pitch
        val band = WHISTLE_MIN_HZ * TONE_NEAR_FRAC
        val state = when (want.tone) {
            "hum" -> if (f0 < WHISTLE_MIN_HZ - band) "ok" else if (f0 < WHISTLE_MIN_HZ + band) "near" else "miss"
            else -> if (f0 >= WHISTLE_MIN_HZ + band) "ok" else if (f0 >= WHISTLE_MIN_HZ - band) "near" else "miss"
        }
        return Check("SOUND", "SOUND", state, f0, want.tone)
    }

    private fun loudCheck(want: Want, heard: Heard): Check? {
        val state = when {
            heard.gated -> "miss"                                     // gated = too quiet for the gate
            heard.clipped -> "miss"
            heard.levelDb != null && heard.gateDb != null ->
                if (heard.levelDb >= heard.gateDb) "ok"
                else if (heard.levelDb >= heard.gateDb - LOUD_NEAR_DB) "near"
                else "miss"
            else -> "ok"                                              // nothing to judge against: it passed
        }
        return Check("LOUD", "LOUD", state, heard.levelDb ?: heard.loudness, heard.gateDb)
    }

    private fun countCheck(want: Want, heard: Heard): Check? {
        if (want.sequence.size < 2) return null
        return Check("COUNT", "COUNT", if (heard.labels.size == want.sequence.size) "ok" else "miss",
            heard.labels.size, want.sequence.size)
    }

    private fun gapCheck(want: Want, heard: Heard): Check? {
        val gapS = want.gapS ?: return null
        val gaps = heard.gapsMs ?: return null
        if (gaps.isEmpty()) return Check("GAP", "GAP", "miss", null, gapS)
        val g = gaps.max().toDouble() / 1000.0                    // the widest gap must fit the window
        return Check("GAP", "GAP", if (abs(g - gapS) <= GAP_OK_S) "ok" else "miss", g, gapS)
    }

    // --- public -------------------------------------------------------------------------------------------------------

    /** The tolerant grade of a finished take. Only the ids that apply, in order. */
    fun grade(want: Want, heard: Heard, scale: Scale? = null): List<Check> =
        listOfNotNull(
            pitchCheck(want, heard, scale),
            shapeCheck(want, heard),
            lengthCheck(want, heard),
            soundCheck(want, heard),
            loudCheck(want, heard),
            countCheck(want, heard),
            gapCheck(want, heard),
        )

    /**
     * The provisional grade of the live trace so far (Hz per [tickMs] ms tick, null = unvoiced). Pending until there
     * is enough data: pitch after [LIVE_PITCH_MS] voiced, shape after [LIVE_SHAPE_FRAC] of the wanted length voiced, length
     * only at the end.
     */
    fun live(want: Want, traceHz: List<Double?>, tickMs: Int, scale: Scale? = null): List<Check> {
        val voiced = traceHz.filterNotNull().filter { it > 0 }
        val elapsedMs = traceHz.size.toLong() * tickMs
        val voicedMs = voiced.size * tickMs
        val wantedMs = wantedDurS(want) * 1000.0
        val startHz = if (voiced.isEmpty()) null else JMath.median(voiced.take(LIVE_START_TICKS))
        val heard = Heard(
            labels = emptyList(),
            pitch16 = if (voiced.isNotEmpty()) bins16(voiced) else null,
            f0Hz = if (voiced.isNotEmpty()) JMath.median(voiced) else null,
            startHz = startHz,
            durMs = elapsedMs,
        )
        val pending = { id: String, value: Any?, wantV: Any? -> Check(id, id, "pending", value, wantV) }
        val g = want.sequence.singleOrNull()
        val pitched = g != null && g in TrainPlan.CONTOURS
        val pitch = if (want.start == "none") null else
            if (voicedMs < LIVE_PITCH_MS) pending("PITCH", startHz, want.start)
            else pitchCheck(want, heard, scale)
        val shape = if (!pitched) null else
            if (voicedMs < wantedMs * LIVE_SHAPE_FRAC) pending("SHAPE", null, g)
            else shapeCheck(want, heard)
        val length = if (want.speed == null && want.sequence.all { it in TrainPlan.DISCRETE }) null
            else pending("LENGTH", elapsedMs, want.speed)
        val sound = when {
            want.start == "none" -> soundCheck(want, heard)          // unpitched: judged as soon as there is (no) pitch
            want.tone == "any" -> null
            voiced.isEmpty() -> pending("SOUND", null, want.tone)
            else -> soundCheck(want, heard)
        }
        return listOfNotNull(pitch, shape, length, sound)
    }
}
