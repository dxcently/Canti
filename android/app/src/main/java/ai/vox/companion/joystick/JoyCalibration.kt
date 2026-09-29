package ai.vox.companion.joystick

import ai.vox.companion.ShapeGrade
import org.json.JSONArray
import org.json.JSONObject
import java.math.BigDecimal
import java.math.RoundingMode
import kotlin.math.abs

/*
 * The voice cursor's calibration (a port of extractor/joystick.py Session's setup: _home_setup, _range_setup,
 * _vowel_setup, _pop_setup, _fail / _retry / _skip), one profile per mic source (phone / usb / pico).
 *
 * Steps (the contract's names; the prototype's in brackets): hum [home], glide [range], vowels, pops, and calibration
 * v2's clicks, whistle, hiss, room. A voiced step waits for a steady note (8 ticks, <= 0.35 st per tick), records,
 * and either finishes (state step_done, or done after the last) or FAILS with a reason and waits: retry() records it
 * again, skip() keeps its defaults, records it in `skipped` and moves on to the next step by itself. Nothing is
 * skipped or restarted without the user. The discrete steps (pops, clicks, hiss) and the room read the gesture
 * extractor's events ([extractorEvent], with the gate numbers); they set the level gate and the click / pop rule
 * ([CalibV2]). The whistle step needs the ticks' pitch ceiling raised ([tickF0MaxHz]).
 * Checked tick for tick against the prototype (JoyCalibrationTest, golden "setup" / "setup_fail").
 * Pure JVM: no Android types (the service keeps the store and the pushes).
 */

/** Python's round(x, n) (round half to even on the exact binary value) and its "{:.nf}" format. */
internal object PyFmt {
    fun round(v: Double, n: Int): Double = BigDecimal(v).setScale(n, RoundingMode.HALF_EVEN).toDouble()
    fun fixed(v: Double, n: Int): String = BigDecimal(v).setScale(n, RoundingMode.HALF_EVEN).toPlainString()
    fun pct(v: Double): String = fixed(v * 100, 0) + "%"
}

