package ai.vox.companion

import java.util.Locale
import kotlin.math.roundToInt

/**
 * Smart volume (pure Kotlin, no Android; PhraseGrammarTest, VolumeTest).
 *
 * [VolumeGrammar] turns a cleaned phrase ([PhraseGrammar.normalize]) into a [SpeechCommand.Volume]: which stream
 * ([VolStream], context-aware by default) and what to do ([VolOp]): a step up or down with an amount, an exact level,
 * mute, unmute. [VolumePlan] turns that plus the stream's current state into what the [Executor] sets. Everything acts
 * at once (volume is reversible: no confirm pop) and always shows the system volume bar.
 *
 * The decider path (rules, models) keeps the model vocabulary's `volume_up` / `volume_down` (one step, the auto
 * stream): the richer forms here are the grammar's own, like opening an app or setting a timer, so the trained
 * option lists and the vocabulary digest are unchanged.
 */
enum class VolStream(val key: String) {
    /** During a call (audio mode in-call / in-communication) the call volume, else media. */
    AUTO("auto"), MUSIC("music"), RING("ring"), ALARM("alarm"), NOTIFICATION("notification"), CALL("call");
}

sealed class VolOp {
    /**
     * [steps] up ([dir] +1) or down (-1). [exact]: that many volume indices ("a bit" = 1, "by 3"); else steps of
     * about 1/15 of the stream's range, so "louder" is 1 index on a 15-step stream and 2 on a 30-step one.
     * [fraction]: a share of the range instead ("up by 20 percent").
     */
    data class Step(val steps: Int, val dir: Int, val exact: Boolean = false, val fraction: Double? = null) : VolOp()
    /** An exact level: [fraction] of the maximum, or volume [index] (a number above the maximum, up to 100, is a percent). */
    data class Set(val fraction: Double? = null, val index: Int? = null) : VolOp()
    /** The lowest audible level (not mute). */
    object Lowest : VolOp() { override fun toString() = "Lowest" }
    object Mute : VolOp() { override fun toString() = "Mute" }
    object Unmute : VolOp() { override fun toString() = "Unmute" }

    fun describe(): String = when (this) {
        is Step -> (if (dir > 0) "up " else "down ") + when {
            fraction != null -> "${(fraction * 100).roundToInt()}%"
            exact -> "$steps"
            else -> "$steps step" + if (steps == 1) "" else "s"
        }
        is Set -> if (fraction != null) "to ${(fraction * 100).roundToInt()}%" else "to $index"
        Lowest -> "to lowest"
        Mute -> "mute"
        Unmute -> "unmute"
    }
}

object VolumeGrammar {
    /** Stream words; the match is replaced by "volume" before the operation is read ("turn the ringer up" -> "turn volume up"). */
    private val STREAMS: List<Pair<Regex, VolStream>> = listOf(
        "(?:ring|ringer|ringtone|ringing)(?: volume| sound)?" to VolStream.RING,
        "(?:alarm|alarms)(?: volume| sound)?" to VolStream.ALARM,
        "(?:notification|notifications)(?: volume| sound| sounds)?" to VolStream.NOTIFICATION,
        "(?:media|music|video|videos|song|songs)(?: volume| sound)?" to VolStream.MUSIC,
        "(?:in call|voice call|phone call|call)(?: volume)?" to VolStream.CALL,
    ).map { (re, s) -> Regex("(?:^| )(?:the |my )?(?:$re)(?= |$)") to s }

    private val THE_VOLUME = Regex("(^| )(?:the|my|your|this|that) (volume|sound|audio)(?= |$)")
    /** Amount words, taken out before the operation is read. */
    private val BIT = Regex("(?:^| )(?:just )?(?:a (?:little |tiny |teeny |wee )?(?:bit|touch|tad|notch|smidge|hair)|a little|slightly|one notch|a little bit)(?: more)?(?= |$)")
    private val LOT = Regex("(?:^| )(?:a (?:whole )?lot|a ton|loads|heaps|way|much|really|super|so much|far|significantly|a good bit)(?: more)?(?= |$)")
    private val STEP_UNITS = setOf("step", "steps", "notch", "notches", "click", "clicks", "level", "levels", "times", "bar", "bars")
    private val BY_N = Regex("(?:^| )by (\\S+(?: \\S+)?)(?: percent)?$")
    private val PERCENT_BY = Regex("(?:^| )by (\\S+(?: \\S+)?) percent$")

