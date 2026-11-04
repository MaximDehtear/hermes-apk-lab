"""Evidence-oriented static reconnaissance; candidates are not runtime findings."""
import json
import re
import time
import xml.etree.ElementTree as ET

from .core import atomic_json, event, inside, job_dir, lock, read_json, sha256
from .pipeline import input_apk

ANDROID = "{http://schemas.android.com/apk/res/android}"


def source_files(job_id):
    base = job_dir(job_id) / "decoded" / "apktool"
    if not base.is_dir():
        raise ValueError("Run decompile first")
    for folder in sorted(base.glob("smali*")):
        if folder.is_dir():
            for path in sorted(folder.rglob("*.smali")):
                yield inside(path, base)


def recon(job_id):
    p = job_dir(job_id)
    with lock(p / ".operation.lock", blocking=False):
        apk = input_apk(job_id)
        manifest = inside(p / "decoded/apktool/AndroidManifest.xml", p)
        if not manifest.is_file():
            raise ValueError("Run decompile first")
        try:
            tree = ET.parse(manifest).getroot()
        except ET.ParseError as exc:
            raise ValueError("Invalid decoded manifest: " + str(exc)) from exc
        app = tree.find("application")
        components = []
        for node in app if app is not None else []:
            if node.tag not in {"activity", "activity-alias", "service", "receiver", "provider"}:
                continue
            attrs = {k.removeprefix(ANDROID): v for k, v in node.attrib.items()}
            components.append({"type": node.tag, "attributes": attrs,
                               "exported_resolution": attrs.get("exported", "implicit: resolve by component/API/targetSdk"),
                               "intent_filters": [{"actions": [x.get(ANDROID + "name") for x in f.findall("action")],
                                                   "categories": [x.get(ANDROID + "name") for x in f.findall("category")],
                                                   "data": [{k.removeprefix(ANDROID): v for k, v in x.attrib.items()} for x in f.findall("data")]}
                                                  for f in node.findall("intent-filter")]})
        files = 0
        methods = 0
        native_methods = []
        for path in source_files(job_id):
            files += 1
            with path.open(errors="replace") as handle:
                for number, line in enumerate(handle, 1):
                    if line.lstrip().startswith(".method "):
                        methods += 1
                        if " native " in line and len(native_methods) < 200:
                            native_methods.append({"file": str(path.relative_to(p)), "line": number, "declaration": line.strip()})
        inventory = read_json(p / "inventory.json", {})
        result = {"schema_version": 1, "created_at": time.time(), "input_sha256": sha256(apk),
                  "manifest": {"file": str(manifest.relative_to(p)), "sha256": sha256(manifest),
                               "package": tree.get("package"),
                               "application": {k.removeprefix(ANDROID): v for k, v in app.attrib.items()} if app is not None else {},
                               "permissions": [n.get(ANDROID + "name") for n in tree if n.tag.startswith("uses-permission")],
                               "components": components},
                  "smali_files": files, "methods": methods, "native_method_samples": native_methods,
                  "native_libraries": inventory.get("native_libraries", []),
                  "framework_hints": inventory.get("framework_hints", {}),
                  "decompile": read_json(p / "analysis/decompile.json", {}),
                  "limitations": ["Static inventory of the current decoded tree; not proof of reachability or runtime behavior.",
                                  "Native declarations sampled up to 200; dynamic loading/reflection and server behavior require separate investigation."]}
        output = p / "analysis/recon.json"
        atomic_json(output, result)
        event(job_id, "recon", path=str(output), input_sha256=result["input_sha256"])
        return {"path": str(output), "components": len(components), "smali_files": files,
                "methods": methods, "limitations": result["limitations"]}


def xrefs(job_id, symbol):
    if not re.fullmatch(r"L[^;\s]+;->[^\s]+", symbol):
        raise ValueError("Use a full smali method/field reference: Lpkg/Class;->method()V or Lpkg/Class;->flag:Z")
    p = job_dir(job_id)
    with lock(p / ".operation.lock", blocking=False):
        apk = input_apk(job_id)
        output = p / "analysis" / ("xrefs-" + str(time.time_ns()) + ".jsonl")
        count = 0
        samples = []
        scanned = 0
        with output.open("w") as out:
            for path in source_files(job_id):
                scanned += 1
                owner, method = None, None
                digest = None
                with path.open(errors="replace") as handle:
                    for number, raw in enumerate(handle, 1):
                        line = raw.strip()
                        if line.startswith(".class "):
                            owner = line.split()[-1]
                        if line.startswith(".method "):
                            method = line[len(".method "):]
                        instruction = line.split("#", 1)[0].strip()
                        if method and instruction.split() and instruction.split()[-1] == symbol:
                            opcode = instruction.split()[0]
                            if opcode.startswith(("invoke-", "iget", "iput", "sget", "sput")):
                                digest = digest or sha256(path)
                                kind = "call" if opcode.startswith("invoke-") else "write" if opcode.startswith(("iput", "sput")) else "read"
                                item = {"file": str(path.relative_to(p)), "source_sha256": digest, "line": number,
                                        "class": owner, "method": method, "kind": kind, "instruction": instruction}
                                out.write(json.dumps(item) + "\n")
                                count += 1
                                if len(samples) < 20:
                                    samples.append(item)
                        if line.startswith(".end method"):
                            method = None
        event(job_id, "xrefs", symbol=symbol, count=count, path=str(output))
        result = {"schema_version": 1, "created_at": time.time(), "input_sha256": sha256(apk),
                  "symbol": symbol, "count": count, "files_scanned": scanned, "path": str(output), "samples": samples,
                "limitations": "Exact static instruction references only; no virtual dispatch resolution, reflection, JNI or dynamic-code coverage. Zero matches does not prove absence."}
        atomic_json(output.with_suffix(".meta.json"), result)
        return result
