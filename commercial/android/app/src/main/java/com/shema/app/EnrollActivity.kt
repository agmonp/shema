package com.shema.app

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast

/**
 * "Let Shema know your voice": the owner reads a short text aloud for 25 seconds; those recordings go to the PC
 * as owner voice samples (kind=enroll). Shown from the card at the top of the main screen (first run, with "skip")
 * and from the settings. Skipping is fine: the owner's voice is also learnt from "זה אני" in "מי זה?".
 */
class EnrollActivity : Activity() {
    companion object {
        const val PASSAGE = "שלום, זה הקול שלי. ככה שמע ילמד לזהות אותי בכל שיחה.\n\n" +
            "הבוקר התעוררתי מוקדם, שתיתי קפה חם ויצאתי לסידורים. בדרך פגשתי שכן, ודיברנו קצת על מזג האוויר ועל החגים שמתקרבים.\n\n" +
            "בערב כיף לי לבשל, לשמוע מוזיקה ולטייל בפארק ליד הבית. בסוף השבוע נסענו לים עם כל המשפחה, " +
            "אכלנו ארוחה גדולה, צחקנו הרבה ותכננו את החופשה הבאה.\n\n" +
            "אחת, שתיים, שלוש, ארבע, חמש, שש, שבע, שמונה, תשע, עשר."
        const val MIN_SPEECH_MS = 8_000L                    // less speech than this in the 25 s = read again
    }
    private val ui = Handler(Looper.getMainLooper())
    private val col = object {
        val bg = Color.parseColor("#13100E"); val surface = Color.parseColor("#1C1815"); val surface2 = Color.parseColor("#25201C")
        val ink = Color.parseColor("#F4EDE5"); val dim = Color.parseColor("#B1A597"); val faint = Color.parseColor("#958A7D")
        val accent = Color.parseColor("#EAA45E"); val accentInk = Color.parseColor("#1B130B"); val sage = Color.parseColor("#86BBA8")
        val rose = Color.parseColor("#E48A7F"); val rec = Color.parseColor("#E5484D")
    }
    private var dp = 1f
    private lateinit var body: LinearLayout
    private var first = false                               // opened from the first-run card: offer "skip"
    private var alive = false
    private var phase = "ready"                             // ready / reading / sending / done
    private var before = -1                                 // owner samples on the PC before this reading
    private var sentAt = 0L
    private var beganAt = 0L

