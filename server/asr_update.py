# -*- coding: utf-8 -*-
r"""asr_update.py -- find other Hebrew speech models, measure them on OUR recordings the way production transcribes,
and switch only when a measured improvement is large enough and nothing regresses; one click goes back.

Called from home_listener's idle() once a day; it acts only when EVERY_DAYS passed since config["asr_check"]["last"].
  1. Discovery (needs the internet, sends nothing of ours): ivrit-ai ct2 models with an open licence, any date.
     Newly seen ones are listed on the screen; nothing is downloaded automatically.
  2. Nominated models (the screen's "evaluate this model", or config asr_check.nominated) are evaluated whatever their
     date -- once installed (asr_models.install, an explicit action).
  3. Evaluation = asr_engine with production settings (same Silero VAD, segmentation, keep-filter and Whisper hint) on
     the gold set (gold/*.ogg + .txt in the data folder; the /home screen adds them), scored with asr_metrics.
     The current model is measured in the same run, so the comparison is like for like.
  4. Promotion gate: at least MIN_GOLD_WORDS reference words, candidate WER <= IMPROVE x current, and no gold condition
     (.json "condition") with >= 50 words getting more than REGRESS worse. asr_check.auto_promote=false = only report.
     A switch keeps the previous model in config["whisper_model_prev"] and a line in asr_check["switches"].
  5. Checks without improvement are counted (misses) but never switch the checks off.

    python -X utf8 asr_update.py                   # status
    python -X utf8 asr_update.py --check           # discovery + evaluation now (prints, changes nothing)
    python -X utf8 asr_update.py --check --apply   # ... and switch if the gate passes
    python -X utf8 asr_update.py --wer MODEL       # production-equivalent WER of one installed model on the gold set
    python -X utf8 asr_update.py --rollback        # back to the previous model
"""
import argparse, json, sys, time, urllib.parse, urllib.request
from datetime import datetime, timedelta
from pathlib import Path

PROJ = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJ))
from paths import DATA as HOME, CONFIG, device as _device  # noqa: E402

GOLD = HOME / "gold"
DEFAULT_MODEL = "ivrit-ai/whisper-large-v3-turbo-ct2"
EVERY_DAYS = 90
IMPROVE = 0.90            # candidate WER must be <= 90 % of the current one
REGRESS = 1.05            # ... and no gold condition more than 5 % worse
MIN_GOLD_WORDS = 200
MAX_CANDIDATES = 3
HF = "https://huggingface.co/api/models"
OPEN_LICENSES = ("apache-2.0", "mit", "bsd-3-clause")


def log(m):
    sys.stdout.write(time.strftime("[%H:%M:%S] ") + "asr_update: " + m + "\n")
    sys.stdout.flush()


def cfg_read():
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def cfg_write(cfg):
    tmp = CONFIG.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=1, ensure_ascii=False)
    tmp.replace(CONFIG)


def state(cfg):
    st = cfg.setdefault("asr_check", {"enabled": True, "misses": 0, "last": None, "history": []})
    for k, v in (("seen", []), ("nominated", []), ("evaluations", {}), ("switches", []), ("auto_promote", True)):
        st.setdefault(k, v)
    return st


def current_model(cfg=None):
    return (cfg or cfg_read()).get("whisper_model") or DEFAULT_MODEL


# ------------------------------------------------------------------ WER (kept for old callers; asr_metrics does the work)
def normalize(t):
    import asr_metrics
    return asr_metrics.DEFAULT.text(t)


def wer(ref, hyp):
    import asr_metrics
    c = asr_metrics.wer_counts(ref, hyp)
    return asr_metrics.rate(c), c["N"]


def gold_items():
    import asr_bench
    return [it for it in asr_bench.gold_items(GOLD) if not it["silence"]]


def evaluate(model, items, cfg=None):
    """Production-equivalent scoring of one INSTALLED model -> {"wer", "words", "by_condition", "took_s"}."""
    import torch  # noqa: F401  (cublas for CTranslate2)
    import asr_engine, asr_metrics, asr_models
    import home_analyze as HA
    cfg = dict(cfg or cfg_read())
    if not asr_models.local_path(model):
        raise FileNotFoundError(f"{model} is not installed")
    cfg["whisper_model"] = model
    cfg["asr"] = dict(cfg.get("asr") or {}, mode="legacy")      # the model alone, production segmentation
    dev = _device()
    eng = asr_engine.Engine(cfg, dev, cfg.get("asr_compute") or ("float16" if dev == "cuda" else "int8"))
    prompt = HA.asr_prompt(cfg)
    import voice_embed as VE
    tot, by, t = {}, {}, time.time()
    try:
        for it in items:
            audio = VE.read_audio(it["path"], max_s=100000)
            if audio is None:
                continue
            words, _ = eng.transcribe(audio, prompt=prompt)
            c = asr_metrics.wer_counts(it["ref"], "".join(w[2] for w in words), asr_metrics.Norm(aliases=it["aliases"]))
            asr_metrics.add(tot, c)
            asr_metrics.add(by.setdefault(it["condition"], {}), c)
    finally:
        eng.models.unload_all()
    r = lambda c: round(asr_metrics.rate(c), 4) if c.get("N") else None  # noqa: E731
    return {"wer": r(tot), "words": tot.get("N", 0), "by_condition": {k: {"wer": r(v), "words": v["N"]} for k, v in by.items()},
            "took_s": round(time.time() - t, 1), "at": datetime.now().isoformat(timespec="seconds")}


