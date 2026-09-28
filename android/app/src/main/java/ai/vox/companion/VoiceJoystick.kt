package ai.vox.companion

import android.content.Context
import android.os.Handler
import android.os.SystemClock
import ai.vox.companion.audio.MicSettings
import ai.vox.companion.audio.PhoneMicSource
import ai.vox.companion.audio.VxNative
import ai.vox.companion.joystick.CalibV2
import ai.vox.companion.joystick.Element
import ai.vox.companion.joystick.JoyCalibration
import ai.vox.companion.joystick.JoyIndicators
import ai.vox.companion.joystick.JoyProfile
import ai.vox.companion.joystick.JoySpec
import ai.vox.companion.joystick.Magnet
import ai.vox.companion.joystick.Mover
import ai.vox.companion.joystick.PopDetector
import ai.vox.companion.joystick.PopMerge
import ai.vox.companion.joystick.SoundExample
import ai.vox.companion.joystick.Tick
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.Executors

/**
 * The voice joystick in the service (wiki/voice-cursor.md "Joystick cursor"; user decisions 2026-09-27): in cursor
 * mode with the phone or a USB mic as the sound source, the mic's per-20 ms ticks (native, vx_tick.cpp) drive the
 * cursor continuously ([Mover]: pitch against the home note up / down, the vowel sideways; it moves only while a hum
 * lasts and stays where it ends), the magnet snaps it to a clickable element within 48 dp, and a pop clicks (the
 * ticks' own pop detector beside the extractor's; one pop heard by both counts once). The Pico keeps the discrete
 * cursor. The position persists (prefs, dp); only [recentre] and a rotation's clamp move it otherwise.
 *
 * It also runs the calibration ([JoyCalibration], one profile per mic source, SharedPreferences "canti_joystick"
 * `calib_<source>`) for the app's setup screen: [calibCommand] (UiBridge, the debug socket) and [uiSink] (the
 * `calib_status` pushes). While a calibration records, every mic sound is dropped (nothing acts).
 *
 * Calibration v2: the source's profile also sets the mic's level gate and click / pop rule ([PhoneMicSource.levelGate],
 * applied to every phone / USB sound, cursor mode or not; the spec's default gate when uncalibrated; off while a
 * calibration records, which must hear the quiet sounds too), the whistle range (the cursor's whistle band) and the
 * ticks' pitch ceiling (the whistle's while it has a whistle range or the whistle step runs).
 *
 * Main thread, except [PhoneMicSource.tickSink] (the capture thread), which only copies and posts.
 */
