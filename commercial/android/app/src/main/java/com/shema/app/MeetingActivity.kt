package com.shema.app

import android.Manifest
import android.animation.ValueAnimator
import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
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
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.concurrent.thread

/**
 * The meeting being recorded now (kept across restarts of the service) and the last meetings.
 * temp = the service was started only for a meeting / the voice reading: it stops once everything was sent.
 */
object Meeting {
    private fun p(c: Context) = c.getSharedPreferences("meeting", Context.MODE_PRIVATE)
    fun id(c: Context) = p(c).getString("id", "")!!
    fun title(c: Context) = p(c).getString("title", "")!!
    fun start(c: Context) = p(c).getLong("start", 0L)
    fun active(c: Context) = id(c).isNotEmpty()
    fun begin(c: Context, id: String, title: String, start: Long) =
        p(c).edit().putString("id", id).putString("title", title).putLong("start", start).apply()
    fun clear(c: Context) = p(c).edit().remove("id").remove("title").remove("start").apply()
    fun temp(c: Context) = p(c).getBoolean("temp", false)
    fun setTemp(c: Context, v: Boolean) = p(c).edit().putBoolean("temp", v).apply()

    /** newest first: [{"id","title","start","end"}] */
    fun history(c: Context): JSONArray = try { JSONArray(p(c).getString("history", "[]")) } catch (e: Exception) { JSONArray() }
    fun remember(c: Context, id: String, title: String, start: Long, end: Long) {
        val a = JSONArray().put(JSONObject().put("id", id).put("title", title).put("start", start).put("end", end))
        val old = history(c)
        for (i in 0 until minOf(old.length(), 29)) if (old.getJSONObject(i).optString("id") != id) a.put(old.get(i))
        p(c).edit().putString("history", a.toString()).apply()
    }
    /** deleted by the user: off the recent list */
    fun forget(c: Context, ids: Collection<String>) {
        val old = history(c); val a = JSONArray()
        for (i in 0 until old.length()) if (old.getJSONObject(i).optString("id") !in ids) a.put(old.get(i))
        p(c).edit().putString("history", a.toString()).apply()
    }
    fun known(c: Context, id: String): JSONObject? {
        val a = history(c)
        for (i in 0 until a.length()) if (a.getJSONObject(i).optString("id") == id) return a.getJSONObject(i)
        return null
    }
    fun notified(c: Context, id: String) = p(c).getStringSet("notified", emptySet())!!.contains(id)
    fun setNotified(c: Context, id: String) {
        val s = p(c).getStringSet("notified", emptySet())!!.toMutableSet(); s.add(id)
        p(c).edit().putStringSet("notified", s.toList().takeLast(60).toSet()).apply()
    }
}

/**
 * "Record a meeting": start, end, and then the PC's transcript, summary, decisions, tasks and next steps,
 * ready to send. While the meeting runs everything the phone hears goes to it (also away from home, also when
 * muted / paused: the user chose to record it). Opened with extra "id" it shows that meeting's result.
 */
class MeetingActivity : Activity() {
    companion object {
        @Volatile var showing = ""                       // the meeting on screen now (no "ready" notification for it)
    }
    private val ui = Handler(Looper.getMainLooper())
    private lateinit var picker: Picker
    private val col = object {
        val bg = Color.parseColor("#13100E"); val surface = Color.parseColor("#1C1815"); val surface2 = Color.parseColor("#25201C")
        val ink = Color.parseColor("#F4EDE5"); val dim = Color.parseColor("#B1A597"); val faint = Color.parseColor("#958A7D")
        val accent = Color.parseColor("#EAA45E"); val accentInk = Color.parseColor("#1B130B"); val sage = Color.parseColor("#86BBA8")
        val rose = Color.parseColor("#E48A7F"); val rec = Color.parseColor("#E5484D"); val off = Color.parseColor("#6F665C")
    }
    private var dp = 1f
    private lateinit var body: LinearLayout
    private var resultId = ""                              // the meeting whose result is shown ("" = start / recording)
    private var lastResult: JSONObject? = null
    private var pulse: ValueAnimator? = null
    private var alive = false
    private var startTitle = ""

