package ai.vox.companion.rec

import org.json.JSONArray
import org.json.JSONObject

/**
 * The bundled range spec (extractor/prompts/range_v1.json) parsed into the recorder's plan. [build] mirrors
 * extractor/range_layout.build_plan exactly for profile `short` | `full`: the same order, the same
 * take_id `<block>-<cell_id>-r<rep>`, and the same cue / expect / cond / cond_id / rep / bg; backgrounds are their own
 * kind. The spec bytes are bundled by a Gradle copy task (asset `range/range_v1.json`); JVM tests read the extractor
 * file directly (`../../extractor/prompts/range_v1.json` from the module dir) rather than the asset.
 */
object RangePlan {
    class Take(
        val takeId: String,
        val block: String,
        val kind: String,               // "takes" | "backgrounds"
        val cue: String,
        val expect: List<String>,
        val cond: Map<String, String>,
        val condId: String?,
        val rep: Int,
        val bg: JSONObject?,            // null or {name, kind, level} (real-* cells)
        val name: String?,              // backgrounds only
        val bgKind: String?,            // the cell's acoustic kind (backgrounds only)
        val level: Any?,                // backgrounds only (Number or null)
        val seconds: Double?,           // backgrounds only
        val quiet: Boolean,
        val targetS: Double?,
        val maxS: Double?,
        val anchor: String?,
    ) {
        /** Manual takes (backgrounds, real-*): the user starts the media first, then rec_go. */
        val manual: Boolean get() = kind == "backgrounds" || block.startsWith("real-")
        /** Fixed window (no silence end, no "no sound"): a background plays, or the quiet room step. */
        val fixedWindow: Boolean get() = bg != null || quiet
    }

    class Block(val id: String, val kind: String, val intro: String, val cells: List<Take>)

    class Plan(
        val profile: String,
        val blocks: List<Block>,
        val takes: List<Take>,
        val defaults: JSONObject,
        val ratingsMin: Int,
        val ratingsMax: Int,
        val analysis: JSONObject,
    ) {
        fun takeById(id: String): Take? = takes.firstOrNull { it.takeId == id }
    }

    /** The six condition keys in canonical order (range_layout.COND_KEYS). */
    val COND_KEYS = listOf("tone", "pitch", "speed", "loud", "dist", "gap")

    /** Parses [bytes] (the spec JSON) and builds the [profile] plan. */
    fun parse(bytes: ByteArray, profile: String): Plan = parse(JSONObject(String(bytes, Charsets.UTF_8)), profile)

    fun parse(spec: JSONObject, profile: String): Plan {
        require(spec.optString("version") == "range_v1") { "expected range_v1" }
        val profiles = spec.optJSONObject("profiles")
        val chosen: JSONObject = profiles?.optJSONObject(profile)
            ?: throw IllegalArgumentException("unknown profile '$profile'; the spec has ${profiles?.keys()?.asSequence()?.toList()}")
        val chosenBlocks = chosen.getJSONArray("blocks").let { a ->
            (0 until a.length()).associate { i -> a.getJSONObject(i).getString("id") to a.getJSONObject(i) }
        }
        val blocksOut = ArrayList<Block>()
        val takesOut = ArrayList<Take>()
        val blocksArr = spec.getJSONArray("blocks")
        for (bi in 0 until blocksArr.length()) {
            val b = blocksArr.getJSONObject(bi)
            val bid = b.getString("id")
            val sel = chosenBlocks[bid] ?: continue
            val cellsArr = b.getJSONArray("cells")
            val selCells = sel.getJSONArray("cells").let { a -> (0 until a.length()).map { a.getString(it) }.toSet() }
            val selReps = if (sel.has("reps") && !sel.isNull("reps")) sel.getInt("reps") else null
            val blockTakes = ArrayList<Take>()
            for (ci in 0 until cellsArr.length()) {
                val c = cellsArr.getJSONObject(ci)
                if (c.getString("cell_id") !in selCells) continue
                val reps = selReps ?: c.getInt("reps")
                for (r in 1..reps) {
                    blockTakes.add(take(c, bid, b.getString("kind"), r))
                }
            }
            blocksOut.add(Block(bid, b.getString("kind"), b.optString("intro"), blockTakes))
            takesOut.addAll(blockTakes)
        }
        val defaults = spec.optJSONObject("defaults") ?: JSONObject()
        val ratings = spec.optJSONObject("ratings") ?: JSONObject()
        val analysis = spec.optJSONObject("analysis") ?: JSONObject()
        return Plan(profile, blocksOut, takesOut, defaults, ratings.optInt("min", 1), ratings.optInt("max", 5), analysis)
    }

    private fun take(c: JSONObject, block: String, kind: String, rep: Int): Take {
        val isBg = kind == "backgrounds"
        val expect = strList(c.optJSONArray("expect"))
        return Take(
            takeId = "$block-${c.getString("cell_id")}-r$rep",
            block = block,
            kind = kind,
            cue = c.getString("cue"),
            expect = expect,
            cond = (0 until COND_KEYS.size).associate { i -> COND_KEYS[i] to (c.optJSONObject("cond")?.optString(COND_KEYS[i]) ?: "na") },
            condId = if (c.has("cond_id") && !c.isNull("cond_id")) c.getString("cond_id") else null,
            rep = rep,
            bg = if (c.has("bg") && !c.isNull("bg")) c.getJSONObject("bg") else null,
            name = if (c.has("name") && !c.isNull("name")) c.getString("name") else null,
            bgKind = if (c.has("kind")) c.getString("kind") else null,
            level = if (c.has("level") && !c.isNull("level")) c.get("level") else null,
            seconds = if (c.has("seconds") && !c.isNull("seconds")) c.getDouble("seconds") else null,
            quiet = c.optBoolean("quiet", false),
            targetS = if (c.has("target_s") && !c.isNull("target_s")) c.getDouble("target_s") else null,
            maxS = if (c.has("max_s") && !c.isNull("max_s")) c.getDouble("max_s") else null,
            anchor = if (c.has("anchor") && !c.isNull("anchor")) c.getString("anchor") else null,
        )
    }

    private fun strList(a: JSONArray?): List<String> {
        if (a == null) return emptyList()
        return (0 until a.length()).map { a.getString(it) }
    }

    /** The parity serialization (the fixture fields) for one take: {take_id, block, cue, expect, cond_id, rep, bg, kind}. */
    fun fixtureEntry(t: Take): JSONObject = JSONObject()
        .put("take_id", t.takeId).put("block", t.block).put("cue", t.cue)
        .put("expect", JSONArray(t.expect)).put("cond_id", t.condId ?: JSONObject.NULL)
        .put("rep", t.rep).put("bg", t.bg ?: JSONObject.NULL).put("kind", t.kind)
}
