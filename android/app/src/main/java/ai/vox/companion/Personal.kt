package ai.vox.companion

import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * Phone-side personalization (wiki personalization.md): the device sends a sound fingerprint (`fp`, an opaque vector
 * of a declared version) and a 16-point pitch track with each sound. The app matches it against the user's enrolled
 * examples and rewrites the sound line before any decider sees it:
 *   custom class -> `my sound "<name>"; duration <bucket>; loudness <bucket>` (sequence label `my:<name>`)
 *   ignore class -> the extractor's line with `sounds like one of my ignore sounds`
 *   gesture class (a re-recorded rise, pop, ...) -> that gesture's normal line when the extractor labelled it
 *     otherwise (`enroll_gesture_relabel`, default on); kept and trusted when the labels agree.
 * The model does not know these lines before training data v6, so custom and ignore sounds are resolved locally
 * (see [Personal.localReason]).
 */

/**
 * Per-sound fingerprint fields of a feature message (PROTOCOL.md `features`). [meta] is an enrollment example's own
 * notes (gesture training: the cell tags and what the extractor heard, GestureTraining.kt); never part of a message.
 */
class SoundFeatures(val fp: DoubleArray, val fpVersion: String, val pitch16: DoubleArray, val meta: JSONObject? = null) {
    val pitched get() = pitch16.size == PITCH_POINTS

    fun toJson(): JSONObject = JSONObject().put("fp", JSONArray(fp.toList())).put("fp_version", fpVersion)
        .put("pitch16", JSONArray(pitch16.toList())).also { if (meta != null) it.put("meta", meta) }

    fun withMeta(m: JSONObject?) = SoundFeatures(fp, fpVersion, pitch16, m)

    companion object {
        const val PITCH_POINTS = 16
        const val MAX_FP = 256
        /** An example's `meta` (enrollment only), as JSON text. */
        const val MAX_META_CHARS = 2048

        /** Validates one `features` entry; throws IllegalArgumentException with a readable reason. */
        fun parse(o: JSONObject, where: String): SoundFeatures {
            val a = o.optJSONArray("fp") ?: throw IllegalArgumentException("$where.fp missing or not an array")
            require(a.length() in 1..MAX_FP) { "$where.fp must have 1-$MAX_FP values, got ${a.length()}" }
            val fp = numbers(a, "$where.fp")
            require(o.has("fp_version") && !o.isNull("fp_version") && o.get("fp_version") is String) { "$where.fp_version missing" }
            val ver = o.getString("fp_version")
            require(ver.isNotBlank() && ver.length <= 32) { "$where.fp_version must be 1-32 characters" }
            val p = if (o.has("pitch16") && !o.isNull("pitch16")) o.optJSONArray("pitch16")
                ?: throw IllegalArgumentException("$where.pitch16 is not an array") else null
            val pitch = if (p == null) DoubleArray(0) else {
                require(p.length() == 0 || p.length() == PITCH_POINTS) { "$where.pitch16 must have 0 or $PITCH_POINTS values, got ${p.length()}" }
                numbers(p, "$where.pitch16")
            }
            val meta = if (o.has("meta") && !o.isNull("meta")) (o.optJSONObject("meta")
                ?: throw IllegalArgumentException("$where.meta is not an object")) else null
            require(meta == null || meta.toString().length <= MAX_META_CHARS) { "$where.meta is over $MAX_META_CHARS characters" }
            return SoundFeatures(fp, ver, pitch, meta)
        }

        private fun numbers(a: JSONArray, where: String) = DoubleArray(a.length()) { i ->
            val v = a.get(i)
            require(v is Number) { "$where[$i] is not a number" }
            v.toDouble().also { require(it.isFinite()) { "$where[$i] is not finite" } }
        }
    }
}

class EnrollExample(val fp: DoubleArray, val pitch16: DoubleArray, val meta: JSONObject? = null) {
    val pitched get() = pitch16.size == SoundFeatures.PITCH_POINTS
    /** The gesture-training cell this example was recorded for (`meta.cell`), or null. */
    val cell: String? get() = meta?.optString("cell")?.takeIf { it.isNotEmpty() }
    /** A training take whose extractor label differed and the user has not confirmed yet (train_confirm): held back. */
    val unconfirmed get() = meta?.optBoolean("label_mismatch") == true && !meta.optBoolean("confirmed")
}

