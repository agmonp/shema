package com.shema.app

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import org.json.JSONArray
import org.json.JSONObject
import kotlin.concurrent.thread

/**
 * The day on a timeline (2026-10-17), the same data and rules as the PC's day page (/home/api/day, daytl.js):
 * a lane of conversations coloured by the mood in the voice, one lane per speaker (8 at most, by talk time), "לא מזוהה",
 * and a hatched "רקע" lane for TV / music. Opens on the day's active hours. Tap a conversation or a speaker block =
 * that conversation (ConvActivity), at that moment.
 */
class DayActivity : Activity() {
    private val ui = Handler(Looper.getMainLooper())
    private val col = object {
        val bg = Color.parseColor("#13100E"); val surface = Color.parseColor("#1C1815"); val surface2 = Color.parseColor("#25201C")
        val ink = Color.parseColor("#F4EDE5"); val dim = Color.parseColor("#B1A597"); val faint = Color.parseColor("#958A7D")
        val accent = Color.parseColor("#EAA45E"); val accentInk = Color.parseColor("#1B130B"); val rose = Color.parseColor("#E48A7F")
        val sage = Color.parseColor("#86BBA8"); val sky = Color.parseColor("#8FB3E0"); val unk = Color.parseColor("#6F665C")
    }
    private val palette = listOf("#EAA45E", "#86BBA8", "#8FB3E0", "#E48A7F", "#C9A3E6", "#D8C37A").map { Color.parseColor(it) }
    private var dp = 1f
    private var day: String? = null
    private lateinit var body: LinearLayout
    private lateinit var dayRow: LinearLayout

