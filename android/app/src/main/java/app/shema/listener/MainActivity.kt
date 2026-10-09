package app.shema.listener

import android.Manifest
import android.animation.ValueAnimator
import android.app.Activity
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
import android.app.AlertDialog
import android.widget.EditText
import android.widget.Toast
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

object Prefs {
    private fun p(c: Context) = c.getSharedPreferences("home", Context.MODE_PRIVATE)
    fun server(c: Context) = p(c).getString("server", "")!!.trimEnd('/')
    fun token(c: Context) = p(c).getString("token", "")!!
    fun save(c: Context, server: String, token: String) =
        p(c).edit().putString("server", server.trim()).putString("token", token.trim()).apply()
    /** the user pressed Start (and not Off): used after a restart to offer "tap to listen" */
    fun wanted(c: Context) = p(c).getBoolean("wanted", false)
    fun setWanted(c: Context, v: Boolean) = p(c).edit().putBoolean("wanted", v).apply()
    /** the home Wi-Fi (learnt the first time the PC answers on it) */
    fun homeSsid(c: Context) = p(c).getString("home_ssid", "")!!
    fun setHomeSsid(c: Context, v: String) = p(c).edit().putString("home_ssid", v).apply()
    fun autostartDone(c: Context) = p(c).getBoolean("autostart_done", false)
    fun setAutostartDone(c: Context) = p(c).edit().putBoolean("autostart_done", true).apply()
    /** "home": records only at home (the phone that stays). "wearer" (default): the personal phone that goes out with the user. */
    fun role(c: Context) = p(c).getString("role", "wearer")!!
    fun setRole(c: Context, v: String) = p(c).edit().putString("role", v).apply()
    /** private places: JSON [{"n":name,"lat":..,"lon":..,"r":metres}] -- no recording inside them */
    fun zones(c: Context): org.json.JSONArray =
        try { org.json.JSONArray(p(c).getString("zones", "[]")) } catch (e: Exception) { org.json.JSONArray() }
    fun setZones(c: Context, a: org.json.JSONArray) = p(c).edit().putString("zones", a.toString()).apply()
    /** a calendar event whose title has one of these words is private: no recording while it runs */
    fun calWords(c: Context) = p(c).getString("cal_words", "רופא,טיפול,פסיכולוג,עורך דין,רפואי,פרטי,doctor,therapy,lawyer,private")!!
    fun setCalWords(c: Context, v: String) = p(c).edit().putString("cal_words", v).apply()
    /** The PC's Tailscale address, e.g. http://100.x.y.z:8770 (used when the home address does not answer) */
    fun remote(c: Context) = p(c).getString("remote", "")!!.trimEnd('/')
    fun setRemote(c: Context, v: String) = p(c).edit().putString("remote", v.trim()).apply()
    /** the address to talk to right now: whichever answered last, else the home one */
    fun base(c: Context) = ListenService.activeServer.ifEmpty { server(c) }
    fun flag(c: Context, k: String) = p(c).getBoolean(k, false)
    fun setFlag(c: Context, k: String) = p(c).edit().putBoolean(k, true).apply()
    fun digestDay(c: Context) = p(c).getString("digest_day", "")!!
    fun paired(c: Context) = server(c).isNotEmpty() && token(c).isNotEmpty()

    /** shema://pair?server=http://<LAN-IP>:8770&remote=http://<tailscale-ip>:8770&token=<token>  -> (server, remote, token) */
    fun parsePair(s: String?): Triple<String, String, String>? {
        if (s.isNullOrBlank()) return null
        return try {
            val u = Uri.parse(s.trim())
            if (u.scheme != "shema" || u.host != "pair") return null
            val server = u.getQueryParameter("server").orEmpty().trim().trimEnd('/')
            val remote = u.getQueryParameter("remote").orEmpty().trim().trimEnd('/')
            val token = u.getQueryParameter("token").orEmpty().trim()
            val okUrl = { x: String -> x.startsWith("http://") || x.startsWith("https://") }
            if (!okUrl(server) || token.isEmpty() || (remote.isNotEmpty() && !okUrl(remote))) null else Triple(server, remote, token)
        } catch (e: Exception) { null }
    }
    fun setDigestDay(c: Context, v: String) = p(c).edit().putString("digest_day", v).apply()
}

/**
 * One screen, built in code (no layout files, no extra libraries):
 *   status orb (pulses red while it hears speech) + one big button + quick actions
 *   today's numbers, a setup checklist that shows only what is missing, connection settings.
 */
