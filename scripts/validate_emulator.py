#!/usr/bin/env python3
"""Install a synthetic APK on the managed AVD and verify visual before/after evidence."""
import argparse
import json
import time
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from apk_lab import collaborative, core, device, emulator, instrumentation, pipeline


def command(argv):
    done = subprocess.run([str(x) for x in argv], capture_output=True, text=True, timeout=180)
    if done.returncode:
        raise ValueError(done.stdout + done.stderr)


def ui_text(job_id):
    return " ".join(n.get("text") or "" for n in device.hierarchy(job_id)["nodes"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(PROJECT / "emulator-validation.json"))
    args = parser.parse_args()
    previous = os.environ.get("APK_LAB_WORKSPACE")
    state = emulator.start()
    try:
        with tempfile.TemporaryDirectory(prefix="apk-lab-avd-validation-") as temporary:
            os.environ["APK_LAB_WORKSPACE"] = temporary
            temp = Path(temporary)
            sdk = Path(core.config()["android_sdk"])
            platform = sdk / "platforms" / "android-34" / "android.jar"
            command([pipeline.required("aapt2"), "compile", "--dir", PROJECT / "tests/fixture/res", "-o", temp / "resources.zip"])
            bootstrap = temp / "bootstrap.apk"
            command([pipeline.required("aapt2"), "link", "-I", platform, "--manifest", PROJECT / "tests/fixture/AndroidManifest.xml",
                     temp / "resources.zip", "-o", bootstrap])
            tree = temp / "fixture"
            command([pipeline.required("apktool"), "d", bootstrap, "-o", tree, "-p", temp / "framework"])
            smali = tree / "smali/dev/hermes/apklabtest/MainActivity.smali"
            smali.parent.mkdir(parents=True)
            shutil.copyfile(PROJECT / "tests/fixture/MainActivity.smali", smali)
            source = temp / "fixture.apk"
            command([pipeline.required("apktool"), "b", tree, "-o", source, "-p", temp / "framework"])
            job_id = core.create_job("Validate visual Before patch to After patch change on AVD")["id"]
            pipeline.import_file(job_id, source)
            pipeline.inspect(job_id)
            pipeline.decompile(job_id)
            baseline = pipeline.build(job_id, baseline=True)
            metadata = device.select(job_id, state["serial"])
            core.update_job(job_id, test_mode="emulator", device=metadata, work_mode="auto", control_owner="agent")
            with core.lock(device.device_lock(state["serial"]), blocking=False):
                baseline_receipt = pipeline.runtime_test(job_id, baseline["apk"], state["serial"])
            before = device.screenshot(job_id, "before-validation", baseline["sha256"])
            before_text = ui_text(job_id)
            if "Before patch" not in before_text:
                raise ValueError("Baseline UI does not show expected text: " + before_text[:300])
            collaborative.set_mode(job_id, "assisted")
            collaborative.handoff(job_id, "user", "Synthetic handoff validation; preserve current app state")
            try:
                device.action(job_id, "key", ["home"])
                raise AssertionError("User turn failed to block mutation")
            except ValueError as error:
                assert "User owns" in str(error)
            observation = collaborative.observe(job_id, "handoff-read-only")
            assert not observation["errors"], observation
            assert "Before patch" in ui_text(job_id)
            collaborative.handoff(job_id, "agent", "Synthetic ready signal; continue from current screen")
            marker = instrumentation.inject(job_id, "Ldev/hermes/apklabtest/MainActivity;->onCreate(Landroid/os/Bundle;)V", "fixtureOnCreate")
            diagnostic = pipeline.build(job_id)
            assert diagnostic["diagnostic_only"]
            with core.lock(device.device_lock(state["serial"]), blocking=False):
                pipeline.runtime_test(job_id, diagnostic["apk"], state["serial"])
            marker_log = device.adb(["-s", state["serial"], "logcat", "-d", "-s", "APKLAB:I", "*:S"])
            assert marker["marker"] in marker_log, marker_log
            instrumentation.remove(job_id, marker["marker"])
            decoded = core.job_dir(job_id) / "decoded/apktool/smali/dev/hermes/apklabtest/MainActivity.smali"
            decoded.write_text(decoded.read_text().replace('"Before patch"', '"After patch"'))
            (core.job_dir(job_id) / "patches/CHANGELOG.md").write_text("Change fixture TextView label.\n")
            patched = pipeline.build(job_id)
            assert not patched["diagnostic_only"]
            with core.lock(device.device_lock(state["serial"]), blocking=False):
                patched_receipt = pipeline.runtime_test(job_id, patched["apk"], state["serial"])
            after = device.screenshot(job_id, "after-validation", patched["sha256"])
            after_text = ui_text(job_id)
            if "After patch" not in after_text or "Before patch" in after_text:
                raise ValueError("Patched UI does not show expected text: " + after_text[:300])
            spec_path = core.job_dir(job_id) / "tests/scenario.json"
            core.atomic_json(spec_path, {"scenario": "TextView changes from Before patch to After patch",
                                         "expected": "After patch visible", "observed": after_text,
                                         "verdict": "passed", "before": before["path"], "after": after["path"],
                                         "build_sha256": patched["sha256"]})
            scenario = device.evidence_result(job_id, spec_path)
            proof = {"time": time.time(), "passed": True, "serial": state["serial"], "avd": state["avd"],
                     "human_turn_blocked_mutation": True, "observation_preserved_ui": True,
                     "diagnostic_marker_seen_in_logcat": True, "final_has_no_markers": True,
                     "baseline_launched": baseline_receipt["process_alive"],
                     "patched_launched": patched_receipt["process_alive"],
                     "before_ui": before_text, "after_ui": after_text,
                     "before_png_sha256": before["image_sha256"], "after_png_sha256": after["image_sha256"],
                     "scenario_verdict": scenario["verdict"], "screenshot_size": [after["width"], after["height"]]}
            if not proof["baseline_launched"] or not proof["patched_launched"]:
                raise ValueError("Fixture process did not stay alive after launch")
            core.atomic_json(args.output, proof)
            print(json.dumps(proof, ensure_ascii=False, indent=2))
    finally:
        try:
            device.adb(["-s", emulator.SERIAL, "uninstall", "dev.hermes.apklabtest"], timeout=30)
        except (ValueError, OSError, subprocess.TimeoutExpired):
            pass
        if previous is None:
            os.environ.pop("APK_LAB_WORKSPACE", None)
        else:
            os.environ["APK_LAB_WORKSPACE"] = previous
        print("Emulator cleanup:", emulator.stop())


if __name__ == "__main__":
    main()
