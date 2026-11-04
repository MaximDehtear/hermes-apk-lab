#!/usr/bin/env python3
"""Install pinned decompilers inside the project, never into Hermes' working data."""
import argparse
import hashlib
import json
import os
import shutil
import urllib.request
import zipfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
RELEASES = {
    "jadx": ("1.5.6", "https://github.com/skylot/jadx/releases/download/v1.5.6/jadx-1.5.6.zip", "545ea2be9c242511bc145755cf4bda2485ade42966e096f8b4d3da2a230e8974"),
    "apktool": ("3.0.3", "https://github.com/iBotPeaches/Apktool/releases/download/v3.0.3/apktool_3.0.3.jar", "dbf930b076c6b9be08d57c449cacefc3bdd6b71ebd59b3066fc0e1f5b14f9423"),
}


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024**2), b""):
            h.update(block)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--move-existing", action="append", default=[], help="Move an old jar into toolchain/legacy and leave a compatibility symlink")
    a = p.parse_args()
    base = PROJECT / "toolchain"
    base.mkdir(exist_ok=True)
    for value in a.move_existing:
        src = Path(value).expanduser()
        if src.is_symlink():
            continue
        if not src.is_file():
            raise SystemExit("Missing existing tool: " + str(src))
        dest = base / "legacy" / src.name
        dest.parent.mkdir(exist_ok=True)
        if dest.exists():
            raise SystemExit("Refusing to overwrite " + str(dest))
        shutil.move(str(src), str(dest))
        src.symlink_to(dest)
        print("Moved", src, "->", dest, flush=True)
    manifest = {}
    for name, (version, url, expected) in RELEASES.items():
        filename = url.rsplit("/", 1)[1]
        archive = base / filename
        if not archive.exists() or digest(archive) != expected:
            temp = archive.with_suffix(archive.suffix + ".part")
            print("Downloading", name, version, flush=True)
            request = urllib.request.Request(url, headers={"User-Agent": "hermes-apk-lab/0.1"})
            with urllib.request.urlopen(request, timeout=90) as r, temp.open("wb") as f:
                shutil.copyfileobj(r, f, 1024**2)
            if digest(temp) != expected:
                temp.unlink()
                raise SystemExit("SHA256 mismatch: " + name)
            temp.replace(archive)
        manifest[name] = {"version": version, "url": url, "sha256": expected}
        if name == "jadx":
            target = base / ("jadx-" + version)
            if not (target / "bin" / "jadx").exists():
                with zipfile.ZipFile(archive) as z:
                    for item in z.infolist():
                        if not (target / item.filename).resolve().is_relative_to(target.resolve()):
                            raise SystemExit("Unsafe tool archive")
                    z.extractall(target)
                for f in (target / "bin").iterdir():
                    f.chmod(0o755)
    bindir = base / "bin"
    bindir.mkdir(exist_ok=True)
    # Resolve paths relative to each wrapper so the checkout remains relocatable.
    wrappers = {
        "apktool": '#!/bin/sh\nTOOL_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)\nexec java -Xmx2g -jar "$TOOL_ROOT/apktool_3.0.3.jar" "$@"\n',
        "jadx": '#!/bin/sh\nTOOL_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)\nexport JAVA_OPTS="${JAVA_OPTS:--Xmx3g}"\nexec "$TOOL_ROOT/jadx-1.5.6/bin/jadx" "$@"\n',
    }
    for name, text in wrappers.items():
        file = bindir / name
        file.write_text(text)
        file.chmod(0o755)
    (base / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Toolchain ready:", base)


if __name__ == "__main__":
    main()
