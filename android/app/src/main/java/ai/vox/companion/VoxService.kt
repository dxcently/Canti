package ai.vox.companion

import android.accessibilityservice.AccessibilityService
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.AudioManager
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import org.json.JSONObject
import java.util.concurrent.Executors

/**
 * The VOX accessibility service. Pipeline (all on the main thread except the decider call):
 *
 *   FeatureSource -> deliver() -> Sequencer (act now, or wait for a bound sequence) -> resolve()
 *     -> ScreenSummarizer (screen line, tie-breaker only) -> StateBuilder (Scene.text) -> Decider (worker thread)
 *     -> Executor (dispatchGesture / performGlobalAction) -> Confirmer ("confirmed (events|pixels)" / "no visible change")
 *
 * Intent cursor mode: in cursor mode "click pop" opens the listening window; the phrase that follows names an element.
 * Targets (accessibility nodes -> "label (role, position)" options) -> SystemOneClient question "target" -> tap it,
 * or highlight the top 3 for rise/fall/pop/hiss, or "not on screen".
 *
 * Personalization: a sound that carries a fingerprint is matched against the active profile's enrolled examples
 * (EnrollmentStore, Matcher) before sequencing, and its line and label are rewritten (Personal.rewrite).
 *
 * Every step is written to the event log (EventLog: logcat tag VOX + files/events.jsonl).
 */
class VoxService : AccessibilityService() {
    companion object {
        @Volatile var instance: VoxService? = null
            private set
    }

    private val main = Handler(Looper.getMainLooper())
    private val worker = Executors.newSingleThreadExecutor { r -> Thread(r, "vox-decider").apply { isDaemon = true } }
    private lateinit var settings: Settings
    private lateinit var overlay: Overlay
    private lateinit var confirmer: Confirmer
    private lateinit var executor: Executor
    private lateinit var sequencer: Sequencer
    private lateinit var audio: AudioManager
    private var decider: Decider = RuleDecider()
    private var profile: Profile = Profile.empty()
    private val sources = mutableListOf<FeatureSource>()
    private var ble: BleFeatureSource? = null

    private var deviceMode = "gesture"
    private var armed = true
    // Paused from the phone (the Flutter UI or op `pause`): sounds and phrases are ignored whatever the device says.
    private var paused = false
    private var lastMsgId: Long? = null
    private var listeningUntil = 0L
    private var lastPkg = "unknown"
    private var generation = 0L
    private var decisionCount = 0L
    private val recent = ArrayDeque<Pair<String, Long>>()   // action key, time
    private val labelCache = HashMap<String, String>()
    private val asr: PhraseRecognizer = StubPhraseRecognizer()

    // Personalization: the active profile's enrolled classes and the matcher built from them.
    private var enroll = EnrollmentStore(Profile.DEFAULT_NAME)
    private var matcher: Matcher? = null
    // Per-feature std floors by fp_version: assets/fp_floors.json, overridden by files/fp_floors.json (op fp_floors).
    private var floors: FpFloors = FpFloors.EMPTY

    // Intent cursor mode: the highlighted candidates, while the user picks one with sounds.
    private var choice: TargetChoice? = null
    private var choiceN = 0L
    private var choiceTimeout: Runnable? = null

    private val shotExecutor = Executors.newSingleThreadExecutor()

    /** Rects never compared by the pixel confirmer: system bars/windows and VOX's own overlays. */
    private fun pixelMask(): List<IntArray> {
        val r = android.graphics.Rect()
        val out = mutableListOf<IntArray>()
        try {
            for (w in windows) {
                if (w.type == android.view.accessibility.AccessibilityWindowInfo.TYPE_SYSTEM ||
                    w.type == android.view.accessibility.AccessibilityWindowInfo.TYPE_ACCESSIBILITY_OVERLAY) {
                    w.getBoundsInScreen(r); out += intArrayOf(r.left, r.top, r.right, r.bottom)
                }
            }
        } catch (_: Exception) {}
        return out + overlay.maskRects()
    }

    /** Screenshot -> masked luminance grid (API 30+ takeScreenshot); calls back on the main thread. */
    private fun grabGrid(cb: (PixelGrid?) -> Unit) {
        val mask = pixelMask()
        val sw = screenW(); val sh = screenH()
        try {
            takeScreenshot(android.view.Display.DEFAULT_DISPLAY, shotExecutor, object : TakeScreenshotCallback {
                override fun onSuccess(res: ScreenshotResult) {
                    val grid = try {
                        val hb = res.hardwareBuffer
                        val hw = android.graphics.Bitmap.wrapHardwareBuffer(hb, res.colorSpace)
                        val soft = hw?.copy(android.graphics.Bitmap.Config.ARGB_8888, false)
                        hb.close(); hw?.recycle()
                        soft?.let { b ->
                            val small = android.graphics.Bitmap.createScaledBitmap(b, PixelGrid.COLS * 4, PixelGrid.ROWS * 4, true)
                            val px = IntArray(small.width * small.height)
                            small.getPixels(px, 0, small.width, 0, 0, small.width, small.height)
                            val g = PixelGrid.from(small.width, small.height, px, sw, sh, mask)
                            if (small !== b) small.recycle(); b.recycle()
                            g
                        }
                    } catch (e: Exception) { null }
                    main.post { cb(grid) }
                }
                override fun onFailure(code: Int) {
                    main.post { EventLog.ev("screenshot", "error" to code); cb(null) }
                }
            })
        } catch (e: Exception) { cb(null) }
    }