class EnrollClass(val kind: String, val name: String, val examples: MutableList<EnrollExample> = mutableListOf()) {
    /** Only classes with at least MIN_EXAMPLES take part in matching. */
    val active get() = confirmed.size >= EnrollmentStore.MIN_EXAMPLES
    /** The examples that take part in matching (unconfirmed takes are held back until the user confirms them). */
    val confirmed get() = examples.filter { !it.unconfirmed }
    /** Re-recorded contour gestures are also matched on the pitch track (banded DTW). */
    val contour get() = kind == EnrollmentStore.GESTURE && name in Vocab.CONTOURS
}

/**
 * The enrolled classes of one profile on one mic source ([source]: `pico`, `phone`, `usb`; null = the old
 * profile-only store). All examples share one fp version and length: the first example fixes them, and they are
 * released again when the store becomes empty. Persisted as JSON (files/enroll/<profile>@<source>.json; before
 * 2026-09-27 files/enroll/<profile>.json, migrated by [load] as the store of the source current at that moment).
 */
class EnrollmentStore(val profile: String, val source: String? = null) {
    var fpVersion: String? = null; private set
    var dim: Int? = null; private set
    val classes = mutableListOf<EnrollClass>()

    fun find(name: String) = classes.firstOrNull { it.name == name }

    /** Adds examples (creating the class if needed). All-or-nothing: nothing changes if any example is rejected. */
    fun add(kind: String, rawName: String, examples: List<SoundFeatures>): EnrollClass {
        val name = rawName.trim().lowercase()
        require(kind in KINDS) { "kind must be one of $KINDS" }
        require(NAME_RE.matches(name)) { "name must match ${NAME_RE.pattern}" }
        if (kind == GESTURE) require(name in Vocab.CONTOURS || name in Vocab.DISCRETE) { "a gesture class must be named after a gesture (${Vocab.CONTOURS.keys + Vocab.DISCRETE.keys})" }
        require(examples.isNotEmpty()) { "no examples" }
        val existing = find(name)
        if (existing != null) require(existing.kind == kind) { "'$name' is already a ${existing.kind} class" }
        val have = existing?.examples?.size ?: 0
        require(have + examples.size <= MAX_EXAMPLES) { "a class holds at most $MAX_EXAMPLES examples ('$name' has $have, adding ${examples.size})" }
        val ver = fpVersion ?: examples[0].fpVersion
        val len = dim ?: examples[0].fp.size
        examples.forEachIndexed { i, e ->
            require(e.fpVersion == ver) { "example $i: fp_version '${e.fpVersion}' differs from the store's '$ver'" }
            require(e.fp.size == len) { "example $i: fp has ${e.fp.size} values, the store has $len" }
            if (kind == GESTURE && name in Vocab.CONTOURS) require(e.pitched) { "example $i: a contour gesture needs a 16-point pitch16" }
        }
        fpVersion = ver; dim = len
        val c = existing ?: EnrollClass(kind, name).also { classes += it }
        examples.forEach { c.examples += EnrollExample(it.fp, it.pitch16, it.meta) }
        return c
    }

    /** Deletes a class, or one example of it (index); returns false if there was nothing to delete. */
    fun delete(name: String, index: Int? = null): Boolean {
        val c = find(name.trim().lowercase()) ?: return false
        if (index == null) classes.remove(c) else {
            if (index !in c.examples.indices) return false
            c.examples.removeAt(index)
            if (c.examples.isEmpty()) classes.remove(c)
        }
        releaseIfEmpty()
        return true
    }

    fun clear() { classes.clear(); releaseIfEmpty() }

    private fun releaseIfEmpty() { if (classes.isEmpty()) { fpVersion = null; dim = null } }

    fun toJson(): JSONObject = JSONObject().put("profile", profile).also { if (source != null) it.put("source", source) }
        .put("fp_version", fpVersion ?: JSONObject.NULL).put("dim", dim ?: JSONObject.NULL)
        .put("classes", JSONArray(classes.map { c ->
            JSONObject().put("kind", c.kind).put("name", c.name).put("examples", JSONArray(c.examples.map { e ->
                JSONObject().put("fp", JSONArray(e.fp.toList())).put("pitch16", JSONArray(e.pitch16.toList()))
                    .also { if (e.meta != null) it.put("meta", e.meta) }
            }))
        }))

