package ai.vox.companion.rec

import ai.vox.companion.BuildConfig

/**
 * The dev gate for everything in this package (the in-app test recorder + quick record). All recorder code reads
 * [enabled] and does nothing when it is false: no tap, no ring, no EventLog listener, no ops, no menu row, and the
 * `ai.vox/recorder` channel answers `{enabled:false}`. Set by `DEV_RECORDER` (debug only; see app/build.gradle.kts).
 *
 * [overrideForTests] lets JVM tests flip the gate without a BuildConfig (BuildConfig.DEV_RECORDER is false in the
 * unit-test classpath); it is internal and only ever touched by tests.
 */
object DevRec {
    val enabled: Boolean get() = override ?: BuildConfig.DEV_RECORDER

    @Volatile private var override: Boolean? = null

    internal fun overrideForTests(v: Boolean?) { override = v }
}
