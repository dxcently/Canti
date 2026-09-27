package ai.vox.companion.audio

/**
 * Phone-mic media gate: while a video or music plays on the phone's own speaker, the mic hears it, and the extractor
 * reads bits of it as gestures (a drum hit or a consonant as a pop -> tap, a spoken syllable's falling pitch as a
 * falling hum -> swipe down). Offline (android/tools/phone_media_eval.py, MUSAN speech + music, default Config) that
 * is 1.3-1.6 acts per minute of media alone, most of them taps from music.
 *
 * A gated sound is not dropped: [PhoneMicSource] hands it on as "unknown" (Decider: not deliberate) with the message's
 * `gated` flag (so personalization never relabels it), so it still
 * breaks up its group the way it would have, instead of letting a neighbouring sound act alone.
 *
 * The rule, from the same eval (pm_base + pm_syn, 400 media minutes):
 * - pop / click: at least [POP_SNR_DB] over the noise floor (media pops: p90 12.7 dB; synthetic pops in quiet 34+);
 * - hum (rise / fall / arch / dip / flat, whistles included): at least [HUM_SNR_DB] over the floor AND a median
 *   clarity of at least [HUM_CLARITY] (a single clear period; music chords and breathy speech fall below).
 * Media alone: 1.31 -> 0.25 acts / min (music 1.7 -> 0.14; speech 0.6 -> 0.44: what is left are single spoken
 * syllables that really are hum-shaped, which only an echo reference can tell apart). Clean gestures, pops,
 * click-pops and whistles: unchanged. Gestures made over the media at 10 dB: survival 0.29 -> 0.24 (synthetic),
 * 0.24 -> 0.19 (the user's own) - the gate asks for a louder gesture while a video plays.
 *
 * Not always on: the user's own pops / clicks in a quiet room are 11-30 dB over the floor (median 18), so a 14 dB
 * rule would cost a quarter of them when nothing is playing.
 *
 * Media hiss ([hissReason], setting `hiss_media_max_centroid_hz`, default [HISS_MEDIA_MAX_CENTROID_HZ], 0 = off;
 * wiki/phone-mic-echo.md, 2026-09-27): on the Z Flip a YouTube Short on the speaker made lone "hiss" sounds with a
 * spectral centroid of 6.6-7.3 kHz (p10 / p50 6.6 / 6.9 kHz, all "mouth sound", so deliberate), each one a `back`
 * through the Sequencer: 38-42 would-act / min in the shipped `auto` preset. While media plays on the phone's own
 * speaker, a phone / USB mic hiss whose energy-weighted centroid (the extractor's `centroid_hz`) is over the
 * threshold becomes `unknown`: 38 / 42 -> 4 / 0 a minute (auto / VR), and it kept 100 % of the user's 69 Q9 mouth
 * hisses (centroid p90 4.7 kHz) and 98 % of 175 quiet-room phone mouth hisses. Independent of `mic_media_gate` (its
 * own setting), always on the speaker route (earbuds / Bluetooth: no echo, no rule), never for the Pico. Fitted to one
 * Short on one phone: the source of the 7 kHz band is not known yet (the `mic_status` band levels are there to find it).
 */
object PhoneGate {
    const val POP_SNR_DB = 14.0
    const val HUM_SNR_DB = 14.0
    const val HUM_CLARITY = 0.8
    /** Default for `hiss_media_max_centroid_hz`: a hiss above this centroid while media plays on the speaker is gated. */
    const val HISS_MEDIA_MAX_CENTROID_HZ = 6500
    private val HUMS = setOf("rise", "fall", "arch", "dip", "flat")
    private val DISCRETE = setOf("pop", "click")

    /** Why this sound is gated, or null if it passes. [snrDb] / [clarity] are the extractor's gate numbers (mic_sound.gate). */
    fun reason(label: String, snrDb: Double?, clarity: Double?): String? = when (label) {
        in DISCRETE -> if ((snrDb ?: 0.0) < POP_SNR_DB) "pop under ${POP_SNR_DB.toInt()} dB over the floor" else null
        in HUMS -> when {
            (snrDb ?: 0.0) < HUM_SNR_DB -> "hum under ${HUM_SNR_DB.toInt()} dB over the floor"
            (clarity ?: 0.0) < HUM_CLARITY -> "hum clarity under $HUM_CLARITY"
            else -> null
        }
        else -> null
    }

    /**
     * The media-hiss rule: why this hiss is gated, or null. [centroidHz]: the extractor's `centroid_hz` (mic_sound.gate);
     * [speakerMedia]: media is playing on the phone's own speaker (the `speaker` mode's test); [maxCentroidHz]: the
     * setting (0 = off); [source]: MicSettings.source (`pico` is never gated). A missing centroid passes (hiss was never
     * gated before this rule; the native gate object always carries it).
     */
    fun hissReason(label: String, centroidHz: Double?, speakerMedia: Boolean, maxCentroidHz: Int, source: String): String? {
        if (label != "hiss" || maxCentroidHz <= 0 || !speakerMedia || source == MicSettings.PICO) return null
        val c = centroidHz ?: return null
        return if (c > maxCentroidHz) "hiss centroid ${Math.round(c)} Hz over $maxCentroidHz Hz while media plays on the speaker" else null
    }

    /** Whether the gate applies now. [mode]: MicSettings.MEDIA_GATES; [speakerMedia]: media is playing on the phone's own speaker. */
    fun active(mode: String, mediaPlaying: Boolean, speakerMedia: Boolean): Boolean = when (mode) {
        "always" -> true
        "media" -> mediaPlaying
        "speaker" -> speakerMedia
        else -> false
    }
}