/** A calibration: per source, stored locally. A skipped (or never measured) step's fields are null. */
data class JoyProfile(
    val source: String,
    val savedAtMs: Long = 0,
    val homeSt: Double? = null,
    val clarityOn: Double? = null,
    val loSt: Double? = null,
    val hiSt: Double? = null,
    val centroids: Map<String, DoubleArray>? = null,
    val vowelDeadZone: Double? = null,
    val vowelFull: Double? = null,
    /** Per vowel {n, right, none, left} (in-sample fractions), from the vowel step. */
    val vowelReport: Map<String, Map<String, Double?>>? = null,
    val pop: Map<String, Number>? = null,
    val popsHeard: Int? = null,
    val popLabels: List<String> = listOf("pop"),
    val skipped: List<String> = emptyList(),
    /** Per-person overrides for the native extractor (VxNative.overridesJson). Reserved: empty (the desktop go/no-go
     *  found no field worth it). */
    val extractor: Map<String, Any?> = emptyMap(),
    // calibration v2 (profile format version 2)
    /** The extractor's numbers for the pops / clicks / hiss steps' sounds. */
    val popsExamples: List<SoundExample>? = null,
    val clicksExamples: List<SoundExample>? = null,
    val hissExamples: List<SoundExample>? = null,
    val whistle: WhistleRange? = null,
    val room: RoomNoise? = null,
    /** Derived from the above when saved (the live gate is derived again from the examples with the current spec). */
    val levelGate: LevelGate? = null,
    val clickPop: ClickPopRule? = null,
    /** calib_save ran (the run is complete); per-step saves leave it false. */
    val complete: Boolean = false,
    /** The format version it was loaded from (1 = before calibration v2). */
    val loadedVersion: Int = VERSION,
) {
    /** The steps neither measured nor skipped (a version 1 profile: clicks, whistle, hiss, room). */
    val missingSteps: List<String> get() = JoyCalibration.STEPS.filter { s ->
        s !in skipped && when (s) {
            "hum" -> homeSt == null; "glide" -> loSt == null; "vowels" -> centroids == null; "pops" -> pop == null
            "clicks" -> clicksExamples == null; "whistle" -> whistle == null; "hiss" -> hissExamples == null
            else -> room == null
        }
    }
    val needsRecalibration: Boolean get() = missingSteps.isNotEmpty()

    /** The accuracy of each vowel: how often it steered its own way (ee right, ah none, oo left). */
    fun vowelAcc(v: String): Double? = vowelReport?.get(v)?.get(JoyCalibration.VOWEL_WANT[v])

    fun toJson(): JSONObject {
        val n = JSONObject.NULL
        fun o(v: Any?) = v ?: n
        val vowels = JSONObject()
        for (v in JoyCalibration.VOWELS) vowels.put(v, JSONObject().put("acc", o(vowelAcc(v))))
        return JSONObject()
            .put("source", source).put("version", VERSION).put("saved_at_ms", savedAtMs)
            .put("complete", complete)
            .put("home_hz", o(homeSt?.let { PyFmt.round(JMath.hz(it), 1) }))
            .put("range_lo_hz", o(loSt?.let { PyFmt.round(JMath.hz(it), 1) }))
            .put("range_hi_hz", o(hiSt?.let { PyFmt.round(JMath.hz(it), 1) }))
            .put("voicing_threshold", o(clarityOn))
            .put("vowels", vowels)
            .put("pops_heard", o(popsHeard))
            .put("skipped", JSONArray(skipped))
            .put("extractor", JSONObject(extractor))
            // beyond the contract: what the cursor needs back (the UI ignores these)
            .put("home_st", o(homeSt)).put("clarity_on", o(clarityOn)).put("lo_st", o(loSt)).put("hi_st", o(hiSt))
            .put("vowel_centroids_bark", o(centroids?.let { c -> JSONObject().also { j -> c.forEach { (k, v) -> j.put(k, JSONArray(v.toList())) } } }))
            .put("vowel_dead_zone", o(vowelDeadZone)).put("vowel_full", o(vowelFull))
            .put("vowel_report", o(vowelReport?.let { r -> JSONObject().also { j -> r.forEach { (k, m) -> j.put(k, JSONObject().also { q -> m.forEach { (a, b) -> q.put(a, o(b)) } }) } } }))
            .put("pop", o(pop?.let { JSONObject(it) }))
            .put("pop_labels", JSONArray(popLabels))
            // calibration v2
            .put("clicks_heard", o(clicksExamples?.size)).put("hiss_heard", o(hissExamples?.size))
            .put("whistle_lo_hz", o(whistle?.let { PyFmt.round(JMath.hz(it.loSt), 1) }))
            .put("whistle_hi_hz", o(whistle?.let { PyFmt.round(JMath.hz(it.hiSt), 1) }))
            .put("whistle_home_hz", o(whistle?.let { PyFmt.round(JMath.hz(it.homeSt), 1) }))
            .put("room_floor_dbfs", o(room?.floorDbfs))
            .put("level_gate", o(levelGate?.toJson()))
            .put("relabel_rule", clickPop != null)
            .put("missing_steps", JSONArray(missingSteps)).put("needs_recalibration", needsRecalibration)
            .put("whistle", o(whistle?.toJson())).put("room", o(room?.toJson()))
            .put("pops_examples", SoundExample.listJson(popsExamples)).put("clicks_examples", SoundExample.listJson(clicksExamples))
            .put("hiss_examples", SoundExample.listJson(hissExamples))
            .put("click_pop", o(clickPop?.toJson()))
    }

    /** The live level gate for this mic: from the examples and the room with the current spec (the default when the
     *  clicks step was never measured). */
    fun gate(spec: JoySpec): LevelGate = CalibV2.deriveGate(popsExamples, clicksExamples, hissExamples, room, spec)

    /** The live click / pop rule (null = never relabel). */
    fun rule(spec: JoySpec): ClickPopRule? = CalibV2.deriveClickPop(popsExamples, clicksExamples, spec)

    /** Put this profile into a live cursor and pop detector (the defaults for whatever it lacks). */
    fun applyTo(spec: JoySpec, mv: Mover, pd: PopDetector) {
        mv.setRange(loSt ?: spec.homeRangeSt.first, hiSt ?: spec.homeRangeSt.second)
        mv.setHome(homeSt)
        mv.cent = centroids ?: spec.centroidsBark.filterKeys { it in JoyCalibration.VOWELS }
        mv.vowelDeadZone = vowelDeadZone ?: spec.vowelDeadZone
        mv.vowelFull = vowelFull ?: spec.vowelFull
        pd.params(spec.pop)
        pop?.let { pd.apply(it["peak_db"]?.toDouble(), it["rise_db"]?.toDouble(), it["core_ticks"]?.toInt()) }
        mv.setWhistle(whistle)
    }

    /** The ticks' pitch ceiling for this profile: the whistle's when it has a whistle range, else the voice's. */
    fun tickF0MaxHz(spec: JoySpec): Double = if (whistle != null) spec.whistleTickF0MaxHz else spec.voiceTickF0MaxHz

    companion object {
        /** The profile format: 2 = calibration v2 (clicks, whistle, hiss, room; the level gate, the click / pop rule). */
        const val VERSION = 2

        fun fromJson(j: JSONObject): JoyProfile {
            fun d(k: String) = if (!j.has(k) || j.isNull(k)) null else j.getDouble(k)
            fun strs(k: String) = j.optJSONArray(k)?.let { a -> (0 until a.length()).map { a.getString(it) } }
            val cent = j.optJSONObject("vowel_centroids_bark")?.let { c ->
                c.keys().asSequence().associateWith { k -> c.getJSONArray(k).let { doubleArrayOf(it.getDouble(0), it.getDouble(1)) } }
            }
            val rep = j.optJSONObject("vowel_report")?.let { r ->
                r.keys().asSequence().associateWith { k ->
                    val m = r.getJSONObject(k)
                    m.keys().asSequence().associateWith { a -> if (m.isNull(a)) null else m.getDouble(a) }
                }
            }
            val pop = j.optJSONObject("pop")?.let { p ->
                mapOf<String, Number>("peak_db" to p.getDouble("peak_db"), "rise_db" to p.getDouble("rise_db"),
                    "core_ticks" to p.getInt("core_ticks"))
            }
            val ex = j.optJSONObject("extractor")?.let { e -> e.keys().asSequence().associateWith { e.get(it) as Any? } }
            fun obj(k: String) = if (!j.has(k) || j.isNull(k)) null else j.getJSONObject(k)
            fun arr(k: String) = if (!j.has(k) || j.isNull(k)) null else j.getJSONArray(k)
            return JoyProfile(j.getString("source"), j.optLong("saved_at_ms", 0), d("home_st"), d("clarity_on"),
                d("lo_st"), d("hi_st"), cent, d("vowel_dead_zone"), d("vowel_full"), rep, pop,
                if (j.isNull("pops_heard")) null else j.getInt("pops_heard"), strs("pop_labels") ?: listOf("pop"),
                strs("skipped") ?: emptyList(), ex ?: emptyMap(),
                SoundExample.listFrom(arr("pops_examples")), SoundExample.listFrom(arr("clicks_examples")),
                SoundExample.listFrom(arr("hiss_examples")), obj("whistle")?.let(WhistleRange::fromJson),
                obj("room")?.let(RoomNoise::fromJson),
                obj("level_gate")?.let { g -> LevelGate(g.getDouble("min_snr_db"), g.getDouble("min_level_dbfs"), g.optString("from", "default"),
                    g.optInt("n", 0), if (g.has("weakest_snr_db")) g.getDouble("weakest_snr_db") else null,
                    if (g.has("weakest_level_dbfs")) g.getDouble("weakest_level_dbfs") else null) },
                obj("click_pop")?.let(ClickPopRule::fromJson), j.optBoolean("complete", false), j.optInt("version", 1))
        }
    }
}

