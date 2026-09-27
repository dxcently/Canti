package ai.vox.companion

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.Base64

/** The asr_audio / grammar debug ops' argument handling (AsrAudioArgs in AudioFileAsr.kt): no device needed. */
class AudioFileAsrTest {
    private fun chunk(id: String, body: ByteArray): ByteArray {
        val b = ByteBuffer.allocate(8 + body.size + (body.size and 1)).order(ByteOrder.LITTLE_ENDIAN)
        b.put(id.toByteArray(Charsets.US_ASCII)).putInt(body.size).put(body)
        return b.array()
    }

    private fun fmt(format: Int = 1, channels: Int = 1, rate: Int = 16000, bits: Int = 16): ByteArray =
        ByteBuffer.allocate(16).order(ByteOrder.LITTLE_ENDIAN).putShort(format.toShort()).putShort(channels.toShort()).putInt(rate)
            .putInt(rate * channels * bits / 8).putShort((channels * bits / 8).toShort()).putShort(bits.toShort()).array()

    private fun wav(vararg chunks: ByteArray): ByteArray {
        val body = ByteArrayOutputStream().apply { write("WAVE".toByteArray()); chunks.forEach { write(it) } }.toByteArray()
        return ByteBuffer.allocate(8 + body.size).order(ByteOrder.LITTLE_ENDIAN).put("RIFF".toByteArray()).putInt(body.size).put(body).array()
    }

    private fun pcm(samples: Int) = ByteArray(samples * 2) { (it % 7).toByte() }
    private fun args(bytes: ByteArray) = JSONObject().put("wav_b64", Base64.getEncoder().encodeToString(bytes))

    private fun refused(what: String, f: () -> Unit) {
        try { f(); fail("expected a refusal: $what") } catch (e: IllegalArgumentException) {
            assertTrue("'${e.message}' should mention '$what'", e.message.orEmpty().contains(what))
        }
    }

    @Test fun readsAPlainWav() {
        val data = pcm(16000)   // 1 s
        val a = AsrAudioArgs.audio(args(wav(chunk("fmt ", fmt()), chunk("data", data))))
        assertEquals(16000, a.rate)
        assertEquals(1000L, a.durationMs)
        assertArrayEquals(data, a.pcm)
    }

    @Test fun skipsOtherChunksAndOddPadding() {
        val data = pcm(800)
        val a = AsrAudioArgs.audio(args(wav(chunk("LIST", ByteArray(3)), chunk("fmt ", fmt()), chunk("junk", ByteArray(5)), chunk("data", data))))
        assertArrayEquals(data, a.pcm)
        assertEquals(50L, a.durationMs)
    }

    @Test fun refusesMissingOrBrokenInput() {
        refused("give wav_b64") { AsrAudioArgs.audio(JSONObject()) }
        refused("not base64") { AsrAudioArgs.audio(JSONObject().put("wav_b64", "!!not base64!!")) }
        refused("not a WAV") { AsrAudioArgs.audio(args("hello world, not audio".toByteArray())) }
        refused("no fmt") { AsrAudioArgs.audio(args(wav(chunk("data", pcm(10))))) }
        refused("no data") { AsrAudioArgs.audio(args(wav(chunk("fmt ", fmt())))) }
        refused("empty") { AsrAudioArgs.audio(args(wav(chunk("fmt ", fmt()), chunk("data", ByteArray(0))))) }
        val full = wav(chunk("fmt ", fmt()), chunk("data", pcm(100)))
        refused("truncated") { AsrAudioArgs.audio(args(full.copyOf(full.size - 10))) }
    }

    @Test fun refusesOtherFormats() {
        refused("not PCM") { AsrAudioArgs.audio(args(wav(chunk("fmt ", fmt(format = 3, bits = 32)), chunk("data", pcm(10))))) }
        refused("want mono") { AsrAudioArgs.audio(args(wav(chunk("fmt ", fmt(channels = 2)), chunk("data", pcm(10))))) }
        refused("want 16-bit") { AsrAudioArgs.audio(args(wav(chunk("fmt ", fmt(bits = 8)), chunk("data", ByteArray(10))))) }
        refused("want 16000") { AsrAudioArgs.audio(args(wav(chunk("fmt ", fmt(rate = 48000)), chunk("data", pcm(10))))) }
    }

