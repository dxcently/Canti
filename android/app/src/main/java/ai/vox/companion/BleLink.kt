package ai.vox.companion

import org.json.JSONObject
import org.json.JSONTokener
import java.nio.ByteBuffer
import java.nio.charset.CharacterCodingException
import java.nio.charset.CodingErrorAction
import java.util.UUID

/**
 * The BLE GATT link (PROTOCOL.md "BLE GATT link (v1)"), without Android: UUIDs, fragment reassembly, message
 * decoding, INFO parsing, reconnect backoff. [BleFeatureSource] drives it from the Bluetooth callbacks; the JVM tests
 * drive it directly.
 */
object BleProtocol {
    val SERVICE: UUID = UUID.fromString("ac740001-3c66-cc47-6290-e0e7094c17b9")
    val EVENT: UUID = UUID.fromString("ac740002-3c66-cc47-6290-e0e7094c17b9")
    val CONFIG: UUID = UUID.fromString("ac740003-3c66-cc47-6290-e0e7094c17b9")
    val INFO: UUID = UUID.fromString("ac740004-3c66-cc47-6290-e0e7094c17b9")
    /** Client Characteristic Configuration descriptor (enables notifications). */
    val CCCD: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
    const val MTU_REQUEST = 517
    const val MTU_DEFAULT = 23
    const val LAST = 0x80
    const val FIRST = 0x40
    const val COUNTER_MASK = 0x3f
    /** The protocol's message limit (UTF-8 bytes, headers excluded). Anything larger is a device bug and is dropped. */
    const val MAX_MESSAGE_BYTES = 4096
    const val NAME_PREFIX = "VOX-"

    /**
     * Splits one message into EVENT notifications for [mtu] (each at most mtu - 3 bytes: 1 header byte + chunk), the
     * counters starting at [counter]. This is the device's side; the app uses it only in tests and fixtures.
     */
    fun fragment(msg: ByteArray, mtu: Int, counter: Int): List<ByteArray> {
        val chunk = mtu - 3 - 1
        require(chunk >= 1) { "MTU $mtu too small" }
        val n = maxOf(1, (msg.size + chunk - 1) / chunk)
        return List(n) { i ->
            val part = msg.copyOfRange(i * chunk, minOf(msg.size, (i + 1) * chunk))
            val h = ((counter + i) and COUNTER_MASK) or (if (i == 0) FIRST else 0) or (if (i == n - 1) LAST else 0)
            byteArrayOf(h.toByte()) + part
        }
    }
}

/**
 * Reassembles EVENT notifications into messages. `[header][chunk]`; header bit 7 = last fragment of a message,
 * bit 6 = first fragment (both on a single-fragment message), bits 0-5 = a counter, 0 for the first notification of
 * a connection, +1 per notification (mod 64) across messages.
 *
 * A message starts at a first fragment and ends at a last one. A skipped counter drops the partial message
 * ([Out.Gap], logged as `ble_gap`); fragments are then ignored until the next first fragment. Also dropped, as
 * [Out.Bad]: a message longer than [maxBytes], a continuation fragment with no message open (other than after a
 * gap), and a partial message cut short by a new first fragment.
 *
 * Call [reset] on every new connection: the next notification is expected to carry counter 0.
 */
class Reassembler(val maxBytes: Int = BleProtocol.MAX_MESSAGE_BYTES) {
    sealed class Out {
        class Message(val bytes: ByteArray) : Out()
        /** Counter [got] where [expected] was due; [dropped] bytes of a partial message were discarded. */
        data class Gap(val expected: Int, val got: Int, val dropped: Int) : Out()
        /** A notification that could not be used (see the class comment). */
        data class Bad(val reason: String) : Out()
    }

    private enum class Mode { IDLE, IN_MESSAGE, SKIPPING }

    private val buf = java.io.ByteArrayOutputStream()
    private var expected = 0
    private var mode = Mode.IDLE
    var fragments = 0L; private set

    fun reset() { buf.reset(); expected = 0; mode = Mode.IDLE }

    fun feed(n: ByteArray): List<Out> {
        if (n.isEmpty()) return listOf(Out.Bad("empty notification"))
        fragments++
        val out = mutableListOf<Out>()
        val h = n[0].toInt() and 0xff
        val first = h and BleProtocol.FIRST != 0
        val last = h and BleProtocol.LAST != 0
        val ctr = h and BleProtocol.COUNTER_MASK
        if (ctr != expected) {
            out += Out.Gap(expected, ctr, buf.size())
            buf.reset()
            mode = Mode.SKIPPING
        }
        expected = (ctr + 1) and BleProtocol.COUNTER_MASK
        if (first) {
            if (mode == Mode.IN_MESSAGE) out += Out.Bad("first fragment before the previous message ended: dropped ${buf.size()} bytes")
            buf.reset()
            mode = Mode.IN_MESSAGE
        } else when (mode) {
            Mode.IN_MESSAGE -> {}
            Mode.SKIPPING -> return out
            Mode.IDLE -> { out += Out.Bad("continuation fragment with no first fragment"); mode = Mode.SKIPPING; return out }
        }
        buf.write(n, 1, n.size - 1)
        if (buf.size() > maxBytes) {
            out += Out.Bad("message longer than $maxBytes bytes: dropped")
            buf.reset(); mode = if (last) Mode.IDLE else Mode.SKIPPING
            return out
        }
        if (last) { out += Out.Message(buf.toByteArray()); buf.reset(); mode = Mode.IDLE }
        return out
    }
}

