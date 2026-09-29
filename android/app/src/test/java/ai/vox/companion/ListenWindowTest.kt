package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The phrase window with a fake recognizer, mic and clock (ListenWindow.kt): no microphone or recognizer needed. */
class ListenWindowTest {
    private class Clock : Scheduler {
        var t = 0L
        private val tasks = mutableListOf<Pair<Long, () -> Unit>>()
        override fun now() = t
        override fun schedule(delayMs: Long, task: () -> Unit): () -> Unit {
            val e = (t + delayMs) to task; tasks += e; return { tasks.remove(e) }
        }
        /** Run everything due, in time order, including what the tasks schedule on the way. */
        fun advance(ms: Long) {
            val end = t + ms
            while (true) {
                val next = tasks.filter { it.first <= end }.minByOrNull { it.first } ?: break
                tasks.remove(next); t = maxOf(t, next.first); next.second()
            }
            t = end
        }
        val pending get() = tasks.size
    }

    private class Mic(var capturing: Boolean = true) : ListenWindow.MicYield {
        var yields = 0; var resumes = 0
        override fun yieldMic(why: String): Boolean { yields++; val was = capturing; capturing = false; return was }
        override fun resumeMic(why: String) { resumes++; capturing = true }
    }

    private class Rec(var unavailable: String? = null, override val usesMic: Boolean = true) : PhraseRecognizer {
        override val name = "fake"
        var listener: PhraseRecognizer.Listener? = null
        var starts = 0; var stops = 0; var cancels = 0
        var startedAt = -1L
        lateinit var clock: Clock
        override fun status() = unavailable
        override fun start(listener: PhraseRecognizer.Listener) { starts++; startedAt = clock.t; this.listener = listener }
        override fun stop() { stops++ }
        override fun cancel() { cancels++ }
    }

    private fun harness(rec: Rec = Rec(), mic: Mic? = Mic()): Triple<Clock, ListenWindow, MutableList<ListenWindow.Done>> {
        val c = Clock(); rec.clock = c
        return Triple(c, ListenWindow(c, mic), mutableListOf())
    }

    @Test fun finalResultClosesOnceAndResumesTheMicOnce() {
        val rec = Rec(); val mic = Mic()
        val (c, w, done) = harness(rec, mic)
        w.open(rec, 6000) { done += it }
        assertTrue(w.isOpen)
        assertEquals(1, mic.yields); assertFalse(mic.capturing)
        assertEquals(0, rec.starts)                       // waits for the recorder to be released
        c.advance(ListenWindow.HANDOFF_MS)
        assertEquals(1, rec.starts); assertEquals(ListenWindow.HANDOFF_MS, rec.startedAt)
        val l = rec.listener!!
        l.onReady(); l.onLevel(3f); l.onLevel(8f); l.onPartial("open you"); l.onPartial("open youtube")
        c.advance(1000)
        l.onFinal(Heard(listOf("open youtube", "open you tube"), listOf(0.9f, 0.4f)))
        assertFalse(w.isOpen)
        assertEquals(1, done.size)
        val d = done[0]
        assertEquals("final", d.why); assertNull(d.status)
        assertEquals(listOf("open youtube", "open you tube"), d.heard!!.hypotheses)
        assertEquals(2, d.partials); assertEquals(8f, d.peakDb!!, 0f); assertEquals(ListenWindow.HANDOFF_MS, d.readyMs)
        assertEquals(1, mic.resumes); assertTrue(mic.capturing)
        assertEquals(1, rec.cancels)                     // the engine is freed
        // late callbacks and the old timeout do nothing
        l.onFinal(Heard(listOf("again"))); l.onError(7, "no match", null)
        c.advance(10_000)
        assertEquals(1, done.size); assertEquals(1, mic.resumes); assertEquals(0, rec.stops); assertEquals(0, c.pending)
    }

