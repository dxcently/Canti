package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** ChainQueue (Chain.kt): the state machine, driven with a fake clock and a list of effects. */
class ChainQueueTest {
    private class Clock : Scheduler {
        var t = 0L
        private val tasks = mutableListOf<Pair<Long, () -> Unit>>()
        override fun now() = t
        override fun schedule(delayMs: Long, task: () -> Unit): () -> Unit {
            val e = (t + delayMs) to task; tasks += e; return { tasks.remove(e) }
        }
        fun advance(ms: Long) {
            val end = t + ms
            while (true) {
                val next = tasks.filter { it.first <= end }.minByOrNull { it.first } ?: break
                tasks.remove(next); t = maxOf(t, next.first); next.second()
            }
            t = end
        }
    }

    private fun cs(vararg said: String) = said.map { ChainStep(it, SpeechCommand.Nav(it)) }
    private fun action(a: String, watch: Long? = null) = Last.Action(a, "listening", 0L, "app", watch = watch)

    private class Rig {
        val c = Clock()
        val q = ChainQueue(c, stepTimeoutMs = { 60_000L })
        val eff = mutableListOf<ChainEffect>()
        init { q.onEffect = { eff += it } }
        fun runs() = eff.filterIsInstance<ChainEffect.RunStep>().map { it.step.n }
        fun runUndos() = eff.filterIsInstance<ChainEffect.RunUndo>().map { it.step.n }
        fun rows() = eff.filterIsInstance<ChainEffect.Row>().map { it.row }
        fun listens() = eff.filterIsInstance<ChainEffect.Listen>()
        fun ended() = eff.filterIsInstance<ChainEffect.Ended>().map { it.why }
    }

    @Test fun stepsRunStrictlyInOrderAfterEachConfirm() {
        val r = Rig()
        r.q.start(cs("open settings", "scroll down", "go back"), 0)
        assertEquals(listOf(1), r.runs())   // only step 1 runs at start
        r.q.onExec(action("tap", watch = 10L))
        assertEquals("checking", r.q.stepList[0].note)
        assertEquals(listOf(1), r.runs())   // step 2 does not start before the confirm
        r.q.onConfirm(10L, "confirmed (events)")
        assertEquals(StepStatus.DONE, r.q.stepList[0].status)
        assertEquals(listOf(1, 2), r.runs())
    }

    @Test fun noVisibleChangePausesAndHoldsLaterSteps() {
        val r = Rig()
        r.q.start(cs("scroll down", "go back"), 0)
        r.q.onExec(action("scroll_down", watch = 10L))
        r.q.onConfirm(10L, "no visible change")
        assertEquals(StepStatus.STUCK, r.q.stepList[0].status)
        assertEquals(StepStatus.WAITING, r.q.stepList[1].status)
        assertEquals("held", r.q.stepList[1].note)
        assertTrue(r.rows().any { it is StripRow.Paused })
        assertTrue(r.listens().isNotEmpty())
        assertEquals(emptyList<String>(), r.ended())
    }

    @Test fun retrySkipContinueCancel() {
        // retry re-runs the stuck step
        val r = Rig()
        r.q.start(cs("scroll down", "go back"), 0)
        r.q.onExec(action("scroll_down", watch = 10L)); r.q.onConfirm(10L, "no visible change")
        r.q.control(ChainControl.Cmd.Retry)
        assertEquals(StepStatus.RUNNING, r.q.stepList[0].status)
        assertEquals(listOf(1, 1), r.runs())
        // skip drops the stuck step and continues
        val r2 = Rig()
        r2.q.start(cs("scroll down", "go back"), 0)
        r2.q.onExec(action("scroll_down", watch = 10L)); r2.q.onConfirm(10L, "no visible change")
        r2.q.control(ChainControl.Cmd.Skip)
        assertEquals(StepStatus.DROPPED, r2.q.stepList[0].status)
        assertEquals(StepStatus.RUNNING, r2.q.stepList[1].status)
        // cancel drops the rest and ends
        val r3 = Rig()
        r3.q.start(cs("scroll down", "go back"), 0)
        r3.q.onExec(action("scroll_down", watch = 10L)); r3.q.onConfirm(10L, "no visible change")
        r3.q.control(ChainControl.Cmd.Cancel)
        assertTrue(r3.ended().isNotEmpty())
        assertEquals(StepStatus.DROPPED, r3.q.stepList[1].status)
    }

