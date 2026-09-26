package ai.vox.fixture

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.view.GestureDetector
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityNodeInfo.AccessibilityAction
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ListView
import android.widget.TextView
import kotlin.math.abs

/*
 * VOX fixture app: deterministic screens for the emulator suite. Every observable state is a TextView with a resource
 * id, so tests can assert it from `uiautomator dump`.
 *
 *   Menu      buttons to each screen
 *   Feed      vertical "video" feed: swipe up/down = next/previous item, swipe left/right = page, tap = play/pause,
 *             double-tap = like, long-press = long-press counter, back = return to Menu
 *   List      a ListView of 100 rows
 *   Controls  a centred toggle button (tap toggles, long-press counts) and a text field
 *   Static    nothing interactive: any gesture here must produce "no visible change"
 */

private fun Context.label(id: Int, text: String, size: Float = 18f) = TextView(this).apply {
    this.id = id; this.text = text; textSize = size; setTextColor(Color.WHITE)
}

class MenuActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val col = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(48, 120, 48, 48) }
        col.addView(label(R.id.title, "VOX fixture menu", 22f))
        for ((name, cls) in listOf("Feed" to FeedActivity::class.java, "List" to ListActivity::class.java,
                "Controls" to ControlsActivity::class.java, "Static" to StaticActivity::class.java)) {
            col.addView(Button(this).apply { text = name; setOnClickListener { startActivity(Intent(this@MenuActivity, cls)) } })
        }
        setContentView(col)
    }
}

class FeedActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(FeedView(this).apply { id = R.id.feed })
    }
}

/**
 * One full-screen "video" at a time, like a short-video feed. Exposed to accessibility as a vertically scrollable
 * collection with one visible child, which is what a ViewPager2 feed looks like.
 */
class FeedView(ctx: Context) : FrameLayout(ctx) {
    private val count = 20
    private var index = 0
    private var page = 0
    private var playing = true
    private var likes = 0
    private var longPresses = 0
    private val card = LinearLayout(ctx).apply { orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER }
    private val indexLabel = ctx.label(R.id.feed_index, "", 28f)
    private val stateLabel = ctx.label(R.id.feed_state, "")
    private val playButton = ctx.label(R.id.feed_play, "", 16f)
    private val likesLabel = ctx.label(R.id.feed_likes, "")
    private val longLabel = ctx.label(R.id.feed_long, "")
    private val pageLabel = ctx.label(R.id.feed_page, "")
    private var downX = 0f
    private var downY = 0f
    private var swiped = false
    private val colors = intArrayOf(0xFF8E24AA.toInt(), 0xFF3949AB.toInt(), 0xFF00897B.toInt(), 0xFFF4511E.toInt())

    private val detector = GestureDetector(ctx, object : GestureDetector.SimpleOnGestureListener() {
        override fun onDown(e: MotionEvent) = true
        override fun onSingleTapConfirmed(e: MotionEvent): Boolean { playing = !playing; render(); return true }
        override fun onDoubleTap(e: MotionEvent): Boolean { likes++; render(); return true }
        override fun onLongPress(e: MotionEvent) { if (!swiped) { longPresses++; render() } }
    })

