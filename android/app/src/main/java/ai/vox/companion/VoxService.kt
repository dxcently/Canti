package ai.vox.companion

import android.accessibilityservice.AccessibilityService
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.AudioManager
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
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
 *   (fast path: what the decider settles locally, Decider.local, is decided at once on the main thread, no screen)
 *     -> Executor (dispatchGesture / performGlobalAction) -> Confirmer ("confirmed (events|pixels)" / "no visible change")
 *
 * Intent cursor mode: in cursor mode "pop pop" opens the listening window; the phrase that follows names an element.
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

        /** Moving between Canti screens pauses one and resumes the next within this: the head stays tucked. */
        const val TUCK_DEBOUNCE_MS = 150L
        /** The main-thread lag probe's tick while armed ([MainLoad] `main:lag`). */
        const val HEARTBEAT_MS = 50L
        const val LAUNCHER_CACHE_MS = 60_000L
        /** How long a local model's declared target option format is trusted before it is read again. */
        const val OPTION_FORMAT_MAX_AGE_MS = 10 * 60_000L
        /** [train] The UI channel's `train_status` pushes (UiBridge sets it; main thread). */
        @Volatile var trainSink: ((Map<String, Any?>) -> Unit)? = null
    }

    private val main = Handler(Looper.getMainLooper())
    /** The mode the user last chose themselves (UserMode.kt); a wake restores it. */
    private val userMode by lazy {
        val p = getSharedPreferences("canti_device", MODE_PRIVATE)
        UserMode(object : UserMode.Store {
            override fun load() = p.getString("user_mode", null)
            override fun save(mode: String) { p.edit().putString("user_mode", mode).apply() }
            override fun log(ev: String, vararg fields: Pair<String, Any?>) { EventLog.ev(ev, *fields) }
        })
    }
    private val worker = Executors.newSingleThreadExecutor { r -> Thread(r, "vox-decider").apply { isDaemon = true } }
    private lateinit var settings: Settings
    private lateinit var overlay: Overlay
    private lateinit var confirmer: Confirmer
    private lateinit var executor: Executor
    private lateinit var sequencer: Sequencer
    private lateinit var holdScroll: HoldScroller
    // The last executed rise/fall swipe: a held flat starting right after it scrolls (HoldScrollTrigger).
    private var lastSwipe: HoldScrollTrigger.Swipe? = null
    // A `hold start` that arrived while a sound was still pending or being decided (maybe the swipe it follows),
    // with its arrival time; applied once that decision is acted on ([applyBufferedHold]).
    private var bufferedHold: Pair<HoldMessage, Long>? = null
    private var bufferedHoldEnded = false
    // Gesture decisions handed to the decider and not yet acted on.
    private val deciding = mutableSetOf<Long>()
    private lateinit var audio: AudioManager
    /** Phone / USB mic sounds while media plays: dropped except a `pop pop` unlock (MediaGate.kt). */
    private lateinit var mediaGate: MediaGate
    private var decider: Decider = RuleDecider()
    private var profile: Profile = Profile.empty()
    private val sources = mutableListOf<FeatureSource>()
    private var ble: BleFeatureSource? = null
    // [phone-mic] The phone/USB mic source (audio/PhoneMicSource.kt); always present, idle unless sound_source picks it.
    private var mic: ai.vox.companion.audio.PhoneMicSource? = null
    /** The voice joystick (cursor mode with the phone / a USB mic; VoiceJoystick.kt) and its calibration. */
    var joy: VoiceJoystick? = null; private set
    private var sink: Sink? = null
    private var lastSource = ""

    private var deviceMode = "gesture"
    private var armed = true
    // Paused from the phone (the Flutter UI or op `pause`): sounds and phrases are ignored whatever the device says.
    private var paused = false
    private var lastMsgId: Long? = null
    private var lastMsgAt = 0L   // elapsedRealtime of the last features message (decision event "since_msg_ms")
    private var lastPkg = "unknown"
    private var generation = 0L
    private var decisionCount = 0L
    private val recent = ArrayDeque<Pair<String, Long>>()   // action key, time
    private val labelCache = HashMap<String, String>()
    // The phrase window: the recognizer (`asr_engine`), the window around it, the last problem the user must fix.
    private var asr: PhraseRecognizer = StubPhraseRecognizer()
    private lateinit var listenWindow: ListenWindow
    /** Dictation mode (VoiceTyping.kt): utterance after utterance typed into the focused box. */
    private lateinit var dictation: Dictation
    private var asrProblem: String? = null

    // Personalization: the active profile's enrolled classes on the current sound source and the matcher built from them.
    private var enroll = EnrollmentStore(Profile.DEFAULT_NAME)
    // [train] Gesture training (GestureTraining.kt, PROTOCOL.md "Gesture training"): the UI's train_* session.
    var train: GestureTrainer? = null; private set
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
        mediaGate = MediaGate({ settings.mediaLock }, { settings.mediaUnlockMs }, { settings.gapMs }, { settings.mediaUnlockMode })
        audio.registerAudioPlaybackCallback(playbackWatch, main)
        overlay = Overlay(this, ::screenW, ::screenH)
        confirmer = Confirmer(main, packageName, { MainLoad.time("tree:fingerprint") { TreeReader.fingerprint(TreeReader.appRoot(this)) } }, { settings.confirmTimeoutMs }, ::grabGrid)
        MainLoad.mainThread = Thread.currentThread()
        MainLoad.onSlow = { what, ms -> EventLog.ev("main_slow", "what" to what, "ms" to Math.round(ms * 10) / 10.0, "app" to lastPkg) }
        main.removeCallbacks(heartbeat); main.post(heartbeat)
        executor = Executor(this, overlay, confirmer, ::screenW, ::screenH, ::openListening)
        executor.dialogGuard = ::systemDialog
        executor.feedWatch = { armed && !paused }
        executor.onDialogBlock = { action, dialog ->
            EventLog.ev("system_dialog", "action" to action, "dialog" to dialog, "result" to "refused")
            main.post { updateBadge(SystemDialog.BADGE) }
        }
        val scheduler = object : Scheduler {
            override fun now() = SystemClock.elapsedRealtime()
            override fun schedule(delayMs: Long, task: () -> Unit): () -> Unit {
                val r = Runnable(task); main.postDelayed(r, delayMs); return { main.removeCallbacks(r) }
            }
        }
        val micYield = object : ListenWindow.MicYield {
            override fun yieldMic(why: String) = mic?.yieldMic(why) ?: false
            override fun resumeMic(why: String) { mic?.resumeMic(why) }
        }
        listenWindow = ListenWindow(scheduler, micYield)
        // Dictation holds the mic itself for the whole session; its windows (one recognizer per utterance) have none.
        dictation = Dictation(scheduler, micYield, ListenWindow(scheduler, null), { asr },
            object : Dictation.Typer {
                override fun refusal() = executor.typingRefusal()
                override fun type(text: String) = executor.typeText(text)
            },
            logText = { settings.logTypedText }, log = { f -> EventLog.ev("dictate", *f) },
            speechHoldMs = { settings.dictateSpeechHoldMs },
            onStop = { why, status ->
                if (status != null) asrProblem = status
                toast(if (why == "stop phrase" || why == "silence") "dictation off" else "dictation off: $why")
                updateBadge("")
            })
        val power = getSystemService(PowerManager::class.java)
        holdScroll = HoldScroller(scheduler, foreground = ::currentApp, screenOn = { power.isInteractive },
            drag = executor.Drag { settings.autoScrollPct * screenH() / 100f * holdScroll.speed.toFloat() },   // speed: pitch throttle
            onEvent = { ev, r, why ->
                EventLog.ev("auto_scroll", "event" to ev, "action" to r.action, "app" to r.app, "hold" to r.holdId, "why" to why,
                    "pct_per_s" to settings.autoScrollPct, "ms" to SystemClock.elapsedRealtime() - r.startedAt)
                updateBadge(if (ev == "start") holdScroll.status ?: "" else "scroll stopped")
            })
        sequencer = Sequencer(
            scheduler = scheduler,
            gapMs = { settings.gapMs },
            jitterMs = { settings.jitterMs },
            onResolve = ::resolve,
            onWait = { p, waitingFor, delay ->
                EventLog.ev("wait", "sequence" to p.sequence.joinToString(" "), "gap_ms" to settings.gapMs, "wait_ms" to delay,
                    "clock" to p.clock, "for" to waitingFor.joinToString(" | ") { it.joinToString(" ") })
                updateBadge("")
            },
            onAbsorb = { p, sound, gap ->
                EventLog.ev("absorbed", "sound" to sound, "tail_of" to p.sequence.joinToString(" "), "gap_ms" to gap,
                    "clock" to if (gap != null) "device" else "arrival", "why" to "the rest of a sequence whose prefix already acted")
            },
        )
        loadFloors()
        loadProfile()
        rebuildDecider()
        rebuildAsr()
        try { overlay.showBadge(badgeActions) } catch (e: Exception) { EventLog.ev("error", "where" to "overlay", "error" to e.toString()) }
        ai.vox.companion.audio.SoundSource.addListener(sourceListener)
        application.registerActivityLifecycleCallbacks(screenCallbacks)
        LauncherIcon.watch(application)
        instance = this
        val sink = Sink { m, src -> deliver(m, src) }
        this.sink = sink
        // [phone-mic] BLE only when the sound source is the Pico; the mic source decides itself (SourcePolicy).
        if (settings.mic.source == ai.vox.companion.audio.MicSettings.PICO) sources += BleFeatureSource(this, settings).also { ble = it }
        sources += ai.vox.companion.audio.PhoneMicSource(this, settings.mic,
            active = { !paused && (armed || settings.mic.whileDisarmed) }, mode = { deviceMode }).also { mic = it }
        try {
            joy = VoiceJoystick(this, overlay, settings, main, { Targets.build(TreeReader.targetLayers(this), screenW(), screenH()) }, { screenW() to screenH() })
        } catch (e: Exception) { EventLog.ev("error", "where" to "joystick", "error" to e.toString()) }
        train = GestureTrainer(trainHost(scheduler))   // [train]
        if (settings.debugSource) sources += DebugSocketSource(this)
        for (s in sources) try { s.start(sink) } catch (e: Exception) { EventLog.ev("error", "where" to "source ${s.name}", "error" to e.toString()) }
        EventLog.ev("service", "state" to "connected", "vocab" to Vocab.SOURCE_DIGEST, "decider" to decider.name,
            "screen" to "${screenW()}x${screenH()}", "swipe_safe" to executor.safeInsets().toString())
        updateBadge("ready")
        joyUpdate()
        lastSource = settings.mic.source
        ai.vox.companion.audio.CantiNotification.start(this, ::notificationState)   // [phone-mic] status notification
    }

    override fun onUnbind(intent: Intent?): Boolean { shutdown(); return super.onUnbind(intent) }
    override fun onDestroy() { shutdown(); super.onDestroy() }
    override fun onInterrupt() {}

    private fun shutdown() {
        if (instance == null) return
        instance = null
        holdScroll.stop("service stopped")
        train?.cancel("service stopped"); train = null   // [train]
        try { audio.unregisterAudioPlaybackCallback(playbackWatch) } catch (_: Exception) {}
        main.removeCallbacks(mediaWindowEnd); main.removeCallbacks(mediaRecheck)
        listenWindow.cancel("service stopped"); dictation.stop("service stopped"); asr.cancel(); fileAsr.cancel("service stopped")
        ai.vox.companion.audio.SoundSource.removeListener(sourceListener)
        application.unregisterActivityLifecycleCallbacks(screenCallbacks); resumedScreens.clear(); main.removeCallbacks(tuckCheck)
        joy?.close(); joy = null
        sources.forEach { it.stop() }; sources.clear(); ble = null; mic = null; sink = null   // [phone-mic] mic, sink
        try { overlay.remove() } catch (_: Exception) {}
        ai.vox.companion.audio.CantiNotification.stop()   // [phone-mic]
        EventLog.ev("service", "state" to "disconnected")
    }

    override fun onAccessibilityEvent(e: AccessibilityEvent) = MainLoad.time("a11y_event") { onEvent(e) }

    private fun onEvent(e: AccessibilityEvent) {
        if (instance == null) return
        confirmer.onEvent(e)
        executor.onWindowEvent(e.eventType, e.packageName?.toString(), e.windowId)
        if (e.eventType == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) {
            val pkg = e.packageName?.toString() ?: return
            if (pkg != packageName && pkg != lastPkg && pkg != "com.android.systemui") {
                lastPkg = pkg
                EventLog.ev("app", "package" to pkg)
                holdScroll.appChanged(pkg)
            }
        }
    }

    // --- input ----------------------------------------------------------------------------------------------------

    /** Entry point for every source (main thread). */
    fun deliver(msg: JSONObject, source: String): JSONObject {
        return try {
            if (msg.optString("type", "features") == "control") control(msg)
            else if (HoldMessage.isHold(msg)) hold(HoldMessage.parse(msg), source)
            else MainLoad.time("msg:features") { features(FeatureMessage.parse(msg), source) }
        } catch (e: IllegalArgumentException) {
            EventLog.ev("ignored", "reason" to "bad message: ${e.message}", "source" to source)
            JSONObject().put("ok", false).put("error", e.message)
        }
    }

    private fun features(m: FeatureMessage, source: String): JSONObject {
        lastMsgAt = SystemClock.elapsedRealtime()
        // The device's ids restart at 1 on every boot: its first message on a new link is a reset point.
        if (source == BleFeatureSource.CONNECT_SOURCE) lastMsgId = null
        if (m.id != null && m.id == lastMsgId) {
            EventLog.ev("ignored", "reason" to "duplicate id ${m.id}")
            return JSONObject().put("ok", true).put("duplicate", true)
        }
        lastMsgId = m.id
        EventLog.ev("msg", "id" to m.id, "source" to source, "mode" to m.mode, "armed" to m.armed,
            "sequence" to m.sequence.joinToString(" "), "phrase" to m.phrase, "sleeping" to (if (m.sleeping) true else null),
            "by" to m.by)
        // The user switched the mode on the Pico's button: that is their own choice, so a wake keeps it (UserMode).
        if (m.by == "button" && m.sequence.isEmpty()) userMode.chose(m.mode, "button")
        if (!m.armed) {
            // A dropped BLE link disarms like the device would (PROTOCOL.md); the device's ids may restart after it.
            if (source == BleFeatureSource.DISCONNECT_SOURCE) { lastMsgId = null; disarm("ble disconnect") }
            else disarm(if (m.sleeping) "device (going to sleep)" else "device")
            return ok()
        }
        // Arm and take the message's mode before drawing: the head goes straight from OFF / TAP_TO_WAKE to its final
        // state (a wake into cursor mode must not show idle first).
        val arming = !armed
        if (arming) { armed = true; EventLog.ev("arm", "state" to "armed"); mic?.refresh("armed"); executor.feedKindWake() }   // [phone-mic] refresh
        val modeChanged = setDeviceMode(if (m.mode == "listening") deviceMode else m.mode)
        if (arming && !modeChanged) updateBadge("")
        if (paused) {
            if (m.sequence.isNotEmpty() || m.phrase != null) EventLog.ev("ignored", "reason" to "paused (app)", "id" to m.id)
            return ok()
        }
        // [train] Gesture training: while a session is open every sound goes to it (a take, or dropped) and none acts.
        train?.let { t ->
            if (!t.active) return@let
            val recording = t.recording
            t.onSounds(m)
            if (!recording && m.sequence.isNotEmpty()) EventLog.ev("ignored", "reason" to "gesture training (not recording)",
                "id" to m.id, "sequence" to m.sequence.joinToString(" "))
            return ok()
        }
        // Media playing: a phone / USB mic sound is dropped unless it completes the `pop pop` unlock (MediaGate).
        if (mediaGateDrops(m, source)) return ok()
        // The held flat's final event was the scroll: drop it (no long-press).
        val kept = dropHeld(m)
        if (kept.sequence.isEmpty() && m.sequence.isNotEmpty() && kept.phrase == null) return ok()
        // Any other sound stops a hold-scroll (normally its `hold end` already has) and is handled as usual.
        if (kept.sequence.isNotEmpty()) holdScroll.stop("other sound: ${kept.sequence.joinToString(" ")}")
        return sounds(kept)
    }

    /** An armed, unpaused message's phrase and sounds. */
    private fun sounds(m: FeatureMessage): JSONObject {
        // Dictating: a sound is never acted on. While words are coming in it is speech (ignored, Dictation logs it);
        // after a pause it stops dictation. A phrase from the device is not dictation.
        if (dictation.active) {
            if (m.sequence.isNotEmpty()) {
                if (dictation.sound(m.sequence.joinToString(" ")))
                    EventLog.ev("ignored", "reason" to "dictating (the sound stopped dictation)", "sequence" to m.sequence.joinToString(" "))
            } else if (m.phrase != null) EventLog.ev("ignored", "reason" to "phrase message while dictating")
            return ok()
        }
        if (m.phrase != null) {
            if (!listenWindow.isOpen) {
                EventLog.ev("ignored", "reason" to "phrase outside listening window", "phrase" to m.phrase)
            } else {
                // A phrase from the device (or the debug socket) answers the window: the phone's recognizer stops.
                sequencer.flush()
                listenWindow.cancel("phrase message")
                onHeard(Heard(listOf(m.phrase)), "message", window = true)
            }
        }
        // While the phrase window is open the user is talking: speech is not gestures (the Pico still hears it).
        if (listenWindow.isOpen && m.sequence.isNotEmpty()) {
            EventLog.ev("ignored", "reason" to "phrase window open (speech is not gestures)", "sequence" to m.sequence.joinToString(" "))
            return ok()
        }
        val pm = personalize(m)
        if (choice != null && pm.sequence.isNotEmpty()) { choiceInput(pm); return ok() }
        if (confirm != null && pm.sequence.isNotEmpty() && confirmInput(pm)) return ok()
        if (pm.sequence.isNotEmpty()) {
            val pkg = currentApp()
            sequencer.add(deviceMode, pkg, pm.sounds, pm.sequence, profile.boundSequences(pkg, deviceMode), pm.timing,
                profile.absorbedSequences(pkg, deviceMode))
        }
        return ok()
    }

    /** Drop the sounds whose hold scrolled (`timing[i].sound` of a held flat), logging each. */
    private fun dropHeld(m: FeatureMessage): FeatureMessage {
        val t = m.timing ?: return m
        val drop = t.indices.filter { i -> holdScroll.consumeFinal(t[i]?.sound?.toString()) }
        if (drop.isEmpty()) return m
        for (i in drop) EventLog.ev("resolve", "id" to m.id, "sequence" to m.sequence[i], "auto_scroll" to "hold", "hold" to t[i]?.sound,
            "note" to "its hold scrolled (a held flat after a swipe, or glide-and-hold), so its final event is not acted on")
        fun <T> keep(l: List<T>?) = l?.filterIndexed { i, _ -> i !in drop }
        return m.copy(sounds = keep(m.sounds)!!, sequence = keep(m.sequence)!!, timing = keep(m.timing), features = keep(m.features))
    }

    /**
     * A live hold message (PROTOCOL.md "Hold messages"). `start` right after an executed rise/fall swipe
     * ([HoldScrollTrigger]) scrolls that way until `end`; a start that arrives while a sound is still pending or being
     * decided waits for that decision ([applyBufferedHold]). `flat:false` never acts, except a glide-and-hold start
     * (`"from":"glide"`, [GlideHold]): that scrolls the glide's way at once, with no swipe before it. [HoldGate] routes.
     */
    private fun hold(h: HoldMessage, source: String): JSONObject {
        if (source == BleFeatureSource.CONNECT_SOURCE) lastMsgId = null
        if (h.id != null && h.id == lastMsgId) {
            EventLog.ev("ignored", "reason" to "duplicate id ${h.id}")
            return JSONObject().put("ok", true).put("duplicate", true)
        }
        lastMsgId = h.id
        // [train] no hold-scroll while gesture training records (a held flat is a take, not a scroll)
        if (train?.active == true) {
            if (h.kind != "pitch") EventLog.ev("ignored", "reason" to "gesture training", "hold" to h.kind, "sound" to h.sound)
            return ok()
        }
        if (h.kind == "pitch") {   // pitch throttle (PROTOCOL.md "Hold pitch"): only for the hold that is scrolling
            val used = h.f0Hz != null && holdScroll.pitch(h.sound.toString(), h.f0Hz, h.tMs)
            EventLog.ev("hold", "id" to h.id, "kind" to "pitch", "sound" to h.sound, "t_ms" to h.tMs, "f0_hz" to h.f0Hz,
                "used" to used, "st" to holdScroll.pitchSt, "speed" to holdScroll.speed)
            return ok()
        }
        val now = SystemClock.elapsedRealtime()
        EventLog.ev("hold", "id" to h.id, "source" to source, "kind" to h.kind, "sound" to h.sound, "t_start_ms" to h.tStartMs,
            "t_ms" to h.tMs, "f0_hz" to h.f0Hz, "flat" to (if (h.kind == "start") h.flat else null), "from" to h.from, "dir" to h.dir)
        val sound = h.sound.toString()
        if (h.kind == "end") {
            val b = bufferedHold
            if (b != null && b.first.sound == h.sound) { bufferedHoldEnded = true; return ok() }
            if (!holdScroll.holdEnded(sound)) EventLog.ev("ignored", "reason" to "hold end with no running hold-scroll", "sound" to h.sound)
            return ok()
        }
        if (isMicSource(source) && mediaLocked(now)) {
            // a hold start is a sound too (a held flat scrolls); its end always passes, so a running scroll can stop
            EventLog.ev("media_gate", "kind" to "hold", "source" to settings.mic.source, "dropped" to true, "hold" to h.sound)
            return ok()
        }
        if (dictation.active) {
            if (dictation.sound("hold")) EventLog.ev("ignored", "reason" to "dictating (the sound stopped dictation)", "hold" to h.sound)
            return ok()
        }
        when (val r = HoldGate.route(h, armed, paused, listenWindow.isOpen, sequencer.isWaiting, deciding.isNotEmpty(),
                deviceMode, currentApp(), profile)) {
            is HoldGate.Route.Ignore -> EventLog.ev("ignored", "reason" to r.why, "hold" to h.sound)
            HoldGate.Route.Buffer -> {
                bufferedHold = h to now; bufferedHoldEnded = false
                EventLog.ev("hold", "sound" to h.sound, "event" to "buffered", "why" to "a sound is still pending or being decided")
            }
            is HoldGate.Route.Glide -> startGlide(h, r.action)
            HoldGate.Route.Flat -> startHold(h, now)
        }
        return ok()
    }

    /** Glide-and-hold: scroll [action] (what a single rise / fall does here) until `hold end`. */
    private fun startGlide(h: HoldMessage, action: String) {
        lastSwipe = null
        EventLog.ev("hold", "sound" to h.sound, "event" to "scroll", "action" to action, "why" to "glide-and-hold ${h.dir}")
        holdScroll.start(action, currentApp(), h.sound.toString(), h.f0Hz)
    }

    /** Apply the gate to a hold start and scroll. */
    private fun startHold(h: HoldMessage, arrivedAt: Long) {
        if (h.isGlide) {   // buffered behind a decision: route it again now
            GlideHold.action(h.dir, deviceMode, currentApp(), profile)?.let { startGlide(h, it) }
                ?: EventLog.ev("hold", "sound" to h.sound, "event" to "no scroll", "why" to "glide ${h.dir}: not a scroll here")
            return
        }
        val app = currentApp()
        val why = HoldScrollTrigger.follows(lastSwipe, decisionCount, deviceMode, app, h.tStartMs, arrivedAt)
        val s = lastSwipe
        if (why == null || s == null) {
            EventLog.ev("hold", "sound" to h.sound, "event" to "no scroll", "why" to "not right after a rise/fall swipe (long-press rules apply)",
                "last_swipe" to s?.action)
            return
        }
        lastSwipe = null
        EventLog.ev("hold", "sound" to h.sound, "event" to "scroll", "action" to s.action, "why" to why)
        holdScroll.start(s.action, app, h.sound.toString(), h.f0Hz)
    }

    /**
     * After a decision is acted on: a hold start buffered behind it gets its gate now (once nothing else is pending),
     * unless its `hold end` has already arrived: then it does not act, and its sound is decided as usual.
     */
    private fun applyBufferedHold() {
        val b = bufferedHold ?: return
        if (sequencer.isWaiting || deciding.isNotEmpty()) return
        bufferedHold = null
        when {
            bufferedHoldEnded -> EventLog.ev("hold", "sound" to b.first.sound, "event" to "no scroll",
                "why" to "hold ended before the swipe was acted on")
            armed && !paused -> startHold(b.first, b.second)
        }
    }

    private fun dropBufferedHold() { bufferedHold = null }

    /** Match each sound that carries a fingerprint against the enrolled classes and rewrite its line and label. */
    private fun personalize(m: FeatureMessage): FeatureMessage {
        val feats = m.features ?: return m
        val mt = matcher
        val sounds = m.sounds.toMutableList(); val seq = m.sequence.toMutableList()
        for (i in seq.indices) {
            val f = feats[i] ?: continue
            val r = mt?.match(f) ?: MatchResult("skipped", reason = "nothing enrolled for profile '${enroll.profile}'")
            val gated = m.gated?.getOrNull(i)   // [train] a phone-mic gate made it `unknown` on purpose: never rewritten
            val out = Personal.rewrite(r, sounds[i], seq[i], settings.enrollGestureRelabel, f.pitch16, gated)   // [train] gesture relabel
            EventLog.ev("match", "id" to m.id, "i" to i, "profile" to enroll.profile, "result" to r.result, "class" to r.cls?.name,
                "nearest" to r.nearest, "distance" to r.distance?.let(::r4), "threshold" to r.threshold?.let(::r4),
                "dtw" to r.dtw?.let(::r4), "dtw_threshold" to r.dtwThreshold?.let(::r4), "reason" to r.reason,
                "label" to seq[i], "new_label" to out.label.takeIf { it != seq[i] }, "line" to out.sound.takeIf { it != sounds[i] },
                "floors" to mt?.floorStatus,
                // [train] a trained gesture relabelled the sound (or agreed with the extractor: trusted)
                "relabel" to out.relabelFrom?.let { JSONObject().put("from", it).put("to", out.label) }, "trusted" to out.trusted.takeIf { it },
                "dist" to r.distance?.let(::r4).takeIf { out.relabelFrom != null },
                "skipped" to out.skipped, "gated" to gated)   // [train] gated: the match is logged, the sound left alone
            sounds[i] = out.sound; seq[i] = out.label
        }
        return m.copy(sounds = sounds, sequence = seq)
    }

    private fun r4(d: Double) = Math.round(d * 10000) / 10000.0

    private fun ok() = JSONObject().put("ok", true).put("waiting", sequencer.isWaiting).put("mode", deviceMode)

    /** Follows the device's mode; true when it changed (and the badge was redrawn). */
    private fun setDeviceMode(mode: String): Boolean {
        if (mode == deviceMode) return false
        sequencer.flush()
        holdScroll.stop("mode change"); dropBufferedHold()
        deviceMode = mode
        if (mode == "cursor") overlay.showCursor() else { overlay.hideCursor(); executor.cancelDrag(); cancelChoice("mode change") }
        joyUpdate()
        EventLog.ev("mode", "mode" to mode)
        updateBadge("")
        return true
    }

    /** Emergency stop / disarm: drop pending sounds, stop the cursor, close listening, discard in-flight decisions. */
    private fun disarm(why: String) {
        armed = false
        generation++
        sequencer.cancel()
        holdScroll.stop("disarm ($why)"); dropBufferedHold()
        overlay.stop(); executor.cancelDrag(); cancelChoice("disarm")
        listenWindow.cancel("disarm"); dictation.stop("disarm")
        EventLog.ev("arm", "state" to "disarmed", "by" to why)
        updateBadge("DISARMED")
        mic?.refresh("disarm")   // [phone-mic]
    }

    /** Pause or resume from the phone. Pausing drops what is pending, like a disarm; the device's arm state is kept. */
    fun setPaused(p: Boolean, by: String) {
        if (p == paused) return
        paused = p
        if (p) {
            generation++
            sequencer.cancel()
            holdScroll.stop("pause"); dropBufferedHold()
            overlay.stop(); executor.cancelDrag(); cancelChoice("pause")
            listenWindow.cancel("pause"); dictation.stop("pause")
        }
        // [phone-mic] With a mic source the phone owns the arm state: resuming also re-arms.
        if (!p && !armed && settings.mic.usesMic) { armed = true; EventLog.ev("arm", "state" to "armed", "by" to "resume ($by)") }
        EventLog.ev("pause", "state" to if (p) "paused" else "resumed", "by" to by)
        updateBadge(if (p) "PAUSED" else "")
        mic?.refresh(if (p) "pause" else "resume")   // [phone-mic]
    }

    /**
     * [phone-mic] The `sound_source` setting may have changed (settings screen, op `config`): run BLE only for the
     * Pico, and let the mic source apply its policy. Switching to a mic source re-arms (the phone owns the arm state
     * then; a Pico that disconnected left it disarmed).
     */
    fun soundSourceChanged() {
        val s = sink ?: return
        val wantBle = !settings.mic.usesMic
        val b = ble
        if (wantBle && b == null) {
            val nb = BleFeatureSource(this, settings)
            ble = nb; sources += nb
            try { nb.start(s) } catch (e: Exception) { EventLog.ev("error", "where" to "source ${nb.name}", "error" to e.toString()) }
        } else if (!wantBle && b != null) {
            b.stop(); sources.remove(b); ble = null
        }
        if (!wantBle && !armed) { armed = true; EventLog.ev("arm", "state" to "armed", "by" to "sound source ${settings.mic.source}"); updateBadge("") }
        mic?.refresh("sound source ${settings.mic.source}")
        joyUpdate()
        if (settings.mic.source != lastSource) { lastSource = settings.mic.source; ai.vox.companion.audio.SoundSource.notifyListeners(lastSource) }
        // [train] the enrollment store is per sound source: match against (and train into) the new source's store
        if (settings.mic.source != enroll.source) { train?.cancel("sound source changed"); loadEnrollment() }
    }

    /** The joystick follows the mode, the sound source and the mic source (VoiceJoystick.update). */
    private fun joyUpdate() { joy?.update(deviceMode == "cursor", settings.mic.source, mic) }

    /** The state the Flutter status screen shows ([UiBridge], PROTOCOL.md "UI channel"). Main thread. */
    fun uiStatus(): Map<String, Any?> = mapOf<String, Any?>(
        "service" to true, "armed" to armed, "paused" to paused, "mode" to deviceMode, "app" to currentApp(),
        "decider" to settings.deciderLabel(), "decider_mode" to settings.decider, "ble_state" to ble?.state?.name?.lowercase(), "ble_device" to settings.bleDevice, "ble_hint" to ble?.hint,
        "device_state" to ble?.deviceState(), "device_ready" to (ble?.link?.ready == true), "device_armed" to ble?.link?.armed,
        "device_mode" to ble?.link?.mode, "device_waiting" to ble?.link?.waitingFor?.label, "device_error" to ble?.link?.error,
        "vocab" to Vocab.SOURCE_DIGEST, "auto_scroll" to holdScroll.status, "badge" to BadgeStates.label(badgeState()),
        // [phone-mic] the sound source and the mic's state
        "sound_source" to settings.mic.source, "mic_state" to mic?.state, "mic_device" to mic?.device,
        "notifications" to ai.vox.companion.audio.NotificationSetup.enabled(this),
        // The first-run pairing screen (../ui pair_screen.dart): missing permissions, Bluetooth, the device being found.
        "ble_missing" to BleFeatureSource.missingPermissions(this), "ble_blocked" to Pairing.permissionBlocked,
        // The phrase window's speech: engine and whether it can listen ("ready", "offline speech pack missing", ...).
        "asr_engine" to settings.asrEngine, "asr_status" to asrStatus(),
        // the media gate: phone / USB mic sounds dropped while media plays (MediaGate)
        "media_locked" to (settings.mic.usesMic && mediaLocked(SystemClock.elapsedRealtime())),
        // the voice joystick: a saved calibration for the current sound source (the Pico: always false for now)
        "calibrated" to (joy?.calibrated() ?: false),
    ) + (ble?.setup() ?: emptyMap())


    /** [phone-mic] What the status notification shows (audio/CantiNotification.kt). */
    private fun notificationState() = ai.vox.companion.audio.CantiNotification.State(
        source = settings.mic.source, paused = paused, armed = armed, mode = deviceMode,
        device = ble?.deviceState(), micState = mic?.state, micDevice = mic?.device, wakeable = deviceWakeable())

    /** The Pico is connected and paused only by a link drop (DeviceLink.wakeable; not with a mic source). */
    private fun deviceWakeable() = ble?.link?.wakeable == true

    /**
     * Wake the Pico after a link drop left it paused: the badge's tap in TAP_TO_WAKE, or the notification's Wake. The
     * same arm command as the status screen's Resume ({"armed": true}, DeviceLink), plus the mode the user last chose
     * ([UserMode]) when the device is in another one (a test tool or console may have left it): one write, one
     * confirmation. The device's confirming state message arms the app and sets its mode in one badge update
     * ([features]); this callback runs just before that message is delivered, so it draws only on failure. Logged
     * `wake{by, result, mode}` (+ `mode_request{by: wake}` when the mode is restored); a failure plays the error one-shot.
     */
    fun wakeDevice(by: String) {
        val link = ble?.link
        val why = when {
            link == null -> "no Pico link"
            !link.wakeable -> "not paused by a link drop (${link.pauseCause?.name?.lowercase() ?: "armed"})"
            link.waitingFor != null -> "busy: '${link.waitingFor?.label}' is waiting"
            else -> null
        }
        if (why != null) { EventLog.ev("wake", "by" to by, "result" to "skipped", "why" to why); updateBadge(""); return }
        val c = userMode.wakeCommand(link!!.mode)
        EventLog.ev("wake", "by" to by, "result" to "sent", "mode" to c.mode, "device_mode" to link.mode, "user_mode" to userMode.mode)
        if (c.mode != null) EventLog.ev("mode_request", "mode" to c.mode, "by" to "wake", "why" to "the user's mode (device in ${link.mode})")
        deviceCommand(c) { r ->
            val ok = r.optBoolean("ok", false)
            EventLog.ev("wake", "by" to by, "result" to r.optString("result"), "error" to r.opt("error"), "ms" to r.opt("ms"),
                "mode" to c.mode, "applied" to r.opt("applied"))
            if (!ok) { try { overlay.badgePlayOnce(BadgeState.ERROR) } catch (_: Exception) {}; updateBadge("") }
            main.post { ai.vox.companion.audio.CantiNotification.refresh() }   // after the confirming message is handled
        }
    }

    /**
     * [phone-mic] Gesture <-> cursor from the phone (notification, badge). The same path as the UI's mode buttons
     * ([deviceCommand]): a command to the Pico, which answers with its new mode; with a mic source, applied here.
     */
    fun toggleMode(by: String) {
        val to = if (deviceMode == "cursor") "gesture" else "cursor"
        EventLog.ev("mode_request", "mode" to to, "by" to by)
        deviceCommand(DeviceLink.Command(mode = to), by) { r -> if (!r.optBoolean("ok", true)) EventLog.ev("mode_request", "mode" to to, "result" to r.toString()) }
    }
    /**
     * An app command to the device (PROTOCOL.md "App commands (CONFIG)"); [done] gets the outcome (main thread). [by]:
     * the user's control that sent it (UserMode.USER_PATHS); a confirmed mode change from one is saved as the user's mode.
     */
    fun deviceCommand(c: DeviceLink.Command, by: String? = null, done: (JSONObject) -> Unit) {
        if (by != null && c.mode != null) {
            val then = done
            return deviceCommand(c) { r ->
                if (r.optBoolean("ok") && r.optBoolean("applied", true)) userMode.chose(c.mode, by)
                then(r)
            }
        }
        // [phone-mic] With a mic source there is no device: the phone owns mode and arm state, applied here.
        if (settings.mic.usesMic) {
            if (c.sleep) return done(JSONObject().put("ok", false).put("cmd", c.label).put("result", "failed").put("error", "no device with a mic source"))
            c.mode?.let { setDeviceMode(it) }
            c.armed?.let { a -> if (!a) disarm("app") else if (!armed) { armed = true; EventLog.ev("arm", "state" to "armed", "by" to "app"); updateBadge(""); mic?.refresh("armed") } }
            ai.vox.companion.audio.CantiNotification.refresh()
            return done(JSONObject().put("ok", true).put("cmd", c.label).put("result", "applied").put("local", true))
        }
        val b = ble ?: return done(JSONObject().put("ok", false).put("cmd", c.label).put("result", "failed").put("error", "BLE source not running"))
        b.command(c, done)
    }

    /** Connect to the remembered device again (after the user acted on a pairing hint). */
    fun connectDevice(): JSONObject = bleOrThrow().connect("auto")

    // --- the phrase window (ListenWindow.kt, PhraseGrammar.kt) -----------------------------------------------------
    //
    // Transcripts are personal: they go to the local event log and, only as the phrase decider's input, to a model
    // the user enabled (decider model/hybrid/escalate). Commands the grammar knows never leave the phone.

    /** `asr_engine` -> the recognizer (a new one only when the engine changes; a window in flight is closed first). */
    private fun rebuildAsr() {
        val want = settings.asrEngine
        if (asr.name == want) return
        if (::listenWindow.isInitialized) listenWindow.cancel("asr_engine changed")
        if (::dictation.isInitialized) dictation.stop("asr_engine changed")
        asr.cancel()
        asr = when (want) {
            "android" -> AndroidPhraseRecognizer(this, { settings.asrAllowOnline }, { settings.asrLanguage })
            else -> StubPhraseRecognizer()
        }
        EventLog.ev("asr", "engine" to asr.name)
        checkAsr("engine ${asr.name}")
    }

    /** Ask the recognizer whether it can listen (the offline pack); the result is the UI's `asr_status`. */
    private fun checkAsr(why: String) {
        val a = asr as? AndroidPhraseRecognizer
        if (a == null) { asrProblem = null; return }
        asrProblem = a.status()
        a.check { pack ->
            asrProblem = a.status()
            EventLog.ev("asr", "event" to "check", "why" to why, "pack" to pack, "status" to (asrProblem ?: "ready"), "info" to JSONObject(a.describe()))
        }
    }

    private fun asrStatus(): String = when {
        settings.asrEngine == "off" -> "off"
        else -> asrProblem ?: "ready"
    }

    private fun openListening() {
        val engine = asr
        EventLog.ev("listening", "state" to "open", "window_ms" to settings.listenWindowMs, "mode" to deviceMode, "engine" to engine.name,
            "recognizer" to (engine as? AndroidPhraseRecognizer)?.plan()?.kind?.name?.lowercase())
        val gen = generation
        listenWindow.open(engine, settings.listenWindowMs) { d -> listenDone(d, gen) }
        updateBadge("LISTENING")
        // Warm the app list ("open <app>") while the user speaks, after the recognizer has started.
        main.postDelayed({ if (listenWindow.isOpen) launchableApps() }, 700)
    }

    private fun listenDone(d: ListenWindow.Done, gen: Long) {
        val h = d.heard
        val hide = h != null && hidesText(h)
        EventLog.ev("asr", "event" to "closed", "why" to d.why, "engine" to d.engine, "recognizer" to (asr as? AndroidPhraseRecognizer)?.kind,
            "status" to d.status, "n_best" to h?.let { if (hide) "(typing: not logged)" else org.json.JSONArray(it.hypotheses) },
            "confidence" to h?.confidences?.takeIf { it.isNotEmpty() }?.let { c -> org.json.JSONArray(c.map { it.toDouble() }) },
            "partial" to if (h?.partial == true) true else null, "partials" to d.partials, "peak_db" to d.peakDb?.toDouble(),
            "ready_ms" to d.readyMs, "ms" to d.ms, "mic_yielded" to d.micYielded)
        if (d.status != null) {
            asrProblem = d.status
            toast("Canti: ${d.status}")
        } else if (h != null && asr is AndroidPhraseRecognizer) asrProblem = null
        updateBadge("")
        if (h == null) return
        if (gen != generation || !armed || paused) { EventLog.ev("ignored", "reason" to "disarmed while listening", "phrase" to if (hide) "(typing: not logged)" else h.best); return }
        onHeard(h, "asr:${d.engine}", window = true)   // every recognizer run answers a listen window a pop pop opened
    }

    /** The `phrase` debug op's record of one phrase's path (parse, decision, exec); null outside that op. */
    private var trace: JSONObject? = null
    private fun trace(key: String, value: Any?) { trace?.put(key, value) }

    /** A phrase (the recognizer's n-best, or a message's phrase): the grammar first, then the phrase decider. */
    private fun onHeard(h: Heard, source: String, window: Boolean) {
        // Typing by voice, in a listen window only: the best hypothesis as said, never the grammar's cleaned words.
        if (window) h.best?.let { TypeGrammar.parse(it) }?.let { runTyping(it, source); return }
        val t0 = System.nanoTime()
        val apps = launchableApps()
        val t1 = System.nanoTime()
        val ctx = PhraseGrammar.Context(apps = apps, userPhrases = profile.phraseBindings().mapNotNull { it.say }.toSet(),
            cursor = deviceMode == "cursor", window = window)
        var targets: List<Target>? = null
        val screenTargets = {
            targets ?: (try { Targets.build(TreeReader.targetLayers(this), screenW(), screenH(), format = optionFormat) }
                catch (e: Exception) { EventLog.ev("error", "where" to "targets", "error" to e.toString()); emptyList() }).also { targets = it }
        }
        val pick = PhraseGrammar.choose(h, ctx) { q -> TargetMatcher.best(screenTargets(), q) }
        val parseMs = Math.round((System.nanoTime() - t1) / 1e5) / 10.0   // the screen read for a tap included
        EventLog.ev("phrase_parse", "source" to source, "heard" to pick.text, "hypothesis" to pick.index, "command" to pick.command.describe(),
            "parses" to org.json.JSONArray(pick.parsed.map { it.describe() }), "mode" to deviceMode, "window" to window, "parse_ms" to parseMs)
        trace("heard", pick.text); trace("hypothesis", pick.index); trace("command", pick.command.describe())
        trace("parses", org.json.JSONArray(pick.parsed.map { it.describe() }))
        trace("apps_ms", Math.round((t1 - t0) / 1e5) / 10.0); trace("parse_ms", parseMs)
        runCommand(pick.command, screenTargets)
    }

    /** A "type ..." whose words stay out of the log (unless `log_typed_text`). */
    private fun hidesText(h: Heard): Boolean = !settings.logTypedText && h.hypotheses.any { TypeGrammar.parse(it) is TypeGrammar.Cmd.Type }

    /** "type <text>" / "write <text>", "dictate", "stop dictation" ([TypeGrammar]). Typing never presses send or enter. */
    private fun runTyping(c: TypeGrammar.Cmd, source: String) {
        val n = ++decisionCount
        EventLog.ev("phrase_parse", "source" to source, "command" to when (c) {
            is TypeGrammar.Cmd.Type -> "type (${c.text.length} chars)"
            TypeGrammar.Cmd.StartDictation -> "dictate"
            TypeGrammar.Cmd.StopDictation -> "stop dictation"
        }, "mode" to deviceMode, "window" to true)
        trace("command", c.javaClass.simpleName.lowercase())
        when (c) {
            is TypeGrammar.Cmd.Type -> {
                val text = Punctuation.apply(c.text)
                val r = if (text.isEmpty()) TextInsert.Outcome(false, TextInsert.EMPTY)
                    else try { executor.typeText(text) } catch (e: Exception) { TextInsert.Outcome(false, "error: $e") }
                EventLog.ev("exec", "n" to n, "action" to Executor.TYPE_TEXT, "ok" to r.ok, "how" to r.how, "chars" to r.chars,
                    "text" to text.takeIf { settings.logTypedText })
                trace("exec", JSONObject().put("action", Executor.TYPE_TEXT).put("ok", r.ok).put("how", r.how).put("chars", r.chars))
                if (!r.ok) toast(if (r.how == TextInsert.EMPTY) "say what to type: \"type hello\"" else r.how)
                updateBadge("type")
            }
            TypeGrammar.Cmd.StartDictation -> {
                val why = dictation.start(source)
                trace("exec", JSONObject().put("action", "dictate").put("ok", why == null).put("how", why ?: "started"))
                toast(why ?: "dictating: stops on silence, a sound, or \"stop dictation\"")
                updateBadge("dictate")
            }
            TypeGrammar.Cmd.StopDictation -> {
                // a stop phrase inside dictation is the Dictation's own; here, in a listen window, nothing is dictating
                trace("result", "ignored")
                EventLog.ev("ignored", "reason" to "stop dictation: not dictating")
                updateBadge("")
            }
        }
    }

    private fun runCommand(c: SpeechCommand, screenTargets: () -> List<Target>) {
        when (c) {
            is SpeechCommand.Phrase -> {
                if (c.text.isEmpty()) return
                resolveInput("listening", currentApp(), emptyList(), emptyList(), c.text, false, 0)
            }
            is SpeechCommand.Nav -> repeat(c.count.coerceIn(1, SwipeGrammar.MAX_COUNT)) { decideNav(c.phrase) }   // "scroll down three times"
            is SpeechCommand.Volume -> {
                val n = ++decisionCount
                val r = try { executor.setVolume(c) } catch (e: Exception) { Executor.Result(false, "error: $e") }
                EventLog.ev("exec", "n" to n, "action" to "volume", "stream" to c.stream.key, "op" to c.op.describe(), "ok" to r.ok, "how" to r.how,
                    "watch" to r.watch)
                trace("exec", JSONObject().put("action", "volume").put("stream", c.stream.key).put("op", c.op.describe()).put("ok", r.ok).put("how", r.how))
                if (!r.ok) toast("couldn't change the volume")
                updateBadge("volume")
            }
            is SpeechCommand.Swipe -> swipeNamed(c, screenTargets)
            is SpeechCommand.Ignore -> {
                // filler, chatter, a retraction: nothing to do; two commands at once: say so (never a guess)
                trace("result", "ignored")
                if (c.why.startsWith("two commands")) toast("one command at a time")
                updateBadge("")
            }
            is SpeechCommand.Tap -> tapNamed(c, screenTargets())
            is SpeechCommand.AppMissing -> {
                // never a tap on screen text of that name
                EventLog.ev("exec", "n" to ++decisionCount, "action" to "open_app", "name" to c.name, "ok" to false, "how" to "not installed")
                trace("exec", JSONObject().put("action", "open_app").put("ok", false).put("how", "not installed"))
                toast("no app called ${c.name}")
                updateBadge("no app called ${c.name}")
            }
            is SpeechCommand.OpenApp -> {
                val n = ++decisionCount
                val prefs = try { AppChoice.parsePrefer(settings.appPrefer) } catch (e: IllegalArgumentException) { emptyMap() }
                val launchable = launchableApps().map { it.pkg }.toSet()
                val pkg = (if (c.others.isEmpty()) c.pkg else AppChoice.pick(listOf(c.pkg) + c.others, recentUse(listOf(c.pkg) + c.others), prefs = prefs))
                    ?.let { AppChoice.prefer(it, prefs) { p -> p in launchable } }
                if (pkg == null) {
                    EventLog.ev("exec", "n" to n, "action" to "open_app", "label" to c.label, "ok" to false, "how" to "ambiguous: ${(listOf(c.pkg) + c.others).joinToString()}")
                    toast("which ${c.label}? " + (listOf(c.pkg) + c.others).joinToString(" or "))
                    updateBadge("which ${c.label}?")
                    return
                }
                val r = try { executor.launchApp(pkg) } catch (e: Exception) { Executor.Result(false, "error: $e") }
                EventLog.ev("exec", "n" to n, "action" to "open_app", "app" to c.pkg, "opened" to pkg.takeIf { it != c.pkg }, "label" to c.label, "ok" to r.ok, "how" to r.how, "watch" to r.watch)
                trace("exec", JSONObject().put("action", "open_app").put("app", c.pkg).put("ok", r.ok).put("how", r.how))
                if (!r.ok) toast("couldn't open ${c.label}")
                updateBadge("open ${c.label}")
            }
            is SpeechCommand.Timer -> {
                val n = ++decisionCount
                val s = c.seconds ?: run { toast("say how long: \"set a timer for 5 minutes\""); EventLog.ev("exec", "n" to n, "action" to "set_timer", "ok" to false, "how" to "no length heard"); return }
                val r = try { executor.setTimer(s, settings.timerApp) } catch (e: Exception) { Executor.Result(false, "error: $e") }
                EventLog.ev("exec", "n" to n, "action" to "set_timer", "seconds" to s, "ok" to r.ok, "how" to r.how)
                trace("exec", JSONObject().put("action", "set_timer").put("seconds", s).put("ok", r.ok).put("how", r.how))
                toast(if (r.ok) "timer: ${timerText(s)}" else "no timer set: ${r.how}")
                updateBadge("timer")
            }
        }
    }

    private fun timerText(s: Int): String = listOfNotNull(
        (s / 3600).takeIf { it > 0 }?.let { "$it h" }, (s % 3600 / 60).takeIf { it > 0 }?.let { "$it min" }, (s % 60).takeIf { it > 0 }?.let { "$it s" },
    ).joinToString(" ")

    /** A navigation phrase: the rules decide it (user phrase rules first, then the screen tie-break); never a model. */
    private fun decideNav(phrase: String) {
        val n = ++decisionCount
        val pkg = currentApp()
        val screen = try { summarize(pkg).first } catch (e: Exception) { EventLog.ev("error", "where" to "screen", "error" to e.toString()); null }
        val scene = StateBuilder.build("listening", pkg, appLabel(pkg), emptyList(), emptyList(), phrase, profile, recentActions(), null, screen)
        EventLog.ev("state", "n" to n, "text" to scene.text())
        val d = try { RuleDecider().decide(DecisionInput(scene, profile)) } catch (e: Exception) { Decision("none", "error:${e.javaClass.simpleName}") }
        act(n, generation, "listening", d, local = true)
    }

    /**
     * A spoken swipe (Swipes.kt): a finger or content direction as said, or next/previous resolved on this screen
     * ([SwipePlan]: the rules' screen tie-break, a horizontal noun, a Next/Previous button, else the rules), [count] times.
     */
    private fun swipeNamed(c: SpeechCommand.Swipe, screenTargets: () -> List<Target>) {
        val n = ++decisionCount
        var action = c.action
        var via = c.how
        if (action == null) {
            val next = c.semantic == "next"
            val kind = try { summarize(currentApp()).first.kind } catch (e: Exception) { EventLog.ev("error", "where" to "screen", "error" to e.toString()); null }
            val rtl = resources.configuration.layoutDirection == android.view.View.LAYOUT_DIRECTION_RTL
            // a Next/Previous control only matters where neither the screen type nor the noun decides
            val button = if (Vocab.SCREEN_NEXT.containsKey(kind) || c.how in SwipeGrammar.HORIZONTAL || c.how in SwipeGrammar.VERTICAL) null else pagerButton(screenTargets(), next)
            val plan = SwipePlan.semantic(next, c.how, kind, button != null, rtl)
            EventLog.ev("swipe_plan", "n" to n, "semantic" to c.semantic, "noun" to c.how, "screen" to kind, "rtl" to rtl, "via" to plan.via,
                "action" to plan.action, "button" to button?.option, "count" to c.count)
            trace("swipe_plan", JSONObject().put("via", plan.via).put("action", plan.action).put("screen", kind).put("count", c.count))
            if (plan.tapButton && button != null) { repeat(c.count) { tapTarget(n, button, "pager button") }; return }
            action = plan.action ?: return
            via = plan.via
        }
        val d = Decision(action, "grammar:swipe ($via)", explicit = true)
        repeat(c.count) { act(n, generation, "listening", d, local = true) }
    }

    /** A clear "Next" (or "Previous") control on the screen, or null. */
    private fun pagerButton(targets: List<Target>, next: Boolean): Target? {
        for (q in if (next) listOf("next", "next page") else listOf("previous", "prev", "previous page")) {
            val out = TargetMatcher.match(targets, q)
            if (out is Targets.Outcome.Tap) return out.target
        }
        return null
    }

    /** "tap the plus button": the screen's targets by name; weak or several -> highlight them (pop taps, hiss cancels). */
    private fun tapNamed(c: SpeechCommand.Tap, targets: List<Target>) {
        cancelChoice("new target phrase")
        val n = ++decisionCount
        // Every target picker (this matcher, the local model, the cloud) gets the same cleaned query; the raw one is logged.
        val query = TargetQuery.forPicker(c.query)
        val out = TargetMatcher.match(targets, query)
        EventLog.ev("target_match", "n" to n, "query" to query, "query_raw" to c.query.takeIf { it != query }, "targets" to targets.size,
            "result" to when (out) { is Targets.Outcome.Tap -> "tap"; is Targets.Outcome.Choose -> "choose"; else -> "not on screen" },
            "top" to org.json.JSONArray(TargetMatcher.rank(targets, query).take(3).map {
                JSONObject().put("option", it.target.option).put("score", Math.round(it.score * 100) / 100.0) }))
        trace("target", JSONObject().put("query", query).put("query_raw", c.query).put("targets", targets.size).put("result", when (out) {
            is Targets.Outcome.Tap -> "tap"; is Targets.Outcome.Choose -> "choose"; else -> "not on screen" }))
        when (out) {
            is Targets.Outcome.Tap -> tapTarget(n, out.target, "named")
            is Targets.Outcome.Choose -> {
                startChoice(n, out.targets)
                toast(if (out.targets.size == 1) "pop to tap \"${out.targets[0].label}\", hiss to cancel" else "rise/fall to pick, pop to tap, hiss to cancel")
            }
            is Targets.Outcome.NotOnScreen -> when {
                c.fallback != null -> runCommand(c.fallback) { targets }
                // The model decider can still find it by meaning ("the thing to write a message").
                settings.decider != "rules" && targets.isNotEmpty() -> selectTarget(query, c.query)
                else -> { toast("no \"${c.query}\" on screen"); updateBadge("not on screen") }
            }
        }
    }

    // The asr_audio / grammar debug ops (AudioFileAsr.kt): recorded clips through the live recognizer settings and grammar.
    private val fileAsr by lazy {
        AudioFileAsr(this) { ((asr as? AndroidPhraseRecognizer) ?: AndroidPhraseRecognizer(this, { false }, { settings.asrLanguage })).intent(online = false) }
    }
    private fun grammarPick(h: Heard) = PhraseGrammar.choose(h, PhraseGrammar.Context(apps = launchableApps(),
        userPhrases = profile.phraseBindings().mapNotNull { it.say }.toSet(), cursor = deviceMode == "cursor", window = true))

    // Launcher apps for "open <app>": label + aliases (AppMatcher); refreshed at most once a minute.
    private var appsCache: Pair<Long, List<AppEntry>>? = null
    private fun launchableApps(): List<AppEntry> {
        val now = SystemClock.elapsedRealtime()
        appsCache?.let { (at, list) -> if (now - at < LAUNCHER_CACHE_MS) return list }
        val list = try {
            packageManager.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), 0)
                .map { it.activityInfo.packageName to it.loadLabel(packageManager).toString() }
        } catch (e: Exception) { EventLog.ev("error", "where" to "launcher apps", "error" to e.toString()); emptyList() }
        return AppMatcher.entries(list).also { appsCache = now to it }
    }

    // --- decide and act -------------------------------------------------------------------------------------------

    private fun resolve(p: Sequencer.Pending) {
        if (mediaUnlockResolved(p)) return
        resolveInput(p.mode, p.app, p.sounds, p.sequence, null, p.waited, SystemClock.elapsedRealtime() - p.firstAt, p)
    }

    /**
     * A gesture from an open media-gate unlock (MediaGate, `media_unlock_mode`): `one` re-locks after it (it still acts),
     * `popext` takes a `pop pop` as the extension (true: consumed, no listen), `fixed` does nothing.
     */
    private fun mediaUnlockResolved(p: Sequencer.Pending): Boolean {
        if (!settings.mic.usesMic) return false
        val now = SystemClock.elapsedRealtime()
        return when (mediaGate.resolved(p.sequence, now, audio.isMusicActive)) {
            MediaGate.Resolution.NONE -> false
            MediaGate.Resolution.CLOSED -> {
                main.removeCallbacks(mediaWindowEnd)
                EventLog.ev("media_unlock", "event" to "used", "sequence" to p.sequence.joinToString(" "), "unlock_mode" to settings.mediaUnlockMode)
                updateBadge("")
                false
            }
            MediaGate.Resolution.EXTENDED -> {
                EventLog.ev("media_unlock", "event" to "extend", "window_ms" to settings.mediaUnlockMs, "unlock_mode" to settings.mediaUnlockMode)
                scheduleMediaWindowEnd()
                updateBadge("")
                true
            }
        }
    }

    private fun resolveInput(mode: String, pkg: String, sounds: List<String>, seq: List<String>, phrase: String?, waited: Boolean, heldMs: Long,
                             p: Sequencer.Pending? = null) {
        val n = ++decisionCount
        EventLog.ev("resolve", "n" to n, "sequence" to seq.joinToString(" "), "phrase" to phrase, "waited" to waited, "held_ms" to heldMs, "app" to pkg,
            "clock" to p?.clock, "ended_by" to p?.endedBy, "gaps_ms" to p?.gapsMs?.let { org.json.JSONArray(it) }, "note" to p?.note)
        val gen = generation
        val d = decider
        if (mode == "cursor" && seq == Profile.CURSOR_LISTEN && profile.cursorBindings().none { it.phrase == seq }) {
            // Not a model decision: CURSOR_ACTIONS has no listen option (schema.py), so the app owns this sequence.
            micListen(n, pkg, seq)
            act(n, gen, mode, Decision("listen_for_phrase", "app:cursor-listen", explicit = true), local = true)
            return
        }
        if (mode == "gesture" && phrase == null && Vocab.DEFAULT_BINDINGS[seq] == "listen_for_phrase" &&
                profile.appBindings(pkg).none { it.phrase == seq } && profile.globalBindings().none { it.phrase == seq } &&
                RuleDecider.notDeliberate(Scene(mode = mode, app = pkg, appName = pkg, heard = sounds, sequence = seq)) == null) {
            // The app owns the default listen gesture ("pop pop" since 2026-09-27) in every decider mode: the models were
            // trained when it was "click pop" (Vocab.DEFAULTS_TEXT), so a model must not be asked about it.
            micListen(n, pkg, seq)
            act(n, gen, mode, Decision("listen_for_phrase", "app:listen", explicit = true), local = true)
            return
        }
        if (mode == "gesture" && phrase == null && seq in Vocab.FREED_SEQUENCES &&
                profile.appBindings(pkg).none { it.phrase == seq } && profile.globalBindings().none { it.phrase == seq }) {
            // The same for the old listen gesture ("click pop", now unbound): a model trained on it would still listen.
            act(n, gen, mode, Decision("none", "app:unbound (freed ${seq.joinToString(" ")})"), local = true)
            return
        }
        if (phrase == null && MicPopGate.unbound(settings.mic.usesMic, mode, seq, userBound(pkg, seq))) {
            // A phone or USB mic's lone pop does nothing unless the user bound it (user decision 2026-09-27; MicPopGate).
            EventLog.ev("unbound", "n" to n, "sequence" to seq.joinToString(" "), "app" to pkg, "source" to MicPopGate.SOURCE)
            trace("result", "unbound: a pop from the phone mic has no default action")
            act(n, gen, mode, Decision("none", "app:unbound (phone mic pop)"), local = true)
            return
        }
        // Fast path: what the decider settles locally never reads the screen (Decider.local), so it is decided here at
        // once, without the tree walk or the worker hop. Only when nothing older is still being decided (keeps order).
        if (phrase == null && deciding.isEmpty()) {
            val quick = StateBuilder.build(mode, pkg, appLabel(pkg), sounds, seq, null, profile, recentActions(),
                if (mode == "cursor") overlay.description else null, null)
            val local = try { d.local(DecisionInput(quick, profile)) } catch (e: Exception) { null }
            if (local != null) {
                EventLog.ev("state", "n" to n, "text" to quick.text(), "screen" to "skipped (decided locally)")
                (d as? EscalatingDecider)?.cancelInFlight()
                act(n, gen, mode, local, p, local = true)
                return
            }
        }
        val screen = try { summarize(pkg).first } catch (e: Exception) { EventLog.ev("error", "where" to "screen", "error" to e.toString()); null }
        val scene = StateBuilder.build(mode, pkg, appLabel(pkg), sounds, seq, phrase, profile, recentActions(),
            if (mode == "cursor") overlay.description else null, screen)
        val input = DecisionInput(scene, profile)
        EventLog.ev("state", "n" to n, "text" to scene.text())
        deciding += n
        updateBadge("")
        trace("pending", "decider n=$n on the worker: its decision and exec events follow in the log")
        (d as? EscalatingDecider)?.submitted()   // a newer event: cancel a cloud call in flight
        worker.execute {
            val decision = try { d.decide(input) } catch (e: Exception) { Decision("none", "error:${e.javaClass.simpleName}:${e.message}") }
            main.post { act(n, gen, mode, decision, p) }
        }
    }

    /** A global or per-app rule the user wrote for [seq] (the defaults are not rules). */
    private fun userBound(pkg: String, seq: List<String>): Boolean =
        profile.appBindings(pkg).any { it.phrase == seq } || profile.globalBindings().any { it.phrase == seq }

    /** A listen window opened by pops the phone mic heard (maybe the room, not the user): logged, since it cannot act by itself. */
    private fun micListen(n: Long, pkg: String, seq: List<String>) {
        if (settings.mic.usesMic) EventLog.ev("mic_listen", "n" to n, "app" to pkg, "sequence" to seq.joinToString(" "), "source" to settings.mic.source)
    }

    private fun act(n: Long, gen: Long, mode: String, d: Decision, p: Sequencer.Pending? = null, local: Boolean = false) {
        EventLog.ev("decision", "n" to n, "action" to d.action, "source" to d.source, "confidence" to if (d.unscored) null else d.confidence,
            "ms" to d.latencyMs, "mode" to mode, "server_ms" to d.serverMs, "top" to d.top.takeIf { it.isNotEmpty() }?.let(::topJson),
            "unscored" to if (d.unscored) true else null, "path" to if (local) "local" else "worker",
            "since_msg_ms" to SystemClock.elapsedRealtime() - lastMsgAt)
        trace("decision", JSONObject().put("n", n).put("action", d.action).put("source", d.source).put("path", if (local) "local" else "worker"))
        deciding -= n
        try {
            if (gen != generation || !armed) { EventLog.ev("ignored", "n" to n, "reason" to "disarmed while deciding"); return }
            if (p != null && MicPopGate.gates(settings.mic.usesMic, p.app, p.sequence, d.action, mode, userBound(p.app, p.sequence))) {
                // the phone mic hears the room: its pops and clicks tap only where the user bound them, and never act
                // outward in social / video apps
                EventLog.ev("gated", "n" to n, "action" to d.action, "sequence" to p.sequence.joinToString(" "), "app" to p.app, "why" to MicPopGate.WHY)
                trace("result", "gated: a ${p.sequence.joinToString(" ")} from the phone mic never ${d.action}s in ${p.app}")
                lastSwipe = null
                updateBadge("")
                return
            }
            if (Risk.needsConfirm(d)) { lastSwipe = null; askConfirm(n, gen, mode, d); return }
            perform(n, mode, d, p)
        } finally { applyBufferedHold() }
    }

    // A confirm pop gates two things ([Risk.why]): an unscored (cloud) decision for a risky action, and ALWAYS an
    // outward action ([Outward]: like, follow, share...) or a tap on an outward button, whatever decided it. The badge
    // asks ("Like? pop to confirm"); pop runs it, hiss cancels, any other sound cancels it and is handled as usual
    // (never blocks a gesture); the timeout cancels (outward: confirm_timeout_ms, else target_choose_ms).
    private class PendingConfirm(val n: Long, val gen: Long, val mode: String, val what: String, val run: () -> Unit, val timeout: Runnable)
    private var confirm: PendingConfirm? = null

    private fun askConfirm(n: Long, gen: Long, mode: String, what: String, source: String, why: String, windowMs: Long, run: () -> Unit) {
        cancelConfirm("superseded")
        val r = Runnable { cancelConfirm("timeout") }
        confirm = PendingConfirm(n, gen, mode, what, run, r)
        main.postDelayed(r, windowMs)
        EventLog.ev("confirm_ask", "n" to n, "action" to what, "source" to source, "why" to why, "window_ms" to windowMs)
        trace("result", "waiting for a confirm pop ($why)")
        updateBadge(Outward.question(what))
    }

    private fun askConfirm(n: Long, gen: Long, mode: String, d: Decision) {
        val why = Risk.why(d) ?: return
        askConfirm(n, gen, mode, d.action, d.source, why, Outward.windowMs(why, settings.outwardConfirmMs, settings.targetChooseMs)) {
            perform(n, mode, d, confirmed = true)
        }
    }

    private fun cancelConfirm(why: String) {
        val c = confirm ?: return
        confirm = null
        main.removeCallbacks(c.timeout)
        EventLog.ev("confirm_ask", "n" to c.n, "event" to "cancelled", "why" to why)
        updateBadge("cancelled")
    }

    /** True if the message was used to answer the pending confirm (pop or hiss). */
    private fun confirmInput(m: FeatureMessage): Boolean {
        val c = confirm ?: return false
        val pkg = currentApp()
        val first = m.sequence.indices.firstOrNull { i ->
            RuleDecider.notDeliberate(Scene(mode = c.mode, app = pkg, appName = pkg, heard = listOf(m.sounds.getOrNull(i) ?: ""),
                sequence = listOf(m.sequence[i]))) == null
        }?.let { m.sequence[it] } ?: return false
        return when (first) {
            "pop" -> {
                if (MicPopGate.gatesConfirm(settings.mic.usesMic, pkg, c.what)) {
                    EventLog.ev("gated", "n" to c.n, "action" to c.what, "sequence" to "pop", "app" to pkg, "why" to MicPopGate.WHY, "confirm" to true)
                    cancelConfirm("gated: ${MicPopGate.WHY}")
                    return true
                }
                confirm = null; main.removeCallbacks(c.timeout)
                EventLog.ev("confirm_ask", "n" to c.n, "event" to "confirmed", "action" to c.what)
                if (c.gen == generation && armed) c.run()
                true
            }
            "hiss" -> { cancelConfirm("hiss"); true }
            else -> { cancelConfirm("other sound: $first"); false }
        }
    }

    private fun perform(n: Long, mode: String, d: Decision, p: Sequencer.Pending? = null, confirmed: Boolean = false) {
        // the voice joystick: a pop's click on an outward button ("Like", "Follow", "Send") asks first, like a named target
        if (!confirmed && d.action == "click" && mode == "cursor") joy?.outwardUnderCursor()?.let { label ->
            askConfirm(n, generation, mode, "tap $label", "joystick", "outward button", settings.outwardConfirmMs) { perform(n, mode, d, p, confirmed = true) }
            return
        }
        val t0 = SystemClock.elapsedRealtime()
        val r = try { executor.perform(d.action, mode, confirmed) } catch (e: Exception) { Executor.Result(false, "error: $e") }
        // prep_ms: main-thread time up to the dispatch call (the Confirmer's before-fingerprint included).
        EventLog.ev("exec", "n" to n, "action" to d.action, "ok" to r.ok, "how" to r.how, "watch" to r.watch,
            "prep_ms" to SystemClock.elapsedRealtime() - t0)
        trace("exec", JSONObject().put("action", d.action).put("ok", r.ok).put("how", r.how).put("prep_ms", SystemClock.elapsedRealtime() - t0))
        lastSwipe = if (r.ok && p != null && p.sequence.size == 1 && d.action in HoldScrollTrigger.DIRECTIONS)
            HoldScrollTrigger.Swipe(n, d.action, p.app, mode, p.stamps.lastOrNull(), p.firstAt) else null
        if (d.action != "none" && r.ok) {
            recent.addLast(d.action to SystemClock.elapsedRealtime())
            while (recent.size > 3) recent.removeFirst()
        }
        updateBadge(d.action)
        // a `none` shrugs (IGNORED), at most once per 2.5 s; anything else plays its action's one-shot
        BadgeStates.forDecision(d.action, r.ok)
            ?.takeIf { it != BadgeState.IGNORED || ignoredGate.admit(SystemClock.elapsedRealtime()) }
            ?.let { try { overlay.badgePlayOnce(it) } catch (_: Exception) {} }
    }

    private fun topJson(top: List<Pair<String, Double>>): org.json.JSONArray =
        org.json.JSONArray(top.map { (o, p) -> JSONObject().put("option", o).put("p", p) })

    private fun toast(text: String) {
        EventLog.ev("toast", "text" to text)
        try { android.widget.Toast.makeText(this, text, android.widget.Toast.LENGTH_SHORT).show() } catch (_: Exception) {}
    }

    // --- intent cursor mode -----------------------------------------------------------------------------------------

    /** The phrase after "pop pop" in cursor mode names an on-screen element: build the options and ask the model. */
    private fun selectTarget(utterance: String, raw: String = utterance) {
        cancelChoice("new target phrase")
        val n = ++decisionCount
        val pkg = currentApp()
        refreshOptionFormat()
        val targets = Targets.build(TreeReader.targetLayers(this), screenW(), screenH(), format = optionFormat)
        val screen = try { summarize(pkg).first } catch (e: Exception) { ScreenContext("other", "none", "not scrollable", "hidden") }
        // The local model and the cloud see the cleaned query (TargetQuery); the log keeps what was heard.
        val query = TargetQuery.forPicker(utterance)
        val state = Targets.stateText(StateBuilder.appName(pkg, appLabel(pkg)), pkg, screen, query)
        val options = Targets.options(targets)
        EventLog.ev("target_state", "n" to n, "app" to pkg, "text" to state, "query_raw" to raw.takeIf { it != query },
            "options" to org.json.JSONArray(options))
        if (targets.isEmpty()) { toast("nothing to tap on this screen"); EventLog.ev("target", "n" to n, "result" to "no targets"); return }
        if (settings.decider == "rules") {
            toast("naming a target needs the model decider")
            EventLog.ev("target", "n" to n, "result" to "no model (decider=rules)"); return
        }
        val client = SystemOneClient(settings.baseUrl, settings.targetModel.ifBlank { settings.model }, { settings.apiKey }, settings.httpTimeoutMs)
        val esc = decider as? EscalatingDecider
        esc?.submitted()
        val gen = generation
        updateBadge("naming...")
        worker.execute {
            val res = try { Result.success(esc?.pickTarget(state, options) ?: client.choice(state, "target", TargetVocab.POLICY, options)) }
                catch (e: Exception) { Result.failure(e) }
            main.post { onTargetAnswer(n, gen, targets, res) }
        }
    }

    private fun onTargetAnswer(n: Long, gen: Long, targets: List<Target>, res: Result<ChoiceAnswer>) {
        val a = res.getOrElse { e ->
            EventLog.ev("target_decision", "n" to n, "error" to "${e.javaClass.simpleName}: ${e.message?.take(160)}")
            toast("couldn't pick a target"); updateBadge("target failed"); return
        }
        EventLog.ev("target_decision", "n" to n, "choice" to a.choice, "confidence" to if (a.unscored) null else a.confidence,
            "top" to topJson(a.top(3)), "ms" to a.ms, "server_ms" to a.serverMs, "min_confidence" to settings.targetMinConfidence,
            "unscored" to if (a.unscored) true else null)
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

    /** A tap on a named screen target; an outward button ("Like", "Follow", "Send") waits for a confirm pop first. */
    private fun tapTarget(n: Long, t: Target, why: String, confirmed: Boolean = false) {
        if (!confirmed && Outward.isOutwardTarget(t.label)) {
            askConfirm(n, generation, deviceMode, "tap ${t.label}", "target", "outward button", settings.outwardConfirmMs) {
                tapTarget(n, t, why, confirmed = true)
            }
            return
        }
        val r = try { executor.tapTarget(t, confirmed) } catch (e: Exception) { Executor.Result(false, "error: $e") }
        EventLog.ev("target", "n" to n, "result" to "tap", "why" to why, "option" to t.option, "x" to t.cx, "y" to t.cy,
            "ok" to r.ok, "how" to r.how, "watch" to r.watch)
        trace("exec", JSONObject().put("action", "tap_target").put("option", t.option).put("ok", r.ok).put("how", r.how))
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
        if (why != null) cancelConfirm(why)
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

    /** Recompute the Canti head's held state ([BadgeStates]); [last] is kept for callers' readability only. */
    @Suppress("UNUSED_PARAMETER")
    private fun updateBadge(last: String) {
        val s = badgeState()
        try { overlay.setBadgeState(s) } catch (_: Exception) {}
        // The app's header mirrors the held state (../ui): one event per change.
        if (s != lastBadge) { lastBadge = s; EventLog.ev("badge", "event" to "state", "state" to BadgeStates.label(s)) }
    }
    private var lastBadge: BadgeState? = null
    private val ignoredGate = IgnoredGate()

    // While one of Canti's own screens (MainActivity, LegacySettings, SourceChooser) is resumed, the floating head is
    // tucked away: the app's header shows it there. Process-wide activity callbacks (same process as the screens);
    // debounced so moving between Canti screens does not make it hop out and back.
    private val resumedScreens = java.util.Collections.newSetFromMap(java.util.IdentityHashMap<android.app.Activity, Boolean>())
    private val tuckCheck = Runnable { try { overlay.tuckBadge(resumedScreens.isNotEmpty()) } catch (e: Exception) { EventLog.ev("error", "where" to "badge tuck", "error" to e.toString()) } }
    private fun screensChanged() { main.removeCallbacks(tuckCheck); main.postDelayed(tuckCheck, TUCK_DEBOUNCE_MS) }
    private val screenCallbacks = object : android.app.Application.ActivityLifecycleCallbacks {
        override fun onActivityResumed(a: android.app.Activity) { resumedScreens += a; screensChanged() }
        override fun onActivityPaused(a: android.app.Activity) { resumedScreens -= a; screensChanged() }
        override fun onActivityDestroyed(a: android.app.Activity) { if (resumedScreens.remove(a)) screensChanged() }
        override fun onActivityCreated(a: android.app.Activity, b: android.os.Bundle?) {}
        override fun onActivityStarted(a: android.app.Activity) {}
        override fun onActivityStopped(a: android.app.Activity) {}
        override fun onActivitySaveInstanceState(a: android.app.Activity, b: android.os.Bundle) {}
    }

    private fun badgeState(): BadgeState = BadgeStates.held(BadgeStates.Inputs(
        armed = armed, paused = paused, mode = deviceMode, holdScrolling = holdScroll.active,
        pending = sequencer.isWaiting || deciding.isNotEmpty() || confirm != null || choice != null,
        // dictating shows the same listening face (no new art)
        listening = ::listenWindow.isInitialized && (listenWindow.isOpen || dictation.active),
        sourceError = settings.mic.usesMic && mic?.state?.startsWith("mic error") == true,
        wakeable = deviceWakeable(),
        mediaUnlocked = ::mediaGate.isInitialized && settings.mic.usesMic && mediaGate.isOpen(SystemClock.elapsedRealtime()),
    ))

    // --- media gate (MediaGate.kt) ----------------------------------------------------------------------------------

    /** The phone / USB mic source (and its debug feed); never the Pico or the debug socket. */
    private fun isMicSource(source: String) = MediaGate.appliesTo(source)

    /** Media is playing, the gate is on and no unlock window is open. */
    private fun mediaLocked(now: Long) = mediaGate.active(audio.isMusicActive) && !mediaGate.isOpen(now)

    /** True if the gate took this message (dropped it, or it was half or all of the unlock). */
    private fun mediaGateDrops(m: FeatureMessage, source: String): Boolean {
        if (!isMicSource(source) || m.sequence.isEmpty()) return false
        val now = SystemClock.elapsedRealtime()
        val playing = audio.isMusicActive
        var took = false
        for ((i, kind) in m.sequence.withIndex()) {
            val st = m.timing?.getOrNull(i)
            val v = mediaGate.onSound(kind, st?.startMs ?: now, st?.endMs ?: now, now, playing)
            if (v == MediaGate.Verdict.PASS) continue
            took = true
            EventLog.ev("media_gate", "kind" to kind, "source" to settings.mic.source, "dropped" to true,
                "unlock" to when (v) { MediaGate.Verdict.FIRST_POP -> "1/2"; MediaGate.Verdict.UNLOCK -> "2/2"; else -> null })
            if (v == MediaGate.Verdict.UNLOCK) {
                EventLog.ev("media_unlock", "event" to "open", "window_ms" to settings.mediaUnlockMs, "unlock_mode" to settings.mediaUnlockMode, "mode" to deviceMode, "app" to lastPkg)
                scheduleMediaWindowEnd()
                updateBadge("unlocked")
            }
        }
        return took
    }

    private val mediaWindowEnd = Runnable {
        val now = SystemClock.elapsedRealtime()
        if (mediaGate.isOpen(now)) { scheduleMediaWindowEnd(); return@Runnable }
        EventLog.ev("media_unlock", "event" to "expired")
        updateBadge("")
    }

    private fun scheduleMediaWindowEnd() {
        main.removeCallbacks(mediaWindowEnd)
        main.postDelayed(mediaWindowEnd, mediaGate.leftMs(SystemClock.elapsedRealtime()).coerceAtLeast(1))
    }

    /** Playback started or stopped somewhere: media stopping lifts the gate (and ends a window) at once. */
    private fun mediaCheck() {
        if (!::mediaGate.isInitialized) return
        if (mediaGate.mediaChanged(SystemClock.elapsedRealtime(), audio.isMusicActive)) {
            main.removeCallbacks(mediaWindowEnd)
            EventLog.ev("media_unlock", "event" to "lifted", "why" to "media stopped")
            updateBadge("")
        }
    }

    // isMusicActive can trail the playback callback by a moment: check at once and again shortly after.
    private val mediaRecheck = Runnable { mediaCheck() }
    private val playbackWatch = object : AudioManager.AudioPlaybackCallback() {
        override fun onPlaybackConfigChanged(configs: MutableList<android.media.AudioPlaybackConfiguration>?) {
            mediaCheck()
            main.removeCallbacks(mediaRecheck); main.postDelayed(mediaRecheck, 750)
        }
    }

    /** The head's tap menu: mode and pause through the same paths as the UI; the source through audio.SoundSource. */
    private val badgeActions = object : BadgeActions {
        override val mode get() = deviceMode
        override val paused get() = this@VoxService.paused
        override val source get() = ai.vox.companion.audio.SoundSource.get(this@VoxService)
        override fun setMode(mode: String) { if (mode != deviceMode) toggleMode("badge") }
        override fun setPaused(p: Boolean) = this@VoxService.setPaused(p, "badge")
        override val wakeable get() = deviceWakeable()
        override fun wake() = wakeDevice("badge")
        override val joystick get() = joy?.on == true
        override fun recentre() { joy?.recentre("badge") }
        override fun calibrate() { Pairing.openRoute(this@VoxService, Pairing.ROUTE_CALIBRATE, "badge") }
        override fun setSource(src: String) {
            if (!ai.vox.companion.audio.SoundSource.set(this@VoxService, src, "badge")) ai.vox.companion.audio.SoundSource.choose(this@VoxService)
            // The Pico with no device remembered: the first-run pairing screen.
            else if (src == ai.vox.companion.audio.SoundSource.PICO) Pairing.openIfNoDevice(this@VoxService, "badge")
        }
    }
    private val sourceListener = ai.vox.companion.audio.SoundSource.Listener { updateBadge("") }

    override fun onConfigurationChanged(newConfig: android.content.res.Configuration) {
        super.onConfigurationChanged(newConfig)
        if (instance == null) return
        // Rotation or fold: the head goes to its remembered place for the new orientation.
        main.post { try { overlay.hideMenu(); overlay.placeBadge(); joy?.screenChanged() } catch (_: Exception) {} }
    }

    // --- app and screen -------------------------------------------------------------------------------------------

    // The system dialog in front ([SystemDialog]), read from the window list; cached 100 ms (asked before every touch).
    private var dialogAt = 0L
    private var dialogSeen: String? = null
    private fun systemDialog(): String? {
        val now = SystemClock.elapsedRealtime()
        if (now - dialogAt < 100) return dialogSeen
        val ws = try { windows } catch (_: Exception) { emptyList() }
        dialogSeen = SystemDialog.detect(ws.map { w ->
            val kind = when (w.type) {
                android.view.accessibility.AccessibilityWindowInfo.TYPE_APPLICATION -> SystemDialog.Kind.APPLICATION
                android.view.accessibility.AccessibilityWindowInfo.TYPE_SYSTEM -> SystemDialog.Kind.SYSTEM
                else -> SystemDialog.Kind.OTHER
            }
            SystemDialog.Win(kind, if (kind == SystemDialog.Kind.OTHER) null else try { w.root?.packageName?.toString() } catch (_: Exception) { null }, w.layer)
        }, packageName)
        dialogAt = now
        return dialogSeen
    }

    /** Last-used times of [pkgs], only when usage access is already granted (Canti never asks for it); else null. */
    private fun recentUse(pkgs: List<String>): Map<String, Long>? = try {
        val ops = getSystemService(Context.APP_OPS_SERVICE) as android.app.AppOpsManager
        @Suppress("DEPRECATION")
        val mode = ops.checkOpNoThrow(android.app.AppOpsManager.OPSTR_GET_USAGE_STATS, android.os.Process.myUid(), packageName)
        if (mode != android.app.AppOpsManager.MODE_ALLOWED) null else {
            val us = getSystemService(Context.USAGE_STATS_SERVICE) as android.app.usage.UsageStatsManager
            val now = System.currentTimeMillis()
            val stats = us.queryAndAggregateUsageStats(now - 30L * 86_400_000L, now)
            pkgs.associateWith { stats[it]?.lastTimeUsed ?: 0L }
        }
    } catch (_: Exception) { null }

    private fun currentApp(): String = MainLoad.time("tree:current_app") {
        TreeReader.appPackage(this) ?: lastPkg   // no tree read once the window is known (ForegroundApp)
    }

    /**
     * Main-thread lag: a tick every [HEARTBEAT_MS] while armed (1 s otherwise); how late it runs is time the main
     * thread was busy with something else (`main_load` op: `main:lag`).
     */
    private var beatDue = 0L
    private val heartbeat: Runnable = object : Runnable {
        override fun run() {
            val now = SystemClock.uptimeMillis()
            if (beatDue > 0 && armed) MainLoad.done("main:lag", (now - beatDue).coerceAtLeast(0).toDouble())
            val next = if (armed) HEARTBEAT_MS else 1000L
            beatDue = now + next
            if (instance != null) main.postDelayed(this, next)
        }
    }

    private fun appLabel(pkg: String): String? = labelCache.getOrPut(pkg) {
        try { packageManager.getApplicationLabel(packageManager.getApplicationInfo(pkg, 0)).toString() } catch (e: Exception) { pkg }
    }

    // The home apps rarely change: a package-manager query per decision was main-thread time for nothing.
    private var launcherCache: Pair<Long, Set<String>>? = null
    private fun launchers(): Set<String> {
        val now = SystemClock.elapsedRealtime()
        launcherCache?.let { (at, set) -> if (now - at < LAUNCHER_CACHE_MS) return set }
        val set = packageManager.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME), PackageManager.MATCH_DEFAULT_ONLY)
            .map { it.activityInfo.packageName }.toSet()
        launcherCache = now to set
        return set
    }

    /** Screen line + raw summary for the current app window. */
    fun summarize(pkg: String = currentApp()): Pair<ScreenContext, JSONObject> = MainLoad.time("tree:summarize") { summarizeNow(pkg) }

    private fun summarizeNow(pkg: String): Pair<ScreenContext, JSONObject> {
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

    // [train] The store is per profile AND sound source (files/enroll/<profile>@<source>.json); the old profile-only
    // file becomes the store of the source current when it is first loaded.
    private fun loadEnrollment() {
        val src = settings.mic.source
        enroll = try { loadStore(src, fresh = true) } catch (e: Exception) {
            EventLog.ev("error", "where" to "enrollment", "profile" to profile.name, "source" to src, "error" to e.toString()); EnrollmentStore(profile.name, src)
        }
        rebuildMatcher()
    }

    /** [train] The store of [src] for the active profile: the live one for the current source, else read from its file. */
    private fun loadStore(src: String, fresh: Boolean = false): EnrollmentStore {
        if (!fresh && src == enroll.source && profile.name == enroll.profile) return enroll
        return EnrollmentStore.load(filesDir, profile.name, src) { from, to ->
            EventLog.ev("enroll", "change" to "migrate", "profile" to profile.name, "source" to src, "from" to from.name, "to" to to.name)
        }
    }

    /** [train] Changes and persists [src]'s store (the current source's through [changeEnrollment], matcher included). */
    private fun changeStore(src: String, what: String, change: (EnrollmentStore) -> Unit) {
        require(src in EnrollmentStore.SOURCES) { "source must be one of ${EnrollmentStore.SOURCES}" }
        if (src == enroll.source) { changeEnrollment(what) { change(enroll) }; return }
        val st = loadStore(src)
        change(st)
        EnrollmentStore.save(filesDir, st)
        EventLog.ev("enroll", "change" to what, "profile" to st.profile, "source" to src, "classes" to st.classes.size,
            "examples" to st.classes.sumOf { it.examples.size })
    }

    /** [train] What the gesture trainer needs from the service (main thread). */
    private fun trainHost(scheduler: Scheduler) = object : TrainHost, Scheduler by scheduler {
        override fun source() = settings.mic.source
        override fun blocker(): String? = when {
            paused -> "Canti is paused: resume it first."
            !armed -> "Canti is not listening (the device is paused or asleep): resume it first."
            deviceMode == "cursor" -> "Canti is in cursor mode: switch to gesture mode to train gestures."
            settings.mic.usesMic && mic?.state != "listening" -> "The mic is not listening (${mic?.state ?: "off"})."
            !settings.mic.usesMic && ble?.link?.ready != true -> "The Canti device is not connected."
            else -> null
        }
        override fun liveTrace() = settings.mic.usesMic && mic != null
        override fun ticks(on: Boolean) {
            val m = mic ?: return
            m.trainTickSink = if (!on) null else { rows, n, _ ->
                val copy = rows.copyOf(n * ai.vox.companion.audio.VxNative.TICK_COLS)
                main.post {
                    val cols = ai.vox.companion.audio.VxNative.TICK_COLS
                    for (i in 0 until n) {
                        val o = i * cols
                        val voiced = copy[o + ai.vox.companion.audio.VxNative.TICK_VOICED] > 0.5
                        train?.onTick(if (voiced) copy[o + ai.vox.companion.audio.VxNative.TICK_F0] else null, copy[o + ai.vox.companion.audio.VxNative.TICK_DB])
                    }
                }
            }
            m.setTrainTicks(on)
        }
        override fun profile() = profile.name
        override fun store(source: String) = loadStore(source)
        override fun change(source: String, what: String, change: (EnrollmentStore) -> Unit) = changeStore(source, what, change)
        override fun wallMs() = System.currentTimeMillis()
        override fun log(vararg fields: Pair<String, Any?>) { EventLog.ev("train", *fields) }
        override fun push(status: Map<String, Any?>) { trainSink?.invoke(status) }
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

    /** [train] The store of [src] (default: the current sound source's, the one matching uses). */
    private fun enrollSummary(src: String = settings.mic.source): JSONObject {
        val st = loadStore(src)
        val mt = if (st === enroll) matcher else Matcher(st, settings.enrollRejectMult, floors)
        val th = mt?.thresholds() ?: emptyMap()
        return JSONObject().put("profile", st.profile).put("source", src).put("file", EnrollmentStore.file(filesDir, st.profile, src).name)
            .put("fp_version", st.fpVersion ?: JSONObject.NULL).put("dim", st.dim ?: JSONObject.NULL)
            .put("reject_mult", settings.enrollRejectMult).put("floors", mt?.floorStatus ?: JSONObject.NULL)
            .put("classes", org.json.JSONArray(st.classes.map { c ->
                JSONObject().put("kind", c.kind).put("name", c.name).put("examples", c.examples.size).put("active", c.active)
                    .put("contour", c.contour).put("threshold", th[c.name]?.first?.let(::r4) ?: JSONObject.NULL)
                    .put("dtw_threshold", th[c.name]?.second?.let(::r4) ?: JSONObject.NULL)
            }))
    }

    /** Apply an enrollment change and persist it; on a failed save the in-memory store is reloaded from disk. */
    private fun changeEnrollment(what: String, change: () -> Unit) {
        // [train] a change of several steps (a redone training cell: delete, then add) that fails midway leaves nothing
        try { change() } catch (e: IllegalArgumentException) { loadEnrollment(); throw e }
        try { EnrollmentStore.save(filesDir, enroll) } catch (e: Exception) { loadEnrollment(); throw IllegalArgumentException("save failed: $e") }
        rebuildMatcher()
        EventLog.ev("enroll", "change" to what, "profile" to enroll.profile, "source" to enroll.source, "classes" to enroll.classes.size,
            "examples" to enroll.classes.sumOf { it.examples.size })
    }

    // The target option format the local model was trained on (OptionFormat): v1 until its /health declares v2. Read off
    // the main thread when the decider is rebuilt and again when older than OPTION_FORMAT_MAX_AGE_MS; v1 meanwhile.
    @Volatile private var optionFormat = OptionFormat.V1
    @Volatile private var optionFormatAt = 0L
    private fun refreshOptionFormat(maxAgeMs: Long = OPTION_FORMAT_MAX_AGE_MS) {
        val now = SystemClock.elapsedRealtime()
        if (optionFormatAt != 0L && now - optionFormatAt < maxAgeMs) return
        optionFormatAt = now
        val base = settings.baseUrl; val key = settings.apiKey
        Thread({
            val (f, why) = OptionFormat.fetch(base, key)
            EventLog.ev("option_format", "format" to f, "why" to why, "changed" to (f != optionFormat))
            optionFormat = f
        }, "vox-option-format").apply { isDaemon = true }.start()
    }

    private fun rebuildDecider() {
        val http = if (settings.decider == "rules") null else HttpDecider(settings.baseUrl, settings.model, { settings.apiKey },
            settings.httpTimeoutMs, settings.minConfidence)
        decider = if (settings.decider != "escalate") ChainDecider(settings.decider, http) else {
            // The local model is optional here (blank base URL = none); the cloud needs an endpoint and a key (or a LAN
            // Ollama with an empty key; the endpoint alone is enough then).
            val local = http.takeIf { settings.baseUrl.isNotBlank() }
            val cloud = settings.ollamaEndpoint.takeIf { it.isNotBlank() && settings.ollamaModel.isNotBlank() }?.let {
                OllamaDecider(OllamaClient(it, settings.ollamaModel, { settings.ollamaKey }), settings.ollamaTimeoutMs)
            }
            val localTarget = local?.let {
                val c = SystemOneClient(settings.baseUrl, settings.targetModel.ifBlank { settings.model }, { settings.apiKey }, settings.httpTimeoutMs)
                return@let { state: String, options: List<String> -> c.choice(state, "target", TargetVocab.POLICY, options) }
            }
            EscalatingDecider(cloud, local, localTarget, settings.ollamaTargetTimeoutMs)
        }
        refreshOptionFormat(0)
    }

    private fun control(m: JSONObject): JSONObject {
        val op = m.getString("op")
        val reply = JSONObject().put("ok", true).put("op", op)
        when (op) {
            "main_load" -> {
                // Where the main thread spends its time (MainLoad.kt): sections by total time; `reset: true` starts over.
                reply.put("sections", JSONObject(MainLoad.stats.snapshot().mapValues { JSONObject(it.value) }))
                if (m.optBoolean("reset")) MainLoad.stats.reset()
            }
            // the voice joystick (VoiceJoystick): its state, recentre, and the calibration commands (the UI's calib_*)
            // a harvest hides the head around its screencap (Overlay.hideForCapture); it comes back by itself after `ms`
            "badge_hide" -> {
                val hide = m.optBoolean("hide", true)
                overlay.hideForCapture(hide, m.optLong("ms", 10_000L).coerceIn(500L, 60_000L))
                reply.put("hidden", hide)
            }
            "joy_state" -> reply.put("joystick", joy?.describe() ?: JSONObject.NULL)
            "joy_recentre" -> { joy?.recentre("ctl"); reply.put("joystick", joy?.describe() ?: JSONObject.NULL) }
            "calib_start", "calib_step", "calib_redo", "calib_retry", "calib_skip", "calib_save", "calib_cancel", "calib_status", "calib_get" -> {
                val args = m.keys().asSequence().filter { it != "op" && it != "type" }.associateWith { m.get(it) as Any? }
                val r = (joy ?: throw IllegalArgumentException("the joystick did not start")).calibCommand(op, args)
                reply.put("calib", r?.let { JSONObject(it) } ?: JSONObject.NULL)
                (r?.get("error") as? String)?.let { reply.put("ok", false).put("error", it) }
            }
            "ping" -> reply.put("app", currentApp()).put("mode", deviceMode).put("armed", armed).put("paused", paused)
                .put("waiting", sequencer.isWaiting).put("settings", settings.describe()).put("vocab", Vocab.SOURCE_DIGEST)
                .put("decisions", decisionCount).put("device", ble?.link?.status() ?: JSONObject.NULL)   // the Pico's own armed/mode (null: no BLE link)
                .put("media_lock", JSONObject().put("on", settings.mediaLock).put("mode", settings.mediaUnlockMode).put("media_playing", audio.isMusicActive)
                    .put("locked", settings.mic.usesMic && mediaLocked(SystemClock.elapsedRealtime()))
                    .put("unlock_left_ms", mediaGate.leftMs(SystemClock.elapsedRealtime())))
            "config" -> { settings.apply(m); mediaCheck(); rebuildDecider(); rebuildMatcher(); soundSourceChanged(); rebuildAsr(); if (m.has("asr_allow_online") || m.has("asr_language")) checkAsr("config"); reply.put("settings", settings.describe()) }   // [phone-mic] soundSourceChanged
            "enroll_add" -> {
                // {kind, name, examples: [{fp, fp_version, pitch16, meta?}], source?} for the active profile on the
                // current sound source, or on `source` ([train] per-source stores).
                val ex = m.getJSONArray("examples")
                val feats = List(ex.length()) { SoundFeatures.parse(ex.getJSONObject(it), "examples[$it]") }
                val kind = m.getString("kind"); val name = m.getString("name")
                val src = m.optString("source").ifEmpty { settings.mic.source }
                changeStore(src, "add $kind '$name' +${feats.size}") { it.add(kind, name, feats) }
                reply.put("enrollment", enrollSummary(src))
            }
            "enroll_list" -> reply.put("enrollment", enrollSummary(m.optString("source").ifEmpty { settings.mic.source }))
            // [train] gesture training (GestureTraining.kt): the UI channel's train_* methods, same args and reply
            "train_status", "train_start", "train_record", "train_retry", "train_skip", "train_keep", "train_next", "train_cancel", "train_delete" -> {
                val args = m.keys().asSequence().filter { it != "op" && it != "type" }.associateWith { m.get(it) as Any? }
                val r = (train ?: throw IllegalArgumentException("gesture training did not start")).command(op, args)
                reply.put("train", trainJson(r))
                (r["error"] as? String)?.let { reply.put("ok", false).put("error", it) }
            }
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
            // [phone-mic] the phone/USB mic source: status, live level, and feeding PCM through the JNI extractor
            "mic_status", "mic_level", "mic_feed" ->
                reply.put("mic", (mic ?: throw IllegalArgumentException("mic source not running")).control(op, m))
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
                // {name, index?} deletes a class or one example; {all: true} clears the store (the current source's, or
                // `source`'s: [train] per-source stores).
                val src = m.optString("source").ifEmpty { settings.mic.source }
                if (m.optBoolean("all")) changeStore(src, "clear") { it.clear() }
                else {
                    val name = m.getString("name"); val idx = if (m.has("index")) m.getInt("index") else null
                    var found = false
                    changeStore(src, "delete '$name'${idx?.let { " #$it" } ?: ""}") { found = it.delete(name, idx) }
                    reply.put("deleted", found)
                }
                reply.put("enrollment", enrollSummary(src))
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
                if (m.optBoolean("raw")) {
                    reply.put("package", currentApp()).put("window", root?.packageName?.toString() ?: "").put("raw", TreeReader.rawDump(root))
                    return reply
                }
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
                val layers = TreeReader.targetLayers(this)
                val fmt = optionFormat
                val targets = Targets.build(layers, screenW(), screenH(), format = fmt)
                val (ctx, _) = summarize(pkg)
                // app_name + state_template (additive fields): the exact "target" question state the app would send,
                // with {UTTERANCE} where the spoken phrase goes (real-screen test set, finetune/data/real-targets-v1).
                val appName = StateBuilder.appName(pkg, appLabel(pkg))
                reply.put("app_name", appName).put("state_template", Targets.stateText(appName, pkg, ctx, "{UTTERANCE}"))
                reply.put("package", pkg).put("screen_text", ctx.text()).put("option_format", fmt).put("options", org.json.JSONArray(Targets.options(targets)))
                    .put("targets", org.json.JSONArray(targets.map(Targets::json)))
                // options_v1 / targets_v1, options_v2 / targets_v2: every format of the same windows (harvest training text).
                Targets.allFormats(layers, screenW(), screenH()).let { all -> all.keys().forEach { k -> reply.put(k, all.get(k)) } }
            }
            "asr" -> {
                // The recognizer's state; `check`: ask again about the offline pack (the answer lands in the log and the UI).
                (asr as? AndroidPhraseRecognizer)?.let { a -> reply.put("asr", JSONObject(a.describe())); if (m.optBoolean("check")) checkAsr("op") }
                reply.put("engine", asr.name).put("status", asrStatus()).put("window_open", listenWindow.isOpen)
            }
            "listen" -> { openListening(); reply.put("engine", asr.name) }
            // A recorded clip through the on-device recognizer with the live settings, never online (AudioFileAsr.kt):
            // {wav_b64} -> {id}; poll asr_audio_result {id}. grammar {texts}: each text's parse, no screen read, no action.
            "asr_audio" -> {
                check(!listenWindow.isOpen) { "asr_audio: a phrase window is open" }
                reply.put("id", fileAsr.start(AsrAudioArgs.audio(m)) { h -> AsrAudioArgs.pick(grammarPick(h)) })
            }
            "asr_audio_result" -> fileAsr.result(AsrAudioArgs.id(m)).let { r -> r.keys().forEach { k -> reply.put(k, r.get(k)) } }
            "grammar" -> reply.put("results", org.json.JSONArray(AsrAudioArgs.texts(m).map { AsrAudioArgs.pick(grammarPick(Heard(listOf(it)))) }))
            "heard", "phrase" -> {
                // A recognizer result without a microphone (tests): the n-best goes through the grammar like a real one,
                // then the decider and the executor. `phrase`: {"text": "...", "nbest": [...]} and the reply carries what
                // happened (parse, decision, exec, timings); a decision on the worker (the model decider) arrives later
                // in the log ("pending"). `heard`: {"hypotheses": [...]} (older form, same path).
                val hyps = ArrayList<String>()
                m.optString("text").takeIf { it.isNotBlank() }?.let { hyps += it }
                (m.optJSONArray("nbest") ?: m.optJSONArray("hypotheses"))?.let { a -> for (i in 0 until a.length()) a.getString(i).let { if (it !in hyps) hyps += it } }
                require(hyps.isNotEmpty()) { "phrase: give text or nbest" }
                listenWindow.cancel("$op op")
                val t0 = SystemClock.elapsedRealtime()
                val tr = JSONObject()
                trace = tr
                try { onHeard(Heard(hyps), "op:$op", window = m.optBoolean("window", true)) } finally { trace = null }
                tr.put("total_ms", SystemClock.elapsedRealtime() - t0).put("armed", armed).put("mode", deviceMode)
                reply.put("result", tr)
            }
            "reset" -> {
                generation++; sequencer.cancel(); sequencer.resetClock(); holdScroll.stop("reset"); dropBufferedHold(); lastSwipe = null; overlay.stop(); executor.cancelDrag(); listenWindow.cancel("reset"); dictation.stop("reset"); recent.clear()
                cancelChoice("reset")
                lastMsgId = null; armed = true; paused = false
                if (m.optBoolean("clear_log")) EventLog.clear()
                if (m.optBoolean("clear_harvest")) EventLog.clearHarvest()
                EventLog.ev("reset")
                updateBadge("reset")
                mic?.refresh("reset")   // [phone-mic]
            }
            else -> throw IllegalArgumentException("unknown control op '$op'")
        }
        return reply
    }
}
