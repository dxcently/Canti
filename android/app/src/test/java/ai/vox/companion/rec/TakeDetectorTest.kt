package ai.vox.companion.rec

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.PI
import kotlin.math.sin

/** The take silence detector (contract §6), fed synthetic PCM: sine bursts, silence and low noise. */
class TakeDetectorTest {
    private fun sine(rate: Int, freq: Double, n: Int, amp: Double): ShortArray =
        ShortArray(n) { (amp * 32767.0 * sin(2 * PI * freq * it / rate)).toInt().toShort() }

    private fun silence(n: Int) = ShortArray(n)

    private fun noise(rate: Int, n: Int, amp: Double): ShortArray {
        var seed = 42L
        return ShortArray(n) {
            seed = seed * 6364136223846793005L + 1442695040888963407L
            (((seed ushr 33).toDouble() / (1L shl 30)) * amp * 32767.0).toInt().toShort()
        }
    }

    private fun detector(rate: Int, fixed: Boolean = false, background: Boolean = false, targetS: Double = 5.0) =
        TakeDetector(rate, fixed, background, (targetS * rate).toInt(),
            0.05, 0.5, 8.0, 5.0, 1.0, 4.0, 0.5)

    @Test fun silenceEnd() {
        val rate = 16000
        val d = detector(rate)
        d.setFloor(silence(rate))   // 1 s quiet pre-roll: floor ~ -180 dB
        val burst = sine(rate, 200.0, rate / 2, 0.5)      // 0.5 s loud
        val tail = silence(rate * 2)                      // 2 s quiet
        val post = burst + tail
        val ended = d.feed(post, 0, post.size)
        assertTrue(ended)
        assertEquals("silence", d.reason)
        assertEquals(rate / 2 + rate / 2, d.endFrame.toInt())   // last loud tick (0.5 s) + 0.5 s post-roll
        assertFalse(d.noSound)
    }

    @Test fun maxLengthEnd() {
        val rate = 16000
        val d = detector(rate, targetS = 1.0)   // max_s = 1 s
        d.setFloor(silence(rate))
        val post = sine(rate, 200.0, rate * 2, 0.5)   // loud throughout
        assertTrue(d.feed(post, 0, post.size))
        assertEquals("max length", d.reason)
        assertEquals(rate + rate / 2, d.endFrame.toInt())   // max_s (1 s) + 0.5 s post-roll
    }

    @Test fun noSoundAt4s() {
        val rate = 16000
        val d = detector(rate)
        d.setFloor(silence(rate))
        val post = silence(rate * 5)
        assertTrue(d.feed(post, 0, post.size))
        assertEquals("no sound", d.reason)
        assertTrue(d.noSound)
        assertEquals(rate * 4 + rate / 2, d.endFrame.toInt())   // 4 s + post-roll
    }

    @Test fun fixedWindowDoesNotEndOnSilence() {
        val rate = 16000
        val d = detector(rate, fixed = true, targetS = 3.5)   // the quiet room step
        d.setFloor(silence(rate))
        val post = sine(rate, 200.0, rate, 0.5) + silence(rate * 4)   // a transient then quiet: still runs to 3.5 s
        assertTrue(d.feed(post, 0, post.size))
        assertEquals("fixed", d.reason)
        assertEquals((3.5 * rate).toInt() + rate / 2, d.endFrame.toInt())
    }

    @Test fun backgroundIsExactlySeconds() {
        val rate = 16000
        val seconds = 3.0
        val d = detector(rate, background = true, targetS = seconds)
        val post = sine(rate, 200.0, (seconds * rate).toInt(), 0.5)
        assertTrue(d.feed(post, 0, post.size))
        assertEquals("fixed", d.reason)
        assertEquals((seconds * rate).toInt(), d.endFrame.toInt())   // no pre/post-roll
    }

    @Test fun floorIgnoresTheBurstAfterGo() {
        val rate = 16000
        val d = detector(rate)
        d.setFloor(silence(rate))   // floor from the quiet pre-roll
        val post = sine(rate, 200.0, rate / 2, 0.5) + silence(rate * 2)
        d.feed(post, 0, post.size)
        // The post-GO burst opened the detector (floor was not raised by it), then silence ended it.
        assertEquals("silence", d.reason)
    }

    @Test fun lowNoiseFloor() {
        val rate = 16000
        val d = detector(rate)
        val pre = noise(rate, rate, 0.0005)   // low noise pre-roll
        val floor = d.setFloor(pre)
        val post = sine(rate, 200.0, rate / 2, 0.2) + noise(rate, rate * 2, 0.0005)
        d.feed(post, 0, post.size)
        assertTrue(floor > -100.0)   // noise floor is far above digital silence
        assertEquals("silence", d.reason)
    }

    @Test fun fortyEightKilohertz() {
        val rate = 48000
        val d = detector(rate)
        d.setFloor(silence(rate))
        val post = sine(rate, 200.0, rate / 2, 0.5) + silence(rate * 2)
        assertTrue(d.feed(post, 0, post.size))
        assertEquals("silence", d.reason)
        assertEquals(rate / 2 + rate / 2, d.endFrame.toInt())
    }
}
