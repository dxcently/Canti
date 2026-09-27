package ai.vox.companion

import android.content.Context
import android.content.SharedPreferences
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONObject
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * App settings (SharedPreferences "vox"). The API key lives here and only here: it is entered in MainActivity (or,
 * on debug builds, pushed over the adb-only debug channel), never hard-coded and never written to the event log.
 * TODO: move the key to Android Keystore-backed storage before any non-debug release.
 */
class Settings(ctx: Context) {
    private val p: SharedPreferences = ctx.getSharedPreferences("vox", Context.MODE_PRIVATE)
    private val secrets by lazy { KeystoreSecrets(ctx) }
    /** [phone-mic] The sound source and microphone settings (same prefs file; audio/MicSettings.kt). */
    val mic = ai.vox.companion.audio.MicSettings(p)

    /** The status screen's decider line. */
    fun deciderLabel(): String = if (decider == "escalate") "escalate (ollama: $ollamaModel)" else decider

    var decider: String get() = p.getString("decider", "rules")!!; set(v) = put("decider", v)
    // Decider mode "escalate": the cloud model (Ollama chat API) for target picking and the cases the local path
    // can't settle. The key is Keystore-encrypted ([KeystoreSecrets]), entered only in LegacySettingsActivity, never
    // accepted or returned by the debug "config" op, and never logged.
    var ollamaEndpoint: String get() = p.getString("ollama_endpoint", "https://ollama.com")!!; set(v) = put("ollama_endpoint", v)
    var ollamaModel: String get() = p.getString("ollama_model", "deepseek-v4.1-flash")!!; set(v) = put("ollama_model", v)
    var ollamaKey: String get() = secrets.get("ollama_key"); set(v) = secrets.put("ollama_key", v)
    var ollamaTimeoutMs: Int get() = p.getInt("ollama_timeout_ms", 1500); set(v) = p.edit().putInt("ollama_timeout_ms", v).apply()
    var ollamaTargetTimeoutMs: Int get() = p.getInt("ollama_target_timeout_ms", 2500); set(v) = p.edit().putInt("ollama_target_timeout_ms", v).apply()
    var baseUrl: String get() = p.getString("base_url", "https://api.typesafe.ai")!!; set(v) = put("base_url", v)
    var model: String get() = p.getString("model", "jev-1.13.0")!!; set(v) = put("model", v)
    var apiKey: String get() = p.getString("api_key", "")!!; set(v) = put("api_key", v)
    var minConfidence: Double get() = p.getFloat("min_confidence", 0.5f).toDouble(); set(v) = p.edit().putFloat("min_confidence", v.toFloat()).apply()
    var httpTimeoutMs: Int get() = p.getInt("http_timeout_ms", 2000); set(v) = p.edit().putInt("http_timeout_ms", v).apply()
    /** Max gap between sounds of one sequence, and how long a bound prefix waits (wiki: ~600 ms). */
    var gapMs: Long get() = p.getLong("gap_ms", 600); set(v) = p.edit().putLong("gap_ms", v).apply()
    /** Device-stamp grouping: allowance for a follow-up sound arriving later than the fastest link (PROTOCOL.md). */
    var jitterMs: Long get() = p.getLong("jitter_ms", 150); set(v) = p.edit().putLong("jitter_ms", v).apply()
    var confirmTimeoutMs: Long get() = p.getLong("confirm_timeout_ms", 1500); set(v) = p.edit().putLong("confirm_timeout_ms", v).apply()
    /** How long an outward action (like, follow, share...) waits for its confirm pop ([Outward.windowMs]). */
    var outwardConfirmMs: Long get() = p.getLong("outward_confirm_ms", Outward.DEFAULT_CONFIRM_MS); set(v) = p.edit().putLong("outward_confirm_ms", v).apply()
    var listenWindowMs: Long get() = p.getLong("listen_window_ms", 6000); set(v) = p.edit().putLong("listen_window_ms", v).apply()
    /** Speech in the phrase window: `android` (the phone's SpeechRecognizer) or `off` (a phrase comes only in a message). */
    var asrEngine: String get() = p.getString("asr_engine", "android")!!; set(v) = put("asr_engine", v)
    /** The Android recognizer may use the network. Off: offline only, and a missing offline pack is reported, never bypassed. */
    var asrAllowOnline: Boolean get() = p.getBoolean("asr_allow_online", false); set(v) = p.edit().putBoolean("asr_allow_online", v).apply()
    /** The recognizer's language (BCP 47). The command grammar is English. */
    var asrLanguage: String get() = p.getString("asr_language", "en-US")!!; set(v) = put("asr_language", v)
    /** Intent cursor mode: tap the model's pick at or above this confidence, else highlight the top 3. */
    var targetMinConfidence: Double get() = p.getFloat("target_min_confidence", 0.6f).toDouble(); set(v) = p.edit().putFloat("target_min_confidence", v.toFloat()).apply()
    /** Model for the "target" question; empty = the same as `model`. */
    var targetModel: String get() = p.getString("target_model", "")!!; set(v) = put("target_model", v)
    /** How long the highlighted candidates wait for rise/fall/pop before cancelling (reset by each rise/fall). */
    var targetChooseMs: Long get() = p.getLong("target_choose_ms", 6000); set(v) = p.edit().putLong("target_choose_ms", v).apply()
    /** Personalization: a sound matches a class only within (largest within-class distance) x this. */
    var enrollRejectMult: Double get() = p.getFloat("enroll_reject_mult", 1.4f).toDouble(); set(v) = p.edit().putFloat("enroll_reject_mult", v.toFloat()).apply()
    /** [train] Personalization: a match to an active gesture class relabels a sound the extractor labelled otherwise. */
    var enrollGestureRelabel: Boolean get() = p.getBoolean("enroll_gesture_relabel", true); set(v) = p.edit().putBoolean("enroll_gesture_relabel", v).apply()
    /** The remembered VOX device (Bluetooth address), set on the first good BLE connection; null = none. */
    var bleDevice: String? get() = p.getString("ble_device", null); set(v) = put("ble_device", v)
    /** Auto-scroll (rise/fall + a long flat hum): speed in percent of the screen height per second (2..60). */
    var autoScrollPct: Int get() = p.getInt("auto_scroll_pct", 10); set(v) = p.edit().putInt("auto_scroll_pct", v.coerceIn(2, 60)).apply()
    /** How far a rise/fall step moves an ordinary list ([StepSize]: small, medium, large); pagers always fling. */
    var scrollStep: String get() = StepSize.of(p.getString("scroll_step", null)).key; set(v) = put("scroll_step", StepSize.of(v).key)
    /** Duration of the fling on a paged video feed (TikTok, Reels, Shorts; [ScrollStep.Decision.feed]); lists step, other flings keep [SwipeGeometry.DURATION_MS]. */
    var feedFlingMs: Int get() = p.getInt("feed_fling_ms", ScrollStep.FEED_FLING_MS).coerceIn(ScrollStep.FEED_FLING_RANGE); set(v) = p.edit().putInt("feed_fling_ms", v.coerceIn(ScrollStep.FEED_FLING_RANGE)).apply()
    /** Length of that feed fling, % of the screen height from its usual start ([ScrollStep.feedLine]). */
    var feedFlingPct: Int get() = p.getInt("feed_fling_pct", ScrollStep.FEED_FLING_PCT).coerceIn(ScrollStep.FEED_FLING_PCT_RANGE); set(v) = p.edit().putInt("feed_fling_pct", v.coerceIn(ScrollStep.FEED_FLING_PCT_RANGE)).apply()
    var debugSource: Boolean get() = p.getBoolean("debug_source", true); set(v) = p.edit().putBoolean("debug_source", v).apply()
    /** The clock app for spoken timers (a package name; empty = the only / default / system clock, see [TimerTarget]). */
    var timerApp: String get() = p.getString("timer_app", "")!!; set(v) = put("timer_app", v)
    /** Which installed app a spoken name opens when there are two: "from=to,..." ([AppChoice.parsePrefer]); default YouTube -> RVX. */
    var appPrefer: String get() = p.getString("app_prefer", AppChoice.DEFAULT_PREFER)!!; set(v) = put("app_prefer", v)
    /** Debug: the dictate and type events carry the typed words. Off: only counts (the words are the user's). */
    var logTypedText: Boolean get() = p.getBoolean("log_typed_text", false); set(v) = p.edit().putBoolean("log_typed_text", v).apply()
    /** Dictation: a device sound this soon after the last recognized words is speech (ignored); later it stops dictation. */
    var dictateSpeechHoldMs: Long get() = p.getLong("dictate_speech_hold_ms", Dictation.SPEECH_HOLD_MS); set(v) = p.edit().putLong("dictate_speech_hold_ms", v).apply()
    /** While media plays, phone / USB mic sounds are dropped except a `pop pop` unlock ([MediaGate]; user decision 2026-09-27). */
    var mediaLock: Boolean get() = p.getBoolean("media_lock", true); set(v) = p.edit().putBoolean("media_lock", v).apply()
    /** How an unlock ends ([MediaGate.MODES]): `one` (the next gesture only), `fixed` (a window), `popext` (a window only pop pop extends). */
    var mediaUnlockMode: String get() = p.getString("media_unlock_mode", MediaGate.ONE)!!.takeIf { it in MediaGate.MODES } ?: MediaGate.ONE; set(v) = put("media_unlock_mode", v)
    /** The unlock's time limit: to make the one gesture (`one`), or the window (`fixed`, `popext`). */
    var mediaUnlockMs: Long get() = p.getLong("media_unlock_ms", MediaGate.DEFAULT_UNLOCK_MS); set(v) = p.edit().putLong("media_unlock_ms", v).apply()
    /** Voice cursor (joystick) speed: x the spec's start and max dp/s ([ai.vox.companion.joystick.Mover.speedMul]); 0.5..2.0. */
    var cursorSpeed: Double get() = CursorSlider.clamp(p.getFloat("cursor_speed", CursorSlider.DEFAULT.toFloat()).toDouble()); set(v) = p.edit().putFloat("cursor_speed", CursorSlider.clamp(v).toFloat()).apply()
    /** Voice cursor pitch sensitivity: higher = less pitch for full speed ([ai.vox.companion.joystick.Mover.pitchSens]); 0.5..2.0. */
    var cursorPitchSens: Double get() = CursorSlider.clamp(p.getFloat("cursor_pitch_sens", CursorSlider.DEFAULT.toFloat()).toDouble()); set(v) = p.edit().putFloat("cursor_pitch_sens", CursorSlider.clamp(v).toFloat()).apply()
    var profileJson: String? get() = p.getString("profile", null); set(v) = put("profile", v)

