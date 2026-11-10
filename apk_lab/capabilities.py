"""Discover optional native research components without importing them in the controller."""
import json
import os
import subprocess
from pathlib import Path
from .core import PROJECT, config

PINS = {'capstone': '5.0.6', 'unicorn': '2.1.4', 'pyelftools': '0.32', 'frida': '17.4.0'}
IMPORTS = {'capstone': 'capstone', 'unicorn': 'unicorn', 'pyelftools': 'elftools', 'frida': 'frida'}


def python_path():
    return Path(config().get('research_python', PROJECT / 'toolchain/research/bin/python'))


def discover():
    executable = python_path()
    result = {'python': str(executable), 'ready': False, 'packages': {},
              'install': 'python3 scripts/setup_research.py',
              'limits': ['Host probes execute native code; process isolation is not a security sandbox.',
                         'Frida client availability does not establish device/server compatibility.']}
    if not executable.is_file() or not os.access(executable, os.X_OK):
        result['error'] = 'Optional research environment is not installed'
        return result
    program = '''import importlib, importlib.metadata, json
result = {}
for name, module in %r.items():
 try:
  importlib.import_module(module)
  result[name] = {'version': importlib.metadata.version(name)}
 except Exception as exc:
  result[name] = {'error': str(exc)}
print(json.dumps(result))
''' % IMPORTS
    try:
        proc = subprocess.run([str(executable), '-I', '-c', program], capture_output=True, text=True, timeout=20)
        if proc.returncode:
            raise ValueError(proc.stderr[-1000:])
        result['packages'] = json.loads(proc.stdout)
        for name, item in result['packages'].items():
            item['expected'] = PINS[name]
            item['compatible'] = item.get('version') == PINS[name]
        result['ready'] = all(result['packages'][n]['compatible'] for n in PINS if n != 'frida')
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        result['error'] = str(exc)
    return result
