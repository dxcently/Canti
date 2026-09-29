package ai.vox.companion

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import android.view.View

/**
 * The command chain's queue view (S9, "B-half"): one snug paper block per visible step, right-aligned so it ends at
 * the strip's right edge, stacked just above the strip's timer tab. [ChainViewLayout] is pure (ChainViewLayoutTest);
 * the View draws it with the strip's own 1-bit fonts.
 */
object ChainViewLayout {
    const val BASE = 1080
    const val GUT = 16

    fun scale(width: Int): Float = width.toFloat() / BASE

    // S9 block: 12 px pad + 28 px glyph + 16 px gap + text + note + 12 px pad (the 44 px glyph-to-text gap includes the
    // 28 px glyph, so the fixed shell is 12 + 28 + 16 + 12 = 68 px at scale 1).
    fun blockWidth(s: Float, textW: Float, noteW: Float): Float = 68f * s + textW + noteW

    fun rowHeight(s: Float): Float = 48f * s

    fun chipHeight(s: Float): Float = 34f * s
}

class ChainQueueView(ctx: Context, private val tiny: Typeface, private val small: Typeface) : View(ctx) {
    private val ORANGE = Color.rgb(0xf2, 0xa3, 0x3a)
    private val RED = Color.rgb(0xc0, 0x3a, 0x2e)
    private val DIM = Color.rgb(0x8a, 0x93, 0xb8)
    private val txt = Paint().apply { isAntiAlias = false; typeface = tiny }
    private val notePaint = Paint().apply { isAntiAlias = false; typeface = small }
    private val chipPaint = Paint().apply { isAntiAlias = false; typeface = small }
    private val fill = Paint().apply { isAntiAlias = false }

    var frame: QueueFrame? = null
    var paletteLight = false
    var onTap: (() -> Unit)? = null
    var onScroll: ((Float) -> Unit)? = null   // drag delta y, px

    /** The drawn content's width (blocks + chips) at scale [s], for sizing the window (Y3). */
    fun contentWidth(s: Float): Float {
        val f = frame ?: return 0f
        txt.textSize = 32f * s; notePaint.textSize = 24f * s; chipPaint.textSize = 22f * s
        var w = 0f
        for (row in f.rows) {
            val tw = txt.measureText("${row.n} ${row.text}")
            val nw = row.note?.let { notePaint.measureText("  $it") } ?: 0f
            w = maxOf(w, ChainViewLayout.blockWidth(s, tw, nw))
        }
        if (f.doneAbove > 0) w = maxOf(w, chipPaint.measureText("▲ ${f.doneAbove} done") + 48f * s)
        if (f.moreBelow > 0) w = maxOf(w, chipPaint.measureText("▼ ${f.moreBelow} more") + 48f * s)
        return w
    }

    private var downX = 0f
    private var downY = 0f
    private var lastY = 0f
    private var travelled = 0f

    init {
        setOnTouchListener { _, e ->
            when (e.actionMasked) {
                android.view.MotionEvent.ACTION_DOWN -> { downX = e.x; downY = e.y; lastY = e.y; travelled = 0f; true }
                android.view.MotionEvent.ACTION_MOVE -> {
                    val dy = e.y - lastY; lastY = e.y
                    travelled += Math.abs(e.y - downY) + Math.abs(e.x - downX)
                    onScroll?.invoke(dy)
                    true
                }
                android.view.MotionEvent.ACTION_UP -> {
                    if (travelled < 12 * resources.displayMetrics.density) onTap?.invoke()
                    true
                }
                else -> false
            }
        }
    }

    private fun ink() = if (paletteLight) Color.rgb(0x1d, 0x27, 0x57) else Color.rgb(0xf4, 0xf0, 0xdc)
    private fun paper() = if (paletteLight) Color.rgb(0xdd, 0xeb, 0xd3) else Color.rgb(0x1d, 0x27, 0x57)

    private fun art(d: Canvas, x: Float, y: Float, s: Float, col: Int) =
        d.drawRect(x, y, x + 4f * s - 1f, y + 4f * s - 1f, fill.apply { color = col })

    override fun onDraw(c: Canvas) {
        val f = frame ?: return
        val s = ChainViewLayout.scale(width.coerceAtLeast(1))
        val row = ChainViewLayout.rowHeight(s)
        val right = width - ChainViewLayout.GUT * s - 24f * s
        // chain order top -> bottom: the first visible step (last-done) at the top, the last (next) just above the tabs.
        var y = height - row * f.rows.size
        for (row_ in f.rows) {
            drawRow(c, row_, right, y, s)
            y += row
        }
        // overflow chips above the stack (right-aligned, 12 px apart)
        var cy = height - row * f.rows.size - 44f * s
        if (f.moreBelow > 0) { drawChip(c, "▼ ${f.moreBelow} more", right, cy, s); cy -= ChainViewLayout.chipHeight(s) + 12f * s }
        if (f.doneAbove > 0) drawChip(c, "▲ ${f.doneAbove} done", right, cy, s)
    }

