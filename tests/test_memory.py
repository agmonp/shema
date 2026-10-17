"""2026-10-17 phase 5: decisions/commitments tied to a real line, and meaning search (memory_index). No model needed:
the model calls are replaced by fakes."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

_TMP = tempfile.mkdtemp(prefix="shema_mem_")
os.environ["SHEMA_DATA"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import home_listener as H      # noqa: E402
import memory_index as MI      # noqa: E402

LINES = [("תמר", "voice", "מה עם החוזה של הדירה?"),
         ("אגמון", "voice", "אני אשלח לך את החוזה מחר בבוקר, בסדר?"),
         ("תמר", "conv", "טוב. ואז החלטנו שלא קונים את המכונית הזאת."),
         (None, None, "אולי כדאי לקנות אופניים"),
         ("אגמון", "voice", "נדבר על זה ביום חמישי")]


class Fake:
    """Stands in for _ollama_json: one answer per call, in order; an Exception item = the model failed."""
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, system, user, num_ctx=8192, models=None):
        self.calls.append((system[:20], models))
        a = self.answers.pop(0)
        return {"error": "down"} if a is Exception else dict(a, model="fake")


class ItemsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        H.config()
        H.migrate()

    def setUp(self):
        self._orig = H._ollama_json
        with H.db() as c:
            for t in ("utterances", "conversations", "tasks"):
                c.execute(f"DELETE FROM {t}")
            c.execute("INSERT INTO conversations (id, start, end, seconds, status) VALUES (1, '2026-10-17T10:00:00', "
                      "'2026-10-17T10:05:00', 300, 'done')")
            for i, (n, how, text) in enumerate(LINES):
                c.execute("INSERT INTO utterances (id, conv_id, t0, t1, seconds, name, how, text) VALUES (?,1,?,?,3,?,?,?)",
                          (10 + i, f"2026-10-17T10:00:{i:02d}", f"2026-10-17T10:00:{i:02d}", n, how, text + " " + "מילה " * 6))
        with H.db() as c:
            self.L = [dict(r) for r in c.execute("SELECT id, name, how, text FROM utterances ORDER BY t0")]

    def tearDown(self):
        H._ollama_json = self._orig

    def test_quote_must_be_said_in_that_line_or_the_next(self):
        self.assertEqual(H.find_quote(self.L, "אני אשלח לך את החוזה מחר"), 1)
        self.assertEqual(H.find_quote(self.L, "אני אשלח לך את החוזה מחר", line=4), 1)      # wrong line number is fixed
        self.assertIsNone(H.find_quote(self.L, "אני אשלח לך את ההסכם מחר"))                 # one word changed = not said
        self.assertIsNone(H.find_quote(self.L, "אשלח מחר"))                                 # too short to prove anything

    def test_due_only_when_said_and_who_from_the_line(self):
        rows = H.check_items(self.L, [
            {"type": "promise", "line": 2, "quote": "אני אשלח לך את החוזה מחר בבוקר", "what": "לשלוח חוזה", "when": "מחר בבוקר"},
            {"type": "decision", "line": 3, "quote": "החלטנו שלא קונים את המכונית הזאת", "what": "לא קונים", "when": "בשבוע הבא"},
            {"type": "idea", "line": 4, "quote": "אולי כדאי לקנות אופניים", "what": "אופניים"},
            {"type": "promise", "line": 2, "quote": "אני אתקשר לבנק עוד היום", "what": "מומצא"}])
        self.assertEqual([(r["kind"], r["utt_id"], r["who"], r["who_how"], r["due"]) for r in rows],
                         [("promise", 11, "אגמון", "voice", "מחר בבוקר"), ("decision", 12, "תמר", "conv", None)])

    def test_judge_decides_and_a_failure_keeps_what_is_stored(self):
        prop = {"items": [{"type": "promise", "line": 2, "quote": "אני אשלח לך את החוזה מחר בבוקר", "what": "לשלוח חוזה"},
                          {"type": "agreed", "line": 5, "quote": "נדבר על זה ביום חמישי", "what": "לדבר", "when": "חמישי"}]}
        H._ollama_json = f = Fake(prop, {"keep": [0, 1]}, prop, {"keep": [0]})              # 2nd pass: only the promise
        rows = H.extract_items(1, force=True)
        self.assertEqual([r["kind"] for r in rows], ["promise"])                               # both passes must agree
        self.assertEqual({m for _, m in f.calls}, {("gemma4:12b",)})                          # no small-model fallback
        H._ollama_json = Fake(prop, Exception)                                                 # judge down
        H.extract_items(1, force=True)
        with H.db() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM tasks WHERE conv_id=1").fetchone()[0], 1)

    def test_nothing_found_costs_one_pass(self):
        H._ollama_json = f = Fake({"items": []})
        self.assertEqual(H.extract_items(1, force=True), [])
        self.assertEqual(len(f.calls), 1)

    def test_handled_items_are_not_proposed_again(self):
        prop = {"items": [{"type": "promise", "line": 2, "quote": "אני אשלח לך את החוזה מחר בבוקר", "what": "לשלוח חוזה"}]}
        H._ollama_json = Fake(prop, {"keep": [0]}, prop, {"keep": [0]})
        H.extract_items(1, force=True)
        with H.db() as c:
            c.execute("UPDATE tasks SET state='dismissed'")
        H._ollama_json = Fake(prop, {"keep": [0]}, prop, {"keep": [0]})
        H.extract_items(1, force=True)
        with H.db() as c:
            self.assertEqual([r[0] for r in c.execute("SELECT state FROM tasks")], ["dismissed"])

    def test_brief_marks_candidates_and_points_at_the_line(self):
        with H.db() as c:
            c.execute("INSERT INTO tasks (conv_id, who, who_how, what, quote, kind, utt_id, state) VALUES "
                      "(1,'אגמון','voice','לשלוח חוזה','אני אשלח לך את החוזה','promise',11,'open')")
            c.execute("INSERT INTO tasks (conv_id, who, who_how, what, quote, kind, utt_id, state) VALUES "
                      "(1,'תמר','conv','לא קונים','החלטנו שלא קונים','decision',12,'confirmed')")
            B = H.brief(c, "2026-10-17")["items"]
        self.assertEqual([(i["kind"], i["sure"], i["utt_id"]) for i in B], [("decision", True, 12), ("task", False, 11)])
        self.assertFalse(B[0]["who_sure"])                                                     # "כנראה" name stays a guess


class MeaningTests(unittest.TestCase):
    def test_windows_share_one_line_and_cover_everything(self):
        U = [{"id": i, "t0": str(i), "name": "א", "text": " ".join(["מילה"] * 12)} for i in range(7)]
        W = MI.windows(U)
        self.assertEqual([[u["id"] for u in w] for w in W], [[0, 1, 2], [2, 3, 4], [4, 5, 6]])
        self.assertEqual(MI.windows(U[:3]), [U[:3]])

    def test_fuse_keeps_exact_words_and_adds_meaning(self):
        sem = [(.6, 7, 30, 1, 2, "t"), (.55, 8, 10, None, None, "t"), (.5, 9, 10, 5, 6, "t")]
        out = MI.fuse([10, 20], sem, 5)
        self.assertEqual([x[0] for x in out], [10, 30, 20])
        self.assertEqual(out[0][2]["u0"], 5)                 # the summary vector (u0 None) is never the line window
        self.assertIsNone(out[2][2])

    def test_semantic_search_without_a_model_returns_nothing(self):
        H.config()
        H.migrate()
        orig = MI.embed
        MI.embed = lambda texts, query=False: None
        try:
            with H.db() as c:
                c.execute("INSERT INTO seg_vecs (conv_id, u0, u1, t0, text, vec) VALUES (1,1,1,'2026','x',?)",
                          (np.ones(768, np.float32).tobytes(),))
                self.assertEqual(MI.semantic(c, "שאלה"), [])
            self.assertEqual(H.search_convs("שאלה"), [])         # full text only, and nothing matched
        finally:
            MI.embed = orig
            with H.db() as c:                                     # the test database is shared by later test modules
                c.execute("DELETE FROM seg_vecs")


if __name__ == "__main__":
    unittest.main()
