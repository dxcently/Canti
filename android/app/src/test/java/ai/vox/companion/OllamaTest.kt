package ai.vox.companion

import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.ServerSocket
import java.net.SocketTimeoutException
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.concurrent.thread

/**
 * A fake Ollama /api/chat on loopback. [reply] builds (status, body) from the request body; [delayMs] holds the
 * answer back (for timeouts and cancellation). Every request's headers and body are kept.
 */
private class FakeOllama(var delayMs: Long = 0, var reply: (JSONObject) -> Pair<Int, String> = { 200 to chat("t0") }, var contentType: String = "application/json") : AutoCloseable {
    val server = ServerSocket(0, 20, java.net.InetAddress.getLoopbackAddress())
    val bodies = CopyOnWriteArrayList<JSONObject>()
    val headers = CopyOnWriteArrayList<List<String>>()
    val base get() = "http://127.0.0.1:${server.localPort}"

    init {
        thread(isDaemon = true) {
            while (!server.isClosed) {
                val sock = try { server.accept() } catch (e: Exception) { break }
                thread(isDaemon = true) {
                    sock.use { s ->
                        try {
                            val inp = s.getInputStream().bufferedReader()
                            val h = generateSequence { inp.readLine() }.takeWhile { it.isNotEmpty() }.toList()
                            val len = h.first { it.startsWith("Content-Length", true) }.substringAfter(":").trim().toInt()
                            val buf = CharArray(len); var got = 0
                            while (got < len) got += inp.read(buf, got, len - got)
                            val body = JSONObject(String(buf))
                            headers += h; bodies += body
                            if (delayMs > 0) Thread.sleep(delayMs)
                            val (code, out) = reply(body)
                            val bytes = out.toByteArray()
                            s.getOutputStream().write(("HTTP/1.1 $code X\r\nContent-Type: $contentType\r\nContent-Length: ${bytes.size}\r\n" +
                                "Connection: close\r\n\r\n").toByteArray() + bytes)
                        } catch (_: Exception) {}
                    }
                }
            }
        }
    }

    override fun close() = server.close()

    companion object {
        fun chat(content: String) = JSONObject().put("model", "m").put("done", true)
            .put("message", JSONObject().put("role", "assistant").put("content", content))
            .put("prompt_eval_count", 230).put("eval_count", 3).toString()
    }
}

class OllamaTest {
    private val key = "sk-ollama-SECRET-4f9a"
    private val logged = CopyOnWriteArrayList<String>()
    private val listener: (JSONObject) -> Unit = { logged += it.toString() }
    private val log: (String, Array<Pair<String, Any?>>) -> Unit = { ev, f -> logged += (EventLog.ev(ev, *f)).toString() }

    init { EventLog.addListener(listener) }
    @After fun tearDown() = EventLog.removeListener(listener)

    private fun sound(label: String) = when (label) {
        "pop", "click" -> "${Vocab.DISCRETE[label]}; instant sound; loudness normal; sounds like mouth sound"
        else -> "hum that ${Vocab.CONTOURS[label]}; pitch change large (over 4 semitones); duration short (150-400 ms); tone clear tone; loudness normal; sounds like hum"
    }

    private fun input(seq: List<String> = emptyList(), phrase: String? = null, profile: Profile = Profile.empty(), mode: String = "gesture") =
        DecisionInput(StateBuilder.build(if (phrase != null) "listening" else mode, "ai.vox.fixture", "Fixture", seq.map { sound(it) }, seq, phrase,
            profile, emptyList(), null, ScreenContext("video feed", "playing", "at the top", "hidden")), profile)

    private fun escalating(f: FakeOllama?, local: Decider? = null, timeoutMs: Int = 1500, localTarget: ((String, List<String>) -> ChoiceAnswer)? = null) =
        EscalatingDecider(f?.let { OllamaDecider(OllamaClient(it.base, "deepseek-v4.1-flash", { key }), timeoutMs) }, local, localTarget,
            targetTimeoutMs = 2500, log = log)

    /** A local model stand-in with a fixed answer. */
    private class FixedLocal(val d: Decision) : Decider { override val name = "model"; var calls = 0
        override fun decide(input: DecisionInput): Decision { calls++; return d } }

    private val ruleProfile = Profile.parse(JSONObject("""{"global":[{"phrase":["pop","pop"],"kind":"rule","rule":"Two pops like the post I'm looking at."}]}"""))