    private fun screenW() = (getSystemService(Context.WINDOW_SERVICE) as WindowManager).currentWindowMetrics.bounds.width()
    private fun screenH() = (getSystemService(Context.WINDOW_SERVICE) as WindowManager).currentWindowMetrics.bounds.height()

    override fun onServiceConnected() {
        EventLog.init(this)
        settings = Settings(this)
        audio = getSystemService(Context.AUDIO_SERVICE) as AudioManager
        overlay = Overlay(this, ::screenW, ::screenH)
        confirmer = Confirmer(main, packageName, { TreeReader.fingerprint(TreeReader.appRoot(this)) }, { settings.confirmTimeoutMs }, ::grabGrid)
        executor = Executor(this, overlay, confirmer, ::screenW, ::screenH, ::openListening)
        sequencer = Sequencer(
            scheduler = object : Scheduler {
                override fun now() = SystemClock.elapsedRealtime()
                override fun schedule(delayMs: Long, task: () -> Unit): () -> Unit {
                    val r = Runnable(task); main.postDelayed(r, delayMs); return { main.removeCallbacks(r) }
                }
            },
            gapMs = { settings.gapMs },
            jitterMs = { settings.jitterMs },
            onResolve = ::resolve,
            onWait = { p, waitingFor, delay ->
                EventLog.ev("wait", "sequence" to p.sequence.joinToString(" "), "gap_ms" to settings.gapMs, "wait_ms" to delay,
                    "clock" to p.clock, "for" to waitingFor.joinToString(" | ") { it.joinToString(" ") })
            },
        )
        loadFloors()
        loadProfile()
        rebuildDecider()
        try { overlay.showBadge() } catch (e: Exception) { EventLog.ev("error", "where" to "overlay", "error" to e.toString()) }
        instance = this
        val sink = Sink { m, src -> deliver(m, src) }
        sources += BleFeatureSource(this, settings).also { ble = it }
        if (settings.debugSource) sources += DebugSocketSource(this)
        for (s in sources) try { s.start(sink) } catch (e: Exception) { EventLog.ev("error", "where" to "source ${s.name}", "error" to e.toString()) }
        EventLog.ev("service", "state" to "connected", "vocab" to Vocab.SOURCE_DIGEST, "decider" to decider.name,
            "screen" to "${screenW()}x${screenH()}")
        updateBadge("ready")
    }

    override fun onUnbind(intent: Intent?): Boolean { shutdown(); return super.onUnbind(intent) }
    override fun onDestroy() { shutdown(); super.onDestroy() }
    override fun onInterrupt() {}

    private fun shutdown() {
        if (instance == null) return
        instance = null
        sources.forEach { it.stop() }; sources.clear(); ble = null
        try { overlay.remove() } catch (_: Exception) {}
        EventLog.ev("service", "state" to "disconnected")
    }

    override fun onAccessibilityEvent(e: AccessibilityEvent) {
        if (instance == null) return
        confirmer.onEvent(e)
        if (e.eventType == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) {
            val pkg = e.packageName?.toString() ?: return
            if (pkg != packageName && pkg != lastPkg && pkg != "com.android.systemui") {
                lastPkg = pkg
                EventLog.ev("app", "package" to pkg)
            }
        }
    }

    // --- input ----------------------------------------------------------------------------------------------------

    /** Entry point for every source (main thread). */
    fun deliver(msg: JSONObject, source: String): JSONObject {
        return try {
            if (msg.optString("type", "features") == "control") control(msg)
            else features(FeatureMessage.parse(msg), source)
        } catch (e: IllegalArgumentException) {
            EventLog.ev("ignored", "reason" to "bad message: ${e.message}", "source" to source)
            JSONObject().put("ok", false).put("error", e.message)
        }
    }

