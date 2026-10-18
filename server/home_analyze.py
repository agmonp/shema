# -*- coding: utf-8 -*-
r"""home_analyze.py -- the home listener's brain: one audio file -> who said what, how it sounded,
what was heard around it (torch + faster-whisper + sherpa-onnx).

    python -X utf8 home_analyze.py FILE.wav [--year 2026]
prints the analysed conversation as JSON (nothing stored -- home_listener.py stores).

Per utterance (one speaker, consecutive words):
  speaker  the voices the user taught on the screen (+ optional voiceprints.json) or None
  prosody  NumPy acoustic estimates: pitch, relative intensity, syllable rate, voiced share
  emotion  unavailable in this distribution; no inferred emotion numbers are fabricated
Whole file:
  sounds   AST AudioSet tags per 5 s window (laughter, crying, TV, music, dog, shouting ...)
  dynamics talk share, turns, overlaps (word times of different speakers cross), interruptions
           (a turn that starts while the other is mid-utterance and the other stops < 1 s later),
           response gaps
"""
import argparse, json, os, re, sys, time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

PROJ = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJ))
from paths import VOICE, CONFIG, device as _device  # noqa: E402
from audio_features import prosody  # noqa: E402

SR = 16000
SIM_MIN, MARGIN = 0.45, 0.12          # a voice is named only when it is this close and beats the runner-up by MARGIN
WHISPER_MODEL = "ivrit-ai/whisper-large-v3-turbo-ct2"      # default; config.json "whisper_model" overrides (asr_update.py)


