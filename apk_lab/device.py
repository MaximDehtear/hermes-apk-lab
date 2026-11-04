from __future__ import annotations

import hashlib
import json
import re
import shlex
import struct
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from .core import atomic_json, event, get_job, job_dir, lock, now, publish, read_json, root, sha256, update_job
from .pipeline import required


def adb(argv, timeout=30, binary=False):
    r = subprocess.run([required("adb"), *argv], capture_output=True, timeout=timeout)
    if r.returncode:
        raise ValueError("ADB: " + r.stderr.decode(errors="replace")[-2000:])
    return r.stdout if binary else r.stdout.decode(errors="replace")


def shell(serial, words, timeout=30):
    # adb joins shell arguments: quote the remote command explicitly, never interpolate user text.
    return adb(["-s", serial, "shell", shlex.join([str(x) for x in words])], timeout)


def devices():
    lines = adb(["devices", "-l"]).splitlines()[1:]
    return [{"serial": parts[0], "state": parts[1], "details": " ".join(parts[2:])}
            for line in lines if len(parts := line.split()) >= 2]


def select(job_id, serial):
    available = devices()
    if not any(x["serial"] == serial and x["state"] == "device" for x in available):
        raise ValueError("Device must be connected and authorized; check device list and accept USB debugging on the phone")
    metadata = {"serial": serial, "model": shell(serial, ["getprop", "ro.product.model"]).strip(),
                "android": shell(serial, ["getprop", "ro.build.version.release"]).strip(),
                "abi": shell(serial, ["getprop", "ro.product.cpu.abilist"]).strip(),
                "display": shell(serial, ["wm", "size"]).strip()}
    update_job(job_id, device=metadata)
    event(job_id, "device_selected", **metadata)
    return metadata


def selected(job_id):
    job = get_job(job_id)
    if job.get("test_mode") not in {"phone", "emulator"}:
        raise ValueError("Choose phone or emulator test target for this job first")
    value = job.get("device", {}).get("serial")
    if not value:
        raise ValueError("Select a device explicitly for this job first")
    return value


def device_lock(serial):
    return root() / ".runtime" / ("device-" + hashlib.sha256(serial.encode()).hexdigest()[:20] + ".lock")


def screenshot(job_id, label, build_sha256=None, publish_image=True):
    serial = selected(job_id)
    folder = job_dir(job_id) / "tests" / "screenshots"
    folder.mkdir(exist_ok=True)
    tag = f"{time.time_ns()}-{re.sub(r'[^a-zA-Z0-9_-]', '_', label)[:60]}"
    with lock(device_lock(serial), blocking=False):
        data = adb(["-s", serial, "exec-out", "screencap", "-p"], binary=True)
        if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) < 24:
            raise ValueError("Device did not return a PNG screenshot")
        width, height = struct.unpack(">II", data[16:24])
        path = folder / (tag + ".png")
        path.write_bytes(data)
        focus = shell(serial, ["dumpsys", "window", "windows"])
        focus = "\n".join(x.strip() for x in focus.splitlines() if "mCurrentFocus" in x or "mFocusedApp" in x)
    metadata = {"path": str(path), "label": label, "captured_at": now(), "serial": serial,
                "width": width, "height": height, "focus": focus, "build_sha256": build_sha256,
                "image_sha256": sha256(path), "note": "Build hash is declared context; verify the installed build separately"}
    atomic_json(folder / (tag + ".json"), metadata)
    event(job_id, "screenshot", **metadata)
    if publish_image:
        metadata["artifact"] = publish(job_id, path, label)
    return metadata


def hierarchy(job_id):
    serial = selected(job_id)
    with lock(device_lock(serial), blocking=False):
        shell(serial, ["uiautomator", "dump", "/data/local/tmp/apk-lab-ui.xml"], timeout=45)
        xml = shell(serial, ["cat", "/data/local/tmp/apk-lab-ui.xml"])
    name = job_dir(job_id) / "tests" / f"ui-{time.time_ns()}.xml"
    name.write_text(xml)
    try:
        tree = ET.fromstring(xml)
        nodes = [{k: n.get(k) for k in ["text", "resource-id", "content-desc", "class", "bounds", "clickable", "enabled"]}
                 for n in tree.iter("node") if n.get("text") or n.get("content-desc") or n.get("clickable") == "true"]
    except ET.ParseError:
        nodes = []
    return {"path": str(name), "nodes": nodes, "note": "Custom-rendered/Unity/Flutter screens may need image-based targeting"}


