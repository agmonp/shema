package com.shema.app

import android.app.AlarmManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale
import kotlin.concurrent.thread

/**
 * Opt-in reminders on promises / tasks. Owner's rule: a reminder exists only after the user asked for it on that
 * item (here or on the PC); nothing is reminded by itself. The PC keeps the list (tasks.remind_at), the phone keeps a
 * copy so it can remind without the PC, and re-syncs it from every status poll and after a restart.
 *
 * Alarms: exact when Android allows it (Android 12+ asks the user for that in Settings; we never send them there),
 * otherwise setAndAllowWhileIdle, which may come a few minutes late in deep sleep.
 */
object Reminders {
    private const val ACT_FIRE = "app.shema.REMIND"
    private const val ACT_DONE = "app.shema.REMIND_DONE"
    private const val ACT_TOMORROW = "app.shema.REMIND_TOMORROW"
    private const val CHANNEL = "reminders"
    private const val MISSED_MS = 12 * 3600_000L        // a reminder missed while the phone was off still comes, up to 12 h late

    private fun p(c: Context) = c.getSharedPreferences("home_reminders", Context.MODE_PRIVATE)
    private val fmt get() = SimpleDateFormat("yyyy-MM-dd'T'HH:mm", Locale.US)

    fun list(c: Context): JSONArray = try { JSONArray(p(c).getString("list", "[]")) } catch (e: Exception) { JSONArray() }
    private fun save(c: Context, a: JSONArray) = p(c).edit().putString("list", a.toString()).apply()
    private fun find(c: Context, id: Int): JSONObject? = list(c).let { a -> (0 until a.length()).map { a.getJSONObject(it) }.firstOrNull { it.optInt("id") == id } }
    private fun key(r: JSONObject) = r.optInt("id").toString() + "@" + r.optString("at")
    private fun fired(c: Context): MutableList<String> = try { JSONArray(p(c).getString("fired", "[]")).let { a -> MutableList(a.length()) { a.getString(it) } } } catch (e: Exception) { mutableListOf() }
    private fun markFired(c: Context, k: String) = fired(c).let { f -> if (k !in f) { f += k; p(c).edit().putString("fired", JSONArray(f.takeLast(200)).toString()).apply() } }

    fun atMs(at: String): Long = try { fmt.parse(at)!!.time } catch (e: Exception) { 0L }
    fun tomorrow9(): String = Calendar.getInstance().apply { add(Calendar.DAY_OF_YEAR, 1); set(Calendar.HOUR_OF_DAY, 9); set(Calendar.MINUTE, 0) }.let { fmt.format(it.time) }
    fun fmtAt(ms: Long): String = fmt.format(Date(ms))

    /** "היום 18:30" / "מחר 09:00" / "25/10 09:00" */
    fun label(at: String): String {
        val t = Calendar.getInstance().apply { timeInMillis = atMs(at) }
        val n = Calendar.getInstance()
        val d = (t.get(Calendar.YEAR) - n.get(Calendar.YEAR)) * 400 + t.get(Calendar.DAY_OF_YEAR) - n.get(Calendar.DAY_OF_YEAR)
        val hm = "%02d:%02d".format(Locale.US, t.get(Calendar.HOUR_OF_DAY), t.get(Calendar.MINUTE))
        return when (d) { 0 -> "היום $hm"; 1 -> "מחר $hm"; else -> "${t.get(Calendar.DAY_OF_MONTH)}/${t.get(Calendar.MONTH) + 1} $hm" }
    }

    /** The PC's list (status poll). Gone or moved items are cancelled, new ones scheduled, a missed one comes now. */
    fun sync(c: Context, server: JSONArray) {
        flushPending(c)
        val now = System.currentTimeMillis()
        val fresh = (0 until server.length()).map { server.getJSONObject(it) }
        val byId = fresh.associateBy { it.optInt("id") }
        val old = list(c)
        for (i in 0 until old.length()) {
            val o = old.getJSONObject(i)
            val n = byId[o.optInt("id")]
            if (n == null || n.optString("at") != o.optString("at")) {
                cancelAlarm(c, o.optInt("id"))
                if (n == null) nm(c).cancel(notifId(o.optInt("id")))          // done / deleted elsewhere
            }
        }
        save(c, JSONArray(fresh))
        for (r in fresh) arm(c, r, now)
    }