def home_config():
    """config.json in the data folder; {} when unreadable."""
    try:
        return json.load(open(CONFIG, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def household():
    """config.json "household": person ids that are always candidates (the owner is added)."""
    cfg = home_config()
    return list(dict.fromkeys([cfg.get("owner") or "owner"] + list(cfg.get("household") or [])))


def asr_prompt(cfg=None):
    """Recurring words (names, professional terms; the user edits "asr_terms" in config.json) nudge
    Whisper toward the right spelling, in Hebrew or in Latin letters."""
    import asr_correct
    terms = asr_correct.prompt_terms(cfg or home_config())    # asr_terms + glossary terms (asr_correct.py)
    return ", ".join(terms[:60]) if terms else None      # no header word: "מונחים:" leaked into the transcript (test 2026-10-09)
SOUND_KEEP = {  # AudioSet label -> our tag (home life)
    "Laughter": "צחוק", "Baby laughter": "צחוק", "Giggle": "צחוק", "Chuckle, chortle": "צחוק",
    "Crying, sobbing": "בכי", "Baby cry, infant cry": "בכי", "Whimper": "בכי",
    "Screaming": "צעקה", "Shout": "צעקה", "Yell": "צעקה", "Children shouting": "צעקות ילדים",
    "Singing": "שירה", "Music": "מוזיקה", "Television": "טלוויזיה", "Radio": "רדיו",
    "Dog": "כלב", "Bark": "כלב", "Cat": "חתול", "Dishes, pots, and pans": "כלים", "Cutlery, silverware": "כלים",
    "Door": "דלת", "Knock": "דפיקה", "Doorbell": "פעמון", "Vacuum cleaner": "שואב אבק",
    "Water tap, faucet": "ברז", "Microwave oven": "מיקרוגל", "Blender": "בלנדר", "Telephone bell ringing": "טלפון",
    "Ringtone": "טלפון", "Applause": "מחיאות כפיים", "Snoring": "נחירות", "Cough": "שיעול", "Sneeze": "התעטשות",
    "Typing": "הקלדה", "Video game music": "משחק מחשב", "Vehicle": "רכב", "Siren": "סירנה",
    "Child speech, kid speaking": "דיבור ילדים", "Babbling": "מלמול תינוק",
}
SOUND_MIN = 0.25


class Brain:
    def __init__(self):
        import torch  # noqa: F401  (cublas for CTranslate2)
        self.torch = torch
        import asr_engine
        cfg = home_config()
        self.dev = _device()
        compute = cfg.get("asr_compute") or ("float16" if self.dev == "cuda" else "int8")
        self.asr = asr_engine.Engine(cfg, self.dev, compute)      # config.json "asr": mode / segmentation (legacy default)
        self.model_name = self.asr.model_name
        self.asr.models.get(self.model_name)                      # load now, as before: a broken install fails here
        import voice_embed as VE
        self.VE = VE
        # ORT threads for the speaker embedders. 4 threads spin-wait and burn ~3x the CPU of 1 thread for the same
        # vector (2026-10-15: 291 vs 97 CPU-ms per voice_vec, cos 1.0); 2 = 186 CPU-ms for +3% chunk wall. config.json "spk_threads" tunes it.
        self.ex = VE.load_extractors(["eres2netv2", "titanet"], threads=int(cfg.get("spk_threads") or 2))
        self.prints = defaultdict(list)
        try:                                   # optional: voiceprints prepared outside the app
            meta = json.load(open(VOICE / "voiceprints.json", encoding="utf-8"))["prints"]
            vecs = np.load(VOICE / "voiceprints.npz")["vecs"]
            for p, v in zip(meta, vecs):
                self.prints[p["person_id"]].append((p, v))
        except (OSError, ValueError, KeyError):
            pass
        try:                                   # optional: person_id -> {"name": ...}
            self.names = json.load(open(VOICE / "names.json", encoding="utf-8"))
        except (OSError, ValueError):
            self.names = {}

    def demucs(self):
        if getattr(self, "_demucs", None) is None:
            from demucs.pretrained import get_model
            self._demucs = get_model("htdemucs").to(self.dev).eval()
        return self._demucs

    def unmusic(self, audio):
        """Demucs htdemucs "vocals" stem: removes instruments under the talk (singing stays -- it is a
        voice). In tests it named more speakers over TV + music and kept the TV's words out."""
        import torch
        import torchaudio.functional as AF
        m = self.demucs()
        x = AF.resample(torch.from_numpy(audio).float(), SR, m.samplerate)
        from demucs.apply import apply_model
        with torch.no_grad():
            out = apply_model(m, x[None, None].repeat(1, 2, 1).to(self.dev), split=True, overlap=0.25)[0]
        voc = out[m.sources.index("vocals")].mean(0).cpu()
        y = AF.resample(voc, m.samplerate, SR).numpy().astype(np.float32)
        return y[: len(audio)] if len(y) >= len(audio) else np.pad(y, (0, len(audio) - len(y)))

    def ears(self):
        if getattr(self, "_ears", None) is None:
            import home_sounds
            cfg = home_config()
            self._ears = home_sounds.Ears(device=self.dev, use_clap=cfg.get("clap", self.dev == "cuda"))
        return self._ears

    # ---- pieces
    def transcribe(self, audio, raw=None):
        """Silero speech regions (legacy: gaps < 0.4 s merged, <= 15 s), each decoded ON ITS OWN.
        One pass over the whole file can go silent after an English TV stretch with music, and
        conditioning on the previous text carries the confusion forward. asr_engine.py does the work (the benchmark
        runs the same code); self.asr.trace keeps which model read which window and what looked suspicious."""
        words, _ = self.asr.transcribe(audio, prompt=asr_prompt(), raw=raw)
        return words, "he"

    def voice_vec(self, wave):
        e = [self.VE.embed(self.ex[k], wave) for k in ("eres2netv2", "titanet")]
        return np.concatenate(e) / np.sqrt(2)

    def candidates(self, year, people, bank=None):
        """pid -> list of reference vectors: an optional prepared voiceprint for that year and, when the user
        has labelled phone recordings of that person, their centroid."""
        import voice_speakers as VS
        out = {}
        for pid in dict.fromkeys(list(people or []) + household()):
            if pid in self.prints:
                v = VS.print_for(self.prints[pid], year)
                if v is not None:
                    out[pid] = [v]
        for pid, vecs in (bank or {}).items():
            out.setdefault(pid, []).extend(vecs)
        return out

    def sounds(self, audio, sound_bank=None):
        """CED-base + CLAP + the user's taught sounds (home_sounds.py). Each event carries the mean
        CLAP vector of its windows so the user can later say what it was."""
        ev, vecs, starts = self.ears().listen(audio, sound_bank)
        if vecs is not None:
            for e in ev:
                idx = [i for i, s in enumerate(starts) if e["t0"] - 1e-6 <= s < e["t1"]]
                if idx:
                    v = vecs[idx].mean(axis=0)
                    e["vec"] = (v / (np.linalg.norm(v) + 1e-9)).astype("float32")
        return ev, vecs, starts


from asr_engine import HALLUCINATIONS, hallucination  # noqa: E402,F401  (moved; old imports keep working)


HEB_VOWELISH = re.compile(r"[אהוי]|[^\s]")


def syllables_he(text):
    """Rough Hebrew syllable count: ~ letters / 2.2 (unvocalised text has no vowels to count)."""
    letters = len(re.findall(r"[א-ת]", text))
    latin = len(re.findall(r"[aeiouy]+", text.lower()))
    return max(1, round(letters / 2.2) + latin)


# ------------------------------------------------------------------ TV / music / songs: no need to transcribe
# them, only know what was on. Decided per 3 s chunk, before chunks merge into utterances, so talk over the
# TV stays separate. A chunk is media when the sound tagger hears broadcast/music in it AND the voice is
# nobody we know (a strong known-voice match always wins: that is someone talking over the TV).
MUSIC_HE = {"מוזיקה", "שירה", "שיר", "גיטרה", "פסנתר", "קלידים", "תופים", "כינור", "יוקלילי", "שירי ילדים", "טלוויזיה", "רדיו"}
TV_SPEAKER = "__tv__"       # voice-bank key of what the user marked as TV / radio
TV_TAGS = ("Television", "Radio", "Speech synthesizer")
MUSIC_TAGS = ("Music", "Pop music", "Music for children", "Background music", "Theme music", "Soundtrack music",
              "Video game music", "Jingle (music)", "Christmas music", "Children's music")
SING_TAGS = ("Singing", "Child singing", "Choir", "Male singing", "Female singing", "Rapping")


def latin_share(text):
    he = len(re.findall(r"[א-ת]", text))
    la = len(re.findall(r"[A-Za-z]", text))
    return la / (he + la) if he + la else 0.0


def media_of(B, audio, c, away=False):
    """-> None | 'טלוויזיה' | 'מוזיקה' | 'שיר' for one word chunk (c has s1 when voices were scored)."""
    if c.get("speaker"):
        return None
    mid = (c["t0"] + c["t1"]) / 2
    half = max(c["t1"] - c["t0"], 2.0) / 2
    w = audio[int(max(0, mid - half) * SR):int(min(len(audio) / SR, mid + half) * SR)]
    if len(w) < 0.5 * SR:
        return None
    tags = B.ears().tag(w)
    tv = max(tags.get(t, 0) for t in TV_TAGS)
    music = max(tags.get(t, 0) for t in MUSIC_TAGS)
    sing = max(tags.get(t, 0) for t in SING_TAGS)
    voice = c.get("s1", 0.0)
    latin = latin_share(c["text"])
    c["media_scores"] = {"tv": round(tv, 2), "music": round(music, 2), "sing": round(sing, 2),
                         "voice": round(voice, 2), "latin": round(latin, 2)}
    # Precision first: spoken-language ID is unreliable on phone audio, so it is NOT used.
    # Only strong evidence counts:
    if voice >= 0.5:
        return None                  # close to a known voice
    if latin >= 0.6 and not away:
        return "טלוויזיה"            # Whisper wrote English words: English speech = a show in this home
                                     # (away from home English is people, so the rule is off)
    if sing >= 0.3 and music >= 0.4:
        return "שיר"
    if tv >= 0.4 and voice < 0.35:
        return "טלוויזיה"            # loud broadcast and a voice far from every known voice, even in Hebrew
    if music >= 0.75 and voice < 0.35:
        return "מוזיקה"
    return None


def media_context(ch):
    """Inside a TV stretch (>= 2 media chunks within 60 s), unnamed chunks that also carry broadcast or
    music get the same label (Whisper writes the show's English in Hebrew letters: "סירקל, רפטאגלס")."""
    marks = [i for i, c in enumerate(ch) if c.get("media")]
    for i, c in enumerate(ch):
        if c.get("media") or c.get("speaker") or not c.get("media_scores"):
            continue
        near = [j for j in marks if abs(ch[j]["t0"] - c["t0"]) <= 60]
        sc = c["media_scores"]
        if len(near) >= 2 and sc["voice"] < 0.45 and (sc["tv"] >= 0.15 or sc["music"] >= 0.4):
            kinds = [ch[j]["media"] for j in near]
            c["media"] = max(set(kinds), key=kinds.count)


def best_two(x, cands):
    sims = sorted(((max(float(x @ v) for v in vs), p) for p, vs in cands.items()), reverse=True)
    return sims[0][1], sims[0][0], (sims[1][0] if len(sims) > 1 else -1.0)


def utterances(B, audio, words, cands, names=None, raw=None, away=False, people_only=False):
    """words -> chunks (pause >= 0.35 s / 3 s max) -> speaker per chunk -> merged utterances.
    audio = what voices / prosody / emotion are read from (music removed when there was music);
    raw   = the recording as heard (the TV / music / song decision needs the music);
    people_only = a meeting recorded on the PC: what the PC plays IS the other side of the call, so nothing is TV."""
    raw = audio if raw is None else raw
    import voice_speakers as VS
    ch = VS.chunks_of(words)
    vecs = {}       # (a0, a1) -> voice vector: an utterance made of one chunk reads the chunk's window again (CPU, 2026-10-15)

    def vec_at(a0, a1):
        if (a0, a1) not in vecs:
            vecs[(a0, a1)] = B.voice_vec(audio[a0:a1])
        return vecs[(a0, a1)]

    for c in ch:
        mid, half = (c["t0"] + c["t1"]) / 2, max(c["t1"] - c["t0"], 1.0) / 2
        a0, a1 = int(max(0, mid - half) * SR), int(min(len(audio) / SR, mid + half) * SR)
        c["speaker"] = None
        if cands and a1 - a0 >= 0.5 * SR:
            x = vec_at(a0, a1)
            c["best"], c["s1"], c["s2"] = best_two(x, cands)
            if c["s1"] >= SIM_MIN and c["s1"] - c["s2"] >= MARGIN:
                c["speaker"] = c["best"]
    for c in ch:
        if people_only:                     # a PC meeting: call audio is compressed and often sounds like a broadcast
            c["media"] = None
            if c["speaker"] == TV_SPEAKER:
                c["speaker"] = None
        elif c["speaker"] == TV_SPEAKER:    # matches voices the user marked "this is the TV"
            c["speaker"], c["media"] = None, "טלוויזיה"
            c["media_scores"] = {"taught": round(c["s1"], 2)}
        else:
            c["media"] = media_of(B, raw, c, away)
    media_context(ch)
    for i, c in enumerate(ch):                        # same context fill as voice_speakers
        if c["speaker"] or "best" not in c or c["media"]:
            continue
        prev = next((x for x in reversed(ch[:i]) if x["speaker"]), None)
        nxt = next((x for x in ch[i + 1:] if x["speaker"]), None)
        if prev and nxt and prev["speaker"] == nxt["speaker"] == c["best"] and c["s1"] >= 0.25 \
                and c["t0"] - prev["t1"] < 1.5 and nxt["t0"] - c["t1"] < 1.5:
            c["speaker"] = c["best"]
    U = []
    for c in ch:
        if U and U[-1]["speaker"] == c["speaker"] and U[-1].get("media") == c["media"] and c["t0"] - U[-1]["t1"] < 1.2:
            U[-1]["t1"], U[-1]["text"] = c["t1"], U[-1]["text"] + " " + c["text"]
            U[-1]["words"] += c.get("words") or []
        else:
            U.append({"t0": c["t0"], "t1": c["t1"], "speaker": c["speaker"], "text": c["text"],
                      "how": "voice" if c["speaker"] else ("media" if c["media"] else None), "media": c["media"],
                      "media_scores": c.get("media_scores"), "words": list(c.get("words") or []),
                      "lang": "en" if latin_share(c["text"]) > 0.6 else "he"})
    names = names or {}
    for u in U:
        if u["media"]:                    # not a person: no name, voice, tone or emotion; the words go to
            u["name"], u["emb"] = None, None          # media_text only until the conversation summary
            u["media_text"], u["text"] = u["text"], ""
            u["prosody"] = {}
            continue
        u["name"] = (names.get(u["speaker"]) or B.names.get(u["speaker"], {}).get("name")) if u["speaker"] else None
        wave = audio[int(u["t0"] * SR):int(u["t1"] * SR)]
        # the utterance's own voice vector: lets the user's later "this is X" re-score without the audio
        mid, half = (u["t0"] + u["t1"]) / 2, max(u["t1"] - u["t0"], 1.0) / 2
        a0, a1 = int(max(0, mid - half) * SR), int(min(len(audio) / SR, mid + half) * SR)
        u["emb"] = vec_at(a0, a1).astype("float32") if a1 - a0 >= 0.5 * SR else None
        dur = max(u["t1"] - u["t0"], 0.01)
        u["prosody"] = prosody(wave) if len(wave) >= 0.3 * SR else {}
        u["prosody"]["syll_per_s"] = round(syllables_he(u["text"]) / dur, 2)
        # Unavailable measurements stay absent, so the database stores NULL.
        u["emotion"], u["dims"] = {}, {}
    return U


def dynamics(U):
    talk = Counter()
    for u in U:
        talk[u["name"] or "?"] += u["t1"] - u["t0"]
    tot = sum(talk.values()) or 1
    turns, overlaps, interrupts, gaps = 0, 0, [], []
    for a, b in zip(U, U[1:]):
        if a["speaker"] == b["speaker"]:
            continue
        turns += 1
        gap = b["t0"] - a["t1"]
        if gap < 0:
            overlaps += 1
            if b["t1"] - b["t0"] > 1.0:
                interrupts.append({"who": b["name"] or "?", "cut": a["name"] or "?", "t": b["t0"]})
        else:
            gaps.append(gap)
    return {"talk_share": {k: round(v / tot, 2) for k, v in talk.most_common()},
            "talk_seconds": {k: round(v, 1) for k, v in talk.most_common()},
            "turns": turns, "overlaps": overlaps, "interruptions": interrupts,
            "median_response_gap_s": round(float(np.median(gaps)), 2) if gaps else None}


def unknown_sounds(audio, words, events, vecs, starts, min_db=-38.0):
    """Loud 2 s windows with no speech and no tag -> 'צליל לא מזוהה' events (so the user can teach them)."""
    if vecs is None:
        return []
    out = []
    spoken = [(w[0] - 0.3, w[1] + 0.3) for w in words]
    tagged = [(e["t0"], e["t1"]) for e in events]
    for i, s in enumerate(starts):
        e = s + 2.0
        if any(a < e and s < b for a, b in spoken) or any(a < e and s < b for a, b in tagged):
            continue
        w = audio[int(s * SR):int(e * SR)]
        if len(w) < SR // 2:
            continue
        db = 20 * np.log10(np.sqrt(np.mean(w ** 2)) + 1e-9)
        if db < min_db:
            continue
        if out and s - out[-1]["t1"] <= 1.0:
            out[-1]["t1"] = round(float(e), 1)
            out[-1]["_idx"].append(i)
        else:
            out.append({"tag": "צליל לא מזוהה", "group": "לא מזוהה", "t0": round(float(s), 1), "t1": round(float(e), 1),
                        "score": round(float(db), 1), "source": "loud", "_idx": [i]})
    for o in out:
        v = vecs[o.pop("_idx")].mean(axis=0)
        o["vec"] = (v / (np.linalg.norm(v) + 1e-9)).astype("float32")
    return out[:6]


def asr_annotate(U, trace, cfg=None):
    """ASR 2.0, after the speakers are known (the text never moves between speakers):
    u["asr"]      which model read it, the suspicion flags, uncertain yes / no   (config "asr": {"mark_uncertain"})
    u["text_raw"] the transcript before glossary corrections, only when a correction changed it
    Media utterances (TV / music) are left alone."""
    import asr_correct
    import asr_engine
    cfg = cfg or home_config()
    mark = (cfg.get("asr") or {}).get("mark_uncertain", True) is not False
    for u in U:
        if u.get("media"):
            continue
        info = asr_engine.utterance_info(u, trace) if mark else None
        new, changes, raw = asr_correct.correct(u["text"], cfg)
        if changes and new != raw:
            u["text_raw"], u["text"] = raw, new
            info = dict(info or {}, changes=changes)
        if info:
            u["asr"] = info


SONG_TAGS = {"מוזיקה", "שירה", "שיר", "שירי ילדים", "גיטרה", "פסנתר", "קלידים"}


def analyse(B, path, year=None, people=None, bank=None, names=None, sound_bank=None, kind="speech", when=None,
            songs=True, away=False, people_only=False):
    import voice_embed as VE
    t = time.time()
    audio = VE.read_audio(path, max_s=100000)
    if audio is None or len(audio) < 0.3 * SR:            # cut-off upload (app killed mid-file) / empty
        return {"file": str(path), "seconds": round(len(audio) / SR, 1) if audio is not None else 0,
                "lang": None, "utterances": [], "sounds": [], "dynamics": dynamics([]), "took_s": 0, "empty": True}
    year = year or int(time.strftime("%Y"))
    events, vecs, starts = B.sounds(audio, sound_bank)          # on the recording as heard
    music = any(e["tag"] in MUSIC_HE for e in events)
    voice_audio = B.unmusic(audio) if music else audio
    words, lang = B.transcribe(voice_audio, raw=audio if music else None)
    cands = B.candidates(year, people, bank)
    U = utterances(B, voice_audio, words, cands, names, raw=audio, away=away, people_only=people_only) if words else []
    asr_annotate(U, getattr(B.asr, "trace", None) if hasattr(B, "asr") else None)
    events += unknown_sounds(audio, words, events, vecs, starts)
    # which song: an ONLINE signature lookup (Shazam), so it is off unless config.json "song_lookup": true
    mw = [(e["t0"], e["t1"], e["score"]) for e in events if e["tag"] in SONG_TAGS and e["t1"] - e["t0"] >= 5]
    if songs and mw and home_config().get("song_lookup"):
        try:
            import home_songs
            song = home_songs.song_for(audio, mw, now_s=when)
        except Exception:
            song = None
        if song:
            t0, t1, _ = max(mw, key=lambda w: (w[2], w[1] - w[0]))
            events.append({"tag": f"שיר: {song['title']}" + (f" — {song['artist']}" if song.get("artist") else ""),
                           "group": "מוזיקה", "t0": t0, "t1": t1, "score": 1.0, "source": "shazam"})
    for u in U:
        u["unmusic"] = music
    events.sort(key=lambda e: e["t0"])
    res = {"file": str(path), "seconds": round(len(audio) / SR, 1), "lang": lang, "utterances": U,
           "sounds": events, "dynamics": dynamics(U), "kind": kind}
    res["took_s"] = round(time.time() - t, 1)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--year", type=int)
    ap.add_argument("--people", default="", help="extra person ids (comma separated)")
    ap.add_argument("--out", help="write JSON here")
    args = ap.parse_args()
    B = Brain()
    r = analyse(B, args.file, args.year, [p for p in args.people.split(",") if p])
    for u in r["utterances"]:
        u.pop("emb", None)
    for e in r["sounds"]:
        e.pop("vec", None)
    txt = json.dumps(r, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(txt, encoding="utf-8")
    else:
        print(txt)


if __name__ == "__main__":
    main()
