package app.shema.listener

import android.app.Activity
import android.app.AlertDialog
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

/**
 * "Who is this?" on the phone: the PC's unnamed-voice queue, one card at a time -- listen, confirm the
 * best guess with one tap or pick / type a name. Every answer teaches the PC (it re-names similar voices).
 * Works whenever the PC answers (the home Wi-Fi); the token pairs the phone.
 */
class TeachActivity : Activity() {
    private val ui = Handler(Looper.getMainLooper())
    private val col = object {
        val bg = Color.parseColor("#13100E"); val surface = Color.parseColor("#1C1815"); val surface2 = Color.parseColor("#25201C")
        val ink = Color.parseColor("#F4EDE5"); val dim = Color.parseColor("#B1A597"); val accent = Color.parseColor("#EAA45E")
        val accentInk = Color.parseColor("#1B130B"); val sage = Color.parseColor("#86BBA8"); val rose = Color.parseColor("#E48A7F")
    }
    private var dp = 1f
    private lateinit var body: LinearLayout
    private var items = JSONArray()
    private var people = JSONArray()
    private var idx = 0
    private var left = 0
    private var done = 0
    private var goal = 0
    private var doneToday = 0
    private var player: MediaPlayer? = null

    private fun px(v: Int) = (v * dp).toInt()
    private fun round(color: Int, r: Int) = GradientDrawable().apply { setColor(color); cornerRadius = px(r).toFloat() }
    private fun text(t: String, size: Float, color: Int = col.ink, bold: Boolean = false) = TextView(this).apply {
        text = t; textSize = size; setTextColor(color); if (bold) typeface = Typeface.DEFAULT_BOLD
    }
    private fun button(t: String, primary: Boolean = false, onClick: () -> Unit) = TextView(this).apply {
        text = t; textSize = if (primary) 18f else 15f; gravity = Gravity.CENTER
        setTextColor(if (primary) col.accentInk else col.ink); typeface = Typeface.DEFAULT_BOLD
        background = round(if (primary) col.accent else col.surface2, 16)
        setPadding(px(16), px(if (primary) 16 else 12), px(16), px(if (primary) 16 else 12))
        isClickable = true; setOnClickListener { onClick() }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        dp = resources.displayMetrics.density
        body = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; layoutDirection = View.LAYOUT_DIRECTION_RTL
            setPadding(px(18), px(22), px(18), px(28))
        }
        setContentView(ScrollView(this).apply { setBackgroundColor(col.bg); addView(body) })
        load()
    }

    override fun onDestroy() { player?.release(); super.onDestroy() }

    // ------------------------------------------------------------ network (token header, run off the main thread)
    private fun call(method: String, path: String, json: JSONObject? = null): String? = try {
        val c = URL(Prefs.base(this) + path).openConnection() as HttpURLConnection
        c.requestMethod = method; c.connectTimeout = 4000; c.readTimeout = 120000
        c.setRequestProperty("X-Home-Token", Prefs.token(this))
        if (json != null) {
            val b = json.toString().toByteArray()
            c.doOutput = true; c.setRequestProperty("Content-Type", "application/json"); c.setFixedLengthStreamingMode(b.size)
            c.outputStream.use { it.write(b) }
        }
        val r = if (c.responseCode == 200) c.inputStream.bufferedReader().readText() else null
        c.disconnect(); r
    } catch (e: Exception) { null }

    private fun load() {
        body.removeAllViews()
        body.addView(text("טוען מהמחשב…", 16f, col.dim))
        thread {
            val q = call("GET", "/home/api/teach")
            val p = call("GET", "/home/api/people")
            ui.post {
                if (q == null || p == null) { showError(); return@post }
                val j = JSONObject(q)
                items = j.getJSONArray("items"); left = j.optInt("left"); goal = j.optInt("goal"); doneToday = j.optInt("done_today"); people = JSONArray(p); idx = 0
                show()
            }
        }
    }

    private fun showError() {
        body.removeAllViews()
        body.addView(text("המחשב לא זמין", 20f, col.rose, true))
        body.addView(text("הלימוד עובד כשהטלפון ברשת הבית והמחשב ער.", 14f, col.dim))
        body.addView(View(this), LinearLayout.LayoutParams(1, px(14)))
        body.addView(button("נסה שוב") { load() })
    }

    private fun show() {
        body.removeAllViews()
        body.addView(text("מי זה?", 22f, bold = true))
        if (goal > 0) body.addView(text("לימוד חכם · ${minOf(doneToday + done, goal)}/$goal היום", 14f, col.sage, true))
        body.addView(text("$done נלמדו עכשיו · $left ממתינים במחשב", 13f, col.dim))
        body.addView(View(this), LinearLayout.LayoutParams(1, px(16)))
        if (idx >= items.length()) {
            body.addView(text("אין עוד קולות ללמד כרגע ✓", 18f, col.sage, true))
            return
        }
        val it = items.getJSONObject(idx)
        val card = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; background = round(col.surface, 18); setPadding(px(16), px(14), px(16), px(14))
        }
        card.addView(text(it.optString("t0").replace("T", " ").take(16) + " · " + "%.1f".format(it.optDouble("seconds")) + " שנ׳", 12f, col.dim))
        card.addView(text(it.optString("text"), 18f))
        card.addView(View(this), LinearLayout.LayoutParams(1, px(10)))
        val pb = button("▶ שמע") { play(it.getInt("id")) }
        playBtn = pb
        card.addView(pb)
        play(it.getInt("id"))                                  // the clip starts by itself; tap to hear it again
        body.addView(card)
        body.addView(View(this), LinearLayout.LayoutParams(1, px(12)))
        val guess = it.optString("guess")
        val gname = it.optString("guess_name")
        if (guess.isNotEmpty() && gname.isNotEmpty() && guess != "__tv__") {
            body.addView(button("זה ${gname} (ניחוש ${(it.optDouble("guess_sim") * 100).toInt()}%)", primary = true) { label(it, guess, null) })
            body.addView(View(this), LinearLayout.LayoutParams(1, px(8)))
        }
        body.addView(button("מישהו אחר…") { pick(it) })
        body.addView(View(this), LinearLayout.LayoutParams(1, px(8)))
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        row.addView(button("📺 טלוויזיה") { label(it, "__tv__", null) },
            LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { marginEnd = px(8) })
        body.addView(View(this), LinearLayout.LayoutParams(1, px(8)))
        body.addView(button("🗣 כמה מדברים / לא ברור") {
            try { player?.stop() } catch (e: Exception) { }
            val id = it.getInt("id"); idx++
            thread { call("POST", "/home/api/teach_skip", JSONObject().put("utt_id", id).put("reason", "multi")) }
            show()
        })
        body.addView(View(this), LinearLayout.LayoutParams(1, px(8)))
        row.addView(button("דלג") { try { player?.stop() } catch (e: Exception) { }; idx++; show() }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        body.addView(row)
    }

    /** The clip is downloaded first (token header, short wav) and then played from a file: MediaPlayer streaming
     *  over http with headers failed silently on some phones. The button shows what is happening. */
    private var playBtn: TextView? = null

    private fun play(id: Int) {
        val btn = playBtn
        btn?.text = "⏳ טוען…"
        thread {
            try {
                val c = URL(Prefs.base(this) + "/home/audio/utt/$id").openConnection() as HttpURLConnection
                c.connectTimeout = 4000; c.readTimeout = 30000
                c.setRequestProperty("X-Home-Token", Prefs.token(this))
                if (c.responseCode != 200) throw RuntimeException("HTTP ${c.responseCode} (ההקלטה כבר נמחקה?)")
                val f = java.io.File(cacheDir, "clip_$id.wav")
                c.inputStream.use { i -> f.outputStream().use { o -> i.copyTo(o) } }
                c.disconnect()
                ui.post {
                    try {
                        player?.release()
                        val mp = MediaPlayer()
                        player = mp
                        mp.setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
                            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
                        mp.setDataSource(f.path)
                        mp.setOnPreparedListener { p -> btn?.text = "⏸ מנגן…"; p.start() }
                        mp.setOnCompletionListener { btn?.text = "▶ שמע שוב"; f.delete() }
                        mp.setOnErrorListener { _, w, e -> btn?.text = "⚠ הנגינה נכשלה ($w/$e). הקש לנסות שוב"; true }
                        mp.prepareAsync()
                    } catch (e: Exception) { btn?.text = "⚠ ${e.message ?: "הנגינה נכשלה"}. הקש לנסות שוב" }
                }
            } catch (e: Exception) {
                ui.post { btn?.text = "⚠ ${e.message ?: "אין חיבור"}. הקש לנסות שוב" }
            }
        }
    }

    private fun pick(it: JSONObject) {
        val names = ArrayList<String>(); val ids = ArrayList<String>()
        for (i in 0 until people.length()) { val p = people.getJSONObject(i); names += p.optString("name"); ids += p.optString("id") }
        names += "+ שם חדש…"
        AlertDialog.Builder(this).setTitle("מי דיבר?")
            .setItems(names.toTypedArray()) { _, which ->
                if (which == ids.size) newName(it) else label(it, ids[which], null)
            }.show()
    }

    private fun newName(it: JSONObject) {
        val e = EditText(this).apply { inputType = InputType.TYPE_CLASS_TEXT; hint = "שם" }
        AlertDialog.Builder(this).setTitle("שם חדש").setView(e)
            .setPositiveButton("שמור") { _, _ -> val n = e.text.toString().trim(); if (n.isNotEmpty()) label(it, null, n) }
            .setNegativeButton("בטל", null).show()
    }

    private fun label(it: JSONObject, speaker: String?, newName: String?) {
        try { player?.stop() } catch (e: Exception) { }
        body.removeAllViews(); body.addView(text("שומר ומעדכן…", 16f, col.dim))
        val b = JSONObject().put("utt_id", it.getInt("id"))
        if (speaker != null) b.put("speaker", speaker)
        if (newName != null) b.put("new_name", newName)
        thread {
            val r = call("POST", "/home/api/label", b)
            ui.post {
                if (r != null) { done++; left = maxOf(0, left - 1 - JSONObject(r).optInt("renamed")) }
                idx++; show()
            }
        }
    }
}
