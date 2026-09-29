package ai.vox.companion.joystick

import org.json.JSONObject
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.hypot
import kotlin.math.ln
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.roundToInt
import kotlin.math.sign

/*
 * The voice joystick (wiki/voice-cursor.md "Joystick cursor"), a port of extractor/joystick_core.py: ticks in, cursor
 * position out. Same rules and numbers (assets/joystick_v1.json = extractor/prompts/joystick_v1.json), checked against
 * golden traces made by the Python core (JoystickParityTest). The per-tick analysis (pitch, clarity, level, floor,
 * F1/F2) runs natively (firmware/extract/src/vx_tick.cpp); this file starts at the Tick.
 *
 * Mover        ticks -> cursor (dp). Up/down by pitch (home / glide / start), sideways by the vowel (ee right, oo
 *              left), only while a sound lasts; stops where it ends (minus the release), then the magnet.
 * PopDetector  ticks -> pops (the second pop detector, beside the extractor's).
 * PopMerge     the two detectors hearing one pop count once.
 * Clicker      pops -> click after the pop-pop gap.
 * Pure JVM: no Android types.
 */

/** One 20 ms analysis step (joystick_core.Tick). f1 / f2 NaN = none; f0 0 unless voiced. */
data class Tick(
    val tMs: Double,
    val f0: Double,
    val clarity: Double,
    val db: Double,
    val voiced: Boolean,
    val f1: Double = Double.NaN,
    val f2: Double = Double.NaN,
    val why: String = "",
    val f0Raw: Double = 0.0,
    val overDb: Double = 0.0,
)

object JMath {
    fun st(f: Double) = 12.0 * ln(f / 55.0) / ln(2.0)
    fun hz(st: Double) = 55.0 * 2.0.pow(st / 12.0)
    fun bark(f: Double) = 26.81 * f / (1960.0 + f) - 0.53

    /** numpy.median: the middle value, or the mean of the two middle ones. */
    fun median(xs: Collection<Double>): Double {
        require(xs.isNotEmpty())
        val s = xs.sorted()
        val n = s.size
        return if (n % 2 == 1) s[n / 2] else (s[n / 2 - 1] + s[n / 2]) / 2.0
    }

    fun mean(xs: Collection<Double>): Double = xs.sum() / xs.size

    /** numpy.percentile, linear interpolation. */
    fun percentile(xs: Collection<Double>, p: Double): Double {
        val s = xs.sorted()
        val pos = (s.size - 1) * p / 100.0
        val lo = pos.toInt()
        val hi = min(lo + 1, s.size - 1)
        return s[lo] + (s[hi] - s[lo]) * (pos - lo)
    }

    fun clip(v: Double, lo: Double, hi: Double) = min(max(v, lo), hi)

    /** Python's round() for the tick counts here (values like 100 / 20: exact, or .5 ties to even). */
    fun pyRound(v: Double): Int {
        val r = v.roundToInt()
        return if (abs(v - kotlin.math.floor(v) - 0.5) < 1e-12 && r % 2 != 0) r - 1 else r
    }
}

/** The pop detector's thresholds (spec "pop"); a calibration replaces peak_db, rise_db and core_ticks. */
data class PopParams(
    val loudDb: Double, val peakDb: Double, val riseDb: Double, val leadDb: Double, val peakWithin: Int,
    val coreDb: Double, val coreTicks: Int, val maxTicks: Int, val maxVoiced: Int, val quietTicks: Int,
    val afterVoiceMs: Double, val confirmMs: Double, val confirmDb: Double, val mergeMs: Double, val warmupMs: Double,
    val calPeakFrac: Double, val calPeakDb: Pair<Double, Double>, val calRiseFrac: Double,
    val calRiseDb: Pair<Double, Double>, val calCoreTicks: Pair<Int, Int>, val findPeakDb: Double, val findRiseDb: Double,
)

/** joystick_v1.json, parsed once. */
class JoySpec(val json: JSONObject) {
    private val tick = json.getJSONObject("tick")
    private val vo = json.getJSONObject("voicing")
    private val p = json.getJSONObject("pitch")
    private val vt = json.getJSONObject("vertical")
    private val home = vt.getJSONObject("home")
    private val gl = vt.getJSONObject("glide")
    private val ou = vt.getJSONObject("onset_undo")
    private val vw = json.getJSONObject("vowel")
    private val sp = json.getJSONObject("speed")
    private val mg = json.getJSONObject("magnet")
    private val pj = json.getJSONObject("pop")

    val version: String = json.optString("version")
    val tickMs = tick.getDouble("tick_ms")

    val clarityMin = vo.getDouble("clarity_min")
    val levelOverFloorDb = vo.getDouble("level_over_floor_db")
    val startTicks = vo.getInt("start_ticks")
    val endGapMs = vo.getDouble("end_gap_ms")
    val clarityContinue = vo.getDouble("clarity_continue")
    val continueNearSt = vo.getDouble("continue_near_st")
    val personClarity = vo.getJSONArray("person_clarity").let { it.getDouble(0) to it.getDouble(1) }
    val personMargin = vo.getDouble("person_margin")

