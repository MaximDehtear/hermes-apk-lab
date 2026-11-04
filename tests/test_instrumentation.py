import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from apk_lab import core, instrumentation, pipeline


class InstrumentationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, APK_LAB_WORKSPACE=self.temp.name)
        self.env.start()
        self.jid = core.create_job('Trace obfuscated method')['id']
        self.directory = core.job_dir(self.jid)
        apk = Path(self.temp.name)/'test.apk'
        with zipfile.ZipFile(apk,'w') as archive:
            archive.writestr('AndroidManifest.xml', 'fixture')
        pipeline.import_file(self.jid, apk)
        self.path = self.directory/'decoded/apktool/smali/a/A.smali'
        self.path.parent.mkdir(parents=True)
        self.path.write_text('''.class public La/A;
.super Ljava/lang/Object;
.method public a()I
    .locals 1
    .annotation runtime Ltest/Annotation;
        value = "not an instruction"
    .end annotation
    const/4 v0, 0x1
    invoke-static {}, La/A;->b()I
    move-result v0
    return v0
.end method
''')
        (self.directory/'patches/baseline-source.zip').write_bytes(b'fixture')
        self.original = self.path.read_bytes()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_marker_preserves_registers_and_can_be_removed_exactly(self):
        result = instrumentation.inject(self.jid, 'La/A;->a()I', 'readPreferences')
        current = self.path.read_text()
        self.assertIn('.locals 1', current)
        self.assertLess(current.index('.end annotation'), current.index('->hit()V'))
        self.assertLess(current.index('->hit()V'), current.index('const/4'))
        helper = Path(result['helper'])
        self.assertTrue(helper.exists())
        instrumentation.remove(self.jid, result['marker'])
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse(helper.exists())

    def test_line_markers_refuse_stale_hash_and_move_result(self):
        with self.assertRaisesRegex(ValueError, 'Source hash'):
            instrumentation.inject(self.jid, 'La/A;->a()I', 'send', 'line', 9, 'stale')
        with self.assertRaisesRegex(ValueError, 'ordering'):
            instrumentation.inject(self.jid, 'La/A;->a()I', 'send', 'line', 10, core.sha256(self.path))
        with self.assertRaisesRegex(ValueError, 'executable'):
            instrumentation.inject(self.jid, 'La/A;->a()I', 'send', 'line', 6, core.sha256(self.path))

    def test_removal_refuses_overwriting_later_edits(self):
        result = instrumentation.inject(self.jid, 'La/A;->a()I', 'return', 'returns')
        self.path.write_text(self.path.read_text()+'# later patch\n')
        with self.assertRaisesRegex(ValueError, 'sources changed'):
            instrumentation.remove(self.jid, result['marker'])
