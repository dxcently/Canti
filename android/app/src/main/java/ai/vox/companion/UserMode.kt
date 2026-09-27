package ai.vox.companion

/**
 * The mode the user last chose themselves (gesture or cursor), so a wake after a link drop puts the Pico back in it and
 * not in whatever a test tool or console left set.
 *
 * Saved (SharedPreferences `canti_device/user_mode`, default `gesture`) only when a mode change from one of the user's
 * own controls ([USER_PATHS]: the badge menu, the notification, the status screen) is confirmed, or when the Pico reports
 * that its button changed the mode (a state message with `"by":"button"`, PROTOCOL.md). Debug ops (`device`), test
 * tools and the Pico's console reach the app as direct link commands or untagged state messages and never count. Logged `user_mode{mode, by, result: saved | unchanged | ignored}`.
 */
class UserMode(private val store: Store) {
    interface Store {
        fun load(): String?
        fun save(mode: String)
        fun log(ev: String, vararg fields: Pair<String, Any?>) {}
    }

    var mode: String = store.load()?.takeIf { it in DeviceLink.Command.MODES } ?: DEFAULT; private set

    /** A confirmed mode change [by] one of the phone's controls; saved only when [by] is one of the user's own. */
    fun chose(mode: String, by: String): Boolean {
        val result = when {
            by !in USER_PATHS || mode !in DeviceLink.Command.MODES -> "ignored"
            mode == this.mode -> "unchanged"
            else -> { this.mode = mode; store.save(mode); "saved" }
        }
        store.log("user_mode", "mode" to mode, "by" to by, "result" to result)
        return result == "saved"
    }

    /** The wake: arm, plus the user's mode when the device's last word ([deviceMode]) differs. One write, one confirmation. */
    fun wakeCommand(deviceMode: String?) = DeviceLink.Command(armed = true, mode = mode.takeIf { it != deviceMode })

    companion object {
        const val DEFAULT = "gesture"
        val USER_PATHS = setOf("badge", "notification", "status-screen", "button")
    }
}
