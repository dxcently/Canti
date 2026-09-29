package ai.vox.companion

import android.content.Context
import android.content.Intent
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecordingConfiguration
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.ParcelFileDescriptor
import android.os.SystemClock
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.Base64

/**
 * The `asr_audio` debug ops: recognise an AUDIO FILE with the live phrase window's recognizer settings, so recorded
 * phrase clips can be scored by the phone's own recognizer (extractor/phone_asr.py). Debuggable builds only (the
 * debug socket), never the live path.
 *
 * On-device only: createOnDeviceSpeechRecognizer with EXTRA_AUDIO_SOURCE (API 33+), the live intent's extras
 * ([AndroidPhraseRecognizer.intent], offline). When on-device recognition is unavailable the op refuses; it never
 * falls back to an online recognizer. The audio arrives base64 over the socket and is streamed from memory into a
 * pipe in real time: nothing is written to storage. Transcripts go back in the op's reply only, never to the log.
 *
 * Guard: Android documents that a recognizer without EXTRA_AUDIO_SOURCE support silently records from the mic. The
 * op watches the device's active recordings (AudioManager recording callback) and ends the recognition at once if a
 * new one starts ([Result] mic_opened); mic_watch false means it could not watch, so the caller must not trust it.
 *
 * Diagnostics (the Z Flip heard "no speech" in a LibriVox clip that was fully read from the pipe, 2026-09-27): the
 * reply says what the recognizer did with the audio (rms range and count, beginning/end of speech, segments, the
 * error code) and what was sent (level, leading silence, clipping: [AsrAudioArgs.stats]), and which recognition
 * service the on-device recognizer is ([services]). Options ([AsrAudioArgs.Options]) vary one thing at a time:
 * segmented session, feeding before onReadyForSpeech, faster than real time, silence padding, chunk size.
 */
class AudioFileAsr(private val ctx: Context, private val baseIntent: () -> Intent) {
    private val main = Handler(Looper.getMainLooper())
    private val done = LinkedHashMap<String, JSONObject>()
    private var run: Run? = null
    private var seq = 0

    private inner class Run(val id: String, val audio: AsrAudioArgs.Audio, val choose: (Heard) -> JSONObject) {
        val t0 = SystemClock.elapsedRealtime()
        var rec: SpeechRecognizer? = null
        var readFd: ParcelFileDescriptor? = null
        var writeFd: ParcelFileDescriptor? = null
        var writer: Thread? = null
        @Volatile var stopWriting = false
        @Volatile var fedMs = 0L
        var readyMs: Long? = null
        var fedAllMs: Long? = null
        var partial: String? = null
        var micWatch = false
        var micOpened = false
        val micSources = ArrayList<Int>()
        var baseline: Set<Int> = emptySet()
        var baselineCount = 0
        var cb: AudioManager.AudioRecordingCallback? = null
        val cancels = ArrayList<Runnable>()
        // what the recognizer did (diagnostics; no text)
        var rmsMin: Float? = null
        var rmsMax: Float? = null
        var rmsCount = 0
        var beginMs: Long? = null
        var endMs: Long? = null
        var buffers = 0
        val events = ArrayList<Int>()
        val segments = ArrayList<String>()
        var segmentedEnd = false
        val pcm: ByteArray = AsrAudioArgs.framed(audio.pcm, audio.rate, audio.options)
        val sentMs get() = pcm.size / 2 * 1000L / audio.rate
    }

    val busy get() = run != null

    /** Start one recognition; the id's result comes from [result]. [choose]: the grammar's pick for the n-best. */
    fun start(audio: AsrAudioArgs.Audio, choose: (Heard) -> JSONObject): String {
        if (Build.VERSION.SDK_INT < 33) throw IllegalStateException("asr_audio needs Android 13+ (EXTRA_AUDIO_SOURCE); this is API ${Build.VERSION.SDK_INT}")
        check(run == null) { "asr_audio: busy with ${run?.id}" }
        check(SpeechRecognizer.isOnDeviceRecognitionAvailable(ctx)) { "on-device recognition is unavailable (no online fallback)" }
        val r = Run("a${++seq}", audio, choose)
        run = r
        try { begin(r) } catch (e: Exception) { finish(r, "error: start failed: ${e.javaClass.simpleName}: ${e.message}", null, null) }
        return r.id
    }

