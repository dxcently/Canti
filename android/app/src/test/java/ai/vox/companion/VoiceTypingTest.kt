package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Typing by voice (VoiceTyping.kt) with a fake recognizer, clock, mic and focused text box: no phone needed. */
class VoiceTypingTest {
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
        val pending get() = tasks.size
    }

    private class Mic : ListenWindow.MicYield {
        var yields = 0; var resumes = 0
        override fun yieldMic(why: String): Boolean { yields++; return true }
        override fun resumeMic(why: String) { resumes++ }
    }

    private class Rec(var unavailable: String? = null) : PhraseRecognizer {
        override val name = "fake"
        var listener: PhraseRecognizer.Listener? = null
        var starts = 0
        override fun status() = unavailable
        override fun start(listener: PhraseRecognizer.Listener) { starts++; this.listener = listener }
        override fun stop() {}
        override fun cancel() { listener = null }
        fun say(text: String) { listener!!.onPartial(text); listener!!.onFinal(Heard(listOf(text))) }
    }

    /** A focused text box that records every action performed on it. */
    private class Field(var value: String = "", var start: Int = -1, var end: Int = -1, override val isPassword: Boolean = false,
                        override val isEditable: Boolean = true, override val showingHint: Boolean = false,
                        override val maxLength: Int = 0) : TextField {
        val actions = mutableListOf<String>()
        override val text get() = value
        override val selStart get() = start
        override val selEnd get() = end
        override fun setText(text: String): Boolean { actions += "set_text"; value = text; return true }
        override fun setSelection(start: Int, end: Int): Boolean { actions += "set_selection"; this.start = start; this.end = end; return true }
    }

    // --- the grammar and punctuation -------------------------------------------------------------------------------

    @Test fun typeAndWriteKeepTheWordsAsSaid() {
        assertEquals(TypeGrammar.Cmd.Type("Hello there, Sam"), TypeGrammar.parse("type Hello there, Sam"))
        assertEquals(TypeGrammar.Cmd.Type("meet at 5 PM"), TypeGrammar.parse("  Write meet at 5 PM "))
        assertEquals(TypeGrammar.Cmd.Type("go home"), TypeGrammar.parse("please type go home"))   // typed, never a command
        assertEquals(TypeGrammar.Cmd.Type("send it"), TypeGrammar.parse("hey canti, type: send it"))
        assertEquals(TypeGrammar.Cmd.Type(""), TypeGrammar.parse("type"))
        assertNull(TypeGrammar.parse("typewriter sounds"))
        assertNull(TypeGrammar.parse("tap type"))
        assertNull(TypeGrammar.parse("open youtube"))
    }

    @Test fun dictationPhrases() {
        for (s in listOf("dictate", "Start dictation", "start dictating please")) assertEquals(s, TypeGrammar.Cmd.StartDictation, TypeGrammar.parse(s))
        for (s in listOf("Hey could you start dictation", "start the dictation", "turn dictation on", "can you go into dictation mode",
            "enable voice typing")) assertEquals(s, TypeGrammar.Cmd.StartDictation, TypeGrammar.parse(s))
        assertNull(TypeGrammar.parse("what is dictation"))
        assertEquals(TypeGrammar.Cmd.Type("hello"), TypeGrammar.parse("Hey could you type hello"))
        assertEquals(TypeGrammar.Cmd.StopDictation, TypeGrammar.parse("stop dictation"))
        assertEquals("see you soon", TypeGrammar.beforeStop("see you soon, stop dictation."))
        assertEquals("", TypeGrammar.beforeStop("Stop dictation"))
        assertNull(TypeGrammar.beforeStop("please stop the music"))
    }

    @Test fun spokenPunctuationBecomesSymbols() {
        assertEquals("hello, world.", Punctuation.apply("hello comma world period"))
        assertEquals("are you there?", Punctuation.apply(" are you there question mark "))
        assertEquals("Dear Sam,\nthanks", Punctuation.apply("Dear Sam comma new line thanks"))
        assertEquals("line one\nline two", Punctuation.apply("line one Newline line two"))
        assertEquals("Commas and periods stay words", Punctuation.apply("Commas and periods stay words"))
    }

    // --- inserting -------------------------------------------------------------------------------------------------

    @Test fun insertsAtTheCursorAndMovesItAfter() {
        val f = Field("Hi Sam see you", start = 6, end = 6)
        val r = TextInsert.insert(f, "you're great,")
        assertTrue(r.ok)
        assertEquals("Hi Sam you're great, see you", f.value)
        assertEquals(20, f.start); assertEquals(20, f.end)
        assertEquals(listOf("set_text", "set_selection"), f.actions)   // nothing else: no click, enter or IME action
    }

    @Test fun appendsWithNoCursorAndReplacesASelection() {
        val f = Field("Hello")
        TextInsert.insert(f, "world")
        assertEquals("Hello world", f.value)
        val g = Field("I like cats a lot", start = 7, end = 11)
        TextInsert.insert(g, "dogs")
        assertEquals("I like dogs a lot", g.value)
        val h = Field("Search", showingHint = true)
        TextInsert.insert(h, "cats")
        assertEquals("cats", h.value)
    }

    @Test fun refusesNoBoxAPasswordAndAFullBox() {
        assertEquals(TextInsert.Outcome(false, TextInsert.NO_FIELD), TextInsert.insert(null, "hi"))
        val ro = Field("label", isEditable = false)
        assertEquals(TextInsert.NO_FIELD, TextInsert.insert(ro, "hi").how)
        val pw = Field("", isPassword = true)
        assertEquals(TextInsert.PASSWORD, TextInsert.insert(pw, "hunter2").how)
        val full = Field("12345", maxLength = 6)
        assertEquals(TextInsert.FULL, TextInsert.insert(full, "678").how)
        assertTrue(ro.actions.isEmpty() && pw.actions.isEmpty() && full.actions.isEmpty())
    }

    // --- dictation -------------------------------------------------------------------------------------------------

    private class Rig(val field: Field? = Field(), logText: Boolean = false, rec: Rec = Rec()) {
        val clock = Clock(); val mic = Mic(); val rec = rec
        val logs = mutableListOf<Map<String, Any?>>()
        val stops = mutableListOf<String>()
        val window = ListenWindow(clock, null)
        val typer = object : Dictation.Typer {
            override fun refusal() = TextInsert.refusal(field)
            override fun type(text: String) = TextInsert.insert(field, text)
        }
        val d = Dictation(clock, mic, window, { rec }, typer, { logText }, { logs += it.toMap() }, { why, _ -> stops += why })
        fun events() = logs.map { it["event"] }
    }

    @Test fun eachUtteranceIsTypedWithASpaceBetween() {
        val r = Rig()
        assertNull(r.d.start("phrase"))
        assertEquals(1, r.mic.yields)
        r.clock.advance(ListenWindow.HANDOFF_MS)
        r.rec.say("Hello comma")
        r.clock.advance(Dictation.REOPEN_MS)
        r.rec.say("how are you question mark")
        r.clock.advance(Dictation.REOPEN_MS)
        r.rec.say("go home")   // typed, never a command
        assertEquals("Hello, how are you? go home", r.field!!.value)
        assertTrue(r.d.active)
        assertTrue(r.field.actions.all { it == "set_text" || it == "set_selection" })
        assertEquals(listOf("start", "utterance", "utterance", "utterance"), r.events())
        assertTrue(r.logs.none { it["text"] != null })   // the words are not logged by default
    }

    @Test fun silenceStops() {
        val r = Rig()
        r.d.start("phrase")
        r.clock.advance(ListenWindow.HANDOFF_MS)
        r.rec.say("one")
        r.clock.advance(3000)
        r.rec.listener!!.onPartial("two")   // speech restarts the silence clock
        r.clock.advance(3500)
        assertTrue(r.d.active)
        r.clock.advance(Dictation.SILENCE_MS)
        assertFalse(r.d.active)
        assertEquals(listOf("silence"), r.stops)
        assertEquals(1, r.mic.resumes)
        assertEquals(0, r.clock.pending)
        assertFalse(r.window.isOpen)
    }

    @Test fun stopPhraseTypesWhatCameBeforeIt() {
        val r = Rig(logText = true)
        r.d.start("phrase")
        r.clock.advance(ListenWindow.HANDOFF_MS)
        r.rec.say("see you soon period stop dictation")
        assertEquals("see you soon.", r.field!!.value)
        assertEquals(listOf("stop phrase"), r.stops)
        assertEquals("see you soon.", r.logs.first { it["event"] == "utterance" }["text"])   // logged only with the debug setting
        val stop = r.logs.last()
        assertEquals("stop", stop["event"]); assertEquals(13, stop["chars"])
    }

    @Test fun aSoundMidSpeechIsIgnored() {
        val r = Rig()
        r.d.start("phrase"); r.clock.advance(ListenWindow.HANDOFF_MS)
        r.clock.advance(1500)
        r.rec.listener!!.onPartial("I think")
        r.clock.advance(600)
        assertFalse(r.d.sound("pop"))   // a plosive in the words the Pico heard
        r.rec.say("I think so")
        r.clock.advance(999)
        assertFalse(r.d.sound("click"))
        assertTrue(r.d.active)
        assertEquals(2, r.logs.count { it["event"] == "ignored_sound" })
        assertEquals("I think so", r.field!!.value)
    }

    @Test fun aSoundAfterAPauseStops() {
        val r = Rig()
        r.d.start("phrase"); r.clock.advance(ListenWindow.HANDOFF_MS)
        r.rec.say("hello")
        r.clock.advance(1200)
        assertTrue(r.d.sound("pop"))
        assertEquals(listOf("sound"), r.stops)
        assertFalse(r.window.isOpen); assertEquals(1, r.mic.resumes)
        assertEquals("hello", r.field!!.value)
    }

    @Test fun aSoundExactlyAtTheHoldStops() {
        val r = Rig()
        r.d.start("phrase"); r.clock.advance(ListenWindow.HANDOFF_MS)
        r.rec.say("hello")
        r.clock.advance(Dictation.SPEECH_HOLD_MS - 1)
        assertFalse(r.d.sound("pop"))   // 999 ms: still speech
        r.clock.advance(1)
        assertTrue(r.d.sound("pop"))    // 1000 ms: a pause of at least the hold
        assertEquals(listOf("sound"), r.stops)
        // the start phrase counts as words: a sound straight after it is its tail
        val s = Rig(); s.d.start("phrase"); s.clock.advance(300)
        assertFalse(s.d.sound("pop")); assertTrue(s.d.active)
    }

    @Test fun theHoldIsASetting() {
        val c = Clock(); val rec = Rec(); val f = Field()
        val typer = object : Dictation.Typer { override fun refusal() = TextInsert.refusal(f); override fun type(text: String) = TextInsert.insert(f, text) }
        val d = Dictation(c, null, ListenWindow(c, null), { rec }, typer, { false }, {}, speechHoldMs = { 2000L })
        d.start("phrase"); c.advance(0); rec.say("hi")
        c.advance(1500); assertFalse(d.sound("pop"))
        c.advance(500); assertTrue(d.sound("pop"))
    }

    @Test fun aSoundOrTheTimeLimitStops() {
        val r = Rig()
        r.d.start("phrase")
        r.clock.advance(ListenWindow.HANDOFF_MS + Dictation.SPEECH_HOLD_MS)
        assertTrue(r.d.sound("pop"))   // no words for the hold: the sound stops it (and is not acted on)
        assertEquals(listOf("sound"), r.stops)
        assertFalse(r.window.isOpen); assertEquals(1, r.mic.resumes)
        r.d.stop("again"); assertEquals(1, r.stops.size)

        val t = Rig()
        t.d.start("phrase")
        var said = 0
        while (t.d.active && said < 200) { t.clock.advance(1000); t.rec.listener?.let { it.onPartial("word $said"); it.onFinal(Heard(listOf("word"))) }; said++ }
        assertEquals(listOf("time limit"), t.stops)
        assertTrue(t.clock.t <= Dictation.MAX_MS + 1000)
    }

    @Test fun noBoxOrPasswordRefusesToStart() {
        val none = Rig(field = null)
        assertEquals(TextInsert.NO_FIELD, none.d.start("phrase"))
        assertFalse(none.d.active); assertEquals(0, none.mic.yields); assertEquals(0, none.rec.starts)
        val pw = Rig(field = Field(isPassword = true))
        assertEquals(TextInsert.PASSWORD, pw.d.start("phrase"))
        assertTrue(pw.field!!.actions.isEmpty())
        val off = Rig(rec = Rec(unavailable = "offline speech pack missing"))
        assertEquals("offline speech pack missing", off.d.start("phrase"))
        assertEquals(0, off.mic.yields)
    }

    @Test fun theBoxGoingAwayStops() {
        var f: Field? = Field()
        val clock = Clock(); val rec = Rec(); val stops = mutableListOf<String>()
        val typer = object : Dictation.Typer {
            override fun refusal() = TextInsert.refusal(f)
            override fun type(text: String) = TextInsert.insert(f, text)
        }
        val d = Dictation(clock, null, ListenWindow(clock, null), { rec }, typer, { false }, {}, { why, _ -> stops += why })
        d.start("phrase")
        clock.advance(0)
        rec.say("first")
        f = null
        clock.advance(Dictation.REOPEN_MS)
        rec.say("second")
        assertEquals(listOf(TextInsert.NO_FIELD), stops)
        assertFalse(d.active)
    }

    @Test fun sendIsNeverPressed() {
        val f = Field("Reply:")
        TextInsert.insert(f, Punctuation.apply("send it new line"))
        val r = Rig(field = f)
        r.d.start("phrase"); r.clock.advance(ListenWindow.HANDOFF_MS)
        r.rec.say("press send"); r.clock.advance(Dictation.REOPEN_MS); r.rec.say("enter")
        assertEquals("Reply: send it\npress send enter", f.value)
        assertTrue(f.actions.all { it == "set_text" || it == "set_selection" })
    }

    @Test fun dictationReportsWordsTypedAndQuiet() {
        val clock = Clock(); val rec = Rec(); val field = Field()
        val words = mutableListOf<String>(); val typed = mutableListOf<String>(); val quiets = mutableListOf<Long>()
        val typer = object : Dictation.Typer {
            override fun refusal() = TextInsert.refusal(field)
            override fun type(text: String) = TextInsert.insert(field, text)
        }
        val d = Dictation(clock, null, ListenWindow(clock, null), { rec }, typer, { false }, {}, { _, _ -> },
            onWords = { words += it }, onTyped = { typed += it }, onQuiet = { quiets += it })
        assertNull(d.start("phrase"))
        clock.advance(ListenWindow.HANDOFF_MS)
        rec.say("hello world")
        assertTrue(words.contains("hello world"))       // the partial and the final best
        assertEquals(listOf("hello world"), typed)      // one settled utterance
        assertTrue(quiets.isNotEmpty())
        assertTrue(quiets.all { it > clock.t || it > 0 })
    }
}
