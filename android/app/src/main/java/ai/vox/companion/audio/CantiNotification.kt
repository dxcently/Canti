package ai.vox.companion.audio

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import ai.vox.companion.EventLog
import ai.vox.companion.MainActivity
import ai.vox.companion.R
import ai.vox.companion.VoxService

/**
 * Canti's persistent notification, for every sound source, while the accessibility service runs:
 *
 *   Canti · Pico listening            Gesture mode             [Cursor mode] [Pause] [Source]
 *   Canti is listening · Phone mic    Cursor mode · USB ...    [Gesture mode] [Pause] [Source]
 *   Canti · paused                    Phone mic · Gesture mode [Cursor mode] [Resume] [Source]
 *
 * - With a mic source and the mic's foreground service up, it is that service's notification ([MicListenService],
 *   id [FGS_ID]); otherwise (Pico, or the mic service not started yet) a plain ongoing notification ([PLAIN_ID]).
 *   Only a phone/USB source holds the microphone.
 * - Buttons: mode (the service's [VoxService.setMode]: a device command to the Pico, or local with a mic source),
 *   pause/resume ([VoxService.setPaused]; **Wake** in its place while the Pico sits paused after a link drop:
 *   [VoxService.wakeDevice], the badge's tap-to-wake), and Source, which opens the small chooser ([SourceChooserActivity]; picking a
 *   mic there can ask for the permission and start the mic's service, which Android 14 allows from a visible screen).
 * - The service calls [start] / [stop]; [refresh] re-renders (it only posts when the text changed), and a 2 s poll
 *   follows the Bluetooth link's state without hooks in the BLE code.
 */
object CantiNotification {
    const val CHANNEL = "vox_mic"
    const val FGS_ID = 7301
    const val PLAIN_ID = 7303
    private const val ACTION_MODE = "ai.vox.companion.NOTIF_MODE"
    private const val ACTION_PAUSE = "ai.vox.companion.NOTIF_PAUSE"
    private const val ACTION_RESUME = "ai.vox.companion.NOTIF_RESUME"
    private const val ACTION_WAKE = "ai.vox.companion.NOTIF_WAKE"
    private const val POLL_MS = 2000L

    /** What the notification shows; the service builds it ([VoxService.notificationState]). */
    data class State(val source: String, val paused: Boolean, val armed: Boolean, val mode: String,
                     val device: String?, val micState: String?, val micDevice: String?,
                     /** The Pico is connected and paused only by a link drop (DeviceLink.wakeable): Wake replaces Pause. */
                     val wakeable: Boolean = false)

    private val main = Handler(Looper.getMainLooper())
    private var ctx: Context? = null
    private var state: (() -> State)? = null
    private var shown: Pair<Int, State>? = null
    private val poll = object : Runnable { override fun run() { refresh(); main.postDelayed(this, POLL_MS) } }

    /** The service is up (main thread). */
    fun start(ctx: Context, state: () -> State) {
        this.ctx = ctx.applicationContext; this.state = state; shown = null
        main.removeCallbacks(poll); main.post(poll)
    }

    /** The service is going away: remove the plain notification (the mic's service removes its own). */
    fun stop() {
        main.removeCallbacks(poll)
        ctx?.getSystemService(NotificationManager::class.java)?.cancel(PLAIN_ID)
        ctx = null; state = null; shown = null
    }

    /** Re-render now, from any thread. */
    fun refresh() {
        if (Looper.myLooper() != Looper.getMainLooper()) { main.post { refresh() }; return }
        val c = ctx ?: return
        val s = try { state?.invoke() } catch (e: Exception) { null } ?: return
        val nm = c.getSystemService(NotificationManager::class.java) ?: return
        val id = if (MicListenService.running) FGS_ID else PLAIN_ID
        if (shown == id to s) return
        if (id == FGS_ID) nm.cancel(PLAIN_ID)
        try { nm.notify(id, build(c, s)) } catch (e: Exception) { EventLog.ev("error", "where" to "notification", "error" to e.toString()) }
        shown = id to s
    }

    /** Post again even if unchanged (notifications were just allowed). */
    fun repost() { shown = null; refresh() }

    /** The notification for the mic's foreground service to start with. */
    fun forService(c: Context): Notification = build(c, state?.invoke() ?: State(MicSettings(c).source, false, true, "gesture", null, null, null))

    fun title(s: State): String {
        val src = MicSettings.LABELS[s.source] ?: s.source
        return when {
            s.paused -> "Canti · paused"
            s.wakeable -> "Canti · Pico paused (link lost): tap Wake"
            !s.armed -> "Canti · off"
            s.source == MicSettings.PICO -> "Canti · Pico ${s.device ?: "not set up"}"
            s.micState == "listening" -> "Canti is listening · $src"
            else -> "Canti · $src: ${s.micState ?: "off"}"
        }
    }

    fun body(s: State): String {
        val mode = if (s.mode == "cursor") "Cursor mode" else "Gesture mode"
        val src = when {
            s.source == MicSettings.PICO -> "Pico (Bluetooth)"
            s.micDevice != null -> s.micDevice
            else -> MicSettings.LABELS[s.source] ?: s.source
        }
        return "$mode · $src"
    }

    private fun build(c: Context, s: State): Notification {
        val nm = c.getSystemService(NotificationManager::class.java)
        if (nm.getNotificationChannel(CHANNEL) == null)
            nm.createNotificationChannel(NotificationChannel(CHANNEL, "Canti status", NotificationManager.IMPORTANCE_LOW).apply {
                description = "Canti's sound source and mode, with Pause, mode and source buttons"
                setShowBadge(false)
            })
        val flags = PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        fun broadcast(code: Int, action: String) =
            PendingIntent.getBroadcast(c, code, Intent(c, Receiver::class.java).setAction(action), flags)
        val open = PendingIntent.getActivity(c, 0, Intent(c, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), flags)
        val source = PendingIntent.getActivity(c, 3, Intent(c, SourceChooserActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK), flags)
        return Notification.Builder(c, CHANNEL)
            .setSmallIcon(R.drawable.ic_launcher_mono_on)
            .setContentTitle(title(s))
            .setContentText(body(s))
            .setContentIntent(open)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(Notification.CATEGORY_SERVICE)
            .setForegroundServiceBehavior(Notification.FOREGROUND_SERVICE_IMMEDIATE)
            .addAction(Notification.Action.Builder(null, if (s.mode == "cursor") "Gesture mode" else "Cursor mode", broadcast(1, ACTION_MODE)).build())
            .addAction(if (s.wakeable) Notification.Action.Builder(null, "Wake", broadcast(4, ACTION_WAKE)).build()
                else Notification.Action.Builder(null, if (s.paused) "Resume" else "Pause",
                    broadcast(2, if (s.paused) ACTION_RESUME else ACTION_PAUSE)).build())
            .addAction(Notification.Action.Builder(null, "Source", source).build())
            .build()
    }

    /** The mode and pause buttons (not exported: only this app's PendingIntents reach it). */
    class Receiver : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            val svc = VoxService.instance ?: return
            when (intent.action) {
                ACTION_MODE -> svc.toggleMode("notification")
                ACTION_PAUSE -> svc.setPaused(true, "notification")
                ACTION_RESUME -> svc.setPaused(false, "notification")
                ACTION_WAKE -> svc.wakeDevice("notification")
            }
            refresh()
        }
    }
}
