package com.shema.app

import android.Manifest
import android.content.ContentUris
import android.content.Context
import android.content.pm.PackageManager
import android.media.MediaMetadataRetriever
import android.net.Uri
import android.os.Build
import android.provider.DocumentsContract
import android.provider.MediaStore
import java.io.File
import java.net.URLEncoder
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Phone calls. Android gives no app the sound of a call: while one runs, every microphone but the dialer's
 * is silenced, and the other side never reaches the microphone at all. The phone's own dialer can record
 * calls (ColorOS, HyperOS / MIUI, One UI); this picks up each new recording and queues it as an import, so
 * the call becomes its own conversation on the PC, titled "📞 שיחה עם <name>".
 *
 * Recordings are found through MediaStore (audio whose folder or name says "call"), or in a folder the
 * user picked once (Storage Access Framework), for phones whose recorder hides its folder from MediaStore.
 * Only reads audio files: no call-log, phone-state or accessibility permission (Play policy).
 */
object CallImport {
    private fun p(c: Context) = c.getSharedPreferences("calls", Context.MODE_PRIVATE)

    fun enabled(c: Context) = p(c).getBoolean("on", false)
    fun setEnabled(c: Context, v: Boolean) {
        val e = p(c).edit().putBoolean("on", v)
        // first switch-on: recordings of the last day come too, older history stays on the phone
        if (v && p(c).getLong("since", 0L) == 0L) e.putLong("since", System.currentTimeMillis() - 24 * 3600_000L)
        e.apply()
    }
    fun tree(c: Context) = p(c).getString("tree", "")!!
    fun setTree(c: Context, v: String) = p(c).edit().putString("tree", v).apply()
    fun imported(c: Context) = p(c).getInt("n", 0)
    fun last(c: Context) = p(c).getString("last", "")!!

    val permission: String
        get() = if (Build.VERSION.SDK_INT >= 33) Manifest.permission.READ_MEDIA_AUDIO else Manifest.permission.READ_EXTERNAL_STORAGE
    fun permOk(c: Context) = c.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED

    private class Rec(val uri: Uri, val name: String, val modMs: Long, val durMs: Long, val size: Long)

    /** Queue every call recording finished since the last scan. Returns how many were queued. */
    @Synchronized
    fun scan(c: Context, queueDir: File): Int {
        if (!enabled(c)) return 0
        val since = p(c).getLong("since", 0L)
        val settle = System.currentTimeMillis() - 20_000L       // a recording still being written keeps moving its date
        val recs = (if (tree(c).isNotEmpty()) fromTree(c, since) else if (permOk(c)) fromMediaStore(c, since) else emptyList())
            .filter { it.modMs in (since + 1)..settle && it.size > 4_000 }
            .sortedBy { it.modMs }
        var n = 0
        var newest = since
        for (r in recs) {
            val dur = if (r.durMs > 0) r.durMs else duration(c, r.uri)
            if (dur in 1 until 3_000) { newest = r.modMs; continue }   // a ring cut short, nothing said
            val startMs = r.modMs - maxOf(0L, dur)
            val ext = r.name.substringAfterLast('.', "m4a").lowercase().takeIf { it.length in 2..4 } ?: "m4a"
            val stamp = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS", Locale.US).format(Date(startMs))
            val out = File(queueDir, "${stamp}_imp.$ext")
            try {
                c.contentResolver.openInputStream(r.uri)?.use { i -> out.outputStream().use { o -> i.copyTo(o) } } ?: continue
                val title = "📞 שיחה עם " + peer(r.name)
                File(queueDir, "${out.name}.meta").writeText("ms=$startMs&home=1&role=home&call=1&cal=" + URLEncoder.encode(title.take(80), "UTF-8"))
                n++
                newest = r.modMs
                p(c).edit().putString("last", title + " · " + SimpleDateFormat("d.M HH:mm", Locale.US).format(Date(startMs))).apply()
            } catch (e: Exception) { out.delete(); break }           // try again next scan
        }
        if (newest > since) p(c).edit().putLong("since", newest).putInt("n", imported(c) + n).apply()
        return n
    }

