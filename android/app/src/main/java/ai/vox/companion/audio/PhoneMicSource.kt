package ai.vox.companion.audio

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioDeviceCallback
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Base64
import ai.vox.companion.EventLog
import ai.vox.companion.FeatureSource
import ai.vox.companion.Sink
import ai.vox.companion.joystick.CalibV2
import ai.vox.companion.joystick.ClickPopRule
import ai.vox.companion.joystick.LevelGate
import org.json.JSONArray
import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Feature source "phone-mic": the phone's own microphone (or a USB mic plugged into it) through the C++ extractor
 * ([VxNative], the Pico's code), delivering the same protocol messages as the BLE link ([PhoneMessages]).
 *
 * What runs is decided by [SourcePolicy] from the `sound_source` setting, the app state ([active]: not paused, armed
 * or `mic_while_disarmed`), the RECORD_AUDIO permission and the attached USB inputs; [refresh] applies it and is
 * called by the service whenever one of those changes, and by the device callback on plug / unplug.
 *
 * - The foreground service [MicListenService] must start while Canti is visible (Android 14's while-in-use rule for
 *   the mic). If starting it is refused, the state says "open Canti to start the mic" and [onAppVisible] (the status
 *   and settings screens' onResume) retries.
 * - `phone`: the built-in mic (preferred explicitly, so a plugged USB headset does not take over). `usb`: the first
 *   USB input; none plugged = wait for one, never fall back to the phone mic.
 * - Messages are built on the main thread with the service's current mode and delivered to the service's [Sink] as
 *   source "phone-mic". Timing is on the elapsedRealtime clock, like the sequencer's arrival times.
 * - Privacy: samples go from AudioRecord straight into the extractor; nothing is stored, logged or sent. Only the
 *   extractor's output (the sound lines and fp1 numbers the Pico would send) leaves the audio thread.
 */
class PhoneMicSource(
    private val ctx: Context,
    private val settings: MicSettings,
    private val active: () -> Boolean,
    private val mode: () -> String,
) : FeatureSource {
    override val name = NAME
    private val main = Handler(Looper.getMainLooper())
    private val audio = ctx.getSystemService(AudioManager::class.java)
    private var sink: Sink? = null
    private var nextId = SystemClock.elapsedRealtime()   // never repeats a BLE id the service saw last
    private var plan: SourcePolicy.Plan? = null
    var state = "off"; private set
    /** The input the capture uses ("USB headset: CMEDIA Q9"), when it runs. */
    var device: String? = null; private set
    private var serviceAsked = false        // startForegroundService called, waiting for serviceStarted
    private var serviceRefused: String? = null
    private var captureError: String? = null
    private var retry: Runnable? = null
    private var sounds = 0L
    private var mediaGated = 0L
    private var hissGated = 0L                     // of mediaGated: the media-hiss rule (PhoneGate.hissReason)
    private var levelGated = 0L                    // pop / click / hiss / unknown under the level gate (calibration v2)
    private var relabelled = 0L                    // pop <-> click by the person's own rule
    private val latencies = ArrayDeque<Double>()   // ms, end of sound -> delivered to the service (main thread)
    private var lastCaptureInfo: JSONObject? = null
    /** Touch safety (`mic_touch_guard`): sounds overlapping a finger on the screen are dropped. */
    private val touchGuard = TouchGuard()
    private val touchWatch = TouchWatch(ctx, touchGuard)

    private val capture = MicCapture(audio, object : MicCapture.Listener {
        override fun onMessages(msgs: Array<String>, baseMs: Long, nowNs: Long) {
            // audio thread -> main thread; baseMs is on the nanoTime clock: move it to elapsedRealtime there.
            main.post { deliver(msgs, baseMs, nowNs, NAME) }
        }
        override fun onState(state: String, info: JSONObject) {
            main.post { captureState(state, info) }
        }
        override fun onTicks(rows: DoubleArray, n: Int, baseMs: Long) {
            tickSink?.invoke(rows, n, baseMs)
            trainTickSink?.invoke(rows, n, baseMs)   // [train]
        }
    })

    // --- the voice joystick (VoiceJoystick) ------------------------------------------------------------------------

    /** Joystick ticks (audio thread; [rows] is reused: copy it). Set by the service's VoiceJoystick. */
    @Volatile var tickSink: ((rows: DoubleArray, n: Int, baseMs: Long) -> Unit)? = null

    /** Turn the per-20 ms ticks on or off, with the voicing threshold ([clarityOn]) and the pitch ceiling ([f0MaxHz]:
     *  the voice's 1100 Hz, or the whistle's 2600 Hz during the whistle step and once there is a whistle range). */
    fun setTicks(on: Boolean, clarityOn: Double, f0MaxHz: Double = 1100.0) {
        capture.tickClarityOn = clarityOn
        capture.tickF0MaxHz = f0MaxHz
        joyTicks = on
        capture.ticks = on || trainTicks   // [train] gesture training may keep them on
    }

    // [train] Gesture training's live pitch trace (GestureTrainer.onTick): the same ticks, wanted independently of the
    // joystick (which turns its own off whenever it is not in cursor mode). Audio thread; [rows] is reused.
    @Volatile var trainTickSink: ((rows: DoubleArray, n: Int, baseMs: Long) -> Unit)? = null
    @Volatile private var joyTicks = false
    @Volatile private var trainTicks = false
    fun setTrainTicks(on: Boolean) {
        trainTicks = on
        capture.ticks = joyTicks || on
    }

    /** The capture is running (the mic hears). */
    val capturing: Boolean get() = capture.isRunning

    /** A calibration profile's extractor overrides (VxNative.overridesJson); a change restarts the capture. Null (the
     *  default, and all profiles today) = the extractor's defaults, byte-identical to before. */
    var extractorJson: String? = null
        set(v) { if (v != field) { field = v; refresh("extractor overrides") } }

    /**
     * Judges each sound before it goes to the service: (label, stream t_start ms) -> a reason to drop it, or null.
     * The joystick drops hums (they move the cursor, they are not gestures), a pop both detectors heard (merged),
     * and everything while a calibration records. Main thread.
     */
    var soundFilter: ((label: String, tStartStreamMs: Long, gate: JSONObject?) -> String?)? = null

    /**
     * Calibration v2 (VoiceJoystick sets both from this source's profile; main thread): the level gate a pop / click /
     * hiss must pass (snr_db AND level_db from the extractor's gate numbers; the spec's default when uncalibrated,
     * null = none, e.g. while a calibration records) and the person's click / pop rule (null = never relabel).
     * Settings `level_gate` (on / off) and `level_gate_offset_db` (+ = stricter). The tick detector's pops are not
     * gated (they have their own calibrated thresholds).
     */
    var levelGate: LevelGate? = null
    var clickPopRule: ClickPopRule? = null

    /** A pop the joystick's tick detector heard (stream ms; [baseNanoMs] = the ticks' base): delivered like the
     *  extractor's own, through the touch guard, the media gates and the dry run. Main thread. */
    fun deliverTickPop(tStartMs: Long, tEndMs: Long, baseNanoMs: Long) {
        val n = JSONObject().put("kind", "sound").put("label", "pop").put("text", "pop (tick detector)")
            .put("t_start_ms", tStartMs).put("t_end_ms", tEndMs).put("tick", true)
        deliver(arrayOf(n.toString()), baseNanoMs, System.nanoTime(), NAME)
    }

    private val devices = object : AudioDeviceCallback() {
        override fun onAudioDevicesAdded(added: Array<out AudioDeviceInfo>) = devicesChanged("added", added)
        override fun onAudioDevicesRemoved(removed: Array<out AudioDeviceInfo>) = devicesChanged("removed", removed)
    }

    // --- lifecycle -----------------------------------------------------------------------------------------------

    override fun start(sink: Sink) {
        this.sink = sink
        current = this
        audio.registerAudioDeviceCallback(devices, main)
        EventLog.ev("source", "name" to name, "state" to "started", "native" to (VxNative.loadError ?: VxNative.version()),
            "unprocessed" to capture.unprocessedSupported())
        refresh("start")
    }

    override fun stop() {
        capture.stop()
        speechHold = null
        touchWatch.stop()
        retry?.let(main::removeCallbacks); retry = null
        try { audio.unregisterAudioDeviceCallback(devices) } catch (_: Exception) {}
        if (MicListenService.running || serviceAsked) MicListenService.stop(ctx)
        serviceAsked = false
        setState("off", "source stopped")
        if (current === this) current = null
        sink = null
    }

    // The phrase window (ListenWindow): while a speech recognizer records, Canti's own capture pauses. Only the capture:
    // MicListenService stays in the foreground (it could not be restarted from the background).
    private var speechHold: String? = null

    /** Pause the capture for a speech recognizer; true if it was running (the recorder is released after its read). */
    fun yieldMic(why: String): Boolean {
        val was = capture.isRunning
        speechHold = why
        refresh("yield: $why")
        return was
    }

    /** End [yieldMic]; the capture restarts if the policy still wants it. */
    fun resumeMic(why: String) {
        if (speechHold == null) return
        speechHold = null
        refresh("resume: $why")
    }

    /** A screen of Canti is visible: a refused foreground-service start may be retried now. */
    fun appVisible() {
        if (serviceRefused != null) { serviceRefused = null; refresh("app visible") }
    }

    /** From [MicListenService.onStartCommand]: null = in the foreground, else why it was refused. */
    fun serviceStarted(error: String?) {
        main.post {
            serviceAsked = false
            serviceRefused = error
            refresh(if (error == null) "service started" else "service refused")
        }
    }

    private fun permission() = ctx.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
    private fun inputs() = audio.getDevices(AudioManager.GET_DEVICES_INPUTS).toList()
    private fun usbInput() = inputs().firstOrNull { it.type in MicCapture.USB_TYPES }
    private fun builtinInput() = inputs().firstOrNull { it.type == AudioDeviceInfo.TYPE_BUILTIN_MIC }

    /** Apply [SourcePolicy] now (main thread). */
    fun refresh(why: String) {
        if (sink == null) return
        val p = SourcePolicy.plan(SourcePolicy.Inputs(settings.source, active(), permission(), usbInput() != null, VxNative.available))
        plan = p
        // 1. the foreground service
        if (p.service) {
            if (!MicListenService.running && !serviceAsked && serviceRefused == null) {
                try { MicListenService.start(ctx); serviceAsked = true }
                catch (e: Exception) { serviceRefused = e.toString() }
            }
        } else {
            if (MicListenService.running || serviceAsked) { MicListenService.stop(ctx); serviceAsked = false }
            serviceRefused = null
        }
        // 2. the capture
        val want = if (p.capture && speechHold == null && MicListenService.running && captureError == null) config(p) else null
        val have = capture.config
        if (want == null) { if (capture.isRunning) capture.stop() }
        else if (!capture.isRunning || have == null || key(have) != key(want)) capture.start(want)
        // the touch watch runs while the mic listens (only then can a tap turn into a sound)
        if (want != null && settings.touchGuard) touchWatch.start() else touchWatch.stop()
        // 3. what the user sees
        val st = when {
            p.service && serviceRefused != null -> "open Canti to start the mic"
            p.capture && captureError != null -> "mic error: $captureError"
            p.capture && speechHold != null -> "paused for speech"
            p.capture && !MicListenService.running -> "starting"
            else -> p.state
        }
        setState(st, why)
        device = if (p.capture) want?.device?.let(MicCapture::describe) else null
        CantiNotification.refresh()
    }

    private fun config(p: SourcePolicy.Plan) = MicCapture.Config(settings.rate, settings.readMs, settings.preset,
        if (p.route == SourcePolicy.Route.USB) usbInput() else builtinInput(), settings.effects, extractorJson)

    private fun key(c: MicCapture.Config) = listOf(c.rate, c.readMs, c.preset, c.device?.id, c.effects, c.extractorJson)

    private fun setState(s: String, why: String) {
        if (s == state) return
        state = s
        EventLog.ev("mic", "state" to s, "why" to why, "source" to settings.source)
    }

    private fun captureState(s: String, info: JSONObject) {
        lastCaptureInfo = info
        EventLog.ev("mic_capture", "state" to s, "info" to info)
        if (s == "error") {
            captureError = info.optString("error").take(160)
            // A mic held by another app, or a device that vanished mid-read: try again in 5 s.
            retry?.let(main::removeCallbacks)
            retry = Runnable { retry = null; captureError = null; refresh("retry after error") }.also { main.postDelayed(it, 5000) }
            refresh("capture error")
        }
    }

    private fun devicesChanged(what: String, list: Array<out AudioDeviceInfo>) {
        val relevant = list.filter { it.isSource && (it.type in MicCapture.USB_TYPES || it.type == AudioDeviceInfo.TYPE_BUILTIN_MIC) }
        if (relevant.isEmpty()) return
        EventLog.ev("mic_device", "change" to what, "devices" to JSONArray(relevant.map(MicCapture::describe)))
        refresh("device $what")
    }

    // --- messages ------------------------------------------------------------------------------------------------

    /** Main thread: native messages -> protocol messages -> the service. */
    private fun deliver(msgs: Array<String>, baseNanoMs: Long, nowNs: Long, source: String) {
        if (sink == null) return
        // stream ms -> elapsedRealtime ms (the sequencer's clock)
        val clockOffset = SystemClock.elapsedRealtimeNanos() / 1_000_000 - System.nanoTime() / 1_000_000
        val base = baseNanoMs + clockOffset
        for (raw in msgs) {
            val n = try { JSONObject(raw) } catch (e: Exception) { EventLog.ev("ignored", "reason" to "bad native message: $e", "source" to source); continue }
            val out = PhoneMessages.toProtocol(n, nextId++, mode(), base)
            if (out == null) { EventLog.ev("ignored", "reason" to "native message kind '${n.optString("kind")}' not handled", "source" to source); continue }
            if (n.optString("kind") != "sound") { sink?.deliver(out, source); continue }
            // A touch-down may still arrive for this sound (the finger's lift, the event queue): judge it once
            // [TouchGuard.preMs] after its end has passed. Later sounds end later, so the order is kept.
            val wait = if (touchWatch.running) touchGuard.settleMs(base + n.getLong("t_end_ms"), SystemClock.elapsedRealtime()) else 0
            if (wait > 0) main.postDelayed({ judge(n, out, base, baseNanoMs, nowNs, source) }, wait)
            else judge(n, out, base, baseNanoMs, nowNs, source)
        }
    }

    /** One sound: the touch guard, the mic_sound log line (with the extractor's gate numbers), then the service. */
    private fun judge(n: JSONObject, out: JSONObject, base: Long, baseNanoMs: Long, nowNs: Long, source: String) {
        val s = sink ?: return
        val t0 = base + n.getLong("t_start_ms"); val t1 = base + n.getLong("t_end_ms")
        val touch = if (touchWatch.running) touchGuard.overlapping(t0, t1) else null
        val endNs = (baseNanoMs + n.getLong("t_end_ms")) * 1_000_000
        val detect = (nowNs - endNs) / 1e6              // end of sound -> the extractor emitted it (hangover + read)
        val lat = (System.nanoTime() - endNs) / 1e6      // ... -> handed to the service on the main thread
        if (source == NAME) {
            sounds++
            if (touch == null) { latencies.addLast(lat); while (latencies.size > 64) latencies.removeFirst() }
        }
        val tick = n.optBoolean("tick")
        val g = n.optJSONObject("gate")
        // the level gate, then the click / pop relabel (calibration v2): before the joystick's filter, which then sees
        // the relabelled sound (a pop both detectors heard is merged once), and before the service, so a gated sound
        // (pop / click / hiss / unknown) never reaches its personalization (Personal.rewrite's trained-gesture relabel)
        val v = CalibV2.phoneVerdict(n.optString("label"), g, levelGate, clickPopRule, settings.levelGate,
            settings.levelGateOffsetDb.toDouble(), tick, touch != null)
        val level = v.drop
        if (level != null) {
            levelGated++
            EventLog.ev("ignored", *level.fields(), "offset_db" to settings.levelGateOffsetDb, "source" to source,
                "sound" to n.optLong("sound"), "t_start_ms" to n.optLong("t_start_ms"))
        }
        val rl = v.relabel
        if (rl != null) {
            relabelled++
            out.put("sequence", JSONArray().put(rl.to))
            EventLog.ev("relabel", "by" to "click_pop_rule", "from" to rl.from, "to" to rl.to, "votes" to JSONObject(rl.votes as Map<*, *>), "source" to source,
                "sound" to n.optLong("sound"), "t_start_ms" to n.optLong("t_start_ms"))
        }
        val label = v.label
        val joy = if (tick || level != null) null else soundFilter?.invoke(label, n.optLong("t_start_ms"), g)
        val dry = settings.dryRun
        val playing = audio.isMusicActive
        val onSpeaker = playing && mediaOnSpeaker()
        fun num(k: String) = g?.optDouble(k)?.takeUnless { it.isNaN() }
        val hiss = PhoneGate.hissReason(label, num("centroid_hz"), onSpeaker, settings.hissMediaMaxCentroidHz, settings.source)
        val gated = (if (PhoneGate.active(settings.mediaGate, playing, onSpeaker)) PhoneGate.reason(label, num("snr_db"), num("clarity_med")) else null)
            ?: hiss
        if (gated != null) { mediaGated++; out.put("sequence", JSONArray().put("unknown")) }   // not deliberate: still breaks its group
        // [train] the explicit gated flag: personalization (VoxService.personalize) never relabels a gated sound
        if (gated != null) out.put("gated", JSONArray().put(if (gated == hiss) "media_hiss" else "media"))
        if (gated != null && gated == hiss) hissGated++
        EventLog.ev("mic_sound", "label" to n.optString("label"), "sound" to n.optLong("sound"), "source" to source,
            "t_start_ms" to n.optLong("t_start_ms"), "t_end_ms" to n.optLong("t_end_ms"),
            "detect_ms" to Math.round(detect * 10) / 10.0, "latency_ms" to Math.round(lat * 10) / 10.0,
            "text" to n.optString("text"), "gate" to n.optJSONObject("gate"),
            "dropped" to (touch?.let { "touch" } ?: level?.reason ?: joy ?: if (dry) "dry_run" else null), "touch_ms" to touch?.let { it.atMs - t0 },
            "relabel" to rl?.let { "${it.from}->${it.to}" },
            "tick" to if (n.optBoolean("tick")) true else null,
            "media" to playing, "media_speaker" to onSpeaker, "gated" to gated)   // media playing at judge time (speaker: its route)
        if (touch == null && level == null && joy == null && !dry) s.deliver(out, source)
    }

    /** Media plays on the phone's own speaker (so the mic hears it). Before Android 13 the route is not known: assume so. */
    private fun mediaOnSpeaker(): Boolean {
        if (android.os.Build.VERSION.SDK_INT < 33) return true
        return try {
            val attrs = android.media.AudioAttributes.Builder().setUsage(android.media.AudioAttributes.USAGE_MEDIA).build()
            audio.getAudioDevicesForAttributes(attrs).any { it.type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER }
        } catch (_: Exception) { true }
    }

    // --- status and debug ops ------------------------------------------------------------------------------------

    fun status(): JSONObject {
        val lat = latencies.sorted()
        fun pct(p: Double) = if (lat.isEmpty()) JSONObject.NULL else Math.round(lat[((lat.size - 1) * p).toInt()] * 10) / 10.0
        return JSONObject().put("source", settings.source).put("state", state)
            .put("plan", plan?.let { JSONObject().put("service", it.service).put("capture", it.capture).put("route", it.route?.name?.lowercase()) })
            .put("service_running", MicListenService.running).put("service_refused", serviceRefused)
            .put("capturing", capture.isRunning).put("routed", capture.routed).put("capture", lastCaptureInfo)
            .put("permission", permission()).put("native", VxNative.loadError ?: VxNative.version())
            .put("unprocessed_supported", capture.unprocessedSupported())
            .put("inputs", JSONArray(inputs().map(MicCapture::describe)))
            .put("sounds", sounds).put("latency_ms", JSONObject().put("n", lat.size).put("p50", pct(0.5)).put("max", pct(1.0)))
            .put("stats", capture.status)
            .put("touch_guard", JSONObject().put("on", touchWatch.running).put("error", touchWatch.error)
                .put("user_touches", touchGuard.userTouches).put("injected_touches", touchGuard.injectedTouches)
                .put("sounds_dropped", touchGuard.dropped))
            .put("media_gate", JSONObject().put("mode", settings.mediaGate).put("media_playing", audio.isMusicActive)
                .put("gated", mediaGated).put("hiss_gated", hissGated).put("hiss_media_max_centroid_hz", settings.hissMediaMaxCentroidHz))
            .put("level_gate", JSONObject().put("on", settings.levelGate).put("offset_db", settings.levelGateOffsetDb)
                .put("gate", levelGate?.toJson()).put("dropped", levelGated).put("relabel_rule", clickPopRule != null)
                .put("relabelled", relabelled))
            .put("bands", if (capture.isRunning) capture.status?.optJSONObject("level")?.let { l ->
                JSONObject().put("band_hz", l.opt("band_hz")).put("dbfs", l.opt("bands_dbfs")).put("ms", l.opt("ms")) } else null)
            .let { settings.describeInto(it) }
    }

    /** The mic's input level over the last second (dBFS) and the extractor's noise floor. */
    fun level(): JSONObject {
        val st = capture.status
        return JSONObject().put("state", state).put("routed", capture.routed)
            .put("level", st?.optJSONObject("level")).put("floor_db", st?.opt("floor_db")).put("gate_open", st?.opt("gate_open"))
            .put("silent_input", st?.opt("silent_input"))
    }

    /** Debug ops `mic_status`, `mic_level`, `mic_feed`; see PROTOCOL.md "Phone microphone". */
    fun control(op: String, m: JSONObject): JSONObject = when (op) {
        "mic_status" -> status()
        "mic_level" -> level()
        "mic_feed" -> feed(m)
        else -> throw IllegalArgumentException("unknown mic op '$op'")
    }

    /**
     * Runs PCM16 LE mono (`pcm_b64`) at `rate` through a fresh native extractor, `chunk_ms` per push (default 20),
     * `repeat` times, and returns the events (the full event JSON with raw when `raw`) and the timing stats. With
     * `deliver`, each sound also goes to the service as source "phone-mic-feed", exactly as a live one would.
     * The live capture keeps running (the native lock serialises the two).
     */
    private fun feed(m: JSONObject): JSONObject {
        val rate = m.optInt("rate", 16000)
        val bytes = Base64.decode(m.getString("pcm_b64"), Base64.DEFAULT)
        val raw = m.optBoolean("raw", false)
        val repeat = m.optInt("repeat", 1).coerceIn(1, 1000)
        val chunk = (rate * m.optInt("chunk_ms", 20) / 1000).coerceAtLeast(1)
        val n = bytes.size / 2
        val buf = ByteBuffer.allocateDirect(chunk * 2).order(ByteOrder.nativeOrder())
        val src = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer()
        val h = VxNative.open(rate, raw)
        val events = JSONArray()
        val out = ArrayList<String>()
        val t0 = System.nanoTime()
        try {
            for (r in 0 until repeat) {
                if (r > 0) VxNative.reset(h)
                var i = 0
                while (i < n) {
                    val k = minOf(chunk, n - i)
                    buf.clear()
                    for (j in 0 until k) buf.putShort(src.get(i + j))
                    VxNative.pushDirect(h, buf, k, false)?.let { if (r == 0) out += it }
                    i += k
                }
                VxNative.flush(h)?.let { if (r == 0) out += it }
            }
            val wall = (System.nanoTime() - t0) / 1e6
            for (s in out) {
                val o = JSONObject(s)
                events.put(if (raw) o.getJSONObject("event") else o.apply { remove("features") })
            }
            if (m.optBoolean("deliver", false) && out.isNotEmpty()) {
                val base = System.nanoTime() / 1_000_000 - n * 1000L / rate
                val arr = out.toTypedArray()
                main.post { deliver(arr, base, System.nanoTime(), "$NAME-feed") }
            }
            return JSONObject().put("events", events).put("stats", JSONObject(VxNative.stats(h)))
                .put("wall_ms", Math.round(wall * 10) / 10.0).put("audio_ms", n * 1000L * repeat / rate)
                .put("native", VxNative.version())
        } finally { VxNative.destroy(h) }
    }

    companion object {
        const val NAME = "phone-mic"
        /** The running source (one per service), for the foreground service and the activities. */
        @Volatile var current: PhoneMicSource? = null; internal set
        /** A Canti screen is visible (onResume): retry a foreground-service start that was refused. */
        fun onAppVisible() { current?.let { s -> Handler(Looper.getMainLooper()).post { s.appVisible() } } }
    }
}
