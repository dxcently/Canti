package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Main-thread section timing (MainLoad.kt): counts, totals, maxima, the slow buckets, busiest first, reset. */
class LoadStatsTest {
    @Test fun countsTotalsMaximaAndBuckets() {
        val s = LoadStats()
        s.record("a11y_event", 1.0); s.record("a11y_event", 3.0)
        s.record("tree:current_app", 20.0); s.record("tree:current_app", 60.0); s.record("tree:current_app", 150.0)
        val snap = s.snapshot()
        assertEquals(listOf("tree:current_app", "a11y_event"), snap.keys.toList())   // busiest first
        val app = snap.getValue("tree:current_app")
        assertEquals(3L, app["count"]); assertEquals(230.0, app["total_ms"]); assertEquals(150.0, app["max_ms"])
        assertEquals(3L, app["over_16"]); assertEquals(2L, app["over_50"]); assertEquals(1L, app["over_100"])
        assertEquals(2.0, snap.getValue("a11y_event")["mean_ms"])
        s.reset(); assertTrue(s.snapshot().isEmpty())
    }

    @Test fun onlySlowSectionsAreReported() {
        val slow = ArrayList<String>()
        MainLoad.onSlow = { what, _ -> slow += what }
        try {
            MainLoad.done("fast", 5.0); MainLoad.done("slow", 150.0)
            assertEquals(listOf("slow"), slow)
            assertEquals(42, MainLoad.time("timed") { 42 })
            assertTrue(MainLoad.stats.snapshot().containsKey("timed"))
        } finally { MainLoad.onSlow = { _, _ -> }; MainLoad.stats.reset() }
    }

    @Test fun offMainSectionsAreTaggedAndNeverMainSlow() {
        val slow = ArrayList<String>()
        MainLoad.onSlow = { what, _ -> slow += what }
        MainLoad.mainThread = Thread.currentThread()
        try {
            val t = Thread { MainLoad.done("tree:refresh", 300.0) }
            t.start(); t.join(2000)
            assertTrue(slow.isEmpty())   // a background tree read is not the main thread being slow
            val snap = MainLoad.stats.snapshot()
            assertTrue(snap.containsKey("tree:refresh@bg")); assertTrue(!snap.containsKey("tree:refresh"))
            MainLoad.done("tree:refresh", 300.0)   // on the main thread: reported as before
            assertEquals(listOf("tree:refresh"), slow)
        } finally { MainLoad.mainThread = null; MainLoad.onSlow = { _, _ -> }; MainLoad.stats.reset() }
    }
}
