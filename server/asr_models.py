# -*- coding: utf-8 -*-
r"""asr_models.py -- which speech models are on this PC, installing one on request, and loading them lazily.

Nothing is downloaded unless the user asks (installer, the /home screen's "install" button, or this command line):

    python -X utf8 asr_models.py                                   # what is installed
    python -X utf8 asr_models.py --install ivrit-ai/whisper-large-v3-ct2
    python -X utf8 asr_models.py --verify  ivrit-ai/whisper-large-v3-ct2   # sha256 of every file against Hugging Face

An install checks the licence (only open licences), the free disk space, downloads into the Hugging Face cache and
then checks every file's size and sha256 against the model's published metadata.
Once installed, models are loaded with local_files_only=True, so recognition works with no internet connection.
"""
import argparse, gc, hashlib, json, os, shutil, sys, threading, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

PRIMARY = "ivrit-ai/whisper-large-v3-turbo-ct2"
SECONDARY = "ivrit-ai/whisper-large-v3-ct2"
KNOWN = {   # measured sizes on disk; VRAM is approximate for float16 weights (CTranslate2 adds working memory)
    PRIMARY: {"gb": 1.62, "vram_gb": 1.7, "note": "turbo: 4 decoder layers, the production model"},
    SECONDARY: {"gb": 3.09, "vram_gb": 3.2, "note": "large-v3: 32 decoder layers, slower, optional"},
}
OPEN_LICENSES = ("apache-2.0", "mit", "bsd-3-clause")
INSTALL = {"state": "idle"}            # the /home screen polls this while an install runs


def log(m):
    sys.stdout.write(time.strftime("[%H:%M:%S] ") + "asr_models: " + m + "\n")
    sys.stdout.flush()


def local_path(model):
    """Folder of the cached model, or None when it is not (completely) on this PC. No network."""
    if os.path.isdir(model):
        return model
    try:
        from huggingface_hub import snapshot_download
        p = snapshot_download(model, local_files_only=True)
        return p if (Path(p) / "model.bin").exists() else None
    except Exception:  # noqa: BLE001
        return None


def installed(models=(PRIMARY, SECONDARY)):
    return {m: bool(local_path(m)) for m in models}


def _meta(model):
    from huggingface_hub import HfApi
    return HfApi().model_info(model, files_metadata=True)


def install(model, verify=True):
    """-> {"ok": bool, "msg": str}. Safe to call again: a complete cached copy is only re-verified."""
    INSTALL.update(state="checking", model=model, msg="בודק רישיון ומקום פנוי", at=time.time())
    try:
        info = _meta(model)
    except Exception as exc:  # noqa: BLE001
        INSTALL.update(state="failed", msg=f"אין חיבור ל-Hugging Face: {exc!r}"[:200])
        return {"ok": False, "msg": INSTALL["msg"]}
    lic = (info.card_data or {}).get("license") if info.card_data else None
    if lic not in OPEN_LICENSES:
        INSTALL.update(state="failed", msg=f"רישיון לא פתוח ({lic}); לא מותקן")
        return {"ok": False, "msg": INSTALL["msg"]}
    files = {s.rfilename: s for s in info.siblings}
    if "model.bin" not in files:
        INSTALL.update(state="failed", msg="זה לא מודל CTranslate2 (אין model.bin)")
        return {"ok": False, "msg": INSTALL["msg"]}
    need = sum((s.size or 0) for s in info.siblings)
    from huggingface_hub.constants import HF_HUB_CACHE
    cache = Path(HF_HUB_CACHE)
    cache.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(cache).free
    if not local_path(model) and free < need * 1.2 + 2e9:
        INSTALL.update(state="failed", msg=f"אין מספיק מקום: צריך {need / 1e9:.1f} GB, פנוי {free / 1e9:.1f} GB")
        return {"ok": False, "msg": INSTALL["msg"]}
    INSTALL.update(state="downloading", msg=f"מוריד {need / 1e9:.1f} GB")
    from huggingface_hub import snapshot_download
    try:
        path = snapshot_download(model, revision=info.sha)
    except Exception as exc:  # noqa: BLE001
        INSTALL.update(state="failed", msg=f"ההורדה נכשלה: {exc!r}"[:200])
        return {"ok": False, "msg": INSTALL["msg"]}
    if verify:
        INSTALL.update(state="verifying", msg="בודק שלמות קבצים")
        bad = verify_files(path, info)
        if bad:
            INSTALL.update(state="failed", msg="קבצים פגומים: " + ", ".join(bad))
            return {"ok": False, "msg": INSTALL["msg"], "bad": bad}
    INSTALL.update(state="done", msg="הותקן ונבדק", path=path, license=lic, revision=info.sha)
    return {"ok": True, "msg": INSTALL["msg"], "path": path, "license": lic, "revision": info.sha}


