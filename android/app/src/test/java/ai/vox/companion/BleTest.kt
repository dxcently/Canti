package ai.vox.companion

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File

/** The BLE link without Android: fragment reassembly, message decoding and parsing, INFO, backoff. */
class BleTest {
    private val hum = "hum that ${Vocab.CONTOURS["rise"]}; pitch change large (over 4 semitones); duration short (150-400 ms); tone clear tone; loudness loud; sounds like hum"

    /** A realistic one-sound message with timing and a 24-value fingerprint + pitch track (~700 bytes). */
    private fun soundMsg(id: Int) = JSONObject().put("v", 1).put("id", id).put("mode", "gesture").put("armed", true)
        .put("sounds", JSONArray(listOf(hum))).put("sequence", JSONArray(listOf("rise")))
        .put("timing", JSONArray(listOf(JSONObject().put("t_start_ms", 1000L * id).put("t_end_ms", 1000L * id + 310))))
        .put("features", JSONArray(listOf(JSONObject().put("fp", JSONArray(List(24) { -1.2345 + it * 0.1111 }))
            .put("fp_version", "fp1").put("pitch16", JSONArray(List(16) { it * 0.37 })))))

    private fun bytes(o: JSONObject) = o.toString().toByteArray(Charsets.UTF_8)

    private fun messages(r: Reassembler, frags: List<ByteArray>) = frags.flatMap { r.feed(it) }

    private fun onlyMessage(outs: List<Reassembler.Out>): ByteArray {
        assertEquals(outs.toString(), 1, outs.size)
        return (outs[0] as Reassembler.Out.Message).bytes
    }

    // --- fragmentation and reassembly --------------------------------------------------------------------------------

    /** The device side of one connection: its counter starts at 0 and runs across messages. */
    private class Device(val mtu: Int) {
        var ctr = 0
        fun send(m: ByteArray): List<ByteArray> = BleProtocol.fragment(m, mtu, ctr).also { ctr += it.size }
    }

    private val stateMsg = """{"v":1,"id":7,"mode":"gesture","armed":false,"sounds":[],"sequence":[]}""".toByteArray()

    private fun header(f: ByteArray) = f[0].toInt() and 0xff

    @Test fun singleFragment() {
        val f = BleProtocol.fragment(stateMsg, 517, 0)
        assertEquals(1, f.size)
        assertEquals(0x80 or 0x40, header(f[0]))                     // first + last, counter 0
        assertEquals(stateMsg.size + 1, f[0].size)
        assertTrue(stateMsg.contentEquals(onlyMessage(Reassembler().feed(f[0]))))
    }

    @Test fun multiFragmentAtEveryMtu() {
        val m = bytes(soundMsg(3))
        for (mtu in listOf(23, 24, 50, 185, 247, 517)) {
            val f = BleProtocol.fragment(m, mtu, 0)
            assertTrue("mtu $mtu", f.all { it.size <= mtu - 3 })
            assertEquals("mtu $mtu", (m.size + mtu - 5) / (mtu - 4), f.size)
            assertTrue("only the first fragment has bit 6", header(f[0]) and 0x40 != 0 && f.drop(1).all { header(it) and 0x40 == 0 })
            assertTrue("only the final fragment has bit 7", f.dropLast(1).all { header(it) and 0x80 == 0 } && header(f.last()) and 0x80 != 0)
            assertEquals("counters 0, 1, 2, ... mod 64", f.indices.map { it and 0x3f }, f.map { header(it) and 0x3f })
            val r = Reassembler()
            val outs = messages(r, f)
            assertTrue("mtu $mtu", m.contentEquals(onlyMessage(outs)))
            assertEquals(f.size.toLong(), r.fragments)
        }
        assertTrue(bytes(soundMsg(3)).size > 514)   // a fingerprinted sound needs more than one notification even at 517
    }

    @Test fun multiByteCharacterSplitAcrossFragments() {
        val m = bytes(JSONObject().put("v", 1).put("mode", "listening").put("phrase", "ouvre l'appareil photo, s'il te plaît ".repeat(3))
            .put("sounds", JSONArray()).put("sequence", JSONArray()))
        val r = Reassembler()
        val out = onlyMessage(messages(r, BleProtocol.fragment(m, 23, 0)))
        assertEquals("ouvre l'appareil photo, s'il te plaît ".repeat(3), FeatureMessage.parse(BleMessages.decode(out)).phrase)
    }

