package ai.vox.companion

import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.SocketTimeoutException
import java.net.URL
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/** One cloud answer: the chosen option key. Cloud answers carry no calibrated probability ("unscored"). */
data class CloudAnswer(val key: String, val ms: Long, val promptTokens: Int? = null, val evalTokens: Int? = null)

/** The call was dropped because a newer event arrived (before or during the request). */
class CancelledException : IOException("cancelled: a newer event arrived")

/**
 * Client for Ollama's chat API (Ollama cloud at https://ollama.com, or a LAN Ollama): one typed choice question per
 * call, the same request finetune/sweeps/ollama_eval.py scored:
 *   POST {endpoint}/api/chat {model, stream: false, think: false, options: {temperature: 0},
 *     format: {"type": "object", "properties": {"choice": {"type": "string", "enum": [keys]}}, "required": ["choice"]},
 *     messages: [system = policy, user = state + "key: option" lines]}
 * keep_alive is left at the server default. The API key is read through [apiKey] at call time, sent only as the
 * Authorization header, and never logged or put in an exception message.
 *
 * One request in flight: [cancel] aborts it (the caller then falls back locally). Every call has a hard wall-clock
 * deadline: connect and read timeouts, plus a watchdog that disconnects at the deadline.
 */
class OllamaClient(
    endpoint: String,
    val model: String,
    private val apiKey: () -> String?,
) {
    private val url = endpoint.trim().trimEnd('/') + "/api/chat"
    private val lock = Any()
    private var current: HttpURLConnection? = null
    private var cancelled: HttpURLConnection? = null

    fun requestBody(system: String, user: String, keys: List<String>): JSONObject {
        val schema = JSONObject().put("type", "object")
            .put("properties", JSONObject().put("choice", JSONObject().put("type", "string").put("enum", JSONArray(keys))))
            .put("required", JSONArray(listOf("choice")))
        val messages = JSONArray()
            .put(JSONObject().put("role", "system").put("content", system))
            .put(JSONObject().put("role", "user").put("content", user))
        return JSONObject().put("model", model).put("stream", false).put("think", false)
            .put("options", JSONObject().put("temperature", 0)).put("format", schema).put("messages", messages)
    }

    /**
     * Ask one question. [stale] is checked just before connecting (under the same lock [cancel] takes), so a newer
     * event can never be stuck behind a request that had not started yet. Throws [CancelledException], a
     * [SocketTimeoutException] at the deadline, or an IOException for HTTP errors and answers that are not one of [keys].
     */
    fun choice(system: String, user: String, keys: List<String>, texts: List<String>, timeoutMs: Int,
               stale: () -> Boolean = { false }): CloudAnswer {
        val t0 = System.nanoTime()
        val conn = URL(url).openConnection() as HttpURLConnection
        synchronized(lock) {
            if (stale()) throw CancelledException()
            current = conn
        }
        val timedOut = java.util.concurrent.atomic.AtomicBoolean(false)
        val watchdog = WATCHDOG.schedule({ timedOut.set(true); conn.disconnect() }, timeoutMs.toLong(), TimeUnit.MILLISECONDS)
        try {
            conn.requestMethod = "POST"
            conn.connectTimeout = timeoutMs
            conn.readTimeout = timeoutMs
            conn.doOutput = true
            // ollama.com answers 403 (an HTML page, before auth) to the default "Dalvik/…" user agent.
            CantiHttp.apply(conn, apiKey())
            conn.outputStream.use { it.write(requestBody(system, user, keys).toString().toByteArray()) }
            val code = conn.responseCode
            if (code != 200) {
                val err = (conn.errorStream ?: conn.inputStream)?.bufferedReader()?.use { it.readText() }?.take(120)
                throw IOException(scrub(CantiHttp.errorText(code, conn.contentType, err)))
            }
            val body = JSONObject(conn.inputStream.bufferedReader().use { it.readText() })
            val content = body.optJSONObject("message")?.optString("content") ?: ""
            val key = parseChoice(content, keys, texts) ?: throw IOException("invalid choice '${scrub(content.take(60))}'")
            return CloudAnswer(key, (System.nanoTime() - t0) / 1_000_000,
                body.optInt("prompt_eval_count", -1).takeIf { it >= 0 }, body.optInt("eval_count", -1).takeIf { it >= 0 })
        } catch (e: IOException) {
            val wasCancelled = synchronized(lock) { cancelled === conn }
            if (wasCancelled) throw CancelledException()
            if (timedOut.get() && e !is SocketTimeoutException) throw SocketTimeoutException("deadline ${timeoutMs} ms")
            throw e
        } finally {
            watchdog.cancel(false)
            synchronized(lock) { if (current === conn) current = null }
            conn.disconnect()
        }
    }

    /** Never let the key into a message, even if a server or the model echoes it back. */
    private fun scrub(text: String?): String {
        val k = try { apiKey()?.trim() } catch (_: Exception) { null }
        val t = text ?: ""
        return if (k.isNullOrEmpty()) t else t.replace(k, "***")
    }

    /** Abort the request in flight, if any (any thread). */
    fun cancel() {
        synchronized(lock) {
            val c = current ?: return
            cancelled = c
            current = null
            Thread { try { c.disconnect() } catch (_: Exception) {} }.start()   // disconnect may touch the network
        }
    }

    companion object {
        private val WATCHDOG = Executors.newSingleThreadScheduledExecutor { r -> Thread(r, "vox-ollama-deadline").apply { isDaemon = true } }

        private val ECHO = Regex("^\"?([A-Za-z0-9_]+)\"?\\s*:\\s*(.+?)\\.?$")

        /**
         * Strict: the answer must name exactly one of [keys] ([texts] are the option texts, aligned). Accepted shapes
         * (finetune/sweeps/ollama_eval.py parse_choice, the same rules):
         *  - {"choice": k}, what the schema asks for, or a JSON string "k";
         *  - the bare key k: Ollama cloud's deepseek-v4.1-flash ignores `format` and usually answers this way;
         *  - "k: <the start of option k's text>", one line: the option line copied back.
         * Anything else is null: prose, an unknown key, or a key followed by some other text.
         */
        fun parseChoice(content: String, keys: List<String>, texts: List<String>): String? {
            val s = content.trim()
            if (s.startsWith("{")) return try { JSONObject(s).optString("choice", "").trim().takeIf { it in keys } } catch (_: Exception) { null }
            if (s.length >= 2 && s.startsWith("\"") && s.endsWith("\"")) return s.substring(1, s.length - 1).trim().takeIf { it in keys }
            if (s in keys) return s
            if ('\n' in s) return null
            val m = ECHO.matchEntire(s) ?: return null
            val k = m.groupValues[1]
            val i = keys.indexOf(k)
            if (i < 0 || i >= texts.size) return null
            return k.takeIf { texts[i].lowercase().startsWith(m.groupValues[2].trim().lowercase()) }
        }

        /** The user message: the state text, then one "key: option text" line per option (the eval's format). */
        fun userMessage(state: String, options: List<Pair<String, String>>): String =
            state + "\n\noptions (answer with the key before the colon):\n" + options.joinToString("\n") { (k, t) -> "$k: $t" }

        /** Option keys for a target question: t0..t{n-2} for the elements, "none" for NONE_OPTION (targets.py). */
        fun targetKeys(options: List<String>): List<String> =
            options.mapIndexed { i, o -> if (o == TargetVocab.NONE_OPTION) "none" else "t$i" }
    }
}

