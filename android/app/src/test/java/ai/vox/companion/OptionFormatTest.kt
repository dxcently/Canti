package ai.vox.companion

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Test
import java.net.ServerSocket
import kotlin.concurrent.thread

/** The target option format follows the local model's declared `option_format`; anything else is v1 (OptionFormat.kt). */
class OptionFormatTest {
    @Test fun onlyAnExplicitV2IsV2() {
        assertEquals(OptionFormat.V2, OptionFormat.of(JSONObject("""{"status":"ok","option_format":"v2"}""")))
        assertEquals("a model without the field is v1", OptionFormat.V1, OptionFormat.of(JSONObject("""{"status":"ok","engine":"verdict"}""")))
        assertEquals(OptionFormat.V1, OptionFormat.of(JSONObject("""{"option_format":"v1"}""")))
        assertEquals(OptionFormat.V1, OptionFormat.of(JSONObject("""{"option_format":"v3"}""")))
        assertEquals(OptionFormat.V1, OptionFormat.of(JSONObject("""{"option_format":2}""")))
        assertEquals(OptionFormat.V1, OptionFormat.of(null))
    }

    /** A one-shot HTTP server answering every request with [code] and [body]; returns its base URL and the paths asked. */
    private fun serve(code: Int, body: String): Pair<String, MutableList<String>> {
        val server = ServerSocket(0, 5, java.net.InetAddress.getLoopbackAddress())
        val paths = java.util.Collections.synchronizedList(mutableListOf<String>())
        thread(isDaemon = true) {
            while (!server.isClosed) {
                val c = try { server.accept() } catch (e: Exception) { break }
                c.use { sock ->
                    val inp = sock.getInputStream().bufferedReader()
                    val lines = generateSequence { inp.readLine() }.takeWhile { it.isNotEmpty() }.toList()
                    paths += lines.first().split(' ')[1]
                    sock.getOutputStream().write(("HTTP/1.1 $code X\r\nContent-Type: application/json\r\nContent-Length: ${body.toByteArray().size}\r\n" +
                        "Connection: close\r\n\r\n$body").toByteArray())
                }
            }
        }
        return "http://127.0.0.1:${server.localPort}/" to paths
    }

    @Test fun readFromTheLocalModelsHealth() {
        val (v2, paths) = serve(200, """{"status":"ok","engine":"verdict","option_format":"v2"}""")
        assertEquals(OptionFormat.V2, OptionFormat.fetch(v2, null).first)
        assertEquals(listOf("/health"), paths)
        val (plain, _) = serve(200, """{"status":"ok","engine":"verdict"}""")
        assertEquals(OptionFormat.V1 to "not declared", OptionFormat.fetch(plain, null))
        val (missing, _) = serve(404, """{"detail":"Not Found"}""")
        assertEquals(OptionFormat.V1, OptionFormat.fetch(missing, null).first)
        val (html, _) = serve(200, "<html>proxy</html>")
        assertEquals(OptionFormat.V1, OptionFormat.fetch(html, null).first)
        assertEquals(OptionFormat.V1 to "no local model", OptionFormat.fetch("  ", null))
        val dead = ServerSocket(0).let { val p = it.localPort; it.close(); "http://127.0.0.1:$p" }
        assertEquals(OptionFormat.V1, OptionFormat.fetch(dead, null, timeoutMs = 500).first)
    }
}
