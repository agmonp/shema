# -*- coding: utf-8 -*-
r"""asr_correct.py -- the user's glossary, and careful fixes of the transcript text (off unless switched on).

Glossary (config.json, edited on the /home screen "איכות התמלול"):
  "asr_terms":    ["ניר", "Tailscale", ...]            the old list: spelling hints for Whisper only
  "asr_glossary": [{"term": "WhatsApp", "variants": ["וואטסאפ", "ווטסאפ"], "kind": "company", "prompt": true}, ...]
     term      the spelling to keep
     variants  wrong spellings the user has SEEN in transcripts; only these are replaced, word for word
     kind      name | place | tech | company | acronym | english   (shown on the screen; Latin kinds fix letter case)
     prompt    false = not sent to Whisper as a hint
Both feed Whisper's hint ("initial_prompt") exactly as asr_terms did.

Correction (config.json "asr": {"correct": {"enabled": false, "llm": false, "llm_model": "..."}}):
  1. deterministic: listed variants -> term (Hebrew prefix letters ו ב ל ה מ ש כ kept), letter case of Latin terms,
     a space before punctuation. Nothing else.
  2. optional local LLM (Ollama): for words that LOOK like a glossary term (letter similarity) but are not listed,
     the model only answers yes / no per candidate; it never writes text. Negations, numbers and words shorter than
     3 letters are never touched. Ollama missing = step 2 is skipped.
The raw transcript is kept next to the corrected one, with a list of every change.
"""
import difflib, json, re

PREFIX = "ובלמשהכ"
NEGATIONS = {"לא", "אין", "אל", "בלי", "אף", "אינו", "אינה", "אינם", "אינני", "מעולם", "לעולם", "שום", "no", "not",
             "never", "don't", "doesn't", "isn't", "won't", "can't"}
LATIN_KINDS = {"company", "english", "tech", "acronym"}
_NIQQUD = re.compile(r"[֑-ׇ]")
_WORD = re.compile(r"[\w֐-׿'\"׳״.+#-]+|[^\w\s]|\s+")


def glossary(cfg):
    """-> list of entries {"term", "variants", "kind", "prompt"}; asr_terms come first, as plain hints."""
    out, seen = [], set()
    for t in cfg.get("asr_terms") or []:
        t = str(t).strip()
        if t and t not in seen:
            seen.add(t)
            out.append({"term": t, "variants": [], "kind": "", "prompt": True})
    for e in cfg.get("asr_glossary") or []:
        if not isinstance(e, dict) or not str(e.get("term", "")).strip():
            continue
        t = str(e["term"]).strip()[:60]
        variants = [str(v).strip()[:60] for v in (e.get("variants") or []) if str(v).strip() and str(v).strip() != t]
        if t in seen:
            prev = next(x for x in out if x["term"] == t)
            prev["variants"] = list(dict.fromkeys(prev["variants"] + variants))
            prev["kind"] = e.get("kind") or prev["kind"]
            prev["prompt"] = e.get("prompt", True) is not False
            continue
        seen.add(t)
        out.append({"term": t, "variants": variants[:20], "kind": str(e.get("kind") or "")[:12],
                    "prompt": e.get("prompt", True) is not False})
    return out


def prompt_terms(cfg):
    return [e["term"] for e in glossary(cfg) if e["prompt"]]


def check_entry(e):
    """Problems with a glossary entry the screen should show before saving (empty list = fine)."""
    out = []
    for v in e.get("variants") or []:
        k = _key(v)
        if k in {_key(n) for n in NEGATIONS}:
            out.append(f"'{v}' היא מילת שלילה; לא תוחלף")
        if re.search(r"\d", v) and not re.search(r"\d", e.get("term", "")):
            out.append(f"'{v}' מכילה מספר; לא תוחלף")
    return out


def _key(t):
    return _NIQQUD.sub("", (t or "")).strip(".,!?;:\"'()[]״׳").lower()


def _tokens(text):
    return _WORD.findall(text or "")


def _split_prefix(word, target_key):
    """'ובוואטסאפ' and target 'וואטסאפ' -> ('וב', core) when the core matches; else (None, None)."""
    k = _key(word)
    for n in range(0, 3):
        if n and (len(k) <= n or any(ch not in PREFIX for ch in k[:n])):
            break
        if k[n:] == target_key:
            return word[:n], word[n:]
    return None, None