    companion object {
        const val CUSTOM = "custom"; const val IGNORE = "ignore"; const val GESTURE = "gesture"
        val KINDS = listOf(CUSTOM, IGNORE, GESTURE)
        const val MIN_EXAMPLES = 3
        const val MAX_EXAMPLES = 10
        /** Class names end up inside `my sound "<name>"` and `my:<name>`: no quotes, semicolons or colons. */
        val NAME_RE = Regex("[a-z0-9][a-z0-9 -]{0,23}")
        val PROFILE_RE = Regex("[a-z0-9_-]{1,32}")
        /** The mic sources a store belongs to (MicSettings.source). */
        val SOURCES = listOf("pico", "phone", "usb")

        /** [source] overrides the file's own (a migrated profile-only store has none). */
        fun fromJson(o: JSONObject, source: String? = o.optString("source").takeIf { it.isNotEmpty() }): EnrollmentStore {
            val s = EnrollmentStore(o.getString("profile"), source)
            val arr = o.getJSONArray("classes")
            for (i in 0 until arr.length()) {
                val c = arr.getJSONObject(i)
                val ex = c.getJSONArray("examples")
                val feats = List(ex.length()) { j ->
                    val e = ex.getJSONObject(j)
                    SoundFeatures.parse(e.put("fp_version", o.getString("fp_version")), "classes[$i].examples[$j]")
                }
                s.add(c.getString("kind"), c.getString("name"), feats)
            }
            return s
        }

        /** files/enroll/<profile>@<source>.json; with no source the old profile-only file. */
        fun file(dir: File, profile: String, source: String? = null) =
            File(File(dir, "enroll"), if (source == null) "$profile.json" else "$profile@$source.json")

        /**
         * The store of [profile] on [source]. When that file does not exist yet but the old profile-only one does, the
         * old one becomes this source's store (renamed, so it happens once; [onMigrate] is told) and every other
         * source starts empty.
         */
        fun load(dir: File, profile: String, source: String? = null, onMigrate: (from: File, to: File) -> Unit = { _, _ -> }): EnrollmentStore {
            val f = file(dir, profile, source)
            if (source != null && !f.exists()) {
                val old = file(dir, profile)
                if (old.exists()) {
                    require(old.renameTo(f)) { "could not migrate $old to $f" }
                    onMigrate(old, f)
                }
            }
            return if (f.exists()) fromJson(JSONObject(f.readText()), source) else EnrollmentStore(profile, source)
        }

        fun save(dir: File, s: EnrollmentStore) {
            val f = file(dir, s.profile, s.source)
            f.parentFile?.mkdirs()
            val tmp = File(f.parentFile, f.name + ".tmp")
            tmp.writeText(s.toJson().toString())
            require(tmp.renameTo(f)) { "could not write $f" }
        }

        /** The per-source trash of soft-deleted takes: files/enroll/<profile>@<source>.trash.json. */
        fun trashFile(dir: File, profile: String, source: String) = File(File(dir, "enroll"), "$profile@$source.trash.json")

        /** The trash entries (newest first), or null when absent / empty / damaged. */
        fun loadTrash(dir: File, profile: String, source: String): JSONArray? {
            val f = trashFile(dir, profile, source)
            if (!f.exists()) return null
            return try { JSONObject(f.readText()).getJSONArray("entries") } catch (e: Exception) { null }
        }

        /** Persists the trash (a null or empty [entries] removes the file). */
        fun saveTrash(dir: File, profile: String, source: String, entries: JSONArray?) {
            val f = trashFile(dir, profile, source)
            f.parentFile?.mkdirs()
            if (entries == null || entries.length() == 0) { f.delete(); return }
            val tmp = File(f.parentFile, f.name + ".tmp")
            tmp.writeText(JSONObject().put("entries", entries).toString())
            require(tmp.renameTo(f)) { "could not write $f" }
        }
    }
}

