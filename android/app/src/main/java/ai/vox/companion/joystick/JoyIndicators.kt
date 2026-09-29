package ai.vox.companion.joystick

import org.json.JSONObject
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.max
import kotlin.math.min

/*
 * The joystick's indicators, approved 2026-09-27 as static mockups (extractor/joystick_ind.py is the drawing code;
 * JoyIndicatorsTest checks these rules against it):
 *  Cursor B  a 13-cell pixel ring with a centre dot; moving = 1-3 chevrons ahead in its heading (8 directions), more
 *            when faster; voiced but not moving = four crosshair ticks; stopped = the ring; snapped = corner brackets
 *            around the element. The grids come pre-drawn in assets/joystick_cursor.json (tools/gen_joystick_cursor.py).
 *  Face A    the badge's screen: a bar up / down in 4 steps from the line, [----] in the dead zone, an arrowhead past
 *            the range, a side pointer for ee / oo, dashed when not voiced: the badge manifest's joy_* still frames.
 * Pure JVM.
 */
object JoyIndicators {
    val ORDER = listOf("E", "NE", "N", "NW", "W", "SW", "S", "SE")

    /** (dx, dy), y down -> one of 8 headings (joystick_ind.heading). */
    fun heading(dx: Double, dy: Double): String {
        val a = ((Math.toDegrees(atan2(-dy, dx)) % 360) + 360) % 360
        return ORDER[(Math.floorDiv(Math.floor(a + 22.5).toLong(), 45L) % 8).toInt()]
    }

    /** 1-3 chevrons: thirds of the speed ramp (start .. max dp/s). */
    fun chevrons(speed: Double, startDpS: Double, maxDpS: Double): Int {
        val f = (speed - startDpS) / (maxDpS - startDpS)
        return 1 + min(2.0, max(0.0, f * 3)).toInt()
    }

    /** The bar's step name for the manifest: "0", "up1".."up4", "down1".."down4", "upoff" / "downoff" (past = +-1:
     *  outside the range that way). joystick_ind.bar_step. */
    fun barStep(off: Double, dead: Double, full: Double, past: Int = 0): String {
        if (past != 0) return if (past > 0) "upoff" else "downoff"
        val a = abs(off)
        if (a < dead) return "0"
        val n = 1 + min(3.0, (a - dead) / max(1e-6, full - dead) * 4).toInt()
        return if (off > 0) "up$n" else "down$n"
    }

    /** The cursor grid for the mover now: "plain" (no sound), "neutral" (voiced, not moving) or "<heading>-<n>". */
    fun cursorKey(mv: Mover): String {
        if (!mv.active) return "plain"
        val s = mv.state
        if (s.speed <= 0 || (abs(s.dx) < 1e-6 && abs(s.dy) < 1e-6)) return "neutral"
        return "${heading(s.dx, s.dy)}-${chevrons(s.speed, mv.startDpS, mv.maxDpS)}"
    }

    /** Face A's manifest state for the mover now (joystick.py App.face_state + canti_sprite.joy_state_name). */
    fun faceState(mv: Mover): String {
        val s = mv.state
        val sm = s.sm
        if (!mv.active || sm == null) return "joy_idle"
        val (lo, hi) = mv.range
        val (off, dead, full) = when (mv.mode) {
            "glide" -> Triple(s.momentum, mv.spec.glideDead, 1.0)
            "home" -> (s.offset ?: 0.0).let { o -> Triple(o, mv.spec.deadZoneSt, mv.fullSt(o < 0)) }
            else -> Triple(s.offset ?: 0.0, mv.spec.deadZoneSt, mv.startFullSt)
        }
        val past = if (sm > hi) 1 else if (sm < lo) -1 else 0
        val x = s.xVowel
        val dz = mv.vowelDeadZone
        val v = if (x > dz) "ee" else if (x < -dz) "oo" else "ah"
        return "joy_${barStep(off, dead, full, past)}_$v"
    }

    /** Every Face A state name (34), for checks against the badge manifest. */
    val FACE_STATES: List<String> = listOf("joy_idle") +
        listOf("0", "up1", "up2", "up3", "up4", "down1", "down2", "down3", "down4", "upoff", "downoff")
            .flatMap { n -> listOf("ah", "ee", "oo").map { "joy_${n}_$it" } }

