import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    with patch.object(sys, 'path', [str(SCRIPTS), *sys.path]):
        spec.loader.exec_module(module)
    return module


class SetupTests(unittest.TestCase):
    def test_sdk_bootstrap_creates_missing_sdk_without_kvm(self):
        module = load('setup_sdk')
        with tempfile.TemporaryDirectory() as tmp:
            sdk = Path(tmp)/'new-sdk'
            def download(path):
                self.assertTrue(path.is_dir())
                return path/'sdkmanager'
            def install(argv, **kwargs):
                for path in [sdk/'platform-tools/adb', sdk/'platforms/android-34/android.jar',
                             *[sdk/'build-tools/36.0.0'/n for n in ['aapt2','apksigner','zipalign']]]:
                    path.parent.mkdir(parents=True,exist_ok=True)
                    path.touch()
            with patch.object(module, 'config', return_value={'android_sdk':str(sdk)}), \
                    patch.object(module, 'download_tools', side_effect=download), \
                    patch.object(module.shutil, 'which', return_value='/usr/bin/java'), \
                    patch.object(module.platform, 'machine', return_value='x86_64'), \
                    patch.object(module.subprocess, 'run', side_effect=install) as run, \
                    patch.object(sys, 'argv', ['setup_sdk.py','--licenses']):
                module.main()
            self.assertIn('--licenses',run.call_args_list[0].args[0])
            self.assertIn('build-tools;36.0.0',run.call_args_list[1].args[0])

    def test_explicit_workspace_does_not_bypass_backend_check(self):
        module = load('install')
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)/'hermes';home.mkdir()
            (home/'config.yaml').write_text('terminal:\n  backend: docker\n')
            workspace=Path(tmp)/'workspace'
            with patch.object(sys,'argv',['install.py','--hermes-home',str(home),'--workspace',str(workspace)]):
                with self.assertRaisesRegex(SystemExit,'backend=local'):
                    module.main()
            self.assertFalse(workspace.exists())

    def test_configuration_is_used_by_installer(self):
        import contextlib
        import io
        import json
        configure = load('configure')
        installer = load('install')
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)/'project';project.mkdir()
            user = Path(tmp)/'user';user.mkdir()
            home = user/'.hermes';home.mkdir()
            workspace = user/'work'
            (home/'config.yaml').write_text('terminal:\n  backend: local\n  cwd: '+str(workspace)+'\n')
            (project/'bin').mkdir();(project/'bin/apk-lab').write_text('#!/bin/sh\n')
            (project/'skills/apk-reverse-engineering').mkdir(parents=True)
            with patch.object(configure,'PROJECT',project), patch.object(sys,'argv',[
                    'configure.py','--non-interactive','--hermes-home',str(home),
                    '--workspace',str(workspace),'--port','9123','--exposure','local',
                    '--sdk',str(user/'sdk'),'--max-upload-gib','2']), contextlib.redirect_stdout(io.StringIO()):
                configure.main()
            with patch.object(installer,'PROJECT',project), patch.object(Path,'home',return_value=user), \
                    patch.dict('os.environ',{'HERMES_HOME':str(home)}), \
                    patch.object(sys,'argv',['install.py']), contextlib.redirect_stdout(io.StringIO()):
                installer.main()
            cfg=json.loads((project/'config.local.json').read_text())
            self.assertEqual(cfg['port'],9123)
            self.assertEqual(cfg['exposure'],'local')
            self.assertEqual(cfg['android_sdk'],str(user/'sdk'))
            self.assertEqual(cfg['max_upload_bytes'],2*1024**3)
            self.assertTrue((home/'skills/security/apk-reverse-engineering').is_symlink())
