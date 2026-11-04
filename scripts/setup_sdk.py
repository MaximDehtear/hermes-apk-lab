#!/usr/bin/env python3
"""Bootstrap the Linux Android SDK required for APK builds and ADB."""
import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from apk_lab.core import config
from setup_emulator import download_tools

PACKAGES = ['platform-tools', 'build-tools;36.0.0', 'platforms;android-34']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--licenses', action='store_true', help='Interactively review SDK licenses before package installation')
    args = parser.parse_args()
    if sys.platform != 'linux' or platform.machine() != 'x86_64':
        raise SystemExit('This SDK setup supports Linux x86_64, including WSL2 x86_64; not native Windows or ARM hosts')
    if not shutil.which('java'):
        raise SystemExit('Install Java 21 first; see INSTALL.md')
    sdk = Path(config().get('android_sdk', str(Path.home() / 'Android/Sdk'))).expanduser().resolve()
    sdk.mkdir(parents=True, exist_ok=True)
    manager = download_tools(sdk)
    base = [str(manager), '--sdk_root=' + str(sdk)]
    if args.licenses:
        subprocess.run([*base, '--licenses'], check=True)
    subprocess.run([*base, '--install', *PACKAGES], check=True)
    expected = [sdk/'platform-tools/adb', sdk/'platforms/android-34/android.jar',
                *[sdk/'build-tools/36.0.0'/name for name in ['aapt2', 'apksigner', 'zipalign']]]
    missing = [str(path) for path in expected if not path.is_file()]
    if missing:
        raise SystemExit('Incomplete SDK installation: ' + ', '.join(missing))
    print('Android SDK ready:', sdk)


if __name__ == '__main__':
    main()
