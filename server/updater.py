# -*- coding: utf-8 -*-
r"""updater.py -- "a new version is available" + the one-click update on the PC screen (2026-10-20).

Checks the public GitHub release list of agmonp/shema (no data is sent, only the request itself) at most every
CHECK_H hours while the screen is open; config.json "update_check": false turns it off. The update itself:
download the release zip, unpack it under data\updates, check it is a Shema release of that version, then start
install\update.ps1 from it, detached: it stops this server, copies the program files (with a backup and roll back on
any failure) and starts the new version. Only an installed copy (%LOCALAPPDATA%\Shema\app) updates itself.
"""
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

import paths

VERSION = ((paths.CODE / "VERSION").read_text(encoding="utf-8").strip() if (paths.CODE / "VERSION").exists() else "0.0.0")
REPO = "agmonp/shema"
API = os.getenv("SHEMA_UPDATE_API") or f"https://api.github.com/repos/{REPO}/releases/latest"
CHECK_H = 6
MAX_ZIP = 200 * 1024 * 1024
UPDATES = paths.DATA / "updates"
RESULT = paths.DATA / "update_result.json"

_lock = threading.Lock()
_st = {"checked": 0.0, "latest": None, "notes": None, "zip": None, "page": None, "error": None,
       "state": "idle", "msg": None}


def vt(v):
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)$", str(v or "").strip())
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def installed():
    """only the installer's copy updates itself (a developer checkout / another folder never does)"""
    try:
        return paths.CODE.resolve() == (paths.APP / "app").resolve()
    except OSError:
        return False


def check(enabled=True, force=False):
    """the latest public release (cached CHECK_H hours)"""
    if not enabled:
        return
    with _lock:
        if not force and time.time() - _st["checked"] < CHECK_H * 3600:
            return
        _st["checked"] = time.time()
    try:
        rq = urllib.request.Request(API, headers={"User-Agent": "shema-updater", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(rq, timeout=8) as r:
            j = json.loads(r.read().decode("utf-8-sig"))
        tag = j.get("tag_name") or ""
        asset = next((a for a in j.get("assets") or [] if re.match(r"^shema-windows-v[\d.]+\.zip$", a.get("name") or "")), None)
        with _lock:
            _st.update(latest=tag.lstrip("v") if vt(tag) > (0, 0, 0) else None, notes=(j.get("body") or "")[:3000],
                       zip=asset.get("browser_download_url") if asset else None, page=j.get("html_url"), error=None)
    except Exception as exc:  # noqa: BLE001
        with _lock:
            _st["error"] = f"{type(exc).__name__}"


def last_result():
    try:
        return json.loads(RESULT.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def status(enabled=True):
    check(enabled)
    with _lock:
        s = dict(_st)
    newer = bool(s["latest"]) and vt(s["latest"]) > vt(VERSION)
    return {"current": VERSION, "latest": s["latest"], "newer": newer, "notes": s["notes"] if newer else None,
            "page": s["page"], "can_update": installed() and bool(s["zip"]), "installed": installed(),
            "state": s["state"], "msg": s["msg"], "enabled": enabled, "error": s["error"], "last": last_result()}


def _set(state, msg=None):
    with _lock:
        _st.update(state=state, msg=msg)


def apply(port, enabled=True):
    """the user pressed "update": download + unpack + start update.ps1 (which restarts this server)"""
    s = status(enabled)
    if not s["installed"]:
        return {"ok": False, "msg": "עדכון בלחיצה עובד רק בהתקנה הרגילה. אפשר להוריד את הגרסה ולהריץ Install.bat."}
    if not s["newer"] or not s["can_update"]:
        return {"ok": False, "msg": "אין גרסה חדשה להתקנה"}
    if s["state"] in ("downloading", "installing"):
        return {"ok": True, "state": s["state"]}
    _set("downloading", "מוריד את הגרסה החדשה…")
    threading.Thread(target=_run, args=(s["latest"], _st["zip"], port), daemon=True).start()
    return {"ok": True, "state": "downloading"}


def _run(version, url, port):
    try:
        UPDATES.mkdir(parents=True, exist_ok=True)
        z = UPDATES / f"shema-windows-v{version}.zip"
        rq = urllib.request.Request(url, headers={"User-Agent": "shema-updater"})
        with urllib.request.urlopen(rq, timeout=60) as r, open(z, "wb") as f:
            n = 0
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                n += len(b)
                if n > MAX_ZIP:
                    raise ValueError("too big")
                f.write(b)
        dst = UPDATES / f"v{version}"
        shutil.rmtree(dst, ignore_errors=True)
        with zipfile.ZipFile(z) as zf:
            for m in zf.namelist():                                # no path outside the folder
                if m.startswith(("/", "\\")) or ".." in Path(m).parts or ":" in m:
                    raise ValueError("bad zip")
            zf.extractall(dst)
        got = (dst / "server" / "VERSION").read_text(encoding="utf-8").strip() if (dst / "server" / "VERSION").exists() else ""
        upd = dst / "install" / "update.ps1"
        if got != version or not (dst / "server" / "home_listener.py").exists() or not upd.exists():
            raise ValueError("not a Shema release of that version")
        RESULT.unlink(missing_ok=True)
        _set("installing", "מתקין… השרת יחזור לבד בעוד דקה-שתיים")
        # update.ps1 stops this server, so it must not be our child: a child of the "Shema" task dies with it, and a
        # DETACHED powershell does not start at all (measured). A one-time task of the user runs it on its own.
        q = lambda p: str(p).replace("'", "''")                    # noqa: E731  (PowerShell single quotes)
        arg = f'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{upd}" -Src "{dst}" -ShemaHome "{paths.APP}" -Port {int(port)}'
        launch = UPDATES / "start_update.ps1"
        launch.write_text(
            f"$a = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '{q(arg)}' -WorkingDirectory '{q(dst)}'\n"
            "$p = New-ScheduledTaskPrincipal -UserId \"$env:USERDOMAIN\\$env:USERNAME\" -LogonType Interactive -RunLevel Limited\n"
            "$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1)\n"
            "Register-ScheduledTask -TaskName 'ShemaUpdate' -Action $a -Principal $p -Settings $s -Force -ErrorAction Stop | Out-Null\n"
            "Start-ScheduledTask -TaskName 'ShemaUpdate' -ErrorAction Stop\n", encoding="utf-8-sig")
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(launch)],
                           capture_output=True, text=True, timeout=60, creationflags=0x08000000)
        if r.returncode:
            raise RuntimeError("task: " + (r.stderr or r.stdout)[-300:])
    except Exception as exc:  # noqa: BLE001
        _set("failed", f"העדכון נכשל ({type(exc).__name__}). אפשר לנסות שוב, או להוריד ולהריץ Install.bat.")
