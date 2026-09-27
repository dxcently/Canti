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
 * The native settings screen (decider mode, model endpoint, API key, the cloud model for decider "escalate" with a
 * "Test connection" button, Bluetooth permissions, a link to accessibility settings), from before the Flutter UI. Opened from the Flutter status screen ("Legacy settings") until Flutter
 * screens replace it.
 */
class LegacySettingsActivity : Activity() {
    private lateinit var s: Settings
    private lateinit var status: TextView
    private lateinit var sound: ai.vox.companion.audio.SoundSourcePanel   // [phone-mic]
    private lateinit var notif: ai.vox.companion.audio.NotificationSetup.Row   // [phone-mic]

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        s = Settings(this)
        val col = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(40, 60, 40, 40) }
        status = TextView(this).apply { textSize = 16f }
        col.addView(status)
        sound = ai.vox.companion.audio.SoundSourcePanel(this, s.mic).also { col.addView(it.view) }   // [phone-mic]
        col.addView(Button(this).apply {
            text = "Open accessibility settings"
            setOnClickListener { startActivity(Intent(SystemSettings.ACTION_ACCESSIBILITY_SETTINGS)) }
        })
        // [phone-mic] next to the accessibility step: one line when the notification controls are off
        notif = ai.vox.companion.audio.NotificationSetup.Row(this).also { col.addView(it.view) }
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
        val decider = field("Decider: ${Settings.DECIDERS.joinToString(" | ")}", s.decider)
        val base = field("Model base URL (POST {base}/v1/systemone)", s.baseUrl)
        val model = field("Model", s.model)
        val key = field("API key (stored on this device only; blank for a local server)", s.apiKey, password = true)
        val conf = field("Minimum confidence", s.minConfidence.toString())
        val scrollPct = field("Hold-to-scroll speed (% of the screen height per second, 2-60; rise/fall, then hold a flat hum)", s.autoScrollPct.toString())
        // Cloud model for decider "escalate". The saved key is never shown: an empty field keeps it.
        val oEndpoint = field("Cloud endpoint (Ollama chat API, POST {endpoint}/api/chat)", s.ollamaEndpoint)
        val oModel = field("Cloud model", s.ollamaModel)
        val oKey = field("Cloud API key (encrypted on this device; empty keeps the saved key)", "", password = true)
        oKey.hint = if (s.ollamaKey.isBlank()) "not set" else "set"
        val oStatus = TextView(this)
        col.addView(Button(this).apply {
            text = "Test connection"
            setOnClickListener {
                val key = oKey.text.toString().trim().ifEmpty { s.ollamaKey }
                val client = OllamaClient(oEndpoint.text.toString().trim(), oModel.text.toString().trim(), { key })
                oStatus.text = "Testing ${client.model}..."
                Thread {
                    val msg = try {
                        val a = client.choice("Answer with the key only.", OllamaClient.userMessage("Is this a test?", listOf("yes" to "yes", "no" to "no")),
                            listOf("yes", "no"), listOf("yes", "no"), 10_000)
                        "OK: ${client.model} answered '${a.key}' in ${a.ms} ms"
                    } catch (e: Exception) { "Failed: ${e.javaClass.simpleName}: ${e.message?.take(160)}" }
                    runOnUiThread { oStatus.text = msg }
                }.start()
            }
        })
        col.addView(oStatus)
        col.addView(Button(this).apply {
            text = "Clear cloud API key"
            setOnClickListener { s.ollamaKey = ""; oKey.hint = "not set"; oStatus.text = "Cloud key cleared." }
        })
        col.addView(Button(this).apply {
            text = "Save"
            setOnClickListener {
                val d = decider.text.toString().trim()
                if (d in Settings.DECIDERS) s.decider = d
                s.baseUrl = base.text.toString().trim()
                s.model = model.text.toString().trim()
                s.apiKey = key.text.toString().trim()
                conf.text.toString().toDoubleOrNull()?.let { s.minConfidence = it }
                scrollPct.text.toString().toIntOrNull()?.let { s.autoScrollPct = it; scrollPct.setText(s.autoScrollPct.toString()) }
                s.ollamaEndpoint = oEndpoint.text.toString().trim()
                s.ollamaModel = oModel.text.toString().trim()
                oKey.text.toString().trim().takeIf { it.isNotEmpty() }?.let { s.ollamaKey = it; oKey.setText(""); oKey.hint = "set" }
                refresh()
                status.append("\nSaved. Toggle the service off and on to apply.")
            }
        })
        setContentView(ScrollView(this).apply { addView(col) })
    }

    override fun onResume() { super.onResume(); refresh(); sound.refresh(); notif.refresh() }   // [phone-mic] sound, notif

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQ_BLE) { VoxService.instance?.blePermissionsChanged(); refresh() }
        sound.onPermissionResult(requestCode)   // [phone-mic]
    }

    private fun bleGranted() = BleFeatureSource.runtimePermissions().all { checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED }

    private fun refresh() {
        status.text = "Canti\nService: ${if (VoxService.instance != null) "running" else "off (enable Canti controls in Accessibility)"}\n" +
            "Decider: ${s.deciderLabel()}   Vocabulary: ${Vocab.SOURCE_DIGEST}\n" +
            "Bluetooth: ${if (bleGranted()) "allowed" else "not allowed yet"}   Device: ${s.bleDevice ?: "none remembered"}"
    }

    companion object { private const val REQ_BLE = 1 }
}
