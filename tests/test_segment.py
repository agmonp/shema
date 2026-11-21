"""2026-11-21: "✂ בחר קטע": the audio and the summary of only a part of a conversation / meeting (seg_bounds)."""
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

_TMP = tempfile.mkdtemp(prefix="shema_segment_")
os.environ["SHEMA_DATA"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import home_listener as H                          # noqa: E402
from test_meeting_audio import tone, duration      # noqa: E402

LONG = "משפט ארוך מספיק כדי שיהיה מה לסכם בקטע הזה של השיחה"


def plan_seconds(P):
    return round(sum(p["dur"] for p in P), 2)


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        H.config()
        H.migrate()

    def setUp(self):
        d = Path(_TMP) / "rec"
        d.mkdir(exist_ok=True)
        tone(d / "c.wav", 60, [(5, 14), (20, 25), (40, 44)])
        tone(d / "d.wav", 60, [(2, 8)])
        tone(d / "a.wav", 60, [(5, 14), (40, 44)])
        tone(d / "b.wav", 60, [(2, 8)])
        with H.db() as c:
            for t in ("utterances", "chunks", "meetings", "conversations"):
                c.execute(f"DELETE FROM {t}")
            c.execute("INSERT INTO conversations (id, start, end, seconds, topic, summary, status) VALUES "
                      "(7, '2026-10-20T09:30:00', '2026-10-20T09:36:00', 360, 'ארוחת בוקר', 'הסיכום של כל השיחה', 'done')")
            c.execute("INSERT INTO conversations (id, start, end, seconds, topic, status) VALUES "
                      "(8, '2026-10-20T11:00:00', '2026-10-20T11:01:00', 60, 'אחרת', 'done')")
            c.execute("INSERT INTO conversations (id, start, end, seconds, topic, status, ctx) VALUES "
                      "(9, '2026-10-20T14:00:00', '2026-10-20T14:06:00', 360, 'פגישה', 'done', 'meet:m1')")
            c.execute("INSERT INTO meetings (id, device, title, started, ended, status) VALUES "
                      "('m1', 'ph', 'תכנון רבעון', '2026-10-20T14:00:00', '2026-10-20T14:06:00', 'done')")
            for cid, st, f, ctx in ((11, "2026-10-20T09:30:00", d / "c.wav", None), (12, "2026-10-20T09:35:00", d / "d.wav", None),
                                    (21, "2026-10-20T14:00:00", d / "a.wav", "meet:m1"),
                                    (22, "2026-10-20T14:05:00", d / "b.wav", "meet:m1")):
                c.execute("INSERT INTO chunks (id, device, start, seconds, file, status, ctx) VALUES (?,?,?,60,?,'done',?)",
                          (cid, "ph", st, str(f), ctx))
            # conversation 7: 101 תמר, 102 דנה, 103 TV (left out), 105 דנה in the next recording; 104 is conversation 8's
            for uid, ch, conv, t0, t1, n, media in ((101, 11, 7, "09:30:05", "09:30:10", "תמר", None),
                                                    (102, 11, 7, "09:30:10.500", "09:30:14", "דנה", None),
                                                    (103, 11, 7, "09:30:20", "09:30:25", None, "tv"),
                                                    (104, 11, 8, "09:30:40", "09:30:44", "יוסי", None),
                                                    (105, 12, 7, "09:35:02", "09:35:08", "דנה", None),
                                                    (201, 21, 9, "14:00:05", "14:00:10", "תמר", None),
                                                    (202, 21, 9, "14:00:10.500", "14:00:14", "דנה", None),
                                                    (203, 21, 9, "14:00:40", "14:00:44", "תמר", None),
                                                    (204, 22, 9, "14:05:02", "14:05:08", "דנה", None)):
                c.execute("INSERT INTO utterances (id, chunk_id, conv_id, t0, t1, seconds, name, text, media) "
                          "VALUES (?,?,?,?,?,?,?,?,?)",
                          (uid, ch, conv, "2026-10-20T" + t0, "2026-10-20T" + t1, 4.0, n, f"{n} {uid}: {LONG}", media))


class SegmentAudioTests(Fixture):
    def plan(self, **q):
        with H.db() as c:
            return H.conv_audio_plan(c, 7, H.seg_bounds({k: [str(v)] for k, v in q.items()}))

    def test_no_bounds_is_unchanged(self):
        self.assertIsNone(H.seg_bounds({}))
        self.assertIsNone(H.seg_bounds({"ds": ["5"]}))         # an edge shift alone is not a segment
        with H.db() as c:
            whole = H.conv_audio_plan(c, 7)
            self.assertEqual(whole, H.conv_audio_plan(c, 7, None))
        self.assertEqual(plan_seconds(whole[0]), 16.0)          # 9.5 + 6.5, as in test_meeting_audio
        f, info = H.conv_audio(7)
        self.assertEqual(info["name"], "conversation-2026-10-20-0930.m4a")
        self.assertAlmostEqual(duration(f), 16.0, delta=0.3)

    def test_cut_between_two_lines(self):
        P, C, miss = self.plan(**{"from": 101, "to": 102})
        self.assertEqual(plan_seconds(P), 9.0)                  # 09:30:05 - 09:30:14, no padding outside the edges
        self.assertEqual([x["who"] for x in C], ["תמר", "דנה"])
        f, info = H.conv_audio(7, (101, 102, 0.0, 0.0))
        self.assertEqual(info["name"], "conversation-7-09-30-09-30.m4a")
        self.assertAlmostEqual(duration(f), 9.0, delta=0.3)
        self.assertNotEqual(f, H.conv_audio(7)[0])              # its own file, the whole one is not touched

    def test_reversed_lines_are_the_same_part(self):
        self.assertEqual(self.plan(**{"from": 102, "to": 101}), self.plan(**{"from": 101, "to": 102}))

    def test_one_line_and_edge_shifts(self):
        self.assertEqual(plan_seconds(self.plan(**{"from": 102, "to": 102})[0]), 3.5)
        # 5 s earlier reaches into תמר's line: 09:30:05.5 - 09:30:14
        P, C, _ = self.plan(**{"from": 102, "to": 102, "ds": -5})
        self.assertEqual(plan_seconds(P), 8.5)
        self.assertEqual([x["who"] for x in C], ["תמר", "דנה"])
        # 5 s later from the last line: only the line's own padding is speech
        self.assertEqual(plan_seconds(self.plan(**{"from": 105, "to": 105, "de": 5})[0]), 6.25)
        # a shift into the line itself cuts it
        self.assertEqual(plan_seconds(self.plan(**{"from": 101, "to": 101, "ds": 2, "de": -1})[0]), 2.0)

    def test_across_two_recordings(self):
        P, C, _ = self.plan(**{"from": 101, "to": 105})
        self.assertEqual(plan_seconds(P), 9.25 + 6.25)          # the TV line and conversation 8's line stay out
        self.assertEqual(len(P), 2)

    def test_bad_bounds(self):
        for q in ({"from": 104, "to": 101},                     # another conversation's line
                  {"from": 103, "to": 101},                     # a TV line
                  {"from": 999, "to": 101}):
            with self.assertRaises(H.SegError):
                self.plan(**q)
        for q in ({"from": "x"}, {"from": 101, "ds": "abc"}, {"from": 101, "ds": 1000}, {"from": 101, "de": "nan"}):
            with self.assertRaises(H.SegError):
                H.seg_bounds({k: [str(v)] for k, v in q.items()})
        with self.assertRaises(H.SegError):                     # the end moved before the start
            self.plan(**{"from": 102, "to": 102, "de": -10})

    def test_meeting_part(self):
        with H.db() as c:
            P, C, _ = H.meeting_audio_plan(c, "m1", (202, 204, 0.0, 0.0))
            self.assertEqual(plan_seconds(H.meeting_audio_plan(c, "m1")[0]), 20.5)
        self.assertEqual(plan_seconds(P), 3.75 + 4.5 + 6.25)
        self.assertEqual([x["who"] for x in C], ["דנה", "תמר", "דנה"])
        f, info = H.meeting_audio("m1", (202, 204, 0.0, 0.0))
        self.assertEqual(info["name"], "meeting-m1-14-00-14-05.m4a")
        self.assertAlmostEqual(duration(f), 14.5, delta=0.3)
        with self.assertRaises(H.SegError):
            H.meeting_audio("m1", (101, 204, 0.0, 0.0))         # a line of another conversation

    def test_http(self):
        cfg = H.config(); cfg["token"] = "tk"; H._write_config(cfg)

        class Remote(H.Handler):
            def _local(self):
                return False
        from http.server import ThreadingHTTPServer
        srv = ThreadingHTTPServer(("127.0.0.1", 0), Remote)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}/home/audio/"
        get = lambda p: urllib.request.urlopen(urllib.request.Request(base + p, headers={"X-Home-Token": "tk"}))  # noqa: E731
        try:
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(base + "conv/7.m4a?from=101&to=102")
            self.assertIn(e.exception.code, (403, 404))      # refused without the access code, like the whole recording
            with get("conv/7.m4a?from=101&to=102") as r:
                self.assertIn("conversation-7-09-30-09-30.m4a", r.headers["Content-Disposition"])
                self.assertEqual(r.headers["X-Speech-Seconds"], "9.0")
            with get("conv/7.m4a") as r:
                self.assertIn("conversation-2026-10-20-0930.m4a", r.headers["Content-Disposition"])
                self.assertEqual(r.headers["X-Speech-Seconds"], "16.0")
            with get("meeting/m1.m4a?from=204&to=202&de=0") as r:
                self.assertIn("meeting-m1-14-00-14-05.m4a", r.headers["Content-Disposition"])
            for bad in ("conv/7.m4a?from=104&to=101", "conv/7.m4a?from=101&ds=x", "conv/7.m4a?from=102&de=-10"):
                with self.assertRaises(urllib.error.HTTPError) as e:
                    get(bad)
                self.assertEqual(e.exception.code, 400, bad)
        finally:
            srv.shutdown()


