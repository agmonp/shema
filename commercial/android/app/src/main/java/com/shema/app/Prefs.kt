package com.shema.app

import android.content.Context
import android.net.Uri

object Prefs {
    private fun p(c: Context) = c.getSharedPreferences("home_pro", Context.MODE_PRIVATE)

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
    fun base(c: Context) = activeServer.ifEmpty { server(c) }
    /** set by ListenService; kept here so code that runs at boot never reaches the microphone service (Play's Android 15 check) */
    @Volatile var activeServer = ""                      // the address that answered last ("" = none)
    fun flag(c: Context, k: String) = p(c).getBoolean(k, false)
    fun setFlag(c: Context, k: String) = p(c).edit().putBoolean(k, true).apply()
    fun digestDay(c: Context) = p(c).getString("digest_day", "")!!
    fun setDigestDay(c: Context, v: String) = p(c).edit().putString("digest_day", v).apply()

    fun paired(c: Context) = server(c).isNotEmpty() && token(c).isNotEmpty()

    /** "השהה": nothing is recorded until the user resumes (kept across restarts) */
    fun paused(c: Context) = p(c).getBoolean("paused", false)
    fun setPaused(c: Context, v: Boolean) = p(c).edit().putBoolean("paused", v).apply()
    fun clearFlag(c: Context, k: String) = p(c).edit().putBoolean(k, false).apply()

    /** Commercial & Google Play Compliance preferences */
    fun isSubscribed(c: Context) = p(c).getBoolean("is_subscribed", false)
    fun setSubscribed(c: Context, v: Boolean) = p(c).edit().putBoolean("is_subscribed", v).apply()

    /** the gift code this phone got (Gift.kt checks it every time) */
    fun gift(c: Context) = p(c).getString("gift_code", "")!!
    fun setGift(c: Context, v: String) = p(c).edit().putString("gift_code", v).apply()
    /** only for a phone without ANDROID_ID */
    fun fallbackId(c: Context): String = p(c).getString("fallback_id", null)
        ?: java.util.UUID.randomUUID().toString().also { p(c).edit().putString("fallback_id", it).apply() }

    fun firstInstallTime(c: Context): Long {
        val t = p(c).getLong("first_install_time", 0L)
        if (t == 0L) {
            val now = System.currentTimeMillis()
            p(c).edit().putLong("first_install_time", now).apply()
            return now
        }
        return t
    }

    fun isDisclosureAccepted(c: Context) = p(c).getBoolean("disclosure_accepted", false)
    fun setDisclosureAccepted(c: Context, v: Boolean) = p(c).edit().putBoolean("disclosure_accepted", v).apply()

    /** shema://pair?server=http://<LAN-IP>:8770&remote=http://<tailscale-ip>:8770&token=<token> -> (server, remote, token) */
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
}
