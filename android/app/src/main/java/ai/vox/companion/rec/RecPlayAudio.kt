package ai.vox.companion.rec

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioTrack
import java.io.File

/**
 * The on-device [RecPlayer.Backend]: plays a PCM16 mono/stereo WAV through an AudioTrack in static mode (the whole
 * buffer is written once, so [RecPlayer] drives completion from elapsed time). Android-only; the JVM tests inject a
 * fake backend instead.
 */
class RecPlayAudio : RecPlayer.Backend {
    private var track: AudioTrack? = null
    private var rate = 0

    override fun play(file: File) {
        stop()
        val (channels, r, _) = RecLibrary.wavInfo(file)
        rate = r
        val data = file.readBytes()
        val pcm = data.size - 44
        val mask = if (channels == 2) AudioFormat.CHANNEL_OUT_STEREO else AudioFormat.CHANNEL_OUT_MONO
        val t = AudioTrack(
            AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build(),
            AudioFormat.Builder().setEncoding(AudioFormat.ENCODING_PCM_16BIT).setSampleRate(rate).setChannelMask(mask).build(),
            pcm, AudioTrack.MODE_STATIC, AudioManager.AUDIO_SESSION_ID_GENERATE,
        )
        t.write(data, 44, pcm)
        t.play()
        track = t
    }

    override fun stop() {
        track?.let { try { it.stop(); it.release() } catch (_: Exception) {} }
        track = null
    }

    override fun positionMs(): Long {
        val t = track ?: return 0L
        return if (rate > 0) t.playbackHeadPosition.toLong() * 1000 / rate else 0L
    }
}
