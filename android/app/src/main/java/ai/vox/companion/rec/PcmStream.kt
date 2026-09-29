package ai.vox.companion.rec

import ai.vox.companion.Scheduler
import java.util.Base64

/**
 * PC stream (contract §5 pcm_*): the PC records the phone's own mic capture over the debug socket by polling the RAM
 * ring. One stream at a time; while it is open every phone/usb sound is dropped as "pc stream" (RecDrops.reason), so
 * Canti never acts on the takes, and the recorder / calibration / training refuse to start. The sample clock is the
 * ring's stream frame; each read returns up to [READ_S] seconds of PCM16 LE mono as base64. An idle timer (renewed by
 * every read) closes the stream when the PC stops polling, so a crashed PC never leaves Canti deaf. All timing runs
 * through the injected [scheduler], so the whole machine is JVM-tested without Android.
 *
 * Ops (flat replies): pcm_open {idle_ms?} / pcm_read {sid, from} / pcm_close {sid}. A capture generation or rate
 * change since the open closes the stream with {ok:false, error:"capture restarted", gen} on the next read. Events are
 * logged as `pc_stream{event, sid, rate, frames}` (never audio).
 */
class PcmStream(
    private val scheduler: Scheduler,
    private val ring: RingBuffer,
    private val env: Env,
) {
    interface Env {
        val source: String            // phone | usb | pico
        val micName: String           // "phone built-in mic" / "usb: <device>"
        val capturing: Boolean
        val listening: Boolean        // the mic capture is listening
        val mode: String              // gesture | cursor | listening
        val calibrating: Boolean
        val training: Boolean
        val measuring: Boolean
        val recording: Boolean        // a recorder session is open
    }

    companion object {
        const val DEFAULT_IDLE_MS = 5000L
        const val MIN_IDLE_MS = 1000L
        const val MAX_IDLE_MS = 30000L
        /** The most frames one pcm_read returns (2 s at the capture rate). */
        const val READ_S = 2
    }

    /** One open stream: its sid, the capture it was opened against, and how many frames it has sent. */
    private class Stream(
        val sid: Long,
        val idleMs: Long,
        val rate: Int,
        val gen: Int,
        val frame: Long,
        val mic: String,
        val source: String,
    ) {
        var framesSent = 0L
        var idleCancel: (() -> Unit)? = null
    }

    private var nextSid = 1L
    private var stream: Stream? = null

    /** A PC stream is open (its sounds are dropped as "pc stream"). */
    val isOpen: Boolean get() = stream != null

    fun command(method: String, args: Map<String, Any?>): Map<String, Any?> = when (method) {
        "pcm_open" -> open(args)
        "pcm_read" -> read(args)
        "pcm_close" -> close(args)
        else -> mapOf("ok" to false, "error" to "unknown pcm op '$method'")
    }

    /** VoxService shutdown: end the stream (its sounds would otherwise stay dropped). */
    fun closeForShutdown() { stream?.let { closeStream(it, "close") } }

    // --- commands -------------------------------------------------------------------------------------------------

    private fun refuse(): String? {
        val src = env.source
        if (src != "phone" && src != "usb") return "the PC stream records the running phone/usb capture only (source: $src)"
        if (!env.capturing || !env.listening) return "not listening"
        if (env.mode != "gesture") return "Switch Canti to gesture mode first"
        if (env.recording) return "a recorder session is open"
        if (env.calibrating) return "a calibration is open"
        if (env.training) return "a training round is open"
        if (env.measuring) return "a measurement is open"
        if (stream != null) return "a PC stream is already open"
        return null
    }

    private fun open(args: Map<String, Any?>): Map<String, Any?> {
        refuse()?.let { return mapOf("ok" to false, "error" to it) }
        val idleMs = (args["idle_ms"] as? Number)?.toLong()?.coerceIn(MIN_IDLE_MS, MAX_IDLE_MS) ?: DEFAULT_IDLE_MS
        val s = Stream(nextSid++, idleMs, ring.sampleRate, ring.generation, ring.end, env.micName, env.source)
        stream = s
        armIdleClose(s)
        log("open", s)
        return mapOf("ok" to true, "sid" to s.sid, "rate" to s.rate, "gen" to s.gen, "frame" to s.frame,
            "mic" to s.mic, "source" to s.source)
    }

    private fun read(args: Map<String, Any?>): Map<String, Any?> {
        val sid = (args["sid"] as? Number)?.toLong()
        val s = stream
        if (sid == null || s == null || s.sid != sid) return mapOf("ok" to false, "error" to "no stream")
        val from = (args["from"] as? Number)?.toLong()
            ?: return mapOf("ok" to false, "error" to "pcm_read needs {sid, from}")
        // A capture restart (new generation) or a rate change since the open: the stream is on a dead clock.
        if (ring.sampleRate != s.rate || ring.generation != s.gen) {
            closeStream(s, "restart")
            return mapOf("ok" to false, "error" to "capture restarted", "gen" to ring.generation)
        }
        val start = maxOf(from, ring.start)
        val to = minOf(ring.end, start + s.rate * READ_S)
        val lost = maxOf(0L, ring.start - from)
        val samples = ring.copy(start, to) ?: ShortArray(0)
        s.framesSent += samples.size
        armIdleClose(s)   // every read renews the idle timer
        return mapOf("ok" to true, "sid" to s.sid, "gen" to s.gen, "rate" to s.rate, "from" to from, "to" to to,
            "start" to start, "end" to ring.end, "lost_frames" to lost, "b64" to pcm16ToB64(samples))
    }

    private fun close(args: Map<String, Any?>): Map<String, Any?> {
        val sid = (args["sid"] as? Number)?.toLong()
        val s = stream
        if (sid == null || s == null || s.sid != sid) return mapOf("ok" to false, "error" to "no stream")
        val frames = s.framesSent
        closeStream(s, "close")
        return mapOf("ok" to true, "frames_sent" to frames)
    }

    // --- idle timer + events ---------------------------------------------------------------------------------------

    private fun armIdleClose(s: Stream) {
        s.idleCancel?.invoke()
        s.idleCancel = scheduler.schedule(s.idleMs) { if (stream === s) closeStream(s, "idle_close") }
    }

    private fun closeStream(s: Stream, event: String) {
        s.idleCancel?.invoke()
        s.idleCancel = null
        if (stream === s) stream = null
        log(event, s)
    }

    private fun log(event: String, s: Stream) {
        ai.vox.companion.EventLog.ev("pc_stream", "event" to event, "sid" to s.sid, "rate" to s.rate,
            "frames" to s.framesSent)
    }

    /** The samples as PCM16 little-endian bytes, base64 (standard, no line breaks). */
    private fun pcm16ToB64(samples: ShortArray): String {
        if (samples.isEmpty()) return ""
        val bytes = ByteArray(samples.size * 2)
        for (i in samples.indices) {
            val v = samples[i].toInt()
            bytes[i * 2] = (v and 0xff).toByte()
            bytes[i * 2 + 1] = (v shr 8).toByte()
        }
        return Base64.getEncoder().encodeToString(bytes)
    }
}
