package ai.vox.companion

/**
 * Spoken input while a target choice is up ([VoxService.choiceInput]): a number picks a candidate, "cancel"/"never
 * mind" cancels, a phrase that names one or more of the current candidates narrows them, and anything that parses to a
 * concrete command (e.g. "go home") cancels the choice and runs normally. Pure Kotlin (SpokenPickTest).
 *
 * Rules, in order, on the phrase lowercased and collapsed by [PhraseGrammar.basic]:
 *  1. "cancel", "never mind", "nevermind", "forget it" -> [Cancel].
 *  2. A bare number anywhere in the phrase, everything else a lead/filler word ("number", "option", "open", "tap",
 *     "click", "press", "pick", "choose", "select", "the", "a", "an", "one", "of", "please", "it", "that", "this") ->
 *     [Tap] of that 1-based candidate ("2", "two", "number 2", "open 2", "the second one", "second"). Out of range
 *     (1..N) -> [Hint] and the choice stays.
 *  3. Otherwise the phrase narrows: [TargetMatcher.match] re-ranks ONLY the current candidates (label + context words,
 *     the same matcher rules). One clear winner -> [Narrow] of a single target (the caller taps it); several remain ->
 *     [Narrow] of those (renumbered, still listening); none match -> the phrase is not about the candidates.
 *  4. A phrase that matches no candidate but parses to a concrete command -> [RunNormally] (cancel the choice and run
 *     the phrase as a normal command): nav / volume / swipe / timer / an app name (installed or not — "open settings",
 *     "open snapchat"), or a tap with an explicit verb or a fallback command ("tap <thing>", a bare "home"/"mute").
 *     A bare word that only names an element in cursor mode ("banana") is not a command. Anything else that matches
 *     nothing -> [Hint]("no match, say a number") and the choice stays.
 */
object SpokenPick {
    sealed class Result {
        /** Pick the 1-based candidate [index] (already range-checked). */
        data class Tap(val index: Int) : Result()
        object Cancel : Result()
        /** Move the highlight to the next candidate (a follow-up "the other one" / "the next one" while picking). */
        object Next : Result()
        /** The narrowed candidates (>= 1): one means tap it, several means renumber and keep listening. */
        data class Narrow(val targets: List<Target>) : Result()
        /** Keep the current choice and show [text]. */
        data class Hint(val text: String) : Result()
        /** Cancel the choice and run the phrase as a normal command. */
        object RunNormally : Result()
    }

    private val CANCEL = setOf("cancel", "never mind", "nevermind", "forget it")
    /** Follow-up "other/next" phrases move the highlight (checked before the number words: "one" is a number). */
    private val NEXT = setOf("the other one", "other one", "not that one", "the next one", "next one")
    private val LEAD_FILLER = setOf("number", "option", "open", "tap", "click", "press", "pick", "choose", "select",
        "the", "a", "an", "one", "of", "please", "it", "that", "this", "item")

    fun parse(text: String, candidates: List<Target>): Result {
        val cleaned = PhraseGrammar.basic(text)
        val words = cleaned.split(' ').filter { it.isNotEmpty() }
        if (words.isEmpty()) return Result.Hint("say a number or more words")
        if (cleaned in CANCEL) return Result.Cancel
        if (cleaned in NEXT) return Result.Next

        pickNumber(words)?.let { n ->
            return if (n in 1..candidates.size) Result.Tap(n)
            else Result.Hint("no such number: say 1 to ${candidates.size}")
        }

        return when (val out = TargetMatcher.match(candidates, text)) {
            is Targets.Outcome.Tap -> Result.Narrow(listOf(out.target))
            is Targets.Outcome.Choose -> Result.Narrow(out.targets)
            Targets.Outcome.NotOnScreen -> if (concrete(PhraseGrammar.parse(text, PhraseGrammar.Context(cursor = true, window = true))))
                Result.RunNormally else Result.Hint("no match, say a number")
        }
    }

    private fun pickNumber(words: List<String>): Int? {
        for (i in words.indices) {
            val n = TargetMatcher.number(words[i]) ?: continue
            val rest = (words.subList(0, i) + words.subList(i + 1, words.size))
            if (rest.all { it in LEAD_FILLER }) return n
        }
        return null
    }

    private fun concrete(c: SpeechCommand): Boolean =
        c is SpeechCommand.Nav || c is SpeechCommand.Volume || c is SpeechCommand.OpenApp ||
            c is SpeechCommand.Swipe || c is SpeechCommand.Timer || c is SpeechCommand.AppMissing ||
            (c is SpeechCommand.Tap && (c.verb != null || c.fallback != null))
}
