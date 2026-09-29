package ai.vox.companion

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import android.view.View
import kotlin.math.roundToInt

/**
 * Draws one [StripFrame] snapshot with the pixel-kit geometry (brief §9) and the day/night palette. No logic beyond
 * drawing: the controller owns the state machine ([StripModel]) and hands this view a fresh snapshot. The transcript
 * text exists only here, on screen and in memory.
 *
 * The window is sized by [Overlay.placeStrip] (full width minus the gutters, `body_h + 44` tall). This view draws at
 * scale `s = width / 1048` (the §9 frame is 1080 - 2·16 wide at `s = 1`), snapping the two font sizes to multiples of
 * 8 px so the 8-unit-em pixel fonts stay crisp.
 */
class TranscriptStripView(ctx: Context, private val tiny: Typeface, private val small: Typeface) : View(ctx) {
    private val fill = Paint().apply { isAntiAlias = false }
    private val txt = Paint().apply { isAntiAlias = false }

    var palette = StripPalette.dark()
    var frame: StripFrame? = null
        set(value) { field = value; invalidate() }

    private val s get() = if (width <= 0) 1f else width / FRAME_W
    private fun fontPx(base: Int) = (base * s / 8f).roundToInt().coerceAtLeast(1) * 8

    // §9 geometry, scaled by s (device px at 1080-wide screen).
    private val GUT = 16f; private val P = 4f; private val LH = 60f; private val TAB = 44f
    private val TX = 36f; private val TY0 = 30f

    private val DONE = 0xFF3E9E6A.toInt()
    private val MISS = 0xFFD94A3D.toInt()
    private val ASK = 0xFFF2A33A.toInt()

    override fun onDraw(c: Canvas) {
        super.onDraw(c)
        val f = frame ?: return
        val x0 = 0f; val x1 = width.toFloat()
        val y0 = TAB * s; val y1 = height.toFloat()
        drawTitleTab(c, f, x0, x1, y0)
        drawTimer(c, f, x0, x1, y0)
        drawFrameBox(c, x0, y0, x1, y1)
        drawTranscript(c, f, x0, y0)
        drawRow(c, f, x0, x1, y0)
    }

    private fun drawTitleTab(c: Canvas, f: StripFrame, x0: Float, x1: Float, y0: Float) {
        val smallPx = fontPx(24)
        txt.typeface = small; txt.textSize = smallPx.toFloat()
        val title = f.kind.title
        val tw = txt.measureText(title) + (32 + 16 + 28) * s
        val ty0 = 0f
        fill.color = palette.tabBg
        c.drawRect(x0 + 24 * s, ty0, x0 + 24 * s + tw, y0 + 8 * s, fill)
        // the 4x4-art-px round lamp (orange while listening, red while dictating)
        val lamp = if (f.kind.orangeLamp) ASK else MISS
        lamp(c, (x0 + 24 * s + 14 * s), ty0 + 12 * s, lamp)
        txt.color = palette.tabFg
        c.drawText(title, x0 + (24 + 14 + 16 + 12) * s, ty0 + 10 * s - txt.fontMetrics.ascent, txt)
    }

    private fun drawTimer(c: Canvas, f: StripFrame, x0: Float, x1: Float, y0: Float) {
        if (f.deadline <= 0L || f.totalMs <= 0L) return
        val now = android.os.SystemClock.elapsedRealtime()   // the model's deadlines are on the scheduler's clock
        val left = cellsLeft(now, f.deadline, f.totalMs)
        if (f.deadline > now) postInvalidateDelayed(250)   // tick the cells down
        val n = 8
        val ty0 = 0f
        val cx = x1 - 24 * s - n * 20 * s
        fill.color = palette.tabBg
        c.drawRect(cx - 16 * s, ty0, x1 - 24 * s + 8 * s, y0 + 8 * s, fill)
        fill.color = palette.tabFg
        for (i in 0 until n) {
            val r = floatArrayOf(cx + i * 20 * s, ty0 + 16 * s, cx + i * 20 * s + 12 * s, ty0 + 36 * s)
            if (i < left) c.drawRect(r[0], r[1], r[2], r[3], fill)
            else strokeRect(c, r[0], r[1], r[2], r[3], 4 * s, fill)
        }
    }

    private fun drawFrameBox(c: Canvas, x0: Float, y0: Float, x1: Float, y1: Float) {
        val p = P * s
        fill.color = palette.paper
        c.drawRect(x0 + p, y0, x1 - p, y1, fill)
        c.drawRect(x0, y0 + p, x1, y1 - p, fill)
        fill.color = palette.ink
        // outer line
        c.drawRect(x0 + p, y0, x1 - p, y0 + p, fill); c.drawRect(x0 + p, y1 - p, x1 - p, y1, fill)
        c.drawRect(x0, y0 + p, x0 + p, y1 - p, fill); c.drawRect(x1 - p, y0 + p, x1, y1 - p, fill)
        // inner line at i = 3p
        val i = 3 * p
        c.drawRect(x0 + i, y0 + i, x1 - i, y0 + i + p, fill); c.drawRect(x0 + i, y1 - i - p, x1 - i, y1 - i, fill)
        c.drawRect(x0 + i, y0 + i, x0 + i + p, y1 - i, fill); c.drawRect(x1 - i - p, y0 + i, x1 - i, y1 - i, fill)
    }

