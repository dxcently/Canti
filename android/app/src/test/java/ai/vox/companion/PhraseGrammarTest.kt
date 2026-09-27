package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Spoken phrases -> commands (PhraseGrammar.kt): numbers, timers, navigation, apps, targets, n-best choice. */
class PhraseGrammarTest {
    private val apps = AppMatcher.entries(listOf(
        "com.google.android.youtube" to "YouTube",
        "com.google.android.apps.maps" to "Maps",
        "com.android.settings" to "Settings",
        "com.zhiliaoapp.musically" to "TikTok",
        "com.spotify.music" to "Spotify",
        "com.netflix.mediaclient" to "Netflix",
        "com.whatsapp" to "WhatsApp",
        "com.sec.android.app.clockpackage" to "Clock",
        "org.tasks" to "Tasks.org",
        "com.instagram.android" to "Instagram",
        "com.android.chrome" to "Chrome",
        "com.google.android.gm" to "Gmail",
        "com.facebook.katana" to "Facebook",
        "org.telegram.messenger" to "Telegram",
        "com.linkedin.android" to "LinkedIn",
    ))
    private val ctx = PhraseGrammar.Context(apps = apps)
    private fun parse(s: String, c: PhraseGrammar.Context = ctx) = PhraseGrammar.parse(s, c)
    private fun opens(s: String) = (parse(s) as? SpeechCommand.OpenApp)?.pkg

    @Test fun normalizesFillersPunctuationAndSymbols() {
        assertEquals("open youtube", PhraseGrammar.normalize("Um, could you open YouTube, please?"))
        assertEquals("tap the plus button", PhraseGrammar.normalize("Tap the + button."))
        assertEquals("set a timer for 5 min", PhraseGrammar.normalize("Hey Canti set a timer for 5min"))
        assertEquals("whats app", PhraseGrammar.normalize("What's app"))
        assertEquals("1.5 minutes", PhraseGrammar.normalize("1.5 minutes."))
    }

    @Test fun numbersInWordsAndDigits() {
        assertEquals(25.0, NumberWords.parse("twenty five")!!, 0.0)
        assertEquals(5.0, NumberWords.parse("5")!!, 0.0)
        assertEquals(120.0, NumberWords.parse("one hundred and twenty")!!, 0.0)
        assertEquals(100.0, NumberWords.parse("a hundred")!!, 0.0)
        assertEquals(1500.0, NumberWords.parse("fifteen hundred")!!, 0.0)
        assertEquals(40.0, NumberWords.parse("forty")!!, 0.0)
        assertNull(NumberWords.parse("five five"))
        assertNull(NumberWords.parse("minutes"))
    }

    @Test fun timerLengths() {
        assertEquals(300, Durations.seconds("set a timer for five minutes"))
        assertEquals(300, Durations.seconds("set a timer for 5 minutes"))
        assertEquals(300, Durations.seconds("5min timer"))
        assertEquals(600, Durations.seconds("set a 10-minute timer"))
        assertEquals(90, Durations.seconds("timer ninety seconds"))
        assertEquals(90, Durations.seconds("timer for 1.5 minutes"))
        assertEquals(5400, Durations.seconds("timer for 1 hour and 30 minutes"))
        assertEquals(5400, Durations.seconds("set a timer for an hour and a half"))
        assertEquals(1800, Durations.seconds("timer for half an hour"))
        assertEquals(150, Durations.seconds("two and a half minute timer"))
        assertEquals(60, Durations.seconds("set a timer for a minute"))
        assertEquals(1500, Durations.seconds("timer twenty five minutes"))
        assertEquals(75, Durations.seconds("timer for one minute fifteen seconds"))
        // "for"/"to" are prepositions, except straight before a unit where the number was misheard
        assertEquals(240, Durations.seconds("set a timer for minutes"))
        assertEquals(120, Durations.seconds("set a timer too minutes"))
        assertEquals(600, Durations.seconds("set a timer to 10 minutes"))
        assertNull(Durations.seconds("set a timer"))
        assertNull(Durations.seconds("set a timer for five"))
    }

    @Test fun timerCommands() {
        assertEquals(SpeechCommand.Timer(300), parse("Set a timer for 5 minutes."))
        assertEquals(SpeechCommand.Timer(180), parse("start a three minute timer please"))
        assertEquals(SpeechCommand.Timer(null), parse("set a timer"))
        assertEquals(SpeechCommand.Timer(null), parse("set a timer for 30 hours"))   // over 24 h
    }

    @Test fun navigationVariantsBecomeTheRulePhrases() {
        val cases = mapOf(
            "go back" to "go back", "back" to "go back", "Go back." to "go back", "navigate back" to "go back",
            "previous" to "the one before", "previous video" to "the one before", "go back one" to "the one before", "last one" to "the one before",
            "go home" to "go home", "take me home" to "go home", "go to the home screen" to "go home", "home" to "go home",
            "scroll down" to "scroll down", "scroll down a bit please" to "scroll down", "scroll" to "scroll down", "page down" to "scroll down",
            "scroll up" to "scroll up", "scroll up a little" to "scroll up",
            "next" to "next", "next video" to "next", "skip this" to "next", "next one" to "next",
            "pause the video" to "pause", "resume" to "play", "keep playing" to "play",
            "open camera" to "open camera", "open the camera" to "open camera", "open notifications" to "show notifications",
            "zoom in" to "zoom in",
        )
        for ((said, phrase) in cases) assertEquals(said, SpeechCommand.Nav(phrase), parse(said))
    }

