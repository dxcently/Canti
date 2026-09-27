package ai.vox.companion.audio

import android.app.Activity
import android.os.Bundle
import android.widget.Button
import android.widget.LinearLayout

/**
 * The small "Sound source" chooser (a dialog-styled activity), opened by the notification's Source button and by
 * [SoundSource.choose]: the same [SoundSourcePanel] as the settings screen, so a mic source asks for the permission
 * with its reason here too. Being a visible Canti screen, it also lets the mic's foreground service start.
 */
class SourceChooserActivity : Activity() {
    private lateinit var panel: SoundSourcePanel

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        title = "Sound source"
        panel = SoundSourcePanel(this, MicSettings(this))
        setContentView(LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 16, 48, 32)
            addView(panel.view)
            addView(Button(this@SourceChooserActivity).apply { text = "Done"; setOnClickListener { finish() } })
        })
    }

    override fun onResume() { super.onResume(); panel.refresh() }

    @Deprecated("Deprecated in Java")
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        panel.onPermissionResult(requestCode)
    }
}