def model_wer(model, items):
    """Old interface: WER of [model] over the gold items (now production-equivalent)."""
    return evaluate(model, items)["wer"]


# ------------------------------------------------------------------ Hugging Face (discovery only)
def hf_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "shema-asr-update"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def candidates(cfg):
    """ivrit-ai ct2 models with an open licence other than the current one, of ANY date (a CPU install keeps to
    turbo / small / medium). -> (list of {"id", "modified", "license"}, current model's lastModified)."""
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
        # Unknown or restrictive licensing must never enter via an automatic update.
        details = hf_json(f"{HF}/{mid}")
        lic = (details.get("cardData") or {}).get("license")
        if lic not in OPEN_LICENSES:
            continue
        if cfg.get("device") == "cpu" and not any(k in mid for k in ("small", "medium", "turbo")):
            continue
        out.append({"id": mid, "modified": m.get("lastModified") or "", "license": lic})
    return out, cur_mod


# ------------------------------------------------------------------ the gate
def gate(cur, cand, min_words=MIN_GOLD_WORDS):
    """-> (promote?, reason). cur / cand = evaluate() results on the same gold set."""
    if not cur or not cand or cur["wer"] is None or cand["wer"] is None:
        return False, "missing result"
    if cur["words"] < min_words:
        return False, f"gold set too small ({cur['words']} words < {min_words})"
    if cand["wer"] > cur["wer"] * IMPROVE:
        return False, f"not 10 % better (WER {cand['wer']:.1%} vs {cur['wer']:.1%})"
    for k, v in cur["by_condition"].items():
        c = cand["by_condition"].get(k)
        if v["words"] >= 50 and c and c["wer"] is not None and v["wer"] is not None and c["wer"] > v["wer"] * REGRESS + 1e-9:
            return False, f"regression on '{k}' ({c['wer']:.1%} vs {v['wer']:.1%})"
    return True, f"WER {cand['wer']:.1%} vs {cur['wer']:.1%} on {cur['words']} words"


def switch(cfg, to, why, wer_from=None, wer_to=None):
    st = state(cfg)
    frm = current_model(cfg)
    cfg["whisper_model_prev"] = frm
    cfg["whisper_model"] = to
    st["switches"].append({"at": datetime.now().isoformat(timespec="seconds"), "from": frm, "to": to, "why": why,
                           "wer_from": wer_from, "wer_to": wer_to})
    st["switches"] = st["switches"][-20:]


def rollback():
    """Back to the previous model (it is still installed: switching never deletes a model)."""
    cfg = cfg_read()
    prev = cfg.get("whisper_model_prev")
    if not prev or prev == current_model(cfg):
        return {"ok": False, "msg": "אין מודל קודם לחזור אליו"}
    switch(cfg, prev, "rollback")
    state(cfg)["note"] = f"חזרנו למודל התמלול הקודם: {prev}"
    cfg_write(cfg)
    return {"ok": True, "model": prev, "msg": state(cfg)["note"]}


# ------------------------------------------------------------------ the check
def due(cfg):
    st = state(cfg)
    if not st.get("enabled", True):
        return False
    if not st.get("last"):
        return True
    return datetime.now() - datetime.fromisoformat(st["last"]) >= timedelta(days=EVERY_DAYS)


