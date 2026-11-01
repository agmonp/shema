r"""me_period.py -- the phone's "אני" screen for one period (day / week), and short names for meetings.  (2026-11-01)

report(): what the PC already knows about a day or a week, in one answer the phone can keep offline:
  stats      recording minutes, conversations, meetings, the owner's own speaking minutes, marked moments, items
  prev       the same numbers for the period before (the "compared with last week" line)
  days       per day of a week: minutes, conversations, mood (voice valence / arousal, weighted by length)
  topics     the day summaries' topics (each tied to a conversation), else the longest conversations' topics
  people     who the owner talked with most (speaking minutes) and whose names came up most (mentions)
  items      decisions, open tasks / requests / promises, done ones, and open questions from meetings
  moments    the day summaries' highlights and the user's own marks, each with a conversation to open
  meetings   the period's meetings with their title and one-line description
Only tables both servers have are read (conversations, utterances, tasks, daily, marks, meetings); optional columns are
checked first. schema = SCHEMA: the phone keeps older answers and draws only the parts an answer has.

Weeks are the Israeli week, Sunday to Saturday (the same as me_speech.py on the owner's server).

Meeting names: a meeting without a title (NULL, '' or the placeholder "פגישה" that a calendar marker of an untitled
meeting turned into) gets a 3-7 word Hebrew title from its summary once the summary is ready, marked title_auto = 1.
Every summarised meeting gets one line about what it was about (meetings.oneline). A title the user typed is never
changed. fill() also covers older meetings (the backfill): it only touches rows that still need something.
"""
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta

SCHEMA = 2
PLACEHOLDER_TITLES = {"", "פגישה", "פגישה חדשה", "null", "none"}
TITLE_MIN, TITLE_MAX = 3, 7
# first names that are everyday Hebrew words: a "mention" of them is only the full name
COMMON_WORD_NAMES = {"אדם", "שחר", "אור", "טל", "גל", "חן", "דן", "רון", "שי", "ים", "בר", "עוז", "נוי", "שלום", "חיים",
                     "אביב", "גיל", "רז", "שמש", "ליאור", "מאור", "אמיר", "דור", "הדר", "יובל", "עדי", "פז", "שקד"}
ONELINE_MAX = 110


# ---------------------------------------------------------------- periods
def period_of(kind, d):
    day = datetime.strptime(d[:10], "%Y-%m-%d")
    if kind == "week":                                    # the Israeli week: Sunday to Saturday
        s = day - timedelta(days=(day.weekday() + 1) % 7)
        return s, s + timedelta(days=7)
    return day, day + timedelta(days=1)


def label(kind, s, e):
    if kind == "week":
        return f"{s.strftime('%d/%m')}–{(e - timedelta(days=1)).strftime('%d/%m')}"
    return s.strftime("%d/%m")


def _ymd(t):
    return t.strftime("%Y-%m-%d")


def _cols(c, table):
    return {r[1] for r in c.execute(f"PRAGMA table_info({table})")}


def _has_table(c, name):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone())


# ---------------------------------------------------------------- the numbers of one period
def stats(c, owner, s, e):
    a, b = _ymd(s), _ymd(e)
    k = c.execute("SELECT count(*), coalesce(sum(seconds), 0) FROM conversations WHERE status='done' AND start>=? AND start<?",
                  (a, b)).fetchone()
    mine = c.execute("SELECT coalesce(sum(seconds), 0), count(*) FROM utterances WHERE speaker=? AND media IS NULL "
                     "AND t0>=? AND t0<?", (owner, a, b)).fetchone()
    meets = c.execute("SELECT count(*) FROM meetings WHERE started>=? AND started<? AND coalesce(status,'')!='empty'",
                      (a, b)).fetchone()[0]
    marks = c.execute("SELECT count(*) FROM marks WHERE t>=? AND t<?", (a, b)).fetchone()[0]
    tk = "kind" in _cols(c, "tasks")
    items = c.execute("SELECT " + ("coalesce(t.kind,'')='decision'" if tk else "0") + " AS dec, count(*) FROM tasks t "
                      "JOIN conversations k ON k.id=t.conv_id WHERE k.start>=? AND k.start<? AND t.state!='dismissed' "
                      "GROUP BY dec", (a, b)).fetchall()
    by = {r[0]: r[1] for r in items}
    return {"conversations": k[0], "rec_minutes": round(k[1] / 60, 1), "my_minutes": round(mine[0] / 60, 1),
            "my_lines": mine[1], "meetings": meets, "marks": marks, "tasks": by.get(0, 0), "decisions": by.get(1, 0)}


