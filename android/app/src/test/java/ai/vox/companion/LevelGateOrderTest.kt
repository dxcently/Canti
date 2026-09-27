package ai.vox.companion

import ai.vox.companion.joystick.CalibV2
import ai.vox.companion.joystick.GateDrop
import ai.vox.companion.joystick.JoySpec
import ai.vox.companion.joystick.LevelGate
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.random.Random

/**
 * Calibration v2's level gate runs before personalization: PhoneMicSource.judge decides (CalibV2.phoneVerdict) and
 * hands the service only a deliverable sound; the service's personalize (Personal.rewrite's trained-gesture relabel)
 * sees delivered messages only. So a quiet sound under the gate is ignored even when its fingerprint matches a trained
 * gesture that would otherwise relabel it (a keyboard tap the extractor called `unknown`, turned into the user's click).
 */
class LevelGateOrderTest {
    private val spec = JoySpec.parse(java.io.File("src/main/assets/joystick_v1.json").readText())
    private val clickC = doubleArrayOf(-1.0, 0.2, 2.0, -0.4, 1.5, 0.9)
    private val tapLine = "background noise"

    private fun store(): EnrollmentStore {
        val rng = Random(5)
        fun near(c: DoubleArray) = DoubleArray(c.size) { c[it] + (rng.nextDouble() * 2 - 1) * 0.06 }
        return EnrollmentStore("default", "phone").apply {
            add("gesture", "click", List(4) { SoundFeatures(near(clickC), "fp1", DoubleArray(0)) })
        }
    }

    private fun gate(snr: Double, level: Double) = JSONObject().put("snr_db", snr).put("level_db", level).put("dur_ms", 20.0)

    /** The mic -> service path in order: the verdict, then (only if delivered) the service's personalization. */
    private fun pipeline(label: String, g: JSONObject, lg: LevelGate?, m: Matcher, f: SoundFeatures): Pair<GateDrop?, Personal.Rewritten?> {
        val v = CalibV2.phoneVerdict(label, g, lg, null, on = true)
        if (!v.deliverable) return v.drop to null
        return null to Personal.rewrite(m.match(f), tapLine, v.label, gestureRelabel = true, pitch16 = f.pitch16)
    }

    @Test fun belowGateSoundMatchingATrainedClassIsStillIgnored() {
        val m = Matcher(store(), 1.4)
        val tap = SoundFeatures(DoubleArray(clickC.size) { clickC[it] + 0.02 }, "fp1", DoubleArray(0))
        // the risk: delivered, the matcher and Personal.rewrite turn this `unknown` into the trained click
        val r = m.match(tap)
        assertEquals("gesture", r.result); assertEquals("click", r.cls!!.name)
        val relabelled = Personal.rewrite(r, tapLine, "unknown", gestureRelabel = true)
        assertEquals("click", relabelled.label); assertEquals("unknown", relabelled.relabelFrom)

        // quiet (8 dB over the floor, -55 dBFS): under the uncalibrated default gate and under a calibrated one
        for (lg in listOf(CalibV2.defaultGate(spec), LevelGate(16.0, -40.0, "calibration", 7, 24.0, -32.0))) {
            val (drop, personal) = pipeline("unknown", gate(8.0, -55.0), lg, m, tap)
            assertNull("never reaches the matcher", personal)
            assertNotNull(drop)
            assertEquals("below level gate", drop!!.reason)
            assertEquals("unknown", drop.label)
            assertEquals(lg.from, drop.from)
            assertEquals("below level gate", drop.fields().toMap()["reason"])
        }
        // the same for a quiet sound the extractor already called a click (the gate's own labels)
        assertNull(pipeline("click", gate(8.0, -55.0), CalibV2.defaultGate(spec), m, tap).second)

        // loud enough: delivered, and then personalization is free to relabel it (the other agent's feature)
        val (none, loud) = pipeline("unknown", gate(30.0, -25.0), CalibV2.defaultGate(spec), m, tap)
        assertNull(none); assertEquals("click", loud!!.label)
    }

    @Test fun phoneVerdictScope() {
        val d = CalibV2.defaultGate(spec)
        val quiet = gate(5.0, -60.0)
        // phone / USB: pop, click, hiss and unknown are gated; hums (the voice) are not
        for (l in listOf("pop", "click", "hiss", "unknown")) assertFalse(l, CalibV2.phoneVerdict(l, quiet, d, null).deliverable)
        for (l in listOf("flat", "rise", "fall", "arch", "dip")) assertTrue(l, CalibV2.phoneVerdict(l, quiet, d, null).deliverable)
        // the prototype's gate (gate_reason's default labels, the parity golden) stays pop / click / hiss
        assertNull(CalibV2.gateReason(d, "unknown", 5.0, -60.0))
        // no gate (the Pico, or a calibration running), the setting off, ticks and touch-dropped sounds: no level verdict
        assertTrue(CalibV2.phoneVerdict("unknown", quiet, null, null).deliverable)
        assertTrue(CalibV2.phoneVerdict("unknown", quiet, d, null, on = false).deliverable)
        assertTrue(CalibV2.phoneVerdict("unknown", quiet, d, null, tick = true).deliverable)
        assertNull(CalibV2.phoneVerdict("unknown", quiet, d, null, touched = true).drop)
        // the offset: +10 makes a sound that passed at 0 fail
        assertTrue(CalibV2.phoneVerdict("pop", gate(20.0, -40.0), d, null).deliverable)
        assertFalse(CalibV2.phoneVerdict("pop", gate(20.0, -40.0), d, null, offsetDb = 10.0).deliverable)
        // no gate numbers (an old native build): passes
        assertTrue(CalibV2.phoneVerdict("pop", null, d, null).deliverable)
    }
}
