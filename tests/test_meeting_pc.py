"""2026-10-18 UX phase 5: meetings recorded on the PC ("הקלט פגישה"), the call's two sides, and meeting items that keep
only what was really said (the quote, the owner, the due time)."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
import wave

import numpy as np

_TMP = tempfile.mkdtemp(prefix="shema_meetpc_")
os.environ["SHEMA_DATA"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import home_listener as H      # noqa: E402
import pc_record as P          # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_pc_record import FakeSource   # noqa: E402


def stereo_wav(path, parts, sr=16000):
    """parts = [(seconds, mic_amp, sys_amp)] -> a two-channel file (left = microphone 220 Hz, right = system 440 Hz)."""
    cols = []
    for sec, ma, sa in parts:
        t = np.arange(int(sec * sr)) / sr
        cols.append(np.stack([ma * np.sin(2 * np.pi * 220 * t), sa * np.sin(2 * np.pi * 440 * t)], 1))
    a = (np.concatenate(cols) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(a.tobytes())
    return path


class SidesTests(unittest.TestCase):
    def test_which_side_said_it(self):
        p = stereo_wav(Path(_TMP) / "sides.wav", [
            (1, 0.3, 0.0),        # 0-1 s: only the microphone -> the user's side
            (1, 0.0, 0.3),        # 1-2 s: only the system audio -> the other side
            (1, 0.02, 0.3),       # 2-3 s: the other side through loudspeakers: the microphone hears a weak echo
            (1, 0.3, 0.12),       # 3-4 s: both talk, the microphone clearly louder... but the other side is there too
            (1, 0.0, 0.0)])       # 4-5 s: silence
        got = P.channel_sides(p, [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5)])
        self.assertEqual(got[:3], ["mic", "system", "system"])
        self.assertIsNone(got[3])                                  # 8 dB apart: not decided
        self.assertIsNone(got[4])

    def test_mono_or_missing_file_is_undecided(self):
        p = Path(_TMP) / "mono.wav"
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\0\0" * 16000)
        self.assertEqual(P.channel_sides(p, [(0, 1)]), [None])
        self.assertEqual(P.channel_sides(Path(_TMP) / "nope.wav", [(0, 1), (1, 2)]), [None, None])


class RecorderMeetTests(unittest.TestCase):
    def setUp(self):
        FakeSource.opened, FakeSource.fail_open, FakeSource.fail_after = [], set(), {}
        self.dir = Path(tempfile.mkdtemp(prefix="rec_", dir=_TMP))
        self.got = []
        self.r = P.Recorder(self.store, self.dir, source_factory=FakeSource, chunk_s=1, log=lambda *_: None)

    def store(self, raw, st, meet=None):
        self.got.append((st, meet))
        return len(self.got)

    def test_meeting_id_on_every_chunk_and_after_a_crash(self):
        self.assertEqual(self.r.start("both", meet="pc-1")["meet"], "pc-1")
        end = time.time() + 5
        while time.time() < end and len(self.got) < 2:
            time.sleep(0.01)
        self.r.stop()
        self.assertTrue(self.got and all(m == "pc-1" for _, m in self.got))
        # a crash in the middle of a meeting: the partial file still knows its meeting
        p = self.dir / "partial_20261018T101500_000000.pcm"
        p.write_bytes(np.zeros(16000 * 2, "<i2").tobytes())
        p.with_suffix(".json").write_text(json.dumps({"start": "2026-10-18T10:15:00", "channels": 2, "meet": "pc-2"}),
                                          encoding="utf-8")
        self.got.clear()
        self.r.recover()
        self.assertEqual(self.got[0][1], "pc-2")


class PcMeetingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        H.config()
        H.migrate()
        H.PC_MEET_CHUNK_S = 1

    def setUp(self):
        FakeSource.opened, FakeSource.fail_open, FakeSource.fail_after = [], set(), {}
        H.PCREC = None
        r = H.pcrec()
        r.factory, r.chunk_s, r.normal_chunk_s = FakeSource, 2, 2
        r.log = lambda *_: None
        with H.db() as c:
            for t in ("chunks", "meetings", "marks"):
                c.execute(f"DELETE FROM {t}")

    def wait(self, cond, timeout=5):
        end = time.time() + timeout
        while time.time() < end and not cond():
            time.sleep(0.02)
        self.assertTrue(cond())

    def test_consent_needed_and_nothing_created(self):
        out = H.pc_rec_action({"action": "start", "source": "both", "meeting": True})
        self.assertIn("יודעים", out["error"])
        with H.db() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM meetings").fetchone()[0], 0)

    def test_failed_start_leaves_no_meeting(self):
        FakeSource.fail_open = {"mic"}
        out = H.pc_rec_action({"action": "start", "source": "both", "meeting": True, "consent": True})
        self.assertIn("מיקרופון", out["error"])
        with H.db() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM meetings").fetchone()[0], 0)
        self.assertEqual(H.PCREC.chunk_s, 2)

    def test_meeting_start_mark_stop(self):
        out = H.pc_rec_action({"action": "start", "source": "both", "meeting": True, "consent": True, "title": " סטטוס שבועי "})
        mid = out["meet"]
        self.assertTrue(mid.startswith("pc-"))
        self.assertEqual(H.PCREC.chunk_s, 1)                       # shorter chunks: the transcript shows up sooner
        with H.db() as c:
            m = c.execute("SELECT * FROM meetings WHERE id=?", (mid,)).fetchone()
        self.assertEqual((m["device"], m["status"], m["title"], m["source"]), ("pc", "recording", "סטטוס שבועי", "both"))
        self.wait(lambda: H.PCREC.chunks)
        mk = H.pc_rec_action({"action": "mark", "note": "המחיר"})
        self.assertTrue(mk["ok"])
        self.assertEqual(mk["meet"], mid)
        with H.db() as c:
            v = H.meeting_view(c, mid)
        self.assertEqual(v["live"]["state"], "recording")           # the live screen reads the recorder
        self.assertEqual([x["note"] for x in v["marks"]], ["המחיר"])
        out = H.pc_rec_action({"action": "stop"})
        self.assertEqual((out["state"], out["meet_ended"]), ("idle", mid))
        self.assertEqual(H.PCREC.chunk_s, 2)
        self.assertIsNone(H.PCREC.meet)
        with H.db() as c:
            self.assertEqual(c.execute("SELECT status FROM meetings WHERE id=?", (mid,)).fetchone()[0], "ended")
            rows = c.execute("SELECT ctx, meet, device FROM chunks").fetchall()
            self.assertIsNone(H.meeting_view(c, mid)["live"])
        self.assertTrue(rows)
        self.assertTrue(all((r["ctx"], r["meet"], r["device"]) == ("meet:" + mid, mid, "pc") for r in rows))
        self.assertFalse(H.pc_rec_action({"action": "mark"})["ok"])   # no recording: nothing to mark

    def test_recording_that_stops_by_itself_ends_the_meeting(self):
        FakeSource.fail_after = {"system": 8}
        mid = H.pc_rec_action({"action": "start", "source": "system", "meeting": True, "consent": True})["meet"]
        self.wait(lambda: H.PCREC.state == "idle")
        self.assertEqual(H.pc_rec_status()["meet"], None)
        with H.db() as c:
            self.assertEqual(c.execute("SELECT status FROM meetings WHERE id=?", (mid,)).fetchone()[0], "ended")

    def test_orphaned_meeting_ends_at_server_start(self):
        with H.db() as c:
            c.execute("INSERT INTO meetings (id, device, started, status, updated) VALUES ('pc-x','pc','2026-10-18T09:00:00',"
                      "'recording','2026-10-18T09:30:00')")
            c.execute("INSERT INTO meetings (id, device, started, status, updated) VALUES ('ph-1','phone','2026-10-18T09:00:00',"
                      "'recording','2026-10-18T09:30:00')")
        self.assertEqual(H.pc_meetings_orphaned(), ["pc-x"])
        with H.db() as c:
            st = dict(c.execute("SELECT id, status FROM meetings").fetchall())
        self.assertEqual(st, {"pc-x": "ended", "ph-1": "recording"})   # a phone's meeting is the phone's to end


def utt(text, t0, t1, speaker=None, name=None):
    return {"text": text, "t0": t0, "t1": t1, "speaker": speaker, "name": name, "how": "voice" if speaker else None,
            "emb": None, "prosody": {}, "emotion": {}, "dims": {}}


class SideNamingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        H.config()
        H.migrate()

    def test_mic_side_is_probably_the_user_and_the_other_side_never_is(self):
        with H.db() as c:
            for t in ("chunks", "utterances", "conversations"):
                c.execute(f"DELETE FROM {t}")
        f = stereo_wav(Path(_TMP) / "call.wav", [(2, 0.3, 0.0), (2, 0.0, 0.3), (2, 0.0, 0.3)])
        with H.db() as c:
            cid = c.execute("INSERT INTO chunks (device, start, file, status, kind, ctx, away, meet) VALUES "
                            "('pc','2026-10-18T10:00:00',?,'new','speech','meet:pc-s',0,'pc-s')", (str(f),)).lastrowid
            row = c.execute("SELECT * FROM chunks WHERE id=?", (cid,)).fetchone()
        res = {"utterances": [utt("אני אשלח את המצגת אחר כך", 0.1, 1.9),
                              utt("מצוין תודה רבה לך", 2.1, 3.9, H.owner_id(), "בעלים"),   # a voice match on the far side
                              utt("ואני אבדוק את התקציב", 4.1, 5.9, "p_dana", "דנה")], "sounds": []}
        H.save_analysis(row, H.datetime.fromisoformat(row["start"]), res)
        with H.db() as c:
            got = [tuple(r) for r in c.execute("SELECT side, speaker, how FROM utterances ORDER BY t0")]
        self.assertEqual(got, [("mic", H.owner_id(), "mic"), ("system", None, None), ("system", "p_dana", "voice")])


LINES = [("דנה", "voice", "טוב אז בואו נתחיל עם הלוח זמנים של הפרויקט"),
         ("יוסי", "voice", "החלטנו שהגרסה הראשונה יוצאת בלי המודול של התשלומים"),
         ("יוסי", "voice", "דנה תשלחי בבקשה את המצגת ללקוח עד יום חמישי"),
         ("דנה", "conv", "אני אבדוק את התקציב מול הכספים ואחזור אליכם"),
         ("?", None, "צריך מישהו שיעדכן את האתר בסוף החודש הזה"),
         ("יוסי", "voice", "אוקיי מעולה אז נתראה בשבוע הבא באותה שעה")]


class FakeModel:
    def __init__(self, *answers):
        self.answers = list(answers)

    def __call__(self, system, user, num_ctx=8192, models=None):
        a = self.answers.pop(0)
        return {"error": "down"} if a is Exception else dict(a, model="fake")


class MeetingItemsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        H.config()
        H.migrate()

    def setUp(self):
        self._orig = H._ollama_json
        with H.db() as c:
            for t in ("utterances", "conversations", "tasks", "meetings", "chunks", "marks"):
                c.execute(f"DELETE FROM {t}")
            c.execute("INSERT INTO conversations (id, start, end, seconds, status, ctx, topic, summary) VALUES (7, "
                      "'2026-10-18T10:00:00', '2026-10-18T10:20:00', 1200, 'done', 'meet:pc-m', 'שבועי', 'דיברו על הגרסה')")
            c.execute("INSERT INTO meetings (id, device, title, started, ended, status, conv_id, updated) VALUES "
                      "('pc-m','pc','סטטוס','2026-10-18T10:00:00','2026-10-18T10:20:00','done',7,'2026-10-18T10:21:00')")
            for i, (n, how, text) in enumerate(LINES):
                c.execute("INSERT INTO utterances (id, conv_id, t0, t1, seconds, name, how, text, side) VALUES (?,7,?,?,3,?,?,?,?)",
                          (100 + i, f"2026-10-18T10:0{i}:00", f"2026-10-18T10:0{i}:03", None if n == "?" else n, how, text,
                           "system" if n == "יוסי" else "mic"))
        with H.db() as c:
            self.U = [dict(r) for r in c.execute("SELECT * FROM utterances ORDER BY t0")]

    def tearDown(self):
        H._ollama_json = self._orig

    def L(self):
        return [{"id": u["id"], "name": u["name"], "how": u["how"], "text": u["text"]} for u in self.U]

    def test_owner_only_when_said(self):
        L = self.L()
        self.assertEqual(H.meeting_owner(None, "promise", L, 3), "דנה")          # "אני אבדוק": the speaker's own promise
        self.assertEqual(H.meeting_owner("אני", "promise", L, 3), "דנה")
        self.assertEqual(H.meeting_owner("דנה", "request", L, 2), "דנה")          # named in the line: "דנה תשלחי"
        self.assertIsNone(H.meeting_owner("יוסי", "request", L, 2))              # the requester is not the one who does it
        self.assertIsNone(H.meeting_owner("רוני", "agreed", L, 4))               # a name never said
        self.assertIsNone(H.meeting_owner(None, "agreed", L, 4))
        self.assertIsNone(H.meeting_owner("יוסי", "decision", L, 1))

    def test_summary_items_are_checked_and_stored_with_their_line(self):
        H._ollama_json = FakeModel({
            "topic": "סטטוס", "purpose": "לעבור על לוח הזמנים", "summary": "עברו על הגרסה.", "topics": ["לוח זמנים", 3],
            "conclusions": ["הגרסה מצטמצמת"], "open_questions": ["מי מעדכן את האתר?"], "next_steps": ["פגישה בשבוע הבא"],
            "items": [
                {"type": "decision", "line": 2, "quote": "החלטנו שהגרסה הראשונה יוצאת בלי המודול", "what": "גרסה 1 בלי תשלומים",
                 "owner": "יוסי"},
                {"type": "request", "line": 3, "quote": "דנה תשלחי בבקשה את המצגת ללקוח", "what": "לשלוח מצגת ללקוח",
                 "owner": "דנה", "when": "עד יום חמישי"},
                {"type": "promise", "line": 4, "quote": "אני אבדוק את התקציב מול הכספים", "what": "לבדוק תקציב",
                 "owner": None, "when": "מחר"},                                           # "מחר" was never said
                {"type": "agreed", "line": 5, "quote": "צריך מישהו שיעדכן את האתר בסוף", "what": "לעדכן את האתר",
                 "owner": "רוני"},
                {"type": "promise", "line": 6, "quote": "אני אכין את כל החוזים עד ראשון בבוקר", "what": "חוזים"},  # never said
            ],
            "per_person": {"דנה": "שאלה על תקציב", "מישהו": "x"}})
        with H.db() as c:
            U, S, dyn = H.conv_stats(c, 7)
        summ = H.summarise_meeting(U, dyn)
        self.assertEqual(summ["topics"], ["לוח זמנים"])
        self.assertEqual(len(summ["items"]), 4)                                   # the invented quote is gone
        self.assertEqual(summ["decisions"], ["גרסה 1 בלי תשלומים"])
        H.save_meeting("pc-m", 7, summ)
        with H.db() as c:
            v = H.meeting_view(c, "pc-m")
        self.assertEqual(v["purpose"], "לעבור על לוח הזמנים")
        self.assertEqual(v["open_questions"], ["מי מעדכן את האתר?"])
        d = v["decision_items"][0]
        self.assertEqual((d["utt_id"], d["owner"], d["said_by"], d["t0"]), (101, None, "יוסי", "2026-10-18T10:01:00"))
        T = {t["what"]: t for t in v["tasks"]}
        self.assertEqual(set(T), {"לשלוח מצגת ללקוח", "לבדוק תקציב", "לעדכן את האתר"})
        self.assertEqual((T["לשלוח מצגת ללקוח"]["who"], T["לשלוח מצגת ללקוח"]["said_by"], T["לשלוח מצגת ללקוח"]["due"]),
                         ("דנה", "יוסי", "עד יום חמישי"))
        self.assertEqual((T["לבדוק תקציב"]["who"], T["לבדוק תקציב"]["due"], T["לבדוק תקציב"]["who_how"]), ("דנה", None, "conv"))
        self.assertEqual((T["לעדכן את האתר"]["who"], T["לעדכן את האתר"]["owner"]), ("?", None))  # "לא נקבע"
        self.assertEqual([x["side"] for x in v["lines"]][:2], ["mic", "system"])
        self.assertIn("דנה: לשלוח מצגת ללקוח (עד יום חמישי)", v["share_text"])
        self.assertIn("*שאלות פתוחות*", v["share_text"])
        # the user marks one done and dismisses another; summarising again keeps both and does not bring them back
        with H.db() as c:
            c.execute("UPDATE tasks SET state='done' WHERE id=?", (T["לבדוק תקציב"]["id"],))
            c.execute("UPDATE tasks SET state='dismissed' WHERE id=?", (T["לעדכן את האתר"]["id"],))
        H.save_meeting("pc-m", 7, summ)
        with H.db() as c:
            v = H.meeting_view(c, "pc-m")
            lst = H.meetings_list(c)
        self.assertEqual(sorted((t["what"], t["state"]) for t in v["tasks"]),
                         [("לבדוק תקציב", "done"), ("לשלוח מצגת ללקוח", "open")])
        self.assertIn("✓ דנה: לבדוק תקציב", v["share_text"])
        self.assertEqual(lst[0]["open_tasks"], 1)

    def test_due_said_in_english(self):
        said = "Dana please update the pricing page before Friday"
        self.assertEqual(H.when_said("by Friday", said), "by Friday")             # the connecting word may differ
        self.assertIsNone(H.when_said("by Monday", said))
        self.assertIsNone(H.when_said("next week", "we meet this week"))

    def test_model_down_gives_an_empty_summary(self):
        H._ollama_json = FakeModel(Exception)
        with H.db() as c:
            U, S, dyn = H.conv_stats(c, 7)
        self.assertEqual(H.summarise_meeting(U, dyn)["items"], [])

    def test_long_meeting_items_point_at_lines_across_parts(self):
        old = H.MEETING_CHARS
        H.MEETING_CHARS = 120                                                     # one part per ~2 lines
        try:
            part = {"summary": "חלק", "items": [{"type": "decision", "line": 2, "quote": "החלטנו שהגרסה הראשונה יוצאת בלי",
                                                 "what": "גרסה 1"}]}
            later = {"summary": "חלק", "items": [{"type": "promise", "line": 4, "quote": "אני אבדוק את התקציב מול",
                                                  "what": "תקציב"}]}
            H._ollama_json = FakeModel(part, later, part, {"topic": "סטטוס", "summary": "הכול", "topics": ["א"]})   # 3 parts + join
            with H.db() as c:
                U, S, dyn = H.conv_stats(c, 7)
            summ = H.summarise_meeting(U, dyn)
        finally:
            H.MEETING_CHARS = old
        self.assertEqual([(r["utt_id"], r["kind"]) for r in summ["items"]], [(101, "decision"), (103, "promise")])
        self.assertEqual(summ["topics"], ["א"])


if __name__ == "__main__":
    unittest.main()
