package ai.vox.companion.rec

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.file.Files

/** RecLibrary (contract L): listing phone + pushed pc sessions with counts/missing_n, tombstones honoured, damaged
 *  sessions as error rows, and the rec_play path check. Synthetic sessions in temp dirs. */
class RecLibraryTest {
    private val v2 = File("../../extractor/prompts/range_v2.json").readBytes()
    private val v1 = File("../../extractor/prompts/range_v1.json").readBytes()

    private fun take(spec: ByteArray, profile: String = "short") =
        RangePlan.parse(spec, profile).takes.first { it.kind == "takes" }

    private fun totalTakes(spec: ByteArray, profile: String = "short") =
        RangePlan.parse(spec, profile).takes.count { it.kind == "takes" }

    /** Builds one session under files/range (phone) or files/range_pc (pc); optionally records one heard take. */
    private fun build(filesDir: File, origin: String, name: String, spec: ByteArray, profile: String = "short",
                      heard: Boolean = true): File {
        val root = File(filesDir, if (origin == RecLibrary.PC) "range_pc/$name" else "range/$name")
        val s = RecSession(root, 16000, "phone built-in mic", 16000)
        s.create(spec, profile, "self", emptyMap())
        if (heard) s.saveTake(take(spec, profile), ShortArray(16000 * 2), 16000L, 0, emptyList(), false)
        return root
    }

    @Suppress("UNCHECKED_CAST")
    private fun sessions(list: Map<String, Any?>): List<Map<String, Any?>> = list["sessions"] as List<Map<String, Any?>>

    private fun find(list: Map<String, Any?>, name: String): Map<String, Any?> =
        sessions(list).first { it["name"] == name }

    @Test fun listsV1V2AndPcWithCounts() {
        val filesDir = Files.createTempDirectory("lib").toFile()
        build(filesDir, RecLibrary.PHONE, "range-v1-0001", v1)
        build(filesDir, RecLibrary.PHONE, "range-v2-0001", v2)
        build(filesDir, RecLibrary.PC, "range-pc-0001", v2)
        val lib = RecLibrary(filesDir, v2)
        val list = lib.list()

        val total = totalTakes(v2)
        val v1Total = totalTakes(v1)
        val names = sessions(list).map { it["name"] as String }
        assertEquals(listOf("range-pc-0001", "range-v1-0001", "range-v2-0001"), names.sorted())

        val phoneV2 = find(list, "range-v2-0001")
        assertEquals("phone", phoneV2["origin"])
        assertEquals("range_v2", phoneV2["spec"])
        assertEquals("self", phoneV2["speaker"])
        assertEquals("short", phoneV2["profile"])
        assertEquals(1, phoneV2["done"]); assertEquals(total, phoneV2["total"])
        assertEquals(0, phoneV2["no_sound"]); assertEquals(0, phoneV2["deleted"])
        assertEquals(total - 1, phoneV2["missing_n"])
        assertEquals(true, phoneV2["resumable"])

        val phoneV1 = find(list, "range-v1-0001")
        assertEquals("range_v1", phoneV1["spec"])
        assertEquals(1, phoneV1["done"]); assertEquals(v1Total, phoneV1["total"])
        assertEquals(v1Total - 1, phoneV1["missing_n"])
        assertEquals(false, phoneV1["resumable"])   // v1 is not the bundled version

        val pc = find(list, "range-pc-0001")
        assertEquals("pc", pc["origin"])
        assertEquals(1, pc["done"]); assertEquals(total, pc["total"])
        assertEquals(false, pc["resumable"])        // pc sessions are never resumable here

        assertEquals(mapOf("version" to "range_v2"), list["bundled"])
    }

    @Test fun tombstonesChangeCounts() {
        val filesDir = Files.createTempDirectory("lib").toFile()
        val root = build(filesDir, RecLibrary.PHONE, "range-self-0001", v2)
        val s = RecSession(root, 16000, "phone built-in mic", 16000)
        val total = totalTakes(v2)

        // delete the heard take: it stops counting, the delete is in force
        val del = s.delete(take(v2).takeId, "take", null)
        var list = RecLibrary(filesDir, v2).list()
        var row = find(list, "range-self-0001")
        assertEquals(0, row["done"]); assertEquals(1, row["deleted"]); assertEquals(total, row["missing_n"])

        // restore: it counts again, the delete leaves force
        s.restore(del)
        list = RecLibrary(filesDir, v2).list()
        row = find(list, "range-self-0001")
        assertEquals(1, row["done"]); assertEquals(0, row["deleted"]); assertEquals(total - 1, row["missing_n"])

        // purge keeps the delete in force forever (counts stay gone)
        val del2 = s.delete(take(v2).takeId, "take", null)
        s.purge(listOf(del2))
        list = RecLibrary(filesDir, v2).list()
        row = find(list, "range-self-0001")
        assertEquals(0, row["done"]); assertEquals(1, row["deleted"])
        try { s.restore(del2); assertTrue(false) } catch (e: IllegalArgumentException) { assertTrue(e.message!!.contains("purged")) }
    }

