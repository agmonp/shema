# -*- coding: utf-8 -*-
r"""voice_speakers.py -- helpers shared by the analysis: words -> short chunks, and the voiceprint of a
person for a given year (when optional voiceprints.json / voiceprints.npz exist in the data folder)."""

GAP, MAX_CHUNK = 0.35, 3.0


def print_for(entries, year):
    """The person's print for that year: exact/closest child year, else 'all'/'adult'."""
    yearly = [(p, v) for p, v in entries if p.get("year")]
    other = [(p, v) for p, v in entries if not p.get("year")]
    if yearly and year:
        p, v = min(yearly, key=lambda pv: abs(pv[0]["year"] - year))
        if abs(p["year"] - year) <= 2:
            return v
        if other and year > max(q["year"] for q, _ in yearly):
            return other[0][1]
        return v if abs(p["year"] - year) <= 4 else None
    if other:
        return other[0][1]
    return None


def chunks_of(words):
    """words [[t0, t1, text], ...] -> chunks split at pauses >= GAP s or after MAX_CHUNK s."""
    out, cur = [], []
    for w in words:
        if cur and (w[0] - cur[-1][1] >= GAP or w[1] - cur[0][0] > MAX_CHUNK):
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return [{"t0": c[0][0], "t1": c[-1][1], "text": "".join(x[2] for x in c).strip()} for c in out]
