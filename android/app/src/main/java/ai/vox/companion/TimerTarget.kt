package ai.vox.companion

/**
 * Which clock app gets a spoken timer (pure; TimerTargetTest). ACTION_SET_TIMER sent loosely opens the system chooser
 * (ResolverActivity) when several clock apps handle it and none is the default: no timer is set, so reporting success
 * would be a lie. The intent is therefore resolved first and sent to one handler explicitly (with EXTRA_SKIP_UI):
 *  1. the `timer_app` setting, if that app handles timers;
 *  2. the only handler;
 *  3. the system default (resolveActivity answered with a real handler, not the chooser);
 *  4. the one preinstalled (system) clock among several;
 * else not-ok with "choose a clock app for timers" (set `timer_app`), and nothing is started.
 */
object TimerTarget {
    data class Handler(val pkg: String, val activity: String, val label: String, val system: Boolean)

    sealed class Pick {
        data class Use(val handler: Handler, val why: String) : Pick()
        data class Refuse(val message: String, val candidates: List<Handler>) : Pick()
    }

    /** The chooser Android answers with when a loose intent is ambiguous. */
    fun isChooser(pkg: String?, activity: String?): Boolean =
        pkg == null || pkg == "android" || activity?.endsWith("ResolverActivity") == true || activity?.endsWith("ChooserActivity") == true

    /**
     * [handlers]: queryIntentActivities for ACTION_SET_TIMER; [defaultPkg]/[defaultActivity]: what resolveActivity
     * answered (the chooser when ambiguous); [preferred]: the `timer_app` setting ("" = none).
     */
    fun pick(handlers: List<Handler>, defaultPkg: String?, defaultActivity: String?, preferred: String): Pick {
        val hs = handlers.distinctBy { it.pkg to it.activity }
        if (hs.isEmpty()) return Pick.Refuse("no clock app on this phone handles timers", hs)
        if (preferred.isNotBlank()) hs.firstOrNull { it.pkg == preferred.trim() }?.let { return Pick.Use(it, "timer_app setting") }
        if (hs.size == 1) return Pick.Use(hs[0], "only clock app")
        if (!isChooser(defaultPkg, defaultActivity)) {
            hs.firstOrNull { it.pkg == defaultPkg && (defaultActivity == null || it.activity == defaultActivity) }
                ?.let { return Pick.Use(it, "default clock app") }
            hs.firstOrNull { it.pkg == defaultPkg }?.let { return Pick.Use(it, "default clock app") }
        }
        val system = hs.filter { it.system }.distinctBy { it.pkg }
        if (system.size == 1) return Pick.Use(hs.first { it.pkg == system[0].pkg }, "system clock app")
        return Pick.Refuse("choose a clock app for timers (several: ${hs.distinctBy { it.pkg }.joinToString { it.label }}; set timer_app)", hs)
    }
}
