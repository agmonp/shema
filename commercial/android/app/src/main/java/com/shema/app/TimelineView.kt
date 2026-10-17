package com.shema.app

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.DashPathEffect
import android.graphics.Paint
import android.graphics.RectF
import android.text.TextPaint
import android.text.TextUtils
import android.view.GestureDetector
import android.view.MotionEvent
import android.view.ScaleGestureDetector
import android.view.View
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

/**
 * The PC's timeline (server/ui/daytl.js) drawn natively for a touch screen: one lane per speaker (who talked when),
 * a "רקע" lane for TV / music, and for a whole day a lane of conversations coloured by the mood in the voice.
 * Time runs left -> right like on the PC; the speaker names sit on the right (Hebrew side).
 * Pinch = zoom around the fingers, drag = move, double tap = zoom in, tap = choose a block.
 * Only what is on screen is drawn, and blocks closer than a pixel are drawn as one, so a long day stays smooth.
 * Times are seconds since midnight (as /home/api/day "segs").
 */
class TimelineView(ctx: Context) : View(ctx) {
    class Lane(val label: String, val color: Int, val kind: Int = SPEAKER)
    /** id = the utterance (speaker lanes) or the conversation (conversation lane); conv = its conversation */
    class Seg(val t0: Double, val t1: Double, val lane: Int, val id: Int, val conv: Int = 0, val color: Int? = null, val label: String? = null)

    companion object {
        const val SPEAKER = 0; const val BACKGROUND = 1; const val CONVERSATIONS = 2
        private val STEPS = doubleArrayOf(5.0, 10.0, 30.0, 60.0, 300.0, 600.0, 900.0, 1800.0, 3600.0, 7200.0, 10800.0)
        /** a time range inside Hebrew text: kept left-to-right ("07:00–22:00", not reversed) */
        fun ltr(s: String) = "⁦$s⁩"
        fun hm(s: Double, sec: Boolean = false): String {
            val t = s.toInt().coerceIn(0, 86399)
            return if (sec) "%02d:%02d:%02d".format(t / 3600, t / 60 % 60, t % 60) else "%02d:%02d".format(t / 3600, t / 60 % 60)
        }
    }

    private val dp = resources.displayMetrics.density
    private var lanes: List<Lane> = emptyList()
    private var segs: List<Seg> = emptyList()            // sorted by t0
    private var maxDur = 0.0
    private var rangeStart = 0.0; private var rangeEnd = 86400.0
    private var minSpan = 300.0
    var viewStart = 0.0; private set
    var viewSpan = 86400.0; private set
    var selLane = -1; set(v) { field = v; invalidate() }
    var selId = -1; set(v) { field = v; invalidate() }
    var playhead = -1.0; set(v) { field = v; invalidate() }
    var onTap: ((Seg) -> Unit)? = null
    var onLaneTap: ((Int) -> Unit)? = null
    var onView: (() -> Unit)? = null

    private val labW get() = 68 * dp
    private val laneH get() = 28 * dp
    private val axisH get() = 18 * dp
    private val plotL get() = 2 * dp
    private val plotR get() = width - labW
    private val plotW get() = max(1f, plotR - plotL)