def verify_files(path, info=None, model=None):
    """Names of files whose size or sha256 differs from the published metadata ([] = all good)."""
    info = info or _meta(model)
    bad = []
    for s in info.siblings:
        f = Path(path) / s.rfilename
        if not f.exists():
            bad.append(s.rfilename + " (חסר)")
            continue
        if s.size is not None and f.stat().st_size != s.size:
            bad.append(s.rfilename + " (גודל)")
            continue
        sha = getattr(getattr(s, "lfs", None), "sha256", None) if getattr(s, "lfs", None) else None
        if sha:
            h = hashlib.sha256()
            with open(f, "rb") as fh:
                for block in iter(lambda: fh.read(1 << 22), b""):
                    h.update(block)
            if h.hexdigest() != sha:
                bad.append(s.rfilename + " (sha256)")
    return bad


def install_async(model):
    if INSTALL.get("state") in ("checking", "downloading", "verifying"):
        return dict(INSTALL, ok=False)
    threading.Thread(target=install, args=(model,), daemon=True).start()
    return {"ok": True, "state": "checking", "model": model}


# ------------------------------------------------------------------ lazy loading
def is_oom(exc):
    t = repr(exc).lower()
    return "out of memory" in t or "cuda_error_out_of_memory" in t or ("cuda" in t and "alloc" in t)


def free_vram_gb():
    try:
        import torch
        if torch.cuda.is_available():
            return torch.cuda.mem_get_info()[0] / 2 ** 30
    except Exception:  # noqa: BLE001
        pass
    return None


def _empty_cache():
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass


class Models:
    """Loads WhisperModels on first use. The primary stays loaded; the secondary is unloaded after use unless
    keep="always", or keep="auto" and enough VRAM stays free (3 GB margin for summaries / other GPU work)."""

    def __init__(self, device, compute=None, keep="auto", factory=None):
        self.device = device
        self.compute = compute or ("float16" if device == "cuda" else "int8")
        self.keep = keep
        self.loaded = {}
        self.where = {}                    # model -> "cuda/float16" or "cpu/int8" (after a fallback)
        self.events = []                   # what went wrong while loading / decoding (shown in the trace)
        self._factory = factory            # tests pass a fake

    def _make(self, name, device, compute):
        if self._factory:
            return self._factory(name, device, compute)
        from faster_whisper import WhisperModel
        path = local_path(name)
        return WhisperModel(path or name, device=device, compute_type=compute,
                            cpu_threads=max(2, (os.cpu_count() or 4) - 2), local_files_only=bool(path))

    def get(self, name):
        if name in self.loaded:
            return self.loaded[name]
        try:
            m = self._make(name, self.device, self.compute)
            self.where[name] = f"{self.device}/{self.compute}"
        except Exception as exc:  # noqa: BLE001
            if self.device != "cuda":
                raise
            self.events.append(f"load {name} on cuda failed: {exc!r}"[:200])
            log(self.events[-1])
            if is_oom(exc) and len(self.loaded) > 0:
                self.unload_all(keep=self.primary_name())
                _empty_cache()
                try:
                    m = self._make(name, self.device, self.compute)
                    self.where[name] = f"{self.device}/{self.compute}"
                    self.loaded[name] = m
                    return m
                except Exception as exc2:  # noqa: BLE001
                    self.events.append(f"retry {name} on cuda failed: {exc2!r}"[:200])
            m = self._make(name, "cpu", "int8")          # CUDA missing / broken / full: slow but working
            self.where[name] = "cpu/int8"
        self.loaded[name] = m
        return m

    def primary_name(self):
        return next(iter(self.loaded), None)

    def release(self, name):
        """After a secondary pass: keep it or free its memory."""
        if name not in self.loaded or self.keep == "always":
            return
        if self.keep == "auto":
            free = free_vram_gb()
            if free is not None and free > 3.0:
                return
        self.loaded.pop(name, None)
        _empty_cache()

    def unload_all(self, keep=None):
        for k in [k for k in self.loaded if k != keep]:
            self.loaded.pop(k, None)
        _empty_cache()


def status():
    from home_analyze import home_config
    cfg = home_config()
    a = cfg.get("asr") or {}
    return {"installed": installed(tuple(dict.fromkeys([cfg.get("whisper_model") or PRIMARY, PRIMARY, SECONDARY,
                                                         a.get("secondary_model") or SECONDARY]))),
            "known": KNOWN, "install": {k: v for k, v in INSTALL.items() if k != "path"}}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--install")
    ap.add_argument("--verify")
    a = ap.parse_args()
    if a.install:
        print(json.dumps(install(a.install), ensure_ascii=False, indent=1))
    elif a.verify:
        p = local_path(a.verify)
        print(json.dumps({"path": p, "bad": verify_files(p, model=a.verify) if p else ["not installed"]}, ensure_ascii=False))
    else:
        print(json.dumps(installed(), indent=1))