    @Test fun counterWrapsAroundAt64() {
        val r = Reassembler(); val d = Device(185)
        repeat(61) { onlyMessage(messages(r, d.send(stateMsg))) }     // counters 0..60
        val a = bytes(soundMsg(1)); val b = bytes(soundMsg(2))
        val fa = d.send(a)                                             // 61, 62, 63, 0, ...
        assertTrue(fa.size >= 4)
        assertEquals(0, header(fa[3]) and 0x3f)
        assertTrue(a.contentEquals(onlyMessage(messages(r, fa))))
        assertTrue(b.contentEquals(onlyMessage(messages(r, d.send(b)))))   // the counter runs across messages
    }

    @Test fun eachConnectionStartsAtCounterZero() {
        val r = Reassembler()
        val m = bytes(soundMsg(1))
        val d1 = Device(185); d1.ctr = 0
        repeat(3) { onlyMessage(messages(r, d1.send(m))) }
        r.reset()                                                    // new connection: the device restarts at 0
        assertTrue(m.contentEquals(onlyMessage(messages(r, Device(185).send(m)))))
        // If the connection's first notifications were lost, that is a gap (nothing partial to drop), and a message
        // that starts at a first fragment still gets through.
        r.reset()
        val outs = messages(r, BleProtocol.fragment(stateMsg, 185, 5))
        assertEquals(Reassembler.Out.Gap(0, 5, 0), outs[0])
        assertTrue(stateMsg.contentEquals((outs[1] as Reassembler.Out.Message).bytes))
    }

    @Test fun gapDropsThePartialMessageAndResyncsAtTheNextFirstFragment() {
        val r = Reassembler(); val d = Device(185)
        val a = bytes(soundMsg(1)); val b = bytes(soundMsg(2)); val c = bytes(soundMsg(3))
        val fa = d.send(a); val fb = d.send(b); val fc = d.send(c)
        // Lose fa[2]: the partial a is dropped (gap: expected 2, got 3), the rest of a is skipped silently; b and c
        // arrive whole.
        val outs = messages(r, fa.filterIndexed { i, _ -> i != 2 } + fb + fc)
        assertEquals(Reassembler.Out.Gap(2, 3, 2 * (185 - 4)), outs.filterIsInstance<Reassembler.Out.Gap>().single())
        assertTrue(outs.toString(), outs.none { it is Reassembler.Out.Bad })
        val got = outs.filterIsInstance<Reassembler.Out.Message>().map { String(it.bytes) }
        assertEquals(listOf(String(b), String(c)), got)
        for (m in got) FeatureMessage.parse(BleMessages.decode(m.toByteArray()))
    }

    @Test fun gapThatSwallowsAWholeMessageKeepsTheNextOne() {
        val r = Reassembler(); val d = Device(517)
        val a = bytes(soundMsg(1)); val b = bytes(soundMsg(2)); val c = bytes(soundMsg(3))
        val fa = d.send(a); val fb = d.send(b); val fc = d.send(c)
        val outs = messages(r, fa + fc)
        assertEquals(Reassembler.Out.Gap(fa.size, fa.size + fb.size, 0), outs.filterIsInstance<Reassembler.Out.Gap>().single())
        assertEquals(listOf(String(a), String(c)), outs.filterIsInstance<Reassembler.Out.Message>().map { String(it.bytes) })
    }

    @Test fun gapOnTheLastFragmentDropsTheMessage() {
        val r = Reassembler(); val d = Device(185)
        val a = bytes(soundMsg(1)); val b = bytes(soundMsg(2))
        val fa = d.send(a); val fb = d.send(b)
        val outs = messages(r, fa.dropLast(1) + fb)
        assertEquals(1, outs.filterIsInstance<Reassembler.Out.Gap>().size)
        assertEquals(listOf(String(b)), outs.filterIsInstance<Reassembler.Out.Message>().map { String(it.bytes) })
    }

