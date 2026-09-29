package ai.vox.companion.rec

import ai.vox.companion.Scheduler
import ai.vox.companion.audio.Measure
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.log10
import kotlin.math.sqrt

/**
 * Quick record (contract §5 qr_*): a RAM-only snapshot of the last ~12 s of mic audio plus what Canti heard and did in
 * that window, saved only when the user taps Save. Nothing touches storage until qr_save. One pending snapshot; a new
 * snap replaces it; dropped after 10 min or on qr_save / qr_discard. Pure (the clip and HeardLog math) except qr_save's
 * file IO, so it is JVM-tested.
 */
class QuickRec(
    private val scheduler: Scheduler,
    private val wallClock: () -> Long,
    private val ring: RingBuffer,
    private val heard: HeardLog,
    private val env: Env,
    private val filesDir: File,
) {
    interface Env {
        val source: String           // phone | usb (the capture the ring holds)
        val micName: String
        val appForeground: String
        val mode: String
        val minLevelDb: Double?      // the mic's level-gate min_level_dbfs, or null
    }

    companion object {
        const val EXPIRY_MS = 10L * 60_000L
        /** qr_save's labels (the picker's "misfire / other" is `misfire`). */
        val LABELS = setOf("rise", "fall", "dip", "arch", "pop", "pop pop", "click", "hiss", "hum", "misfire")
    }

    private class Snap(
        val id: String,
        val rate: Int,
        val clip: ShortArray,
        val clipStartMs: Long,
        val gen: Int,
        val barsDb: List<Double>,
        val minDb: Double?,
        val sounds: List<Map<String, Any?>>,
        val lastAction: Map<String, Any?>?,
        val app: String,
        val mode: String,
        val atMs: Long,
    )

    private var pending: Snap? = null
    private var expiryCancel: (() -> Unit)? = null

    /** The snapshot map (contract §5), or {id: null} when none is pending. */
    fun pending(): Map<String, Any?> {
        val s = pending ?: return mapOf("id" to null)
        return snapMap(s)
    }

    /** Copies the whole ring plus the HeardLog window and the last action into one pending snapshot. */
    fun snap(): Map<String, Any?> {
        // one consistent view of the ring (the capture thread keeps writing)
        val held = ring.held() ?: return mapOf("id" to null, "error" to "nothing heard yet: the mic is not listening")
        expiryCancel?.invoke()
        val rate = held.rate
        val gen = held.gen
        val clip = held.samples
        val startMs = held.startFrame * 1000 / rate
        val endMs = held.endFrame * 1000 / rate
        val id = wallClock().toString()
        val atMs = scheduler.now()
        val bars = barsDb(clip, rate)
        val sounds = heard.window(gen, startMs, endMs).map { h ->
            val did = heard.did(h)
            mapOf("label" to h.label, "t_start_ms" to h.tStartMs, "t_end_ms" to h.tEndMs,
                "rel_ms" to (h.tStartMs - startMs), "dur_ms" to (h.tEndMs - h.tStartMs),
                "pitch16" to h.pitch16, "f0_hz" to h.f0Hz, "dropped" to h.dropped, "gated" to h.gated,
                "relabel" to h.relabel,
                "did" to did?.let { mapOf("n" to it.n, "sequence" to it.sequence, "action" to it.action, "ok" to it.ok) },
                "did_text" to heard.didText(h, did), "ago_s" to (atMs - h.t) / 1000.0)
        }
        // the last thing Canti did, from the whole log (it may be older than the clip)
        val lastAction = heard.sounds().lastOrNull { heard.did(it) != null }?.let { h ->
            mapOf("text" to heard.didText(h, heard.did(h)), "ago_s" to (atMs - h.t) / 1000.0,
                "in_clip" to (gen == heard.generation && h.tEndMs in startMs..endMs))
        }
        val snap = Snap(id, rate, clip, startMs, gen, bars, env.minLevelDb, sounds, lastAction, env.appForeground, env.mode, atMs)
        pending = snap
        expiryCancel = scheduler.schedule(EXPIRY_MS) { if (pending?.id == snap.id) pending = null }
        return snapMap(snap)
    }

    /** Writes files/quickrec/<id>/{clip.wav, meta.json} (tmp + rename) and clears the pending snapshot. */
    fun save(id: String, label: String, note: String?, sound: Int?): Map<String, Any?> {
        val s = pending?.takeIf { it.id == id } ?: return mapOf("ok" to false, "error" to "no such pending snapshot")
        if (label !in LABELS) return mapOf("ok" to false, "error" to "label must be one of ${LABELS.joinToString(" | ")}")
        if (sound != null && sound !in s.sounds.indices) return mapOf("ok" to false, "error" to "sound must index the snapshot's sounds")
        val dir = File(filesDir, "quickrec/$id")
        val clipFile = File(dir, "clip.wav")
        dir.mkdirs()
        val tmp = File(dir, "clip.tmp.wav")
        RandomAccessFile(tmp, "rw").use { raf ->
            raf.setLength(0)
            raf.write(Measure.wavHeader(s.rate, 1, s.clip.size * 2))
            val bb = ByteBuffer.allocate(s.clip.size * 2).order(ByteOrder.LITTLE_ENDIAN)
            bb.asShortBuffer().put(s.clip)
            raf.write(bb.array())
        }
        require(tmp.renameTo(clipFile)) { "could not write $clipFile" }
        val meta = JSONObject()
            .put("version", 1).put("id", id).put("saved_at_ms", wallClock())
            .put("label", label).put("note", note ?: JSONObject.NULL).put("sound", sound ?: JSONObject.NULL)
            .put("rate", s.rate).put("seconds", s.clip.size.toDouble() / s.rate)
            .put("source", env.source).put("mic", env.micName).put("app", s.app).put("mode", s.mode)
            .put("sounds", JSONArray(s.sounds.map { JSONObject(it) }))
        val metaFile = File(dir, "meta.json")
        val mtmp = File(dir, "meta.json.tmp")
        mtmp.writeText(meta.toString(2) + "\n")
        require(mtmp.renameTo(metaFile)) { "could not write $metaFile" }
        pending = null
        expiryCancel?.invoke(); expiryCancel = null
        return mapOf("ok" to true, "id" to id, "file" to "quickrec/$id/clip.wav", "bytes" to clipFile.length())
    }

    fun discard(id: String): Map<String, Any?> {
        if (pending?.id == id) { pending = null; expiryCancel?.invoke(); expiryCancel = null }
        return mapOf("ok" to true)
    }

    /** The qr_* ops. */
    fun command(method: String, args: Map<String, Any?>): Map<String, Any?> = when (method) {
        "qr_snap" -> snap()
        "qr_pending" -> pending()
        "qr_save" -> save(args["id"] as? String ?: "", args["label"] as? String ?: "", args["note"] as? String,
            (args["sound"] as? Number)?.toInt())
        "qr_discard" -> discard(args["id"] as? String ?: "")
        else -> mapOf("error" to "unknown quickrec op '$method'")
    }

    private fun snapMap(s: Snap): Map<String, Any?> = mapOf(
        "id" to s.id, "seconds" to s.clip.size.toDouble() / s.rate, "rate" to s.rate,
        "bars_db" to s.barsDb, "min_db" to s.minDb, "sounds" to s.sounds, "last_action" to s.lastAction,
        "app" to s.app, "mode" to s.mode)

    /** 100 ms RMS dBFS over the clip, oldest first. */
    private fun barsDb(clip: ShortArray, rate: Int): List<Double> {
        val tick = (rate / 10).coerceAtLeast(1)   // 100 ms
        val out = ArrayList<Double>()
        var o = 0
        while (o + tick <= clip.size) {
            var sumSq = 0.0
            for (i in o until o + tick) { val s = clip[i] / 32768.0; sumSq += s * s }
            out.add(20.0 * log10(sqrt(sumSq / tick) + 1e-9))
            o += tick
        }
        return out
    }
}

/** Counts the quickrec folders for rec_list's quickrec: {count, bytes}. */
fun quickrecSummary(filesDir: File): Map<String, Any?> {
    val dir = File(filesDir, "quickrec")
    val count = if (dir.isDirectory) dir.listFiles()?.count { it.isDirectory } ?: 0 else 0
    val bytes = if (dir.isDirectory) dir.walkTopDown().filter { it.isFile }.sumOf { it.length() } else 0L
    return mapOf("count" to count, "bytes" to bytes)
}
