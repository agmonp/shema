# -*- coding: utf-8 -*-
"""memory_index.py -- search conversations by meaning, not only by exact words (2026-10-17, Shema 2.0 phase 5).

Each finished conversation is cut into windows of consecutive lines (about 30 words, one line shared with the
next window); each window gets a vector from the local `embeddinggemma` model in Ollama (768 numbers, nothing leaves
the PC). The vectors live in the same SQLite file (table seg_vecs) and are compared in memory: a whole history is a
few thousand windows, so no vector database is needed. Search fuses this ranking with the full-text index
(reciprocal rank fusion), so exact names and numbers still count while "רכישת מחשב" also finds "קניתי מחשב שולחני".

No model installed / Ollama down -> every function here returns nothing and search stays full-text only.
"""
import json
import os
import threading
import time

import numpy as np

MODEL = os.getenv("SHEMA_EMBED_MODEL", "embeddinggemma")
# Measured 2026-10-17 on the owner's history (769 conversations, 70 questions written by gemma4:12b from transcript
# windows in other words; target = that conversation in the top 6):
#   full-text only 40% (finds nothing 50%) | meaning only, 60-word windows 34% | hybrid 60 words 50% | hybrid 30 words 56%
#   (top 1: 26% -> 31%, top 3: 37% -> 49%). Weighting meaning x1.5/x2 or a similarity cut-off were worse.
# Off-topic questions score 0.29-0.45, real ones median 0.47: no threshold separates "not discussed" from "discussed",
# so the answer step decides that from the evidence, not this module. MIN_SIM only drops obvious noise: a short
# keyword query ("טיפול שיניים") tops out around 0.26 where a full question reaches 0.47, so a higher floor would
# silently drop every meaning hit for keyword searches. Hits found only by meaning are labelled as such in the UI.
WIN_WORDS = 30
BATCH = 64
MIN_SIM = 0.15
RRF_K = 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS seg_vecs (id INTEGER PRIMARY KEY, conv_id INTEGER, u0 INTEGER, u1 INTEGER, t0 TEXT,
    text TEXT, vec BLOB, model TEXT);
CREATE INDEX IF NOT EXISTS sv_conv ON seg_vecs(conv_id);
"""

_client = None
_down_until = 0.0


def _ollama():
    global _client
    if _client is None:
        import ollama
        _client = ollama.Client(host=os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"), timeout=120)
    return _client


def embed(texts, query=False):
    """Unit vectors (float32, n x d) for texts, or None when the model can't be reached (then retried after 5 min)."""
    global _down_until
    if not texts or time.time() < _down_until:
        return None
    pre = "task: search result | query: " if query else "title: none | text: "
    out = []
    try:
        for i in range(0, len(texts), BATCH):
            r = _ollama().embed(model=MODEL, input=[pre + t for t in texts[i:i + BATCH]], keep_alive="5m")
            out += r["embeddings"]
    except Exception:  # noqa: BLE001
        _down_until = time.time() + 300
        return None
    E = np.asarray(out, dtype=np.float32)
    return E / np.maximum(np.linalg.norm(E, axis=1, keepdims=True), 1e-9)


def windows(U):
    """Lines (dicts/rows with id, t0, name, text) -> lists of lines of ~WIN_WORDS words; the last line of a window
    opens the next one, so an answer split across the cut is still whole in one of them."""
    out, cur, n = [], [], 0
    for u in U:
        cur.append(u)
        n += len((u["text"] or "").split())
        if n >= WIN_WORDS:
            out.append(cur)
            cur = [u]
            n = len((u["text"] or "").split())
    if cur and not (out and len(cur) == 1 and cur[0] is out[-1][-1]):
        out.append(cur)
    return out


def win_text(w):
    return "\n".join(f"{u['name'] or '?'}: {u['text']}" for u in w)


def index_conv(c, cid):
    """(Re)build the windows of one conversation. Returns the number of windows, or None if the model is down."""
    U = c.execute("SELECT id, t0, name, text FROM utterances WHERE conv_id=? AND media IS NULL AND text!='' ORDER BY t0",
                  (cid,)).fetchall()
    W = windows(U)
    k = c.execute("SELECT start, topic, summary FROM conversations WHERE id=?", (cid,)).fetchone()
    # the conversation's own summary as one more vector (u0 NULL): clean text, so meaning matches it far better than
    # the noisy transcript; the transcript windows still give the lines to listen to
    head = " ".join(x for x in ((k["topic"] + ".") if k and k["topic"] else None, k["summary"] if k else None) if x)
    texts = [win_text(w) for w in W] + ([head] if head else [])
    E = embed(texts) if texts else np.zeros((0, 1), np.float32)
    if E is None:
        return None
    c.execute("DELETE FROM seg_vecs WHERE conv_id=?", (cid,))
    rows = [(cid, w[0]["id"], w[-1]["id"], w[0]["t0"], texts[i], E[i].tobytes(), MODEL) for i, w in enumerate(W)]
    if head:
        rows.append((cid, None, None, k["start"], head, E[-1].tobytes(), MODEL))
    c.executemany("INSERT INTO seg_vecs (conv_id, u0, u1, t0, text, vec, model) VALUES (?,?,?,?,?,?,?)", rows)
    _CACHE.dirty = True
    return len(rows)


