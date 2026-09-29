package ai.vox.companion

/**
 * The status screen's bindings window (PROTOCOL.md "UI channel", the `bindings` key): the effective sound -> action
 * for each mode, resolved the way [RuleDecider] resolves it, so the window shows the user's own rules on top of the
 * Vocab defaults instead of a hard-coded picture. Display-only: nothing here changes what acts.
 *
 * Resolution mirrors [RuleDecider]:
 * - gesture mode: the app's rule, else the global rule, else [Vocab.DEFAULT_BINDINGS], else
 *   [Vocab.APP_ONLY_BINDINGS] (the last rule for a sequence wins, as in [RuleDecider.gesture]);
 * - cursor mode: a cursor rule, else the built-in single-sound cursor (hums move the cursor, a flat hum stops,
 *   a click taps, a short hiss goes back, a long hiss listens — [CursorListen], which the app owns). Multi-sound cursor
 *   rules still parse but never fire (cursor mode has no waits), so the window shows no cursor combos.
 * With a phone or USB mic in cursor mode the voice joystick drives ([VoiceJoystick.PASS]): hum gestures never reach
 * the decider (a hum steers the cursor continuously), so rise/fall/arch/dip/flat show "steers the joystick" and a
 * cursor rule on them is not shown (it never fires).
 * A lone click has no default in gesture mode on a phone or USB mic ([MicPopGate.unbound]): it taps only where the
 * user binds it, so the window says so rather than echoing the Pico's default.
 *
 * The result is plain maps/lists (the Flutter channel codec's types), one entry per sound `{label, source}` (null =
 * unbound) and one per combo `{seq, label, source}`. `source` marks a user rule (`global`, `app`, `cursor`) apart from
 * `default` and `app-only`; `label` is the action's option text ([Vocab.ACTIONS] / [Vocab.CURSOR_ACTIONS], or the
 * concise built-in cursor wording). The cursor-mode hiss entry also carries `long` ("listen for a name").
 */
object Bindings {
    /** The single sounds shown as glyphs, in order (contours then discrete). No "pop" glyph: a pop is a click. */
    val SOUNDS = listOf("rise", "fall", "arch", "dip", "flat", "click", "hiss")

    /** `{gesture: {sounds, combos, note}, cursor: {sounds, combos, note}}` for the current app and profile. */
    fun view(profile: Profile, pkg: String, micSource: Boolean): Map<String, Any?> = mapOf(
        "gesture" to mode(profile, pkg, "gesture", micSource),
        "cursor" to mode(profile, pkg, "cursor", micSource),
    )

    private fun mode(profile: Profile, pkg: String, m: String, micSource: Boolean): Map<String, Any?> {
        val sounds = SOUNDS.associateWith { s ->
            if (m == "cursor") cursorSound(profile, s, micSource) else gestureSound(profile, pkg, s, micSource)
        }
        val combos = if (m == "cursor") cursorCombos(profile) else gestureCombos(profile, pkg)
        val note = if (m == "cursor" && micSource) JOYSTICK_NOTE else null
        return mapOf("sounds" to sounds, "combos" to combos, "note" to note)
    }

    /** One resolved binding as `{label, source}`; null when the sound is unbound. */
    private fun entry(label: String?, source: String?): Map<String, Any?>? =
        if (label == null) null else mapOf("label" to label, "source" to source)

    private fun gestureSound(profile: Profile, pkg: String, sound: String, micSource: Boolean): Map<String, Any?>? {
        val seq = listOf(sound)
        profile.appBindings(pkg).lastOrNull { it.phrase == seq }?.let { return binding(it, "app") }
        profile.globalBindings().lastOrNull { it.phrase == seq }?.let { return binding(it, "global") }
        // A phone/USB mic's lone click has no default action (MicPopGate.unbound): say so, don't echo "tap".
        if (sound == "click" && micSource) return entry("tap if bound", "default")
        Vocab.DEFAULT_BINDINGS[seq]?.let { return entry(actionText(it, cursor = false), "default") }
        Vocab.APP_ONLY_BINDINGS[seq]?.let { return entry(actionText(it, cursor = false), "app-only") }
        return null
    }

