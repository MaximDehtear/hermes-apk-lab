"""Selected-device Frida attach through the experiment/evidence workflow."""
import shutil
import time
from . import capabilities, collaborative, core, device, experiments


def attach(job_id, pid, script, seconds=10):
    if pid < 1 or not 1 <= seconds <= 300:
        raise ValueError('PID must be positive; seconds must be 1..300')
    collaborative.require_agent(job_id)
    serial = device.selected(job_id)
    base = core.job_dir(job_id)
    source = experiments._file(base, script)
    python = capabilities.python_path()
    if not python.is_file():
        raise ValueError('Install the optional Frida client: python3 scripts/setup_research.py --frida')
    # Keep a copy of the worker alongside the script for reproducible provenance.
    folder = base / 'analysis/runtime' / str(time.time_ns())
    folder.mkdir(parents=True)
    worker = folder/'frida_probe.py'
    shutil.copyfile(core.PROJECT/'scripts/frida_probe.py', worker)
    spec = {'version': 1, 'argv': [str(python), str(worker)],
            'files': [str(worker.relative_to(base)), str(source.relative_to(base))],
            'timeout': seconds + 20, 'repeats': 1,
            'assumptions': ['Attach changes process behavior. Installed APK identity must be checked separately.',
                            'Server version, ABI and access rights must be checked before attach.'],
            'cases': [{'id': 'attach', 'input': {'serial': serial, 'pid': pid,
                       'script': str(source), 'seconds': seconds}}]}
    path = folder/'spec.json'
    core.atomic_json(path, spec)
    with core.lock(device.device_lock(serial), blocking=False):
        collaborative.require_agent(job_id)
        return experiments.run(job_id, path)
