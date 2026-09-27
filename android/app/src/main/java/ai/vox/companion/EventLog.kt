package ai.vox.companion

import android.content.Context
import android.os.SystemClock
import android.util.Log
import org.json.JSONObject
import java.io.File

/**
 * The event log. Each event is one JSON object, written to:
 *   - logcat, tag "VOX" (read with: adb logcat -v raw -s VOX:I)
 *   - files/events.jsonl in app storage (read with: adb exec-out run-as ai.vox.companion cat files/events.jsonl),
 *     rotated to events.1.jsonl at 2 MB.
 * Fields: "ev" (event name), "t" (elapsedRealtime ms), then event-specific fields. Secrets are never logged.
 */
object EventLog {
    const val TAG = "VOX"
    private const val MAX_BYTES = 2L shl 20
    private var file: File? = null
    private var harvestFile: File? = null
    /** Live subscribers (the Flutter UI's event channel). Called on the logging thread, inside the log's lock. */
    private val listeners = java.util.concurrent.CopyOnWriteArrayList<(JSONObject) -> Unit>()
    /** File writes, in call order, off the caller's thread. */
    private val io = java.util.concurrent.Executors.newSingleThreadExecutor { r -> Thread(r, "vox-log").apply { isDaemon = true } }

    fun init(ctx: Context) {
        file = File(ctx.filesDir, "events.jsonl")
        harvestFile = File(ctx.filesDir, "harvest.jsonl")
    }

    /** For the activity, which may start before the service (or without it). */
    fun initIfNeeded(ctx: Context) { if (file == null) init(ctx) }

    fun addListener(l: (JSONObject) -> Unit) { listeners += l }
    fun removeListener(l: (JSONObject) -> Unit) { listeners -= l }

    @Synchronized
    fun ev(name: String, vararg fields: Pair<String, Any?>): JSONObject {
        val o = JSONObject().put("ev", name).put("t", SystemClock.elapsedRealtime())
        for ((k, v) in fields) o.put(k, v ?: JSONObject.NULL)
        val line = o.toString()
        // logcat truncates around 4 KB; long events (state text, harvest) are shortened there but complete in the file.
        Log.i(TAG, if (line.length > 3800) line.take(3790) + "…[cut]" else line)
        // The file write runs on the log's own thread: file I/O never delays the caller (the main thread).
        file?.let { f -> io.execute {
            try {
                if (f.length() > MAX_BYTES) f.renameTo(File(f.parentFile, "events.1.jsonl"))
                f.appendText(line + "\n")
            } catch (e: Exception) {
                Log.w(TAG, "event file write failed: $e")
            }
        } }
        for (l in listeners) try { l(o) } catch (e: Exception) { Log.w(TAG, "event listener failed: $e") }
        return o
    }

    @Synchronized
    fun harvest(o: JSONObject) {
        val f = harvestFile ?: return
        val line = o.toString()
        io.execute { try { f.appendText(line + "\n") } catch (e: Exception) { Log.w(TAG, "harvest write failed: $e") } }
    }

    /** In order with the writes (the log's thread). */
    @Synchronized
    fun clear() {
        val f = file ?: return
        io.execute { f.delete(); File(f.parentFile, "events.1.jsonl").delete() }
    }

    @Synchronized
    fun clearHarvest() { val f = harvestFile ?: return; io.execute { f.delete() } }
}
