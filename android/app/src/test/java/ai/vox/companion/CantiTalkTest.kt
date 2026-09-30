package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** CantiTalk.kt: about-Canti is a command unless it explicitly targets Canti (K1-K6). */
class CantiTalkTest {
    private fun ui(badge: Boolean = false, strip: Boolean = false, queue: Boolean = false,
                   preview: Boolean = false, picker: Boolean = false) =
        CantiTalk.CantiUi(badge, strip, queue, preview, picker)

    private val badgeUp = ui(badge = true)
    private val stripUp = ui(strip = true)
    private val queueUp = ui(queue = true)
    private val pickerUp = ui(picker = true)

    private fun note() = CantiTalk.Result(null, true)
    private fun fix(f: CantiTalk.Fix) = CantiTalk.Result(f, false)

    // phrase -> (ui, expected); a null expected means "not about Canti" (a normal command).
    private val table: List<Triple<String, CantiTalk.CantiUi, CantiTalk.Result?>> = listOf(
        // commands (a concrete parse, or a Canti noun without a fix verb/complaint) — never about Canti
        Triple("open candy crush", ui(), null),
        Triple("turn on subtitles", ui(), null),
        Triple("show the transcript", ui(), null),
        Triple("open the queue", ui(), null),
        Triple("tap the badge icon", ui(), null),
        Triple("clear the badge", ui(), null),
        Triple("tap the numbers", pickerUp, null),          // "tap the numbers" is a command even with the picker up
        Triple("the numbers", ui(), null),                  // no number overlay -> a command
        Triple("hey canti could you open youtube", ui(), null),
        Triple("canti please scroll down", ui(), null),
        Triple("canti can you go back", ui(), null),
        Triple("canti, scroll down", ui(), null),
        Triple("tap the menu button", ui(), null),
        Triple("swipe the first one away", ui(), null),     // an item swipe is a command
        Triple("open settings then tap wifi", ui(), null),
        Triple("move the badge", ui(), null),               // no badge up -> not a fix
        Triple("candy the badge is in the way", ui(), null), // "candy" is not a marker, badge not up
        // about Canti
        Triple("canti keeps mishearing me", ui(), note()),
        Triple("canti you tapped the wrong thing", ui(), note()),
        Triple("the box is covering the button", stripUp, fix(CantiTalk.Fix.PANEL_OTHER_END)),
        Triple("move the badge", badgeUp, fix(CantiTalk.Fix.MOVE_BADGE)),
        Triple("why is the orange outline on that", ui(), note()),
        Triple("hide your subtitles", stripUp, fix(CantiTalk.Fix.HIDE_STRIP)),
        Triple("hide the queue", queueUp, fix(CantiTalk.Fix.HIDE_QUEUE)),
        Triple("the badge is in the way", badgeUp, fix(CantiTalk.Fix.MOVE_BADGE)),
        Triple("orange box", ui(), note()),
        Triple("candy the badge is in the way", badgeUp, fix(CantiTalk.Fix.MOVE_BADGE)),
        Triple("move your badge", ui(), fix(CantiTalk.Fix.MOVE_BADGE)),
        Triple("get rid of the queue", queueUp, fix(CantiTalk.Fix.HIDE_QUEUE)),
        Triple("the transcript is covering the button", stripUp, fix(CantiTalk.Fix.HIDE_STRIP)),
        Triple("the numbers", pickerUp, note()),            // number overlay up -> about Canti
    )

    @Test fun table() {
        val bad = table.mapNotNull { (said, ui, want) ->
            val got = CantiTalk.detect(listOf(said), ui)
            if (got == want) null else "\"$said\" (ui=${ui}): want $want, got $got"
        }
        assertTrue(bad.joinToString("\n", "\n"), bad.isEmpty())
    }
}
