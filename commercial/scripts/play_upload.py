"""Upload a signed .aab to Google Play (Play Developer API v3) - no manual Play Console step.

  python play_upload.py <file.aab> [--track production] [--status draft|completed|inProgress]
                        [--fraction 0.2] [--notes "מה חדש"] [--key C:\\Users\\agmon\\keys\\play-publisher.json]

status: draft (default) = the release waits in Play Console for "Send for review"; completed = sent for review
and published to everyone once approved; inProgress = staged rollout to --fraction of users.

Key: a Google Cloud service-account JSON that was invited in Play Console (Users and permissions) with release
rights for app.shema.listener. Looked up in --key, then %SHEMA_PLAY_KEY%, then C:\\Users\\agmon\\keys\\play-publisher.json.
Only the standard library + cryptography (already installed) - nothing else to pip install.
"""
import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

PACKAGE = "app.shema.listener"
API = "https://androidpublisher.googleapis.com/androidpublisher/v3/applications/" + PACKAGE
UPLOAD = "https://androidpublisher.googleapis.com/upload/androidpublisher/v3/applications/" + PACKAGE
SCOPE = "https://www.googleapis.com/auth/androidpublisher"
DEFAULT_KEY = os.path.join(os.path.expanduser("~"), "keys", "play-publisher.json")


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def token(key_path):
    """service-account JWT -> OAuth access token"""
    k = json.load(open(key_path, encoding="utf-8"))
    now = int(time.time())
    head = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claim = _b64(json.dumps({"iss": k["client_email"], "scope": SCOPE, "aud": k["token_uri"],
                             "iat": now, "exp": now + 3600}).encode())
    pk = serialization.load_pem_private_key(k["private_key"].encode(), password=None)
    sig = _b64(pk.sign(f"{head}.{claim}".encode(), padding.PKCS1v15(), hashes.SHA256()))
    body = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                   "assertion": f"{head}.{claim}.{sig}"}).encode()
    return json.load(urllib.request.urlopen(urllib.request.Request(k["token_uri"], body), timeout=30))["access_token"], k["client_email"]


def call(tok, method, url, body=None, raw=None, ctype="application/json", timeout=60):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": "Bearer " + tok, "Content-Type": ctype})
    try:
        r = urllib.request.urlopen(req, timeout=timeout).read()
        return json.loads(r) if r else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {url.split(PACKAGE)[-1] or '/'} -> {e.code}: {e.read().decode(errors='replace')}") from None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("aab")
    ap.add_argument("--track", default="production")
    ap.add_argument("--status", default="draft", choices=["draft", "completed", "inProgress"])
    ap.add_argument("--fraction", type=float, default=0.2)
    ap.add_argument("--notes", default="")
    ap.add_argument("--key", default=os.environ.get("SHEMA_PLAY_KEY") or DEFAULT_KEY)
    ap.add_argument("--name", default="", help="release name; default: the version in the file name (shema-pro-v1.0.19.aab)")
    ap.add_argument("--existing", type=int, default=0, help="a versionCode already uploaded: only set the track (no upload)")
    a = ap.parse_args()
    # without a name Play keeps the previous draft's name (1.0.19 showed as "1.0.18")
    m = re.search(r"v(\d+(?:\.\d+)+)\.aab$", a.aab)
    name = a.name or (m.group(1) if m else "")
    if not os.path.exists(a.key):
        sys.exit(f"No service-account key at {a.key} (see the setup steps in play_console_upload_guide.md)")

    tok, who = token(a.key)
    print(f"Signed in as {who}")
    edit = call(tok, "POST", API + "/edits", {})["id"]
    try:
        if a.existing:
            vc = a.existing
        else:
            size = os.path.getsize(a.aab) / 1e6
            print(f"Uploading {os.path.basename(a.aab)} ({size:.1f} MB)...")
            vc = call(tok, "POST", UPLOAD + f"/edits/{edit}/bundles?uploadType=media",
                      raw=open(a.aab, "rb").read(), ctype="application/octet-stream", timeout=900)["versionCode"]
            print(f"Uploaded: versionCode {vc}")
        rel = {"versionCodes": [str(vc)], "status": a.status}
        if name:
            rel["name"] = name
        if a.status == "inProgress":
            rel["userFraction"] = a.fraction
        if a.notes.strip():
            rel["releaseNotes"] = [{"language": "iw-IL", "text": a.notes.strip()[:500]}]
        call(tok, "PUT", API + f"/edits/{edit}/tracks/{a.track}", {"track": a.track, "releases": [rel]})
        try:
            call(tok, "POST", API + f"/edits/{edit}:commit")
            sent = a.status != "draft"
        except RuntimeError as e:
            # apps whose changes must be sent by hand (e.g. listing changes already waiting): save, don't send
            if "changesNotSentForReview" not in str(e):
                raise
            call(tok, "POST", API + f"/edits/{edit}:commit?changesNotSentForReview=true")
            sent = False
    except Exception:
        try:
            call(tok, "DELETE", API + f"/edits/{edit}")
        except Exception:  # noqa: BLE001
            pass
        raise
    print(f"Done: {a.track} track, versionCode {vc}, status {a.status}.")
    print("Sent to Google for review." if sent else
          "Saved, NOT sent yet: Play Console -> Publishing overview -> Send changes for review.")


if __name__ == "__main__":
    main()
