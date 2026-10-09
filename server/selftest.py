# -*- coding: utf-8 -*-
r"""selftest.py -- can this PC load what Shema needs? (called by the installer; prints one JSON line)

    python -X utf8 selftest.py              # import check: torch, faster_whisper, sherpa_onnx (+ CUDA)
    python -X utf8 selftest.py --prefetch   # also download the speech / emotion models now (else on the first recording)

Smart App Control / WDAC blocks show up here as "An Application Control policy has blocked this file".
"""
import json, sys, traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def check(name):
    try:
        __import__(name)
        return None
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"[:400]


def main():
    out = {"python": sys.version.split()[0], "errors": {}}
    for m in ("torch", "faster_whisper", "sherpa_onnx", "ctranslate2", "funasr", "parselmouth", "librosa", "demucs"):
        e = check(m)
        if e:
            out["errors"][m] = e
    out["blocked_by_policy"] = any("Application Control" in e or "4551" in e for e in out["errors"].values())
    try:
        import torch
        out["cuda"] = bool(torch.cuda.is_available())
        out["gpu"] = torch.cuda.get_device_name(0) if out["cuda"] else None
    except Exception:  # noqa: BLE001
        out["cuda"] = False
    if "--prefetch" in sys.argv and not out["errors"]:
        out["prefetch"] = prefetch()
    print("SELFTEST " + json.dumps(out, ensure_ascii=False))


def prefetch():
    """Download the Hugging Face models once, so the first recording is not slow."""
    import paths
    done, cfg = {}, {}
    try:
        cfg = json.load(open(paths.CONFIG, encoding="utf-8"))
    except (OSError, ValueError):
        pass
    from huggingface_hub import snapshot_download
    import home_analyze as HA
    names = [cfg.get("whisper_model") or HA.WHISPER_MODEL, HA.EMO_MODEL, HA.DIM_MODEL]
    if cfg.get("clap", paths.device() == "cuda"):
        import home_sounds
        names.append(home_sounds.CLAP_MODEL)
    for n in names:
        try:
            snapshot_download(n)
            done[n] = "ok"
        except Exception as exc:  # noqa: BLE001
            done[n] = repr(exc)[:200]
    try:
        from demucs.pretrained import get_model
        get_model("htdemucs")
        done["htdemucs"] = "ok"
    except Exception as exc:  # noqa: BLE001
        done["htdemucs"] = repr(exc)[:200]
    return done


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        print("SELFTEST " + json.dumps({"fatal": traceback.format_exc()[-800:]}))
