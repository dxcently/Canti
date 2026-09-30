package ai.vox.companion

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Context
import android.content.Intent
import android.graphics.Path
import android.media.AudioManager
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.provider.MediaStore
import android.view.KeyEvent
import android.view.WindowInsets
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo
import java.util.concurrent.Executors

/**
 * Performs an action key from ACTIONS / CURSOR_ACTIONS. Gestures via dispatchGesture, navigation via
 * performGlobalAction, media/volume via AudioManager. Every screen-changing action is registered with the
 * [Confirmer] before dispatch.
 *
 * Geometry (fractions of the screen) keeps strokes away from the edges, where gesture navigation would take them:
 * swipes are flings over 60-70% of the screen in 100 ms ([SwipeGeometry]), clamped out of the system gesture insets,
 * except a vertical swipe in an ordinary list, which is a no-momentum step ([ScrollStep]).
 * "forward" (no global action on Android) clicks a Forward control, looking in the overflow menu if needed ([Forward]).
 */
class Executor(
    private val svc: AccessibilityService,
    private val overlay: Overlay,
    private val confirmer: Confirmer,
    private val screenW: () -> Int,
    private val screenH: () -> Int,
    private val onListen: () -> Unit,
) {
    data class Result(val ok: Boolean, val how: String, val watch: Long? = null)

    private val audio = svc.getSystemService(Context.AUDIO_SERVICE) as AudioManager
    private var dragStart: Pair<Float, Float>? = null
    private val main = Handler(Looper.getMainLooper())

    /** [confirmed]: a confirm pop answered it; an outward action ([Outward]) is refused without one. */
    fun perform(action: String, mode: String, confirmed: Boolean = false): Result {
        if (!Outward.mayDispatch(action, confirmed)) return Result(false, "refused: $action is outward and needs a confirm pop")
        if (!SystemDialog.allows(action)) dialogInFront(action)?.let { return Result(false, it) }
        val w = screenW().toFloat(); val h = screenH().toFloat()
        val cx = w / 2; val cy = h / 2
        if (mode == "cursor") cursorAction(action)?.let { return it }
        return when (action) {
            "none" -> Result(true, "nothing")
            "swipe_up", "swipe_down", "swipe_left", "swipe_right" -> swipeOrStep(action, w.toInt(), h.toInt())
            "forward" -> forward()
            "tap" -> gesture(action, tap(cx, cy), "tap(center)")
            "double_tap", "like" -> gesture(action, doubleTap(cx, cy), "double-tap(center)")
            "long_press" -> gesture(action, press(cx, cy, 1000), "long-press(center,1000ms)")
            "back" -> global(action, AccessibilityService.GLOBAL_ACTION_BACK)
            "home" -> global(action, AccessibilityService.GLOBAL_ACTION_HOME)
            "recents" -> global(action, AccessibilityService.GLOBAL_ACTION_RECENTS)
            "notifications" -> global(action, AccessibilityService.GLOBAL_ACTION_NOTIFICATIONS)
            "quick_settings" -> global(action, AccessibilityService.GLOBAL_ACTION_QUICK_SETTINGS)
            // [swipes] close the shade: dismiss on API 31+, else a Back (the shade is a window "in front").
            "close_shade" -> if (android.os.Build.VERSION.SDK_INT >= 31)
                global(action, AccessibilityService.GLOBAL_ACTION_DISMISS_NOTIFICATION_SHADE)
                else global(action, AccessibilityService.GLOBAL_ACTION_BACK)
            "pull_refresh" -> pullRefresh(action)
            "scroll_down" -> feedScroll(action, "swipe_up", w.toInt(), h.toInt()) ?: scroll(action, forward = true) ?: gesture(action, swipe(cx, h * 0.62f, cx, h * 0.42f, 300), "short-swipe")
            "scroll_up" -> feedScroll(action, "swipe_down", w.toInt(), h.toInt()) ?: scroll(action, forward = false) ?: gesture(action, swipe(cx, h * 0.42f, cx, h * 0.62f, 300), "short-swipe")
            "zoom_in" -> gesture(action, pinch(cx, cy, w * 0.08f, w * 0.30f), "pinch-out")
            "zoom_out" -> gesture(action, pinch(cx, cy, w * 0.30f, w * 0.08f), "pinch-in")
            // on a paged feed the next / previous item is the next / previous page (the screen line may not have said "video feed")
            "next_item" -> feedScroll(action, "swipe_up", w.toInt(), h.toInt()) ?: mediaKey(action, KeyEvent.KEYCODE_MEDIA_NEXT)
            "previous_item" -> feedScroll(action, "swipe_down", w.toInt(), h.toInt()) ?: mediaKey(action, KeyEvent.KEYCODE_MEDIA_PREVIOUS)
            "play_pause" -> mediaKey(action, KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE)
            "volume_up" -> volume(action, AudioManager.ADJUST_RAISE)
            "volume_down" -> volume(action, AudioManager.ADJUST_LOWER)
            "open_camera" -> {
                val id = confirmer.begin(action)
                try {
                    svc.startActivity(Intent(MediaStore.INTENT_ACTION_STILL_IMAGE_CAMERA).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                    Result(true, "intent:STILL_IMAGE_CAMERA", id)
                } catch (e: Exception) { Result(false, "no camera app: ${e.javaClass.simpleName}", id) }
            }
            // An accessibility service cannot inject KEYCODE_CAMERA; per-app shutter taps belong in a profile rule.
            "take_photo" -> Result(false, "unsupported: no generic shutter action (bind a tap in the camera app's profile)")
            "listen_for_phrase" -> { onListen(); Result(true, "listening window opened") }
            else -> Result(false, "unknown action")
        }
    }

    /** Cursor-mode actions; null = not a cursor-only action (e.g. "back" falls through to the normal table). */
    private fun cursorAction(action: String): Result? {
        if (action.startsWith("move_")) {
            val parts = action.removePrefix("move_").split("_")
            val fast = parts.last() == "fast"
            overlay.move(parts.dropLast(1).joinToString("_"), fast)
            return Result(true, "cursor ${overlay.description}")
        }
        return when (action) {
            "stop" -> { overlay.stop(); Result(true, "cursor stopped") }
            "click" -> { overlay.stop(); gesture(action, tap(overlay.x, overlay.y), "tap(cursor ${overlay.x.toInt()},${overlay.y.toInt()})") }
            "drag_toggle" -> {
                overlay.stop()
                val start = dragStart
                if (start == null) {
                    dragStart = overlay.x to overlay.y; overlay.dragging = true; overlay.refresh()
                    Result(true, "drag started at ${overlay.x.toInt()},${overlay.y.toInt()}")
                } else {
                    dragStart = null; overlay.dragging = false; overlay.refresh()
                    gesture(action, swipe(start.first, start.second, overlay.x, overlay.y, 600), "drag")
                }
            }
            "grid_pick_1" -> { overlay.moveTo(screenW() / 6f, screenH() / 6f); Result(true, "cursor to top-left cell") }
            "grid_pick_5" -> { overlay.moveTo(screenW() / 2f, screenH() / 2f); Result(true, "cursor to centre cell") }
            "grid_pick_9" -> { overlay.moveTo(screenW() * 5 / 6f, screenH() * 5 / 6f); Result(true, "cursor to bottom-right cell") }
            else -> null
        }
    }

    /** Intent cursor mode: tap the centre of a chosen element (and park the cursor there, if it is shown). */
    fun tapTarget(t: Target, confirmed: Boolean = false): Result {
        if (!Outward.mayTap(t.label, confirmed)) return Result(false, "refused: '${t.label}' is outward and needs a confirm pop")
        dialogInFront("tap_target")?.let { return Result(false, it) }
        val r = gesture("tap_target", tap(t.cx.toFloat(), t.cy.toFloat()), "tap(${t.cx},${t.cy}) ${t.option}")
        if (overlay.cursorVisible()) overlay.moveTo(t.cx.toFloat(), t.cy.toFloat())
        return r
    }

    // --- typing by voice ([TextInsert]) ---------------------------------------------------------------------------

    /** The box with input focus (the keyboard's), never Canti's own; null = none. */
    fun focusedField(): TextField? {
        val n = try { svc.findFocus(AccessibilityNodeInfo.FOCUS_INPUT) } catch (_: Exception) { null } ?: return null
        if (n.packageName?.toString() == svc.packageName) return null
        return NodeField(n)
    }

    /** Why typing can't happen now (a system dialog in front, no box, a password box), or null. */
    fun typingRefusal(): String? =
        (if (!SystemDialog.allows(TYPE_TEXT)) dialogInFront(TYPE_TEXT) else null) ?: TextInsert.refusal(focusedField())

    /**
     * Type [text] into the focused box: ACTION_SET_TEXT (the whole new text) then ACTION_SET_SELECTION (the cursor).
     * Not a paste: that would overwrite the user's clipboard. Never a click, enter or IME action, so nothing is sent.
     */
    fun typeText(text: String): TextInsert.Outcome {
        if (!SystemDialog.allows(TYPE_TEXT)) dialogInFront(TYPE_TEXT)?.let { return TextInsert.Outcome(false, it) }
        return TextInsert.insert(focusedField(), text)
    }

    private class NodeField(private val n: AccessibilityNodeInfo) : TextField {
        override val text get() = n.text?.toString()
        override val showingHint get() = n.isShowingHintText
        override val selStart get() = n.textSelectionStart
        override val selEnd get() = n.textSelectionEnd
        override val isEditable get() = n.isEditable
        override val isPassword get() = n.isPassword
        override val maxLength get() = n.maxTextLength
        override fun setText(text: String) = n.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT,
            android.os.Bundle().apply { putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text) })
        override fun setSelection(start: Int, end: Int) = n.performAction(AccessibilityNodeInfo.ACTION_SET_SELECTION,
            android.os.Bundle().apply {
                putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_START_INT, start)
                putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_END_INT, end)
            })
    }

    /** A spoken "open <app>": its launcher activity, in this user (Canti runs in user 0; Secure Folder apps are not seen). */
    fun launchApp(pkg: String): Result {
        val id = confirmer.begin("open_app")
        val i = svc.packageManager.getLaunchIntentForPackage(pkg) ?: return Result(false, "no launcher activity for $pkg", id)
        return try {
            svc.startActivity(i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED))
            Result(true, "launch:$pkg", id)
        } catch (e: Exception) { Result(false, "launch failed: ${e.javaClass.simpleName}", id) }
    }

    /** A spoken "set a timer for ...": the clock app's timer, without its screen where the app allows ([seconds] 1..86400). */
    /**
     * Sent to one resolved clock app ([TimerTarget]: the `timer_app` setting [preferred], the only one, the default,
     * the system clock), never loosely: a loose intent can open the app chooser and set nothing. Several and no pick:
     * not ok, nothing started.
     */
    fun setTimer(seconds: Int, preferred: String = ""): Result {
        require(seconds in 1..86_400) { "timer length must be 1 s .. 24 h" }
        val i = Intent(android.provider.AlarmClock.ACTION_SET_TIMER)
            .putExtra(android.provider.AlarmClock.EXTRA_LENGTH, seconds)
            .putExtra(android.provider.AlarmClock.EXTRA_SKIP_UI, true)
            .putExtra(android.provider.AlarmClock.EXTRA_MESSAGE, "Canti")
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        val pm = svc.packageManager
        val handlers = try {
            pm.queryIntentActivities(i, 0).map { r ->
                TimerTarget.Handler(r.activityInfo.packageName, r.activityInfo.name, r.loadLabel(pm).toString(),
                    (r.activityInfo.applicationInfo.flags and android.content.pm.ApplicationInfo.FLAG_SYSTEM) != 0)
            }
        } catch (e: Exception) { return Result(false, "timer apps unknown: ${e.javaClass.simpleName}") }
        val def = try { pm.resolveActivity(i, android.content.pm.PackageManager.MATCH_DEFAULT_ONLY)?.activityInfo } catch (_: Exception) { null }
        return when (val pick = TimerTarget.pick(handlers, def?.packageName, def?.name, preferred)) {
            is TimerTarget.Pick.Refuse -> Result(false, pick.message)
            is TimerTarget.Pick.Use -> try {
                svc.startActivity(i.setClassName(pick.handler.pkg, pick.handler.activity))
                Result(true, "intent:SET_TIMER ${seconds}s -> ${pick.handler.pkg} (${pick.why})")
            } catch (e: Exception) { Result(false, "${pick.handler.label} refused the timer: ${e.javaClass.simpleName}") }
        }
    }

    fun cancelDrag() { dragStart = null; overlay.dragging = false }

    /** System gesture and bar insets (at least [SwipeGeometry.fallback]): swipe points stay out of them. */
    fun safeInsets(): SwipeGeometry.Safe {
        val fb = SwipeGeometry.fallback(svc.resources.displayMetrics.density)
        return try {
            val wm = svc.getSystemService(WindowManager::class.java)
            val i = wm.currentWindowMetrics.windowInsets.getInsets(
                WindowInsets.Type.systemGestures() or WindowInsets.Type.mandatorySystemGestures() or WindowInsets.Type.systemBars())
            SwipeGeometry.Safe(maxOf(i.left, fb.left), maxOf(i.top, fb.top), maxOf(i.right, fb.right), maxOf(i.bottom, fb.bottom))
        } catch (_: Exception) { fb }
    }

    /**
     * A rise/fall in an ordinary list is a no-momentum step (a drag over the `scroll_step` share of the list, then
     * still for [ScrollStep.HOLD_MS] before the lift); pagers, sideways swipes and unknown screens keep the fling
     * ([ScrollStep.decide]). This synchronous read (bounded, main thread, like node-scroll's) is only voice scroll's
     * feed check now; a feed it finds also goes into [feedKind]'s cache. Rise / fall plan from the cache instead.
     */
    private fun stepDecision(action: String, h: Int): ScrollStep.Decision {
        val (d, pkg, windowId) = try {
            val root = TreeReader.appRoot(svc)
            if (root == null) Triple(ScrollStep.Decision(false, "no app window"), null, -1)
            else root.packageName?.toString().let { pkg -> Triple(ScrollStep.decide(action, pkg, ScrollerReader.read(root), h), pkg, root.windowId) }
        } catch (e: Exception) { Triple(ScrollStep.Decision(false, "tree read failed: ${e.javaClass.simpleName}"), null, -1) }
        if (pkg != null && d.feed) feedKind.cache.put(FeedKindCache.Answer(pkg, windowId, FeedKindCache.Kind.FEED, d.why, screenW = screenW(), screenH = h))
        return d
    }

    // --- the swipe-plan cache ([FeedKindCache]) ---------------------------------------------------------------------

    private val feedThread = Executors.newSingleThreadExecutor { r -> Thread(r, "vox-feedkind").apply { isDaemon = true } }
    /** The screen size for the background read (read on the main thread, where the events arrive). */
    @Volatile private var feedW = 0
    @Volatile private var feedH = 0
    /** Windows already probed for "no scrollable list" in a known feed app ([FeedProbe]); once per window a session. */
    private val probed = java.util.Collections.synchronizedSet(HashSet<Pair<String, Int>>())

    /** What a rise / fall meets: refreshed off the main thread, read by rise / fall without a tree walk. */
    val feedKind = FeedKindWatcher(FeedKindCache(SystemClock::elapsedRealtime), ::readFeedKind, feedThread::execute,
        { ms, r -> main.postDelayed(r, ms) })

    /** Set by the service: refresh only while Canti can act (armed, not paused); window changes always invalidate. */
    var feedWatch: () -> Boolean = { true }

    /** The background read: the tree read and rules 1-4 of the swipe ([ScrollStep.classify]); never on the main thread. */
    private fun readFeedKind(): FeedKindCache.Answer? {
        val root = TreeReader.appRoot(svc) ?: return null
        val pkg = root.packageName?.toString() ?: return null
        val w = feedW.takeIf { it > 0 } ?: return null
        val h = feedH.takeIf { it > 0 } ?: return null
        val nodes = ScrollerReader.readNodes(root)
        val c = ScrollStep.classify(pkg, nodes.map { it.first }, h)
        val handle = (c as? ScrollStep.Kind.List)?.let { l -> nodes.firstOrNull { it.first === l.main }?.second }
        if (c is ScrollStep.Kind.Fling && !c.d.feed && pkg in ScrollStep.FEED_APPS && probed.add(pkg to root.windowId)) {
            // YouTube Shorts in RVX: "no scrollable list" on every swipe (round 4). What the tree shows, for its detection.
            try {
                TreeReader.snapshot(root)?.let { s ->
                    EventLog.ev("feed_undetected", "app" to pkg, "window" to root.windowId, "why" to c.d.why, "tree" to FeedProbe.summary(s, w, h))
                }
            } catch (_: Exception) {}
        }
        return FeedKindCache.answerOf(pkg, root.windowId, c, handle, w, h)
    }

    /** Accessibility events (main thread): a window change invalidates, content changes and scrolls refresh (throttled). */
    fun onWindowEvent(type: Int, pkg: String?, windowId: Int) {
        if (pkg.isNullOrEmpty() || pkg == svc.packageName || pkg == SYSTEM_UI) return
        val watching = feedWatch()
        if (watching) { feedW = screenW(); feedH = screenH() }
        when (type) {
            AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED ->
                if (watching) feedKind.windowStateChanged(pkg, windowId) else feedKind.cache.windowEvent(pkg, windowId)
            AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED, AccessibilityEvent.TYPE_VIEW_SCROLLED ->
                if (watching && feedKind.cache.current()?.pkg.let { it == null || it == pkg }) feedKind.contentChanged()
        }
    }

    /** Armed again: read the window now, so the first swipe finds an answer. */
    fun feedKindWake() { feedW = screenW(); feedH = screenH(); feedKind.refresh(force = true) }

    /** The cached list node, refreshed now (one node, not the tree) as the planner sees it; null if gone. */
    private fun liveList(handle: Any?): NodeSnap? {
        val n = handle as? AccessibilityNodeInfo ?: return null
        return try { if (n.refresh()) ScrollerReader.snap(n) else null } catch (_: Exception) { null }
    }

    /** The fling for [action] ([SwipeGeometry] line); on a paged feed ([ScrollStep.Decision.feed]) the shorter [ScrollStep.feedLine] (`feed_fling_pct`) in `feed_fling_ms`. */
    private fun fling(action: String, key: String, w: Int, h: Int, d: ScrollStep.Decision, safe: SwipeGeometry.Safe, why: String): Result {
        val f = (if (d.feed) ScrollStep.feedLine(key, w, h, safe, prefs.feedFlingPct) else null) ?: SwipeGeometry.line(key, w, h, safe)!!
        val ms = if (d.feed) prefs.feedFlingMs.toLong() else SwipeGeometry.DURATION_MS
        return gesture(action, swipe(f[0], f[1], f[2], f[3], ms),
            "${if (d.feed) "feed-fling" else "fling"}(${f[0].toInt()},${f[1].toInt()} -> ${f[2].toInt()},${f[3].toInt()}, $ms ms; $why)")
    }

    /** A feed decision from a cached answer (no tree read). */
    private fun cachedFeed(l: FeedKindCache.Lookup): ScrollStep.Decision? =
        (l as? FeedKindCache.Lookup.Hit)?.takeIf { it.entry.kind == FeedKindCache.Kind.FEED }
            ?.let { ScrollStep.Decision(false, "${it.entry.why} (cached ${it.ageMs} ms)", feed = true) }

    /**
     * `fling_wait` event, for round 5: [t0] -> `wait_ms` from the executor taking the swipe to the dispatch call
     * returning (a tree read included when there was one, `tree_ms`; the live list check, `check_ms`), and what the
     * cache said (`cache`: hit / expired / miss; "none" for sideways swipes, which never read the tree).
     */
    private fun logPlan(action: String, plan: String, cache: String, ageMs: Long?, treeMs: Double?, t0: Long, r: Result,
                        checkMs: Double? = null, refused: String? = null) {
        EventLog.ev("fling_wait", "action" to action, "plan" to plan, "cache" to cache, "cache_hit" to (cache == "hit"),
            "age_ms" to ageMs, "tree_ms" to treeMs, "check_ms" to checkMs, "refused" to refused, "wait_ms" to msSince(t0),
            "how" to r.how.substringBefore('('), "ok" to r.ok)
    }

    private fun msSince(t0: Long) = Math.round((SystemClock.elapsedRealtimeNanos() - t0) / 1e5) / 10.0

    /**
     * Voice scroll_down / scroll_up on a paged feed (TikTok, Reels, Shorts: [ScrollStep.Decision.feed]) is the feed
     * fling of [swipe], as a rise / fall there: ACTION_SCROLL on TikTok's pager returns true and does not move.
     * Null elsewhere (node-scroll as before). A fresh cached feed answer skips the tree read; anything else reads it.
     */
    private fun feedScroll(action: String, swipe: String, w: Int, h: Int): Result? {
        val t0 = SystemClock.elapsedRealtimeNanos()
        val l = feedKind.cache.lookup(TreeReader.appPackage(svc))
        cachedFeed(l)?.let { d -> return fling(action, swipe, w, h, d, safeInsets(), d.why).also { logPlan(action, "feed", l.label, (l as FeedKindCache.Lookup.Hit).ageMs, null, t0, it) } }
        val t1 = SystemClock.elapsedRealtimeNanos()
        val d = stepDecision(swipe, h)
        val tree = msSince(t1)
        return if (d.feed) fling(action, swipe, w, h, d, safeInsets(), d.why).also { logPlan(action, "read", l.label, null, tree, t0, it) } else null
    }

    /**
     * A rise / fall plans from the cache ([FeedKindWatcher.plan], [FlingPlan]) and never reads the tree: a fresh feed
     * answer is the feed fling; a fresh list plan is the step, once its list node (refreshed alone, [StepCheck]) is
     * still there and on screen; a fresh "neither" answer is the plain fling. With no usable answer (none yet,
     * expired, or the list check refused): the feed fling in a known feed app whose last answer this session was a
     * feed, else the plain fling, and a refresh starts. Sideways swipes always fling.
     */
    private fun swipeOrStep(action: String, w: Int, h: Int): Result {
        val t0 = SystemClock.elapsedRealtimeNanos()
        val safe = safeInsets()
        if (action != "swipe_up" && action != "swipe_down") {
            val d = ScrollStep.decide(action, null, emptyList(), h)
            return fling(action, action, w, h, d, safe, d.why).also { logPlan(action, "sideways", "none", null, null, t0, it) }
        }
        feedW = w; feedH = h
        val pkg = TreeReader.appPackage(svc)
        val (plan, look) = feedKind.plan(pkg)
        val age = (look as? FeedKindCache.Lookup.Hit)?.ageMs ?: (look as? FeedKindCache.Lookup.Expired)?.ageMs
        fun plain(why: String, checkMs: Double? = null, refused: String? = null): Result {
            val d = ScrollStep.Decision(false, why)
            return fling(action, action, w, h, d, safe, d.why).also { logPlan(action, "plain", look.label, age, null, t0, it, checkMs, refused) }
        }
        return when (plan) {
            FlingPlan.FEED -> {
                val d = cachedFeed(look)!!
                fling(action, action, w, h, d, safe, d.why).also { logPlan(action, "feed", look.label, age, null, t0, it) }
            }
            FlingPlan.LAST_FEED -> {
                val d = ScrollStep.Decision(false, "cache ${look.label}; last answer for $pkg this session was a feed", feed = true)
                fling(action, action, w, h, d, safe, d.why).also { logPlan(action, "last-feed", look.label, age, null, t0, it) }
            }
            FlingPlan.OTHER -> {
                val why = (look as FeedKindCache.Lookup.Hit).entry.why
                fling(action, action, w, h, ScrollStep.Decision(false, why), safe, "$why (cached)")
                    .also { logPlan(action, "other", look.label, age, null, t0, it) }
            }
            FlingPlan.PLAIN -> plain("swipe plan not known yet (cache ${look.label}): plain fling")
            FlingPlan.LIST -> {
                val e = (look as FeedKindCache.Lookup.Hit).entry
                val t1 = SystemClock.elapsedRealtimeNanos()
                val chk = StepCheck.check(action, e.answer, liveList(e.answer.handle), w, h)
                val checkMs = msSince(t1)
                val d = chk.decision
                if (d == null) {
                    // the cached list is gone or moved off screen: never step on a vanished area; read again
                    feedKind.cache.invalidate(); feedKind.refresh(force = true)
                    return plain("cached list refused: ${chk.refused}", checkMs, chk.refused)
                }
                val l = d.list?.let { ScrollStep.line(action, it, w, h, safe, StepSize.of(prefs.scrollStep), android.view.ViewConfiguration.get(svc).scaledTouchSlop) }
                if (l == null) return fling(action, action, w, h, d, safe, if (d.step) "band too short" else d.why)
                    .also { logPlan(action, "list", look.label, age, null, t0, it, checkMs) }
                val move = GestureDescription.StrokeDescription(Path().apply { moveTo(l[0], l[1]); lineTo(l[2], l[3]) }, 0, ScrollStep.STROKE_MS, true)
                val still = move.continueStroke(Path().apply { moveTo(l[2], l[3]) }, 0, ScrollStep.HOLD_MS, false)
                gesture(action, GestureDescription.Builder().addStroke(move).build(),
                    "step(${l[0].toInt()},${l[1].toInt()} -> ${l[2].toInt()},${l[3].toInt()}, ${ScrollStep.STROKE_MS}+${ScrollStep.HOLD_MS} ms still; ${d.why})",
                    next = GestureDescription.Builder().addStroke(still).build()).also { logPlan(action, "list", look.label, age, null, t0, it, checkMs) }
            }
        }
    }

    private val prefs by lazy { Settings(svc) }

    // --- hold-to-scroll -----------------------------------------------------------------------------------------

    /**
     * The hold-scroll finger ([ScrollDrag]): one continued stroke, extended in 100 ms segments at [pxPerS] (read at
     * each segment), from 75% to 25% of the screen along the swipe's axis; there it holds still 150 ms, lifts and
     * grabs again. [end] finishes the current segment, holds still 150 ms and lifts, so the content stops where it is
     * (no fling). Main thread (gesture callbacks run on the main looper).
     */
    inner class Drag(private val pxPerS: () -> Float) : ScrollDrag {
        private var action = ""
        private var active = false
        private var inFlight = false
        private var last: GestureDescription.StrokeDescription? = null
        private var x = 0f; private var y = 0f; private var travelled = 0f
        private var onFail: (String) -> Unit = {}

        override fun begin(action: String, onFail: (String) -> Unit) {
            this.action = action; this.onFail = onFail
            active = true; last = null
            // queued one-shot gestures would cancel the drag's strokes when their turn came
            for (d in steps.dropWaiting()) EventLog.ev("gesture", "action" to d.action, "result" to "dropped (hold-scroll started)")
            grab()
            segment()
        }

        override fun end() {
            active = false
            if (!inFlight) lift()
        }

        private fun horizontal() = action == "swipe_left" || action == "swipe_right"
        private fun span() = if (horizontal()) screenW().toFloat() else screenH().toFloat()

        private fun grab() {
            val w = screenW().toFloat(); val h = screenH().toFloat()
            travelled = 0f
            when (action) {
                "swipe_up" -> { x = w / 2; y = h * 0.75f }
                "swipe_down" -> { x = w / 2; y = h * 0.25f }
                "swipe_left" -> { x = w * 0.75f; y = h / 2 }
                else -> { x = w * 0.25f; y = h / 2 }
            }
        }

        private fun segment() {
            if (!active) { lift(); return }
            if (travelled >= span() * 0.5f) { lift(); grab() }
            val d = pxPerS() * SEGMENT_MS / 1000f
            val (dx, dy) = when (action) { "swipe_up" -> 0f to -d; "swipe_down" -> 0f to d; "swipe_left" -> -d to 0f; else -> d to 0f }
            val path = Path().apply { moveTo(x, y); lineTo(x + dx, y + dy) }
            val prev = last
            val s = prev?.continueStroke(path, 0, SEGMENT_MS, true) ?: GestureDescription.StrokeDescription(path, 0, SEGMENT_MS, true)
            x += dx; y += dy; travelled += d
            inFlight = true
            val ok = inject(GestureDescription.Builder().addStroke(s).build(), object : AccessibilityService.GestureResultCallback() {
                override fun onCompleted(g: GestureDescription?) { inFlight = false; last = s; segment() }
                override fun onCancelled(g: GestureDescription?) {
                    inFlight = false; last = null
                    if (active) { active = false; onFail("drag cancelled (screen touched?)") }
                }
            })
            if (!ok) { inFlight = false; last = null; active = false; onFail("dispatchGesture refused") }
        }

        /** Hold still, then lift: velocity ~0 at the lift, so there is no fling. */
        private fun lift() {
            val prev = last ?: return
            last = null
            val hold = prev.continueStroke(Path().apply { moveTo(x, y) }, 0, 150, false)
            inject(GestureDescription.Builder().addStroke(hold).build(), null)
        }
    }

    // --- forward --------------------------------------------------------------------------------------------------

    /** The foreground app's windows (popup menus are windows of their own), topmost first; never ours. */
    private fun appRoots(): List<AccessibilityNodeInfo> {
        val own = svc.packageName
        val ws = try { svc.windows } catch (_: Exception) { emptyList<AccessibilityWindowInfo>() }
        val roots = ws.filter { it.type == AccessibilityWindowInfo.TYPE_APPLICATION }.mapNotNull { it.root }
            .filter { it.packageName?.toString() != own }
        return roots.ifEmpty { listOfNotNull(TreeReader.appRoot(svc)) }
    }

    private fun kids(n: AccessibilityNodeInfo): List<AccessibilityNodeInfo> = (0 until n.childCount).mapNotNull { n.getChild(it) }

    private fun info(n: AccessibilityNodeInfo): Forward.Info {
        val r = android.graphics.Rect().also { n.getBoundsInScreen(it) }
        return Forward.Info(n.text?.toString(), n.contentDescription?.toString(), n.isClickable, n.isEnabled, n.isVisibleToUser,
            r.left, r.top, r.right, r.bottom)
    }

    private fun click(n: AccessibilityNodeInfo): Boolean {
        if (n.performAction(AccessibilityNodeInfo.ACTION_CLICK)) return true
        val r = android.graphics.Rect().also { n.getBoundsInScreen(it) }
        if (r.isEmpty) return false
        val g = tap(r.exactCenterX(), r.exactCenterY())
        if (clearOfHead(g)) { main.postDelayed({ inject(g, null) }, HEAD_CLEAR_MS); return true }
        return inject(g, null)
    }

    /**
     * Forward: a visible Forward control is clicked; a disabled one means there is nothing to go forward to. Otherwise
     * open the overflow menu and look there (polling up to 1.5 s): click Forward if enabled, else close the menu (back,
     * only if the screen changed, so a menu that did not open is never "closed" by navigating back). The outcome of the
     * menu path is logged as event "forward".
     */
    private fun forward(): Result {
        val roots = appRoots()
        Forward.forward(roots, ::kids, ::info)?.let { hit ->
            if (!hit.enabled) return Result(false, "no-forward (Forward is disabled)")
            val id = confirmer.begin("forward")
            return Result(click(hit.click), "click:Forward (visible)", id)
        }
        val menu = Forward.menu(roots, ::kids, ::info, screenH())
            ?: return Result(false, "no-forward (no Forward control and no overflow menu)").also { EventLog.ev("forward", "result" to "no-forward", "why" to "no control, no menu") }
        val before = TreeReader.fingerprint(TreeReader.appRoot(svc))
        if (!click(menu.click)) return Result(false, "no-forward (overflow menu click failed)")
        val started = System.currentTimeMillis()
        fun look() {
            val rs = appRoots()
            val hit = Forward.forward(rs, ::kids, ::info)
            val waited = System.currentTimeMillis() - started
            when {
                hit != null && hit.enabled -> {
                    val id = confirmer.begin("forward")
                    val ok = click(hit.click)
                    EventLog.ev("forward", "result" to if (ok) "clicked" else "click-failed", "where" to "overflow menu", "waited_ms" to waited, "watch" to id)
                }
                hit != null || waited >= 1500 -> {
                    val opened = TreeReader.fingerprint(TreeReader.appRoot(svc)) != before || rs.size != roots.size
                    if (opened) svc.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)
                    EventLog.ev("forward", "result" to "no-forward", "why" to if (hit != null) "Forward is disabled in the menu" else "no Forward in the menu",
                        "waited_ms" to waited, "menu_closed" to opened)
                }
                else -> main.postDelayed(::look, 150)
            }
        }
        main.postDelayed(::look, 250)
        return Result(true, "opened overflow menu (${Forward.norm(info(menu.labelled).desc ?: info(menu.labelled).text)}), looking for Forward")
    }

    // --- primitives -----------------------------------------------------------------------------------------------

    /** Strokes' start points and the gesture's total length (for [Overlay.passThroughIfUnder]). */
    private fun starts(g: GestureDescription): Pair<List<FloatArray>, Long> {
        var end = 0L
        val pts = (0 until g.strokeCount).map { i ->
            val st = g.getStroke(i)
            end = maxOf(end, st.startTime + st.duration)
            FloatArray(2).also { android.graphics.PathMeasure(st.path, false).getPosTan(0f, it, null) }
        }
        return pts to end
    }

    /** True if the Canti head was under the gesture: it lets touches through now, and the caller waits a frame. */
    private fun clearOfHead(g: GestureDescription): Boolean {
        val (pts, len) = starts(g)
        return try { overlay.passThroughIfUnder(pts, len + 400) } catch (_: Exception) { false }
    }

    /** One step of the [GestureQueue]: an injected gesture, or a global action ([code]) queued behind gestures. */
    private class Step(val action: String, val g: GestureDescription?, val code: Int = 0) {
        var id = 0L
        var viaHead = false
        /** A second part dispatched when [g] completes (a step's still hold, continuing its stroke). */
        var next: GestureDescription? = null
    }
    private val steps = GestureQueue<Step>()

    /** The system dialog in front, or null ([SystemDialog]); set by the service. [onDialogBlock]: a refusal happened. */
    var dialogGuard: () -> String? = { null }
    var onDialogBlock: (action: String, dialog: String) -> Unit = { _, _ -> }

    /** A dialog in front: drop every queued gesture, report, and return the refusal; null = go ahead. */
    private fun dialogInFront(action: String): String? {
        val d = try { dialogGuard() } catch (_: Exception) { null } ?: return null
        // queued touches go; a queued back or home stays (it is how the user gets out of the dialog)
        for (w in steps.dropWaiting()) {
            if (w.g == null) steps.offer(w, SystemClock.uptimeMillis())?.let { start(it) }
            else EventLog.ev("gesture", "action" to w.action, "result" to "dropped (system dialog: $d)")
        }
        EventLog.ev("gesture", "action" to action, "result" to "refused (system dialog: $d)")
        onDialogBlock(action, d)
        return SystemDialog.refusal(action, d)
    }

    private fun gesture(action: String, g: GestureDescription, how: String, next: GestureDescription? = null): Result {
        val s = Step(action, g).also { it.next = next }
        val go = steps.offer(s, SystemClock.uptimeMillis())
        logDropped()
        if (go !== s) {
            EventLog.ev("gesture", "action" to action, "result" to "queued")
            go?.let { start(it) }
            return Result(true, "$how (queued behind the gesture in progress)")
        }
        val ok = start(s)
        return Result(ok, if (s.viaHead) "$how (after letting it through the Canti head)" else how, s.id)
    }

    /** Runs the step the queue just made current: its confirm watch, then the gesture (clear of the head) or global action. */
    private fun start(s: Step): Boolean {
        val g = s.g
        if (g == null) {
            s.id = confirmer.begin(s.action)
            val ok = svc.performGlobalAction(s.code)
            EventLog.ev("gesture", "watch" to s.id, "action" to s.action, "result" to if (ok) "global (was queued)" else "global refused")
            done(s)
            return ok
        }
        if (dialogInFront(s.action) != null) { done(s); return false }
        s.id = confirmer.begin(s.action, injected = true)
        if (clearOfHead(g)) { s.viaHead = true; main.postDelayed({ dispatch(s, g) }, HEAD_CLEAR_MS); return true }
        return dispatch(s, g)
    }

    private fun dispatch(s: Step, g: GestureDescription): Boolean {
        val ok = inject(g, object : AccessibilityService.GestureResultCallback() {
            override fun onCompleted(d: GestureDescription?) {
                s.next?.let { n -> s.next = null; dispatch(s, n); return }
                confirmer.gestureDone(s.id)
                EventLog.ev("gesture", "watch" to s.id, "action" to s.action, "result" to "completed")
                done(s)
            }
            override fun onCancelled(d: GestureDescription?) {
                confirmer.gestureDone(s.id)
                EventLog.ev("gesture", "watch" to s.id, "action" to s.action, "result" to "cancelled")
                done(s)
            }
        })
        if (!ok) { EventLog.ev("gesture", "watch" to s.id, "action" to s.action, "result" to "refused"); done(s) }
        return ok
    }

    /** The running step is over: start the next waiting one, if any. */
    private fun done(s: Step) { steps.finished(s, SystemClock.uptimeMillis())?.let { start(it) } }

    private fun logDropped() {
        for (d in steps.dropped) EventLog.ev("gesture", "action" to d.action, "result" to "dropped (queue full)")
        steps.dropped.clear()
    }

    /** Every injected touch goes through here: it stamps [lastInjectedGestureMs] / [lastInjectedGestureEndMs]. */
    private fun inject(g: GestureDescription, cb: AccessibilityService.GestureResultCallback?): Boolean {
        if (dialogInFront("gesture") != null) return false   // last check: hold-scroll strokes, a step's second part
        val now = SystemClock.uptimeMillis()
        val len = (0 until g.strokeCount).maxOfOrNull { g.getStroke(it).let { s -> s.startTime + s.duration } } ?: 0L
        lastInjectedGestureMs = now
        lastInjectedGestureEndMs = now + len
        return svc.dispatchGesture(g, cb, null)
    }

    private fun global(action: String, code: Int): Result {
        // Behind gestures still waiting to run ("swipe, swipe, back" in that order); otherwise at once, as before.
        if (steps.hasWaiting) {
            steps.offer(Step(action, null, code), SystemClock.uptimeMillis())?.let { start(it) }
            logDropped()
            EventLog.ev("gesture", "action" to action, "result" to "queued")
            return Result(true, "global:$action (queued behind waiting gestures)")
        }
        val id = confirmer.begin(action)
        return Result(svc.performGlobalAction(code), "global:$action", id)
    }

    private fun scroll(action: String, forward: Boolean): Result? {
        val root = TreeReader.appRoot(svc) ?: return null
        val target = largestScrollable(root) ?: return null
        val id = confirmer.begin(action)
        val ok = target.performAction(if (forward) AccessibilityNodeInfo.ACTION_SCROLL_FORWARD else AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD)
        return Result(ok, "node-scroll:${target.className}", id)
    }

    /** The main vertical list ([ScrollPick]: not the outer tab pager of the same size). */
    private fun largestScrollable(root: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        class Cand(val node: AccessibilityNodeInfo, val area: Long, val horizontal: Boolean)
        val found = ArrayList<Cand>()
        val r = android.graphics.Rect()
        val stack = ArrayDeque<AccessibilityNodeInfo>().apply { add(root) }
        var n = 0
        while (stack.isNotEmpty() && n++ < 1500) {
            val x = stack.removeLast()   // children pushed in reverse: pre-order
            if (x.isScrollable && x.isVisibleToUser) {
                x.getBoundsInScreen(r)
                val ci = x.collectionInfo
                found += Cand(x, r.width().toLong() * r.height(),
                    ScrollPick.horizontal(x.className?.toString(), ci?.rowCount ?: -1, ci?.columnCount ?: -1))
            }
            for (i in x.childCount - 1 downTo 0) x.getChild(i)?.let { stack.add(it) }
        }
        return ScrollPick.best(found.filter { it.area > 0 }, { it.area }, { it.horizontal })?.node
    }

    // [swipes] pull to refresh: a downward drag from 25% to 70% of the top scrollable's height at its horizontal
    // centre, 400 ms, only when that scrollable is at its top (else "not at the top").
    private fun pullRefresh(action: String): Result {
        val root = TreeReader.appRoot(svc) ?: return Result(false, "not at the top")
        val target = largestScrollable(root) ?: return Result(false, "not at the top")
        if (target.actions and AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD != 0) return Result(false, "not at the top")
        val r = android.graphics.Rect()
        target.getBoundsInScreen(r)
        val cx = r.centerX().toFloat()
        val y0 = r.top + r.height() * 0.25f
        val y1 = r.top + r.height() * 0.70f
        return gesture(action, swipe(cx, y0, cx, y1, 400), "pull-refresh")
    }

    // [swipes] an item swipe (ItemSwipeGeometry): a horizontal drag from the target's centre, 70% of the screen width.
    // The Confirmer judges the returned watch (a dismissed row changes the tree).
    fun itemSwipe(box: Box, dir: String, rtl: Boolean): Result {
        val g = ItemSwipeGeometry.gesture(box, screenW(), dir, rtl)
        return gesture("item_swipe", swipe(g.x0, g.y0, g.x1, g.y1, g.ms), "item-swipe($dir)")
    }

    private fun mediaKey(action: String, code: Int): Result {
        val id = confirmer.begin(action)
        audio.dispatchMediaKeyEvent(KeyEvent(KeyEvent.ACTION_DOWN, code))
        audio.dispatchMediaKeyEvent(KeyEvent(KeyEvent.ACTION_UP, code))
        return Result(true, "media-key:${KeyEvent.keyCodeToString(code)}", id)
    }

    /** The decider's `volume_up` / `volume_down`: one system step on the auto stream (the call volume during a call). */
    private fun volume(action: String, dir: Int): Result {
        val id = confirmer.begin(action)
        val s = VolumePlan.stream(VolStream.AUTO, inCall())
        audio.adjustStreamVolume(ANDROID_STREAM.getValue(s), dir, AudioManager.FLAG_SHOW_UI)
        return Result(true, "volume:${s.key}:${if (dir > 0) "raise" else "lower"}", id)
    }

    private fun inCall(): Boolean = audio.mode == AudioManager.MODE_IN_CALL || audio.mode == AudioManager.MODE_IN_COMMUNICATION

    /** Per stream: the level a spoken "mute" silenced, for "unmute" (this service's lifetime). */
    private val preMute = HashMap<Int, Int>()

    /**
     * A spoken volume command ([VolumeGrammar]): the stream (context-aware), then [VolumePlan] on its state. Always shows
     * the system volume bar; no confirm (reversible). Where a stream cannot be muted (the call volume) it goes to its
     * minimum. Changing the ringer in Do Not Disturb can be refused by the system: reported, not retried.
     */
    fun setVolume(v: SpeechCommand.Volume): Result {
        val s = VolumePlan.stream(v.stream, inCall())
        val st = ANDROID_STREAM.getValue(s)
        val flags = AudioManager.FLAG_SHOW_UI
        val id = confirmer.begin(if (v.op is VolOp.Step && (v.op as VolOp.Step).dir < 0) "volume_down" else "volume_up")
        return try {
            val before = VolumePlan.Level(audio.getStreamVolume(st), audio.getStreamMinVolume(st), audio.getStreamMaxVolume(st), audio.isStreamMute(st))
            val plan = VolumePlan.plan(v.op, before, preMute[st], canMute = s != VolStream.CALL)
            plan.remember?.let { preMute[st] = it }
            if (plan.unmute) audio.adjustStreamVolume(st, AudioManager.ADJUST_UNMUTE, flags)
            if (plan.mute) {
                audio.adjustStreamVolume(st, AudioManager.ADJUST_MUTE, flags)
                // not every stream honours ADJUST_MUTE: then the minimum
                if (!audio.isStreamMute(st) && audio.getStreamVolume(st) > before.min) audio.setStreamVolume(st, before.min, flags)
            }
            plan.setIndex?.let { audio.setStreamVolume(st, it, flags) }
            if (!plan.mute && !plan.unmute && plan.setIndex == null) audio.adjustStreamVolume(st, AudioManager.ADJUST_SAME, flags)   // show the bar
            val now = audio.getStreamVolume(st)
            Result(true, "volume:${s.key} ${before.index}->$now of ${before.max}${if (audio.isStreamMute(st)) " muted" else ""} (${plan.describe()})", id)
        } catch (e: SecurityException) {
            Result(false, "volume:${s.key} refused by the system (Do Not Disturb?): ${e.message}", id)
        }
    }

    companion object {
        const val SEGMENT_MS = 100L
        /** Typing by voice: not a touch, but it changes the screen, so a system dialog in front refuses it. */
        const val TYPE_TEXT = "type_text"

        /** [VolStream] -> AudioManager stream (AUTO is resolved first by [VolumePlan.stream]). */
        val ANDROID_STREAM: Map<VolStream, Int> = mapOf(
            VolStream.AUTO to AudioManager.STREAM_MUSIC, VolStream.MUSIC to AudioManager.STREAM_MUSIC,
            VolStream.RING to AudioManager.STREAM_RING, VolStream.ALARM to AudioManager.STREAM_ALARM,
            VolStream.NOTIFICATION to AudioManager.STREAM_NOTIFICATION, VolStream.CALL to AudioManager.STREAM_VOICE_CALL,
        )

        /** Wait after making the Canti head non-touchable, so the input windows have updated before the gesture. */
        const val HEAD_CLEAR_MS = 50L
        /** The status bar / shade: its window changes are not the app's ([onWindowEvent]). */
        const val SYSTEM_UI = "com.android.systemui"

        /**
         * When Canti last dispatched a touch gesture ([SystemClock.uptimeMillis]; 0 = never), and when that gesture's
         * strokes end. The phone mic's touch guard (audio/TouchGuard) reads these so Canti's own touches are not taken
         * for the user's. A continued stroke (hold-to-scroll) stamps every segment.
         */
        @Volatile var lastInjectedGestureMs = 0L
            private set
        @Volatile var lastInjectedGestureEndMs = 0L
            private set

        fun swipe(x1: Float, y1: Float, x2: Float, y2: Float, ms: Long): GestureDescription {
            val p = Path().apply { moveTo(x1, y1); lineTo(x2, y2) }
            return GestureDescription.Builder().addStroke(GestureDescription.StrokeDescription(p, 0, ms)).build()
        }

        fun tap(x: Float, y: Float) = press(x, y, 60)

        fun press(x: Float, y: Float, ms: Long): GestureDescription {
            val p = Path().apply { moveTo(x, y) }
            return GestureDescription.Builder().addStroke(GestureDescription.StrokeDescription(p, 0, ms)).build()
        }

        fun doubleTap(x: Float, y: Float): GestureDescription {
            val p = Path().apply { moveTo(x, y) }
            return GestureDescription.Builder()
                .addStroke(GestureDescription.StrokeDescription(p, 0, 50))
                .addStroke(GestureDescription.StrokeDescription(p, 150, 50))
                .build()
        }

        /** Two fingers moving apart (from < to) or together (from > to) along the horizontal axis. */
        fun pinch(cx: Float, cy: Float, from: Float, to: Float): GestureDescription {
            val a = Path().apply { moveTo(cx - from, cy); lineTo(cx - to, cy) }
            val b = Path().apply { moveTo(cx + from, cy); lineTo(cx + to, cy) }
            return GestureDescription.Builder()
                .addStroke(GestureDescription.StrokeDescription(a, 0, 400))
                .addStroke(GestureDescription.StrokeDescription(b, 0, 400))
                .build()
        }
    }
}