    /** A cell grid: 0 clear, 1 ink, 2 paper; (x, y) = its top-left in device px. */
    class Grid(val w: Int, val h: Int, val cells: ByteArray, val x: Int = 0, val y: Int = 0) {
        operator fun get(x: Int, y: Int) = cells[y * w + x].toInt()
        fun rows(): List<String> = (0 until h).map { y -> (0 until w).joinToString("") { x -> get(x, y).toString() } }
    }

    /** Ink cells get a one-cell paper outline (8-neighbour) so they read on light and dark apps. */
    fun outline(w: Int, h: Int, c: ByteArray) {
        val ink = BooleanArray(c.size) { c[it].toInt() == 1 }
        for (y in 0 until h) for (x in 0 until w) {
            val i = y * w + x
            if (ink[i] || c[i].toInt() != 0) continue
            var near = false
            for (dy in -1..1) for (dx in -1..1) {
                val xx = x + dx; val yy = y + dy
                if (xx in 0 until w && yy in 0 until h && ink[yy * w + xx]) near = true
            }
            if (near) c[i] = 2
        }
    }

    /** Snapped: corner brackets around an element's bounds (device px) on the [px]-px art grid (joystick_ind.brackets). */
    fun brackets(l: Int, t: Int, r: Int, b: Int, px: Int, pad: Int = 2, arm: Int = 5): Grid {
        val left = Math.floorDiv(l, px) - pad
        val top = Math.floorDiv(t, px) - pad
        val right = -Math.floorDiv(-r, px) + pad - 1
        val bottom = -Math.floorDiv(-b, px) + pad - 1
        val w = right - left + 3
        val h = bottom - top + 3
        val c = ByteArray(w * h)
        fun set(x: Int, y: Int) { if (x in 0 until w && y in 0 until h) c[y * w + x] = 1 }
        val x0 = 1; val y0 = 1; val x1 = w - 2; val y1 = h - 2
        for (k in 0 until arm) {
            set(x0 + k, y0); set(x0, y0 + k); set(x1 - k, y0); set(x1, y0 + k)
            set(x0 + k, y1); set(x0, y1 - k); set(x1 - k, y1); set(x1, y1 - k)
        }
        set(x0 + 1, y0 + 1); set(x1 - 1, y0 + 1); set(x0 + 1, y1 - 1); set(x1 - 1, y1 - 1)
        outline(w, h, c)
        return Grid(w, h, c, (left - 1) * px, (top - 1) * px)
    }

    /**
     * Ink / paper / cell size (device px per art cell) for the pixel highlights (the snap brackets and the target
     * choice): the cursor art's when present, else the default navy/mint palette at the default art's cell size, so the
     * bracket geometry matches the snap either way. Pure JVM (Overlay, JoyIndicatorsTest).
     */
    class Palette(val ink: Int, val paper: Int, val cellPx: Int) {
        companion object {
            const val DEFAULT_INK = 0xFF1D2757.toInt()
            const val DEFAULT_PAPER = 0xFFDDEBD3.toInt()
            /** assets/joystick_cursor.json's art_px_dp (the default cursor's cell size when no art is loaded). */
            const val DEFAULT_ART_PX_DP = 1.5238095238095237
            fun of(art: CursorArt?, density: Float): Palette =
                art?.let { Palette(it.ink, it.paper, it.cellPx(density)) }
                    ?: Palette(DEFAULT_INK, DEFAULT_PAPER, max(1, Math.round(density * DEFAULT_ART_PX_DP).toInt()))
        }
    }

    /** assets/joystick_cursor.json. */
    class CursorArt(json: String) {
        private val o = JSONObject(json)
        val r = o.getInt("R")
        val artPxDp = o.getDouble("art_px_dp")
        val ink = parseColor(o.getString("ink"))
        val paper = parseColor(o.getString("paper"))
        val grids: Map<String, Grid> = o.getJSONObject("grids").let { g ->
            g.keys().asSequence().associateWith { k ->
                val rows = g.getJSONArray(k)
                val n = rows.length()
                val w = rows.getString(0).length
                val c = ByteArray(w * n)
                for (y in 0 until n) { val s = rows.getString(y); for (x in 0 until w) c[y * w + x] = (s[x] - '0').toByte() }
                Grid(w, n, c)
            }
        }
        /** Device px per art cell: the whole number nearest density x art_px_dp (4 on a 2.625x phone), at least 1. */
        fun cellPx(density: Float): Int = max(1, Math.round(density * artPxDp).toInt())

        companion object {
            const val ASSET = "joystick_cursor.json"
            fun parseColor(s: String): Int = (0xFF000000L or s.removePrefix("#").toLong(16)).toInt()
        }
    }
}
