import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from apk_lab import capabilities

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT/'toolchain/research/bin/python'


class DiscoveryTests(unittest.TestCase):
    def test_missing_optional_does_not_break_doctor(self):
        with patch('apk_lab.capabilities.python_path', return_value=Path('/missing/python')):
            self.assertFalse(capabilities.discover()['ready'])

    def test_version_mismatch_reported(self):
        packages = {n: {'version': '0.0'} for n in capabilities.PINS}
        proc = subprocess.CompletedProcess([], 0, json.dumps(packages), '')
        with patch('apk_lab.capabilities.python_path', return_value=Path('/usr/bin/python3')), \
                patch('apk_lab.capabilities.subprocess.run', return_value=proc):
            self.assertFalse(capabilities.discover()['ready'])


@unittest.skipUnless(PYTHON.exists(), 'Optional research environment unavailable')
class NativeWorkerTests(unittest.TestCase):
    def probe(self, request, files=None):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            for name, data in (files or {}).items():
                (p/name).write_bytes(data)
            (p/'input.json').write_text(json.dumps(request))
            env = os.environ | {'APK_LAB_REQUEST':str(p/'input.json'), 'APK_LAB_RESPONSE':str(p/'output.json')}
            subprocess.run([str(PYTHON), str(ROOT/'scripts/native_probe.py')], cwd=p, env=env, check=True, capture_output=True)
            return json.loads((p/'output.json').read_text())['observation']

    def test_bounded_execution_and_fault(self):
        # inc eax; jmp backwards: a loop that must stop at the instruction budget.
        req = {'operation':'emulate', 'architecture':'x86_64',
               'regions':[{'address':4096,'size':4096,'file':'code.bin'}],
               'start':4096,'until':4100,'instruction_limit':10,
               'registers':{'eax':3},'read_registers':['eax']}
        out = self.probe(req, {'code.bin':b'\xff\xc0\xeb\xfc'})
        self.assertEqual(out['status'],'instruction_limit')
        self.assertEqual(out['executed'],10)
        self.assertEqual(out['registers']['eax'],8)
        req['start'] = 8192
        self.assertEqual(self.probe(req, {'code.bin':b'\xff\xc0\xeb\xfc'})['status'],'fault')

    def test_elf_has_real_segments(self):
        out = self.probe({'operation':'elf','file':'/bin/true'})
        self.assertTrue(out['load_segments'])
        self.assertTrue(out['needed'])

class RuntimeOwnershipTests(unittest.TestCase):
    def test_handoff_denial_prevents_attach(self):
        from apk_lab import runtime
        with patch('apk_lab.runtime.collaborative.require_agent', side_effect=ValueError('user owns turn')), \
                patch('apk_lab.runtime.experiments.run') as execute:
            with self.assertRaisesRegex(ValueError, 'user owns turn'):
                runtime.attach('a'*16, 42, 'analysis/probe.js')
            execute.assert_not_called()

    def test_invalid_duration_prevents_attach(self):
        from apk_lab import runtime
        with self.assertRaises(ValueError):
            runtime.attach('a'*16, 42, 'analysis/probe.js', 0)
