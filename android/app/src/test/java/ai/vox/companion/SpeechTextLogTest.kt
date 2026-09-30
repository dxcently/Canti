package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** SpeechTextLog.kt: the log_speech_text switch-and-expiry gate, and the fixed-field redaction summary. */
class SpeechTextLogTest {
    @Test fun offByDefault() {
        assertFalse(SpeechTextLog.enabled(false, 0L, 1000L))
        assertFalse(SpeechTextLog.enabled(false, 9999L, 1000L))   // a future expiry does not re-enable a cleared flag
    }

    @Test fun onWithinExpiry() {
        assertTrue(SpeechTextLog.enabled(true, 2000L, 1000L))
    }

    @Test fun expiredIsOff() {
        assertFalse(SpeechTextLog.enabled(true, 1000L, 2000L))
    }

    @Test fun summaryCarriesLengthAndWordsOnly() {
        assertEquals("11 chars, 2 words", SpeechTextLog.summary("hello world"))
        assertEquals("0 chars, 0 words", SpeechTextLog.summary(""))
    }
}
