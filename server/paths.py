# -*- coding: utf-8 -*-
r"""paths.py -- where Shema keeps its things. Nothing personal lives next to the code.

    %LOCALAPPDATA%\Shema\data     recordings, database, config.json (SHEMA_DATA / HOME_DATA override it)
    %LOCALAPPDATA%\Shema\models   speech / voice / sound models downloaded by the installer (SHEMA_MODELS)
    %LOCALAPPDATA%\Shema\app.apk  the phone app served at /home/app.apk
"""
import os
from pathlib import Path

CODE = Path(__file__).resolve().parent
APP = Path(os.getenv("SHEMA_HOME") or (Path(os.getenv("LOCALAPPDATA") or Path.home()) / "Shema"))
DATA = Path(os.getenv("SHEMA_DATA") or os.getenv("HOME_DATA") or (APP / "data"))
MODELS = Path(os.getenv("SHEMA_MODELS") or (APP / "models"))
VOICE = DATA / "voice"
CONFIG = DATA / "config.json"
APK = APP / "app.apk"


def device():
    """'cuda' when torch sees an NVIDIA card, else 'cpu' (config.json "device" overrides)."""
    try:
        import json
        d = json.load(open(CONFIG, encoding="utf-8")).get("device")
        if d in ("cuda", "cpu"):
            return d
    except (OSError, ValueError):
        pass
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:  # noqa: BLE001
        return "cpu"
