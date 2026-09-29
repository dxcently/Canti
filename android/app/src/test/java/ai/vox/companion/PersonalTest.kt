package ai.vox.companion

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import kotlin.random.Random

/** Personalization: fingerprint parsing, the enrollment store, the matcher, the line rewrite and the local gate. */
class PersonalTest {
    private val eps = 1e-9
    private val hum = "hum that ${Vocab.CONTOURS["rise"]}; pitch change large (over 4 semitones); duration short (150-400 ms); tone clear tone; loudness loud; sounds like hum"
    private val pop = "a short lip pop; instant sound; loudness normal; sounds like mouth sound"

    private fun feat(vararg fp: Double, ver: String = "fp1", pitch: DoubleArray = DoubleArray(0)) = SoundFeatures(fp, ver, pitch)
    private fun expectFail(what: String, block: () -> Unit) {
        try { block(); fail("expected a rejection: $what") } catch (_: IllegalArgumentException) {}
    }
    private fun assertThrowsMsg(part: String, block: () -> Unit) {
        try { block(); fail("expected IllegalArgumentException containing '$part'") } catch (e: IllegalArgumentException) {
            assertTrue("'${e.message}' should contain '$part'", e.message!!.contains(part))
        }
    }

    /** Clusters: each class = centre + small noise, dimension 6. */
    private fun cluster(rng: Random, centre: DoubleArray, n: Int, noise: Double = 0.05) =
        List(n) { SoundFeatures(DoubleArray(centre.size) { centre[it] + (rng.nextDouble() * 2 - 1) * noise }, "fp1", DoubleArray(0)) }

    private val meowC = doubleArrayOf(1.0, 0.0, 0.0, 2.0, 0.5, 0.0)
    private val sneezeC = doubleArrayOf(0.0, 1.0, 1.0, 0.0, -0.5, 3.0)

    private fun store(): EnrollmentStore {
        val rng = Random(7)
        return EnrollmentStore("default").apply {
            add("custom", "meow", cluster(rng, meowC, 5))
            add("ignore", "sneeze", cluster(rng, sneezeC, 3))
        }
    }

    // --- maths --------------------------------------------------------------------------------------------------------

    @Test fun standardisation() {
        val (mean, std) = Personal.standardizer(listOf(doubleArrayOf(1.0, 10.0, 5.0), doubleArrayOf(3.0, 10.0, 7.0)))
        assertEquals(listOf(2.0, 10.0, 6.0), mean.toList())
        assertEquals(listOf(1.0, 1.0, 1.0), std.toList())   // the constant feature gets std 1
        assertEquals(listOf(2.0, 1.0, 0.0), Personal.standardize(doubleArrayOf(4.0, 11.0, 6.0), mean, std).toList())
        val (m2, s2) = Personal.standardizer(listOf(doubleArrayOf(0.0), doubleArrayOf(4.0), doubleArrayOf(8.0)))
        assertEquals(4.0, m2[0], eps); assertEquals(Math.sqrt(32.0 / 3), s2[0], eps)   // population std
        assertEquals(5.0, Personal.euclid(doubleArrayOf(0.0, 0.0), doubleArrayOf(3.0, 4.0)), eps)
    }

    @Test fun bandedDtw() {
        val a = DoubleArray(16) { it.toDouble() }
        assertEquals(0.0, Personal.dtw(a, a), eps)
        val lag1 = DoubleArray(16) { maxOf(0, it - 1).toDouble() }   // the same rise, one point late
        assertEquals(1.0, Personal.dtw(a, lag1), eps)                // warps away except the final point
        assertEquals(15.0, (0 until 16).sumOf { Math.abs(a[it] - lag1[it]) }, eps)   // vs 15 point by point
        // A step 5 points late cannot be absorbed within a band of 3; an unconstrained DTW absorbs it completely.
        val s1 = DoubleArray(16) { if (it < 8) 0.0 else 10.0 }
        val s2 = DoubleArray(16) { if (it < 13) 0.0 else 10.0 }
        assertEquals(0.0, Personal.dtw(s1, s2, band = 16), eps)
        assertEquals(20.0, Personal.dtw(s1, s2, band = 3), eps)
        val fall = DoubleArray(16) { -it.toDouble() }
        assertTrue(Personal.dtw(a, fall) > 100)
    }

