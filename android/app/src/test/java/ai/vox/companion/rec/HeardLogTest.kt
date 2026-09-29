package ai.vox.companion.rec

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import org.json.JSONObject

/** The heard-vs-did pure core (contract §4): append/trim/gen-clear, and the "what Canti did" assignment. */
class HeardLogTest {
    private fun sound(t: Long, label: String, dropped: String? = null, gated: String? = null) =
        HeardLog.Sound(t, label, 0, t, t + 300, emptyList(), null, dropped, gated, null)

    @Test fun deliveredSoundIsAssignedToTheResolveThatFollows() {
        val log = HeardLog()
        val s = sound(1000, "hiss")
        log.append(s)
        log.append(HeardLog.Resolve(1100, 1, "hiss"))
        log.append(HeardLog.Decision(1200, 1, "back"))
        log.append(HeardLog.Exec(1300, 1, true))
        val did = log.did(s)!!
        assertEquals(1, did.n)
        assertEquals("hiss", did.sequence)
        assertEquals("back", did.action)
        assertEquals(true, did.ok)
        assertEquals("HISS → back", log.didText(s, did))
    }

    @Test fun droppedSoundIsIgnored() {
        val log = HeardLog()
        val s = sound(1000, "hiss", dropped = "below level gate")
        log.append(s)
        assertNull(log.did(s))
        assertEquals("ignored: below level gate", log.didText(s, null))
    }

    @Test fun mediaLockWithinOneSecondIsIgnored() {
        val log = HeardLog()
        val s = sound(1000, "hiss")
        log.append(s)
        log.append(HeardLog.MediaGate(1500, "hiss", true))
        assertNull(log.did(s))
        assertEquals("ignored: media lock", log.didText(s, null))
    }

    @Test fun noResolveWithinThreeSecondsIsNoAction() {
        val log = HeardLog()
        val s = sound(1000, "click")
        log.append(s)
        assertNull(log.did(s))
        assertEquals("no action", log.didText(s, null))
    }

    @Test fun multiSoundSequenceTakesLastK() {
        val log = HeardLog()
        val a = sound(1000, "pop")
        val b = sound(1100, "pop")
        log.append(a); log.append(b)
        log.append(HeardLog.Resolve(1200, 1, "pop pop"))
        log.append(HeardLog.Decision(1300, 1, "pause"))
        log.append(HeardLog.Exec(1400, 1, true))
        assertEquals("POP → pause", log.didText(a, log.did(a)))
        assertEquals("POP → pause", log.didText(b, log.did(b)))
    }

    @Test fun trimsTo64() {
        val log = HeardLog()
        for (i in 0 until 100) log.append(sound(i.toLong(), "click"))
        assertEquals(64, log.sounds().size)
    }

    @Test fun genChangeClears() {
        val log = HeardLog()
        log.setGen(0)
        log.append(sound(0, "click"))
        log.setGen(1)
        assertEquals(0, log.sounds().size)
    }

    @Test fun windowFiltersByStreamEndMs() {
        val log = HeardLog()
        log.setGen(0)
        val a = HeardLog.Sound(0, "rise", 0, 500, 600, emptyList(), null, null, null, null)
        val b = HeardLog.Sound(10, "fall", 0, 1200, 1300, emptyList(), null, null, null, null)
        log.append(a); log.append(b)
        assertEquals(listOf(a), log.window(0, 400, 700))
        assertEquals(listOf(a, b), log.window(0, 400, 1300))
    }

    @Test fun listenerParsesAndAppends() {
        val log = HeardLog()
        val l = HeardLogListener(log)
        l.onEvent(JSONObject().put("ev", "mic_sound").put("t", 100).put("label", "hiss").put("sound", 1)
            .put("t_start_ms", 50).put("t_end_ms", 200).put("pitch16", org.json.JSONArray(listOf(1.0, 2.0)))
            .put("f0_hz", 120.0).put("dropped", "dry_run"))
        l.onEvent(JSONObject().put("ev", "resolve").put("t", 101).put("n", 1).put("sequence", "hiss"))
        l.onEvent(JSONObject().put("ev", "ignored"))   // unknown kind: skipped
        assertEquals(1, log.sounds().size)
        val s = log.sounds()[0]
        assertEquals("hiss", s.label)
        assertEquals(listOf(1.0, 2.0), s.pitch16)
        assertEquals(120.0, s.f0Hz!!, 1e-9)
        assertEquals("dry_run", s.dropped)
    }

    @Test fun aResolveAfterThreeSecondsDoesNotTakeTheSound() {
        val log = HeardLog()
        val old = sound(1000, "click")
        log.append(old)
        log.append(HeardLog.Resolve(1000 + HeardLog.NO_ACTION_MS + 1, 1, "click"))
        assertNull(log.did(old))
        assertEquals("no action", log.didText(old, null))
    }

    @Test fun aMediaLockedSoundNeverReachesTheNextResolve() {
        val log = HeardLog()
        val locked = sound(1000, "hiss")
        val real = sound(1500, "click")
        log.append(locked)
        log.append(HeardLog.MediaGate(1100, "hiss", true))
        log.append(real)
        log.append(HeardLog.Resolve(1600, 7, "click"))
        assertNull(log.did(locked))
        assertEquals(7, log.did(real)!!.n)
    }

    @Test fun aGatedSoundShowsAsUnknownMedia() {
        val log = HeardLog()
        val s = sound(1000, "hiss", gated = "[\"media\"]")
        log.append(s)
        log.append(HeardLog.Resolve(1100, 2, "unknown"))
        log.append(HeardLog.Decision(1150, 2, "none"))
        assertEquals("UNKNOWN (MEDIA) → none", log.didText(s, log.did(s)))
    }

    @Test fun anOlderGenerationNeverRollsTheLogBack() {
        val log = HeardLog()
        log.setGen(3)
        log.append(sound(1000, "hiss"))
        log.setGen(2)   // a restart's late "stopped" of the old capture
        assertEquals(3, log.generation)
        assertEquals(1, log.window(3, 0, 5000).size)
        log.setGen(4)
        assertEquals(0, log.sounds().size)
    }
}
