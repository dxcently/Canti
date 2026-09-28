package ai.vox.companion

import ai.vox.companion.MediaGate.Verdict
import ai.vox.companion.audio.SpeakerRoute
import android.bluetooth.BluetoothClass
import android.media.AudioDeviceInfo
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The phone-mic media lock (user decision 2026-09-27): while media plays, phone / USB mic sounds are dropped except a
 * `pop pop` unlock, which opens a `media_unlock_ms` window of normal rules; the Pico is never gated.
 */
class MediaGateTest {
    private var on = true
    private var unlockMs = 5000L
    private var mode = MediaGate.ONE
    private val gate = MediaGate({ on }, { unlockMs }, { 600L }, { mode })

    /** A sound [durMs] long ending at [end] (stamps and "now" on the same clock, as for the phone mic). */
    private fun sound(label: String, end: Long, playing: Boolean = true, durMs: Long = 60) =
        gate.onSound(label, end - durMs, end, end, playing)

    /** The unlock: two pops 250 ms apart, the second ending at [end]. */
    private fun unlock(end: Long): Verdict {
        assertEquals(Verdict.FIRST_POP, sound("pop", end - 310))
        return sound("pop", end)
    }

    @Test fun mediaOffPassesEverything() {
        for (l in listOf("pop", "hiss", "click", "rise", "flat")) assertEquals(Verdict.PASS, sound(l, 1000, playing = false))
        assertFalse(gate.active(false))
    }

    @Test fun mediaOnDropsEverySound() {
        for ((i, l) in listOf("hiss", "click", "click", "rise", "fall", "flat", "arch", "dip", "unknown").withIndex())
            assertEquals(l, Verdict.DROP, sound(l, 1000L + i * 300))
        assertTrue(gate.active(true))
    }

    @Test fun popPopUnlocksAndTheUnlockItselfIsDropped() {
        assertEquals(Verdict.UNLOCK, unlock(10_000))
        assertTrue(gate.isOpen(10_000))
        // the window: sounds pass to the normal rules
        assertEquals(Verdict.PASS, sound("hiss", 11_000))
        assertEquals(Verdict.PASS, sound("pop", 12_000))
    }

    @Test fun onlyTwoPopsWithinTheGapAndNothingBetween() {
        // too far apart: the second pop is a new first pop
        assertEquals(Verdict.FIRST_POP, sound("pop", 1000))
        assertEquals(Verdict.FIRST_POP, gate.onSound("pop", 1000 + 601, 1000 + 660, 1660, true))
        // ... which a pop within the gap completes
        assertEquals(Verdict.UNLOCK, gate.onSound("pop", 1660 + 600, 1660 + 650, 2310, true))
        // a media sound between the pops breaks it
        val g = MediaGate({ true }, { 5000L }, { 600L })
        assertEquals(Verdict.FIRST_POP, g.onSound("pop", 0, 50, 50, true))
        assertEquals(Verdict.DROP, g.onSound("click", 100, 110, 110, true))
        assertEquals(Verdict.FIRST_POP, g.onSound("pop", 200, 250, 250, true))
        // click click / pop click / hiss hiss never unlock
        val h = MediaGate({ true }, { 5000L }, { 600L })
        for (pair in listOf(listOf("click", "click"), listOf("pop", "click"), listOf("click", "pop"), listOf("hiss", "hiss"))) {
            var t = 10_000L
            val v = pair.map { t += 300; h.onSound(it, t - 50, t, t, true) }
            assertFalse("$pair", Verdict.UNLOCK in v)
            h.onSound("hiss", t + 1000, t + 1100, t + 1100, true)   // reset between cases
        }
        // a pop the 14 dB rule turned into "unknown" is not a pop
        val u = MediaGate({ true }, { 5000L }, { 600L })
        assertEquals(Verdict.DROP, u.onSound("unknown", 0, 50, 50, true))
        assertEquals(Verdict.FIRST_POP, u.onSound("pop", 200, 250, 250, true))
    }

