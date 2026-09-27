package ai.vox.companion.audio

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Handler
import android.os.Looper
import ai.vox.companion.EventLog
import ai.vox.companion.VoxService
import java.util.concurrent.CopyOnWriteArrayList

/**
 * The one API for the `sound_source` setting (Pico (Bluetooth) | Phone mic | USB mic), for every UI that switches it:
 * the settings screen ([SoundSourcePanel]), the notification ([CantiNotification]), the floating badge's menu.
 *
 *     SoundSource.get(ctx)                     -> "pico" | "phone" | "usb"
 *     SoundSource.set(ctx, "phone", "badge")   -> true: applied; false: needs the mic permission (call choose())
 *     SoundSource.choose(ctx)                  // opens the small chooser dialog (asks for the permission there)
 *     SoundSource.next(src)                    // pico -> phone -> usb -> pico (a cycle button)
 *     SoundSource.label(src)                   // "Pico (Bluetooth)", "Phone mic", "USB mic"
 *     SoundSource.micState()                   // the mic's state line ("listening", "waiting for a USB mic", ...), or null
 *     SoundSource.addListener(l); removeListener(l)   // l(source) on the main thread after every change
 *
 * [set] is safe from any thread and from the background (the accessibility service, a notification action). The mic's
 * foreground service may still need a visible Canti screen to start on Android 14; the mic state then says
 * "open Canti to start the mic" and it starts on the next resume.
 */
object SoundSource {
    const val PICO = MicSettings.PICO
    const val PHONE = MicSettings.PHONE
    const val USB = MicSettings.USB
    val SOURCES = MicSettings.SOURCES

    fun interface Listener { fun onSourceChanged(source: String) }

    private val listeners = CopyOnWriteArrayList<Listener>()
    private val main = Handler(Looper.getMainLooper())

    fun get(ctx: Context): String = MicSettings(ctx).source

    fun label(src: String): String = MicSettings.LABELS[src] ?: src

    fun next(src: String): String = SOURCES[(SOURCES.indexOf(src) + 1).mod(SOURCES.size)]

    fun micState(): String? = PhoneMicSource.current?.state

    fun hasMicPermission(ctx: Context) =
        ctx.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

    /**
     * Switch to [src] ([by] goes to the event log). A mic source without the RECORD_AUDIO permission is not applied:
     * returns false, and the caller opens [choose] (which explains and asks). Same source = true, nothing happens.
     */
    fun set(ctx: Context, src: String, by: String): Boolean {
        require(src in SOURCES) { "sound source must be one of $SOURCES, got '$src'" }
        val s = MicSettings(ctx)
        if (src == s.source) return true
        if (src != PICO && !hasMicPermission(ctx)) return false
        s.source = src
        EventLog.ev("sound_source", "source" to src, "by" to by)
        changed(src)
        return true
    }

    /** The chooser dialog ([SourceChooserActivity]); works from the background (the accessibility service may start activities). */
    fun choose(ctx: Context) {
        ctx.startActivity(Intent(ctx, SourceChooserActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    fun addListener(l: Listener) { listeners.addIfAbsent(l) }
    fun removeListener(l: Listener) { listeners.remove(l) }

    /** After the setting was written: the service applies it (and calls [notifyListeners]); without it, just tell the listeners. */
    private fun changed(src: String) = onMain {
        val svc = VoxService.instance
        if (svc != null) svc.soundSourceChanged() else notifyListeners(src)
    }

    /** Called by the service once a change is applied (whoever wrote the setting, op `config` included). Main thread. */
    fun notifyListeners(src: String) {
        CantiNotification.refresh()
        for (l in listeners) try { l.onSourceChanged(src) } catch (e: Exception) {
            EventLog.ev("error", "where" to "sound source listener", "error" to e.toString())
        }
    }

    private fun onMain(r: () -> Unit) { if (Looper.myLooper() == Looper.getMainLooper()) r() else main.post(r) }
}
