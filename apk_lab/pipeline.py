from __future__ import annotations

import os
import re
import secrets
import shutil
import signal
import subprocess
import time
import zipfile
from pathlib import Path, PurePosixPath

from .core import PROJECT, atomic_json, config, event, get_job, inside, job_dir, lock, now, read_json, root, sha256, update_job


def tools():
    cfg = config().get("tools", {})
    sdk = Path(config().get("android_sdk", str(Path.home() / "Android/Sdk")))
    builds = sorted((sdk / "build-tools").glob("*"), key=lambda p: tuple(int(x) for x in re.findall(r"\d+", p.name)))
    result = {}
    for name in ["java", "keytool", "adb", "apksigner", "zipalign", "aapt2", "jadx", "apktool", "emulator", "analyzeHeadless", "readelf", "nm", "strings", "objdump"]:
        value = cfg.get(name)
        if not value:
            options = [PROJECT / "toolchain" / "bin" / name]
            if name == "adb":
                options.append(sdk / "platform-tools" / name)
            if name == "emulator":
                options.append(sdk / "emulator" / name)
            if name in {"apksigner", "zipalign", "aapt2"}:
                options += [p / name for p in reversed(builds)]
            value = next((str(p) for p in options if p.is_file()), shutil.which(name))
        result[name] = value if value and Path(value).is_file() else None
    return result


def doctor():
    found = tools()
    required = ["java", "keytool", "jadx", "apktool", "apksigner", "zipalign", "aapt2"]
    return {"project": str(PROJECT), "workspace": config()["workspace"], "data_root": str(root()),
            "tools": found, "missing": [n for n in required if not found[n]],
            "native_decompiler_ready": bool(found["analyzeHeadless"]),
            "kvm": os.access("/dev/kvm", os.R_OK | os.W_OK),
            "emulator_avd_ready": (root() / ".emulator/avd/HermesApkLab_API34.avd/config.ini").is_file(),
            "max_upload_bytes": config()["max_upload_bytes"], "port": config()["port"]}


def required(name):
    value = tools().get(name)
    if not value:
        installer = "scripts/setup_native.py" if name == "analyzeHeadless" else "scripts/setup_tools.py"
        raise ValueError("Missing tool: " + name + "; run " + installer)
    return value


def run(job_id, label, argv, timeout=1800, env=None):
    p = job_dir(job_id)
    tag = f"{time.time_ns()}-{label}"
    logfile = p / "logs" / (tag + ".log")
    started = now()
    # Each command has an independent process group so cancellation kills descendants too.
    with logfile.open("wb") as f:
        proc = subprocess.Popen([str(x) for x in argv], cwd=p, stdout=f, stderr=subprocess.STDOUT,
                                env=env, start_new_session=True)
        timed_out = False
        try:
            while proc.poll() is None:
                if now() - started > timeout or get_job(job_id)["phase"] == "paused":
                    timed_out = True
                    os.killpg(proc.pid, signal.SIGTERM)
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait()
                    break
                time.sleep(0.25)
        except BaseException:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            raise
    result = {"argv": [str(x) for x in argv], "exit_code": proc.returncode, "log": str(logfile),
              "duration_seconds": round(now() - started, 2), "interrupted": timed_out}
    event(job_id, "command", **result)
    return result


def checked(job_id, label, argv, timeout=1800, env=None):
    result = run(job_id, label, argv, timeout, env)
    if result["exit_code"] != 0:
        if get_job(job_id)["phase"] != "paused":
            update_job(job_id, phase="blocked", blockers=[{"kind": label, "log": result["log"]}],
                       next_action="Read command log and repair or document the blocker")
        raise ValueError(f"{label} failed; see {result['log']}")
    return result


