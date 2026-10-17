"""2026-10-17 UX phase 4: recording on the PC itself (pc_record.py + /home/api/pc_rec), with fake audio sources."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import wave

import numpy as np

_TMP = tempfile.mkdtemp(prefix="shema_pcrec_")
os.environ["SHEMA_DATA"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import home_listener as H      # noqa: E402
import pc_record as P          # noqa: E402


class FakeSource:
    """A device that delivers a sine (mic 220 Hz, system 440 Hz) in real time, or fails on open / on read."""
    opened = []
    fail_open = set()
    fail_after = {}

    def __init__(self, kind):
        if kind in FakeSource.fail_open:
            raise RuntimeError("no microphone" if kind == "mic" else "no speakers")
        self.kind, self.name, self.t, self.reads = kind, f"fake {kind}", 0, 0
        FakeSource.opened.append(self)
        self.closed = False

    def read(self, n):
        self.reads += 1
        if self.reads > FakeSource.fail_after.get(self.kind, 10 ** 9):
            raise RuntimeError("device unplugged")
        time.sleep(n / P.SR / 20)               # 20x faster than real time
        f = 220 if self.kind == "mic" else 440
        a = 0.3 * np.sin(2 * np.pi * f * (np.arange(n) + self.t) / P.SR)
        self.t += n
        return a.astype(np.float32)

    def close(self):
        self.closed = True


def read_wav(raw):
    with wave.open(io.BytesIO(raw)) as w:
        return w.getnchannels(), w.getframerate(), w.getnframes()


class RecorderTests(unittest.TestCase):
    def setUp(self):
        FakeSource.opened, FakeSource.fail_open, FakeSource.fail_after = [], set(), {}
        self.dir = Path(tempfile.mkdtemp(prefix="rec_", dir=_TMP))
        self.got = []
        self.r = P.Recorder(self.store, self.dir, source_factory=FakeSource, chunk_s=1, log=lambda *_: None)

    def store(self, raw, st):
        self.got.append((raw, st))
        return len(self.got)

    def wait(self, cond, timeout=5):
        end = time.time() + timeout
        while time.time() < end and not cond():
            time.sleep(0.01)
        self.assertTrue(cond())

    def test_chunks_mono_and_stop(self):
        st = self.r.start("mic")
        self.assertEqual(st["state"], "recording")
        self.wait(lambda: len(self.got) >= 2)
        out = self.r.stop()
        self.assertEqual(out["state"], "idle")
        self.assertGreaterEqual(out["chunks"], 2)
        ch, sr, n = read_wav(self.got[0][0])
        self.assertEqual((ch, sr, n), (1, 16000, 16000))          # 1 s chunks, mono, 16 kHz
        self.assertTrue(all(s.closed for s in FakeSource.opened))
        self.assertEqual(list(self.dir.glob("partial_*")), [])    # nothing left half-written
        starts = [s for _, s in self.got]
        self.assertEqual(starts, sorted(starts))

    def test_both_is_two_channels(self):
        self.r.start("both")
        self.wait(lambda: self.got)
        self.r.stop()
        raw = self.got[0][0]
        self.assertEqual(read_wav(raw)[0], 2)
        with wave.open(io.BytesIO(raw)) as w:
            a = np.frombuffer(w.readframes(w.getnframes()), "<i2").reshape(-1, 2).astype(float)
        # left = microphone (220 Hz), right = system audio (440 Hz): kept apart, not mixed
        for col, f in ((0, 220), (1, 440)):
            spec = np.abs(np.fft.rfft(a[:, col]))
            self.assertAlmostEqual(np.argmax(spec) * 16000 / len(a), f, delta=3)

    def test_pause_resume_releases_the_device(self):
        self.r.start("mic")
        self.wait(lambda: self.r.status()["seconds"] > 0.3)
        self.assertEqual(self.r.pause()["state"], "paused")
        self.assertTrue(FakeSource.opened[0].closed)                # the microphone is free while paused
        n = len(self.got)
        self.assertGreaterEqual(n, 1)                               # pause closes the running chunk
        sec = self.r.status()["seconds"]
        time.sleep(0.2)
        self.assertEqual(self.r.status()["seconds"], sec)           # paused time is not recorded
        self.assertEqual(self.r.resume()["state"], "recording")
        self.assertEqual(len(FakeSource.opened), 2)
        self.wait(lambda: self.r.status()["seconds"] > sec + 0.7)     # more than the half second a chunk needs
        self.r.stop()
        self.assertGreater(len(self.got), n)

    def test_no_mic(self):
        FakeSource.fail_open = {"mic"}
        st = self.r.start("both")
        self.assertEqual(st["state"], "idle")
        self.assertIn("מיקרופון", st["error"])
        self.assertTrue(all(s.closed or s.kind != "system" for s in FakeSource.opened) or not FakeSource.opened)
        self.assertEqual(self.r.start("nonsense")["error"], "מקור לא מוכר")

    def test_device_lost_keeps_what_was_recorded(self):
        FakeSource.fail_after = {"system": 15}                      # 1.5 s, then unplugged
        self.r.start("system")
        self.wait(lambda: self.r.state == "idle")
        st = self.r.status()
        self.assertIn("ההקלטה נכשלה", st["error"])
        total = sum(read_wav(raw)[2] for raw, _ in self.got)
        self.assertEqual(total, 15 * 1600)

    def test_one_recording_at_a_time(self):
        self.r.start("mic")
        self.assertEqual(self.r.start("system")["error"], "כבר מקליט")
        self.assertEqual(self.r.probe("system")["ok"], False)
        self.r.stop()

    def test_max_duration(self):
        r = P.Recorder(self.store, self.dir, source_factory=FakeSource, chunk_s=1, max_s=0.5, log=lambda *_: None)
        r.start("mic")
        self.wait(lambda: r.state == "idle")
        self.assertIn("נעצר אוטומטית", r.status()["note"])

    def test_recover_after_crash(self):
        # what a crash leaves: a partial file with its sidecar, never turned into a chunk
        p = self.dir / "partial_20261017T101500_000000.pcm"
        p.write_bytes((np.zeros(16000 * 2, "<i2")).tobytes())
        p.with_suffix(".json").write_text(json.dumps({"start": "2026-10-17T10:15:00", "channels": 2}), encoding="utf-8")
        tiny = self.dir / "partial_20261017T101600_000000.pcm"       # under half a second: dropped, not stored
        tiny.write_bytes(b"\0" * 1000)
        self.assertEqual(self.r.recover(), [1])
        self.assertEqual(read_wav(self.got[0][0])[:2], (2, 16000))
        self.assertEqual(self.got[0][1].isoformat(), "2026-10-17T10:15:00")
        self.assertEqual(list(self.dir.glob("partial_*")), [])

    def test_probe_levels(self):
        r = self.r.probe("both", seconds=0.3)
        self.assertTrue(r["ok"])
        self.assertAlmostEqual(r["sources"]["mic"]["db"], -10.5, delta=0.3)     # 0.3 peak = -10.5 dBFS
        FakeSource.fail_open = {"mic"}
        r = self.r.probe("both", seconds=0.3)
        self.assertFalse(r["ok"])
        self.assertTrue(r["sources"]["system"]["ok"])


class ServerTests(unittest.TestCase):
    """The PC's chunks go into the same queue as a phone's: chunks table, device "pc", at home."""

    @classmethod
    def setUpClass(cls):
        H.config()
        H.migrate()
        FakeSource.opened, FakeSource.fail_open, FakeSource.fail_after = [], set(), {}
        H.PCREC = None
        r = H.pcrec()
        r.factory, r.chunk_s = FakeSource, 1
        r.log = lambda *_: None

    def test_consent_needed(self):
        out = H.pc_rec_action({"action": "start", "source": "mic"})
        self.assertIn("יודעים", out["error"])
        self.assertEqual(H.PCREC.state, "idle")

    def test_chunks_join_the_pipeline(self):
        with H.db() as c:
            c.execute("DELETE FROM chunks")
        out = H.pc_rec_action({"action": "start", "source": "system", "consent": True})
        self.assertEqual(out["state"], "recording")
        self.assertEqual(H.pc_rec_status()["state"], "recording")
        end = time.time() + 5
        while time.time() < end and not H.PCREC.chunks:
            time.sleep(0.02)
        out = H.pc_rec_action({"action": "stop"})
        self.assertEqual(out["state"], "idle")
        with H.db() as c:
            rows = c.execute("SELECT * FROM chunks ORDER BY id").fetchall()
        self.assertGreaterEqual(len(rows), 1)
        for row in rows:
            self.assertEqual((row["device"], row["status"], row["kind"], row["ctx"], row["away"]), ("pc", "new", "speech", "home", 0))
            self.assertTrue(row["file"].endswith("_pc.wav") and os.path.exists(row["file"]))
            self.assertEqual(read_wav(Path(row["file"]).read_bytes())[:2], (1, 16000))

    def test_unknown_action(self):
        self.assertEqual(H.pc_rec_action({"action": "explode"})["error"], "פעולה לא מוכרת")

    def test_http_local_only(self):
        """POST only from this PC; GET tells the screen whether it may steer."""
        from http.server import ThreadingHTTPServer
        import urllib.request
        srv = ThreadingHTTPServer(("127.0.0.1", 0), H.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        try:
            g = json.loads(urllib.request.urlopen(base + "/home/api/pc_rec").read())
            self.assertTrue(g["local"])
            self.assertIn("devices", g)
            self.assertEqual(g["rec"]["state"], "idle")
            req = urllib.request.Request(base + "/home/api/pc_rec", data=json.dumps({"action": "probe", "source": "mic"}).encode(),
                                         headers={"Content-Type": "application/json"})
            self.assertTrue(json.loads(urllib.request.urlopen(req).read())["ok"])
            st = json.loads(urllib.request.urlopen(base + "/home/api/status").read())
            self.assertIn("pc_rec", st)
            self.assertIn("pc_has_mic", st)
            # from another address the same POST is refused
            H.Handler._local_orig = H.Handler._local
            H.Handler._local = lambda self: False
            try:
                with self.assertRaises(urllib.error.HTTPError) as e:
                    urllib.request.urlopen(req)
                self.assertEqual(e.exception.code, 403)
            finally:
                H.Handler._local = H.Handler._local_orig
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