    @Test fun pickerAndConfirmAsk() {
        val r = Rig()
        r.q.start(cs("scroll down", "go back"), 0)
        r.q.onOutcome(Outcome.Ask.Picker)
        assertEquals(StepStatus.ASK, r.q.stepList[0].status)
        assertEquals("which one?", r.q.stepList[0].note)
        r.q.onOutcome(Outcome.AskEnded(false))
        assertEquals(StepStatus.STUCK, r.q.stepList[0].status)   // cancelled picker pauses
        // confirm ask closes listening and re-runs on ok
        val r2 = Rig()
        r2.q.start(cs("scroll down"), 0)
        r2.q.onOutcome(Outcome.Ask.Confirm)
        assertEquals("click to confirm", r2.q.stepList[0].note)
        assertTrue(r2.eff.any { it is ChainEffect.StopListening })
        r2.q.onOutcome(Outcome.AskEnded(true))
        assertEquals(StepStatus.RUNNING, r2.q.stepList[0].status)
    }

    @Test fun doneNoWatchAndStepTimeoutAndSuperseded() {
        val r = Rig()
        r.q.start(cs("scroll down", "go back"), 0)
        r.q.onOutcome(Outcome.DoneNoWatch)
        assertEquals(StepStatus.DONE, r.q.stepList[0].status)
        assertEquals(listOf(1, 2), r.runs())
        // a watch that never answers -> step timeout
        val r2 = Rig()
        r2.q.start(cs("scroll down"), 0)
        r2.q.onExec(action("scroll_down", watch = 10L))
        r2.c.advance(60_000)
        assertEquals(StepStatus.STUCK, r2.q.stepList[0].status)
        assertEquals("no answer", r2.q.stepList[0].note)
        // superseded is ignored
        val r3 = Rig()
        r3.q.start(cs("scroll down"), 0)
        r3.q.onExec(action("scroll_down", watch = 10L))
        r3.q.onConfirm(10L, "superseded")
        assertEquals(StepStatus.RUNNING, r3.q.stepList[0].status)
    }

    @Test fun tailAndPauseSilenceEnd() {
        val r = Rig()
        r.q.start(cs("scroll down"), 0)
        r.q.onExec(action("scroll_down", watch = 10L)); r.q.onConfirm(10L, "confirmed (events)")
        assertEquals(StepStatus.DONE, r.q.stepList[0].status)   // queue empty -> tail
        r.q.onSilence()
        assertEquals(listOf("silence"), r.ended())
        // paused -> paused_timeout, rest dropped
        val r2 = Rig()
        r2.q.start(cs("scroll down", "go back"), 0)
        r2.q.onExec(action("scroll_down", watch = 10L)); r2.q.onConfirm(10L, "no visible change")
        r2.q.onSilence()
        assertEquals(listOf("paused_timeout"), r2.ended())
        assertEquals(StepStatus.DROPPED, r2.q.stepList[1].status)
    }

    @Test fun doneControlAndAppendAndRejectNext() {
        val r = Rig()
        r.q.start(cs("scroll down", "go back"), 0)
        r.q.control(ChainControl.Cmd.Done)
        assertEquals(listOf("done"), r.ended())
        assertEquals(StepStatus.DROPPED, r.q.stepList[0].status)
        // append while running
        val r2 = Rig()
        r2.q.start(cs("scroll down"), 0)
        r2.q.append(cs("go back"))
        assertEquals(2, r2.q.stepList.size)
        // reject next drops the waiting step
        val r3 = Rig()
        r3.q.start(cs("scroll down", "go back"), 0)
        r3.q.control(ChainControl.Cmd.RejectNext)
        assertEquals(StepStatus.DROPPED, r3.q.stepList[1].status)
    }

    @Test fun undoNavigationStepReversesThenPauses() {
        val r = Rig()
        r.q.start(cs("scroll down", "go back"), 0)
        r.q.onExec(action("scroll_down", watch = 10L)); r.q.onConfirm(10L, "confirmed (events)")
        assertEquals(StepStatus.DONE, r.q.stepList[0].status)
        r.q.control(ChainControl.Cmd.Undo)
        assertEquals(listOf(1), r.runUndos())   // RunUndo emitted with the inverse
        r.q.onExec(action("scroll_up", watch = 20L))
        r.q.onConfirm(20L, "confirmed (events)")
        assertEquals(StepStatus.UNDONE, r.q.stepList[0].status)
        assertTrue(r.rows().any { it is StripRow.Paused })   // paused
    }