    private fun px(v: Int) = (v * dp).toInt()
    private fun round(color: Int, r: Int) = GradientDrawable().apply { setColor(color); cornerRadius = px(r).toFloat() }
    private fun text(t: String, size: Float, color: Int = col.ink, bold: Boolean = false) = TextView(this).apply {
        text = t; textSize = size; setTextColor(color); if (bold) typeface = Typeface.DEFAULT_BOLD
        setLineSpacing(0f, 1.15f)
    }
    private fun button(t: String, primary: Boolean = false, onClick: () -> Unit) = TextView(this).apply {
        text = t; textSize = if (primary) 18f else 15f; gravity = Gravity.CENTER
        setTextColor(if (primary) col.accentInk else col.ink); typeface = Typeface.DEFAULT_BOLD
        background = round(if (primary) col.accent else col.surface2, 16)
        setPadding(px(16), px(if (primary) 16 else 12), px(16), px(if (primary) 16 else 12))
        isClickable = true; setOnClickListener { onClick() }
    }
    private fun card() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL; background = round(col.surface, 18); setPadding(px(16), px(14), px(16), px(14))
    }
    private fun gap(h: Int) = body.addView(View(this), LinearLayout.LayoutParams(1, px(h)))

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        dp = resources.displayMetrics.density
        body = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; layoutDirection = View.LAYOUT_DIRECTION_RTL
            setPadding(px(18), px(22), px(18), px(96))
        }
        val host = FrameLayout(this)
        host.addView(ScrollView(this).apply { setBackgroundColor(col.bg); addView(body) })
        setContentView(host)
        picker = Picker(this, host, "פגישה", "פגישות",
            commit = { ids -> (Net.call(this, "POST", "/home/api/delete_items", JSONObject().put("meetings", JSONArray(ids))) != null)
                .also { ok -> if (ok) Meeting.forget(this, ids) } },
            redraw = { if (alive) render() })
        resultId = intent?.getStringExtra("id") ?: ""
        startTitle = intent?.getStringExtra("title") ?: ""
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        intent?.getStringExtra("id")?.let { resultId = it; lastResult = null }
        render()
    }

    override fun onResume() { super.onResume(); alive = true; render() }
    override fun onStop() { picker.flush(); super.onStop() }
    override fun onPause() { alive = false; showing = ""; pulse?.cancel(); pulse = null; super.onPause() }

    private fun render() {
        when {
            Meeting.active(this) -> showRecording()
            resultId.isNotEmpty() -> showResult()
            else -> showStart()
        }
    }

    // ------------------------------------------------------------ start
    private fun showStart() {
        showing = ""
        body.removeAllViews()
        body.addView(text("📋 הקלטת פגישה", 24f, bold = true))
        gap(6)
        body.addView(text("לחץ התחל כשהפגישה מתחילה, וסיים כשהיא נגמרת. המחשב מתמלל, ואחרי כמה דקות תקבל כאן סיכום, החלטות, משימות ותמלול מלא, מוכנים לשליחה.", 15f, col.dim))
        gap(16)
        val title = EditText(this).apply {
            hint = "שם הפגישה (לא חובה)"; setHintTextColor(col.faint); setTextColor(col.ink); textSize = 17f
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_CAP_SENTENCES
            background = round(col.surface2, 14); setPadding(px(14), px(12), px(14), px(12)); setText(startTitle)
        }
        body.addView(title)
        gap(12)
        body.addView(button("▶ התחל פגישה", primary = true) { begin(title.text.toString().trim()) })
        gap(10)
        body.addView(text("ההקלטה רצה גם מחוץ לבית וגם כשההקשבה מושתקת, עד שתלחץ סיים. ספר למשתתפים שהפגישה מוקלטת.", 13f, col.faint))
        val h = Meeting.history(this)
        if (h.length() > 0) {
            gap(22)
            picker.clear()
            val head = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
            head.addView(text("פגישות אחרונות", 14f, col.faint), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            head.addView(text("בחר", 14f, col.dim, true).apply { setPadding(px(12), px(6), px(12), px(6)); background = round(col.surface2, 14)
                contentDescription = "בחירת פגישות למחיקה"; isClickable = true; setOnClickListener { picker.start() } })
            body.addView(head)
            gap(6)
            for (i in 0 until minOf(h.length(), 10)) {
                val m = h.getJSONObject(i)
                val open = { resultId = m.optString("id"); lastResult = null; render() }
                val row = card().apply {
                    orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
                    val inner = LinearLayout(this@MeetingActivity).apply { orientation = LinearLayout.VERTICAL }
                    inner.addView(text(m.optString("title").ifEmpty { "פגישה" }, 16f, bold = true))
                    inner.addView(text(when_(m.optLong("start")) + " · " + mins(m.optLong("end") - m.optLong("start")), 13f, col.dim))
                    addView(inner, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
                    isClickable = true; setOnClickListener { open() }
                }
                val mark = text("", 14f, col.ink, true).apply { gravity = Gravity.CENTER }
                row.addView(mark, LinearLayout.LayoutParams(px(24), px(24)).apply { marginStart = px(10) })
                picker.row(m.optString("id"), row, mark, open)
                body.addView(row)
                gap(8)
            }
        }
    }

    private fun begin(title: String) {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            startTitle = title
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO, Manifest.permission.POST_NOTIFICATIONS), 1); return
        }
        if (!ListenService.on && !MainActivity.canRecord(this)) {   // not allowed to switch the microphone on from here
            startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP))
            Toast.makeText(this, "קודם צריך להפעיל את שמע במסך הראשי", Toast.LENGTH_LONG).show()
            finish(); return
        }
        val id = "m" + System.currentTimeMillis()
        startForegroundService(Intent(this, ListenService::class.java).setAction(ListenService.ACTION_MEETING_START)
            .putExtra("id", id).putExtra("title", title))
        resultId = ""
        ui.postDelayed({ render() }, 400)
    }

    override fun onRequestPermissionsResult(rc: Int, perms: Array<out String>, res: IntArray) {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) begin(startTitle)
        else Toast.makeText(this, "בלי הרשאת מיקרופון אי אפשר להקליט", Toast.LENGTH_LONG).show()
    }

    // ------------------------------------------------------------ recording
    private fun showRecording() {
        showing = ""
        body.removeAllViews()
        body.addView(text("📋 הפגישה מוקלטת", 24f, bold = true))
        val t = Meeting.title(this)
        if (t.isNotEmpty()) body.addView(text(t, 17f, col.dim))
        gap(18)
        val orbBox = FrameLayout(this)
        val ring = View(this).apply { background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(col.rec) }; alpha = 0f }
        val orb = View(this).apply { background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(col.rec) } }
        orbBox.addView(ring, FrameLayout.LayoutParams(px(110), px(110), Gravity.CENTER))
        orbBox.addView(orb, FrameLayout.LayoutParams(px(76), px(76), Gravity.CENTER))
        body.addView(orbBox, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, px(120)))
        val clock = text("0:00", 44f, bold = true).apply { gravity = Gravity.CENTER; typeface = Typeface.create(Typeface.DEFAULT_BOLD, Typeface.BOLD) }
        val heard = text("", 15f, col.dim).apply { gravity = Gravity.CENTER }
        body.addView(clock); body.addView(heard)
        gap(22)
        body.addView(button("⏹ סיים פגישה וקבל סיכום", primary = true) { end() })
        gap(12)
        body.addView(text("אפשר לנעול את המסך ולצאת מהאפליקציה: ההקלטה ממשיכה. אפשר לסיים גם מההתראה בווילון.", 13f, col.faint))
        pulse?.cancel()
        pulse = ValueAnimator.ofFloat(0f, 0.8f).apply {
            duration = 900; repeatCount = ValueAnimator.INFINITE; repeatMode = ValueAnimator.REVERSE
            addUpdateListener { ring.alpha = if (ListenService.hearing) it.animatedValue as Float else 0f }
            start()
        }
        fun tick() {
            if (!alive || !Meeting.active(this)) { if (alive) render(); return }
            clock.text = clockText(System.currentTimeMillis() - Meeting.start(this))
            heard.text = when {
                !ListenService.on -> "מפעיל את המיקרופון…"
                ListenService.silencedNow -> "המיקרופון תפוס (שיחת טלפון?) · ממשיך כשיתפנה"
                ListenService.hearing -> "שומע דיבור ●"
                else -> "מקשיב"
            }
            ui.postDelayed({ tick() }, 500)
        }
        tick()
    }

    private fun end() {
        val id = Meeting.id(this)
        startService(Intent(this, ListenService::class.java).setAction(ListenService.ACTION_MEETING_END))
        pulse?.cancel(); pulse = null
        resultId = id; lastResult = null
        body.removeAllViews(); body.addView(text("מסיים…", 16f, col.dim))
        ui.postDelayed({ render() }, 900)                    // the service writes the end after the last segment
    }

    // ------------------------------------------------------------ result
    private fun showResult() {
        showing = resultId
        lastResult?.let { if (it.optJSONObject("meeting")?.optString("status") == "done") { drawResult(it); return } }
        body.removeAllViews()
        val m = Meeting.known(this, resultId)
        body.addView(text(m?.optString("title")?.ifEmpty { null } ?: "פגישה", 22f, bold = true))
        if (m != null) body.addView(text(when_(m.optLong("start")) + " · " + mins(m.optLong("end") - m.optLong("start")), 13f, col.dim))
        gap(18)
        val status = text("בודק…", 17f, col.ink, true)
        val detail = text("", 14f, col.dim)
        body.addView(status); body.addView(detail)
        gap(20)
        body.addView(button("חזרה") { resultId = ""; lastResult = null; startTitle = ""; render() })
        poll(status, detail)
    }

    private fun queueState(): Pair<Boolean, Int> {
        val files = File(filesDir, "queue").listFiles() ?: emptyArray()
        val endWaiting = files.any { it.name.endsWith("_meetend.txt") && (try { it.readText().startsWith("$resultId,") } catch (e: Exception) { false }) }
        return endWaiting to files.count { !it.name.endsWith(".meta") && !it.name.endsWith(".txt") }
    }

    private fun poll(status: TextView, detail: TextView) {
        if (!alive || resultId.isEmpty()) return
        val id = resultId
        thread {
            val r = call("GET", "/home/api/meeting?id=" + URLEncoder.encode(id, "UTF-8"))
            ui.post {
                if (!alive || resultId != id) return@post
                val (endWaiting, queued) = queueState()
                val j = try { r?.let { JSONObject(it) } } catch (e: Exception) { null }
                val mt = j?.optJSONObject("meeting")
                val st = mt?.optString("status") ?: ""
                if (st == "done" && !endWaiting) { lastResult = j; drawResult(j!!); return@post }
                when {
                    endWaiting && !ListenService.pcOnline -> {
                        status.text = "המחשב לא זמין כרגע"
                        detail.text = "ההקלטות שמורות בטלפון ($queued ממתינות). הן יישלחו כשהמחשב יענה, ותקבל התראה כשהסיכום מוכן. אפשר לסגור את המסך."
                    }
                    endWaiting -> { status.text = "שולח את ההקלטות למחשב…"; detail.text = "$queued ממתינות בטלפון" }
                    j == null -> { status.text = "אין חיבור למחשב"; detail.text = "מנסה שוב… (צריך להיות ברשת הבית או מחובר דרך Tailscale)" }
                    mt == null -> { status.text = "ממתין למחשב…"; detail.text = "" }
                    st == "empty" -> { status.text = "לא נשמע דיבור בפגישה הזו"; detail.text = ""; return@post }
                    st == "summarising" -> { status.text = "כותב סיכום ומשימות…"; detail.text = "עוד רגע" }
                    else -> {
                        val p = j.optJSONObject("progress")
                        status.text = "מתמלל במחשב…"
                        detail.text = if (p != null && p.optInt("chunks") > 0) "${p.optInt("done")} מתוך ${p.optInt("chunks")} קטעים" else ""
                    }
                }
                ui.postDelayed({ poll(status, detail) }, 4000)
            }
        }
    }

    private fun drawResult(j: JSONObject) {
        body.removeAllViews()
        val mt = j.getJSONObject("meeting")
        val title = mt.optString("title").takeIf { it.isNotEmpty() && it != "null" } ?: j.optString("topic").takeIf { it.isNotEmpty() && it != "null" } ?: "פגישה"
        body.addView(text("📋 $title", 22f, bold = true))
        val people = j.optJSONArray("people") ?: JSONArray()
        val info = mutableListOf(when_(parseIso(mt.optString("started"))), mins(((j.optDouble("seconds", 0.0)) * 1000).toLong()))
        if (people.length() > 0) info += (0 until people.length()).joinToString(", ") { people.getString(it) }
        body.addView(text(info.filter { it.isNotEmpty() }.joinToString(" · "), 13f, col.dim))
        gap(14)
        val share = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        share.addView(button("📤 שלח סיכום", primary = true) { send(j, false) },
            LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { marginEnd = px(8) })
        share.addView(button("שלח עם תמלול") { send(j, true) }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        body.addView(share)
        if (j.optBoolean("has_audio")) {                   // PC 1.0.12+: the recordings are still kept
            gap(8)
            val rec = button("🎧 שתף הקלטה") {}
            rec.setOnClickListener { shareAudio(mt.optString("id"), rec) }
            body.addView(rec)
            body.addView(text("רק הקטעים שבהם דיברו. הפרקים בקובץ נקראים לפי השעה בפגישה. ההקלטה כוללת קולות של אחרים: ודא שהם מסכימים לפני ששולחים.", 12f, col.faint).apply { setPadding(0, px(4), 0, 0) })
        }
        gap(14)
        val summary = j.optString("summary").takeIf { it.isNotEmpty() && it != "null" }
        section("סיכום", if (summary != null) listOf(summary) else listOf("המחשב לא הצליח לכתוב סיכום (מודל הסיכום לא זמין?). התמלול למטה שלם."), bullets = false)
        section("החלטות", strings(j.optJSONArray("decisions")))
        val tasks = j.optJSONArray("tasks") ?: JSONArray()
        section("משימות", (0 until tasks.length()).map {
            val t = tasks.getJSONObject(it)
            val who = t.optString("who").takeIf { w -> w.isNotEmpty() && w != "?" && w != "null" }
            val due = t.optString("due").takeIf { d -> d.isNotEmpty() && d != "null" }
            (if (who != null) "$who: " else "") + t.optString("what") + (if (due != null) " ($due)" else "")
        })
        section("הצעדים הבאים", strings(j.optJSONArray("next_steps")))
        val lines = j.optJSONArray("lines") ?: JSONArray()
        val tr = card()
        tr.addView(text("תמלול מלא · ${lines.length()} שורות", 14f, col.faint))
        val trBody = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; visibility = View.GONE }
        for (i in 0 until lines.length()) {
            val u = lines.getJSONObject(i)
            val n = u.optString("name").takeIf { it.isNotEmpty() && it != "null" } ?: "לא מזוהה"
            trBody.addView(text(u.optString("t0").drop(11).take(5) + "  " + n + ": " + u.optString("text"), 14f, col.ink).apply { setPadding(0, px(4), 0, px(4)) })
        }
        val toggle = button("הצג תמלול") {}
        toggle.setOnClickListener {
            trBody.visibility = if (trBody.visibility == View.GONE) View.VISIBLE else View.GONE
            toggle.text = if (trBody.visibility == View.GONE) "הצג תמלול" else "הסתר תמלול"
        }
        tr.addView(View(this), LinearLayout.LayoutParams(1, px(8)))
        tr.addView(toggle); tr.addView(trBody)
        body.addView(tr)
        gap(14)
        val more = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        more.addView(button("העתק") { copy(j) }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { marginEnd = px(8) })
        more.addView(button("סכם שוב") { resummarise() }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { marginEnd = px(8) })
        more.addView(button("פגישה חדשה") { resultId = ""; lastResult = null; startTitle = ""; render() }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        body.addView(more)
        gap(10)
        body.addView(text("הסיכום והמשימות נכתבו אוטומטית מהתמלול. כדאי לעבור עליהם לפני שליחה.", 12f, col.faint))
    }

    private fun section(head: String, items: List<String>, bullets: Boolean = true) {
        if (items.isEmpty()) return
        val c = card()
        c.addView(text(head, 14f, col.accent, true))
        for (s in items) c.addView(text((if (bullets) "• " else "") + s, 16f).apply { setPadding(0, px(6), 0, 0) })
        body.addView(c)
        gap(10)
    }

    private fun strings(a: JSONArray?): List<String> = if (a == null) emptyList() else (0 until a.length()).map { a.optString(it) }.filter { it.isNotBlank() }

    private fun shareText(j: JSONObject, full: Boolean): String {
        val s = j.optString("share_text")
        return if (!full) s else s + "\n\n*תמלול*\n" + j.optString("transcript_text")
    }

    private fun send(j: JSONObject, full: Boolean) {
        val title = j.optJSONObject("meeting")?.optString("title")?.takeIf { it.isNotEmpty() && it != "null" } ?: "סיכום פגישה"
        startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).apply {
            type = "text/plain"; putExtra(Intent.EXTRA_SUBJECT, title); putExtra(Intent.EXTRA_TEXT, shareText(j, full))
        }, "שלח את סיכום הפגישה"))
    }

    /** The whole meeting as one m4a from the PC (speech only, chapters = the real clock time) -> the share sheet. */
    private fun shareAudio(mid: String, btn: TextView) =
        AudioShare.share(this, "/home/audio/meeting/" + URLEncoder.encode(mid, "UTF-8") + ".m4a", "meeting-$mid.m4a", "שתף את הקלטת הפגישה", btn)

    private fun copy(j: JSONObject) {
        (getSystemService(CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText("סיכום פגישה", shareText(j, true)))
        Toast.makeText(this, "הסיכום והתמלול הועתקו", Toast.LENGTH_SHORT).show()
    }

    private fun resummarise() {
        val id = resultId
        body.removeAllViews(); body.addView(text("מבקש מהמחשב לסכם שוב…", 16f, col.dim))
        thread {
            call("POST", "/home/api/meeting_end?device=${ListenService.device()}&id=" + URLEncoder.encode(id, "UTF-8"))
            ui.post { lastResult = null; render() }
        }
    }

    // ------------------------------------------------------------ helpers
    private fun call(method: String, path: String): String? = try {
        val c = URL(Prefs.base(this) + path).openConnection() as HttpURLConnection
        c.requestMethod = method; c.connectTimeout = 4000; c.readTimeout = 20000
        c.setRequestProperty("X-Home-Token", Prefs.token(this))
        if (method == "POST") { c.doOutput = true; c.setFixedLengthStreamingMode(0); c.outputStream.close() }
        val r = if (c.responseCode == 200) c.inputStream.bufferedReader().readText() else null
        c.disconnect(); r
    } catch (e: Exception) { null }

    private fun clockText(ms: Long): String {
        val s = maxOf(0L, ms / 1000)
        return if (s >= 3600) "%d:%02d:%02d".format(s / 3600, s / 60 % 60, s % 60) else "%d:%02d".format(s / 60, s % 60)
    }
    private fun mins(ms: Long): String = if (ms <= 0) "" else "${maxOf(1L, (ms + 30_000) / 60_000)} דק׳"
    private fun when_(ms: Long): String = if (ms <= 0) "" else SimpleDateFormat("dd.MM HH:mm", Locale.US).format(Date(ms))
    private fun parseIso(s: String): Long = try {
        SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US).parse(s.take(19))!!.time
    } catch (e: Exception) { 0L }
}
