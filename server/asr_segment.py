# -*- coding: utf-8 -*-
r"""asr_segment.py -- which stretches of a recording are decoded, and which decoded words belong to whom (numpy only).

The production cut (home_analyze before ASR 2.0, kept as preset "legacy"):
  Silero speech regions; a region joins the previous one when the gap is < 0.4 s and the joined span stays < 15 s;
  each region is decoded on its own with 0.2 s of audio added on both sides; regions shorter than 0.25 s are skipped.

The other presets are experiments (config.json "asr": {"segmentation": NAME} or {"seg": {...}}):
  pad05 / pad08   0.5 / 0.8 s of context on both sides
  merge           longer joins (gap < 0.8 s, up to 25 s)
  overlap         long regions are cut into 20 s windows that overlap by 2 s
  short           also decodes regions of 0.1-0.25 s ("כן", "לא")
When the decoded audio of two windows overlaps (context padding, overlapping windows) every word is owned by exactly one
window: the one whose own span contains the word's middle. That is what keeps a word from being stored twice.
"""
import numpy as np

SR = 16000

PRESETS = {
    "legacy":  {"pad": 0.2, "merge_gap": 0.4, "max_merge": 15.0, "min_len": 0.25, "split": 0.0, "overlap": 0.0, "own": False},
    "pad05":   {"pad": 0.5, "merge_gap": 0.4, "max_merge": 15.0, "min_len": 0.25, "split": 0.0, "overlap": 0.0, "own": True},
    "pad08":   {"pad": 0.8, "merge_gap": 0.4, "max_merge": 15.0, "min_len": 0.25, "split": 0.0, "overlap": 0.0, "own": True},
    "merge":   {"pad": 0.2, "merge_gap": 0.8, "max_merge": 25.0, "min_len": 0.25, "split": 0.0, "overlap": 0.0, "own": True},
    "overlap": {"pad": 0.5, "merge_gap": 0.8, "max_merge": 28.0, "min_len": 0.25, "split": 20.0, "overlap": 2.0, "own": True},
    "short":   {"pad": 0.5, "merge_gap": 0.4, "max_merge": 15.0, "min_len": 0.10, "split": 0.0, "overlap": 0.0, "own": True},
}


def settings(name=None, override=None):
    s = dict(PRESETS.get(name or "legacy", PRESETS["legacy"]))
    for k, v in (override or {}).items():
        if k in s:
            s[k] = type(s[k])(v)
    return s


def regions_from_mask(mask, merge_gap=0.4, max_merge=15.0):
    """Voiced sample mask -> [[a, b], ...] in samples (the production join rule)."""
    edges = np.flatnonzero(np.diff(np.r_[0, np.asarray(mask).astype(np.int8), 0]))
    regions = []
    for a, b in zip(edges[::2], edges[1::2]):
        if regions and a - regions[-1][1] < merge_gap * SR and b - regions[-1][0] < max_merge * SR:
            regions[-1][1] = b
        else:
            regions.append([a, b])        # numpy ints, as before: offsets (and so rounded word times) stay bit-identical
    return regions


def windows(regions, n, s):
    """Regions -> decode windows: {"a0", "b0"} = the audio slice handed to the model, {"lo", "hi"} = the span whose
    words this window owns (seconds; None = keep everything, the legacy behaviour), {"a", "b"} = the speech region."""
    out = []
    pad = int(s["pad"] * SR)
    kept = [r for r in regions if r[1] - r[0] >= s["min_len"] * SR]
    for i, (a, b) in enumerate(kept):
        # ownership boundaries: half way to the neighbouring regions
        lo = 0.0 if i == 0 else (kept[i - 1][1] + a) / 2 / SR
        hi = n / SR if i == len(kept) - 1 else (b + kept[i + 1][0]) / 2 / SR
        pieces = [(a, b)]
        if s["split"] and b - a > s["split"] * SR:
            step = int((s["split"] - s["overlap"]) * SR)
            pieces, x = [], a
            while True:
                y = min(b, x + int(s["split"] * SR))
                pieces.append((x, y))
                if y >= b:
                    break
                x += step
        for j, (x, y) in enumerate(pieces):
            plo = lo if j == 0 else (pieces[j - 1][1] + x) / 2 / SR      # middle of the overlap with the previous piece
            phi = hi if j == len(pieces) - 1 else (y + pieces[j + 1][0]) / 2 / SR
            out.append({"a": x, "b": y, "a0": max(0, x - pad), "b0": min(n, y + pad),
                        "lo": plo if s["own"] else None, "hi": phi if s["own"] else None})
    return out


def owns(win, w):
    """Does this window own word w = [t0, t1, text] (absolute seconds)?"""
    if win.get("lo") is None:
        return True
    mid = (w[0] + w[1]) / 2
    return win["lo"] <= mid < win["hi"]


def _key(t):
    return "".join(ch for ch in (t or "").lower() if ch.isalnum())


def reconcile(words):
    """Sorted words with exact re-reads removed: the same word (letters only) whose time overlaps the previous copy
    by more than half of the shorter one. Different words that overlap are kept (two people can talk at once)."""
    out = []
    for w in sorted(words, key=lambda x: (x[0], x[1])):
        if out:
            p = out[-1]
            ov = min(p[1], w[1]) - max(p[0], w[0])
            short = max(min(p[1] - p[0], w[1] - w[0]), 0.01)
            if _key(p[2]) == _key(w[2]) and ov > 0.5 * short:
                continue
        out.append(w)
    return out