object BleMessages {
    /**
     * One reassembled message: strict UTF-8, exactly one JSON object, a feature message (never a control message:
     * the device cannot drive the app's debug operations). Throws IllegalArgumentException with the reason.
     * The feature fields themselves are validated by [FeatureMessage.parse] in the service.
     */
    fun decode(bytes: ByteArray): JSONObject {
        require(bytes.isNotEmpty()) { "empty message" }
        val text = try {
            Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT)
                .decode(ByteBuffer.wrap(bytes)).toString()
        } catch (e: CharacterCodingException) { throw IllegalArgumentException("not UTF-8") }
        val t = JSONTokener(text)
        val v = try { t.nextValue() } catch (e: Exception) { throw IllegalArgumentException("not JSON: ${e.message?.take(80)}") }
        require(v is JSONObject) { "not a JSON object" }
        require(t.nextClean() == 0.toChar()) { "trailing data after the JSON object" }
        val type = v.optString("type", "features")
        require(type == "features") { "message type '$type' is not accepted over BLE" }
        return v
    }
}

/** The INFO characteristic: `{"v":1,"fw":"0.1.0","mic":"inmp441"|"none","fp_version":"fp1"|null,"insecure":true?}`. */
data class BleInfo(val v: Int, val fw: String, val mic: String, val fpVersion: String?, val insecure: Boolean, val raw: JSONObject) {
    companion object {
        fun parse(bytes: ByteArray): BleInfo {
            val o = try { JSONObject(String(bytes, Charsets.UTF_8)) } catch (e: Exception) { throw IllegalArgumentException("INFO is not a JSON object") }
            val v = o.optInt("v", -1)
            require(v == 1) { "INFO version $v (expected 1)" }
            return BleInfo(v, o.optString("fw", "?"), o.optString("mic", "?"),
                if (o.has("fp_version") && !o.isNull("fp_version")) o.getString("fp_version") else null, o.optBoolean("insecure", false), o)
        }
    }
}

/**
 * Pairing and encryption failures (PROTOCOL.md "Pairing"). New bonds are accepted only while the device's 60 s pairing
 * window is open (button held 5 s), and every firmware flash erases the device's bonds, so retrying cannot fix either:
 * after [LIMIT] failures in a row the link stops and tells the user what to do ([hint]).
 */
class AuthFailures {
    /** Why pairing failed, as far as the phone can tell. */
    enum class Problem {
        /** The phone was bonded but encryption failed: the device lost its keys (re-flashed). */
        STALE_BOND,
        /** The phone was not bonded and bonding was refused: the pairing window was closed. */
        WINDOW_CLOSED,
        /** Could be either. */
        UNKNOWN,
    }

    var count = 0; private set
    /** Records one failed attempt; true when it is time to stop retrying. */
    fun record(): Boolean { count++; return count >= LIMIT }
    fun reset() { count = 0 }

    companion object {
        const val LIMIT = 2
        /**
         * Statuses from onConnectionStateChange / GATT operations that mean the keys do not match: 5 (insufficient
         * authentication; also HCI "authentication failure"), 6 (HCI "PIN or key missing"), 15 (insufficient
         * encryption), 61 (0x3D, link dropped on a MIC failure: wrong key), 137 (0x89, GATT_AUTH_FAIL).
         */
        val STATUSES = setOf(5, 6, 15, 61, 137)
        fun isAuthFailure(status: Int) = status in STATUSES

        /** The advertised name, `VOX-` + the last 2 address bytes (PROTOCOL.md). */
        fun deviceName(address: String) = BleProtocol.NAME_PREFIX + address.replace(":", "").takeLast(4).uppercase()

        const val HOLD = "Hold the VOX button 5 s until the light blinks fast, then connect."

        /** What the user has to do; one line per step. */
        fun hint(address: String, problem: Problem): String {
            val n = deviceName(address)
            return when (problem) {
                Problem.WINDOW_CLOSED -> HOLD
                Problem.STALE_BOND -> "Forget $n in the phone's Bluetooth settings (a firmware flash erased its pairings).\n$HOLD"
                Problem.UNKNOWN -> "If $n was re-flashed, forget it in the phone's Bluetooth settings first.\n$HOLD"
            }
        }
    }
}