def _days(c, s, e):
    out = []
    d = s
    while d < e:
        a, b = _ymd(d), _ymd(d + timedelta(days=1))
        rows = c.execute("SELECT seconds, mood_valence, mood_arousal FROM conversations WHERE status='done' AND start>=? "
                         "AND start<?", (a, b)).fetchall()
        w = sum(r[0] or 0 for r in rows if r[1] is not None)
        mood = c.execute("SELECT mood FROM daily WHERE day=?", (a,)).fetchone()
        out.append({"day": a, "label": d.strftime("%d/%m"), "conversations": len(rows),
                    "minutes": round(sum(r[0] or 0 for r in rows) / 60, 1),
                    "valence": round(sum((r[0] or 0) * r[1] for r in rows if r[1] is not None) / w, 2) if w else None,
                    "arousal": round(sum((r[0] or 0) * r[2] for r in rows if r[2] is not None) / w, 2) if w else None,
                    "mood": (mood[0] if mood and isinstance(mood[0], str) else None)})
        d += timedelta(days=1)
    return out


def _detail(c, s, e):
    """the day summaries' topics and highlights (daily.detail where it exists, else the plain highlights list)"""
    has_detail = "detail" in _cols(c, "daily")
    topics, highlights = [], []
    for r in c.execute("SELECT day, highlights" + (", detail" if has_detail else "") + " FROM daily WHERE day>=? AND day<? "
                       "ORDER BY day", (_ymd(s), _ymd(e))):
        det = {}
        if has_detail and r[2]:
            try:
                det = json.loads(r[2]) or {}
            except ValueError:
                det = {}
        for t in det.get("topics") or []:
            if isinstance(t, dict) and t.get("text"):
                topics.append({"text": t["text"], "conv": t.get("conv_id") or t.get("conv"), "day": r[0]})
        hl = det.get("highlights")
        if not hl and r[1]:
            try:
                hl = json.loads(r[1])
            except ValueError:
                hl = []
        for h in hl or []:
            if isinstance(h, dict) and h.get("text"):
                highlights.append({"text": h["text"], "conv": h.get("conv_id") or h.get("conv"), "day": r[0]})
            elif isinstance(h, str) and h.strip():
                highlights.append({"text": h.strip(), "conv": None, "day": r[0]})
    return topics, highlights


def _people(c, owner, s, e, n=8):
    a, b = _ymd(s), _ymd(e)
    talk = defaultdict(lambda: {"minutes": 0.0, "convs": set()})
    for r in c.execute("SELECT name, conv_id, seconds FROM utterances WHERE t0>=? AND t0<? AND media IS NULL "
                       "AND coalesce(name,'')!='' AND coalesce(speaker,'')!=?", (a, b, owner)):
        p = talk[r[0]]
        p["minutes"] += (r[2] or 0) / 60
        p["convs"].add(r[1])
    # mentions: a known person's first name said as a word in anyone's sentences
    names = [r[0] for r in c.execute("SELECT name FROM home_people WHERE coalesce(name,'')!='' AND id!=?", (owner,))]
    first = {}
    for nm in names:
        w = nm.split()[0]
        if len(w) >= 3 and w not in COMMON_WORD_NAMES:      # "אדם", "שחר", "אור" are words first: they count only in full
            first.setdefault(w, nm)
        elif len(nm.split()) > 1:
            first.setdefault(nm, nm)
    mentions = Counter()
    if first:
        pat = re.compile(r"(?<![\w])[ולבהמש]?(" + "|".join(sorted(map(re.escape, first), key=len, reverse=True)) + r")(?![\w])")
        for (t,) in c.execute("SELECT text FROM utterances WHERE t0>=? AND t0<? AND media IS NULL AND coalesce(text,'')!=''",
                              (a, b)):
            for m in pat.finditer(t):
                mentions[first[m.group(1)]] += 1
    keys = set(talk) | set(mentions)
    rows = [{"name": k, "minutes": round(talk[k]["minutes"], 1) if k in talk else 0.0,
             "convs": len(talk[k]["convs"]) if k in talk else 0, "mentions": mentions.get(k, 0)} for k in keys]
    by_talk = sorted([r for r in rows if r["minutes"] > 0], key=lambda r: -r["minutes"])[:n]
    by_mention = sorted([r for r in rows if r["mentions"] > 0], key=lambda r: -r["mentions"])[:n]
    return by_talk, by_mention


