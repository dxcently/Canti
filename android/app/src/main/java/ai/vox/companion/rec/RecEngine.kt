package ai.vox.companion.rec

import ai.vox.companion.JsonMaps
import ai.vox.companion.Scheduler
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import kotlin.math.log10
import kotlin.math.sqrt

/**
 * The recorder's take state machine (contract §5), driven by the ops (rec_start … rec_clear) and a scheduler tick that
 * reads the shared ring. All timing runs through the injected [scheduler] (elapsedRealtime) and [wallClock] (wall ms),
 * so the whole machine is JVM-tested without Android.
 *
 * States: idle / ready / countdown / recording / saved / no_sound / rate / done / error. A non-manual take goes ready
 * -> countdown (3 s when cond.dist is table or across, else straight to GO) by itself READY_MS after rec_next; manual
 * takes (backgrounds, real-*) wait for rec_go. Pre-roll: at GO the ring must hold pre_roll_s before GO, else the
 * machine waits (state stays ready/countdown). A take ends on the detector's silence / max length / fixed / no sound;
 * saved holds SAVED_HOLD_MS then auto-next unless the next take is manual, in another block, or the block needs a
 * rating (state "rate"). A "no sound" take is saved and kept (its own `.a<redo>` WAV, RecSession) and waits in state
 * no_sound for Try again (rec_next {take_id}) or Skip. The session closes on rec_close, UiBridge.close ("ui closed"),
 * 10 min idle; a capture stop / restart / gap aborts only the in-flight take (state error, session stays open) —
 * never on the app background. Session names follow range_layout.default_session_name: `range-<yyyyMMdd-HHmmss>`
 * for "me", `range-<speaker>-<yyyyMMdd-HHmmss>` for another speaker (then `-2`, `-3`... if taken).
 */
