package com.shema.app

import android.app.Activity
import android.app.Dialog
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.ColorDrawable
import android.graphics.drawable.GradientDrawable
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.Window
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import org.json.JSONArray
import org.json.JSONObject
import java.net.URLEncoder
import java.util.Locale
import kotlin.concurrent.thread

/**
 * "✂ בחר קטע" (2026-11-21): a part of a conversation / meeting. After "✂ בחר קטע" the user taps the first line and the
 * last line (tap again to move the nearer edge); the bar at the bottom shows the length, moves either edge by ±5 s,
 * plays the part, summarises only it ("/home/api/segment_summary", not saved as the conversation's summary) and shares
 * only its audio (AudioShare with "/home/audio/<kind>/<id>.m4a?from=&to=&ds=&de=").
 * The screen keeps its own rows; it asks mark(i) how to paint row i and calls tap(i) while active.
 */
class Segment(
    private val a: Activity,
    private val kind: String,                       // "conv" | "meeting"
    private val ident: String,                      // conversation id / meeting id
    private val lines: () -> List<JSONObject>,      // the screen's lines (id, t0, t1, name, text, media)
    private val hasAudio: () -> Boolean,
    private val onChange: () -> Unit,               // repaint the rows (and the timeline)
    private val clip: Clip = Clip(a),
) {
    companion object {
        const val NONE = 0; const val IN = 1; const val START = 2; const val END = 3; const val BOTH = 4
        private const val STEP = 5.0
        private const val MAX_SHIFT = 120.0
        fun clock(s: Double): String { val t = Math.floorMod(Math.round(s), 86400L); return "%02d:%02d:%02d".format(Locale.US, t / 3600, t / 60 % 60, t % 60) }
        fun sod(iso: String?): Double? = try {
            iso!!.substring(11, 13).toInt() * 3600 + iso.substring(14, 16).toInt() * 60 + iso.substring(17).toDouble()
        } catch (e: Exception) { null }
        fun length(s: Double): String { val t = Math.round(s); return if (t < 60) "$t שנ׳" else "%d:%02d דק׳".format(Locale.US, t / 60, t % 60) }
        /** one line's audio (the who-said-this window): the same route with from = to = that line */
        fun linePath(kind: String, ident: String, uttId: Int) =
            "/home/audio/$kind/${URLEncoder.encode(ident, "UTF-8")}.m4a?from=$uttId&to=$uttId"
        fun partName(kind: String) = Regex("${if (kind == "meeting") "meeting" else "conversation"}-.+-\\d\\d-\\d\\d-\\d\\d-\\d\\d\\.m4a")
    }

    private val ui = Handler(Looper.getMainLooper())
    private val dp = a.resources.displayMetrics.density
    private val col = object {
        val surface = Color.parseColor("#1C1815"); val surface2 = Color.parseColor("#25201C")
        val ink = Color.parseColor("#F4EDE5"); val dim = Color.parseColor("#B1A597"); val faint = Color.parseColor("#958A7D")
        val accent = Color.parseColor("#EAA45E"); val accentInk = Color.parseColor("#1B130B"); val sage = Color.parseColor("#86BBA8")
        val line = Color.parseColor("#33FFECD6")
    }
    var active = false; private set
    private var fromId = -1; private var toId = -1
    private var ds = 0.0; private var de = 0.0
    private var playState = ""

    private fun px(v: Int) = (v * dp).toInt()
    private fun round(color: Int, r: Int, stroke: Int? = null) = GradientDrawable().apply {
        setColor(color); cornerRadius = px(r).toFloat(); stroke?.let { setStroke(px(1), it) } }
    private fun text(t: String, size: Float, color: Int = col.ink, bold: Boolean = false) = TextView(a).apply {
        text = t; textSize = size; setTextColor(color); if (bold) typeface = Typeface.DEFAULT_BOLD }
    private fun chip(t: String, primary: Boolean = false, onClick: () -> Unit) = TextView(a).apply {
        text = t; textSize = 13f; gravity = Gravity.CENTER; isClickable = true; setOnClickListener { onClick() }
        setTextColor(if (primary) col.accentInk else col.ink); if (primary) typeface = Typeface.DEFAULT_BOLD
        background = if (primary) round(col.accent, 14) else round(col.surface2, 14, col.line)
        setPadding(px(12), px(7), px(12), px(7)); minHeight = px(36)
    }
    private fun ltr(t: TextView) = t.apply { textDirection = View.TEXT_DIRECTION_LTR }

    // ------------------------------------------------------------ the two views the screen places
    private val hint = text("", 13f, col.accent).apply { setPadding(0, 0, px(8), 0) }
    /** under the header: what to tap now, and "✕ ביטול" */
    val banner: LinearLayout = LinearLayout(a).apply {
        orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL; layoutDirection = View.LAYOUT_DIRECTION_RTL
        background = round(col.surface, 10, col.accent); setPadding(px(12), px(8), px(12), px(8)); visibility = View.GONE
        addView(hint, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        addView(text("✕ ביטול", 13f, col.dim).apply { isClickable = true; setPadding(px(8), px(4), 0, px(4)); setOnClickListener { cancel() }
            contentDescription = "בטל את בחירת הקטע" })
    }
    private val dur = text("", 16f, bold = true)
    private val meta = ltrMeta()
    private fun ltrMeta() = text("", 12f, col.faint).apply { setPaddingRelative(px(8), 0, 0, 0) }
    private val play = text("▶", 16f, col.accentInk, true).apply {
        gravity = Gravity.CENTER; background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(col.accent) }
        isClickable = true; setOnClickListener { togglePlay() }; contentDescription = "השמע את הקטע"
    }
    private val startTv = ltr(text("", 12f))
    private val endTv = ltr(text("", 12f))
    private val shareBtn = chip("🎧 שתף את הקטע") {}.also { b -> b.setOnClickListener { share(b) } }
    private val note = text("כולל קולות של אחרים: ודא שהם מסכימים לפני ששולחים.", 11f, col.faint).apply { setPadding(0, px(6), 0, 0) }
    /** the bottom bar: length, ±5 s on each edge, ▶, summarise / share */
    val bar: LinearLayout = LinearLayout(a).apply {
        orientation = LinearLayout.VERTICAL; layoutDirection = View.LAYOUT_DIRECTION_RTL; visibility = View.GONE
        background = GradientDrawable().apply { setColor(col.surface); cornerRadii = FloatArray(8) { i -> if (i < 4) px(16).toFloat() else 0f }; setStroke(px(1), col.accent) }
        setPadding(px(14), px(10), px(14), px(12)); isClickable = true
        addView(LinearLayout(a).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
            addView(dur); addView(meta, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            addView(play, LinearLayout.LayoutParams(px(40), px(40)))
        })
        addView(LinearLayout(a).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL; setPadding(0, px(8), 0, 0)
            addView(edge("התחלה", startTv, true), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            addView(edge("סוף", endTv, false), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        })
        addView(LinearLayout(a).apply {
            orientation = LinearLayout.HORIZONTAL; setPadding(0, px(10), 0, 0)
            addView(chip("סכם את הקטע", primary = true) { summarise() }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { marginEnd = px(8) })
            addView(shareBtn, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        })
        addView(note)
    }

    private fun edge(label: String, at: TextView, start: Boolean) = LinearLayout(a).apply {
        orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
        addView(text(label, 11f, col.faint).apply { setPaddingRelative(0, 0, px(4), 0) })
        addView(ltr(chip("−5") { shift(start, -STEP) }).apply { setPadding(px(8), px(5), px(8), px(5)); minHeight = px(32)
            contentDescription = "$label: 5 שניות מוקדם יותר" })
        addView(at.apply { setPadding(px(4), 0, px(4), 0) })
        addView(ltr(chip("+5") { shift(start, STEP) }).apply { setPadding(px(8), px(5), px(8), px(5)); minHeight = px(32)
            contentDescription = "$label: 5 שניות מאוחר יותר" })
    }

    // ------------------------------------------------------------ choosing
    fun start() { active = true; fromId = -1; toId = -1; ds = 0.0; de = 0.0; refresh() }

    fun cancel() { active = false; fromId = -1; toId = -1; ds = 0.0; de = 0.0; stopPlay(); refresh() }

    /** start a part at this line (the who-said-this window) */
    fun beginAt(i: Int) { start(); tap(i) }

    private fun idx(id: Int) = lines().indexOfFirst { it.optInt("id") == id }
    private fun speech(u: JSONObject) = u.optString("media").let { it.isBlank() || it == "null" } && sod(u.optString("t0")) != null

    /** a tap on line i while choosing */
    fun tap(i: Int) {
        val L = lines()
        if (i !in L.indices) return
        if (!speech(L[i])) { Toast.makeText(a, "בחר משפט של דיבור (לא קטע רקע)", Toast.LENGTH_SHORT).show(); return }
        val id = L[i].optInt("id")
        val f = idx(fromId); val t = idx(toId)
        when {
            f < 0 -> { fromId = id; toId = -1; ds = 0.0; de = 0.0 }
            t < 0 -> { if (i < f) { toId = fromId; fromId = id } else toId = id }
            i < f -> { fromId = id; ds = 0.0 }
            i > t -> { toId = id; de = 0.0 }
            i == f || i == t -> return
            i - f <= t - i -> { fromId = id; ds = 0.0 }
            else -> { toId = id; de = 0.0 }
        }
        stopPlay(); refresh()
    }

    /** how the screen paints row i */
    fun mark(i: Int): Int {
        if (!active) return NONE
        val f = idx(fromId); if (f < 0) return NONE
        val t = idx(toId)
        if (t < 0) return if (i == f) START else NONE           // the end is not chosen yet
        return when { i == f && i == t -> BOTH; i == f -> START; i == t -> END; i in f..t -> IN; else -> NONE }
    }
    fun label(m: Int) = when (m) { START -> "התחלה"; END -> "סוף"; BOTH -> "התחלה וסוף"; else -> "" }

    /** the chosen part in seconds since midnight (for the timeline), or null */
    fun range(): Pair<Double, Double>? {
        val L = lines(); val f = idx(fromId); if (!active || f < 0) return null
        val t = idx(toId)
        val a0 = (sod(L[f].optString("t0")) ?: return null) + ds
        if (t < 0) return a0 to a0
        return a0 to (maxOf(sod(L[t].optString("t1")) ?: 0.0, sod(L[f].optString("t1")) ?: 0.0) + de)
    }
    private fun ready() = active && idx(fromId) >= 0 && idx(toId) >= 0

    private fun shift(start: Boolean, by: Double) {
        val nds = if (start) ds + by else ds; val nde = if (start) de else de + by
        if (maxOf(Math.abs(nds), Math.abs(nde)) > MAX_SHIFT) { Toast.makeText(a, "אפשר להזיז גבול עד שתי דקות", Toast.LENGTH_SHORT).show(); return }
        val old = ds to de; ds = nds; de = nde
        val r = range()
        if (r == null || r.second - r.first < 0.5) { ds = old.first; de = old.second; Toast.makeText(a, "הסוף לא יכול לבוא לפני ההתחלה", Toast.LENGTH_SHORT).show(); return }
        stopPlay(); refresh()
    }

    private fun refresh() {
        banner.visibility = if (active) View.VISIBLE else View.GONE
        hint.text = when { idx(fromId) < 0 -> "✂ הקש על משפט ההתחלה"; idx(toId) < 0 -> "✂ עכשיו הקש על משפט הסוף"; else -> "✂ הקש על משפט כדי להזיז גבול" }
        bar.visibility = if (ready()) View.VISIBLE else View.GONE
        if (ready()) {
            val r = range()!!
            val L = lines(); val f = idx(fromId); val t = idx(toId)
            val n = (f..t).count { speech(L[it]) }
            dur.text = length(r.second - r.first)
            meta.text = " · $n משפטים · " + TimelineView.ltr("${clock(r.first).take(5)}–${clock(r.second).take(5)}")
            startTv.text = clock(r.first); endTv.text = clock(r.second)
            play.visibility = if (hasAudio()) View.VISIBLE else View.GONE
            shareBtn.visibility = if (hasAudio()) View.VISIBLE else View.GONE
            note.visibility = shareBtn.visibility
            play.text = when (playState) { "loading" -> "⏳"; "playing" -> "■"; else -> "▶" }
        }
        onChange()
    }

    // ------------------------------------------------------------ the part's audio and summary
    private fun query() = "from=$fromId&to=$toId&ds=" + "%.1f".format(Locale.US, ds) + "&de=" + "%.1f".format(Locale.US, de)
    private fun audioPath() = "/home/audio/$kind/${URLEncoder.encode(ident, "UTF-8")}.m4a?" + query()

    private fun togglePlay() {
        if (playState == "loading" || playState == "playing") { stopPlay(); refresh(); return }
        clip.playPath(-2, audioPath(), "segment.m4a", "ההקלטה של הקטע כבר לא שמורה") { s ->
            playState = s
            if (s != "loading" && s != "playing" && s != "done") Toast.makeText(a, s, Toast.LENGTH_LONG).show()
            refresh()
        }
    }
    private fun stopPlay() { if (clip.playingId == -2) clip.stop(); playState = "" }
    fun stop() { val was = playState; stopPlay(); if (active && was.isNotEmpty()) refresh() }

    private fun share(btn: TextView) {
        stopPlay(); refresh()
        AudioShare.share(a, audioPath(), "${if (kind == "meeting") "meeting" else "conversation"}-$ident-part.m4a",
            "שתף את הקטע", btn, expect = partName(kind))
    }

    private fun summarise() {
        val r = range() ?: return
        val L = lines(); val f = idx(fromId); val t = idx(toId)
        val n = (f..t).count { speech(L[it]) }
        val head = TimelineView.ltr("${clock(r.first).take(5)}–${clock(r.second).take(5)}") + " · " + length(r.second - r.first)
        val (d, box) = sheet()
        box.addView(text("סיכום הקטע", 17f, bold = true))
        box.addView(text(head, 12f, col.faint).apply { setPadding(0, px(2), 0, px(10)) })
        val wait = text("המחשב מסכם $n משפטים… זה יכול לקחת דקה או שתיים.", 14f, col.dim)
        box.addView(wait)
        val path = "/home/api/segment_summary?kind=$kind&id=${URLEncoder.encode(ident, "UTF-8")}&" + query()
        thread {
            val res = Net.call(a, "GET", path, null, 600_000)?.let { try { JSONObject(it) } catch (e: Exception) { null } }
            ui.post {
                if (a.isFinishing || a.isDestroyed || !d.isShowing) return@post
                box.removeView(wait)
                val sum = res?.optString("summary")?.takeIf { it.isNotBlank() && it != "null" }
                if (res == null || sum == null) {
                    box.addView(text(res?.optString("error")?.takeIf { it.isNotBlank() }
                        ?: "המחשב לא זמין (או שצריך לעדכן בו את שמע). נסה שוב כשהטלפון ברשת הבית.", 14f, col.dim))
                    box.addView(actions(d, null)); return@post
                }
                val people = strs(res.optJSONArray("people"))
                if (people.isNotEmpty()) box.addView(text(people.joinToString(", "), 12f, col.faint).apply { setPadding(0, 0, 0, px(6)) })
                box.addView(text(if (kind == "meeting") "לא נשמר כסיכום של הפגישה" else "לא נשמר כסיכום של השיחה", 11f, col.sage).apply {
                    background = round(Color.TRANSPARENT, 8, col.sage); setPadding(px(8), px(2), px(8), px(2)) },
                    LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { bottomMargin = px(10) })
                val copy = StringBuilder("סיכום קטע · $head\n")
                res.optString("topic").takeIf { it.isNotBlank() && it != "null" }?.let { box.addView(text(it, 15f, col.accent, true)); copy.append(it).append("\n") }
                box.addView(text(sum, 15f).apply { setLineSpacing(0f, 1.2f); setPadding(0, px(4), 0, px(6)) }); copy.append(sum).append("\n")
                val pp = res.optJSONObject("per_person")
                pp?.keys()?.forEach { k -> val s = "• $k: ${pp.optString(k)}"; box.addView(text(s, 14f).apply { setPadding(0, px(3), 0, 0) }); copy.append(s).append("\n") }
                fun list(title: String, items: List<String>) {
                    if (items.isEmpty()) return
                    box.addView(text(title, 13f, col.accent, true).apply { setPadding(0, px(10), 0, 0) }); copy.append("\n$title\n")
                    for (s in items) { box.addView(text("• $s", 14f).apply { setPadding(0, px(3), 0, 0) }); copy.append("• $s\n") }
                }
                list("החלטות", strs(res.optJSONArray("decisions")))
                val tasks = res.optJSONArray("tasks") ?: JSONArray()
                list("משימות", (0 until tasks.length()).map { tasks.getJSONObject(it) }.map { o ->
                    val who = o.optString("who").takeIf { it.isNotBlank() && it != "null" && it != "?" }
                    val due = o.optString("due").takeIf { it.isNotBlank() && it != "null" }
                    (if (who != null) "$who: " else "") + o.optString("what") + (if (due != null) " ($due)" else "") })
                list("הצעדים הבאים", strs(res.optJSONArray("next_steps")))
                res.optString("mood").takeIf { it.isNotBlank() && it != "null" }?.let { box.addView(text(it, 13f, col.dim).apply { setPadding(0, px(8), 0, 0) }) }
                box.addView(text("נכתב אוטומטית מהתמלול של הקטע.", 11f, col.faint).apply { setPadding(0, px(10), 0, 0) })
                box.addView(actions(d, copy.toString().trim()))
            }
        }
    }

    private fun strs(a: JSONArray?) = if (a == null) emptyList() else (0 until a.length()).map { a.optString(it) }.filter { it.isNotBlank() && it != "null" }

    private fun actions(d: Dialog, copyText: String?) = LinearLayout(a).apply {
        orientation = LinearLayout.HORIZONTAL; setPadding(0, px(14), 0, 0)
        val lp = { LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { marginEnd = px(6) } }
        if (copyText != null) addView(chip("📋 העתק") {
            (a.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText("סיכום קטע", copyText))
            Toast.makeText(a, "הסיכום הועתק", Toast.LENGTH_SHORT).show() }, lp())
        if (hasAudio()) addView(chip("🎧 שתף את הקטע") {}.also { b -> b.setOnClickListener { share(b) }; b.maxLines = 1 },
            LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1.6f).apply { marginEnd = px(6) })
        addView(chip("סגור") { d.dismiss() }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
    }

    /** a sheet from the bottom, in the screen's colours */
    private fun sheet(): Pair<Dialog, LinearLayout> {
        val d = Dialog(a)
        d.requestWindowFeature(Window.FEATURE_NO_TITLE)
        val box = LinearLayout(a).apply { orientation = LinearLayout.VERTICAL; layoutDirection = View.LAYOUT_DIRECTION_RTL
            setPadding(px(18), px(8), px(18), px(18)) }
        val outer = LinearLayout(a).apply {
            orientation = LinearLayout.VERTICAL
            background = GradientDrawable().apply { setColor(col.surface); cornerRadii = FloatArray(8) { i -> if (i < 4) px(18).toFloat() else 0f } }
            addView(View(a).apply { background = round(col.faint, 2) }, LinearLayout.LayoutParams(px(36), px(4)).apply {
                gravity = Gravity.CENTER_HORIZONTAL; topMargin = px(10) })
            addView(ScrollView(a).apply { addView(box) })
        }
        d.setContentView(outer)
        d.window?.apply {
            setBackgroundDrawable(ColorDrawable(Color.TRANSPARENT)); setGravity(Gravity.BOTTOM)
            setLayout(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        }
        d.show()
        return d to box
    }
}
