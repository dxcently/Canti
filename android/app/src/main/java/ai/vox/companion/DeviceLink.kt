package ai.vox.companion

import org.json.JSONObject

/**
 * What the app knows about the VOX device, and the app's commands to it, without Android (PROTOCOL.md "BLE GATT link
 * (v1)": *App commands (CONFIG)*, *Sleep and wake*, *Pairing*, *Disconnect*). [BleFeatureSource] feeds it the link's
 * events and every decoded device message; the JVM tests feed it a fake link.
 *
 * - **Commands** ([command]) are written to CONFIG only on a ready link. The confirmation is the device's next
 *   no-sound state message (for `sleep`, its `sleeping: true` message), not the write's success. A reply carrying
 *   `rejected` fails the command at once with the device's reason. No reply within [confirmTimeoutMs] (a write the
 *   Bluetooth stack blocked) is a failure too. Failures are logged `device_cmd{result: failed}` and kept in [error] for
 *   the status screen.
 * - **Sleep**: a `sleeping: true` message marks the device [asleep]. The link drop that follows is expected: [lost]
 *   returns true, and the source reconnects quietly (no backoff escalation, no pairing hint, no second disarm). The
 *   device is awake again as soon as a connection is made ([connected]); its state-on-connect message then says
 *   `armed: true` (woken with 5 presses), which the app follows like any other message.
 * - **Disconnect**: the device comes back disarmed and the app never arms it by itself: nothing here writes unless
 *   asked by [command].
 * - **Pairing**: [authFailure] counts failures and, at the limit, sets [hint] (never while the device sleeps).
 */
class DeviceLink(private val io: Io, val confirmTimeoutMs: Long = CONFIRM_TIMEOUT_MS) {
    interface Io {
        /** Starts a CONFIG write; null when started, otherwise why not. */
        fun write(bytes: ByteArray): String?
        /** Runs [r] after [ms] on the same thread; returns a canceller. */
        fun later(ms: Long, r: () -> Unit): () -> Unit
        fun now(): Long
        fun log(ev: String, vararg fields: Pair<String, Any?>)
    }

    /** One app command. `armed` and `mode` may go together; `sleep` goes alone. */
    data class Command(val armed: Boolean? = null, val mode: String? = null, val sleep: Boolean = false) {
        init {
            require(sleep || armed != null || mode != null) { "a device command needs armed, mode or sleep" }
            require(!sleep || (armed == null && mode == null)) { "sleep cannot be combined with armed or mode" }
            require(mode == null || mode in MODES) { "mode must be one of $MODES, got '$mode'" }
        }

        fun json(): JSONObject = JSONObject().put("v", 1).apply {
            armed?.let { put("armed", it) }
            mode?.let { put("mode", it) }
            if (sleep) put("sleep", true)
        }

        val label: String get() = if (sleep) "sleep"
            else listOfNotNull(armed?.let { if (it) "arm" else "pause" }, mode?.let { "mode $it" }).joinToString(" + ")

        /** Whether a state message shows the command applied (it may not: the button and the app are equal, the latest wins). */
        // A stay-awake build (VOX_SLEEP_STAYS_AWAKE) answers sleep with a plain disarm: that counts as applied too.
        fun appliedIn(m: JSONObject): Boolean = if (sleep) m.optBoolean("sleeping", false) || !m.optBoolean("armed", true)
            else (armed == null || m.optBoolean("armed", true) == armed) && (mode == null || m.optString("mode") == mode)

        companion object {
            val MODES = setOf("gesture", "cursor")

            /** From a control op or UI call: `armed` (bool), `mode` (str), `sleep` (bool); absent or null = not sent. */
            fun from(o: JSONObject): Command = Command(
                armed = if (o.has("armed") && !o.isNull("armed")) o.getBoolean("armed") else null,
                mode = if (o.has("mode") && !o.isNull("mode")) o.getString("mode") else null,
                sleep = o.optBoolean("sleep", false),
            )
        }
    }

    /** The link is encrypted and subscribed: commands can be sent. */
    var ready = false; private set
    /** The device's last word (null until it has spoken on some link). */
    var armed: Boolean? = null; private set
    var mode: String? = null; private set
    /** The device said it is going to sleep, and has not been reached since. */
    var asleep = false; private set
    /** The last command failure, until a command is confirmed or a new link is ready. */
    var error: String? = null; private set
    /** What the user must do to pair again; null unless pairing failed [AuthFailures.LIMIT] times in a row. */
    var hint: String? = null; private set
    val authFailures = AuthFailures()

    private class Pending(val cmd: Command, val t0: Long, val done: (JSONObject) -> Unit) { var cancel: () -> Unit = {} }
    private var pending: Pending? = null
    /** The command waiting for its confirmation, if any. */
    val waitingFor: Command? get() = pending?.cmd

    /**
     * The device as the status screen names it: `pairing needed`, `asleep`, `listening`, `awake – paused`, or
     * `connecting` (the source knows better when Bluetooth is off or no device is wanted).
     */
    fun presence(): String = when {
        hint != null -> "pairing needed"
        asleep -> "asleep"
        ready && armed == true -> "listening"
        ready -> "awake – paused"
        else -> "connecting"
    }

