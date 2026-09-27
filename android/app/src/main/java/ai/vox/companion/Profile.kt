package ai.vox.companion

import org.json.JSONArray
import org.json.JSONObject

/**
 * A binding from a sound sequence (or a spoken phrase) to an action.
 *  kind = "fixed": the action is known; the local decider applies it and the model sees it as a rule sentence.
 *  kind = "rule":  a plain-language rule for the model; `action` (optional) is what the local fallback does.
 * action = "none" disables the sequence (a "disable" rule).
 */
data class Binding(
    val scope: String,              // "global", "app:<package>", "cursor", "phrases"
    val phrase: List<String>,       // sound labels; empty for spoken-phrase bindings
    val kind: String,
    val action: String?,
    val rule: String?,
    val say: String? = null,        // spoken phrase for scope "phrases"
)

/**
 * Global profile plus per-app overrides (wiki gesture-vocabulary.md "Profiles"). JSON:
 * { "global": [ {"phrase": ["rise","rise"], "kind": "fixed", "action": "notifications"} ],
 *   "app:app.organicmaps": [ {"phrase": ["rise"], "kind": "fixed", "action": "zoom_in"} ],
 *   "cursor": [ {"phrase": ["hiss"], "kind": "fixed", "action": "drag_toggle"} ],
 *   "phrases": [ {"say": "boom", "kind": "fixed", "action": "take_photo"} ] }
 * Optional "name" (default "default") selects the enrollment store (personalization). An enrolled custom sound is
 * bound with {"sound": "my:<name>", "action": ...} (shorthand for "phrase": ["my:<name>"]).
 */
class Profile(val bindings: List<Binding>, val name: String = DEFAULT_NAME) {

    fun appBindings(pkg: String) = bindings.filter { it.scope == "app:$pkg" }
    fun globalBindings() = bindings.filter { it.scope == "global" }
    fun cursorBindings() = bindings.filter { it.scope == "cursor" }
    fun phraseBindings() = bindings.filter { it.scope == "phrases" }

    /**
     * The sound sequences worth waiting for in this app and mode (resolution order app > global > defaults and app-only
     * bindings). Used by the sequencer: a sound only waits if one of these multi-sound sequences starts with it.
     * Disabled sequences are not bound. A sequence whose fixed action is the same as that of a shorter bound prefix is
     * left out: waiting for it would change nothing but the delay (default "hiss click" = back, so a hiss acts at once;
     * a click that follows within the gap is absorbed, [absorbedSequences]).
     */
    fun boundSequences(pkg: String, mode: String): Set<List<String>> = sequences(pkg, mode).first

    /**
     * The sequences [boundSequences] leaves out because a shorter bound prefix does the same (default "hiss click" =
     * back = "hiss"). The sequencer acts on the prefix at once and absorbs the rest if it follows within the gap, so
     * "hiss click" is one back ([Sequencer]). None in cursor mode.
     */
    fun absorbedSequences(pkg: String, mode: String): Set<List<String>> = sequences(pkg, mode).second

    private fun sequences(pkg: String, mode: String): Pair<Set<List<String>>, Set<List<String>>> {
        if (mode == "cursor") {
            val bound = cursorBindings().filter { it.action != "none" }.map { it.phrase }.toMutableSet()
            // "pop pop" names a target (intent cursor mode) unless a cursor rule claims the sequence.
            if (cursorBindings().none { it.phrase == CURSOR_LISTEN }) bound += CURSOR_LISTEN
            return bound to emptySet<List<String>>()
        }
        val table = LinkedHashMap<List<String>, String?>()
        for ((seq, a) in Vocab.DEFAULT_BINDINGS) table[seq] = a
        for ((seq, a) in Vocab.APP_ONLY_BINDINGS) table[seq] = a
        for (b in globalBindings()) table[b.phrase] = b.action ?: RULE
        for (b in appBindings(pkg)) table[b.phrase] = b.action ?: RULE
        val live = table.filterValues { it != "none" }
        val (bound, absorbed) = live.keys.partition { seq ->
            val a = live[seq]
            a == RULE || (1 until seq.size).none { live[seq.subList(0, it)] == a }
        }
        return LinkedHashSet(bound) to LinkedHashSet(absorbed)
    }

