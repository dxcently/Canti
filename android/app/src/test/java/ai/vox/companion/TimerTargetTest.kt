package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Which clock app gets a spoken timer; never the app chooser (TimerTarget.kt). */
class TimerTargetTest {
    private val google = TimerTarget.Handler("com.google.android.deskclock", "com.android.deskclock.HandleApiCalls", "Clock", system = false)
    private val samsung = TimerTarget.Handler("com.sec.android.app.clockpackage", "com.sec.android.app.clockpackage.TimerActivity", "Clock", system = true)
    private val other = TimerTarget.Handler("com.example.timer", "com.example.timer.Set", "Timer+", system = false)
    private val resolver = "android" to "com.android.internal.app.ResolverActivity"

    private fun use(p: TimerTarget.Pick) = (p as TimerTarget.Pick.Use)

    @Test fun oneHandlerIsUsed() = assertEquals(google, use(TimerTarget.pick(listOf(google), google.pkg, google.activity, "")).handler)

    @Test fun theSettingWins() {
        val p = use(TimerTarget.pick(listOf(google, samsung), samsung.pkg, samsung.activity, google.pkg))
        assertEquals(google, p.handler); assertEquals("timer_app setting", p.why)
    }

    @Test fun theDefaultIsUsedWhenThereIsOne() =
        assertEquals(other, use(TimerTarget.pick(listOf(samsung, other), other.pkg, other.activity, "")).handler)

    @Test fun theChooserIsNeverTakenForSuccess() {
        // several, no default: the one preinstalled clock
        assertEquals(samsung, use(TimerTarget.pick(listOf(google, samsung, other), resolver.first, resolver.second, "")).handler)
        // several, no default, no single system clock: refused, with a clear message
        val r = TimerTarget.pick(listOf(google, other), resolver.first, resolver.second, "")
        assertTrue(r is TimerTarget.Pick.Refuse)
        assertTrue((r as TimerTarget.Pick.Refuse).message, r.message.startsWith("choose a clock app for timers"))
        assertTrue(TimerTarget.isChooser("android", "com.android.internal.app.ResolverActivity"))
        assertTrue(TimerTarget.isChooser(null, null))
    }

    @Test fun noHandlerIsRefused() = assertTrue(TimerTarget.pick(emptyList(), null, null, "") is TimerTarget.Pick.Refuse)

    @Test fun aSettingForAMissingAppFallsBackToTheRules() =
        assertEquals(google, use(TimerTarget.pick(listOf(google), google.pkg, google.activity, "com.gone.clock")).handler)
}
