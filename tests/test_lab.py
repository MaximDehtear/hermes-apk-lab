import contextlib
import hashlib
import http.client
import io
import json
import os
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from apk_lab import core, pipeline, server


def fake_apk(payload=b"test"):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as z:
        z.writestr("AndroidManifest.xml", b"test manifest")
        z.writestr("classes.dex", payload)
    return data.getvalue()


class LabTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("APK_LAB_WORKSPACE")
        os.environ["APK_LAB_WORKSPACE"] = self.temp.name
        self.job = core.create_job("Investigate a setting")
        self.jid = self.job["id"]
        self.token = core.issue_token(self.jid)
        self.http = server.LabServer(("127.0.0.1", 0))
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        if self.old is None:
            os.environ.pop("APK_LAB_WORKSPACE", None)
        else:
            os.environ["APK_LAB_WORKSPACE"] = self.old
        self.temp.cleanup()

    def request(self, action, method="GET", body=None, headers=None, token=True):
        conn = http.client.HTTPConnection("127.0.0.1", self.http.server_address[1], timeout=5)
        hdr = {"Authorization": "Bearer " + self.token} if token else {}
        hdr.update(headers or {})
        if isinstance(body, dict):
            body = json.dumps(body).encode()
        conn.request(method, "/api/" + self.jid + "/" + action, body, hdr)
        r = conn.getresponse()
        code, response_headers, data = r.status, dict(r.getheaders()), r.read()
        conn.close()
        return code, response_headers, data

    def upload(self, data):
        code, _, body = self.request("upload", "POST", {"name": "test.apk", "size": len(data), "fingerprint": "same"})
        self.assertEqual(code, 200)
        upload = json.loads(body)
        code, _, _ = self.request("chunk", "PUT", data, {"X-Upload-ID": upload["id"], "X-Upload-Offset": "0"})
        self.assertEqual(code, 200)
        return self.request("complete", "POST", {"id": upload["id"]})

    def test_authorization_and_rotation(self):
        self.assertEqual(self.request("status", token=False)[0], 403)
        self.assertEqual(self.request("status")[0], 200)
        core.issue_token(self.jid)
        self.assertEqual(self.request("status")[0], 403)

    def test_resumable_upload_and_idempotent_completion(self):
        data = fake_apk(b"x" * 100000)
        metadata = {"name": "test.apk", "size": len(data), "fingerprint": "same"}
        upload = json.loads(self.request("upload", "POST", metadata)[2])
        headers = {"X-Upload-ID": upload["id"], "X-Upload-Offset": "0"}
        self.assertEqual(self.request("chunk", "PUT", data[:12345], headers)[0], 200)
        self.assertEqual(self.request("complete", "POST", {"id": upload["id"]})[0], 400)
        self.assertEqual(self.request("chunk", "PUT", data[:1], headers)[0], 400)
        resume = json.loads(self.request("upload", "POST", metadata)[2])
        self.assertEqual(resume["offset"], 12345)
        headers["X-Upload-Offset"] = "12345"
        self.assertEqual(self.request("chunk", "PUT", data[12345:], headers)[0], 200)
        for _ in range(2):
            self.assertEqual(self.request("complete", "POST", {"id": upload["id"]})[0], 200)
        job = core.get_job(self.jid)
        self.assertEqual(job["phase"], "ready")
        self.assertEqual(job["input"]["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(self.request("chunk", "PUT", b"x", headers)[0], 400)

    def test_upload_limits_cross_origin_and_file_conflict(self):
        limit = core.config()["max_upload_bytes"]
        self.assertEqual(self.request("upload", "POST", {"name": "x.apk", "size": limit + 1})[0], 400)
        self.assertEqual(self.request("upload", "POST", {"name": "x.apk", "size": 100})[0], 200)
        self.assertEqual(self.request("upload", "POST", {"name": "y.apk", "size": 100})[0], 400)
        self.assertEqual(self.request("status", headers={"Origin": "https://attacker.invalid"})[0], 403)

    def test_archive_traversal_rejected(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            z.writestr("AndroidManifest.xml", "x")
            z.writestr("../escape", "x")
        self.assertEqual(self.upload(buffer.getvalue())[0], 400)
        self.assertIsNone(core.get_job(self.jid)["input"])

    def test_artifacts_cookie_range_and_path_boundary(self):
        path = core.job_dir(self.jid) / "analysis" / "REPORT.md"
        path.write_text("0123456789" * 50)
        item = core.publish(self.jid, path)
        _, headers, _ = self.request("auth", "POST")
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        code, hdr, data = self.request("download/" + item["id"], headers={"Cookie": cookie, "Range": "bytes=10-19"}, token=False)
        self.assertEqual(code, 206)
        self.assertEqual(data, b"0123456789")
        self.assertEqual(hdr["Content-Range"], "bytes 10-19/500")
        self.assertEqual(self.request("preview/" + item["id"])[0], 400)
        outside = Path(self.temp.name) / "secret.txt"
        outside.write_text("private")
        with self.assertRaises(ValueError):
            core.publish(self.jid, outside)
        linked = path.with_name("secret.txt")
        linked.symlink_to(outside)
        with self.assertRaises(ValueError):
            core.publish(self.jid, linked)

    def test_screenshot_preview_requires_auth_and_preserves_png(self):
        from test_device import PNG
        path = core.job_dir(self.jid) / "tests" / "before.png"
        path.write_bytes(PNG)
        artifact = core.publish(self.jid, path, "Before patch")
        action = "preview/" + artifact["id"]
        self.assertEqual(self.request(action, token=False)[0], 403)
        code, headers, body = self.request(action)
        self.assertEqual(code, 200)
        self.assertEqual(headers["Content-Type"], "image/png")
        self.assertEqual(headers["Content-Disposition"], "inline")
        self.assertEqual(body, PNG)

    def test_direct_public_url_and_invalid_hosts(self):
        self.assertEqual(server.validate_base_url("http://apk.example:9099/"), "http://apk.example:9099")
        for url in ["http://0.0.0.0:9099", "https://example/path", "https://user:secret@example", "ftp://example", "http://example:bad"]:
            with self.assertRaises(ValueError):
                server.validate_base_url(url)
        state = {"public_url": "http://apk.example:9099", "configured_public_url": "http://apk.example:9099",
                 "bind": "0.0.0.0", "port": 9099}
        with patch("apk_lab.server.start_server", return_value=state):
            result = server.link(self.jid)
        self.assertTrue(result["url"].startswith("http://apk.example:9099/#job="))
        self.assertTrue(result["public_address_configured"])
        self.assertFalse(result["internet_reachability_verified"])

    def test_concurrent_updates_and_readable_snapshot(self):
        threads = [threading.Thread(target=core.update_job, args=(self.jid,), kwargs={"field" + str(i): i}) for i in range(12)]
        for t in threads: t.start()
        for t in threads: t.join()
        job = core.get_job(self.jid)
        for i in range(12): self.assertEqual(job["field" + str(i)], i)
        self.assertEqual(core.read_json(core.job_dir(self.jid) / "state.json"), job)

    def test_poll_does_not_prevent_idle_shutdown(self):
        self.http.last_activity = 1
        self.assertEqual(self.request("status")[0], 200)
        self.assertEqual(self.http.last_activity, 1)

    def test_changed_original_detected(self):
        self.assertEqual(self.upload(fake_apk())[0], 200)
        path = Path(core.get_job(self.jid)["input"]["path"])
        path.chmod(0o600)
        path.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "hash changed"):
            pipeline.input_apk(self.jid)


if __name__ == "__main__":
    unittest.main()
