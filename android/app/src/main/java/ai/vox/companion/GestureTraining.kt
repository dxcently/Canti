package ai.vox.companion

import org.json.JSONArray
import org.json.JSONObject
import kotlin.math.pow
import kotlin.math.roundToInt

/*
 * Gesture training (PROTOCOL.md "Gesture training", wiki/personalization.md; user decision 2026-09-27): the user
 * records their own version of every gesture, with variations, into the enrollment store of the current mic source
 * (EnrollmentStore, class kind `gesture` named after the gesture). Separate from the voice cursor's setup, resumable,
 * one card per gesture.
 *
 * - [TrainPlan]: the cells. A contour (rise, fall, arch, dip) = hum|whistle x low|high start x slow|quick, 8 takes;
 *   flat = hum|whistle x low|high note x short|long, 8 takes; click, hiss = soft|loud x 2 takes, 4. 48 in all.
 * - [TrainJudge]: one take against its cell. It must be ONE sound and carry a fingerprint; the rest is the tolerant
 *   grade ([ShapeGrade]: start note, shape, length, hum/whistle, ...; near counts as a pass). A passing take the
 *   extractor labelled otherwise is stored with `label_mismatch` and held out of Personal until train_confirm.
 * - [GestureTrainer]: the session. A failed take stops with the reason and waits for RETRY or SKIP (and, when only
 *   the shape missed, KEEP ANYWAY, logged). A pass moves on by itself after [GestureTrainer.AUTO_ADVANCE_MS];
 *   train_goto (the header arrows) moves anywhere in the plan.
 * Pure JVM: the service is the [TrainHost].
 */

/** The training cells. A cell's [tags] are stored with its example (`meta`) for later analysis. */
object TrainPlan {
    const val VERSION = 1

    data class Cell(val gesture: String, val id: String, val tags: Map<String, String>, val prompt: String, val hint: String)

    val CONTOURS = listOf("rise", "fall", "arch", "dip", "flat")
    /** A pop counts as a click (2026-09-28): the discrete gestures are click and hiss (no pop). */
    val DISCRETE = listOf("click", "hiss")
    val GESTURES = CONTOURS + DISCRETE

    /** What each shape is, for prompts and reasons. */
    val SHAPE = mapOf(
        "rise" to "goes up", "fall" to "goes down", "arch" to "goes up then down", "dip" to "goes down then up",
        "flat" to "stays level", "click" to "a tongue click", "hiss" to "a hiss",
    )
    /** The heard shape in brackets (a reason's "heard a dip (down then up)"). */
    val SHORT_SHAPE = mapOf(
        "rise" to "up", "fall" to "down", "arch" to "up then down", "dip" to "down then up", "flat" to "level",
    )

    private fun contourCells(g: String): List<Cell> {
        val out = mutableListOf<Cell>()
        for (tone in listOf("hum", "whistle")) for (pitch in listOf("low", "high")) for (speed in if (g == "flat") listOf("short", "long") else listOf("slow", "quick")) {
            val verb = if (tone == "hum") "Hum" else "Whistle"
            val prompt = if (g == "flat") "$verb a ${speed.uppercase()} flat note, ${pitch.uppercase()}"
                else "$verb a ${speed.uppercase()} $g, starting ${pitch.uppercase()}"
            val how = when (speed) {
                "quick", "short" -> "about half a second"
                else -> "about 1.5 s"
            }
            val where = if (g == "flat") (if (pitch == "low") "a low note for you" else "a high note for you")
                else (if (pitch == "low") "start near the bottom of your range" else "start near the top of your range")
            val toneHint = if (tone == "hum") "lips closed, \"mm\"" else "a whistle"
            val hint = "${if (g.first() in "aeiou") "An" else "A"} $g ${SHAPE[g]}. ${speed.replaceFirstChar { it.uppercase() }}: $how. ${where.replaceFirstChar { it.uppercase() }}. ${toneHint.replaceFirstChar { it.uppercase() }}."
            val tags = linkedMapOf("tone" to tone, "pitch" to pitch, if (g == "flat") "length" to speed else "speed" to speed)
            out += Cell(g, "$tone-$pitch-$speed", tags, prompt, hint)
        }
        return out
    }

    private fun discreteCells(g: String): List<Cell> {
        val out = mutableListOf<Cell>()
        for (loud in listOf("soft", "loud")) for (take in 1..2) {
            val adv = if (loud == "soft") "SOFTLY" else "LOUDLY"
            val prompt = when (g) {
                "click" -> "Click your tongue $adv ($take of 2)"
                else -> "Hiss $adv, about half a second ($take of 2)"
            }
            val hint = when (g) {
                "click" -> "A tongue click, like \"tsk\" or a cluck."
                else -> "A short \"sss\" or \"shh\", under a second."
            } + if (loud == "soft") " Soft: as quiet as you would use it." else " Loud: as loud as you would use it."
            out += Cell(g, "$loud-$take", linkedMapOf("loudness" to loud, "take" to "$take"), prompt, hint)
        }
        return out
    }

    private val cells: Map<String, List<Cell>> = GESTURES.associateWith { if (it in CONTOURS) contourCells(it) else discreteCells(it) }

    fun cells(gesture: String): List<Cell> = cells[gesture] ?: throw IllegalArgumentException("gesture must be one of $GESTURES")
    fun cell(gesture: String, id: String): Cell = cells(gesture).firstOrNull { it.id == id }
        ?: throw IllegalArgumentException("'$gesture' has no cell '$id' (${cells(gesture).joinToString { it.id }})")
    val TOTAL = GESTURES.sumOf { cells(it).size }
}

/** One take as heard: every sound of the recording window. */
data class TrainHeard(val labels: List<String>, val lines: List<String>, val durMs: Long?, val features: SoundFeatures?) {
    val label get() = labels.firstOrNull()
    val line get() = lines.firstOrNull()
}

/** The judgement of one take: [reasons] empty = accepted. [checks] is the tolerant grade (ShapeGrade). */
data class TrainVerdict(val reasons: List<Pair<String, String>>, val canKeep: Boolean, val heard: Map<String, Any?>,
                        val checks: List<ShapeGrade.Check> = emptyList()) {
    val ok get() = reasons.isEmpty()
    val reason get() = reasons.joinToString(" ") { it.second }
}

object TrainJudge {
    /** A whistle's median f0 is at least this (the extractor's `whistle_min_hz`, vx_config.h). */
    const val WHISTLE_MIN_HZ = 600.0
    /** QUICK / SHORT takes last at most this; SLOW / LONG at least [SLOW_MIN_MS] (the prompts say 0.5 s and 1.5 s). */
    const val QUICK_MAX_MS = 1000L
    const val SLOW_MIN_MS = 800L

