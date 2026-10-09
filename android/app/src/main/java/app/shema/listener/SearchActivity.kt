package app.shema.listener

import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import kotlin.concurrent.thread

/**
 * Search, questions, period summaries and "who talked" -- all computed on the PC (nothing is stored or
 * computed here): the phone sends a short request with the pairing token and draws the text that comes back.
 * Results are capped (30 conversations), nothing is kept in memory after the screen closes, and the last
 * stats / summary of each period are saved as small text so they can be shown when the PC is not reachable.
 */
class SearchActivity : Activity() {
    private val ui = Handler(Looper.getMainLooper())
    private val col = object {
        val bg = Color.parseColor("#13100E"); val surface = Color.parseColor("#1C1815"); val surface2 = Color.parseColor("#25201C")
        val ink = Color.parseColor("#F4EDE5"); val dim = Color.parseColor("#B1A597"); val faint = Color.parseColor("#958A7D")
        val accent = Color.parseColor("#EAA45E"); val accentInk = Color.parseColor("#1B130B")
        val sage = Color.parseColor("#86BBA8"); val rose = Color.parseColor("#E48A7F"); val sky = Color.parseColor("#8FB3E0")
    }
    private var dp = 1f
    private var range = "today"
    private val ranges = listOf("today" to "היום", "yesterday" to "אתמול", "week" to "7 ימים", "month" to "30 יום", "all" to "הכל")
    private lateinit var chipRow: LinearLayout
    private lateinit var query: EditText
    private lateinit var statsBox: LinearLayout
    private lateinit var resultBox: LinearLayout
    private var gen = 0                                   // answers of an older request are ignored