    @Test fun theRulesDecideNavPhrasesWithTheScreenTieBreak() {
        // The canonical phrases are ones RuleDecider knows.
        for (p in listOf("go back", "the one before", "go home", "scroll down", "scroll up", "next", "volume up", "volume down",
                "pause", "play", "open camera", "show notifications", "recent apps")) {
            val s = Scene(mode = "listening", app = "x", appName = "x", phrase = p)
            val d = RuleDecider().decide(DecisionInput(s, Profile.empty()))
            assertTrue("$p -> ${d.action} (${d.source})", d.action != "none" && d.source == "rules:phrase")
        }
    }

    @Test fun openAppsFuzzily() {
        assertEquals("com.google.android.youtube", opens("open YouTube"))
        assertEquals("com.google.android.youtube", opens("open you tube"))
        assertEquals("com.google.android.youtube", opens("launch the youtube app"))
        assertEquals("com.zhiliaoapp.musically", opens("open tick tock"))
        assertEquals("com.netflix.mediaclient", opens("open net flicks"))
        assertEquals("com.whatsapp", opens("open what's app"))
        assertEquals("com.spotify.music", opens("start spotify"))
        assertEquals("com.google.android.apps.maps", opens("open google maps"))
        assertEquals("com.google.android.apps.maps", opens("open maps"))
        assertEquals("com.android.settings", opens("go to settings"))
        assertEquals("org.tasks", opens("open tasks"))
        // no such app: "open" may name something on the screen instead
        assertEquals(SpeechCommand.Tap("lunch box", "open"), parse("open lunch box"))
        // "start"/"launch" of nothing known goes to the phrase decider
        assertEquals(SpeechCommand.Phrase("start the video", "unparsed"), parse("start the video"))
    }

    @Test fun tapCommandsAndMisrecognitions() {
        assertEquals(SpeechCommand.Tap("settings", "click"), parse("click on settings"))
        assertEquals(SpeechCommand.Tap("plus button", "tap"), parse("tap the plus button"))
        assertEquals(SpeechCommand.Tap("plus button", "tap"), parse("Tap the + button"))
        assertEquals(SpeechCommand.Tap("ok", "press"), parse("press OK"))
        assertEquals(SpeechCommand.Tap("compose", "tab"), parse("tab compose"))   // "tap" heard as "tab"
        assertEquals(SpeechCommand.Tap("search", "select"), parse("select the search"))
    }

    @Test fun unknownTextGoesToThePhraseDeciderAndUserRulesComeFirst() {
        assertEquals(SpeechCommand.Phrase("zoom out a lot", "unparsed"), parse("Zoom out a lot!"))
        assertEquals(SpeechCommand.Ignore("chatter"), parse("What's the weather?"))
        val c = ctx.copy(userPhrases = setOf("next"))
        assertEquals(SpeechCommand.Phrase("next", "user phrase rule"), parse("next", c))
        assertEquals(SpeechCommand.Ignore("empty"), parse("  ...  "))
    }

    @Test fun cursorModePhrasesNameElements() {
        val c = ctx.copy(cursor = true)
        assertEquals(SpeechCommand.Tap("compose", null), parse("compose", c))
        assertEquals(SpeechCommand.Tap("new message", null), parse("the new message", c))
        // a bare word is an element first, the command if nothing on screen matches
        assertEquals(SpeechCommand.Tap("home", null, SpeechCommand.Nav("go home")), parse("home", c))
        // explicit commands still work
        assertEquals("com.google.android.youtube", (parse("open youtube", c) as SpeechCommand.OpenApp).pkg)
        assertEquals(SpeechCommand.Nav("go back"), parse("go back", c))
        assertEquals(SpeechCommand.Timer(60), parse("set a timer for one minute", c))
    }

    @Test fun nBestPrefersAConcreteCommand() {
        val p = PhraseGrammar.choose(Heard(listOf("open you", "open youtube", "open you tube")), ctx)
        assertEquals(1, p.index); assertTrue(p.command is SpeechCommand.OpenApp)
        val t = PhraseGrammar.choose(Heard(listOf("set a timer for", "set a timer for four minutes")), ctx)
        assertEquals(SpeechCommand.Timer(240), t.command)
        // nothing concrete: the recognizer's first
        val u = PhraseGrammar.choose(Heard(listOf("zoom out a lot", "zoom out a log")), ctx)
        assertEquals(0, u.index); assertEquals(SpeechCommand.Phrase("zoom out a lot", "unparsed"), u.command)
        // taps: the hypothesis that names something on screen
        val onScreen = setOf("settings")
        val s = PhraseGrammar.choose(Heard(listOf("tap sittings", "tap settings")), ctx) { q -> if (q in onScreen) 1.0 else 0.0 }
        assertEquals(1, s.index)
        assertEquals(-1, PhraseGrammar.choose(Heard(emptyList()), ctx).index)
    }

    // --- messy speech: fillers, hesitations, corrections, repeats, chatter ------------------------------------------

    private val YT = "com.google.android.youtube"; private val IG = "com.instagram.android"; private val SP = "com.spotify.music"
    private fun nav(p: String) = SpeechCommand.Nav(p)
    private fun app(pkg: String) = Expect.App(pkg)
    private fun tap(q: String) = Expect.TapOf(q)
    private val IGNORE = Expect.Nothing
    private sealed class Expect {
        data class App(val pkg: String) : Expect()
        data class TapOf(val query: String) : Expect()
        object Nothing : Expect()
    }

