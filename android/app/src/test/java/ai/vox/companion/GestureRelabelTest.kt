package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.random.Random

/** [train] A match to a trained gesture class relabels the sound (PROTOCOL.md "Personalization", `enroll_gesture_relabel`). */
class GestureRelabelTest {
    private val dipLine = "hum that ${Vocab.CONTOURS["dip"]}; pitch change medium (2-4 semitones); duration medium (400-1000 ms); tone breathy; loudness quiet; sounds like whistle"
    private val clickLine = "a tongue click; instant sound; loudness loud; sounds like mouth sound"
    private val arch = { k: Double -> DoubleArray(16) { 4.0 * k * kotlin.math.sin(Math.PI * it / 15) } }
    private val archC = doubleArrayOf(0.4, 0.8, -0.2, 1.1, 0.0, 0.3)
    private val popC = doubleArrayOf(-1.0, 0.2, 2.0, -0.4, 1.5, 0.9)

    /** The user's arch (n takes) and pop (4 takes) on the phone mic. */
    private fun store(archTakes: Int = 5): EnrollmentStore {
        val rng = Random(11)
        fun near(c: DoubleArray) = DoubleArray(c.size) { c[it] + (rng.nextDouble() * 2 - 1) * 0.06 }
        return EnrollmentStore("default", "phone").apply {
            add("gesture", "arch", List(archTakes) { i -> SoundFeatures(near(archC), "fp1", arch(1.0 + 0.05 * i)) })
            add("gesture", "pop", List(4) { SoundFeatures(near(popC), "fp1", DoubleArray(0)) })
        }
    }

    @Test fun trainedArchRelabelsAnExtractorDip() {
        val m = Matcher(store(), 1.4)
        val f = SoundFeatures(DoubleArray(archC.size) { archC[it] + 0.02 }, "fp1", arch(1.1))
        val r = m.match(f)
        assertEquals("gesture", r.result); assertEquals("arch", r.cls!!.name)
        assertTrue(r.distance!! <= r.threshold!! && r.dtw!! <= r.dtwThreshold!!)
        val out = Personal.rewrite(r, dipLine, "dip", gestureRelabel = true, pitch16 = f.pitch16)
        assertEquals("arch", out.label); assertEquals("dip", out.relabelFrom)
        // the arch's normal line, keeping what the extractor measured
        assertEquals("hum that rises then falls; pitch change medium (2-4 semitones); duration medium (400-1000 ms); tone breathy; " +
            "loudness quiet; sounds like whistle", out.sound)
        // agreeing labels: the line stays, trusted
        val same = Personal.rewrite(r, dipLine.replace(Vocab.CONTOURS.getValue("dip"), Vocab.CONTOURS.getValue("arch")), "arch", true, f.pitch16)
        assertEquals("arch", same.label); assertTrue(same.trusted); assertNull(same.relabelFrom)
        // a discrete class: an extractor click that is the user's pop
        val p = m.match(SoundFeatures(popC.copyOf(), "fp1", DoubleArray(0)))
        val pop = Personal.rewrite(p, clickLine, "click")
        assertEquals(Personal.Rewritten("a short lip pop; instant sound; loudness loud; sounds like mouth sound", "pop", relabelFrom = "click"), pop)
    }

    @Test fun noRelabelBeyondTheThreshold() {
        val m = Matcher(store(), 1.4)
        // far from every class in fp
        val far = m.match(SoundFeatures(DoubleArray(archC.size) { archC[it] + 3.0 }, "fp1", arch(1.0)))
        assertEquals("none", far.result)
        assertEquals(Personal.Rewritten(dipLine, "dip"), Personal.rewrite(far, dipLine, "dip"))
        // close in fp but the pitch track is a dip: the DTW test rejects it
        val dipTrack = m.match(SoundFeatures(archC.copyOf(), "fp1", arch(-1.0)))
        assertEquals("none", dipTrack.result); assertTrue(dipTrack.reason, dipTrack.reason.contains("DTW"))
        assertEquals(Personal.Rewritten(dipLine, "dip"), Personal.rewrite(dipTrack, dipLine, "dip"))
    }

    @Test fun noRelabelFromAClassUnderThreeExamples() {
        val s = store(archTakes = 2)
        val m = Matcher(s, 1.4)
        assertTrue("arch" !in m.thresholds())
        val r = m.match(SoundFeatures(archC.copyOf(), "fp1", arch(1.0)))
        assertTrue(r.result != "gesture" || r.cls!!.name != "arch")
        assertEquals("dip", Personal.rewrite(r, dipLine, "dip", true, arch(1.0)).label)
    }

    @Test fun flagOffKeepsTheExtractorLine() {
        val m = Matcher(store(), 1.4)
        val f = SoundFeatures(archC.copyOf(), "fp1", arch(1.0))
        val r = m.match(f)
        assertEquals("gesture", r.result)
        assertEquals(Personal.Rewritten(dipLine, "dip"), Personal.rewrite(r, dipLine, "dip", gestureRelabel = false, pitch16 = f.pitch16))
    }

    @Test fun gestureLineFormats() {
        assertEquals("a hiss; duration short (150-400 ms); loudness normal; sounds like hum",
            Personal.gestureLine("hiss", "hum that stays level; pitch change small (under 2 semitones); duration short (150-400 ms); tone clear tone; loudness normal; sounds like hum"))
        // flat always says small; a line without a pitch change takes the pitch track's range
        assertTrue(Personal.gestureLine("flat", dipLine).contains("stays level; pitch change small (under 2 semitones)"))
        assertTrue(Personal.gestureLine("rise", clickLine, DoubleArray(16) { it * 0.5 }).startsWith(
            "hum that rises from low to high; pitch change large (over 4 semitones); duration very short (under 150 ms); tone clear tone; loudness loud"))
    }

    @Test fun settingDefaultsOnAndIsAConfigKey() {
        val src = java.io.File("src/main/java/ai/vox/companion/Settings.kt").readText()
        assertTrue(src.contains("getBoolean(\"enroll_gesture_relabel\", true)"))
        assertTrue(src.contains("\"enroll_gesture_relabel\" -> enrollGestureRelabel"))
    }
}
