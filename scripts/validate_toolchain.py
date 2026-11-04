#!/usr/bin/env python3
"""Real native-tool smoke test plus a 210 MiB resumed upload, isolated from user jobs."""
import argparse
import hashlib
import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from apk_lab import core, pipeline, research, server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--large-upload", action="store_true")
    parser.add_argument("--output", default=str(PROJECT / "validation.json"))
    args = parser.parse_args()
    result = {"time": time.time(), "toolchain": pipeline.doctor()["tools"], "phone_tested": False}
    sdk = Path(core.config()["android_sdk"])
    android_jar = sorted((sdk / "platforms").glob("*/android.jar"))[-1]
    with tempfile.TemporaryDirectory(prefix="apk-lab-validation-") as tmp:
        os.environ["APK_LAB_WORKSPACE"] = tmp
        temp = Path(tmp)
        def command(argv):
            r = subprocess.run([str(x) for x in argv], capture_output=True, text=True, timeout=180)
            if r.returncode:
                raise RuntimeError(r.stdout + r.stderr)
        bootstrap = temp / "bootstrap.apk"
        command([pipeline.required("aapt2"), "compile", "--dir", PROJECT / "tests/fixture/res", "-o", temp / "resources.zip"])
        command([pipeline.required("aapt2"), "link", "-I", android_jar, "--manifest", PROJECT / "tests/fixture/AndroidManifest.xml", temp / "resources.zip", "-o", bootstrap])
        fixture_tree = temp / "fixture"
        command([pipeline.required("apktool"), "d", bootstrap, "-o", fixture_tree, "-p", temp / "framework"])
        smali = fixture_tree / "smali/dev/hermes/apklabtest/MainActivity.smali"
        smali.parent.mkdir(parents=True)
        shutil.copyfile(PROJECT / "tests/fixture/MainActivity.smali", smali)
        fixture_apk = temp / "fixture.apk"
        command([pipeline.required("apktool"), "b", fixture_tree, "-o", fixture_apk, "-p", temp / "framework"])
        job = core.create_job("Change the fixture label from Before patch to After patch")
        jid = job["id"]
        pipeline.import_file(jid, fixture_apk)
        result["inventory"] = pipeline.inspect(jid)
        result["decompile"] = pipeline.decompile(jid)
        overview = research.recon(jid)
        references = research.xrefs(jid, "Landroid/widget/TextView;->setText(Ljava/lang/CharSequence;)V")
        assert overview["components"] == 1 and overview["methods"] == 2
        assert references["count"] == 1
        assert references["samples"][0]["method"] == "protected onCreate(Landroid/os/Bundle;)V"
        result["research"] = {"components": overview["components"], "methods": overview["methods"],
                              "set_text_references": references["count"], "source_hash_matches":
                              references["samples"][0]["source_sha256"] == core.sha256(core.job_dir(jid) / references["samples"][0]["file"])}
        assert result["research"]["source_hash_matches"]
        baseline = pipeline.build(jid, baseline=True)
        result["baseline_signature_verified"] = baseline["signature"]["exit_code"] == 0
        decoded = core.job_dir(jid) / "decoded/apktool/smali/dev/hermes/apklabtest/MainActivity.smali"
        text = decoded.read_text()
        assert '"Before patch"' in text
        decoded.write_text(text.replace('"Before patch"', '"After patch"'))
        (core.job_dir(jid) / "patches/CHANGELOG.md").write_text("Replace fixture TextView label in onCreate. Runtime test pending.\n")
        patched = pipeline.build(jid)
        with zipfile.ZipFile(patched["apk"]) as z:
            dex = z.read("classes.dex")
            assert b"After patch" in dex and b"Before patch" not in dex
        assert "After patch" in (Path(patched["apk"]).parent / "patch.diff").read_text()
        pipeline.verified_build(jid, patched["apk"])
        result["verified_build_hash_matches"] = True
        rebuilt = Path(patched["apk"]).parent / "redecoded"
        command([pipeline.required("apktool"), "d", patched["apk"], "-o", rebuilt, "-p", temp / "framework"])
        final_smali = (rebuilt / "smali/dev/hermes/apklabtest/MainActivity.smali").read_text()
        assert '"After patch"' in final_smali and '"Before patch"' not in final_smali
        assert "Landroid/widget/TextView;->setText(Ljava/lang/CharSequence;)V" in final_smali
        result["signed_artifact_redecoded"] = True
        result["patch_in_final_dex"] = True
        result["patched_signature_verified"] = patched["signature"]["exit_code"] == 0
        result["alignment_verified"] = patched["alignment"]["exit_code"] == 0
        result["original_unchanged"] = core.sha256(fixture_apk) == core.get_job(jid)["input"]["sha256"]
        if args.large_upload:
            large = temp / "large.apk"
            shutil.copyfile(fixture_apk, large)
            with zipfile.ZipFile(large, "a", compression=zipfile.ZIP_STORED) as z:
                with z.open("assets/large-test.bin", "w", force_zip64=True) as f:
                    for _ in range(210):
                        f.write(b"x" * 1024**2)
            target = core.create_job("Large upload validation")
            token = core.issue_token(target["id"])
            http_server = server.LabServer(("127.0.0.1", 0))
            thread = threading.Thread(target=http_server.serve_forever, daemon=True)
            thread.start()
            def request(action, method="GET", body=None, extra=None):
                conn = http.client.HTTPConnection("127.0.0.1", http_server.server_address[1], timeout=60)
                headers = {"Authorization": "Bearer " + token, **(extra or {})}
                if isinstance(body, dict): body = json.dumps(body).encode()
                conn.request(method, "/api/"+target["id"]+"/"+action, body, headers)
                r = conn.getresponse()
                data = r.read()
                conn.close()
                assert r.status == 200, data
                return json.loads(data)
            try:
                meta = {"name": "large.apk", "size": large.stat().st_size, "fingerprint": "large-test"}
                upload = request("upload", "POST", meta)
                offset = 0
                with large.open("rb") as f:
                    while block := f.read(upload["chunk_bytes"]):
                        if offset == 2 * upload["chunk_bytes"]:
                            resumed = request("upload", "POST", meta)
                            assert resumed["offset"] == offset and resumed["id"] == upload["id"]
                        reply = request("chunk", "PUT", block, {"X-Upload-ID": upload["id"], "X-Upload-Offset": str(offset)})
                        offset = reply["offset"]
                finished = request("complete", "POST", {"id": upload["id"]})
                assert finished["input"]["sha256"] == core.sha256(large)
                result["large_upload"] = {"bytes": large.stat().st_size, "resumed": True, "sha256_matches": True}
            finally:
                http_server.shutdown()
                http_server.server_close()
                thread.join()
        result["passed"] = True
        # Keep compact proof, not paths to private temporary logs that will disappear.
        result["inventory"] = {k: result["inventory"].get(k) for k in ["kind", "package", "launch_activity", "dex"]}
        result["decompile"] = {"apktool_ok": result["decompile"]["apktool_ok"], "jadx_partial": result["decompile"]["jadx_partial"]}
    core.atomic_json(args.output, result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