    val smoothMs = p.getDouble("smooth_ms")
    val attackMs = p.getDouble("attack_ms")
    val settleMs = p.getDouble("settle_ms")
    val settleTolSt = p.getDouble("settle_tol_st")
    val settleMaxMs = p.getDouble("settle_max_ms")
    val reanchorGraceMs = p.getDouble("reanchor_grace_ms")
    val reanchorMinSt = p.getDouble("reanchor_min_st")
    val jumpGuardSt = p.getDouble("jump_guard_st")
    val jumpPersistMs = p.getDouble("jump_persist_ms")
    val deadZoneSt = p.getDouble("dead_zone_st")
    val fullSpeedSt = p.getDouble("full_speed_st")

    val verticalMode: String = vt.getString("mode").let { if (it == "mid") "home" else it }
    val homeRangeSt = home.getJSONArray("range_st").let { it.getDouble(0) to it.getDouble(1) }
    val homeFullFrac = home.getDouble("full_frac")
    val adaptHums = home.getInt("adapt_hums")
    val adaptBoundSt = home.getDouble("adapt_bound_st")
    val glideWindowMs = gl.getDouble("window_ms")
    val glideMinSt = gl.getDouble("min_st")
    val glideFullSt = gl.getDouble("full_st")
    val glideDead = gl.getDouble("dead")
    val onsetGraceMs = ou.getDouble("grace_ms")
    val onsetMinBelowSt = ou.getDouble("min_below_st")
    val onsetClarityMax: Double? = if (ou.isNull("clarity_max")) null else ou.getDouble("clarity_max")

    val vowelSmoothMs = vw.getDouble("smooth_ms")
    val sigmaBark = vw.getDouble("sigma_bark")
    val rejectBark = vw.getDouble("reject_bark")
    val vowelDeadZone = vw.getDouble("dead_zone")
    val vowelFull = vw.getDouble("full")
    val centroidsBark: Map<String, DoubleArray> = vw.getJSONObject("centroids_bark").let { c ->
        linkedMapOf<String, DoubleArray>().apply {
            for (k in c.keys()) c.optJSONArray(k)?.let { a -> put(k, doubleArrayOf(a.getDouble(0), a.getDouble(1))) }
        }
    }

    val speedRamp = sp.optString("mode", "ramp") == "ramp"
    val startDpS = sp.getDouble("start_dp_s")
    val maxDpS = sp.getDouble("max_dp_s")
    val rampS = sp.getDouble("ramp_s")
    val rampResetMs = sp.getDouble("ramp_reset_ms")

    val rewindMs = json.getJSONObject("release").getDouble("rewind_ms")

    val snapDp = mg.getDouble("snap_dp")
    val maxAreaFrac = mg.getDouble("max_area_frac")
    val centreMaxDp: Double? = if (mg.isNull("centre_max_dp")) null else mg.getDouble("centre_max_dp")

    val popSeqGapMs = json.getJSONObject("click").getDouble("pop_seq_gap_ms")

    val pop: PopParams = pj.getJSONObject("calibrate").let { c ->
        fun pr(k: String) = c.getJSONArray(k).let { it.getDouble(0) to it.getDouble(1) }
        PopParams(
            pj.getDouble("loud_db"), pj.getDouble("peak_db"), pj.getDouble("rise_db"), pj.getDouble("lead_db"),
            pj.getInt("peak_within"), pj.getDouble("core_db"), pj.getInt("core_ticks"), pj.getInt("max_ticks"),
            pj.getInt("max_voiced"), pj.getInt("quiet_ticks"), pj.getDouble("after_voice_ms"), pj.getDouble("confirm_ms"),
            pj.getDouble("confirm_db"), pj.getDouble("merge_ms"), pj.getDouble("warmup_ms"),
            c.getDouble("peak_frac"), pr("peak_db"), c.getDouble("rise_frac"), pr("rise_db"),
            c.getJSONArray("core_ticks").let { it.getInt(0) to it.getInt(1) }, c.getDouble("find_peak_db"),
            c.getDouble("find_rise_db"))
    }

