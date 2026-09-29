package ai.vox.companion.rec

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * The dev-only in-app range library (contract L): every range session on the device — phone sessions under
 * `files/range/<name>` and pushed PC copies under `files/range_pc/<name>` — with progress, what is missing, playback
 * targets, and the bundled spec for browsing. A session is parsed with ITS OWN spec.json (range_v1 or range_v2) and its
 * rows read through the contract-T effective rows, so deletes and restores are honoured. A damaged session is listed
 * with an "error" and never crashes the list.
 *
 * Phone sessions are just another dataset: there is no "continue a PC session on the phone" here (origin pc is
 * read-only; deletes are refused and point back at the PC).
 */
class RecLibrary(private val filesDir: File, private val bundledSpec: ByteArray) {

    val bundledVersion: String get() = JSONObject(String(bundledSpec, Charsets.UTF_8)).optString("version")

    /** {sessions: [...], bundled: {version}}. Phone sessions first, then PC copies; each damaged session is an error row. */
    fun list(): Map<String, Any?> {
        val sessions = ArrayList<Map<String, Any?>>()
        for (origin in listOf(PHONE, PC)) {
            val root = sessionRoot(origin)
            if (!root.isDirectory) continue
            val dirs = root.listFiles()?.filter { it.isDirectory }?.sortedBy { it.name } ?: emptyList()
            for (d in dirs) sessions.add(summary(d, origin))
        }
        return mapOf("sessions" to sessions, "bundled" to mapOf("version" to bundledVersion))
    }

    /** The summary fields + takes / backgrounds / deletes for one session. Throws if the session is damaged. */
    fun session(name: String, origin: String): Map<String, Any?> = detail(sessionDir(name, origin), origin)

    /** The bundled plan (not a session) for browsing without recording: {version, profile, blocks:[...]}. */
    fun spec(profile: String): Map<String, Any?> {
        val p = RangePlan.parse(bundledSpec, profile)
        val blocks = p.blocks.filter { it.cells.isNotEmpty() }.map { b ->
            mapOf(
                "id" to b.id, "intro" to b.intro,
                "takes" to b.cells.map { t ->
                    mapOf(
                        "take_id" to t.takeId, "cue" to t.cue, "expect" to t.expect, "cond" to t.cond,
                        "target_s" to t.targetS, "max_s" to t.maxS, "manual" to t.manual, "quiet" to t.quiet,
                    )
                },
            )
        }
        return mapOf("version" to p.version, "profile" to p.profile, "blocks" to blocks)
    }

    /** The on-disk dir for a session: `files/range/<name>` (phone) or `files/range_pc/<name>` (pc). */
    fun sessionDir(name: String, origin: String): File {
        require(origin == PHONE || origin == PC) { "origin must be phone|pc" }
        require(SAFE_NAME.matches(name)) { "bad session name" }
        return File(sessionRoot(origin), name)
    }

    private fun sessionRoot(origin: String): File = File(filesDir, if (origin == PC) "range_pc" else "range")

    // --- summary --------------------------------------------------------------------------------------------------

    private fun summary(dir: File, origin: String): Map<String, Any?> {
        val p = try { parse(dir, origin) } catch (e: Exception) {
            return mapOf("name" to dir.name, "origin" to origin, "error" to (e.message ?: "unreadable session"))
        }
        val plan = p.plan
        val done = plan.takes.count { it.kind == "takes" && p.takeStatus(it) == "done" }
        val noSound = plan.takes.count { it.kind == "takes" && p.takeStatus(it) == "no_sound" }
        val missing = plan.takes.count { it.kind == "takes" && p.takeStatus(it) == "missing" }
        val total = plan.takes.count { it.kind == "takes" }
        val bgDone = plan.takes.count { it.kind == "backgrounds" && p.bgLatest.containsKey(it.name) }
        val bgTotal = plan.takes.count { it.kind == "backgrounds" }
        val blocks = plan.blocks.filter { it.cells.isNotEmpty() }.map { b ->
            val rated = p.ratings.lastOrNull { it.optString("block") == b.id }
            mapOf(
                "id" to b.id,
                "done" to b.cells.count { (if (it.kind == "backgrounds") p.bgLatest.containsKey(it.name) else p.takeStatus(it) == "done") },
                "total" to b.cells.size,
                "rating" to rated?.optInt("rating"),
            )
        }
        return mapOf(
            "name" to dir.name, "origin" to origin,
            "speaker" to p.meta.optString("speaker", "self"),
            "profile" to p.profile,
            "device" to p.meta.optString("device", ""),
            "mic" to p.meta.optString("mic", ""),
            "recorder" to p.meta.optString("recorder", ""),
            "spec" to p.specVersion,
            "synthetic" to p.meta.optBoolean("synthetic", false),
            "sittings" to (p.meta.optJSONArray("sittings")?.length() ?: 0),
            "done" to done, "total" to total,
            "backgrounds_done" to bgDone, "backgrounds_total" to bgTotal,
            "no_sound" to noSound, "deleted" to p.deleted,
            "blocks" to blocks,
            "missing_n" to missing,
            "resumable" to (origin == PHONE && p.specVersion == bundledVersion),
            "twin" to p.meta.optString("twin", "").takeIf { it.isNotEmpty() },
        )
    }

    // --- detail ---------------------------------------------------------------------------------------------------