    private fun put(k: String, v: String?) = p.edit().putString(k, v).apply()

    /** Apply a debug "config" control message. Unknown keys are rejected. */
    fun apply(o: JSONObject) {
        for (k in o.keys()) when (k) {
            "op", "type", "v" -> {}
            "decider" -> { val v = o.getString(k); require(v in DECIDERS) { "decider must be one of $DECIDERS" }; decider = v }
            "ollama_endpoint" -> ollamaEndpoint = o.getString(k)
            "ollama_model" -> ollamaModel = o.getString(k)
            "ollama_timeout_ms" -> ollamaTimeoutMs = o.getInt(k)
            "ollama_target_timeout_ms" -> ollamaTargetTimeoutMs = o.getInt(k)
            "ollama_key" -> throw IllegalArgumentException("ollama_key is entered in the settings screen only")
            "base_url" -> baseUrl = o.getString(k)
            "model" -> model = o.getString(k)
            "api_key" -> apiKey = o.getString(k)
            "min_confidence" -> minConfidence = o.getDouble(k)
            "http_timeout_ms" -> httpTimeoutMs = o.getInt(k)
            "gap_ms" -> gapMs = o.getLong(k)
            "jitter_ms" -> jitterMs = o.getLong(k)
            "confirm_timeout_ms" -> confirmTimeoutMs = o.getLong(k)
            "outward_confirm_ms" -> { val v = o.getLong(k); require(v in Outward.CONFIRM_MS_RANGE) { "outward_confirm_ms must be ${Outward.CONFIRM_MS_RANGE}" }; outwardConfirmMs = v }
            "listen_window_ms" -> listenWindowMs = o.getLong(k)
            "asr_engine" -> { val v = o.getString(k); require(v in ASR_ENGINES) { "asr_engine must be one of $ASR_ENGINES" + if (v == "sherpa") " (sherpa is not built yet)" else "" }; asrEngine = v }
            "asr_allow_online" -> asrAllowOnline = o.getBoolean(k)
            "asr_language" -> { val v = o.getString(k).trim(); require(Regex("[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*").matches(v)) { "asr_language must be a language tag like en-US" }; asrLanguage = v }
            "target_min_confidence" -> targetMinConfidence = o.getDouble(k)
            "target_model" -> targetModel = o.getString(k)
            "target_choose_ms" -> targetChooseMs = o.getLong(k)
            "timer_app" -> timerApp = o.getString(k).trim()
            "app_prefer" -> { val v = o.getString(k).trim(); AppChoice.parsePrefer(v); appPrefer = v }
            "log_typed_text" -> logTypedText = o.getBoolean(k)
            "media_lock" -> mediaLock = o.getBoolean(k)
            "media_unlock_mode" -> { val v = o.getString(k); require(v in MediaGate.MODES) { "media_unlock_mode must be one of ${MediaGate.MODES}" }; mediaUnlockMode = v }
            "media_unlock_ms" -> { val v = o.getLong(k); require(v in MediaGate.UNLOCK_MS_RANGE) { "media_unlock_ms must be ${MediaGate.UNLOCK_MS_RANGE.first}..${MediaGate.UNLOCK_MS_RANGE.last}" }; mediaUnlockMs = v }
            "dictate_speech_hold_ms" -> { val v = o.getLong(k); require(v in Dictation.SPEECH_HOLD_RANGE) { "dictate_speech_hold_ms must be ${Dictation.SPEECH_HOLD_RANGE.first}..${Dictation.SPEECH_HOLD_RANGE.last}" }; dictateSpeechHoldMs = v }
            "cursor_speed" -> cursorSpeed = o.getDouble(k)
            "cursor_pitch_sens" -> cursorPitchSens = o.getDouble(k)
            "auto_scroll_pct" -> { val v = o.getInt(k); require(v in 2..60) { "auto_scroll_pct must be 2..60" }; autoScrollPct = v }
            "scroll_step" -> { val v = o.getString(k); require(v in StepSize.KEYS) { "scroll_step must be one of ${StepSize.KEYS}" }; scrollStep = v }
            "feed_fling_ms" -> { val v = o.getInt(k); require(v in ScrollStep.FEED_FLING_RANGE) { "feed_fling_ms must be ${ScrollStep.FEED_FLING_RANGE.first}..${ScrollStep.FEED_FLING_RANGE.last}" }; feedFlingMs = v }
            "feed_fling_pct" -> { val v = o.getInt(k); require(v in ScrollStep.FEED_FLING_PCT_RANGE) { "feed_fling_pct must be ${ScrollStep.FEED_FLING_PCT_RANGE.first}..${ScrollStep.FEED_FLING_PCT_RANGE.last}" }; feedFlingPct = v }
            "enroll_reject_mult" -> { val v = o.getDouble(k); require(v > 0) { "enroll_reject_mult must be > 0" }; enrollRejectMult = v }
            "enroll_gesture_relabel" -> enrollGestureRelabel = o.getBoolean(k)   // [train]
            "ble_device" -> bleDevice = if (o.isNull(k)) null else o.getString(k).uppercase().also {
                require(BLE_ADDRESS.matches(it)) { "ble_device must be a Bluetooth address like AA:BB:CC:DD:EE:FF, or null" }
            }
            in ai.vox.companion.audio.MicSettings.KEYS -> mic.apply(k, o)   // [phone-mic]
            else -> throw IllegalArgumentException("unknown config key '$k'")
        }
    }

