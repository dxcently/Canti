package ai.vox.companion.audio

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.pm.PackageManager
import android.widget.LinearLayout
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.TextView
import ai.vox.companion.VoxService

/**
 * The "Sound source" block of the settings screen: Pico (Bluetooth) | Phone mic | USB mic, the microphone
 * permission (asked with its reason when a mic source is picked), and the mic's live state.
 *
 * Picking a mic source here, while the screen is visible, is also what lets the foreground service start
 * (Android 14's while-in-use rule for the mic).
 */
class SoundSourcePanel(private val activity: Activity, private val settings: MicSettings) {
    private val state = TextView(activity)
    private val group = RadioGroup(activity)
    private var pending: String? = null

    val view = LinearLayout(activity).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(0, 24, 0, 24)
        addView(TextView(activity).apply { text = "Sound source"; textSize = 18f })
        addView(TextView(activity).apply {
            text = "Where Canti hears your sounds. Phone mic and USB mic run the same sound extractor as the Pico, on " +
                "this phone. Audio never leaves the phone and is never saved: only the sound descriptions are used."
        })
        for (src in MicSettings.SOURCES) group.addView(RadioButton(activity).apply {
            id = 1000 + MicSettings.SOURCES.indexOf(src)
            text = MicSettings.LABELS[src]
        })
        addView(group)
        addView(state)
    }

    init {
        group.check(1000 + MicSettings.SOURCES.indexOf(settings.source))
        group.setOnCheckedChangeListener { _, id -> pick(MicSettings.SOURCES[id - 1000]) }
        refresh()
    }

    private fun granted(p: String) = activity.checkSelfPermission(p) == PackageManager.PERMISSION_GRANTED

    private fun pick(src: String) {
        if (src == settings.source) return
        if (src == MicSettings.PICO || granted(Manifest.permission.RECORD_AUDIO)) { apply(src); return }
        pending = src
        AlertDialog.Builder(activity)
            .setTitle("Allow the microphone")
            .setMessage("To hear your hums, pops and clicks without the VOX device, Canti needs the microphone. " +
                "The sound is analysed on this phone as it comes in; it is not recorded, saved or sent anywhere. " +
                "Android shows the microphone indicator while Canti listens, and a notification with a Pause button.")
            .setPositiveButton("Continue") { _, _ ->
                activity.requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), REQ_MIC)
            }
            .setNegativeButton("Cancel") { _, _ -> pending = null; revert() }
            .setOnCancelListener { pending = null; revert() }
            .show()
    }

    private fun apply(src: String) {
        if (!SoundSource.set(activity, src, activity.javaClass.simpleName)) revert()
        // Pico with no device remembered yet: straight to pairing (a radio button already checked fires nothing, so
        // re-picking the current source never gets here)
        else if (src == MicSettings.PICO) ai.vox.companion.Pairing.openIfNoDevice(activity, activity.javaClass.simpleName)
        refresh()
    }

    private fun revert() { group.check(1000 + MicSettings.SOURCES.indexOf(settings.source)) }

    /** Route the activity's onRequestPermissionsResult here; true if it was ours. */
    fun onPermissionResult(requestCode: Int): Boolean {
        if (requestCode != REQ_MIC) return false
        val src = pending; pending = null
        if (src != null && granted(Manifest.permission.RECORD_AUDIO)) apply(src)
        else { revert(); refresh() }
        return true
    }

    fun refresh() {
        PhoneMicSource.onAppVisible()
        val mic = PhoneMicSource.current
        state.text = when {
            VoxService.instance == null -> "Canti's accessibility service is off."
            settings.source == MicSettings.PICO -> "Listening through the VOX device (Bluetooth)."
            !granted(Manifest.permission.RECORD_AUDIO) -> "Microphone not allowed yet: pick the source again to allow it."
            mic == null -> "Microphone source not running."
            else -> "Microphone: ${mic.state}" + (mic.status().optString("routed").takeIf { it.isNotBlank() && it != "null" }?.let { " ($it)" } ?: "")
        }
    }

    companion object { const val REQ_MIC = 7302 }
}
