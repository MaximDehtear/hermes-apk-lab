#!/usr/bin/env python3
"""Install the official Android emulator and create the Hermes APK Lab AVD."""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from apk_lab.core import config, root

TOOLS_URL = "https://dl.google.com/android/repository/commandlinetools-linux-15859902_latest.zip"
TOOLS_SHA256 = "4e4c464f145a7512b57d088ac6c278c03c9eea610886b35a5e0804e74eedf583"
IMAGE = "system-images;android-34;google_apis;x86_64"
AVD_NAME = "HermesApkLab_API34"


def download_tools(sdk):
    manager = sdk / "cmdline-tools" / "latest" / "bin" / "sdkmanager"
    if manager.is_file():
        for tool in manager.parent.iterdir():
            if tool.is_file():
                tool.chmod(tool.stat().st_mode | 0o111)
        return manager
    target = manager.parents[1]
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="apk-lab-tools-", dir=target.parent) as tmp:
        archive = Path(tmp) / "tools.zip"
        h = hashlib.sha256()
        with urllib.request.urlopen(TOOLS_URL, timeout=60) as response, archive.open("wb") as output:
            while block := response.read(1024 * 1024):
                h.update(block)
                output.write(block)
        if h.hexdigest() != TOOLS_SHA256:
            raise ValueError("Android command-line tools checksum mismatch")
        with zipfile.ZipFile(archive) as z:
            z.extractall(tmp)
        source = Path(tmp) / "cmdline-tools"
        if not (source / "bin" / "sdkmanager").is_file():
            raise ValueError("Downloaded Android tools archive is incomplete")
        if target.exists():
            raise ValueError("Incomplete cmdline-tools/latest exists; inspect it before setup")
        shutil.move(source, target)
    return download_tools(sdk)


def main():
    if sys.platform != "linux" or os.uname().machine != "x86_64":
        raise SystemExit("This setup currently supports Linux x86_64 only")
    sdk = Path(config().get("android_sdk", str(Path.home() / "Android/Sdk"))).expanduser()
    if not sdk.is_dir() or not os.access("/dev/kvm", os.R_OK | os.W_OK):
        raise SystemExit("Run scripts/setup_sdk.py first; a usable /dev/kvm is also required (not guaranteed in WSL2)")
    if shutil.disk_usage(root()).free < 10 * 1024**3:
        raise SystemExit("At least 10 GiB of free workspace disk space is required")
    manager = download_tools(sdk)
    subprocess.run([str(manager), "--sdk_root=" + str(sdk), "--install", "emulator", IMAGE], check=True)
    emulator = sdk / "emulator" / "emulator"
    if not emulator.is_file():
        raise SystemExit("Android Emulator package did not install")
    subprocess.run([str(emulator), "-accel-check"], check=True)
    avd_home = root() / ".emulator" / "avd"
    avd_home.mkdir(parents=True, exist_ok=True, mode=0o700)
    avd_dir = avd_home / (AVD_NAME + ".avd")
    if not (avd_dir / "config.ini").is_file():
        manager = sdk / "cmdline-tools" / "latest" / "bin" / "avdmanager"
        env = dict(os.environ, ANDROID_SDK_ROOT=str(sdk), ANDROID_AVD_HOME=str(avd_home))
        subprocess.run([str(manager), "create", "avd", "-n", AVD_NAME, "-k", IMAGE,
                        "-d", "pixel_5", "-p", str(avd_dir)], input="no\n", text=True, env=env, check=True)
    # Migrate only the generic profile created by early versions of this setup.
    ini = avd_dir / "config.ini"
    settings = ini.read_text()
    if all(line in settings.splitlines() for line in ("hw.lcd.width=320", "hw.lcd.height=640", "hw.lcd.density=160")):
        for old, new in (("hw.lcd.width=320", "hw.lcd.width=1080"),
                         ("hw.lcd.height=640", "hw.lcd.height=2340"),
                         ("hw.lcd.density=160", "hw.lcd.density=440")):
            settings = settings.replace(old, new, 1)
        ini.write_text(settings)
    print(f"Emulator ready: {emulator}; AVD: {avd_dir}")


if __name__ == "__main__":
    main()
