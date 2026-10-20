"""Owner dashboard for שמע Pro: free Pro gift codes (who has it, until when) and what is waiting to go out
to GitHub / Google Play. Runs on this PC only (127.0.0.1), standard library only.

Gift codes are signed by ../scripts/gift.ps1 with the private key in ~/keys (never in the repository).
The gift list (names, phones) lives in ~/keys/shema-gifts.json, also outside the repository.
Open with Open-Dashboard.bat, or:  pythonw server.py --open
"""
import json, os, re, subprocess, sys, threading, time, uuid, webbrowser, zipfile
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8795
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent                      # the shema repository
COMM = ROOT / "commercial"
GRADLE = COMM / "android" / "app" / "build.gradle.kts"
GIFT_KT = COMM / "android" / "app" / "src" / "main" / "java" / "com" / "shema" / "app" / "Gift.kt"
GIFT_PS1 = COMM / "scripts" / "gift.ps1"
DIST = COMM / "dist"
KEYS = Path.home() / "keys"
GIFTS = KEYS / "shema-gifts.json"
STATE = KEYS / "shema-dashboard.json"
BUILD_LOG = Path(os.environ.get("TEMP", str(HERE))) / "shema-dashboard-build.log"
EPOCH = date(1970, 1, 1)
NOWIN = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
lock = threading.Lock()
build = {"proc": None, "what": ""}


