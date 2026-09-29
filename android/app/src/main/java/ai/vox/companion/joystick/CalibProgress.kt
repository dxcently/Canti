package ai.vox.companion.joystick

import org.json.JSONArray
import org.json.JSONObject

/*
 * The per-step calibration save and resume (E9 contract C). Pure JVM: the service (VoiceJoystick) gives [CalibSaves]
 * its SharedPreferences as a [CalibPrefs] and calls it from calib_start, the tick loop, calib_skip and calib_save.
 *
 * A finished step is merged into the saved profile `calib_<source>` at once, so a cancel (BackgroundGuard,
 * UiBridge.close, idle, calib_cancel), a service restart or an app kill loses only the in-flight step.
 * `calib_progress_<source>` = {done_steps, current, updated_ms}; resume starts at the first step not in done_steps, and
 * is the default while the progress is under [CalibProgress.FRESH_MS] old. calib_save removes the progress (the run is
 * complete: the next calib_start begins at the top).
 */
object CalibProgress {
    /** Resume by default while the saved progress is this recent (contract C: < 24 h). */
    const val FRESH_MS = 24 * 60 * 60 * 1000L

    /** The steps still to do, in order, after [doneSteps]. */
    fun remaining(doneSteps: Collection<String>): List<String> = JoyCalibration.STEPS.filter { it !in doneSteps }

    /** The first step not in [doneSteps] (where a resume starts), or null when every step is done. */
    fun resumeStep(doneSteps: Collection<String>): String? = remaining(doneSteps).firstOrNull()

    /** `calib_progress_<source>`: what has been done so far and where the run left off. */
    fun toJson(doneSteps: List<String>, current: String, nowMs: Long): JSONObject =
        JSONObject().put("done_steps", JSONArray(doneSteps)).put("current", current).put("updated_ms", nowMs)

    /** The saved done steps (known step names only, in step order; a damaged entry reads as none). */
    fun doneStepsOf(p: JSONObject?): List<String> {
        val a = p?.optJSONArray("done_steps") ?: return emptyList()
        val names = (0 until a.length()).mapNotNull { a.opt(it) as? String }.toSet()
        return JoyCalibration.STEPS.filter { it in names }
    }

    fun updatedMs(p: JSONObject?): Long = p?.optLong("updated_ms", 0) ?: 0

    /** Whether a saved progress is fresh enough to resume by default (< [FRESH_MS]). */
    fun fresh(p: JSONObject?, nowMs: Long): Boolean = p != null && nowMs - updatedMs(p) < FRESH_MS
}

/** Where the saves go: SharedPreferences in the service, a map in the tests. */
interface CalibPrefs {
    fun get(key: String): String?
    /** Writes every entry in ONE commit (a null value removes the key), durably: an app kill right after keeps it. */
    fun put(entries: Map<String, String?>)
}

/**
 * The saved profiles and the per-step saves of the calibration runs (one run at a time). [onError]: a stored entry
 * that does not parse (it then reads as absent).
 */
class CalibSaves(private val prefs: CalibPrefs, private val onError: (what: String, e: Exception) -> Unit = { _, _ -> }) {
    /** The finishes of the current run already saved ([JoyCalibration.finishCount]). */
    private var savedFinishes = 0
    /** The steps done before the current run began: a resumed run's earlier steps, or a subset run's others. */
    private var baseDone: Set<String> = emptySet()
    /** Whether the current run resumed a saved progress (for the log). */
    var resumed = false; private set

    fun profileKey(src: String) = "calib_$src"
    fun progressKey(src: String) = "calib_progress_$src"

    fun load(src: String): JoyProfile? = prefs.get(profileKey(src))?.let {
        try { JoyProfile.fromJson(JSONObject(it)) } catch (e: Exception) { onError("joystick profile", e); null }
    }

    fun progress(src: String): JSONObject? = prefs.get(progressKey(src))?.let {
        try { JSONObject(it) } catch (e: Exception) { onError("calibration progress", e); null }
    }

    /**
     * calib_start: a new run for [src] on its saved profile. [steps]: an explicit subset (never resumed); [resume]: null
     * = the default (a progress under 24 h old). A resume with nothing left starts a full run.
     */
    fun start(spec: JoySpec, src: String, steps: List<String>?, resume: Boolean?, nowMs: Long): JoyCalibration {
        val prog = progress(src)
        val base = load(src)
        val prevDone = CalibProgress.doneStepsOf(prog)
        val left = CalibProgress.remaining(prevDone)
        resumed = steps == null && prog != null && left.isNotEmpty() && (resume ?: CalibProgress.fresh(prog, nowMs))
        val cal = JoyCalibration(spec, src, base, if (resumed) left else steps)
        baseDone = if (resumed) prevDone.toSet()
            else JoyCalibration.STEPS.filter { it !in cal.steps && base != null && it !in base.missingSteps }.toSet()
        savedFinishes = 0
        return cal
    }

    /** The steps done so far: those done before this run and those this run finished (measured or skipped). */
    fun doneSteps(cal: JoyCalibration): List<String> = JoyCalibration.STEPS.filter { it in baseDone || it in cal.finished }

    /** After ticks and a skip: a step that finished since the last save (a redo too) is saved at once. True = saved. */
    fun check(cal: JoyCalibration, nowMs: Long): Boolean {
        if (cal.finishCount <= savedFinishes) return false
        savedFinishes = cal.finishCount
        val p = cal.draft.copy(savedAtMs = nowMs, complete = false)
        prefs.put(mapOf(profileKey(cal.source) to p.toJson().toString(),
            progressKey(cal.source) to CalibProgress.toJson(doneSteps(cal), cal.step, nowMs).toString()))
        return true
    }

    /** calib_save: the whole draft, marked complete; the progress goes (the next run starts at the top). */
    fun complete(cal: JoyCalibration, nowMs: Long): JoyProfile {
        val p = cal.draft.copy(savedAtMs = nowMs, complete = true)
        prefs.put(mapOf(profileKey(cal.source) to p.toJson().toString(), progressKey(cal.source) to null))
        return p
    }

    /** The inactive map's `resume` for [src]: `{step, done_steps}` where calib_start {resume: true} begins, or null. */
    fun resume(src: String): Map<String, Any?>? {
        val prog = progress(src) ?: return null
        val done = CalibProgress.doneStepsOf(prog)
        val step = CalibProgress.resumeStep(done) ?: return null
        return linkedMapOf("step" to step, "done_steps" to done)
    }
}
