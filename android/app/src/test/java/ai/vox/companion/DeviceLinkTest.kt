package ai.vox.companion

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * [DeviceLink] against a fake link (PROTOCOL.md "BLE GATT link (v1)": *App commands*, *Sleep and wake*, *Pairing*,
 * *Disconnect*): CONFIG writes are recorded, time is a manual clock, and the "device" is the test sending its state
 * messages.
 */
class DeviceLinkTest {
    private class FakeLink : DeviceLink.Io {
        var t = 0L
        val writes = mutableListOf<JSONObject>()
        var refuse: String? = null
        private class Timer(val due: Long, val r: () -> Unit)
        private val timers = mutableListOf<Timer>()
        val logs = mutableListOf<Pair<String, Map<String, Any?>>>()

        override fun write(bytes: ByteArray): String? = refuse ?: run { writes += JSONObject(String(bytes, Charsets.UTF_8)); null }
        override fun later(ms: Long, r: () -> Unit): () -> Unit { val x = Timer(t + ms, r); timers += x; return { timers.remove(x) } }
        override fun now() = t
        override fun log(ev: String, vararg fields: Pair<String, Any?>) { logs += ev to fields.toMap() }

        fun advance(ms: Long) {
            val end = t + ms
            while (true) {
                val next = timers.filter { it.due <= end }.minByOrNull { it.due } ?: break
                timers.remove(next); t = next.due; next.r()
            }
            t = end
        }
        fun cmdLogs(result: String) = logs.filter { it.first == "device_cmd" && it.second["result"] == result }
    }

    private val addr = "88:A2:9E:0D:28:07"
    private val hold = "Hold the VOX button 5 s until the light blinks fast, then connect."

    private fun state(armed: Boolean, mode: String = "gesture", sleeping: Boolean = false, id: Int = 1) = JSONObject()
        .put("v", 1).put("id", id).put("mode", mode).put("armed", armed).put("sounds", JSONArray()).put("sequence", JSONArray())
        .apply { if (sleeping) put("sleeping", true) }

    private fun sound(id: Int = 9) = JSONObject().put("v", 1).put("id", id).put("mode", "gesture").put("armed", true)
        .put("sounds", JSONArray().put(Vocab.DISCRETE.getValue("pop") + "; instant sound; loudness normal; sounds like mouth sound"))
        .put("sequence", JSONArray().put("pop"))

    private fun map(o: JSONObject) = o.keys().asSequence().associateWith { o.get(it) }

    /** A link that is up, with the device's state-on-connect message delivered. */
    private fun up(armed: Boolean = true): Pair<FakeLink, DeviceLink> {
        val io = FakeLink(); val d = DeviceLink(io)
        d.connected(); d.ready(); d.message(state(armed))
        return io to d
    }

    private fun DeviceLink.run(c: DeviceLink.Command): MutableList<JSONObject> { val out = mutableListOf<JSONObject>(); command(c) { out += it }; return out }

    // --- commands -------------------------------------------------------------------------------------------------------

