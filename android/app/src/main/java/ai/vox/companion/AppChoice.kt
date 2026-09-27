package ai.vox.companion

/**
 * Two installed apps answer to one spoken name ("open YouTube": YouTube and a YouTube mod). Pure (AppChoiceTest):
 *  0. the user's preference ([prefer], `app_prefer`): "youtube" means RVX when RVX is installed;
 *  1. the most recently used, when usage access is already granted ([lastUsed] non-null; Canti never asks for it);
 *  2. else the official app: a package Canti knows by name ([official]: [Vocab.APPS] and [AppMatcher.ALIASES] keys);
 *  3. else null: ask which (never a guess).
 */
object AppChoice {
    val OFFICIAL: Set<String> get() = Vocab.APPS.keys + AppMatcher.ALIASES.keys

    /** `app_prefer` default: the package a name resolves to -> the package to open instead, when that one is installed. */
    const val DEFAULT_PREFER = "com.google.android.youtube=app.rvx.android.youtube"

    /** "from=to,from=to" -> map. Blank = no preferences. Malformed -> IllegalArgumentException (the config op rejects it). */
    fun parsePrefer(s: String): Map<String, String> = s.split(',').map { it.trim() }.filter { it.isNotEmpty() }.associate { e ->
        val kv = e.split('=').map { it.trim() }
        require(kv.size == 2 && kv.all { PKG.matches(it) } && kv[0] != kv[1]) { "app_prefer entries are package=package, got '$e'" }
        kv[0] to kv[1]
    }
    private val PKG = Regex("[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z][A-Za-z0-9_]*)+")

    /** [pkg], or the package the user prefers over it when that one is installed ([installed]). One hop, no chains. */
    fun prefer(pkg: String, prefs: Map<String, String>, installed: (String) -> Boolean): String =
        prefs[pkg]?.takeIf(installed) ?: pkg

    fun pick(candidates: List<String>, lastUsed: Map<String, Long>?, official: Set<String> = OFFICIAL,
             prefs: Map<String, String> = emptyMap()): String? {
        val c = candidates.distinct()
        if (c.size <= 1) return c.firstOrNull()
        c.firstNotNullOfOrNull { prefs[it]?.takeIf { p -> p in c } }?.let { return it }
        if (lastUsed != null) {
            val used = c.filter { (lastUsed[it] ?: 0L) > 0L }.sortedByDescending { lastUsed[it] }
            if (used.isNotEmpty() && (used.size == 1 || lastUsed[used[0]] != lastUsed[used[1]])) return used[0]
        }
        val off = c.filter { it in official }
        return off.singleOrNull()
    }
}
