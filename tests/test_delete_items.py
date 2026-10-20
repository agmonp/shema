"""2026-10-20: the user's "מחק" on conversations and meetings (one or many): everything of them goes, a shared
recording stays, a conversation still being recorded is refused, the day summary is removed (and rewritten)."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="shema_del_")
os.environ["SHEMA_DATA"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import home_listener as H      # noqa: E402

DAY = "2026-10-19"


class DeleteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        H.config()
        H.migrate()

    def setUp(self):
        d = Path(_TMP) / "rec"
        d.mkdir(exist_ok=True)
        self.files = {k: d / f"{k}.ogg" for k in ("a", "shared", "m")}
        for f in self.files.values():
            f.write_bytes(b"x")
        with H.db() as c:
            for t in ("utterances", "conversations", "tasks", "meetings", "chunks", "daily", "sounds", "utt_edits", "conv_fts", "seg_vecs", "voice_bank"):
                c.execute(f"DELETE FROM {t}")
            for cid, st, status, ctx in ((1, "09", "done", "home"), (2, "10", "done", "home"), (3, "11", "open", "home"),
                                         (4, "12", "done", "meet:mt1")):
                c.execute("INSERT INTO conversations (id, start, end, seconds, status, ctx, topic, summary) VALUES (?,?,?,60,?,?,'נושא','סיכום')",
                          (cid, f"{DAY}T{st}:00:00", f"{DAY}T{st}:01:00", status, ctx))
                c.execute("INSERT INTO conv_fts (conv_id, topic, people, body) VALUES (?, 'נושא', '', 'גוף')", (cid,))
            for ch, f, ctx in ((10, "a", "home"), (11, "shared", "home"), (12, "m", "meet:mt1")):
                c.execute("INSERT INTO chunks (id, start, seconds, file, status, ctx) VALUES (?,?,60,?,'done',?)", (ch, DAY + "T09:00:00", str(self.files[f]), ctx))
            # conv 1 lives in chunk 10 alone and shares chunk 11 with conv 2
            for uid, cid, ch in ((100, 1, 10), (101, 1, 11), (102, 2, 11), (103, 3, 11), (104, 4, 12)):
                c.execute("INSERT INTO utterances (id, conv_id, chunk_id, t0, seconds, text) VALUES (?,?,?,?,2,'שלום')", (uid, cid, ch, DAY + "T09:00:00"))
            c.execute("INSERT INTO utt_edits (utt_id, kind, original) VALUES (100, 'fix', 'מקור')")
            c.execute("INSERT INTO voice_bank (speaker, utt_id, vec) VALUES ('p1', 100, x'00')")
            c.execute("INSERT INTO tasks (conv_id, what, remind_at) VALUES (1, 'משימה', '2026-10-21T09:00')")
            c.execute("INSERT INTO meetings (id, device, status, conv_id) VALUES ('mt1', 'ph', 'done', 4)")
            c.execute("INSERT INTO meetings (id, device, status) VALUES ('mt2', 'ph', 'recording')")
            c.execute("INSERT INTO daily (day, summary) VALUES (?, 'סיכום יום עם שיחה 1')", (DAY,))

    @mock.patch.object(H, "summarize_day")
    def test_delete_conversation_and_meeting(self, summ):
        r = H.delete_items(convs=[1, 3], meetings=["mt1", "mt2"])
        self.assertEqual((r["deleted"], r["refused"]), (2, 2))        # conv 3 is still open, mt2 still recording
        with H.db() as c:
            ids = {x[0] for x in c.execute("SELECT id FROM conversations")}
            self.assertEqual(ids, {2, 3})
            self.assertEqual({x[0] for x in c.execute("SELECT id FROM utterances")}, {102, 103})
            self.assertEqual(c.execute("SELECT count(*) FROM tasks").fetchone()[0], 0)
            self.assertEqual(c.execute("SELECT count(*) FROM utt_edits").fetchone()[0], 0)
            self.assertEqual({x[0] for x in c.execute("SELECT conv_id FROM conv_fts")}, {2, 3})
            self.assertEqual({x[0] for x in c.execute("SELECT id FROM meetings")}, {"mt2"})
            self.assertEqual(c.execute("SELECT count(*) FROM voice_bank WHERE speaker='p1'").fetchone()[0], 1)   # taught voice kept
            self.assertIsNone(c.execute("SELECT summary FROM daily WHERE day=?", (DAY,)).fetchone())
            files = {r["id"]: r["file"] for r in c.execute("SELECT id, file FROM chunks")}
        self.assertIsNone(files[10]); self.assertFalse(self.files["a"].exists())        # only conv 1 was in it
        self.assertIsNotNone(files[11]); self.assertTrue(self.files["shared"].exists())  # conv 2 is still in it
        self.assertIsNone(files[12]); self.assertFalse(self.files["m"].exists())         # the meeting's recording
        H.threading.enumerate()                                                         # the re-summary thread ran
        for t in H.threading.enumerate():
            if t is not H.threading.current_thread() and t.daemon:
                t.join(timeout=2)
        summ.assert_called_with(DAY)

    @mock.patch.object(H, "summarize_day")
    def test_nothing_and_garbage(self, summ):
        self.assertEqual(H.delete_items(convs=["x", 999], meetings=["../etc", "nope"])["deleted"], 0)
        summ.assert_not_called()


if __name__ == "__main__":
    unittest.main()