    @Test fun gapOnAFirstFragmentSkipsThatWholeMessage() {
        val r = Reassembler(); val d = Device(185)
        val a = bytes(soundMsg(1)); val b = bytes(soundMsg(2)); val c = bytes(soundMsg(3))
        val fa = d.send(a); val fb = d.send(b); val fc = d.send(c)
        val outs = messages(r, fa + fb.drop(1) + fc)
        assertEquals(Reassembler.Out.Gap(fa.size, fa.size + 1, 0), outs.filterIsInstance<Reassembler.Out.Gap>().single())
        assertTrue(outs.none { it is Reassembler.Out.Bad })
        assertEquals(listOf(String(a), String(c)), outs.filterIsInstance<Reassembler.Out.Message>().map { String(it.bytes) })
    }

    /**
     * What the first flag fixes: after a gap, a continuation fragment whose chunk happens to start with `{` (the old
     * resync guess took that for a new message) is skipped like any other continuation.
     */
    @Test fun continuationStartingWithABraceIsNotANewMessage() {
        val m = bytes(soundMsg(1))
        var checked = 0
        for (mtu in 23..517) {
            val f = BleProtocol.fragment(m, mtu, 0)
            val k = (2 until f.size).firstOrNull { f[it].size > 1 && f[it][1] == '{'.code.toByte() } ?: continue
            val r = Reassembler()
            val outs = messages(r, f.filterIndexed { i, _ -> i != k - 1 })   // lose the fragment just before it
            assertEquals("mtu $mtu", 1, outs.filterIsInstance<Reassembler.Out.Gap>().size)
            assertTrue("mtu $mtu: $outs", outs.none { it is Reassembler.Out.Message || it is Reassembler.Out.Bad })
            checked++
        }
        assertTrue("no MTU put a '{' at the start of a continuation chunk", checked > 0)
    }

    @Test fun protocolViolationsWithoutAGap() {
        val r = Reassembler()
        val m = bytes(soundMsg(1)); val f = BleProtocol.fragment(m, 185, 0)
        // A continuation with no message open (counter in sequence) is a device bug: reported once, then skipped.
        var outs = messages(r, f.drop(1).mapIndexed { i, x -> byteArrayOf(((header(x) and 0xc0) or i).toByte()) + x.copyOfRange(1, x.size) })
        assertEquals(listOf<Reassembler.Out>(Reassembler.Out.Bad("continuation fragment with no first fragment")), outs)
        // A first fragment while a message is open: the partial one is reported and dropped, the new one is kept.
        r.reset()
        val d = Device(185)
        val fa = d.send(m); d.ctr = fa.size - 1                        // the device "forgets" a's last fragment
        outs = messages(r, fa.dropLast(1) + d.send(stateMsg))
        assertEquals(Reassembler.Out.Bad("first fragment before the previous message ended: dropped ${(fa.size - 1) * (185 - 4)} bytes"), outs[0])
        assertTrue(stateMsg.contentEquals((outs[1] as Reassembler.Out.Message).bytes))
        assertEquals(2, outs.size)
    }

    @Test fun protocolMessageLimitIs4096Bytes() {
        fun msgOf(size: Int): ByteArray {
            val base = """{"v":1,"mode":"gesture","sounds":[],"sequence":[],"pad":""}"""
            return (base.dropLast(2) + "x".repeat(size - base.length) + "\"}").toByteArray()
        }
        assertEquals(4096, BleProtocol.MAX_MESSAGE_BYTES)
        val r = Reassembler(); val d = Device(23)
        val ok = msgOf(4096); val big = msgOf(4097)
        assertEquals(4096, ok.size); assertEquals(4097, big.size)
        assertTrue(ok.contentEquals(onlyMessage(messages(r, d.send(ok)))))
        val outs = messages(r, d.send(big) + d.send(stateMsg))
        assertEquals(Reassembler.Out.Bad("message longer than 4096 bytes: dropped"), outs[0])
        assertEquals(2, outs.size)                                   // the rest of the big message is skipped silently
        assertTrue(stateMsg.contentEquals((outs[1] as Reassembler.Out.Message).bytes))
    }

