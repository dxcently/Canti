package ai.vox.companion

import java.io.File
import org.json.JSONObject

/**
 * The local about-Canti note file (pure Kotlin + File/JSONObject; CantiNotesTest).
 *
 * On-device, in the app's filesDir: one JSON object per line (`canti_notes.jsonl`), capped at [max] lines (the oldest
 * drop). Read-and-delete happens only through the socket-only `canti_notes` op (W9); nothing else reads it, and the
 * utterance words are stored only here (W8).
 */
class CantiNotes(private val dir: File, private val max: Int = 200) {
    private val file: File get() = File(dir, "canti_notes.jsonl")

    /** Append one note, keeping at most [max] lines (dropping the oldest). */
    fun add(json: JSONObject) {
        dir.mkdirs()
        val lines = readRaw().toMutableList()
        lines.add(json.toString())
        while (lines.size > max) lines.removeAt(0)
        file.writeText(lines.joinToString("\n") + if (lines.isNotEmpty()) "\n" else "")
    }

    /** All notes, oldest first; a line that is not a JSON object is skipped (never throws). */
    fun read(): List<JSONObject> = readRaw().mapNotNull { line ->
        try { JSONObject(line) } catch (_: Exception) { null }
    }

    /** The number of notes read, then delete the file. */
    fun delete(): Int {
        val n = read().size
        if (file.exists()) file.delete()
        return n
    }

    private fun readRaw(): List<String> = if (file.exists()) file.readLines() else emptyList()
}