    /** said -> expected: a command, an app, a tap on a query (any verb), or nothing at all. */
    private fun check(cases: List<Pair<String, Any>>, c: PhraseGrammar.Context = ctx) {
        val bad = cases.mapNotNull { (said, want) ->
            val got = parse(said, c)
            val ok = when (want) {
                is Expect.App -> (got as? SpeechCommand.OpenApp)?.pkg == want.pkg
                is Expect.TapOf -> got is SpeechCommand.Tap && got.query == want.query
                Expect.Nothing -> got is SpeechCommand.Ignore
                else -> got == want
            }
            if (ok) null else "\"$said\": want $want, got ${got.describe()}"
        }
        assertTrue(bad.joinToString("\n", "\n"), bad.isEmpty())
    }

    @Test fun fillersAndHesitationsAroundTheCommand() = check(listOf(
        "um so can you like uh scroll down a bit" to nav("scroll down"),
        "okay open uh… instagram please" to app(IG),
        "could you maybe go back" to nav("go back"),
        "uh uh tap the the search" to tap("search"),
        "hey canti open youtube" to app(YT),
        "uh, go home" to nav("go home"),
        "er... next" to nav("next"),
        "hmm, scroll up a little" to nav("scroll up"),
        "can you, like, go back?" to nav("go back"),
        "go back please, thanks" to nav("go back"),
        "you know, open spotify" to app(SP),
        "so yeah go back" to nav("go back"),
        "alright then scroll down" to nav("scroll down"),
        "scroll down a bit more please" to nav("scroll down"),
        "open youtube for me real quick" to app(YT),
    ))

    @Test fun politenessRequestsAndTheWakeWord() = check(listOf(
        "would you mind scrolling down" to nav("scroll down"),
        "could you please open gmail for me" to app("com.google.android.gm"),
        "I want you to go home" to nav("go home"),
        "hey candy, open youtube" to app(YT),              // the wake word misheard
        "ok canti, next video" to nav("next"),
        "would you kindly press the search" to tap("search"),
        "go ahead and tap settings" to tap("settings"),
        "i need to set a timer for ten minutes" to SpeechCommand.Timer(600),
        "okay so I want you to open settings" to app("com.android.settings"),
        "I'm gonna go home" to nav("go home"),
    ))

    @Test fun selfCorrectionsKeepTheLastCommand() = check(listOf(
        "go back — no wait, home" to nav("go home"),
        "open youtube, no wait, spotify" to app(SP),       // the correction borrows "open"
        "tap settings, sorry, search" to tap("search"),
        "go back, actually go home" to nav("go home"),
        "scroll down, I mean up" to nav("scroll up"),
        "scroll up, sorry, down" to nav("scroll down"),
        "no no, go home" to nav("go home"),
        "go back, no wait, never mind" to IGNORE,
        "open settings, never mind" to IGNORE,
        "tap no" to tap("no"),                               // "no" is the button here, not a correction
        "press wait" to tap("wait"),
        "tap okay" to tap("okay"),
        "select yes" to tap("yes"),
    ))

    @Test fun repeatsCountOnce() = check(listOf(
        "scroll down scroll down" to nav("scroll down"),
        "go back go back" to nav("go back"),
        "next next next" to nav("next"),
        "open youtube open youtube" to app(YT),
        "tap tap the search" to tap("search"),
        "go back, back" to nav("go back"),
    ))

    @Test fun twoDifferentCommandsAreRefusedNotGuessed() {
        check(listOf(
            "scroll down and go home" to IGNORE,
            "open youtube then go back" to IGNORE,
            "go back go home" to IGNORE,
            "tap settings and then scroll down" to IGNORE,
            "set a timer for five minutes and go home" to IGNORE,
            // "and" inside one command is not two
            "set a timer for an hour and a half" to SpeechCommand.Timer(5400),
            "set a timer for five minutes and thirty seconds" to SpeechCommand.Timer(330),
            "tap terms and conditions" to tap("terms and conditions"),
            "go back home" to nav("go home"),
            "open youtube and spotify" to IGNORE,              // the second app shares the verb
            "go to youtube and then spotify" to IGNORE,
            "open terms and conditions" to tap("terms and conditions"),
        ))
        assertTrue((parse("scroll down and go home") as SpeechCommand.Ignore).why.startsWith("two commands"))
    }

    @Test fun chatterAndFillerDoNothing() {
        check(listOf(
            "um okay yeah" to IGNORE, "what was I doing" to IGNORE, "what's the weather like" to IGNORE,
            "I was going to press it later" to IGNORE,   // a tap verb in a remark is not a tap
            "I opened it yesterday" to IGNORE, "is it paused" to IGNORE, "that's so funny" to IGNORE,
            "how long is left on the timer" to IGNORE, "yeah no" to IGNORE, "thank you" to IGNORE, "no" to IGNORE,
            "hey canti" to IGNORE, "um um um" to IGNORE, "" to IGNORE, "please" to IGNORE, "hmm, wait" to IGNORE,
        ))
        // no verb, no tap: a bare name outside cursor mode is for the phrase decider, never a tap
        for (s in listOf("banana phone", "the search", "settings", "top of the page", "tap the", "tap", "open")) assertTrue(s, parse(s) !is SpeechCommand.Tap)
        // an explicit like names what is liked ("like this video"); it still waits for a confirm pop (Outward)
        assertEquals(nav(PhraseGrammar.LIKE), parse("like this video"))
        check(listOf("okay google, open youtube" to app(YT), "open you too" to app(YT), "wait, go back" to nav("go back")))
    }