    @Test fun eachCommandIsWrittenAndConfirmedByTheDevicesStateMessage() {
        val (io, d) = up(armed = true)
        assertEquals("listening", d.presence())

        // pause: the write alone confirms nothing; the state message does
        var r = d.run(DeviceLink.Command(armed = false))
        assertEquals(mapOf("v" to 1, "armed" to false), map(io.writes.last()))
        d.writeDone(0); io.advance(200)
        assertTrue(r.isEmpty())
        assertEquals("pause", d.waitingFor?.label)
        d.message(state(armed = false, id = 2))
        assertEquals(1, r.size)
        assertTrue(r[0].getBoolean("ok")); assertEquals("confirmed", r[0].getString("result")); assertTrue(r[0].getBoolean("applied"))
        assertEquals(200L, r[0].getLong("ms"))
        assertNull(d.waitingFor); assertNull(d.error)
        assertEquals("awake – paused", d.presence())

        // arm
        r = d.run(DeviceLink.Command(armed = true))
        assertEquals(mapOf("v" to 1, "armed" to true), map(io.writes.last()))
        d.message(state(armed = true, id = 3))
        assertEquals("confirmed", r.single().getString("result")); assertEquals("listening", d.presence())

        // mode
        r = d.run(DeviceLink.Command(mode = "cursor"))
        assertEquals(mapOf("v" to 1, "mode" to "cursor"), map(io.writes.last()))
        d.message(state(armed = true, mode = "cursor", id = 4))
        assertEquals("confirmed", r.single().getString("result")); assertEquals("cursor", d.mode)

        // armed and mode in one write
        r = d.run(DeviceLink.Command(armed = false, mode = "gesture"))
        assertEquals(mapOf("v" to 1, "armed" to false, "mode" to "gesture"), map(io.writes.last()))
        d.message(state(armed = false, mode = "gesture", id = 5))
        assertTrue(r.single().getBoolean("applied")); assertEquals("gesture", d.mode); assertEquals(false, d.armed)

        // sleep: confirmed by the sleeping message, after which the device is asleep
        r = d.run(DeviceLink.Command(sleep = true))
        assertEquals(mapOf("v" to 1, "sleep" to true), map(io.writes.last()))
        d.message(state(armed = false, sleeping = true, id = 6))
        assertEquals("confirmed", r.single().getString("result")); assertTrue(r.single().getBoolean("applied"))
        assertTrue(d.asleep); assertEquals("asleep", d.presence())

        assertEquals(5, io.writes.size)
        assertEquals(5, io.cmdLogs("sent").size); assertEquals(5, io.cmdLogs("confirmed").size)
    }

    @Test fun stayAwakeBuildConfirmsSleepWithAPlainDisarm() {
        val (_, d) = up()
        val r = d.run(DeviceLink.Command(sleep = true))
        d.message(state(armed = false, id = 3))                                       // VOX_SLEEP_STAYS_AWAKE: no sleeping flag
        assertEquals("confirmed", r.single().getString("result")); assertTrue(r.single().getBoolean("applied"))
        assertFalse(d.asleep); assertEquals(false, d.armed)
    }

    @Test fun onlyANoSoundStateMessageConfirms() {
        val (_, d) = up()
        val r = d.run(DeviceLink.Command(armed = false))
        d.message(sound())                                                            // a sound is not a confirmation
        d.message(state(true).put("mode", "listening").put("phrase", "next"))         // nor is a phrase
        assertTrue(r.isEmpty())
        // The button and the app are equal: a state message that shows the button's later action still confirms (the
        // device answered), but says the command was not what stuck.
        d.message(state(armed = true, id = 3))
        assertEquals("confirmed", r.single().getString("result")); assertFalse(r.single().getBoolean("applied"))
        assertEquals("listening", d.presence())
    }

    @Test fun noConfirmationWithinTheTimeoutIsAFailureShownToTheUser() {
        val (io, d) = up()
        val r = d.run(DeviceLink.Command(armed = false))
        io.advance(DeviceLink.CONFIRM_TIMEOUT_MS - 1)
        assertTrue(r.isEmpty())
        io.advance(1)
        assertFalse(r.single().getBoolean("ok")); assertEquals("failed", r.single().getString("result"))
        assertEquals("no confirmation from the device within 1500 ms", r.single().getString("error"))
        assertEquals("Pause failed: no confirmation from the device within 1500 ms.", d.error)
        assertEquals(1, io.cmdLogs("failed").size)
        assertNull(d.waitingFor)
        // a late state message is just the device's state, not a second answer
        d.message(state(armed = false, id = 2))
        assertEquals(1, r.size); assertEquals("awake – paused", d.presence())
        // the error stays until a command is confirmed
        val r2 = d.run(DeviceLink.Command(armed = true))
        assertEquals(d.error, "Pause failed: no confirmation from the device within 1500 ms.")
        d.message(state(armed = true, id = 3))
        assertTrue(r2.single().getBoolean("ok")); assertNull(d.error)
    }

