package ai.vox.companion

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognitionSupport
import android.speech.RecognitionSupportCallback
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer

/**
 * `asr_engine` android: the phone's SpeechRecognizer, offline only unless `asr_allow_online` ([AsrPlan]).
 * One recognizer per window, created in [start] and destroyed in [cancel]; main thread only.
 *
 * [check] asks the recognizer (API 33+) whether the language pack is installed, so a missing pack is reported when
 * the window opens instead of after a failed listen. Transcripts go only to the local event log (VoxService) and the
 * phrase decider; this class logs no text.
 */
class AndroidPhraseRecognizer(
    private val ctx: Context,
    private val allowOnline: () -> Boolean,
    private val language: () -> String,
) : PhraseRecognizer {
    override val name = "android"
    private var rec: SpeechRecognizer? = null
    private var plan: AsrPlan.Plan? = null
    /** From [check]: the pack is known to be missing (null = not checked or unknown); "downloading" when pending. */
    private var packMissing: Boolean? = null
    var packState: String? = null; private set

    private fun permission() = ctx.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
    private fun onDeviceAvailable() = Build.VERSION.SDK_INT >= 31 && try { SpeechRecognizer.isOnDeviceRecognitionAvailable(ctx) } catch (_: Exception) { false }

    fun plan(): AsrPlan.Plan = AsrPlan.choose(Build.VERSION.SDK_INT, permission(), onDeviceAvailable(),
        SpeechRecognizer.isRecognitionAvailable(ctx), allowOnline(), packMissing == true)

    override fun status(): String? = plan().status

    /** What the UI and `asr` op show. */
    fun describe(): Map<String, Any?> {
        val p = plan()
        return mapOf("engine" to name, "recognizer" to p.kind.name.lowercase(), "status" to (p.status ?: "ready"),
            "language" to language(), "pack" to packState, "allow_online" to allowOnline(),
            "on_device_available" to onDeviceAvailable(), "any_available" to SpeechRecognizer.isRecognitionAvailable(ctx))
    }

    internal fun intent(online: Boolean) = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
        .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
        .putExtra(RecognizerIntent.EXTRA_LANGUAGE, language())
        .putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
        .putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 5)
        .putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, ctx.packageName)
        .putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, !online)

    private fun create(kind: AsrPlan.Kind): SpeechRecognizer =
        if (kind == AsrPlan.Kind.ON_DEVICE && Build.VERSION.SDK_INT >= 31) SpeechRecognizer.createOnDeviceSpeechRecognizer(ctx)
        else SpeechRecognizer.createSpeechRecognizer(ctx)

    /**
     * API 33+: is the language installed for offline use? [done] gets the new pack state (main thread). Below 33 the
     * pack can't be asked about; a missing one shows as an error on the first listen.
     */
    fun check(done: (String) -> Unit) {
        if (Build.VERSION.SDK_INT < 33) { packState = "unknown (Android < 13)"; done(packState!!); return }
        packMissing = null   // ask again: plan() must not assume the old answer
        val p = plan()
        if (p.kind == AsrPlan.Kind.NONE) { packState = p.status; done(packState ?: "none"); return }
        val r = try { create(p.kind) } catch (e: Exception) { packState = "check failed: ${e.javaClass.simpleName}"; done(packState!!); return }
        val lang = language()
        try {
            r.checkRecognitionSupport(intent(online = false), ctx.mainExecutor, object : RecognitionSupportCallback {
                override fun onSupportResult(s: RecognitionSupport) {
                    val installed = s.installedOnDeviceLanguages.any { same(it, lang) }
                    val pending = s.pendingOnDeviceLanguages.any { same(it, lang) }
                    val supported = s.supportedOnDeviceLanguages.any { same(it, lang) }
                    packMissing = !installed
                    packState = when {
                        installed -> "installed"
                        pending -> "downloading"
                        supported -> "not installed (download it in the phone's speech settings)"
                        else -> "not available for $lang"
                    }
                    try { r.destroy() } catch (_: Exception) {}
                    done(packState!!)
                }
                override fun onError(error: Int) {
                    packState = "unknown (check error $error)"
                    try { r.destroy() } catch (_: Exception) {}
                    done(packState!!)
                }
            })
        } catch (e: Exception) {
            packState = "unknown (${e.javaClass.simpleName})"
            try { r.destroy() } catch (_: Exception) {}
            done(packState!!)
        }
    }

    private fun same(a: String, b: String) = a.equals(b, true) || a.substringBefore('-').equals(b, true) ||
        a.replace('_', '-').equals(b.replace('_', '-'), true)

    override fun start(listener: PhraseRecognizer.Listener) {
        cancel()
        val p = plan()
        plan = p
        if (p.kind == AsrPlan.Kind.NONE) { listener.onError(-1, "unavailable", p.status); return }
        val online = p.kind == AsrPlan.Kind.DEFAULT_ONLINE
        val offlineOnly = !online
        val r = create(p.kind)
        rec = r
        r.setRecognitionListener(object : RecognitionListener {
            override fun onReadyForSpeech(params: Bundle?) { if (rec === r) listener.onReady() }
            override fun onBeginningOfSpeech() {}
            override fun onRmsChanged(rmsdB: Float) { if (rec === r) listener.onLevel(rmsdB) }
            override fun onBufferReceived(buffer: ByteArray?) {}
            override fun onEndOfSpeech() {}
            override fun onError(error: Int) {
                if (rec !== r) return
                val (what, status) = AsrPlan.error(error, offlineOnly)
                if (status == AsrPlan.PACK_MISSING) { packMissing = true; packState = "missing (error $error: $what)" }
                listener.onError(error, what, status)
            }
            override fun onResults(results: Bundle?) { if (rec === r) listener.onFinal(heard(results)) }
            override fun onPartialResults(partial: Bundle?) {
                if (rec !== r) return
                partial?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.takeIf { it.isNotBlank() }?.let(listener::onPartial)
            }
            override fun onEvent(eventType: Int, params: Bundle?) {}
        })
        r.startListening(intent(online))
    }

    private fun heard(b: Bundle?): Heard {
        val texts = b?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION).orEmpty().filter { it.isNotBlank() }
        val conf = b?.getFloatArray(SpeechRecognizer.CONFIDENCE_SCORES)?.toList().orEmpty()
        return Heard(texts, conf)
    }

    override fun stop() { try { rec?.stopListening() } catch (_: Exception) {} }

    override fun cancel() {
        val r = rec ?: return
        rec = null
        try { r.cancel() } catch (_: Exception) {}
        try { r.destroy() } catch (_: Exception) {}
    }

    /** The recognizer this window uses (for the log). */
    val kind: String? get() = plan?.kind?.name?.lowercase()
}