    @Test fun rejectThresholdAndLeaveOneOut() {
        val d = { x: Double, y: Double -> Math.abs(x - y) }
        // Leave-one-out for every size: max over examples of the distance to the nearest other one (not the pairwise max)
        assertEquals(2.0, Personal.withinClass(listOf(0.0, 1.0, 3.0), d), eps)            // pairwise max would be 3
        assertEquals(4.0, Personal.withinClass(listOf(0.0, 1.0, 3.0, 7.0), d), eps)       // nearest: 1, 1, 2, 4 (pairwise 7)
        assertEquals(1.0, Personal.withinClass(List(10) { it.toDouble() }, d), eps)       // 10 evenly spaced: 1 (pairwise 9)
        assertEquals(5.0, Personal.withinClass(listOf(2.0, 7.0), d), eps)                 // 2: the one pair
        expectFail("one example") { Personal.withinClass(listOf(1.0), d) }

        val s = store()
        val m = Matcher(s, 1.4)
        val z = { c: String -> s.find(c)!!.examples.map { Personal.standardize(it.fp, m.mean, m.std) } }
        val th = m.thresholds()
        assertEquals(Personal.withinClass(z("meow"), Personal::euclid) * 1.4, th.getValue("meow").first, eps)
        assertEquals(Personal.withinClass(z("sneeze"), Personal::euclid) * 1.4, th.getValue("sneeze").first, eps)
        // Both classes (5 and 3 examples) use the leave-one-out distance, strictly below their pairwise max here.
        for (c in listOf("meow", "sneeze")) {
            val zs = z(c)
            val pairMax = zs.indices.maxOf { i -> zs.indices.filter { it != i }.maxOf { j -> Personal.euclid(zs[i], zs[j]) } }
            assertTrue(c, th.getValue(c).first < pairMax * 1.4)
        }
        assertNull(th.getValue("meow").second)   // not a contour class: no DTW threshold
        // the multiplier scales linearly
        assertEquals(th.getValue("meow").first / 1.4 * 2.0, Matcher(s, 2.0).thresholds().getValue("meow").first, eps)
    }

    @Test fun nearestNeighbourWithReject() {
        val s = store()
        val m = Matcher(s, 1.4)
        val near = m.match(SoundFeatures(meowC.copyOf().also { it[0] += 0.01 }, "fp1", DoubleArray(0)))
        assertEquals("custom", near.result); assertEquals("meow", near.cls!!.name)
        assertTrue(near.distance!! <= near.threshold!!)
        val sn = m.match(SoundFeatures(sneezeC.copyOf().also { it[5] -= 0.01 }, "fp1", DoubleArray(0)))
        assertEquals("ignore", sn.result); assertEquals("sneeze", sn.cls!!.name)
        // Far from both: the nearest class is reported, with a distance above its threshold.
        val far = m.match(feat(-3.0, 4.0, -2.0, 5.0, 3.0, -4.0))
        assertEquals("none", far.result); assertNull(far.cls)
        assertTrue(far.nearest != null && far.distance!! > far.threshold!!)
        // Halfway between the clusters: nearest is one of them, but outside both thresholds.
        val mid = m.match(SoundFeatures(DoubleArray(6) { (meowC[it] + sneezeC[it]) / 2 }, "fp1", DoubleArray(0)))
        assertEquals("none", mid.result)
        // Version / length mismatches never match; they are skipped with a reason.
        val v = m.match(SoundFeatures(meowC, "fp2", DoubleArray(0)))
        assertEquals("skipped", v.result); assertTrue(v.reason, v.reason.contains("fp_version 'fp2'"))
        val l = m.match(feat(1.0, 0.0, 0.0))
        assertEquals("skipped", l.result); assertTrue(l.reason, l.reason.contains("3 values"))
        // A class with fewer than 3 examples is stored but does not match.
        val small = EnrollmentStore("p").apply { add("custom", "kiss", cluster(Random(1), meowC, 2)) }
        assertFalse(small.find("kiss")!!.active)
        assertEquals("skipped", Matcher(small, 1.4).match(SoundFeatures(meowC, "fp1", DoubleArray(0))).result)
    }

    private fun floors(ver: String, floor: DoubleArray, provisional: Boolean = true) =
        FpFloors(mapOf(ver to FpFloors.Entry(floor, provisional, "test")))