    @Test fun timeoutStopsThenUsesTheLastPartialAfterTheGrace() {
        val rec = Rec(); val mic = Mic()
        val (c, w, done) = harness(rec, mic)
        w.open(rec, 6000) { done += it }
        c.advance(ListenWindow.HANDOFF_MS)
        rec.listener!!.onPartial("scroll down")
        c.advance(6000 - ListenWindow.HANDOFF_MS)
        assertEquals(1, rec.stops); assertTrue(w.isOpen)   // waiting for the final result
        c.advance(ListenWindow.GRACE_MS)
        assertFalse(w.isOpen)
        assertEquals("timeout", done.single().why)
        assertEquals(Heard(listOf("scroll down"), partial = true), done.single().heard)
        assertEquals(1, mic.resumes)
    }

    @Test fun aFinalResultInTheGraceWins() {
        val rec = Rec()
        val (c, w, done) = harness(rec)
        w.open(rec, 3000) { done += it }
        c.advance(3000)
        assertEquals(1, rec.stops)
        c.advance(500)
        rec.listener!!.onFinal(Heard(listOf("go home")))
        assertEquals("final", done.single().why); assertEquals("go home", done.single().heard!!.best)
        c.advance(5000)
        assertEquals(1, done.size)
    }

    @Test fun silenceEndsWithNothingToActOn() {
        val rec = Rec(); val mic = Mic()
        val (c, w, done) = harness(rec, mic)
        w.open(rec, 6000) { done += it }
        c.advance(ListenWindow.HANDOFF_MS)
        rec.listener!!.onError(6, "no speech", null)
        assertNull(done.single().heard); assertNull(done.single().status); assertEquals("error: no speech", done.single().why)
        assertEquals(1, mic.resumes)
        // an empty final result is no speech too
        w.open(rec, 6000) { done += it }
        c.advance(ListenWindow.HANDOFF_MS)
        rec.listener!!.onFinal(Heard(listOf("", " ")))
        assertEquals("no speech", done.last().why); assertNull(done.last().heard)
        assertEquals(2, mic.resumes); assertEquals(2, mic.yields)
    }

    @Test fun missingOfflinePackIsReportedAndNeverTouchesTheMic() {
        val rec = Rec(unavailable = AsrPlan.PACK_MISSING); val mic = Mic()
        val (_, w, done) = harness(rec, mic)
        w.open(rec, 6000) { done += it }
        assertFalse(w.isOpen)
        assertEquals("unavailable", done.single().why); assertEquals(AsrPlan.PACK_MISSING, done.single().status)
        assertEquals(0, rec.starts); assertEquals(0, mic.yields); assertEquals(0, mic.resumes); assertFalse(done.single().micYielded)
        assertTrue(mic.capturing)
    }

    @Test fun anErrorTheUserMustFixDropsThePartial() {
        val rec = Rec(); val mic = Mic()
        val (c, w, done) = harness(rec, mic)
        w.open(rec, 6000) { done += it }
        c.advance(ListenWindow.HANDOFF_MS)
        rec.listener!!.onPartial("open")
        val (what, status) = AsrPlan.error(13, offlineOnly = true)
        rec.listener!!.onError(13, what, status)
        assertNull(done.single().heard); assertEquals(AsrPlan.PACK_MISSING, done.single().status)
        assertEquals(1, mic.resumes)
    }

    @Test fun cancelAndSupersedeKeepYieldsAndResumesBalanced() {
        val rec = Rec(); val mic = Mic()
        val (c, w, done) = harness(rec, mic)
        w.open(rec, 6000) { done += it }
        w.cancel("disarm")                                  // before the recognizer even started
        assertEquals("cancelled: disarm", done.single().why)
        c.advance(10_000)
        assertEquals(0, rec.starts); assertEquals(1, mic.yields); assertEquals(1, mic.resumes); assertTrue(mic.capturing)
        w.open(rec, 6000) { done += it }
        c.advance(ListenWindow.HANDOFF_MS)
        w.open(rec, 6000) { done += it }                    // pop pop again while listening
        assertEquals("cancelled: superseded", done[1].why)
        c.advance(ListenWindow.HANDOFF_MS)
        rec.listener!!.onFinal(Heard(listOf("next")))
        assertEquals("final", done[2].why)
        assertEquals(3, mic.yields); assertEquals(3, mic.resumes); assertTrue(mic.capturing)
        w.cancel("again")
        assertEquals(3, done.size)                         // nothing open: nothing reported
    }

