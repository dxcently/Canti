package ai.vox.companion.rec

import ai.vox.companion.Scheduler
import java.io.File

/**
 * The library playback (contract L): plays one session WAV (PCM16 mono/stereo, already path-checked) behind a [Backend]
 * (AudioTrack on device, a fake in the JVM tests), pushes `rec_play {state, name, origin, file, pos_ms, dur_ms}` at 10
 * Hz while playing and once on each state change, and holds the mic-drop "playback" for [TAIL_MS] after the end so the
 * phone's own speaker cannot trigger gestures. All timing runs through the injected [scheduler].
 */
class RecPlayer(
    private val backend: Backend,
    private val scheduler: Scheduler,
    private val push: (Map<String, Any?>) -> Unit,
) {
    interface Backend {
        /** Start playing [file] (a PCM16 mono/stereo WAV). Non-blocking; throws on failure. */
        fun play(file: File)
        fun stop()
        /** The current playback position in ms, or 0 when idle. */
        fun positionMs(): Long
    }

    var state = "stopped"; private set
    var name: String? = null; private set
    var origin: String? = null; private set
    var file: String? = null; private set
    var durMs = 0L; private set

    private var playStartedAt = 0L
    private var endedAt = -1L
    private var pump: (() -> Unit)? = null
    private var tailCancel: (() -> Unit)? = null

    /** True while playing, or within [TAIL_MS] of stopping (the drop reason's "playback" window). */
    val dropping: Boolean get() = state == "playing" || (endedAt >= 0 && scheduler.now() - endedAt < TAIL_MS)

    /** Starts [rel] (the session-relative path) of [name]/[origin]; [f] is its resolved file, [dur] its ms length. */
    fun start(n: String, o: String, rel: String, f: File, dur: Long) {
        tailCancel?.invoke(); tailCancel = null
        stopPump()
        backend.stop()
        name = n; origin = o; file = rel; durMs = dur
        endedAt = -1L
        try {
            playStartedAt = scheduler.now()
            backend.play(f)
            setState("playing")
            startPump()
        } catch (e: Exception) {
            setState("error")
        }
    }

    /** rec_play_stop: ends an in-flight playback (and its 500 ms tail). */
    fun stop() {
        if (state != "playing") return
        backend.stop()
        finish("stopped")
    }

    /** A tick of the 10 Hz pump: detects natural completion and re-pushes while playing. */
    fun tick() {
        if (state != "playing") return
        if (durMs > 0 && scheduler.now() - playStartedAt >= durMs) finish("done")
        else if (state == "playing") pushState()
    }

    fun posMs(): Long = when (state) {
        "playing" -> backend.positionMs()
        "done", "error" -> durMs
        else -> 0L
    }

    private fun finish(s: String) {
        if (state != "playing") return
        endedAt = scheduler.now()
        stopPump()
        setState(s)
        tailCancel = scheduler.schedule(TAIL_MS) { endedAt = -1L }
    }

    private fun setState(s: String) {
        state = s
        pushState()
    }

    private fun pushState() {
        push(mapOf("state" to state, "name" to name, "origin" to origin, "file" to file,
            "pos_ms" to posMs(), "dur_ms" to durMs))
    }

    private fun startPump() {
        stopPump()
        fun loop() {
            if (state != "playing") return
            tick()
            if (state == "playing") pump = scheduler.schedule(PUSH_MS) { loop() }
        }
        pump = scheduler.schedule(PUSH_MS) { loop() }
    }

    private fun stopPump() {
        pump?.invoke(); pump = null
    }

    companion object {
        const val TAIL_MS = 500L
        const val PUSH_MS = 100L

        /** rec_play is refused while a take is in countdown/recording; the error to reply, else null. */
        fun refusal(state: String?): String? =
            if (state == "countdown" || state == "recording") "a take is recording; abort it first" else null
    }
}
