package ai.vox.companion.rec

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.file.Files

/** Quick record (contract §5 qr_*): the snapshot math on synthetic HeardLog entries, and a valid save. */
class QuickRecTest {
    private class FakeEnv : QuickRec.Env {
        override val source = "usb"
        override val micName = "phone built-in mic"
        override val appForeground = "com.test"
        override val mode = "gesture"
        override val minLevelDb = -45.0
    }

    class FakeScheduler : ai.vox.companion.Scheduler {
        var now = 0L
        override fun now() = now
        override fun schedule(delayMs: Long, task: () -> Unit): () -> Unit = { }
    }

    private fun ringWrite(r: RingBuffer, n: Int) {
        val b = ByteBuffer.allocateDirect(n * 2).order(ByteOrder.nativeOrder())
        for (i in 0 until n) b.putShort(100)
        r.write(b, n, 0, 16000, 0)
    }

    @Test fun snapshotSoundsAgoAndInClip() {
        val ring = RingBuffer()
        ringWrite(ring, 16000)   // 1 s at 16 kHz: clip [0, 16000)
        val heard = HeardLog()
        heard.setGen(0)
        val snd = HeardLog.Sound(100, "hiss", 0, 200, 500, emptyList(), 120.0, null, null, null)
        heard.append(snd)
        heard.append(HeardLog.Resolve(150, 1, "hiss"))
        heard.append(HeardLog.Decision(160, 1, "back"))
        heard.append(HeardLog.Exec(170, 1, true))

        val sched = FakeScheduler(); sched.now = 300
        val q = QuickRec(sched, { 12345L }, ring, heard, FakeEnv(), Files.createTempDirectory("qr").toFile())
        val snap = q.snap()
        assertEquals("12345", snap["id"])
        assertEquals(1.0, snap["seconds"] as Double, 1e-9)
        assertEquals(16000, snap["rate"])
        assertEquals(-45.0, snap["min_db"] as Double, 1e-9)
        val sounds = snap["sounds"] as List<Map<String, Any?>>
        assertEquals(1, sounds.size)
        val s = sounds[0]
        assertEquals("hiss", s["label"])
        assertEquals(200L, s["t_start_ms"])
        assertEquals(500L, s["t_end_ms"])
        assertEquals(200L, s["rel_ms"])   // start - clip start (0)
        assertEquals(0.2, s["ago_s"] as Double, 1e-6)   // (300 - 100)/1000
        assertEquals("HISS → back", s["did_text"])
        val last = snap["last_action"] as Map<String, Any?>
        assertEquals("HISS → back", last["text"])
        assertTrue(last["in_clip"] as Boolean)   // t_end_ms 500 in [0, 1000)
    }

    @Test fun saveWritesValidWavAndMeta() {
        val ring = RingBuffer()
        ringWrite(ring, 16000)
        val heard = HeardLog()
        heard.setGen(0)
        val dir = Files.createTempDirectory("qr").toFile()
        val q = QuickRec(FakeScheduler(), { 12345L }, ring, heard, FakeEnv(), dir)
        val snap = q.snap()
        val id = snap["id"] as String
        val r = q.save(id, "hiss", "a test note", null)   // no sounds in this snapshot: nothing to point at
        assertEquals(true, r["ok"])
        val clip = File(dir, "quickrec/$id/clip.wav")
        assertTrue(clip.exists())
        assertEquals(44L + 16000 * 2, clip.length())   // RIFF header + PCM16
        val meta = org.json.JSONObject(File(dir, "quickrec/$id/meta.json").readText())
        assertEquals(1, meta.getInt("version"))
        assertEquals("hiss", meta.getString("label"))
        assertEquals(16000, meta.getInt("rate"))
        assertEquals("phone built-in mic", meta.getString("mic"))
        assertEquals("usb", meta.getString("source"))   // the running capture's source, not a constant
        // a new snap after save is gone (discarded by save)
        assertEquals(null, q.pending()["id"])
    }

    @Test fun snapRefusesAnEmptyRingAndSaveChecksTheLabel() {
        val heard = HeardLog()
        val dir = Files.createTempDirectory("qr").toFile()
        val empty = QuickRec(FakeScheduler(), { 1L }, RingBuffer(), heard, FakeEnv(), dir)
        val none = empty.snap()
        assertEquals(null, none["id"])
        assertTrue((none["error"] as String).contains("not listening"))

        val ring = RingBuffer()
        ringWrite(ring, 16000)
        val q = QuickRec(FakeScheduler(), { 2L }, ring, heard, FakeEnv(), dir)
        val id = q.snap()["id"] as String
        assertEquals(false, q.save(id, "whistle", null, null)["ok"])   // not a picker label
        assertEquals(false, q.save(id, "hiss", null, 3)["ok"])         // no sound #3 in this snapshot
        assertTrue(!File(dir, "quickrec/$id").exists())                   // nothing written by a refused save
        assertEquals(true, q.save(id, "misfire", null, null)["ok"])
    }
}