    @Test fun numberWordsInMessyTimers() = check(listOf(
        "set a timer for twenty five minutes" to SpeechCommand.Timer(1500),
        "uh set a timer for, um, five minutes" to SpeechCommand.Timer(300),
        "timer for a minute and a half" to SpeechCommand.Timer(90),
        "set a timer for two hours please" to SpeechCommand.Timer(7200),
        "set a timer for 90 seconds" to SpeechCommand.Timer(90),
        "could you set a three minute timer" to SpeechCommand.Timer(180),
        "set a timer for fifteen" to SpeechCommand.Timer(null),
    ))

    @Test fun appNameVariantsAndMishearings() = check(listOf(
        "open insta gram" to app(IG), "open insta" to app(IG), "launch g mail" to app("com.google.android.gm"),
        "open crome" to app("com.android.chrome"), "open you tube" to app(YT), "lunch spotify" to app(SP),
        "open face book" to app("com.facebook.katana"), "open what's up" to app("com.whatsapp"),
        "open net flicks" to app("com.netflix.mediaclient"), "open the camera app" to nav("open camera"),
        "open maps please" to app("com.google.android.apps.maps"),
    ))

    @Test fun misheardVerbs() = check(listOf(
        "top the search" to tap("search"), "top on settings" to tap("settings"), "klick settings" to tap("settings"),
        "tab compose" to tap("compose"), "school down" to nav("scroll down"),
    ))

    @Test fun cursorModeStillIgnoresHesitationButNamesOkButtons() {
        val c = ctx.copy(cursor = true)
        check(listOf("ok" to tap("ok"), "um compose" to tap("compose"), "uh uh" to IGNORE, "the the new message" to tap("new message")), c)
    }

    @Test fun nBestNeverTurnsChatterIntoATap() {
        val p = PhraseGrammar.choose(Heard(listOf("what was I doing", "what was I doing it")), ctx) { 1.0 }
        assertTrue(p.command.describe(), p.command is SpeechCommand.Ignore)
        // a real command in the n-best still wins over filler
        val q = PhraseGrammar.choose(Heard(listOf("um yeah", "um go back")), ctx)
        assertEquals(nav("go back"), q.command)
    }

    // --- targets ---------------------------------------------------------------------------------------------------

    private fun t(label: String, role: String, pos: String) = Target(label, role, pos, 0, 0, 10, 10)
    private val screen = listOf(
        t("Search", "button", "top"), t("Settings", "button", "top right"), t("More options", "button", "top right"),
        t("Add task", "button", "bottom right"), t("Inbox", "tab", "bottom left"), t("Today", "tab", "bottom"),
        t("5", "button", "center"), t("unlabeled", "button", "left"),
    )
    private fun tapped(q: String, targets: List<Target> = screen) = (TargetMatcher.match(targets, q) as? Targets.Outcome.Tap)?.target?.label

    @Test fun targetsByNameSynonymAndMisspelling() {
        assertEquals("Add task", tapped("plus button"))
        assertEquals("Add task", tapped("the + button"))
        assertEquals("Settings", tapped("settings"))
        assertEquals("Settings", tapped("setting"))
        assertEquals("More options", tapped("menu"))
        assertEquals("More options", tapped("three dots"))
        assertEquals("Search", tapped("search bar"))
        assertEquals("Today", tapped("today tab"))
        assertEquals("5", tapped("five"))
        assertEquals("Inbox", tapped("in box"))
    }

    @Test fun weakOrAmbiguousMatchesAskAndUnknownIsNotOnScreen() {
        // a place only: never tapped on its own, the candidates are highlighted
        val c = TargetMatcher.match(screen, "the button at the top right")
        assertTrue(c.toString(), c is Targets.Outcome.Choose)
        assertEquals(setOf("Settings", "More options"), (c as Targets.Outcome.Choose).targets.map { it.label }.toSet())
        // two elements with the same name
        val twice = listOf(t("Add", "button", "top left"), t("Add", "button", "bottom right"))
        assertTrue(TargetMatcher.match(twice, "add") is Targets.Outcome.Choose)
        // ... and the place picks one
        assertEquals("bottom right", (TargetMatcher.match(twice, "add at the bottom right") as Targets.Outcome.Tap).target.position)
        assertEquals(Targets.Outcome.NotOnScreen, TargetMatcher.match(screen, "banana"))
        assertEquals(Targets.Outcome.NotOnScreen, TargetMatcher.match(emptyList(), "settings"))
        assertEquals(Targets.Outcome.NotOnScreen, TargetMatcher.match(screen, "unlabeled"))
    }

    @Test fun fuzzyHelpers() {
        assertEquals(Fuzzy.phonetic("netflix"), Fuzzy.phonetic("net flicks"))
        assertEquals(Fuzzy.phonetic("tiktok"), Fuzzy.phonetic("tick tock"))
        assertEquals(3, Fuzzy.levenshtein("kitten", "sitting"))
        assertEquals(1.0, AppMatcher.score("you tube", "YouTube"), 0.0)
        assertNull(AppMatcher.best("you", apps))
    }

