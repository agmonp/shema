package com.shema.app

import android.app.Activity
import android.content.Intent
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.TextUtils
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import org.json.JSONArray
import org.json.JSONObject
import java.time.LocalDate
import kotlin.concurrent.thread

/**
 * "אני" (2026-11-01): one day or one week of what the PC analysed -- numbers and the change from the period before,
 * the week day by day, how the owner spoke (the owner's server "אני" analysis, me2), topics, people, decisions and open
 * items, moments with a link to the conversation, meetings. Every period received is kept on the phone (LocalStore),
 * so with the PC away the saved one is shown with when it was received, and earlier periods stay browsable (‹ ›).
 * The current week with nothing in it yet (a Sunday) shows the last week that has something, and says so.
 * Extras: "kind" = day | week.
 */
class MeActivity : Activity() {
    private val ui = Handler(Looper.getMainLooper())
    private val col = object {
        val bg = Color.parseColor("#13100E"); val surface = Color.parseColor("#1C1815"); val surface2 = Color.parseColor("#25201C")
        val ink = Color.parseColor("#F4EDE5"); val dim = Color.parseColor("#B1A597"); val faint = Color.parseColor("#958A7D")
        val accent = Color.parseColor("#EAA45E"); val sage = Color.parseColor("#86BBA8"); val rose = Color.parseColor("#E48A7F")
    }
    private var dp = 1f
    private lateinit var body: LinearLayout
    private var kind = "week"
    private var start: LocalDate = LocalDate.now()
    private var autoBack = false                         // start moved back because the current period is empty
    private var result: MeResult? = null
    private var loading = false
    private var alive = false
    private var gen = 0