    private fun px(v: Int) = (v * dp).toInt()
    private fun round(color: Int, r: Int) = GradientDrawable().apply { setColor(color); cornerRadius = px(r).toFloat() }
    private fun text(t: String, size: Float, color: Int = col.ink, bold: Boolean = false) = TextView(this).apply {
        text = t; textSize = size; setTextColor(color); if (bold) typeface = Typeface.DEFAULT_BOLD
    }
    private fun button(t: String, primary: Boolean = false, onClick: () -> Unit) = TextView(this).apply {
        text = t; textSize = 15f; gravity = Gravity.CENTER
        setTextColor(if (primary) col.accentInk else col.ink); typeface = Typeface.DEFAULT_BOLD
        background = round(if (primary) col.accent else col.surface2, 14)
        setPadding(px(14), px(11), px(14), px(11))
        isClickable = true; setOnClickListener { onClick() }
    }
    private fun card() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL; background = round(col.surface, 18); setPadding(px(14), px(12), px(14), px(12))
    }
    private fun gap(h: Int) = View(this).apply { layoutParams = LinearLayout.LayoutParams(1, px(h)) }
    private fun LinearLayout.add(v: View, top: Int = 0): LinearLayout { if (top > 0) addView(gap(top)); addView(v); return this }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        dp = resources.displayMetrics.density
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; layoutDirection = View.LAYOUT_DIRECTION_RTL
            setPadding(px(16), px(20), px(16), px(28))
        }
        root.addView(text("חיפוש ושאלות", 22f, bold = true))
        root.addView(text("הכל מחושב במחשב. כאן רק מציגים.", 13f, col.faint))
        root.addView(gap(12))
        chipRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        root.addView(android.widget.HorizontalScrollView(this).apply { isHorizontalScrollBarEnabled = false; addView(chipRow) })
        root.addView(gap(10))
        query = EditText(this).apply {
            hint = "חפש בשיחות, או שאל שאלה"; setTextColor(col.ink); setHintTextColor(col.faint)
            inputType = InputType.TYPE_CLASS_TEXT; imeOptions = EditorInfo.IME_ACTION_SEARCH; setSingleLine()
            background = round(col.surface2, 12); setPadding(px(12), px(10), px(12), px(10))
            setOnEditorActionListener { _, _, _ -> doSearch(); true }
        }
        root.addView(query)
        root.addView(gap(8))
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        fun w(v: View, last: Boolean = false) = row.addView(v, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
            .apply { if (!last) marginEnd = px(8) })
        w(button("חפש", true) { doSearch() }); w(button("שאל") { doAsk() }); w(button("סכם", false) { doSummary() }, true)
        root.addView(row)
        root.addView(gap(14))
        resultBox = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        statsBox = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        root.addView(resultBox)
        root.addView(statsBox)
        setContentView(ScrollView(this).apply { setBackgroundColor(col.bg); addView(root) })
        drawChips()
        loadStats()
        doList()
    }

    override fun onDestroy() { gen++; super.onDestroy() }

    private fun drawChips() {
        chipRow.removeAllViews()
        for ((k, t) in ranges) {
            val sel = k == range
            chipRow.addView(TextView(this).apply {
                text = t; textSize = 14f; setTextColor(if (sel) col.accentInk else col.ink); typeface = Typeface.DEFAULT_BOLD
                background = round(if (sel) col.accent else col.surface2, 18); setPadding(px(14), px(8), px(14), px(8))
                isClickable = true
                setOnClickListener { range = k; drawChips(); loadStats(); if (query.text.isBlank()) doList() else doSearch() }
            }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { marginEnd = px(8) })
        }
    }

    // ------------------------------------------------------------ network
    private fun fetch(path: String, timeoutMs: Int = 20000): String? = try {
        val c = URL(Prefs.base(this) + path).openConnection() as HttpURLConnection
        c.connectTimeout = 4000; c.readTimeout = timeoutMs
        c.setRequestProperty("X-Home-Token", Prefs.token(this))
        val r = if (c.responseCode == 200) c.inputStream.bufferedReader().readText() else null
        c.disconnect(); r
    } catch (e: Exception) { null }

    private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")

    private fun run(path: String, timeoutMs: Int, busy: String, show: (JSONObject) -> Unit) {
        val my = ++gen
        resultBox.removeAllViews(); resultBox.addView(text("⏳ $busy", 15f, col.dim))
        thread {
            val r = fetch(path, timeoutMs)
            ui.post {
                if (my != gen || isDestroyed) return@post
                resultBox.removeAllViews()
                if (r == null) { resultBox.addView(text("המחשב לא זמין. החיפוש עובד כשהטלפון ברשת הבית והמחשב ער.", 15f, col.rose)); return@post }
                try { show(JSONObject(r)) } catch (e: Exception) { resultBox.addView(text("תשובה לא תקינה מהמחשב", 15f, col.rose)) }
            }
        }
    }

    // ------------------------------------------------------------ search / ask / summary
    private fun doList() = run("/home/api/search?r=$range&q=", 20000, "טוען שיחות…") { showConvs(it.getJSONArray("results"), null) }

    private fun doSearch() {
        val q = query.text.toString().trim()
        if (q.isEmpty()) { doList(); return }
        run("/home/api/search?r=$range&q=${enc(q)}", 20000, "מחפש…") { showConvs(it.getJSONArray("results"), null) }
    }

    private fun doAsk() {
        val q = query.text.toString().trim()
        if (q.isEmpty()) { resultBox.removeAllViews(); resultBox.addView(text("כתוב שאלה", 15f, col.dim)); return }
        run("/home/api/ask?r=$range&q=${enc(q)}", 240000, "מנסח תשובה מתוך השיחות… (עד חצי דקה)") {
            val a = it.optString("answer", "")
            showConvs(it.optJSONArray("conversations") ?: JSONArray(), if (a.isBlank() || a == "null") "לא הצלחתי לנסח תשובה" else a)
        }
    }

    private fun doSummary() {
        val key = "sum_$range"
        run("/home/api/range_summary?r=$range", 240000, "כותב סיכום… (עד חצי דקה)") {
            if (!it.optBoolean("ok")) { resultBox.addView(text(it.optString("msg", "לא הצליח"), 15f, col.dim)); return@run }
            getSharedPreferences("cache", MODE_PRIVATE).edit().putString(key, it.toString().take(20000)).apply()
            showSummary(it)
        }
    }

    private fun showSummary(j: JSONObject) {
        val c = card()
        c.addView(text("סיכום · ${j.optInt("conversations")} שיחות", 16f, col.accent, true))
        c.addView(text(j.optString("summary"), 16f), )
        val hl = j.optJSONArray("highlights") ?: JSONArray()
        for (i in 0 until hl.length()) c.add(text("• " + hl.getString(i), 14f, col.dim), 6)
        val bp = j.optJSONObject("by_person")
        bp?.keys()?.forEach { n -> c.add(text("$n: ${bp.getString(n)}", 14f, col.sage), 6) }
        resultBox.addView(c)
    }

    private fun showConvs(arr: JSONArray, answer: String?) {
        if (answer != null) {
            val c = card(); c.addView(text("תשובה", 13f, col.faint)); c.addView(text(answer, 17f)); resultBox.addView(c); resultBox.addView(gap(10))
        }
        if (arr.length() == 0) { resultBox.addView(text(if (answer == null) "לא נמצאו שיחות בתקופה הזאת." else "", 15f, col.dim)); return }
        resultBox.addView(text("${arr.length()} שיחות", 13f, col.faint))
        for (i in 0 until minOf(arr.length(), 30)) {
            val k = arr.getJSONObject(i)
            val c = card()
            val place = k.optString("place").let { if (it.isNotBlank() && it != "null") " · 📍$it" else "" }
            c.addView(text(k.optString("start").take(16).replace("T", " ") + place + (if (k.optInt("marked") == 1) " · ⭐" else ""), 12f, col.faint))
            c.addView(text(k.optString("topic").let { if (it == "null" || it.isBlank()) "שיחה" else it }, 16f, bold = true))
            val body = k.optString("snippet").let { if (it.isNotBlank() && it != "null") it else k.optString("summary") }
            if (body.isNotBlank() && body != "null") c.addView(text(body.replace("«", "").replace("»", "").take(260), 14f, col.dim))
            c.isClickable = true; c.setOnClickListener { openConv(k.getInt("id")) }
            resultBox.addView(gap(8)); resultBox.addView(c)
        }
    }

    /** the conversation's lines, in a dialog: fetched on tap, dropped when it closes */
    private fun openConv(id: Int) {
        thread {
            val r = fetch("/home/api/conversation?id=$id")
            ui.post {
                if (isDestroyed) return@post
                if (r == null) { resultBox.addView(text("המחשב לא זמין", 14f, col.rose)); return@post }
                val j = JSONObject(r); val u = j.getJSONArray("utterances"); val sb = StringBuilder()
                for (i in 0 until minOf(u.length(), 120)) {
                    val x = u.getJSONObject(i)
                    if (x.optString("media").let { it.isNotBlank() && it != "null" }) continue
                    val nm = x.optString("name").let { if (it.isBlank() || it == "null") "?" else it.split(" ")[0] }
                    sb.append(nm).append(": ").append(x.optString("text")).append("\n\n")
                }
                val conv = j.optJSONObject("conversation")
                AlertDialog.Builder(this).setTitle(conv?.optString("topic")?.takeIf { it != "null" } ?: "שיחה")
                    .setMessage(sb.toString().ifBlank { "אין תמלול" }).setPositiveButton("סגור", null).show()
            }
        }
    }

    // ------------------------------------------------------------ who talked
    private fun loadStats() {
        statsBox.removeAllViews()
        val key = "stats_$range"
        val cache = getSharedPreferences("cache", MODE_PRIVATE)
        statsBox.addView(gap(14)); statsBox.addView(text("⏳ מי דיבר…", 14f, col.dim))
        val my = ++gen
        thread {
            val r = fetch("/home/api/stats?r=$range")
            ui.post {
                if (isDestroyed) return@post
                statsBox.removeAllViews()
                val src = r ?: cache.getString(key, null)
                if (src == null) return@post
                if (r != null) cache.edit().putString(key, r.take(30000)).apply()
                try { showStats(JSONObject(src), r == null) } catch (e: Exception) { }
            }
        }
    }

    private fun showStats(j: JSONObject, cached: Boolean) {
        val people = j.getJSONArray("people")
        statsBox.addView(gap(14))
        val c = card()
        c.addView(text("מי דיבר" + if (cached) " (נשמר, המחשב לא זמין)" else "", 16f, col.accent, true))
        val before = if (j.isNull("minutes_before")) "" else {
            val d = j.optDouble("minutes") - j.optDouble("minutes_before")
            " · " + (if (d >= 0) "+" else "") + "%.0f".format(d) + " דק׳ מהתקופה הקודמת"
        }
        c.addView(text("${"%.0f".format(j.optDouble("minutes"))} דקות דיבור · ${j.optInt("conversations")} שיחות$before", 13f, col.dim))
        if (people.length() == 0) { c.add(text("אין דיבור בתקופה הזאת.", 14f, col.dim), 8); statsBox.addView(c); return }
        for (i in 0 until minOf(people.length(), 8)) {
            val p = people.getJSONObject(i)
            c.addView(gap(12))
            val head = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
            head.addView(text(p.optString("name").split(" ")[0], 16f, if (p.optString("id") == "?") col.faint else col.ink, true),
                LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            head.addView(text("%.1f דק׳ · %d%%".format(p.optDouble("minutes"), (p.optDouble("share") * 100).toInt()), 14f, col.dim))
            c.addView(head)
            val bar = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; background = round(col.surface2, 3) }
            val sh = p.optDouble("share").coerceIn(0.02, 1.0).toFloat()
            bar.addView(View(this).apply { background = round(if (p.optString("id") == "?") col.faint else col.accent, 3) },
                LinearLayout.LayoutParams(0, px(6), sh))
            bar.addView(View(this), LinearLayout.LayoutParams(0, px(6), 1f - sh))
            c.add(bar, 4)
            val bits = mutableListOf<String>()
            bits += "${p.optInt("lines")} משפטים · ${p.optInt("words")} מילים"
            if (!p.isNull("pace")) bits += "קצב ${p.optDouble("pace")} הברות/שנ׳"
            val v = if (p.isNull("valence")) null else p.optDouble("valence")
            if (v != null) bits += "קול " + (if (v >= .58) "רגוע/חיובי" else if (v <= .42) "מתוח" else "ביניים")
            val vs = if (p.isNull("valence_vs_usual")) null else p.optDouble("valence_vs_usual")
            if (vs != null && Math.abs(vs) >= .05) bits += if (vs > 0) "חיובי מהרגיל" else "מתוח מהרגיל"
            if (!p.isNull("minutes_before")) {
                val d = p.optDouble("minutes") - p.optDouble("minutes_before")
                if (Math.abs(d) >= 1) bits += (if (d > 0) "+" else "") + "%.0f".format(d) + " דק׳ מהקודם"
            }
            c.add(text(bits.joinToString(" · "), 12f, col.faint), 3)
            val em = p.optJSONArray("emotions")
            if (em != null && em.length() > 0) {
                val s = (0 until em.length()).joinToString("  ") { val e = em.getJSONObject(it); "${e.optString("emotion")} ${(e.optDouble("share") * 100).toInt()}%" }
                c.add(text("רגש בקול (רק כשהמודל בטוח): $s", 12f, col.sky), 2)
            }
        }
        val un = j.optDouble("unnamed_share")
        if (un >= .15) {
            c.addView(gap(12))
            c.addView(text("${(un * 100).toInt()}% מהדיבור עוד לא זוהה לאדם. כל שם שתלמד משפר את כל השאר.", 13f, col.rose))
            c.add(button("ללמד קולות") { startActivity(Intent(this, TeachActivity::class.java)) }, 6)
        }
        val bg = j.optJSONArray("background")
        val sounds = j.optJSONArray("sounds")
        val extra = mutableListOf<String>()
        if (bg != null) for (i in 0 until bg.length()) { val b = bg.getJSONObject(i); extra += "${b.optString("media")} ${b.optDouble("minutes")} דק׳" }
        if (sounds != null) for (i in 0 until minOf(sounds.length(), 5)) { val s = sounds.getJSONObject(i); extra += "${s.optString("tag")} ×${s.optInt("n")}" }
        if (extra.isNotEmpty()) { c.addView(gap(10)); c.addView(text("ברקע: " + extra.joinToString(" · "), 12f, col.faint)) }
        c.addView(gap(8))
        c.addView(text("הרגשות והטון הם הערכה של מודל, לא קביעה. השוואה ל\"רגיל\" של אותו אדם חשובה יותר מהמספר עצמו.", 11f, col.faint))
        statsBox.addView(c)
    }
}
