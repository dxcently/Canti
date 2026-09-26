package ai.vox.companion

import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/** One answered choice question. [probabilities] is keyed by option text; [serverMs] is the server's own latency_ms. */
data class ChoiceAnswer(
    val choice: String,
    val probabilities: Map<String, Double>,
    val confidence: Double,
    val ms: Long,
    val serverMs: Double? = null,
) {
    fun top(n: Int): List<Pair<String, Double>> = probabilities.entries.sortedByDescending { it.value }.take(n).map { it.key to it.value }
}

/**
 * Client for TypeSafe's typed-decision API (Jev) or any drop-in server with the same endpoint (e.g.
 * finetune/servers/systemone.py):
 *   POST {base}/v1/systemone  {"state": <text>, "model": <model>, "questions": {<qid>: {"type": "choice", ...}}}
 * criteria = {option text: null}, in the given order. The API key comes from settings (never hard-coded, never
 * logged); an empty key sends no Authorization header, which is what a local drop-in server expects.
 */
class SystemOneClient(
    private val baseUrl: String,
    val model: String,
    private val apiKey: () -> String?,
    private val timeoutMs: Int = 2000,
) {
    fun requestBody(state: String, qid: String, instructions: String, options: Collection<String>): JSONObject {
        val criteria = JSONObject()
        for (text in options) criteria.put(text, JSONObject.NULL)
        val question = JSONObject().put("type", "choice").put("instructions", instructions).put("criteria", criteria)
        return JSONObject().put("state", state).put("model", model).put("questions", JSONObject().put(qid, question))
    }

    /** Ask one choice question. Throws IOException on HTTP errors or an answer that is not one of [options]. */
    fun choice(state: String, qid: String, instructions: String, options: List<String>): ChoiceAnswer {
        val t0 = System.nanoTime()
        val url = URL(baseUrl.trimEnd('/') + "/v1/systemone")
        val conn = url.openConnection() as HttpURLConnection
        try {
            conn.requestMethod = "POST"
            conn.connectTimeout = timeoutMs
            conn.readTimeout = timeoutMs
            conn.doOutput = true
            conn.setRequestProperty("Content-Type", "application/json")
            apiKey()?.takeIf { it.isNotBlank() }?.let { conn.setRequestProperty("Authorization", "Bearer $it") }
            conn.outputStream.use { it.write(requestBody(state, qid, instructions, options).toString().toByteArray()) }
            val code = conn.responseCode
            if (code != 200) {
                val err = (conn.errorStream ?: conn.inputStream)?.bufferedReader()?.use { it.readText() }?.take(200)
                throw IOException("HTTP $code ${if (code == 401 || code == 403) "(auth)" else ""} $err")
            }
            val body = JSONObject(conn.inputStream.bufferedReader().use { it.readText() })
            val ans = body.getJSONObject("answers").getJSONObject(qid)
            val choice = ans.getString("choice")
            if (choice !in options) throw IOException("model chose an unknown option '${choice.take(80)}'")
            val probs = LinkedHashMap<String, Double>()
            ans.optJSONObject("probabilities")?.let { p -> for (k in p.keys()) probs[k] = p.getDouble(k) }
            val conf = if (ans.has("confidence")) ans.getDouble("confidence") else probs[choice] ?: 1.0
            val server = if (body.has("latency_ms")) body.getDouble("latency_ms") else null
            return ChoiceAnswer(choice, probs, conf, (System.nanoTime() - t0) / 1_000_000, server)
        } finally {
            conn.disconnect()
        }
    }
}

/**
 * The gesture decision over HTTP: question "action", instructions = POLICY, criteria = the full option table in
 * schema order (the question the finetune teachers answer, teachers/scorer.py question()). The chosen option text is
 * mapped back to the action key; below [minConfidence] the decision is "none".
 */
class HttpDecider(
    private val baseUrl: String,
    private val model: String,
    private val apiKey: () -> String?,
    private val timeoutMs: Int = 2000,
    private val minConfidence: Double = 0.5,
) : Decider {
    override val name = "model"
    private val client = SystemOneClient(baseUrl, model, apiKey, timeoutMs)

    fun requestBody(input: DecisionInput): JSONObject =
        client.requestBody(input.scene.text(), "action", Vocab.POLICY, input.options.values)

    override fun decide(input: DecisionInput): Decision {
        val a = client.choice(input.scene.text(), "action", Vocab.POLICY, input.options.values.toList())
        val key = input.options.entries.first { it.value == a.choice }.key
        return if (a.confidence < minConfidence) Decision("none", "model:below-threshold($key)", a.confidence, a.ms, top = a.top(3), serverMs = a.serverMs)
        else Decision(key, "model", a.confidence, a.ms, top = a.top(3), serverMs = a.serverMs)
    }
}

/**
 * Decider modes (setting "decider"):
 *  rules  - RuleDecider only (deterministic; the test suite uses this).
 *  model  - every event goes to the model; the rule table answers if the model call fails.
 *  hybrid - wiki "Design A": explicit bindings resolve locally at once; everything else asks the model.
 */
class ChainDecider(private val mode: String, private val model: Decider?, private val rules: Decider = RuleDecider()) : Decider {
    override val name = mode

    override fun decide(input: DecisionInput): Decision {
        // Custom and ignore sounds (personalization) never reach the model unless a plain-language rule asks for it.
        Personal.localReason(input)?.let { why -> val d = rules.decide(input); return d.copy(source = "personal:$why -> ${d.source}") }
        if (mode == "rules" || model == null) return rules.decide(input)
        if (mode == "hybrid") {
            val local = rules.decide(input)
            if (local.explicit) return local
        }
        return try {
            model.decide(input)
        } catch (e: Exception) {
            val d = rules.decide(input)
            d.copy(source = "model-fallback:${e.javaClass.simpleName}:${e.message?.take(80)} -> ${d.source}")
        }
    }
}