    @Test fun undoNonNavigationSaysCantUndo() {
        val r = Rig()
        r.q.start(cs("scroll down"), 0)
        // a toggle tap (no window change) is not undoable
        r.q.onExec(Last.Pick(Target("Toggle", "switch", "center", 0, 0, 10, 10), emptyList(), 0L, "app", watch = 10L,
            confirm = "confirmed (events)", by = "TYPE_VIEW_CLICKED:com.x"))
        r.q.onConfirm(10L, "confirmed (events)")
        r.q.control(ChainControl.Cmd.Undo)
        assertTrue(r.rows().any { it is StripRow.BackMiss && it.value.startsWith("can't undo") })
    }

    @Test fun rewindReversesInOrderAndStopsAtCantUndo() {
        val r = Rig()
        r.q.start(cs("scroll down", "scroll up"), 0)
        r.q.onExec(action("scroll_down", watch = 10L)); r.q.onConfirm(10L, "confirmed (events)")
        r.q.onExec(action("scroll_up", watch = 20L)); r.q.onConfirm(20L, "confirmed (events)")
        r.q.control(ChainControl.Cmd.Rewind("scroll down"))
        assertEquals(listOf(2), r.runUndos())   // the latest done step first
        r.q.onExec(action("scroll_down", watch = 30L)); r.q.onConfirm(30L, "confirmed (events)")
        assertEquals(listOf(2, 1), r.runUndos()) // then the named step
    }

    @Test fun chainMemoryWindowAndAppSwitch() {
        val r = Rig()
        r.q.start(cs("scroll down"), 0)
        val m = ChainMemory()
        m.store(r.q, "appA", 1000)
        assertEquals(r.q, m.current(1000 + 30_000, "appA"))   // exactly the edge
        assertNull(m.current(1000 + 30_001, "appA"))
        assertNull(m.current(2000, "appB"))                   // app switched
        m.clear(); assertNull(m.current(2000, "appA"))
    }

    @Test fun queueLayoutSlotsChipsExpandedAndScroll() {
        fun step(n: Int, status: StepStatus) = QueueStep(n, "said $n", SpeechCommand.Nav("go home")).apply { this.status = status }
        val steps = listOf(step(1, StepStatus.DONE), step(2, StepStatus.DONE), step(3, StepStatus.DONE),
            step(4, StepStatus.RUNNING), step(5, StepStatus.WAITING), step(6, StepStatus.WAITING), step(7, StepStatus.WAITING))
        val f = QueueLayout.frame(steps, expanded = false, scroll = 0)
        assertEquals(listOf(3, 4, 5), f.rows.map { it.n })   // last-done / running / next
        assertEquals(2, f.doneAbove)                          // steps 1 and 2 are above the shown done step
        assertEquals(2, f.moreBelow)                          // steps 6 and 7 are below the shown next
        val e = QueueLayout.frame(steps, expanded = true, scroll = 1)
        assertEquals(7, e.rows.size)
        assertEquals(1, e.scroll)
        assertTrue(e.scrollbar != null)
        val clamp = QueueLayout.frame(steps, expanded = true, scroll = 99)
        assertEquals(6, clamp.scroll)                         // clamped to size-1
    }

    @Test fun silenceOnlyEndsTailAndPause() {
        val r = Rig()
        r.q.start(cs("scroll down"), 0)
        r.q.onSilence()   // RUNNING (step not yet executed): ignored
        assertEquals(emptyList<String>(), r.ended())
        r.q.onExec(action("scroll_down", watch = 10L))
        r.q.onSilence()   // RUNNING (checking): ignored
        assertEquals(emptyList<String>(), r.ended())
        r.q.onConfirm(10L, "confirmed (events)")   // now TAIL
        r.q.onSilence()
        assertEquals(listOf("silence"), r.ended())
    }

    @Test fun cantUndoPausesAndTimesOut() {
        val r = Rig()
        r.q.start(cs("scroll down"), 0)
        r.q.onExec(Last.Pick(Target("Toggle", "switch", "center", 0, 0, 10, 10), emptyList(), 0L, "app", watch = 10L,
            confirm = "confirmed (events)", by = "TYPE_VIEW_CLICKED:com.x"))
        r.q.onConfirm(10L, "confirmed (events)")
        r.q.control(ChainControl.Cmd.Undo)
        assertTrue(r.rows().any { it is StripRow.BackMiss && it.value.startsWith("can't undo") })
        assertTrue(r.listens().isNotEmpty())   // the can't-undo pause listens like the others
        r.q.onSilence()
        assertEquals(listOf("paused_timeout"), r.ended())
    }

