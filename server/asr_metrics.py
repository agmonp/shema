# -*- coding: utf-8 -*-
r"""asr_metrics.py -- how wrong is a transcript? (pure Python, no models)

Every candidate system is scored with the SAME normalisation (Norm), so differences come from the audio side only.

  wer_counts(ref, hyp)      -> substitutions / deletions / insertions / reference words (word level)
  cer_counts(ref, hyp)      -> the same on characters (spaces removed)
  term_hits(ref, hyp, terms) -> which reference names / numbers / Latin terms the hypothesis kept (strict check)
  timestamp_issues(words)   -> words out of order, overlapping, too long / too short, outside the audio

Aliases: {"canonical": ["variant", ...]} -- valid spellings / transliterations that count as the same word
(e.g. {"וואטסאפ": ["ווטסאפ", "whatsapp"]}). They are applied to the reference AND the hypothesis.
"""
import re
import unicodedata

_NIQQUD = re.compile(r"[֑-ׇ]")
_FINALS = str.maketrans("ךםןףץ", "כמנפצ")
_BIDI = re.compile(r"[‎‏‪-‮⁦-⁩]")
# geresh / gershayim (and the ASCII quotes Whisper writes for them) INSIDE a word: צה"ל -> צהל, ג'ירפה -> גירפה
_INWORD_QUOTE = re.compile(r"(?<=\w)[\"'׳״’”](?=\w)")
_PREFIXES = "ובלמשהכ"


class Norm:
    """Configurable Hebrew normalisation. Defaults = the lenient score (punctuation, niqqud, final letters, case,
    whitespace all ignored). strict=True keeps final letters and inner quotes (used for the names / numbers check)."""

    def __init__(self, niqqud=True, punctuation=True, finals=True, case=True, maqaf_split=True, aliases=None):
        self.niqqud, self.punctuation, self.finals, self.case = niqqud, punctuation, finals, case
        self.maqaf_split = maqaf_split
        self.aliases = []                       # (variant tokens, canonical tokens), longest first
        for canon, variants in (aliases or {}).items():
            c = self._base(canon).split()
            for v in variants:
                vt = self._base(v).split()
                if vt and vt != c:
                    self.aliases.append((vt, c))
        self.aliases.sort(key=lambda a: -len(a[0]))

    def _base(self, t):
        t = unicodedata.normalize("NFC", t or "")
        t = _BIDI.sub("", t)
        if self.niqqud:
            t = _NIQQUD.sub("", t)
        if self.maqaf_split:
            t = t.replace("־", " ").replace("-", " ")
        if self.punctuation:
            t = _INWORD_QUOTE.sub("", t)
            t = re.sub(r"[^\w\s%]|_", " ", t)
        if self.finals:
            t = t.translate(_FINALS)
        if self.case:
            t = t.lower()
        return re.sub(r"\s+", " ", t).strip()

    def tokens(self, t):
        toks = self._base(t).split()
        if not self.aliases:
            return toks
        out, i = [], 0
        while i < len(toks):
            for var, canon in self.aliases:
                n = len(var)
                if toks[i:i + n] == var:
                    out += canon
                    i += n
                    break
                # the variant with a Hebrew prefix letter: ו+variant -> ו+canonical
                if n == 1 and len(toks[i]) > 1 and toks[i][0] in _PREFIXES and toks[i][1:] == var[0]:
                    out.append(toks[i][0] + canon[0])
                    i += 1
                    break
            else:
                out.append(toks[i])
                i += 1
        return out

    def text(self, t):
        return " ".join(self.tokens(t))


DEFAULT = Norm()


