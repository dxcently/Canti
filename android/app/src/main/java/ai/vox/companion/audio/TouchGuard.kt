package ai.vox.companion.audio

/**
 * Phone-mic safety: a finger on the glass is loud on the phone's own mic (a tap reads as a pop, two taps as a double
 * pop), so a sound that overlaps a touch is not the user's gesture. Pure logic, fed by [TouchWatch]; times are
 * elapsedRealtime ms.
 *
 * A sound [tStart, tEnd] is dropped when a touch-down lies in [tStart - [postMs], tEnd + [preMs]]: the tap's own
 * click comes at the down and the lift (typically 60-150 ms later), plus the capture clock's uncertainty.
 *
 * Touches Canti injected itself ([isInjected]: Executor.lastInjectedGestureMs / EndMs, or no input device) are
 * counted but do not guard, so an executed action does not swallow the next sound.
 */
class TouchGuard(val preMs: Long = 150, val postMs: Long = 400, private val keep: Int = 32) {
    data class Touch(val atMs: Long, val injected: Boolean)

    private val touches = ArrayDeque<Touch>()
    var userTouches = 0L; private set
    var injectedTouches = 0L; private set
    var dropped = 0L; private set

    fun onTouchDown(atMs: Long, injected: Boolean) {
        if (injected) injectedTouches++ else userTouches++
        touches.addLast(Touch(atMs, injected))
        while (touches.size > keep) touches.removeFirst()
    }

    /** The user touch that overlaps this sound, or null. Counts a drop when there is one. */
    fun overlapping(tStartMs: Long, tEndMs: Long): Touch? =
        touches.lastOrNull { !it.injected && it.atMs >= tStartMs - postMs && it.atMs <= tEndMs + preMs }
            ?.also { dropped++ }

    /** How long to wait after a sound's end before judging it (a touch-down may still arrive). */
    fun settleMs(tEndMs: Long, nowMs: Long): Long = (tEndMs + preMs - nowMs).coerceAtLeast(0)

    fun lastUserTouchMs(): Long? = touches.lastOrNull { !it.injected }?.atMs

    companion object {
        /**
         * Whether a touch-down is Canti's own: within Canti's last dispatched gesture ([injStartMs]..[injEndMs], uptime
         * clock like [eventUptimeMs]; 30 ms before / 50 ms after for dispatch slack), or from no input device
         * ([deviceId] < 0: dispatchGesture's events; a finger always has its touchscreen's id).
         *
         * NOT the MotionEvent flag FLAG_IS_ACCESSIBILITY_EVENT (0x800): on the Z Flip 6 (One UI, Android 14) every
         * ACTION_OUTSIDE delivered to an accessibility overlay carries it, the user's own finger included (field log
         * 20:29: device 7, the touchscreen, flags 0x800, no Canti gesture within 3 s). Trusting it made every user
         * touch "injected", and the guard never dropped anything.
         */
        fun isInjected(deviceId: Int, eventUptimeMs: Long, injStartMs: Long, injEndMs: Long): Boolean =
            deviceId < 0 || (injStartMs > 0 && eventUptimeMs >= injStartMs - 30 && eventUptimeMs <= injEndMs + 50)
    }
}