/**
 * How late a device message arrived, from the device's own clock (PROTOCOL.md: `timing[].t_end_ms`, a hold's `t_ms`).
 * The clocks are never compared directly: lag = (arrival - device time) - the smallest such offset over the last
 * [window] messages (the clock offset plus the fastest delivery), so it is the delay above the best recent one. A
 * device clock that goes backwards (a reboot) starts over. Pure; BleFeatureSource logs it per message (`ble_rx`).
 */
class ArrivalLag(private val window: Int = 16) {
    private val offsets = ArrayDeque<Long>()
    private var lastDevice: Long? = null

    fun lag(arrivalMs: Long, deviceMs: Long): Long {
        if (lastDevice?.let { deviceMs < it } == true) offsets.clear()
        lastDevice = deviceMs
        val o = arrivalMs - deviceMs
        offsets.addLast(o)
        while (offsets.size > window) offsets.removeFirst()
        return o - offsets.min()
    }

    companion object {
        /** The message's latest device time: a hold's `t_ms`, else the last `timing` entry's `t_end_ms`; null = none. */
        fun deviceMs(m: org.json.JSONObject): Long? {
            if (m.has("t_ms") && !m.isNull("t_ms")) return m.optLong("t_ms")
            val t = m.optJSONArray("timing") ?: return null
            for (i in t.length() - 1 downTo 0) {
                val o = t.optJSONObject(i) ?: continue
                if (o.has("t_end_ms")) return o.getLong("t_end_ms")
            }
            return null
        }
    }
}

/** Reconnect delays: base, 2x each failure, capped; [reset] after a good connection. */
class Backoff(private val baseMs: Long = 1000, private val maxMs: Long = 30_000) {
    var failures = 0; private set
    fun next(): Long { val d = minOf(maxMs, baseMs shl minOf(failures, 20)); failures++; return d }
    fun reset() { failures = 0 }
}

/**
 * How the BLE client retries (pure; BleTest). BleFeatureSource reports each failure's kind and asks before each attempt.
 *
 *  - [Failure.DROP]: no link came up, or an up link went away (device off or away, connect timeout). [Backoff] 1 s
 *    doubling to 30 s; after [autoAfter] in a row the stack's background auto-connect takes over.
 *  - [Failure.SETUP]: a link came up but could not be made ready (INFO / CCCD refused, VOX service or EVENT missing,
 *    setup/subscribe timeout). Seen after a service restart: the phone's stack still had the old link up, the new
 *    client got the cached database within 60 ms, then its read and CCCD write were refused. Retrying on that link
 *    fails the same way, so the client is closed fully (disconnect + close), the next attempt waits at least
 *    [settleMs] (the backoff still doubles), refreshes the GATT cache, and never auto-connects (it would reattach).
 *
 * A link the stack already has up to the device while this client has none (left by a previous service instance or
 * process) is waited out before connecting: up to [staleWaitMs], once per streak (again after each SETUP failure), so
 * a link someone else holds for good does not stall reconnecting.
 */
class LinkRecovery(
    private val backoff: Backoff = Backoff(),
    private val autoAfter: Int = 5,
    private val settleMs: Long = 2_000,
    private val staleWaitMs: Long = 4_000,
) {
    enum class Failure { DROP, SETUP }

    sealed interface Plan {
        /** The stack still has a link to the device that is not ours: poll up to [ms] for it to drop, then ask again. */
        data class WaitForRelease(val ms: Long) : Plan
        /** connectGatt(autoConnect = [autoConnect]); [refreshCache] = clear the GATT cache once connected, before discovery. */
        data class Connect(val autoConnect: Boolean, val refreshCache: Boolean) : Plan
    }

    val failures: Int get() = backoff.failures
    /** SETUP failures in a row (a DROP or ready ends the streak). */
    var setupFailures = 0; private set
    private var waited = false

    /** [staleLink] = the stack has a GATT link to the device and this client none; [asleep] = the device said it sleeps. */
    fun attempt(staleLink: Boolean, asleep: Boolean): Plan {
        if (staleLink && !waited) { waited = true; return Plan.WaitForRelease(staleWaitMs) }
        val auto = setupFailures == 0 && (asleep || backoff.failures >= autoAfter)
        return Plan.Connect(autoConnect = auto, refreshCache = setupFailures > 0 || staleLink)
    }

    /** The attempt failed; returns the delay before the next one. */
    fun failed(f: Failure): Long {
        val d = backoff.next()
        return when (f) {
            Failure.DROP -> { setupFailures = 0; d }
            Failure.SETUP -> { setupFailures++; waited = false; maxOf(settleMs, d) }
        }
    }

    /** The link is ready (or a new connection was asked for): start over. */
    fun reset() { backoff.reset(); setupFailures = 0; waited = false }
}
