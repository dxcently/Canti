package ai.vox.companion

import ai.vox.companion.ForegroundApp.Result
import ai.vox.companion.ForegroundApp.Type
import ai.vox.companion.ForegroundApp.Win
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.random.Random

/** The app in front from the window list and learned packages: the same answer as reading the tree (ForegroundApp.kt). */
class ForegroundAppTest {
    private val own = "ai.vox.companion"
    private val IG = "com.instagram.android"; private val TT = "com.zhiliaoapp.musically"; private val UI = "com.android.systemui"

    /** TreeReader.appRoot's choice (its pick), with every window's root package known; null: no root. */
    private fun model(ws: List<Pair<Win, String>>): String? {
        val active = ws.firstOrNull { it.first.active }
        if (active != null) {
            if (active.second != own) return active.second
            if (ws.any { it.first.active && it.first.type == Type.APPLICATION }) return active.second
        }
        return ws.firstNotNullOfOrNull { (w, p) ->
            when (w.type) { Type.APPLICATION -> p; Type.SYSTEM -> p.takeIf { it != own }; Type.OTHER -> null }
        }
    }

    private fun resolve(ws: List<Pair<Win, String>>, known: Set<Int> = ws.map { it.first.id }.toSet()): Result {
        val pkgs = ws.associate { it.first.id to it.second }
        return ForegroundApp.resolve(ws.map { it.first }, { id -> if (id in known) pkgs[id] else null }, own)
    }

    private fun known(r: Result) = (r as? Result.Known)?.pkg

    @Test fun theActiveAppWindow() {
        val ws = listOf(Win(9, Type.SYSTEM, false) to UI, Win(7, Type.APPLICATION, true) to IG, Win(4, Type.APPLICATION, false) to TT)
        assertEquals(IG, known(resolve(ws)))
        assertEquals(Result.Read, resolve(ws, known = setOf(9, 4)))              // Instagram's window not learned yet: read once
    }

    @Test fun cantiOwnScreensAndTheSystemFallback() {
        // Canti's own settings screen in front: it is the app (as appRoot)
        assertEquals(own, known(resolve(listOf(Win(3, Type.APPLICATION, true) to own, Win(1, Type.APPLICATION, false) to TT))))
        // Canti's head (a system window) active with no active app window: the first app window
        assertEquals(TT, known(resolve(listOf(Win(3, Type.SYSTEM, true) to own, Win(1, Type.APPLICATION, false) to TT))))
        // the notification shade pulled down: SystemUI
        assertEquals(UI, known(resolve(listOf(Win(5, Type.SYSTEM, true) to UI, Win(1, Type.APPLICATION, false) to TT))))
        assertEquals(Result.None, resolve(listOf(Win(3, Type.SYSTEM, false) to own, Win(8, Type.OTHER, false) to "ime")))
        assertEquals(Result.Read, resolve(emptyList()))                          // no window list: read the tree
    }

    /** Same answer as appRoot on every window layout, with everything learned; unknown windows only ever cost a read. */
    @Test fun identicalToTheTreeReadOnRandomLayouts() {
        val rnd = Random(20260927)
        val pkgs = listOf(own, IG, TT, UI, "com.android.chrome")
        repeat(5000) {
            val n = rnd.nextInt(0, 6)
            val activeAt = rnd.nextInt(-1, n.coerceAtLeast(1))
            val ws = (0 until n).map { i ->
                Win(100 + i, Type.values()[rnd.nextInt(3)], i == activeAt) to pkgs[rnd.nextInt(pkgs.size)]
            }
            val full = resolve(ws)
            val want = model(ws)
            if (ws.isEmpty()) assertEquals(Result.Read, full)
            else assertEquals("$ws", want, known(full)).also { if (want == null) assertEquals(Result.None, full) }
            val partial = resolve(ws, known = ws.map { it.first.id }.filter { rnd.nextBoolean() }.toSet())
            assertTrue("$ws: $partial", partial == Result.Read || partial == full)
        }
    }

    @Test fun learnedPackagesForgetWindowsThatAreGone() {
        val m = WindowPackages()
        m.learn(7, IG); m.learn(4, TT); m.learn(-1, "x"); m.learn(5, null)
        assertEquals(2, m.size())
        m.retain(listOf(7, 9))
        assertEquals(IG, m.get(7)); assertNull(m.get(4))
        m.retain(emptyList())                                                     // an unreadable list forgets nothing
        assertEquals(IG, m.get(7))
    }
}
