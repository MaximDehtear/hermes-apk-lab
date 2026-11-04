import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from apk_lab import core, server


class LifecycleTests(unittest.TestCase):
    def test_detached_server_stop_and_idle_preserve_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.json"
            core.atomic_json(cfg, {"workspace": tmp, "port": 0, "exposure": "local", "idle_seconds": 2, "lifetime_seconds": 60})
            with patch.dict(os.environ, APK_LAB_CONFIG=str(cfg), APK_LAB_WORKSPACE=tmp):
                job = core.create_job("Lifecycle test")
                try:
                    first = server.start_server("local", 0)
                    self.assertTrue(first["running"])
                    same = server.start_server("local", 0)
                    self.assertEqual(first["process"], same["process"])
                    stopped = server.stop_server()
                    self.assertFalse(stopped["status"]["running"])
                    # Give systemd time to collect the old transient unit.
                    time.sleep(0.5)
                    server.start_server("local", 0)
                    deadline = time.monotonic() + 8
                    while server.server_status()["running"] and time.monotonic() < deadline:
                        time.sleep(0.1)
                    self.assertFalse(server.server_status()["running"])
                    self.assertEqual(core.get_job(job["id"])["goal"], "Lifecycle test")
                finally:
                    server.stop_server()


if __name__ == "__main__":
    unittest.main()