    private const val OBJ = "(?:it|this|that|volume|sound|audio|things|everything)"
    private val UP = listOf(
        "louder", "(?:make|get|turn|put) $OBJ louder", "volume (?:up|louder|higher)", "turn $OBJ up", "turn up(?: $OBJ)?",
        "(?:crank|pump|bump|blast|jack)(?: $OBJ)?(?: up)?", "(?:raise|increase|boost)(?: $OBJ)?", "up $OBJ", "more volume", "louder $OBJ",
        "(?:bring|push) $OBJ up", "(?:bring|push) up $OBJ", "higher volume",
    ).map { Regex("^(?:$it)(?: more)?$") }
    private val DOWN = listOf(
        "quieter", "softer", "(?:make|get|turn|put) $OBJ (?:quieter|softer|lower)", "volume (?:down|lower|quieter|softer)",
        "turn $OBJ down", "turn down(?: $OBJ)?", "(?:lower|decrease|reduce)(?: $OBJ)?", "(?:drop|cut) (?:volume|sound|audio)", "less volume", "tone $OBJ down",
        "tone down $OBJ", "keep $OBJ down", "(?:bring|push) $OBJ down", "(?:bring|push) down $OBJ", "quieter $OBJ", "softer $OBJ",
        "lower volume",
    ).map { Regex("^(?:$it)(?: more)?$") }
    /** Verbs that set the amount themselves: "crank it up" is a big step. */
    private val CRANK = setOf("crank", "blast", "jack")

    private val MUTE = listOf(
        "(?:mute|silence)(?: $OBJ)?(?: completely| entirely| for now)?", "sh+", "shush", "hush", "be quiet", "shut up", "no sound",
        "sound off", "volume off", "volume mute", "turn (?:the )?(?:sound|volume|audio) off", "turn off (?:the )?(?:sound|volume|audio)",
        "kill (?:the )?(?:sound|volume|audio)",
    ).map { Regex("^(?:$it)$") }
    private val UNMUTE = listOf(
        "un ?mute(?: $OBJ)?", "(?:turn |put |bring )?(?:the )?(?:sound|volume|audio) back(?: on| up)?", "(?:turn )?(?:the )?(?:sound|volume|audio) on",
        "turn on (?:the )?(?:sound|volume|audio)", "bring back (?:the )?(?:sound|volume|audio)", "(?:turn |put )?$OBJ back on",
    ).map { Regex("^(?:$it)$") }

    // "volume to 30 percent", "set it to half", "half volume", "max volume", "turn it all the way up".
    private val SET_TO = Regex("^(?:(?:set|put|turn|change|bring|crank|pump|lower|raise) )?(?:$OBJ )?(?:up |down )?(?:to|at) (.+)$")
    private val VOLUME_N = Regex("^volume (?:level )?(.+)$")
    private val N_VOLUME = Regex("^(.+) volume$")
    private val ALL_THE_WAY = Regex("^(?:(?:turn|crank|put|bring|pump|push|jack) )?(?:$OBJ )?all the way (up|down)$")
    private val ALL_THE_WAY_2 = Regex("^(?:turn|crank|put|bring|pump|push) (up|down) (?:$OBJ )?all the way$")
    private val MAX_IT = Regex("^(?:max|max out|max it out|max it|maximum|full blast|full volume)(?: $OBJ)?$")

    // Indirect: a complaint about the level ("it's too loud", "i can't hear it", "that hurts my ears").
    private val TOO = Regex("^(?:(?:its|it is|its getting|it got|its still|thats|that is|thats getting|this is|this is getting|volume is|volume s|volumes|youre|you are|everything is|everythings|sound is|audio is|that volume is|this volume is|the volume is|it sounds|this sounds|that sounds) )?(?:(way|much|far|really|a bit|a little|a little bit|slightly|kind of|just|still|a tad|super|definitely|kinda) )*too (loud|quiet|soft|low|high|noisy|faint)(?: now| right now)?$")
    private val CANT_HEAR = Regex("^i (cant|can not|cannot|can barely|could not|couldnt|barely|cant really|can hardly|hardly) hear(?: (?:it|this|that|anything|a thing|you|volume|the sound|the audio|anyone|them|him|her))?(?: at all| anymore)?$")
    private val EARS = Regex("^(?:(?:its|it is|thats|that is|this is|it|that|this|volume is) )?(?:hurting my ears|hurts my ears|killing my ears|deafening|blasting my ears|ear ?splitting|my ears hurt|my ears are bleeding)$")

