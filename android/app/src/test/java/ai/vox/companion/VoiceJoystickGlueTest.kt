package ai.vox.companion

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The voice joystick's app-side pieces that run on the JVM: the sliders' clamp, the JSON -> channel-map conversion
 *  (calib_status `result`, calib_get), Face A on the badge player, the calibrate route. */
class VoiceJoystickGlueTest {
    @Test fun sliderClamp() {
        assertEquals(0.9, CursorSlider.DEFAULT, 0.0)
        assertEquals(0.5, CursorSlider.clamp(0.1), 0.0)
        assertEquals(2.0, CursorSlider.clamp(9.0), 0.0)
        assertEquals(1.23, CursorSlider.clamp(1.234), 0.0)
        assertEquals(CursorSlider.DEFAULT, CursorSlider.clamp(Double.NaN), 0.0)
    }

    @Test fun jsonToChannelMaps() {
        val o = JSONObject().put("a", 1).put("n", JSONObject.NULL).put("o", JSONObject().put("x", 2.5))
            .put("l", JSONArray().put("hum").put(JSONObject.NULL))
        val m = JsonMaps.of(o)
        assertEquals(1, m["a"]); assertTrue(m.containsKey("n")); assertNull(m["n"])
        assertEquals(mapOf("x" to 2.5), m["o"])
        assertEquals(listOf("hum", null), m["l"])
    }

    @Test fun faceAOnTheBadgePlayer() {
        val sprite = BadgeSprite.parse(java.io.File("../../ui/assets/badge", "canti_badge.json").readText())
        val p = BadgePlayer(sprite)
        p.setHeld(BadgeState.IDLE, 0)
        val idle = p.frameAt(0)
        assertTrue(p.setJoy("joy_up2_ee"))
        assertFalse(p.setJoy("joy_up2_ee"))
        val joy = sprite.anims.getValue("joy_up2_ee")
        assertEquals(joy.frames[joy.still], p.frameAt(10))
        assertEquals(-1, p.nextChangeIn(10))
        p.playOnce(BadgeState.BACK, 20)                       // one-shots play over it
        val q = BadgePlayer(sprite).also { it.setHeld(BadgeState.IDLE, 0); it.playOnce(BadgeState.BACK, 20) }
        assertEquals(q.frameAt(20), p.frameAt(20))
        assertEquals(joy.frames[joy.still], p.frameAt(20 + 60_000))   // and it comes back after
        assertTrue(p.setJoy(null))
        assertEquals(idle, p.frameAt(0))
        assertFalse(p.setJoy("no_such_state"))                // unknown = off (already off)
    }

    @Test fun calibrateRoute() = assertEquals("calibrate", Pairing.ROUTE_CALIBRATE)
}
