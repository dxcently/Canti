package ai.vox.companion

import ai.vox.companion.audio.Measure
import ai.vox.companion.audio.MeasureSession
import ai.vox.companion.audio.MicSettings
import ai.vox.companion.audio.WavWriter
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.ShortBuffer

/**
 * The near-field measurement harness's pure pieces (Measure.kt): the prompt schedule, the WAV header (mono / stereo,
 * patched on stop), the stream-ms mapping, the stereo de-interleave, the max_s auto-stop and the start refusal.
 */
class MeasureTest {
    private fun le16(b: ByteArray, off: Int) = (b[off].toInt() and 0xFF) or ((b[off + 1].toInt() and 0xFF) shl 8)
    private fun le32(b: ByteArray, off: Int) = (b[off].toInt() and 0xFF) or
        ((b[off + 1].toInt() and 0xFF) shl 8) or ((b[off + 2].toInt() and 0xFF) shl 16) or
        ((b[off + 3].toInt() and 0xFF) shl 24)
    private fun ascii(b: ByteArray, off: Int, n: Int) = String(b, off, n, Charsets.US_ASCII)

    // --- prompt schedule (round-robin) ----------------------------------------------------------------------------

    @Test fun promptScheduleIsRoundRobin() {
        val g = listOf("rise", "fall", "click", "click click", "hiss")
        assertEquals("rise", Measure.promptGesture(g, 0))
        assertEquals("fall", Measure.promptGesture(g, 1))
        assertEquals("hiss", Measure.promptGesture(g, 4))
        assertEquals("rise", Measure.promptGesture(g, 5))   // wraps
        assertEquals("click click", Measure.promptGesture(g, 8))   // 8 mod 5 = 3
    }

    @Test fun promptCountIsWholePromptsBeforeMaxS() {
        assertEquals(60, Measure.promptCount(300, 5000))
        assertEquals(15, Measure.promptCount(30, 2000))
        assertEquals(60, Measure.promptCount(1200, 20000))
    }

    // --- stream-ms mapping -----------------------------------------------------------------------------------------

    @Test fun streamMsFromPushedFrames() {
        assertEquals(0L, Measure.streamMs(0, 16000))
        assertEquals(1000L, Measure.streamMs(16000, 16000))
        assertEquals(500L, Measure.streamMs(8000, 16000))
        assertEquals(1000L, Measure.streamMs(48000, 48000))
    }

    @Test fun nanoToStreamMsAgainstFrame0() {
        assertEquals(0L, Measure.nanoToStreamMs(1_000_000L, 1_000_000L))
        assertEquals(1500L, Measure.nanoToStreamMs(2_500_000_000L, 1_000_000_000L))
        assertEquals(-20L, Measure.nanoToStreamMs(980_000_000L, 1_000_000_000L))   // before frame0
    }

    // --- max_s auto-stop -------------------------------------------------------------------------------------------

    @Test fun maxReachedBoundary() {
        assertFalse(Measure.maxReached(300, 299_999L))
        assertTrue(Measure.maxReached(300, 300_000L))
        assertTrue(Measure.maxReached(30, 30_000L))
        assertFalse(Measure.maxReached(30, 29_999L))
    }

    // --- start refusal ---------------------------------------------------------------------------------------------

    @Test fun startRefusedOnPico() {
        assertEquals("measure needs sound_source phone or usb, not pico",
            Measure.startError(MicSettings.PICO, capturing = true, alreadyRunning = false))
        assertNull(Measure.startError(MicSettings.PHONE, capturing = true, alreadyRunning = false))
        assertNull(Measure.startError(MicSettings.USB, capturing = true, alreadyRunning = false))
    }

    @Test fun startRefusedWhenNotCapturingOrRunning() {
        assertEquals("the mic capture is not listening",
            Measure.startError(MicSettings.PHONE, capturing = false, alreadyRunning = false))
        assertEquals("a measurement is already running",
            Measure.startError(MicSettings.PHONE, capturing = true, alreadyRunning = true))
    }