    private fun px(v: Int) = (v * dp).toInt()
    private fun round(color: Int, r: Int, stroke: Int? = null) = GradientDrawable().apply {
        setColor(color); cornerRadius = px(r).toFloat(); stroke?.let { setStroke(px(1), it) }
    }
    private fun text(t: String, size: Float, color: Int = col.ink, bold: Boolean = false) = TextView(this).apply {
        text = t; textSize = size; setTextColor(color); if (bold) typeface = Typeface.DEFAULT_BOLD
        setLineSpacing(0f, 1.15f); textDirection = View.TEXT_DIRECTION_RTL; textAlignment = View.TEXT_ALIGNMENT_VIEW_START
    }
    private fun chip(t: String, on: Boolean = false, onClick: (() -> Unit)?) = TextView(this).apply {
        text = t; textSize = 14f; setTextColor(if (on) col.accent else col.ink); gravity = Gravity.CENTER
        background = round(col.surface2, 14, if (on) col.accent else Color.parseColor("#33FFECD6"))
        setPadding(px(12), px(7), px(12), px(7))
        if (onClick != null) { isClickable = true; setOnClickListener { onClick() } } else alpha = 0.35f
    }
    private fun card() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL; background = round(col.surface, 18, Color.parseColor("#1CFFECD6"))
        setPadding(px(16), px(14), px(16), px(14))
    }
    private fun LinearLayout.gap(h: Int) = addView(View(this@MeActivity), LinearLayout.LayoutParams(1, px(h)))
    private fun LinearLayout.head(t: String) { addView(text(t, 13f, col.faint, true)) }
    private fun LinearLayout.line(t: String, color: Int = col.ink, size: Float = 15f, onClick: (() -> Unit)? = null) {
        gap(6); addView(text(t, size, color).apply { if (onClick != null) { isClickable = true; setOnClickListener { onClick() } } })
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        dp = resources.displayMetrics.density
        kind = if (intent?.getStringExtra("kind") == "day") "day" else "week"
        start = MePeriods.start(kind, LocalDate.now())
        autoBack = true
        body = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; layoutDirection = View.LAYOUT_DIRECTION_RTL
            setPadding(px(18), px(22), px(18), px(40))
        }
        setContentView(ScrollView(this).apply { setBackgroundColor(col.bg); addView(body) })
    }

    override fun onResume() { super.onResume(); alive = true; load(); ui.postDelayed(refresher, 60_000) }
    override fun onPause() { alive = false; ui.removeCallbacks(refresher); super.onPause() }

    // a saved answer is retried every minute (the PC came back: fresh data without touching anything); a fresh one every 5
    private var lastLoad = 0L
    private val refresher = object : Runnable {
        override fun run() {
            if (!alive) return
            val every = if (result?.pcAnswered == true) 300_000 else 60_000
            if (System.currentTimeMillis() - lastLoad >= every) load(quiet = true)
            ui.postDelayed(this, 60_000)
        }
    }

    private fun go(k: String, s: LocalDate, back: Boolean = false) {
        kind = k; start = s; autoBack = back; result = null; load()
    }

    private fun load(quiet: Boolean = false) {
        val my = ++gen; val k = kind; val s = start; val tryBack = autoBack
        loading = true; lastLoad = System.currentTimeMillis()
        if (!quiet) draw()
        thread {
            val store = LocalStore.of(this)
            val today = LocalDate.now()
            val now = System.currentTimeMillis()
            val fetch = { p: String -> if (Prefs.paired(this)) Net.call(this, "GET", p, timeoutMs = 20000) else null }
            var r = MeRepo.load(k, s, today, store, now, fetch)
            var shown = s; var moved = false
            if (tryBack && MePeriods.isCurrent(k, s, today) && !MePeriods.hasData(r.json)) {
                MeRepo.fallback(k, today, store, now, fetch = fetch)?.let { (ps, pr) -> shown = ps; r = pr; moved = true }
            }
            ui.post {
                if (my != gen || isDestroyed) return@post
                loading = false; result = r; start = shown
                movedNote = if (moved) (if (k == "week") "השבוע רק התחיל ועוד לא נשמע בו דיבור, לכן מוצג השבוע הקודם."
                                        else "היום עוד לא נשמע דיבור, לכן מוצג היום הקודם.") else null
                draw()
            }
        }
    }
    private var movedNote: String? = null

    // ------------------------------------------------------------ drawing
    private fun draw() {
        body.removeAllViews()
        val today = LocalDate.now()
        val top = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        top.addView(text("אני", 24f, bold = true), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        for ((k, t) in listOf("day" to "יום", "week" to "שבוע")) {
            top.addView(View(this), LinearLayout.LayoutParams(px(6), 1))
            top.addView(chip(t, k == kind) { if (k != kind) go(k, MePeriods.start(k, today), back = true) })
        }
        body.addView(top)
        body.gap(10)
        // ‹ previous · the period · next ›  (RTL: the earlier period is on the right)
        val nav = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        nav.addView(chip("› הקודם") { go(kind, MePeriods.prev(kind, start)) })
        nav.addView(text(MePeriods.label(kind, start, today), 16f, col.ink, true).apply { gravity = Gravity.CENTER },
            LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        val atNow = MePeriods.isCurrent(kind, start, today)
        nav.addView(chip("הבא ‹", onClick = if (atNow) null else ({ go(kind, MePeriods.next(kind, start)) })))
        body.addView(nav)

        val r = result
        movedNote?.let { body.gap(8); body.addView(text(it, 13f, col.faint)) }
        if (r?.fromCache == true) { body.gap(8); body.addView(text("📦 " + MePeriods.savedNotice(r.fetchedMs), 13f, col.accent)) }
        if (r == null || r.json == null) {
            body.gap(14)
            val c = card()
            if (loading) c.addView(text("טוען…", 15f, col.dim))
            else {
                c.addView(text("אין עדיין ניתוח לתקופה הזו", 16f, bold = true))
                c.line(if (!Prefs.paired(this)) "צריך לחבר את שמע למחשב כדי לקבל ניתוח."
                       else "המחשב לא זמין עכשיו, ואין ניתוח שמור לתקופה הזו. כשהמחשב יחזור, הניתוח יופיע כאן לבד.", col.dim, 14f)
            }
            body.addView(c)
            savedList()
            return
        }
        val j = r.json
        if (!MePeriods.hasData(j)) {
            body.gap(14)
            val c = card()
            c.addView(text(if (kind == "week") "לא נשמע דיבור בשבוע הזה" else "לא נשמע דיבור ביום הזה", 16f, bold = true))
            c.line("כששמע מקשיב, השיחות מנותחות במחשב ומופיעות כאן. אפשר לעבור לתקופה קודמת עם \"הקודם\".", col.dim, 14f)
            body.addView(c)
            if (r.fromCache) savedList()
            return
        }
        val p = j.optJSONObject("period"); val me2 = j.optJSONObject("me2"); val old = j.optJSONObject("me")
        statsCard(p, me2, old)
        if (p != null) daysCard(p)
        if (me2 != null) toneCard(me2)
        if (p != null) { topicsCard(p); peopleCard(p, me2); itemsCard(p); momentsCard(p, me2); meetingsCard(p) }
        else if (me2 != null) momentsCard(null, me2)
        if (p == null) { body.gap(12); body.addView(text("פרטים נוספים (נושאים, משימות, פגישות) יופיעו אחרי עדכון של תוכנת שמע במחשב.", 12f, col.faint)) }
        if (r.fromCache) savedList()
    }

    private fun mins(m: Double): String = when {
        m >= 90 -> "${Math.round(m / 6) / 10.0} שעות".replace(".0 ", " ")
        m >= 10 -> "${Math.round(m)} דק׳"
        else -> "${Math.round(m * 10) / 10.0} דק׳".replace(".0 ", " ")
    }
    private fun pct(v: Double) = "${Math.round(v * 100)}%"

    /** "+40%" / "-20%" / "כמו" against the period before (words, never "a : b" -- that reads backwards in RTL) */
    private fun change(now: Double, before: Double): String = when {
        before <= 0 && now <= 0 -> ""
        before <= 0 -> "חדש"
        else -> { val d = (now - before) / before; if (Math.abs(d) < 0.1) "כמו קודם" else (if (d > 0) "יותר ב-" else "פחות ב-") + pct(Math.abs(d)) }
    }

    private fun statsCard(p: JSONObject?, me2: JSONObject?, old: JSONObject?) {
        body.gap(14)
        val c = card()
        c.head("במספרים")
        val st = p?.optJSONObject("stats")
        if (st != null) {
            val parts = mutableListOf("הוקלטו ${mins(st.optDouble("rec_minutes"))}", "${st.optInt("conversations")} שיחות")
            if (st.optInt("meetings") > 0) parts += "${st.optInt("meetings")} פגישות"
            if (st.optInt("marks") > 0) parts += "${st.optInt("marks")} רגעים שסימנת"
            c.line(parts.joinToString(" · "), col.ink, 16f)
            if (st.optDouble("my_minutes") > 0) c.line("דיברת ${mins(st.optDouble("my_minutes"))}", col.dim, 14f)
            if (st.optInt("decisions") + st.optInt("tasks") > 0)
                c.line("${st.optInt("decisions")} החלטות · ${st.optInt("tasks")} משימות ובקשות", col.dim, 14f)
            p.optJSONObject("prev")?.let { pv ->
                val a = change(st.optDouble("rec_minutes"), pv.optDouble("rec_minutes"))
                val b = change(st.optInt("conversations").toDouble(), pv.optInt("conversations").toDouble())
                if (a.isNotEmpty() || b.isNotEmpty()) {
                    c.gap(8)
                    c.addView(text("לעומת ${if (kind == "week") "השבוע הקודם" else "היום הקודם"} (${MePeriods.ltr(pv.optString("label"))}):", 13f, col.faint))
                    if (a.isNotEmpty()) c.line("זמן הקלטה: $a (${mins(pv.optDouble("rec_minutes"))} אז)", col.dim, 14f)
                    if (b.isNotEmpty()) c.line("שיחות: $b (${pv.optInt("conversations")} אז)", col.dim, 14f)
                    val m2 = change(st.optInt("meetings").toDouble(), pv.optInt("meetings").toDouble())
                    if (m2.isNotEmpty() && (st.optInt("meetings") + pv.optInt("meetings")) > 0) c.line("פגישות: $m2", col.dim, 14f)
                }
            }
        } else if (me2?.optJSONObject("me") != null) {
            val me = me2.getJSONObject("me")
            c.line("דיברת ${mins(me.optDouble("minutes"))} ב-${me.optInt("conversations")} שיחות", col.ink, 16f)
        } else if (old != null) {
            c.line("דיברת ${Math.round(old.optInt("seconds") / 60.0)} דק׳ ב-${old.optInt("conversations")} שיחות" +
                (if (!old.isNull("share")) " · ${pct(old.optDouble("share"))} מהדיבור" else ""), col.ink, 16f)
            c.line("קטעת ${old.optInt("cut_others")} פעמים · קטעו אותך ${old.optInt("was_cut")}", col.dim, 14f)
        }
        body.addView(c)
    }

    /** the week day by day: bar height = minutes recorded, colour = the voices' mood (warmer = more positive) */
    private fun daysCard(p: JSONObject) {
        val days = p.optJSONArray("days") ?: return
        if (days.length() < 2) return
        val ds = (0 until days.length()).map { days.getJSONObject(it) }
        val maxMin = ds.maxOf { it.optDouble("minutes") }
        if (maxMin <= 0) return
        body.gap(12)
        val c = card()
        c.head("מצב רוח ואנרגיה לאורך השבוע")
        c.gap(4)
        c.addView(text("גובה = זמן שיחה · צבע = הטון בקולות (ירוק חיובי, אדום מתוח)", 12f, col.faint))
        c.gap(8)
        val names = listOf("א", "ב", "ג", "ד", "ה", "ו", "ש")
        val chart = object : View(this) {
            val paint = Paint(Paint.ANTI_ALIAS_FLAG)
            override fun onDraw(cv: Canvas) {
                val n = ds.size; val w = width.toFloat() / n; val labelH = px(16).toFloat(); val h = height - labelH
                paint.textSize = px(11).toFloat(); paint.textAlign = Paint.Align.CENTER
                for ((i, d) in ds.withIndex()) {
                    val x = width - (i + 1) * w                     // Sunday on the right (RTL)
                    val m = d.optDouble("minutes")
                    val v = if (d.isNull("valence")) -1.0 else d.optDouble("valence")
                    paint.color = when { m <= 0 -> col.surface2; v < 0 -> col.faint; v >= 0.5 -> col.sage; v >= 0.4 -> col.accent; else -> col.rose }
                    val bh = if (m <= 0) px(2).toFloat() else maxOf(px(4).toFloat(), (h * m / maxMin).toFloat())
                    cv.drawRoundRect(x + w * 0.2f, h - bh, x + w * 0.8f, h, px(3).toFloat(), px(3).toFloat(), paint)
                    paint.color = col.faint
                    cv.drawText(names.getOrElse(i) { "" }, x + w / 2, height.toFloat() - px(3), paint)
                }
            }
        }
        c.addView(chart, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, px(90)))
        val busiest = ds.maxByOrNull { it.optDouble("minutes") }
        if (busiest != null) c.line("היום העמוס: ${MePeriods.heDay(MePeriods.parse(busiest.optString("day")))} (${mins(busiest.optDouble("minutes"))})", col.dim, 13f)
        ds.lastOrNull { !it.isNull("mood") && it.optString("mood").isNotBlank() && it.optString("mood") != "null" }?.let {
            c.line("האווירה ב${MePeriods.heDay(MePeriods.parse(it.optString("day")))}: ${it.optString("mood")}", col.dim, 13f)
        }
        body.addView(c)
    }

    /** how the owner spoke (the owner's server only: me2) */
    private fun toneCard(j: JSONObject) {
        val me = j.optJSONObject("me") ?: return
        if (me.optInt("lines") <= 0) return
        body.gap(12)
        val c = card()
        c.head("איך דיברתי")
        if (!me.isNull("share")) c.line("דיברת ${pct(me.optDouble("share"))} מזמן הדיבור בשיחות שלך", col.ink, 15f)
        if (me.optInt("classified") == 0) c.line("הטון של המשפטים ינותח במחשב בלילה.", col.faint, 13f)
        else {
            val pos = me.optInt("pos"); val neg = me.optInt("neg")
            val tone = when {
                pos + neg < 3 -> "רוב המשפטים ניטרליים"
                neg == 0 -> "$pos משפטים חיוביים, אף לא אחד שלילי"
                pos >= neg -> "חיובי פי ${me.optDouble("ratio")} מהשלילי ($pos מול $neg)"
                else -> "יותר שלילי מחיובי: $pos משפטים חיוביים מול $neg שליליים"
            }
            c.line("☺ $tone", if (neg > 0 && pos < neg) col.rose else col.sage)
            if (neg > 0) c.line("לפי גוטמן, בקשר טוב יש פי 5 משפטים חיוביים מהשליליים.", col.faint, 12f)
        }
        val q = me.optInt("questions")
        c.line("❓ $q שאלות (${Math.round(100.0 * q / me.optInt("lines"))}% מהמשפטים)", col.dim, 14f)
        val raised = me.optInt("raised")
        if (raised > 0) c.line("🔊 הרמת קול $raised " + (if (raised == 1) "פעם" else "פעמים"), col.rose, 14f)
        val cutO = me.optInt("cut_others"); val cutM = me.optInt("was_cut")
        if (cutO + cutM > 0) c.line("✂ קטעת $cutO פעמים · קטעו אותך $cutM", col.dim, 14f)
        val tags = me.optJSONObject("tags"); val he = j.optJSONObject("tag_he")
        if (tags != null && he != null) {
            val warm = listOf("praise", "thanks", "empathy").filter { tags.optInt(it) > 0 }.map { "${he.optString(it)} ${tags.optInt(it)}" }
            val hard = listOf("blame", "sarcasm", "curse").filter { tags.optInt(it) > 0 }.map { "${he.optString(it)} ${tags.optInt(it)}" }
            if (warm.isNotEmpty()) c.line("💛 " + warm.joinToString(" · "), col.dim, 13f)
            if (hard.isNotEmpty()) c.line("⚡ " + hard.joinToString(" · "), col.dim, 13f)
        }
        val ph = j.optJSONArray("phrases")
        if (ph != null && ph.length() > 0) {
            val l = (0 until minOf(5, ph.length())).mapNotNull { ph.optJSONArray(it)?.optString(0) }
            if (l.isNotEmpty()) c.line("הביטויים שלך: " + l.joinToString(" · "), col.dim, 13f)
        }
        trend(c, j.optJSONArray("trend"))
        body.addView(c)
    }

    private fun trend(c: LinearLayout, tr: JSONArray?) {
        if (tr == null || tr.length() < 3) return
        val vals = (0 until tr.length()).map { tr.getJSONObject(it).let { o -> if (o.isNull("pos_share")) -1.0 else o.optDouble("pos_share") } }
        if (vals.count { it >= 0 } < 2) return
        c.gap(10)
        c.addView(text(if (kind == "day") "חיוביות ב-${vals.size} הימים האחרונים" else "חיוביות ב-${vals.size} השבועות האחרונים", 12f, col.faint))
        c.addView(object : View(this) {
            val paint = Paint(Paint.ANTI_ALIAS_FLAG)
            override fun onDraw(cv: Canvas) {
                val n = vals.size; val w = width.toFloat() / n; val h = height.toFloat()
                for ((i, v) in vals.withIndex()) {
                    val x = width - (i + 1) * w + w * 0.18f       // oldest on the right, newest on the left (RTL reading)
                    if (v < 0) { paint.color = col.surface2; cv.drawRect(x, h - px(2), x + w * 0.64f, h, paint); continue }
                    paint.color = if (i == n - 1) col.accent else if (v >= 0.5) col.sage else col.rose
                    cv.drawRoundRect(x, h - maxOf(px(3).toFloat(), (h * v).toFloat()), x + w * 0.64f, h, px(2).toFloat(), px(2).toFloat(), paint)
                }
            }
        }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, px(40)))
    }

    private fun topicsCard(p: JSONObject) {
        val t = p.optJSONArray("topics") ?: return
        if (t.length() == 0) return
        body.gap(12)
        val c = card()
        c.head("נושאים מרכזיים")
        for (i in 0 until t.length()) {
            val o = t.getJSONObject(i)
            c.line("• " + o.optString("text"), col.ink, 15f, onClick = convOpener(o.optInt("conv"), null))
        }
        body.addView(c)
    }

    private fun peopleCard(p: JSONObject, me2: JSONObject?) {
        val talk = p.optJSONArray("people"); val ment = p.optJSONArray("mentioned")
        if ((talk?.length() ?: 0) == 0 && (ment?.length() ?: 0) == 0) return
        body.gap(12)
        val c = card()
        c.head("אנשים")
        // tone with each person, when the owner's server has it (me2.people by name)
        val tone = HashMap<String, JSONObject>()
        me2?.optJSONArray("people")?.let { a -> for (i in 0 until a.length()) a.getJSONObject(i).let { tone[it.optString("name")] = it } }
        if (talk != null && talk.length() > 0) {
            c.line("דיברת הכי הרבה עם:", col.faint, 13f)
            for (i in 0 until minOf(5, talk.length())) {
                val o = talk.getJSONObject(i)
                val tn = tone[o.optString("name")]?.let { x -> if (!x.isNull("pos_share")) " · ${pct(x.optDouble("pos_share"))} חיובי" else "" } ?: ""
                c.line("${o.optString("name")} · ${mins(o.optDouble("minutes"))} ב-${o.optInt("convs")} שיחות$tn", col.ink, 14f)
            }
        }
        if (ment != null && ment.length() > 0) {
            c.gap(6)
            c.line("השמות שעלו הכי הרבה: " + (0 until minOf(6, ment.length())).joinToString(" · ") {
                ment.getJSONObject(it).let { o -> "${o.optString("name")} (${o.optInt("mentions")})" } }, col.dim, 14f)
        }
        body.addView(c)
    }

    /** a section that shows 3 rows and opens the rest with "עוד N" */
    private fun list(c: LinearLayout, title: String, rows: List<Pair<String, (() -> Unit)?>>, color: Int = col.ink) {
        if (rows.isEmpty()) return
        c.gap(10)
        c.addView(text("$title (${rows.size})", 13f, col.faint, true))
        val rest = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; visibility = View.GONE }
        for ((i, r) in rows.withIndex()) (if (i < 3) c else rest).line(r.first, color, 14f, r.second)
        if (rows.size > 3) {
            c.addView(rest)
            c.line("עוד ${rows.size - 3} ▾", col.accent, 13f) {}
            val more = c.getChildAt(c.childCount - 1) as TextView
            more.setOnClickListener { val open = rest.visibility != View.VISIBLE; rest.visibility = if (open) View.VISIBLE else View.GONE
                more.text = if (open) "פחות ▴" else "עוד ${rows.size - 3} ▾" }
        }
    }

    private fun itemsCard(p: JSONObject) {
        val it = p.optJSONObject("items") ?: return
        fun rows(k: String) = it.optJSONArray(k)?.let { a -> (0 until a.length()).map { a.getJSONObject(it) } } ?: emptyList()
        fun who(o: JSONObject) = o.optString("who").takeIf { w -> w.isNotBlank() && w != "null" }?.let { "$it: " } ?: ""
        fun due(o: JSONObject) = o.optString("due").takeIf { d -> d.isNotBlank() && d != "null" }?.let { " ($it)" } ?: ""
        val dec = rows("decisions"); val open = rows("open"); val q = rows("questions"); val done = rows("done")
        if (dec.isEmpty() && open.isEmpty() && q.isEmpty() && done.isEmpty()) return
        body.gap(12)
        val c = card()
        c.head("החלטות, משימות ומה שנשאר פתוח")
        list(c, "הוחלט", dec.map { o -> "✔ " + o.optString("text") to convOpener(o.optInt("conv"), null) })
        list(c, "משימות פתוחות", open.map { o -> "☐ " + who(o) + o.optString("text") + due(o) to convOpener(o.optInt("conv"), null) })
        list(c, "שאלות פתוחות מפגישות", q.map { o -> "? " + o.optString("text") to convOpener(o.optInt("conv"), null) }, col.dim)
        list(c, "בוצעו", done.map { o -> "✓ " + who(o) + o.optString("text") to convOpener(o.optInt("conv"), null) }, col.faint)
        body.addView(c)
    }

    private fun momentsCard(p: JSONObject?, me2: JSONObject?) {
        val rows = mutableListOf<Pair<String, (() -> Unit)?>>()
        p?.optJSONArray("moments")?.let { a ->
            for (i in 0 until a.length()) a.getJSONObject(i).let { o ->
                rows += ((if (o.optString("kind") == "mark") "📍 " else "✨ ") + o.optString("text")) to convOpener(o.optInt("conv"), o.optString("t"))
            }
        }
        for ((k, icon) in listOf("good" to "💛", "hard" to "⚡")) me2?.optJSONArray(k)?.let { a ->
            for (i in 0 until a.length()) a.getJSONObject(i).let { o ->
                val with = o.optJSONArray("with")?.let { w -> (0 until w.length()).joinToString(", ") { w.optString(it) } }?.takeIf { it.isNotBlank() }
                rows += "$icon ״${o.optString("text")}״" + (with?.let { " · עם $it" } ?: "") to convOpener(o.optInt("conv"), o.optString("t"))
            }
        }
        if (rows.isEmpty()) return
        body.gap(12)
        val c = card()
        c.head("רגעים וציטוטים")
        c.addView(text("נגיעה פותחת את השיחה", 12f, col.faint))
        list(c, "רגעים", rows)
        body.addView(c)
    }

    private fun meetingsCard(p: JSONObject) {
        val a = p.optJSONArray("meetings") ?: return
        if (a.length() == 0) return
        body.gap(12)
        val c = card()
        c.head("פגישות")
        for (i in 0 until a.length()) {
            val m = a.getJSONObject(i)
            val title = m.optString("title").takeIf { it.isNotBlank() && it != "null" } ?: "פגישה"
            c.line("📋 $title", col.ink, 15f) { startActivity(Intent(this, MeetingActivity::class.java).putExtra("id", m.optString("id"))) }
            m.optString("oneline").takeIf { it.isNotBlank() && it != "null" }?.let {
                c.addView(text(it, 13f, col.dim).apply { maxLines = 2; ellipsize = TextUtils.TruncateAt.END })
            }
        }
        body.addView(c)
    }

    /** the saved periods of this kind (offline: what can be read without the PC) */
    private fun savedList() {
        val saved = try { LocalStore.of(this).savedMe(kind) } catch (e: Exception) { emptyList() }
        val today = LocalDate.now()
        val others = saved.filter { it != MePeriods.key(start) }
        if (others.isEmpty()) return
        body.gap(16)
        body.addView(text("ניתוחים שמורים בטלפון", 13f, col.faint, true))
        val row = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        for (s in others.take(12)) {
            val d = MePeriods.parse(s)
            row.addView(chip(MePeriods.label(kind, d, today)) { go(kind, d) }, LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = px(6) })
        }
        body.addView(row)
    }

    /** open the conversation (at the line's time when known: "2026-10-29T15:06" -> seconds of the day) */
    private fun convOpener(conv: Int, t: String?): (() -> Unit)? {
        if (conv <= 0) return null
        val at = t?.let { Regex("T(\\d\\d):(\\d\\d)(?::(\\d\\d))?").find(it) }?.let { m ->
            m.groupValues[1].toInt() * 3600.0 + m.groupValues[2].toInt() * 60 + (m.groupValues[3].toIntOrNull() ?: 0)
        }
        return { startActivity(Intent(this, ConvActivity::class.java).putExtra("id", conv).apply { if (at != null) putExtra("at", at) }) }
    }
}