    private val fill = Paint(Paint.ANTI_ALIAS_FLAG)
    private val stroke = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; strokeWidth = 2 * dp; color = Color.parseColor("#F4EDE5") }
    private val grid = Paint().apply { color = Color.parseColor("#1CFFECD6"); strokeWidth = 1 * dp }
    private val bgPaint = Paint().apply { color = Color.parseColor("#25201C") }
    private val hatch = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.parseColor("#8C8FB3E0"); strokeWidth = 2 * dp; pathEffect = DashPathEffect(floatArrayOf(4 * dp, 3 * dp), 0f) }
    private val text = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { textSize = 12 * dp; isFakeBoldText = true }
    private val small = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { textSize = 10.5f * dp; color = Color.parseColor("#958A7D") }
    private val blockText = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { textSize = 11 * dp; color = Color.parseColor("#1B130B"); isFakeBoldText = true }
    private val playPaint = Paint().apply { color = Color.parseColor("#E48A7F"); strokeWidth = 2 * dp }
    private val r = RectF()

    fun setData(l: List<Lane>, s: List<Seg>, start: Double, end: Double, minSpanS: Double) {
        lanes = l; segs = s.sortedBy { it.t0 }
        maxDur = segs.maxOfOrNull { it.t1 - it.t0 } ?: 0.0
        rangeStart = start; rangeEnd = max(end, start + 1.0); minSpan = min(minSpanS, rangeEnd - rangeStart)
        show(rangeStart, rangeEnd)
        requestLayout()
    }

    /** shows t0..t1 (clamped to the range) */
    fun show(t0: Double, t1: Double) {
        viewSpan = (t1 - t0).coerceIn(minSpan, rangeEnd - rangeStart)
        viewStart = ((t0 + t1) / 2 - viewSpan / 2).coerceIn(rangeStart, rangeEnd - viewSpan)
        invalidate(); onView?.invoke()
    }

    fun zoom(f: Double, at: Double = viewStart + viewSpan / 2) {
        val ns = (viewSpan / f).coerceIn(minSpan, rangeEnd - rangeStart)
        val k = (at - viewStart) / viewSpan
        viewSpan = ns
        viewStart = (at - k * ns).coerceIn(rangeStart, rangeEnd - ns)
        invalidate(); onView?.invoke()
    }

    fun all() = show(rangeStart, rangeEnd)
    fun canZoomIn() = viewSpan > minSpan + 0.5
    fun canZoomOut() = viewSpan < rangeEnd - rangeStart - 0.5

    /** keeps t on screen (when the list scrolls to a line, or the playhead moves) */
    fun reveal(t0: Double, t1: Double = t0) {
        if (t0 >= viewStart && t1 <= viewStart + viewSpan) return
        viewStart = (t0 - viewSpan * 0.25).coerceIn(rangeStart, rangeEnd - viewSpan)
        invalidate(); onView?.invoke()
    }

    private fun x(t: Double) = (plotL + (t - viewStart) / viewSpan * plotW).toFloat()
    private fun t(x: Float) = viewStart + (x - plotL) / plotW * viewSpan
    private fun laneTop(i: Int) = i * laneH

    override fun onMeasure(w: Int, h: Int) {
        setMeasuredDimension(MeasureSpec.getSize(w), (max(1, lanes.size) * laneH + axisH + 2 * dp).toInt())
    }

    override fun onDraw(c: Canvas) {
        val end = viewStart + viewSpan
        // plot background + grid
        r.set(plotL, 0f, plotR, lanes.size * laneH); fill.color = Color.parseColor("#25201C")
        c.drawRoundRect(r, 8 * dp, 8 * dp, bgPaint)
        val step = STEPS.firstOrNull { viewSpan / it <= max(3f, plotW / (64 * dp)) } ?: 10800.0
        var g = Math.ceil(viewStart / step) * step
        val withSec = step < 60
        while (g <= end) {
            val gx = x(g)
            c.drawLine(gx, 0f, gx, lanes.size * laneH, grid)
            val lab = hm(g, withSec); val w = small.measureText(lab)
            c.drawText(lab, (gx - w / 2).coerceIn(plotL, plotR - w), lanes.size * laneH + axisH - 4 * dp, small)
            g += step
        }
        // lanes
        for ((i, ln) in lanes.withIndex()) {
            val top = laneTop(i)
            if (i > 0) c.drawLine(plotL, top, plotR, top, grid)
            val dim = selLane >= 0 && selLane != i && ln.kind == SPEAKER
            text.color = if (selLane == i) Color.parseColor("#F4EDE5") else ln.color
            text.alpha = if (dim) 110 else 255
            val lab = TextUtils.ellipsize(ln.label, text, labW - 10 * dp, TextUtils.TruncateAt.END).toString()
            c.drawText(lab, width - 4 * dp - text.measureText(lab), top + laneH / 2 + 4 * dp, text)
        }
        // blocks: only the visible ones (sorted by start; the longest block bounds how far back to look)
        var i = lowerBound(viewStart - maxDur)
        val pend = arrayOfNulls<FloatArray>(lanes.size)      // per lane: a run of touching blocks drawn as one
        val pendColor = IntArray(lanes.size)
        fun flush(li: Int) {
            val p = pend[li] ?: return
            drawBlock(c, li, p[0], p[1], pendColor[li], null, false); pend[li] = null
        }
        while (i < segs.size && segs[i].t0 <= end) {
            val s = segs[i++]
            if (s.t1 < viewStart || s.lane !in lanes.indices) continue
            val x0 = max(plotL, x(s.t0)); val x1 = min(plotR, max(x(s.t1), x0 + 2 * dp))
            val col = s.color ?: lanes[s.lane].color
            val sel = s.id == selId && selId >= 0
            if (lanes[s.lane].kind == CONVERSATIONS || sel || s.label != null) {
                flush(s.lane); drawBlock(c, s.lane, x0, x1, col, s.label, sel); continue
            }
            val p = pend[s.lane]
            if (p != null && x0 <= p[1] + 1 * dp && pendColor[s.lane] == col) p[1] = max(p[1], x1)
            else { flush(s.lane); pend[s.lane] = floatArrayOf(x0, x1); pendColor[s.lane] = col }
        }
        for (li in lanes.indices) flush(li)
        if (playhead in viewStart..end) { val px = x(playhead); c.drawLine(px, 0f, px, lanes.size * laneH, playPaint) }
    }

    private fun drawBlock(c: Canvas, li: Int, x0: Float, x1: Float, col: Int, label: String?, sel: Boolean) {
        val ln = lanes[li]; val top = laneTop(li)
        val pad = if (ln.kind == CONVERSATIONS) 4 * dp else 6 * dp
        r.set(x0, top + pad, x1, top + laneH - pad)
        if (ln.kind == BACKGROUND) {                       // TV / music: hatched, like the PC
            var hx = x0
            while (hx < x1) { c.drawLine(hx, r.bottom, min(x1, hx + 6 * dp), r.top, hatch); hx += 5 * dp }
            return
        }
        fill.color = col
        fill.alpha = if (selLane >= 0 && selLane != li && ln.kind == SPEAKER) 70 else if (ln.kind == SPEAKER) 225 else 255
        c.drawRoundRect(r, 3 * dp, 3 * dp, fill)
        if (sel) c.drawRoundRect(r, 3 * dp, 3 * dp, stroke)
        if (label != null && x1 - x0 > 34 * dp) {
            val l = TextUtils.ellipsize(label, blockText, x1 - x0 - 8 * dp, TextUtils.TruncateAt.END).toString()
            c.drawText(l, x1 - 4 * dp - blockText.measureText(l), r.centerY() + 4 * dp, blockText)
        }
    }

    private fun lowerBound(t: Double): Int {
        var lo = 0; var hi = segs.size
        while (lo < hi) { val m = (lo + hi) / 2; if (segs[m].t0 < t) lo = m + 1 else hi = m }
        return lo
    }

    /** the block under a finger: the closest one in that lane within 12 dp */
    private fun hit(xp: Float, yp: Float): Seg? {
        val li = (yp / laneH).toInt()
        if (li !in lanes.indices || xp > plotR) return null
        val tt = t(xp); val slop = 12 * dp / plotW * viewSpan
        var best: Seg? = null; var bd = Double.MAX_VALUE
        var i = lowerBound(tt - maxDur - slop)
        while (i < segs.size && segs[i].t0 <= tt + slop) {
            val s = segs[i++]
            if (s.lane != li) continue
            val d = if (tt in s.t0..s.t1) 0.0 else min(abs(tt - s.t0), abs(tt - s.t1))
            if (d <= slop && d < bd) { bd = d; best = s }
        }
        return best
    }

    private val scale = ScaleGestureDetector(ctx, object : ScaleGestureDetector.SimpleOnScaleGestureListener() {
        override fun onScale(d: ScaleGestureDetector): Boolean { zoom(d.scaleFactor.toDouble(), t(d.focusX)); return true }
    })
    private val gest = GestureDetector(ctx, object : GestureDetector.SimpleOnGestureListener() {
        override fun onDown(e: MotionEvent) = true
        override fun onScroll(e1: MotionEvent?, e2: MotionEvent, dx: Float, dy: Float): Boolean {
            if (abs(dx) > abs(dy)) {
                parent?.requestDisallowInterceptTouchEvent(true)
                viewStart = (viewStart + dx / plotW * viewSpan).coerceIn(rangeStart, rangeEnd - viewSpan)
                invalidate(); onView?.invoke()
            }
            return true
        }
        override fun onSingleTapConfirmed(e: MotionEvent): Boolean {
            if (e.x > plotR) { onLaneTap?.invoke((e.y / laneH).toInt().coerceIn(0, lanes.size - 1)); return true }
            hit(e.x, e.y)?.let { onTap?.invoke(it) }
            return true
        }
        override fun onDoubleTap(e: MotionEvent): Boolean { if (e.x <= plotR) zoom(2.0, t(e.x)); return true }
    })

    override fun onTouchEvent(e: MotionEvent): Boolean {
        scale.onTouchEvent(e)
        if (e.pointerCount > 1) parent?.requestDisallowInterceptTouchEvent(true)
        if (!scale.isInProgress) gest.onTouchEvent(e)
        if (e.actionMasked == MotionEvent.ACTION_UP || e.actionMasked == MotionEvent.ACTION_CANCEL) parent?.requestDisallowInterceptTouchEvent(false)
        return true
    }
}
