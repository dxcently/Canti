package ai.vox.companion

import android.Manifest
import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.BluetoothStatusCodes
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.ParcelUuid
import android.os.SystemClock
import org.json.JSONArray
import org.json.JSONObject

/**
 * BLE GATT client for the VOX Pico 2 W (PROTOCOL.md "BLE GATT link (v1)").
 *
 * Connection: connect (LE) -> high connection priority -> request MTU 517 (works at whatever is granted, down to 23)
 * -> discover services -> read INFO (logged `ble_info`) -> bond (LE Secure Connections, Just Works; skipped when INFO
 * says `insecure`) -> enable EVENT notifications -> `ready`. Notifications are reassembled ([Reassembler]), decoded
 * ([BleMessages]) and handed to the same [Sink] as the debug sources, as source "ble" ("ble-connect" for the first
 * message of each link, where the service forgets the last message id: the device's ids restart on every boot). A
 * dropped link disarms the app (a synthetic `armed:false` message, source "ble-disconnect") and is retried with
 * backoff (1 s doubling to 30 s; after 5 failed attempts the stack's background auto-connect takes over, which waits
 * for the device without a timeout). Pairing/encryption failures are not retried forever ([AuthFailures]): the state
 * becomes `needs_pairing` with a [hint] (hold the button 5 s to open the pairing window; forget a stale bond).
 *
 * The device side of things (its arm state, mode and sleep, the app's CONFIG commands and their confirmation, the
 * pairing policy) is [DeviceLink], plain JVM code; this class feeds it. After the device's `sleeping` message the link
 * drop is expected: the source waits for the device with the background auto-connect, quietly (state `waiting`,
 * presence `asleep`), and does not disarm a second time.
 *
 * Everything runs on the main thread: the Bluetooth callbacks post to it. Control: [scan], [connect], [disconnect],
 * [forget], [status], [writeConfig], [command] (debug ops `ble_*` and `device` in VoxService). The remembered device is the setting
 * `ble_device`; it is set on the first successful connection and used at start-up.
 *
 * Not testable on the emulator (no real Bluetooth): see README "BLE end-to-end test".
 */
@SuppressLint("MissingPermission")   // every Bluetooth call is behind hasConnect() / hasScan()
class BleFeatureSource(private val ctx: Context, private val settings: Settings) : FeatureSource {
    override val name = "ble"
    private val main = Handler(Looper.getMainLooper())
    private val manager = ctx.getSystemService(BluetoothManager::class.java)
    private val adapter: BluetoothAdapter? get() = manager?.adapter
    private var sink: Sink? = null

    /** NEEDS_PAIRING: pairing/encryption failed repeatedly; no retries until the bond is removed or [connect] is called. */
    enum class State { OFF, IDLE, SCANNING, CONNECTING, DISCOVERING, BONDING, SUBSCRIBING, READY, WAITING, NEEDS_PAIRING }
    var state = State.IDLE; private set
    private var why = ""                       // last state change reason (status)

    // The device we want to be connected to (null = none: idle), and the live GATT object.
    private var target: String? = null
    private var gatt: BluetoothGatt? = null
    private var mtu = BleProtocol.MTU_DEFAULT
    private var info: BleInfo? = null
    private var readySince = 0L
    private val backoff = Backoff()
    private var retry: Runnable? = null
    private var retryAt = 0L
    private var watchdog: Runnable? = null
    private val reasm = Reassembler()
    private var messages = 0L; private var gaps = 0L; private var bad = 0L
    // The first message of each link (normally the device's state message) is delivered as CONNECT_SOURCE: the device's
    // message ids restart at 1 on every boot, so the service forgets the last id it saw there.
    private var firstOfLink = true
    /** The device's state and the app's commands (plain JVM, see [DeviceLink]). */
    val link = DeviceLink(object : DeviceLink.Io {
        override fun write(bytes: ByteArray): String? = startWrite(bytes)
        override fun later(ms: Long, r: () -> Unit): () -> Unit { val x = Runnable(r); main.postDelayed(x, ms); return { main.removeCallbacks(x) } }
        override fun now() = SystemClock.elapsedRealtime()
        override fun log(ev: String, vararg fields: Pair<String, Any?>) { EventLog.ev(ev, *fields) }
    })
    /** Shown to the user while [State.NEEDS_PAIRING]. */
    val hint: String? get() = link.hint

