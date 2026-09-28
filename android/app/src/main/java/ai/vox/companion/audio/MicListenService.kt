package ai.vox.companion.audio

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.IBinder
import ai.vox.companion.EventLog

/**
 * The foreground service (type `microphone`) that lets Canti use the mic while it is not on screen. Its notification
 * is Canti's status notification ([CantiNotification]: "Canti is listening · Phone mic", mode / Pause / Source).
 *
 * It holds no audio itself: the capture ([MicCapture]) runs in the same process, owned by [PhoneMicSource] inside
 * the accessibility service. Android grants a background process mic access only through a foreground service of
 * this type, started while the app is visible (Android 14: FOREGROUND_SERVICE_MICROPHONE + RECORD_AUDIO, and the
 * while-in-use rule), so PhoneMicSource starts it when a phone/USB source is picked or a Canti screen resumes, and
 * keeps it for as long as that source is selected; a pause only closes the AudioRecord.
 */
class MicListenService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val err = try {
            startForeground(CantiNotification.FGS_ID, CantiNotification.forService(this), ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
            null
        } catch (e: Exception) { e.toString() }
        running = err == null
        EventLog.ev("mic_service", "state" to if (err == null) "foreground" else "refused", "error" to err)
        PhoneMicSource.current?.serviceStarted(err)
        CantiNotification.refresh()
        if (err != null) stopSelf()
        return START_NOT_STICKY   // restarted by PhoneMicSource (from the UI), never by the system in the background
    }

    override fun onDestroy() {
        running = false
        PhoneMicSource.current?.serviceDestroyed()
        CantiNotification.refresh()   // back to the plain notification
        super.onDestroy()
    }

    companion object {
        @Volatile var running = false; private set

        /** Start from a visible screen (or wherever Android allows it). Throws what startForegroundService throws. */
        fun start(ctx: Context) {
            ctx.startForegroundService(Intent(ctx, MicListenService::class.java))
        }

        fun stop(ctx: Context) {
            running = false
            ctx.stopService(Intent(ctx, MicListenService::class.java))
        }
    }
}
