package ai.vox.companion.audio

import android.annotation.SuppressLint
import android.media.AudioDeviceInfo
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.AudioTimestamp
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.media.audiofx.AutomaticGainControl
import android.media.audiofx.NoiseSuppressor
import android.os.Process
import android.os.SystemClock
import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.atomic.AtomicBoolean

/**
 * The audio thread: AudioRecord (mono PCM16 at 16 or 48 kHz) -> the native extractor, one read every [Config.readMs].
 *
 * Per read: one blocking AudioRecord.read into a direct ByteBuffer and one JNI call that hands the same memory to the
 * extractor. Nothing is allocated unless a sound finished (then the native side returns its messages). Once a second
 * the thread snapshots the extractor stats and its own CPU time ([status]); the audio is never stored.
 *
 * Clock: `frame0Ns`, the System.nanoTime of the stream's first frame, from AudioRecord.getTimestamp (MONOTONIC) when
 * the platform has it (re-read every 2 s), else from the first read's return time. Messages get `baseMs` =
 * frame0Ns / 1e6, and each sound's latency (now - its end) is measured against it.
 *
 * Threading: [start] and [stop] are called on the main thread; the capture thread owns the AudioRecord and the native
 * handle. [Listener] callbacks run on the capture thread.
 */
class MicCapture(private val audio: AudioManager, private val listener: Listener) {
    /** [effects]: the platform pre-processing on the session, `off` / `platform` / `aec` / `aec_ns` ([MicSettings]). */
    data class Config(val rate: Int, val readMs: Int, val preset: String, val device: AudioDeviceInfo?, val effects: String = "off",
                      /** Extractor overrides (VxNative.overridesJson of the calibration profile), null = the defaults. */
                      val extractorJson: String? = null)

    interface Listener {
        /** Native messages (JSON strings) that just finished; [baseMs] maps stream ms to nanoTime ms. */
        fun onMessages(msgs: Array<String>, baseMs: Long, nowNs: Long)
        /** The capture started (routed device, effects) or failed / ended ([error] non-null on failure). */
        fun onState(state: String, info: JSONObject)
        /** Joystick ticks ([ticks] on): [n] rows of VxNative.TICK_COLS in [rows] (reused: copy what you keep). */
        fun onTicks(rows: DoubleArray, n: Int, baseMs: Long) {}
    }

    // One flag per capture session, so a slow-to-finish old thread can never see a newer session's "run".
    @Volatile private var session: AtomicBoolean? = null
    private var thread: Thread? = null
    @Volatile var config: Config? = null; private set
    /** The last once-a-second snapshot: extractor stats (level, hop times, floor) + thread CPU; null before the first. */
    @Volatile var status: JSONObject? = null; private set
    @Volatile var routed: String? = null; private set
    @Volatile var sessionId: Int = 0; private set

    val isRunning get() = session?.get() == true

    /** Joystick ticks wanted (cursor mode on this source); the capture thread applies it before its next read. */
    @Volatile var ticks = false
    /** The ticks' clarity_on (the calibration profile's voicing threshold). */
    @Volatile var tickClarityOn = 0.8
    /** The ticks' pitch ceiling (1100 Hz; 2600 with a calibrated whistle range, or during the whistle step). */
    @Volatile var tickF0MaxHz = 1100.0

    fun start(cfg: Config) {
        stop()
        thread?.let { if (it.isAlive) it.join(500) }   // the mic cannot be opened twice; this waits one read at most
        config = cfg
        status = null
        val alive = AtomicBoolean(true)
        session = alive
        thread = Thread({ run(cfg, alive) }, "vox-mic").apply { start() }
    }

    /** Asynchronous: the thread ends after its current read (at most readMs) and releases the mic. */
    fun stop() { session?.set(false); config = null }

