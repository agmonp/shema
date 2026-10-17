"""2026-10-17 speaker tools: "who said this" candidates, word times, split one line between speakers and undo."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

import numpy as np

_TMP = tempfile.mkdtemp(prefix="shema_spk_")
os.environ["SHEMA_DATA"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import home_listener as H      # noqa: E402
import memory_index            # noqa: E402

memory_index.embed = lambda texts, query=False: None      # labelling re-indexes meaning; no model in tests

D = 192
RNG = np.random.default_rng(3)


def unit(v):
    return (v / np.linalg.norm(v)).astype(np.float32)


VOICE = {p: unit(RNG.normal(size=D)) for p in ("p_a", "p_b", "p_c")}


class SpeakerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        H.config()
        H.migrate()

    def setUp(self):
        now = datetime(2026, 10, 17, 12, 0, 0)
        self.t0 = now
        with H.db() as c:
            for t in ("utterances", "conversations", "voice_bank", "home_people", "utt_edits", "teach_skips"):
                c.execute(f"DELETE FROM {t}")
            for pid, n in (("p_a", "אורי"), ("p_b", "בת-אל"), ("p_c", "גיל")):
                c.execute("INSERT INTO home_people (id, name, created) VALUES (?,?,?)", (pid, n, H.iso(now)))
                for k in range(3):
                    c.execute("INSERT INTO voice_bank (speaker, utt_id, vec, created, device) VALUES (?,?,?,?,?)",
                              (pid, -100 - k, unit(VOICE[pid] + RNG.normal(scale=.05, size=D)).tobytes(), H.iso(now), "ph"))
            c.execute("INSERT INTO conversations (id, start, end, seconds, status) VALUES (1,?,?,60,'done')",
                      (H.iso(now), H.iso(now + timedelta(seconds=60))))

    def add(self, text, emb=None, speaker=None, how=None, words=None, t=0.0, dur=4.0):
        with H.db() as c:
            uid = c.execute("INSERT INTO utterances (chunk_id, conv_id, t0, t1, seconds, speaker, name, text, emb, how, device, words) "
                            "VALUES (1,1,?,?,?,?,?,?,?,?, 'ph', ?)",
                            (H.iso(self.t0 + timedelta(seconds=t)), H.iso(self.t0 + timedelta(seconds=t + dur)), dur, speaker,
                             H.name_of(c, speaker) if speaker else None, text,
                             emb.tobytes() if emb is not None else None, how,
                             json.dumps(words, ensure_ascii=False) if words else None)).lastrowid
            if how == "user" and emb is not None:
                c.execute("INSERT INTO voice_bank (speaker, utt_id, vec, created, device) VALUES (?,?,?,?,?)",
                          (speaker, uid, emb.tobytes(), H.iso(self.t0), "ph"))
        return uid

    def row(self, uid):
        with H.db() as c:
            r = c.execute("SELECT * FROM utterances WHERE id=?", (uid,)).fetchone()
            return dict(r) if r else None

    # ---------------------------------------------------------------- candidates
    def test_clear_voice_one_candidate_random_voice_none(self):
        clear = self.add("שלום מה שלומך היום", unit(.9 * VOICE["p_b"] + .1 * unit(RNG.normal(size=D))))
        rand = self.add("כן כן בסדר", unit(RNG.normal(size=D)), t=10)
        with H.db() as c:
            a, b = H.who_cands(c, clear), H.who_cands(c, rand)
        self.assertEqual([x["id"] for x in a["cands"]], ["p_b"])
        self.assertEqual(a["cands"][0]["why"], "voice")
        self.assertEqual(b["cands"], [])
        self.assertNotIn("score", a["cands"][0])            # no uncalibrated number reaches the screen

    def test_conversation_alone_is_not_a_reason(self):
        self.add("אני פה", unit(VOICE["p_c"]), speaker="p_c", how="user", t=20)
        rand = self.add("טוב אז ככה", unit(RNG.normal(size=D)), t=30)
        with H.db() as c:
            self.assertEqual(H.who_cands(c, rand)["cands"], [])  # named in the conversation, but the voice disagrees

    def test_no_voice_no_candidates(self):
        self.add("אני פה", unit(VOICE["p_c"]), speaker="p_c", how="user", t=20)
        bare = self.add("נו", None, t=30)                     # a line without a voice vector
        with H.db() as c:
            self.assertEqual(H.who_cands(c, bare)["cands"], [])

    def test_at_most_three(self):
        mix = unit(VOICE["p_a"] + VOICE["p_b"] + VOICE["p_c"])
        with H.db() as c:
            self.assertLessEqual(len(H.who_cands(c, self.add("א ב ג ד", mix))["cands"]), H.WHO_MAX)

    # ---------------------------------------------------------------- word times
    def test_words_json_relative_to_line(self):
        u = {"t0": 2.0, "media": None, "words": [[2.0, 2.4, " שלום"], [2.5, 2.9, " לך"]]}
        self.assertEqual(json.loads(H.words_json(u)), [[0.0, 0.4, "שלום"], [0.5, 0.9, "לך"]])
        self.assertIsNone(H.words_json(dict(u, media="טלוויזיה")))

    # ---------------------------------------------------------------- split / undo
    def test_split_with_word_times_follows_audio(self):
        words = [[0.0, 0.5, "מי"], [0.6, 1.0, "בא"], [2.0, 2.4, "אני"], [2.5, 3.0, "בא"]]
        uid = self.add("מי בא אני בא", unit(VOICE["p_a"]), speaker="p_a", how="user", words=words)
        r = H.split_utterance(uid, [2], [{"speaker": "p_a"}, {"new_name": "דנה"}])
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["exact"])
        a, b = self.row(r["ids"][0]), self.row(r["ids"][1])
        self.assertEqual((a["text"], b["text"]), ("מי בא", "אני בא"))
        self.assertEqual(b["name"], "דנה")
        self.assertEqual(b["t0"][11:19], "12:00:02")                        # starts at the 3rd word
        self.assertAlmostEqual(a["seconds"], 1.0, places=2)
        self.assertIsNone(a["emb"])                                         # mixed voice: nothing to learn
        with H.db() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM voice_bank WHERE utt_id=?", (uid,)).fetchone()[0], 0)

    def test_split_without_word_times_is_marked_estimated(self):
        uid = self.add("אחת שתיים שלוש ארבע", unit(VOICE["p_a"]))
        r = H.split_utterance(uid, [1], [{}, {"speaker": "p_b"}])
        self.assertTrue(r["ok"])
        self.assertFalse(r["exact"])

    def test_overlap_keeps_whole_span(self):
        uid = self.add("כן לא כן לא", unit(VOICE["p_a"]))
        r = H.split_utterance(uid, [2], [{"speaker": "p_a"}, {"speaker": "p_b"}], overlap=True)
        parts = [self.row(i) for i in r["ids"]]
        self.assertTrue(all(p["overlap"] == 1 and p["seconds"] == 4.0 for p in parts))
        self.assertEqual(parts[0]["t0"], parts[1]["t0"])

    def test_undo_restores_everything_and_survives_reopen(self):
        emb = unit(VOICE["p_a"])
        uid = self.add("אני רוצה לאכול עכשיו", emb, speaker="p_a", how="user")
        before = self.row(uid)
        r = H.split_utterance(uid, [1, 3], [{"speaker": "p_a"}, {"speaker": "p_b"}, {}])
        self.assertEqual(len(r["ids"]), 3)
        self.assertFalse(H.split_utterance(r["ids"][1], [1], [{}, {}])["ok"])   # no split of a split
        u = H.unsplit_utterance(r["ids"][2])                                    # undo from any part
        self.assertTrue(u["ok"])
        after = self.row(uid)
        self.assertEqual({k: after[k] for k in before}, before)
        with H.db() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM utterances WHERE split_of=?", (uid,)).fetchone()[0], 0)
            self.assertEqual(c.execute("SELECT count(*) FROM voice_bank WHERE utt_id=?", (uid,)).fetchone()[0], 1)

    def test_bad_requests(self):
        uid = self.add("רק מילה", unit(VOICE["p_a"]))
        self.assertFalse(H.split_utterance(uid, [], [{}])["ok"])
        self.assertFalse(H.split_utterance(uid, [1], [{}])["ok"])           # one person for two parts
        self.assertFalse(H.unsplit_utterance(uid)["ok"])


if __name__ == "__main__":
    unittest.main()