    /**
     * Store-wide standardisation alone: a feature nearly constant across every enrolled example gets a std equal to
     * its noise, so that noise weighs as much as a separating feature and inflates every class's threshold; the
     * midpoint between two classes is then accepted. The per-feature floor fixes it: the midpoint is rejected, and
     * the classes' own sounds still match. (Deterministic data: feature 0 separates the classes, features 1-3 are
     * 0.5 +- 0.01 everywhere. The earlier random-noise version of this case is already rejected by leave-one-out.)
     */
    @Test fun nearConstantFeatureIsFloored() {
        val ex = { f0: Double, signs: String -> SoundFeatures(DoubleArray(4) { if (it == 0) f0 else 0.5 + (if (signs[it - 1] == '+') 0.01 else -0.01) }, "fp1", DoubleArray(0)) }
        val s = EnrollmentStore("p").apply {
            add("custom", "a", listOf("++-", "-++", "+-+", "---", "+++").map { ex(0.0, it) })
            add("ignore", "b", listOf("-+-", "+--", "--+").map { ex(1.0, it) })
        }
        val q = { f0: Double -> SoundFeatures(doubleArrayOf(f0, 0.5, 0.5, 0.5), "fp1", DoubleArray(0)) }
        // Without a floor (no table entry): the noise features are z = +-1 and set the thresholds; the midpoint passes.
        val bare = Matcher(s, 1.4)
        assertEquals("none", bare.floorStatus)
        assertTrue(bare.std[1] < 0.011)
        val bm = bare.match(q(0.5))
        assertEquals("custom", bm.result)
        // With a floor of 0.25 per feature: features 1-3 are divided by 0.25, feature 0 keeps its own std (0.48).
        val m = Matcher(s, 1.4, floors("fp1", DoubleArray(4) { 0.25 }))
        assertEquals("provisional", m.floorStatus)
        assertEquals(0.25, m.std[1], eps)
        assertEquals(bare.std[0], m.std[0], eps)
        val r = m.match(q(0.5))
        assertEquals("none", r.result)
        assertTrue(r.distance!! > r.threshold!!)
        assertTrue(m.thresholds().getValue("a").first < bare.thresholds().getValue("a").first / 10)
        assertEquals("custom", m.match(q(0.02)).result)
        assertEquals("ignore", m.match(q(0.98)).result)
        // The random-noise data of the first version (feature 4 equal in both classes): rejected with the floor too.
        val rng = Random(7)
        val a6 = doubleArrayOf(1.0, 0.0, 0.0, 2.0, 0.5, 0.0); val b6 = doubleArrayOf(0.0, 1.0, 1.0, 0.0, 0.5, 3.0)
        val s6 = EnrollmentStore("p").apply { add("custom", "a", cluster(rng, a6, 5)); add("ignore", "b", cluster(rng, b6, 3)) }
        val mid6 = SoundFeatures(DoubleArray(6) { (a6[it] + b6[it]) / 2 }, "fp1", DoubleArray(0))
        assertEquals("none", Matcher(s6, 1.4, floors("fp1", DoubleArray(6) { 0.25 })).match(mid6).result)
    }