/** One match attempt, as logged (`match` event). */
data class MatchResult(
    val result: String,              // custom | ignore | gesture | none | skipped
    val cls: EnrollClass? = null,    // the accepted class (null unless result is a kind)
    val nearest: String? = null,     // the nearest class, accepted or not
    val distance: Double? = null,    // standardised Euclidean distance to its nearest example
    val threshold: Double? = null,   // that class's reject threshold
    val dtw: Double? = null,         // contour classes: banded DTW distance of the pitch tracks
    val dtwThreshold: Double? = null,
    val reason: String = "",
)

/**
 * Per-feature std floors, keyed by fp_version. The matcher standardises by the std of the enrolled examples; a feature
 * that is nearly constant across all of them would get a std equal to its noise, and that noise would weigh as much
 * as a separating feature. With a floor the matcher divides by max(std, floor).
 *
 * The table is data, not code: assets/fp_floors.json (built into the APK), overridden per version by
 * files/fp_floors.json (the `fp_floors` control op). Format: {"<fp_version>": {"floor": [d numbers >= 0],
 * "provisional": bool, "source": "...", "names": [...]?}}. A version without an entry, or whose floor length differs
 * from the enrolled vectors, gets no floor (logged).
 */
class FpFloors(val entries: Map<String, Entry>) {
    class Entry(val floor: DoubleArray, val provisional: Boolean, val source: String) {
        fun toJson(): JSONObject = JSONObject().put("floor", JSONArray(floor.toList())).put("provisional", provisional).put("source", source)
    }

    operator fun get(version: String?) = version?.let { entries[it] }

    /** This table with other's entries replacing ours version by version. */
    fun overriddenBy(other: FpFloors) = FpFloors(entries + other.entries)

    fun toJson(): JSONObject = JSONObject().also { o -> entries.forEach { (k, v) -> o.put(k, v.toJson()) } }

    companion object {
        val EMPTY = FpFloors(emptyMap())

        /** Validates the whole table; throws IllegalArgumentException with a readable reason. */
        fun parse(o: JSONObject): FpFloors {
            val out = LinkedHashMap<String, Entry>()
            for (ver in o.keys()) {
                require(ver.isNotBlank() && ver.length <= 32) { "fp_version key '$ver' must be 1-32 characters" }
                val e = o.optJSONObject(ver) ?: throw IllegalArgumentException("$ver must be an object")
                val a = e.optJSONArray("floor") ?: throw IllegalArgumentException("$ver.floor missing or not an array")
                require(a.length() in 1..SoundFeatures.MAX_FP) { "$ver.floor must have 1-${SoundFeatures.MAX_FP} values" }
                val floor = DoubleArray(a.length()) { i ->
                    val v = a.get(i)
                    require(v is Number && v.toDouble().isFinite() && v.toDouble() >= 0) { "$ver.floor[$i] must be a finite number >= 0" }
                    v.toDouble()
                }
                val names = e.optJSONArray("names")
                require(names == null || names.length() == floor.size) { "$ver.names has ${names?.length()} entries, floor ${floor.size}" }
                // Anything not explicitly marked final is provisional.
                out[ver] = Entry(floor, e.optBoolean("provisional", true), e.optString("source", ""))
            }
            return FpFloors(out)
        }
    }
}

/**
 * Nearest neighbour with a per-class reject threshold. Features are standardised by the per-feature mean and std of
 * all examples in the store, the std raised to the fp_version's floor ([FpFloors]). A class's threshold =
 * (its leave-one-out within-class distance) x rejectMult, for every class size: the largest distance from one of its
 * examples to the nearest of the others.
 */
class Matcher(val store: EnrollmentStore, val rejectMult: Double, val floors: FpFloors = FpFloors.EMPTY) {
    val mean: DoubleArray
    val std: DoubleArray
    /** The floor entry in use, or null (no entry for the store's version, or a length mismatch: see [floorStatus]). */
    val floor: FpFloors.Entry?
    /** For the logs: `provisional`, `final`, `none` (no entry for the version), `mismatch` (length), `empty` (no store). */
    val floorStatus: String
    private class Prepared(val c: EnrollClass, val z: List<DoubleArray>, val fpThreshold: Double, val dtwThreshold: Double?,
                           val confirmed: List<EnrollExample>)
    private val prepared: List<Prepared>