    private fun features(m: FeatureMessage, source: String): JSONObject {
        // The device's ids restart at 1 on every boot: its first message on a new link is a reset point.
        if (source == BleFeatureSource.CONNECT_SOURCE) lastMsgId = null
        if (m.id != null && m.id == lastMsgId) {
            EventLog.ev("ignored", "reason" to "duplicate id ${m.id}")
            return JSONObject().put("ok", true).put("duplicate", true)
        }
        lastMsgId = m.id
        EventLog.ev("msg", "id" to m.id, "source" to source, "mode" to m.mode, "armed" to m.armed,
            "sequence" to m.sequence.joinToString(" "), "phrase" to m.phrase, "sleeping" to (if (m.sleeping) true else null))
        if (!m.armed) {
            // A dropped BLE link disarms like the device would (PROTOCOL.md); the device's ids may restart after it.
            if (source == BleFeatureSource.DISCONNECT_SOURCE) { lastMsgId = null; disarm("ble disconnect") }
            else disarm(if (m.sleeping) "device (going to sleep)" else "device")
            return ok()
        }
        if (!armed) { armed = true; EventLog.ev("arm", "state" to "armed") }
        setDeviceMode(if (m.mode == "listening") deviceMode else m.mode)
        if (paused) {
            if (m.sequence.isNotEmpty() || m.phrase != null) EventLog.ev("ignored", "reason" to "paused (app)", "id" to m.id)
            return ok()
        }

        if (m.phrase != null) {
            val now = SystemClock.elapsedRealtime()
            if (now > listeningUntil) {
                EventLog.ev("ignored", "reason" to "phrase outside listening window", "phrase" to m.phrase)
            } else {
                sequencer.flush()
                listeningUntil = 0
                asr.cancel()
                if (deviceMode == "cursor") selectTarget(m.phrase)
                else resolveInput("listening", currentApp(), emptyList(), emptyList(), m.phrase, false, 0)
            }
        }
        val pm = personalize(m)
        if (choice != null && pm.sequence.isNotEmpty()) { choiceInput(pm); return ok() }
        if (pm.sequence.isNotEmpty()) {
            val pkg = currentApp()
            sequencer.add(deviceMode, pkg, pm.sounds, pm.sequence, profile.boundSequences(pkg, deviceMode), pm.timing)
        }
        return ok()
    }

    /** Match each sound that carries a fingerprint against the enrolled classes and rewrite its line and label. */
    private fun personalize(m: FeatureMessage): FeatureMessage {
        val feats = m.features ?: return m
        val mt = matcher
        val sounds = m.sounds.toMutableList(); val seq = m.sequence.toMutableList()
        for (i in seq.indices) {
            val f = feats[i] ?: continue
            val r = mt?.match(f) ?: MatchResult("skipped", reason = "nothing enrolled for profile '${enroll.profile}'")
            val out = Personal.rewrite(r, sounds[i], seq[i])
            EventLog.ev("match", "id" to m.id, "i" to i, "profile" to enroll.profile, "result" to r.result, "class" to r.cls?.name,
                "nearest" to r.nearest, "distance" to r.distance?.let(::r4), "threshold" to r.threshold?.let(::r4),
                "dtw" to r.dtw?.let(::r4), "dtw_threshold" to r.dtwThreshold?.let(::r4), "reason" to r.reason,
                "label" to seq[i], "new_label" to out.label.takeIf { it != seq[i] }, "line" to out.sound.takeIf { it != sounds[i] },
                "floors" to mt?.floorStatus)
            sounds[i] = out.sound; seq[i] = out.label
        }
        return m.copy(sounds = sounds, sequence = seq)
    }

    private fun r4(d: Double) = Math.round(d * 10000) / 10000.0

    private fun ok() = JSONObject().put("ok", true).put("waiting", sequencer.isWaiting).put("mode", deviceMode)

    private fun setDeviceMode(mode: String) {
        if (mode == deviceMode) return
        sequencer.flush()
        deviceMode = mode
        if (mode == "cursor") overlay.showCursor() else { overlay.hideCursor(); executor.cancelDrag(); cancelChoice("mode change") }
        EventLog.ev("mode", "mode" to mode)
        updateBadge("")
    }

    /** Emergency stop / disarm: drop pending sounds, stop the cursor, close listening, discard in-flight decisions. */
    private fun disarm(why: String) {
        armed = false
        generation++
        sequencer.cancel()
        overlay.stop(); executor.cancelDrag(); cancelChoice("disarm")
        listeningUntil = 0
        EventLog.ev("arm", "state" to "disarmed", "by" to why)
        updateBadge("DISARMED")
    }

    /** Pause or resume from the phone. Pausing drops what is pending, like a disarm; the device's arm state is kept. */
    fun setPaused(p: Boolean, by: String) {
        if (p == paused) return
        paused = p
        if (p) {
            generation++
            sequencer.cancel()
            overlay.stop(); executor.cancelDrag(); cancelChoice("pause")
            listeningUntil = 0
        }
        EventLog.ev("pause", "state" to if (p) "paused" else "resumed", "by" to by)
        updateBadge(if (p) "PAUSED" else "")
    }