    @Test fun floorTableByVersion() {
        // standardizer: std = max(std, floor); a floor of 0 keeps the old "constant -> 1" rule.
        val xs = listOf(doubleArrayOf(0.0, 5.0, 1.0), doubleArrayOf(2.0, 5.0, 1.02))
        val (_, std) = Personal.standardizer(xs, doubleArrayOf(0.5, 0.0, 0.1))
        assertEquals(1.0, std[0], eps); assertEquals(1.0, std[1], eps); assertEquals(0.1, std[2], eps)
        expectFail("floor length") { Personal.standardizer(xs, doubleArrayOf(1.0)) }

        val rng = Random(5)
        val s = EnrollmentStore("p").apply { add("custom", "a", cluster(rng, meowC, 3)) }
        assertEquals("none", Matcher(s, 1.4, floors("fp2", DoubleArray(6) { 1.0 })).floorStatus)       // other version only
        val mis = Matcher(s, 1.4, floors("fp1", DoubleArray(5) { 1.0 }))
        assertEquals("mismatch", mis.floorStatus); assertNull(mis.floor)
        assertEquals(Matcher(s, 1.4).std.toList(), mis.std.toList())                                   // not applied
        assertEquals("final", Matcher(s, 1.4, floors("fp1", DoubleArray(6) { 1.0 }, provisional = false)).floorStatus)
        assertEquals("empty", Matcher(EnrollmentStore("q"), 1.4, floors("fp1", DoubleArray(6))).floorStatus)

        // JSON: validated, provisional unless marked otherwise, overrides replace per version.
        val t = FpFloors.parse(JSONObject("""{"fp1": {"floor": [0.1, 0.2]}, "fp2": {"floor": [1], "provisional": false, "source": "x"}}"""))
        assertTrue(t["fp1"]!!.provisional); assertFalse(t["fp2"]!!.provisional); assertNull(t["fp3"]); assertNull(t[null])
        val o = t.overriddenBy(FpFloors.parse(JSONObject("""{"fp1": {"floor": [0.3, 0.4], "provisional": false}}""")))
        assertEquals(listOf(0.3, 0.4), o["fp1"]!!.floor.toList()); assertEquals("x", o["fp2"]!!.source)
        assertEquals(t["fp1"]!!.floor.toList(), FpFloors.parse(t.toJson())["fp1"]!!.floor.toList())
        assertThrowsMsg("fp1.floor[1]") { FpFloors.parse(JSONObject("""{"fp1": {"floor": [0.1, -1]}}""")) }
        assertThrowsMsg("fp1.floor missing") { FpFloors.parse(JSONObject("""{"fp1": {}}""")) }
        assertThrowsMsg("fp1.names") { FpFloors.parse(JSONObject("""{"fp1": {"floor": [1, 2], "names": ["x"]}}""")) }
        expectFail("not an object") { FpFloors.parse(JSONObject("""{"fp1": [1]}""")) }
    }

    /** The table shipped in the APK: fp1, 24 floors (one per FINGERPRINT.md feature), marked provisional. */
    @Test fun shippedFloorTable() {
        val t = FpFloors.parse(JSONObject(java.io.File("src/main/assets/fp_floors.json").readText()))
        val e = t["fp1"]!!
        assertEquals(24, e.floor.size)
        assertTrue(e.floor.all { it > 0 })
        assertTrue("replace with the extractor's scales, then mark it final", e.provisional)
    }

    @Test fun contourClassAlsoNeedsTheDtwMatch() {
        val rng = Random(3)
        val rise = { k: Double -> DoubleArray(16) { it * 0.4 * k } }
        val s = EnrollmentStore("p")
        val base = doubleArrayOf(0.5, 0.5, 0.5, 0.5)
        s.add("gesture", "rise", List(4) { i ->
            SoundFeatures(DoubleArray(4) { base[it] + rng.nextDouble() * 0.1 }, "fp1", rise(1.0 + 0.1 * i))
        })
        s.add("custom", "meow", List(4) { SoundFeatures(DoubleArray(4) { 2.0 + rng.nextDouble() * 0.1 }, "fp1", DoubleArray(0)) })
        val m = Matcher(s, 1.4)
        assertTrue(s.find("rise")!!.contour); assertFalse(s.find("meow")!!.contour)
        assertTrue(m.thresholds().getValue("rise").second!! > 0)
        val q = DoubleArray(4) { base[it] + 0.05 }
        val ok = m.match(SoundFeatures(q, "fp1", rise(1.12)))
        assertEquals("gesture", ok.result); assertTrue(ok.dtw!! <= ok.dtwThreshold!!)
        val wrongTrack = m.match(SoundFeatures(q, "fp1", DoubleArray(16) { -it * 0.4 }))
        assertEquals("none", wrongTrack.result); assertEquals("rise", wrongTrack.nearest)
        assertTrue(wrongTrack.reason, wrongTrack.reason.contains("DTW"))
        // Without a pitch track a contour class is not a candidate: the next nearest class is judged instead.
        val unpitched = m.match(SoundFeatures(q, "fp1", DoubleArray(0)))
        assertEquals("meow", unpitched.nearest); assertEquals("none", unpitched.result)
    }

    // --- store -----------------------------------------------------------------------------------------------------------