    // calibration v2 (the clicks / whistle / hiss / room steps, the level gate, the click / pop rule)
    private val c2 = json.getJSONObject("calib_v2")
    val clicksStep = DiscreteStep.of(c2.getJSONObject("clicks"))
    val hissStep = DiscreteStep.of(c2.getJSONObject("hiss"))
    private val c2w = c2.getJSONObject("whistle")
    val whistleGlideMs = c2w.getDouble("glide_ms")
    val whistleMinRangeSt = c2w.getDouble("min_range_st")
    val whistleMinSteadyTicks = c2w.getInt("min_steady_ticks")
    val whistleTickF0MaxHz = c2w.getDouble("tick_f0_max_hz")
    val voiceTickF0MaxHz = c2w.getDouble("voice_tick_f0_max_hz")
    private val c2r = c2.getJSONObject("room")
    val roomWindowMs = c2r.getDouble("window_ms")
    val roomSettleMs = c2r.getDouble("settle_ms")
    val roomMaxVoicedRunTicks = c2r.getInt("max_voiced_run_ticks")
    private val lg = json.getJSONObject("level_gate")
    val gateMarginSnrDb = lg.getDouble("margin_snr_db")
    val gateMarginLevelDb = lg.getDouble("margin_level_db")
    val gateRoomMarginDb = lg.getDouble("room_margin_db")
    val gateCapBelowWeakestDb = lg.getDouble("cap_below_weakest_db")
    val gateDefaultSnrDb = lg.getJSONObject("default").getDouble("min_snr_db")
    val gateDefaultLevelDbfs = lg.getJSONObject("default").getDouble("min_level_dbfs")
    val gateOffsetDb = lg.getJSONArray("offset_db").let { it.getDouble(0) to it.getDouble(1) }
    private val cp = json.getJSONObject("click_pop")
    /** Per feature (in the spec's order): the least gap between the pops and the clicks for it to separate them. */
    val clickPopMinGap: Map<String, Double> = cp.getJSONObject("min_gap").let { g -> linkedMapOf<String, Double>().apply { for (k in g.keys()) put(k, g.getDouble(k)) } }
    val clickPopMinEach = cp.getInt("min_each")
    val clickPopMinVotes = cp.getInt("min_votes")

    /** calib_v2.clicks / .hiss: the window, how many are asked for and needed, the settle after the last, the longest. */
    data class DiscreteStep(val windowMs: Double, val ask: Int, val need: Int, val settleMs: Double, val maxDurMs: Double?) {
        companion object {
            fun of(o: JSONObject) = DiscreteStep(o.getDouble("window_ms"), o.getInt("ask"), o.getInt("need"), o.getDouble("settle_ms"),
                if (o.has("max_dur_ms")) o.getDouble("max_dur_ms") else null)
        }
    }

    companion object {
        const val ASSET = "joystick_v1.json"
        fun parse(text: String) = JoySpec(JSONObject(text))
    }
}

// ------------------------------------------------------------------------------------------------ elements, magnet

/** A clickable element's bounds in dp and a label (joystick_core.Element). */
data class Element(val l: Double, val t: Double, val r: Double, val b: Double, val label: String = "") {
    val cx get() = (l + r) / 2
    val cy get() = (t + b) / 2
    val area get() = (r - l) * (b - t)
    fun dist(x: Double, y: Double): Double = hypot(max(max(l - x, 0.0), x - r), max(max(t - y, 0.0), y - b))
    fun contains(x: Double, y: Double) = x in l..r && y in t..b
}

object Magnet {
    /** The element the cursor snaps to: the nearest within snapDp (0 inside), the smaller one on a tie; containers
     *  (area > maxArea) never. */
    fun pick(els: List<Element>, x: Double, y: Double, snapDp: Double, maxArea: Double): Int? {
        var best: Int? = null
        var kd = 0.0
        var ka = 0.0
        for ((i, e) in els.withIndex()) {
            if (e.area > maxArea) continue
            val d = e.dist(x, y)
            if (d <= snapDp && (best == null || d < kd || (d == kd && e.area < ka))) { best = i; kd = d; ka = e.area }
        }
        return best
    }

    /** Where a snap puts the cursor: the centre of a small element, else just onto it (inset dp inside its edge). */
    fun snapPoint(e: Element, x: Double, y: Double, centreMaxDp: Double?, insetDp: Double = 8.0): Pair<Double, Double> {
        if (centreMaxDp == null || max(e.r - e.l, e.b - e.t) <= centreMaxDp) return e.cx to e.cy
        if (e.contains(x, y)) return x to y
        val ix = min(insetDp, (e.r - e.l) / 2)
        val iy = min(insetDp, (e.b - e.t) / 2)
        return min(max(x, e.l + ix), e.r - ix) to min(max(y, e.t + iy), e.b - iy)
    }

    /** The element a click at (x, y) lands on: the smallest containing it. */
    fun hit(els: List<Element>, x: Double, y: Double): Int? {
        var best: Int? = null
        for ((i, e) in els.withIndex()) if (e.contains(x, y) && (best == null || e.area < els[best].area)) best = i
        return best
    }
}

// ------------------------------------------------------------------------------------------------ the mover

private class TV(val t: Double, val v: Double)
private class TXY(val t: Double, val x: Double, val y: Double)

