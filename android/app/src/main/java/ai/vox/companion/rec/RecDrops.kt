package ai.vox.companion.rec

/**
 * The recorder side of the single drop-reason hook ([ai.vox.companion.audio.PhoneMicSource.recDrop]). It answers one
 * question: why is the mic sound dropped right now? "recording" while a recorder session is open, "pc stream" while a
 * PC stream is open, "playback" while the library is playing a WAV (and for [RecPlayer.TAIL_MS] after, so the phone's
 * own speaker cannot trigger gestures), else null. Every reason is computed here and the one lambda in
 * VoxService.setupRec just forwards it.
 */
object RecDrops {
    /** The mic-drop reason from the recorder / PC stream / playback (contract §5), or null when it is not dropping. */
    fun reason(recording: Boolean, pcStream: Boolean = false, playback: Boolean = false): String? = when {
        recording -> "recording"
        pcStream -> "pc stream"
        playback -> "playback"
        else -> null
    }
}