    @Test fun enrollmentStoreRulesAndJson() {
        val s = store()
        assertEquals("fp1", s.fpVersion); assertEquals(6, s.dim)
        assertThrowsMsg("fp_version") { s.add("custom", "meow", listOf(SoundFeatures(meowC, "fp2", DoubleArray(0)))) }
        assertThrowsMsg("fp has 3 values") { s.add("custom", "meow", listOf(feat(1.0, 2.0, 3.0))) }
        assertThrowsMsg("already a custom class") { s.add("ignore", "meow", listOf(SoundFeatures(meowC, "fp1", DoubleArray(0)))) }
        assertThrowsMsg("at most 10") { s.add("custom", "meow", cluster(Random(2), meowC, 6)) }
        assertEquals(5, s.find("meow")!!.examples.size)   // all-or-nothing: nothing was added by the failed calls
        assertThrowsMsg("kind") { s.add("dog", "woof", listOf(SoundFeatures(meowC, "fp1", DoubleArray(0)))) }
        assertThrowsMsg("name") { s.add("custom", "say \"hi\"", listOf(SoundFeatures(meowC, "fp1", DoubleArray(0)))) }
        assertThrowsMsg("named after a gesture") { s.add("gesture", "meow2", listOf(SoundFeatures(meowC, "fp1", DoubleArray(0)))) }
        assertThrowsMsg("pitch16") { s.add("gesture", "fall", listOf(SoundFeatures(meowC, "fp1", DoubleArray(0)))) }
        s.add("gesture", "pop", listOf(SoundFeatures(meowC, "fp1", DoubleArray(0))))   // discrete gestures need no pitch track
        s.add("custom", " Trill ", listOf(SoundFeatures(meowC, "fp1", DoubleArray(0))))
        assertTrue(s.find("trill") != null)   // names are trimmed and lower-cased

        val back = EnrollmentStore.fromJson(JSONObject(s.toJson().toString()))
        assertEquals(s.toJson().toString(), back.toJson().toString())
        assertEquals(listOf("meow", "sneeze", "pop", "trill"), back.classes.map { it.name })

        assertTrue(s.delete("meow", 0)); assertEquals(4, s.find("meow")!!.examples.size)
        assertFalse(s.delete("meow", 9)); assertFalse(s.delete("nothing"))
        assertTrue(s.delete("meow")); assertNull(s.find("meow"))
        s.clear(); assertNull(s.fpVersion); assertNull(s.dim)
        s.add("custom", "meow", listOf(feat(1.0, 2.0, ver = "fp9")))   // an empty store takes a new version and length
        assertEquals("fp9", s.fpVersion); assertEquals(2, s.dim)
    }

    // --- message --------------------------------------------------------------------------------------------------------

    private fun msg(features: Any?): JSONObject = JSONObject().put("v", 1).put("sounds", JSONArray(listOf(hum, pop)))
        .put("sequence", JSONArray(listOf("rise", "pop"))).also { if (features != null) it.put("features", features) }

    @Test fun featureFieldsParseAndValidate() {
        val f0 = JSONObject().put("fp", JSONArray(listOf(1, 2.5, -3))).put("fp_version", "fp1").put("pitch16", JSONArray(List(16) { it * 0.5 }))
        val m = FeatureMessage.parse(msg(JSONArray().put(f0).put(JSONObject.NULL)))
        assertEquals(listOf(1.0, 2.5, -3.0), m.features!![0]!!.fp.toList())
        assertEquals("fp1", m.features!![0]!!.fpVersion); assertTrue(m.features!![0]!!.pitched)
        assertNull(m.features!![1])
        assertNull(FeatureMessage.parse(msg(null)).features)   // optional
        val unpitched = JSONObject().put("fp", JSONArray(listOf(1))).put("fp_version", "fp1").put("pitch16", JSONArray())
        assertFalse(FeatureMessage.parse(msg(JSONArray().put(unpitched).put(JSONObject.NULL))).features!![0]!!.pitched)
        // round trip through toJson
        assertEquals(m.features!![0]!!.fp.toList(), FeatureMessage.parse(m.toJson()).features!![0]!!.fp.toList())

        assertThrowsMsg("features (1) and sequence (2)") { FeatureMessage.parse(msg(JSONArray().put(f0))) }
        assertThrowsMsg("pitch16 must have 0 or 16") {
            FeatureMessage.parse(msg(JSONArray().put(JSONObject(f0.toString()).put("pitch16", JSONArray(listOf(1, 2, 3, 4, 5)))).put(JSONObject.NULL)))
        }
        assertThrowsMsg("fp_version missing") {
            FeatureMessage.parse(msg(JSONArray().put(JSONObject().put("fp", JSONArray(listOf(1)))).put(JSONObject.NULL)))
        }
        assertThrowsMsg("features[0].fp[1] is not a number") {
            FeatureMessage.parse(msg(JSONArray().put(JSONObject(f0.toString()).put("fp", JSONArray(listOf(1, "x")))).put(JSONObject.NULL)))
        }
        assertThrowsMsg("fp must have") {
            FeatureMessage.parse(msg(JSONArray().put(JSONObject(f0.toString()).put("fp", JSONArray())).put(JSONObject.NULL)))
        }
    }