    /** Median f0 in Hz from an fp1 fingerprint (`f0_oct` = log2(f0 / 100 Hz), -3 when unpitched), or null. */
    fun f0Hz(f: SoundFeatures?): Double? {
        if (f == null || f.fpVersion != "fp1" || f.fp.isEmpty()) return null
        val oct = f.fp[0]
        return if (oct <= -2.99) null else 100.0 * 2.0.pow(oct)
    }

    /** The start note, estimated from the median f0 and the contour's median (pitch16 is relative to the start). */
    fun startHz(f: SoundFeatures?): Double? {
        val med = f0Hz(f) ?: return null
        if (!f!!.pitched) return null
        val s = f.pitch16.sorted()
        val m = (s[7] + s[8]) / 2
        return med / 2.0.pow(m / 12)
    }

    /** hum | whistle by f0 band (the line's `sounds like` when the fingerprint has no f0), or null. */
    fun tone(f: SoundFeatures?, line: String?): String? {
        f0Hz(f)?.let { return if (it >= WHISTLE_MIN_HZ) "whistle" else "hum" }
        return line?.let { SoundLine(it).soundsLike }?.takeIf { it == "hum" || it == "whistle" }
    }

    private fun a(label: String) = if (label.first() in "aeiou") "an $label" else "a $label"

    private fun heardShape(label: String) = TrainPlan.SHORT_SHAPE[label]?.let { "${a(label)} ($it)" } ?: a(label)

    private fun wanted(g: String) = if (g in TrainPlan.DISCRETE) "${a(g)} is ${TrainPlan.SHAPE[g]}"
        else "${a(g)} ${TrainPlan.SHAPE[g]}"

    private fun secs(ms: Long) = "%.1f s".format(java.util.Locale.ROOT, ms / 1000.0)

    fun judge(cell: TrainPlan.Cell, h: TrainHeard, scale: ShapeGrade.Scale? = null): TrainVerdict {
        val g = cell.gesture
        val f = h.features
        val f0 = f0Hz(f)
        val heard = linkedMapOf<String, Any?>(
            "label" to h.label, "line" to h.line, "sounds" to h.labels.size, "labels" to h.labels,
            "dur_ms" to h.durMs, "f0_hz" to f0?.roundToInt(), "start_hz" to startHz(f)?.roundToInt(),
            "tone" to tone(f, h.line), "loudness" to h.line?.let { SoundLine(it).loudness },
            "pitch16" to f?.pitch16?.toList(), "shape" to h.label?.let { TrainPlan.SHAPE[it] },
        )
        if (h.labels.isEmpty()) return TrainVerdict(listOf("nothing" to "Heard nothing."), false, heard)
        if (h.labels.size > 1) {
            val seq = h.labels.joinToString(" then ")
            return TrainVerdict(listOf("count" to "Heard ${h.labels.size} sounds ($seq): make it one unbroken sound."), false, heard)
        }
        if (f == null) return TrainVerdict(listOf("features" to "No fingerprint came with the sound, so it cannot be stored (an older Canti firmware?)."), false, heard)
        val label = h.label!!
        if (label == "unknown") return TrainVerdict(listOf("label" to "Canti did not count that as a gesture (too quiet, too short, or media playing): ${wanted(g)}."), false, heard)

        // The tolerant grade (ShapeGrade): a near miss passes; only a clear miss fails. The heard label is no longer
        // checked directly — a passing take whose label differs is stored with `label_mismatch` (confirmed later).
        val start = if (g in TrainPlan.DISCRETE) "none" else cell.tags["pitch"] ?: "none"
        val speed = cell.tags["speed"] ?: cell.tags["length"]
        val want = ShapeGrade.Want(listOf(g), start, speed, cell.tags["tone"] ?: "any")
        val heardS = ShapeGrade.Heard(h.labels, f.pitch16.toList(), f0, startHz(f), h.durMs,
            h.line?.let { SoundLine(it).loudness }, tone(f, h.line))
        val checks = ShapeGrade.grade(want, heardS, scale)
        val misses = checks.filter { it.state == "miss" }
        val reasons = mutableListOf<Pair<String, String>>()
        if (misses.isNotEmpty()) reasons += missReason(misses.first(), cell, label, f0, h.durMs)
        // Keep anyway: a take that misses ONLY the shape (the direction / label family) can still be stored as the
        // user's own version — a contour class needs a pitch track to hold it.
        val canKeep = misses.size == 1 && misses[0].id == "SHAPE" && (g !in TrainPlan.CONTOURS || f.pitched)
        return TrainVerdict(reasons, canKeep, heard, checks)
    }

    /** The "next step" sentence for the first miss, keeping the reason texts. */
    private fun missReason(miss: ShapeGrade.Check, cell: TrainPlan.Cell, label: String, f0: Double?, dur: Long?): Pair<String, String> {
        val g = cell.gesture
        return when (miss.id) {
            "SHAPE" -> if (label != g) "shape" to "Heard ${heardShape(label)}: ${wanted(g)}."
                else "shape" to "That was not ${wanted(g)}."
            "SOUND" -> {
                val want = cell.tags["tone"]
                "tone" to when {
                    // a low voice: under the extractor's f0 floor (75 Hz) a hum has no pitch at all
                    f0 == null && want == "hum" && cell.tags["pitch"] == "low" ->
                        "No clear pitch: hum it with your lips closed, a little above your very lowest note."
                    f0 == null -> "No clear pitch: ${if (want == "hum") "hum it with your lips closed" else "whistle it"}."
                    want == "whistle" -> "Heard a hum (about ${f0.roundToInt()} Hz): a whistle is ${WHISTLE_MIN_HZ.roundToInt()} Hz or higher. Whistle it."
                    else -> "Heard a whistle (about ${f0.roundToInt()} Hz): hum it with your lips closed, below ${WHISTLE_MIN_HZ.roundToInt()} Hz."
                }
            }
            "LENGTH" -> {
                val speed = cell.tags["speed"] ?: cell.tags["length"]
                val what = if (g == "flat") "flat note" else g
                "speed" to when {
                    speed == "quick" || speed == "short" -> "It took ${secs(dur ?: 0)}: a ${speed.uppercase()} $what takes about half a second (at most ${secs(QUICK_MAX_MS)})."
                    speed == "slow" || speed == "long" -> "It took ${secs(dur ?: 0)}: a ${speed.uppercase()} $what takes about 1.5 s (at least ${secs(SLOW_MIN_MS)})."
                    else -> "It took ${secs(dur ?: 0)}: keep it under 4 s."
                }
            }
            "PITCH" -> "pitch" to when (cell.tags["pitch"]) {
                "low" -> "It started too high: start LOW, near the bottom of your range."
                "high" -> "It started too low: start HIGH, near the top of your range."
                else -> "It started far from your usual note."
            }
            "LOUD" -> "loud" to "Too quiet for Canti: a little louder."
            else -> miss.id.lowercase() to miss.label
        }
    }
}