    /** after a restart / app update: alarms are gone, set them again from the copy */
    fun rearm(c: Context) {
        val now = System.currentTimeMillis()
        val a = list(c)
        for (i in 0 until a.length()) arm(c, a.getJSONObject(i), now)
    }

    private fun arm(c: Context, r: JSONObject, now: Long) {
        val ms = r.optLong("at_ms").takeIf { it > 0 } ?: atMs(r.optString("at"))
        if (ms > now) schedule(c, r.optInt("id"), r.optString("at"), ms)
        else if (now - ms < MISSED_MS && key(r) !in fired(c)) show(c, r)
    }

    /** The user set (or cancelled, at = null) a reminder on this screen: ask the PC, then keep the copy in step. */
    fun set(c: Context, item: JSONObject, at: String?): String? {
        val id = item.getInt("id")
        val r = Net.call(c, "POST", "/home/api/task_remind", JSONObject().put("id", id).put("at", at ?: JSONObject.NULL))
            ?: return "המחשב לא זמין, נסה שוב"
        val j = try { JSONObject(r) } catch (e: Exception) { return "תשובה לא מובנת מהמחשב" }
        if (!j.optBoolean("ok")) return j.optString("msg", "לא הצליח")
        val when_ = j.optString("remind_at").takeIf { j.has("remind_at") && !j.isNull("remind_at") }
        if (when_ == null) remove(c, id)
        else upsert(c, JSONObject().put("id", id).put("conv_id", item.optInt("conv_id")).put("text", item.optString("text"))
            .put("quote", item.optString("quote").takeIf { it != "null" } ?: "")
            .put("who", item.optString("who").takeIf { it.isNotBlank() && it != "null" } ?: JSONObject.NULL)
            .put("at", when_).put("at_ms", j.optLong("at_ms").takeIf { it > 0 } ?: atMs(when_)))
        return null
    }

    private fun upsert(c: Context, r: JSONObject) {
        val a = list(c); val out = JSONArray()
        for (i in 0 until a.length()) a.getJSONObject(i).let { if (it.optInt("id") != r.optInt("id")) out.put(it) }
        out.put(r); save(c, out)
        cancelAlarm(c, r.optInt("id"))
        arm(c, r, System.currentTimeMillis())
    }

    /** done / deleted / cancelled: no alarm, no notification */
    fun remove(c: Context, id: Int) {
        val a = list(c); val out = JSONArray()
        for (i in 0 until a.length()) a.getJSONObject(i).let { if (it.optInt("id") != id) out.put(it) }
        save(c, out)
        cancelAlarm(c, id)
        nm(c).cancel(notifId(id))
    }