    private fun source(preset: String): Int = when (preset) {
        "unprocessed" -> MediaRecorder.AudioSource.UNPROCESSED
        "voice_recognition" -> MediaRecorder.AudioSource.VOICE_RECOGNITION
        "voice_communication" -> MediaRecorder.AudioSource.VOICE_COMMUNICATION
        "mic" -> MediaRecorder.AudioSource.MIC
        else -> if (unprocessedSupported()) MediaRecorder.AudioSource.UNPROCESSED else MediaRecorder.AudioSource.VOICE_RECOGNITION
    }

    fun unprocessedSupported(): Boolean = audio.getProperty(AudioManager.PROPERTY_SUPPORT_AUDIO_SOURCE_UNPROCESSED) == "true"

    @SuppressLint("MissingPermission")   // PhoneMicSource only starts a capture with RECORD_AUDIO granted
    private fun run(cfg: Config, alive: AtomicBoolean) {
        Process.setThreadPriority(Process.THREAD_PRIORITY_AUDIO)
        val frames = cfg.rate * cfg.readMs / 1000
        val bytes = frames * 2
        val src = source(cfg.preset)
        var rec: AudioRecord? = null
        var handle = 0L
        val held = ArrayList<android.media.audiofx.AudioEffect>()   // effects we turned on: kept until the capture ends
        val info = JSONObject().put("rate", cfg.rate).put("read_ms", cfg.readMs).put("preset", cfg.preset)
            .put("source", SOURCE_NAMES[src] ?: src.toString())
        try {
            info.put("env_before", env())   // before the AudioRecord exists: what a VOICE_COMMUNICATION capture changes shows in env_after
            handle = VxNative.open(cfg.rate, configJson = cfg.extractorJson)
            val fmt = AudioFormat.Builder().setEncoding(AudioFormat.ENCODING_PCM_16BIT).setSampleRate(cfg.rate)
                .setChannelMask(AudioFormat.CHANNEL_IN_MONO).build()
            val min = AudioRecord.getMinBufferSize(cfg.rate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
            val r = AudioRecord.Builder().setAudioSource(src).setAudioFormat(fmt)
                .setBufferSizeInBytes(maxOf(min * 2, bytes * 4)).build()
            rec = r
            if (r.state != AudioRecord.STATE_INITIALIZED) throw IllegalStateException("AudioRecord did not initialise")
            cfg.device?.let { r.setPreferredDevice(it) }
            sessionId = r.audioSessionId
            info.put("effects", effects(r.audioSessionId, cfg.effects, held)).put("buffer_bytes", r.bufferSizeInFrames * 2).put("min_buffer_bytes", min)
            r.startRecording()
            if (r.recordingState != AudioRecord.RECORDSTATE_RECORDING) throw IllegalStateException("AudioRecord did not start (mic in use?)")
            val buf = ByteBuffer.allocateDirect(bytes).order(ByteOrder.nativeOrder())
            val ts = AudioTimestamp()
            var frame0Ns = 0L
            var tsAt = 0L
            var tsSource = "first read"
            var pushed = 0L
            var nextSnap = SystemClock.elapsedRealtime() + 1000
            val cpu0 = SystemClock.currentThreadTimeMillis(); val wall0 = SystemClock.elapsedRealtime()
            var zeroSecs = 0
            var reported = false
            var ticksOn = false
            var clarityApplied = Double.NaN
            var f0MaxApplied = Double.NaN
            val tickRows = DoubleArray(64 * VxNative.TICK_COLS)
            // enableTicks starts the tick clock at 0; the sounds' t_start_ms count from the stream's first sample. The
            // stream ms at the enable puts the ticks on the sounds' clock (the pop merge, the calibration's pop matching).
            var tickT0Ms = 0.0
            while (alive.get()) {
                val n = r.read(buf, bytes, AudioRecord.READ_BLOCKING)
                if (n <= 0) {
                    if (n == 0) continue
                    throw IllegalStateException("AudioRecord.read error $n")
                }
                val k = n / 2
                val now = System.nanoTime()
                if (pushed == 0L) frame0Ns = now - k * 1_000_000_000L / cfg.rate
                // Frame clock from the audio HAL, when it has one: exact capture times, re-read every 2 s.
                if (now - tsAt > 2_000_000_000L && r.getTimestamp(ts, AudioTimestamp.TIMEBASE_MONOTONIC) == AudioRecord.SUCCESS) {
                    frame0Ns = ts.nanoTime - ts.framePosition * 1_000_000_000L / cfg.rate
                    tsAt = now; tsSource = "AudioTimestamp"
                }
                val wantTicks = ticks
                if (wantTicks != ticksOn) { ticksOn = VxNative.enableTicks(handle, wantTicks) && wantTicks; clarityApplied = Double.NaN; f0MaxApplied = Double.NaN; tickT0Ms = pushed * 1000.0 / cfg.rate }
                if (ticksOn) tickClarityOn.let { if (it != clarityApplied) { VxNative.setTickClarityOn(handle, it); clarityApplied = it } }
                if (ticksOn) tickF0MaxHz.let { if (it != f0MaxApplied) { VxNative.setTickF0MaxHz(handle, it); f0MaxApplied = it } }
                val msgs = VxNative.pushDirect(handle, buf, k, false)
                pushed += k
                if (!reported) {
                    reported = true
                    routed = r.routedDevice?.let(::describe)
                    info.put("routed", routed ?: JSONObject.NULL).put("clock", tsSource).put("env_after", env())
                    listener.onState("listening", info)
                }
                if (msgs != null) listener.onMessages(msgs, frame0Ns / 1_000_000L, now)
                if (ticksOn) {
                    var m = VxNative.takeTicks(handle, tickRows)
                    while (m > 0) {
                        if (tickT0Ms != 0.0) for (i in 0 until m) tickRows[i * VxNative.TICK_COLS + VxNative.TICK_T_MS] += tickT0Ms
                        listener.onTicks(tickRows, m, frame0Ns / 1_000_000L)
                        m = if (m == 64) VxNative.takeTicks(handle, tickRows) else 0
                    }
                }
                val t = SystemClock.elapsedRealtime()
                if (t >= nextSnap) {
                    nextSnap = t + 1000
                    val st = JSONObject(VxNative.stats(handle))
                    // Digital silence (every sample 0) for 2 s: the mic is blocked (privacy toggle, another app holding
                    // it, an emulator without host audio). Reported, not fatal.
                    zeroSecs = if (st.getJSONObject("level").getDouble("peak_dbfs") <= -199.0) zeroSecs + 1 else 0
                    val wall = t - wall0
                    val cpu = SystemClock.currentThreadTimeMillis() - cpu0
                    st.put("thread_cpu_ms", cpu).put("wall_ms", wall)
                        .put("thread_cpu_pct", if (wall > 0) Math.round(cpu * 1000.0 / wall) / 10.0 else 0.0)
                        .put("silent_input", zeroSecs >= 2).put("clock", tsSource).put("routed", routed ?: JSONObject.NULL)
                        .put("seconds", pushed / cfg.rate)
                        .put("env", env())
                    status = st
                }
            }
            listener.onState("stopped", info)
        } catch (e: Throwable) {
            listener.onState("error", info.put("error", e.toString()))
        } finally {
            held.forEach { try { it.release() } catch (_: Exception) {} }
            try { rec?.stop() } catch (_: Exception) {}
            rec?.release()
            if (handle != 0L) VxNative.destroy(handle)
            alive.set(false)
            if (session === alive) routed = null
        }
    }

    /**
     * The platform pre-processing on the session. `off` (default): AGC, NS and AEC turned off (the extractor has its
     * own gate, and NS / AGC eat a steady hum). `platform`: left as the source attached them (VOICE_COMMUNICATION
     * usually brings AEC + NS). `aec`: echo canceller on, NS and AGC off. `aec_ns`: echo canceller and noise
     * suppressor on, AGC off. Effects turned on are kept in [held] until the capture ends. Reports what each was.
     */
    private fun effects(session: Int, mode: String, held: MutableList<android.media.audiofx.AudioEffect>): JSONObject {
        val o = JSONObject().put("mode", mode)
        fun one(name: String, available: Boolean, want: Boolean?, create: () -> android.media.audiofx.AudioEffect?) {
            if (!available) { o.put(name, "n/a"); return }
            try {
                val fx = create() ?: run { o.put(name, "none"); return }
                val was = fx.enabled
                if (want == null) { o.put(name, if (was) "on (platform)" else "off (platform)"); fx.release(); return }
                if (was != want) fx.enabled = want
                val now = fx.enabled
                o.put(name, (if (now) "on" else "off") + (if (was != now) " (was ${if (was) "on" else "off"})" else "") +
                    (if (now != want) " (refused)" else ""))
                if (now) held += fx else fx.release()
            } catch (e: Exception) { o.put(name, "error: ${e.message}") }
        }
        val (agc, ns, aec) = when (mode) {
            "platform" -> Triple(null, null, null)
            "aec" -> Triple(false, false, true)
            "aec_ns" -> Triple(false, true, true)
            else -> Triple(false, false, false)
        }
        one("agc", AutomaticGainControl.isAvailable(), agc) { AutomaticGainControl.create(session) }
        one("ns", NoiseSuppressor.isAvailable(), ns) { NoiseSuppressor.create(session) }
        one("aec", AcousticEchoCanceler.isAvailable(), aec) { AcousticEchoCanceler.create(session) }
        return o
    }

    /**
     * The audio environment, for the echo A/B: a VOICE_COMMUNICATION capture must not switch the phone into a call
     * mode, move media to the earpiece or turn the media volume down (a dealbreaker if it does). Also whether media
     * is playing (the media-aware gate).
     */
    fun env(): JSONObject {
        val o = JSONObject().put("audio_mode", when (audio.mode) {
            AudioManager.MODE_NORMAL -> "normal"; AudioManager.MODE_IN_CALL -> "in_call"
            AudioManager.MODE_IN_COMMUNICATION -> "in_communication"; AudioManager.MODE_RINGTONE -> "ringtone"
            else -> "mode ${audio.mode}" })
            .put("music_active", audio.isMusicActive)
            .put("music_volume", audio.getStreamVolume(AudioManager.STREAM_MUSIC))
            .put("music_volume_max", audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC))
            .put("playbacks", audio.activePlaybackConfigurations.size)
        if (android.os.Build.VERSION.SDK_INT >= 31)
            o.put("communication_device", audio.communicationDevice?.let(::describe) ?: JSONObject.NULL)
        return o
    }