    private fun drawTranscript(c: Canvas, f: StripFrame, x0: Float, y0: Float) {
        val bigPx = fontPx(48)
        txt.typeface = tiny; txt.textSize = bigPx.toFloat()
        val tx = x0 + TX * s; val ty = y0 + TY0 * s
        val lines = f.lines.takeLast(2)
        lines.forEachIndexed { li, words ->
            var x = tx
            for (w in words) {
                txt.color = when (w.tone) { Tone.INK -> palette.ink; Tone.DIM -> palette.dim; Tone.BAD -> MISS }
                c.drawText(w.text, x, ty + li * LH * s - txt.fontMetrics.ascent, txt)
                if (w.tone == Tone.BAD) {
                    fill.color = MISS
                    c.drawRect(x, ty + li * LH * s + 50 * s, x + txt.measureText(w.text), ty + li * LH * s + 53 * s, fill)
                } else if (w.tone == Tone.DIM) {
                    dotted(c, x, x + txt.measureText(w.text), ty + li * LH * s + 50 * s, palette.dim, 8 * s)
                }
                x += txt.measureText(w.text + " ")
            }
            if (f.caret && li == lines.size - 1) {
                fill.color = palette.ink
                c.drawRect(x, ty + li * LH * s + 6 * s, x + 20 * s, ty + li * LH * s + 48 * s, fill)
            }
        }
    }

    private fun drawRow(c: Canvas, f: StripFrame, x0: Float, x1: Float, y0: Float) {
        val row = f.row ?: return
        val smallPx = fontPx(24); val bigPx = fontPx(48)
        val ry = y0 + (32 + LH * 2 + 18) * s
        fill.color = palette.ink
        c.drawRect(x0 + 28 * s, ry - 10 * s, x1 - 28 * s, ry - 7 * s, fill)   // a rule above the row
        txt.typeface = small; txt.textSize = smallPx.toFloat(); txt.color = palette.ink
        c.drawText(row.key, x0 + TX * s, ry + 8 * s - txt.fontMetrics.ascent, txt)
        val keyW = txt.measureText(row.key)
        txt.typeface = tiny; txt.textSize = bigPx.toFloat()
        val vx = x1 - TX * s - txt.measureText(row.value)
        dotted(c, x0 + TX * s + keyW + 16 * s, vx - 16 * s, ry + 26 * s, palette.ink, 12 * s)
        txt.color = when (row.signal) {
            Signal.DONE -> DONE; Signal.MISS -> MISS; Signal.ASK -> ASK; Signal.PLAIN -> palette.ink
        }
        c.drawText(row.value, vx, ry - txt.fontMetrics.ascent, txt)
    }

    private fun lamp(c: Canvas, x: Float, y: Float, col: Int, s4: Float = 4f) {
        fill.color = col
        for ((yy, row) in LAMP.withIndex()) for ((xx, ch) in row.withIndex()) {
            if (ch == '#') c.drawRect(x + xx * s4 * s, y + yy * s4 * s, x + (xx + 1) * s4 * s, y + (yy + 1) * s4 * s, fill)
        }
    }

    private fun dotted(c: Canvas, x0: Float, x1: Float, y: Float, col: Int, step: Float) {
        fill.color = col
        var x = x0
        val size = 4 * s
        while (x < x1) { c.drawRect(x, y, x + size, y + size, fill); x += step }
    }

    private fun strokeRect(c: Canvas, l: Float, t: Float, r: Float, b: Float, w: Float, p: Paint) {
        c.drawRect(l, t, r, t + w, p); c.drawRect(l, b - w, r, b, p)
        c.drawRect(l, t, l + w, b, p); c.drawRect(r - w, t, r, b, p)
    }

    companion object {
        const val FRAME_W = 1080f - 2 * 16f   // 1048: the frame width at scale 1 (device px on a 1080-wide screen)
        private val LAMP = listOf(".##.", "####", "####", ".##.")
    }
}

/** The strip's day/night palette (paper, ink, dim, and the inverted tab background/foreground). */
data class StripPalette(val paper: Int, val ink: Int, val dim: Int, val tabBg: Int, val tabFg: Int) {
    companion object {
        fun light() = StripPalette(0xFFDDEBD3.toInt(), 0xFF1D2757.toInt(), 0xFF7F8B9E.toInt(), 0xFF1D2757.toInt(), 0xFFDDEBD3.toInt())
        fun dark() = StripPalette(0xFF1D2757.toInt(), 0xFFF4F0DC.toInt(), 0xFF8A93B8.toInt(), 0xFFDDEBD3.toInt(), 0xFF1D2757.toInt())
    }
}