    // --- smart volume (Volume.kt) ------------------------------------------------------------------------------------

    private fun vol(op: VolOp, s: VolStream = VolStream.AUTO) = SpeechCommand.Volume(s, op)
    private fun up(n: Int, exact: Boolean = false) = VolOp.Step(n, 1, exact)
    private fun down(n: Int, exact: Boolean = false) = VolOp.Step(n, -1, exact)

    @Test fun volumeStepsAndAmounts() = check(listOf(
        "louder" to vol(up(1)), "turn it up" to vol(up(1)), "volume up" to vol(up(1)), "make it louder" to vol(up(1)),
        "turn it up a bit" to vol(up(1, exact = true)), "a little louder" to vol(up(1, exact = true)),
        "a lot louder" to vol(up(3)), "way louder" to vol(up(3)), "much louder" to vol(up(3)), "crank it up" to vol(up(4)),
        "louder louder" to vol(up(2)), "louder louder louder" to vol(up(3)),
        "quieter" to vol(down(1)), "turn the volume down" to vol(down(1)), "turn it down a lot" to vol(down(3)),
        "volume up by 3" to vol(up(3, exact = true)), "turn it up two steps" to vol(up(2, exact = true)),
        "volume down 2" to vol(down(2, exact = true)),
        "turn it up by 20 percent" to vol(VolOp.Step(0, 1, fraction = 0.2)),
    ))

    @Test fun volumeExactLevels() = check(listOf(
        "volume to 30 percent" to vol(VolOp.Set(fraction = 0.3)), "set the volume to 30%" to vol(VolOp.Set(fraction = 0.3)),
        "half volume" to vol(VolOp.Set(fraction = 0.5)), "volume 5" to vol(VolOp.Set(index = 5)), "volume five" to vol(VolOp.Set(index = 5)),
        "max volume" to vol(VolOp.Set(fraction = 1.0)), "full volume" to vol(VolOp.Set(fraction = 1.0)),
        "turn it all the way up" to vol(VolOp.Set(fraction = 1.0)), "volume to minimum" to vol(VolOp.Lowest),
        "turn it all the way down" to vol(VolOp.Lowest), "set volume to seven out of ten" to vol(VolOp.Set(fraction = 0.7)),
        "volume to zero" to vol(VolOp.Mute),
    ))

    @Test fun volumeMuteAndUnmute() = check(listOf(
        "mute" to vol(VolOp.Mute), "silence it" to vol(VolOp.Mute), "shh" to vol(VolOp.Mute), "shhh" to vol(VolOp.Mute),
        "unmute" to vol(VolOp.Unmute), "sound back on" to vol(VolOp.Unmute), "turn the sound back on" to vol(VolOp.Unmute),
        "un mute it" to vol(VolOp.Unmute),
    ))

    @Test fun volumeStreamsByName() = check(listOf(
        "turn the ringer up" to vol(up(1), VolStream.RING), "ring volume down" to vol(down(1), VolStream.RING),
        "alarm volume to max" to vol(VolOp.Set(fraction = 1.0), VolStream.ALARM),
        "mute notifications" to vol(VolOp.Mute, VolStream.NOTIFICATION),
        "turn the music down" to vol(down(1), VolStream.MUSIC), "media volume half" to vol(VolOp.Set(fraction = 0.5), VolStream.MUSIC),
        "call volume up" to vol(up(1), VolStream.CALL),
    ))

    @Test fun volumeFromComplaints() = check(listOf(
        "it's too loud" to vol(down(1)), "that's way too quiet" to vol(up(3)), "it's a bit too loud" to vol(down(1, exact = true)),
        "I can't hear it" to vol(up(1)), "I can't hear anything" to vol(up(3)), "this hurts my ears" to vol(down(3)),
        "too quiet" to vol(up(1)),
    ))

    @Test fun volumeThroughFillersAndCorrections() = check(listOf(
        "um can you like turn it up a bit" to vol(up(1, exact = true)), "uh make it louder please" to vol(up(1)),
        "could you turn the volume down a little for me" to vol(down(1, exact = true)), "turn it up like a lot" to vol(up(3)),
        "hey canti, louder" to vol(up(1)), "turn it up, no, down" to vol(down(1)),
    ))

    @Test fun volumeWordsElsewhereDoNotChangeTheVolume() {
        check(listOf(
            "that song is so loud lol" to IGNORE, "is it too loud" to IGNORE, "it's not too loud" to IGNORE,
            "I turned it up already" to IGNORE,
            "tap the mute button" to tap("mute button"), "like button" to tap("like button"),
        ))
        for (s in listOf("open volume booster", "set the alarm to 7", "silence the alarm", "tap volume", "go right ahead", "the music was louder yesterday"))
            assertTrue(s, parse(s) !is SpeechCommand.Volume)
        // cursor mode: a bare "mute" names a Mute button first, the volume is the fallback
        assertEquals(SpeechCommand.Tap("mute", null, vol(VolOp.Mute)), parse("mute", ctx.copy(cursor = true)))
    }

    // --- smart swipes (Swipes.kt) ------------------------------------------------------------------------------------

    private fun finger(a: String, n: Int = 1) = SpeechCommand.Swipe(a, null, n, "finger")
    private fun content(a: String, n: Int = 1) = SpeechCommand.Swipe(a, null, n, "content")
    private fun sem(next: Boolean, noun: String, n: Int = 1) = SpeechCommand.Swipe(null, if (next) "next" else "previous", n, noun)

