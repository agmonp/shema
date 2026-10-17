package com.shema.app

import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.os.Handler
import android.os.Looper
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

/** Requests to the paired PC (token header). Call off the main thread; null = no answer. */
object Net {
    fun call(c: Context, method: String, path: String, json: JSONObject? = null, timeoutMs: Int = 30000): String? = try {
        val h = URL(Prefs.base(c) + path).openConnection() as HttpURLConnection
        h.requestMethod = method; h.connectTimeout = 4000; h.readTimeout = timeoutMs
        h.setRequestProperty("X-Home-Token", Prefs.token(c))
        if (json != null) {
            val b = json.toString().toByteArray()
            h.doOutput = true; h.setRequestProperty("Content-Type", "application/json"); h.setFixedLengthStreamingMode(b.size)
            h.outputStream.use { it.write(b) }
        }
        val r = if (h.responseCode == 200) h.inputStream.bufferedReader().readText() else null
        h.disconnect(); r
    } catch (e: Exception) { null }
}

/**
 * One clip at a time from the PC: a line, or part of it (s..e seconds from the line's start). The wav is downloaded
 * first and played from a file (MediaPlayer streaming with headers failed silently on some phones).
 * onState: "loading", "playing", "done", or an error text.
 */
class Clip(private val c: Context) {
    private val ui = Handler(Looper.getMainLooper())
    private var player: MediaPlayer? = null
    private var gen = 0
    var playingId = -1; private set

    fun play(id: Int, s: Double? = null, e: Double? = null, onState: (String) -> Unit) {
        stop()
        val my = ++gen
        playingId = id
        onState("loading")
        thread {
            try {
                val q = if (s != null && e != null) "?s=%.2f&e=%.2f".format(java.util.Locale.US, s, e) else ""
                val h = URL(Prefs.base(c) + "/home/audio/utt/$id$q").openConnection() as HttpURLConnection
                h.connectTimeout = 4000; h.readTimeout = 30000
                h.setRequestProperty("X-Home-Token", Prefs.token(c))
                if (h.responseCode != 200) throw RuntimeException(if (h.responseCode == 404) "ההקלטה של השורה כבר לא שמורה" else "HTTP ${h.responseCode}")
                val f = File(c.cacheDir, "clip_$id.wav")
                h.inputStream.use { i -> f.outputStream().use { o -> i.copyTo(o) } }
                h.disconnect()
                ui.post {
                    if (my != gen) return@post
                    try {
                        val mp = MediaPlayer(); player = mp
                        mp.setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
                            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
                        mp.setDataSource(f.path)
                        mp.setOnPreparedListener { p -> if (my == gen) { p.start(); onState("playing") } }
                        mp.setOnCompletionListener { if (my == gen) { playingId = -1; onState("done") }; f.delete() }
                        mp.setOnErrorListener { _, w, x -> onState("הנגינה נכשלה ($w/$x)"); true }
                        mp.prepareAsync()
                    } catch (x: Exception) { onState(x.message ?: "הנגינה נכשלה") }
                }
            } catch (x: Exception) {
                ui.post { if (my == gen) { playingId = -1; onState(x.message ?: "אין חיבור למחשב") } }
            }
        }
    }

    /** seconds played of the current clip (for the playhead), or -1 */
    fun position(): Double = try { player?.let { if (it.isPlaying) it.currentPosition / 1000.0 else -1.0 } ?: -1.0 } catch (e: Exception) { -1.0 }

    fun stop() {
        gen++
        playingId = -1
        try { player?.stop() } catch (e: Exception) { }
        player?.release(); player = null
    }
}
