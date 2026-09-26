package ai.vox.companion

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.net.LocalServerSocket
import android.net.LocalSocket
import android.os.Handler
import android.os.Looper
import android.util.Base64
import org.json.JSONObject
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/**
 * Where device messages come from. Every source delivers the same JSON message (PROTOCOL.md) to [Sink] on the main
 * thread. The sink returns a small JSON reply (used by the debug socket so tests can synchronise).
 */
fun interface Sink { fun deliver(msg: JSONObject, source: String): JSONObject }

interface FeatureSource {
    val name: String
    fun start(sink: Sink)
    fun stop()
}

/**
 * Speech-to-text for the listening window. STUB: real ASR is out of scope. Today a phrase arrives in the feature
 * message's `phrase` field (from the device, or injected through a debug source). A phone-side recognizer (Android
 * SpeechRecognizer, or an on-device model) would implement this; the service opens it with the listening window and
 * feeds its text into the same path as a phrase message.
 */
interface PhraseRecognizer {
    val name: String
    /** Listen for up to [windowMs]; call [onPhrase] once on the main thread with the text, or null if nothing was heard. */
    fun listen(windowMs: Long, onPhrase: (String?) -> Unit)
    fun cancel()
}

class StubPhraseRecognizer : PhraseRecognizer {
    override val name = "stub"
    override fun listen(windowMs: Long, onPhrase: (String?) -> Unit) {
        EventLog.ev("asr", "state" to "stub: no phone-side speech recognition; waiting for a phrase message", "window_ms" to windowMs)
    }
    override fun cancel() {}
}

private fun isDebuggable(ctx: Context) = (ctx.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE) != 0

/** Runs [sink] on the main thread and waits for its reply (the socket thread needs the reply to answer). */
private fun deliverOnMain(main: Handler, sink: Sink, msg: JSONObject, source: String): JSONObject {
    if (Looper.myLooper() == Looper.getMainLooper()) return sink.deliver(msg, source)
    val out = AtomicReference<JSONObject>()
    val latch = CountDownLatch(1)
    main.post {
        try { out.set(sink.deliver(msg, source)) }
        catch (e: Exception) { out.set(JSONObject().put("ok", false).put("error", e.toString())) }
        finally { latch.countDown() }
    }
    return if (latch.await(5, TimeUnit.SECONDS)) out.get() else JSONObject().put("ok", false).put("error", "timeout")
}

/**
 * Debug feature source: a Unix-domain socket in the abstract namespace, "vox-debug". Newline-delimited JSON in, one
 * JSON reply line out per message. Reach it from the host with:
 *     adb forward tcp:7788 localabstract:vox-debug
 * Only peers with uid 0 (root) or 2000 (shell, i.e. adb) are accepted, and only on debuggable builds, so other apps
 * on the phone cannot drive the accessibility service through it.
 */
class DebugSocketSource(private val ctx: Context) : FeatureSource {
    override val name = "debug-socket"
    @Volatile private var server: LocalServerSocket? = null
    private var thread: Thread? = null
    private val main = Handler(Looper.getMainLooper())

    override fun start(sink: Sink) {
        if (!isDebuggable(ctx)) { EventLog.ev("source", "name" to name, "state" to "disabled: not a debuggable build"); return }
        val s = LocalServerSocket(SOCKET_NAME)
        server = s
        thread = Thread({
            while (!Thread.currentThread().isInterrupted) {
                val c = try { s.accept() } catch (e: Exception) { break }
                Thread({ serve(c, sink) }, "vox-debug-client").apply { isDaemon = true }.start()
            }
        }, "vox-debug-accept").apply { isDaemon = true; start() }
        EventLog.ev("source", "name" to name, "state" to "listening", "socket" to "localabstract:$SOCKET_NAME")
    }

    private fun serve(c: LocalSocket, sink: Sink) {
        c.use { sock ->
            val uid = try { sock.peerCredentials.uid } catch (e: Exception) { -1 }
            if (uid != 0 && uid != 2000) {
                EventLog.ev("ignored", "reason" to "debug socket peer uid $uid is not shell/root")
                return
            }
            val out = sock.outputStream.bufferedWriter()
            sock.inputStream.bufferedReader().lineSequence().forEach { line ->
                if (line.isBlank()) return@forEach
                val reply = try { deliverOnMain(main, sink, JSONObject(line), name) }
                catch (e: Exception) { JSONObject().put("ok", false).put("error", e.toString()) }
                out.write(reply.toString()); out.write("\n"); out.flush()
            }
        }
    }

    override fun stop() {
        try { server?.close() } catch (_: Exception) {}
        thread?.interrupt()
        server = null
    }

    companion object { const val SOCKET_NAME = "vox-debug" }
}

/**
 * Debug feature source over broadcasts (same JSON). The manifest requires senders to hold android.permission.DUMP,
 * which adb shell has and ordinary apps cannot get:
 *     adb shell am broadcast -a ai.vox.companion.DEBUG -n ai.vox.companion/.DebugBroadcastReceiver --es b64 <base64 json>
 * The reply is logged as a "reply" event.
 */
class DebugBroadcastReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        if (!isDebuggable(ctx)) return
        val raw = intent.getStringExtra("json")
            ?: intent.getStringExtra("b64")?.let { String(Base64.decode(it, Base64.DEFAULT)) }
            ?: return
        val svc = VoxService.instance
        if (svc == null) { EventLog.ev("ignored", "reason" to "broadcast received but the accessibility service is not running"); return }
        val reply = try { svc.deliver(JSONObject(raw), "debug-broadcast") }
        catch (e: Exception) { JSONObject().put("ok", false).put("error", e.toString()) }
        EventLog.ev("reply", "source" to "debug-broadcast", "reply" to reply)
    }
}