private class Sound(val tOn: Double, var lastVoiced: Double, val posOnX: Double, val posOnY: Double) {
    var ref: Double? = null
    var refT: Double? = null
    var posAtRef: Pair<Double, Double>? = null
    var raw = ArrayList<TV>()        // accepted pitch frames (st); the newest RAW_KEEP
    val jump = ArrayList<Double>()
    val vx = ArrayList<TV>()         // vowel x frames; the newest VX_KEEP
    var tMoving = 0.0
    var idleMs = 0.0
    val path = ArrayList<TXY>()      // position after each voiced tick; the newest PATH_KEEP
    var reanchors = 0
    val every = ArrayList<TXY>()     // (t, st, clarity) of the first EVERY_KEEP voiced ticks
    var sm = ArrayList<TV>()         // smoothed pitch since the last jump; the newest SM_KEEP
    var momentum = 0.0
    var gliding = false
    var undone = false
    var gapWhy = ""
    var continued = 0
}

/** What the indicators read after each tick (joystick_core Mover.state). */
data class MoverState(
    val tMs: Double = 0.0,
    val phase: String = "idle",       // idle | settle | move | gap
    val dx: Double = 0.0,
    val dy: Double = 0.0,
    val speed: Double = 0.0,          // dp/s (after the speed slider)
    val sm: Double? = null,           // smoothed pitch (st)
    val offset: Double? = null,       // from the mode's reference (st)
    val momentum: Double = 0.0,
    val xVowel: Double = 0.0,
    val vowel: Map<String, Double>? = null,
    val hz: Double = 0.0,
    val edge: String = "",
    val stop: String = "",
    val band: String? = null,         // voice | whistle (calibration v2's whistle band), null when idle
)

/** hum_start / hum_end. For hum_end: (stopX, stopY) where it stopped, (x, y) after the magnet, snapped = element index. */
data class MoverEvent(
    val kind: String, val tMs: Double, val x: Double, val y: Double,
    val tOn: Double = 0.0, val stopX: Double = 0.0, val stopY: Double = 0.0, val snapped: Int? = null,
    val durMs: Double = 0.0, val why: String = "", val reanchors: Int = 0, val continued: Int = 0,
)

/**
 * Ticks -> cursor, in dp. The position persists across sounds and across [enabled] off / on; only [recentre] moves
 * it to the centre and [setScreen] clamps it into new bounds.
 *
 * Sliders (Settings cursor_speed / cursor_pitch_sens, both 1.0 = the spec): [speedMul] multiplies the speed
 * (start_dp_s and max_dp_s); [pitchSens] divides the offset that gives full speed (home: per side; start:
 * full_speed_st; glide: full_st), never below dead zone + 0.5 st (glide: min_st). The dead zone itself is unchanged.
 */
