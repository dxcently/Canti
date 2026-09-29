package ai.vox.companion.rec

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.file.Files

/** RecSession writes the exact layout range_layout.validate_session reads (contract §7). */
class RecSessionTest {
    private val spec = File("../../extractor/prompts/range_v1.json").readBytes()

    private fun take(block: String = "range", id: String = "bottom_hz", rep: Int = 1) = RangePlan.Take(
        takeId = "$block-$id-r$rep", block = block, kind = "takes", cue = "c",
        expect = listOf("flat"),
        cond = mapOf("tone" to "hum", "pitch" to "bottom", "speed" to "normal", "loud" to "normal", "dist" to "hand", "gap" to "na"),
        condId = "hum-bottom-normal-normal-hand-na", rep = rep, bg = null,
        name = null, bgKind = null, level = null, seconds = null, quiet = false, targetS = 2.0, maxS = 5.0, anchor = "bottom_hz")

    @Test fun writesTheLayoutRangeLayoutReads() {
        val root = Files.createTempDirectory("rec").toFile()
        val rate = 16000
        val s = RecSession(File(root, "range-self-0101"), rate, "phone built-in mic", rate)   // pre-roll = 1 s
        s.create(spec, "short", "self", emptyMap())

        val meta = JSONObject(File(s.root, "session.json").readText())
        assertEquals("phone", meta.getString("device"))
        assertEquals("phone built-in mic", meta.getString("mic"))
        assertEquals(16000, meta.getInt("rate"))
        assertEquals(1, meta.getInt("channels"))
        assertEquals("range_v1", meta.getString("spec"))
        assertFalse(meta.getBoolean("synthetic"))
        assertEquals("short", meta.getString("profile"))
        assertEquals("self", meta.getString("speaker"))
        assertTrue(meta.getJSONObject("range").isNull("bottom_hz"))
        assertTrue(meta.getBoolean("range_pending"))
        assertEquals("app", meta.getString("recorder"))
        assertEquals(1, meta.getJSONArray("sittings").length())
        // spec.json is the bundled spec verbatim
        assertTrue(File(s.root, "spec.json").readBytes().contentEquals(spec))
        for (f in listOf("labels.jsonl", "backgrounds.jsonl", "ratings.jsonl")) assertTrue(File(s.root, f).exists())

        val clip = ShortArray(rate * 2)   // 2 s: [GO - 1 s, GO + 1 s)
        val goFrame = rate.toLong()       // GO at 1 s
        val row = s.saveTake(take(), clip, goFrame, 0, emptyList(), false)
        assertEquals("range-bottom_hz-r1", row.getString("take_id"))
        assertEquals("range", row.getString("block"))
        assertEquals(1000.0, row.getDouble("t_go_ms"), 1e-9)
        assertEquals(2000.0, row.getDouble("dur_ms"), 1e-9)
        assertEquals(0.0, row.getDouble("clip_start_ms"), 1e-9)
        assertEquals(1000.0, row.getDouble("go_offset_ms"), 1e-9)
        assertEquals(0, row.getInt("redo"))
        // clip_start + go_offset == t_go (frame counts, no rounding)
        assertEquals(row.getDouble("t_go_ms"), row.getDouble("clip_start_ms") + row.getDouble("go_offset_ms"), 1e-9)
        // the WAV's dur matches dur_ms within one sample
        val wav = File(s.root, "takes/range/range-bottom_hz-r1.wav")
        val dataBytes = wav.length() - 44
        assertEquals(clip.size * 2, dataBytes.toInt())
        assertEquals(row.getDouble("dur_ms"), dataBytes / 2 * 1000.0 / rate, 1e-6)
    }

    @Test fun lastRowWinsRedo() {
        val root = Files.createTempDirectory("rec").toFile()
        val rate = 16000
        val s = RecSession(File(root, "range-self-0101"), rate, "phone built-in mic", rate)
        s.create(spec, "short", "self", emptyMap())
        val clip = ShortArray(rate * 2)
        s.saveTake(take(), clip, rate.toLong(), 0, emptyList(), false)
        assertEquals(1, s.redoFor("range-bottom_hz-r1"))
        s.saveTake(take(), clip, rate.toLong(), 1, emptyList(), false)   // redo = previous rows
        assertEquals(2, s.labelRows().size)   // both rows kept, last wins
        assertEquals(1, s.latestLabels()["range-bottom_hz-r1"]!!.getInt("redo"))
    }

    @Test fun openChecksSpecRateAndMic() {
        val root = Files.createTempDirectory("rec").toFile()
        val rate = 16000
        val s = RecSession(File(root, "range-self-0101"), rate, "phone built-in mic", rate)
        s.create(spec, "short", "self", emptyMap())
        // same spec + rate + mic: appends a sitting
        val s2 = RecSession(File(root, "range-self-0101"), rate, "phone built-in mic", rate)
        s2.open(spec, rate, "phone built-in mic")
        assertEquals(2, s2.meta().getJSONArray("sittings").length())
        // a differing rate is refused
        try { RecSession(File(root, "range-self-0101"), 48000, "phone built-in mic", 48000).open(spec, 48000, "phone built-in mic"); assertTrue(false) }
        catch (e: IllegalArgumentException) { assertTrue(e.message!!.contains("16000")) }
    }

    @Test fun backgroundRow() {
        val root = Files.createTempDirectory("rec").toFile()
        val rate = 16000
        val s = RecSession(File(root, "range-self-0101"), rate, "phone built-in mic", rate)
        s.create(spec, "full", "self", emptyMap())
        val bg = RangePlan.Take("backgrounds-media-30-r1", "backgrounds", "backgrounds", "cue", emptyList(),
            emptyMap(), null, 1, null, "media-30", "media", 30, 60.0, false, null, null, null)
        val clip = ShortArray((60.0 * rate).toInt())
        val row = s.saveBackground(bg, clip)
        assertEquals("media-30", row.getString("name"))
        assertEquals("media", row.getString("kind"))
        assertEquals(30, row.getInt("level"))
        assertEquals(60.0, row.getDouble("seconds"), 1e-9)
        assertEquals("backgrounds/media-30.wav", row.getString("file"))
    }
}
