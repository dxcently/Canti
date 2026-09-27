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
 * for the device without a timeout). A link that comes up but cannot be set up (INFO or the CCCD write refused: a stale
 * link the stack kept from before a service restart) is closed fully and replaced by a fresh one, with the GATT cache
 * refreshed ([LinkRecovery]). Pairing/encryption failures are not retried forever ([AuthFailures]): the state
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
    private val recovery = LinkRecovery()
    /** Clear the GATT cache when the next link comes up ([LinkRecovery.Plan.Connect.refreshCache]). */
    private var refreshOnConnect = false
    private var started = false
    private val arrival = ArrivalLag()
    /** HIGH priority asked again this link after a slow interval (once per link). */
    private var reRequested = false
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
        // A user's pause of the device outlives the service (a restart must not make it look like a link-drop pause).
        private val prefs get() = ctx.getSharedPreferences("canti_device", Context.MODE_PRIVATE)
        override fun saveUserPaused(paused: Boolean) { prefs.edit().putBoolean("user_paused", paused).apply() }
        override fun loadUserPaused() = prefs.getBoolean("user_paused", false)
    })
    /** Shown to the user while [State.NEEDS_PAIRING]. */
    val hint: String? get() = link.hint

    // Scan results (address -> name, rssi), for ble_status / ble_connect auto.
    private class Found(val name: String?, var rssi: Int, var seen: Long)
    private val found = LinkedHashMap<String, Found>()
    private var scanning: ScanCallback? = null
    private var connectAfterScan = false
    // The first-run search's outcome for the pairing screen: "none found" when a search ended without a device.
    private var scanOutcome: String? = null

    // --- lifecycle ---------------------------------------------------------------------------------------------------

    override fun start(sink: Sink) {
        // One live client per process: a previous service instance that was never stopped would hold the device's
        // single link (the Pico takes one central). Starting twice is a restart.
        live?.takeIf { it !== this }?.let { log("start", "note" to "stopping a previous instance"); it.stop() }
        if (started) stop()
        live = this; started = true
        this.sink = sink
        val filter = IntentFilter().apply { addAction(BluetoothDevice.ACTION_BOND_STATE_CHANGED); addAction(BluetoothAdapter.ACTION_STATE_CHANGED) }
        // System broadcasts only; NOT_EXPORTED still receives them.
        if (Build.VERSION.SDK_INT >= 33) ctx.registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED) else ctx.registerReceiver(receiver, filter)
        val remembered = settings.bleDevice
        log("start", "remembered" to remembered, "adapter" to adapterState(), "permissions" to permissions())
        if (remembered != null) try { connect(remembered) } catch (e: IllegalArgumentException) { log("connect", "error" to e.message) }
    }

    override fun stop() {
        if (live === this) live = null
        started = false
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
        if (target != null && gatt == null && retry == null && state != State.NEEDS_PAIRING) attempt()
    }

    // --- control -----------------------------------------------------------------------------------------------------

    /** Scan for [ms] with the VOX service UUID filter; results are logged (`ble_found`) and kept for [status]. */
    fun scan(ms: Long = 10_000, thenConnect: Boolean = false): JSONObject {
        val a = usableAdapter() ?: return error("bluetooth unavailable: ${adapterState()}")
        if (!hasScan()) return error("no Bluetooth scan permission: open the Canti app and press 'Allow Bluetooth'")
        stopScan("restart")
        val scanner = a.bluetoothLeScanner ?: return error("no LE scanner")
        found.clear()
        connectAfterScan = thenConnect
        scanOutcome = null
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
        if (why == "done" && connectAfterScan && found.isEmpty()) scanOutcome = "none found"
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
        scanOutcome = null
        recovery.reset()
        attempt()
        if (usableAdapter() == null) return error("bluetooth unavailable (${adapterState()}): will connect to $addr when it is turned on")
        if (!hasConnect()) return error("no Bluetooth connect permission: open the Canti app and press 'Allow Bluetooth'; will connect to $addr then")
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

    /**
     * For the first-run pairing screen (VoxService.uiStatus): Bluetooth on/off, the device being connected and its
     * advertised name (`VOX-2807`), and the search (`scanning`, `none found`, or null).
     */
    fun setup(): Map<String, Any?> = mapOf(
        "ble_adapter" to adapterState(),
        "ble_target" to target,
        "ble_target_name" to target?.let { targetName(it) },
        "ble_scan" to if (scanning != null) "scanning" else scanOutcome,
    )

    private fun targetName(addr: String): String? = found[addr]?.name
        ?: try { if (hasConnect()) adapter?.getRemoteDevice(addr)?.name else null } catch (_: Exception) { null }

    fun status(): JSONObject = JSONObject()
        .put("state", state.name.lowercase()).put("why", why).put("adapter", adapterState()).put("permissions", permissions())
        .put("remembered", settings.bleDevice ?: JSONObject.NULL).put("target", target ?: JSONObject.NULL)
        .put("mtu", mtu).put("bonded", target?.let { bondName(it) } ?: JSONObject.NULL)
        .put("info", info?.raw ?: JSONObject.NULL)
        .put("ready_ms", if (state == State.READY) SystemClock.elapsedRealtime() - readySince else JSONObject.NULL)
        .put("reconnect_in_ms", if (retry != null) maxOf(0, retryAt - SystemClock.elapsedRealtime()) else JSONObject.NULL)
        .put("failures", recovery.failures).put("setup_failures", recovery.setupFailures).put("messages", messages).put("fragments", reasm.fragments).put("gaps", gaps).put("bad", bad)
        .put("auth_failures", link.authFailures.count).put("hint", hint ?: JSONObject.NULL)
        .put("device", link.status().put("presence", deviceState() ?: JSONObject.NULL))
        .put("found", JSONArray(found.map { (a, f) -> JSONObject().put("address", a).put("name", f.name ?: JSONObject.NULL).put("rssi", f.rssi) }))

    // --- connection state machine -------------------------------------------------------------------------------------

    private fun attempt() {
        retry?.let { main.removeCallbacks(it) }   // single flight: whoever calls, one pending attempt at most
        retry = null
        val addr = target ?: return
        val a = usableAdapter() ?: run { setState(State.OFF, "bluetooth ${adapterState()}"); return }
        if (!hasConnect()) { setState(State.OFF, "no connect permission"); return }
        closeGatt()
        reasm.reset(); info = null; mtu = BleProtocol.MTU_DEFAULT; firstOfLink = true; reRequested = false
        val dev = a.getRemoteDevice(addr)
        val stale = stackConnected(dev)
        // A sleeping device is waited for in the background from the start: it may sleep for hours ([LinkRecovery]).
        when (val plan = recovery.attempt(stale, link.asleep)) {
            is LinkRecovery.Plan.WaitForRelease -> {
                log("stale_link", "address" to addr, "action" to "wait", "ms" to plan.ms)
                setState(State.CONNECTING, "waiting for the old link to drop")
                waitForRelease(dev, SystemClock.elapsedRealtime() + plan.ms)
            }
            is LinkRecovery.Plan.Connect -> {
                val auto = plan.autoConnect
                refreshOnConnect = plan.refreshCache
                setState(State.CONNECTING, if (link.asleep && auto) "device asleep: waiting for it to wake" else if (auto) "background auto-connect"
                    else "attempt ${recovery.failures + 1}" + (if (recovery.setupFailures > 0) " (fresh link after ${recovery.setupFailures} setup failures)" else "") + (if (stale) " (stale link still up)" else ""))
                gatt = dev.connectGatt(ctx, auto, Callback(), BluetoothDevice.TRANSPORT_LE)
                // A direct attempt that hangs is abandoned; the background auto-connect waits for as long as it takes.
                if (!auto) arm(CONNECT_TIMEOUT_MS, "connect timeout")
            }
        }
    }

    /** True if the phone's stack has a GATT link to [dev] (any client's). Ours is closed when this is asked. */
    private fun stackConnected(dev: BluetoothDevice): Boolean = try {
        manager?.getConnectedDevices(BluetoothProfile.GATT)?.any { it.address == dev.address } == true
    } catch (_: Exception) { false }

    /** Poll until the stack's old link to [dev] is gone or [until], then attempt again (a cancellable [retry]). */
    private fun waitForRelease(dev: BluetoothDevice, until: Long) {
        val r = Runnable {
            retry = null
            val up = stackConnected(dev)
            if (!up || SystemClock.elapsedRealtime() >= until) { log("stale_link", "action" to if (up) "gave up waiting" else "released"); attempt() }
            else waitForRelease(dev, until)
        }
        retry = r; retryAt = until
        main.postDelayed(r, STALE_POLL_MS)
    }

    /** BluetoothGatt.refresh() (hidden): drops the stack's cached database so discovery asks the device. */
    private fun refreshCache(g: BluetoothGatt): Boolean = try {
        g.javaClass.getMethod("refresh").invoke(g) as? Boolean ?: false
    } catch (_: Exception) { false }

    private inner class Callback : BluetoothGattCallback() {
        private fun on(g: BluetoothGatt, f: () -> Unit) = main.post { if (g === gatt) f() }

        override fun onConnectionStateChange(g: BluetoothGatt, status: Int, newState: Int) { on(g) {
            if (newState == BluetoothProfile.STATE_CONNECTED && status == BluetoothGatt.GATT_SUCCESS) {
                link.connected()
                setState(State.DISCOVERING, "connected")
                arm(SETUP_TIMEOUT_MS, "setup timeout", LinkRecovery.Failure.SETUP)
                if (refreshOnConnect) { refreshOnConnect = false; log("gatt_refresh", "ok" to refreshCache(g)) }
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
            if (state == State.DISCOVERING && !g.discoverServices()) lost("discoverServices failed", LinkRecovery.Failure.SETUP)
        } }

        override fun onServicesDiscovered(g: BluetoothGatt, status: Int) { on(g) {
            val svc = g.getService(BleProtocol.SERVICE)
            log("services", "status" to status, "count" to g.services.size, "vox" to (svc != null))
            if (status != BluetoothGatt.GATT_SUCCESS || svc == null) { lost("no VOX service (status $status)", LinkRecovery.Failure.SETUP); return@on }
            if (svc.getCharacteristic(BleProtocol.EVENT) == null) { lost("no EVENT characteristic", LinkRecovery.Failure.SETUP); return@on }
            val infoC = svc.getCharacteristic(BleProtocol.INFO)
            if (infoC == null) { log("info", "error" to "no INFO characteristic"); secure(g); return@on }
            // A refused read on a fresh link is the stale-link symptom; the CCCD write after it decides (SETUP failure).
            if (!g.readCharacteristic(infoC)) { log("info", "error" to "INFO read not started", "properties" to infoC.properties, "bond" to bondName(g.device.bondState)); secure(g) }
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
                else -> lost("enabling notifications failed (status $status)", LinkRecovery.Failure.SETUP)
            }
        } }

        @Deprecated("API < 33")
        override fun onCharacteristicChanged(g: BluetoothGatt, c: BluetoothGattCharacteristic) {
            @Suppress("DEPRECATION") val v = c.value?.copyOf() ?: ByteArray(0)
            if (Build.VERSION.SDK_INT < 33) changed(g, c, v)
        }

        override fun onCharacteristicChanged(g: BluetoothGatt, c: BluetoothGattCharacteristic, value: ByteArray) = changed(g, c, value.copyOf())

        // Stamped on the Binder thread: the wait for the main thread shows as ble_rx.queue_ms.
        private fun changed(g: BluetoothGatt, c: BluetoothGattCharacteristic, v: ByteArray) {
            val at = SystemClock.elapsedRealtime()
            on(g) { if (c.uuid == BleProtocol.EVENT) notification(v, at) }
        }

        /**
         * Hidden in the SDK but called by the stack (BluetoothGattCallback.onConnectionUpdated, API 26+): the link's
         * actual parameters (interval in 1.25 ms units, timeout in 10 ms units). The device's own parameter request
         * (7.5-30 ms) may replace HIGH priority's 11.25-15 ms; then HIGH is asked for again, once per link.
         */
        @Suppress("unused")
        fun onConnectionUpdated(g: BluetoothGatt, interval: Int, latency: Int, timeout: Int, status: Int) { on(g) {
            log("conn_params", "interval_ms" to interval * 1.25, "latency" to latency, "timeout_ms" to timeout * 10, "status" to status)
            if (state == State.READY && interval > HIGH_MAX_INTERVAL && !reRequested) {
                reRequested = true
                log("priority", "high" to g.requestConnectionPriority(BluetoothGatt.CONNECTION_PRIORITY_HIGH), "when" to "slow interval")
            }
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
        val c = g.getService(BleProtocol.SERVICE)?.getCharacteristic(BleProtocol.EVENT) ?: run { lost("no EVENT characteristic", LinkRecovery.Failure.SETUP); return }
        val d = c.getDescriptor(BleProtocol.CCCD) ?: run { lost("EVENT has no CCCD", LinkRecovery.Failure.SETUP); return }
        setState(State.SUBSCRIBING, "enabling notifications")
        arm(SETUP_TIMEOUT_MS, "subscribe timeout", LinkRecovery.Failure.SETUP)
        val local = g.setCharacteristicNotification(c, true)
        val v = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
        // API 33+ says why a write did not start (BluetoothStatusCodes: 201 = busy, 6 = not allowed...).
        val code = if (Build.VERSION.SDK_INT >= 33) g.writeDescriptor(d, v)
            else @Suppress("DEPRECATION") run { d.value = v; if (g.writeDescriptor(d)) BluetoothStatusCodes.SUCCESS else -1 }
        log("cccd_write", "started" to (code == BluetoothStatusCodes.SUCCESS), "code" to code, "local_notify" to local)
        if (code != BluetoothStatusCodes.SUCCESS) lost("CCCD write not started (code $code)", LinkRecovery.Failure.SETUP)
    }

    private fun ready() {
        cancelWatchdog()
        recovery.reset()
        link.ready()
        // No reasm.reset() here: attempt() already reset it for this connection, and the device's state message
        // (counter 0, sent as soon as the CCCD is written) may be delivered before this callback.
        readySince = SystemClock.elapsedRealtime()
        val addr = target
        if (addr != null && settings.bleDevice != addr) { settings.bleDevice = addr; log("remember", "address" to addr) }
        // Asked once after connect; setup (MTU, encryption, the device's parameter request) may have changed it since.
        gatt?.let { g -> log("priority", "high" to g.requestConnectionPriority(BluetoothGatt.CONNECTION_PRIORITY_HIGH), "when" to "ready") }
        setState(State.READY, "notifications on, mtu $mtu")
    }

    private fun notification(v: ByteArray, at: Long = SystemClock.elapsedRealtime()) {
        for (o in reasm.feed(v)) when (o) {
            is Reassembler.Out.Gap -> { gaps++; EventLog.ev("ble_gap", "expected" to o.expected, "got" to o.got, "dropped_bytes" to o.dropped) }
            is Reassembler.Out.Bad -> { bad++; EventLog.ev("ble_bad", "reason" to o.reason) }
            is Reassembler.Out.Message -> try {
                val msg = BleMessages.decode(o.bytes)
                messages++
                val now = SystemClock.elapsedRealtime()
                EventLog.ev("ble_rx", "id" to msg.opt("id"), "bytes" to o.bytes.size, "queue_ms" to now - at,
                    "lag_ms" to ArrivalLag.deviceMs(msg)?.let { arrival.lag(at, it) })
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
    private fun lost(reason: String, failure: LinkRecovery.Failure = LinkRecovery.Failure.DROP) {
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
        val d = recovery.failed(failure)
        if (failure == LinkRecovery.Failure.SETUP) log("setup_failed", "reason" to reason, "streak" to recovery.setupFailures, "retry_ms" to d)
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

    /**
     * Disconnect, then close: close() alone only unregisters this client and can leave the link up in the stack (the
     * next client then attaches to it and has its setup refused). Idempotent.
     */
    private fun closeGatt() {
        val g = gatt ?: return
        gatt = null
        try { g.disconnect() } catch (_: Exception) {}
        try { g.close() } catch (_: Exception) {}
    }

    private fun arm(ms: Long, reason: String, failure: LinkRecovery.Failure = LinkRecovery.Failure.DROP) {
        cancelWatchdog()
        val g = gatt
        val r = Runnable { if (gatt === g && gatt != null) { try { gatt?.disconnect() } catch (_: Exception) {}; lost(reason, failure) } }
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
                        link.clearPairing(); recovery.reset(); attempt(); return
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
                    if (s == BluetoothAdapter.STATE_ON && target != null && gatt == null && state != State.NEEDS_PAIRING) { recovery.reset(); attempt() }
                }
            }
        }
    }

    // --- helpers -----------------------------------------------------------------------------------------------------

    private fun setState(s: State, reason: String) {
        if (s == state && reason == why) return
        state = s; why = reason
        log("state", "state" to s.name.lowercase(), "why" to reason, "address" to target)
        LauncherIcon.update(ctx, s == State.READY)
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
        /** How often a stale link is checked while waiting for it to drop ([LinkRecovery.Plan.WaitForRelease]). */
        const val STALE_POLL_MS = 250L
        /** HIGH priority means an 11.25-15 ms interval (1.25 ms units); slower than this, it is asked for again. */
        const val HIGH_MAX_INTERVAL = 12

        /** The started instance; a new one stops it (see [start]). */
        private var live: BleFeatureSource? = null
        /** Between background auto-connect attempts while the device sleeps (one attempt normally waits until it wakes). */
        const val ASLEEP_RETRY_MS = 2_000L
        const val GATT_INSUFFICIENT_AUTHENTICATION = 5
        const val GATT_INSUFFICIENT_ENCRYPTION = 15

        /** The runtime permissions still missing (the pairing screen names them and asks). */
        fun missingPermissions(ctx: Context): List<String> =
            runtimePermissions().filter { ctx.checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }

        /** The permissions the app asks for (the pairing screen, the legacy settings screen). */
        fun runtimePermissions(): Array<String> = if (Build.VERSION.SDK_INT >= 31)
            arrayOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT)
            else arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)
    }
}
