#!/usr/bin/env python3
"""Compile a synthetic C++ library, pack it into a fixture APK, and decompile it."""
import json
import os
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from apk_lab import core, native, pipeline


def main():
    with tempfile.TemporaryDirectory(prefix='apk-lab-native-test-') as temporary:
        folder = Path(temporary)
        os.environ['APK_LAB_WORKSPACE'] = temporary
        source = folder/'fixture.cpp'
        source.write_text('namespace Lab { int score(int x) { return x * 3 + 7; } }\nextern "C" int Java_lab_Test_score(void*, void*, int x) { return Lab::score(x); }\n')
        library = folder/'libfixture.so'
        subprocess.run(['g++', '-shared', '-fPIC', '-O0', str(source), '-o', str(library)], check=True)
        apk = folder/'native.apk'
        with zipfile.ZipFile(apk, 'w') as zipped:
            zipped.writestr('AndroidManifest.xml', b'synthetic static-only fixture')
            zipped.write(library, 'lib/x86_64/libfixture.so')
        job = core.create_job('Validate native C++ decompilation')['id']
        pipeline.import_file(job, apk)
        result = native.analyze(job, 'lib/x86_64/libfixture.so', True, 'score', 5)
        assert result['ghidra']['decompiled'] >= 2, result
        rows = [json.loads(s) for s in (Path(result['output'])/'functions.jsonl').read_text().splitlines()]
        cpp = next(r for r in rows if 'Lab::score' in r['name'])
        pseudocode = (Path(result['output'])/cpp['pseudocode']).read_text()
        assert '3' in pseudocode and '7' in pseudocode, pseudocode
        again = native.analyze(job, 'lib/x86_64/libfixture.so', True, 'Java_lab_Test_score', 1)
        assert again['project_reused'] and again['ghidra']['decompiled'] == 1
        proof = {'time':time.time(), 'passed':True, 'summary':result['ghidra'],
                 'library_sha256':result['library_sha256'], 'cpp_name':cpp['name'],
                 'pseudocode':pseudocode, 'project_reused':again['project_reused'],
                 'note':'Host x86_64 ELF validates analysis/decompilation only; not an Android runtime/JNI test.'}
        core.atomic_json(PROJECT/'native-validation.json', proof)
        print(json.dumps(proof, indent=2))


if __name__ == '__main__':
    main()
