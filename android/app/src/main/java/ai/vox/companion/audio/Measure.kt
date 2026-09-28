package ai.vox.companion.audio

import org.json.JSONObject
import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.ShortBuffer
import java.util.concurrent.atomic.AtomicLong

/**
 * The near-field measurement harness (round7-plan §3c, PROTOCOL.md "Near-field measurement"), app side.
 *
 * A session tees the live capture's raw PCM into `files/measure/<sid>/audio.wav` while the capture keeps feeding the
 * extractor (so gestures still work). It also shows a prompt every `every_ms`, and tags every `mic_sound` with the
 * gesture-training matcher's verdict so the PC side can separate "the user's own sounds" from media.
 *
 * This file holds the pure, JVM-tested pieces: the prompt schedule, the WAV header, the stream-ms mapping, the
 * stereo de-interleave and the WAV writer. The session wiring (capture tee, prompt overlay, events) lives in
 * [PhoneMicSource].
 */
object Measure {
    const val DEFAULT_EVERY_MS = 5000
    const val DEFAULT_MAX_S = 300
    /** How long a prompt stays on screen (Overlay.showPrompt's default). */
    const val PROMPT_VISIBLE_MS = 1500L
    val DEFAULT_GESTURES = listOf("rise", "fall", "click", "click click", "hiss")

    /**
     * The prompt schedule: round-robin over [gestures], so prompt [n] shows gestures[n mod size]. Pure and
     * deterministic, so a recorded session can be replayed against its prompts. [gestures] must be non-empty.
     */
    fun promptGesture(gestures: List<String>, n: Int): String = gestures[Math.floorMod(n, gestures.size)]

    /** The number of prompts a session shows before [maxS] seconds ends it. */
    fun promptCount(maxS: Int, everyMs: Int): Int = maxS * 1000 / everyMs

    /**
     * Stream ms: the measurement clock is "ms since the first sample of the current capture stream", i.e. the
     * pushed-samples count scaled to milliseconds. [frames] samples pushed -> frames * 1000 / rate ms.
     */
    fun streamMs(frames: Long, rate: Int): Long = frames * 1000L / rate

    /** [nanoNs] (System.nanoTime) as stream ms against the capture's first-frame clock [frame0Ns]. */
    fun nanoToStreamMs(nanoNs: Long, frame0Ns: Long): Long = (nanoNs - frame0Ns) / 1_000_000L

    /** Whether a session that started [elapsedMs] ago has reached its [maxS] seconds limit. */
    fun maxReached(maxS: Int, elapsedMs: Long): Boolean = elapsedMs >= maxS * 1000L

    /** The longest `measure_cue` text (the prompt overlay shows one large line or two). */
    const val MAX_CUE_CHARS = 120

    /**
     * Why `measure_cue` should refuse, or null to accept. A cue needs a running session whose first sample has arrived
     * (before it `wav_t0_ms` is unknown and the cue could precede the WAV), a non-blank [text] of at most
     * [MAX_CUE_CHARS] and a non-blank [id].
     */
    fun cueError(running: Boolean, sampled: Boolean, text: String, id: String): String? = when {
        !running -> "no measurement running"
        text.isBlank() -> "text must be a non-blank string"
        text.length > MAX_CUE_CHARS -> "text is longer than $MAX_CUE_CHARS characters"
        id.isBlank() -> "id must be a non-blank string"
        // last: only a well-formed cue gets the retryable answer, so a caller never retries a bad one
        !sampled -> "the measurement has no sample yet (retry)"
        else -> null
    }

    /**
     * Why [measureStart] should refuse, or null to accept. A measurement needs the phone or USB mic listening, and
     * only one session runs at a time.
     */
    fun startError(source: String, capturing: Boolean, alreadyRunning: Boolean): String? = when {
        alreadyRunning -> "a measurement is already running"
        source == MicSettings.PICO -> "measure needs sound_source phone or usb, not pico"
        !capturing -> "the mic capture is not listening"
        else -> null
    }