# ------------------------------------------------------------------ storage
def load(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def save(p, data):
    KEYS.mkdir(exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def state():
    # 1.0.6 (103) was the last one uploaded to Play when this dashboard was made
    return load(STATE, {"play": {"code": 103, "name": "1.0.6", "date": "2026-10-12", "commit": ""}})


def run(*cmd, cwd=ROOT, timeout=60):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=timeout, creationflags=NOWIN)
    return r.returncode, r.stdout.decode("utf-8", "replace").rstrip(), r.stderr.decode("utf-8", "replace").strip()


def git(*a):
    return run("git", "-C", str(ROOT), *a)[1]


# ------------------------------------------------------------------ gifts
PHONE = re.compile(r"^[0-9A-Z]{4}-[0-9A-Z]{4}$")


def norm_phone(s):
    s = re.sub(r"[^0-9A-Za-z]", "", s or "").upper().replace("O", "0").replace("I", "1").replace("L", "1")
    return f"{s[:4]}-{s[4:]}" if len(s) == 8 else ""


def sign(phone, name, until_day):
    code, out, err = run("powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(GIFT_PS1),
                         "-Phone", phone, "-Name", name, "-UntilDay", str(until_day), "-Json", timeout=60)
    m = re.search(r'\{"code":"(SHEMA-[0-9A-Z]+)","until":(\d+)\}', out)
    if not m:
        raise RuntimeError(err or out or "gift.ps1 failed")
    return m.group(1)


def revoked_phones(gifts):
    """phones whose latest gift is revoked"""
    latest = {}
    for g in sorted(gifts, key=lambda g: g["created"]):
        latest[g["phone"]] = g
    return sorted(p for p, g in latest.items() if g.get("revoked"))


def write_revoked(gifts):
    phones = revoked_phones(gifts)
    t = GIFT_KT.read_text(encoding="utf-8")
    inner = ", ".join(f'"{p}"' for p in phones)
    new = re.sub(r"private val REVOKED = setOf<String>\([^)]*\)  // dashboard:revoked",
                 f"private val REVOKED = setOf<String>({inner})  // dashboard:revoked", t)
    if new != t:
        GIFT_KT.write_text(new, encoding="utf-8", newline="\n")


def app_revoked():
    m = re.search(r"setOf<String>\(([^)]*)\)  // dashboard:revoked", GIFT_KT.read_text(encoding="utf-8"))
    return re.findall(r'"([^"]+)"', m.group(1)) if m else []


def new_gift(b):
    phone = norm_phone(b.get("phone"))
    if not PHONE.match(phone):
        raise ValueError("קוד הטלפון הוא 8 תווים, כמו SG8P-B0XR")
    name = (b.get("name") or "").strip()
    if not name:
        raise ValueError("חסר שם")
    if len(name.encode("utf-8")) > 60:
        raise ValueError("השם ארוך מדי")
    until = b.get("until") or ""                 # yyyy-mm-dd, empty = forever
    until_day = 0
    if until:
        d = date.fromisoformat(until)
        if d < date.today():
            raise ValueError("התאריך כבר עבר")
        until_day = (d - EPOCH).days
    code = sign(phone, name, until_day)
    with lock:
        gifts = load(GIFTS, [])
        g = {"id": uuid.uuid4().hex[:10], "phone": phone, "name": name,
             "group": (b.get("group") or "").strip(), "note": (b.get("note") or "").strip(),
             "created": datetime.now().isoformat(timespec="seconds"), "until": until, "code": code,
             "revoked": False}
        for old in gifts:                        # a new code for the same phone replaces the old one
            if old["phone"] == phone and not old.get("replaced_by"):
                old["replaced_by"] = g["id"]
        gifts.append(g)
        save(GIFTS, gifts)
        write_revoked(gifts)
    return g


def edit_gift(gid, b):
    with lock:
        gifts = load(GIFTS, [])
        g = next((x for x in gifts if x["id"] == gid), None)
        if not g:
            raise ValueError("לא נמצא")
        act = b.get("action")
        if act == "revoke":
            g["revoked"] = True; g["revoked_at"] = datetime.now().isoformat(timespec="seconds")
        elif act == "unrevoke":
            g["revoked"] = False; g.pop("revoked_at", None)
        elif act == "note":
            g["note"] = (b.get("note") or "").strip(); g["group"] = (b.get("group") or "").strip()
        elif act == "delete":
            gifts.remove(g)
        save(GIFTS, gifts)
        write_revoked(gifts)
    return {"ok": True}


# ------------------------------------------------------------------ versions
def gradle_version():
    t = GRADLE.read_text(encoding="utf-8")
    return int(re.search(r"versionCode = (\d+)", t).group(1)), re.search(r'versionName = "([^"]+)"', t).group(1)


def area(path):
    if path.startswith("commercial/android/"):
        return "app"
    if path.startswith(("server/", "install/")) or path in ("requirements.txt",):
        return "pc"
    return "other"


def release_info():
    st = state()
    code, name = gradle_version()
    files = []
    for line in git("status", "--porcelain").splitlines():
        p = line[3:].strip().strip('"')
        if " -> " in p:
            p = p.split(" -> ")[1]
        files.append({"path": p, "state": line[:2].strip(), "area": area(p)})
    try:
        run("git", "-C", str(ROOT), "fetch", "--tags", "-q", timeout=20)
    except Exception:
        pass
    unpushed = [l for l in git("log", "--oneline", "@{u}..HEAD").splitlines() if l]
    tags = [t for t in git("tag", "--sort=-v:refname").splitlines() if re.match(r"^v\d+\.\d+\.\d+$", t)]
    last_tag = tags[0] if tags else ""
    pc_commits = [l for l in git("log", "--oneline", f"{last_tag}..HEAD", "--", "server", "install", "requirements.txt").splitlines() if l] if last_tag else []
    play = st["play"]
    app_commits = []
    if play.get("commit"):
        app_commits = [l for l in git("log", "--oneline", f"{play['commit']}..HEAD", "--", "commercial/android").splitlines() if l]
    aabs = sorted(({"name": f.name, "size": f.stat().st_size, "time": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="minutes")}
                   for f in DIST.glob("shema-pro-v*.aab")), key=lambda x: x["time"], reverse=True)
    zips = sorted((f.name for f in DIST.glob("shema-windows-v*.zip")), reverse=True)
    nxt = last_tag.lstrip("v").split(".") if last_tag else ["1", "0", "0"]
    next_pc = f"{nxt[0]}.{nxt[1]}.{int(nxt[2]) + 1}"
    proc = build["proc"]
    return {
        "root": str(ROOT), "files": files, "unpushed": unpushed, "head": git("rev-parse", "--short", "HEAD"),
        "app": {"code": code, "name": name, "play": play, "commits_since_play": app_commits,
                "aabs": aabs[:5], "aab_exists": (DIST / f"shema-pro-v{name}.aab").exists(), "aab_ready": aab_fresh(name),
                "revoked_in_app": app_revoked(), "revoked_wanted": revoked_phones(load(GIFTS, []))},
        "pc": {"last_tag": last_tag, "commits_since": pc_commits, "next": next_pc, "zips": zips[:3]},
        "build": {"running": bool(proc and proc.poll() is None), "what": build["what"],
                  "exit": (proc.poll() if proc else None), "log": tail(BUILD_LOG)},
    }


def aab_fresh(name):
    """the AAB for this version exists and was built after the last change to the app's code"""
    f = DIST / f"shema-pro-v{name}.aab"
    if not f.exists():
        return False
    src = COMM / "android" / "app"
    newest = max((x.stat().st_mtime for x in (src / "src").rglob("*") if x.is_file()), default=0)
    return f.stat().st_mtime >= max(newest, GRADLE.stat().st_mtime)