class Mover(val spec: JoySpec, w: Double, h: Double, vowels: Map<String, DoubleArray>? = null,
            rangeSt: Pair<Double, Double>? = null) {
    var mode = spec.verticalMode; private set
    var range: Pair<Double, Double> = rangeSt ?: spec.homeRangeSt; private set
    var homeSetup: Double? = null; private set
    private val homeHist = ArrayDeque<Double>()
    val tickMs = spec.tickMs
    var w = w; private set
    var h = h; private set
    var x = w / 2; private set
    var y = h / 2; private set
    var cent: Map<String, DoubleArray> = (vowels ?: spec.centroidsBark).filterKeys { it in VOWELS }
    var vowelDeadZone = spec.vowelDeadZone
    var vowelFull = spec.vowelFull
    private var run = 0
    private var sound: Sound? = null
    /** The magnet's candidates; setting them does not move the cursor. */
    var elements: List<Element> = emptyList()
    var snapped: Int? = null; private set
    var enabled = true
    var state = MoverState(); private set
    val events = ArrayList<MoverEvent>()
    var lastStop = ""; private set
    var speedMul = 1.0
    var pitchSens = 1.0
    /** Calibration v2's whistle range (null = none): over its split, home mode steers by the whistle home / range. */
    var whistle: WhistleRange? = null; private set

    val active get() = sound != null

    /** home mode's reference (st): the relaxed hum, adapted by recent hum starts, or the range's middle. */
    val mid: Double get() {
        val hs = homeSetup ?: return (range.first + range.second) / 2
        if (homeHist.size < 3) return hs
        return JMath.clip(JMath.median(homeHist), hs - spec.adaptBoundSt, hs + spec.adaptBoundSt)
    }

    /** home mode: the offset (st) that gives full speed on that side. */
    fun fullSt(down: Boolean, whistle: Boolean = false): Double {
        val w = this.whistle
        val room = if (whistle && w != null) (if (down) w.homeSt - w.loSt else w.hiSt - w.homeSt)
            else if (down) mid - range.first else range.second - mid
        val base = max(spec.deadZoneSt + 1.0, spec.homeFullFrac * room)
        return max(spec.deadZoneSt + 0.5, base / pitchSens)
    }

    /** start mode's full-speed offset, after the sensitivity slider. */
    val startFullSt get() = max(spec.deadZoneSt + 0.5, spec.fullSpeedSt / pitchSens)
    private val glideFull get() = max(spec.glideMinSt, spec.glideFullSt / pitchSens)
    val startDpS get() = spec.startDpS * speedMul
    val maxDpS get() = spec.maxDpS * speedMul

    fun setMode(m: String) {
        val mm = if (m == "mid") "home" else m
        require(mm in MODES) { "mode $m" }
        mode = mm
    }

    fun setHome(st: Double?) { homeSetup = st; homeHist.clear() }
    fun setWhistle(w: WhistleRange?) { whistle = w }
    /** The pitch (st) is in the whistle band: at or over the split between the voice range's top and the whistle's bottom. */
    fun inWhistle(sm: Double): Boolean = whistle?.let { sm >= it.splitSt } ?: false
    /** home mode's reference for this pitch: the whistle home in the whistle band, else the voice home. */
    fun homeRef(sm: Double): Double = if (inWhistle(sm)) whistle!!.homeSt else mid
    fun setRange(lo: Double, hi: Double) { range = lo to hi }

    /** A new screen or a rotation: same coordinates, clamped into the new bounds. */
    fun setScreen(w: Double, h: Double, els: List<Element>) {
        this.w = w; this.h = h; elements = els
        x = JMath.clip(x, 0.0, w); y = JMath.clip(y, 0.0, h)
        snapped = null
    }


    fun recentre() { x = w / 2; y = h / 2; snapped = null }

    /** Put the cursor somewhere (restoring a persisted position): clamped, not snapped. */
    fun moveTo(nx: Double, ny: Double) { x = JMath.clip(nx, 0.0, w); y = JMath.clip(ny, 0.0, h); snapped = null }

    fun push(tk0: Tick) {
        var tk = tk0
        run = if (tk.voiced) run + 1 else 0
        var snd = sound
        if (snd == null) {
            if (tk.voiced && run >= spec.startTicks && enabled) {
                val tOn = tk.tMs - (run - 1) * tickMs
                snd = Sound(tOn, tk.tMs, x, y)
                sound = snd
                snapped = null
                events += MoverEvent("hum_start", tOn, x, y)
            } else {
                state = MoverState(tMs = tk.tMs, phase = "idle", stop = lastStop)
                return
            }
        }
        if (!enabled) { end(tk.tMs, "mode off"); return }
        if (!tk.voiced) {
            val near = snd.sm.isNotEmpty() && tk.f0Raw > 0 && abs(JMath.st(tk.f0Raw) - snd.sm.last().v) <= spec.continueNearSt
            if (tk.clarity >= spec.clarityContinue && tk.overDb >= spec.levelOverFloorDb && near) {
                tk = Tick(tk.tMs, tk.f0Raw, tk.clarity, tk.db, true, Double.NaN, Double.NaN, "", tk.f0Raw, tk.overDb)
                snd.continued++
            } else {
                if (snd.gapWhy.isEmpty()) snd.gapWhy = tk.why
                if (tk.tMs - snd.lastVoiced >= spec.endGapMs) end(tk.tMs, tk.why)
                else state = state.copy(phase = "gap", tMs = tk.tMs)
                return
            }
        }
        snd.lastVoiced = tk.tMs
        snd.gapWhy = ""
        val ps = pitch(snd, tk)
        val vowelW = vowel(snd, tk)
        var (dx, dy, xv) = direction(snd, tk.tMs)
        val dt = tickMs / 1000
        var n = hypot(dx, dy)
        var speed = 0.0
        var edge = state.edge
        if (n > 0) {
            snd.tMoving += tickMs / 1000
            snd.idleMs = 0.0
            val ramp = if (spec.speedRamp) min(1.0, snd.tMoving / spec.rampS) else 1.0
            speed = startDpS + (maxDpS - startDpS) * ramp
            if (n > 1) { dx /= n; dy /= n; n = 1.0 }
            val nx = x + dx * speed * dt
            val ny = y + dy * speed * dt
            x = JMath.clip(nx, 0.0, w); y = JMath.clip(ny, 0.0, h)
            edge = listOfNotNull("left".takeIf { nx < 0 }, "right".takeIf { nx > w }, "top".takeIf { ny < 0 },
                "bottom".takeIf { ny > h }).joinToString("+")
        } else {
            snd.idleMs += tickMs
            if (snd.idleMs >= spec.rampResetMs) snd.tMoving = 0.0
        }
        snd.path += TXY(tk.tMs, x, y)
        if (snd.path.size > PATH_KEEP) snd.path.removeAt(0)
        val moving = if (mode == "start") snd.ref != null else tk.tMs - snd.tOn >= spec.attackMs
        state = MoverState(tMs = tk.tMs, phase = if (moving) "move" else "settle", dx = dx, dy = dy, speed = speed * n,
            sm = ps?.first ?: state.sm, offset = if (ps != null) ps.second else state.offset, momentum = snd.momentum,
            band = ps?.let { if (inWhistle(it.first)) "whistle" else "voice" } ?: state.band,
            xVowel = xv ?: state.xVowel, vowel = vowelW, hz = tk.f0, edge = edge, stop = lastStop)
    }

    /** Returns (sm, offset) when this tick's pitch was taken, null when the jump guard held it back. */
    private fun pitch(snd: Sound, tk: Tick): Pair<Double, Double?>? {
        val s = JMath.st(tk.f0)
        val nS = max(1, JMath.pyRound(spec.smoothMs / tickMs))
        val recent = snd.raw.takeLast(nS).map { it.v }
        if (recent.isNotEmpty() && abs(s - JMath.median(recent)) > spec.jumpGuardSt) {
            snd.jump += s
            if (snd.jump.size * tickMs < spec.jumpPersistMs) return null
            snd.raw = ArrayList(snd.jump.map { TV(tk.tMs, it) })
            snd.jump.clear(); snd.sm = ArrayList(); snd.gliding = false
        } else {
            snd.jump.clear()
            snd.raw += TV(tk.tMs, s)
            if (snd.raw.size > RAW_KEEP) snd.raw.removeAt(0)
        }
        if (snd.every.size < EVERY_KEEP) snd.every += TXY(tk.tMs, s, tk.clarity)
        val nW = max(1, JMath.pyRound(spec.settleMs / tickMs))
        val win = snd.raw.takeLast(nW).filter { it.t >= snd.tOn + spec.attackMs }.map { it.v }
        val settled = win.size >= nW && (win.max() - win.min()) <= 2 * spec.settleTolSt
        val sm = JMath.mean(snd.raw.takeLast(nS).map { it.v })
        snd.sm += TV(tk.tMs, sm)
        if (snd.sm.size > SM_KEEP) snd.sm.removeAt(0)
        if (mode != "start") {
            onsetUndo(snd, tk.tMs, win, settled)
            if (mode == "glide") glide(snd, tk.tMs)
        }
        val ref0 = snd.ref
        if (ref0 == null) {
            val late = tk.tMs - snd.tOn >= spec.settleMaxMs && win.size >= max(1, nW / 2)
            if (settled || late) { snd.ref = JMath.median(win); snd.refT = tk.tMs; snd.posAtRef = x to y }
        } else if (mode == "start" && settled && tk.tMs - snd.tOn <= spec.reanchorGraceMs &&
            abs(JMath.median(win) - ref0) >= spec.reanchorMinSt) {
            snd.ref = JMath.median(win)
            snd.posAtRef?.let { (px, py) -> x = px; y = py }
            snd.refT = tk.tMs; snd.tMoving = 0.0; snd.reanchors++
        }
        val ref = when (mode) { "home" -> homeRef(sm); "glide" -> null; else -> snd.ref }
        return sm to ref?.let { sm - it }
    }

    private fun onsetUndo(snd: Sound, t: Double, win: List<Double>, settled: Boolean) {
        if (snd.undone || !settled || t - snd.tOn > spec.onsetGraceMs) return
        val early = snd.every.filter { it.t < t - win.size * tickMs }
        if (early.size < 3) return
        if (JMath.median(win) - JMath.median(early.map { it.x }) < spec.onsetMinBelowSt) return
        val cm = spec.onsetClarityMax
        if (cm != null && JMath.median(early.map { it.y }) >= cm) return
        snd.undone = true
        x = snd.posOnX; y = snd.posOnY
        snd.tMoving = 0.0; snd.momentum = 0.0; snd.gliding = false
        snd.sm = ArrayList(snd.sm.takeLast(1))
        snd.reanchors++
    }

    private fun glide(snd: Sound, t: Double) {
        if (t - snd.tOn < spec.attackMs || snd.sm.size < 2) return
        val old = snd.sm.lastOrNull { it.t <= t - spec.glideWindowMs } ?: return
        val change = snd.sm.last().v - old.v
        if (abs(change) >= spec.glideMinSt) {
            var step = snd.sm.last().v - snd.sm[snd.sm.size - 2].v
            if (!snd.gliding) { step = change; snd.gliding = true }
            snd.momentum = JMath.clip(snd.momentum + step / glideFull, -1.0, 1.0)
        } else {
            snd.gliding = false
        }
    }

    /** Soft weights over ee / ah / oo, or null (no formants, or nothing near a centre). */
    fun vowelWeights(f1: Double, f2: Double): Map<String, Double>? {
        if (f1.isNaN() || f2.isNaN() || cent.isEmpty()) return null
        return vowelWeightsBark(JMath.bark(f1), JMath.bark(f2))
    }

    fun vowelWeightsBark(b1: Double, b2: Double): Map<String, Double>? {
        val d = cent.mapValues { (_, c) -> hypot(b1 - c[0], b2 - c[1]) }
        if (d.values.min() > spec.rejectBark) return null
        val sg = spec.sigmaBark
        val w = d.mapValues { (_, v) -> exp(-v * v / (2 * sg * sg)) }
        val tot = w.values.sum()
        return w.mapValues { (_, v) -> v / tot }
    }

    private fun vowel(snd: Sound, tk: Tick): Map<String, Double>? {
        val w = vowelWeights(tk.f1, tk.f2)
        if (w != null) {
            snd.vx += TV(tk.tMs, (w["ee"] ?: 0.0) - (w["oo"] ?: 0.0))
            if (snd.vx.size > VX_KEEP) snd.vx.removeAt(0)
        }
        return w
    }

    private fun direction(snd: Sound, t: Double): Triple<Double, Double, Double?> {
        if ((mode == "start" && snd.ref == null) || snd.sm.isEmpty() || t - snd.tOn < spec.attackMs)
            return Triple(0.0, 0.0, null)
        val dy: Double
        if (mode == "glide") {
            val dead = spec.glideDead
            dy = -sign(snd.momentum) * min(1.0, max(0.0, (abs(snd.momentum) - dead) / (1 - dead)))
        } else {
            val sm = snd.sm.last().v
            val off = sm - (if (mode == "home") homeRef(sm) else snd.ref!!)
            val full = if (mode == "home") fullSt(off < 0, inWhistle(sm)) else startFullSt
            val dz = spec.deadZoneSt
            val mag = min(1.0, max(0.0, (abs(off) - dz) / (full - dz)))
            dy = -sign(off) * mag
        }
        val xs = snd.vx.filter { it.t > t - spec.vowelSmoothMs }.map { it.v }
        val xv = if (xs.isNotEmpty()) JMath.mean(xs) else 0.0
        val mx = min(1.0, max(0.0, (abs(xv) - vowelDeadZone) / (vowelFull - vowelDeadZone)))
        return Triple(sign(xv) * mx, dy, xv)
    }

    /** End the current sound now (e.g. cursor mode left); no-op when idle. */
    fun endSound(t: Double, why: String) { if (sound != null) end(t, why) }

    private fun end(t: Double, why: String) {
        val snd = sound ?: return
        sound = null
        lastStop = when (why) {
            "quiet" -> "quiet (level < floor+6dB)"; "unclear" -> "unclear (clarity < 0.8)"; "no pitch" -> "no pitch"
            else -> why
        }
        val cut = snd.lastVoiced - spec.rewindMs
        if (snd.path.isNotEmpty()) {
            val before = snd.path.lastOrNull { it.t <= cut }
            if (before != null) { x = before.x; y = before.y }
            else { val p = snd.posAtRef ?: (snd.posOnX to snd.posOnY); x = p.first; y = p.second }
        }
        val stopX = x
        val stopY = y
        val first = snd.every.take(6).map { it.x }
        if (first.isNotEmpty() && snd.lastVoiced - snd.tOn >= 200) {
            val m = JMath.median(first)
            if (m >= range.first - 1 && m <= range.second + 1) {
                homeHist.addLast(m)
                while (homeHist.size > spec.adaptHums) homeHist.removeFirst()
            }
        }
        snapped = Magnet.pick(elements, x, y, spec.snapDp, spec.maxAreaFrac * w * h)
        snapped?.let { i -> Magnet.snapPoint(elements[i], x, y, spec.centreMaxDp).let { (sx, sy) -> x = sx; y = sy } }
        events += MoverEvent("hum_end", t, x, y, snd.tOn, stopX, stopY, snapped, snd.lastVoiced - snd.tOn, lastStop,
            snd.reanchors, snd.continued)
        state = MoverState(tMs = t, phase = "idle", stop = lastStop)
    }

    companion object {
        val MODES = listOf("home", "glide", "start")
        val VOWELS = setOf("ee", "ah", "oo")
        private const val PATH_KEEP = 128
        private const val RAW_KEEP = 64
        private const val SM_KEEP = 64
        private const val VX_KEEP = 32
        private const val EVERY_KEEP = 64
    }
}

