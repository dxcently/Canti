package ai.vox.companion.rec

/**
 * The recorder side of the single drop-reason hook ([ai.vox.companion.audio.PhoneMicSource.recDrop]). It answers one
 * question: why is the mic sound dropped right now? "recording" while a recorder session is open, else null. Two later
 * tasks add "pc stream" and "playback" reasons through the same lambda, so the reason is computed here and the one
 * lambda in VoxService.setupRec just forwards it.
 */
object RecDrops {
    /** The mic-drop reason from the recorder (contract §5), or null when it is not dropping. */
    fun reason(recording: Boolean): String? = if (recording) "recording" else null
}