/**
 * One calibration run for one source. [push] every tick (stream ms), [extractorEvent] each gesture-extractor event
 * (the pop step learns which labels the person's pops get), commands from the UI. [status] is the calib_status map.
 * [clarityOn] is the voicing threshold the tick analyser should use now (it changes after the hum step).
 *
 * [steps] is the run: an ordered subset of [STEPS] (default all 8). The run starts on its first step and is `done`
 * once every one of them is finished (measured or skipped); a skip or a redo never starts a step outside it, nor
 * wraps round to an earlier one. The draft is [base] with the run's steps unskipped: a step outside the run keeps its
 * saved values and skip state (the save merges), a step in it is recorded again.
 */
class JoyCalibration(val spec: JoySpec, val source: String, base: JoyProfile? = null, steps: List<String>? = null) {
    companion object {
        val STEPS = listOf("hum", "glide", "vowels", "pops", "clicks", "whistle", "hiss", "room")
        /** The steps calibration v2 added (a version 1 profile lacks them). */
        val V2_STEPS = listOf("clicks", "whistle", "hiss", "room")
        val VOWELS = listOf("ee", "ah", "oo")
        val VOWEL_WANT = mapOf("ee" to "right", "ah" to "none", "oo" to "left")
        const val VOWEL_MIN_OWN = 0.5
        const val START_TIMEOUT_MS = 10000.0
        const val VOWEL_TIMEOUT_MS = 12000.0
        const val HOME_MIN_MS = 3000.0
        const val HOME_MAX_MS = 5000.0
        const val RANGE_MS = 5000.0
        const val POPS_WINDOW_MS = 8000.0
        const val POPS_NEED = 3
        const val VOWEL_FRAMES = 80
        const val VOWEL_FRAMES_MIN = 30
        /** The live pitch trace keeps this many ticks (5 s of 20 ms ticks). */
        const val TRACE_MAX = 250

        /** joystick.Session.steady: the ticks in runs of >= [run] whose pitch moves <= [step] st per tick (NaN =
         *  unvoiced). */
        fun steady(st: List<Double>, step: Double = 0.35, run: Int = 8): List<Double> {
            val n = st.size
            if (n < 2) return emptyList()
            val ok = BooleanArray(n - 1) { abs(st[it + 1] - st[it]) <= step }
            val keep = BooleanArray(n)
            var i = 0
            while (i < ok.size) {
                if (!ok[i]) { i++; continue }
                var j = i
                while (j < ok.size && ok[j]) j++
                if (j - i + 1 >= run) for (k in i..j) keep[k] = true
                i = j
            }
            return st.filterIndexed { k, _ -> keep[k] }
        }
    }

    /** The steps this run covers, in order (a calib_step / calib_redo of another step adds it). */
    val steps: MutableList<String> = (steps ?: STEPS).also { l ->
        require(l.isNotEmpty()) { "steps must name at least one step" }
        l.forEach { require(it in STEPS) { "unknown step '$it': steps are ${STEPS.joinToString(" | ")}" } }
        require(l.toSet().size == l.size) { "steps must not repeat" }
    }.toMutableList()

    var draft: JoyProfile = (base ?: JoyProfile(source)).let { b -> b.copy(source = source, skipped = b.skipped.filter { it !in this.steps }) }
        private set
    var step: String = this.steps.first(); private set
    /** waiting | recording | failed | step_done | done */
    var state: String = "waiting"; private set
    var reason: String? = null; private set
    /** The steps finished (measured or skipped) in this run. */
    val finished = LinkedHashSet<String>()
    /** Every finish (measured or skipped) so far, a redo of a finished step too: the per-step save watches it. */
    var finishCount = 0; private set
    var tNow = 0.0; private set
    var lastTick: Tick? = null; private set
    /** The live pitch trace (the last ~5 s of 20 ms ticks: Hz when voiced, null when not). */
    private val trace = ArrayDeque<Double?>()
    /** The pop step's detector (the spec's thresholds; pushed every tick, as the prototype's). */
    val pd = PopDetector(spec.pop)
    private val log = ArrayList<String>()
    /** What the steps said (the prototype's say()), newest last; for the debug socket. */
    val messages: List<String> get() = log

    val clarityOn: Double get() = draft.clarityOn ?: spec.clarityMin
    val stepDone get() = state == "step_done" || state == "done"

    // per step
    private class Su(val tPrompt: Double) {
        var t0: Double? = null
        var st = ArrayList<Double>()
        val cl = ArrayList<Double>()
        var recent = ArrayList<Double>()
        var quiet = 0.0
    }
    private var su: Su? = null
    private class Vs(var tPrompt: Double) {
        var i = 0
        var t0: Double? = null
        var quietMs: Double? = null
        val frames = VOWELS.associateWith { ArrayList<DoubleArray>() }
    }
    private var vs: Vs? = null
    private class Ps(val t0: Double, val n0: Int) {
        val ex = ArrayList<Triple<Double, String, SoundExample>>()
        var cand = 0
    }
    private var ps: Ps? = null
    /** clicks / hiss: the extractor's events in the window. */
    private class Ds(val kind: String, val t0: Double) {
        val ex = ArrayList<Triple<Double, String, SoundExample>>()
        var cand = 0
    }
    private var ds: Ds? = null
    private var ws: Su? = null
    private class Rm(val t0: Double) {
        val ex = ArrayList<Triple<Double, String, SoundExample>>()
        val db = ArrayList<Double>()
        var run = 0
        var maxRun = 0
    }
    private var rm: Rm? = null

    /** The ticks' pitch ceiling now: the whistle's during the whistle step and once there is a whistle range. */
    val tickF0MaxHz: Double get() = if (ws != null || draft.whistle != null) spec.whistleTickF0MaxHz else spec.voiceTickF0MaxHz

    private fun clearSteps() { su = null; vs = null; ps = null; ds = null; ws = null; rm = null }

    init { startStep(this.steps.first()) }

    /** The run's steps not finished yet, in order. */
    val remaining: List<String> get() = steps.filter { it !in finished }

    private fun say(m: String) { log += m; if (log.size > 50) log.removeAt(0) }

