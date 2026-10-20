package com.shema.app

import android.app.Activity
import android.content.ClipData
import android.content.ComponentName
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.widget.TextView
import android.widget.Toast
import androidx.core.content.FileProvider
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

/** "🎧 שתף הקלטה": one m4a from the PC (speech only, chapters = the real clock time) -> the share sheet (not back into Shema).
 *  path = "/home/audio/meeting/<id>.m4a" or "/home/audio/conv/<id>.m4a" (PC 1.0.12+ / 1.0.13+). */
object AudioShare {
    fun share(a: Activity, path: String, fallbackName: String, chooserTitle: String, btn: TextView) {
        val ui = Handler(Looper.getMainLooper())
        val was = btn.text; btn.text = "מכין קובץ…"; btn.isEnabled = false
        thread {
            var err: String? = null
            var f: File? = null
            try {
                val dir = File(a.cacheDir, "share").apply { mkdirs(); listFiles()?.forEach { it.delete() } }   // last one only
                val h = URL(Prefs.base(a) + path).openConnection() as HttpURLConnection
                h.connectTimeout = 5000; h.readTimeout = 180_000
                h.setRequestProperty("X-Home-Token", Prefs.token(a))
                if (h.responseCode == 200) {
                    val name = Regex("filename=\"([^\"]+)\"").find(h.getHeaderField("Content-Disposition") ?: "")?.groupValues?.get(1) ?: fallbackName
                    f = File(dir, name)
                    h.inputStream.use { i -> f.outputStream().use { o -> i.copyTo(o) } }
                } else err = try { JSONObject(h.errorStream.bufferedReader().readText()).optString("error") } catch (e: Exception) { null } ?: "HTTP ${h.responseCode}"
                h.disconnect()
            } catch (e: Exception) { err = "המחשב לא זמין, נסה שוב" }
            ui.post {
                btn.text = was; btn.isEnabled = true
                if (a.isFinishing || a.isDestroyed) return@post
                val file = f
                if (file == null || err != null) { Toast.makeText(a, err ?: "ההורדה נכשלה", Toast.LENGTH_LONG).show(); return@post }
                val uri = FileProvider.getUriForFile(a, "${a.packageName}.share", file)
                a.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).apply {
                    type = "audio/mp4"; putExtra(Intent.EXTRA_STREAM, uri); addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    clipData = ClipData.newRawUri("", uri)
                }, chooserTitle).putExtra(Intent.EXTRA_EXCLUDE_COMPONENTS,             // not back into Shema itself
                    arrayOf(ComponentName(a, ShareActivity::class.java))))
            }
        }
    }
}
