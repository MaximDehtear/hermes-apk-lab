#!/usr/bin/env python3
"""Black-box ELF preflight validation against independently executed readelf."""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from apk_lab import capabilities, core, experiments, native, pipeline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('apk')
    parser.add_argument('--workspace', required=True, help='Dedicated validation workspace')
    args = parser.parse_args()
    os.environ['APK_LAB_WORKSPACE'] = str(Path(args.workspace).resolve())
    job = core.create_job('Black-box ELF preflight validation')['id']
    pipeline.import_file(job, Path(args.apk).resolve())
    base = core.job_dir(job)
    apk = pipeline.input_apk(job)
    libraries = pipeline.archive_info(apk)['native_libraries'][:2]
    if not libraries:
        raise SystemExit('Sample contains no native libraries; native validation not exercised')
    worker = base/'analysis/native_probe.py'
    shutil.copyfile(PROJECT/'scripts/native_probe.py', worker)
    checks = []
    for member in libraries:
        native.analyze(job, member)
        library = base/'decoded/native-input'/Path(member).relative_to('lib')
        spec = {'version':1, 'argv':[str(capabilities.python_path()),str(worker)],
                'files':[str(worker.relative_to(base)),str(library.relative_to(base))],
                'cases':[{'id':'elf','input':{'operation':'elf','file':str(library)}}]}
        path = base/'analysis/spec.json'
        core.atomic_json(path, spec)
        a, b = experiments.run(job, path), experiments.run(job, path)
        observed = a['runs'][0]['observation']
        reference = subprocess.run([pipeline.required('readelf'),'-h',str(library)],capture_output=True,text=True,check=True).stdout
        (base/'logs'/('reference-'+library.parent.name+'-'+library.name+'.txt')).write_text(reference)
        bits = int(re.search(r'Class:\s+ELF(32|64)',reference).group(1))
        entry = int(re.search(r'Entry point address:\s+(0x[0-9a-fA-F]+)',reference).group(1),16)
        passed = observed['bits'] == bits and observed['entry'] == entry and a['repeatable'] and experiments.compare(job,a['report'],b['report'])['agreement']
        checks.append({'library_sha256':core.sha256(library),'readelf_header_agreement':passed,'repeatable':a['repeatable']})
    result = {'job':job,'input_sha256':core.sha256(apk),'checks':checks,
              'scope':'Real APK ELF preflight only; no Android execution or semantic solution claims'}
    core.atomic_json(base/'analysis/validation.json', result)
    print(json.dumps(result,indent=2))
    if not all(c['readelf_header_agreement'] for c in checks):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