    /** The state the Flutter status screen shows ([UiBridge], PROTOCOL.md "UI channel"). Main thread. */
    fun uiStatus(): Map<String, Any?> = mapOf(
        "service" to true, "armed" to armed, "paused" to paused, "mode" to deviceMode, "app" to currentApp(),
        "decider" to settings.decider, "ble_state" to ble?.state?.name?.lowercase(), "ble_device" to settings.bleDevice, "ble_hint" to ble?.hint,
        "device_state" to ble?.deviceState(), "device_ready" to (ble?.link?.ready == true), "device_armed" to ble?.link?.armed,
        "device_mode" to ble?.link?.mode, "device_waiting" to ble?.link?.waitingFor?.label, "device_error" to ble?.link?.error,
        "vocab" to Vocab.SOURCE_DIGEST)

    /** An app command to the device (PROTOCOL.md "App commands (CONFIG)"); [done] gets the outcome (main thread). */
    fun deviceCommand(c: DeviceLink.Command, done: (JSONObject) -> Unit) {
        val b = ble ?: return done(JSONObject().put("ok", false).put("cmd", c.label).put("result", "failed").put("error", "BLE source not running"))
        b.command(c, done)
    }

    /** Connect to the remembered device again (after the user acted on a pairing hint). */
    fun connectDevice(): JSONObject = bleOrThrow().connect("auto")

    private fun openListening() {
        val until = SystemClock.elapsedRealtime() + settings.listenWindowMs
        listeningUntil = until
        EventLog.ev("listening", "state" to "open", "window_ms" to settings.listenWindowMs, "mode" to deviceMode)
        updateBadge("LISTENING")
        asr.listen(settings.listenWindowMs) { text ->
            if (text != null && listeningUntil == until) deliver(JSONObject().put("v", 1).put("mode", "listening").put("armed", true)
                .put("sounds", org.json.JSONArray()).put("sequence", org.json.JSONArray()).put("phrase", text), "asr:${asr.name}")
        }
        main.postDelayed({
            if (listeningUntil == until) { listeningUntil = 0; EventLog.ev("listening", "state" to "closed (timeout)"); updateBadge("") }
        }, settings.listenWindowMs)
    }

    // --- decide and act -------------------------------------------------------------------------------------------

    private fun resolve(p: Sequencer.Pending) {
        val held = SystemClock.elapsedRealtime() - p.firstAt
        resolveInput(p.mode, p.app, p.sounds, p.sequence, null, p.waited, held, p)
    }

    private fun resolveInput(mode: String, pkg: String, sounds: List<String>, seq: List<String>, phrase: String?, waited: Boolean, heldMs: Long,
                             p: Sequencer.Pending? = null) {
        val n = ++decisionCount
        EventLog.ev("resolve", "n" to n, "sequence" to seq.joinToString(" "), "phrase" to phrase, "waited" to waited, "held_ms" to heldMs, "app" to pkg,
            "clock" to p?.clock, "ended_by" to p?.endedBy, "gaps_ms" to p?.gapsMs?.let { org.json.JSONArray(it) }, "note" to p?.note)
        val screen = try { summarize(pkg).first } catch (e: Exception) { EventLog.ev("error", "where" to "screen", "error" to e.toString()); null }
        val scene = StateBuilder.build(mode, pkg, appLabel(pkg), sounds, seq, phrase, profile, recentActions(),
            if (mode == "cursor") overlay.description else null, screen)
        val input = DecisionInput(scene, profile)
        EventLog.ev("state", "n" to n, "text" to scene.text())
        val gen = generation
        if (mode == "cursor" && seq == Profile.CURSOR_LISTEN && profile.cursorBindings().none { it.phrase == seq }) {
            // Not a model decision: CURSOR_ACTIONS has no listen option (schema.py), so the app owns this sequence.
            act(n, gen, mode, Decision("listen_for_phrase", "app:cursor-listen", explicit = true))
            return
        }
        val d = decider
        worker.execute {
            val decision = try { d.decide(input) } catch (e: Exception) { Decision("none", "error:${e.javaClass.simpleName}:${e.message}") }
            main.post { act(n, gen, mode, decision) }
        }
    }

    private fun act(n: Long, gen: Long, mode: String, d: Decision) {
        EventLog.ev("decision", "n" to n, "action" to d.action, "source" to d.source, "confidence" to d.confidence,
            "ms" to d.latencyMs, "mode" to mode, "server_ms" to d.serverMs, "top" to d.top.takeIf { it.isNotEmpty() }?.let(::topJson))
        if (gen != generation || !armed) { EventLog.ev("ignored", "n" to n, "reason" to "disarmed while deciding"); return }
        val r = try { executor.perform(d.action, mode) } catch (e: Exception) { Executor.Result(false, "error: $e") }
        EventLog.ev("exec", "n" to n, "action" to d.action, "ok" to r.ok, "how" to r.how, "watch" to r.watch)
        if (d.action != "none" && r.ok) {
            recent.addLast(d.action to SystemClock.elapsedRealtime())
            while (recent.size > 3) recent.removeFirst()
        }
        updateBadge(d.action)
    }

