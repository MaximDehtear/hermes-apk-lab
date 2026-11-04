import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from apk_lab import core, native, pipeline


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, APK_LAB_WORKSPACE=self.temp.name)
        self.env.start()
        self.jid = core.create_job('Inspect native library')['id']
        apk = Path(self.temp.name)/'fixture.apk'
        with zipfile.ZipFile(apk, 'w') as zipped:
            zipped.writestr('AndroidManifest.xml', b'fixture')
            zipped.writestr('lib/arm64-v8a/libtest.so', b'not ELF')
        pipeline.import_file(self.jid, apk)

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_path_and_headless_option_injection_rejected(self):
        with patch('apk_lab.native.checked') as execute:
            for member in ['../../libtest.so', '/lib/arm64-v8a/libtest.so', 'lib/../libtest.so', 'lib/arm64-v8a/-bad.so']:
                with self.assertRaises(ValueError):
                    native.analyze(self.jid, member)
            with self.assertRaisesRegex(ValueError, 'selector'):
                native.analyze(self.jid, 'lib/arm64-v8a/libtest.so', True, '-preScript')
            execute.assert_not_called()

    def test_non_elf_rejected_before_tools(self):
        with patch('apk_lab.native.checked') as execute:
            with self.assertRaisesRegex(ValueError, 'not an ELF'):
                native.analyze(self.jid, 'lib/arm64-v8a/libtest.so')
            execute.assert_not_called()