    // Scan results (address -> name, rssi), for ble_status / ble_connect auto.
    private class Found(val name: String?, var rssi: Int, var seen: Long)
    private val found = LinkedHashMap<String, Found>()
    private var scanning: ScanCallback? = null
    private var connectAfterScan = false

    // --- lifecycle ---------------------------------------------------------------------------------------------------

    override fun start(sink: Sink) {
        this.sink = sink
        val filter = IntentFilter().apply { addAction(BluetoothDevice.ACTION_BOND_STATE_CHANGED); addAction(BluetoothAdapter.ACTION_STATE_CHANGED) }
        // System broadcasts only; NOT_EXPORTED still receives them.
        if (Build.VERSION.SDK_INT >= 33) ctx.registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED) else ctx.registerReceiver(receiver, filter)
        val remembered = settings.bleDevice
        log("start", "remembered" to remembered, "adapter" to adapterState(), "permissions" to permissions())
        if (remembered != null) try { connect(remembered) } catch (e: IllegalArgumentException) { log("connect", "error" to e.message) }
    }

    override fun stop() {
        try { ctx.unregisterReceiver(receiver) } catch (_: Exception) {}
        stopScan("stopped")
        target = null
        cancelTimers()
        closeGatt()
        link.lost("service stopped")
        setState(State.IDLE, "service stopped")
        sink = null
    }

    /** MainActivity calls this after the permission dialog; retries whatever was wanted. */
    fun permissionsChanged() {
        log("permissions", "permissions" to permissions())
        if (target != null && gatt == null && state != State.NEEDS_PAIRING) attempt()
    }

    // --- control -----------------------------------------------------------------------------------------------------

    /** Scan for [ms] with the VOX service UUID filter; results are logged (`ble_found`) and kept for [status]. */
    fun scan(ms: Long = 10_000, thenConnect: Boolean = false): JSONObject {
        val a = usableAdapter() ?: return error("bluetooth unavailable: ${adapterState()}")
        if (!hasScan()) return error("no Bluetooth scan permission: open the VOX app and press 'Allow Bluetooth'")
        stopScan("restart")
        val scanner = a.bluetoothLeScanner ?: return error("no LE scanner")
        found.clear()
        connectAfterScan = thenConnect
        val cb = object : ScanCallback() {
            override fun onScanResult(callbackType: Int, r: ScanResult) { main.post { onFound(r) } }
            override fun onBatchScanResults(results: MutableList<ScanResult>) { main.post { results.forEach { onFound(it) } } }
            override fun onScanFailed(errorCode: Int) { main.post { log("scan", "result" to "failed", "code" to errorCode); scanning = null; if (state == State.SCANNING) setState(State.IDLE, "scan failed $errorCode") } }
        }
        scanning = cb
        scanner.startScan(listOf(ScanFilter.Builder().setServiceUuid(ParcelUuid(BleProtocol.SERVICE)).build()),
            ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build(), cb)
        if (gatt == null) setState(State.SCANNING, "scan ${ms} ms")
        main.postDelayed({ if (scanning === cb) stopScan("done") }, ms)
        log("scan", "result" to "started", "ms" to ms, "then_connect" to thenConnect)
        return ok()
    }

    private fun onFound(r: ScanResult) {
        val addr = r.device.address
        val name = try { r.scanRecord?.deviceName ?: r.device.name } catch (_: SecurityException) { null }
        val f = found[addr]
        if (f == null) { found[addr] = Found(name, r.rssi, SystemClock.elapsedRealtime()); log("found", "address" to addr, "name" to name, "rssi" to r.rssi) }
        else { f.rssi = r.rssi; f.seen = SystemClock.elapsedRealtime() }
        if (connectAfterScan && scanning != null) {
            stopScan("found")
            try { connect(addr) } catch (e: IllegalArgumentException) { log("connect", "error" to e.message) }
        }
    }

    private fun stopScan(why: String) {
        val cb = scanning ?: return
        scanning = null
        try { if (hasScan()) adapter?.bluetoothLeScanner?.stopScan(cb) } catch (_: Exception) {}
        log("scan", "result" to "stopped", "why" to why, "found" to found.size)
        if (state == State.SCANNING) setState(State.IDLE, "scan $why")
    }

    /** Connect to [address], or "auto": the remembered device, else the strongest one found, else scan and take the first. */
    fun connect(address: String): JSONObject {
        val addr = if (address == "auto") settings.bleDevice ?: found.maxByOrNull { it.value.rssi }?.key else address.uppercase()
        if (addr == null) return scan(thenConnect = true).put("note", "nothing remembered or found yet: scanning, will connect to the first VOX device")
        if (!BluetoothAdapter.checkBluetoothAddress(addr)) return error("not a Bluetooth address: '$address'")
        if (target == addr && gatt != null) return ok().put("note", "already ${state.name.lowercase()}")
        stopScan("connecting")
        link.clearPairing()
        dropLink("switching device")
        cancelTimers()
        // The target is kept even when Bluetooth is off or not permitted yet: turning it on / granting connects.
        target = addr
        backoff.reset()
        attempt()
        if (usableAdapter() == null) return error("bluetooth unavailable (${adapterState()}): will connect to $addr when it is turned on")
        if (!hasConnect()) return error("no Bluetooth connect permission: open the VOX app and press 'Allow Bluetooth'; will connect to $addr then")
        return ok().put("address", addr)
    }

    /** Drop the link and stay disconnected until the next [connect] (the remembered device is kept). */
    fun disconnect(): JSONObject {
        target = null
        cancelTimers()
        dropLink("disconnect requested")
        setState(State.IDLE, "disconnect requested")
        return ok()
    }

    /** Disconnect and forget the remembered device. The Android bond stays (remove it in Bluetooth settings). */
    fun forget(): JSONObject {
        val was = settings.bleDevice
        disconnect()
        settings.bleDevice = null
        log("forget", "address" to was)
        return ok().put("forgot", was ?: JSONObject.NULL)
            .put("note", "the bond is kept by Android; remove it under Settings > Bluetooth if needed")
    }

    /** Write a raw JSON object to CONFIG (e.g. {"v":1,"test_sounds":true}). Needs a ready link. App commands use [command]. */
    fun writeConfig(o: JSONObject): JSONObject {
        link.waitingFor?.let { return error("busy: the device command '${it.label}' is waiting for its confirmation") }
        startWrite(o.toString().toByteArray(Charsets.UTF_8))?.let { return error(it) }
        return ok()
    }

    /** An app command (arm/pause, mode, sleep); [done] gets the outcome once it is confirmed or has failed. */
    fun command(c: DeviceLink.Command, done: (JSONObject) -> Unit) = link.command(c, done)

    /** Starts a CONFIG write; null when started, otherwise why not. The result comes to [DeviceLink.writeDone]. */
    private fun startWrite(bytes: ByteArray): String? {
        val g = gatt ?: return "not connected"
        if (state != State.READY) return "link not ready (${state.name.lowercase()})"
        val c = g.getService(BleProtocol.SERVICE)?.getCharacteristic(BleProtocol.CONFIG) ?: return "device has no CONFIG characteristic"
        if (bytes.size > mtu - 3) return "CONFIG write of ${bytes.size} bytes exceeds MTU $mtu - 3"
        val started = if (Build.VERSION.SDK_INT >= 33) g.writeCharacteristic(c, bytes, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT) == BluetoothStatusCodes.SUCCESS
            else @Suppress("DEPRECATION") run { c.writeType = BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT; c.value = bytes; g.writeCharacteristic(c) }
        log("config_write", "bytes" to bytes.size, "started" to started)
        return if (started) null else "CONFIG write not started (busy?)"
    }

    /**
     * The device for the status screen: null when no device is wanted, `bluetooth off`, `not connected`, or
     * [DeviceLink.presence] (`pairing needed`, `asleep`, `listening`, `awake – paused`, `connecting`).
     */
    fun deviceState(): String? = when {
        target == null && settings.bleDevice == null -> null
        state == State.OFF -> "bluetooth off"
        target == null -> "not connected"
        else -> link.presence()
    }

    fun status(): JSONObject = JSONObject()
        .put("state", state.name.lowercase()).put("why", why).put("adapter", adapterState()).put("permissions", permissions())
        .put("remembered", settings.bleDevice ?: JSONObject.NULL).put("target", target ?: JSONObject.NULL)
        .put("mtu", mtu).put("bonded", target?.let { bondName(it) } ?: JSONObject.NULL)
        .put("info", info?.raw ?: JSONObject.NULL)
        .put("ready_ms", if (state == State.READY) SystemClock.elapsedRealtime() - readySince else JSONObject.NULL)
        .put("reconnect_in_ms", if (retry != null) maxOf(0, retryAt - SystemClock.elapsedRealtime()) else JSONObject.NULL)
        .put("failures", backoff.failures).put("messages", messages).put("fragments", reasm.fragments).put("gaps", gaps).put("bad", bad)
        .put("auth_failures", link.authFailures.count).put("hint", hint ?: JSONObject.NULL)
        .put("device", link.status().put("presence", deviceState() ?: JSONObject.NULL))
        .put("found", JSONArray(found.map { (a, f) -> JSONObject().put("address", a).put("name", f.name ?: JSONObject.NULL).put("rssi", f.rssi) }))

    // --- connection state machine -------------------------------------------------------------------------------------

    private fun attempt() {
        retry = null
        val addr = target ?: return
        val a = usableAdapter() ?: run { setState(State.OFF, "bluetooth ${adapterState()}"); return }
        if (!hasConnect()) { setState(State.OFF, "no connect permission"); return }
        closeGatt()
        reasm.reset(); info = null; mtu = BleProtocol.MTU_DEFAULT; firstOfLink = true
        // A sleeping device is waited for in the background from the start: it may sleep for hours.
        val auto = link.asleep || backoff.failures >= AUTO_CONNECT_AFTER
        val dev = a.getRemoteDevice(addr)
        setState(State.CONNECTING, if (link.asleep) "device asleep: waiting for it to wake" else if (auto) "background auto-connect" else "attempt ${backoff.failures + 1}")
        gatt = dev.connectGatt(ctx, auto, Callback(), BluetoothDevice.TRANSPORT_LE)
        // A direct attempt that hangs is abandoned; the background auto-connect waits for as long as it takes.
        if (!auto) arm(CONNECT_TIMEOUT_MS, "connect timeout")
    }

    private inner class Callback : BluetoothGattCallback() {
        private fun on(g: BluetoothGatt, f: () -> Unit) = main.post { if (g === gatt) f() }

        override fun onConnectionStateChange(g: BluetoothGatt, status: Int, newState: Int) { on(g) {
            if (newState == BluetoothProfile.STATE_CONNECTED && status == BluetoothGatt.GATT_SUCCESS) {
                link.connected()
                setState(State.DISCOVERING, "connected")
                arm(SETUP_TIMEOUT_MS, "setup timeout")
                // The device asks for a 7.5-30 ms interval; Android's default "balanced" priority adds latency.
                log("priority", "high" to g.requestConnectionPriority(BluetoothGatt.CONNECTION_PRIORITY_HIGH))
                if (!g.requestMtu(BleProtocol.MTU_REQUEST)) g.discoverServices()
            } else if (AuthFailures.isAuthFailure(status)) {
                val problem = when {
                    g.device.bondState == BluetoothDevice.BOND_BONDED -> AuthFailures.Problem.STALE_BOND
                    state == State.BONDING -> AuthFailures.Problem.WINDOW_CLOSED
                    else -> AuthFailures.Problem.UNKNOWN
                }
                authFailed("disconnected (status $status)", problem)
            } else lost("disconnected (status $status)")
        } }

        override fun onCharacteristicWrite(g: BluetoothGatt, c: BluetoothGattCharacteristic, status: Int) { on(g) {
            if (c.uuid == BleProtocol.CONFIG) { log("config_write", "status" to status); link.writeDone(status) }
        } }

        override fun onMtuChanged(g: BluetoothGatt, m: Int, status: Int) { on(g) {
            if (status == BluetoothGatt.GATT_SUCCESS) mtu = m
            log("mtu", "mtu" to mtu, "status" to status)
            if (state == State.DISCOVERING && !g.discoverServices()) lost("discoverServices failed")
        } }

        override fun onServicesDiscovered(g: BluetoothGatt, status: Int) { on(g) {
            val svc = g.getService(BleProtocol.SERVICE)
            if (status != BluetoothGatt.GATT_SUCCESS || svc == null) { lost("no VOX service (status $status)"); return@on }
            if (svc.getCharacteristic(BleProtocol.EVENT) == null) { lost("no EVENT characteristic"); return@on }
            val infoC = svc.getCharacteristic(BleProtocol.INFO)
            if (infoC == null || !g.readCharacteristic(infoC)) { log("info", "error" to "INFO not readable"); secure(g) }
        } }

        @Deprecated("API < 33")
        override fun onCharacteristicRead(g: BluetoothGatt, c: BluetoothGattCharacteristic, status: Int) {
            @Suppress("DEPRECATION") val v = c.value?.copyOf() ?: ByteArray(0)
            if (Build.VERSION.SDK_INT < 33) read(g, c, v, status)
        }

        override fun onCharacteristicRead(g: BluetoothGatt, c: BluetoothGattCharacteristic, value: ByteArray, status: Int) = read(g, c, value.copyOf(), status)

        private fun read(g: BluetoothGatt, c: BluetoothGattCharacteristic, v: ByteArray, status: Int) { on(g) {
            if (c.uuid != BleProtocol.INFO) return@on
            if (status == BluetoothGatt.GATT_SUCCESS) try {
                val i = BleInfo.parse(v); info = i
                log("info", "fw" to i.fw, "mic" to i.mic, "fp_version" to i.fpVersion, "insecure" to i.insecure, "raw" to i.raw.toString())
            } catch (e: IllegalArgumentException) { log("info", "error" to e.message) }
            else log("info", "error" to "read status $status")
            secure(g)
        } }

        override fun onDescriptorWrite(g: BluetoothGatt, d: BluetoothGattDescriptor, status: Int) { on(g) {
            if (d.uuid != BleProtocol.CCCD) return@on
            when {
                status == BluetoothGatt.GATT_SUCCESS -> ready()
                // Bonded, yet the device wants encryption: its keys are gone (re-flashed).
                AuthFailures.isAuthFailure(status) && g.device.bondState == BluetoothDevice.BOND_BONDED ->
                    authFailed("enabling notifications failed (status $status) although bonded", AuthFailures.Problem.STALE_BOND)
                // Android starts pairing itself on these; the bond receiver subscribes again once bonded.
                status == GATT_INSUFFICIENT_AUTHENTICATION || status == GATT_INSUFFICIENT_ENCRYPTION ->
                    { setState(State.BONDING, "encryption required (status $status)"); arm(BOND_TIMEOUT_MS, "bond timeout") }
                else -> lost("enabling notifications failed (status $status)")
            }
        } }

        @Deprecated("API < 33")
        override fun onCharacteristicChanged(g: BluetoothGatt, c: BluetoothGattCharacteristic) {
            @Suppress("DEPRECATION") val v = c.value?.copyOf() ?: ByteArray(0)
            if (Build.VERSION.SDK_INT < 33) changed(g, c, v)
        }

        override fun onCharacteristicChanged(g: BluetoothGatt, c: BluetoothGattCharacteristic, value: ByteArray) = changed(g, c, value.copyOf())

        private fun changed(g: BluetoothGatt, c: BluetoothGattCharacteristic, v: ByteArray) { on(g) {
            if (c.uuid == BleProtocol.EVENT) notification(v)
        } }
    }

    /** After INFO: bond unless bonded (or the firmware says it runs without encryption), then subscribe. */
    private fun secure(g: BluetoothGatt) {
        val dev = g.device
        when {
            dev.bondState == BluetoothDevice.BOND_BONDED -> subscribe(g)
            info?.insecure == true -> { log("bond", "result" to "skipped: INFO says insecure (debug firmware)"); subscribe(g) }
            dev.bondState == BluetoothDevice.BOND_BONDING -> { setState(State.BONDING, "bonding in progress"); arm(BOND_TIMEOUT_MS, "bond timeout") }
            else -> {
                setState(State.BONDING, "bonding")
                arm(BOND_TIMEOUT_MS, "bond timeout")
                if (!dev.createBond()) lost("createBond failed")
            }
        }
    }

    private fun subscribe(g: BluetoothGatt) {
        val c = g.getService(BleProtocol.SERVICE)?.getCharacteristic(BleProtocol.EVENT) ?: run { lost("no EVENT characteristic"); return }
        val d = c.getDescriptor(BleProtocol.CCCD) ?: run { lost("EVENT has no CCCD"); return }
        setState(State.SUBSCRIBING, "enabling notifications")
        arm(SETUP_TIMEOUT_MS, "subscribe timeout")
        g.setCharacteristicNotification(c, true)
        val v = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
        val started = if (Build.VERSION.SDK_INT >= 33) g.writeDescriptor(d, v) == BluetoothStatusCodes.SUCCESS
            else @Suppress("DEPRECATION") run { d.value = v; g.writeDescriptor(d) }
        if (!started) lost("CCCD write not started")
    }

    private fun ready() {
        cancelWatchdog()
        backoff.reset()
        link.ready()
        // No reasm.reset() here: attempt() already reset it for this connection, and the device's state message
        // (counter 0, sent as soon as the CCCD is written) may be delivered before this callback.
        readySince = SystemClock.elapsedRealtime()
        val addr = target
        if (addr != null && settings.bleDevice != addr) { settings.bleDevice = addr; log("remember", "address" to addr) }
        setState(State.READY, "notifications on, mtu $mtu")
    }

    private fun notification(v: ByteArray) {
        for (o in reasm.feed(v)) when (o) {
            is Reassembler.Out.Gap -> { gaps++; EventLog.ev("ble_gap", "expected" to o.expected, "got" to o.got, "dropped_bytes" to o.dropped) }
            is Reassembler.Out.Bad -> { bad++; EventLog.ev("ble_bad", "reason" to o.reason) }
            is Reassembler.Out.Message -> try {
                val msg = BleMessages.decode(o.bytes)
                messages++
                link.message(msg)
                val src = if (firstOfLink) CONNECT_SOURCE else name
                firstOfLink = false
                sink?.deliver(msg, src)
            } catch (e: IllegalArgumentException) {
                bad++; EventLog.ev("ble_bad", "reason" to e.message, "bytes" to o.bytes.size)
            } catch (e: Exception) {
                EventLog.ev("error", "where" to "ble deliver", "error" to e.toString())
            }
        }
    }

    /**
     * The link is gone or failed: disarm if it was up, and retry while a device is wanted. After the device's `sleeping`
     * message the drop is expected: no second disarm, and the device is waited for quietly in the background.
     */
    private fun lost(reason: String) {
        val wasReady = state == State.READY
        cancelWatchdog()
        closeGatt()
        val asleep = link.lost(reason)
        if (wasReady && !asleep) disarm(reason)
        if (target == null) { setState(State.IDLE, reason); return }
        if (asleep) {
            setState(State.WAITING, "device asleep: waiting for it to wake")
            val r = Runnable { attempt() }
            retry = r; retryAt = SystemClock.elapsedRealtime() + ASLEEP_RETRY_MS
            main.postDelayed(r, ASLEEP_RETRY_MS)
            return
        }
        val d = backoff.next()
        setState(State.WAITING, "$reason; retry in $d ms")
        val r = Runnable { attempt() }
        retry = r; retryAt = SystemClock.elapsedRealtime() + d
        main.postDelayed(r, d)
    }

    /**
     * A pairing or encryption failure. Retrying cannot fix stale keys (every flash erases the device's bonds) or a
     * closed pairing window, so after [AuthFailures.LIMIT] in a row the link stops and tells the user what to do
     * ([DeviceLink.authFailure]); removing the bond, or [connect], starts again.
     */
    private fun authFailed(reason: String, problem: AuthFailures.Problem) {
        val addr = target
        val h = addr?.let { link.authFailure(it, problem) }
        if (addr == null || h == null) { lost("$reason; pairing problem ${link.authFailures.count}/${AuthFailures.LIMIT} (${problem.name.lowercase()})"); return }
        val wasReady = state == State.READY
        cancelTimers()
        try { gatt?.disconnect() } catch (_: Exception) {}
        closeGatt()
        link.lost(reason)
        if (wasReady) disarm(reason)
        log("auth_failed", "reason" to reason, "problem" to problem.name.lowercase(), "failures" to link.authFailures.count,
            "bonded" to bondName(addr), "hint" to hint)
        setState(State.NEEDS_PAIRING, reason)
    }

    /** Disconnect = disarm (PROTOCOL.md): the same path as a device message with armed:false. */
    private fun disarm(reason: String) {
        log("disarm", "reason" to reason)
        try { sink?.deliver(JSONObject().put("v", 1).put("armed", false).put("sounds", JSONArray()).put("sequence", JSONArray()), DISCONNECT_SOURCE) }
        catch (e: Exception) { EventLog.ev("error", "where" to "ble disarm", "error" to e.toString()) }
    }

    /** Close the current link on purpose (no retry here; the caller decides). */
    private fun dropLink(reason: String) {
        if (gatt == null) return
        val wasReady = state == State.READY
        try { gatt?.disconnect() } catch (_: Exception) {}
        closeGatt()
        link.lost(reason)
        if (wasReady) disarm(reason)
    }

    private fun closeGatt() {
        val g = gatt ?: return
        gatt = null
        try { g.close() } catch (_: Exception) {}
    }

    private fun arm(ms: Long, reason: String) {
        cancelWatchdog()
        val g = gatt
        val r = Runnable { if (gatt === g && gatt != null) { try { gatt?.disconnect() } catch (_: Exception) {}; lost(reason) } }
        watchdog = r
        main.postDelayed(r, ms)
    }

    private fun cancelWatchdog() { watchdog?.let { main.removeCallbacks(it) }; watchdog = null }
    private fun cancelTimers() { cancelWatchdog(); retry?.let { main.removeCallbacks(it) }; retry = null }

    private val receiver = object : BroadcastReceiver() {
        override fun onReceive(c: Context, i: Intent) {
            when (i.action) {
                BluetoothDevice.ACTION_BOND_STATE_CHANGED -> {
                    val dev: BluetoothDevice? = if (Build.VERSION.SDK_INT >= 33) i.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE, BluetoothDevice::class.java)
                        else @Suppress("DEPRECATION") i.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE)
                    if (dev == null || dev.address != target) return
                    val s = i.getIntExtra(BluetoothDevice.EXTRA_BOND_STATE, BluetoothDevice.ERROR)
                    val prev = i.getIntExtra(BluetoothDevice.EXTRA_PREVIOUS_BOND_STATE, BluetoothDevice.ERROR)
                    log("bond", "state" to bondName(s), "previous" to bondName(prev))
                    // The user removed the stale bond (the hint's advice): pair again from scratch.
                    if (state == State.NEEDS_PAIRING && s == BluetoothDevice.BOND_NONE) {
                        link.clearPairing(); backoff.reset(); attempt(); return
                    }
                    val g = gatt ?: return
                    if (state != State.BONDING) return
                    if (s == BluetoothDevice.BOND_BONDED) subscribe(g)
                    // Bonding refused: the device accepts new bonds only while its pairing window is open.
                    else if (s == BluetoothDevice.BOND_NONE && prev == BluetoothDevice.BOND_BONDING) authFailed("bonding failed", AuthFailures.Problem.WINDOW_CLOSED)
                }
                BluetoothAdapter.ACTION_STATE_CHANGED -> {
                    val s = i.getIntExtra(BluetoothAdapter.EXTRA_STATE, BluetoothAdapter.ERROR)
                    log("adapter", "state" to adapterState())
                    if (s == BluetoothAdapter.STATE_OFF) {
                        // Keep the target: the link comes back when Bluetooth does.
                        cancelTimers()
                        if (state == State.READY) disarm("bluetooth turned off")
                        closeGatt()
                        link.lost("bluetooth off")
                        setState(State.OFF, "bluetooth off")
                    }
                    if (s == BluetoothAdapter.STATE_ON && target != null && gatt == null && state != State.NEEDS_PAIRING) { backoff.reset(); attempt() }
                }
            }
        }
    }

    // --- helpers -----------------------------------------------------------------------------------------------------

    private fun setState(s: State, reason: String) {
        if (s == state && reason == why) return
        state = s; why = reason
        log("state", "state" to s.name.lowercase(), "why" to reason, "address" to target)
    }

    private fun log(what: String, vararg f: Pair<String, Any?>) { EventLog.ev("ble", "what" to what, *f) }
    private fun ok() = JSONObject().put("ok", true).put("ble", status())
    private fun error(msg: String): JSONObject = throw IllegalArgumentException(msg)

    private fun usableAdapter(): BluetoothAdapter? = adapter?.takeIf { it.isEnabled }
    private fun adapterState() = when { adapter == null -> "none"; adapter!!.isEnabled -> "on"; else -> "off" }

    private fun granted(p: String) = ctx.checkSelfPermission(p) == PackageManager.PERMISSION_GRANTED
    private fun hasConnect() = Build.VERSION.SDK_INT < 31 || granted(Manifest.permission.BLUETOOTH_CONNECT)
    private fun hasScan() = if (Build.VERSION.SDK_INT >= 31) granted(Manifest.permission.BLUETOOTH_SCAN) else granted(Manifest.permission.ACCESS_FINE_LOCATION)
    private fun permissions() = JSONObject().put("scan", hasScan()).put("connect", hasConnect())

    private fun bondName(addr: String): String = try { if (hasConnect()) bondName(adapter?.getRemoteDevice(addr)?.bondState ?: -1) else "unknown" } catch (_: Exception) { "unknown" }
    private fun bondName(s: Int) = when (s) {
        BluetoothDevice.BOND_BONDED -> "bonded"; BluetoothDevice.BOND_BONDING -> "bonding"; BluetoothDevice.BOND_NONE -> "none"; else -> "unknown"
    }

    companion object {
        const val DISCONNECT_SOURCE = "ble-disconnect"
        /** Source of the first message on each link (see [firstOfLink]). */
        const val CONNECT_SOURCE = "ble-connect"
        const val CONNECT_TIMEOUT_MS = 20_000L
        const val SETUP_TIMEOUT_MS = 15_000L
        const val BOND_TIMEOUT_MS = 60_000L
        const val AUTO_CONNECT_AFTER = 5
        /** Between background auto-connect attempts while the device sleeps (one attempt normally waits until it wakes). */
        const val ASLEEP_RETRY_MS = 2_000L
        const val GATT_INSUFFICIENT_AUTHENTICATION = 5
        const val GATT_INSUFFICIENT_ENCRYPTION = 15

        /** The permissions MainActivity asks for. */
        fun runtimePermissions(): Array<String> = if (Build.VERSION.SDK_INT >= 31)
            arrayOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT)
            else arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)
    }
}