    /** {state: running|done, result?}; a done result is handed out once and then forgotten (transcripts stay in memory briefly). */
    fun result(id: String): JSONObject {
        run?.let { if (it.id == id) return JSONObject().put("state", "running").put("fed_ms", it.fedMs).put("audio_ms", it.sentMs) }
        val res = done.remove(id) ?: throw IllegalArgumentException("asr_audio_result: unknown id '$id'")
        return JSONObject().put("state", "done").put("result", res)
    }

    private fun begin(r: Run) {
        if (Build.VERSION.SDK_INT < 33) throw IllegalStateException("API ${Build.VERSION.SDK_INT}")
        watchMic(r)
        val pipe = ParcelFileDescriptor.createPipe()
        r.readFd = pipe[0]; r.writeFd = pipe[1]
        val intent = baseIntent().putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE, pipe[0])
        for ((k, v) in AsrAudioArgs.extras(r.audio.rate, r.audio.options)) when (v) {
            is Int -> intent.putExtra(k, v)
            is Boolean -> intent.putExtra(k, v)
            is String -> intent.putExtra(k, v)
            else -> throw IllegalStateException("extra $k: ${v.javaClass}")
        }
        val rec = SpeechRecognizer.createOnDeviceSpeechRecognizer(ctx)
        r.rec = rec
        rec.setRecognitionListener(object : RecognitionListener {
            override fun onReadyForSpeech(params: Bundle?) {
                if (run !== r || r.readyMs != null) return
                r.readyMs = SystemClock.elapsedRealtime() - r.t0
                feed(r)
            }
            override fun onBeginningOfSpeech() { if (run === r && r.beginMs == null) r.beginMs = SystemClock.elapsedRealtime() - r.t0 }
            override fun onRmsChanged(rmsdB: Float) {
                if (run !== r) return
                r.rmsCount++
                if (r.rmsMin == null || rmsdB < r.rmsMin!!) r.rmsMin = rmsdB
                if (r.rmsMax == null || rmsdB > r.rmsMax!!) r.rmsMax = rmsdB
            }
            override fun onBufferReceived(buffer: ByteArray?) { if (run === r) r.buffers++ }
            override fun onEndOfSpeech() { if (run === r && r.endMs == null) r.endMs = SystemClock.elapsedRealtime() - r.t0 }
            override fun onError(error: Int) {
                if (run !== r) return
                finish(r, "error: ${AsrPlan.error(error, offlineOnly = true).first}", error, null)
            }
            override fun onResults(results: Bundle?) {
                if (run !== r) return
                val texts = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION).orEmpty().filter { it.isNotBlank() }
                val conf = results?.getFloatArray(SpeechRecognizer.CONFIDENCE_SCORES)?.toList().orEmpty()
                finish(r, if (texts.isEmpty()) "no speech (empty results)" else "final", null, Heard(texts, conf))
            }
            // A segmented session (option `segmented`) answers in segments until the audio source ends.
            override fun onSegmentResults(segment: Bundle) {
                if (run !== r) return
                segment.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.takeIf { it.isNotBlank() }?.let { r.segments += it }
            }
            override fun onEndOfSegmentedSession() {
                if (run !== r) return
                r.segmentedEnd = true
                finish(r, if (r.segments.isEmpty()) "no speech (segmented)" else "final", null,
                    r.segments.takeIf { it.isNotEmpty() }?.let { Heard(listOf(it.joinToString(" "))) })
            }
            override fun onPartialResults(partial: Bundle?) {
                if (run !== r) return
                partial?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.takeIf { it.isNotBlank() }?.let { r.partial = it }
            }
            override fun onEvent(eventType: Int, params: Bundle?) { if (run === r && r.events.size < 20) r.events += eventType }
        })
        rec.startListening(intent)
        if (r.audio.options.feedAt == "start") feed(r)   // the pipe fills before the recognizer says it is ready
        later(r, READY_WAIT_MS) { if (r.readyMs == null) feed(r) }   // no onReadyForSpeech: feed anyway (the pipe blocks when full)
        later(r, r.sentMs + DEADLINE_EXTRA_MS) { finish(r, "timeout", null, null) }
    }

    /**
     * Stream the raw PCM (no WAV header: [AsrAudioArgs.wav] strips it) into the pipe in [AsrAudioArgs.chunks], in
     * real time unless the option says otherwise (the pipe blocks when full either way), then close it (end of audio).
     */
    private fun feed(r: Run) {
        if (r.writer != null) return
        val fd = r.writeFd ?: return
        val pcm = r.pcm
        val o = r.audio.options
        val chunks = AsrAudioArgs.chunks(pcm.size, r.audio.rate, o.chunkMs)
        r.writer = Thread({
            val start = SystemClock.elapsedRealtime()
            try {
                ParcelFileDescriptor.AutoCloseOutputStream(fd).use { out ->
                    for ((i, c) in chunks.withIndex()) {
                        if (r.stopWriting) break
                        out.write(pcm, c.first, c.second)
                        r.fedMs = (c.first + c.second) / 2 * 1000L / r.audio.rate
                        val wait = start + (i + 1) * o.chunkMs.toLong() - SystemClock.elapsedRealtime()
                        if (o.realtime && wait > 0) Thread.sleep(wait)
                    }
                }
            } catch (_: IOException) {   // the recognizer closed its end (it finished early): fine
            } catch (_: InterruptedException) {}
            main.post { if (run === r) fedAll(r) }
        }, "vox-asr-audio").apply { isDaemon = true; start() }
    }

    /** All audio in: the endpointer should end it (the clip carries trailing silence); else stop, then give up. */
    private fun fedAll(r: Run) {
        if (r.fedAllMs != null) return
        r.fedAllMs = SystemClock.elapsedRealtime() - r.t0
        later(r, ListenWindow.GRACE_MS) {
            try { r.rec?.stopListening() } catch (_: Exception) {}
            later(r, ListenWindow.GRACE_MS) { finish(r, "timeout", null, null) }
        }
    }

    // --- the mic guard ---------------------------------------------------------------------------------------------

    private fun watchMic(r: Run) {
        val am = ctx.getSystemService(AudioManager::class.java) ?: return
        try {
            val now = am.activeRecordingConfigurations
            r.baseline = now.map { it.clientAudioSessionId }.toSet(); r.baselineCount = now.size
            val cb = object : AudioManager.AudioRecordingCallback() {
                override fun onRecordingConfigChanged(configs: MutableList<AudioRecordingConfiguration>?) { checkMic(r, configs.orEmpty()) }
            }
            am.registerAudioRecordingCallback(cb, main)
            r.cb = cb
            r.micWatch = true
        } catch (_: Exception) { r.micWatch = false }
    }

    /** A recording that was not there when the recognition started: the recognizer is (probably) on the mic. Stop at once. */
    private fun checkMic(r: Run, configs: List<AudioRecordingConfiguration>) {
        if (run !== r) return
        val fresh = configs.filter { it.clientAudioSessionId !in r.baseline }
        if (fresh.isEmpty() && configs.size <= r.baselineCount) return
        r.micOpened = true
        fresh.forEach { r.micSources += it.clientAudioSource }
        finish(r, "error: mic opened during a file recognition", null, null)
    }

    // --- the end ---------------------------------------------------------------------------------------------------

    private fun later(r: Run, ms: Long, f: () -> Unit) {
        val task = Runnable { if (run === r) f() }
        r.cancels += task
        main.postDelayed(task, ms)
    }

    private fun finish(r: Run, why: String, code: Int?, heard: Heard?) {
        if (run !== r) return
        // a last look at the recordings before the recognizer goes (a mic that opened between callbacks)
        if (r.micWatch && !r.micOpened) try {
            ctx.getSystemService(AudioManager::class.java)?.activeRecordingConfigurations?.let { cs ->
                val fresh = cs.filter { it.clientAudioSessionId !in r.baseline }
                if (fresh.isNotEmpty() || cs.size > r.baselineCount) { r.micOpened = true; fresh.forEach { r.micSources += it.clientAudioSource } }
            }
        } catch (_: Exception) {}
        run = null
        r.cancels.forEach(main::removeCallbacks)
        r.stopWriting = true
        r.writer?.interrupt()
        r.rec?.let { try { it.cancel() } catch (_: Exception) {}; try { it.destroy() } catch (_: Exception) {} }
        r.cb?.let { cb -> try { ctx.getSystemService(AudioManager::class.java)?.unregisterAudioRecordingCallback(cb) } catch (_: Exception) {} }
        try { r.writeFd?.close() } catch (_: Exception) {}
        try { r.readFd?.close() } catch (_: Exception) {}
        val hyps = heard?.hypotheses.orEmpty()
        val out = JSONObject().put("id", r.id).put("why", if (r.micOpened && !why.startsWith("error: mic")) "error: mic opened during a file recognition" else why)
            .put("error_code", code ?: JSONObject.NULL)
            .put("hypotheses", JSONArray(hyps)).put("confidences", JSONArray(heard?.confidences.orEmpty().map { it.toDouble() }))
            .put("partial", r.partial ?: JSONObject.NULL)
            .put("recognizer", "on_device").put("audio_ms", r.sentMs).put("clip_ms", r.audio.durationMs).put("fed_ms", r.fedMs)
            .put("ready_ms", r.readyMs ?: JSONObject.NULL).put("fed_all_ms", r.fedAllMs ?: JSONObject.NULL)
            .put("elapsed_ms", SystemClock.elapsedRealtime() - r.t0)
            .put("mic_watch", r.micWatch).put("mic_opened", r.micOpened).put("mic_sources", JSONArray(r.micSources))
            .put("heard", JSONObject().put("rms_db_min", r.rmsMin?.toDouble() ?: JSONObject.NULL).put("rms_db_max", r.rmsMax?.toDouble() ?: JSONObject.NULL)
                .put("rms_n", r.rmsCount).put("begin_ms", r.beginMs ?: JSONObject.NULL).put("end_ms", r.endMs ?: JSONObject.NULL)
                .put("buffers", r.buffers).put("events", JSONArray(r.events)).put("segments", r.segments.size).put("segmented_end", r.segmentedEnd))
            .put("sent", AsrAudioArgs.stats(r.pcm, r.audio.rate).json().put("options", r.audio.options.json()))
            .put("service", services())
        if (hyps.isNotEmpty() && !r.micOpened) out.put("pick", try { r.choose(Heard(hyps, heard!!.confidences)) } catch (e: Exception) { JSONObject().put("error", e.toString()) })
        done[r.id] = out
        while (done.size > KEEP_RESULTS) done.remove(done.keys.first())
        // no transcript text in the log: counts and outcome only
        EventLog.ev("asr_audio", "id" to r.id, "why" to out.getString("why"), "n" to hyps.size, "audio_ms" to r.audio.durationMs,
            "elapsed_ms" to out.getLong("elapsed_ms"), "mic_watch" to r.micWatch, "mic_opened" to r.micOpened)
    }

    /**
     * Which recognition service answers: the platform's default on-device one (a framework resource, what
     * createOnDeviceSpeechRecognizer binds), the user's default recognizer, and every installed RecognitionService.
     */
    private fun services(): JSONObject {
        val o = JSONObject()
        try {
            val res = android.content.res.Resources.getSystem()
            val id = res.getIdentifier("config_defaultOnDeviceSpeechRecognitionService", "string", "android")
            o.put("on_device_default", if (id != 0) res.getString(id).ifEmpty { "(empty)" } else "(unknown)")
        } catch (e: Exception) { o.put("on_device_default", "(${e.javaClass.simpleName})") }
        try { o.put("user_default", android.provider.Settings.Secure.getString(ctx.contentResolver, "voice_recognition_service") ?: JSONObject.NULL) }
        catch (e: Exception) { o.put("user_default", "(${e.javaClass.simpleName})") }
        try {
            o.put("installed", JSONArray(ctx.packageManager.queryIntentServices(Intent(android.speech.RecognitionService.SERVICE_INTERFACE), 0)
                .map { "${it.serviceInfo.packageName}/${it.serviceInfo.name}" }))
        } catch (e: Exception) { o.put("installed", "(${e.javaClass.simpleName})") }
        return o
    }

    /** Ends a recognition in flight (service stopping, reset). */
    fun cancel(why: String) { run?.let { finish(it, "cancelled: $why", null, null) } }

    companion object {
        const val READY_WAIT_MS = 1000L
        const val DEADLINE_EXTRA_MS = 10_000L
        const val KEEP_RESULTS = 4
    }
}

