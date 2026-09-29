package ai.vox.companion.rec

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** The RAM ring (contract §2): writes, gap/gen reset, held-range copy. */
class RingBufferTest {
    private fun buf(samples: ShortArray): ByteBuffer {
        val b = ByteBuffer.allocateDirect(samples.size * 2).order(ByteOrder.nativeOrder())
        for (s in samples) b.putShort(s)
        return b
    }

    @Test fun copiesWhatWasWritten() {
        val r = RingBuffer()
        val s = shortArrayOf(1, 2, 3, 4, 5)
        r.write(buf(s), 5, 0, 16000, 0)
        assertEquals(0, r.generation)
        assertEquals(0L, r.start)
        assertEquals(5L, r.end)
        assertArrayEquals(s, r.copy(0, 5))
    }

    @Test fun startReflectsCapacity() {
        val r = RingBuffer()
        // write 13 s at 16 kHz (208000 samples) but only 12 s held (192000)
        val n = 13 * 16000
        r.write(buf(ShortArray(n)), n, 0, 16000, 0)
        assertEquals(16000L, r.start)          // 208000 - 192000
        assertEquals(n.toLong(), r.end)
        assertNull(r.copy(0, 16000))
        assertEquals(192000, r.copy(r.start, r.end)!!.size)
    }

    @Test fun newGenerationResets() {
        val r = RingBuffer()
        r.write(buf(shortArrayOf(1, 2, 3)), 3, 0, 16000, 0)
        r.write(buf(shortArrayOf(9)), 1, 100, 16000, 1)   // new gen, non-contiguous firstFrame
        assertEquals(1, r.generation)
        assertEquals(100L, r.start)
        assertEquals(101L, r.end)
        assertArrayEquals(shortArrayOf(9), r.copy(100, 101))
    }

    @Test fun gapResetsWithoutSplicing() {
        val r = RingBuffer()
        r.write(buf(shortArrayOf(1, 2)), 2, 0, 16000, 0)
        r.write(buf(shortArrayOf(3, 4)), 2, 10, 16000, 0)   // gap: 2 -> 10, same gen
        assertEquals(10L, r.start)
        assertEquals(12L, r.end)
        assertArrayEquals(shortArrayOf(3, 4), r.copy(10, 12))
    }

    @Test fun copyOutOfRangeIsNull() {
        val r = RingBuffer()
        r.write(buf(shortArrayOf(1, 2, 3)), 3, 0, 16000, 0)
        assertNull(r.copy(1, 4))   // to > end
        assertNull(r.copy(3, 3))   // empty
    }

    @Test fun heldIsNullBeforeFirstWrite() {
        val r = RingBuffer()
        assertNull(r.held())
    }
}
