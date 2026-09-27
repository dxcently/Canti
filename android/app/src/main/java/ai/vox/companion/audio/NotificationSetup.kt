package ai.vox.companion.audio

import android.Manifest
import android.app.Activity
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.provider.Settings
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView

/**
 * The notification permission (Android 13+) for Canti's status notification ([CantiNotification]): asked ONCE, at
 * the first start of the app (next to the accessibility setup), never again. If it is denied or the notifications are
 * blocked, the settings screen shows one line ([row]) with a button to the system's notification settings; no nagging.
 */
object NotificationSetup {
    const val REQ = 7304
    private const val ASKED = "notifications_asked"

    /** Notifications can be shown (permission granted and not blocked for the app). */
    fun enabled(ctx: Context): Boolean =
        ctx.getSystemService(NotificationManager::class.java)?.areNotificationsEnabled() == true

    /** The first start: ask for POST_NOTIFICATIONS once, if needed. */
    fun askOnce(a: Activity) {
        if (Build.VERSION.SDK_INT < 33) return
        val p = a.getSharedPreferences("vox", Context.MODE_PRIVATE)
        if (p.getBoolean(ASKED, false)) return
        p.edit().putBoolean(ASKED, true).apply()
        if (a.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) return
        a.requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), REQ)
    }

    /** "Notification controls are off" + a button to the system settings; hidden while notifications work. */
    class Row(private val a: Activity) {
        val view = LinearLayout(a).apply {
            orientation = LinearLayout.VERTICAL
            addView(TextView(a).apply {
                text = "Notification controls are off: Canti's notification (Pause, mode and sound source buttons) is not shown."
            })
            addView(Button(a).apply {
                text = "Open notification settings"
                setOnClickListener {
                    a.startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, a.packageName))
                }
            })
        }

        fun refresh() {
            view.visibility = if (enabled(a)) android.view.View.GONE else android.view.View.VISIBLE
            if (enabled(a)) CantiNotification.repost()
        }
    }
}