def action(job_id, kind, values):
    from .collaborative import require_agent
    require_agent(job_id)
    serial = selected(job_id)
    if get_job(job_id)["phase"] == "paused":
        raise ValueError("Job is paused")
    if kind == "tap":
        if len(values) != 2:
            raise ValueError("tap requires X Y in original screenshot pixels")
        points = [int(x) for x in values]
        if any(x < 0 or x > 20000 for x in points):
            raise ValueError("Invalid coordinates")
        args = ["input", "tap", *map(str, points)]
    elif kind == "swipe":
        if len(values) not in (4, 5):
            raise ValueError("swipe requires X1 Y1 X2 Y2 [milliseconds]")
        nums = [int(x) for x in values]
        if any(x < 0 or x > 20000 for x in nums):
            raise ValueError("Invalid swipe values")
        args = ["input", "swipe", *map(str, nums)]
    elif kind == "key":
        keys = {"back": "4", "home": "3", "enter": "66", "tab": "61", "delete": "67", "wake": "224"}
        if len(values) != 1 or values[0] not in keys:
            raise ValueError("Allowed keys: " + ", ".join(keys))
        args = ["input", "keyevent", keys[values[0]]]
    elif kind == "text":
        value = " ".join(values)
        if not value.isascii() or not value or any(ord(c) < 32 for c in value):
            raise ValueError("ADB text input supports printable ASCII here; use the on-screen keyboard for other scripts")
        args = ["input", "text", value.replace(" ", "%s")]
    elif kind == "launch":
        if len(values) != 1 or not re.fullmatch(r"[A-Za-z0-9_.$]+/[A-Za-z0-9_.$]+", values[0]):
            raise ValueError("launch requires package/activity")
        args = ["am", "start", "-W", "-n", values[0]]
    else:
        raise ValueError("Unknown device action")
    with lock(job_dir(job_id) / ".collaboration.lock"), lock(device_lock(serial), blocking=False):
        require_agent(job_id)
        output = shell(serial, args)
    # Do not persist text typed into possibly sensitive form fields.
    event(job_id, "device_action", serial=serial, action=kind, arguments=values if kind != "text" else ["<redacted>"], output=output[-3000:])
    return {"action": kind, "serial": serial, "output": output, "next_action": "Capture a new screenshot and verify the resulting UI before the next action"}


def capture_logcat(job_id):
    serial = selected(job_id)
    data = adb(["-s", serial, "logcat", "-d", "-t", "1000"])
    path = job_dir(job_id) / "tests" / f"logcat-{time.time_ns()}.txt"
    path.write_text(data)
    return {"path": str(path), "serial": serial}


def connect(address):
    if not re.fullmatch(r"[A-Za-z0-9.:-]+:\d{1,5}", address) or not 0 < int(address.rsplit(":", 1)[1]) < 65536:
        raise ValueError("Expected device IP:port from Wireless debugging")
    return {"output": adb(["connect", address]), "devices": devices()}


def evidence_result(job_id, spec_path):
    """Explicit observations, bound to screenshots/build; never infer success from installation."""
    p = job_dir(job_id)
    from .core import inside
    spec = read_json(inside(spec_path, p))
    for key in ["scenario", "expected", "observed", "verdict", "before", "after", "build_sha256"]:
        if not spec.get(key):
            raise ValueError("Missing scenario evidence: " + key)
    if spec["verdict"] not in {"passed", "failed", "inconclusive"}:
        raise ValueError("verdict must be passed, failed or inconclusive")
    build_records = [read_json(x, {}) for x in (p / "builds").glob("*/verification.json")]
    matching = [x for x in build_records if x.get("sha256") == spec["build_sha256"]]
    if not matching:
        raise ValueError("Scenario must reference a verified build SHA-256")
    shots = {}
    for key in ["before", "after"]:
        path = inside(spec[key], p / "tests" / "screenshots")
        if not path.is_file() or path.suffix != ".png":
            raise ValueError("Evidence screenshot is missing")
        metadata = read_json(path.with_suffix(".json"), {})
        if not metadata or metadata.get("image_sha256") != sha256(path):
            raise ValueError("Screenshot metadata is missing or PNG was modified")
        shots[key] = metadata
        spec[key] = str(path)
        spec[key + "_artifact"] = publish(job_id, path, key + ": " + spec["scenario"])
    if spec["before"] == spec["after"]:
        raise ValueError("Before and after must be separate captures")
    if shots["after"].get("build_sha256") != spec["build_sha256"]:
        raise ValueError("After screenshot must be captured with the tested build SHA-256")
    if shots["before"]["serial"] != shots["after"]["serial"]:
        raise ValueError("Before/after captures must use the same device")
    receipts = [read_json(x, {}) for x in (p / "tests").glob("runtime-*.json")]
    if spec["verdict"] == "passed" and not any(r.get("apk_sha256") == spec["build_sha256"] and r.get("process_alive") and r.get("serial") == shots["after"]["serial"] for r in receipts):
        raise ValueError("A passed patched-build scenario requires an install/launch receipt for this exact APK")
    spec["recorded_at"] = now()
    dest = p / "tests" / f"scenario-{time.time_ns()}.json"
    atomic_json(dest, spec)
    event(job_id, "scenario", verdict=spec["verdict"], report=str(dest))
    return {"path": str(dest), "verdict": spec["verdict"], "screenshots_published": True}
