import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apk_lab import cli, core


class TestTargetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, APK_LAB_WORKSPACE=self.temp.name)
        self.env.start()
        self.jid = core.create_job("Change startup label")["id"]

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def call(self, *args):
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            code = cli.main(list(args))
        return code, json.loads(out.getvalue() if code == 0 else err.getvalue())

    def test_explicit_emulator_selection_uses_managed_serial(self):
        with patch("apk_lab.cli.emulator.start", return_value={"serial": "emulator-5580"}) as start, \
                patch("apk_lab.cli.device.select", return_value={"serial": "emulator-5580", "model": "AVD"}) as select:
            code, job = self.call("test-target", self.jid, "emulator")
        self.assertEqual(code, 0)
        self.assertEqual(job["test_mode"], "emulator")
        self.assertEqual(job["device"]["serial"], "emulator-5580")
        start.assert_called_once()
        select.assert_called_once_with(self.jid, "emulator-5580")

    def test_none_finishes_patch_as_untested(self):
        self.assertEqual(self.call("test-target", self.jid, "none")[0], 0)
        p = core.job_dir(self.jid)
        apk = p / "builds" / "patched.apk"
        apk.write_bytes(b"synthetic")
        verification = {"apk": str(apk), "baseline": False, "sha256": core.sha256(apk),
                        "signature": {"exit_code": 0}, "alignment": {"exit_code": 0}}
        core.atomic_json(apk.parent / "verification.json", verification)
        core.update_job(self.jid, verification=verification)
        report = p / "analysis" / "REPORT.md"
        report.write_text("Patch compiled and signed, but its requested behavior was not tested on Android. " * 3)
        code, result = self.call("finish", self.jid, "--kind", "patch", "--report", str(report))
        self.assertEqual(code, 0)
        self.assertEqual(result["verification_status"], "untested")
        self.assertTrue(any("not runtime-tested" in a["label"] for a in result["artifacts"]))
        self.assertEqual(self.call("test-target", self.jid, "phone")[0], 1)

    def test_emulator_stops_after_last_job_finishes(self):
        other = core.create_job("Investigate second APK")["id"]
        with patch("apk_lab.cli.emulator.stop", return_value={"stopped": True}) as stop:
            for job_id in (self.jid, other):
                core.update_job(job_id, test_mode="emulator")
            for job_id in (self.jid, other):
                report = core.job_dir(job_id) / "analysis" / "REPORT.md"
                report.write_text("The inspected app exposes a test screen. Additional details would require the uploaded APK. " * 2)
                code, result = self.call("finish", job_id, "--report", str(report))
                self.assertEqual(code, 0)
                if job_id == self.jid:
                    self.assertEqual(result["emulator_cleanup"], {"kept_for_jobs": [other]})
                    stop.assert_not_called()
                else:
                    self.assertEqual(result["emulator_cleanup"], {"stopped": True})
            stop.assert_called_once()

    def test_telegram_output_keeps_job_id_and_token(self):
        full_url = "http://192.0.2.10:9099/#job=" + self.jid + "&token=sentinel-token"
        transfer = {"job_id": self.jid, "url": full_url, "public_address_configured": False}
        for args in (("link", self.jid), ("open", "--goal", "Analyze this APK")):
            with patch("apk_lab.cli.server.link", return_value=transfer):
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    self.assertEqual(cli.main([*args, "--format", "telegram"]), 0)
            lines = out.getvalue().splitlines()
            self.assertIn("Job: " + self.jid, lines)
            self.assertIn(full_url, lines)
            self.assertTrue(any("local network" in line for line in lines))

    def test_requesting_window_does_not_restart_active_headless_avd(self):
        from apk_lab import emulator
        with patch("apk_lab.emulator.status", return_value={"running": True, "ready": True, "window": False}), \
                patch("apk_lab.emulator.subprocess.Popen") as start:
            with self.assertRaisesRegex(ValueError, "already headless"):
                emulator.start(window=True)
            start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