class RecEngine(
    private val scheduler: Scheduler,
    private val wallClock: () -> Long,
    private val ring: RingBuffer,
    private val heard: HeardLog,
    private val specBytes: ByteArray,
    private val env: Env,
    private val push: (Map<String, Any?>) -> Unit,
) {
    interface Env {
        val rate: Int
        val source: String            // phone | usb | pico
        val micName: String           // "phone built-in mic" / "usb: <device>"
        val capturing: Boolean
        val listening: Boolean        // the mic capture is listening
        val mode: String              // gesture | cursor | listening
        val calibrating: Boolean
        val training: Boolean
        val measuring: Boolean
        val freeBytes: Long
        val scale: JSONObject?        // {low_hz, home_hz, high_hz} from the saved calibration, or null
        val appForeground: String
        val filesDir: File
        /** [rec] Turn the recorder's 20 ms pitch ticks on/off, with the pitch ceiling [f0MaxHz] (hum 1100, whistle 2600). */
        fun ticks(on: Boolean, f0MaxHz: Double) {}
    }

    companion object {
        const val READY_MS = 1500L
        const val SAVED_HOLD_MS = 1500L
        const val COUNTDOWN_MS = 3000L
        const val IDLE_CLOSE_MS = 10L * 60_000L
        const val MIN_FREE_BYTES = 200L * 1024 * 1024
        const val TICK_MS = 50L
        const val LEVEL_BARS = 40
        /** [rec] The live pitch trace's tick width and the f0 ceiling per tone (joystick_v1.json calib_v2). */
        const val LIVE_TICK_MS = 20L
        const val WHISTLE_F0_MAX_HZ = 2600.0
        const val HUM_F0_MAX_HZ = 1100.0
        private val SAFE_NAME = Regex("[A-Za-z0-9_-]+")
        private val QR_ID = Regex("[0-9]+")
    }

    private var plan: RangePlan.Plan? = null
    private var session: RecSession? = null
    private var name: String? = null
    private var speaker = "self"
    private var profile = "short"
    private var preFrames = 0
    private var sRate = 0          // the open session's rate (the capture must keep running at it)
    private val blockStart = HashMap<String, Long>()   // when each block was first readied this sitting (rec_rate seconds)

    var state = "idle"; private set
    private var reason: String? = null
    private var error: String? = null

    private var current: RangePlan.Take? = null
    private var run: TakeRun? = null
    private var lastSavedTake: RangePlan.Take? = null
    private var lastSavedRow: JSONObject? = null
    private var lastGoFrame = 0L
    private var lastEndFrame = 0L
    private var lastReason: String? = null
    private var lastF0Hz: Double? = null
    private var lastLive: List<Double?>? = null          // the last take's live pitch trace (saved / no_sound)
    private val liveTrace = ArrayList<Double?>()          // f0 Hz per 20 ms tick since GO, null when unvoiced
    private var liveCap = 0                              // (max_s + 1) s of ticks

    private var lastCommandAt = 0L
    private var idleCloseCancel: (() -> Unit)? = null
    private var autoNextCancel: (() -> Unit)? = null
    private var countdownCancel: (() -> Unit)? = null
    private var tickCancel: (() -> Unit)? = null
    private var countdownStart = 0L
    private var recStarted = 0L
    private var skipped: Set<String> = emptySet()

    /** A recorder session is open (uiStatus.recording; also the §3 sound drop). */
    val recording: Boolean get() = session != null

    /** The open session's name, or null. */
    val openName: String? get() = name

    // --- a take in flight ------------------------------------------------------------------------------------------

    /** One take from GO: [preRoll] is the ring's `[GO - pre_roll, GO)` (empty for a background, which has none). */
    private inner class TakeRun(val take: RangePlan.Take, val goFrame: Long, val genAtGo: Int, val preRoll: ShortArray) {
        val detector: TakeDetector = TakeDetector.forTake(sRate, take, plan!!.analysis)
        var buf = ShortArray(8192)
        var bufLen = 0
        var lastRead = goFrame
        var fedLen = 0
        var detectorDone = false
        val levelBars = ArrayList<Double>()
        var peakDb = -200.0
        val redo: Int = session!!.redoFor(take.takeId)

        init { if (take.kind != "backgrounds") detector.setFloor(preRoll) }

        fun append(samples: ShortArray, n: Int) {
            if (bufLen + n > buf.size) buf = buf.copyOf(maxOf(buf.size * 2, bufLen + n))
            System.arraycopy(samples, 0, buf, bufLen, n)
            bufLen += n
        }

        fun clip(endFrame: Long): ShortArray {
            val n = endFrame.toInt()
            return if (take.kind == "backgrounds") buf.copyOf(n) else preRoll + buf.copyOf(n)
        }
    }

    // --- commands -------------------------------------------------------------------------------------------------

    fun command(method: String, args: Map<String, Any?>): Map<String, Any?> {
        touch()
        return when (method) {
            "rec_start" -> start(args)
            "rec_open" -> open(args)
            "rec_status" -> status()
            "rec_next" -> next(args["take_id"] as? String)
            "rec_go" -> go()
            "rec_abort" -> abort()
            "rec_skip" -> skip()
            "rec_redo_last" -> redoLast()
            "rec_rate" -> rate(args)
            "rec_close" -> close("op")
            "rec_clear" -> clear(args)
            "rec_delete" -> delete(args)
            "rec_restore" -> restore(args)
            "rec_trash_clear" -> trashClear(args)
            else -> mapOf("error" to "unknown recorder op '$method'")
        }
    }

    private fun start(args: Map<String, Any?>): Map<String, Any?> {
        refuseStart()?.let { return mapOf("error" to it, "active" to recording) }
        val who = args["who"] as? String ?: "me"
        val spk = if (who == "me") "self" else args["speaker"] as? String ?: ""
        if (who != "me" && (spk == "self" || !spk.matches(Regex("[A-Za-z0-9_-]{1,24}"))))
            return mapOf("error" to "speaker must be a nickname matching [A-Za-z0-9_-]{1,24}, not \"self\"")
        val prof = args["profile"] as? String ?: "short"
        if (prof != "short" && prof != "full") return mapOf("error" to "profile must be short|full")
        plan = RangePlan.parse(specBytes, prof)
        sRate = env.rate
        preFrames = Math.round(plan!!.analysis.getDouble("pre_roll_s") * sRate).toInt().coerceAtLeast(0)
        speaker = spk; profile = prof
        name = uniqueName(sessionBase(spk, wallClock()))
        val s = RecSession(File(env.filesDir, "range/$name"), env.rate, env.micName, preFrames)
        val sc = env.scale
        s.create(specBytes, prof, spk, mapOf(
            "bottom_hz" to (sc?.opt("low_hz") as? Number)?.toDouble(),
            "home_hz" to (sc?.opt("home_hz") as? Number)?.toDouble(),
            "top_hz" to (sc?.opt("high_hz") as? Number)?.toDouble()))
        session = s
        skipped = emptySet(); blockStart.clear()
        lastSavedTake = null; lastSavedRow = null; lastReason = null; lastF0Hz = null; lastLive = null
        state = "idle"; error = null; reason = null
        armIdleClose()
        log("open", mapOf("name" to name, "speaker" to spk, "profile" to prof))
        pushNow()
        return status()
    }

    private fun open(args: Map<String, Any?>): Map<String, Any?> {
        val n = args["name"] as? String ?: return mapOf("error" to "rec_open needs {name}")
        if (!n.matches(SAFE_NAME)) return mapOf("error" to "bad session name")
        if (session != null) return mapOf("error" to "a session is already open", "active" to true)
        refuseStart()?.let { return mapOf("error" to it, "active" to false) }
        val metaFile = File(env.filesDir, "range/$n/session.json")
        if (!metaFile.exists()) return mapOf("error" to "no such session: $n")
        val meta = JSONObject(metaFile.readText())
        val p = RangePlan.parse(specBytes, meta.optString("profile", "short"))
        // A session bound to a different spec version is refused (no sitting appended, no file written); the
        // byte-for-byte compare in RecSession.open still guards the same version.
        val sessionVersion = meta.optString("spec")
        if (sessionVersion.isNotEmpty() && sessionVersion != p.version)
            return mapOf("error" to "This session was recorded with $sessionVersion; the app records ${p.version}. Start a new session.")
        val pre = Math.round(p.analysis.getDouble("pre_roll_s") * env.rate).toInt().coerceAtLeast(0)
        val s = RecSession(File(env.filesDir, "range/$n"), env.rate, env.micName, pre)
        try { s.open(specBytes, env.rate, env.micName) }
        catch (e: IllegalArgumentException) { return mapOf("error" to e.message) }
        session = s; name = n; plan = p; preFrames = pre; sRate = env.rate
        speaker = meta.optString("speaker", "self"); profile = p.profile
        skipped = s.skipped(s.sitting()); blockStart.clear()
        lastSavedTake = null; lastSavedRow = null; lastReason = null; lastF0Hz = null; lastLive = null
        state = "idle"; error = null; reason = null
        armIdleClose()
        log("open", mapOf("name" to n))
        pushNow()
        return status()
    }

    private fun refuseStart(): String? {
        val src = env.source
        if (src != "phone" && src != "usb") return "the recorder records the running phone/usb capture only (source: $src)"
        if (!env.capturing || !env.listening) return "not listening"
        if (env.mode != "gesture") return "Switch Canti to gesture mode first"
        if (env.calibrating) return "a calibration is open"
        if (env.training) return "a training round is open"
        if (env.measuring) return "a measurement is open"
        if (env.freeBytes < MIN_FREE_BYTES) return "not enough free space"
        return null
    }

    private fun next(takeId: String?): Map<String, Any?> {
        val s = session ?: return inactive()
        val p = plan ?: return inactive()
        abortTake()
        val take = if (takeId != null) p.takeById(takeId) ?: return mapOf("error" to "unknown take_id '$takeId'", "active" to true)
            else p.takes.firstOrNull { t -> !settled(s, t) }
        if (take == null) { state = if (allDone()) "done" else "idle"; pushNow(); return status() }
        state = "ready"; reason = null; error = null
        current = take
        blockStart.putIfAbsent(take.block, scheduler.now())
        goAtReady()
        log("take", mapOf("take_id" to take.takeId, "event" to "ready"))
        pushNow()
        return status()
    }

    /** Recorded: a take with a label row (a missed attempt counts: Try again is explicit), a background with its row. */
    private fun recorded(t: RangePlan.Take, latest: Map<String, JSONObject>, bgs: Map<String, JSONObject>): Boolean =
        if (t.kind == "backgrounds") t.name in bgs else t.takeId in latest

    /** Recorded or skipped in this sitting (skips are kept by take_id for backgrounds too). */
    private fun settled(s: RecSession, t: RangePlan.Take): Boolean =
        t.takeId in skipped || recorded(t, s.latestLabels(), s.latestBackgrounds())

    private fun goAtReady() {
        val take = current ?: return
        if (!take.manual) autoNextCancel = scheduler.schedule(READY_MS) { if (state == "ready") go() }
    }

    private fun go(): Map<String, Any?> {
        if (state != "ready" && state != "countdown") return mapOf("error" to "not ready", "active" to recording)
        val take = current ?: return mapOf("error" to "no take", "active" to recording)
        if (state == "ready" && (take.cond["dist"] == "table" || take.cond["dist"] == "across")) {
            state = "countdown"; countdownStart = scheduler.now()
            countdownCancel = scheduler.schedule(COUNTDOWN_MS) { if (state == "countdown") beginGo() }
            pushNow()
            return status()
        }
        return beginGo()
    }

    private fun beginGo(): Map<String, Any?> {
        val take = current ?: return mapOf("error" to "no take", "active" to recording)
        countdownCancel = null
        val ringRate = ring.sampleRate
        if (ringRate != 0 && ringRate != sRate) return takeError("the capture runs at $ringRate Hz, the session at $sRate Hz")
        val gen = ring.generation
        val go = ring.end
        val pre = if (take.kind == "backgrounds") ShortArray(0) else ring.copy(go - preFrames, go)
        if (ringRate == 0 || pre == null) {
            // not a full pre-roll yet (the capture just started or restarted): GO waits, the state stays ready/countdown
            countdownCancel = scheduler.schedule(TICK_MS) { if (state == "ready" || state == "countdown") beginGo() }
            return status()
        }
        state = "recording"; recStarted = scheduler.now()
        run = TakeRun(take, go, gen, pre)
        // [rec] live pitch: hum and whistle takes get ticks on (f0 ceiling per tone); clicks/hisses/backgrounds don't.
        val tone = take.cond["tone"]
        if (tone == "hum" || tone == "whistle") {
            liveTrace.clear()
            liveCap = (((take.maxS ?: 0.0) + 1.0) * 1000.0 / LIVE_TICK_MS).toInt().coerceAtLeast(1)
            env.ticks(true, if (tone == "whistle") WHISTLE_F0_MAX_HZ else HUM_F0_MAX_HZ)
        }
        tickCancel = scheduler.schedule(TICK_MS) { tick() }
        log("take", mapOf("take_id" to take.takeId, "event" to "go"))
        pushNow()
        return status()
    }

    /** Reads the ring since the last read, feeds the detector, and finalises when the end (with post-roll) is held. */
    private fun tick() {
        val r = run ?: return
        tickCancel = null
        // a restart (new generation), a rate change, or frames the ring no longer holds (a gap or a stalled main
        // thread) would splice two streams into one clip: abort the take instead
        if (ring.generation != r.genAtGo || ring.sampleRate != sRate) { takeError("capture changed"); return }
        val end = ring.end
        if (end > r.lastRead) {
            val chunk = ring.copy(r.lastRead, end) ?: run { takeError("capture gap"); return }
            r.append(chunk, chunk.size); feedLevel(r, chunk)
            r.lastRead = end
        }
        val newN = r.bufLen - r.fedLen
        if (newN > 0) { if (r.detector.feed(r.buf, r.fedLen, newN)) r.detectorDone = true; r.fedLen = r.bufLen }
        if (r.detectorDone && r.bufLen >= r.detector.endFrame) { finalise(r); return }
        tickCancel = scheduler.schedule(TICK_MS) { tick() }
    }

    /** The in-flight take is dropped (not saved); state error with [why]; the session stays open. */
    private fun takeError(why: String): Map<String, Any?> {
        abortTake(why)
        state = "error"; error = why
        pushNow()
        return status()
    }

    private fun finalise(r: TakeRun) {
        tickCancel?.invoke(); tickCancel = null
        val take = r.take
        val endFrame = r.detector.endFrame
        val clip = r.clip(endFrame)
        val fromMs = r.goFrame * 1000 / sRate - 200
        val toMs = (r.goFrame + endFrame) * 1000 / sRate
        val appHeard = heard.window(r.genAtGo, fromMs, toMs).map { it.label }
        val row = try {
            if (take.kind == "backgrounds") session!!.saveBackground(take, clip)
            else session!!.saveTake(take, clip, r.goFrame, r.redo, appHeard, r.detector.noSound)
        } catch (e: Exception) { run = null; takeError("could not save the take: ${e.message}"); return }
        lastSavedTake = take; lastSavedRow = row; lastReason = r.detector.reason
        lastGoFrame = r.goFrame; lastEndFrame = endFrame
        lastF0Hz = if (take.block == "range") medianF0(heard.window(r.genAtGo, fromMs, toMs)) else null
        lastLive = if (take.cond["tone"] == "hum" || take.cond["tone"] == "whistle") liveTrace.toList() else null
        ticksOff()
        run = null
        state = if (r.detector.noSound) "no_sound" else "saved"
        log("take", mapOf("take_id" to take.takeId, "event" to "saved", "reason" to r.detector.reason,
            "no_sound" to r.detector.noSound, "redo" to r.redo))
        autoNextCancel = scheduler.schedule(SAVED_HOLD_MS) { if (state == "saved") autoNext() }
        pushNow()
    }

    /** After the saved hold: the next unrecorded take of the same block, unless it is manual or the block needs a rating. */
    private fun autoNext() {
        if (state != "saved") return
        val take = current ?: return
        val s = session ?: return
        val p = plan!!
        val next = p.takes.drop(p.takes.indexOf(take) + 1).firstOrNull { !settled(s, it) }
        when {
            needsRating(take.block) -> { state = "rate"; pushNow() }
            next != null && !next.manual && next.block == take.block -> next(next.takeId)
            else -> { state = if (allDone()) "done" else "idle"; pushNow() }
        }
    }

    private fun abort(): Map<String, Any?> {
        if (session == null) return inactive()
        abortTake()
        state = "idle"
        pushNow()
        return status()
    }

    private fun skip(): Map<String, Any?> {
        val s = session ?: return inactive()
        val take = current ?: return mapOf("error" to "no take", "active" to true)
        abortTake()
        s.skip(take.takeId)
        skipped = skipped + take.takeId
        log("skip", mapOf("take_id" to take.takeId))
        if (needsRating(take.block)) { state = "rate"; pushNow(); return status() }
        return next(null)
    }

    private fun redoLast(): Map<String, Any?> {
        val t = lastSavedTake ?: return mapOf("error" to "no saved take this sitting", "active" to recording)
        return next(t.takeId)
    }

    private fun rate(args: Map<String, Any?>): Map<String, Any?> {
        val s = session ?: return inactive()
        val p = plan!!
        val block = args["block"] as? String ?: return mapOf("error" to "rec_rate needs {block}")
        if (p.blocks.none { it.id == block }) return mapOf("error" to "block '$block' is not in this profile")
        val rating = (args["rating"] as? Number)?.toInt() ?: return mapOf("error" to "rec_rate needs {rating: 1..5}")
        if (rating !in p.ratingsMin..p.ratingsMax) return mapOf("error" to "rating must be ${p.ratingsMin}..${p.ratingsMax}")
        val note = args["note"] as? String ?: ""
        // seconds: since the block was first readied this sitting; redos: its re-recorded takes this sitting
        val seconds = blockStart[block]?.let { (scheduler.now() - it) / 1000.0 } ?: 0.0
        val sitting = s.sitting()
        val redos = s.labelRows().count { it.optString("block") == block && it.optInt("sitting") == sitting && it.optInt("redo") > 0 }
        s.saveRating(block, rating, note, seconds, redos)
        log("rate", mapOf("block" to block, "rating" to rating))
        state = if (allDone()) "done" else "idle"
        pushNow()
        return status()
    }

    fun close(reason: String): Map<String, Any?> {
        val s = session ?: return mapOf("ok" to false, "error" to "no session")
        abortTake()
        s.closeSitting()
        log("close", mapOf("reason" to reason))
        session = null; name = null; plan = null; current = null; sRate = 0
        run = null; lastSavedTake = null; lastSavedRow = null; blockStart.clear()
        state = "idle"; error = null; this.reason = null
        cancelAll()
        pushNow()
        return mapOf("ok" to true, "active" to false)
    }

    /** rec_clear {sessions?: [names], quickrec?: [ids] | "all"}: deletes exactly those (names/ids checked, never a path). */
    private fun clear(args: Map<String, Any?>): Map<String, Any?> {
        if (session != null) return mapOf("error" to "close the open session first")
        val sessions = (args["sessions"] as? List<*>)?.map { it.toString() } ?: emptyList()
        val qrRoot = File(env.filesDir, "quickrec")
        val quick = when (val q = args["quickrec"]) {
            null -> emptyList()
            "all" -> qrRoot.listFiles()?.filter { it.isDirectory }?.map { it.name } ?: emptyList()
            is List<*> -> q.map { it.toString() }
            else -> return mapOf("error" to "quickrec must be a list of ids or \"all\"")
        }
        if (sessions.any { !it.matches(SAFE_NAME) } || quick.any { !it.matches(QR_ID) }) return mapOf("error" to "bad session name or quickrec id")
        val gone = sessions.filter { n -> File(env.filesDir, "range/$n").let { it.isDirectory && it.deleteRecursively() } }
        val qGone = quick.filter { id -> File(qrRoot, id).let { it.isDirectory && it.deleteRecursively() } }
        log("clear", mapOf("sessions" to gone.size, "quickrec" to qGone.size))
        return mapOf("ok" to true, "deleted" to mapOf("sessions" to gone, "quickrec" to qGone))
    }

    // --- delete / restore / purge (contract T) -----------------------------------------------------------------------

    /** The session dir + its own plan (its spec.json, so a v1 session parses as v1) for a named session. */
    private fun sessionPlan(name: String): Pair<File, RangePlan.Plan>? {
        val dir = File(env.filesDir, "range/$name")
        val metaFile = File(dir, "session.json")
        if (!metaFile.exists()) return null
        val meta = JSONObject(metaFile.readText())
        val specFile = File(dir, "spec.json")
        val spec = if (specFile.exists()) specFile.readBytes() else specBytes
        return try { dir to RangePlan.parse(spec, meta.optString("profile", "short")) } catch (e: Exception) { null }
    }

    private fun targetName(args: Map<String, Any?>): String? =
        args["name"] as? String ?: session?.name

    private fun delete(args: Map<String, Any?>): Map<String, Any?> {
        val n = targetName(args) ?: return mapOf("ok" to false, "error" to "no session open; pass {name}")
        val takeId = args["take_id"] as? String ?: return mapOf("ok" to false, "error" to "rec_delete needs {take_id}")
        val scope = args["scope"] as? String ?: return mapOf("ok" to false, "error" to "rec_delete needs {scope}")
        val attempt = (args["attempt"] as? Number)?.toInt()
        val (dir, plan) = sessionPlan(n) ?: return mapOf("ok" to false, "error" to "no such session: $n")
        // a delete of the take currently recording/countdown is refused
        if (n == session?.name && (state == "recording" || state == "countdown") && current?.takeId == takeId)
            return mapOf("ok" to false, "error" to "that take is recording; abort it first")
        val t = plan.takeById(takeId)
        val bgName = if (t == null) plan.takes.firstOrNull { it.kind == "backgrounds" && it.name == takeId }?.name else null
        if (t == null && bgName == null) return mapOf("ok" to false, "error" to "unknown take_id '$takeId'")
        val s = RecSession(dir, env.rate, env.micName, 0)
        val delId = try {
            when {
                t != null && t.kind == "backgrounds" -> { if (scope != "take") return mapOf("ok" to false, "error" to "backgrounds delete uses scope \"take\""); s.deleteBackground(t.name!!) }
                bgName != null -> { if (scope != "take") return mapOf("ok" to false, "error" to "backgrounds delete uses scope \"take\""); s.deleteBackground(bgName) }
                else -> { if (scope != "take" && scope != "attempt") return mapOf("ok" to false, "error" to "bad delete scope"); s.delete(takeId, scope, attempt) }
            }
        } catch (e: IllegalArgumentException) { return mapOf("ok" to false, "error" to e.message) }
        log("delete", mapOf("take_id" to takeId, "scope" to scope, "attempt" to (attempt ?: JSONObject.NULL), "del_id" to delId))
        if (n == session?.name) {
            // a delete of the take just saved: `next` points at it again (its effective row is gone) and no auto-advance
            if (lastSavedTake?.takeId == takeId || lastSavedTake?.name == takeId) {
                lastSavedTake = null; lastSavedRow = null; lastReason = null; lastF0Hz = null; lastLive = null
                autoNextCancel?.invoke(); autoNextCancel = null
                if (state == "saved") state = "idle"
            }
            pushNow()
        }
        return (if (n == session?.name) status() else linkedMapOf()) + linkedMapOf("ok" to true, "del_id" to delId)
    }

    private fun restore(args: Map<String, Any?>): Map<String, Any?> {
        val n = targetName(args) ?: return mapOf("ok" to false, "error" to "no session open; pass {name}")
        val delId = args["del_id"] as? String ?: return mapOf("ok" to false, "error" to "rec_restore needs {del_id}")
        val (dir, _) = sessionPlan(n) ?: return mapOf("ok" to false, "error" to "no such session: $n")
        val s = RecSession(dir, env.rate, env.micName, 0)
        val key = try { s.restore(delId) } catch (e: IllegalArgumentException) { return mapOf("ok" to false, "error" to e.message) }
        log("restore", mapOf("del_id" to delId, "take_id" to key))
        if (n == session?.name) pushNow()
        return (if (n == session?.name) status() else linkedMapOf()) + linkedMapOf("ok" to true, "del_id" to delId)
    }

    private fun trashClear(args: Map<String, Any?>): Map<String, Any?> {
        val n = targetName(args) ?: return mapOf("ok" to false, "error" to "no session open; pass {name}")
        val delIds = (args["del_ids"] as? List<*>)?.map { it.toString() }
        val (dir, _) = sessionPlan(n) ?: return mapOf("ok" to false, "error" to "no such session: $n")
        val s = RecSession(dir, env.rate, env.micName, 0)
        val ids = s.purge(delIds)
        log("purge", mapOf("del_ids" to ids, "take_id" to null))
        if (n == session?.name) pushNow()
        return (if (n == session?.name) status() else linkedMapOf()) + linkedMapOf("ok" to true, "del_ids" to ids)
    }

    // --- capture events -------------------------------------------------------------------------------------------

    /** A capture stop / restart during a take aborts only that take; the session stays open (state error). An older
     *  capture's late state (a restart's "stopped" after the new "listening") is ignored. */
    fun onCaptureState(state: String, gen: Int) {
        val r = run ?: return
        if (gen > r.genAtGo || (gen == r.genAtGo && state != "listening")) takeError("capture $state")
    }

    fun onUiClosed() { if (session != null) close("ui closed") }

    private fun armIdleClose() {
        lastCommandAt = scheduler.now()
        scheduleIdleCheck(IDLE_CLOSE_MS)
    }

    /** Closes the session after IDLE_CLOSE_MS with no command; a command in between moves the check (re-armed). */
    private fun scheduleIdleCheck(delayMs: Long) {
        idleCloseCancel?.invoke()
        idleCloseCancel = scheduler.schedule(delayMs) {
            idleCloseCancel = null
            val idle = scheduler.now() - lastCommandAt
            if (session == null) return@schedule
            if (idle >= IDLE_CLOSE_MS) close("idle") else scheduleIdleCheck(IDLE_CLOSE_MS - idle)
        }
    }

    private fun touch() { lastCommandAt = scheduler.now() }

    // --- status ---------------------------------------------------------------------------------------------------

    fun inactive() = mapOf<String, Any?>("enabled" to DevRec.enabled, "active" to false)

    /** [withPlan]: the ordered take list `plan: [{take_id, block}]` of the open profile (fixed for the session); left
     *  out of the 10 Hz level pushes only, so a UI keeps the last one it got (every reply and state push carries it). */
    fun status(withPlan: Boolean = true): Map<String, Any?> {
        val s = session ?: return inactive()
        val p = plan ?: return inactive()
        val latest = s.latestLabels()
        val bgs = s.latestBackgrounds()
        val ratings = s.ratingRows()
        val total = p.takes.count { it.kind == "takes" }
        val done = p.takes.count { it.kind == "takes" && recorded(it, latest, bgs) }
        val bgTotal = p.takes.count { it.kind == "backgrounds" }
        val bgDone = p.takes.count { it.kind == "backgrounds" && recorded(it, latest, bgs) }
        val blocks = p.blocks.map { b ->
            // a block's rating: its last row (range_suite reads every row; the hub shows the latest)
            mapOf("id" to b.id, "title" to b.intro, "intro" to b.intro,
                "done" to b.cells.count { recorded(it, latest, bgs) }, "total" to b.cells.size,
                "rating" to ratings.lastOrNull { it.optString("block") == b.id }?.optInt("rating"),
                "skipped" to b.cells.count { it.takeId in skipped })
        }
        val next = p.takes.firstOrNull { t -> !(t.takeId in skipped || recorded(t, latest, bgs)) }
        val take = current
        val out = linkedMapOf<String, Any?>(
            "enabled" to DevRec.enabled, "active" to true, "name" to name, "speaker" to speaker, "profile" to profile,
            "mic" to env.micName, "rate" to sRate, "state" to state, "error" to error, "reason" to reason,
            "done" to done, "total" to total, "skipped" to skipped.size, "bytes" to s.bytes(),
            "backgrounds_done" to bgDone, "backgrounds_total" to bgTotal,
            "rated_blocks" to ratings.map { it.optString("block") }.distinct(),
            "blocks" to blocks, "next" to next?.let { mapOf("take_id" to it.takeId, "cue" to it.cue) },
            "defaults" to mapOf("distances_cm" to JsonMaps.of(p.defaults.optJSONObject("distances_cm") ?: JSONObject()),
                "speed_s" to JsonMaps.of(p.defaults.optJSONObject("speed_s") ?: JSONObject()),
                "gap_s" to JsonMaps.of(p.defaults.optJSONObject("gap_s") ?: JSONObject())),
            "scale" to env.scale?.let { mapOf("low_hz" to it.opt("low_hz"), "home_hz" to it.opt("home_hz"),
                "high_hz" to it.opt("high_hz"), "from" to "calibration") },
        )
        if (withPlan) out["plan"] = p.takes.map { mapOf("take_id" to it.takeId, "block" to it.block) }
        if (take != null) out["take"] = takeMap(take)
        out["countdown_s"] = if (state == "countdown") ((COUNTDOWN_MS - (scheduler.now() - countdownStart)) / 1000).coerceAtLeast(0) else null
        out["rec_s"] = if (state == "recording" && recStarted > 0) (scheduler.now() - recStarted) / 1000.0 else null
        out["level"] = levelMap()
        out["heard"] = heardMap()
        out["last"] = lastMap()
        out["live"] = liveMap()
        return out
    }

    /** The live pitch trace: while recording it is the take's own trace; saved/no_sound keeps the last take's. */
    private fun liveMap(): Map<String, Any?>? {
        val trace = when (state) {
            "recording" -> liveTrace.toList()
            "saved", "no_sound" -> lastLive
            else -> null
        } ?: return null
        return mapOf("trace_hz" to trace, "tick_ms" to LIVE_TICK_MS)
    }

    private fun takeMap(t: RangePlan.Take): Map<String, Any?> {
        val p = plan!!
        val idx = p.takes.indexOf(t)
        val b = p.blocks.first { it.id == t.block }
        val bii = b.cells.indexOf(t)
        return mapOf(
            "take_id" to t.takeId, "block" to t.block, "block_title" to b.intro, "i" to idx + 1, "n" to p.takes.size,
            "block_i" to bii + 1, "block_n" to b.cells.size, "cue" to t.cue, "expect" to t.expect,
            "cond" to t.cond, "bg" to t.bg?.let(JsonMaps::of), "kind" to t.kind, "quiet" to t.quiet, "manual" to t.manual,
            "target_s" to t.targetS, "max_s" to t.maxS, "seconds" to t.seconds, "redo" to session!!.redoFor(t.takeId),
        )
    }

    private fun levelMap(): Map<String, Any?> {
        val r = run ?: return mapOf("bars_db" to emptyList<Double>(), "min_db" to null, "peak_dbfs" to -200.0, "note" to "good")
        val floor = r.detector.floorDbValue()
        val minDb = if (floor.isFinite()) floor + plan!!.analysis.getDouble("open_db") else null
        val peak = r.peakDb
        return mapOf("bars_db" to r.levelBars, "min_db" to minDb, "peak_dbfs" to peak,
            "note" to if (peak >= -1.0) "loud" else if (minDb != null && peak <= minDb) "quiet" else "good")
    }

    private fun heardMap(): List<Map<String, Any?>> {
        val r = run
        val g = r?.genAtGo ?: ring.generation
        if (r == null && lastSavedTake == null) return emptyList()
        val goFrame = r?.goFrame ?: lastGoFrame
        val fromMs = goFrame * 1000 / sRate - 200
        // while recording: everything since GO (the end is not known yet); after: up to the saved take's end
        val toMs = if (r != null) Long.MAX_VALUE else (lastGoFrame + lastEndFrame) * 1000 / sRate
        return heard.window(g, fromMs, toMs).map { h ->
            val did = heard.did(h)
            val label = ai.vox.companion.SoundFold.label(h.label)
            val m = linkedMapOf<String, Any?>(
                "label" to label, "t_start_ms" to h.tStartMs, "t_end_ms" to h.tEndMs,
                "rel_ms" to (h.tStartMs - goFrame * 1000 / sRate),
                "dur_ms" to (h.tEndMs - h.tStartMs), "pitch16" to h.pitch16, "f0_hz" to h.f0Hz,
                "dropped" to h.dropped, "gated" to h.gated, "relabel" to h.relabel,
                "did" to did?.let { mapOf("n" to it.n, "sequence" to it.sequence, "action" to it.action, "ok" to it.ok) },
                "did_text" to heard.didText(h, did))
            if (label != h.label) m["raw_label"] = h.label   // a pop folded to click keeps its raw label
            m
        }
    }

    private fun lastMap(): Map<String, Any?>? {
        val t = lastSavedTake ?: return null
        val r = lastSavedRow ?: return null
        return mapOf("take_id" to t.takeId, "saved" to true, "dur_ms" to r.optDouble("dur_ms"), "reason" to lastReason,
            "f0_hz" to lastF0Hz, "below_f0_min" to false)
    }

    private fun feedLevel(r: TakeRun, samples: ShortArray) {
        val tickFrames = (plan!!.analysis.getDouble("tick_s") * sRate).toInt().coerceAtLeast(1)
        var o = 0
        while (o + tickFrames <= samples.size) {
            val db = rmsDb(samples, o, tickFrames)
            r.levelBars.add(db)
            while (r.levelBars.size > LEVEL_BARS) r.levelBars.removeAt(0)
            if (db > r.peakDb) r.peakDb = db
            o += tickFrames
        }
    }

    private fun rmsDb(samples: ShortArray, from: Int, n: Int): Double {
        var sumSq = 0.0
        for (i in from until from + n) { val s = samples[i] / 32768.0; sumSq += s * s }
        return 20.0 * log10(sqrt(sumSq / n) + 1e-9)
    }

    private fun medianF0(sounds: List<HeardLog.Sound>): Double? {
        val fs = sounds.mapNotNull { it.f0Hz }.sorted()
        if (fs.isEmpty()) return null
        return if (fs.size % 2 == 1) fs[fs.size / 2] else (fs[fs.size / 2 - 1] + fs[fs.size / 2]) / 2
    }

    private fun abortTake(reason: String? = null) {
        if (run != null && reason == null) log("abort", mapOf("take_id" to run?.take?.takeId))
        tickCancel?.invoke(); tickCancel = null
        countdownCancel?.invoke(); countdownCancel = null
        autoNextCancel?.invoke(); autoNextCancel = null
        run = null
        ticksOff()
        if (reason != null) { this.reason = reason; log("abort", mapOf("reason" to reason)) }
    }

    /** [rec] The live pitch trace since GO: one entry per 20 ms tick (null = unvoiced), capped at (max_s + 1) s. */
    fun onTick(f0Hz: Double?, levelDb: Double?) {
        if (state != "recording" || liveTrace.size >= liveCap) return
        liveTrace.add(f0Hz)
    }

    private fun ticksOff() { env.ticks(false, HUM_F0_MAX_HZ) }

    /** Every take of [block] is recorded or skipped this sitting and the block has no rating yet (state "rate"). */
    private fun needsRating(block: String): Boolean {
        val p = plan ?: return false; val s = session ?: return false
        val b = p.blocks.firstOrNull { it.id == block } ?: return false
        return b.cells.all { settled(s, it) } && s.ratingRows().none { it.optString("block") == block }
    }

    private fun allDone(): Boolean {
        val p = plan!!; val s = session!!
        return p.takes.all { settled(s, it) }
    }

    private fun uniqueName(base: String): String {
        var n = base; var i = 2
        while (File(env.filesDir, "range/$n").exists()) { n = "$base-$i"; i++ }
        return n
    }

    private fun cancelAll() {
        idleCloseCancel?.invoke(); autoNextCancel?.invoke(); countdownCancel?.invoke(); tickCancel?.invoke()
        idleCloseCancel = null; autoNextCancel = null; countdownCancel = null; tickCancel = null
    }

    private fun pushNow() { push(status()) }

    private fun log(event: String, fields: Map<String, Any?>) {
        val o = JSONObject()
        for ((k, v) in fields) o.put(k, v ?: JSONObject.NULL)
        ai.vox.companion.EventLog.ev("rec", "event" to event, "name" to (name ?: JSONObject.NULL), "fields" to o)
    }

    /** The 10 Hz pusher (the host drives it while ready/countdown/recording). */
    fun pushIfActive() { if (state == "ready" || state == "countdown" || state == "recording") push(status(withPlan = false)) }

    /** range_layout.default_session_name: `range-<yyyyMMdd-HHmmss>` for "self", else `range-<speaker>-<...>`. */
    internal fun sessionBase(speaker: String, wall: Long): String {
        val stamp = java.text.SimpleDateFormat("yyyyMMdd-HHmmss", java.util.Locale.US).format(java.util.Date(wall))
        return if (speaker == "self") "range-$stamp" else "range-$speaker-$stamp"
    }
}