// ------------------------------------------------------------------------------------------------ clicks and pops

/** Pops -> a click after the pop-pop gap; a second pop inside the gap is pop pop (joystick_core.Clicker).
 *  Not used by the app (kept for JoystickParityTest's check against the prototype): the app folds pop to click at
 *  intake and the sequencer has no cursor-mode waits. */
class Clicker(private val gapMs: Double) {
    private var pending: Double? = null
    fun pop(t: Double): String? {
        val p = pending
        if (p != null && t - p <= gapMs) { pending = null; return "pop_pop" }
        pending = t
        return null
    }
    fun poll(t: Double): String? {
        val p = pending
        if (p != null && t - p > gapMs) { pending = null; return "click" }
        return null
    }
}

/** A burst the pop detector judged (joystick_core PopDetector.features + "pop"). */
data class Burst(val t: Double, val ticks: Int, val peakDb: Double, val peakI: Int, val riseDb: Double, val core: Int,
                 val voiced: Int, val pop: Boolean)

/** Ticks -> pops from the level alone (joystick_core.PopDetector). [push] returns a pop's start time when confirmed. */
class PopDetector(p: PopParams) {
    var c = p; private set
    private val hist = ArrayDeque<Tick>()
    private var burst: ArrayList<Tick>? = null
    private var before = 0.0
    private var pendStart = 0.0
    private var pendConfirm = 0.0
    private var pending = false
    private var run = 0
    private var lastVoice = -1e9
    private var lastPop = -1e9
    /** The bursts judged so far (the newest [BURSTS_KEEP]); the pop setup reads the ones since it started. */
    val bursts = ArrayList<Burst>()
    /** Bursts judged since creation (the index the setup starts from). */
    var burstCount = 0; private set

