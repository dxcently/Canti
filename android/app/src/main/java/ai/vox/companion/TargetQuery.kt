package ai.vox.companion

import java.util.Locale

/**
 * The spoken target query, cleaned before it reaches any target picker (TargetMatcher, the local Verdict model, the
 * cloud): hesitations, filler words, politeness, restarts and self-corrections out, everything else as said (case and
 * word order kept). Pure Kotlin; the word lists come from [PhraseGrammar] (shared, not copied). TargetQueryTest runs
 * the shared vectors in app/src/test/resources/target_query_cases.json; finetune mirrors these rules in Python.
 *
 * RULES (exact, in order; "key" = the token lowercased, ' and ’ removed, then non-letter/digit characters stripped from
 * both ends; "comma-marked" = the raw token ends with "," or ";"):
 *  1. Tokens: "—", "–" and "--" become " — "; "…" becomes " "; whitespace before , ; : ! ? . is removed; split on
 *     whitespace.
 *  2. Self-corrections split the tokens into parts; the LAST part that is non-empty after rules 3-7 is the query (none:
 *     ""). Markers, checked at each token left to right, longer first:
 *     - the multi-word PhraseGrammar.CORRECTIONS ("no wait", "wait no", "no no", "no sorry", "sorry no", "i mean",
 *       "scratch that", "or rather", "never mind", "forget it", "cancel that"), matched on keys;
 *     - a single-word one ("no", "wait", "sorry", "actually", "nevermind") only if (it is not the first token or it is
 *       comma-marked) and the previous key is not in [ARG_WORDS] and the next key is not "thanks"/"thank";
 *     - a dash token (key empty, "—" or "-") that is neither first nor last.
 *  3. Dropped anywhere in the part: key-empty tokens; hesitations (PhraseGrammar.HESITATION: um, uh, er, ah, hmm, mm,
 *     eh and drawn-out spellings); a cut-off fragment (raw token, trailing , ; removed, ends with "-", not the part's
 *     last token); "please", "pls", "kinda", "sorta"; the phrases of PhraseGrammar.SOFT_PHRASES ("you know what", "you
 *     know", "kind of", "sort of", "real quick", "if you can", "if you could", matched left to right, longer first)
 *     except "kind of"/"sort of" after a key in [KIND_KEEP] and "you know..." after "do"/"did"/"dont"/"didnt"/"if".
 *  4. "like" (neighbours = the part's original tokens, before rule 3's removals):
 *     last token -> kept; comma-marked -> dropped; next key in [LIKE_OBJECTS] -> kept; previous token comma-marked ->
 *     dropped; previous key in [LIKE_KEEP_AFTER] -> kept; previous token dropped (rule 3 or an earlier "like") or its
 *     key in [LEAD_WORDS] or [LEAD_GUARDED] -> dropped; not first and (next key in [DETERMINERS] or next token dropped)
 *     -> dropped; otherwise kept. ("the like button", "tap like", "like the photo" keep it; "um, like, the ..." and
 *     "the blue like the one" drop it.)
 *  5. Lead, repeatedly while more than one token is left: a PhraseGrammar.LEAD_PHRASES phrase ("can you", "could you",
 *     "would you mind", "i want you to", "go ahead and", ...) shorter than what is left; else a key in [LEAD_WORDS];
 *     else a key in [LEAD_GUARDED] ("ok", "yes", "right", ...) that is comma-marked or followed by a key in
 *     LEAD_WORDS, LEAD_GUARDED or DETERMINERS ("ok button", "right arrow" stay).
 *  6. Tail, repeatedly while more than one token is left (longer phrases first): a [TRAIL_ANY] phrase unless the key
 *     before it is in [ARG_WORDS] or is "no" ("no thanks" stays); a [TRAIL_COMMA] phrase only when the token before it
 *     is comma-marked ("the settings, yeah that one"; "Buy now", "Try again" stay).
 *  7. Repeats: an n-gram (n = 3, 2, 1, first match from the left) immediately repeated on keys is kept once, the later
 *     copy; n-grams made only of numbers (digits or number words) are left alone. Repeat until nothing changes.
 *  8. Output: each token with , ; : - – — trimmed from both ends, empty ones out, joined by one space, then trailing
 *     . , ; : and spaces trimmed. No letter or digit left -> "".
 * [forPicker] falls back to the trimmed raw text when the result is "" (never send an empty query).
 */