    init {
        val all = store.classes.flatMap { it.confirmed }.map { it.fp }
        val e = floors[store.fpVersion]
        floor = e?.takeIf { it.floor.size == store.dim }
        floorStatus = when {
            store.fpVersion == null -> "empty"
            e == null -> "none"
            floor == null -> "mismatch"
            floor.provisional -> "provisional"
            else -> "final"
        }
        val st = Personal.standardizer(all, floor?.floor)
        mean = st.first; std = st.second
        prepared = store.classes.filter { it.active }.map { c ->
            val confirmed = c.confirmed
            val z = confirmed.map { Personal.standardize(it.fp, mean, std) }
            val fpBase = Personal.withinClass(z, Personal::euclid)
            val dtwBase = if (c.contour) Personal.withinClass(confirmed.map { it.pitch16 }) { a, b -> Personal.dtw(a, b) } else null
            Prepared(c, z, fpBase * rejectMult, dtwBase?.let { it * rejectMult }, confirmed)
        }
    }

    /** The thresholds per active class (for enroll_list). */
    fun thresholds(): Map<String, Pair<Double, Double?>> = prepared.associate { it.c.name to (it.fpThreshold to it.dtwThreshold) }

    fun match(f: SoundFeatures): MatchResult {
        if (prepared.isEmpty()) return MatchResult("skipped", reason = "no class with ${EnrollmentStore.MIN_EXAMPLES}+ examples")
        if (f.fpVersion != store.fpVersion) return MatchResult("skipped", reason = "fp_version '${f.fpVersion}' != enrolled '${store.fpVersion}'")
        if (f.fp.size != store.dim) return MatchResult("skipped", reason = "fp has ${f.fp.size} values, enrolled ${store.dim}")
        val q = Personal.standardize(f.fp, mean, std)
        // A contour class can only match a pitched sound (it is also compared on the pitch track).
        val candidates = prepared.filter { !it.c.contour || f.pitched }
        if (candidates.isEmpty()) return MatchResult("none", reason = "only contour classes are enrolled and the sound has no pitch track")
        var best: Prepared? = null; var bestD = Double.POSITIVE_INFINITY
        for (p in candidates) for (z in p.z) { val d = Personal.euclid(q, z); if (d < bestD) { bestD = d; best = p } }
        val p = best!!
        if (bestD > p.fpThreshold) return MatchResult("none", nearest = p.c.name, distance = bestD, threshold = p.fpThreshold,
            reason = "fp distance above the threshold")
        if (p.c.contour) {
            val dtw = p.confirmed.minOf { Personal.dtw(f.pitch16, it.pitch16) }
            if (dtw > p.dtwThreshold!!) return MatchResult("none", nearest = p.c.name, distance = bestD, threshold = p.fpThreshold,
                dtw = dtw, dtwThreshold = p.dtwThreshold, reason = "pitch track DTW above the threshold")
            return MatchResult(p.c.kind, p.c, p.c.name, bestD, p.fpThreshold, dtw, p.dtwThreshold, "matched")
        }
        return MatchResult(p.c.kind, p.c, p.c.name, bestD, p.fpThreshold, reason = "matched")
    }
}

object Personal {
    const val MY = "my:"
    const val IGNORE_SOUNDS_LIKE = "one of my ignore sounds"
    const val DTW_BAND = 3

    fun isCustomLabel(label: String) = label.startsWith(MY) && EnrollmentStore.NAME_RE.matches(label.removePrefix(MY))

    // --- maths ----------------------------------------------------------------------------------------------------

    /**
     * Per-feature mean and (population) std, the std raised to [floor] (same length, or null for none). A feature
     * still (near) constant after that gets std 1 so it neither divides by 0 nor counts.
     */
    fun standardizer(xs: List<DoubleArray>, floor: DoubleArray? = null): Pair<DoubleArray, DoubleArray> {
        if (xs.isEmpty()) return DoubleArray(0) to DoubleArray(0)
        val d = xs[0].size
        require(floor == null || floor.size == d) { "floor has ${floor?.size} values, the vectors $d" }
        val mean = DoubleArray(d) { j -> xs.sumOf { it[j] } / xs.size }
        val std = DoubleArray(d) { j ->
            val s = maxOf(kotlin.math.sqrt(xs.sumOf { (it[j] - mean[j]) * (it[j] - mean[j]) } / xs.size), floor?.get(j) ?: 0.0)
            if (s < 1e-9) 1.0 else s
        }
        return mean to std
    }