    private fun px(v: Int) = (v * dp).toInt()
    private fun round(color: Int, r: Int, stroke: Int? = null) = GradientDrawable().apply {
        setColor(color); cornerRadius = px(r).toFloat(); stroke?.let { setStroke(px(1), it) } }
    private fun text(t: String, size: Float, color: Int = col.ink, bold: Boolean = false) = TextView(this).apply {
        text = t; textSize = size; setTextColor(color); if (bold) typeface = Typeface.DEFAULT_BOLD }
    private fun chip(t: String, on: Boolean = false, onClick: () -> Unit) = TextView(this).apply {
        text = t; textSize = 13f; gravity = Gravity.CENTER; setTextColor(if (on) col.accentInk else col.ink)
        background = if (on) round(col.accent, 14) else round(col.surface2, 14, Color.parseColor("#33FFECD6"))
        setPadding(px(12), px(7), px(12), px(7)); minHeight = px(36); isClickable = true; setOnClickListener { onClick() }
    }
    private fun sod(iso: String): Double = try {
        iso.substring(11, 13).toInt() * 3600 + iso.substring(14, 16).toInt() * 60 + iso.substring(17).toDouble()
    } catch (e: Exception) { 0.0 }
    private fun mood(v: Double?) = when { v == null || v.isNaN() -> col.unk; v >= .58 -> col.sage; v <= .42 -> col.rose; else -> col.accent }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        dp = resources.displayMetrics.density
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; layoutDirection = View.LAYOUT_DIRECTION_RTL; setPadding(px(14), px(16), px(14), px(24)) }
        val top = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        top.addView(text("→", 24f, col.dim).apply { contentDescription = "חזרה"; setPadding(px(4), 0, px(12), 0); isClickable = true; setOnClickListener { finish() } })
        top.addView(text("ציר הזמן", 21f, bold = true))
        root.addView(top)
        dayRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; layoutDirection = View.LAYOUT_DIRECTION_RTL }
        root.addView(HorizontalScrollView(this).apply { isHorizontalScrollBarEnabled = false; setPadding(0, px(10), 0, px(4)); addView(dayRow) })
        body = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        root.addView(body)
        setContentView(ScrollView(this).apply { setBackgroundColor(col.bg); addView(root) })
        body.addView(text("טוען מהמחשב…", 15f, col.dim))
        thread {
            val d = Net.call(this, "GET", "/home/api/days")
            ui.post {
                if (isDestroyed) return@post
                if (d == null) { body.removeAllViews(); body.addView(text("המחשב לא זמין. ציר הזמן עובד כשהטלפון ברשת הבית (או ב-Tailscale).", 15f, col.rose)); return@post }
                val days = try { JSONArray(d) } catch (e: Exception) { JSONArray() }
                if (days.length() == 0) { body.removeAllViews(); body.addView(text("עוד אין שיחות.", 15f, col.dim)); return@post }
                day = days.getJSONObject(0).optString("day")
                drawDays(days); load()
            }
        }
    }

    private fun drawDays(days: JSONArray) {
        dayRow.removeAllViews()
        for (i in 0 until minOf(days.length(), 30)) {
            val x = days.getJSONObject(i); val d = x.optString("day")
            dayRow.addView(chip("${d.drop(8)}/${d.drop(5).take(2)} · ${x.optInt("conversations")}", d == day) { day = d; drawDays(days); load() })
            dayRow.addView(View(this), LinearLayout.LayoutParams(px(6), 1))
        }
    }

    private fun load() {
        val d = day ?: return
        body.removeAllViews(); body.addView(text("טוען…", 14f, col.dim))
        thread {
            val r = Net.call(this, "GET", "/home/api/day?d=$d")
            ui.post { if (!isDestroyed && d == day) { if (r == null) { body.removeAllViews(); body.addView(text("המחשב לא זמין", 15f, col.rose)) } else show(JSONObject(r)) } }
        }
    }

    private fun show(D: JSONObject) {
        body.removeAllViews()
        val convs = D.optJSONArray("conversations") ?: JSONArray()
        if (convs.length() == 0) { body.addView(text("אין שיחות ביום הזה.", 15f, col.dim)); return }
        // lanes: conversations, then speakers in the order of the day's talk (like the PC), unknown, background
        val talk = D.optJSONArray("talk") ?: JSONArray()
        val order = ArrayList<String>()
        for (i in 0 until talk.length()) { val n = talk.getJSONObject(i).optString("name"); if (n.isNotBlank() && n != "?" && n != "null" && n !in order) order += n }
        val segsIn = D.optJSONArray("segs") ?: JSONArray()
        var hasUnk = false; var hasBg = false
        for (i in 0 until segsIn.length()) { val s = segsIn.getJSONArray(i)
            if (!s.isNull(3) && s.optString(3).isNotBlank()) hasBg = true else if (s.isNull(2) || s.optString(2).isBlank()) hasUnk = true
            else if (s.optString(2) !in order) order += s.optString(2) }
        val named = order.take(8)
        val lanes = ArrayList<TimelineView.Lane>()
        lanes += TimelineView.Lane("שיחות", col.dim, TimelineView.CONVERSATIONS)
        named.forEachIndexed { i, n -> lanes += TimelineView.Lane(n.split(" ")[0], palette[i % palette.size]) }
        if (hasUnk) lanes += TimelineView.Lane("לא מזוהה", col.unk)
        if (hasBg) lanes += TimelineView.Lane("📺 רקע", col.sky, TimelineView.BACKGROUND)
        val unkLane = if (hasUnk) 1 + named.size else -1
        val bgLane = if (hasBg) lanes.size - 1 else -1
        val segs = ArrayList<TimelineView.Seg>()
        var first = Double.MAX_VALUE; var last = 0.0
        for (i in 0 until convs.length()) {
            val c = convs.getJSONObject(i)
            val a = sod(c.optString("start")); val b = maxOf(sod(c.optString("end")), a + 20)
            val v = if (c.isNull("mood_valence")) null else c.optDouble("mood_valence")
            segs += TimelineView.Seg(a, b, 0, c.getInt("id"), c.getInt("id"), mood(v), c.optString("topic").takeIf { it.isNotBlank() && it != "null" })
            first = minOf(first, a); last = maxOf(last, b)
        }
        for (i in 0 until segsIn.length()) {
            val s = segsIn.getJSONArray(i)
            val lane = when {
                !s.isNull(3) && s.optString(3).isNotBlank() -> bgLane
                s.isNull(2) || s.optString(2).isBlank() -> unkLane
                else -> named.indexOf(s.optString(2)).let { if (it < 0) -1 else it + 1 }
            }
            if (lane < 0) continue
            segs += TimelineView.Seg(s.getDouble(0), maxOf(s.getDouble(1), s.getDouble(0) + 0.5), lane, -1, if (s.isNull(4)) 0 else s.getInt(4))
        }
        val tl = TimelineView(this)
        tl.setData(lanes, segs, 0.0, 86400.0, 120.0)
        // the active hours, rounded to the hour (like the PC)
        tl.show(Math.floor(first / 3600) * 3600, minOf(86400.0, Math.ceil(last / 3600) * 3600))
        tl.contentDescription = "ציר הזמן של היום: ${convs.length()} שיחות. צבוט להגדלה, גרור כדי לזוז, הקש על שיחה כדי לפתוח."
        tl.onTap = { s -> if (s.conv > 0) startActivity(Intent(this, ConvActivity::class.java).putExtra("id", s.conv).also { i -> if (s.lane != 0) i.putExtra("at", s.t0) }) }
        val zoomRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL; setPadding(0, px(8), 0, px(6)) }
        val rng = text("", 12f, col.faint)
        zoomRow.addView(rng, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        zoomRow.addView(chip("−") { tl.zoom(0.5) }.apply { contentDescription = "הקטן" })
        zoomRow.addView(View(this), LinearLayout.LayoutParams(px(6), 1))
        zoomRow.addView(chip("+") { tl.zoom(2.0) }.apply { contentDescription = "הגדל" })
        zoomRow.addView(View(this), LinearLayout.LayoutParams(px(6), 1))
        zoomRow.addView(chip("כל היום") { tl.all() })
        tl.onView = { rng.text = TimelineView.ltr("${TimelineView.hm(tl.viewStart)}–${TimelineView.hm(tl.viewStart + tl.viewSpan)}") }
        tl.onView?.invoke()
        body.addView(zoomRow); body.addView(tl)
        // the mood colour only where the PC measures it (Shema Pro does not analyse tone)
        val hasMood = (0 until convs.length()).any { !convs.getJSONObject(it).isNull("mood_valence") }
        body.addView(text((if (hasMood) "צבע השיחה = מצב הרוח בקול (ירוק רגוע · כתום ביניים · אדום מתוח). " else "") +
            "צבוט להגדלה, גרור כדי לזוז, הקש כדי לפתוח.", 12f, col.faint).apply { setPadding(0, px(6), 0, px(12)) })
        // the day's conversations, newest first
        for (i in convs.length() - 1 downTo 0) {
            val c = convs.getJSONObject(i)
            val card = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; background = round(col.surface, 14); setPadding(px(14), px(12), px(14), px(12))
                isClickable = true; setOnClickListener { startActivity(Intent(this@DayActivity, ConvActivity::class.java).putExtra("id", c.getInt("id"))) } }
            card.addView(text(TimelineView.ltr("${c.optString("start").drop(11).take(5)}–${c.optString("end").drop(11).take(5)}"), 12f, col.faint))
            card.addView(text(c.optString("topic").takeIf { it.isNotBlank() && it != "null" } ?: "שיחה", 16f, bold = true))
            c.optString("summary").takeIf { it.isNotBlank() && it != "null" }?.let { card.addView(text(it, 13f, col.dim).apply { maxLines = 3 }) }
            body.addView(card); body.addView(View(this), LinearLayout.LayoutParams(1, px(8)))
        }
    }
}
