"""2026-11-01: the phone's "אני" screen (me_period.report: the Israeli week, the previous period, empty weeks) and
meeting names (a title only when there is none, never over the user's; one line for every summarised meeting)."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

_TMP = tempfile.mkdtemp(prefix="shema_period_")
os.environ["SHEMA_DATA"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import home_listener as H      # noqa: E402
import me_period as P          # noqa: E402


class PeriodTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        H.config()
        H.migrate()

    def setUp(self):
        with H.db() as c:
            for t in ("utterances", "conversations", "tasks", "meetings", "daily", "marks", "home_people"):
                c.execute(f"DELETE FROM {t}")
            c.execute("INSERT INTO home_people (id, name, created) VALUES ('p1', 'תמר פורת', 'x'), ('p2', 'אדם פורת', 'x')")
            # last week (Sunday 25/10 .. Saturday 31/10): two conversations; this week (from Sunday 1/11): none yet
            for cid, start, topic in ((1, "2026-10-26T09:00:00", "קניית מחשב"), (2, "2026-10-31T20:00:00", "ארוחת שבת"),
                                      (3, "2026-10-20T10:00:00", "שבוע קודם")):
                c.execute("INSERT INTO conversations (id, start, end, seconds, topic, summary, status, mood_valence, mood_arousal) "
                          "VALUES (?,?,?,600,?,'סיכום','done',0.5,0.3)", (cid, start, start, topic))
            for cid, t, sp, n, text in ((1, "2026-10-26T09:00:05", "owner", "אגמון", "תמר, נקנה את המחשב מחר"),
                                        (1, "2026-10-26T09:00:20", "p1", "תמר פורת", "טוב, ואדם יבוא איתנו"),
                                        (2, "2026-10-31T20:00:05", "p1", "תמר פורת", "שבת שלום")):
                c.execute("INSERT INTO utterances (conv_id, t0, t1, seconds, speaker, name, text) VALUES (?,?,?,60,?,?,?)",
                          (cid, t, t, sp, n, text))
            c.execute("INSERT INTO tasks (conv_id, who, what, state, created, kind) VALUES (1,'אגמון','לקנות מחשב','open','x','promise')")
            c.execute("INSERT INTO tasks (conv_id, who, what, state, created, kind) VALUES (1,'אגמון','קונים מחשב','open','x','decision')")
            c.execute("INSERT INTO daily (day, summary, highlights, detail) VALUES ('2026-10-26','s','[]',?)",
                      (json.dumps({"topics": [{"text": "מחשב חדש", "conv_id": 1}],
                                   "highlights": [{"text": "החלטנו על מחשב", "conv_id": 1}]}, ensure_ascii=False),))

    def report(self, kind, d):
        with H.db() as c:
            return P.report(c, H.owner_id(), kind, d)

    def test_israeli_week(self):
        s, e = P.period_of("week", "2026-11-01")       # a Sunday starts its own week
        self.assertEqual((s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d")), ("2026-11-01", "2026-11-08"))
        s, _ = P.period_of("week", "2026-10-31")       # a Saturday ends the week that began on Sunday 25/10
        self.assertEqual(s.strftime("%Y-%m-%d"), "2026-10-25")

    def test_week_with_data(self):
        r = self.report("week", "2026-10-28")
        self.assertEqual(r["schema"], P.SCHEMA)
        self.assertEqual(r["label"], "25/10–31/10")
        self.assertEqual(r["stats"]["conversations"], 2)
        self.assertEqual(r["stats"]["rec_minutes"], 20.0)
        self.assertEqual(r["stats"]["decisions"], 1)
        self.assertEqual(len(r["days"]), 7)
        self.assertEqual([t["text"] for t in r["topics"]], ["מחשב חדש"])
        self.assertEqual(r["items"]["decisions"][0]["text"], "קונים מחשב")
        self.assertEqual(r["items"]["open"][0]["conv"], 1)
        self.assertEqual(r["moments"][0]["conv"], 1)
        self.assertEqual(r["people"][0]["name"], "תמר פורת")
        # "תמר" said as a word counts; "אדם" is an everyday word, so only "אדם פורת" in full would count
        self.assertEqual({p["name"]: p["mentions"] for p in r["mentioned"]}, {"תמר פורת": 1})
        self.assertEqual(r["prev"]["label"], "18/10–24/10")
        self.assertEqual(r["prev"]["conversations"], 1)

    def test_new_week_is_empty_not_an_error(self):
        r = self.report("week", "2026-11-01")          # the bug's case: Sunday, nothing heard yet this week
        self.assertEqual(r["stats"]["conversations"], 0)
        self.assertEqual(r["topics"], [])
        self.assertEqual(r["prev"]["label"], "25/10–31/10")
        self.assertEqual(r["prev"]["conversations"], 2)  # the phone can offer last week

    def test_day(self):
        r = self.report("day", "2026-10-26")
        self.assertEqual((r["label"], r["days"], r["stats"]["conversations"]), ("26/10", [], 1))


class MeetingNameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        H.config()
        H.migrate()

    def setUp(self):
        with H.db() as c:
            for t in ("conversations", "meetings"):
                c.execute(f"DELETE FROM {t}")
            summ = "הצוות דן בתקציב הרבעון ובגיוס שני מפתחים. הוחלט לדחות את ההשקה."
            for i, (mid, title, status) in enumerate((("m1", None, "done"), ("m2", "פגישה", "done"),
                                                       ("m3", "סטטוס שבועי עם דנה", "done"), ("m4", None, "recording")), 1):
                c.execute("INSERT INTO conversations (id, start, seconds, topic, summary, status, ctx) VALUES (?,?,600,?,?,'done',?)",
                          (i, f"2026-10-2{i}T10:00:00", "תקציב וגיוס", summ, "meet:" + mid))
                c.execute("INSERT INTO meetings (id, title, started, ended, conv_id, status) VALUES (?,?,?,?,?,?)",
                          (mid, title, f"2026-10-2{i}T10:00:00", f"2026-10-2{i}T10:40:00", i, status))

    def rows(self):
        with H.db() as c:
            return {r["id"]: dict(r) for r in c.execute("SELECT id, title, title_auto, oneline FROM meetings")}

    def test_fill_names_untitled_keeps_user_title(self):
        llm = lambda s, u: {"title": "תקציב רבעון וגיוס מפתחים", "line": "דיון בתקציב הרבעון ובגיוס, וההשקה נדחתה."}
        self.assertEqual(P.fill(H.db, llm, limit=10, log=lambda *_: None), 3)
        r = self.rows()
        self.assertEqual((r["m1"]["title"], r["m1"]["title_auto"]), ("תקציב רבעון וגיוס מפתחים", 1))
        self.assertEqual(r["m2"]["title"], "תקציב רבעון וגיוס מפתחים")        # the placeholder is not a title
        self.assertEqual((r["m3"]["title"], r["m3"]["title_auto"]), ("סטטוס שבועי עם דנה", None))
        self.assertTrue(r["m3"]["oneline"])                                  # ...but it still gets its line
        self.assertIsNone(r["m4"]["oneline"])                                # not summarised yet
        self.assertEqual(P.fill(H.db, llm, limit=10, log=lambda *_: None), 0)  # the backfill runs once

    def test_without_model_uses_summary(self):
        P.fill(H.db, lambda s, u: {"error": "no model"}, limit=10, log=lambda *_: None)
        r = self.rows()
        # the topic "תקציב וגיוס" is under 3 words: the summary's first words make the title
        self.assertEqual(r["m1"]["title"], "הצוות דן בתקציב הרבעון ובגיוס שני מפתחים")
        self.assertEqual(r["m1"]["oneline"], "הצוות דן בתקציב הרבעון ובגיוס שני מפתחים.")

    def test_fit_title_and_line(self):
        self.assertEqual(P.fit_title("פגישה על תכנון השקה של המוצר החדש בחודש הבא ממש"), "תכנון השקה של המוצר החדש בחודש הבא")
        self.assertEqual(P.fit_title(None, None, "דיברנו על הגינה ועל השכנים. ועוד."), "דיברנו על הגינה ועל השכנים")
        self.assertTrue(P.fit_line("א " * 80).endswith("…"))
        self.assertTrue(P.is_placeholder("📋 פגישה") and not P.is_placeholder("פגישת צוות"))

    def test_meetings_list_shows_line_not_placeholder(self):
        P.fill(H.db, None, limit=10, log=lambda *_: None)
        with H.db() as c:
            ms = {m["id"]: m for m in H.meetings_list(c)}
        self.assertNotEqual(ms["m2"]["title"], "פגישה")
        self.assertEqual(ms["m4"]["title"], "תקציב וגיוס")                  # no title yet: its topic is shown
        self.assertEqual(ms["m1"]["seconds"], 2400)
        self.assertTrue(ms["m1"]["oneline"])

    def test_untitled_meeting_marker_is_not_a_title(self):
        with H.db() as c:
            H.meeting_seen(c, "m9", "phone", H.datetime(2026, 10, 30, 9), cal="📋 פגישה")
            self.assertIsNone(c.execute("SELECT title FROM meetings WHERE id='m9'").fetchone()[0])
            H.meeting_seen(c, "m8", "phone", H.datetime(2026, 10, 30, 9), cal="📋 פגישה: תקציב")
            self.assertEqual(c.execute("SELECT title FROM meetings WHERE id='m8'").fetchone()[0], "תקציב")


if __name__ == "__main__":
    unittest.main()