    // --- line rewrite ---------------------------------------------------------------------------------------------------

    @Test fun lineRewriteFormat() {
        assertEquals("my sound \"meow\"; duration short (150-400 ms); loudness loud", Personal.customLine("meow", hum))
        // pop/click lines have no duration field: the shortest bucket
        assertEquals("my sound \"kiss\"; duration very short (under 150 ms); loudness normal", Personal.customLine("kiss", pop))
        assertNull(Personal.customLine("x", "something odd; loudness loud"))
        assertEquals(hum.replace("sounds like hum", "sounds like one of my ignore sounds"), Personal.ignoreLine(hum))
        assertEquals("a hiss; duration long (over 1 s); loudness quiet; sounds like one of my ignore sounds",
            Personal.ignoreLine("a hiss; duration long (over 1 s); loudness quiet; sounds like background noise"))

        val s = store(); val m = Matcher(s, 1.4)
        val custom = m.match(SoundFeatures(meowC, "fp1", DoubleArray(0)))
        assertEquals(Personal.Rewritten("my sound \"meow\"; duration short (150-400 ms); loudness loud", "my:meow"), Personal.rewrite(custom, hum, "rise"))
        val ign = m.match(SoundFeatures(sneezeC, "fp1", DoubleArray(0)))
        assertEquals(Personal.Rewritten(Personal.ignoreLine(hum), "rise"), Personal.rewrite(ign, hum, "rise"))
        assertEquals(Personal.Rewritten(hum, "rise"), Personal.rewrite(MatchResult("none"), hum, "rise"))
        assertEquals(Personal.Rewritten(hum, "rise", trusted = true), Personal.rewrite(MatchResult("gesture", EnrollClass("gesture", "rise")), hum, "rise"))   // [train] agreeing gesture: kept, trusted (relabel: GestureRelabelTest)
    }

    // --- deciding -------------------------------------------------------------------------------------------------------

    private class CountingModel : Decider {
        var calls = 0
        override val name = "fake-model"
        override fun decide(input: DecisionInput): Decision { calls++; return Decision("swipe_up", "model") }
    }

    private fun input(heard: List<String>, seq: List<String>, profile: Profile, mode: String = "gesture") =
        DecisionInput(StateBuilder.build(mode, "ai.vox.fixture", "Fixture", heard, seq, null, profile, emptyList(), null, null), profile)

    @Test fun customAndIgnoreSoundsAreDecidedLocally() {
        val meowLine = Personal.customLine("meow", hum)!!
        val bound = Profile.parse(JSONObject("""{"global": [{"sound": "my:meow", "kind": "fixed", "action": "open_camera"}]}"""))
        assertEquals(listOf("my:meow"), bound.globalBindings()[0].phrase)
        for (mode in listOf("model", "hybrid", "rules")) {
            val model = CountingModel()
            val d = ChainDecider(mode, model)
            val a = d.decide(input(listOf(meowLine), listOf("my:meow"), bound))
            assertEquals("open_camera", a.action); assertTrue(a.source, a.source.startsWith("personal:custom-sound"))
            val u = d.decide(input(listOf(Personal.customLine("trill", hum)!!), listOf("my:trill"), bound))
            assertEquals("none", u.action); assertTrue(u.source, u.source.contains("rules:unbound"))
            val i = d.decide(input(listOf(Personal.ignoreLine(hum)), listOf("rise"), bound))
            assertEquals("none", i.action); assertTrue(i.source, i.source.contains("my-ignore-sound"))
            assertEquals("$mode: the model must not be called", 0, model.calls)
            // a normal sound still reaches the model
            d.decide(input(listOf(pop.replace("a short lip pop", "a tongue click")), listOf("click", "rise"), bound))
            if (mode == "model") assertEquals(1, model.calls)
        }
        // A plain-language rule on a custom sound goes to the model.
        val ruled = Profile.parse(JSONObject("""{"global": [{"sound": "my:meow", "kind": "rule", "rule": "When I make my meow sound, open the camera."}]}"""))
        val model = CountingModel()
        assertEquals("swipe_up", ChainDecider("model", model).decide(input(listOf(meowLine), listOf("my:meow"), ruled)).action)
        assertEquals(1, model.calls)
        // Custom sounds work in cursor mode too (cursor-scope rules).
        val cur = Profile.parse(JSONObject("""{"cursor": [{"sound": "my:meow", "kind": "fixed", "action": "click"}]}"""))
        assertEquals("click", ChainDecider("model", CountingModel()).decide(input(listOf(meowLine), listOf("my:meow"), cur, "cursor")).action)
    }

