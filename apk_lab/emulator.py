"""Managed, headless Android virtual device in the Hermes workspace."""
from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

from .core import atomic_json, config, lock, read_json, root
from .device import adb, devices
from .server import alive, identity

AVD_NAME = "HermesApkLab_API34"
SERIAL = "emulator-5580"


def metadata_path():
    path = root() / ".runtime" / "emulator.json"
    path.parent.mkdir(mode=0o700, exist_ok=True)
    return path


def avd_home():
    return root() / ".emulator" / "avd"


def executable():
    return Path(config().get("android_sdk", str(Path.home() / "Android/Sdk"))) / "emulator" / "emulator"


def status():
    data = read_json(metadata_path(), {})
    return data | {"running": alive(data.get("process")), "ready": alive(data.get("process")) and ready()}


def ready():
    try:
        return adb(["-s", SERIAL, "shell", "getprop", "sys.boot_completed"], timeout=5).strip() == "1"
    except (ValueError, OSError, subprocess.TimeoutExpired):
        return False


def start(timeout=240, window=False):
    with lock(root() / ".runtime" / "emulator.lock"):
        current = status()
        if current["running"]:
            if current["ready"]:
                if window and not current.get("window"):
                    raise ValueError("Emulator is already headless. Use a local scrcpy viewer, or restart with --window only after preserving the current scenario.")
                return current
            raise ValueError("Managed emulator is already starting; retry after boot completes")
        if any(d["serial"] == SERIAL for d in devices()):
            raise ValueError(f"ADB serial {SERIAL} is occupied by an unmanaged emulator")
        exe = executable()
        avd = avd_home() / (AVD_NAME + ".avd")
        if not exe.is_file() or not (avd / "config.ini").is_file():
            raise ValueError("Emulator/AVD missing; run python3 scripts/setup_emulator.py")
        if not os.access("/dev/kvm", os.R_OK | os.W_OK):
            raise ValueError("/dev/kvm is unavailable for this user")
        if window and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            raise ValueError("A desktop display is required for --window; use a phone or an existing remote desktop/viewer")
        env = dict(os.environ, ANDROID_AVD_HOME=str(avd_home()),
                   ANDROID_SDK_ROOT=str(exe.parent.parent))
        log_path = root() / ".runtime" / "emulator.log"
        with log_path.open("ab") as log:
            proc = subprocess.Popen([str(exe), "-avd", AVD_NAME, "-port", "5580",
                                     *([] if window else ["-no-window"]), "-no-audio", "-gpu", "swiftshader_indirect",
                                     "-no-snapshot-save"], cwd=root(), env=env,
                                    stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                    start_new_session=True)
        state = {"process": identity(proc.pid), "serial": SERIAL, "avd": AVD_NAME,
                 "log": str(log_path), "started_at": time.time(), "window": window}
        atomic_json(metadata_path(), state)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise ValueError("Emulator exited during boot; inspect " + str(log_path))
            if ready():
                return status()
            time.sleep(2)
        stop_process(state)
        raise ValueError("Emulator did not boot before timeout; inspect " + str(log_path))


def stop_process(data):
    item = data.get("process")
    if not alive(item):
        return False
    try:
        os.killpg(item["pid"], signal.SIGTERM)
    except ProcessLookupError:
        return False
    for _ in range(30):
        if not alive(item):
            return True
        time.sleep(0.2)
    if alive(item):
        os.killpg(item["pid"], signal.SIGKILL)
    return True


def stop():
    with lock(root() / ".runtime" / "emulator.lock"):
        state = read_json(metadata_path(), {})
        stopped = stop_process(state)
        atomic_json(metadata_path(), state | {"process": None, "stopped_at": time.time()})
        return {"stopped": stopped, "serial": SERIAL, "avd_preserved": True}