class SegmentSummaryTests(Fixture):
    def setUp(self):
        super().setUp()
        self.sent = []
        self._orig = H._ollama_json

        def fake(system, user, **kw):
            self.sent.append((system, user))
            return {"topic": "נושא", "summary": "סיכום הקטע", "per_person": {"דנה": "אמרה", "מישהו": "בדוי"},
                    "moments": [], "signals": [], "model": "fake"}
        H._ollama_json = fake

    def tearDown(self):
        H._ollama_json = self._orig

    def test_only_lines_in_range_and_not_saved(self):
        r = H.api("/home/api/segment_summary", {"kind": ["conv"], "id": ["7"], "from": ["102"], "to": ["105"]})
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["summary"], "סיכום הקטע")
        self.assertEqual(r["lines"], 2)                         # 102 and 105; the TV line is not a line
        self.assertEqual(r["per_person"], {"דנה": "אמרה"})      # no invented people, as in the whole summary
        system, user = self.sent[0]
        self.assertIs(system, H.SUMMARY_TASK)                   # the same prompt as the whole conversation
        self.assertIn("דנה: דנה 102", user)                     # names as in the transcript
        self.assertIn("דנה 105", user)
        self.assertNotIn("תמר 101", user)
        self.assertNotIn("יוסי", user)
        with H.db() as c:
            row = c.execute("SELECT summary, topic FROM conversations WHERE id=7").fetchone()
        self.assertEqual((row["summary"], row["topic"]), ("הסיכום של כל השיחה", "ארוחת בוקר"))

    def test_shift_brings_in_a_line(self):
        r = H.api("/home/api/segment_summary", {"id": ["7"], "from": ["102"], "to": ["102"], "ds": ["-5"]})
        self.assertEqual(r["lines"], 2)
        self.assertIn("תמר 101", self.sent[0][1])

    def test_meeting_uses_the_meeting_prompt(self):
        r = H.api("/home/api/segment_summary", {"kind": ["meeting"], "id": ["m1"], "from": ["203"], "to": ["204"]})
        self.assertTrue(r["ok"], r)
        self.assertIs(self.sent[0][0], H.MEETING_TASK)
        self.assertNotIn("דנה 202", self.sent[0][1])
        self.assertIn("תמר 203", self.sent[0][1])
        self.assertIn("tasks", r)

    def test_bad_requests(self):
        self.assertFalse(H.api("/home/api/segment_summary", {"id": ["7"]})["ok"])
        self.assertFalse(H.api("/home/api/segment_summary", {"id": ["7"], "from": ["104"], "to": ["101"]})["ok"])
        self.assertFalse(H.api("/home/api/segment_summary", {"id": ["999"], "from": ["101"]})["ok"])
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main()