    /** Settings as JSON with the API key redacted. */
    fun describe(): JSONObject = JSONObject()
        .put("decider", decider).put("base_url", baseUrl).put("model", model)
        .put("api_key", if (apiKey.isBlank()) "" else "set(${apiKey.length} chars)")
        .put("min_confidence", minConfidence).put("http_timeout_ms", httpTimeoutMs).put("gap_ms", gapMs).put("jitter_ms", jitterMs)
        .put("confirm_timeout_ms", confirmTimeoutMs).put("outward_confirm_ms", outwardConfirmMs).put("listen_window_ms", listenWindowMs)
        .put("asr_engine", asrEngine).put("asr_allow_online", asrAllowOnline).put("asr_language", asrLanguage)
        .put("target_min_confidence", targetMinConfidence).put("target_model", targetModel).put("target_choose_ms", targetChooseMs)
        .put("enroll_reject_mult", enrollRejectMult).put("enroll_gesture_relabel", enrollGestureRelabel).put("ble_device", bleDevice ?: JSONObject.NULL)
        .put("ollama_endpoint", ollamaEndpoint).put("ollama_model", ollamaModel).put("ollama_key", if (ollamaKey.isBlank()) "" else "set")
        .put("ollama_timeout_ms", ollamaTimeoutMs).put("ollama_target_timeout_ms", ollamaTargetTimeoutMs)
        .put("auto_scroll_pct", autoScrollPct).put("scroll_step", scrollStep).put("cursor_speed", cursorSpeed).put("cursor_pitch_sens", cursorPitchSens).put("feed_fling_ms", feedFlingMs).put("feed_fling_pct", feedFlingPct).put("timer_app", timerApp).put("app_prefer", appPrefer).put("log_typed_text", logTypedText).put("dictate_speech_hold_ms", dictateSpeechHoldMs)
        .put("media_lock", mediaLock).put("media_unlock_mode", mediaUnlockMode).put("media_unlock_ms", mediaUnlockMs)
        .let { mic.describeInto(it) }   // [phone-mic]