/** The `asr_audio` ops' arguments and the grammar's command as JSON: pure, JVM-tested (AudioFileAsrTest). */
object AsrAudioArgs {
    const val RATE = 16000
    const val MAX_MS = 30_000L
    const val MAX_TEXTS = 50

    const val PAD_MAX_MS = 5000
    val CHUNK_MS = 10..200

    /** The clip's raw PCM (16-bit little-endian mono, [rate] Hz: the WAV's data chunk, no header) and the run's [options]. */
    class Audio(val pcm: ByteArray, val rate: Int, val options: Options = Options()) {
        val durationMs: Long get() = pcm.size / 2 * 1000L / rate
    }

    /**
     * Diagnostic knobs, one at a time (defaults = the original run): [segmented] EXTRA_SEGMENTED_SESSION =
     * EXTRA_AUDIO_SOURCE (results per segment until the pipe closes); [feedAt] "ready" (on onReadyForSpeech, or 1 s
     * without it) or "start" (right after startListening); [realtime] false writes as fast as the pipe takes it;
     * [leadMs] / [tailMs] digital silence around the clip; [chunkMs] the write size.
     */
    data class Options(val segmented: Boolean = false, val feedAt: String = "ready", val realtime: Boolean = true,
                       val leadMs: Int = 0, val tailMs: Int = 0, val chunkMs: Int = 20) {
        fun json(): JSONObject = JSONObject().put("segmented", segmented).put("feed_at", feedAt).put("realtime", realtime)
            .put("lead_ms", leadMs).put("tail_ms", tailMs).put("chunk_ms", chunkMs)
    }