object TargetQuery {
    val DETERMINERS = setOf("the", "a", "an", "this", "that", "these", "those", "my", "your", "his", "her", "their", "our")
    /** "like" before one of these is the like button / count, never a filler. */
    val LIKE_OBJECTS = setOf("button", "icon", "heart", "count", "counter", "thumb", "thumbs", "symbol", "sign")
    /** "like" after one of these is content ("the like button", "looks like a heart"). */
    val LIKE_KEEP_AFTER = DETERMINERS + setOf("looks", "look", "looked", "looking", "something", "anything", "sounds", "seems", "feels")
    /** "kind of" / "sort of" after one of these is content ("what kind of"). */
    val KIND_KEEP = setOf("what", "which", "any", "some", "every", "this", "that", "same")
    /** Lead words dropped at the start. */
    val LEAD_WORDS = setOf("so", "well", "oh", "hey", "and", "just", "also", "alright", "actually", "canti")
    /** Lead words that can be a label ("OK", "Yes", "Right arrow", "Now playing"): dropped only when marked off. */
    val LEAD_GUARDED = setOf("ok", "okay", "yeah", "yes", "right", "now", "then", "sure")
    val TRAIL_ANY = listOf("thanks", "thank you", "thx", "for me", "i guess", "i think", "or whatever", "or something", "canti")
    val TRAIL_COMMA = listOf("yeah", "yep", "yes", "ok", "okay", "right", "now", "then", "instead", "that one", "this one",
        "yeah that one", "yes that one")
    /** A word after one of these is its argument, not a correction or a tail ("tap no", "the no button", "says wait"). */
    val ARG_WORDS = PhraseGrammar.TAKES_ARG + setOf("a", "an", "says", "called", "labelled", "labeled", "or")
    private val SINGLE_MARKERS = PhraseGrammar.CORRECTIONS.filter { ' ' !in it }.toSet()
    private val MULTI_MARKERS = PhraseGrammar.CORRECTIONS.filter { ' ' in it }.map { it.split(' ') }.sortedByDescending { it.size }
    private val SOFT = PhraseGrammar.SOFT_PHRASES.map { it.split(' ') }.sortedByDescending { it.size }
    private val DROP_WORDS = setOf("please", "pls", "kinda", "sorta")
    private val LEADS = PhraseGrammar.LEAD_PHRASES.map { it.split(' ') }.sortedByDescending { it.size }
    private val TRAILS = (TRAIL_ANY.map { it to false } + TRAIL_COMMA.map { it to true })
        .map { (p, c) -> p.split(' ') to c }.sortedByDescending { it.first.size }
    private const val TRIM = ",;:-–—"

    private class Tok(val raw: String) {
        val key = raw.lowercase(Locale.ROOT).replace("'", "").replace("’", "").trim { !it.isLetterOrDigit() }
        val comma get() = raw.endsWith(",") || raw.endsWith(";")
        val dash get() = key.isEmpty() && (raw.contains('—') || raw.trim(',', ';', ':', '.', '!', '?') == "-")
    }

    fun key(raw: String) = Tok(raw).key

    fun normalize(raw: String): String {
        var t = raw.replace("—", " — ").replace("–", " — ").replace("--", " — ").replace("…", " ")
        t = Regex("\\s+([,;:!?.])").replace(t, "$1")
        val toks = t.split(Regex("\\s+")).filter { it.isNotEmpty() }.map(::Tok)
        for (part in parts(toks).asReversed()) {
            val out = render(clean(part))
            if (out.isNotEmpty()) return out
        }
        return ""
    }

    /** The query sent to a picker: [normalize], or the raw text if nothing is left. */
    fun forPicker(raw: String): String = normalize(raw).ifEmpty { raw.trim() }

    private fun keysAt(toks: List<Tok>, i: Int, words: List<String>) =
        i + words.size <= toks.size && words.indices.all { toks[i + it].key == words[it] }

