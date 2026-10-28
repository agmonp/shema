package com.shema.app

import android.app.Activity
import android.app.AlertDialog
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
import android.widget.ArrayAdapter
import android.widget.AutoCompleteTextView
import android.widget.BaseAdapter
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.ListView
import android.widget.PopupMenu
import android.widget.TextView
import android.widget.Toast
import org.json.JSONArray
import org.json.JSONObject
import kotlin.concurrent.thread

/**
 * One conversation on the phone (2026-10-17): the PC's speaker timeline on top, the lines under it.
 * Tap a line = hear it and see it on the timeline; tap a block on the timeline = jump to that line and hear it;
 * tap a speaker = that speaker stands out in both, with ‹ › to jump between their lines. Tap a name = "who said this":
 * after a fix the conversation is read again, so the timeline follows. The list recycles its rows (long meetings).
 * Intent extras: "id" (conversation), optional "at" (seconds since midnight to start at).
 */
class ConvActivity : Activity() {
    private val ui = Handler(Looper.getMainLooper())
    private val col = object {
        val bg = Color.parseColor("#13100E"); val surface = Color.parseColor("#1C1815"); val surface2 = Color.parseColor("#25201C")
        val ink = Color.parseColor("#F4EDE5"); val dim = Color.parseColor("#B1A597"); val faint = Color.parseColor("#958A7D")
        val accent = Color.parseColor("#EAA45E"); val accentInk = Color.parseColor("#1B130B"); val rose = Color.parseColor("#E48A7F")
        val sky = Color.parseColor("#8FB3E0"); val unk = Color.parseColor("#6F665C")
    }
    private val palette = listOf("#EAA45E", "#86BBA8", "#8FB3E0", "#E48A7F", "#C9A3E6", "#D8C37A").map { Color.parseColor(it) }
    // 2026-10-20 review: the sure cases (the voice, or you said so) need no tag on every line; only the guesses say so
    private val HOW = mapOf("context" to "לפי ההקשר", "conv" to "כנראה", "call" to "לפי השיחה")
    private var dp = 1f
    private var convId = 0
    private var startAt = -1.0
    private lateinit var root: LinearLayout
    private lateinit var tl: TimelineView
    private lateinit var list: ListView
    private lateinit var chips: LinearLayout
    private lateinit var jumpRow: LinearLayout
    private lateinit var status: TextView
    private val clip by lazy { Clip(this) }
    private var lines = ArrayList<JSONObject>()
    private var laneOf = HashMap<String, Int>()            // speaker name ("?" = unknown, "~" = TV / music) -> lane
    private var laneNames = ArrayList<String>()
    private var sel = -1                                   // selected line (index)
    private var people = JSONArray()
    private var owner = ""