    @Test fun aRefusedCommandFailsAtOnceWithTheDevicesReason() {
        val (io, d) = up(armed = true)
        val r = d.run(DeviceLink.Command(mode = "cursor"))
        d.writeDone(0); io.advance(80)
        // the refusal is the normal state reply (nothing changed) plus the reason
        d.message(state(armed = true, mode = "gesture", id = 2).put("rejected", "bad value for mode"))
        assertFalse(r.single().getBoolean("ok")); assertEquals("failed", r.single().getString("result"))
        assertEquals("the device refused it (bad value for mode)", r.single().getString("error"))
        assertEquals(80L, r.single().getLong("ms"))
        assertEquals("Mode cursor failed: the device refused it (bad value for mode).", d.error)
        assertNull(d.waitingFor); assertEquals("gesture", d.mode); assertEquals("listening", d.presence())
        // the timeout is cancelled: no second answer
        io.advance(DeviceLink.CONFIRM_TIMEOUT_MS * 2)
        assertEquals(1, r.size); assertEquals(1, io.cmdLogs("failed").size); assertEquals(0, io.cmdLogs("confirmed").size)
        // the next command goes through
        val r2 = d.run(DeviceLink.Command(armed = false))
        d.message(state(armed = false, id = 3))
        assertTrue(r2.single().getBoolean("ok")); assertNull(d.error)
    }

    @Test fun commandsNeedAReadyLinkAndGoOneAtATime() {
        val io = FakeLink(); val d = DeviceLink(io)
        var r = d.run(DeviceLink.Command(armed = true))
        assertEquals("no device connected", r.single().getString("error")); assertTrue(io.writes.isEmpty())

        d.connected(); d.ready(); d.message(state(true))
        val first = d.run(DeviceLink.Command(armed = false))
        r = d.run(DeviceLink.Command(mode = "cursor"))
        assertEquals("busy: 'pause' is still waiting for the device", r.single().getString("error"))
        assertEquals(1, io.writes.size)
        // a write the stack reports as failed fails at once
        d.writeDone(3)
        assertEquals("the CONFIG write failed (status 3)", first.single().getString("error"))
        // a write that cannot start
        io.refuse = "CONFIG write not started (busy?)"
        r = d.run(DeviceLink.Command(armed = false))
        assertEquals("CONFIG write not started (busy?)", r.single().getString("error")); assertNull(d.waitingFor)
        io.refuse = null
        // the link drops while waiting
        r = d.run(DeviceLink.Command(armed = false))
        assertFalse(d.lost("status 8"))
        assertEquals("the link dropped (status 8)", r.single().getString("error"))
        io.advance(5000)                                                              // the timer was cancelled: no second answer
        assertEquals(1, r.size)
        // no timer outlives its command
        assertEquals(0, io.cmdLogs("failed").count { (it.second["error"] as String).startsWith("no confirmation") })

        for (bad in listOf({ DeviceLink.Command() }, { DeviceLink.Command(armed = true, sleep = true) }, { DeviceLink.Command(mode = "listening") })) {
            try { bad(); throw AssertionError("accepted") } catch (_: IllegalArgumentException) {}
        }
        assertEquals(DeviceLink.Command(armed = false, mode = "cursor"), DeviceLink.Command.from(JSONObject("""{"armed":false,"mode":"cursor","sleep":false}""")))
        assertEquals(DeviceLink.Command(sleep = true), DeviceLink.Command.from(JSONObject("""{"sleep":true,"armed":null}""")))
    }

    // --- sleep, wake, disconnect ------------------------------------------------------------------------------------------

