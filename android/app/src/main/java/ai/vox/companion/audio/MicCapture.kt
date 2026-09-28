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
                      val extractorJson: String? = null,
                      /** Near-field measurement: open CHANNEL_IN_STEREO (fall back to mono if the device refuses). */
                      val stereo: Boolean = false)

    /** The measurement tee: the capture thread hands each read's raw PCM here (see [tee]), no copy. */
    interface Tee {
        /** [buf] holds [bytes] bytes of PCM16 LE (mono or interleaved stereo); [streamMs] is the stream ms of its
         *  first sample (the pushed count before this read); [channels] is the actual channel count (a refused
         *  stereo fell back to mono). */
        fun write(buf: ByteBuffer, bytes: Int, streamMs: Long, channels: Int)
    }

    interface Listener {
        /** Native messages (JSON strings) that just finished; [baseMs] maps stream ms to nanoTime ms; [gen] is the
         *  capture ([generation]) that heard them. */
        fun onMessages(msgs: Array<String>, baseMs: Long, nowNs: Long, gen: Int)
        /** Capture [gen] started (routed device, effects) or failed / ended ([error] non-null on failure). A restart's
         *  old "stopped" can arrive after the new "listening": compare [gen]. */
        fun onState(state: String, info: JSONObject, gen: Int)
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

    // Near-field measurement (round7-plan §3c): the tee set while a measurement runs; the capture thread hands each
    // read's raw PCM to it (write on the capture thread: a 20 ms read is ~640 B-2.5 KB, written to the page cache, a
    // few microseconds — cheaper than a queue + a second thread for a debug-only feature).
    // The tee is bound to one capture generation: a restart's old thread (still in its last read) never writes to it.
    class TeeBinding(val gen: Int, val tee: Tee)
    @Volatile var tee: TeeBinding? = null
    /** Bumped by every [start]: identifies one capture (its stream clock, its states, its messages). */
    @Volatile var generation = 0; private set
    /** The current stream's first-frame clock (System.nanoTime), 0 until its first read. Only the current thread sets it. */
    @Volatile private var frame0Ns = 0L
    /** The channel count the current capture actually opened (1 or 2; a refused stereo falls back to 1). */
    @Volatile var actualChannels = 1; private set

    val isRunning get() = session?.get() == true

    /** [nanoNs] (System.nanoTime) as stream ms of capture [gen], or null when [gen] is not the current capture or its
     *  first read has not come yet (no clock). */
    fun nanoToStreamMs(nanoNs: Long, gen: Int): Long? {
        val f0 = frame0Ns
        return if (gen != generation || f0 == 0L) null else Measure.nanoToStreamMs(nanoNs, f0)
    }

    /**
     * Whether the device reports stereo capture for [rate] (getMinBufferSize, no AudioRecord opened). The real build
     * in [run] may still refuse and fall back to mono, reported through [actualChannels].
     */
    fun stereoSupported(rate: Int, preset: String): Boolean =
        AudioRecord.getMinBufferSize(rate, AudioFormat.CHANNEL_IN_STEREO, AudioFormat.ENCODING_PCM_16BIT) > 0

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
        frame0Ns = 0L
        val gen = generation + 1
        generation = gen
        thread = Thread({ run(cfg, alive, gen) }, "vox-mic").apply { start() }
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
    private fun run(cfg: Config, alive: AtomicBoolean, gen: Int) {
        Process.setThreadPriority(Process.THREAD_PRIORITY_AUDIO)
        val frames = cfg.rate * cfg.readMs / 1000
        val src = source(cfg.preset)
        var rec: AudioRecord? = null
        var handle = 0L
        val held = ArrayList<android.media.audiofx.AudioEffect>()   // effects we turned on: kept until the capture ends
        val info = JSONObject().put("rate", cfg.rate).put("read_ms", cfg.readMs).put("preset", cfg.preset)
            .put("source", SOURCE_NAMES[src] ?: src.toString())
        try {
            info.put("env_before", env())   // before the AudioRecord exists: what a VOICE_COMMUNICATION capture changes shows in env_after
            handle = VxNative.open(cfg.rate, configJson = cfg.extractorJson)
            // Near-field measurement: open stereo when asked, else mono; a device that refuses stereo falls back to mono.
            var channels = if (cfg.stereo) 2 else 1
            var r: AudioRecord? = null
            var min = 0
            for (ch in intArrayOf(channels, if (channels == 2) 1 else -1)) {
                if (ch <= 0) continue
                val mask = if (ch == 2) AudioFormat.CHANNEL_IN_STEREO else AudioFormat.CHANNEL_IN_MONO
                val fmt = AudioFormat.Builder().setEncoding(AudioFormat.ENCODING_PCM_16BIT).setSampleRate(cfg.rate).setChannelMask(mask).build()
                min = AudioRecord.getMinBufferSize(cfg.rate, mask, AudioFormat.ENCODING_PCM_16BIT)
                val cand = AudioRecord.Builder().setAudioSource(src).setAudioFormat(fmt)
                    .setBufferSizeInBytes(maxOf(min * 2, frames * 2 * ch * 4)).build()
                if (cand.state == AudioRecord.STATE_INITIALIZED) { r = cand; channels = ch; break }
                cand.release()
            }
            if (r == null) throw IllegalStateException("AudioRecord did not initialise")
            rec = r
            actualChannels = channels
            info.put("channels", channels).put("stereo_ok", channels == 2 || !cfg.stereo)
            cfg.device?.let { r.setPreferredDevice(it) }
            sessionId = r.audioSessionId
            info.put("effects", effects(r.audioSessionId, cfg.effects, held)).put("buffer_bytes", r.bufferSizeInFrames * 2 * channels).put("min_buffer_bytes", min)
            r.startRecording()
            if (r.recordingState != AudioRecord.RECORDSTATE_RECORDING) throw IllegalStateException("AudioRecord did not start (mic in use?)")
            val bytes = frames * 2 * channels
            val buf = ByteBuffer.allocateDirect(bytes).order(ByteOrder.nativeOrder())
            val monoBuf = if (channels == 2) ByteBuffer.allocateDirect(frames * 2).order(ByteOrder.nativeOrder()) else null
            // Stereo: short views made once (no per-read allocation; indexed absolutely, so the tee moving buf's
            // position cannot shift them). AudioRecord.read and pushDirect use the buffers' base address.
            val stereoSrc = if (channels == 2) buf.duplicate().order(ByteOrder.nativeOrder()).asShortBuffer() else null
            val stereoDst = monoBuf?.asShortBuffer()
            val ts = AudioTimestamp()
            var f0 = 0L   // this stream's first-frame clock; published to [frame0Ns] (the measurement clock) while current
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
                val k = n / (2 * channels)
                val now = System.nanoTime()
                if (pushed == 0L) f0 = now - k * 1_000_000_000L / cfg.rate
                // Frame clock from the audio HAL, when it has one: exact capture times, re-read every 2 s.
                if (now - tsAt > 2_000_000_000L && r.getTimestamp(ts, AudioTimestamp.TIMEBASE_MONOTONIC) == AudioRecord.SUCCESS) {
                    f0 = ts.nanoTime - ts.framePosition * 1_000_000_000L / cfg.rate
                    tsAt = now; tsSource = "AudioTimestamp"
                }
                if (session === alive && frame0Ns != f0) frame0Ns = f0
                val wantTicks = ticks
                if (wantTicks != ticksOn) { ticksOn = VxNative.enableTicks(handle, wantTicks) && wantTicks; clarityApplied = Double.NaN; f0MaxApplied = Double.NaN; tickT0Ms = pushed * 1000.0 / cfg.rate }
                if (ticksOn) tickClarityOn.let { if (it != clarityApplied) { VxNative.setTickClarityOn(handle, it); clarityApplied = it } }
                if (ticksOn) tickF0MaxHz.let { if (it != f0MaxApplied) { VxNative.setTickF0MaxHz(handle, it); f0MaxApplied = it } }
                // The stream ms of this buffer's first sample (before its frames are counted): the measurement tee's clock.
                val streamMs = pushed * 1000L / cfg.rate
                // Stereo: the extractor is mono, so it gets channel 0 (de-interleaved, no allocation); the WAV keeps both.
                val pushBuf = if (channels == 2) { Measure.deinterleaveCh0(stereoSrc!!, stereoDst!!, k); monoBuf } else buf
                val msgs = VxNative.pushDirect(handle, pushBuf, k, false)
                pushed += k
                // The measurement tee, only for the capture it is bound to. It never throws; the catch is a last guard:
                // a failed recording must never end the gesture capture.
                val tb = tee
                if (tb != null && tb.gen == gen) {
                    try { tb.tee.write(buf, n, streamMs, channels) } catch (_: Throwable) { if (tee === tb) tee = null }
                    buf.clear()
                }
                if (!reported) {
                    reported = true
                    routed = r.routedDevice?.let(::describe)
                    info.put("routed", routed ?: JSONObject.NULL).put("clock", tsSource).put("env_after", env())
                    listener.onState("listening", info, gen)
                }
                if (msgs != null) listener.onMessages(msgs, f0 / 1_000_000L, now, gen)
                if (ticksOn) {
                    var m = VxNative.takeTicks(handle, tickRows)
                    while (m > 0) {
                        if (tickT0Ms != 0.0) for (i in 0 until m) tickRows[i * VxNative.TICK_COLS + VxNative.TICK_T_MS] += tickT0Ms
                        listener.onTicks(tickRows, m, f0 / 1_000_000L)
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
            listener.onState("stopped", info, gen)
        } catch (e: Throwable) {
            listener.onState("error", info.put("error", e.toString()), gen)
        } finally {
            held.forEach { try { it.release() } catch (_: Exception) {} }
            try { rec?.stop() } catch (_: Exception) {}
            rec?.release()
            if (handle != 0L) VxNative.destroy(handle)
            alive.set(false)
            if (session === alive) { routed = null; frame0Ns = 0L; actualChannels = 1 }
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