    fun features(b: List<Tick>): Burst {
        val ov = b.map { it.overDb }
        var pk = 0
        for (i in ov.indices) if (ov[i] > ov[pk]) pk = i
        val lead = ov.indexOfFirst { it >= ov[pk] - c.leadDb }
        var rise = Double.NEGATIVE_INFINITY
        for (i in 0..pk) rise = max(rise, ov[i] - (if (i > 0) ov[i - 1] else before))
        return Burst(b[0].tMs, b.size, ov[pk], pk - lead, rise, ov.count { it >= ov[pk] - c.coreDb },
            b.count { it.voiced }, false)
    }

    fun judge(f: Burst) = f.ticks <= c.maxTicks && f.core <= c.coreTicks && f.peakI <= c.peakWithin &&
        f.peakDb >= c.peakDb && f.riseDb >= c.riseDb && f.voiced <= c.maxVoiced

    fun push(tk: Tick): Double? {
        var out: Double? = null
        run = if (tk.voiced) run + 1 else 0
        if (run >= 3) { lastVoice = tk.tMs; pending = false; burst = null }
        val loud = tk.overDb >= c.loudDb
        if (pending && (tk.overDb >= c.confirmDb || tk.voiced)) pending = false
        if (pending && tk.tMs >= pendConfirm) { out = pendStart; pending = false; lastPop = pendStart }
        val b = burst
        if (b == null) {
            val quiet = hist.size == c.quietTicks && hist.all { it.overDb < c.loudDb }
            if (loud && quiet && tk.tMs - lastVoice >= c.afterVoiceMs && tk.tMs >= c.warmupMs) {
                burst = arrayListOf(tk); before = hist.last().overDb
            }
        } else if (loud && b.size <= c.maxTicks) {
            b += tk
        } else {
            burst = null
            val f0 = features(b)
            val f = f0.copy(pop = judge(f0) && b[0].tMs - lastPop > c.mergeMs)
            bursts += f
            burstCount++
            if (bursts.size > BURSTS_KEEP) bursts.removeAt(0)
            if (f.pop) { pending = true; pendStart = b[0].tMs; pendConfirm = tk.tMs + c.confirmMs }
        }
        hist.addLast(tk)
        while (hist.size > c.quietTicks) hist.removeFirst()
        return out
    }