/** What the trainer needs from the service (main thread). */
interface TrainHost : Scheduler {
    /** The current sound source (`pico`, `phone`, `usb`). */
    fun source(): String
    /** Why a take cannot be recorded right now (paused, cursor mode, mic off, ...), or null. */
    fun blocker(): String?
    /** [rec] Why a training round cannot start at all (the dev test recorder is open), or null. */
    fun refuseStart(): String? = null
    /** What single action fixes [blocker] (for the training screen's "Not ready" button), or null. */
    fun blockerAction(): String? = null
    /** Sounds the mic heard but dropped since [sinceMs] (level gate, touch, the joystick's filter), as one line, or null. */
    fun dropSummary(sinceMs: Long): String? = null
    /** The current source gives live pitch ticks (the phone / USB mic). */
    fun liveTrace(): Boolean
    fun ticks(on: Boolean)
    fun profile(): String
    /** The user's scale for the current sound source and [tone] (a saved calibration profile: the voice range for
     *  `hum`, the whistle range for `whistle`), or null. */
    fun scale(tone: String = "hum"): ShapeGrade.Scale? = null
    /** The enrollment store of [source] (the live one for the current source). */
    fun store(source: String): EnrollmentStore
    /** Changes [source]'s store and persists it (IllegalArgumentException with a reason on failure). */
    fun change(source: String, what: String, change: (EnrollmentStore) -> Unit)
    /** The per-source trash of deleted takes (newest first), as a JSON array, or null when empty. */
    fun trash(source: String): JSONArray?
    /** Replaces [source]'s trash (a null or empty array removes it). */
    fun saveTrash(source: String, entries: JSONArray?)
    fun wallMs(): Long
    fun log(vararg fields: Pair<String, Any?>)
    fun push(status: Map<String, Any?>)
}

/**
 * Why a take cannot be recorded now, and the one action that fixes it (the training screen's "Not ready" button:
 * `resume` or `gesture_mode`; null = no single button does). [TrainHost.blocker] / [TrainHost.blockerAction] in the
 * service; pure for the tests.
 */
object TrainBlock {
    data class Inputs(
        val calibrating: Boolean, val paused: Boolean, val armed: Boolean, val usesMic: Boolean, val cursorMode: Boolean,
        val micState: String?, val deviceReady: Boolean,
    )

    fun of(i: Inputs): Pair<String, String?>? = when {
        // the calibration screen ends it (Stop / Back); leaving the app ends it too (VoxService's background guard)
        i.calibrating -> "Canti is calibrating." to null
        i.paused -> "Canti is paused." to "resume"
        // a phone / USB mic: the app disarmed it (resume re-arms). The Pico: the device is paused (resume arms it over
        // the link) or asleep / gone (nothing to command)
        !i.armed -> if (i.usesMic) "Canti is paused." to "resume"
            else "Canti is not listening (the device is paused or asleep)." to (if (i.deviceReady) "resume" else null)
        i.cursorMode -> "Canti is in cursor mode: switch to gesture mode to train gestures." to "gesture_mode"
        // armed and not paused, yet the mic is off (no permission, no USB mic, a refused foreground service, an error):
        // resuming would change nothing, so no button
        i.usesMic && i.micState != "listening" -> "The mic is off (${i.micState ?: "off"})." to null
        !i.usesMic && !i.deviceReady -> "The Canti device is not connected." to null
        else -> null
    }
}

/**
 * The training session and its commands (UI channel `train_*`, the debug socket's ops of the same names). States:
 * `ready` (the prompt is shown, RECORD starts), `recording` (waiting for the take, live trace), `passed` (stored; NEXT
 * records the next cell), `failed` (the reason; RETRY / SKIP / KEEP ANYWAY when only the label was wrong), `done`
 * (no cell left in this round). While a session is open, every sound goes to it (none acts on the phone).
 */
class GestureTrainer(private val host: TrainHost) {
    companion object {
        /** Wait this long after a take's first sound for a second one (a split arch comes as rise + fall). */
        const val SETTLE_MS = 900L
        /** A recording with no sound at all fails after this. */
        const val TAKE_TIMEOUT_MS = 8000L
        /** A session with no command for this long is closed (the screen went away without saying so). */
        const val IDLE_MS = 5 * 60_000L
        const val TRACE_MAX = 250            // 5 s of 20 ms ticks
        const val PUSH_MS = 100L
        const val TICK_MS = 20               // one live tick
        /** Auto-advance this long after a pass (the next undone cell), unless a command cancelled it. */
        const val AUTO_ADVANCE_MS = 1200L
        /** The per-source trash of soft-deleted takes keeps at most this many entries (the oldest drop off). */
        const val TRASH_MAX = 20
    }

    private inner class Session(val source: String, var gesture: String, var queue: List<TrainPlan.Cell>) {
        /** The user's scales (voice, whistle), read once per round. */
        val scales: Map<String, ShapeGrade.Scale?> = listOf("hum", "whistle").associateWith { host.scale(it) }
        fun scaleOf(cell: TrainPlan.Cell?) = scales[if (cell?.tags?.get("tone") == "whistle") "whistle" else "hum"]
        var index = 0
        var state = "ready"
        var verdict: TrainVerdict? = null
        var heard: TrainHeard? = null
        val labels = mutableListOf<String>(); val lines = mutableListOf<String>()
        var firstDur: Long? = null; var firstFeatures: SoundFeatures? = null
        val trace = ArrayDeque<Double?>()
        var levelDb: Double? = null
        var liveChecks: List<ShapeGrade.Check> = emptyList()
        val passed = mutableListOf<String>(); val skipped = mutableListOf<String>(); val kept = mutableListOf<String>()
        var startedAt = 0L
        var cancelTimer: (() -> Unit)? = null
        var autoAdvance: (() -> Unit)? = null
        val cell get() = queue.getOrNull(index)
    }

    private var s: Session? = null
    private var lastCmdAt = 0L
    private var idleCancel: (() -> Unit)? = null
    private var lastPush = 0L

