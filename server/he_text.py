# -*- coding: utf-8 -*-
"""he_text.py -- Hebrew prefix forms for the conversation search (no models, no dependencies)."""
import re

PREFIX = "ובלמשהכ"
_HEB = re.compile(r"[א-ת]+")


def he_variants(tok):
    """The word, then without one or two prefix letters (ו ב ל מ ש ה כ)."""
    out, t = [tok], tok
    for _ in range(2):
        if len(t) > 3 and t[0] in PREFIX:
            t = t[1:]
            out.append(t)
        else:
            break
    return out


def expand_he(text):
    """Hebrew text + the prefix-less forms of its words (indexed, never shown)."""
    extra = []
    for w in _HEB.findall(text or ""):
        v = he_variants(w)
        if len(v) > 1:
            extra += v[1:]
    return (text or "") + ("\n" + " ".join(extra) if extra else "")
