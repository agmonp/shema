"""2026-10-20: download a whole meeting's recording: one m4a, speech only, chapters named by the real clock time."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
import wave

import numpy as np

_TMP = tempfile.mkdtemp(prefix="shema_meetaudio_")
os.environ["SHEMA_DATA"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import home_listener as H      # noqa: E402
import voice_embed as VE       # noqa: E402

SR = 16000


def tone(path, seconds, spans):
    """seconds of silence with a tone inside every (s, e)"""
    a = np.zeros(int(seconds * SR), np.int16)
    for s, e in spans:
        t = np.arange(int((e - s) * SR)) / SR
        a[int(s * SR):int(s * SR) + len(t)] = (8000 * np.sin(2 * np.pi * 440 * t)).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(a.tobytes())


def chapters_of(f):
    out = subprocess.run([VE.FF, "-v", "error", "-i", str(f), "-f", "ffmetadata", "-"], capture_output=True).stdout.decode("utf-8")
    return [l[6:] for l in out.splitlines() if l.startswith("title=")][1:], out


def duration(f):
    err = subprocess.run([VE.FF, "-i", str(f)], capture_output=True).stderr.decode("utf-8", "replace")
    h, m, s = err.split("Duration: ")[1].split(",")[0].split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


class MeetingAudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        H.config()
        H.migrate()

    def setUp(self):
        d = Path(_TMP) / "rec"
        d.mkdir(exist_ok=True)
        # two recordings of 60 s; speech at 14:00:05-14:00:10 (תמר), 14:00:10.5-14:00:14 (דנה), 14:00:40-44 (תמר)
        # and in the second one 14:05:02-14:05:08 (דנה). Everything else is silence and must not be in the file.
        tone(d / "a.wav", 60, [(5, 14), (40, 44)])
        tone(d / "b.wav", 60, [(2, 8)])
        with H.db() as c:
            for t in ("utterances", "chunks", "meetings"):
                c.execute(f"DELETE FROM {t}")
            c.execute("INSERT INTO meetings (id, device, title, started, ended, status) VALUES "
                      "('m1', 'ph', 'תכנון רבעון', '2026-10-20T14:00:00', '2026-10-20T14:06:00', 'done')")
            for cid, st, f in ((1, "2026-10-20T14:00:00", d / "a.wav"), (2, "2026-10-20T14:05:00", d / "b.wav")):
                c.execute("INSERT INTO chunks (id, device, start, seconds, file, status, ctx) VALUES (?,?,?,60,?,'done','meet:m1')",
                          (cid, "ph", st, str(f)))
            for ch, t0, t1, n in ((1, "14:00:05", "14:00:10", "תמר"), (1, "14:00:10.500", "14:00:14", "דנה"),
                                  (1, "14:00:40", "14:00:44", "תמר"), (2, "14:05:02", "14:05:08", "דנה")):
                c.execute("INSERT INTO utterances (chunk_id, t0, t1, name, text) VALUES (?,?,?,?, 'x')",
                          (ch, "2026-10-20T" + t0, "2026-10-20T" + t1, n))

    def test_plan_speech_only_with_real_times(self):
        with H.db() as c:
            P, C, miss = H.meeting_audio_plan(c, "m1")
        self.assertEqual(miss, 0)
        self.assertEqual(len(P), 3)                         # 5-14 joined (0.5 s pause), 40-44, the second recording
        self.assertAlmostEqual(sum(p["dur"] for p in P), 9.5 + 4.5 + 6.5, places=2)
        self.assertEqual([(x["t"][11:19], x["who"]) for x in C],
                         [("14:00:05", "תמר"), ("14:00:10", "דנה"), ("14:00:40", "תמר"), ("14:05:02", "דנה")])
        self.assertAlmostEqual(C[2]["at"], 9.5, places=2)    # third chapter starts right after the first piece

    def test_file_has_chapters_with_clock_times(self):
        f, info = H.meeting_audio("m1")
        self.assertIsNotNone(f, info)
        self.assertAlmostEqual(duration(f), 20.5, delta=0.3)      # 6 minutes of meeting -> 20.5 s of speech
        titles, raw = chapters_of(f)
        self.assertEqual(titles, ["14:00:05 · תמר", "14:00:10 · דנה", "14:00:40 · תמר", "14:05:02 · דנה"])
        self.assertIn("תכנון רבעון", raw)
        self.assertEqual(info["name"], "meeting-2026-10-20-1400.m4a")
        self.assertEqual(H.meeting_audio("m1")[0], f)             # built once, then reused

    def test_no_audio_kept(self):
        with H.db() as c:
            c.execute("UPDATE chunks SET file=NULL")
        f, why = H.meeting_audio("m1")
        self.assertIsNone(f)
        self.assertIn("לא נשמרה", why)
        f, why = H.meeting_audio("nope")
        self.assertIsNone(f)

    def test_http_needs_token(self):
        cfg = H.config(); cfg["token"] = "tk"; H._write_config(cfg)

        class Remote(H.Handler):
            def _local(self):
                return False
        from http.server import ThreadingHTTPServer
        srv = ThreadingHTTPServer(("127.0.0.1", 0), Remote)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{srv.server_address[1]}/home/audio/meeting/m1.m4a"
        try:
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(url)
            with urllib.request.urlopen(urllib.request.Request(url, headers={"X-Home-Token": "tk"})) as r:
                body = r.read()
                self.assertEqual(r.headers["Content-Type"], "audio/mp4")
                self.assertIn("meeting-2026-10-20-1400.m4a", r.headers["Content-Disposition"])
                self.assertEqual(r.headers["X-Missing-Chunks"], "0")
            self.assertGreater(len(body), 1000)
        finally:
            srv.shutdown()


class ConvAudioTests(unittest.TestCase):
    """2026-10-20: the same download for a regular conversation (its own lines, TV lines left out)."""
    @classmethod
    def setUpClass(cls):
        H.config()
        H.migrate()

    def setUp(self):
        d = Path(_TMP) / "rec"
        d.mkdir(exist_ok=True)
        tone(d / "c.wav", 60, [(5, 14), (20, 25), (40, 44)])
        tone(d / "d.wav", 60, [(2, 8)])
        with H.db() as c:
            for t in ("utterances", "chunks", "meetings", "conversations"):
                c.execute(f"DELETE FROM {t}")
            c.execute("INSERT INTO conversations (id, start, end, seconds, topic, status) VALUES "
                      "(7, '2026-10-20T09:30:00', '2026-10-20T09:36:00', 360, 'ארוחת בוקר', 'done')")
            c.execute("INSERT INTO conversations (id, start, end, seconds, topic, status) VALUES "
                      "(8, '2026-10-20T11:00:00', '2026-10-20T11:01:00', 60, 'אחרת', 'done')")
            for cid, st, f in ((11, "2026-10-20T09:30:00", d / "c.wav"), (12, "2026-10-20T09:35:00", d / "d.wav")):
                c.execute("INSERT INTO chunks (id, device, start, seconds, file, status) VALUES (?,?,?,60,?,'done')",
                          (cid, "ph", st, str(f)))
            # 09:30:20-25 is the TV (media) and another conversation's line sits in the same recording: neither goes in
            for ch, conv, t0, t1, n, media in ((11, 7, "09:30:05", "09:30:10", "תמר", None),
                                               (11, 7, "09:30:10.500", "09:30:14", "דנה", None),
                                               (11, 7, "09:30:20", "09:30:25", None, "tv"),
                                               (11, 8, "09:30:40", "09:30:44", "יוסי", None),
                                               (12, 7, "09:35:02", "09:35:08", "דנה", None)):
                c.execute("INSERT INTO utterances (chunk_id, conv_id, t0, t1, name, text, media) VALUES (?,?,?,?,?, 'x', ?)",
                          (ch, conv, "2026-10-20T" + t0, "2026-10-20T" + t1, n, media))

    def test_plan_own_lines_only(self):
        with H.db() as c:
            P, C, miss = H.conv_audio_plan(c, 7)
            self.assertTrue(H.conv_has_audio(c, 7))
        self.assertEqual(miss, 0)
        self.assertEqual(len(P), 2)
        self.assertAlmostEqual(sum(p["dur"] for p in P), 9.5 + 6.5, places=2)
        self.assertEqual([(x["t"][11:19], x["who"]) for x in C], [("09:30:05", "תמר"), ("09:30:10", "דנה"), ("09:35:02", "דנה")])

    def test_file_and_name(self):
        f, info = H.conv_audio(7)
        self.assertIsNotNone(f, info)
        self.assertAlmostEqual(duration(f), 16.0, delta=0.3)
        titles, raw = chapters_of(f)
        self.assertEqual(titles, ["09:30:05 · תמר", "09:30:10 · דנה", "09:35:02 · דנה"])
        self.assertIn("ארוחת בוקר", raw)
        self.assertEqual(info["name"], "conversation-2026-10-20-0930.m4a")
        self.assertEqual(H.conv_audio(7)[0], f)

    def test_api_has_audio_and_no_audio(self):
        self.assertTrue(H.api("/home/api/conversation", {"id": ["7"]})["has_audio"])
        with H.db() as c:
            c.execute("UPDATE chunks SET file=NULL")
        self.assertFalse(H.api("/home/api/conversation", {"id": ["7"]})["has_audio"])
        f, why = H.conv_audio(7)
        self.assertIsNone(f)
        self.assertIn("לא נשמרה", why)
        self.assertIsNone(H.conv_audio(999)[0])

    def test_http(self):
        cfg = H.config(); cfg["token"] = "tk"; H._write_config(cfg)

        class Remote(H.Handler):
            def _local(self):
                return False
        from http.server import ThreadingHTTPServer
        srv = ThreadingHTTPServer(("127.0.0.1", 0), Remote)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}/home/audio/conv/"
        try:
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(base + "7.m4a")
            with urllib.request.urlopen(urllib.request.Request(base + "7.m4a", headers={"X-Home-Token": "tk"})) as r:
                self.assertEqual(r.headers["Content-Type"], "audio/mp4")
                self.assertIn("conversation-2026-10-20-0930.m4a", r.headers["Content-Disposition"])
                self.assertGreater(len(r.read()), 1000)
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(urllib.request.Request(base + "999.m4a", headers={"X-Home-Token": "tk"}))
            self.assertEqual(e.exception.code, 404)
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main()