    private fun detail(dir: File, origin: String): Map<String, Any?> {
        val p = parse(dir, origin)
        val plan = p.plan
        val takes = plan.takes.filter { it.kind == "takes" }.map { t ->
            val row = p.takeRows[t.takeId]
            val attempts = p.noSound.filter { it.optString("take_id") == t.takeId }.map { r ->
                mapOf("attempt" to r.optInt("attempt"), "file" to r.optString("file"), "dur_ms" to r.optDouble("dur_ms"))
            }
            mapOf(
                "take_id" to t.takeId, "block" to t.block, "cue" to t.cue, "expect" to t.expect, "cond" to t.cond,
                "target_s" to t.targetS,
                "status" to p.takeStatus(t),
                "file" to row?.optString("file")?.takeIf { it.isNotEmpty() },
                "dur_ms" to row?.optDouble("dur_ms"),
                "redo" to row?.optInt("redo"),
                "attempts" to attempts,
            )
        }
        val backgrounds = plan.takes.filter { it.kind == "backgrounds" }.map { t ->
            val r = p.bgLatest[t.name]
            mapOf(
                "name" to t.name,
                "status" to (if (r != null) "done" else "missing"),
                "file" to r?.optString("file")?.takeIf { it.isNotEmpty() },
                "seconds" to r?.optDouble("seconds"),
            )
        }
        val deletes = p.deletes.map { d ->
            mapOf(
                "del_id" to d.optString("del_id"),
                "take_id" to RecSession.rowKey(d),
                "scope" to d.optString("scope"),
                "attempt" to (if (d.has("attempt") && !d.isNull("attempt")) d.getInt("attempt") else null),
                "restorable" to (d.optString("del_id") in p.restorable),
            )
        }
        return summary(dir, origin) + mapOf("takes" to takes, "backgrounds" to backgrounds, "deletes" to deletes)
    }

    // --- parsing --------------------------------------------------------------------------------------------------

    private class Parsed(
        val meta: JSONObject,
        val profile: String,
        val specVersion: String,
        val plan: RangePlan.Plan,
        val ratings: List<JSONObject>,
        val takeRows: Map<String, JSONObject>,
        val noSound: List<JSONObject>,
        val bgLatest: Map<String, JSONObject>,
        val deleted: Int,
        val deletes: List<JSONObject>,
        val restorable: Set<String>,
    ) {
        fun takeStatus(t: RangePlan.Take): String {
            val r = takeRows[t.takeId] ?: return "missing"
            return if (RecSession.isNoSound(r)) "no_sound" else "done"
        }
    }

    private fun parse(dir: File, origin: String): Parsed {
        val meta = JSONObject(File(dir, "session.json").readText())
        val specFile = File(dir, "spec.json")
        require(specFile.exists()) { "missing spec.json" }
        val spec = JSONObject(specFile.readText())
        val specVersion = spec.optString("version")
        val profile = meta.optString("profile", "short")
        val plan = try {
            RangePlan.parse(spec, profile)
        } catch (e: Exception) {
            throw IllegalArgumentException("${e.message}")
        }
        val labels = readJsonl(File(dir, "labels.jsonl"))
        val bgs = readJsonl(File(dir, "backgrounds.jsonl"))
        val ratings = readJsonl(File(dir, "ratings.jsonl"))
        val labelsEff = RecSession.effectiveRows(labels)
        val bgsEff = RecSession.effectiveRows(bgs)
        val bgLatest = LinkedHashMap<String, JSONObject>()
        for (r in bgsEff.rows) bgLatest[r.getString("name")] = r
        val deletes = (labels + bgs).filter { it.optString("op") == "delete" }
        val restorable = (labelsEff.restorable + bgsEff.restorable).toSet()
        return Parsed(
            meta = meta, profile = profile, specVersion = specVersion, plan = plan, ratings = ratings,
            takeRows = RecSession.takeRows(labels), noSound = RecSession.noSoundRows(labels),
            bgLatest = bgLatest, deleted = labelsEff.inForce.size + bgsEff.inForce.size,
            deletes = deletes, restorable = restorable,
        )
    }

    private fun readJsonl(f: File): List<JSONObject> =
        if (!f.exists()) emptyList() else f.readLines().filter { it.isNotBlank() }.map { JSONObject(it) }

    companion object {
        const val PHONE = "phone"
        const val PC = "pc"
        private val SAFE_NAME = Regex("[A-Za-z0-9_-]+")

        /** Resolves a playback target to an absolute path and refuses any traversal outside the session folder. */
        fun resolvePlay(dir: File, file: String): File {
            require(file.isNotBlank()) { "rec_play needs {file}" }
            val base = dir.canonicalFile
            val f = File(base, file).canonicalFile
            require(f.path.startsWith(base.path + File.separator) && f.isFile) { "file escapes the session folder" }
            return f
        }

        /** The WAV's (channels, rate, dur_ms) (PCM16 mono/stereo); throws on a non-PCM16 or malformed header. */
        fun wavInfo(f: File): Triple<Int, Int, Long> {
            val b = f.readBytes()
            require(b.size >= 44 && String(b, 0, 4, Charsets.US_ASCII) == "RIFF" && String(b, 8, 4, Charsets.US_ASCII) == "WAVE") {
                "not a WAV"
            }
            val bb = ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN)
            require(bb.getShort(20).toInt() == 1) { "not PCM" }                       // audio format
            val channels = bb.getShort(22).toInt()
            val rate = bb.getInt(24).toInt()
            require(bb.getShort(34).toInt() == 16) { "not PCM16" }                    // bits per sample
            require(channels in 1..2 && rate > 0) { "not PCM16 mono/stereo" }
            val dataBytes = bb.getInt(40).toInt().toLong()
            val durMs = dataBytes * 1000 / (rate * channels * 2)
            return Triple(channels, rate, durMs)
        }
    }
}
