# -*- coding: utf-8 -*-
r"""asr_quality.py -- is this piece of transcript suspicious, and which of two readings should be kept? (no models)

The signals are Whisper's own numbers plus simple text checks. They are HEURISTICS: a flag means "worth a second look",
not a probability that the text is wrong. The default limits are Whisper's own fallback limits (compression ratio 2.4,
log-probability -1.0, no-speech 0.6) and stay in config.json "asr": {"quality": {...}} so a benchmark can move them.

  window_signals(segments, voiced_s, kept_words)  -> numbers for one decode window
  flags(sig, limits)                              -> list of reasons ("low_logprob", "repetition", ...)
  choose(primary, secondary, limits)              -> which candidate to keep, why, and whether it stays uncertain
"""
import re
from collections import Counter

LIMITS = {
    "logprob": -1.0,          # mean token log-probability below this
    "no_speech": 0.6,         # Whisper thinks there was no speech, yet wrote words
    "compression": 2.4,       # gzip ratio of the text above this = repeated text
    "max_wps": 5.5,           # words per voiced second above this (fast Hebrew talk is ~3-4)
    "empty_voiced_s": 1.0,    # this much speech by the VAD and not one word kept
    "agree": 0.8,             # word similarity at which two readings count as the same
}
SEVERITY = {"empty": 3, "repetition": 3, "compression": 2, "no_speech": 2, "dropped": 2, "low_logprob": 1, "rate": 1,
            "timestamps": 1}


def limits(cfg_quality=None):
    out = dict(LIMITS)
    for k, v in (cfg_quality or {}).items():
        if k in out:
            out[k] = float(v)
    return out


def _tokens(t):
    return [w for w in re.sub(r"[^\w\s]", " ", (t or "").lower()).split() if w]


def repetition(text):
    """A word or a 2-4 word phrase said 3+ times in a row, or one word making up most of a longer text."""
    toks = _tokens(text)
    if len(toks) >= 5 and Counter(toks).most_common(1)[0][1] / len(toks) > 0.5:
        return True
    for n in (1, 2, 3, 4):
        for i in range(len(toks) - 3 * n + 1):
            if toks[i:i + n] == toks[i + n:i + 2 * n] == toks[i + 2 * n:i + 3 * n]:
                return True
    return False


def window_signals(segments, voiced_s, kept_words):
    """segments: what the model returned for one window (all of them, kept or not); kept_words: words that survived the
    production filter. Durations weight the per-segment numbers."""
    segs = list(segments)
    dur = [max(float(s.end) - float(s.start), 0.01) for s in segs]
    tot = sum(dur) or 1.0
    text = " ".join(w[2] for w in kept_words).strip()
    long_words = sum(1 for w in kept_words if w[1] - w[0] > 3.0)
    return {
        "logprob": round(sum(float(s.avg_logprob) * d for s, d in zip(segs, dur)) / tot, 3) if segs else None,
        "no_speech": round(max((float(s.no_speech_prob) for s in segs), default=0.0), 3),
        "compression": round(max((float(s.compression_ratio) for s in segs), default=0.0), 2),
        "segments": len(segs),
        "dropped": sum(1 for s in segs if getattr(s, "_dropped", False)),
        "words": len(kept_words),
        "voiced_s": round(float(voiced_s), 2),
        "wps": round(len(kept_words) / voiced_s, 2) if voiced_s > 0 else None,
        "repetition": repetition(text),
        "long_words": long_words,
        "text": text,
    }


def flags(sig, lim=None):
    lim = lim or LIMITS
    out = []
    if not sig["words"]:
        if sig["voiced_s"] >= lim["empty_voiced_s"]:
            out.append("empty")
        if sig.get("dropped"):
            out.append("dropped")
        return out
    if sig["logprob"] is not None and sig["logprob"] < lim["logprob"]:
        out.append("low_logprob")
    if sig["no_speech"] > lim["no_speech"]:
        out.append("no_speech")
    if sig["compression"] > lim["compression"]:
        out.append("compression")
    if sig["repetition"]:
        out.append("repetition")
    if sig["wps"] is not None and sig["wps"] > lim["max_wps"]:
        out.append("rate")
    if sig["long_words"]:
        out.append("timestamps")
    if sig.get("dropped"):
        out.append("dropped")
    return out


def severity(fl):
    return sum(SEVERITY.get(f, 1) for f in fl)


def similarity(a, b):
    """1 - word error rate of b against a, floored at 0 (1.0 = same words)."""
    from asr_metrics import align
    ra, rb = _tokens(a), _tokens(b)
    if not ra and not rb:
        return 1.0
    if not ra or not rb:
        return 0.0
    errs = sum(1 for op, _, _ in align(ra, rb) if op != "=")
    return max(0.0, 1.0 - errs / max(len(ra), len(rb)))


def choose(primary, secondary, lim=None):
    """primary / secondary: {"model", "words", "sig", "flags"} -> (chosen candidate, reason, uncertain).
    Rules (in order): the readings agree -> primary, settled; only the secondary is clean -> secondary;
    the secondary is less suspicious by a clear margin -> secondary, still uncertain; otherwise -> primary, uncertain.
    Never mixes words of the two readings."""
    lim = lim or LIMITS
    if secondary is None:
        return primary, "no_secondary", bool(primary["flags"])
    sim = similarity(primary["sig"]["text"], secondary["sig"]["text"])
    if sim >= lim["agree"]:
        # two models agreeing settles it, unless both show the same serious problem (shared repeated / empty text)
        shared = {f for f in primary["flags"] if SEVERITY.get(f, 1) >= 2} & set(secondary["flags"])
        return primary, f"agree {sim:.2f}" + (f", both {','.join(sorted(shared))}" if shared else ""), bool(shared)
    p, s = severity(primary["flags"]), severity(secondary["flags"])
    if not secondary["flags"] and primary["flags"]:
        return secondary, f"secondary clean (sim {sim:.2f})", False
    if s + 1 < p:
        return secondary, f"secondary less suspicious {s}<{p} (sim {sim:.2f})", True
    return primary, f"kept primary {p}<={s + 1} (sim {sim:.2f})", True
