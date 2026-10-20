package com.shema.app

import android.app.Activity
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import kotlin.concurrent.thread

/**
 * Pick several rows and delete them (2026-10-20). Nothing extra on the screen until the user long-presses a row or taps
 * "בחר": then a ✓ box on each row and one bar at the bottom ("3 נבחרו · 🗑 מחק · ביטול"). Deleted rows vanish at once
 * and a "בטל" bar stays for UNDO_MS; only then is [commit] called (off the main thread), or at once when the screen
 * closes ([flush] from onStop), so "בטל" really brings everything back.
 */
class Picker(private val a: Activity, private val host: FrameLayout, private val one: String, private val many: String,
             private val commit: (List<String>) -> Boolean, private val redraw: () -> Unit) {
    private class Row(val v: View, val mark: TextView, val open: () -> Unit, val bg: android.graphics.drawable.Drawable?)
    private val ui = Handler(Looper.getMainLooper())
    private val rows = LinkedHashMap<String, Row>()
    private val chosen = LinkedHashSet<String>()
    private var bar: LinearLayout? = null
    private var pending: Runnable? = null
    var on = false; private set
    private val dp = a.resources.displayMetrics.density
    private fun px(v: Int) = (v * dp).toInt()
    private val accent = Color.parseColor("#EAA45E")

    /** a new list is being drawn */
    fun clear() { rows.clear(); chosen.clear(); on = false; bar?.let { host.removeView(it) }; bar = null }

    /** [v] opens with [open]; long press starts picking. [mark] is a small view the picker shows / ticks. */
    fun row(id: String, v: View, mark: TextView, open: () -> Unit) {
        rows[id] = Row(v, mark, open, v.background)
        mark.visibility = View.GONE
        v.setOnClickListener { if (on) toggle(id) else open() }
        v.setOnLongClickListener { if (!on) start(); toggle(id); true }
    }

    fun start() {
        if (on || rows.isEmpty()) return
        on = true
        rows.values.forEach { it.mark.visibility = View.VISIBLE; paint(it, false) }
        showBar()
    }

    fun stop() {
        on = false; chosen.clear()
        rows.values.forEach { it.mark.visibility = View.GONE; it.v.background = it.bg }
        bar?.let { host.removeView(it) }; bar = null
    }

    private fun toggle(id: String) {
        val r = rows[id] ?: return
        if (!chosen.remove(id)) chosen += id
        paint(r, id in chosen)
        showBar()
    }

    private fun paint(r: Row, sel: Boolean) {
        r.mark.text = if (sel) "✓" else ""
        r.mark.background = GradientDrawable().apply { cornerRadius = px(6).toFloat()
            if (sel) setColor(accent) else { setColor(Color.parseColor("#25201C")); setStroke(px(2), Color.parseColor("#55FFECD6")) } }
        r.mark.setTextColor(Color.parseColor("#1B130B"))
        r.v.background = if (sel) GradientDrawable().apply { setColor(Color.parseColor("#1C1815")); cornerRadius = px(14).toFloat(); setStroke(px(2), accent) } else r.bg
        r.v.contentDescription = if (sel) "נבחר" else null
    }

    private fun barView(): LinearLayout = bar ?: LinearLayout(a).apply {
        orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL; layoutDirection = View.LAYOUT_DIRECTION_RTL
        background = GradientDrawable().apply { setColor(Color.parseColor("#3A322B")); cornerRadius = px(14).toFloat(); setStroke(px(1), Color.parseColor("#33FFECD6")) }
        setPadding(px(14), px(10), px(10), px(10)); elevation = px(8).toFloat()
        host.addView(this, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.BOTTOM)
            .apply { setMargins(px(14), 0, px(14), px(18)) })
        bar = this
    }

    private fun btn(t: String, fill: Int?, ink: Int, click: () -> Unit) = TextView(a).apply {
        text = t; textSize = 15f; typeface = Typeface.DEFAULT_BOLD; setTextColor(ink); gravity = Gravity.CENTER
        background = GradientDrawable().apply { cornerRadius = px(10).toFloat(); setColor(fill ?: Color.TRANSPARENT) }
        setPadding(px(14), px(8), px(14), px(8)); minHeight = px(42); isClickable = true; setOnClickListener { click() }
    }

    private fun showBar() {
        val b = barView(); b.removeAllViews()
        b.addView(TextView(a).apply { text = if (chosen.isEmpty()) "בחר $many למחיקה" else "${chosen.size} נבחרו"; textSize = 15f
            setTextColor(Color.parseColor("#F4EDE5")) }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        b.addView(btn("🗑 מחק", if (chosen.isEmpty()) Color.parseColor("#55E5484D") else Color.parseColor("#E5484D"), Color.WHITE) { if (chosen.isNotEmpty()) delete() })
        b.addView(View(a), LinearLayout.LayoutParams(px(6), 1))
        b.addView(btn("ביטול", null, Color.parseColor("#F4EDE5")) { stop() })
    }

    private fun delete() {
        flush()
        val ids = chosen.toList()
        ids.forEach { rows[it]?.v?.visibility = View.GONE }
        stop()
        val b = barView(); b.removeAllViews()
        b.addView(TextView(a).apply { text = if (ids.size == 1) "ה$one נמחקה" else "${ids.size} $many נמחקו"; textSize = 15f
            setTextColor(Color.parseColor("#F4EDE5")) }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        val send = Runnable {
            pending = null
            bar?.let { host.removeView(it) }; bar = null
            thread {
                val ok = commit(ids)
                ui.post { if (!a.isDestroyed) {
                    if (!ok) android.widget.Toast.makeText(a, "המחשב לא זמין: המחיקה לא בוצעה", android.widget.Toast.LENGTH_LONG).show()
                    redraw() } }
            }
        }
        b.addView(btn("בטל", null, accent) {
            ui.removeCallbacks(send); pending = null
            bar?.let { host.removeView(it) }; bar = null
            ids.forEach { rows[it]?.v?.visibility = View.VISIBLE }
        })
        pending = send
        ui.postDelayed(send, UNDO_MS)
    }

    /** the screen closes: a delete still waiting for its undo time goes now */
    fun flush() { pending?.let { ui.removeCallbacks(it); it.run() } }

    companion object { const val UNDO_MS = 7000L }
}