    @Test fun requestShape() {
        FakeOllama(reply = { 200 to FakeOllama.chat("swipe_up") }).use { f ->
            val d = OllamaDecider(OllamaClient(f.base, "deepseek-v4.1-flash", { key }), 1500).decide(input(listOf("rise")))
            assertEquals("swipe_up", d.action); assertTrue(d.unscored); assertEquals("cloud", d.source)
            val b = f.bodies.single()
            assertEquals("deepseek-v4.1-flash", b.getString("model"))
            assertEquals(false, b.getBoolean("stream")); assertEquals(false, b.getBoolean("think"))
            assertEquals(0, b.getJSONObject("options").getInt("temperature"))
            assertFalse("keep_alive stays at the server default", b.has("keep_alive"))
            val choice = b.getJSONObject("format").getJSONObject("properties").getJSONObject("choice")
            assertEquals("string", choice.getString("type"))
            assertEquals(Vocab.ACTIONS.keys.toList(), List(choice.getJSONArray("enum").length()) { choice.getJSONArray("enum").getString(it) })
            assertEquals("choice", b.getJSONObject("format").getJSONArray("required").getString(0))
            val msgs = b.getJSONArray("messages")
            assertEquals("system", msgs.getJSONObject(0).getString("role")); assertEquals(Vocab.POLICY, msgs.getJSONObject(0).getString("content"))
            val user = msgs.getJSONObject(1).getString("content")
            assertTrue(user.startsWith(input(listOf("rise")).scene.text() + "\n\noptions (answer with the key before the colon):\n"))
            assertTrue(user.contains("\nswipe_up: swipe up\n")); assertTrue(user.endsWith("none: ${Vocab.ACTIONS.getValue("none")}"))
            assertTrue(f.headers.single().any { it == "Authorization: Bearer $key" })
        }
        // No key (a LAN Ollama): no Authorization header.
        FakeOllama().use { f ->
            OllamaClient(f.base, "m", { "" }).choice("s", "u", listOf("t0", "none"), listOf("a", "b"), 1500)
            assertTrue(f.headers.single().none { it.startsWith("Authorization", true) })
        }
    }

    @Test fun parsing() {
        val keys = listOf("t0", "t1", "none"); val texts = listOf("Share (button, right)", "Download (item, bottom)", TargetVocab.NONE_OPTION)
        fun p(s: String) = OllamaClient.parseChoice(s, keys, texts)
        assertEquals("t1", p("""{"choice": "t1"}""")); assertEquals("t1", p("\"t1\"")); assertEquals("t1", p(" t1\n"))
        assertEquals("none", p("none"))
        assertEquals("t1", p("t1: Download (item, bottom)")); assertEquals("t1", p("t1: Download"))    // the option line echoed back
        assertNull(p("t1: Share (button, right)"))           // key and text disagree
        assertNull(p("hiss: go back")); assertNull(p("t7")); assertNull(p("""{"choice": "t9"}"""))
        assertNull(p("The answer is t1")); assertNull(p("I think the user means Share.\n\nt0")); assertNull(p("")); assertNull(p("{bad"))
    }

    @Test fun invalidChoiceFallsBack() {
        FakeOllama(reply = { 200 to FakeOllama.chat("The user probably wants the notifications, so t9.") }).use { f ->
            val d = escalating(f).decide(input(phrase = "summon the robot overlords"))
            assertEquals("rules:unknown-phrase", d.source.substringAfter("escalate-fallback -> "))
            assertEquals("none", d.action); assertFalse(d.unscored)
            assertTrue(logged.any { it.contains("\"outcome\":\"invalid choice\"") })
        }
    }

    @Test fun timeoutFallsBackWithinBudget() {
        FakeOllama(delayMs = 3000, reply = { 200 to FakeOllama.chat("tap") }).use { f ->
            val t0 = System.nanoTime()
            try { OllamaClient(f.base, "m", { key }).choice("s", "u", listOf("tap"), listOf("tap"), 300); throw AssertionError("expected a timeout") }
            catch (e: SocketTimeoutException) {}
            val local = FixedLocal(Decision("none", "model:below-threshold(like)", 0.3))
            val d = escalating(f, local, timeoutMs = 300).decide(input(listOf("pop", "pop"), profile = ruleProfile))
            val ms = (System.nanoTime() - t0) / 1_000_000
            assertEquals("none", d.action); assertTrue(d.source, d.source.startsWith("escalate-fallback -> model:below-threshold"))
            assertTrue("both calls bounded by their 300 ms deadlines, took $ms ms", ms < 1500)
            assertTrue(logged.any { it.contains("\"outcome\":\"timeout\"") })
        }
    }

