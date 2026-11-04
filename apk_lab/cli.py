from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from . import collaborative, core, device, emulator, instrumentation, native, pipeline, research, server


def delivery_context():
    platform = os.environ.get("HERMES_SESSION_PLATFORM")
    chat = os.environ.get("HERMES_SESSION_CHAT_ID")
    thread = os.environ.get("HERMES_SESSION_THREAD_ID")
    if platform and chat:
        return platform + ":" + chat + (":" + thread if thread else "")
    return None


def stop_unused_emulator():
    """Keep a shared AVD alive until its last active job finishes or changes target."""
    users = [j["id"] for j in core.list_jobs()
             if j.get("test_mode") == "emulator" and j["phase"] != "done"]
    return {"kept_for_jobs": users} if users else emulator.stop()


def parser():
    p = argparse.ArgumentParser(description="Hermes APK Lab: persistent investigations in the Hermes workspace")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    sub.add_parser("list")
    n = sub.add_parser("new")
    n.add_argument("--goal", required=True)
    n.add_argument("--delivery")
    o = sub.add_parser("open")
    o.add_argument("--goal", required=True)
    o.add_argument("--delivery")
    o.add_argument("--exposure", choices=["direct", "local", "lan"])
    o.add_argument("--port", type=int)
    o.add_argument("--format", choices=["json", "telegram"], default="json")
    for cmd in ["status", "inspect", "decompile", "recon", "pause", "resume"]:
        s = sub.add_parser(cmd)
        s.add_argument("job")
    x = sub.add_parser("xrefs")
    x.add_argument("job")
    x.add_argument("symbol")
    trace = sub.add_parser("instrument")
    trace.add_argument("job")
    trace.add_argument("--method", required=True)
    trace.add_argument("--label", required=True)
    trace.add_argument("--at", choices=["entry", "returns", "line"], default="entry")
    trace.add_argument("--line", type=int)
    trace.add_argument("--source-sha256")
    trace = sub.add_parser("uninstrument")
    trace.add_argument("job")
    trace.add_argument("marker")
    nat = sub.add_parser("native")
    nat.add_argument("job")
    nat.add_argument("library", help="Exact lib/ABI/name.so member from inventory")
    nat.add_argument("--decompile", action="store_true")
    nat.add_argument("--function", default="*", help="Name substring or exact Ghidra entry address; * selects the first functions")
    nat.add_argument("--limit", type=int, default=25)
    mode = sub.add_parser("work-mode")
    mode.add_argument("job")
    mode.add_argument("mode", choices=["auto", "assisted", "manual"])
    turn = sub.add_parser("handoff")
    turn.add_argument("job")
    turn.add_argument("owner", choices=["user", "agent"])
    turn.add_argument("--note", required=True)
    observation = sub.add_parser("observe")
    observation.add_argument("job")
    observation.add_argument("--label", required=True)
    observation.add_argument("--build-sha256", help="Declared installed build identity; verify separately")
    memory = sub.add_parser("remember")
    memory.add_argument("job")
    memory.add_argument("file")
    memory = sub.add_parser("knowledge")
    memory.add_argument("job")
    i = sub.add_parser("import")
    i.add_argument("job")
    i.add_argument("file")
    w = sub.add_parser("wait-upload")
    w.add_argument("job")
    w.add_argument("--timeout", type=int, default=14400)
    l = sub.add_parser("link")
    l.add_argument("job")
    l.add_argument("--exposure", choices=["direct", "local", "lan"])
    l.add_argument("--port", type=int)
    l.add_argument("--format", choices=["json", "telegram"], default="json")
    s = sub.add_parser("server")
    s.add_argument("action", choices=["status", "stop", "start"])
    s.add_argument("--exposure", choices=["direct", "local", "lan"])
    s.add_argument("--port", type=int)
    serve = sub.add_parser("serve", help=argparse.SUPPRESS)
    serve.add_argument("--bind", required=True)
    serve.add_argument("--port", type=int, required=True)
    serve.add_argument("--exposure", required=True)
    b = sub.add_parser("build")
    b.add_argument("job")
    b.add_argument("--baseline", action="store_true")
    pub = sub.add_parser("publish")
    pub.add_argument("job")
    pub.add_argument("file")
    pub.add_argument("--label")
    note = sub.add_parser("checkpoint")
    note.add_argument("job")
    note.add_argument("--next", required=True)
    note.add_argument("--phase", choices=["analyzing", "patching", "blocked", "analyzed", "built"])
    note.add_argument("--blocker")
    finish = sub.add_parser("finish")
    finish.add_argument("job")
    finish.add_argument("--report", required=True)
    finish.add_argument("--kind", choices=["analysis", "patch"], default="analysis")
    target = sub.add_parser("test-target", help="Persist the user's choice of phone, emulator or no testing")
    target.add_argument("job")
    target.add_argument("mode", choices=["phone", "emulator", "none"])
    target.add_argument("--window", action="store_true", help="Show managed emulator on the host desktop")
    target.add_argument("--serial", help="Required for a physical phone")
    emu = sub.add_parser("emulator")
    emu.add_argument("action", choices=["status", "start", "stop"])
    emu.add_argument("--window", action="store_true")
    d = sub.add_parser("device")
    ds = d.add_subparsers(dest="device_command", required=True)
    ds.add_parser("list")
    connect = ds.add_parser("connect")
    connect.add_argument("address")
    select = ds.add_parser("select")
    select.add_argument("job")
    select.add_argument("serial")
    for cmd in ["hierarchy", "logcat"]:
        x = ds.add_parser(cmd)
        x.add_argument("job")
    shot = ds.add_parser("screenshot")
    shot.add_argument("job")
    shot.add_argument("--label", required=True)
    shot.add_argument("--build-sha256")
    act = ds.add_parser("action")
    act.add_argument("job")
    act.add_argument("kind", choices=["tap", "swipe", "key", "text", "launch"])
    act.add_argument("values", nargs="+")
    test = ds.add_parser("install-test")
    test.add_argument("job")
    test.add_argument("apk")
    evidence = ds.add_parser("evidence")
    evidence.add_argument("job")
    evidence.add_argument("json_file")
    return p


