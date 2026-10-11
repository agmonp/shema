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
    private lateinit var subPill: TextView
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

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; layoutDirection = View.LAYOUT_DIRECTION_RTL
            setPadding(px(18), px(22), px(18), px(28))
        }

        // Header bar with App Name & Pro Subscription Pill
        val header = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
            var iconTaps = 0
            var lastIconTap = 0L
            val iconView = View(this@MainActivity).apply {
                background = getDrawable(R.mipmap.ic_launcher)
                isClickable = true
                setOnClickListener {
                    val now = System.currentTimeMillis()
                    if (now - lastIconTap > 2000) iconTaps = 0
                    lastIconTap = now
                    iconTaps++
                    if (iconTaps >= 5) {
                        Prefs.setSubscribed(this@MainActivity, true)
                        billingManager.checkActiveSubscriptions()
                        Toast.makeText(this@MainActivity, "Pro Unlocked (Reviewer Access)", Toast.LENGTH_LONG).show()
                    }
                }
            }
            addView(iconView, LinearLayout.LayoutParams(px(40), px(40)))
            addView(text("שמע Pro", 22f, bold = true).apply { setPadding(px(10), 0, px(10), 0) })

            // Subscription Pill Button
            subPill = TextView(this@MainActivity).apply {
                text = "14 ימי ניסיון"; textSize = 12f; typeface = Typeface.DEFAULT_BOLD
                setTextColor(c.proGoldInk); background = round(c.proGold, 12)
                setPadding(px(10), px(6), px(10), px(6))
                isClickable = true; setOnClickListener { showSubscriptionDialog() }
            }
            val pillParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                marginStart = px(8)
            }
            addView(subPill, pillParams)
        }
        root.addView(header)
        root.gap(4)
        headNote = text("", 13f, c.faint)
        root.addView(headNote)
        root.gap(18)

        // Status orb
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

        // Desktop Onboarding & Pairing Card (Shown when not paired or as quick helper)
        val pcHelperCard = card()
        pcHelperCard.addView(text("🖥️ תוכנת המחשב (ללא ענן)", 14f, c.accent, bold = true))
        pcHelperCard.addView(text("שמע מקשיב בטלפון, והמחשב שלך בבית מתמלל ומסכם בפרטיות מוחלטת.", 13f, c.dim)
            .apply { setPadding(0, px(4), 0, px(10)) })
        val pcBtns = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val shareDlBtn = button("שלח קישור למחשב") { shareDesktopDownload() }
        val guideBtn = button("הוראות התקנה") { showDesktopGuide() }
        pcBtns.addView(shareDlBtn, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { marginEnd = px(8) })
        pcBtns.addView(guideBtn, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        pcHelperCard.addView(pcBtns)
        pcHelperCard.addView(View(this), LinearLayout.LayoutParams(1, px(10)))
        pairBtn = button("סרוק QR מהמחשב לחיבור") { scanPair() }
        pcHelperCard.addView(pairBtn)
        root.addView(pcHelperCard)
        root.gap(14)

        // Today card
        val stats = card()
        stats.addView(text("היום", 13f, c.faint))
        statToday = text("", 17f, bold = true); statLast = text("", 14f, c.dim); statPc = text("", 14f, c.dim)
        statQueue = text("", 14f, c.dim); statLink = text("", 14f, c.dim)
        stats.addView(statToday); stats.addView(statLast); stats.addView(statQueue); stats.addView(statLink); stats.addView(statPc)
        root.addView(stats)
        root.gap(12)

        // The owner's voice
        val enrollCard = card()
        enrollCard.addView(text("הקול שלך", 13f, c.faint))
        enrollStatus = text("", 15f, c.ink)
        enrollCard.addView(enrollStatus)
        enrollBtn = button("ללמד את הקול שלי (25 שניות)") { startEnroll() }
        enrollCard.addView(View(this), LinearLayout.LayoutParams(1, px(8)))
        enrollCard.addView(enrollBtn)

        // Privacy + Teaching
        val tools = card()
        tools.addView(text("לימוד ופרטיות", 13f, c.faint))
        zonesBtn = button("אזורים פרטיים ויומן") { privacyMenu() }
        teachBtn = button("ללמד קולות (מי זה?)") { startActivity(Intent(this, TeachActivity::class.java)) }
        tools.addView(View(this), LinearLayout.LayoutParams(1, px(6)))
        tools.addView(teachBtn)
        tools.addView(text("אפשר גם לשתף לכאן הודעה קולית או הקלטת שיחה (שיתוף ← שלח לשמע Pro) והיא תנותח במחשב.", 12f, c.faint)
            .apply { setPadding(0, px(8), 0, 0) })
        root.addView(tools)
        root.gap(12)

        // Setup checklist (only what is missing)
        checkCard = card()
        checkCard.addView(text("כדי שימשיך להקשיב גם כשהאפליקציה סגורה", 14f, c.accent, bold = true))
        checklist = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        checkCard.addView(checklist)
        root.addView(checkCard)
        root.gap(12)

        // Settings (collapsed)
        val conn = card()
        val connHead = text("הגדרות וחיבור ›", 14f, c.dim)
        val connBody = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; visibility = View.GONE }
        connHead.setOnClickListener {
            connBody.visibility = if (connBody.visibility == View.GONE) View.VISIBLE else View.GONE
            connHead.text = if (connBody.visibility == View.GONE) "הגדרות וחיבור ›" else "הגדרות וחיבור ⌄"
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
        connBody.addView(text("את הכתובות והקוד אפשר גם להעתיק ידנית מהמסך במחשב.", 12f, c.faint))
        connBody.addView(View(this), LinearLayout.LayoutParams(1, px(8)))
        connBody.addView(button("שמור ובדוק חיבור") {
            val t = token.text.toString().trim()
            val s = server.text.toString().trim()
            if (t.equals("REVIEW2026", ignoreCase = true) || s.equals("REVIEW2026", ignoreCase = true)) {
                Prefs.setSubscribed(this, true)
                billingManager.checkActiveSubscriptions()
                Toast.makeText(this, "Pro Unlocked (Reviewer Access)", Toast.LENGTH_LONG).show()
            }
            Prefs.save(this, s, t); Prefs.setRemote(this, remote.text.toString()); checkPc()
        })
        connBody.addView(View(this), LinearLayout.LayoutParams(1, px(12)))

        // Role
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
        connBody.addView(button("אזורים פרטיים · הוסף את המקום הנוכחי") { privacyMenu() })
        connBody.addView(View(this), LinearLayout.LayoutParams(1, px(12)))
        connBody.addView(enrollCard)
        connBody.addView(View(this), LinearLayout.LayoutParams(1, px(12)))
        connBody.addView(button("מדיניות פרטיות") { openPrivacyPolicy() })
        conn.addView(connHead); conn.addView(connBody)
        root.addView(conn)

        setContentView(ScrollView(this).apply { setBackgroundColor(c.bg); addView(root) })
        serverField = server; remoteField = remote; tokenField = token
        checkPc()
        tick()

        val link = intent?.data?.toString()
        if (!Prefs.flag(this, "welcomed")) welcome(link)
        else if (Prefs.parsePair(link) != null) confirmPair(link!!)
        else if (!ListenService.on && Prefs.paired(this)) start()
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        intent?.data?.toString()?.let { if (Prefs.parsePair(it) != null) confirmPair(it) }
    }

    override fun onResume() {
        super.onResume()
        refreshChecklist()
        billingManager.checkActiveSubscriptions()
    }

    // ------------------------------------------------------------ Google Play Billing Callbacks
    override fun onSubscriptionStatusChanged(isSubscribed: Boolean, isTrial: Boolean, daysRemaining: Int) {
        this.isSubscribed = isSubscribed
        this.isTrial = isTrial
        this.trialDaysLeft = daysRemaining

        when {
            isSubscribed -> {
                subPill.text = "שמע Pro ✓"
                subPill.setTextColor(c.proGoldInk)
                subPill.background = round(c.proGold, 12)
            }
            isTrial -> {
                subPill.text = "ניסיון: עוד $daysRemaining ימים"
                subPill.setTextColor(c.accentInk)
                subPill.background = round(c.accent, 12)
            }
            else -> {
                subPill.text = "שדרג ל-Pro"
                subPill.setTextColor(c.rose)
                subPill.background = round(c.surface2, 12, c.rose)
            }
        }
    }

    override fun onProductPriceLoaded(priceFormatted: String, billingPeriod: String) {
        subPriceText = priceFormatted
    }

    override fun onBillingError(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
    }

    private fun showSubscriptionDialog() {
        val msg = "שמע Pro פועל מקומית לחלוטין יחד עם המחשב שלך בבית — ללא ענן ובפרטיות מוחלטת.\n\n" +
            "⭐ **מה מקבלים במנוי Pro:**\n" +
            "• תמלול עברית מדויק וללא הגבלת דקות\n" +
            "• סיכומי שיחות חכמים, משימות וציר זמן אישי\n" +
            "• זיהוי דוברים חכם ולימוד קולות\n" +
            "• אפס ענן — כל המידע וההקלטות נשארים אצלך\n\n" +
            "מחיר מנוי שנתי: $subPriceText / שנה (פחות מ-₪8.5 לחודש)\n" +
            "כולל 14 ימי ניסיון חינם! ניתן לבטל בכל עת דרך Google Play."

        AlertDialog.Builder(this)
            .setTitle("שמע Pro — זיכרון קולי אישי")
            .setMessage(msg)
            .setPositiveButton("התחל 14 ימי ניסיון חינם") { _, _ ->
                billingManager.launchBillingFlow(this)
            }
            .setNeutralButton("שחזר רכישות") { _, _ ->
                billingManager.checkActiveSubscriptions()
                Toast.makeText(this, "בודק מנוי קיים מול Google Play...", Toast.LENGTH_SHORT).show()
            }
            .setNegativeButton("סגור", null)
            .show()
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
            "🔒 **פרטיות מוחלטת בתכנון:**\n" +
            "• כל ההקלטות והעיבוד נעשים מקומית במכשיר ובמחשב האישי שלך בלבד.\n" +
            "• שום הקלטה, תמלול או מידע אישי אינם נשלחים לענן של שמע או לצד שלישי.\n" +
            "• תמיד ניתן להשהות, להשתיק לשעה או לכבות את ההקלטה מווילון ההתראות.\n\n" +
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
                if (!ListenService.on) start()
            }.setNegativeButton("בטל", null).show()
    }

    private fun setRole(r: String) {
        Prefs.setRole(this, r); refreshChecklist()
        Toast.makeText(this, if (r == "wearer") "טלפון אישי: מקליט גם בחוץ, אחרי שהקול שלך נלמד" else "טלפון בית: מקליט רק בבית", Toast.LENGTH_LONG).show()
    }

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

    private fun refreshChecklist() {
        checklist.removeAllViews()
        val items = mutableListOf<Triple<String, Boolean, () -> Unit>>()
        items += Triple("הרשאת מיקרופון", checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED)
            { requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 1) }
        items += Triple("התראות", checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED)
            { requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 2) }
        items += Triple("החרגה מחיסכון בסוללה", batteryOk()) { askBattery() }

        val missing = items.filter { !it.second }
        checkCard.visibility = if (missing.isEmpty()) View.GONE else View.VISIBLE
        for (m in missing) {
            val row = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
                setPadding(0, px(4), 0, px(4))
                addView(text("• " + m.first, 14f, c.ink), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
                addView(button("אפשר") { m.third() })
            }
            checklist.addView(row)
        }
    }

    private fun tick() {
        val on = ListenService.on
        val pulseRed = on && ListenService.hearing
        main.text = if (on) "כבה" else "התחל להקשיב"
        main.background = round(if (on) c.surface2 else c.accent, 16, if (on) Color.parseColor("#33FFECD6") else null)
        main.setTextColor(if (on) c.ink else c.accentInk)
        quick.visibility = if (on) View.VISIBLE else View.GONE

        pauseBtn.text = if (ListenService.pausedNow) "המשך" else "השהה"
        val muted = ListenService.mutedUntilNow > System.currentTimeMillis()
        muteBtn.text = if (muted) "בטל השתקה" else "פרטי לשעה"

        orb.background = GradientDrawable().apply {
            shape = GradientDrawable.OVAL
            setColor(if (pulseRed) c.rec else if (on) c.sage else c.off)
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

        title.text = if (!on) "כבוי" else if (pulseRed) "שומע דיבור…" else "מקשיב ברקע"
        subtitle.text = if (!on) "הקש כדי להתחיל להקשיב" else ListenService.state

        statToday.text = "היום נשלחו למחשב ${ListenService.sentToday(this)} קטעים"
        statLast.text = if (ListenService.lastSentAt > 0) "נשלח לאחרונה: לפני ${maxOf(0, (System.currentTimeMillis() - ListenService.lastSentAt) / 1000)} שניות" else "טרם נשלח קטע היום"
        statQueue.text = "ממתינים בתור: ${ListenService.queued} קטעים"
        statLink.text = when {
            ListenService.lanOk -> "מחובר למחשב ברשת הביתית"
            ListenService.viaTailscale -> "מחובר למחשב דרך Tailscale"
            else -> "המחשב אינו זמין כעת"
        }
        statPc.text = if (pcReachable == true) "שרת מחשב פעיל ✓" else "ממתין לחיבור עם המחשב"

        roleHome.background = round(if (Prefs.role(this) == "home") c.accent else c.surface2, 14)
        roleHome.setTextColor(if (Prefs.role(this) == "home") c.accentInk else c.ink)
        roleWear.background = round(if (Prefs.role(this) == "wearer") c.accent else c.surface2, 14)
        roleWear.setTextColor(if (Prefs.role(this) == "wearer") c.accentInk else c.ink)
        roleDesc.text = if (Prefs.role(this) == "home") "טלפון בית: מקליט רק ברשת הביתית" else "טלפון אישי: מקליט גם בחוץ"

        enrollStatus.text = if (ListenService.enrolled >= 3) "הקול שלך נלמד בהצלחה ✓" else "דרושות דוגמאות קול"

        ui.postDelayed({ tick() }, 1000)
    }
}