    @Test fun garbage() {
        val r = Reassembler()
        assertEquals(listOf<Reassembler.Out>(Reassembler.Out.Bad("empty notification")), r.feed(ByteArray(0)))
        // A header with no chunk completes an empty message, which does not decode.
        val empty = onlyMessage(r.feed(byteArrayOf(0xc0.toByte())))
        assertEquals(0, empty.size)
        assertBad("empty message") { BleMessages.decode(empty) }
        assertBad("not UTF-8") { BleMessages.decode(byteArrayOf('{'.code.toByte(), 0xff.toByte(), 0xfe.toByte(), '}'.code.toByte())) }
        assertBad("not a JSON object") { BleMessages.decode("hello".toByteArray()) }   // org.json reads a bare word as a string
        assertBad("not JSON") { BleMessages.decode("""{"v":1,"sounds":[""".toByteArray()) }
        assertBad("not a JSON object") { BleMessages.decode("[1,2]".toByteArray()) }
        assertBad("trailing data") { BleMessages.decode("""{"v":1}{"v":1}""".toByteArray()) }
        assertBad("trailing data") { BleMessages.decode("""{"v":1}]}""".toByteArray()) }
        // The device may not drive the app's debug operations.
        assertBad("not accepted over BLE") { BleMessages.decode("""{"type":"control","op":"enroll_delete","all":true}""".toByteArray()) }
        // A smaller limit works the same way: the long message is dropped, the next one is fine.
        val small = Reassembler(maxBytes = 100)
        val big = bytes(soundMsg(1)); val ok = """{"v":1,"mode":"cursor","sounds":[],"sequence":[]}""".toByteArray()
        val fb = BleProtocol.fragment(big, 50, 0)
        val outs = messages(small, fb + BleProtocol.fragment(ok, 50, fb.size))
        assertTrue(outs.toString(), outs.first() is Reassembler.Out.Bad)
        assertEquals(listOf(String(ok)), outs.filterIsInstance<Reassembler.Out.Message>().map { String(it.bytes) })
        // Random bytes never throw out of the reassembler, and it never buffers more than the limit + one chunk.
        val rng = kotlin.random.Random(1)
        val rr = Reassembler()
        repeat(20000) { rr.feed(rng.nextBytes(rng.nextInt(0, 515))).forEach { o -> if (o is Reassembler.Out.Message) assertTrue(o.bytes.size <= 4096) } }
    }

    private fun assertBad(part: String, block: () -> Unit) {
        try { block(); fail("expected IllegalArgumentException containing '$part'") } catch (e: IllegalArgumentException) {
            assertTrue("'${e.message}' should contain '$part'", e.message!!.contains(part))
        }
    }

    // --- messages ------------------------------------------------------------------------------------------------------

    @Test fun messageParsing() {
        // One sound per message, with its device timestamps and fingerprint.
        val s = FeatureMessage.parse(BleMessages.decode(bytes(soundMsg(4))))
        assertEquals(listOf("rise"), s.sequence); assertEquals(4L, s.id)
        assertEquals(Stamp(4000, 4310), s.timing!![0]); assertEquals(24, s.features!![0]!!.fp.size)
        // Arm / pause / stop / mode arrive as messages with no sounds.
        val off = FeatureMessage.parse(BleMessages.decode("""{"v":1,"id":7,"mode":"gesture","armed":false,"sounds":[],"sequence":[]}""".toByteArray()))
        assertFalse(off.armed); assertTrue(off.sequence.isEmpty())
        val on = FeatureMessage.parse(BleMessages.decode("""{"v":1,"id":8,"mode":"gesture","armed":true,"sounds":[],"sequence":[]}""".toByteArray()))
        assertTrue(on.armed)
        val cur = FeatureMessage.parse(BleMessages.decode("""{"v":1,"id":9,"mode":"cursor","sounds":[],"sequence":[]}""".toByteArray()))
        assertEquals("cursor", cur.mode)
        // The disarm the app synthesises on a dropped link parses too.
        assertFalse(FeatureMessage.parse(JSONObject().put("v", 1).put("armed", false).put("sounds", JSONArray()).put("sequence", JSONArray())).armed)
        // Invalid feature messages decode (they are JSON objects) and are rejected by the parser.
        for (bad in listOf("""{"v":2,"sounds":[],"sequence":[],"mode":"gesture"}""", """{"v":1,"sounds":["x"],"sequence":["wobble"]}""",
                """{"v":1,"sounds":[],"sequence":[]}""")) {
            val o = BleMessages.decode(bad.toByteArray())
            try { FeatureMessage.parse(o); fail("accepted $bad") } catch (_: IllegalArgumentException) {}
        }
    }