    @Test fun oneModeLetsExactlyTheNextGestureThrough() {
        assertEquals(MediaGate.ONE, mode)
        assertEquals(Verdict.UNLOCK, unlock(10_000))
        assertEquals(15_000, gate.openUntilMs)
        assertEquals(Verdict.PASS, sound("hiss", 11_000))
        assertEquals(MediaGate.Resolution.CLOSED, gate.resolved(listOf("hiss"), 11_700, playing = true))
        assertFalse(gate.isOpen(11_700))
        assertEquals("re-locked", Verdict.DROP, sound("rise", 12_000))
        assertEquals("nothing open to close", MediaGate.Resolution.NONE, gate.resolved(listOf("rise"), 12_700, true))
        // media_unlock_ms is the time allowed to make the gesture
        assertEquals(Verdict.UNLOCK, unlock(20_000))
        assertEquals(Verdict.DROP, sound("hiss", 25_100))
        assertEquals(MediaGate.Resolution.NONE, gate.resolved(listOf("hiss"), 25_200, true))
    }

    @Test fun fixedModeIsAWindowThatNeverExtends() {
        mode = MediaGate.FIXED
        assertEquals(Verdict.UNLOCK, unlock(10_000))
        for ((i, seq) in listOf(listOf("hiss"), listOf("rise"), listOf("pop", "pop")).withIndex()) {
            assertEquals(Verdict.PASS, sound(seq[0], 11_000L + i * 1000))
            assertEquals(MediaGate.Resolution.NONE, gate.resolved(seq, 11_700L + i * 1000, true))
        }
        assertEquals(15_000, gate.openUntilMs)
        assertEquals(Verdict.PASS, sound("fall", 14_900))
        assertEquals(Verdict.DROP, sound("fall", 15_100))
        // media_unlock_ms is read on each unlock
        unlockMs = 2000
        assertEquals(Verdict.UNLOCK, unlock(20_000))
        assertEquals(22_000, gate.openUntilMs)
    }

    @Test fun popextModeOnlyPopPopExtends() {
        mode = MediaGate.POPEXT
        assertEquals(Verdict.UNLOCK, unlock(10_000))
        assertEquals(MediaGate.Resolution.NONE, gate.resolved(listOf("hiss"), 11_000, true))
        assertEquals(MediaGate.Resolution.NONE, gate.resolved(listOf("click", "click"), 12_000, true))
        assertEquals(15_000, gate.openUntilMs)
        assertEquals(MediaGate.Resolution.EXTENDED, gate.resolved(listOf("pop", "pop"), 14_000, true))
        assertEquals(19_000, gate.openUntilMs)
        assertEquals(Verdict.PASS, sound("rise", 18_900))
        assertEquals(Verdict.DROP, sound("rise", 19_100))
        assertEquals("expired: nothing to extend", MediaGate.Resolution.NONE, gate.resolved(listOf("pop", "pop"), 19_200, true))
        assertEquals("media off: nothing to extend", MediaGate.Resolution.NONE, gate.resolved(listOf("pop", "pop"), 19_300, false))
    }

    @Test fun mediaStoppingLiftsTheGateAtOnce() {
        assertEquals(Verdict.UNLOCK, unlock(10_000))
        assertFalse("still playing", gate.mediaChanged(10_500, playing = true))
        assertTrue(gate.mediaChanged(11_000, playing = false))
        assertFalse(gate.isOpen(11_000))
        assertEquals(Verdict.PASS, sound("hiss", 11_500, playing = false))
        // media again: locked again, the old window is gone
        assertEquals(Verdict.DROP, sound("hiss", 12_000))
        // a half unlock does not survive a stop either
        assertEquals(Verdict.FIRST_POP, sound("pop", 13_000))
        gate.mediaChanged(13_100, playing = false)
        assertEquals(Verdict.FIRST_POP, sound("pop", 13_300))
    }

    @Test fun theSettingTurnsItOff() {
        on = false
        assertFalse(gate.active(true))
        assertEquals(Verdict.PASS, sound("hiss", 1000))
        assertEquals(Verdict.PASS, sound("pop", 1300))
        on = true
        assertEquals(Verdict.DROP, sound("hiss", 2000))
    }

    @Test fun picoIsNeverGatedAndUsbIs() {
        // the phone and a USB mic both deliver through the phone-mic source (SourcePolicy routes USB there)
        assertTrue(MediaGate.appliesTo(ai.vox.companion.audio.PhoneMicSource.NAME))
        assertTrue(MediaGate.appliesTo("phone-mic-feed"))
        for (s in listOf("ble", BleFeatureSource.CONNECT_SOURCE, BleFeatureSource.DISCONNECT_SOURCE, "debug-socket"))
            assertFalse(s, MediaGate.appliesTo(s))
    }

    // --- the pop-pop conflict: unlock vs listen-for-phrase ------------------------------------------------------------