class MainActivity : Activity() {
    private val ui = Handler(Looper.getMainLooper())
    private val c = object {
        val bg = Color.parseColor("#13100E"); val surface = Color.parseColor("#1C1815")
        val surface2 = Color.parseColor("#25201C"); val ink = Color.parseColor("#F4EDE5")
        val dim = Color.parseColor("#B1A597"); val faint = Color.parseColor("#958A7D")
        val accent = Color.parseColor("#EAA45E"); val accentInk = Color.parseColor("#1B130B")
        val sage = Color.parseColor("#86BBA8"); val rose = Color.parseColor("#E48A7F")
        val rec = Color.parseColor("#E5484D"); val off = Color.parseColor("#6F665C")
    }
    private var dp = 1f
    private lateinit var orb: View
    private lateinit var orbRing: View
    private lateinit var title: TextView
    private lateinit var subtitle: TextView
    private lateinit var main: TextView
    private lateinit var muteBtn: TextView
    private lateinit var pauseBtn: TextView
    private lateinit var markBtn: TextView
    private lateinit var statQueue: TextView
    private lateinit var statLink: TextView
    private lateinit var quick: LinearLayout
    private lateinit var statToday: TextView
    private lateinit var statLast: TextView
    private lateinit var statPc: TextView
    private lateinit var checklist: LinearLayout
    private lateinit var checkCard: LinearLayout
    private lateinit var headNote: TextView
    private lateinit var roleHome: TextView
    private lateinit var roleWear: TextView
    private lateinit var roleDesc: TextView
    private lateinit var enrollStatus: TextView
    private lateinit var enrollBtn: TextView
    private lateinit var teachBtn: TextView
    private lateinit var zonesBtn: TextView
    private var pulse: ValueAnimator? = null
    private var pcReachable: Boolean? = null

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
        // pairing for developers over USB: adb shell am start -n ... --es server URL --es token CODE (normal users scan the QR)
        val exServer = intent?.getStringExtra("server")
        val exToken = intent?.getStringExtra("token")
        if (!exServer.isNullOrBlank() && !exToken.isNullOrBlank()) Prefs.save(this, exServer, exToken)
        intent?.getStringExtra("remote")?.let { if (it.isNotBlank()) Prefs.setRemote(this, it) }
        intent?.getStringExtra("role")?.let { if (it == "wearer" || it == "home") Prefs.setRole(this, it) }

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; layoutDirection = View.LAYOUT_DIRECTION_RTL
            setPadding(px(18), px(22), px(18), px(28))
        }
        // header
        root.addView(LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
            addView(View(this@MainActivity).apply { background = getDrawable(R.mipmap.ic_launcher) },
                LinearLayout.LayoutParams(px(40), px(40)))
            addView(text("שמע", 22f, bold = true).apply { setPadding(px(10), 0, px(10), 0) })
        })
        root.gap(4)
        headNote = text("", 13f, c.faint)
        root.addView(headNote)
        root.gap(18)

        // status orb
        val orbBox = FrameLayout(this)
        orbRing = View(this).apply { background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(c.rec) }; alpha = 0f }
        orb = View(this).apply { background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(c.off) } }
        orbBox.addView(orbRing, FrameLayout.LayoutParams(px(120), px(120), Gravity.CENTER))
        orbBox.addView(orb, FrameLayout.LayoutParams(px(84), px(84), Gravity.CENTER))
        orbBox.addView(View(this).apply { background = getDrawable(R.drawable.ic_stat) },
            FrameLayout.LayoutParams(px(40), px(40), Gravity.CENTER))
        root.addView(orbBox, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, px(130)))
        title = text("", 20f, bold = true).apply { gravity = Gravity.CENTER }
        subtitle = text("", 14f, c.dim).apply { gravity = Gravity.CENTER }
        root.addView(title); root.addView(subtitle)
        root.gap(18)

        main = button("התחל להקשיב", primary = true) { toggleMain() }
        root.addView(main)
        root.gap(10)
        quick = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        pauseBtn = button("השהה") { svc(ListenService.ACTION_TOGGLE) }
        muteBtn = button("פרטי לשעה") { svc(ListenService.ACTION_MUTE_HOUR) }
        markBtn = button("סמן ⭐") { doMark(10) }
        markBtn.setOnLongClickListener {
            AlertDialog.Builder(this).setTitle("לשמור את הרגע הזה, כמה זמן לפני ואחרי?")
                .setItems(arrayOf("10 דקות", "30 דקות", "שעה", "שעתיים")) { _, i -> doMark(intArrayOf(10, 30, 60, 120)[i]) }.show()
            true
        }
        quick.addView(pauseBtn, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { marginEnd = px(8) })
        quick.addView(muteBtn, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { marginEnd = px(8) })
        quick.addView(markBtn, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        root.addView(quick)
        root.gap(10)
        root.addView(button("חיפוש ושאלות · מי דיבר", primary = true) { startActivity(Intent(this, SearchActivity::class.java)) })
        root.gap(10)
        pairBtn = button("חבר למחשב (סריקת QR)") { scanPair() }
        root.addView(pairBtn)
        root.gap(16)

        // today
        val stats = card()
        stats.addView(text("היום", 13f, c.faint))
        statToday = text("", 17f, bold = true); statLast = text("", 14f, c.dim); statPc = text("", 14f, c.dim)
        statQueue = text("", 14f, c.dim); statLink = text("", 14f, c.dim)
        stats.addView(statToday); stats.addView(statLast); stats.addView(statQueue); stats.addView(statLink); stats.addView(statPc)
        root.addView(stats)
        root.gap(12)

        // the owner's voice: needed before the personal phone records away from home
        val enrollCard = card()
        enrollCard.addView(text("הקול שלך", 13f, c.faint))
        enrollStatus = text("", 15f, c.ink)
        enrollCard.addView(enrollStatus)
        enrollBtn = button("ללמד את הקול שלי (25 שניות)") { startEnroll() }
        enrollCard.addView(View(this), LinearLayout.LayoutParams(1, px(8)))
        enrollCard.addView(enrollBtn)

        // privacy + teaching
        val tools = card()
        tools.addView(text("לימוד", 13f, c.faint))
        zonesBtn = button("אזורים פרטיים ויומן") { privacyMenu() }
        teachBtn = button("ללמד קולות (מי זה?)") { startActivity(Intent(this, TeachActivity::class.java)) }
        tools.addView(View(this), LinearLayout.LayoutParams(1, px(6)))
        tools.addView(teachBtn)
        tools.addView(text("אפשר גם לשתף לכאן הודעה קולית או הקלטת שיחה (שיתוף ← שלח לשמע) והיא תנותח במחשב.", 12f, c.faint)
            .apply { setPadding(0, px(8), 0, 0) })
        root.addView(tools)
        root.gap(12)

        // setup checklist (only what is missing)
        checkCard = card()
        checkCard.addView(text("כדי שימשיך להקשיב גם כשהאפליקציה סגורה", 14f, c.accent, bold = true))
        checklist = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        checkCard.addView(checklist)
        root.addView(checkCard)
        root.gap(12)

        // settings (collapsed): addresses, role, private words and places
        val conn = card()
        val connHead = text("הגדרות ›", 14f, c.dim)
        val connBody = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; visibility = View.GONE }
        connHead.setOnClickListener {
            connBody.visibility = if (connBody.visibility == View.GONE) View.VISIBLE else View.GONE
            connHead.text = if (connBody.visibility == View.GONE) "הגדרות ›" else "הגדרות ⌄"
        }
        val server = EditText(this).apply { setText(Prefs.server(this@MainActivity)); setTextColor(c.ink)
            inputType = InputType.TYPE_TEXT_VARIATION_URI; textDirection = View.TEXT_DIRECTION_LTR }
        val remote = EditText(this).apply { setText(Prefs.remote(this@MainActivity)); setTextColor(c.ink)
            hint = "http://100.x.y.z:8770"; setHintTextColor(c.faint)
            inputType = InputType.TYPE_TEXT_VARIATION_URI; textDirection = View.TEXT_DIRECTION_LTR }
        val token = EditText(this).apply { setText(Prefs.token(this@MainActivity)); setTextColor(c.ink)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD; textDirection = View.TEXT_DIRECTION_LTR }
        connBody.addView(text("כתובת בבית", 12f, c.faint)); connBody.addView(server)
        connBody.addView(text("כתובת מרחוק (Tailscale של המחשב)", 12f, c.faint)); connBody.addView(remote)
        connBody.addView(text("קוד גישה", 12f, c.faint)); connBody.addView(token)
        connBody.addView(text("את הכתובות והקוד אפשר גם להעתיק ידנית מהמסך במחשב: 📱 חבר טלפון.", 12f, c.faint))
        connBody.addView(View(this), LinearLayout.LayoutParams(1, px(8)))
        connBody.addView(button("שמור ובדוק חיבור") {
            Prefs.save(this, server.text.toString(), token.text.toString()); Prefs.setRemote(this, remote.text.toString()); checkPc()
        })
        connBody.addView(View(this), LinearLayout.LayoutParams(1, px(12)))
        // role
        val roleCard = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        roleCard.addView(text("תפקיד הטלפון", 12f, c.faint))
        val roleRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        roleHome = button("טלפון בית") { setRole("home") }
        roleWear = button("טלפון אישי") { setRole("wearer") }
        roleRow.addView(roleHome, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { marginEnd = px(8) })
        roleRow.addView(roleWear, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        roleCard.addView(roleRow)
        roleDesc = text("", 13f, c.dim).apply { setPadding(0, px(8), 0, 0) }
        roleCard.addView(roleDesc)
        
        connBody.addView(roleCard)
        connBody.addView(View(this), LinearLayout.LayoutParams(1, px(12)))
        connBody.addView(button("מילים פרטיות ביומן") { editCalWords() })
        connBody.addView(View(this), LinearLayout.LayoutParams(1, px(8)))
        connBody.addView(button("אזורים פרטיים ויומן · הוסף את המקום הנוכחי") { privacyMenu() })
        connBody.addView(View(this), LinearLayout.LayoutParams(1, px(12)))
        connBody.addView(enrollCard)
        conn.addView(connHead); conn.addView(connBody)
        root.addView(conn)

        setContentView(ScrollView(this).apply { setBackgroundColor(c.bg); addView(root) })
        serverField = server; remoteField = remote; tokenField = token
        checkPc()
        tick()
        val link = intent?.data?.toString()
        if (!Prefs.flag(this, "welcomed")) welcome(link)
        else if (Prefs.parsePair(link) != null) confirmPair(link!!)
        // opening the app starts listening (the app is in front, so Android allows the microphone).
        // "Off" stops it until the app is opened again.
        else if (!ListenService.on && Prefs.paired(this)) start()
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        intent?.data?.toString()?.let { if (Prefs.parsePair(it) != null) confirmPair(it) }
    }

    override fun onResume() { super.onResume(); refreshChecklist() }

    // ------------------------------------------------------------ first run + pairing
    private var serverField: EditText? = null
    private var remoteField: EditText? = null
    private var tokenField: EditText? = null
    private lateinit var pairBtn: TextView

    /** First run: what the app does, that only speech is kept and only on the user's own PC, and consent. */
    private fun welcome(link: String?) {
        val msg = "שמע מקשיב ברקע ושומר רק קטעים שיש בהם דיבור. השקט והרעש נזרקים כבר בטלפון.\n\n" +
            "ההקלטות נשלחות רק למחשב שלך, בבית (או דרך Tailscale אם הגדרת). שם הן מתומללות ומנותחות. " +
            "שום דבר לא עולה לענן, ואין לנו שרת.\n\n" +
            "לפני שמתחילים: ספר לבני הבית ולמי שמדבר איתך שאתה מקליט. הקלטה של שיחה שאינך משתתף בה " +
            "(למשל טלפון בית שמקליט כשאתה לא שם) עלולה להיות אסורה בחוק. האחריות עליך.\n\n" +
            "אפשר תמיד: השהה, פרטי לשעה, אזורים פרטיים, או כבה."
        AlertDialog.Builder(this).setTitle("ברוך הבא לשמע").setMessage(msg).setCancelable(false)
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
            .setPrompt("סרוק את ה-QR שבמסך \"שמע\" במחשב (📱 חבר טלפון)")
            .setBeepEnabled(false).setOrientationLocked(false).initiateScan()
    }

    @Deprecated("Activity result of the QR scanner")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        val r = com.google.zxing.integration.android.IntentIntegrator.parseActivityResult(requestCode, resultCode, data)
        if (r == null) { super.onActivityResult(requestCode, resultCode, data); return }
        val txt = r.contents ?: return
        if (Prefs.parsePair(txt) == null) {
            Toast.makeText(this, "זה לא QR של שמע. פתח במחשב את המסך של שמע ← 📱 חבר טלפון.", Toast.LENGTH_LONG).show(); return
        }
        confirmPair(txt)
    }

    /** Save what the QR / link carries, after the user sees where the recordings will go. */
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
                if (!ListenService.on) start()
            }.setNegativeButton("בטל", null).show()
    }

    // ------------------------------------------------------------ actions
    private fun setRole(r: String) {
        Prefs.setRole(this, r); refreshChecklist()
        Toast.makeText(this, if (r == "wearer") "טלפון אישי: מקליט גם בחוץ, אחרי שהקול שלך נלמד" else "טלפון בית: מקליט רק בבית", Toast.LENGTH_LONG).show()
    }

    private val passage = "קרא בקול רגיל, בלי למהר: \"היום בבוקר קמתי מוקדם, שתיתי קפה והסתכלתי מהחלון על הרחוב. " +
        "אחר כך יצאתי לסידורים, דיברתי עם כמה אנשים ובסוף חזרתי הביתה. אני רוצה שהמחשב יכיר את הקול שלי " +
        "גם כשאני בחוץ, ברחוב רועש או בתוך מכונית.\""

    private fun startEnroll() {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) { start(); return }
        if (!ListenService.on) start()
        ui.postDelayed({ svc(ListenService.ACTION_ENROLL) }, if (ListenService.on) 0 else 1500)
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

    /** The star. Obvious feedback: toast, the button changes for a moment, and the phone vibrates twice. */
    private fun doMark(min: Int) {
        if (!ListenService.on) { Toast.makeText(this, "ההקשבה כבויה, אין מה לסמן. הפעל קודם.", Toast.LENGTH_LONG).show(); return }
        svc(ListenService.ACTION_MARK, min)
        Toast.makeText(this, "⭐ הרגע סומן. נשמרות $min דקות לפני ואחרי, והשיחה לא תימחק.", Toast.LENGTH_LONG).show()
        markBtn.text = "✓ סומן"
        markBtn.background = round(c.sage, 16)
        markBtn.setTextColor(c.accentInk)
        ui.postDelayed({ markBtn.text = "סמן ⭐"; markBtn.background = round(c.surface2, 16, Color.parseColor("#33FFECD6")); markBtn.setTextColor(c.ink) }, 2500)
    }

    private fun toggleMain() { if (ListenService.on) stop() else start() }

    private fun start() {
        Prefs.setWanted(this, true)
        val need = arrayOf(Manifest.permission.RECORD_AUDIO, Manifest.permission.POST_NOTIFICATIONS)
            .filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (need.isNotEmpty()) { requestPermissions(need.toTypedArray(), 1); return }
        startForegroundService(Intent(this, ListenService::class.java))
        if (!batteryOk()) askBattery()
        else if (!locOk()) requestPermissions(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION), 3)
    }

    private fun stop() {
        Prefs.setWanted(this, false)
        startService(Intent(this, ListenService::class.java).setAction(ListenService.ACTION_STOP))
    }

    private fun svc(action: String, min: Int = 0) {
        if (ListenService.on) startService(Intent(this, ListenService::class.java).setAction(action).apply { if (min > 0) putExtra("min", min) })
    }

    override fun onRequestPermissionsResult(rc: Int, perms: Array<out String>, res: IntArray) {
        if (rc == 5) {                                    // camera for the QR
            if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) scanPair()
            else Toast.makeText(this, "בלי מצלמה: הגדרות ← הזן ידנית את הכתובת והקוד מהמסך במחשב", Toast.LENGTH_LONG).show()
            return
        }
        // (re)start: a service started before the location grant must be told again so it can add
        // the location type and read the Wi-Fi name
        if (rc != 4 && checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED)
            startForegroundService(Intent(this, ListenService::class.java))
        refreshChecklist()
    }

    private fun locOk() = checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
    private fun locOn() = (getSystemService(LOCATION_SERVICE) as android.location.LocationManager).isLocationEnabled

    private fun batteryOk() = (getSystemService(POWER_SERVICE) as PowerManager).isIgnoringBatteryOptimizations(packageName)

    private fun askBattery() {
        try { startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName"))) }
        catch (e: Exception) { startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName"))) }
    }

    private fun vendor() = android.os.Build.MANUFACTURER.lowercase()
    private fun isColor() = vendor().let { it.contains("oppo") || it.contains("realme") || it.contains("oneplus") }

    /** Xiaomi / ColorOS (OPPO, realme, OnePlus) / vivo / Samsung kill background apps unless the app is allowed
     *  to start by itself. Android cannot tell us whether it is, so the user taps and we only remember the tap. */
    private fun openAutostart() {
        Prefs.setAutostartDone(this)
        val v = vendor()
        val comps = when {
            v.contains("xiaomi") || v.contains("redmi") || v.contains("poco") ->
                listOf("com.miui.securitycenter" to "com.miui.permcenter.autostart.AutoStartManagementActivity")
            isColor() -> listOf(
                "com.coloros.safecenter" to "com.coloros.safecenter.permission.startup.StartupAppListActivity",
                "com.coloros.safecenter" to "com.coloros.safecenter.startupapp.StartupAppListActivity",
                "com.oppo.safe" to "com.oppo.safe.permission.startup.StartupAppListActivity",
                "com.coloros.oppoguardelf" to "com.coloros.powermanager.fuelgaue.PowerUsageModelActivity",
                "com.oneplus.security" to "com.oneplus.security.chainlaunch.view.ChainLaunchAppListActivity")
            v.contains("vivo") -> listOf("com.vivo.permissionmanager" to "com.vivo.permissionmanager.activity.BgStartUpManagerActivity")
            v.contains("samsung") -> listOf("com.samsung.android.lool" to "com.samsung.android.sm.ui.battery.BatteryActivity")
            else -> emptyList()
        }
        val tries = comps.map { Intent().setClassName(it.first, it.second) } +
            Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName"))
        for (t in tries) try { startActivity(t); return } catch (e: Exception) { }
    }

    private fun checkPc() {
        thread {
            fun ping(base: String, ms: Int) = base.isNotEmpty() && try {
                val h = URL("$base/home/api/status").openConnection() as HttpURLConnection
                h.connectTimeout = ms; h.readTimeout = ms
                val code = h.responseCode; h.disconnect(); code == 200
            } catch (e: Exception) { false }
            val ok = ping(Prefs.server(this), 2500) || ping(Prefs.remote(this), 5000)
            pcReachable = ok
            ui.post { refreshChecklist() }
        }
    }

    // ------------------------------------------------------------ checklist
    private fun refreshChecklist() {
        if (!::checklist.isInitialized) return
        checklist.removeAllViews()
        val items = mutableListOf<Triple<String, Boolean, (() -> Unit)?>>()
        items += Triple("מחובר למחשב (סריקת QR)", Prefs.paired(this), { scanPair() })
        items += Triple("גישה למיקרופון", checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED,
            { requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 1) })
        items += Triple("התראות", checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED,
            { requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 2) })
        items += Triple("סוללה: ללא הגבלות", batteryOk(), { askBattery() })
        items += Triple("הרשאת מיקום (לזיהוי רשת הבית)", locOk(),
            { requestPermissions(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION), 3) })
        items += Triple("מיקום מופעל בטלפון", locOn(), { startActivity(Intent(Settings.ACTION_LOCATION_SOURCE_SETTINGS)) })
        val home = Prefs.homeSsid(this)
        val now = ListenService.ssidNow
        items += Triple(if (home.isEmpty()) "רשת הבית: תילמד כשהמחשב יענה" else "רשת הבית: $home", home.isNotEmpty(),
            if (now.isNotEmpty()) ({ Prefs.setHomeSsid(this, now); refreshChecklist() }) else null)
        items += Triple("הפעלה אוטומטית (" + android.os.Build.MANUFACTURER + ")", Prefs.autostartDone(this), { openAutostart() })
        items += Triple("יומן (אופציונלי: השתקה באירועים פרטיים)", checkSelfPermission(Manifest.permission.READ_CALENDAR) == PackageManager.PERMISSION_GRANTED,
            { requestPermissions(arrayOf(Manifest.permission.READ_CALENDAR), 4) })
        // Tailscale: the way to the PC when away from home
        val vpn = ListenService.vpnOn
        if (Prefs.remote(this).isEmpty()) items += Triple("כתובת Tailscale של המחשב לא הוגדרה (בלי זה אין שליחה בחוץ)", false, { settingsHint() })
        else if (!vpn) items += Triple("Tailscale כבוי בטלפון", false, { openTailscale() })
        if (Prefs.role(this) == "wearer") items += Triple("הקול שלך נלמד", ListenService.enrolled >= ListenService.minSamples,
            { startEnroll() })
        if (isColor()) {
            items += Triple("ColorOS: פעילות ברקע ללא הגבלה", Prefs.flag(this, "bg_done"), { Prefs.setFlag(this, "bg_done"); openAutostart(); refreshChecklist() })
            items += Triple("ColorOS: נעל את שמע במסך האחרונים (הכרטיס ← מנעול)", Prefs.flag(this, "lock_done"), { Prefs.setFlag(this, "lock_done"); refreshChecklist() })
        }
        items += Triple("המחשב זמין", pcReachable == true || ListenService.pcOnline, { checkPc() })
        val missing = items.filter { !it.second }
        checkCard.visibility = View.VISIBLE
        if (missing.isEmpty()) {
            checklist.addView(text("✓ הכל מוכן. אפשר לסגור את האפליקציה, ההקשבה ממשיכה ברקע.", 14f, c.sage))
            return
        }
        for ((label, _, fix) in missing) {                     // only what is missing
            val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL; setPadding(0, px(8), 0, 0) }
            row.addView(text("!", 16f, c.rose, bold = true).apply { setPadding(0, 0, px(10), 0) })
            row.addView(text(label, 15f, c.ink), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            if (fix != null) row.addView(button(if (label.startsWith("רשת הבית")) "זו הרשת" else if (label.startsWith("ColorOS")) "עשיתי"
                else if (label.startsWith("מחובר למחשב")) "סרוק" else "תקן") { fix() })
            checklist.addView(row)
        }
    }

    private fun settingsHint() {
        Toast.makeText(this, "פתח הגדרות ← כתובת מרחוק והדבק את כתובת ה-Tailscale של המחשב", Toast.LENGTH_LONG).show()
    }

    private fun openTailscale() {
        val i = packageManager.getLaunchIntentForPackage("com.tailscale.ipn")
        if (i != null) startActivity(i) else Toast.makeText(this, "Tailscale לא מותקן בטלפון", Toast.LENGTH_LONG).show()
    }

    // ------------------------------------------------------------ live status (every second)
    private fun tick() {
        val S = ListenService
        val now = System.currentTimeMillis()
        val muted = S.mutedUntilNow > now
        val wear = Prefs.role(this) == "wearer"
        val (color, head, sub) = when {
            !S.on -> Triple(c.off, "כבוי", "לא מקליט. לחץ \"התחל להקשיב\".")
            S.enrollUntilNow > now -> Triple(c.rec, "לומד את הקול שלך", "קרא בקול את הטקסט שלמטה")
            S.silencedNow -> Triple(c.accent, "המיקרופון תפוס", "שיחה או אפליקציה אחרת משתמשות בו. זה נרשם כפער.")
            S.pausedNow -> Triple(c.accent, "מושהה", "לא מקליט עד שתלחץ \"המשך\".")
            muted -> Triple(c.accent, "מושתק", "חוזר להקשיב ב-" + java.text.SimpleDateFormat("HH:mm", java.util.Locale.US).format(java.util.Date(S.mutedUntilNow)))
            S.blocked.startsWith("מחוץ לבית") && !wear -> Triple(c.off, "מחוץ לבית", if (Prefs.homeSsid(this).isEmpty())
                "רשת הבית עוד לא נלמדה: היא תילמד כשהמחשב יענה." else "לא מחובר לרשת " + Prefs.homeSsid(this) + ", לכן לא מקליט.")
            S.blocked.isNotEmpty() -> Triple(c.off, if (S.blocked.startsWith("אזור פרטי")) "פרטי" else "לא מקליט", S.stateLine)
            S.hearing -> Triple(c.rec, "שומע דיבור", S.stateLine)
            else -> Triple(c.sage, "מקשיב", S.stateLine)
        }
        (orb.background as GradientDrawable).setColor(color)
        title.text = head; subtitle.text = sub
        setPulse(S.on && S.blocked.isEmpty() && !S.pausedNow && !muted, if (S.hearing) c.rec else c.sage)
        headNote.text = if (wear) "מקליט גם בחוץ, שומר רק שיחות שאתה משתתף בהן, ושולח רק למחשב שלך (בבית או דרך Tailscale)."
            else "מקליט רק בבית, שומר רק דיבור, ושולח רק למחשב שלך."
        roleHome.background = round(if (!wear) c.accent else c.surface2, 16, if (!wear) null else Color.parseColor("#33FFECD6"))
        roleHome.setTextColor(if (!wear) c.accentInk else c.ink)
        roleWear.background = round(if (wear) c.accent else c.surface2, 16, if (wear) null else Color.parseColor("#33FFECD6"))
        roleWear.setTextColor(if (wear) c.accentInk else c.ink)
        roleDesc.text = if (wear) "בחוץ: ההקלטות נשמרות בטלפון ויישלחו כשתחזור הביתה. המחשב ימחק כל שיחה שהקול שלך לא בה."
            else "מקליט רק כשהוא ברשת הבית או כשהמחשב עונה."
        val left = ((S.enrollUntilNow - now) / 1000).toInt()
        if (left > 0) { enrollStatus.text = passage + "\n\nנשארו $left שניות"; enrollBtn.visibility = View.GONE }
        else {
            enrollBtn.visibility = View.VISIBLE
            enrollStatus.text = when {
                S.enrolled < 0 -> "עוד לא ידוע (המחשב צריך לענות)"
                S.enrolled >= S.minSamples -> "✓ הקול שלך נלמד בטלפון הזה (${S.enrolled} דגימות)"
                else -> "עוד לא נלמד" + if (wear) ": בלי זה הטלפון לא מקליט מחוץ לבית" else ""
            }
        }
        teachBtn.text = "ללמד קולות (מי זה?)" + if (S.digestTeach > 0) " · ${S.digestTeach} ממתינים" else ""
        main.text = if (S.on) "כבה" else "התחל להקשיב"
        main.background = round(if (S.on) c.surface2 else c.accent, 16, if (S.on) Color.parseColor("#33FFECD6") else null)
        main.setTextColor(if (S.on) c.ink else c.accentInk)
        quick.visibility = if (S.on) View.VISIBLE else View.GONE
        pauseBtn.text = if (S.pausedNow) "המשך" else "השהה"
        muteBtn.text = if (muted) "בטל פרטי" else "פרטי לשעה"
        if (muted) muteBtn.setOnClickListener { svc(ListenService.ACTION_UNMUTE) }
        else muteBtn.setOnClickListener { svc(ListenService.ACTION_MUTE_HOUR) }
        val n = ListenService.sentToday(this)
        val mins = ListenService.speechToday(this)
        statToday.text = if (mins == 0 && n == 0) "עוד לא הוקלט דיבור היום" else "$mins דקות דיבור הוקלטו · $n קטעים נשלחו"
        statLast.text = if (S.lastSentAt > 0) "נשלח לאחרונה: לפני ${ago(now - S.lastSentAt)}" else ""
        statQueue.text = "ממתינים: ${S.queued} · ${"%.1f".format(java.util.Locale.US, S.queuedBytes / 1e6)} MB" +
            (if (S.oldestMs > 0 && S.queued > 0) " · הישן מלפני ${ago(now - S.oldestMs)}" else "")
        statQueue.text = statQueue.text.toString() + (if (ListenService.marksToday(this) > 0) "\n⭐ ${ListenService.marksToday(this)} רגעים סומנו היום" else "")
        statLink.text = "חיבור: " + when { S.lanOk -> "בית"; S.viaTailscale -> "Tailscale"; else -> "אין" }
        pairBtn.visibility = if (Prefs.paired(this)) View.GONE else View.VISIBLE
        statPc.text = when {
            S.pcOnline -> "המחשב מחובר · הניתוח נעשה שם"
            S.on -> "המחשב לא זמין · ההקלטות נשמרות בטלפון ויישלחו כשיחזור"
            else -> ""
        }
        ui.postDelayed({ tick() }, 1000)
    }

    private fun ago(ms: Long): String {
        val s = ms / 1000
        return when { s < 60 -> "$s שנ׳"; s < 3600 -> "${s / 60} דק׳"; else -> "${s / 3600} שעות" }
    }

    private fun setPulse(on: Boolean, color: Int) {
        (orbRing.background as GradientDrawable).setColor(color)
        if (on && pulse == null) {
            pulse = ValueAnimator.ofFloat(0f, 1f).apply {
                duration = 1600; repeatCount = ValueAnimator.INFINITE
                addUpdateListener { a ->
                    val f = a.animatedValue as Float
                    orbRing.scaleX = 0.7f + f * 0.45f; orbRing.scaleY = orbRing.scaleX; orbRing.alpha = 0.45f * (1 - f)
                }
                start()
            }
        } else if (!on && pulse != null) {
            pulse?.cancel(); pulse = null; orbRing.alpha = 0f
        }
    }

    override fun onDestroy() { pulse?.cancel(); super.onDestroy() }
}