    @Test fun noSoundAndMissingAreDistinct() {
        val filesDir = Files.createTempDirectory("lib").toFile()
        val root = build(filesDir, RecLibrary.PHONE, "range-self-0001", v2, heard = false)
        val s = RecSession(root, 16000, "phone built-in mic", 16000)
        val total = totalTakes(v2)
        // one heard take + one missed (no_sound) attempt of another take
        val t1 = RangePlan.parse(v2, "short").takes.first { it.kind == "takes" }
        val t2 = RangePlan.parse(v2, "short").takes.first { it.kind == "takes" && it.takeId != t1.takeId }
        s.saveTake(t1, ShortArray(16000 * 2), 16000L, 0, emptyList(), false)
        s.saveTake(t2, ShortArray(16000 * 2), 16000L, 0, emptyList(), true)   // no_sound

        val lib = RecLibrary(filesDir, v2)
        val row = find(lib.list(), "range-self-0001")
        assertEquals(1, row["done"]); assertEquals(1, row["no_sound"]); assertEquals(total - 2, row["missing_n"])

        val detail = lib.session("range-self-0001", RecLibrary.PHONE)
        @Suppress("UNCHECKED_CAST")
        val takes = detail["takes"] as List<Map<String, Any?>>
        assertEquals("done", takes.first { it["take_id"] == t1.takeId }["status"])
        assertEquals("no_sound", takes.first { it["take_id"] == t2.takeId }["status"])
        assertEquals("missing", takes.first { it["take_id"] != t1.takeId && it["take_id"] != t2.takeId }["status"])
    }

    @Test fun damagedSessionIsAnErrorRow() {
        val filesDir = Files.createTempDirectory("lib").toFile()
        val dir = File(filesDir, "range/broken-0001"); dir.mkdirs()
        File(dir, "session.json").writeText("{ not json")
        val list = RecLibrary(filesDir, v2).list()
        val row = find(list, "broken-0001")
        assertEquals("phone", row["origin"])
        assertNotNull(row["error"])
        assertNull(row["done"])   // the damaged row carries only name/origin/error
    }

    @Test fun recPlayPathTraversalIsRefused() {
        val dir = Files.createTempDirectory("lib").toFile()
        // ../ and absolute paths escape
        try { RecLibrary.resolvePlay(dir, "../x.wav"); assertTrue(false) } catch (e: IllegalArgumentException) {}
        try { RecLibrary.resolvePlay(dir, "/abs/x.wav"); assertTrue(false) } catch (e: IllegalArgumentException) {}
        // a symlink out of the session is refused (canonicalised)
        val outsideDir = Files.createTempDirectory("out").toFile()
        val outside = File(outsideDir, "out.wav"); outside.writeBytes(ByteArray(44))
        Files.createSymbolicLink(File(dir, "link.wav").toPath(), outside.toPath())
        try { RecLibrary.resolvePlay(dir, "link.wav"); assertTrue(false) } catch (e: IllegalArgumentException) {}
        // a plain file inside the session resolves
        val inside = File(dir, "ok.wav"); inside.writeBytes(ByteArray(44))
        assertEquals(inside.canonicalFile, RecLibrary.resolvePlay(dir, "ok.wav"))
    }

    @Test fun bundledSpecBrowses() {
        val lib = RecLibrary(Files.createTempDirectory("lib").toFile(), v2)
        val spec = lib.spec("short")
        assertEquals("range_v2", spec["version"]); assertEquals("short", spec["profile"])
        @Suppress("UNCHECKED_CAST")
        val blocks = spec["blocks"] as List<Map<String, Any?>>
        assertTrue(blocks.isNotEmpty())
        @Suppress("UNCHECKED_CAST")
        val takes = blocks.first()["takes"] as List<Map<String, Any?>>
        assertTrue(takes.first().containsKey("take_id") && takes.first().containsKey("cue"))
        // a bad profile is refused
        try { lib.spec("bogus"); assertTrue(false) } catch (e: IllegalArgumentException) {}
    }
}