    private class FakeScheduler : Scheduler {
        var t = 0L
        val tasks = mutableListOf<Pair<Long, () -> Unit>>()
        override fun now() = t
        override fun schedule(delayMs: Long, task: () -> Unit): () -> Unit {
            val e = (t + delayMs) to task; tasks += e; return { tasks.remove(e) }
        }
        fun advance(ms: Long) { t += ms; tasks.filter { it.first <= t }.forEach { tasks.remove(it); it.second() } }
    }

    /** The service's order for a phone-mic sound: the gate first (VoxService.features), then the sequencer and the rules. */
    private class Pipeline(mode: String = "gesture", unlockMode: String = MediaGate.ONE) {
        val s = FakeScheduler()
        val gate = MediaGate({ true }, { 5000L }, { 600L }, { unlockMode })
        var playing = true
        val actions = mutableListOf<String>()
        val profile = Profile.empty()
        private val m = mode
        val q = Sequencer(s, { 600L }, onResolve = { p ->
            val seq = p.sequence.toList()
            // VoxService.resolve: the unlock mode sees the gesture first; popext consumes a pop pop
            if (gate.resolved(seq, s.t, playing) == MediaGate.Resolution.EXTENDED) { actions += "extended"; return@Sequencer }
            actions += if (m == "cursor" && seq == Profile.CURSOR_LISTEN) "listen_for_phrase"
                       else Vocab.DEFAULT_BINDINGS[seq] ?: "none"
        })
        fun sound(label: String, playing: Boolean = true) {
            this.playing = playing
            val end = s.t
            if (gate.onSound(label, end - 60, end, end, playing) != MediaGate.Verdict.PASS) return
            q.add(m, "com.google.android.youtube", listOf(label), listOf(label), profile.boundSequences("com.google.android.youtube", m),
                listOf(Stamp(end - 60, end)))
        }
    }

    @Test fun popPopWhileMediaPlaysUnlocksButDoesNotListen() {
        val p = Pipeline()
        p.s.advance(1000); p.sound("pop"); p.s.advance(300); p.sound("pop")
        p.s.advance(2000)
        assertEquals("the unlock reaches nothing", emptyList<String>(), p.actions)
        assertTrue(p.gate.isOpen(p.s.t))
        // a second pop pop inside the window listens
        p.sound("pop"); p.s.advance(300); p.sound("pop"); p.s.advance(1000)
        assertEquals(listOf("listen_for_phrase"), p.actions)
        // one: that was the gesture; locked again
        assertFalse(p.gate.isOpen(p.s.t))
        p.sound("hiss"); p.s.advance(1000)
        assertEquals(listOf("listen_for_phrase"), p.actions)
    }

    @Test fun oneModeTheNextGestureActsThenMediaSoundsAreDroppedAgain() {
        val p = Pipeline()
        p.s.advance(1000); p.sound("pop"); p.s.advance(300); p.sound("pop"); p.s.advance(1000)
        p.sound("hiss"); p.s.advance(1000)          // the video's hiss, or the user's: the one gesture
        p.sound("click"); p.s.advance(200); p.sound("click"); p.s.advance(1000)
        assertEquals(listOf("back"), p.actions)
    }

    @Test fun popextPopPopInsideTheWindowExtendsAndDoesNotListen() {
        val p = Pipeline(unlockMode = MediaGate.POPEXT)
        p.s.advance(1000); p.sound("pop"); p.s.advance(300); p.sound("pop")   // unlock at 1300: open until 6300
        p.s.advance(3000); p.sound("pop"); p.s.advance(300); p.sound("pop"); p.s.advance(1000)
        assertEquals(listOf("extended"), p.actions)
        assertTrue("extended past 6300", p.gate.isOpen(7000))
        p.sound("hiss"); p.s.advance(1000)
        assertEquals(listOf("extended", "back"), p.actions)
        assertTrue("other gestures do not extend", p.gate.openUntilMs < p.s.t + 5000)
    }

    @Test fun popPopWithoutMediaListensAsBefore() {
        val p = Pipeline()
        p.s.advance(1000); p.sound("pop", playing = false); p.s.advance(300); p.sound("pop", playing = false); p.s.advance(1000)
        assertEquals(listOf("listen_for_phrase"), p.actions)
    }

