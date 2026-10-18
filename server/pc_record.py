# -*- coding: utf-8 -*-
r"""pc_record.py -- recording on the PC itself, without a phone (UX phase 4).

Sources: the microphone, the system audio (what the PC plays: WASAPI loopback of the default speakers), or both.
"both" is kept as two channels in one file (left = microphone, right = system audio), so a later step can
tell the user's side from the other side; the analysis reads every file as mono (ffmpeg -ac 1 mixes them).

The recording runs in the server process, not in the browser: closing or crashing the browser does not stop or
lose it. Samples are appended to a partial file on disk every BLOCK_S, so a PC crash loses at most that much;
leftover partial files become normal chunks the next time the server starts (recover()).
Every CHUNK_S seconds, and at pause / stop, the partial file becomes one WAV chunk handed to store(raw, start),
which the server points at store_chunk(..., device "pc"): the same queue as a phone chunk.

Capture uses the "soundcard" package (WASAPI through cffi). Tests pass a fake source factory instead.
"""
import io, json, math, threading, time, wave
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

SR = 16000
BLOCK_S = 0.1               # one read from each source; also how often the partial file is written
CHUNK_S = 30                # one chunk for the pipeline (the analysis reads up to 150 s of a file)
MAX_HOURS = 4               # a forgotten recording stops by itself (config "pc_rec_max_hours")
SOURCES = ("mic", "system", "both")
NAMES = {"mic": "מיקרופון", "system": "שמע המחשב", "both": "מיקרופון + שמע המחשב"}


_TLS = threading.local()


def _sc():
    """soundcard, with COM ready in this thread: it initialises COM only in the thread that imports it, and the HTTP
    server answers every request in a new thread (else: "Error 0x800401f0", CO_E_NOTINITIALIZED)."""
    import soundcard                                              # first: its import fails if COM is already set up here
    if not getattr(_TLS, "com", False):
        try:
            import ctypes
            ctypes.windll.ole32.CoInitializeEx(None, 0)          # COINIT_MULTITHREADED, like soundcard itself
        except (AttributeError, OSError):
            pass                                                  # not Windows
        _TLS.com = True
    return soundcard


def mic_privacy():
    """Windows' microphone switch (Settings > Privacy > Microphone) for the whole PC and for desktop apps.
    -> "allowed" / "denied" / "unknown" (read only; this never changes the setting)."""
    try:
        import winreg
    except ImportError:
        return "unknown"
    base = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"
    out = "allowed"
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for sub in (base, base + r"\NonPackaged"):
            try:
                with winreg.OpenKey(root, sub) as k:
                    if str(winreg.QueryValueEx(k, "Value")[0]).lower() == "deny":
                        return "denied"
            except OSError:
                continue
    return out


def devices():
    """What this PC can record from now. Never raises: a missing package or device is reported, not thrown."""
    out = {"mic": None, "system": None, "privacy": mic_privacy(), "error": None}
    try:
        sc = _sc()
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"soundcard missing: {exc!r}"
        return out
    try:
        out["mic"] = sc.default_microphone().name
    except Exception:  # noqa: BLE001   no microphone connected / enabled
        mics = [m for m in sc.all_microphones() if not getattr(m, "isloopback", False)]
        out["mic"] = mics[0].name if mics else None
    try:
        out["system"] = sc.default_speaker().name
    except Exception:  # noqa: BLE001
        out["system"] = None
    return out


class _Source:
    """One capture device, read in fixed blocks of mono float32 at SR."""

    def __init__(self, kind):
        sc = _sc()
        if kind == "mic":
            try:
                dev = sc.default_microphone()
            except Exception:  # noqa: BLE001
                mics = [m for m in sc.all_microphones() if not getattr(m, "isloopback", False)]
                if not mics:
                    raise RuntimeError("no microphone")
                dev = mics[0]
        else:
            spk = sc.default_speaker()
            dev = sc.get_microphone(spk.id, include_loopback=True)
        self.name = dev.name
        self._ctx = dev.recorder(samplerate=SR, channels=1, blocksize=int(SR * BLOCK_S))
        self._rec = self._ctx.__enter__()

    def read(self, n):
        a = np.asarray(self._rec.record(numframes=n), np.float32)
        a = a[:, 0] if a.ndim == 2 else a
        if len(a) < n:
            a = np.pad(a, (0, n - len(a)))
        return a[:n]

    def close(self):
        try:
            self._ctx.__exit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass


