package ai.vox.companion

/** Everything a decider may look at. `scene.text()` is the exact model state. */
data class DecisionInput(
    val scene: Scene,
    val profile: Profile,
) {
    val mode get() = scene.mode
    /** Option table for this mode: key -> option text. */
    val options: Map<String, String> get() = if (scene.mode == "cursor") Vocab.CURSOR_ACTIONS else Vocab.ACTIONS
}

data class Decision(
    val action: String,          // key in ACTIONS or CURSOR_ACTIONS
    val source: String,          // rules:<why> | model | model-fallback:<why>
    val confidence: Double = 1.0,
    val latencyMs: Long = 0,
    val explicit: Boolean = false, // resolved by an explicit binding (fixed default, profile binding or phrase rule)
    val top: List<Pair<String, Double>> = emptyList(),   // model only: the 3 most probable option texts
    val serverMs: Double? = null,                         // model only: the server's own latency_ms
)

/** Decision interface. Implementations must be safe to call from a worker thread. */
interface Decider {
    val name: String
    fun decide(input: DecisionInput): Decision
}

/**
 * Deterministic local decider: the same policy generate.py computes ground truth with (POLICY in Vocab).
 * Used as the fallback for the model and, in tests, as the only decider.
 *
 * Screen context is read in exactly one place, the spoken-phrase tie-breaker (next/previous, play/pause), which is
 * what the training data does. It never changes an explicit gesture or rule.
 */
class RuleDecider : Decider {
    override val name = "rules"

    override fun decide(input: DecisionInput): Decision {
        val s = input.scene
        return when {
            s.phrase != null -> phrase(s, input.profile)
            s.mode == "cursor" -> cursor(s, input.profile)
            else -> gesture(s, input.profile)
        }
    }

    private fun gesture(s: Scene, p: Profile): Decision {
        notDeliberate(s)?.let { return Decision("none", "rules:not-deliberate:$it") }
        val seq = s.sequence
        p.appBindings(s.app).lastOrNull { it.phrase == seq }?.let { b ->
            return b.action?.let { Decision(it, "rules:app-binding", explicit = true) }
                ?: Decision("none", "rules:app-rule-needs-model")
        }
        p.globalBindings().lastOrNull { it.phrase == seq }?.let { b ->
            return b.action?.let { Decision(it, "rules:global-binding", explicit = true) }
                ?: Decision("none", "rules:global-rule-needs-model")
        }
        Vocab.DEFAULT_BINDINGS[seq]?.let { return Decision(it, "rules:default", explicit = true) }
        return Decision("none", "rules:unbound")
    }

    private fun cursor(s: Scene, p: Profile): Decision {
        notDeliberate(s)?.let { return Decision("none", "rules:not-deliberate:$it") }
        val seq = s.sequence
        p.cursorBindings().lastOrNull { it.phrase == seq }?.let { b ->
            return b.action?.let { Decision(it, "rules:cursor-binding", explicit = true) }
                ?: Decision("none", "rules:cursor-rule-needs-model")
        }
        if (seq.size != 1) return Decision("none", "rules:unbound")
        val loud = SoundLine(s.heard[0]).loudness == "loud"
        val dir = mapOf("rise" to "up", "fall" to "down", "arch" to "right", "dip" to "left")[seq[0]]
        val a = when {
            dir != null -> "move_${dir}_${if (loud) "fast" else "slow"}"
            seq[0] == "flat" -> "stop"
            seq[0] == "pop" -> "click"
            seq[0] == "hiss" -> "back"
            else -> return Decision("none", "rules:unbound")
        }
        return Decision(a, "rules:cursor-default", explicit = true)
    }

    private fun phrase(s: Scene, p: Profile): Decision {
        val said = s.phrase!!.lowercase().trim()
        p.phraseBindings().lastOrNull { it.say == said }?.let { b ->
            return b.action?.let { Decision(it, "rules:phrase-binding", explicit = true) }
                ?: Decision("none", "rules:phrase-rule-needs-model")
        }
        // generate.py labels PAUSE_WORDS / PLAY_WORDS as play_pause although some ("hold on", "stop the video",
        // "keep playing") are not in schema.PHRASES; mirror the generator.
        val base = Vocab.PHRASES.entries.firstOrNull { said in it.value }?.key
            ?: (if (said in Vocab.PAUSE_WORDS || said in Vocab.PLAY_WORDS) "play_pause" else null)
            ?: return Decision("none", "rules:unknown-phrase")
        return Decision(screenTieBreak(said, base, s.screen), "rules:phrase", explicit = true)
    }

    companion object {
        /** generate.py Generator.phrase_answer: resolve a screen-dependent phrase. */
        fun screenTieBreak(phrase: String, base: String, screen: ScreenContext?): String {
            if (screen == null) return base
            return when (base) {
                "next_item" -> Vocab.SCREEN_NEXT[screen.kind] ?: base
                "previous_item" -> Vocab.SCREEN_PREV[screen.kind] ?: base
                "play_pause" -> when {
                    phrase in Vocab.PAUSE_WORDS && screen.media == "paused" -> "none"
                    phrase in Vocab.PLAY_WORDS && screen.media == "playing" -> "none"
                    else -> base
                }
                else -> base
            }
        }

        private val NOT_GESTURE_SOURCES = setOf("talking", "laughing", "coughing", "background music", "background noise")

        /** Why the sequence is not a deliberate gesture (POLICY), or null if every sound passes. */
        fun notDeliberate(s: Scene): String? {
            if (s.sequence.isEmpty()) return "no-sound"
            if ("unknown" in s.sequence) return "unmatched-sound"
            s.heard.forEachIndexed { i, text ->
                val l = SoundLine(text)
                val label = s.sequence[i]
                if (l.soundsLike == Personal.IGNORE_SOUNDS_LIKE) return "my-ignore-sound"
                if (l.soundsLike in NOT_GESTURE_SOURCES) return "sounds-like-${l.soundsLike}"
                if (l.isHum) {
                    if (l.tone == "noisy") return "noisy"
                    if (l.duration == Vocab.DURATION[0]) return "too-short"
                    if (label != "flat" && l.pitchChange == Vocab.EXCURSION[0]) return "small-change"
                    if (label == "flat" && (l.duration == Vocab.DURATION[0] || l.duration == Vocab.DURATION[1])) return "short-flat"
                }
                if (l.isHiss && l.duration == Vocab.DURATION[3]) return "long-hiss"
            }
            return null
        }
    }
}