    val active get() = s != null
    val recording get() = s?.state == "recording"

    // --- commands --------------------------------------------------------------------------------------------------

    /** One UI / socket command; answers the status map (with `error` when refused). Main thread. */
    fun command(method: String, args: Map<String, Any?>): Map<String, Any?> {
        lastCmdAt = host.now()
        // any command (other than a passive status read) cancels a pending auto-advance
        if (method != "train_status") { s?.autoAdvance?.invoke(); s?.autoAdvance = null }
        val src = (args["source"] as? String)
        var undoId: Long? = null
        val err = try {
            when (method) {
                "train_status" -> {}
                "train_start" -> start(SoundFold.label(args["gesture"] as? String ?: throw IllegalArgumentException("train_start needs {gesture}")),
                    args["cell"] as? String, src)
                "train_record" -> record()
                "train_retry" -> { need("failed"); record() }
                "train_skip" -> skip()
                "train_keep" -> keep()
                "train_next" -> next(args["record"] as? Boolean ?: true)
                "train_goto" -> goto(SoundFold.label(args["gesture"] as? String ?: throw IllegalArgumentException("train_goto needs {gesture}")),
                    args["cell"] as? String ?: throw IllegalArgumentException("train_goto needs {cell}"), src)
                "train_confirm" -> confirm(src ?: host.source(),
                    (args["id"] as? Number)?.toLong() ?: throw IllegalArgumentException("train_confirm needs {id}"),
                    args["keep"] as? Boolean ?: throw IllegalArgumentException("train_confirm needs {keep}"))
                "train_cancel" -> cancel("ui")
                // train_delete does NOT fold: {gesture: "pop"} removes a legacy pop class (never the click class)
                "train_delete" -> undoId = delete(src ?: host.source(), args["gesture"] as? String ?: throw IllegalArgumentException("train_delete needs {gesture}"),
                    args["cell"] as? String)
                "train_undelete" -> undelete(src ?: host.source(),
                    (args["id"] as? Number)?.toLong() ?: throw IllegalArgumentException("train_undelete needs {id}"))
                "train_trash_clear" -> clearTrash(src ?: host.source())
                else -> throw IllegalArgumentException("unknown training command $method")
            }
            null
        } catch (e: IllegalArgumentException) { e.message ?: e.toString() }
        armIdle()
        val st = status(src)
        val out = (if (err != null) st + mapOf("error" to err) else st)
            .let { if (undoId != null) it + mapOf("undo_id" to undoId) else it }
        host.push(out)
        return out
    }

    private fun need(vararg states: String) {
        val c = s ?: throw IllegalArgumentException("no training session: start one from a gesture card")
        require(c.state in states) { "not possible now (the take is ${c.state})" }
    }

    private fun start(gesture: String, cellId: String?, source: String?) {
        require(gesture in TrainPlan.GESTURES) { "gesture must be one of ${TrainPlan.GESTURES}" }
        host.refuseStart()?.let { throw IllegalArgumentException(it) }   // [rec]
        val cur = host.source()
        require(source == null || source == cur) { "the current sound source is ${srcName(cur)}: switch to ${srcName(source!!)} to train it" }
        s?.let { finish("restart") }
        val st = host.store(cur)
        val c = st.find(gesture)
        require(c == null || c.kind == EnrollmentStore.GESTURE) { "'$gesture' is already a ${c!!.kind} class in this store" }
        val done = c?.examples?.mapNotNull { it.cell }?.toSet() ?: emptySet()
        val queue = if (cellId != null) listOf(TrainPlan.cell(gesture, cellId)) else TrainPlan.cells(gesture).filter { it.id !in done }
        require(queue.isNotEmpty()) { "every $gesture take is recorded: use Delete / redo to record them again" }
        // Room in the class (at most MAX_EXAMPLES): a redone cell replaces its example.
        val have = c?.examples?.size ?: 0
        val adds = queue.count { it.id !in done }
        require(have + adds <= EnrollmentStore.MAX_EXAMPLES) {
            "the $gesture class already holds $have examples (${have - done.size} not from training): delete them on the card first"
        }
        s = Session(cur, gesture, queue)
        host.ticks(host.liveTrace())
        host.log("event" to "start", "source" to cur, "gesture" to gesture, "cells" to queue.size, "cell" to cellId)
    }

    private fun record() {
        val c = s ?: throw IllegalArgumentException("no training session: start one from a gesture card")
        require(c.state in listOf("ready", "failed", "passed")) { "not possible now (the take is ${c.state})" }
        requireNotNull(c.cell) { "no take left in this round" }
        c.cancelTimer?.invoke(); c.cancelTimer = null
        c.labels.clear(); c.lines.clear(); c.firstDur = null; c.firstFeatures = null; c.trace.clear(); c.levelDb = null
        c.liveChecks = emptyList(); c.verdict = null; c.heard = null
        host.blocker()?.let { why ->
            c.state = "failed"
            c.verdict = TrainVerdict(listOf("blocked" to why), false, emptyMap())
            host.log("event" to "take", "gesture" to c.gesture, "cell" to c.cell!!.id, "result" to "failed", "reason" to why)
            return
        }
        c.state = "recording"
        c.startedAt = host.now()
        c.cancelTimer = host.schedule(TAKE_TIMEOUT_MS) { timeout() }
    }

    private fun timeout() {
        val c = s ?: return
        if (c.state != "recording" || c.labels.isNotEmpty()) return
        c.cancelTimer = null
        // Sounds were heard but dropped (level gate, touch, a calibration): say that, not "heard nothing".
        val dropped = host.dropSummary(c.startedAt)
        val why = host.blocker()
        val msg = dropped ?: "Heard nothing in ${TAKE_TIMEOUT_MS / 1000} s." + (why?.let { " $it" } ?: "")
        fail(c, TrainVerdict(listOf("nothing" to msg), false, emptyMap()))
    }

    private fun skip() {
        val c = s ?: throw IllegalArgumentException("no training session: start one from a gesture card")
        require(c.state in listOf("failed", "ready")) { "not possible now (the take is ${c.state})" }
        c.cell?.let { c.skipped += it.id; host.log("event" to "skip", "gesture" to c.gesture, "cell" to it.id, "reason" to c.verdict?.reason) }
        advance(c, record = false)
    }