def _items(c, s, e):
    a, b = _ymd(s), _ymd(e)
    tc = _cols(c, "tasks")
    sel = "t.id, t.conv_id, t.who, t.what, t.due, t.state, " + ("t.kind" if "kind" in tc else "NULL") + ", " + \
          ("t.utt_id" if "utt_id" in tc else "NULL") + ", " + ("t.owner" if "owner" in tc else "NULL")
    out = {"decisions": [], "open": [], "done": [], "questions": []}
    for r in c.execute(f"SELECT {sel} FROM tasks t JOIN conversations k ON k.id=t.conv_id WHERE k.start>=? AND k.start<? "
                       "AND t.state!='dismissed' ORDER BY k.start, t.id", (a, b)):
        who = r[8] or (r[2] if r[2] and r[2] != "?" else None)
        x = {"id": r[0], "conv": r[1], "utt": r[7], "text": r[3], "who": who, "due": r[4], "state": r[5], "kind": r[6]}
        if r[6] == "decision":
            out["decisions"].append(x)
        elif r[5] == "done":
            out["done"].append(x)
        else:
            out["open"].append(x)
    for r in c.execute("SELECT id, title, conv_id, result FROM meetings WHERE started>=? AND started<? AND result IS NOT NULL",
                       (a, b)):
        try:
            res = json.loads(r[3]) or {}
        except ValueError:
            continue
        for q in res.get("open_questions") or []:
            if isinstance(q, str) and q.strip():
                out["questions"].append({"text": q.strip(), "conv": r[2], "meeting": r[0]})
    for k in out:
        out[k] = out[k][:30]
    return out


def _meetings(c, s, e):
    mc = _cols(c, "meetings")
    rows = c.execute("SELECT m.id, m.title, m.started, m.ended, m.conv_id, m.status, k.topic, k.seconds" +
                     (", m.oneline" if "oneline" in mc else ", NULL") + " FROM meetings m LEFT JOIN conversations k "
                     "ON k.id=m.conv_id WHERE m.started>=? AND m.started<? ORDER BY m.started", (_ymd(s), _ymd(e))).fetchall()
    return [{"id": r[0], "title": shown_title(r[1], r[6]), "started": r[2], "ended": r[3], "conv": r[4], "status": r[5],
             "seconds": r[7], "oneline": r[8]} for r in rows]


def report(c, owner, kind="week", d=None):
    """One period for the phone's "אני" screen (c = an open sqlite connection)."""
    d = (d or datetime.now().strftime("%Y-%m-%d"))[:10]
    kind = kind if kind in ("day", "week") else "week"
    s, e = period_of(kind, d)
    ps, pe = period_of(kind, _ymd(s - timedelta(days=1)))
    topics, highlights = _detail(c, s, e)
    if not topics:                                         # no day summary yet: the longest conversations' own topics
        topics = [{"text": r[0], "conv": r[1], "day": r[2][:10]} for r in c.execute(
            "SELECT topic, id, start FROM conversations WHERE status='done' AND start>=? AND start<? "
            "AND coalesce(topic,'')!='' ORDER BY seconds DESC LIMIT 8", (_ymd(s), _ymd(e)))]
    seen, uniq = set(), []
    for t in topics:
        if t["text"] not in seen:
            seen.add(t["text"])
            uniq.append(t)
    talk, mentioned = _people(c, owner, s, e)
    moments = [dict(h, kind="highlight") for h in highlights][:10]
    for r in c.execute("SELECT t, note FROM marks WHERE t>=? AND t<? ORDER BY t", (_ymd(s), _ymd(e))):
        conv = c.execute("SELECT id FROM conversations WHERE start<=? AND coalesce(end, start)>=? ORDER BY start DESC LIMIT 1",
                         (r[0], r[0])).fetchone()
        moments.append({"text": r[1] or "רגע שסימנת", "conv": conv[0] if conv else None, "day": r[0][:10], "t": r[0],
                        "kind": "mark"})
    return {"schema": SCHEMA, "kind": kind, "d": d, "start": _ymd(s), "end": _ymd(e - timedelta(days=1)),
            "label": label(kind, s, e), "stats": stats(c, owner, s, e),
            "prev": dict(stats(c, owner, ps, pe), label=label(kind, ps, pe), start=_ymd(ps)),
            "days": _days(c, s, e) if kind == "week" else [], "topics": uniq[:8], "people": talk,
            "mentioned": mentioned, "items": _items(c, s, e), "moments": moments[:14], "meetings": _meetings(c, s, e),
            "generated": datetime.now().isoformat(timespec="seconds")}


# ---------------------------------------------------------------- meeting names
NAME_TASK = """לפניך נושא וסיכום של פגישה שהוקלטה. כתוב בעברית:
1. כותרת קצרה לפגישה: 3 עד 7 מילים, בלי מרכאות, בלי תאריך, בלי המילה "פגישה" בהתחלה.
2. שורה אחת שאומרת על מה הפגישה: משפט אחד, עד 15 מילים, רק לפי הסיכום.
אל תמציא שמות או פרטים שלא בסיכום. החזר JSON בלבד: {"title": "...", "line": "..."}"""