    @Test fun noHandoffWaitWhenTheMicWasNotCapturingOrNotUsed() {
        // the Pico is the source: nothing to release
        val rec = Rec(); val mic = Mic(capturing = false)
        val (c, w, done) = harness(rec, mic)
        w.open(rec, 6000) { done += it }
        c.advance(0)
        assertEquals(1, rec.starts); assertEquals(0L, rec.startedAt)
        rec.listener!!.onFinal(Heard(listOf("go back")))
        assertEquals(1, mic.resumes)
        // an engine without the mic (asr_engine off): the capture is never paused
        val stub = Rec(usesMic = false); val mic2 = Mic()
        val (c2, w2, done2) = harness(stub, mic2)
        w2.open(stub, 6000) { done2 += it }
        c2.advance(7500)
        assertEquals(0, mic2.yields); assertEquals(0, mic2.resumes)
        assertEquals("timeout", done2.single().why); assertFalse(done2.single().micYielded)
        assertTrue(done.single().micYielded)
    }

    @Test fun recognizerPlanNeverFallsBackToTheCloudSilently() {
        fun plan(api: Int = 34, perm: Boolean = true, onDevice: Boolean = true, any: Boolean = true, online: Boolean = false, missing: Boolean = false) =
            AsrPlan.choose(api, perm, onDevice, any, online, missing)
        assertEquals(AsrPlan.Plan(AsrPlan.Kind.ON_DEVICE, null), plan())
        assertEquals(AsrPlan.Plan(AsrPlan.Kind.NONE, AsrPlan.NO_PERMISSION), plan(perm = false))
        assertEquals(AsrPlan.Plan(AsrPlan.Kind.DEFAULT_OFFLINE, null), plan(onDevice = false))
        assertEquals(AsrPlan.Plan(AsrPlan.Kind.DEFAULT_OFFLINE, null), plan(api = 30))
        assertEquals(AsrPlan.Plan(AsrPlan.Kind.NONE, AsrPlan.PACK_MISSING), plan(missing = true))
        assertEquals(AsrPlan.Plan(AsrPlan.Kind.DEFAULT_ONLINE, null), plan(missing = true, online = true))
        assertEquals(AsrPlan.Plan(AsrPlan.Kind.NONE, "no speech recognizer on this phone"), plan(onDevice = false, any = false))
        assertEquals(AsrPlan.Plan(AsrPlan.Kind.NONE, AsrPlan.PACK_MISSING), plan(any = false, missing = true, online = true))
        // offline only, the engine asking for the network means the pack is missing
        assertEquals(AsrPlan.PACK_MISSING, AsrPlan.error(2, offlineOnly = true).second)
        assertEquals("speech needs the network", AsrPlan.error(2, offlineOnly = false).second)
        assertEquals(AsrPlan.PACK_MISSING, AsrPlan.error(13, offlineOnly = false).second)
        assertEquals(AsrPlan.NO_PERMISSION, AsrPlan.error(9, offlineOnly = true).second)
        assertNull(AsrPlan.error(7, offlineOnly = true).second)
        assertNull(AsrPlan.error(6, offlineOnly = true).second)
    }

    @Test fun onWordsSeesPartialsAndTheFinalBestAndNothingAfterClose() {
        val rec = Rec(); val mic = Mic()
        val (c, w, _) = harness(rec, mic)
        val words = mutableListOf<String>()
        w.open(rec, 6000, onWords = { words += it }) { }
        c.advance(ListenWindow.HANDOFF_MS)
        rec.listener!!.onPartial("open you")
        rec.listener!!.onPartial("open youtube")
        rec.listener!!.onFinal(Heard(listOf("open youtube", "open you tube")))
        assertEquals(listOf("open you", "open youtube", "open youtube"), words)
        rec.listener!!.onPartial("late")   // after close: nothing more
        assertEquals(3, words.size)
    }
}