    // --- measure_cue (the range suite, round7-plan §3d) --------------------------------------------------------------

    @Test fun cueRefusedWithoutARunningSampledSession() {
        assertEquals("no measurement running", Measure.cueError(running = false, sampled = false, text = "RISE", id = "t1"))
        assertEquals("no measurement running", Measure.cueError(running = false, sampled = true, text = "RISE", id = "t1"))
        assertEquals("the measurement has no sample yet (retry)", Measure.cueError(running = true, sampled = false, text = "RISE", id = "t1"))
        assertNull(Measure.cueError(running = true, sampled = true, text = "RISE · slow", id = "contours-rise-01"))
    }

    @Test fun cueNeedsTextAndId() {
        assertEquals("text must be a non-blank string", Measure.cueError(true, true, "  ", "t1"))
        // a malformed cue is refused as such even before the first sample (not with the retryable error)
        assertEquals("id must be a non-blank string", Measure.cueError(true, false, "RISE", ""))
        assertEquals("text is longer than ${Measure.MAX_CUE_CHARS} characters",
            Measure.cueError(true, false, "x".repeat(Measure.MAX_CUE_CHARS + 1), "t1"))
        assertEquals("id must be a non-blank string", Measure.cueError(true, true, "RISE", ""))
        assertNull(Measure.cueError(true, true, "x".repeat(Measure.MAX_CUE_CHARS), "t1"))
        assertEquals("text is longer than ${Measure.MAX_CUE_CHARS} characters",
            Measure.cueError(true, true, "x".repeat(Measure.MAX_CUE_CHARS + 1), "t1"))
    }

    @Test fun promptsAndCuesShareOneNSequenceAlsoWithoutScheduledPrompts() {
        val dir = createTempDir("measure")
        try {
            val s = MeasureSession(7, "range-contours", 5000, Measure.DEFAULT_GESTURES, false, true, false, 1200, 16000, dir)
            assertEquals(listOf(0, 1, 2), List(3) { s.nextPrompt() })
            assertEquals(3, s.promptN)
            assertEquals(3, s.status().getInt("prompts"))
            s.stop(); s.finish()
        } finally { dir.deleteRecursively() }
    }

    // --- WAV header ------------------------------------------------------------------------------------------------

    @Test fun wavHeaderMono() {
        val h = Measure.wavHeader(16000, 1, 640)
        assertEquals("RIFF", ascii(h, 0, 4))
        assertEquals("WAVE", ascii(h, 8, 4))
        assertEquals("fmt ", ascii(h, 12, 4))
        assertEquals("data", ascii(h, 36, 4))
        assertEquals(36 + 640, le32(h, 4))      // RIFF size
        assertEquals(1, le16(h, 20))            // PCM
        assertEquals(1, le16(h, 22))            // channels
        assertEquals(16000, le32(h, 24))        // rate
        assertEquals(16000 * 1 * 2, le32(h, 28)) // byte rate
        assertEquals(1 * 2, le16(h, 32))        // block align
        assertEquals(16, le16(h, 34))           // bits per sample
        assertEquals(640, le32(h, 40))          // data size
        assertEquals(44, h.size)
    }

    @Test fun wavHeaderStereo() {
        val h = Measure.wavHeader(48000, 2, 1280)
        assertEquals(2, le16(h, 22))                    // channels
        assertEquals(48000, le32(h, 24))
        assertEquals(48000 * 2 * 2, le32(h, 28))        // byte rate
        assertEquals(2 * 2, le16(h, 32))               // block align
        assertEquals(1280, le32(h, 40))
        assertEquals(36 + 1280, le32(h, 4))
    }