    // --- link events --------------------------------------------------------------------------------------------------

    /** A connection was made: whatever it said before, the device is awake now. */
    fun connected() {
        if (asleep) { asleep = false; io.log("ble", "what" to "awake") }
    }

    /** Encrypted and subscribed. */
    fun ready() {
        ready = true; asleep = false
        authFailures.reset(); hint = null; error = null
    }

    /**
     * The link is gone. Fails a waiting command. Returns true when the drop was expected because the device went to
     * sleep: reconnect quietly, and do not disarm again (its `sleeping` message already did).
     */
    fun lost(reason: String): Boolean {
        ready = false
        pending?.let { fail(it, "the link dropped ($reason)") }
        return asleep
    }

    /** Every decoded device message, before the service handles it. */
    fun message(m: JSONObject) {
        val sleeping = m.optBoolean("sleeping", false)
        armed = !sleeping && m.optBoolean("armed", true)
        m.optString("mode").takeIf { it in Command.MODES }?.let { mode = it }
        if (sleeping && !asleep) { asleep = true; io.log("ble", "what" to "asleep") }
        val stateMessage = (m.optJSONArray("sounds")?.length() ?: 0) == 0 && (!m.has("phrase") || m.isNull("phrase"))
        val p = pending ?: return
        if (!stateMessage) return
        // The device answers every command it receives; a refusal is the same reply with the reason (PROTOCOL.md *Replies*).
        val rejected = if (m.has("rejected") && !m.isNull("rejected")) m.optString("rejected").ifBlank { "no reason given" } else null
        if (rejected != null) fail(p, "the device refused it ($rejected)") else confirm(p, m)
    }

    /** The CONFIG write finished (GATT status; 0 = success). A failed write fails the waiting command at once. */
    fun writeDone(status: Int) {
        val p = pending ?: return
        if (status != 0) fail(p, "the CONFIG write failed (status $status)")
    }

    // --- commands -----------------------------------------------------------------------------------------------------

    /** Sends [c]; [done] gets `{ok, cmd, result: confirmed|failed, error?, ms?, applied?, armed?, mode?, sleeping?}` exactly once. */
    fun command(c: Command, done: (JSONObject) -> Unit) {
        val refuse = when {
            !ready -> if (asleep) "the device is asleep (5 presses wake it)" else "no device connected"
            pending != null -> "busy: '${pending!!.cmd.label}' is still waiting for the device"
            else -> null
        }
        if (refuse != null) { finish(Pending(c, io.now(), done), false, "failed", refuse, null); return }
        val p = Pending(c, io.now(), done)
        pending = p
        val bytes = c.json().toString().toByteArray(Charsets.UTF_8)
        io.write(bytes)?.let { fail(p, it); return }
        io.log("device_cmd", "cmd" to c.label, "result" to "sent", "config" to c.json().toString())
        p.cancel = io.later(confirmTimeoutMs) { if (pending === p) fail(p, "no confirmation from the device within $confirmTimeoutMs ms") }
    }

    private fun confirm(p: Pending, m: JSONObject) {
        val applied = p.cmd.appliedIn(m)
        error = null
        finish(p, true, "confirmed", null, m, applied)
    }

    private fun fail(p: Pending, why: String) {
        error = "${p.cmd.label.replaceFirstChar { it.uppercase() }} failed: $why."
        finish(p, false, "failed", why, null)
    }

    private fun finish(p: Pending, ok: Boolean, result: String, why: String?, m: JSONObject?, applied: Boolean? = null) {
        if (pending === p) { pending = null; p.cancel() }
        val ms = io.now() - p.t0
        io.log("device_cmd", "cmd" to p.cmd.label, "result" to result, "error" to why, "ms" to ms, "applied" to applied,
            "armed" to m?.let { armed }, "mode" to m?.let { mode }, "sleeping" to m?.optBoolean("sleeping", false))
        val r = JSONObject().put("ok", ok).put("cmd", p.cmd.label).put("result", result).put("ms", ms)
        if (why != null) r.put("error", why)
        if (m != null) r.put("applied", applied).put("armed", armed).put("mode", mode ?: JSONObject.NULL).put("sleeping", asleep)
        p.done(r)
    }

    // --- pairing ------------------------------------------------------------------------------------------------------

    /**
     * A pairing or encryption failure. Returns the hint when it is time to stop retrying, else null. A sleeping device
     * cannot be the cause, so nothing escalates while [asleep].
     */
    fun authFailure(address: String, problem: AuthFailures.Problem): String? {
        if (asleep) return null
        if (!authFailures.record()) return null
        hint = AuthFailures.hint(address, problem)
        return hint
    }

    /** The user acted (connect again, or removed the bond): start pairing afresh. */
    fun clearPairing() { authFailures.reset(); hint = null }

    fun status(): JSONObject = JSONObject().put("presence", presence()).put("ready", ready).put("asleep", asleep)
        .put("armed", armed ?: JSONObject.NULL).put("mode", mode ?: JSONObject.NULL)
        .put("waiting_for", waitingFor?.label ?: JSONObject.NULL).put("error", error ?: JSONObject.NULL)

    companion object {
        const val CONFIRM_TIMEOUT_MS = 1500L
    }
}
