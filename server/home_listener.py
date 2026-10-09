# -*- coding: utf-8 -*-
r"""home_listener.py -- Shema's PC side (server).

  * receives speech chunks from the phone app on the home network (or over Tailscale):
        POST /home/api/chunk?device=ID&start=ISO8601   body = audio (Ogg Opus from the app; m4a / wav too)
        header X-Home-Token: <token from config.json>
  * stores them (%LOCALAPPDATA%\Shema\data\audio\<day>\), queues them, analyses each one (home_analyze.Brain),
    and groups utterances into conversations (gap < CONV_GAP s)
  * summaries (local model in Ollama, text + numbers only): a provisional one while a conversation is
    still going (every SUMMARY_EVERY new utterances), the final one when it ends, and a day summary
  * teaching: the user says on the PC who spoke (POST /home/api/label, this PC only). The
    utterance's voice vector goes to the voice bank; every unnamed utterance of the last
    RESCORE_DAYS days is re-scored at once, and new recordings use the bank from then on
  * keeps raw audio by config.json "audio_policy" (default "archive"), text + numbers forever
  * serves the screen: GET /home (ui/home.html), /home/api/..., /home/app.apk

    python -X utf8 home_listener.py                 # serve on :8770
    python -X utf8 home_listener.py --ingest FILE --start 2026-10-06T18:00:00
"""
import argparse, json, os, re, secrets, sqlite3, subprocess, sys, threading, time

# Started windowless (pythonw, logon task): without this every ffmpeg child opens its own console
# window that never closes.
_popen_init = subprocess.Popen.__init__


def _popen_no_window(self, *a, **kw):
    if os.name == "nt":
        kw["creationflags"] = (kw.get("creationflags") or 0) | 0x08000000   # CREATE_NO_WINDOW
    _popen_init(self, *a, **kw)


subprocess.Popen.__init__ = _popen_no_window
import urllib.parse
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

PROJ = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJ))
import paths  # noqa: E402