    @Test fun wavWriterPatchesHeaderOnFinish() {
        val f = File.createTempFile("measure", ".wav"); f.deleteOnExit()
        val w = WavWriter(RandomAccessFile(f, "rw"), 16000, 2)
        // 8 frames of interleaved stereo = 32 bytes
        val buf = ByteBuffer.allocate(32).order(ByteOrder.LITTLE_ENDIAN)
        for (i in 0 until 16) buf.putShort(i.toShort())
        w.write(buf, 32)
        w.finish()
        val b = f.readBytes()
        assertEquals(44 + 32, b.size)
        assertEquals("RIFF", ascii(b, 0, 4))
        assertEquals(2, le16(b, 22))         // the header was patched with the stereo channels
        assertEquals(32, le32(b, 40))        // and the real data size
        // the PCM bytes follow the header untouched
        assertEquals(0, le16(b, 44)); assertEquals(1, le16(b, 46))
    }

    @Test fun wavWriterHeaderPlaceholderIsZeroSized() {
        val h = Measure.wavHeader(16000, 1, 0)
        assertEquals(36, le32(h, 4))
        assertEquals(0, le32(h, 40))
    }

    // --- de-interleave ---------------------------------------------------------------------------------------------

    @Test fun deinterleaveKeepsChannel0() {
        // interleaved L0 R0 L1 R1 L2 R2 ...
        val inter = ShortBuffer.wrap(shortArrayOf(10, 100, 11, 101, 12, 102, 13, 103))
        val dst = ShortBuffer.allocate(4)
        Measure.deinterleaveCh0(inter, dst, 4)
        assertEquals(0, dst.position()); assertEquals(4, dst.limit())
        assertEquals(10.toShort(), dst.get(0)); assertEquals(11.toShort(), dst.get(1))
        assertEquals(12.toShort(), dst.get(2)); assertEquals(13.toShort(), dst.get(3))
    }

    /** The capture's pattern: a direct buffer read into at its base, de-interleaved, then teed. The tee moves the
     *  buffer's position; the fixed views made once must still see every later read (a view made per read from the
     *  moved position was empty and threw on the second stereo read). */
    @Test fun deinterleaveViewsSurviveTheTeeWrite() {
        val f = File.createTempFile("measure", ".wav"); f.deleteOnExit()
        val w = WavWriter(RandomAccessFile(f, "rw"), 16000, 2)
        val buf = ByteBuffer.allocateDirect(16).order(ByteOrder.nativeOrder())
        val src = buf.duplicate().order(ByteOrder.nativeOrder()).asShortBuffer()
        val mono = ByteBuffer.allocateDirect(8).order(ByteOrder.nativeOrder())
        val dst = mono.asShortBuffer()
        for (read in 0 until 3) {
            for (i in 0 until 8) buf.putShort(i * 2, (read * 100 + i).toShort())   // absolute: like AudioRecord.read
            Measure.deinterleaveCh0(src, dst, 4)
            assertEquals((read * 100).toShort(), mono.getShort(0))
            assertEquals((read * 100 + 6).toShort(), mono.getShort(6))
            assertTrue(w.write(buf, 16))
            assertEquals(0, buf.position()); assertEquals(16, buf.limit())
        }
        w.finish()
        assertEquals(44 + 48, f.length())
    }

    // --- sids, the WAV writer's edges, the session tee -------------------------------------------------------------

    @Test fun sidIsUniqueAcrossRestartsAndNeverAnExistingFolder() {
        val dir = createTempDir("measure")
        try {
            assertEquals(1000L, Measure.newSid(1000, 0, dir))
            assertEquals(1001L, Measure.newSid(1000, 1000, dir))        // same ms twice: still increasing
            assertEquals(1000L, Measure.newSid(900, 999, dir))           // the clock stepped back: above the last
            File(dir, "2000").mkdirs(); File(dir, "2001").mkdirs()       // folders from an earlier service run
            assertEquals(2002L, Measure.newSid(2000, 0, dir))
        } finally { dir.deleteRecursively() }
    }