    @Test fun refusesTooLong() {
        AsrAudioArgs.audio(args(wav(chunk("fmt ", fmt()), chunk("data", pcm(16000 * 30)))))   // 30 s: the limit
        refused("longer than") { AsrAudioArgs.audio(args(wav(chunk("fmt ", fmt()), chunk("data", pcm(16000 * 31))))) }
    }

    @Test fun resultIdAndGrammarTexts() {
        assertEquals("a3", AsrAudioArgs.id(JSONObject().put("id", "a3")))
        refused("give id") { AsrAudioArgs.id(JSONObject()) }
        assertEquals(listOf("open instagram", "go back"), AsrAudioArgs.texts(JSONObject().put("texts", JSONArray(listOf("open instagram", "go back")))))
        refused("give texts") { AsrAudioArgs.texts(JSONObject()) }
        refused("1..50") { AsrAudioArgs.texts(JSONObject().put("texts", JSONArray())) }
        refused("1..50") { AsrAudioArgs.texts(JSONObject().put("texts", JSONArray(List(51) { "x" }))) }
        refused("texts[1]") { AsrAudioArgs.texts(JSONObject().put("texts", JSONArray(listOf("ok", "  ")))) }
        refused("texts[0]") { AsrAudioArgs.texts(JSONObject().put("texts", JSONArray().put(5))) }
    }

    @Test fun commandFieldsForScoring() {
        val apps = listOf(AppEntry("com.instagram.android", "Instagram"))
        fun cmd(text: String) = AsrAudioArgs.pick(PhraseGrammar.choose(Heard(listOf(text)), PhraseGrammar.Context(apps = apps))).getJSONObject("command")
        cmd("open instagram").let { assertEquals("open_app", it.getString("type")); assertEquals("Instagram", it.getString("label")) }
        cmd("set a timer for five minutes").let { assertEquals("timer", it.getString("type")); assertEquals(300, it.getInt("seconds")) }
        cmd("go back").let { assertEquals("nav", it.getString("type")) }
        val p = AsrAudioArgs.pick(PhraseGrammar.choose(Heard(listOf("um", "open instagram")), PhraseGrammar.Context(apps = apps)))
        assertEquals(1, p.getInt("index"))
        assertEquals(2, p.getJSONArray("parsed").length())
    }

    // --- the recognizer's input: intent extras and PCM framing -------------------------------------------------------

    @Test fun extrasDeclareExactlyWhatIsWritten() {
        val e = AsrAudioArgs.extras(16000, AsrAudioArgs.Options()).toMap()
        // the documented keys, spelled out: a typo'd key is silently ignored by the recognizer
        assertEquals(2, e["android.speech.extra.AUDIO_SOURCE_ENCODING"])          // AudioFormat.ENCODING_PCM_16BIT
        assertEquals(1, e["android.speech.extra.AUDIO_SOURCE_CHANNEL_COUNT"])
        assertEquals(16000, e["android.speech.extra.AUDIO_SOURCE_SAMPLING_RATE"])
        assertEquals(true, e["android.speech.extra.PREFER_OFFLINE"])
        assertEquals(null, e["android.speech.extra.SEGMENTED_SESSION"])
        assertEquals(4, e.size)
        val seg = AsrAudioArgs.extras(16000, AsrAudioArgs.Options(segmented = true)).toMap()
        assertEquals("android.speech.extra.AUDIO_SOURCE", seg["android.speech.extra.SEGMENTED_SESSION"])   // names the audio-source extra
    }

    @Test fun theDeclaredRateIsTheWavs() {
        val a = AsrAudioArgs.audio(args(wav(chunk("fmt ", fmt()), chunk("data", pcm(1600)))))
        assertEquals(a.rate, AsrAudioArgs.extras(a.rate, a.options).toMap()["android.speech.extra.AUDIO_SOURCE_SAMPLING_RATE"])
    }

