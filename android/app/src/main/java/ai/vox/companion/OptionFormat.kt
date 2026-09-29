package ai.vox.companion

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Which target option text the pickers get (Targets.kt OPTION FORMAT): "v1" = "{label} ({role}, {position})", the
 * format every Verdict model so far was trained on; "v2" = with row context and rank; "v2i" = v2 plus the indented-list
 * tree context (a sub-row's parent label). The local target model declares its format; the cloud gets the same options,
 * so it follows the same choice.
 *
 * Contract: `GET {base_url}/health` (the local model server) answers JSON with a top-level `"option_format": "v2"` or
 * `"v2i"`. A missing or unknown field, no local model (blank base URL), an HTTP error or a timeout all mean v1: the new
 * text never reaches a model that was not trained on it.
 */
object OptionFormat {
    const val V1 = "v1"
    const val V2 = "v2"
    const val V2I = "v2i"

    /** The format a model's metadata declares: v2i / v2 only when it says exactly that. */
    fun of(meta: JSONObject?): String = when (meta?.optString("option_format")) {
        V2I -> V2I
        V2 -> V2
        else -> V1
    }

    /** (format, why) for the local model at [baseUrl]; never throws. */
    fun fetch(baseUrl: String, apiKey: String?, timeoutMs: Int = 1500): Pair<String, String> {
        if (baseUrl.isBlank()) return V1 to "no local model"
        return try {
            val conn = URL(baseUrl.trim().trimEnd('/') + "/health").openConnection() as HttpURLConnection
            try {
                conn.connectTimeout = timeoutMs; conn.readTimeout = timeoutMs
                CantiHttp.apply(conn, apiKey)
                if (conn.responseCode != 200) return V1 to "health HTTP ${conn.responseCode}"
                val meta = JSONObject(conn.inputStream.bufferedReader().use { it.readText() })
                of(meta) to (if (meta.has("option_format")) "declared '${meta.optString("option_format").take(20)}'" else "not declared")
            } finally { conn.disconnect() }
        } catch (e: Exception) {
            V1 to "health failed: ${e.javaClass.simpleName}"
        }
    }
}
