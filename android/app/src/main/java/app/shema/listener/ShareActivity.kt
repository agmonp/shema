package app.shema.listener

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.webkit.MimeTypeMap
import android.widget.Toast
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * "Share" target for audio: a WhatsApp voice message, a call recording from the phone's own recorder.
 * The file goes into the upload queue as an import (its own conversation on the PC). The microphone is
 * not involved; the listening service (when it runs) does the uploading.
 */
class ShareActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val uris = mutableListOf<Uri>()
        when (intent?.action) {
            Intent.ACTION_SEND -> (intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM))?.let { uris += it }
            Intent.ACTION_SEND_MULTIPLE -> intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM)?.let { uris += it }
        }
        val dir = File(filesDir, "queue").apply { mkdirs() }
        var n = 0
        var t = System.currentTimeMillis()
        for (u in uris) try {
            val type = contentResolver.getType(u) ?: ""
            val ext = MimeTypeMap.getSingleton().getExtensionFromMimeType(type)
                ?: u.lastPathSegment?.substringAfterLast('.', "")?.takeIf { it.length in 2..4 } ?: "m4a"
            val stamp = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS", Locale.US).format(Date(t++ ))
            val out = File(dir, "${stamp}_imp.$ext")
            contentResolver.openInputStream(u)?.use { i -> out.outputStream().use { o -> i.copyTo(o) } }
            File(dir, "${out.name}.meta").writeText("ms=${t}&home=1&role=home")
            n++
        } catch (e: Exception) { }
        if (n > 0) {
            // the listening service does the uploading; it is not started from here (a share must not turn the microphone on)
            Toast.makeText(this, if (ListenService.on) "נשלח לניתוח במחשב ($n)" else "נשמר ($n). יישלח כשתפעיל את שמע", Toast.LENGTH_LONG).show()
        } else Toast.makeText(this, "לא הצלחתי לקרוא את הקובץ", Toast.LENGTH_LONG).show()
        finish()
    }
}
