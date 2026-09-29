package ai.vox.companion.rec

/**
 * The recorder side of the single drop-reason hook ([ai.vox.companion.audio.PhoneMicSource.recDrop]). It answers one
 * question: why is the mic sound dropped right now? "recording" while a recorder session is open, "playback" while the
 * library is playing a WAV (and for [RecPlayer.TAIL_MS] after, so the phone's own speaker cannot trigger gestures).
 * The "pc stream" reason (a later task) joins through the same lambda, so every reason is computed here and the one
 * lambda in VoxService.setupRec just forwards it.
 */
object RecDrops {
    /** The mic-drop reason from the recorder (contract §5), or null when it is not dropping. */
    fun reason(recording: Boolean, playback: Boolean = false): String? = when {
        recording -> "recording"
        playback -> "playback"
        else -> null
    }
}
