package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** The first-run pairing screen opens only for the Pico with no device remembered (Pairing.kt). */
class PairingTest {
    @Test fun needsSetupOnlyForThePicoWithNothingRemembered() {
        assertTrue(Pairing.needsSetup("pico", null))
        assertFalse(Pairing.needsSetup("pico", "D8:3A:DD:00:28:07"))
        assertFalse(Pairing.needsSetup("phone", null))
        assertFalse(Pairing.needsSetup("usb", null))
        assertEquals("pair", Pairing.ROUTE_PAIR)
    }
}

/** Screenshots stay at least the Android minimum apart (Confirmer.kt GrabGate). */
class GrabGateTest {
    private val grid = PixelGrid(2, 2, IntArray(4))

    @Test fun baselineIsNowThenSkippedThenReusesARecentTimeoutShot() {
        val g = GrabGate(1000)
        assertEquals(GrabGate.Plan.Now, g.baseline(10_000))
        g.took(10_000)
        // A second action 300 ms later: nothing recent to reuse, so no baseline (events only), no error-3 request.
        assertEquals(GrabGate.Plan.Skip, g.baseline(10_300))
        // The first watch's timeout screenshot at 11 500; the next action 400 ms later reuses it as its baseline.
        g.took(11_500); g.tookAfter(11_520, grid)
        assertEquals(GrabGate.Plan.Reuse(grid), g.baseline(11_900))
        // Once the interval has passed, a fresh one.
        assertEquals(GrabGate.Plan.Now, g.baseline(12_500))
        // A timeout shot older than the interval is not reused.
        g.took(13_000)
        assertEquals(GrabGate.Plan.Skip, g.baseline(13_100))
    }

    @Test fun timeoutShotWaitsOutTheInterval() {
        val g = GrabGate(1000)
        assertEquals(GrabGate.Plan.Now, g.after(0))
        g.took(5_000)
        assertEquals(GrabGate.Plan.Later(700), g.after(5_300))
        assertEquals(GrabGate.Plan.Now, g.after(6_000))
    }
}
