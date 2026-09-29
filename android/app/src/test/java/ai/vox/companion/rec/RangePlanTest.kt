package ai.vox.companion.rec

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** RangePlan vs extractor/range_layout.build_plan, through the checked-in parity fixture. */
class RangePlanTest {
    private val spec = File("../../extractor/prompts/range_v1.json").readBytes()

    private fun fixture(profile: String): List<JSONObject> {
        val f = JSONObject(File("../../extractor/tests/fixtures/range_v1_plan.json").readText())
        return f.getJSONArray(profile).let { a -> (0 until a.length()).map { a.getJSONObject(it) } }
    }

    private fun jsonOrNull(o: JSONObject, k: String): Any? = if (!o.has(k) || o.isNull(k)) null else o.get(k)

    private fun assertPlanMatches(profile: String) {
        val plan = RangePlan.parse(spec, profile)
        val want = fixture(profile)
        assertEquals("profile $profile take count", want.size, plan.takes.size)
        for (i in want.indices) {
            val w = want[i]
            val got = RangePlan.fixtureEntry(plan.takes[i])
            for (k in listOf("take_id", "block", "cue", "cond_id", "rep", "kind")) {
                assertEquals("$profile[$i].$k", jsonOrNull(w, k), jsonOrNull(got, k))
            }
            assertEquals("$profile[$i].expect", w.getJSONArray("expect").toString(), got.getJSONArray("expect").toString())
            assertEquals("$profile[$i].bg", jsonOrNull(w, "bg")?.toString(), jsonOrNull(got, "bg")?.toString())
        }
    }

    @Test fun shortProfileIs42Takes() {
        assertEquals(42, RangePlan.parse(spec, "short").takes.size)
        assertPlanMatches("short")
    }

    @Test fun fullProfileIs269TakesAnd7Backgrounds() {
        val plan = RangePlan.parse(spec, "full")
        assertEquals(269, plan.takes.count { it.kind == "takes" })
        assertEquals(7, plan.takes.count { it.kind == "backgrounds" })
        assertPlanMatches("full")
    }

    @Test fun backgroundsAreTheirOwnKind() {
        val plan = RangePlan.parse(spec, "full")
        val bgs = plan.takes.filter { it.kind == "backgrounds" }
        assertTrue(bgs.isNotEmpty())
        assertTrue(bgs.all { it.name != null && it.seconds != null && it.bgKind != null })
    }

    @Test fun manualAndFixedFlags() {
        val plan = RangePlan.parse(spec, "full")
        val room = plan.takeById("room-room-r1")!!
        assertTrue(room.quiet)
        assertTrue(room.fixedWindow)
        assertTrue(!room.manual)
        val bg = plan.takeById("backgrounds-media-30-r1")!!
        assertTrue(bg.manual)
        val real = plan.takeById("real-media-60-rise-hum-home-normal-normal-hand-na-r1")!!
        assertTrue(real.manual)
        assertTrue(real.bg != null)
    }
}