    private fun px(v: Int) = (v * dp).toInt()
    private fun round(color: Int, r: Int, stroke: Int? = null) = GradientDrawable().apply {
        setColor(color); cornerRadius = px(r).toFloat(); stroke?.let { setStroke(px(1), it) } }
    private fun text(t: String, size: Float, color: Int = col.ink, bold: Boolean = false) = TextView(this).apply {
        text = t; textSize = size; setTextColor(color); if (bold) typeface = Typeface.DEFAULT_BOLD }
    private fun chip(t: String, onClick: () -> Unit) = TextView(this).apply {
        text = t; textSize = 13f; setTextColor(col.ink); gravity = Gravity.CENTER
        background = round(col.surface2, 14, Color.parseColor("#33FFECD6")); setPadding(px(12), px(7), px(12), px(7))
        minHeight = px(36); isClickable = true; setOnClickListener { onClick() }
    }
    private fun sod(iso: String): Double = try {
        iso.substring(11, 13).toInt() * 3600 + iso.substring(14, 16).toInt() * 60 + iso.substring(17).toDouble()
    } catch (e: Exception) { 0.0 }
    private fun nameOf(u: JSONObject) = u.optString("name").takeIf { it.isNotBlank() && it != "null" }
    private fun mediaOf(u: JSONObject) = u.optString("media").takeIf { it.isNotBlank() && it != "null" }
    private fun keyOf(u: JSONObject) = if (mediaOf(u) != null) "~" else nameOf(u) ?: "?"
    private fun colorOf(key: String) = when (key) { "?" -> col.unk; "~" -> col.sky; else -> palette[(laneOf[key] ?: 0) % palette.size] }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        dp = resources.displayMetrics.density
        convId = intent.getIntExtra("id", 0); startAt = intent.getDoubleExtra("at", -1.0)
        intent.getIntExtra("notif", 0).takeIf { it != 0 }?.let {           // opened from a reminder's button: it is read
            (getSystemService(NOTIFICATION_SERVICE) as android.app.NotificationManager).cancel(it) }
        root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; layoutDirection = View.LAYOUT_DIRECTION_RTL
            setBackgroundColor(col.bg); setPadding(px(14), px(16), px(14), 0)
        }
        setContentView(root)
        status = text("טוען מהמחשב…", 15f, col.dim)
        root.addView(status)
        load()
    }

    override fun onDestroy() { clip.stop(); ui.removeCallbacksAndMessages(null); super.onDestroy() }

    private fun load(keepView: Boolean = false) {
        thread {
            val r = Net.call(this, "GET", "/home/api/conversation?id=$convId")
            val p = if (people.length() == 0) Net.call(this, "GET", "/home/api/people") else null
            ui.post {
                if (isDestroyed) return@post
                if (r == null) { status.text = "המחשב לא זמין. הצפייה בשיחה עובדת כשהטלפון ברשת הבית (או ב-Tailscale)."; status.setTextColor(col.rose); return@post }
                p?.let { people = try { JSONArray(it) } catch (e: Exception) { JSONArray() } }
                show(JSONObject(r), keepView)
                if (!keepView) Prefs.convOpened(this)          // a conversation really read (for the rating request)
            }
        }
    }

    private fun show(j: JSONObject, keepView: Boolean) {
        val conv = j.optJSONObject("conversation") ?: run { status.text = "השיחה לא נמצאה."; return }
        val U = j.getJSONArray("utterances")
        val oldStart = if (keepView && ::tl.isInitialized) tl.viewStart else -1.0
        val oldSpan = if (keepView && ::tl.isInitialized) tl.viewSpan else -1.0
        val oldLaneName = if (::tl.isInitialized && tl.selLane >= 0) laneNames.getOrNull(tl.selLane) else null
        val oldFirst = if (keepView && ::list.isInitialized) list.firstVisiblePosition else -1
        val oldTop = if (oldFirst >= 0) list.getChildAt(0)?.top ?: 0 else 0
        lines = ArrayList((0 until U.length()).map { U.getJSONObject(it) })
        // lanes like the PC: speakers by talk time (8 at most), then "unknown", then TV / music
        val talk = HashMap<String, Double>()
        for (u in lines) { val k = keyOf(u); if (k != "~") talk[k] = (talk[k] ?: 0.0) + u.optDouble("seconds", 0.0) }
        laneNames = ArrayList(talk.keys.filter { it != "?" }.sortedByDescending { talk[it] }.take(8))
        if (talk.containsKey("?")) laneNames.add("?")
        if (lines.any { keyOf(it) == "~" }) laneNames.add("~")
        laneOf = HashMap(laneNames.withIndex().associate { (i, k) -> k to i })
        root.removeAllViews()

        // header
        val top = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        top.addView(text("→", 24f, col.dim).apply { contentDescription = "חזרה"; setPadding(px(4), 0, px(12), 0); isClickable = true; setOnClickListener { finish() } })
        val st = conv.optString("start"); val en = conv.optString("end")
        val head = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        head.addView(text(conv.optString("topic").takeIf { it.isNotBlank() && it != "null" } ?: "שיחה", 18f, bold = true).apply { maxLines = 2 })
        head.addView(text("${st.take(10).split("-").reversed().joinToString("/")} · " + TimelineView.ltr("${st.drop(11).take(5)}–${en.drop(11).take(5)}"), 12f, col.faint))
        top.addView(head, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        root.addView(top)
        conv.optString("summary").takeIf { it.isNotBlank() && it != "null" }?.let { s ->
            val sum = text(s, 13f, col.dim).apply { maxLines = 2; setPadding(0, px(6), 0, 0); isClickable = true
                setOnClickListener { maxLines = if (maxLines == 2) 40 else 2 }; contentDescription = "סיכום. הקש להרחבה" }
            root.addView(sum)
        }
        if (j.optBoolean("has_audio")) {                   // PC 1.0.13+: the recordings are still kept
            val recRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL; setPadding(0, px(8), 0, 0) }
            val rec = chip("🎧 שתף הקלטה") {}
            rec.setOnClickListener { AudioShare.share(this, "/home/audio/conv/$convId.m4a", "conversation-$convId.m4a", "שתף את הקלטת השיחה", rec) }
            recRow.addView(rec)
            recRow.addView(text("רק הדיבור. כולל קולות של אחרים: ודא שהם מסכימים לפני ששולחים.", 11f, col.faint).apply { setPaddingRelative(px(10), 0, 0, 0) },
                LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            root.addView(recRow)
        }

        // timeline + zoom
        tl = TimelineView(this)
        val lanes = laneNames.map { k -> TimelineView.Lane(when (k) { "?" -> "לא מזוהה"; "~" -> "📺 רקע"; else -> k.split(" ")[0] }, colorOf(k),
            if (k == "~") TimelineView.BACKGROUND else TimelineView.SPEAKER) }
        val segs = lines.mapIndexedNotNull { i, u ->
            val ln = laneOf[keyOf(u)] ?: return@mapIndexedNotNull null
            TimelineView.Seg(sod(u.optString("t0")), sod(u.optString("t1")).coerceAtLeast(sod(u.optString("t0")) + 0.3), ln, i)
        }
        val a = sod(st); val b = maxOf(sod(en), segs.maxOfOrNull { it.t1 } ?: a + 1)
        tl.setData(lanes, segs, a - 1, b + 1, 8.0)
        if (oldSpan > 0) tl.show(oldStart, oldStart + oldSpan)
        tl.contentDescription = "ציר הזמן של השיחה: ${lanes.size} שורות דוברים. צבוט להגדלה, גרור כדי לזוז, הקש על קטע כדי לשמוע אותו."
        tl.onTap = { s -> select(s.id, play = true, scrollList = true) }
        tl.onLaneTap = { li -> toggleLane(li) }
        val zoomRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL; setPadding(0, px(10), 0, px(4)) }
        val rng = text("", 12f, col.faint)
        zoomRow.addView(rng, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        zoomRow.addView(chip("−") { tl.zoom(0.5) }.apply { contentDescription = "הקטן" })
        zoomRow.addView(View(this), LinearLayout.LayoutParams(px(6), 1))
        zoomRow.addView(chip("+") { tl.zoom(2.0) }.apply { contentDescription = "הגדל" })
        zoomRow.addView(View(this), LinearLayout.LayoutParams(px(6), 1))
        zoomRow.addView(chip("כל השיחה") { tl.all() })
        tl.onView = { rng.text = TimelineView.ltr("${TimelineView.hm(tl.viewStart, tl.viewSpan < 600)}–${TimelineView.hm(tl.viewStart + tl.viewSpan, tl.viewSpan < 600)}") + " · צבוט או גרור" }
        tl.onView?.invoke()
        root.addView(zoomRow)
        root.addView(tl)

        // speakers: tap = stand out in both; ‹ › jump between that speaker's lines
        chips = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; layoutDirection = View.LAYOUT_DIRECTION_RTL }
        for ((i, k) in laneNames.withIndex()) {
            val mins = if (k == "~") "" else " · ${((talk[k] ?: 0.0) / 60).let { if (it >= 1) "%.0f דק׳".format(it) else "%.0f שנ׳".format(it * 60) }}"
            chips.addView(chip((if (k == "?") "לא מזוהה" else if (k == "~") "📺 רקע" else k.split(" ")[0]) + mins) { toggleLane(i) }.apply {
                setTextColor(colorOf(k)); tag = i })
            chips.addView(View(this), LinearLayout.LayoutParams(px(6), 1))
        }
        root.addView(HorizontalScrollView(this).apply { isHorizontalScrollBarEnabled = false; setPadding(0, px(8), 0, 0); addView(chips) })
        jumpRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL; setPadding(0, px(6), 0, 0); visibility = View.GONE }
        jumpRow.addView(chip("→ הקודם") { jump(-1) }.apply { contentDescription = "המשפט הקודם של הדובר" })
        jumpRow.addView(View(this), LinearLayout.LayoutParams(px(8), 1))
        jumpRow.addView(chip("הבא ←") { jump(1) }.apply { contentDescription = "המשפט הבא של הדובר" })
        root.addView(jumpRow)

        // the lines
        list = ListView(this).apply {
            divider = null; dividerHeight = 0; isFastScrollEnabled = lines.size > 80; setPadding(0, px(8), 0, px(20)); clipToPadding = false
            adapter = rows
            setOnItemClickListener { _, _, pos, _ -> select(pos, play = true, scrollList = false) }
            setOnItemLongClickListener { _, _, pos, _ -> askWho(pos); true }
            setOnScrollListener(object : android.widget.AbsListView.OnScrollListener {
                override fun onScrollStateChanged(v: android.widget.AbsListView?, s: Int) {}
                override fun onScroll(v: android.widget.AbsListView?, first: Int, n: Int, total: Int) {
                    if (n > 0 && first < lines.size && list.isPressed.not() && clip.playingId < 0 && touching) {
                        val u = lines[first]; tl.reveal(sod(u.optString("t0")))
                    }
                }
            })
            setOnTouchListener { _, e -> touching = e.actionMasked == android.view.MotionEvent.ACTION_MOVE; false }
        }
        root.addView(list, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        if (lines.isEmpty()) root.addView(text("אין תמלול בשיחה הזו.", 14f, col.dim))
        oldLaneName?.let { n -> laneOf[n]?.let { toggleLane(it, jumpTo = false) } }   // a reload keeps the filter, plays nothing
        if (startAt >= 0) {
            val i = lines.indexOfFirst { sod(it.optString("t1")) >= startAt }.coerceAtLeast(0)
            startAt = -1.0
            if (lines.isNotEmpty()) { tl.show(sod(lines[i].optString("t0")) - 30, sod(lines[i].optString("t0")) + 60); select(i, play = false, scrollList = true) }
        } else if (sel in lines.indices) select(sel, play = false, scrollList = false)
        if (oldFirst >= 0) list.post { list.setSelectionFromTop(oldFirst.coerceAtMost(lines.size - 1), oldTop) }   // the list stays where it was
    }

    private var touching = false

    private fun toggleLane(li: Int, jumpTo: Boolean = true) {
        tl.selLane = if (tl.selLane == li) -1 else li
        for (i in 0 until chips.childCount) (chips.getChildAt(i) as? TextView)?.let { c ->
            val on = c.tag == tl.selLane
            c.background = round(if (on) col.surface else col.surface2, 14, if (on) col.accent else Color.parseColor("#33FFECD6"))
        }
        jumpRow.visibility = if (tl.selLane >= 0) View.VISIBLE else View.GONE
        rows.notifyDataSetChanged()
        if (jumpTo && tl.selLane >= 0 && (sel !in lines.indices || laneOf[keyOf(lines[sel])] != tl.selLane)) jump(1)
    }

    private fun jump(dir: Int) {
        val li = tl.selLane
        val from = if (sel in lines.indices) sel else if (dir > 0) -1 else lines.size
        var i = from + dir
        while (i in lines.indices && (li >= 0 && laneOf[keyOf(lines[i])] != li)) i += dir
        if (i in lines.indices) select(i, play = true, scrollList = true)
        else Toast.makeText(this, if (dir > 0) "אין עוד משפטים אחרי זה" else "זה המשפט הראשון", Toast.LENGTH_SHORT).show()
    }

    private val tick = object : Runnable {
        override fun run() {
            val p = clip.position()
            if (p >= 0 && sel in lines.indices) { val t = sod(lines[sel].optString("t0")) - 0.2 + p; tl.playhead = t; tl.reveal(t) }
            else if (clip.playingId < 0) tl.playhead = -1.0
            if (clip.playingId >= 0) ui.postDelayed(this, 100)
        }
    }

    private fun select(i: Int, play: Boolean, scrollList: Boolean) {
        if (i !in lines.indices) return
        sel = i
        val u = lines[i]
        tl.selId = i
        tl.reveal(sod(u.optString("t0")), sod(u.optString("t1")))
        rows.notifyDataSetChanged()
        if (scrollList) list.post { list.setSelectionFromTop(i, px(40)) }   // after the redraw, or the list keeps its place
        if (play) {
            clip.play(u.getInt("id")) { s ->
                playState = s
                rows.notifyDataSetChanged()
                if (s == "playing") { ui.removeCallbacks(tick); ui.post(tick) }
                if (s != "loading" && s != "playing" && s != "done") Toast.makeText(this, s, Toast.LENGTH_SHORT).show()
            }
        }
    }

    private var playState = ""

    private val rows = object : BaseAdapter() {
        override fun getCount() = lines.size
        override fun getItem(p: Int) = lines[p]
        override fun getItemId(p: Int) = p.toLong()
        override fun getView(p: Int, v: View?, parent: ViewGroup?): View {
            val row = (v as? LinearLayout) ?: LinearLayout(this@ConvActivity).apply {
                orientation = LinearLayout.HORIZONTAL; layoutDirection = View.LAYOUT_DIRECTION_RTL
                setPadding(px(8), px(8), px(8), px(8)); minimumHeight = px(48)
                addView(LinearLayout(this@ConvActivity).apply { orientation = LinearLayout.VERTICAL
                    addView(text("", 14f, bold = true)); addView(text("", 11f, col.faint)) }, LinearLayout.LayoutParams(px(84), ViewGroup.LayoutParams.WRAP_CONTENT))
                addView(LinearLayout(this@ConvActivity).apply { orientation = LinearLayout.VERTICAL
                    addView(text("", 11f, col.faint).apply { textDirection = View.TEXT_DIRECTION_LTR; textAlignment = View.TEXT_ALIGNMENT_VIEW_END })
                    addView(text("", 15f)) }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            }
            val u = lines[p]; val k = keyOf(u)
            val left = row.getChildAt(0) as LinearLayout; val right = row.getChildAt(1) as LinearLayout
            val nm = left.getChildAt(0) as TextView; val how = left.getChildAt(1) as TextView
            val tm = right.getChildAt(0) as TextView; val tx = right.getChildAt(1) as TextView
            val media = mediaOf(u)
            nm.text = when { media != null -> "📺 $media"; nameOf(u) != null -> nameOf(u)!!.split(" ")[0] + (if (u.optString("how") == "conv") "?" else ""); else -> "מי זה? ✎" }
            nm.setTextColor(if (nameOf(u) == null && media == null) col.accent else colorOf(k))
            how.text = if (media != null) "ברקע" else if (nameOf(u) != null) HOW[u.optString("how")] ?: "" else "הקש על השם"
            nm.isClickable = true; nm.setOnClickListener { askWho(p) }
            nm.contentDescription = "מי אמר את זה: ${nm.text}. הקש כדי לתקן"
            val marks = (if (u.optInt("split_of") > 0) " ✂" else "") + (if (u.optInt("overlap") == 1) " בו-זמנית" else "")
            tm.text = TimelineView.hm(sod(u.optString("t0")), true) + marks + (if (p == sel) when (playState) { "loading" -> "  ⏳"; "playing" -> "  🔊"; else -> "" } else "")
            tx.text = if (media != null) "$media ברקע · ${u.optDouble("seconds").toInt()} שנ׳" else u.optString("text")
            tx.setTextColor(if (media != null) col.faint else col.ink)
            val dim = tl.selLane >= 0 && laneOf[k] != tl.selLane
            row.alpha = if (dim) 0.45f else 1f
            row.background = if (p == sel) round(col.surface, 10, col.accent) else null
            return row
        }
    }

    // ------------------------------------------------------------ "who said this" (same rules as the PC window)
    private fun askWho(p: Int) {
        if (p !in lines.indices) return
        val u = lines[p]
        select(p, play = true, scrollList = false)
        val box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(px(20), px(8), px(20), 0); layoutDirection = View.LAYOUT_DIRECTION_RTL }
        box.addView(text("״${u.optString("text").take(200)}״", 15f))
        val cands = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(0, px(8), 0, 0) }
        box.addView(cands)
        val names = (0 until people.length()).map { people.getJSONObject(it) }
        val field = AutoCompleteTextView(this).apply {
            hint = "הקלד שם, או שם חדש…"; setTextColor(col.ink); setHintTextColor(col.faint); threshold = 1; isSingleLine = true
            inputType = InputType.TYPE_CLASS_TEXT; imeOptions = EditorInfo.IME_ACTION_DONE
            setAdapter(ArrayAdapter(this@ConvActivity, android.R.layout.simple_dropdown_item_1line, names.map { it.optString("name") }))
        }
        box.addView(field)
        lateinit var d: AlertDialog
        val save = { b: JSONObject -> d.dismiss(); label(u, b) }
        val typed = {
            val n = field.text.toString().trim()
            if (n.isNotEmpty()) { val hit = names.firstOrNull { it.optString("name") == n }
                save(if (hit != null) JSONObject().put("speaker", hit.optString("id")) else JSONObject().put("new_name", n)) }
        }
        field.setOnItemClickListener { _, _, _, _ -> typed() }
        field.setOnEditorActionListener { _, a, _ -> if (a == EditorInfo.IME_ACTION_DONE) { typed(); true } else false }
        d = AlertDialog.Builder(this).setTitle("מי אמר את זה?").setView(box)
            .setPositiveButton("שמור", null).setNeutralButton("⋯ עוד", null).setNegativeButton("סגור", null).show()
        d.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener { typed() }
        var splitOf = u.optInt("split_of")
        d.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener { v ->
            PopupMenu(this, v).apply {
                menu.add(0, 1, 0, if (mediaOf(u) != null) "🗣 זה לא ${mediaOf(u)}: מישהו מדבר" else "📺 טלוויזיה / רדיו / שיר")
                menu.add(0, 2, 1, "👥 כמה אנשים מדברים כאן")
                menu.add(0, 3, 2, "❔ לא ניתן לזהות")
                if (splitOf > 0) menu.add(0, 4, 3, "↺ בטל את הפיצול")
                setOnMenuItemClickListener { m ->
                    d.dismiss()
                    when (m.itemId) {
                        1 -> label(u, JSONObject().put("speaker", if (mediaOf(u) != null) "__person__" else "__tv__"))
                        2, 3 -> thread { Net.call(this@ConvActivity, "POST", "/home/api/teach_skip", JSONObject().put("utt_id", u.getInt("id")).put("reason", if (m.itemId == 2) "multi" else "unclear")) }
                            .also { Toast.makeText(this@ConvActivity, "סומן. לא יישאל שוב.", Toast.LENGTH_SHORT).show() }
                        4 -> thread { val r = Net.call(this@ConvActivity, "POST", "/home/api/unsplit", JSONObject().put("utt_id", u.getInt("id")))
                            ui.post { Toast.makeText(this@ConvActivity, if (r != null) "הפיצול בוטל" else "המחשב לא זמין", Toast.LENGTH_SHORT).show(); load(true) } }
                    }
                    true
                }
            }.show()
        }
        // candidates: at most 3, each with its reason, no numbers (the PC decides; old PCs: none)
        thread {
            val w = Net.call(this, "GET", "/home/api/who_cands?utt=${u.getInt("id")}")?.let { try { JSONObject(it) } catch (e: Exception) { null } }
            ui.post {
                if (!d.isShowing) return@post
                splitOf = w?.optInt("split_of") ?: splitOf
                w?.optString("owner")?.takeIf { it.isNotBlank() }?.let { owner = it }
                val arr = w?.optJSONArray("cands") ?: JSONArray()
                if (arr.length() > 0) cands.addView(text("אולי", 12f, col.faint))
                val shown = HashSet<String>()
                for (i in 0 until minOf(3, arr.length())) {
                    val o = arr.getJSONObject(i); shown += o.optString("id")
                    val why = if (o.optString("why") == "voice") "קול דומה" else "דיבר/ה בשיחה"
                    cands.addView(chip("${o.optString("name")}${if (o.optString("id") == owner) " (אני)" else ""} · $why") {
                        save(JSONObject().put("speaker", o.optString("id"))) }.apply {
                        if (o.optBoolean("strong")) background = round(col.surface2, 14, col.accent) })
                    cands.addView(View(this), LinearLayout.LayoutParams(1, px(6)))
                }
                if (owner.isNotEmpty() && owner !in shown) {
                    cands.addView(chip("🙋 זה אני") { save(JSONObject().put("speaker", owner)) })
                    cands.addView(View(this), LinearLayout.LayoutParams(1, px(6)))
                }
            }
        }
    }

    private fun label(u: JSONObject, body: JSONObject) {
        body.put("utt_id", u.getInt("id"))
        Toast.makeText(this, "שומר…", Toast.LENGTH_SHORT).show()
        thread {
            val r = Net.call(this, "POST", "/home/api/label", body, 120000)?.let { try { JSONObject(it) } catch (e: Exception) { null } }
            ui.post {
                if (isDestroyed) return@post
                if (r == null || !r.optBoolean("ok")) { Toast.makeText(this, "לא נשמר: ${r?.optString("msg") ?: "המחשב לא זמין"}", Toast.LENGTH_LONG).show(); return@post }
                if (body.has("new_name")) people = JSONArray()
                Toast.makeText(this, "למדתי: ${r.optString("name")}" + (if (r.optInt("renamed") > 0) ". זיהיתי מחדש עוד ${r.optInt("renamed")}" else ""), Toast.LENGTH_SHORT).show()
                load(true)                                    // the timeline and the lines follow the fix
                ui.postDelayed({ if (!isDestroyed) load(true) }, 6000)   // similar lines are re-named in the background
            }
        }
    }
}
