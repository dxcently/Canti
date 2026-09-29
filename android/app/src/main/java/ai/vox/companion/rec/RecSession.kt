package ai.vox.companion.rec

import ai.vox.companion.audio.Measure
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * The on-disk recorder session (contract §7): pure file IO on a root dir, writing exactly the layout
 * extractor/range_layout.validate_session reads. Nothing here touches the capture or the UI, so it is JVM-tested by
 * writing a short session into a temp dir.
 *
 * Root `files/range/<name>/`: spec.json (the bundled spec bytes verbatim), session.json, labels.jsonl,
 * backgrounds.jsonl, ratings.jsonl (created empty), and the `takes/` / `backgrounds/` WAVs. WAVs are written to a
 * `.tmp.wav` then renamed BEFORE their label row is appended. The timing fields use frame counts, never ms rounding,
 * so `clip_start_ms + go_offset_ms == t_go_ms` holds to the sample.
 *
 * Missed takes are kept (range_layout.take_rows): a "no sound" attempt goes to `takes/<block>/<take_id>.a<redo>.wav`
 * with `no_sound: true, attempt: <redo>`, so a Try again never overwrites it; the plain `<take_id>.wav` is always the
 * latest heard attempt. A take's row is its last heard row, else its last missed one.
 */
class RecSession(
    val root: File,
    val rate: Int,
    val mic: String,
    private val preRollFrames: Int,
) {
    val name: String get() = root.name
    private val metaFile get() = File(root, "session.json")
    private val specFile get() = File(root, "spec.json")
    private val labelsFile get() = File(root, "labels.jsonl")
    private val backgroundsFile get() = File(root, "backgrounds.jsonl")
    private val ratingsFile get() = File(root, "ratings.jsonl")

    // What this object wrote or read, so rec_status (10 Hz while a take runs) never re-reads the journals or walks the
    // folder: this object is the session's only writer while it is open.
    private val rowCache = HashMap<File, MutableList<JSONObject>>()
    private var metaCache: JSONObject? = null
    private var bytesCache: Long? = null

    /** Creates a fresh session: spec.json verbatim, session.json (range null, range_pending, app_range), empty jsonl. */
    fun create(specBytes: ByteArray, profile: String, speaker: String, appRange: Map<String, Double?>) {
        require(!metaFile.exists()) { "session already exists: $name" }
        root.mkdirs()
        specFile.writeBytes(specBytes)
        val meta = JSONObject()
            .put("device", "phone").put("mic", mic).put("rate", rate).put("channels", 1)
            .put("spec", "range_v1").put("synthetic", false).put("profile", profile).put("speaker", speaker)
            .put("range", JSONObject()
                .put("bottom_hz", JSONObject.NULL).put("home_hz", JSONObject.NULL)
                .put("top_hz", JSONObject.NULL).put("whistle_home_hz", JSONObject.NULL).put("below_f0_min", false))
            .put("sittings", JSONArray())
            .put("private", "Never commit, upload, or send recordings to a model.")
            .put("recorder", "app").put("range_pending", true)
            .put("app_range", JSONObject()
                .put("bottom_hz", appRange["bottom_hz"] ?: JSONObject.NULL)
                .put("home_hz", appRange["home_hz"] ?: JSONObject.NULL)
                .put("top_hz", appRange["top_hz"] ?: JSONObject.NULL)
                .put("whistle_home_hz", JSONObject.NULL))
            .put("skipped_by_sitting", JSONArray())
        writeJsonAtomic(metaFile, meta)
        for (f in listOf(labelsFile, backgroundsFile, ratingsFile)) f.createNewFile()
        appendSitting(meta)
    }

    /** Resumes [name]: refuses a differing spec (byte-for-byte), rate or mic, then appends a sitting. */
    fun open(specBytes: ByteArray, expectedRate: Int, expectedMic: String): JSONObject {
        if (!metaFile.exists()) throw IllegalArgumentException("no such session: $name")
        if (!specFile.readBytes().contentEquals(specBytes)) throw IllegalArgumentException("session spec differs from the bundled spec")
        val meta = JSONObject(metaFile.readText())
        if (meta.optInt("rate") != expectedRate || meta.optString("mic") != expectedMic)
            throw IllegalArgumentException("session recorded at ${meta.optInt("rate")} Hz on the ${meta.optString("mic")}")
        return appendSitting(meta)
    }

    private fun appendSitting(meta: JSONObject): JSONObject {
        val s = meta.getJSONArray("sittings")
        s.put(JSONObject().put("started", System.currentTimeMillis() / 1000.0).put("ended", JSONObject.NULL))
        writeJsonAtomic(metaFile, meta)
        return meta
    }

    fun meta(): JSONObject = JSONObject((metaCache ?: JSONObject(metaFile.readText()).also { metaCache = it }).toString())

    /** The current 1-based sitting index. */
    fun sitting(): Int = meta().getJSONArray("sittings").length()

    /** Ends the current sitting (sittings[-1].ended = now). */
    fun closeSitting() {
        val meta = meta()
        val s = meta.getJSONArray("sittings")
        if (s.length() > 0) s.getJSONObject(s.length() - 1).put("ended", System.currentTimeMillis() / 1000.0)
        writeJsonAtomic(metaFile, meta)
    }

    /** Records a take skip for this sitting (kept in session.json skipped_by_sitting). */
    fun skip(takeId: String) {
        val meta = meta()
        val arr = meta.getJSONArray("skipped_by_sitting")
        while (arr.length() < sitting()) arr.put(JSONArray())
        arr.getJSONArray(sitting() - 1).put(takeId)
        writeJsonAtomic(metaFile, meta)
    }

    fun skipped(sitting: Int): Set<String> {
        val arr = meta().optJSONArray("skipped_by_sitting") ?: return emptySet()
        if (arr.length() < sitting) return emptySet()
        return arr.getJSONArray(sitting - 1).let { a -> (0 until a.length()).map { a.getString(it) }.toSet() }
    }

    /**
     * Writes [clip] (the take PCM, `[GO - pre_roll, end + post_roll)`) to `takes/<block>/<take_id>.wav` (tmp + rename),
     * THEN appends the label row. [goFrame] is GO's absolute stream frame; [redo] counts previous rows of the take_id;
     * [appHeard] is what Canti heard. A [noSound] attempt is kept in its own `<take_id>.a<redo>.wav` and its row gets
     * `no_sound: true, attempt: <redo>`. Returns the appended row.
     */
    fun saveTake(take: RangePlan.Take, clip: ShortArray, goFrame: Long, redo: Int, appHeard: List<String>, noSound: Boolean): JSONObject {
        val rel = takeFile(take.block, take.takeId, if (noSound) redo else null)
        writeWavAtomic(File(root, rel), clip)
        val row = JSONObject()
            .put("take_id", take.takeId).put("block", take.block)
            .put("expect", JSONArray(take.expect))
            .put("cond", JSONObject(take.cond))
            .put("cond_id", take.condId ?: JSONObject.NULL).put("rep", take.rep)
            .put("bg", take.bg ?: JSONObject.NULL)
            .put("file", rel)
            .put("redo", redo)
            .put("t_go_ms", goFrame * 1000.0 / rate)
            .put("dur_ms", clip.size * 1000.0 / rate)
            .put("clip_start_ms", (goFrame - preRollFrames) * 1000.0 / rate)
            .put("go_offset_ms", preRollFrames * 1000.0 / rate)
            .put("sitting", sitting())
            .put("app_heard", JSONArray(appHeard))
        if (noSound) row.put("no_sound", true).put("attempt", redo)
        appendJsonl(labelsFile, row)
        return row
    }

    /** Writes a background (`exactly seconds*rate` frames, no pre/post-roll) to backgrounds/<name>.wav + backgrounds.jsonl. */
    fun saveBackground(take: RangePlan.Take, clip: ShortArray): JSONObject {
        val file = File(root, "backgrounds/${take.name}.wav")
        writeWavAtomic(file, clip)
        val row = JSONObject()
            .put("name", take.name).put("kind", take.bgKind).put("level", take.level ?: JSONObject.NULL)
            .put("seconds", take.seconds).put("file", "backgrounds/${take.name}.wav")
        appendJsonl(backgroundsFile, row)
        return row
    }

    fun saveRating(block: String, rating: Int, note: String, seconds: Double, redos: Int): JSONObject {
        val row = JSONObject().put("block", block).put("rating", rating).put("note", note)
            .put("seconds", seconds).put("redos", redos)
        appendJsonl(ratingsFile, row)
        return row
    }

    /** All label rows in order. */
    fun labelRows(): List<JSONObject> = rows(labelsFile)

    /** take_id -> the take's row: its last heard row, else its last missed one (range_layout.take_rows). */
    fun latestLabels(): Map<String, JSONObject> = takeRows(labelRows())

    /** name -> the last background row. */
    fun latestBackgrounds(): Map<String, JSONObject> = rows(backgroundsFile).associateBy { it.getString("name") }

    fun ratingRows(): List<JSONObject> = rows(ratingsFile)

    /** The redo count for the next save of [takeId]: previous rows + 1 (0 when none). */
    fun redoFor(takeId: String): Int = labelRows().count { it.getString("take_id") == takeId }

    /** Total bytes under the session root (for rec_list). */
    fun bytes(): Long = bytesCache ?: (if (root.isDirectory) root.walkBottomUp().filter { it.isFile }.sumOf { it.length() } else 0L)
        .also { bytesCache = it }

    private fun writeWavAtomic(file: File, samples: ShortArray) {
        file.parentFile?.mkdirs()
        val tmp = File(file.parentFile, file.name.removeSuffix(".wav") + ".tmp.wav")
        RandomAccessFile(tmp, "rw").use { raf ->
            raf.setLength(0)
            raf.write(Measure.wavHeader(rate, 1, samples.size * 2))
            val bb = ByteBuffer.allocate(samples.size * 2).order(ByteOrder.LITTLE_ENDIAN)
            bb.asShortBuffer().put(samples)
            raf.write(bb.array())
        }
        require(tmp.renameTo(file)) { "could not write $file" }
        bytesCache = null
    }

    private fun writeJsonAtomic(file: File, o: JSONObject) {
        val tmp = File(file.parentFile, file.name + ".tmp")
        tmp.writeText(o.toString(2) + "\n")
        require(tmp.renameTo(file)) { "could not write $file" }
        if (file == metaFile) metaCache = JSONObject(o.toString())
        bytesCache = null
    }

    private fun appendJsonl(file: File, o: JSONObject) {
        val cached = rows(file)   // read before the append, so the new row is not counted twice
        file.appendText(o.toString() + "\n")
        cached.add(o)
        bytesCache = null
    }

    private fun rows(file: File): MutableList<JSONObject> = rowCache.getOrPut(file) { readJsonl(file).toMutableList() }

    private fun readJsonl(file: File): List<JSONObject> =
        if (!file.exists()) emptyList()
        else file.readLines().filter { it.isNotBlank() }.map { JSONObject(it) }

    companion object {
        /** A take's WAV (range_layout.take_file): the plain path, or `.a<attempt>` for a missed (no_sound) attempt. */
        fun takeFile(block: String, takeId: String, attempt: Int?): String =
            if (attempt == null) "takes/$block/$takeId.wav" else "takes/$block/$takeId.a$attempt.wav"

        /** take_id -> its last heard row, else its last row (only missed attempts) — range_layout.take_rows. */
        fun takeRows(rows: List<JSONObject>): Map<String, JSONObject> {
            val out = LinkedHashMap<String, JSONObject>()
            for (r in rows) {
                val id = r.getString("take_id")
                val prev = out[id]
                if (!r.optBoolean("no_sound") || prev == null || prev.optBoolean("no_sound")) out[id] = r
            }
            return out
        }
    }
}
