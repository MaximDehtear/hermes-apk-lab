#!/usr/bin/env python3
"""Bind a checkout to Hermes; preserve unrelated Hermes settings and existing work."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from apk_lab.core import atomic_json
from apk_lab.server import validate_base_url


def main():
    saved_path = PROJECT / "config.local.json"
    saved = json.loads(saved_path.read_text()) if saved_path.exists() else {}
    p = argparse.ArgumentParser()
    p.add_argument("--hermes-home", default=os.environ.get("HERMES_HOME", saved.get("hermes_home", str(Path.home() / ".hermes"))))
    p.add_argument("--workspace", default=saved.get("workspace"), help="Hermes terminal.cwd; auto-detect when omitted")
    p.add_argument("--port", type=int, default=saved.get("port", 9099))
    p.add_argument("--exposure", choices=["direct", "local", "lan"], default=saved.get("exposure", "direct"))
    p.add_argument("--public-base-url", help="Externally reachable origin, e.g. http://your-host:9099")
    p.add_argument("--replace-existing", action="store_true")
    a = p.parse_args()
    if not 1 <= a.port <= 65535:
        raise SystemExit("Port must be between 1 and 65535")
    home = Path(a.hermes_home).expanduser().resolve()
    workspace = a.workspace
    if (home / "config.yaml").is_file():
        try:
            import yaml
            settings = yaml.safe_load((home / "config.yaml").read_text()) or {}
        except ImportError:
            raise SystemExit("PyYAML is required to validate Hermes config; install python3-yaml or PyYAML in your Python environment")
        if settings.get("terminal", {}).get("backend", "local") != "local":
            raise SystemExit("This installation requires Hermes terminal.backend=local")
        workspace = workspace or settings.get("terminal", {}).get("cwd")
    else:
        raise SystemExit("Hermes config.yaml is missing; install/configure Hermes first or pass --hermes-home")
    if not workspace or not Path(workspace).expanduser().is_absolute():
        raise SystemExit("An absolute Hermes workspace is required; use --workspace")
    workspace = Path(workspace).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    existing = PROJECT / "config.local.json"
    cfg = json.loads(existing.read_text()) if existing.exists() else {}
    cfg.update(workspace=str(workspace), hermes_home=str(home), port=a.port, exposure=a.exposure)
    if a.public_base_url is not None:
        cfg["public_base_url"] = validate_base_url(a.public_base_url)
    cfg.setdefault("public_base_url", "")
    cfg.setdefault("android_sdk", str(Path.home() / "Android/Sdk"))
    cfg.setdefault("max_upload_bytes", 4 * 1024**3)
    cfg.setdefault("chunk_bytes", 8 * 1024**2)
    cfg.setdefault("idle_seconds", 1800)
    cfg.setdefault("lifetime_seconds", 14400)
    atomic_json(existing, cfg)
    source = PROJECT / "skills" / "apk-reverse-engineering"
    dest = home / "skills" / "security" / "apk-reverse-engineering"
    dest.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if dest.is_symlink() and dest.resolve() == source:
        pass
    else:
        if dest.exists() or dest.is_symlink():
            if not a.replace_existing:
                raise SystemExit("Existing APK skill found; use --replace-existing to replace it")
            backup = home / "apk-lab-backups" / str(time.time_ns()) / "apk-reverse-engineering"
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dest), str(backup))
        dest.symlink_to(source, target_is_directory=True)
    launcher = PROJECT / "bin" / "apk-lab"
    launcher.chmod(0o755)
    bindir = Path.home() / ".local" / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    command = bindir / "apk-lab"
    if command.is_symlink():
        command.unlink()
    elif command.exists():
        raise SystemExit("~/.local/bin/apk-lab exists and is not a symlink; choose another command path")
    command.symlink_to(launcher)
    guide = workspace / "AGENTS.md"
    text = guide.read_text() if guide.exists() else ""
    begin, end = "<!-- hermes-apk-lab:start -->", "<!-- hermes-apk-lab:end -->"
    block = f"""{begin}
## APK investigations

Support Russian and English requests equally. Ask questions, report results and
interpret ready/resume/mode choices in the user's language. English documentation
does not require English input. For APK analysis/reverse engineering/modification/patching, load the
`security/apk-reverse-engineering` skill. Use `{launcher}` as the controller.
All uploaded APKs, decompilation, reports, patches and screenshots belong under
`{workspace / 'apk-lab'}`. The toolchain is in `{PROJECT / 'toolchain'}`.
Large files use the temporary upload service on {"127.0.0.1" if a.exposure == "local" else "0.0.0.0"}:{a.port}, directly, without
third-party tunnels. Use public_base_url for internet links; if unset, the detected
LAN address is not proof of internet access. Start on demand and stop when unused.
For every new APK run apk-lab open --goal ... --format telegram. Copy the complete
URL line, including #job=...&token=..., into the Telegram answer. For an existing
job run apk-lab link JOB --format telegram and send its newly rotated full URL.
A bare host:port is not an upload link.
Ask which test target to use: physical phone, managed Android emulator, or no
runtime testing. Persist the answer with apk-lab test-target JOB; never assume.
Also ask work-mode auto/assisted/manual independently. Persist it before device
mutations. Use handoff JOB user/agent to preserve turn ownership. On user-ready,
observe the current UI/logs without install-test, relaunch or resetting the app.
Keep the emulator running during a pending human handoff. Save demonstrated steps
and symbol aliases with remember; load knowledge when resuming the same APK.
For a chosen Android target use capture -> vision_analyze -> one action -> capture.
Publish before/after screenshots alongside the APK.
For emulator testing use scripts/setup_emulator.py when needed; the AVD and
screenshots live in this Hermes workspace. finish JOB stops it after the final job.
After decompile use recon JOB, then xrefs JOB with exact smali descriptors to trace
the requested behavior. Use native JOB lib/ABI/name.so --decompile for C/C++.
Use reversible instrument markers for diagnostics, remove them before final build.
Cite source paths/methods and runtime evidence; distinguish
facts, hypotheses and unknowns. Use the skill report template for delivery.
Resume saved job state; never mark a patch verified merely because it compiled.
{end}"""
    if begin in text and end in text:
        text = text[:text.index(begin)] + block + text[text.index(end) + len(end):]
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    guide.write_text(text)
    (workspace / "apk-lab").mkdir(mode=0o700, exist_ok=True)
    print(json.dumps({"installed": True, "project": str(PROJECT), "workspace": str(workspace),
                      "skill": str(dest), "launcher": str(command), "old_skill_backup": str(backup) if backup else None}, indent=2))


if __name__ == "__main__":
    main()
