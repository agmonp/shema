# -*- coding: utf-8 -*-
r"""setup_config.py -- create or update config.json (called by install\install.ps1; safe to run again).

    python -X utf8 setup_config.py --device cuda --compute float16 --summary gemma3:12b [--owner NAME] [--remote IP]

Keeps what already exists (access code, owner, the speech model asr_update chose, the user's own settings) and
only fills in / refreshes the hardware choices.
"""
import argparse, json, secrets, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import CONFIG  # noqa: E402

DEFAULT_MODEL = "ivrit-ai/whisper-large-v3-turbo-ct2"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", choices=["cuda", "cpu"], required=True)
    ap.add_argument("--compute", required=True, help="float16 (NVIDIA) / int8 (CPU)")
    ap.add_argument("--summary", required=True, help="Ollama model for summaries")
    ap.add_argument("--owner", default="", help="the owner's name (the main voice)")
    ap.add_argument("--remote", default="", help="this PC's Tailscale IPv4, if any")
    ap.add_argument("--show", action="store_true", help="print owner_name and exit")
    a = ap.parse_args()
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    try:
        cfg = json.load(open(CONFIG, encoding="utf-8-sig"))
    except (OSError, ValueError):
        cfg = {}
    cfg.setdefault("token", secrets.token_urlsafe(24))
    cfg.setdefault("audio_policy", "archive")
    cfg.setdefault("audio_days", 14)
    cfg.setdefault("paused_until", None)
    cfg.setdefault("owner", "owner")
    cfg.setdefault("whisper_model", DEFAULT_MODEL)
    cfg["device"] = a.device
    cfg["asr_compute"] = a.compute
    cfg["summary_model"] = a.summary
    cfg.setdefault("clap", a.device == "cuda")         # the open-set sound labels are slow without a GPU
    cfg.setdefault("song_lookup", False)               # online (Shazam): off unless the user turns it on
    if a.owner.strip():
        cfg["owner_name"] = a.owner.strip()[:60]
    if a.remote.strip():
        cfg["remote"] = a.remote.strip()
    tmp = CONFIG.with_suffix(".tmp")
    json.dump(cfg, open(tmp, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    tmp.replace(CONFIG)
    print("config:", CONFIG)


if __name__ == "__main__":
    main()
