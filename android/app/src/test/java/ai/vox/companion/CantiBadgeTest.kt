package ai.vox.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** The badge sprite's manifest (the real asset) and [BadgePlayer]'s state -> frame logic. */
class CantiBadgeTest {
    private val sprite = BadgeSprite.parse(java.io.File(SHEET_DIR, "canti_badge.json").readText())

    /** A small hand-made manifest: frames 0..5; "idle" loops 0,1 at 100 ms; "back" is 2,3 at 50 + 150 ms. */
    private val mini = BadgeSprite.parse(
        """{"sheet":"s.png","frameWidth":38,"frameHeight":38,"columns":8,"frameCount":6,"states":{
        "idle":{"loop":true,"frames":[0,1],"ms":[100,100],"still":0},
        "off":{"loop":true,"frames":[5],"ms":[1000],"still":0},
        "back":{"loop":false,"frames":[2,3],"ms":[50,150],"still":1},
        "hold_scroll_up":{"loop":true,"frames":[4],"ms":[70],"still":0},
        "hold_scroll_down":{"loop":true,"frames":[5,4],"ms":[70,70],"still":0},
        "error":{"loop":true,"frames":[5],"ms":[500],"still":0},
        "error_once":{"loop":false,"frames":[4,5],"ms":[100,100],"still":0}}}""",
    )

    @Test fun manifestCoversEveryState() {
        for (s in BadgeState.values()) for (name in BadgePlayer.namesFor(s)) {
            assertTrue("manifest lacks $name", name in sprite.anims)
        }
        assertEquals("flutter_assets/assets/badge/canti_badge.png", sprite.sheet)
        assertTrue(sprite.frameCount > 0)
    }

    /** tap-to-wake has its own loop in the real sheet: drowsy eyes (1.2 s), then TAP (0.8 s, the still frame); none of
     *  paused's or idle's frames. */
    @Test fun tapToWakeHasItsOwnLoop() {
        assertEquals(listOf("tap_to_wake"), BadgePlayer.namesFor(BadgeState.TAP_TO_WAKE))
        val a = sprite.anims.getValue("tap_to_wake")
        assertTrue(a.loop)
        assertEquals(listOf(1200, 800), a.ms.toList())
        assertEquals(2, a.frames.size); assertEquals(1, a.still)
        for (other in listOf("paused", "idle", "off")) assertTrue(a.frames.none { it in sprite.anims.getValue(other).frames })
        val p = BadgePlayer(sprite)
        p.setHeld(BadgeState.TAP_TO_WAKE, 0)
        assertEquals(a.frames[0], p.frameAt(0))
        assertEquals(a.frames[1], p.frameAt(1200))
        assertEquals("loops", a.frames[0], p.frameAt(2000))
        p.reduceMotion = true; p.setHeld(BadgeState.IDLE, 3000); p.setHeld(BadgeState.TAP_TO_WAKE, 3000)
        assertEquals("reduced motion: TAP", a.frames[1], p.frameAt(3500))
    }

    @Test fun oneShotsAreShortAndHeldStatesLoop() {
        for (s in listOf(BadgeState.SCROLL_UP, BadgeState.SCROLL_DOWN, BadgeState.BACK, BadgeState.FORWARD, BadgeState.HOME)) {
            val a = sprite.anims.getValue(s.name.lowercase())
            assertFalse("${a.name} should be one-shot", a.loop)
            assertTrue("${a.name} is ${a.totalMs} ms", a.totalMs in 300..700)
        }
        for (name in listOf("idle", "hearing", "pending", "hold_scroll_up", "hold_scroll_down", "cursor", "paused", "off", "error", "tap_to_wake")) {
            assertTrue("$name should loop", sprite.anims.getValue(name).loop)
        }
        assertFalse(sprite.anims.getValue("hearing_once").loop)
        assertFalse(sprite.anims.getValue("error_once").loop)
    }

    /** The shrug for a sound heard but not acted on: a brief one-shot, and BadgePlayer plays it (not idle). */
    @Test fun ignoredOnceIsABriefOneShot() {
        val a = sprite.anims.getValue("ignored_once")
        assertFalse(a.loop)
        assertTrue("${a.totalMs} ms", a.totalMs in 400..500)
        assertTrue(a.frames.size in 4..5)
        assertFalse("not hearing's frames", a.frames.any { it in sprite.anims.getValue("hearing").frames })
        val p = BadgePlayer(sprite)
        p.setHeld(BadgeState.IDLE, 0)
        p.playOnce(BadgeState.IGNORED, 1000)
        assertEquals(BadgeState.IGNORED, p.showing)
        assertEquals(a.frames[1], p.frameAt(1000 + a.ms[0].toLong()))
        p.frameAt(1000L + a.totalMs)
        assertEquals(BadgeState.IDLE, p.showing)
    }

