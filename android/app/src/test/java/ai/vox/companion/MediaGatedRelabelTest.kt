package ai.vox.companion

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.random.Random

/**
 * [train] The phone mic's media gate and media-hiss rule deliver a sound as `unknown` on purpose (it still breaks its
 * group, it never acts) and say so with the message's `gated` flag. Personalization must not undo that: a gated sound
 * whose fingerprint matches a trained click stays `unknown`; the same sound ungated is relabelled (PROTOCOL.md "gated").
 */
class MediaGatedRelabelTest {
    private val clickC = doubleArrayOf(-1.0, 0.2, 2.0, -0.4, 1.5, 0.9)
    private val line = "a drum hit; instant sound; loudness loud; sounds like noise"

    private fun matcher(): Matcher {
        val rng = Random(7)
        fun near(c: DoubleArray) = DoubleArray(c.size) { c[it] + (rng.nextDouble() * 2 - 1) * 0.06 }
        return Matcher(EnrollmentStore("default", "phone").apply {
            add("gesture", "click", List(4) { SoundFeatures(near(clickC), "fp1", DoubleArray(0)) })
        }, 1.4)
    }

    private val hit = SoundFeatures(DoubleArray(clickC.size) { clickC[it] + 0.02 }, "fp1", DoubleArray(0))

    /** A phone-mic message as PhoneMicSource.judge hands it on: the gate put `unknown` in `sequence`, and [gated]. */
    private fun message(gated: String?) = FeatureMessage.parse(JSONObject().put("v", 1).put("id", 3).put("mode", "gesture")
        .put("sounds", JSONArray().put(line)).put("sequence", JSONArray().put("unknown"))
        .put("features", JSONArray().put(hit.toJson()))
        .apply { if (gated != null) put("gated", JSONArray().put(gated)) })

    /** The service's personalize for sound i (VoxService.personalize). */
    private fun personalize(m: FeatureMessage, i: Int = 0) =
        Personal.rewrite(matcher().match(m.features!![i]!!), m.sounds[i], m.sequence[i], true, m.features[i]!!.pitch16, m.gated?.getOrNull(i))

    @Test fun mediaGatedUnknownMatchingATrainedClickStaysUnknown() {
        val m = message("media")
        assertEquals(listOf("media"), m.gated)
        assertEquals("gesture", matcher().match(hit).result)   // it does match the trained click...
        val out = personalize(m)
        assertEquals(Personal.Rewritten(line, "unknown", skipped = "gated"), out)   // ...and is left alone
        assertNull(out.relabelFrom)
        // the media-hiss rule's flag, and a custom class, are skipped the same way
        assertEquals("unknown", personalize(message("media_hiss")).label)
        val custom = MatchResult("custom", EnrollClass("custom", "meow"))
        assertEquals(Personal.Rewritten(line, "unknown", skipped = "gated"), Personal.rewrite(custom, line, "unknown", gated = "media"))
    }

    @Test fun theSameSoundUngatedIsRelabelled() {
        val m = message(null)
        assertNull(m.gated)
        val out = personalize(m)
        assertEquals("click", out.label); assertEquals("unknown", out.relabelFrom); assertNull(out.skipped)
    }

    @Test fun gatedIsParsedValidatedAndRoundTrips() {
        val m = message("media")
        assertEquals(listOf("media"), FeatureMessage.parse(m.toJson()).gated)
        val two = JSONObject().put("sounds", JSONArray().put(line).put(line)).put("sequence", JSONArray().put("unknown").put("pop"))
            .put("gated", JSONArray().put("media").put(JSONObject.NULL))
        assertEquals(listOf("media", null), FeatureMessage.parse(two).gated)
        val bad = try { FeatureMessage.parse(JSONObject(two.toString()).put("gated", JSONArray().put("media"))); null }
            catch (e: IllegalArgumentException) { e.message }
        assertTrue(bad, bad!!.contains("gated (1) and sequence (2)"))
    }

    @Test fun everyDeliberateUnknownCarriesTheFlag() {
        // the only place that writes `unknown` into a delivered sequence is the phone mic's gate; it sets `gated` with it
        val src = java.io.File("src/main/java/ai/vox/companion/audio/PhoneMicSource.kt").readText()
        assertEquals(1, Regex("""put\("sequence", JSONArray\(\)\.put\("unknown"\)\)""").findAll(src).count())
        assertTrue(src.contains("""if (gated != null) out.put("gated", JSONArray().put(if (gated == hiss) "media_hiss" else "media"))"""))
        val svc = java.io.File("src/main/java/ai/vox/companion/VoxService.kt").readText()
        assertTrue(svc.contains("f.pitch16, gated)"))
    }
}
