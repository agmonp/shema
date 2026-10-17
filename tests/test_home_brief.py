"""2026-10-17 home v2: "what matters today" (every item has a source), the structured day summary, "ask" source lines."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

_TMP = tempfile.mkdtemp(prefix="shema_brief_")
os.environ["SHEMA_DATA"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import home_listener as H      # noqa: E402

DAY = "2026-10-17"


class BriefTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        H.config()
        H.migrate()

    def setUp(self):
        with H.db() as c:
            for t in ("utterances", "conversations", "tasks", "meetings", "daily"):
                c.execute(f"DELETE FROM {t}")
            for i, (h, topic, marked) in enumerate((("09", "קניית מחשב", 0), ("13", "ארוחת צהריים", 1), ("20", "חוג", 0)), 1):
                c.execute("INSERT INTO conversations (id, start, end, seconds, topic, summary, status, marked) "
                          "VALUES (?,?,?,60,?,?,'done',?)", (i, f"{DAY}T{h}:00:00", f"{DAY}T{h}:01:00", topic, "סיכום", marked))
            c.execute("INSERT INTO conversations (id, start, end, seconds, status) VALUES (9, '2026-10-16T10:00:00', "
                      "'2026-10-16T10:01:00', 60, 'done')")
            lines = [(1, "09:00:05", "תמר", "אני אשלח לך את הצעת המחיר מחר בבוקר"),
                     (1, "09:00:20", "אגמון", "טוב אז נחכה עם המחשב עד שנראה מחיר"),
                     (2, "13:00:10", "תמר", "מה אוכלים היום"),
                     (9, "10:00:05", "תמר", "אני אשלח לך מחר משהו אחר")]
            for cid, t, n, text in lines:
                day = "2026-10-16" if cid == 9 else DAY
                c.execute("INSERT INTO utterances (conv_id, t0, t1, seconds, name, text, how) VALUES (?,?,?,3,?,?,'voice')",
                          (cid, f"{day}T{t}", f"{day}T{t}", n, text))
            c.execute("INSERT INTO tasks (conv_id, who, what, due, quote, created) VALUES (1,'תמר','לשלוח הצעת מחיר','מחר',"
                      "'אני אשלח לך את הצעת המחיר מחר', ?)", (DAY,))
            c.execute("INSERT INTO tasks (conv_id, who, what, quote, created) VALUES (9,'תמר','משהו אחר','אני אשלח לך מחר משהו', ?)",
                      (DAY,))

    def test_task_points_at_its_line_and_other_days_stay_out(self):
        with H.db() as c:
            B = H.brief(c, DAY)
        tasks = [i for i in B["items"] if i["kind"] == "task"]
        self.assertEqual(len(tasks), 1)
        t = tasks[0]
        self.assertEqual((t["conv_id"], t["who"], t["due"], t["src"]), (1, "תמר", "מחר", "quote"))
        with H.db() as c:
            uid = c.execute("SELECT id FROM utterances WHERE text LIKE 'אני אשלח לך את%'").fetchone()[0]
        self.assertEqual(t["utt_id"], uid)

    def test_empty_kinds_absent_marked_present_teach_needs_five(self):
        with H.db() as c:
            B = H.brief(c, DAY)
        kinds = [i["kind"] for i in B["items"]]
        self.assertEqual(kinds, ["task", "marked"])               # no decisions/open/highlights/teach invented
        with H.db() as c:
            for k in range(5):
                c.execute("INSERT INTO utterances (conv_id, t0, seconds, text, emb) VALUES (3, ?, 2, 'x', x'00')",
                          (f"{DAY}T20:00:{k:02d}",))
            B = H.brief(c, DAY)
        self.assertEqual(B["items"][-1]["kind"], "teach")
        self.assertEqual(B["items"][-1]["n"], 5)

    def test_day_detail_drops_items_without_a_real_conversation_and_takes_no_decisions(self):
        out = {"decisions": [{"text": "לחכות עם המחשב", "conv": 1}],
               "topics": [{"text": "מחשב", "conv": "[1]"}, {"text": "מומצא", "conv": 7}, {"text": "בלי מקור"}],
               "highlights": [{"text": "", "conv": 2}, "מחרוזת", {"text": "ארוחה", "conv": 2}]}
        det = H.day_detail(out, [1, 2, 3])
        self.assertNotIn("decisions", det)                         # a summary of summaries is no evidence for a decision
        self.assertEqual(det["topics"], [{"text": "מחשב", "conv_id": 1}])
        self.assertEqual(det["highlights"], [{"text": "ארוחה", "conv_id": 2}])

    def test_only_evidence_reaches_the_brief(self):
        det = {"decisions": [{"text": "מתוך סיכום", "conv_id": 1}], "topics": [],
               "highlights": [{"text": f"רגע {k}", "conv_id": 3} for k in range(4)]}
        with H.db() as c:
            c.execute("INSERT INTO daily (day, summary, detail) VALUES (?, 'קצר', ?)", (DAY, json.dumps(det, ensure_ascii=False)))
            c.execute("INSERT INTO meetings (id, conv_id, result) VALUES ('m1', 3, ?)",
                      (json.dumps({"decisions": ["לקנות מחשב נייד"]}, ensure_ascii=False),))
            B = H.brief(c, DAY)
        self.assertEqual([(i["kind"], i["src"]) for i in B["items"]], [("decision", "meeting"), ("task", "quote"), ("marked", "mark")])

    def test_at_most_five_with_teach_last(self):
        with H.db() as c:
            c.execute("INSERT INTO meetings (id, conv_id, result) VALUES ('m1', 3, ?)",
                      (json.dumps({"decisions": [f"החלטה {k}" for k in range(3)]}, ensure_ascii=False),))
            c.execute("INSERT INTO meetings (id, conv_id, result) VALUES ('m2', 1, ?)",
                      (json.dumps({"decisions": ["עוד החלטה"]}, ensure_ascii=False),))
            for k in range(6):
                c.execute("INSERT INTO utterances (conv_id, t0, seconds, text, emb) VALUES (3, ?, 2, 'x', x'00')",
                          (f"{DAY}T20:00:{k:02d}",))
            B = H.brief(c, DAY)
        self.assertEqual(len(B["items"]), 5)
        self.assertEqual([i["kind"] for i in B["items"]], ["decision"] * 4 + ["teach"])

    def test_source_lines_match_hebrew_prefixes_and_skip_question_words(self):
        with H.db() as c:
            L = H.source_lines(c, 1, "מה אמרנו על המחשב?")
            self.assertEqual([x["text"][:8] for x in L], ["טוב אז נ"])
            self.assertEqual(H.source_lines(c, 1, "מה אמרנו?"), [])
            L = H.source_lines(c, 1, "הצעת מחיר")
            self.assertEqual(len(L), 2)                            # both lines say מחיר; kept in time order
            self.assertLess(L[0]["t0"], L[1]["t0"])


    def test_answer_shows_dates_not_conversation_numbers(self):
        hits = [{"id": 777, "start": "2026-10-17T08:28:00"}]
        self.assertEqual(H._ask_dates("בשיחה 777 דיברו על מחשב, ובשיחה 7 על משהו", hits),
                         "בשיחה מ-17/10 דיברו על מחשב, ובשיחה על משהו")


if __name__ == "__main__":
    unittest.main()