    // ---------------------------------------------------------------------------------------------- commands
    /** calib_step / calib_redo: record [s] (again). A step already waiting or recording is left alone, unless [force] (a redo). */
    fun startStep(s: String, tMs: Double? = null, force: Boolean = false) {
        require(s in STEPS) { "step must be one of $STEPS" }
        tMs?.let { tNow = it }
        if (s !in steps) steps += s
        if (!force && s == step && (state == "waiting" || state == "recording") && reason == null &&
            (su != null || vs != null || ps != null || ds != null || ws != null || rm != null)) return
        step = s; reason = null
        begin(s, true)
    }

    /** The step's state, timed from [tNow]; [announce] = say its prompt. */
    private fun begin(s: String, announce: Boolean) {
        state = "waiting"
        clearSteps()
        trace.clear()                                   // the live plot and checks are this step's

        val say: (String) -> Unit = { if (announce) this.say(it) }
        when (s) {
            "hum" -> { su = Su(tNow); say("HOME: hum 'mm' relaxed for 3 s, the note that comes out without thinking") }
            "glide" -> { su = Su(tNow); say("RANGE SETUP: glide from your LOWEST comfortable note to your HIGHEST and back (5 s)") }
            "vowels" -> { vs = Vs(tNow); say("VOWEL SETUP: hold 'ee' (as in see) for 2 s, at a middle pitch") }
            "pops" -> { ps = Ps(tNow, pd.burstCount); state = "recording"; say("POPS: pop your lips 3 times, about a second apart (8 s)") }
            "clicks" -> { ds = Ds("clicks", tNow); state = "recording"; say("CLICKS: click your tongue 3 times, about a second apart (8 s)") }
            "hiss" -> { ds = Ds("hiss", tNow); state = "recording"; say("HISS: 2 short 'tss' hisses, about a second apart (8 s)") }
            "whistle" -> { ws = Su(tNow); say("WHISTLE: whistle from your LOWEST note to your HIGHEST and back (5 s)") }
            "room" -> { rm = Rm(tNow); state = "recording"; say("ROOM: stay quiet for 3 s (the room's noise)") }
        }
    }

    /** calib_retry: record the failed step again. */
    fun retry(tMs: Double? = null) {
        check(state == "failed") { "nothing failed to retry" }
        startStep(step, tMs)
    }

    /** calib_skip: from failed, or before the step heard anything. The step's defaults stay, it goes in `skipped`, and
     *  the next step starts (or the run is done). */
    fun skip(tMs: Double? = null) {
        check(state == "failed" || state == "waiting" || (state == "recording" && step == "pops" && (ps?.cand ?: 0) == 0) ||
            (state == "recording" && (step == "clicks" || step == "hiss") && (ds?.cand ?: 0) == 0) || (state == "recording" && step == "room")) {
            "a step can be skipped when it failed or before it has heard anything"
        }
        tMs?.let { tNow = it }
        val s = step
        draft = when (s) {
            "hum" -> draft.copy(homeSt = null, clarityOn = null)
            "glide" -> draft.copy(loSt = null, hiSt = null)
            "vowels" -> draft.copy(centroids = null, vowelDeadZone = null, vowelFull = null, vowelReport = null)
            "pops" -> draft.copy(pop = null, popsHeard = null, popLabels = listOf("pop"), popsExamples = null)
            "clicks" -> draft.copy(clicksExamples = null)
            "hiss" -> draft.copy(hissExamples = null)
            "whistle" -> draft.copy(whistle = null)
            else -> draft.copy(room = null)
        }
        if (s in setOf("pops", "clicks", "hiss", "room")) derive()
        mark(s, true)
        clearSteps(); reason = null
        finished += s; finishCount++
        say("${name(s)}: skipped, its defaults stay")
        // the run's next unfinished step after this one; never a wrap round, never a step outside the run
        val next = steps.drop(steps.indexOf(s) + 1).firstOrNull { it !in finished }
        when {
            next != null -> startStep(next)
            remaining.isEmpty() -> state = "done"
            else -> state = "step_done"   // an earlier step of the run is still open: the UI picks it (calib_step)
        }
    }

    private fun name(s: String) = mapOf("hum" to "HOME", "glide" to "RANGE SETUP", "vowels" to "VOWEL SETUP", "pops" to "POPS",
        "clicks" to "CLICKS", "whistle" to "WHISTLE", "hiss" to "HISS", "room" to "ROOM")[s]!!

    /** The level gate and the click / pop rule from the examples so far and the room (joystick.Session._derive). */
    private fun derive() {
        val d = draft
        draft = d.copy(levelGate = CalibV2.deriveGate(d.popsExamples, d.clicksExamples, d.hissExamples, d.room, spec),
            clickPop = CalibV2.deriveClickPop(d.popsExamples, d.clicksExamples, spec))
    }

    /** The level gate the draft has now (the spec's default before any). */
    val gate: LevelGate get() = draft.levelGate ?: CalibV2.defaultGate(spec)

    private fun mark(s: String, skipped: Boolean) {
        val k = draft.skipped.toMutableSet()
        if (skipped) k += s else k -= s
        draft = draft.copy(skipped = STEPS.filter { it in k })
    }

    private fun fail(why: String) {
        clearSteps()
        state = "failed"; reason = why
        say("${name(step)}: $why")
    }

    private fun succeed() {
        clearSteps()
        mark(step, false)
        finished += step; finishCount++
        state = if (remaining.isEmpty()) "done" else "step_done"
    }

    // ---------------------------------------------------------------------------------------------- ticks

    /** A gesture-extractor event (stream ms, label, its gate numbers): the pop step matches them to the person's
     *  pops; the clicks and hiss steps take them as examples; the room step looks for transients. */
    fun extractorEvent(tStartMs: Double, label: String, raw: Map<String, Double?> = emptyMap()) {
        val e = Triple(tStartMs, label, SoundExample.of(label, raw))
        ps?.ex?.add(e); ds?.ex?.add(e); rm?.ex?.add(e)
    }