def align(r, h):
    """Levenshtein alignment of two token lists -> list of (op, ref_token, hyp_token), op in = S D I."""
    n, m = len(r), len(h)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        d[i][0] = i
    for j in range(1, m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        ri, row, prev = r[i - 1], d[i], d[i - 1]
        for j in range(1, m + 1):
            row[j] = min(prev[j] + 1, row[j - 1] + 1, prev[j - 1] + (ri != h[j - 1]))
    ops, i, j = [], n, m
    while i or j:
        if i and j and d[i][j] == d[i - 1][j - 1] + (r[i - 1] != h[j - 1]):
            ops.append(("=" if r[i - 1] == h[j - 1] else "S", r[i - 1], h[j - 1]))
            i, j = i - 1, j - 1
        elif i and d[i][j] == d[i - 1][j] + 1:
            ops.append(("D", r[i - 1], None))
            i -= 1
        else:
            ops.append(("I", None, h[j - 1]))
            j -= 1
    return ops[::-1]


def _counts(r, h):
    c = {"S": 0, "D": 0, "I": 0, "N": len(r), "hyp": len(h)}
    for op, _, _ in align(r, h):
        if op != "=":
            c[op] += 1
    return c


def wer_counts(ref, hyp, norm=DEFAULT):
    return _counts(norm.tokens(ref), norm.tokens(hyp))


def cer_counts(ref, hyp, norm=DEFAULT):
    return _counts(list(norm.text(ref).replace(" ", "")), list(norm.text(hyp).replace(" ", "")))


def rate(c):
    """errors / reference units; an empty reference scores 0 when the hypothesis is empty too, else 1."""
    if not c["N"]:
        return 0.0 if not c["hyp"] else 1.0
    return (c["S"] + c["D"] + c["I"]) / c["N"]


def add(total, c):
    for k, v in c.items():
        total[k] = total.get(k, 0) + v
    return total


# ------------------------------------------------------------------ strict checks: names, numbers, Latin terms
_NUM = re.compile(r"\d+(?:[.,:/]\d+)*")
_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9+.#-]*")


def _has(tokens, term_tokens):
    """term (1+ tokens) present in tokens, allowing one Hebrew prefix letter on its first token."""
    n = len(term_tokens)
    for i in range(len(tokens) - n + 1):
        first = tokens[i]
        if (first == term_tokens[0] or (len(first) > 1 and first[0] in _PREFIXES and first[1:] == term_tokens[0])) \
                and tokens[i + 1:i + n] == term_tokens[1:]:
            return True
    return False


def term_hits(ref, hyp, terms=(), aliases=None):
    """-> {"entities": [hits, total], "numbers": [...], "latin": [...], "missed": [...]}.
    Strict: final letters and inner quotes are kept; only listed aliases are accepted as other spellings."""
    strict = Norm(finals=False, aliases=aliases)
    rt, ht = strict.tokens(ref), strict.tokens(hyp)
    out = {"entities": [0, 0], "numbers": [0, 0], "latin": [0, 0], "missed": []}
    seen = set()
    for t in terms or ():
        tt = strict.tokens(t)
        if tt and _has(rt, tt) and t not in seen:
            seen.add(t)
            out["entities"][1] += 1
            if _has(ht, tt):
                out["entities"][0] += 1
            else:
                out["missed"].append(t)
    hyp_join = " ".join(ht)
    for kind, rx in (("numbers", _NUM), ("latin", _LATIN)):
        for tok in rx.findall(" ".join(rt)):
            out[kind][1] += 1
            if re.search(r"(?<![\w])" + re.escape(tok) + r"(?![\w])", hyp_join) or \
                    re.search(r"(?<![\w])[" + _PREFIXES + r"]" + re.escape(tok) + r"(?![\w])", hyp_join):
                out[kind][0] += 1
            else:
                out["missed"].append(tok)
    return out


# ------------------------------------------------------------------ timestamps
def timestamp_issues(words, audio_s=None):
    """words [[t0, t1, text], ...] -> counts of suspicious word times (no reference times needed)."""
    out = {"words": len(words), "backwards": 0, "overlap": 0, "too_long": 0, "too_short": 0, "outside": 0}
    for i, w in enumerate(words):
        t0, t1 = float(w[0]), float(w[1])
        if t1 < t0:
            out["backwards"] += 1
        if t1 - t0 > 3.0:
            out["too_long"] += 1
        if t1 - t0 < 0.02:
            out["too_short"] += 1
        if t0 < -0.01 or (audio_s is not None and t1 > audio_s + 0.05):
            out["outside"] += 1
        if i and t0 < float(words[i - 1][1]) - 0.05:
            out["overlap"] += 1
    return out


def coverage(words, speech, tol=0.3):
    """Share of reference speech time [[t0, t1], ...] that has at least one recognised word nearby."""
    tot = sum(b - a for a, b in speech)
    if tot <= 0:
        return None
    got = 0.0
    for a, b in speech:
        spans = sorted((max(a, w[0] - tol), min(b, w[1] + tol)) for w in words if w[1] + tol > a and w[0] - tol < b)
        cur = a
        for s, e in spans:
            if e > cur:
                got += e - max(s, cur)
                cur = e
    return got / tot