    @Test fun thePipeGetsRawLittleEndianPcmNoHeader() {
        val samples = shortArrayOf(0, 1, -1, 1000, -32768, 32767)
        val data = ByteBuffer.allocate(samples.size * 2).order(ByteOrder.LITTLE_ENDIAN).apply { samples.forEach { putShort(it) } }.array()
        val a = AsrAudioArgs.audio(args(wav(chunk("fmt ", fmt()), chunk("data", data))))
        val sent = AsrAudioArgs.framed(a.pcm, a.rate, a.options)
        assertArrayEquals(data, sent)                                  // no RIFF header, byte order kept
        assertEquals(1000.toByte(), sent[6]); assertEquals((1000 shr 8).toByte(), sent[7])   // little-endian
        refused("double-wrapped") { AsrAudioArgs.audio(args(wav(chunk("fmt ", fmt()), chunk("data", wav(chunk("fmt ", fmt()), chunk("data", pcm(8))))))) }
    }

    @Test fun silencePaddingIsWholeSamples() {
        val clip = pcm(160)   // 10 ms
        val f = AsrAudioArgs.framed(clip, 16000, AsrAudioArgs.Options(leadMs = 300, tailMs = 1200))
        assertEquals((4800 + 160 + 19200) * 2, f.size)
        assertTrue(f.copyOfRange(0, 9600).all { it == 0.toByte() })
        assertArrayEquals(clip, f.copyOfRange(9600, 9600 + clip.size))
        assertTrue(f.copyOfRange(9600 + clip.size, f.size).all { it == 0.toByte() })
    }

    @Test fun chunksCoverThePcmInWholeSamples() {
        val c = AsrAudioArgs.chunks(16000 * 2 + 100, 16000, 20)   // 1 s + 50 samples
        assertEquals(640, c[0].second)                              // 20 ms = 320 samples = 640 bytes
        assertEquals(51, c.size)
        assertEquals(100, c.last().second)
        assertTrue(c.all { it.first % 2 == 0 && it.second % 2 == 0 })
        assertEquals(16000 * 2 + 100, c.sumOf { it.second })
        assertEquals((0 until c.size - 1).map { (it + 1) * 640 }, c.drop(1).map { it.first })
    }

    @Test fun optionsAndTheirLimits() {
        assertEquals(AsrAudioArgs.Options(), AsrAudioArgs.options(JSONObject()))
        val o = AsrAudioArgs.options(JSONObject().put("segmented", true).put("feed_at", "start").put("realtime", false)
            .put("lead_ms", 500).put("tail_ms", 2000).put("chunk_ms", 100))
        assertEquals(AsrAudioArgs.Options(true, "start", false, 500, 2000, 100), o)
        refused("feed_at") { AsrAudioArgs.options(JSONObject().put("feed_at", "later")) }
        refused("tail_ms") { AsrAudioArgs.options(JSONObject().put("tail_ms", 9000)) }
        refused("chunk_ms") { AsrAudioArgs.options(JSONObject().put("chunk_ms", 5)) }
    }

    @Test fun levelStatsOfWhatIsSent() {
        val tone = ByteBuffer.allocate(16000 * 2).order(ByteOrder.LITTLE_ENDIAN).apply {
            for (i in 0 until 16000) putShort(if (i < 8000) 0 else (16384 * Math.sin(i * 0.1)).toInt().toShort())
        }.array()
        val s = AsrAudioArgs.stats(tone, 16000)
        assertEquals(-6.0, s.peakDbfs, 0.1)
        assertEquals(500.0, s.leadSilenceMs.toDouble(), 1.0)
        assertEquals(0, s.clipped)
        val silent = AsrAudioArgs.stats(ByteArray(3200), 16000)
        assertTrue(silent.peakDbfs.isInfinite()); assertEquals(100L, silent.leadSilenceMs)
    }
}
