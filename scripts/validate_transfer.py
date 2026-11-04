#!/usr/bin/env python3
"""Test direct 0.0.0.0:9099 transfer using the host interface, without user files."""
import io
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from apk_lab import core, server


def main():
    with tempfile.TemporaryDirectory(prefix="apk-lab-transfer-") as tmp:
        os.environ["APK_LAB_WORKSPACE"] = tmp
        job = core.create_job("Direct transfer validation")
        try:
            cfg = Path(tmp) / "config.json"
            core.atomic_json(cfg, {"workspace": tmp, "exposure": "direct", "port": 9099})
            os.environ["APK_LAB_CONFIG"] = str(cfg)
            link = server.link(job["id"], "direct", 9099)
            assert server.server_status()["bind"] == "0.0.0.0"
            parsed = urlsplit(link["url"])
            origin = parsed.scheme + "://" + parsed.netloc
            token = parse_qs(parsed.fragment)["token"][0]
            def request(action, method="GET", data=None, extra=None, authenticated=True):
                hdr = {"Authorization": "Bearer " + token} if authenticated else {}
                hdr.update(extra or {})
                if isinstance(data, dict):
                    data = json.dumps(data).encode()
                req = urllib.request.Request(origin + "/api/" + job["id"] + "/" + action, data=data, headers=hdr, method=method)
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=60) as r:
                    return json.loads(r.read())
            assert request("status")["id"] == job["id"]
            unauthorized = False
            try:
                request("status", authenticated=False)
            except urllib.error.HTTPError as e:
                unauthorized = e.code == 403
            assert unauthorized
            data = io.BytesIO()
            with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_STORED) as z:
                z.writestr("AndroidManifest.xml", "test transport only")
                z.writestr("assets/payload", b"x" * (12 * 1024**2))
            payload = data.getvalue()
            upload = request("upload", "POST", {"name": "transfer-test.apk", "size": len(payload), "fingerprint": "test"})
            offset = 0
            while offset < len(payload):
                block = payload[offset:offset+upload["chunk_bytes"]]
                reply = request("chunk", "PUT", block, {"X-Upload-ID": upload["id"], "X-Upload-Offset": str(offset), "Content-Type": "application/octet-stream"})
                offset = reply["offset"]
            result = request("complete", "POST", {"id": upload["id"]})
            assert result["phase"] == "ready"
            proof = {"passed": True, "bind": "0.0.0.0", "local_port": 9099, "tested_origin": origin,
                     "external_network_tested": False, "unauthorized_rejected": unauthorized,
                     "uploaded_bytes": len(payload), "time": time.time()}
            core.atomic_json(PROJECT / "transfer-validation.json", proof)
            print(json.dumps(proof, indent=2))
        finally:
            stopped = server.stop_server()
            print("Transfer service stopped:", not stopped["status"]["running"])


if __name__ == "__main__":
    main()