    @Test fun routing() {
        FakeOllama(reply = { b ->
            val keys = b.getJSONObject("format").getJSONObject("properties").getJSONObject("choice").getJSONArray("enum")
            200 to FakeOllama.chat(if (keys.getString(0) == "t0") "t1: Share (button, bottom right)" else "like")
        }).use { f ->
            val local = FixedLocal(Decision("zoom_in", "model", 0.9))
            val esc = escalating(f, local)
            // Bound gestures, cursor defaults, table phrases, not-deliberate and unbound sounds: never the network.
            assertEquals("swipe_up", esc.decide(input(listOf("rise"))).action)
            assertEquals("rules:default", esc.decide(input(listOf("rise"))).source)
            assertEquals("move_up_slow", esc.decide(input(listOf("rise"), mode = "cursor")).action)
            assertEquals("rules:phrase", esc.decide(input(phrase = "go back")).source)
            assertEquals("rules:unbound", esc.decide(input(listOf("rise", "rise"))).source)   // 2026-09-28: "click pop" folds to home, so a truly unbound sequence
            assertEquals(0, f.bodies.size); assertEquals(0, local.calls)
            // An ambiguous gesture with a confident local model: local answer, no cloud.
            assertEquals("zoom_in", esc.decide(input(listOf("pop", "pop"), profile = ruleProfile)).action)
            assertEquals(1, local.calls); assertEquals(0, f.bodies.size)
            // The local model below min_confidence: escalates; the cloud answer is unscored and risky -> confirm.
            val lowLocal = FixedLocal(Decision("none", "model:below-threshold(like)", 0.3))
            val d = escalating(f, lowLocal).decide(input(listOf("pop", "pop"), profile = ruleProfile))
            assertEquals("like", d.action); assertTrue(d.unscored); assertTrue(d.source, d.source.startsWith("cloud:gesture:low-confidence"))
            assertTrue(Risk.needsConfirm(d))
            // An unknown phrase with no local model: straight to the cloud.
            assertTrue(escalating(f).decide(input(phrase = "make it bigger please")).source.startsWith("cloud:phrase:no-local-model"))
            // A target question escalates: keys t0.. + none, the answer is unscored -> highlighted for a confirm pop.
            val ts = listOf(Target("Like", "button", "bottom right", 800, 1800, 900, 1900), Target("Share", "button", "bottom right", 900, 1800, 1000, 1900))
            val opts = Targets.options(ts)
            val before = f.bodies.size
            val a = escalating(f).pickTarget(Targets.stateText("VLC", "org.videolan.vlc", ScreenContext("scrolling list", "none", "at the top", "hidden"), "share this"), opts)
            assertEquals(before + 1, f.bodies.size)
            val q = f.bodies.last()
            assertEquals(TargetVocab.POLICY, q.getJSONArray("messages").getJSONObject(0).getString("content"))
            assertEquals("[\"t0\",\"t1\",\"none\"]", q.getJSONObject("format").getJSONObject("properties").getJSONObject("choice").getJSONArray("enum").toString())
            assertEquals("Share (button, bottom right)", a.choice); assertTrue(a.unscored)
            assertEquals(Targets.Outcome.Choose(listOf(ts[1])), Targets.resolve(ts, a, 0.6))
        }
    }

    @Test fun targetFallsBackToLocalModel() {
        FakeOllama(reply = { 500 to "{\"error\":\"overloaded\"}" }).use { f ->
            val opts = listOf("Like (button, bottom right)", TargetVocab.NONE_OPTION)
            val a = escalating(f, localTarget = { _, o -> ChoiceAnswer(o[0], mapOf(o[0] to 0.8), 0.8, 12) }).pickTarget("state", opts)
            assertEquals("Like (button, bottom right)", a.choice); assertFalse(a.unscored)
            assertTrue(logged.any { it.contains("\"kind\":\"target\"") && it.contains("\"outcome\":\"error\"") })
        }
    }

