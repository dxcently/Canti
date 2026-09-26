package ai.vox.companion

import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.provider.Settings as SystemSettings
import android.text.InputType
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

/**
 * The native settings screen (decider mode, model endpoint, API key, Bluetooth permissions, a link to accessibility
 * settings), from before the Flutter UI. Opened from the Flutter status screen ("Legacy settings") until Flutter
 * screens replace it.
 */
class LegacySettingsActivity : Activity() {
    private lateinit var s: Settings
    private lateinit var status: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        s = Settings(this)
        val col = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(40, 60, 40, 40) }
        status = TextView(this).apply { textSize = 16f }
        col.addView(status)
        col.addView(Button(this).apply {
            text = "Open accessibility settings"
            setOnClickListener { startActivity(Intent(SystemSettings.ACTION_ACCESSIBILITY_SETTINGS)) }
        })
        // Minimal permission path for the BLE link to the VOX device (the real setup screen is future UI work).
        col.addView(Button(this).apply {
            text = "Allow Bluetooth (VOX device)"
            setOnClickListener { requestPermissions(BleFeatureSource.runtimePermissions(), REQ_BLE) }
        })
        fun field(label: String, value: String, password: Boolean = false): EditText {
            col.addView(TextView(this).apply { text = label })
            return EditText(this).apply {
                setText(value); isSingleLine = true
                if (password) inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
                col.addView(this)
            }
        }
        val decider = field("Decider: rules | model | hybrid", s.decider)
        val base = field("Model base URL (POST {base}/v1/systemone)", s.baseUrl)
        val model = field("Model", s.model)
        val key = field("API key (stored on this device only; blank for a local server)", s.apiKey, password = true)
        val conf = field("Minimum confidence", s.minConfidence.toString())
        col.addView(Button(this).apply {
            text = "Save"
            setOnClickListener {
                val d = decider.text.toString().trim()
                if (d in setOf("rules", "model", "hybrid")) s.decider = d
                s.baseUrl = base.text.toString().trim()
                s.model = model.text.toString().trim()
                s.apiKey = key.text.toString().trim()
                conf.text.toString().toDoubleOrNull()?.let { s.minConfidence = it }
                refresh()
                status.append("\nSaved. Toggle the service off and on to apply.")
            }
        })
        setContentView(ScrollView(this).apply { addView(col) })
    }

    override fun onResume() { super.onResume(); refresh() }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQ_BLE) { VoxService.instance?.blePermissionsChanged(); refresh() }
    }

    private fun bleGranted() = BleFeatureSource.runtimePermissions().all { checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED }

    private fun refresh() {
        status.text = "VOX companion\nService: ${if (VoxService.instance != null) "running" else "off (enable VOX in Accessibility)"}\n" +
            "Decider: ${s.decider}   Vocabulary: ${Vocab.SOURCE_DIGEST}\n" +
            "Bluetooth: ${if (bleGranted()) "allowed" else "not allowed yet"}   Device: ${s.bleDevice ?: "none remembered"}"
    }

    companion object { private const val REQ_BLE = 1 }
}
