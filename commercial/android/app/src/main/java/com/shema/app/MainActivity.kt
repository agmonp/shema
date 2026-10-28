package com.shema.app

import android.Manifest
import android.animation.ValueAnimator
import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

/**
 * Shema Pro Commercial Edition:
 * - Local AI voice memory, private by design (no cloud, zero subscription server costs).
 * - Annual Google Play subscription via BillingClient v7 (₪99.90/yr with 14-day free trial).
 * - Full Google Play policy compliance (Prominent Disclosure, persistent notifications, optional permissions).
 * - Onboarding desktop app download helper.
 */
class MainActivity : Activity(), BillingManager.BillingCallback {
    companion object {
        /** May another screen (meeting, voice reading) switch the microphone on by itself? Only after the prominent
         *  disclosure, with Pro (subscription, gift code or trial) and the microphone allowed; else this screen asks first. */
        fun canRecord(c: Context): Boolean = Prefs.isDisclosureAccepted(c) && BillingManager.hasAccess(c) &&
            c.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
    }
    private val ui = Handler(Looper.getMainLooper())
    private val c = object {
        val bg = Color.parseColor("#13100E"); val surface = Color.parseColor("#1C1815")
        val surface2 = Color.parseColor("#25201C"); val ink = Color.parseColor("#F4EDE5")
        val dim = Color.parseColor("#B1A597"); val faint = Color.parseColor("#958A7D")
        val accent = Color.parseColor("#EAA45E"); val accentInk = Color.parseColor("#1B130B")
        val sage = Color.parseColor("#86BBA8"); val rose = Color.parseColor("#E48A7F")
        val rec = Color.parseColor("#E5484D"); val off = Color.parseColor("#6F665C")
        val proGold = Color.parseColor("#FFD700"); val proGoldInk = Color.parseColor("#2A1E00")
    }
    private var dp = 1f
    private lateinit var orb: View
    private lateinit var orbRing: View
    private lateinit var title: TextView
    private lateinit var subtitle: TextView
    private lateinit var main: TextView
    private lateinit var checklist: LinearLayout
    private lateinit var checkCard: LinearLayout
    private lateinit var roleHome: TextView
    private lateinit var roleWear: TextView
    private lateinit var roleDesc: TextView
    private lateinit var enrollStatus: TextView
    private lateinit var enrollBtn: TextView
    private lateinit var subPill: TextView
    private lateinit var subBtn: TextView
    private lateinit var shareBtn: TextView
    private lateinit var meetBtn: TextView
    private var pendingOpen: Class<*>? = null             // open this screen once listening has started (after start()'s dialogs)
    private var pendingAt = 0L
    private var pulse: ValueAnimator? = null
    private var pcReachable: Boolean? = null

    private lateinit var billingManager: BillingManager
    private var subPriceText = "₪99.90"
    private var isSubscribed = false
    private var isTrial = true
    private var trialDaysLeft = 14