    @Test fun infoParsing() {
        val i = BleInfo.parse("""{"v":1,"fw":"0.1.0","mic":"inmp441","fp_version":"fp1"}""".toByteArray())
        assertEquals("0.1.0", i.fw); assertEquals("inmp441", i.mic); assertEquals("fp1", i.fpVersion); assertFalse(i.insecure)
        val j = BleInfo.parse("""{"v":1,"fw":"0.1.0","mic":"none","fp_version":null,"insecure":true}""".toByteArray())
        assertNull(j.fpVersion); assertTrue(j.insecure)
        assertBad("INFO version") { BleInfo.parse("""{"v":2}""".toByteArray()) }
        assertBad("not a JSON object") { BleInfo.parse("junk".toByteArray()) }
    }

    @Test fun backoff() {
        val b = Backoff()
        assertEquals(listOf(1000L, 2000, 4000, 8000, 16000, 30000, 30000), List(7) { b.next() })
        assertEquals(7, b.failures)
        b.reset(); assertEquals(1000L, b.next())
    }

    @Test fun uuidsMatchTheContract() {
        assertEquals("ac740001-3c66-cc47-6290-e0e7094c17b9", BleProtocol.SERVICE.toString())
        assertEquals("ac740002-3c66-cc47-6290-e0e7094c17b9", BleProtocol.EVENT.toString())
        assertEquals("ac740003-3c66-cc47-6290-e0e7094c17b9", BleProtocol.CONFIG.toString())
        assertEquals("ac740004-3c66-cc47-6290-e0e7094c17b9", BleProtocol.INFO.toString())
    }

    // --- the firmware's own data ---------------------------------------------------------------------------------------

    private val firmwareTests = File(System.getenv("VOX_FIRMWARE_TESTS") ?: "../../firmware/tests")

    /** The canned lines the firmware sends in test mode: each, as a one-sound message fragmented at MTU 23, parses. */
    @Test fun firmwareTestSoundsParse() {
        val f = File(firmwareTests, "test_sounds.json")
        assumeTrue("no $f", f.exists())
        val sounds = JSONObject(f.readText()).getJSONArray("sounds")
        assertTrue(sounds.length() > 0)
        val r = Reassembler(); var ctr = 0
        for (i in 0 until sounds.length()) {
            val s = sounds.getJSONObject(i)
            val msg = JSONObject().put("v", 1).put("id", i).put("mode", "gesture").put("armed", true)
                .put("sounds", JSONArray(listOf(s.getString("line")))).put("sequence", JSONArray(listOf(s.getString("label"))))
            val fr = BleProtocol.fragment(bytes(msg), 23, ctr); ctr += fr.size
            val m = FeatureMessage.parse(BleMessages.decode(onlyMessage(messages(r, fr))))
            assertEquals(s.getString("label"), m.sequence.single())
        }
    }

    /**
     * Real messages captured from the Pico (written by the firmware agent). Each line may be the message object
     * itself, {"message": object | string}, or {"notifications"|"fragments": [hex, ...]} (raw EVENT notifications,
     * reassembled here, one connection's worth per line). Every message must decode and parse.
     */
    @Test fun capturedPicoMessagesParse() {
        val f = File(firmwareTests, "captured_messages.jsonl")
        assumeTrue("no $f yet", f.exists())
        var n = 0
        f.readLines().filter { it.isNotBlank() }.forEachIndexed { ln, line ->
            val o = JSONObject(line)
            val raws: List<ByteArray> = when {
                o.has("notifications") || o.has("fragments") -> {
                    val a = o.optJSONArray("notifications") ?: o.getJSONArray("fragments")
                    val r = Reassembler()
                    // A capture that starts mid-connection (first counter not 0) gives one leading gap with nothing dropped.
                    val outs = (0 until a.length()).flatMap { r.feed(hex(a.getString(it))) }
                        .filterIndexed { i, x -> !(i == 0 && x is Reassembler.Out.Gap && x.dropped == 0) }
                    assertTrue("line ${ln + 1}: ${outs.filter { it !is Reassembler.Out.Message }}", outs.all { it is Reassembler.Out.Message })
                    outs.map { (it as Reassembler.Out.Message).bytes }
                }
                o.has("message") -> listOf((o.get("message") as? JSONObject)?.toString()?.toByteArray() ?: o.getString("message").toByteArray())
                o.has("sounds") || o.has("armed") || o.has("v") -> listOf(line.trim().toByteArray())
                else -> { fail("line ${ln + 1}: unknown capture format: ${line.take(120)}"); emptyList() }
            }
            for (b in raws) {
                try { FeatureMessage.parse(BleMessages.decode(b)); n++ }
                catch (e: IllegalArgumentException) { fail("line ${ln + 1}: ${e.message}: ${String(b).take(200)}") }
            }
        }
        assertTrue("no messages in $f", n > 0)
        println("captured Pico messages parsed: $n")
    }