    companion object {
        val SOURCE_NAMES = mapOf(
            MediaRecorder.AudioSource.UNPROCESSED to "unprocessed",
            MediaRecorder.AudioSource.VOICE_RECOGNITION to "voice_recognition",
            MediaRecorder.AudioSource.VOICE_COMMUNICATION to "voice_communication",
            MediaRecorder.AudioSource.MIC to "mic")
        val USB_TYPES = setOf(AudioDeviceInfo.TYPE_USB_DEVICE, AudioDeviceInfo.TYPE_USB_HEADSET)

        fun describe(d: AudioDeviceInfo): String = "${typeName(d.type)}: ${d.productName}" +
            (d.address.takeIf { it.isNotBlank() }?.let { " ($it)" } ?: "")

        fun typeName(t: Int) = when (t) {
            AudioDeviceInfo.TYPE_BUILTIN_MIC -> "builtin"
            AudioDeviceInfo.TYPE_USB_DEVICE -> "usb"
            AudioDeviceInfo.TYPE_USB_HEADSET -> "usb headset"
            AudioDeviceInfo.TYPE_WIRED_HEADSET -> "wired headset"
            AudioDeviceInfo.TYPE_BLUETOOTH_SCO -> "bt sco"
            AudioDeviceInfo.TYPE_TELEPHONY -> "telephony"
            AudioDeviceInfo.TYPE_REMOTE_SUBMIX -> "remote submix"
            else -> "type $t"
        }
    }
}