    fun push(tk: Tick) {
        // the first tick: the run started before any tick (tNow 0, not the stream's clock), so time the step from here;
        // else a mic that ran for 10 s before calib_start would fail its first step at once
        val first = lastTick == null
        tNow = tk.tMs
        lastTick = tk
        trace.addLast(if (tk.voiced) tk.f0 else null); while (trace.size > TRACE_MAX) trace.removeFirst()
        if (first && (state == "waiting" || state == "recording")) begin(step, false)
        pd.push(tk)
        if (state != "waiting" && state != "recording") return
        when {
            su != null && step == "hum" -> home(tk)
            su != null && step == "glide" -> range(tk)
            vs != null -> vowels(tk)
            ps != null -> pops(tk)
            ds != null -> discrete(tk)
            ws != null -> whistle(tk)
            rm != null -> room(tk)
        }
    }

    private fun started(s: Su, tk: Tick): Boolean {
        val v = if (tk.voiced) JMath.st(tk.f0) else Double.NaN
        s.quiet = if (tk.voiced) 0.0 else s.quiet + spec.tickMs
        if (s.t0 != null) { s.st += v; return true }
        s.recent += v
        if (s.recent.size > 8) s.recent.removeAt(0)
        if (s.recent.size == 8 && steady(s.recent).size == 8) {
            s.t0 = tk.tMs - 140; s.st = ArrayList(s.recent)
            state = "recording"
            return true
        }
        return false
    }

    private fun home(tk: Tick) {
        val s = su!!
        if (!started(s, tk)) {
            if (tk.tMs - s.tPrompt >= START_TIMEOUT_MS) fail("no steady hum heard in ${(START_TIMEOUT_MS / 1000).toInt()} s")
            return
        }
        if (tk.f0Raw > 0 && tk.overDb >= 10.0) s.cl += tk.clarity
        val dur = tk.tMs - s.t0!!
        if ((dur >= HOME_MIN_MS && s.quiet >= spec.endGapMs) || dur >= HOME_MAX_MS) {
            val v = steady(s.st)
            if (v.size < 40) { fail("too short or too rough (${v.size} steady ticks, need 40): a relaxed 'mm', 3 s"); return }
            val home = JMath.median(v)
            val (loC, hiC) = spec.personClarity
            val con = if (s.cl.isEmpty()) spec.clarityMin else JMath.clip(JMath.percentile(s.cl, 10.0) - spec.personMargin, loC, hiC)
            draft = draft.copy(homeSt = PyFmt.round(home, 2), clarityOn = PyFmt.round(con, 3))
            say("home ${PyFmt.fixed(home, 1)} st, voicing threshold ${PyFmt.fixed(con, 2)}")
            homeFits()
            succeed()
        }
    }

    /** The range the cursor would use now (this run's or the base profile's, else the spec's). */
    private val range get() = (draft.loSt ?: spec.homeRangeSt.first) to (draft.hiSt ?: spec.homeRangeSt.second)

    /** Home must leave room on both sides: at least 1 st inside the range. */
    private fun homeFits() {
        val h = draft.homeSt ?: return
        val (lo, hi) = range
        if (hi - lo < 4.0) return
        val c = JMath.clip(h, lo + 1.0, hi - 1.0)
        if (abs(c - h) > 0.05) {
            say("home ${PyFmt.fixed(h, 1)} st is at the edge of your range ${PyFmt.fixed(lo, 1)}-${PyFmt.fixed(hi, 1)}: moved to ${PyFmt.fixed(c, 1)}")
            draft = draft.copy(homeSt = PyFmt.round(c, 2))
        }
    }

    private fun range(tk: Tick) {
        val s = su!!
        if (!started(s, tk)) {
            if (tk.tMs - s.tPrompt >= START_TIMEOUT_MS) fail("no steady voice heard in ${(START_TIMEOUT_MS / 1000).toInt()} s")
            return
        }
        if (tk.tMs - s.t0!! >= RANGE_MS && s.quiet >= spec.endGapMs) {
            val v = steady(s.st)
            val (lo, hi) = if (v.size >= 50) JMath.percentile(v, 5.0) to JMath.percentile(v, 95.0) else 0.0 to 0.0
            if (hi - lo < 4.0) {
                fail("too small or too short (${PyFmt.fixed(hi - lo, 1)} st, ${v.size} steady ticks; need 4 st, 50 ticks): " +
                    "glide wider, lowest to highest and back")
                return
            }
            draft = draft.copy(loSt = PyFmt.round(lo, 2), hiSt = PyFmt.round(hi, 2))
            say("range ${PyFmt.fixed(lo, 1)}-${PyFmt.fixed(hi, 1)} st")
            homeFits()
            succeed()
        }
    }

    private fun vowels(tk: Tick) {
        val s = vs!!
        val v = VOWELS[s.i]
        val q = s.quietMs
        if (q != null && q < 200) {                        // the last vowel must end first
            s.quietMs = if (tk.voiced) 0.0 else q + spec.tickMs
            s.tPrompt = tk.tMs
            return
        }
        if (tk.voiced && !tk.f2.isNaN()) {
            if (s.t0 == null) s.t0 = tk.tMs
            state = "recording"
            if (tk.tMs - s.t0!! > 300) s.frames[v]!!.add(doubleArrayOf(JMath.bark(tk.f1), JMath.bark(tk.f2)))
        }
        val n = s.frames[v]!!.size
        if (!(s.t0 != null && (n >= VOWEL_FRAMES || (!tk.voiced && n >= VOWEL_FRAMES_MIN)))) {
            if (tk.tMs - s.tPrompt >= VOWEL_TIMEOUT_MS) {
                val secs = (VOWEL_TIMEOUT_MS / 1000).toInt()
                fail(if (n == 0) "no clear '$v' heard in $secs s"
                     else "only $n clear frames of '$v' in $secs s (need 30): hold it steady for 2 s")
            }
            return
        }
        s.i++
        s.t0 = null; s.quietMs = 0.0
        if (s.i < 3) { say("VOWEL SETUP: now hold '${VOWELS[s.i]}' for 2 s (stop first)"); return }
        val cent = s.frames.mapValues { (_, f) ->
            doubleArrayOf(PyFmt.round(JMath.median(f.map { it[0] }), 2), PyFmt.round(JMath.median(f.map { it[1] }), 2))
        }
        val (rep, dz, full) = vowelReport(cent, s.frames)
        val bad = VOWEL_WANT.entries.map { (k, want) -> Triple(k, want, rep[k]!![want] ?: 0.0) }.filter { it.third < VOWEL_MIN_OWN }
        if (bad.isNotEmpty()) {
            fail("they overlap: " + bad.joinToString(", ") { (k, w, x) -> "'$k' steered $w only ${PyFmt.pct(x)} of the time" })
            return
        }
        draft = draft.copy(centroids = cent, vowelDeadZone = dz, vowelFull = full, vowelReport = rep)
        say("vowels set")
        succeed()
    }