/** A gesture or phrase decision from the cloud: the action question with the full option table of the mode. */
class OllamaDecider(val client: OllamaClient, private val timeoutMs: Int = 1500) : Decider {
    override val name = "ollama"

    fun ask(input: DecisionInput, stale: () -> Boolean = { false }): CloudAnswer {
        val opts = input.options.entries.map { it.key to it.value }
        return client.choice(Vocab.POLICY, OllamaClient.userMessage(input.scene.text(), opts), opts.map { it.first },
            opts.map { it.second }, timeoutMs, stale)
    }

    override fun decide(input: DecisionInput): Decision {
        val a = ask(input)
        return Decision(a.key, "cloud", 0.0, a.ms, unscored = true)
    }
}

/**
 * Which actions need a confirm pop when the answer is unscored (a cloud answer). Risky = the actions the Executor
 * performs as an injected touch on whatever content is under the point (tap, double-tap / like, long-press, a click or
 * drag at the cursor) and target taps: a wrong guess there acts on an app's content and "go back" may not undo it.
 * Swipes, scrolls, zoom, media, volume and global navigation are left alone: they are reversible. The existing code
 * already gates the same thing on a confidence threshold (HttpDecider min_confidence, Targets.resolve); an unscored
 * answer cannot pass a threshold, so it asks instead. Outward actions ([Outward]: like, double_tap, ...) ask always.
 */