def missing(c, limit=40):
    """Finished conversations that have lines but no windows yet (newest first)."""
    return [r[0] for r in c.execute(
        "SELECT k.id FROM conversations k WHERE k.status='done' AND NOT EXISTS (SELECT 1 FROM seg_vecs s WHERE s.conv_id=k.id) "
        "AND EXISTS (SELECT 1 FROM utterances u WHERE u.conv_id=k.id AND u.media IS NULL AND u.text!='') "
        "ORDER BY k.start DESC LIMIT ?", (limit,))]


class _Cache:
    """All window vectors in one matrix; reloaded when windows were added/removed."""
    def __init__(self):
        self.lock = threading.Lock()
        self.dirty = True
        self.sig = None
        self.M = np.zeros((0, 768), np.float32)
        self.meta = []

    def get(self, c):
        sig = c.execute("SELECT count(*), coalesce(max(id),0) FROM seg_vecs").fetchone()
        sig = (sig[0], sig[1])
        with self.lock:
            if self.dirty or sig != self.sig:
                rows = c.execute("SELECT id, conv_id, u0, u1, t0, vec FROM seg_vecs ORDER BY id").fetchall()
                self.meta = [(r[0], r[1], r[2], r[3], r[4]) for r in rows]
                self.M = (np.vstack([np.frombuffer(r[5], np.float32) for r in rows]) if rows
                          else np.zeros((0, 768), np.float32))
                self.sig, self.dirty = sig, False
            return self.M, self.meta


_CACHE = _Cache()


def semantic(c, q, lo=None, hi=None, k=80):
    """Windows closest in meaning to the question: [(sim, win_id, conv_id, u0, u1, t0)], best first, >= MIN_SIM."""
    M, meta = _CACHE.get(c)
    if not len(meta):
        return []
    qv = embed([q], query=True)
    if qv is None:
        return []
    sims = M @ qv[0]
    out = []
    for i in np.argsort(-sims):
        s = float(sims[i])
        if s < MIN_SIM or len(out) >= k:
            break
        wid, cid, u0, u1, t0 = meta[i]
        if (lo and t0 < lo) or (hi and t0 >= hi):
            continue
        out.append((s, wid, cid, u0, u1, t0))
    return out


def fuse(fts_ids, sem, limit):
    """Reciprocal rank fusion of the full-text ranking (conversation ids) and the meaning ranking (windows):
    -> [(conv_id, score, best window or None)]."""
    score, best = {}, {}
    for r, cid in enumerate(fts_ids):
        score[cid] = score.get(cid, 0) + 1 / (RRF_K + r + 1)
    seen = []
    for s, wid, cid, u0, u1, t0 in sem:
        if cid not in seen:
            seen.append(cid)
        if u0 is not None and cid not in best:            # the best transcript window: where the lines come from
            best[cid] = {"win_id": wid, "u0": u0, "u1": u1, "sim": round(s, 3)}
    for r, cid in enumerate(seen):
        score[cid] = score.get(cid, 0) + 1 / (RRF_K + r + 1)
    order = sorted(score, key=lambda x: -score[x])[:limit]
    return [(cid, score[cid], best.get(cid)) for cid in order]


def best_lines(c, q, cid, win=None, k=2):
    """The k lines of a conversation's best window closest in meaning to the question (time order), or []."""
    if not win:
        return []
    U = [dict(r) for r in c.execute("SELECT id, t0, name, how, text FROM utterances WHERE conv_id=? AND media IS NULL "
                                    "AND text!='' AND t0 >= (SELECT t0 FROM utterances WHERE id=?) "
                                    "AND t0 <= (SELECT t0 FROM utterances WHERE id=?) ORDER BY t0",
                                    (cid, win["u0"], win["u1"]))]
    U = [u for u in U if len((u["text"] or "").split()) >= 3] or U
    if not U:
        return []
    E, qv = embed([u["text"] for u in U]), embed([q], query=True)
    if E is None or qv is None:
        return U[:k]
    sims = E @ qv[0]
    top = sorted(np.argsort(-sims)[:k])
    return [dict(U[i], text=(U[i]["text"] or "")[:240]) for i in top]


def backfill(db, budget_s=20.0):
    """Index conversations that have no windows yet, for at most budget_s seconds (called from the idle loop)."""
    t, n = time.time(), 0
    with db() as c:
        todo = missing(c)
    for cid in todo:
        if time.time() - t > budget_s:
            break
        with db() as c:
            if index_conv(c, cid) is None:
                break
        n += 1
    return n


def stats(c):
    a = c.execute("SELECT count(*), count(DISTINCT conv_id) FROM seg_vecs").fetchone()
    return {"windows": a[0], "conversations": a[1], "model": MODEL, "min_sim": MIN_SIM,
            "waiting": len(missing(c, 100000))}


if __name__ == "__main__":
    print(json.dumps({"model": MODEL}))