    private fun keep() {
        val c = s ?: throw IllegalArgumentException("no training session: start one from a gesture card")
        require(c.state == "failed") { "not possible now (the take is ${c.state})" }
        val v = c.verdict!!
        require(v.canKeep) { "only a take with the wrong shape can be kept anyway" }
        store(c, kept = true)
        c.kept += c.cell!!.id
        host.log("event" to "keep", "gesture" to c.gesture, "cell" to c.cell!!.id, "heard" to c.heard?.label, "line" to c.heard?.line,
            "reason" to v.reason, "source" to c.source)
        c.state = "passed"
    }

    private fun next(record: Boolean) {
        val c = s ?: throw IllegalArgumentException("no training session: start one from a gesture card")
        require(c.state == "passed") { "not possible now (the take is ${c.state})" }
        advance(c, record)
    }

    /** train_goto: switch the current take to that cell (in-flight take dropped, a stored take stays). With no round
     *  open (the hub's rows) it opens one on that gesture. */
    private fun goto(gesture: String, cellId: String, source: String?) {
        require(gesture in TrainPlan.GESTURES) { "gesture must be one of ${TrainPlan.GESTURES}" }
        val cell = TrainPlan.cell(gesture, cellId)
        host.blocker()?.let { why -> throw IllegalArgumentException(why) }
        val c = s ?: open(gesture, source)
        if (c.gesture != gesture) switchGesture(c, gesture)
        dropInFlight(c)
        val idx = c.queue.indexOfFirst { it.id == cellId }
        c.index = if (idx >= 0) idx else { c.queue = c.queue + cell; c.queue.size - 1 }   // a done cell: redo it
        c.state = "ready"
        host.log("event" to "goto", "gesture" to c.gesture, "cell" to cell.id, "source" to c.source)
    }

    /** A round for train_goto when none is open: [gesture]'s missing cells (maybe none: the goto adds its cell). */
    private fun open(gesture: String, source: String?): Session {
        val cur = host.source()
        require(source == null || source == cur) { "the current sound source is ${srcName(cur)}: switch to ${srcName(source!!)} to train it" }
        val c = Session(cur, gesture, emptyList())
        switchGesture(c, gesture)
        s = c
        host.ticks(host.liveTrace())
        host.log("event" to "start", "source" to cur, "gesture" to gesture, "cells" to c.queue.size, "by" to "goto")
        return c
    }

    /** train_goto crossing a gesture boundary: re-open the round for the new gesture (stored takes stay). */
    private fun switchGesture(c: Session, gesture: String) {
        val st = host.store(c.source)
        val cls = st.find(gesture)
        require(cls == null || cls.kind == EnrollmentStore.GESTURE) { "'$gesture' is already a ${cls!!.kind} class in this store" }
        val done = cls?.examples?.mapNotNull { it.cell }?.toSet() ?: emptySet()
        c.gesture = gesture
        c.queue = TrainPlan.cells(gesture).filter { it.id !in done }
        c.index = 0
        c.passed.clear(); c.skipped.clear(); c.kept.clear()
    }

    /** Drop the in-flight take (a stored take stays); the next record starts fresh. */
    private fun dropInFlight(c: Session) {
        c.cancelTimer?.invoke(); c.cancelTimer = null
        c.autoAdvance?.invoke(); c.autoAdvance = null
        c.labels.clear(); c.lines.clear(); c.firstDur = null; c.firstFeatures = null; c.trace.clear(); c.levelDb = null
        c.liveChecks = emptyList(); c.verdict = null; c.heard = null
    }

    /** train_confirm {id, keep}: keep a label-mismatched take (confirmed) or delete it (reject). Only a take stored with
     *  `label_mismatch` can be addressed: an example stored before ids has none, and must never be hit by id -1. */
    private fun confirm(src: String, id: Long, keep: Boolean) {
        require(src in EnrollmentStore.SOURCES) { "source must be one of ${EnrollmentStore.SOURCES}" }
        fun EnrollExample.isIt() = meta?.let { m -> m.optBoolean("label_mismatch") && m.optLong("id", -1) == id } == true
        require(id >= 0 && host.store(src).classes.any { cls -> cls.examples.any { it.isIt() } }) { "no stored take with id $id to confirm" }
        host.change(src, "train ${if (keep) "confirm" else "reject"} $id") { s2 ->
            for (cls in s2.classes) for (i in cls.examples.indices) if (cls.examples[i].isIt()) {
                if (keep) cls.examples[i].meta!!.put("confirmed", true) else s2.delete(cls.name, i)
                return@change
            }
        }
        host.log("event" to "confirm", "id" to id, "keep" to keep, "source" to src)
    }

    private fun advance(c: Session, record: Boolean) {
        c.cancelTimer?.invoke(); c.cancelTimer = null
        c.verdict = null; c.heard = null; c.trace.clear(); c.liveChecks = emptyList()
        // the next undone cell after this one, then one before it that the arrows jumped over; a skipped cell stays
        // skipped for this round
        val done = doneCells(host.store(c.source), c.gesture)
        val open = { i: Int -> c.queue[i].id !in done && c.queue[i].id !in c.skipped }
        c.index = ((c.index + 1 until c.queue.size) + (0 until minOf(c.index, c.queue.size))).firstOrNull(open) ?: c.queue.size
        if (c.cell == null) {
            c.state = "done"
            host.log("event" to "done", "gesture" to c.gesture, "source" to c.source, "passed" to c.passed.size,
                "kept" to c.kept.size, "skipped" to c.skipped.joinToString(" "))
        } else {
            c.state = "ready"
            if (record) record()
        }
    }

    /** Ends the session; one the screen did not end itself (idle, the app in the background) is pushed to it now. */
    fun cancel(by: String) { if (s != null) { finish(by); if (by != "ui") host.push(status(null)) } }

    private fun finish(by: String) {
        val c = s ?: return
        c.cancelTimer?.invoke()
        c.autoAdvance?.invoke(); c.autoAdvance = null
        host.log("event" to "end", "by" to by, "gesture" to c.gesture, "source" to c.source, "passed" to c.passed.size,
            "kept" to c.kept.size, "skipped" to c.skipped.size, "state" to c.state)
        s = null
        host.ticks(false)
        idleCancel?.invoke(); idleCancel = null
    }

    /** The removed example(s) of a soft delete, re-addable: each example as a SoundFeatures JSON (with the store's
     *  fp_version) so train_undelete can `st.add` them back. */
    private fun exampleJson(ver: String, e: EnrollExample): JSONObject =
        JSONObject().put("fp", JSONArray(e.fp.toList())).put("fp_version", ver)
            .put("pitch16", JSONArray(e.pitch16.toList())).also { if (e.meta != null) it.put("meta", e.meta) }