HOME = paths.DATA                     # %LOCALAPPDATA%\Shema\data (SHEMA_DATA / HOME_DATA: tests use a scratch folder)
AUDIO = HOME / "audio"
DB = HOME / "home.sqlite"
CONFIG = paths.CONFIG
PAGE = PROJ / "ui" / "home.html"
VOICE = paths.VOICE
PORT = int(os.getenv("HOME_PORT") or os.getenv("SHEMA_PORT") or "8770")
CONV_GAP = 90             # s of silence that ends a conversation
AUDIO_DAYS = 14          # policy "days" only
# Audio policy (config.json "audio_policy"; the installer sets "archive"):
#   "teach"           -- delete a recording right after analysis, unless it holds an unnamed voice or an
#                        unidentified sound: those stay TEACH_DAYS days so the user can listen and teach,
#                        and go as soon as everything in them is named
#   "none"            -- delete every recording right after analysis
#   "days"            -- keep everything audio_days days (the first version)
#   "archive"         -- keep a small archive: processed speech / imports are converted to
#                        Opus 12 kbps mono (~5.4 MB per hour) and kept; sounds go as soon as nothing in them needs
#                        teaching (or after teach_days); enrolment recordings go after processing; keep=1 never goes.
#                        Text, speakers, tone, sound tags and voice vectors are kept in every policy.
#   "keep"            -- never delete automatically (the screen shows the space used, deleting is manual)
# Text, voice/sound vectors (not reversible to sound), tone and emotion numbers are always kept.
TEACH_DAYS = 3
MAX_BODY = 40 * 1024 * 1024
SUMMARY_MODEL = os.getenv("HOME_SUMMARY_MODEL", "")      # empty: config.json "summary_model" (installer), else gemma3:4b
SUMMARY_EVERY = 6         # new utterances before the provisional summary of a running conversation is redone
RESCORE_DAYS = 30
OWNER = "owner"           # the person id of the PC's owner (the main voice); named at install time
SIGNALS = ["חום", "הומור", "משחק", "ויכוח", "תסכול", "כעס", "תיקון", "הקשבה", "תכנון", "למידה", "עייפות", "התרגשות"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (id INTEGER PRIMARY KEY, device TEXT, start TEXT, seconds REAL,
    file TEXT, status TEXT, error TEXT, keep INTEGER DEFAULT 0, received TEXT, analysed TEXT, took REAL);
CREATE TABLE IF NOT EXISTS conversations (id INTEGER PRIMARY KEY, start TEXT, end TEXT, seconds REAL,
    people TEXT, talk_seconds TEXT, turns INTEGER, overlaps INTEGER, interruptions TEXT,
    mood_valence REAL, mood_arousal REAL, sounds TEXT, topic TEXT, summary TEXT, moments TEXT,
    status TEXT);
CREATE TABLE IF NOT EXISTS utterances (id INTEGER PRIMARY KEY, chunk_id INTEGER, conv_id INTEGER,
    t0 TEXT, t1 TEXT, seconds REAL, speaker TEXT, name TEXT, text TEXT,
    f0_hz REAL, f0_range_st REAL, intensity_db REAL, syll_per_s REAL, voiced_share REAL,
    emotion TEXT, emotion_p REAL, emotion_scores TEXT, arousal REAL, dominance REAL, valence REAL);
CREATE TABLE IF NOT EXISTS sounds (id INTEGER PRIMARY KEY, chunk_id INTEGER, conv_id INTEGER,
    t0 TEXT, t1 TEXT, tag TEXT, score REAL);
CREATE TABLE IF NOT EXISTS voice_bank (id INTEGER PRIMARY KEY, speaker TEXT, utt_id INTEGER, vec BLOB, created TEXT);
CREATE TABLE IF NOT EXISTS home_people (id TEXT PRIMARY KEY, name TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS sound_bank (id INTEGER PRIMARY KEY, tag TEXT, sound_id INTEGER, vec BLOB, created TEXT);
CREATE TABLE IF NOT EXISTS daily (day TEXT PRIMARY KEY, summary TEXT, highlights TEXT, mood TEXT,
    conversations INTEGER, updated TEXT, model TEXT);
CREATE TABLE IF NOT EXISTS marks (id INTEGER PRIMARY KEY, t TEXT, device TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS places (id INTEGER PRIMARY KEY, name TEXT, lat REAL, lon REAL, r_m REAL DEFAULT 150,
    mute INTEGER DEFAULT 0, created TEXT);
CREATE TABLE IF NOT EXISTS dropped (id INTEGER PRIMARY KEY, day TEXT, ctx TEXT, reason TEXT, seconds REAL, utterances INTEGER,
    at TEXT);
CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY, conv_id INTEGER, who TEXT, what TEXT, due TEXT, quote TEXT,
    state TEXT DEFAULT 'open', created TEXT);
CREATE TABLE IF NOT EXISTS phone_timeline (device TEXT, s TEXT, e TEXT, reason TEXT, detail TEXT, received TEXT,
    PRIMARY KEY (device, s));
CREATE TABLE IF NOT EXISTS teach_skips (utt_id INTEGER PRIMARY KEY, reason TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS imports (path TEXT PRIMARY KEY, mtime REAL, chunk_id INTEGER);
CREATE VIRTUAL TABLE IF NOT EXISTS conv_fts USING fts5(conv_id UNINDEXED, topic, people, body,
    tokenize='porter unicode61 remove_diacritics 2');
CREATE INDEX IF NOT EXISTS u_conv ON utterances(conv_id);
CREATE INDEX IF NOT EXISTS u_t0 ON utterances(t0);
CREATE INDEX IF NOT EXISTS s_t0 ON sounds(t0);
CREATE INDEX IF NOT EXISTS c_status ON chunks(status);
"""
MIGRATIONS = [   # columns added after the first version (2026-10-06 afternoon)
    ("utterances", "emb", "BLOB"), ("utterances", "how", "TEXT"), ("utterances", "score", "REAL"),
    ("conversations", "summary_n", "INTEGER"), ("conversations", "mood_text", "TEXT"),
    ("conversations", "per_person", "TEXT"), ("conversations", "signals", "TEXT"),
    ("conversations", "summary_model", "TEXT"),
    ("sounds", "grp", "TEXT"), ("sounds", "source", "TEXT"), ("sounds", "vec", "BLOB"),
    ("chunks", "kind", "TEXT"),
    ("utterances", "media", "TEXT"), ("utterances", "media_text", "TEXT"), ("conversations", "media_note", "TEXT"),
    # 2026-10-06 night: second phone that goes out (wearer), context, privacy gate, two-phone dedupe
    ("chunks", "role", "TEXT"), ("chunks", "lat", "REAL"), ("chunks", "lon", "REAL"), ("chunks", "away", "INTEGER"),
    ("chunks", "cal", "TEXT"), ("chunks", "ctx", "TEXT"), ("chunks", "skew", "INTEGER"), ("chunks", "bat", "INTEGER"),
    ("conversations", "ctx", "TEXT"), ("conversations", "away", "INTEGER"), ("conversations", "lat", "REAL"),
    ("conversations", "lon", "REAL"), ("conversations", "place", "TEXT"), ("conversations", "cal", "TEXT"),
    ("conversations", "marked", "INTEGER"), ("conversations", "device", "TEXT"),
    ("utterances", "device", "TEXT"), ("utterances", "alt_db", "REAL"), ("utterances", "alt_device", "TEXT"),
    ("voice_bank", "device", "TEXT"),
    ("utterances", "lang", "TEXT"), ("marks", "minutes", "INTEGER"),
    ("chunks", "tries", "INTEGER DEFAULT 0"),   # 2026-10-09: requeue_failed() retries environment failures
]


def db():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def migrate():
    with db() as c:
        c.executescript(SCHEMA)
        for table, col, typ in MIGRATIONS:
            have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
            if col not in have:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        cfg = config()
        if cfg.get("owner_name") and not c.execute("SELECT 1 FROM home_people WHERE id=?", (owner_id(),)).fetchone():
            c.execute("INSERT INTO home_people (id, name, created) VALUES (?,?,?)",
                      (owner_id(), str(cfg["owner_name"])[:60], iso(datetime.now())))
        c.execute("UPDATE chunks SET ctx='home', away=0, role='home' WHERE ctx IS NULL")
        c.execute("UPDATE conversations SET ctx='home', away=0 WHERE ctx IS NULL")
        c.execute("UPDATE conversations SET place='בית' WHERE ctx='home' AND place IS NULL")
        c.execute("UPDATE utterances SET device=(SELECT device FROM chunks WHERE chunks.id=utterances.chunk_id) "
                  "WHERE device IS NULL")
        c.execute("UPDATE voice_bank SET device=(SELECT device FROM utterances WHERE utterances.id=voice_bank.utt_id) "
                  "WHERE device IS NULL AND utt_id IS NOT NULL")


def config():
    HOME.mkdir(parents=True, exist_ok=True)
    if CONFIG.exists():
        return json.load(open(CONFIG, encoding="utf-8"))
    cfg = {"token": secrets.token_urlsafe(24), "audio_days": AUDIO_DAYS, "paused_until": None, "audio_policy": "archive",
           "owner": OWNER}
    json.dump(cfg, open(CONFIG, "w", encoding="utf-8"), indent=1)
    return cfg


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]


def log(msg):
    line = time.strftime("[%H:%M:%S] ") + msg
    try:
        print(line, flush=True)
    except Exception:     # pythonw: no stdout
        pass
    try:                  # the windowless service has no console: keep a log file
        lp = HOME / "listener.log"
        if lp.exists() and lp.stat().st_size > 5_000_000:
            lp.replace(HOME / "listener.log.1")
        with open(lp, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d ") + line + "\n")
    except Exception:
        pass


# Failures that are the machine's fault, not the recording's: retry them (<= 3 tries per chunk).
ENV_ERRORS = ("Application Control policy", "filename or extension is too long", "DLL load failed",
              "CUDA out of memory", "CUDA error", "Errno 22", "WinError 206")
_last_requeue = 0.0


def requeue_failed(force=False):
    """status='failed' with an environment error, file still there, tries<3 -> back to 'new' (tries+1).
    Runs at start-up and at most hourly from idle()."""
    global _last_requeue
    if not force and time.time() - _last_requeue < 3600:
        return 0
    _last_requeue = time.time()
    n = 0
    with db() as c:
        rows = c.execute("SELECT id, file, error, COALESCE(tries,0) t FROM chunks WHERE status='failed' "
                         "AND COALESCE(tries,0)<3 AND file IS NOT NULL").fetchall()
        for r in rows:
            if any(k in (r["error"] or "") for k in ENV_ERRORS) and os.path.exists(r["file"]):
                c.execute("UPDATE chunks SET status='new', error=NULL, tries=? WHERE id=?", (r["t"] + 1, r["id"]))
                n += 1
    if n:
        log(f"requeue_failed: {n} chunks back to 'new'")
    return n


# ------------------------------------------------------------------ people + voice bank
_names_cache = None


def known_names():
    """Optional: person_id -> {"name": ...} from voice/names.json in the data folder ({} when missing)."""
    global _names_cache
    if _names_cache is None:
        try:
            _names_cache = json.load(open(VOICE / "names.json", encoding="utf-8"))
        except (OSError, ValueError):
            _names_cache = {}
    return _names_cache


def name_of(c, pid):
    if not pid:
        return None
    if pid == "__tv__":
        return "טלוויזיה"
    r = c.execute("SELECT name FROM home_people WHERE id=?", (pid,)).fetchone()
    return r["name"] if r else (known_names().get(pid) or {}).get("name") or pid


def bank(c, device=None):
    """speaker -> [centroid of the user-labelled phone utterances] (+ a second centroid made only of
    this phone's samples: a phone in a pocket does not sound like a phone on the shelf)."""
    out, per_dev = {}, {}
    for r in c.execute("SELECT speaker, vec, device FROM voice_bank"):
        v = np.frombuffer(r["vec"], dtype=np.float32)
        out.setdefault(r["speaker"], []).append(v)
        if device and r["device"] == device:
            per_dev.setdefault(r["speaker"], []).append(v)
    res = {}
    for s, vs in out.items():
        m = np.mean(vs, axis=0)
        res[s] = [m / (np.linalg.norm(m) + 1e-9)]
        if s in per_dev:
            m = np.mean(per_dev[s], axis=0)
            res[s].append(m / (np.linalg.norm(m) + 1e-9))
    return res


def owner_id():
    return config().get("owner") or OWNER


def household():
    """The owner + config.json "household" (person ids that are always voice candidates)."""
    return list(dict.fromkeys([owner_id()] + list(config().get("household") or [])))


def owner_enrolled(c, device):
    """How many voice samples of the owner exist for this phone (the wearer phone only records away
    from home once this is >= OWNER_MIN_SAMPLES)."""
    return c.execute("SELECT count(*) FROM voice_bank WHERE speaker=? AND device=?", (owner_id(), device)).fetchone()[0]


def extra_names(c):
    return {r["id"]: r["name"] for r in c.execute("SELECT id, name FROM home_people")}


def people_list(c):
    """For the "who is speaking?" menu: the owner / household first, then everyone heard or added."""
    try:
        prints = json.load(open(VOICE / "voiceprints.json", encoding="utf-8"))["prints"]
    except (OSError, ValueError):
        prints = []
    seen, out = set(), []

    def add(pid, group):
        if pid and pid not in seen:
            seen.add(pid)
            out.append({"id": pid, "name": name_of(c, pid), "group": group})
    for pid in household():
        add(pid, "בית")
    for r in c.execute("SELECT speaker, count(*) AS n FROM utterances WHERE speaker IS NOT NULL "
                       "GROUP BY speaker ORDER BY n DESC"):
        add(r["speaker"], "נשמעו")
    for r in c.execute("SELECT id FROM home_people ORDER BY created"):
        add(r["id"], "נוספו")
    for p in prints:
        add(p["person_id"], "מוכנים מראש")
    return out


TV = "__tv__"


def label(utt_id, speaker=None, new_name=None):
    """The user says who spoke one utterance -> voice bank -> re-score unnamed utterances.
    speaker "__tv__" = "this is the TV": the words leave the transcript, the voice teaches the TV filter.
    speaker "__person__" = "not TV": the utterance goes back to the transcript as an unnamed person."""
    from home_analyze import SIM_MIN, MARGIN, best_two
    with db() as c:
        u = c.execute("SELECT * FROM utterances WHERE id=?", (utt_id,)).fetchone()
        if not u:
            return {"ok": False, "msg": "no such utterance"}
        if new_name:
            new_name = new_name.strip()[:60]
            hit = next((pid for pid, d in known_names().items() if (d or {}).get("name") == new_name), None)
            hit = hit or (c.execute("SELECT id FROM home_people WHERE name=?", (new_name,)).fetchone() or [None])[0]
            if not hit:
                hit = "home_" + secrets.token_hex(4)
                c.execute("INSERT INTO home_people (id, name, created) VALUES (?,?,?)", (hit, new_name, iso(datetime.now())))
            speaker = hit
        if not speaker:
            return {"ok": False, "msg": "no speaker"}
        if speaker == "__person__":
            c.execute("UPDATE utterances SET media=NULL, text=coalesce(nullif(text,''), media_text, ''), how=NULL "
                      "WHERE id=?", (utt_id,))
            c.execute("DELETE FROM voice_bank WHERE utt_id=? AND speaker=?", (utt_id, TV))
            return {"ok": True, "speaker": None, "name": "לא טלוויזיה", "renamed": 0}
        if speaker == TV:
            c.execute("UPDATE utterances SET speaker=NULL, name=NULL, how='user', media='טלוויזיה', "
                      "media_text=coalesce(media_text, text), text='' WHERE id=?", (utt_id,))
            c.execute("DELETE FROM voice_bank WHERE utt_id=?", (utt_id,))
            if u["emb"] is not None:
                c.execute("INSERT INTO voice_bank (speaker, utt_id, vec, created, device) VALUES (?,?,?,?,?)",
                          (TV, utt_id, u["emb"], iso(datetime.now()), u["device"]))
            name = "טלוויזיה"
        else:
            name = name_of(c, speaker)
        if speaker != TV:
            c.execute("UPDATE utterances SET speaker=?, name=?, how='user', score=NULL, media=NULL, "
                      "text=coalesce(nullif(text,''), media_text, '') WHERE id=?", (speaker, name, utt_id))
            c.execute("DELETE FROM voice_bank WHERE utt_id=?", (utt_id,))
            if u["emb"] is not None:
                c.execute("INSERT INTO voice_bank (speaker, utt_id, vec, created, device) VALUES (?,?,?,?,?)",
                          (speaker, utt_id, u["emb"], iso(datetime.now()), u["device"]))
        # re-score: everything unnamed (and machine-named) from the last RESCORE_DAYS days
        cands = current_cands(c)
        since = iso(datetime.now() - timedelta(days=RESCORE_DAYS))
        changed = 0
        if len(cands) >= 1:
            rows = c.execute("SELECT id, speaker, emb FROM utterances WHERE t0>=? AND emb IS NOT NULL "
                             "AND coalesce(how,'') != 'user' AND media IS NULL", (since,)).fetchall()
            for r in rows:
                x = np.frombuffer(r["emb"], dtype=np.float32)
                best, s1, s2 = best_two(x, cands)
                new = best if (s1 >= SIM_MIN and s1 - s2 >= MARGIN) else None
                if new == TV:
                    c.execute("UPDATE utterances SET speaker=NULL, name=NULL, how='voice', media='טלוויזיה', "
                              "media_text=text, text='' WHERE id=?", (r["id"],))
                    changed += 1
                    continue
                if new != r["speaker"] and (new or r["speaker"] is None):
                    if new:
                        c.execute("UPDATE utterances SET speaker=?, name=?, how='voice', score=? WHERE id=?",
                                  (new, name_of(c, new), round(s1, 3), r["id"]))
                        changed += 1
        convs = [r[0] for r in c.execute("SELECT DISTINCT conv_id FROM utterances WHERE t0>=? AND conv_id IS NOT NULL", (since,))]
        taught = {name_of(c, r["speaker"]): r["n"] for r in
                  c.execute("SELECT speaker, count(*) AS n FROM voice_bank GROUP BY speaker")}
    for cid in convs:                                      # names in the conversation cards follow
        refresh_people(cid)
    retention(force=True)
    log(f"label: utterance {utt_id} = {name}; {changed} more utterances re-named")
    return {"ok": True, "speaker": speaker, "name": name, "renamed": changed, "taught": taught}


SOUND_SIM = 0.80        # CLAP cosine to a taught sound (home_sounds.BANK_MIN_SIM)


def sound_bank(c):
    return [(r["tag"], np.frombuffer(r["vec"], dtype=np.float32)) for r in c.execute("SELECT tag, vec FROM sound_bank")]


def label_sound(sound_id, tag):
    """The user names a sound ("הפעמון שלנו", "מקרר"). Its CLAP vector joins the sound bank and every
    sound of the last RESCORE_DAYS days that is close enough gets the same name."""
    tag = (tag or "").strip()[:40]
    if not tag:
        return {"ok": False, "msg": "no name"}
    with db() as c:
        r = c.execute("SELECT * FROM sounds WHERE id=?", (sound_id,)).fetchone()
        if not r:
            return {"ok": False, "msg": "no such sound"}
        c.execute("UPDATE sounds SET tag=?, grp='לימדת', source='user' WHERE id=?", (tag, sound_id))
        c.execute("DELETE FROM sound_bank WHERE sound_id=?", (sound_id,))
        renamed = 0
        if r["vec"] is not None:
            c.execute("INSERT INTO sound_bank (tag, sound_id, vec, created) VALUES (?,?,?,?)",
                      (tag, sound_id, r["vec"], iso(datetime.now())))
            v = np.frombuffer(r["vec"], dtype=np.float32)
            since = iso(datetime.now() - timedelta(days=RESCORE_DAYS))
            for o in c.execute("SELECT id, vec FROM sounds WHERE t0>=? AND vec IS NOT NULL AND id!=? "
                               "AND coalesce(source,'') != 'user'", (since, sound_id)).fetchall():
                if float(np.frombuffer(o["vec"], dtype=np.float32) @ v) >= SOUND_SIM:
                    c.execute("UPDATE sounds SET tag=?, grp='לימדת', source='taught' WHERE id=?", (tag, o["id"]))
                    renamed += 1
    log(f"sound {sound_id} = {tag}; {renamed} similar sounds renamed")
    retention(force=True)
    return {"ok": True, "tag": tag, "renamed": renamed}


def sounds_day(c, day):
    rows = [dict(r) for r in c.execute("SELECT id, conv_id, t0, t1, tag, grp, score, source, vec IS NOT NULL AS teachable "
                                       "FROM sounds WHERE substr(t0,1,10)=? ORDER BY t0", (day,))]
    counts = {}
    for r in rows:
        k = (r["tag"], r["grp"] or "")
        counts[k] = counts.get(k, 0) + 1
    tags = sorted(({"tag": t, "group": g, "n": n} for (t, g), n in counts.items()), key=lambda x: -x["n"])
    known = sorted({r["tag"] for r in c.execute("SELECT DISTINCT tag FROM sounds WHERE tag != 'צליל לא מזוהה'")})
    return {"day": day, "events": rows, "tags": tags, "known_tags": known}


def current_cands(c):
    """Optional prepared voiceprints for this year + everything the user taught (phone voice bank)."""
    import voice_speakers as VS
    try:
        meta = json.load(open(VOICE / "voiceprints.json", encoding="utf-8"))["prints"]
        vecs = np.load(VOICE / "voiceprints.npz")["vecs"]
    except (OSError, ValueError):
        meta, vecs = [], []
    by = {}
    for p, v in zip(meta, vecs):
        by.setdefault(p["person_id"], []).append((p, v))
    cands = {}
    for pid in household():
        if pid in by:
            v = VS.print_for(by[pid], datetime.now().year)
            if v is not None:
                cands[pid] = [v]
    for pid, vs in bank(c).items():
        cands.setdefault(pid, []).extend(vs)
    return cands


TEACH_GOAL = 10          # smart teaching: sentences per day worth the user's time


def teach_queue(c, limit=40, mode="smart"):
    """What to ask the user. mode "smart" (default): TEACH_GOAL sentences that teach the most, chosen by
      * need      -- the guessed person has few taught examples (3-5 per person already help a lot),
      * clarity   -- one person clearly closest (margin over the runner-up); sentences where two household voices
                     score the same (probably two people talking together) are left out, so no mixed voice is learnt,
      * length    -- long enough, several words,
      * variety   -- not near-duplicates, at most 4 per guessed person and 2 per conversation.
    mode "all": every unnamed sentence, newest first (the old list). Sentences marked "several speakers / unclear"
    never come back in smart mode."""
    from home_analyze import best_two
    cands = current_cands(c)
    taught = {r["speaker"]: r["n"] for r in c.execute("SELECT speaker, count(*) AS n FROM voice_bank GROUP BY speaker")}
    taught_names = {name_of(c, k): v for k, v in taught.items()}
    today = datetime.now().strftime("%Y-%m-%d")
    done_today = c.execute("SELECT count(*) FROM voice_bank WHERE substr(created,1,10)=?", (today,)).fetchone()[0]
    left = c.execute("SELECT count(*) FROM utterances WHERE speaker IS NULL AND media IS NULL AND emb IS NOT NULL "
                     "AND seconds >= 1.2").fetchone()[0]

    def card(r, best=None, s1=0.0, s2=0.0):
        d = {k: r[k] for k in ("id", "t0", "seconds", "text", "conv_id")}
        if best is not None:
            d.update(guess=best, guess_name=("📺 טלוויזיה" if best == "__tv__" else name_of(c, best)),
                     guess_sim=round(s1, 3), guess_margin=round(s1 - s2, 3))
        return d

    if mode == "all":
        rows = c.execute("SELECT id, t0, seconds, text, conv_id, emb FROM utterances WHERE speaker IS NULL AND media IS NULL "
                         "AND emb IS NOT NULL AND seconds >= 1.2 ORDER BY t0 DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            if cands:
                b, s1, s2 = best_two(np.frombuffer(r["emb"], dtype=np.float32), cands)
                out.append(card(r, b, s1, s2))
            else:
                out.append(card(r))
        return {"items": out, "left": left, "taught": taught_names, "mode": "all", "goal": TEACH_GOAL, "done_today": done_today}

    rows = c.execute("SELECT id, t0, seconds, text, conv_id, emb FROM utterances WHERE speaker IS NULL AND media IS NULL "
                     "AND emb IS NOT NULL AND seconds >= 1.5 AND id NOT IN (SELECT utt_id FROM teach_skips) "
                     "ORDER BY t0 DESC LIMIT 1200").fetchall()
    scored, ambiguous = [], 0
    for r in rows:
        words = len((r["text"] or "").split())
        if words < 3 or not cands:
            continue
        x = np.frombuffer(r["emb"], dtype=np.float32)
        b, s1, s2 = best_two(x, cands)
        if b == "__tv__":
            continue
        margin = s1 - s2
        if s1 < 0.25 or margin < 0.04:                      # two voices equally close: likely a mix, not worth learning
            ambiguous += 1
            continue
        need = 1.0 / (1.0 + taught.get(b, 0)) ** 0.5
        score = 0.5 * need + 0.3 * min(1.0, margin / 0.12) + 0.2 * min(1.0, r["seconds"] / 4.0) * min(1.0, words / 6.0)
        scored.append((score, r, b, s1, s2, x / (np.linalg.norm(x) + 1e-9)))
    scored.sort(key=lambda t: -t[0])
    picks, per_guess, per_conv = [], {}, {}
    for score, r, b, s1, s2, xn in scored:
        if len(picks) >= max(limit, TEACH_GOAL) or len(picks) >= TEACH_GOAL:
            break
        if per_guess.get(b, 0) >= 4 or per_conv.get(r["conv_id"], 0) >= 2:
            continue
        if any(float(np.dot(xn, p[5])) >= 0.93 for p in picks):          # near-duplicate of one already chosen
            continue
        picks.append((score, r, b, s1, s2, xn))
        per_guess[b] = per_guess.get(b, 0) + 1
        per_conv[r["conv_id"]] = per_conv.get(r["conv_id"], 0) + 1
    out = [card(r, b, s1, s2) for _, r, b, s1, s2, _ in picks]
    return {"items": out, "left": left, "taught": taught_names, "mode": "smart", "goal": TEACH_GOAL, "done_today": done_today,
            "skipped_ambiguous": ambiguous,
            "need": {name_of(c, k): v for k, v in taught.items() if not k.startswith("__")}}


def people_stats(c):
    """Per person: minutes per day (last 14 days), mood, last line, how many voice samples taught."""
    since = (datetime.now() - timedelta(days=13)).strftime("%Y-%m-%d")
    out = {}
    for r in c.execute("SELECT speaker, name, substr(t0,1,10) AS day, sum(seconds) AS s, count(*) AS n, avg(valence) AS v, "
                       "avg(arousal) AS a FROM utterances WHERE speaker IS NOT NULL AND t0>=? GROUP BY speaker, day", (since,)):
        p = out.setdefault(r["speaker"], {"id": r["speaker"], "name": r["name"], "days": {}, "lines": 0, "seconds": 0, "v": [], "a": []})
        p["days"][r["day"]] = round(r["s"] / 60, 1)
        p["lines"] += r["n"]; p["seconds"] += r["s"]
        if r["v"] is not None:
            p["v"].append(r["v"]); p["a"].append(r["a"])
    taught = {r["speaker"]: r["n"] for r in c.execute("SELECT speaker, count(*) AS n FROM voice_bank GROUP BY speaker")}
    res = []
    for pid, p in out.items():
        last = c.execute("SELECT text, t0 FROM utterances WHERE speaker=? AND length(text)>12 ORDER BY t0 DESC LIMIT 1", (pid,)).fetchone()
        with_ = c.execute("""SELECT u2.name, count(DISTINCT u2.conv_id) AS n FROM utterances u1 JOIN utterances u2
                             ON u1.conv_id=u2.conv_id AND u2.speaker IS NOT NULL AND u2.speaker!=u1.speaker
                             WHERE u1.speaker=? AND u1.t0>=? GROUP BY u2.name ORDER BY n DESC LIMIT 3""", (pid, since)).fetchall()
        res.append({"id": pid, "name": p["name"], "days": p["days"], "lines": p["lines"],
                    "minutes": round(p["seconds"] / 60, 1),
                    "valence": round(sum(p["v"]) / len(p["v"]), 2) if p["v"] else None,
                    "arousal": round(sum(p["a"]) / len(p["a"]), 2) if p["a"] else None,
                    "last": dict(last) if last else None, "taught": taught.get(pid, 0),
                    "with": [{"name": w["name"], "n": w["n"]} for w in with_]})
    res.sort(key=lambda x: -x["minutes"])
    return {"people": res, "since": since}


def refresh_people(cid):
    import home_analyze
    with db() as c:
        U = [dict(x) for x in c.execute("SELECT t0, seconds, speaker, name FROM utterances WHERE conv_id=? AND media IS NULL "
                                         "ORDER BY t0", (cid,))]
        if not U:
            return
        t0 = datetime.fromisoformat(U[0]["t0"])
        dyn = home_analyze.dynamics([{"t0": (datetime.fromisoformat(u["t0"]) - t0).total_seconds(),
                                      "t1": (datetime.fromisoformat(u["t0"]) - t0).total_seconds() + u["seconds"],
                                      "speaker": u["speaker"], "name": u["name"]} for u in U])
        c.execute("UPDATE conversations SET people=?, talk_seconds=?, interruptions=? WHERE id=?",
                  (json.dumps(sorted({u["name"] for u in U if u["name"]}), ensure_ascii=False),
                   json.dumps(dyn["talk_seconds"], ensure_ascii=False),
                   json.dumps(dyn["interruptions"], ensure_ascii=False), cid))
        done = c.execute("SELECT status FROM conversations WHERE id=?", (cid,)).fetchone()
    if done and done["status"] == "done":
        index_conversation(cid)


# ------------------------------------------------------------------ phones (heartbeat every 30 s)
PHONES_FILE = HOME / "phones.json"
_phones_lock = threading.Lock()


def phone_seen(device, ip, **info):
    device = re.sub(r"[^A-Za-z0-9_-]", "", device or "phone")[:30] or "phone"
    with _phones_lock:
        try:
            ph = json.load(open(PHONES_FILE, encoding="utf-8"))
        except (OSError, ValueError):
            ph = {}
        d = ph.setdefault(device, {})
        d.update({k: v for k, v in info.items() if v is not None}, last_seen=iso(datetime.now()), ip=ip)
        tmp = PHONES_FILE.with_suffix(".tmp")
        json.dump(ph, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        tmp.replace(PHONES_FILE)


def store_timeline(device, tl, skew):
    """The phone's own log of what its microphone did: [{s,e (ms, phone clock), r (reason, '' = recording), d}].
    The running entry arrives again with a later end: upsert by (device, start)."""
    device = clean_device(device)
    try:
        arr = json.loads(tl) if tl else []
    except ValueError:
        return 0
    off = skew if abs(skew) > 2000 else 0
    n = 0
    with db() as c:
        for x in arr[:60]:
            try:
                s0 = iso(datetime.fromtimestamp((int(x["s"]) + off) / 1000))
                e0 = iso(datetime.fromtimestamp((int(x["e"]) + off) / 1000))
            except (KeyError, ValueError, TypeError, OSError):
                continue
            c.execute("INSERT INTO phone_timeline (device, s, e, reason, detail, received) VALUES (?,?,?,?,?,?) "
                      "ON CONFLICT(device, s) DO UPDATE SET e=excluded.e, reason=excluded.reason, detail=excluded.detail, "
                      "received=excluded.received", (device, s0, e0, str(x.get("r") or "")[:20], str(x.get("d") or "")[:80],
                                                   iso(datetime.now())))
            n += 1
    return n


def phones():
    try:
        ph = json.load(open(PHONES_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        return []
    now = datetime.now()
    out = []
    for dev, d in ph.items():
        age = (now - datetime.fromisoformat(d["last_seen"])).total_seconds()
        name = (config().get("phone_names") or {}).get(dev, dev)     # device code -> readable name
        out.append(dict(d, device=name, code=dev, seconds_ago=round(age), online=age < 120))
    return sorted(out, key=lambda d: d["seconds_ago"])


# ------------------------------------------------------------------ ingest
KINDS = ("speech", "sound", "enroll", "import")
OWNER_MIN_SAMPLES = 3         # wearer phone: owner voice samples needed before it records away from home
OWNER_MIN_SECONDS = 1.5       # away conversations without this much of the owner's own speech are dropped


def clean_device(device):
    return re.sub(r"[^A-Za-z0-9_-]", "", device or "phone")[:30] or "phone"


def store_chunk(raw, device, start, ext, kind="speech", meta=None):
    """meta (from the phone): ms (epoch ms), skew (server-phone clock, ms), lat, lon, home (1/0), role, cal, bat."""
    meta = meta or {}
    device = clean_device(device)
    st = None
    if meta.get("ms"):                                    # the phone's epoch -> this PC's clock (phone abroad / wrong clock)
        skew = int(meta.get("skew") or 0)
        st = datetime.fromtimestamp((int(meta["ms"]) + (skew if abs(skew) > 2000 else 0)) / 1000)
    if st is None:
        try:
            st = datetime.fromisoformat(start.replace("Z", ""))
        except ValueError:
            st = datetime.now()
    role = meta.get("role") or "home"
    home = 1 if str(meta.get("home", "1")) in ("1", "true") else 0
    away = 0 if (role == "home" or home) else 1
    if kind == "import":
        ctx = f"import:{device}:{st.strftime('%Y%m%dT%H%M%S')}"
    else:
        ctx = "home" if not away else f"away:{device}"
    with db() as c:
        dup = c.execute("SELECT id FROM chunks WHERE device=? AND start=? AND coalesce(kind,'speech')=?",
                        (device, iso(st), kind)).fetchone()
        if dup:                                           # the phone re-sent a file whose "ok" got lost
            return dup["id"]
    day = AUDIO / st.strftime("%Y-%m-%d")
    day.mkdir(parents=True, exist_ok=True)
    fn = day / f"{st.strftime('%H%M%S_%f')[:-3]}_{device[:20]}{'_' + kind if kind != 'speech' else ''}.{ext}"
    fn.write_bytes(raw)
    with db() as c:
        cur = c.execute("INSERT INTO chunks (device,start,file,status,received,kind,role,lat,lon,away,cal,ctx,skew,bat) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (device, iso(st), str(fn), "new", iso(datetime.now()), kind, role, meta.get("lat"), meta.get("lon"),
                         away, (meta.get("cal") or "")[:120] or None, ctx, meta.get("skew"), meta.get("bat")))
        if marked_now(c, iso(st)):                       # a star was pressed around this time: never delete it
            c.execute("UPDATE chunks SET keep=1 WHERE id=?", (cur.lastrowid,))
        return cur.lastrowid


# ------------------------------------------------------------------ places, marks, privacy helpers
def km(lat1, lon1, lat2, lon2):
    import math
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2 +
         math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(a))


def place_of(c, lat, lon):
    """-> (name, mute) of the nearest known place the coordinates fall in, else (None, 0)."""
    if lat is None or lon is None:
        return None, 0
    best = None
    for r in c.execute("SELECT name, lat, lon, r_m, mute FROM places"):
        d = km(lat, lon, r["lat"], r["lon"]) * 1000
        if d <= r["r_m"] and (best is None or d < best[0]):
            best = (d, r["name"], r["mute"])
    return (best[1], best[2]) if best else (None, 0)


DIGITS = re.compile(r"(?<![\d])(?:\d[ \-]?){8,}(?!\d)")


def redact(text):
    """Card / ID / phone-like digit runs never reach the database."""
    return DIGITS.sub(lambda m: "[מספר]" + (" " if m.group(0).endswith(" ") else ""), text) if text else text


def optout_set():
    return set(config().get("optout") or [])


def set_optout(pid, on=True):
    """Someone who asked not to be recorded: their voice stays known (so they can be recognised and dropped)
    but every utterance of theirs is deleted now and never stored again."""
    cfg = config()
    lst = set(cfg.get("optout") or [])
    (lst.add if on else lst.discard)(pid)
    cfg["optout"] = sorted(lst)
    json.dump(cfg, open(CONFIG, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    n = 0
    if on:
        with db() as c:
            n = c.execute("DELETE FROM utterances WHERE speaker=?", (pid,)).rowcount
    return {"ok": True, "optout": sorted(lst), "deleted": n}


MARK_MINUTES = 10


def add_mark(device, t, note=None, minutes=None):
    """The star on the phone. Every recording within [minutes] before and after the mark is never deleted (also the ones that
    arrive later: store_chunk checks the marks), and the conversations in that window are kept even away from home."""
    minutes = max(1, min(int(minutes or config().get("mark_minutes", MARK_MINUTES)), 180))
    with db() as c:
        c.execute("INSERT INTO marks (t, device, note, minutes) VALUES (?,?,?,?)", (iso(t), clean_device(device), note, minutes))
        c.execute("UPDATE chunks SET keep=1 WHERE start>=? AND start<=?",
                  (iso(t - timedelta(minutes=minutes)), iso(t + timedelta(minutes=minutes))))
        c.execute("UPDATE conversations SET marked=1 WHERE start<=? AND end>=?",
                  (iso(t + timedelta(minutes=minutes)), iso(t - timedelta(minutes=minutes))))
    return minutes


def marked_now(c, start_iso):
    """Is this recording inside the window of some star?"""
    t = datetime.fromisoformat(start_iso)
    for r in c.execute("SELECT t, coalesce(minutes, 2) m FROM marks WHERE t >= ? AND t <= ?",
                       (iso(t - timedelta(minutes=181)), iso(t + timedelta(minutes=181)))):
        if abs((datetime.fromisoformat(r["t"]) - t).total_seconds()) <= r["m"] * 60:
            return True
    return False


# ------------------------------------------------------------------ analysis worker
class Worker(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.B = None
        self.last_used = 0
        self.busy = False

    def run(self):
        last_close = 0.0
        while True:
            try:
                if time.time() - last_close > 60:          # idle() never runs while chunks keep coming: close conversations anyway
                    last_close = time.time()
                    close_conversations()
                did = self.step()
            except Exception as exc:  # noqa: BLE001
                log(f"worker error {exc!r}")
                did = False
            if not did:
                try:
                    self.idle()
                except Exception as exc:  # noqa: BLE001
                    log(f"idle error {exc!r}")
                time.sleep(3)

    def idle(self):
        if self.B is not None and time.time() - self.last_used > 600:     # free the memory after 10 min idle
            self.B = None
            import gc
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
            log("models released (idle)")
        requeue_failed()
        try:
            import asr_update
            asr_update.maybe_run()            # every 90 days, when no chunk is waiting
        except Exception as exc:  # noqa: BLE001
            log(f"asr_update failed {exc!r}")
        scan_imports()
        close_conversations()
        provisional_summaries()
        daily_summaries()
        retention()

    def step(self):
        with db() as c:
            row = c.execute("SELECT * FROM chunks WHERE status='new' ORDER BY (kind='enroll') DESC, start LIMIT 1").fetchone()
        if not row:
            return False
        self.busy = True
        try:
            import home_analyze
            if self.B is None:
                log("loading models")
                self.B = home_analyze.Brain()
            self.last_used = time.time()
            st = datetime.fromisoformat(row["start"])
            t = time.time()
            with db() as c:
                bk, names, sb = bank(c, row["device"]), extra_names(c), sound_bank(c)
            kind = row["kind"] or "speech"
            res = home_analyze.analyse(self.B, row["file"], year=st.year, bank=bk, names=names, sound_bank=sb,
                                       kind=kind, when=st.timestamp(),
                                       songs=config().get("song_lookup", False) and not row["away"],
                                       away=bool(row["away"]))
            if kind == "enroll":
                enrol_owner(row, res)
            else:
                save_analysis(row, st, res)
            with db() as c:
                c.execute("UPDATE chunks SET status='done', seconds=?, analysed=?, took=? WHERE id=?",
                          (res["seconds"], iso(datetime.now()), round(time.time() - t, 1), row["id"]))
            log(f"chunk {row['id']} {res['seconds']}s -> {len(res['utterances'])} utterances in {time.time() - t:.1f}s")
            retention(force=True)
        except Exception as exc:  # noqa: BLE001
            with db() as c:
                c.execute("UPDATE chunks SET status='failed', error=? WHERE id=?", (repr(exc)[:500], row["id"]))
            log(f"chunk {row['id']} failed {exc!r}")
        finally:
            self.busy = False
        return True


def enrol_owner(row, res):
    """The owner read a passage into this phone: every utterance's voice vector becomes an owner sample
    for this phone. The recording itself is not kept."""
    n = 0
    with db() as c:
        for u in res["utterances"]:
            if u.get("emb") is not None and not u.get("media") and u["t1"] - u["t0"] >= 1.0:
                c.execute("INSERT INTO voice_bank (speaker, utt_id, vec, created, device) VALUES (?,NULL,?,?,?)",
                          (owner_id(), u["emb"].astype(np.float32).tobytes(), iso(datetime.now()), row["device"]))
                n += 1
        if row["file"]:
            drop_audio(c, row["id"], row["file"])
    log(f"enrol: {n} owner voice samples for {row['device']}")


def _norm_words(t):
    return [w for w in re.sub(r"[^\w\s]", " ", (t or "").lower()).split() if w]


def _dup_of(c, device, t0, t1, text):
    """An utterance the OTHER phone already heard (same time, same words)?"""
    import difflib
    words = _norm_words(text)
    if len(words) < 2:
        return None
    for e in c.execute("""SELECT * FROM utterances WHERE device!=? AND t0<=? AND t1>=? AND text!='' AND media IS NULL""",
                       (device, iso(datetime.fromisoformat(t1) + timedelta(seconds=1.5)),
                        iso(datetime.fromisoformat(t0) - timedelta(seconds=1.5)))):
        other = _norm_words(e["text"])
        sm = difflib.SequenceMatcher(None, words, other)
        shared = sum(b.size for b in sm.get_matching_blocks())
        if shared >= 2 and shared / max(1, min(len(words), len(other))) >= 0.6:   # one contains (most of) the other
            return e
    return None


def _open_conv(c, ctx, t0, lat, lon):
    """The open conversation of this context that the utterance continues, or None (a new one starts)."""
    prev = c.execute("SELECT * FROM conversations WHERE status='open' AND coalesce(ctx,'home')=? "
                     "ORDER BY end DESC LIMIT 1", (ctx,)).fetchone()
    # the utterance must fall inside [start - gap, end + gap] of the conversation, so chunks replayed out of order
    # (a backlog analysed hours later) do not all join whatever conversation is open.
    t = datetime.fromisoformat(t0)
    if prev and (datetime.fromisoformat(prev["start"]) - timedelta(seconds=CONV_GAP) <= t
                 <= datetime.fromisoformat(prev["end"]) + timedelta(seconds=CONV_GAP)):
        moved = (lat is not None and prev["lat"] is not None and km(lat, lon, prev["lat"], prev["lon"]) > 0.3)
        if not moved:                                         # moved > 300 m = a new place = a new conversation
            return prev["id"]
    if prev:
        c.execute("UPDATE conversations SET status='ended' WHERE id=?", (prev["id"],))
    return None


def save_analysis(row, st, res):
    chunk_id, device = row["id"], row["device"]
    ctx, away = row["ctx"] or "home", int(row["away"] or 0)
    at = lambda s: iso(st + timedelta(seconds=float(s)))  # noqa: E731
    out_opt = optout_set()
    skipped = 0
    with db() as c:
        place, _ = place_of(c, row["lat"], row["lon"])
        place = place or ("בית" if not away else None)
        for u in res["utterances"]:
            if not u["text"].strip() and not (u.get("media") and (u.get("media_text") or "").strip()):
                continue
            if u.get("speaker") in out_opt:                   # asked not to be recorded
                skipped += 1
                continue
            u["text"], u["media_text"] = redact(u["text"]), redact(u.get("media_text"))
            t0, t1 = at(u["t0"]), at(u["t1"])
            p, e, d = u.get("prosody") or {}, u.get("emotion") or {}, u.get("dims") or {}
            dup = None if (u.get("media") or ctx.startswith("import:")) else _dup_of(c, device, t0, t1, u["text"])
            alt_db, alt_dev = None, None
            if dup is not None:                               # two phones heard it: keep the louder (closer) one
                n_new, n_old = len(_norm_words(u["text"])), len(_norm_words(dup["text"]))
                new_better = n_new > n_old * 1.15 or (n_new >= n_old * 0.87 and
                                                     (p.get("intensity_db") or -99) > (dup["intensity_db"] or -99))
                if not new_better:                            # the other phone's version has more words / is closer
                    c.execute("UPDATE utterances SET alt_db=?, alt_device=? WHERE id=?",
                              (p.get("intensity_db"), device, dup["id"]))
                    continue
                alt_db, alt_dev = dup["intensity_db"], dup["device"]
                c.execute("DELETE FROM utterances WHERE id=?", (dup["id"],))
            conv = _open_conv(c, ctx, t0, row["lat"], row["lon"])
            if conv:
                c.execute("UPDATE conversations SET end=? WHERE id=? AND end<?", (t1, conv, t1))
            else:
                conv = c.execute("INSERT INTO conversations (start,end,status,ctx,away,lat,lon,place,cal,device) "
                                 "VALUES (?,?,'open',?,?,?,?,?,?,?)",
                                 (t0, t1, ctx, away, row["lat"], row["lon"], place, row["cal"], device)).lastrowid
            if row["cal"]:
                c.execute("UPDATE conversations SET cal=coalesce(cal,?) WHERE id=?", (row["cal"], conv))
            emb = u.get("emb")
            c.execute("""INSERT INTO utterances (chunk_id,conv_id,t0,t1,seconds,speaker,name,text,f0_hz,f0_range_st,
                         intensity_db,syll_per_s,voiced_share,emotion,emotion_p,emotion_scores,arousal,dominance,valence,
                         emb,how,media,media_text,device,alt_db,alt_device,lang)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (chunk_id, conv, t0, t1, round(u["t1"] - u["t0"], 2), u["speaker"], u["name"],
                       u["text"].strip(), p.get("f0_hz"), p.get("f0_range_st"), p.get("intensity_db"),
                       p.get("syll_per_s"), p.get("voiced_share"), e.get("label"), e.get("p"),
                       json.dumps(e.get("scores")) if e else None, d.get("arousal"), d.get("dominance"), d.get("valence"),
                       emb.astype(np.float32).tobytes() if emb is not None else None, u.get("how"),
                       u.get("media"), u.get("media_text"), device, alt_db, alt_dev, u.get("lang")))
        for s in res["sounds"]:
            if away:
                break                                         # away from home: only the speech of the owner's conversations
            conv = c.execute("SELECT id FROM conversations WHERE start<=? AND end>=? AND coalesce(ctx,'home')=? LIMIT 1",
                             (at(s["t0"]), at(s["t0"]), ctx)).fetchone()
            v = s.get("vec")
            c.execute("INSERT INTO sounds (chunk_id,conv_id,t0,t1,tag,score,grp,source,vec) VALUES (?,?,?,?,?,?,?,?,?)",
                      (chunk_id, conv["id"] if conv else None, at(s["t0"]), at(s["t1"]), s["tag"], s["score"],
                       s.get("group"), s.get("source"), v.astype(np.float32).tobytes() if v is not None else None))
    if skipped:
        with db() as c:
            c.execute("INSERT INTO dropped (day, ctx, reason, seconds, utterances, at) VALUES (?,?,?,?,?,?)",
                      (st.strftime("%Y-%m-%d"), ctx, "optout", 0, skipped, iso(datetime.now())))


# ------------------------------------------------------------------ privacy gate for conversations away from home
def drop_conversation(cid, reason):
    """Delete an away conversation completely: words, voices, sounds, the recordings that held only it."""
    with db() as c:
        conv = c.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
        if not conv:
            return
        chunks = [r[0] for r in c.execute("SELECT DISTINCT chunk_id FROM utterances WHERE conv_id=?", (cid,))]
        n = c.execute("SELECT count(*) FROM utterances WHERE conv_id=?", (cid,)).fetchone()[0]
        secs = c.execute("SELECT coalesce(sum(seconds),0) FROM utterances WHERE conv_id=?", (cid,)).fetchone()[0]
        c.execute("DELETE FROM utterances WHERE conv_id=?", (cid,))
        c.execute("DELETE FROM sounds WHERE conv_id=?", (cid,))
        c.execute("DELETE FROM conversations WHERE id=?", (cid,))
        c.execute("DELETE FROM conv_fts WHERE conv_id=?", (cid,))
        c.execute("INSERT INTO dropped (day, ctx, reason, seconds, utterances, at) VALUES (?,?,?,?,?,?)",
                  (conv["start"][:10], conv["ctx"], reason, round(secs, 1), n, iso(datetime.now())))
        for ch in chunks:
            left = c.execute("SELECT count(*) FROM utterances WHERE chunk_id=?", (ch,)).fetchone()[0]
            f = c.execute("SELECT file FROM chunks WHERE id=?", (ch,)).fetchone()
            if not left and f and f["file"]:
                drop_audio(c, ch, f["file"])
    log(f"away conversation {cid} dropped ({reason}): {n} utterances, {secs:.0f}s")


def gate_conversation(cid):
    """Away from home only conversations the owner takes part in are kept (a participant may usually record
    a conversation they are in; see README). -> True when kept."""
    with db() as c:
        conv = c.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
        if not conv or not conv["away"]:
            return True
        cs, ce = datetime.fromisoformat(conv["start"]), datetime.fromisoformat(conv["end"])
        marked = sum(1 for m in c.execute("SELECT t, coalesce(minutes, 2) m FROM marks WHERE t >= ? AND t <= ?",
                                          (iso(cs - timedelta(minutes=181)), iso(ce + timedelta(minutes=181))))
                     if datetime.fromisoformat(m["t"]) - timedelta(minutes=m["m"]) <= ce + timedelta(seconds=CONV_GAP)
                     and datetime.fromisoformat(m["t"]) + timedelta(minutes=m["m"]) >= cs - timedelta(seconds=CONV_GAP))
        mute = place_of(c, conv["lat"], conv["lon"])[1]
        owner = c.execute("SELECT coalesce(sum(seconds),0) AS s, avg(intensity_db) AS db FROM utterances "
                          "WHERE conv_id=? AND speaker=? AND media IS NULL", (cid, owner_id())).fetchone()
    cfg = config()
    if mute:
        drop_conversation(cid, "mute-place")
        return False
    if not marked and (owner["s"] or 0) < cfg.get("owner_min_seconds", OWNER_MIN_SECONDS):
        drop_conversation(cid, "owner-not-in-conversation")
        return False
    # bystanders: unnamed voices much quieter than the owner are people talking elsewhere, not to the owner
    if owner["db"] is not None:
        gap = cfg.get("bystander_db", 12)
        with db() as c:
            q = c.execute("DELETE FROM utterances WHERE conv_id=? AND speaker IS NULL AND media IS NULL "
                          "AND intensity_db IS NOT NULL AND intensity_db < ?", (cid, owner["db"] - gap)).rowcount
            if q:
                c.execute("INSERT INTO dropped (day, ctx, reason, seconds, utterances, at) VALUES (?,?,?,?,?,?)",
                          (conv["start"][:10], conv["ctx"], "bystander", 0, q, iso(datetime.now())))
    if marked:
        with db() as c:
            c.execute("UPDATE conversations SET marked=1 WHERE id=?", (cid,))
    return True


def resplit_conversation(cid):
    """Repair: cut one conversation into real conversations at gaps > CONV_GAP of the utterances' own times
    (e.g. after a backlog replay merged many hours into one). The new ones are 'ended',
    so close_conversations() gates, summarises and indexes each of them."""
    with db() as c:
        old = c.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
        if not old:
            return 0
        U = c.execute("SELECT id, t0, t1 FROM utterances WHERE conv_id=? ORDER BY t0", (cid,)).fetchall()
        groups = []
        for u in U:
            if groups and (datetime.fromisoformat(u["t0"]) - datetime.fromisoformat(groups[-1][-1]["t1"])).total_seconds() < CONV_GAP:
                groups[-1].append(u)
            else:
                groups.append([u])
        ids = []
        for g in groups:
            a, b = g[0]["t0"], max(x["t1"] for x in g)
            nid = c.execute("INSERT INTO conversations (start,end,status,ctx,away,lat,lon,place,cal,device) "
                            "VALUES (?,?,'ended',?,?,?,?,?,?,?)",
                            (a, b, old["ctx"], old["away"], old["lat"], old["lon"], old["place"], old["cal"], old["device"])).lastrowid
            c.executemany("UPDATE utterances SET conv_id=? WHERE id=?", [(nid, x["id"]) for x in g])
            c.execute("UPDATE sounds SET conv_id=? WHERE conv_id=? AND t0>=? AND t0<=?", (nid, cid, a, b))
            ids.append(nid)
        c.execute("UPDATE sounds SET conv_id=NULL WHERE conv_id=?", (cid,))
        c.execute("DELETE FROM conv_fts WHERE conv_id=?", (cid,))
        c.execute("DELETE FROM conversations WHERE id=?", (cid,))
    log(f"resplit conversation {cid} into {len(ids)} conversations")
    return len(ids)


def close_conversations():
    """Open conversations quiet for > CONV_GAP s (and no queued chunk before that) -> final summary."""
    now = datetime.now()
    with db() as c:
        # only a queued chunk that could still belong to the conversation holds it back (with two phones sending all day
        # and a backlog the queue may never be empty).
        oldest_new = c.execute("SELECT min(start) FROM chunks WHERE status='new'").fetchone()[0]
        rows = c.execute("SELECT id, end FROM conversations WHERE status IN ('open','ended') ORDER BY start").fetchall()
    for r in rows:
        end = datetime.fromisoformat(r["end"])
        quiet = (now - end).total_seconds()
        if quiet < CONV_GAP or (oldest_new and datetime.fromisoformat(oldest_new) <= end + timedelta(seconds=CONV_GAP + 60)):
            continue
        if not gate_conversation(r["id"]):
            continue
        finish_conversation(r["id"])


def provisional_summaries():
    """A running conversation gets a summary every SUMMARY_EVERY new utterances (marked provisional)."""
    with db() as c:
        rows = c.execute("""SELECT k.id, k.summary_n, count(u.id) AS n FROM conversations k JOIN utterances u ON u.conv_id=k.id
                            WHERE k.status='open' GROUP BY k.id""").fetchall()
    for r in rows:
        if r["n"] - (r["summary_n"] or 0) >= SUMMARY_EVERY:
            finish_conversation(r["id"], final=False)


def conv_stats(c, cid):
    import home_analyze
    U = [dict(x) for x in c.execute("SELECT * FROM utterances WHERE conv_id=? AND media IS NULL ORDER BY t0", (cid,))]
    S = [dict(x) for x in c.execute("SELECT tag, max(score) AS score, count(*) AS n FROM sounds WHERE conv_id=? "
                                    "GROUP BY tag ORDER BY n DESC", (cid,))]
    if not U:
        return U, S, None
    t0 = datetime.fromisoformat(U[0]["t0"])
    for u in U:
        u["t0s"] = (datetime.fromisoformat(u["t0"]) - t0).total_seconds()
        u["t1s"] = u["t0s"] + u["seconds"]
    dyn = home_analyze.dynamics([{"t0": u["t0s"], "t1": u["t1s"], "speaker": u["speaker"], "name": u["name"]} for u in U])
    return U, S, dyn


MEDIA_TASK = """לפניך מילים שזוהו בהקלטה בבית כשידור טלוויזיה, שיר או מוזיקה ברקע (תמלול אוטומטי, עם שגיאות).
כתוב שורה אחת קצרה בעברית: מה כנראה שודר או התנגן (סוג תוכנית, נושא, שפה, שם שיר אם הוא ברור מהמילים).
אל תצטט ואל תמציא. אם אי אפשר לדעת, כתוב רק את הסוג (למשל "מוזיקה ברקע").
החזר JSON: {"note": "..."}"""


def describe_media(c, cid, final):
    """One line about what was on (TV / song / music); the words themselves are dropped when final."""
    rows = c.execute("SELECT media, media_text, seconds FROM utterances WHERE conv_id=? AND media IS NOT NULL "
                     "ORDER BY t0", (cid,)).fetchall()
    if not rows:
        only = [r["tag"][4:] for r in c.execute("SELECT DISTINCT tag FROM sounds WHERE conv_id=? AND source='shazam'", (cid,))]
        return ("🎵 " + ", ".join(only[:4])) if only else None
    kinds = {}
    for r in rows:
        kinds[r["media"]] = kinds.get(r["media"], 0) + (r["seconds"] or 0)
    head = ", ".join(f"{k} {round(v / 60, 1)} דק׳" for k, v in sorted(kinds.items(), key=lambda kv: -kv[1]))
    songs = [r["tag"][4:] for r in c.execute("SELECT DISTINCT tag FROM sounds WHERE conv_id=? AND source='shazam'", (cid,))]
    if songs:
        head += " · 🎵 " + ", ".join(songs[:4])
    words = " ".join(r["media_text"] or "" for r in rows).strip()[:4000]
    note = None
    if len(words) >= 30:
        out = _ollama_json(MEDIA_TASK, words)
        note = out.get("note") if isinstance(out.get("note"), str) else None
    if final:
        c.execute("UPDATE utterances SET media_text=NULL WHERE conv_id=? AND media IS NOT NULL", (cid,))
    return f"{head}" + (f" · {note}" if note else "")


def finish_conversation(cid, final=True):
    with db() as c:
        U, S, dyn = conv_stats(c, cid)
        media_note = describe_media(c, cid, final)
        if media_note:
            c.execute("UPDATE conversations SET media_note=? WHERE id=?", (media_note, cid))
    if not U and media_note:                       # only TV / music, nobody talking
        with db() as c:
            r = c.execute("SELECT min(t0) a, max(t1) b FROM utterances WHERE conv_id=?", (cid,)).fetchone()
            c.execute("UPDATE conversations SET seconds=?, topic=?, status=? WHERE id=?",
                      ((datetime.fromisoformat(r["b"]) - datetime.fromisoformat(r["a"])).total_seconds(),
                       "ברקע: " + media_note.split(" ")[0], "done" if final else "open", cid))
        return
    if not U:
        with db() as c:
            c.execute("UPDATE conversations SET status='empty' WHERE id=?", (cid,))
        return
    people = sorted({u["name"] for u in U if u["name"]})
    val = [u["valence"] for u in U if u["valence"] is not None]
    aro = [u["arousal"] for u in U if u["arousal"] is not None]
    summ = summarise(U, S, dyn, media_note)
    with db() as c:
        c.execute("""UPDATE conversations SET seconds=?, people=?, talk_seconds=?, turns=?, overlaps=?, interruptions=?,
                     mood_valence=?, mood_arousal=?, sounds=?, topic=?, summary=?, moments=?, mood_text=?, per_person=?,
                     signals=?, summary_model=?, summary_n=?, status=? WHERE id=?""",
                  ((datetime.fromisoformat(U[-1]["t1"]) - datetime.fromisoformat(U[0]["t0"])).total_seconds(),
                   json.dumps(people, ensure_ascii=False), json.dumps(dyn["talk_seconds"], ensure_ascii=False),
                   dyn["turns"], dyn["overlaps"], json.dumps(dyn["interruptions"], ensure_ascii=False),
                   round(sum(val) / len(val), 3) if val else None, round(sum(aro) / len(aro), 3) if aro else None,
                   json.dumps(S, ensure_ascii=False), summ.get("topic"), summ.get("summary"),
                   json.dumps(summ.get("moments") or [], ensure_ascii=False), summ.get("mood"),
                   json.dumps(summ.get("per_person") or {}, ensure_ascii=False),
                   json.dumps(summ.get("signals") or [], ensure_ascii=False), summ.get("model"), len(U),
                   "done" if final else "open", cid))
    if final:
        try:
            extract_tasks(cid, U)
            index_conversation(cid)
        except Exception as exc:  # noqa: BLE001
            log(f"tasks/index for conversation {cid} failed {exc!r}")
    log(f"conversation {cid} {'done' if final else 'provisional summary'}: {len(U)} utterances, {people}")


SUMMARY_TASK = f"""אתה מסכם שיחה שהוקלטה בבית. כתוב בעברית, קצר, חם ועובדתי, רק לפי התמלול והנתונים.
אל תמציא שמות, מקומות, מספרים או אירועים שלא נאמרו. "?" הוא דובר שלא זוהה. התמלול אוטומטי ויש בו שגיאות.
"טון" ליד משפט הוא מדידה אקוסטית (עוררות 0-1, חיוביות 0-1); השתמש בו רק כדי לתאר אווירה כללית, לא לקבוע מה מישהו הרגיש.
החזר JSON בלבד:
{{"topic": "2-5 מילים",
 "summary": "2-3 משפטים: על מה דיברו ומה קרה",
 "mood": "חצי משפט על האווירה",
 "per_person": {{"שם": "משפט אחד: מה האדם הזה אמר או רצה בשיחה"}},
 "signals": ["0-3 מתוך: {', '.join(SIGNALS)}"],
 "moments": ["עד 3 משפטים בולטים, מצוטטים מילה במילה מהתמלול"]}}"""


def _ollama_json(system, user, num_ctx=8192):
    import ollama
    cl = ollama.Client(host=os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"), timeout=300)
    last = None
    first = SUMMARY_MODEL or config().get("summary_model") or "gemma3:4b"
    for model in dict.fromkeys((first, "gemma3:4b")):      # a big model may not load while the card is full
        try:
            kw = {"think": False} if model.startswith(("gemma4", "qwen3")) else {}
            r = cl.chat(model=model, messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                        format="json", options={"temperature": 0.2, "num_ctx": num_ctx}, keep_alive="2m", **kw)
            out = json.loads(r["message"]["content"])
            if isinstance(out, dict):
                out["model"] = model
                return out
        except Exception as exc:  # noqa: BLE001
            last = exc
            log(f"summary with {model} failed {exc!r}"[:300])
    return {"error": repr(last)}


def summarise(U, S, dyn, media_note=None):
    def tone(u):
        return f" [טון: עוררות {u['arousal']:.1f}, חיוביות {u['valence']:.1f}]" if u.get("arousal") is not None else ""
    lines = "\n".join(f"{u['name'] or '?'}: {u['text']}{tone(u)}" for u in U)[:7000]
    if len(" ".join(u["text"] for u in U)) < 40:
        return {"topic": None, "summary": None, "moments": []}
    extra = []
    if S:
        extra.append("צלילים ברקע: " + ", ".join(s["tag"] for s in S[:6]))
    if media_note:
        extra.append("ברקע היה: " + media_note + " (זה לא חלק מהשיחה)")
    if dyn:
        extra.append("זמן דיבור (שניות): " + ", ".join(f"{k}={v}" for k, v in dyn["talk_seconds"].items()))
        if dyn["interruptions"]:
            extra.append(f"קטיעות: {len(dyn['interruptions'])}")
    out = _ollama_json(SUMMARY_TASK, lines + "\n\n" + "\n".join(extra))
    if "error" in out:
        return {"topic": None, "summary": None, "moments": []}
    text = " ".join(u["text"] for u in U)
    names = {u["name"] for u in U if u["name"]}
    out["moments"] = [m for m in (out.get("moments") or []) if isinstance(m, str) and m.strip("״\"' ")[:12] in text][:3]
    out["signals"] = [s for s in (out.get("signals") or []) if s in SIGNALS][:3]
    pp = out.get("per_person") if isinstance(out.get("per_person"), dict) else {}
    out["per_person"] = {k: v for k, v in pp.items() if k in names and isinstance(v, str)}   # no invented people
    return out


DAY_TASK = """אתה כותב סיכום יום קצר של מה שנשמע בבית, לפי סיכומי השיחות של היום בלבד.
עברית, חם ועובדתי, בלי להמציא. החזר JSON: {"summary": "3-5 משפטים על היום", "mood": "חצי משפט על האווירה",
"highlights": ["עד 4 רגעים או נושאים שכדאי לזכור, כל אחד בשורה קצרה"]}"""


def summarize_day(day):
    with db() as c:
        convs = c.execute("SELECT start, end, topic, summary, mood_text, people, moments FROM conversations "
                          "WHERE substr(start,1,10)=? AND status='done' AND summary IS NOT NULL ORDER BY start", (day,)).fetchall()
    if not convs:
        return {"ok": False, "msg": "אין עדיין שיחות מסוכמות ביום הזה"}
    txt = "\n".join(f"{r['start'][11:16]}-{r['end'][11:16]} [{', '.join(json.loads(r['people'] or '[]')) or 'לא מזוהים'}] "
                    f"{r['topic'] or ''}: {r['summary']} ({r['mood_text'] or ''})" for r in convs)[:9000]
    out = _ollama_json(DAY_TASK, txt, num_ctx=12288)
    if "error" in out:
        return {"ok": False, "msg": out["error"]}
    with db() as c:
        c.execute("INSERT OR REPLACE INTO daily (day, summary, highlights, mood, conversations, updated, model) "
                  "VALUES (?,?,?,?,?,?,?)", (day, out.get("summary"), json.dumps(out.get("highlights") or [], ensure_ascii=False),
                                             out.get("mood"), len(convs), iso(datetime.now()), out.get("model")))
    return {"ok": True}


def daily_summaries():
    """Refresh today's day summary when it has new finished conversations (at most every 30 min)."""
    day = datetime.now().strftime("%Y-%m-%d")
    with db() as c:
        n = c.execute("SELECT count(*) FROM conversations WHERE substr(start,1,10)=? AND status='done' "
                      "AND summary IS NOT NULL", (day,)).fetchone()[0]
        d = c.execute("SELECT conversations, updated FROM daily WHERE day=?", (day,)).fetchone()
    if not n or (d and (d["conversations"] == n or
                        (datetime.now() - datetime.fromisoformat(d["updated"])).total_seconds() < 1800)):
        return
    summarize_day(day)


_last_retention = 0


def drop_audio(c, chunk_id, path):
    try:
        os.remove(path)
    except OSError:
        pass
    c.execute("UPDATE chunks SET file=NULL WHERE id=?", (chunk_id,))


def year_estimate(c, db_bytes=0):
    """GB per year if speech is kept as Opus 12 kbps (1500 B/s): from the speech seconds of the last 14 recorded days."""
    row = c.execute("SELECT coalesce(sum(seconds),0), count(DISTINCT substr(start,1,10)) FROM chunks "
                    "WHERE COALESCE(kind,'speech') IN ('speech','import') AND status='done' AND start >= ?",
                    (iso(datetime.now() - timedelta(days=14)),)).fetchone()
    days = max(1, row[1])
    per_day = row[0] / days * 1500
    return {"speech_min_per_day": round(row[0] / days / 60, 1), "est_gb_year": round(per_day * 365 / 1e9, 2),
            "est_gb_year_target": "4-10"}


def storage(c):
    """Space used by Shema + free space on the disk, per month, for the screen."""
    import shutil
    audio = sum(f.stat().st_size for f in AUDIO.rglob("*") if f.is_file()) if AUDIO.exists() else 0
    dbs = sum(f.stat().st_size for f in HOME.glob("home.sqlite*"))
    by_month = {}
    for d in AUDIO.glob("*") if AUDIO.exists() else []:
        if d.is_dir():
            by_month[d.name[:7]] = by_month.get(d.name[:7], 0) + sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
    hours = c.execute("SELECT coalesce(sum(seconds),0)/3600.0 FROM chunks WHERE file IS NOT NULL").fetchone()[0]
    du = shutil.disk_usage(HOME)
    days = c.execute("SELECT count(DISTINCT substr(start,1,10)) FROM chunks WHERE file IS NOT NULL").fetchone()[0] or 1
    per_day = audio / days
    return {"audio_mb": round(audio / 1e6, 1), "db_mb": round(dbs / 1e6, 1), "audio_hours": round(hours, 2),
            "files": c.execute("SELECT count(*) FROM chunks WHERE file IS NOT NULL").fetchone()[0],
            "by_month_mb": {k: round(v / 1e6, 1) for k, v in sorted(by_month.items())},
            "disk_free_gb": round(du.free / 1e9, 1), "disk_total_gb": round(du.total / 1e9, 1),
            "per_day_mb": round(per_day / 1e6, 1),
            "days_left_on_disk": int(du.free * 0.5 / per_day) if per_day else None,   # until half the free space
            "policy": config().get("audio_policy", "archive"),
            **year_estimate(c, dbs)}


def delete_audio_before(day):
    """Manual cleanup from the screen: delete recordings from before `day` (text and numbers stay)."""
    n = 0
    with db() as c:
        for r in c.execute("SELECT id, file FROM chunks WHERE file IS NOT NULL AND substr(start,1,10) < ? AND keep=0",
                           (day,)).fetchall():
            drop_audio(c, r["id"], r["file"])
            n += 1
    log(f"manual cleanup: audio of {n} recordings before {day} deleted")
    return {"ok": True, "deleted": n}


def needs_teaching(c, chunk_id):
    """Does this recording still hold something the user may want to hear before naming it?"""
    u = c.execute("SELECT count(*) FROM utterances WHERE chunk_id=? AND speaker IS NULL AND emb IS NOT NULL "
                  "AND seconds >= 1.2", (chunk_id,)).fetchone()[0]
    s_ = c.execute("SELECT count(*) FROM sounds WHERE chunk_id=? AND tag='צליל לא מזוהה'", (chunk_id,)).fetchone()[0]
    return bool(u or s_)


_opus_ok = None
_last_archive = 0.0


def opus_available():
    """Does this ffmpeg have the libopus encoder? (cached)"""
    global _opus_ok
    if _opus_ok is None:
        import voice_embed as VE
        try:
            out = subprocess.run([VE.FF, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=30).stdout
            _opus_ok = "libopus" in out
        except Exception:  # noqa: BLE001
            _opus_ok = False
    return _opus_ok


def to_opus(src, dst):
    """Mono 16 kHz Opus 12 kbps (voip). True when dst exists and has sound."""
    import voice_embed as VE
    r = subprocess.run([VE.FF, "-v", "error", "-y", "-i", src, "-ac", "1", "-ar", "16000", "-c:a", "libopus",
                        "-b:a", "12k", "-application", "voip", dst], capture_output=True, timeout=300)
    return r.returncode == 0 and os.path.exists(dst) and os.path.getsize(dst) > 200


def archive_candidates(c, limit=None):
    q = ("SELECT id, file, seconds FROM chunks WHERE status='done' AND file IS NOT NULL AND keep=0 "
         "AND COALESCE(kind,'speech') IN ('speech','import') AND lower(file) NOT LIKE '%.ogg' AND lower(file) NOT LIKE '%.opus' "
         "ORDER BY start" + (f" LIMIT {int(limit)}" if limit else ""))
    return c.execute(q).fetchall()


def archive_pass(cfg=None, limit=200):
    """audio_policy 'archive': convert up to [limit] processed speech/import recordings to Opus 12k (the original is
    deleted only after the new file is verified), drop what policy says goes."""
    cfg = cfg or config()
    conv = freed = dropped = 0
    with db() as c:
        # sounds: as soon as nothing in them needs teaching (or after teach_days); enrolment: right after processing
        for r in c.execute("SELECT id, file, start, COALESCE(kind,'speech') k FROM chunks WHERE status='done' AND file IS NOT NULL "
                           "AND keep=0 AND COALESCE(kind,'speech') IN ('sound','enroll')").fetchall():
            age = (datetime.now() - datetime.fromisoformat(r["start"])).total_seconds() / 86400
            if r["k"] == "enroll" or age > cfg.get("teach_days", TEACH_DAYS) or not needs_teaching(c, r["id"]):
                drop_audio(c, r["id"], r["file"]); dropped += 1
        rows = archive_candidates(c, limit)
        if rows and not opus_available():
            log("archive: this ffmpeg has no libopus, speech recordings stay as they are")
            rows = []
        for r in rows:
            if not os.path.exists(r["file"]):
                c.execute("UPDATE chunks SET file=NULL WHERE id=?", (r["id"],)); continue
            dst = str(Path(r["file"]).with_suffix(".ogg"))
            if not to_opus(r["file"], dst):
                try:
                    os.remove(dst)
                except OSError:
                    pass
                continue
            freed += os.path.getsize(r["file"]) - os.path.getsize(dst)
            c.execute("UPDATE chunks SET file=? WHERE id=?", (dst, r["id"]))
            c.commit()
            try:
                os.remove(r["file"])
            except OSError:
                pass
            conv += 1
    if conv or dropped:
        log(f"archive: {conv} recordings -> Opus 12k (freed {freed / 1e6:.1f} MB), {dropped} sound/enrol recordings deleted")
    return {"converted": conv, "freed_mb": round(freed / 1e6, 1), "dropped": dropped}


def archive_dry_run():
    """What --archive-now would do: how many recordings, how much space now, and the estimate afterwards."""
    with db() as c:
        rows = archive_candidates(c)
        now = est = 0
        for r in rows:
            if r["file"] and os.path.exists(r["file"]):
                now += os.path.getsize(r["file"])
                est += int((r["seconds"] or 0) * 1500 * 1.03)         # 12 kbps + container
        snd = c.execute("SELECT id, file FROM chunks WHERE status='done' AND file IS NOT NULL AND keep=0 "
                        "AND COALESCE(kind,'speech') IN ('sound','enroll')").fetchall()
        snd_mb = sum(os.path.getsize(r["file"]) for r in snd if r["file"] and os.path.exists(r["file"])) / 1e6
    return {"to_convert": len(rows), "now_mb": round(now / 1e6, 1), "after_mb": round(est / 1e6, 1),
            "freed_mb": round((now - est) / 1e6, 1), "sound_enroll_files": len(snd), "sound_enroll_mb": round(snd_mb, 1),
            "opus_in_ffmpeg": opus_available()}


def retention(force=False):
    """Apply the audio policy. Runs every 10 minutes from the idle worker (and once per analysed chunk)."""
    global _last_retention, _last_archive
    if not force and time.time() - _last_retention < 600:
        return
    _last_retention = time.time()
    cfg = config()
    policy = cfg.get("audio_policy", "archive")
    n = 0
    if policy == "archive":
        if time.time() - _last_archive < 120:              # called after every analysed chunk: do the work at most every 2 min
            return
        _last_archive = time.time()
        try:
            archive_pass(cfg)
        except Exception as exc:  # noqa: BLE001
            log(f"archive pass failed {exc!r}")
        return
    with db() as c:
        rows = c.execute("SELECT id, file, start, keep FROM chunks WHERE status IN ('done','failed') "
                         "AND file IS NOT NULL").fetchall()
        for r in rows:
            if r["keep"]:
                continue
            age_days = (datetime.now() - datetime.fromisoformat(r["start"])).total_seconds() / 86400
            if policy == "keep":
                continue
            if policy == "none":
                drop = True
            elif policy == "days":
                drop = age_days > cfg.get("audio_days", AUDIO_DAYS)
            else:                                   # "teach"
                drop = age_days > cfg.get("teach_days", TEACH_DAYS) or not needs_teaching(c, r["id"])
            if drop:
                drop_audio(c, r["id"], r["file"])
                n += 1
    if n:
        log(f"audio policy '{policy}': {n} recordings deleted (text, voice vectors, tone and sounds kept)")


# ------------------------------------------------------------------ search over conversations, questions, tasks
def index_conversation(cid):
    """Keep the full-text index of finished conversations current (Hebrew prefix forms are indexed too)."""
    from he_text import expand_he
    with db() as c:
        conv = c.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
        U = c.execute("SELECT name, text FROM utterances WHERE conv_id=? AND media IS NULL AND text!='' ORDER BY t0", (cid,)).fetchall()
        c.execute("DELETE FROM conv_fts WHERE conv_id=?", (cid,))
        if not conv or not U:
            return
        body = "\n".join(f"{u['name'] or '?'}: {u['text']}" for u in U)
        head = " . ".join(x for x in (conv["topic"], conv["summary"], conv["place"], conv["cal"]) if x)
        people = ", ".join(json.loads(conv["people"] or "[]"))
        c.execute("INSERT INTO conv_fts (conv_id, topic, people, body) VALUES (?,?,?,?)",
                  (cid, expand_he(head), people, expand_he(body)))


def reindex_all():
    with db() as c:
        have = c.execute("SELECT count(*) FROM conv_fts").fetchone()[0]
        ids = [r[0] for r in c.execute("SELECT id FROM conversations WHERE status='done'")]
    if have < len(ids):
        for i in ids:
            index_conversation(i)


def _fts_expr(q, mode="AND"):
    from he_text import he_variants
    parts = []
    for t in re.findall(r"\w+", q or ""):
        vs = list(dict.fromkeys(he_variants(t)))[:6] or [t]
        parts.append("(" + " OR ".join('"%s"' % v.replace('"', "") for v in vs) + ")")
    return f" {mode} ".join(parts)


def range_bounds(r):
    """today / yesterday / week (7 days) / month (30 days) / all  ->  (from, until) as ISO strings or None."""
    now = datetime.now()
    d0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if r == "today":
        return iso(d0), None
    if r == "yesterday":
        return iso(d0 - timedelta(days=1)), iso(d0)
    if r == "week":
        return iso(d0 - timedelta(days=6)), None
    if r == "month":
        return iso(d0 - timedelta(days=29)), None
    return None, None


def list_convs(r, limit=60):
    lo, hi = range_bounds(r)
    with db() as c:
        rows = c.execute("SELECT id, start, end, topic, summary, people, place, away, marked FROM conversations "
                         "WHERE status='done' AND (? IS NULL OR start>=?) AND (? IS NULL OR start<?) "
                         "ORDER BY start DESC LIMIT ?", (lo, lo, hi, hi, limit)).fetchall()
    return [dict(x, snippet=None) for x in rows]


def search_convs(q, limit=12, r="all"):
    out = []
    lo, hi = range_bounds(r)
    for mode in ("AND", "OR"):
        expr = _fts_expr(q, mode)
        if not expr:
            return []
        with db() as c:
            rows = c.execute("SELECT conv_id, snippet(conv_fts, 3, '«', '»', ' … ', 20) AS snip FROM conv_fts "
                             "WHERE conv_fts MATCH ? ORDER BY rank LIMIT ?", (expr, limit * 4)).fetchall()
            for x in rows:
                k = c.execute("SELECT id, start, end, topic, summary, people, place, away, marked FROM conversations WHERE id=?",
                              (x["conv_id"],)).fetchone()
                if k and (lo is None or k["start"] >= lo) and (hi is None or k["start"] < hi):
                    out.append(dict(k, snippet=x["snip"]))
        if out:
            break
    return out[:limit]


RANGE_TASK = """אתה כותב סיכום של מה שנשמע בשיחות בתקופה מסוימת, לפי סיכומי השיחות בלבד. עברית, חם ועובדתי, בלי להמציא.
החזר JSON: {"summary": "4-7 משפטים: מה היה בתקופה, נושאים חוזרים, אנשים", "highlights": ["עד 6 רגעים או נושאים שכדאי לזכור, כל אחד בשורה קצרה, עם היום"],
"by_person": {"שם": "משפט אחד על מה שהאדם הזה עסק בו"}}"""


EMO_HE = {"angry": "כעס", "disgusted": "גועל", "fearful": "פחד", "happy": "שמחה", "neutral": "ניטרלי", "other": "אחר",
          "sad": "עצב", "surprised": "הפתעה", "<unk>": "לא ידוע"}
EMO_SURE = 0.8            # the emotion model is shown only when it is this sure (it calls calm Hebrew "sad" a lot)


def _prev_bounds(r):
    """The period of the same length right before the range (for "more / less than before")."""
    lo, hi = range_bounds(r)
    if not lo:
        return None, None
    a = datetime.fromisoformat(lo)
    b = datetime.fromisoformat(hi) if hi else datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return iso(a - (b - a)), lo


def stats(r="today"):
    """Who talked how much, in what mood, in a period: minutes, share, lines, words, pace, voice mood vs the
    person's usual, confident emotions, per-day minutes, background (TV / music), and the same period before."""
    lo, hi = range_bounds(r)
    plo, phi = _prev_bounds(r)
    where = "media IS NULL AND text!='' AND (? IS NULL OR t0>=?) AND (? IS NULL OR t0<?)"
    with db() as c:
        rows = c.execute(f"SELECT speaker, coalesce(name,'') AS name, seconds, text, valence, arousal, emotion, emotion_p, syll_per_s, "
                         f"substr(t0,1,10) AS day FROM utterances WHERE {where}", (lo, lo, hi, hi)).fetchall()
        prev = c.execute(f"SELECT coalesce(name,'') AS name, sum(seconds) AS s FROM utterances WHERE {where} GROUP BY name",
                         (plo, plo, phi, phi)).fetchall() if plo else []
        media = [dict(x) for x in c.execute("SELECT media, round(sum(seconds)/60.0,1) AS minutes FROM utterances WHERE media IS NOT NULL "
                                            "AND (? IS NULL OR t0>=?) AND (? IS NULL OR t0<?) GROUP BY media", (lo, lo, hi, hi))]
        sounds = [dict(x) for x in c.execute("SELECT tag, count(*) AS n FROM sounds WHERE tag NOT IN ('צליל לא מזוהה') "
                                             "AND (? IS NULL OR t0>=?) AND (? IS NULL OR t0<?) GROUP BY tag ORDER BY n DESC LIMIT 8",
                                             (lo, lo, hi, hi))]
        convs = c.execute("SELECT count(*) FROM conversations WHERE status='done' AND (? IS NULL OR start>=?) AND (? IS NULL OR start<?)",
                          (lo, lo, hi, hi)).fetchone()[0]
        until = (hi or iso(datetime.now()))
        by = {}
        for u in rows:
            k = u["speaker"] or "?"
            d = by.setdefault(k, {"id": k, "name": u["name"] or "קול לא מזוהה", "seconds": 0.0, "lines": 0, "words": 0, "v": [], "a": [],
                                  "emo": {}, "sps": [], "days": {}})
            d["seconds"] += u["seconds"] or 0
            d["lines"] += 1
            d["words"] += len((u["text"] or "").split())
            if u["valence"] is not None:
                d["v"].append(u["valence"]); d["a"].append(u["arousal"])
            if u["emotion"] and (u["emotion_p"] or 0) >= EMO_SURE:
                d["emo"][u["emotion"]] = d["emo"].get(u["emotion"], 0) + 1
            if u["syll_per_s"]:
                d["sps"].append(u["syll_per_s"])
            d["days"][u["day"]] = d["days"].get(u["day"], 0) + (u["seconds"] or 0)
        total = sum(d["seconds"] for d in by.values()) or 1
        base = baselines(c, {k for k in by if k != "?"}, until)
    prev_by = {x["name"] or "קול לא מזוהה": x["s"] or 0 for x in prev}
    people = []
    for d in by.values():
        b = base.get(d["id"]) or {}
        v = sum(d["v"]) / len(d["v"]) if d["v"] else None
        a = sum(d["a"]) / len(d["a"]) if d["a"] else None
        emo_n = sum(d["emo"].values())
        people.append({
            "id": d["id"], "name": d["name"], "minutes": round(d["seconds"] / 60, 1), "share": round(d["seconds"] / total, 3),
            "lines": d["lines"], "words": d["words"],
            "pace": round(sum(d["sps"]) / len(d["sps"]), 2) if d["sps"] else None,
            "valence": round(v, 2) if v is not None else None, "arousal": round(a, 2) if a is not None else None,
            "valence_vs_usual": round(v - b["valence"], 2) if v is not None and b.get("valence") is not None else None,
            "arousal_vs_usual": round(a - b["arousal"], 2) if a is not None and b.get("arousal") is not None else None,
            "emotions": [{"emotion": EMO_HE.get(k, k), "share": round(n / emo_n, 2)} for k, n in
                         sorted(d["emo"].items(), key=lambda x: -x[1])[:4]] if emo_n >= 5 else [],
            "minutes_before": round(prev_by.get(d["name"], 0) / 60, 1) if plo else None})
    people.sort(key=lambda x: -x["minutes"])
    days = {}
    for d in by.values():
        for k, v in d["days"].items():
            days[k] = days.get(k, 0) + v
    return {"range": r, "from": lo, "conversations": convs, "minutes": round(total / 60, 1) if by else 0,
            "unnamed_share": round(by["?"]["seconds"] / total, 2) if "?" in by else 0, "people": people,
            "per_day": [{"day": k, "minutes": round(v / 60, 1)} for k, v in sorted(days.items())],
            "background": media, "sounds": sounds,
            "minutes_before": round(sum(prev_by.values()) / 60, 1) if plo else None}


def range_summary(r):
    """A summary of a whole period built from the summaries of its conversations (and a count per day)."""
    lo, hi = range_bounds(r)
    with db() as c:
        convs = c.execute("SELECT start, topic, summary, mood_text, people, place FROM conversations WHERE status='done' "
                          "AND summary IS NOT NULL AND (? IS NULL OR start>=?) AND (? IS NULL OR start<?) ORDER BY start",
                          (lo, lo, hi, hi)).fetchall()
        per_day = [dict(x) for x in c.execute("SELECT substr(start,1,10) AS day, count(*) AS n, round(sum(seconds)/60.0) AS minutes "
                                              "FROM conversations WHERE status='done' AND (? IS NULL OR start>=?) AND (? IS NULL OR start<?) "
                                              "GROUP BY day ORDER BY day", (lo, lo, hi, hi))]
    if not convs:
        return {"ok": False, "msg": "אין שיחות מסוכמות בתקופה הזאת", "per_day": per_day}
    txt = "\n".join(f"{x['start'][5:10]} {x['start'][11:16]} [{', '.join(json.loads(x['people'] or '[]')) or 'לא מזוהים'}"
                     f"{' · ' + x['place'] if x['place'] and x['place'] != 'בית' else ''}] {x['topic'] or ''}: {x['summary']}"
                     for x in convs)[:14000]
    out = _ollama_json(RANGE_TASK, txt, num_ctx=16384)
    if "error" in out:
        return {"ok": False, "msg": out["error"], "per_day": per_day}
    return {"ok": True, "range": r, "conversations": len(convs), "per_day": per_day, "summary": out.get("summary"),
            "highlights": [h for h in (out.get("highlights") or []) if isinstance(h, str)][:6],
            "by_person": {k: v for k, v in (out.get("by_person") or {}).items() if isinstance(v, str)}}


ASK_TASK = """אתה עונה על שאלה על שיחות שהוקלטו, רק לפי קטעי השיחות שלפניך. אל תמציא. אם התשובה לא כתובה שם, כתוב שלא נמצא.
ציין תאריך ושם דובר כשהם ברורים. החזר JSON: {"answer": "תשובה קצרה בעברית", "conv_ids": [מספרי השיחות שהתשובה מבוססת עליהן]}"""


def ask(q, r="all"):
    hits = search_convs(q, 6, r)
    if not hits:
        return {"answer": "לא מצאתי שיחה שקשורה לזה.", "conversations": []}
    with db() as c:
        blocks = []
        for h in hits:
            U = c.execute("SELECT name, text FROM utterances WHERE conv_id=? AND media IS NULL AND text!='' ORDER BY t0",
                          (h["id"],)).fetchall()
            blocks.append(f"[שיחה {h['id']} · {h['start'][:16]} · {h['place'] or ''}]\n" +
                          "\n".join(f"{u['name'] or '?'}: {u['text']}" for u in U)[:1800])
    out = _ollama_json(ASK_TASK, "שאלה: " + q + "\n\n" + "\n\n".join(blocks), num_ctx=12288)
    ids = {h["id"] for h in hits}
    cited = [i for i in (out.get("conv_ids") or []) if i in ids]
    return {"answer": out.get("answer") if "error" not in out else None, "conversations": [h for h in hits if h["id"] in (cited or ids)]}


TASKS_TASK = """אתה מחלץ התחייבויות מתמלול שיחה בעברית: רק דברים שמישהו לקח על עצמו או שסוכמו במפורש בין אנשים
("אני אשלח לך מחר", "נקבע ליום שלישי", "אני אבדוק ואחזור אליך", "צריך להגיש עד סוף החודש").
לא בקשות או הוראות יומיומיות (למשל "תביא", "תסגור", "תעשה שיעורי בית"), לא שאלות ולא שיחה כללית. אל תמציא.
החזר JSON: {"tasks": [{"who": "שם מי שהתחייב או ? אם לא ברור", "what": "מה צריך לקרות, קצר", "when": "מתי, רק אם נאמר, אחרת null",
"quote": "ציטוט מילה במילה מהתמלול, עד 12 מילים"}]}. אם אין כלום: {"tasks": []}"""


def extract_tasks(cid, U, force=False):
    """Commitments from conversations away from home (and marked ones); at home only with config "tasks_at_home"."""
    text = " ".join(u["text"] for u in U)
    if len(text.split()) < 25:
        return
    with db() as c:
        k = c.execute("SELECT away, marked FROM conversations WHERE id=?", (cid,)).fetchone()
    if not force and not (k and (k["away"] or k["marked"])) and not config().get("tasks_at_home"):
        return
    out = _ollama_json(TASKS_TASK, "\n".join(f"{u['name'] or '?'}: {u['text']}" for u in U)[:7000])
    if "error" in out:
        return
    norm = " ".join(text.split())
    with db() as c:
        c.execute("DELETE FROM tasks WHERE conv_id=? AND state='open'", (cid,))
        for t in (out.get("tasks") or [])[:6]:
            if not isinstance(t, dict) or not isinstance(t.get("what"), str):
                continue
            quote = " ".join(str(t.get("quote") or "").split())
            if len(quote) < 8 or quote[:14] not in norm:          # must be something that was really said
                continue
            c.execute("INSERT INTO tasks (conv_id, who, what, due, quote, created) VALUES (?,?,?,?,?,?)",
                      (cid, str(t.get("who") or "?")[:40], t["what"][:200], (str(t["when"])[:40] if t.get("when") else None),
                       quote[:200], iso(datetime.now())))


FILLERS = {"אה", "אמ", "אממ", "אמממ", "כאילו", "יעני", "נו", "אהה", "אההה"}


def me_stats(c, day):
    """The owner's own speech that day: time, share of the talk, pace vs. usual, fillers, interruptions."""
    oid = owner_id()
    mine = c.execute("SELECT seconds, text, syll_per_s, conv_id, name FROM utterances WHERE speaker=? AND substr(t0,1,10)=? "
                     "AND media IS NULL", (oid, day)).fetchall()
    if not mine:
        return {"day": day, "seconds": 0}
    convs = sorted({r["conv_id"] for r in mine})
    ph = ",".join("?" * len(convs))
    everyone = c.execute(f"SELECT coalesce(sum(seconds),0) FROM utterances WHERE conv_id IN ({ph}) AND media IS NULL", convs).fetchone()[0]
    words = [w for r in mine for w in _norm_words(r["text"])]
    fill = sum(1 for w in words if w in FILLERS)
    me_name = mine[0]["name"]
    cut_by, cut_me = 0, 0
    for k in c.execute(f"SELECT interruptions FROM conversations WHERE id IN ({ph})", convs):
        for i in json.loads(k["interruptions"] or "[]"):
            cut_by += i.get("who") == me_name
            cut_me += i.get("cut") == me_name
    base = baselines(c, {oid}, day + "T23:59:59").get(oid) or {}
    syl = [r["syll_per_s"] for r in mine if r["syll_per_s"]]
    pace = round(sum(syl) / len(syl), 2) if syl else None
    where = {}
    for r in c.execute(f"SELECT coalesce(k.place, 'לא ידוע') AS place, sum(u.seconds) AS s FROM utterances u JOIN conversations k "
                       f"ON k.id=u.conv_id WHERE u.speaker=? AND substr(u.t0,1,10)=? GROUP BY place", (oid, day)):
        where[r["place"]] = round(r["s"] / 60, 1)
    return {"day": day, "seconds": round(sum(r["seconds"] for r in mine)), "words": len(words),
            "share": round(sum(r["seconds"] for r in mine) / everyone, 2) if everyone else None,
            "conversations": len(convs), "fillers_per_100": round(100 * fill / len(words), 1) if words else None,
            "pace": pace, "pace_usual": round(base["syll_per_s"], 2) if base.get("syll_per_s") else None,
            "cut_others": cut_by, "was_cut": cut_me, "where_min": where}


def digest(device=None):
    day = datetime.now().strftime("%Y-%m-%d")
    with db() as c:
        d = c.execute("SELECT summary, conversations FROM daily WHERE day=?", (day,)).fetchone()
        tasks = c.execute("SELECT count(*) FROM tasks WHERE state='open'").fetchone()[0]
        teach = c.execute("SELECT count(*) FROM utterances WHERE speaker IS NULL AND media IS NULL AND emb IS NOT NULL "
                          "AND seconds>=1.2").fetchone()[0]
        n = c.execute("SELECT count(*) FROM conversations WHERE substr(start,1,10)=? AND status='done'", (day,)).fetchone()[0]
    try:
        import asr_update
        notice = asr_update.status().get("note")
    except Exception:  # noqa: BLE001
        notice = None
    return {"day": day, "ready": bool(d and d["summary"]), "summary": d["summary"] if d else None, "conversations": n,
            "tasks_open": tasks, "teach": min(teach, 99), "notice": notice}


def privacy_state(c):
    names = {r["id"]: r["name"] for r in c.execute("SELECT id, name FROM home_people")}
    gn = known_names()
    dev = {r["device"]: r["n"] for r in c.execute("SELECT device, count(*) AS n FROM voice_bank WHERE speaker=? "
                                                   "GROUP BY device", (owner_id(),))}
    dropped = [dict(r) for r in c.execute("SELECT reason, count(*) AS n, round(sum(seconds)) AS seconds, sum(utterances) AS utterances "
                                          "FROM dropped WHERE day>=? GROUP BY reason",
                                          ((datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d"),))]
    cfg = config()
    return {"owner": owner_id(), "owner_name": name_of(c, owner_id()), "owner_samples": dev,
            "optout": [{"id": p, "name": names.get(p) or (gn.get(p) or {}).get("name") or p} for p in cfg.get("optout") or []],
            "places": [dict(r) for r in c.execute("SELECT id, name, lat, lon, r_m, mute FROM places ORDER BY name")],
            "dropped_14d": dropped, "owner_min_seconds": cfg.get("owner_min_seconds", OWNER_MIN_SECONDS),
            "bystander_db": cfg.get("bystander_db", 12), "import_dirs": cfg.get("import_dirs") or [],
            "min_samples": OWNER_MIN_SAMPLES}


def conv_context(c, cid):
    """Where / when the conversation was and which calendar event."""
    k = c.execute("SELECT start, end, place, cal, lat, lon, marked FROM conversations WHERE id=?", (cid,)).fetchone()
    if not k:
        return None
    return dict(k, photos=[])


# ------------------------------------------------------------------ pairing a phone (QR on this PC's screen)
def lan_ip():
    """This PC's address on the home network (no packet is sent)."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def tailscale_ip():
    """config.json "remote" (written by the installer), else `tailscale ip -4` when Tailscale is installed."""
    cfg = config()
    if cfg.get("remote"):
        return cfg["remote"]
    import shutil
    exe = shutil.which("tailscale") or next((p for p in (r"C:\Program Files\Tailscale\tailscale.exe",) if os.path.exists(p)), None)
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=5).stdout.strip().splitlines()
        return out[0].strip() if out and re.fullmatch(r"100\.\d+\.\d+\.\d+", out[0].strip()) else None
    except Exception:  # noqa: BLE001
        return None


def pair_info():
    """What the "connect a phone" card shows (this PC only: it holds the access code)."""
    cfg = config()
    server = f"http://{lan_ip()}:{PORT}"
    ts = tailscale_ip()
    remote = f"http://{ts}:{PORT}" if ts else None
    q = {"server": server, "token": cfg["token"]}
    if remote:
        q["remote"] = remote
    return {"server": server, "remote": remote, "token": cfg["token"],
            "uri": "shema://pair?" + urllib.parse.urlencode(q), "apk": apk_path() is not None,
            "owner_name": cfg.get("owner_name")}


def apk_path():
    for p in (paths.APK, PROJ.parent / "app.apk"):
        if p.exists():
            return p
    return None


AUDIO_EXT = {".m4a", ".mp3", ".ogg", ".opus", ".oga", ".amr", ".wav", ".aac", ".3gp", ".wma", ".flac"}
_last_import_scan = 0


def scan_imports():
    """Folders the user listed in config.json "import_dirs" (voice messages, call recordings that
    sync to the PC): every new audio file becomes its own conversation."""
    global _last_import_scan
    dirs = config().get("import_dirs") or []
    if not dirs or time.time() - _last_import_scan < 60:
        return
    _last_import_scan = time.time()
    for d in dirs:
        try:
            files = [f for f in Path(d).rglob("*") if f.is_file() and f.suffix.lower() in AUDIO_EXT]
        except OSError:
            continue
        for f in files:
            try:
                st = f.stat()
                if time.time() - st.st_mtime < 30 or st.st_size > MAX_BODY * 4:
                    continue
                with db() as c:
                    if c.execute("SELECT 1 FROM imports WHERE path=? AND mtime=?", (str(f), st.st_mtime)).fetchone():
                        continue
                cid = store_chunk(f.read_bytes(), "import", iso(datetime.fromtimestamp(st.st_mtime)), f.suffix.lstrip(".").lower(),
                                  "import", {"role": "home", "home": 1})
                with db() as c:
                    c.execute("INSERT OR REPLACE INTO imports (path, mtime, chunk_id) VALUES (?,?,?)", (str(f), st.st_mtime, cid))
                log(f"import queued: {f.name}")
            except OSError:
                continue


# ------------------------------------------------------------------ read API for the screen
def _clean(rows):
    out = []
    for r in rows:
        d = dict(r)
        d.pop("emb", None)
        d.pop("media_text", None)
        out.append(d)
    return out


REASON_HE = {"": "הוקלט", "rec": "הוקלט", "private": "פרטי", "cal": "פרטי (יומן)", "mute": "פרטי (השתקה)", "pause": "מושהה",
             "battery": "סוללה", "busy": "מיקרופון תפוס", "away": "מחוץ לבית (טלפון בית)", "enroll_needed": "ממתין ללימוד קול",
             "off": "כבוי ידנית", "killed": "האפליקציה/הטלפון נעצרו", "stall": "המיקרופון נתקע", "unknown": "הטלפון לא ענה",
             "nolog": "אין יומן מהטלפון (גרסה ישנה של האפליקציה)"}


def coverage(c, day=None):
    """Per phone, 96 cells of 15 minutes: what its microphone did (from its own timeline, sent with every heartbeat).
    A cell is 'rec' when it was recording for at least half of it, else the reason that covers most of it,
    else 'unknown' = the phone said nothing (off, no network and no log)."""
    day = day or datetime.now().strftime("%Y-%m-%d")
    d0 = datetime.fromisoformat(day)
    now = datetime.now()
    out = []
    devs = {r[0] for r in c.execute("SELECT DISTINCT device FROM phone_timeline WHERE substr(e,1,10)>=? AND substr(s,1,10)<=?", (day, day))}
    devs |= {r[0] for r in c.execute("SELECT DISTINCT device FROM chunks WHERE substr(start,1,10)=? AND COALESCE(kind,'speech')!='import'", (day,))}
    try:
        ph = json.load(open(PHONES_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        ph = {}
    devs |= set(ph)
    for dev in sorted(devs):
        rows = c.execute("SELECT s, e, reason FROM phone_timeline WHERE device=? AND substr(e,1,10)>=? AND substr(s,1,10)<=?",
                         (dev, day, day)).fetchall()
        spans = [(datetime.fromisoformat(r["s"]), datetime.fromisoformat(r["e"]), r["reason"] or "rec") for r in rows]
        chunk_t = [datetime.fromisoformat(r[0]) for r in c.execute(
            "SELECT start FROM chunks WHERE device=? AND substr(start,1,10)=? AND COALESCE(kind,'speech') IN ('speech','sound')", (dev, day))]
        fl = c.execute("SELECT min(s) FROM phone_timeline WHERE device=?", (dev,)).fetchone()[0]
        first_log = datetime.fromisoformat(fl) if fl else None        # before this the phone ran the old app: no log
        cells, tot = [], {}
        for i in range(96):
            a = d0 + timedelta(minutes=15 * i)
            b = a + timedelta(minutes=15)
            if a > now:
                cells.append("future"); continue
            span_s = ((min(b, now) - a).total_seconds()) or 1
            acc = {}
            for s0, e0, r in spans:
                ov = (min(b, e0, now) - max(a, s0)).total_seconds()
                if ov > 0:
                    acc[r] = acc.get(r, 0) + ov
            rec = acc.pop("rec", 0)
            if rec >= span_s * 0.5 or (not acc and any(a <= t < b for t in chunk_t)):
                st = "rec"
            elif acc and max(acc.values()) >= span_s * 0.3:
                st = max(acc, key=acc.get)
            elif rec >= span_s * 0.2:
                st = "rec"
            else:
                st = "unknown" if (first_log and b > first_log) else "nolog"   # no log yet (old app) is not "silent"
            cells.append(st)
            tot[st] = tot.get(st, 0) + (span_s / 3600)
        name = (config().get("phone_names") or {}).get(dev, dev)
        out.append({"device": name, "code": dev, "cells": cells,
                    "hours": {k: round(v, 2) for k, v in tot.items() if k != "future"}})
    return {"day": day, "phones": out, "reasons": REASON_HE}


ENV_HINTS = (("Application Control", "מדיניות אבטחה של Windows חסמה קובץ"), ("too long", "שם קובץ/פקודה ארוכים מדי"),
             ("DLL load", "טעינת ספרייה נכשלה"), ("CUDA", "שגיאת כרטיס מסך"), ("empty", "קובץ ריק"), ("moov", "קובץ חתוך"))


def health(c):
    """Chunks that failed in the last 24 hours (count + reasons) and the backlog."""
    since = iso(datetime.now() - timedelta(hours=24))
    rows = c.execute("SELECT error, count(*) n FROM chunks WHERE status='failed' AND received>=? GROUP BY error", (since,)).fetchall()
    reasons, total = {}, 0
    for r in rows:
        txt = r["error"] or "?"
        key = next((h for k, h in ENV_HINTS if k.lower() in txt.lower()), txt[:80])
        reasons[key] = reasons.get(key, 0) + r["n"]
        total += r["n"]
    n = {r["status"]: r["n"] for r in c.execute("SELECT status, count(*) AS n FROM chunks GROUP BY status")}
    return {"failed_24h": total, "reasons": reasons, "alarm": total > 20, "backlog": n.get("new", 0),
            "requeued_total": c.execute("SELECT coalesce(sum(tries),0) FROM chunks").fetchone()[0]}


def add_gold(c, utt_id, text):
    """Cut one utterance's audio into gold/<id>.ogg (data folder) with its (corrected) text: the set asr_update.py measures on."""
    r = c.execute("SELECT u.t0, u.t1, u.text, k.start, k.file FROM utterances u JOIN chunks k ON k.id=u.chunk_id WHERE u.id=?",
                  (utt_id,)).fetchone()
    if not r or not r["file"] or not os.path.exists(r["file"]):
        return {"ok": False, "msg": "השמע של המשפט הזה כבר נמחק"}
    import voice_embed as VE
    text = (text or r["text"] or "").strip()
    if not text:
        return {"ok": False, "msg": "אין טקסט"}
    gold = HOME / "gold"
    gold.mkdir(parents=True, exist_ok=True)
    off = (datetime.fromisoformat(r["t0"]) - datetime.fromisoformat(r["start"])).total_seconds()
    dur = (datetime.fromisoformat(r["t1"]) - datetime.fromisoformat(r["t0"])).total_seconds()
    dst = gold / f"u{utt_id}.ogg"
    p = subprocess.run([VE.FF, "-v", "error", "-y", "-ss", f"{max(0, off - 0.2):.2f}", "-t", f"{dur + 0.4:.2f}", "-i", r["file"],
                        "-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "24k", str(dst)], capture_output=True)
    if p.returncode != 0 or not dst.exists():
        return {"ok": False, "msg": "החיתוך נכשל"}
    dst.with_suffix(".txt").write_text(text, encoding="utf-8")
    return {"ok": True, "gold_items": len(list(gold.glob("*.txt")))}


def api(path, qs):
    with db() as c:
        if path == "/home/api/status":
            n = {r["status"]: r["n"] for r in c.execute("SELECT status, count(*) AS n FROM chunks GROUP BY status")}
            last = c.execute("SELECT max(received) FROM chunks").fetchone()[0]
            return {"chunks": n, "last_received": last, "worker_busy": WORKER.busy if WORKER else None,
                    "paused_until": config().get("paused_until"), "phones": phones(), "pc_has_mic": False,
                    "audio_policy": config().get("audio_policy", "archive"),
                    "audio_kept": c.execute("SELECT count(*) FROM chunks WHERE file IS NOT NULL").fetchone()[0],
                    "audio_mb": round(sum(f.stat().st_size for f in AUDIO.rglob("*") if f.is_file()) / 1e6, 1),
                    "now_ms": int(time.time() * 1000), "owner_min_samples": OWNER_MIN_SAMPLES,
                    "owner_enrolled": owner_enrolled(c, clean_device(qs["device"][0])) if "device" in qs else None,
                    "digest": digest() if "device" in qs else None}
        if path == "/home/api/coverage":
            return coverage(c, (qs.get("day") or [None])[0])
        if path == "/home/api/health":
            return health(c)
        if path == "/home/api/asr":
            import asr_update
            return asr_update.status()
        if path == "/home/api/live":
            since = iso(datetime.now() - timedelta(minutes=15))
            U = _clean(c.execute("SELECT * FROM utterances WHERE t0>=? ORDER BY t0 DESC LIMIT 40", (since,)).fetchall())[::-1]
            conv = c.execute("SELECT id, topic, summary, mood_text, status, summary_n FROM conversations "
                             "WHERE end>=? ORDER BY end DESC LIMIT 1", (since,)).fetchone()
            q = c.execute("SELECT count(*) FROM chunks WHERE status='new'").fetchone()[0]
            snd = [dict(r) for r in c.execute("SELECT tag, t0, score FROM sounds WHERE t0>=? ORDER BY t0 DESC LIMIT 6", (since,))]
            return {"utterances": U, "conversation": dict(conv) if conv else None, "queue": q,
                    "worker_busy": WORKER.busy if WORKER else None, "sounds": snd, "now": iso(datetime.now())}
        if path == "/home/api/people":
            return people_list(c)
        if path == "/home/api/search":
            q, r = qs.get("q", [""])[0].strip(), qs.get("r", ["all"])[0]
            return {"q": q, "range": r, "results": search_convs(q, 20, r) if q else list_convs(r)}
        if path == "/home/api/ask":
            return ask(qs.get("q", [""])[0], qs.get("r", ["all"])[0])
        if path == "/home/api/stats":
            return stats(qs.get("r", ["today"])[0])
        if path == "/home/api/range_summary":
            return range_summary(qs.get("r", ["week"])[0])
        if path == "/home/api/tasks":
            st = qs.get("state", ["open"])[0]
            return [dict(r) for r in c.execute(
                "SELECT t.*, k.start AS conv_start, k.place AS place FROM tasks t LEFT JOIN conversations k ON k.id=t.conv_id "
                "WHERE t.state=? ORDER BY t.created DESC LIMIT 100", (st,))]
        if path == "/home/api/me":
            return me_stats(c, qs.get("d", [datetime.now().strftime("%Y-%m-%d")])[0])
        if path == "/home/api/digest":
            return digest()
        if path == "/home/api/privacy":
            return privacy_state(c)
        if path == "/home/api/conv_context":
            return conv_context(c, int(qs.get("id", ["0"])[0]))
        if path == "/home/api/storage":
            return storage(c)
        if path == "/home/api/sounds":
            return sounds_day(c, qs.get("d", [datetime.now().strftime("%Y-%m-%d")])[0])
        if path == "/home/api/teach":
            return teach_queue(c, mode=(qs.get("m") or ["smart"])[0])
        if path == "/home/api/people_stats":
            return people_stats(c)
        if path == "/home/api/days":
            return [dict(r) for r in c.execute(
                "SELECT substr(start,1,10) AS day, count(*) AS conversations, sum(seconds) AS seconds "
                "FROM conversations WHERE status!='empty' GROUP BY day ORDER BY day DESC LIMIT 60")]
        if path == "/home/api/day":
            day = qs.get("d", [datetime.now().strftime("%Y-%m-%d")])[0]
            convs = [dict(r) for r in c.execute("SELECT * FROM conversations WHERE substr(start,1,10)=? "
                                                "AND status!='empty' ORDER BY start", (day,))]
            sounds = [dict(r) for r in c.execute("SELECT tag, t0, t1, score FROM sounds WHERE substr(t0,1,10)=? "
                                                 "ORDER BY t0", (day,))]
            talk = [dict(r) for r in c.execute("SELECT coalesce(name,'?') AS name, round(sum(seconds)/60.0,1) AS minutes, "
                                               "avg(valence) AS valence, avg(arousal) AS arousal FROM utterances "
                                               "WHERE substr(t0,1,10)=? AND media IS NULL GROUP BY name ORDER BY minutes DESC", (day,))]
            daily = c.execute("SELECT * FROM daily WHERE day=?", (day,)).fetchone()
            media = [dict(r) for r in c.execute("SELECT media, round(sum(seconds)/60.0,1) AS minutes FROM utterances "
                                                "WHERE substr(t0,1,10)=? AND media IS NOT NULL GROUP BY media", (day,))]
            return {"day": day, "conversations": convs, "sounds": sounds, "talk": talk, "media": media,
                    "daily": dict(daily) if daily else None}
        if path == "/home/api/conversation":
            cid = int(qs.get("id", ["0"])[0])
            conv = c.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
            U = _clean(c.execute("SELECT * FROM utterances WHERE conv_id=? ORDER BY t0", (cid,)).fetchall())
            base = baselines(c, {u["speaker"] for u in U if u["speaker"]}, conv["start"] if conv else None)
            for u in U:
                b = base.get(u["speaker"])
                if b:
                    u["rel"] = {k: (round(u[k] - b[k], 2) if u.get(k) is not None and b.get(k) is not None else None)
                                for k in ("f0_hz", "intensity_db", "syll_per_s", "arousal", "valence")}
            S = [dict(r) for r in c.execute("SELECT * FROM sounds WHERE conv_id=? ORDER BY t0", (cid,))]
            return {"conversation": dict(conv) if conv else None, "utterances": U, "sounds": S}
    return None


def baselines(c, speakers, until):
    """Each person's usual voice: medians over the 30 days before `until` (>= 20 utterances)."""
    import statistics
    out = {}
    if not until:
        return out
    since = iso(datetime.fromisoformat(until) - timedelta(days=30))
    for s in speakers:
        rows = c.execute("SELECT f0_hz, intensity_db, syll_per_s, arousal, valence FROM utterances "
                         "WHERE speaker=? AND t0>=? AND t0<=?", (s, since, until)).fetchall()
        if len(rows) < 20:
            continue
        out[s] = {k: statistics.median([r[k] for r in rows if r[k] is not None] or [0])
                  for k in ("f0_hz", "intensity_db", "syll_per_s", "arousal", "valence")}
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        if getattr(self, "_cookie", None):
            self.send_header("Set-Cookie", self._cookie)
        if getattr(self, "_dl_name", None):
            self.send_header("Content-Disposition", f'attachment; filename="{self._dl_name}"')
        self.end_headers()
        self.wfile.write(body)

    def _local(self):
        return self.client_address[0] in ("127.0.0.1", "::1")

    def _authed(self):
        """this PC's screen, or a device that knows the access code (paired phone: header X-Home-Token; a browser on another
        device: the cookie set by opening /home?token=CODE once). config.json "api_auth": false turns the check off."""
        if self._local() or config().get("api_auth", True) is False:
            return True
        tok = config()["token"]
        if secrets.compare_digest(self.headers.get("X-Home-Token", ""), tok):
            return True
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "home_token" and secrets.compare_digest(urllib.parse.unquote(v), tok):
                return True
        return False

    def _body(self):
        n = int(self.headers.get("content-length", 0) or 0)
        return json.loads(self.rfile.read(n) or b"{}") if 0 < n < 100000 else {}

    def do_POST(self):
        u = urllib.parse.urlsplit(self.path)
        qs = urllib.parse.parse_qs(u.query)
        if u.path in ("/home/api/label", "/home/api/summarize_day", "/home/api/summarize_conv", "/home/api/label_sound",
                      "/home/api/delete_audio", "/home/api/task", "/home/api/optout", "/home/api/place", "/home/api/import_dirs",
                      "/home/api/privacy_set", "/home/api/gold", "/home/api/asr_check", "/home/api/teach_skip"):
            phone_ok = u.path in ("/home/api/label", "/home/api/task", "/home/api/teach_skip")       # teaching + task checking also from the paired phone
            if not (self._authed() if phone_ok else self._local()):
                return self._send(403, {"error": "only from this PC" if not phone_ok else "bad token"})
            b = self._body()
            try:
                if u.path == "/home/api/task":
                    with db() as c:
                        c.execute("UPDATE tasks SET state=? WHERE id=?", (b.get("state") if b.get("state") in ("open", "done", "dismissed") else "open",
                                                                          int(b.get("id", 0))))
                    return self._send(200, {"ok": True})
                if u.path == "/home/api/teach_skip":        # "several people talk / unclear": never ask about it again
                    with db() as c:
                        c.execute("INSERT OR REPLACE INTO teach_skips (utt_id, reason, at) VALUES (?,?,?)",
                                  (int(b.get("utt_id", 0)), str(b.get("reason") or "unclear")[:20], iso(datetime.now())))
                    return self._send(200, {"ok": True})
                if u.path == "/home/api/gold":
                    with db() as c:
                        return self._send(200, add_gold(c, int(b.get("utt_id", 0)), b.get("text")))
                if u.path == "/home/api/asr_check":
                    import asr_update
                    cfg = asr_update.cfg_read()
                    st = asr_update.state(cfg)
                    st["enabled"] = bool(b.get("enabled", True))
                    if st["enabled"]:
                        st["misses"] = 0
                        st["note"] = None
                    asr_update.cfg_write(cfg)
                    return self._send(200, dict(asr_update.status(), ok=True))
                if u.path == "/home/api/optout":
                    return self._send(200, set_optout(str(b.get("id", "")), bool(b.get("on", True))))
                if u.path == "/home/api/place":
                    with db() as c:
                        if b.get("delete"):
                            c.execute("DELETE FROM places WHERE id=?", (int(b["delete"]),))
                        else:
                            c.execute("INSERT INTO places (name, lat, lon, r_m, mute, created) VALUES (?,?,?,?,?,?)",
                                      (str(b.get("name", ""))[:40], float(b["lat"]), float(b["lon"]), float(b.get("r_m", 150)),
                                       1 if b.get("mute") else 0, iso(datetime.now())))
                    return self._send(200, {"ok": True})
                if u.path == "/home/api/import_dirs":
                    cfg = config()
                    cfg["import_dirs"] = [str(x) for x in (b.get("dirs") or [])][:10]
                    json.dump(cfg, open(CONFIG, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
                    return self._send(200, {"ok": True})
                if u.path == "/home/api/privacy_set":
                    cfg = config()
                    for k, lo, hi in (("owner_min_seconds", 0, 30), ("bystander_db", 3, 40)):
                        if k in b:
                            cfg[k] = max(lo, min(hi, float(b[k])))
                    json.dump(cfg, open(CONFIG, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
                    return self._send(200, {"ok": True})
                if u.path == "/home/api/label":
                    return self._send(200, label(int(b.get("utt_id", 0)), b.get("speaker"), b.get("new_name")))
                if u.path == "/home/api/delete_audio":
                    if b.get("confirm") != "yes" or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(b.get("before", ""))):
                        return self._send(400, {"ok": False, "msg": "missing date / confirmation"})
                    return self._send(200, delete_audio_before(b["before"]))
                if u.path == "/home/api/label_sound":
                    return self._send(200, label_sound(int(b.get("sound_id", 0)), b.get("tag")))
                if u.path == "/home/api/summarize_conv":
                    finish_conversation(int(b.get("id", 0)), final=b.get("final", True))
                    return self._send(200, {"ok": True})
                return self._send(200, summarize_day(str(b.get("day", datetime.now().strftime("%Y-%m-%d")))))
            except Exception as exc:  # noqa: BLE001
                return self._send(500, {"ok": False, "msg": repr(exc)})
        if u.path not in ("/home/api/chunk", "/home/api/mark"):
            return self._send(404, {"error": "not found"})
        if not secrets.compare_digest(self.headers.get("X-Home-Token", ""), config()["token"]):
            return self._send(403, {"error": "bad token"})
        q1 = lambda k, d=None: qs.get(k, [d])[0]  # noqa: E731
        if u.path == "/home/api/mark":                         # "mark this moment" from the phone (button / quick tile)
            ms = int(q1("ms") or 0)
            skew = int(q1("skew") or 0)
            t = datetime.fromtimestamp((ms + (skew if abs(skew) > 2000 else 0)) / 1000) if ms else datetime.now()
            mins = add_mark(q1("device", "phone"), t, (q1("note") or "")[:80] or None, int(q1("min") or 0) or None)
            return self._send(200, {"ok": True, "minutes": mins})
        n = int(self.headers.get("content-length", 0) or 0)
        if not 0 < n <= MAX_BODY:
            return self._send(413, {"error": "size"})
        raw = self.rfile.read(n)
        ctype = self.headers.get("Content-Type", "")
        ext = re.sub(r"[^a-z0-9]", "", (q1("ext") or "").lower())[:5] or (
            "wav" if "wav" in ctype else "m4a" if ("mp4" in ctype or "m4a" in ctype or "aac" in ctype) else "ogg")
        kind = q1("kind", "speech")
        kind = kind if kind in KINDS else "speech"

        def num(k, cast=float):
            try:
                return cast(q1(k)) if q1(k) not in (None, "") else None
            except ValueError:
                return None
        meta = {"ms": num("ms", int), "skew": num("skew", int), "lat": num("lat"), "lon": num("lon"), "bat": num("bat", int),
                "home": q1("home", "1"), "role": q1("role", "home") if q1("role") in ("home", "wearer") else "home",
                "cal": q1("cal")}
        cid = store_chunk(raw, q1("device", "phone"), q1("start", iso(datetime.now())), ext, kind, meta)
        phone_seen(q1("device", "phone"), self.client_address[0], last_chunk=iso(datetime.now()))
        return self._send(200, {"ok": True, "id": cid})

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        if u.path in ("/home", "/home/"):
            self._cookie = None
            tok = (urllib.parse.parse_qs(u.query).get("token") or [""])[0]
            if tok and secrets.compare_digest(tok, config()["token"]):      # open /home?token=CODE once on a new device
                self._cookie = f"home_token={urllib.parse.quote(tok)}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Lax"
            return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        if u.path in ("/home/icon.svg", "/favicon.ico"):
            return self._send(200, (PROJ / "ui" / "home_icon.svg").read_bytes(), "image/svg+xml")
        if u.path == "/home/qrcode.js":
            return self._send(200, (PROJ / "ui" / "qrcode.js").read_bytes(), "text/javascript; charset=utf-8")
        if u.path == "/home/app.apk":                      # install on the phone over the home Wi-Fi
            apk = apk_path()
            if not apk:
                return self._send(404, {"error": "app.apk not found: run install\\Install.bat again"})
            self._dl_name = "shema.apk"
            return self._send(200, apk.read_bytes(), "application/vnd.android.package-archive")
        if u.path == "/home/api/pair":                     # the QR: only on this PC (it holds the access code)
            if not self._local():
                return self._send(403, {"error": "only from this PC"})
            return self._send(200, pair_info())
        m = re.fullmatch(r"/home/audio/utt/(\d+)", u.path)
        if m and self._authed():                           # one utterance's audio (to check by ear before labelling)
            return self._utt_audio(int(m.group(1)))
        m = re.fullmatch(r"/home/audio/sound/(\d+)", u.path)
        if m and self._authed():                           # one sound event's audio
            return self._utt_audio(int(m.group(1)), table="sounds")
        qs = urllib.parse.parse_qs(u.query)
        authed = self._authed()
        if u.path.startswith("/home/api/") and u.path != "/home/api/status" and not authed:
            return self._send(403, {"error": "access code needed: open /home?token=CODE once on this device"})
        if u.path == "/home/api/status" and "device" in qs:          # the phone's heartbeat
            phone_seen(qs["device"][0], self.client_address[0], state=qs.get("state", [None])[0],
                       sent=qs.get("sent", [None])[0], queued=qs.get("queued", [None])[0],
                       role=qs.get("role", [None])[0], bat=qs.get("bat", [None])[0], silenced=qs.get("sil", [None])[0],
                       place=qs.get("place", [None])[0], qmb=qs.get("qmb", [None])[0], oldest=qs.get("oldest", [None])[0],
                       vpn=qs.get("vpn", [None])[0], charging=qs.get("chg", [None])[0],
                       speech_s=qs.get("speech", [None])[0],
                       via="tailscale" if self.client_address[0].startswith("100.") else "lan")
            if qs.get("tl", [""])[0]:
                try:
                    store_timeline(qs["device"][0], qs["tl"][0], int(qs.get("skew", ["0"])[0] or 0))
                except Exception as exc:  # noqa: BLE001
                    log(f"timeline store failed {exc!r}")
        try:
            out = api(u.path, qs)
            if u.path == "/home/api/status" and not authed and isinstance(out, dict):
                out = dict(out, digest=None, owner_enrolled=None, phones=[])        # no codes -> only the clock and counts
        except Exception as exc:  # noqa: BLE001
            return self._send(500, {"error": repr(exc)})
        return self._send(200, out) if out is not None else self._send(404, {"error": "not found"})

    def _utt_audio(self, uid, table="utterances"):
        with db() as c:
            r = c.execute(f"SELECT u.t0, u.t1, k.start, k.file FROM {table} u JOIN chunks k ON k.id=u.chunk_id "
                          "WHERE u.id=?", (uid,)).fetchone()
        if not r or not r["file"] or not os.path.exists(r["file"]):
            return self._send(404, {"error": "audio gone"})
        import voice_embed as VE
        off = (datetime.fromisoformat(r["t0"]) - datetime.fromisoformat(r["start"])).total_seconds()
        dur = (datetime.fromisoformat(r["t1"]) - datetime.fromisoformat(r["t0"])).total_seconds()
        wav = subprocess.run([VE.FF, "-v", "error", "-ss", f"{max(0, off - 0.2):.2f}", "-t", f"{dur + 0.4:.2f}",
                              "-i", r["file"], "-ac", "1", "-ar", "16000", "-f", "wav", "-"], capture_output=True).stdout
        return self._send(200, _fix_wav(wav), "audio/wav")


def _fix_wav(b):
    """ffmpeg writing to a pipe leaves the RIFF / data sizes at 0xFFFFFFFF: browsers cope, Android's MediaPlayer
    refuses the file ("error 1, -2147483648"). Write the real sizes."""
    import struct
    i = b.find(b"data")
    if len(b) < 44 or i < 0:
        return b
    b = bytearray(b)
    struct.pack_into("<I", b, 4, len(b) - 8)
    struct.pack_into("<I", b, i + 4, len(b) - (i + 8))
    return bytes(b)


WORKER = None


def main():
    global WORKER
    ap = argparse.ArgumentParser()
    ap.add_argument("--ingest", help="queue a local audio file (testing without the phone)")
    ap.add_argument("--start", help="ISO start time of --ingest")
    ap.add_argument("--once", action="store_true", help="process the queue, close conversations, exit")
    ap.add_argument("--archive-now", action="store_true", help="one-time conversion of the existing m4a/other audio to Opus 12k: "
                    "prints a dry-run report (space freed) and does nothing else, unless --apply is added")
    ap.add_argument("--apply", action="store_true", help="with --archive-now: really convert")
    ap.add_argument("--resplit", type=int, help="cut one merged conversation into real ones at gaps in its own utterance times")
    args = ap.parse_args()
    config()
    migrate()
    requeue_failed(force=True)
    if args.resplit:
        print("new conversations:", resplit_conversation(args.resplit))
        return
    if args.archive_now:
        rep = archive_dry_run()
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        if args.apply:
            if not rep["opus_in_ffmpeg"]:
                print("ffmpeg has no libopus: nothing done")
                return
            while True:
                r = archive_pass(limit=200)
                print(r, flush=True)
                if not r["converted"]:
                    break
        else:
            print("dry run only. Add --apply to convert (the original is deleted after each new file is checked).")
        return
    try:
        reindex_all()
    except Exception as exc:  # noqa: BLE001
        log(f"reindex failed {exc!r}")
    if args.ingest:
        p = Path(args.ingest)
        cid = store_chunk(p.read_bytes(), "pc-test", args.start or iso(datetime.now()), p.suffix.lstrip(".") or "wav")
        print("queued chunk", cid)
        if not args.once:
            return
    if args.once:
        w = Worker()
        while w.step():
            pass
        with db() as c:
            for r in c.execute("SELECT id FROM conversations WHERE status IN ('open','ended')").fetchall():
                if gate_conversation(r["id"]):
                    finish_conversation(r["id"])
        return
    WORKER = Worker()
    WORKER.start()
    log(f"Shema server on :{PORT}  (data in {HOME})")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