    /** `asr_audio` {wav_b64, segmented?, feed_at?, realtime?, lead_ms?, tail_ms?, chunk_ms?}: a base64 WAV, PCM 16-bit mono 16 kHz, 0 < length <= 30 s. */
    fun audio(m: JSONObject): Audio {
        val b64 = m.optString("wav_b64")
        require(b64.isNotEmpty()) { "asr_audio: give wav_b64 (a 16 kHz mono 16-bit PCM WAV, base64)" }
        val bytes = try { Base64.getDecoder().decode(b64) } catch (e: IllegalArgumentException) { throw IllegalArgumentException("asr_audio: wav_b64 is not base64") }
        val a = wav(bytes)
        return Audio(a.pcm, a.rate, options(m))
    }

    fun options(m: JSONObject): Options {
        val d = Options()
        fun ms(k: String, def: Int, range: IntRange): Int = if (!m.has(k)) def else m.getInt(k).also { require(it in range) { "asr_audio: $k must be ${range.first}..${range.last}" } }
        val feedAt = m.optString("feed_at", d.feedAt)
        require(feedAt in setOf("ready", "start")) { "asr_audio: feed_at must be ready or start" }
        return Options(segmented = m.optBoolean("segmented", d.segmented), feedAt = feedAt, realtime = m.optBoolean("realtime", d.realtime),
            leadMs = ms("lead_ms", d.leadMs, 0..PAD_MAX_MS), tailMs = ms("tail_ms", d.tailMs, 0..PAD_MAX_MS), chunkMs = ms("chunk_ms", d.chunkMs, CHUNK_MS))
    }