    /** joystick.Session.vowel_accuracy + _vowel_report: each frame through the vowel rule with the new centres
     *  (smoothed over the live 100 ms); widens the dead zone when 'ah' drifts. Starts from the spec's dead zone. */
    internal fun vowelReport(cent: Map<String, DoubleArray>, frames: Map<String, List<DoubleArray>>):
        Triple<Map<String, Map<String, Double?>>, Double, Double> {
        val mv = Mover(spec, 1.0, 1.0, cent)
        val nS = maxOf(1, JMath.pyRound(spec.vowelSmoothMs / spec.tickMs))
        val acc = frames.mapValues { (_, fr) ->
            val xs = fr.map { f -> mv.vowelWeightsBark(f[0], f[1]).let { w -> (w?.get("ee") ?: 0.0) - (w?.get("oo") ?: 0.0) } }
            if (xs.size >= nS) List(xs.size - nS + 1) { i -> var t = 0.0; for (k in 0 until nS) t += xs[i + k] * (1.0 / nS); t } else xs
        }
        var dz = spec.vowelDeadZone
        var full = spec.vowelFull
        val ah = acc["ah"]!!.let { x -> if (x.isEmpty()) listOf(0.0) else x.map { abs(it) } }
        if (ah.count { it > dz }.toDouble() / ah.size > 0.10) {
            val d = minOf(0.7, JMath.percentile(ah, 90.0))
            if (d > dz) {
                dz = PyFmt.round(d, 2); full = PyFmt.round(maxOf(full, d + 0.3), 2)
                say("'ah' drifted sideways: vowel dead zone widened to ${PyFmt.fixed(d, 2)}")
            }
        }
        val rep = acc.mapValues { (_, x) ->
            val n = x.size
            fun frac(p: (Double) -> Boolean): Double? = if (n == 0) null else PyFmt.round(x.count(p).toDouble() / n, 2)
            mapOf("n" to n.toDouble(), "right" to frac { it > dz }, "none" to frac { abs(it) <= dz }, "left" to frac { it < -dz })
        }
        return Triple(rep, dz, full)
    }

    private fun pops(tk: Tick) {
        val s = ps!!
        val nNew = pd.burstCount - s.n0
        val new = pd.bursts.takeLast(minOf(nNew, pd.bursts.size))
        val cand = new.filter { pd.setupCandidate(it) }
        s.cand = cand.size
        val done = cand.size >= 3 && tk.tMs - cand[2].t > 700
        if (!done && tk.tMs - s.t0 < POPS_WINDOW_MS) return
        val top = cand.sortedByDescending { it.peakDb }.take(3)
        val heard = top.count { pd.judge(it) }
        val matched = top.flatMap { f -> s.ex.filter { abs(it.first - f.t) < 250 } }
        val labels = matched.map { it.second }
        if (top.size < 2) {
            fail("heard ${top.size}/3 pops, need 2 (pop your lips a bit louder, a second apart)")
            return
        }
        val newc = pd.calibrate(top)
        val learnt = labels.toSet().filter { l -> labels.count { it == l } >= 2 && l in setOf("pop", "click") }
        val popLabels = (setOf("pop") + draft.popLabels + learnt).sorted()
        draft = draft.copy(pop = newc, popsHeard = top.size, popLabels = popLabels,
            popsExamples = matched.filter { it.second in CalibV2.GATE_LABELS }.map { it.third })
        derive()
        say("POPS: heard ${top.size}/3 (the old thresholds: $heard/3); peak >= ${PyFmt.fixed(newc["peak_db"]!!.toDouble(), 0)} dB, " +
            "rise >= ${PyFmt.fixed(newc["rise_db"]!!.toDouble(), 0)} dB, extractor said ${labels.groupingBy { it }.eachCount()}")
        succeed()
    }

    /** clicks (3 tongue clicks: any discrete label up to max_dur_ms, the guided single clicks come out as any of
     *  the three) or hiss (2 'tss': label hiss): the strongest `ask` of the extractor's events are the examples. */
    private fun discrete(tk: Tick) {
        val s = ds!!
        val c = if (s.kind == "clicks") spec.clicksStep else spec.hissStep
        val cand = s.ex.filter { (_, lab, e) ->
            e.snrDb != null && e.levelDb != null &&
                if (s.kind == "clicks") lab in CalibV2.GATE_LABELS && (e.durMs ?: 0.0) <= c.maxDurMs!! else lab == "hiss"
        }
        s.cand = cand.size
        val done = cand.size >= c.ask && tk.tMs - cand.map { it.first }.sorted()[c.ask - 1] > c.settleMs
        if (!done && tk.tMs - s.t0 < c.windowMs) return
        val top = cand.sortedByDescending { it.third.snrDb!! }.take(c.ask)
        if (top.size < c.need) {
            val what = if (s.kind == "clicks") "clicks" else "hisses"
            val tip = if (s.kind == "clicks") "click your tongue a bit louder, about a second apart" else "a short, sharp 'tss', a bit louder"
            fail("heard ${top.size}/${c.ask} $what, need ${c.need} ($tip)")
            return
        }
        val ex = top.map { it.third }
        draft = if (s.kind == "clicks") draft.copy(clicksExamples = ex) else draft.copy(hissExamples = ex)
        derive()
        val g = gate
        say("${name(s.kind)}: heard ${top.size}/${c.ask} (${top.joinToString(", ") { it.second }}), quietest " +
            "${PyFmt.fixed(ex.minOf { it.snrDb!! }, 0)} dB over the floor; level gate >= ${PyFmt.fixed(g.minSnrDb, 0)} dB and " +
            "${PyFmt.fixed(g.minLevelDbfs, 0)} dBFS")
        succeed()
    }