def run(force=False, apply=True, evaluate_fn=None, installed_fn=None):
    import asr_models
    evaluate_fn = evaluate_fn or evaluate
    installed_fn = installed_fn or (lambda m: bool(asr_models.local_path(m)))
    cfg = cfg_read()
    st = state(cfg)
    if not force and not due(cfg):
        return None
    now = datetime.now().isoformat(timespec="seconds")
    res = {"at": now, "current": current_model(cfg)}
    try:
        found, _ = candidates(cfg)
    except Exception as exc:  # noqa: BLE001
        log(f"could not reach Hugging Face: {exc!r}; nominated models are still evaluated")
        found, res["discovery_error"] = [], repr(exc)[:200]
    new = [c["id"] for c in found if c["id"] not in st["seen"]]
    res["discovered"], res["new"] = [c["id"] for c in found], new
    pool = list(dict.fromkeys(list(st["nominated"]) + new))[:MAX_CANDIDATES]
    ready = [m for m in pool if installed_fn(m)]
    res["not_installed"] = [m for m in pool if m not in ready]
    items = gold_items()
    res["gold_items"] = len(items)
    if not ready:
        res["result"] = "nothing installed to evaluate"
        if new:
            st["note"] = "יש מודל תמלול נוסף: " + ", ".join(new[:3]) + ". אפשר להתקין ולבדוק אותו מהמסך."
    elif not items:
        res["result"] = "no gold set"
        st["note"] = "אין סט זהב, לכן מודלים לא נבדקו (הוסף משפטים מהמסך)."
    else:
        cur = evaluate_fn(current_model(cfg), items)
        st["evaluations"][current_model(cfg)] = cur
        res["current_wer"] = cur["wer"]
        best = None
        for m in ready:
            try:
                r = evaluate_fn(m, items)
            except Exception as exc:  # noqa: BLE001
                log(f"candidate {m} failed: {exc!r}")
                continue
            st["evaluations"][m] = r
            res.setdefault("candidate_wer", {})[m] = r["wer"]
            if r["wer"] is not None and (best is None or r["wer"] < best[1]["wer"]):
                best = (m, r)
        st["current_wer"] = cur["wer"]
        ok, why = gate(cur, best[1]) if best else (False, "no candidate result")
        res["gate"] = why
        if ok and apply and st.get("auto_promote", True):
            switch(cfg, best[0], why, cur["wer"], best[1]["wer"])
            st["misses"] = 0
            st["note"] = f"עברנו למודל תמלול: {best[0]} (שגיאות מילים {best[1]['wer']:.0%} במקום {cur['wer']:.0%}). אפשר לחזור מהמסך."
            res["result"], res["switched"] = f"switched to {best[0]}", True
        elif ok:
            res["result"] = f"better: {best[0]} ({why}), not switched"
        else:
            st["misses"] = st.get("misses", 0) + 1
            res["result"] = f"kept current: {why}"
        for m in ready:
            if m in st["nominated"]:
                st["nominated"].remove(m)
    if apply:
        st["seen"] = list(dict.fromkeys(st["seen"] + res["discovered"]))[-50:]
        st["last"] = now
        st.setdefault("history", []).append(res)
        st["history"] = st["history"][-12:]
        cfg_write(cfg)
    log(json.dumps(res, ensure_ascii=False))
    return res


def maybe_run():
    """idle() hook: at most once a day, and only when EVERY_DAYS passed (or a model was nominated)."""
    try:
        cfg = cfg_read()
        st = state(cfg)
        today = datetime.now().strftime("%Y-%m-%d")
        if st.get("tried_day") == today or not (due(cfg) or (st.get("enabled", True) and st["nominated"])):
            return None
        st["tried_day"] = today
        cfg_write(cfg)
        return run(force=True)
    except Exception as exc:  # noqa: BLE001
        log(f"failed: {exc!r}")
        return None


def nominate(model):
    cfg = cfg_read()
    st = state(cfg)
    if model and model not in st["nominated"]:
        st["nominated"].append(model[:120])
    st["tried_day"] = None
    cfg_write(cfg)
    return {"ok": True, "nominated": st["nominated"]}


def status():
    """For the /home screen."""
    cfg = cfg_read()
    st = state(cfg)
    last_eval = max((v.get("at") or "" for v in st["evaluations"].values()), default=None) or None
    return {"model": current_model(cfg), "previous": cfg.get("whisper_model_prev"), "enabled": st.get("enabled", True),
            "last": st.get("last"), "last_eval": last_eval, "misses": st.get("misses", 0), "wer": st.get("current_wer"),
            "note": st.get("note"), "gold_items": len(gold_items()), "every_days": EVERY_DAYS,
            "evaluations": st["evaluations"], "switches": st["switches"][-5:], "nominated": st["nominated"],
            "seen": st["seen"][-10:], "auto_promote": st.get("auto_promote", True), "min_gold_words": MIN_GOLD_WORDS,
            "next": (datetime.fromisoformat(st["last"]) + timedelta(days=EVERY_DAYS)).strftime("%Y-%m-%d") if st.get("last") else "בקרוב"}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--wer")
    ap.add_argument("--rollback", action="store_true")
    a = ap.parse_args()
    if a.wer:
        it = gold_items()
        print(len(it), "gold items;", json.dumps(evaluate(a.wer, it), ensure_ascii=False))
    elif a.rollback:
        print(json.dumps(rollback(), ensure_ascii=False))
    elif a.check:
        print(json.dumps(run(force=True, apply=a.apply), ensure_ascii=False, indent=1))
    else:
        print(json.dumps(status(), ensure_ascii=False, indent=1))