    /**
     * The intent extras besides EXTRA_AUDIO_SOURCE (the pipe): the format of what is written (must match it exactly:
     * PCM 16-bit, mono, [rate]), offline, and the segmented session when asked (its value names the audio-source extra).
     */
    fun extras(rate: Int, o: Options): List<Pair<String, Any>> = listOfNotNull(
        RecognizerIntent.EXTRA_PREFER_OFFLINE to true,
        RecognizerIntent.EXTRA_AUDIO_SOURCE_ENCODING to AudioFormat.ENCODING_PCM_16BIT,
        RecognizerIntent.EXTRA_AUDIO_SOURCE_CHANNEL_COUNT to 1,
        RecognizerIntent.EXTRA_AUDIO_SOURCE_SAMPLING_RATE to rate,
        if (o.segmented) RecognizerIntent.EXTRA_SEGMENTED_SESSION to RecognizerIntent.EXTRA_AUDIO_SOURCE else null,
    )

    /** What goes into the pipe: [Options.leadMs] of silence, the clip, [Options.tailMs] of silence (whole samples). */
    fun framed(pcm: ByteArray, rate: Int, o: Options): ByteArray {
        val lead = rate * o.leadMs / 1000 * 2; val tail = rate * o.tailMs / 1000 * 2
        if (lead == 0 && tail == 0) return pcm
        return ByteArray(lead + pcm.size + tail).also { System.arraycopy(pcm, 0, it, lead, pcm.size) }
    }