    @Test fun cursorModeHasTheSameGate() {
        val p = Pipeline("cursor")
        p.s.advance(1000); p.sound("rise"); p.s.advance(1000)
        p.sound("pop"); p.s.advance(300); p.sound("pop"); p.s.advance(1000)
        assertEquals(emptyList<String>(), p.actions)
        p.sound("pop"); p.s.advance(300); p.sound("pop"); p.s.advance(1000)
        assertEquals(listOf("listen_for_phrase"), p.actions)
    }

    @Test fun mediaUnlockedShowsThePendingFace() {
        val i = BadgeStates.Inputs(armed = true, paused = false, mode = "gesture", holdScrolling = false, pending = false,
            listening = false, sourceError = false)
        assertEquals(BadgeState.IDLE, BadgeStates.held(i))
        assertEquals(BadgeState.PENDING, BadgeStates.held(i.copy(mediaUnlocked = true)))
        assertEquals(BadgeState.PENDING, BadgeStates.held(i.copy(mode = "cursor", mediaUnlocked = true)))
        assertEquals("the phrase window wins", BadgeState.HEARING, BadgeStates.held(i.copy(listening = true, mediaUnlocked = true)))
    }

    // --- the speaker test (SpeakerRoute.kt): the lock only applies when media plays on a speaker the mic hears -------

    @Test fun speakerRouteIsAudibleOnlyOnASpeaker() {
        // the phone's own speaker and a Bluetooth (LE) speaker play into the room: the mic hears them
        assertTrue(SpeakerRoute.speakerMedia(setOf(AudioDeviceInfo.TYPE_BUILTIN_SPEAKER)))
        assertTrue(SpeakerRoute.speakerMedia(setOf(AudioDeviceInfo.TYPE_BLE_SPEAKER)))
        // headphones / earbuds / a hearing aid: the phone mic hears nothing, so no lock
        // (A2DP is resolved by its device class, not its type alone — see a2dpDeviceClassDecidesSpeakerVsHeadphones)
        for (t in listOf(AudioDeviceInfo.TYPE_WIRED_HEADSET, AudioDeviceInfo.TYPE_WIRED_HEADPHONES,
            AudioDeviceInfo.TYPE_BLE_HEADSET, AudioDeviceInfo.TYPE_USB_HEADSET, AudioDeviceInfo.TYPE_HEARING_AID))
            assertFalse("type $t", SpeakerRoute.speakerMedia(setOf(t)))
        // a speaker among other outputs still counts (media is partly on the speaker)
        assertTrue(SpeakerRoute.speakerMedia(setOf(AudioDeviceInfo.TYPE_BUILTIN_SPEAKER, AudioDeviceInfo.TYPE_BLE_HEADSET)))
        // an unknown route (pre-Android-13, or an error) is assumed audible: fail safe, the mic may hear it
        assertTrue(SpeakerRoute.speakerMedia(emptySet()))
    }

    @Test fun earbudsInMidPlaybackLiftTheLockAndOutReLock() {
        val speaker = setOf(AudioDeviceInfo.TYPE_BUILTIN_SPEAKER)
        val earbuds = setOf(AudioDeviceInfo.TYPE_BLUETOOTH_A2DP)
        fun on(route: Set<Int>) = SpeakerRoute.speakerMedia(route)
        assertEquals(Verdict.UNLOCK, unlock(10_000))
        // earbuds connect while the window is open: the lock and the window lift at once
        assertTrue(gate.mediaChanged(10_500, on(earbuds)))
        assertEquals(Verdict.PASS, sound("hiss", 11_000, playing = on(earbuds)))
        // a half unlock on the speaker does not survive a switch to earbuds
        assertEquals(Verdict.FIRST_POP, sound("pop", 12_000, playing = on(speaker)))
        assertFalse("no window was open", gate.mediaChanged(12_100, on(earbuds)))
        assertEquals(Verdict.FIRST_POP, sound("pop", 12_300, playing = on(speaker)))
        // back on the speaker: locked again, no window carried over
        assertEquals(Verdict.DROP, sound("hiss", 13_000, playing = on(speaker)))
    }

    @Test fun otherRoutesDoNotLock() {
        // HDMI / a USB DAC / casting: not a known speaker, so no lock (only an empty, unknown route is assumed audible)
        for (t in listOf(AudioDeviceInfo.TYPE_HDMI, AudioDeviceInfo.TYPE_USB_DEVICE, AudioDeviceInfo.TYPE_REMOTE_SUBMIX)) {
            assertFalse("type $t", SpeakerRoute.speakerMedia(setOf(t)))
            assertEquals("other", SpeakerRoute.routeName(setOf(t)))
        }
    }