    private fun px(v: Int) = (v * dp).toInt()
    private fun round(color: Int, r: Int) = GradientDrawable().apply { setColor(color); cornerRadius = px(r).toFloat() }
    private fun text(t: String, size: Float, color: Int = col.ink, bold: Boolean = false) = TextView(this).apply {
        text = t; textSize = size; setTextColor(color); if (bold) typeface = Typeface.DEFAULT_BOLD
        setLineSpacing(0f, 1.2f)
    }
    private fun button(t: String, primary: Boolean = false, onClick: () -> Unit) = TextView(this).apply {
        text = t; textSize = if (primary) 18f else 15f; gravity = Gravity.CENTER
        setTextColor(if (primary) col.accentInk else col.ink); typeface = Typeface.DEFAULT_BOLD
        background = round(if (primary) col.accent else col.surface2, 16)
        setPadding(px(16), px(if (primary) 16 else 12), px(16), px(if (primary) 16 else 12))
        isClickable = true; setOnClickListener { onClick() }
    }
    private fun gap(h: Int) = body.addView(View(this), LinearLayout.LayoutParams(1, px(h)))

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        dp = resources.displayMetrics.density
        first = intent?.getBooleanExtra("first", false) ?: false
        body = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; layoutDirection = View.LAYOUT_DIRECTION_RTL
            setPadding(px(18), px(22), px(18), px(28))
        }
        setContentView(ScrollView(this).apply { setBackgroundColor(col.bg); addView(body) })
        if (System.currentTimeMillis() < ListenService.enrollUntilNow) {                    // came back while reading
            phase = "reading"; beganAt = ListenService.enrollUntilNow - ListenService.ENROLL_SECONDS * 1000L
        }
    }

    override fun onResume() { super.onResume(); alive = true; render() }
    override fun onPause() { alive = false; super.onPause() }

    private fun render() {
        when (phase) {
            "reading" -> showReading()
            "sending" -> showSending()
            "done" -> showDone()
            else -> showReady()
        }
    }

    private fun header(sub: String) {
        body.removeAllViews()
        body.addView(text("🎙 תן לשמע להכיר את הקול שלך", 22f, bold = true))
        gap(6)
        body.addView(text(sub, 15f, col.dim))
        gap(16)
    }

    private fun passage(active: Boolean) {
        body.addView(text(PASSAGE, 20f, if (active) col.ink else col.dim).apply {
            background = round(col.surface, 18); setPadding(px(18), px(16), px(18), px(16))
        })
    }

    private fun showReady() {
        val known = ListenService.enrolled >= ListenService.minSamples
        header(if (known) "הקול שלך כבר נלמד ✓. אפשר לקרוא שוב כדי לחזק את הזיהוי (למשל אם הטלפון החליף מקום או כיסוי)."
               else "קרא את הטקסט בקול רם, בקצב רגיל, כ-25 שניות. ככה שמע יידע מתי אתה מדבר, וכל משפט שלך יופיע בשם שלך.")
        passage(false)
        gap(16)
        body.addView(button("🎙 התחל לקרוא (25 שניות)", primary = true) { begin() })
        gap(10)
        if (first) {
            body.addView(button("דלג · התחל להקליט בלי זה") { skip() })
            gap(8)
            body.addView(text("אם תדלג, שמע ילמד את הקול שלך מהשיחות: במסך \"מי זה?\" לחץ \"זה אני\" על משפט שלך. " +
                "בטלפון אישי, הקלטה מחוץ לבית מתחילה רק אחרי שהקול שלך נלמד.", 13f, col.faint))
        } else {
            body.addView(button("סגור") { finish() })
            gap(8)
            body.addView(text("אפשר גם בלי לקרוא: במסך \"מי זה?\" לחץ \"זה אני\" על משפט שלך, ושמע ילמד מזה.", 13f, col.faint))
        }
    }

    private fun skip() {
        Prefs.setFlag(this, "enroll_later")
        Toast.makeText(this, "בסדר. שמע מקליט, וילמד את הקול שלך כשתסמן \"זה אני\" במסך \"מי זה?\"", Toast.LENGTH_LONG).show()
        finish()
    }

    private fun begin() {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO, Manifest.permission.POST_NOTIFICATIONS), 1); return
        }
        if (!ListenService.on && !MainActivity.canRecord(this)) {
            startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP))
            Toast.makeText(this, "קודם צריך להפעיל את שמע במסך הראשי", Toast.LENGTH_LONG).show()
            finish(); return
        }
        before = ListenService.enrolled
        beganAt = System.currentTimeMillis()
        startForegroundService(Intent(this, ListenService::class.java).setAction(ListenService.ACTION_ENROLL))
        phase = "reading"
        ui.postDelayed({ render() }, 300)
    }

    override fun onRequestPermissionsResult(rc: Int, perms: Array<out String>, res: IntArray) {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) begin()
        else Toast.makeText(this, "בלי הרשאת מיקרופון אי אפשר ללמוד את הקול", Toast.LENGTH_LONG).show()
    }

    private fun showReading() {
        header("קרא עכשיו בקול רם, מההתחלה. אם הטקסט נגמר, התחל אותו שוב.")
        val bar = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            max = 1000; progressTintList = android.content.res.ColorStateList.valueOf(col.accent)
        }
        val left = text("", 26f, bold = true).apply { gravity = Gravity.CENTER }
        val heard = text("", 15f, col.dim).apply { gravity = Gravity.CENTER }
        body.addView(left); body.addView(bar, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, px(10))); body.addView(heard)
        gap(14)
        passage(true)
        gap(14)
        body.addView(button("סיימתי לקרוא") { startService(Intent(this, ListenService::class.java).setAction(ListenService.ACTION_ENROLL_STOP)) })
        fun tick() {
            if (!alive || phase != "reading") return
            val until = ListenService.enrollUntilNow
            val now = System.currentTimeMillis()
            if (until < beganAt + 1000) {                    // the service has not taken this reading yet
                left.text = "${ListenService.ENROLL_SECONDS}"; heard.text = "מפעיל את המיקרופון…"
                if (now - beganAt > 8000) { phase = "ready"; render(); Toast.makeText(this, "המיקרופון לא נפתח. נסה שוב.", Toast.LENGTH_LONG).show(); return }
                ui.postDelayed({ tick() }, 200); return
            }
            if (until <= now) {
                if (ListenService.enrollSpeechMs < MIN_SPEECH_MS) { tooLittle(); return }
                phase = "sending"; sentAt = now; render(); return
            }
            val total = ListenService.ENROLL_SECONDS * 1000L
            val rem = if (until > now) until - now else total
            left.text = "${(rem + 999) / 1000}"
            bar.progress = (1000 * (total - rem) / total).toInt()
            val sp = ListenService.enrollSpeechMs / 1000
            heard.text = when {
                !ListenService.on -> "מפעיל את המיקרופון…"
                ListenService.silencedNow -> "המיקרופון תפוס (שיחה או אפליקציה אחרת)"
                ListenService.hearing -> "● שומע אותך · $sp שנ׳ דיבור"
                else -> "דבר בקול רם · $sp שנ׳ דיבור"
            }
            heard.setTextColor(if (ListenService.hearing) col.sage else col.dim)
            ui.postDelayed({ tick() }, 200)
        }
        tick()
    }

    private fun tooLittle() {
        phase = "ready"
        header("שמעתי רק ${ListenService.enrollSpeechMs / 1000} שניות של דיבור. נסה שוב, בקול רם וקרוב לטלפון.")
        passage(false)
        gap(16)
        body.addView(button("🎙 נסה שוב", primary = true) { begin() })
        gap(10)
        body.addView(button(if (first) "דלג · התחל להקליט בלי זה" else "סגור") { if (first) skip() else finish() })
    }

    private fun showSending() {
        header("תודה! ההקלטה נשלחת למחשב, והוא לומד ממנה את הקול שלך.")
        val st = text("", 17f, bold = true)
        val det = text("", 14f, col.dim)
        body.addView(st); body.addView(det)
        gap(16)
        body.addView(button("סגור · זה ימשיך לבד") { finish() })
        fun tick() {
            if (!alive || phase != "sending") return
            val n = ListenService.enrolled
            if (n >= ListenService.minSamples && (before < ListenService.minSamples || n > before)) { phase = "done"; render(); return }
            val waited = (System.currentTimeMillis() - sentAt) / 1000
            when {
                !ListenService.pcOnline -> { st.text = "המחשב לא זמין כרגע"
                    det.text = "ההקלטה שמורה בטלפון ותישלח כשהמחשב יענה. אפשר לסגור." }
                ListenService.queued > 0 -> { st.text = "שולח למחשב…"; det.text = "${ListenService.queued} ממתינים בתור" }
                waited > 180 -> { st.text = "המחשב עדיין לומד"; det.text = "אפשר לסגור. זה יסתיים לבד, והסטטוס יתעדכן בהגדרות." }
                else -> { st.text = "המחשב לומד את הקול שלך…"; det.text = "בדרך כלל פחות מדקה" }
            }
            if (waited % 5 == 0L) startService(Intent(this, ListenService::class.java).setAction(ListenService.ACTION_PING))
            ui.postDelayed({ tick() }, 1000)
        }
        tick()
    }

    private fun showDone() {
        Prefs.setFlag(this, "voice_known")
        body.removeAllViews()
        body.addView(text("✓ הקול שלך נלמד", 26f, col.sage, true))
        gap(8)
        body.addView(text("מעכשיו המשפטים שלך יופיעו בשיחות בשם שלך. אם משפט שלך יופיע בלי שם, לחץ \"זה אני\" במסך \"מי זה?\" וזה ישתפר.", 16f, col.dim))
        gap(20)
        body.addView(button("סיום", primary = true) { finish() })
    }
}
