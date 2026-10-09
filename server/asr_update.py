# -*- coding: utf-8 -*-
r"""asr_update.py -- every 90 days, look for a better Hebrew speech model (ivrit-ai, ct2 format) and switch to it
only when it is clearly better on OUR recordings.

Called from home_listener's idle() once a day; it acts only when 90 days passed since config["asr_check"]["last"].
  1. Hugging Face model list (author ivrit-ai, search "whisper", newest first) -> ct2 models newer than the current one.
  2. Gold set: gold/*.ogg + *.txt in the data folder (a recording + its correct text; the /home screen adds them: "add to gold
     set" on an utterance, with the text editable). Without gold files only a note is left ("a new model exists").
  3. WER of the current model and of each candidate on the gold set (runs only when the worker is idle).
     Candidate >= 10 % better (WER <= 0.9 x current) -> config["whisper_model"] = candidate (home_analyze reads it
     when its models load), and a line in config["asr_check"]["history"].
  4. misses += 1 for every check without improvement; 3 in a row -> enabled=False and a note in the evening summary.
     Switch it back on from the screen (/home/api/asr_check {"enabled": true}).

    python -X utf8 asr_update.py --check          # force a check now (prints, changes nothing)
    python -X utf8 asr_update.py --check --apply  # force a check now and switch if better
    python -X utf8 asr_update.py --wer MODEL      # WER of one model on the gold set
"""
import argparse, json, os, re, sys, time, urllib.parse, urllib.request
from datetime import datetime, timedelta
from pathlib import Path

PROJ = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJ))
from paths import DATA as HOME, CONFIG, device as _device  # noqa: E402

GOLD = HOME / "gold"
DEFAULT_MODEL = "ivrit-ai/whisper-large-v3-turbo-ct2"
EVERY_DAYS = 90
IMPROVE = 0.90            # candidate WER must be <= 90 % of the current one
MAX_MISSES = 3
HF = "https://huggingface.co/api/models"


def log(m):
    sys.stdout.write(time.strftime("[%H:%M:%S] ") + "asr_update: " + m + "\n")
    sys.stdout.flush()


def cfg_read():
    return json.load(open(CONFIG, encoding="utf-8"))


