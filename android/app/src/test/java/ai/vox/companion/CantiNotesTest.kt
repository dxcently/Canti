package ai.vox.companion

import java.io.File
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Test

/** CantiNotes.kt: the local note file — add/read/delete, the line cap, and skipping a corrupt line. */
class CantiNotesTest {
    private fun dir(): File = File.createTempFile("canti_notes", "").let { it.delete(); it.mkdirs(); it }

    private fun note(word: String) = JSONObject().put("words", word).put("ts", 1)

    @Test fun addThenRead() {
        val d = dir()
        val notes = CantiNotes(d)
        notes.add(note("a"))
        notes.add(note("b"))
        assertEquals(listOf("a", "b"), notes.read().map { it.getString("words") })
    }

    @Test fun readThenDeleteEmpties() {
        val d = dir()
        val notes = CantiNotes(d)
        notes.add(note("a"))
        assertEquals(1, notes.read().size)
        assertEquals(1, notes.delete())
        assertEquals(0, notes.read().size)
        assertEquals(0, notes.delete())   // already gone
    }

    @Test fun capDropsOldest() {
        val d = dir()
        val notes = CantiNotes(d, max = 3)
        notes.add(note("a")); notes.add(note("b")); notes.add(note("c")); notes.add(note("d"))
        assertEquals(listOf("b", "c", "d"), notes.read().map { it.getString("words") })
    }

    @Test fun corruptLineIsSkipped() {
        val d = dir()
        val notes = CantiNotes(d)
        notes.add(note("good"))
        File(d, "canti_notes.jsonl").appendText("not json\n")
        assertEquals(listOf("good"), notes.read().map { it.getString("words") })
    }
}