    /**
     * The same captured messages as the device sends them: each line's exact bytes, fragmented at MTU 23, 185 and 517
     * with one counter running across the whole capture (one connection), must come out of the reassembler byte for
     * byte and parse. The capture includes messages of exactly 4096 bytes, the protocol limit.
     */
    @Test fun capturedPicoMessagesThroughTheReassembler() {
        val f = File(firmwareTests, "captured_messages.jsonl")
        assumeTrue("no $f yet", f.exists())
        val lines = f.readLines().filter { it.isNotBlank() }.map { it.toByteArray(Charsets.UTF_8) }
        assertTrue(lines.all { it.size <= BleProtocol.MAX_MESSAGE_BYTES })
        for (mtu in listOf(23, 185, 517)) {
            val r = Reassembler(); val d = Device(mtu)
            val outs = lines.flatMap { messages(r, d.send(it)) }
            assertTrue("mtu $mtu: ${outs.filter { it !is Reassembler.Out.Message }.take(3)}", outs.all { it is Reassembler.Out.Message })
            val got = outs.map { (it as Reassembler.Out.Message).bytes }
            assertEquals(lines.size, got.size)
            for (i in lines.indices) {
                assertTrue("mtu $mtu line ${i + 1}", lines[i].contentEquals(got[i]))
                FeatureMessage.parse(BleMessages.decode(got[i]))
            }
        }
        println("captured Pico messages through the reassembler: ${lines.size} x 3 MTUs, largest ${lines.maxOf { it.size }} bytes, " +
            "${lines.count { it.size == 4096 }} of 4096 bytes")
    }

    // --- pairing failures ----------------------------------------------------------------------------------------------

    @Test fun authFailuresStopRetryingAndNameTheDevice() {
        for (s in listOf(5, 6, 15, 61, 137)) assertTrue("$s", AuthFailures.isAuthFailure(s))
        for (s in listOf(0, 8, 19, 22, 62, 133, 147)) assertFalse("$s", AuthFailures.isAuthFailure(s))   // timeouts, remote/local close, GATT_ERROR
        val a = AuthFailures()
        assertFalse(a.record())                                      // one failure: retry (it may be transient)
        assertTrue(a.record())                                       // two in a row: stop, ask the user
        a.reset(); assertFalse(a.record())
        assertEquals("VOX-2807", AuthFailures.deviceName("88:A2:9E:0D:28:07"))
        val addr = "88:A2:9E:0D:28:07"
        val hold = "Hold the VOX button 5 s until the light blinks fast, then connect."
        assertEquals(hold, AuthFailures.hint(addr, AuthFailures.Problem.WINDOW_CLOSED))
        assertEquals(listOf("Forget VOX-2807 in the phone's Bluetooth settings (a firmware flash erased its pairings).", hold),
            AuthFailures.hint(addr, AuthFailures.Problem.STALE_BOND).lines())
        assertEquals(listOf("If VOX-2807 was re-flashed, forget it in the phone's Bluetooth settings first.", hold),
            AuthFailures.hint(addr, AuthFailures.Problem.UNKNOWN).lines())
    }

    // --- LinkRecovery: the retry state machine ----------------------------------------------------------------------

    private fun connect(auto: Boolean, refresh: Boolean) = LinkRecovery.Plan.Connect(autoConnect = auto, refreshCache = refresh)

    @Test fun recoveryDropsBackOffThenAutoConnect() {
        val r = LinkRecovery()
        assertEquals(connect(auto = false, refresh = false), r.attempt(staleLink = false, asleep = false))
        assertEquals(listOf(1000L, 2000L, 4000L, 8000L, 16000L), (1..5).map { r.failed(LinkRecovery.Failure.DROP) })
        assertEquals(connect(auto = true, refresh = false), r.attempt(staleLink = false, asleep = false))
        assertEquals(listOf(30_000L, 30_000L), (1..2).map { r.failed(LinkRecovery.Failure.DROP) })   // capped
    }