    /** The writes: (offset, length) of [chunkMs] each, whole 16-bit samples, the last one shorter. */
    fun chunks(size: Int, rate: Int, chunkMs: Int): List<Pair<Int, Int>> {
        val step = rate * chunkMs / 1000 * 2
        require(step > 0 && size % 2 == 0)
        return (0 until size step step).map { it to minOf(step, size - it) }
    }

    /** The level of what is sent: a silent, clipped or quiet clip explains "no speech" without the recognizer. */
    data class Stats(val peakDbfs: Double, val rmsDbfs: Double, val leadSilenceMs: Long, val clipped: Int, val samples: Int) {
        fun json(): JSONObject = JSONObject().put("peak_dbfs", r1(peakDbfs)).put("rms_dbfs", r1(rmsDbfs))
            .put("lead_silence_ms", leadSilenceMs).put("clipped", clipped).put("samples", samples)
        private fun r1(x: Double): Any = if (x.isInfinite()) "-inf" else Math.round(x * 10) / 10.0
    }

    /** Little-endian 16-bit samples; lead silence = before the first sample over -40 dBFS. */
    fun stats(pcm: ByteArray, rate: Int): Stats {
        val bb = ByteBuffer.wrap(pcm).order(ByteOrder.LITTLE_ENDIAN)
        val n = pcm.size / 2
        var peak = 0; var sum = 0.0; var clipped = 0; var first = -1
        for (i in 0 until n) {
            val s = bb.getShort(i * 2).toInt()
            val a = if (s == Short.MIN_VALUE.toInt()) 32768 else Math.abs(s)
            if (a > peak) peak = a
            if (a >= 32767) clipped++
            if (first < 0 && a > 327) first = i
            sum += s.toDouble() * s
        }
        fun db(x: Double) = if (x <= 0) Double.NEGATIVE_INFINITY else 20 * Math.log10(x / 32768.0)
        return Stats(db(peak.toDouble()), db(if (n == 0) 0.0 else Math.sqrt(sum / n)), (if (first < 0) n else first) * 1000L / rate, clipped, n)
    }

