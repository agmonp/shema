"""2026-10-20: opt-in reminders. A reminder exists only after the user asked for it on that item; nothing is
reminded by itself (not even a confirmed item). The paired phone gets them in its status poll."""
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.request

_TMP = tempfile.mkdtemp(prefix="shema_remind_")
os.environ["SHEMA_DATA"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import home_listener as H      # noqa: E402

TODAY = datetime.now().strftime("%Y-%m-%d")


class ReminderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        H.config()
        H.migrate()

    def setUp(self):
        with H.db() as c:
            for t in ("utterances", "conversations", "tasks"):
                c.execute(f"DELETE FROM {t}")
            c.execute("INSERT INTO conversations (id, start, end, seconds, status) VALUES (1, ?, ?, 60, 'done')",
                      (f"{TODAY}T00:00:01", f"{TODAY}T00:01:00"))
            c.execute("INSERT INTO tasks (id, conv_id, who, what, due, quote, state) VALUES "
                      "(1, 1, 'תמר', 'לשלוח הצעת מחיר', 'מחר בבוקר', 'אני אשלח לך מחר בבוקר', 'confirmed')")
            c.execute("INSERT INTO tasks (id, conv_id, who, what, quote) VALUES (2, 1, '?', 'להתקשר לחשמלאי', 'צריך להתקשר')")

    def test_migration_adds_remind_at_to_an_old_tasks_table(self):
        old = Path(_TMP) / "old.db"
        c = sqlite3.connect(old)
        c.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, conv_id INTEGER, who TEXT, what TEXT, due TEXT, quote TEXT, "
                  "state TEXT DEFAULT 'open', created TEXT)")
        c.execute("INSERT INTO tasks (what) VALUES ('ישן')")
        c.commit(); c.close()
        saved = H.DB
        try:
            H.DB = old
            H.migrate()
            with H.db() as c:
                cols = {r["name"] for r in c.execute("PRAGMA table_info(tasks)")}
                self.assertIn("remind_at", cols)
                self.assertIsNone(c.execute("SELECT remind_at FROM tasks").fetchone()[0])
        finally:
            H.DB = saved

    def test_nothing_is_reminded_by_itself_not_even_confirmed(self):
        with H.db() as c:
            self.assertEqual(H.reminders(c), [])
            B = H.brief(c, TODAY)
        self.assertTrue(all(i.get("remind_at") is None for i in B["items"] if i["kind"] == "task"))

    def test_set_list_and_cancel(self):
        at = (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")
        r = H.set_reminder(2, at)
        self.assertEqual((r["ok"], r["remind_at"]), (True, at))
        with H.db() as c:
            R = H.reminders(c)
            B = H.brief(c, TODAY)
        self.assertEqual([x["id"] for x in R], [2])
        self.assertEqual(R[0]["at_ms"], int(datetime.fromisoformat(at).timestamp() * 1000))
        self.assertIsNone(R[0]["who"])                         # "?" is no name
        self.assertEqual({i["id"]: i["remind_at"] for i in B["items"] if i["kind"] == "task"}, {1: None, 2: at})
        self.assertTrue(H.set_reminder(2, None)["ok"])
        with H.db() as c:
            self.assertEqual(H.reminders(c), [])

    def test_bad_past_unknown_and_closed(self):
        self.assertFalse(H.set_reminder(1, "מחר")["ok"])
        self.assertFalse(H.set_reminder(1, "2020-01-01T09:00")["ok"])
        self.assertFalse(H.set_reminder(99, (datetime.now() + timedelta(days=1)).isoformat())["ok"])
        at = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT09:00")
        self.assertTrue(H.set_reminder(1, at)["ok"])
        with H.db() as c:
            c.execute("UPDATE tasks SET state='done' WHERE id=1")
            self.assertEqual(H.reminders(c), [])               # done -> the phone drops it on its next sync
        self.assertFalse(H.set_reminder(1, at)["ok"])

    def test_said_due_time_is_only_a_suggestion(self):
        with H.db() as c:
            t = [i for i in H.brief(c, TODAY)["items"] if i.get("id") == 1][0]
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        self.assertEqual(t["due_at"], f"{tomorrow}T09:00")
        self.assertIsNone(t["remind_at"])

    def test_due_to_time(self):
        base = "2026-10-20T11:00:00"                          # a Tuesday
        cases = {"מחר": "2026-10-21T09:00", "מחרתיים בערב": "2026-10-22T19:00", "הערב": "2026-10-20T19:00",
                 "ביום שלישי": "2026-10-27T09:00", "ביום ראשון בשעה 17:30": "2026-10-25T17:30",
                 "בעוד שלושה ימים": "2026-10-23T09:00", "בשבוע הבא": "2026-10-27T09:00", "25/10": "2026-10-25T09:00",
                 "מחר ב-5 אחר הצהריים": "2026-10-21T17:00", "עד חמישי": "2026-10-22T09:00",
                 "בקרוב": None, "": None, None: None, "פעם שני": None}
        for due, want in cases.items():
            self.assertEqual(H.due_to_time(due, base), want, due)


class ReminderHttpTests(unittest.TestCase):
    """The endpoint is phone-ok (needs the pairing token) and the status poll carries the list only with a device."""
    @classmethod
    def setUpClass(cls):
        H.config()
        H.migrate()
        cls.token = H.config().get("token") or "t0k"
        cfg = H.config(); cfg["token"] = cls.token; H._write_config(cfg)
        from http.server import ThreadingHTTPServer
        class Remote(H.Handler):                          # as if from the phone, not this PC's own screen
            def _local(self):
                return False
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Remote)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def _req(self, path, body=None, token=True):
        h = {"Content-Type": "application/json"}
        if token:
            h["X-Home-Token"] = self.token
        rq = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None, headers=h)
        try:
            with urllib.request.urlopen(rq) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_endpoint_and_status(self):
        with H.db() as c:
            c.execute("DELETE FROM tasks")
            c.execute("INSERT INTO tasks (id, conv_id, who, what, quote) VALUES (5, 1, 'דנה', 'להחזיר ספר', 'אחזיר')")
        at = (datetime.now() + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M")
        self.assertEqual(self._req("/home/api/task_remind", {"id": 5, "at": at}, token=False)[0], 403)
        code, out = self._req("/home/api/task_remind", {"id": 5, "at": at})
        self.assertEqual((code, out["ok"]), (200, True))
        code, st = self._req("/home/api/status?device=ph1")
        self.assertEqual([r["id"] for r in st["reminders"]], [5])
        code, st = self._req("/home/api/status?device=ph1", token=False)
        self.assertIsNone(st["reminders"])                     # nothing about items without the code
        code, out = self._req("/home/api/task_remind", {"id": 5, "at": None})
        self.assertTrue(out["ok"])
        self.assertEqual(self._req("/home/api/status?device=ph1")[1]["reminders"], [])


if __name__ == "__main__":
    unittest.main()
