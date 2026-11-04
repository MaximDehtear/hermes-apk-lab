import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from apk_lab import collaborative, core, device, pipeline


class CollaborativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, APK_LAB_WORKSPACE=self.temp.name)
        self.env.start()
        self.jid = core.create_job('Shared UI investigation')['id']
        self.directory = core.job_dir(self.jid)
        core.update_job(self.jid, test_mode='phone', device={'serial':'fixture'})

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_explicit_mode_and_human_turn_block_mutations(self):
        with patch('apk_lab.device.shell', return_value='') as shell:
            with self.assertRaisesRegex(ValueError, 'work-mode'):
                device.action(self.jid, 'tap', ['1','2'])
            collaborative.set_mode(self.jid, 'manual')
            with self.assertRaisesRegex(ValueError, 'User owns'):
                device.action(self.jid, 'tap', ['1','2'])
            shell.assert_not_called()
            collaborative.handoff(self.jid, 'agent', 'User says ready; inspect current screen')
            device.action(self.jid, 'tap', ['1','2'])
            shell.assert_called_once()
            collaborative.handoff(self.jid, 'user', 'Please open the hidden settings screen')
            self.assertEqual(core.get_job(self.jid)['handoff_sequence'], 2)
            with self.assertRaisesRegex(ValueError, 'User owns'):
                collaborative.require_agent(self.jid)

    def test_observe_user_turn_is_read_only_and_records_partial_failures(self):
        collaborative.set_mode(self.jid, 'manual')
        with patch('apk_lab.device.screenshot', return_value={'path':'screen.png'}) as screenshot, \
                patch('apk_lab.device.hierarchy', side_effect=ValueError('secure/custom UI')), \
                patch('apk_lab.device.capture_logcat', return_value={'path':'logs.txt'}), \
                patch('apk_lab.device.action') as action, patch('apk_lab.pipeline.runtime_test') as install:
            result = collaborative.observe(self.jid, 'user-ready', 'declared-build-hash')
            screenshot.assert_called_once_with(self.jid, 'user-ready', 'declared-build-hash')
        self.assertIn('hierarchy', result['errors'])
        self.assertIn('logcat', result['observations'])
        action.assert_not_called()
        install.assert_not_called()
        self.assertEqual(core.get_job(self.jid)['control_owner'], 'user')

    def test_memories_are_evidence_bound_and_reused_only_for_exact_input(self):
        apk = Path(self.temp.name)/'fixture.apk'
        with zipfile.ZipFile(apk, 'w') as archive:
            archive.writestr('AndroidManifest.xml', 'fixture')
        pipeline.import_file(self.jid, apk)
        evidence = self.directory/'analysis/observed.txt'
        evidence.write_text('User opened menu then long-pressed settings')
        spec = self.directory/'analysis/lesson.json'
        core.atomic_json(spec, {'kind':'procedure', 'name':'Open advanced settings',
                               'precondition':'Home screen, same account and build',
                               'steps':['Open menu', 'Long-press settings'], 'result':'demonstrated',
                               'evidence':['analysis/observed.txt']})
        collaborative.remember(self.jid, spec)
        other = core.create_job('Reuse investigation')['id']
        pipeline.import_file(other, apk)
        records = collaborative.memories(other)['records']
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0]['evidence_intact'])
        evidence.write_text('changed')
        self.assertFalse(collaborative.memories(other)['records'][0]['evidence_intact'])
        core.atomic_json(spec, {'kind':'alias','symbol':'La;->b()V','label':'refreshPreferences',
                               'basis':'inferred','evidence':['/etc/passwd']})
        with self.assertRaises(ValueError):
            collaborative.remember(self.jid, spec)

    def test_human_turn_in_another_job_protects_shared_device(self):
        collaborative.set_mode(self.jid, 'auto')
        other = core.create_job('Other human scenario')['id']
        core.update_job(other, test_mode='phone', device={'serial':'fixture'})
        collaborative.set_mode(other, 'manual')
        with self.assertRaisesRegex(ValueError, 'another job'):
            collaborative.require_agent(self.jid)
        collaborative.handoff(other, 'agent', 'User finished the shared-device segment')
        collaborative.require_agent(self.jid)