    /** The PCM of a RIFF/WAVE file (chunks in any order, odd chunks padded), or why not. */
    fun wav(b: ByteArray): Audio {
        require(b.size >= 12 && String(b, 0, 4, Charsets.US_ASCII) == "RIFF" && String(b, 8, 4, Charsets.US_ASCII) == "WAVE") { "asr_audio: not a WAV file" }
        val bb = ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN)
        var off = 12
        var fmt: IntArray? = null   // format, channels, rate, bits
        var data: ByteArray? = null
        while (off + 8 <= b.size) {
            val id = String(b, off, 4, Charsets.US_ASCII)
            val size = bb.getInt(off + 4).toLong() and 0xffffffffL
            val body = off + 8
            require(body + size <= b.size) { "asr_audio: truncated WAV ('$id' chunk)" }
            when (id) {
                "fmt " -> { require(size >= 16) { "asr_audio: bad fmt chunk" }
                    fmt = intArrayOf(bb.getShort(body).toInt() and 0xffff, bb.getShort(body + 2).toInt(), bb.getInt(body + 4), bb.getShort(body + 14).toInt()) }
                "data" -> data = b.copyOfRange(body, body + size.toInt())
            }
            off = body + size.toInt() + (size.toInt() and 1)
        }
        val f = fmt ?: throw IllegalArgumentException("asr_audio: no fmt chunk")
        require(f[0] == 1) { "asr_audio: not PCM (format ${f[0]})" }
        require(f[1] == 1) { "asr_audio: ${f[1]} channels, want mono" }
        require(f[3] == 16) { "asr_audio: ${f[3]}-bit, want 16-bit" }
        require(f[2] == RATE) { "asr_audio: ${f[2]} Hz, want $RATE" }
        val d = data ?: throw IllegalArgumentException("asr_audio: no data chunk")
        require(d.isNotEmpty() && d.size % 2 == 0) { "asr_audio: empty or odd-sized data" }
        // a WAV inside the data chunk would reach the recognizer as a 44-byte click of "samples"
        require(!(d.size >= 12 && String(d, 0, 4, Charsets.US_ASCII) == "RIFF" && String(d, 8, 4, Charsets.US_ASCII) == "WAVE")) { "asr_audio: a WAV header inside the data chunk (double-wrapped)" }
        return Audio(d, f[2]).also { require(it.durationMs <= MAX_MS) { "asr_audio: ${it.durationMs} ms is longer than $MAX_MS ms" } }
    }

    /** `asr_audio_result` {id}. */
    fun id(m: JSONObject): String = m.optString("id").also { require(it.isNotEmpty()) { "asr_audio_result: give id" } }

    /** `grammar` {texts: [...]}: 1..50 non-blank strings. */
    fun texts(m: JSONObject): List<String> {
        val a = m.optJSONArray("texts") ?: throw IllegalArgumentException("grammar: give texts (a list of strings)")
        require(a.length() in 1..MAX_TEXTS) { "grammar: 1..$MAX_TEXTS texts" }
        return (0 until a.length()).map { i -> (a.opt(i) as? String)?.takeIf { it.isNotBlank() } ?: throw IllegalArgumentException("grammar: texts[$i] is not a non-blank string") }
    }

    /** The grammar's command as fields (phone_asr.py scores these against the expected intent). */
    fun command(c: SpeechCommand): JSONObject {
        val o = JSONObject().put("describe", c.describe())
        when (c) {
            is SpeechCommand.OpenApp -> o.put("type", "open_app").put("label", c.label).put("pkg", c.pkg).put("score", c.score).put("others", JSONArray(c.others))
            is SpeechCommand.AppMissing -> o.put("type", "app_missing").put("name", c.name)
            is SpeechCommand.Tap -> o.put("type", "tap").put("query", c.query).put("verb", c.verb ?: JSONObject.NULL)
                .put("fallback", c.fallback?.let(::command) ?: JSONObject.NULL)
            is SpeechCommand.Nav -> o.put("type", "nav").put("phrase", c.phrase).put("count", c.count)
            is SpeechCommand.Timer -> o.put("type", "timer").put("seconds", c.seconds ?: JSONObject.NULL)
            is SpeechCommand.Phrase -> o.put("type", "phrase").put("text", c.text).put("why", c.why)
            is SpeechCommand.Ignore -> o.put("type", "ignore").put("why", c.why)
            is SpeechCommand.Volume -> o.put("type", "volume").put("stream", c.stream.key).put("op", c.op.describe())
            is SpeechCommand.Swipe -> o.put("type", "swipe").put("action", c.action ?: JSONObject.NULL).put("semantic", c.semantic ?: JSONObject.NULL)
                .put("count", c.count).put("how", c.how)
            is SpeechCommand.Followup -> o.put("type", "followup").put("kind", c.kind.name.lowercase())
                .put("dir", c.dir?.name?.lowercase() ?: JSONObject.NULL).put("fallback", c.fallback?.let(::command) ?: JSONObject.NULL)
            is SpeechCommand.Chain -> o.put("type", "chain").put("steps", c.steps.size).put("dangling", c.dangling).put("dropped", c.dropped)
        }
        return o
    }

    /** A grammar pick as JSON: which hypothesis won, its command, and each hypothesis' parse. */
    fun pick(p: PhraseGrammar.Pick): JSONObject = JSONObject().put("index", p.index).put("text", p.text).put("command", command(p.command))
        .put("parsed", JSONArray(p.parsed.map(::command)))
}