    private fun topJson(top: List<Pair<String, Double>>): org.json.JSONArray =
        org.json.JSONArray(top.map { (o, p) -> JSONObject().put("option", o).put("p", p) })

    private fun toast(text: String) {
        EventLog.ev("toast", "text" to text)
        try { android.widget.Toast.makeText(this, text, android.widget.Toast.LENGTH_SHORT).show() } catch (_: Exception) {}
    }

    // --- intent cursor mode -----------------------------------------------------------------------------------------

    /** The phrase after "click pop" in cursor mode names an on-screen element: build the options and ask the model. */
    private fun selectTarget(utterance: String) {
        cancelChoice("new target phrase")
        val n = ++decisionCount
        val pkg = currentApp()
        val targets = Targets.build(TreeReader.snapshot(TreeReader.appRoot(this)), screenW(), screenH())
        val screen = try { summarize(pkg).first } catch (e: Exception) { ScreenContext("other", "none", "not scrollable", "hidden") }
        val state = Targets.stateText(StateBuilder.appName(pkg, appLabel(pkg)), pkg, screen, utterance.trim())
        val options = Targets.options(targets)
        EventLog.ev("target_state", "n" to n, "app" to pkg, "text" to state, "options" to org.json.JSONArray(options))
        if (targets.isEmpty()) { toast("nothing to tap on this screen"); EventLog.ev("target", "n" to n, "result" to "no targets"); return }
        if (settings.decider == "rules") {
            toast("naming a target needs the model decider")
            EventLog.ev("target", "n" to n, "result" to "no model (decider=rules)"); return
        }
        val client = SystemOneClient(settings.baseUrl, settings.targetModel.ifBlank { settings.model }, { settings.apiKey }, settings.httpTimeoutMs)
        val gen = generation
        updateBadge("naming...")
        worker.execute {
            val res = try { Result.success(client.choice(state, "target", TargetVocab.POLICY, options)) } catch (e: Exception) { Result.failure(e) }
            main.post { onTargetAnswer(n, gen, targets, res) }
        }
    }

    private fun onTargetAnswer(n: Long, gen: Long, targets: List<Target>, res: Result<ChoiceAnswer>) {
        val a = res.getOrElse { e ->
            EventLog.ev("target_decision", "n" to n, "error" to "${e.javaClass.simpleName}: ${e.message?.take(160)}")
            toast("couldn't pick a target"); updateBadge("target failed"); return
        }
        EventLog.ev("target_decision", "n" to n, "choice" to a.choice, "confidence" to a.confidence, "top" to topJson(a.top(3)),
            "ms" to a.ms, "server_ms" to a.serverMs, "min_confidence" to settings.targetMinConfidence)
        if (gen != generation || !armed) { EventLog.ev("ignored", "n" to n, "reason" to "disarmed while deciding"); return }
        val out = try { Targets.resolve(targets, a, settings.targetMinConfidence) } catch (e: IllegalArgumentException) {
            EventLog.ev("target", "n" to n, "result" to "error", "error" to e.message); return
        }
        when (out) {
            is Targets.Outcome.NotOnScreen -> { toast("not on screen"); EventLog.ev("target", "n" to n, "result" to "not on screen"); updateBadge("not on screen") }
            is Targets.Outcome.Tap -> tapTarget(n, out.target, "confident")
            is Targets.Outcome.Choose -> startChoice(n, out.targets)
        }
    }

    private fun tapTarget(n: Long, t: Target, why: String) {
        val r = try { executor.tapTarget(t) } catch (e: Exception) { Executor.Result(false, "error: $e") }
        EventLog.ev("target", "n" to n, "result" to "tap", "why" to why, "option" to t.option, "x" to t.cx, "y" to t.cy,
            "ok" to r.ok, "how" to r.how, "watch" to r.watch)
        updateBadge("tap ${t.label}")
    }

    private fun startChoice(n: Long, candidates: List<Target>) {
        val c = TargetChoice(candidates)
        choice = c; choiceN = n
        try { overlay.showTargets(candidates, 0) } catch (e: Exception) { EventLog.ev("error", "where" to "highlight", "error" to e.toString()) }
        EventLog.ev("target", "n" to n, "result" to "choose", "candidates" to org.json.JSONArray(candidates.map { it.option }), "selected" to 1)
        armChoiceTimeout()
        updateBadge("pick 1-${candidates.size}")
    }

    private fun armChoiceTimeout() {
        choiceTimeout?.let { main.removeCallbacks(it) }
        val r = Runnable { cancelChoice("timeout") }
        choiceTimeout = r
        main.postDelayed(r, settings.targetChooseMs)
    }

    private fun cancelChoice(why: String?) {
        if (choice == null) return
        choice = null
        choiceTimeout?.let { main.removeCallbacks(it) }; choiceTimeout = null
        try { overlay.hideTargets() } catch (_: Exception) {}
        if (why != null) { EventLog.ev("choice", "n" to choiceN, "event" to "cancelled", "why" to why); updateBadge("cancelled") }
    }