    private fun drawRow(c: Canvas, row: QueueRow, right: Float, ry: Float, s: Float) {
        val ink = ink(); val paper = paper()
        txt.textSize = 32f * s
        notePaint.textSize = 24f * s
        val t = "${row.n} ${row.text}"
        val tw = txt.measureText(t)
        val note = row.note
        val nw = if (note != null) notePaint.measureText("  $note") else 0f
        val x = right - tw - nw
        val gx = x - 44f * s
        // paper block + the 3 px ink bar on the right edge
        fill.color = paper
        c.drawRect(gx - 12f * s, ry, right + 12f * s, ry + 44f * s, fill)
        fill.color = ink
        c.drawRect(right + 8f * s, ry, right + 11f * s, ry + 44f * s, fill)
        drawGlyph(c, row.status, gx, ry + 8f * s, s, ink, paper)
        txt.color = when (row.status) { StepStatus.STUCK -> RED; StepStatus.DONE, StepStatus.UNDONE, StepStatus.DROPPED -> DIM; else -> ink }
        c.drawText(t, x, ry + 6f * s - txt.fontMetrics.ascent, txt)
        if (row.status == StepStatus.UNDONE || row.status == StepStatus.DROPPED) {
            fill.color = DIM
            c.drawRect(x, ry + 24f * s, x + tw, ry + 27f * s, fill)   // strikethrough
        }
        if (note != null) {
            notePaint.color = when (row.status) { StepStatus.STUCK -> RED; StepStatus.RUNNING, StepStatus.ASK -> ORANGE; else -> DIM }
            c.drawText(note, x + tw + notePaint.measureText("  "), ry + 12f * s - notePaint.fontMetrics.ascent, notePaint)
        }
    }

    private fun drawGlyph(c: Canvas, st: StepStatus, x: Float, y: Float, s: Float, ink: Int, paper: Int) {
        when (st) {
            StepStatus.DONE -> {   // ink square + paper tick
                fill.color = ink; c.drawRect(x, y, x + 28f * s, y + 28f * s, fill)
                for ((px, py) in listOf(1 to 4, 2 to 5, 3 to 4, 4 to 3, 5 to 2)) art(c, x + px * 4f * s, y + py * 4f * s, s, paper)
            }
            StepStatus.RUNNING -> {   // orange dot (lamp)
                fill.color = ORANGE
                c.drawCircle(x + 14f * s, y + 14f * s, 8f * s, fill)
            }
            StepStatus.WAITING -> {   // hollow square
                fill.color = DIM; fill.style = Paint.Style.STROKE; fill.strokeWidth = 4f * s
                c.drawRect(x + 4f * s, y + 4f * s, x + 24f * s, y + 24f * s, fill)
                fill.style = Paint.Style.FILL
            }
            StepStatus.STUCK -> {   // red square + paper "!"
                fill.color = RED; c.drawRect(x, y, x + 28f * s, y + 28f * s, fill)
                fill.color = paper
                c.drawRect(x + 12f * s, y + 4f * s, x + 15f * s, y + 16f * s, fill)
                c.drawRect(x + 12f * s, y + 20f * s, x + 15f * s, y + 24f * s, fill)
            }
            StepStatus.ASK -> {   // orange hollow square
                fill.color = ORANGE; fill.style = Paint.Style.STROKE; fill.strokeWidth = 4f * s
                c.drawRect(x + 4f * s, y + 4f * s, x + 24f * s, y + 24f * s, fill)
                fill.style = Paint.Style.FILL
            }
            else -> {   // undone / dropped: a dash
                fill.color = DIM; c.drawRect(x + 4f * s, y + 12f * s, x + 24f * s, y + 16f * s, fill)
            }
        }
    }

    private fun drawChip(c: Canvas, label: String, right: Float, y: Float, s: Float) {
        chipPaint.textSize = 22f * s
        val w = chipPaint.measureText(label) + 48f * s
        val x = right - w
        fill.color = if (paletteLight) Color.rgb(0x1d, 0x27, 0x57) else Color.rgb(0xdd, 0xeb, 0xd3)
        c.drawRect(x, y, x + w, y + ChainViewLayout.chipHeight(s), fill)
        chipPaint.color = if (paletteLight) Color.rgb(0xdd, 0xeb, 0xd3) else Color.rgb(0x1d, 0x27, 0x57)
        c.drawText(label, x + 38f * s, y + 4f * s - chipPaint.fontMetrics.ascent, chipPaint)
    }
}