    /** The next undo id for [source]'s trash: unique in it (a re-record's example id and the wall clock never collide). */
    private fun nextTrashId(source: String): Long {
        val tr = host.trash(source)
        val max = tr?.let { a -> (0 until a.length()).maxOfOrNull { a.getJSONObject(it).optLong("id", -1L) } ?: -1L } ?: -1L
        return maxOf(host.wallMs(), max + 1)
    }

    /** Prepends an entry to [source]'s trash (newest first), capping it at [TRASH_MAX] (the oldest drop off). */
    private fun pushTrash(source: String, id: Long, gesture: String, cellId: String?, examples: JSONArray, t: Long) {
        val entry = JSONObject().put("id", id).put("gesture", gesture)
            .put("cell", cellId ?: JSONObject.NULL).put("examples", examples).put("t", t)
        val cur = host.trash(source) ?: JSONArray()
        val next = JSONArray().put(entry)
        for (i in 0 until cur.length()) if (next.length() < TRASH_MAX) next.put(cur.getJSONObject(i))
        host.saveTrash(source, next)
    }

    /** train_delete (soft): the removed example(s) move to the source's trash; the reply's `undo_id` addresses them. */
    private fun delete(source: String, gesture: String, cellId: String?): Long? {
        // a legacy gesture:pop class (a pop counts as a click, 2026-09-28) can still be deleted whole — never the click class
        require(gesture in TrainPlan.GESTURES || (gesture == "pop" && cellId == null)) { "gesture must be one of ${TrainPlan.GESTURES}" }
        require(s?.let { it.gesture == gesture && it.source == source } != true) { "the $gesture card is being recorded: stop it first" }
        if (cellId != null) TrainPlan.cell(gesture, cellId)
        val st = host.store(source)
        val c = st.find(gesture) ?: return null
        require(c.kind == EnrollmentStore.GESTURE) { "'$gesture' is a ${c.kind} class" }
        val removed = if (cellId == null) c.examples.toList() else c.examples.filter { it.cell == cellId }
        if (removed.isEmpty()) return null
        val undoId = nextTrashId(source)
        val examplesJson = JSONArray(removed.map { exampleJson(st.fpVersion ?: "fp1", it) })
        host.change(source, "train delete $gesture${cellId?.let { " $it" } ?: ""}") { s2 ->
            val cc = s2.find(gesture) ?: return@change
            if (cellId == null) s2.delete(gesture)
            else cc.examples.indexOfFirst { it.cell == cellId }.takeIf { it >= 0 }?.let { s2.delete(gesture, it) }
        }
        pushTrash(source, undoId, gesture, cellId, examplesJson, host.wallMs())
        host.log("event" to "delete", "source" to source, "gesture" to gesture, "cell" to cellId, "undo_id" to undoId)
        return undoId
    }

    /** train_undelete {id}: puts a trashed delete back, unless that cell (or class) has been recorded again since. */
    private fun undelete(source: String, id: Long) {
        require(source in EnrollmentStore.SOURCES) { "source must be one of ${EnrollmentStore.SOURCES}" }
        val tr = host.trash(source) ?: throw IllegalArgumentException("no deleted take with id $id to restore")
        val idx = (0 until tr.length()).indexOfFirst { tr.getJSONObject(it).optLong("id", -1L) == id }
        require(idx >= 0) { "no deleted take with id $id to restore" }
        val entry = tr.getJSONObject(idx)
        val gesture = entry.getString("gesture")
        val cell = entry.optString("cell").takeIf { it.isNotEmpty() }
        val st = host.store(source)
        val c = st.find(gesture)
        val recordedAgain = if (cell != null) c?.examples?.any { it.cell == cell } == true
            else c != null && c.examples.isNotEmpty()
        require(!recordedAgain) { "recorded again since" }
        val exs = entry.getJSONArray("examples")
        val feats = List(exs.length()) { SoundFeatures.parse(exs.getJSONObject(it), "trash[$it]") }
        host.change(source, "train undelete $id") { s2 -> s2.add(EnrollmentStore.GESTURE, gesture, feats) }
        val next = JSONArray()
        for (i in 0 until tr.length()) if (i != idx) next.put(tr.getJSONObject(i))
        host.saveTrash(source, if (next.length() == 0) null else next)
        host.log("event" to "undelete", "source" to source, "id" to id, "gesture" to gesture, "cell" to cell)
    }

    /** train_trash_clear: empties a source's trash. */
    private fun clearTrash(source: String) {
        require(source in EnrollmentStore.SOURCES) { "source must be one of ${EnrollmentStore.SOURCES}" }
        host.saveTrash(source, null)
        host.log("event" to "trash_clear", "source" to source)
    }

    private fun armIdle() {
        idleCancel?.invoke(); idleCancel = null
        if (s == null) return
        idleCancel = host.schedule(IDLE_MS) { if (host.now() - lastCmdAt >= IDLE_MS) cancel("idle") }
    }

    // --- sounds ----------------------------------------------------------------------------------------------------

    /**
     * A feature message while a session is open: true = taken (it must not act). Only a recording take keeps the
     * sounds; otherwise they are dropped (logged by the caller).
     */
    fun onSounds(m: FeatureMessage): Boolean {
        val c = s ?: return false
        if (m.sequence.isEmpty()) return true
        if (c.state != "recording") return true
        for (i in m.sequence.indices) {
            if (c.labels.isEmpty()) {
                c.firstDur = m.timing?.getOrNull(i)?.let { it.endMs - it.startMs }
                c.firstFeatures = m.features?.getOrNull(i)
                c.cancelTimer?.invoke()
                c.cancelTimer = host.schedule(SETTLE_MS) { settle() }
            }
            c.labels += m.sequence[i]; c.lines += m.sounds[i]
        }
        pushSoon(force = true)
        return true
    }

    private fun settle() {
        val c = s ?: return
        if (c.state != "recording") return
        c.cancelTimer = null
        val h = TrainHeard(c.labels.toList(), c.lines.toList(), c.firstDur, c.firstFeatures)
        c.heard = h
        val cell = c.cell!!
        val v = TrainJudge.judge(cell, h, c.scaleOf(cell))
        c.verdict = v
        if (!v.ok) { fail(c, v); return }
        try {
            store(c, kept = false)
        } catch (e: IllegalArgumentException) {
            fail(c, TrainVerdict(listOf("store" to "Could not store it: ${e.message}"), false, v.heard))
            return
        }
        c.state = "passed"
        host.log("event" to "take", "gesture" to c.gesture, "cell" to cell.id, "result" to "passed", "label" to h.label,
            "dur_ms" to h.durMs, "f0_hz" to v.heard["f0_hz"], "source" to c.source)
        // auto-advance: after a beat the next undone cell starts (as next(record=true)), unless a command cancels it
        c.autoAdvance = host.schedule(AUTO_ADVANCE_MS) {
            c.autoAdvance = null
            // pushed: nothing else would tell the screen (the Pico sends no live ticks)
            if (s === c && c.state == "passed") { advance(c, record = true); pushSoon(force = true) }
        }
        pushSoon(force = true)
    }