    private fun parts(toks: List<Tok>): List<List<Tok>> {
        val out = ArrayList<List<Tok>>(); var cur = ArrayList<Tok>(); var i = 0
        while (i < toks.size) {
            val len = markerAt(toks, i)
            if (len > 0) { out += cur; cur = ArrayList(); i += len } else { cur += toks[i]; i++ }
        }
        out += cur
        return out
    }

    private fun markerAt(toks: List<Tok>, i: Int): Int {
        MULTI_MARKERS.firstOrNull { keysAt(toks, i, it) }?.let { return it.size }
        val tk = toks[i]
        if (tk.dash) return if (i >= 1 && i < toks.size - 1) 1 else 0
        if (tk.key in SINGLE_MARKERS && (i >= 1 || tk.comma) && toks.getOrNull(i - 1)?.key !in ARG_WORDS &&
            toks.getOrNull(i + 1)?.key !in setOf("thanks", "thank")) return 1
        return 0
    }

    private fun clean(p: List<Tok>): List<Tok> {
        val n = p.size
        val drop = BooleanArray(n)
        for (i in 0 until n) {
            val k = p[i].key
            if (k.isEmpty() || PhraseGrammar.isHesitation(k) || k in DROP_WORDS ||
                (i < n - 1 && p[i].raw.trimEnd(',', ';').endsWith("-"))) drop[i] = true
        }
        var i = 0
        while (i < n) {
            val ph = SOFT.firstOrNull { keysAt(p, i, it) }
            val prev = p.getOrNull(i - 1)?.key
            val keep = ph != null && ((ph[0] in setOf("kind", "sort") && prev in KIND_KEEP) ||
                (ph[0] == "you" && prev in setOf("do", "did", "dont", "didnt", "if")))
            if (ph != null && !keep) { for (j in i until i + ph.size) drop[j] = true; i += ph.size } else i++
        }
        for (j in 0 until n) {
            if (p[j].key != "like" || drop[j]) continue
            val prev = p.getOrNull(j - 1); val next = p.getOrNull(j + 1)
            drop[j] = when {
                next == null -> false
                p[j].comma -> true
                next.key in LIKE_OBJECTS -> false
                prev != null && prev.comma -> true
                prev != null && prev.key in LIKE_KEEP_AFTER -> false
                prev != null && (drop[j - 1] || prev.key in LEAD_WORDS || prev.key in LEAD_GUARDED) -> true
                prev != null && (next.key in DETERMINERS || drop[j + 1]) -> true
                else -> false
            }
        }
        var l = p.filterIndexed { j, _ -> !drop[j] }
        // lead
        while (l.size > 1) {
            val ph = LEADS.firstOrNull { keysAt(l, 0, it) && l.size > it.size }
            if (ph != null) { l = l.drop(ph.size); continue }
            val k = l[0].key
            if (k in LEAD_WORDS) { l = l.drop(1); continue }
            val nk = l[1].key
            if (k in LEAD_GUARDED && (l[0].comma || nk in LEAD_WORDS || nk in LEAD_GUARDED || nk in DETERMINERS)) { l = l.drop(1); continue }
            break
        }
        // tail
        while (l.size > 1) {
            val hit = TRAILS.firstOrNull { (w, needsComma) ->
                if (l.size <= w.size || !keysAt(l, l.size - w.size, w)) return@firstOrNull false
                val before = l[l.size - w.size - 1]
                if (needsComma) before.comma else before.key !in ARG_WORDS && before.key != "no"
            } ?: break
            l = l.dropLast(hit.first.size)
        }
        // repeats
        var changed = true
        while (changed) {
            changed = false
            loop@ for (g in 3 downTo 1) {
                for (s in 0..l.size - 2 * g) {
                    val a = l.subList(s, s + g).map { it.key }
                    if (a != l.subList(s + g, s + 2 * g).map { it.key } || a.all { PhraseGrammar.isNumberWord(it) }) continue
                    l = l.take(s) + l.drop(s + g); changed = true; break@loop
                }
            }
        }
        return l
    }

    private fun render(l: List<Tok>): String {
        val s = l.map { it.raw.trim { c -> c in TRIM } }.filter { it.isNotEmpty() }.joinToString(" ").trimEnd('.', ',', ';', ':', ' ')
        return if (s.any { it.isLetterOrDigit() }) s else ""
    }
}