    init {
        for (v in listOf(indexLabel, stateLabel, playButton, likesLabel, longLabel, pageLabel)) {
            v.gravity = Gravity.CENTER
            card.addView(v, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT).apply { topMargin = 24 })
        }
        addView(card, LayoutParams(MATCH_PARENT, MATCH_PARENT))
        isFocusable = true
        render()
    }

    private fun render() {
        card.setBackgroundColor(colors[index % colors.size])
        indexLabel.text = "Video ${index + 1} of $count"
        stateLabel.text = if (playing) "playing" else "paused"
        playButton.text = if (playing) "Pause" else "Play"
        playButton.contentDescription = if (playing) "Pause" else "Play"
        likesLabel.text = "likes: $likes"
        longLabel.text = "long presses: $longPresses"
        pageLabel.text = "page: $page"
        sendAccessibilityEvent(android.view.accessibility.AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED)
    }

    private fun go(delta: Int) {
        val n = (index + delta).coerceIn(0, count - 1)
        if (n != index) { index = n; render(); sendAccessibilityEvent(android.view.accessibility.AccessibilityEvent.TYPE_VIEW_SCROLLED) }
    }

    override fun onInterceptTouchEvent(ev: MotionEvent) = true

    override fun onTouchEvent(ev: MotionEvent): Boolean {
        when (ev.actionMasked) {
            MotionEvent.ACTION_DOWN -> { downX = ev.x; downY = ev.y; swiped = false }
            MotionEvent.ACTION_MOVE -> if (abs(ev.x - downX) > 40 || abs(ev.y - downY) > 40) swiped = true
            MotionEvent.ACTION_UP -> {
                val dx = ev.x - downX; val dy = ev.y - downY
                if (abs(dy) > height * 0.15f && abs(dy) > abs(dx)) {
                    go(if (dy < 0) 1 else -1)          // finger moved up = next item
                    cancelDetector(ev); return true
                }
                if (abs(dx) > width * 0.15f && abs(dx) > abs(dy)) {
                    page += if (dx < 0) 1 else -1       // finger moved left = next page
                    render(); cancelDetector(ev); return true
                }
            }
        }
        detector.onTouchEvent(ev)
        return true
    }

    private fun cancelDetector(ev: MotionEvent) {
        val c = MotionEvent.obtain(ev).apply { action = MotionEvent.ACTION_CANCEL }
        detector.onTouchEvent(c); c.recycle()
    }

    override fun getAccessibilityClassName(): CharSequence = "ai.vox.fixture.FeedView"

    override fun onInitializeAccessibilityNodeInfo(info: AccessibilityNodeInfo) {
        super.onInitializeAccessibilityNodeInfo(info)
        info.isScrollable = true
        info.collectionInfo = AccessibilityNodeInfo.CollectionInfo.obtain(count, 1, false)
        if (index < count - 1) info.addAction(AccessibilityAction.ACTION_SCROLL_FORWARD)
        if (index > 0) info.addAction(AccessibilityAction.ACTION_SCROLL_BACKWARD)
    }

    override fun performAccessibilityAction(action: Int, arguments: Bundle?): Boolean = when (action) {
        AccessibilityNodeInfo.ACTION_SCROLL_FORWARD -> { go(1); true }
        AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD -> { go(-1); true }
        else -> super.performAccessibilityAction(action, arguments)
    }
}

class ListActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val lv = ListView(this).apply { id = R.id.list }
        lv.adapter = ArrayAdapter(this, android.R.layout.simple_list_item_1, List(100) { "Item $it" })
        setContentView(lv)
    }
}

class ControlsActivity : Activity() {
    private var on = false
    private var longs = 0

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = FrameLayout(this).apply { setBackgroundColor(0xFF263238.toInt()) }
        val top = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(48, 120, 48, 0) }
        val state = label(R.id.toggle_state, "State: OFF")
        val longState = label(R.id.long_state, "long presses: 0")
        top.addView(state); top.addView(longState)
        top.addView(EditText(this).apply { id = R.id.text_field; hint = "Type here"; setTextColor(Color.WHITE); setHintTextColor(Color.GRAY) })
        root.addView(top, FrameLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT, Gravity.TOP))
        // Centred, so the executor's centre tap / long-press lands on it.
        val toggle = Button(this).apply {
            id = R.id.toggle; text = "Toggle"
            setOnClickListener { on = !on; state.text = if (on) "State: ON" else "State: OFF" }
            setOnLongClickListener { longs++; longState.text = "long presses: $longs"; true }
        }
        root.addView(toggle, FrameLayout.LayoutParams(600, 300, Gravity.CENTER))
        setContentView(root)
    }
}

class StaticActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = FrameLayout(this).apply { setBackgroundColor(0xFF37474F.toInt()) }
        root.addView(label(R.id.static_label, "Static screen: nothing here reacts"), FrameLayout.LayoutParams(WRAP_CONTENT, WRAP_CONTENT, Gravity.TOP or Gravity.CENTER_HORIZONTAL).apply { topMargin = 160 })
        setContentView(root)
    }
}
