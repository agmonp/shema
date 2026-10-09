# -*- coding: utf-8 -*-
r"""home_songs.py -- which song was playing. OPTIONAL and ONLINE: runs only with config.json "song_lookup": true
and the optional package shazamio installed (pip install shazamio).

shazamio computes the Shazam acoustic signature ON THIS PC and sends only that signature (not the
audio) to Shazam's service; no account. One lookup per music stretch: the clip is the 12 s with the
most music in it. Results are cached per stretch; failures (offline, not found) are quiet.

    python -X utf8 home_songs.py FILE      # try one file
"""
import asyncio, json, sys, tempfile, time
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 16000
CLIP_S = 12
MIN_GAP_S = 120          # at most one lookup per 2 minutes (a song lasts ~3)
_last = {"t": 0.0, "song": None}


def identify(wave):
    """-> {"title", "artist", "url"} or None. wave: 16 kHz mono float32, >= 5 s of music."""
    from shazamio import Shazam
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "clip.wav"
        sf.write(f, wave, SR)

        async def go():
            return await Shazam().recognize(str(f))
        try:
            r = asyncio.run(go())
        except Exception:
            return None
    tr = (r or {}).get("track") or {}
    if not tr.get("title"):
        return None
    return {"title": tr.get("title"), "artist": tr.get("subtitle"), "url": tr.get("url")}


def song_for(audio, music_windows, now_s=None):
    """music_windows: [(t0, t1, score)] music events of this recording. Picks the strongest 12 s and
    asks Shazam, unless a lookup happened in the last MIN_GAP_S seconds (then reuses that answer)."""
    if not music_windows:
        return None
    now_s = now_s if now_s is not None else time.time()
    if now_s - _last["t"] < MIN_GAP_S:
        return _last["song"]
    t0, t1, _ = max(music_windows, key=lambda w: (w[2], w[1] - w[0]))
    mid = (t0 + t1) / 2
    a = int(max(0, mid - CLIP_S / 2) * SR)
    clip = audio[a:a + CLIP_S * SR]
    if len(clip) < 5 * SR:
        return None
    _last["t"] = now_s
    _last["song"] = identify(clip.astype(np.float32))
    return _last["song"]


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import voice_embed as VE
    for f in sys.argv[1:]:
        a = VE.read_audio(f, max_s=600)
        print(f, json.dumps(identify(a[: CLIP_S * SR]), ensure_ascii=False))
