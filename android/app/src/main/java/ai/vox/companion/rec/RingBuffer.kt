package ai.vox.companion.rec

import java.nio.ByteBuffer

/**
 * The RAM-only mono PCM16 ring the recorder and quick record share (contract §2). One writer (the capture thread,
 * via [MicCapture.MonoTap]) and readers on the main thread, ordered by a lock.
 *
 * [write] copies a read of `frames` mono samples in native order from [buf] (read with absolute `getShort(i*2)`, so
 * the buffer's position is never moved and nothing is allocated per call). [firstFrame] is the stream frame of
 * [buf]'s first sample (the pushed count before the read); [gen] is the capture generation. A new gen, a rate change,
 * or a firstFrame that is not the current [endFrame] resets the ring — two streams are never spliced.
 *
 * [copy] returns the held samples of `[from, to)`, or null when any of that range has already fallen out of the ring.
 * The ring holds [RING_S] seconds at the current capture rate (16 kHz: 192,000 samples = 384 KB; 48 kHz: 1.15 MB).
 * It is never written to disk except by an explicit qr_save / a recorder take.
 */
class RingBuffer {
    private val lock = Any()
    private var rate = 0
    private var samples = ShortArray(0)
    private var capacity = 0
    private var gen = -1
    private var endFrame = 0L
    private var resetStart = 0L   // the first frame of the current (non-spliced) stream

    /** The capture rate of the frames held (0 before the first write). */
    val sampleRate: Int get() = synchronized(lock) { rate }

    /** The capture generation of the frames currently held (resets the ring when it changes). */
    val generation: Int get() = synchronized(lock) { gen }

    /** The stream frame one past the newest held sample. */
    val end: Long get() = synchronized(lock) { endFrame }

    /** The first stream frame still held (`max(resetStart, end - capacity)`); a reset never splices two streams. */
    val start: Long get() = synchronized(lock) { maxOf(resetStart, (endFrame - capacity).coerceAtLeast(0)) }

    /** The held frames `[from, to)` as a fresh ShortArray, or null when not fully held. */
    fun copy(from: Long, to: Long): ShortArray? = synchronized(lock) {
        if (from < start || to > endFrame || from >= to) return null
        val out = ShortArray((to - from).toInt())
        for (i in out.indices) out[i] = samples[((from + i) % capacity).toInt()]
        out
    }

    /** The whole held ring (at most [RING_S] seconds) in one consistent view, or null before the first sample. */
    class Held(val rate: Int, val gen: Int, val startFrame: Long, val samples: ShortArray) {
        val endFrame: Long get() = startFrame + samples.size
    }

    fun held(): Held? = synchronized(lock) {
        val from = start
        if (rate == 0 || endFrame <= from) null else Held(rate, gen, from, copy(from, endFrame)!!)
    }

    fun write(buf: ByteBuffer, frames: Int, firstFrame: Long, rate: Int, gen: Int) {
        synchronized(lock) {
            if (rate != this.rate) {           // a rate change allocates once, never per read
                this.rate = rate
                capacity = rate * RING_S
                this.samples = ShortArray(capacity)
                this.gen = -1
                resetStart = firstFrame
                endFrame = firstFrame
            }
            if (gen != this.gen || firstFrame != endFrame) {   // a restart or a gap: start over, never splice
                this.gen = gen
                resetStart = firstFrame
                endFrame = firstFrame
            }
            for (i in 0 until frames) samples[((firstFrame + i) % capacity).toInt()] = buf.getShort(i * 2)
            endFrame = firstFrame + frames
        }
    }

    companion object {
        /** The ring's length in seconds. */
        const val RING_S = 12
    }
}
