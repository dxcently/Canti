package ai.vox.companion.rec

import kotlin.math.log10
import kotlin.math.sqrt

/**
 * The take's silence detector (contract §6), a pure port of extractor/range_session.capture_live, fed PCM16 mono
 * frames. All numbers come from the spec's `analysis`. Frame counts (no ms rounding) drive the timing fields the
 * recorder writes.
 *
 * - floor = median of 50 ms tick dB over the floor window (0.5 s) before GO, from the pre-roll the engine supplies.
 * - dB = 20*log10(rms(samples / 32768) + 1e-9) over a whole tick.
 * - open if level > floor + open_db, stay open while >= floor + close_db.
 * - end on silence_s after the last loud tick, at max_s, or "no sound" after no_sound_s; fixed windows (a background
 *   or the quiet room step) never end on silence or "no sound"; backgrounds end at exactly seconds*rate frames.
 * - the end frame includes post-roll (backgrounds have none).
 */
class TakeDetector(
    private val rate: Int,
    private val fixedWindow: Boolean,
    private val background: Boolean,
    private val targetFrames: Int,           // max_s*rate (takes) or seconds*rate (backgrounds)
    tickS: Double,
    floorWindowS: Double,
    private val openDb: Double,
    private val closeDb: Double,
    silenceS: Double,
    noSoundS: Double,
    postRollS: Double,
) {
    private val tickFrames = (tickS * rate).toInt().coerceAtLeast(1)
    private val floorFrames = (floorWindowS * rate).toInt().coerceAtLeast(1)
    private val silenceFrames = (silenceS * rate).toInt().coerceAtLeast(1)
    private val noSoundFrames = (noSoundS * rate).toInt().coerceAtLeast(1)
    private val postRollFrames = (postRollS * rate).toInt().coerceAtLeast(0)

    private var floorDb = Double.NaN
    private var heard = false
    private var last = 0L        // end frame (relative to GO) of the last loud tick
    private var now = 0L         // post-GO frames fed so far
    private var ended = false

    var reason = "max length"; private set
    var noSound = false; private set

    /** The end frame relative to GO (the take buffer spans [GO - pre, GO + endFrame)). */
    var endFrame = 0L; private set

    /** The floor computed by [setFloor] (NaN before it runs). */
    fun floorDbValue(): Double = floorDb

    private val tick = ShortArray(tickFrames)
    private var tickFill = 0

    /** Computes the floor from [preRoll] (1 s before GO): the median 50 ms tick dB over the last floor window. */
    fun setFloor(preRoll: ShortArray): Double {
        val n = floorFrames.coerceAtMost(preRoll.size)
        val start = preRoll.size - n
        val whole = (n / tickFrames) * tickFrames
        if (whole <= 0) { floorDb = -1e9; return floorDb }
        val dbs = ArrayList<Double>(whole / tickFrames)
        for (o in start until start + whole step tickFrames) dbs.add(tickDb(preRoll, o, tickFrames))
        dbs.sort()
        floorDb = if (dbs.size % 2 == 1) dbs[dbs.size / 2] else (dbs[dbs.size / 2 - 1] + dbs[dbs.size / 2]) / 2
        return floorDb
    }

    /** Feeds [n] post-GO frames from [samples] starting at [from]; returns true when the take's end was reached. */
    fun feed(samples: ShortArray, from: Int, n: Int): Boolean {
        var i = from
        while (i < from + n && !ended) {
            tick[tickFill++] = samples[i]; i++
            if (tickFill == tickFrames) {
                evaluateTick()
                tickFill = 0
            }
        }
        return ended
    }

    private fun evaluateTick() {
        now += tickFrames
        val level = tickDb(tick, 0, tickFrames)
        if (level > floorDb + openDb || (heard && level >= floorDb + closeDb)) { heard = true; last = now }
        if (background) {
            if (now >= targetFrames) end("fixed", now)   // exactly seconds*rate, no post-roll
            return
        }
        val fixed = fixedWindow
        if (!fixed && heard && (now - last) >= silenceFrames) { end("silence", last + postRollFrames); return }
        if (now >= targetFrames) { end(if (fixed) "fixed" else "max length", now + postRollFrames); return }
        if (!fixed && !heard && now >= noSoundFrames) { noSound = true; end("no sound", now + postRollFrames); return }
    }

    private fun end(reason: String, endFrame: Long) {
        this.reason = reason; this.endFrame = endFrame; ended = true
    }

    private fun tickDb(samples: ShortArray, from: Int, n: Int): Double {
        var sumSq = 0.0
        for (i in from until from + n) { val s = samples[i] / 32768.0; sumSq += s * s }
        return 20.0 * log10(sqrt(sumSq / n) + 1e-9)
    }

    companion object {
        /** The detector's analysis numbers straight from the spec, framed at [rate]. */
        fun forTake(rate: Int, take: RangePlan.Take, analysis: org.json.JSONObject): TakeDetector {
            val a = analysis
            val target = if (take.kind == "backgrounds") (take.seconds!! * rate).toInt()
                else (take.maxS!! * rate).toInt()
            return TakeDetector(rate, take.fixedWindow, take.kind == "backgrounds", target,
                a.getDouble("tick_s"), a.getDouble("floor_window_s"), a.getDouble("open_db"),
                a.getDouble("close_db"), a.getDouble("silence_s"), a.getDouble("no_sound_s"),
                a.getDouble("post_roll_s"))
        }
    }
}