    private fun fail(c: Session, v: TrainVerdict) {
        c.state = "failed"
        c.verdict = v
        host.log("event" to "take", "gesture" to c.gesture, "cell" to c.cell?.id, "result" to "failed", "reason" to v.reason,
            "reasons" to v.reasons.joinToString(" ") { it.first }, "label" to c.heard?.label, "can_keep" to v.canKeep, "source" to c.source)
        pushSoon(force = true)
    }

    /** Stores the take into class `gesture:<name>` of the session's source (a redone cell replaces its example). */
    private fun store(c: Session, kept: Boolean) {
        val cell = c.cell!!
        val h = c.heard!!
        val f = h.features!!
        val v = c.verdict!!
        val mismatch = SoundFold.label(h.label ?: "") != cell.gesture
        // unique in the store (train_confirm addresses a take by it), and still the store time in ms
        val id = maxOf(host.wallMs(), maxId(host.store(c.source)) + 1)
        val meta = JSONObject().put("train", TrainPlan.VERSION).put("cell", cell.id).put("id", id)
        cell.tags.forEach { (k, x) -> meta.put(k, x) }
        meta.put("heard", JSONObject().put("label", h.label).put("dur_ms", h.durMs ?: JSONObject.NULL)
            .put("f0_hz", v.heard["f0_hz"] ?: JSONObject.NULL).put("start_hz", v.heard["start_hz"] ?: JSONObject.NULL)
            .put("tone", v.heard["tone"] ?: JSONObject.NULL).put("loudness", v.heard["loudness"] ?: JSONObject.NULL))
        if (kept) meta.put("kept", true)
        // a take whose extractor label differs from the prompted gesture: stored, but held until the user confirms it
        // (train_confirm); Personal matching and relabel skip it meanwhile.
        if (mismatch) { meta.put("label_mismatch", true); meta.put("confirmed", false) }
        meta.put("at_ms", id)
        host.change(c.source, "train ${cell.gesture} ${cell.id}${if (kept) " (kept anyway)" else ""}") { st ->
            st.find(cell.gesture)?.examples?.indexOfFirst { it.cell == cell.id }?.takeIf { it >= 0 }?.let { st.delete(cell.gesture, it) }
            st.add(EnrollmentStore.GESTURE, cell.gesture, listOf(f.withMeta(meta)))
        }
        c.passed += cell.id
    }

    private fun maxId(st: EnrollmentStore): Long =
        st.classes.maxOfOrNull { cls -> cls.examples.maxOfOrNull { it.meta?.optLong("id", -1) ?: -1L } ?: -1L } ?: -1L

    // --- live trace -----------------------------------------------------------------------------------------------

    /** One 20 ms tick of the phone / USB mic: its f0 (Hz, null when unvoiced) and level. Main thread. */
    fun onTick(f0Hz: Double?, levelDb: Double?) {
        val c = s ?: return
        if (c.state != "recording") return
        c.trace.addLast(f0Hz?.takeIf { it > 0 }); while (c.trace.size > TRACE_MAX) c.trace.removeFirst()
        c.levelDb = levelDb
        c.cell?.let { c.liveChecks = ShapeGrade.live(cellWant(it), c.trace.toList(), TICK_MS, c.scaleOf(it)) }
        pushSoon(force = false)
    }

    /** The wanted shape of a cell, for the tolerant grade (ShapeGrade). */
    private fun cellWant(cell: TrainPlan.Cell): ShapeGrade.Want {
        val g = cell.gesture
        return ShapeGrade.Want(listOf(g), if (g in TrainPlan.DISCRETE) "none" else cell.tags["pitch"] ?: "none",
            cell.tags["speed"] ?: cell.tags["length"], cell.tags["tone"] ?: "any")
    }

    private fun pushSoon(force: Boolean) {
        val now = host.now()
        if (!force && now - lastPush < PUSH_MS) return
        lastPush = now
        host.push(status(null))
    }

    // --- status ----------------------------------------------------------------------------------------------------

    private fun srcName(src: String) = when (src) { "phone" -> "the phone mic"; "usb" -> "the USB mic"; "pico" -> "the Canti device"; else -> src }

    /** Done / total per source (the status screen's entry). */
    fun progress(): Map<String, Map<String, Int>> = EnrollmentStore.SOURCES.associateWith { src ->
        val st = try { host.store(src) } catch (_: Exception) { null }
        mapOf("done" to (st?.let { doneCount(it) } ?: 0), "total" to TrainPlan.TOTAL)
    }

    private fun doneCells(st: EnrollmentStore, g: String): Set<String> {
        val c = st.find(g)?.takeIf { it.kind == EnrollmentStore.GESTURE } ?: return emptySet()
        val ids = TrainPlan.cells(g).map { it.id }.toSet()
        return c.examples.mapNotNull { it.cell }.filter { it in ids }.toSet()
    }

    private fun doneCount(st: EnrollmentStore) = TrainPlan.GESTURES.sumOf { doneCells(st, it).size }

    /** The global index of a cell in the flattened plan (TrainPlan order). */
    private fun globalIndex(gesture: String, cellId: String): Int {
        var base = 0
        for (g in TrainPlan.GESTURES) {
            if (g == gesture) return base + TrainPlan.cells(g).indexOfFirst { it.id == cellId }
            base += TrainPlan.cells(g).size
        }
        return -1
    }

    private fun checkMap(c: ShapeGrade.Check) = linkedMapOf<String, Any?>(
        "id" to c.id, "label" to c.label, "state" to c.state, "value" to c.value, "want" to c.want)

    private fun scaleMap(s: ShapeGrade.Scale?) = s?.let {
        linkedMapOf<String, Any?>("low_hz" to it.loHz, "home_hz" to it.homeHz, "high_hz" to it.hiHz)
    }