def is_placeholder(title):
    return title is None or str(title).strip().strip("📋").strip().lower() in PLACEHOLDER_TITLES


def shown_title(title, topic):
    return title if not is_placeholder(title) else (topic or None)


def _words(s):
    return [w for w in re.split(r"\s+", str(s or "").strip()) if w]


def _clean(s):
    s = re.sub(r"\s+", " ", str(s or "")).strip().strip("\"'״׳“”.,:;-– ").strip()
    return re.sub(r"^פגישה\s*(?:על|בנושא|:|-|–)?\s*", "", s).strip() or s


def fit_title(t, topic=None, summary=None):
    """3-7 words: the model's title, else the conversation topic, else the summary's first words; None if nothing."""
    for cand in (t, topic):
        w = _words(_clean(cand))
        if TITLE_MIN <= len(w) <= TITLE_MAX:
            return " ".join(w)
        if len(w) > TITLE_MAX:
            return " ".join(w[:TITLE_MAX])
    first = re.split(r"(?<=[.!?])\s", str(summary or "").strip())[0]
    w = _words(_clean(first))[:TITLE_MAX]
    if len(w) >= TITLE_MIN:
        return " ".join(w)
    w = _words(_clean(topic or t))                         # a 1-2 word topic is still better than no title
    return " ".join(w) or None


def fit_line(line, summary=None):
    """one line about the meeting: the model's line, else the summary's first sentence, cut at a word"""
    s = _clean(line) if line else ""
    if len(_words(s)) < 3:
        s = re.split(r"(?<=[.!?])\s", str(summary or "").strip())[0].strip()
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return None
    if len(s) > ONELINE_MAX:
        s = s[:ONELINE_MAX].rsplit(" ", 1)[0].rstrip(",;:-– ") + "…"
    return s


def name_meeting(topic, summary, llm=None):
    """-> (title, line). llm(system, user) -> dict (the server's _ollama_json); without it, or when it fails, the
    summary's own words are used."""
    out = {}
    if llm is not None and (summary or topic):
        try:
            out = llm(NAME_TASK, f"נושא: {topic or '-'}\nסיכום: {summary or '-'}") or {}
        except Exception:  # noqa: BLE001 -- a name is never worth failing a meeting for
            out = {}
        if not isinstance(out, dict) or "error" in out:
            out = {}
    return fit_title(out.get("title"), topic, summary), fit_line(out.get("line"), summary)


def ensure(c):
    have = _cols(c, "meetings")
    for col, typ in (("oneline", "TEXT"), ("title_auto", "INTEGER")):
        if col not in have:
            c.execute(f"ALTER TABLE meetings ADD COLUMN {col} {typ}")


def pending(c, limit=3):
    """summarised meetings still missing their line, or an auto title"""
    ensure(c)
    return c.execute("SELECT m.id, m.title, m.title_auto, k.topic, k.summary FROM meetings m JOIN conversations k "
                     "ON k.id=m.conv_id WHERE m.status='done' AND coalesce(k.summary,'')!='' AND (m.oneline IS NULL OR "
                     "((m.title IS NULL OR trim(m.title) IN ('', 'פגישה', 'פגישה חדשה')) AND coalesce(m.title_auto,0)=0)) "
                     "ORDER BY m.started DESC LIMIT ?", (limit,)).fetchall()


def apply(c, mid, title, line):
    """the user's title is kept: only an empty / placeholder one is replaced (and marked title_auto = 1)"""
    ensure(c)
    row = c.execute("SELECT title FROM meetings WHERE id=?", (mid,)).fetchone()
    if row is None:
        return False
    if title and is_placeholder(row[0]):
        c.execute("UPDATE meetings SET title=?, title_auto=1 WHERE id=?", (title, mid))
    c.execute("UPDATE meetings SET oneline=coalesce(?, oneline, '') WHERE id=?", (line, mid))
    return True


def fill(db, llm=None, limit=3, log=print):
    """name the meetings that need it (after a summary, and the older ones once). Cheap when nothing waits."""
    with db() as c:
        rows = [tuple(r) for r in pending(c, limit)]
    n = 0
    for mid, title, _auto, topic, summary in rows:
        t, line = name_meeting(topic, summary, llm)
        with db() as c:
            if apply(c, mid, t, line):
                n += 1
        log(f"meeting {mid}: named " + json.dumps({"title": t if is_placeholder(title) else None, "line": line},
                                                  ensure_ascii=False))
    return n
