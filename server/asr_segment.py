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

_BASE = {"pad": 0.2, "merge_gap": 0.4, "max_merge": 15.0, "min_len": 0.25, "split": 0.0, "overlap": 0.0, "own": False,
         "vad_norm": False}
PRESETS = {
    "legacy":  dict(_BASE),
    "pad05":   dict(_BASE, pad=0.5, own=True),
    "pad08":   dict(_BASE, pad=0.8, own=True),
    "merge":   dict(_BASE, merge_gap=0.8, max_merge=25.0, own=True),
    "overlap": dict(_BASE, pad=0.5, merge_gap=0.8, max_merge=28.0, split=20.0, overlap=2.0, own=True),
    "short":   dict(_BASE, pad=0.5, min_len=0.10, own=True),
    # the VAD hears a copy raised to a fixed peak (quiet speakers / a phone in a pocket); Whisper still gets the original
    "vadnorm": dict(_BASE, vad_norm=True),
}


def settings(name=None, override=None):
    """A preset; "pad05+vadnorm" combines presets left to right (later non-default values win)."""
    s = dict(_BASE)
    for part in (name or "legacy").split("+"):
        p = PRESETS.get(part, PRESETS["legacy"])
        s.update({k: v for k, v in p.items() if v != _BASE[k]})
    for k, v in (override or {}).items():
        if k in s:
            s[k] = (str(v).lower() in ("1", "true", "yes")) if isinstance(s[k], bool) else type(s[k])(v)
    return s


def vad_view(audio, peak=0.5):
    """What the VAD listens to when vad_norm is on: the same audio scaled so its loudest sample is `peak`
    (never more than 30 dB of gain, so pure hiss stays hiss)."""
    m = float(np.max(np.abs(audio))) if len(audio) else 0.0
    if m <= 0:
        return audio
    return (audio * min(peak / m, 10 ** (30 / 20))).astype(np.float32)


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


def speaker_cuts(audio, region, embed, thr, win=1.5, hop=0.25, edge=1.0, max_cuts=3):
    """Points (samples) inside one speech region where the voice before differs from the voice after: a 1.5 s
    voice vector every 0.25 s; at each point, the window ending there vs the window starting there. Cut at the
    least similar point when its cosine is below thr, then look again on both sides (at most max_cuts).
    embed(wave) -> unit vector. Experiment (2026-10-18): asr_engine uses it only with SHEMA_ASR_SPKCUT set."""
    a, b = int(region[0]), int(region[1])
    w, h, e = int(win * SR), int(hop * SR), int(edge * SR)
    if b - a < 2 * e + h:
        return []
    starts = list(range(a, b - w + 1, h))
    if len(starts) < 2:
        return []
    vec = {s: embed(audio[s:s + w]) for s in starts}

    def best(lo, hi):
        cand = []
        for t in range(lo + e, hi - e + 1, h):
            left, right = t - w, t
            if left in vec and right in vec and left >= lo and right + w <= hi:
                cand.append((float(vec[left] @ vec[right]), t))
        return min(cand) if cand else None

    cuts, spans = [], [(a, b)]
    while spans and len(cuts) < max_cuts:
        lo, hi = spans.pop(0)
        x = best(lo, hi)
        if x and x[0] < thr:
            cuts.append(x[1])
            spans += [(lo, x[1]), (x[1], hi)]
    return sorted(cuts)


def split_regions(audio, regions, embed, thr):
    """Regions cut at speaker changes (speaker_cuts): each piece is then decoded on its own."""
    out = []
    for r in regions:
        pts = [int(r[0])] + speaker_cuts(audio, r, embed, thr) + [int(r[1])]
        out += [[pts[i], pts[i + 1]] for i in range(len(pts) - 1)]
    return out


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