    @Test fun scaleIsTheLargestWholeFactor() {
        assertEquals(5, BadgeSprite.scaleFor(76f * 2.625f, 38, 38))   // Z Flip: 190 px = 72 dp
        assertEquals(4, BadgeSprite.scaleFor(72f * 2.625f, 38, 38))   // 189 px doesn't fit 5
        assertEquals(6, BadgeSprite.scaleFor(76f * 3f, 38, 38))
        assertEquals(1, BadgeSprite.scaleFor(10f, 38, 38))
        assertEquals(2, BadgeSprite.scaleFor(100f, 38, 50))            // the taller side limits
    }

    /** Taps count only on drawn pixels: the mask and its rectangles cover exactly the opaque ones. */
    @Test fun hitMaskIsTheDrawnPixels() {
        val o = 0xFF16192B.toInt(); val t = 0x00000000
        val px = intArrayOf(
            t, o, o, t,
            t, o, o, t,
            o, t, t, o,
        )
        val m = BadgeHitMask.of(px, 4, 3)
        assertTrue(m.hit(1, 0)); assertTrue(m.hit(0, 2)); assertTrue(m.hit(3, 2))
        assertFalse(m.hit(0, 0)); assertFalse(m.hit(1, 2)); assertFalse(m.hit(-1, 0)); assertFalse(m.hit(4, 2))
        assertEquals(listOf(listOf(1, 0, 3, 2), listOf(0, 2, 1, 3), listOf(3, 2, 4, 3)), m.rects.map { it.toList() })
        assertEquals(m, BadgeHitMask.of(px.map { if (it != 0) 0xFF7FE0C9.toInt() else 0 }.toIntArray(), 4, 3))
        val shared = BadgeHitMask.shared(arrayOf(m, BadgeHitMask.of(px.copyOf(), 4, 3)))
        assertTrue(shared[0] === shared[1])
    }

    /** On the real sheet: every frame's rectangles cover exactly its opaque pixels, and the transparent margin
     *  (the frame's corners, beside the head) is not the badge's, while the head's middle is. */
    @Test fun realFramesPassTapsAroundTheCharacter() {
        val img = SheetPixels(java.io.File(SHEET_DIR, "canti_badge.png").path)
        for (i in 0 until sprite.frameCount) {
            val px = img.argb(sprite.frameX(i), sprite.frameY(i), sprite.frameW, sprite.frameH)
            val m = BadgeHitMask.of(px, sprite.frameW, sprite.frameH)
            val covered = HashSet<Int>()
            for (r in m.rects) for (y in r[1] until r[3]) for (x in r[0] until r[2]) {
                assertTrue("frame $i: rect over a transparent pixel", m.hit(x, y))
                assertTrue("frame $i: rects overlap", covered.add(y * sprite.frameW + x))
            }
            assertEquals("frame $i", px.count { (it ushr 24) != 0 }, covered.size)
        }
        val idle = sprite.anims.getValue("idle").frames[0]
        val px = img.argb(sprite.frameX(idle), sprite.frameY(idle), sprite.frameW, sprite.frameH)
        val m = BadgeHitMask.of(px, sprite.frameW, sprite.frameH)
        assertFalse(m.hit(sprite.frameW - 1, 0)); assertFalse(m.hit(0, sprite.frameH - 1))
        assertFalse(m.hit(sprite.frameW - 1, sprite.frameH - 1))
        assertTrue(m.hit(sprite.frameW / 2, sprite.frameH / 3))
    }

    /** The manifest's artPxDp rule: whole device px per art px, about the same dp on every screen. */
    @Test fun artPixelIsRoundedDensityTimesArtPxDp() {
        val d38 = 8f / 7f   // the 38-px-head sheet: 3 px at 2.625x, the stipple icon's dot there
        assertEquals(3, BadgeSprite.pixelsPerArtPx(2.625f, d38))       // Z Flip
        assertEquals(3, BadgeSprite.pixelsPerArtPx(3f, d38))
        assertEquals(2, BadgeSprite.pixelsPerArtPx(2f, d38))
        assertEquals(4, BadgeSprite.pixelsPerArtPx(3.5f, d38))
        assertEquals(5, BadgeSprite.pixelsPerArtPx(4f, d38))
        assertEquals(2, BadgeSprite.pixelsPerArtPx(1.5f, d38))
        assertEquals(1, BadgeSprite.pixelsPerArtPx(0.5f, d38))         // never 0
        val d28 = 32f / 21f // the 28-px-head sheet: 4 px at 2.625x
        assertEquals(4, BadgeSprite.pixelsPerArtPx(2.625f, d28))
        assertEquals(3, BadgeSprite.pixelsPerArtPx(2f, d28))
        assertEquals(0f, mini.artPxDp)                                 // absent: the view fits a box instead
        assertEquals(1.1429f, BadgeSprite.parse(
            """{"sheet":"s.png","frameWidth":68,"frameHeight":74,"columns":8,"frameCount":1,"artPxDp":1.1429,
            "states":{"idle":{"loop":true,"frames":[0],"ms":[100]}}}""").artPxDp, 1e-6f)
    }