    /**
     * The 44-byte RIFF/WAVE header for PCM16 LE, [channels] interleaved channels at [rate], [dataBytes] of samples.
     * Written twice: a placeholder at open (dataBytes 0) and the real header patched in place on [WavWriter.finish].
     */
    fun wavHeader(rate: Int, channels: Int, dataBytes: Int): ByteArray {
        val b = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
        b.put("RIFF".toByteArray(Charsets.US_ASCII))
        b.putInt(36 + dataBytes)                 // file size - 8
        b.put("WAVE".toByteArray(Charsets.US_ASCII))
        b.put("fmt ".toByteArray(Charsets.US_ASCII))
        b.putInt(16)                             // PCM fmt chunk size
        b.putShort(1)                            // audio format: PCM
        b.putShort(channels.toShort())
        b.putInt(rate)
        b.putInt(rate * channels * 2)            // byte rate
        b.putShort((channels * 2).toShort())     // block align
        b.putShort(16)                           // bits per sample
        b.put("data".toByteArray(Charsets.US_ASCII))
        b.putInt(dataBytes)
        return b.array()
    }

    /**
     * Channel 0 of an interleaved stereo PCM16 buffer, into [dst] (pre-allocated, no per-read allocation). [src] holds
     * 2*[frames] shorts (L0 R0 L1 R1 ...); [dst] receives L0 L1 ... . The extractor is mono, so it hears channel 0
     * while the WAV keeps both. [dst] is left flipped (position 0, limit frames) for the native push.
     */
    fun deinterleaveCh0(src: ShortBuffer, dst: ShortBuffer, frames: Int) {
        dst.clear()
        for (i in 0 until frames) dst.put(src.get(i * 2))
        dst.flip()
    }

    /**
     * Whether capture state [state] of capture generation [gen] ends a session recording from generation [sessionGen]:
     * its own capture stopped or failed, or a newer capture started. An older capture's states (a stereo restart's own
     * "stopped", which can arrive after the new "listening") never do.
     */
    fun captureEndsSession(state: String, gen: Int, sessionGen: Int): Boolean =
        gen > sessionGen || (gen == sessionGen && state != "listening")

    /** The largest WAV data chunk: the RIFF sizes are unsigned 32-bit (max_s 1200 at 48 kHz stereo is ~230 MB). */
    const val MAX_DATA_BYTES = 0xFFFF_FFFFL - 36

    /**
     * A session id unique across service restarts: the wall-clock ms, above [last], and never an existing
     * `measure/<sid>` folder in [measureDir] (a WAV is never overwritten).
     */
    fun newSid(nowMs: Long, last: Long, measureDir: File): Long {
        var sid = maxOf(nowMs, last + 1)
        while (File(measureDir, sid.toString()).exists()) sid++
        return sid
    }
}

/**
 * Appends PCM16 to a WAV file, patching the header on [finish]. Written only on the capture thread ([MeasureSession]
 * hands the tee straight to [MicCapture]); [finish] runs on the main thread, so a lock orders a final in-flight write
 * against the header patch. No allocation per write: the direct capture buffer is written through the file channel.
 */
class WavWriter(private val raf: RandomAccessFile, private val rate: Int, initialChannels: Int) {
    /** The channels the data actually has; fixed on the first sample (a refused stereo falls back to mono). */
    @Volatile var channels = initialChannels
    @Volatile var dataBytes = 0L; private set
    private val lock = Any()
    @Volatile private var closed = false
    // Everything through the one FileChannel: RandomAccessFile.write and its channel do not reliably share the file
    // pointer, so mixing them would let a later write overwrite the header instead of appending.
    private val ch = raf.channel

    init {
        raf.setLength(0)   // never keep an older file's tail
        ch.write(ByteBuffer.wrap(Measure.wavHeader(rate, initialChannels, 0)))
    }

    /** Appends [bytes] bytes of [buf] (from 0); false when closed or at [Measure.MAX_DATA_BYTES] (nothing written).
     *  Leaves [buf] cleared (position 0, limit = capacity) for the next read. Throws on an I/O error. */
    fun write(buf: ByteBuffer, bytes: Int): Boolean = synchronized(lock) {
        if (closed || dataBytes + bytes > Measure.MAX_DATA_BYTES) return false
        buf.position(0).limit(bytes)
        try { while (buf.hasRemaining()) ch.write(buf) } finally { buf.clear() }
        dataBytes += bytes
        true
    }

    /** Patches the sizes and channel count into the header, then closes the file. */
    fun finish() { synchronized(lock) {
        if (closed) return
        closed = true
        try {
            ch.position(0)
            ch.write(ByteBuffer.wrap(Measure.wavHeader(rate, channels, dataBytes.toInt())))   // the unsigned 32-bit bits
        } finally { try { ch.close() } catch (_: Exception) {} }
    } }
}