    @Test fun theSleepingMessageMeansAsleepAndAQuietReconnect() {
        val (io, d) = up(armed = true)
        val msg = state(armed = false, sleeping = true, id = 7)
        d.message(msg)
        assertTrue(d.asleep); assertEquals(false, d.armed); assertEquals("asleep", d.presence())
        assertTrue(io.logs.any { it.first == "ble" && it.second["what"] == "asleep" })
        // The service disarms on it (a sleeping device is never armed, whatever the message says).
        val fm = FeatureMessage.parse(msg)
        assertTrue(fm.sleeping); assertFalse(fm.armed)
        assertFalse(FeatureMessage.parse(state(armed = true, sleeping = true)).armed)
        // The drop that follows is expected: true = reconnect quietly, no second disarm.
        assertTrue(d.lost("disconnected (status 19)"))
        // While it sleeps, nothing escalates to "pairing needed" and no error is shown.
        repeat(5) { assertNull(d.authFailure(addr, AuthFailures.Problem.UNKNOWN)) }
        assertNull(d.hint); assertNull(d.error); assertEquals("asleep", d.presence())
        // Commands are refused with the reason, and nothing is written.
        assertEquals("the device is asleep (5 presses wake it)", d.run(DeviceLink.Command(armed = true)).single().getString("error"))
        assertTrue(io.writes.isEmpty())
    }

    @Test fun wakingWithFivePressesReconnectsArmedAndTheAppFollows() {
        val (io, d) = up(armed = true)
        d.message(state(armed = false, sleeping = true, id = 7)); d.lost("status 19")
        // 5 presses: the device advertises; the background connect reaches it.
        d.connected()
        assertFalse(d.asleep)
        assertTrue(io.logs.any { it.first == "ble" && it.second["what"] == "awake" })
        d.ready()
        val onConnect = state(armed = true, id = 1)                                   // ids restart after the device's sleep
        d.message(onConnect)
        assertEquals("listening", d.presence()); assertEquals(true, d.armed)
        assertTrue(FeatureMessage.parse(onConnect).armed)                              // the service arms from this message
        assertTrue(io.writes.isEmpty())                                               // the app sent nothing
    }

    @Test fun anUnexpectedDisconnectComesBackDisarmedAndTheAppDoesNotArmIt() {
        val (io, d) = up(armed = true)
        assertEquals("listening", d.presence())
        // Out of range: not asleep, so the source disarms and reconnects with backoff.
        assertFalse(d.lost("disconnected (status 8)"))
        assertEquals("connecting", d.presence())
        d.connected(); d.ready()
        d.message(state(armed = false, id = 12))                                      // the device stayed disarmed
        assertEquals("awake – paused", d.presence())
        assertFalse(FeatureMessage.parse(state(armed = false)).armed)
        io.advance(60_000)
        assertTrue("the app must not arm the device by itself", io.writes.isEmpty())
    }

    // --- pairing --------------------------------------------------------------------------------------------------------

    @Test fun pairingFailuresEscalateToAHintThatSaysWhatToDo() {
        val io = FakeLink(); val d = DeviceLink(io)
        assertNull(d.authFailure(addr, AuthFailures.Problem.WINDOW_CLOSED))           // one failure: retry
        assertEquals(hold, d.authFailure(addr, AuthFailures.Problem.WINDOW_CLOSED))   // two: stop and say what to do
        assertEquals("pairing needed", d.presence())
        d.clearPairing()                                                              // the user pressed Connect
        assertNull(d.hint); assertEquals("connecting", d.presence())
        assertNull(d.authFailure(addr, AuthFailures.Problem.STALE_BOND))
        val h = d.authFailure(addr, AuthFailures.Problem.STALE_BOND)!!
        assertTrue(h.startsWith("Forget VOX-2807 in the phone's Bluetooth settings")); assertTrue(h.endsWith(hold))
        d.connected(); d.ready()                                                      // paired again
        assertNull(d.hint); assertEquals(0, d.authFailures.count)
        assertTrue(io.writes.isEmpty())
    }
}