    @Test fun swipeDirectionsFingerAndContent() = check(listOf(
        // a swipe word names the finger
        "swipe right" to finger("swipe_right"), "swipe to the right" to finger("swipe_right"), "swipe it right" to finger("swipe_right"),
        "flick right" to finger("swipe_right"), "swipe left" to finger("swipe_left"), "swipe right on it" to finger("swipe_right"),
        "swipe up" to finger("swipe_up"),
        // a content word names what to bring into view: the finger goes the other way
        "scroll right" to content("swipe_left"), "go right" to content("swipe_left"), "move left" to content("swipe_right"),
        "see what's on the right" to content("swipe_left"), "what's on the left" to content("swipe_right"),
        "scroll right a bit" to content("swipe_left"),
    ))

    @Test fun swipeCountsRepeatUpToFive() = check(listOf(
        "swipe right twice" to finger("swipe_right", 2), "swipe left three times" to finger("swipe_left", 3),
        "flick left twice" to finger("swipe_left", 2), "swipe right 10 times" to finger("swipe_right", 5),
        "swipe right swipe right" to finger("swipe_right", 2), "go right twice" to content("swipe_left", 2),
    ))

    @Test fun swipeNextAndPreviousByNoun() = check(listOf(
        "next photo" to sem(true, "photo"), "previous picture" to sem(false, "picture"), "next slide" to sem(true, "slide"),
        "next story" to sem(true, "story"), "last photo" to sem(false, "photo"), "next page" to sem(true, "page"),
        "go back one photo" to sem(false, "photo"), "go three photos forward" to sem(true, "photo", 3),
        "go forward two pictures" to sem(true, "picture", 2), "back three slides" to sem(false, "slide", 3),
        "the next three pictures" to sem(true, "picture", 3), "skip two" to sem(true, "", 2), "skip two photos" to sem(true, "photo", 2),
        "show me the previous tab" to sem(false, "tab"),
        // one ordinary item keeps the plain nav phrase and its screen tie-break
        "next video" to nav("next"), "previous video" to nav("the one before"), "show me the next one" to nav("next"),
        "next one" to nav("next"), "the one before" to nav("the one before"), "go back one" to nav("the one before"),
    ))

    @Test fun swipeThroughFillersCorrectionsAndChatter() = check(listOf(
        "um can you like swipe to the uh next picture" to sem(true, "picture"),
        "swipe left — no, right" to finger("swipe_right"), "uh swipe right please" to finger("swipe_right"),
        "could you flick left for me" to finger("swipe_left"),
        "I swiped right on her lol" to IGNORE, "I swiped left yesterday" to IGNORE, "that swipe was so smooth" to IGNORE,
        "right" to IGNORE, "you're right" to IGNORE,
    ))

    @Test fun swipeWordsElsewhereAreNotSwipes() {
        for (s in listOf("go right ahead", "turn right", "right now", "all right")) assertTrue(s, parse(s) !is SpeechCommand.Swipe)
    }

    // --- "like" is filler unless the like is explicit (like is outward: it always needs a confirm pop too) -----------

    private fun likes(c: SpeechCommand): Boolean = c == nav(PhraseGrammar.LIKE) || c == nav("heart it") ||
        (c is SpeechCommand.Tap && (c.fallback == nav(PhraseGrammar.LIKE) || "like" in c.query.split(' '))) ||
        (c is SpeechCommand.Phrase && "like" in c.text.split(' '))

    @Test fun fillerLikeNeverLikes() {
        val said = listOf("like this", "like that", "like", "like, like, you know", "like this is so cool", "so like this",
            "like, uh, this", "like like this", "like this one is funny", "i like this", "i like this song", "like what",
            "it's like this big", "like the one before", "do it like this", "like, scroll down", "um like go home",
            "can you like open youtube", "scroll down like this", "turn it up like a lot", "go back like", "open like youtube",
            "like, next", "you know like", "like whatever", "and like this", "like so", "yeah like that")
        val bad = said.map { it to parse(it) }.filter { likes(it.second) }
        assertTrue(bad.joinToString("\n", "\n") { "\"${it.first}\" -> ${it.second.describe()}" }, bad.isEmpty())
        check(listOf(
            "like this" to IGNORE, "like that" to IGNORE, "like" to IGNORE, "so like this" to IGNORE, "like like this" to IGNORE,
            "like, scroll down" to nav("scroll down"), "um like go home" to nav("go home"), "can you like open youtube" to app(YT),
            "scroll down like this" to nav("scroll down"), "open like youtube" to app(YT), "like, next" to nav("next"),
            "i like this song" to IGNORE, "like this is so cool" to IGNORE,
        ))
    }

    @Test fun explicitLikesAreRecognised() {
        for (s in listOf("like this post", "like the video", "like this photo", "like it", "heart it", "heart this", "please like this reel",
                "um can you like this post")) assertEquals(s, nav(PhraseGrammar.LIKE), parse(s))
        // the like button on the screen, else the like action
        assertEquals(SpeechCommand.Tap("like", "hit", nav(PhraseGrammar.LIKE)), parse("hit like"))
        assertEquals(SpeechCommand.Tap("like button", "tap", nav(PhraseGrammar.LIKE)), parse("tap the like button"))
        assertEquals(SpeechCommand.Tap("like", "press", nav(PhraseGrammar.LIKE)), parse("press like"))
        assertEquals("like button", (parse("um tap the uh like button", ctx.copy(cursor = true)) as SpeechCommand.Tap).query)
    }