    @Test fun speakerRouteName() {
        assertEquals("speaker", SpeakerRoute.routeName(setOf(AudioDeviceInfo.TYPE_BUILTIN_SPEAKER)))
        assertEquals("speaker", SpeakerRoute.routeName(setOf(AudioDeviceInfo.TYPE_BLE_SPEAKER)))
        assertEquals("headphones", SpeakerRoute.routeName(setOf(AudioDeviceInfo.TYPE_USB_HEADSET)))
        assertEquals("unknown", SpeakerRoute.routeName(emptySet()))
        // A2DP is named by its device class; an unknown class is fail-safe "bt-speaker"
        assertEquals("bt-speaker", SpeakerRoute.routeName(setOf(AudioDeviceInfo.TYPE_BLUETOOTH_A2DP)))
        assertEquals("bt-speaker", SpeakerRoute.routeName(setOf(AudioDeviceInfo.TYPE_BLUETOOTH_A2DP),
            setOf(BluetoothClass.Device.AUDIO_VIDEO_LOUDSPEAKER)))
        assertEquals("bt-headphones", SpeakerRoute.routeName(setOf(AudioDeviceInfo.TYPE_BLUETOOTH_A2DP),
            setOf(BluetoothClass.Device.AUDIO_VIDEO_HEADPHONES)))
        assertEquals("bt-headphones", SpeakerRoute.routeName(setOf(AudioDeviceInfo.TYPE_BLUETOOTH_A2DP),
            setOf(BluetoothClass.Device.AUDIO_VIDEO_WEARABLE_HEADSET)))
    }

    @Test fun a2dpDeviceClassDecidesSpeakerVsHeadphones() {
        // room speakers: the mic hears them -> lock
        for (c in listOf(BluetoothClass.Device.AUDIO_VIDEO_LOUDSPEAKER, BluetoothClass.Device.AUDIO_VIDEO_HIFI_AUDIO,
            BluetoothClass.Device.AUDIO_VIDEO_PORTABLE_AUDIO, BluetoothClass.Device.AUDIO_VIDEO_CAR_AUDIO,
            BluetoothClass.Device.AUDIO_VIDEO_VIDEO_DISPLAY_AND_LOUDSPEAKER, BluetoothClass.Device.AUDIO_VIDEO_SET_TOP_BOX))
            assertTrue("class $c", SpeakerRoute.a2dpSpeaker(c))
        // in/on the ear: the mic hears nothing -> no lock
        for (c in listOf(BluetoothClass.Device.AUDIO_VIDEO_HEADPHONES, BluetoothClass.Device.AUDIO_VIDEO_WEARABLE_HEADSET,
            BluetoothClass.Device.AUDIO_VIDEO_HANDSFREE))
            assertFalse("class $c", SpeakerRoute.a2dpSpeaker(c))
        // unknown / uncategorised / no permission -> fail safe (speaker, lock)
        assertTrue(SpeakerRoute.a2dpSpeaker(null))
        assertTrue(SpeakerRoute.a2dpSpeaker(BluetoothClass.Device.AUDIO_VIDEO_UNCATEGORIZED))
        assertTrue(SpeakerRoute.a2dpSpeaker(BluetoothClass.Device.AUDIO_VIDEO_MICROPHONE))
    }

    @Test fun a2dpSpeakerLocksAndHeadphonesDoNot() {
        val a2dp = setOf(AudioDeviceInfo.TYPE_BLUETOOTH_A2DP)
        // a Bluetooth speaker over A2DP locks (the mic hears it); an unknown class locks (fail safe)
        assertTrue(SpeakerRoute.speakerMedia(a2dp, setOf(BluetoothClass.Device.AUDIO_VIDEO_LOUDSPEAKER)))
        assertTrue(SpeakerRoute.speakerMedia(a2dp, setOf(null)))
        // earbuds / headphones over A2DP do not lock
        assertFalse(SpeakerRoute.speakerMedia(a2dp, setOf(BluetoothClass.Device.AUDIO_VIDEO_WEARABLE_HEADSET)))
        assertFalse(SpeakerRoute.speakerMedia(a2dp, setOf(BluetoothClass.Device.AUDIO_VIDEO_HEADPHONES)))
    }
}
