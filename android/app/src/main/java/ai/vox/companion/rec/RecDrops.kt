package ai.vox.companion.rec

/**
 * The recorder side of the single drop-reason hook ([ai.vox.companion.audio.PhoneMicSource.recDrop]). It answers one
 * question: why is the mic sound dropped right now? "recording" while a recorder session is open, "pc stream" while a
 * PC stream is open, else null. A later task adds "playback" through the same lambda, so the reason is computed here
 * and the one lambda in VoxService.setupRec just forwards it.
 */
object RecDrops {
    /** The mic-drop reason from the recorder / PC stream (contract §5), or null when it is not dropping. */
    fun reason(recording: Boolean, pcStream: Boolean = false): String? = when {
        recording -> "recording"
        pcStream -> "pc stream"
        else -> null
    }
}