    /** A 5 s whistle glide at the whistle's pitch ceiling: the range (5th / 95th percentile of the steady ticks), its
     *  home (the median) and the split from the voice range (halfway between the voice's top and the whistle's bottom). */
    private fun whistle(tk: Tick) {
        val s = ws!!
        if (!started(s, tk)) {
            if (tk.tMs - s.tPrompt >= START_TIMEOUT_MS) fail("no steady whistle heard in ${(START_TIMEOUT_MS / 1000).toInt()} s")
            return
        }
        if (tk.tMs - s.t0!! < spec.whistleGlideMs || s.quiet < spec.endGapMs) return
        val v = steady(s.st)
        val n = spec.whistleMinSteadyTicks
        val (lo, hi) = if (v.size >= n) JMath.percentile(v, 5.0) to JMath.percentile(v, 95.0) else 0.0 to 0.0
        if (hi - lo < spec.whistleMinRangeSt) {
            fail("too small or too short (${PyFmt.fixed(hi - lo, 1)} st, ${v.size} steady ticks; need " +
                "${PyFmt.fixed(spec.whistleMinRangeSt, 0)} st, $n ticks): whistle from your lowest to your highest and back")
            return
        }
        val top = range.second
        if (lo <= top) {
            fail("the whistle overlaps your voice range (whistle from ${PyFmt.fixed(JMath.hz(lo), 0)} Hz, voice up to " +
                "${PyFmt.fixed(JMath.hz(top), 0)} Hz): whistle higher, or skip")
            return
        }
        val w = WhistleRange(PyFmt.round(lo, 2), PyFmt.round(hi, 2), PyFmt.round(JMath.median(v), 2), PyFmt.round((top + lo) / 2, 2))
        draft = draft.copy(whistle = w)
        say("whistle ${PyFmt.fixed(lo, 1)}-${PyFmt.fixed(hi, 1)} st (${PyFmt.fixed(JMath.hz(lo), 0)}-${PyFmt.fixed(JMath.hz(hi), 0)} Hz), " +
            "home ${PyFmt.fixed(w.homeSt, 1)} st, over ${PyFmt.fixed(w.splitSt, 1)} st steers by the whistle")
        succeed()
    }

    /** 3 s of quiet: the ticks' level (the floor), no steady tone, and the loudest extractor transient; fails when that
     *  transient is as loud as the quietest calibrated sound in both SNR and level (the gate could not keep it out). */
    private fun room(tk: Tick) {
        val r = rm!!
        if (tk.tMs - r.t0 <= spec.roomWindowMs) {
            r.db += tk.db
            r.run = if (tk.voiced) r.run + 1 else 0
            r.maxRun = maxOf(r.maxRun, r.run)
        }
        if (tk.tMs - r.t0 < spec.roomWindowMs + spec.roomSettleMs) return
        if (r.maxRun >= spec.roomMaxVoicedRunTicks) {
            fail("not quiet: a steady tone was heard for ${PyFmt.fixed(r.maxRun * spec.tickMs, 0)} ms (a voice, music or a hum): " +
                "make the room quiet and retry")
            return
        }
        val tr = r.ex.filter { (t, lab, e) -> lab in CalibV2.GATE_LABELS && t >= r.t0 && t <= r.t0 + spec.roomWindowMs &&
            e.snrDb != null && e.levelDb != null }
        val ts = tr.maxOfOrNull { it.third.snrDb!! }
        val tl = tr.maxOfOrNull { it.third.levelDb!! }
        val ex = listOf(draft.popsExamples, draft.clicksExamples, draft.hissExamples).flatMap { it ?: emptyList() }
            .filter { it.snrDb != null && it.levelDb != null }
        if (tr.isNotEmpty() && ex.isNotEmpty()) {
            val wsn = ex.minOf { it.snrDb!! }; val wl = ex.minOf { it.levelDb!! }
            val cap = spec.gateCapBelowWeakestDb
            if (ts!! + spec.gateRoomMarginDb > wsn - cap && tl!! + spec.gateRoomMarginDb > wl - cap) {
                fail("a sound in the room was as loud as your quietest calibrated sound (${PyFmt.fixed(ts, 0)} dB over the floor, " +
                    "yours ${PyFmt.fixed(wsn, 0)} dB): make the room quieter and retry, or skip")
                return
            }
        }
        val room = RoomNoise(if (r.db.isEmpty()) null else PyFmt.round(JMath.median(r.db), 2), ts?.let { PyFmt.round(it, 2) },
            tl?.let { PyFmt.round(it, 2) }, tr.size)
        draft = draft.copy(room = room)
        derive()
        say("room: floor ${room.floorDbfs} dBFS, ${tr.size} transient(s); level gate >= ${PyFmt.fixed(gate.minSnrDb, 0)} dB and " +
            "${PyFmt.fixed(gate.minLevelDbfs, 0)} dBFS")
        succeed()
    }

    // ---------------------------------------------------------------------------------------------- status

    private val prompts = mapOf(
        "hum" to "Hum 'mm' relaxed for 3 s: the note that comes out without thinking",
        "glide" to "Glide from your lowest comfortable note to your highest and back (5 s)",
        "vowels" to "Hold 'ee', then 'ah', then 'oo', 2 s each at a middle pitch",
        "pops" to "Pop your lips 3 times, about a second apart",
        "clicks" to "Click your tongue 3 times, about a second apart",
        "whistle" to "Whistle from your lowest note to your highest and back (5 s)",
        "hiss" to "Two short 'tss' hisses, about a second apart",
        "room" to "Stay quiet for 3 s: Canti listens to the room",
    )

