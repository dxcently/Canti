package ai.vox.companion

/** Screen context, one value from each schema list. Sent to the model as a tie-breaker only. */
data class ScreenContext(val kind: String, val media: String, val scroll: String, val keyboard: String) {
    init {
        require(kind in Vocab.SCREEN_KIND) { "bad screen kind $kind" }
        require(media in Vocab.SCREEN_MEDIA) { "bad media $media" }
        require(scroll in Vocab.SCREEN_SCROLL) { "bad scroll $scroll" }
        require(keyboard in Vocab.SCREEN_KEYBOARD) { "bad keyboard $keyboard" }
    }
    fun text() = Vocab.screenText(kind, media, scroll, keyboard)
}

/**
 * The decision state. text() reproduces finetune/vox/generate.py Scene.text() byte for byte (checked by
 * StateParityTest against fixtures produced by tools/state_parity.py).
 */
data class Scene(
    val mode: String = "gesture",
    val app: String,                 // package name
    val appName: String,             // display name (schema APPS name when known, else the launcher label)
    val heard: List<String> = emptyList(),
    val sequence: List<String> = emptyList(),
    val rules: List<String> = emptyList(),
    val phrase: String? = null,
    val recent: List<String> = emptyList(),   // option texts of recent actions
    val cursor: String? = null,
    val screen: ScreenContext? = null,
) {
    fun text(): String {
        val lines = mutableListOf("mode: $mode", "app: $appName ($app)")
        screen?.let { lines += it.text() }
        cursor?.let { if (it.isNotEmpty()) lines += "cursor: $it" }
        phrase?.let { lines += "spoken phrase: \"$it\"" }
        heard.forEachIndexed { i, h -> lines += "sound ${i + 1}: $h" }
        if (sequence.isNotEmpty()) lines += "sequence: " + sequence.joinToString(" then ")
        lines += Vocab.DEFAULTS_TEXT
        lines += "my rules:" + if (rules.isEmpty()) " none" else rules.joinToString("") { "\n- $it" }
        if (recent.isNotEmpty()) lines += "recent actions: " + recent.joinToString(", ")
        return lines.joinToString("\n")
    }
}

object StateBuilder {
    fun appName(pkg: String, label: String?): String = Vocab.APPS[pkg] ?: label ?: pkg

    fun build(
        mode: String,
        pkg: String,
        appLabel: String?,
        heard: List<String>,
        sequence: List<String>,
        phrase: String?,
        profile: Profile,
        recentActions: List<String>,
        cursor: String?,
        screen: ScreenContext?,
    ): Scene {
        val name = appName(pkg, appLabel)
        val table = if (mode == "cursor") Vocab.CURSOR_ACTIONS else Vocab.ACTIONS
        return Scene(
            mode = mode,
            app = pkg,
            appName = name,
            heard = heard,
            sequence = sequence,
            rules = profile.ruleTexts(pkg, name, mode),
            phrase = phrase,
            recent = recentActions.mapNotNull { Vocab.ACTIONS[it] ?: table[it] },
            cursor = if (mode == "cursor") cursor else null,
            screen = screen,
        )
    }
}
