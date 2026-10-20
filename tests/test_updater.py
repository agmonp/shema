"""2026-10-20: the PC's update button: which release is newer, only an installed copy updates itself, a release
zip is checked before anything runs."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

_TMP = tempfile.mkdtemp(prefix="shema_upd_")
os.environ["SHEMA_DATA"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import updater as U      # noqa: E402


def fake_release(tag, assets=("shema-windows-v{v}.zip",)):
    v = tag.lstrip("v")
    body = json.dumps({"tag_name": tag, "body": "מה חדש", "html_url": "https://x/" + tag,
                       "assets": [{"name": a.format(v=v), "browser_download_url": "https://x/" + a.format(v=v)} for a in assets]})
    return mock.MagicMock(__enter__=lambda s: io.BytesIO(body.encode()), __exit__=lambda *a: False)


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        U._st.update(checked=0.0, latest=None, zip=None, state="idle", msg=None, error=None)

    def test_version_file_is_a_version(self):
        self.assertRegex(U.VERSION, r"^\d+\.\d+\.\d+$")
        self.assertGreater(U.vt("1.0.12"), U.vt("1.0.9"))      # numbers, not text
        self.assertEqual(U.vt("garbage"), (0, 0, 0))

    def test_newer_only_when_really_newer_and_a_dev_checkout_never_updates(self):
        with mock.patch.object(U, "VERSION", "1.0.12"), mock.patch("urllib.request.urlopen", return_value=fake_release("v1.0.13")):
            s = U.status()
        self.assertTrue(s["newer"]); self.assertEqual(s["latest"], "1.0.13")
        self.assertFalse(s["installed"]); self.assertFalse(s["can_update"])          # this test runs from the repo
        self.assertFalse(U.apply(8770)["ok"])
        U._st["checked"] = 0
        with mock.patch.object(U, "VERSION", "1.0.12"), mock.patch("urllib.request.urlopen", return_value=fake_release("v1.0.12")):
            self.assertFalse(U.status()["newer"])

    def test_off_means_no_request(self):
        with mock.patch("urllib.request.urlopen") as op:
            s = U.status(enabled=False)
        op.assert_not_called()
        self.assertFalse(s["newer"])

    def test_zip_with_a_path_outside_is_refused(self):
        z = Path(_TMP) / "evil.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("../outside.txt", "x")
        body = z.read_bytes()
        resp = mock.MagicMock(__enter__=lambda s: io.BytesIO(body), __exit__=lambda *a: False)
        with mock.patch("urllib.request.urlopen", return_value=resp), mock.patch("subprocess.run") as run:
            U._run("1.0.99", "https://x/z.zip", 8770)
        run.assert_not_called()
        self.assertEqual(U._st["state"], "failed")
        self.assertFalse((Path(_TMP) / "outside.txt").exists())


if __name__ == "__main__":
    unittest.main()