    /** While candidates are highlighted, sounds pick among them instead of going to the decider. */
    private fun choiceInput(m: FeatureMessage) {
        val c = choice ?: return
        val pkg = currentApp()
        for (i in m.sequence.indices) {
            val label = m.sequence[i]
            val heard = m.sounds.getOrNull(i) ?: ""
            val nd = RuleDecider.notDeliberate(Scene(mode = "cursor", app = pkg, appName = pkg, heard = listOf(heard), sequence = listOf(label)))
            if (nd != null) { EventLog.ev("choice", "n" to choiceN, "event" to "ignored", "sound" to label, "why" to nd); continue }
            when (label) {
                "rise", "fall" -> {
                    if (label == "rise") c.next() else c.previous()
                    overlay.selectTarget(c.index)
                    armChoiceTimeout()
                    EventLog.ev("choice", "n" to choiceN, "event" to "select", "sound" to label, "selected" to c.index + 1, "option" to c.selected.option)
                }
                "pop" -> {
                    val t = c.selected; val idx = c.index + 1; val n = choiceN; val gen = generation
                    EventLog.ev("choice", "n" to n, "event" to "picked", "selected" to idx, "option" to t.option)
                    cancelChoice(null)
                    // Let the highlight window disappear before the tap (and before the confirmer's first screenshot).
                    main.postDelayed({ if (gen == generation && armed) tapTarget(n, t, "picked $idx of ${c.candidates.size}") }, 120)
                    return
                }
                "hiss" -> { cancelChoice("hiss"); return }
                else -> EventLog.ev("choice", "n" to choiceN, "event" to "ignored", "sound" to label, "why" to "rise/fall cycle, pop taps, hiss cancels")
            }
        }
    }

    private fun recentActions(): List<String> {
        val now = SystemClock.elapsedRealtime()
        return recent.filter { now - it.second < 30_000 }.map { it.first }
    }

    private fun updateBadge(last: String) {
        val m = when { !armed -> "OFF"; paused -> "PAUSED"; listeningUntil > SystemClock.elapsedRealtime() -> "LISTEN"; else -> deviceMode.uppercase() }
        try { overlay.setBadge("VOX $m ${if (last.isNotEmpty()) "· $last" else ""}") } catch (_: Exception) {}
    }

    // --- app and screen -------------------------------------------------------------------------------------------

    private fun currentApp(): String =
        TreeReader.appRoot(this)?.packageName?.toString() ?: lastPkg

    private fun appLabel(pkg: String): String? = labelCache.getOrPut(pkg) {
        try { packageManager.getApplicationLabel(packageManager.getApplicationInfo(pkg, 0)).toString() } catch (e: Exception) { pkg }
    }

