package com.shema.app

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper

/**
 * What the phone keeps from the PC so it can be read with the PC away (2026-11-01): every "אני" period received
 * (day / week, history kept, a newer answer replaces only its own period) and the meetings list.
 * The answers are stored as the PC sent them (JSON); the screens draw only the parts an answer has, so older saved
 * answers keep working when the PC adds fields.
 *
 * Schema changes: raise VERSION and add a step in onUpgrade (ALTER / CREATE only). Nothing is dropped: these are
 * the only copies the phone has while the PC is off.
 */
class LocalStore private constructor(c: Context) : SQLiteOpenHelper(c, "shema_local.db", null, VERSION), MeCache {
    companion object {
        const val VERSION = 1
        @Volatile private var one: LocalStore? = null
        fun of(c: Context): LocalStore = one ?: synchronized(this) { one ?: LocalStore(c.applicationContext).also { one = it } }
    }

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE IF NOT EXISTS me_periods (kind TEXT NOT NULL, start TEXT NOT NULL, json TEXT NOT NULL, " +
            "fetched INTEGER NOT NULL, PRIMARY KEY (kind, start))")
        db.execSQL("CREATE TABLE IF NOT EXISTS meetings (id TEXT PRIMARY KEY, started TEXT, json TEXT NOT NULL, fetched INTEGER NOT NULL)")
    }

    override fun onUpgrade(db: SQLiteDatabase, old: Int, new: Int) {
        // version 1 is the first. Future steps go here, one `if (old < N)` each, without dropping saved data.
        onCreate(db)
    }

    override fun putMe(kind: String, start: String, json: String, fetchedMs: Long) {
        writableDatabase.insertWithOnConflict("me_periods", null, ContentValues().apply {
            put("kind", kind); put("start", start); put("json", json); put("fetched", fetchedMs)
        }, SQLiteDatabase.CONFLICT_REPLACE)
    }

    override fun getMe(kind: String, start: String): Pair<String, Long>? =
        readableDatabase.rawQuery("SELECT json, fetched FROM me_periods WHERE kind=? AND start=?", arrayOf(kind, start)).use {
            if (it.moveToFirst()) it.getString(0) to it.getLong(1) else null
        }

    override fun savedMe(kind: String): List<String> =
        readableDatabase.rawQuery("SELECT start FROM me_periods WHERE kind=? ORDER BY start DESC LIMIT 60", arrayOf(kind)).use {
            val out = mutableListOf<String>(); while (it.moveToNext()) out += it.getString(0); out
        }

    /** the meetings list from the PC: rows it no longer sends (deleted there) go too */
    fun putMeetings(rows: org.json.JSONArray, fetchedMs: Long) {
        val db = writableDatabase
        db.beginTransaction()
        try {
            db.delete("meetings", null, null)
            for (i in 0 until rows.length()) {
                val m = rows.optJSONObject(i) ?: continue
                db.insertWithOnConflict("meetings", null, ContentValues().apply {
                    put("id", m.optString("id")); put("started", m.optString("started")); put("json", m.toString()); put("fetched", fetchedMs)
                }, SQLiteDatabase.CONFLICT_REPLACE)
            }
            db.setTransactionSuccessful()
        } finally { db.endTransaction() }
    }

    /** newest first, and when they were received (0 = never) */
    fun meetings(): Pair<List<org.json.JSONObject>, Long> =
        readableDatabase.rawQuery("SELECT json, fetched FROM meetings ORDER BY started DESC", null).use {
            val out = mutableListOf<org.json.JSONObject>(); var at = 0L
            while (it.moveToNext()) { try { out += org.json.JSONObject(it.getString(0)) } catch (e: Exception) { }; at = maxOf(at, it.getLong(1)) }
            out to at
        }

    fun forgetMeetings(ids: Collection<String>) {
        for (id in ids) writableDatabase.delete("meetings", "id=?", arrayOf(id))
    }
}