def archive_info(path):
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        if len(infos) > 200000:
            raise ValueError("Archive contains too many entries")
        names = [i.filename for i in infos]
        if len(set(names)) != len(names):
            raise ValueError("Duplicate archive entries are not supported")
        expanded = sum(i.file_size for i in infos)
        if expanded > 16 * 1024**3:
            raise ValueError("Expanded archive exceeds 16 GiB limit")
        for i in infos:
            parts = PurePosixPath(i.filename).parts
            if i.filename.startswith("/") or ".." in parts or "\\" in i.filename or "\x00" in i.filename:
                raise ValueError("Unsafe archive path")
            if (i.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Archive symlinks are not supported")
            if i.flag_bits & 1:
                raise ValueError("Encrypted archive entries are unsupported")
        is_apk = "AndroidManifest.xml" in names
        nested = [n for n in names if n.lower().endswith(".apk")]
        if not is_apk and not nested:
            raise ValueError("Expected APK or an archive containing APKs")
        return {"kind": "apk" if is_apk else "split_archive", "entries": len(infos),
                "expanded_bytes": expanded, "dex": [n for n in names if re.fullmatch(r"classes\d*\.dex", n)],
                "native_libraries": [n for n in names if n.startswith("lib/") and n.endswith(".so")],
                "nested_apks": nested,
                "framework_hints": {"flutter": any("libflutter.so" in n for n in names),
                                    "unity": any("libunity.so" in n for n in names),
                                    "react_native": any("index.android.bundle" in n or "libhermes.so" in n for n in names)}}


def accept_input(job_id, path, name):
    p = job_dir(job_id)
    job = get_job(job_id)
    if job["input"]:
        raise ValueError("This job already has input; create a new job for another APK")
    info = archive_info(path)
    digest = sha256(path)
    suffix = ".apk" if info["kind"] == "apk" else ".zip"
    dest = p / "input" / ("original" + suffix)
    os.replace(path, dest)
    os.chmod(dest, 0o400)
    inp = {"path": str(dest), "name": Path(name).name, "sha256": digest,
           "size": dest.stat().st_size, **info}
    atomic_json(p / "inventory.json", inp)
    job = update_job(job_id, input=inp, phase="ready", blockers=[], next_action="Run inspect, then decompile and investigate the goal")
    event(job_id, "upload_complete", sha256=digest, size=inp["size"])
    return job


def import_file(job_id, source):
    with lock(job_dir(job_id) / ".upload.lock"):
        tmp = job_dir(job_id) / "input" / "import.part"
        try:
            shutil.copyfile(source, tmp)
            return accept_input(job_id, tmp, Path(source).name)
        finally:
            tmp.unlink(missing_ok=True)


def input_apk(job_id):
    inp = get_job(job_id)["input"]
    if not inp:
        raise ValueError("Upload an APK first")
    if inp["kind"] != "apk":
        raise ValueError("Split archive: inspect inventory and analyze each package; monolithic rebuild is not valid")
    path = Path(inp["path"])
    if sha256(path) != inp["sha256"]:
        raise ValueError("Original APK hash changed")
    return path


def inspect(job_id):
    with lock(job_dir(job_id) / ".operation.lock", blocking=False):
        job = get_job(job_id)
        if not job["input"]:
            raise ValueError("Upload input first")
        path = Path(job["input"]["path"])
        if sha256(path) != job["input"]["sha256"]:
            raise ValueError("Original APK hash changed")
        inventory = dict(job["input"])
        if inventory["kind"] == "split_archive":
            update_job(job_id, phase="blocked", blockers=[{"kind": "split_archive", "details": inventory["nested_apks"]}],
                       next_action="Extract and inspect the base and required splits separately; never claim base-only is installable")
            return inventory
        update_job(job_id, phase="analyzing", next_action="Read metadata; decompile and trace the requested behavior")
        if tools()["aapt2"]:
            result = run(job_id, "badging", [required("aapt2"), "dump", "badging", path])
            inventory["badging_log"] = result["log"]
            text = Path(result["log"]).read_text(errors="replace")
            for field, pattern in {"package": r"package: name='([^']+)'", "launch_activity": r"launchable-activity: name='([^']+)'",
                                   "min_sdk": r"sdkVersion:'([^']+)'", "target_sdk": r"targetSdkVersion:'([^']+)'"}.items():
                match = re.search(pattern, text)
                inventory[field] = match.group(1) if match else None
        if tools()["apksigner"]:
            inventory["original_signature"] = run(job_id, "original-signature", [required("apksigner"), "verify", "--verbose", "--print-certs", path])
        atomic_json(job_dir(job_id) / "inventory.json", inventory)
        return inventory


def decompile(job_id):
    p = job_dir(job_id)
    with lock(p / ".operation.lock", blocking=False):
        apk = input_apk(job_id)
        update_job(job_id, phase="analyzing", blockers=[], next_action="Trace goal-relevant classes, smali, resources and native code; record evidence")
        status = read_json(p / "analysis" / "decompile.json", {})
        smali = p / "decoded" / "apktool"
        if not status.get("apktool_ok"):
            # Failed outputs are retained for diagnosis, never silently overwritten.
            if smali.exists():
                smali.rename(smali.with_name("apktool.failed." + str(time.time_ns())))
            result = checked(job_id, "apktool-decode", [required("apktool"), "d", str(apk), "-o", str(smali), "-p", str(p / "decoded" / "framework")])
            status.update(apktool_ok=True, apktool=result)
            atomic_json(p / "analysis" / "decompile.json", status)
        if not status.get("jadx_finished"):
            result = run(job_id, "jadx", [required("jadx"), "--threads-count", "2", "-d", str(p / "decoded" / "jadx"), str(apk)])
            status.update(jadx_finished=not result["interrupted"], jadx=result,
                          jadx_partial=result["exit_code"] != 0)
            atomic_json(p / "analysis" / "decompile.json", status)
        event(job_id, "decompiled", partial=status.get("jadx_partial"))
        return status


def snapshot_patch(job_id):
    p = job_dir(job_id)
    files = {}
    for file in (p / "decoded" / "apktool").rglob("*"):
        if file.is_file() and not any(x in {"build", "dist"} for x in file.relative_to(p / "decoded" / "apktool").parts):
            files[str(file.relative_to(p / "decoded" / "apktool"))] = sha256(file)
    return files


def build(job_id, baseline=False):
    p = job_dir(job_id)
    with lock(p / ".operation.lock", blocking=False):
        input_apk(job_id)
        if not (p / "decoded" / "apktool" / "apktool.yml").exists():
            raise ValueError("Run decompile before building")
        before = snapshot_patch(job_id)
        if baseline:
            if (p / "analysis" / "baseline-files.json").exists():
                raise ValueError("Baseline already exists; do not replace it with patched content")
        else:
            original = read_json(p / "analysis" / "baseline-files.json")
            if original is None:
                raise ValueError("Build a baseline before applying patches")
            if not (p / "patches" / "CHANGELOG.md").is_file():
                raise ValueError("Record the requested changes and evidence in patches/CHANGELOG.md")
        revision = get_job(job_id)["revision"] + 1
        while (p / "builds" / f"r{revision:03d}").exists():
            revision += 1
        out = p / "builds" / f"r{revision:03d}"
        out.mkdir()
        if not baseline:
            changed = sorted(k for k in set(original) | set(before) if original.get(k) != before.get(k))
            atomic_json(out / "changes.json", {"changed_files": changed, "before": original, "after": before})
            # Reproducible text diff, independent of the agent's narrative.
            import difflib
            with zipfile.ZipFile(p / "patches" / "baseline-source.zip") as baseline_zip:
                with (out / "patch.diff").open("w") as diff:
                    for name in changed:
                        old = baseline_zip.read(name) if name in original else b""
                        new = (p / "decoded" / "apktool" / name).read_bytes() if name in before else b""
                        try:
                            old_text, new_text = old.decode("utf-8"), new.decode("utf-8")
                        except UnicodeDecodeError:
                            diff.write(f"Binary file changed: {name}\n")
                            continue
                        diff.writelines(difflib.unified_diff(old_text.splitlines(True), new_text.splitlines(True), fromfile="a/"+name, tofile="b/"+name))
        update_job(job_id, phase="building", revision=revision, next_action="Build, align, sign and verify")
        checked(job_id, "apktool-build", [required("apktool"), "b", str(p / "decoded" / "apktool"), "-p", str(p / "decoded" / "framework"), "-o", str(out / "unsigned.apk")])
        checked(job_id, "zipalign", [required("zipalign"), "-P", "16", "-f", "4", str(out / "unsigned.apk"), str(out / "aligned.apk")])
        keys = root() / ".keys"
        keys.mkdir(mode=0o700, exist_ok=True)
        keystore = keys / "lab.p12"
        password_path = keys / "password"
        with lock(keys / ".lock"):
            if not keystore.exists():
                if not password_path.exists():
                    password_path.write_text(secrets.token_urlsafe(36))
                    os.chmod(password_path, 0o600)
                env = dict(os.environ, APK_LAB_KEY_PASSWORD=password_path.read_text().strip())
                checked(job_id, "create-key", [required("keytool"), "-genkeypair", "-keystore", str(keystore), "-storetype", "PKCS12",
                        "-storepass:env", "APK_LAB_KEY_PASSWORD", "-alias", "apk-lab", "-keyalg", "RSA", "-keysize", "3072",
                        "-validity", "10000", "-dname", "CN=Hermes APK Lab"], env=env)
                os.chmod(keystore, 0o600)
        env = dict(os.environ, APK_LAB_KEY_PASSWORD=password_path.read_text().strip())
        final = out / ("baseline.apk" if baseline else "patched.apk")
        checked(job_id, "sign", [required("apksigner"), "sign", "--ks", str(keystore), "--ks-key-alias", "apk-lab",
                "--ks-pass", "env:APK_LAB_KEY_PASSWORD", "--out", str(final), str(out / "aligned.apk")], env=env)
        signature = checked(job_id, "verify-signature", [required("apksigner"), "verify", "--verbose", "--print-certs", str(final)])
        alignment = checked(job_id, "verify-alignment", [required("zipalign"), "-c", "-P", "16", "4", str(final)])
        markers = [read_json(x, {}) for x in (p / "patches/instrumentation").glob("*/record.json")]
        active_markers = [m["marker"] for m in markers if not m.get("removed")]
        result = {"diagnostic_markers": active_markers, "diagnostic_only": bool(active_markers),
                  "baseline": baseline, "revision": revision, "apk": str(final), "sha256": sha256(final),
                  "signature": signature, "alignment": alignment, "runtime": "not_tested"}
        atomic_json(out / "verification.json", result)
        if baseline:
            atomic_json(p / "analysis" / "baseline-files.json", before)
            # Baseline source snapshot permits an actual diff/rollback after editing.
            with zipfile.ZipFile(p / "patches" / "baseline-source.zip", "w", zipfile.ZIP_DEFLATED) as z:
                for name in before:
                    z.write(p / "decoded" / "apktool" / name, name)
        update_job(job_id, phase="analyzing" if baseline else "built", verification=result,
                   next_action="Test baseline on Android" if baseline else "Test target behavior on Android and write report")
        event(job_id, "build_verified", **result)
        return result


def verified_build(job_id, apk):
    path = inside(apk, job_dir(job_id) / "builds")
    record = read_json(path.parent / "verification.json", {})
    if (not path.is_file() or record.get("apk") != str(path)
            or not record.get("sha256") or sha256(path) != record["sha256"]
            or record.get("signature", {}).get("exit_code") != 0
            or record.get("alignment", {}).get("exit_code") != 0):
        raise ValueError("Build is unverified or APK hash changed; rebuild before installation/delivery")
    return record


def runtime_test(job_id, apk, serial):
    p = job_dir(job_id)
    apk = inside(apk, p / "builds")
    if not apk.is_file():
        raise ValueError("APK is missing")
    from .collaborative import require_agent
    with lock(p / ".collaboration.lock"), lock(p / ".operation.lock", blocking=False):
        require_agent(job_id)
        verified_build(job_id, apk)
        inventory = read_json(p / "inventory.json", {})
        package, activity = inventory.get("package"), inventory.get("launch_activity")
        if not package or not activity:
            raise ValueError("Run inspect and determine the launchable activity first")
        adb = [required("adb"), "-s", serial]
        checked(job_id, "device-state", adb + ["get-state"], 30)
        installed = checked(job_id, "install", adb + ["install", "-r", str(apk)], 180)
        launched = checked(job_id, "launch", adb + ["shell", "am", "start", "-W", "-n", package + "/" + activity], 60)
        launch_text = Path(launched["log"]).read_text(errors="replace")
        if "Status: ok" not in launch_text or "Error:" in launch_text:
            raise ValueError("Activity launch did not report Status: ok; inspect " + launched["log"])
        time.sleep(2)
        alive = run(job_id, "app-pid", adb + ["shell", "pidof", package], 20)
        logs = run(job_id, "logcat", adb + ["logcat", "-d", "-t", "500"], 30)
        result = {"apk_sha256": sha256(apk), "serial": serial, "install": installed, "launch": launched,
                  "process_alive": alive["exit_code"] == 0, "logcat": logs, "behavior_verified": False,
                  "note": "Install/launch smoke test only; the requested behavior needs a separate scenario"}
        atomic_json(p / "tests" / f"runtime-{time.time_ns()}.json", result)
        update_job(job_id, next_action="Execute and record the goal-specific UI/runtime scenario")
        return result
