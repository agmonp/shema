"""2026-10-20 bug: the home said "99+ voices to teach" while the teaching screen showed nothing after a few lines.
The home count is now what smart teaching will really ask about, batches continue until it is zero, and a user with
no voices taught yet still gets lines to start with."""
from datetime import datetime
import os
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

_TMP = tempfile.mkdtemp(prefix="shema_teachn_")
os.environ["SHEMA_DATA"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import home_listener as H      # noqa: E402

DAY = datetime.now().strftime("%Y-%m-%d")
RNG = np.random.default_rng(7)


def unit(v):
    return (v / np.linalg.norm(v)).astype(np.float32)


A, B = unit(RNG.normal(size=192)), unit(RNG.normal(size=192))      # two clearly different voices


def near(v):
    return unit(v + 0.15 * RNG.normal(size=192) / np.sqrt(192) * 10)


class TeachCountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        H.config()
        H.migrate()

    def setUp(self):
        H._TEACH_CACHE.clear()
        with H.db() as c:
            for t in ("utterances", "voice_bank", "teach_skips", "conversations"):
                c.execute(f"DELETE FROM {t}")
            k = 0
            for conv in range(1, 16):                     # 15 conversations x 2 teachable lines = 30
                c.execute("INSERT INTO conversations (id, start, end, seconds, status) VALUES (?,?,?,60,'done')",
                          (conv, f"{DAY}T08:{conv:02d}:00", f"{DAY}T08:{conv:02d}:59"))
                for j in range(2):
                    k += 1
                    c.execute("INSERT INTO utterances (conv_id, t0, seconds, text, emb) VALUES (?,?,3,'אני אומר משהו ארוך',?)",
                              (conv, f"{DAY}T08:{conv:02d}:{j * 10:02d}", near(A if k % 2 else B).tobytes()))
            # never offered, so never counted: too short, too few words, TV, marked unclear
            c.execute("INSERT INTO utterances (conv_id, t0, seconds, text, emb) VALUES (1, ?, 1.0, 'קצר מדי אבל מילים', ?)", (DAY + "T09:00:00", near(A).tobytes()))
            c.execute("INSERT INTO utterances (conv_id, t0, seconds, text, emb) VALUES (1, ?, 3, 'שתי מילים', ?)", (DAY + "T09:00:01", near(A).tobytes()))
            c.execute("INSERT INTO utterances (conv_id, t0, seconds, text, emb, media) VALUES (1, ?, 3, 'טלוויזיה אומרת דברים', ?, 'tv')", (DAY + "T09:00:02", near(A).tobytes()))
            c.execute("INSERT INTO utterances (id, conv_id, t0, seconds, text, emb) VALUES (999, 1, ?, 3, 'כמה אנשים מדברים יחד', ?)", (DAY + "T09:00:03", near(A).tobytes()))
            c.execute("INSERT INTO teach_skips (utt_id, reason, at) VALUES (999, 'multi', ?)", (DAY,))

    def teach_all(self, q, who=None):
        with H.db() as c:
            for it in q["items"]:
                c.execute("UPDATE utterances SET speaker=? WHERE id=?", (who or it.get("guess") or "p_a", it["id"]))

    def test_new_user_without_voices_can_start_and_count_matches(self):
        with H.db() as c:
            q = H.teach_queue(c)
            n = H.teach_count(c)
        self.assertEqual(n, 30)                              # not 34: the 4 lines the screen would never show are out
        self.assertEqual(q["left"], n)
        self.assertEqual(len(q["items"]), H.TEACH_GOAL)
        self.assertTrue(q["more"])
        self.assertEqual(H.digest()["teach"], 30)

    def test_batches_continue_until_finished(self):
        seen = 0
        for _ in range(10):
            with H.db() as c:
                q = H.teach_queue(c)
            if not q["items"]:
                break
            self.assertEqual(q["left"], 30 - seen)
            seen += len(q["items"])
            self.teach_all(q)
        with H.db() as c:
            q = H.teach_queue(c)
            self.assertEqual((q["items"], q["left"], q["more"], H.teach_count(c)), ([], 0, False, 0))
        self.assertEqual(seen, 30)
        self.assertEqual(H.digest()["teach"], 0)

    def test_with_known_voices_ambiguous_lines_are_not_promised(self):
        with H.db() as c:
            c.execute("INSERT INTO voice_bank (speaker, vec, created) VALUES ('p_a', ?, ?)", (A.tobytes(), DAY))
            c.execute("INSERT INTO voice_bank (speaker, vec, created) VALUES ('p_b', ?, ?)", (B.tobytes(), DAY))
            mix = unit(A + B)                                # equally close to both: a mix, never asked
            c.execute("INSERT INTO utterances (conv_id, t0, seconds, text, emb) VALUES (2, ?, 3, 'שניים מדברים ביחד כאן', ?)",
                      (DAY + "T09:30:00", mix.tobytes()))
            q = H.teach_queue(c)
            self.assertEqual(q["left"], H.teach_count(c))
            self.assertEqual(q["skipped_ambiguous"], 1)
            self.assertTrue(all(it.get("guess") in ("p_a", "p_b") for it in q["items"]))

    def test_after_teaching_one_voice_new_people_are_still_asked(self):
        """found on the emulator: after the owner's first lines the screen said "finished" while other people's
        lines were waiting -- lines no known voice is close to were thrown out as "unclear"."""
        with H.db() as c:
            c.execute("INSERT INTO voice_bank (speaker, vec, created) VALUES ('p_a', ?, ?)", (A.tobytes(), DAY))
            q = H.teach_queue(c)
            n = H.teach_count(c)
        self.assertEqual(n, 30)                              # 15 of A's (guessed) + 15 of B's (a new person)
        self.assertEqual(q["skipped_ambiguous"], 0)
        new = [it for it in q["items"] if "guess" not in it]
        self.assertTrue(0 < len(new) <= 4)                  # new voices asked beside the guessed ones

    def test_brief_teach_item_uses_the_same_count(self):
        with H.db() as c:
            items = H.brief(c, DAY)["items"]
        t = [i for i in items if i["kind"] == "teach"]
        self.assertEqual(t[0]["n"], 30)


if __name__ == "__main__":
    unittest.main()
