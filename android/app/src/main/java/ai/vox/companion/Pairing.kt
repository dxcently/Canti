package ai.vox.companion

import android.content.Context
import android.content.Intent
import ai.vox.companion.audio.MicSettings

/**
 * The first-run pairing screen (Flutter `PairScreen`, ../ui/lib/src/pair_screen.dart): opened from the status screen's
 * "Find my Canti device" button, and from the badge menu and the sound-source chooser when the Pico is picked but no
 * device is remembered yet. The route travels to Flutter as the MainActivity extra [EXTRA_ROUTE] ([UiBridge] hands it
 * over: `launchRoute` on a cold start, `openRoute` to a running UI).
 */
object Pairing {
    const val EXTRA_ROUTE = "canti_route"
    const val ROUTE_PAIR = "pair"
    /** The voice joystick's calibration (Flutter setup screen, ../ui/lib/src/calibration.dart): the badge menu's CALIBRATE. */
    const val ROUTE_CALIBRATE = "calibrate"

    /**
     * The user refused the Bluetooth permissions with "don't ask again" (the last request came back denied without a
     * rationale): the screen offers the app's settings page instead of the permission dialog. Set by [UiBridge].
     */
    @Volatile var permissionBlocked = false

    /** A Pico is the sound source and no device is remembered: pairing is the next step. Pure (PairingTest). */
    fun needsSetup(source: String, remembered: String?) = source == MicSettings.PICO && remembered == null

    /** Opens the pairing screen (from the service or a notification: a new task, or the running UI's top). */
    fun open(ctx: Context, by: String) = openRoute(ctx, ROUTE_PAIR, by)

    /** Opens the UI on [route] ([ROUTE_PAIR], [ROUTE_CALIBRATE]): a new task, or the running UI's top. */
    fun openRoute(ctx: Context, route: String, by: String) {
        EventLog.ev("ui", "what" to if (route == ROUTE_PAIR) "open_pairing" else "open_$route", "by" to by)
        ctx.startActivity(Intent(ctx, MainActivity::class.java).putExtra(EXTRA_ROUTE, route)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP))
    }

    /** [open] when [needsSetup]; true if it opened. Call after the source was set (badge menu, source chooser). */
    fun openIfNoDevice(ctx: Context, by: String): Boolean {
        val s = Settings(ctx)
        if (!needsSetup(s.mic.source, s.bleDevice)) return false
        open(ctx, by)
        return true
    }
}
