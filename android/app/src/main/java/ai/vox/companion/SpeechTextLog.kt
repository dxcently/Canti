package ai.vox.companion

/**
 * W12: spoken text is redacted from the event log by default; a `log_speech_text` switch turns text logging back on
 * for a while and auto-expires (60 min). Pure (SpeechTextLogTest on the JVM).
 *
 * [enabled] is the switch-and-expiry gate; [summary] is the fixed-field replacement that carries only a length and a
 * word count, never the words themselves.
 */
object SpeechTextLog {
    const val AUTO_EXPIRE_MS = 60 * 60 * 1000L

    /** On iff the flag is set AND the clock is still before the stored expiry. */
    fun enabled(flag: Boolean, expiryMs: Long, nowMs: Long): Boolean = flag && nowMs < expiryMs

    /** The redacted form while off: length and word count only. */
    fun summary(text: String): String = "${text.length} chars, ${text.split(' ').count { it.isNotEmpty() }} words"
}