def main(argv=None):
    os.umask(0o077)
    a = parser().parse_args(argv)
    try:
        c = a.command
        if c == "doctor":
            result = pipeline.doctor()
        elif c == "new":
            result = core.create_job(a.goal, a.delivery or delivery_context())
        elif c == "open":
            job = core.create_job(a.goal, a.delivery or delivery_context())
            # Persist job before starting the server, so failed network startup never loses the goal.
            try:
                transfer = server.link(job["id"], a.exposure, a.port)
                result = {"job_id": job["id"], "url": transfer["url"], "transfer": transfer,
                          "directory": job["directory"], "goal": job["goal"]}
            except ValueError as e:
                raise ValueError(f"Job {job['id']} was created; retry link for that job. {e}") from e
        elif c == "list":
            result = [{k: j[k] for k in ["id", "goal", "phase", "directory", "updated_at"]} for j in core.list_jobs()]
        elif c == "status":
            result = core.get_job(a.job)
        elif c == "import":
            result = pipeline.import_file(a.job, a.file)
        elif c == "wait-upload":
            started = core.now()
            while True:
                job = core.get_job(a.job)
                if job["input"]:
                    result = {"job": job, "instruction": "Upload completed. Resume the APK skill NOW: inspect, decompile, investigate the saved goal; checkpoint evidence and finish with a report. Do not create another upload job."}
                    break
                if job["phase"] == "paused":
                    raise ValueError("Job paused")
                if core.now() - started >= a.timeout:
                    raise ValueError("Upload wait expired; input and job are preserved. Reopen link and wait again.")
                time.sleep(1)
        elif c == "link":
            result = server.link(a.job, a.exposure, a.port)
        elif c == "server":
            result = server.server_status() if a.action == "status" else server.stop_server() if a.action == "stop" else server.start_server(a.exposure, a.port)
        elif c == "serve":
            server.serve(a.bind, a.port, a.exposure)
            return 0
        elif c == "inspect":
            result = pipeline.inspect(a.job)
        elif c == "decompile":
            result = pipeline.decompile(a.job)
        elif c == "recon":
            result = research.recon(a.job)
        elif c == "xrefs":
            result = research.xrefs(a.job, a.symbol)
        elif c == "build":
            result = pipeline.build(a.job, a.baseline)
        elif c == "publish":
            result = core.publish(a.job, a.file, a.label)
        elif c == "pause":
            job = core.get_job(a.job)
            result = core.update_job(a.job, paused_from=job["phase"], phase="paused", next_action="Waiting for user to resume")
        elif c == "resume":
            job = core.get_job(a.job)
            phase = "ready" if job["input"] else "waiting_upload"
            result = core.update_job(a.job, phase=phase, next_action="Read saved evidence and continue the goal without repeating completed steps")
        elif c == "checkpoint":
            changes = {"next_action": a.next}
            if a.phase:
                changes["phase"] = a.phase
            if a.blocker:
                changes["blockers"] = [a.blocker]
            result = core.update_job(a.job, **changes)
            core.event(a.job, "checkpoint", **changes)
        elif c == "finish":
            with core.lock(core.job_dir(a.job) / ".collaboration.lock"), core.lock(core.job_dir(a.job) / ".operation.lock", blocking=False):
                job = core.get_job(a.job)
                if job.get("control_owner") == "user":
                    raise ValueError("User owns the turn; hand control back before finishing and stopping the emulator")
                report = core.inside(a.report, core.job_dir(a.job) / "analysis")
                if not report.is_file() or report.stat().st_size < 100:
                    raise ValueError("Write a substantive evidence-backed report under analysis/ first")
                if a.kind == "patch":
                    v = job.get("verification", {})
                    if not v.get("apk") or v.get("baseline"):
                        raise ValueError("No verified patched build exists")
                    verified = pipeline.verified_build(a.job, v["apk"])
                    if verified.get("diagnostic_only"):
                        raise ValueError("Diagnostic markers remain; remove them and rebuild the final artifact. Publish diagnostic builds explicitly with a diagnostic label.")
                    if verified["sha256"] != v.get("sha256"):
                        raise ValueError("Job verification is stale; rebuild before delivery")
                    receipts = [core.read_json(p, {}) for p in (core.job_dir(a.job) / "tests").glob("scenario-*.json")]
                    passed = any(r.get("verdict") == "passed" and r.get("build_sha256") == v["sha256"] for r in receipts)
                    untested = job.get("test_mode") == "none"
                    if not passed and not untested:
                        raise ValueError("No passed before/after behavior evidence for the current patched APK. Publish an unverified build if requested, but do not mark the patch done.")
                    core.publish(a.job, v["apk"], "Patched APK" if passed else "Patched APK (not runtime-tested)")
                artifact = core.publish(a.job, report, "Analysis report")
                result = core.update_job(a.job, phase="done", next_action="Deliver published artifacts and explain verification status",
                                         report=artifact["path"], verification_status=("passed" if passed else "untested") if a.kind == "patch" else "analysis_only")
                if job.get("test_mode") == "emulator":
                    result["emulator_cleanup"] = stop_unused_emulator()
        elif c == "instrument":
            result = instrumentation.inject(a.job, a.method, a.label, a.at, a.line, a.source_sha256)
        elif c == "uninstrument":
            result = instrumentation.remove(a.job, a.marker)
        elif c == "native":
            result = native.analyze(a.job, a.library, a.decompile, a.function, a.limit)
        elif c == "work-mode":
            result = collaborative.set_mode(a.job, a.mode)
        elif c == "handoff":
            result = collaborative.handoff(a.job, a.owner, a.note)
        elif c == "observe":
            result = collaborative.observe(a.job, a.label, a.build_sha256)
        elif c == "remember":
            result = collaborative.remember(a.job, a.file)
        elif c == "knowledge":
            result = collaborative.memories(a.job)
        elif c == "test-target":
            if a.window and a.mode != "emulator":
                raise ValueError("--window is only for the managed emulator")
            if a.mode == "phone":
                if not a.serial or a.serial.startswith("emulator-"):
                    raise ValueError("Phone mode requires the connected physical phone serial (--serial)")
                metadata = device.select(a.job, a.serial)
                result = core.update_job(a.job, test_mode="phone", device=metadata)
            elif a.mode == "emulator":
                if a.serial:
                    raise ValueError("Emulator mode selects the managed virtual device automatically")
                state = emulator.start(window=True) if a.window else emulator.start()
                metadata = device.select(a.job, state["serial"])
                result = core.update_job(a.job, test_mode="emulator", device=metadata)
            else:
                if a.serial:
                    raise ValueError("No serial is used when testing is skipped")
                result = core.update_job(a.job, test_mode="none", device={}, next_action="Continue analysis/build; report runtime behavior as untested")
            core.event(a.job, "test_target", mode=a.mode, serial=result.get("device", {}).get("serial"))
            if a.mode != "emulator":
                result["emulator_cleanup"] = stop_unused_emulator()
        elif c == "emulator":
            if a.window and a.action != "start":
                raise ValueError("--window applies to emulator start")
            result = emulator.status() if a.action == "status" else emulator.start(window=a.window) if a.action == "start" else emulator.stop()
        elif c == "device":
            dc = a.device_command
            if dc == "list": result = device.devices()
            elif dc == "connect": result = device.connect(a.address)
            elif dc == "select":
                metadata = device.select(a.job, a.serial)
                result = core.update_job(a.job, test_mode="emulator" if a.serial.startswith("emulator-") else "phone", device=metadata)
                if result["test_mode"] == "phone":
                    result["emulator_cleanup"] = stop_unused_emulator()
            elif dc == "screenshot": result = device.screenshot(a.job, a.label, a.build_sha256)
            elif dc == "hierarchy": result = device.hierarchy(a.job)
            elif dc == "logcat": result = device.capture_logcat(a.job)
            elif dc == "action": result = device.action(a.job, a.kind, a.values)
            elif dc == "install-test":
                with core.lock(device.device_lock(device.selected(a.job)), blocking=False):
                    result = pipeline.runtime_test(a.job, a.apk, device.selected(a.job))
            elif dc == "evidence": result = device.evidence_result(a.job, a.json_file)
        if c in {"open", "link"} and a.format == "telegram":
            transfer = result["transfer"] if c == "open" else result
            print("Job: " + transfer["job_id"])
            print("Complete upload and results download link:")
            print(transfer["url"])
            if not transfer["public_address_configured"]:
                print("The address was detected for the local network; internet access has not been verified.")
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, TimeoutError, subprocess.SubprocessError, zipfile.BadZipFile) as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