    /** Thresholds from the setup's pops: half the weakest's dB within bounds; core = the widest + 1. {} if < 2. */
    fun calibrate(pops: List<Burst>): Map<String, Number> {
        if (pops.size < 2) return emptyMap()
        val peak = JMath.clip(pops.minOf { it.peakDb } * c.calPeakFrac, c.calPeakDb.first, c.calPeakDb.second)
        val rise = JMath.clip(pops.minOf { it.riseDb } * c.calRiseFrac, c.calRiseDb.first, c.calRiseDb.second)
        val core = min(max(pops.maxOf { it.core } + 1, c.calCoreTicks.first), c.calCoreTicks.second)
        c = c.copy(peakDb = peak, riseDb = rise, coreTicks = core)
        return mapOf("peak_db" to peak, "rise_db" to rise, "core_ticks" to core)
    }

    /** Replace all the thresholds (a profile change starts from the spec's). */
    fun params(p: PopParams) { c = p }

    /** Apply saved thresholds (a profile's pop block). */
    fun apply(peakDb: Double?, riseDb: Double?, coreTicks: Int?) {
        c = c.copy(peakDb = peakDb ?: c.peakDb, riseDb = riseDb ?: c.riseDb, coreTicks = coreTicks ?: c.coreTicks)
    }

    /** Does this burst look like a pop at the setup's loose bounds (joystick.Session._pop_setup)? */
    fun setupCandidate(f: Burst) = f.peakDb >= c.findPeakDb && f.riseDb >= c.findRiseDb && f.core <= c.calCoreTicks.second &&
        f.peakI <= c.peakWithin && f.ticks <= c.maxTicks && f.voiced <= c.maxVoiced

    companion object { const val BURSTS_KEEP = 64 }
}

/** The tick detector and the extractor hearing one pop: the second within merge_ms + 100 of the first is dropped
 *  (joystick.Session._pop). Times are stream ms on one clock. */
class PopMerge(private val windowMs: Double) {
    private var last = -1e9
    /** true = a new pop; false = the same pop again. */
    fun accept(t: Double): Boolean {
        if (abs(t - last) < windowMs) return false
        last = t
        return true
    }
    fun reset() { last = -1e9 }
}