object Risk {
    val RISKY_ACTIONS = setOf("tap", "double_tap", "like", "long_press", "click", "drag_toggle")
    /** Why [d] waits for a confirm pop, or null: outward actions always ([Outward]), risky ones when unscored. */
    fun why(d: Decision): String? = when {
        Outward.isOutward(d.action) -> "outward action"
        d.unscored && d.action in RISKY_ACTIONS -> "unscored risky action"
        else -> null
    }
    fun needsConfirm(d: Decision): Boolean = why(d) != null
}

/**
 * Decider mode "escalate": the local path first, the cloud only for the hard cases, and never in the way of a gesture.
 *
 * Stays local (instant, no network):
 *  - personalization (custom / ignore sounds), as in every mode;
 *  - every explicit binding the rule table resolves: default and profile gesture bindings, cursor defaults and cursor
 *    bindings, the user's phrase rules;
 *  - what the policy itself settles: not-deliberate sounds and unbound sequences (do nothing).
 * Escalates (logged as event "escalate"):
 *  - a gesture or phrase the rule table can't settle: "*-rule-needs-model" (a plain-language rule matched but has no
 *    fixed action) or "rules:unknown-phrase" (a wording not in the phrase table). The local model answers first; the
 *    cloud is asked when the local model is absent (blank base URL), fails, or answers below min_confidence
 *    (HttpDecider's `model:below-threshold`); if the cloud fails too, the local model's answer, else the rule table.
 *    Phrases in the phrase table stay with the rule table: finetune/reports/ollama_vs_students.md measured the cloud
 *    at 0.71 on them (it breaks the screen tie-break) against 0.92 on unknown wordings;
 *  - "target" ([pickTarget]): intent cursor target picking: the cloud first (0.90 vs Verdict's 0.65 on real
 *    screens), then the local model's target question.
 * Never blocking: [submitted] (called on the main thread for every new event) cancels a cloud call in flight, and a
 * decision that starts while a newer event is queued skips the network and answers from the rule table at once.
 * Cloud answers are unscored ([Decision.unscored]): risky actions wait for a confirm pop ([Risk]).
 */