/**
 * One measurement session's state and its WAV. The capture thread writes PCM through [tee] (and the first write pins
 * [t0Ms] and [channels]); the main thread ([PhoneMicSource]) drives prompts, the max_s stop and the events.
 * `record=false` opens no WAV (prompts and mic_sound tags still run). Nothing is ever read back or uploaded.
 * [onFirstSample] and [onWriteError] run on the capture thread: they only post to the main thread.
 */
class MeasureSession(
    val sid: Long,
    val phase: String,
    val everyMs: Int,
    val gestures: List<String>,
    val prompt: Boolean,
    val record: Boolean,
    val stereo: Boolean,
    val maxS: Int,
    val rate: Int,
    filesDir: File,
    private val onFirstSample: ((MeasureSession) -> Unit)? = null,
    private val onWriteError: ((MeasureSession) -> Unit)? = null,
) {
    /** "measure/<sid>/audio.wav" relative to the app files dir (the `file` field of the events / replies). */
    val relPath: String = "measure/$sid/audio.wav"
    val file: File = File(filesDir, relPath)

    @Volatile var channels = if (stereo) 2 else 1; private set
    /** Stream ms of the first sample the session saw (the WAV's first sample when recording); -1 before it. */
    @Volatile var t0Ms = -1L; private set
    /** The event's `wav_t0_ms`: null when not recording or before the first sample. */
    val wavT0Ms: Long? get() = t0Ms.takeIf { record && it >= 0 }
    /** The capture generation ([MicCapture.generation]) the session records from; set by [PhoneMicSource]. */
    @Volatile var captureGen = -1
    /** Frames written (mono frames; stereo counts frames, not per-channel samples): the WAV's frame count. */
    val samples = AtomicLong(0)
    /** Prompts shown so far (the measure_prompt `n` sequence). */
    @Volatile var promptN = 0; private set
    @Volatile var running = true; private set
    /** measure_start is logged (at the first sample, or at the stop when none came). Main thread. */
    var startLogged = false
    /** Why the tee stopped writing (an I/O error, the size cap), null while fine. */
    @Volatile var writeError: String? = null; private set

    private val wav: WavWriter? = if (record) {
        file.parentFile?.mkdirs()
        WavWriter(RandomAccessFile(file, "rw"), rate, channels)
    } else null

    /** Handed to MicCapture: the capture thread writes the raw PCM (mono or interleaved stereo), no copy. Never throws:
     *  a failed write ends the recording (and, through [onWriteError], the session), never the gesture capture. */
    val tee = object : MicCapture.Tee {
        override fun write(buf: ByteBuffer, bytes: Int, streamMs: Long, ch: Int) {
            if (!running || writeError != null) return
            if (t0Ms < 0) {
                t0Ms = streamMs; channels = ch; wav?.channels = ch
                try { onFirstSample?.invoke(this@MeasureSession) } catch (_: Throwable) {}
            }
            val w = wav ?: return
            try {
                if (w.write(buf, bytes)) samples.addAndGet((bytes / (2 * ch)).toLong())
                else if (running && w.dataBytes + bytes > Measure.MAX_DATA_BYTES) fail("size cap")
            } catch (e: Throwable) { fail(e.toString()) }
        }
    }

    private fun fail(why: String) {
        if (writeError != null) return
        writeError = why
        try { onWriteError?.invoke(this) } catch (_: Throwable) {}
    }

    /** Frames written / rate (whole seconds). */
    val seconds: Long get() = samples.get() / rate

    /** A prompt (scheduled or `measure_cue`) was shown: its `n` (the one sequence of the session), then counted. */
    fun nextPrompt(): Int = promptN.also { promptN = it + 1 }

    fun stop() { running = false }

    /** Closes the WAV, patching the header with the real sizes and channels. No-op when not recording. */
    fun finish() { try { wav?.finish() } catch (e: Exception) { if (writeError == null) writeError = e.toString() } }

    fun status(): JSONObject = JSONObject()
        .put("running", running).put("sid", sid).put("phase", phase)
        .put("seconds", seconds).put("prompts", promptN).put("file", relPath)
}