    private fun progress(): Double {
        if (state == "step_done" || state == "done") return 1.0
        val t = tNow
        su?.let { s -> val t0 = s.t0 ?: return 0.0; return minOf(1.0, (t - t0) / (if (step == "hum") HOME_MIN_MS else RANGE_MS)) }
        vs?.let { s -> return minOf(1.0, (s.i + minOf(1.0, s.frames[VOWELS[minOf(s.i, 2)]]!!.size.toDouble() / VOWEL_FRAMES)) / 3) }
        ps?.let { s -> return minOf(1.0, maxOf(s.cand.toDouble() / POPS_NEED, (t - s.t0) / POPS_WINDOW_MS)) }
        ds?.let { s -> val c = if (s.kind == "clicks") spec.clicksStep else spec.hissStep
            return minOf(1.0, maxOf(s.cand.toDouble() / c.ask, (t - s.t0) / c.windowMs)) }
        ws?.let { s -> val t0 = s.t0 ?: return 0.0; return minOf(1.0, (t - t0) / spec.whistleGlideMs) }
        rm?.let { r -> return minOf(1.0, (t - r.t0) / spec.roomWindowMs) }
        return 0.0
    }

    private fun sub(): String? = when {
        state == "failed" -> "failed: retry or skip"
        state == "waiting" && step == "whistle" -> "waiting for a steady whistle"
        state == "waiting" && step != "vowels" -> "waiting for a steady note"
        rm != null -> "stay quiet"
        vs != null -> vs!!.let { s -> if (s.quietMs != null && s.quietMs!! < 200) "stop, then '${VOWELS[s.i]}'" else "now '${VOWELS[s.i]}'" }
        else -> null
    }

    /** The user's scale for the tolerant grade, from the draft (nulls where a step has not measured yet); during the
     *  whistle step the whistle range (a whistle is judged against a voice's notes never). */
    fun scale(): ShapeGrade.Scale? {
        if (step == "whistle") return draft.whistle?.let { w -> ShapeGrade.Scale(JMath.hz(w.loSt), JMath.hz(w.homeSt), JMath.hz(w.hiSt)) }
        val lo = draft.loSt?.let(JMath::hz); val home = draft.homeSt?.let(JMath::hz); val hi = draft.hiSt?.let(JMath::hz)
        return if (lo != null || home != null || hi != null) ShapeGrade.Scale(lo, home, hi) else null
    }

    /** The wanted shape of a pitched step, for the live grade (contract C `expect` / `live.checks`). The glides go
     *  lowest to highest AND BACK (their prompts): an arch from low, not a rise; the lengths are the steps' own. */
    fun wantFor(step: String): ShapeGrade.Want? = when (step) {
        "hum" -> ShapeGrade.Want(listOf("flat"), "home", null, "hum", durS = HOME_MIN_MS / 1000)
        "glide" -> ShapeGrade.Want(listOf("arch"), "low", null, "hum", durS = RANGE_MS / 1000)
        "whistle" -> ShapeGrade.Want(listOf("arch"), "low", null, "whistle", durS = spec.whistleGlideMs / 1000)
        else -> null
    }

    /** The `expect` map for a step (contract B), or null for a step with no pitched shape. */
    fun expectFor(step: String): Map<String, Any?>? {
        val w = wantFor(step) ?: return null
        return linkedMapOf<String, Any?>("sequence" to w.sequence, "start" to w.start, "span_st" to 4, "tol_st" to 1.5,
            "dur_s" to ShapeGrade.wantedDurS(w), "gap_s" to w.gapS, "tone" to w.tone)
    }

    /** The hub's one-word result for a step: "ok", "skipped", or "·" (not done yet). */
    fun resultWord(s: String): String = when {
        s in draft.skipped -> "skipped"
        s !in draft.missingSteps -> "ok"
        else -> "·"
    }

    /** The calib_status map (the contract in android/PROTOCOL.md). [calibrated]: this source has a saved profile. */
    fun status(calibrated: Boolean, liveMover: Mover? = null): Map<String, Any?> {
        val tk = lastTick
        val w = if (tk != null && tk.voiced) (liveMover ?: Mover(spec, 1.0, 1.0, draft.centroids)).vowelWeights(tk.f1, tk.f2) else null
        val best = w?.maxByOrNull { it.value }
        val liveChecks = wantFor(step)?.let { ShapeGrade.live(it, trace.toList(), 20, scale()) } ?: emptyList()
        val live = mapOf("voiced" to (tk?.voiced == true), "pitch_hz" to tk?.takeIf { it.voiced }?.f0,
            "level_db" to tk?.db, "vowel" to best?.key, "vowel_conf" to best?.value,
            "trace_hz" to trace.toList(),
            "checks" to liveChecks.map { c -> mapOf("id" to c.id, "label" to c.label, "state" to c.state, "value" to c.value, "want" to c.want) })
        val pos = linkedMapOf<String, Any?>("i" to (STEPS.indexOf(step) + 1), "n" to STEPS.size)
        val hub = STEPS.map { s -> linkedMapOf<String, Any?>("id" to s, "done" to (s !in draft.missingSteps), "result_word" to resultWord(s)) }
        return linkedMapOf(
            "active" to true, "source" to source, "step" to step, "state" to state,
            "prompt" to prompts[step], "sub" to sub(), "progress" to progress(),
            "waiting_for_steady" to (state == "waiting"), "live" to live,
            "heard" to mapOf("pops_n" to (ps?.cand ?: if (step == "pops" && "pops" in finished) draft.popsHeard ?: 0 else 0),
                "pops_need" to POPS_NEED,
                "clicks_n" to (ds?.takeIf { it.kind == "clicks" }?.cand ?: if (step == "clicks" && "clicks" in finished) draft.clicksExamples?.size ?: 0 else 0),
                "clicks_need" to spec.clicksStep.ask,
                "hiss_n" to (ds?.takeIf { it.kind == "hiss" }?.cand ?: if (step == "hiss" && "hiss" in finished) draft.hissExamples?.size ?: 0 else 0),
                "hiss_need" to spec.hissStep.ask),
            "step_done" to stepDone, "reason" to reason, "skipped" to draft.skipped.filter { it in steps },
            "steps" to steps.toList(), "remaining" to remaining,
            "expect" to expectFor(step), "scale" to scale()?.let { s -> mapOf("low_hz" to s.loHz, "home_hz" to s.homeHz, "high_hz" to s.hiHz) },
            "pos" to pos, "hub" to hub,
            "result" to if (finished.isNotEmpty()) draft.toJson() else null, "calibrated" to calibrated,
        )
    }
}