    /** The volume command in [t] (a cleaned phrase), or null. [repeat]: the phrase said that many times ("louder louder"). */
    fun parse(t0: String, repeat: Int = 1): SpeechCommand.Volume? {
        if (t0.isEmpty()) return null
        // the stream, if one is named (at most one)
        var stream = VolStream.AUTO
        var t = " $t0 "
        val named = STREAMS.filter { it.first.containsMatchIn(t0) }
        if (named.size > 1) return null
        var explicit = true   // the stream named with "volume"/"sound" ("alarm volume"), or none named
        named.firstOrNull()?.let { (re, s) ->
            stream = s; explicit = re.find(t0)!!.value.let { it.endsWith(" volume") || it.endsWith(" sound") || it.endsWith(" sounds") }
            t = " " + re.replace(t0, " volume") + " "
        }
        t = t.replace(Regex("\\s+"), " ").trim().replace("volume volume", "volume")
        t = t.replace(THE_VOLUME, "$1$2")   // "turn the volume down" = "turn volume down"

        indirect(t)?.let { return SpeechCommand.Volume(stream, it) }
        // "set the alarm to 7", "silence the alarm": an alarm, not its volume; for the alarm, levels and mutes need "volume"
        val loose = !explicit && stream == VolStream.ALARM
        if (MUTE.any { it.matches(t) }) return if (loose) null else SpeechCommand.Volume(stream, VolOp.Mute)
        if (UNMUTE.any { it.matches(t) }) return if (loose) null else SpeechCommand.Volume(stream, VolOp.Unmute)
        exact(t)?.let { return if (loose) null else SpeechCommand.Volume(stream, it) }
        step(t, repeat)?.let { return SpeechCommand.Volume(stream, it) }
        return null
    }

    private fun indirect(t: String): VolOp? {
        TOO.find(t)?.let { m ->
            val dir = if (m.groupValues[2] in setOf("loud", "high", "noisy")) -1 else 1
            val words = m.value.split(' ')
            val big = words.any { it in setOf("way", "much", "far", "really", "super", "definitely") }
            val small = listOf("a bit", "a little", "slightly", "kind of", "kinda", "a tad").any { m.value.contains(it) }
            return when {
                big -> VolOp.Step(3, dir)
                small -> VolOp.Step(1, dir, exact = true)
                else -> VolOp.Step(1, dir)
            }
        }
        CANT_HEAR.find(t)?.let { m ->
            val lot = m.value.endsWith(" at all") || m.value.contains(" anything") || m.value.contains(" a thing")
            return VolOp.Step(if (lot) 3 else 1, 1)
        }
        if (EARS.matches(t)) return VolOp.Step(3, -1)
        return null
    }

    private fun exact(t: String): VolOp? {
        ALL_THE_WAY.find(t)?.let { return if (it.groupValues[1] == "up") VolOp.Set(fraction = 1.0) else VolOp.Lowest }
        ALL_THE_WAY_2.find(t)?.let { return if (it.groupValues[1] == "up") VolOp.Set(fraction = 1.0) else VolOp.Lowest }
        if (MAX_IT.matches(t)) return VolOp.Set(fraction = 1.0)
        SET_TO.find(t)?.let { m -> level(m.groupValues[1])?.let { return it } }
        VOLUME_N.find(t)?.let { m -> level(m.groupValues[1])?.let { return it } }
        N_VOLUME.find(t)?.let { m -> level(m.groupValues[1], named = true)?.let { return it } }
        return null
    }

