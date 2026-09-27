package ai.vox.companion

/**
 * System-dialog guard (pure; SystemDialogTest). A permission request (TikTok's READ_CONTACTS mid-feed), a role request
 * (Chrome's "default browser?"), the package installer, the app chooser or an "app isn't responding" dialog can come
 * up at any time, over the app the user is steering. While one is in front Canti:
 *  - drops every queued gesture (logged `gesture{result: "dropped (system dialog)"}`);
 *  - refuses every touch: swipes, flings, scrolls, taps, double-taps, long-presses, target taps, cursor clicks and
 *    drags, hold-scroll strokes; it never taps a dialog's buttons;
 *  - still allows back and home (and what touches nothing: volume, media keys, cursor moves);
 *  - shows [BADGE].
 *
 * The signal is the accessibility window list: a window owned by a dialog package ([DIALOG_PACKAGES]: the permission
 * controller, the package installer), or one owned by the system itself ([SYSTEM_OWNERS]: the resolver/chooser, ANR
 * and other system_server dialogs) at or above the top app window. Ordinary overlays (chat heads, Samsung's edge
 * panel, a screen recorder bubble) are TYPE_SYSTEM windows too but are not dialogs: they never block, or Canti would
 * stay blocked while one is shown. SystemUI (bars, the notification shade) and the keyboard never count.
 */
object SystemDialog {
    enum class Kind { APPLICATION, SYSTEM, OTHER }
    /** One accessibility window: its type, owner package (its root's), and layer (higher = in front). */
    data class Win(val kind: Kind, val pkg: String?, val layer: Int)

    val DIALOG_PACKAGES = setOf(
        "com.google.android.permissioncontroller", "com.android.permissioncontroller", "com.samsung.android.permissioncontroller",
        "com.google.android.packageinstaller", "com.android.packageinstaller", "com.samsung.android.packageinstaller",
    )
    /** The system's own windows: ResolverActivity / ChooserActivity, "isn't responding", other system_server dialogs. */
    val SYSTEM_OWNERS = setOf("android", "com.android.intentresolver")
    private val NEVER = setOf("com.android.systemui")

    const val BADGE = "system dialog: back or home only"
    const val REFUSED = "refused: system dialog"

    /** Actions that touch nothing on the screen, allowed over a dialog. Anything else (and any new action) is refused. */
    val ALLOWED = setOf("back", "home", "none", "listen_for_phrase", "volume_up", "volume_down", "play_pause", "next_item",
        "previous_item", "stop", "grid_pick_1", "grid_pick_5", "grid_pick_9", "volume", "open_app", "set_timer")

    fun allows(action: String): Boolean = action in ALLOWED || action.startsWith("move_")

    /** The dialog in front ("com.google.android.permissioncontroller"), or null. [own]: Canti's package. */
    fun detect(windows: List<Win>, own: String): String? {
        val ws = windows.filter { it.pkg != null && it.pkg != own && it.pkg !in NEVER && it.kind != Kind.OTHER }
        ws.firstOrNull { it.pkg in DIALOG_PACKAGES }?.let { return it.pkg }
        val topApp = ws.filter { it.kind == Kind.APPLICATION && it.pkg !in SYSTEM_OWNERS }.maxOfOrNull { it.layer } ?: Int.MIN_VALUE
        return ws.filter { it.pkg in SYSTEM_OWNERS && it.layer >= topApp }.maxByOrNull { it.layer }?.pkg
    }

    /** What the Executor says when it refuses [action]. */
    fun refusal(action: String, dialog: String) = "$REFUSED ($dialog): $action (back or home only)"
}
