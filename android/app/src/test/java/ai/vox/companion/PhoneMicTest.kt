package ai.vox.companion

import ai.vox.companion.audio.MicSettings
import ai.vox.companion.audio.PhoneMessages
import ai.vox.companion.audio.SourcePolicy
import ai.vox.companion.audio.SourcePolicy.Inputs
import ai.vox.companion.audio.SourcePolicy.Route
import ai.vox.companion.audio.VxNative
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * The phone-mic source without a phone:
 * - JNI parity: every extractor/vectors case through the JNI extractor (the host build of vx_jni.cpp + the Pico's
 *   sources, loaded from vox.vx_jni.path; see tools/build_host_jni.sh), compared with the vectors' reference events
 *   exactly as firmware/tools/check_extract.py compares them;
 * - the mapping from native messages to protocol messages (the same FeatureMessage the Pico's message gives);
 * - the source policy (what runs for each sound source and app state).
 */
class PhoneMicTest {
    companion object {
        init {
            // The host build of the JNI library (tools/build_host_jni.sh; gradle sets the property and builds it first).
            if (System.getProperty("vox.vx_jni.path") == null)
                System.setProperty("vox.vx_jni.path", File("build/host-jni/libvx_jni.so").absolutePath)
        }
    }

    private val vectors = File(System.getProperty("vox.vectors") ?: "../../extractor/vectors")

    // --- JNI parity --------------------------------------------------------------------------------------------------

    private fun pcm(name: String): ShortArray {
        val b = File(vectors, "$name.pcm").readBytes()
        val s = ShortArray(b.size / 2)
        ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer().get(s)
        return s
    }

    /** Runs [x] through a fresh extractor, [chunk] samples per push, via the direct buffer (the audio thread's path) or short[]. */
    private fun run(x: ShortArray, rate: Int, chunk: Int, direct: Boolean): List<JSONObject> {
        val h = VxNative.open(rate, withRaw = true)
        val out = ArrayList<JSONObject>()
        try {
            val buf = ByteBuffer.allocateDirect(chunk * 2).order(ByteOrder.nativeOrder())
            var i = 0
            while (i < x.size) {
                val k = minOf(chunk, x.size - i)
                val m = if (direct) { buf.clear(); buf.asShortBuffer().put(x, i, k); VxNative.pushDirect(h, buf, k, false) }
                        else VxNative.pushShorts(h, x, i, k)
                m?.forEach { out += JSONObject(it) }
                i += k
            }
            VxNative.flush(h)?.forEach { out += JSONObject(it) }
        } finally { VxNative.destroy(h) }
        return out
    }

    private fun within(got: Double, ref: Double) = Math.abs(got - ref) <= 0.01 + 0.01 * Math.abs(ref)

    private fun nums(a: JSONArray?) = if (a == null) emptyList() else List(a.length()) { a.getDouble(it) }

    @Test fun jniParityWithEveryVector() {
        assertNull("native library: ${VxNative.loadError}", VxNative.loadError)
        val cases = JSONObject(File(vectors, "manifest.json").readText()).getJSONArray("cases")
        var events = 0
        for (c in 0 until cases.length()) {
            val case = cases.getJSONObject(c)
            val name = case.getString("name"); val rate = case.getInt("rate")
            val ref = JSONObject(File(vectors, "$name.events.json").readText()).getJSONArray("events")
            val x = pcm(name)
            // 20 ms reads through the direct buffer (live), and odd-sized short[] chunks: the result must not depend on them
            for ((chunk, direct) in listOf(rate / 50 to true, 777 to false)) {
                val got = run(x, rate, chunk, direct)
                val what = "$name (chunk $chunk${if (direct) ", direct" else ""})"
                assertEquals("$what: event count", ref.length(), got.size)
                for (i in got.indices) {
                    val r = ref.getJSONObject(i); val g = got[i]; val ge = g.getJSONObject("event")
                    assertEquals("$what #$i label", r.getString("label"), g.getString("label"))
                    assertEquals("$what #$i text", r.getString("text"), g.getString("text"))
                    assertTrue("$what #$i t_start", Math.abs(r.getInt("t_start_ms") - g.getInt("t_start_ms")) <= 10)
                    assertTrue("$what #$i t_end", Math.abs(r.getInt("t_end_ms") - g.getInt("t_end_ms")) <= 10)
                    assertEquals("$what #$i sound id", i + 1L, g.getLong("sound"))
                    // the compact gate object (PhoneGate, mic_sound logs) agrees with the full event
                    val gt = g.getJSONObject("gate"); val gr = ge.getJSONObject("raw")
                    assertEquals("$what #$i why", gr.getString("why"), gt.getString("why"))
                    assertEquals("$what #$i like", ge.getString("sounds_like"), gt.getString("like"))
                    for (key in listOf("dur_ms", "snr_db", "voiced_frac", "clarity_med", "onset_flux_db", "floor_db", "excursion_st",
                            "centroid_hz", "peak_centroid_hz", "zcr", "lf_ratio", "hf_ratio"))
                        if (gr.has(key)) assertEquals("$what #$i gate $key", gr.getDouble(key), gt.getDouble(key), 0.0)
                    assertEquals("$what #$i cues", gr.optJSONArray("speech_cues")?.length() ?: 0, gt.getJSONArray("cues").length())
                    // fp1 and pitch16: the reference's raw values, the compact features entry and the full event agree
                    val rr = r.getJSONObject("raw")
                    val f = g.getJSONObject("features")
                    assertEquals("fp1", f.getString("fp_version"))
                    for (key in listOf("fp", "pitch16")) {
                        val a = nums(rr.optJSONArray(key)); val b = nums(f.getJSONArray(key)); val e = nums(ge.getJSONObject("raw").optJSONArray(key))
                        assertEquals("$what #$i $key length", a.size, b.size)
                        assertEquals("$what #$i $key event", b, e)
                        for (k in a.indices) assertTrue("$what #$i $key[$k] ${b[k]} vs ${a[k]}", within(b[k], a[k]))
                    }
                    // and it maps to a valid protocol message
                    val fm = FeatureMessage.parse(PhoneMessages.toProtocol(g, 1, "gesture", 0)!!)
                    assertEquals(listOf(g.getString("label")), fm.sequence)
                    assertNotNull(fm.features!![0])
                }
                events += got.size
            }
        }
        assertTrue("events compared: $events", events >= 40)
    }

    @Test fun jniStatsAndReset() {
        val x = pcm("rise_20db")
        val h = VxNative.open(16000)
        try {
            var n = 0
            for (round in 0 until 2) {
                if (round == 1) VxNative.reset(h)
                var i = 0
                while (i < x.size) { VxNative.pushShorts(h, x, i, minOf(320, x.size - i))?.let { m -> n += m.size
                    assertEquals("sound ids restart after reset", 1L, JSONObject(m[0]).getLong("sound")) }; i += 320 }
            }
            assertEquals(2, n)
            val st = JSONObject(VxNative.stats(h))
            assertEquals(16000, st.getInt("rate"))
            assertTrue(st.getInt("hops") > 300)
            val hop = st.getJSONObject("hop_us")
            assertTrue(hop.getDouble("p50") > 0 && hop.getDouble("p99") >= hop.getDouble("p50") && hop.getDouble("max") >= hop.getDouble("p99") - 1)
            assertTrue(st.getJSONObject("level").getDouble("rms_dbfs") in -80.0..0.0)
            assertEquals(8, st.getJSONObject("level").getJSONArray("bands_dbfs").length())
            assertEquals(1000, st.getJSONObject("level").getInt("band_hz"))
            // the level window restarts on each read (no frame since: no band levels)
            val again = JSONObject(VxNative.stats(h)).getJSONObject("level")
            assertEquals(-200.0, again.getDouble("rms_dbfs"), 0.0)
            assertTrue(again.isNull("bands_dbfs"))
        } finally { VxNative.destroy(h) }
        // a rate the port does not take
        assertEquals(0L, VxNative.create(44100, false, null))
        assertTrue(VxNative.lastError().contains("16000"))
    }

    /** mic_status band levels: a sine lands in its 1 kHz band at its mean-square level (Parseval over the frame FFTs). */
    @Test fun bandLevelsPutASineInItsBand() {
        fun bands(rate: Int, hz: Double, amp: Double): List<Double> {
            val h = VxNative.open(rate)
            try {
                val x = ShortArray(rate * 2) { (amp * 32767 * Math.sin(2 * Math.PI * hz * it / rate)).toInt().toShort() }
                var i = 0
                while (i < x.size) { VxNative.pushShorts(h, x, i, minOf(rate / 50, x.size - i)); i += rate / 50 }
                return nums(JSONObject(VxNative.stats(h)).getJSONObject("level").getJSONArray("bands_dbfs"))
            } finally { VxNative.destroy(h) }
        }
        val want = 20 * Math.log10(0.5 / Math.sqrt(2.0))                       // a 0.5 sine: -9.0 dBFS mean square
        for ((hz, band) in listOf(7500.0 to 7, 6900.0 to 6, 1500.0 to 1, 4500.0 to 4)) {
            for (rate in listOf(16000, 48000)) {
                val b = bands(rate, hz, 0.5)
                assertEquals("$hz Hz at $rate: loudest band ($b)", band, b.indices.maxByOrNull { b[it] })
                // at 48 kHz the levels are after the port's Decimator3: its anti-alias filter takes ~4 dB off 6.9 kHz and ~10 dB off 7.5 kHz
                if (rate == 48000 && band >= 6) assertTrue("$hz Hz at $rate: band $band ($b)", b[band] in (want - 15)..(want + 0.5))
                else assertEquals("$hz Hz at $rate: band $band level ($b)", want, b[band], 0.5)
                for (k in b.indices) if (Math.abs(k - band) > 1) assertTrue("$hz Hz at $rate: band $k far below ($b)", b[k] < want - 30)
            }
        }
        // silence: every band at the -200 floor or far below the sine
        assertTrue(bands(16000, 1000.0, 0.0).all { it <= -150 })
    }

    @Test fun configOverrides() {
        val x = pcm("rise_20db")
        fun sounds(cfg: String?): Int {
            val h = VxNative.open(16000, configJson = cfg)
            var n = 0
            try {
                var i = 0
                while (i < x.size) { n += VxNative.pushShorts(h, x, i, minOf(320, x.size - i))?.size ?: 0; i += 320 }
                n += VxNative.flush(h)?.size ?: 0
            } finally { VxNative.destroy(h) }
            return n
        }
        val base = sounds(null)
        assertTrue(base >= 1)
        assertEquals("empty override = defaults", base, sounds("{}"))
        assertEquals("a gate far above the sound: nothing", 0, sounds("""{"gate_open_db": 80.0}"""))
        // an unknown key is an error, with the extractor's reason
        assertEquals(0L, VxNative.create(16000, false, """{"no_such_key": 1}"""))
        assertTrue(VxNative.lastError(), VxNative.lastError().startsWith("config:"))
    }

    // --- touch guard -------------------------------------------------------------------------------------------------

    @Test fun touchGuardDropsSoundsAroundAUserTouch() {
        val g = ai.vox.companion.audio.TouchGuard(preMs = 150, postMs = 400)
        g.onTouchDown(10_000, injected = false)
        assertNotNull("the tap itself", g.overlapping(10_010, 10_060))
        assertNotNull("the lift, 300 ms later", g.overlapping(10_300, 10_340))
        assertNotNull("a sound ending just before the down (capture clock slack)", g.overlapping(9_700, 9_880))
        assertNull("well after", g.overlapping(10_450, 10_900))
        assertNull("well before", g.overlapping(9_000, 9_800))
        assertNotNull("a long sound spanning the touch", g.overlapping(9_000, 11_000))
        // Canti's own injected taps never guard
        g.onTouchDown(20_000, injected = true)
        assertNull(g.overlapping(20_000, 20_100))
        assertEquals(1L, g.userTouches); assertEquals(1L, g.injectedTouches); assertEquals(4L, g.dropped)
        assertEquals(100L, g.settleMs(tEndMs = 1_000, nowMs = 1_050)); assertEquals(0L, g.settleMs(1_000, 2_000))
    }

    @Test fun aFingerIsNeverTakenForCantisOwnTouch() {
        val T = ai.vox.companion.audio.TouchGuard
        // the Z Flip field case: a finger (touchscreen device 7), Canti's last gesture 3 s earlier
        assertFalse(T.isInjected(deviceId = 7, eventUptimeMs = 10_000, injStartMs = 7_000, injEndMs = 7_120))
        assertFalse("never injected anything", T.isInjected(7, 10_000, 0, 0))
        assertTrue("during Canti's fling", T.isInjected(7, 7_060, 7_000, 7_120))
        assertTrue("dispatch slack", T.isInjected(7, 6_980, 7_000, 7_120))
        assertFalse("just after the slack", T.isInjected(7, 7_171, 7_000, 7_120))
        assertTrue("no input device = dispatched", T.isInjected(-1, 10_000, 0, 0))
    }

    // --- media gate --------------------------------------------------------------------------------------------------

    @Test fun mediaGateAsksForAClearSoundOnlyWhileMediaPlays() {
        val G = ai.vox.companion.audio.PhoneGate
        assertNotNull("a media pop just over the floor", G.reason("pop", 10.0, 0.4))
        assertNull("a real pop, clearly over the floor", G.reason("pop", 20.0, 0.4))
        assertNotNull("a click too", G.reason("click", 12.0, null))
        assertNotNull("a quiet hum", G.reason("fall", 11.0, 0.95))
        assertNotNull("a loud but unclear 'hum' (chord, breathy syllable)", G.reason("rise", 25.0, 0.6))
        assertNull("a loud clear hum / whistle", G.reason("rise", 20.0, 0.9))
        assertNotNull("missing numbers gate (fail safe)", G.reason("flat", null, null))
        assertNull("hiss is not gated (media barely makes it)", G.reason("hiss", 5.0, 0.1))
        assertNull(G.reason("unknown", 0.0, 0.0))
        assertTrue(G.active("speaker", mediaPlaying = true, speakerMedia = true))
        assertFalse("media on earbuds: no echo, no gate", G.active("speaker", mediaPlaying = true, speakerMedia = false))
        assertFalse(G.active("speaker", mediaPlaying = false, speakerMedia = false))
        assertTrue(G.active("media", mediaPlaying = true, speakerMedia = false))
        assertTrue(G.active("always", mediaPlaying = false, speakerMedia = false))
        assertFalse(G.active("off", mediaPlaying = true, speakerMedia = true))
    }

    @Test fun mediaHissRuleGatesHighHissOnlyWhileMediaPlaysOnTheSpeaker() {
        val G = ai.vox.companion.audio.PhoneGate
        val max = G.HISS_MEDIA_MAX_CENTROID_HZ
        assertEquals(6500, max)
        val phone = MicSettings.PHONE
        // media on the phone's own speaker: a 6.9 kHz hiss (the Z Flip's media band) is gated, with its reason
        val why = G.hissReason("hiss", 6912.4, speakerMedia = true, maxCentroidHz = max, source = phone)
        assertNotNull(why); assertTrue(why!!, why.startsWith("hiss centroid 6912 Hz over 6500 Hz"))
        // a mouth hiss (Q9 p90 4.7 kHz) passes
        assertNull(G.hissReason("hiss", 4700.0, true, max, phone))
        // media off, or on earbuds / Bluetooth (speakerMedia false): never gated
        assertNull("no media", G.hissReason("hiss", 7000.0, speakerMedia = false, maxCentroidHz = max, source = phone))
        // the boundary: over the threshold is gated, at it passes
        assertNull("6500 Hz exactly passes", G.hissReason("hiss", 6500.0, true, max, phone))
        assertNotNull("6500.1 Hz is over", G.hissReason("hiss", 6500.1, true, max, phone))
        assertNotNull("a custom threshold", G.hissReason("hiss", 6100.0, true, 6000, phone))
        assertNull(G.hissReason("hiss", 5900.0, true, 6000, phone))
        // a USB mic is gated like the phone mic; the Pico never
        assertNotNull(G.hissReason("hiss", 7000.0, true, max, MicSettings.USB))
        assertNull("Pico exempt", G.hissReason("hiss", 7000.0, true, max, MicSettings.PICO))
        // the setting off (0)
        assertNull("off", G.hissReason("hiss", 7900.0, true, 0, phone))
        // only hisses; a missing centroid passes
        for (l in listOf("click", "pop", "rise", "flat", "unknown")) assertNull(l, G.hissReason(l, 7000.0, true, max, phone))
        assertNull(G.hissReason("hiss", null, true, max, phone))
        // the snr / clarity rule still never gates a hiss by itself
        assertNull(G.reason("hiss", 5.0, 0.1))
    }

    @Test fun hissSettingDefaultApplyAndRange() {
        val m = MicSettings(MemPrefs())
        assertEquals(6500, m.hissMediaMaxCentroidHz)
        assertTrue("hiss_media_max_centroid_hz" in MicSettings.KEYS)
        assertTrue(m.apply("hiss_media_max_centroid_hz", JSONObject().put("hiss_media_max_centroid_hz", 0)))
        assertEquals(0, m.hissMediaMaxCentroidHz)
        m.apply("hiss_media_max_centroid_hz", JSONObject().put("hiss_media_max_centroid_hz", 6000))
        assertEquals(6000, m.describeInto(JSONObject()).getInt("hiss_media_max_centroid_hz"))
        for (bad in listOf(-1, 8001)) try { m.hissMediaMaxCentroidHz = bad; fail("$bad accepted") } catch (_: IllegalArgumentException) {}
        assertEquals(6000, m.hissMediaMaxCentroidHz)
    }

    /** Calibration v2's level gate settings: on by default, offset 0, -10..10. */
    @Test fun levelGateSettingsDefaultApplyAndRange() {
        val m = MicSettings(MemPrefs())
        assertTrue(m.levelGate); assertEquals(0, m.levelGateOffsetDb)
        assertTrue("level_gate" in MicSettings.KEYS && "level_gate_offset_db" in MicSettings.KEYS)
        assertTrue(m.apply("level_gate", JSONObject().put("level_gate", false)))
        assertTrue(m.apply("level_gate_offset_db", JSONObject().put("level_gate_offset_db", 4)))
        val d = m.describeInto(JSONObject())
        assertFalse(d.getBoolean("level_gate")); assertEquals(4, d.getInt("level_gate_offset_db"))
        for (bad in listOf(-11, 11)) try { m.levelGateOffsetDb = bad; fail("$bad accepted") } catch (_: IllegalArgumentException) {}
        assertEquals(4, m.levelGateOffsetDb)
    }

    /** The native sound's `gate` numbers reach the level gate and the click / pop rule (SoundExample.raw). */
    @Test fun nativeGateCarriesTheLevelGateNumbers() {
        var seen = 0
        for (name in listOf("click_30db", "click_pop_30db")) {
            for (m in run(pcm(name), 16000, 320, direct = false)) {
                if (m.optString("kind") != "sound" || m.optString("label") !in listOf("pop", "click", "hiss")) continue
                val raw = ai.vox.companion.joystick.SoundExample.raw(m.getJSONObject("gate"))
                for (k in listOf("dur_ms", "snr_db", "level_db", "lf_ratio", "peak_centroid_hz")) assertNotNull("$name $k", raw[k])
                seen++
            }
        }
        assertTrue("some pop / click / hiss vectors", seen > 0)
    }

    /** The ticks' pitch ceiling (the whistle step): a 1600 Hz whistle is only read right with it raised to 2600 Hz. */
    @Test fun tickCeilingReadsAWhistle() {
        val rate = 16000
        val x = ShortArray(rate) { (6000 * kotlin.math.sin(2 * Math.PI * 1600.0 * it / rate)).toInt().toShort() }
        fun medianF0(ceiling: Double?): Double {
            val h = VxNative.open(rate)
            try {
                assertTrue(VxNative.enableTicks(h, true))
                ceiling?.let { VxNative.setTickF0MaxHz(h, it) }
                val out = DoubleArray(VxNative.TICK_COLS * 200)
                val f0 = ArrayList<Double>()
                var i = 0
                while (i < x.size) {
                    VxNative.pushShorts(h, x, i, minOf(320, x.size - i)); i += 320
                    val n = VxNative.takeTicks(h, out)
                    for (r in 0 until n) if (out[r * VxNative.TICK_COLS + VxNative.TICK_VOICED] > 0.5) f0 += out[r * VxNative.TICK_COLS + VxNative.TICK_F0]
                }
                return if (f0.isEmpty()) 0.0 else f0.sorted()[f0.size / 2]
            } finally { VxNative.destroy(h) }
        }
        val high = medianF0(2600.0)
        assertTrue("raised: $high", kotlin.math.abs(12 * kotlin.math.ln(high / 1600.0) / kotlin.math.ln(2.0)) < 0.5)
        val low = medianF0(null)
        assertTrue("voice ceiling: $low", low == 0.0 || kotlin.math.abs(12 * kotlin.math.ln(low / 1600.0) / kotlin.math.ln(2.0)) > 0.5)
    }

    /** In-memory SharedPreferences (the android.jar one is a stub in JVM tests). */
    private class MemPrefs : android.content.SharedPreferences {
        val m = HashMap<String, Any?>()
        override fun getAll(): MutableMap<String, *> = m
        override fun getString(k: String, d: String?) = m[k] as String? ?: d
        override fun getStringSet(k: String, d: MutableSet<String>?) = @Suppress("UNCHECKED_CAST") (m[k] as MutableSet<String>? ?: d)
        override fun getInt(k: String, d: Int) = m[k] as Int? ?: d
        override fun getLong(k: String, d: Long) = m[k] as Long? ?: d
        override fun getFloat(k: String, d: Float) = m[k] as Float? ?: d
        override fun getBoolean(k: String, d: Boolean) = m[k] as Boolean? ?: d
        override fun contains(k: String) = k in m
        override fun registerOnSharedPreferenceChangeListener(l: android.content.SharedPreferences.OnSharedPreferenceChangeListener?) {}
        override fun unregisterOnSharedPreferenceChangeListener(l: android.content.SharedPreferences.OnSharedPreferenceChangeListener?) {}
        override fun edit(): android.content.SharedPreferences.Editor = object : android.content.SharedPreferences.Editor {
            override fun putString(k: String, v: String?) = apply { m[k] = v }
            override fun putStringSet(k: String, v: MutableSet<String>?) = apply { m[k] = v }
            override fun putInt(k: String, v: Int) = apply { m[k] = v }
            override fun putLong(k: String, v: Long) = apply { m[k] = v }
            override fun putFloat(k: String, v: Float) = apply { m[k] = v }
            override fun putBoolean(k: String, v: Boolean) = apply { m[k] = v }
            override fun remove(k: String) = apply { m.remove(k) }
            override fun clear() = apply { m.clear() }
            override fun commit() = true
            override fun apply() {}
        }
    }

    // --- mapping -----------------------------------------------------------------------------------------------------

    private val line = "hum that rises from low to high; pitch change large (over 4 semitones); duration medium (400-1000 ms); tone clear tone; loudness normal; sounds like hum"
    private val features = JSONObject().put("fp", JSONArray(List(24) { it * 0.5 - 3.25 })).put("fp_version", "fp1")
        .put("pitch16", JSONArray(List(16) { it * 0.37 }))
    private fun nativeSound() = JSONObject().put("kind", "sound").put("sound", 3).put("t_start_ms", 839).put("t_end_ms", 1329)
        .put("label", "rise").put("text", line).put("truncated", false).put("features", features)

    @Test fun soundMapsToThePicoMessage() {
        val out = PhoneMessages.toProtocol(nativeSound(), 42, "cursor", 100_000)!!
        // What firmware/arduino/vox_node/vox_state.cpp send_sound() sends for the same sound on the device clock
        val pico = JSONObject("""{"v":1,"id":42,"mode":"cursor","armed":true,"sounds":["$line"],"sequence":["rise"],""" +
            """"timing":[{"t_start_ms":100839,"t_end_ms":101329}],"phrase":null,"cursor":null,"features":[$features]}""")
        val a = FeatureMessage.parse(out); val b = FeatureMessage.parse(pico)
        // SoundFeatures has array fields (identity equality): compare them as JSON, the rest as data
        fun feats(m: FeatureMessage) = m.features!!.map { it!!.toJson().toString() }
        fun stamps(m: FeatureMessage) = m.timing!!.map { it!!.startMs to it.endMs }
        assertEquals(b.copy(features = null, timing = null), a.copy(features = null, timing = null))
        assertEquals(feats(b), feats(a))
        assertEquals(stamps(b), stamps(a))
        assertEquals(pico.keys().asSequence().toSet(), out.keys().asSequence().toSet())
        assertEquals(3L, out.getJSONArray("timing").getJSONObject(0).getLong("sound"))
        assertFalse(out.getJSONArray("timing").getJSONObject(0).has("held"))
        // features survive a toJson round trip unchanged (the matcher reads them)
        assertEquals(feats(a), feats(FeatureMessage.parse(a.toJson())))
    }

    @Test fun heldFlagAndHoldMessagesMap() {
        val held = PhoneMessages.toProtocol(nativeSound().put("held", true), 7, "gesture", 0)!!
        assertTrue(held.getJSONArray("timing").getJSONObject(0).getBoolean("held"))
        val start = PhoneMessages.toProtocol(JSONObject().put("kind", "hold_start").put("sound", 3).put("t_start_ms", 839)
            .put("t_ms", 1139).put("f0_hz", 145.2).put("flat", true), 8, "gesture", 1000)!!
        assertEquals(JSONObject("""{"v":1,"id":8,"hold":"start","sound":3,"t_start_ms":1839,"t_ms":2139,"f0_hz":145.2,"flat":true}""").toString(),
            start.toString())
        val end = PhoneMessages.toProtocol(JSONObject().put("kind", "hold_end").put("sound", 3).put("t_start_ms", 839).put("t_ms", 1329), 9, "gesture", 1000)!!
        assertEquals("end", end.getString("hold")); assertEquals(2329L, end.getLong("t_ms")); assertFalse(end.has("sounds"))
        assertNull(PhoneMessages.toProtocol(JSONObject().put("kind", "something_new"), 10, "gesture", 0))
    }

    // --- source policy -----------------------------------------------------------------------------------------------

    private fun plan(source: String, active: Boolean = true, perm: Boolean = true, usb: Boolean = false, native: Boolean = true) =
        SourcePolicy.plan(Inputs(source, active, perm, usb, native))

    @Test fun sourceSwitching() {
        // Pico: Bluetooth only, never the mic (whatever else is true)
        with(plan(MicSettings.PICO, usb = true)) { assertTrue(ble); assertFalse(service); assertFalse(capture) }
        // phone mic: no BLE; built-in route, even with a USB mic plugged in
        with(plan(MicSettings.PHONE, usb = true)) { assertFalse(ble); assertTrue(service); assertTrue(capture); assertEquals(Route.BUILTIN, route) }
        // USB mic: its route when plugged, waiting (service kept, mic closed) when not; never the phone mic instead
        with(plan(MicSettings.USB, usb = true)) { assertTrue(capture); assertEquals(Route.USB, route) }
        with(plan(MicSettings.USB, usb = false)) { assertTrue(service); assertFalse(capture); assertNull(route); assertEquals("waiting for a USB mic", state) }
        // paused / disarmed: the mic closes, the service stays so it can reopen from the background
        with(plan(MicSettings.PHONE, active = false)) { assertTrue(service); assertFalse(capture); assertEquals("paused", state) }
        // no permission or no native library: nothing runs, and the state says why
        with(plan(MicSettings.PHONE, perm = false)) { assertFalse(service); assertFalse(capture); assertEquals("needs microphone permission", state) }
        with(plan(MicSettings.USB, native = false, usb = true)) { assertFalse(service); assertFalse(capture); assertTrue(state.startsWith("unavailable")) }
        assertFalse(plan(MicSettings.PHONE).ble)
    }
}