    @Test fun profileNameSoundKeyAndRuleTexts() {
        val p = Profile.parse(JSONObject("""{"name": "alice", "global": [
            {"sound": "my:meow", "kind": "fixed", "action": "open_camera"},
            {"sound": "my:trill", "kind": "rule", "rule": "When I trill, go home."},
            {"phrase": ["rise", "rise"], "kind": "fixed", "action": "notifications"}]}"""))
        assertEquals("alice", p.name)
        assertEquals(Profile.DEFAULT_NAME, Profile.parse(JSONObject("{}")).name)
        // fixed custom-sound rules are local only; plain-language ones and ordinary bindings are shown to the model
        val texts = p.ruleTexts("ai.vox.fixture", "Fixture", "gesture")
        assertEquals(2, texts.size)
        assertTrue(texts.none { it.contains("meow") }); assertTrue(texts.contains("When I trill, go home."))
        expectFail("bad profile name") { Profile.parse(JSONObject("""{"name": "../x"}""")) }
        expectFail("bad custom label") { Profile.parse(JSONObject("""{"global": [{"sound": "my:Me\"ow", "action": "home"}]}""")) }
        expectFail("sound and phrase") { Profile.parse(JSONObject("""{"global": [{"sound": "my:meow", "phrase": ["rise"], "action": "home"}]}""")) }
        // a custom sound can be part of a sequence; the sequencer then waits after "click"
        val seq = Profile.parse(JSONObject("""{"global": [{"phrase": ["click", "my:meow"], "action": "home"}]}"""))
        assertTrue(listOf("click", "my:meow") in seq.boundSequences("x", "gesture"))
    }

    /** E9: a training take with a mismatched label is held out of matching and relabel until the user confirms it. */
    @Test fun unconfirmedTakesAreSkippedUntilConfirmed() {
        val st = EnrollmentStore("default")
        val ok = JSONObject().put("cell", "soft-1")
        val un = JSONObject().put("cell", "soft-2").put("label_mismatch", true).put("confirmed", false)
        st.add("gesture", "pop", listOf(
            feat(1.0, 1.0, 1.0).withMeta(ok), feat(1.1, 1.1, 1.1).withMeta(ok), feat(1.2, 1.2, 1.2).withMeta(un)))
        val cls = st.find("pop")!!
        assertTrue(cls.examples[2].unconfirmed)
        assertEquals(2, cls.confirmed.size)
        assertFalse(cls.active)                                          // 3 examples, but only 2 confirmed
        assertEquals("skipped", Matcher(st, 1.5).match(feat(1.05, 1.05, 1.05)).result)
        // held back after a restart too: the flag survives the store file (toJson / fromJson)
        val reloaded = EnrollmentStore.fromJson(JSONObject(st.toJson().toString()))
        assertTrue(reloaded.find("pop")!!.examples[2].unconfirmed); assertFalse(reloaded.find("pop")!!.active)
        assertEquals("skipped", Matcher(reloaded, 1.5).match(feat(1.05, 1.05, 1.05)).result)
        // confirm (train_confirm keep): the take now takes part in matching
        cls.examples[2].meta!!.put("confirmed", true)
        assertFalse(cls.examples[2].unconfirmed)
        assertEquals(3, cls.confirmed.size); assertTrue(cls.active)
        assertEquals("gesture", Matcher(st, 1.5).match(feat(1.05, 1.05, 1.05)).result)
    }
}