    /** A level: "max", "half", "30 percent", "a quarter", "five", "7 out of 10". [named]: before "volume" ("half volume"). */
    fun level(s0: String, named: Boolean = false): VolOp? {
        val s = s0.removePrefix("the ").removeSuffix(" please").trim()
        when (s) {
            "max", "maximum", "full", "top", "highest", "the highest", "loudest", "the loudest", "all the way", "all the way up", "full blast",
            "one hundred percent", "hundred percent" -> return VolOp.Set(fraction = 1.0)
            "half", "halfway", "half way", "middle", "medium", "the middle", "mid", "half of max", "half of the max" -> return VolOp.Set(fraction = 0.5)
            "min", "minimum", "lowest", "the lowest", "quietest", "the quietest", "all the way down", "low" -> return VolOp.Lowest
            "a quarter", "quarter", "one quarter" -> return VolOp.Set(fraction = 0.25)
            "three quarters", "three quarter" -> return VolOp.Set(fraction = 0.75)
            "a third", "one third" -> return VolOp.Set(fraction = 1.0 / 3)
            "two thirds" -> return VolOp.Set(fraction = 2.0 / 3)
            "zero", "0", "nothing", "off", "none", "mute", "silent" -> return if (named) null else VolOp.Mute
        }
        val w = s.split(' ')
        val n = NumberWords.at(w, 0) ?: return null
        val rest = w.drop(n.second)
        val v = n.first
        return when {
            rest.isEmpty() -> if (v == 0.0) VolOp.Mute else VolOp.Set(index = v.roundToInt())
            rest == listOf("percent") || rest == listOf("per", "cent") || rest == listOf("percent", "volume") -> VolOp.Set(fraction = (v / 100).coerceIn(0.0, 1.0))
            rest.size >= 2 && rest[0] == "out" && rest[1] == "of" -> {
                val d = NumberWords.at(rest, 2)?.takeIf { it.second == rest.size - 2 && it.first > 0 } ?: return null
                VolOp.Set(fraction = (v / d.first).coerceIn(0.0, 1.0))
            }
            else -> null
        }
    }

    private fun step(t0: String, repeat: Int): VolOp? {
        var t = " $t0 "
        var steps: Int? = null; var exact = false; var fraction: Double? = null
        PERCENT_BY.find(t.trim())?.let { m ->
            NumberWords.at(m.groupValues[1].split(' '), 0)?.takeIf { it.second == m.groupValues[1].split(' ').size }?.let {
                fraction = (it.first / 100).coerceIn(0.0, 1.0)
                t = " " + t.trim().removeSuffix(m.value).trim() + " "
            }
        }
        if (fraction == null) {
            val w = t.trim().split(' ')
            val ui = w.indexOfFirst { it in STEP_UNITS }
            if (ui > 0) for (k in 2 downTo 1) {
                if (ui - k < 0) continue
                val r = NumberWords.at(w, ui - k)
                if (r == null || r.second != k) continue
                steps = r.first.roundToInt().coerceIn(1, 100); exact = true
                val from = if (ui - k > 0 && w[ui - k - 1] == "by") ui - k - 1 else ui - k
                t = " " + (w.subList(0, from) + w.subList(ui + 1, w.size)).joinToString(" ") + " "
                break
            }
        }
        if (fraction == null && steps == null) BY_N.find(t.trim())?.let { m ->
            NumberWords.at(m.groupValues[1].split(' '), 0)?.takeIf { it.second == m.groupValues[1].split(' ').size }?.let {
                steps = it.first.roundToInt().coerceIn(1, 100); exact = true; t = " " + t.trim().removeSuffix(m.value).trim() + " "
            }
        }
        var amount = 1; var bit = false
        if (steps == null && fraction == null) {
            if (BIT.containsMatchIn(t)) { bit = true; t = BIT.replace(t, " ") }
            else if (LOT.containsMatchIn(t)) { amount = 3; t = LOT.replace(t, " ") }
        }
        // "volume up 3", "turn it down two"
        var core = t.replace(Regex("\\s+"), " ").trim()
        if (steps == null && fraction == null) {
            val w = core.split(' ')
            val num = (1 until w.size).firstOrNull { i -> NumberWords.at(w, i)?.let { it.second == w.size - i } == true }
            if (num != null && w[num - 1] in setOf("up", "down")) {
                steps = NumberWords.at(w, num)!!.first.roundToInt().coerceIn(1, 100); exact = true
                core = w.subList(0, num).joinToString(" ")
            }
        }
        val dir = when {
            UP.any { it.matches(core) } -> 1
            DOWN.any { it.matches(core) } -> -1
            else -> return null
        }
        if (fraction != null) return VolOp.Step(0, dir, fraction = fraction)
        steps?.let { return VolOp.Step(it, dir, exact = true) }
        if (bit) return VolOp.Step(1, dir, exact = true)
        if (dir > 0 && core.split(' ').first() in CRANK && amount < 4) amount = 4
        return VolOp.Step(if (amount == 1) repeat.coerceIn(1, 5) else amount, dir)
    }
}

/**
 * What to set for a [VolOp] on a stream in the state [level]: pure arithmetic, the [Executor] applies it.
 * Mute remembers the level it silenced (per stream); unmute and a step up from mute come back to it.
 */
