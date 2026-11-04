#!/usr/bin/env python3
"""Install a checksum-pinned Ghidra release inside the project (Java 21)."""
import hashlib
import json
import shutil
import urllib.request
import zipfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
VERSION = '11.4.2'
NAME = 'ghidra_11.4.2_PUBLIC_20250826.zip'
URL = 'https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_11.4.2_build/' + NAME
SHA256 = '795a02076af16257bd6f3f4736c4fc152ce9ff1f95df35cd47e2adc086e037a6'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    base = PROJECT / 'toolchain'
    base.mkdir(exist_ok=True)
    archive = base / NAME
    if not archive.exists() or digest(archive) != SHA256:
        if shutil.disk_usage(base).free < 2 * 1024**3:
            raise SystemExit('At least 2 GiB free disk space required')
        part = archive.with_suffix('.part')
        print('Downloading Ghidra', VERSION, flush=True)
        request = urllib.request.Request(URL, headers={'User-Agent': 'hermes-apk-lab'})
        with urllib.request.urlopen(request, timeout=120) as response, part.open('wb') as stream:
            shutil.copyfileobj(response, stream, 1024**2)
        if digest(part) != SHA256:
            part.unlink()
            raise SystemExit('Ghidra checksum mismatch')
        part.replace(archive)
    with zipfile.ZipFile(archive) as zipped:
        for entry in zipped.infolist():
            dest = (base / entry.filename).resolve()
            mode = entry.external_attr >> 16
            if not dest.is_relative_to(base.resolve()) or mode & 0o170000 == 0o120000:
                raise SystemExit('Unsafe tool archive entry')
        zipped.extractall(base)
        for entry in zipped.infolist():
            path = base / entry.filename
            if path.is_file():
                path.chmod(0o755 if (entry.external_attr >> 16) & 0o111 else 0o644)
    binary = base / 'bin/analyzeHeadless'
    binary.parent.mkdir(exist_ok=True)
    binary.write_text('#!/bin/sh\nTOOL_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)\nexec "$TOOL_ROOT/ghidra_11.4.2_PUBLIC/support/analyzeHeadless" "$@"\n')
    binary.chmod(0o755)
    (base / 'native-manifest.json').write_text(json.dumps({'ghidra': {'version': VERSION, 'url': URL, 'sha256': SHA256}}, indent=2) + '\n')
    print('Ghidra ready:', binary)


if __name__ == '__main__':
    main()