def _db(a):
    p = float(np.max(np.abs(a))) if len(a) else 0.0
    return round(20 * math.log10(p), 1) if p > 1e-5 else None


def wav_bytes(pcm16, channels):
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm16)
    return b.getvalue()


def _parse_iso(s):
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


class Recorder:
    """state: idle -> recording <-> paused -> idle. One recording at a time.

    store(raw_wav_bytes, start_datetime) -> chunk id; called from the capture thread for every finished chunk."""

    def __init__(self, store, folder, source_factory=None, chunk_s=CHUNK_S, max_s=MAX_HOURS * 3600, log=print):
        self.store, self.folder = store, Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.factory = source_factory or _Source
        self.chunk_s, self.max_s, self.log = chunk_s, max_s, log
        self.lock = threading.Lock()
        self.state, self.source, self.error, self.note = "idle", None, None, None
        self.started = None                 # the whole recording
        self.recorded_s = 0.0               # seconds captured (pauses excluded)
        self.chunks, self.levels, self.names = [], {}, {}
        self._thread, self._want = None, None   # _want: "run" / "pause" / "stop"
        self._part = None                   # (path, meta) of the chunk being written
        self.meet = None                    # meeting id (UX phase 5): every chunk of this recording belongs to it

    # ------------------------------------------------------------- control (called from the HTTP threads)
    def start(self, source, meet=None):
        if source not in SOURCES:
            return self.status(error="מקור לא מוכר")
        with self.lock:
            if self.state != "idle":
                return self.status(error="כבר מקליט")
            kinds = ["mic", "system"] if source == "both" else [source]
            try:
                opened = [self.factory(k) for k in kinds]
            except Exception as exc:  # noqa: BLE001
                return self.status(error=_why(exc, source))
            self.source, self.error, self.note, self.meet = source, None, None, meet
            self.started, self.recorded_s, self.chunks, self.levels = datetime.now(), 0.0, [], {}
            self.names = {k: getattr(s, "name", k) for k, s in zip(kinds, opened)}
            self.state, self._want = "recording", "run"
            self._thread = threading.Thread(target=self._run, args=(kinds, opened), daemon=True, name="pc-rec")
            self._thread.start()
        self.log(f"pc_rec: start {source} {self.names}")
        return self.status()

    def pause(self):
        with self.lock:
            if self.state == "recording":
                self._want = "pause"
        return self._wait_for("paused")

    def resume(self):
        with self.lock:
            if self.state == "paused":
                self._want = "run"
        return self._wait_for("recording")

    def stop(self):
        with self.lock:
            if self.state in ("recording", "paused"):
                self._want = "stop"
            t = self._thread
        if t:
            t.join(timeout=10)
        return self.status()

    def _wait_for(self, st, timeout=5):
        end = time.time() + timeout
        while time.time() < end and self.state != st and self.state != "idle":
            time.sleep(0.02)
        return self.status()

    def status(self, error=None):
        return {"state": self.state, "source": self.source, "source_name": NAMES.get(self.source),
                "devices": self.names, "started": self.started.isoformat(timespec="seconds") if self.started else None,
                "seconds": round(self.recorded_s, 1), "chunks": len(self.chunks), "levels": dict(self.levels),
                "error": error or self.error, "note": self.note, "chunk_s": self.chunk_s, "meet": self.meet}

    # ------------------------------------------------------------- capture thread
    def _run(self, kinds, opened):
        n = int(SR * BLOCK_S)
        srcs = opened
        try:
            if self.factory is _Source:
                _sc()                                             # COM in this thread too (the reads call WASAPI)
            while True:
                want = self._want
                if want == "stop":
                    break
                if want == "pause":
                    self._finish()
                    for s in srcs:
                        s.close()
                    srcs = []
                    self.state, self.levels = "paused", {}
                    while self._want == "pause":
                        time.sleep(0.05)
                    if self._want == "stop":
                        break
                    srcs = [self.factory(k) for k in kinds]      # the microphone is really released while paused
                    self.state = "recording"
                    continue
                blocks = [s.read(n) for s in srcs]
                self.levels = {k: _db(b) for k, b in zip(kinds, blocks)}
                frames = np.stack(blocks, 1) if len(blocks) > 1 else blocks[0][:, None]
                self._append(frames, len(kinds))
                self.recorded_s += BLOCK_S
                if self._part and self._part[1]["frames"] >= self.chunk_s * SR:
                    self._finish()
                if self.recorded_s >= self.max_s:
                    self.note = f"נעצר אוטומטית אחרי {self.max_s / 3600:g} שעות"
                    break
        except Exception as exc:  # noqa: BLE001   a device unplugged mid-recording: keep what was recorded
            self.error = _why(exc, self.source)
            self.log(f"pc_rec: capture stopped {exc!r}")
        finally:
            try:
                self._finish()
            except Exception as exc:  # noqa: BLE001
                self.log(f"pc_rec: last chunk failed {exc!r}")
            for s in srcs:
                s.close()
            self.state, self._want, self.levels = "idle", None, {}
            self.log(f"pc_rec: stopped after {self.recorded_s:.0f} s, {len(self.chunks)} chunks")

    def _append(self, frames, channels):
        if self._part is None:
            st = datetime.now() - timedelta(seconds=BLOCK_S)      # the first block was recorded just before now
            p = self.folder / f"partial_{st.strftime('%Y%m%dT%H%M%S_%f')}.pcm"
            meta = {"start": st.isoformat(), "channels": channels, "source": self.source, "frames": 0, "meet": self.meet}
            p.with_suffix(".json").write_text(json.dumps(meta), encoding="utf-8")
            self._part = (p, meta)
        p, meta = self._part
        pcm = (np.clip(frames, -1, 1) * 32767).astype("<i2").tobytes()
        with open(p, "ab") as f:
            f.write(pcm)
            f.flush()
        meta["frames"] += len(frames)

    def _finish(self):
        """The partial file -> one chunk in the pipeline (start time = its first sample)."""
        if self._part is None:
            return
        p, meta = self._part
        self._part = None
        cid = self._store_file(p, meta)
        if cid is not None:
            self.chunks.append(cid)

    def _store_file(self, p, meta):
        pcm = p.read_bytes() if p.exists() else b""
        ch = int(meta.get("channels") or 1)
        pcm = pcm[:len(pcm) - len(pcm) % (2 * ch)]
        cid = None
        if len(pcm) >= 2 * ch * SR // 2:                          # under half a second: nothing worth analysing
            args = (wav_bytes(pcm, ch), _parse_iso(meta.get("start")) or datetime.now())
            cid = self.store(*args, meta["meet"]) if meta.get("meet") else self.store(*args)   # a crash keeps the meeting too
        p.unlink(missing_ok=True)
        p.with_suffix(".json").unlink(missing_ok=True)
        return cid

    def recover(self):
        """Partial files left by a crash (PC, power, server) -> chunks. Call once at server start."""
        out = []
        for p in sorted(self.folder.glob("partial_*.pcm")):
            try:
                meta = json.loads(p.with_suffix(".json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta = {"start": datetime.strptime(p.stem[8:23], "%Y%m%dT%H%M%S").isoformat(), "channels": 1}
            try:
                cid = self._store_file(p, meta)
                if cid is not None:
                    out.append(cid)
            except Exception as exc:  # noqa: BLE001
                self.log(f"pc_rec: recover {p.name} failed {exc!r}")
        if out:
            self.log(f"pc_rec: recovered {len(out)} chunks after a crash")
        return out

    def probe(self, source, seconds=1.5):
        """Device check before recording: listen a moment and say how loud each source is (dBFS, None = silence)."""
        if self.state != "idle":
            return {"ok": False, "error": "כבר מקליט"}
        kinds = ["mic", "system"] if source == "both" else [source]
        res = {}
        for k in kinds:
            try:
                s = self.factory(k)
            except Exception as exc:  # noqa: BLE001
                res[k] = {"ok": False, "error": _why(exc, k)}
                continue
            try:
                a = np.concatenate([s.read(int(SR * BLOCK_S)) for _ in range(int(seconds / BLOCK_S))])
                res[k] = {"ok": True, "name": getattr(s, "name", k), "db": _db(a)}
            except Exception as exc:  # noqa: BLE001
                res[k] = {"ok": False, "error": _why(exc, k)}
            finally:
                s.close()
        return {"ok": all(r["ok"] for r in res.values()), "sources": res}


SIDE_SILENT_DB = -50         # RMS dBFS under which a channel counts as silent during a line
SIDE_MIC_OVER = 10           # the microphone this much louder than the system audio: the user's side of the call
SIDE_SYS_NEAR = 3            # the system audio at most this much quieter than the microphone: the other side


def _rms_db(a):
    if not len(a):
        return None
    r = float(np.sqrt(np.mean(np.square(a.astype(np.float64)))))
    return 20 * math.log10(r) if r > 1e-6 else -120.0


def channel_sides(path, spans):
    """UX phase 5: for a "both" recording (left = microphone, right = system audio), which side each line came from.
    spans = [(s0, s1) seconds in the file] -> ["mic" | "system" | None, ...]. The system channel is a clean copy of what
    the PC played (the other people on a call); the user's own voice reaches only the microphone. With loudspeakers the
    microphone also hears the other side, but weaker than the clean copy, so: system silent -> "mic"; system about as
    loud as the microphone or louder -> "system"; both loud and the microphone clearly louder -> "mic"; in between
    (talking over each other) -> None, not decided. A mono file -> all None."""
    try:
        with wave.open(str(path), "rb") as w:
            if w.getnchannels() != 2 or w.getsampwidth() != 2:
                return [None] * len(spans)
            sr = w.getframerate()
            a = np.frombuffer(w.readframes(w.getnframes()), "<i2").reshape(-1, 2).astype(np.float32) / 32768
    except (OSError, wave.Error, EOFError, ValueError):
        return [None] * len(spans)
    out = []
    for s0, s1 in spans:
        seg = a[max(0, int(float(s0) * sr)):max(0, int(float(s1) * sr))]
        mic, sysd = _rms_db(seg[:, 0]), _rms_db(seg[:, 1])
        if mic is None:
            out.append(None)
        elif sysd < SIDE_SILENT_DB:
            out.append("mic" if mic >= SIDE_SILENT_DB else None)
        elif mic < SIDE_SILENT_DB or sysd >= mic - SIDE_SYS_NEAR:
            out.append("system")
        elif mic - sysd >= SIDE_MIC_OVER:
            out.append("mic")
        else:
            out.append(None)
    return out


def _why(exc, source):
    """A reason the user can act on."""
    s = repr(exc)
    if "no microphone" in s or "0x80070490" in s:
        return "אין מיקרופון מחובר למחשב (או שהוא מושבת בהגדרות הקול של Windows)"
    if "0x80070005" in s or "denied" in s.lower():
        return "Windows חוסם גישה למיקרופון: הגדרות > פרטיות ואבטחה > מיקרופון > לאפשר לאפליקציות שולחן עבודה"
    if "soundcard" in s or "No module" in s:
        return "חסרה ספריית ההקלטה (soundcard): להריץ שוב את ההתקנה"
    return f"ההקלטה נכשלה ({source}): {s[:120]}"