    private fun launchers(): Set<String> =
        packageManager.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME), PackageManager.MATCH_DEFAULT_ONLY)
            .map { it.activityInfo.packageName }.toSet()

    /** Screen line + raw summary for the current app window. */
    fun summarize(pkg: String = currentApp()): Pair<ScreenContext, JSONObject> {
        val root = TreeReader.appRoot(this)
        val snap = TreeReader.snapshot(root)
        val facts = ScreenFacts(root?.packageName?.toString() ?: pkg, screenW(), screenH(), TreeReader.keyboardOpen(this),
            launchers(), audio.isMusicActive, windows.size)
        return ScreenSummarizer.classify(snap, facts) to ScreenSummarizer.rawSummary(snap, facts)
    }

    // --- profile, decider, control --------------------------------------------------------------------------------

    private fun loadProfile() {
        val json = settings.profileJson ?: assets.open("profile_default.json").bufferedReader().use { it.readText() }
        profile = try { Profile.parse(JSONObject(json)) } catch (e: Exception) {
            EventLog.ev("error", "where" to "profile", "error" to e.toString()); Profile.empty()
        }
        EventLog.ev("profile", "name" to profile.name, "bindings" to profile.bindings.size, "custom" to (settings.profileJson != null))
        if (profile.name != enroll.profile || matcher == null) loadEnrollment()
    }

    private fun loadEnrollment() {
        enroll = try { EnrollmentStore.load(filesDir, profile.name) } catch (e: Exception) {
            EventLog.ev("error", "where" to "enrollment", "profile" to profile.name, "error" to e.toString()); EnrollmentStore(profile.name)
        }
        rebuildMatcher()
    }

    private fun rebuildMatcher() {
        val before = matcher?.let { it.store.fpVersion to it.floorStatus }
        val m = Matcher(enroll, settings.enrollRejectMult, floors)
        matcher = m
        // Say once (per change) which floors the matcher uses, and loudly when they are provisional or missing.
        if (before != (enroll.fpVersion to m.floorStatus) && enroll.fpVersion != null)
            EventLog.ev("fp_floors", "fp_version" to enroll.fpVersion, "status" to m.floorStatus, "source" to m.floor?.source,
                "note" to when (m.floorStatus) {
                    "provisional" -> "provisional per-feature floors, to be replaced by the extractor's scales"
                    "none" -> "no floors for this fp_version: near-constant features are not floored"
                    "mismatch" -> "floor length differs from the enrolled vectors: not used"
                    else -> null
                })
    }

    private fun bleOrThrow() = ble ?: throw IllegalArgumentException("BLE source not running")

    /** MainActivity: the Bluetooth permissions may have changed. */
    fun blePermissionsChanged() { ble?.permissionsChanged() }

    private fun overrideFloorsFile() = java.io.File(filesDir, "fp_floors.json")

    /** Asset table, then the on-device override on top (each validated; a bad file is logged and skipped). */
    private fun loadFloors() {
        var t = try { assets.open("fp_floors.json").bufferedReader().use { FpFloors.parse(JSONObject(it.readText())) } } catch (e: Exception) {
            EventLog.ev("error", "where" to "fp_floors asset", "error" to e.toString()); FpFloors.EMPTY
        }
        val f = overrideFloorsFile()
        if (f.exists()) t = try { t.overriddenBy(FpFloors.parse(JSONObject(f.readText()))) } catch (e: Exception) {
            EventLog.ev("error", "where" to "fp_floors override", "error" to e.toString()); t
        }
        floors = t
    }

    private fun enrollSummary(): JSONObject {
        val th = matcher?.thresholds() ?: emptyMap()
        return JSONObject().put("profile", enroll.profile).put("fp_version", enroll.fpVersion ?: JSONObject.NULL).put("dim", enroll.dim ?: JSONObject.NULL)
            .put("reject_mult", settings.enrollRejectMult).put("floors", matcher?.floorStatus ?: JSONObject.NULL)
            .put("classes", org.json.JSONArray(enroll.classes.map { c ->
                JSONObject().put("kind", c.kind).put("name", c.name).put("examples", c.examples.size).put("active", c.active)
                    .put("contour", c.contour).put("threshold", th[c.name]?.first?.let(::r4) ?: JSONObject.NULL)
                    .put("dtw_threshold", th[c.name]?.second?.let(::r4) ?: JSONObject.NULL)
            }))
    }

    /** Apply an enrollment change and persist it; on a failed save the in-memory store is reloaded from disk. */
    private fun changeEnrollment(what: String, change: () -> Unit) {
        change()
        try { EnrollmentStore.save(filesDir, enroll) } catch (e: Exception) { loadEnrollment(); throw IllegalArgumentException("save failed: $e") }
        rebuildMatcher()
        EventLog.ev("enroll", "change" to what, "profile" to enroll.profile, "classes" to enroll.classes.size,
            "examples" to enroll.classes.sumOf { it.examples.size })
    }

    private fun rebuildDecider() {
        val http = if (settings.decider == "rules") null else HttpDecider(settings.baseUrl, settings.model, { settings.apiKey },
            settings.httpTimeoutMs, settings.minConfidence)
        decider = ChainDecider(settings.decider, http)
    }

    private fun control(m: JSONObject): JSONObject {
        val op = m.getString("op")
        val reply = JSONObject().put("ok", true).put("op", op)
        when (op) {
            "ping" -> reply.put("app", currentApp()).put("mode", deviceMode).put("armed", armed).put("paused", paused)
                .put("waiting", sequencer.isWaiting).put("settings", settings.describe()).put("vocab", Vocab.SOURCE_DIGEST)
                .put("decisions", decisionCount)
            "config" -> { settings.apply(m); rebuildDecider(); rebuildMatcher(); reply.put("settings", settings.describe()) }
            "enroll_add" -> {
                // {kind, name, examples: [{fp, fp_version, pitch16}]} for the active profile (enrollment is done on the PC).
                val ex = m.getJSONArray("examples")
                val feats = List(ex.length()) { SoundFeatures.parse(ex.getJSONObject(it), "examples[$it]") }
                val kind = m.getString("kind"); val name = m.getString("name")
                changeEnrollment("add $kind '$name' +${feats.size}") { enroll.add(kind, name, feats) }
                reply.put("enrollment", enrollSummary())
            }
            "enroll_list" -> reply.put("enrollment", enrollSummary())
            "pause" -> { setPaused(m.optBoolean("paused", true), "op"); reply.put("paused", paused) }
            // BLE link to the device (no UI yet): scan, connect <address|auto>, status, disconnect, forget, CONFIG write.
            "ble_scan" -> reply.put("ble", bleOrThrow().scan(m.optLong("ms", 10_000).coerceIn(1_000, 60_000)).getJSONObject("ble"))
            "ble_connect" -> reply.put("result", bleOrThrow().connect(m.optString("address", "auto")))
            "ble_status" -> reply.put("ble", bleOrThrow().status())
            "ble_disconnect" -> reply.put("ble", bleOrThrow().disconnect().getJSONObject("ble"))
            "device" -> {
                // Returns at once; the confirmation (or its timeout) is logged as device_cmd and shown in ble_status.
                var now: JSONObject? = null
                bleOrThrow().command(DeviceLink.Command.from(m)) { r -> now = r }
                now?.let { if (!it.optBoolean("ok")) throw IllegalArgumentException(it.optString("error")) }
                reply.put("device_cmd", now ?: JSONObject().put("result", "sent").put("note", "the confirmation is logged as device_cmd"))
            }
            "ble_forget" -> reply.put("result", bleOrThrow().forget())
            "ble_config" -> reply.put("result", bleOrThrow().writeConfig(m.getJSONObject("config")))
            "fp_floors" -> {
                // {} shows the table in use; {table: {...}} stores an override (entries replace the asset's per
                // fp_version); {reset: true} removes the override.
                val f = overrideFloorsFile()
                if (m.optBoolean("reset")) f.delete()
                else if (m.has("table")) {
                    val t = m.getJSONObject("table")
                    FpFloors.parse(t)
                    val tmp = java.io.File(filesDir, "fp_floors.json.tmp"); tmp.writeText(t.toString())
                    require(tmp.renameTo(f)) { "could not write $f" }
                }
                if (m.optBoolean("reset") || m.has("table")) { loadFloors(); matcher = null; rebuildMatcher() }
                reply.put("table", floors.toJson()).put("override", f.exists()).put("status", matcher?.floorStatus ?: JSONObject.NULL)
            }
            "enroll_delete" -> {
                // {name, index?} deletes a class or one example; {all: true} clears the profile's store.
                if (m.optBoolean("all")) changeEnrollment("clear") { enroll.clear() }
                else {
                    val name = m.getString("name"); val idx = if (m.has("index")) m.getInt("index") else null
                    var found = false
                    changeEnrollment("delete '$name'${idx?.let { " #$it" } ?: ""}") { found = enroll.delete(name, idx) }
                    reply.put("deleted", found)
                }
                reply.put("enrollment", enrollSummary())
            }
            "profile" -> {
                if (m.isNull("profile")) settings.profileJson = null
                else { Profile.parse(m.getJSONObject("profile")); settings.profileJson = m.getJSONObject("profile").toString() }
                loadProfile(); reply.put("bindings", profile.bindings.size)
            }
            "screen" -> {
                val (ctx, raw) = summarize()
                EventLog.ev("screen", "line" to ctx.text(), "package" to raw.optString("package"))
                reply.put("line", ctx.text()).put("summary", raw)
            }
            "dump" -> {
                // Visible nodes of the app window (id, class, text, description, bounds), for test assertions.
                val root = TreeReader.appRoot(this)
                val snap = TreeReader.snapshot(root)
                val arr = org.json.JSONArray()
                snap?.walk()?.filter { it.visible }?.forEach { n ->
                    arr.put(JSONObject().put("id", n.id ?: "").put("cls", n.shortCls).put("text", n.text ?: "")
                        .put("desc", n.desc ?: "").put("click", n.clickable).put("scroll", n.scrollable)
                        .put("bounds", "${n.left},${n.top},${n.right},${n.bottom}"))
                }
                reply.put("package", currentApp()).put("window", root?.packageName?.toString() ?: "").put("nodes", arr)
            }
            "harvest" -> {
                val (ctx, raw) = summarize()
                val rec = JSONObject().put("tag", m.optString("tag")).put("package", raw.optString("package"))
                    .put("screen_text", ctx.text()).put("summary", raw)
                EventLog.harvest(rec)
                EventLog.ev("harvest", "tag" to m.optString("tag"), "package" to raw.optString("package"), "screen_text" to ctx.text())
                reply.put("record", rec)
            }
            "targets" -> {
                // The option list intent cursor mode would send for the current screen (harvest / debugging).
                val pkg = currentApp()
                val targets = Targets.build(TreeReader.snapshot(TreeReader.appRoot(this)), screenW(), screenH())
                val (ctx, _) = summarize(pkg)
                reply.put("package", pkg).put("screen_text", ctx.text()).put("options", org.json.JSONArray(Targets.options(targets)))
                    .put("targets", org.json.JSONArray(targets.map { t ->
                        JSONObject().put("option", t.option).put("bounds", "${t.left},${t.top},${t.right},${t.bottom}") }))
            }
            "reset" -> {
                generation++; sequencer.cancel(); sequencer.resetClock(); overlay.stop(); executor.cancelDrag(); listeningUntil = 0; recent.clear()
                cancelChoice("reset")
                lastMsgId = null; armed = true; paused = false
                if (m.optBoolean("clear_log")) EventLog.clear()
                if (m.optBoolean("clear_harvest")) EventLog.clearHarvest()
                EventLog.ev("reset")
                updateBadge("reset")
            }
            else -> throw IllegalArgumentException("unknown control op '$op'")
        }
        return reply
    }
}
