package com.shema.app

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.ZoneOffset

/** 2026-11-01: the weekly "אני" bug (an empty current week on Sunday) and the offline cache. */
class MePeriodsTest {
    private val sunday = LocalDate.of(2026, 11, 1)

    private class MapCache : MeCache {
        val m = HashMap<String, Pair<String, Long>>()
        override fun putMe(kind: String, start: String, json: String, fetchedMs: Long) { m["$kind|$start"] = json to fetchedMs }
        override fun getMe(kind: String, start: String) = m["$kind|$start"]
        override fun savedMe(kind: String) = m.keys.filter { it.startsWith("$kind|") }.map { it.substringAfter('|') }.sortedDescending()
    }

    private fun me2(lines: Int) = """{"kind":"week","me":{"lines":$lines,"minutes":12.5,"conversations":3}}"""
    private fun period(convs: Int) = """{"schema":2,"stats":{"conversations":$convs,"my_lines":0}}"""

    @Test fun israeliWeekStartsOnSunday() {
        assertEquals(sunday, MePeriods.start("week", sunday))
        assertEquals(LocalDate.of(2026, 10, 25), MePeriods.start("week", LocalDate.of(2026, 10, 31)))   // Saturday
        assertEquals(LocalDate.of(2026, 10, 25), MePeriods.prev("week", sunday))
        assertEquals(LocalDate.of(2026, 10, 31), MePeriods.end("week", LocalDate.of(2026, 10, 25)))
        assertEquals("השבוע שעבר · ⁦25/10–31/10⁩", MePeriods.label("week", LocalDate.of(2026, 10, 25), sunday))
    }

    @Test fun sundayFallsBackToLastWeekWithData() {
        val cache = MapCache()
        val fetch = { p: String ->
            when {
                p.contains("d=2026-11-01") && p.contains("me2") -> me2(0)            // this week: nothing yet
                p.contains("d=2026-11-01") -> period(0)
                p.contains("d=2026-10-31") && p.contains("me2") -> me2(1994)          // last week, asked by its last day
                p.contains("d=2026-10-31") -> period(254)
                else -> null
            }
        }
        val now = MeRepo.load("week", sunday, sunday, cache, 1000L, fetch)
        assertFalse(MePeriods.hasData(now.json))
        val back = MeRepo.fallback("week", sunday, cache, 1000L, fetch = fetch)
        assertNotNull(back)
        assertEquals(LocalDate.of(2026, 10, 25), back!!.first)
        assertTrue(MePeriods.hasData(back.second.json))
        assertEquals(1994, back.second.json!!.getJSONObject("me2").getJSONObject("me").getInt("lines"))
    }

    @Test fun pcAwayShowsSavedPeriodWithItsTime() {
        val cache = MapCache()
        val s = LocalDate.of(2026, 10, 25)
        MeRepo.load("week", s, sunday, cache, 1_000L) { p -> if (p.contains("me2")) me2(10) else null }
        val off = MeRepo.load("week", s, sunday, cache, 9_000L) { null }               // PC not answering
        assertTrue(off.fromCache)
        assertFalse(off.pcAnswered)
        assertEquals(1_000L, off.fetchedMs)
        assertEquals(10, off.json!!.getJSONObject("me2").getJSONObject("me").getInt("lines"))
        // history: an older week stays saved when a newer one arrives
        MeRepo.load("week", sunday, sunday, cache, 2_000L) { p -> if (p.contains("me2")) me2(1) else null }
        assertEquals(listOf("2026-11-01", "2026-10-25"), cache.savedMe("week"))
    }

    @Test fun nothingSavedAndPcAway() {
        val r = MeRepo.load("day", sunday, sunday, MapCache(), 1L) { null }
        assertNull(r.json)
        assertFalse(r.fromCache)
    }

    @Test fun errorsAreNotSaved() {
        val cache = MapCache()
        val r = MeRepo.load("week", sunday, sunday, cache, 1L) { """{"error":"boom"}""" }
        assertNull(r.json)
        assertTrue(cache.m.isEmpty())
    }

    @Test fun olderAnswersStillRead() {
        // the oldest PCs: only /home/api/me for a day; a saved answer without "period" is still data
        val j = MePeriods.combine("day", sunday, null, null, """{"seconds":300,"conversations":2}""")!!
        assertTrue(MePeriods.hasData(j))
        assertTrue(j.isNull("period"))
        assertTrue(MePeriods.hasData(JSONObject("""{"me2":{"me":{"lines":3}}}""")))     // no "period", no "me" key at all
    }

    @Test fun savedNoticeText() {
        val ms = java.time.LocalDateTime.of(2026, 10, 31, 21, 9).toInstant(ZoneOffset.UTC).toEpochMilli()
        assertEquals("מוצג מידע שמור · עודכן לאחרונה: 31/10 21:09", MePeriods.savedNotice(ms, ZoneOffset.UTC))
    }
}