    fun standardize(x: DoubleArray, mean: DoubleArray, std: DoubleArray) = DoubleArray(x.size) { (x[it] - mean[it]) / std[it] }

    fun euclid(a: DoubleArray, b: DoubleArray): Double {
        var s = 0.0
        for (i in a.indices) { val d = a[i] - b[i]; s += d * d }
        return kotlin.math.sqrt(s)
    }

    /** Banded DTW (Sakoe-Chiba, |i - j| <= band), cost |a_i - b_j| summed along the path. */
    fun dtw(a: DoubleArray, b: DoubleArray, band: Int = DTW_BAND): Double {
        val n = a.size; val m = b.size
        require(n > 0 && m > 0) { "empty track" }
        val w = maxOf(band, kotlin.math.abs(n - m))
        val inf = Double.POSITIVE_INFINITY
        val d = Array(n + 1) { DoubleArray(m + 1) { inf } }
        d[0][0] = 0.0
        for (i in 1..n) for (j in maxOf(1, i - w)..minOf(m, i + w)) {
            d[i][j] = kotlin.math.abs(a[i - 1] - b[j - 1]) + minOf(d[i - 1][j], d[i][j - 1], d[i - 1][j - 1])
        }
        return d[n][m]
    }

    /**
     * The within-class distance the reject threshold is scaled from, for every class size: leave-one-out, i.e. the
     * largest over the examples of the distance to the nearest other example. (It asks "how far can a genuine new
     * example be from the nearest enrolled one", which is what matching measures. The pairwise maximum grows with the
     * class's spread and with its size, so a class with more examples would accept ever farther sounds.)
     */
    fun <T> withinClass(xs: List<T>, dist: (T, T) -> Double): Double {
        require(xs.size >= 2) { "need 2+ examples" }
        return xs.indices.maxOf { i -> xs.indices.filter { it != i }.minOf { j -> dist(xs[i], xs[j]) } }
    }

    // --- line rewrite ----------------------------------------------------------------------------------------------

    /**
     * `my sound "<name>"; duration <bucket>; loudness <bucket>`, keeping the extractor's buckets. A pop/click line
     * has no duration field ("instant sound"): it gets the shortest duration bucket. Null if the line has no
     * loudness or duration to keep (then the line is left alone).
     */
    fun customLine(name: String, line: String): String? {
        val l = SoundLine(line)
        val dur = l.duration?.takeIf { it in Vocab.DURATION }
            ?: (if (line.split("; ").contains("instant sound")) Vocab.DURATION[0] else null) ?: return null
        val loud = l.loudness?.takeIf { it in Vocab.LOUDNESS } ?: return null
        return "my sound \"$name\"; duration $dur; loudness $loud"
    }

    /** The extractor's line with its `sounds like` value replaced (appended if it had none). */
    fun ignoreLine(line: String): String {
        val parts = line.split("; ").toMutableList()
        val i = parts.indexOfFirst { it.startsWith("sounds like ") }
        if (i >= 0) parts[i] = "sounds like $IGNORE_SOUNDS_LIKE" else parts += "sounds like $IGNORE_SOUNDS_LIKE"
        return parts.joinToString("; ")
    }

    /**
     * [relabelFrom]: the extractor's label when a trained gesture class relabelled the sound; [trusted]: a gesture
     * class matched and agreed with the extractor's label (the line is kept).
     * [skipped]: "gated" when the sound was gated (FeatureMessage.gated) and so left as it was.
     */
    data class Rewritten(val sound: String, val label: String, val relabelFrom: String? = null, val trusted: Boolean = false, val skipped: String? = null)