def cfg_write(cfg):
    tmp = CONFIG.with_suffix(".tmp")
    json.dump(cfg, open(tmp, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    tmp.replace(CONFIG)


def state(cfg):
    return cfg.setdefault("asr_check", {"enabled": True, "misses": 0, "last": None, "history": []})


def current_model(cfg=None):
    return (cfg or cfg_read()).get("whisper_model") or DEFAULT_MODEL


# ------------------------------------------------------------------ WER
_NIQQUD = re.compile(r"[֑-ׇ]")
_FINALS = str.maketrans("ךםןףץ", "כמנפצ")


def normalize(t):
    """No niqqud, no punctuation, final letters folded, lower case, one space."""
    t = _NIQQUD.sub("", t or "").translate(_FINALS).lower()
    t = re.sub(r"[^\w\s]|_", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def wer(ref, hyp):
    r, h = normalize(ref).split(), normalize(hyp).split()
    if not r:
        return (0.0 if not h else 1.0), 0
    d = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        prev, d[0] = d[0], i
        for j, hw in enumerate(h, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (rw != hw))
    return d[len(h)] / len(r), len(r)


def gold_items():
    out = []
    for a in sorted(GOLD.glob("*.ogg")) + sorted(GOLD.glob("*.wav")):
        t = a.with_suffix(".txt")
        if t.exists() and t.read_text(encoding="utf-8").strip():
            out.append((a, t.read_text(encoding="utf-8").strip()))
    return out


def model_wer(model, items):
    """Word error rate of [model] over the gold items (total errors / total reference words)."""
    import torch  # noqa: F401  (cublas for CTranslate2)
    from faster_whisper import WhisperModel
    sys.path.insert(0, str(PROJ))
    import voice_embed as VE
    import home_analyze as HA
    dev = _device()
    m = WhisperModel(model, device=dev, compute_type=cfg_read().get("asr_compute") or ("float16" if dev == "cuda" else "int8"))
    errs = words = 0.0
    prompt = HA.asr_prompt()
    for path, ref in items:
        audio = VE.read_audio(str(path), max_s=600)
        if audio is None:
            continue
        segs, _ = m.transcribe(audio, language="he", beam_size=5, vad_filter=True, condition_on_previous_text=False,
                               initial_prompt=prompt)
        w, n = wer(ref, " ".join(s.text for s in segs))
        errs += w * n
        words += n
    del m
    try:
        import gc
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass
    return round(errs / words, 4) if words else None


# ------------------------------------------------------------------ Hugging Face
def hf_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "shema-asr-update"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def candidates(cfg):
    """ct2 models of ivrit-ai that were modified after the current model (same size family when the PC has no
    NVIDIA card: a CPU install keeps to models whose name says turbo / small / medium)."""
    cur = current_model(cfg)
    try:
        cur_mod = hf_json(f"{HF}/{cur}").get("lastModified") or ""
    except Exception:  # noqa: BLE001
        cur_mod = ""
    q = urllib.parse.urlencode({"author": "ivrit-ai", "search": "whisper", "sort": "lastModified", "direction": "-1", "limit": 40})
    out = []
    for m in hf_json(f"{HF}?{q}"):
        mid = m.get("id") or m.get("modelId")
        if not mid or mid == cur or "ct2" not in mid.lower():
            continue
        if cfg.get("device") == "cpu" and "large-v3-turbo" not in mid and not any(k in mid for k in ("small", "medium", "turbo")):
            continue
        mod = m.get("lastModified") or ""
        if not cur_mod or mod > cur_mod:
            out.append({"id": mid, "modified": mod})
    return out, cur_mod


# ------------------------------------------------------------------ the check
def due(cfg):
    st = state(cfg)
    if not st.get("enabled", True):
        return False
    if not st.get("last"):
        return True
    return datetime.now() - datetime.fromisoformat(st["last"]) >= timedelta(days=EVERY_DAYS)


def run(force=False, apply=True):
    cfg = cfg_read()
    st = state(cfg)
    if not force and not due(cfg):
        return None
    now = datetime.now().isoformat(timespec="seconds")
    res = {"at": now, "current": current_model(cfg)}
    try:
        cands, cur_mod = candidates(cfg)
    except Exception as exc:  # noqa: BLE001
        log(f"could not reach Hugging Face: {exc!r}; will try again tomorrow")
        return {"error": repr(exc)}
    res["candidates"] = [c["id"] for c in cands]
    items = gold_items()
    res["gold_items"] = len(items)
    if not cands:
        st["misses"] = st.get("misses", 0) + 1
        res["result"] = "no newer model"
    elif not items:
        st["note"] = "יש מודל תמלול חדש: " + ", ".join(c["id"] for c in cands[:3]) + ". אין סט זהב, לכן לא נבדק (הוסף משפטים מהמסך)."
        st["misses"] = st.get("misses", 0) + 1
        res["result"] = "new model exists, no gold set"
    else:
        cur_wer = model_wer(current_model(cfg), items)
        res["current_wer"] = cur_wer
        best = None
        for c in cands[:3]:
            try:
                w = model_wer(c["id"], items)
            except Exception as exc:  # noqa: BLE001
                log(f"candidate {c['id']} failed: {exc!r}")
                continue
            res.setdefault("candidate_wer", {})[c["id"]] = w
            if w is not None and (best is None or w < best[1]):
                best = (c["id"], w)
        st["current_wer"] = cur_wer
        if best and cur_wer and best[1] <= cur_wer * IMPROVE:
            res["result"] = f"better: {best[0]} (WER {best[1]} vs {cur_wer})"
            if apply:
                cfg["whisper_model"] = best[0]
                st["misses"] = 0
                st["note"] = f"עברנו למודל תמלול חדש: {best[0]} (שגיאות מילים {best[1]:.0%} במקום {cur_wer:.0%})"
                res["switched"] = True
        else:
            st["misses"] = st.get("misses", 0) + 1
            res["result"] = "no improvement of 10 % or more"
    if apply:
        st["last"] = now
        st.setdefault("history", []).append(res)
        st["history"] = st["history"][-12:]
        if st.get("misses", 0) >= MAX_MISSES:
            st["enabled"] = False
            st["note"] = (st.get("note") or "") + f" בדיקת המודלים כבתה אחרי {MAX_MISSES} בדיקות בלי שיפור. אפשר להפעיל מחדש מהמסך."
        cfg_write(cfg)
    log(json.dumps(res, ensure_ascii=False))
    return res


def maybe_run():
    """idle() hook: at most once a day, and only when 90 days passed."""
    try:
        cfg = cfg_read()
        st = state(cfg)
        today = datetime.now().strftime("%Y-%m-%d")
        if st.get("tried_day") == today or not due(cfg):
            return None
        st["tried_day"] = today
        cfg_write(cfg)
        return run()
    except Exception as exc:  # noqa: BLE001
        log(f"failed: {exc!r}")
        return None


def status():
    """For the /home screen."""
    cfg = cfg_read()
    st = state(cfg)
    return {"model": current_model(cfg), "enabled": st.get("enabled", True), "last": st.get("last"),
            "misses": st.get("misses", 0), "wer": st.get("current_wer"), "note": st.get("note"),
            "gold_items": len(gold_items()), "every_days": EVERY_DAYS,
            "next": (datetime.fromisoformat(st["last"]) + timedelta(days=EVERY_DAYS)).strftime("%Y-%m-%d") if st.get("last") else "בקרוב"}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--wer")
    a = ap.parse_args()
    if a.wer:
        it = gold_items()
        print(len(it), "gold items; WER", model_wer(a.wer, it))
    elif a.check:
        print(json.dumps(run(force=True, apply=a.apply), ensure_ascii=False, indent=1))
    else:
        print(json.dumps(status(), ensure_ascii=False, indent=1))