    @Test fun undoWhileStepRunningHoldsItAndIgnoresItsLateConfirm() {
        val r = Rig()
        r.q.start(cs("scroll down", "scroll up"), 0)
        r.q.onExec(action("scroll_down", watch = 10L)); r.q.onConfirm(10L, "confirmed (events)")
        r.q.onExec(action("scroll_up", watch = 20L))   // step 2 now RUNNING
        assertEquals(StepStatus.RUNNING, r.q.stepList[1].status)
        r.q.control(ChainControl.Cmd.Undo)
        assertEquals(StepStatus.WAITING, r.q.stepList[1].status)   // held back
        assertEquals("held", r.q.stepList[1].note)
        assertEquals(listOf(1), r.runUndos())
        r.q.onConfirm(20L, "confirmed (events)")   // late answer for the old watch: ignored
        assertEquals(StepStatus.WAITING, r.q.stepList[1].status)
        assertEquals(StepStatus.UNDONE, r.q.stepList[0].status)
    }

    @Test fun endedChainOnlyReopensForUndo() {
        val r = Rig()
        r.q.start(cs("scroll down"), 0)
        r.q.onExec(action("scroll_down", watch = 10L)); r.q.onConfirm(10L, "confirmed (events)")
        r.q.onSilence()
        assertEquals(listOf("silence"), r.ended())
        // controls on an ENDED chain are no-ops (not consumed)
        r.q.control(ChainControl.Cmd.Skip)
        r.q.control(ChainControl.Cmd.Done)
        assertEquals(listOf("silence"), r.ended())
        // reopen for undo only
        assertTrue(r.q.reopenForUndo())
        r.q.control(ChainControl.Cmd.Undo)
        assertEquals(listOf(1), r.runUndos())
    }

    @Test fun reopenForUndoUndoesThenEndsAgain() {
        val r = Rig()
        r.q.start(cs("scroll down", "scroll up"), 0)
        r.q.onExec(action("scroll_down", watch = 10L)); r.q.onConfirm(10L, "confirmed (events)")
        r.q.onExec(action("scroll_up", watch = 20L)); r.q.onConfirm(20L, "confirmed (events)")
        r.q.onSilence()
        assertEquals(listOf("silence"), r.ended())
        assertTrue(r.q.reopenForUndo())
        r.q.control(ChainControl.Cmd.Undo)
        assertEquals(listOf(2), r.runUndos())
        r.q.onExec(action("scroll_down", watch = 30L)); r.q.onConfirm(30L, "confirmed (events)")
        assertTrue(r.ended().contains("undo"))   // ends again, not a pause
        assertEquals(StepStatus.UNDONE, r.q.stepList[1].status)
    }

    @Test fun heardRearmsListenOnlyWhenIdle() {
        // TAIL -> re-listen
        val r1 = Rig()
        r1.q.start(cs("scroll down"), 0)
        r1.q.onExec(action("scroll_down", watch = 10L)); r1.q.onConfirm(10L, "confirmed (events)")
        val n1 = r1.listens().size
        r1.q.heard()
        assertEquals(n1 + 1, r1.listens().size)
        // RUNNING -> no re-listen
        val r2 = Rig()
        r2.q.start(cs("scroll down"), 0)
        val n2 = r2.listens().size
        r2.q.heard()
        assertEquals(n2, r2.listens().size)
        // PAUSED -> re-listen
        val r3 = Rig()
        r3.q.start(cs("scroll down", "go back"), 0)
        r3.q.onExec(action("scroll_down", watch = 10L)); r3.q.onConfirm(10L, "no visible change")
        val n3 = r3.listens().size
        r3.q.heard()
        assertEquals(n3 + 1, r3.listens().size)
    }

    @Test fun afterEndExecConfirmAndOutcomeAreNoOps() {
        val r = Rig()
        r.q.start(cs("scroll down", "go back"), 0)
        r.q.onExec(action("scroll_down", watch = 10L))   // step 1 running with a watch
        r.q.control(ChainControl.Cmd.Cancel)
        assertEquals(listOf("cancel"), r.ended())
        assertEquals(StepStatus.DROPPED, r.q.stepList[0].status)
        r.q.onConfirm(10L, "confirmed (events)")   // late confirm: must not resurrect the dropped step
        assertEquals(StepStatus.DROPPED, r.q.stepList[0].status)
        r.q.onExec(action("scroll_up", watch = 99L))
        r.q.onOutcome(Outcome.DoneNoWatch)
        assertEquals(StepStatus.DROPPED, r.q.stepList[0].status)
        assertEquals(StepStatus.DROPPED, r.q.stepList[1].status)
    }
}