def deterministic(text, entries):
    """-> (new text, changes). Only listed variants, letter case of Latin terms, and ' ,' -> ','."""
    toks, changes = _tokens(text), []
    for e in entries:
        term = e["term"]
        tparts = term.split()
        pairs = [(v, v.split()) for v in e["variants"] if _key(v) not in NEGATIONS
                 and not (re.search(r"\d", v) and not re.search(r"\d", term))]
        if e.get("kind") in LATIN_KINDS and re.search(r"[A-Za-z]", term):
            pairs.append((term.lower(), term.lower().split()))     # case-only variant
        for v, vparts in pairs:
            i = 0
            while i < len(toks):
                words_at = [j for j in range(i, len(toks)) if not toks[j].isspace()][:len(vparts)]
                if len(words_at) < len(vparts):
                    break
                pre, _core = _split_prefix(toks[words_at[0]], _key(vparts[0]))
                ok = pre is not None and all(_key(toks[j]) == _key(p) for j, p in zip(words_at[1:], vparts[1:]))
                if ok:
                    old = "".join(toks[words_at[0]:words_at[-1] + 1])
                    trail = re.search(r"[.,!?;:]+$", toks[words_at[-1]])
                    new = pre + " ".join(tparts) + (trail.group(0) if trail else "")
                    if old != new:
                        toks[words_at[0]:words_at[-1] + 1] = [new]
                        changes.append({"from": old, "to": new, "rule": "glossary" if v != term.lower() else "case"})
                    i = words_at[0] + 1
                else:
                    i += 1
    out = "".join(toks)
    fixed = re.sub(r"\s+([,.!?;:])", r"\1", out)
    fixed = re.sub(r"[ \t]{2,}", " ", fixed).strip()
    if fixed != out.strip():
        changes.append({"from": "", "to": "", "rule": "spacing"})
    return fixed, changes


def near_candidates(text, entries, min_sim=0.75):
    """Words that look like a glossary term but are not it (and are not negations / numbers / short words)."""
    out = []
    toks = [t for t in _tokens(text) if not t.isspace()]
    for i, t in enumerate(toks):
        k = _key(t)
        if len(k) < 3 or k in NEGATIONS or re.search(r"\d", k):
            continue
        for e in entries:
            tk = _key(e["term"])
            if " " in tk or k == tk or not tk:
                continue
            core = k
            for n in (1, 2):
                if len(k) > n + 2 and all(ch in PREFIX for ch in k[:n]) and \
                        difflib.SequenceMatcher(None, k[n:], tk).ratio() > difflib.SequenceMatcher(None, core, tk).ratio():
                    core = k[n:]
            sim = difflib.SequenceMatcher(None, core, tk).ratio()
            if sim >= min_sim:
                out.append({"i": i, "word": t, "term": e["term"], "sim": round(sim, 2)})
    return out


def llm_review(text, cands, model, ask=None):
    """The model answers which candidate indices really mean the glossary term. ask(prompt) -> str (tests);
    default: local Ollama. Returns the accepted candidates; [] when the model is unavailable or unsure."""
    if not cands:
        return []
    lines = "\n".join(f'{n}. המילה "{c["word"]}" -> "{c["term"]}"' for n, c in enumerate(cands))
    prompt = ("לפניך משפט שתומלל אוטומטית מעברית מדוברת, ורשימת החלפות אפשריות של מילה במונח מילון.\n"
              "אשר החלפה רק אם ברור מההקשר שהדובר אמר את המונח ושהמילה היא שגיאת תמלול שלו. "
              "אם המילה היא מילה רגילה שמתאימה למשפט - אל תאשר.\n"
              f"משפט: {text}\nהחלפות:\n{lines}\n"
              'ענה ב-JSON בלבד: {"approve": [מספרי ההחלפות שאושרו]}')
    try:
        if ask is None:
            import ollama
            r = ollama.generate(model=model, prompt=prompt, format="json", options={"temperature": 0, "num_predict": 60},
                                keep_alive="2m")
            raw = r["response"]
        else:
            raw = ask(prompt)
        ok = json.loads(raw).get("approve") or []
        return [cands[n] for n in ok if isinstance(n, int) and 0 <= n < len(cands)]
    except Exception:  # noqa: BLE001
        return []


def correct(text, cfg, ask=None):
    """-> (text, changes, raw). raw is the input; text == raw when correction is off or nothing applied."""
    c = ((cfg.get("asr") or {}).get("correct") or {})
    if not c.get("enabled") or not (text or "").strip():
        return text, [], text
    entries = glossary(cfg)
    new, changes = deterministic(text, entries)
    if c.get("llm"):
        cands = near_candidates(new, entries)
        acc = llm_review(new, cands, c.get("llm_model") or cfg.get("summary_model") or "gemma3:4b", ask=ask)
        if acc:
            toks = [t for t in _tokens(new)]
            idx = [j for j, t in enumerate(toks) if not t.isspace()]
            for a in sorted(acc, key=lambda x: -x["i"]):
                j = idx[a["i"]]
                k = _key(toks[j])
                pre = ""
                for n in (2, 1):
                    if len(k) > n + 2 and all(ch in PREFIX for ch in k[:n]) and \
                            difflib.SequenceMatcher(None, k[n:], _key(a["term"])).ratio() >= a["sim"]:
                        pre = toks[j][:n]
                        break
                trail = re.search(r"[.,!?;:]+$", toks[j])
                repl = pre + a["term"] + (trail.group(0) if trail else "")
                changes.append({"from": toks[j], "to": repl, "rule": "llm", "sim": a["sim"]})
                toks[j] = repl
            new = "".join(toks)
    return new, changes, text