    companion object {
        val BLE_ADDRESS = Regex("[0-9A-F]{2}(:[0-9A-F]{2}){5}")
        val DECIDERS = listOf("rules", "model", "hybrid", "escalate")
        val ASR_ENGINES = listOf("android", "off")
    }
}

/**
 * Small secrets store: AES-256-GCM under a non-exportable Android Keystore key; only the ciphertext (IV + data, base64)
 * is written, to SharedPreferences "vox_secrets". (androidx EncryptedSharedPreferences is deprecated, and the app uses
 * platform APIs only.) A value that can't be decrypted (key lost, e.g. after a restore to another device) reads as "".
 */
class KeystoreSecrets(ctx: Context) {
    private val p: SharedPreferences = ctx.getSharedPreferences("vox_secrets", Context.MODE_PRIVATE)

    private fun key(): SecretKey {
        val ks = KeyStore.getInstance(STORE).apply { load(null) }
        (ks.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val g = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, STORE)
        g.init(KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256).build())
        return g.generateKey()
    }

    @Synchronized
    fun get(name: String): String {
        val b = p.getString(name, null) ?: return ""
        return try {
            val raw = Base64.decode(b, Base64.NO_WRAP)
            val c = Cipher.getInstance(TRANSFORM)
            c.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, raw, 0, IV_BYTES))
            String(c.doFinal(raw, IV_BYTES, raw.size - IV_BYTES), Charsets.UTF_8)
        } catch (e: Exception) { "" }
    }

    @Synchronized
    fun put(name: String, value: String) {
        if (value.isBlank()) { p.edit().remove(name).apply(); return }
        val c = Cipher.getInstance(TRANSFORM)
        c.init(Cipher.ENCRYPT_MODE, key())
        val out = c.iv + c.doFinal(value.trim().toByteArray(Charsets.UTF_8))
        p.edit().putString(name, Base64.encodeToString(out, Base64.NO_WRAP)).apply()
    }

    private companion object {
        const val STORE = "AndroidKeyStore"
        const val ALIAS = "vox_secrets_v1"
        const val TRANSFORM = "AES/GCM/NoPadding"
        const val IV_BYTES = 12
    }
}

/** The voice cursor's two sliders (cursor_speed, cursor_pitch_sens): 0.5..2.0, default 0.9 (user decision
 *  2026-09-27); stored rounded to 2 decimals (the app steps them by 0.1). */
object CursorSlider {
    const val MIN = 0.5
    const val MAX = 2.0
    const val DEFAULT = 0.9
    fun clamp(v: Double): Double = if (v.isNaN()) DEFAULT else Math.round(v.coerceIn(MIN, MAX) * 100) / 100.0
}