    /**
     * What the sound becomes after a match: custom and ignore as above; a gesture match whose class differs from the
     * extractor's label becomes that gesture's normal line (when [gestureRelabel], the `enroll_gesture_relabel`
     * setting); a gesture match that agrees keeps the line and is trusted; none/skipped are unchanged.
     * A [gated] sound (a phone-mic gate made it `unknown` on purpose: FeatureMessage.gated) is never rewritten: a trained
     * pop / click / custom class must not undo the media gate or the media-hiss rule.
     */
    fun rewrite(m: MatchResult, line: String, label: String, gestureRelabel: Boolean = true, pitch16: DoubleArray? = null, gated: String? = null): Rewritten =
        if (gated != null) Rewritten(line, label, skipped = "gated") else when (m.result) {
            EnrollmentStore.CUSTOM -> customLine(m.cls!!.name, line)?.let { Rewritten(it, MY + m.cls.name) } ?: Rewritten(line, label)
            EnrollmentStore.IGNORE -> Rewritten(ignoreLine(line), label)
            EnrollmentStore.GESTURE -> {
                val g = SoundFold.label(m.cls!!.name)   // an old enrolled `gesture:pop` class that matches is "click", trusted
                when {
                    g == label -> Rewritten(line, label, trusted = true)
                    !gestureRelabel -> Rewritten(line, label)
                    else -> Rewritten(gestureLine(g, line, pitch16), g, relabelFrom = label)
                }
            }
            else -> Rewritten(line, label)
        }

    /**
     * The extractor's line for gesture [g], keeping what the original [line] measured (duration, tone, loudness,
     * sounds like; a contour's pitch change, else the bucket of [pitch16]'s range). The formats are the extractor's:
     *   `hum that <shape>; pitch change <bucket>; duration <bucket>; tone <t>; loudness <l>; sounds like <s>`
     *   `a short lip pop` / `a tongue click` + `; instant sound; loudness <l>; sounds like <s>`
     *   `a hiss; duration <bucket>; loudness <l>; sounds like <s>`
     * A flat note's pitch change is always the small bucket (that is what "stays level" says).
     */
    fun gestureLine(g: String, line: String, pitch16: DoubleArray? = null): String {
        val l = SoundLine(line)
        val loud = l.loudness?.takeIf { it in Vocab.LOUDNESS } ?: Vocab.LOUDNESS[1]
        val like = l.soundsLike
        val dur = l.duration?.takeIf { it in Vocab.DURATION } ?: Vocab.DURATION[0]
        Vocab.CONTOURS[g]?.let { shape ->
            val change = when {
                g == "flat" -> Vocab.EXCURSION[0]
                l.pitchChange in Vocab.EXCURSION -> l.pitchChange!!
                pitch16 != null && pitch16.isNotEmpty() -> {
                    val range = pitch16.max() - pitch16.min()
                    Vocab.EXCURSION[if (range < 2) 0 else if (range <= 4) 1 else 2]
                }
                else -> Vocab.EXCURSION[1]
            }
            val tone = l.tone?.takeIf { it in Vocab.CLARITY } ?: Vocab.CLARITY[2]
            return "hum that $shape; pitch change $change; duration $dur; tone $tone; loudness $loud; sounds like ${like ?: "hum"}"
        }
        val desc = Vocab.DISCRETE.getValue(g)
        val s = like ?: "mouth sound"
        return if (g == "hiss") "$desc; duration $dur; loudness $loud; sounds like $s"
            else "$desc; instant sound; loudness $loud; sounds like $s"
    }

    // --- deciding -----------------------------------------------------------------------------------------------------

    /**
     * Why this input must be decided locally (the model does not know these lines before training data v6), or null.
     * An ignore sound is always none. A custom sound goes to the model only when a plain-language rule
     * (kind "rule") is bound to exactly that sequence; a fixed rule or no rule at all is resolved by the rule table
     * (unbound = none).
     */
    fun localReason(input: DecisionInput): String? {
        val s = input.scene
        if (s.heard.any { SoundLine(it).soundsLike == IGNORE_SOUNDS_LIKE }) return "ignore-sound"
        if (s.sequence.none { it.startsWith(MY) }) return null
        val p = input.profile
        val b = if (s.mode == "cursor") p.cursorBindings().lastOrNull { it.phrase == s.sequence }
            else p.appBindings(s.app).lastOrNull { it.phrase == s.sequence } ?: p.globalBindings().lastOrNull { it.phrase == s.sequence }
        return if (b?.kind == "rule") null else "custom-sound"
    }
}