    /**
     * The rule sentences the model sees under "my rules:" (only rules that apply to this app and mode). Fixed rules on
     * custom sounds (`my:<name>`) are left out: they are always resolved locally, and the model has no training data
     * for them before v6.
     */
    fun ruleTexts(pkg: String, appName: String, mode: String): List<String> {
        val out = mutableListOf<String>()
        fun shown(b: Binding) = b.kind == "rule" || b.phrase.none { it.startsWith(Personal.MY) }
        when (mode) {
            "cursor" -> cursorBindings().filter(::shown).forEach { out += it.rule ?: cursorRuleText(it) }
            "listening" -> phraseBindings().forEach { out += it.rule ?: phraseRuleText(it) }
        }
        globalBindings().filter(::shown).forEach { out += it.rule ?: globalRuleText(it) }
        appBindings(pkg).filter(::shown).forEach { out += it.rule ?: appRuleText(it, appName) }
        return out
    }

    companion object {
        /** In cursor mode, "pop pop" opens the listening window for a spoken target (handled by the app, not the model). */
        val CURSOR_LISTEN = listOf("pop", "pop")
        private const val RULE = "\u0000rule"   // a plain-language rule: the model decides, so never "the same action"

        const val DEFAULT_NAME = "default"

        fun empty() = Profile(emptyList())

        fun parse(json: JSONObject): Profile {
            val out = mutableListOf<Binding>()
            val name = if (json.has("name")) json.getString("name") else DEFAULT_NAME
            require(EnrollmentStore.PROFILE_RE.matches(name)) { "profile name must match ${EnrollmentStore.PROFILE_RE.pattern}" }
            for (scope in json.keys()) {
                if (scope == "name") continue
                require(scope == "global" || scope == "cursor" || scope == "phrases" || scope.startsWith("app:")) {
                    "unknown profile scope '$scope'"
                }
                val arr: JSONArray = json.getJSONArray(scope)
                for (i in 0 until arr.length()) {
                    val o = arr.getJSONObject(i)
                    require(!(o.has("sound") && o.has("phrase"))) { "use either 'sound' or 'phrase'" }
                    val phrase = if (o.has("sound")) listOf(o.getString("sound"))
                        else o.optJSONArray("phrase")?.let { a -> List(a.length()) { a.getString(it) } } ?: emptyList()
                    val kind = o.optString("kind", "fixed")
                    require(kind == "fixed" || kind == "rule") { "kind must be fixed or rule" }
                    val action = if (o.has("action") && !o.isNull("action")) o.getString("action") else null
                    val table = if (scope == "cursor") Vocab.CURSOR_ACTIONS else Vocab.ACTIONS
                    if (action != null) require(action in table) { "unknown action '$action' in $scope" }
                    val rule = if (o.has("rule")) o.getString("rule") else null
                    require(kind == "fixed" || rule != null) { "a rule binding needs 'rule' text" }
                    require(kind == "rule" || action != null) { "a fixed binding needs 'action'" }
                    val say = if (o.has("say")) o.getString("say").lowercase().trim() else null
                    if (scope == "phrases") require(say != null) { "phrase bindings need 'say'" }
                    else {
                        require(phrase.isNotEmpty() && phrase.size <= 3) { "phrase must have 1-3 sounds" }
                        for (s in phrase) require(s in Vocab.CONTOURS || s in Vocab.DISCRETE || Personal.isCustomLabel(s)) { "unknown sound '$s'" }
                    }
                    out += Binding(scope, phrase, kind, action, rule, say)
                }
            }
            return Profile(out, name)
        }

        fun seqWords(seq: List<String>) = seq.joinToString(" followed by ") {
            if (it.startsWith(Personal.MY)) "my \"${it.removePrefix(Personal.MY)}\" sound" else Vocab.GESTURE_WORDS.getValue(it)
        }

        fun appRuleText(b: Binding, appName: String): String =
            if (b.action == "none") Vocab.DISABLE_RULE_TEMPLATE.replace("{app}", appName).replace("{g}", seqWords(b.phrase))
            else Vocab.APP_RULE_TEMPLATE.replace("{app}", appName).replace("{g}", seqWords(b.phrase))
                .replace("{a}", Vocab.ACTIONS.getValue(b.action!!))

        fun globalRuleText(b: Binding): String =
            if (b.action == "none") "Everywhere, ignore ${seqWords(b.phrase)}."
            else Vocab.GLOBAL_RULE_TEMPLATE.replace("{g}", seqWords(b.phrase)).replace("{a}", Vocab.ACTIONS.getValue(b.action!!))

        fun cursorRuleText(b: Binding): String =
            "In cursor mode, ${seqWords(b.phrase)} means ${Vocab.CURSOR_ACTIONS.getValue(b.action!!)}."

        fun phraseRuleText(b: Binding): String =
            Vocab.PHRASE_RULE_TEMPLATE.replace("{p}", b.say!!).replace("{a}", Vocab.ACTIONS.getValue(b.action!!))
    }
}
