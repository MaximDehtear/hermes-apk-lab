import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apk_lab import core, device

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j9GQAAAAASUVORK5CYII=")


class DeviceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, APK_LAB_WORKSPACE=self.temp.name)
        self.env.start()
        self.jid = core.create_job("Visual fixture test")["id"]
        core.update_job(self.jid, device={"serial": "fixture-serial"}, test_mode="phone", work_mode="auto", control_owner="agent")

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_remote_shell_arguments_are_quoted(self):
        with patch("apk_lab.device.adb", return_value="") as called:
            device.shell("phone", ["input", "text", "$(touch /tmp/unwanted);x"])
            argv = called.call_args.args[0]
            self.assertEqual(argv[:3], ["-s", "phone", "shell"])
            self.assertIn("'$(touch /tmp/unwanted);x'", argv[3])

    def test_screenshot_publication_and_evidence_binding(self):
        p = core.job_dir(self.jid)
        with patch("apk_lab.device.adb", return_value=PNG), patch("apk_lab.device.shell", return_value="focus fixture"):
            before = device.screenshot(self.jid, "before", "original")
            after = device.screenshot(self.jid, "after", "patched")
        self.assertEqual(before["width"], 1)
        self.assertTrue(Path(before["artifact"]["path"]).is_file())
        self.assertNotEqual(before["artifact"]["id"], after["artifact"]["id"])
        self.assertEqual(len(core.get_job(self.jid)["artifacts"]), 2)
        build = p / "builds/r001"
        build.mkdir()
        core.atomic_json(build / "verification.json", {"sha256": "patched"})
        spec = {"scenario": "change label", "expected": "new label", "observed": "new label shown",
                "verdict": "passed", "before": before["path"], "after": after["path"], "build_sha256": "patched"}
        file = p / "tests/spec.json"
        core.atomic_json(file, spec)
        with self.assertRaisesRegex(ValueError, "receipt"):
            device.evidence_result(self.jid, file)
        core.atomic_json(p / "tests/runtime-1.json", {"apk_sha256": "patched", "process_alive": True, "serial": "fixture-serial"})
        self.assertEqual(device.evidence_result(self.jid, file)["verdict"], "passed")
        Path(after["path"]).write_bytes(b"modified")
        with self.assertRaisesRegex(ValueError, "modified"):
            device.evidence_result(self.jid, file)

    def test_paused_job_does_not_tap_phone(self):
        core.update_job(self.jid, phase="paused")
        with patch("apk_lab.device.shell") as called:
            with self.assertRaisesRegex(ValueError, "paused"):
                device.action(self.jid, "tap", ["10", "20"])
            called.assert_not_called()

    def test_skip_testing_blocks_device_actions(self):
        core.update_job(self.jid, test_mode="none", device={})
        with patch("apk_lab.device.adb") as called:
            with self.assertRaisesRegex(ValueError, "Choose phone or emulator"):
                device.screenshot(self.jid, "untested")
            called.assert_not_called()


if __name__ == "__main__":
    unittest.main()
