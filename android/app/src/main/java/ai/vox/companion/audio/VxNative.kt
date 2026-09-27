package ai.vox.companion.audio

import java.nio.ByteBuffer

/**
 * The C++ extractor (firmware/extract/src, the same code the Pico runs) through JNI: src/main/cpp/vx_jni.cpp.
 *
 * One handle = one streaming extractor at 16 or 48 kHz (48 kHz goes through the port's Decimator3). push*() returns
 * null when nothing finished (the usual case, no allocation) or the messages that did, one JSON object each, with a
 * `kind`: `sound` today (label, text, stream-time t_start_ms / t_end_ms, `sound` id, fp1 `features`); `hold_start` /
 * `hold_end` later (PROTOCOL.md "Hold messages"), through the same list. [PhoneMessages] turns them into protocol
 * messages.
 *
 * The native side holds one process-wide lock (the port keeps its FFT and classify scratch in static buffers), so
 * two handles never run at the same time.
 */
object VxNative {
    /** Null when the library could not be loaded (an ABI without it); the phone mic source then reports it. */
    val loadError: String? = try {
        val path = System.getProperty("vox.vx_jni.path")   // host JVM tests: an absolute path to the host build
        if (path != null) System.load(path) else System.loadLibrary("vx_jni")
        null
    } catch (e: Throwable) { e.toString() }

    val available get() = loadError == null

    /** [configJson]: null = the defaults (the Pico's config), else a flat JSON of overrides (VxConfig keys). */
    @JvmStatic external fun create(rate: Int, withRaw: Boolean, configJson: String?): Long
    @JvmStatic external fun lastError(): String
    @JvmStatic external fun destroy(h: Long)
    @JvmStatic external fun reset(h: Long)
    @JvmStatic external fun pushShorts(h: Long, a: ShortArray, off: Int, n: Int): Array<String>?
    @JvmStatic external fun pushFloats(h: Long, a: FloatArray, off: Int, n: Int): Array<String>?
    /** [buf] must be a direct buffer holding [n] samples, int16 or (isFloat) float32, native byte order. */
    @JvmStatic external fun pushDirect(h: Long, buf: ByteBuffer, n: Int, isFloat: Boolean): Array<String>?
    @JvmStatic external fun flush(h: Long): Array<String>?
    /** JSON: hop time percentiles (us), sound-end and push times, counts, noise floor, input level (window reset). */
    @JvmStatic external fun stats(h: Long): String
    @JvmStatic external fun statsReset(h: Long)
    @JvmStatic external fun version(): String
    /** Joystick ticks (vx_tick.h, extractor/joystick_core.py Analyzer) on the same samples: 20 ms rows of [TICK_COLS]
     *  doubles. on = a fresh tick analyzer; off = none (the extractor path exactly as without). false = did not init. */
    @JvmStatic external fun enableTicks(h: Long, on: Boolean): Boolean
    /** The voicing start threshold of the ticks (the person's clarity_on; default 0.8). */
    @JvmStatic external fun setTickClarityOn(h: Long, v: Double)
    /** The ticks' pitch ceiling, Hz (default 1100; 2600 while a whistle range is calibrated). Kept across enableTicks. */
    @JvmStatic external fun setTickF0MaxHz(h: Long, v: Double)
    /** The queued ticks, oldest first, into [out] (whole rows of [TICK_COLS]); returns the rows written. */
    @JvmStatic external fun takeTicks(h: Long, out: DoubleArray): Int

    const val TICK_COLS = 10
    const val TICK_T_MS = 0; const val TICK_F0 = 1; const val TICK_F0_RAW = 2; const val TICK_CLARITY = 3
    const val TICK_DB = 4; const val TICK_FLOOR = 5; const val TICK_F1 = 6; const val TICK_F2 = 7
    const val TICK_VOICED = 8; const val TICK_WHY = 9
    /** TICK_WHY codes (vx_tick.h VX_TICK_WHY_*). */
    val TICK_WHY_NAMES = arrayOf("", "quiet", "unclear", "no pitch")

    /** create() or throw with the extractor's reason. [configJson] null = the defaults, byte-identical to before
     *  (a calibration profile's `extractor` block becomes this JSON only when it has fields: [overridesJson]). */
    fun open(rate: Int, withRaw: Boolean = false, configJson: String? = null): Long {
        loadError?.let { throw IllegalStateException("native extractor not available: $it") }
        val h = create(rate, withRaw, configJson)
        require(h != 0L) { "extractor: ${lastError()}" }
        return h
    }

    /** A flat JSON of extractor overrides from a profile's `extractor` block, or null when there are none. The
     *  block is empty today (the desktop go/no-go found no vx_config field worth overriding per person), so this is
     *  null and open() takes the default path. f0_min_hz is kept at or above [F0_MIN_HZ_FLOOR]: the Python and C++
     *  extractors disagree below 31.4 Hz and vx_config_check does not bound it. */
    fun overridesJson(extractor: Map<String, Any?>?): String? {
        val m = extractor?.filterValues { it != null }.orEmpty().toMutableMap()
        (m["f0_min_hz"] as? Number)?.let { m["f0_min_hz"] = maxOf(it.toDouble(), F0_MIN_HZ_FLOOR) }
        return if (m.isEmpty()) null else org.json.JSONObject(m as Map<*, *>).toString()
    }

    const val F0_MIN_HZ_FLOOR = 32.0
}