    // --- softeners: at the edges or next to a command word, never inside an argument ----------------------------------

    @Test fun softWordsAtTheEdgesOnly() {
        check(listOf(
            "tap maybe later" to tap("maybe later"), "press maybe later please" to tap("maybe later"),
            "tap the maybe later button" to tap("maybe later button"),
            "scroll down quickly" to nav("scroll down"), "maybe scroll down" to nav("scroll down"), "please go back" to nav("go back"),
            "can you maybe open youtube" to app(YT), "scroll quickly down" to nav("scroll down"),
            "scroll down quickly for me" to nav("scroll down"), "basically go home" to nav("go home"),
            "open youtube please quickly" to app(YT),
        ))
        assertEquals(SpeechCommand.Tap("maybe later", null), parse("maybe later", ctx.copy(cursor = true)))
        assertEquals(SpeechCommand.Tap("maybe", "tap"), parse("tap maybe"))
    }

    // --- round 3 (Z Flip): real speech ---------------------------------------------------------------------------

    private val TG = "org.telegram.messenger"; private val LI = "com.linkedin.android"

    @Test fun round3FragmentsFillersAndCorrections() = check(listOf(
        "Hmm, let's see, uh, pause the video" to nav("pause"),
        "Scroll d-, scroll down" to nav("scroll down"),
        "Open Tele-, Telegram" to app(TG),
        "Uh, can you open, um, what's it called, LinkedIn" to app(LI),
        "open, what is it called, spotify" to app(SP),
        "Open Facebook, sorry, I mean Instagram" to app(IG),
        "open youtube, no wait, spotify" to app(SP),
        "Set a timer for ten, no, fifteen minutes" to SpeechCommand.Timer(900),
        "set a timer for five minutes, sorry, ten" to SpeechCommand.Timer(600),
        "scroll down, i mean up" to nav("scroll up"),
        "Timer for one minute thirty" to SpeechCommand.Timer(90),
        "timer for an hour and fifteen" to SpeechCommand.Timer(4500),
        "timer for two minutes thirty seconds" to SpeechCommand.Timer(150),
        "timer for one minute" to SpeechCommand.Timer(60),
    ))

    @Test fun cutOffWordsGoHyphenatedWordsStay() {
        assertEquals("scroll scroll down", PhraseGrammar.basic("Scroll d-, scroll down"))
        assertEquals("turn on wi fi", PhraseGrammar.basic("turn on Wi-Fi"))
        assertEquals("tap check in", PhraseGrammar.basic("tap check-in"))
    }

    @Test fun goBackToAndSwitchToOpenTheApp() = check(listOf(
        "go back to instagram" to app(IG),
        "switch to telegram" to app(TG),
        "switch back to youtube" to app(YT),
        "return to spotify" to app(SP),
        "back to whatsapp" to app("com.whatsapp"),
        "go back" to nav("go back"),
        "go back to the home screen" to nav("go home"),
    ))

    @Test fun anAppThatIsNotInstalledIsSaidNeverTapped() {
        assertEquals(SpeechCommand.AppMissing("snapchat"), parse("open snapchat"))
        assertEquals(SpeechCommand.AppMissing("snapchat"), parse("switch to snapchat"))
        assertEquals(SpeechCommand.AppMissing("pinterest"), parse("launch pinterest"))
        assertEquals(SpeechCommand.AppMissing("discord"), parse("can you open discord please"))
        assertEquals("no app called snapchat", parse("open snapchat").describe())
        // an unknown name after an app-only verb is not a tap either
        assertTrue(parse("launch the zorblax") !is SpeechCommand.Tap)
        assertTrue(parse("switch to zorblax") !is SpeechCommand.Tap)
        // "open" + a thing that is no app's name stays a tap (in-app items: "open settings" in an app, "open messages")
        assertEquals(SpeechCommand.Tap("zorblax", "open"), parse("open zorblax"))
        assertEquals(SpeechCommand.Tap("messages", "open"), parse("open messages"))
        assertEquals(SpeechCommand.Tap("lunch box", "open"), parse("open lunch box"))
    }

    @Test fun twoAppsWithOneNameCarryTheOthersForTheServiceToPick() {
        val two = ctx.copy(apps = AppMatcher.entries(listOf(YT to "YouTube", "app.revanced.android.youtube" to "YouTube", SP to "Spotify")))
        val c = parse("Hey Canti, open YouTube", two) as SpeechCommand.OpenApp
        val all = listOf(c.pkg) + c.others
        assertEquals(setOf(YT, "app.revanced.android.youtube"), all.toSet())
        assertEquals(YT, AppChoice.pick(all, null))                                         // no usage access: the official one
        assertEquals("app.revanced.android.youtube", AppChoice.pick(all, mapOf(YT to 1L, "app.revanced.android.youtube" to 9L)))
        assertTrue((parse("open spotify", two) as SpeechCommand.OpenApp).others.isEmpty())
    }

    @Test fun volumeAndLikesFromRound3() {
        assertTrue(parse("turn it down a little") is SpeechCommand.Volume)
        assertTrue(parse("Um, could you, like, turn it down a little") is SpeechCommand.Volume)
        assertEquals(nav(PhraseGrammar.LIKE), parse("heart it"))                            // explicit: confirmed before it runs
        assertTrue(parse("like this") != nav(PhraseGrammar.LIKE))
    }