    @Test fun recoverySetupFailureGivesAFreshDirectLinkWithARefreshedCache() {
        val r = LinkRecovery()
        repeat(5) { r.failed(LinkRecovery.Failure.DROP) }          // auto-connect territory
        assertEquals(30_000L, r.failed(LinkRecovery.Failure.SETUP))
        assertEquals(1, r.setupFailures)
        // never auto-connect after a setup failure (it would reattach to the same link), and refresh the cache
        assertEquals(connect(auto = false, refresh = true), r.attempt(staleLink = false, asleep = false))
        assertEquals(connect(auto = false, refresh = true), r.attempt(staleLink = false, asleep = true))
    }

    @Test fun recoverySetupFailuresWaitAtLeastTheSettleTimeAndStillEscalate() {
        val r = LinkRecovery()
        assertEquals(listOf(2000L, 2000L, 4000L, 8000L, 16000L, 30000L, 30000L), (1..7).map { r.failed(LinkRecovery.Failure.SETUP) })
        assertEquals(7, r.setupFailures)
    }

    @Test fun recoveryADropEndsTheSetupStreak() {
        val r = LinkRecovery()
        r.failed(LinkRecovery.Failure.SETUP)
        r.failed(LinkRecovery.Failure.DROP)                         // device away: back to the normal rules
        assertEquals(0, r.setupFailures)
        assertEquals(connect(auto = true, refresh = false), r.attempt(staleLink = false, asleep = true))
    }

    @Test fun recoveryWaitsOutAStaleLinkOncePerStreak() {
        val r = LinkRecovery()
        assertEquals(LinkRecovery.Plan.WaitForRelease(4_000), r.attempt(staleLink = true, asleep = false))
        // still up after the wait: connect anyway, refreshing the cache
        assertEquals(connect(auto = false, refresh = true), r.attempt(staleLink = true, asleep = false))
        r.failed(LinkRecovery.Failure.DROP)
        assertEquals(connect(auto = false, refresh = true), r.attempt(staleLink = true, asleep = false))
        // a setup failure allows another wait (our own closed link may linger)
        r.failed(LinkRecovery.Failure.SETUP)
        assertTrue(r.attempt(staleLink = true, asleep = false) is LinkRecovery.Plan.WaitForRelease)
    }

    @Test fun recoveryReadyStartsOver() {
        val r = LinkRecovery()
        r.attempt(staleLink = true, asleep = false)
        repeat(3) { r.failed(LinkRecovery.Failure.SETUP) }
        r.reset()
        assertEquals(0, r.failures); assertEquals(0, r.setupFailures)
        assertEquals(1000L, r.failed(LinkRecovery.Failure.DROP))
        assertTrue(r.attempt(staleLink = true, asleep = false) is LinkRecovery.Plan.WaitForRelease)
    }

    @Test fun arrivalLagIsTheDelayAboveTheBestRecentOne() {
        val a = ArrivalLag(window = 4)
        assertEquals(0L, a.lag(10_030, 5_000))            // offset 5030: the best so far
        assertEquals(200L, a.lag(11_230, 6_000))          // 200 ms later than that
        assertEquals(0L, a.lag(12_020, 7_000))            // a faster one becomes the reference
        assertEquals(10L, a.lag(13_030, 8_000))
        assertEquals(0L, a.lag(500, 100))                 // device rebooted (clock went back): start over
        assertEquals(82_090L, ArrivalLag.deviceMs(JSONObject().put("hold", "start").put("t_ms", 82_090)))
        assertEquals(81_512L, ArrivalLag.deviceMs(JSONObject("{\"timing\":[{\"t_start_ms\":1,\"t_end_ms\":2},{\"t_start_ms\":81234,\"t_end_ms\":81512}]}")))
        assertEquals(2L, ArrivalLag.deviceMs(JSONObject("{\"timing\":[{\"t_start_ms\":1,\"t_end_ms\":2},null]}")))
        assertNull(ArrivalLag.deviceMs(JSONObject().put("armed", true)))
    }

    private fun hex(s: String) = s.replace(" ", "").chunked(2).map { it.toInt(16).toByte() }.toByteArray()
}