    @Test fun newerEventCancelsAndNeverWaits() {
        FakeOllama(delayMs = 5000, reply = { 200 to FakeOllama.chat("tap") }).use { f ->
            val esc = escalating(f, timeoutMs = 4000)
            var d: Decision? = null
            val t0 = System.nanoTime()
            val th = thread { d = esc.decide(input(phrase = "whatever you think")) }
            while (f.bodies.isEmpty() && System.nanoTime() - t0 < 3_000_000_000) Thread.sleep(10)
            esc.submitted()                                   // a new event arrives: the call in flight is dropped
            th.join(3000)
            val ms = (System.nanoTime() - t0) / 1_000_000
            assertTrue("returned after $ms ms", ms < 2500)
            assertEquals("none", d!!.action); assertTrue(d!!.source, d!!.source.startsWith("escalate-fallback"))
            assertTrue(logged.any { it.contains("cancelled (newer event)") })
            // The newer event's own decision: a bound gesture, instant, no network.
            assertEquals("swipe_up", esc.decide(input(listOf("rise"))).action)
            // Two events queued before the first one starts: the first skips the network entirely.
            val n = f.bodies.size
            esc.submitted(); esc.submitted()
            assertTrue(esc.decide(input(phrase = "whatever you think")).source.startsWith("escalate-skipped"))
            assertEquals(n, f.bodies.size)
        }
    }

    @Test fun keyNeverLogged() {
        // A hostile or buggy server that echoes the key back in its error body and in its answer.
        FakeOllama(reply = { 401 to "{\"error\":\"bad key $key\"}" }).use { f ->
            escalating(f).decide(input(phrase = "open sesame"))
            try { OllamaClient(f.base, "m", { key }).choice("s", "u", listOf("a"), listOf("a"), 1500); throw AssertionError("expected an error") }
            catch (e: java.io.IOException) { assertFalse(e.message!!, e.message!!.contains(key)); assertTrue(e.message!!.contains("(auth)")) }
        }
        FakeOllama(reply = { 200 to FakeOllama.chat("my key is $key") }).use { f ->
            escalating(f).decide(input(phrase = "open sesame"))
            runCatching { escalating(f).pickTarget("state", listOf("A (item, top)", TargetVocab.NONE_OPTION)) }
        }
        assertTrue(logged.size >= 2)
        assertTrue(logged.none { it.contains(key) })
    }

    @Test fun namesItselfAsCantiNotDalvikAndReadsAnHtmlBlockPage() {
        // ollama.com: a 403 HTML page for the default Dalvik user agent, whatever the key.
        val ua = CantiHttp.headers("k").getValue("User-Agent")
        assertTrue(ua, ua.startsWith("Canti/") && ua.endsWith("(Android)") && !ua.contains("Dalvik"))
        assertEquals("Bearer k", CantiHttp.headers(" k ")["Authorization"])
        assertFalse(CantiHttp.headers("  ").containsKey("Authorization"))
        FakeOllama(reply = { 200 to FakeOllama.chat("a") }).use { f ->
            assertEquals("a", OllamaClient(f.base, "m", { key }).choice("s", "u", listOf("a"), listOf("a"), 1500).key)
            val sent = f.headers.single().first { it.startsWith("User-Agent", true) }.substringAfter(":").trim()
            assertEquals(ua, sent)
        }
        FakeOllama(reply = { 403 to "<!DOCTYPE html><html><body>Forbidden</body></html>" }, contentType = "text/html").use { f ->
            try { OllamaClient(f.base, "m", { key }).choice("s", "u", listOf("a"), listOf("a"), 1500); throw AssertionError("expected an error") }
            catch (e: java.io.IOException) {
                assertTrue(e.message!!, e.message!!.contains("blocked by server (not an API reply)"))
                assertFalse(e.message!!, e.message!!.contains("(auth)"))
            }
        }
        assertEquals("HTTP 403 (auth): {\"error\":\"unauthorized\"}", CantiHttp.errorText(403, "application/json", "{\"error\":\"unauthorized\"}"))
        assertEquals("HTTP 502 blocked by server (not an API reply)", CantiHttp.errorText(502, null, "  <html>bad gateway</html>"))
    }

    @Test fun riskyActions() {
        assertTrue(Risk.needsConfirm(Decision("tap", "cloud", 0.0, unscored = true)))
        assertTrue(Risk.needsConfirm(Decision("click", "cloud", 0.0, unscored = true)))
        assertFalse(Risk.needsConfirm(Decision("swipe_up", "cloud", 0.0, unscored = true)))
        assertFalse(Risk.needsConfirm(Decision("none", "cloud", 0.0, unscored = true)))
        assertFalse(Risk.needsConfirm(Decision("tap", "rules:default", explicit = true)))
        assertFalse(Risk.needsConfirm(Decision("tap", "model", 0.9)))
    }
}