    @Test fun heldLoopWraps() {
        val p = BadgePlayer(mini)
        p.setHeld(BadgeState.IDLE, 1000)
        assertEquals(0, p.frameAt(1000))
        assertEquals(1, p.frameAt(1150))
        assertEquals(0, p.frameAt(1200))
        assertEquals(50L, p.nextChangeIn(1250))
    }

    @Test fun sameStateDoesNotRestart() {
        val p = BadgePlayer(mini)
        assertTrue(p.setHeld(BadgeState.IDLE, 0))
        assertFalse(p.setHeld(BadgeState.IDLE, 150))
        assertEquals(1, p.frameAt(150))
    }

    @Test fun oneShotReturnsToHeld() {
        val p = BadgePlayer(mini)
        p.setHeld(BadgeState.IDLE, 0)
        p.playOnce(BadgeState.BACK, 1000)
        assertEquals(BadgeState.BACK, p.showing)
        assertEquals(2, p.frameAt(1000))
        assertEquals(3, p.frameAt(1100))
        assertEquals(50L, p.nextChangeIn(1150))       // until the one-shot ends
        assertEquals(0, p.frameAt(1200))              // back to idle, its loop starting over
        assertEquals(BadgeState.IDLE, p.showing)
        assertEquals(1, p.frameAt(1300))
    }

    @Test fun heldChangeDuringOneShotShowsAfterIt() {
        val p = BadgePlayer(mini)
        p.setHeld(BadgeState.IDLE, 0)
        p.playOnce(BadgeState.BACK, 0)
        p.setHeld(BadgeState.OFF, 100)
        assertEquals(3, p.frameAt(100))
        assertEquals(5, p.frameAt(250))
        assertEquals(-1L, p.nextChangeIn(250))        // a one-frame loop never ticks
    }

    @Test fun onceVariantIsPreferredForOneShots() {
        val p = BadgePlayer(mini)
        p.setHeld(BadgeState.ERROR, 0)
        assertEquals(5, p.frameAt(10))
        p.setHeld(BadgeState.IDLE, 0)
        p.playOnce(BadgeState.ERROR, 1000)
        assertEquals(4, p.frameAt(1000))
        assertEquals(0, p.frameAt(1200))
    }

    @Test fun holdScrollFollowsTheLastScroll() {
        val p = BadgePlayer(mini)
        p.setHeld(BadgeState.HOLD_SCROLL, 0)
        assertEquals(4, p.frameAt(0))                 // up by default
        p.playOnce(BadgeState.SCROLL_DOWN, 100)       // no scroll_down in mini: shows idle, then the held state
        assertEquals(5, p.frameAt(100 + 200))         // hold_scroll_down from where the one-shot ended
    }

    @Test fun reducedMotionShowsStillFrames() {
        val p = BadgePlayer(mini)
        p.reduceMotion = true
        p.setHeld(BadgeState.IDLE, 0)
        assertEquals(0, p.frameAt(150))
        assertEquals(-1L, p.nextChangeIn(150))
        p.playOnce(BadgeState.BACK, 1000)
        assertEquals(3, p.frameAt(1000))              // back's still frame for back's length
        assertEquals(200L, p.nextChangeIn(1000))
        assertEquals(0, p.frameAt(1200))
    }
}

/** The sheet's one copy: the Flutter module's asset (the APK has it under flutter_assets/). Tests run in android/app. */
private const val SHEET_DIR = "../../ui/assets/badge"

/** A PNG's ARGB pixels via the test JVM's ImageIO (not on the android.jar compile classpath, so by reflection). */
private class SheetPixels(path: String) {
    private val img: Any = Class.forName("javax.imageio.ImageIO")
        .getMethod("read", java.io.File::class.java).invoke(null, java.io.File(path))
    private val getRGB = img.javaClass.getMethod("getRGB", Int::class.java, Int::class.java, Int::class.java,
        Int::class.java, IntArray::class.java, Int::class.java, Int::class.java)

    fun argb(x: Int, y: Int, w: Int, h: Int): IntArray = getRGB.invoke(img, x, y, w, h, null, 0, w) as IntArray
}