    private fun fromMediaStore(c: Context, since: Long): List<Rec> {
        val base = MediaStore.Audio.Media.EXTERNAL_CONTENT_URI
        val col = arrayOf(MediaStore.Audio.Media._ID, MediaStore.Audio.Media.DISPLAY_NAME, MediaStore.Audio.Media.RELATIVE_PATH,
            MediaStore.Audio.Media.DATE_MODIFIED, MediaStore.Audio.Media.DURATION, MediaStore.Audio.Media.SIZE)
        // ColorOS "Music/Recordings/Call Recordings", HyperOS "MIUI/sound_recorder/call_rec", One UI "Recordings/Call"
        val sel = "(${MediaStore.Audio.Media.RELATIVE_PATH} LIKE ? OR ${MediaStore.Audio.Media.DISPLAY_NAME} LIKE ? " +
            "OR ${MediaStore.Audio.Media.RELATIVE_PATH} LIKE ?) AND ${MediaStore.Audio.Media.DATE_MODIFIED} > ?"
        val out = mutableListOf<Rec>()
        try {
            c.contentResolver.query(base, col, sel, arrayOf("%call%", "call%", "%שיחות%", (since / 1000).toString()), null)?.use { q ->
                while (q.moveToNext()) out += Rec(ContentUris.withAppendedId(base, q.getLong(0)), q.getString(1) ?: "",
                    q.getLong(3) * 1000, q.getLong(4), q.getLong(5))
            }
        } catch (e: Exception) { }
        return out
    }

    /** The picked folder and its sub-folders one level down (some recorders keep a folder per contact). */
    private fun fromTree(c: Context, since: Long): List<Rec> {
        val out = mutableListOf<Rec>()
        val root = try { Uri.parse(tree(c)) } catch (e: Exception) { return out }
        fun list(docId: String, depth: Int) {
            val kids = DocumentsContract.buildChildDocumentsUriUsingTree(root, docId)
            val col = arrayOf(DocumentsContract.Document.COLUMN_DOCUMENT_ID, DocumentsContract.Document.COLUMN_DISPLAY_NAME,
                DocumentsContract.Document.COLUMN_MIME_TYPE, DocumentsContract.Document.COLUMN_LAST_MODIFIED, DocumentsContract.Document.COLUMN_SIZE)
            try {
                c.contentResolver.query(kids, col, null, null, null)?.use { q ->
                    while (q.moveToNext()) {
                        val id = q.getString(0); val mime = q.getString(2) ?: ""
                        if (mime == DocumentsContract.Document.MIME_TYPE_DIR) { if (depth < 1) list(id, depth + 1); continue }
                        val name = q.getString(1) ?: ""
                        if (!mime.startsWith("audio/") && !name.matches(Regex(".*\\.(m4a|mp3|amr|aac|wav|ogg|opus|3gp)$", RegexOption.IGNORE_CASE))) continue
                        val mod = q.getLong(3)
                        if (mod > since) out += Rec(DocumentsContract.buildDocumentUriUsingTree(root, id), name, mod, 0L, q.getLong(4))
                    }
                }
            } catch (e: Exception) { }
        }
        try { list(DocumentsContract.getTreeDocumentId(root), 0) } catch (e: Exception) { }
        return out
    }

    private fun duration(c: Context, u: Uri): Long = try {
        MediaMetadataRetriever().run {
            setDataSource(c, u)
            val d = extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)?.toLongOrNull() ?: 0L
            release(); d
        }
    } catch (e: Exception) { 0L }

    /** "Tamar Porat_20261012191432.m4a", "Call recording Tamar_241012_191432.m4a", "+972501234567 2026-10-12 19-14-32.mp3" -> who. */
    fun peer(fileName: String): String {
        var s = fileName.substringBeforeLast('.')
        s = s.replace(Regex("(?i)^(call[ _-]?recording|call[ _-]?rec|record|recording|הקלטת שיחה)[ _-]*"), "")
        // the date / time tail: 20261012191432, 241012_191432, 2026-10-12 19-14-32
        s = s.replace(Regex("[ _\\-@()\\[\\]]*(?:20)?\\d{2}[-_.]?\\d{2}[-_.]?\\d{2}(?:[ _\\-T]*\\d{2}[-_.:]?\\d{2}(?:[-_.:]?\\d{2})?)?\\)?$"), "")
        s = s.trim(' ', '_', '-', '.', '@')
        if (s.any { it.isLetter() }) s = s.replace(Regex("[ _@]*\\(?\\+?[\\d \\-]{6,}\\)?$"), "").trim()   // "תמר (050...)" -> "תמר"
        if (s.isEmpty()) return "מספר לא ידוע"
        return if (s.any { it.isLetter() }) s.replace('_', ' ') else s       // a number with no contact stays a number
    }
}