class EscalatingDecider(
    private val cloud: OllamaDecider?,
    private val local: Decider?,
    private val localTarget: ((String, List<String>) -> ChoiceAnswer)? = null,
    private val targetTimeoutMs: Int = 2500,
    private val rules: Decider = RuleDecider(),
    private val log: (String, Array<Pair<String, Any?>>) -> Unit = { ev, f -> EventLog.ev(ev, *f) },
) : Decider {
    override val name = "escalate"
    private val queued = AtomicInteger()
    private val newer: () -> Boolean = { queued.get() > 0 }

    /** A new event was queued for the decider thread: cancel a cloud call in flight (main thread). */
    fun submitted() {
        queued.incrementAndGet()
        cloud?.client?.cancel()
    }

    /** A newer event was decided locally ([local], main thread): cancel a cloud call in flight, queue nothing. */
    fun cancelInFlight() { cloud?.client?.cancel() }

    /** [decide]'s answer when it stays on the rule table (a gesture: phrases may read the screen). */
    override fun local(input: DecisionInput): Decision? {
        if (input.scene.phrase != null) return null
        Personal.localReason(input)?.let { why -> val d = rules.decide(input); return d.copy(source = "personal:$why -> ${d.source}") }
        val r = rules.decide(input)
        if (r.explicit) return r
        if (r.source !in UNSETTLED && !r.source.endsWith("-rule-needs-model")) return r
        return null
    }

    /** Called at the start of each decision on the worker thread: true if a newer event is already waiting. */
    private fun started(): Boolean = queued.updateAndGet { maxOf(0, it - 1) } > 0

    override fun decide(input: DecisionInput): Decision {
        val stale = started()
        Personal.localReason(input)?.let { why -> val d = rules.decide(input); return d.copy(source = "personal:$why -> ${d.source}") }
        val r = rules.decide(input)
        if (r.explicit) return r
        if (r.source !in UNSETTLED && !r.source.endsWith("-rule-needs-model")) return r   // not deliberate / unbound: none
        val what = if (input.scene.phrase != null) "phrase" else "gesture"
        if (stale) return skipped(what, r)
        // The local model first; the cloud when it is absent, fails, or is below min_confidence.
        var why = "$what:no-local-model"
        var localAnswer: Decision? = null
        if (local != null) {
            try {
                val m = local.decide(input)
                if (!m.source.startsWith("model:below-threshold")) return m
                localAnswer = m; why = "$what:low-confidence(${"%.2f".format(m.confidence)})"
            } catch (e: Exception) { why = "$what:local-failed:${e.javaClass.simpleName}" }
        }
        cloudDecision(why, input)?.let { return it }
        // Cloud failed: the local model's answer (below threshold = none), else the rule table.
        return localAnswer?.let { it.copy(source = "escalate-fallback -> ${it.source}") } ?: r.copy(source = "escalate-fallback -> ${r.source}")
    }

    private fun skipped(why: String, r: Decision): Decision {
        log("escalate", arrayOf("kind" to why, "outcome" to "skipped (newer event)", "fallback" to r.source))
        return r.copy(source = "escalate-skipped -> ${r.source}")
    }

    private fun cloudDecision(why: String, input: DecisionInput): Decision? {
        val c = cloud ?: run {
            log("escalate", arrayOf("kind" to why, "outcome" to "no cloud (key or endpoint not set)")); return null
        }
        val t0 = System.nanoTime()
        return try {
            val a = c.ask(input, newer)
            log("escalate", arrayOf("kind" to why, "outcome" to "ok", "model" to c.client.model, "choice" to a.key,
                "ms" to a.ms, "tokens_in" to a.promptTokens, "tokens_out" to a.evalTokens))
            Decision(a.key, "cloud:$why", 0.0, a.ms, unscored = true)
        } catch (e: Exception) {
            log("escalate", arrayOf("kind" to why, "outcome" to outcome(e), "model" to c.client.model,
                "ms" to (System.nanoTime() - t0) / 1_000_000, "error" to e.message?.take(120)))
            null
        }
    }

    /**
     * Intent cursor target picking: the cloud first ([targetTimeoutMs]), then the local model's "target" question.
     * The cloud answer comes back unscored (confidence 0, no probabilities), so Targets.resolve highlights it for a
     * confirm pop instead of tapping. Throws if every path failed.
     */
    fun pickTarget(state: String, options: List<String>): ChoiceAnswer {
        val stale = started()
        val keys = OllamaClient.targetKeys(options)
        val c = cloud
        if (stale) log("escalate", arrayOf("kind" to "target", "outcome" to "skipped (newer event)"))
        else if (c == null) log("escalate", arrayOf("kind" to "target", "outcome" to "no cloud (key or endpoint not set)"))
        else {
            val t0 = System.nanoTime()
            try {
                val a = c.client.choice(TargetVocab.POLICY, OllamaClient.userMessage(state, keys.zip(options)), keys, options, targetTimeoutMs, newer)
                log("escalate", arrayOf("kind" to "target", "outcome" to "ok", "model" to c.client.model, "choice" to a.key,
                    "ms" to a.ms, "tokens_in" to a.promptTokens, "tokens_out" to a.evalTokens))
                return ChoiceAnswer(options[keys.indexOf(a.key)], emptyMap(), 0.0, a.ms, unscored = true)
            } catch (e: Exception) {
                log("escalate", arrayOf("kind" to "target", "outcome" to outcome(e), "model" to c.client.model,
                    "ms" to (System.nanoTime() - t0) / 1_000_000, "error" to e.message?.take(120)))
                if (e is CancelledException) throw e
            }
        }
        val lt = localTarget ?: throw IOException("no target model answered")
        if (newer()) throw CancelledException()
        return lt(state, options)
    }

    companion object {
        /** Rule table answers that mean "the table can't settle this" besides the "*-rule-needs-model" ones. */
        val UNSETTLED = setOf("rules:unknown-phrase")
    }

    private fun outcome(e: Exception) = when (e) {
        is CancelledException -> "cancelled (newer event)"
        is SocketTimeoutException -> "timeout"
        else -> if (e.message?.startsWith("invalid choice") == true) "invalid choice" else "error"
    }
}