class VoiceJoystick(
    private val ctx: Context,
    private val overlay: Overlay,
    private val settings: Settings,
    private val main: Handler,
    private val readElements: () -> List<Target>,
    private val screenPx: () -> Pair<Int, Int>,
) {
    val spec: JoySpec = JoySpec.parse(ctx.assets.open(JoySpec.ASSET).bufferedReader().use { it.readText() })
    private val art = JoyIndicators.CursorArt(ctx.assets.open(JoyIndicators.CursorArt.ASSET).bufferedReader().use { it.readText() })
    private val prefs = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    private val density get() = ctx.resources.displayMetrics.density
    private val reader = Executors.newSingleThreadExecutor { r -> Thread(r, "joystick-tree").apply { isDaemon = true } }

    val mover: Mover = screenDp().let { (w, h) -> Mover(spec, w, h) }
    private val pd = PopDetector(spec.pop)
    private val merge = PopMerge(spec.pop.mergeMs + 100)
    private var mic: PhoneMicSource? = null
    private var source = ""
    /** Driving the cursor now (cursor mode, a mic source, the service armed). */
    var on = false; private set
    private var profile: JoyProfile? = null
    private var elements: List<Target> = emptyList()
    private var readPending = false
    private var ticks = 0L
    private var pops = 0L
    private var merged = 0L
    private var lastFace: String? = null
    private var lastT = 0.0

    // ---------------------------------------------------------------------------------------------- on / off

    /** The service's state changed (mode, sound source, arming, the mic source object). */
    fun update(cursorMode: Boolean, source: String, mic: PhoneMicSource?) {
        if (source != this.source) { this.source = source; loadProfile() }
        if (mic !== this.mic) { this.mic?.let { detach(it) }; this.mic = mic; mic?.let { attach(it) } }
        val want = cursorMode && source != MicSettings.PICO && mic != null
        if (want != on) {
            on = want
            if (on) start() else stop()
            EventLog.ev("joystick", "state" to if (on) "on" else "off", "source" to source, "calibrated" to (profile != null))
        }
        applyTicks()
        mic?.extractorJson = VxNative.overridesJson(profile?.extractor)
    }

    private fun attach(m: PhoneMicSource) {
        m.tickSink = { rows, n, base -> val copy = rows.copyOf(n * VxNative.TICK_COLS); main.post { onTicks(copy, n, base) } }
        m.soundFilter = ::filter
        applyGate()
    }

    private fun detach(m: PhoneMicSource) {
        m.tickSink = null; m.soundFilter = null
        m.levelGate = null; m.clickPopRule = null
        m.setTicks(false, spec.clarityMin)
    }

    private fun applyTicks() {
        val cal = calib
        mic?.setTicks(on || cal != null, cal?.clarityOn ?: profile?.clarityOn ?: spec.clarityMin,
            cal?.tickF0MaxHz ?: profile?.tickF0MaxHz(spec) ?: spec.voiceTickF0MaxHz)
    }

    /** The mic's level gate and click / pop rule: this source's profile (the default gate when uncalibrated), none while
     *  a calibration records or for the Pico. */
    private fun applyGate() {
        val m = mic ?: return
        val live = calib == null && source != MicSettings.PICO && source.isNotEmpty()
        m.levelGate = if (live) profile?.gate(spec) ?: CalibV2.defaultGate(spec) else null
        m.clickPopRule = if (live) profile?.rule(spec) else null
    }

    private fun start() {
        overlay.setJoystick(art)
        // the position never resets: this process's cursor, else the one saved before a restart
        val px = prefs.getFloat(KEY_X, Float.NaN); val py = prefs.getFloat(KEY_Y, Float.NaN)
        if (!overlay.placed && !px.isNaN() && !py.isNaN()) overlay.moveTo(px * density, py * density)
        overlay.showCursor()
        val (w, h) = screenDp()
        mover.setScreen(w, h, emptyList())
        mover.moveTo(overlay.x / density.toDouble(), overlay.y / density.toDouble())
        mover.enabled = true
        applySliders()
        draw(jump = true)
    }

    private fun stop() {
        mover.endSound(lastT, "joystick off"); mover.events.clear()
        mover.enabled = false
        overlay.joyBrackets(null)
        overlay.setBadgeJoy(null)
        overlay.setJoystick(null)
        lastFace = null
        save()
    }

    fun applySliders() {
        mover.speedMul = settings.cursorSpeed
        mover.pitchSens = settings.cursorPitchSens
    }

    private fun loadProfile() {
        profile = if (source == MicSettings.PICO || source.isEmpty()) null else load(source)
        val p = profile ?: JoyProfile(source)
        p.applyTo(spec, mover, pd)
        applyGate()
        EventLog.ev("joystick", "profile" to source, "calibrated" to (profile != null), "skipped" to profile?.skipped?.joinToString(" "),
            "version" to profile?.loadedVersion, "missing_steps" to profile?.missingSteps?.joinToString(" "),
            "level_gate" to mic?.levelGate?.toJson(), "relabel_rule" to (mic?.clickPopRule != null), "whistle" to (p.whistle != null))
    }

    // ---------------------------------------------------------------------------------------------- ticks

    private fun onTicks(rows: DoubleArray, n: Int, baseMs: Long) {
        val cal = calib
        for (i in 0 until n) {
            val tk = tickOf(rows, i * VxNative.TICK_COLS)
            ticks++
            // a new capture stream (the mic restarted) starts its clock over: end the sound, forget the last pop
            if (tk.tMs < lastT - 1) {
                mover.endSound(lastT, "mic restarted"); merge.reset()
                for (ev in mover.events) onEvent(ev.kind, ev)
                mover.events.clear()
                EventLog.ev("joystick", "event" to "clock", "from_ms" to lastT.toLong(), "to_ms" to tk.tMs.toLong())
            }
            lastT = tk.tMs
            if (cal != null) {
                val before = cal.clarityOn
                val f0Before = cal.tickF0MaxHz
                cal.push(tk)
                if (cal.clarityOn != before || cal.tickF0MaxHz != f0Before) applyTicks()
                continue
            }
            if (!on) continue
            mover.push(tk)
            pd.push(tk)?.let { t -> tickPop(t, baseMs) }
            for (ev in mover.events) onEvent(ev.kind, ev)
            mover.events.clear()
        }
        if (cal != null) calibChanged(false)
        else if (on) draw(jump = false)
    }

    private fun tickOf(r: DoubleArray, o: Int): Tick {
        val voiced = r[o + VxNative.TICK_VOICED] > 0.5
        val db = r[o + VxNative.TICK_DB]
        val why = VxNative.TICK_WHY_NAMES.getOrElse(r[o + VxNative.TICK_WHY].toInt()) { "" }
        return Tick(r[o + VxNative.TICK_T_MS], if (voiced) r[o + VxNative.TICK_F0] else 0.0, r[o + VxNative.TICK_CLARITY], db, voiced,
            r[o + VxNative.TICK_F1], r[o + VxNative.TICK_F2], why, r[o + VxNative.TICK_F0_RAW], db - r[o + VxNative.TICK_FLOOR])
    }

    private fun onEvent(kind: String, ev: ai.vox.companion.joystick.MoverEvent) {
        when (kind) {
            "hum_start" -> { overlay.joyBrackets(null); refreshElements() }
            "hum_end" -> {
                val sn = ev.snapped
                val t = sn?.let { mover.elements.getOrNull(it) }
                overlay.joyBrackets(t?.let { e -> intArrayOf((e.l * density).toInt(), (e.t * density).toInt(), (e.r * density).toInt(), (e.b * density).toInt()) })
                draw(jump = true)
                save()
                EventLog.ev("joystick", "event" to "stop", "x_dp" to r1(ev.x), "y_dp" to r1(ev.y), "stop_dp" to "${r1(ev.stopX)},${r1(ev.stopY)}",
                    "ms" to ev.durMs.toLong(), "why" to ev.why, "snapped" to t?.label, "reanchors" to ev.reanchors)
                refreshElements()
            }
        }
    }

    private fun r1(v: Double) = Math.round(v * 10) / 10.0

    /** The clickable elements on screen for the magnet, read off the main thread; the mover gets them in dp. */
    private fun refreshElements() {
        if (readPending) return
        readPending = true
        reader.execute {
            val t = try { readElements() } catch (e: Exception) { emptyList() }
            main.post {
                readPending = false
                elements = t
                val d = density.toDouble()
                mover.elements = t.map { Element(it.left / d, it.top / d, it.right / d, it.bottom / d, it.label) }
            }
        }
    }

    private fun tickPop(tStreamMs: Double, baseMs: Long) {
        val t = tStreamMs.toLong()
        if (!merge.accept(t.toDouble())) { merged++; return }
        pops++
        EventLog.ev("joystick", "event" to "pop", "detector" to "tick", "t_ms" to t)
        mic?.deliverTickPop(t, t + 40, baseMs)
    }

    /** Mic sounds while the joystick drives or a calibration records ([PhoneMicSource.soundFilter]). */
    private fun filter(label: String, tStartMs: Long, gate: JSONObject?): String? {
        calib?.let { c -> c.extractorEvent(tStartMs.toDouble(), label, SoundExample.raw(gate)); return "calibrating" }
        if (!on) return null
        if (label !in PASS) return "joystick (a hum moves the cursor)"
        if (label == "pop" && !merge.accept(tStartMs.toDouble())) { merged++; return "joystick (the tick detector heard this pop)" }
        return null
    }

    private fun draw(jump: Boolean) {
        val d = density
        overlay.joyUpdate((mover.x * d).toFloat(), (mover.y * d).toFloat(), JoyIndicators.cursorKey(mover), jump)
        val face = JoyIndicators.faceState(mover)
        if (face != lastFace) { lastFace = face; overlay.setBadgeJoy(face) }
    }

    private fun save() {
        prefs.edit().putFloat(KEY_X, mover.x.toFloat()).putFloat(KEY_Y, mover.y.toFloat()).apply()
    }

    private fun screenDp(): Pair<Double, Double> = screenPx().let { (w, h) -> w / density.toDouble() to h / density.toDouble() }

    // ---------------------------------------------------------------------------------------------- commands

    fun recentre(by: String) {
        mover.recentre()
        overlay.joyBrackets(null)
        if (on) draw(jump = true) else overlay.recentre()
        save()
        EventLog.ev("joystick", "event" to "recentre", "by" to by)
    }

    /** A rotation or fold: the same coordinates, clamped into the new screen. */
    fun screenChanged() {
        val (w, h) = screenDp()
        mover.setScreen(w, h, emptyList())
        overlay.joyBrackets(null)
        overlay.clampCursor()
        if (on) { draw(jump = true); refreshElements() }
        EventLog.ev("joystick", "event" to "screen", "w_dp" to r1(w), "h_dp" to r1(h), "x_dp" to r1(mover.x), "y_dp" to r1(mover.y))
    }

    /** The element under the cursor when it is an outward button ("Like", "Follow", "Send"): a click asks first. */
    fun outwardUnderCursor(): String? {
        if (!on) return null
        val i = Magnet.hit(mover.elements, mover.x, mover.y) ?: return null
        return mover.elements[i].label.takeIf { Outward.isOutwardTarget(it) }
    }

    fun describe(): JSONObject = JSONObject().put("on", on).put("source", source).put("calibrated", profile != null)
        .put("mode", mover.mode).put("x_dp", r1(mover.x)).put("y_dp", r1(mover.y)).put("snapped", mover.snapped)
        .put("phase", mover.state.phase).put("mid_st", r1(mover.mid)).put("range_st", JSONArray(listOf(r1(mover.range.first), r1(mover.range.second))))
        .put("speed_mul", mover.speedMul).put("pitch_sens", mover.pitchSens).put("elements", mover.elements.size)
        .put("ticks", ticks).put("pops", pops).put("merged", merged).put("calibrating", calib != null)
        .put("whistle", mover.whistle?.toJson()).put("band", mover.state.band)
        .put("level_gate", mic?.levelGate?.toJson()).put("relabel_rule", mic?.clickPopRule != null)
        .put("needs_recalibration", profile?.needsRecalibration)

    fun close() {
        mic?.let { detach(it) }; mic = null
        reader.shutdownNow()
        cancelCalibration("service stopped")
    }

    // ---------------------------------------------------------------------------------------------- calibration

    private var calib: JoyCalibration? = null
    private var calibError: String? = null
    private val calibPush = object : Runnable {
        override fun run() {
            if (calib == null) return
            calibChanged(true)
            main.postDelayed(this, PUSH_MS)
        }
    }
    private var lastPushAt = 0L
    // The idle timeout (like gesture training's): a calibration left open with no command for [CALIB_IDLE_MS] is ended
    // here, not left to make Canti deaf (every mic sound is dropped as "calibrating" while one runs).
    private var lastCalibCmdAt = 0L
    private val calibIdle = Runnable {
        if (calib != null && SystemClock.elapsedRealtime() - lastCalibCmdAt >= CALIB_IDLE_MS)
            cancelCalibration("idle", "The calibration stopped: nothing happened for ${CALIB_IDLE_MS / 60_000} min.")
    }

    /** A saved calibration for [src] (the current source: the loaded profile, no prefs read; uiStatus asks often). */
    fun calibrated(src: String = source): Boolean = if (src == source) profile != null else load(src) != null

    /** A calibration run is open now (its sounds are dropped as "calibrating", so Canti is deaf until it ends). */
    val calibrating: Boolean get() = calib != null

    /** A calibration run started or ended (the service redraws the badge: the paused face while one runs). Main thread. */
    var onCalibChanged: (() -> Unit)? = null

    fun load(src: String): JoyProfile? = prefs.getString("calib_$src", null)?.let {
        try { JoyProfile.fromJson(JSONObject(it)) } catch (e: Exception) { EventLog.ev("error", "where" to "joystick profile", "error" to e.toString()); null }
    }

    /** One command from the UI or the debug socket -> the calib_status map (calib_get: the profile map, or null). */
    fun calibCommand(method: String, args: Map<String, Any?>): Map<String, Any?>? {
        val r = command(method, args)
        // the reply goes to the caller; the UI's status stream gets it too (a command from the debug socket)
        if (method != "calib_get") { applyTicks(); lastPushAt = SystemClock.elapsedRealtime(); uiSink?.invoke(r ?: idleStatus()) }
        if (method != "calib_get" && method != "calib_status") armCalibIdle()   // reads are not activity
        return r
    }

    private fun armCalibIdle() {
        main.removeCallbacks(calibIdle)
        if (calib != null) {
            lastCalibCmdAt = SystemClock.elapsedRealtime()
            main.postDelayed(calibIdle, CALIB_IDLE_MS)
        }
    }

    private fun command(method: String, args: Map<String, Any?>): Map<String, Any?>? {
        calibError = null
        try {
            when (method) {
                "calib_get" -> {
                    val src = args["source"] as? String ?: source
                    return load(src)?.toJson()?.let(JsonMaps::of)
                }
                "calib_start" -> {
                    val src = args["source"] as? String ?: throw IllegalArgumentException("calib_start needs {source}")
                    require(src in listOf(MicSettings.PHONE, MicSettings.USB, MicSettings.PICO)) { "source must be phone | usb | pico" }
                    require(src != MicSettings.PICO) { "the Pico's mic can't be calibrated yet (phone and USB mics only)" }
                    require(src == source) { "the sound source is $source, not $src: switch to it first" }
                    require(mic?.capturing == true) { "the mic is off (${mic?.state ?: "no mic source"}): resume Canti first" }
                    // calibration v2: an optional ordered subset of the steps (a list, or a JSON array from the debug socket)
                    val steps = when (val a = args["steps"]) {
                        null, JSONObject.NULL -> null
                        is List<*> -> a.map { it as? String ?: throw IllegalArgumentException("steps must be step names") }
                        is org.json.JSONArray -> (0 until a.length()).map { a.optString(it) }
                        else -> throw IllegalArgumentException("steps must be a list of ${JoyCalibration.STEPS.joinToString(" | ")}")
                    }
                    calib = JoyCalibration(spec, src, load(src), steps)
                    applyTicks(); applyGate()
                    main.removeCallbacks(calibPush); main.postDelayed(calibPush, PUSH_MS)
                    EventLog.ev("calib", "event" to "start", "source" to src, "steps" to calib?.steps?.joinToString(" "))
                    onCalibChanged?.invoke()
                }
                "calib_step", "calib_redo" -> {
                    val c = calib ?: throw IllegalStateException("no calibration running (calib_start first)")
                    val step = args["step"] as? String ?: throw IllegalArgumentException("$method needs {step: ${JoyCalibration.STEPS.joinToString(" | ")}}")
                    // calib_step of the step already waiting or recording is a no-op (it would throw away what it heard)
                    if (method == "calib_redo") c.startStep(step, null, force = true)
                    else if (c.step != step || (c.state != "waiting" && c.state != "recording")) c.startStep(step)
                    EventLog.ev("calib", "event" to method.removePrefix("calib_"), "step" to step)
                }
                "calib_retry" -> { (calib ?: throw IllegalStateException("no calibration running")).retry(); EventLog.ev("calib", "event" to "retry", "step" to calib?.step) }
                "calib_skip" -> {
                    val c = calib ?: throw IllegalStateException("no calibration running")
                    val s = c.step
                    c.skip()
                    applyTicks()
                    EventLog.ev("calib", "event" to "skip", "step" to s, "next" to c.step, "state" to c.state)
                }
                "calib_save" -> {
                    val c = calib ?: throw IllegalStateException("no calibration running")
                    val p = c.draft.copy(savedAtMs = System.currentTimeMillis())
                    prefs.edit().putString("calib_${p.source}", p.toJson().toString()).apply()
                    EventLog.ev("calib", "event" to "save", "source" to p.source, "skipped" to p.skipped.joinToString(" "),
                        "steps" to c.finished.joinToString(" "))
                    calibEnd()
                    if (p.source == source) { loadProfile(); mic?.extractorJson = VxNative.overridesJson(profile?.extractor) }
                    return idleStatus()
                }
                "calib_cancel" -> {
                    cancelCalibration("ui")
                    return idleStatus()
                }
                "calib_status" -> {}
                else -> throw IllegalArgumentException("unknown calibration command $method")
            }
        } catch (e: IllegalArgumentException) {
            calibError = e.message
            if (method == "calib_start") EventLog.ev("calib", "event" to "refused", "reason" to e.message, "source" to args["source"])
        } catch (e: IllegalStateException) { calibError = e.message }
        return calibStatus()
    }

    private fun calibEnd() {
        calib = null
        main.removeCallbacks(calibPush)
        main.removeCallbacks(calibIdle)
        applyTicks(); applyGate()
        onCalibChanged?.invoke()
    }

    /** End an open calibration, logging why it ended (the idle timeout, the app going to the background, the UI closing).
     *  [note]: an end the calibration screen did not ask for — pushed to it now as its error, so a screen still showing
     *  the run says it stopped. */
    fun cancelCalibration(by: String, note: String? = null) {
        if (calib == null) return
        EventLog.ev("calib", "event" to "cancel", "by" to by, "step" to calib?.step)
        calibEnd()
        if (note != null) { calibError = note; lastPushAt = SystemClock.elapsedRealtime(); uiSink?.invoke(idleStatus()) }
    }

    fun calibStatus(): Map<String, Any?> {
        val c = calib ?: return idleStatus()
        val m = LinkedHashMap(c.status(calibrated(c.source), null))
        (m["result"] as? JSONObject)?.let { m["result"] = JsonMaps.of(it) }
        if (!(mic?.capturing ?: false)) m["sub"] = "the mic is off (${mic?.state ?: "no mic source"})"
        calibError?.let { m["error"] = it }
        return m
    }

    private fun idleStatus(): Map<String, Any?> {
        val p = load(source)
        return linkedMapOf("active" to false, "source" to source, "state" to null,
            "calibrated" to calibrated(), "skipped" to (p?.skipped ?: emptyList<String>()), "error" to calibError,
            // calibration v2: a profile saved before it (or partly) lacks steps; the UI offers to calibrate them
            "needs_recalibration" to (p?.needsRecalibration ?: false), "missing_steps" to (p?.missingSteps ?: emptyList<String>()))
    }

    /** Push the status: at most every [PUSH_MS] from the ticks, always on a command or the timer. */
    private fun calibChanged(force: Boolean) {
        val now = SystemClock.elapsedRealtime()
        if (!force && now - lastPushAt < PUSH_MS) return
        lastPushAt = now
        uiSink?.invoke(calibStatus())
    }


    companion object {
        const val PREFS = "canti_joystick"
        const val KEY_X = "pos_x_dp"
        const val KEY_Y = "pos_y_dp"
        const val PUSH_MS = 100L
        /** A calibration with no command for this long is ended (mirrors gesture training's [GestureTrainer.IDLE_MS]). */
        const val CALIB_IDLE_MS = 5 * 60_000L
        /** The UI's `calib_status` pushes (UiBridge sets it while the Flutter UI is attached; main thread). */
        @Volatile var uiSink: ((Map<String, Any?>) -> Unit)? = null
        /** The sounds that stay gestures while the joystick drives: the pops (click, pop pop), a tongue click, hiss. */
        val PASS = setOf("pop", "click", "hiss")
    }
}

/** org.json -> the plain maps and lists the Flutter channel codec takes. */
object JsonMaps {
    fun of(o: JSONObject): Map<String, Any?> = o.keys().asSequence().associateWith { k -> value(o.get(k)) }
    fun value(v: Any?): Any? = when (v) {
        null, JSONObject.NULL -> null
        is JSONObject -> of(v)
        is JSONArray -> (0 until v.length()).map { value(v.get(it)) }
        else -> v
    }
}