    private fun alarmIntent(c: Context, id: Int, at: String?) = PendingIntent.getBroadcast(c, id,
        Intent(c, ReminderReceiver::class.java).setAction(ACT_FIRE).putExtra("id", id).apply { if (at != null) putExtra("at", at) },
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

    private fun schedule(c: Context, id: Int, at: String, ms: Long) {
        val am = c.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        val pi = alarmIntent(c, id, at)
        try {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S || am.canScheduleExactAlarms())
                am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, ms, pi)
            else am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, ms, pi)
        } catch (e: SecurityException) {                                 // exact alarms taken away meanwhile
            am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, ms, pi)
        }
    }

    private fun cancelAlarm(c: Context, id: Int) {
        (c.getSystemService(Context.ALARM_SERVICE) as AlarmManager).cancel(alarmIntent(c, id, null))
    }

    private fun nm(c: Context) = c.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
    private fun notifId(id: Int) = 100_000 + id

    /** The notification: the item, who, the original words; ✓ בוצע · הזכר מחר · פתח את השיחה */
    fun show(c: Context, r: JSONObject) {
        markFired(c, key(r))
        val id = r.optInt("id")
        val nm = nm(c)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "תזכורות שביקשת", NotificationManager.IMPORTANCE_HIGH))
        val who = r.optString("who").takeIf { it.isNotBlank() && it != "null" }
        val quote = r.optString("quote").takeIf { it.isNotBlank() && it != "null" }
        val body = listOfNotNull(who, quote?.let { "״$it״" }).joinToString(": ").ifEmpty { "תזכורת שביקשת" }
        val conv = PendingIntent.getActivity(c, notifId(id),
            Intent(c, ConvActivity::class.java).putExtra("id", r.optInt("conv_id")).putExtra("notif", notifId(id)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        fun act(a: String, rc: Int) = PendingIntent.getBroadcast(c, rc,
            Intent(c, ReminderReceiver::class.java).setAction(a).putExtra("id", id), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        nm.notify(notifId(id), Notification.Builder(c, CHANNEL).setSmallIcon(R.drawable.ic_stat).setColor(0xFFEAA45E.toInt())
            .setContentTitle("🔔 " + r.optString("text")).setContentText(body)
            .setStyle(Notification.BigTextStyle().bigText(body))
            .setCategory(Notification.CATEGORY_REMINDER).setContentIntent(conv).setAutoCancel(true)
            .addAction(Notification.Action.Builder(null, "✓ בוצע", act(ACT_DONE, 3 * id + 1)).build())
            .addAction(Notification.Action.Builder(null, "הזכר מחר", act(ACT_TOMORROW, 3 * id + 2)).build())
            .addAction(Notification.Action.Builder(null, "פתח את השיחה", conv).build())
            .build())
    }

    // a button pressed while the PC was away: kept and sent with the next status poll
    private fun queue(c: Context, path: String, body: JSONObject) {
        val a = try { JSONArray(p(c).getString("pending", "[]")) } catch (e: Exception) { JSONArray() }
        a.put(JSONObject().put("path", path).put("body", body))
        p(c).edit().putString("pending", a.toString()).apply()
    }

    private fun flushPending(c: Context) {
        val a = try { JSONArray(p(c).getString("pending", "[]")) } catch (e: Exception) { return }
        if (a.length() == 0) return
        val left = JSONArray()
        for (i in 0 until a.length()) a.getJSONObject(i).let { if (Net.call(c, "POST", it.getString("path"), it.getJSONObject("body")) == null) left.put(it) }
        p(c).edit().putString("pending", left.toString()).apply()
    }

    internal fun onReceive(c: Context, i: Intent) {
        val id = i.getIntExtra("id", 0); if (id <= 0) return
        when (i.action) {
            ACT_FIRE -> {
                val r = find(c, id) ?: return                                  // cancelled meanwhile
                if (i.getStringExtra("at") != null && i.getStringExtra("at") != r.optString("at")) return
                if (key(r) !in fired(c)) show(c, r)
            }
            ACT_DONE -> {
                remove(c, id)
                val b = JSONObject().put("id", id).put("state", "done")
                if (Net.call(c, "POST", "/home/api/task", b, timeoutMs = 8000) == null) queue(c, "/home/api/task", b)
            }
            ACT_TOMORROW -> {
                val r = find(c, id) ?: JSONObject().put("id", id)
                val at = tomorrow9()
                nm(c).cancel(notifId(id))
                upsert(c, r.put("at", at).put("at_ms", atMs(at)))
                val b = JSONObject().put("id", id).put("at", at)
                if (Net.call(c, "POST", "/home/api/task_remind", b, timeoutMs = 8000) == null) queue(c, "/home/api/task_remind", b)
            }
        }
    }
}

class ReminderReceiver : BroadcastReceiver() {
    override fun onReceive(c: Context, i: Intent) {
        if (i.action == BootReceiver.REARM) { Reminders.rearm(c); return }     // a minute after a restart / update
        val done = goAsync()                                // the buttons talk to the PC: off the main thread
        thread { try { Reminders.onReceive(c, i) } finally { done.finish() } }
    }
}
