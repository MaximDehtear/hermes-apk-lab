import contextlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from apk_lab import cli, core, pipeline, research


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, APK_LAB_WORKSPACE=self.temp.name)
        self.env.start()
        self.jid = core.create_job("Trace a persisted flag")["id"]
        self.job = core.job_dir(self.jid)
        source = Path(self.temp.name) / "fixture.apk"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("AndroidManifest.xml", b"fixture")
        pipeline.import_file(self.jid, source)
        self.tree = self.job / "decoded/apktool"
        self.tree.mkdir(parents=True)
        (self.tree / "AndroidManifest.xml").write_text('''<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="test.app">
<uses-permission android:name="android.permission.INTERNET"/>
<application android:debuggable="false"><activity android:name=".Main">
<intent-filter><action android:name="android.intent.action.VIEW"/><data android:scheme="https"/></intent-filter>
</activity><service android:name=".Worker" android:exported="false"/></application></manifest>''')
        self.code = self.tree / "smali/test/A.smali"
        self.code.parent.mkdir(parents=True)
        self.code.write_text('''.class public Ltest/A;
.super Ljava/lang/Object;
.method public check()V
    # sget-boolean v0, Ltest/State;->flag:Z
    const-string v0, "Ltest/State;->flag:Z"
    sget-boolean v0, Ltest/State;->flag:Z # real read
    sput-boolean v0, Ltest/State;->flag:Z
    sget-boolean v0, Ltest/State;->flag:Zmore
    invoke-static {}, Ltest/State;->refresh()V
    invoke-static {}, Ltest/State;->refresh(I)V
    return-void
.end method
.method public native calculate()I
.end method
''')
        other = self.tree / "smali_classes2/test/B.smali"
        other.parent.mkdir(parents=True)
        other.write_text('''.class public Ltest/B;
.method public reset()V
    iput-boolean v0, p0, Ltest/State;->flag:Z
    return-void
.end method
''')

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_recon_preserves_implicit_exports_and_multidex(self):
        summary = research.recon(self.jid)
        result = core.read_json(summary["path"])
        self.assertEqual((result["smali_files"], result["methods"]), (2, 3))
        components = result["manifest"]["components"]
        self.assertTrue(components[0]["exported_resolution"].startswith("implicit:"))
        self.assertEqual(components[1]["exported_resolution"], "false")
        self.assertEqual(components[0]["intent_filters"][0]["data"], [{"scheme": "https"}])
        self.assertEqual(result["native_method_samples"][0]["declaration"], ".method public native calculate()I")
        self.assertEqual(result["input_sha256"], core.get_job(self.jid)["input"]["sha256"])

    def test_exact_xrefs_ignore_strings_comments_and_partial_names(self):
        result = research.xrefs(self.jid, "Ltest/State;->flag:Z")
        rows = [json.loads(line) for line in Path(result["path"]).read_text().splitlines()]
        self.assertEqual(result["count"], 3)
        self.assertEqual([r["kind"] for r in rows], ["read", "write", "write"])
        self.assertEqual(rows[0]["method"], "public check()V")
        self.assertEqual(rows[-1]["class"], "Ltest/B;")
        self.assertEqual(rows[0]["source_sha256"], core.sha256(self.code))
        self.assertEqual(rows[0]["line"], 6)
        metadata = core.read_json(Path(result["path"]).with_suffix(".meta.json"))
        self.assertEqual(metadata["symbol"], result["symbol"])
        calls = research.xrefs(self.jid, "Ltest/State;->refresh()V")
        self.assertEqual(calls["count"], 1)
        self.assertEqual(calls["samples"][0]["kind"], "call")
        self.assertEqual(research.xrefs(self.jid, "Ltest/State;->missing()V")["count"], 0)
        with self.assertRaisesRegex(ValueError, "full smali"):
            research.xrefs(self.jid, "flag")

    def test_malformed_manifest_and_source_escape_are_rejected(self):
        (self.tree / "AndroidManifest.xml").write_text("<broken>")
        with self.assertRaisesRegex(ValueError, "Invalid decoded manifest"):
            research.recon(self.jid)
        outside = Path(self.temp.name) / "outside.smali"
        outside.write_text(self.code.read_text())
        self.code.unlink()
        self.code.symlink_to(outside)
        with self.assertRaises(ValueError):
            research.xrefs(self.jid, "Ltest/State;->flag:Z")

    def test_modified_original_rejected_before_external_tools(self):
        original = Path(core.get_job(self.jid)["input"]["path"])
        original.chmod(0o600)
        original.write_bytes(b"changed")
        with patch("apk_lab.pipeline.run") as run:
            for operation in (pipeline.inspect, research.recon):
                with self.assertRaisesRegex(ValueError, "Original APK hash changed"):
                    operation(self.jid)
            run.assert_not_called()

    def verified_fixture(self):
        folder = self.job / "builds/r001"
        folder.mkdir()
        apk = folder / "patched.apk"
        apk.write_bytes(b"synthetic signed build")
        record = {"apk": str(apk), "sha256": core.sha256(apk), "baseline": False,
                  "signature": {"exit_code": 0}, "alignment": {"exit_code": 0}}
        core.atomic_json(folder / "verification.json", record)
        core.update_job(self.jid, verification=record, test_mode="none", work_mode="auto", control_owner="agent")
        return apk, record

    def test_tampered_build_cannot_install_or_finish_even_when_testing_skipped(self):
        apk, record = self.verified_fixture()
        self.assertEqual(pipeline.verified_build(self.jid, apk), record)
        apk.write_bytes(b"changed after signing")
        with patch("apk_lab.pipeline.checked") as checked:
            with self.assertRaisesRegex(ValueError, "hash changed"):
                pipeline.runtime_test(self.jid, apk, "fixture-serial")
            checked.assert_not_called()
        report = self.job / "analysis/REPORT.md"
        report.write_text("Behavior not tested; no runtime claim is made. " * 4)
        with contextlib.redirect_stderr(io.StringIO()) as err:
            code = cli.main(["finish", self.jid, "--kind", "patch", "--report", str(report)])
        self.assertEqual(code, 1)
        self.assertIn("hash changed", err.getvalue())
        self.assertEqual(core.get_job(self.jid)["artifacts"], [])

    def test_failed_signature_and_stale_job_record_cannot_finish(self):
        apk, record = self.verified_fixture()
        record["signature"]["exit_code"] = 1
        core.atomic_json(apk.parent / "verification.json", record)
        with self.assertRaisesRegex(ValueError, "unverified"):
            pipeline.verified_build(self.jid, apk)
        record["signature"]["exit_code"] = 0
        core.atomic_json(apk.parent / "verification.json", record)
        core.update_job(self.jid, verification={**record, "sha256": "stale"})
        report = self.job / "analysis/REPORT.md"
        report.write_text("Behavior not tested; no runtime claim is made. " * 4)
        with contextlib.redirect_stderr(io.StringIO()) as err:
            code = cli.main(["finish", self.jid, "--kind", "patch", "--report", str(report)])
        self.assertEqual(code, 1)
        self.assertIn("stale", err.getvalue())

    def test_diagnostic_build_cannot_be_finished_as_final(self):
        apk, record = self.verified_fixture()
        record["diagnostic_only"] = True
        core.atomic_json(apk.parent / "verification.json", record)
        core.update_job(self.jid, verification=record)
        report = self.job / "analysis/REPORT.md"
        report.write_text("Diagnostic build for observation, with temporary markers. " * 4)
        with contextlib.redirect_stderr(io.StringIO()) as err:
            code = cli.main(["finish", self.jid, "--kind", "patch", "--report", str(report)])
        self.assertEqual(code, 1)
        self.assertIn("Diagnostic markers", err.getvalue())
        self.assertEqual(core.get_job(self.jid)["artifacts"], [])


if __name__ == "__main__":
    unittest.main()
