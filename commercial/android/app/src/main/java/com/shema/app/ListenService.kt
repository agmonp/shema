package com.shema.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.AudioRecordingConfiguration
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.media.MediaMuxer
import android.media.MediaRecorder
import android.os.BatteryManager
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.os.VibrationEffect
import android.os.Vibrator
import android.provider.CalendarContract
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.concurrent.thread
import kotlin.math.sqrt

/**
 * Listens, keeps only speech, and sends each speech segment (Opus 12 kbps .ogg, AAC .m4a if Opus is missing; timestamped, with its context:
 * where, calendar event, home or away) to home_listener.py on the home PC. Nothing goes anywhere else.
 *
 * Two roles (Prefs.role):
 *   home   -- the phone that stays: records only at home (PC answers or the home Wi-Fi), as before.
 *   wearer -- the phone that goes out with the user: records at home too, and away from home ONLY after
 *             the owner's voice was taught (the PC then keeps just the conversations the owner is in).
 * Not recording: private places, calendar events with a private word, battery <= 8% (not charging),
 * paused / muted, the microphone taken by a call or another app (reported as a gap, not as silence).
 * Away from home the files wait in the queue until the PC answers.
 */
class ListenService : Service() {
    companion object {
        const val ACTION_MUTE_HOUR = "mute_hour"
        const val ACTION_TOGGLE = "toggle"
        const val ACTION_UNMUTE = "unmute"
        const val ACTION_STOP = "stop"
        const val ACTION_MARK = "mark"
        const val ACTION_ENROLL = "enroll"
        const val ACTION_ENROLL_STOP = "enroll_stop"       // "done reading" before the 25 s are over
        const val ACTION_PING = "ping"                     // heartbeat now (the voice screen waits for the PC's count)
        const val ACTION_MEETING_START = "meeting_start"   // extras: id, title
        const val ACTION_MEETING_END = "meeting_end"
        const val CHANNEL = "listen"
        const val SR = 16000
        const val ENROLL_SECONDS = 25
        const val QUEUE_LIMIT = 1_500_000_000L           // bytes kept in the phone while the PC is away (~270 h of Opus speech)
        const val AWAY_BATCH_MS = 240_000L               // away from home: send in batches, every 4 min ...
        const val AWAY_BATCH_FILES = 20                  // ... or at once when more than 20 files wait
        const val SEND_MIN_BAT = 15                      // below this (not charging) uploading waits; recording goes on to 8%
        @Volatile var state = "כבוי"
        @Volatile var sent = 0
        @Volatile var queued = 0
        // for the main screen (read every second)
        @Volatile var on = false
        @Volatile var home = false
        @Volatile var hearing = false
        @Volatile var pausedNow = false
        @Volatile var mutedUntilNow = 0L
        @Volatile var lastSentAt = 0L
        @Volatile var lastPcOk = 0L
        @Volatile var pcOnline = false
        @Volatile var ssidNow = ""
        /** why the microphone is closed right now ("" = recording) */
        @Volatile var blocked = ""
        @Volatile var enrolled = -1                       // owner voice samples on the PC for this phone (-1 = unknown)
        @Volatile var minSamples = 3
        @Volatile var enrollUntilNow = 0L
        @Volatile var enrollSpeechMs = 0L                // speech heard during the current voice reading
        @Volatile var meetingSince = 0L                  // a meeting is being recorded since (0 = none)
        @Volatile var silencedNow = false
        @Volatile var lat = Double.NaN
        @Volatile var lon = Double.NaN
        @Volatile var digestTeach = 0
        @Volatile var digestTasks = 0
        // reachability over the home Wi-Fi or Tailscale, queue health, battery
        @Volatile var activeServer = ""                  // the address that answered last ("" = none)
        @Volatile var lanOk = false                      // the PC answered on the home address
        @Volatile var viaTailscale = false               // it answered on the remote (Tailscale) address
        @Volatile var vpnOn = false
        @Volatile var queuedBytes = 0L
        @Volatile var oldestMs = 0L
        @Volatile var batNow = -1
        @Volatile var chargingNow = false
        @Volatile var stateLine = "כבוי"

        /** speech segments sent today (kept across restarts) */
        fun sentToday(c: Context): Int {
            val p = c.getSharedPreferences("home", Context.MODE_PRIVATE)
            val day = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())
            return if (p.getString("sent_day", "") == day) p.getInt("sent_n", 0) else 0
        }
        fun countSent(c: Context) {
            val p = c.getSharedPreferences("home", Context.MODE_PRIVATE)
            val day = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())
            val n = if (p.getString("sent_day", "") == day) p.getInt("sent_n", 0) else 0
            p.edit().putString("sent_day", day).putInt("sent_n", n + 1).apply()
        }
        @Volatile var lastMarkAt = 0L
        @Volatile var lastMarkMin = 10
        @Volatile var lastMarkSent = false
        fun addMark(c: Context) {
            val p = c.getSharedPreferences("home", Context.MODE_PRIVATE)
            val day = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())
            val n = if (p.getString("mark_day", "") == day) p.getInt("mark_n", 0) else 0
            p.edit().putString("mark_day", day).putInt("mark_n", n + 1).apply()
        }
        fun marksToday(c: Context): Int {
            val p = c.getSharedPreferences("home", Context.MODE_PRIVATE)
            val day = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())
            return if (p.getString("mark_day", "") == day) p.getInt("mark_n", 0) else 0
        }
        fun device() = android.os.Build.MODEL.replace(Regex("[^A-Za-z0-9]"), "")
        fun addSpeech(c: Context, sec: Double) {
            val p = c.getSharedPreferences("home", Context.MODE_PRIVATE)
            val day = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())
            val cur = if (p.getString("speech_day", "") == day) p.getFloat("speech_sec", 0f) else 0f
            p.edit().putString("speech_day", day).putFloat("speech_sec", cur + sec.toFloat()).apply()
        }
        fun speechToday(c: Context): Int {
            val p = c.getSharedPreferences("home", Context.MODE_PRIVATE)
            val day = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())
            return if (p.getString("speech_day", "") == day) (p.getFloat("speech_sec", 0f) / 60).toInt() else 0
        }
    }

    @Volatile private var running = false
    @Volatile private var mutedUntil = 0L
    @Volatile private var paused = false
    @Volatile private var atHome = false
    @Volatile private var speaking = false
    @Volatile private var enrollUntil = 0L
    @Volatile private var enrollFrom = 0L
    @Volatile private var silenced = false
    @Volatile private var recSession = -1
    @Volatile private var skew = 0L                       // PC clock minus this phone's clock (ms)
    @Volatile private var zoneName = ""
    @Volatile private var calTitle = ""
    @Volatile private var calMute = false
    @Volatile private var lowBat = false
    @Volatile private var batPct = -1
    @Volatile private var charging = false
    @Volatile private var reasonKey = ""                  // Timeline reason of the moment ("" = recording)
    @Volatile private var reasonDetail = ""
    @Volatile private var lastFrameAt = 0L
    @Volatile private var recRef: AudioRecord? = null
    // meeting mode (state kept in Meeting so a restarted service goes on with it)
    @Volatile private var meetId = ""
    @Volatile private var meetTitle = ""
    @Volatile private var meetStart = 0L
    @Volatile private var meetEndReq = false             // "end meeting": the record loop saves the open segment, then ends it
    @Volatile private var cutReq = false                 // the meeting started: close the open segment so it starts clean
    @Volatile private var tempRun = false                // started only for a meeting / the voice reading
    @Volatile private var draining = 0L                  // ... which is over: not recording, stop once the queue is sent
    private var wake: PowerManager.WakeLock? = null
    private val queueDir by lazy { File(filesDir, "queue").apply { mkdirs() } }
    private val ui = Handler(Looper.getMainLooper())
    private var locRegistered = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val act = intent?.action
        if (!running && (act == ACTION_MEETING_START || act == ACTION_ENROLL || act == ACTION_MEETING_END))
            Meeting.setTemp(this, true)                       // the service was off: on only for this, off again once it was sent
        loadMeeting()
        when (act) {
            ACTION_MUTE_HOUR -> { mutedUntil = System.currentTimeMillis() + 3600_000; update(); pingSoon() }
            ACTION_UNMUTE -> { mutedUntil = 0; update(); pingSoon() }
            ACTION_TOGGLE -> { paused = !paused; if (!paused) mutedUntil = 0; update(); pingSoon() }
            ACTION_MARK -> mark(intent?.getIntExtra("min", 10) ?: 10)
            ACTION_ENROLL -> { enrollFrom = System.currentTimeMillis(); enrollUntil = enrollFrom + ENROLL_SECONDS * 1000L
                enrollUntilNow = enrollUntil; enrollSpeechMs = 0; draining = 0; update() }
            ACTION_ENROLL_STOP -> { if (enrolling()) { enrollUntil = System.currentTimeMillis(); enrollUntilNow = enrollUntil }; update() }
            ACTION_PING -> pingSoon()
            ACTION_MEETING_START -> startMeeting(intent)
            ACTION_MEETING_END -> if (meetId.isNotEmpty()) { meetEndReq = true; if (!running) finishMeeting() }
            ACTION_STOP -> { if (meetId.isNotEmpty()) finishMeeting()          // the end goes to the PC with the next start
                Timeline.userStop(this); stopAll(); return START_NOT_STICKY }
        }
        // + location type when allowed: lets the service read the Wi-Fi name and the place in the background
        val loc = checkSelfPermission(android.Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
        startForeground(1, notification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE or
            (if (loc) ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION else 0))
        if (loc) startLocation()
        if (!running) {
            running = true
            on = true
            Timeline.begin(this, System.currentTimeMillis())      // the time since the last tick is a gap (killed / stopped)
            lastFrameAt = System.currentTimeMillis()
            wake = (getSystemService(Context.POWER_SERVICE) as PowerManager)
                .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "shema:rec").apply { acquire() }
            (getSystemService(AUDIO_SERVICE) as AudioManager).registerAudioRecordingCallback(arCb, ui)
            thread(name = "home-check") { homeLoop() }
            thread(name = "rec") { recordLoop() }
            thread(name = "upload") { uploadLoop() }
        }
        update()
        return START_STICKY
    }

    override fun onDestroy() {
        running = false
        on = false; home = false; hearing = false; blocked = ""
        Timeline.end(this, System.currentTimeMillis())
        try { (getSystemService(AUDIO_SERVICE) as AudioManager).unregisterAudioRecordingCallback(arCb) } catch (e: Exception) { }
        stopLocation()
        wake?.let { if (it.isHeld) it.release() }
        super.onDestroy()
    }

    private fun stopAll() {
        Timeline.end(this, System.currentTimeMillis())
        running = false; on = false; home = false; hearing = false; blocked = ""; meetingSince = 0L
        Meeting.setTemp(this, false); draining = 0
        stopForeground(STOP_FOREGROUND_REMOVE); stopSelf(); state = "כבוי"
    }

    // ------------------------------------------------------------ meeting mode
    private fun loadMeeting() {
        meetId = Meeting.id(this); meetTitle = Meeting.title(this); meetStart = Meeting.start(this)
        meetingSince = if (meetId.isEmpty()) 0L else meetStart
        tempRun = Meeting.temp(this)
        if (!tempRun) draining = 0
    }

    /** From now on every speech segment belongs to the meeting (tagged meet=<id>), whatever would stop recording otherwise. */
    private fun startMeeting(i: Intent?) {
        if (meetId.isEmpty()) {
            val now = System.currentTimeMillis()
            Meeting.begin(this, i?.getStringExtra("id")?.ifBlank { null } ?: "m$now", (i?.getStringExtra("title") ?: "").trim().take(80), now)
            loadMeeting()
            cutReq = true; draining = 0
            try { (getSystemService(VIBRATOR_SERVICE) as Vibrator).vibrate(VibrationEffect.createOneShot(120, VibrationEffect.DEFAULT_AMPLITUDE)) } catch (e: Exception) { }
        }
        update(); pingSoon()
    }

    /** The meeting's end goes into the queue after its last segment (the queue is sent in time order), then the PC summarises. */
    private fun finishMeeting() {
        meetEndReq = false
        val id = meetId
        if (id.isEmpty()) return
        val end = System.currentTimeMillis()
        try {
            File(queueDir, SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS", Locale.US).format(Date(end)) + "_meetend.txt")
                .writeText("$id,$meetStart,$end," + URLEncoder.encode(meetTitle, "UTF-8"))
        } catch (e: Exception) { }
        Meeting.remember(this, id, meetTitle, meetStart, end)
        Meeting.clear(this)
        loadMeeting()
        try { (getSystemService(VIBRATOR_SERVICE) as Vibrator).vibrate(VibrationEffect.createWaveform(longArrayOf(0, 90, 90, 90), -1)) } catch (e: Exception) { }
        refreshQueueStats(); update()
    }

    /** The PC finished a meeting of this phone: one "summary ready" notification (not while its screen is open). */
    private fun meetingReady(id: String) {
        val m = Meeting.known(this, id) ?: return
        if (Meeting.notified(this, id)) return
        Meeting.setNotified(this, id)
        if (MeetingActivity.showing == id) return
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(NotificationChannel("meeting", "סיכומי פגישות", NotificationManager.IMPORTANCE_DEFAULT))
        val open = PendingIntent.getActivity(this, 100 + (id.hashCode() and 0xffff),
            Intent(this, MeetingActivity::class.java).putExtra("id", id), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        nm.notify(7, Notification.Builder(this, "meeting").setSmallIcon(R.drawable.ic_stat).setColor(0xFFEAA45E.toInt())
            .setContentTitle("סיכום הפגישה מוכן")
            .setContentText(m.optString("title").ifEmpty { "פגישה" } + " · תמלול, סיכום ומשימות")
            .setContentIntent(open).setAutoCancel(true).build())
    }

    private fun wearer() = Prefs.role(this) == "wearer"
    private fun enrolling() = System.currentTimeMillis() < enrollUntil

    /** Is the microphone allowed to be open right now? Also sets [blocked] (the reason, for both screens)
     *  and [reasonKey]/[reasonDetail] (the same reason for the Timeline the PC reads). */
    private fun listening(): Boolean {
        val now = System.currentTimeMillis()
        // teaching the owner's voice and a meeting the user started override the rest
        if (now < enrollUntil || meetId.isNotEmpty()) { blocked = ""; reasonKey = ""; reasonDetail = ""; return true }
        if (draining > 0L) { blocked = "שולח למחשב ואז נכבה"; reasonKey = "pause"; reasonDetail = ""; return false }
        var key = ""; var det = ""
        val why = when {
            paused -> { key = "pause"; "מושהה" }
            now < mutedUntil -> { key = "mute"; "מושתק עד " + SimpleDateFormat("HH:mm", Locale.US).format(Date(mutedUntil)) }
            zoneName.isNotEmpty() -> { key = "private"; det = zoneName; "אזור פרטי: $zoneName" }
            calMute -> { key = "cal"; "אירוע פרטי ביומן: $calTitle" }
            lowBat -> { key = "battery"; "סוללה חלשה ($batPct%)" }
            !wearer() && !atHome -> { key = "away"; "מחוץ לבית" }
            wearer() && !atHome && enrolled in 0 until minSamples -> { key = "enroll_needed"; "מחוץ לבית: צריך ללמד את הקול שלך כדי להקליט בחוץ" }
            wearer() && !atHome && enrolled < 0 -> { key = "enroll_needed"; "מחוץ לבית: עוד לא ידוע אם הקול שלך נלמד" }
            else -> ""
        }
        blocked = why; reasonKey = key; reasonDetail = det
        return why.isEmpty()
    }

    // ------------------------------------------------------------ context: place, calendar, battery
    private val locListener = object : LocationListener {
        override fun onLocationChanged(l: Location) { lat = l.latitude; lon = l.longitude }
        @Deprecated("old API") override fun onStatusChanged(p: String?, s: Int, e: Bundle?) {}
        override fun onProviderEnabled(p: String) {}
        override fun onProviderDisabled(p: String) {}
    }

    private fun startLocation() {
        if (locRegistered) return
        try {
            val lm = getSystemService(LOCATION_SERVICE) as LocationManager
            for (p in listOf(LocationManager.NETWORK_PROVIDER, LocationManager.PASSIVE_PROVIDER)) {
                if (lm.allProviders.contains(p)) {
                    lm.requestLocationUpdates(p, 120_000L, 80f, locListener, Looper.getMainLooper())
                    lm.getLastKnownLocation(p)?.let { if (lat.isNaN()) { lat = it.latitude; lon = it.longitude } }
                }
            }
            locRegistered = true
        } catch (e: SecurityException) { } catch (e: Exception) { }
    }

    private fun stopLocation() {
        if (!locRegistered) return
        try { (getSystemService(LOCATION_SERVICE) as LocationManager).removeUpdates(locListener) } catch (e: Exception) { }
        locRegistered = false
    }

    private fun calendarNow(): String {
        if (checkSelfPermission(android.Manifest.permission.READ_CALENDAR) != PackageManager.PERMISSION_GRANTED) return ""
        return try {
            val now = System.currentTimeMillis()
            val cur = CalendarContract.Instances.query(contentResolver,
                arrayOf(CalendarContract.Instances.TITLE, CalendarContract.Instances.ALL_DAY), now, now + 1)
            cur.use {
                var title = ""
                while (it.moveToNext()) {
                    if (it.getInt(1) == 0 && !it.getString(0).isNullOrBlank()) { title = it.getString(0); break }
                }
                title
            }
        } catch (e: Exception) { "" }
    }

    /** every 30 s: zone, calendar event, battery */
    private fun refreshContext() {
        var z = ""
        if (!lat.isNaN()) {
            val zs = Prefs.zones(this)
            for (i in 0 until zs.length()) {
                val o = zs.getJSONObject(i)
                val d = FloatArray(1)
                Location.distanceBetween(lat, lon, o.getDouble("lat"), o.getDouble("lon"), d)
                if (d[0] <= o.optDouble("r", 150.0)) { z = o.optString("n", "פרטי"); break }
            }
        }
        zoneName = z
        calTitle = calendarNow()
        val words = Prefs.calWords(this).split(",").map { it.trim().lowercase() }.filter { it.isNotEmpty() }
        calMute = calTitle.isNotEmpty() && words.any { calTitle.lowercase().contains(it) }
        val b = registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        if (b != null) {
            val level = b.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
            val scale = b.getIntExtra(BatteryManager.EXTRA_SCALE, 100)
            batPct = if (level >= 0) level * 100 / scale else -1
            val plugged = b.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) != 0
            lowBat = batPct in 1..8 && !plugged
            charging = plugged; chargingNow = plugged; batNow = batPct
        }
    }

    // ------------------------------------------------------------ the microphone was taken by a call / another app
    private val arCb = object : AudioManager.AudioRecordingCallback() {
        override fun onRecordingConfigChanged(configs: MutableList<AudioRecordingConfiguration>) {
            val mine = configs.firstOrNull { it.clientAudioSessionId == recSession }
            val sil = mine?.isClientSilenced ?: false
            if (sil != silenced) { silenced = sil; silencedNow = sil; update() }
        }
    }

    // ------------------------------------------------------------ "mark this moment"
    /** The star: "this moment matters". The PC keeps every recording [min] minutes before and after it (they are never
     *  deleted) and keeps the conversation even when it would otherwise be dropped. The file holds "ms,minutes". */
    private fun mark(min: Int = 10) {
        val now = System.currentTimeMillis()
        try { File(queueDir, SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS", Locale.US).format(Date(now)) + "_mark.txt")
            .writeText("$now,$min") } catch (e: Exception) { }
        try {                                                  // two clear pulses = "got it"
            val v = getSystemService(VIBRATOR_SERVICE) as Vibrator
            v.vibrate(VibrationEffect.createWaveform(longArrayOf(0, 90, 90, 90), -1))
        } catch (e: Exception) { }
        lastMarkAt = now; lastMarkMin = min; lastMarkSent = false
        addMark(this)
        refreshQueueStats()
        update()
    }

    // ------------------------------------------------------------ "at home" = the PC answers on the home address or the home Wi-Fi
    private fun query(tl: String): String {
        val st = URLEncoder.encode(state, "UTF-8")
        return "device=${device()}&state=$st&sent=$sent&queued=$queued&role=${Prefs.role(this)}&bat=$batPct&sil=${if (silenced) 1 else 0}" +
            "&qmb=${"%.1f".format(Locale.US, queuedBytes / 1e6)}&oldest=${if (oldestMs > 0) (System.currentTimeMillis() - oldestMs) / 1000 else 0}" +
            "&skew=$skew&vpn=${if (vpnOn) 1 else 0}&chg=${if (charging) 1 else 0}&speech=${"%.0f".format(Locale.US, speechSecToday())}" +
            "&tl=" + URLEncoder.encode(tl, "UTF-8")
    }

    private fun speechSecToday(): Float = speechToday(this) * 60f

    /** One heartbeat to [base]. True only for a real answer from our PC (JSON with now_ms): another device on a
     *  foreign Wi-Fi that happens to own the same address must never read as "home". It doubles as the heartbeat
     *  (state, queue, recording timeline) and brings back the PC's clock, the owner's voice samples and the digest. */
    private fun pingOne(base: String, timeoutMs: Int): Boolean = try {
        val (tl, nTl) = Timeline.pending(this, System.currentTimeMillis())
        val c = URL(base + "/home/api/status?" + query(tl)).openConnection() as HttpURLConnection
        c.connectTimeout = timeoutMs; c.readTimeout = timeoutMs
        c.setRequestProperty("X-Home-Token", Prefs.token(this))      // without it the PC answers with the clock only
        val t0 = System.currentTimeMillis()
        var ok = false
        if (c.responseCode == 200) {
            try {
                val j = org.json.JSONObject(c.inputStream.bufferedReader().readText())
                val t1 = System.currentTimeMillis()
                if (j.has("now_ms")) {
                    ok = true
                    skew = j.getLong("now_ms") - (t0 + t1) / 2
                    Timeline.ack(this, nTl)
                    if (!j.isNull("owner_enrolled")) enrolled = j.getInt("owner_enrolled")
                    if (j.has("owner_min_samples")) minSamples = j.getInt("owner_min_samples")
                    val d = j.optJSONObject("digest")
                    if (d != null) { digestTeach = d.optInt("teach"); digestTasks = d.optInt("tasks_open"); maybeDigest(d) }
                    j.optJSONArray("meetings_done")?.let { a -> for (i in 0 until a.length()) meetingReady(a.optString(i)) }
                }
            } catch (e: Exception) { }
        }
        c.disconnect(); ok
    } catch (e: Exception) { false }

    /** Home address first (2 s), then the remote Tailscale address (5 s). */
    private fun ping(): Boolean {
        val lan = Prefs.server(this)
        if (pingOne(lan, 2000)) { activeServer = lan; lanOk = true; viaTailscale = false; return true }
        lanOk = false
        val rem = Prefs.remote(this)
        if (rem.isNotEmpty() && pingOne(rem, 5000)) { activeServer = rem; viaTailscale = true; return true }
        viaTailscale = false; activeServer = ""
        return false
    }

    private fun vpnActive(): Boolean = try {
        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as android.net.ConnectivityManager
        cm.allNetworks.any { cm.getNetworkCapabilities(it)?.hasTransport(android.net.NetworkCapabilities.TRANSPORT_VPN) == true }
    } catch (e: Exception) { false }

    private fun maybeDigest(d: org.json.JSONObject) {
        val today = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())
        val hour = java.util.Calendar.getInstance().get(java.util.Calendar.HOUR_OF_DAY)
        if (hour < 20 || Prefs.digestDay(this) == today || !d.optBoolean("ready")) return
        Prefs.setDigestDay(this, today)
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(NotificationChannel("digest", "סיכום יום", NotificationManager.IMPORTANCE_DEFAULT))
        val teach = d.optInt("teach")
        val target = if (teach > 0) Intent(this, TeachActivity::class.java) else Intent(this, MainActivity::class.java)
        val open = PendingIntent.getActivity(this, 5, target, PendingIntent.FLAG_IMMUTABLE)
        nm.notify(3, Notification.Builder(this, "digest").setSmallIcon(R.drawable.ic_stat)
            .setColor(0xFFEAA45E.toInt()).setContentTitle("סיכום היום מוכן")
            .setContentText("${d.optInt("conversations")} שיחות · ${d.optInt("tasks_open")} משימות פתוחות" +
                (if (teach > 0) " · $teach קולות ללמד" else ""))
            .setStyle(Notification.BigTextStyle().bigText(d.optString("summary") + (if (d.optString("notice").isNotBlank() && d.optString("notice") != "null") "\n\n" + d.optString("notice") else "")))
            .setContentIntent(open).setAutoCancel(true).build())
    }

    /** Current Wi-Fi name, "" when unknown (no Wi-Fi, no location permission, or location off). */
    @Suppress("DEPRECATION")
    private fun ssid(): String = try {
        val wm = applicationContext.getSystemService(Context.WIFI_SERVICE) as android.net.wifi.WifiManager
        val s = wm.connectionInfo?.ssid ?: ""
        if (s.isBlank() || s.contains("unknown ssid")) "" else s.trim('"')
    } catch (e: Exception) { "" }

    /** Home = the PC answers on the home address, or the home Wi-Fi (its name is learnt only when the home address
     *  answered). An answer over Tailscale never means "home". */
    private fun homeLoop() {
        while (running) {
            try { refreshContext() } catch (e: Exception) { }
            vpnOn = vpnActive()
            val ok = ping()
            if (ok) lastPcOk = System.currentTimeMillis()
            pcOnline = ok
            val s = ssid()
            ssidNow = s
            if (lanOk && s.isNotEmpty() && Prefs.homeSsid(this).isEmpty()) Prefs.setHomeSsid(this, s)
            val home = lanOk || (s.isNotEmpty() && s == Prefs.homeSsid(this))
            if (home != atHome) {
                atHome = home; update()
                if (ok) ping()                               // report the new state at once
            } else update()
            watchdog()
            Thread.sleep(30_000)
        }
    }

    /** ColorOS and friends sometimes leave the service alive with a dead microphone: no audio frames for 2 minutes
     *  while we should be listening -> close the recorder (this unblocks a stuck read) and let the loop reopen it. */
    private fun watchdog() {
        if (!blocked.isEmpty() || recRef == null) return
        if (System.currentTimeMillis() - lastFrameAt > 120_000L) {
            Timeline.gap(this, lastFrameAt, System.currentTimeMillis(), "stall")
            try { recRef?.stop() } catch (e: Exception) { }
            try { recRef?.release() } catch (e: Exception) { }
            recRef = null
            lastFrameAt = System.currentTimeMillis()
            val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
            nm.createNotificationChannel(NotificationChannel("warn", "תקלות והתראות", NotificationManager.IMPORTANCE_DEFAULT))
            nm.notify(4, Notification.Builder(this, "warn").setSmallIcon(R.drawable.ic_stat).setColor(0xFFEAA45E.toInt())
                .setContentTitle("שמע: המיקרופון נתקע")
                .setContentText("לא הגיע שמע שתי דקות. פותח את ההקלטה מחדש.").setAutoCancel(true).build())
        }
    }

    /** Called when state changes (mute / pause / resume) so the PC screen follows within a second. */
    private fun pingSoon() { thread { ping() } }

    // ------------------------------------------------------------ recording + Silero VAD
    // 32 ms frames; start after 3 speech frames (~100 ms), keep 0.5 s before it, end after
    // 0.8 s without speech, cut at 30 s so the PC screen stays close to real time.
    private fun recordLoop() {
        val frame = Vad.FRAME
        val minBuf = AudioRecord.getMinBufferSize(SR, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val vad = try { Vad(this) } catch (e: Exception) { null }
        var rec: AudioRecord? = null
        val buf = ShortArray(frame)
        val pre = ArrayDeque<ShortArray>()                    // 0.5 s pre-roll
        var seg: MutableList<ShortArray>? = null
        var segStart = 0L
        var quiet = 0
        var on = 0
        // non-speech sounds (door, microwave, bell, ball ...): a jump >= 15 dB over the room's floor -- at home only
        var snd: MutableList<ShortArray>? = null
        var sndStart = 0L
        var sndQuiet = 0
        var lastSnd = 0L
        var floorDb = -60.0
        var lastTl = 0L
        while (running) {
            if (cutReq || meetEndReq) {                        // a meeting starts / ends: the open segment belongs to what came before
                seg?.let { if (it.size > 30) save(it, segStart) }; seg = null; on = 0
                if (speaking) { speaking = false; update() }
                cutReq = false
                if (meetEndReq) finishMeeting()
            }
            val ok = listening()
            val nowTl = System.currentTimeMillis()
            if (nowTl - lastTl >= 1000) {                      // what the microphone did, for the PC's coverage strip
                lastTl = nowTl
                Timeline.tick(this, nowTl, if (!ok) reasonKey else if (silenced) "busy" else "", reasonDetail)
            }
            if (!ok) {
                rec?.let { try { it.stop(); it.release() } catch (e: Exception) { } }; rec = null; recRef = null; recSession = -1
                seg?.let { if (it.size > 30) save(it, segStart) }; seg = null
                snd = null
                vad?.reset()
                if (speaking) { speaking = false; update() }
                Thread.sleep(1000); continue
            }
            if (rec == null) {
                rec = AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, SR, AudioFormat.CHANNEL_IN_MONO,
                    AudioFormat.ENCODING_PCM_16BIT, maxOf(minBuf, frame * 2 * 8))
                recSession = rec.audioSessionId
                rec.startRecording()
                recRef = rec
                lastFrameAt = System.currentTimeMillis()
            }
            var got = 0
            while (got < frame) {                              // exactly one 512-sample frame
                val n = rec.read(buf, got, frame - got)
                if (n <= 0) break
                got += n
            }
            if (got < frame) {                                 // the recorder died (or the watchdog closed it): reopen
                try { rec.stop(); rec.release() } catch (e: Exception) { }
                rec = null; recRef = null; recSession = -1
                Thread.sleep(500); continue
            }
            lastFrameAt = System.currentTimeMillis()
            val f = buf.copyOf()
            if (silenced) continue                             // a call / another app has the microphone: a gap, not speech
            val p = vad?.prob(f) ?: energyProb(f)
            if (p >= 0.5f && System.currentTimeMillis() < enrollUntil) enrollSpeechMs += 32     // for the voice screen
            val db = dbfs(f)
            if (seg == null && snd == null) floorDb = if (db < floorDb) floorDb * 0.9 + db * 0.1 else floorDb * 0.998 + db * 0.002
            if (seg == null && p < 0.35f && atHome) {
                val now = System.currentTimeMillis()
                if (snd == null && db > floorDb + 15 && db > -45 && now - lastSnd > 8_000) {
                    snd = pre.toMutableList(); sndStart = now - snd.size * 32L; sndQuiet = 0
                } else if (snd != null) {
                    snd.add(f)
                    sndQuiet = if (db > floorDb + 6) 0 else sndQuiet + 1
                    if (sndQuiet >= 19 || snd.size >= 156) {      // 0.6 s back to the floor, or 5 s
                        save(snd, sndStart, sound = true); snd = null; lastSnd = now
                    }
                }
            } else if (snd != null) {
                snd = null                                         // speech started: the speech segment keeps it
            }
            if (seg == null) {
                pre.addLast(f); if (pre.size > 16) pre.removeFirst()
                on = if (p >= 0.5f) on + 1 else 0
                if (on >= 3) {
                    seg = pre.toMutableList(); pre.clear()
                    segStart = System.currentTimeMillis() - seg.size * 32L
                    quiet = 0
                    if (!speaking) { speaking = true; update() }
                }
            } else {
                seg.add(f)
                quiet = if (p >= 0.35f) 0 else quiet + 1
                if (quiet >= 25 || seg.size >= 940) {          // 0.8 s quiet or 30 s
                    save(seg, segStart); seg = null; on = 0
                    if (quiet >= 25) { speaking = false; update() }
                }
            }
        }
        rec?.let { try { it.stop(); it.release() } catch (e: Exception) { } }
        recRef = null
        vad?.close()
    }

    private fun dbfs(f: ShortArray): Double {
        var s = 0.0
        for (v in f) s += v.toDouble() * v
        return 20 * Math.log10(sqrt(s / f.size) / 32768.0 + 1e-9)
    }

    /** Fallback if the model cannot load: plain loudness. */
    private var floor = 300.0
    private fun energyProb(f: ShortArray): Float {
        var s = 0.0
        for (v in f) s += v.toDouble() * v
        val rms = sqrt(s / f.size)
        val speechy = rms > floor * 3.0 && rms > 250
        floor = if (!speechy) floor * 0.995 + rms * 0.005 else floor * 0.9995 + rms * 0.0005
        return if (speechy) 1f else 0f
    }

    /** Segments are encoded on their own thread so the microphone loop never stops reading. Encoding inline took about
     *  0.5 s per second of audio while AudioRecord's small buffer overflowed: after every segment the phone was deaf for
     *  half its length (measured 2026-10-15 from the gaps between segment starts: ~15 s lost after each 30 s segment). */
    private val encoder = java.util.concurrent.ThreadPoolExecutor(1, 1, 30, java.util.concurrent.TimeUnit.SECONDS,
        java.util.concurrent.LinkedBlockingQueue<Runnable>()) { r -> Thread(r, "encode").apply { isDaemon = true } }
        .apply { allowCoreThreadTimeOut(true) }           // no shutdown needed: the thread ends after 30 s idle

    private fun save(frames: List<ShortArray>, start: Long, sound: Boolean = false) {
        val pcm = ShortArray(frames.sumOf { it.size })
        var i = 0
        for (f in frames) { f.copyInto(pcm, i); i += f.size }
        val stamp = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS", Locale.US).format(Date(start))
        val enroll = !sound && start >= enrollFrom - 600 && start < enrollUntil && enrollUntil > 0
        val base = File(queueDir, when { sound -> "${stamp}_snd"; enroll -> "${stamp}_enr"; else -> stamp })
        // the context of this segment (as it is now, when the segment ends), sent along with it
        val m = StringBuilder("ms=$start&home=${if (atHome) 1 else 0}&role=${Prefs.role(this)}&bat=$batPct")
        if (!lat.isNaN()) m.append("&lat=${"%.4f".format(Locale.US, lat)}&lon=${"%.4f".format(Locale.US, lon)}")
        if (!sound && meetId.isNotEmpty() && start >= meetStart - 1000) {        // a segment of the meeting being recorded
            m.append("&meet=").append(meetId).append("&cal=")
                .append(URLEncoder.encode("📋 פגישה" + (if (meetTitle.isNotEmpty()) ": " + meetTitle.take(60) else ""), "UTF-8"))
        } else if (calTitle.isNotEmpty()) m.append("&cal=").append(URLEncoder.encode(calTitle.take(80), "UTF-8"))
        val meta = m.toString()
        try {
            encoder.execute {
                var out: File? = null
                try {
                    out = encodeAudio(pcm, base)
                    File(queueDir, "${out.name}.meta").writeText(meta)
                    if (!sound && !enroll) addSpeech(this, pcm.size.toDouble() / SR)
                } catch (e: Exception) { out?.delete() }
                refreshQueueStats()
                update()
            }
        } catch (e: java.util.concurrent.RejectedExecutionException) { }
    }

    /** Opus 12 kbps in an Ogg (about 5 MB per hour of speech); AAC-LC 24 kbps .m4a if this phone has no Opus encoder. */
    private fun encodeAudio(pcm: ShortArray, base: File): File {
        val ogg = File(base.path + ".ogg")
        try {
            encode(pcm, ogg, opus = true)
            if (ogg.length() < 64) throw IllegalStateException("empty opus file")
            return ogg
        } catch (e: Exception) { ogg.delete() }
        val m4a = File(base.path + ".m4a")
        encode(pcm, m4a, opus = false)
        return m4a
    }

    /** PCM 16 kHz mono -> compressed file (MediaCodec + MediaMuxer, no libraries). */
    private fun encode(pcm: ShortArray, out: File, opus: Boolean) {
        val mime = if (opus) MediaFormat.MIMETYPE_AUDIO_OPUS else MediaFormat.MIMETYPE_AUDIO_AAC
        val fmt = MediaFormat.createAudioFormat(mime, SR, 1).apply {
            if (opus) setInteger(MediaFormat.KEY_BIT_RATE, 12000)
            else {
                setInteger(MediaFormat.KEY_AAC_PROFILE, MediaCodecInfo.CodecProfileLevel.AACObjectLC)
                setInteger(MediaFormat.KEY_BIT_RATE, 24000)
            }
        }
        val codec = MediaCodec.createEncoderByType(mime)
        var mux: MediaMuxer? = null
        try {
            codec.configure(fmt, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
            codec.start()
            // Opus: our own Ogg writer (MediaMuxer's OGG output wastes a page header on every 20 ms packet)
            val mx = if (opus) null else MediaMuxer(out.path, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
            mux = mx
            var ogg: OggOpus? = null
            var track = -1
            var pos = 0
            var inputDone = false
            var wrote = 0
            val info = MediaCodec.BufferInfo()
            val bytes = java.nio.ByteBuffer.allocate(pcm.size * 2).order(java.nio.ByteOrder.LITTLE_ENDIAN)
            bytes.asShortBuffer().put(pcm)
            val all = bytes.array()
            var idle = 0
            while (true) {
                if (!inputDone) {
                    val ii = codec.dequeueInputBuffer(10_000)
                    if (ii >= 0) {
                        val ib = codec.getInputBuffer(ii)!!
                        val len = minOf(ib.capacity(), all.size - pos)
                        val pts = pos.toLong() / 2 * 1_000_000 / SR
                        if (len <= 0) {
                            codec.queueInputBuffer(ii, 0, 0, pts, MediaCodec.BUFFER_FLAG_END_OF_STREAM); inputDone = true
                        } else {
                            ib.put(all, pos, len); codec.queueInputBuffer(ii, 0, len, pts, 0); pos += len
                        }
                    }
                }
                val oi = codec.dequeueOutputBuffer(info, 10_000)
                if (oi == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    if (opus) {
                        // csd-0 is Android's wrapper (AOPUSHDR ... AOPUSDLY <ns> ...): take only the encoder delay from it
                        var pre = 312
                        val csd = codec.outputFormat.getByteBuffer("csd-0")
                        if (csd != null) {
                            val raw = ByteArray(csd.remaining()).also { csd.duplicate().get(it) }
                            val k = String(raw, Charsets.ISO_8859_1).indexOf("AOPUSDLY")
                            if (k >= 0 && raw.size >= k + 24) {
                                var ns = 0L
                                for (i in 7 downTo 0) ns = (ns shl 8) or (raw[k + 16 + i].toLong() and 0xFF)
                                if (ns in 1..40_000_000L) pre = (ns * 48000 / 1_000_000_000L).toInt()
                            }
                        }
                        ogg = OggOpus(OggOpus.opusHead(pre), pre)
                        track = 0
                    } else { track = mx!!.addTrack(codec.outputFormat); mx.start() }
                } else if (oi >= 0) {
                    idle = 0
                    val ob = codec.getOutputBuffer(oi)!!
                    if (info.size > 0 && track >= 0 && info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG == 0) {
                        if (opus) {
                            val pk = ByteArray(info.size); ob.position(info.offset); ob.get(pk, 0, info.size); ogg?.add(pk)
                        } else mx!!.writeSampleData(track, ob, info)
                        wrote++
                    }
                    codec.releaseOutputBuffer(oi, false)
                    if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) break
                } else if (++idle > 500) throw IllegalStateException("encoder stuck")
            }
            if (wrote == 0) throw IllegalStateException("no encoded data")
            if (opus) ogg!!.write(out, pcm.size) else mx!!.stop()
        } finally {
            try { codec.stop() } catch (e: Exception) { }
            codec.release()
            try { mux?.release() } catch (e: Exception) { }
        }
    }

    // ------------------------------------------------------------ upload queue (deleted after the PC confirms)
    /** Enrolment recordings and the star marks go first, then oldest to newest. */
    private fun queueFiles() = (queueDir.listFiles() ?: emptyArray()).filter { !it.name.endsWith(".meta") }
        .sortedWith(compareBy({ !(it.name.contains("_enr") || it.name.endsWith("_mark.txt")) }, { it.name }))

    private fun fileTime(f: File): Long = try {
        SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS", Locale.US).parse(f.name.substring(0, 23))!!.time
    } catch (e: Exception) { f.lastModified() }

    private fun refreshQueueStats() {
        val files = queueFiles().filter { !it.name.endsWith(".txt") }      // recordings only (not stars / meeting ends)
        queued = files.size
        queuedBytes = (queueDir.listFiles() ?: emptyArray()).sumOf { it.length() }
        oldestMs = files.minOfOrNull { fileTime(it) } ?: 0L
    }

    /** The PC stayed away for a long time: keep the phone's storage bounded (sounds first, then the oldest speech).
     *  Enrolment recordings and star marks are never dropped. */
    private fun trimQueue() {
        var total = (queueDir.listFiles() ?: emptyArray()).sumOf { it.length() }
        if (total <= QUEUE_LIMIT) return
        val order = queueFiles().sortedWith(compareBy({ !it.name.contains("_snd") }, { it.name }))
        for (f in order) {
            if (total <= QUEUE_LIMIT * 0.9) break
            if (f.name.contains("_enr") || f.name.contains("_imp") || f.name.endsWith(".txt")) continue
            total -= f.length() + File(queueDir, f.name + ".meta").length()
            f.delete(); File(queueDir, f.name + ".meta").delete()
        }
    }

    /** More than 48 h without the PC: one soft reminder (twice a day at most). */
    private fun maybeStaleWarning() {
        val now = System.currentTimeMillis()
        if (pcOnline || oldestMs == 0L || now - oldestMs < 48 * 3600_000L) return
        val p = getSharedPreferences("home", Context.MODE_PRIVATE)
        if (now - p.getLong("stale_warn", 0L) < 12 * 3600_000L) return
        p.edit().putLong("stale_warn", now).apply()
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(NotificationChannel("warn", "תקלות והתראות", NotificationManager.IMPORTANCE_DEFAULT))
        nm.notify(6, Notification.Builder(this, "warn").setSmallIcon(R.drawable.ic_stat).setColor(0xFFEAA45E.toInt())
            .setContentTitle("המחשב לא זמין כבר ${(now - oldestMs) / 3600_000L} שעות")
            .setContentText("$queued קטעים (${"%.0f".format(Locale.US, queuedBytes / 1e6)} MB) ממתינים בטלפון. הם יישלחו כשהמחשב יענה.")
            .setAutoCancel(true).build())
    }

    private fun uploadLoop() {
        var lastTrim = 0L
        while (running) {
            if (System.currentTimeMillis() - lastTrim > 60_000) {
                trimQueue(); maybeStaleWarning(); lastTrim = System.currentTimeMillis()
                try { CallImport.scan(this, queueDir) } catch (e: Exception) { }   // the dialer's call recordings
            }
            refreshQueueStats()
            val files = queueFiles()
            var failed = false
            val now = System.currentTimeMillis()
            // on only for a meeting / the voice reading, and it is over: stop recording, stop the service once all was sent
            if (tempRun && meetId.isEmpty() && !enrolling() && !meetEndReq) {
                if (draining == 0L) { draining = now; update() }
                else if (!speaking && now - draining > 4000 && files.isEmpty()) { ui.post { if (draining > 0L) stopAll() }; return }
            }
            // hold: low battery (not charging), or away from home and the batch is neither old (4 min) nor big (> 20 files);
            // a finished meeting goes at once (its summary is awaited)
            val lowBatHold = batPct in 1 until SEND_MIN_BAT && !charging
            val awayHold = !atHome && files.size <= AWAY_BATCH_FILES && files.isNotEmpty() && draining == 0L &&
                files.none { it.name.endsWith("_meetend.txt") } && now - (files.minOf { fileTime(it) }) < AWAY_BATCH_MS
            if (files.isEmpty() || lowBatHold || awayHold || !pcOnline) {
                Thread.sleep(if (awayHold) 10_000 else 15_000); continue
            }
            for (f in files) {
                if (!pcOnline || !running) { failed = true; break }
                if (send(f)) {
                    f.delete(); File(queueDir, f.name + ".meta").delete()
                    if (f.name.endsWith("_mark.txt")) lastMarkSent = true else if (!f.name.endsWith(".txt")) { sent++; countSent(this) }
                    lastSentAt = System.currentTimeMillis(); refreshQueueStats(); update()
                } else { failed = true; break }
            }
            Thread.sleep(if (failed) 15_000 else 1_000)
        }
    }

    private fun send(f: File): Boolean = try {
        val n = f.name
        val start = n.substring(0, 23)                       // yyyy-MM-dd'T'HH:mm:ss.SSS
        val isMark = n.endsWith("_mark.txt")
        val isMeetEnd = n.endsWith("_meetend.txt")
        val kind = when { n.contains("_snd.") -> "sound"; n.contains("_enr.") -> "enroll"; n.contains("_imp.") -> "import"; else -> "speech" }
        val meta = File(queueDir, "$n.meta").takeIf { it.exists() }?.readText() ?: "role=${Prefs.role(this)}&home=1"
        val common = "device=${device()}&start=$start&skew=$skew"
        val base = activeServer.ifEmpty { Prefs.server(this) }
        val c: HttpURLConnection
        if (isMark) {
            val parts = f.readText().trim().split(",")
            c = URL(base + "/home/api/mark?$common&ms=${parts[0]}&min=${parts.getOrNull(1) ?: "10"}").openConnection() as HttpURLConnection
            c.requestMethod = "POST"; c.doOutput = true; c.setFixedLengthStreamingMode(0)
        } else if (isMeetEnd) {                              // "id,start ms,end ms,title (url-encoded)"
            val parts = f.readText().trim().split(",")
            c = URL(base + "/home/api/meeting_end?$common&id=${parts[0]}&ms0=${parts.getOrElse(1) { "" }}" +
                "&ms1=${parts.getOrElse(2) { "" }}&title=${parts.getOrElse(3) { "" }}").openConnection() as HttpURLConnection
            c.requestMethod = "POST"; c.doOutput = true; c.setFixedLengthStreamingMode(0)
        } else {
            val ext = f.extension.ifEmpty { "m4a" }
            c = URL(base + "/home/api/chunk?$common&kind=$kind&ext=$ext&$meta").openConnection() as HttpURLConnection
            c.requestMethod = "POST"; c.doOutput = true
            c.setRequestProperty("Content-Type", when (ext) { "m4a" -> "audio/mp4"; "ogg", "opus" -> "audio/ogg"; else -> "application/octet-stream" })
            c.setFixedLengthStreamingMode(f.length())
        }
        c.connectTimeout = if (viaTailscale) 8000 else 5000; c.readTimeout = 60000
        c.setRequestProperty("X-Home-Token", Prefs.token(this))
        if (!isMark && !isMeetEnd) c.outputStream.use { o -> f.inputStream().use { it.copyTo(o) } } else c.outputStream.close()
        val code = c.responseCode
        val ok = code == 200 || (isMeetEnd && code == 404)  // a PC program older than meetings: never block the queue
        c.disconnect(); ok
    } catch (e: Exception) { false }

    // ------------------------------------------------------------ notification
    private fun ageText(ms: Long): String {
        val h = ms / 3600_000L
        return if (h < 1) "${maxOf(1, ms / 60_000L)} דקות" else if (h < 48) "$h שעות" else "${h / 24} ימים"
    }

    private fun queueText(): String =
        "ממתינים $queued קטעים · ${"%.0f".format(Locale.US, queuedBytes / 1e6)} MB" +
            (if (oldestMs > 0) " · הישן מלפני ${ageText(System.currentTimeMillis() - oldestMs)}" else "")

    private fun linkText(): String = when {
        lanOk -> "מחובר בבית"
        viaTailscale -> "מחובר דרך Tailscale"
        else -> ""
    }

    private fun update() {
        home = atHome; hearing = speaking; pausedNow = paused; mutedUntilNow = mutedUntil; silencedNow = silenced
        listening()                                           // refreshes [blocked]
        state = when {
            enrolling() -> "לומד את הקול שלך · דבר עכשיו"
            meetId.isNotEmpty() && silenced -> "📋 פגישה · המיקרופון תפוס (שיחה או אפליקציה אחרת)"
            meetId.isNotEmpty() -> "📋 מקליט פגישה" + (if (meetTitle.isNotEmpty()) ": $meetTitle" else "") + (if (speaking) " · שומע דיבור" else "")
            draining > 0L -> "שולח למחשב" + (if (queued > 0) " ($queued ממתינים)" else "") + " · ייכבה בסיום"
            silenced -> "המיקרופון תפוס (שיחה או אפליקציה אחרת)"
            blocked.isNotEmpty() -> if (reasonKey == "private" || reasonKey == "cal") "פרטי: ${reasonDetail.ifEmpty { calTitle }} · לא מקליט" else "$blocked — לא מקליט"
            !pcOnline -> "מקשיב · שומר בטלפון ($queued ממתינים)"
            else -> "מקשיב" + (if (speaking) " · שומע דיבור" else "") + " · " + linkText()
        }
        stateLine = state
        (getSystemService(NOTIFICATION_SERVICE) as NotificationManager).notify(1, notification())
    }

    private fun notification(): Notification {
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "שמע", NotificationManager.IMPORTANCE_LOW))
        fun act(a: String, code: Int) = PendingIntent.getService(this, code,
            Intent(this, ListenService::class.java).setAction(a), PendingIntent.FLAG_IMMUTABLE)
        if (meetId.isNotEmpty()) {                            // a meeting: its own screen, a running clock and "end"
            return Notification.Builder(this, CHANNEL).setSmallIcon(R.drawable.ic_stat).setColor(0xFFE5484D.toInt())
                .setContentTitle(state).setContentText("הקש כדי לראות · הסיכום יגיע אחרי שתסיים")
                .setUsesChronometer(true).setWhen(meetStart).setShowWhen(true).setOngoing(true)
                .setContentIntent(PendingIntent.getActivity(this, 6, Intent(this, MeetingActivity::class.java), PendingIntent.FLAG_IMMUTABLE))
                .addAction(Notification.Action.Builder(null, "⏹ סיים פגישה", act(ACTION_MEETING_END, 4)).build())
                .addAction(Notification.Action.Builder(null, "סמן רגע ⭐", act(ACTION_MARK, 2)).build())
                .build()
        }
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat)
            .setColor(0xFFEAA45E.toInt())
            .setContentTitle(state)
            .setContentText(if (System.currentTimeMillis() - lastMarkAt < 180_000L)
                "⭐ סומן ${SimpleDateFormat("HH:mm", Locale.US).format(Date(lastMarkAt))} · נשמרות $lastMarkMin דקות לפני ואחרי · " +
                    (if (lastMarkSent) "נשלח למחשב ✓" else "ממתין לשליחה")
            else if (queued > 0 && !pcOnline) queueText() else "היום נשלחו למחשב ${sentToday(this)} קטעי דיבור" + if (queued > 0) " · $queued ממתינים" else "")
            .setOngoing(true)
            .setContentIntent(open)
            .addAction(Notification.Action.Builder(null, if (mutedUntil > System.currentTimeMillis()) "בטל השתקה" else "פרטי לשעה",
                act(if (mutedUntil > System.currentTimeMillis()) ACTION_UNMUTE else ACTION_MUTE_HOUR, 1)).build())
            .addAction(Notification.Action.Builder(null, "סמן רגע ⭐", act(ACTION_MARK, 2)).build())
            .addAction(Notification.Action.Builder(null, "כבה", act(ACTION_STOP, 3)).build())
            .build()
    }
}

