package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** Two installed apps for one name: the recently used one (usage access granted), else the official one, else ask. */
class AppChoiceTest {
    private val yt = "com.google.android.youtube"
    private val mod = "app.revanced.android.youtube"

    @Test fun oneCandidateIsIt() = assertEquals(yt, AppChoice.pick(listOf(yt), null))

    @Test fun mostRecentlyUsedWhenUsageAccessIsGranted() {
        assertEquals(mod, AppChoice.pick(listOf(yt, mod), mapOf(yt to 100L, mod to 200L)))
        assertEquals(yt, AppChoice.pick(listOf(yt, mod), mapOf(yt to 300L, mod to 0L)))
    }

    @Test fun elseTheOfficialApp() {
        assertEquals(yt, AppChoice.pick(listOf(mod, yt), null))
        assertEquals(yt, AppChoice.pick(listOf(mod, yt), mapOf(yt to 0L, mod to 0L)))
    }

    private val rvx = "app.rvx.android.youtube"
    private val ytMusic = "com.google.android.apps.youtube.music"
    private val prefs = AppChoice.parsePrefer(AppChoice.DEFAULT_PREFER)

    @Test fun youtubeMeansRvxWhenInstalled() {
        assertEquals(mapOf(yt to rvx), prefs)
        assertEquals(rvx, AppChoice.prefer(yt, prefs) { it == rvx || it == yt })
        // both answer to "youtube": the preference wins over recency and over the official app
        assertEquals(rvx, AppChoice.pick(listOf(yt, rvx), mapOf(yt to 900L, rvx to 100L), prefs = prefs))
        assertEquals(rvx, AppChoice.pick(listOf(rvx, yt), null, prefs = prefs))
    }

    @Test fun youtubeIsTheOfficialAppWhenRvxIsMissing() {
        assertEquals(yt, AppChoice.prefer(yt, prefs) { it == yt })
        assertEquals(yt, AppChoice.pick(listOf(yt, mod), null, prefs = prefs))
    }

    @Test fun youtubeMusicIsNotAffected() {
        assertEquals(ytMusic, AppChoice.prefer(ytMusic, prefs) { true })
        assertEquals(rvx, AppChoice.prefer(rvx, prefs) { true })
    }

    @Test fun preferenceParsing() {
        assertEquals(emptyMap<String, String>(), AppChoice.parsePrefer(""))
        assertEquals(mapOf("a.b" to "c.d", "e.f" to "g.h"), AppChoice.parsePrefer(" a.b=c.d , e.f=g.h "))
        for (bad in listOf("a.b", "a.b=c.d=e.f", "a.b=a.b", "youtube=rvx", "a.b=")) {
            try { AppChoice.parsePrefer(bad); throw AssertionError("accepted $bad") } catch (_: IllegalArgumentException) {}
        }
    }

    @Test fun elseAsk() {
        assertNull(AppChoice.pick(listOf("a.one", "b.two"), null))
        assertNull(AppChoice.pick(listOf("a.one", "b.two"), mapOf("a.one" to 5L, "b.two" to 5L)))
    }
}
