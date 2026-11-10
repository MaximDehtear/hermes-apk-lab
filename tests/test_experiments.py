import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from apk_lab import core, experiments, pipeline


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, APK_LAB_WORKSPACE=self.tmp.name)
        self.env.start()
        self.job = core.create_job('Unknown sample research')['id']
        self.base = core.job_dir(self.job)
        apk = Path(self.tmp.name) / 'sample.apk'
        with zipfile.ZipFile(apk, 'w') as z:
            z.writestr('AndroidManifest.xml', b'fixture, not installable Android')
        pipeline.import_file(self.job, apk)
        self.script = self.base / 'analysis/probe.py'
        self.script.write_text("import os,json\nfrom pathlib import Path\nx=json.loads(Path(os.environ['APK_LAB_REQUEST']).read_text())\nPath(os.environ['APK_LAB_RESPONSE']).write_text(json.dumps({'observation':x}))\n")
        self.spec = {'version': 1, 'argv': [sys.executable, str(self.script)],
                     'files': ['analysis/probe.py'], 'repeats': 2, 'timeout': 2,
                     'cases': [{'id': 'a', 'input': {'value': 7}, 'expected': {'value': 7}}]}
        self.path = self.base / 'analysis/spec.json'

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def run_probe(self):
        core.atomic_json(self.path, self.spec)
        return experiments.run(self.job, self.path)

    def test_fresh_process_repeat_and_compare(self):
        a, b = self.run_probe(), self.run_probe()
        self.assertTrue(a['repeatable'])
        self.assertEqual(a['verdict'], 'unverified')
        self.assertTrue(all(r['matches_expected'] for r in a['runs']))
        c = experiments.compare(self.job, a['report'], b['report'])
        self.assertTrue(c['agreement'])
        self.spec['cases'][0]['input'] = {'value': 8}
        d = self.run_probe()
        self.assertFalse(experiments.compare(self.job, a['report'], d['report'])['agreement'])

    def test_exit_zero_without_observation_is_not_success(self):
        self.script.write_text('pass\n')
        report = self.run_probe()
        self.assertEqual(report['coverage']['observed'], 0)
        self.assertFalse(report['repeatable'])
        self.assertEqual(report['runs'][0]['status'], 'invalid_response')

    def test_timeout_and_crash_count_as_missing_observation(self):
        for script, expected in [('import os,signal; os.kill(os.getpid(),signal.SIGKILL)', 'execution_failed'),
                                 ('import time; time.sleep(20)', 'timeout_or_cancelled')]:
            self.script.write_text(script)
            self.spec.update(repeats=1, timeout=1)
            r = self.run_probe()
            self.assertEqual(r['runs'][0]['status'], expected)
            self.assertEqual(r['coverage'], {'planned': 1, 'attempted': 1, 'observed': 0})

    def test_bad_schema_and_paths(self):
        for change in [{'timeout': 0}, {'repeats': True}, {'argv': 'echo x'}, {'cases': []},
                       {'cases': [{'id': '../x', 'input': 0}]}]:
            with self.assertRaises(ValueError):
                experiments.validate(self.spec | change)
        self.spec['files'] = ['/etc/passwd']
        with self.assertRaises(ValueError):
            self.run_probe()

    def test_paused_job_not_executed(self):
        core.update_job(self.job, phase='paused')
        with self.assertRaisesRegex(ValueError, 'paused'):
            self.run_probe()

    def test_changed_harness_detected(self):
        self.script.write_text("from pathlib import Path\nPath(__file__).write_text('pass')\n")
        self.assertFalse(self.run_probe()['inputs_unchanged'])

    def test_memory_length_changes_and_truncation(self):
        a, b = self.base/'analysis/a.bin', self.base/'analysis/b.bin'
        a.write_bytes(b'abc'); b.write_bytes(b'axcde')
        r = experiments.memory_diff(self.job, str(a), str(b), 1)
        self.assertEqual(r['changed_bytes'], 3)
        self.assertEqual(r['first_changed_offsets'], [1])
        self.assertTrue(r['offsets_truncated'])

    @unittest.skipUnless(shutil.which('cc'), 'C compiler required')
    def test_unknown_native_fixture_with_independent_oracle(self):
        # Randomized arithmetic is chosen by the test, not known to the controller.
        import secrets
        factor = secrets.randbelow(1000) + 2
        source = self.base/'analysis/sample.c'
        library = self.base/'analysis/sample.so'
        source.write_text(f'unsigned int probe(unsigned int x) {{ return x * {factor}u + 17u; }}')
        subprocess.run(['cc', '-shared', '-fPIC', '-o', str(library), str(source)], check=True)
        self.script.write_text("import ctypes,json,os\nfrom pathlib import Path\nlib=ctypes.CDLL('"+str(library)+"')\nlib.probe.argtypes=[ctypes.c_uint]\nlib.probe.restype=ctypes.c_uint\nx=json.loads(Path(os.environ['APK_LAB_REQUEST']).read_text())\nPath(os.environ['APK_LAB_RESPONSE']).write_text(json.dumps({'observation':lib.probe(x)}))\n")
        self.spec['files'].append('analysis/sample.so')
        self.spec['cases'] = [{'id': str(i), 'input': v, 'expected': (v*factor+17) & 0xffffffff}
                              for i,v in enumerate([0,1,2**32-1,secrets.randbits(32)])]
        a, b = self.run_probe(), self.run_probe()
        self.assertTrue(a['repeatable'])
        self.assertTrue(all(x['matches_expected'] for x in a['runs']))
        self.assertTrue(experiments.compare(self.job, a['report'], b['report'])['agreement'])

    def test_cli_protocol_end_to_end(self):
        core.atomic_json(self.path, self.spec)
        cli = Path(__file__).resolve().parents[1]/'bin/apk-lab'
        proc = subprocess.run([str(cli), 'experiment', self.job, str(self.path)],
                              capture_output=True, text=True, check=True)
        report = json.loads(proc.stdout)
        self.assertEqual(report['coverage']['observed'], 2)
        self.assertTrue(report['repeatable'])
        self.assertTrue(Path(report['report']).is_file())