    private fun px(v: Int) = (v * dp).toInt()
    private fun round(color: Int, r: Int, stroke: Int? = null) = GradientDrawable().apply {
        setColor(color); cornerRadius = px(r).toFloat(); stroke?.let { setStroke(px(1), it) }
    }
    private fun text(t: String, size: Float, color: Int = c.ink, bold: Boolean = false) = TextView(this).apply {
        text = t; textSize = size; setTextColor(color); if (bold) typeface = Typeface.DEFAULT_BOLD
    }
    private fun button(t: String, primary: Boolean = false, onClick: () -> Unit) = TextView(this).apply {
        text = t; textSize = if (primary) 18f else 15f; gravity = Gravity.CENTER
        setTextColor(if (primary) c.accentInk else c.ink); typeface = Typeface.DEFAULT_BOLD
        background = round(if (primary) c.accent else c.surface2, 16, if (primary) null else Color.parseColor("#33FFECD6"))
        setPadding(px(16), px(if (primary) 16 else 12), px(16), px(if (primary) 16 else 12))
        isClickable = true; setOnClickListener { onClick() }
    }
    private fun card() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL; background = round(c.surface, 18, Color.parseColor("#1CFFECD6"))
        setPadding(px(16), px(14), px(16), px(14))
    }
    private fun LinearLayout.gap(h: Int) = addView(View(this@MainActivity), LinearLayout.LayoutParams(1, px(h)))

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        dp = resources.displayMetrics.density

        // Initialize Google Play In-App Billing
        billingManager = BillingManager(this, this)

        val exServer = intent?.getStringExtra("server")
        val exToken = intent?.getStringExtra("token")
        if (!exServer.isNullOrBlank() && !exToken.isNullOrBlank()) Prefs.save(this, exServer, exToken)
        intent?.getStringExtra("remote")?.let { if (it.isNotBlank()) Prefs.setRemote(this, it) }
        intent?.getStringExtra("role")?.let { if (it == "wearer" || it == "home") Prefs.setRole(this, it) }
        // installs from before the step-by-step first run already went through the old welcome
        if (Prefs.flag(this, "welcomed") && !Prefs.flag(this, "onboarded")) Prefs.setFlag(this, "onboarded")

        buildHome()
        buildSettings()
        checkPc()
        tick()

        val link = intent?.data?.toString()
        when {
            !Prefs.flag(this, "onboarded") -> { pendingLink = link; showOnboarding() }
            Prefs.parsePair(link) != null -> { showHome(); confirmPair(link!!) }
            else -> { showHome(); if (!ListenService.on && Prefs.paired(this) && Prefs.wanted(this)) start() }
        }
    }

    // ------------------------------------------------------------ screens: home, settings, first run
    private lateinit var homeView: ScrollView
    private lateinit var settingsView: ScrollView
    private var screen = "home"
    private var pendingLink: String? = null
    private lateinit var alerts: LinearLayout
    private lateinit var whoBtn: TextView
    private lateinit var todayLine: TextView
    private lateinit var connStatus: TextView
    private lateinit var connBody: LinearLayout
    private lateinit var searchBtn: TextView

    private fun page(build: LinearLayout.() -> Unit): ScrollView {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; layoutDirection = View.LAYOUT_DIRECTION_RTL
            setPadding(px(18), px(22), px(18), px(28))
        }
        root.build()
        return ScrollView(this).apply { setBackgroundColor(c.bg); addView(root) }
    }

    // the home page + a floating "undo" bar at the bottom (it must not push the page around under the finger)
    private val homeFrame by lazy { FrameLayout(this).apply { addView(homeView); addView(undoHost,
        FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.BOTTOM)) } }
    private val undoHost by lazy { FrameLayout(this).apply { setPadding(px(16), 0, px(16), px(24)) } }
    private fun showHome() { screen = "home"; (homeView.parent as? ViewGroup)?.let { if (it !== homeFrame) it.removeView(homeView) }; setContentView(homeFrame) }
    private fun pcConnected() = Prefs.paired(this) && (ListenService.lanOk || ListenService.viaTailscale || pcReachable == true)

    private fun showSettings() {
        screen = "settings"; refreshChecklist(); refreshCalls()
        connBody.visibility = if (pcConnected()) View.GONE else View.VISIBLE
        setContentView(settingsView)
    }

    @Deprecated("Activity back")
    override fun onBackPressed() {
        if (screen == "settings") showHome()
        else super.onBackPressed()
    }

    private fun buildHome() {
        homeView = page {
            // header: name, subscription, settings
            val header = LinearLayout(this@MainActivity).apply {
                orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
                addView(View(this@MainActivity).apply { background = getDrawable(R.mipmap.ic_launcher) },
                    LinearLayout.LayoutParams(px(36), px(36)))
                addView(text("שמע Pro", 21f, bold = true).apply { setPadding(px(10), 0, px(8), 0) })
                // 2026-10-17: a small quiet status, not a call to buy (the title already says "Pro")
                subPill = TextView(this@MainActivity).apply {
                    text = "ניסיון"; textSize = 11f
                    setTextColor(c.faint); background = round(c.surface2, 10)
                    setPadding(px(8), px(4), px(8), px(4))
                    isClickable = true; setOnClickListener { if (Gift.active(this@MainActivity)) showGiftInfo() else showSubscriptionDialog() }
                }
                addView(subPill)
                addView(View(this@MainActivity), LinearLayout.LayoutParams(0, 1, 1f))
                addView(text("⚙", 24f, c.dim).apply {
                    contentDescription = "הגדרות"; setPadding(px(10), px(4), px(4), px(4))
                    isClickable = true; setOnClickListener { showSettings() }
                })
            }
            addView(header)
            gap(10)

            // only when something needs the user: one card per problem, with the fix
            alerts = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.VERTICAL }
            addView(alerts)

            // 2026-10-20 review: value first. The state is one compact row (it only matters when something is wrong);
            // the screen is about what was said today.
            val statusRow = LinearLayout(this@MainActivity).apply {
                orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
                background = round(c.surface, 18, Color.parseColor("#1CFFECD6")); setPadding(px(14), px(12), px(12), px(12))
            }
            val orbBox = FrameLayout(this@MainActivity)
            orbRing = View(this@MainActivity).apply { background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(c.rec) }; alpha = 0f }
            orb = View(this@MainActivity).apply { background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(c.off) } }
            orbBox.addView(orbRing, FrameLayout.LayoutParams(px(48), px(48), Gravity.CENTER))
            orbBox.addView(orb, FrameLayout.LayoutParams(px(36), px(36), Gravity.CENTER))
            orbBox.addView(View(this@MainActivity).apply { background = getDrawable(R.drawable.ic_stat) },
                FrameLayout.LayoutParams(px(20), px(20), Gravity.CENTER))
            statusRow.addView(orbBox, LinearLayout.LayoutParams(px(48), px(48)))
            val words = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.VERTICAL; setPadding(px(10), 0, px(8), 0) }
            title = text("", 17f, bold = true)
            subtitle = text("", 13f, c.dim).apply { maxLines = 2 }
            words.addView(title); words.addView(subtitle)
            statusRow.addView(words, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            // one control: start when off, pause / resume when on (pause = nothing is recorded until resumed)
            pauseBtn = button("⏸ השהה") { if (ListenService.on) svc(ListenService.ACTION_TOGGLE) else start() }
            statusRow.addView(pauseBtn)
            addView(statusRow)
            gap(10)
            // off: one big orange call to action (the only thing that matters then)
            main = button("התחל להקשיב", primary = true) { if (ListenService.on) svc(ListenService.ACTION_TOGGLE) else start() }
            addView(main)

            // what matters today (promises, requests, meeting decisions), with done / delete right here
            briefBox = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.VERTICAL }
            addView(briefBox)
            // today's conversations: the newest three, then the whole day
            todayBox = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.VERTICAL }
            addView(todayBox)
            // "אני": how the owner spoke (from the PC's "אני" tab), day / week
            meBox = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.VERTICAL }
            addView(meBox)
            gap(12)

            val row = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.HORIZONTAL }
            searchBtn = button("🔎 חפש או שאל") { startActivity(Intent(this@MainActivity, SearchActivity::class.java)) }
            meetBtn = button("📋 הקלט פגישה") { openWhenListening(MeetingActivity::class.java) }
            row.addView(searchBtn, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            row.addView(meetBtn, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { marginStart = px(8) })
            addView(row)
            gap(8)
            whoBtn = button("מי זה?") { startActivity(Intent(this@MainActivity, TeachActivity::class.java)) }
            addView(whoBtn)
            gap(14)
            todayLine = text("", 13f, c.faint).apply { gravity = Gravity.CENTER }
            addView(todayLine)
        }
    }

    // ------------------------------------------------------------ home: today (from the PC)
    private lateinit var pauseBtn: TextView
    private lateinit var briefBox: LinearLayout
    private lateinit var todayBox: LinearLayout
    private var todayAt = 0L
    private var todayJson: String? = null

    private fun day() = java.text.SimpleDateFormat("yyyy-MM-dd", java.util.Locale.US).format(java.util.Date())

    /** Today's conversations and "what matters today" from the PC: on open, and every 2 minutes while the home is shown. */
    private fun loadToday(force: Boolean = false) {
        if (!Prefs.paired(this) || (!force && System.currentTimeMillis() - todayAt < 120_000)) return
        todayAt = System.currentTimeMillis()
        val d = day()
        thread {
            val dayJ = Net.call(this, "GET", "/home/api/day?d=$d", timeoutMs = 15000)
            val briefJ = Net.call(this, "GET", "/home/api/brief?d=$d", timeoutMs = 15000)      // PC 1.0.11+ (older: null)
            ui.post { if (!isDestroyed) drawToday(dayJ, briefJ) }
            loadMe()
        }
    }

    // ------------------------------------------------------------ home: "אני" (the owner's own speech)
    private lateinit var meBox: LinearLayout
    private var meKind = "day"
    private var meJson: String? = null

    /** /home/api/me2 (the PC's "אני" tab: tone, questions, raised voice, per person, trend); older PCs only have
     *  /home/api/me (minutes, share, pace, fillers). Called from a background thread. */
    private fun loadMe() {
        val k = meKind
        val m2 = Net.call(this, "GET", "/home/api/me2?k=$k&d=${day()}", timeoutMs = 20000)
            ?.takeIf { it.trimStart().startsWith("{") && !it.contains("\"error\"") }
        val old = if (m2 == null && k == "day") Net.call(this, "GET", "/home/api/me?d=${day()}", timeoutMs = 15000) else null
        ui.post { if (!isDestroyed && k == meKind) drawMe(m2, old) }
    }

    private fun pct(v: Double) = "${Math.round(v * 100)}%"

    private fun drawMe(m2: String?, old: String?) {
        val key = meKind + "|" + (m2 ?: "") + "|" + (old ?: "")
        if (m2 == null && old == null && meJson != null) return  // keep the last good view while the PC is away
        if (key == meJson) return
        meJson = key
        meBox.removeAllViews()
        if (m2 == null && old == null) return
        meBox.gap(12)
        val card = card()
        // title + היום / השבוע
        val head = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        head.addView(text("אני", 13f, c.faint, bold = true), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        if (m2 != null || meKind == "week") for ((k, t) in listOf("day" to "היום", "week" to "השבוע")) {
            head.addView(View(this), LinearLayout.LayoutParams(px(6), 1))
            head.addView(smallBtn(t) { if (meKind != k) { meKind = k; thread { loadMe() } } }.apply {
                if (k == meKind) { setTextColor(c.accent); background = round(c.surface2, 12, c.accent) } })
        }
        card.addView(head)
        val when_ = if (meKind == "day") "היום" else "השבוע"
        fun line(t: String, color: Int = c.ink, size: Float = 15f) { card.gap(6); card.addView(text(t, size, color)) }

        if (m2 == null) {                                          // older PC: the basic numbers only
            val o = try { org.json.JSONObject(old!!) } catch (e: Exception) { return }
            if (o.optInt("seconds") <= 0) { line("עוד לא שמעתי אותך מדבר $when_.", c.dim, 14f); meBox.addView(card); return }
            line("דיברת ${Math.round(o.optInt("seconds") / 60.0)} דק׳ ב-${o.optInt("conversations")} שיחות" +
                (if (!o.isNull("share")) " · ${pct(o.optDouble("share"))} מהדיבור" else ""), c.ink)
            if (!o.isNull("pace") && !o.isNull("pace_usual")) {
                val r = o.optDouble("pace") / o.optDouble("pace_usual")
                line(if (r > 1.08) "קצב הדיבור מהיר מהרגיל שלך" else if (r < 0.92) "קצב הדיבור איטי מהרגיל שלך" else "קצב הדיבור כרגיל", c.dim, 14f)
            }
            line("קטעת ${o.optInt("cut_others")} פעמים · קטעו אותך ${o.optInt("was_cut")}", c.dim, 14f)
            meBox.addView(card); return
        }

        val j = try { org.json.JSONObject(m2) } catch (e: Exception) { return }
        val me = j.optJSONObject("me") ?: org.json.JSONObject()
        if (me.optInt("lines") <= 0) { line("עוד לא שמעתי אותך מדבר $when_.", c.dim, 14f); meBox.addView(card); return }
        line("דיברת ${me.optDouble("minutes").let { if (it < 10) it.toString() else Math.round(it).toString() }} דק׳ ב-${me.optInt("conversations")} שיחות" +
            (if (!me.isNull("share")) " · ${pct(me.optDouble("share"))} מהדיבור" else ""), c.ink, 15f)
        // tone (classified at night on the PC); ratios as words: "a : b" reads backwards in RTL
        if (me.optInt("classified") == 0) line("הטון של המשפטים ינותח במחשב בלילה.", c.faint, 13f)
        else {
            val pos = me.optInt("pos"); val neg = me.optInt("neg")
            val tone = when {
                pos + neg < 3 -> "רוב המשפטים ניטרליים"
                neg == 0 -> "$pos משפטים חיוביים, אף לא אחד שלילי"
                pos >= neg -> "חיובי פי ${me.optDouble("ratio")} מהשלילי ($pos מול $neg)"
                else -> "יותר שלילי מחיובי: $pos משפטים חיוביים מול $neg שליליים"
            }
            line("☺ $tone", if (neg > 0 && pos < neg) c.rose else c.sage)
            if (neg > 0) line("לפי גוטמן, בקשר טוב יש פי 5 משפטים חיוביים מהשליליים.", c.faint, 12f)
        }
        // listening + voice
        val q = me.optInt("questions")
        line("❓ $q שאלות (${Math.round(100.0 * q / me.optInt("lines"))}% מהמשפטים)", c.dim, 14f)
        val raised = me.optInt("raised")
        if (raised > 0) line("🔊 הרמת קול $raised " + (if (raised == 1) "פעם" else "פעמים"), c.rose, 14f)
        val cutO = me.optInt("cut_others"); val cutM = me.optInt("was_cut")
        if (cutO + cutM > 0) line("✂ קטעת $cutO פעמים · קטעו אותך $cutM", c.dim, 14f)
        // the warm and the hard words (only what happened)
        val tags = me.optJSONObject("tags"); val he = j.optJSONObject("tag_he")
        if (tags != null && he != null) {
            val warm = listOf("praise", "thanks", "empathy").filter { tags.optInt(it) > 0 }.map { "${he.optString(it)} ${tags.optInt(it)}" }
            val hard = listOf("blame", "sarcasm", "curse").filter { tags.optInt(it) > 0 }.map { "${he.optString(it)} ${tags.optInt(it)}" }
            if (warm.isNotEmpty()) line("💛 " + warm.joinToString(" · "), c.dim, 13f)
            if (hard.isNotEmpty()) line("⚡ " + hard.joinToString(" · "), c.dim, 13f)
        }
        // with whom (the top two by sentences)
        val people = j.optJSONArray("people")
        if (people != null && people.length() > 0) {
            card.gap(8)
            for (i in 0 until minOf(2, people.length())) {
                val p = people.getJSONObject(i)
                val ps = if (!p.isNull("pos_share")) " · ${pct(p.optDouble("pos_share"))} חיובי" else ""
                val share = if (!p.isNull("my_share")) " · דיברת ${pct(p.optDouble("my_share"))} מהזמן" else ""
                card.addView(text("עם ${p.optString("name")}: ${p.optInt("lines")} משפטים$share$ps", 13f, c.dim))
            }
        }
        // trend: share of positive sentences, oldest on the left, today on the right
        val tr = j.optJSONArray("trend")
        if (tr != null && tr.length() >= 3) {
            val vals = (0 until tr.length()).map { tr.getJSONObject(it).let { o -> if (o.isNull("pos_share")) -1.0 else o.optDouble("pos_share") } }
            if (vals.count { it >= 0 } >= 2) {
                card.gap(10)
                card.addView(text(if (meKind == "day") "חיוביות ב-${vals.size} הימים האחרונים" else "חיוביות ב-${vals.size} השבועות האחרונים", 12f, c.faint))
                card.addView(object : View(this) {
                    val paint = android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG)
                    override fun onDraw(cv: android.graphics.Canvas) {
                        val n = vals.size; val w = width.toFloat() / n; val h = height.toFloat()
                        for ((i, v) in vals.withIndex()) {
                            val x = i * w + w * 0.18f
                            if (v < 0) { paint.color = c.surface2; cv.drawRect(x, h - px(2), x + w * 0.64f, h, paint); continue }
                            paint.color = if (i == n - 1) c.accent else if (v >= 0.5) c.sage else c.rose
                            cv.drawRoundRect(x, h - maxOf(px(3).toFloat(), (h * v).toFloat()), x + w * 0.64f, h, px(2).toFloat(), px(2).toFloat(), paint)
                        }
                    }
                }.apply { layoutDirection = View.LAYOUT_DIRECTION_LTR }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, px(40)))
            }
        }
        card.gap(8)
        card.addView(text("הניתוח המלא בלשונית \"אני\" במחשב", 12f, c.faint))
        meBox.addView(card)
    }

    private fun drawToday(dayJ: String?, briefJ: String?) {
        val key = (dayJ ?: "") + "|" + (briefJ ?: "")
        if (dayJ == null && todayJson != null) return            // keep the last good view while the PC is away
        if (key == todayJson) return
        todayJson = if (dayJ == null) null else key
        briefBox.removeAllViews(); todayBox.removeAllViews()
        // what matters today
        val items = try { org.json.JSONObject(briefJ ?: "{}").optJSONArray("items") } catch (e: Exception) { null }
        val acts = mutableListOf<org.json.JSONObject>()
        if (items != null) for (i in 0 until items.length()) items.getJSONObject(i).let { if (it.optString("kind") == "task" || it.optString("kind") == "decision") acts += it }
        if (acts.isNotEmpty()) {
            briefBox.gap(12)
            val card = card()
            card.addView(text("חשוב היום", 13f, c.faint, bold = true))
            for (it in acts.take(4)) {
                card.gap(8)
                val sure = it.optBoolean("sure", true)
                val who = it.optString("who").takeIf { w -> w.isNotBlank() && w != "null" }
                val label = (if (it.optString("kind") == "decision") "הוחלט" else if (it.optString("item_kind") == "request") "בקשה" else "משימה") + (if (sure) "" else "?")
                card.addView(text("$label · " + (if (who != null) "$who: " else "") + it.optString("text") +
                    (it.optString("due").takeIf { d -> d.isNotBlank() && d != "null" }?.let { d -> " ($d)" } ?: ""), 15f, c.ink).apply {
                    isClickable = true; setOnClickListener { _ -> openConvAt(it) } })
                val btns = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; setPadding(0, px(4), 0, 0) }
                btns.addView(smallBtn("✓ בוצע") { briefAct(it, "done") })
                btns.addView(View(this), LinearLayout.LayoutParams(px(6), 1))
                btns.addView(smallBtn("✕ מחק") { briefAct(it, "del") })
                if (it.has("id") && !it.isNull("id")) {           // a reminder only when the user asks for it on this item
                    val at = it.optString("remind_at").takeIf { r -> it.has("remind_at") && !it.isNull("remind_at") && r.isNotBlank() }
                    btns.addView(View(this), LinearLayout.LayoutParams(px(6), 1))
                    btns.addView(smallBtn(if (at != null) "🔔 " + Reminders.label(at) else "🔔 הזכר לי") { remindPick(it, at) }.apply {
                        if (at != null) { setTextColor(c.accent); background = round(c.surface2, 12, c.accent) } })
                }
                card.addView(btns)
            }
            briefBox.addView(card)
        }
        // today's conversations
        todayBox.gap(12)
        val convs = try { org.json.JSONObject(dayJ ?: "{}").optJSONArray("conversations") } catch (e: Exception) { null }
        val card = card()
        if (dayJ == null) {
            card.addView(text("השיחות של היום יופיעו כאן כשהמחשב זמין.", 14f, c.dim))
        } else if (convs == null || convs.length() == 0) {
            card.addView(text("עוד אין שיחות היום", 15f, c.ink, bold = true))
            card.addView(text("שמע מקשיב. כל שיחה מופיעה כאן כמה דקות אחרי שהיא נגמרת: סיכום, מי דיבר ומה סוכם.", 14f, c.dim))
        } else {
            card.addView(text("היום · ${convs.length()} שיחות", 13f, c.faint, bold = true))
            for (i in convs.length() - 1 downTo maxOf(0, convs.length() - 3)) {
                val k = convs.getJSONObject(i)
                card.gap(8)
                val item = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; isClickable = true
                    setOnClickListener { startActivity(Intent(this@MainActivity, ConvActivity::class.java).putExtra("id", k.getInt("id"))) } }
                item.addView(text(TimelineView.ltr(k.optString("start").drop(11).take(5)) + " · " +
                    (k.optString("topic").takeIf { it.isNotBlank() && it != "null" } ?: "שיחה"), 15f, c.ink, bold = true))
                k.optString("summary").takeIf { it.isNotBlank() && it != "null" }?.let { item.addView(text(it, 13f, c.dim).apply { maxLines = 2 }) }
                card.addView(item)
            }
            card.gap(10)
            card.addView(text("כל היום וציר הזמן ›", 14f, c.accent, bold = true).apply {
                isClickable = true; setOnClickListener { startActivity(Intent(this@MainActivity, DayActivity::class.java)) } })
        }
        todayBox.addView(card)
    }

    private fun smallBtn(t: String, onClick: () -> Unit) = TextView(this).apply {
        text = t; textSize = 13f; setTextColor(c.dim); background = round(c.surface2, 12, Color.parseColor("#33FFECD6"))
        setPadding(px(12), px(6), px(12), px(6)); isClickable = true; setOnClickListener { onClick() }
    }

    private fun openConvAt(it: org.json.JSONObject) {
        val cid = it.optInt("conv_id"); if (cid <= 0) return
        startActivity(Intent(this, ConvActivity::class.java).putExtra("id", cid))
    }

    /** "✓ בוצע" / "✕ מחק" on a promise (tasks) or a meeting decision, with undo (same API as the PC's day page). */
    private fun briefAct(it: org.json.JSONObject, a: String) {
        val isTask = it.has("id") && !it.isNull("id")
        val was = if (isTask) (if (it.optBoolean("sure", true)) "confirmed" else "open") else "open"
        fun set(s: String) = if (isTask) Net.call(this, "POST", "/home/api/task", org.json.JSONObject().put("id", it.getInt("id")).put("state", s))
            else Net.call(this, "POST", "/home/api/decision", org.json.JSONObject().put("conv_id", it.optInt("conv_id")).put("text", it.optString("text")).put("state", s))
        val to = if (a == "done") "done" else if (isTask) "dismissed" else "deleted"
        thread {
            val r = set(to)
            if (r != null && isTask) Reminders.remove(this, it.getInt("id"))     // done / deleted: no reminder (undo brings it back on the next sync)
            ui.post {
                if (r == null) { Toast.makeText(this, "המחשב לא זמין, נסה שוב", Toast.LENGTH_SHORT).show(); return@post }
                loadToday(force = true)
                undoBar(if (a == "done") "סומן כבוצע" else "נמחק מהרשימה") { thread { set(was); ui.post { loadToday(force = true) } } }
            }
        }
    }

    /** "🔔 הזכר לי": tomorrow 09:00 / the time that was said / a chosen time / cancel. Sets remind_at on the PC (which
     *  keeps the list) and schedules it here at once. */
    private fun remindPick(it: org.json.JSONObject, at: String?) {
        val tm = Reminders.tomorrow9()
        val opts = mutableListOf<Pair<String, String?>>("מחר ב-09:00" to tm)
        it.optString("due_at").takeIf { d -> it.has("due_at") && d != tm && Reminders.atMs(d) > System.currentTimeMillis() }?.let { d ->
            opts += "כמו שנאמר: ${it.optString("due")} (${Reminders.label(d)})" to d }
        opts += "בחר זמן…" to "pick"
        if (at != null) opts += "בטל תזכורת" to null
        AlertDialog.Builder(this).setTitle(if (at != null) "🔔 תזכורת ${Reminders.label(at)}" else "להזכיר לך?")
            .setItems(opts.map { o -> o.first }.toTypedArray()) { _, k ->
                val v = opts[k].second
                if (v == "pick") pickTime(at ?: tm) { t -> remindSet(it, t) } else remindSet(it, v)
            }.setNegativeButton("סגור", null).show()
    }

    private fun pickTime(start: String, done: (String) -> Unit) {
        val cal = java.util.Calendar.getInstance().apply { timeInMillis = Reminders.atMs(start).takeIf { it > 0 } ?: System.currentTimeMillis() }
        android.app.DatePickerDialog(this, { _, y, m, d ->
            android.app.TimePickerDialog(this, { _, h, mi ->
                cal.set(y, m, d, h, mi, 0); done(Reminders.fmtAt(cal.timeInMillis))
            }, cal.get(java.util.Calendar.HOUR_OF_DAY), cal.get(java.util.Calendar.MINUTE), true).show()
        }, cal.get(java.util.Calendar.YEAR), cal.get(java.util.Calendar.MONTH), cal.get(java.util.Calendar.DAY_OF_MONTH))
            .apply { datePicker.minDate = System.currentTimeMillis() - 1000 }.show()
    }

    private fun remindSet(it: org.json.JSONObject, at: String?) {
        thread {
            val err = Reminders.set(this, it, at)
            ui.post {
                Toast.makeText(this, err ?: if (at != null) "🔔 אזכיר לך ${Reminders.label(at)}" else "התזכורת בוטלה", Toast.LENGTH_SHORT).show()
                if (err == null) loadToday(force = true)
            }
        }
    }

    /** a short "done · undo" line under the header for 8 seconds */
    private var undoView: View? = null
    private fun undoBar(msg: String, undo: () -> Unit) {
        undoHost.removeAllViews()
        val v = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
            background = round(Color.parseColor("#3A322B"), 14, c.accent); setPadding(px(14), px(12), px(10), px(12)); elevation = px(6).toFloat()
            layoutDirection = View.LAYOUT_DIRECTION_RTL
            addView(text(msg, 14f, c.ink), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            addView(text("בטל", 14f, c.accent, bold = true).apply { setPadding(px(12), px(4), px(4), px(4)); isClickable = true
                setOnClickListener { undoHost.removeAllViews(); undoView = null; undo() } })
        }
        undoView = v; undoHost.addView(v)
        ui.postDelayed({ if (undoView === v) { undoHost.removeAllViews(); undoView = null } }, 8000)
    }

    private fun section(parent: LinearLayout, title: String) {
        parent.gap(18)
        parent.addView(text(title, 13f, c.faint, bold = true))
        parent.gap(6)
    }

    private fun buildSettings() {
        settingsView = page {
            val top = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
            top.addView(text("→", 24f, c.dim).apply {
                contentDescription = "חזרה"; setPadding(px(4), 0, px(12), 0); isClickable = true; setOnClickListener { showHome() } })
            top.addView(text("הגדרות", 21f, bold = true))
            addView(top)

            // connection to the PC
            section(this, "חיבור למחשב")
            val connCard = card()
            // closed while the phone is connected: one line; it opens by itself when the PC is not connected
            connStatus = text("", 14f, c.ink).apply { isClickable = true; setOnClickListener {
                connBody.visibility = if (connBody.visibility == View.GONE) View.VISIBLE else View.GONE } }
            connCard.addView(connStatus)
            connBody = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.VERTICAL; visibility = View.GONE }
            connCard.addView(connBody)
            val conn = connBody
            conn.gap(10)
            val server = EditText(this@MainActivity).apply { setText(Prefs.server(this@MainActivity)); setTextColor(c.ink)
                inputType = InputType.TYPE_TEXT_VARIATION_URI; textDirection = View.TEXT_DIRECTION_LTR }
            val remote = EditText(this@MainActivity).apply { setText(Prefs.remote(this@MainActivity)); setTextColor(c.ink)
                hint = "http://100.x.y.z:8770"; setHintTextColor(c.faint)
                inputType = InputType.TYPE_TEXT_VARIATION_URI; textDirection = View.TEXT_DIRECTION_LTR }
            val token = EditText(this@MainActivity).apply { setText(Prefs.token(this@MainActivity)); setTextColor(c.ink)
                inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD; textDirection = View.TEXT_DIRECTION_LTR }
            conn.addView(text("כתובת בבית", 12f, c.faint)); conn.addView(server)
            conn.addView(text("כתובת מרחוק (Tailscale של המחשב)", 12f, c.faint)); conn.addView(remote)
            conn.addView(text("קוד גישה", 12f, c.faint)); conn.addView(token)
            conn.gap(8)
            conn.addView(button("שמור ובדוק חיבור") {
                Prefs.save(this@MainActivity, server.text.toString(), token.text.toString())
                Prefs.setRemote(this@MainActivity, remote.text.toString()); checkPc()
            })
            conn.gap(8)
            pairBtn = button("סרוק QR מהמחשב (חיבור מחדש או מחשב חדש)") { scanPair() }
            conn.addView(pairBtn)
            conn.gap(8)
            val pcBtns = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.HORIZONTAL }
            pcBtns.addView(button("שלח קישור למחשב") { shareDesktopDownload() },
                LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { marginEnd = px(8) })
            pcBtns.addView(button("הוראות התקנה") { showDesktopGuide() }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            conn.addView(pcBtns)
            addView(connCard)
            serverField = server; remoteField = remote; tokenField = token

            // this phone
            section(this, "הטלפון הזה")
            val roleCard = card()
            val roleRow = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.HORIZONTAL }
            roleWear = button("טלפון אישי") { setRole("wearer") }
            roleHome = button("טלפון בית") { setRole("home") }
            roleRow.addView(roleWear, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { marginEnd = px(8) })
            roleRow.addView(roleHome, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            roleCard.addView(roleRow)
            roleDesc = text("", 13f, c.dim).apply { setPadding(0, px(8), 0, 0) }
            roleCard.addView(roleDesc)
            addView(roleCard)
            gap(10)
            val calls = card()
            calls.addView(text("שיחות טלפון", 14f, c.ink, bold = true))
            callStatus = text("", 14f, c.dim)
            calls.addView(callStatus)
            callBtn = button("") { toggleCalls() }
            calls.gap(8)
            calls.addView(callBtn)
            callMore = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.HORIZONTAL; setPadding(0, px(8), 0, 0) }
            callMore.addView(button("פתח את החייגן") { openDialerSettings() },
                LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { marginEnd = px(8) })
            callMore.addView(button("בחר תיקייה") { pickCallFolder() }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            calls.addView(callMore)
            addView(calls)

            // my voice
            section(this, "הקול שלי")
            val enrollCard = card()
            enrollStatus = text("", 14f, c.ink)
            enrollCard.addView(enrollStatus)
            enrollBtn = button("ללמד את הקול שלי (25 שניות)") { openEnroll(false) }
            enrollCard.gap(8)
            enrollCard.addView(enrollBtn)
            addView(enrollCard)

            // privacy
            section(this, "פרטיות")
            addView(button("אזורים פרטיים · הוסף את המקום הנוכחי") { privacyMenu() })
            gap(8)
            addView(button("מילים פרטיות ביומן") { editCalWords() })

            // permissions: every item with its state; what is missing has a button
            section(this, "הרשאות וסוללה")
            checkCard = card()
            checklist = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.VERTICAL }
            checkCard.addView(checklist)
            addView(checkCard)

            // subscription
            section(this, "מנוי")
            subBtn = button("שמע Pro · מנוי וקוד מתנה") { if (Gift.active(this@MainActivity)) showGiftInfo() else showSubscriptionDialog() }
            addView(subBtn)
            gap(8)
            shareBtn = button("💌 שתף את שמע עם חבר") { shareApp() }
            addView(shareBtn)

            section(this, "")
            addView(button("מדיניות פרטיות") { openPrivacyPolicy() })
            gap(8)
            addView(button("כבה את שמע לגמרי") {
                AlertDialog.Builder(this@MainActivity).setTitle("לכבות את שמע?")
                    .setMessage("שמע יפסיק להקשיב עד שתפעיל אותו שוב במסך הראשי. אם רצית רק הפסקה, עדיף \"השהה\".")
                    .setPositiveButton("כבה") { _, _ -> stop(); showHome() }.setNegativeButton("בטל", null).show()
            }.apply { setTextColor(c.rose) })
        }
    }

    // ------------------------------------------------------------ first run, one step at a time
    private var obStep = 0
    // no voice reading here: tagging "זה אני" / "מי זה?" teaches the voices; the reading stays in the settings.
    // 2026-10-20 review: microphone + notifications in one step, and no "which phone?" step (personal is the
    // default and the common case; a home phone is chosen in the settings)
    private val obSteps = listOf("welcome", "perms", "battery", "pc")

    private fun stepNeeded(s: String) = when (s) {
        "welcome" -> !Prefs.isDisclosureAccepted(this)
        "perms" -> checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED ||
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        "battery" -> !batteryOk()
        "pc" -> !Prefs.paired(this)
        "role" -> !Prefs.flag(this, "role_chosen")
        "voice" -> !Prefs.flag(this, "voice_known") && !Prefs.flag(this, "enroll_later")
        else -> false
    }

    private var obList = listOf<String>()

    private fun showOnboarding() {
        screen = "onboarding"
        obList = obSteps.filter { stepNeeded(it) }
        obStep = 0
        renderStep()
    }

    private fun nextStep() { obStep++; renderStep() }

    private fun renderStep() {
        while (obStep < obList.size && !stepNeeded(obList[obStep])) obStep++     // done meanwhile (paired, allowed in settings)
        if (obStep >= obList.size) { finishOnboarding(); return }
        val s = obList[obStep]
        // opened from the PC's pairing link (phone camera on the QR): no second scan, just confirm it
        if (s == "pc" && Prefs.parsePair(pendingLink) != null) ui.post {
            val l = pendingLink; pendingLink = null; if (l != null && screen == "onboarding") confirmPair(l) }
        setContentView(page {
            gap(30)
            addView(text("שלב ${obStep + 1} מתוך ${obList.size}", 13f, c.faint))
            gap(6)
            fun body(t: String, d: String) {
                addView(text(t, 24f, bold = true)); gap(12)
                addView(text(d, 16f, c.dim).apply { setLineSpacing(0f, 1.2f) }); gap(28)
            }
            when (s) {
                "welcome" -> {
                    body("ברוך הבא לשמע", "שמע מקשיב ברקע ושומר רק קטעים שיש בהם דיבור. ההקלטות נשלחות רק למחשב שלך בבית, " +
                        "ושם הן מתומללות ומסוכמות. שום דבר לא עולה לענן.\n\nלפני שמתחילים: ספר לאנשים סביבך שאתה מקליט. " +
                        "אתה אחראי לקבל את הסכמתם. אסור להקליט שיחה שאינך משתתף בה.\n\n" +
                        "כל עוד שמע מקשיב מופיעה התראה קבועה. בכל רגע אפשר ללחוץ בה \"השהה\" או \"עצור\".")
                    addView(button("מסכים, בוא נתחיל", primary = true) {
                        Prefs.setDisclosureAccepted(this@MainActivity, true); Prefs.setFlag(this@MainActivity, "welcomed"); nextStep() })
                    gap(10)
                    addView(button("לא עכשיו") { finishOnboarding() })     // no microphone is asked for; start() asks again later
                    gap(10)
                    addView(button("מדיניות הפרטיות") { openPrivacyPolicy() })
                }
                "perms" -> {
                    body("מיקרופון והתראה", "מיקרופון: כדי לשמוע שיחות. נשמרים רק קטעים עם דיבור, והם נשלחים רק למחשב שלך.\n\n" +
                        "התראה: כל עוד שמע מקשיב היא מופיעה, ומשם משהים בלחיצה אחת.")
                    addView(button("אפשר", primary = true) {
                        requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO, Manifest.permission.POST_NOTIFICATIONS)
                            .filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }.toTypedArray(), 11) })
                }
                "battery" -> {
                    body("להמשיך להקשיב", "בלי זה, הטלפון סוגר את שמע אחרי זמן מה כדי לחסוך סוללה, וחלקים מהיום לא מוקלטים. " +
                        "במסך הבא בחר \"אפשר\".")
                    addView(button("אפשר", primary = true) { askBattery() })
                }
                "pc" -> {
                    body("חיבור למחשב", "שמע מתמלל ומסכם במחשב שלך בבית. במחשב, פתח את מסך שמע ולחץ \"חבר טלפון\", ואז סרוק את הקוד.")
                    addView(button("סרוק QR מהמחשב", primary = true) { scanPair() })
                    gap(10)
                    addView(button("עוד אין לי את התוכנה במחשב · שלח לי קישור") { shareDesktopDownload() })
                    gap(10)
                    addView(button("איך מתקינים?") { showDesktopGuide() })
                }
                "role" -> {
                    body("איזה טלפון זה?", "טלפון אישי יוצא איתך ומקליט גם בחוץ. טלפון בית נשאר בבית ומקליט רק שם.")
                    addView(button("טלפון אישי (שלי)", primary = true) { setRole("wearer"); Prefs.setFlag(this@MainActivity, "role_chosen"); nextStep() })
                    gap(10)
                    addView(button("טלפון בית") { setRole("home"); Prefs.setFlag(this@MainActivity, "role_chosen"); nextStep() })
                }
                "voice" -> {
                    body("שמע ילמד את הקול שלך", "קרא בקול טקסט קצר (25 שניות), וכל משפט שלך יופיע בשם שלך. אפשר גם אחר כך, מההגדרות.")
                    addView(button("ללמד עכשיו", primary = true) { Prefs.setFlag(this@MainActivity, "enroll_later"); finishOnboarding(); openEnroll(true) })
                    gap(10)
                    addView(button("אחר כך") { Prefs.setFlag(this@MainActivity, "enroll_later"); nextStep() })
                }
            }
            gap(20)
            if (s != "welcome" && s != "perms") addView(text("דלג", 15f, c.faint).apply {
                gravity = Gravity.CENTER; setPadding(0, px(10), 0, px(10)); isClickable = true; setOnClickListener { nextStep() } })
        })
    }

    private fun finishOnboarding() {
        Prefs.setFlag(this, "onboarded"); Prefs.setFlag(this, "welcomed")
        showHome()
        val link = pendingLink; pendingLink = null
        if (Prefs.parsePair(link) != null) confirmPair(link!!)
        else if (!ListenService.on && Prefs.paired(this)) start()
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        intent?.data?.toString()?.let { if (Prefs.parsePair(it) != null) confirmPair(it) }
    }

    override fun onResume() {
        super.onResume()
        if (screen == "onboarding" && obStep < obList.size && !stepNeeded(obList[obStep])) nextStep()   // back from the battery screen
        if (screen == "home") loadToday(force = true)
        refreshChecklist()
        refreshCalls()
        billingManager.checkActiveSubscriptions()
    }

    // ------------------------------------------------------------ phone calls
    private lateinit var callStatus: TextView
    private lateinit var callBtn: TextView
    private lateinit var callMore: LinearLayout

    private fun refreshCalls() {
        val on = CallImport.enabled(this)
        callBtn.text = if (on) "כבה ייבוא שיחות" else "ייבא הקלטות שיחה אוטומטית"
        callMore.visibility = if (on) View.VISIBLE else View.GONE
        callStatus.text = when {
            !on -> "אנדרואיד לא נותן לאף אפליקציה לשמוע שיחת טלפון. אפשר להפעיל הקלטת שיחות בחייגן של הטלפון, ושמע ייקח כל הקלטה חדשה לניתוח במחשב (מי דיבר, תמלול, סיכום)."
            CallImport.tree(this).isEmpty() && !CallImport.permOk(this) -> "חסרה הרשאה לקרוא קבצי שמע. לחץ שוב על הכפתור."
            CallImport.imported(this) > 0 -> "פעיל · יובאו ${CallImport.imported(this)} שיחות · אחרונה: ${CallImport.last(this)}"
            else -> "פעיל · עוד לא נמצאה הקלטת שיחה. ודא שבחייגן מופעל \"הקלטת שיחות אוטומטית\" (הגדרות החייגן ← הקלטת שיחות). " +
                "אם ההקלטות נשמרות בתיקייה אחרת, לחץ \"בחר תיקייה\"."
        }
    }

    private fun toggleCalls() {
        if (CallImport.enabled(this) && (CallImport.permOk(this) || CallImport.tree(this).isNotEmpty())) {
            CallImport.setEnabled(this, false); refreshCalls(); return
        }
        CallImport.setEnabled(this, true)
        if (!CallImport.permOk(this) && CallImport.tree(this).isEmpty()) requestPermissions(arrayOf(CallImport.permission), 8)
        else scanCallsNow()
        refreshCalls()
    }

    private fun scanCallsNow() = Thread {
        val n = try { CallImport.scan(this, File(filesDir, "queue").apply { mkdirs() }) } catch (e: Exception) { 0 }
        runOnUiThread {
            refreshCalls()
            if (n > 0) Toast.makeText(this, "נמצאו $n הקלטות שיחה, נשלחות לניתוח", Toast.LENGTH_LONG).show()
        }
    }.start()

    private fun openDialerSettings() {
        // no standard intent for "call recording settings": open the dialer, the user goes to its settings
        try { startActivity(Intent(Intent.ACTION_DIAL)) } catch (e: Exception) { }
        Toast.makeText(this, "בחייגן: ⋮ ← הגדרות ← הקלטת שיחות ← הקלט את כל השיחות", Toast.LENGTH_LONG).show()
    }

    private fun pickCallFolder() {
        try { startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT_TREE), 9) }
        catch (e: Exception) { Toast.makeText(this, "לא נפתח בוחר התיקיות", Toast.LENGTH_LONG).show() }
    }

    // ------------------------------------------------------------ Google Play Billing Callbacks
    override fun onSubscriptionStatusChanged(isSubscribed: Boolean, isGift: Boolean, isTrial: Boolean, daysRemaining: Int) {
        this.isSubscribed = isSubscribed
        this.isTrial = isTrial
        this.trialDaysLeft = daysRemaining

        // quiet in every state; only the expired one gets the accent colour (still no fill, no red)
        subPill.background = round(c.surface2, 10)
        subPill.setTextColor(c.faint)
        subPill.contentDescription = null
        when {
            isSubscribed -> subPill.text = "פעיל ✓"
            isGift -> subPill.text = "פעיל 🎁"
            isTrial -> subPill.text = "ניסיון · עוד $daysRemaining ימים"
            else -> { subPill.text = "שדרוג"; subPill.setTextColor(c.accent); subPill.background = round(c.surface2, 10, c.accent) }
        }
        subPill.contentDescription = "מנוי: " + subPill.text
        subBtn.text = when {
            isSubscribed || isGift -> "מנוי: Pro פעיל"
            isTrial -> "מנוי: ניסיון, עוד $daysRemaining ימים · הירשם או קוד מתנה"
            else -> "מנוי: שדרג ל-Pro · קוד מתנה"
        }
        shareBtn.text = if (isSubscribed || isGift) "💌 שתף את שמע עם חבר" else "💌 הזמן מישהו להתנסות בשמע"
    }

    override fun onProductPriceLoaded(priceFormatted: String, billingPeriod: String) {
        subPriceText = priceFormatted
    }

    override fun onBillingError(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
    }

    private fun showSubscriptionDialog() {
        val msg = "שמע Pro פועל מקומית לחלוטין יחד עם המחשב שלך בבית — ללא ענן ובפרטיות מוחלטת.\n\n" +
            "⭐ מה מקבלים במנוי Pro:\n" +
            "• תמלול עברית מדויק וללא הגבלת דקות\n" +
            "• סיכומי שיחות חכמים, משימות וציר זמן אישי\n" +
            "• זיהוי דוברים חכם ולימוד קולות\n" +
            "• אפס ענן — כל המידע וההקלטות נשארים אצלך\n\n" +
            "מחיר מנוי שנתי: $subPriceText / שנה (פחות מ-₪8.5 לחודש). ניתן לבטל בכל עת דרך Google Play."
        // the 14-day trial starts by itself on the first day: say so, and do not offer to "start" it again
        val trial = BillingManager.trialActive(this) && !Prefs.isSubscribed(this) && !Gift.active(this)
        val left = ((BillingManager.TRIAL_MS - (System.currentTimeMillis() - Prefs.firstInstallTime(this))) / 86_400_000L + 1).toInt()
        val top = if (trial) "✓ תקופת הניסיון כבר פעילה: נשארו עוד $left ימים. לא צריך לעשות כלום.\n" +
            "אפשר להירשם עכשיו או בסוף הניסיון.\n\n" else ""

        val giftLink = text("🎁 יש לי קוד מתנה", 15f, c.accent, bold = true).apply {
            setPadding(px(24), px(4), px(24), px(4)); isClickable = true }
        // before paying: a quiet invitation (never a condition for anything)
        val invite = text("רוצה שגם מישהו אחר יכיר את שמע? הזמן אותו להתנסות", 13f, c.dim).apply {
            setPadding(px(24), px(10), px(24), px(4)); isClickable = true; setOnClickListener { shareApp() } }
        val extra = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; addView(giftLink)
            if (!Prefs.isSubscribed(this@MainActivity) && !Gift.active(this@MainActivity)) addView(invite) }
        val d = AlertDialog.Builder(this)
            .setTitle("שמע Pro — זיכרון קולי אישי")
            .setMessage(top + msg)
            .setView(extra)
            .setPositiveButton(if (trial) "הירשם עכשיו" else "הירשם ל-Pro") { _, _ ->
                billingManager.launchBillingFlow(this)
            }
            .setNeutralButton("שחזר רכישות") { _, _ ->
                billingManager.checkActiveSubscriptions()
                Toast.makeText(this, "בודק מנוי קיים מול Google Play...", Toast.LENGTH_SHORT).show()
            }
            .setNegativeButton("סגור", null)
            .show()
        giftLink.setOnClickListener { d.dismiss(); showGiftDialog() }
    }

    /** Free Pro for a friend: they send their phone code, the owner sends back a code signed for that phone
     *  (commercial/scripts/gift.ps1), and it works on that phone only. */
    private fun showGiftDialog() {
        val phone = Gift.phoneCode(this)
        val box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(px(22), px(8), px(22), 0) }
        box.addView(text("1. שלח את קוד הטלפון שלך למי שנותן לך את המתנה:", 14f, c.dim))
        box.addView(text(phone, 26f, c.accent, bold = true).apply {
            gravity = Gravity.CENTER; textDirection = View.TEXT_DIRECTION_LTR; setTextIsSelectable(true); setPadding(0, px(8), 0, px(8)) })
        box.addView(button("שלח את קוד הטלפון") {
            startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain")
                .putExtra(Intent.EXTRA_TEXT, "קוד הטלפון שלי בשמע Pro: $phone"), "שלח את קוד הטלפון"))
        })
        box.gap(16)
        box.addView(text("2. קיבלת קוד מתנה? העתק את ההודעה והדבק אותה כאן:", 14f, c.dim))
        val field = EditText(this).apply {
            hint = "SHEMA-…"; setTextColor(c.ink); setHintTextColor(c.faint); textSize = 13f
            textDirection = View.TEXT_DIRECTION_LTR; maxLines = 3 }
        // copied from WhatsApp just before: fill it in
        val clip = try {
            (getSystemService(Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager).primaryClip?.getItemAt(0)?.coerceToText(this)
        } catch (e: Exception) { null }
        Gift.find(clip)?.let { field.setText(it) }
        box.addView(field)
        val d = AlertDialog.Builder(this).setTitle("🎁 קוד מתנה").setView(box)
            .setPositiveButton("הפעל", null).setNegativeButton("סגור", null).show()
        d.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
            val why = when (Gift.check(this, field.text.toString())) {
                is Gift.Result.Ok -> {
                    Prefs.setGift(this, Gift.find(field.text)!!)
                    billingManager.evaluateEntitlement()
                    d.dismiss(); showGiftInfo(fresh = true); return@setOnClickListener
                }
                Gift.Result.OtherPhone -> "הקוד הזה נוצר לטלפון אחר. שלח את קוד הטלפון שלך ($phone) ובקש קוד חדש."
                Gift.Result.Expired -> "התוקף של הקוד הזה כבר עבר."
                Gift.Result.Revoked -> "המתנה לטלפון הזה בוטלה."
                Gift.Result.Invalid -> "זה לא קוד מתנה תקין. ודא שהעתקת את כל ההודעה."
            }
            Toast.makeText(this, why, Toast.LENGTH_LONG).show()
        }
    }

    private fun showGiftInfo(fresh: Boolean = false) {
        val g = Gift.info(this) ?: return
        val until = if (g.until == 0L) "ללא הגבלת זמן" else "עד " +
            java.text.SimpleDateFormat("dd/MM/yyyy", java.util.Locale.US).apply { timeZone = java.util.TimeZone.getTimeZone("UTC") }
                .format(java.util.Date(g.until - 1))
        AlertDialog.Builder(this).setTitle(if (fresh) "🎁 שמע Pro פתוח!" else "🎁 שמע Pro במתנה")
            .setMessage("שמע Pro במתנה" + (if (g.name.isNotBlank()) " ל${g.name}" else "") + ", $until.\nהמתנה שייכת לטלפון הזה בלבד.")
            .setPositiveButton("מעולה") { _, _ -> if (fresh && !ListenService.on && Prefs.paired(this)) start() }
            .show()
    }

    /** "Share Shema with a friend": the Android share sheet with a short message and the Play link. */
    private fun shareApp() {
        val url = "https://play.google.com/store/apps/details?id=app.shema.listener"
        val msg = "אני משתמש בשמע: זיכרון של השיחות שלי, בעברית, ונשאר אצלי בבית בלי ענן. שווה לנסות:\n$url"
        startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain")
            .putExtra(Intent.EXTRA_TEXT, msg), "שתף את שמע"))
    }

    // ------------------------------------------------------------ Desktop Onboarding & Helper
    private fun shareDesktopDownload() {
        val url = getString(R.string.desktop_download_url)
        val text = "הורדת תוכנת שמע למחשב (ללא ענן): $url\nהתקן על מחשב Windows והפעל את Install.bat."
        val sendIntent = Intent().apply {
            action = Intent.ACTION_SEND
            putExtra(Intent.EXTRA_TEXT, text)
            type = "text/plain"
        }
        startActivity(Intent.createChooser(sendIntent, "שלח קישור למחשב"))
    }

    private fun showDesktopGuide() {
        val msg = "כיצד לחבר את שמע למחשב ב-3 צעדים:\n\n" +
            "1. שלח לעצמך את הקישור ופתח אותו במחשב Windows.\n" +
            "2. פתח את קובץ ה-ZIP והפעל את Install.bat (ההתקנה מתקינה את מודלי ה-AI המקומיים).\n" +
            "3. בסיום יפתח מסך שמע בדפדפן. לחץ על 'חבר טלפון' וסרוק את קוד ה-QR עם האפליקציה הזו.\n\n" +
            "הכל עובד ברשת הביתית ללא שום שרת ענן!"
        AlertDialog.Builder(this).setTitle("התקנת תוכנת המחשב").setMessage(msg).setPositiveButton("הבנתי", null).show()
    }

    private fun openPrivacyPolicy() {
        startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://github.com/agmonp/shema#פרטיות")))
    }

    // ------------------------------------------------------------ Google Play Prominent Disclosure
    private fun showProminentDisclosure(onAccepted: () -> Unit) {
        val msg = "שמע Pro מקליט ברקע קטעי דיבור בלבד כדי לתמלל, לזהות דוברים ולסכם את השיחות שלך.\n\n" +
            "• ההקלטות והעיבוד נעשים בטלפון ובמחשב האישי שלך בלבד.\n" +
            "• שום הקלטה, תמלול או מידע אישי אינם נשלחים לענן של שמע או לצד שלישי.\n" +
            "• כל עוד שמע מקשיב מופיעה התראה קבועה, וממנה אפשר להשהות או לעצור.\n" +
            "• אתה אחראי ליידע את האנשים סביבך ולקבל את הסכמתם. אסור להקליט שיחה שאינך משתתף בה.\n\n" +
            "האם לאשר את הפעלת המיקרופון?"

        AlertDialog.Builder(this)
            .setTitle("האזנה לקולך והגנה על הפרטיות")
            .setMessage(msg)
            .setCancelable(false)
            .setPositiveButton("אני מסכים/ה") { _, _ ->
                Prefs.setDisclosureAccepted(this, true)
                onAccepted()
            }
            .setNegativeButton("לא עכשיו", null)
            .setNeutralButton("מדיניות הפרטיות") { _, _ -> openPrivacyPolicy() }
            .show()
    }

    // ------------------------------------------------------------ first run + pairing
    private var serverField: EditText? = null
    private var remoteField: EditText? = null
    private var tokenField: EditText? = null
    private lateinit var pairBtn: TextView

    private fun welcome(link: String?) {
        val msg = "שמע מקשיב ברקע ושומר רק קטעים שיש בהם דיבור. השקט והרעש נזרקים כבר בטלפון.\n\n" +
            "ההקלטות נשלחות רק למחשב שלך, בבית (או דרך Tailscale). שם הן מתומללות ומנותחות. " +
            "שום דבר לא עולה לענן, ואין לנו שרת.\n\n" +
            "לפני שמתחילים: ספר לבני הבית שאתה מקליט. הקלטה של שיחה שאינך משתתף בה עלולה להיות אסורה בחוק.\n\n" +
            "אפשר תמיד: השהה, פרטי לשעה, אזורים פרטיים, או כבה."
        AlertDialog.Builder(this).setTitle("ברוך הבא לשמע Pro").setMessage(msg).setCancelable(false)
            .setPositiveButton("הבנתי") { _, _ ->
                Prefs.setFlag(this, "welcomed")
                when {
                    Prefs.parsePair(link) != null -> confirmPair(link!!)
                    !Prefs.paired(this) -> scanPair()
                    !ListenService.on -> start()
                }
            }.show()
    }

    private fun scanPair() {
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.CAMERA), 5); return
        }
        com.google.zxing.integration.android.IntentIntegrator(this)
            .setDesiredBarcodeFormats(com.google.zxing.integration.android.IntentIntegrator.QR_CODE)
            .setPrompt("סרוק את ה-QR שבמסך שמע במחשב (📱 חבר טלפון)")
            .setBeepEnabled(false).setOrientationLocked(false).initiateScan()
    }

    @Deprecated("Activity result of the QR scanner")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode == 9) {                              // the call-recordings folder
            val u = data?.data
            if (resultCode == RESULT_OK && u != null) {
                try { contentResolver.takePersistableUriPermission(u, Intent.FLAG_GRANT_READ_URI_PERMISSION) } catch (e: Exception) { }
                CallImport.setTree(this, u.toString())
                scanCallsNow()
            }
            return
        }
        val r = com.google.zxing.integration.android.IntentIntegrator.parseActivityResult(requestCode, resultCode, data)
        if (r == null) { super.onActivityResult(requestCode, resultCode, data); return }
        val txt = r.contents ?: return
        if (Prefs.parsePair(txt) == null) {
            Toast.makeText(this, "זה לא QR של שמע. פתח במחשב את המסך של שמע ← 📱 חבר טלפון.", Toast.LENGTH_LONG).show(); return
        }
        confirmPair(txt)
    }

    private fun confirmPair(link: String) {
        val (server, remote, token) = Prefs.parsePair(link) ?: return
        AlertDialog.Builder(this).setTitle("לחבר את הטלפון למחשב הזה?")
            .setMessage("ההקלטות יישלחו רק אל:\n$server" + (if (remote.isNotEmpty()) "\n$remote (מחוץ לבית)" else "") +
                "\n\nחבר רק למחשב שלך.")
            .setPositiveButton("חבר") { _, _ ->
                Prefs.save(this, server, token)
                Prefs.setRemote(this, remote)
                serverField?.setText(server); remoteField?.setText(remote); tokenField?.setText(token)
                Toast.makeText(this, "מחובר. בודק את המחשב…", Toast.LENGTH_LONG).show()
                checkPc()
                if (screen == "onboarding") nextStep()           // listening starts at the end of the first run
                else if (!ListenService.on) start()
            }.setNegativeButton("בטל", null).show()
    }

    private fun setRole(r: String) {
        Prefs.setRole(this, r); refreshChecklist()
        Toast.makeText(this, if (r == "wearer") "טלפון אישי: מקליט גם בחוץ" else "טלפון בית: מקליט רק בבית", Toast.LENGTH_LONG).show()
    }

    /** The voice reading screen (it was a silent 25 s in the background, so nothing seemed to happen on the tap). */
    private fun openEnroll(first: Boolean) = openWhenListening(EnrollActivity::class.java, first)

    /** Meeting / voice screens switch the microphone on themselves when allowed; else listening starts here first
     *  (subscription, disclosure, permissions) and the screen opens once it runs. */
    private var pendingFirst = false
    private fun openWhenListening(cls: Class<*>, first: Boolean = false) {
        if (ListenService.on || canRecord(this)) { startActivity(Intent(this, cls).putExtra("first", first)); return }
        pendingOpen = cls; pendingFirst = first; pendingAt = System.currentTimeMillis()
        start()
    }

    private fun privacyMenu() {
        val items = arrayOf("הוסף את המקום הנוכחי כאזור פרטי", "אזורים פרטיים (" + Prefs.zones(this).length() + ")",
            "יומן: מילים שמשתיקות", if (checkSelfPermission(Manifest.permission.READ_CALENDAR) == PackageManager.PERMISSION_GRANTED)
                "יומן: ההרשאה ניתנה ✓" else "יומן: לתת הרשאה")
        AlertDialog.Builder(this).setTitle("פרטיות").setItems(items) { _, i ->
            when (i) {
                0 -> addZone()
                1 -> listZones()
                2 -> editCalWords()
                3 -> requestPermissions(arrayOf(Manifest.permission.READ_CALENDAR), 4)
            }
        }.show()
    }

    private fun addZone() {
        val lat = ListenService.lat; val lon = ListenService.lon
        if (lat.isNaN() || checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            Toast.makeText(this, "המיקום עוד לא ידוע (צריך הרשאת מיקום והאזנה פעילה)", Toast.LENGTH_LONG).show(); return
        }
        val e = EditText(this).apply { hint = "שם המקום (עבודה, רופא...)"; inputType = InputType.TYPE_CLASS_TEXT }
        AlertDialog.Builder(this).setTitle("אזור פרטי: אין הקלטה ברדיוס 150 מ׳").setView(e)
            .setPositiveButton("שמור") { _, _ ->
                val a = Prefs.zones(this)
                a.put(org.json.JSONObject().put("n", e.text.toString().ifBlank { "פרטי" }).put("lat", lat).put("lon", lon).put("r", 150))
                Prefs.setZones(this, a)
            }.setNegativeButton("בטל", null).show()
    }

    private fun listZones() {
        val a = Prefs.zones(this)
        if (a.length() == 0) { Toast.makeText(this, "אין אזורים פרטיים", Toast.LENGTH_SHORT).show(); return }
        val names = Array(a.length()) { a.getJSONObject(it).optString("n") }
        AlertDialog.Builder(this).setTitle("הקש כדי למחוק").setItems(names) { _, i ->
            val b = org.json.JSONArray(); for (k in 0 until a.length()) if (k != i) b.put(a.get(k)); Prefs.setZones(this, b)
        }.show()
    }

    private fun editCalWords() {
        val e = EditText(this).apply { setText(Prefs.calWords(this@MainActivity)); inputType = InputType.TYPE_CLASS_TEXT }
        AlertDialog.Builder(this).setTitle("אירוע ביומן עם אחת המילים האלה = לא מקליט (מופרדות בפסיק)").setView(e)
            .setPositiveButton("שמור") { _, _ -> Prefs.setCalWords(this, e.text.toString()) }
            .setNegativeButton("בטל", null).show()
    }

    private fun doMark(min: Int) {
        if (!ListenService.on) { Toast.makeText(this, "ההקשבה כבויה, אין מה לסמן. הפעל קודם.", Toast.LENGTH_LONG).show(); return }
        svc(ListenService.ACTION_MARK, min)
        Toast.makeText(this, "⭐ הרגע סומן. נשמרות $min דקות לפני ואחרי, והשיחה לא תימחק.", Toast.LENGTH_LONG).show()
    }

    private fun toggleMain() { if (ListenService.on) stop() else start() }

    private fun start() {
        // Enforce subscription or trial entitlement
        if (!billingManager.evaluateEntitlement()) {
            showSubscriptionDialog()
            return
        }

        // Prominent disclosure requirement before asking microphone permission
        if (!Prefs.isDisclosureAccepted(this)) {
            showProminentDisclosure { proceedStart() }
            return
        }
        proceedStart()
    }

    private fun proceedStart() {
        Prefs.setWanted(this, true)
        Meeting.setTemp(this, false)                          // listening for good, not just for a meeting / the voice reading
        val need = arrayOf(Manifest.permission.RECORD_AUDIO, Manifest.permission.POST_NOTIFICATIONS)
            .filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (need.isNotEmpty()) { requestPermissions(need.toTypedArray(), 1); return }
        startForegroundService(Intent(this, ListenService::class.java))
        if (!batteryOk()) askBattery()
    }

    private fun stop() {
        Prefs.setWanted(this, false)
        startService(Intent(this, ListenService::class.java).setAction(ListenService.ACTION_STOP))
    }

    private fun svc(action: String, min: Int = 0) {
        if (ListenService.on) startService(Intent(this, ListenService::class.java).setAction(action).apply { if (min > 0) putExtra("min", min) })
    }

    override fun onRequestPermissionsResult(rc: Int, perms: Array<out String>, res: IntArray) {
        if (rc == 11) {                                      // first run: microphone + notifications
            if (screen == "onboarding") {
                val ok = checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
                if (!ok) Toast.makeText(this, "בלי מיקרופון שמע לא יכול להקשיב", Toast.LENGTH_LONG).show()
                else { obStep++; renderStep() }                  // notifications refused: fine, the settings offer it again
            }
            refreshChecklist(); return
        }
        if (rc == 8) { if (CallImport.permOk(this)) scanCallsNow(); refreshCalls(); return }
        if (rc == 5) {
            if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) scanPair()
            else Toast.makeText(this, "בלי מצלמה: הגדרות ← הזן ידנית את הכתובת והקוד מהמסך במחשב", Toast.LENGTH_LONG).show()
            return
        }
        if (rc != 4 && checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            startForegroundService(Intent(this, ListenService::class.java))
        }
        refreshChecklist()
    }

    private fun locOk() = checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
    private fun batteryOk(): Boolean {
        val pm = getSystemService(POWER_SERVICE) as PowerManager
        return pm.isIgnoringBatteryOptimizations(packageName)
    }
    private fun askBattery() {
        try { startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName"))) } catch (e: Exception) { }
    }

    private fun checkPc() {
        val s = Prefs.server(this)
        if (s.isEmpty()) { pcReachable = null; return }
        thread {
            val ok = try {
                val c = URL(s + "/home/api/status?device=ping").openConnection() as HttpURLConnection
                c.connectTimeout = 1500; c.readTimeout = 1500
                c.responseCode == 200
            } catch (e: Exception) { false }
            ui.post { pcReachable = ok }
        }
    }

    /** Settings: every permission with its state; a button only where something is missing. */
    private fun refreshChecklist() {
        if (!::checklist.isInitialized) return
        checklist.removeAllViews()
        val items = mutableListOf<Triple<String, Boolean, () -> Unit>>()
        items += Triple("מיקרופון", checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED)
            { requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 1) }
        items += Triple("התראות", checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED)
            { requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 2) }
        items += Triple("החרגה מחיסכון בסוללה", batteryOk()) { askBattery() }
        items += Triple("מיקום (רק לאזורים פרטיים ולזיהוי בית)", locOk())
            { requestPermissions(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION), 4) }
        for (m in items) {
            val row = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
                setPadding(0, px(4), 0, px(4))
                addView(text((if (m.second) "✓ " else "• ") + m.first, 14f, if (m.second) c.dim else c.ink),
                    LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
                if (!m.second) addView(button("אפשר") { m.third() })
            }
            checklist.addView(row)
        }
    }

    /** The home screen's problem cards: only what stops Shema from working, each with its fix. */
    private fun refreshAlerts() {
        val list = mutableListOf<Triple<String, String, () -> Unit>>()
        val on = ListenService.on
        if (!Prefs.paired(this)) list += Triple("עוד לא מחובר למחשב. בלי מחשב אין תמלול.", "חבר") { showSettings() }
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED)
            list += Triple("אין הרשאת מיקרופון.", "אפשר") { requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 1) }
        if (!batteryOk()) list += Triple("הטלפון עלול לסגור את שמע כדי לחסוך סוללה, וחלק מהיום לא יוקלט.", "תקן") { askBattery() }
        if (on && Prefs.paired(this) && !ListenService.lanOk && !ListenService.viaTailscale && ListenService.queued > 0)
            list += Triple("המחשב לא עונה. ${ListenService.queued} קטעים מחכים בטלפון ויישלחו כשיתחבר.", "מה לעשות") {
                AlertDialog.Builder(this).setTitle("המחשב לא עונה")
                    .setMessage("ההקלטות שמורות בטלפון ולא ילכו לאיבוד.\n\n• ודא שהמחשב דלוק ושמע פועל בו.\n" +
                        "• בבית: הטלפון והמחשב באותה רשת Wi-Fi.\n• בחוץ: Tailscale פועל בטלפון ובמחשב.")
                    .setPositiveButton("הבנתי", null).show()
            }
        val key = list.joinToString("|") { it.first }
        if (key == alertsKey) return
        alertsKey = key
        alerts.removeAllViews()
        for ((msg, act, fix) in list) {
            val card = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
                background = round(Color.parseColor("#3A1F1C"), 14, c.rose); setPadding(px(14), px(10), px(10), px(10))
                addView(text(msg, 14f, c.ink), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
                addView(button(act) { fix() })
            }
            alerts.addView(card)
            alerts.addView(View(this), LinearLayout.LayoutParams(1, px(8)))
        }
    }
    private var alertsKey: String? = null

    private fun tick() {
        val on = ListenService.on
        val paused = on && ListenService.pausedNow
        val pulseRed = on && !paused && ListenService.hearing
        // off / paused: one big orange "start / resume"; listening: only the small "pause" in the status row
        main.text = if (paused) "▶ המשך להקשיב" else "התחל להקשיב"
        main.visibility = if (!on || paused) View.VISIBLE else View.GONE
        pauseBtn.visibility = if (on && !paused) View.VISIBLE else View.GONE

        orb.background = GradientDrawable().apply {
            shape = GradientDrawable.OVAL
            setColor(if (pulseRed) c.rec else if (on && !paused) c.sage else c.off)
        }
        if (pulseRed && pulse == null) {
            pulse = ValueAnimator.ofFloat(0f, 1f).apply {
                duration = 1000; repeatCount = ValueAnimator.INFINITE; repeatMode = ValueAnimator.REVERSE
                addUpdateListener { orbRing.alpha = it.animatedValue as Float }
                start()
            }
        } else if (!pulseRed && pulse != null) {
            pulse?.cancel(); pulse = null; orbRing.alpha = 0f
        }

        // one status line
        val link = when { ListenService.lanOk -> "מחובר בבית"; ListenService.viaTailscale -> "מחובר מרחוק"; else -> "המחשב לא זמין" }
        val sent = if (ListenService.lastSentAt > 0) {
            val s = maxOf(0, (System.currentTimeMillis() - ListenService.lastSentAt) / 1000)
            "נשלח למחשב " + when { s < 60 -> "לפני $s שנ׳"; s < 3600 -> "לפני ${s / 60} דק׳"; else -> "לפני ${s / 3600} שע׳" }
        } else ""
        title.text = when { !on -> "כבוי"; paused -> "מושהה · לא מקליט"; pulseRed -> "שומע דיבור…"; else -> "מקשיב" }
        subtitle.text = when {
            !on -> "שום דבר לא מוקלט"
            paused -> "שום דבר לא מוקלט עד שתמשיך"
            ListenService.blocked.isNotEmpty() -> ListenService.blocked
            sent.isNotEmpty() -> "$link · $sent"
            else -> link
        }

        // home extras: who is this (only when voices wait), today
        val teach = ListenService.digestTeach
        whoBtn.visibility = if (teach > 0) View.VISIBLE else View.GONE
        whoBtn.text = "🙋 מי זה? $teach משפטים מחכים לשם"
        val mins = ListenService.speechToday(this)
        todayLine.text = if (mins > 0) "היום נשלחו למחשב " + (if (mins >= 60) "${mins / 60} שע׳ ${mins % 60} דק׳" else "$mins דק׳") + " דיבור" else ""
        if (screen == "home") loadToday()

        val meeting = Meeting.active(this)
        meetBtn.text = if (meeting) "🔴 פגישה מוקלטת · ${(System.currentTimeMillis() - Meeting.start(this)) / 60_000} דק׳" else "📋 הקלט פגישה"
        meetBtn.background = round(if (meeting) c.rec else c.surface2, 16, if (meeting) null else Color.parseColor("#33FFECD6"))
        refreshAlerts()

        // settings (kept current while open)
        connStatus.text = when {
            !Prefs.paired(this) -> "לא מחובר. סרוק את ה-QR שבמסך שמע במחשב."
            ListenService.lanOk -> "✓ מחובר למחשב ברשת הביתית"
            ListenService.viaTailscale -> "✓ מחובר למחשב דרך Tailscale"
            pcReachable == true -> "✓ המחשב עונה"
            else -> "המחשב לא זמין כרגע"
        } + (if (ListenService.queued > 0) " · ${ListenService.queued} קטעים ממתינים" else "") +
            (if (connBody.visibility == View.GONE) "  · פרטים ›" else "  ⌄")
        roleHome.background = round(if (Prefs.role(this) == "home") c.accent else c.surface2, 14)
        roleHome.setTextColor(if (Prefs.role(this) == "home") c.accentInk else c.ink)
        roleWear.background = round(if (Prefs.role(this) == "wearer") c.accent else c.surface2, 14)
        roleWear.setTextColor(if (Prefs.role(this) == "wearer") c.accentInk else c.ink)
        roleDesc.text = if (Prefs.role(this) == "home") "טלפון בית: מקליט רק ברשת הביתית" else "טלפון אישי: מקליט גם בחוץ"
        val en = ListenService.enrolled
        val known = en >= ListenService.minSamples
        if (known && !Prefs.flag(this, "voice_known")) Prefs.setFlag(this, "voice_known")
        enrollStatus.text = when {
            known -> "הקול שלך נלמד ✓ ($en דוגמאות)"
            en > 0 -> "מתחיל להכיר אותך ($en מתוך ${ListenService.minSamples} דוגמאות)"
            en == 0 -> "לא חובה: שמע לומד את הקול שלך גם כשאתה מסמן \"זה אני\" במסך \"מי זה?\". קריאה קצרה (25 שניות) רק מאיצה את זה."
            else -> "עוד לא ידוע (המחשב לא ענה עדיין)"
        }
        enrollBtn.text = if (known) "ללמד שוב" else "קריאה קצרה (25 שניות) · לא חובה"

        pendingOpen?.let { cls ->
            if (ListenService.on) { pendingOpen = null; startActivity(Intent(this, cls).putExtra("first", pendingFirst)) }
            else if (System.currentTimeMillis() - pendingAt > 60_000) pendingOpen = null
        }
        ui.postDelayed({ tick() }, 1000)
    }
}