    private fun cursorSound(profile: Profile, sound: String, micSource: Boolean): Map<String, Any?>? {
        // Phone/USB mic: the joystick drops hum gestures before any rule is looked at (VoiceJoystick.filter).
        if (micSource && sound !in VoiceJoystick.PASS) return entry(JOYSTICK, "default")
        // A hiss is back and a long hiss listens (CursorListen): the `long` key says so on the window's hiss entry,
        // whatever its label (a cursor rule on ["hiss"] applies only to short hisses, but its `long` still applies).
        if (sound == "hiss") {
            val rule = profile.cursorBindings().lastOrNull { it.phrase == listOf("hiss") }
            return (rule?.let { binding(it, "cursor") } ?: entry("back", "default"))?.plus("long" to CURSOR_LISTEN_LABEL)
        }
        profile.cursorBindings().lastOrNull { it.phrase == listOf(sound) }?.let { return binding(it, "cursor") }
        // The built-in single-sound cursor (RuleDecider.cursor). "click" is bound.
        return when (sound) {
            "rise" -> entry("cursor up", "default")
            "fall" -> entry("cursor down", "default")
            "arch" -> entry("cursor right", "default")
            "dip" -> entry("cursor left", "default")
            "flat" -> entry("stop", "default")
            "click" -> entry("click", "default")
            else -> null
        }
    }

    /** Gesture-mode combos: the default and app-only two-sound sequences, with the user's global and app rules on top. */
    private fun gestureCombos(profile: Profile, pkg: String): List<Map<String, Any?>> {
        val table = LinkedHashMap<List<String>, String?>()
        val src = LinkedHashMap<List<String>, String>()
        for ((seq, a) in Vocab.DEFAULT_BINDINGS) { table[seq] = a; src[seq] = "default" }
        for ((seq, a) in Vocab.APP_ONLY_BINDINGS) { table[seq] = a; src[seq] = "app-only" }
        for (b in profile.globalBindings()) { table[b.phrase] = b.action ?: RULE; src[b.phrase] = "global" }
        for (b in profile.appBindings(pkg)) { table[b.phrase] = b.action ?: RULE; src[b.phrase] = "app" }
        return table.entries.filter { it.key.size > 1 && it.value != "none" }.map { (seq, a) ->
            mapOf("seq" to seq, "label" to comboLabel(a), "source" to src[seq])
        }
    }

    /**
     * Cursor-mode combos: none. Multi-sound cursor rules never fire in cursor mode (the sequencer never waits there:
     * a click taps at once, a short hiss is back, a long hiss listens — user decision 2026-09-28), so the window shows
     * no combos.
     */
    private fun cursorCombos(profile: Profile): List<Map<String, Any?>> = emptyList()

    /** A phone/USB mic's hum in cursor mode: it steers the voice joystick, it is not a gesture. */
    const val JOYSTICK = "steers cursor"
    const val JOYSTICK_NOTE = "voice joystick: a hum's pitch moves the cursor up / down, its vowel sideways"

    /** A long hiss in cursor mode: the listening window for a spoken target name (the intent cursor). */
    const val CURSOR_LISTEN_LABEL = "listen for a name"

    /** A profile binding as `{label, source}`: its fixed action's text, or "ignored" / the rule's own sentence. */
    private fun binding(b: Binding, source: String): Map<String, Any?>? = when {
        b.action == "none" -> entry("ignored", source)
        b.action != null -> entry(actionText(b.action, cursor = source == "cursor"), source)
        else -> entry(b.rule ?: "custom rule", source)
    }

    /** The window's short label for an action (D186): SHORT / CURSOR_SHORT, else the option text, else the key. */
    internal fun actionText(action: String, cursor: Boolean): String =
        (if (cursor) CURSOR_SHORT[action] ?: Vocab.CURSOR_ACTIONS[action]
         else SHORT[action] ?: Vocab.ACTIONS[action] ?: Vocab.APP_ONLY_ACTIONS[action]) ?: action

    /**
     * Short labels for the window (user 2026-09-28: "short labels are fine"). Display only: the models still see
     * [Vocab.ACTIONS] / [Vocab.CURSOR_ACTIONS] option text.
     */
    val SHORT: Map<String, String> = mapOf(
        "tap" to "tap", "double_tap" to "double-tap", "long_press" to "hold", "back" to "back", "home" to "home",
        "forward" to "forward", "recents" to "recents", "notifications" to "notifications",
        "scroll_up" to "scroll up", "scroll_down" to "scroll down", "next_item" to "next", "previous_item" to "previous",
        "play_pause" to "play / pause", "volume_up" to "volume up", "volume_down" to "volume down",
        "open_camera" to "camera", "take_photo" to "photo", "like" to "like", "listen_for_phrase" to "listen",
    )
    val CURSOR_SHORT: Map<String, String> = mapOf(
        "stop" to "stop", "click" to "click", "drag_toggle" to "drag", "back" to "back",
        "grid_pick_1" to "grid: top-left", "grid_pick_5" to "grid: centre", "grid_pick_9" to "grid: bottom-right",
    )

    /** A combo's label: its fixed action's text, or "custom rule" for a plain-language rule (the model decides). */
    private fun comboLabel(a: String?): String =
        if (a == null || a == RULE) "custom rule" else actionText(a, cursor = false)

    /** The sentinel [Profile.sequences] uses for a plain-language rule (its action is not fixed). */
    private const val RULE = "\u0000rule"
}