    @Test fun wavWriterTruncatesAnOlderFileAndRefusesAfterFinish() {
        val f = File.createTempFile("measure", ".wav"); f.deleteOnExit()
        f.writeBytes(ByteArray(1000) { 7 })
        val w = WavWriter(RandomAccessFile(f, "rw"), 16000, 1)
        assertTrue(w.write(ByteBuffer.allocateDirect(4), 4))
        w.finish()
        assertFalse(w.write(ByteBuffer.allocateDirect(4), 4))
        assertEquals(48L, f.length())
        assertEquals(4, le32(f.readBytes(), 40))
    }

    private fun session(dir: File, record: Boolean = true, stereo: Boolean = false, onError: (MeasureSession) -> Unit = {}) =
        MeasureSession(42, "p", 5000, Measure.DEFAULT_GESTURES, true, record, stereo, 30, 16000, dir, onWriteError = onError)

    @Test fun teePinsT0AndActualChannelsAndCountsFrames() {
        val dir = createTempDir("measure")
        try {
            var first = 0
            val s = MeasureSession(42, "p", 5000, Measure.DEFAULT_GESTURES, true, true, true, 30, 16000, dir,
                onFirstSample = { first++ })
            val buf = ByteBuffer.allocateDirect(640)
            s.tee.write(buf, 640, 1234, 1)   // stereo asked, the device fell back to mono
            s.tee.write(buf, 640, 1254, 1)
            assertEquals(1, first)
            assertEquals(1234L, s.t0Ms); assertEquals(1234L, s.wavT0Ms)
            assertEquals(1, s.channels)
            assertEquals(640L, s.samples.get())
            s.stop(); s.tee.write(buf, 640, 1274, 1)   // after the stop: nothing written
            s.finish()
            val b = File(dir, "measure/42/audio.wav").readBytes()
            assertEquals(1, le16(b, 22)); assertEquals(1280, le32(b, 40)); assertEquals(44 + 1280, b.size)
        } finally { dir.deleteRecursively() }
    }

    @Test fun teeWriteFailureNeverThrowsAndReportsOnce() {
        val dir = createTempDir("measure")
        try {
            var errors = 0
            val s = session(dir, onError = { errors++ })
            val buf = ByteBuffer.allocateDirect(64)
            s.tee.write(buf, 1_000_000, 0, 1)    // past the buffer: the write throws inside the tee
            s.tee.write(buf, 64, 20, 1)          // the tee stays quiet after a failure
            assertEquals(1, errors)
            assertTrue(s.writeError != null)
            assertEquals(0L, s.samples.get())
            s.finish()
            assertEquals(44L, File(dir, "measure/42/audio.wav").length())
        } finally { dir.deleteRecursively() }
    }

    @Test fun noRecordingOpensNoFileButStillPinsTheClock() {
        val dir = createTempDir("measure")
        try {
            val s = session(dir, record = false)
            s.tee.write(ByteBuffer.allocateDirect(64), 64, 500, 1)
            assertEquals(500L, s.t0Ms); assertNull(s.wavT0Ms)
            assertFalse(File(dir, "measure").exists())
        } finally { dir.deleteRecursively() }
    }

    @Test fun onlyTheSessionsOwnCaptureOrANewerOneEndsIt() {
        // a stereo restart: the session records from gen 5; gen 4's late "stopped" / "error" do not end it
        assertFalse(Measure.captureEndsSession("stopped", 4, 5))
        assertFalse(Measure.captureEndsSession("error", 4, 5))
        assertFalse(Measure.captureEndsSession("listening", 5, 5))
        assertTrue(Measure.captureEndsSession("stopped", 5, 5))
        assertTrue(Measure.captureEndsSession("error", 5, 5))
        assertTrue(Measure.captureEndsSession("listening", 6, 5))   // replaced under it (settings, device)
    }
}
