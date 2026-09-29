package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** ChainControl.parse (Chain.kt): the exact S6 phrases, and what is NOT a control. */
class ChainControlTest {
    private fun parse(s: String) = ChainControl.parse(s)

    @Test fun everyS6Phrase() {
        for (s in listOf("try again", "again", "once more", "retry")) assertEquals(s, ChainControl.Cmd.Retry, parse(s))
        for (s in listOf("skip", "skip it", "skip that", "skip this step")) assertEquals(s, ChainControl.Cmd.Skip, parse(s))
        for (s in listOf("continue", "go on", "keep going", "carry on")) assertEquals(s, ChainControl.Cmd.Continue, parse(s))
        for (s in listOf("cancel", "stop", "cancel that", "stop the chain", "forget it", "never mind")) assertEquals(s, ChainControl.Cmd.Cancel, parse(s))
        for (s in listOf("undo", "undo that", "not that", "no not that", "i didnt mean that", "no i didnt mean that", "thats wrong")) assertEquals(s, ChainControl.Cmd.Undo, parse(s))
        for (s in listOf("done", "thats it", "thats all", "im done", "finished")) assertEquals(s, ChainControl.Cmd.Done, parse(s))
        assertEquals(ChainControl.Cmd.RejectNext, parse("not that one"))
    }

    @Test fun rewinds() {
        assertEquals(ChainControl.Cmd.Rewind("menu"), parse("no not the menu"))
        assertEquals(ChainControl.Cmd.Rewind("menu"), parse("not the menu"))
        assertEquals(ChainControl.Cmd.Rewind("menu"), parse("no not menu"))
        assertEquals(ChainControl.Cmd.Rewind("settings"), parse("not the settings"))
    }

    @Test fun cleaning() {
        assertEquals(ChainControl.Cmd.Undo, parse("please undo that"))
        assertEquals(ChainControl.Cmd.Cancel, parse("no wait, cancel"))   // the last correction part
        assertEquals(ChainControl.Cmd.Undo, parse("ok no not that"))
        assertEquals(ChainControl.Cmd.Retry, parse("try again please"))
    }

    @Test fun notControls() {
        assertNull(parse("undo the last two"))     // exact only
        assertNull(parse("skip this video"))        // a Nav/Swipe, not a control
        assertNull(parse("no"))                     // "no" alone is nothing
        assertNull(parse(""))
        assertNull(parse("um"))
    }
}
