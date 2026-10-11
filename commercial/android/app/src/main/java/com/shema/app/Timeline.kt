package com.shema.app

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

/**
 * What the microphone did, minute by minute, so the PC can tell "quiet" from "did not record".
 * Entries: {s,e (epoch ms, phone clock), r (reason key, "" = recording), d (detail)}.
 * Reason keys: pause, mute, private, cal, battery, away, busy, off, killed, stall, enroll_needed.
 * Closed entries wait in prefs until the PC acknowledges them (sent with the heartbeat).
 */
object Timeline {
    private const val MIN_MS = 15_000L          // shorter blips are dropped
    private const val MAX_KEPT = 400
    private fun p(c: Context) = c.getSharedPreferences("home_pro", Context.MODE_PRIVATE)
    private fun closed(c: Context) = try { JSONArray(p(c).getString("tl_closed", "[]")) } catch (e: Exception) { JSONArray() }
    private fun open(c: Context): JSONObject? = try { p(c).getString("tl_open", null)?.let { JSONObject(it) } } catch (e: Exception) { null }

    private fun addClosed(c: Context, s: Long, e: Long, r: String, d: String) {
        if (e - s < MIN_MS) return
        val a = closed(c)
        // merge with the previous entry when it is the same thing, back to back
        if (a.length() > 0) {
            val last = a.getJSONObject(a.length() - 1)
            if (last.optString("r") == r && last.optString("d") == d && s - last.getLong("e") < 5_000L) {
                last.put("e", e); p(c).edit().putString("tl_closed", a.toString()).apply(); return
            }
        }
        a.put(JSONObject().put("s", s).put("e", e).put("r", r).put("d", d))
        val out = JSONArray()
        for (i in maxOf(0, a.length() - MAX_KEPT) until a.length()) out.put(a.get(i))
        p(c).edit().putString("tl_closed", out.toString()).apply()
    }

    /** A gap the service noticed by itself (e.g. the microphone stalled). */
    fun gap(c: Context, s: Long, e: Long, r: String, d: String = "") = addClosed(c, s, e, r, d)

    /** Service started: the time since the last tick was spent dead (killed by the phone, or stopped by the user). */
    fun begin(c: Context, now: Long) {
        val o = open(c)
        if (o != null) {
            val last = o.optLong("t", o.getLong("s"))
            addClosed(c, o.getLong("s"), last, o.optString("r"), o.optString("d"))
            val why = p(c).getString("off_reason", null)
            addClosed(c, last, now, why ?: "killed", "")
        }
        p(c).edit().remove("off_reason").remove("tl_open").apply()
    }

    fun userStop(c: Context) = p(c).edit().putString("off_reason", "off").apply()

    /** Called often; persists at most every 15 s. [r] = "" while recording. */
    fun tick(c: Context, now: Long, r: String, d: String = "") {
        val o = open(c)
        if (o == null) {
            p(c).edit().putString("tl_open", JSONObject().put("s", now).put("r", r).put("d", d).put("t", now).toString()).apply(); return
        }
        if (o.optString("r") != r || (r != "" && o.optString("d") != d)) {
            addClosed(c, o.getLong("s"), now, o.optString("r"), o.optString("d"))
            p(c).edit().putString("tl_open", JSONObject().put("s", now).put("r", r).put("d", d).put("t", now).toString()).apply()
        } else if (now - o.optLong("t", 0L) >= 15_000L) {
            o.put("t", now); p(c).edit().putString("tl_open", o.toString()).apply()
        }
    }

    /** Service ended cleanly. */
    fun end(c: Context, now: Long) {
        val o = open(c) ?: return
        addClosed(c, o.getLong("s"), now, o.optString("r"), o.optString("d"))
        p(c).edit().remove("tl_open").apply()
    }

    /** Returns (JSON string, number of closed intervals), ready to send with the heartbeat. */
    fun pending(c: Context, now: Long): Pair<String, Int> {
        val a = closed(c)
        val o = open(c)
        val copy = JSONArray()
        for (i in 0 until a.length()) copy.put(a.get(i))
        if (o != null) {
            val s = o.getLong("s")
            if (now - s >= MIN_MS) copy.put(JSONObject().put("s", s).put("e", now).put("r", o.optString("r")).put("d", o.optString("d")))
        }
        return copy.toString() to a.length()
    }

    /** The PC acknowledged receiving [count] intervals: drop them from the closed queue. */
    fun ack(c: Context, count: Int) {
        if (count <= 0) return
        val a = closed(c)
        val out = JSONArray()
        for (i in count until a.length()) out.put(a.get(i))
        p(c).edit().putString("tl_closed", out.toString()).apply()
    }
}