object VolumePlan {
    /** A stream's state: its index now, its min and max, whether it is muted. */
    data class Level(val index: Int, val min: Int, val max: Int, val muted: Boolean = false)

    /**
     * [unmute]: undo a mute first; [mute]: mute (ADJUST_MUTE; [setIndex] is then the fallback where a stream cannot be
     * muted, e.g. the call volume); [setIndex]: the index to set (null: leave it); [remember]: the level to restore
     * after this mute; [note]: why nothing changed ("already at max").
     */
    data class Plan(val setIndex: Int? = null, val mute: Boolean = false, val unmute: Boolean = false, val remember: Int? = null,
                    val note: String? = null) {
        fun describe(): String = listOfNotNull(if (mute) "mute" else null, if (unmute) "unmute" else null, setIndex?.let { "set $it" },
            remember?.let { "remember $it" }, note).joinToString(", ")
    }

    /** The stream for [s] given whether a call is on (audio mode in-call or in-communication). */
    fun stream(s: VolStream, inCall: Boolean): VolStream = if (s == VolStream.AUTO) (if (inCall) VolStream.CALL else VolStream.MUSIC) else s

    /** Indices per "step": about 1/15 of the range (1 on a 15-step stream, 2 on a 30-step one). */
    fun unit(l: Level): Int = maxOf(1, ((l.max - l.min) / 15.0).roundToInt())

    /** The lowest audible index. */
    fun lowest(l: Level): Int = maxOf(l.min, 1).coerceAtMost(l.max)

    /** Where an unmute comes back to with nothing remembered: 30 % of the range, at least audible. */
    fun fallback(l: Level): Int = maxOf(lowest(l), (l.max * 0.3).roundToInt())

    fun plan(op: VolOp, l: Level, remembered: Int?, canMute: Boolean = true): Plan {
        val clamp = { i: Int -> i.coerceIn(l.min, l.max) }
        return when (op) {
            is VolOp.Step -> {
                val delta = when {
                    op.fraction != null -> maxOf(1, (op.fraction * (l.max - l.min)).roundToInt())
                    op.exact -> op.steps
                    else -> op.steps * unit(l)
                }
                if (l.muted) {
                    if (op.dir < 0) Plan(note = "muted") else {
                        // like the volume keys: up from mute unmutes, from the level that was muted
                        val base = remembered?.let(clamp) ?: l.min
                        Plan(setIndex = clamp(base + delta), unmute = true)
                    }
                } else {
                    val to = clamp(l.index + op.dir * delta)
                    if (to == l.index) Plan(note = if (op.dir > 0) "already at max" else "already at min") else Plan(setIndex = to)
                }
            }
            is VolOp.Set -> {
                val to = when {
                    op.fraction != null -> clamp((op.fraction * l.max).roundToInt())
                    op.index != null && op.index <= l.max -> clamp(op.index)
                    op.index != null && op.index <= 100 -> clamp((op.index / 100.0 * l.max).roundToInt())   // "volume 30" on a 15-step stream
                    else -> l.max
                }
                if (l.muted) Plan(setIndex = to, unmute = to > l.min)
                else if (to == l.index) Plan(note = "already there") else Plan(setIndex = to)
            }
            VolOp.Lowest -> {
                val to = lowest(l)
                if (l.muted) Plan(setIndex = to, unmute = true) else if (to == l.index) Plan(note = "already at lowest") else Plan(setIndex = to)
            }
            VolOp.Mute -> when {
                l.muted -> Plan(note = "already muted")
                l.index <= l.min && !canMute -> Plan(note = "already at min")
                canMute -> Plan(mute = true, remember = l.index.takeIf { it > l.min })
                else -> Plan(setIndex = l.min, remember = l.index.takeIf { it > l.min })
            }
            VolOp.Unmute -> when {
                l.muted -> Plan(unmute = true, setIndex = remembered?.let(clamp)?.takeIf { it > l.min })
                l.index <= l.min -> Plan(setIndex = remembered?.let(clamp)?.takeIf { it > l.min } ?: fallback(l))
                else -> Plan(note = "not muted")
            }
        }
    }

    fun percent(index: Int, l: Level): String = String.format(Locale.ROOT, "%d%%", if (l.max <= 0) 0 else (index * 100.0 / l.max).roundToInt())
}
