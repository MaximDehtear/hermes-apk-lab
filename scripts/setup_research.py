#!/usr/bin/env python3
"""Install optional research wheels in a private, hash-locked Python environment."""
import argparse
import subprocess
import sys
import venv
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from apk_lab.core import lock


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--frida', action='store_true', help='Also install the optional Frida Python client')
    a = p.parse_args()
    if not (3, 11) <= sys.version_info[:2] < (3, 15):
        raise SystemExit('Use Python 3.11–3.14')
    target = PROJECT / 'toolchain/research'
    with lock(PROJECT / 'toolchain/.research-install.lock', blocking=False):
        executable = target / 'bin/python'
        if not executable.exists():
            venv.EnvBuilder(with_pip=True).create(target)
        profiles = ['research'] + (['frida'] if a.frida else [])
        for profile in profiles:
            subprocess.run([str(executable), '-m', 'pip', 'install', '--disable-pip-version-check',
                            '--require-hashes', '--only-binary=:all:', '--no-deps',
                            '-r', str(PROJECT / 'requirements' / (profile + '.txt'))], check=True)
        subprocess.run([str(executable), '-m', 'pip', 'check'], check=True)
        modules = 'capstone, unicorn, elftools' + (', frida' if a.frida else '')
        subprocess.run([str(executable), '-I', '-c', 'import ' + modules], check=True)
    print('Research environment ready:', executable)


if __name__ == '__main__':
    main()
