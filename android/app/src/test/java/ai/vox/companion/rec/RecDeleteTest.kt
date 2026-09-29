package ai.vox.companion.rec

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.file.Files

/** Contract T parity: RecSession.effectiveRows/takeRows/noSoundRows vs extractor/tests/fixtures/range_tombstones.json,
 *  plus delete / restore / purge / redo numbering on a temp dir. */
class RecDeleteTest {
    private val spec = File("../../extractor/prompts/range_v2.json").readBytes()

    private fun rows(arr: org.json.JSONArray): List<JSONObject> =
        (0 until arr.length()).map { arr.getJSONObject(it) }

    private fun key(o: JSONObject): String = "file=${o.optString("file")};redo=${o.optInt("redo")};ns=${o.optBoolean("no_sound")};at=${o.optInt("attempt")}"

    @Test fun tombstoneFixtureParity() {
        val f = JSONObject(File("../../extractor/tests/fixtures/range_tombstones.json").readText())
        val cases = f.getJSONArray("cases")
        assertTrue(cases.length() >= 8)
        for (ci in 0 until cases.length()) {
            val c = cases.getJSONObject(ci)
            val about = c.getString("about")
            val journal = rows(c.getJSONArray("journal"))
            val eff = RecSession.effectiveRows(journal)
            val takeRows = RecSession.takeRows(journal)
            val noSound = RecSession.noSoundRows(journal)

            // in_force / restorable
            assertEquals("$about in_force", jsonList(c.getJSONArray("in_force")), eff.inForce)
            assertEquals("$about restorable", jsonList(c.getJSONArray("restorable")), eff.restorable)

            // take_rows
            val want = c.getJSONObject("take_rows")
            assertEquals("$about take_rows keys", jsonKeys(want), takeRows.keys.toList())
            for (k in want.keys()) assertEquals("$about take_rows[$k]", key(want.getJSONObject(k)), key(takeRows[k]!!))

            // no_sound
            val wantNs = rows(c.getJSONArray("no_sound"))
            assertEquals("$about no_sound count", wantNs.size, noSound.size)
            for (i in wantNs.indices) assertEquals("$about no_sound[$i]", key(wantNs[i]), key(noSound[i]))
        }
    }

    private fun jsonList(a: org.json.JSONArray): List<String> = (0 until a.length()).map { a.getString(it) }
    private fun jsonKeys(o: JSONObject): List<String> = o.keys().asSequence().toList()

    private fun take(id: String = "range-bottom_hz-r1", block: String = "range") = RangePlan.Take(
        takeId = id, block = block, kind = "takes", cue = "c", expect = listOf("flat"),
        cond = mapOf("tone" to "hum", "pitch" to "bottom", "speed" to "normal", "loud" to "normal", "dist" to "hand", "gap" to "na"),
        condId = "hum-bottom-normal-normal-hand-na", rep = 1, bg = null, name = null, bgKind = null, level = null,
        seconds = null, quiet = false, targetS = 2.0, maxS = 5.0, anchor = "bottom_hz")

    private fun session(): Pair<RecSession, Int> {
        val root = Files.createTempDirectory("rec").toFile()
        val rate = 16000
        return RecSession(File(root, "range-self-0101"), rate, "phone built-in mic", rate) to rate
    }

    @Test fun deleteRestorePurgeAndRedoNumbering() {
        val (s, rate) = session()
        s.create(spec, "short", "self", emptyMap())
        val clip = ShortArray(rate * 2)
        s.saveTake(take(), clip, rate.toLong(), 0, emptyList(), false)                    // redo 0 (heard)
        s.saveTake(take(), clip, rate.toLong(), 1, emptyList(), true)                     // redo 1 (missed)
        assertEquals(2, s.redoFor("range-bottom_hz-r1"))

        // delete scope take moves both WAVs and excludes every earlier row
        val del = s.delete("range-bottom_hz-r1", "take", null)
        assertTrue(File(s.root, "takes/range/range-bottom_hz-r1.wav").let { !it.exists() })
        assertTrue(File(s.root, "trash/$del/takes/range/range-bottom_hz-r1.wav").exists())
        assertTrue(s.latestLabels().isEmpty())
        assertEquals(2, s.redoFor("range-bottom_hz-r1"))   // redo over ALL take rows, excluded included

        // re-record: redo continues (never reuses a file name)
        s.saveTake(take(), clip, rate.toLong(), 2, emptyList(), false)
        assertEquals(3, s.redoFor("range-bottom_hz-r1"))
        assertEquals("range-bottom_hz-r1", s.latestLabels().keys.first())

        // restore is refused (the take was re-recorded)
        try { s.restore(del); assertTrue(false) } catch (e: IllegalArgumentException) { assertTrue(e.message!!.contains("exists now")) }

        // purge keeps the delete in force but it can no longer be restored
        s.purge(listOf(del))
        assertTrue(RecSession.effectiveRows(s.labelRows()).inForce.contains(del))
        assertTrue(!RecSession.effectiveRows(s.labelRows()).restorable.contains(del))
        try { s.restore(del); assertTrue(false) } catch (e: IllegalArgumentException) { assertTrue(e.message!!.contains("purged")) }
    }

    @Test fun deleteAttemptScopeAndBackground() {
        val (s, rate) = session()
        s.create(spec, "full", "self", emptyMap())
        val clip = ShortArray(rate * 2)
        // two missed attempts then a heard one
        s.saveTake(take(), clip, rate.toLong(), 0, emptyList(), true)
        s.saveTake(take(), clip, rate.toLong(), 1, emptyList(), true)
        s.saveTake(take(), clip, rate.toLong(), 2, emptyList(), false)

        // delete attempt 1 excludes only that missed attempt
        val del = s.delete("range-bottom_hz-r1", "attempt", 1)
        assertEquals(2, s.latestLabels()["range-bottom_hz-r1"]!!.getInt("redo"))   // the heard row (redo 2) remains
        assertTrue(!File(s.root, "takes/range/range-bottom_hz-r1.a1.wav").exists())

        // restore the attempt delete: the missed file comes back
        s.restore(del)
        assertTrue(File(s.root, "takes/range/range-bottom_hz-r1.a1.wav").exists())

        // a background delete (scope take, name in place of take_id)
        val bg = RangePlan.Take("backgrounds-media-30-r1", "backgrounds", "backgrounds", "cue", emptyList(),
            emptyMap(), null, 1, null, "media-30", "media", 30, 60.0, false, null, null, null)
        s.saveBackground(bg, ShortArray((60.0 * rate).toInt()))
        val bdel = s.deleteBackground("media-30")
        assertTrue(File(s.root, "trash/$bdel/backgrounds/media-30.wav").exists())
        assertTrue(s.latestBackgrounds().isEmpty())
        // restore refused once purged (backgrounds journal sees its own purge)
        s.purge(listOf(bdel))
        try { s.restore(bdel); assertTrue(false) } catch (e: IllegalArgumentException) { assertTrue(e.message!!.contains("purged")) }
    }
}