    /** The wanted shape of the current cell for the ShapePlot (contract B `expect`). */
    private fun expectMap(cell: TrainPlan.Cell): Map<String, Any?> {
        val g = cell.gesture
        return linkedMapOf<String, Any?>(
            "sequence" to listOf(g),
            "start" to (if (g in TrainPlan.DISCRETE) "none" else cell.tags["pitch"] ?: "none"),
            "span_st" to 4, "tol_st" to 1.5,
            "dur_s" to ShapeGrade.wantedDurS(cell.tags["speed"] ?: cell.tags["length"]),
            "gap_s" to null,
        )
    }

    /** The `train_status` map (PROTOCOL.md "Gesture training"). [source]: whose cards (default the current one). */
    fun status(source: String?): Map<String, Any?> {
        val cur = host.source()
        val src = source?.takeIf { it in EnrollmentStore.SOURCES } ?: cur
        val st = host.store(src)
        val gestures = TrainPlan.GESTURES.map { g ->
            val cls = st.find(g)?.takeIf { it.kind == EnrollmentStore.GESTURE }
            val done = doneCells(st, g)
            val cells = TrainPlan.cells(g)
            linkedMapOf<String, Any?>(
                "name" to g, "kind" to if (g in TrainPlan.CONTOURS) "contour" else "discrete",
                "done" to done.size, "total" to cells.size,
                "examples" to (cls?.examples?.size ?: 0), "extra" to (cls?.examples?.count { it.cell == null } ?: 0),
                "active" to (cls?.active ?: false),
                "kept" to (cls?.examples?.count { it.meta?.optBoolean("kept") == true } ?: 0),
                "cells" to cells.map { c -> linkedMapOf<String, Any?>("id" to c.id, "prompt" to c.prompt, "done" to (c.id in done), "tags" to c.tags) },
            )
        }
        // Takes stored with a label the user has not confirmed yet (the review screen's "sounded like X, keep as Y?").
        // The take's own pitch16 and f0 ride along so the review plots the actual take, not the canonical outline.
        val unconfirmed = mutableListOf<Map<String, Any?>>()
        for (g in TrainPlan.GESTURES) {
            val cls = st.find(g)?.takeIf { it.kind == EnrollmentStore.GESTURE } ?: continue
            for ((i, ex) in cls.examples.withIndex()) {
                val m = ex.meta ?: continue
                if (!m.optBoolean("label_mismatch") || m.optBoolean("confirmed")) continue
                val heard = m.optJSONObject("heard")
                fun opt(k: String) = heard?.takeIf { !it.isNull(k) }?.opt(k)
                unconfirmed += linkedMapOf("id" to m.optLong("id", -1), "gesture" to g,
                    "heard" to heard?.optString("label"), "pos" to i,
                    "pitch16" to ex.pitch16.toList(), "f0_hz" to opt("f0_hz"), "dur_ms" to opt("dur_ms"))
            }
        }
        val c = s
        val session = c?.let {
            val cell = it.cell
            val v = it.verdict
            // 1-based like calib_status pos (the pager shows i/n); gi is the 0-based place in the whole plan
            val gi = cell?.let { cl -> globalIndex(cl.gesture, cl.id) } ?: -1
            val pos = cell?.let { cl ->
                linkedMapOf<String, Any?>("i" to gi + 1, "n" to TrainPlan.TOTAL,
                    "gesture_i" to TrainPlan.cells(cl.gesture).indexOfFirst { x -> x.id == cl.id } + 1,
                    "gesture_n" to TrainPlan.cells(cl.gesture).size)
            }
            linkedMapOf<String, Any?>(
                "source" to it.source, "gesture" to it.gesture, "state" to it.state,
                "cell" to cell?.id, "prompt" to cell?.prompt, "hint" to cell?.hint, "tags" to cell?.tags,
                "index" to it.index, "count" to it.queue.size,
                "next_prompt" to it.queue.getOrNull(it.index + 1)?.prompt,
                "reason" to v?.takeIf { x -> !x.ok }?.reason,
                "reasons" to v?.reasons?.map { r -> r.first },
                "can_keep" to (it.state == "failed" && v?.canKeep == true),
                "heard" to (v?.heard?.takeIf { h -> h.isNotEmpty() }),
                "heard_n" to it.labels.size,
                "left_ms" to if (it.state == "recording" && it.labels.isEmpty()) maxOf(0L, TAKE_TIMEOUT_MS - (host.now() - it.startedAt)) else null,
                "live" to linkedMapOf("trace_hz" to it.trace.toList(), "level_db" to it.levelDb?.let { d -> Math.round(d * 10) / 10.0 },
                    "pitch_hz" to it.trace.lastOrNull()?.let { h -> Math.round(h * 10) / 10.0 },
                    "checks" to it.liveChecks.map(::checkMap)),
                "result" to (v?.checks?.takeIf { x -> x.isNotEmpty() }?.let { x -> linkedMapOf<String, Any?>("checks" to x.map(::checkMap)) }),
                "expect" to (cell?.let(::expectMap)),
                "pos" to pos, "can_prev" to (gi > 0), "can_next" to (gi in 0 until TrainPlan.TOTAL - 1),
                "passed" to it.passed.toList(), "skipped" to it.skipped.toList(), "kept" to it.kept.toList(),
            )
        }
        // a legacy gesture:pop class (a pop counts as a click, 2026-09-28) stays in the store for Personal matching but
        // is not part of the plan: surface it so a UI can offer deleting it
        val legacy = st.find("pop")?.takeIf { it.kind == EnrollmentStore.GESTURE }
            ?.let { listOf(mapOf("gesture" to "pop", "n" to it.examples.size)) } ?: emptyList()
        return linkedMapOf(
            "active" to (c != null), "source" to src, "current_source" to cur, "profile" to host.profile(),
            "live_trace" to host.liveTrace(), "blocked" to host.blocker(), "blocked_action" to host.blockerAction(),
            "done" to doneCount(st), "total" to TrainPlan.TOTAL,
            // the current cell's scale (the whistle range for a whistle cell), else the voice's
            "scale" to scaleMap(if (c != null) c.scaleOf(c.cell) else host.scale()), "unconfirmed" to unconfirmed,
            "gestures" to gestures, "legacy" to legacy, "session" to session, "sources" to progress(),
        )
    }
}

/** A status map as JSON (the debug socket's reply). */
internal fun trainJson(m: Map<String, Any?>): JSONObject = JSONObject(m.mapValues { (_, v) -> jsonValue(v) })

private fun jsonValue(v: Any?): Any? = when (v) {
    null -> JSONObject.NULL
    is Map<*, *> -> JSONObject(v.entries.associate { (k, x) -> k.toString() to jsonValue(x) })
    is List<*> -> JSONArray(v.map { jsonValue(it) })
    else -> v
}