def tail(p, n=25):
    try:
        return "\n".join(p.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
    except Exception:
        return ""


def bump():
    code, name = gradle_version()
    a = name.split(".")
    nn = f"{a[0]}.{a[1]}.{int(a[2]) + 1}"
    t = GRADLE.read_text(encoding="utf-8")
    t = re.sub(r"versionCode = \d+", f"versionCode = {code + 1}", t)
    t = re.sub(r'versionName = "[^"]+"', f'versionName = "{nn}"', t)
    GRADLE.write_text(t, encoding="utf-8", newline="\n")
    return {"code": code + 1, "name": nn}


def start_build(what, version=""):
    if build["proc"] and build["proc"].poll() is None:
        raise ValueError("בנייה אחרת עדיין רצה")
    log = open(BUILD_LOG, "w", encoding="utf-8")
    if what == "aab":
        code, name = gradle_version()
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(COMM / "scripts" / "build_aab.ps1"),
               "-VersionName", name, "-VersionCode", str(code)]
        build["proc"] = subprocess.Popen(cmd, cwd=str(COMM), stdout=log, stderr=subprocess.STDOUT, creationflags=NOWIN)
        build["what"] = f"אפליקציה {name}"
    elif what == "zip":
        if not re.match(r"^\d+\.\d+\.\d+$", version or ""):
            raise ValueError("גרסה בצורה 1.0.9")
        build["proc"] = subprocess.Popen([sys.executable, str(HERE / "server.py"), "--zip", version], cwd=str(ROOT),
                                         stdout=log, stderr=subprocess.STDOUT, creationflags=NOWIN)
        build["what"] = f"תוכנת מחשב {version}"
    return {"ok": True}


def make_zip(version):
    """The Windows server zip from the committed files (forward slashes; Compress-Archive on PS 5.1 writes backslashes)."""
    have = (ROOT / "server" / "VERSION").read_text(encoding="utf-8").strip() if (ROOT / "server" / "VERSION").exists() else ""
    if have != version:                               # the update button compares it with the release tag
        raise SystemExit(f"server/VERSION is {have!r}, not {version!r}: set it, commit, then build")
    files = [f for f in git("ls-files", "server", "install", "requirements.txt", "README.md", "LICENSE").splitlines() if f]
    DIST.mkdir(exist_ok=True)
    out = DIST / f"shema-windows-v{version}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(ROOT / f, f)
    print(f"Created {out} ({out.stat().st_size} bytes, {len(files)} files)")


def mark_uploaded():
    code, name = gradle_version()
    st = state()
    st["play"] = {"code": code, "name": name, "date": date.today().isoformat(), "commit": git("rev-parse", "HEAD")}
    save(STATE, st)
    return st["play"]


# ------------------------------------------------------------------ http
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, obj, status=200, ctype="application/json; charset=utf-8"):
        body = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        try:
            if self.path in ("/", "/index.html"):
                return self.send((HERE / "index.html").read_bytes(), ctype="text/html; charset=utf-8")
            if self.path == "/api/gifts":
                return self.send({"gifts": load(GIFTS, []), "key": (KEYS / "shema-gift-key.json").exists(),
                                  "today": date.today().isoformat()})
            if self.path == "/api/release":
                return self.send(release_info())
            if self.path == "/api/gifts.csv":
                rows = ["date,name,group,phone,until,status,note"]
                for g in load(GIFTS, []):
                    st = "revoked" if g.get("revoked") else "replaced" if g.get("replaced_by") else "active"
                    rows.append(",".join('"' + str(v).replace('"', "'") + '"' for v in
                                         (g["created"][:10], g["name"], g.get("group", ""), g["phone"], g["until"] or "forever", st, g.get("note", ""))))
                return self.send(("﻿" + "\n".join(rows)).encode("utf-8"), ctype="text/csv; charset=utf-8")
            self.send({"error": "not found"}, 404)
        except Exception as e:
            self.send({"error": str(e)}, 500)

    def do_POST(self):
        if self.headers.get("Origin") not in (None, f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
            return self.send({"error": "forbidden"}, 403)
        try:
            b = self.body()
            if self.path == "/api/gifts":
                return self.send(new_gift(b))
            m = re.match(r"^/api/gifts/([0-9a-f]+)$", self.path)
            if m:
                return self.send(edit_gift(m.group(1), b))
            if self.path == "/api/release/bump":
                return self.send(bump())
            if self.path == "/api/release/build":
                return self.send(start_build(b.get("what"), b.get("version", "")))
            if self.path == "/api/release/uploaded":
                return self.send(mark_uploaded())
            if self.path == "/api/open":
                target = {"dist": str(DIST), "play": "https://play.google.com/console",
                          "github": "https://github.com/agmonp/shema/releases"}.get(b.get("what"))
                if target:
                    os.startfile(target)
                return self.send({"ok": bool(target)})
            self.send({"error": "not found"}, 404)
        except ValueError as e:
            self.send({"error": str(e)}, 400)
        except Exception as e:
            self.send({"error": str(e)}, 500)


def main():
    if "--zip" in sys.argv:
        return make_zip(sys.argv[sys.argv.index("--zip") + 1])
    url = f"http://127.0.0.1:{PORT}/"
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    except OSError:                                # already running: just open it
        if "--open" in sys.argv:
            webbrowser.open(url)
        return
    if "--open" in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    srv.serve_forever()


if __name__ == "__main__":
    main()
