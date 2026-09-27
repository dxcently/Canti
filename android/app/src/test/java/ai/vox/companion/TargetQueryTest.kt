package ai.vox.companion

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** The target pickers' query normaliser (TargetQuery.kt): the shared vectors, idempotence, the raw-text fallback. */
class TargetQueryTest {
    private val cases = JSONObject(TargetQueryTest::class.java.classLoader!!.getResource("target_query_cases.json")!!.readText())
        .getJSONArray("cases").let { a -> (0 until a.length()).map { a.getJSONArray(it).let { c -> c.getString(0) to c.getString(1) } } }

    @Test fun sharedVectors() {
        assertTrue(cases.size >= 30)
        val bad = cases.filter { (raw, want) -> TargetQuery.normalize(raw) != want }
            .map { (raw, want) -> "\"$raw\" -> \"${TargetQuery.normalize(raw)}\" (want \"$want\")" }
        assertEquals(bad.joinToString("\n"), 0, bad.size)
    }

    @Test fun idempotent() {
        for ((raw, _) in cases) {
            val once = TargetQuery.normalize(raw)
            assertEquals(raw, once, TargetQuery.normalize(once))
        }
    }

    @Test fun nothingLeftSendsTheRawText() {
        assertEquals("", TargetQuery.normalize("uh, um"))
        assertEquals("uh, um", TargetQuery.forPicker("  uh, um "))
        assertEquals("the settings", TargetQuery.forPicker("um the settings"))
    }

    /** The live path: PhraseGrammar has already lowercased and cleaned the query; the normaliser must not undo or break that. */
    @Test fun grammarCleanedQueriesPassThrough() {
        for (q in listOf("like button", "settings", "red one", "ok", "no thanks", "maybe later", "the second one from the top", "wi fi"))
            assertEquals(q, TargetQuery.normalize(q))
        val tap = PhraseGrammar.parse("um tap the uh like button", PhraseGrammar.Context(cursor = true)) as SpeechCommand.Tap
        assertEquals("like button", TargetQuery.forPicker(tap.query))
    }
}