    @Test fun loneDownUpAndRepeatCounts() {
        // user decision: a lone direction scrolls only in a listen window opened on purpose (pop pop, then speech)
        val window = ctx.copy(window = true)
        assertEquals(nav("scroll down"), parse("down", window))
        assertEquals(nav("scroll up"), parse("Up.", window))
        assertEquals(nav("scroll down"), parse("um, down", window))
        assertEquals(SpeechCommand.Tap("down", null, nav("scroll down")), parse("down", window.copy(cursor = true)))
        // anywhere else (an always-listening mic) it needs a verb: nothing happens, never the phrase decider
        assertTrue(parse("down") is SpeechCommand.Ignore)
        assertTrue(parse("up") is SpeechCommand.Ignore)
        assertEquals(SpeechCommand.Tap("down", null, null), parse("down", ctx.copy(cursor = true)))
        for (c in listOf(ctx, window)) {
            assertEquals(nav("scroll down"), parse("scroll down", c)); assertEquals(nav("scroll down"), parse("go down", c))
            assertEquals(nav("scroll up"), parse("go up a bit", c)); assertEquals(nav("scroll up"), parse("move up", c))
            assertTrue(parse("turn it up, no, down", c) is SpeechCommand.Volume)   // a correction's direction is no scroll
        }
        assertEquals(nav("scroll down"), PhraseGrammar.choose(Heard(listOf("down")), window).command)
        assertTrue(PhraseGrammar.choose(Heard(listOf("down")), ctx).command is SpeechCommand.Ignore)
        assertEquals(SpeechCommand.Nav("scroll down", 3), parse("scroll down three times"))
        assertEquals(SpeechCommand.Nav("scroll up", 2), parse("scroll up twice"))
        assertEquals(SpeechCommand.Nav("next", 2), parse("next twice"))
        assertEquals(SpeechCommand.Nav("scroll down", SwipeGrammar.MAX_COUNT), parse("scroll down twenty times"))
        assertEquals(SpeechCommand.Nav("go home", 1), parse("go home three times"))             // only scrolls and next/previous repeat
        assertEquals("nav \"scroll down\" x3", parse("scroll down three times").describe())
    }

    /** "next video", "previous one", "skip this" on Reels, Shorts and TikTok (SwipePlan: a vertical fling there). */
    @Test fun feedPhrasings() = check(listOf(
        "next reel" to SpeechCommand.Swipe(null, "next", 1, "reel"),
        "next short" to SpeechCommand.Swipe(null, "next", 1, "short"),
        "skip this reel" to SpeechCommand.Swipe(null, "next", 1, "reel"),
        "previous short" to SpeechCommand.Swipe(null, "previous", 1, "short"),
        "go back one video" to nav("the one before"),
        "next video" to nav("next"),
        "previous one" to nav("the one before"),
        "skip this" to nav("next"),
        "skip this video" to nav("next"),
        "skip" to nav("next"),
        "next tiktok" to SpeechCommand.Swipe(null, "next", 1, "tiktok"),
    ))

    /** Phrasings the user said again and again in the recording session (Whisper transcripts). */
    @Test fun recordingSessionPhrasings() = check(listOf(
        "set timer for five minutes" to SpeechCommand.Timer(300),
        "Set timer for 5 minutes." to SpeechCommand.Timer(300),
        "hold on a second" to nav("pause"),
        "hold on a sec" to nav("pause"),
        "hold on" to nav("pause"),
        "open youtube, I meant instagram" to app(IG),
        "scroll down, sorry, I meant up" to nav("scroll up"),
        "open up Instagram" to app(IG),
        "please open Instagram" to app(IG),
        "hey, open Instagram" to app(IG),
        "open open Instagram" to app(IG),
        "Open, open Instagram." to app(IG),
        "click on the search button" to tap("search button"),
        "click on the search bar" to tap("search bar"),
        "click on the the search bar" to tap("search bar"),
        "skip video" to nav("next"),
        "skip this video" to nav("next"),
        "go back to the previous screen" to nav("go back"),
        "go back to the last screen" to nav("go back"),
        "go back to the previous page" to nav("go back"),
        "pause, please" to nav("pause"),
        "Pause please." to nav("pause"),
        // "three thirty" in a timer: 3 min 30 s (a timer is a length, never a clock time)
        "set a timer for three thirty" to SpeechCommand.Timer(210),
        "timer for two fifteen" to SpeechCommand.Timer(135),
        "timer for one forty five" to SpeechCommand.Timer(105),
        "set a timer for 3 30" to SpeechCommand.Timer(210),
        "set a timer for thirty" to SpeechCommand.Timer(null),
    ))

    @Test fun recordingPhrasingsDoNotCollide() {
        assertTrue(parse("go back to the previous screen") !is SpeechCommand.OpenApp)
        assertTrue(parse("go back to the previous screen") !is SpeechCommand.AppMissing)
        assertEquals(SpeechCommand.Tap("search", "tap"), parse("tap on search"))
        assertTrue(parse("hold on a second timer") is SpeechCommand.Timer)       // "timer" wins: never a pause
        assertEquals(SpeechCommand.Timer(90), parse("timer for one minute thirty"))
        assertEquals(SpeechCommand.Timer(900), parse("set a timer for ten, no, fifteen minutes"))
        assertEquals(nav("scroll down"), parse("scroll scroll down"))
    }
}
