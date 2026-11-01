package com.shema.app

import org.json.JSONObject
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/**
 * The "אני" periods: a day, or the Israeli week (Sunday to Saturday, the same as the PC's me_speech.py / me_period.py).
 * Plain Kotlin + org.json, so the rules are unit-tested on the JVM (app/src/test).
 *
 * 2026-11-01, the weekly "אני" bug: the phone always asked for the week that contains today. On a Sunday (and early in
 * any week) that week has nothing yet, so "השבוע" showed only "עוד לא שמעתי אותך מדבר השבוע" although last week was full;
 * and when the PC did not answer, the card was emptied or left as it was. Now: the current week falls back to the last
 * week with data (said so on screen), every period ever received is kept on the phone (LocalStore), and when the PC is
 * away the saved one is shown with the time it was received.
 */
object MePeriods {
    private val dmy = DateTimeFormatter.ofPattern("dd/MM")
    private val ymd = DateTimeFormatter.ISO_LOCAL_DATE

    fun start(kind: String, d: LocalDate): LocalDate =
        if (kind == "week") d.minusDays((d.dayOfWeek.value % 7).toLong()) else d     // Sunday = 0
    fun end(kind: String, s: LocalDate): LocalDate = if (kind == "week") s.plusDays(6) else s
    fun prev(kind: String, s: LocalDate): LocalDate = start(kind, s.minusDays(1))
    fun next(kind: String, s: LocalDate): LocalDate = if (kind == "week") s.plusDays(7) else s.plusDays(1)
    fun isCurrent(kind: String, s: LocalDate, today: LocalDate) = start(kind, today) == s
    fun key(s: LocalDate): String = s.format(ymd)
    fun parse(s: String): LocalDate = LocalDate.parse(s.take(10), ymd)

    fun label(kind: String, s: LocalDate, today: LocalDate): String = when {
        kind == "day" && s == today -> "היום"
        kind == "day" && s == today.minusDays(1) -> "אתמול"
        kind == "day" -> "${heDay(s)} ${s.format(dmy)}"
        isCurrent(kind, s, today) -> "השבוע · " + ltr("${s.format(dmy)}–${end(kind, s).format(dmy)}")
        isCurrent(kind, next(kind, s), today) -> "השבוע שעבר · " + ltr("${s.format(dmy)}–${end(kind, s).format(dmy)}")
        else -> ltr("${s.format(dmy)}–${end(kind, s).format(dmy)}")
    }

    /** a date range keeps its order inside Hebrew text ("25/10–31/10", not "31/10–25/10") */
    fun ltr(s: String) = "⁦$s⁩"

    fun heDay(d: LocalDate) = "יום " + listOf("שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון")[d.dayOfWeek.value - 1]

    /**
     * One saved period: {"kind","start","me2","period","me"} -- the PC's answers as they came (me2 = the owner's server
     * "אני" analysis, period = me_period.py, me = the oldest PCs' basic numbers). Any of them may be missing: older
     * PCs have fewer, and the screen draws only what a saved answer has.
     */
    fun combine(kind: String, s: LocalDate, me2: String?, period: String?, old: String?): JSONObject? {
        fun obj(t: String?) = t?.trim()?.takeIf { it.startsWith("{") }?.let { try { JSONObject(it) } catch (e: Exception) { null } }
            ?.takeIf { !it.has("error") }
        val a = obj(me2); val b = obj(period); val o = obj(old)
        if (a == null && b == null && o == null) return null
        return JSONObject().put("kind", kind).put("start", key(s)).put("me2", a ?: JSONObject.NULL)
            .put("period", b ?: JSONObject.NULL).put("me", o ?: JSONObject.NULL)
    }

    /** was anything heard in this period? (an empty week is shown as empty, and the current one falls back) */
    fun hasData(j: JSONObject?): Boolean {
        if (j == null) return false
        j.optJSONObject("me2")?.optJSONObject("me")?.let { if (it.optInt("lines") > 0) return true }
        j.optJSONObject("period")?.optJSONObject("stats")?.let { if (it.optInt("conversations") > 0 || it.optInt("my_lines") > 0) return true }
        j.optJSONObject("me")?.let { if (it.optInt("seconds") > 0) return true }
        return false
    }

    /** "מוצג מידע שמור · עודכן לאחרונה: 31/10 21:09" */
    fun savedNotice(fetchedMs: Long, zone: ZoneId = ZoneId.systemDefault()): String =
        "מוצג מידע שמור · עודכן לאחרונה: " + DateTimeFormatter.ofPattern("dd/MM HH:mm").format(Instant.ofEpochMilli(fetchedMs).atZone(zone))
}

/** where saved periods live (LocalStore on the phone, a map in the tests) */
interface MeCache {
    fun putMe(kind: String, start: String, json: String, fetchedMs: Long)
    fun getMe(kind: String, start: String): Pair<String, Long>?
    fun savedMe(kind: String): List<String>          // starts, newest first
}

/** what a screen shows for one period: the answer (fresh or saved), and whether the PC answered */
data class MeResult(val json: JSONObject?, val fromCache: Boolean, val fetchedMs: Long, val pcAnswered: Boolean)

object MeRepo {
    /**
     * fetch(path) -> body or null (no answer). The PC is asked for the period's own date; a fresh answer is saved
     * (replacing the old one of that period); without one the saved answer is returned, marked fromCache.
     */
    fun load(kind: String, s: LocalDate, today: LocalDate, cache: MeCache, now: Long, fetch: (String) -> String?): MeResult {
        val d = if (MePeriods.isCurrent(kind, s, today)) today else MePeriods.end(kind, s)
        val ds = MePeriods.key(d)
        val me2 = fetch("/home/api/me2?k=$kind&d=$ds")
        val period = fetch("/home/api/me_period?k=$kind&d=$ds")
        val old = if (me2 == null && period == null && kind == "day") fetch("/home/api/me?d=$ds") else null
        val j = MePeriods.combine(kind, s, me2, period, old)
        if (j != null) {
            cache.putMe(kind, MePeriods.key(s), j.toString(), now)
            return MeResult(j, false, now, true)
        }
        val saved = cache.getMe(kind, MePeriods.key(s))
        val sj = saved?.let { try { JSONObject(it.first) } catch (e: Exception) { null } }
        return MeResult(sj, sj != null, saved?.second ?: 0L, false)
    }

    /**
     * "השבוע" (or "היום") with nothing in it yet: the newest earlier period that has something, up to `back` periods
     * back (fresh from the PC, or saved). null = keep the current (empty) one.
     */
    fun fallback(kind: String, today: LocalDate, cache: MeCache, now: Long, back: Int = 2, fetch: (String) -> String?): Pair<LocalDate, MeResult>? {
        var s = MePeriods.start(kind, today)
        repeat(back) {
            s = MePeriods.prev(kind, s)
            val r = load(kind, s, today, cache, now, fetch)
            if (MePeriods.hasData(r.json)) return s to r
        }
        return null
    }
}
